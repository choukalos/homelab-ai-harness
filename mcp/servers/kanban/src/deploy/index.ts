/**
 * Deploy stage (PLAN.md §4/§8, Slice 3b): automated publishing after QA
 * pass — no human gate. Routed by task `kind`:
 *   code  → commit + push the task branch (GitHub; no PRs)
 *   blog  → commit + push a markdown post at <blog_content_path>/<date>-<slug>.md
 *   media → publish media files to one of the project's media_paths
 *   other → no-op
 * Failure → needs_attention (retryable via retry_deploy, Slice 5 surface).
 */
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync, type Stats } from "node:fs";
import path from "node:path";
import type { IdeaSpec, TaskKind } from "../db/schema.js";
import { createPublishGit, type PublishGit } from "../publish/git.js";

/** Everything a deploy handler needs to know. */
export interface DeployContext {
  taskId: number;
  kind: TaskKind;
  spec: IdeaSpec;
  project: {
    name: string;
    repoUrl: string | null;
    defaultBranch: string | null;
    blogRepoUrl: string | null;
    blogContentPath: string | null;
    mediaPaths: string[] | null;
  };
  /** Task workspace (/workspace/task-<id>). */
  workspace: string;
  /** App-side agent workspace root (scratch dirs under it are never publish targets). */
  workspaceRoot?: string;
  /** Task branch (task/<id>). */
  branch: string;
  lastCommit: string | null;
}

/** What the deploy did (deploy task_event + the summary session). */
export interface DeployResult {
  /** One-line description of what was published. */
  published: string;
  /** Target (branch / blog path / media dir / none). */
  target: string;
}

export type DeployHandler = (ctx: DeployContext, git: PublishGit) => Promise<DeployResult>;

/** "Add a dark mode" → "add-a-dark-mode" (blog post slug). */
export function slugify(text: string, max = 60): string {
  const slug = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, max)
    .replace(/-+$/g, "");
  return slug || "post";
}

/** Today as YYYY-MM-DD (UTC) — blog post date prefix. */
export function postDate(now = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/**
 * Extract the machine path from a (possibly free-text) publish-target entry.
 *
 * Grooming-authored specs often embed the path in prose ("NAS 'media' share
 * (mandatory): /media-store/x/ — file.mp4 + state.json"); the deploy stage
 * needs the path itself. A clean path (no surrounding whitespace — absolute
 * or relative) is used as-is; free text yields the first absolute path after
 * stripping URLs (a URL's path component, e.g. /files/x.mp4 in
 * choukalos.com/files/x.mp4, is NOT a container path); prose with no usable
 * path yields null (the entry is skipped, never guessed).
 */
export function extractTargetPath(entry: string): string | null {
  const t = entry.trim();
  if (!t) return null;
  if (!/\s/.test(t)) return t;
  const noUrls = t.replace(/https?:\/\/\S+/g, " ");
  const m = /\/[A-Za-z0-9._+~-]+(?:\/[A-Za-z0-9._+~-]+)*\/?/.exec(noUrls);
  return m ? m[0] : null;
}

// ---------------------------------------------------------------------------
// Handlers per kind
// ---------------------------------------------------------------------------

/** code: safety-net commit, then push the task branch (no PRs). */
export const deployCode: DeployHandler = async (ctx, git) => {
  await git.commitAll(ctx.workspace, `task ${ctx.taskId}: final checkpoint before deploy`);
  if (!ctx.project.repoUrl) {
    // Scratch project (no repo): work is committed on the local task branch.
    return {
      published: "no repo configured — work committed locally",
      target: `branch ${ctx.branch} (local)`,
    };
  }
  await git.pushBranch(ctx.workspace, ctx.branch);
  return {
    published: `pushed branch ${ctx.branch}`,
    target: `${ctx.project.repoUrl} (branch ${ctx.branch})`,
  };
};

/** blog: publish the post at <blog_content_path>/<date>-<slug>.md. */
export const deployBlog: DeployHandler = async (ctx, git) => {
  if (!ctx.project.blogRepoUrl) {
    throw new Error("deploy failed: project has no blog_repo_url");
  }
  const contentPath = ctx.project.blogContentPath ?? "";
  const postPath = ctx.spec.publish_targets?.[0] ?? "post.md";
  const src = path.join(ctx.workspace, postPath);
  if (!existsSync(src)) {
    throw new Error(`deploy failed: blog post not found at ${src}`);
  }
  const body = readFileSync(src, "utf8");
  const date = postDate();
  const slug = slugify(ctx.spec.goal);
  const fileName = `${date}-${slug}.md`;

  const cloneDir = path.join(ctx.workspace, `../publish-blog-${ctx.taskId}`);
  rmSync(cloneDir, { recursive: true, force: true });
  mkdirSync(cloneDir, { recursive: true });
  await git.clone(cloneDir, ctx.project.blogRepoUrl, ctx.project.defaultBranch);
  const destDir = path.join(cloneDir, contentPath);
  mkdirSync(destDir, { recursive: true });
  writeFileSync(path.join(destDir, fileName), body);
  const commit = await git.commitAll(cloneDir, `task ${ctx.taskId}: publish blog post ${fileName}`);
  if (!commit) throw new Error(`deploy failed: blog post ${fileName} was not written`);
  await git.pushCurrent(cloneDir);
  return {
    published: `published blog post ${fileName}`,
    target: `${ctx.project.blogRepoUrl} → ${contentPath}/${fileName}`,
  };
};

/**
 * media: publish the task's media/ output to the target.
 *   - absolute target path → local directory on the host: copy, no git
 *     (includes the blog public drop, /publish/... in the kanban container)
 *   - relative target path → subdirectory of the blog repo: clone, copy,
 *     commit, push (requires blog_repo_url)
 * publish_targets entries are grooming-authored and may be free text —
 * extractTargetPath pulls the machine path out of each; entries with no
 * usable path are skipped (2026-11-23: a prose entry crashed the stage with
 * "project has no blog_repo_url" after the task had already published).
 *
 * Idempotent: media tasks (media-film P7) often self-publish directly to
 * the target and the QA gate verifies the published output. If the
 * workspace media/ has no files but the (local) target is already
 * populated, the deploy is a verified no-op — not a failure (2026-11-23
 * task 2: draft published to NAS + blog, stage failed with "media is
 * empty" and parked the task in needs_attention).
 */
export const deployMedia: DeployHandler = async (ctx, git) => {
  // Pick the first publish target that is a real output location: absolute
  // paths under the agent workspace root are scratch (groom-<id>/task-<id>)
  // and are skipped, falling back to the project's media_paths.
  const root = ctx.workspaceRoot ? path.resolve(ctx.workspaceRoot) : null;
  const isScratch = (t: string): boolean => {
    if (!root || !path.isAbsolute(t)) return false;
    const p = path.resolve(t);
    return p === root || p.startsWith(root + path.sep);
  };
  const candidates = (ctx.spec.publish_targets ?? [])
    .map((t) => (t ? extractTargetPath(t) : null))
    .filter((t): t is string => t !== null && !isScratch(t));
  const targetPath = candidates[0] ?? ctx.project.mediaPaths?.[0];
  if (!targetPath) {
    throw new Error("deploy failed: no media path (spec publish_targets or project media_paths)");
  }
  const src = path.join(ctx.workspace, "media");
  const files = existsSync(src) ? listFiles(src) : [];
  if (files.length === 0) {
    // The task self-published (media-film P7) and QA verified the output:
    // a populated local target makes the deploy a verified no-op.
    const verified = alreadyPublished(targetPath);
    if (verified !== null) {
      return {
        published: `already published at ${targetPath} (task self-published; ${verified} file(s) verified at target)`,
        target: targetPath,
      };
    }
    if (!path.isAbsolute(targetPath)) {
      // Blog-repo subdir: cannot be verified from this container.
      throw new Error(`deploy failed: no media files at ${src}`);
    }
    throw new Error(
      `deploy failed: no media files at ${src} and target ${targetPath} is not populated`,
    );
  }

  // Local (absolute) target. A target with a file extension is an exact
  // file destination (one image per task per project constraints); a bare
  // directory receives the whole media/ tree.
  if (path.isAbsolute(targetPath)) {
    if (path.extname(targetPath) !== "") {
      const single = files[0];
      if (files.length !== 1 || single === undefined) {
        throw new Error(
          `deploy failed: target ${targetPath} is a file but the task produced ${files.length} media files`,
        );
      }
      mkdirSync(path.dirname(targetPath), { recursive: true });
      cpSync(path.join(src, single), targetPath);
      return {
        published: `published ${files[0]} to ${targetPath}`,
        target: targetPath,
      };
    }
    mkdirSync(targetPath, { recursive: true });
    cpSync(src, targetPath, { recursive: true });
    return {
      published: `published ${files.length} media file(s) to ${targetPath}`,
      target: targetPath,
    };
  }

  if (!ctx.project.blogRepoUrl) {
    throw new Error("deploy failed: project has no blog_repo_url");
  }
  const cloneDir = path.join(ctx.workspace, `../publish-media-${ctx.taskId}`);
  rmSync(cloneDir, { recursive: true, force: true });
  mkdirSync(cloneDir, { recursive: true });
  await git.clone(cloneDir, ctx.project.blogRepoUrl, ctx.project.defaultBranch);
  const destDir = path.join(cloneDir, targetPath);
  mkdirSync(destDir, { recursive: true });
  cpSync(src, destDir, { recursive: true });
  const commit = await git.commitAll(cloneDir, `task ${ctx.taskId}: publish media to ${targetPath}`);
  if (!commit) throw new Error(`deploy failed: no media changes to commit in ${targetPath}`);
  await git.pushCurrent(cloneDir);
  return {
    published: `published ${files.length} media file(s) to ${targetPath}`,
    target: `${ctx.project.blogRepoUrl} → ${targetPath}`,
  };
};

/** other: no publishing. */
export const deployOther: DeployHandler = async (ctx) => ({
  published: "no-op (kind: other)",
  target: "none",
});

/** Route a deploy by task kind. */
export function handlerForKind(kind: TaskKind): DeployHandler {
  switch (kind) {
    case "code":
      return deployCode;
    case "blog":
      return deployBlog;
    case "media":
      return deployMedia;
    default:
      return deployOther;
  }
}

/**
 * Verify a LOCAL (absolute) target already contains published output:
 * a file target must exist with size > 0; a directory target must exist
 * and contain at least one file (recursive). Returns the file count, or
 * null when the target is absent/empty or cannot be verified (relative
 * targets are blog-repo subdirs — not on this filesystem).
 */
function alreadyPublished(targetPath: string): number | null {
  if (!path.isAbsolute(targetPath)) return null;
  let st: Stats;
  try {
    st = statSync(targetPath);
  } catch {
    return null;
  }
  if (path.extname(targetPath) !== "") {
    return st.isFile() && st.size > 0 ? 1 : null;
  }
  if (!st.isDirectory()) return null;
  const n = listFiles(targetPath).length;
  return n > 0 ? n : null;
}

/** All files under a dir, relative to it (recursive). */
function listFiles(dir: string): string[] {
  const out: string[] = [];
  const walk = (d: string) => {
    for (const entry of readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, entry.name);
      if (entry.isDirectory()) walk(p);
      else out.push(path.relative(dir, p));
    }
  };
  walk(dir);
  return out;
}

// ---------------------------------------------------------------------------
// Runner
// ---------------------------------------------------------------------------

export interface DeployRunnerOptions {
  /** Git plumbing (default: real git via execFile). */
  git?: PublishGit;
  /** GITHUB_TOKEN for authenticated clones/pushes. */
  token?: string | null;
}

/**
 * The deploy stage: route by kind, run the handler, clean up temp publish
 * clones. Throws on failure (the orchestrator lands the task in
 * needs_attention).
 */
export class DeployRunner {
  private readonly git: PublishGit;

  constructor(opts: DeployRunnerOptions = {}) {
    this.git = opts.git ?? createPublishGit({ token: opts.token });
  }

  /** Run the deploy for one task (returns what was published). */
  async deploy(ctx: DeployContext): Promise<DeployResult> {
    const handler = handlerForKind(ctx.kind);
    return handler(ctx, this.git);
  }
}
