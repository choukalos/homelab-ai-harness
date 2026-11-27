/**
 * QA gate tests (Slice 3b): verdict parsing + one QA round over a mocked Pi
 * session and git (no network, no model).
 */
import test from "node:test";
import assert from "node:assert/strict";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import {
  QaGate,
  buildQaPrompt,
  parseQaVerdict,
  qaFeedbackPrompt,
  type QaRunContext,
  type QaSessionCreateOptions,
  type QaSessionFactory,
  type QaSessionLike,
  type QaVerdict,
} from "./qa.js";
import { mockAssistantMsg } from "./grooming-mock.js";
import type { GitOps, TaskSessionEvent, UsageSample } from "./sessions.js";
// ---------------------------------------------------------------------------
// Verdict parsing
// ---------------------------------------------------------------------------

test("parseQaVerdict: whole-message JSON, code fence, and trailing-text forms", () => {
  assert.deepEqual(parseQaVerdict('{"pass": true, "feedback": ""}'), { pass: true, feedback: "" });
  assert.deepEqual(
    parseQaVerdict('All good.\n```json\n{"pass": true, "feedback": ""}\n```'),
    { pass: true, feedback: "" },
  );
  assert.deepEqual(
    parseQaVerdict('Ran the tests, all green. Verdict: {"pass": true, "feedback": ""}'),
    { pass: true, feedback: "" },
  );
  assert.deepEqual(
    parseQaVerdict('{"pass": false, "feedback": "tests fail: 2 assertions"}'),
    { pass: false, feedback: "tests fail: 2 assertions" },
  );
  // Last verdict wins when several JSON objects appear.
  assert.equal(
    parseQaVerdict('{"pass": true, "feedback": ""} then I checked again: {"pass": false, "feedback": "broken"}')
      ?.pass,
    false,
  );
});

test("parseQaVerdict: rejects non-verdict JSON, prose, and empty text", () => {
  assert.equal(parseQaVerdict('{"status": "ok"}'), null);
  assert.equal(parseQaVerdict("PASS — everything looks fine"), null);
  assert.equal(parseQaVerdict(""), null);
  assert.equal(parseQaVerdict("the verdict is {pass: true} (not JSON)"), null);
});

test("buildQaPrompt: spec, acceptance, diff, completion summary, round", () => {
  const ctx: QaRunContext = {
    taskId: 7,
    workspace: "/workspace/task-7",
    branch: "task/7",
    defaultBranch: "main",
    spec: { goal: "Build the widget API", steps: ["scaffold"], acceptance: ["tests pass"], kind: "code" },
    completionSummary: "The widget API is complete.",
    round: 2,
  };
  const prompt = buildQaPrompt(ctx, "diff --git a/x b/x");
  assert.ok(prompt.includes("# QA round 2 — task 7"));
  assert.ok(prompt.includes("Goal: Build the widget API"));
  assert.ok(prompt.includes("- tests pass"), "acceptance criteria");
  assert.ok(prompt.includes("The widget API is complete."), "completion summary");
  assert.ok(prompt.includes("diff --git a/x b/x"), "git diff base..HEAD");
  assert.ok(prompt.includes("branch task/7"));
});

test("buildQaPrompt: minimal spec ({goal} only) degrades, never crashes", () => {
  // A task can carry a minimal spec (no steps/acceptance/kind) — the QA
  // prompt must degrade to placeholders, not crash the QA gate.
  const ctx: QaRunContext = {
    taskId: 19,
    workspace: "/workspace/task-19",
    branch: "task/19",
    defaultBranch: "main",
    spec: { goal: "Do the thing" } as QaRunContext["spec"],
    completionSummary: "Done.",
    round: 1,
  };
  const prompt = buildQaPrompt(ctx, "(no diff)");
  assert.ok(prompt.includes("Goal: Do the thing"));
  assert.ok(!prompt.includes("Steps:"), "no steps section for a missing field");
  assert.ok(!prompt.includes("Acceptance criteria:"), "no acceptance section for a missing field");
  assert.ok(prompt.includes("Kind: (unspecified)"), "kind degrades to a placeholder");
  assert.ok(!prompt.includes("undefined"), "no 'undefined' leaks into the prompt");

  // An empty spec object must not crash either.
  const empty = buildQaPrompt(
    { ...ctx, spec: {} as QaRunContext["spec"] },
    "(no diff)",
  );
  assert.ok(empty.includes("Goal: (not specified"), "missing goal degrades to a placeholder");
});

// ---------------------------------------------------------------------------
// QaGate over a mocked session
// ---------------------------------------------------------------------------

/** Mocked Pi QA session: one assistant message per prompt. */
class MockQaSession implements QaSessionLike {
  readonly messages: AgentMessage[] = [];
  readonly prompts: string[] = [];
  disposed = false;
  private listeners = new Set<(e: TaskSessionEvent) => void>();

  constructor(
    private readonly reply: string,
    private readonly onUsage?: (u: UsageSample) => void,
  ) {}

  subscribe(fn: (e: TaskSessionEvent) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private fire(e: TaskSessionEvent): void {
    for (const l of this.listeners) l(e);
  }

  async prompt(text: string): Promise<void> {
    this.prompts.push(text);
    this.messages.push({ role: "user", content: text, timestamp: Date.now() } as AgentMessage);
    this.fire({ type: "tool_execution_start", toolName: "bash", args: { command: "npm test" } });
    const msg = mockAssistantMsg(this.reply);
    this.messages.push(msg);
    this.fire({ type: "message_end", message: msg });
    this.onUsage?.({
      role: "qa",
      model: "test-model",
      thinking: "xhigh",
      input: 20,
      output: 10,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 30,
      cost: 0.02,
    });
  }

  dispose(): void {
    this.disposed = true;
  }
}

const mockQaGit: GitOps = {
  prepareWorkspace: async () => undefined,
  headCommit: async () => "head1",
  commitAll: async () => null,
  mergeBase: async () => "base1",
  diff: async (_dest, base) => `mock diff from ${base}`,
};

function qaCtx(overrides: Partial<QaRunContext> = {}): QaRunContext {
  return {
    taskId: 7,
    workspace: "/workspace/task-7",
    branch: "task/7",
    defaultBranch: "main",
    spec: { goal: "Build the widget API", steps: ["scaffold"], acceptance: ["tests pass"], kind: "code" },
    completionSummary: "The widget API is complete.",
    round: 1,
    ...overrides,
  };
}

test("QaGate.run: pass verdict, prompt content, log tail, usage, dispose", async () => {
  let session: MockQaSession | undefined;
  const factory: QaSessionFactory = (opts: QaSessionCreateOptions) => {
    const s = new MockQaSession('Verdict: {"pass": true, "feedback": ""}', opts.onUsage);
    session = s;
    return Promise.resolve(s);
  };
  const gate = new QaGate({ sessionFactory: factory, git: mockQaGit });
  assert.equal(gate.maxRounds, 2, "default max rounds");

  const log: string[] = [];
  const usages: UsageSample[] = [];
  const verdict = await gate.run(
    qaCtx({
      onLog: (line) => log.push(line),
      onUsage: (u) => usages.push(u),
    }),
  );

  assert.deepEqual(verdict, { pass: true, feedback: "" });
  assert.ok(session, "session created");
  assert.equal(session!.prompts.length, 1);
  assert.ok(session!.prompts[0]!.includes("# QA round 1 — task 7"));
  assert.ok(session!.prompts[0]!.includes("mock diff from base1"), "diff in the prompt");
  assert.equal(session!.disposed, true, "session disposed after the round");
  assert.ok(log.some((l) => l === "[qa] [tool] bash: {\"command\":\"npm test\"}"), "QA log tail");
  assert.ok(log.some((l) => l === "[qa] [agent] Verdict: {\"pass\": true, \"feedback\": \"\"}"), "assistant line");
  assert.equal(usages.length, 1, "usage captured");
  assert.equal(usages[0]!.role, "qa");
});

test("QaGate.run: fail verdict carries the feedback", async () => {
  const factory: QaSessionFactory = () =>
    Promise.resolve(new MockQaSession('{"pass": false, "feedback": "acceptance: tests fail (3 errors)"}'));
  const gate = new QaGate({ sessionFactory: factory, git: mockQaGit });
  const verdict = await gate.run(qaCtx());
  assert.equal(verdict.pass, false);
  assert.equal(verdict.feedback, "acceptance: tests fail (3 errors)");
});

test("QaGate.run: unparseable verdict → fail with a parseable-feedback note", async () => {
  const factory: QaSessionFactory = () => Promise.resolve(new MockQaSession("Looks fine to me, no JSON."));
  const gate = new QaGate({ sessionFactory: factory, git: mockQaGit });
  const verdict = await gate.run(qaCtx());
  assert.equal(verdict.pass, false);
  assert.match(verdict.feedback, /no parseable verdict/);
  assert.match(verdict.feedback, /Looks fine to me/);
});

test("QaGate.run: scratch repo (no default branch) → no diff section crash", async () => {
  const factory: QaSessionFactory = () => Promise.resolve(new MockQaSession('{"pass": true, "feedback": ""}'));
  const gate = new QaGate({ sessionFactory: factory, git: mockQaGit });
  const verdict = await gate.run(qaCtx({ defaultBranch: null, branch: null }));
  assert.equal(verdict.pass, true);
});

test("QaGate requires a sessionFactory or an AgentRuntime", () => {
  assert.throws(() => new QaGate({}), /needs a sessionFactory or an AgentRuntime/);
});

test("qaFeedbackPrompt: round + feedback + acceptance reminder", () => {
  const p = qaFeedbackPrompt(1, "tests fail: 3 errors");
  assert.ok(p.includes("QA round 1 FAILED"));
  assert.ok(p.includes("tests fail: 3 errors"));
  assert.ok(p.includes("acceptance criteria"));
  assert.ok(p.includes("commit after each meaningful step"));
});
