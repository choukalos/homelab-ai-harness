/**
 * Agents master switch — the global on/off gate for ALL standing agents
 * (product / strategist / marketing / analyst).
 *
 * State lives in the durable `kv` table (key `agents_master_switch`), so it
 * survives restarts and is readable by every orchestrator tick. The
 * fail-safe default is OFF: a missing or malformed row means agents are
 * disabled — the switch can only ever LEAVE agents running when someone
 * explicitly set `on`.
 *
 * Semantics (v1):
 *  - OFF: the orchestrator does not START agent-owned cards — tick() zeroes
 *    the agent slot and startTask() on an agent card returns 409. In-flight
 *    agent tasks run to completion (no mid-session kill in v1).
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

export interface AgentsSwitchView {
  state: AgentsSwitchState;
  /** Epoch ms the state was last set (null = never set; default applied). */
  setAt: number | null;
  /** Caller identity that last set it (null = never set). */
  setBy: string | null;
}

/**
 * Read the switch. Missing row or malformed value -> OFF (fail-safe).
 * Never throws: a switch read failure must not break the board — it fails
 * closed (agents stay off) and logs.
 */
export async function getAgentsSwitch(db: Db): Promise<AgentsSwitchView> {
  try {
    const [row] = await db.select().from(kv).where(eq(kv.key, AGENTS_SWITCH_KV_KEY));
    if (!row) return { state: "off", setAt: null, setBy: null };
    const parsed: unknown = JSON.parse(row.value);
    if (
      parsed !== null &&
      typeof parsed === "object" &&
      (parsed as { state?: unknown }).state === "on"
    ) {
      const p = parsed as { state: AgentsSwitchState; setAt?: unknown; setBy?: unknown };
      return {
        state: "on",
        setAt: typeof p.setAt === "number" ? p.setAt : null,
        setBy: typeof p.setBy === "string" ? p.setBy : null,
      };
    }
    // state === "off" (or anything unexpected) -> fail-safe OFF.
    const p =
      parsed !== null && typeof parsed === "object"
        ? (parsed as { setAt?: unknown; setBy?: unknown })
        : {};
    return {
      state: "off",
      setAt: typeof p.setAt === "number" ? p.setAt : null,
      setBy: typeof p.setBy === "string" ? p.setBy : null,
    };
  } catch (err) {
    console.error("[agents-switch] read failed — failing closed (off):", err);
    return { state: "off", setAt: null, setBy: null };
  }
}

/**
 * Set the switch (read-modify-write upsert — dialect-neutral; the row is
 * single and flips are rare, so a select + update/insert is contention-free
 * for this purpose). `setBy` = caller identity (MCP key alias) for the
 * audit trail. Returns the new view.
 */
export async function setAgentsSwitch(
  db: Db,
  state: AgentsSwitchState,
  setBy: string,
): Promise<AgentsSwitchView> {
  const setAt = Date.now();
  const value = JSON.stringify({ state, setAt, setBy });
  const [existing] = await db.select().from(kv).where(eq(kv.key, AGENTS_SWITCH_KV_KEY));
  if (existing) {
    await db.update(kv).set({ value }).where(eq(kv.key, AGENTS_SWITCH_KV_KEY));
  } else {
    await db.insert(kv).values({ key: AGENTS_SWITCH_KV_KEY, value });
  }
  return { state, setAt, setBy };
}
