/**
 * Deploy stage tests (Slice 3b): routing per kind + each handler over a
 * mocked PublishGit (no network) with real temp dirs for the file logic.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { IdeaSpec } from "../db/schema.js";
import {
  DeployRunner,
  deployBlog,
  deployCode,
  deployMedia,
  deployOther,
  extractTargetPath,
  handlerForKind,
  postDate,
  slugify,
  type DeployContext,
} from "./index.js";
import type { PublishGit } from "../publish/git.js";

/** Mocked publish git: records calls; `clone` seeds a fake repo dir. */
function mockPublishGit() {
  const calls: {
    commits: Array<[string, string]>;
    pushes: string[];
    pushesCurrent: string[];
    clones: Array<[string, string]>;
  } = { commits: [], pushes: [], pushesCurrent: [], clones: [] };
  const git: PublishGit = {
    headCommit: async () => "head1",
    commitAll: async (dest, message) => {
      calls.commits.push([dest, message]);
      return "newhead1";
    },
    pushBranch: async (dest, branch) => {
      calls.pushes.push(`${dest}:${branch}`);
    },
    pushCurrent: async (dest) => {
      calls.pushesCurrent.push(dest);
    },
    clone: async (dest, repoUrl) => {
      calls.clones.push([dest, repoUrl]);
      if (!existsSync(dest)) mkdirSync(dest, { recursive: true });
    },
  };
  return { git, calls };
}

function ctx(overrides: Partial<DeployContext> = {}): DeployContext {
  return {
    taskId: 7,
    kind: "code",
    spec: { goal: "Add a dark mode", steps: [], acceptance: ["toggle works"], kind: "code" },
    project: {
      name: "Alpha",
      repoUrl: "https://github.com/chuck/alpha",
      defaultBranch: "main",
      blogRepoUrl: "https://github.com/chuck/blog",
      blogContentPath: "content/posts",
      mediaPaths: ["media/homelab"],
    },
    workspace: "/workspace/task-7",
    branch: "task/7",
    lastCommit: "abc123",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

test("slugify + postDate", () => {
  assert.equal(slugify("Add a Dark Mode!"), "add-a-dark-mode");
  assert.equal(slugify("  --weird__chars--  "), "weird-chars");
  assert.equal(slugify(""), "post");
  assert.equal(postDate(new Date("2026-11-15T12:00:00Z")), "2026-11-15");
});

test("handlerForKind routes code/blog/media/other", () => {
  assert.equal(handlerForKind("code"), deployCode);
  assert.equal(handlerForKind("blog"), deployBlog);
  assert.equal(handlerForKind("media"), deployMedia);
  assert.equal(handlerForKind("other"), deployOther);
});

// ---------------------------------------------------------------------------
// code
// ---------------------------------------------------------------------------

test("deployCode: checkpoint commit + push task branch", async () => {
  const { git, calls } = mockPublishGit();
  const result = await deployCode(ctx(), git);
  assert.equal(result.published, "pushed branch task/7");
  assert.equal(result.target, "https://github.com/chuck/alpha (branch task/7)");
  assert.equal(calls.commits.length, 1, "safety-net checkpoint commit");
  assert.match(calls.commits[0]![1], /final checkpoint before deploy/);
  assert.deepEqual(calls.pushes, ["/workspace/task-7:task/7"]);
  assert.equal(calls.pushesCurrent.length, 0);
});

test("deployCode: no repoUrl → local commit, no push (no-op note)", async () => {
  const { git, calls } = mockPublishGit();
  const result = await deployCode(ctx({ project: { ...ctx().project, repoUrl: null } }), git);
  assert.match(result.published, /no repo configured/);
  assert.equal(calls.pushes.length, 0, "nothing to push");
  assert.equal(calls.commits.length, 1, "work still committed locally");
});

// ---------------------------------------------------------------------------
// blog
// ---------------------------------------------------------------------------

test("deployBlog: clones blog repo, writes <path>/<date>-<slug>.md, commits, pushes", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-blog-"));
  const workspace = path.join(dir, "workspace", "task-7");
  mkdirSync(workspace, { recursive: true });
  writeFileSync(path.join(workspace, "post.md"), "# Dark mode\n\nIt works.\n");
  const { git, calls } = mockPublishGit();

  const result = await deployBlog(
    ctx({
      kind: "blog",
      spec: { goal: "Add a Dark Mode", steps: [], acceptance: ["post published"], kind: "blog" } as IdeaSpec,
      workspace,
    }),
    git,
  );

  const date = postDate();
  const fileName = `${date}-add-a-dark-mode.md`;
  assert.equal(result.published, `published blog post ${fileName}`);
  assert.equal(result.target, `https://github.com/chuck/blog → content/posts/${fileName}`);

  // Blog repo cloned once.
  assert.equal(calls.clones.length, 1);
  assert.equal(calls.clones[0]![1], "https://github.com/chuck/blog");
  const cloneDir = calls.clones[0]![0];
  assert.ok(cloneDir.startsWith(path.join(dir, "workspace")), "temp clone next to the workspace");

  // Post written at the configured public path.
  const written = readFileSync(path.join(cloneDir, "content/posts", fileName), "utf8");
  assert.equal(written, "# Dark mode\n\nIt works.\n");

  // Commit + push of the current branch.
  assert.equal(calls.commits.length, 1);
  assert.match(calls.commits[0]![1], new RegExp(`publish blog post ${fileName}`));
  assert.deepEqual(calls.pushesCurrent, [cloneDir]);
  assert.equal(calls.pushes.length, 0, "blog pushes the current branch, not a task branch");
});

test("deployBlog: publish_targets[0] overrides the post file location", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-blog-"));
  const workspace = path.join(dir, "workspace", "task-7");
  mkdirSync(path.join(workspace, "drafts"), { recursive: true });
  writeFileSync(path.join(workspace, "drafts", "my-post.md"), "hi");
  const { git } = mockPublishGit();

  const result = await deployBlog(
    ctx({
      kind: "blog",
      spec: {
        goal: "A post",
        steps: [],
        acceptance: [],
        kind: "blog",
        publish_targets: ["drafts/my-post.md"],
      } as IdeaSpec,
      workspace,
    }),
    git,
  );
  assert.match(result.published, /published blog post/);
});

test("deployBlog: missing post file / missing blog repo → failure", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-blog-"));
  const workspace = path.join(dir, "workspace", "task-7");
  mkdirSync(workspace, { recursive: true });
  const { git } = mockPublishGit();

  await assert.rejects(
    deployBlog(ctx({ kind: "blog", workspace }), git),
    /blog post not found/,
  );
  await assert.rejects(
    deployBlog(
      ctx({ kind: "blog", workspace, project: { ...ctx().project, blogRepoUrl: null } }),
      git,
    ),
    /no blog_repo_url/,
  );
});

// ---------------------------------------------------------------------------
// media
// ---------------------------------------------------------------------------

test("deployMedia: copies workspace media/ into the blog repo's public dir, commits, pushes", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-media-"));
  const workspace = path.join(dir, "workspace", "task-7");
  mkdirSync(path.join(workspace, "media", "sub"), { recursive: true });
  writeFileSync(path.join(workspace, "media", "a.png"), "img");
  writeFileSync(path.join(workspace, "media", "sub", "b.mp4"), "vid");
  const { git, calls } = mockPublishGit();

  const result = await deployMedia(ctx({ kind: "media", workspace }), git);
  assert.equal(result.published, "published 2 media file(s) to media/homelab");
  assert.equal(result.target, "https://github.com/chuck/blog → media/homelab");

  const cloneDir = calls.clones[0]![0];
  assert.equal(readFileSync(path.join(cloneDir, "media/homelab", "a.png"), "utf8"), "img");
  assert.equal(readFileSync(path.join(cloneDir, "media/homelab", "sub", "b.mp4"), "utf8"), "vid");
  assert.deepEqual(calls.pushesCurrent, [cloneDir]);
});

test("deployMedia: publish_targets[0] picks the target dir; empty/missing media → failure", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-media-"));
  const workspace = path.join(dir, "workspace", "task-7");
  mkdirSync(path.join(workspace, "media"), { recursive: true });
  writeFileSync(path.join(workspace, "media", "x.png"), "img");
  const { git } = mockPublishGit();

  // Target override via publish_targets.
  const result = await deployMedia(
    ctx({
      kind: "media",
      workspace,
      spec: { goal: "g", steps: [], acceptance: [], kind: "media", publish_targets: ["media/bluebovine"] } as IdeaSpec,
    }),
    git,
  );
  assert.equal(result.target, "https://github.com/chuck/blog → media/bluebovine");

  // No media dir → failure.
  const emptyWs = path.join(dir, "workspace-empty");
  mkdirSync(emptyWs, { recursive: true });
  await assert.rejects(deployMedia(ctx({ kind: "media", workspace: emptyWs }), git), /no media files/);

  // No target anywhere → failure.
  await assert.rejects(
    deployMedia(
      ctx({
        kind: "media",
        workspace,
        project: { ...ctx().project, mediaPaths: null },
        spec: { goal: "g", steps: [], acceptance: [], kind: "media" } as IdeaSpec,
      }),
      git,
    ),
    /no media path/,
  );
});

test("deployMedia: absolute target path copies to a local dir (no git)", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-media-"));
  const workspace = path.join(dir, "workspace", "task-9");
  mkdirSync(path.join(workspace, "media"), { recursive: true });
  writeFileSync(path.join(workspace, "media", "cheat-sheet.png"), "img");
  const target = path.join(dir, "out", "demo_infographics");
  const { git, calls } = mockPublishGit();

  const result = await deployMedia(
    ctx({
      kind: "media",
      workspace,
      project: { ...ctx().project, blogRepoUrl: null, mediaPaths: [target] },
    }),
    git,
  );
  assert.equal(result.published, `published 1 media file(s) to ${target}`);
  assert.equal(result.target, target);
  assert.equal(readFileSync(path.join(target, "cheat-sheet.png"), "utf8"), "img");
  // No git involved for local targets.
  assert.equal(calls.clones.length, 0);
  assert.equal(calls.pushesCurrent.length, 0);
});

test("deployMedia: absolute file target (with extension) copies the single media file exactly", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-media-"));
  const workspace = path.join(dir, "workspace", "task-9");
  mkdirSync(path.join(workspace, "media"), { recursive: true });
  writeFileSync(path.join(workspace, "media", "cheat-sheet.png"), "img");
  const target = path.join(dir, "out", "demo_infographics", "media", "dnd5e_cheatsheet.png");
  const { git, calls } = mockPublishGit();

  const result = await deployMedia(
    ctx({
      kind: "media",
      workspace,
      spec: { ...ctx().spec, publish_targets: [target] },
      project: { ...ctx().project, blogRepoUrl: null, mediaPaths: [path.join(dir, "out", "demo_infographics")] },
    }),
    git,
  );
  assert.equal(result.published, `published cheat-sheet.png to ${target}`);
  assert.equal(readFileSync(target, "utf8"), "img");
  // The target is a file, not a directory named like a file.
  assert.equal(statSync(target).isFile(), true);
  assert.equal(calls.clones.length, 0);
});

test("deployMedia: file target with multiple media files fails", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-media-"));
  const workspace = path.join(dir, "workspace", "task-9");
  mkdirSync(path.join(workspace, "media"), { recursive: true });
  writeFileSync(path.join(workspace, "media", "a.png"), "a");
  writeFileSync(path.join(workspace, "media", "b.png"), "b");
  const target = path.join(dir, "out", "one.png");
  const { git } = mockPublishGit();

  await assert.rejects(
    deployMedia(
      ctx({
        kind: "media",
        workspace,
        spec: { ...ctx().spec, publish_targets: [target] },
        project: { ...ctx().project, blogRepoUrl: null },
      }),
      git,
    ),
    /is a file but the task produced 2 media files/,
  );
});

test("deployMedia: scratch targets under the workspace root are skipped (falls back to project media path)", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-media-"));
  const workspace = path.join(dir, "workspace", "task-9");
  mkdirSync(path.join(workspace, "media"), { recursive: true });
  writeFileSync(path.join(workspace, "media", "img.png"), "img");
  const workspaceRoot = path.join(dir, "workspace");
  const scratchTarget = path.join(workspaceRoot, "groom-3", "media");
  const projectTarget = path.join(dir, "out", "demo_infographics");
  const { git, calls } = mockPublishGit();

  const result = await deployMedia(
    ctx({
      kind: "media",
      workspace,
      workspaceRoot,
      spec: { ...ctx().spec, publish_targets: [scratchTarget, projectTarget] },
      project: { ...ctx().project, blogRepoUrl: null, mediaPaths: [projectTarget] },
    }),
    git,
  );
  // The scratch target (under workspaceRoot) is skipped; the real target is used.
  assert.equal(result.target, projectTarget);
  assert.equal(readFileSync(path.join(projectTarget, "img.png"), "utf8"), "img");
  assert.equal(existsSync(scratchTarget), false, "nothing written to the scratch dir");
  assert.equal(calls.clones.length, 0);
});

test("deployMedia: all-scratch publish targets fall back to project media_paths", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-media-"));
  const workspace = path.join(dir, "workspace", "task-9");
  mkdirSync(path.join(workspace, "media"), { recursive: true });
  writeFileSync(path.join(workspace, "media", "img.png"), "img");
  const workspaceRoot = path.join(dir, "workspace");
  const projectTarget = path.join(dir, "out", "demo_infographics");
  const { git } = mockPublishGit();

  const result = await deployMedia(
    ctx({
      kind: "media",
      workspace,
      workspaceRoot,
      spec: { ...ctx().spec, publish_targets: [path.join(workspaceRoot, "groom-3", "media")] },
      project: { ...ctx().project, blogRepoUrl: null, mediaPaths: [projectTarget] },
    }),
    git,
  );
  assert.equal(result.target, projectTarget);
  assert.equal(readFileSync(path.join(projectTarget, "img.png"), "utf8"), "img");
});

// ---------------------------------------------------------------------------
// extractTargetPath — free-text publish targets (grooming-authored prose)
// ---------------------------------------------------------------------------

test("extractTargetPath: clean paths as-is; free text → first absolute path; no path → null", () => {
  // Clean absolute path (the normal case) — unchanged.
  assert.equal(
    extractTargetPath("/media-store/potato-wars-v2/b2/file.mp4"),
    "/media-store/potato-wars-v2/b2/file.mp4",
  );
  // Clean relative path (blog-repo subdir) — unchanged.
  assert.equal(extractTargetPath("media/homelab"), "media/homelab");
  // Free text with an embedded absolute path (the 2026-11-23 task-3 shape).
  assert.equal(
    extractTargetPath(
      "NAS 'media' share (homelab archive, mandatory): /media-store/potato-wars-v2/b2/ — draft.mp4 + state.json copy (thor mount equivalent: /mnt/lego-media-store/potato-wars-v2/b2/)",
    ),
    "/media-store/potato-wars-v2/b2/",
  );
  // Absolute path with a prose suffix — the path only.
  assert.equal(
    extractTargetPath("/publish/video/draft.mp4 (published via publish-file skill)"),
    "/publish/video/draft.mp4",
  );
  // URL-only text: the URL's path component is NOT a container path.
  assert.equal(extractTargetPath("served at https://choukalos.com/files/video/x.mp4 only"), null);
  // Prose with no usable path.
  assert.equal(extractTargetPath("publish to the blog file area"), null);
  assert.equal(extractTargetPath(""), null);
});

test("deployMedia: free-text publish_targets (grooming prose) → path extracted, local copy, no git crash", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-media-"));
  const workspace = path.join(dir, "workspace", "task-3");
  mkdirSync(path.join(workspace, "media"), { recursive: true });
  writeFileSync(path.join(workspace, "media", "draft.mp4"), "vid");
  const nasTarget = path.join(dir, "nas", "potato-wars-v2", "b2");
  const { git, calls } = mockPublishGit();

  // The exact shape that crashed 2026-11-23: prose entries, no blog_repo_url.
  const result = await deployMedia(
    ctx({
      kind: "media",
      workspace,
      workspaceRoot: path.join(dir, "workspace"),
      spec: {
        ...ctx().spec,
        publish_targets: [
          `NAS 'media' share (homelab archive, mandatory): ${nasTarget}/ — draft.mp4 + state.json copy (thor mount equivalent: /mnt/lego-media-store/potato-wars-v2/b2/)`,
          `Public blog file area (explicitly requested): /publish/video/draft.mp4 — served at https://choukalos.com/files/video/draft.mp4`,
        ],
      } as IdeaSpec,
      project: { ...ctx().project, blogRepoUrl: null, mediaPaths: null },
    }),
    git,
  );
  // The first entry's embedded absolute path wins; local copy, no git.
  assert.equal(result.target, `${nasTarget}/`);
  assert.equal(readFileSync(path.join(nasTarget, "draft.mp4"), "utf8"), "vid");
  assert.equal(calls.clones.length, 0);
  assert.equal(calls.pushesCurrent.length, 0);
});

test("deployMedia: URL-only target is skipped, next usable target wins", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-media-"));
  const workspace = path.join(dir, "workspace", "task-3");
  mkdirSync(path.join(workspace, "media"), { recursive: true });
  writeFileSync(path.join(workspace, "media", "draft.mp4"), "vid");
  const publicTarget = path.join(dir, "publish", "video", "draft.mp4");
  const { git, calls } = mockPublishGit();

  const result = await deployMedia(
    ctx({
      kind: "media",
      workspace,
      spec: {
        ...ctx().spec,
        publish_targets: [
          "served at https://choukalos.com/files/video/draft.mp4 (URL only — no container path)",
          publicTarget,
        ],
      } as IdeaSpec,
      project: { ...ctx().project, blogRepoUrl: null, mediaPaths: null },
    }),
    git,
  );
  assert.equal(result.target, publicTarget);
  assert.equal(readFileSync(publicTarget, "utf8"), "vid");
  assert.equal(calls.clones.length, 0);
});

// ---------------------------------------------------------------------------
// other + runner
// ---------------------------------------------------------------------------

test("deployOther: no-op", async () => {
  const { git, calls } = mockPublishGit();
  const result = await deployOther(ctx({ kind: "other" }), git);
  assert.equal(result.published, "no-op (kind: other)");
  assert.equal(result.target, "none");
  assert.equal(calls.commits.length + calls.pushes.length + calls.clones.length, 0, "no git ops");
});

test("DeployRunner.deploy routes by kind (blog end-to-end)", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-deploy-runner-"));
  const workspace = path.join(dir, "workspace", "task-9");
  mkdirSync(workspace, { recursive: true });
  writeFileSync(path.join(workspace, "post.md"), "# Post");
  const { git } = mockPublishGit();
  const runner = new DeployRunner({ git });
  const result = await runner.deploy(
    ctx({
      taskId: 9,
      kind: "blog",
      spec: { goal: "Runner post", steps: [], acceptance: [], kind: "blog" } as IdeaSpec,
      workspace,
    }),
  );
  assert.match(result.published, /published blog post \d{4}-\d{2}-\d{2}-runner-post\.md/);
});
