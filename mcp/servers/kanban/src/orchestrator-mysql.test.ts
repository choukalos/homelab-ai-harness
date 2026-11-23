/**
 * Driver-realism regression test (MySQL): the task state machine over a REAL
 * drizzle-orm/mysql2 instance.
 *
 * Why this file exists: every other orchestrator test runs over a real temp
 * SQLite db. That is exactly what hid the `.returning()` bug — drizzle
 * implements `.returning()` for Postgres/SQLite only; the MySQL update
 * builder has no such method (MySQL has no RETURNING clause), so on the
 * deployed MySQL driver (compose.mcp.yml: DB_DRIVER=mysql) EVERY task state
 * transition crashed with
 * `this.db.update(...).set(...).where(...).returning is not a function`.
 *
 * This test does NOT mock the query builder (mocking the builder is what
 * hid the bug). It builds a real drizzle-orm/mysql2 instance over a mocked
 * mysql2 POOL — the wire-protocol boundary: pool.query() resolves
 * OkPacket / rows exactly as mysql2 does. If transition()'s chain ever
 * references a method absent from the MySQL builder, this test fails with
 * the production error.
 *
 * DB_DRIVER must be "mysql" before db/tables.js loads (module-level driver
 * switch). node --test runs each test file in its own process, so setting
 * the env here and then dynamically importing the orchestrator is safe and
 * matches the deployed environment.
 */
process.env.DB_DRIVER = "mysql";

import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { drizzle } from "drizzle-orm/mysql2";
import type { Pool } from "mysql2/promise";
import type { KanbanConfig } from "./config.js";
import { mysqlSchema } from "./db/schema.js";
import type { AgentRuntime, TaskRunContext, TaskRunResult, TaskRunner } from "./agent/sessions.js";
import type { QaRunContext, QaVerdict } from "./agent/qa.js";
import type { DeployContext, DeployResult } from "./deploy/index.js";
import type { SummaryUpdateContext } from "./agent/summary.js";
import { ServiceError } from "./services/common.js";
import type {
  DeployRunnerLike,
  QaGateLike,
  SummaryUpdaterLike,
} from "./orchestrator.js";

// Value import of the class AFTER the env is set: orchestrator.js imports
// db/tables.js, whose module-level driver switch reads DB_DRIVER at load.
const { Orchestrator } = await import("./orchestrator.js");

type Row = Record<string, unknown>;

/**
 * Mocked mysql2 pool: in-memory tables + the wire-protocol result shapes
 * (UPDATE/INSERT -> [OkPacket, FieldPacket[]]; SELECT -> [rows, fields]).
 * Rows use DB column names (state_changed_at, idea_id, ...) exactly as
 * mysql2 returns them; drizzle's real result mappers do the rest.
 */
class MockMysqlPool {
  tasks = new Map<number, Row>();
  ideas = new Map<number, Row>();
  projects = new Map<number, Row>();
  /** task_events INSERTs (params arrays) — the audit trail. */
  events: unknown[][] = [];
  sqlLog: string[] = [];
  /**
   * When set, the next conditional UPDATE for this task simulates a
   * concurrent writer: the stored row's state is flipped before the
   * WHERE is evaluated, so affectedRows = 0 (the 409 path).
   */
  raceTaskId: number | null = null;

  async query(q: string | { sql: string }, params: unknown[] = []): Promise<unknown> {
    const s = typeof q === "string" ? q : q.sql;
    this.sqlLog.push(s);
    if (/^update `tasks`/i.test(s)) return this.updateTasks(s, params);
    if (/^update /i.test(s)) return this.updateOther(s, params);
    if (/^select/i.test(s)) return this.select(s, params);
    if (/^insert/i.test(s)) {
      if (/into `task_events`/i.test(s)) this.events.push(params);
      return [{ affectedRows: 1, insertId: this.events.length }, []];
    }
    throw new Error(`MockMysqlPool: unhandled SQL: ${s}`);
  }

  private updateTasks(s: string, params: unknown[]): [Row, unknown[]] {
    // Only the SET clause has plain `col` = ? pairs; the WHERE clause is
    // table-qualified (`tasks`.`id` = ?), so scope the match to `set … where`.
    const setClause = s.match(/^update `tasks` set (.+) where/i)?.[1];
    assert.ok(setClause, `MockMysqlPool: no SET clause in: ${s}`);
    const setCols = [...setClause.matchAll(/`(\w+)` = \?/g)].map((m) => m[1]!);
    const setVals = params.slice(0, setCols.length);
    const whereParams = params.slice(setCols.length);

    let taskId: number;
    let fromState: string | undefined;
    if (/`tasks`\.`id` = \? and `tasks`\.`state` = \?/i.test(s)) {
      [taskId, fromState] = whereParams as [number, string];
    } else if (/`tasks`\.`id` = \?/i.test(s)) {
      taskId = whereParams[0] as number;
    } else {
      throw new Error(`MockMysqlPool: unhandled UPDATE WHERE: ${s}`);
    }

    const row = this.tasks.get(taskId);
    if (this.raceTaskId === taskId && fromState !== undefined) {
      assert.ok(row, "MockMysqlPool: race task must exist");
      row.state = "running"; // concurrent writer wins the race
      this.raceTaskId = null;
    }
    const matched = row !== undefined && (fromState === undefined || row.state === fromState);
    if (matched) setCols.forEach((c, i) => (row[c] = setVals[i]));
    return [{ affectedRows: matched ? 1 : 0, insertId: 0 }, []];
  }

  /** Plain UPDATEs on other tables (e.g. the project state_summary write
   *  after the summary stage): apply the SET, no state condition. */
  private updateOther(s: string, params: unknown[]): [Row, unknown[]] {
    const m = s.match(/^update `(\w+)` set (.+) where `(\w+)`\.`(\w+)` = \?/i);
    assert.ok(m, `MockMysqlPool: no match for UPDATE: ${s}`);
    const table = m[1]!;
    const setClause = m[2]!;
    const setCols = [...setClause.matchAll(/`(\w+)` = \?/g)].map((x) => x[1]!);
    const setVals = params.slice(0, setCols.length);
    const id = params[setCols.length] as number;
    const store =
      table === "projects" ? this.projects : table === "ideas" ? this.ideas : this.tasks;
    const row = store.get(id);
    assert.ok(row, `MockMysqlPool: no row ${id} in ${table}`);
    setCols.forEach((c, i) => (row[c] = setVals[i]));
    return [{ affectedRows: 1, insertId: 0 }, []];
  }

  private select(s: string, params: unknown[]): [unknown[], unknown[]] {
    // The mysql2 session queries SELECTs with rowsAsArray: true — rows come
    // back POSITIONAL (values in select-list order); drizzle's mapResultRow
    // reads row[columnIndex]. So the mock must emit arrays, not objects.
    const list = s.match(/^select (.+?) from /i)?.[1] ?? "";
    const colNames = [...list.matchAll(/`(\w+)`/g)].map((m) => m[1]!);
    const toArray = (rows: Row[]): unknown[] => rows.map((r) => colNames.map((c) => (c in r ? r[c] : null)));
    if (/from `tasks`/i.test(s)) {
      if (/`tasks`\.`id` = \? limit \?/i.test(s)) {
        const row = this.tasks.get(params[0] as number);
        return [toArray(row ? [row] : []), []];
      }
      if (/`tasks`\.`state` = \? and `tasks`\.`paused` = \?/i.test(s)) {
        const [state, paused] = params as [string, boolean];
        return [toArray([...this.tasks.values()].filter((r) => r.state === state && r.paused === paused)), []];
      }
    }
    if (/from `ideas`/i.test(s) && /`ideas`\.`id` = \? limit \?/i.test(s)) {
      const row = this.ideas.get(params[0] as number);
      return [toArray(row ? [row] : []), []];
    }
    if (/from `projects`/i.test(s) && /`projects`\.`id` = \? limit \?/i.test(s)) {
      const row = this.projects.get(params[0] as number);
      return [toArray(row ? [row] : []), []];
    }
    throw new Error(`MockMysqlPool: unhandled SELECT: ${s}`);
  }

  /** isPool() check: "getConnection" in client. */
  async getConnection(): Promise<never> {
    throw new Error("MockMysqlPool: getConnection not needed");
  }
}

/** Records runs; every run completes with a commit. */
class MockTaskRunner implements TaskRunner {
  runs: TaskRunContext[] = [];
  aborted: number[] = [];
  run(ctx: TaskRunContext): Promise<TaskRunResult> {
    this.runs.push(ctx);
    return Promise.resolve({ summary: "done", lastCommit: "abc1234" });
  }
  abort(taskId: number): void {
    this.aborted.push(taskId);
  }
}

class PassQaGate implements QaGateLike {
  readonly maxRounds = 3;
  run(_ctx: QaRunContext): Promise<QaVerdict> {
    return Promise.resolve({ pass: true, feedback: "" });
  }
}

class OkDeployRunner implements DeployRunnerLike {
  ctxs: DeployContext[] = [];
  deploy(ctx: DeployContext): Promise<DeployResult> {
    this.ctxs.push(ctx);
    return Promise.resolve({ published: `pushed branch ${ctx.branch}`, target: "origin" });
  }
}

class FixedSummaryUpdater implements SummaryUpdaterLike {
  calls: SummaryUpdateContext[] = [];
  update(ctx: SummaryUpdateContext): Promise<string> {
    this.calls.push(ctx);
    return Promise.resolve("New project state summary.");
  }
}

function seed(pool: MockMysqlPool) {
  const now = Date.now();
  pool.projects.set(1, {
    id: 1,
    name: "Alpha",
    description: "d",
    goal: "g",
    repo_url: "https://github.com/x/y",
    default_branch: "main",
    blog_repo_url: null,
    blog_content_path: null,
    media_paths: null,
    constraints: null,
    architecture_notes: null,
    notes: null,
    state_summary: null,
    owner: "",
    created_at: now,
    updated_at: now,
  });
  pool.ideas.set(1, {
    id: 1,
    project_id: 1,
    text: "First task",
    state: "moved",
    spec: { goal: "g", steps: ["s1"], acceptance: ["a1"], kind: "code" },
    depends_on: [],
    owner: "chuck",
    created_at: now,
    updated_at: now,
  });
  pool.tasks.set(1, {
    id: 1,
    idea_id: 1,
    project_id: 1,
    spec: { goal: "g", steps: ["s1"], acceptance: ["a1"], kind: "code" },
    state: "backlog",
    state_changed_at: now,
    branch: null,
    last_commit: null,
    qa_rounds: 0,
    paused: false,
    workspace: null,
    resolution: null,
    owner: "chuck",
    created_at: now,
  });
}

function makeOrch(pool: MockMysqlPool) {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-orch-mysql-"));
  const cfg = {
    litellm: { baseUrl: "https://llm.example.com/v1", apiKey: "sk-test" },
    model: "test-model",
    modelCost: undefined,
    githubToken: undefined,
    userKeys: {},
    // The orchestrator never opens cfg.db (deps.db is injected) — plausible
    // shape only.
    db: {
      driver: "mysql",
      sqlitePath: undefined,
      mysql: { host: "127.0.0.1", user: "x", password: "y", database: "ai_kanban" },
    },
    workspace: { hostPath: dir, dir },
    harness: { repoUrl: "https://example.com/harness", skillsPath: "agent-skills" },
    thinking: { groom: "xhigh", task: "medium", qa: "xhigh", summary: "medium" },
    concurrentTasks: 1,
    workspaceCleanupDays: 7,
    server: { bindAddr: "127.0.0.1", port: 3000 },
  } as unknown as KanbanConfig;
  const db = drizzle(pool as unknown as Pool, { schema: mysqlSchema, mode: "default" });
  const runner = new MockTaskRunner();
  const qa = new PassQaGate();
  const deploy = new OkDeployRunner();
  const summary = new FixedSummaryUpdater();
  const orch = new Orchestrator({
    cfg,
    db: { driver: "mysql", db, close: async () => {} },
    agent: {} as unknown as AgentRuntime,
    tasks: runner,
    qa,
    deploy,
    summary,
    workspaceRoot: dir,
    noTimer: true,
  });
  return { orch, runner, qa, deploy, summary };
}

test("mysql: startTask drives the full lifecycle through transition() (no builder mock)", async () => {
  const pool = new MockMysqlPool();
  seed(pool);
  const { orch, runner, deploy, summary } = makeOrch(pool);

  // The MCP start_task entry point: backlog -> running (the transition that
  // crashed in production), then the pipeline: running -> deploy -> done.
  const task = await orch.startTask(1);
  assert.equal(task.state, "running");
  assert.equal(pool.tasks.get(1)!.state, "running");
  assert.equal(pool.tasks.get(1)!.branch, "task/1");

  // Let the in-flight pipeline settle (QA pass -> complete -> deploy -> done).
  await orch.settled();
  assert.equal(pool.tasks.get(1)!.state, "done");
  assert.equal(runner.runs.length, 1);
  assert.equal(deploy.ctxs.length, 1);
  assert.equal(summary.calls.length, 1);

  // The audit trail was written through the MySQL path (INSERT task_events).
  const stateEvents = pool.events.filter((p) => p.includes("state"));
  const transitions = stateEvents
    .map((p) => JSON.stringify(p))
    .filter((j) => j.includes("backlog") && j.includes("running"));
  assert.ok(transitions.length >= 1, "backlog -> running state event recorded");
});

test("mysql: transition 409 when the conditional UPDATE matches 0 rows (concurrent writer)", async () => {
  const pool = new MockMysqlPool();
  seed(pool);
  const { orch } = makeOrch(pool);
  // Simulate a concurrent writer flipping the task between the getTask
  // SELECT and the conditional UPDATE -> affectedRows = 0 -> 409.
  pool.raceTaskId = 1;

  await assert.rejects(
    () => orch.startTask(1),
    (err: unknown) =>
      err instanceof ServiceError &&
      err.status === 409 &&
      /is not backlog \(state: running\)/.test(err.message),
  );
  // The failed transition wrote no state event (the audit trail stays clean).
  assert.ok(!pool.events.some((p) => p.includes("state")), "no state event on 409");
});
