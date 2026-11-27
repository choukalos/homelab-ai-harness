/**
 * Agents master switch (v2) — service-layer tests over a real (temp) sqlite
 * db. Covers the fail-safe default (missing row -> off), v1-row backward
 * compatibility, global + per-slug set/get round-trips with audit
 * attribution, cross-preservation (global set keeps slugs and vice versa),
 * unknown-slug rejection, effective-state composition, malformed-value
 * fail-closed, and the KanbanServices surface.
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
  effectiveSwitchState,
  getAgentsSwitch,
  setAgentsSwitchGlobal,
  setAgentsSwitchSlug,
} from "./agents-switch.js";

const SLUGS = ["product", "analyst", "strategist", "marketing"];

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
    agentSlugs: SLUGS,
    ownerModels: {},
    ownerModelCosts: {},
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
  return {
    services: createKanbanServices(db, { agentSlugs: SLUGS }),
    q: db.db as unknown as BetterSQLite3Database<any>,
  };
}

test("agents switch: missing row -> fail-safe OFF (never set, no slugs)", async () => {
  const { services } = await setup();
  assert.deepEqual(await services.getAgentsSwitch(), {
    global: { state: "off", setAt: null, setBy: null },
    slugs: {},
  });
});

test("agents switch: v1 flat row is read as the global entry (backward compat)", async () => {
  const { q } = await setup();
  await q.insert(kv).values({
    key: AGENTS_SWITCH_KV_KEY,
    value: JSON.stringify({ state: "on", setAt: 1234, setBy: "chuck" }),
  });
  const view = await getAgentsSwitch(q as unknown as Parameters<typeof getAgentsSwitch>[0]);
  assert.deepEqual(view, {
    global: { state: "on", setAt: 1234, setBy: "chuck" },
    slugs: {},
  });
  assert.equal(effectiveSwitchState(view, "product"), "on", "v1 'on' row enables all slugs");
});

test("agents switch: global set/get round-trip with audit attribution", async () => {
  const { services } = await setup();
  const before = Date.now();
  const on = await services.setAgentsSwitch("on", "chuck");
  assert.equal(on.global.state, "on");
  assert.ok(on.global.setAt! >= before, "setAt stamped");
  assert.equal(on.global.setBy, "chuck");
  assert.deepEqual(on.slugs, {});

  const read = await services.getAgentsSwitch();
  assert.deepEqual(read, {
    global: { state: "on", setAt: on.global.setAt, setBy: "chuck" },
    slugs: {},
  });

  // Flip back off: the row is UPDATED (not duplicated) and the audit follows.
  const off = await services.setAgentsSwitch("off", "dylan");
  assert.equal(off.global.state, "off");
  const read2 = await services.getAgentsSwitch();
  assert.deepEqual(read2, {
    global: { state: "off", setAt: off.global.setAt, setBy: "dylan" },
    slugs: {},
  });
});

test("agents switch: per-slug set/get round-trip with audit attribution", async () => {
  const { services } = await setup();
  await services.setAgentsSwitch("on", "chuck"); // global on first
  const before = Date.now();
  const off = await services.setAgentsSwitchSlug("product", "off", "chuck");
  assert.equal(off.global.state, "on", "global untouched by a slug write");
  assert.equal(off.slugs.product!.state, "off");
  assert.ok(off.slugs.product!.setAt! >= before, "slug setAt stamped");
  assert.equal(off.slugs.product!.setBy, "chuck");

  const read = await services.getAgentsSwitch();
  assert.deepEqual(read.slugs.product, {
    state: "off",
    setAt: off.slugs.product!.setAt,
    setBy: "chuck",
  });
  assert.equal(read.slugs.analyst, undefined, "other slugs untouched");
});

test("agents switch: global set preserves per-slug entries (and vice versa)", async () => {
  const { services } = await setup();
  await services.setAgentsSwitch("on", "chuck");
  const s1 = await services.setAgentsSwitchSlug("product", "off", "chuck");
  await services.setAgentsSwitchSlug("analyst", "off", "dylan");
  // Global flip must keep both slug entries.
  const g2 = await services.setAgentsSwitch("off", "chuck");
  assert.equal(g2.global.state, "off");
  assert.deepEqual(Object.keys(g2.slugs).sort(), ["analyst", "product"]);
  assert.equal(g2.slugs.product!.setBy, "chuck");
  assert.equal(g2.slugs.analyst!.setBy, "dylan");
  // A later slug write must keep the global entry (and its audit).
  const s2 = await services.setAgentsSwitchSlug("product", "on", "dylan");
  assert.equal(s2.global.state, "off");
  assert.equal(s2.global.setBy, "chuck", "global audit preserved");
  assert.equal(s2.slugs.product!.state, "on");
  assert.equal(s2.slugs.product!.setBy, "dylan");
  assert.equal(s2.slugs.analyst!.state, "off", "other slug preserved");
  void s1;
});

test("agents switch: unknown slug is rejected (no phantom entries)", async () => {
  const { services } = await setup();
  await services.setAgentsSwitch("on", "chuck");
  await assert.rejects(
    () => services.setAgentsSwitchSlug("ghost", "off", "chuck"),
    /unknown agent slug 'ghost'/,
  );
  const read = await services.getAgentsSwitch();
  assert.equal(read.slugs.ghost, undefined, "no phantom entry written");
});

test("agents switch: effective state — global OFF dominates everything", async () => {
  const { services } = await setup();
  await services.setAgentsSwitch("on", "chuck");
  await services.setAgentsSwitchSlug("product", "on", "chuck");
  const view = await services.setAgentsSwitch("off", "chuck");
  for (const slug of SLUGS) {
    assert.equal(effectiveSwitchState(view, slug), "off", `global off dominates ${slug}`);
  }
});

test("agents switch: effective state — global ON, absent slug -> on, slug OFF -> off", async () => {
  const { services } = await setup();
  const view = await services.setAgentsSwitch("on", "chuck");
  assert.equal(effectiveSwitchState(view, "product"), "on", "absent slug entry -> on");
  const v2 = await services.setAgentsSwitchSlug("product", "off", "chuck");
  assert.equal(effectiveSwitchState(v2, "product"), "off", "slug off");
  assert.equal(effectiveSwitchState(v2, "analyst"), "on", "other slugs unaffected");
});

test("agents switch: exactly one kv row after repeated flips", async () => {
  const { q } = await setup();
  const db = q as unknown as Parameters<typeof setAgentsSwitchGlobal>[0];
  await setAgentsSwitchGlobal(db, "on", "a");
  await setAgentsSwitchSlug(db, "product", "off", "b", SLUGS);
  await setAgentsSwitchGlobal(db, "off", "c");
  await setAgentsSwitchSlug(db, "analyst", "on", "d", SLUGS);
  const rows = await q.select().from(kv).where(eq(kv.key, AGENTS_SWITCH_KV_KEY));
  assert.equal(rows.length, 1, "upsert keeps a single row");
});

test("agents switch: malformed value fails closed (OFF)", async () => {
  const { q } = await setup();
  const db = q as unknown as Parameters<typeof getAgentsSwitch>[0];
  await q.insert(kv).values({ key: AGENTS_SWITCH_KV_KEY, value: "not-json{{" });
  assert.deepEqual(await getAgentsSwitch(db), {
    global: { state: "off", setAt: null, setBy: null },
    slugs: {},
  });
});

test("agents switch: unexpected global state value fails closed (OFF)", async () => {
  const { q } = await setup();
  const db = q as unknown as Parameters<typeof getAgentsSwitch>[0];
  await q.insert(kv).values({
    key: AGENTS_SWITCH_KV_KEY,
    value: JSON.stringify({ global: { state: "maybe", setAt: 1, setBy: "x" } }),
  });
  const view = await getAgentsSwitch(db);
  assert.equal(view.global.state, "off", "only an explicit 'on' enables agents");
});

test("agents switch: malformed slug entry fails closed for that slug only", async () => {
  const { q } = await setup();
  const db = q as unknown as Parameters<typeof getAgentsSwitch>[0];
  await q.insert(kv).values({
    key: AGENTS_SWITCH_KV_KEY,
    value: JSON.stringify({
      global: { state: "on", setAt: 1, setBy: "x" },
      slugs: { product: { state: "wut" }, analyst: { state: "off", setAt: 2, setBy: "y" } },
    }),
  });
  const view = await getAgentsSwitch(db);
  assert.equal(view.global.state, "on");
  assert.equal(effectiveSwitchState(view, "product"), "off", "malformed slug entry -> off");
  assert.equal(effectiveSwitchState(view, "analyst"), "off", "explicit slug off");
  assert.equal(effectiveSwitchState(view, "marketing"), "on", "untouched slug -> on");
});
