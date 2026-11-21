/**
 * Publish git plumbing (PLAN.md §4 Deploy / §8 publishing): the git
 * operations the deploy handlers use — commit, push, and fresh clones of
 * the blog repo. Auth via GITHUB_TOKEN (https URL rewriting). Shared by all
 * deploy handlers (code / blog / media); tests inject a mock PublishGit.
 */
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const pExecFile = promisify(execFile);

export interface PublishGit {
  /** Current HEAD sha, or null when the repo has no commits. */
  headCommit(dest: string): Promise<string | null>;
  /** Commit all changes; new HEAD sha, or null when there was nothing to commit. */
  commitAll(dest: string, message: string): Promise<string | null>;
  /** Push <branch> to origin (throws on failure). */
  pushBranch(dest: string, branch: string): Promise<void>;
  /** Push the current branch (HEAD) to origin (throws on failure). */
  pushCurrent(dest: string): Promise<void>;
  /** Fresh clone of a repo into dest (dest must not exist). */
  clone(dest: string, repoUrl: string, branch?: string | null): Promise<void>;
}

export interface PublishGitOptions {
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

/** Default PublishGit: shell out to `git` (execFile, no shell). */
export function createPublishGit(opts: PublishGitOptions = {}): PublishGit {
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
    async headCommit(dest) {
      try {
        return await run(dest, ["rev-parse", "HEAD"]);
      } catch {
        return null;
      }
    },
    async commitAll(dest, message) {
      await run(dest, ["add", "-A"]);
      try {
        await run(dest, ["commit", "-m", message]);
      } catch (err) {
        const out = (err as { stdout?: string }).stdout ?? "";
        if (/nothing to commit/i.test(out)) return null;
        throw err;
      }
      return run(dest, ["rev-parse", "HEAD"]);
    },
    async pushBranch(dest, branch) {
      await run(dest, ["push", "origin", branch]);
    },
    async pushCurrent(dest) {
      await run(dest, ["push", "origin", "HEAD"]);
    },
    async clone(dest, repoUrl, branch) {
      const url = authedRepoUrl(repoUrl, opts.token);
      await run(
        dest,
        branch ? ["clone", "--branch", branch, "--single-branch", url, "."] : ["clone", url, "."],
      );
    },
  };
}
