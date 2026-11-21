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
import { monthWindow } from "../services/reports.js";
import type { AgentRuntime, TaskRunContext, TaskRunResult, TaskRunner } from "../agent/sessions.js";
import { GroomingManager } from "../agent/grooming.js";
import { createMockGrooming, type MockGrooming } from "../agent/grooming-mock.js";
import { ResolutionDialog } from "../agent/resolve.js";
import { createMockResolution, type MockResolution } from "../agent/resolve-mock.js";
import { Orchestrator, type DeployRunnerLike, type QaGateLike, type SummaryUpdaterLike } from "../orchestrator.js";
import type { QaRunContext, QaVerdict } from "../agent/qa.js";
import type { SummaryUpdateContext } from "../agent/summary.js";
import type { DeployContext, DeployResult } from "../deploy/index.js";
import { buildApp } from "./app.js";
import { createKanbanServices } from "../services/index.js";
import { MCP_SERVER_INFO } from "../mcp/server.js";

function testCfg(sqlitePath: string): KanbanConfig {
  return {
    litellm: { baseUrl: "https://llm.example.com/v1", apiKey: "sk-test" },
    model: "test-model",
    modelCost: undefined,
    githubToken: undefined,
    db: { driver: "sqlite", sqlitePath, mysql: undefined },
    workspace: { hostPath: "/tmp/workspace", dir: "/tmp/workspace" },
    harness: { repoUrl: "https://example.com/harness", skillsPath: "agent-skills" },
    thinking: { groom: "xhigh", task: "medium", qa: "xhigh", summary: "medium" },
    concurrentTasks: 1,
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
 * Grooming + resolution run against mocked Pi sessions (file-backed); the
 * orchestrator runs the real state machine with mocked task/QA/deploy/summary. */
async function makeApp(opts: { groomSlowMs?: number; mcpKeyCapabilities?: Map<string, Set<string>> } = {}) {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-http-"));
  const cfg = testCfg(path.join(dir, "kanban.db"));
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
  const resolveMock: MockResolution = createMockResolution();
  const resolve = new ResolutionDialog({
    db: db.db as unknown as BetterSQLite3Database<any>,
    cfg,
    sessionFactory: resolveMock.factory,
    workspacePathFor: (taskId) => orchestrator.workspacePath(taskId),
    sessionsDir: path.join(dir, "sessions"),
    restart: (taskId) => orchestrator.restartTask(taskId),
  });
  const services = createKanbanServices(db, { grooming, orchestrator });
  const app = buildApp({
    cfg,
    db,
    agent: {} as unknown as AgentRuntime,
    services,
    orchestrator,
    grooming,
    resolve,
    mcpKeyCapabilities: opts.mcpKeyCapabilities,
  });
  return { app, db, cfg, services, grooming, mock, orchestrator, taskRunner, deploy, resolve, resolveMock };
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

/** drizzle's returning() is typed `Row | Row[]`; normalize to a single row. */
function one<T>(r: T | T[], label: string): T {
  const row = Array.isArray(r) ? r[0] : r;
  assert.ok(row, label);
  return row;
}

test("GET /health returns ok with model + db driver", async () => {
  const { app } = await makeApp();
  const res = await app.inject({ method: "GET", url: "/health" });
  assert.equal(res.statusCode, 200);
  const body = res.json();
  assert.equal(body.ok, true);
  assert.equal(body.model, "test-model");
  assert.equal(body.db, "sqlite");
  await app.close();
});

test("GET / renders the board with stats, columns, and 60s auto-refresh", async () => {
  const { app } = await makeApp();
  const res = await app.inject({ method: "GET", url: "/" });
  assert.equal(res.statusCode, 200);
  assert.match(res.headers["content-type"] ?? "", /text\/html/);
  const html = res.payload;
  for (const label of ["Board", "Projects", "Reports"]) {
    assert.ok(html.includes(`>${label}<`), `nav missing ${label}`);
  }
  assert.ok(html.includes('href="/" class="active"'), "Board nav link should be active");
  assert.ok(html.includes("color-scheme: dark"), "dark theme only");
  for (const col of ["Backlog", "Running", "Deploy", "Done", "Needs Attention"]) {
    assert.ok(html.includes(col), `board column missing: ${col}`);
  }
  assert.ok(html.includes("Spend this month"), "month spend stat");
  assert.ok(html.includes("Completed this month"), "month completed stat");
  assert.ok(html.includes("$0.00"), "empty board shows zero spend");
  assert.ok(html.includes('hx-trigger="every 60s"'), "60s HTMX auto-refresh");
  assert.ok(html.includes("htmx.org"), "HTMX script tag");
  assert.ok(html.includes('id="task-panel"'), "layout carries the #task-panel slide-over dialog");
  assert.ok(html.includes("openTaskPanel"), "panel opener script");
  await app.close();
});

test("GET /projects and /reports render with nav", async () => {
  const { app } = await makeApp();
  for (const [url, active] of [
    ["/projects", "/projects"],
    ["/reports", "/reports"],
  ] as const) {
    const res = await app.inject({ method: "GET", url });
    assert.equal(res.statusCode, 200);
    assert.ok(res.payload.includes(`href="${active}" class="active"`), `${url} active nav`);
  }
  const projects = await app.inject({ method: "GET", url: "/projects" });
  assert.ok(projects.payload.includes("New project"), "New project button");
  assert.ok(projects.payload.includes("<dialog"), "project editor dialog");
  await app.close();
});

test("POST /projects (JSON) creates, 409 on duplicate, 400 without name", async () => {
  const { app } = await makeApp();
  const created = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({
      name: "Demo",
      description: "A demo project",
      repoUrl: "https://github.com/chuck/demo",
      defaultBranch: "main",
      mediaPaths: ["media/a", "media/b"],
    }),
  });
  assert.equal(created.statusCode, 201);
  const body = created.json();
  assert.equal(body.name, "Demo");
  assert.equal(body.description, "A demo project");
  assert.equal(body.repoUrl, "https://github.com/chuck/demo");
  assert.deepEqual(body.mediaPaths, ["media/a", "media/b"]);
  assert.ok(body.id > 0);

  const dup = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name: "Demo" }),
  });
  assert.equal(dup.statusCode, 409);
  assert.match(dup.json().error, /already exists/);

  const noName = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ description: "no name" }),
  });
  assert.equal(noName.statusCode, 400);
  await app.close();
});

test("POST /projects (form) redirects and the project shows in the list", async () => {
  const { app } = await makeApp();
  const res = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "name=Form+Project&description=made+via+form&repo_url=https%3A%2F%2Fgithub.com%2Fx%2Fy",
  });
  assert.equal(res.statusCode, 302);
  assert.equal(res.headers.location, "/projects");

  const list = await app.inject({ method: "GET", url: "/projects" });
  assert.ok(list.payload.includes("Form Project"), "project name in list");
  assert.ok(list.payload.includes("made via form"), "description in list");
  await app.close();
});

test("GET /projects/<id> renders settings, pipeline columns, and dialogs", async () => {
  const { app } = await makeApp();
  const created = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({
      name: "Alpha",
      description: "alpha desc",
      goal: "ship it",
      repoUrl: "https://github.com/chuck/alpha",
      defaultBranch: "main",
      constraints: "never force-push",
    }),
  });
  const id = created.json().id;

  const res = await app.inject({ method: "GET", url: `/projects/${id}` });
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
  assert.ok(html.includes('id="idea-drop"'), "idea drop dialog");
  assert.ok(html.includes(`action="/projects/${id}/ideas"`), "idea drop form action");
  assert.ok(html.includes('id="project-editor"'), "project editor dialog");
  assert.ok(html.includes(`action="/projects/${id}"`), "edit form action");
  assert.ok(html.includes('value="Alpha"'), "edit form pre-filled name");

  const missing = await app.inject({ method: "GET", url: "/projects/999" });
  assert.equal(missing.statusCode, 404);
  await app.close();
});

test("project page + grooming page show live 'agent working' indicators while a turn is in flight", async () => {
  const { app } = await makeApp({ groomSlowMs: 300 });
  const { projectId, ideaId } = await makeProjectAndIdea(app, "Badge", "Badge idea");

  // Start grooming: the seed turn (300ms mock) is in flight.
  await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` });

  // Project page: the Grooming column card carries the working badge.
  const proj = await app.inject({ method: "GET", url: `/projects/${projectId}` });
  assert.ok(proj.payload.includes("groom-badge working"), "working badge in Grooming column");
  assert.ok(proj.payload.includes("agent working"), "badge text");

  // Grooming page: the banner is shown while the seed runs.
  const groom = await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` });
  assert.ok(groom.payload.includes('<div class="groom-banner">'), "working banner on the grooming page");
  assert.ok(groom.payload.includes("The agent is working on this idea"), "banner text");

  // After the seed settles: quiet badge, no banner.
  await new Promise((r) => setTimeout(r, 400));
  const proj2 = await app.inject({ method: "GET", url: `/projects/${projectId}` });
  assert.ok(!proj2.payload.includes("groom-badge working"), "no working badge after settle");
  assert.ok(proj2.payload.includes('class="groom-badge"'), "quiet 'in grooming chat' badge");
  const groom2 = await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` });
  assert.ok(!groom2.payload.includes('<div class="groom-banner">'), "no banner after settle");
  await app.close();
});

test("POST /projects/<id> (JSON) updates; unknown id 404s", async () => {
  const { app } = await makeApp();
  const created = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name: "Alpha", description: "keep me" }),
  });
  const id = created.json().id;

  const updated = await app.inject({
    method: "POST",
    url: `/projects/${id}`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name: "Alpha 2" }),
  });
  assert.equal(updated.statusCode, 200);
  assert.equal(updated.json().name, "Alpha 2");
  assert.equal(updated.json().description, "keep me", "partial update keeps untouched fields");

  const dup = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name: "Beta" }),
  });
  const conflict = await app.inject({
    method: "POST",
    url: `/projects/${id}`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name: "Beta" }),
  });
  assert.equal(conflict.statusCode, 409);

  const missing = await app.inject({
    method: "POST",
    url: "/projects/999",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name: "Ghost" }),
  });
  assert.equal(missing.statusCode, 404);
  await app.close();
});

test("POST /projects/<id>/ideas drops an idea (form + JSON)", async () => {
  const { app } = await makeApp();
  const created = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name: "Alpha" }),
  });
  const id = created.json().id;

  const form = await app.inject({
    method: "POST",
    url: `/projects/${id}/ideas`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "text=My+great+idea",
  });
  assert.equal(form.statusCode, 302);
  assert.equal(form.headers.location, `/projects/${id}`);

  const json = await app.inject({
    method: "POST",
    url: `/projects/${id}/ideas`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ text: "Another idea" }),
  });
  assert.equal(json.statusCode, 201);
  assert.equal(json.json().state, "idea");
  assert.equal(json.json().projectName, "Alpha");

  const empty = await app.inject({
    method: "POST",
    url: `/projects/${id}/ideas`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ text: "   " }),
  });
  assert.equal(empty.statusCode, 400);

  const page = await app.inject({ method: "GET", url: `/projects/${id}` });
  assert.ok(page.payload.includes("My great idea"), "form idea in Idea column");
  assert.ok(page.payload.includes("Another idea"), "json idea in Idea column");

  const badProject = await app.inject({
    method: "POST",
    url: "/projects/999/ideas",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ text: "orphan" }),
  });
  assert.equal(badProject.statusCode, 404);
  await app.close();
});

test("board shows task cards with tag, usage, deps, and month stats", async () => {
  const { app, db, services } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const now = Date.now();

  const alpha = await services.createProject({ name: "Alpha" });
  const beta = await services.createProject({ name: "Beta" });

  // Ideas: a1 (Alpha), a2 (Alpha, depends on a1), a3 (Alpha), b1 (Beta).
  const a1 = await services.addIdea(alpha.id, "First idea");
  const a2 = await services.addIdea(alpha.id, "Second idea");
  const a3 = await services.addIdea(alpha.id, "Third idea");
  const b1 = await services.addIdea(beta.id, "Beta idea");
  await q.update(ideas).set({ dependsOn: [a1.id] }).where(eq(ideas.id, a2.id));

  // Tasks: t1 (a1, running — so a1 has no done task yet), t2 (a2, backlog —
  // waiting on a1), t3 (b1, running), t4 (a3, done).
  const spec = { goal: "g", steps: [], acceptance: [], kind: "code" as const };
  const t1 = one(
    await q
      .insert(tasks)
      .values({ ideaId: a1.id, projectId: alpha.id, spec, state: "running", stateChangedAt: now, createdAt: now })
      .returning(),
    "t1",
  );
  const t2 = one(
    await q
      .insert(tasks)
      .values({ ideaId: a2.id, projectId: alpha.id, spec, state: "backlog", stateChangedAt: now, createdAt: now })
      .returning(),
    "t2",
  );
  const t3 = one(
    await q
      .insert(tasks)
      .values({ ideaId: b1.id, projectId: beta.id, spec, state: "running", stateChangedAt: now, createdAt: now })
      .returning(),
    "t3",
  );
  const t4 = one(
    await q
      .insert(tasks)
      .values({ ideaId: a3.id, projectId: alpha.id, spec, state: "done", stateChangedAt: now, createdAt: now })
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
  await app.close();
});

test("POST /mcp rejects missing/wrong auth with 401", async () => {
  const { app } = await makeApp();
  const noAuth = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
  });
  assert.equal(noAuth.statusCode, 401);
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

test("POST /mcp tools/list returns the Slice 1+2+3 tool set", async () => {
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
    "create_project",
    "get_project",
    "groom_idea",
    "list_ideas",
    "list_projects",
    "move_to_backlog",
    "pause_task",
    "project_status",
    "restart_task",
    "resume_task",
    "retry_deploy",
    "start_task",
    "stop_task",
    "task_status",
    "update_project",
  ]);
  await app.close();
});

test("MCP tools: project + idea round-trip", async () => {
  const { app, services } = await makeApp();
  const created = mcpText(await mcpCall(app, "create_project", { name: "MCP Project", description: "via mcp" }));
  assert.equal(created.name, "MCP Project");

  const listed = mcpText(await mcpCall(app, "list_projects", {}));
  assert.ok(listed.some((p: any) => p.name === "MCP Project"), "list_projects includes the new project");

  const fetched = mcpText(await mcpCall(app, "get_project", { project_id: created.id }));
  assert.equal(fetched.description, "via mcp");

  const updated = mcpText(
    await mcpCall(app, "update_project", { project_id: created.id, name: "MCP Project 2" }),
  );
  assert.equal(updated.name, "MCP Project 2");
  assert.equal(updated.description, "via mcp", "partial update keeps fields");

  const idea = mcpText(await mcpCall(app, "add_idea", { project_id: created.id, text: "mcp idea" }));
  assert.equal(idea.state, "idea");
  assert.equal(idea.projectName, "MCP Project 2");

  const ideas = mcpText(await mcpCall(app, "list_ideas", { project_id: created.id }));
  assert.ok(ideas.some((i: any) => i.text === "mcp idea"), "list_ideas includes the new idea");

  // Errors surface as isError results.
  const missing = await mcpCall(app, "get_project", { project_id: 999 });
  assert.equal(missing.isError, true);
  assert.match(missing.content[0].text, /not found/);
  const dup = await mcpCall(app, "create_project", { name: "MCP Project 2" });
  assert.equal(dup.isError, true);
  assert.match(dup.content[0].text, /already exists/);

  // The REST layer sees the same data (shared service layer).
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
// Slice 2: grooming chat + icebox
// ---------------------------------------------------------------------------

/** Create a project + idea via REST and return their ids. */
async function makeProjectAndIdea(app: Awaited<ReturnType<typeof makeApp>>["app"], name: string, ideaText: string) {
  const created = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name }),
  });
  assert.equal(created.statusCode, 201, `project create: ${created.payload}`);
  const projectId = created.json().id;
  const ideaId = await addIdea(app, projectId, ideaText);
  return { projectId, ideaId };
}

/** Drop an idea into an existing project via REST; return its id. */
async function addIdea(app: Awaited<ReturnType<typeof makeApp>>["app"], projectId: number, text: string): Promise<number> {
  const dropped = await app.inject({
    method: "POST",
    url: `/projects/${projectId}/ideas`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ text }),
  });
  assert.equal(dropped.statusCode, 201, `idea drop: ${dropped.payload}`);
  return dropped.json().id;
}

test("GET /ideas/<id>/groom starts grooming and renders the chat page", async () => {
  const { app, services } = await makeApp();
  const { projectId, ideaId } = await makeProjectAndIdea(app, "Groom", "Build a widget");

  const res = await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` });
  assert.equal(res.statusCode, 200);
  const html = res.payload;
  assert.ok(html.includes("Grooming —"), "grooming page title");
  assert.ok(html.includes("Build a widget"), "idea text shown");
  assert.ok(html.includes('id="groom-messages"'), "message list");
  assert.ok(html.includes('hx-post="/ideas/' + ideaId + '/groom/messages"'), "HTMX chat turn");
  assert.ok(html.includes('hx-target="#groom-messages"'), "HTMX target");
  assert.ok(html.includes('action="/ideas/' + ideaId + '/groom/accept"'), "Accept form");
  assert.ok(html.includes('action="/ideas/' + ideaId + '/groom/cancel"'), "Cancel form");
  assert.ok(html.includes('action="/ideas/' + ideaId + '/groom/re-groom"'), "Re-groom form");
  assert.ok(html.includes('action="/ideas/' + ideaId + '/discard"'), "Discard form");
  assert.ok(html.includes("mock reply to: Build a widget"), "seeded assistant reply");

  // The idea transitioned to grooming.
  const idea = await services.getIdea(ideaId);
  assert.equal(idea?.state, "grooming");

  // Unknown idea → 404.
  const missing = await app.inject({ method: "GET", url: "/ideas/999/groom" });
  assert.equal(missing.statusCode, 404);
  await app.close();
});

test("POST /ideas/<id>/groom/messages echoes the user message; reply arrives via poll", async () => {
  const { app } = await makeApp();
  const { ideaId } = await makeProjectAndIdea(app, "Groom2", "Chat idea");
  await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` }); // start

  // The POST is non-blocking: it returns the user's message immediately and
  // the assistant reply arrives via the 3s transcript poll.
  const res = await app.inject({
    method: "POST",
    url: `/ideas/${ideaId}/groom/messages`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "message=What+kind+is+this%3F",
  });
  assert.equal(res.statusCode, 200);
  assert.match(res.headers["content-type"] ?? "", /text\/html/);
  assert.ok(res.payload.includes('class="msg user"'), "user fragment echoed");
  assert.ok(res.payload.includes("What kind is this?"), "user text");

  // The assistant reply lands in the transcript (mock turn is fast).
  await new Promise((r) => setTimeout(r, 25));
  const poll = await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom/messages` });
  assert.equal(poll.statusCode, 200);
  assert.ok(poll.payload.includes('id="groom-messages"'), "poll returns the container");
  assert.ok(poll.payload.includes('hx-trigger="every 3s"'), "poll attributes re-emitted");
  assert.ok(poll.payload.includes("mock reply to: What kind is this?"), "assistant reply in transcript");

  // Empty message → 400 error fragment.
  const empty = await app.inject({
    method: "POST",
    url: `/ideas/${ideaId}/groom/messages`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "message=",
  });
  assert.equal(empty.statusCode, 400);
  assert.ok(empty.payload.includes('class="msg error"'));
  await app.close();
});

test("grooming transitions: accept → icebox, cancel → idea, re-groom, discard", async () => {
  const { app, services } = await makeApp();
  const { projectId, ideaId } = await makeProjectAndIdea(app, "Transitions", "Transition idea");
  await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` }); // start

  // Accept (form) → 302 to the project page IMMEDIATELY; the finalize turn
  // runs in the background and the idea lands in the icebox when it settles.
  const accept = await app.inject({
    method: "POST",
    url: `/ideas/${ideaId}/groom/accept`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "",
  });
  assert.equal(accept.statusCode, 302);
  assert.equal(accept.headers.location, `/projects/${projectId}`);

  // Wait for the background finalize to settle (mock turn is fast).
  let iceboxed = await services.getIdea(ideaId);
  for (let i = 0; i < 50 && iceboxed?.state !== "icebox"; i++) {
    await new Promise((r) => setTimeout(r, 10));
    iceboxed = await services.getIdea(ideaId);
  }
  assert.equal(iceboxed?.state, "icebox");
  assert.equal(iceboxed?.spec?.goal, "Mock goal");
  assert.deepEqual(iceboxed?.dependsOn, []);

  // Accept on an icebox idea → 409 (no longer groomable).
  const lateAccept = await app.inject({
    method: "POST",
    url: `/ideas/${ideaId}/groom/accept`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "",
  });
  assert.equal(lateAccept.statusCode, 409);

  // Groom page for an icebox idea → 409.
  const stale = await app.inject({ method: "GET", url: `/ideas/${ideaId}/groom` });
  assert.equal(stale.statusCode, 409);
  assert.ok(stale.payload.includes("no longer in grooming"));

  // A second idea: re-groom (while grooming), then cancel.
  const i2 = await addIdea(app, projectId, "Cancel idea");
  await app.inject({ method: "GET", url: `/ideas/${i2}/groom` }); // start

  // Re-groom (while grooming) → 302 back to the grooming page, state stays grooming.
  const reGroom = await app.inject({
    method: "POST",
    url: `/ideas/${i2}/groom/re-groom`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "",
  });
  assert.equal(reGroom.statusCode, 302);
  assert.equal(reGroom.headers.location, `/ideas/${i2}/groom`);
  assert.equal((await services.getIdea(i2))?.state, "grooming");

  // Cancel → back to idea.
  const cancel = await app.inject({
    method: "POST",
    url: `/ideas/${i2}/groom/cancel`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "",
  });
  assert.equal(cancel.statusCode, 302);
  assert.equal((await services.getIdea(i2))?.state, "idea");

  // Re-groom is invalid once back in the idea state.
  const reGroomTooLate = await app.inject({
    method: "POST",
    url: `/ideas/${i2}/groom/re-groom`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "",
  });
  assert.equal(reGroomTooLate.statusCode, 409);

  // Discard → 302; idea soft-deleted.
  const discard = await app.inject({
    method: "POST",
    url: `/ideas/${i2}/discard`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "",
  });
  assert.equal(discard.statusCode, 302);
  assert.equal((await services.getIdea(i2))?.state, "discarded");

  // Guards: accept/cancel/re-groom on a discarded idea → 409.
  for (const route of ["/groom/accept", "/groom/cancel", "/groom/re-groom"]) {
    const res = await app.inject({
      method: "POST",
      url: `/ideas/${i2}${route}`,
      headers: { "content-type": "application/x-www-form-urlencoded" },
      payload: "",
    });
    assert.equal(res.statusCode, 409, route);
  }
  await app.close();
});

test("POST /projects/<id>/icebox/move moves selected items to the backlog", async () => {
  const { app, services, db } = await makeApp();
  const { projectId } = await makeProjectAndIdea(app, "Icebox", "Icebox idea A");
  const q = db.db as unknown as BetterSQLite3Database<any>;

  // Finalize two ideas into the icebox via the grooming accept flow.
  const ideas = await services.listIdeas(projectId);
  const ideaA = ideas[0]!;
  await app.inject({ method: "POST", url: `/projects/${projectId}/ideas`, headers: { "content-type": "application/json" }, payload: JSON.stringify({ text: "Icebox idea B" }) });
  const ideaB = (await services.listIdeas(projectId)).find((i) => i.text === "Icebox idea B")!;
  await app.inject({ method: "GET", url: `/ideas/${ideaA.id}/groom` });
  await app.inject({ method: "POST", url: `/ideas/${ideaA.id}/groom/accept`, headers: { "content-type": "application/x-www-form-urlencoded" }, payload: "" });
  await app.inject({ method: "GET", url: `/ideas/${ideaB.id}/groom` });
  await app.inject({ method: "POST", url: `/ideas/${ideaB.id}/groom/accept`, headers: { "content-type": "application/x-www-form-urlencoded" }, payload: "" });

  // The project page shows the icebox specs with checkboxes + move form.
  const page = await app.inject({ method: "GET", url: `/projects/${projectId}` });
  assert.ok(page.payload.includes('name="idea_ids" value="' + ideaA.id + '"'), "icebox checkbox A");
  assert.ok(page.payload.includes('name="idea_ids" value="' + ideaB.id + '"'), "icebox checkbox B");
  assert.ok(page.payload.includes('action="/projects/' + projectId + '/icebox/move"'), "move form");
  assert.ok(page.payload.includes("Move to Backlog"), "move button");
  assert.ok(page.payload.includes("Mock goal"), "finalized spec goal shown");
  assert.ok(page.payload.includes(">code<"), "spec kind tag");

  // Move one item (form) → 302; task created in the backlog.
  const move = await app.inject({
    method: "POST",
    url: `/projects/${projectId}/icebox/move`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: `idea_ids=${ideaA.id}`,
  });
  assert.equal(move.statusCode, 302);
  assert.equal(move.headers.location, `/projects/${projectId}`);
  assert.equal((await services.getIdea(ideaA.id))?.state, "moved");
  const taskRows = await q.select().from(tasks).where(eq(tasks.ideaId, ideaA.id));
  assert.equal(taskRows.length, 1);
  assert.equal(taskRows[0]!.state, "backlog");
  assert.equal(taskRows[0]!.spec?.goal, "Mock goal");

  // Move the second (JSON) → 200 with the result.
  const moveJson = await app.inject({
    method: "POST",
    url: `/projects/${projectId}/icebox/move`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ idea_ids: [ideaB.id] }),
  });
  assert.equal(moveJson.statusCode, 200);
  const body = moveJson.json();
  assert.equal(body.tasks.length, 1);
  assert.equal(body.tasks[0].ideaId, ideaB.id);
  assert.equal(body.ideas[0].state, "moved");

  // Guards: moving a moved idea → 409; empty selection → 400; foreign idea → 400.
  const again = await app.inject({
    method: "POST",
    url: `/projects/${projectId}/icebox/move`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ idea_ids: [ideaA.id] }),
  });
  assert.equal(again.statusCode, 409);
  const emptyMove = await app.inject({
    method: "POST",
    url: `/projects/${projectId}/icebox/move`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ idea_ids: [] }),
  });
  assert.equal(emptyMove.statusCode, 400);

  // The board now shows the two backlog tasks.
  const board = await app.inject({ method: "GET", url: "/" });
  assert.ok(board.payload.includes("Icebox idea A"), "backlog card A");
  assert.ok(board.payload.includes("Icebox idea B"), "backlog card B");
  await app.close();
});

test("MCP groom_idea + move_to_backlog drive the pipeline", async () => {
  const { app, services } = await makeApp();
  const { projectId, ideaId } = await makeProjectAndIdea(app, "MCP Groom", "MCP groomed idea");

  // groom_idea: one-shot idea → icebox.
  const groomed = mcpText(await mcpCall(app, "groom_idea", { idea_id: ideaId }));
  assert.equal(groomed.state, "icebox");
  assert.equal(groomed.spec.goal, "Mock goal");
  assert.deepEqual(groomed.dependsOn, []);

  // Idempotent.
  const again = mcpText(await mcpCall(app, "groom_idea", { idea_id: ideaId }));
  assert.equal(again.state, "icebox");

  // move_to_backlog (one or more).
  const ideaId2 = await addIdea(app, projectId, "Second MCP idea");
  await mcpCall(app, "groom_idea", { idea_id: ideaId2 });
  const moved = mcpText(await mcpCall(app, "move_to_backlog", { idea_ids: [ideaId, ideaId2] }));
  assert.equal(moved.tasks.length, 2);
  assert.ok(moved.tasks.every((t: any) => t.state === "backlog"));
  assert.equal((await services.getIdea(ideaId))?.state, "moved");

  // Errors surface as isError results.
  const missing = await mcpCall(app, "groom_idea", { idea_id: 999 });
  assert.equal(missing.isError, true);
  assert.match(missing.content[0].text, /not found/);
  const notIcebox = await mcpCall(app, "move_to_backlog", { idea_ids: [999] });
  assert.equal(notIcebox.isError, true);
  assert.match(notIcebox.content[0].text, /not found/);
  await app.close();
});

// ---------------------------------------------------------------------------
// Slice 3a: task detail page (live log, workspace, branch, usage)
// ---------------------------------------------------------------------------

/** Create a project + a task in the given state with log events + usage. */
let taskFixtureSeq = 0;
async function makeTaskFixture(
  app: Awaited<ReturnType<typeof makeApp>>["app"],
  db: Awaited<ReturnType<typeof makeApp>>["db"],
  opts: { state: string; log?: boolean; usage?: boolean } = { state: "running" },
) {
  const q = db.db as unknown as BetterSQLite3Database<any>;
  taskFixtureSeq += 1;
  const created = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({
      name: `TaskProject ${taskFixtureSeq}`,
      repoUrl: "https://github.com/chuck/taskproj",
      defaultBranch: "main",
      constraints: "no force-push",
    }),
  });
  assert.equal(created.statusCode, 201);
  const projectId = created.json().id;
  const ideaId = await addIdea(app, projectId, "Build the task engine");
  const now = Date.now();
  const task = one(
    await q
      .insert(tasks)
      .values({
        ideaId,
        projectId,
        spec: { goal: "Build the task engine", steps: ["scaffold", "wire"], acceptance: ["tests green"], kind: "code" },
        state: opts.state,
        stateChangedAt: now,
        createdAt: now,
        branch: "task/1",
        workspace: "/workspace/task-1",
        lastCommit: "abc1234",
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
      { projectId, taskId: task.id, ts: now, role: "task", model: "m", thinking: "medium", tokensIn: 100, tokensOut: 50, cost: 1.5 },
      { projectId, taskId: task.id, ts: now, role: "qa", model: "m", thinking: "xhigh", tokensIn: 10, tokensOut: 5, cost: 0.25 },
    ]);
  }
  return { projectId, task };
}

test("GET /tasks/<id> renders the task detail with log tail, workspace, branch, usage", async () => {
  const { app, db } = await makeApp();
  const { task } = await makeTaskFixture(app, db, { state: "running", log: true, usage: true });

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
  assert.ok(html.includes("Build the task engine"), "spec goal");
  assert.ok(html.includes("tests green"), "acceptance criterion");
  assert.ok(html.includes("$1.75"), "usage so far (1.50 + 0.25)");
  assert.ok(html.includes("task $1.50"), "usage by role: task");
  assert.ok(html.includes("qa $0.25"), "usage by role: qa");
  assert.ok(html.includes("[tool] bash: {&quot;command&quot;:&quot;npm test&quot;}"), "log tail: tool line");
  assert.ok(html.includes("[agent] scaffolding the engine"), "log tail: agent line");
  assert.ok(html.includes("commit abc1234"), "log tail: heartbeat");
  assert.ok(html.includes("state: backlog → running"), "log tail: state event");
  assert.ok(html.includes('id="task-log"'), "log container");
  assert.ok(html.includes(`hx-get="/tasks/${task.id}/log"`), "HTMX log refresh");
  assert.ok(html.includes('hx-trigger="every 2s"'), "2s auto-refresh while running");
  assert.ok(html.includes('hx-swap="innerHTML"'), "fragment swap");
  assert.ok(html.includes('<!doctype html>'), "full page for plain navigation");
  assert.ok(html.includes('id="task-panel"'), "layout carries the #task-panel dialog");
  await app.close();
});

test("GET /tasks/<id> with HX-Request returns the bare slide-over fragment", async () => {
  const { app, db } = await makeApp();
  const { task } = await makeTaskFixture(app, db, { state: "running", log: true, usage: true });

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
  const { app, db } = await makeApp();
  const { task } = await makeTaskFixture(app, db, { state: "backlog" });

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

test("GET /tasks/<id>/log returns the log tail fragment", async () => {
  const { app, db } = await makeApp();
  const { task } = await makeTaskFixture(app, db, { state: "running", log: true });

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

test("needs-attention task shows the what-happened panel + resolution dialog", async () => {
  const { app, db } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const { task } = await makeTaskFixture(app, db, { state: "needs_attention", log: true });
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
  assert.ok(res.payload.includes("Resolution dialog"), "resolution dialog section");
  assert.ok(res.payload.includes(`/tasks/${task.id}/resolve/messages`), "chat form posts to resolve/messages");
  assert.ok(res.payload.includes(`/tasks/${task.id}/resolve/accept`), "accept form posts to resolve/accept");
  assert.ok(res.payload.includes("state-needs_attention"), "state badge");
  await app.close();
});

test("non-needs-attention task does not show the resolution dialog", async () => {
  const { app, db } = await makeApp();
  const { task } = await makeTaskFixture(app, db, { state: "running", log: true });
  const res = await app.inject({ method: "GET", url: `/tasks/${task.id}` });
  assert.equal(res.statusCode, 200);
  assert.ok(!res.payload.includes("Resolution dialog"), "no dialog while running");
  assert.ok(!res.payload.includes("What happened"), "no what-happened panel");
  await app.close();
});

test("POST /tasks/<id>/resolve/messages: chat turn fragment + audit event", async () => {
  const { app, db } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const { task } = await makeTaskFixture(app, db, { state: "needs_attention", log: true });

  const res = await app.inject({
    method: "POST",
    url: `/tasks/${task.id}/resolve/messages`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "message=what+went+wrong?",
  });
  assert.equal(res.statusCode, 200);
  assert.match(res.headers["content-type"] ?? "", /text\/html/);
  assert.ok(res.payload.includes("msg assistant"), "assistant message fragment");
  assert.ok(res.payload.includes("mock resolution reply"), "mock reply text");

  // Audit event + usage (role resolve) recorded.
  const events = await q.select().from(taskEvents).where(eq(taskEvents.taskId, task.id));
  assert.ok(events.some((e) => e.type === "resolve" && e.payload!.text === "what went wrong?"), "resolve event");

  // Guards: empty message → 400 fragment; unknown task → 404-ish error fragment.
  const empty = await app.inject({
    method: "POST",
    url: `/tasks/${task.id}/resolve/messages`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "message=   ",
  });
  assert.equal(empty.statusCode, 400);
  assert.ok(empty.payload.includes("message is required"));
  await app.close();
});

test("POST /tasks/<id>/resolve/accept: plan → backlog (JSON + form redirect)", async () => {
  const { app, db } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const { task } = await makeTaskFixture(app, db, { state: "needs_attention", log: true });

  // JSON accept.
  const res = await app.inject({
    method: "POST",
    url: `/tasks/${task.id}/resolve/accept`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({}),
  });
  assert.equal(res.statusCode, 200);
  const body = res.json();
  assert.equal(body.state, "backlog", "task back in the backlog");
  assert.equal(body.qaRounds, 0, "QA rounds reset");
  assert.ok(body.resolution, "plan captured");
  assert.ok(body.resolution.includes("what went wrong"), "plan content from the mock session");

  // Guards: a backlog task cannot be accepted again.
  const again = await app.inject({
    method: "POST",
    url: `/tasks/${task.id}/resolve/accept`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({}),
  });
  assert.equal(again.statusCode, 409);

  // Form accept → 302 redirect to the task page.
  const { task: t2 } = await makeTaskFixture(app, db, { state: "needs_attention" });
  const form = await app.inject({
    method: "POST",
    url: `/tasks/${t2.id}/resolve/accept`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "",
  });
  assert.equal(form.statusCode, 302);
  assert.equal(form.headers.location, `/tasks/${t2.id}`);
  await app.close();
});

test("POST /tasks/<id>/retry-deploy: re-runs only the deploy step", async () => {
  const { app, db } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const { task } = await makeTaskFixture(app, db, { state: "needs_attention" });
  const now = Date.now();
  await q.insert(taskEvents).values({
    taskId: task.id,
    ts: now,
    type: "state",
    payload: { from: "deploy", to: "needs_attention", reason: "deploy failed: push failed: auth" },
  });

  const res = await app.inject({
    method: "POST",
    url: `/tasks/${task.id}/retry-deploy`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({}),
  });
  assert.equal(res.statusCode, 200);
  const body = res.json();
  assert.equal(body.state, "done", "deploy re-run succeeds → done");
  const events = await q.select().from(taskEvents).where(eq(taskEvents.taskId, task.id));
  const deployEvent = events.filter((e) => e.type === "deploy").pop()!;
  assert.equal(deployEvent.payload!.status, "ok");

  // Guards: a running task is not deployable.
  const { task: t2 } = await makeTaskFixture(app, db, { state: "running" });
  const guard = await app.inject({
    method: "POST",
    url: `/tasks/${t2.id}/retry-deploy`,
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({}),
  });
  assert.equal(guard.statusCode, 409);
  assert.match(guard.json().error, /not deployable/);
  await app.close();
});

test("board cards link to the task detail page", async () => {
  const { app, db } = await makeApp();
  const { task } = await makeTaskFixture(app, db, { state: "backlog" });

  const res = await app.inject({ method: "GET", url: "/" });
  assert.equal(res.statusCode, 200);
  assert.ok(res.payload.includes(`href="/tasks/${task.id}"`), "board card links to /tasks/<id>");
  await app.close();
});

// ---------------------------------------------------------------------------
// Slice 3c: MCP task control tools (start_task, retry_deploy, restart_task,
// task_status)
// ---------------------------------------------------------------------------

test("MCP tools: start_task / task_status / restart_task / retry_deploy", async () => {
  const { app, db, orchestrator } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const { task } = await makeTaskFixture(app, db, { state: "backlog", log: true, usage: true });

  // task_status: state + log tail + usage, no failure reason yet.
  let status = mcpText(await mcpCall(app, "task_status", { task_id: task.id }));
  assert.equal(status.state, "backlog");
  assert.ok(status.logTail.length > 0, "log tail");
  assert.ok(status.usageTotal > 0, "usage total");
  assert.equal(status.failureReason, null);

  // start_task: backlog → running (the mock pipeline then completes it).
  const started = mcpText(await mcpCall(app, "start_task", { task_id: task.id }));
  assert.equal(started.state, "running");
  await orchestrator.settled();
  status = mcpText(await mcpCall(app, "task_status", { task_id: task.id }));
  assert.equal(status.state, "done", "pipeline settled to done");

  // restart_task: needs_attention → backlog with a resolution note.
  const { task: t2 } = await makeTaskFixture(app, db, { state: "needs_attention", log: true });
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
  const { task: t3 } = await makeTaskFixture(app, db, { state: "needs_attention" });
  await q.insert(taskEvents).values({
    taskId: t3.id,
    ts: Date.now(),
    type: "state",
    payload: { from: "deploy", to: "needs_attention", reason: "deploy failed: push failed: auth" },
  });
  const redeployed = mcpText(await mcpCall(app, "retry_deploy", { task_id: t3.id }));
  assert.equal(redeployed.state, "done", "deploy re-run → done");

  // retry_deploy refuses QA-exhausted tasks (resolution dialog first).
  const { task: t4 } = await makeTaskFixture(app, db, { state: "needs_attention" });
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

// ---------------------------------------------------------------------------
// Slice 5: resilience — pause/resume/stop (REST + MCP), GUI controls
// ---------------------------------------------------------------------------

test("POST /tasks/<id>/pause|resume|stop: manual control (JSON + form redirect)", async () => {
  const { app, db, orchestrator, taskRunner } = await makeApp();
  const { task } = await makeTaskFixture(app, db, { state: "backlog" });
  const json = { "content-type": "application/json" };

  // Hold the run open so the task is deterministically running.
  taskRunner.behavior.set(task.id, "hang");
  await orchestrator.startTask(task.id);

  // stop (JSON) → paused flag, state stays running.
  let res = await app.inject({ method: "POST", url: `/tasks/${task.id}/stop`, headers: json, payload: "{}" });
  assert.equal(res.statusCode, 200);
  assert.equal(res.json().paused, true);
  assert.equal(res.json().state, "running");
  assert.ok(taskRunner.aborted.includes(task.id), "session aborted");

  // stop/pause again → 409 (already paused).
  res = await app.inject({ method: "POST", url: `/tasks/${task.id}/stop`, headers: json, payload: "{}" });
  assert.equal(res.statusCode, 409);
  res = await app.inject({ method: "POST", url: `/tasks/${task.id}/pause`, headers: json, payload: "{}" });
  assert.equal(res.statusCode, 409);

  // resume (JSON) → un-paused; the resumed run re-launches and completes
  // (behavior cleared).
  taskRunner.behavior.delete(task.id);
  const runsBefore = taskRunner.runs.length;
  res = await app.inject({ method: "POST", url: `/tasks/${task.id}/resume`, headers: json, payload: "{}" });
  assert.equal(res.statusCode, 200);
  assert.equal(res.json().paused, false);
  await orchestrator.settled();
  assert.equal(res.json().state, "running");
  assert.equal(taskRunner.runs.length, runsBefore + 1, "resumed run re-launched");

  // resume on a non-paused task → 409.
  res = await app.inject({ method: "POST", url: `/tasks/${task.id}/resume`, headers: json, payload: "{}" });
  assert.equal(res.statusCode, 409);
  assert.match(res.json().error, /not paused/);

  // pause/stop on a done task → 409 (not running).
  const { task: t2 } = await makeTaskFixture(app, db, { state: "backlog" });
  await orchestrator.startTask(t2.id);
  await orchestrator.settled();
  res = await app.inject({ method: "POST", url: `/tasks/${t2.id}/pause`, headers: json, payload: "{}" });
  assert.equal(res.statusCode, 409);
  assert.match(res.json().error, /not running/);

  // Form posts redirect to the task page (GUI buttons).
  const { task: t3 } = await makeTaskFixture(app, db, { state: "backlog" });
  taskRunner.behavior.set(t3.id, "hang");
  await orchestrator.startTask(t3.id);
  res = await app.inject({
    method: "POST",
    url: `/tasks/${t3.id}/stop`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "",
  });
  assert.equal(res.statusCode, 302);
  assert.equal(res.headers.location, `/tasks/${t3.id}`);
  res = await app.inject({
    method: "POST",
    url: `/tasks/${t3.id}/resume`,
    headers: { "content-type": "application/x-www-form-urlencoded" },
    payload: "",
  });
  assert.equal(res.statusCode, 302);
  assert.equal(res.headers.location, `/tasks/${t3.id}`);

  // Invalid id → 400.
  res = await app.inject({ method: "POST", url: "/tasks/abc/pause", headers: json, payload: "{}" });
  assert.equal(res.statusCode, 400);
  await app.close();
});

test("MCP tools: pause_task / resume_task / stop_task", async () => {
  const { app, db, orchestrator, taskRunner } = await makeApp();
  const { task } = await makeTaskFixture(app, db, { state: "backlog" });
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

  // resume_task → un-paused; the resumed run re-launches and completes
  // (behavior cleared).
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

test("task page shows control buttons (Stop/Resume/Retry deploy) + last activity", async () => {
  const { app, db } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;

  // Running (not paused) → Stop button + last-activity row.
  const { task } = await makeTaskFixture(app, db, { state: "running", log: true });
  let res = await app.inject({ method: "GET", url: `/tasks/${task.id}` });
  assert.equal(res.statusCode, 200);
  assert.ok(res.payload.includes(`hx-post="/tasks/${task.id}/stop"`), "Stop button while running");
  assert.ok(!res.payload.includes(`hx-post="/tasks/${task.id}/resume"`), "no Resume while running");
  assert.ok(res.payload.includes("Last activity"), "last activity row (watchdog visibility)");

  // Running + paused → Resume button (orthogonal paused flag).
  await q.update(tasks).set({ paused: true }).where(eq(tasks.id, task.id));
  res = await app.inject({ method: "GET", url: `/tasks/${task.id}` });
  assert.ok(res.payload.includes(`hx-post="/tasks/${task.id}/resume"`), "Resume button while paused");
  assert.ok(!res.payload.includes(`hx-post="/tasks/${task.id}/stop"`), "no Stop while paused");
  assert.ok(res.payload.includes("paused"), "paused badge");

  // Needs Attention → Retry deploy button.
  const { task: t2 } = await makeTaskFixture(app, db, { state: "needs_attention", log: true });
  res = await app.inject({ method: "GET", url: `/tasks/${t2.id}` });
  assert.ok(res.payload.includes(`hx-post="/tasks/${t2.id}/retry-deploy"`), "Retry deploy button");

  // Backlog → no control buttons.
  const { task: t3 } = await makeTaskFixture(app, db, { state: "backlog" });
  res = await app.inject({ method: "GET", url: `/tasks/${t3.id}` });
  assert.ok(!res.payload.includes(`hx-post="/tasks/${t3.id}/stop"`), "no Stop in backlog");
  assert.ok(!res.payload.includes(`hx-post="/tasks/${t3.id}/resume"`), "no Resume in backlog");
  assert.ok(!res.payload.includes(`hx-post="/tasks/${t3.id}/retry-deploy"`), "no Retry deploy in backlog");
  await app.close();
});

// ---------------------------------------------------------------------------
// Slice 4: reports & history
// ---------------------------------------------------------------------------

/** Seed a project + task + usage rows with timestamps in controlled months. */
async function seedSpend(
  app: Awaited<ReturnType<typeof makeApp>>["app"],
  db: Awaited<ReturnType<typeof makeApp>>["db"],
  opts: {
    projectName: string;
    ideaText: string;
    taskState: string;
    /** Offset from the start of the current month (ms); negative = earlier. */
    tsOffset: number;
    cost: number;
    role?: string;
  },
): Promise<{ projectId: number; taskId: number }> {
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const created = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name: opts.projectName }),
  });
  assert.equal(created.statusCode, 201);
  const projectId = created.json().id;
  const ideaId = await addIdea(app, projectId, opts.ideaText);
  const now = Date.now();
  const curStart = monthWindow(now)[monthWindow(now).length - 1]!.start;
  const ts = curStart + opts.tsOffset;
  const task = one(
    await q
      .insert(tasks)
      .values({
        ideaId,
        projectId,
        spec: { goal: "g", steps: [], acceptance: [], kind: "code" },
        state: opts.taskState,
        stateChangedAt: ts,
        createdAt: now,
      })
      .returning(),
    "task",
  );
  await q.insert(usage).values([
    {
      projectId,
      taskId: task.id,
      ts,
      role: opts.role ?? "task",
      model: "m",
      thinking: "medium",
      tokensIn: 100,
      tokensOut: 40,
      cost: opts.cost,
    },
  ]);
  return { projectId, taskId: task.id };
}

test("GET /reports renders spend chart, total callout, per-project stats, and per-task table", async () => {
  const { app, db } = await makeApp();
  const a = await seedSpend(app, db, {
    projectName: "Alpha",
    ideaText: "Alpha widget",
    taskState: "done",
    tsOffset: 3600_000,
    cost: 2.5,
  });
  await seedSpend(app, db, {
    projectName: "Beta",
    ideaText: "Beta gadget",
    taskState: "running",
    tsOffset: 2 * 3600_000,
    cost: 1.5,
  });

  const res = await app.inject({ method: "GET", url: "/reports" });
  assert.equal(res.statusCode, 200);
  const html = res.payload;
  assert.ok(html.includes('href="/reports" class="active"'), "reports nav active");
  assert.ok(html.includes("Spend — rolling 12 months"), "spend section");
  assert.ok(html.includes("Total spend (12 mo)"), "total callout label");
  assert.ok(html.includes("$4.00"), "total spend value (2.5 + 1.5)");
  assert.ok(html.includes("Per project — rolling 12 months"), "per-project section");
  assert.ok(html.includes("Alpha"), "per-project table: Alpha");
  assert.ok(html.includes("Beta"), "per-project table: Beta");
  assert.ok(html.includes("Per-task usage"), "per-task section");
  assert.ok(html.includes("Alpha widget"), "per-task table: task title");
  assert.ok(html.includes("Beta gadget"), "per-task table: task title");
  assert.ok(html.includes(`<a href="/tasks/${a.taskId}">#${a.taskId}</a>`), "task link");
  // Two server-rendered SVG charts (monthly bars + per-project bars).
  assert.equal(html.match(/<svg /g)?.length, 2, "two SVG charts");
  assert.ok(html.includes("<rect "), "bars rendered as rects");
  // Filter form (GET /reports with project/state/role/q).
  assert.ok(html.includes('<form class="filters" method="get" action="/reports">'), "filter form");
  for (const name of ["project", "state", "role", "q"]) {
    assert.ok(html.includes(`name="${name}"`), `filter input ${name}`);
  }
  await app.close();
});

test("GET /reports filters the per-task table by project / state / role / q", async () => {
  const { app, db } = await makeApp();
  const a = await seedSpend(app, db, {
    projectName: "Alpha",
    ideaText: "Alpha widget",
    taskState: "done",
    tsOffset: 3600_000,
    cost: 2.5,
  });
  const b = await seedSpend(app, db, {
    projectName: "Beta",
    ideaText: "Beta gadget",
    taskState: "running",
    tsOffset: 2 * 3600_000,
    cost: 1.5,
  });

  // Project filter.
  let res = await app.inject({ method: "GET", url: `/reports?project=${a.projectId}` });
  assert.ok(res.payload.includes("Alpha widget"), "alpha task shown");
  assert.ok(!res.payload.includes("Beta gadget"), "beta task filtered out");
  // State filter.
  res = await app.inject({ method: "GET", url: "/reports?state=running" });
  assert.ok(res.payload.includes("Beta gadget"), "running task shown");
  assert.ok(!res.payload.includes("Alpha widget"), "done task filtered out");
  // Role filter (both seeded rows use role `task`).
  res = await app.inject({ method: "GET", url: "/reports?role=task" });
  assert.ok(res.payload.includes("Alpha widget") && res.payload.includes("Beta gadget"), "role=task keeps both");
  res = await app.inject({ method: "GET", url: "/reports?role=qa" });
  assert.ok(res.payload.includes("No task usage recorded for the current filters"), "role=qa matches none");
  // Text filter.
  res = await app.inject({ method: "GET", url: "/reports?q=beta" });
  assert.ok(res.payload.includes("Beta gadget"), "q=beta matches");
  assert.ok(!res.payload.includes("Alpha widget"), "q=beta excludes alpha");
  // Invalid filter values are ignored (treated as unfiltered).
  res = await app.inject({ method: "GET", url: "/reports?state=bogus&role=bogus" });
  assert.ok(res.payload.includes("Alpha widget") && res.payload.includes("Beta gadget"), "invalid filters ignored");
  void b;
  await app.close();
});

test("GET /projects/<id> shows the completed list (hidden by default) with pagination", async () => {
  const { app, db } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const created = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name: "Alpha" }),
  });
  const id = created.json().id;

  // 11 done tasks with distinct completion times (newest first in the list).
  for (let i = 0; i < 11; i++) {
    const ideaId = await addIdea(app, id, `Done item ${i}`);
    await q.insert(tasks).values({
      ideaId,
      projectId: id,
      spec: { goal: "g", steps: [], acceptance: [], kind: "code" },
      state: "done",
      stateChangedAt: Date.now() - i * 3600_000, // item 0 is newest
      createdAt: Date.now(),
    });
  }

  const res = await app.inject({ method: "GET", url: `/projects/${id}` });
  const html = res.payload;
  // Hidden by default: the list lives inside a collapsed <details>.
  assert.ok(html.includes('<details class="completed">'), "completed list in <details> (hidden by default)");
  assert.ok(!html.includes("<details class=\"completed\" open"), "not open by default");
  assert.ok(html.includes("Completed items (11)"), "completed count");
  // The ideas also appear in the Idea column (state `idea`), so match the
  // completed-list table cells specifically: <td>Done item N</td>.
  assert.ok(html.includes("<td>Done item 0</td>"), "newest item on page 1");
  assert.ok(!html.includes("<td>Done item 10</td>"), "oldest item not on page 1");
  assert.ok(html.includes("page 1 of 2"), "pagination label");
  assert.ok(html.includes(`/projects/${id}?page=2`), "next-page link");

  const res2 = await app.inject({ method: "GET", url: `/projects/${id}?page=2` });
  assert.ok(res2.payload.includes("<td>Done item 10</td>"), "oldest item on page 2");
  assert.ok(!res2.payload.includes("<td>Done item 0</td>"), "newest item not on page 2");
  assert.ok(res2.payload.includes("page 2 of 2"), "pagination label page 2");
  assert.ok(res2.payload.includes(`<a href="/projects/${id}">← prev</a>`), "prev link on page 2");

  // No completed tasks → empty state.
  const empty = await app.inject({
    method: "POST",
    url: "/projects",
    headers: { "content-type": "application/json" },
    payload: JSON.stringify({ name: "Empty" }),
  });
  const emptyId = empty.json().id;
  const res3 = await app.inject({ method: "GET", url: `/projects/${emptyId}` });
  assert.ok(res3.payload.includes("Completed items (0)"), "zero completed");
  assert.ok(res3.payload.includes("No completed items yet."), "empty state");
  await app.close();
});

test("MCP project_status: state summary + icebox listing + task counts", async () => {
  const { app, db } = await makeApp();
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const project = mcpText(await mcpCall(app, "create_project", { name: "Alpha", goal: "ship it" }));
  const projectId = project.id;

  // LLM-maintained state summary (normally written by the summary session).
  await q
    .update(projects)
    .set({ stateSummary: "Widget API is live; dark mode deployed." })
    .where(eq(projects.id, projectId));

  // Two icebox items (one depends on the other) + one idea outside the icebox.
  const idea1 = await addIdea(app, projectId, "Icebox item one");
  const idea2 = await addIdea(app, projectId, "Icebox item two");
  await addIdea(app, projectId, "Still a raw idea");
  const spec1 = { goal: "Build the widget API", steps: ["scaffold"], acceptance: ["tests green"], kind: "code" as const };
  const spec2 = { goal: "Dark mode", steps: ["theme"], acceptance: ["dark"], kind: "blog" as const };
  await q
    .update(ideas)
    .set({ state: "icebox", spec: spec1, dependsOn: [] })
    .where(eq(ideas.id, idea1));
  await q
    .update(ideas)
    .set({ state: "icebox", spec: spec2, dependsOn: [idea1] })
    .where(eq(ideas.id, idea2));

  // Board tasks: one done, one running.
  const idea3 = await addIdea(app, projectId, "Done item");
  await q.insert(tasks).values({
    ideaId: idea3,
    projectId,
    spec: { goal: "g", steps: [], acceptance: [], kind: "code" },
    state: "done",
    stateChangedAt: Date.now(),
    createdAt: Date.now(),
  });
  const idea4 = await addIdea(app, projectId, "Running item");
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
// MCP per-key capability scoping (guardrails for multi-user keys)
// ---------------------------------------------------------------------------

const READ_TOOLS = [
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
  const { app, db } = await makeApp({
    mcpKeyCapabilities: new Map([
      ["abc123", new Set(["read"])],
    ]),
  });
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

  // tools/list → only the read set
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

test("MCP: kanban key still gets the full tool set (no regression)", async () => {
  const { app } = await makeApp();
  const res = await app.inject({
    method: "POST",
    url: "/mcp",
    headers: MCP_HEADERS,
    payload: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }),
  });
  const rpc = parseRpc(res.payload);
  assert.equal(rpc.result.tools.length, 16, "kanban key sees all 16 tools");
  await app.close();
});
