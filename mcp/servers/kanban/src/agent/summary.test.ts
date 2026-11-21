/**
 * Project state-summary tests (Slice 3b): one-shot update over a mocked Pi
 * session (no network, no model).
 */
import test from "node:test";
import assert from "node:assert/strict";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import {
  SUMMARY_SYSTEM_PROMPT,
  SummaryUpdater,
  buildSummaryPrompt,
  cleanSummary,
  type SummarySessionCreateOptions,
  type SummarySessionFactory,
  type SummarySessionLike,
  type SummaryUpdateContext,
} from "./summary.js";
import { mockAssistantMsg } from "./grooming-mock.js";
import type { UsageSample } from "./sessions.js";

/** Mocked one-shot summary session. */
class MockSummarySession implements SummarySessionLike {
  readonly messages: AgentMessage[] = [];
  readonly prompts: string[] = [];
  disposed = false;

  constructor(
    private readonly reply: string,
    private readonly onUsage?: (u: UsageSample) => void,
  ) {}

  async prompt(text: string): Promise<void> {
    this.prompts.push(text);
    this.messages.push({ role: "user", content: text, timestamp: Date.now() } as AgentMessage);
    this.messages.push(mockAssistantMsg(this.reply));
    this.onUsage?.({
      role: "summary",
      model: "test-model",
      thinking: "medium",
      input: 5,
      output: 20,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 25,
      cost: 0.005,
    });
  }

  dispose(): void {
    this.disposed = true;
  }
}

function summaryCtx(overrides: Partial<SummaryUpdateContext> = {}): SummaryUpdateContext {
  return {
    projectName: "Alpha",
    projectGoal: "ship the widget platform",
    previousSummary: "Phase 1 done: the API is live.",
    deployed: "task 7 (code): pushed branch task/7",
    ...overrides,
  };
}

test("buildSummaryPrompt: previous summary + what was just deployed", () => {
  const p = buildSummaryPrompt(summaryCtx());
  assert.ok(p.includes("Project: Alpha"));
  assert.ok(p.includes("Goal: ship the widget platform"));
  assert.ok(p.includes("Phase 1 done: the API is live."), "previous summary");
  assert.ok(p.includes("task 7 (code): pushed branch task/7"), "what was deployed");
  assert.ok(p.includes("Write the updated project state summary now"));
});

test("cleanSummary: strips code fences and surrounding quotes", () => {
  assert.equal(cleanSummary("  The widget API is live with dark mode.  "), "The widget API is live with dark mode.");
  assert.equal(cleanSummary("```text\nNew summary here.\n```"), "New summary here.");
  assert.equal(cleanSummary('"Quoted summary"'), "Quoted summary");
  assert.equal(cleanSummary("'Single quoted'"), "Single quoted");
});

test("SummaryUpdater.update: prompt content, result, usage (role summary), dispose", async () => {
  let session: MockSummarySession | undefined;
  const factory: SummarySessionFactory = (opts: SummarySessionCreateOptions) => {
    const s = new MockSummarySession("The widget API is live; dark mode is deployed.", opts.onUsage);
    session = s;
    return Promise.resolve(s);
  };
  const updater = new SummaryUpdater({ sessionFactory: factory });

  const usages: UsageSample[] = [];
  const next = await updater.update(summaryCtx({ onUsage: (u) => usages.push(u) }));

  assert.equal(next, "The widget API is live; dark mode is deployed.");
  assert.ok(session, "session created");
  assert.ok(session!.prompts[0]!.includes("Phase 1 done: the API is live."));
  assert.equal(session!.disposed, true);
  assert.equal(usages.length, 1, "usage captured");
  assert.equal(usages[0]!.role, "summary");

  // The system prompt demands summary-only output.
  assert.match(SUMMARY_SYSTEM_PROMPT, /ONLY the new summary text/);
});

test("SummaryUpdater.update: empty reply → empty string (caller keeps the old summary)", async () => {
  const factory: SummarySessionFactory = () => Promise.resolve(new MockSummarySession(""));
  const updater = new SummaryUpdater({ sessionFactory: factory });
  assert.equal(await updater.update(summaryCtx()), "");
});

test("SummaryUpdater requires a sessionFactory or an AgentRuntime", () => {
  assert.throws(() => new SummaryUpdater({}), /needs a sessionFactory or an AgentRuntime/);
});
