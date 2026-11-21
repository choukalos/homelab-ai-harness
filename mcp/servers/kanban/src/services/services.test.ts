/**
 * Service-layer tests (Slice 1): projects, ideas, board — over a real
 * temp sqlite db (the default driver). The MySQL path shares the same
 * service code (identical column sets, src/db/schema.ts).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { eq } from "drizzle-orm";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import type { KanbanConfig } from "../config.js";
import { initDb } from "../db/index.js";
import { ideas, taskEvents, tasks, usage } from "../db/schema.js";
import { createKanbanServices, ServiceError, type KanbanServices } from "./index.js";

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
    concurrentTasks: 1,
    workspaceCleanupDays: 7,
    server: { bindAddr: "127.0.0.1", port: 3000 },
  };
}

async function setup(): Promise<{ services: KanbanServices; q: BetterSQLite3Database<any> }> {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-svc-"));
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  return { services: createKanbanServices(db), q: db.db as unknown as BetterSQLite3Database<any> };
}

/** drizzle's returning() is typed `Row | Row[]`; normalize to a single row. */
function one<T>(r: T | T[], label: string): T {
  const row = Array.isArray(r) ? r[0] : r;
  assert.ok(row, label);
  return row;
}

test("createProject: defaults, fields, and validation", async () => {
  const { services } = await setup();

  const p = await services.createProject({ name: "Alpha" });
  assert.ok(p.id > 0);
  assert.equal(p.name, "Alpha");
  assert.equal(p.description, "");
  assert.equal(p.goal, "");
  assert.equal(p.mediaPaths, null);
  assert.equal(p.stateSummary, null);
  assert.ok(p.createdAt > 0 && p.updatedAt >= p.createdAt);

  const full = await services.createProject({
    name: "Beta",
    description: "beta",
    goal: "ship",
    repoUrl: "https://github.com/chuck/beta",
    defaultBranch: "main",
    blogRepoUrl: "https://github.com/chuck/blog",
    blogContentPath: "content/blog",
    mediaPaths: ["media/a", "media/b"],
    constraints: "no force-push",
    architectureNotes: "see docs/",
    notes: "n",
  });
  assert.equal(full.repoUrl, "https://github.com/chuck/beta");
  assert.deepEqual(full.mediaPaths, ["media/a", "media/b"]);

  await assert.rejects(
    services.createProject({ name: "Alpha" }),
    (err: unknown) => err instanceof ServiceError && err.status === 409,
    "duplicate name → 409",
  );
  await assert.rejects(
    services.createProject({ name: "   " }),
    (err: unknown) => err instanceof ServiceError && err.status === 400,
    "empty name → 400",
  );
  await assert.rejects(
    services.createProject({ name: "x".repeat(256) }),
    (err: unknown) => err instanceof ServiceError && err.status === 400,
    "name too long → 400",
  );
});

test("listProjects / getProject", async () => {
  const { services } = await setup();
  await services.createProject({ name: "Zeta", description: "z" });
  await services.createProject({ name: "Alpha", description: "a" });

  const list = await services.listProjects();
  assert.deepEqual(
    list.map((p) => p.name),
    ["Alpha", "Zeta"],
    "ordered by name",
  );
  assert.deepEqual(Object.keys(list[0]!).sort(), ["description", "id", "name", "owner"], "summary shape");
  assert.equal(list[0]!.owner, "", "no owner stamped → '' (unattributed)");

  const alpha = list.find((p) => p.name === "Alpha")!;
  const got = await services.getProject(alpha.id);
  assert.equal(got?.name, "Alpha");
  assert.equal(got?.description, "a");
  assert.equal(await services.getProject(999), undefined);
});

test("updateProject: partial, rename, clear, conflicts", async () => {
  const { services } = await setup();
  const p = await services.createProject({ name: "Alpha", description: "keep", goal: "g" });
  await services.createProject({ name: "Beta" });

  // Partial update: only name changes.
  const renamed = await services.updateProject(p.id, { name: "Alpha 2" });
  assert.equal(renamed?.name, "Alpha 2");
  assert.equal(renamed?.description, "keep", "untouched fields preserved");

  // Empty string clears a field.
  const cleared = await services.updateProject(p.id, { description: "   " });
  assert.equal(cleared?.description, "");

  // mediaPaths: provided array stored, empty array → null.
  const withMedia = await services.updateProject(p.id, { mediaPaths: ["a", " b ", ""] });
  assert.deepEqual(withMedia?.mediaPaths, ["a", "b"]);
  const noMedia = await services.updateProject(p.id, { mediaPaths: [] });
  assert.equal(noMedia?.mediaPaths, null);

  // Rename onto an existing name → 409.
  await assert.rejects(
    services.updateProject(p.id, { name: "Beta" }),
    (err: unknown) => err instanceof ServiceError && err.status === 409,
  );
  // Same name as itself → allowed (no-op).
  const self = await services.updateProject(p.id, { name: "Alpha 2" });
  assert.equal(self?.name, "Alpha 2");

  // Unknown project → undefined.
  assert.equal(await services.updateProject(999, { name: "Ghost" }), undefined);
});

test("addIdea / listIdeas", async () => {
  const { services } = await setup();
  const a = await services.createProject({ name: "Alpha" });
  const b = await services.createProject({ name: "Beta" });

  const i1 = await services.addIdea(a.id, "  an idea  ");
  assert.equal(i1.text, "an idea", "trimmed");
  assert.equal(i1.state, "idea");
  assert.equal(i1.projectName, "Alpha");
  assert.equal(i1.spec, null);
  assert.deepEqual(i1.dependsOn, []);

  await services.addIdea(a.id, "second");
  await services.addIdea(b.id, "beta idea");

  const all = await services.listIdeas();
  assert.equal(all.length, 3);
  assert.ok(all.every((i) => i.projectName !== ""));

  const onlyA = await services.listIdeas(a.id);
  assert.equal(onlyA.length, 2);
  assert.ok(onlyA.every((i) => i.projectName === "Alpha"));

  await assert.rejects(
    services.addIdea(a.id, "   "),
    (err: unknown) => err instanceof ServiceError && err.status === 400,
  );
  await assert.rejects(
    services.addIdea(999, "orphan"),
    (err: unknown) => err instanceof ServiceError && err.status === 404,
  );
});

test("owner attribution: createProject / addIdea stamp the caller; tasks inherit", async () => {
  const { services, q } = await setup();
  const p = await services.createProject({ name: "Alpha" }, "chuck");
  assert.equal(p.owner, "chuck");
  const p2 = await services.createProject({ name: "Beta" });
  assert.equal(p2.owner, "", "no owner arg → ''");

  const i1 = await services.addIdea(p.id, "chuck's idea", "chuck");
  assert.equal(i1.owner, "chuck");
  const i2 = await services.addIdea(p.id, "dylan's idea", "dylan");
  assert.equal(i2.owner, "dylan");

  // Tasks inherit the idea's owner at move-to-backlog — even when a
  // different caller pushes the move.
  const spec = { goal: "g", steps: [], acceptance: [], kind: "code" as const };
  for (const i of [i1, i2]) {
    await q.update(ideas).set({ state: "icebox", spec, dependsOn: [] }).where(eq(ideas.id, i.id));
  }
  const result = await services.moveIceboxToBacklog([i1.id, i2.id]);
  assert.equal(result.tasks[0]!.owner, "chuck");
  assert.equal(result.tasks[1]!.owner, "dylan");
  const t1 = (await q.select().from(tasks).where(eq(tasks.ideaId, i1.id)))[0]!;
  assert.equal(t1.owner, "chuck");

  // The board + boardStatus carry the owner through.
  const board = await services.board();
  const card = board.columns.flatMap((c) => c.cards).find((c) => c.taskId === t1.id)!;
  assert.equal(card.owner, "chuck");
  const status = await services.boardStatus();
  assert.equal(status.counts.backlog, 2);
  assert.deepEqual(status.running, []);
  assert.deepEqual(status.needsAttention, []);
  const filtered = await services.boardStatus({ owner: "dylan" });
  assert.equal(filtered.counts.backlog, 1);
  assert.equal(filtered.running.length, 0);
});

test("boardStatus: needs-attention summary (reason, last activity, resolution) + running + filters", async () => {
  const { services, q } = await setup();
  const now = Date.now();
  const p = await services.createProject({ name: "Alpha" }, "chuck");
  const d = await services.createProject({ name: "Beta" }, "dylan");
  const spec = { goal: "g", steps: [], acceptance: [], kind: "code" as const };

  const mkTask = async (projectId: number, text: string, state: string, owner: string) => {
    const idea = await services.addIdea(projectId, text, owner);
    const t = one(
      await q
        .insert(tasks)
        .values({ ideaId: idea.id, projectId, spec, state, stateChangedAt: now, createdAt: now, owner })
        .returning(),
      "task",
    );
    return t;
  };

  const stuck = await mkTask(p.id, "Stuck task", "needs_attention", "chuck");
  const running = await mkTask(p.id, "Running task", "running", "dylan");
  const done = await mkTask(d.id, "Done task", "done", "dylan");

  await q.insert(taskEvents).values([
    { taskId: stuck.id, ts: now - 60000, type: "state", payload: { from: "running", to: "needs_attention", reason: "watchdog: no activity for 10m" } },
    { taskId: stuck.id, ts: now - 30000, type: "log", payload: { line: "last line before silence" } },
    { taskId: running.id, ts: now - 1000, type: "heartbeat", payload: { kind: "watchdog" } },
  ]);
  await q.insert(usage).values([
    { projectId: p.id, taskId: running.id, ts: now, role: "task", model: "m", thinking: "medium", tokensIn: 10, tokensOut: 5, cost: 0.42 },
  ]);

  const status = await services.boardStatus();
  assert.deepEqual(status.counts, { backlog: 0, running: 1, deploy: 0, done: 1, needs_attention: 1 });
  assert.equal(status.needsAttention.length, 1);
  const na = status.needsAttention[0]!;
  assert.equal(na.taskId, stuck.id);
  assert.equal(na.title, "Stuck task");
  assert.equal(na.project, "Alpha");
  assert.equal(na.owner, "chuck");
  assert.equal(na.reason, "watchdog: no activity for 10m");
  assert.equal(na.lastActivityAt, now - 30000, "last task_event ts");
  assert.equal(na.resolution, null);
  assert.equal(status.running.length, 1);
  assert.equal(status.running[0]!.taskId, running.id);
  assert.equal(status.running[0]!.owner, "dylan");
  assert.equal(status.running[0]!.cost, 0.42);
  assert.equal(status.running[0]!.paused, false);

  // Project filter: only Beta's tasks.
  const beta = await services.boardStatus({ projectId: d.id });
  assert.equal(beta.counts.done, 1);
  assert.deepEqual(beta.needsAttention, []);
  // Owner filter: only dylan's tasks.
  const dylan = await services.boardStatus({ owner: "dylan" });
  assert.equal(dylan.counts.running, 1);
  assert.equal(dylan.counts.done, 1);
  assert.deepEqual(dylan.needsAttention, []);
});

test("board: columns, usage, dependency status, month stats", async () => {
  const { services, q } = await setup();
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
    { projectId: alpha.id, taskId: t2.id, ts: now, role: "qa", model: "m", thinking: "xhigh", tokensIn: 10, tokensOut: 5, cost: 0.25 },
    { projectId: beta.id, taskId: null, ts: now, role: "groom", model: "m", thinking: "xhigh", tokensIn: 10, tokensOut: 5, cost: 0.1 },
  ]);

  const board = await services.board();

  // Five columns in state order.
  assert.deepEqual(
    board.columns.map((c) => c.state),
    ["backlog", "running", "deploy", "done", "needs_attention"],
  );
  const byState = new Map(board.columns.map((c) => [c.state, c.cards]));

  const done = byState.get("done")!;
  assert.equal(done.length, 1);
  assert.equal(done[0]!.taskId, t4.id);
  assert.equal(done[0]!.projectName, "Alpha");
  assert.equal(done[0]!.title, "Third idea");
  assert.equal(done[0]!.cost, 0);
  assert.deepEqual(done[0]!.waitingOn, []);

  const backlog = byState.get("backlog")!;
  assert.equal(backlog.length, 1);
  assert.equal(backlog[0]!.taskId, t2.id);
  assert.deepEqual(backlog[0]!.waitingOn, ["First idea"], "waiting on the unsatisfied dep");
  assert.equal(backlog[0]!.cost, 0.25);

  const running = byState.get("running")!;
  assert.equal(running.length, 2, "t1 (Alpha) + t3 (Beta)");
  assert.equal(running[0]!.taskId, t1.id);
  assert.equal(running[0]!.projectName, "Alpha");
  assert.equal(running[0]!.cost, 1.5);
  assert.equal(running[1]!.taskId, t3.id);
  assert.equal(running[1]!.projectName, "Beta");
  assert.equal(running[1]!.cost, 0);
  assert.equal(running[1]!.paused, false);

  assert.equal(board.month.spend, 1.85, "month spend incl. null-task usage");
  assert.equal(board.month.completed, 1, "one done task this month");

  // A done dep satisfies the wait.
  await q.update(tasks).set({ state: "done", stateChangedAt: now }).where(eq(tasks.id, t1.id));
  const board2 = await services.board();
  const backlog2 = board2.columns.find((c) => c.state === "backlog")!;
  assert.deepEqual(backlog2.cards[0]!.waitingOn, [], "dep satisfied once the idea has a done task");
});

test("board: empty db", async () => {
  const { services } = await setup();
  const board = await services.board();
  assert.equal(board.columns.length, 5);
  assert.ok(board.columns.every((c) => c.cards.length === 0));
  assert.equal(board.month.spend, 0);
  assert.equal(board.month.completed, 0);
});

// ---------------------------------------------------------------------------
// Slice 2: icebox → backlog
// ---------------------------------------------------------------------------

/** Put an idea into the icebox with a finalized spec (fixture). */
async function iceboxIdea(q: BetterSQLite3Database<any>, services: KanbanServices, projectId: number, text: string) {
  const idea = await services.addIdea(projectId, text);
  await q
    .update(ideas)
    .set({
      state: "icebox",
      spec: { goal: `goal: ${text}`, steps: ["s1"], acceptance: ["a1"], kind: "code" },
      dependsOn: [],
    })
    .where(eq(ideas.id, idea.id));
  return idea;
}

test("moveIceboxToBacklog: one or more ideas → backlog tasks, ideas moved", async () => {
  const { services, q } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const a1 = await iceboxIdea(q, services, p.id, "First");
  const a2 = await iceboxIdea(q, services, p.id, "Second");
  // A raw idea that must NOT be movable.
  const raw = await services.addIdea(p.id, "Raw");

  const result = await services.moveIceboxToBacklog([a1.id, a2.id]);
  assert.equal(result.ideas.length, 2);
  assert.ok(result.ideas.every((i) => i.state === "moved"));
  assert.equal(result.tasks.length, 2);
  for (const t of result.tasks) {
    assert.equal(t.state, "backlog");
    assert.equal(t.projectId, p.id);
  }

  // Tasks carry the spec snapshot; ideas flipped to `moved`.
  const t1 = (await q.select().from(tasks).where(eq(tasks.ideaId, a1.id)))[0]!;
  assert.equal(t1.spec.goal, "goal: First");
  assert.equal(t1.state, "backlog");
  assert.equal(t1.qaRounds, 0);
  const moved = (await q.select().from(ideas).where(eq(ideas.id, a1.id)))[0]!;
  assert.equal(moved.state, "moved");

  // Guards.
  await assert.rejects(
    services.moveIceboxToBacklog([raw.id]),
    (err: unknown) => err instanceof ServiceError && err.status === 409 && /not in the icebox/.test(err.message),
    "raw idea → 409",
  );
  await assert.rejects(
    services.moveIceboxToBacklog([a1.id]),
    (err: unknown) => err instanceof ServiceError && err.status === 409 && /moved/.test(err.message),
    "already moved → 409",
  );
  await assert.rejects(
    services.moveIceboxToBacklog([999]),
    (err: unknown) => err instanceof ServiceError && err.status === 404,
    "unknown idea → 404",
  );
  await assert.rejects(
    services.moveIceboxToBacklog([]),
    (err: unknown) => err instanceof ServiceError && err.status === 400,
    "empty list → 400",
  );
});

test("moveIceboxToBacklog: icebox item without spec → 409", async () => {
  const { services, q } = await setup();
  const p = await services.createProject({ name: "Beta" });
  const idea = await services.addIdea(p.id, "No spec");
  await q.update(ideas).set({ state: "icebox", spec: null }).where(eq(ideas.id, idea.id));
  await assert.rejects(
    services.moveIceboxToBacklog([idea.id]),
    (err: unknown) => err instanceof ServiceError && err.status === 409 && /no finalized spec/.test(err.message),
  );
});
