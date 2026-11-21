/**
 * Usage accounting (PLAN.md §2/§11): one row per LLM call, tagged by
 * task/project/role + thinking level + owner. Reporting only — no limits.
 * `taskId` is nullable for grooming/summary calls.
 */
import { type UsageRole } from "../db/schema.js";
import { usage } from "../db/tables.js";
import type { Db } from "./common.js";

export interface UsageRecord {
  projectId: number;
  /** Null for grooming/summary calls. */
  taskId?: number | null;
  role: UsageRole;
  model: string;
  thinking: string | null;
  tokensIn: number;
  tokensOut: number;
  cost: number;
  /**
   * Owner whose key this LLM call billed to (Phase 2): the owner name when
   * the session ran on a USER_KEYS profile, else '' (service key / unmapped
   * owner / legacy rows).
   */
  owner?: string;
}

/** Insert one usage row. */
export async function recordUsage(db: Db, rec: UsageRecord): Promise<void> {
  await db.insert(usage).values({
    projectId: rec.projectId,
    taskId: rec.taskId ?? null,
    ts: Date.now(),
    role: rec.role,
    model: rec.model,
    thinking: rec.thinking,
    tokensIn: rec.tokensIn,
    tokensOut: rec.tokensOut,
    cost: rec.cost,
    owner: rec.owner ?? "",
  });
}
