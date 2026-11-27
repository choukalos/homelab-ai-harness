/**
 * Fastify app (requirements §9, PLAN.md §5): health probe, READ-ONLY GUI
 * (Board · Projects · Reports) + the MCP endpoint.
 *
 * MCP-first (2026-11-21): the web UI is a read-only status view — ALL
 * mutations (projects, ideas, grooming, backlog, task control, resolution)
 * go through the MCP endpoint, where the caller key authenticates the user,
 * enforces the capability set, and stamps the owner. The unauthenticated
 * LAN UI therefore can no longer mutate state.
 *
 * Routes (all GET — no mutation endpoints remain):
 *   GET  /                     Board (landing): 5 columns, month stats, 60s refresh
 *   GET  /projects             Projects list
 *   GET  /projects/<id>        Project page: settings + Idea/Grooming/Icebox (read-only)
 *   GET  /ideas/<id>/groom     Grooming transcript viewer (read-only; 3s poll while grooming)
 *   GET  /ideas/<id>/groom/messages  Transcript fragment (HTMX swap unit)
 *   GET  /tasks/<id>           Task detail: live log (2s poll while running),
 *                              workspace, branch, usage so far; Needs Attention:
 *                              what-happened panel (resolve via MCP:
 *                              task_status + restart_task(resolution_note))
 *   GET  /tasks/<id>/log       Log tail fragment (HTMX swap unit)
 *   GET  /reports              Rolling-12-month $ spend chart + total callout;
 *                              per-project completed + $; per-task usage table
 *                              (filterable via ?project=&state=&role=&q=)
 *   GET  /projects/<id>?page=N Project page: completed list (hidden, paginated)
 *   GET  /health               Health probe
 *   POST /api/projects/<id>/files  File intake (REST variant of the stage_file
 *                                  MCP tool): { path, content (base64) }
 *   POST /api/projects/<id>/refs   File intake (REST variant of the stage_ref
 *                                  MCP tool): { ref (URL or NAS path) }
 *
 * The /api file-intake routes are the only mutation endpoints (2026-11-23,
 * remote client file intake): JSON in/out for non-MCP clients, LAN-bound
 * like the unauthenticated board UI (LAN trust). The MCP endpoint remains
 * the attributed mutation path (caller key → owner + capability scoping);
 * /api rows are stamped owner '' (unattributed).
 */
import Fastify, { type FastifyInstance, type FastifyReply, type FastifyRequest } from "fastify";
import type { KanbanConfig } from "../config.js";
import type { DbHandle } from "../db/index.js";
import type { AgentRuntime } from "../agent/sessions.js";
import type { GroomMessage, GroomingManager } from "../agent/grooming.js";
import type { Orchestrator } from "../orchestrator.js";
import { ServiceError, type KanbanServices, type TaskDetail } from "../services/index.js";
import { taskEventLine } from "../services/tasks.js";
import { TASK_STATES, USAGE_ROLES, type TaskState, type UsageRole } from "../db/schema.js";
import { registerMcpRoutes } from "../mcp/http.js";
import {
  boardPage,
  errorPage,
  groomMessagesFragment,
  groomPage,
  layout,
  projectPage,
  projectsPage,
  reportsPage,
  taskLogFragment,
  taskPage,
  type BoardCardView,
  type BoardPageData,
  type GroomPageData,
  type ProjectPageData,
  type ReportsPageData,
  type TaskLogLineView,
  type TaskPageData,
} from "./templates.js";

export interface AppDeps {
  cfg: KanbanConfig;
  db: DbHandle;
  agent: AgentRuntime;
  services: KanbanServices;
  orchestrator: Orchestrator;
  /** Grooming manager (read-only transcript viewer + live turn status). */
  grooming: GroomingManager;
  /**
   * MCP key-suffix → capability mapping (guardrails for multi-user keys).
   * Default: parsed from the MCP_KEY_CAPABILITIES env var. Owner resolution
   * uses cfg.userKeys (USER_KEYS) directly — no separate owner map.
   */
  mcpKeyCapabilities?: Map<string, Set<string>>;
}

const BOARD_COLUMN_TITLES: Record<TaskState, string> = {
  backlog: "Backlog",
  running: "Running",
  deploy: "Deploy",
  done: "Done",
  needs_attention: "Needs Attention",
};

function setHtml(reply: FastifyReply, body: string): string {
  reply.header("content-type", "text/html; charset=utf-8");
  return body;
}

function parseId(raw: unknown): number | undefined {
  const n = Number.parseInt(String(raw), 10);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

/** Render task_events as display log lines (task detail page + log fragment). */
function taskLogLines(detail: TaskDetail): TaskLogLineView[] {
  return detail.log.map((e) => ({ ts: e.ts, type: e.type, text: taskEventLine(e) }));
}

export function buildApp(deps: AppDeps): FastifyInstance {
  const app = Fastify({ logger: true });

  app.get("/health", async () => ({
    ok: true,
    model: deps.cfg.model,
    db: deps.db.driver,
    mediaConcurrentTasks: deps.cfg.mediaConcurrentTasks,
    nonMediaConcurrentTasks: deps.cfg.nonMediaConcurrentTasks,
    agentConcurrentTasks: deps.cfg.agentConcurrentTasks,
    /** Standing-agent slugs (cards owned by one of them count against the agent slot). */
    agentSlugs: deps.cfg.agentSlugs,
    /** Per-owner pipeline model map (KANBAN_OWNER_MODELS; owner → model). */
    ownerModels: deps.cfg.ownerModels,
    /** Owner names with a dedicated LLM key profile (USER_KEYS; Phase 2). */
    userKeys: Object.keys(deps.cfg.userKeys),
  }));

  // ------------------------------------------------------------------
  // Board (landing) — 60s HTMX auto-refresh (requirements §9)
  // ------------------------------------------------------------------
  app.get("/", async (_req, reply) => {
    const data = await deps.services.board();
    const view: BoardPageData = {
      columns: data.columns.map((c) => ({
        title: BOARD_COLUMN_TITLES[c.state],
        cards: c.cards.map(
          (card): BoardCardView => ({
            taskId: card.taskId,
            projectName: card.projectName,
            title: card.title,
            paused: card.paused,
            cost: card.cost,
            owner: card.owner,
            waitingOn: card.waitingOn,
          }),
        ),
      })),
      month: data.month,
    };
    return setHtml(reply, layout("Board", "board", boardPage(view), { autoRefreshUrl: "/" }));
  });

  // ------------------------------------------------------------------
  // Task detail: live log (2s poll while running), workspace, branch,
  // usage so far. Needs Attention: what-happened panel (read-only —
  // resolution happens via MCP: task_status + restart_task(note)).
  // ------------------------------------------------------------------
  app.get("/tasks/:id", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    if (id === undefined) {
      return setHtml(reply, layout("Error", "board", errorPage("invalid task id")));
    }
    const detail = await deps.services.getTask(id);
    if (!detail) {
      reply.code(404);
      return setHtml(reply, layout("Not found", "board", errorPage("Task not found.")));
    }
    const t = detail.task;
    const lastReason = [...detail.log]
      .reverse()
      .find((e) => e.type === "state" && e.payload?.reason !== undefined)?.payload?.reason;
    let qaFeedback: string | null = null;
    for (const e of [...detail.log].reverse()) {
      const fb = e.payload?.feedback;
      if (e.type === "qa" && typeof fb === "string" && fb !== "") {
        qaFeedback = fb;
        break;
      }
    }
    const view: TaskPageData = {
      id: t.id,
      title: detail.idea.text,
      state: t.state,
      paused: t.paused,
      stateChangedAt: t.stateChangedAt,
      project: detail.project,
      owner: t.owner,
      kind: t.spec?.kind ?? "other",
      workspace: t.workspace,
      branch: t.branch,
      lastCommit: t.lastCommit,
      qaRounds: t.qaRounds,
      goal: t.spec?.goal ?? "",
      steps: t.spec?.steps ?? [],
      acceptance: t.spec?.acceptance ?? [],
      resolution: t.resolution,
      waitingOn: detail.waitingOn,
      usageTotal: detail.usageTotal,
      usageByRole: detail.usageByRole,
      usageByModel: detail.usageByModel,
      log: taskLogLines(detail),
      live: t.state === "running",
      lastActivityAt: detail.log.length > 0 ? detail.log[detail.log.length - 1]!.ts : null,
      failureReason: typeof lastReason === "string" ? lastReason : null,
      qaFeedback,
    };
    // Slide-over panel: HTMX requests (the board's panel fetch carries
    // HX-Request) get the bare panel fragment; plain navigation (deep link
    // / direct URL) gets the full page.
    if (req.headers["hx-request"] === "true") {
      return setHtml(reply, taskPage(view, { panel: true }));
    }
    return setHtml(reply, layout(`Task ${t.id}`, "board", taskPage(view)));
  });

  // Log tail fragment (HTMX swap unit for #task-log, 2s while running).
  app.get("/tasks/:id/log", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    if (id === undefined) {
      reply.code(400);
      return setHtml(reply, taskLogFragment([]));
    }
    const detail = await deps.services.getTask(id);
    if (!detail) {
      reply.code(404);
      return setHtml(reply, taskLogFragment([]));
    }
    return setHtml(reply, taskLogFragment(taskLogLines(detail)));
  });

  // ------------------------------------------------------------------
  // Projects (read-only)
  // ------------------------------------------------------------------
  app.get("/projects", async (_req, reply) => {
    const projects = await deps.services.listProjects();
    return setHtml(reply, layout("Projects", "projects", projectsPage({ projects })));
  });

  app.get("/projects/:id", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    if (id === undefined) {
      return setHtml(reply, layout("Error", "projects", errorPage("invalid project id")));
    }
    const project = await deps.services.getProject(id);
    if (!project) {
      reply.code(404);
      return setHtml(reply, layout("Not found", "projects", errorPage("Project not found.")));
    }
    const ideas = await deps.services.listIdeas(id);
    const page = parseId((req.query as Record<string, string>)?.page) ?? 1;
    const completed = await deps.services.projectCompleted(id, page);
    const view: ProjectPageData = {
      id: project.id,
      name: project.name,
      owner: project.owner,
      description: project.description,
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
      ideas: ideas.map((i) => ({
        id: i.id,
        text: i.text,
        state: i.state,
        owner: i.owner,
        dependsOn: i.dependsOn,
        spec: i.spec,
      })),
      groomingStatus: Object.fromEntries(
        ideas
          .filter((i) => i.state === "grooming")
          .map((i) => [i.id, deps.grooming.turnStatus(i.id)]),
      ),
      completed: {
        items: completed.items,
        page: completed.page,
        pageSize: completed.pageSize,
        total: completed.total,
        pageCount: completed.pageCount,
      },
    };
    return setHtml(reply, layout(project.name, "projects", projectPage(view)));
  });

  // ------------------------------------------------------------------
  // Grooming transcript viewer (READ-ONLY): the grooming conversation
  // happens via MCP (start_grooming / groom_message / groom_accept / ...);
  // this page shows where the conversation is at. While an idea is in
  // `grooming`, the transcript polls every 3s.
  // ------------------------------------------------------------------
  app.get("/ideas/:id/groom", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    if (id === undefined) {
      return setHtml(reply, layout("Error", "projects", errorPage("invalid idea id")));
    }
    const idea = await deps.services.getIdea(id);
    if (!idea) {
      reply.code(404);
      return setHtml(reply, layout("Not found", "projects", errorPage(`idea ${id} not found`)));
    }
    let messages: GroomMessage[] = [];
    if (idea.state === "grooming") {
      try {
        messages = await deps.grooming.transcript(id); // resume the session if needed
      } catch (err) {
        const status = err instanceof ServiceError ? err.status : 500;
        reply.code(status);
        return setHtml(reply, layout("Error", "projects", errorPage(err instanceof Error ? err.message : "error")));
      }
    }
    const view: GroomPageData = {
      ideaId: id,
      projectId: idea.projectId,
      projectName: idea.projectName,
      ideaText: idea.text,
      state: idea.state,
      messages,
      turn: deps.grooming.turnStatus(id),
    };
    return setHtml(reply, layout(`Grooming — ${idea.projectName}`, "projects", groomPage(view)));
  });

  // Transcript fragment (HTMX poll target for #groom-messages): status line
  // + full transcript. The container re-emits its own poll attributes.
  app.get("/ideas/:id/groom/messages", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    if (id === undefined) {
      return setHtml(reply, `<div id="groom-messages"></div>`);
    }
    try {
      const idea = await deps.services.getIdea(id);
      if (!idea) {
        reply.code(404);
        return setHtml(reply, `<div id="groom-messages"><p class="empty">idea not found</p></div>`);
      }
      if (idea.state !== "grooming") {
        return setHtml(
          reply,
          `<div id="groom-messages"><p class="empty">This idea is no longer in grooming (state: ${idea.state}).</p></div>`,
        );
      }
      const messages = await deps.grooming.transcript(id);
      return setHtml(reply, groomMessagesFragment(id, messages, deps.grooming.turnStatus(id)));
    } catch (err) {
      const status = err instanceof ServiceError ? err.status : 500;
      reply.code(status);
      return setHtml(reply, `<div id="groom-messages"><p class="empty">${err instanceof Error ? err.message : "error"}</p></div>`);
    }
  });

  // ------------------------------------------------------------------
  // Reports (Slice 4, requirements §9/§11): rolling-12-month $ spend
  // chart + total callout, per-project completed + $, per-task usage
  // table (filterable via query params: project / state / role / q).
  // ------------------------------------------------------------------
  app.get("/reports", async (req, reply) => {
    const q = (req.query ?? {}) as Record<string, string>;
    const projectId = parseId(q.project);
    const state = TASK_STATES.includes(q.state as TaskState) ? (q.state as TaskState) : undefined;
    const role = USAGE_ROLES.includes(q.role as UsageRole) ? (q.role as UsageRole) : undefined;
    const text = typeof q.q === "string" ? q.q.trim() : "";
    const data = await deps.services.reports({
      ...(projectId !== undefined ? { projectId } : {}),
      ...(state !== undefined ? { state } : {}),
      ...(role !== undefined ? { role } : {}),
      ...(text !== "" ? { q: text } : {}),
    });
    const view: ReportsPageData = {
      months: data.spend.months.map((m) => ({ key: m.key, label: m.label, short: m.short, spend: m.spend })),
      total: data.spend.total,
      owners: data.owners,
      roleSpend: data.roles,
      projects: data.projects,
      tasks: data.tasks,
      filters: {
        project: projectId !== undefined ? String(projectId) : "",
        state: state ?? "",
        role: role ?? "",
        q: text,
      },
      projectOptions: data.projectOptions,
      states: [...TASK_STATES],
      roles: [...USAGE_ROLES],
    };
    return setHtml(reply, layout("Reports", "reports", reportsPage(view)));
  });

  // ------------------------------------------------------------------
  // File intake API (2026-11-23, remote client file intake): REST variants
  // of the stage_file / stage_ref MCP tools for non-MCP clients. JSON
  // in/out; ServiceError statuses map straight to the HTTP status.
  // ------------------------------------------------------------------
  app.post("/api/projects/:id/files", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    if (id === undefined) {
      reply.code(400);
      return { error: "invalid project id" };
    }
    const body = (req.body ?? {}) as { path?: unknown; content?: unknown };
    try {
      return await deps.services.stageFile(id, String(body.path ?? ""), String(body.content ?? ""));
    } catch (err) {
      const status = err instanceof ServiceError ? err.status : 500;
      reply.code(status);
      return { error: err instanceof Error ? err.message : "error" };
    }
  });

  app.post("/api/projects/:id/refs", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    if (id === undefined) {
      reply.code(400);
      return { error: "invalid project id" };
    }
    const body = (req.body ?? {}) as { ref?: unknown };
    try {
      return await deps.services.stageRef(id, String(body.ref ?? ""));
    } catch (err) {
      const status = err instanceof ServiceError ? err.status : 500;
      reply.code(status);
      return { error: err instanceof Error ? err.message : "error" };
    }
  });

  registerMcpRoutes(app, {
    cfg: deps.cfg,
    services: deps.services,
    keyCapabilities: deps.mcpKeyCapabilities,
  });

  return app;
}
