/**
 * DB client: driver selection (DB_DRIVER) + open + migrate.
 *
 * - sqlite (default): better-sqlite3, WAL, foreign keys on, file at
 *   /data/kanban.db (configurable via KanbanConfig.db.sqlitePath).
 * - mysql: mysql2 pool against the pre-created database; tables only.
 */
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import Database from "better-sqlite3";
import type { Database as SqliteDatabase } from "better-sqlite3";
import { drizzle as drizzleSqlite } from "drizzle-orm/better-sqlite3";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import { drizzle as drizzleMysql } from "drizzle-orm/mysql2";
import type { MySql2Database } from "drizzle-orm/mysql2";
import mysql from "mysql2/promise";
import type { KanbanConfig } from "../config.js";
import { migrateMysql, migrateSqlite } from "./migrate.js";
import { mysqlSchema, sqliteSchema } from "./schema.js";

/** drizzle() return types carry the raw driver as `$client`. */
export type SqliteDb = BetterSQLite3Database<typeof sqliteSchema> & {
  $client: SqliteDatabase;
};
export type MysqlDb = MySql2Database<typeof mysqlSchema> & { $client: mysql.Pool };

export interface SqliteDbHandle {
  driver: "sqlite";
  db: SqliteDb;
  close(): Promise<void>;
}

export interface MysqlDbHandle {
  driver: "mysql";
  db: MysqlDb;
  close(): Promise<void>;
}

export type DbHandle = SqliteDbHandle | MysqlDbHandle;

/** Open the configured driver (no migrations). */
export function openDb(cfg: KanbanConfig): DbHandle {
  if (cfg.db.driver === "sqlite") {
    const dir = dirname(cfg.db.sqlitePath);
    mkdirSync(dir, { recursive: true });
    const sqlite = new Database(cfg.db.sqlitePath);
    sqlite.pragma("journal_mode = WAL");
    sqlite.pragma("foreign_keys = ON");
    const db = drizzleSqlite(sqlite, { schema: sqliteSchema });
    return {
      driver: "sqlite",
      db,
      close: () => {
        sqlite.close();
        return Promise.resolve();
      },
    };
  }

  const m = cfg.db.mysql;
  if (!m) {
    throw new Error(
      "DB_DRIVER=mysql but MYSQL_HOST/MYSQL_USER/MYSQL_PASSWORD/MYSQL_DATABASE are not set",
    );
  }
  const pool = mysql.createPool({
    host: m.host,
    port: m.port,
    user: m.user,
    password: m.password,
    database: m.database,
    // Migration scripts contain multiple statements; the DB is dedicated.
    multipleStatements: true,
    waitForConnections: true,
    connectionLimit: 5,
  });
  const db = drizzleMysql(pool, { schema: mysqlSchema, mode: "default" });
  return { driver: "mysql", db, close: () => pool.end() };
}

/** Open the configured driver and apply all pending migrations. */
export async function initDb(cfg: KanbanConfig): Promise<DbHandle> {
  const handle = openDb(cfg);
  if (handle.driver === "sqlite") {
    migrateSqlite(handle.db.$client);
  } else {
    await migrateMysql(handle.db.$client);
  }
  return handle;
}
