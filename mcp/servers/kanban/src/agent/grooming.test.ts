/**
 * Grooming state machine tests (Slice 2) with a mocked Pi session — no
 * network, no model. The mock session factory is file-backed: transcripts
 * persist to the stable session file path (JSON), so resume-after-restart
 * (SessionManager.open semantics) and cancel/re-groom file deletion are
 * exercised the same way the real SessionManager would behave.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync } from "node:fs";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { eq } from "drizzle-orm";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import type { KanbanConfig } from "../config.js";
import { initDb } from "../db/index.js";
import { ideas, usage, type IdeaSpec } from "../db/schema.js";
import { createKanbanServices, ServiceError } from "../services/index.js";
import {
  buildFinalizePrompt,
  GroomingManager,
  GROOM_STALL_MS_BY_LEVEL,
  parseGroomSpec,
  transcriptToGroomMessages,
  type GroomMessage,
} from "./grooming.js";
import { createMockGrooming, type MockGrooming } from "./grooming-mock.js";

// ---------------------------------------------------------------------------
// Test harness
// ---------------------------------------------------------------------------

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

interface Harness {
  q: BetterSQLite3Database<any>;
  services: ReturnType<typeof createKanbanServices>;
  ws: string;
  sessions: string;
  mock: MockGrooming;
  manager: GroomingManager;
  projectId: number;
}

async function setup(): Promise<Harness> {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-groom-"));
  const ws = path.join(dir, "workspace");
  const sessions = path.join(dir, "sessions");
  mkdirSync(ws, { recursive: true });
  mkdirSync(sessions, { recursive: true });
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const services = createKanbanServices(db);
  const mock = createMockGrooming();
  const manager = new GroomingManager({
    db: q,
    cfg,
    sessionFactory: mock.factory,
    workspaceRoot: ws,
    sessionsDir: sessions,
  });
  const project = await services.createProject({
    name: "Groom Project",
    goal: "ship things",
    constraints: "never force-push",
  });
  return { q, services, ws, sessions, mock, manager, projectId: project.id };
}

/** Put an idea straight into the icebox with a spec (test fixture). */
async function toIcebox(q: BetterSQLite3Database<any>, ideaId: number, spec?: Partial<IdeaSpec>): Promise<void> {
  await q
    .update(ideas)
    .set({
      state: "icebox",
      spec: {
        goal: "fixture goal",
        steps: ["s"],
        acceptance: ["a"],
        kind: "code",
        ...spec,
      },
    })
    .where(eq(ideas.id, ideaId));
}

function expectServiceError(promise: Promise<unknown>, status: number, match?: RegExp): Promise<void> {
  return assert.rejects(
    promise,
    (err: unknown) => {
      assert.ok(err instanceof ServiceError, `expected ServiceError, got: ${err}`);
      assert.equal(err.status, status);
      if (match) assert.match(err.message, match);
      return true;
    },
    `expected ServiceError(${status})`,
  );
}

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

test("startGrooming: idea → grooming, scratch dir, seeded persisted session", async () => {
  const h = await setup();
  const idea = await h.services.addIdea(h.projectId, "Build a widget");

  const result = await h.manager.startGrooming(idea.id);
  assert.equal(result.state, "grooming");

  // Scratch dir created under the workspace root.
  const scratch = path.join(h.ws, `groom-${idea.id}`);
  assert.ok(existsSync(scratch), "scratch dir exists");

  // Exactly one session, at the stable path, seeded with the idea text.
  assert.equal(h.mock.sessions.length, 1);
  const session = h.mock.sessions[0]!;
  assert.equal(session.sessionFile, path.join(h.sessions, `groom-${idea.id}.jsonl`));
  assert.deepEqual(session.prompts, ["Build a widget"], "seed prompt = idea text");
  assert.ok(existsSync(session.sessionFile), "session file persisted");

  // System prompt carries the project context.
  const transcript = await h.manager.transcript(idea.id);
  assert.equal(transcript.length, 2);
  assert.equal(transcript[0]!.role, "user");
  assert.equal(transcript[0]!.text, "Build a widget");
  assert.equal(transcript[1]!.role, "assistant");

  // Idempotent while grooming (no new session, no new prompt).
  await h.manager.startGrooming(idea.id);
  assert.equal(h.mock.sessions.length, 1);
  assert.equal(session.prompts.length, 1);

  // Guards: not allowed from icebox.
  await toIcebox(h.q, idea.id);
  await expectServiceError(h.manager.startGrooming(idea.id), 409, /icebox/);
  await h.manager.dispose();
});

test("turnStatus: active during an in-flight background seed, idle after it settles", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-groom-status-"));
  const ws = path.join(dir, "workspace");
  const sessions = path.join(dir, "sessions");
  mkdirSync(ws, { recursive: true });
  mkdirSync(sessions, { recursive: true });
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const services = createKanbanServices(db);
  const mock = createMockGrooming(undefined, { slowMs: 40 });
  const manager = new GroomingManager({
    db: q,
    cfg,
    sessionFactory: mock.factory,
    workspaceRoot: ws,
    sessionsDir: sessions,
  });
  const project = await services.createProject({ name: "Status Project" });
  const idea = await services.addIdea(project.id, "Slow seed");

  // Background start returns immediately; the seed turn is in flight.
  // (The in-flight mark lands a microtask later, once the session creation
  // promise is kicked off — the page's first poll is 3s later.)
  const started = await manager.startGrooming(idea.id, { background: true });
  assert.equal(started.state, "grooming");
  await new Promise((r) => setTimeout(r, 5));
  const during = manager.turnStatus(idea.id);
  assert.equal(during.active, true, "active during the in-flight seed");
  assert.ok(during.since! > 0, "since timestamp set");

  // A chat message queued while the seed runs keeps the status active.
  void manager.sendGroomMessage(idea.id, "queued question");
  const queued = manager.turnStatus(idea.id);
  assert.equal(queued.active, true, "still active with a queued turn");

  // Wait for both turns to settle (seed 40ms + queued 40ms).
  await new Promise((r) => setTimeout(r, 150));
  const after = manager.turnStatus(idea.id);
  assert.equal(after.active, false, "idle after all turns settle");

  // Transcript: seed pair + queued user/assistant pair.
  const transcript = await manager.transcript(idea.id);
  assert.deepEqual(
    transcript.map((m) => m.role),
    ["user", "assistant", "user", "assistant"],
  );
  await manager.dispose();
});

test("postAcceptGrooming: finalizes in the background; idea lands in the icebox", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-groom-accept-"));
  const ws = path.join(dir, "workspace");
  const sessions = path.join(dir, "sessions");
  mkdirSync(ws, { recursive: true });
  mkdirSync(sessions, { recursive: true });
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const services = createKanbanServices(db);
  const mock = createMockGrooming(undefined, { slowMs: 30 });
  const manager = new GroomingManager({
    db: q,
    cfg,
    sessionFactory: mock.factory,
    workspaceRoot: ws,
    sessionsDir: sessions,
  });
  const project = await services.createProject({ name: "Accept Project" });
  const idea = await services.addIdea(project.id, "Accept me");
  await manager.startGrooming(idea.id); // blocking seed (fast mock)

  // Fire-and-forget accept: returns after validation; finalize runs in flight.
  await manager.postAcceptGrooming(idea.id);
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(manager.turnStatus(idea.id).active, true, "finalize turn in flight");
  assert.equal(manager.turnStatus(idea.id).label, "finalizing spec");

  // Wait for the background finalize to settle (mock turn ~30ms).
  let done = await services.getIdea(idea.id);
  for (let i = 0; i < 100 && done?.state !== "icebox"; i++) {
    await new Promise((r) => setTimeout(r, 10));
    done = await services.getIdea(idea.id);
  }
  assert.equal(done?.state, "icebox");
  assert.equal(done?.spec?.goal, "Mock goal");
  assert.equal(manager.turnStatus(idea.id).active, false, "idle after finalize");

  // Guards: wrong state → 409, unknown idea → 404.
  await expectServiceError(manager.postAcceptGrooming(idea.id), 409, /icebox/);
  await expectServiceError(manager.postAcceptGrooming(999), 404, /not found/);
  await manager.dispose();
});

test("watchdog: a stuck turn (no activity) is aborted and the idea stays usable", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-groom-watchdog-"));
  const ws = path.join(dir, "workspace");
  const sessions = path.join(dir, "sessions");
  mkdirSync(ws, { recursive: true });
  mkdirSync(sessions, { recursive: true });
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const services = createKanbanServices(db);
  // Slow turn that never emits activity → looks stuck to the watchdog.
  const mock = createMockGrooming(undefined, { slowMs: 60_000, activityMs: Infinity });
  const manager = new GroomingManager({
    db: q,
    cfg,
    sessionFactory: mock.factory,
    workspaceRoot: ws,
    sessionsDir: sessions,
    turnStallMs: 300,
    watchdogIntervalMs: 50,
  });
  const project = await services.createProject({ name: "Watchdog Project" });
  const idea = await services.addIdea(project.id, "Stuck seed");

  const seedP = manager.startGrooming(idea.id); // blocking seed; will be released
  let active = true;
  for (let i = 0; i < 100 && active; i++) {
    await new Promise((r) => setTimeout(r, 25));
    active = manager.turnStatus(idea.id).active;
  }
  assert.equal(active, false, "watchdog released the stuck turn");
  await assert.rejects(seedP, /aborted/, "stuck turn promise rejects after abort");

  // Idea is still groomable: the session was dropped, the transcript keeps
  // the seed user message, and a new chat turn completes normally.
  const stillGrooming = await services.getIdea(idea.id);
  assert.equal(stillGrooming?.state, "grooming");
  mock.setSlowMs(0); // future turns are fast again
  const reply = await manager.sendGroomMessage(idea.id, "hello again");
  assert.ok(reply.text.length > 0);
  assert.equal(manager.turnStatus(idea.id).active, false, "idle after the new turn");
  await manager.dispose();
});

test("watchdog: a live slow turn (activity events) is not aborted", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-groom-watchdog-"));
  const ws = path.join(dir, "workspace");
  const sessions = path.join(dir, "sessions");
  mkdirSync(ws, { recursive: true });
  mkdirSync(sessions, { recursive: true });
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const services = createKanbanServices(db);
  // Slow turn that keeps emitting activity → long but live, must survive.
  const mock = createMockGrooming(undefined, { slowMs: 600, activityMs: 50 });
  const manager = new GroomingManager({
    db: q,
    cfg,
    sessionFactory: mock.factory,
    workspaceRoot: ws,
    sessionsDir: sessions,
    turnStallMs: 150, // well below the 600ms turn
    watchdogIntervalMs: 50,
  });
  const project = await services.createProject({ name: "Live Project" });
  const idea = await services.addIdea(project.id, "Live seed");

  await manager.startGrooming(idea.id); // blocking; completes despite the stall budget
  const liveIdea = await services.getIdea(idea.id);
  assert.equal(liveIdea?.state, "grooming");
  assert.equal(manager.turnStatus(idea.id).active, false, "settled after the live turn");
  const reply = await manager.sendGroomMessage(idea.id, "hi");
  assert.ok(reply.text.length > 0);
  await manager.dispose();
});

test("startGrooming: system prompt carries the project context", async () => {
  const h = await setup();
  const idea = await h.services.addIdea(h.projectId, "An idea");
  await h.manager.startGrooming(idea.id);
  const opts = h.mock.created[0]!;
  assert.equal(opts.cwd, path.join(h.ws, `groom-${idea.id}`), "scratch dir as cwd");
  assert.equal(opts.sessionFile, path.join(h.sessions, `groom-${idea.id}.jsonl`), "stable session file");
  assert.match(opts.systemPrompt, /Groom Project/);
  assert.match(opts.systemPrompt, /ship things/);
  assert.match(opts.systemPrompt, /never force-push/);
  assert.match(opts.systemPrompt, new RegExp(`groom-${idea.id}`), "scratch dir named in the prompt");
  await h.manager.dispose();
});

test("sendGroomMessage: chat turn returns the new assistant message", async () => {
  const h = await setup();
  const idea = await h.services.addIdea(h.projectId, "Chat idea");
  await h.manager.startGrooming(idea.id);

  const msg = await h.manager.sendGroomMessage(idea.id, "What kind should this be?");
  assert.equal(msg.role, "assistant");
  assert.match(msg.text, /mock reply to: What kind/);

  const transcript = await h.manager.transcript(idea.id);
  assert.deepEqual(
    transcript.map((m: GroomMessage) => m.role),
    ["user", "assistant", "user", "assistant"],
  );

  // Empty message → 400; wrong state → 409; unknown idea → 404.
  await expectServiceError(h.manager.sendGroomMessage(idea.id, "   "), 400, /required/);
  await toIcebox(h.q, idea.id);
  await expectServiceError(h.manager.sendGroomMessage(idea.id, "too late"), 409, /icebox/);
  await expectServiceError(h.manager.sendGroomMessage(999, "hi"), 404, /not found/);
  await h.manager.dispose();
});

test("accept: finalizes spec + LLM deps → icebox, session disposed, usage recorded", async () => {
  const h = await setup();
  const dep = await h.services.addIdea(h.projectId, "Foundation work");
  await toIcebox(h.q, dep.id);
  // Phase 2: the idea's owner is threaded into the session + usage rows.
  const idea = await h.services.addIdea(h.projectId, "Dependent idea", "chuck");
  await h.manager.startGrooming(idea.id);

  h.mock.setResponder((prompt) => {
    if (prompt.startsWith("FINALIZE")) {
      return (
        "Here is the spec:\n```json\n" +
        JSON.stringify({
          goal: "Dependent goal",
          steps: ["do it"],
          acceptance: ["works"],
          kind: "blog",
          publish_targets: ["content/blog"],
          notes: "build on the foundation",
          depends_on: [dep.id],
        }) +
        "\n```"
      );
    }
    return "chat";
  });

  const result = await h.manager.acceptGrooming(idea.id);
  assert.equal(result.state, "icebox");
  assert.equal(result.spec?.goal, "Dependent goal");
  assert.deepEqual(result.spec?.steps, ["do it"]);
  assert.deepEqual(result.spec?.acceptance, ["works"]);
  assert.equal(result.spec?.kind, "blog");
  assert.deepEqual(result.spec?.publish_targets, ["content/blog"]);
  assert.equal(result.spec?.notes, "build on the foundation");
  assert.deepEqual(result.dependsOn, [dep.id], "LLM-identified deps stored");

  // The finalize prompt listed the current icebox items as dep candidates.
  const session = h.mock.sessions[0]!;
  const finalize = session.prompts.find((p) => p.startsWith("FINALIZE"))!;
  assert.ok(finalize.includes(`id ${dep.id}: Foundation work`), "icebox item listed");
  assert.ok(finalize.includes("depends_on"));

  // In-memory session disposed (file kept as grooming output).
  assert.equal(session.disposed, true);
  assert.ok(existsSync(session.sessionFile), "session file kept under /data");

  // Usage recorded (role groom, taskId null, project tagged, owner stamped).
  const rows = await h.q.select().from(usage).where(eq(usage.role, "groom"));
  assert.ok(rows.length >= 2, "seed + finalize usage rows");
  assert.ok(rows.every((r) => r.taskId === null && r.projectId === h.projectId));
  // Phase 2: the session factory got the idea's owner; usage rows carry it.
  assert.equal(h.mock.created[0]!.owner, "chuck", "factory options carry the idea owner");
  assert.ok(rows.every((r) => r.owner === "chuck"), "usage rows stamped with the owner");

  // Accept again → 409 (no longer grooming).
  await expectServiceError(h.manager.acceptGrooming(idea.id), 409, /icebox/);
  await h.manager.dispose();
});

test("accept: invalid dep id or malformed JSON keeps the idea in grooming", async () => {
  const h = await setup();
  const idea = await h.services.addIdea(h.projectId, "Bad spec idea");
  await h.manager.startGrooming(idea.id);

  // Dep references an idea that is not in the icebox.
  h.mock.setResponder(() =>
    JSON.stringify({
      goal: "g",
      steps: [],
      acceptance: [],
      kind: "code",
      publish_targets: null,
      notes: null,
      depends_on: [999],
    }),
  );
  await expectServiceError(h.manager.acceptGrooming(idea.id), 400, /not a current icebox item/);
  let row = (await h.q.select().from(ideas).where(eq(ideas.id, idea.id))).find((r) => r.id === idea.id)!;
  assert.equal(row.state, "grooming", "still grooming after bad dep");

  // Malformed JSON.
  h.mock.setResponder(() => "I cannot produce JSON right now.");
  await expectServiceError(h.manager.acceptGrooming(idea.id), 400, /spec JSON/);
  row = (await h.q.select().from(ideas).where(eq(ideas.id, idea.id))).find((r) => r.id === idea.id)!;
  assert.equal(row.state, "grooming", "still grooming after malformed JSON");

  // Self-reference rejected.
  h.mock.setResponder(() =>
    JSON.stringify({
      goal: "g",
      steps: [],
      acceptance: [],
      kind: "code",
      publish_targets: null,
      notes: null,
      depends_on: [idea.id],
    }),
  );
  await expectServiceError(h.manager.acceptGrooming(idea.id), 400, /itself/);
  await h.manager.dispose();
});

test("cancel: grooming → idea, chat discarded (session file deleted)", async () => {
  const h = await setup();
  const idea = await h.services.addIdea(h.projectId, "Cancel me");
  await h.manager.startGrooming(idea.id);
  const file = path.join(h.sessions, `groom-${idea.id}.jsonl`);
  assert.ok(existsSync(file));

  const result = await h.manager.cancelGrooming(idea.id);
  assert.equal(result.state, "idea");
  assert.ok(!existsSync(file), "session file deleted (chat discarded)");
  assert.equal(h.mock.sessions[0]!.disposed, true);

  // Guards.
  await expectServiceError(h.manager.cancelGrooming(idea.id), 409, /idea/);
  // Re-grooming starts a fresh session (no transcript continuity).
  await h.manager.startGrooming(idea.id);
  const fresh = h.mock.sessions[1]!;
  assert.equal(fresh.prompts.length, 1, "re-seeded");
  assert.equal(fresh.messages.length, 2, "fresh transcript (no old messages)");
  await h.manager.dispose();
});

test("reGroom: fresh session, re-seeded with the idea", async () => {
  const h = await setup();
  const idea = await h.services.addIdea(h.projectId, "Re-groom me");
  await h.manager.startGrooming(idea.id);
  await h.manager.sendGroomMessage(idea.id, "old chat");
  const file = path.join(h.sessions, `groom-${idea.id}.jsonl`);

  const result = await h.manager.reGroom(idea.id);
  assert.equal(result.state, "grooming");
  const fresh = h.mock.sessions[1]!;
  assert.equal(fresh.sessionFile, file);
  assert.deepEqual(fresh.prompts, ["Re-groom me"], "re-seeded with the idea");
  assert.equal(fresh.messages.length, 2, "no old transcript");
  assert.equal(h.mock.sessions[0]!.disposed, true, "old session disposed");

  // Guard: only from grooming.
  await expectServiceError(h.manager.reGroom(999), 404);
  await h.manager.dispose();
});

test("discard: soft-deletes the idea and discards the chat", async () => {
  const h = await setup();
  const raw = await h.services.addIdea(h.projectId, "Discard raw");
  const grooming = await h.services.addIdea(h.projectId, "Discard grooming");
  await h.manager.startGrooming(grooming.id);
  const file = path.join(h.sessions, `groom-${grooming.id}.jsonl`);

  const r1 = await h.manager.discardIdea(raw.id);
  assert.equal(r1.state, "discarded");
  const r2 = await h.manager.discardIdea(grooming.id);
  assert.equal(r2.state, "discarded");
  assert.ok(!existsSync(file), "session file deleted");

  // Guards: discarded/icebox ideas cannot be discarded again or groomed.
  await expectServiceError(h.manager.discardIdea(r1.id), 409, /discarded/);
  await expectServiceError(h.manager.startGrooming(r1.id), 409);
  const iceboxed = await h.services.addIdea(h.projectId, "Iceboxed");
  await toIcebox(h.q, iceboxed.id);
  await expectServiceError(h.manager.discardIdea(iceboxed.id), 409, /icebox/);
  await h.manager.dispose();
});

test("resume after restart: a new manager reopens the persisted session file", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-groom-"));
  const ws = path.join(dir, "workspace");
  const sessions = path.join(dir, "sessions");
  mkdirSync(ws, { recursive: true });
  mkdirSync(sessions, { recursive: true });
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const services = createKanbanServices(db);
  const project = await services.createProject({ name: "Resume Project" });
  const idea = await services.addIdea(project.id, "Resume idea");

  const mock1 = createMockGrooming();
  const m1 = new GroomingManager({
    db: q,
    cfg,
    sessionFactory: mock1.factory,
    workspaceRoot: ws,
    sessionsDir: sessions,
  });
  await m1.startGrooming(idea.id);
  await m1.sendGroomMessage(idea.id, "hello from before");
  m1.dispose();

  // "Server restart": new manager + new factory, same sessions dir.
  const mock2 = createMockGrooming();
  const m2 = new GroomingManager({
    db: q,
    cfg,
    sessionFactory: mock2.factory,
    workspaceRoot: ws,
    sessionsDir: sessions,
  });
  const msg = await m2.sendGroomMessage(idea.id, "hello after restart");
  assert.match(msg.text, /hello after restart/);
  const resumed = mock2.sessions[0]!;
  const transcript = transcriptToGroomMessages(resumed.messages);
  assert.equal(transcript.length, 6, "seed + old turn (4) + new turn (2)");
  assert.equal(transcript[0]!.text, "Resume idea");
  assert.equal(transcript[2]!.text, "hello from before");
  assert.equal(transcript[4]!.text, "hello after restart");
  m2.dispose();
  await db.close();
});

test("parseGroomSpec: fences/prose tolerated, schema enforced", () => {
  const icebox = new Set([7, 8]);
  const base = {
    goal: "g",
    steps: ["s"],
    acceptance: ["a"],
    kind: "code" as const,
    publish_targets: null,
    notes: null,
    depends_on: [7],
  };

  // Plain JSON.
  assert.deepEqual(parseGroomSpec(JSON.stringify(base), icebox, 1).spec.goal, "g");
  // Code fence + surrounding prose.
  const fenced = "Sure!\n```json\n" + JSON.stringify(base) + "\n```\nLet me know.";
  assert.deepEqual(parseGroomSpec(fenced, icebox, 1).dependsOn, [7]);
  // null publish_targets/notes → omitted from the spec.
  const { spec } = parseGroomSpec(JSON.stringify(base), icebox, 1);
  assert.equal(spec.publish_targets, undefined);
  assert.equal(spec.notes, undefined);

  // Invalid kind.
  assert.throws(
    () => parseGroomSpec(JSON.stringify({ ...base, kind: "video" }), icebox, 1),
    /incomplete spec/,
  );
  // Missing goal.
  assert.throws(() => parseGroomSpec(JSON.stringify({ ...base, goal: "" }), icebox, 1), /goal/);
  // Unknown dep.
  assert.throws(() => parseGroomSpec(JSON.stringify({ ...base, depends_on: [9] }), icebox, 1), /not a current icebox item/);
  // Self dep.
  assert.throws(() => parseGroomSpec(JSON.stringify({ ...base, depends_on: [1] }), icebox, 1), /itself/);
  // No JSON at all.
  assert.throws(() => parseGroomSpec("no json here", icebox, 1), /did not return a spec JSON/);
  // Invalid JSON.
  assert.throws(() => parseGroomSpec("{not json}", icebox, 1), /invalid spec JSON/);
});

test("buildFinalizePrompt lists icebox items (or none)", () => {
  const none = buildFinalizePrompt([]);
  assert.ok(none.includes("(none)"));
  const withItems = buildFinalizePrompt([
    { id: 3, text: "A" },
    { id: 4, text: "B" },
  ]);
  assert.ok(withItems.includes("- id 3: A"));
  assert.ok(withItems.includes("- id 4: B"));
  assert.ok(withItems.includes('"kind": "code" | "blog" | "media" | "other"'));
});

test("transcript: empty for a raw idea, normalized for a grooming chat", async () => {
  const h = await setup();
  const idea = await h.services.addIdea(h.projectId, "Transcript idea");
  assert.deepEqual(await h.manager.transcript(idea.id), []);
  await h.manager.startGrooming(idea.id);
  const t = await h.manager.transcript(idea.id);
  assert.equal(t.length, 2);
  assert.equal(t[0]!.role, "user");
  assert.equal(t[1]!.role, "assistant");
  // 404 for unknown idea.
  await expectServiceError(h.manager.transcript(999), 404);
  await h.manager.dispose();
});

test("workspace/session paths honor the configured roots", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-groom-"));
  const ws = path.join(dir, "custom-ws");
  const sessions = path.join(dir, "custom-sessions");
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const mock = createMockGrooming();
  const manager = new GroomingManager({
    db: q,
    cfg,
    sessionFactory: mock.factory,
    workspaceRoot: ws,
    sessionsDir: sessions,
  });
  assert.equal(manager.scratchDir(42), path.join(ws, "groom-42"));
  assert.equal(manager.sessionFile(42), path.join(sessions, "groom-42.jsonl"));
  await db.close();
});

// ---------------------------------------------------------------------------
// Turn watchdog stall threshold: per thinking level (GROOM_STALL_MS_BY_LEVEL)
// ---------------------------------------------------------------------------

function stallMsOf(manager: GroomingManager): number {
  return (manager as unknown as { turnStallMs: number }).turnStallMs;
}

test("turn stall threshold defaults to the grooming thinking level", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-groom-"));
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const mock = createMockGrooming();
  const saved = process.env.GROOM_TURN_STALL_MINUTES;
  try {
    delete process.env.GROOM_TURN_STALL_MINUTES;
    for (const level of ["medium", "high", "xhigh", "off"] as const) {
      const manager = new GroomingManager({
        db: q,
        cfg: { ...cfg, thinking: { ...cfg.thinking, groom: level } },
        sessionFactory: mock.factory,
      });
      assert.equal(
        stallMsOf(manager),
        GROOM_STALL_MS_BY_LEVEL[level],
        `stall default for ${level}`,
      );
      manager.dispose();
    }
    // xhigh is the most patient (deep turns can be quiet 10+ min)
    assert.ok(GROOM_STALL_MS_BY_LEVEL.xhigh! > GROOM_STALL_MS_BY_LEVEL.medium!);
  } finally {
    if (saved === undefined) delete process.env.GROOM_TURN_STALL_MINUTES;
    else process.env.GROOM_TURN_STALL_MINUTES = saved;
    await db.close();
  }
});

test("GROOM_TURN_STALL_MINUTES env overrides the per-level default", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-groom-"));
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  const q = db.db as unknown as BetterSQLite3Database<any>;
  const mock = createMockGrooming();
  const saved = process.env.GROOM_TURN_STALL_MINUTES;
  try {
    process.env.GROOM_TURN_STALL_MINUTES = "7";
    const manager = new GroomingManager({
      db: q,
      cfg: { ...cfg, thinking: { ...cfg.thinking, groom: "xhigh" } },
      sessionFactory: mock.factory,
    });
    assert.equal(stallMsOf(manager), 7 * 60_000, "env wins over the xhigh default");
    manager.dispose();
  } finally {
    if (saved === undefined) delete process.env.GROOM_TURN_STALL_MINUTES;
    else process.env.GROOM_TURN_STALL_MINUTES = saved;
    await db.close();
  }
});
