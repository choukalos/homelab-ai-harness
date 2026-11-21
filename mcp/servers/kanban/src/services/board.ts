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
import { and, eq, gte, inArray, isNotNull, lt, sql } from "drizzle-orm";
import { TASK_STATES, type TaskState } from "../db/schema.js";
import { ideas, projects, taskEvents, tasks, usage } from "../db/tables.js";
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
  /** Owner (inherited from the idea); '' = unattributed (legacy). */
  owner: string;
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
        owner: t.owner,
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

// ---------------------------------------------------------------------------
// Board status (MCP board_status): a compact, needs-attention-focused view
// of the board for conversational clients — counts per state, and for each
// needs-attention task a summary + what attention it needs (failure reason,
// last activity, accepted resolution if any). Resolve one by one via
// task_status(task_id) → restart_task(task_id, resolution_note).
// ---------------------------------------------------------------------------

export interface BoardStatusFilters {
  projectId?: number;
  /** Only tasks owned by this user (owner column). */
  owner?: string;
}

export interface BoardStatusNeedsAttention {
  taskId: number;
  title: string;
  projectId: number;
  project: string;
  owner: string;
  /** `reason` of the last state event that moved the task to needs_attention. */
  reason: string | null;
  /** Last task_event ts (when the task last did something). */
  lastActivityAt: number | null;
  /** Accepted resolution plan, if one was captured. */
  resolution: string | null;
}

export interface BoardStatusRunning {
  taskId: number;
  title: string;
  projectId: number;
  project: string;
  owner: string;
  paused: boolean;
  /** Usage total (cost) across all roles for this task. */
  cost: number;
}

export interface BoardStatus {
  /** Task counts per board state (all five states always present). */
  counts: Record<string, number>;
  /** Needs-attention tasks with failure context (the dialog entry point). */
  needsAttention: BoardStatusNeedsAttention[];
  /** Running tasks (paused flag + cost so far). */
  running: BoardStatusRunning[];
}

/**
 * Board status for the MCP `board_status` tool (PLAN: MCP-first change).
 * Optional filters: project_id and/or owner.
 */
export async function boardStatus(db: Db, filters: BoardStatusFilters = {}): Promise<BoardStatus> {
  const where = and(
    filters.projectId !== undefined ? eq(tasks.projectId, filters.projectId) : undefined,
    filters.owner !== undefined && filters.owner !== "" ? eq(tasks.owner, filters.owner) : undefined,
  );
  const [taskRows, projectRows, ideaRows, eventRows, usageRows] = await Promise.all([
    where === undefined
      ? db.select().from(tasks)
      : db.select().from(tasks).where(where),
    db.select({ id: projects.id, name: projects.name }).from(projects),
    db.select({ id: ideas.id, text: ideas.text }).from(ideas),
    db.select().from(taskEvents),
    db
      .select({
        taskId: usage.taskId,
        total: sql<number>`coalesce(sum(${usage.cost}), 0)`,
      })
      .from(usage)
      .where(isNotNull(usage.taskId))
      .groupBy(usage.taskId),
  ]);

  const projectById = new Map(projectRows.map((r) => [r.id, r.name]));
  const ideaById = new Map(ideaRows.map((r) => [r.id, r.text]));
  const costByTask = new Map(usageRows.map((r) => [r.taskId as number, r.total]));

  // Per-task event facts: last ts + the last needs_attention failure reason.
  const lastEventTs = new Map<number, number>();
  const failureReason = new Map<number, string>();
  for (const e of eventRows) {
    lastEventTs.set(e.taskId, Math.max(lastEventTs.get(e.taskId) ?? 0, e.ts));
    const p = e.payload ?? {};
    if (e.type === "state" && p.to === "needs_attention" && typeof p.reason === "string") {
      failureReason.set(e.taskId, p.reason); // later events overwrite (chronological order)
    }
  }

  const counts: Record<string, number> = {};
  for (const s of TASK_STATES) counts[s] = 0;
  const needsAttention: BoardStatusNeedsAttention[] = [];
  const running: BoardStatusRunning[] = [];
  for (const t of taskRows) {
    counts[t.state] = (counts[t.state] ?? 0) + 1;
    const base = {
      taskId: t.id,
      title: ideaById.get(t.ideaId) ?? `task ${t.id}`,
      projectId: t.projectId,
      project: projectById.get(t.projectId) ?? "?",
      owner: t.owner,
    };
    if (t.state === "needs_attention") {
      needsAttention.push({
        ...base,
        reason: failureReason.get(t.id) ?? null,
        lastActivityAt: lastEventTs.get(t.id) ?? t.stateChangedAt,
        resolution: t.resolution,
      });
    } else if (t.state === "running") {
      running.push({ ...base, paused: t.paused, cost: costByTask.get(t.id) ?? 0 });
    }
  }
  needsAttention.sort((a, b) => a.taskId - b.taskId);
  running.sort((a, b) => a.taskId - b.taskId);
  return { counts, needsAttention, running };
}
