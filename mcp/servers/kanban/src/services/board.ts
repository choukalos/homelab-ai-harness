/**
 * Board service (requirements §9, PLAN.md §4): the global board landing
 * page — tasks grouped by state (Backlog / Running / Deploy / Done /
 * Needs Attention) with per-card project tag, usage so far, and
 * dependency status, plus the header stats (spend this month + items
 * completed this month).
 *
 * Dependency status (PLAN.md §2): a task's effective deps are its idea's
 * `depends_on` (idea ids); a dep is satisfied when the referenced idea has
 * a `done` task. Unsatisfied deps are reported as `waitingOn`.
 */
import { and, eq, gte, isNotNull, lt, sql } from "drizzle-orm";
import { ideas, projects, tasks, usage, TASK_STATES, type TaskState } from "../db/schema.js";
import type { Db } from "./common.js";

export interface BoardCard {
  taskId: number;
  projectName: string;
  /** Idea text (1:1 with the task). */
  title: string;
  state: TaskState;
  paused: boolean;
  /** Usage total (cost) across all roles for this task. */
  cost: number;
  /** Texts of ideas this task is still waiting on (empty = deps satisfied). */
  waitingOn: string[];
}

export interface BoardData {
  columns: Array<{ state: TaskState; cards: BoardCard[] }>;
  month: { spend: number; completed: number };
}

export async function board(db: Db): Promise<BoardData> {
  const taskRows = await db.select().from(tasks);
  const projectRows = await db.select({ id: projects.id, name: projects.name }).from(projects);
  const ideaRows = await db.select().from(ideas);
  const usageRows = await db
    .select({
      taskId: usage.taskId,
      total: sql<number>`coalesce(sum(${usage.cost}), 0)`,
    })
    .from(usage)
    .where(isNotNull(usage.taskId))
    .groupBy(usage.taskId);

  const projectById = new Map(projectRows.map((r) => [r.id, r.name]));
  const ideaById = new Map(ideaRows.map((r) => [r.id, r]));
  const costByTask = new Map(usageRows.map((r) => [r.taskId as number, r.total]));
  const doneIdeaIds = new Set(taskRows.filter((t) => t.state === "done").map((t) => t.ideaId));

  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
  const monthEnd = new Date(now.getFullYear(), now.getMonth() + 1, 1).getTime();

  const spendRow = await db
    .select({ total: sql<number>`coalesce(sum(${usage.cost}), 0)` })
    .from(usage)
    .where(and(gte(usage.ts, monthStart), lt(usage.ts, monthEnd)));
  const doneRow = await db
    .select({ total: sql<number>`coalesce(count(*), 0)` })
    .from(tasks)
    .where(
      and(eq(tasks.state, "done"), gte(tasks.stateChangedAt, monthStart), lt(tasks.stateChangedAt, monthEnd)),
    );

  const cards = taskRows.map(
    (t): BoardCard => {
      const idea = ideaById.get(t.ideaId);
      const deps = idea?.dependsOn ?? [];
      const waitingOn = deps
        .map((depId) => ideaById.get(depId))
        .filter((dep): dep is NonNullable<typeof dep> => dep !== undefined && !doneIdeaIds.has(dep.id))
        .map((dep) => dep.text);
      return {
        taskId: t.id,
        projectName: projectById.get(t.projectId) ?? "?",
        title: idea?.text ?? `task ${t.id}`,
        state: t.state as TaskState,
        paused: t.paused,
        cost: costByTask.get(t.id) ?? 0,
        waitingOn,
      };
    },
  );

  return {
    columns: TASK_STATES.map((state) => ({
      state,
      cards: cards.filter((c) => c.state === state).sort((a, b) => a.taskId - b.taskId),
    })),
    month: {
      spend: spendRow[0]?.total ?? 0,
      completed: doneRow[0]?.total ?? 0,
    },
  };
}
