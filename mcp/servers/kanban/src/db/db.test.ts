import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import mysql from "mysql2/promise";
import { eq } from "drizzle-orm";
import { drizzle as drizzleMysql } from "drizzle-orm/mysql2";
import type { KanbanConfig } from "../config.js";
import type { SqliteDbHandle } from "./client.js";
import {
  appliedMysqlVersions,
  appliedSqliteVersions,
  initDb,
  migrateMysql,
  migrateSqlite,
  openDb,
  MIGRATIONS,
} from "./index.js";
import {
  ideas,
  kv,
  mysqlIdeas,
  mysqlKv,
  mysqlProjectFiles,
  mysqlProjects,
  mysqlSchema,
  mysqlTaskEvents,
  mysqlTasks,
  mysqlUsage,
  projectFiles,
  projects,
  taskEvents,
  tasks,
  usage,
} from "./schema.js";

const EXPECTED_TABLES = [
  "projects",
  "ideas",
  "tasks",
  "task_events",
  "usage",
  "kv",
  "project_files",
  "schema_migrations",
];

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function sqliteConfig(dbPath: string): KanbanConfig {
  return {
    litellm: { baseUrl: "https://llm.example.com/v1", apiKey: "sk-test" },
    model: "test-model",
    modelCost: undefined,
    githubToken: undefined,
    userKeys: {},
    db: { driver: "sqlite", sqlitePath: dbPath, mysql: undefined },
    workspace: { hostPath: "/tmp/workspace", dir: "/tmp/workspace" },
    harness: { repoUrl: "https://example.com/harness", skillsPath: "agent-skills" },
    thinking: { groom: "xhigh", task: "medium", qa: "xhigh", summary: "medium" },
    mediaConcurrentTasks: 1,
    nonMediaConcurrentTasks: 1,
    workspaceCleanupDays: 7,
    server: { bindAddr: "127.0.0.1", port: 3000 },
  };
}

function mysqlTestConfig(): KanbanConfig {
  return {
    ...sqliteConfig(path.join(tmpdir(), "unused.db")),
    db: {
      driver: "mysql",
      sqlitePath: path.join(tmpdir(), "unused.db"),
      mysql: {
        host: mysqlTestEnv.host,
        port: mysqlTestEnv.port,
        user: mysqlTestEnv.user,
        password: mysqlTestEnv.password,
        database: mysqlTestEnv.database,
      },
    },
  };
}

/**
 * MySQL test server (optional). Point it at a pre-created database, e.g.:
 *   docker run -d -e MYSQL_DATABASE=kanban_test -e MYSQL_USER=kanban \
 *     -e MYSQL_PASSWORD=kanban_pw -p 33060:3306 mysql:8.0
 *   AI_KANBAN_MYSQL_TEST_HOST=127.0.0.1 AI_KANBAN_MYSQL_TEST_PORT=33060 npm test
 */
const mysqlTestEnv = {
  host: process.env.AI_KANBAN_MYSQL_TEST_HOST ?? "",
  port: Number(process.env.AI_KANBAN_MYSQL_TEST_PORT ?? "3306"),
  user: process.env.AI_KANBAN_MYSQL_TEST_USER ?? "kanban",
  password: process.env.AI_KANBAN_MYSQL_TEST_PASSWORD ?? "kanban_pw",
  database: process.env.AI_KANBAN_MYSQL_TEST_DATABASE ?? "kanban_test",
};

async function openMysqlTestPool(): Promise<mysql.Pool> {
  return mysql.createPool({
    host: mysqlTestEnv.host,
    port: mysqlTestEnv.port,
    user: mysqlTestEnv.user,
    password: mysqlTestEnv.password,
    database: mysqlTestEnv.database,
    multipleStatements: true,
    connectionLimit: 2,
  });
}

async function withSqliteDb(
  fn: (handle: SqliteDbHandle) => Promise<void>,
): Promise<void> {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-db-"));
  try {
    const handle = await initDb(sqliteConfig(path.join(dir, "test.db")));
    if (handle.driver !== "sqlite") throw new Error("expected sqlite handle");
    try {
      await fn(handle);
    } finally {
      await handle.close();
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------------
// shared schema round-trip (ORM insert → read back → FK behavior)
// ---------------------------------------------------------------------------

interface RoundTripTables {
  projects: any;
  ideas: any;
  tasks: any;
  taskEvents: any;
  usage: any;
  kv: any;
  projectFiles: any;
}

async function runRoundTrip(db: any, t: RoundTripTables): Promise<void> {
  const now = Date.now();

  await db.insert(t.projects).values({
    name: "homelab",
    description: "Homelab infrastructure",
    goal: "Keep the homelab running",
    repoUrl: "https://github.com/choukalos/homelab",
    defaultBranch: "main",
    blogRepoUrl: "https://github.com/choukalos/blog",
    blogContentPath: "/content/posts",
    mediaPaths: ["/media/photos", "/media/videos"],
    constraints: "Never delete data",
    architectureNotes: "See docs/architecture.md",
    notes: "wip",
    stateSummary: "Initial state: nothing deployed",
    createdAt: now,
    updatedAt: now,
  });
  const [proj] = await db
    .select()
    .from(t.projects)
    .where(eq(t.projects.name, "homelab"));

  const spec = {
    goal: "Add a nightly backup job",
    steps: ["Write the script", "Add a cron entry"],
    acceptance: ["A restore succeeds"],
    kind: "code" as const,
    publish_targets: ["github"],
    notes: "use restic",
  };

  await db.insert(t.ideas).values({
    projectId: proj.id,
    text: "Add a nightly backup job",
    state: "icebox",
    spec,
    dependsOn: [],
    createdAt: now,
    updatedAt: now,
  });
  const [idea] = await db
    .select()
    .from(t.ideas)
    .where(eq(t.ideas.projectId, proj.id));

  await db.insert(t.tasks).values({
    ideaId: idea.id,
    projectId: proj.id,
    spec,
    state: "running",
    stateChangedAt: now,
    branch: "task/t1",
    lastCommit: "abc123",
    qaRounds: 1,
    paused: true,
    workspace: "/workspace/task-t1",
    resolution: "Retry with the fix applied",
    createdAt: now,
  });
  const [task] = await db
    .select()
    .from(t.tasks)
    .where(eq(t.tasks.ideaId, idea.id));

  await db.insert(t.taskEvents).values([
    { taskId: task.id, ts: now, type: "log", payload: { line: "cloning repo" } },
    { taskId: task.id, ts: now + 1, type: "heartbeat", payload: null },
  ]);

  await db.insert(t.usage).values([
    {
      taskId: task.id,
      projectId: proj.id,
      ts: now,
      role: "task",
      model: "matrix-coder",
      thinking: "medium",
      tokensIn: 1000,
      tokensOut: 500,
      cost: 0.0125,
    },
    {
      taskId: null,
      projectId: proj.id,
      ts: now,
      role: "groom",
      model: "matrix-coder",
      thinking: "xhigh",
      tokensIn: 2000,
      tokensOut: 800,
      cost: 0.02,
    },
  ]);

  await db
    .insert(t.kv)
    .values({ key: "orchestrator.state", value: JSON.stringify({ slots: 1 }) });

  await db.insert(t.projectFiles).values({
    projectId: proj.id,
    path: "scripts/frozen.py",
    size: 1234,
    stagedBy: "chuck",
    stagedAt: now,
  });

  // --- read back -----------------------------------------------------------

  const [projBack] = await db
    .select()
    .from(t.projects)
    .where(eq(t.projects.id, proj.id));
  assert.equal(projBack.name, "homelab");
  assert.deepEqual(projBack.mediaPaths, ["/media/photos", "/media/videos"]);
  assert.equal(projBack.stateSummary, "Initial state: nothing deployed");
  assert.equal(projBack.createdAt, now);

  const [ideaBack] = await db
    .select()
    .from(t.ideas)
    .where(eq(t.ideas.id, idea.id));
  assert.deepEqual(ideaBack.spec, spec);
  assert.deepEqual(ideaBack.dependsOn, []);
  assert.equal(ideaBack.state, "icebox");

  const [taskBack] = await db
    .select()
    .from(t.tasks)
    .where(eq(t.tasks.id, task.id));
  assert.deepEqual(taskBack.spec, spec);
  assert.equal(taskBack.state, "running");
  assert.equal(taskBack.paused, true);
  assert.equal(taskBack.qaRounds, 1);
  assert.equal(taskBack.lastCommit, "abc123");
  assert.equal(taskBack.resolution, "Retry with the fix applied");

  const events = await db
    .select()
    .from(t.taskEvents)
    .where(eq(t.taskEvents.taskId, task.id));
  assert.equal(events.length, 2);
  assert.deepEqual(events[0].payload, { line: "cloning repo" });
  assert.equal(events[1].payload, null);

  const usageRows = await db
    .select()
    .from(t.usage)
    .where(eq(t.usage.projectId, proj.id));
  assert.equal(usageRows.length, 2);
  const taskUsage = usageRows.find((u: any) => u.taskId === task.id);
  assert.equal(taskUsage.tokensIn, 1000);
  assert.equal(taskUsage.tokensOut, 500);
  assert.equal(taskUsage.cost, 0.0125);
  const groomUsage = usageRows.find((u: any) => u.taskId === null);
  assert.equal(groomUsage.role, "groom");

  const [kvBack] = await db
    .select()
    .from(t.kv)
    .where(eq(t.kv.key, "orchestrator.state"));
  assert.deepEqual(JSON.parse(kvBack.value), { slots: 1 });

  const fileRows = await db
    .select()
    .from(t.projectFiles)
    .where(eq(t.projectFiles.projectId, proj.id));
  assert.equal(fileRows.length, 1);
  assert.equal(fileRows[0]!.path, "scripts/frozen.py");
  assert.equal(fileRows[0]!.size, 1234);
  assert.equal(fileRows[0]!.stagedBy, "chuck");
  assert.equal(fileRows[0]!.stagedAt, now);

  // --- FK behavior: deleting the task cascades events, nulls usage ---------

  await db.delete(t.tasks).where(eq(t.tasks.id, task.id));
  const eventsAfter = await db
    .select()
    .from(t.taskEvents)
    .where(eq(t.taskEvents.taskId, task.id));
  assert.equal(eventsAfter.length, 0);
  const usageAfter = await db
    .select()
    .from(t.usage)
    .where(eq(t.usage.projectId, proj.id));
  assert.equal(usageAfter.length, 2);
  assert.ok(usageAfter.every((u: any) => u.taskId === null));

  // Deleting the project cascades the staged-file audit rows too.
  await db.delete(t.projects).where(eq(t.projects.id, proj.id));
  const fileRowsAfter = await db.select().from(t.projectFiles).limit(10);
  assert.equal(fileRowsAfter.length, 0, "project_files cascade on project delete");
}

// ---------------------------------------------------------------------------
// sqlite (default driver) — always runs
// ---------------------------------------------------------------------------

test("sqlite: initDb runs migrations and creates all tables", () =>
  withSqliteDb(async (handle) => {
    const raw = handle.db.$client;
    const rows = raw
      .prepare("SELECT name FROM sqlite_master WHERE type = 'table'")
      .all() as Array<{ name: string }>;
    const tables = new Set(rows.map((r) => r.name));
    for (const name of EXPECTED_TABLES) {
      assert.ok(tables.has(name), `missing table ${name}`);
    }
    assert.deepEqual(appliedSqliteVersions(raw), [
      "0001_init",
      "0002_owner",
      "0003_usage_owner",
      "0004_project_files",
    ]);
    // 0002_owner: owner columns on projects / ideas / tasks.
    for (const table of ["projects", "ideas", "tasks"]) {
      const cols = raw
        .prepare(`PRAGMA table_info(${table})`)
        .all() as Array<{ name: string }>;
      assert.ok(cols.some((c) => c.name === "owner"), `${table}.owner column exists`);
    }
    // 0003_usage_owner: owner column on usage (per-user spend attribution).
    const usageCols = raw.prepare("PRAGMA table_info(usage)").all() as Array<{ name: string }>;
    assert.ok(usageCols.some((c) => c.name === "owner"), "usage.owner column exists");
    // 0004_project_files: audit table for the durable project file store.
    const fileCols = raw.prepare("PRAGMA table_info(project_files)").all() as Array<{ name: string }>;
    for (const col of ["id", "project_id", "path", "size", "staged_by", "staged_at"]) {
      assert.ok(fileCols.some((c) => c.name === col), `project_files.${col} column exists`);
    }
  }));

test("sqlite: migrations are idempotent and preserve data", () =>
  withSqliteDb(async (handle) => {
    await handle.db.insert(kv).values({ key: "x", value: "y" });
    // second run on the same DB: no-op, no error
    migrateSqlite(handle.db.$client);
    assert.deepEqual(appliedSqliteVersions(handle.db.$client), [
      "0001_init",
      "0002_owner",
      "0003_usage_owner",
      "0004_project_files",
    ]);
    const rows = await handle.db.select().from(kv).where(eq(kv.key, "x"));
    assert.equal(rows.length, 1);
    assert.equal(rows[0]!.value, "y");
  }));

test("sqlite: WAL journal mode enabled", () =>
  withSqliteDb(async (handle) => {
    const mode = handle.db.$client.pragma("journal_mode", { simple: true });
    assert.equal(mode, "wal");
  }));

test("sqlite: schema round-trip (JSON columns, defaults, FK behavior)", () =>
  withSqliteDb(async (handle) => {
    await runRoundTrip(handle.db, {
      projects,
      ideas,
      tasks,
      taskEvents,
      usage,
      kv,
      projectFiles,
    });
  }));

test("sqlite: foreign keys are enforced", () =>
  withSqliteDb(async (handle) => {
    await assert.rejects(
      handle.db.insert(ideas).values({
        projectId: 9999,
        text: "orphan idea",
        createdAt: 1,
        updatedAt: 1,
      }),
      /FOREIGN KEY/,
    );
  }));

test("driver selection via DB_DRIVER config", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-db-"));
  try {
    const s = openDb(sqliteConfig(path.join(dir, "sel.db")));
    assert.equal(s.driver, "sqlite");
    await s.close();

    const m = openDb(mysqlTestConfig());
    assert.equal(m.driver, "mysql");
    await m.close(); // pool is lazy; no server needed

    assert.throws(
      () =>
        openDb({
          ...mysqlTestConfig(),
          db: { driver: "mysql", sqlitePath: "x", mysql: undefined },
        }),
      /MYSQL_/,
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------------------
// mysql — runs against a test container when available, else skipped
// ---------------------------------------------------------------------------

test("mysql: migrations + schema round-trip", { concurrency: 1 }, async (t) => {
  if (!mysqlTestEnv.host) {
    t.skip(
      "no MySQL test server — set AI_KANBAN_MYSQL_TEST_HOST/PORT/USER/PASSWORD/DATABASE " +
        "(e.g. docker run -d -e MYSQL_DATABASE=kanban_test -e MYSQL_USER=kanban " +
        "-e MYSQL_PASSWORD=kanban_pw -p 33060:3306 mysql:8.0, then " +
        "AI_KANBAN_MYSQL_TEST_HOST=127.0.0.1 AI_KANBAN_MYSQL_TEST_PORT=33060 npm test)",
    );
    return;
  }

  let pool: mysql.Pool;
  const dropAppTables = async () => {
    await pool.query("SET FOREIGN_KEY_CHECKS = 0");
    await pool.query(
      "DROP TABLE IF EXISTS `usage`, `task_events`, `tasks`, `ideas`, `projects`, `kv`, `project_files`, `schema_migrations`",
    );
    await pool.query("SET FOREIGN_KEY_CHECKS = 1");
  };

  await t.test("connect to the pre-created database", async () => {
    pool = await openMysqlTestPool();
    const [rows] = await pool.query("SELECT 1 AS ok");
    assert.equal((rows as Array<{ ok: number }>)[0]!.ok, 1);
  });

  await t.test("migrations create all tables (tables only)", async () => {
    await dropAppTables();
    await migrateMysql(pool);
    const [rows] = await pool.query(
      "SELECT table_name AS name FROM information_schema.tables WHERE table_schema = DATABASE()",
    );
    const tables = new Set((rows as Array<{ name: string }>).map((r) => r.name));
    for (const name of EXPECTED_TABLES) {
      assert.ok(tables.has(name), `missing table ${name}`);
    }
  });

  await t.test("migrations are idempotent and preserve data", async () => {
    await pool.query("INSERT INTO `kv` (`key`, `value`) VALUES ('x', 'y')");
    await migrateMysql(pool); // second run: no-op
    assert.deepEqual(await appliedMysqlVersions(pool), [
      "0001_init",
      "0002_owner",
      "0003_usage_owner",
      "0004_project_files",
    ]);
    const [usageCols] = await pool.query("SHOW COLUMNS FROM `usage`");
    assert.ok(
      (usageCols as Array<{ Field: string }>).some((c) => c.Field === "owner"),
      "usage.owner column exists",
    );
    const [rows] = await pool.query("SELECT value FROM `kv` WHERE `key` = 'x'");
    assert.equal((rows as Array<{ value: string }>).length, 1);
    await pool.query("DELETE FROM `kv`");
  });

  await t.test("schema round-trip (JSON columns, defaults, FK behavior)", async () => {
    await dropAppTables();
    await migrateMysql(pool);
    const db = drizzleMysql(pool, { schema: mysqlSchema, mode: "default" });
    await runRoundTrip(db, {
      projects: mysqlProjects,
      ideas: mysqlIdeas,
      tasks: mysqlTasks,
      taskEvents: mysqlTaskEvents,
      usage: mysqlUsage,
      kv: mysqlKv,
      projectFiles: mysqlProjectFiles,
    });
  });

  await t.test("migrations never create the database", async () => {
    for (const m of MIGRATIONS) {
      assert.ok(
        !/CREATE\s+DATABASE/i.test(m.mysql),
        "mysql migrations must be tables-only (DB is pre-created)",
      );
    }
  });

  await t.test("teardown", async () => {
    await pool.end();
  });
});
