/**
 * Project state-summary update (PLAN.md §4/§6, Slice 3b): after each
 * successful deploy, a one-shot Pi session (SUMMARY_THINKING) updates the
 * project's `state_summary` from (previous summary + what was just
 * deployed). Read-only in the GUI; injected into mission briefs.
 */
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import { lastAssistantText } from "./grooming.js";
import type { AgentRuntime, AgentSessionHandle, UsageSample } from "./sessions.js";

export const SUMMARY_SYSTEM_PROMPT = [
  "You maintain the state summary of a project in ai-kanban, an LLM task board.",
  "The summary is a short paragraph (2-5 sentences) describing the current completion state of the project: what exists, what works, what is in flight.",
  "You are given the previous summary and what was just deployed.",
  "Write the updated summary — carry over what is still true, add what changed.",
  "Reply with ONLY the new summary text (no preamble, no quotes, no markdown).",
].join("\n");

/** One-shot summary session (Pi AgentSession or a mock in tests). */
export interface SummarySessionLike {
  readonly messages: AgentMessage[];
  prompt(text: string): Promise<void>;
  dispose(): void;
}

export interface SummarySessionCreateOptions {
  systemPrompt: string;
  /** Owner (USER_KEYS name) the session's LLM calls bill to (Phase 2). */
  owner?: string;
  onUsage?: (usage: UsageSample) => void;
}

export type SummarySessionFactory = (opts: SummarySessionCreateOptions) => Promise<SummarySessionLike>;

/** What the summary session needs to know. */
export interface SummaryUpdateContext {
  projectName: string;
  projectGoal?: string | null;
  /** The project's current state_summary ("" when none yet). */
  previousSummary: string;
  /** What was just deployed (one line, e.g. "task 7 (code): pushed branch task/7"). */
  deployed: string;
  /** Owner (USER_KEYS name) the session's LLM calls bill to (Phase 2). */
  owner?: string;
  onUsage?: (usage: UsageSample) => void;
}

/** The one-shot prompt (user message). */
export function buildSummaryPrompt(ctx: SummaryUpdateContext): string {
  const lines: string[] = [];
  lines.push(`Project: ${ctx.projectName}`);
  if (ctx.projectGoal) lines.push(`Goal: ${ctx.projectGoal}`);
  lines.push("");
  lines.push("Previous summary:");
  lines.push(ctx.previousSummary || "(none yet)");
  lines.push("");
  lines.push("Just deployed:");
  lines.push(ctx.deployed);
  lines.push("");
  lines.push("Write the updated project state summary now.");
  return lines.join("\n");
}

/** Strip surrounding code fences / quotes from the model's reply. */
export function cleanSummary(text: string): string {
  let t = text.trim();
  const fence = t.match(/^```[a-zA-Z]*\s*\n?([\s\S]*?)\n?\s*```$/);
  if (fence?.[1]) t = fence[1].trim();
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
    t = t.slice(1, -1).trim();
  }
  return t;
}

export interface SummaryUpdaterOptions {
  /** Create the one-shot session (default: an AgentRuntime session, role `summary`). */
  sessionFactory?: SummarySessionFactory;
  /** Agent runtime (required when sessionFactory is not given). */
  agent?: AgentRuntime;
}

/** One-shot project state-summary updates. */
export class SummaryUpdater {
  private readonly factory: SummarySessionFactory;

  constructor(opts: SummaryUpdaterOptions) {
    if (opts.sessionFactory) {
      this.factory = opts.sessionFactory;
    } else if (opts.agent) {
      const agent = opts.agent;
      this.factory = (o) =>
        agent
          .createSession({
            role: "summary",
            cwd: process.cwd(),
            systemPrompt: o.systemPrompt,
            owner: o.owner, // Phase 2: bill to the task owner's key (else service key)
            // Item 15: the summary session is a service session — it runs on
            // the pipeline model (KANBAN_MODEL) even for a mapped owner.
            useServiceModel: true,
            onUsage: o.onUsage,
          })
          .then((h: AgentSessionHandle) => h.session as unknown as SummarySessionLike);
    } else {
      throw new Error("SummaryUpdater needs a sessionFactory or an AgentRuntime");
    }
  }

  /**
   * One-shot update: previous summary + what was just deployed → new
   * state_summary. Returns the new summary text ("" when the session
   * produced nothing).
   */
  async update(ctx: SummaryUpdateContext): Promise<string> {
    const session = await this.factory({
      systemPrompt: SUMMARY_SYSTEM_PROMPT,
      owner: ctx.owner, // Phase 2: bill to the task owner's key (else service key)
      onUsage: ctx.onUsage,
    });
    try {
      await session.prompt(buildSummaryPrompt(ctx));
      const text = lastAssistantText(session.messages) ?? "";
      return cleanSummary(text);
    } finally {
      session.dispose();
    }
  }
}
