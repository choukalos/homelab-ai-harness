/**
 * QA gate (PLAN.md §4, Slice 3b): when the task session declares done, a
 * FRESH Pi session (separate context, same workspace, full tools — may run
 * tests/builds) verifies the work:
 *
 *   task spec + acceptance criteria + `git diff base..HEAD` + completion
 *   summary → pass/fail + feedback.
 *
 *   pass → Deploy stage.
 *   fail → back to running with the feedback, qa_rounds+1;
 *          max 2 rounds → needs_attention (QA exhausted).
 *
 * The verdict is a JSON object the QA session must end with:
 *   {"pass": true, "feedback": ""}  /  {"pass": false, "feedback": "..."}
 * (parseQaVerdict is lenient: whole message, code fences, or the last
 * {...} around "pass".)
 */
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { IdeaSpec } from "../db/schema.js";
import { lastAssistantText } from "./grooming.js";
import {
  createGitOps,
  formatApiError,
  formatTaskLogLine,
  SessionApiError,
  apiErrorFromEvent,
  type AgentRuntime,
  type AgentSessionHandle,
  type GitOps,
  type TaskSessionEvent,
  type UsageSample,
} from "./sessions.js";

export interface QaVerdict {
  pass: boolean;
  /** What must be fixed (empty when pass). */
  feedback: string;
}

/** Parse the QA verdict from the session's final assistant message. */
export function parseQaVerdict(text: string): QaVerdict | null {
  const t = text.trim();
  if (!t) return null;
  const candidates: string[] = [t];
  for (const m of t.matchAll(/```(?:json)?\s*([\s\S]*?)```/g)) candidates.push(m[1]?.trim() ?? "");
  const passIdx = t.lastIndexOf('"pass"');
  if (passIdx !== -1) {
    const start = t.lastIndexOf("{", passIdx);
    const end = t.lastIndexOf("}");
    if (start !== -1 && end > start) candidates.push(t.slice(start, end + 1));
  }
  for (const c of candidates) {
    try {
      const obj: unknown = JSON.parse(c);
      if (obj && typeof obj === "object" && typeof (obj as QaVerdict).pass === "boolean") {
        const v = obj as QaVerdict;
        return { pass: v.pass, feedback: typeof v.feedback === "string" ? v.feedback : "" };
      }
    } catch {
      // not JSON — try the next candidate
    }
  }
  return null;
}

/** A QA session (Pi AgentSession or a mock in tests). */
export interface QaSessionLike {
  readonly messages: AgentMessage[];
  subscribe(fn: (e: TaskSessionEvent) => void): () => void;
  prompt(text: string): Promise<void>;
  dispose(): void;
}

export interface QaSessionCreateOptions {
  /** Workspace the QA session works in (same as the task workspace). */
  cwd: string;
  systemPrompt: string;
  /** Owner (USER_KEYS name) the session's LLM calls bill to (Phase 2). */
  owner?: string;
  onUsage?: (usage: UsageSample) => void;
}

export type QaSessionFactory = (opts: QaSessionCreateOptions) => Promise<QaSessionLike>;

/** Everything one QA round needs. */
export interface QaRunContext {
  taskId: number;
  /** Task workspace (/workspace/task-<id>). */
  workspace: string;
  branch: string | null;
  /** Project default branch (the diff base ref). */
  defaultBranch: string | null;
  spec: IdeaSpec;
  /** 1-based QA round number. */
  round: number;
  /** Owner (USER_KEYS name) the session's LLM calls bill to (Phase 2). */
  owner?: string;
  onLog?: (line: string) => void;
  onUsage?: (usage: UsageSample) => void;
}

export const QA_SYSTEM_PROMPT = [
  "You are the QA gate for ai-kanban, an LLM task board.",
  "A task agent just finished work in this workspace (its task branch).",
  "You are reviewing FRESH CONTEXT: you were given only the task requirements (spec + acceptance criteria) and the diff — you have NOT seen the task agent's reasoning or claims, and you are given none of them. Judge the work on the evidence in the diff alone; do not assume the work is complete or correct beyond what the diff shows.",
  "Verify the work against the task spec and acceptance criteria you are given.",
  "You have full tools: inspect files, run tests, run builds — use them.",
  "Be strict: FAIL if any acceptance criterion is not met, the work is broken, or it violates the project constraints.",
  "When done, end your final message with the verdict as a single JSON object (nothing after it):",
  '{"pass": true, "feedback": ""}',
  "or",
  '{"pass": false, "feedback": "<specific, actionable description of what must be fixed>"}',
].join("\n");

/**
 * The QA round kickoff (user message): requirements (spec + acceptance) +
 * diff ONLY. The worker's completion summary is deliberately NOT included
 * (chuck 2026-11-27, item 17): the QA reviewer is a fresh-context critic —
 * giving it the worker's claims is a sycophancy vector (critics who saw the
 * worker's reasoning rubber-stamp it). The diff is the evidence; the spec
 * is the requirements.
 */
export function buildQaPrompt(ctx: QaRunContext, diff: string): string {
  const lines: string[] = [];
  lines.push(`# QA round ${ctx.round} — task ${ctx.taskId}`);
  lines.push("");
  lines.push("## Task spec");
  // The spec is JSON from the DB — treat every field as runtime-untrusted
  // (a task can carry a minimal spec, e.g. {goal} only): never crash the
  // QA gate on a missing field, degrade to a placeholder instead.
  const steps = Array.isArray(ctx.spec.steps) ? ctx.spec.steps : [];
  const acceptance = Array.isArray(ctx.spec.acceptance) ? ctx.spec.acceptance : [];
  lines.push(`Goal: ${ctx.spec.goal ?? "(not specified — derive it from the diff)"}`);
  if (steps.length > 0) {
    lines.push("Steps:");
    steps.forEach((s, i) => lines.push(`${i + 1}. ${s}`));
  }
  if (acceptance.length > 0) {
    lines.push("Acceptance criteria:");
    acceptance.forEach((a) => lines.push(`- ${a}`));
  }
  lines.push(`Kind: ${ctx.spec.kind ?? "(unspecified)"}`);
  lines.push("");
  lines.push(`## Diff (base..HEAD${ctx.branch ? `, branch ${ctx.branch}` : ""})`);
  lines.push("```");
  lines.push(diff || "(no diff available)");
  lines.push("```");
  lines.push("");
  lines.push("Verify the work now. Run the tests if there are any.");
  lines.push("");
  lines.push(
    "Robustness rules: if a tool or model dependency is unavailable or failing (e.g. a vision " +
      "model is down), do NOT wait for it or keep retrying — fall back to deterministic " +
      "programmatic checks (file validity, dimensions, pixel/geometry analysis, schema " +
      "validation) and make your verdict on those. Finish within a reasonable number of " +
      "steps; a stalled QA run is worse than a pragmatic one.",
  );
  return lines.join("\n");
}

export interface QaGateOptions {
  /** Create the fresh QA session (default: an AgentRuntime session, role `qa`). */
  sessionFactory?: QaSessionFactory;
  /** Agent runtime (required when sessionFactory is not given). */
  agent?: AgentRuntime;
  /** Git ops for the diff (default: real git via execFile). */
  git?: GitOps;
  /** Max QA rounds before needs_attention (default 2). */
  maxRounds?: number;
}

/**
 * Kickoff prompt for the task session re-run after a failed QA round
 * ("back to running with feedback", PLAN.md §4): the QA feedback + a
 * reminder of the acceptance discipline.
 */
export function qaFeedbackPrompt(round: number, feedback: string): string {
  return [
    `QA round ${round} FAILED. The QA gate found the following issues:`,
    "",
    feedback,
    "",
    "Fix the issues, re-verify against the acceptance criteria in your mission brief,",
    "and commit after each meaningful step.",
    "When done, end your turn with a short summary of what you changed.",
  ].join("\n");
}

/**
 * The QA gate: one fresh Pi session per round (QA_THINKING), same workspace
 * as the task, full tools. Returns the verdict (never throws for a
 * "fail" — only for infrastructure errors).
 */
export class QaGate {
  readonly maxRounds: number;
  private readonly factory: QaSessionFactory;
  private readonly git: GitOps;

  constructor(opts: QaGateOptions) {
    if (opts.sessionFactory) {
      this.factory = opts.sessionFactory;
    } else if (opts.agent) {
      const agent = opts.agent;
      this.factory = (o) =>
        agent
          .createSession({
            role: "qa",
            cwd: o.cwd,
            systemPrompt: o.systemPrompt,
            owner: o.owner, // Phase 2: bill to the task owner's key (else service key)
            onUsage: o.onUsage,
          })
          .then((h: AgentSessionHandle) => h.session as unknown as QaSessionLike);
    } else {
      throw new Error("QaGate needs a sessionFactory or an AgentRuntime");
    }
    this.git = opts.git ?? createGitOps();
    this.maxRounds = opts.maxRounds ?? 2;
  }

  /**
   * Run one QA round in the task workspace. Returns the verdict (never
   * throws for a "fail" — only for infrastructure errors). Throws
   * SessionApiError when the QA session's LLM calls failed with an API
   * error and produced no parseable verdict (item 14 loud-fail — the
   * orchestrator consumes the round with the REAL error instead of
   * "no parseable verdict").
   */
  async run(ctx: QaRunContext): Promise<QaVerdict> {
    // Diff base: the project's default branch (the clone base).
    const base = ctx.defaultBranch
      ? await this.git.mergeBase(ctx.workspace, ctx.defaultBranch).catch(() => null)
      : null;
    const diff = base ? await this.git.diff(ctx.workspace, base).catch(() => "") : "";

    const session = await this.factory({
      cwd: ctx.workspace,
      systemPrompt: QA_SYSTEM_PROMPT,
      owner: ctx.owner, // Phase 2: bill to the task owner's key (else service key)
      onUsage: ctx.onUsage,
    });
    /** First API error seen during the round (item 14 loud-fail). */
    let firstApiError: string | undefined;
    const unsubscribe = session.subscribe((event) => {
      const line = formatTaskLogLine(event);
      if (line) ctx.onLog?.(`[qa] ${line}`);
      const apiError = apiErrorFromEvent(event);
      if (apiError) firstApiError ??= apiError;
    });
    try {
      try {
        await session.prompt(buildQaPrompt(ctx, diff));
      } catch (err) {
        // prompt() rejected (stream/runtime failure) — loud-fail too.
        const f = formatApiError(err instanceof Error ? err.message : String(err));
        ctx.onLog?.(`[qa] LLM API error — failing loudly: ${f.message}`);
        throw new SessionApiError(f.message, f.status);
      }
      const text = lastAssistantText(session.messages) ?? "";
      const verdict = parseQaVerdict(text);
      if (verdict) return verdict;
      // No parseable verdict: an API error with no output is a loud failure
      // (the real error, not "no parseable verdict"); an empty-but-
      // successful response keeps today's behavior (a failed round).
      if (firstApiError) {
        const f = formatApiError(firstApiError);
        ctx.onLog?.(`[qa] LLM API error with no verdict — failing loudly: ${f.message}`);
        throw new SessionApiError(f.message, f.status);
      }
      return {
        pass: false,
        feedback: `QA session returned no parseable verdict (last message: ${text.slice(0, 300) || "(empty)"})`,
      };
    } finally {
      unsubscribe();
      session.dispose();
    }
  }
}
