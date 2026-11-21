/**
 * Usage reports tests (Slice 4, requirements §11): rolling-12-month spend
 * buckets + total, per-project completed count + $ spend, per-task usage
 * table + filters, and completed-item pagination — over a real temp
 * sqlite db (the default driver; the MySQL path shares this code).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import type { KanbanConfig } from "../config.js";
import { initDb } from "../db/index.js";
import { ideas, projects, tasks, usage } from "../db/schema.js";
import type { Db } from "./common.js";
import {
  ROLLING_MONTHS,
  monthWindow,
  projectCompleted,
  projectStats,
  spendByMonth,
  spendByOwner,
  taskUsageTable,
} from "./reports.js";

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
    server: { bindAddr: "127.0.0.1", port: 3000 },
  };
}

async function setup(): Promise<{ db: Db; q: BetterSQLite3Database<any> }> {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-reports-"));
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  return { db: db.db as unknown as Db, q: db.db as unknown as BetterSQLite3Database<any> };
}

/** drizzle's returning() resolves to `Row[]`; take the single row. */
function first<T>(rows: T[], label: string): T {
  const row = rows[0];
  assert.ok(row, label);
  return row;
}

/** Float-tolerant equality (usage costs are summed as floats). */
function closeTo(actual: number, expected: number, label: string): void {
  assert.ok(Math.abs(actual - expected) < 1e-9, `${label}: ${actual} !== ${expected}`);
}

interface Fixture {
  alpha: number;
  beta: number;
  /** Alpha: done task (in window) + running task. */
  alphaDone: number;
  alphaRunning: number;
  /** Beta: done task (in window). */
  betaDone: number;
  /** Alpha: done task completed OUTSIDE the rolling window. */
  alphaOldDone: number;
}

/** Seed two projects, tasks in various states, and usage rows in the
 * current month, the previous month, and outside the window. */
async function seed(q: BetterSQLite3Database<any>, now: number): Promise<Fixture> {
  const alpha = first(
    await q.insert(projects).values({ name: "Alpha", createdAt: now, updatedAt: now }).returning(),
    "alpha",
  );
  const beta = first(
    await q.insert(projects).values({ name: "Beta", createdAt: now, updatedAt: now }).returning(),
    "beta",
  );
  const mkIdea = async (projectId: number, text: string, state = "moved") =>
    first(
      await q.insert(ideas).values({ projectId, text, state, createdAt: now, updatedAt: now }).returning(),
      `idea ${text}`,
    );
  const mkTask = async (ideaId: number, projectId: number, state: string, changedAt: number) =>
    first(
      await q
        .insert(tasks)
        .values({
          ideaId,
          projectId,
          spec: { goal: "g", steps: [], acceptance: [], kind: "code" },
          state,
          stateChangedAt: changedAt,
          createdAt: now,
        })
        .returning(),
      `task ${state}`,
    );

  const i1 = await mkIdea(alpha.id, "Alpha done item", "moved");
  const i2 = await mkIdea(alpha.id, "Alpha running item", "moved");
  const i3 = await mkIdea(beta.id, "Beta done item", "moved");
  const i4 = await mkIdea(alpha.id, "Alpha old done item", "moved");

  const months = monthWindow(now);
  const cur = months[months.length - 1]!;
  const prev = months[months.length - 2]!;

  const alphaDone = await mkTask(i1.id, alpha.id, "done", now - 10 * 86400_000);
  const alphaRunning = await mkTask(i2.id, alpha.id, "running", now - 3600_000);
  const betaDone = await mkTask(i3.id, beta.id, "done", now - 50 * 86400_000);
  const alphaOldDone = await mkTask(i4.id, alpha.id, "done", months[0]!.start - 86400_000);

  await q.insert(usage).values([
    // Alpha done task: task + qa usage, current month (owner chuck).
    { projectId: alpha.id, taskId: alphaDone.id, ts: cur.start + 1000, role: "task", model: "m", thinking: "medium", tokensIn: 1000, tokensOut: 500, cost: 2.0, owner: "chuck" },
    { projectId: alpha.id, taskId: alphaDone.id, ts: cur.start + 2000, role: "qa", model: "m", thinking: "xhigh", tokensIn: 100, tokensOut: 50, cost: 0.5, owner: "chuck" },
    // Alpha running task: task usage, previous month (owner dylan).
    { projectId: alpha.id, taskId: alphaRunning.id, ts: prev.start + 1000, role: "task", model: "m", thinking: "medium", tokensIn: 2000, tokensOut: 800, cost: 4.0, owner: "dylan" },
    // Beta done task: task usage, current month (unattributed).
    { projectId: beta.id, taskId: betaDone.id, ts: cur.start + 3000, role: "task", model: "m", thinking: "medium", tokensIn: 300, tokensOut: 100, cost: 1.25, owner: "" },
    // Out of window: the old done task (13 months ago).
    { projectId: alpha.id, taskId: alphaOldDone.id, ts: months[0]!.start - 1000, role: "task", model: "m", thinking: "medium", tokensIn: 999, tokensOut: 999, cost: 9.99, owner: "chuck" },
    // Grooming/summary rows carry no task (must not appear in the task table).
    { projectId: alpha.id, taskId: null, ts: cur.start + 4000, role: "groom", model: "m", thinking: "xhigh", tokensIn: 50, tokensOut: 20, cost: 0.1, owner: "dylan" },
    { projectId: beta.id, taskId: null, ts: cur.start + 5000, role: "summary", model: "m", thinking: "medium", tokensIn: 10, tokensOut: 5, cost: 0.05, owner: "" },
  ]);

  return { alpha: alpha.id, beta: beta.id, alphaDone: alphaDone.id, alphaRunning: alphaRunning.id, betaDone: betaDone.id, alphaOldDone: alphaOldDone.id };
}

test("monthWindow: 12 buckets, oldest first, covering the current month", () => {
  const now = Date.now();
  const w = monthWindow(now);
  assert.equal(w.length, ROLLING_MONTHS);
  for (let i = 1; i < w.length; i++) {
    assert.equal(w[i]!.start, w[i - 1]!.end, "contiguous months");
    assert.ok(w[i]!.start > w[i - 1]!.start, "ascending");
  }
  const last = w[w.length - 1]!;
  assert.ok(last.start <= now && now < last.end, "current month contains now");
  const first = w[0]!;
  const d = new Date(now);
  assert.equal(first.start, new Date(d.getFullYear(), d.getMonth() - 11, 1).getTime(), "starts 11 months back");
  assert.match(first.key, /^\d{4}-\d{2}$/);
  assert.equal(first.short.length, 3, "short label");
});

test("spendByMonth: buckets by month, excludes out-of-window rows, total sums in-window", async () => {
  const { db, q } = await setup();
  const now = Date.now();
  const f = await seed(q, now);
  void f;

  const report = await spendByMonth(db, now);
  assert.equal(report.months.length, 12);
  const cur = report.months[report.months.length - 1]!;
  const prev = report.months[report.months.length - 2]!;
  // Current month: alpha done (2.0 + 0.5) + beta done (1.25) + groom (0.1) + summary (0.05).
  closeTo(cur.spend, 3.9, "current month spend");
  // Previous month: alpha running (4.0).
  closeTo(prev.spend, 4.0, "previous month spend");
  // Everything else is zero; the 9.99 out-of-window row is excluded.
  closeTo(report.total, 7.9, "total");
  for (const m of report.months) {
    if (m !== cur && m !== prev) assert.equal(m.spend, 0, `month ${m.key} empty`);
  }
});

test("spendByOwner: per-user × per-month, window-only, unattributed last", async () => {
  const { db, q } = await setup();
  const now = Date.now();
  void await seed(q, now);

  const rows = await spendByOwner(db, now);
  const months = monthWindow(now);
  const cur = months[months.length - 1]!;
  const prev = months[months.length - 2]!;
  const byName = new Map(rows.map((r) => [r.owner, r]));

  // Order: by total desc; the unattributed ('') row is last regardless.
  assert.deepEqual(rows.map((r) => r.owner), ["dylan", "chuck", ""]);

  // chuck: alpha done task (2.0) + qa (0.5), current month; the 9.99
  // out-of-window row is excluded.
  const chuck = byName.get("chuck")!;
  closeTo(chuck.total, 2.5, "chuck total");
  closeTo(chuck.byMonth[cur.key] ?? 0, 2.5, "chuck current month");
  assert.equal(chuck.byMonth[prev.key], undefined, "chuck has no previous-month spend");

  // dylan: alpha running task (4.0) previous month + groom (0.1) current.
  const dylan = byName.get("dylan")!;
  closeTo(dylan.total, 4.1, "dylan total");
  closeTo(dylan.byMonth[cur.key] ?? 0, 0.1, "dylan current month");
  closeTo(dylan.byMonth[prev.key] ?? 0, 4.0, "dylan previous month");

  // unattributed: beta done (1.25) + summary (0.05), current month.
  const unattr = byName.get("")!;
  closeTo(unattr.total, 1.3, "unattributed total");
  closeTo(unattr.byMonth[cur.key] ?? 0, 1.3, "unattributed current month");

  // All owners' totals sum to the window total (all keys, no filtering).
  closeTo(rows.reduce((s, r) => s + r.total, 0), 7.9, "owner totals sum to window total");
});

test("projectStats: completed counts (in-window done only) + $ spend per project", async () => {
  const { db, q } = await setup();
  const now = Date.now();
  const f = await seed(q, now);

  const rows = await projectStats(db, now);
  assert.equal(rows.length, 2);
  const alpha = rows.find((r) => r.id === f.alpha)!;
  const beta = rows.find((r) => r.id === f.beta)!;
  // Alpha: 1 in-window done (the 13-months-ago done is excluded); spend = 2.0 + 0.5 + 4.0 + 0.1 (groom).
  assert.equal(alpha.completed, 1);
  closeTo(alpha.spend, 6.6, "alpha spend");
  // Beta: 1 done; spend = 1.25 + 0.05 (summary).
  assert.equal(beta.completed, 1);
  closeTo(beta.spend, 1.3, "beta spend");
  // Sorted by spend desc.
  assert.equal(rows[0]!.id, f.alpha);
});

test("taskUsageTable: per-task totals, by-role breakdown, and filters", async () => {
  const { db, q } = await setup();
  const now = Date.now();
  const f = await seed(q, now);

  const all = await taskUsageTable(db);
  assert.equal(all.length, 4, "four tasks with usage (groom/summary rows excluded)");
  // Sorted by cost desc: 9.99 (old done), 4.0 (running), 2.5 (done), 1.25 (beta).
  assert.deepEqual(
    all.map((t) => t.taskId),
    [f.alphaOldDone, f.alphaRunning, f.alphaDone, f.betaDone],
    "sorted by cost desc",
  );
  const done = all.find((t) => t.taskId === f.alphaDone)!;
  assert.equal(done.tokensIn, 1100);
  assert.equal(done.tokensOut, 550);
  assert.equal(done.cost, 2.5);
  assert.deepEqual(done.byRole, { task: 2.0, qa: 0.5 });
  assert.equal(done.project, "Alpha");
  assert.equal(done.title, "Alpha done item");
  assert.equal(done.state, "done");

  // Project filter.
  const onlyAlpha = await taskUsageTable(db, { projectId: f.alpha });
  assert.ok(onlyAlpha.every((t) => t.projectId === f.alpha));
  assert.equal(onlyAlpha.length, 3);

  // State filter.
  const running = await taskUsageTable(db, { state: "running" });
  assert.equal(running.length, 1);
  assert.equal(running[0]!.taskId, f.alphaRunning);

  // Role filter: only qa usage counts; tasks without qa usage disappear.
  const qa = await taskUsageTable(db, { role: "qa" });
  assert.equal(qa.length, 1);
  assert.equal(qa[0]!.taskId, f.alphaDone);
  assert.equal(qa[0]!.cost, 0.5);
  assert.deepEqual(qa[0]!.byRole, { qa: 0.5 });

  // Text filter (case-insensitive substring on the task title).
  const search = await taskUsageTable(db, { q: "beta DONE" });
  assert.equal(search.length, 1);
  assert.equal(search[0]!.taskId, f.betaDone);
  const noMatch = await taskUsageTable(db, { q: "zzz" });
  assert.equal(noMatch.length, 0);
});

test("projectCompleted: newest-first, paginated, with per-task cost", async () => {
  const { db, q } = await setup();
  const now = Date.now();
  const f = await seed(q, now);

  // Add ten more done tasks to Alpha for pagination (Alpha then has 12
  // done: the fixture done task + the out-of-window done + 10 bulk).
  for (let i = 0; i < 10; i++) {
    const idea = first(
      await q
        .insert(ideas)
        .values({ projectId: f.alpha, text: `Bulk item ${i}`, state: "moved", createdAt: now, updatedAt: now })
        .returning(),
      "bulk idea",
    );
    await q
      .insert(tasks)
      .values({
        ideaId: idea.id,
        projectId: f.alpha,
        spec: { goal: "g", steps: [], acceptance: [], kind: "code" },
        state: "done",
        stateChangedAt: now - (100 + i) * 3600_000, // older than the fixture done task
        createdAt: now,
      });
  }

  const page1 = await projectCompleted(db, f.alpha, 1, 10);
  assert.equal(page1.total, 12);
  assert.equal(page1.pageCount, 2);
  assert.equal(page1.items.length, 10);
  // Newest first: the bulk items (now - ~100h) are newer than the fixture
  // done task (now - 10 days) → bulk item 0 (newest) first.
  assert.equal(page1.items[0]!.title, "Bulk item 0");
  assert.equal(page1.items[0]!.cost, 0, "no usage recorded for bulk items");

  const page2 = await projectCompleted(db, f.alpha, 2, 10);
  assert.equal(page2.items.length, 2);
  assert.equal(page2.items[0]!.taskId, f.alphaDone, "fixture done task first");
  assert.equal(page2.items[0]!.title, "Alpha done item");
  closeTo(page2.items[0]!.cost, 2.5, "done task cost");
  assert.equal(page2.items[1]!.taskId, f.alphaOldDone, "out-of-window done task last");
  closeTo(page2.items[1]!.cost, 9.99, "old done task cost");

  // Page past the end clamps to the last page; project without done
  // tasks → empty page.
  const clamped = await projectCompleted(db, f.alpha, 99, 10);
  assert.equal(clamped.page, 2);
  const gamma = first(
    await q.insert(projects).values({ name: "Gamma", createdAt: now, updatedAt: now }).returning(),
    "gamma",
  );
  const empty = await projectCompleted(db, gamma.id, 1, 10);
  assert.equal(empty.total, 0);
  assert.equal(empty.items.length, 0);
  assert.equal(empty.pageCount, 1);
});
