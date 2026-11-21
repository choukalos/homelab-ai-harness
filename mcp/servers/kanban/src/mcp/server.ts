/**
 * MCP surface (PLAN.md §5/§10, SDK_NOTES.md §5): kanban tools exposed over
 * the standard @modelcontextprotocol/sdk as a thin layer over the same
 * transport-agnostic service functions the REST API uses.
 *
 * Slice 1 tools: list_projects, get_project, create_project, update_project,
 * list_ideas, add_idea. Slice 2: groom_idea, move_to_backlog. Slice 3:
 * start_task, retry_deploy, restart_task, task_status. Slice 4:
 * project_status. Slice 5: control (pause_task, resume_task, stop_task).
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { CallToolRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import type { KanbanServices, ProjectInput } from "../services/index.js";

export type { KanbanServices } from "../services/index.js";

export const MCP_SERVER_INFO = { name: "ai-kanban", version: "0.1.0" } as const;

/**
 * MCP capability sets (guardrails for multi-user keys): the kanban key
 * (LITELLM_API_KEY) always gets the full tool set; other keys can be scoped
 * via MCP_KEY_CAPABILITIES (see resolveMcpCapabilities).
 */
export const MCP_CAPABILITY_SETS = {
  /** Read-only board/project/task inspection. */
  read: [
    "list_projects",
    "get_project",
    "list_ideas",
    "task_status",
    "project_status",
  ],
  /** read + board mutation (ideas, grooming, backlog, task control). */
  control: [
    "read",
    "add_idea",
    "groom_idea",
    "move_to_backlog",
    "start_task",
    "pause_task",
    "resume_task",
    "stop_task",
    "retry_deploy",
    "restart_task",
  ],
  /** control + project administration. */
  admin: ["control", "create_project", "update_project"],
} as const;

export type McpCapability = keyof typeof MCP_CAPABILITY_SETS;

/** All MCP tool names (the full tool set the kanban key gets). */
export const MCP_TOOL_NAMES: readonly string[] = [
  "list_projects",
  "get_project",
  "create_project",
  "update_project",
  "list_ideas",
  "add_idea",
  "groom_idea",
  "move_to_backlog",
  "start_task",
  "pause_task",
  "resume_task",
  "stop_task",
  "retry_deploy",
  "restart_task",
  "task_status",
  "project_status",
];

function expandCapabilities(set: readonly string[]): Set<string> {
  const out = new Set<string>();
  const visit = (name: string) => {
    const def = (MCP_CAPABILITY_SETS as Record<string, readonly string[]>)[name];
    if (def) {
      for (const sub of def) visit(sub);
    } else {
      out.add(name);
    }
  };
  for (const name of set) visit(name);
  return out;
}

/**
 * Parse the MCP_KEY_CAPABILITIES env var: `key-suffix:cap1,cap2;...` where
 * key-suffix is the TAIL of a Bearer key (keys are secret — match on the
 * last N chars) and caps are capability sets (read/control/admin) or
 * individual tool names. The kanban key (LITELLM_API_KEY) always gets the
 * full set. Unknown entries are dropped; an empty/invalid mapping yields
 * {} (every non-kanban key is rejected with a clear error).
 */
export function parseMcpKeyCapabilities(raw: string | undefined): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  if (!raw) return out;
  for (const entry of raw.split(";")) {
    const [suffix, caps] = entry.split(":");
    if (!suffix || !caps) continue;
    const suffixTrim = suffix.trim();
    const valid = new Set<string>();
    for (const cap of caps.split(",")) {
      const c = cap.trim();
      if (!c) continue;
      if ((MCP_CAPABILITY_SETS as Record<string, unknown>)[c] !== undefined || MCP_TOOL_NAMES.includes(c)) {
        valid.add(c);
      }
    }
    if (suffixTrim && valid.size > 0) out.set(suffixTrim, valid);
  }
  return out;
}

/**
 * Resolve the allowed tool set for a Bearer key:
 * - the kanban key (LITELLM_API_KEY) → the full tool set (always);
 * - a key whose tail matches a MCP_KEY_CAPABILITIES entry → that entry's
 *   expanded tools;
 * - anything else → null (the endpoint rejects the request with a clear
 *   "key not authorized" error).
 */
export function resolveMcpCapabilities(
  bearerKey: string,
  kanbanKey: string,
  mapping: Map<string, Set<string>> = new Map(),
): Set<string> | null {
  if (bearerKey === kanbanKey) return new Set(MCP_TOOL_NAMES);
  for (const [suffix, caps] of mapping) {
    if (bearerKey.length >= suffix.length && bearerKey.endsWith(suffix)) {
      return expandCapabilities([...caps]);
    }
  }
  return null;
}

/**
 * Build the MCP server with the kanban tools registered. When `allowedTools`
 * is given (per-key capability scoping), only those tools are registered and
 * the rest are invisible to tools/list; calls to unknown tool names are
 * answered with a clear "not available for this key" error.
 */
export function createKanbanMcpServer(services: KanbanServices, allowedTools?: Set<string>): McpServer {
  // Declaring the tools capability up front makes tools/list respond
  // instead of "Method not found".
  const server = new McpServer(
    { ...MCP_SERVER_INFO },
    { capabilities: { tools: { listChanged: true } } },
  );
  registerMcpTools(server, services, allowedTools);
  if (allowedTools) {
    // Scoped keys: answer calls to out-of-scope tool names with a clear
    // error instead of the SDK's generic "Tool not found". The SDK
    // registers its own tools/call handler in the constructor; capture it
    // before replacing with the guard.
    const originalCallHandler = (
      server as unknown as {
        server: {
          _requestHandlers: Map<string, (r: unknown, e: unknown) => Promise<Record<string, unknown>>>;
        };
      }
    ).server._requestHandlers.get("tools/call")!;
    server.server.setRequestHandler(
      CallToolRequestSchema,
      async (req, extra) => {
        const name = req.params.name;
        if (!allowedTools.has(name)) {
          return {
            content: [
              {
                type: "text" as const,
                text: `tool ${name} is not available for this key (MCP_KEY_CAPABILITIES); ask the operator to extend the key's capability set`,
              },
            ],
            isError: true,
          };
        }
        // Delegate to the McpServer's own tools/call handler (registered
        // during construction; setRequestHandler replaces it for the
        // out-of-scope guard, so keep the original for in-scope tools).
        return originalCallHandler(req, extra);
      },
    );
  }
  return server;
}

type ToolResult = { content: Array<{ type: "text"; text: string }>; isError?: boolean };

/** Success result: the service value as pretty JSON. */
function ok(value: unknown): ToolResult {
  return { content: [{ type: "text", text: JSON.stringify(value, null, 2) }] };
}

/** Failure result: the error message (ServiceError messages are user-facing). */
function fail(err: unknown): ToolResult {
  const msg = err instanceof Error ? err.message : String(err);
  return { content: [{ type: "text", text: msg }], isError: true };
}

/** Run a tool handler, converting thrown errors into MCP error results. */
function run(fn: () => Promise<ToolResult>): Promise<ToolResult> {
  return fn().catch(fail);
}

/** Project field shape shared by create_project / update_project. */
const projectFields = {
  description: z.string().optional(),
  goal: z.string().optional(),
  repo_url: z.string().optional(),
  default_branch: z.string().optional(),
  blog_repo_url: z.string().optional(),
  blog_content_path: z.string().optional(),
  media_paths: z.array(z.string()).optional(),
  constraints: z.string().optional(),
  architecture_notes: z.string().optional(),
  notes: z.string().optional(),
};

const projectFieldsSchema = z.object(projectFields);

type ProjectFieldArgs = z.infer<typeof projectFieldsSchema>;

function toProjectInput(args: { name?: string } & ProjectFieldArgs): ProjectInput {
  return {
    name: args.name,
    description: args.description,
    goal: args.goal,
    repoUrl: args.repo_url,
    defaultBranch: args.default_branch,
    blogRepoUrl: args.blog_repo_url,
    blogContentPath: args.blog_content_path,
    mediaPaths: args.media_paths,
    constraints: args.constraints,
    architectureNotes: args.architecture_notes,
    notes: args.notes,
  };
}

/**
 * Tool registration over the service layer. Each tool mirrors a service
 * function (Slice 1: projects/ideas). When `allowedTools` is given, only
 * those tools are registered (per-key capability scoping) and the rest are
 * invisible to tools/list.
 */
export function registerMcpTools(server: McpServer, services: KanbanServices, allowedTools?: Set<string>): void {
  const reg = (
    name: string,
    def: { description: string; inputSchema?: Record<string, unknown> },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- tool handlers are per-tool typed
    handler: (...args: any[]) => Promise<ToolResult>,
  ) => {
    if (allowedTools && !allowedTools.has(name)) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    server.registerTool(name, def as any, handler);
  };

  reg(
    "list_projects",
    { description: "List all projects (id, name, description)." },
    () => run(async () => ok(await services.listProjects())),
  );

  reg(
    "get_project",
    {
      description: "Get one project by id (full spec, incl. LLM state summary).",
      inputSchema: { project_id: z.number().int().positive() },
    },
    ({ project_id }) =>
      run(async () => {
        const p = await services.getProject(project_id);
        if (!p) return fail(new Error(`project ${project_id} not found`));
        return ok(p);
      }),
  );

  reg(
    "create_project",
    {
      description:
        "Create a project. name is required (unique); other fields optional " +
        "(repo_url + default_branch, blog_repo_url + blog_content_path, media_paths, ...).",
      inputSchema: { name: z.string().min(1), ...projectFields },
    },
    (args) => run(async () => ok(await services.createProject(toProjectInput(args)))),
  );

  reg(
    "update_project",
    {
      description:
        "Update a project by id. Only provided fields change; name may be " +
        "provided to rename (must stay unique).",
      inputSchema: {
        project_id: z.number().int().positive(),
        name: z.string().min(1).optional(),
        ...projectFields,
      },
    },
    (args) =>
      run(async () => {
        const { project_id, ...fields } = args;
        const p = await services.updateProject(project_id, toProjectInput(fields));
        if (!p) return fail(new Error(`project ${project_id} not found`));
        return ok(p);
      }),
  );

  reg(
    "list_ideas",
    {
      description:
        "List ideas (id, project, text, state, spec, depends_on), optionally filtered by project_id.",
      inputSchema: { project_id: z.number().int().positive().optional() },
    },
    ({ project_id }) => run(async () => ok(await services.listIdeas(project_id))),
  );

  reg(
    "add_idea",
    {
      description: "Drop a raw idea (state=idea) into a project.",
      inputSchema: {
        project_id: z.number().int().positive(),
        text: z.string().min(1),
      },
    },
    ({ project_id, text }) => run(async () => ok(await services.addIdea(project_id, text))),
  );

  reg(
    "groom_idea",
    {
      description:
        "Autonomous one-shot grooming for non-GUI clients: runs the idea's grooming " +
        "session and finalizes the structured spec (goal/steps/acceptance/kind/" +
        "publish_targets/notes) plus LLM-identified depends_on among the project's " +
        "current icebox items. The idea moves to the icebox. Idempotent if the idea " +
        "is already in the icebox (returns the existing spec).",
      inputSchema: { idea_id: z.number().int().positive() },
    },
    ({ idea_id }) => run(async () => ok(await services.groomIdea(idea_id))),
  );

  reg(
    "move_to_backlog",
    {
      description:
        "Move one or more icebox items to the board backlog (creates their tasks). " +
        "All listed ideas must be in the icebox; the orchestrator starts them only " +
        "when their depends_on ideas have done tasks.",
      inputSchema: { idea_ids: z.array(z.number().int().positive()).min(1) },
    },
    ({ idea_ids }) => run(async () => ok(await services.moveIceboxToBacklog(idea_ids))),
  );

  reg(
    "start_task",
    {
      description:
        "Start a backlog task now (bypasses the pickup timer). Dependency and " +
        "CONCURRENT_TASKS slot gates still apply.",
      inputSchema: { task_id: z.number().int().positive() },
    },
    ({ task_id }) => run(async () => ok(await services.startTask(task_id))),
  );

  reg(
    "pause_task",
    {
      description:
        "Pause a running task: the session is aborted and the task keeps its " +
        "running state with the paused flag (orthogonal to the state machine). " +
        "Resume it with resume_task (one-click, re-runs from last_commit).",
      inputSchema: { task_id: z.number().int().positive() },
    },
    ({ task_id }) => run(async () => ok(await services.pauseTask(task_id))),
  );

  reg(
    "resume_task",
    {
      description:
        "One-click resume of a paused task: un-pause and re-run from " +
        "last_commit (mission brief + progress summary re-injected).",
      inputSchema: { task_id: z.number().int().positive() },
    },
    ({ task_id }) => run(async () => ok(await services.resumeTask(task_id))),
  );

  reg(
    "stop_task",
    {
      description:
        "Stop a running task (same as pause_task: the session is aborted and " +
        "the task keeps its running state with the paused flag).",
      inputSchema: { task_id: z.number().int().positive() },
    },
    ({ task_id }) => run(async () => ok(await services.stopTask(task_id))),
  );

  reg(
    "retry_deploy",
    {
      description:
        "Re-run ONLY the deploy step for a task stuck in deploy, or a " +
        "needs_attention task whose failure was a deploy failure. QA-exhausted " +
        "tasks must go through restart_task (resolution) first.",
      inputSchema: { task_id: z.number().int().positive() },
    },
    ({ task_id }) => run(async () => ok(await services.retryDeploy(task_id))),
  );

  reg(
    "restart_task",
    {
      description:
        "Send a needs_attention task back to the backlog (resume from last " +
        "commit, QA rounds reset). An optional resolution_note becomes the " +
        "accepted plan injected into the mission brief — the remote equivalent " +
        "of the resolution dialog (task_status supplies the failure context).",
      inputSchema: {
        task_id: z.number().int().positive(),
        resolution_note: z.string().min(1).optional(),
      },
    },
    ({ task_id, resolution_note }) =>
      run(async () => ok(await services.restartTask(task_id, resolution_note))),
  );

  reg(
    "task_status",
    {
      description:
        "Task state, log tail, usage (total + by role), failure reason " +
        "(needs_attention), and the accepted resolution plan if any.",
      inputSchema: { task_id: z.number().int().positive() },
    },
    ({ task_id }) =>
      run(async () => {
        const s = await services.taskStatus(task_id);
        if (!s) return fail(new Error(`task ${task_id} not found`));
        return ok(s);
      }),
  );

  reg(
    "project_status",
    {
      description:
        "Project status: full spec incl. the LLM-maintained state summary, " +
        "the icebox listing (finalized specs + LLM-identified depends_on), " +
        "and task counts per board state.",
      inputSchema: { project_id: z.number().int().positive() },
    },
    ({ project_id }) =>
      run(async () => {
        const s = await services.projectStatus(project_id);
        if (!s) return fail(new Error(`project ${project_id} not found`));
        return ok(s);
      }),
  );
}
