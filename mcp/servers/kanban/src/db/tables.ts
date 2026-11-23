/**
 * Driver-conditional table objects for the service layer.
 *
 * The service layer queries through ONE set of table objects regardless of
 * driver (the MySQL drizzle instance is cast to `Db` at the boundary —
 * src/services/common.ts). Table names and column names are identical across
 * dialects, so the generated SQL is compatible — but drizzle maps result
 * rows through each table's COLUMN MAPPERS, and those are dialect-specific:
 *
 * - SQLite `text({ mode: "json" })` JSON.parse()s the driver value (strings
 *   from better-sqlite3).
 * - mysql2 returns native JSON columns **already parsed** (objects). Run
 *   through the SQLite mapper they get double-parsed: JSON.parse(String(obj))
 *   — e.g. depends_on = [] becomes JSON.parse("") → "Unexpected end of JSON
 *   input". Any full-row read of ideas/tasks (or projects.media_paths /
 *   task_events.payload) on MySQL would crash.
 *
 * So on DB_DRIVER=mysql the service layer must use the mysql-* table
 * objects, whose mysql-core json() columns pass driver values through
 * untouched. The driver is fixed for the process lifetime (env at boot), so
 * a module-level switch is safe.
 */
import {
  ideas as sqliteIdeas,
  kv as sqliteKv,
  projectFiles as sqliteProjectFiles,
  projects as sqliteProjects,
  taskEvents as sqliteTaskEvents,
  tasks as sqliteTasks,
  usage as sqliteUsage,
  mysqlIdeas,
  mysqlKv,
  mysqlProjectFiles,
  mysqlProjects,
  mysqlTaskEvents,
  mysqlTasks,
  mysqlUsage,
} from "./schema.js";

const useMysql = process.env.DB_DRIVER === "mysql";

/**
 * The service layer treats these as the SQLite table objects (identical
 * column sets by construction — see src/services/common.ts). The cast keeps
 * the query builder's types stable regardless of the active dialect.
 */
export const projects = (useMysql ? mysqlProjects : sqliteProjects) as typeof sqliteProjects;
export const ideas = (useMysql ? mysqlIdeas : sqliteIdeas) as typeof sqliteIdeas;
export const tasks = (useMysql ? mysqlTasks : sqliteTasks) as typeof sqliteTasks;
export const taskEvents = (useMysql ? mysqlTaskEvents : sqliteTaskEvents) as typeof sqliteTaskEvents;
export const usage = (useMysql ? mysqlUsage : sqliteUsage) as typeof sqliteUsage;
export const kv = (useMysql ? mysqlKv : sqliteKv) as typeof sqliteKv;
export const projectFiles = (useMysql ? mysqlProjectFiles : sqliteProjectFiles) as typeof sqliteProjectFiles;

/** True when the mysql-* table objects are active (DB_DRIVER=mysql). */
export const tablesUseMysql = useMysql;
