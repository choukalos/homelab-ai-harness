/**
 * Versioned, idempotent migrations (PLAN.md §2: "Migrations are versioned +
 * idempotent (schema evolves while the tool is in use)").
 *
 * Each migration carries SQL for both dialects. Every statement is
 * idempotent (CREATE ... IF NOT EXISTS), and the runner (migrate.ts) skips
 * versions already recorded in the schema_migrations table.
 *
 * MySQL: the database is pre-created and the app user has table-level
 * privileges — migrations create TABLES ONLY (never CREATE DATABASE).
 */

export interface Migration {
  /** Monotonic version id (applied in array order). */
  version: string;
  description: string;
  sqlite: string;
  mysql: string;
}

const INIT_SQLITE = `
CREATE TABLE IF NOT EXISTS "projects" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "name" TEXT NOT NULL UNIQUE,
  "description" TEXT NOT NULL DEFAULT '',
  "goal" TEXT NOT NULL DEFAULT '',
  "repo_url" TEXT,
  "default_branch" TEXT,
  "blog_repo_url" TEXT,
  "blog_content_path" TEXT,
  "media_paths" TEXT,
  "constraints" TEXT,
  "architecture_notes" TEXT,
  "notes" TEXT,
  "state_summary" TEXT,
  "created_at" INTEGER NOT NULL,
  "updated_at" INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS "ideas" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "project_id" INTEGER NOT NULL REFERENCES "projects"("id") ON DELETE CASCADE,
  "text" TEXT NOT NULL,
  "state" TEXT NOT NULL DEFAULT 'idea',
  "spec" TEXT,
  "depends_on" TEXT,
  "created_at" INTEGER NOT NULL,
  "updated_at" INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS "ideas_project_id_idx" ON "ideas" ("project_id");

CREATE TABLE IF NOT EXISTS "tasks" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "idea_id" INTEGER NOT NULL UNIQUE REFERENCES "ideas"("id") ON DELETE CASCADE,
  "project_id" INTEGER NOT NULL REFERENCES "projects"("id") ON DELETE CASCADE,
  "spec" TEXT NOT NULL,
  "state" TEXT NOT NULL DEFAULT 'backlog',
  "state_changed_at" INTEGER NOT NULL,
  "branch" TEXT,
  "last_commit" TEXT,
  "qa_rounds" INTEGER NOT NULL DEFAULT 0,
  "paused" INTEGER NOT NULL DEFAULT 0,
  "workspace" TEXT,
  "resolution" TEXT,
  "created_at" INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS "tasks_project_id_idx" ON "tasks" ("project_id");

CREATE INDEX IF NOT EXISTS "tasks_state_idx" ON "tasks" ("state");

CREATE TABLE IF NOT EXISTS "task_events" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "task_id" INTEGER NOT NULL REFERENCES "tasks"("id") ON DELETE CASCADE,
  "ts" INTEGER NOT NULL,
  "type" TEXT NOT NULL,
  "payload" TEXT
);

CREATE INDEX IF NOT EXISTS "task_events_task_id_ts_idx" ON "task_events" ("task_id", "ts");

CREATE TABLE IF NOT EXISTS "usage" (
  "id" INTEGER PRIMARY KEY AUTOINCREMENT,
  "task_id" INTEGER REFERENCES "tasks"("id") ON DELETE SET NULL,
  "project_id" INTEGER NOT NULL REFERENCES "projects"("id") ON DELETE CASCADE,
  "ts" INTEGER NOT NULL,
  "role" TEXT NOT NULL,
  "model" TEXT NOT NULL,
  "thinking" TEXT,
  "tokens_in" INTEGER NOT NULL DEFAULT 0,
  "tokens_out" INTEGER NOT NULL DEFAULT 0,
  "cost" REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS "usage_project_id_ts_idx" ON "usage" ("project_id", "ts");

CREATE INDEX IF NOT EXISTS "usage_task_id_idx" ON "usage" ("task_id");

CREATE TABLE IF NOT EXISTS "kv" (
  "key" TEXT PRIMARY KEY,
  "value" TEXT NOT NULL
);
`;

const INIT_MYSQL = `
CREATE TABLE IF NOT EXISTS \`projects\` (
  \`id\` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  \`name\` VARCHAR(255) NOT NULL,
  \`description\` MEDIUMTEXT NOT NULL,
  \`goal\` MEDIUMTEXT NOT NULL,
  \`repo_url\` VARCHAR(512) NULL,
  \`default_branch\` VARCHAR(255) NULL,
  \`blog_repo_url\` VARCHAR(512) NULL,
  \`blog_content_path\` VARCHAR(512) NULL,
  \`media_paths\` JSON NULL,
  \`constraints\` MEDIUMTEXT NULL,
  \`architecture_notes\` MEDIUMTEXT NULL,
  \`notes\` MEDIUMTEXT NULL,
  \`state_summary\` MEDIUMTEXT NULL,
  \`created_at\` BIGINT NOT NULL,
  \`updated_at\` BIGINT NOT NULL,
  PRIMARY KEY (\`id\`),
  UNIQUE KEY \`uq_projects_name\` (\`name\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS \`ideas\` (
  \`id\` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  \`project_id\` INT UNSIGNED NOT NULL,
  \`text\` MEDIUMTEXT NOT NULL,
  \`state\` VARCHAR(32) NOT NULL DEFAULT 'idea',
  \`spec\` JSON NULL,
  \`depends_on\` JSON NULL,
  \`created_at\` BIGINT NOT NULL,
  \`updated_at\` BIGINT NOT NULL,
  PRIMARY KEY (\`id\`),
  KEY \`ideas_project_id_idx\` (\`project_id\`),
  CONSTRAINT \`fk_ideas_project\` FOREIGN KEY (\`project_id\`) REFERENCES \`projects\` (\`id\`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS \`tasks\` (
  \`id\` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  \`idea_id\` INT UNSIGNED NOT NULL,
  \`project_id\` INT UNSIGNED NOT NULL,
  \`spec\` JSON NOT NULL,
  \`state\` VARCHAR(32) NOT NULL DEFAULT 'backlog',
  \`state_changed_at\` BIGINT NOT NULL,
  \`branch\` VARCHAR(255) NULL,
  \`last_commit\` VARCHAR(64) NULL,
  \`qa_rounds\` INT NOT NULL DEFAULT 0,
  \`paused\` TINYINT(1) NOT NULL DEFAULT 0,
  \`workspace\` VARCHAR(512) NULL,
  \`resolution\` MEDIUMTEXT NULL,
  \`created_at\` BIGINT NOT NULL,
  PRIMARY KEY (\`id\`),
  UNIQUE KEY \`uq_tasks_idea\` (\`idea_id\`),
  KEY \`tasks_project_id_idx\` (\`project_id\`),
  KEY \`tasks_state_idx\` (\`state\`),
  CONSTRAINT \`fk_tasks_idea\` FOREIGN KEY (\`idea_id\`) REFERENCES \`ideas\` (\`id\`) ON DELETE CASCADE,
  CONSTRAINT \`fk_tasks_project\` FOREIGN KEY (\`project_id\`) REFERENCES \`projects\` (\`id\`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS \`task_events\` (
  \`id\` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  \`task_id\` INT UNSIGNED NOT NULL,
  \`ts\` BIGINT NOT NULL,
  \`type\` VARCHAR(32) NOT NULL,
  \`payload\` JSON NULL,
  PRIMARY KEY (\`id\`),
  KEY \`task_events_task_id_ts_idx\` (\`task_id\`, \`ts\`),
  CONSTRAINT \`fk_task_events_task\` FOREIGN KEY (\`task_id\`) REFERENCES \`tasks\` (\`id\`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS \`usage\` (
  \`id\` INT UNSIGNED NOT NULL AUTO_INCREMENT,
  \`task_id\` INT UNSIGNED NULL,
  \`project_id\` INT UNSIGNED NOT NULL,
  \`ts\` BIGINT NOT NULL,
  \`role\` VARCHAR(32) NOT NULL,
  \`model\` VARCHAR(128) NOT NULL,
  \`thinking\` VARCHAR(16) NULL,
  \`tokens_in\` INT NOT NULL DEFAULT 0,
  \`tokens_out\` INT NOT NULL DEFAULT 0,
  \`cost\` DOUBLE NOT NULL DEFAULT 0,
  PRIMARY KEY (\`id\`),
  KEY \`usage_project_id_ts_idx\` (\`project_id\`, \`ts\`),
  KEY \`usage_task_id_idx\` (\`task_id\`),
  CONSTRAINT \`fk_usage_task\` FOREIGN KEY (\`task_id\`) REFERENCES \`tasks\` (\`id\`) ON DELETE SET NULL,
  CONSTRAINT \`fk_usage_project\` FOREIGN KEY (\`project_id\`) REFERENCES \`projects\` (\`id\`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS \`kv\` (
  \`key\` VARCHAR(191) NOT NULL,
  \`value\` MEDIUMTEXT NOT NULL,
  PRIMARY KEY (\`key\`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
`;

export const MIGRATIONS: readonly Migration[] = [
  {
    version: "0001_init",
    description:
      "Initial schema per PLAN.md §2: projects, ideas, tasks, task_events, usage, kv",
    sqlite: INIT_SQLITE,
    mysql: INIT_MYSQL,
  },
  {
    version: "0002_owner",
    description:
      "Owner attribution (MCP-first change): owner column on projects/ideas/tasks — " +
      "the caller identity (LiteLLM key → user name) of the mutation; tasks inherit " +
      "the idea's owner at move-to-backlog. Additive-only; legacy rows stay '' (unattributed).",
    sqlite: `
ALTER TABLE "projects" ADD COLUMN "owner" TEXT NOT NULL DEFAULT '';
ALTER TABLE "ideas" ADD COLUMN "owner" TEXT NOT NULL DEFAULT '';
ALTER TABLE "tasks" ADD COLUMN "owner" TEXT NOT NULL DEFAULT '';
`,
    mysql: `
ALTER TABLE \`projects\` ADD COLUMN \`owner\` VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE \`ideas\` ADD COLUMN \`owner\` VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE \`tasks\` ADD COLUMN \`owner\` VARCHAR(64) NOT NULL DEFAULT '';
`,
  },
  {
    version: "0003_usage_owner",
    description:
      "Per-user spend attribution (Phase 2): owner column on usage — the owner " +
      "whose key the LLM call billed to (denormalized at capture; grooming/summary " +
      "rows have no task to join through). Additive-only; legacy rows stay '' (unattributed).",
    sqlite: `
ALTER TABLE "usage" ADD COLUMN "owner" TEXT NOT NULL DEFAULT '';
`,
    mysql: `
ALTER TABLE \`usage\` ADD COLUMN \`owner\` VARCHAR(64) NOT NULL DEFAULT '';
`,
  },
];
