/**
 * Resolution dialog (PLAN.md §4, requirements §5/§8): a persisted Pi session
 * per failed task (<sessions>/resolve-<task>.jsonl), seeded with failure
 * context + task spec + project context, with workspace tools when the
 * workspace still exists, at the QA_THINKING level (AgentRuntime role
 * `resolve`).
 *
 * - Chat (POST /tasks/<id>/resolve/messages): one turn per call; every
 *   assistant message is recorded (usage role `resolve`, tagged by task) and
 *   a `resolve` task_event is appended (audit trail / log tail).
 * - Accept (POST /tasks/<id>/resolve/accept): a final prompt makes the
 *   session emit the structured resolution plan; the plan is captured into
 *   `tasks.resolution` and the task returns to the backlog (resume from
 *   `last_commit`, plan injected into the mission brief, `qa_rounds` reset)
 *   via the injected `restart()` (Orchestrator.restartTask).
 *
 * The Pi session is created through an injectable factory so tests run the
 * full flow against a mocked session (no network, no model).
 */
import { existsSync } from "node:fs";
import path from "node:path";
import { asc, eq } from "drizzle-orm";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { KanbanConfig } from "../config.js";
import { projects, taskEvents, tasks, type TaskRow } from "../db/schema.js";
import { ServiceError, type Db } from "../services/common.js";
import { appendTaskEvent } from "../services/tasks.js";
import { recordUsage } from "../services/usage.js";
import type { AgentRuntime, AgentSessionHandle, UsageSample } from "./sessions.js";
import { lastAssistantText, transcriptToGroomMessages, type GroomMessage } from "./grooming.js";

/** One resolution dialog message for the GUI (same shape as grooming chat). */
export type ResolveMessage = GroomMessage;

/**
 * The subset of Pi's AgentSession the resolution dialog needs. AgentSession
 * satisfies this structurally; tests provide a mock.
 */
export interface ResolveSessionLike {
  /** Run one turn; resolves when the turn settles. */
  prompt(text: string): Promise<void>;
  /** Full transcript (user/assistant messages, in order). */
  readonly messages: AgentMessage[];
  /** Path of the persisted session file (if any). */
  readonly sessionFile?: string;
  dispose(): void;
}

export interface ResolveSessionCreateOptions {
  taskId: number;
  /**
   * Session working directory: the task workspace when it still exists
   * (workspace tools: inspect files, run tests), else a fallback dir.
   */
  cwd: string;
  /** Resolution system prompt (failure context + task spec + project context). */
  systemPrompt: string;
  /**
   * Stable session file path (<sessions>/resolve-<taskId>.jsonl). Opened
   * with SessionManager.open semantics: resume if the file exists, create
   * if not.
   */
  sessionFile: string;
  /** Called with usage for each completed assistant message. */
  onUsage?: (usage: UsageSample) => void;
}

export type ResolveSessionFactory = (opts: ResolveSessionCreateOptions) => Promise<ResolveSessionLike>;

// ---------------------------------------------------------------------------
// Plan finalization (Accept)
// ---------------------------------------------------------------------------

/** Final prompt sent on Accept (PLAN.md §4: structured plan → backlog). */
export const RESOLVE_FINALIZE_PROMPT = [
  "ACCEPTED. The user accepts your resolution plan.",
  "Produce the final structured resolution plan now.",
  "Respond with ONLY the plan text (no markdown, no code fences, no commentary):",
  "1) what went wrong (one or two lines),",
  "2) the concrete steps to get the task back on track, starting from the last commit,",
  "3) what the executing agent should verify before declaring done.",
].join(" ");

/**
 * Normalize the assistant's final reply into the plan text. Strips code
 * fences and surrounding quotes. Throws ServiceError(400) when the reply is
 * empty (the dialog stays open; the user can try Accept again).
 */
export function cleanResolutionPlan(assistantText: string): string {
  let t = (assistantText ?? "").trim();
  // Strip a single code fence (```...```) if the model wrapped the plan.
  const fence = t.match(/^```[a-zA-Z0-9_-]*\s*\n?([\s\S]*?)\n?```\s*$/);
  if (fence) t = (fence[1] ?? "").trim();
  // Strip surrounding quotes.
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
    t = t.slice(1, -1).trim();
  }
  if (t === "") {
    throw new ServiceError(400, "resolution session produced no plan — try Accept again");
  }
  return t;
}

// ---------------------------------------------------------------------------
// Failure context (seed)
// ---------------------------------------------------------------------------

export interface FailureContext {
  /** `reason` of the last state event that moved the task to needs_attention. */
  reason: string | null;
  /** Feedback of the last QA event (empty when none). */
  qaFeedback: string | null;
  /** Last log/heartbeat lines (chronological, display text). */
  logTail: string[];
  /** Last commit of the failed run (resume point). */
  lastCommit: string | null;
}

/**
 * Gather the failure context for a failed task: the reason it landed in
 * needs_attention, the last QA feedback, and the log tail (PLAN.md §4:
 * "seeded with failure context + task spec + project context").
 */
export async function collectFailureContext(db: Db, task: TaskRow, logLimit = 30): Promise<FailureContext> {
  const rows = await db
    .select()
    .from(taskEvents)
    .where(eq(taskEvents.taskId, task.id))
    .orderBy(asc(taskEvents.id))
    .limit(500);
  let reason: string | null = null;
  let qaFeedback: string | null = null;
  const logLines: string[] = [];
  for (const r of rows) {
    const p = r.payload ?? {};
    if (r.type === "state" && p.to === "needs_attention" && typeof p.reason === "string") reason = p.reason;
    if (r.type === "qa" && typeof p.feedback === "string" && p.feedback !== "") qaFeedback = p.feedback;
    if (r.type === "log" && typeof p.line === "string") logLines.push(p.line);
    if (r.type === "heartbeat" && typeof p.commit === "string") logLines.push(`commit ${p.commit}`);
  }
  return {
    reason,
    qaFeedback,
    logTail: logLines.slice(-logLimit),
    lastCommit: task.lastCommit,
  };
}

/**
 * Build the resolution system prompt: role + failure context + task spec +
 * project context + workspace availability (PLAN.md §4).
 */
export function buildResolveSystemPrompt(
  task: TaskRow,
  project: { name: string; goal: string | null; repoUrl: string | null; defaultBranch: string | null; constraints: string | null; notes: string | null },
  failure: FailureContext,
  workspace: string | null,
): string {
  const lines: string[] = [];
  lines.push("You are the resolution assistant for ai-kanban, an LLM task board.");
  lines.push("A task failed and landed in Needs Attention. Help the user diagnose what went wrong");
  lines.push("and agree on a concrete resolution plan to get it back on track.");
  lines.push("");
  lines.push("## What happened");
  lines.push(`Failure reason: ${failure.reason ?? "(unknown)"}`);
  if (failure.qaFeedback) lines.push(`QA feedback: ${failure.qaFeedback}`);
  if (failure.lastCommit) lines.push(`Last commit before the failure: ${failure.lastCommit}`);
  if (failure.logTail.length > 0) {
    lines.push("Log tail:");
    for (const l of failure.logTail) lines.push(`  ${l}`);
  } else {
    lines.push("Log tail: (none recorded)");
  }
  lines.push("");
  lines.push("## Task");
  lines.push(`Goal: ${task.spec.goal}`);
  if (task.spec.steps.length > 0) {
    lines.push("Steps:");
    task.spec.steps.forEach((s, i) => lines.push(`${i + 1}. ${s}`));
  }
  if (task.spec.acceptance.length > 0) {
    lines.push("Acceptance criteria:");
    task.spec.acceptance.forEach((a) => lines.push(`- ${a}`));
  }
  lines.push(`Kind: ${task.spec.kind}`);
  if (task.branch) lines.push(`Branch: ${task.branch}`);
  lines.push("");
  lines.push(`## Project: ${project.name}`);
  if (project.goal) lines.push(`Goal: ${project.goal}`);
  if (project.repoUrl) lines.push(`Repo: ${project.repoUrl}${project.defaultBranch ? ` (branch ${project.defaultBranch})` : ""}`);
  if (project.constraints) lines.push(`Constraints (never do these): ${project.constraints}`);
  if (project.notes) lines.push(`Notes: ${project.notes}`);
  lines.push("");
  lines.push("## Workspace");
  if (workspace) {
    lines.push(`The task workspace still exists at ${workspace} (branch ${task.branch ?? `task/${task.id}`}).`);
    lines.push("You have full workspace tools: inspect files, read code, and run tests/builds to diagnose the failure.");
  } else {
    lines.push("The task workspace no longer exists (cleaned up).");
    lines.push("Work from the failure reason, QA feedback, and log tail above.");
  }
  lines.push("");
  lines.push("When the user is satisfied, the app sends a FINALIZE prompt. Respond to it with");
  lines.push("ONLY the resolution plan text — no markdown, no code fences, no commentary.");
  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Manager
// ---------------------------------------------------------------------------

export interface ResolutionDialogOptions {
  db: Db;
  cfg: KanbanConfig;
  /**
   * Create/resume the Pi session for a failed task. Defaults to wrapping an
   * AgentRuntime (role `resolve`, QA_THINKING); tests inject a mock.
   */
  sessionFactory?: ResolveSessionFactory;
  /** Agent runtime (required when sessionFactory is not given). */
  agent?: AgentRuntime;
  /** Task workspace path resolver (to check whether it still exists). */
  workspacePathFor: (taskId: number) => string;
  /** Session file dir (default: the agent runtime's sessions dir). */
  sessionsDir?: string;
  /**
   * needs_attention → backlog transition (Orchestrator.restartTask:
   * qa_rounds reset, resume from last_commit on pickup).
   */
  restart: (taskId: number) => Promise<unknown>;
}

export class ResolutionDialog {
  readonly sessionsDir: string;

  private readonly db: Db;
  private readonly cfg: KanbanConfig;
  private readonly factory: ResolveSessionFactory;
  private readonly workspacePathFor: (taskId: number) => string;
  private readonly restart: (taskId: number) => Promise<unknown>;
  /** Active in-memory sessions, per task. */
  private readonly active = new Map<number, ResolveSessionLike>();
  /** Per-task turn lock (one prompt in flight per session). */
  private readonly turns = new Map<number, Promise<unknown>>();

  constructor(opts: ResolutionDialogOptions) {
    this.db = opts.db;
    this.cfg = opts.cfg;
    this.workspacePathFor = opts.workspacePathFor;
    this.restart = opts.restart;
    if (opts.sessionFactory) {
      this.factory = opts.sessionFactory;
      this.sessionsDir =
        opts.sessionsDir ?? opts.agent?.sessionsDir ?? path.join(process.env.AI_KANBAN_DATA_DIR ?? "/data", "sessions");
    } else if (opts.agent) {
      const agent = opts.agent;
      this.factory = (o) =>
        agent
          .createSession({
            role: "resolve",
            cwd: o.cwd,
            systemPrompt: o.systemPrompt,
            sessionFile: o.sessionFile, // SessionManager.open semantics (stable path)
            onUsage: o.onUsage,
          })
          .then((h: AgentSessionHandle) => h.session as unknown as ResolveSessionLike);
      this.sessionsDir = opts.sessionsDir ?? agent.sessionsDir;
    } else {
      throw new Error("ResolutionDialog needs a sessionFactory or an AgentRuntime");
    }
  }

  // -- paths ---------------------------------------------------------------

  /** Stable persisted session file (<sessions>/resolve-<taskId>.jsonl). */
  sessionFile(taskId: number): string {
    return path.join(this.sessionsDir, `resolve-${taskId}.jsonl`);
  }

  /**
   * Session working directory: the task workspace when it still exists
   * (workspace tools), else the sessions dir (harmless fallback — the
   * prompt tells the model the workspace is gone).
   */
  private cwdFor(task: TaskRow): string {
    const workspace = this.workspacePathFor(task.id);
    return existsSync(workspace) ? workspace : this.sessionsDir;
  }

  // -- chat ----------------------------------------------------------------

  /**
   * One resolution dialog turn (POST /tasks/<id>/resolve/messages): append
   * the user message, run the turn, return the new assistant message.
   */
  async sendResolveMessage(taskId: number, text: string): Promise<ResolveMessage> {
    const t = (text ?? "").trim();
    if (t === "") throw new ServiceError(400, "message is required");
    const task = await this.requireTask(taskId, ["needs_attention"]);
    const session = await this.ensureSession(task);
    const before = session.messages.length;
    await this.withTurnLock(taskId, () => session.prompt(t));
    const reply = lastAssistantText(session.messages.slice(before));
    if (reply === undefined) {
      throw new ServiceError(500, `resolution session produced no assistant reply for task ${taskId}`);
    }
    await this.appendResolve(taskId, { text: t });
    return { role: "assistant", text: reply };
  }

  /**
   * Accept (needs_attention → backlog): the final prompt makes the session
   * emit the structured resolution plan; the plan is captured into
   * `tasks.resolution` and the task restarts (resume from last_commit, plan
   * injected into the mission brief, qa_rounds reset).
   */
  async acceptResolution(taskId: number): Promise<TaskRow> {
    const task = await this.requireTask(taskId, ["needs_attention"]);
    const session = await this.ensureSession(task);
    const before = session.messages.length;
    await this.withTurnLock(taskId, () => session.prompt(RESOLVE_FINALIZE_PROMPT));
    const reply = lastAssistantText(session.messages.slice(before));
    if (reply === undefined) {
      throw new ServiceError(500, `resolution session produced no assistant reply for task ${taskId}`);
    }
    const plan = cleanResolutionPlan(reply);
    await this.db.update(tasks).set({ resolution: plan }).where(eq(tasks.id, taskId));
    await this.appendResolve(taskId, { accepted: true, text: plan });
    await this.restart(taskId);
    // The dialog is done: drop the in-memory session (the session file is
    // kept under /data as the resolution output).
    this.dropActive(taskId);
    return await this.getTask(taskId);
  }

  /** Transcript for the task page (opens/resumes the session if needed). */
  async transcript(taskId: number): Promise<ResolveMessage[]> {
    const task = await this.requireTask(taskId, ["needs_attention"]);
    const session = await this.ensureSession(task);
    return transcriptToGroomMessages(session.messages);
  }

  /** Dispose all active sessions (shutdown). */
  dispose(): void {
    for (const id of [...this.active.keys()]) this.dropActive(id);
  }

  // -- internals -----------------------------------------------------------

  private async requireTask(taskId: number, states: string[]): Promise<TaskRow> {
    const row = await this.getTask(taskId);
    if (!states.includes(row.state)) {
      throw new ServiceError(
        409,
        `task ${taskId} is in state "${row.state}" (expected ${states.join("/")})`,
      );
    }
    return row;
  }

  private async getTask(taskId: number): Promise<TaskRow> {
    const [row] = await this.db.select().from(tasks).where(eq(tasks.id, taskId)).limit(1);
    if (!row) throw new ServiceError(404, `task ${taskId} not found`);
    return row;
  }

  /** Open (resume or create) the session for a failed task. */
  private async ensureSession(task: TaskRow): Promise<ResolveSessionLike> {
    const existing = this.active.get(task.id);
    if (existing) return existing;
    const [project] = await this.db
      .select()
      .from(projects)
      .where(eq(projects.id, task.projectId))
      .limit(1);
    const failure = await collectFailureContext(this.db, task);
    const workspace = existsSync(this.workspacePathFor(task.id)) ? this.workspacePathFor(task.id) : null;
    const session = await this.factory({
      taskId: task.id,
      cwd: this.cwdFor(task),
      systemPrompt: buildResolveSystemPrompt(
        task,
        {
          name: project?.name ?? "?",
          goal: project?.goal ?? null,
          repoUrl: project?.repoUrl ?? null,
          defaultBranch: project?.defaultBranch ?? null,
          constraints: project?.constraints ?? null,
          notes: project?.notes ?? null,
        },
        failure,
        workspace,
      ),
      sessionFile: this.sessionFile(task.id),
      onUsage: (u) => this.recordUsage(task, u),
    });
    this.active.set(task.id, session);
    return session;
  }

  private async appendResolve(taskId: number, payload: { text: string; accepted?: boolean }): Promise<void> {
    await appendTaskEvent(this.db, taskId, "resolve", payload).catch((err) =>
      console.error(`[resolve] task event failed (task ${taskId}):`, err),
    );
  }

  private recordUsage(task: TaskRow, u: UsageSample): void {
    void recordUsage(this.db, {
      projectId: task.projectId,
      taskId: task.id,
      role: "resolve",
      model: u.model,
      thinking: u.thinking,
      tokensIn: u.input,
      tokensOut: u.output,
      cost: u.cost,
    }).catch((err) => console.error(`[resolve] usage record failed (task ${task.id}):`, err));
  }

  /** Serialize turns per task (one prompt in flight per session). */
  private withTurnLock<T>(taskId: number, fn: () => Promise<T>): Promise<T> {
    const prev = this.turns.get(taskId) ?? Promise.resolve();
    const next = prev.then(() => fn(), () => fn());
    this.turns.set(taskId, next.catch(() => undefined));
    return next;
  }

  private dropActive(taskId: number): void {
    const session = this.active.get(taskId);
    if (session) {
      this.active.delete(taskId);
      try {
        session.dispose();
      } catch {
        // already disposed
      }
    }
  }
}
