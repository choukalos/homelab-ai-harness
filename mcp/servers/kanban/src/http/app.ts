/**
 * Fastify app (requirements §9, PLAN.md §5): health probe, GUI (Board ·
 * Projects · Reports) + REST, and the MCP endpoint.
 *
 * Slice 1 routes:
 *   GET  /                     Board (landing): 5 columns, month stats, 60s refresh
 *   GET  /projects             Projects list
 *   POST /projects             Create project (JSON → 201; form → 302)
 *   GET  /projects/<id>        Project page: settings + Idea/Grooming/Icebox
 *   POST /projects/<id>        Update project (JSON → 200; form → 302)
 *   POST /projects/<id>/ideas  Idea drop (JSON → 201; form → 302)
 *
 * Slice 2 routes:
 *   GET  /ideas/<id>/groom            Grooming chat page (starts + seeds on first load)
 *   POST /ideas/<id>/groom/messages   Chat turn (HTMX; new assistant message fragment)
 *   POST /ideas/<id>/groom/accept     Finalize spec + deps → Icebox
 *   POST /ideas/<id>/groom/cancel     Back to Idea (chat discarded)
 *   POST /ideas/<id>/groom/re-groom   Fresh chat session
 *   POST /ideas/<id>/discard          Delete idea (soft: state `discarded`)
 *   POST /projects/<id>/icebox/move   Move one or more icebox items → Backlog
 *
 * Slice 3 routes:
 *   GET  /tasks/<id>                  Task detail: live log (2s poll while running),
 *                                     workspace, branch, usage so far; Needs Attention:
 *                                     what-happened panel + resolution dialog
 *   GET  /tasks/<id>/log              Log tail fragment (HTMX swap unit)
 *   POST /tasks/<id>/resolve/messages Resolution dialog chat turn (HTMX fragment)
 *   POST /tasks/<id>/resolve/accept   Capture plan → Backlog (resume, QA reset)
 *   POST /tasks/<id>/pause            Pause a running task (paused flag)
 *   POST /tasks/<id>/resume           One-click resume of a paused task
 *   POST /tasks/<id>/stop             Stop a running task (= pause)
 *   POST /tasks/<id>/retry-deploy     Re-run only the deploy step
 *
 * Slice 4 routes:
 *   GET  /reports                     Rolling-12-month $ spend chart + total
 *                                     callout; per-project completed + $;
 *                                     per-task usage table (filterable via
 *                                     ?project=&state=&role=&q=)
 *   GET  /projects/<id>?page=N        Project page: completed list (hidden,
 *                                     paginated)
 *
 * GUI forms post application/x-www-form-urlencoded (parsed manually — no
 * form-body plugin); JSON requests get JSON responses. Service errors
 * (ServiceError.status) map straight to the response status.
 */
import Fastify, { type FastifyInstance, type FastifyReply, type FastifyRequest } from "fastify";
import type { KanbanConfig } from "../config.js";
import type { DbHandle } from "../db/index.js";
import type { AgentRuntime } from "../agent/sessions.js";
import type { GroomingManager } from "../agent/grooming.js";
import type { ResolutionDialog } from "../agent/resolve.js";
import type { Orchestrator } from "../orchestrator.js";
import { ServiceError, type KanbanServices, type ProjectInput, type TaskDetail } from "../services/index.js";
import { taskEventLine } from "../services/tasks.js";
import { TASK_STATES, USAGE_ROLES, type TaskState, type UsageRole } from "../db/schema.js";
import { registerMcpRoutes } from "../mcp/http.js";
import {
  boardPage,
  errorPage,
  groomMessageFragment,
  groomMessagesFragment,
  groomPage,
  layout,
  projectEditorDialog,
  projectPage,
  projectsPage,
  reportsPage,
  resolveMessageFragment,
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
  grooming: GroomingManager;
  /** Resolution dialog (Needs Attention → Backlog). */
  resolve: ResolutionDialog;
  /**
   * MCP key-suffix → capability mapping (guardrails for multi-user keys).
   * Default: parsed from the MCP_KEY_CAPABILITIES env var.
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

/** Parse the request body as string fields: JSON object or urlencoded form. */
async function requestFields(req: FastifyRequest): Promise<Record<string, string>> {
  const ct = String(req.headers["content-type"] ?? "");
  if (ct.includes("application/json")) {
    const body = (req.body ?? {}) as Record<string, unknown>;
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(body)) {
      if (typeof v === "string") out[k] = v;
      else if (Array.isArray(v)) out[k] = v.map(String).join(",");
    }
    return out;
  }
  const raw =
    typeof req.body === "string"
      ? req.body
      : Buffer.isBuffer(req.body)
        ? req.body.toString("utf8")
        : "";
  return Object.fromEntries(new URLSearchParams(raw));
}

function isJson(req: FastifyRequest): boolean {
  return String(req.headers["content-type"] ?? "").includes("application/json");
}

/** Build a ProjectInput from request fields (camelCase JSON or snake_case forms). */
function projectInputFromFields(f: Record<string, string>): ProjectInput {
  const pick = (...keys: string[]): string | undefined => {
    for (const k of keys) if (f[k] !== undefined) return f[k];
    return undefined;
  };
  const media = pick("mediaPaths", "media_paths");
  return {
    name: pick("name"),
    description: pick("description"),
    goal: pick("goal"),
    repoUrl: pick("repoUrl", "repo_url"),
    defaultBranch: pick("defaultBranch", "default_branch"),
    blogRepoUrl: pick("blogRepoUrl", "blog_repo_url"),
    blogContentPath: pick("blogContentPath", "blog_content_path"),
    mediaPaths:
      media === undefined ? undefined : media.split(",").map((s) => s.trim()).filter((s) => s !== ""),
    constraints: pick("constraints"),
    architectureNotes: pick("architectureNotes", "architecture_notes"),
    notes: pick("notes"),
  };
}

function parseId(raw: unknown): number | undefined {
  const n = Number.parseInt(String(raw), 10);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

/** Map a thrown error to a response (JSON or HTML for form posts). */
function sendError(reply: FastifyReply, err: unknown, htmlError: boolean): void {
  if (err instanceof ServiceError) {
    if (htmlError) {
      reply.code(err.status).send(setHtml(reply, layout("Error", "projects", errorPage(err.message))));
    } else {
      reply.code(err.status).send({ error: err.message });
    }
    return;
  }
  console.error("[http] unhandled error:", err);
  reply
    .code(500)
    .send(htmlError ? setHtml(reply, layout("Error", "projects", errorPage("internal error"))) : { error: "internal error" });
}

/** Render task_events as display log lines (task detail page + log fragment). */
function taskLogLines(detail: TaskDetail): TaskLogLineView[] {
  return detail.log.map((e) => ({ ts: e.ts, type: e.type, text: taskEventLine(e) }));
}

export function buildApp(deps: AppDeps): FastifyInstance {
  const app = Fastify({ logger: true });

  // Task detail slide-over panel (PLAN.md §5, post-MVP): the board page
  // carries the #task-panel <dialog> + the opener script (in layout()); the
  // panel fetch (HX-Request header) gets the bare fragment from
  // GET /tasks/:id, while plain navigation gets the full page.
  // GUI forms post urlencoded. Fastify v5 hands the parser the payload as a
  // stream — collect it into a utf8 string; requestFields() parses it with
  // URLSearchParams.
  app.addContentTypeParser("application/x-www-form-urlencoded", (req, body, done) => {
    const chunks: Buffer[] = [];
    body.on("data", (chunk: Buffer) => chunks.push(chunk));
    body.on("end", () => done(null, Buffer.concat(chunks).toString("utf8")));
    body.on("error", (err: Error) => done(err));
  });

  app.get("/health", async () => ({
    ok: true,
    model: deps.cfg.model,
    db: deps.db.driver,
    concurrentTasks: deps.cfg.concurrentTasks,
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
            waitingOn: card.waitingOn,
          }),
        ),
      })),
      month: data.month,
    };
    return setHtml(reply, layout("Board", "board", boardPage(view), { autoRefreshUrl: "/" }));
  });

  // ------------------------------------------------------------------
  // Task detail (Slice 3a, requirements §9): live log (2s poll while
  // running), workspace, branch, usage so far
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
    // Needs Attention: open/resume the resolution session for the transcript.
    let resolveMessages: Array<{ role: "user" | "assistant"; text: string }> = [];
    if (t.state === "needs_attention") {
      resolveMessages = await deps.resolve.transcript(id);
    }
    const view: TaskPageData = {
      id: t.id,
      title: detail.idea.text,
      state: t.state,
      paused: t.paused,
      stateChangedAt: t.stateChangedAt,
      project: detail.project,
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
      log: taskLogLines(detail),
      live: t.state === "running",
      lastActivityAt: detail.log.length > 0 ? detail.log[detail.log.length - 1]!.ts : null,
      failureReason: typeof lastReason === "string" ? lastReason : null,
      qaFeedback,
      resolveMessages,
    };
    // Slide-over panel (PLAN.md §5, post-MVP): HTMX requests (the board's
    // panel fetch carries HX-Request) get the bare panel fragment; plain
    // navigation (deep link / direct URL) gets the full page.
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
  // Resolution dialog (Slice 3c, requirements §5/§8): chat + Accept →
  // Backlog (resume from last_commit, plan injected, QA rounds reset)
  // ------------------------------------------------------------------

  // Chat turn (HTMX): append the user message, run the turn, return the new
  // assistant message fragment for #resolve-messages (hx-swap="beforeend").
  app.post("/tasks/:id/resolve/messages", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    if (id === undefined) {
      reply.code(400);
      return setHtml(reply, `<div class="msg error">invalid task id</div>`);
    }
    const fields = await requestFields(req);
    try {
      const msg = await deps.resolve.sendResolveMessage(id, fields.message ?? "");
      return setHtml(reply, resolveMessageFragment(msg.role, msg.text));
    } catch (err) {
      const status = err instanceof ServiceError ? err.status : 500;
      const message = err instanceof ServiceError ? err.message : "internal error";
      if (!(err instanceof ServiceError)) console.error("[http] resolution turn failed:", err);
      reply.code(status);
      return setHtml(reply, `<div class="msg error">${message.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")}</div>`);
    }
  });

  // Accept: final prompt → structured plan → tasks.resolution → Backlog.
  app.post("/tasks/:id/resolve/accept", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    const json = isJson(req);
    if (id === undefined) {
      if (json) return reply.code(400).send({ error: "invalid task id" });
      return setHtml(reply, layout("Error", "board", errorPage("invalid task id")));
    }
    try {
      const task = await deps.resolve.acceptResolution(id);
      if (json) return task;
      reply.code(302).headers({ location: `/tasks/${id}` }).send();
    } catch (err) {
      sendError(reply, err, !json);
    }
  });

  // retry_deploy (PLAN.md §4/§5): re-run ONLY the deploy step.
  app.post("/tasks/:id/retry-deploy", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    const json = isJson(req);
    if (id === undefined) {
      if (json) return reply.code(400).send({ error: "invalid task id" });
      return setHtml(reply, layout("Error", "board", errorPage("invalid task id")));
    }
    try {
      const task = await deps.services.retryDeploy(id);
      if (json) return task;
      reply.code(302).headers({ location: `/tasks/${id}` }).send();
    } catch (err) {
      sendError(reply, err, !json);
    }
  });

  // ------------------------------------------------------------------
  // Manual control (Slice 5, PLAN.md §4/§5): pause / resume / stop.
  // `paused` is an orthogonal flag on running tasks — stop/pause abort the
  // session and keep the `running` state; resume re-runs from last_commit.
  // ------------------------------------------------------------------
  const taskControl = (route: string, fn: (id: number) => Promise<unknown>) => {
    app.post(route, async (req, reply) => {
      const id = parseId((req.params as Record<string, string>).id);
      const json = isJson(req);
      if (id === undefined) {
        if (json) return reply.code(400).send({ error: "invalid task id" });
        return setHtml(reply, layout("Error", "board", errorPage("invalid task id")));
      }
      try {
        const task = await fn(id);
        if (json) return task;
        reply.code(302).headers({ location: `/tasks/${id}` }).send();
      } catch (err) {
        sendError(reply, err, !json);
      }
    });
  };
  taskControl("/tasks/:id/pause", (id) => deps.services.pauseTask(id));
  taskControl("/tasks/:id/resume", (id) => deps.services.resumeTask(id));
  taskControl("/tasks/:id/stop", (id) => deps.services.stopTask(id));

  // ------------------------------------------------------------------
  // Projects
  // ------------------------------------------------------------------
  app.get("/projects", async (_req, reply) => {
    const projects = await deps.services.listProjects();
    return setHtml(reply, layout("Projects", "projects", projectsPage({ projects })));
  });

  app.post("/projects", async (req, reply) => {
    const input = projectInputFromFields(await requestFields(req));
    const json = isJson(req);
    try {
      const project = await deps.services.createProject(input);
      if (json) {
        reply.code(201);
        return project;
      }
      reply.code(302).headers({ location: "/projects" }).send();
    } catch (err) {
      sendError(reply, err, !json);
    }
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

  app.post("/projects/:id", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    const json = isJson(req);
    if (id === undefined) {
      if (json) return reply.code(400).send({ error: "invalid project id" });
      return setHtml(reply, layout("Error", "projects", errorPage("invalid project id")));
    }
    const input = projectInputFromFields(await requestFields(req));
    try {
      const project = await deps.services.updateProject(id, input);
      if (!project) {
        if (json) return reply.code(404).send({ error: `project ${id} not found` });
        reply.code(404);
        return setHtml(reply, layout("Not found", "projects", errorPage("Project not found.")));
      }
      if (json) return project;
      reply.code(302).headers({ location: `/projects/${id}` }).send();
    } catch (err) {
      sendError(reply, err, !json);
    }
  });

  // Idea drop (requirements §9: quick prompt form on the project page).
  app.post("/projects/:id/ideas", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    const json = isJson(req);
    if (id === undefined) {
      if (json) return reply.code(400).send({ error: "invalid project id" });
      return setHtml(reply, layout("Error", "projects", errorPage("invalid project id")));
    }
    const fields = await requestFields(req);
    try {
      const idea = await deps.services.addIdea(id, fields.text ?? "");
      if (json) {
        reply.code(201);
        return idea;
      }
      reply.code(302).headers({ location: `/projects/${id}` }).send();
    } catch (err) {
      sendError(reply, err, !json);
    }
  });

  // ------------------------------------------------------------------
  // Grooming chat (Slice 2, requirements §5/§9)
  // ------------------------------------------------------------------

  // Grooming chat page. First load of an `idea` starts grooming (transition
  // + seed the persisted Pi session with the idea + project context);
  // later loads resume the session (no new LLM call).
  app.get("/ideas/:id/groom", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    if (id === undefined) {
      return setHtml(reply, layout("Error", "projects", errorPage("invalid idea id")));
    }
    let idea;
    try {
      idea = await deps.services.getIdea(id);
      if (!idea) throw new ServiceError(404, `idea ${id} not found`);
    } catch (err) {
      const status = err instanceof ServiceError ? err.status : 500;
      reply.code(status);
      return setHtml(reply, layout("Not found", "projects", errorPage(err instanceof Error ? err.message : "error")));
    }
    if (idea.state === "icebox" || idea.state === "moved" || idea.state === "discarded") {
      reply.code(409);
      return setHtml(
        reply,
        layout(
          "Grooming",
          "projects",
          errorPage(
            `This idea is no longer in grooming (state: ${idea.state}). ` +
              `<a href="/projects/${idea.projectId}">Back to project</a>`,
          ),
        ),
      );
    }
    try {
      if (idea.state === "idea") {
        await deps.grooming.startGrooming(id, { background: true }); // transition; seed runs in background
      } else {
        await deps.grooming.transcript(id); // ensure the session is alive (resume)
      }
      const messages = await deps.grooming.transcript(id);
      const view: GroomPageData = {
        ideaId: id,
        projectId: idea.projectId,
        projectName: idea.projectName,
        ideaText: idea.text,
        messages,
        turn: deps.grooming.turnStatus(id),
      };
      return setHtml(reply, layout(`Grooming — ${idea.projectName}`, "projects", groomPage(view)));
    } catch (err) {
      sendError(reply, err, true);
    }
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
      sendError(reply, err, false);
    }
  });

  // Chat turn (HTMX): queue the user message and return it immediately;
  // the assistant reply appears via the 3s transcript poll. Turns are
  // serialized per idea — messages sent mid-turn are queued behind it.
  app.post("/ideas/:id/groom/messages", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    if (id === undefined) {
      reply.code(400);
      return setHtml(reply, `<div class="msg error">invalid idea id</div>`);
    }
    const fields = await requestFields(req);
    const text = (fields.message ?? "").trim();
    if (text === "") {
      reply.code(400);
      return setHtml(reply, `<div class="msg error">message is required</div>`);
    }
    let idea;
    try {
      idea = await deps.services.getIdea(id);
    } catch {
      idea = undefined;
    }
    if (!idea) {
      reply.code(404);
      return setHtml(reply, `<div class="msg error">idea ${id} not found</div>`);
    }
    if (idea.state !== "grooming") {
      reply.code(409);
      return setHtml(reply, `<div class="msg error">idea ${id} is not in grooming (state: ${idea.state})</div>`);
    }
    // Fire-and-forget turn; errors are logged (the user can resend).
    deps.grooming.postGroomMessage(id, text).catch((err) => {
      console.error(`[http] grooming turn failed for idea ${id}:`, err);
    });
    return setHtml(reply, groomMessageFragment("user", text));
  });

  const groomAction = (route: string, fn: (id: number) => Promise<{ projectId: number }>) => {
    app.post(route, async (req, reply) => {
      const id = parseId((req.params as Record<string, string>).id);
      const json = isJson(req);
      if (id === undefined) {
        if (json) return reply.code(400).send({ error: "invalid idea id" });
        return setHtml(reply, layout("Error", "projects", errorPage("invalid idea id")));
      }
      try {
        const idea = await fn(id);
        if (json) return idea;
        reply.code(302).headers({ location: `/projects/${idea.projectId}` }).send();
      } catch (err) {
        sendError(reply, err, !json);
      }
    });
  };

  // Accept: kick off the finalize turn in the background and return
  // immediately (the finalize LLM turn can take many minutes at xhigh).
  // The idea appears in the Icebox column when the spec lands.
  app.post("/ideas/:id/groom/accept", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    const json = isJson(req);
    if (id === undefined) {
      if (json) return reply.code(400).send({ error: "invalid idea id" });
      return setHtml(reply, layout("Error", "projects", errorPage("invalid idea id")));
    }
    let idea;
    try {
      idea = await deps.services.getIdea(id);
    } catch {
      idea = undefined;
    }
    if (!idea) {
      if (json) return reply.code(404).send({ error: `idea ${id} not found` });
      reply.code(404);
      return setHtml(reply, layout("Not found", "projects", errorPage(`idea ${id} not found`)));
    }
    if (idea.state !== "grooming") {
      const msg = `idea ${id} is not in grooming (state: ${idea.state})`;
      if (json) return reply.code(409).send({ error: msg });
      reply.code(409);
      return setHtml(reply, layout("Error", "projects", errorPage(msg)));
    }
    deps.grooming.postAcceptGrooming(id).catch((err) => {
      console.error(`[http] grooming finalize failed for idea ${id}:`, err);
    });
    if (json) return { ideaId: id, state: "grooming", finalizing: true };
    reply.code(302).headers({ location: `/projects/${idea.projectId}` }).send();
  });
  // Cancel: back to Idea, chat discarded.
  groomAction("/ideas/:id/groom/cancel", (id) => deps.grooming.cancelGrooming(id));
  // Re-groom: fresh chat session (re-seeded with the idea).
  app.post("/ideas/:id/groom/re-groom", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    const json = isJson(req);
    if (id === undefined) {
      if (json) return reply.code(400).send({ error: "invalid idea id" });
      return setHtml(reply, layout("Error", "projects", errorPage("invalid idea id")));
    }
    try {
      await deps.grooming.reGroom(id, { background: true }); // re-seed runs in background
      if (json) {
        const idea = await deps.services.getIdea(id);
        if (!idea) return reply.code(404).send({ error: `idea ${id} not found` });
        return idea;
      }
      reply.code(302).headers({ location: `/ideas/${id}/groom` }).send();
    } catch (err) {
      sendError(reply, err, !json);
    }
  });
  // Discard: delete the idea (soft: state `discarded`).
  groomAction("/ideas/:id/discard", (id) => deps.grooming.discardIdea(id));

  // Icebox → Backlog: move one or more finalized specs to the board.
  app.post("/projects/:id/icebox/move", async (req, reply) => {
    const id = parseId((req.params as Record<string, string>).id);
    const json = isJson(req);
    if (id === undefined) {
      if (json) return reply.code(400).send({ error: "invalid project id" });
      return setHtml(reply, layout("Error", "projects", errorPage("invalid project id")));
    }
    const project = await deps.services.getProject(id);
    if (!project) {
      if (json) return reply.code(404).send({ error: `project ${id} not found` });
      reply.code(404);
      return setHtml(reply, layout("Not found", "projects", errorPage("Project not found.")));
    }
    const fields = await requestFields(req);
    const ideaIds = (fields.idea_ids ?? "")
      .split(",")
      .map((s) => Number.parseInt(s.trim(), 10))
      .filter((n) => Number.isFinite(n) && n > 0);
    try {
      // Only this project's ideas may be moved through its route.
      const projectIdeas = new Set((await deps.services.listIdeas(id)).map((i) => i.id));
      const foreign = ideaIds.filter((n) => !projectIdeas.has(n));
      if (foreign.length > 0) {
        throw new ServiceError(400, `ideas ${foreign.join(", ")} do not belong to project ${id}`);
      }
      const result = await deps.services.moveIceboxToBacklog(ideaIds);
      if (json) return result;
      reply.code(302).headers({ location: `/projects/${id}` }).send();
    } catch (err) {
      sendError(reply, err, !json);
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
      months: data.spend.months.map((m) => ({ label: m.label, short: m.short, spend: m.spend })),
      total: data.spend.total,
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

  registerMcpRoutes(app, {
    cfg: deps.cfg,
    services: deps.services,
    keyCapabilities: deps.mcpKeyCapabilities,
  });

  return app;
}
