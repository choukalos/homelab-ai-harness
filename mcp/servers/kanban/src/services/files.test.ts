/**
 * Durable project file store tests (proposal:
 * tier2-kanban-remote-client-file-intake, part 1): path validation,
 * stageFile write + project_files audit row, project-delete GC (dir + rows),
 * and the orphan sweep (live projects + young dirs kept, stale orphans
 * removed) — over a real temp sqlite db + temp store dir with a real
 * orchestrator (mocked task/QA/deploy/summary; no network, no model).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, utimesSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { eq } from "drizzle-orm";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import type { KanbanConfig } from "../config.js";
import { initDb } from "../db/index.js";
import { projectFiles, projects } from "../db/schema.js";
import type { AgentRuntime, TaskRunContext, TaskRunResult, TaskRunner } from "../agent/sessions.js";
import type { QaRunContext, QaVerdict } from "../agent/qa.js";
import type { SummaryUpdateContext } from "../agent/summary.js";
import type { DeployContext, DeployResult } from "../deploy/index.js";
import {
  Orchestrator,
  type DeployRunnerLike,
  type QaGateLike,
  type SummaryUpdaterLike,
} from "../orchestrator.js";
import { createKanbanServices, type KanbanServices } from "../services/index.js";
import { ServiceError } from "../services/common.js";
import {
  FILES_ORPHAN_TTL_DAYS,
  fileContainerPath,
  listProjectFiles,
  removeProjectFiles,
  stageFile,
  sweepOrphanProjectFiles,
  validateProjectFilePath,
} from "./files.js";

const DAY = 86_400_000;
const TTL = FILES_ORPHAN_TTL_DAYS * DAY;

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
    mediaConcurrentTasks: 1,
    nonMediaConcurrentTasks: 1,
    agentConcurrentTasks: 1,
    agentSlugs: [],
    workspaceCleanupDays: 7,
    server: { bindAddr: "127.0.0.1", port: 3000 },
  };
}

class OkTaskRunner implements TaskRunner {
  run(_ctx: TaskRunContext): Promise<TaskRunResult> {
    return Promise.resolve({ summary: "ok", lastCommit: null });
  }
  abort(_taskId: number): void {}
}

class PassQa implements QaGateLike {
  readonly maxRounds = 2;
  run(_ctx: QaRunContext): Promise<QaVerdict> {
    return Promise.resolve({ pass: true, feedback: "" });
  }
}

class OkDeploy implements DeployRunnerLike {
  deploy(_ctx: DeployContext): Promise<DeployResult> {
    return Promise.resolve({ published: "pushed", target: "origin" });
  }
}

class FixedSummary implements SummaryUpdaterLike {
  update(_ctx: SummaryUpdateContext): Promise<string> {
    return Promise.resolve("New project state summary.");
  }
}

async function setup() {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-files-"));
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const filesRoot = path.join(dir, "files");
  const workspaceRoot = path.join(dir, "workspace");
  mkdirSync(filesRoot, { recursive: true });
  mkdirSync(workspaceRoot, { recursive: true });
  const orch = new Orchestrator({
    cfg,
    db,
    agent: {} as unknown as AgentRuntime,
    tasks: new OkTaskRunner(),
    qa: new PassQa(),
    deploy: new OkDeploy(),
    summary: new FixedSummary(),
    workspaceRoot,
    filesRoot,
    noTimer: true,
  });
  const services = createKanbanServices(db, { orchestrator: orch });
  return { cfg, db, q, orch, services, filesRoot, dir };
}

// ---------------------------------------------------------------------------
// Path validation
// ---------------------------------------------------------------------------

test("validateProjectFilePath: accepts clean relative paths, rejects traversal/absolute/garbage", () => {
  assert.equal(validateProjectFilePath("scripts/frozen.py"), "scripts/frozen.py");
  assert.equal(validateProjectFilePath("  nested/a b/c.txt  "), "nested/a b/c.txt");
  assert.equal(fileContainerPath(7, "scripts/frozen.py"), "/files/7/scripts/frozen.py");
  for (const bad of [
    "",
    "   ",
    "/abs/path",
    "../up",
    "a/../b",
    "a/..",
    ".",
    "..",
    "a//b",
    "a/",
    "a\\b",
    "a\0b",
  ]) {
    assert.throws(
      () => validateProjectFilePath(bad),
      ServiceError,
      `rejects ${JSON.stringify(bad)}`,
    );
  }
});

// ---------------------------------------------------------------------------
// Store write (stageFile)
// ---------------------------------------------------------------------------

test("stageFile: writes under root/<project_id>/, records the project_files row, returns the container path", async () => {
  const { q, services, filesRoot } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const content = Buffer.from("#!/usr/bin/env python\nprint('frozen')\n");
  const res = await stageFile(q, {
    root: filesRoot,
    projectId: p.id,
    path: "scripts/frozen.py",
    content,
    owner: "chuck",
  });
  assert.equal(res.containerPath, `/files/${p.id}/scripts/frozen.py`);
  assert.equal(res.path, "scripts/frozen.py");
  assert.equal(res.size, content.length);
  const onDisk = await readFile(path.join(filesRoot, String(p.id), "scripts/frozen.py"));
  assert.deepEqual(onDisk, content, "file on disk under the project dir");
  const rows = await q.select().from(projectFiles).where(eq(projectFiles.projectId, p.id));
  assert.equal(rows.length, 1, "one audit row");
  assert.equal(rows[0]!.path, "scripts/frozen.py");
  assert.equal(rows[0]!.size, content.length);
  assert.equal(rows[0]!.stagedBy, "chuck");
  const list = await listProjectFiles(q, p.id);
  assert.equal(list.length, 1);
  assert.equal(list[0]!.path, "scripts/frozen.py");
  assert.equal(list[0]!.stagedBy, "chuck");
});

test("stageFile: 404 unknown project, 400 invalid paths (nothing written)", async () => {
  const { q, services, filesRoot } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  await assert.rejects(
    stageFile(q, { root: filesRoot, projectId: 9999, path: "a.txt", content: Buffer.from("x") }),
    /project 9999 not found/,
  );
  await assert.rejects(
    stageFile(q, { root: filesRoot, projectId: p.id, path: "../escape", content: Buffer.from("x") }),
    ServiceError,
  );
  await assert.rejects(
    stageFile(q, { root: filesRoot, projectId: p.id, path: "/abs", content: Buffer.from("x") }),
    ServiceError,
  );
  assert.equal((await q.select().from(projectFiles)).length, 0, "no rows written");
  assert.ok(!existsSync(path.join(filesRoot, "9999")), "no dir created for the unknown project");
});

test("stageFile: re-staging the same path overwrites the file and replaces the row (last write wins)", async () => {
  const { q, services, filesRoot } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  const v1 = Buffer.from("version 1");
  const v2 = Buffer.from("version 2 (evolved)");
  await stageFile(q, { root: filesRoot, projectId: p.id, path: "scripts/frozen.py", content: v1, owner: "chuck" });
  const res = await stageFile(q, {
    root: filesRoot,
    projectId: p.id,
    path: "scripts/frozen.py",
    content: v2,
    owner: "dylan",
  });
  assert.deepEqual(await readFile(path.join(filesRoot, String(p.id), "scripts/frozen.py")), v2);
  const rows = await q.select().from(projectFiles).where(eq(projectFiles.projectId, p.id));
  assert.equal(rows.length, 1, "single row after overwrite");
  assert.equal(rows[0]!.size, v2.length);
  assert.equal(rows[0]!.stagedBy, "dylan");
  assert.equal(res.size, v2.length);
});

// ---------------------------------------------------------------------------
// GC path 1: project delete (dir + rows, immediate, no TTL)
// ---------------------------------------------------------------------------

test("deleteProject: removes the project's store dir + its project_files rows", async () => {
  const { q, services, filesRoot } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  await stageFile(q, { root: filesRoot, projectId: p.id, path: "scripts/a.py", content: Buffer.from("a") });
  await stageFile(q, { root: filesRoot, projectId: p.id, path: "config/b.yaml", content: Buffer.from("b") });
  const dir = path.join(filesRoot, String(p.id));
  assert.ok(existsSync(dir), "store dir exists before delete");

  const result = await services.deleteProject(p.id);
  assert.equal(result.project.id, p.id);
  assert.ok(result.removedDirs.includes(dir), "store dir listed as removed");
  assert.ok(!existsSync(dir), "store dir gone");
  assert.equal((await q.select().from(projectFiles)).length, 0, "project_files rows gone");
  assert.equal(await services.getProject(p.id), undefined, "project row gone");
});

test("removeProjectFiles: explicit GC removes dir + rows; idempotent on a second call", async () => {
  const { q, services, filesRoot } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  await stageFile(q, { root: filesRoot, projectId: p.id, path: "x.txt", content: Buffer.from("x") });
  const dir = path.join(filesRoot, String(p.id));
  const removed = await removeProjectFiles(q, filesRoot, p.id);
  assert.deepEqual(removed, [dir]);
  assert.ok(!existsSync(dir));
  assert.equal((await q.select().from(projectFiles)).length, 0);
  assert.deepEqual(await removeProjectFiles(q, filesRoot, p.id), [], "second call: nothing to remove");
});

// ---------------------------------------------------------------------------
// GC path 2: orphan sweep (project gone + older than TTL only)
// ---------------------------------------------------------------------------

test("sweepProjectFiles: removes only stale orphans — live projects and young dirs kept", async () => {
  const { q, services, orch, filesRoot } = await setup();
  const now = Date.now();

  // A: LIVE project, old dir → kept (any age — icebox retention).
  const a = await services.createProject({ name: "Alpha" });
  await stageFile(q, { root: filesRoot, projectId: a.id, path: "keep.txt", content: Buffer.from("keep") });
  // B: project deleted (simulated failed deletion — dir left behind), old dir → removed.
  const b = await services.createProject({ name: "Beta" });
  await stageFile(q, { root: filesRoot, projectId: b.id, path: "stale.txt", content: Buffer.from("stale") });
  await q.delete(projects).where(eq(projects.id, b.id));
  // C: project deleted, FRESH dir (younger than the 30-day TTL) → kept.
  const c = await services.createProject({ name: "Gamma" });
  await stageFile(q, { root: filesRoot, projectId: c.id, path: "fresh.txt", content: Buffer.from("fresh") });
  await q.delete(projects).where(eq(projects.id, c.id));

  // Backdate A's and B's dirs (40 days > 30-day TTL); C stays fresh.
  const old = new Date(now - 40 * DAY);
  utimesSync(path.join(filesRoot, String(a.id)), old, old);
  utimesSync(path.join(filesRoot, String(b.id)), old, old);
  // A non-numeric dir, old → not a project dir, untouched.
  const foreign = path.join(filesRoot, "notes");
  mkdirSync(foreign, { recursive: true });
  utimesSync(foreign, old, old);

  const result = await orch.sweepProjectFiles();
  assert.deepEqual(result.deleted, [String(b.id)], "only the stale orphan removed");
  assert.ok(result.skipped.includes(String(a.id)), "live project skipped");
  assert.ok(result.skipped.includes(String(c.id)), "young orphan skipped");
  assert.ok(existsSync(path.join(filesRoot, String(a.id))), "live project dir kept");
  assert.ok(existsSync(path.join(filesRoot, String(c.id))), "young orphan dir kept");
  assert.ok(!existsSync(path.join(filesRoot, String(b.id))), "stale orphan dir removed");
  assert.ok(existsSync(foreign), "non-project dir untouched");

  // A second pass is a no-op.
  const again = await orch.sweepProjectFiles();
  assert.deepEqual(again.deleted, []);
});

test("sweepOrphanProjectFiles: TTL boundary — younger than TTL kept, strictly older deleted", async () => {
  const { q, services, filesRoot } = await setup();
  const p = await services.createProject({ name: "Alpha" });
  await stageFile(q, { root: filesRoot, projectId: p.id, path: "x.txt", content: Buffer.from("x") });
  await q.delete(projects).where(eq(projects.id, p.id));
  const fixedNow = Date.now();
  // 1s younger than the TTL → kept (strictly older is required). The margin
  // keeps this deterministic on filesystems with coarse (second-granular)
  // mtime precision — the exact-TTL boundary is not reliably representable.
  utimesSync(
    path.join(filesRoot, String(p.id)),
    new Date(fixedNow - TTL + 1000),
    new Date(fixedNow - TTL + 1000),
  );
  let result = await sweepOrphanProjectFiles(q, filesRoot, { ttlMs: TTL, now: () => fixedNow });
  assert.deepEqual(result.deleted, [], "younger than TTL is kept");
  assert.deepEqual(result.skipped, [String(p.id)]);
  // 1s older than the TTL → deleted.
  utimesSync(
    path.join(filesRoot, String(p.id)),
    new Date(fixedNow - TTL - 1000),
    new Date(fixedNow - TTL - 1000),
  );
  result = await sweepOrphanProjectFiles(q, filesRoot, { ttlMs: TTL, now: () => fixedNow });
  assert.deepEqual(result.deleted, [String(p.id)], "strictly older than TTL is deleted");
});

test("sweepOrphanProjectFiles: missing store root is a no-op", async () => {
  const { q } = await setup();
  const result = await sweepOrphanProjectFiles(
    q,
    path.join(tmpdir(), "ai-kanban-files-does-not-exist"),
    { ttlMs: TTL },
  );
  assert.deepEqual(result, { deleted: [], skipped: [] });
});
