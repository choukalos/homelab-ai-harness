/**
 * Slice 5 resilience tests (PLAN.md §4/§6): watchdog (per-task heartbeat,
 * 10-min silence → needs_attention), auto-resume on container start
 * (rehydrate running tasks from last_commit + progress summary), and the
 * 7-day workspace cleanup — over a real temp sqlite db with a mocked task
 * runner + QA gate + deploy stage and an injectable clock (no network,
 * no model, no git). Per-category slot coverage lives in
 * orchestrator.test.ts; pause/resume/stop REST + MCP coverage lives in
 * http/http.test.ts.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { and, eq } from "drizzle-orm";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import type { KanbanConfig } from "./config.js";
import { initDb } from "./db/index.js";
import { ideas, projects, taskEvents, tasks, type TaskRow } from "./db/schema.js";
import type { AgentRuntime, TaskRunContext, TaskRunResult, TaskRunner, UsageSample } from "./agent/sessions.js";
import type { QaRunContext, QaVerdict } from "./agent/qa.js";
import type { SummaryUpdateContext } from "./agent/summary.js";
import type { DeployContext, DeployResult } from "./deploy/index.js";
import { Orchestrator, type DeployRunnerLike, type QaGateLike, type SummaryUpdaterLike } from "./orchestrator.js";
import { createKanbanServices, type KanbanServices } from "./services/index.js";
import { taskEventLine } from "./services/tasks.js";

const SPEC = { goal: "g", steps: ["s1"], acceptance: ["a1"], kind: "code" as const };
const DAY = 86_400_000;

function testCfg(sqlitePath: string): KanbanConfig {
  return {
    litellm: { baseUrl: "https://llm.example.com/v1", apiKey: "sk-test" },
    model: "test-model",
    modelCost: undefined,
    githubToken: undefined,
    userKeys: {},
    db: { driver: "sqlite", sqlitePath, mysql: undefined },
    workspace: { hostPath: "/tmp/workspace", dir: "/tmp/workspace" },
    harness: { repoUrl: "https://example.com/harness", skillsPath: "agent-skills" },
    thinking: { groom: "xhigh", task: "medium", qa: "xhigh", summary: "medium" },
    mediaConcurrentTasks: 1,
    nonMediaConcurrentTasks: 1,
    workspaceCleanupDays: 7,
    server: { bindAddr: "127.0.0.1", port: 3000 },
  };
}

/** Mocked task pipeline: per-task behavior (ok / fail / hang), abort support. */
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
        this.resolvers.set(ctx.taskId, () => resolve(this.resultFor(ctx)));
      });
    }
    if (b === "fail") return Promise.reject(new Error("mock session crashed"));
    return Promise.resolve(this.resultFor(ctx));
  }

  private resultFor(ctx: TaskRunContext): TaskRunResult {
    ctx.onLog?.("mock log line");
    ctx.onCommit?.("c0ffee");
    ctx.onUsage?.({
      role: "task",
      model: "test-model",
      thinking: "medium",
      input: 10,
      output: 5,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 15,
      cost: 0.01,
    } satisfies UsageSample);
    return { summary: `mock summary for task ${ctx.taskId}`, lastCommit: "c0ffee" };
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

class PassQaGate implements QaGateLike {
  readonly maxRounds = 2;
  run(_ctx: QaRunContext): Promise<QaVerdict> {
    return Promise.resolve({ pass: true, feedback: "" });
  }
}

class OkDeployRunner implements DeployRunnerLike {
  deploy(ctx: DeployContext): Promise<DeployResult> {
    return Promise.resolve({ published: `pushed branch ${ctx.branch}`, target: "origin" });
  }
}

class FixedSummaryUpdater implements SummaryUpdaterLike {
  update(_ctx: SummaryUpdateContext): Promise<string> {
    return Promise.resolve("New project state summary.");
  }
}

async function setup() {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-resilience-"));
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const services = createKanbanServices(db);
  const runner = new MockTaskRunner();
  const workspaceRoot = path.join(dir, "workspace");
  mkdirSync(workspaceRoot, { recursive: true });
  // Offset clock: real Date.now() + offset so DB timestamps (written with
  // the real clock) stay consistent with the mocked "now".
  let offset = 0;
  const orch = new Orchestrator({
    cfg,
    db,
    agent: {} as unknown as AgentRuntime,
    tasks: runner,
    qa: new PassQaGate(),
    deploy: new OkDeployRunner(),
    summary: new FixedSummaryUpdater(),
    workspaceRoot,
    noTimer: true,
    now: () => Date.now() + offset,
  });
  return {
    cfg,
    db,
    q,
    services,
    runner,
    orch,
    workspaceRoot,
    dir,
    advance: (ms: number) => {
      offset += ms;
    },
  };
}

/** drizzle's returning() is typed `Row | Row[]`; normalize to a single row. */
function one<T>(r: T | T[], label: string): T {
  const row = Array.isArray(r) ? r[0] : r;
  assert.ok(row, label);
  return row;
}

/** Create a project + a backlog task for a (moved) idea. */
async function makeBacklogTask(q: BetterSQLite3Database<any>, services: KanbanServices, projectId: number, text: string) {
  const idea = await services.addIdea(projectId, text);
  await q.update(ideas).set({ state: "moved", spec: SPEC }).where(eq(ideas.id, idea.id));
  const now = Date.now();
  const task = one(
    await q
      .insert(tasks)
      .values({ ideaId: idea.id, projectId, spec: SPEC, state: "backlog", stateChangedAt: now, createdAt: now })
      .returning(),
    "task",
  );
  return { idea, task };
}

async function getTask(q: BetterSQLite3Database<any>, id: number): Promise<TaskRow> {
  const rows = await q.select().from(tasks).where(eq(tasks.id, id));
  return rows[0]!;
}

async function eventsFor(q: BetterSQLite3Database<any>, taskId: number) {
  const rows = await q.select().from(taskEvents).where(eq(taskEvents.taskId, taskId));
  return [...rows].sort((a, b) => a.id - b.id);
}

// ---------------------------------------------------------------------------
// Watchdog: per-task heartbeat (60s) + 10-min silence → needs_attention
// ---------------------------------------------------------------------------

test("watchdog: heartbeat every 60s while active; 10-min silence → needs_attention + abort", async () => {
  const { q, services, runner, orch, advance } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Sticky task");
  runner.behavior.set(task.id, "hang"); // the session produces no further activity

  await orch.start();
  await orch.startTask(task.id);
  assert.equal((await getTask(q, task.id)).state, "running");

  // 60s of silence: the session is in flight (launch counts as fresh
  // activity) → a watchdog heartbeat is written.
  advance(60_000);
  let result = await orch.watchdogTick();
  assert.deepEqual(result.heartbeats, [task.id], "heartbeat at 60s");
  assert.deepEqual(result.flagged, []);
  let heartbeats = (await eventsFor(q, task.id)).filter(
    (e) => e.type === "heartbeat" && e.payload?.kind === "watchdog",
  );
  assert.equal(heartbeats.length, 1);

  // Another 60s with no new activity → no second heartbeat (nothing new).
  advance(60_000);
  result = await orch.watchdogTick();
  assert.deepEqual(result.heartbeats, [], "no heartbeat without new activity");
  assert.equal((await getTask(q, task.id)).state, "running");

  // Past the 10-minute silence timeout → needs_attention + abort.
  advance(541_000); // 661s total silence from the last activity
  result = await orch.watchdogTick();
  assert.deepEqual(result.flagged, [task.id], "flagged after 10 min silence");
  const t = await getTask(q, task.id);
  assert.equal(t.state, "needs_attention");
  assert.ok(runner.aborted.includes(task.id), "session aborted");
  const events = await eventsFor(q, task.id);
  const last = events[events.length - 1]!;
  assert.equal(last.type, "state");
  assert.equal(last.payload!.to, "needs_attention");
  assert.match(String(last.payload!.reason), /watchdog: no activity for \d+m/);

  // The aborted run settles without overriding the failure state.
  await orch.settled();
  assert.equal((await getTask(q, task.id)).state, "needs_attention");
  await orch.stop();
});

test("watchdog: activity resets the silence window", async () => {
  const { q, services, runner, orch, advance } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Chatty task");
  runner.behavior.set(task.id, "hang");

  await orch.start();
  await orch.startTask(task.id);

  // t+60s: first heartbeat.
  advance(60_000);
  await orch.watchdogTick();

  // t+90s: the session produces activity (a log line) — the silence clock
  // restarts from here.
  advance(30_000);
  runner.runs[0]!.onLog?.("still working");

  // t+120s: 60s since the last heartbeat AND new activity → second heartbeat.
  advance(30_000);
  const result = await orch.watchdogTick();
  assert.deepEqual(result.heartbeats, [task.id], "heartbeat after renewed activity");
  assert.deepEqual(result.flagged, []);

  // t+661s: 571s since the last activity (< 10 min) → still running.
  advance(541_000);
  const mid = await orch.watchdogTick();
  assert.deepEqual(mid.flagged, [], "activity extended the grace window");
  assert.equal((await getTask(q, task.id)).state, "running");

  // t+721s: 631s since the last activity (> 10 min) → flagged.
  advance(60_000);
  const end = await orch.watchdogTick();
  assert.deepEqual(end.flagged, [task.id]);
  assert.equal((await getTask(q, task.id)).state, "needs_attention");
  await orch.stop();
});

test("watchdog: paused tasks are skipped (silence is expected)", async () => {
  const { q, services, runner, orch, advance } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Paused task");
  runner.behavior.set(task.id, "hang");

  await orch.start();
  await orch.startTask(task.id);
  await orch.stopTask(task.id); // running + paused
  advance(11 * 60_000); // well past the timeout
  const result = await orch.watchdogTick();
  assert.deepEqual(result.flagged, [], "paused task not flagged");
  assert.deepEqual(result.heartbeats, [], "paused task gets no heartbeat");
  const t = await getTask(q, task.id);
  assert.equal(t.state, "running");
  assert.equal(t.paused, true);
  await orch.stop();
});

test("watchdog: running task with no in-flight pipeline is flagged after 10 min (crash case)", async () => {
  const { q, services, orch, advance } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Crashed task");
  // Simulate a container crash: the task is `running` in the DB with a
  // recent event trail, but no pipeline is in flight.
  const now = Date.now();
  await q
    .update(tasks)
    .set({ state: "running", branch: `task/${task.id}`, stateChangedAt: now })
    .where(eq(tasks.id, task.id));
  await q.insert(taskEvents).values({
    taskId: task.id,
    ts: now,
    type: "state",
    payload: { from: "backlog", to: "running" },
  });

  // A fresh crash (events seconds old) is not flagged…
  const fresh = await orch.watchdogTick();
  assert.deepEqual(fresh.flagged, []);

  // …but 10 minutes of silence with no session is.
  advance(11 * 60_000);
  const stale = await orch.watchdogTick();
  assert.deepEqual(stale.flagged, [task.id]);
  const t = await getTask(q, task.id);
  assert.equal(t.state, "needs_attention");
  assert.match(String((await eventsFor(q, task.id)).at(-1)!.payload!.reason), /watchdog/);
  await orch.stop();
});

test("taskEventLine renders the watchdog heartbeat", () => {
  assert.equal(
    taskEventLine({ type: "heartbeat", payload: { kind: "watchdog" } } as never),
    "heartbeat (alive)",
  );
  assert.equal(taskEventLine({ type: "heartbeat", payload: { commit: "abc" } } as never), "commit abc");
});

// ---------------------------------------------------------------------------
// Auto-resume on container start
// ---------------------------------------------------------------------------

test("auto-resume: running tasks are rehydrated on start (last_commit + progress summary)", async () => {
  const { q, services, runner, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Survivor");
  // The container died mid-run: running state, a last commit, a log trail.
  const now = Date.now();
  await q
    .update(tasks)
    .set({
      state: "running",
      branch: `task/${task.id}`,
      workspace: `task-${task.id}`,
      lastCommit: "cafe1234",
      stateChangedAt: now,
    })
    .where(eq(tasks.id, task.id));
  await q.insert(taskEvents).values([
    { taskId: task.id, ts: now - 1000, type: "log", payload: { line: "[agent] half done" } },
    { taskId: task.id, ts: now, type: "state", payload: { from: "backlog", to: "running" } },
  ]);

  // Container start → auto-resume rehydrates the running task.
  const rehydrated = await orch.autoResume();
  assert.equal(rehydrated, 1, "one running task rehydrated");

  // The rehydrated run continues to completion (mock pipeline).
  await orch.settled();
  assert.equal(runner.runs.length, 1, "pipeline relaunched");
  const ctx = runner.runs[0]!;
  assert.equal(ctx.resumeCommit, "cafe1234", "re-clone/checkout last_commit");
  assert.ok(ctx.progressSummary, "progress summary re-injected");
  assert.ok(ctx.progressSummary!.includes("half done"), "progress from the event trail");
  assert.ok(ctx.progressSummary!.includes("Last commit: cafe1234"));
  assert.equal((await getTask(q, task.id)).state, "done");
  await orch.stop();
});

test("auto-resume: paused running tasks stay paused (user resumes explicitly)", async () => {
  const { q, services, runner, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const a = await makeBacklogTask(q, services, p.id, "Auto survivor");
  const b = await makeBacklogTask(q, services, p.id, "Paused survivor");
  const now = Date.now();
  for (const { task } of [a, b]) {
    await q
      .update(tasks)
      .set({ state: "running", branch: `task/${task.id}`, lastCommit: "cafe1234", stateChangedAt: now })
      .where(eq(tasks.id, task.id));
  }
  await q.update(tasks).set({ paused: true }).where(eq(tasks.id, b.task.id));

  const rehydrated = await orch.autoResume();
  assert.equal(rehydrated, 1, "only the non-paused task rehydrated");

  await orch.settled();
  assert.equal(runner.runs.length, 1);
  assert.equal(runner.runs[0]!.taskId, a.task.id);
  assert.equal((await getTask(q, a.task.id)).state, "done");
  const bTask = await getTask(q, b.task.id);
  assert.equal(bTask.state, "running", "paused task untouched");
  assert.equal(bTask.paused, true);
  await orch.stop();
});

// ---------------------------------------------------------------------------
// 7-day workspace cleanup
// ---------------------------------------------------------------------------

test("cleanup: sweeps old task-<id> and groom-<id> dirs (app-managed, not in-flight, > 7 days)", async () => {
  const { q, services, orch, workspaceRoot, advance } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const t1 = await makeBacklogTask(q, services, p.id, "Old done task"); // id 1
  const t2 = await makeBacklogTask(q, services, p.id, "Old running task"); // id 2
  const t3 = await makeBacklogTask(q, services, p.id, "Fresh done task"); // id 3

  // Task states: 1 done (old dir → delete), 2 running (old dir → keep),
  // 3 done (fresh dir → keep). Task 4 has no DB row (old dir → delete).
  const now = Date.now();
  await q.update(tasks).set({ state: "done", stateChangedAt: now }).where(eq(tasks.id, t1.task.id));
  await q.update(tasks).set({ state: "running", stateChangedAt: now }).where(eq(tasks.id, t2.task.id));
  await q.update(tasks).set({ state: "done", stateChangedAt: now }).where(eq(tasks.id, t3.task.id));

  // Workspace dirs: task-1..task-4 (app-managed) + groom-1 (idea 1 not in
  // the DB → not grooming → swept) + media-build (not app-managed).
  // Old mtimes via utimes (8 days), except task-3.
  const old = new Date(now - 8 * DAY);
  for (const name of ["task-1", "task-2", "task-3", "task-4", "groom-1", "media-build"]) {
    mkdirSync(path.join(workspaceRoot, name), { recursive: true });
  }
  for (const name of ["task-1", "task-2", "task-4", "groom-1", "media-build"]) {
    utimesSync(path.join(workspaceRoot, name), old, old);
  }

  const result = await orch.cleanupWorkspaces();
  assert.deepEqual(result.deleted.sort(), ["groom-1", "task-1", "task-4"], "old app-managed dirs swept");
  assert.ok(result.skipped.includes("task-2"), "running task's workspace kept");
  assert.ok(result.skipped.includes("task-3"), "fresh workspace kept");
  assert.ok(!result.deleted.includes("media-build"), "media build folders untouched");

  assert.ok(!existsSync(path.join(workspaceRoot, "task-1")), "task-1 removed");
  assert.ok(!existsSync(path.join(workspaceRoot, "task-4")), "task-4 (no DB row) removed");
  assert.ok(!existsSync(path.join(workspaceRoot, "groom-1")), "groom-1 (idea not grooming) removed");
  assert.ok(existsSync(path.join(workspaceRoot, "task-2")), "task-2 (running) kept");
  assert.ok(existsSync(path.join(workspaceRoot, "task-3")), "task-3 (fresh) kept");
  assert.ok(existsSync(path.join(workspaceRoot, "media-build")), "media-build kept");

  // A second pass is a no-op (deleted dirs are gone).
  advance(0);
  const again = await orch.cleanupWorkspaces();
  assert.deepEqual(again.deleted, []);
  await orch.stop();
});

test("cleanup: keeps groom-<id> while its idea is actively grooming", async () => {
  const { q, services, orch, workspaceRoot } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const now = Date.now();
  // Idea 1 is in grooming (old groom dir → kept); idea 2 is icebox (old groom
  // dir → swept).
  await q.insert(ideas).values([
    {
      id: 1,
      projectId: p.id,
      text: "grooming idea",
      state: "grooming",
      createdAt: now,
      updatedAt: now,
    },
    {
      id: 2,
      projectId: p.id,
      text: "icebox idea",
      state: "icebox",
      createdAt: now,
      updatedAt: now,
    },
  ]);
  const old = new Date(now - 8 * DAY);
  for (const name of ["groom-1", "groom-2"]) {
    mkdirSync(path.join(workspaceRoot, name), { recursive: true });
    utimesSync(path.join(workspaceRoot, name), old, old);
  }
  const result = await orch.cleanupWorkspaces();
  assert.deepEqual(result.deleted, ["groom-2"], "only the non-grooming idea's dir swept");
  assert.ok(result.skipped.includes("groom-1"), "active grooming workspace kept");
  assert.ok(existsSync(path.join(workspaceRoot, "groom-1")), "groom-1 kept on disk");
  assert.ok(!existsSync(path.join(workspaceRoot, "groom-2")), "groom-2 removed");
  await orch.stop();
});

test("cleanup: missing workspace root is a no-op", async () => {
  const { orch } = await setup();
  const result = await orch.cleanupWorkspaces();
  assert.deepEqual(result, { deleted: [], skipped: [] });
  await orch.stop();
});
