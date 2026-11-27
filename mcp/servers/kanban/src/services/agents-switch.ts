/**
 * Agents master switch — the global on/off gate for ALL standing agents
 * (product / strategist / marketing / analyst) plus per-agent (per-slug)
 * overrides (v2).
 *
 * State lives in the durable `kv` table (key `agents_master_switch`), so it
 * survives restarts and is readable by every orchestrator tick. The
 * fail-safe default is OFF: a missing or malformed row means agents are
 * disabled — the switch can only ever LEAVE agents running when someone
 * explicitly set `on`.
 *
 * Document shape (v2, single row):
 *   {
 *     "global": { "state": "on"|"off", "setAt": <epoch ms>, "setBy": <alias> },
 *     "slugs":  { "<slug>": { "state": "on"|"off", "setAt": ..., "setBy": ... } }
 *   }
 * A v1 row (flat `{state, setAt, setBy}`) is read as the global entry — no
 * migration needed. A slug entry is optional: when absent, the slug is
 * governed by the global switch alone (default "on" per slug).
 *
 * Effective state for a slug: global OFF -> OFF (always). Global ON -> the
 * slug's own entry (absent -> ON; present but malformed -> OFF, fail-closed).
 *
 * Semantics (v2 — hard kill):
 *  - OFF (global or per-slug): the orchestrator does not START agent-owned
 *    cards for that scope (tick() zeroes the slot / skips the card;
 *    startTask() returns 409) AND kills in-flight agent tasks in that scope
 *    — the session is aborted and the task returns to the backlog, where it
 *    resumes automatically when the switch is flipped back on (resume from
 *    last_commit). Non-agent board work is unaffected.
 *  - ON: normal operation (agent cards start per the AGENT_CONCURRENT_TASKS
 *    slot gate).
 *
 * Flipping is an ADMIN action (the `agents_switch` MCP tool is in the admin
 * capability set only) — a kill switch is not a control action.
 */
import { eq } from "drizzle-orm";
import { kv } from "../db/tables.js";
import { type Db } from "./common.js";
export const AGENTS_SWITCH_KV_KEY = "agents_master_switch";

export type AgentsSwitchState = "on" | "off";

/** One switch entry (global or per-slug). */
export interface AgentsSwitchEntry {
  state: AgentsSwitchState;
  /** Epoch ms the entry was last set (null = never set; default applied). */
  setAt: number | null;
  /** Caller identity that last set it (null = never set). */
  setBy: string | null;
}

export interface AgentsSwitchView {
  global: AgentsSwitchEntry;
  /** Per-slug entries (only slugs that were explicitly set). */
  slugs: Record<string, AgentsSwitchEntry>;
}

/** The never-set entry (fail-safe OFF for the global scope). */
const OFF_DEFAULT: AgentsSwitchEntry = { state: "off", setAt: null, setBy: null };

function isState(v: unknown): v is AgentsSwitchState {
  return v === "on" || v === "off";
}

/** Normalize one raw entry; malformed -> OFF (fail-closed). */
function normalizeEntry(raw: unknown): AgentsSwitchEntry {
  if (raw === null || typeof raw !== "object") return { ...OFF_DEFAULT };
  const p = raw as { state?: unknown; setAt?: unknown; setBy?: unknown };
  const entry: AgentsSwitchEntry = {
    state: isState(p.state) ? p.state : "off",
    setAt: typeof p.setAt === "number" ? p.setAt : null,
    setBy: typeof p.setBy === "string" ? p.setBy : null,
  };
  return entry;
}

/**
 * Read the switch. Missing row or malformed value -> global OFF, no slugs
 * (fail-safe). Never throws: a switch read failure must not break the board
 * — it fails closed (agents stay off) and logs.
 */
export async function getAgentsSwitch(db: Db): Promise<AgentsSwitchView> {
  try {
    const [row] = await db.select().from(kv).where(eq(kv.key, AGENTS_SWITCH_KV_KEY));
    if (!row) return { global: { ...OFF_DEFAULT }, slugs: {} };
    const parsed: unknown = JSON.parse(row.value);
    if (parsed === null || typeof parsed !== "object") {
      return { global: { ...OFF_DEFAULT }, slugs: {} };
    }
    const doc = parsed as {
      global?: unknown;
      slugs?: unknown;
      // v1 flat shape (backward compat):
      state?: unknown;
      setAt?: unknown;
      setBy?: unknown;
    };
    // v2: explicit global entry. v1: flat state/setAt/setBy.
    let global: AgentsSwitchEntry;
    if (doc.global !== undefined) {
      global = normalizeEntry(doc.global);
    } else if (isState(doc.state)) {
      global = normalizeEntry({
        state: doc.state,
        setAt: doc.setAt,
        setBy: doc.setBy,
      });
    } else {
      global = { ...OFF_DEFAULT };
    }
    const slugs: Record<string, AgentsSwitchEntry> = {};
    if (doc.slugs !== null && typeof doc.slugs === "object") {
      for (const [slug, raw] of Object.entries(doc.slugs as Record<string, unknown>)) {
        slugs[slug] = normalizeEntry(raw);
      }
    }
    return { global, slugs };
  } catch (err) {
    console.error("[agents-switch] read failed — failing closed (off):", err);
    return { global: { ...OFF_DEFAULT }, slugs: {} };
  }
}

/** Effective state for a slug: global OFF dominates; absent slug entry -> ON. */
export function effectiveSwitchState(view: AgentsSwitchView, slug: string): AgentsSwitchState {
  if (view.global.state === "off") return "off";
  const entry = view.slugs[slug];
  if (!entry) return "on";
  return entry.state;
}

/** Serialize the document (v2 shape). */
function toDocument(view: AgentsSwitchView): string {
  return JSON.stringify({ global: view.global, slugs: view.slugs });
}

/**
 * Persist a view (read-modify-write upsert — dialect-neutral; the row is
 * single and flips are rare, so a select + update/insert is contention-free
 * for this purpose).
 */
async function writeSwitch(db: Db, view: AgentsSwitchView): Promise<void> {
  const value = toDocument(view);
  const [existing] = await db.select().from(kv).where(eq(kv.key, AGENTS_SWITCH_KV_KEY));
  if (existing) {
    await db.update(kv).set({ value }).where(eq(kv.key, AGENTS_SWITCH_KV_KEY));
  } else {
    await db.insert(kv).values({ key: AGENTS_SWITCH_KV_KEY, value });
  }
}

/**
 * Set the GLOBAL switch (preserves per-slug entries). `setBy` = caller
 * identity (MCP key alias) for the audit trail. Returns the new view.
 */
export async function setAgentsSwitchGlobal(
  db: Db,
  state: AgentsSwitchState,
  setBy: string,
): Promise<AgentsSwitchView> {
  const current = await getAgentsSwitch(db);
  const view: AgentsSwitchView = {
    global: { state, setAt: Date.now(), setBy },
    slugs: current.slugs,
  };
  await writeSwitch(db, view);
  return view;
}

/**
 * Set a PER-SLUG switch (preserves the global entry and other slugs). The
 * slug must be a known standing agent (AGENT_SLUGS) — unknown slugs are
 * rejected so a typo can't create a phantom entry. Returns the new view.
 */
export async function setAgentsSwitchSlug(
  db: Db,
  slug: string,
  state: AgentsSwitchState,
  setBy: string,
  allowedSlugs: readonly string[],
): Promise<AgentsSwitchView> {
  if (!allowedSlugs.includes(slug)) {
    throw new Error(
      `unknown agent slug '${slug}' (known: ${allowedSlugs.join(", ") || "none"})`,
    );
  }
  const current = await getAgentsSwitch(db);
  const view: AgentsSwitchView = {
    global: current.global,
    slugs: { ...current.slugs, [slug]: { state, setAt: Date.now(), setBy } },
  };
  await writeSwitch(db, view);
  return view;
}
