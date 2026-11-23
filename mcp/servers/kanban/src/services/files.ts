/**
 * Durable project file store (proposal:
 * tier2-kanban-remote-client-file-intake, part 1).
 *
 * Client-supplied task inputs (scripts, configs, text) live in a dedicated
 * persistent store — `/files/<project_id>/...` in the container (host:
 * /home/chuck/data/ai-kanban-files) — instead of the transitory workspace.
 *
 * Retention design (the load-bearing constraint):
 * - The retention unit is the PROJECT, not the task: staged inputs feed work
 *   that can sit in the icebox for months, and a `done` task may be
 *   restarted/retried with the same inputs.
 * - Lifecycle GC (tied to project deletion, never a time sweep of live
 *   inputs):
 *   - `delete_project` removes `/files/<project_id>/` + its project_files
 *     rows immediately (removeProjectFiles).
 *   - Orphan sweep (orchestrator background job, same pattern as
 *     cleanupWorkspaces): removes only dirs whose project_id no longer
 *     exists in `projects` AND that are older than a TTL (default 30 days)
 *     — a safety valve for failed deletions, never for live projects
 *     (sweepOrphanProjectFiles).
 * - The `project_files` table (project_id, path, size, staged_by,
 *   staged_at) is the audit trail; its FK cascade removes rows with the
 *   project.
 *
 * Media inputs do NOT go through this store — they are referenced by
 * location (NAS /media-store, public drop /publish) via stage_ref.
 */
import path from "node:path";
import { mkdir, readdir, rm, stat, writeFile } from "node:fs/promises";
import type { Stats } from "node:fs";
import { and, asc, eq } from "drizzle-orm";
import { projectFiles, projects } from "../db/tables.js";
import { ServiceError, type Db } from "./common.js";

/** Container mount of the durable store (compose: /files). */
export const FILES_MOUNT = "/files";
/** Orphan-sweep TTL default (days) — safety valve only, never for live projects. */
export const FILES_ORPHAN_TTL_DAYS = 30;
/** Max staged file path length (matches the project_files.path column). */
export const MAX_FILE_PATH_LENGTH = 512;

export interface ProjectFile {
  projectId: number;
  /** Project-store-relative path (validated). */
  path: string;
  size: number;
  /** Caller identity that staged the file; '' = unattributed. */
  stagedBy: string;
  stagedAt: number;
}

/** Result of a store write (stage_file). */
export interface StageFileResult {
  projectId: number;
  /** Normalized project-store-relative path. */
  path: string;
  /** Container-side path to cite in specs (/files/<project_id>/<path>). */
  containerPath: string;
  size: number;
}

/** Container-side path for a staged file. */
export function fileContainerPath(projectId: number, relPath: string): string {
  return `${FILES_MOUNT}/${projectId}/${relPath}`;
}

/**
 * Validate a client-supplied project-relative file path.
 *
 * Rules: non-empty, RELATIVE to the project store (no leading `/`), no `..`
 * or `.` segments, no empty segments (double/leading/trailing slashes), no
 * backslashes (POSIX separators only), no null bytes, bounded length.
 * Returns the normalized path (forward slashes). 400 on violation.
 */
export function validateProjectFilePath(raw: string): string {
  if (typeof raw !== "string") {
    throw new ServiceError(400, "path is required (project-relative, e.g. scripts/frozen.py)");
  }
  const p = raw.trim();
  if (p === "") {
    throw new ServiceError(400, "path must be a non-empty project-relative path");
  }
  if (p.length > MAX_FILE_PATH_LENGTH) {
    throw new ServiceError(400, `path must be at most ${MAX_FILE_PATH_LENGTH} characters`);
  }
  if (p.includes("\0")) {
    throw new ServiceError(400, "path must not contain null bytes");
  }
  if (path.isAbsolute(p)) {
    throw new ServiceError(400, `path must be relative to the project store (got absolute path ${JSON.stringify(raw)})`);
  }
  if (p.includes("\\")) {
    throw new ServiceError(400, `path must use forward slashes (got ${JSON.stringify(raw)})`);
  }
  const segments = p.split("/");
  for (const seg of segments) {
    if (seg === "" || seg === "." || seg === "..") {
      throw new ServiceError(
        400,
        `path must be a clean relative path (no empty, dot, or parent-dot segments; got ${JSON.stringify(raw)})`,
      );
    }
  }
  return segments.join("/");
}

/** True when `dir` exists and is a directory (stat-based, async). */
async function dirExists(dir: string): Promise<boolean> {
  try {
    const st = await stat(dir);
    return st.isDirectory();
  } catch {
    return false;
  }
}

/**
 * Write a file into the project's durable store (`root/<project_id>/<path>`)
 * and record it in project_files (audit trail). Re-staging the same path
 * overwrites the file and replaces its row (last write wins).
 *
 * 404 when the project does not exist; 400 on an invalid path.
 */
export async function stageFile(
  db: Db,
  opts: { root: string; projectId: number; path: string; content: Buffer; owner?: string },
): Promise<StageFileResult> {
  const { root, projectId, content, owner = "" } = opts;
  const relPath = validateProjectFilePath(opts.path);
  const [project] = await db
    .select({ id: projects.id })
    .from(projects)
    .where(eq(projects.id, projectId))
    .limit(1);
  if (!project) throw new ServiceError(404, `project ${projectId} not found`);

  const projectDir = path.resolve(root, String(projectId));
  const target = path.resolve(projectDir, relPath);
  // Defense in depth: the validated path cannot escape, but verify anyway.
  if (target !== projectDir && !target.startsWith(projectDir + path.sep)) {
    throw new ServiceError(400, "path escapes the project store");
  }
  await mkdir(path.dirname(target), { recursive: true });
  await writeFile(target, content);

  // Replace any prior row for the same (project, path) — last write wins.
  await db
    .delete(projectFiles)
    .where(and(eq(projectFiles.projectId, projectId), eq(projectFiles.path, relPath)));
  await db.insert(projectFiles).values({
    projectId,
    path: relPath,
    size: content.length,
    stagedBy: owner,
    stagedAt: Date.now(),
  });
  return {
    projectId,
    path: relPath,
    containerPath: fileContainerPath(projectId, relPath),
    size: content.length,
  };
}

/** All staged files of a project (audit listing), oldest first. */
export async function listProjectFiles(db: Db, projectId: number): Promise<ProjectFile[]> {
  const rows = await db
    .select()
    .from(projectFiles)
    .where(eq(projectFiles.projectId, projectId))
    .orderBy(asc(projectFiles.stagedAt));
  return rows.map((r) => ({
    projectId: r.projectId,
    path: r.path,
    size: r.size,
    stagedBy: r.stagedBy,
    stagedAt: r.stagedAt,
  }));
}

/**
 * Remove a project's store dir (`root/<project_id>`) + its project_files
 * rows — the immediate GC path for delete_project (no TTL: the project is
 * going away). Returns the dirs removed (empty when the dir did not exist).
 */
export async function removeProjectFiles(db: Db, root: string, projectId: number): Promise<string[]> {
  const dir = path.join(root, String(projectId));
  const removed: string[] = [];
  if (await dirExists(dir)) {
    await rm(dir, { recursive: true, force: true });
    removed.push(dir);
    console.log(`[files] removed project store dir ${dir} (project ${projectId} deleted)`);
  }
  await db.delete(projectFiles).where(eq(projectFiles.projectId, projectId));
  return removed;
}

/**
 * Orphan sweep for the durable store (orchestrator background job, same
 * pattern as cleanupWorkspaces): remove `root/<project_id>` dirs whose
 * project no longer exists in `projects` AND whose dir is older than
 * `ttlMs` (default 30 days). Only numeric-named dirs (project ids) are
 * considered — the store is dedicated to kanban, but the naming check keeps
 * the sweep from touching anything foreign. A safety valve for failed
 * deletions; NEVER touches live projects. Returns what was deleted/kept
 * (tests).
 */
export async function sweepOrphanProjectFiles(
  db: Db,
  root: string,
  opts: { ttlMs: number; now?: () => number },
): Promise<{ deleted: string[]; skipped: string[] }> {
  const deleted: string[] = [];
  const skipped: string[] = [];
  let entries: string[];
  try {
    entries = await readdir(root);
  } catch {
    return { deleted, skipped }; // store root not mounted yet
  }
  const now = opts.now ?? (() => Date.now());
  const nowMs = now();
  for (const name of entries) {
    if (!/^\d+$/.test(name)) continue; // only project-id dirs
    const dir = path.join(root, name);
    let st: Stats;
    try {
      st = await stat(dir);
    } catch {
      continue;
    }
    if (!st.isDirectory()) continue;
    const [project] = await db
      .select({ id: projects.id })
      .from(projects)
      .where(eq(projects.id, Number(name)))
      .limit(1);
    if (project) {
      skipped.push(name); // live project — never touched, any age
      continue;
    }
    if (nowMs - st.mtimeMs <= opts.ttlMs) {
      skipped.push(name); // younger than the TTL
      continue;
    }
    await rm(dir, { recursive: true, force: true });
    deleted.push(name);
    console.log(
      `[files] sweep: removed ${dir} (orphan, age ` +
        `${Math.round((nowMs - st.mtimeMs) / 86_400_000)}d > TTL ${Math.round(opts.ttlMs / 86_400_000)}d)`,
    );
  }
  return { deleted, skipped };
}
