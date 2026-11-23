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
import { checkRef, isHttpUrl, MEDIA_STORE_MOUNT, rootForPath, type FetchLike } from "./reachability.js";

/** Container mount of the durable store (compose: /files). */
export const FILES_MOUNT = "/files";
/** Orphan-sweep TTL default (days) — safety valve only, never for live projects. */
export const FILES_ORPHAN_TTL_DAYS = 30;
/** Max staged file path length (matches the project_files.path column). */
export const MAX_FILE_PATH_LENGTH = 512;
/** stage_file content cap (~100 MB — small inputs only; media goes via stage_ref). */
export const MAX_STAGED_FILE_BYTES = 100 * 1024 * 1024;

/** Base64 alphabet (padding optional — Buffer.from accepts unpadded input). */
const BASE64_RE = /^[A-Za-z0-9+/]+={0,2}$/;

export interface ProjectFile {
  projectId: number;
  /** Project-store-relative path (validated). */
  path: string;
  size: number;
  /** Caller identity that staged the file; '' = unattributed. */
  stagedBy: string;
  stagedAt: number;
}

/**
 * Decode a base64 file payload (stage_file `content`) and enforce the
 * stage_file size cap. 400 on non-base64 input or an oversized file.
 */
export function decodeStagedContent(b64: string, maxBytes: number = MAX_STAGED_FILE_BYTES): Buffer {
  if (typeof b64 !== "string" || b64.trim() === "") {
    throw new ServiceError(400, "content is required (base64-encoded file bytes)");
  }
  const s = b64.trim();
  if (!BASE64_RE.test(s)) {
    throw new ServiceError(400, "content must be base64-encoded");
  }
  const buf = Buffer.from(s, "base64");
  if (buf.length > maxBytes) {
    throw new ServiceError(
      400,
      `file is ${buf.length} bytes — stage_file accepts at most ${maxBytes} bytes (~100 MB); ` +
        "larger media inputs go on the NAS/public drop and are registered with stage_ref",
    );
  }
  return buf;
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

/** Result of an external-reference registration (stage_ref). */
export interface StageRefResult {
  projectId: number;
  /** The registered reference (http(s) URL or NAS path under the media store). */
  ref: string;
  kind: "url" | "path";
  /** Always true — unreachable references are rejected at registration. */
  reachable: boolean;
}

/**
 * Register an external media reference for a project WITHOUT moving content
 * (stage_ref): an http(s) URL (validated with a bounded HTTP HEAD → 200) or
 * a NAS path under the media store mount (validated by existence). The
 * reference is recorded in project_files (size 0 — no content lands in the
 * durable store) so the preflight + audit trail have a machine-checkable
 * record. Re-registering the same reference replaces its row (last write
 * wins). 404 unknown project; 400 unreachable reference, non-NAS path, or
 * oversized ref.
 */
export async function stageRef(
  db: Db,
  opts: {
    projectId: number;
    ref: string;
    owner?: string;
    /** Media store mount root (default /media-store). */
    mediaStoreRoot?: string;
    fetchImpl?: FetchLike;
    timeoutMs?: number;
  },
): Promise<StageRefResult> {
  const { projectId, owner = "" } = opts;
  const ref = (opts.ref ?? "").trim();
  if (ref === "") {
    throw new ServiceError(400, "ref is required (http(s) URL or NAS path under the media store)");
  }
  if (ref.length > MAX_FILE_PATH_LENGTH) {
    throw new ServiceError(400, `ref must be at most ${MAX_FILE_PATH_LENGTH} characters`);
  }
  const [project] = await db
    .select({ id: projects.id })
    .from(projects)
    .where(eq(projects.id, projectId))
    .limit(1);
  if (!project) throw new ServiceError(404, `project ${projectId} not found`);

  const mediaStoreRoot = opts.mediaStoreRoot ?? MEDIA_STORE_MOUNT;
  // A stage_ref path must be a NAS reference under the media store mount —
  // everything else is either a URL (checked below) or a store file (use
  // stage_file) or a client/host path (unreachable by construction).
  if (!isHttpUrl(ref) && rootForPath(ref, [mediaStoreRoot]) === null) {
    throw new ServiceError(
      400,
      `stage_ref accepts an http(s) URL or a NAS path under the media store (${mediaStoreRoot}); ` +
        `small files are pushed with stage_file (got ${JSON.stringify(ref)})`,
    );
  }
  const check = await checkRef(ref, {
    roots: [mediaStoreRoot],
    fetchImpl: opts.fetchImpl,
    timeoutMs: opts.timeoutMs,
  });
  if (!check.reachable) {
    throw new ServiceError(400, `reference is not reachable: ${check.reason}`);
  }

  // Replace any prior row for the same (project, ref) — last write wins.
  await db
    .delete(projectFiles)
    .where(and(eq(projectFiles.projectId, projectId), eq(projectFiles.path, ref)));
  await db.insert(projectFiles).values({
    projectId,
    path: ref,
    size: 0, // metadata-only registration — no content in the store
    stagedBy: owner,
    stagedAt: Date.now(),
  });
  return { projectId, ref, kind: check.kind, reachable: true };
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
