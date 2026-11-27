/**
 * merge_task service tests (item 13 — admin MCP tool): eligibility gates
 * (done vs running, branch, kind, repo_url/default_branch), the merge commit
 * + push over REAL temp git repos (local-path origin), the already-merged
 * no-op, conflict rejection (nothing partial, task stays done, temp clone
 * cleaned up), the existing-workspace path, the `merge` task_event audit
 * trail, and the MCP admin capability gate (non-admin keys rejected).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { and, eq } from "drizzle-orm";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import type { KanbanConfig } from "../config.js";
import { initDb } from "../db/index.js";
import { ideas, projects, taskEvents, tasks, type IdeaSpec } from "../db/schema.js";
import {
  createKanbanMcpServer,
  MCP_TOOL_NAMES,
  parseMcpKeyCapabilities,
  resolveMcpCapabilities,
} from "../mcp/server.js";
import { createKanbanServices, type KanbanServices } from "./index.js";
import { ServiceError } from "./common.js";
import { createMergeGit, truncateForSubject } from "./merge-task.js";

const pExecFile = promisify(execFile);

/** Run a git command (test identity; local repos only — no network). */
async function git(cwd: string, ...args: string[]): Promise<string> {
  const { stdout } = await pExecFile("git", args, {
    cwd,
    env: {
      ...process.env,
      GIT_AUTHOR_NAME: "test",
      GIT_AUTHOR_EMAIL: "test@test",
      GIT_COMMITTER_NAME: "test",
      GIT_COMMITTER_EMAIL: "test@test",
    },
  });
  return stdout.trim();
}

/** A real origin repo: `main` with one commit (the merge target). */
async function makeOrigin(dir: string): Promise<string> {
  const origin = path.join(dir, "origin");
  mkdirSync(origin, { recursive: true });
  await git(origin, "init", "-q", "-b", "main");
  // Non-bare origin (tests commit directly into it): allow pushes to the
  // checked-out branch (GitHub's real origin has no such restriction).
  await git(origin, "config", "receive.denyCurrentBranch", "updateInstead");
  writeFileSync(path.join(origin, "README.md"), "# origin\n");
  await git(origin, "add", "-A");
  await git(origin, "commit", "-qm", "initial");
  return origin;
}

/** Create + push a task branch off main (the deploy stage's shape). */
async function pushTaskBranch(origin: string, branch: string, file: string, content: string): Promise<void> {
  const work = path.join(origin, `work-${branch.replace("/", "_")}`);
  await git(origin, "clone", "-q", "--branch", "main", origin, work);
  await git(work, "checkout", "-qb", branch);
  mkdirSync(path.dirname(path.join(work, file)), { recursive: true });
  writeFileSync(path.join(work, file), content);
  await git(work, "add", "-A");
  await git(work, "commit", "-qm", `work on ${branch}`);
  await git(work, "push", "-q", "origin", branch);
  rmSync(work, { recursive: true, force: true });
}

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
    ownerModels: {},
    ownerModelCosts: {},
    workspaceCleanupDays: 7,
    server: { bindAddr: "127.0.0.1", port: 3000 },
  };
}

interface SeedOpts {
  state?: string;
  branch?: string | null;
  kind?: IdeaSpec["kind"];
  repoUrl?: string | null;
  defaultBranch?: string | null;
  workspace?: string | null;
  ideaText?: string;
}

/** Seed a project + moved idea + task row (the merge_task inputs). */
async function seedTask(
  q: BetterSQLite3Database<any>,
  opts: SeedOpts = {},
): Promise<{ projectId: number; taskId: number }> {
  const {
    state = "done",
    branch = "task/7",
    kind = "code",
    repoUrl = "https://example.com/repo",
    defaultBranch = "main",
    workspace = null,
    ideaText = "Add a dark mode toggle to the settings page",
  } = opts;
  const now = Date.now();
  const spec: IdeaSpec = { goal: "g", steps: ["s1"], acceptance: ["a1"], kind };
  const [project] = (await q
    .insert(projects)
    .values({ name: `Alpha-${now}-${Math.random().toString(36).slice(2, 8)}`, repoUrl, defaultBranch, createdAt: now, updatedAt: now })
    .returning()) as [typeof projects.$inferSelect];
  const [idea] = (await q
    .insert(ideas)
    .values({ projectId: project.id, text: ideaText, state: "moved", spec, createdAt: now, updatedAt: now })
    .returning()) as [typeof ideas.$inferSelect];
  const [task] = (await q
    .insert(tasks)
    .values({
      ideaId: idea.id,
      projectId: project.id,
      spec,
      state,
      stateChangedAt: now,
      branch,
      workspace,
      createdAt: now,
    })
    .returning()) as [typeof tasks.$inferSelect];
  return { projectId: project.id, taskId: task.id };
}

async function setup(): Promise<{
  services: KanbanServices;
  q: BetterSQLite3Database<any>;
  dir: string;
  tmpRoot: string;
}> {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-merge-"));
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const tmpRoot = path.join(dir, "merge-tmp");
  mkdirSync(tmpRoot, { recursive: true });
  const services = createKanbanServices(db, {
    mergeGit: createMergeGit(),
    mergeTmpRoot: tmpRoot,
  });
  return { services, q: db.db as unknown as BetterSQLite3Database<any>, dir, tmpRoot };
}

function isServiceError(err: unknown, status: number, re: RegExp): boolean {
  assert.ok(err instanceof ServiceError, `expected ServiceError, got: ${err}`);
  assert.equal(err.status, status, `expected status ${status}, got ${err.status}: ${err.message}`);
  assert.match(err.message, re, `expected /${re}/ in: ${err.message}`);
  return true;
}

/** The `merge` task_event rows for a task. */
async function mergeEvents(q: BetterSQLite3Database<any>, taskId: number) {
  return q
    .select()
    .from(taskEvents)
    .where(and(eq(taskEvents.taskId, taskId), eq(taskEvents.type, "merge")));
}

// ---------------------------------------------------------------------------
// Eligibility
// ---------------------------------------------------------------------------

test("merge_task: running task rejected with the state named", async () => {
  const { services, q } = await setup();
  const { taskId } = await seedTask(q, { state: "running" });
  await assert.rejects(services.mergeTask(taskId, undefined, "chuck"), (err: unknown) =>
    isServiceError(err, 409, /not done \(state: running\)/),
  );
});

test("merge_task: needs_attention task rejected with the state named", async () => {
  const { services, q } = await setup();
  const { taskId } = await seedTask(q, { state: "needs_attention" });
  await assert.rejects(services.mergeTask(taskId, undefined, "chuck"), (err: unknown) =>
    isServiceError(err, 409, /not done \(state: needs_attention\)/),
  );
});

test("merge_task: done task without a branch rejected", async () => {
  const { services, q } = await setup();
  const { taskId } = await seedTask(q, { branch: null });
  await assert.rejects(services.mergeTask(taskId, undefined, "chuck"), (err: unknown) =>
    isServiceError(err, 409, /no branch/),
  );
});

test("merge_task: non-code kind rejected (no task branch was pushed)", async () => {
  const { services, q } = await setup();
  const { taskId } = await seedTask(q, { kind: "blog" });
  await assert.rejects(services.mergeTask(taskId, undefined, "chuck"), (err: unknown) =>
    isServiceError(err, 409, /kind 'blog'/),
  );
});

test("merge_task: project without repo_url / default_branch rejected", async () => {
  const { services, q } = await setup();
  const noRepo = await seedTask(q, { repoUrl: null });
  await assert.rejects(services.mergeTask(noRepo.taskId, undefined, "chuck"), (err: unknown) =>
    isServiceError(err, 409, /no repo_url/),
  );
  const noBranch = await seedTask(q, { defaultBranch: null });
  await assert.rejects(services.mergeTask(noBranch.taskId, undefined, "chuck"), (err: unknown) =>
    isServiceError(err, 409, /no default_branch/),
  );
});

test("merge_task: unknown task → 404", async () => {
  const { services } = await setup();
  await assert.rejects(services.mergeTask(999, undefined, "chuck"), (err: unknown) =>
    isServiceError(err, 404, /task 999 not found/),
  );
});

// ---------------------------------------------------------------------------
// Merge commit + push (real temp git repos, fresh clone)
// ---------------------------------------------------------------------------

test("merge_task: merge commit + push (fresh clone), audit event, temp cleanup", async () => {
  const { services, q, dir, tmpRoot } = await setup();
  const origin = await makeOrigin(dir);
  await pushTaskBranch(origin, "task/7", "docs/added.md", "task work\n");
  const { taskId } = await seedTask(q, { repoUrl: origin, ideaText: "Add a dark mode toggle to the settings page" });

  const result = await services.mergeTask(taskId, "verified the diff", "chuck");

  // Result shape.
  assert.equal(result.merged, true);
  assert.equal(result.alreadyMerged, false);
  assert.equal(result.freshClone, true);
  assert.equal(result.branch, "task/7");
  assert.equal(result.defaultBranch, "main");
  assert.equal(result.note, "verified the diff");
  assert.equal(result.by, "chuck");
  assert.match(result.mergeCommit ?? "", /^[0-9a-f]{40}$/);

  // The default branch on origin now ends at the merge commit.
  assert.equal(await git(origin, "rev-parse", "refs/heads/main"), result.mergeCommit);

  // It is a real MERGE commit (two parents), not a fast-forward/squash.
  const parents = (await git(origin, "log", "-1", "--format=%P", result.mergeCommit!)).split(" ");
  assert.equal(parents.length, 2, "merge commit has exactly two parents");

  // Commit message: subject + note + attribution.
  const subject = await git(origin, "log", "-1", "--format=%s", result.mergeCommit!);
  assert.equal(subject, `merge task/${taskId}: Add a dark mode toggle to the settings page`);
  const body = await git(origin, "log", "-1", "--format=%b", result.mergeCommit!);
  assert.match(body, /verified the diff/);
  assert.match(body, /\(merged via merge_task by chuck\)/);

  // The task branch's work is on main.
  assert.equal(await git(origin, "show", "main:docs/added.md"), "task work");

  // Audit: one `merge` task_event with the full payload.
  const events = await mergeEvents(q, taskId);
  assert.equal(events.length, 1);
  assert.deepEqual(events[0]!.payload, {
    branch: "task/7",
    defaultBranch: "main",
    mergeCommit: result.mergeCommit,
    note: "verified the diff",
    by: "chuck",
  });

  // The temp clone is cleaned up.
  assert.deepEqual(readdirSync(tmpRoot), [], "temp clone dir removed");
});

test("merge_task: long idea text truncated to ~72 chars in the subject", async () => {
  const { services, q, dir } = await setup();
  const origin = await makeOrigin(dir);
  await pushTaskBranch(origin, "task/8", "x.md", "x\n");
  const longText = "A very long idea title that goes on and on and on and on and on and on and on";
  const { taskId } = await seedTask(q, { branch: "task/8", repoUrl: origin, ideaText: longText });

  const result = await services.mergeTask(taskId, undefined, "chuck");
  assert.equal(result.merged, true);
  const subject = await git(origin, "log", "-1", "--format=%s", result.mergeCommit!);
  assert.equal(subject, `merge task/${taskId}: ${truncateForSubject(longText)}`);
  assert.ok(subject.length <= `merge task/${taskId}: `.length + 72, "subject stays ~72 chars of idea text");
  assert.match(subject, /…$/);
  // No note → attribution line only in the body.
  const body = await git(origin, "log", "-1", "--format=%b", result.mergeCommit!);
  assert.equal(body.trim(), "(merged via merge_task by chuck)");
});

// ---------------------------------------------------------------------------
// Idempotency (already merged → no-op, never a failure)
// ---------------------------------------------------------------------------

test("merge_task: already-merged branch → {alreadyMerged: true} no-op, never a failure", async () => {
  const { services, q, dir } = await setup();
  const origin = await makeOrigin(dir);
  await pushTaskBranch(origin, "task/7", "docs/added.md", "task work\n");
  const { taskId } = await seedTask(q, { repoUrl: origin });

  const first = await services.mergeTask(taskId, "first pass", "chuck");
  assert.equal(first.merged, true);

  // Second call: the branch is already merged into main.
  const mainBefore = await git(origin, "rev-parse", "refs/heads/main");
  const second = await services.mergeTask(taskId, "second pass", "chuck");
  assert.equal(second.alreadyMerged, true);
  assert.equal(second.merged, false);
  assert.equal(second.mergeCommit, null);
  assert.equal(await git(origin, "rev-parse", "refs/heads/main"), mainBefore, "main untouched");

  // The no-op is audited too (mergeCommit null).
  const events = await mergeEvents(q, taskId);
  assert.equal(events.length, 2);
  assert.deepEqual(events[1]!.payload, {
    branch: "task/7",
    defaultBranch: "main",
    mergeCommit: null,
    note: "second pass",
    by: "chuck",
  });
});

// ---------------------------------------------------------------------------
// Conflict → clear rejection, nothing partial
// ---------------------------------------------------------------------------

test("merge_task: conflict → rejected, nothing partial, task stays done, temp cleaned", async () => {
  const { services, q, dir, tmpRoot } = await setup();
  const origin = await makeOrigin(dir);
  // A real conflict: both sides edit the same file from the SAME base.
  writeFileSync(path.join(origin, "shared.md"), "base\n");
  await git(origin, "add", "-A");
  await git(origin, "commit", "-qm", "base shared.md");
  // The task branch diverges from the base...
  await pushTaskBranch(origin, "task/7", "shared.md", "task version\n");
  // ...and main diverges from the base with a conflicting edit.
  writeFileSync(path.join(origin, "shared.md"), "main version\n");
  await git(origin, "add", "-A");
  await git(origin, "commit", "-qm", "main edits shared.md");
  const mainBefore = await git(origin, "rev-parse", "refs/heads/main");
  const { taskId } = await seedTask(q, { repoUrl: origin });

  await assert.rejects(services.mergeTask(taskId, undefined, "chuck"), (err: unknown) =>
    isServiceError(err, 409, /merge conflict merging 'task\/7' into 'main'/),
  );

  // Nothing partial: origin's main is untouched (still the pre-merge tip).
  assert.equal(await git(origin, "rev-parse", "refs/heads/main"), mainBefore);
  assert.equal(await git(origin, "show", "main:shared.md"), "main version");

  // The task stays done.
  const [task] = await q.select().from(tasks).where(eq(tasks.id, taskId));
  assert.equal(task!.state, "done");

  // No merge audit event (nothing was merged).
  assert.equal((await mergeEvents(q, taskId)).length, 0);

  // The temp clone is cleaned up.
  assert.deepEqual(readdirSync(tmpRoot), [], "temp clone dir removed");
});

// ---------------------------------------------------------------------------
// Existing workspace (persists after done)
// ---------------------------------------------------------------------------

test("merge_task: uses the task's existing workspace when present (kept, restored to task branch)", async () => {
  const { services, q, dir } = await setup();
  const origin = await makeOrigin(dir);
  await pushTaskBranch(origin, "task/9", "docs/ws.md", "ws work\n");
  // The task workspace: a clone of origin on the task branch (persists after done).
  const ws = path.join(dir, "workspace", "task-9");
  await git(origin, "clone", "-q", origin, ws);
  await git(ws, "checkout", "-q", "task/9");
  const { taskId } = await seedTask(q, { branch: "task/9", repoUrl: origin, workspace: ws });

  const result = await services.mergeTask(taskId, undefined, "chuck");
  assert.equal(result.merged, true);
  assert.equal(result.freshClone, false);

  // The merge landed on origin's main.
  assert.equal(await git(origin, "rev-parse", "refs/heads/main"), result.mergeCommit);
  assert.equal(await git(origin, "show", "main:docs/ws.md"), "ws work");

  // The workspace is kept (not deleted) and restored to the task branch.
  assert.ok(existsSync(path.join(ws, ".git")), "workspace kept");
  assert.equal(await git(ws, "rev-parse", "--abbrev-ref", "HEAD"), "task/9");
  // And it is clean (no partial merge state left behind).
  assert.equal(await git(ws, "status", "--porcelain"), "");
});

// ---------------------------------------------------------------------------
// truncateForSubject
// ---------------------------------------------------------------------------

test("truncateForSubject: short text as-is, long text ~72 chars + ellipsis, whitespace flattened", () => {
  assert.equal(truncateForSubject("Short idea"), "Short idea");
  assert.equal(truncateForSubject("x".repeat(72)), "x".repeat(72));
  const out = truncateForSubject("word ".repeat(30).trim());
  assert.ok(out.length <= 72);
  assert.match(out, /…$/);
  assert.equal(truncateForSubject("  a\n\nb  c "), "a b c");
});

// ---------------------------------------------------------------------------
// MCP admin capability gate (the agents_switch pattern)
// ---------------------------------------------------------------------------

test("merge_task: capability sets — admin (and the kanban key) include it, control/read do not", () => {
  // The kanban key always gets the full tool set.
  const kanban = resolveMcpCapabilities("sk-kanban", "sk-kanban");
  assert.ok(kanban!.has("merge_task"));
  assert.ok(MCP_TOOL_NAMES.includes("merge_task"));

  // A control-scoped key does NOT get merge_task (same gate as agents_switch).
  const controlMap = parseMcpKeyCapabilities("usersuffix1:control");
  const control = resolveMcpCapabilities("sk-usersuffix1", "sk-kanban", controlMap);
  assert.ok(control!.has("restart_task"), "control keeps the task-control tools");
  assert.ok(!control!.has("merge_task"), "control does not include merge_task");
  assert.ok(!control!.has("agents_switch"), "control does not include agents_switch");

  // An admin-scoped key does.
  const adminMap = parseMcpKeyCapabilities("adminsuffix2:admin");
  const admin = resolveMcpCapabilities("sk-adminsuffix2", "sk-kanban", adminMap);
  assert.ok(admin!.has("merge_task"), "admin includes merge_task");
});

/** Run an MCP client against a kanban MCP server over an in-memory transport. */
async function withMcpClient<T>(
  services: KanbanServices,
  allowed: Set<string> | undefined,
  owner: string,
  fn: (client: Client) => Promise<T>,
): Promise<T> {
  const server = createKanbanMcpServer(services, allowed, owner);
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  const client = new Client({ name: "test-client", version: "1.0.0" });
  await client.connect(clientTransport);
  try {
    return await fn(client);
  } finally {
    await client.close().catch(() => {});
    await server.close().catch(() => {});
  }
}

test("merge_task: MCP server — non-admin key rejected (not in tools/list, tools/call errors)", async () => {
  const { services } = await setup();
  const mapping = parseMcpKeyCapabilities("usersuffix1:control");
  const allowed = resolveMcpCapabilities("sk-usersuffix1", "sk-kanban", mapping)!;

  await withMcpClient(services, allowed, "chuck", async (client) => {
    const tools = await client.listTools();
    assert.ok(!tools.tools.some((t) => t.name === "merge_task"), "merge_task invisible to control keys");
    const res = await client.callTool({ name: "merge_task", arguments: { task_id: 1 } });
    assert.equal(res.isError, true);
    assert.match(String((res.content as Array<{ text?: unknown }>)[0]?.text), /not available for this key/);
  });
});

test("merge_task: MCP server — admin key end-to-end (merge + push + attribution)", async () => {
  const { services, q, dir } = await setup();
  const origin = await makeOrigin(dir);
  await pushTaskBranch(origin, "task/7", "docs/e2e.md", "e2e\n");
  const { taskId } = await seedTask(q, { repoUrl: origin });
  const mapping = parseMcpKeyCapabilities("adminsuffix2:admin");
  const allowed = resolveMcpCapabilities("sk-adminsuffix2", "sk-kanban", mapping)!;

  await withMcpClient(services, allowed, "chuck", async (client) => {
    const tools = await client.listTools();
    assert.ok(tools.tools.some((t) => t.name === "merge_task"), "merge_task visible to admin keys");
    const res = await client.callTool({
      name: "merge_task",
      arguments: { task_id: taskId, note: "via mcp" },
    });
    const content = res.content as Array<{ text?: unknown }>;
    assert.ok(!res.isError, String(content[0]?.text));
    const parsed = JSON.parse(String(content[0]?.text)) as {
      merged: boolean;
      alreadyMerged: boolean;
      mergeCommit: string;
      by: string;
    };
    assert.equal(parsed.merged, true);
    assert.equal(parsed.alreadyMerged, false);
    assert.equal(parsed.by, "chuck", "owner attribution from the caller key");
    assert.equal(await git(origin, "rev-parse", "refs/heads/main"), parsed.mergeCommit);
    const body = await git(origin, "log", "-1", "--format=%b", parsed.mergeCommit);
    assert.match(body, /via mcp/);
    assert.match(body, /\(merged via merge_task by chuck\)/);
  });
});
