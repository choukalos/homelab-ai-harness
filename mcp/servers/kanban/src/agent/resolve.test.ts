/**
 * Resolution dialog tests (Slice 3c) with a mocked Pi session — no network,
 * no model. The mock session factory is file-backed (SessionManager.open
 * semantics): failure context seeding, chat turns, usage (role `resolve`),
 * and Accept → plan into tasks.resolution → restart (backlog, QA reset).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { eq } from "drizzle-orm";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import type { KanbanConfig } from "../config.js";
import { initDb } from "../db/index.js";
import { ideas, taskEvents, tasks, usage, type TaskRow } from "../db/schema.js";
import { createKanbanServices, ServiceError } from "../services/index.js";
import {
  RESOLVE_FINALIZE_PROMPT,
  buildResolveSystemPrompt,
  cleanResolutionPlan,
  collectFailureContext,
  ResolutionDialog,
  type FailureContext,
} from "./resolve.js";
import { createMockResolution, type MockResolution } from "./resolve-mock.js";

// ---------------------------------------------------------------------------
// Test harness
// ---------------------------------------------------------------------------

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

interface Harness {
  q: BetterSQLite3Database<any>;
  services: ReturnType<typeof createKanbanServices>;
  ws: string;
  sessions: string;
  mock: MockResolution;
  dialog: ResolutionDialog;
  restarted: Array<{ taskId: number }>;
  projectId: number;
}

async function setup(): Promise<Harness> {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-resolve-"));
  const ws = path.join(dir, "workspace");
  const sessions = path.join(dir, "sessions");
  mkdirSync(ws, { recursive: true });
  mkdirSync(sessions, { recursive: true });
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const services = createKanbanServices(db);
  const mock = createMockResolution();
  const restarted: Array<{ taskId: number }> = [];
  const dialog = new ResolutionDialog({
    db: q,
    cfg,
    sessionFactory: mock.factory,
    workspacePathFor: (taskId) => path.join(ws, `task-${taskId}`),
    sessionsDir: sessions,
    restart: async (taskId) => {
      restarted.push({ taskId });
      // Simulate Orchestrator.restartTask: needs_attention → backlog.
      await q.update(tasks).set({ state: "backlog", qaRounds: 0, stateChangedAt: Date.now() }).where(eq(tasks.id, taskId));
    },
  });
  const project = await services.createProject({
    name: "Resolve Project",
    goal: "ship things",
    constraints: "never force-push",
  });
  return { q, services, ws, sessions, mock, dialog, restarted, projectId: project.id };
}

/** drizzle's returning() is typed `Row | Row[]`; normalize to a single row. */
function one<T>(r: T | T[], label: string): T {
  const row = Array.isArray(r) ? r[0] : r;
  assert.ok(row, label);
  return row;
}

/** Create a needs_attention task with a failure event trail. */
async function makeFailedTask(
  h: Harness,
  opts: { state?: string; qaRounds?: number; lastCommit?: string | null } = {},
): Promise<TaskRow> {
  const idea = await h.services.addIdea(h.projectId, "Fix the broken deploy");
  await h.q.update(ideas).set({ state: "moved" }).where(eq(ideas.id, idea.id));
  const now = Date.now();
  const task = (
    await h.q
      .insert(tasks)
      .values({
        ideaId: idea.id,
        projectId: h.projectId,
        spec: { goal: "Fix the deploy", steps: ["diagnose", "fix"], acceptance: ["push works"], kind: "code" },
        state: opts.state ?? "needs_attention",
        stateChangedAt: now,
        createdAt: now,
        branch: "task/7",
        workspace: "/workspace/task-7",
        lastCommit: opts.lastCommit ?? "deadbeef",
        qaRounds: opts.qaRounds ?? 2,
      })
      .returning()
  );
  const t = one(task, "task");
  if (opts.state === undefined || opts.state === "needs_attention") {
    await h.q.insert(taskEvents).values([
      { taskId: t.id, ts: now, type: "state", payload: { from: "backlog", to: "running" } },
      { taskId: t.id, ts: now + 1, type: "log", payload: { line: "[tool] bash: {\"command\":\"npm test\"}" } },
      { taskId: t.id, ts: now + 2, type: "log", payload: { line: "[agent] tests are failing" } },
      { taskId: t.id, ts: now + 3, type: "qa", payload: { round: 2, pass: false, feedback: "3 tests fail in deploy.spec.ts" } },
      {
        taskId: t.id,
        ts: now + 4,
        type: "state",
        payload: { from: "running", to: "needs_attention", reason: "QA exhausted after 2 rounds", feedback: "3 tests fail in deploy.spec.ts" },
      },
    ]);
  }
  return t;
}

// ---------------------------------------------------------------------------
// Plan parsing + prompt building (pure)
// ---------------------------------------------------------------------------

test("cleanResolutionPlan: plain text, code fence, and quoted forms", () => {
  assert.equal(cleanResolutionPlan("  step one\nstep two  "), "step one\nstep two");
  assert.equal(cleanResolutionPlan("```text\nplan A\nplan B\n```"), "plan A\nplan B");
  assert.equal(cleanResolutionPlan('"quoted plan"'), "quoted plan");
  assert.throws(() => cleanResolutionPlan(""), ServiceError);
  assert.throws(() => cleanResolutionPlan("   "), ServiceError);
  assert.throws(() => cleanResolutionPlan("```\n```"), ServiceError);
});

test("buildResolveSystemPrompt: failure context, task spec, project, workspace availability", async () => {
  const h = await setup();
  const task = await makeFailedTask(h);
  const failure: FailureContext = {
    reason: "QA exhausted after 2 rounds",
    qaFeedback: "3 tests fail in deploy.spec.ts",
    logTail: ["[agent] tests are failing"],
    lastCommit: "deadbeef",
  };
  const withWs = buildResolveSystemPrompt(
    task,
    { name: "Resolve Project", goal: "ship things", repoUrl: null, defaultBranch: null, constraints: "never force-push", notes: null },
    failure,
    "/workspace/task-7",
  );
  assert.ok(withWs.includes("QA exhausted after 2 rounds"), "failure reason");
  assert.ok(withWs.includes("QA feedback: 3 tests fail in deploy.spec.ts"), "QA feedback");
  assert.ok(withWs.includes("[agent] tests are failing"), "log tail");
  assert.ok(withWs.includes("deadbeef"), "last commit");
  assert.ok(withWs.includes("Fix the deploy"), "task goal");
  assert.ok(withWs.includes("never force-push"), "project constraints");
  assert.ok(withWs.includes("workspace still exists at /workspace/task-7"), "workspace tools");
  assert.ok(withWs.includes("run tests/builds"), "workspace tools guidance");

  const noWs = buildResolveSystemPrompt(
    task,
    { name: "Resolve Project", goal: "ship things", repoUrl: null, defaultBranch: null, constraints: null, notes: null },
    failure,
    null,
  );
  assert.ok(noWs.includes("workspace no longer exists"), "workspace gone");
  assert.ok(noWs.includes("Work from the failure reason"), "fallback guidance");
  assert.ok(!noWs.includes("workspace still exists"), "no workspace claim");
});

// ---------------------------------------------------------------------------
// Failure context collection
// ---------------------------------------------------------------------------

test("collectFailureContext: reason, QA feedback, log tail, last commit", async () => {
  const h = await setup();
  const task = await makeFailedTask(h);
  const failure = await collectFailureContext(h.q, task);
  assert.equal(failure.reason, "QA exhausted after 2 rounds");
  assert.equal(failure.qaFeedback, "3 tests fail in deploy.spec.ts");
  assert.deepEqual(failure.logTail, ["[tool] bash: {\"command\":\"npm test\"}", "[agent] tests are failing"]);
  assert.equal(failure.lastCommit, "deadbeef");
});

// ---------------------------------------------------------------------------
// Chat + Accept (mocked session)
// ---------------------------------------------------------------------------

test("sendResolveMessage: turn, usage (role resolve, tagged by task), resolve event", async () => {
  const h = await setup();
  const task = await makeFailedTask(h);

  const msg = await h.dialog.sendResolveMessage(task.id, "what do you think went wrong?");
  assert.equal(msg.role, "assistant");
  assert.ok(msg.text.includes("mock resolution reply"), "assistant reply");

  // Usage: role `resolve`, tagged by task + project.
  const rows = await h.q.select().from(usage).where(eq(usage.taskId, task.id));
  const resolveRows = rows.filter((u) => u.role === "resolve");
  assert.equal(resolveRows.length, 1, "one resolve usage row");
  assert.equal(resolveRows[0]!.projectId, h.projectId);
  assert.equal(resolveRows[0]!.cost, 0.01);

  // Audit event.
  const events = await h.q.select().from(taskEvents).where(eq(taskEvents.taskId, task.id));
  const resolveEvent = events.find((e) => e.type === "resolve");
  assert.ok(resolveEvent, "resolve event appended");
  assert.equal(resolveEvent!.payload!.text, "what do you think went wrong?");
  assert.equal(resolveEvent!.payload!.accepted, undefined);
});

test("acceptResolution: plan into tasks.resolution, restart → backlog, QA reset", async () => {
  const h = await setup();
  const task = await makeFailedTask(h);

  const updated = await h.dialog.acceptResolution(task.id);
  assert.equal(updated.state, "backlog", "restarted to backlog");
  assert.equal(updated.qaRounds, 0, "QA rounds reset");
  assert.ok(updated.resolution, "plan captured");
  assert.ok(updated.resolution!.includes("what went wrong"), "plan content");
  assert.equal(h.restarted.length, 1, "restart() called once");
  assert.equal(h.restarted[0]!.taskId, task.id);

  // The final prompt was sent; an accepted resolve event was appended.
  const session = h.mock.sessions[0]!;
  assert.ok(session.prompts.some((p) => p === RESOLVE_FINALIZE_PROMPT), "FINALIZE prompt sent");
  const events = await h.q.select().from(taskEvents).where(eq(taskEvents.taskId, task.id));
  const accepted = events.find((e) => e.type === "resolve" && e.payload!.accepted === true);
  assert.ok(accepted, "accepted resolve event");
  assert.equal(accepted!.payload!.text, updated.resolution);

  // The session file is kept under /data (resolution output).
  assert.ok(existsSync(h.mock.created[0]!.sessionFile), "session file persisted");
  assert.match(h.mock.created[0]!.sessionFile, /resolve-\d+\.jsonl$/);
});

test("acceptResolution: empty reply → 500, task stays needs_attention", async () => {
  const h = await setup();
  h.mock.setResponder(() => "   ");
  const task = await makeFailedTask(h);
  await assert.rejects(
    h.dialog.acceptResolution(task.id),
    (err: unknown) => err instanceof ServiceError && err.status === 500,
  );
  const fresh = (await h.q.select().from(tasks).where(eq(tasks.id, task.id)))[0]!;
  assert.equal(fresh.state, "needs_attention", "unchanged");
  assert.equal(h.restarted.length, 0, "no restart");
});

test("guards: wrong state → 409, unknown task → 404, empty message → 400", async () => {
  const h = await setup();
  const running = await makeFailedTask(h, { state: "running" });
  await assert.rejects(
    h.dialog.sendResolveMessage(running.id, "hi"),
    (err: unknown) => err instanceof ServiceError && err.status === 409,
  );
  await assert.rejects(
    h.dialog.acceptResolution(9999),
    (err: unknown) => err instanceof ServiceError && err.status === 404,
  );
  const failed = await makeFailedTask(h);
  await assert.rejects(
    h.dialog.sendResolveMessage(failed.id, "   "),
    (err: unknown) => err instanceof ServiceError && err.status === 400,
  );
});

test("cwd: workspace tools when the workspace exists, fallback when cleaned up", async () => {
  const h = await setup();
  // Task 1: workspace exists.
  const t1 = await makeFailedTask(h);
  mkdirSync(path.join(h.ws, `task-${t1.id}`), { recursive: true });
  writeFileSync(path.join(h.ws, `task-${t1.id}`, "README.md"), "workspace file");
  await h.dialog.sendResolveMessage(t1.id, "inspect the workspace");
  const c1 = h.mock.created[0]!;
  assert.equal(c1.cwd, path.join(h.ws, `task-${t1.id}`), "cwd = workspace");
  assert.ok(c1.systemPrompt.includes("workspace still exists"), "prompt: workspace tools");

  // Task 2: workspace cleaned up.
  const t2 = await makeFailedTask(h);
  await h.dialog.sendResolveMessage(t2.id, "diagnose from the log");
  const c2 = h.mock.created.find((o) => o.taskId === t2.id)!;
  assert.equal(c2.cwd, h.sessions, "cwd = fallback (sessions dir)");
  assert.ok(c2.systemPrompt.includes("workspace no longer exists"), "prompt: workspace gone");
});

test("transcript: user + assistant messages in order (persisted across turns)", async () => {
  const h = await setup();
  const task = await makeFailedTask(h);
  await h.dialog.sendResolveMessage(task.id, "first question");
  await h.dialog.sendResolveMessage(task.id, "second question");
  const transcript = await h.dialog.transcript(task.id);
  assert.equal(transcript.length, 4, "two turns → four messages");
  assert.equal(transcript[0]!.role, "user");
  assert.equal(transcript[0]!.text, "first question");
  assert.equal(transcript[1]!.role, "assistant");
  assert.equal(transcript[2]!.role, "user");
  assert.equal(transcript[2]!.text, "second question");
  assert.equal(transcript[3]!.role, "assistant");
});

test("ResolutionDialog requires a sessionFactory or an AgentRuntime", () => {
  assert.throws(
    () =>
      new ResolutionDialog({
        db: {} as never,
        cfg: testCfg("/tmp/x.db"),
        workspacePathFor: (id) => `/workspace/task-${id}`,
        restart: async () => undefined,
      }),
    /sessionFactory or an AgentRuntime/,
  );
});
