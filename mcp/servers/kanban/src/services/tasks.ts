/**
 * Task services (Slice 3a/3c, PLAN.md §2/§4/§5): task detail (state,
 * workspace, branch, usage, log tail) + task_events appends + dependency
 * gating + task status (MCP task_status). Transport-agnostic: used by the
 * REST task detail page, the orchestrator, and the MCP tools.
 */
import { and, desc, eq, inArray, sql } from "drizzle-orm";
import {
  ideas,
  projects,
  taskEvents,
  tasks,
  usage,
  type EventPayload,
  type TaskEventRow,
  type TaskEventType,
  type TaskRow,
} from "../db/schema.js";
import { type Db } from "./common.js";

/** Append one task_event row (log tail + audit trail, PLAN.md §2). */
export async function appendTaskEvent(
  db: Db,
  taskId: number,
  type: TaskEventType,
  payload: EventPayload,
): Promise<void> {
  await db.insert(taskEvents).values({ taskId, ts: Date.now(), type, payload });
}

export interface DependencyStatus {
  /** Dep idea ids without a done task yet. */
  waitingOn: number[];
  satisfied: boolean;
}

/**
 * Dependency gating (PLAN.md §2/§4): a task's effective deps are its idea's
 * `depends_on` (idea ids); satisfied when every referenced idea has a `done`
 * task. If a dep is still in the icebox, the task simply waits.
 */
export async function taskDependencyStatus(db: Db, ideaId: number): Promise<DependencyStatus> {
  const [idea] = await db
    .select({ dependsOn: ideas.dependsOn })
    .from(ideas)
    .where(eq(ideas.id, ideaId))
    .limit(1);
  const deps = idea?.dependsOn ?? [];
  if (deps.length === 0) return { waitingOn: [], satisfied: true };
  const done = await db
    .select({ ideaId: tasks.ideaId })
    .from(tasks)
    .where(and(inArray(tasks.ideaId, deps), eq(tasks.state, "done")));
  const doneIds = new Set(done.map((t) => t.ideaId));
  const waitingOn = deps.filter((d) => !doneIds.has(d));
  return { waitingOn, satisfied: waitingOn.length === 0 };
}

export interface TaskDetail {
  task: TaskRow;
  project: { id: number; name: string };
  idea: { id: number; text: string; dependsOn: number[] | null };
  /** Total usage cost across all roles for this task. */
  usageTotal: number;
  /** Cost per role (task/qa/...). */
  usageByRole: Record<string, number>;
  /** Last `logLimit` task_events, chronological. */
  log: TaskEventRow[];
  /** Texts of ideas this task is still waiting on (empty = deps satisfied). */
  waitingOn: string[];
}

/** Full task detail for the task page / MCP task_status (undefined when missing). */
export async function getTaskDetail(db: Db, taskId: number, logLimit = 200): Promise<TaskDetail | undefined> {
  const [task] = await db.select().from(tasks).where(eq(tasks.id, taskId)).limit(1);
  if (!task) return undefined;

  const [project] = await db
    .select({ id: projects.id, name: projects.name })
    .from(projects)
    .where(eq(projects.id, task.projectId))
    .limit(1);
  const [idea] = await db
    .select({ id: ideas.id, text: ideas.text, dependsOn: ideas.dependsOn })
    .from(ideas)
    .where(eq(ideas.id, task.ideaId))
    .limit(1);

  const usageRows = await db
    .select({ role: usage.role, total: sql<number>`coalesce(sum(${usage.cost}), 0)` })
    .from(usage)
    .where(eq(usage.taskId, taskId))
    .groupBy(usage.role);
  const usageByRole: Record<string, number> = {};
  let usageTotal = 0;
  for (const r of usageRows) {
    usageByRole[r.role] = r.total;
    usageTotal += r.total;
  }

  const logDesc = await db
    .select()
    .from(taskEvents)
    .where(eq(taskEvents.taskId, taskId))
    .orderBy(desc(taskEvents.id))
    .limit(logLimit);
  const log = logDesc.reverse();

  const depStatus = await taskDependencyStatus(db, task.ideaId);
  let waitingOn: string[] = [];
  if (depStatus.waitingOn.length > 0) {
    const depIdeas = await db
      .select({ id: ideas.id, text: ideas.text })
      .from(ideas)
      .where(inArray(ideas.id, depStatus.waitingOn));
    waitingOn = depIdeas.map((i) => i.text);
  }

  return {
    task,
    project: project ?? { id: task.projectId, name: "?" },
    idea: idea ?? { id: task.ideaId, text: `task ${taskId}`, dependsOn: null },
    usageTotal,
    usageByRole,
    log,
    waitingOn,
  };
}

/**
 * Render one task_event as a display log line (shared by the GUI log tail
 * and the MCP task_status log tail). Plain text, truncated to 200 chars.
 */
export function taskEventLine(e: TaskEventRow): string {
  const p = e.payload ?? {};
  switch (e.type) {
    case "log":
      return String(p.line ?? "");
    case "heartbeat":
      // `kind: watchdog` = the Slice 5 liveness heartbeat (no commit attached).
      return p.kind === "watchdog" ? "heartbeat (alive)" : `commit ${String(p.commit ?? "")}`;
    case "state": {
      const from = p.from !== undefined ? String(p.from) : "?";
      const to = p.to !== undefined ? String(p.to) : p.paused !== undefined ? (p.paused ? "paused" : "resumed") : "?";
      let text = `state: ${from} → ${to}`;
      if (p.reason !== undefined) text += ` (${String(p.reason)})`;
      if (p.summary !== undefined) text += ` summary: ${String(p.summary).slice(0, 200)}`;
      return text;
    }
    case "qa":
      return `qa ${p.pass ? "pass" : "fail"}${p.feedback ? `: ${String(p.feedback).slice(0, 200)}` : ""}`;
    case "deploy":
      return `deploy ${String(p.status ?? "")}${p.detail ? `: ${String(p.detail).slice(0, 200)}` : ""}`;
    case "resolve":
      return `resolve${p.accepted ? " (accepted)" : ""}: ${String(p.text ?? "").slice(0, 200)}`;
    case "usage":
      return `usage ${p.tokensIn ?? 0} in / ${p.tokensOut ?? 0} out ($${Number(p.cost ?? 0).toFixed(2)})`;
    default:
      return JSON.stringify(p).slice(0, 200);
  }
}

export interface TaskStatus {
  id: number;
  state: string;
  paused: boolean;
  /** Idea text (1:1 with the task). */
  title: string;
  project: { id: number; name: string };
  /** Owner (inherited from the idea); '' = unattributed (legacy). */
  owner: string;
  branch: string | null;
  lastCommit: string | null;
  qaRounds: number;
  /** Accepted resolution plan (needs_attention → backlog), if any. */
  resolution: string | null;
  usageTotal: number;
  usageByRole: Record<string, number>;
  /** `reason` of the last state event that moved the task to needs_attention. */
  failureReason: string | null;
  /** Last log lines (display text, chronological). */
  logTail: string[];
}

/**
 * Task status for the MCP task_status tool (PLAN.md §5): state, log tail,
 * usage, failure reason (undefined when the task is missing).
 */
export async function getTaskStatus(db: Db, taskId: number, logLimit = 50): Promise<TaskStatus | undefined> {
  const detail = await getTaskDetail(db, taskId, logLimit);
  if (!detail) return undefined;
  const t = detail.task;
  let failureReason: string | null = null;
  for (const e of [...detail.log].reverse()) {
    const p = e.payload ?? {};
    if (e.type === "state" && p.to === "needs_attention" && typeof p.reason === "string") {
      failureReason = p.reason;
      break;
    }
  }
  const logTail = detail.log.map((e) => taskEventLine(e)).filter((l) => l !== "");
  return {
    id: t.id,
    state: t.state,
    paused: t.paused,
    title: detail.idea.text,
    project: detail.project,
    owner: t.owner,
    branch: t.branch,
    lastCommit: t.lastCommit,
    qaRounds: t.qaRounds,
    resolution: t.resolution,
    usageTotal: detail.usageTotal,
    usageByRole: detail.usageByRole,
    failureReason,
    logTail,
  };
}
