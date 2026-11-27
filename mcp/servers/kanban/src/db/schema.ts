/**
 * Drizzle schema for both DB drivers (PLAN.md §2).
 *
 * Column sets are identical across drivers; only the dialect types differ.
 * Timestamps are INTEGER epoch milliseconds (BIGINT on MySQL). JSON columns
 * (spec / depends_on / media_paths / payload) are native JSON on MySQL and
 * JSON-as-TEXT on SQLite — Drizzle (de)serializes them in both cases.
 */
import {
  index,
  integer,
  real,
  sqliteTable,
  text,
  uniqueIndex,
} from "drizzle-orm/sqlite-core";
import {
  bigint,
  boolean,
  double,
  index as mysqlIndex,
  int,
  json as mysqlJson,
  mediumtext,
  mysqlTable,
  text as mysqlText,
  uniqueIndex as mysqlUniqueIndex,
  varchar,
} from "drizzle-orm/mysql-core";

// ---------------------------------------------------------------------------
// Shared domain types
// ---------------------------------------------------------------------------

export const IDEA_STATES = ["idea", "grooming", "icebox", "moved", "discarded"] as const;
export type IdeaState = (typeof IDEA_STATES)[number];

export const TASK_STATES = ["backlog", "running", "deploy", "done", "needs_attention"] as const;
export type TaskState = (typeof TASK_STATES)[number];

export const TASK_EVENT_TYPES = ["log", "heartbeat", "state", "qa", "usage", "deploy", "resolve", "merge"] as const;
export type TaskEventType = (typeof TASK_EVENT_TYPES)[number];

export const USAGE_ROLES = ["groom", "task", "qa", "summary", "resolve"] as const;
export type UsageRole = (typeof USAGE_ROLES)[number];

export const TASK_KINDS = ["code", "blog", "media", "other"] as const;
export type TaskKind = (typeof TASK_KINDS)[number];

/** Idea spec — populated on Accept (PLAN.md §2). */
export interface IdeaSpec {
  goal: string;
  steps: string[];
  acceptance: string[];
  kind: TaskKind;
  publish_targets?: string[];
  notes?: string;
}

/** Free-form event payload (log lines, QA feedback, deploy results, ...). */
export type EventPayload = Record<string, unknown>;

// ---------------------------------------------------------------------------
// SQLite schema (default driver)
// ---------------------------------------------------------------------------

export const projects = sqliteTable("projects", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").notNull().unique(),
  description: text("description").notNull().default(""),
  goal: text("goal").notNull().default(""),
  repoUrl: text("repo_url"),
  defaultBranch: text("default_branch"),
  blogRepoUrl: text("blog_repo_url"),
  blogContentPath: text("blog_content_path"),
  /** JSON list of public subdirs in the blog repo (extensible). */
  mediaPaths: text("media_paths", { mode: "json" }).$type<string[]>(),
  constraints: text("constraints"),
  architectureNotes: text("architecture_notes"),
  notes: text("notes"),
  /** LLM-maintained current completion state of the project. */
  stateSummary: text("state_summary"),
  /** Caller identity (LiteLLM key → user name) of the creating mutation; '' = unattributed (legacy). */
  owner: text("owner").notNull().default(""),
  createdAt: integer("created_at").notNull(),
  updatedAt: integer("updated_at").notNull(),
});

export const ideas = sqliteTable(
  "ideas",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    projectId: integer("project_id")
      .notNull()
      .references(() => projects.id, { onDelete: "cascade" }),
    text: text("text").notNull(),
    state: text("state").notNull().default("idea"),
    /** JSON spec (goal, steps, acceptance, kind, publish_targets, notes). */
    spec: text("spec", { mode: "json" }).$type<IdeaSpec>(),
    /** JSON list of idea ids this idea depends on. */
    dependsOn: text("depends_on", { mode: "json" }).$type<number[]>(),
    /** Caller identity (LiteLLM key → user name) of the creating mutation; '' = unattributed (legacy). */
    owner: text("owner").notNull().default(""),
    createdAt: integer("created_at").notNull(),
    updatedAt: integer("updated_at").notNull(),
  },
  (t) => [index("ideas_project_id_idx").on(t.projectId)],
);

export const tasks = sqliteTable(
  "tasks",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    /** 1:1 with ideas. */
    ideaId: integer("idea_id")
      .notNull()
      .unique()
      .references(() => ideas.id, { onDelete: "cascade" }),
    projectId: integer("project_id")
      .notNull()
      .references(() => projects.id, { onDelete: "cascade" }),
    /** JSON snapshot of the idea spec at task creation. */
    spec: text("spec", { mode: "json" }).$type<IdeaSpec>().notNull(),
    state: text("state").notNull().default("backlog"),
    stateChangedAt: integer("state_changed_at").notNull(),
    branch: text("branch"),
    lastCommit: text("last_commit"),
    qaRounds: integer("qa_rounds").notNull().default(0),
    paused: integer("paused", { mode: "boolean" }).notNull().default(false),
    workspace: text("workspace"),
    /** Accepted resolution plan (Needs Attention → Backlog). */
    resolution: text("resolution"),
    /** Owner (inherited from the idea at task creation); '' = unattributed (legacy). */
    owner: text("owner").notNull().default(""),
    createdAt: integer("created_at").notNull(),
  },
  (t) => [
    index("tasks_project_id_idx").on(t.projectId),
    index("tasks_state_idx").on(t.state),
  ],
);

export const taskEvents = sqliteTable(
  "task_events",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    taskId: integer("task_id")
      .notNull()
      .references(() => tasks.id, { onDelete: "cascade" }),
    ts: integer("ts").notNull(),
    type: text("type").notNull(),
    payload: text("payload", { mode: "json" }).$type<EventPayload>(),
  },
  (t) => [index("task_events_task_id_ts_idx").on(t.taskId, t.ts)],
);

export const usage = sqliteTable(
  "usage",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    /** Nullable for grooming/summary calls. */
    taskId: integer("task_id").references(() => tasks.id, { onDelete: "set null" }),
    projectId: integer("project_id")
      .notNull()
      .references(() => projects.id, { onDelete: "cascade" }),
    ts: integer("ts").notNull(),
    role: text("role").notNull(),
    model: text("model").notNull(),
    thinking: text("thinking"),
    tokensIn: integer("tokens_in").notNull().default(0),
    tokensOut: integer("tokens_out").notNull().default(0),
    cost: real("cost").notNull().default(0),
    /** Owner whose key this LLM call billed to (Phase 2); '' = service key / unattributed (legacy). */
    owner: text("owner").notNull().default(""),
  },
  (t) => [
    index("usage_project_id_ts_idx").on(t.projectId, t.ts),
    index("usage_task_id_idx").on(t.taskId),
  ],
);

export const kv = sqliteTable("kv", {
  key: text("key").primaryKey(),
  value: text("value").notNull(),
});

/**
 * Durable project file store audit (proposal:
 * tier2-kanban-remote-client-file-intake). One row per staged file in
 * /files/<project_id>/ — the retention unit is the PROJECT (icebox items
 * can wait months), so rows live as long as the project (FK cascade on
 * delete_project) and the orphan sweep only touches dirs of GONE projects.
 */
export const projectFiles = sqliteTable(
  "project_files",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    projectId: integer("project_id")
      .notNull()
      .references(() => projects.id, { onDelete: "cascade" }),
    /** Project-store-relative path (validated: no `..`, no absolute). */
    path: text("path").notNull(),
    size: integer("size").notNull(),
    /** Caller identity that staged the file; '' = unattributed. */
    stagedBy: text("staged_by").notNull().default(""),
    /** INTEGER epoch milliseconds. */
    stagedAt: integer("staged_at").notNull(),
  },
  (t) => [index("project_files_project_id_idx").on(t.projectId)],
);

export const sqliteSchema = { projects, ideas, tasks, taskEvents, usage, kv, projectFiles };

export type ProjectRow = typeof projects.$inferSelect;
export type IdeaRow = typeof ideas.$inferSelect;
export type TaskRow = typeof tasks.$inferSelect;
export type TaskEventRow = typeof taskEvents.$inferSelect;
export type UsageRow = typeof usage.$inferSelect;
export type KvRow = typeof kv.$inferSelect;
export type ProjectFileRow = typeof projectFiles.$inferSelect;

// ---------------------------------------------------------------------------
// MySQL schema (DB pre-created; app creates tables only)
// ---------------------------------------------------------------------------

export const mysqlProjects = mysqlTable(
  "projects",
  {
    id: int("id").primaryKey().autoincrement(),
    name: varchar("name", { length: 255 }).notNull(),
    description: mediumtext("description").notNull(),
    goal: mediumtext("goal").notNull(),
    repoUrl: varchar("repo_url", { length: 512 }),
    defaultBranch: varchar("default_branch", { length: 255 }),
    blogRepoUrl: varchar("blog_repo_url", { length: 512 }),
    blogContentPath: varchar("blog_content_path", { length: 512 }),
    mediaPaths: mysqlJson("media_paths").$type<string[]>(),
    constraints: mediumtext("constraints"),
    architectureNotes: mediumtext("architecture_notes"),
    notes: mediumtext("notes"),
    stateSummary: mediumtext("state_summary"),
    owner: varchar("owner", { length: 64 }).notNull().default(""),
    createdAt: bigint("created_at", { mode: "number" }).notNull(),
    updatedAt: bigint("updated_at", { mode: "number" }).notNull(),
  },
  (t) => [mysqlUniqueIndex("uq_projects_name").on(t.name)],
);

export const mysqlIdeas = mysqlTable(
  "ideas",
  {
    id: int("id").primaryKey().autoincrement(),
    projectId: int("project_id")
      .notNull()
      .references(() => mysqlProjects.id, { onDelete: "cascade" }),
    text: mediumtext("text").notNull(),
    state: varchar("state", { length: 32 }).notNull().default("idea"),
    spec: mysqlJson("spec").$type<IdeaSpec>(),
    dependsOn: mysqlJson("depends_on").$type<number[]>(),
    owner: varchar("owner", { length: 64 }).notNull().default(""),
    createdAt: bigint("created_at", { mode: "number" }).notNull(),
    updatedAt: bigint("updated_at", { mode: "number" }).notNull(),
  },
  (t) => [mysqlIndex("ideas_project_id_idx").on(t.projectId)],
);

export const mysqlTasks = mysqlTable(
  "tasks",
  {
    id: int("id").primaryKey().autoincrement(),
    ideaId: int("idea_id")
      .notNull()
      .references(() => mysqlIdeas.id, { onDelete: "cascade" }),
    projectId: int("project_id")
      .notNull()
      .references(() => mysqlProjects.id, { onDelete: "cascade" }),
    spec: mysqlJson("spec").$type<IdeaSpec>().notNull(),
    state: varchar("state", { length: 32 }).notNull().default("backlog"),
    stateChangedAt: bigint("state_changed_at", { mode: "number" }).notNull(),
    branch: varchar("branch", { length: 255 }),
    lastCommit: varchar("last_commit", { length: 64 }),
    qaRounds: int("qa_rounds").notNull().default(0),
    paused: boolean("paused").notNull().default(false),
    workspace: varchar("workspace", { length: 512 }),
    resolution: mediumtext("resolution"),
    owner: varchar("owner", { length: 64 }).notNull().default(""),
    createdAt: bigint("created_at", { mode: "number" }).notNull(),
  },
  (t) => [
    mysqlUniqueIndex("uq_tasks_idea").on(t.ideaId),
    mysqlIndex("tasks_project_id_idx").on(t.projectId),
    mysqlIndex("tasks_state_idx").on(t.state),
  ],
);

export const mysqlTaskEvents = mysqlTable(
  "task_events",
  {
    id: int("id").primaryKey().autoincrement(),
    taskId: int("task_id")
      .notNull()
      .references(() => mysqlTasks.id, { onDelete: "cascade" }),
    ts: bigint("ts", { mode: "number" }).notNull(),
    type: varchar("type", { length: 32 }).notNull(),
    payload: mysqlJson("payload").$type<EventPayload>(),
  },
  (t) => [mysqlIndex("task_events_task_id_ts_idx").on(t.taskId, t.ts)],
);

export const mysqlUsage = mysqlTable(
  "usage",
  {
    id: int("id").primaryKey().autoincrement(),
    taskId: int("task_id").references(() => mysqlTasks.id, { onDelete: "set null" }),
    projectId: int("project_id")
      .notNull()
      .references(() => mysqlProjects.id, { onDelete: "cascade" }),
    ts: bigint("ts", { mode: "number" }).notNull(),
    role: varchar("role", { length: 32 }).notNull(),
    model: varchar("model", { length: 128 }).notNull(),
    thinking: varchar("thinking", { length: 16 }),
    tokensIn: int("tokens_in").notNull().default(0),
    tokensOut: int("tokens_out").notNull().default(0),
    cost: double("cost").notNull().default(0),
    /** Owner whose key this LLM call billed to (Phase 2); '' = service key / unattributed (legacy). */
    owner: varchar("owner", { length: 64 }).notNull().default(""),
  },
  (t) => [
    mysqlIndex("usage_project_id_ts_idx").on(t.projectId, t.ts),
    mysqlIndex("usage_task_id_idx").on(t.taskId),
  ],
);

export const mysqlKv = mysqlTable("kv", {
  key: varchar("key", { length: 191 }).primaryKey(),
  value: mediumtext("value").notNull(),
});

export const mysqlProjectFiles = mysqlTable(
  "project_files",
  {
    id: int("id").primaryKey().autoincrement(),
    projectId: int("project_id")
      .notNull()
      .references(() => mysqlProjects.id, { onDelete: "cascade" }),
    path: varchar("path", { length: 512 }).notNull(),
    size: bigint("size", { mode: "number" }).notNull(),
    stagedBy: varchar("staged_by", { length: 64 }).notNull().default(""),
    stagedAt: bigint("staged_at", { mode: "number" }).notNull(),
  },
  (t) => [mysqlIndex("project_files_project_id_idx").on(t.projectId)],
);

export const mysqlSchema = {
  projects: mysqlProjects,
  ideas: mysqlIdeas,
  tasks: mysqlTasks,
  taskEvents: mysqlTaskEvents,
  usage: mysqlUsage,
  kv: mysqlKv,
  projectFiles: mysqlProjectFiles,
};
