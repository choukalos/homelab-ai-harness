/**
 * MCP surface (PLAN.md §5/§10, SDK_NOTES.md §5): kanban tools exposed over
 * the standard @modelcontextprotocol/sdk as a thin layer over the same
 * transport-agnostic service functions the REST API uses.
 *
 * MCP-first (2026-11-21): the web UI is read-only; the MCP surface is the
 * only mutation interface. Tools (27): list_projects, get_project,
 * create_project, update_project, delete_project, list_ideas, add_idea,
 * edit_idea, board_status, interactive grooming (start_grooming,
 * groom_message, groom_status, groom_accept, groom_cancel, groom_re_groom),
 * discard_idea, move_to_backlog, start_task, pause/resume/stop_task,
 * retry_deploy, restart_task, task_status, project_status, file intake
 * (stage_file, stage_ref — remote client file intake, 2026-11-23).
 *
 * Owner attribution: the caller's LiteLLM key resolves to a user name via
 * USER_KEYS (full-key match); create_project / add_idea stamp it on the
 * row, and tasks inherit the idea's owner at move_to_backlog.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { CallToolRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import type { KanbanServices, Idea, ProjectInput } from "../services/index.js";
import {
  isPreflightStrict,
  preflightSpec,
  preflightSpecs,
  withPreflightWarning,
} from "../services/preflight.js";

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
  /** read + board mutation (ideas, interactive grooming, backlog, task control, file intake). */
  control: [
    "read",
    "add_idea",
    "edit_idea",
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
    "stage_file",
    "stage_ref",
  ],
  /** control + project administration + the agents master switch. */
  admin: ["control", "create_project", "update_project", "delete_project", "agents_switch"],
} as const;

export type McpCapability = keyof typeof MCP_CAPABILITY_SETS;

/** All MCP tool names (the full tool set the kanban key gets). */
export const MCP_TOOL_NAMES: readonly string[] = [
  "list_projects",
  "get_project",
  "create_project",
  "update_project",
  "delete_project",
  "list_ideas",
  "add_idea",
  "edit_idea",
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
  "stage_file",
  "stage_ref",
  "agents_switch",
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
 * Parse the MCP_KEY_CAPABILITIES env var: `keyref:cap1,cap2;...` where
 * keyref is either a key ALIAS (resolved to the full key via USER_KEYS —
 * stable across key rotation, Phase 13.3) or the TAIL of a Bearer key
 * (legacy suffix form — keys are secret, match on the last N chars).
 * caps are capability sets (read/control/admin) or individual tool names.
 * The kanban key (LITELLM_API_KEY) always gets the full set. Unknown
 * entries are dropped; an empty/invalid mapping yields {} (every
 * non-kanban key is rejected with a clear error).
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
 * - a keyref that is a USER_KEYS alias and the Bearer key equals the
 *   alias's full key → that entry's expanded tools (Phase 13.3 — exact
 *   full-key match, stable across key rotation);
 * - a key whose tail matches a legacy suffix entry → that entry's
 *   expanded tools (backward compatibility);
 * - anything else → null (the endpoint rejects the request with a clear
 *   "key not authorized" error).
 *
 * Alias entries NEVER fall back to suffix matching (no ambiguity);
 * keyrefs absent from userKeys keep the legacy suffix semantics.
 */
export function resolveMcpCapabilities(
  bearerKey: string,
  kanbanKey: string,
  mapping: Map<string, Set<string>> = new Map(),
  userKeys: Record<string, string> = {},
): Set<string> | null {
  if (bearerKey === kanbanKey) return new Set(MCP_TOOL_NAMES);
  for (const [keyref, caps] of mapping) {
    const aliasKey = userKeys[keyref];
    if (aliasKey !== undefined) {
      if (bearerKey === aliasKey) return expandCapabilities([...caps]);
    } else if (bearerKey.length >= keyref.length && bearerKey.endsWith(keyref)) {
      return expandCapabilities([...caps]);
    }
  }
  return null;
}

/**
 * Resolve the owner name for a Bearer key (improvements batch: derived from
 * USER_KEYS instead of the removed MCP_KEY_OWNERS suffix map — full-key
 * match, no suffix ambiguity, one less env var to keep in sync on key
 * rotation):
 * - the kanban key (LITELLM_API_KEY) → "kanban" (service-driven mutations);
 * - a key equal to a USER_KEYS value (name = full key) → that user name;
 * - anything else → "unknown" (authorized keys without spend attribution).
 */
export function resolveMcpOwner(
  bearerKey: string,
  kanbanKey: string,
  userKeys: Record<string, string> = {},
): string {
  if (bearerKey === kanbanKey) return "kanban";
  for (const [name, key] of Object.entries(userKeys)) {
    if (key !== "" && bearerKey === key) return name;
  }
  return "unknown";
}

/**
 * Build the MCP server with the kanban tools registered. When `allowedTools`
 * is given (per-key capability scoping), only those tools are registered and
 * the rest are invisible to tools/list; calls to unknown tool names are
 * answered with a clear "not available for this key" error. `owner` is the
 * caller's user name (key → user via USER_KEYS) stamped on the items the
 * caller creates.
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
    "delete_project",
    {
      description:
        "Delete a project (admin). Its ideas/tasks/usage rows are removed " +
        "(cascade) and the project's workspace scratch dirs are removed " +
        "immediately (the workspace is transitory — durable results of done " +
        "work are already pushed/published). Refused (409) while any task is " +
        "running/deploy — pause/stop it first.",
      inputSchema: { project_id: z.number().int().positive() },
    },
    ({ project_id }) => run(async () => ok(await services.deleteProject(project_id))),
  );

  reg(
    "agents_switch",
    {
      description:
        "Master on/off switch for ALL standing agents (product/strategist/" +
        "marketing/analyst). No args: read the current state. " +
        "state='on'|'off': set it (admin-only). When OFF the orchestrator " +
        "does not start agent-owned cards (the agent slot is zeroed each " +
        "tick; start_task on an agent card returns 409); in-flight agent " +
        "tasks run to completion. Fail-safe default is OFF (missing/malformed " +
        "state row). Durable (kv) — survives restarts.",
      inputSchema: { state: z.enum(["on", "off"]).optional() },
    },
    ({ state }) =>
      run(async () =>
        state === undefined
          ? ok(await services.getAgentsSwitch())
          : ok(await services.setAgentsSwitch(state, owner || "mcp")),
      ),
  );

  reg(
    "stage_file",
    {
      description:
        "Push a small input file (script, config, text — ≤ ~100 MB) into the project's durable file store. " +
        "`path` is RELATIVE to the project store (no .., no absolute paths); `content` is base64-encoded. " +
        "Returns the container-side path (/files/<project_id>/<path>) to cite in task specs — the executor " +
        "reads it directly. Staged files are retained for the life of the project (icebox-safe). " +
        "Media inputs (stills, reference video, audio) must NOT be pushed — place them on the NAS/public " +
        "drop and register the URL or path with stage_ref instead.",
      inputSchema: {
        project_id: z.number().int().positive(),
        path: z.string().min(1),
        content: z.string().min(1),
      },
    },
    ({ project_id, path, content }) =>
      run(async () => ok(await services.stageFile(project_id, path, content, owner))),
  );

  reg(
    "stage_ref",
    {
      description:
        "Register an external media reference for a project WITHOUT moving content: an http(s) URL " +
        "(validated with a bounded HTTP HEAD → 200) or a NAS path under /media-store (validated by " +
        "existence). Unreachable references are rejected at registration. The reference is recorded in " +
        "the project's file audit (project_files, size 0) so the preflight + audit trail have a " +
        "machine-checkable record. For media inputs: place the file on the NAS or the public drop " +
        "(https://choukalos.com/files/...) and register/cite its URL or container path.",
      inputSchema: {
        project_id: z.number().int().positive(),
        ref: z.string().min(1),
      },
    },
    ({ project_id, ref }) => run(async () => ok(await services.stageRef(project_id, ref, owner))),
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
    "edit_idea",
    {
      description:
        "Edit an idea's text before grooming (typos, scope tweaks). Only " +
        "ideas in the 'idea' state are editable — grooming/icebox specs are " +
        "generated from the text at grooming. Returns the updated idea.",
      inputSchema: {
        idea_id: z.number().int().positive(),
        text: z.string().min(1),
      },
    },
    ({ idea_id, text }) => run(async () => ok(await services.editIdea(idea_id, text))),
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
        "when their depends_on ideas have done tasks. Spec-path preflight runs first: " +
        "unreachable input references (client paths, dead URLs) return a structured " +
        "warning on the result (advisory; strict mode refuses when KANBAN_PREFLIGHT_STRICT=1).",
      inputSchema: { idea_ids: z.array(z.number().int().positive()).min(1) },
    },
    ({ idea_ids }) =>
      run(async () => {
        // Spec-path preflight (advisory; strict via KANBAN_PREFLIGHT_STRICT):
        // fail fast on unreachable inputs, before the move.
        const specs = (
          await Promise.all(idea_ids.map((id: number) => services.getIdea(id)))
        ).filter((idea): idea is Idea => idea !== undefined).map((idea) => idea.spec);
        const report = await preflightSpecs(specs, { strict: isPreflightStrict() });
        return ok(withPreflightWarning(await services.moveIceboxToBacklog(idea_ids), report));
      }),
  );

  reg(
    "start_task",
    {
      description:
        "Start a backlog task now (bypasses the pickup timer). Dependency and " +
        "per-category slot gates still apply (MEDIA_CONCURRENT_TASKS for " +
        "media-kind tasks, NON_MEDIA_CONCURRENT_TASKS for everything else). " +
        "Spec-path preflight runs first: unreachable input references return a " +
        "structured warning on the result (advisory; strict mode refuses when " +
        "KANBAN_PREFLIGHT_STRICT=1).",
      inputSchema: { task_id: z.number().int().positive() },
    },
    ({ task_id }) =>
      run(async () => {
        // Spec-path preflight (advisory; strict via KANBAN_PREFLIGHT_STRICT):
        // fail fast on unreachable inputs, before the start.
        const detail = await services.getTask(task_id);
        const report = detail
          ? await preflightSpec(detail.task.spec, { strict: isPreflightStrict() })
          : { checked: [], unreachable: [] };
        return ok(withPreflightWarning(await services.startTask(task_id), report));
      }),
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
