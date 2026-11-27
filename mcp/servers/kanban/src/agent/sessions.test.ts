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
  EMPTY_RETRY_PROMPT,
  LITELLM_PROVIDER,
  SessionApiError,
  TaskAbortedError,
  TaskSessionRunner,
  apiErrorFromEvent,
  buildMissionBrief,
  formatApiError,
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
  mediaConcurrentTasks: 1,
  nonMediaConcurrentTasks: 1,
  agentConcurrentTasks: 1,
  agentSlugs: [],
  ownerModels: {},
  ownerModelCosts: {},
  workspaceCleanupDays: 7,
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

test("modelCostRates: a mapped owner model uses its own rates — never the pipeline model's (item 15)", () => {
  const withOwner: KanbanConfig = {
    ...cfg,
    modelCost: { input: 0.75, output: 4.5, cacheRead: 0, cacheWrite: 0.075 },
    ownerModelCosts: {
      "writer-model": { input: 0.5, output: 2.0, cacheRead: 0, cacheWrite: 0 },
    },
  };
  // The pipeline model keeps its own rates (explicit or default selection).
  assert.deepEqual(modelCostRates(withOwner, cfg.model), {
    input: 0.75,
    output: 4.5,
    cacheRead: 0,
    cacheWrite: 0.075,
  });
  assert.deepEqual(modelCostRates(withOwner), {
    input: 0.75,
    output: 4.5,
    cacheRead: 0,
    cacheWrite: 0.075,
  });
  // A mapped model with configured rates uses them.
  assert.deepEqual(modelCostRates(withOwner, "writer-model"), {
    input: 0.5,
    output: 2.0,
    cacheRead: 0,
    cacheWrite: 0,
  });
  // A mapped model WITHOUT configured rates → all-zero, NOT the pipeline
  // model's rates (pricing one model at another's rate would be wrong).
  assert.deepEqual(modelCostRates(withOwner, "unmapped-model"), {
    input: 0,
    output: 0,
    cacheRead: 0,
    cacheWrite: 0,
  });
});

test("formatApiError: pi-ai '<status>: <body>' → 'HTTP <status> — <body>' + status (item 14)", () => {
  assert.deepEqual(
    formatApiError("403: The requested model 'matrix-coder' is not available for this API key"),
    {
      message: "HTTP 403 — The requested model 'matrix-coder' is not available for this API key",
      status: 403,
    },
  );
  assert.deepEqual(formatApiError("500"), { message: "HTTP 500", status: 500 });
  // No status prefix → the raw message is kept (status stays undefined).
  assert.deepEqual(formatApiError("stream interrupted"), { message: "stream interrupted" });
});

test("apiErrorFromEvent: error-bearing assistant message_end → the raw error; else undefined (item 14)", () => {
  const errMsg = { role: "assistant", content: [], stopReason: "error", errorMessage: "403: no key" } as unknown as AgentMessage;
  assert.equal(apiErrorFromEvent({ type: "message_end", message: errMsg }), "403: no key");
  // A normal completion is not an API error.
  assert.equal(apiErrorFromEvent({ type: "message_end", message: mockAssistantMsg("ok") }), undefined);
  // An aborted run is NOT an API error (abort is not a failure).
  const abortedMsg = { role: "assistant", content: [], stopReason: "aborted" } as unknown as AgentMessage;
  assert.equal(apiErrorFromEvent({ type: "message_end", message: abortedMsg }), undefined);
  // Non-message events never carry an API error.
  assert.equal(apiErrorFromEvent({ type: "tool_execution_end", toolName: "bash", isError: true }), undefined);
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

test("AgentRuntime: per-owner pipeline model (item 15) — mapped → mapped model; unmapped/no owner → cfg.model", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-agent-"));
  try {
    const rt = await AgentRuntime.create(
      {
        ...cfg,
        userKeys: { strategist: "sk-strategist", dylan: "sk-dylan" },
        ownerModels: { strategist: "writer-model" },
        ownerModelCosts: {
          "writer-model": { input: 0.5, output: 2.0, cacheRead: 0, cacheWrite: 0 },
        },
      },
      { dataDir: dir },
    );
    try {
      // Mapped owner → the mapped model; the pipeline model is still
      // available on the same profile (serviceModel) for service sessions.
      const mapped = rt.profileFor("strategist");
      assert.equal(mapped.model.id, "writer-model");
      assert.equal(mapped.serviceModel.id, "test-model");

      // Unmapped owner with a key profile → the pipeline model.
      const unmapped = rt.profileFor("dylan");
      assert.equal(unmapped.model.id, "test-model");
      assert.equal(unmapped.serviceModel.id, "test-model");

      // No owner → the service profile on the pipeline model.
      const service = rt.profileFor();
      assert.equal(service.name, "service");
      assert.equal(service.model.id, "test-model");
      assert.equal(service.serviceModel.id, "test-model");

      // models.json: the mapped profile carries BOTH models (owner model +
      // pipeline model) with per-model rates; the unmapped profile carries
      // only the pipeline model.
      const mappedModels = JSON.parse(
        await readFile(path.join(mapped.dir, "models.json"), "utf8"),
      ) as any;
      const mappedIds = mappedModels.providers[LITELLM_PROVIDER].models.map((m: any) => m.id).sort();
      assert.deepEqual(mappedIds, ["test-model", "writer-model"]);
      const writerEntry = mappedModels.providers[LITELLM_PROVIDER].models.find(
        (m: any) => m.id === "writer-model",
      );
      assert.deepEqual(writerEntry.cost, { input: 0.5, output: 2.0, cacheRead: 0, cacheWrite: 0 });
      const unmappedModels = JSON.parse(
        await readFile(path.join(unmapped.dir, "models.json"), "utf8"),
      ) as any;
      assert.deepEqual(
        unmappedModels.providers[LITELLM_PROVIDER].models.map((m: any) => m.id),
        ["test-model"],
      );
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

test("buildMissionBrief: minimal spec ({goal} only) degrades, never crashes", () => {
  // The spec is JSON from the DB — a task can carry a minimal spec with no
  // steps/acceptance/kind (the 2026-11-27 live probe that crashed the
  // session pipeline). The brief must degrade to placeholders, not throw.
  const minimal = { goal: "Do the thing" } as unknown as IdeaSpec;
  const brief = buildMissionBrief(taskCtx({ spec: minimal }), "/workspace/task-7");
  assert.ok(brief.includes("Goal: Do the thing"), "the goal is present");
  assert.ok(!brief.includes("Steps:"), "no steps section for a missing field");
  assert.ok(!brief.includes("Acceptance criteria:"), "no acceptance section for a missing field");
  assert.ok(brief.includes("Kind: (unspecified"), "kind degrades to a placeholder");
  assert.ok(!brief.includes("undefined"), "no 'undefined' leaks into the brief");

  // Even an empty object must not crash.
  const empty = {} as unknown as IdeaSpec;
  const emptyBrief = buildMissionBrief(taskCtx({ spec: empty }), "/workspace/task-7");
  assert.ok(emptyBrief.includes("Goal: (not specified"), "missing goal degrades to a placeholder");

  // Non-array steps/acceptance (corrupt JSON) must not crash either.
  const corrupt = { goal: "x", steps: "nope", acceptance: 42 } as unknown as IdeaSpec;
  const corruptBrief = buildMissionBrief(taskCtx({ spec: corrupt }), "/workspace/task-7");
  assert.ok(corruptBrief.includes("Goal: x"));
  assert.ok(!corruptBrief.includes("Steps:"), "non-array steps ignored");
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

/**
 * Mocked Pi task session scripted per prompt (item 14): each entry is
 * "empty" (HTTP 200, zero assistant content), an API-error string (the SDK
 * resolves the prompt; the failure is encoded in the final assistant
 * message with stopReason "error" + errorMessage), or the assistant text.
 */
class ScriptedTaskSession implements TaskSessionLike {
  readonly messages: AgentMessage[] = [];
  readonly prompts: string[] = [];
  aborted = false;
  disposed = false;
  private listeners = new Set<(e: TaskSessionEvent) => void>();

  constructor(
    readonly sessionFile: string | undefined,
    private readonly replies: Array<string | "empty">,
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
    const reply = this.replies[Math.min(this.prompts.length - 1, this.replies.length - 1)] ?? "empty";
    if (reply === "empty") return; // HTTP 200, no assistant content at all
    if (reply.startsWith("api-error:")) {
      // The SDK does not reject on API errors — it encodes them in the
      // final assistant message (stopReason "error" + errorMessage).
      const msg = {
        role: "assistant",
        content: [],
        stopReason: "error",
        errorMessage: reply.slice("api-error:".length),
      } as unknown as AgentMessage;
      this.messages.push(msg);
      this.fire({ type: "message_end", message: msg });
      return;
    }
    const msg = mockAssistantMsg(reply);
    this.messages.push(msg);
    this.fire({ type: "message_end", message: msg });
  }

  abort(): void {
    this.aborted = true;
  }

  dispose(): void {
    this.disposed = true;
  }
}

test("TaskSessionRunner.run: API error with no assistant completion → SessionApiError (item 14 loud-fail)", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-task-"));
  try {
    const { ops } = mockGit();
    const session = new ScriptedTaskSession(path.join(dir, "x.jsonl"), [
      "api-error:403: The requested model 'matrix-coder' is not available for this API key",
    ]);
    const runner = new TaskSessionRunner({
      sessionFactory: () => Promise.resolve(session),
      git: ops,
      workspaceRoot: path.join(dir, "workspace"),
      sessionsDir: path.join(dir, "sessions"),
      missionsDir: path.join(dir, "missions"),
    });
    const log: string[] = [];
    await assert.rejects(
      runner.run(taskCtx({ onLog: (line) => log.push(line) })),
      (err: unknown) =>
        err instanceof SessionApiError &&
        err.status === 403 &&
        /HTTP 403 — The requested model 'matrix-coder' is not available for this API key/.test(err.message),
    );
    // The real error is logged, not an empty completion.
    assert.ok(log.some((l) => l.includes("failing loudly") && l.includes("HTTP 403")), "loud-fail log line");
    assert.equal(session.disposed, true, "session disposed on failure");
    // No retry prompt for an API error (the retry is for 200-empty only).
    assert.equal(session.prompts.length, 1);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("TaskSessionRunner.run: prompt() rejecting with an API error → SessionApiError (item 14 loud-fail)", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-task-"));
  try {
    const { ops } = mockGit();
    class RejectingSession implements TaskSessionLike {
      readonly messages: AgentMessage[] = [];
      readonly sessionFile: string | undefined = undefined;
      readonly prompts: string[] = [];
      aborted = false;
      disposed = false;
      private listeners = new Set<(e: TaskSessionEvent) => void>();
      subscribe(fn: (e: TaskSessionEvent) => void): () => void {
        this.listeners.add(fn);
        return () => this.listeners.delete(fn);
      }
      async prompt(): Promise<void> {
        throw new Error("401: Invalid API key");
      }
      abort(): void {
        this.aborted = true;
      }
      dispose(): void {
        this.disposed = true;
      }
    }
    const session = new RejectingSession();
    const runner = new TaskSessionRunner({
      sessionFactory: () => Promise.resolve(session),
      git: ops,
      workspaceRoot: path.join(dir, "workspace"),
      sessionsDir: path.join(dir, "sessions"),
      missionsDir: path.join(dir, "missions"),
    });
    await assert.rejects(
      runner.run(taskCtx()),
      (err: unknown) =>
        err instanceof SessionApiError && err.status === 401 && /HTTP 401 — Invalid API key/.test(err.message),
    );
    assert.equal(session.disposed, true);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("TaskSessionRunner.run: empty completion (HTTP 200, no content) → one EMPTY_RETRY_PROMPT retry, then completes (item 14)", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-task-"));
  try {
    const { ops } = mockGit();
    const session = new ScriptedTaskSession(path.join(dir, "x.jsonl"), [
      "empty",
      "Done after the retry.",
    ]);
    const runner = new TaskSessionRunner({
      sessionFactory: () => Promise.resolve(session),
      git: ops,
      workspaceRoot: path.join(dir, "workspace"),
      sessionsDir: path.join(dir, "sessions"),
      missionsDir: path.join(dir, "missions"),
    });
    const log: string[] = [];
    const result = await runner.run(taskCtx({ onLog: (line) => log.push(line) }));
    // Retried ONCE with the retry prompt, then completed with the text.
    assert.equal(session.prompts.length, 2, "exactly one retry");
    assert.equal(session.prompts[1], EMPTY_RETRY_PROMPT, "the retry uses EMPTY_RETRY_PROMPT");
    assert.equal(result.summary, "Done after the retry.");
    assert.ok(log.some((l) => l.includes("empty completion") && l.includes("retrying")), "retry log line");
    assert.equal(session.disposed, true);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("TaskSessionRunner.run: retry also empty → completes with the placeholder (exactly one retry, item 14)", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-task-"));
  try {
    const { ops } = mockGit();
    const session = new ScriptedTaskSession(path.join(dir, "x.jsonl"), ["empty", "empty"]);
    const runner = new TaskSessionRunner({
      sessionFactory: () => Promise.resolve(session),
      git: ops,
      workspaceRoot: path.join(dir, "workspace"),
      sessionsDir: path.join(dir, "sessions"),
      missionsDir: path.join(dir, "missions"),
    });
    const log: string[] = [];
    const result = await runner.run(taskCtx({ onLog: (line) => log.push(line) }));
    // Model behavior, not an API failure: completes (no error) after ONE retry.
    assert.equal(session.prompts.length, 2, "no second retry");
    assert.equal(result.summary, "(no completion summary)");
    assert.ok(log.some((l) => l.includes("retry also empty")), "retry-also-empty log line");
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
