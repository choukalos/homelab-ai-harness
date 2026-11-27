/**
 * merge_task service (item 13 — admin MCP tool, the Q7 single-approval
 * merge gate): merges a DONE code task's pushed branch into the project's
 * default branch with a MERGE commit (not squash/rebase — the task branch's
 * history stays attributable) and pushes the default branch.
 *
 * Eligibility: task state `done` + has a branch + kind `code` + the project
 * has `repo_url` + `default_branch`. Non-done tasks are rejected with a
 * clear message naming the state.
 *
 * Workspace: the task's existing workspace if present (the tasks row keeps
 * the workspace path and it persists after done); otherwise a fresh clone
 * into a temp dir (cleaned up afterwards — never a partial merge).
 *
 * Idempotent: if the task branch is already merged into the default branch
 * (`git merge-base --is-ancestor`), returns `{alreadyMerged: true}` — a
 * no-op, never a failure.
 *
 * Conflict → rejected with a clear message; the merge is aborted, the
 * workspace restored to the task branch, the temp clone (if any) removed,
 * the task stays `done` and the branch stays pushed (chuck resolves
 * manually or restarts the task with a resolution note).
 *
 * Audit: a `merge` task_event (`{branch, defaultBranch, mergeCommit, note,
 * by}`) — also for the already-merged no-op (`mergeCommit: null`) — plus
 * the merge commit message, which carries the task id as the audit link.
 */
import { execFile } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { eq } from "drizzle-orm";
import { ideas, projects, tasks } from "../db/tables.js";
import { ServiceError, type Db } from "./common.js";
import { appendTaskEvent } from "./tasks.js";

const pExecFile = promisify(execFile);

// ---------------------------------------------------------------------------
// Git operations (merge plumbing; tests inject a mock)
// ---------------------------------------------------------------------------

/** Git ops for merge_task (the default implementation shells out to `git`). */
export interface MergeGit {
  /** Fresh clone of repoUrl's `branch` into dest (dest must not exist). */
  clone(dest: string, repoUrl: string, branch: string): Promise<void>;
  /**
   * Fetch one remote branch into its remote-tracking ref
   * (refs/remotes/origin/<branch>) — works even in a --single-branch clone.
   * Throws when the branch is missing on origin.
   */
  fetchBranch(dest: string, branch: string): Promise<void>;
  /** git merge-base --is-ancestor <ancestorRef> <descendantRef>. */
  isAncestor(dest: string, ancestorRef: string, descendantRef: string): Promise<boolean>;
  /** git checkout <ref> (throws on failure, e.g. a dirty tree). */
  checkout(dest: string, ref: string): Promise<void>;
  /** git merge --ff-only <ref> (fast-forward only; throws when diverged). */
  mergeFastForwardOnly(dest: string, ref: string): Promise<void>;
  /** git merge --no-ff <ref> -m <message> (throws on conflict). */
  mergeNoFastForward(dest: string, ref: string, message: string): Promise<void>;
  /** git merge --abort (best effort; no-op when no merge is in progress). */
  abortMerge(dest: string): Promise<void>;
  /** git reset --hard <ref> (discard a local-only merge commit after a failed push). */
  resetHard(dest: string, ref: string): Promise<void>;
  /** git push origin <branch> (throws on failure). */
  pushBranch(dest: string, branch: string): Promise<void>;
  /** git rev-parse HEAD (null when the repo has no commits). */
  headCommit(dest: string): Promise<string | null>;
}

export interface MergeGitOptions {
  /** Auth token for https clones/pushes (GITHUB_TOKEN). */
  token?: string | null;
  /** Commit identity (defaults to ai-kanban <ai-kanban@local>). */
  userName?: string;
  userEmail?: string;
}

/** https://github.com/... → https://x-access-token:<token>@github.com/... */
function authedRepoUrl(url: string, token: string | null | undefined): string {
  if (!token) return url;
  try {
    const u = new URL(url);
    if (u.protocol === "https:") {
      u.username = "x-access-token";
      u.password = token;
      return u.toString();
    }
  } catch {
    // not a URL — use as-is
  }
  return url;
}

/** Default MergeGit: shell out to `git` (execFile, no shell). */
export function createMergeGit(opts: MergeGitOptions = {}): MergeGit {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    GIT_AUTHOR_NAME: opts.userName ?? "ai-kanban",
    GIT_AUTHOR_EMAIL: opts.userEmail ?? "ai-kanban@local",
    GIT_COMMITTER_NAME: opts.userName ?? "ai-kanban",
    GIT_COMMITTER_EMAIL: opts.userEmail ?? "ai-kanban@local",
  };
  const run = async (cwd: string, args: string[]): Promise<string> => {
    const { stdout } = await pExecFile("git", args, {
      cwd,
      env,
      timeout: 300_000,
      maxBuffer: 10 * 1024 * 1024,
    });
    return stdout.trim();
  };
  return {
    async clone(dest, repoUrl, branch) {
      const url = authedRepoUrl(repoUrl, opts.token);
      await run(path.dirname(dest), ["clone", "-q", "--branch", branch, "--single-branch", url, dest]);
    },
    async fetchBranch(dest, branch) {
      // Explicit refspec: updates the remote-tracking ref even in a
      // --single-branch clone (whose default refspec covers one branch only).
      await run(dest, ["fetch", "-q", "origin", `+refs/heads/${branch}:refs/remotes/origin/${branch}`]);
    },
    async isAncestor(dest, ancestorRef, descendantRef) {
      try {
        await run(dest, ["merge-base", "--is-ancestor", ancestorRef, descendantRef]);
        return true;
      } catch {
        return false;
      }
    },
    async checkout(dest, ref) {
      await run(dest, ["checkout", "-q", ref]);
    },
    async mergeFastForwardOnly(dest, ref) {
      await run(dest, ["merge", "--ff-only", ref]);
    },
    async mergeNoFastForward(dest, ref, message) {
      await run(dest, ["merge", "--no-ff", ref, "-m", message]);
    },
    async abortMerge(dest) {
      try {
        await run(dest, ["merge", "--abort"]);
      } catch {
        // no merge in progress (or nothing to abort) — best effort
      }
    },
    async resetHard(dest, ref) {
      await run(dest, ["reset", "--hard", ref]);
    },
    async pushBranch(dest, branch) {
      await run(dest, ["push", "origin", branch]);
    },
    async headCommit(dest) {
      try {
        return await run(dest, ["rev-parse", "HEAD"]);
      } catch {
        return null;
      }
    },
  };
}

// ---------------------------------------------------------------------------
// mergeTask
// ---------------------------------------------------------------------------

/** Truncate idea text for the merge commit subject (~72 chars, one line). */
export function truncateForSubject(text: string, max = 72): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  return `${flat.slice(0, max - 1).trimEnd()}…`;
}

/** First line(s) of a git failure (stderr preferred) for user-facing errors. */
function gitError(err: unknown): string {
  const e = err as { stderr?: unknown; message?: unknown };
  const raw = (typeof e.stderr === "string" && e.stderr.trim()) || (e.message ?? String(err));
  return String(raw)
    .trim()
    .split("\n")
    .slice(0, 3)
    .join(" ");
}

export interface MergeTaskOptions {
  taskId: number;
  /** Optional note recorded in the merge commit + the audit event. */
  note?: string;
  /** Caller identity (MCP key → user name) for the commit + audit trail. */
  by: string;
  /** Git ops (default: real git; tests inject a mock). */
  git?: MergeGit;
  /** Temp dir root for fresh clones (default: os.tmpdir()). */
  tmpRoot?: string;
}

export interface MergeTaskResult {
  taskId: number;
  /** true when a merge commit was created and the default branch pushed. */
  merged: boolean;
  /** true when the branch was already merged (no-op, never a failure). */
  alreadyMerged: boolean;
  branch: string;
  defaultBranch: string;
  /** The merge commit sha (null when alreadyMerged). */
  mergeCommit: string | null;
  note: string | null;
  by: string;
  /** true when a fresh temp clone was used (cleaned up after the merge). */
  freshClone: boolean;
}

/**
 * Merge a done task's branch into the project's default branch (item 13).
 * Throws ServiceError (404 unknown task, 409 eligibility/conflict/push
 * failure) — a rejection never leaves a partial merge behind.
 */
export async function mergeTask(db: Db, opts: MergeTaskOptions): Promise<MergeTaskResult> {
  const { taskId, note, by } = opts;
  const git = opts.git ?? createMergeGit();

  // -- Eligibility ---------------------------------------------------------
  const [task] = await db.select().from(tasks).where(eq(tasks.id, taskId)).limit(1);
  if (!task) throw new ServiceError(404, `task ${taskId} not found`);
  if (task.state !== "done") {
    throw new ServiceError(
      409,
      `task ${taskId} is not done (state: ${task.state}) — merge_task only merges done tasks`,
    );
  }
  if (!task.branch) {
    throw new ServiceError(409, `task ${taskId} has no branch to merge (state: ${task.state})`);
  }
  if (task.spec?.kind !== "code") {
    throw new ServiceError(
      409,
      `task ${taskId} is kind '${task.spec?.kind ?? "unknown"}' — merge_task only merges code tasks (only the code deploy pushes a task branch)`,
    );
  }
  const [project] = await db
    .select()
    .from(projects)
    .where(eq(projects.id, task.projectId))
    .limit(1);
  if (!project?.repoUrl) {
    throw new ServiceError(
      409,
      `project ${project?.name ?? task.projectId} has no repo_url — nothing to merge into`,
    );
  }
  if (!project.defaultBranch) {
    throw new ServiceError(
      409,
      `project ${project.name} has no default_branch — nothing to merge into`,
    );
  }
  const branch = task.branch;
  const defaultBranch = project.defaultBranch;

  // Idea text for the merge commit subject (the task is 1:1 with its idea).
  const [idea] = await db
    .select({ text: ideas.text })
    .from(ideas)
    .where(eq(ideas.id, task.ideaId))
    .limit(1);
  const ideaText = idea?.text ?? task.spec?.goal ?? `task ${taskId}`;

  // -- Workspace: the task's existing one if present, else a fresh clone ----
  let ws = task.workspace;
  let tmpDir: string | null = null;
  if (!ws || !existsSync(path.join(ws, ".git"))) {
    tmpDir = mkdtempSync(path.join(opts.tmpRoot ?? tmpdir(), `ai-kanban-merge-${taskId}-`));
    const cloneDest = path.join(tmpDir, "clone");
    await git.clone(cloneDest, project.repoUrl, defaultBranch);
    ws = cloneDest;
  }
  const freshClone = tmpDir !== null;

  try {
    // Fetch origin's default branch + the task branch (remote-tracking refs).
    await git.fetchBranch(ws, defaultBranch);
    try {
      await git.fetchBranch(ws, branch);
    } catch (err) {
      throw new ServiceError(
        409,
        `task branch '${branch}' not found on origin — the deploy stage may not have pushed it: ${gitError(err)}`,
      );
    }

    // Idempotent: already merged into the default branch → no-op, never a
    // failure (the audit event keeps the call on record, mergeCommit null).
    const alreadyMerged = await git.isAncestor(ws, `origin/${branch}`, `origin/${defaultBranch}`);
    if (alreadyMerged) {
      await appendTaskEvent(db, taskId, "merge", {
        branch,
        defaultBranch,
        mergeCommit: null,
        note: note ?? null,
        by,
      });
      return {
        taskId,
        merged: false,
        alreadyMerged: true,
        branch,
        defaultBranch,
        mergeCommit: null,
        note: note ?? null,
        by,
        freshClone,
      };
    }

    // Merge with a MERGE commit (not squash/rebase) so the task branch's
    // history stays attributable; the task id in the message is the audit
    // link.
    const subject = `merge task/${taskId}: ${truncateForSubject(ideaText)}`;
    const body: string[] = [];
    if (note) body.push(note);
    body.push(`(merged via merge_task by ${by})`);
    const message = `${subject}\n\n${body.join("\n\n")}`;

    // The merge happens on the default branch, fast-forwarded to origin's
    // tip first (the workspace's local default may be behind). A diverged
    // local default is rejected — never merged into a stale base.
    try {
      await git.checkout(ws, defaultBranch);
    } catch (err) {
      throw new ServiceError(
        409,
        `could not check out '${defaultBranch}' in the workspace (uncommitted changes?): ${gitError(err)}`,
      );
    }
    try {
      await git.mergeFastForwardOnly(ws, `origin/${defaultBranch}`);
    } catch (err) {
      await git.checkout(ws, branch).catch(() => {});
      throw new ServiceError(
        409,
        `local '${defaultBranch}' in the workspace has diverged from origin — nothing was merged (reset the workspace or use a fresh clone): ${gitError(err)}`,
      );
    }

    let mergeCommit: string;
    try {
      await git.mergeNoFastForward(ws, `origin/${branch}`, message);
      mergeCommit = (await git.headCommit(ws)) ?? "";
    } catch (err) {
      // Conflict (or any merge failure): abort + restore the task branch —
      // nothing partial; the task stays done and the branch stays pushed.
      await git.abortMerge(ws);
      await git.checkout(ws, branch).catch(() => {});
      throw new ServiceError(
        409,
        `merge conflict merging '${branch}' into '${defaultBranch}' — nothing was merged (the task stays done and the branch stays pushed; resolve the conflict manually or restart the task with a resolution note): ${gitError(err)}`,
      );
    }

    // Push the default branch; a failed push must not leave a local-only
    // merge commit behind (reset back to origin's tip + restore the branch).
    try {
      await git.pushBranch(ws, defaultBranch);
    } catch (err) {
      await git.resetHard(ws, `origin/${defaultBranch}`).catch(() => {});
      await git.checkout(ws, branch).catch(() => {});
      throw new ServiceError(
        409,
        `push of '${defaultBranch}' failed after the local merge — the local merge commit was discarded (nothing partial): ${gitError(err)}`,
      );
    }

    // Restore the workspace to the task branch (least surprise; the merge
    // commit is safe on origin).
    await git.checkout(ws, branch).catch(() => {});

    // Audit: a `merge` task_event (machine-readable record of the gate).
    await appendTaskEvent(db, taskId, "merge", {
      branch,
      defaultBranch,
      mergeCommit,
      note: note ?? null,
      by,
    });

    return {
      taskId,
      merged: true,
      alreadyMerged: false,
      branch,
      defaultBranch,
      mergeCommit,
      note: note ?? null,
      by,
      freshClone,
    };
  } finally {
    // Clean up the temp clone (fresh-clone path only; the task's own
    // workspace is kept — it persists after done).
    if (tmpDir) rmSync(tmpDir, { recursive: true, force: true });
  }
}
