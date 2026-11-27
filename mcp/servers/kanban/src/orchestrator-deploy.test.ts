/**
 * Orchestrator Slice 3b tests: QA gate + deploy stage + project summary
 * update, over a real temp sqlite db with mocked task runner / QA gate /
 * deploy stage / summary updater (no network, no model, no git).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { eq } from "drizzle-orm";
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

const SPEC = { goal: "g", steps: ["s1"], acceptance: ["a1"], kind: "code" as const };

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
    agentConcurrentTasks: 1,
    agentSlugs: [],
    workspaceCleanupDays: 7,
    server: { bindAddr: "127.0.0.1", port: 3000 },
  };
}

/** Mocked task pipeline: completes immediately (or holds until aborted). */
class MockTaskRunner implements TaskRunner {
  runs: TaskRunContext[] = [];
  aborted: number[] = [];
  /** Task ids whose runs stay open until aborted. */
  hold = new Set<number>();
  private resolvers = new Map<number, () => void>();

  run(ctx: TaskRunContext): Promise<TaskRunResult> {
    this.runs.push(ctx);
    ctx.onLog?.("task log line");
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
    return new Promise<TaskRunResult>((resolve) => {
      this.resolvers.set(ctx.taskId, () => resolve({ summary: `task ${ctx.taskId} done`, lastCommit: "c0ffee" }));
      // Auto-complete unless the test holds the run open.
      if (!this.hold.has(ctx.taskId)) {
        setImmediate(() => {
          const r = this.resolvers.get(ctx.taskId);
          if (r) {
            this.resolvers.delete(ctx.taskId);
            r();
          }
        });
      }
    });
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

/** Scripted QA gate: one verdict per call (default pass). */
class MockQaGate implements QaGateLike {
  readonly maxRounds = 2;
  verdicts: QaVerdict[] = [];
  runs: QaRunContext[] = [];

  run(ctx: QaRunContext): Promise<QaVerdict> {
    this.runs.push(ctx);
    ctx.onUsage?.({
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
    return Promise.resolve(this.verdicts.shift() ?? { pass: true, feedback: "" });
  }
}

/** Scripted deploy stage: results / failures per call (default ok). */
class MockDeployRunner implements DeployRunnerLike {
  results: DeployResult[] = [];
  failures: string[] = [];
  ctxs: DeployContext[] = [];

  deploy(ctx: DeployContext): Promise<DeployResult> {
    this.ctxs.push(ctx);
    const fail = this.failures.shift();
    if (fail) return Promise.reject(new Error(fail));
    return Promise.resolve(this.results.shift() ?? { published: "pushed branch task/7", target: "origin" });
  }
}

/** Scripted summary updater (default: a fixed new summary). */
class MockSummaryUpdater implements SummaryUpdaterLike {
  calls: SummaryUpdateContext[] = [];
  failures: string[] = [];
  reply = "New project state summary.";

  update(ctx: SummaryUpdateContext): Promise<string> {
    this.calls.push(ctx);
    ctx.onUsage?.({
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
    const fail = this.failures.shift();
    if (fail) return Promise.reject(new Error(fail));
    return Promise.resolve(this.reply);
  }
}

async function setup() {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-orch3b-"));
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const services = createKanbanServices(db);
  const runner = new MockTaskRunner();
  const qa = new MockQaGate();
  const deploy = new MockDeployRunner();
  const summary = new MockSummaryUpdater();
  const orch = new Orchestrator({
    cfg,
    db,
    agent: {} as unknown as AgentRuntime,
    tasks: runner,
    qa,
    deploy,
    summary,
    workspaceRoot: path.join(dir, "workspace"),
    noTimer: true,
  });
  return { cfg, db, q, services, runner, qa, deploy, summary, orch, dir };
}

function one<T>(r: T | T[], label: string): T {
  const row = Array.isArray(r) ? r[0] : r;
  assert.ok(row, label);
  return row;
}

async function getTask(q: BetterSQLite3Database<any>, id: number): Promise<TaskRow> {
  const rows = await q.select().from(tasks).where(eq(tasks.id, id));
  return rows[0]!;
}

async function eventsFor(q: BetterSQLite3Database<any>, taskId: number) {
  const rows = await q.select().from(taskEvents).where(eq(taskEvents.taskId, taskId));
  return [...rows].sort((a, b) => a.id - b.id);
}

async function makeTask(q: BetterSQLite3Database<any>, services: KanbanServices, projectId: number, text: string) {
  const idea = await services.addIdea(projectId, text);
  await q
    .update(ideas)
    .set({ state: "moved", spec: SPEC, dependsOn: [] })
    .where(eq(ideas.id, idea.id));
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

test("QA pass → deploy → done: events, usage (task/qa/summary), project summary update", async () => {
  const { q, services, runner, qa, deploy, summary, orch } = await setup();
  const p = await services.createProject({
    name: "Alpha",
    repoUrl: "https://github.com/chuck/alpha",
    defaultBranch: "main",
  });
  await q.update(projects).set({ stateSummary: "Phase 1 done." }).where(eq(projects.id, p.id));
  const { task } = await makeTask(q, services, p.id, "Deploy me");

  await orch.start();
  await orch.startTask(task.id);
  await orch.settled();

  const t = await getTask(q, task.id);
  assert.equal(t.state, "done", "QA pass + deploy ok → done");
  assert.equal(t.lastCommit, "c0ffee");
  assert.equal(t.qaRounds, 0, "no failed QA rounds");

  // QA saw the completion summary + workspace + round 1.
  assert.equal(qa.runs.length, 1);
  assert.equal(qa.runs[0]!.round, 1);
  assert.equal(qa.runs[0]!.completionSummary, `task ${task.id} done`);
  assert.ok(qa.runs[0]!.workspace.endsWith(`task-${task.id}`), "QA in the task workspace");

  // Deploy got the routed context (kind code, branch, workspace).
  assert.equal(deploy.ctxs.length, 1);
  assert.equal(deploy.ctxs[0]!.kind, "code");
  assert.equal(deploy.ctxs[0]!.branch, `task/${task.id}`);
  assert.ok(deploy.ctxs[0]!.workspace.endsWith(`task-${task.id}`));

  // Summary: previous + what was deployed → new state_summary persisted.
  assert.equal(summary.calls.length, 1);
  assert.equal(summary.calls[0]!.previousSummary, "Phase 1 done.");
  assert.equal(summary.calls[0]!.projectName, "Alpha");
  assert.ok(summary.calls[0]!.deployed.includes(`task ${task.id} (code)`));
  const project = (await q.select().from(projects).where(eq(projects.id, p.id)))[0]!;
  assert.equal(project.stateSummary, "New project state summary.");

  // Event trail: state, qa, state, deploy, state.
  const events = await eventsFor(q, task.id);
  const qaEvent = events.find((e) => e.type === "qa")!;
  assert.equal(qaEvent.payload!.round, 1);
  assert.equal(qaEvent.payload!.pass, true);
  const deployEvent = events.find((e) => e.type === "deploy")!;
  assert.equal(deployEvent.payload!.status, "ok");
  assert.equal(deployEvent.payload!.published, "pushed branch task/7");
  const states = events.filter((e) => e.type === "state");
  assert.deepEqual(states.map((s) => s.payload!.to), ["running", "deploy", "done"]);

  // Usage: task + qa (tagged by task) + summary (taskId null).
  const usageRows = await q.select().from(usage).where(eq(usage.taskId, task.id));
  const byRole = new Map(usageRows.map((u) => [u.role, u]));
  assert.equal(byRole.get("task")!.cost, 0.01);
  assert.equal(byRole.get("qa")!.role, "qa");
  const summaryUsage = (await q.select().from(usage).where(eq(usage.role, "summary"))).filter(
    (u) => u.taskId === null,
  );
  assert.equal(summaryUsage.length, 1, "summary usage row with null taskId");
  assert.equal(summaryUsage[0]!.projectId, p.id);
});

test("QA fail → re-run with feedback → QA pass → done (qa_rounds tracked)", async () => {
  const { q, services, runner, qa, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeTask(q, services, p.id, "Flaky work");
  qa.verdicts.push({ pass: false, feedback: "tests fail: 3 errors" });
  qa.verdicts.push({ pass: true, feedback: "" });

  await orch.start();
  await orch.startTask(task.id);
  await orch.settled();

  const t = await getTask(q, task.id);
  assert.equal(t.state, "done");
  assert.equal(t.qaRounds, 1, "one failed round recorded");

  // Task session ran twice; the re-run got the QA feedback as its prompt.
  assert.equal(runner.runs.length, 2);
  assert.ok(runner.runs[1]!.prompt, "re-run has a custom prompt");
  assert.ok(runner.runs[1]!.prompt!.includes("QA round 1 FAILED"), "feedback prompt");
  assert.ok(runner.runs[1]!.prompt!.includes("tests fail: 3 errors"), "the feedback itself");
  assert.equal(runner.runs[0]!.prompt, undefined, "first run uses the default kickoff");

  // QA ran twice; events show the failed round + the re-run state event.
  assert.equal(qa.runs.length, 2);
  assert.equal(qa.runs[0]!.round, 1);
  assert.equal(qa.runs[1]!.round, 2);
  const events = await eventsFor(q, task.id);
  const qaEvents = events.filter((e) => e.type === "qa");
  assert.equal(qaEvents.length, 2);
  assert.equal(qaEvents[0]!.payload!.pass, false);
  assert.equal(qaEvents[0]!.payload!.feedback, "tests fail: 3 errors");
  const rerun = events.find((e) => e.type === "state" && e.payload!.reason === "QA round 1 failed — re-running with feedback");
  assert.ok(rerun, "re-run state event");
});

test("QA exhausted after 2 rounds → needs_attention; retryDeploy refuses", async () => {
  const { q, services, runner, qa, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeTask(q, services, p.id, "Broken work");
  qa.verdicts.push({ pass: false, feedback: "round 1 issues" });
  qa.verdicts.push({ pass: false, feedback: "round 2 issues" });

  await orch.start();
  await orch.startTask(task.id);
  await orch.settled();

  const t = await getTask(q, task.id);
  assert.equal(t.state, "needs_attention", "QA exhausted → needs_attention");
  assert.equal(t.qaRounds, 2);
  assert.equal(runner.runs.length, 2, "two task runs (round 1 + re-run)");

  const events = await eventsFor(q, task.id);
  const last = events[events.length - 1]!;
  assert.equal(last.type, "state");
  assert.equal(last.payload!.to, "needs_attention");
  assert.equal(last.payload!.reason, "QA exhausted after 2 rounds");
  assert.equal(last.payload!.feedback, "round 2 issues");

  // retry_deploy refuses QA-exhausted tasks (resolution dialog instead).
  await assert.rejects(
    orch.retryDeploy(task.id),
    (err: unknown) => err instanceof Error && /failed QA/.test(err.message),
  );
});

test("deploy failure → needs_attention; retryDeploy re-runs only the deploy step", async () => {
  const { q, services, qa, deploy, summary, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeTask(q, services, p.id, "Push me");
  deploy.failures.push("push failed: auth");

  await orch.start();
  await orch.startTask(task.id);
  await orch.settled();

  let t = await getTask(q, task.id);
  assert.equal(t.state, "needs_attention", "deploy failure → needs_attention");
  const events = await eventsFor(q, task.id);
  const deployEvent = events.filter((e) => e.type === "deploy").pop()!;
  assert.equal(deployEvent.payload!.status, "failed");
  assert.equal(deployEvent.payload!.detail, "push failed: auth");
  const last = events[events.length - 1]!;
  assert.equal(last.payload!.reason, "deploy failed: push failed: auth");
  assert.equal(summary.calls.length, 0, "no summary on a failed deploy");

  // retry_deploy: re-runs ONLY the deploy step (no new QA round, no task run).
  const runsBefore = qa.runs.length;
  await orch.retryDeploy(task.id);
  t = await getTask(q, task.id);
  assert.equal(t.state, "done", "retry deploy → done");
  assert.equal(qa.runs.length, runsBefore, "QA not re-run");
  assert.equal(deploy.ctxs.length, 2, "deploy re-run");
  assert.equal(summary.calls.length, 1, "summary on the successful retry");

  // retry_deploy guards: backlog tasks are not deployable.
  const { task: t2 } = await makeTask(q, services, p.id, "Another task");
  await assert.rejects(
    orch.retryDeploy(t2.id),
    (err: unknown) => err instanceof Error && /not deployable/.test(err.message),
  );
});

test("summary update failure does not fail an already-deployed task", async () => {
  const { q, services, summary, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeTask(q, services, p.id, "Summarize me");
  summary.failures.push("llm timeout");

  await orch.start();
  await orch.startTask(task.id);
  await orch.settled();

  const t = await getTask(q, task.id);
  assert.equal(t.state, "done", "task still done");
  const events = await eventsFor(q, task.id);
  const summaryFailed = events.find((e) => e.type === "deploy" && e.payload!.status === "summary_failed");
  assert.ok(summaryFailed, "summary_failed deploy event");
  assert.match(String(summaryFailed.payload!.detail), /llm timeout/);
  const project = (await q.select().from(projects).where(eq(projects.id, p.id)))[0]!;
  assert.equal(project.stateSummary, null, "old (null) summary kept");
});

test("paused task: QA/deploy do not run after a stop mid-run", async () => {
  const { q, services, runner, qa, deploy, orch } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const { task } = await makeTask(q, services, p.id, "Long task");

  // Hold the task run open, then stop it mid-run.
  runner.hold.add(task.id);
  const p_run = orch.startTask(task.id).then(() => orch.settled());
  await new Promise((r) => setTimeout(r, 50)); // let the run get in flight
  await orch.stopTask(task.id); // paused + abort
  await p_run;

  const t = await getTask(q, task.id);
  assert.equal(t.state, "running");
  assert.equal(t.paused, true);
  assert.equal(qa.runs.length, 0, "QA did not run on a stopped task");
  assert.equal(deploy.ctxs.length, 0, "deploy did not run");
});
