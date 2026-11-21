/**
 * Icebox → Backlog (requirements §5, PLAN.md §4): the user selects one or
 * more finalized specs and moves them to the board's backlog. Each move
 * creates the 1:1 task (state `backlog`, spec snapshot) and flips the idea
 * to `moved`. The orchestrator (Slice 3) picks backlog tasks up, enforcing
 * dependency order.
 */
import { and, eq, inArray } from "drizzle-orm";
import { type IdeaSpec } from "../db/schema.js";
import { ideas, projects, tasks } from "../db/tables.js";
import { ServiceError, type Db } from "./common.js";
import { type Idea } from "./ideas.js";

export interface IceboxMoveResult {
  /** Ideas that were moved (state now `moved`). */
  ideas: Idea[];
  /** Tasks created in the backlog (one per idea; owner inherited from the idea). */
  tasks: Array<{ id: number; ideaId: number; projectId: number; state: "backlog"; owner: string }>;
}

/**
 * Move one or more icebox ideas to the board backlog.
 *
 * All ideas are validated first (exist, state `icebox`, spec present); then
 * tasks are created and ideas flipped. 404 on unknown idea, 409 on an idea
 * that is not a finalized icebox item, 400 on an empty list.
 */
export async function moveIceboxToBacklog(db: Db, ideaIds: number[]): Promise<IceboxMoveResult> {
  const ids = [...new Set(ideaIds)];
  if (ids.length === 0) {
    throw new ServiceError(400, "no icebox items selected");
  }

  const rows = await db
    .select({ idea: ideas, projectName: projects.name })
    .from(ideas)
    .innerJoin(projects, eq(ideas.projectId, projects.id))
    .where(inArray(ideas.id, ids));
  const byId = new Map<number, Idea>(rows.map((r) => [r.idea.id, { ...r.idea, projectName: r.projectName }]));
  for (const id of ids) {
    const row = byId.get(id);
    if (!row) throw new ServiceError(404, `idea ${id} not found`);
    if (row.state !== "icebox") {
      throw new ServiceError(409, `idea ${id} is not in the icebox (state: ${row.state})`);
    }
    if (!row.spec) {
      throw new ServiceError(409, `idea ${id} has no finalized spec (state: ${row.state})`);
    }
  }

  const now = Date.now();
  const ideasOut: Idea[] = [];
  const tasksOut: IceboxMoveResult["tasks"] = [];
  for (const id of ids) {
    const idea = byId.get(id)!;
    await db
      .insert(tasks)
      .values({
        ideaId: idea.id,
        projectId: idea.projectId,
        spec: idea.spec as IdeaSpec,
        state: "backlog",
        stateChangedAt: now,
        // Owner = the idea's owner (who asked for the work), not the caller
        // of the move.
        owner: idea.owner,
        createdAt: now,
      });
    // Single-user app: the newest backlog task of this idea is ours (1:1).
    const [task] = await db
      .select()
      .from(tasks)
      .where(and(eq(tasks.ideaId, idea.id), eq(tasks.state, "backlog")))
      .limit(1);
    if (!task) throw new ServiceError(500, "task insert did not persist");
    await db
      .update(ideas)
      .set({ state: "moved", updatedAt: now })
      .where(eq(ideas.id, idea.id));
    ideasOut.push({ ...idea, state: "moved" });
    tasksOut.push({ id: task.id, ideaId: idea.id, projectId: idea.projectId, state: "backlog", owner: task.owner });
  }
  return { ideas: ideasOut, tasks: tasksOut };
}
