/**
 * Agents master switch — service-layer tests over a real (temp) sqlite db.
 * Covers the fail-safe default (missing row -> off), the set/get round-trip,
 * audit attribution, malformed-value fail-closed, and the KanbanServices
 * surface (getAgentsSwitch / setAgentsSwitch).
 */
import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { eq } from "drizzle-orm";
import type { BetterSQLite3Database } from "drizzle-orm/better-sqlite3";
import type { KanbanConfig } from "../config.js";
import { initDb } from "../db/index.js";
import { kv } from "../db/tables.js";
import { createKanbanServices, type KanbanServices } from "./index.js";
import {
  AGENTS_SWITCH_KV_KEY,
  getAgentsSwitch,
  setAgentsSwitch,
} from "./agents-switch.js";

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

async function setup(): Promise<{
  services: KanbanServices;
  q: BetterSQLite3Database<any>;
}> {
  const dir = mkdtempSync(path.join(tmpdir(), "ai-kanban-switch-"));
  const cfg = testCfg(path.join(dir, "kanban.db"));
  const db = await initDb(cfg);
  return { services: createKanbanServices(db), q: db.db as unknown as BetterSQLite3Database<any> };
}

test("agents switch: missing row -> fail-safe OFF (never set)", async () => {
  const { services } = await setup();
  assert.deepEqual(await services.getAgentsSwitch(), {
    state: "off",
    setAt: null,
    setBy: null,
  });
});

test("agents switch: set/get round-trip with audit attribution", async () => {
  const { services } = await setup();
  const before = Date.now();
  const on = await services.setAgentsSwitch("on", "chuck");
  assert.equal(on.state, "on");
  assert.ok(on.setAt! >= before, "setAt stamped");
  assert.equal(on.setBy, "chuck");

  const read = await services.getAgentsSwitch();
  assert.deepEqual(read, { state: "on", setAt: on.setAt, setBy: "chuck" });

  // Flip back off: the row is UPDATED (not duplicated) and the audit follows.
  const off = await services.setAgentsSwitch("off", "dylan");
  assert.equal(off.state, "off");
  const read2 = await services.getAgentsSwitch();
  assert.deepEqual(read2, { state: "off", setAt: off.setAt, setBy: "dylan" });
});

test("agents switch: exactly one kv row after repeated flips", async () => {
  const { q } = await setup();
  const db = q as unknown as Parameters<typeof setAgentsSwitch>[0];
  await setAgentsSwitch(db, "on", "a");
  await setAgentsSwitch(db, "off", "b");
  await setAgentsSwitch(db, "on", "c");
  const rows = await q.select().from(kv).where(eq(kv.key, AGENTS_SWITCH_KV_KEY));
  assert.equal(rows.length, 1, "upsert keeps a single row");
});

test("agents switch: malformed value fails closed (OFF)", async () => {
  const { q } = await setup();
  const db = q as unknown as Parameters<typeof setAgentsSwitch>[0];
  await q.insert(kv).values({ key: AGENTS_SWITCH_KV_KEY, value: "not-json{{" });
  assert.deepEqual(await getAgentsSwitch(db), { state: "off", setAt: null, setBy: null });
});

test("agents switch: unexpected state value fails closed (OFF)", async () => {
  const { q } = await setup();
  const db = q as unknown as Parameters<typeof setAgentsSwitch>[0];
  await q
    .insert(kv)
    .values({ key: AGENTS_SWITCH_KV_KEY, value: JSON.stringify({ state: "maybe", setAt: 1, setBy: "x" }) });
  assert.equal((await getAgentsSwitch(db)).state, "off", "only an explicit 'on' enables agents");
});
