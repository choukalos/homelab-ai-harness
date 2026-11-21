/**
 * Orchestrator tests (Slice 3a/3b): state machine, CONCURRENT_TASKS slots,
 * dependency gating, paused flag, state_changed_at + task_events — over a
 * real temp sqlite db with a mocked task runner + QA gate + deploy stage
 * (no network, no model, no git). The full QA/deploy/summary pipeline is
 * covered in orchestrator-deploy.test.ts.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { and, eq } from "drizzle-orm";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import type { KanbanConfig } from "./config.js";
import { initDb } from "./db/index.js";
import { ideas, projects, taskEvents, tasks, usage, type TaskRow } from "./db/schema.js";
import type { AgentRuntime, TaskRunContext, TaskRunResult, TaskRunner, UsageSample } from "./agent/sessions.js";
import type { QaRunContext, QaVerdict } from "./agent/qa.js";
import type { SummaryUpdateContext } from "./agent/summary.js";
import type { DeployContext, DeployResult } from "./deploy/index.js";
import {
  Orchestrator,
  type DeployRunnerLike,
  type QaGateLike,
  type SummaryUpdaterLike,
} from "./orchestrator.js";
import { createKanbanServices, type KanbanServices } from "./services/index.js";
import { taskDependencyStatus } from "./services/tasks.js";

const SPEC = { goal: "g", steps: ["s1"], acceptance: ["a1"], kind: "code" as const };

function testCfg(sqlitePath: string, concurrentTasks = 1): KanbanConfig {
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
    concurrentTasks,
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
    });
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

/** QA gate that always passes (full QA behavior is covered in orchestrator-deploy.test.ts). */
class PassQaGate implements QaGateLike {
  readonly maxRounds = 2;
  runs: QaRunContext[] = [];
  run(ctx: QaRunContext): Promise<QaVerdict> {
    this.runs.push(ctx);
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
  calls: SummaryUpdateContext[] = [];
  update(ctx: SummaryUpdateContext): Promise<string> {
    this.calls.push(ctx);
    return Promise.resolve("New project state summary.");
  }
}

async function setup(opts: { concurrentTasks?: number; tickMs?: number; noTimer?: boolean } = {}) {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-orch-"));
  const cfg = testCfg(path.join(dir, "kanban.db"), opts.concurrentTasks ?? 1);
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const services = createKanbanServices(db);
  const runner = new MockTaskRunner();
  const qa = new PassQaGate();
  const deploy = new OkDeployRunner();
  const summary = new FixedSummaryUpdater();
  const workspaceRoot = path.join(dir, "workspace");
  const orch = new Orchestrator({
    cfg,
    db,
    agent: {} as unknown as AgentRuntime,
    tasks: runner,
    qa,
    deploy,
    summary,
    workspaceRoot,
    noTimer: opts.noTimer ?? true,
    tickMs: opts.tickMs ?? 100,
  });
  return { cfg, db, q, services, runner, qa, deploy, summary, orch, workspaceRoot, dir };
}

/** drizzle's returning() is typed `Row | Row[]`; normalize to a single row. */
function one<T>(r: T | T[], label: string): T {
  const row = Array.isArray(r) ? r[0] : r;
  assert.ok(row, label);
  return row;
}

/** Create a project + a backlog task for a (moved) idea. */
async function makeBacklogTask(
  q: BetterSQLite3Database<any>,
  services: KanbanServices,
  projectId: number,
  text: string,
  deps: number[] = [],
  owner = "",
) {
  const idea = await services.addIdea(projectId, text, owner);
  await q
    .update(ideas)
    .set({ state: "moved", spec: SPEC, dependsOn: deps })
    .where(eq(ideas.id, idea.id));
  const now = Date.now();
  const task = one(
    await q
      .insert(tasks)
      .values({ ideaId: idea.id, projectId, spec: SPEC, state: "backlog", stateChangedAt: now, createdAt: now, owner })
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

test("tick: backlog → running → deploy with branch, workspace, events, usage", async () => {
  const { q, services, runner, qa, summary, orch, workspaceRoot } = await setup();
  const p = await services.createProject({ name: "Alpha", repoUrl: "https://github.com/x/y", defaultBranch: "main" });
  const { task } = await makeBacklogTask(q, services, p.id, "First task", [], "chuck");
  const before = (await getTask(q, task.id)).stateChangedAt;

  await orch.start();
  await orch.tick();
  const running = await getTask(q, task.id);
  assert.equal(running.state, "running", "slot free + no deps → running");
  assert.equal(running.branch, `task/${task.id}`);
  assert.equal(running.workspace, path.join(workspaceRoot, `task-${task.id}`));
  assert.ok(running.stateChangedAt >= before, "state_changed_at updated");

  await orch.settled();
  const done = await getTask(q, task.id);
  assert.equal(done.state, "done", "QA pass + deploy ok → done (Slice 3b pipeline)");
  assert.equal(done.lastCommit, "c0ffee");

  // task_events: state (backlog→running), log, heartbeat, qa, state (running→deploy),
  // deploy (ok), state (deploy→done).
  const events = await eventsFor(q, task.id);
  const types = events.map((e) => e.type);
  assert.ok(types.includes("state"), "state events written");
  assert.ok(types.includes("log"), "live log tail written");
  assert.ok(types.includes("heartbeat"), "commit heartbeat written");
  assert.ok(types.includes("qa"), "QA verdict event written");
  assert.ok(types.includes("deploy"), "deploy event written");
  const stateEvents = events.filter((e) => e.type === "state");
  assert.equal(stateEvents.length, 3);
  assert.deepEqual(stateEvents[0]!.payload, { from: "backlog", to: "running" });
  assert.deepEqual(stateEvents[1]!.payload, {
    from: "running",
    to: "deploy",
    summary: `mock summary for task ${task.id}`,
  });
  assert.deepEqual(stateEvents[2]!.payload, {
    from: "deploy",
    to: "done",
    published: `pushed branch task/${task.id}`,
  });
  const heartbeat = events.find((e) => e.type === "heartbeat")!;
  assert.equal(heartbeat.payload!.commit, "c0ffee");

  // Usage captured (role `task`, tagged by task + project, owner stamped).
  const usageRows = (await q.select().from(usage).where(eq(usage.taskId, task.id))).filter(
    (u) => u.role === "task",
  );
  assert.equal(usageRows.length, 1);
  assert.equal(usageRows[0]!.projectId, p.id);
  assert.equal(usageRows[0]!.cost, 0.01);
  assert.equal(usageRows[0]!.owner, "chuck", "Phase 2: usage row stamped with the task owner");

  // Phase 2: the owner is threaded into the task/QA/summary sessions.
  assert.equal(runner.runs[0]!.owner, "chuck", "task context carries the owner");
  assert.equal(qa.runs[0]!.owner, "chuck", "QA context carries the owner");
  assert.equal(summary.calls[0]!.owner, "chuck", "summary context carries the owner");

  // The runner got the task context (project spec + task spec).
  assert.equal(runner.runs.length, 1);
  assert.equal(runner.runs[0]!.project.name, "Alpha");
  assert.equal(runner.runs[0]!.spec.goal, "g");
  assert.equal(runner.runs[0]!.resumeCommit, null, "fresh start");
});

test("dependency gating: task starts only when all dep ideas have done tasks", async () => {
  const { q, services, runner, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const a = await makeBacklogTask(q, services, p.id, "Base work");
  const b = await makeBacklogTask(q, services, p.id, "Dependent work", [a.idea.id]);

  // Hold A's run open so A stays `running` (dep unsatisfied) deterministically.
  runner.behavior.set(a.task.id, "hang");

  // Dep not done → B waits (A starts).
  await orch.start();
  await orch.tick();
  assert.equal((await getTask(q, a.task.id)).state, "running", "dep-free task starts");
  assert.equal((await getTask(q, b.task.id)).state, "backlog", "dependent task waits");

  // startTask rejects while deps are unsatisfied.
  await assert.rejects(
    orch.startTask(b.task.id),
    (err: unknown) => err instanceof Error && /waiting on: Base work/.test(err.message),
  );

  // taskDependencyStatus agrees.
  const status = await taskDependencyStatus(q as any, b.idea.id);
  assert.deepEqual(status.waitingOn, [a.idea.id]);
  assert.equal(status.satisfied, false);

  // A's task done → B unblocks on the next tick.
  runner.abort(a.task.id);
  await orch.settled();
  assert.equal((await getTask(q, a.task.id)).state, "done");
  assert.equal((await taskDependencyStatus(q as any, b.idea.id)).satisfied, true);
  await orch.tick();
  assert.equal((await getTask(q, b.task.id)).state, "running");
  await orch.settled();
});
test("slots: CONCURRENT_TASKS limits parallel running tasks", async () => {
  const { q, services, runner, orch } = await setup({ concurrentTasks: 1 });
  const p = await services.createProject({ name: "Alpha" });
  const t1 = await makeBacklogTask(q, services, p.id, "Task one");
  const t2 = await makeBacklogTask(q, services, p.id, "Task two");

  // Hold t1 in flight so the slot stays taken deterministically.
  runner.behavior.set(t1.task.id, "hang");

  // One slot: only the oldest eligible task starts.
  await orch.start();
  await orch.tick();
  assert.equal((await getTask(q, t1.task.id)).state, "running");
  assert.equal((await getTask(q, t2.task.id)).state, "backlog", "second task waits for a slot");

  // Manual start is refused while the slot is full.
  await assert.rejects(
    orch.startTask(t2.task.id),
    (err: unknown) => err instanceof Error && /no free task slots/.test(err.message),
  );

  // First task completes → slot frees → second starts.
  runner.abort(t1.task.id);
  await orch.settled();
  assert.equal((await getTask(q, t1.task.id)).state, "done");
  await orch.tick();
  assert.equal((await getTask(q, t2.task.id)).state, "running");
  await orch.settled();
});
test("slots: CONCURRENT_TASKS=2 runs two tasks in parallel", async () => {
  const { q, services, runner, orch } = await setup({ concurrentTasks: 2 });
  const p = await services.createProject({ name: "Alpha" });
  const t1 = await makeBacklogTask(q, services, p.id, "Task one");
  const t2 = await makeBacklogTask(q, services, p.id, "Task two");

  runner.behavior.set(t1.task.id, "hang");
  runner.behavior.set(t2.task.id, "hang");

  await orch.start();
  await orch.tick();
  assert.equal((await getTask(q, t1.task.id)).state, "running");
  assert.equal((await getTask(q, t2.task.id)).state, "running", "both slots used");
  runner.abort(t1.task.id);
  runner.abort(t2.task.id);
  await orch.settled();
  assert.equal((await getTask(q, t1.task.id)).state, "done");
  assert.equal((await getTask(q, t2.task.id)).state, "done");
});

test("session failure → needs_attention with the failure reason", async () => {
  const { q, services, runner, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Crashy task");
  runner.behavior.set(task.id, "fail");

  await orch.start();
  await orch.tick();
  await orch.settled();
  const t = await getTask(q, task.id);
  assert.equal(t.state, "needs_attention");
  const events = await eventsFor(q, task.id);
  const last = events[events.length - 1]!;
  assert.equal(last.type, "state");
  assert.equal(last.payload!.from, "running");
  assert.equal(last.payload!.to, "needs_attention");
  assert.match(String(last.payload!.reason), /mock session crashed/);
});

test("paused backlog tasks are not picked up", async () => {
  const { q, services, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Paused task");
  await q.update(tasks).set({ paused: true }).where(eq(tasks.id, task.id));

  await orch.start();
  await orch.tick();
  assert.equal((await getTask(q, task.id)).state, "backlog", "paused task not picked up");

  await assert.rejects(
    orch.startTask(task.id),
    (err: unknown) => err instanceof Error && /paused/.test(err.message),
  );
});

test("stopTask pauses a running task (abort) and resumeTask re-runs from last_commit", async () => {
  const { q, services, runner, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Long task");
  runner.behavior.set(task.id, "hang");

  await orch.start();
  await orch.tick();
  let t = await getTask(q, task.id);
  assert.equal(t.state, "running");

  // Stop: paused flag + abort; state stays running.
  await orch.stopTask(task.id);
  t = await getTask(q, task.id);
  assert.equal(t.state, "running");
  assert.equal(t.paused, true);
  assert.ok(runner.aborted.includes(task.id), "session aborted");
  const stopEvent = (await eventsFor(q, task.id)).find((e) => e.type === "state" && e.payload?.paused === true)!;
  assert.equal(stopEvent.payload!.reason, "stopped");

  // Guards.
  await assert.rejects(
    orch.stopTask(task.id),
    (err: unknown) => err instanceof Error && /already paused/.test(err.message),
  );
  await assert.rejects(
    orch.resumeTask(999),
    (err: unknown) => err instanceof Error && /not found/.test(err.message),
  );

  // The aborted run settles without changing state (still running + paused).
  await orch.settled();
  t = await getTask(q, task.id);
  assert.equal(t.state, "running");
  assert.equal(t.paused, true);

  // One-click resume: un-pause + re-run from last_commit (resume context).
  runner.behavior.delete(task.id); // the resumed run completes normally
  await orch.resumeTask(task.id);
  t = await getTask(q, task.id);
  assert.equal(t.paused, false);
  const resumeEvent = (await eventsFor(q, task.id)).find((e) => e.type === "state" && e.payload?.paused === false)!;
  assert.equal(resumeEvent.payload!.reason, "resumed");

  await orch.settled();
  t = await getTask(q, task.id);
  assert.equal(t.state, "done", "resumed run completes to done");
  const resumeRun = runner.runs[runner.runs.length - 1]!;
  assert.equal(resumeRun.resumeCommit, "c0ffee", "resumes from last_commit");
  assert.ok((resumeRun.progressSummary ?? "").includes("Last commit: c0ffee"), "progress summary re-injected");

  // resumeTask on a non-paused task → 409.
  await assert.rejects(
    orch.resumeTask(task.id),
    (err: unknown) => err instanceof Error && /not paused/.test(err.message),
  );
});

test("startTask guards: wrong state, unknown task, failTask transition", async () => {
  const { q, services, runner, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Guarded task");

  // Unknown task → 404.
  await assert.rejects(
    orch.startTask(999),
    (err: unknown) => err instanceof Error && /not found/.test(err.message),
  );

  // Hold the run in flight so failTask acts on a deterministically running task.
  runner.behavior.set(task.id, "hang");
  await orch.startTask(task.id);
  // Now running → startTask again → 409.
  await assert.rejects(
    orch.startTask(task.id),
    (err: unknown) => err instanceof Error && /not in the backlog/.test(err.message),
  );

  // failTask: running → needs_attention (QA/deploy/watchdog failures use this).
  await orch.failTask(task.id, "qa exhausted");
  const t = await getTask(q, task.id);
  assert.equal(t.state, "needs_attention");
  const events = await eventsFor(q, task.id);
  const last = events[events.length - 1]!;
  assert.equal(last.payload!.to, "needs_attention");
  assert.equal(last.payload!.reason, "qa exhausted");

  // The in-flight run settles without overriding the failure state.
  runner.abort(task.id);
  await orch.settled();
  assert.equal((await getTask(q, task.id)).state, "needs_attention");

  // failTask on a done task → 409.
  await q.update(tasks).set({ state: "done" }).where(eq(tasks.id, task.id));
  await assert.rejects(
    orch.failTask(task.id, "too late"),
    (err: unknown) => err instanceof Error && /is done/.test(err.message),
  );

  // stopTask on a non-running task → 409.
  await assert.rejects(
    orch.stopTask(task.id),
    (err: unknown) => err instanceof Error && /not running/.test(err.message),
  );
});

test("start/stop: the pickup timer picks up backlog tasks and stops cleanly", async () => {
  const { q, services, orch } = await setup({ concurrentTasks: 1, tickMs: 50, noTimer: false });
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Timed task");

  await orch.start();
  assert.equal(orch.isRunning, true);
  // The interval timer picks the task up within a few ticks.
  const deadline = Date.now() + 2000;
  while ((await getTask(q, task.id)).state === "backlog" && Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 10));
  }
  assert.equal((await getTask(q, task.id)).state, "done", "timer-driven pickup completed the task");

  await orch.stop();
  assert.equal(orch.isRunning, false);
});

test("mission context: dependency outputs + resolution plan reach the runner", async () => {
  const { q, services, runner, orch } = await setup();
  const p = await services.createProject({
    name: "Alpha",
    goal: "ship the thing",
    constraints: "no force-push",
  });
  // stateSummary is LLM-maintained (not part of ProjectInput) — set it directly.
  await q.update(projects).set({ stateSummary: "phase 1 done" }).where(eq(projects.id, p.id));
  const dep = await makeBacklogTask(q, services, p.id, "Foundation");
  const main = await makeBacklogTask(q, services, p.id, "On top of foundation", [dep.idea.id]);

  // Foundation done with a completion summary.
  await q
    .update(tasks)
    .set({ state: "done", branch: "task/1", lastCommit: "dep123", stateChangedAt: Date.now() })
    .where(eq(tasks.id, dep.task.id));
  await q.insert(taskEvents).values({
    taskId: dep.task.id,
    ts: Date.now(),
    type: "state",
    payload: { from: "running", to: "deploy", summary: "built the foundation API" },
  });

  // An accepted resolution plan on the main task (Needs Attention → Backlog).
  await q.update(tasks).set({ resolution: "use the foundation API instead of a new one" }).where(eq(tasks.id, main.task.id));

  await orch.startTask(main.task.id);
  await orch.settled();

  const ctx = runner.runs[0]!;
  assert.equal(ctx.deps.length, 1);
  assert.equal(ctx.deps[0]!.text, "Foundation");
  assert.equal(ctx.deps[0]!.branch, "task/1");
  assert.equal(ctx.deps[0]!.lastCommit, "dep123");
  assert.equal(ctx.deps[0]!.summary, "built the foundation API");
  assert.equal(ctx.resolution, "use the foundation API instead of a new one");
  assert.equal(ctx.project.goal, "ship the thing");
  assert.equal(ctx.project.constraints, "no force-push");
  assert.equal(ctx.project.stateSummary, "phase 1 done");
  assert.equal(ctx.ideaText, "On top of foundation");
});

// ---------------------------------------------------------------------------
// Slice 3c: restartTask (needs_attention → backlog) + resume on pickup
// ---------------------------------------------------------------------------

test("restartTask: needs_attention → backlog with note, QA reset; guards", async () => {
  const { q, services, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Broken task");

  // Simulate a QA-exhausted failure.
  await q
    .update(tasks)
    .set({ state: "needs_attention", qaRounds: 2, lastCommit: "cafe1234", branch: `task/${task.id}`, stateChangedAt: Date.now() })
    .where(eq(tasks.id, task.id));
  await q.insert(taskEvents).values({
    taskId: task.id,
    ts: Date.now(),
    type: "state",
    payload: { from: "running", to: "needs_attention", reason: "QA exhausted after 2 rounds" },
  });

  // Guards: not needs_attention.
  const other = await makeBacklogTask(q, services, p.id, "Backlog task");
  await assert.rejects(
    orch.restartTask(other.task.id, "note"),
    (err: unknown) => err instanceof Error && /not needs_attention/.test(err.message),
  );

  // Restart with a resolution note.
  const restarted = await orch.restartTask(task.id, "fix the auth token, then re-run");
  assert.equal(restarted.state, "backlog");
  assert.equal(restarted.qaRounds, 0, "QA rounds reset");
  assert.equal(restarted.resolution, "fix the auth token, then re-run", "note becomes the plan");

  const events = await eventsFor(q, task.id);
  const last = events[events.length - 1]!;
  assert.equal(last.type, "state");
  assert.equal(last.payload!.from, "needs_attention");
  assert.equal(last.payload!.to, "backlog");
  assert.match(String(last.payload!.reason), /restarted/);

  // Restart without a note keeps any existing resolution.
  const { task: t2 } = await makeBacklogTask(q, services, p.id, "Broken again");
  await q.update(tasks).set({ state: "needs_attention", qaRounds: 1, stateChangedAt: Date.now() }).where(eq(tasks.id, t2.id));
  await q.update(tasks).set({ resolution: "existing plan" }).where(eq(tasks.id, t2.id));
  const r2 = await orch.restartTask(t2.id);
  assert.equal(r2.resolution, "existing plan", "existing plan kept");
  assert.equal(r2.qaRounds, 0);
});

test("restarted task pickup: resume from last_commit, plan + progress injected", async () => {
  const { q, services, runner, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeBacklogTask(q, services, p.id, "Restart me");

  // A failed run left a last commit + log trail.
  await q
    .update(tasks)
    .set({
      state: "needs_attention",
      qaRounds: 2,
      lastCommit: "cafe1234",
      branch: `task/${task.id}`,
      workspace: `task-${task.id}`,
      stateChangedAt: Date.now(),
    })
    .where(eq(tasks.id, task.id));
  await q.insert(taskEvents).values([
    { taskId: task.id, ts: Date.now() - 1000, type: "log", payload: { line: "[agent] half done" } },
    {
      taskId: task.id,
      ts: Date.now(),
      type: "state",
      payload: { from: "running", to: "needs_attention", reason: "QA exhausted after 2 rounds" },
    },
  ]);

  // Resolution dialog Accept: plan + restart.
  await q.update(tasks).set({ resolution: "skip the broken step and re-run" }).where(eq(tasks.id, task.id));
  await orch.restartTask(task.id);

  // Pickup resumes from last_commit with the plan + progress summary.
  await orch.start();
  await orch.tick();
  await orch.settled();

  const ctx = runner.runs[0]!;
  assert.equal(ctx.resumeCommit, "cafe1234", "resume from last_commit");
  assert.equal(ctx.resolution, "skip the broken step and re-run", "plan injected");
  assert.ok(ctx.progressSummary, "progress summary on resume");
  assert.ok(ctx.progressSummary!.includes("half done"), "progress from the event trail");
  const t = await getTask(q, task.id);
  assert.equal(t.state, "done", "restarted task completes the pipeline");
});
