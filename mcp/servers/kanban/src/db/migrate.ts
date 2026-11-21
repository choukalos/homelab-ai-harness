/**
 * Idempotent migration runner for both drivers.
 *
 * Bookkeeping lives in a `schema_migrations` table (version + applied_at).
 * Each pending migration runs in a single transaction; already-applied
 * versions are skipped, so the runner is safe to invoke on every startup.
 */
import type { Database } from "better-sqlite3";
import type { Pool } from "mysql2/promise";
import { MIGRATIONS } from "./migrations.js";

const SCHEMA_MIGRATIONS_SQLITE = `
CREATE TABLE IF NOT EXISTS "schema_migrations" (
  "version" TEXT PRIMARY KEY,
  "applied_at" INTEGER NOT NULL
);
`;

const SCHEMA_MIGRATIONS_MYSQL = `
CREATE TABLE IF NOT EXISTS \`schema_migrations\` (
  \`version\` VARCHAR(64) NOT NULL,
  \`applied_at\` BIGINT NOT NULL,
  PRIMARY KEY (\`version\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
`;

/** Apply all pending migrations to a better-sqlite3 database (synchronous). */
export function migrateSqlite(sqlite: Database): void {
  sqlite.exec(SCHEMA_MIGRATIONS_SQLITE);
  const rows = sqlite
    .prepare("SELECT version FROM schema_migrations")
    .all() as Array<{ version: string }>;
  const applied = new Set(rows.map((r) => r.version));

  const record = sqlite.prepare(
    'INSERT INTO "schema_migrations" ("version", "applied_at") VALUES (?, ?)',
  );

  for (const m of MIGRATIONS) {
    if (applied.has(m.version)) continue;
    sqlite.exec("BEGIN IMMEDIATE");
    try {
      sqlite.exec(m.sqlite);
      record.run(m.version, Date.now());
      sqlite.exec("COMMIT");
    } catch (err) {
      sqlite.exec("ROLLBACK");
      throw new Error(
        `sqlite migration ${m.version} failed: ${(err as Error).message}`,
      );
    }
  }
}

/**
 * Apply all pending migrations via a mysql2 pool. The pool must be created
 * with `multipleStatements: true` (migration scripts contain several
 * statements). Tables only — the database itself is pre-created.
 */
export async function migrateMysql(pool: Pool): Promise<void> {
  await pool.query(SCHEMA_MIGRATIONS_MYSQL);
  const [rows] = await pool.query("SELECT version FROM schema_migrations");
  const applied = new Set(
    (rows as Array<{ version: string }>).map((r) => r.version),
  );

  for (const m of MIGRATIONS) {
    if (applied.has(m.version)) continue;
    const conn = await pool.getConnection();
    try {
      await conn.beginTransaction();
      await conn.query(m.mysql);
      await conn.query(
        "INSERT INTO `schema_migrations` (`version`, `applied_at`) VALUES (?, ?)",
        [m.version, Date.now()],
      );
      await conn.commit();
    } catch (err) {
      await conn.rollback().catch(() => {});
      throw new Error(
        `mysql migration ${m.version} failed: ${(err as Error).message}`,
      );
    } finally {
      conn.release();
    }
  }
}

/** Versions currently recorded in schema_migrations (diagnostics/tests). */
export function appliedSqliteVersions(sqlite: Database): string[] {
  return (
    sqlite
      .prepare("SELECT version FROM schema_migrations ORDER BY version")
      .all() as Array<{ version: string }>
  ).map((r) => r.version);
}

export async function appliedMysqlVersions(pool: Pool): Promise<string[]> {
  const [rows] = await pool.query(
    "SELECT version FROM schema_migrations ORDER BY version",
  );
  return (rows as Array<{ version: string }>).map((r) => r.version);
}
