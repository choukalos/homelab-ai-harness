/**
 * Service layer facade (PLAN.md §7): transport-agnostic functions over the
 * db. Both the REST API (src/http) and the MCP tools (src/mcp) call into
 * these — the MCP tools are a thin layer over the same service functions.
 *
 * Slice 1: projects, ideas, board. Slice 2: grooming/icebox. Slice 3:
 * tasks/orchestration. Slice 4: usage reports.
 */
import type { DbHandle } from "../db/index.js";
import type { IdeaRow, TaskRow } from "../db/schema.js";
import type { GroomingManager } from "../agent/grooming.js";
import type { Orchestrator } from "../orchestrator.js";
import { ServiceError, type Db } from "./common.js";
import { addIdea, getIdea, listIdeas, type Idea } from "./ideas.js";
import { moveIceboxToBacklog, type IceboxMoveResult } from "./icebox.js";
import {
  createProject,
  getProject,
  listProjects,
  updateProject,
  type Project,
  type ProjectInput,
  type ProjectSummary,
} from "./projects.js";
import { board, type BoardData } from "./board.js";
import { getTaskDetail, getTaskStatus, type TaskDetail, type TaskStatus } from "./tasks.js";
import {
  projectCompleted,
  projectStats,
  spendByMonth,
  taskUsageTable,
  type CompletedPage,
  type ProjectReportRow,
  type SpendReport,
  type TaskUsageFilters,
  type TaskUsageRow,
} from "./reports.js";
import { getProjectStatus, type ProjectStatus } from "./projects.js";

export { ServiceError } from "./common.js";
export type { Project, ProjectInput, ProjectSummary } from "./projects.js";
export type { ProjectStatus } from "./projects.js";
export type { Idea } from "./ideas.js";
export type { BoardData, BoardCard } from "./board.js";
export type { IceboxMoveResult } from "./icebox.js";
export type { TaskDetail, TaskStatus, DependencyStatus } from "./tasks.js";
export type {
  SpendReport,
  MonthBucket,
  ProjectReportRow,
  TaskUsageFilters,
  TaskUsageRow,
  CompletedItem,
  CompletedPage,
} from "./reports.js";

export interface KanbanServices {
  listProjects(): Promise<ProjectSummary[]>;
  getProject(id: number): Promise<Project | undefined>;
  createProject(input: ProjectInput): Promise<Project>;
  updateProject(id: number, input: ProjectInput): Promise<Project | undefined>;
  listIdeas(projectId?: number): Promise<Idea[]>;
  getIdea(id: number): Promise<Idea | undefined>;
  addIdea(projectId: number, text: string): Promise<Idea>;
  board(): Promise<BoardData>;
  /** Task detail (state, workspace, branch, usage, log tail) for /tasks/<id>. */
  getTask(id: number): Promise<TaskDetail | undefined>;
  /** Task status for MCP task_status (state, log tail, usage, failure reason). */
  taskStatus(id: number): Promise<TaskStatus | undefined>;
  /** Start a backlog task now (dependency + slot gates apply). */
  startTask(taskId: number): Promise<TaskRow>;
  /** Pause a running task (stop the session; keeps `running` + paused flag). */
  pauseTask(taskId: number): Promise<TaskRow>;
  /** One-click resume of a paused task (re-run from last_commit). */
  resumeTask(taskId: number): Promise<TaskRow>;
  /** Stop a running task (= pause: abort session, paused flag). */
  stopTask(taskId: number): Promise<TaskRow>;
  /** Re-run ONLY the deploy step (deploy / needs_attention after a deploy fail). */
  retryDeploy(taskId: number): Promise<TaskRow>;
  /** needs_attention → backlog (resume from last_commit, QA reset; optional note). */
  restartTask(taskId: number, note?: string): Promise<TaskRow>;
  /** Icebox → Backlog: create the 1:1 task per idea, flip idea to `moved`. */
  moveIceboxToBacklog(ideaIds: number[]): Promise<IceboxMoveResult>;
  /** Autonomous one-shot grooming (MCP groom_idea; GUI uses the chat). */
  groomIdea(ideaId: number): Promise<IdeaRow>;
  /**
   * Reports page data (Slice 4, requirements §11): rolling-12-month $ spend
   * (per month + total), per-project completed count + $ spend, and the
   * per-task usage table (filterable).
   */
  reports(filters?: TaskUsageFilters): Promise<ReportsData>;
  /** Project status for MCP project_status (state summary + icebox + task counts). */
  projectStatus(id: number): Promise<ProjectStatus | undefined>;
  /** Completed/deployed items of a project (hidden by default, paginated). */
  projectCompleted(id: number, page?: number, pageSize?: number): Promise<CompletedPage>;
}

/** Reports page payload (GET /reports, requirements §9/§11). */
export interface ReportsData {
  spend: SpendReport;
  projects: ProjectReportRow[];
  tasks: TaskUsageRow[];
  /** Normalized filters (echoed into the filter form). */
  filters: TaskUsageFilters;
  /** Project options for the filter form. */
  projectOptions: Array<{ id: number; name: string }>;
}

export interface KanbanServicesDeps {
  /** Grooming manager (agent-backed); required for groomIdea. */
  grooming?: GroomingManager;
  /** Orchestrator; required for task control (start/retry/restart). */
  orchestrator?: Orchestrator;
}

/** Bind the service functions to a db handle. */
export function createKanbanServices(handle: DbHandle, deps: KanbanServicesDeps = {}): KanbanServices {
  const db: Db = handle.db as unknown as Db;
  const orchestrator = () => {
    if (!deps.orchestrator) {
      return Promise.reject(new ServiceError(503, "orchestrator is not configured"));
    }
    return Promise.resolve(deps.orchestrator);
  };
  return {
    listProjects: () => listProjects(db),
    getProject: (id) => getProject(db, id),
    createProject: (input) => createProject(db, input),
    updateProject: (id, input) => updateProject(db, id, input),
    listIdeas: (projectId) => listIdeas(db, projectId),
    getIdea: (id) => getIdea(db, id),
    addIdea: (projectId, text) => addIdea(db, projectId, text),
    board: () => board(db),
    getTask: (id) => getTaskDetail(db, id),
    taskStatus: (id) => getTaskStatus(db, id),
    startTask: (taskId) => orchestrator().then((o) => o.startTask(taskId)),
    pauseTask: (taskId) => orchestrator().then((o) => o.stopTask(taskId)),
    resumeTask: (taskId) => orchestrator().then((o) => o.resumeTask(taskId)),
    stopTask: (taskId) => orchestrator().then((o) => o.stopTask(taskId)),
    retryDeploy: (taskId) => orchestrator().then((o) => o.retryDeploy(taskId)),
    restartTask: (taskId, note) => orchestrator().then((o) => o.restartTask(taskId, note)),
    moveIceboxToBacklog: (ideaIds) => moveIceboxToBacklog(db, ideaIds),
    groomIdea: (ideaId) => {
      if (!deps.grooming) {
        return Promise.reject(new ServiceError(503, "grooming is not configured"));
      }
      return deps.grooming.groomIdeaOneShot(ideaId);
    },
    reports: async (filters = {}) => {
      const [spend, projects, tasks, projectOptions] = await Promise.all([
        spendByMonth(db),
        projectStats(db),
        taskUsageTable(db, filters),
        listProjects(db),
      ]);
      return {
        spend,
        projects,
        tasks,
        filters,
        projectOptions: projectOptions.map((p) => ({ id: p.id, name: p.name })),
      };
    },
    projectStatus: (id) => getProjectStatus(db, id),
    projectCompleted: (id, page, pageSize) => projectCompleted(db, id, page, pageSize),
  };
}
