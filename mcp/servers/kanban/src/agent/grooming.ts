/**
 * Grooming chat (PLAN.md §4, requirements §5): an interactive Pi session per
 * idea, with tools + skills (bash for web fetch/curl, read for images/files,
 * harness skills, LiteLLM-proxy MCP tools) and an ephemeral scratch dir.
 *
 * - Persisted Pi session per idea at <sessions>/groom-<ideaId>.jsonl —
 *   SessionManager.open semantics (stable path): first turn creates the
 *   file, later turns (including after a server restart) reopen it for
 *   continuity (SDK_NOTES.md §2/§6).
 * - Seeded with the idea (first user message) + project context (system
 *   prompt), at the GROOM_THINKING level (AgentRuntime role `groom`).
 * - State machine:
 *     idea ──startGrooming──► grooming ──accept──► icebox
 *                               │ cancel → idea (chat discarded)
 *                               │ reGroom → grooming (fresh session)
 *                               │ discard → discarded (soft-deleted)
 * - Accept: a final prompt makes the session emit the structured spec as
 *   JSON (goal/steps/acceptance/kind/publish_targets/notes) plus
 *   `depends_on` — LLM-identified among the project's current icebox items.
 * - Usage: every assistant message is recorded (role `groom`, taskId null).
 *
 * The Pi session is created through an injectable factory so tests run the
 * full state machine against a mocked session (no network, no model).
 */
import { existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { z } from "zod";
import { eq, and } from "drizzle-orm";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { AssistantMessage, UserMessage } from "@earendil-works/pi-ai";
import type { KanbanConfig } from "../config.js";
import type { ThinkingLevel } from "../config.js";
import { ideas, projects, TASK_KINDS, type IdeaRow, type IdeaSpec, type IdeaState } from "../db/schema.js";
import { ServiceError, type Db } from "../services/common.js";
import { recordUsage } from "../services/usage.js";
import type { AgentRuntime, AgentSessionHandle, UsageSample } from "./sessions.js";

// ---------------------------------------------------------------------------
// Session abstraction (mockable)
// ---------------------------------------------------------------------------

/**
 * Turn-watchdog stall defaults per grooming thinking level (ms).
 * xhigh turns can be legitimately quiet for 10+ min (deep research / long
 * web fetches), so the flat 15-min default was close to the edge — the
 * threshold scales with the level instead. Override for all levels with
 * the GROOM_TURN_STALL_MINUTES env var (minutes).
 */
export const GROOM_STALL_MS_BY_LEVEL: Partial<Record<ThinkingLevel, number>> = {
  off: 5 * 60_000,
  minimal: 5 * 60_000,
  low: 10 * 60_000,
  medium: 15 * 60_000,
  high: 20 * 60_000,
  xhigh: 30 * 60_000,
  max: 30 * 60_000,
};

/** One grooming chat message for the GUI. */
export interface GroomMessage {
  role: "user" | "assistant";
  text: string;
}

/**
 * The subset of Pi's AgentSession the grooming manager needs. AgentSession
 * satisfies this structurally; tests provide a mock.
 */
export interface GroomSessionLike {
  /** Run one turn; resolves when the turn settles. */
  prompt(text: string): Promise<void>;
  /** Full transcript (user/assistant messages, in order). */
  readonly messages: AgentMessage[];
  /** Path of the persisted session file (if any). */
  readonly sessionFile?: string;
  /** Stop the current turn (best effort; used by the turn watchdog). */
  abort?(): void;
  dispose(): void;
}

export interface GroomSessionCreateOptions {
  ideaId: number;
  /** Scratch working directory (/workspace/groom-<ideaId>). */
  cwd: string;
  /** Grooming system prompt (role + project context + idea). */
  systemPrompt: string;
  /**
   * Stable session file path (<sessions>/groom-<ideaId>.jsonl). Opened with
   * SessionManager.open semantics: resume if the file exists, create if not.
   */
  sessionFile: string;
  /**
   * Owner (USER_KEYS name) the session's LLM calls bill to (Phase 2):
   * the idea's owner; ''/unmapped → the service key.
   */
  owner?: string;
  /** Called with usage for each completed assistant message. */
  onUsage?: (usage: UsageSample) => void;
  /**
   * Called on live streaming activity (message_update / tool events) so the
   * turn watchdog can distinguish a long but live turn from a stuck one.
   */
  onActivity?: (kind: string) => void;
}

export type GroomSessionFactory = (opts: GroomSessionCreateOptions) => Promise<GroomSessionLike>;

// ---------------------------------------------------------------------------
// Spec finalization (Accept)
// ---------------------------------------------------------------------------

const groomSpecSchema = z.object({
  goal: z.string().min(1),
  steps: z.array(z.string()),
  acceptance: z.array(z.string()),
  kind: z.enum(TASK_KINDS),
  publish_targets: z.union([z.array(z.string()), z.null()]).optional(),
  notes: z.union([z.string(), z.null()]).optional(),
  depends_on: z.array(z.number().int().positive()),
});

/**
 * Parse the finalized spec JSON out of an assistant message. Tolerates code
 * fences and surrounding prose (first `{` … last `}`). Throws ServiceError(400)
 * when the payload is missing/invalid, and 400 when a depends_on id is not
 * one of the given icebox item ids (or is the idea itself).
 */
export function parseGroomSpec(
  assistantText: string,
  iceboxIds: Set<number>,
  selfId: number,
): { spec: IdeaSpec; dependsOn: number[] } {
  const start = assistantText.indexOf("{");
  const end = assistantText.lastIndexOf("}");
  if (start === -1 || end === -1 || end < start) {
    throw new ServiceError(400, "grooming session did not return a spec JSON object — try Accept again");
  }
  let raw: unknown;
  try {
    raw = JSON.parse(assistantText.slice(start, end + 1));
  } catch (err) {
    throw new ServiceError(400, `grooming session returned invalid spec JSON: ${(err as Error).message}`);
  }
  const parsed = groomSpecSchema.safeParse(raw);
  if (!parsed.success) {
    const issue = parsed.error.issues[0] ?? { path: [], message: "invalid spec" };
    throw new ServiceError(
      400,
      `grooming session returned an incomplete spec (${issue.path.join(".") || "spec"}: ${issue.message}) — try Accept again`,
    );
  }
  const v = parsed.data;
  for (const dep of v.depends_on) {
    if (dep === selfId) {
      throw new ServiceError(400, `spec depends_on references the idea itself (${selfId}) — try Accept again`);
    }
    if (!iceboxIds.has(dep)) {
      throw new ServiceError(
        400,
        `spec depends_on references idea ${dep}, which is not a current icebox item — try Accept again`,
      );
    }
  }
  return {
    spec: {
      goal: v.goal,
      steps: v.steps,
      acceptance: v.acceptance,
      kind: v.kind,
      ...(v.publish_targets !== undefined && v.publish_targets !== null ? { publish_targets: v.publish_targets } : {}),
      ...(v.notes !== undefined && v.notes !== null ? { notes: v.notes } : {}),
    },
    dependsOn: v.depends_on,
  };
}

/** Final prompt sent on Accept (PLAN.md §4: structured spec + deps). */
export function buildFinalizePrompt(iceboxItems: Array<{ id: number; text: string }>): string {
  const list =
    iceboxItems.length > 0
      ? iceboxItems.map((i) => `- id ${i.id}: ${i.text}`).join("\n")
      : "(none)";
  return [
    "FINALIZE NOW. Produce the structured spec for this idea.",
    "Respond with ONLY a JSON object (no markdown, no code fences, no commentary) with exactly these keys:",
    '{',
    '  "goal": string,                    // one-paragraph task goal',
    '  "steps": string[],                 // ordered implementation steps',
    '  "acceptance": string[],            // verifiable acceptance criteria',
    '  "kind": "code" | "blog" | "media" | "other",',
    '  "publish_targets": string[] | null,// FINAL output location(s) only (project repo / blog path / media dir or file on the host); NEVER your scratch directory; null if none',
    '  "notes": string | null,            // extra context for the executing agent; null if none',
    '  "depends_on": number[]             // ids of the icebox items below this idea depends on; [] if none',
    "}",
    "",
    "Current icebox items (the only valid depends_on ids):",
    list,
  ].join("\n");
}

// ---------------------------------------------------------------------------
// Transcript helpers
// ---------------------------------------------------------------------------

/** Extract the displayable text of a transcript message ("" when none). */
export function extractMessageText(m: AgentMessage): string {
  if (m.role === "user") {
    const c = (m as UserMessage).content;
    if (typeof c === "string") return c;
    return c
      .filter((p): p is { type: "text"; text: string } => p.type === "text")
      .map((p) => p.text)
      .join("");
  }
  if (m.role === "assistant") {
    return (m as AssistantMessage).content
      .filter((p): p is { type: "text"; text: string } => p.type === "text")
      .map((p) => p.text)
      .join("\n");
  }
  return "";
}

/** Normalize a full transcript to GUI chat messages (skips empty/tool-only). */
export function transcriptToGroomMessages(messages: AgentMessage[]): GroomMessage[] {
  const out: GroomMessage[] = [];
  for (const m of messages) {
    const text = extractMessageText(m);
    if (text.trim() === "") continue;
    out.push({ role: m.role === "user" ? "user" : "assistant", text });
  }
  return out;
}

// ---------------------------------------------------------------------------
// Manager
// ---------------------------------------------------------------------------

export interface GroomingManagerOptions {
  db: Db;
  cfg: KanbanConfig;
  /**
   * Create/resume the Pi session for an idea. Defaults to wrapping an
   * AgentRuntime (role `groom`); tests inject a mock.
   */
  sessionFactory?: GroomSessionFactory;
  /** Agent runtime (required when sessionFactory is not given). */
  agent?: AgentRuntime;
  /** Scratch dir root (default: AI_KANBAN_WORKSPACE_DIR env, else /workspace). */
  workspaceRoot?: string;
  /** Session file dir (default: the agent runtime's sessions dir). */
  sessionsDir?: string;
  /**
   * Turn watchdog: a turn with no streaming activity for this long is
   * aborted and released. Defaults scale with the grooming thinking level
   * (GROOM_STALL_MS_BY_LEVEL — xhigh turns can be legitimately quiet for
   * 10+ min, so the flat 15-min default was close to the edge). Override
   * for all levels with the GROOM_TURN_STALL_MINUTES env var (minutes).
   */
  turnStallMs?: number;
  /** Watchdog tick interval (default 60s; tests use a short value). */
  watchdogIntervalMs?: number;
}

export class GroomingManager {
  readonly workspaceRoot: string;
  readonly sessionsDir: string;

  private readonly db: Db;
  private readonly cfg: KanbanConfig;
  private readonly factory: GroomSessionFactory;
  /** Active in-memory sessions, per idea. */
  private readonly active = new Map<number, GroomSessionLike>();
  /** In-flight session creation (dedupes concurrent ensureSession calls). */
  private readonly sessionPending = new Map<number, Promise<GroomSessionLike>>();
  /** Per-idea turn lock (one prompt in flight per session). */
  private readonly turns = new Map<number, Promise<unknown>>();
  /** In-flight turn count per idea (live "assistant is working" status). */
  private readonly inflight = new Map<number, number>();
  /** Start ts of the first in-flight turn per idea. */
  private readonly turnSince = new Map<number, number>();
  /** Label of the currently RUNNING turn per idea (seeding / chat / finalizing). */
  private readonly turnLabel = new Map<number, string>();
  /** Last streaming-activity ts per idea (turn watchdog). */
  private readonly lastActivity = new Map<number, number>();
  /**
   * Per-idea turn generation, bumped ONLY by the watchdog when it releases
   * a stuck turn. A stale finally-block (the stuck turn settling after the
   * release) becomes a no-op; normal queued turns share the generation and
   * decrement the in-flight count correctly.
   */
  private readonly turnGen = new Map<number, number>();
  private readonly turnStallMs: number;
  private watchdogTimer?: NodeJS.Timeout;

  constructor(opts: GroomingManagerOptions) {
    this.db = opts.db;
    this.cfg = opts.cfg;
    this.workspaceRoot = opts.workspaceRoot ?? process.env.AI_KANBAN_WORKSPACE_DIR ?? "/workspace";
    // Stall threshold: GROOM_TURN_STALL_MINUTES (minutes, all levels) wins;
    // otherwise the per-thinking-level default (xhigh is the most patient —
    // a deep grooming turn can be legitimately quiet for 10+ min).
    const stallEnv = Number(process.env.GROOM_TURN_STALL_MINUTES);
    const levelMs = GROOM_STALL_MS_BY_LEVEL[this.cfg.thinking.groom] ?? GROOM_STALL_MS_BY_LEVEL.medium!;
    this.turnStallMs =
      opts.turnStallMs ?? (Number.isFinite(stallEnv) && stallEnv > 0 ? stallEnv * 60_000 : levelMs);
    this.watchdogTimer = setInterval(() => this.watchTurns(), opts.watchdogIntervalMs ?? 60_000);
    this.watchdogTimer.unref?.();
    if (opts.sessionFactory) {
      this.factory = opts.sessionFactory;
      this.sessionsDir =
        opts.sessionsDir ?? opts.agent?.sessionsDir ?? path.join(process.env.AI_KANBAN_DATA_DIR ?? "/data", "sessions");
    } else if (opts.agent) {
      const agent = opts.agent;
      this.factory = (o) =>
        agent
          .createSession({
            role: "groom",
            cwd: o.cwd,
            systemPrompt: o.systemPrompt,
            sessionFile: o.sessionFile, // SessionManager.open semantics (stable path)
            owner: o.owner, // Phase 2: bill to the idea owner's key (else service key)
            onUsage: o.onUsage,
          })
          .then((h: AgentSessionHandle) => {
            // Live streaming activity for the turn watchdog (a long xhigh
            // turn emits message_update events continuously; a stuck one
            // emits nothing).
            if (o.onActivity) {
              const onActivity = o.onActivity;
              h.session.subscribe((event) => {
                if (
                  event.type === "message_update" ||
                  event.type === "message_end" ||
                  event.type === "tool_execution_start" ||
                  event.type === "tool_execution_end"
                ) {
                  onActivity(event.type);
                }
              });
            }
            return h.session as unknown as GroomSessionLike;
          });
      this.sessionsDir = opts.sessionsDir ?? agent.sessionsDir;
    } else {
      throw new Error("GroomingManager needs a sessionFactory or an AgentRuntime");
    }
  }

  // -- paths ---------------------------------------------------------------

  /** Ephemeral scratch dir for the grooming session (/workspace/groom-<id>). */
  scratchDir(ideaId: number): string {
    return path.join(this.workspaceRoot, `groom-${ideaId}`);
  }

  /** Stable persisted session file (<sessions>/groom-<id>.jsonl). */
  sessionFile(ideaId: number): string {
    return path.join(this.sessionsDir, `groom-${ideaId}.jsonl`);
  }

  // -- state machine -------------------------------------------------------

  /**
   * Start grooming an idea (idea → grooming): create the scratch dir, open
   * the (new) persisted session, and seed it with the idea text. Idempotent
   * when the idea is already grooming (resumes the session after a restart).
   *
   * `background: true` (read-only UI page load) returns as soon as the
   * state flip is persisted; the seed LLM turn runs in the background and
   * is visible via `turnStatus` + transcript polling. Default (MCP
   * `start_grooming`, tests) awaits the seed turn.
   */
  async startGrooming(ideaId: number, opts: { background?: boolean } = {}): Promise<IdeaRow> {
    const idea = await this.requireIdea(ideaId, ["idea", "grooming"]);
    if (idea.state === "grooming") {
      await this.ensureSeeded(idea, true); // resume; background re-seed if stuck-empty
      return idea;
    }
    mkdirSync(this.scratchDir(ideaId), { recursive: true });
    await this.setIdeaState(ideaId, "grooming");
    const updated = await this.getIdea(ideaId);
    if (opts.background) {
      // Fire-and-forget seed; a failed seed leaves the idea in grooming with
      // an empty transcript — the next page load retries (ensureSeeded).
      void this.ensureSeeded(updated, true).catch((err) => {
        console.error(`[grooming] seed failed for idea ${ideaId}:`, err);
      });
      return updated;
    }
    try {
      await this.ensureSeeded(updated, false); // create + seed (awaited)
    } catch (err) {
      // Keep the idea in grooming: the transcript is persisted, so the user
      // can continue the chat, re-accept, or cancel/re-groom from the page.
      // (Reverting to `idea` would drop the partial research work.)
      console.error(`[grooming] seed failed for idea ${ideaId}:`, err);
      throw this.wrapError(ideaId, "start grooming", err);
    }
    return updated;
  }

  /**
   * One chat turn (blocking): append the user message, run the turn, return
   * the new assistant message. Used by the MCP `groom_message` tool and
   * tests — the client relays the reply to the user in its own conversation.
   */
  async sendGroomMessage(ideaId: number, text: string): Promise<GroomMessage> {
    const t = (text ?? "").trim();
    if (t === "") throw new ServiceError(400, "message is required");
    const idea = await this.requireIdea(ideaId, ["grooming"]);
    const session = await this.ensureSeeded(idea, true);
    const before = session.messages.length;
    await this.withTurn(ideaId, "chat", () => session.prompt(t));
    const reply = lastAssistantText(session.messages.slice(before));
    if (reply === undefined) {
      throw new ServiceError(500, `grooming session produced no assistant reply for idea ${ideaId}`);
    }
    return { role: "assistant", text: reply };
  }

  /** Live status for the grooming viewer (is a turn in flight for this idea?). */
  turnStatus(ideaId: number): { active: boolean; since: number | null; label: string | null } {
    const since = this.turnSince.get(ideaId);
    return { active: since !== undefined, since: since ?? null, label: this.turnLabel.get(ideaId) ?? null };
  }

  /**
   * Accept (grooming → icebox): the final prompt makes the session emit the
   * structured spec JSON + depends_on (LLM-identified among current icebox
   * items); the idea is finalized with the spec.
   */
  async acceptGrooming(ideaId: number): Promise<IdeaRow> {
    const idea = await this.requireIdea(ideaId, ["grooming"]);
    const icebox = await dbSelectIceboxItems(this.db, idea.projectId);
    const iceboxIds = new Set(icebox.map((i) => i.id));
    const session = await this.ensureSeeded(idea, true);
    const before = session.messages.length;
    await this.withTurn(ideaId, "finalizing spec", () => session.prompt(buildFinalizePrompt(icebox)));
    const reply = lastAssistantText(session.messages.slice(before));
    if (reply === undefined) {
      throw new ServiceError(500, `grooming session produced no assistant reply for idea ${ideaId}`);
    }
    const { spec, dependsOn } = parseGroomSpec(reply, iceboxIds, ideaId);
    await this.db
      .update(ideas)
      .set({ state: "icebox", spec, dependsOn, updatedAt: Date.now() })
      .where(eq(ideas.id, ideaId));
    // The chat is done: drop the in-memory session (the session file is kept
    // under /data as the grooming output).
    this.dropActive(ideaId);
    return await this.getIdea(ideaId);
  }

  /**
   * Accept without waiting for the finalize turn (MCP `groom_accept`):
   * validates the state, then runs `acceptGrooming` in the background. The
   * idea lands in the icebox when the finalize prompt settles (visible via
   * turnStatus / groomStatus polling). A failed finalize leaves the idea in
   * grooming — the user can re-accept or keep chatting.
   */
  async postAcceptGrooming(ideaId: number): Promise<void> {
    await this.requireIdea(ideaId, ["grooming"]);
    void this.acceptGrooming(ideaId).catch((err) => {
      console.error(`[grooming] finalize failed for idea ${ideaId}:`, err);
    });
  }

  /** Cancel (grooming → idea): the chat is discarded (session file deleted). */
  async cancelGrooming(ideaId: number): Promise<IdeaRow> {
    await this.requireIdea(ideaId, ["grooming"]);
    await this.teardownSession(ideaId);
    await this.setIdeaState(ideaId, "idea");
    return await this.getIdea(ideaId);
  }

  /**
   * Re-groom (grooming → grooming): fresh session, re-seeded with the idea.
   * `background: true` returns immediately; the re-seed runs in the
   * background (visible via turnStatus + transcript polling). Default (MCP
   * `groom_re_groom`, tests) awaits the re-seed.
   */
  async reGroom(ideaId: number, opts: { background?: boolean } = {}): Promise<IdeaRow> {
    const idea = await this.requireIdea(ideaId, ["grooming"]);
    await this.teardownSession(ideaId);
    if (opts.background) {
      void this.ensureSeeded(idea, true).catch((err) => {
        console.error(`[grooming] re-seed failed for idea ${ideaId}:`, err);
      });
    } else {
      try {
        await this.ensureSeeded(idea, false); // fresh session → seeded (awaited)
      } catch (err) {
        await this.teardownSession(ideaId);
        throw this.wrapError(ideaId, "re-groom", err);
      }
    }
    return await this.getIdea(ideaId);
  }

  /**
   * Discard (idea/grooming → discarded): soft-deleted (the `discarded` state
   * keeps an audit trail; the idea disappears from every view).
   */
  async discardIdea(ideaId: number): Promise<IdeaRow> {
    await this.requireIdea(ideaId, ["idea", "grooming"]);
    await this.teardownSession(ideaId);
    await this.setIdeaState(ideaId, "discarded");
    return await this.getIdea(ideaId);
  }

  /**
   * Transcript for the read-only grooming viewer (resumes the session if
   * needed). Never blocks on a seed turn: a stuck-empty session gets a
   * background re-seed and the (possibly empty) transcript is returned
   * immediately.
   */
  async transcript(ideaId: number): Promise<GroomMessage[]> {
    const idea = await this.requireIdea(ideaId, ["idea", "grooming"]);
    if (idea.state === "grooming") {
      const session = await this.ensureSeeded(idea, true);
      return transcriptToGroomMessages(session.messages);
    }
    return [];
  }

  /** Dispose all active sessions (shutdown). */
  dispose(): void {
    if (this.watchdogTimer) clearInterval(this.watchdogTimer);
    for (const id of [...this.active.keys()]) {
      this.dropActive(id);
    }
  }

  // -- internals -----------------------------------------------------------

  private async requireIdea(ideaId: number, states: IdeaState[]): Promise<IdeaRow> {
    const row = await this.getIdea(ideaId);
    if (!states.includes(row.state as IdeaState)) {
      throw new ServiceError(
        409,
        `idea ${ideaId} is in state "${row.state}" (expected ${states.join("/")})`,
      );
    }
    return row;
  }

  private async getIdea(ideaId: number): Promise<IdeaRow> {
    const [row] = await this.db.select().from(ideas).where(eq(ideas.id, ideaId)).limit(1);
    if (!row) throw new ServiceError(404, `idea ${ideaId} not found`);
    return row;
  }

  private async setIdeaState(ideaId: number, state: IdeaState): Promise<void> {
    await this.db.update(ideas).set({ state, updatedAt: Date.now() }).where(eq(ideas.id, ideaId));
  }

  /** Open (resume or create) the session for an idea (no seeding). */
  private async ensureSession(idea: IdeaRow): Promise<GroomSessionLike> {
    const existing = this.active.get(idea.id);
    if (existing) return existing;
    // Dedupe: a concurrent call (e.g. the transcript poll while a background
    // seed is creating the session) shares the same creation promise.
    const pending = this.sessionPending.get(idea.id);
    if (pending) return pending;
    const p = (async () => {
      const session = await this.factory({
        ideaId: idea.id,
        cwd: this.scratchDir(idea.id),
        systemPrompt: await this.buildSystemPrompt(idea),
        sessionFile: this.sessionFile(idea.id),
        owner: idea.owner, // Phase 2: bill the grooming turns to the idea owner's key
        onUsage: (u) => this.recordUsage(idea.projectId, idea.owner, u),
        onActivity: () => this.lastActivity.set(idea.id, Date.now()),
      });
      this.active.set(idea.id, session);
      return session;
    })().finally(() => this.sessionPending.delete(idea.id));
    this.sessionPending.set(idea.id, p);
    return p;
  }

  /**
   * Ensure the session exists and has its seed user message (PLAN.md §4:
   * "seeded with idea + project context"). `background: true` kicks the
   * seed off without awaiting it (long LLM turn; visible via turnStatus);
   * default awaits it. Resumed sessions already carry the seed message.
   */
  private async ensureSeeded(idea: IdeaRow, background: boolean): Promise<GroomSessionLike> {
    const session = await this.ensureSession(idea);
    const needsSeed = session.messages.every((m) => m.role !== "user");
    if (!needsSeed || this.inflight.has(idea.id)) return session;
    if (background) {
      void this.runSeed(idea.id, idea.text).catch((err) => {
        console.error(`[grooming] seed failed for idea ${idea.id}:`, err);
      });
      return session;
    }
    await this.runSeed(idea.id, idea.text);
    return session;
  }

  /** Run the seed turn (skips it if a user message already exists). */
  private runSeed(ideaId: number, text: string): Promise<void> {
    return this.withTurn(ideaId, "seeding", async () => {
      const session = this.active.get(ideaId);
      if (!session) throw new Error(`no grooming session for idea ${ideaId}`);
      // Re-check under the lock: a queued turn may have added a user message.
      if (session.messages.some((m) => m.role === "user")) return;
      await session.prompt(text);
    });
  }

  /**
   * Grooming system prompt: role + tools guidance + project context.
   * The idea text itself is the seed user message (PLAN.md §4: "seeded with
   * idea + project context").
   */
  private async buildSystemPrompt(idea: IdeaRow): Promise<string> {
    const [project] = await this.db
      .select()
      .from(projects)
      .where(eq(projects.id, idea.projectId))
      .limit(1);
    const p = project;
    const ctx: string[] = [
      `Project: ${p?.name ?? "?"}`,
      p?.goal ? `Goal: ${p.goal}` : "",
      p?.repoUrl ? `Repo: ${p.repoUrl}${p.defaultBranch ? ` (branch ${p.defaultBranch})` : ""}` : "",
      p?.blogRepoUrl
        ? `Blog: ${p.blogRepoUrl}${p.blogContentPath ? ` → ${p.blogContentPath}` : ""}`
        : "",
      p?.mediaPaths && p.mediaPaths.length > 0 ? `Media paths: ${p.mediaPaths.join(", ")}` : "",
      p?.constraints ? `Constraints (never do these): ${p.constraints}` : "",
      p?.architectureNotes ? `Architecture notes: ${p.architectureNotes}` : "",
      p?.notes ? `Notes: ${p.notes}` : "",
    ].filter((s) => s !== "");
    return [
      "You are the grooming assistant for ai-kanban, an LLM task board.",
      "Your job: help the user flesh out one idea into a precise, executable task spec —",
      "goal, ordered steps, verifiable acceptance criteria, kind (code/blog/media/other),",
      "publish target, and notes for the executing agent.",
      "",
      "You have tools and skills: use bash (curl) to fetch and analyze URLs/websites,",
      "read to inspect images and files, and work in your scratch directory:",
      `  ${this.scratchDir(idea.id)}`,
      "Research anything the user shares (links, images, docs) before concluding.",
      "Your scratch directory is a working area only — it is wiped after the task; the",
      "spec's publish_targets must name the final output location(s) (host media paths,",
      "blog paths, repos), never the scratch directory.",
      "",
      "Project context:",
      ...ctx,
      "",
      "When the user is satisfied, the app sends a FINALIZE prompt. Respond to it with",
      "ONLY the JSON object it describes — no markdown, no commentary.",
    ].join("\n");
  }

  /** Dispose the active session and delete its persisted file (chat discarded). */
  private async teardownSession(ideaId: number): Promise<void> {
    this.sessionPending.delete(ideaId);
    this.dropActive(ideaId);
    rmSync(this.sessionFile(ideaId), { force: true });
  }

  private dropActive(ideaId: number): void {
    const session = this.active.get(ideaId);
    if (session) {
      this.active.delete(ideaId);
      try {
        session.dispose();
      } catch {
        // already disposed
      }
    }
  }

  /** Serialize turns per idea (one prompt in flight per session). */
  private withTurnLock<T>(ideaId: number, fn: () => Promise<T>): Promise<T> {
    const prev = this.turns.get(ideaId) ?? Promise.resolve();
    const next = prev.then(() => fn(), () => fn());
    this.turns.set(ideaId, next.catch(() => undefined));
    return next;
  }

  /**
   * Run a turn with the per-idea lock and mark it in-flight (live status).
   * Reference-counted so queued turns don't clear the status while an
   * earlier turn is still running. The finally-block is sequence-guarded:
   * if the watchdog already released a stuck turn (and a newer turn took
   * over), the stale settle is a no-op.
   */
  private async withTurn<T>(ideaId: number, label: string, fn: () => Promise<T>): Promise<T> {
    const myGen = this.turnGen.get(ideaId) ?? 0;
    const mySince = Date.now();
    const count = (this.inflight.get(ideaId) ?? 0) + 1;
    this.inflight.set(ideaId, count);
    if (!this.turnSince.has(ideaId)) this.turnSince.set(ideaId, mySince);
    this.lastActivity.set(ideaId, mySince);
    try {
      return await this.withTurnLock(ideaId, async () => {
        // Label of the RUNNING turn (queued turns label themselves when they
        // start; the lock serializes, so no two labels overlap).
        this.turnLabel.set(ideaId, label);
        try {
          return await fn();
        } finally {
          if ((this.turnGen.get(ideaId) ?? 0) === myGen && this.turnLabel.get(ideaId) === label) {
            this.turnLabel.delete(ideaId);
          }
        }
      });
    } finally {
      // Generation-guarded: if the watchdog already released this turn, the
      // stale settle is a no-op. Otherwise, when the last in-flight turn
      // clears, the status clears too (turnSince holds the FIRST turn's
      // timestamp, so it can't be compared per-turn).
      if ((this.turnGen.get(ideaId) ?? 0) === myGen) {
        const left = (this.inflight.get(ideaId) ?? 1) - 1;
        if (left <= 0) {
          this.inflight.delete(ideaId);
          this.turnSince.delete(ideaId);
        } else {
          this.inflight.set(ideaId, left);
        }
      }
    }
  }

  /** Watchdog tick: release turns with no streaming activity for too long. */
  private watchTurns(): void {
    for (const [ideaId, since] of [...this.turnSince.entries()]) {
      const last = this.lastActivity.get(ideaId) ?? since;
      const idleMs = Date.now() - last;
      if (idleMs <= this.turnStallMs) continue;
      const label = this.turnLabel.get(ideaId) ?? "?";
      console.error(
        `[grooming] watchdog: idea ${ideaId} turn "${label}" (since ${new Date(since).toLocaleTimeString()}) ` +
          `had no streaming activity for ${Math.round(idleMs / 60_000)}m — aborting and releasing`,
      );
      this.releaseStuckTurn(ideaId);
    }
  }

  /**
   * Abort + release a stuck turn: the idea stays in `grooming` and is fully
   * usable again (new session from the persisted transcript; the user can
   * re-accept or keep chatting). The stuck prompt promise may still settle
   * later — its sequence-guarded finally-block is then a no-op.
   */
  private releaseStuckTurn(ideaId: number): void {
    const session = this.active.get(ideaId);
    try {
      session?.abort?.();
    } catch {
      /* best effort */
    }
    this.dropActive(ideaId);
    this.turns.delete(ideaId); // reset the per-idea lock chain
    this.turnGen.set(ideaId, (this.turnGen.get(ideaId) ?? 0) + 1);
    this.inflight.delete(ideaId);
    this.turnSince.delete(ideaId);
    this.turnLabel.delete(ideaId);
    this.lastActivity.delete(ideaId);
  }

  private recordUsage(projectId: number, owner: string, u: UsageSample): void {
    void recordUsage(this.db, {
      projectId,
      taskId: null,
      role: "groom",
      model: u.model,
      thinking: u.thinking,
      tokensIn: u.input,
      tokensOut: u.output,
      cost: u.cost,
      owner,
    }).catch((err) => console.error("[grooming] usage record failed:", err));
  }

  private wrapError(ideaId: number, what: string, err: unknown): ServiceError {
    if (err instanceof ServiceError) return err;
    console.error(`[grooming] failed to ${what} (idea ${ideaId}):`, err);
    return new ServiceError(500, `failed to ${what} (idea ${ideaId}): ${(err as Error).message}`);
  }
}

/** Last assistant message's text in a transcript slice (undefined when none). */
export function lastAssistantText(messages: AgentMessage[]): string | undefined {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]!;
    if (m.role !== "assistant") continue;
    const text = extractMessageText(m);
    if (text.trim() !== "") return text;
  }
  return undefined;
}

/** Current icebox items of a project (candidates for depends_on). */
async function dbSelectIceboxItems(
  db: Db,
  projectId: number,
): Promise<Array<{ id: number; text: string }>> {
  const rows = await db
    .select({ id: ideas.id, text: ideas.text })
    .from(ideas)
    .where(and(eq(ideas.projectId, projectId), eq(ideas.state, "icebox")));
  return rows;
}

/** True when the persisted session file exists (continuity available). */
export function hasGroomSessionFile(sessionsDir: string, ideaId: number): boolean {
  return existsSync(path.join(sessionsDir, `groom-${ideaId}.jsonl`));
}
