import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { eq } from "drizzle-orm";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import type { KanbanConfig } from "../config.js";
import { initDb } from "../db/index.js";
import { ideas, projects, taskEvents, tasks, usage } from "../db/schema.js";
import type { AgentRuntime, TaskRunContext, TaskRunResult, TaskRunner } from "../agent/sessions.js";
import { GroomingManager } from "../agent/grooming.js";
import { createMockGrooming, type MockGrooming } from "../agent/grooming-mock.js";
import { Orchestrator, type DeployRunnerLike, type QaGateLike, type SummaryUpdaterLike } from "../orchestrator.js";
import type { QaRunContext, QaVerdict } from "../agent/qa.js";
import type { SummaryUpdateContext } from "../agent/summary.js";
import type { DeployContext, DeployResult } from "../deploy/index.js";
import { buildApp } from "./app.js";
import { createKanbanServices } from "../services/index.js";
import { MCP_SERVER_INFO } from "../mcp/server.js";

function testCfg(sqlitePath: string, userKeys: Record<string, string> = {}): KanbanConfig {
  return {
    litellm: { baseUrl: "https://llm.example.com/v1", apiKey: "sk-test" },
    model: "test-model",
    modelCost: undefined,
    githubToken: undefined,
    userKeys,
    db: { driver: "sqlite", sqlitePath, mysql: undefined },
    workspace: { hostPath: "/tmp/workspace", dir: "/tmp/workspace" },
    harness: { repoUrl: "https://example.com/harness", skillsPath: "agent-skills" },
    thinking: { groom: "xhigh", task: "medium", qa: "xhigh", summary: "medium" },
    mediaConcurrentTasks: 1,
    nonMediaConcurrentTasks: 1,
    agentConcurrentTasks: 1,
    agentSlugs: ["product", "analyst"],
    ownerModels: {},
    ownerModelCosts: {},
    workspaceCleanupDays: 7,
    server: { bindAddr: "127.0.0.1", port: 3000 },
  };
}

/** Mocked task pipeline (completes immediately; `hang` holds a run open). */
class MockTaskRunner implements TaskRunner {
  runs: TaskRunContext[] = [];
  aborted: number[] = [];
  behavior = new Map<number, "ok" | "fail" | "hang">();
  private resolvers = new Map<number, () => void>();

  run(ctx: TaskRunContext): Promise<TaskRunResult> {
    this.runs.push(ctx);
    const b = this.behavior.get(ctx.taskId) ?? "ok";
    if (b === "hang") {
      return new Promise<TaskRunResult>((resolve) => {
        this.resolvers.set(ctx.taskId, () =>
          resolve({ summary: `mock summary for task ${ctx.taskId}`, lastCommit: "c0ffee" }),
        );
      });
    }
    if (b === "fail") return Promise.reject(new Error("mock session crashed"));
    ctx.onLog?.("mock log line");
    ctx.onCommit?.("c0ffee");
    return Promise.resolve({ summary: `mock summary for task ${ctx.taskId}`, lastCommit: "c0ffee" });
  }

  abort(taskId: number): void {
    this.aborted.push(taskId);
    const r = this.resolvers.get(taskId);
    if (r) {
      this.resolvers.delete(taskId);
      r();
    }
  }
}

/** QA gate that always passes. */
class PassQaGate implements QaGateLike {
  readonly maxRounds = 2;
  run(_ctx: QaRunContext): Promise<QaVerdict> {
    return Promise.resolve({ pass: true, feedback: "" });
  }
}

/** Deploy stage that always succeeds. */
class OkDeployRunner implements DeployRunnerLike {
  ctxs: DeployContext[] = [];
  deploy(ctx: DeployContext): Promise<DeployResult> {
    this.ctxs.push(ctx);
    return Promise.resolve({ published: `pushed branch ${ctx.branch}`, target: "origin" });
  }
}

/** One-shot summary updater with a fixed reply. */
class FixedSummaryUpdater implements SummaryUpdaterLike {
  update(_ctx: SummaryUpdateContext): Promise<string> {
    return Promise.resolve("New project state summary.");
  }
}

/** App wired to a real (temp) sqlite db — routes + MCP hit the service layer.
 * The web UI is READ-ONLY: mutations in tests go through the service layer
 * or the MCP endpoint. Grooming runs against mocked Pi sessions (file-backed);
 * the orchestrator runs the real state machine with mocked task/QA/deploy/summary. */
async function makeApp(opts: {
  groomSlowMs?: number;
  mcpKeyCapabilities?: Map<string, Set<string>>;
  userKeys?: Record<string, string>;
  ownerModels?: Record<string, string>;
} = {}) {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-http-"));
  const cfg = testCfg(path.join(dir, "kanban.db"), opts.userKeys);
  if (opts.ownerModels) cfg.ownerModels = opts.ownerModels;
  const db = await initDb(cfg);
  const mock: MockGrooming = createMockGrooming(undefined, { slowMs: opts.groomSlowMs });
  const grooming = new GroomingManager({
    db: db.db as unknown as BetterSQLite3Database<any>,
    cfg,
    sessionFactory: mock.factory,
    workspaceRoot: path.join(dir, "workspace"),
    sessionsDir: path.join(dir, "sessions"),
  });
  mkdirSync(path.join(dir, "workspace"), { recursive: true });
  mkdirSync(path.join(dir, "sessions"), { recursive: true });
  const taskRunner = new MockTaskRunner();
  const deploy = new OkDeployRunner();
  const orchestrator = new Orchestrator({
    cfg,
    db,
    agent: {} as unknown as AgentRuntime,
    tasks: taskRunner,
    qa: new PassQaGate(),
    deploy,
    summary: new FixedSummaryUpdater(),
    workspaceRoot: path.join(dir, "workspace"),
    noTimer: true,
  });
  // Hermetic URL reachability (stage_ref / preflight): controllable fetch
  // mock + temp media-store root — no network, no real mounts in tests.
  const mediaStoreRoot = path.join(dir, "media-store");
  mkdirSync(mediaStoreRoot, { recursive: true });
  let fetchStatus = 200;
  const fetchImpl = (async (_url: string, _init?: RequestInit) =>
    new Response(null, { status: fetchStatus })) as typeof fetch;
  const services = createKanbanServices(db, {
    grooming,
    orchestrator,
    mediaStoreRoot,
    fetchImpl,
    agentSlugs: cfg.agentSlugs,
  });
  const app = buildApp({
    cfg,
    db,
    agent: {} as unknown as AgentRuntime,
    services,
    orchestrator,
    grooming,
    mcpKeyCapabilities: opts.mcpKeyCapabilities,
  });
  return { app, db, cfg, services, grooming, mock, orchestrator, taskRunner, deploy, dir, mediaStoreRoot, setFetchStatus: (s: number) => { fetchStatus = s; } };
}

/** Parse a streamable-HTTP response body (JSON or SSE) into a JSON-RPC object. */
function parseRpc(body: string): any {
  const trimmed = body.trim();
  if (trimmed.startsWith("{")) return JSON.parse(trimmed);
  const dataLines = trimmed
    .split("\n")
    .filter((l) => l.startsWith("data:"))
    .map((l) => l.slice(5).trim());
  assert.ok(dataLines.length > 0, `no data payload in SSE body: ${trimmed}`);
  return JSON.parse(dataLines[dataLines.length - 1]!);
}

/** MCP test headers: the kanban service key (LITELLM_API_KEY, full tool set). */
const MCP_HEADERS = {
  "content-type": "application/json",
  accept: "application/json, text/event-stream",
  authorization: "Bearer sk-test",
};

/** Invoke an MCP tool over the stateless streamable-HTTP endpoint. */
async function mcpCall(app: Awaited<ReturnType<typeof makeApp>>["app"], name: string, args: Record<string, unknown>) {
  const res = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: MCP_HEADERS,
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }),
  });
  assert.equal(res.statusCode, 200, `tools/call ${name} failed: ${res.payload}`);
  const rpc = parseRpc(res.payload);
  assert.ok(rpc.result, `no result: ${res.payload}`);
  return rpc.result;
}

function mcpText(result: any): any {
  assert.equal(result.content.length, 1);
  return JSON.parse(result.content[0].text);
}

/** Create a project + idea via the service layer (the UI is read-only). */
async function makeProjectAndIdea(ctx: Awaited<ReturnType<typeof makeApp>>, name: string, ideaText: string, owner = "") {
  const project = await ctx.services.createProject({ name }, owner);
  const idea = await ctx.services.addIdea(project.id, ideaText, owner);
  return { projectId: project.id, ideaId: idea.id };
}

/** drizzle's returning() is typed `Row | Row[]`; normalize to a single row. */
function one<T>(r: T | T[], label: string): T {
  const row = Array.isArray(r) ? r[0] : r;
  assert.ok(row, label);
  return row;
}

/** Poll groom_status until the grooming turn settles (finalize/seed). */
async function groomSettled(app: Awaited<ReturnType<typeof makeApp>>["app"], ideaId: number) {
  for (let i = 0; i < 50; i++) {
    const status = mcpText(await mcpCall(app, "groom_status", { idea_id: ideaId }));
    if (!status.turn.active) return status;
    await new Promise((r) => setTimeout(r, 10));
  }
  throw new Error("grooming turn did not settle");
}

/** Create a project + a task in the given state with log events + usage. */
let taskFixtureSeq = 0;
async function makeTaskFixture(
  ctx: Awaited<ReturnType<typeof makeApp>>,
  opts: { state: string; log?: boolean; usage?: boolean; owner?: string } = { state: "running" },
) {
  const { services, db } = ctx;
  const q = db.db as unknown as BetterSQLite3Database<any>;
  taskFixtureSeq += 1;
  const project = await services.createProject(
    { name: `TaskProject ${taskFixtureSeq}`, repoUrl: "https://github.com/chuck/taskproj", defaultBranch: "main", constraints: "no force-push" },
    opts.owner ?? "",
  );
  const idea = await services.addIdea(project.id, "Build the task engine", opts.owner ?? "");
  const now = Date.now();
  const task = one(
    await q
      .insert(tasks)
      .values({
        ideaId: idea.id,
        projectId: project.id,
        spec: { goal: "Build the task engine", steps: ["scaffold", "wire"], acceptance: ["tests green"], kind: "code" },
        state: opts.state,
        stateChangedAt: now,
        createdAt: now,
        branch: "task/1",
        workspace: "/workspace/task-1",
        lastCommit: "abc1234",
        owner: opts.owner ?? "",
      })
      .returning(),
    "task",
  );
  if (opts.log) {
    await q.insert(taskEvents).values([
      { taskId: task.id, ts: now, type: "state", payload: { from: "backlog", to: "running" } },
      { taskId: task.id, ts: now + 1, type: "log", payload: { line: "[tool] bash: {\"command\":\"npm test\"}" } },
      { taskId: task.id, ts: now + 2, type: "log", payload: { line: "[agent] scaffolding the engine" } },
      { taskId: task.id, ts: now + 3, type: "heartbeat", payload: { commit: "abc1234" } },
    ]);
  }
  if (opts.usage) {
    await q.insert(usage).values([
      { projectId: project.id, taskId: task.id, ts: now, role: "task", model: "m", thinking: "medium", tokensIn: 100, tokensOut: 50, cost: 1.5 },
      { projectId: project.id, taskId: task.id, ts: now, role: "qa", model: "m", thinking: "xhigh", tokensIn: 10, tokensOut: 5, cost: 0.25 },
    ]);
  }
  return { projectId: project.id, idea: idea.id, task };
}

// ---------------------------------------------------------------------------
// Read-only web UI
// ---------------------------------------------------------------------------

test("GET /health returns ok with model + db driver + user key profiles", async () => {
  const { app } = await makeApp({ userKeys: { chuck: "sk-chuck", dylan: "sk-dylan" } });
  const res = await app.inject({ method: "GET", url: "/health" });
  assert.equal(res.statusCode, 200);
  const body = res.json();
  assert.equal(body.ok, true);
  assert.equal(body.model, "test-model");
  assert.equal(body.db, "sqlite");
  assert.deepEqual(body.userKeys.sort(), ["chuck", "dylan"], "USER_KEYS profile names exposed");
  await app.close();
});

test("GET /health surfaces the owner-model map (item 15)", async () => {
  const { app } = await makeApp({
    userKeys: { strategist: "sk-strategist", marketing: "sk-marketing" },
    ownerModels: { strategist: "matrix-copywriter", marketing: "matrix-copywriter" },
  });
  const res = await app.inject({ method: "GET", url: "/health" });
  assert.equal(res.statusCode, 200);
  const body = res.json();
  // The KANBAN_OWNER_MODELS map (owner → model) alongside agentSlugs.
  assert.deepEqual(body.ownerModels, {
    strategist: "matrix-copywriter",
    marketing: "matrix-copywriter",
  });
  assert.deepEqual(body.agentSlugs, ["product", "analyst"], "agentSlugs still present");
  await app.close();
});

test("GET / renders the read-only board; mutation endpoints are gone", async () => {
  const { app, services, db } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const project = await services.createProject({ name: "Alpha", description: "alpha desc" }, "chuck");
  const idea1 = await services.addIdea(project.id, "First idea", "chuck");
  const idea2 = await services.addIdea(project.id, "Second idea", "dylan");
  const now = Date.now();
  const spec = { goal: "g", steps: [], acceptance: [], kind: "code" as const };
  await q.insert(tasks).values({
    ideaId: idea1.id,
    projectId: project.id,
    spec,
    state: "backlog",
    stateChangedAt: now,
    createdAt: now,
    owner: "chuck",
  });
  await q.insert(tasks).values({
    ideaId: idea2.id,
    projectId: project.id,
    spec,
    state: "backlog",
    stateChangedAt: now,
    createdAt: now,
    owner: "dylan",
  });

  const res = await app.inject({ method: "GET", url: "/" });
  assert.equal(res.statusCode, 200);
  assert.match(res.headers["content-type"] ?? "", /text\/html/);
  const html = res.payload;
  for (const label of ["Board", "Projects", "Reports"]) {
    assert.ok(html.includes(`>${label}<`), `nav missing ${label}`);
  }
  for (const col of ["Backlog", "Running", "Deploy", "Done", "Needs Attention"]) {
    assert.ok(html.includes(col), `board column missing: ${col}`);
  }
  assert.ok(html.includes("First idea"), "task card title");
  assert.ok(html.includes(">chuck<"), "owner tag on the board");
  assert.ok(html.includes(">dylan<"), "owner tag for the other owner");
  assert.ok(!html.includes("<form"), "read-only board: no forms");
  assert.ok(html.includes("Read-only"), "read-only hint");

  // Every former mutation endpoint is gone (404 route-not-found). Empty
  // payloads go out without a content-type (Fastify 400s on empty JSON
  // bodies before routing).
  const mutationRoutes = [
    { url: "/projects", payload: JSON.stringify({ name: "Ghost" }), json: true },
    { url: "/projects/1", payload: JSON.stringify({ name: "Ghost2" }), json: true },
    { url: "/projects/1/ideas", payload: JSON.stringify({ text: "ghost idea" }), json: true },
    { url: "/ideas/1/groom/messages", payload: JSON.stringify({ message: "hi" }), json: true },
    { url: "/ideas/1/groom/accept", payload: "" },
    { url: "/ideas/1/groom/cancel", payload: "" },
    { url: "/ideas/1/groom/re-groom", payload: "" },
    { url: "/ideas/1/discard", payload: "" },
    { url: "/projects/1/icebox/move", payload: "idea_ids=1" },
    { url: "/tasks/1/pause", payload: JSON.stringify({}), json: true },
    { url: "/tasks/1/resume", payload: JSON.stringify({}), json: true },
    { url: "/tasks/1/stop", payload: JSON.stringify({}), json: true },
    { url: "/tasks/1/retry-deploy", payload: JSON.stringify({}), json: true },
    { url: "/tasks/1/resolve/messages", payload: JSON.stringify({ message: "hi" }), json: true },
    { url: "/tasks/1/resolve/accept", payload: JSON.stringify({}), json: true },
  ];
  for (const route of mutationRoutes) {
    const gone = await app.inject({
      method: "POST",
      url: route.url,
      headers: route.json ? { "content-type": "application/json" } : {},
      payload: route.payload,
    });
    assert.equal(gone.statusCode, 404, `POST ${route.url} should be gone`);
  }
  await app.close();
});

test("GET /projects renders the read-only project list", async () => {
  const { app, services } = await makeApp();
  await services.createProject({ name: "Alpha", description: "alpha desc" }, "chuck");
  await services.createProject({ name: "Beta", description: "beta desc" });

  const res = await app.inject({ method: "GET", url: "/projects" });
  assert.equal(res.statusCode, 200);
  const html = res.payload;
  assert.ok(html.includes("Alpha"), "project name in list");
  assert.ok(html.includes("alpha desc"), "description in list");
  assert.ok(html.includes(">chuck<"), "owner column");
  assert.ok(!html.includes("<form"), "read-only list: no forms");
  assert.ok(!html.includes("New project"), "no create dialog");
  await app.close();
});

test("GET /projects/<id> renders the read-only project page", async () => {
  const { app, services, db } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const project = await services.createProject(
    {
      name: "Alpha",
      description: "alpha desc",
      goal: "ship it",
      repoUrl: "https://github.com/chuck/alpha",
      defaultBranch: "main",
      constraints: "never force-push",
    },
    "chuck",
  );
  const idea = await services.addIdea(project.id, "An idea", "chuck");
  void idea;
  await q.update(projects).set({ stateSummary: "state summary text" }).where(eq(projects.id, project.id));

  const res = await app.inject({ method: "GET", url: `/projects/${project.id}` });
  assert.equal(res.statusCode, 200);
  const html = res.payload;
  for (const col of ["Idea", "Grooming", "Icebox"]) {
    assert.ok(html.includes(`<h2>${col} `), `pipeline column missing: ${col}`);
  }
  assert.ok(html.includes("alpha desc"), "settings: description");
  assert.ok(html.includes("ship it"), "settings: goal");
  assert.ok(html.includes("https://github.com/chuck/alpha (main)"), "settings: repo + branch");
  assert.ok(html.includes("never force-push"), "settings: constraints");
  assert.ok(html.includes("State summary"), "state summary section");
  assert.ok(html.includes(">chuck<"), "owner shown in settings");
  assert.ok(!html.includes("<form"), "read-only page: no forms");
  assert.ok(!html.includes('id="idea-drop"'), "no idea-drop dialog");
  assert.ok(!html.includes('id="project-editor"'), "no project editor dialog");
  assert.ok(html.includes("MCP"), "points at the MCP tools");

  const missing = await app.inject({ method: "GET", url: "/projects/999" });
  assert.equal(missing.statusCode, 404);
  await app.close();
});

test("project page + grooming page show live 'agent working' indicators while a turn is in flight", async () => {
  const ctx = await makeApp({ groomSlowMs: 300 });
  const { app } = ctx;
  const { projectId, ideaId } = await makeProjectAndIdea(ctx, "Badge", "Badge idea", "chuck");

  // Start grooming via MCP (fire-and-forget: the seed turn — 300ms mock —
  // is in flight while we render the pages).
  const startedP = mcpCall(app, "start_grooming", { idea_id: ideaId });
  await new Promise((r) => setTimeout(r, 50));

  // Project page: the Grooming column card carries the working badge.
  const proj = await app.inject({ method: "GET", url: `/projects/${projectId}` });
  assert.ok(proj.payload.includes("groom-badge working"), "working badge in Grooming column");
  assert.ok(proj.payload.includes("agent working"), "badge text");

  // Grooming page: the banner is shown while the seed runs.
  const groom = await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` });
  assert.ok(groom.payload.includes('<div class="groom-banner">'), "working banner on the grooming page");
  assert.ok(groom.payload.includes("The agent is working on this idea"), "banner text");

  // The seed settles; the MCP call resolves with the idea + seed message.
  const started = mcpText(await startedP);
  assert.equal(started.idea.state, "grooming");
  assert.ok(started.lastAssistant.length > 0, "seed assistant message");

  // After the seed settles: no working badge, no banner.
  const proj2 = await app.inject({ method: "GET", url: `/projects/${projectId}` });
  assert.ok(!proj2.payload.includes("groom-badge working"), "no working badge after settle");
  const groom2 = await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` });
  assert.ok(!groom2.payload.includes('<div class="groom-banner">'), "no banner after settle");
  await app.close();
});

test("board shows task cards with tag, usage, deps, and month stats", async () => {
  const { app, db, services } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const now = Date.now();

  const alpha = await services.createProject({ name: "Alpha" }, "chuck");
  const beta = await services.createProject({ name: "Beta" }, "dylan");

  // Ideas: a1 (Alpha), a2 (Alpha, depends on a1), a3 (Alpha), b1 (Beta).
  const a1 = await services.addIdea(alpha.id, "First idea", "chuck");
  const a2 = await services.addIdea(alpha.id, "Second idea", "chuck");
  const a3 = await services.addIdea(alpha.id, "Third idea", "chuck");
  const b1 = await services.addIdea(beta.id, "Beta idea", "dylan");
  await q.update(ideas).set({ dependsOn: [a1.id] }).where(eq(ideas.id, a2.id));

  // Tasks: t1 (a1, running), t2 (a2, backlog — waiting on a1), t3 (b1, running), t4 (a3, done).
  const spec = { goal: "g", steps: [], acceptance: [], kind: "code" as const };
  const t1 = one(
    await q
      .insert(tasks)
      .values({ ideaId: a1.id, projectId: alpha.id, spec, state: "running", stateChangedAt: now, createdAt: now, owner: "chuck" })
      .returning(),
    "t1",
  );
  const t2 = one(
    await q
      .insert(tasks)
      .values({ ideaId: a2.id, projectId: alpha.id, spec, state: "backlog", stateChangedAt: now, createdAt: now, owner: "chuck" })
      .returning(),
    "t2",
  );
  const t3 = one(
    await q
      .insert(tasks)
      .values({ ideaId: b1.id, projectId: beta.id, spec, state: "running", stateChangedAt: now, createdAt: now, owner: "dylan" })
      .returning(),
    "t3",
  );
  const t4 = one(
    await q
      .insert(tasks)
      .values({ ideaId: a3.id, projectId: alpha.id, spec, state: "done", stateChangedAt: now, createdAt: now, owner: "chuck" })
      .returning(),
    "t4",
  );

  await q.insert(usage).values([
    { projectId: alpha.id, taskId: t1.id, ts: now, role: "task", model: "m", thinking: "medium", tokensIn: 100, tokensOut: 50, cost: 1.5 },
    { projectId: alpha.id, taskId: t2.id, ts: now, role: "task", model: "m", thinking: "medium", tokensIn: 10, tokensOut: 5, cost: 0.25 },
    { projectId: beta.id, taskId: null, ts: now, role: "groom", model: "m", thinking: "xhigh", tokensIn: 10, tokensOut: 5, cost: 0.1 },
  ]);

  const res = await app.inject({ method: "GET", url: "/" });
  assert.equal(res.statusCode, 200);
  const html = res.payload;
  assert.ok(html.includes("First idea"), "running card title");
  assert.ok(html.includes("Second idea"), "backlog card title");
  assert.ok(html.includes("Third idea"), "done card title");
  assert.ok(html.includes("Beta idea"), "running card title (Beta)");
  assert.ok(html.includes("waiting on: First idea"), "dependency status");
  assert.ok(html.includes("$1.50"), "running card usage");
  assert.ok(html.includes("$0.25"), "backlog card usage");
  assert.ok(html.includes("$1.85"), "month spend incl. null-task grooming (1.50+0.25+0.10)");
  assert.ok(html.includes(">1<"), "month completed count");
  assert.ok(html.includes('class="tag owner"'), "owner tag on task cards");
  await app.close();
});

// ---------------------------------------------------------------------------
// MCP endpoint
// ---------------------------------------------------------------------------

test("POST /mcp auth: actions require a key; discovery is open (proxy registry)", async () => {
  const { app } = await makeApp();
  // Unauthenticated ACTION (tools/call) → 401.
  const noAuthCall = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "list_projects", arguments: {} } }),
  });
  assert.equal(noAuthCall.statusCode, 401);
  // Unauthenticated DISCOVERY (initialize) → 200: the LiteLLM proxy's
  // startup tools/list handshake carries no caller key.
  const noAuthInit = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: { "content-type": "application/json", accept: "application/json, text/event-stream" },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
  });
  assert.equal(noAuthInit.statusCode, 200);
  // Unauthenticated tools/list → the FULL tool set (the proxy builds one
  // global registry from it; per-key scoping is enforced at call time).
  const noAuthList = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: { "content-type": "application/json", accept: "application/json, text/event-stream" },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }),
  });
  assert.equal(noAuthList.statusCode, 200);
  const rpc = parseRpc(noAuthList.payload);
  const names = rpc.result.tools.map((t: any) => t.name).sort();
  assert.equal(names.length, 29, `expected the full 29-tool set, got ${names.length}`);
  // Unknown key → 401 (even for discovery — only the no-key case is open).
  const wrongAuth = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: { "content-type": "application/json", authorization: "Bearer wrong" },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
  });
  assert.equal(wrongAuth.statusCode, 401);
  await app.close();
});

test("POST /mcp answers the initialize handshake", async () => {
  const { app } = await makeApp();
  const res = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: MCP_HEADERS,
    payload: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "initialize",
      params: {
        protocolVersion: "2025-03-26",
        capabilities: {},
        clientInfo: { name: "test-client", version: "1.0.0" },
      },
    }),
  });
  assert.equal(res.statusCode, 200);
  const rpc = parseRpc(res.payload);
  assert.equal(rpc.id, 1);
  assert.ok(rpc.result, `no result: ${res.payload}`);
  assert.equal(rpc.result.serverInfo.name, MCP_SERVER_INFO.name);
  await app.close();
});

test("POST /mcp tools/list returns the 29-tool set", async () => {
  const { app } = await makeApp();
  const res = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: MCP_HEADERS,
    payload: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }),
  });
  assert.equal(res.statusCode, 200);
  const rpc = parseRpc(res.payload);
  const names = rpc.result.tools.map((t: any) => t.name).sort();
  assert.deepEqual(names, [
    "add_idea",
    "agents_switch",
    "board_status",
    "create_project",
    "delete_project",
    "discard_idea",
    "edit_idea",
    "get_project",
    "groom_accept",
    "groom_cancel",
    "groom_message",
    "groom_re_groom",
    "groom_status",
    "list_ideas",
    "list_projects",
    "merge_task",
    "move_to_backlog",
    "pause_task",
    "project_status",
    "restart_task",
    "resume_task",
    "retry_deploy",
    "stage_file",
    "stage_ref",
    "start_grooming",
    "start_task",
    "stop_task",
    "task_status",
    "update_project",
  ]);
  await app.close();
});

test("MCP tools: project + idea round-trip with owner attribution", async () => {
  const { app, services } = await makeApp();
  const created = mcpText(await mcpCall(app, "create_project", { name: "MCP Project", description: "via mcp" }));
  assert.equal(created.name, "MCP Project");
  assert.equal(created.owner, "kanban", "the kanban key's owner is stamped");

  const listed = mcpText(await mcpCall(app, "list_projects", {}));
  assert.ok(listed.some((p: any) => p.name === "MCP Project"), "list_projects includes the new project");

  const fetched = mcpText(await mcpCall(app, "get_project", { project_id: created.id }));
  assert.equal(fetched.description, "via mcp");
  assert.equal(fetched.owner, "kanban");

  const updated = mcpText(await mcpCall(app, "update_project", { project_id: created.id, name: "MCP Project 2" }));
  assert.equal(updated.name, "MCP Project 2");
  assert.equal(updated.description, "via mcp", "partial update keeps fields");

  const idea = mcpText(await mcpCall(app, "add_idea", { project_id: created.id, text: "mcp idea" }));
  assert.equal(idea.state, "idea");
  assert.equal(idea.projectName, "MCP Project 2");
  assert.equal(idea.owner, "kanban", "idea owner stamped from the key");

  const ideas = mcpText(await mcpCall(app, "list_ideas", { project_id: created.id }));
  assert.ok(ideas.some((i: any) => i.text === "mcp idea"), "list_ideas includes the new idea");
  assert.equal(ideas[0].owner, "kanban");

  // Errors surface as isError results.
  const missing = await mcpCall(app, "get_project", { project_id: 999 });
  assert.equal(missing.isError, true);
  assert.match(missing.content[0].text, /not found/);
  const dup = await mcpCall(app, "create_project", { name: "MCP Project 2" });
  assert.equal(dup.isError, true);
  assert.match(dup.content[0].text, /already exists/);

  // The service layer sees the same data (shared service layer).
  const rest = await services.listProjects();
  assert.ok(rest.some((p) => p.name === "MCP Project 2"));
  await app.close();
});

test("GET /mcp is not a valid MCP method", async () => {
  const { app } = await makeApp();
  const res = await app.inject({ method: "GET", url: "/mcp" });
  assert.equal(res.statusCode, 405);
  await app.close();
});

// ---------------------------------------------------------------------------
// MCP interactive grooming (start → message → accept / cancel / re-groom)
// ---------------------------------------------------------------------------

test("MCP interactive grooming: start → message → status → accept → icebox", async () => {
  const ctx = await makeApp();
  const { app, services } = ctx;
  const { projectId, ideaId } = await makeProjectAndIdea(ctx, "Groom", "Build a kanban export", "chuck");

  // start_grooming: seed turn completes (mock), idea is in grooming.
  const started = mcpText(await mcpCall(app, "start_grooming", { idea_id: ideaId }));
  assert.equal(started.idea.state, "grooming");
  assert.ok(started.lastAssistant.length > 0, "seed assistant message");
  assert.equal(started.idea.owner, "chuck", "idea owner preserved");

  // groom_message: a user question + the assistant's reply.
  const msg = mcpText(await mcpCall(app, "groom_message", { idea_id: ideaId, text: "Should it export to CSV?" }));
  assert.equal(msg.role, "assistant");
  assert.ok(msg.text.length > 0, "assistant reply");

  // groom_status: state + turn + transcript tail.
  const status = mcpText(await mcpCall(app, "groom_status", { idea_id: ideaId }));
  assert.equal(status.state, "grooming");
  assert.equal(status.turn.active, false);
  assert.ok(status.messages.length >= 4, "transcript tail (seed pair + chat pair)");
  assert.equal(status.messages[status.messages.length - 1].role, "assistant");

  // groom_accept: background finalize → poll until settled → icebox + spec.
  const accepted = mcpText(await mcpCall(app, "groom_accept", { idea_id: ideaId }));
  assert.equal(accepted.state, "grooming", "still grooming while finalizing");
  const settled = await groomSettled(app, ideaId);
  assert.equal(settled.turn.active, false);
  assert.equal(settled.state, "icebox");
  assert.equal(settled.spec?.goal, "Mock goal");
  const idea = await services.getIdea(ideaId);
  assert.equal(idea?.state, "icebox");
  assert.equal(idea?.spec?.goal, "Mock goal");

  // Guards.
  const notGrooming = await mcpCall(app, "groom_message", { idea_id: ideaId, text: "too late" });
  assert.equal(notGrooming.isError, true);
  assert.match(notGrooming.content[0].text, /is in state "icebox"/);
  const missing = await mcpCall(app, "start_grooming", { idea_id: 999 });
  assert.equal(missing.isError, true);
  assert.match(missing.content[0].text, /not found/);
  await app.close();
});

test("MCP grooming: cancel back to idea, re_groom (fresh session), discard_idea", async () => {
  const ctx = await makeApp();
  const { app, services } = ctx;
  const { projectId, ideaId } = await makeProjectAndIdea(ctx, "Groom2", "Another idea", "chuck");

  // start → cancel: back to idea.
  await mcpCall(app, "start_grooming", { idea_id: ideaId });
  const cancelled = mcpText(await mcpCall(app, "groom_cancel", { idea_id: ideaId }));
  assert.equal(cancelled.state, "idea");
  assert.equal((await services.getIdea(ideaId))?.state, "idea");

  // Guards: start_grooming on a non-idea/grooming idea → isError.
  const iceboxed = await services.addIdea(projectId, "Iceboxed idea", "chuck");
  const spec = { goal: "g", steps: [], acceptance: [], kind: "code" as const };
  const q = ctx.db.db as unknown as BetterSQLite3Database<any>;
  await q.update(ideas).set({ state: "icebox", spec, dependsOn: [] }).where(eq(ideas.id, iceboxed.id));
  const notIdea = await mcpCall(app, "start_grooming", { idea_id: iceboxed.id });
  assert.equal(notIdea.isError, true);
  assert.match(notIdea.content[0].text, /is in state "icebox"/);
  // re_groom expects the grooming state (a fresh-session restart of a
  // conversation that went off the rails) — not the icebox.
  const notGrooming = await mcpCall(app, "groom_re_groom", { idea_id: iceboxed.id });
  assert.equal(notGrooming.isError, true);
  assert.match(notGrooming.content[0].text, /is in state "icebox"/);

  // re_groom: grooming → grooming with a fresh session (old chat discarded,
  // re-seeded with the idea).
  await mcpCall(app, "start_grooming", { idea_id: ideaId });
  await mcpCall(app, "groom_message", { idea_id: ideaId, text: "a question" });
  const statusBefore = mcpText(await mcpCall(app, "groom_status", { idea_id: ideaId }));
  assert.ok(statusBefore.messages.length >= 4, "seed pair + chat pair");
  const reGroomed = mcpText(await mcpCall(app, "groom_re_groom", { idea_id: ideaId }));
  assert.equal(reGroomed.state, "grooming");
  const statusAfter = mcpText(await mcpCall(app, "groom_status", { idea_id: ideaId }));
  assert.equal(statusAfter.messages.length, 2, "fresh session: only the seed pair");
  // Cancel again to leave it in a clean state.
  await mcpCall(app, "groom_cancel", { idea_id: ideaId });

  // discard_idea: soft delete.
  const idea3 = await services.addIdea(projectId, "Trash idea", "chuck");
  const discarded = mcpText(await mcpCall(app, "discard_idea", { idea_id: idea3.id }));
  assert.equal(discarded.state, "discarded");
  assert.equal((await services.getIdea(idea3.id))?.state, "discarded");
  const listed = mcpText(await mcpCall(app, "list_ideas", { project_id: projectId }));
  assert.ok(!listed.some((i: any) => i.id === idea3.id), "discarded ideas are not listed");
  // Guards.
  const again = await mcpCall(app, "discard_idea", { idea_id: idea3.id });
  assert.equal(again.isError, true);
  assert.match(again.content[0].text, /is in state "discarded"/);
  const missing = await mcpCall(app, "discard_idea", { idea_id: 999 });
  assert.equal(missing.isError, true);
  assert.match(missing.content[0].text, /not found/);
  await app.close();
});

test("MCP board_status: counts + needs_attention + running + filters", async () => {
  const ctx = await makeApp();
  const { app, db } = ctx;
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const now = Date.now();
  const { projectId, ideaId } = await makeProjectAndIdea(ctx, "Board", "Stuck idea", "chuck");
  const { projectId: dylanProjectId } = await makeProjectAndIdea(ctx, "Board2", "Dylan idea", "dylan");

  const spec = { goal: "g", steps: [], acceptance: [], kind: "code" as const };
  const idea2 = await ctx.services.addIdea(projectId, "Running idea", "dylan");
  const idea3 = await ctx.services.addIdea(projectId, "Backlog idea", "chuck");
  const stuck = one(
    await q
      .insert(tasks)
      .values({ ideaId, projectId, spec, state: "needs_attention", stateChangedAt: now, createdAt: now, owner: "chuck" })
      .returning(),
    "stuck",
  );
  const running = one(
    await q
      .insert(tasks)
      .values({ ideaId: idea2.id, projectId, spec, state: "running", stateChangedAt: now, createdAt: now, owner: "dylan" })
      .returning(),
    "running",
  );
  const backlog = one(
    await q
      .insert(tasks)
      .values({ ideaId: idea3.id, projectId, spec, state: "backlog", stateChangedAt: now, createdAt: now, owner: "chuck" })
      .returning(),
    "backlog",
  );
  await q.insert(taskEvents).values([
    { taskId: stuck.id, ts: now - 60000, type: "state", payload: { from: "running", to: "needs_attention", reason: "watchdog: no activity" } },
    { taskId: stuck.id, ts: now - 30000, type: "log", payload: { line: "last line" } },
    { taskId: running.id, ts: now - 1000, type: "heartbeat", payload: { kind: "watchdog" } },
  ]);
  await q.insert(usage).values([
    { projectId, taskId: running.id, ts: now, role: "task", model: "m", thinking: "medium", tokensIn: 10, tokensOut: 5, cost: 0.42 },
  ]);

  const status = mcpText(await mcpCall(app, "board_status", {}));
  assert.deepEqual(status.counts, { backlog: 1, running: 1, deploy: 0, done: 0, needs_attention: 1 });
  assert.equal(status.needsAttention.length, 1);
  const na = status.needsAttention[0];
  assert.equal(na.taskId, stuck.id);
  assert.equal(na.title, "Stuck idea");
  assert.equal(na.project, "Board");
  assert.equal(na.owner, "chuck");
  assert.equal(na.reason, "watchdog: no activity");
  assert.equal(na.lastActivityAt, now - 30000);
  assert.equal(na.resolution, null);
  assert.equal(status.running.length, 1);
  assert.equal(status.running[0].taskId, running.id);
  assert.equal(status.running[0].cost, 0.42);

  // Filters.
  const byProject = mcpText(await mcpCall(app, "board_status", { project_id: dylanProjectId }));
  assert.deepEqual(byProject.counts, { backlog: 0, running: 0, deploy: 0, done: 0, needs_attention: 0 });
  const byOwner = mcpText(await mcpCall(app, "board_status", { owner: "dylan" }));
  assert.equal(byOwner.counts.running, 1);
  assert.equal(byOwner.counts.backlog, 0);
  assert.deepEqual(byOwner.needsAttention, []);

  // The resolution loop: task_status carries the failure context.
  const taskStatus = mcpText(await mcpCall(app, "task_status", { task_id: stuck.id }));
  assert.equal(taskStatus.state, "needs_attention");
  assert.equal(taskStatus.failureReason, "watchdog: no activity");
  assert.equal(taskStatus.owner, "chuck");
  void backlog;
  await app.close();
});

test("MCP move_to_backlog: owner inherited from the idea", async () => {
  const ctx = await makeApp();
  const { app, services, db } = ctx;
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const { projectId, ideaId } = await makeProjectAndIdea(ctx, "Move", "Move idea", "dylan");
  const spec = { goal: "g", steps: [], acceptance: [], kind: "code" as const };
  await q.update(ideas).set({ state: "icebox", spec, dependsOn: [] }).where(eq(ideas.id, ideaId));

  const moved = mcpText(await mcpCall(app, "move_to_backlog", { idea_ids: [ideaId] }));
  assert.equal(moved.tasks.length, 1);
  assert.equal(moved.tasks[0].state, "backlog");
  assert.equal(moved.tasks[0].owner, "dylan", "owner inherited from the idea");
  assert.equal((await services.getIdea(ideaId))?.state, "moved");

  const notIcebox = await mcpCall(app, "move_to_backlog", { idea_ids: [999] });
  assert.equal(notIcebox.isError, true);
  assert.match(notIcebox.content[0].text, /not found/);
  await app.close();
});

test("MCP move_to_backlog: spec-path preflight — advisory warning, move proceeds", async () => {
  const ctx = await makeApp();
  const { app, services, db, setFetchStatus } = ctx;
  setFetchStatus(404); // the spec's URL is dead
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const { ideaId } = await makeProjectAndIdea(ctx, "Pre", "Pre idea", "chuck");
  const spec = {
    goal: "run the frozen script ~/Code/media-film/potato-wars-v2/frozen.py",
    steps: ["cite https://choukalos.com/files/missing.mp4"],
    acceptance: [],
    kind: "media" as const,
  };
  await q.update(ideas).set({ state: "icebox", spec, dependsOn: [] }).where(eq(ideas.id, ideaId));

  const moved = mcpText(await mcpCall(app, "move_to_backlog", { idea_ids: [ideaId] }));
  // Advisory: the move proceeds...
  assert.equal(moved.tasks.length, 1);
  assert.equal(moved.tasks[0].state, "backlog");
  // ...but the result carries the structured preflight warning.
  assert.equal(moved.preflight.unreachable.length, 2);
  const refs = moved.preflight.unreachable.map((r: any) => r.ref).sort();
  assert.deepEqual(refs, [
    "https://choukalos.com/files/missing.mp4",
    "~/Code/media-film/potato-wars-v2/frozen.py",
  ]);
  assert.equal((await services.getIdea(ideaId))?.state, "moved");
  await app.close();
});

test("MCP move_to_backlog: preflight strict (KANBAN_PREFLIGHT_STRICT=1) refuses unreachable specs", async () => {
  process.env.KANBAN_PREFLIGHT_STRICT = "1";
  try {
    const ctx = await makeApp();
    const { app, services, db, setFetchStatus } = ctx;
    setFetchStatus(404);
    const q = db.db as unknown as BetterSQLite3Database<any>;
    const { ideaId } = await makeProjectAndIdea(ctx, "PreStrict", "Pre strict idea", "chuck");
    const spec = {
      goal: "run the frozen script ~/Code/media-film/potato-wars-v2/frozen.py",
      steps: ["cite https://choukalos.com/files/missing.mp4"],
      acceptance: [],
      kind: "media" as const,
    };
    await q.update(ideas).set({ state: "icebox", spec, dependsOn: [] }).where(eq(ideas.id, ideaId));

    const res = await mcpCall(app, "move_to_backlog", { idea_ids: [ideaId] });
    assert.equal(res.isError, true);
    assert.match(res.content[0].text, /preflight strict/);
    assert.match(res.content[0].text, /~\/Code\/media-film\/potato-wars-v2\/frozen\.py/);
    // Refused before the move: the idea stays in the icebox.
    assert.equal((await services.getIdea(ideaId))?.state, "icebox");
    await app.close();
  } finally {
    delete process.env.KANBAN_PREFLIGHT_STRICT;
  }
});

test("MCP start_task: spec-path preflight — advisory warning on unreachable refs", async () => {
  const ctx = await makeApp();
  const { app, db } = ctx;
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const { task } = await makeTaskFixture(ctx, { state: "backlog" });
  await q
    .update(tasks)
    .set({
      spec: {
        goal: "run ~/Code/media-film/potato-wars-v2/frozen.py",
        steps: [],
        acceptance: [],
        kind: "media",
      },
    })
    .where(eq(tasks.id, task.id));

  const started = mcpText(await mcpCall(app, "start_task", { task_id: task.id }));
  // Advisory: the task starts...
  assert.equal(started.state, "running");
  // ...but the result carries the structured preflight warning.
  assert.equal(started.preflight.unreachable.length, 1);
  assert.equal(started.preflight.unreachable[0].ref, "~/Code/media-film/potato-wars-v2/frozen.py");
  await ctx.orchestrator.settled();
  await app.close();
});

test("MCP tools: start_task / task_status / restart_task / retry_deploy", async () => {
  const ctx = await makeApp();
  const { app, db, orchestrator } = ctx;
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const { projectId, task } = await makeTaskFixture(ctx, { state: "backlog", log: true, usage: true });

  // A second model on the same task (item 16: byModel aggregation).
  await q.insert(usage).values([
    { projectId, taskId: task.id, ts: Date.now(), role: "task", model: "m2", thinking: "medium", tokensIn: 40, tokensOut: 20, cost: 0.5 },
  ]);

  // task_status: state + log tail + usage (total + by role + by model),
  // no failure reason yet.
  let status = mcpText(await mcpCall(app, "task_status", { task_id: task.id }));
  assert.equal(status.state, "backlog");
  assert.ok(status.logTail.length > 0, "log tail");
  assert.ok(status.usageTotal > 0, "usage total");
  // byRole: the fixture's task row (1.5) + the m2 task row (0.5); byModel:
  // the fixture's task+qa rows (model m) + the m2 row.
  assert.deepEqual(status.usageByRole, { task: 2.0, qa: 0.25 }, "usage by role");
  assert.deepEqual(status.usageByModel, {
    m: { tokensIn: 110, tokensOut: 55, cost: 1.75 },
    m2: { tokensIn: 40, tokensOut: 20, cost: 0.5 },
  });
  assert.equal(status.failureReason, null);

  // start_task: backlog → running (the mock pipeline then completes it).
  const started = mcpText(await mcpCall(app, "start_task", { task_id: task.id }));
  assert.equal(started.state, "running");
  await orchestrator.settled();
  status = mcpText(await mcpCall(app, "task_status", { task_id: task.id }));
  assert.equal(status.state, "done", "pipeline settled to done");

  // restart_task: needs_attention → backlog with a resolution note.
  const { task: t2 } = await makeTaskFixture(ctx, { state: "needs_attention", log: true });
  await q.insert(taskEvents).values({
    taskId: t2.id,
    ts: Date.now(),
    type: "state",
    payload: { from: "running", to: "needs_attention", reason: "QA exhausted after 2 rounds" },
  });
  const restarted = mcpText(await mcpCall(app, "restart_task", { task_id: t2.id, resolution_note: "fix auth, re-run" }));
  assert.equal(restarted.state, "backlog");
  assert.equal(restarted.qaRounds, 0, "QA rounds reset");
  assert.equal(restarted.resolution, "fix auth, re-run");
  status = mcpText(await mcpCall(app, "task_status", { task_id: t2.id }));
  assert.equal(status.failureReason, "QA exhausted after 2 rounds");
  assert.equal(status.resolution, "fix auth, re-run");

  // retry_deploy: deploy failure → needs_attention → retry → done.
  const { task: t3 } = await makeTaskFixture(ctx, { state: "needs_attention" });
  await q.insert(taskEvents).values({
    taskId: t3.id,
    ts: Date.now(),
    type: "state",
    payload: { from: "deploy", to: "needs_attention", reason: "deploy failed: push failed: auth" },
  });
  const redeployed = mcpText(await mcpCall(app, "retry_deploy", { task_id: t3.id }));
  assert.equal(redeployed.state, "done", "deploy re-run → done");

  // retry_deploy refuses QA-exhausted tasks (resolution via restart_task first).
  const { task: t4 } = await makeTaskFixture(ctx, { state: "needs_attention" });
  await q.insert(taskEvents).values({
    taskId: t4.id,
    ts: Date.now(),
    type: "state",
    payload: { from: "running", to: "needs_attention", reason: "QA exhausted after 2 rounds" },
  });
  const refused = await mcpCall(app, "retry_deploy", { task_id: t4.id });
  assert.equal(refused.isError, true);
  assert.match(refused.content[0].text, /failed QA/);

  // Guards: start_task on a non-backlog task → isError.
  const guard = await mcpCall(app, "start_task", { task_id: t3.id });
  assert.equal(guard.isError, true);
  assert.match(guard.content[0].text, /not in the backlog/);
  await app.close();
});

test("MCP tools: pause_task / resume_task / stop_task", async () => {
  const ctx = await makeApp();
  const { app, db, orchestrator, taskRunner } = ctx;
  const { task } = await makeTaskFixture(ctx, { state: "backlog" });
  taskRunner.behavior.set(task.id, "hang");
  await orchestrator.startTask(task.id);

  // stop_task → paused (state stays running).
  const stopped = mcpText(await mcpCall(app, "stop_task", { task_id: task.id }));
  assert.equal(stopped.paused, true);
  assert.equal(stopped.state, "running");

  // pause_task on an already-paused task → isError.
  const refused = await mcpCall(app, "pause_task", { task_id: task.id });
  assert.equal(refused.isError, true);
  assert.match(refused.content[0].text, /already paused/);

  // resume_task → un-paused; the resumed run re-launches and completes.
  taskRunner.behavior.delete(task.id);
  const runsBefore = taskRunner.runs.length;
  const resumed = mcpText(await mcpCall(app, "resume_task", { task_id: task.id }));
  assert.equal(resumed.paused, false);
  await orchestrator.settled();
  assert.equal(taskRunner.runs.length, runsBefore + 1, "resumed run re-launched");

  // resume_task on a non-paused task → isError.
  const guard = await mcpCall(app, "resume_task", { task_id: task.id });
  assert.equal(guard.isError, true);
  assert.match(guard.content[0].text, /not paused/);
  await app.close();
});

test("MCP project_status: state summary + icebox listing + task counts", async () => {
  const ctx = await makeApp();
  const { app, db } = ctx;
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const project = mcpText(await mcpCall(app, "create_project", { name: "Alpha", goal: "ship it" }));
  const projectId = project.id;

  // LLM-maintained state summary (normally written by the summary session).
  await q.update(projects).set({ stateSummary: "Widget API is live; dark mode deployed." }).where(eq(projects.id, projectId));

  // Two icebox items (one depends on the other) + one idea outside the icebox.
  const idea1 = (await ctx.services.addIdea(projectId, "Icebox item one")).id;
  const idea2 = (await ctx.services.addIdea(projectId, "Icebox item two")).id;
  await ctx.services.addIdea(projectId, "Still a raw idea");
  const spec1 = { goal: "Build the widget API", steps: ["scaffold"], acceptance: ["tests green"], kind: "code" as const };
  const spec2 = { goal: "Dark mode", steps: ["theme"], acceptance: ["dark"], kind: "blog" as const };
  await q.update(ideas).set({ state: "icebox", spec: spec1, dependsOn: [] }).where(eq(ideas.id, idea1));
  await q.update(ideas).set({ state: "icebox", spec: spec2, dependsOn: [idea1] }).where(eq(ideas.id, idea2));

  // Board tasks: one done, one running.
  const idea3 = (await ctx.services.addIdea(projectId, "Done item")).id;
  await q.insert(tasks).values({
    ideaId: idea3,
    projectId,
    spec: { goal: "g", steps: [], acceptance: [], kind: "code" },
    state: "done",
    stateChangedAt: Date.now(),
    createdAt: Date.now(),
  });
  const idea4 = (await ctx.services.addIdea(projectId, "Running item")).id;
  await q.insert(tasks).values({
    ideaId: idea4,
    projectId,
    spec: { goal: "g", steps: [], acceptance: [], kind: "code" },
    state: "running",
    stateChangedAt: Date.now(),
    createdAt: Date.now(),
  });

  const status = mcpText(await mcpCall(app, "project_status", { project_id: projectId }));
  assert.equal(status.name, "Alpha");
  assert.equal(status.goal, "ship it");
  assert.equal(status.stateSummary, "Widget API is live; dark mode deployed.");
  assert.equal(status.icebox.length, 2, "icebox listing (raw idea excluded)");
  const one_ = status.icebox.find((i: any) => i.id === idea1);
  const two_ = status.icebox.find((i: any) => i.id === idea2);
  assert.equal(one_.spec.goal, "Build the widget API");
  assert.deepEqual(one_.dependsOn, []);
  assert.equal(two_.spec.kind, "blog");
  assert.deepEqual(two_.dependsOn, [idea1]);
  assert.deepEqual(status.taskCounts, { done: 1, running: 1 });

  // Unknown project → isError.
  const missing = await mcpCall(app, "project_status", { project_id: 99999 });
  assert.equal(missing.isError, true);
  assert.match(missing.content[0].text, /not found/);
  await app.close();
});

// ---------------------------------------------------------------------------
// Task detail page (read-only) + grooming transcript viewer + reports
// ---------------------------------------------------------------------------

test("GET /tasks/<id> renders the read-only task detail with log tail, usage, owner", async () => {
  const ctx = await makeApp();
  const { app, db } = ctx;
  const { task } = await makeTaskFixture(ctx, { state: "running", log: true, usage: true, owner: "chuck" });

  const res = await app.inject({ method: "GET", url: `/tasks/${task.id}` });
  assert.equal(res.statusCode, 200);
  assert.match(res.headers["content-type"] ?? "", /text\/html/);
  const html = res.payload;
  assert.ok(html.includes(`Task #${task.id}`), "task heading");
  assert.ok(html.includes("Build the task engine"), "idea text");
  assert.ok(html.includes("state-running"), "state badge");
  assert.ok(html.includes("/workspace/task-1"), "workspace path");
  assert.ok(html.includes("task/1"), "branch");
  assert.ok(html.includes("abc1234"), "last commit");
  assert.ok(html.includes("tests green"), "acceptance criterion");
  assert.ok(html.includes("$1.75"), "usage so far (1.50 + 0.25)");
  assert.ok(html.includes("task $1.50"), "usage by role: task");
  assert.ok(html.includes("qa $0.25"), "usage by role: qa");
  assert.ok(html.includes("m $1.75"), "usage by model (1.50 + 0.25 on model m)");
  assert.ok(html.includes("[tool] bash: {&quot;command&quot;:&quot;npm test&quot;}"), "log tail: tool line");
  assert.ok(html.includes("[agent] scaffolding the engine"), "log tail: agent line");
  assert.ok(html.includes("commit abc1234"), "log tail: heartbeat");
  assert.ok(html.includes("state: backlog → running"), "log tail: state event");
  assert.ok(html.includes('id="task-log"'), "log container");
  assert.ok(html.includes(`hx-get="/tasks/${task.id}/log"`), "HTMX log refresh");
  assert.ok(html.includes('hx-trigger="every 2s"'), "2s auto-refresh while running");
  assert.ok(html.includes('<!doctype html>'), "full page for plain navigation");
  assert.ok(html.includes('id="task-panel"'), "layout carries the #task-panel dialog");
  assert.ok(html.includes("chuck"), "owner shown");
  // Read-only: no control buttons, no resolution dialog, no forms.
  assert.ok(!html.includes("<form"), "no forms on the task page");
  assert.ok(!html.includes("Stop (pause)"), "no stop control");
  assert.ok(!html.includes("Retry deploy"), "no retry-deploy control");
  assert.ok(!html.includes("Resolution dialog"), "no resolution dialog");
  await app.close();
});

test("GET /tasks/<id> with HX-Request returns the bare slide-over fragment", async () => {
  const ctx = await makeApp();
  const { app, db } = ctx;
  const { task } = await makeTaskFixture(ctx, { state: "running", log: true, usage: true });

  const res = await app.inject({
    method: "GET",
    url: `/tasks/${task.id}`,
    headers: { "hx-request": "true" },
  });
  assert.equal(res.statusCode, 200);
  const html = res.payload;
  assert.ok(!html.includes("<!doctype html>"), "bare fragment, not a full page");
  assert.ok(html.includes(`Task #${task.id}`), "task heading");
  assert.ok(html.includes('id="task-log"'), "log container in the fragment");
  assert.ok(html.includes(`hx-get="/tasks/${task.id}/log"`), "live log refresh preserved");
  assert.ok(html.includes("panel-close"), "close button in the panel");
  await app.close();
});

test("GET /tasks/<id> without live refresh for non-running tasks; 404 unknown", async () => {
  const ctx = await makeApp();
  const { app } = ctx;
  const { task } = await makeTaskFixture(ctx, { state: "backlog" });

  const res = await app.inject({ method: "GET", url: `/tasks/${task.id}` });
  assert.equal(res.statusCode, 200);
  assert.ok(!res.payload.includes('hx-trigger="every 2s"'), "no 2s refresh while not running");
  assert.ok(res.payload.includes("no log lines yet"), "empty log placeholder");

  const missing = await app.inject({ method: "GET", url: "/tasks/999" });
  assert.equal(missing.statusCode, 404);

  const bad = await app.inject({ method: "GET", url: "/tasks/abc" });
  assert.ok(bad.payload.includes("invalid task id"));
  await app.close();
});

test("needs-attention task shows the what-happened panel + MCP resolution pointer", async () => {
  const ctx = await makeApp();
  const { app, db } = ctx;
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const { task } = await makeTaskFixture(ctx, { state: "needs_attention", log: true });
  const now = Date.now();
  await q.insert(taskEvents).values([
    {
      taskId: task.id,
      ts: now,
      type: "state",
      payload: { from: "running", to: "needs_attention", reason: "mock session crashed" },
    },
    { taskId: task.id, ts: now + 1, type: "qa", payload: { round: 2, pass: false, feedback: "QA said: missing tests" } },
  ]);

  const res = await app.inject({ method: "GET", url: `/tasks/${task.id}` });
  assert.equal(res.statusCode, 200);
  assert.ok(res.payload.includes("What happened"), "what-happened panel");
  assert.ok(res.payload.includes("mock session crashed"), "failure reason shown");
  assert.ok(res.payload.includes("QA said: missing tests"), "QA feedback shown");
  assert.ok(res.payload.includes(`restart_task(${task.id}`), "MCP resolution pointer");
  assert.ok(res.payload.includes("state-needs_attention"), "state badge");
  assert.ok(!res.payload.includes("Resolution dialog"), "no dialog — resolution is via MCP");
  await app.close();
});

test("non-needs-attention task does not show the what-happened panel", async () => {
  const ctx = await makeApp();
  const { app } = ctx;
  const { task } = await makeTaskFixture(ctx, { state: "running", log: true });
  const res = await app.inject({ method: "GET", url: `/tasks/${task.id}` });
  assert.equal(res.statusCode, 200);
  assert.ok(!res.payload.includes("What happened"), "no what-happened panel");
  await app.close();
});

test("GET /tasks/<id>/log returns the log tail fragment", async () => {
  const ctx = await makeApp();
  const { app } = ctx;
  const { task } = await makeTaskFixture(ctx, { state: "running", log: true });

  const res = await app.inject({ method: "GET", url: `/tasks/${task.id}/log` });
  assert.equal(res.statusCode, 200);
  assert.match(res.headers["content-type"] ?? "", /text\/html/);
  assert.ok(res.payload.includes("<div class=\"log\">"), "fragment root");
  assert.ok(res.payload.includes("[agent] scaffolding the engine"), "log line in fragment");
  assert.ok(res.payload.includes("state: backlog → running"), "state event rendered");

  const missing = await app.inject({ method: "GET", url: "/tasks/999/log" });
  assert.equal(missing.statusCode, 404);
  await app.close();
});

test("groom page is a read-only transcript viewer", async () => {
  const ctx = await makeApp();
  const { app, services } = ctx;
  const { projectId, ideaId } = await makeProjectAndIdea(ctx, "Viewer", "Viewer idea", "chuck");

  // Not groomed yet: the viewer points at the MCP start_grooming tool.
  let res = await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` });
  assert.equal(res.statusCode, 200);
  assert.ok(res.payload.includes("start_grooming"), "points at MCP start_grooming");
  assert.ok(!res.payload.includes("<form"), "no forms");

  // Groom via MCP, then the viewer shows the transcript.
  await mcpCall(app, "start_grooming", { idea_id: ideaId });
  await mcpCall(app, "groom_message", { idea_id: ideaId, text: "My question?" });
  res = await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` });
  assert.equal(res.statusCode, 200);
  assert.ok(res.payload.includes("My question?"), "user message in transcript");
  assert.ok(res.payload.includes("groom_message"), "points at MCP grooming tools");
  assert.ok(!res.payload.includes("<form"), "no chat input");
  assert.ok(!res.payload.includes(">Accept<"), "no accept button");

  // Iceboxed idea: the viewer notes it is no longer grooming.
  await mcpCall(app, "groom_accept", { idea_id: ideaId });
  await groomSettled(app, ideaId);
  assert.equal((await services.getIdea(ideaId))?.state, "icebox");
  res = await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` });
  assert.ok(res.payload.includes("no longer in grooming"), "post-grooming note");

  const missing = await app.inject({ method: "GET", url: "/ideas/999/groom" });
  assert.equal(missing.statusCode, 404);
  await app.close();
});

test("GET /reports renders the read-only reports page", async () => {
  const { app, db, services } = await makeApp();
  const res = await app.inject({ method: "GET", url: "/reports" });
  assert.equal(res.statusCode, 200);
  assert.ok(res.payload.includes("Reports"), "reports heading");
  assert.ok(!res.payload.includes('method="post"'), "no mutation forms (the filter form is GET)");
  await app.close();
});

test("GET /reports renders the per-user spend section (owner + unattributed)", async () => {
  const { app, db, services } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const p = await services.createProject({ name: "Spend Project" });
  const now = Date.now();
  const cur = new Date();
  const curStart = new Date(cur.getFullYear(), cur.getMonth(), 1).getTime();
  const prevStart = new Date(cur.getFullYear(), cur.getMonth() - 1, 1).getTime();
  await q
    .insert(usage)
    .values([
      { projectId: p.id, taskId: null, ts: curStart + 1000, role: "groom", model: "m", thinking: "xhigh", tokensIn: 10, tokensOut: 5, cost: 2.5, owner: "chuck" },
      { projectId: p.id, taskId: null, ts: prevStart + 1000, role: "task", model: "m", thinking: "medium", tokensIn: 10, tokensOut: 5, cost: 4.0, owner: "dylan" },
      { projectId: p.id, taskId: null, ts: curStart + 2000, role: "task", model: "m", thinking: "medium", tokensIn: 10, tokensOut: 5, cost: 1.25, owner: "" },
    ]);
  const res = await app.inject({ method: "GET", url: "/reports" });
  assert.equal(res.statusCode, 200);
  const html = res.payload;
  assert.ok(html.includes("Per user — rolling 12 months"), "per-user section heading");
  assert.ok(html.includes(">chuck<"), "chuck row");
  assert.ok(html.includes(">dylan<"), "dylan row");
  assert.ok(html.includes(">unattributed<"), "unattributed row for owner ''");
  assert.ok(html.includes("$2.50"), "chuck spend rendered");
  assert.ok(html.includes("$4.00"), "dylan spend rendered");
  assert.ok(html.includes("$1.25"), "unattributed spend rendered");

  // By-role section: task (4.0 + 1.25) > groom (2.5).
  assert.ok(html.includes("By role — rolling 12 months"), "by-role section heading");
  assert.ok(html.includes(">task<"), "task role row");
  assert.ok(html.includes(">groom<"), "groom role row");
  assert.ok(html.includes("$5.25"), "task role total rendered");
  // Per-project + total sections still span all keys (chuck+dylan+unattributed).
  assert.ok(html.includes("Per project — rolling 12 months"), "per-project section present");
  assert.ok(html.includes("$7.75"), "total spend includes all keys (2.5 + 4.0 + 1.25)");
  await app.close();
});

// ---------------------------------------------------------------------------
// MCP per-key capability scoping (guardrails for multi-user keys)
// ---------------------------------------------------------------------------

const READ_TOOLS = [
  "board_status",
  "get_project",
  "list_ideas",
  "list_projects",
  "project_status",
  "task_status",
].sort();

test("MCP: unknown key is rejected with a clear error (401)", async () => {
  const { app } = await makeApp();
  const res = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      authorization: "Bearer sk-unknown-key",
    },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
  });
  assert.equal(res.statusCode, 401);
  assert.match(res.payload, /not authorized for the kanban MCP/);
  assert.match(res.payload, /MCP_KEY_CAPABILITIES/);
  await app.close();
});

test("MCP: scoped key (read) sees only read tools and cannot call control tools", async () => {
  const ctx = await makeApp({
    mcpKeyCapabilities: new Map([
      ["abc123", new Set(["read"])],
    ]),
  });
  const { app, db } = ctx;
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const now = Date.now();
  const project = await q
    .insert(projects)
    .values({ name: "Scoped", createdAt: now, updatedAt: now })
    .returning();
  const projectId = (Array.isArray(project) ? project[0] : project)!.id as number;

  const headers = {
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    authorization: "Bearer sk-other-user-abc123",
  };
  const call = (method: string, params: Record<string, unknown>) =>
    app.inject({
      method: "POST",
      url: "/mcp",
      headers,
      payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
    });

  // tools/list → only the read set (incl. board_status).
  const list = await call("tools/list", {});
  const rpc = parseRpc(list.payload);
  const names = rpc.result.tools.map((t: any) => t.name).sort();
  assert.deepEqual(names, READ_TOOLS, "scoped key sees exactly the read tools");

  // read tool works
  const get = await call("tools/call", { name: "get_project", arguments: { project_id: projectId } });
  const getRpc = parseRpc(get.payload);
  assert.ok(getRpc.result, `get_project failed: ${get.payload}`);
  assert.equal(JSON.parse(getRpc.result.content[0].text).name, "Scoped");

  // control tool is rejected with a clear error
  const bad = await call("tools/call", {
    name: "start_task",
    arguments: { task_id: 1 },
  });
  const badRpc = parseRpc(bad.payload);
  assert.equal(badRpc.result.isError, true, "control tool rejected for the read key");
  assert.match(badRpc.result.content[0].text, /not available for this key/);
  await app.close();
});

test("MCP: agents_switch is admin-only — control keys rejected, admin reads/sets", async () => {
  const ctx = await makeApp({
    mcpKeyCapabilities: new Map([
      ["ctrl999", new Set(["control"])],
      ["admin88", new Set(["admin"])],
    ]),
    userKeys: { admin88: "sk-admin-admin88" },
  });
  const { app } = ctx;
  const call = (auth: string, name: string, args: Record<string, unknown>) =>
    app.inject({
      method: "POST",
      url: "/mcp",
      headers: {
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        authorization: `Bearer ${auth}`,
      },
      payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name, arguments: args } }),
    });

  // control key: the tool is invisible in tools/list and rejected at call time.
  const ctrlList = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      authorization: "Bearer sk-user-ctrl999",
    },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
  });
  const ctrlNames = parseRpc(ctrlList.payload).result.tools.map((t: any) => t.name);
  assert.ok(!ctrlNames.includes("agents_switch"), "control key does not see agents_switch");
  const ctrlCall = await call("sk-user-ctrl999", "agents_switch", {});
  const ctrlRpc = parseRpc(ctrlCall.payload);
  assert.equal(ctrlRpc.result.isError, true, "agents_switch rejected for the control key");
  assert.match(ctrlRpc.result.content[0].text, /not available for this key/);

  // admin key: read (fail-safe default off), set global on, per-slug off,
  // unknown slug rejected, set off — durable round-trip.
  const read1 = parseRpc((await call("sk-admin-admin88", "agents_switch", {})).payload).result;
  assert.ok(!read1.isError, `read failed: ${JSON.stringify(read1)}`);
  assert.deepEqual(JSON.parse(read1.content[0].text), {
    global: { state: "off", setAt: null, setBy: null },
    slugs: {},
  }, "missing row -> fail-safe OFF, no slugs");
  const setOn = parseRpc((await call("sk-admin-admin88", "agents_switch", { state: "on" })).payload).result;
  assert.ok(!setOn.isError, `set on failed: ${JSON.stringify(setOn)}`);
  const setOnDoc = JSON.parse(setOn.content[0].text);
  assert.equal(setOnDoc.global.state, "on");
  assert.equal(setOnDoc.global.setBy, "admin88", "set attributes the caller");
  // Per-slug: product off (global stays on, preserved).
  const setSlug = parseRpc(
    (await call("sk-admin-admin88", "agents_switch", { slug: "product", state: "off" })).payload,
  ).result;
  assert.ok(!setSlug.isError, `set slug failed: ${JSON.stringify(setSlug)}`);
  const slugDoc = JSON.parse(setSlug.content[0].text);
  assert.equal(slugDoc.global.state, "on", "global preserved by a slug write");
  assert.equal(slugDoc.slugs.product.state, "off");
  assert.equal(slugDoc.slugs.product.setBy, "admin88");
  // Unknown slug: rejected, no phantom entry.
  const badSlug = parseRpc(
    (await call("sk-admin-admin88", "agents_switch", { slug: "ghost", state: "off" })).payload,
  ).result;
  assert.equal(badSlug.isError, true, "unknown slug rejected");
  assert.match(badSlug.content[0].text, /unknown agent slug 'ghost'/);
  // Missing state with a slug: rejected.
  const noState = parseRpc(
    (await call("sk-admin-admin88", "agents_switch", { slug: "product" })).payload,
  ).result;
  assert.equal(noState.isError, true, "state required when slug is given");
  // Read back: global on + product off, durable.
  const read2 = parseRpc((await call("sk-admin-admin88", "agents_switch", {})).payload).result;
  const read2Doc = JSON.parse(read2.content[0].text);
  assert.equal(read2Doc.global.state, "on", "global persists (durable kv)");
  assert.equal(read2Doc.slugs.product.state, "off", "slug entry persists (durable kv)");
  const setOff = parseRpc((await call("sk-admin-admin88", "agents_switch", { state: "off" })).payload).result;
  const setOffDoc = JSON.parse(setOff.content[0].text);
  assert.equal(setOffDoc.global.state, "off");
  assert.equal(setOffDoc.slugs.product.state, "off", "global write preserves slug entries");
  await app.close();
});

test("MCP: kanban key still gets the full tool set (no regression)", async () => {
  const { app } = await makeApp();
  const res = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: MCP_HEADERS,
    payload: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }),
  });
  const rpc = parseRpc(res.payload);
  assert.equal(rpc.result.tools.length, 29, "kanban key sees all 29 tools");
  await app.close();
});

test("MCP: alias-keyed capability entry resolves via USER_KEYS full-key match (Phase 13.3)", async () => {
  const ctx = await makeApp({
    userKeys: { chuck: "sk-chuck-alias-key" },
    mcpKeyCapabilities: new Map([["chuck", new Set(["read"])]]),
  });
  const { app } = ctx;
  const call = (key: string, method: string, params: Record<string, unknown> = {}) =>
    app.inject({
      method: "POST",
      url: "/mcp",
      headers: {
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        authorization: `Bearer ${key}`,
      },
      payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
    });

  // The alias's full key → read-scoped tools.
  const list = await call("sk-chuck-alias-key", "tools/list");
  const names = parseRpc(list.payload).result.tools.map((t: any) => t.name).sort();
  assert.deepEqual(names, READ_TOOLS, "alias full-key match → read tools only");

  // A different key → 401.
  const bad = await call("sk-someone-else", "tools/list");
  assert.equal(bad.statusCode, 401, "non-matching key rejected");
  await app.close();
});

test("MCP: alias entry survives key rotation (map unchanged, USER_KEYS updated)", async () => {
  // Before rotation: alias 'chuck' → old key value.
  const before = await makeApp({
    userKeys: { chuck: "sk-old-value" },
    mcpKeyCapabilities: new Map([["chuck", new Set(["read"])]]),
  });
  const resOld = await before.app.inject({
    method: "POST",
    url: "/mcp",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      authorization: "Bearer sk-old-value",
    },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
  });
  assert.equal(resOld.statusCode, 200, "old key authorized before rotation");
  await before.app.close();

  // After rotation: same capability map, USER_KEYS now holds the NEW value.
  const after = await makeApp({
    userKeys: { chuck: "sk-new-value" },
    mcpKeyCapabilities: new Map([["chuck", new Set(["read"])]]),
  });
  const resNew = await after.app.inject({
    method: "POST",
    url: "/mcp",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      authorization: "Bearer sk-new-value",
    },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
  });
  assert.equal(resNew.statusCode, 200, "new key authorized with the SAME capability map");
  const resOldAfter = await after.app.inject({
    method: "POST",
    url: "/mcp",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      authorization: "Bearer sk-old-value",
    },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
  });
  assert.equal(resOldAfter.statusCode, 401, "old key no longer matches the alias");
  await after.app.close();
});

test("MCP: alias entries never fall back to suffix matching", async () => {
  // 'chuck' is a USER_KEYS alias — a key that merely ENDS with 'chuck'
  // must NOT match the alias entry (legacy suffix semantics are disabled
  // for known aliases).
  const ctx = await makeApp({
    userKeys: { chuck: "sk-the-real-chuck-key" },
    mcpKeyCapabilities: new Map([["chuck", new Set(["read"])]]),
  });
  const res = await ctx.app.inject({
    method: "POST",
    url: "/mcp",
    headers: {
      "content-type": "application/json",
      accept: "application/json, text/event-stream",
      authorization: "Bearer sk-ends-with-chuck",
    },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
  });
  assert.equal(res.statusCode, 401, "suffix-like key rejected for an alias entry");
  await ctx.app.close();
});

test("MCP: mixed map — alias entries + legacy suffix entries coexist", async () => {
  const ctx = await makeApp({
    userKeys: { dylan: "sk-dylan-full" },
    mcpKeyCapabilities: new Map([
      ["dylan", new Set(["read"])],
      ["legacy99", new Set(["read"])],
    ]),
  });
  const call = (key: string) =>
    ctx.app.inject({
      method: "POST",
      url: "/mcp",
      headers: {
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        authorization: `Bearer ${key}`,
      },
      payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }),
    });
  assert.equal((await call("sk-dylan-full")).statusCode, 200, "alias entry works");
  assert.equal((await call("sk-anything-legacy99")).statusCode, 200, "legacy suffix entry works");
  assert.equal((await call("sk-stranger")).statusCode, 401, "unknown key rejected");
  await ctx.app.close();
});

test("MCP: edit_idea + delete_project round-trip", async () => {
  const ctx = await makeApp();
  const { app, services, db } = ctx;
  const q = db.db as unknown as BetterSQLite3Database<any>;

  const project = mcpText(await mcpCall(app, "create_project", { name: "Delete Me" }));
  const idea1 = mcpText(await mcpCall(app, "add_idea", { project_id: project.id, text: "first idea" }));
  mcpText(await mcpCall(app, "add_idea", { project_id: project.id, text: "second idea" }));

  // edit_idea: text update in state 'idea'.
  const edited = mcpText(await mcpCall(app, "edit_idea", { idea_id: idea1.id, text: "first idea (edited)" }));
  assert.equal(edited.text, "first idea (edited)");
  assert.equal(edited.state, "idea");

  // edit_idea: rejected outside state 'idea'.
  await q.update(ideas).set({ state: "icebox" }).where(eq(ideas.id, idea1.id));
  const bad = await mcpCall(app, "edit_idea", { idea_id: idea1.id, text: "nope" });
  assert.equal(bad.isError, true);
  assert.match(bad.content[0].text, /only ideas in the "idea" state/);

  // delete_project: cascades ideas/tasks + cleans the project's workspace dirs.
  const deleted = mcpText(await mcpCall(app, "delete_project", { project_id: project.id }));
  assert.equal(deleted.project.name, "Delete Me");
  assert.deepEqual(deleted.removedDirs, [], "no workspace dirs existed");

  const gone = await mcpCall(app, "get_project", { project_id: project.id });
  assert.equal(gone.isError, true, "project is gone");
  assert.equal((await services.listIdeas(project.id)).length, 0, "ideas cascade-deleted");
  await app.close();
});

test("MCP: delete_project refuses (409) while a task is running", async () => {
  const ctx = await makeApp();
  const { app } = ctx;
  const { projectId } = await makeTaskFixture(ctx, { state: "running" });
  const res = await mcpCall(app, "delete_project", { project_id: projectId });
  assert.equal(res.isError, true);
  assert.match(res.content[0].text, /live task/);
  const still = mcpText(await mcpCall(app, "get_project", { project_id: projectId }));
  assert.equal(still.id, projectId, "project still exists");
  await app.close();
});

test("MCP: board_status includes idea pipeline counts (ideaCounts)", async () => {
  const ctx = await makeApp();
  const { app, services, db } = ctx;
  const q = db.db as unknown as BetterSQLite3Database<any>;

  const p = await services.createProject({ name: "Pipeline" });
  const i1 = await services.addIdea(p.id, "raw idea"); // idea
  const i2 = await services.addIdea(p.id, "grooming idea"); // → grooming
  const i3 = await services.addIdea(p.id, "icebox idea"); // → icebox
  const i4 = await services.addIdea(p.id, "discarded idea"); // → discarded
  await q.update(ideas).set({ state: "grooming" }).where(eq(ideas.id, i2.id));
  await q.update(ideas).set({ state: "icebox" }).where(eq(ideas.id, i3.id));
  await q.update(ideas).set({ state: "discarded" }).where(eq(ideas.id, i4.id));

  const board = mcpText(await mcpCall(app, "board_status", {}));
  assert.deepEqual(board.ideaCounts, { idea: 1, grooming: 1, icebox: 1 }, "visible pipeline states only");

  // Scoped to the project (same filters as the task counts).
  const scoped = mcpText(await mcpCall(app, "board_status", { project_id: p.id }));
  assert.deepEqual(scoped.ideaCounts, { idea: 1, grooming: 1, icebox: 1 });
  await app.close();
});

test("MCP: owner attribution resolves from USER_KEYS (full-key match)", async () => {
  const ctx = await makeApp({
    userKeys: { chuck: "sk-chuck-full-key" },
    mcpKeyCapabilities: new Map([["full-key", new Set(["admin"])]]),
  });
  const { app } = ctx;
  const headers = {
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    authorization: "Bearer sk-chuck-full-key",
  };
  const call = (method: string, params: Record<string, unknown>) =>
    app.inject({
      method: "POST",
      url: "/mcp",
      headers,
      payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
    });

  // Full-key match → owner 'chuck' stamped on the created project.
  const init = await call("initialize", {});
  assert.equal(init.statusCode, 200, "authorized key passes discovery");
  const created = parseRpc(
    (await call("tools/call", { name: "create_project", arguments: { name: "Chuck's Project" } })).payload,
  );
  const project = JSON.parse(created.result.content[0].text);
  assert.equal(project.owner, "chuck", "USER_KEYS full-key match → owner name");
  await app.close();
});
