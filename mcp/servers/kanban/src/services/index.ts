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
import type { GroomMessage, GroomingManager } from "../agent/grooming.js";
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
import { board, boardStatus, type BoardData, type BoardStatus, type BoardStatusFilters } from "./board.js";
import { getTaskDetail, getTaskStatus, type TaskDetail, type TaskStatus } from "./tasks.js";
import {
  projectCompleted,
  projectStats,
  spendByMonth,
  spendByOwner,
  taskUsageTable,
  type CompletedPage,
  type OwnerSpendRow,
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
export type { BoardData, BoardCard, BoardStatus, BoardStatusFilters } from "./board.js";
export type { IceboxMoveResult } from "./icebox.js";
export type { TaskDetail, TaskStatus, DependencyStatus } from "./tasks.js";
export type {
  SpendReport,
  MonthBucket,
  ProjectReportRow,
  OwnerSpendRow,
  TaskUsageFilters,
  TaskUsageRow,
  CompletedItem,
  CompletedPage,
} from "./reports.js";

export interface KanbanServices {
  listProjects(): Promise<ProjectSummary[]>;
  getProject(id: number): Promise<Project | undefined>;
  /** Create a project; `owner` = caller identity of the creating mutation (MCP key → user). */
  createProject(input: ProjectInput, owner?: string): Promise<Project>;
  updateProject(id: number, input: ProjectInput): Promise<Project | undefined>;
  listIdeas(projectId?: number): Promise<Idea[]>;
  getIdea(id: number): Promise<Idea | undefined>;
  /** Drop an idea; `owner` = caller identity of the creating mutation (MCP key → user). */
  addIdea(projectId: number, text: string, owner?: string): Promise<Idea>;
  board(): Promise<BoardData>;
  /** Board status for MCP board_status (counts + needs-attention + running). */
  boardStatus(filters?: BoardStatusFilters): Promise<BoardStatus>;
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
  /** Icebox → Backlog: create the 1:1 task per idea (owner inherited), flip idea to `moved`. */
  moveIceboxToBacklog(ideaIds: number[]): Promise<IceboxMoveResult>;

  // -- Interactive grooming (MCP tools; the web UI is read-only) -----------
  /**
   * Start interactive grooming (idea → grooming): runs the seed turn
   * (the LLM researches, states assumptions, asks questions). Returns the
   * idea + the seed assistant message (the client relays it to the user).
   */
  groomStart(ideaId: number): Promise<{ idea: IdeaRow; lastAssistant: string | null }>;
  /** One blocking grooming chat turn; returns the assistant reply. */
  groomMessage(ideaId: number, text: string): Promise<GroomMessage>;
  /** Grooming status: state, live turn status, transcript tail, spec (if icebox). */
  groomStatus(ideaId: number): Promise<GroomStatusView>;
  /**
   * Accept: kicks off the finalize turn in the background (xhigh finalize
   * can take minutes). Returns the idea (state still `grooming`); poll
   * groomStatus until state=icebox (spec present).
   */
  groomAccept(ideaId: number): Promise<IdeaRow>;
  /** Cancel: back to idea, chat discarded. */
  groomCancel(ideaId: number): Promise<IdeaRow>;
  /** Re-groom: fresh session, re-seeded with the idea (awaited re-seed). */
  groomReGroom(ideaId: number): Promise<IdeaRow>;
  /** Discard: soft-delete (state `discarded`); idea/grooming only. */
  discardIdea(ideaId: number): Promise<IdeaRow>;
  /** Grooming transcript (empty for non-grooming states). */
  groomTranscript(ideaId: number): Promise<GroomMessage[]>;

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

/** Interactive-grooming status view (MCP groom_status). */
export interface GroomStatusView {
  ideaId: number;
  state: string;
  /** Live turn status (is a grooming turn in flight?). */
  turn: { active: boolean; since: number | null; label: string | null };
  /** Transcript tail (last 5 messages; empty for non-grooming states). */
  messages: GroomMessage[];
  /** Finalized spec (state icebox). */
  spec: Idea["spec"];
}

/** Reports page payload (GET /reports, requirements §9/§11). */
export interface ReportsData {
  spend: SpendReport;
  /** Per-user $ spend per month, rolling 12 months (Phase 2; '' = unattributed). */
  owners: OwnerSpendRow[];
  projects: ProjectReportRow[];
  tasks: TaskUsageRow[];
  /** Normalized filters (echoed into the filter form). */
  filters: TaskUsageFilters;
  /** Project options for the filter form. */
  projectOptions: Array<{ id: number; name: string }>;
}

export interface KanbanServicesDeps {
  /** Grooming manager (agent-backed); required for the interactive grooming methods. */
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
  const grooming = () => {
    if (!deps.grooming) {
      return Promise.reject(new ServiceError(503, "grooming is not configured"));
    }
    return Promise.resolve(deps.grooming);
  };
  return {
    listProjects: () => listProjects(db),
    getProject: (id) => getProject(db, id),
    createProject: (input, owner) => createProject(db, input, owner),
    updateProject: (id, input) => updateProject(db, id, input),
    listIdeas: (projectId) => listIdeas(db, projectId),
    getIdea: (id) => getIdea(db, id),
    addIdea: (projectId, text, owner) => addIdea(db, projectId, text, owner),
    board: () => board(db),
    boardStatus: (filters) => boardStatus(db, filters),
    getTask: (id) => getTaskDetail(db, id),
    taskStatus: (id) => getTaskStatus(db, id),
    startTask: (taskId) => orchestrator().then((o) => o.startTask(taskId)),
    pauseTask: (taskId) => orchestrator().then((o) => o.stopTask(taskId)),
    resumeTask: (taskId) => orchestrator().then((o) => o.resumeTask(taskId)),
    stopTask: (taskId) => orchestrator().then((o) => o.stopTask(taskId)),
    retryDeploy: (taskId) => orchestrator().then((o) => o.retryDeploy(taskId)),
    restartTask: (taskId, note) => orchestrator().then((o) => o.restartTask(taskId, note)),
    moveIceboxToBacklog: (ideaIds) => moveIceboxToBacklog(db, ideaIds),

    // Interactive grooming (thin wrappers over the GroomingManager state
    // machine — the web UI is read-only, MCP is the mutation path).
    groomStart: async (ideaId) => {
      const g = await grooming();
      const idea = await g.startGrooming(ideaId); // awaited seed turn
      const messages = await g.transcript(ideaId);
      const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant")?.text ?? null;
      return { idea, lastAssistant };
    },
    groomMessage: (ideaId, text) => grooming().then((g) => g.sendGroomMessage(ideaId, text)),
    groomStatus: async (ideaId) => {
      const g = await grooming();
      const idea = await getIdea(db, ideaId);
      if (!idea) throw new ServiceError(404, `idea ${ideaId} not found`);
      const turn = g.turnStatus(ideaId);
      const messages =
        idea.state === "idea" || idea.state === "grooming" ? await g.transcript(ideaId) : [];
      return {
        ideaId,
        state: idea.state,
        turn,
        messages: messages.slice(-5),
        spec: idea.spec,
      };
    },
    groomAccept: async (ideaId) => {
      const g = await grooming();
      await g.postAcceptGrooming(ideaId); // validates state (409 if not grooming); finalize runs in background
      const idea = await getIdea(db, ideaId);
      if (!idea) throw new ServiceError(404, `idea ${ideaId} not found`);
      return idea as IdeaRow;
    },
    groomCancel: (ideaId) => grooming().then((g) => g.cancelGrooming(ideaId)),
    groomReGroom: (ideaId) => grooming().then((g) => g.reGroom(ideaId)),
    discardIdea: (ideaId) => grooming().then((g) => g.discardIdea(ideaId)),
    groomTranscript: (ideaId) => grooming().then((g) => g.transcript(ideaId)),

    reports: async (filters = {}) => {
      const [spend, owners, projects, tasks, projectOptions] = await Promise.all([
        spendByMonth(db),
        spendByOwner(db),
        projectStats(db),
        taskUsageTable(db, filters),
        listProjects(db),
      ]);
      return {
        spend,
        owners,
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
