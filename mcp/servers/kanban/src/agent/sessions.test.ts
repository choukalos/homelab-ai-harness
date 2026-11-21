import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import type { AgentMessage } from "@earendil-works/pi-agent-core";
import type { KanbanConfig } from "../config.js";
import type { IdeaSpec } from "../db/schema.js";
import {
  AgentRuntime,
  LITELLM_PROVIDER,
  TaskAbortedError,
  TaskSessionRunner,
  buildMissionBrief,
  formatTaskLogLine,
  buildModelsJson,
  modelCostRates,
  type GitOps,
  type TaskRunContext,
  type TaskSessionCreateOptions,
  type TaskSessionFactory,
  type TaskSessionEvent,
  type TaskSessionLike,
  type UsageSample,
} from "./sessions.js";
import { mockAssistantMsg } from "./grooming-mock.js";

const cfg: KanbanConfig = {
  litellm: { baseUrl: "https://llm.example.com/v1", apiKey: "sk-test" },
  model: "test-model",
    modelCost: undefined,
  githubToken: undefined,
  userKeys: {},
  db: { driver: "sqlite", sqlitePath: "/tmp/test.db", mysql: undefined },
  workspace: { hostPath: "/tmp/workspace", dir: "/tmp/workspace" },
  harness: { repoUrl: "https://example.com/harness", skillsPath: "agent-skills" },
  thinking: { groom: "xhigh", task: "medium", qa: "xhigh", summary: "medium" },
  concurrentTasks: 1,
  server: { bindAddr: "127.0.0.1", port: 3000 },
};

test("buildModelsJson matches the LiteLLM provider shape (SDK_NOTES.md §1)", () => {
  const j = buildModelsJson(cfg) as any;
  assert.equal(j.providers[LITELLM_PROVIDER].baseUrl, "https://llm.example.com/v1");
  assert.equal(j.providers[LITELLM_PROVIDER].api, "openai-completions");
  const [m] = j.providers[LITELLM_PROVIDER].models;
  assert.equal(m.id, "test-model");
  assert.equal(m.name, "test-model");
  assert.ok(Array.isArray(m.input));
  assert.ok(m.contextWindow > 0 && m.maxTokens > 0);
});

test("modelCostRates: rates from cfg.modelCost (fetched from /model/info) or all-zero", () => {
  assert.deepEqual(modelCostRates(cfg), { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 });
  const withCost: KanbanConfig = {
    ...cfg,
    modelCost: { input: 0.75, output: 4.5, cacheRead: 0, cacheWrite: 0.075 },
  };
  assert.deepEqual(modelCostRates(withCost), { input: 0.75, output: 4.5, cacheRead: 0, cacheWrite: 0.075 });
});

test("buildModelsJson: catalog cost from cfg.modelCost (else all-zero)", () => {
  const zero = buildModelsJson(cfg) as any;
  assert.deepEqual(zero.providers[LITELLM_PROVIDER].models[0].cost, {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
  });
  const priced = buildModelsJson({
    ...cfg,
    modelCost: { input: 0.75, output: 4.5, cacheRead: 0, cacheWrite: 0.075 },
  }) as any;
  assert.equal(priced.providers[LITELLM_PROVIDER].models[0].cost.input, 0.75);
  assert.equal(priced.providers[LITELLM_PROVIDER].models[0].cost.output, 4.5);
  assert.equal(priced.providers[LITELLM_PROVIDER].models[0].cost.cacheWrite, 0.075);
});

test("AgentRuntime.create materializes the app-owned agent dir", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-agent-"));
  try {
    const rt = await AgentRuntime.create(cfg, { dataDir: dir });
    try {
      assert.equal(rt.agentDir, path.join(dir, "pi-agent"));
      assert.equal(rt.sessionsDir, path.join(dir, "sessions"));
      assert.equal(rt.skillsPath, path.join(dir, "harness", "agent-skills"));
      assert.equal(rt.litellmMcpUrl, "https://llm.example.com/mcp");

      const models = JSON.parse(await readFile(path.join(dir, "pi-agent", "models.json"), "utf8")) as any;
      assert.equal(models.providers[LITELLM_PROVIDER].baseUrl, "https://llm.example.com/v1");
      assert.equal(models.providers[LITELLM_PROVIDER].models[0].id, "test-model");

      const auth = JSON.parse(await readFile(path.join(dir, "pi-agent", "auth.json"), "utf8")) as any;
      assert.equal(auth[LITELLM_PROVIDER].type, "api_key");
      assert.equal(auth[LITELLM_PROVIDER].key, "sk-test");
    } finally {
      rt.dispose();
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("per-role thinking levels (resolve reuses QA)", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-agent-"));
  try {
    const rt = await AgentRuntime.create(cfg, { dataDir: dir });
    try {
      assert.equal(rt.thinkingLevel("groom"), "xhigh");
      assert.equal(rt.thinkingLevel("task"), "medium");
      assert.equal(rt.thinkingLevel("qa"), "xhigh");
      assert.equal(rt.thinkingLevel("summary"), "medium");
      assert.equal(rt.thinkingLevel("resolve"), "xhigh"); // QA level per PLAN.md §3
    } finally {
      rt.dispose();
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("AgentRuntime key profiles: per-user agent dirs + auth.json; profileFor picks by owner", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-agent-"));
  try {
    const rt = await AgentRuntime.create(
      { ...cfg, userKeys: { chuck: "sk-chuck", dylan: "sk-dylan" } },
      { dataDir: dir },
    );
    try {
      // Service profile keeps the historical path + the service key.
      assert.equal(rt.agentDir, path.join(dir, "pi-agent"));
      const serviceAuth = JSON.parse(await readFile(path.join(dir, "pi-agent", "auth.json"), "utf8")) as any;
      assert.equal(serviceAuth[LITELLM_PROVIDER].key, "sk-test");

      // One profile per USER_KEYS entry, with that user's key.
      assert.deepEqual(rt.userProfileNames().sort(), ["chuck", "dylan"]);
      for (const [name, key] of Object.entries({ chuck: "sk-chuck", dylan: "sk-dylan" })) {
        const p = rt.profileFor(name);
        assert.equal(p.name, name);
        assert.equal(p.dir, path.join(dir, `pi-agent-${name}`));
        const auth = JSON.parse(await readFile(path.join(p.dir, "auth.json"), "utf8")) as any;
        assert.equal(auth[LITELLM_PROVIDER].key, key);
        const models = JSON.parse(await readFile(path.join(p.dir, "models.json"), "utf8")) as any;
        assert.equal(models.providers[LITELLM_PROVIDER].models[0].id, "test-model");
      }

      // Fallbacks: no owner / unmapped owner → the service profile.
      assert.equal(rt.profileFor().name, "service");
      assert.equal(rt.profileFor("").name, "service");
      assert.equal(rt.profileFor("unknown-user").name, "service");
    } finally {
      rt.dispose();
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("AgentRuntime without USER_KEYS: service profile only", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-agent-"));
  try {
    const rt = await AgentRuntime.create(cfg, { dataDir: dir });
    try {
      assert.deepEqual(rt.userProfileNames(), []);
      assert.equal(rt.profileFor("chuck").name, "service");
    } finally {
      rt.dispose();
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// Slice 3a: task session (workspace, mission brief, commits, live log, usage)
// ---------------------------------------------------------------------------

/** Mocked Pi task session: one tool call + one assistant message per prompt. */
export class MockTaskSession implements TaskSessionLike {
  readonly messages: AgentMessage[] = [];
  readonly prompts: string[] = [];
  aborted = false;
  disposed = false;
  private listeners = new Set<(e: TaskSessionEvent) => void>();

  constructor(
    readonly sessionFile: string,
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
    this.fire({ type: "tool_execution_start", toolName: "bash", args: { command: "echo hi" } });
    this.fire({ type: "tool_execution_end", toolName: "bash", isError: false, durationMs: 5 });
    const msg = mockAssistantMsg("Done: the task is complete.");
    this.messages.push(msg);
    this.fire({ type: "message_end", message: msg });
    this.onUsage?.({
      role: "task",
      model: "test-model",
      thinking: "medium",
      input: 10,
      output: 5,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 15,
      cost: 0.01,
    });
  }

  abort(): void {
    this.aborted = true;
  }

  dispose(): void {
    this.disposed = true;
  }
}

/** Mocked git: a scripted HEAD sequence (base → agent commit → final). */
function mockGit(heads: string[] = ["c0ffee1", "c0ffee2", "final123"]) {
  const calls: { prepare: unknown[]; head: number; commit: Array<[string, string]>; diff: Array<[string, string]> } = {
    prepare: [],
    head: 0,
    commit: [],
    diff: [],
  };
  let n = 0;
  const ops: GitOps = {
    prepareWorkspace: async (o) => {
      calls.prepare.push(o);
    },
    headCommit: async () => heads[Math.min(n++, heads.length - 1)] ?? null,
    commitAll: async (dest, message) => {
      calls.commit.push([dest, message]);
      return "final123";
    },
    mergeBase: async (dest, baseRef) => {
      calls.diff.push([dest, baseRef]);
      return "base111";
    },
    diff: async (dest, base) => `diff ${base}..HEAD (mock)`,
  };
  return { ops, calls };
}

const SPEC: IdeaSpec = {
  goal: "Build the widget API",
  steps: ["scaffold", "implement"],
  acceptance: ["tests pass"],
  kind: "code",
};

function taskCtx(overrides: Partial<TaskRunContext> = {}): TaskRunContext {
  return {
    taskId: 7,
    projectId: 1,
    ideaText: "Add a widget API",
    spec: SPEC,
    deps: [],
    resolution: null,
    progressSummary: null,
    owner: "",
    project: {
      name: "Alpha",
      goal: "ship the widget platform",
      repoUrl: "https://github.com/chuck/alpha",
      defaultBranch: "main",
      blogRepoUrl: null,
      blogContentPath: null,
      mediaPaths: null,
      constraints: "never force-push",
      architectureNotes: "see docs/",
      notes: null,
      stateSummary: "phase 1 done",
    },
    resumeCommit: null,
    ...overrides,
  };
}

test("buildMissionBrief: project + task spec, deps, resolution, progress", () => {
  const brief = buildMissionBrief(
    taskCtx({
      deps: [
        {
          ideaId: 3,
          text: "Foundation work",
          branch: "task/3",
          lastCommit: "dep123",
          summary: "built the foundation API",
        },
      ],
      resolution: "do X instead of Y",
      progressSummary: "Last commit: c0ffee\n[tool] bash done",
    }),
    "/workspace/task-7",
  );
  assert.ok(brief.includes("# Mission brief — task 7"));
  assert.ok(brief.includes("/workspace/task-7 (branch task/7)"), "workspace + branch");
  assert.ok(brief.includes("## Project: Alpha"));
  assert.ok(brief.includes("Goal: ship the widget platform"));
  assert.ok(brief.includes("Repo: https://github.com/chuck/alpha (branch main)"));
  assert.ok(brief.includes("Constraints (never do these): never force-push"));
  assert.ok(brief.includes("Current project state: phase 1 done"));
  assert.ok(brief.includes("Idea: Add a widget API"));
  assert.ok(brief.includes("Goal: Build the widget API"));
  assert.ok(brief.includes("1. scaffold"));
  assert.ok(brief.includes("- tests pass"));
  assert.ok(brief.includes("Kind: code"));
  assert.ok(brief.includes("Last commit: c0ffee"), "rolling progress summary");
  assert.ok(brief.includes("Foundation work: branch task/3, last commit dep123"), "dependency output");
  assert.ok(brief.includes("built the foundation API"), "dependency summary");
  assert.ok(brief.includes("## Accepted resolution plan (follow it)"));
  assert.ok(brief.includes("do X instead of Y"));

  // Fresh start without deps/resolution.
  const fresh = buildMissionBrief(taskCtx(), "/workspace/task-7");
  assert.ok(fresh.includes("(fresh start — no previous progress)"));
  assert.ok(fresh.includes("(none)"), "no dependency tasks");
  assert.ok(!fresh.includes("Accepted resolution plan"), "no resolution section");
});

test("formatTaskLogLine maps session events to log lines", () => {
  assert.equal(formatTaskLogLine({ type: "tool_execution_start", toolName: "bash", args: { command: "ls" } }),
    '[tool] bash: {"command":"ls"}');
  assert.equal(formatTaskLogLine({ type: "tool_execution_end", toolName: "bash", isError: false, durationMs: 5 }),
    "[tool] bash done in 5ms");
  assert.equal(formatTaskLogLine({ type: "tool_execution_end", toolName: "edit", isError: true }),
    "[tool] edit failed");
  assert.equal(
    formatTaskLogLine({ type: "message_end", message: mockAssistantMsg("All done.") }),
    "[agent] All done.",
  );
  assert.equal(formatTaskLogLine({ type: "message_end", message: { role: "user", content: "hi" } as AgentMessage }), null);
  assert.equal(formatTaskLogLine({ type: "compaction_start", reason: "threshold" }),
    "[compact] context compacted (threshold)");
  assert.equal(formatTaskLogLine({ type: "agent_settled", aborted: true }), "[session] turn aborted");
  assert.equal(formatTaskLogLine({ type: "agent_settled", aborted: false }), null);
  assert.equal(formatTaskLogLine({ type: "message_update" }), null);
});

test("TaskSessionRunner.run: workspace, brief, log tail, commits, usage, summary", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-task-"));
  try {
    const workspaceRoot = path.join(dir, "workspace");
    const missionsDir = path.join(dir, "missions");
    const sessionsDir = path.join(dir, "sessions");
    const { ops, calls } = mockGit();
    const sessions: MockTaskSession[] = [];
    const factory: TaskSessionFactory = (opts: TaskSessionCreateOptions) => {
      const s = new MockTaskSession(opts.sessionFile, opts.onUsage);
      sessions.push(s);
      return Promise.resolve(s);
    };
    const runner = new TaskSessionRunner({
      sessionFactory: factory,
      git: ops,
      workspaceRoot,
      sessionsDir,
      missionsDir,
    });

    const log: string[] = [];
    const commits: string[] = [];
    const usages: UsageSample[] = [];
    const result = await runner.run(
      taskCtx({
        onLog: (line) => log.push(line),
        onCommit: (c) => commits.push(c),
        onUsage: (u) => usages.push(u),
      }),
    );

    // Workspace prepared: fresh clone on the task branch.
    assert.equal(calls.prepare.length, 1);
    const prep = calls.prepare[0] as { dest: string; repoUrl: string | null; branch: string; resumeCommit: string | null };
    assert.equal(prep.dest, path.join(workspaceRoot, "task-7"));
    assert.equal(prep.repoUrl, "https://github.com/chuck/alpha");
    assert.equal(prep.branch, "task/7");
    assert.equal(prep.resumeCommit, null);

    // Mission brief persisted under the missions dir.
    const brief = await readFile(path.join(missionsDir, "task-7.md"), "utf8");
    assert.ok(brief.includes("# Mission brief — task 7"));

    // Session: prompted with the kickoff, disposed after the run.
    assert.equal(sessions.length, 1);
    assert.equal(sessions[0]!.prompts.length, 1);
    assert.ok(sessions[0]!.prompts[0]!.includes("mission brief"));
    assert.equal(sessions[0]!.sessionFile, path.join(sessionsDir, "task-7.jsonl"));
    assert.equal(sessions[0]!.disposed, true);

    // Live log tail: tool lines + the assistant line.
    assert.ok(log.some((l) => l === "[tool] bash: {\"command\":\"echo hi\"}"));
    assert.ok(log.some((l) => l === "[tool] bash done in 5ms"));
    assert.ok(log.some((l) => l === "[agent] Done: the task is complete."));

    // Commit tracking: agent commit (c0ffee2) + safety-net checkpoint (final123).
    assert.deepEqual(commits, ["c0ffee2", "final123"]);
    assert.equal(calls.commit.length, 1, "safety-net commitAll once");
    assert.equal(calls.commit[0]![1], "task 7: checkpoint after run");

    // Usage captured (role `task`).
    assert.equal(usages.length, 1);
    assert.equal(usages[0]!.role, "task");
    assert.equal(usages[0]!.cost, 0.01);

    // Result: completion summary + final HEAD.
    assert.equal(result.summary, "Done: the task is complete.");
    assert.equal(result.lastCommit, "final123");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("TaskSessionRunner.run: resume re-points the branch at last_commit", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-task-"));
  try {
    const { ops, calls } = mockGit(["abc123", "abc123", "abc123"]);
    const runner = new TaskSessionRunner({
      sessionFactory: (opts) => Promise.resolve(new MockTaskSession(opts.sessionFile)),
      git: ops,
      workspaceRoot: path.join(dir, "workspace"),
      sessionsDir: path.join(dir, "sessions"),
      missionsDir: path.join(dir, "missions"),
    });
    const result = await runner.run(taskCtx({ resumeCommit: "abc123" }));
    const prep = calls.prepare[0] as { resumeCommit: string | null };
    assert.equal(prep.resumeCommit, "abc123");
    assert.equal(result.lastCommit, "abc123");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("TaskSessionRunner.run: session failure propagates and disposes the session", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-task-"));
  try {
    const { ops } = mockGit();
    // A session whose prompt rejects (model error, crash, ...).
    class FailingSession extends MockTaskSession {
      override async prompt(text: string): Promise<void> {
        await super.prompt(text);
        throw new Error("model exploded");
      }
    }
    const failing = new FailingSession(path.join(dir, "x.jsonl"));
    const runner = new TaskSessionRunner({
      sessionFactory: () => Promise.resolve(failing),
      git: ops,
      workspaceRoot: path.join(dir, "workspace"),
      sessionsDir: path.join(dir, "sessions"),
      missionsDir: path.join(dir, "missions"),
    });
    await assert.rejects(runner.run(taskCtx()), /model exploded/);
    assert.equal(failing.disposed, true, "session disposed on failure");
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("TaskSessionRunner.abort: in-flight run settles with TaskAbortedError", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-task-"));
  try {
    const { ops } = mockGit();
    let release: () => void = () => {};
    class HangingSession implements TaskSessionLike {
      readonly messages: AgentMessage[] = [];
      readonly sessionFile: string | undefined = undefined;
      private listeners = new Set<(e: TaskSessionEvent) => void>();
      aborted = false;
      disposed = false;
      /** Signaled when the run starts the prompt (session registered as active). */
      promptStarted: (() => void) | undefined;
      subscribe(fn: (e: TaskSessionEvent) => void): () => void {
        this.listeners.add(fn);
        return () => this.listeners.delete(fn);
      }
      async prompt(): Promise<void> {
        this.promptStarted?.();
        await new Promise<void>((r) => (release = r));
      }
      abort(): void {
        this.aborted = true;
        release();
      }
      dispose(): void {
        this.disposed = true;
      }
    }
    const hanging = new HangingSession();
    const runner = new TaskSessionRunner({
      sessionFactory: () => Promise.resolve(hanging),
      git: ops,
      workspaceRoot: path.join(dir, "workspace"),
      sessionsDir: path.join(dir, "sessions"),
      missionsDir: path.join(dir, "missions"),
    });
    const p = runner.run(taskCtx());
    // Abort only works once the run has registered the session (prompt started).
    await new Promise<void>((r) => (hanging.promptStarted = r));
    runner.abort(7);
    await assert.rejects(p, TaskAbortedError);
    assert.equal(hanging.aborted, true);
    assert.equal(hanging.disposed, true);
    // abort() on an idle runner is a no-op.
    runner.abort(7);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("TaskSessionRunner requires a sessionFactory or an AgentRuntime", () => {
  assert.throws(() => new TaskSessionRunner({}), /needs a sessionFactory or an AgentRuntime/);
});
