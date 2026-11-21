/**
 * Orchestrator (PLAN.md §4/§7, Slice 3a/3b): queue, CONCURRENT_TASKS slots,
 * dependency gating, and the task lifecycle state machine.
 *
 * State machine (PLAN.md §4):
 *   backlog ──slot free + all deps done──► running
 *   running ──QA pass──► deploy ──ok──► done (+ project summary update)
 *   running ──QA fail (≤2 rounds)──► running (feedback re-run)
 *   any failure (QA exhausted / deploy fail / stuck / crash) ─► needs_attention
 *   stop ─► paused ──one-click──► running (resume from last_commit)
 *
 * - Every transition updates `state_changed_at` and writes a `state`
 *   task_event (audit trail); the task session writes `log` / `heartbeat`
 *   events (live log tail) and usage rows (role `task`; QA and summary
 *   rows are recorded by the pipeline, roles `qa` / `summary`).
 * - Dependency gating (PLAN.md §2): a task starts only when all of its idea's
 *   `depends_on` ideas have `done` tasks.
 * - The task execution pipeline (TaskRunner), QA gate, deploy stage, and
 *   summary updater are injectable so tests run the full state machine
 *   against mocked sessions/git (no network, no model).
 *
 * Slice 3c: restartTask re-enters the backlog from needs_attention
 * (resolution dialog Accept / MCP restart_task).
 *
 * Slice 5 (resilience, PLAN.md §4/§6):
 * - Pause/resume/stop: stopTask/resumeTask are the state machine behind the
 *   REST (POST /tasks/<id>/pause|resume|stop) and MCP (pause_task /
 *   resume_task / stop_task) controls; `paused` is an orthogonal flag on
 *   running tasks (stop ─► paused ──one-click──► running).
 * - Watchdog: per-task heartbeat (default 60s) written while the session is
 *   alive and producing activity; 10 min of silence → needs_attention +
 *   abort (the GUI shows the reason + last activity).
 * - Auto-resume: on container start, any `running` (non-paused) task is
 *   rehydrated — re-clone/checkout last_commit, restore the Pi session file
 *   (SessionManager.open via the stable session path), re-inject the mission
 *   brief + progress summary, continue.
 * - 7-day workspace cleanup: background job deletes /workspace/task-<id>
 *   dirs older than 7 days (only app-managed dirs; durable results are
 *   pushed by the deploy stage before a task leaves `deploy`).
 */
import path from "node:path";
import { readdir, rm, stat } from "node:fs/promises";
import type { Stats } from "node:fs";
import { and, asc, desc, eq, inArray, sql } from "drizzle-orm";
import type { KanbanConfig } from "./config.js";
import type { DbHandle } from "./db/index.js";
import {
  type EventPayload,
  type TaskEventType,
  type TaskRow,
  type TaskState,
  type UsageRole,
} from "./db/schema.js";
import { ideas, projects, taskEvents, tasks } from "./db/tables.js";
import type { Db } from "./services/common.js";
import { ServiceError } from "./services/common.js";
import { appendTaskEvent, taskDependencyStatus } from "./services/tasks.js";
import { recordUsage } from "./services/usage.js";
import {
  createGitOps,
  TaskAbortedError,
  TaskSessionRunner,
  type TaskRunContext,
  type TaskRunner,
  type UsageSample,
} from "./agent/sessions.js";
import { QaGate, qaFeedbackPrompt, type QaRunContext, type QaVerdict } from "./agent/qa.js";
import { SummaryUpdater, type SummaryUpdateContext } from "./agent/summary.js";
import { DeployRunner, type DeployContext, type DeployResult } from "./deploy/index.js";

/** QA gate as driven by the orchestrator (QaGate or a mock in tests). */
export interface QaGateLike {
  readonly maxRounds: number;
  run(ctx: QaRunContext): Promise<QaVerdict>;
}

/** Deploy stage as driven by the orchestrator (DeployRunner or a mock). */
export interface DeployRunnerLike {
  deploy(ctx: DeployContext): Promise<DeployResult>;
}

/** One-shot project summary updates (SummaryUpdater or a mock). */
export interface SummaryUpdaterLike {
  update(ctx: SummaryUpdateContext): Promise<string>;
}

export interface OrchestratorDeps {
  cfg: KanbanConfig;
  db: DbHandle;
  agent: import("./agent/sessions.js").AgentRuntime;
  /** Task execution pipeline (default: a TaskSessionRunner over the agent). */
  tasks?: TaskRunner;
  /** QA gate (default: a QaGate over the agent). */
  qa?: QaGateLike;
  /** Deploy stage (default: a DeployRunner with real git). */
  deploy?: DeployRunnerLike;
  /** One-shot project summary updates (default: a SummaryUpdater over the agent). */
  summary?: SummaryUpdaterLike;
  /** Workspace root for task dirs (default: AI_KANBAN_WORKSPACE_DIR env, else /workspace). */
  workspaceRoot?: string;
  /** Tick interval for the pickup loop (default 5000ms). */
  tickMs?: number;
  /** Don't start the interval timers (tests drive tick()/watchdogTick()/
   * cleanupWorkspaces() manually). Auto-resume on start() still runs. */
  noTimer?: boolean;
  /** Watchdog + cleanup interval (default 30000ms). */
  watchdogTickMs?: number;
  /** Heartbeat cadence per running task (default 60000ms — PLAN.md §4). */
  heartbeatMs?: number;
  /** Silence before the watchdog moves a task to needs_attention (default 10 min). */
  watchdogTimeoutMs?: number;
  /** Workspace cleanup cadence (default 24h). */
  cleanupIntervalMs?: number;
  /** Age before /workspace/task-<id> dirs are deleted (default 7 days). */
  cleanupAgeMs?: number;
  /** Clock (injectable for tests; default Date.now). */
  now?: () => number;
}

/** Default resilience timings (PLAN.md §4: 60s heartbeat, 10 min silence, 7-day cleanup). */
export const WATCHDOG_DEFAULTS = {
  heartbeatMs: 60_000,
  timeoutMs: 600_000,
  tickMs: 30_000,
  cleanupIntervalMs: 86_400_000,
  cleanupAgeMs: 7 * 86_400_000,
} as const;

export class Orchestrator {
  private running = false;
  private timer: NodeJS.Timeout | undefined;
  private readonly db: Db;
  private readonly tasks: TaskRunner;
  private readonly qa: QaGateLike;
  private readonly deployRunner: DeployRunnerLike;
  private readonly summaryUpdater: SummaryUpdaterLike;
  private readonly workspaceRoot: string;
  /** In-flight task pipelines, per task. */
  private readonly pipelines = new Map<number, Promise<void>>();
  private watchdogTimer: NodeJS.Timeout | undefined;
  private cleanupTimer: NodeJS.Timeout | undefined;
  private readonly heartbeatMs: number;
  private readonly watchdogTimeoutMs: number;
  private readonly cleanupAgeMs: number;
  private readonly now: () => number;
  /** Last session activity per task (log/commit/usage; feeds the watchdog). */
  private readonly activityAt = new Map<number, number>();
  /** Last watchdog heartbeat written per task. */
  private readonly lastHeartbeatAt = new Map<number, number>();

  constructor(private readonly deps: OrchestratorDeps) {
    this.db = deps.db.db as unknown as Db;
    this.tasks = deps.tasks ?? new TaskSessionRunner({ agent: deps.agent, token: deps.cfg.githubToken });
    this.qa =
      deps.qa ??
      new QaGate({ agent: deps.agent, git: createGitOps({ token: deps.cfg.githubToken }) });
    this.deployRunner = deps.deploy ?? new DeployRunner({ token: deps.cfg.githubToken });
    this.summaryUpdater = deps.summary ?? new SummaryUpdater({ agent: deps.agent });
    this.workspaceRoot = deps.workspaceRoot ?? process.env.AI_KANBAN_WORKSPACE_DIR ?? "/workspace";
    this.heartbeatMs = deps.heartbeatMs ?? WATCHDOG_DEFAULTS.heartbeatMs;
    this.watchdogTimeoutMs = deps.watchdogTimeoutMs ?? WATCHDOG_DEFAULTS.timeoutMs;
    this.cleanupAgeMs = deps.cleanupAgeMs ?? WATCHDOG_DEFAULTS.cleanupAgeMs;
    this.now = deps.now ?? (() => Date.now());
  }

  get isRunning(): boolean {
    return this.running;
  }

  async start(): Promise<void> {
    if (this.running) return;
    this.running = true;
    console.log(
      `[orchestrator] started (concurrentTasks=${this.deps.cfg.concurrentTasks}, ` +
        `workspace=${this.workspaceRoot})`,
    );
    if (!this.deps.noTimer) {
      const tickMs = this.deps.tickMs ?? 5000;
      this.timer = setInterval(() => {
        void this.tick().catch((err) => console.error("[orchestrator] tick failed:", err));
      }, tickMs);
      this.timer.unref?.();
      const watchdogTickMs = this.deps.watchdogTickMs ?? WATCHDOG_DEFAULTS.tickMs;
      this.watchdogTimer = setInterval(() => {
        void this.watchdogTick().catch((err) => console.error("[orchestrator] watchdog tick failed:", err));
      }, watchdogTickMs);
      this.watchdogTimer.unref?.();
      const cleanupIntervalMs = this.deps.cleanupIntervalMs ?? WATCHDOG_DEFAULTS.cleanupIntervalMs;
      this.cleanupTimer = setInterval(() => {
        void this.cleanupWorkspaces().catch((err) => console.error("[orchestrator] workspace cleanup failed:", err));
      }, cleanupIntervalMs);
      this.cleanupTimer.unref?.();
    }
    // Slice 5: rehydrate running tasks (auto-resume) + first watchdog/cleanup pass.
    await this.autoResume().catch((err) => console.error("[orchestrator] auto-resume failed:", err));
    if (!this.deps.noTimer) {
      await this.watchdogTick().catch((err) => console.error("[orchestrator] watchdog tick failed:", err));
      await this.cleanupWorkspaces().catch((err) => console.error("[orchestrator] workspace cleanup failed:", err));
    }
  }

  /** Stop the pickup loop; abort in-flight runs and wait for them to settle. */
  async stop(): Promise<void> {
    if (!this.running) return;
    this.running = false;
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = undefined;
    }
    if (this.watchdogTimer) {
      clearInterval(this.watchdogTimer);
      this.watchdogTimer = undefined;
    }
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer);
      this.cleanupTimer = undefined;
    }
    for (const taskId of [...this.pipelines.keys()]) this.tasks.abort(taskId);
    await Promise.allSettled([...this.pipelines.values()]);
    console.log("[orchestrator] stopped");
  }

  /**
   * One pickup pass: fill free slots with eligible backlog tasks (deps
   * satisfied, not paused), oldest first. Public so tests (and Slice 5's
   * auto-resume) can drive it manually.
   */
  async tick(): Promise<void> {
    if (!this.running) return;
    const free = Math.max(0, this.deps.cfg.concurrentTasks - (await this.countRunning()));
    if (free === 0) return;
    for (const task of await this.listEligibleBacklog(free)) {
      try {
        await this.startTask(task.id);
      } catch (err) {
        // A concurrent tick may have taken the slot/state; log and move on.
        if (!(err instanceof ServiceError)) {
          console.error(`[orchestrator] failed to start task ${task.id}:`, err);
        }
      }
    }
  }

  /** Wait for all in-flight task pipelines to settle (tests / shutdown). */
  async settled(): Promise<void> {
    await Promise.allSettled([...this.pipelines.values()]);
  }

  // -------------------------------------------------------------------------
  // State machine transitions
  // -------------------------------------------------------------------------

  /**
   * Start a backlog task (backlog → running): dependency gate + slot gate,
   * then launch the task session pipeline. Used by tick() and (Slice 3c) the
   * MCP start_task tool.
   */
  async startTask(taskId: number): Promise<TaskRow> {
    const task = await this.getTask(taskId);
    if (task.state !== "backlog") {
      throw new ServiceError(409, `task ${taskId} is not in the backlog (state: ${task.state})`);
    }
    if (task.paused) {
      throw new ServiceError(409, `task ${taskId} is paused (resume it first)`);
    }
    const deps = await taskDependencyStatus(this.db, task.ideaId);
    if (!deps.satisfied) {
      const names = await this.ideaTexts(deps.waitingOn);
      throw new ServiceError(409, `task ${taskId} is waiting on: ${names.join(", ") || deps.waitingOn.join(", ")}`);
    }
    const running = await this.countRunning();
    if (running >= this.deps.cfg.concurrentTasks) {
      throw new ServiceError(409, `no free task slots (${running}/${this.deps.cfg.concurrentTasks} running)`);
    }
    await this.transition(taskId, "backlog", "running", {
      branch: `task/${taskId}`,
      workspace: this.workspacePath(taskId),
    });
    // Resume from last_commit when the task has one (restarted from Needs
    // Attention, or re-picked after a stop): checkout the task branch at the
    // last commit and re-inject the mission brief (progress + resolution).
    this.launchPipeline(taskId, task.lastCommit !== null);
    return await this.getTask(taskId);
  }

  /**
   * Task session complete (running → deploy). The QA gate + deploy handlers
   * (Slice 3b) consume the `deploy` state; on success they move the task to
   * `done` and update the project summary.
   */
  async completeTask(taskId: number, summary: string, lastCommit?: string | null): Promise<TaskRow> {
    const task = await this.getTask(taskId);
    if (task.state !== "running") {
      throw new ServiceError(409, `task ${taskId} is not running (state: ${task.state})`);
    }
    if (task.paused) {
      throw new ServiceError(409, `task ${taskId} is paused`);
    }
    const extra: { lastCommit?: string } = {};
    if (lastCommit) extra.lastCommit = lastCommit;
    await this.transition(taskId, "running", "deploy", extra, { summary });
    return await this.getTask(taskId);
  }

  /**
   * Any failure lands in needs_attention (QA exhausted / deploy fail /
   * stuck / crash — PLAN.md §4). The resolution dialog (Slice 3c) re-enters
   * the backlog with the accepted plan.
   */
  async failTask(taskId: number, reason: string): Promise<TaskRow> {
    const task = await this.getTask(taskId);
    if (task.state === "done") {
      throw new ServiceError(409, `task ${taskId} is done`);
    }
    await this.transition(taskId, task.state as TaskState, "needs_attention", undefined, { reason });
    return await this.getTask(taskId);
  }

  /**
   * Stop a running task (stop → paused): abort the session; the task keeps
   * its `running` state with the paused flag (PLAN.md §4). REST/MCP controls
   * land in Slice 5.
   */
  async stopTask(taskId: number): Promise<TaskRow> {
    const task = await this.getTask(taskId);
    if (task.state !== "running") {
      throw new ServiceError(409, `task ${taskId} is not running (state: ${task.state})`);
    }
    if (task.paused) {
      throw new ServiceError(409, `task ${taskId} is already paused`);
    }
    await this.db.update(tasks).set({ paused: true }).where(eq(tasks.id, taskId));
    await this.appendEvent(taskId, "state", { paused: true, reason: "stopped" });
    this.tasks.abort(taskId);
    return await this.getTask(taskId);
  }

  /**
   * restart_task (PLAN.md §4/§5): needs_attention → backlog. The accepted
   * resolution plan (or an optional note) goes into `tasks.resolution`,
   * `qa_rounds` resets to 0, and on pickup the task resumes from
   * `last_commit` with the plan injected into the mission brief. The
   * resolution dialog's Accept lands here (plan already written to
   * `tasks.resolution`); the MCP restart_task tool passes an optional note.
   */
  async restartTask(taskId: number, note?: string): Promise<TaskRow> {
    const task = await this.getTask(taskId);
    if (task.state !== "needs_attention") {
      throw new ServiceError(409, `task ${taskId} is not needs_attention (state: ${task.state})`);
    }
    const trimmed = note?.trim();
    const extra: { qaRounds: number; resolution?: string } = { qaRounds: 0 };
    if (trimmed !== undefined && trimmed !== "") extra.resolution = trimmed;
    await this.transition(taskId, "needs_attention", "backlog", extra, {
      reason: trimmed !== undefined && trimmed !== "" ? "restarted with resolution note" : "restarted",
    });
    return await this.getTask(taskId);
  }

  /**
   * One-click resume (paused → running): re-launch the pipeline from
   * `last_commit` (mission brief re-injected with the progress summary).
   * Waits for the aborted (paused) run to settle first so the re-launch is
   * never skipped by the in-flight-pipeline guard.
   */
  async resumeTask(taskId: number): Promise<TaskRow> {
    const task = await this.getTask(taskId);
    if (task.state !== "running" || !task.paused) {
      throw new ServiceError(409, `task ${taskId} is not paused`);
    }
    const settling = this.pipelines.get(taskId);
    if (settling) await settling; // aborted run still in flight — let it settle
    await this.db.update(tasks).set({ paused: false }).where(eq(tasks.id, taskId));
    await this.appendEvent(taskId, "state", { paused: false, reason: "resumed" });
    this.launchPipeline(taskId, true);
    return await this.getTask(taskId);
  }

  // -------------------------------------------------------------------------
  // Slice 5: resilience (auto-resume, watchdog, workspace cleanup)
  // -------------------------------------------------------------------------

  /**
   * Auto-resume on container start (PLAN.md §4 "Resume"): any task that was
   * `running` (and not paused) when the container stopped is rehydrated —
   * re-clone/checkout `last_commit`, restore the Pi session file
   * (SessionManager.open via the stable session path), re-inject the mission
   * brief + progress summary, continue. Paused tasks stay paused (the user
   * resumes them explicitly). Returns the number of rehydrated tasks.
   */
  async autoResume(): Promise<number> {
    const rows = await this.db
      .select({ id: tasks.id, lastCommit: tasks.lastCommit })
      .from(tasks)
      .where(and(eq(tasks.state, "running"), eq(tasks.paused, false)));
    let count = 0;
    for (const row of rows) {
      if (this.pipelines.has(row.id)) continue;
      this.launchPipeline(row.id, true);
      count++;
      console.log(
        `[orchestrator] auto-resume: rehydrating task ${row.id}` +
          (row.lastCommit ? ` from last_commit ${row.lastCommit}` : " (no commit yet)"),
      );
    }
    if (count > 0) console.log(`[orchestrator] auto-resume: ${count} running task(s) rehydrated`);
    return count;
  }

  /**
   * Watchdog pass (PLAN.md §4): per-task heartbeat (default 60s) + stuck
   * detection (10 min silence → needs_attention + abort).
   *
   * A heartbeat event is written for a running task only while its session
   * pipeline is in flight AND it produced activity (log line, commit, or
   * usage) since the last heartbeat — a stuck session goes quiet, so the
   * heartbeats stop. When the silence exceeds `watchdogTimeoutMs` the task
   * is moved to needs_attention (reason `watchdog: ...`) and the session is
   * aborted. Paused tasks are skipped (silence is expected).
   *
   * Returns the flagged tasks + the tasks that got a heartbeat (tests).
   */
  async watchdogTick(): Promise<{ flagged: number[]; heartbeats: number[] }> {
    const now = this.now();
    const rows = await this.db
      .select({ id: tasks.id })
      .from(tasks)
      .where(and(eq(tasks.state, "running"), eq(tasks.paused, false)));
    const flagged: number[] = [];
    const heartbeats: number[] = [];
    if (rows.length > 0) {
      const lastTsRows = await this.db
        .select({ taskId: taskEvents.taskId, lastTs: sql<number>`max(${taskEvents.ts})` })
        .from(taskEvents)
        .where(inArray(taskEvents.taskId, rows.map((r) => r.id)))
        .groupBy(taskEvents.taskId);
      const lastTs = new Map(lastTsRows.map((r) => [r.taskId, r.lastTs ?? 0]));
      for (const { id } of rows) {
        const lastActivity = Math.max(this.activityAt.get(id) ?? 0, lastTs.get(id) ?? 0);
        if (lastActivity === 0) continue; // no events at all — nothing to measure
        const silentFor = now - lastActivity;
        if (silentFor > this.watchdogTimeoutMs) {
          console.error(`[orchestrator] watchdog: task ${id} silent for ${Math.round(silentFor / 60_000)}m — moving to needs_attention`);
          this.tasks.abort(id);
          try {
            await this.failTask(id, `watchdog: no activity for ${Math.round(silentFor / 60_000)}m (timeout ${Math.round(this.watchdogTimeoutMs / 60_000)}m)`);
            flagged.push(id);
          } catch (err) {
            // A concurrent transition (completion/stop) already moved the task.
            if (!(err instanceof ServiceError)) console.error(`[orchestrator] watchdog failTask (${id}) failed:`, err);
          }
        } else if (this.pipelines.has(id)) {
          const lastHb = this.lastHeartbeatAt.get(id) ?? 0;
          if (now - lastHb >= this.heartbeatMs && lastActivity > lastHb) {
            this.lastHeartbeatAt.set(id, now);
            await this.appendEvent(id, "heartbeat", { kind: "watchdog" });
            heartbeats.push(id);
          }
        }
      }
    }
    // Drop bookkeeping for tasks that are no longer running.
    const runningIds = new Set(rows.map((r) => r.id));
    for (const key of [...this.activityAt.keys()]) {
      if (!runningIds.has(key)) {
        this.activityAt.delete(key);
        this.lastHeartbeatAt.delete(key);
      }
    }
    return { flagged, heartbeats };
  }

  /**
   * 7-day workspace cleanup (PLAN.md §4 "Cleanup"): delete `/workspace/task-<id>`
   * dirs older than `cleanupAgeMs`. Only app-managed dirs (the `task-<id>`
   * naming convention) are touched, and dirs of in-flight tasks (running /
   * deploy) are kept — durable results are pushed by the deploy stage before
   * a task leaves the deploy state. Returns what was deleted/kept (tests).
   */
  async cleanupWorkspaces(): Promise<{ deleted: string[]; skipped: string[] }> {
    const deleted: string[] = [];
    const skipped: string[] = [];
    let entries: string[];
    try {
      entries = await readdir(this.workspaceRoot);
    } catch {
      return { deleted, skipped }; // workspace root not mounted yet
    }
    const now = this.now();
    for (const name of entries) {
      const m = /^task-(\d+)$/.exec(name);
      if (!m) continue; // only app-managed task dirs
      const dir = path.join(this.workspaceRoot, name);
      let st: Stats;
      try {
        st = await stat(dir);
      } catch {
        continue;
      }
      if (!st.isDirectory()) continue;
      if (now - st.mtimeMs <= this.cleanupAgeMs) {
        skipped.push(name); // too recent
        continue;
      }
      const taskId = Number(m[1]);
      const [task] = await this.db
        .select({ state: tasks.state })
        .from(tasks)
        .where(eq(tasks.id, taskId))
        .limit(1);
      if (task && (task.state === "running" || task.state === "deploy")) {
        skipped.push(name); // in-flight — never delete a live workspace
        continue;
      }
      await rm(dir, { recursive: true, force: true });
      deleted.push(name);
      console.log(
        `[orchestrator] cleanup: removed ${dir} (task ${taskId} ${task?.state ?? "missing"}, ` +
          `age ${Math.round((now - st.mtimeMs) / 86_400_000)}d)`,
      );
    }
    return { deleted, skipped };
  }

  // -------------------------------------------------------------------------
  // Task pipeline
  // -------------------------------------------------------------------------

  /** Task workspace dir (/workspace/task-<id>). */
  workspacePath(taskId: number): string {
    return path.join(this.workspaceRoot, `task-${taskId}`);
  }

  private launchPipeline(taskId: number, resume: boolean): void {
    if (this.pipelines.has(taskId)) return;
    // The (re)started pipeline is presumed fresh — the watchdog measures
    // silence from here until the session produces activity.
    this.activityAt.set(taskId, this.now());
    const p = this.runPipeline(taskId, resume).catch((err) => {
      // State conflicts (409) from concurrent transitions are expected; log
      // anything else. Never let a pipeline rejection go unhandled.
      if (!(err instanceof ServiceError)) {
        console.error(`[orchestrator] task pipeline failed (task ${taskId}):`, err);
      }
    });
    const tracked = p.finally(() => {
      this.pipelines.delete(taskId);
    });
    this.pipelines.set(taskId, tracked);
  }

  private async runPipeline(taskId: number, resume: boolean): Promise<void> {
    const task = await this.getTask(taskId);
    let ctx = await this.buildTaskContext(task, resume);
    this.wireSinks(ctx, taskId, task.projectId);

    let completionSummary = "";
    let lastCommit: string | null = null;
    try {
      for (;;) {
        const result = await this.tasks.run(ctx);
        completionSummary = result.summary;
        lastCommit = result.lastCommit;

        // Stopped/paused while running: no state change (Slice 5 surfaces the controls).
        const fresh = await this.getTask(taskId);
        if (fresh.state !== "running" || fresh.paused) {
          await this.appendEvent(taskId, "state", {
            reason: `run ended (task is ${fresh.state}${fresh.paused ? ", paused" : ""})`,
          });
          return;
        }

        // QA gate (fresh session, same workspace) — the task stays `running`.
        const round = fresh.qaRounds + 1;
        const verdict = await this.qa.run({
          taskId,
          workspace: this.workspacePath(taskId),
          branch: fresh.branch,
          defaultBranch: ctx.project.defaultBranch,
          spec: ctx.spec,
          completionSummary: result.summary,
          round,
          owner: task.owner, // Phase 2: bill the QA session to the owner's key
          onLog: (line) => void this.appendEvent(taskId, "log", { line }),
          onUsage: (u) => this.recordUsageFor(taskId, task.projectId, "qa", u, task.owner),
        });
        await this.appendEvent(taskId, "qa", { round, pass: verdict.pass, feedback: verdict.feedback });

        if (verdict.pass) break;

        // QA fail: qa_rounds+1; max rounds → needs_attention, else re-run with feedback.
        await this.db.update(tasks).set({ qaRounds: round }).where(eq(tasks.id, taskId));
        if (round >= this.qa.maxRounds) {
          console.error(`[orchestrator] task ${taskId} QA exhausted after ${round} rounds`);
          await this.transition(taskId, "running", "needs_attention", undefined, {
            reason: `QA exhausted after ${round} rounds`,
            feedback: verdict.feedback,
          });
          return;
        }
        await this.appendEvent(taskId, "state", {
          from: "running",
          to: "running",
          reason: `QA round ${round} failed — re-running with feedback`,
        });
        // Re-run the task session (same session file + workspace) with QA feedback.
        ctx = await this.buildTaskContext(task, true);
        ctx.prompt = qaFeedbackPrompt(round, verdict.feedback);
        this.wireSinks(ctx, taskId, task.projectId);
      }

      // QA pass → deploy state, then the deploy stage (automated, no human gate).
      await this.completeTask(taskId, completionSummary, lastCommit);
      await this.deployStage(taskId);
    } catch (err) {
      if (err instanceof TaskAbortedError) {
        await this.appendEvent(taskId, "state", { reason: "aborted" });
        return;
      }
      const fresh = await this.getTask(taskId);
      if (fresh.state !== "running") return; // already moved (e.g. stopped)
      const reason = err instanceof Error ? err.message : String(err);
      console.error(`[orchestrator] task ${taskId} failed:`, err);
      await this.transition(taskId, "running", "needs_attention", undefined, { reason });
    }
  }

  /** Wire the live-log / commit / usage sinks onto a task run context. */
  private wireSinks(ctx: TaskRunContext, taskId: number, projectId: number): void {
    ctx.onLog = (line) => {
      this.activityAt.set(taskId, this.now());
      void this.appendEvent(taskId, "log", { line });
    };
    ctx.onCommit = (commit) => {
      this.activityAt.set(taskId, this.now());
      void this.db
        .update(tasks)
        .set({ lastCommit: commit })
        .where(eq(tasks.id, taskId))
        .catch((err) => console.error(`[orchestrator] last_commit update failed (task ${taskId}):`, err));
      void this.appendEvent(taskId, "heartbeat", { commit });
    };
    ctx.onUsage = (u: UsageSample) => {
      this.activityAt.set(taskId, this.now());
      this.recordUsageFor(taskId, projectId, "task", u, ctx.owner);
    };
  }

  /** One usage row (role `task`/`qa`/`summary`); taskId null for summary. */
  private recordUsageFor(
    taskId: number | null,
    projectId: number,
    role: UsageRole,
    u: UsageSample,
    owner: string,
  ): void {
    void recordUsage(this.db, {
      projectId,
      taskId,
      role,
      model: u.model,
      thinking: u.thinking,
      tokensIn: u.input,
      tokensOut: u.output,
      cost: u.cost,
      owner,
    }).catch((err) =>
      console.error(`[orchestrator] usage record failed (task ${taskId ?? "-"}, role ${role}):`, err),
    );
  }

  /**
   * Deploy stage (QA pass → deploy → done): routed by task kind; on success
   * → `done` + one-shot project summary update; on failure → needs_attention
   * (retryable via retryDeploy).
   */
  private async deployStage(taskId: number): Promise<void> {
    const task = await this.getTask(taskId);
    if (task.state !== "deploy") return; // already moved (e.g. stopped meanwhile)
    const project = await this.getProject(task.projectId);
    const ctx: DeployContext = {
      taskId,
      kind: task.spec.kind,
      spec: task.spec,
      project: {
        name: project.name,
        repoUrl: project.repoUrl,
        defaultBranch: project.defaultBranch,
        blogRepoUrl: project.blogRepoUrl,
        blogContentPath: project.blogContentPath,
        mediaPaths: project.mediaPaths,
      },
      workspace: this.workspacePath(taskId),
      workspaceRoot: this.workspaceRoot,
      branch: task.branch ?? `task/${taskId}`,
      lastCommit: task.lastCommit,
    };
    try {
      const result = await this.deployRunner.deploy(ctx);
      await this.appendEvent(taskId, "deploy", {
        status: "ok",
        target: result.target,
        published: result.published,
      });
      await this.transition(taskId, "deploy", "done", undefined, { published: result.published });
      // One-shot project summary update (best-effort — a failure here must
      // not fail an already-deployed task).
      try {
        const next = await this.summaryUpdater.update({
          projectName: project.name,
          projectGoal: project.goal,
          previousSummary: project.stateSummary ?? "",
          deployed: `task ${taskId} (${task.spec.kind}): ${result.published}`,
          owner: task.owner, // Phase 2: bill the summary session to the owner's key
          onUsage: (u) => this.recordUsageFor(null, project.id, "summary", u, task.owner),
        });
        if (next) {
          await this.db
            .update(projects)
            .set({ stateSummary: next, updatedAt: Date.now() })
            .where(eq(projects.id, project.id));
        }
      } catch (err) {
        console.error(`[orchestrator] summary update failed (task ${taskId}):`, err);
        await this.appendEvent(taskId, "deploy", {
          status: "summary_failed",
          detail: err instanceof Error ? err.message : String(err),
        });
      }
    } catch (err) {
      const reason = err instanceof Error ? err.message : String(err);
      await this.appendEvent(taskId, "deploy", { status: "failed", detail: reason });
      await this.transition(taskId, task.state, "needs_attention", undefined, {
        reason: `deploy failed: ${reason}`,
      });
    }
  }

  /**
   * retry_deploy (PLAN.md §4/§5): re-run ONLY the deploy step — for a task
   * stuck in `deploy` or a `needs_attention` task whose failure was a deploy
   * failure. QA-exhausted tasks must go through the resolution dialog first.
   */
  async retryDeploy(taskId: number): Promise<TaskRow> {
    const task = await this.getTask(taskId);
    if (task.state !== "deploy" && task.state !== "needs_attention") {
      throw new ServiceError(409, `task ${taskId} is not deployable (state: ${task.state})`);
    }
    if (task.state === "needs_attention") {
      const last = await this.lastFailureReason(taskId);
      if (last?.startsWith("QA exhausted")) {
        throw new ServiceError(
          409,
          `task ${taskId} failed QA — resolve it (resolution dialog) before deploying`,
        );
      }
      await this.transition(taskId, "needs_attention", "deploy", undefined, { reason: "retry deploy" });
    }
    await this.deployStage(taskId);
    return await this.getTask(taskId);
  }

  /** The `reason` of the last state event that moved the task to needs_attention. */
  private async lastFailureReason(taskId: number): Promise<string | null> {
    const rows = await this.db
      .select()
      .from(taskEvents)
      .where(and(eq(taskEvents.taskId, taskId), eq(taskEvents.type, "state")))
      .orderBy(desc(taskEvents.id))
      .limit(20);
    for (const r of rows) {
      const p = r.payload ?? {};
      if (p.to === "needs_attention" && typeof p.reason === "string") return p.reason;
    }
    return null;
  }

  /** Assemble the TaskRunContext (project spec + task spec + deps + resume). */
  private async buildTaskContext(task: TaskRow, resume: boolean): Promise<TaskRunContext> {
    const [project] = await this.db.select().from(projects).where(eq(projects.id, task.projectId)).limit(1);
    const [idea] = await this.db.select().from(ideas).where(eq(ideas.id, task.ideaId)).limit(1);
    if (!project) throw new Error(`project ${task.projectId} for task ${task.id} not found`);

    // Deps: the idea's depends_on entries that have done tasks (what they produced).
    const deps: TaskRunContext["deps"] = [];
    const depIdeaIds = idea?.dependsOn ?? [];
    if (depIdeaIds.length > 0) {
      const doneTasks = await this.db
        .select()
        .from(tasks)
        .where(and(inArray(tasks.ideaId, depIdeaIds), eq(tasks.state, "done")));
      const doneByIdea = new Map(doneTasks.map((t) => [t.ideaId, t]));
      for (const depId of depIdeaIds) {
        const depTask = doneByIdea.get(depId);
        if (!depTask) continue;
        const [depIdea] = await this.db.select().from(ideas).where(eq(ideas.id, depId)).limit(1);
        deps.push({
          ideaId: depId,
          text: depIdea?.text ?? `idea ${depId}`,
          branch: depTask.branch,
          lastCommit: depTask.lastCommit,
          summary: await this.lastSummary(depTask.id),
        });
      }
    }

    return {
      taskId: task.id,
      projectId: task.projectId,
      ideaText: idea?.text ?? `task ${task.id}`,
      spec: task.spec,
      deps,
      resolution: task.resolution,
      progressSummary: resume ? await this.progressSummary(task) : null,
      owner: task.owner, // Phase 2: sessions bill to the owner's key (else service key)
      project: {
        name: project.name,
        goal: project.goal,
        repoUrl: project.repoUrl,
        defaultBranch: project.defaultBranch,
        blogRepoUrl: project.blogRepoUrl,
        blogContentPath: project.blogContentPath,
        mediaPaths: project.mediaPaths,
        constraints: project.constraints,
        architectureNotes: project.architectureNotes,
        notes: project.notes,
        stateSummary: project.stateSummary,
      },
      resumeCommit: resume ? task.lastCommit : null,
    };
  }

  /**
   * Rolling progress summary for a resume (PLAN.md §7): what was done in the
   * previous run, from the task's event trail (log tail + commits + states).
   */
  private async progressSummary(task: TaskRow): Promise<string> {
    const events = await this.db
      .select()
      .from(taskEvents)
      .where(eq(taskEvents.taskId, task.id))
      .orderBy(desc(taskEvents.id))
      .limit(50);
    const lines = events
      .reverse()
      .map((e) => {
        const p = e.payload ?? {};
        if (e.type === "log") return String(p.line ?? "");
        if (e.type === "heartbeat") return `commit ${String(p.commit ?? "")}`;
        if (e.type === "state") {
          const from = p.from !== undefined ? String(p.from) : "?";
          const to = p.to !== undefined ? String(p.to) : "?";
          return `state: ${from} → ${to}`;
        }
        return null;
      })
      .filter((l): l is string => l !== null && l !== "");
    const head = task.lastCommit ? `Last commit: ${task.lastCommit}` : "";
    const body = [head, ...lines.slice(-30)].filter((s) => s !== "");
    return body.length > 0 ? body.join("\n") : "(no progress recorded yet)";
  }

  /** Completion summary of a task's last run (from its state events). */
  private async lastSummary(taskId: number): Promise<string | null> {
    const rows = await this.db
      .select()
      .from(taskEvents)
      .where(and(eq(taskEvents.taskId, taskId), eq(taskEvents.type, "state")))
      .orderBy(desc(taskEvents.id))
      .limit(20);
    for (const r of rows) {
      const s = r.payload?.summary;
      if (typeof s === "string" && s !== "") return s;
    }
    return null;
  }

  // -------------------------------------------------------------------------
  // Internals
  // -------------------------------------------------------------------------

  private async getTask(taskId: number): Promise<TaskRow> {
    const [row] = await this.db.select().from(tasks).where(eq(tasks.id, taskId)).limit(1);
    if (!row) throw new ServiceError(404, `task ${taskId} not found`);
    return row;
  }

  private async getProject(projectId: number) {
    const [row] = await this.db.select().from(projects).where(eq(projects.id, projectId)).limit(1);
    if (!row) throw new ServiceError(404, `project ${projectId} not found`);
    return row;
  }

  /**
   * Transition with state_changed_at + a `state` task_event (audit trail).
   * The update is conditional on the current state (`from`) so concurrent
   * transitions (e.g. failTask vs. pipeline completion) can't overwrite each
   * other; a mismatch throws 409.
   */
  private async transition(
    taskId: number,
    from: TaskState,
    to: TaskState,
    extra?: { branch?: string; workspace?: string; lastCommit?: string; qaRounds?: number; resolution?: string },
    payload: EventPayload = {},
  ): Promise<void> {
    const updated = await this.db
      .update(tasks)
      .set({ state: to, stateChangedAt: Date.now(), ...(extra ?? {}) })
      .where(and(eq(tasks.id, taskId), eq(tasks.state, from)))
      .returning({ id: tasks.id });
    if (updated.length === 0) {
      const current = await this.getTask(taskId);
      throw new ServiceError(409, `task ${taskId} is not ${from} (state: ${current.state})`);
    }
    await this.appendEvent(taskId, "state", { from, to, ...payload });
  }

  private appendEvent(taskId: number, type: TaskEventType, payload: EventPayload): Promise<void> {
    return appendTaskEvent(this.db, taskId, type, payload).catch(
      (err) => console.error(`[orchestrator] task event failed (task ${taskId}):`, err),
    );
  }

  /** Running tasks that hold a slot (running and not paused). */
  private async countRunning(): Promise<number> {
    const rows = await this.db
      .select({ id: tasks.id })
      .from(tasks)
      .where(and(eq(tasks.state, "running"), eq(tasks.paused, false)));
    return rows.length;
  }

  /** Backlog tasks (oldest first) that are not paused and have deps satisfied. */
  private async listEligibleBacklog(limit: number): Promise<TaskRow[]> {
    const rows = await this.db
      .select()
      .from(tasks)
      .where(and(eq(tasks.state, "backlog"), eq(tasks.paused, false)))
      .orderBy(asc(tasks.id))
      .limit(50);
    const out: TaskRow[] = [];
    for (const row of rows) {
      if (out.length >= limit) break;
      const deps = await taskDependencyStatus(this.db, row.ideaId);
      if (deps.satisfied) out.push(row);
    }
    return out;
  }

  private async ideaTexts(ideaIds: number[]): Promise<string[]> {
    if (ideaIds.length === 0) return [];
    const rows = await this.db.select({ text: ideas.text }).from(ideas).where(inArray(ideas.id, ideaIds));
    return rows.map((r) => r.text);
  }
}
