/**
 * MCP surface (PLAN.md §5/§10, SDK_NOTES.md §5): kanban tools exposed over
 * the standard @modelcontextprotocol/sdk as a thin layer over the same
 * transport-agnostic service functions the REST API uses.
 *
 * MCP-first (2026-11-21): the web UI is read-only; the MCP surface is the
 * only mutation interface. Tools: list_projects, get_project,
 * create_project, update_project, list_ideas, add_idea, board_status,
 * interactive grooming (start_grooming, groom_message, groom_status,
 * groom_accept, groom_cancel, groom_re_groom), discard_idea,
 * move_to_backlog, start_task, pause/resume/stop_task, retry_deploy,
 * restart_task, task_status, project_status.
 *
 * Owner attribution: the caller's LiteLLM key resolves to a user name
 * (MCP_KEY_OWNERS); create_project / add_idea stamp it on the row, and
 * tasks inherit the idea's owner at move_to_backlog.
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
    "board_status",
    "task_status",
    "project_status",
  ],
  /** read + board mutation (ideas, interactive grooming, backlog, task control). */
  control: [
    "read",
    "add_idea",
    "start_grooming",
    "groom_message",
    "groom_status",
    "groom_accept",
    "groom_cancel",
    "groom_re_groom",
    "discard_idea",
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
  "board_status",
  "start_grooming",
  "groom_message",
  "groom_status",
  "groom_accept",
  "groom_cancel",
  "groom_re_groom",
  "discard_idea",
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
 * Parse the MCP_KEY_OWNERS env var: `name:key-suffix;...` where key-suffix
 * is the TAIL of a Bearer key (same tail-matching style as
 * MCP_KEY_CAPABILITIES — keys are secret, match on the last N chars).
 * Maps a caller key to the user name stamped on the items they create
 * (owner attribution). Unknown/malformed entries are dropped; an empty
 * mapping yields {} (non-kanban keys resolve to "unknown").
 */
export function parseMcpKeyOwners(raw: string | undefined): Map<string, string> {
  const out = new Map<string, string>();
  if (!raw) return out;
  for (const entry of raw.split(";")) {
    const [name, suffix] = entry.split(":");
    const n = (name ?? "").trim();
    const s = (suffix ?? "").trim();
    if (n && s) out.set(s, n);
  }
  return out;
}

/**
 * Resolve the owner name for a Bearer key:
 * - the kanban key (LITELLM_API_KEY) → "kanban" (service-driven mutations);
 * - a key whose tail matches a MCP_KEY_OWNERS entry → that user name;
 * - anything else → "unknown" (authorized keys missing from the map).
 */
export function resolveMcpOwner(
  bearerKey: string,
  kanbanKey: string,
  mapping: Map<string, string> = new Map(),
): string {
  if (bearerKey === kanbanKey) return "kanban";
  for (const [suffix, name] of mapping) {
    if (bearerKey.length >= suffix.length && bearerKey.endsWith(suffix)) {
      return name;
    }
  }
  return "unknown";
}

/**
 * Build the MCP server with the kanban tools registered. When `allowedTools`
 * is given (per-key capability scoping), only those tools are registered and
 * the rest are invisible to tools/list; calls to unknown tool names are
 * answered with a clear "not available for this key" error. `owner` is the
 * caller's user name (key → user via MCP_KEY_OWNERS) stamped on the items
 * the caller creates.
 */
export function createKanbanMcpServer(
  services: KanbanServices,
  allowedTools?: Set<string>,
  owner = "",
): McpServer {
  // Declaring the tools capability up front makes tools/list respond
  // instead of "Method not found".
  const server = new McpServer(
    { ...MCP_SERVER_INFO },
    { capabilities: { tools: { listChanged: true } } },
  );
  registerMcpTools(server, services, allowedTools, owner);
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
export function registerMcpTools(
  server: McpServer,
  services: KanbanServices,
  allowedTools?: Set<string>,
  owner = "",
): void {
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
        "(repo_url + default_branch, blog_repo_url + blog_content_path, media_paths, ...). " +
        "The project is stamped with the caller's owner.",
      inputSchema: { name: z.string().min(1), ...projectFields },
    },
    (args) => run(async () => ok(await services.createProject(toProjectInput(args), owner))),
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
      description:
        "Drop a raw idea (state=idea) into a project. The idea is stamped with " +
        "the caller's owner (it propagates to the idea's task).",
      inputSchema: {
        project_id: z.number().int().positive(),
        text: z.string().min(1),
      },
    },
    ({ project_id, text }) => run(async () => ok(await services.addIdea(project_id, text, owner))),
  );

  reg(
    "board_status",
    {
      description:
        "Board overview focused on needs-attention: task counts per state, " +
        "each needs-attention task (title, project, owner, failure reason, last " +
        "activity, accepted resolution if any), and running tasks (paused, cost). " +
        "Resolve a needs-attention task one by one: task_status(task_id) for the " +
        "full failure context + log tail, dialog with the user, then " +
        "restart_task(task_id, resolution_note).",
      inputSchema: {
        project_id: z.number().int().positive().optional(),
        owner: z.string().min(1).optional(),
      },
    },
    ({ project_id, owner: ownerFilter }) =>
      run(async () =>
        ok(
          await services.boardStatus(
            {
              ...(project_id !== undefined ? { projectId: project_id } : {}),
              ...(ownerFilter !== undefined ? { owner: ownerFilter } : {}),
            },
          ),
        ),
      ),
  );

  reg(
    "start_grooming",
    {
      description:
        "Start INTERACTIVE grooming for an idea (state idea → grooming): runs " +
        "the seed turn, in which the grooming LLM researches (web/KB/memory via " +
        "its session tools), states its assumptions, and asks questions. Returns " +
        "the idea + the assistant's seed message — relay it to the user and " +
        "answer its questions with groom_message. This is the only grooming " +
        "path: grooming is interactive by design (the user steers before the " +
        "idea is prepped for execution).",
      inputSchema: { idea_id: z.number().int().positive() },
    },
    ({ idea_id }) => run(async () => ok(await services.groomStart(idea_id))),
  );

  reg(
    "groom_message",
    {
      description:
        "Send one user message to an idea's interactive grooming session " +
        "(state grooming) and wait for the assistant's reply (blocking; the " +
        "reply may take minutes at deep thinking levels — relay it to the " +
        "user). Answer the assistant's questions, correct its assumptions, or " +
        "share links/images for it to analyze.",
      inputSchema: {
        idea_id: z.number().int().positive(),
        text: z.string().min(1),
      },
    },
    ({ idea_id, text }) => run(async () => ok(await services.groomMessage(idea_id, text))),
  );

  reg(
    "groom_status",
    {
      description:
        "Poll an idea's grooming state: state (idea/grooming/icebox/...), " +
        "whether a turn is in flight (label + since), the transcript tail " +
        "(last 5 messages), and the finalized spec once the idea is in the " +
        "icebox. Poll after groom_accept until state=icebox.",
      inputSchema: { idea_id: z.number().int().positive() },
    },
    ({ idea_id }) => run(async () => ok(await services.groomStatus(idea_id))),
  );

  reg(
    "groom_accept",
    {
      description:
        "Accept the grooming: the finalize turn runs in the BACKGROUND (xhigh " +
        "finalize can take several minutes) and produces the structured spec " +
        "(goal/steps/acceptance/kind/publish_targets/notes) plus LLM-identified " +
        "depends_on among the project's current icebox items. Returns the idea " +
        "(state still grooming); poll groom_status until state=icebox (spec " +
        "present). A failed finalize leaves the idea in grooming — keep " +
        "chatting (groom_message) or re-accept.",
      inputSchema: { idea_id: z.number().int().positive() },
    },
    ({ idea_id }) => run(async () => ok(await services.groomAccept(idea_id))),
  );

  reg(
    "groom_cancel",
    {
      description:
        "Cancel grooming (state grooming → idea): the chat session is " +
        "discarded. The idea text is kept and can be re-groomed later.",
      inputSchema: { idea_id: z.number().int().positive() },
    },
    ({ idea_id }) => run(async () => ok(await services.groomCancel(idea_id))),
  );

  reg(
    "groom_re_groom",
    {
      description:
        "Re-groom (state grooming → grooming): the chat session is replaced " +
        "with a fresh one, re-seeded with the idea (awaited re-seed). Use when " +
        "the conversation went off the rails.",
      inputSchema: { idea_id: z.number().int().positive() },
    },
    ({ idea_id }) => run(async () => ok(await services.groomReGroom(idea_id))),
  );

  reg(
    "discard_idea",
    {
      description:
        "Discard an idea (state idea/grooming → discarded, soft-deleted — an " +
        "audit trail is kept). Icebox items cannot be discarded (they have a " +
        "finalized spec; move them to the backlog instead).",
      inputSchema: { idea_id: z.number().int().positive() },
    },
    ({ idea_id }) => run(async () => ok(await services.discardIdea(idea_id))),
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
