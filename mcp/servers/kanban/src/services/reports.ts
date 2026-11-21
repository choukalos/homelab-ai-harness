/**
 * Usage reports (PLAN.md §5/§6 Slice 4, requirements §11): rolling-12-month
 * $ spend (per month + total), per-project completed-item count + $ spend,
 * and the per-task usage table (filterable). Reporting only — no limits.
 *
 * Aggregation runs in JS over the usage/tasks/ideas/projects rows (same
 * style as board()) so the queries stay identical across both DB drivers.
 */
import { and, desc, eq, gte, inArray, lt } from "drizzle-orm";
import { ideas, projects, tasks, usage, type TaskState } from "../db/schema.js";
import type { Db } from "./common.js";

export const ROLLING_MONTHS = 12;

export interface MonthBucket {
  /** "YYYY-MM" (local time, consistent with the board's month stats). */
  key: string;
  /** "Nov 2026" (full label). */
  label: string;
  /** "Nov" (short chart label). */
  short: string;
  /** Window start (inclusive), epoch ms. */
  start: number;
  /** Window end (exclusive), epoch ms. */
  end: number;
  spend: number;
}

const MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function keyOf(ts: number): string {
  const d = new Date(ts);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/**
 * Rolling window: the current month + the `months - 1` months before it,
 * oldest first. Boundaries are the first of each month (local time).
 */
export function monthWindow(now: number = Date.now(), months: number = ROLLING_MONTHS): MonthBucket[] {
  const d = new Date(now);
  const out: MonthBucket[] = [];
  for (let i = months - 1; i >= 0; i--) {
    const start = new Date(d.getFullYear(), d.getMonth() - i, 1).getTime();
    const end = new Date(d.getFullYear(), d.getMonth() - i + 1, 1).getTime();
    const s = new Date(start);
    const short = MONTHS_SHORT[s.getMonth()] ?? "?";
    out.push({
      key: keyOf(start),
      label: `${short} ${s.getFullYear()}`,
      short,
      start,
      end,
      spend: 0,
    });
  }
  return out;
}

export interface SpendReport {
  /** 12 buckets, oldest → newest (current month last). */
  months: MonthBucket[];
  /** Total $ spend across the rolling window. */
  total: number;
}

/** $ spend per month, rolling 12 months (all roles, all projects). */
export async function spendByMonth(db: Db, now: number = Date.now()): Promise<SpendReport> {
  const months = monthWindow(now);
  const start = months[0]!.start;
  const end = months[months.length - 1]!.end;
  const rows = await db
    .select({ ts: usage.ts, cost: usage.cost })
    .from(usage)
    .where(and(gte(usage.ts, start), lt(usage.ts, end)));
  const byKey = new Map(months.map((m) => [m.key, m]));
  let total = 0;
  for (const r of rows) {
    const bucket = byKey.get(keyOf(r.ts));
    if (bucket) {
      bucket.spend += r.cost;
      total += r.cost;
    }
  }
  return { months, total };
}

export interface ProjectReportRow {
  id: number;
  name: string;
  /** Completed (state `done`) items whose completion fell in the window. */
  completed: number;
  /** $ spend (all roles) in the window. */
  spend: number;
}

/**
 * Per-user $ spend, rolling 12 months (Phase 2). One row per owner present
 * in the window's usage rows; `owner` '' = unattributed (service key / legacy
 * rows). `byMonth` is keyed by the same month keys as `monthWindow` (the
 * template aligns columns against the total-spend buckets).
 */
export interface OwnerSpendRow {
  /** Owner name ('' = unattributed). */
  owner: string;
  /** $ spend per month key (only months with spend; absent = 0). */
  byMonth: Record<string, number>;
  /** Total $ spend across the rolling window. */
  total: number;
}

/**
 * Per-user $ spend per month, rolling 12 months. All roles, all projects;
 * rows sorted by total (desc), unattributed last.
 */
export async function spendByOwner(db: Db, now: number = Date.now()): Promise<OwnerSpendRow[]> {
  const months = monthWindow(now);
  const start = months[0]!.start;
  const end = months[months.length - 1]!.end;
  const rows = await db
    .select({ ts: usage.ts, cost: usage.cost, owner: usage.owner })
    .from(usage)
    .where(and(gte(usage.ts, start), lt(usage.ts, end)));
  const byOwner = new Map<string, OwnerSpendRow>();
  for (const r of rows) {
    const row = byOwner.get(r.owner) ?? { owner: r.owner, byMonth: {}, total: 0 };
    const key = keyOf(r.ts);
    row.byMonth[key] = (row.byMonth[key] ?? 0) + r.cost;
    row.total += r.cost;
    byOwner.set(r.owner, row);
  }
  return [...byOwner.values()].sort(
    (a, b) =>
      Number(a.owner === "") - Number(b.owner === "") || b.total - a.total || a.owner.localeCompare(b.owner),
  );
}

/** Per-project completed-item count + $ spend, rolling 12 months. */
export async function projectStats(db: Db, now: number = Date.now()): Promise<ProjectReportRow[]> {
  const months = monthWindow(now);
  const start = months[0]!.start;
  const end = months[months.length - 1]!.end;
  const [projectRows, usageRows, doneRows] = await Promise.all([
    db.select({ id: projects.id, name: projects.name }).from(projects),
    db
      .select({ projectId: usage.projectId, cost: usage.cost })
      .from(usage)
      .where(and(gte(usage.ts, start), lt(usage.ts, end))),
    db
      .select({ projectId: tasks.projectId })
      .from(tasks)
      .where(and(eq(tasks.state, "done"), gte(tasks.stateChangedAt, start), lt(tasks.stateChangedAt, end))),
  ]);
  const spend = new Map<number, number>();
  for (const r of usageRows) spend.set(r.projectId, (spend.get(r.projectId) ?? 0) + r.cost);
  const completed = new Map<number, number>();
  for (const r of doneRows) completed.set(r.projectId, (completed.get(r.projectId) ?? 0) + 1);
  return projectRows
    .map((p) => ({
      id: p.id,
      name: p.name,
      completed: completed.get(p.id) ?? 0,
      spend: spend.get(p.id) ?? 0,
    }))
    .sort((a, b) => b.spend - a.spend || a.name.localeCompare(b.name));
}

export interface TaskUsageFilters {
  projectId?: number;
  state?: TaskState;
  /** Usage role (groom/task/qa/summary/resolve). */
  role?: string;
  /** Case-insensitive substring match on the task (idea) title. */
  q?: string;
}

export interface TaskUsageRow {
  taskId: number;
  projectId: number;
  project: string;
  /** Idea text (1:1 with the task). */
  title: string;
  state: string;
  /** Totals respect the filters (when given). */
  tokensIn: number;
  tokensOut: number;
  cost: number;
  /** Cost per role among the rows matching the filters. */
  byRole: Record<string, number>;
}

/**
 * Per-task usage table (filterable). One row per task that has usage
 * matching the filters; all columns (tokens, cost, byRole) reflect the
 * applied filters. Sorted by cost (desc).
 */
export async function taskUsageTable(db: Db, filters: TaskUsageFilters = {}): Promise<TaskUsageRow[]> {
  const [usageRows, taskRows, ideaRows, projectRows] = await Promise.all([
    db.select().from(usage),
    db.select().from(tasks),
    db.select({ id: ideas.id, text: ideas.text }).from(ideas),
    db.select({ id: projects.id, name: projects.name }).from(projects),
  ]);
  const taskById = new Map(taskRows.map((t) => [t.id, t]));
  const ideaById = new Map(ideaRows.map((i) => [i.id, i]));
  const projectName = new Map(projectRows.map((p) => [p.id, p.name]));
  const q = filters.q?.trim().toLowerCase();

  const acc = new Map<number, TaskUsageRow>();
  for (const u of usageRows) {
    if (u.taskId === null) continue; // grooming/summary rows carry no task
    const t = taskById.get(u.taskId);
    if (!t) continue;
    if (filters.projectId !== undefined && t.projectId !== filters.projectId) continue;
    if (filters.state && t.state !== filters.state) continue;
    if (filters.role && u.role !== filters.role) continue;
    const title = ideaById.get(t.ideaId)?.text ?? `task ${t.id}`;
    if (q && !title.toLowerCase().includes(q)) continue;

    const row = acc.get(t.id) ?? {
      taskId: t.id,
      projectId: t.projectId,
      project: projectName.get(t.projectId) ?? "?",
      title,
      state: t.state,
      tokensIn: 0,
      tokensOut: 0,
      cost: 0,
      byRole: {},
    };
    row.tokensIn += u.tokensIn;
    row.tokensOut += u.tokensOut;
    row.cost += u.cost;
    row.byRole[u.role] = (row.byRole[u.role] ?? 0) + u.cost;
    acc.set(t.id, row);
  }
  return [...acc.values()].sort((a, b) => b.cost - a.cost || a.taskId - b.taskId);
}

/**
 * Completed/deployed items of one project (state `done`), newest first,
 * paginated (project page: hidden by default, paginated — requirements §9).
 */
export interface CompletedItem {
  taskId: number;
  title: string;
  /** When the task reached `done` (stateChangedAt). */
  finishedAt: number;
  cost: number;
}

export interface CompletedPage {
  items: CompletedItem[];
  page: number;
  pageSize: number;
  total: number;
  pageCount: number;
}

export async function projectCompleted(
  db: Db,
  projectId: number,
  page: number = 1,
  pageSize: number = 10,
): Promise<CompletedPage> {
  const size = Math.max(1, Math.floor(pageSize));
  const rows = await db
    .select()
    .from(tasks)
    .where(and(eq(tasks.projectId, projectId), eq(tasks.state, "done")))
    .orderBy(desc(tasks.stateChangedAt), desc(tasks.id));
  const total = rows.length;
  const pageCount = Math.max(1, Math.ceil(total / size));
  // Clamp the requested page into range (page out of range → last page).
  const p = Math.min(Math.max(1, Math.floor(page)), pageCount);
  const pageRows = rows.slice((p - 1) * size, p * size);
  const items: CompletedItem[] = [];
  if (pageRows.length > 0) {
    const ideaRows = await db
      .select({ id: ideas.id, text: ideas.text })
      .from(ideas)
      .where(inArray(ideas.id, pageRows.map((t) => t.ideaId)));
    const ideaById = new Map(ideaRows.map((i) => [i.id, i]));
    const usageRows = await db
      .select({ taskId: usage.taskId, cost: usage.cost })
      .from(usage)
      .where(inArray(usage.taskId, pageRows.map((t) => t.id)));
    const costByTask = new Map<number, number>();
    for (const u of usageRows) {
      if (u.taskId === null) continue;
      costByTask.set(u.taskId, (costByTask.get(u.taskId) ?? 0) + u.cost);
    }
    for (const t of pageRows) {
      items.push({
        taskId: t.id,
        title: ideaById.get(t.ideaId)?.text ?? `task ${t.id}`,
        finishedAt: t.stateChangedAt,
        cost: costByTask.get(t.id) ?? 0,
      });
    }
  }
  return {
    items,
    page: p,
    pageSize: size,
    total,
    pageCount,
  };
}
