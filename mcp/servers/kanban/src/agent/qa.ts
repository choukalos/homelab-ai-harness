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
  formatTaskLogLine,
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
  /** The task session's completion summary (last assistant message). */
  completionSummary: string;
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
  "Verify the work against the task spec and acceptance criteria you are given.",
  "You have full tools: inspect files, run tests, run builds — use them.",
  "Be strict: FAIL if any acceptance criterion is not met, the work is broken, or it violates the project constraints.",
  "When done, end your final message with the verdict as a single JSON object (nothing after it):",
  '{"pass": true, "feedback": ""}',
  "or",
  '{"pass": false, "feedback": "<specific, actionable description of what must be fixed>"}',
].join("\n");

/** The QA round kickoff (user message): spec + acceptance + diff + summary. */
export function buildQaPrompt(ctx: QaRunContext, diff: string): string {
  const lines: string[] = [];
  lines.push(`# QA round ${ctx.round} — task ${ctx.taskId}`);
  lines.push("");
  lines.push("## Task spec");
  lines.push(`Goal: ${ctx.spec.goal}`);
  if (ctx.spec.steps.length > 0) {
    lines.push("Steps:");
    ctx.spec.steps.forEach((s, i) => lines.push(`${i + 1}. ${s}`));
  }
  if (ctx.spec.acceptance.length > 0) {
    lines.push("Acceptance criteria:");
    ctx.spec.acceptance.forEach((a) => lines.push(`- ${a}`));
  }
  lines.push(`Kind: ${ctx.spec.kind}`);
  lines.push("");
  lines.push("## Completion summary (from the task agent)");
  lines.push(ctx.completionSummary || "(none)");
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

  /** Run one QA round in the task workspace. */
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
    const unsubscribe = session.subscribe((event) => {
      const line = formatTaskLogLine(event);
      if (line) ctx.onLog?.(`[qa] ${line}`);
    });
    try {
      await session.prompt(buildQaPrompt(ctx, diff));
      const text = lastAssistantText(session.messages) ?? "";
      const verdict = parseQaVerdict(text);
      if (verdict) return verdict;
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
