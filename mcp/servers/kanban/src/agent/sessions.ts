/**
 * Pi session lifecycle (SDK_NOTES.md; PLAN.md §1/§7).
 *
 * - App-owned agent dir (<data>/pi-agent) with models.json + auth.json for
 *   the LiteLLM provider (openai-completions, baseUrl from LITELLM_BASE_URL).
 * - ModelRuntime with static models (no network refresh at boot).
 * - createAgentSession with per-role thinking levels (groom/task/qa/summary;
 *   resolve reuses the QA level — PLAN.md §3).
 * - DefaultResourceLoader: noExtensions (the app controls extensions),
 *   harness skills via additionalSkillPaths, LiteLLM-proxy MCP tools via
 *   createMcpExtension (tool set is dynamic — picked up at session start).
 * - Session files persisted under <data>/sessions (SessionManager).
 * - Usage capture hook from assistant message usage (PLAN.md §11).
 *
 * <data> defaults to /data (container volume); override with the
 * AI_KANBAN_DATA_DIR env var or AgentRuntime.create(cfg, { dataDir }) for
 * local dev/tests.
 */
import { execFile } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import {
  DefaultResourceLoader,
  ModelRuntime,
  SessionManager,
  SettingsManager,
  createAgentSession,
  createMcpExtension,
  type AgentSession,
} from "@earendil-works/pi-coding-agent";
import type { AgentMessage, ThinkingLevel } from "@earendil-works/pi-agent-core";
import { calculateCost, type Model } from "@earendil-works/pi-ai/compat";
import type { KanbanConfig } from "../config.js";
import type { IdeaSpec } from "../db/schema.js";
import { extractMessageText, lastAssistantText } from "./grooming.js";

const pExecFile = promisify(execFile);

export type AgentRole = "groom" | "task" | "qa" | "summary" | "resolve";

/** Provider id used in models.json / auth.json (SDK_NOTES.md §1). */
export const LITELLM_PROVIDER = "litellm";

/** Catalog rates in $/M tokens (the units pi-ai's calculateCost expects). */
export interface ModelCostRates {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
}

/**
 * Rates to price usage with. Sourced at startup from the LiteLLM proxy's
 * /model/info (loadConfig → cfg.modelCost for the pipeline model,
 * cfg.ownerModelCosts for mapped owner models, item 15). `model` selects the
 * per-model rates: the pipeline model (cfg.model) uses cfg.modelCost; a
 * mapped owner model uses its own rates — or all-zero when the proxy has no
 * costs configured for it (never the pipeline model's rates, which would
 * price one model at another's rate). Undefined → all-zero (cost estimates
 * stay $0; tokens are still tracked and reports show $0.00).
 */
export function modelCostRates(cfg: KanbanConfig, model?: string): ModelCostRates {
  if (model !== undefined && model !== cfg.model) {
    return cfg.ownerModelCosts?.[model] ?? { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
  }
  return cfg.modelCost ?? { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 };
}

/** Usage from one assistant message (feeds the usage table, PLAN.md §2/§11). */
export interface UsageSample {
  role: AgentRole;
  model: string;
  thinking: ThinkingLevel;
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
  totalTokens: number;
  /** Best available total cost (provider-reported or catalog estimate). */
  cost: number;
}

export interface AgentSessionHandle {
  session: AgentSession;
  role: AgentRole;
  /** Path of the persisted session file (undefined for in-memory sessions). */
  sessionFile: string | undefined;
  dispose(): void;
}

export interface CreateSessionOptions {
  role: AgentRole;
  /** Session working directory (e.g. /workspace/task-<id>). */
  cwd: string;
  /** Replace the default system prompt (e.g. the task mission brief). */
  systemPrompt?: string;
  /** Append to the default system prompt. */
  appendSystemPrompt?: string[];
  /** Tool allowlist; omit for the default built-in tools. */
  tools?: string[];
  /** Resume an existing persisted session file instead of starting fresh. */
  sessionFile?: string;
  /**
   * Owner (USER_KEYS name) the session's LLM calls bill to (Phase 2):
   * a mapped owner runs on that user's key profile; no owner / unmapped
   * owner → the service key profile (default).
   */
  owner?: string;
  /**
   * Run the session on the pipeline model (cfg.model) instead of the
   * profile's model (item 15): service sessions (summary, ...) run on
   * KANBAN_MODEL even when the owner is mapped to another model — billing
   * still goes to the profile's key.
   */
  useServiceModel?: boolean;
  /** Called with usage for each completed assistant message. */
  onUsage?: (usage: UsageSample) => void;
}

export interface AgentRuntimeOptions {
  /** Data dir root (default: AI_KANBAN_DATA_DIR env, else /data). */
  dataDir?: string;
}

/**
 * A key profile: one app-owned agent dir (models.json + auth.json +
 * models-store.json) with its own ModelRuntime. The `service` profile holds
 * LITELLM_API_KEY; each USER_KEYS entry gets a per-user profile so sessions
 * for that owner bill LLM spend to the user's key (Phase 2).
 */
export interface KeyProfile {
  /** Profile name: "service" or a USER_KEYS owner name. */
  name: string;
  /** App-owned agent dir for this profile. */
  dir: string;
  modelRuntime: ModelRuntime;
  /** The profile's pipeline model (the owner model for mapped owners, item 15). */
  model: Model<any>;
  /**
   * The pipeline model (cfg.model) on this profile's runtime (item 15):
   * service sessions (summary, ...) run on KANBAN_MODEL even for a mapped
   * owner, billed to the owner's key. === `model` for the service profile
   * and unmapped owners.
   */
  serviceModel: Model<any>;
}

/**
 * models.json for the LiteLLM provider (SDK_NOTES.md §1 shape). Carries the
 * profile's model PLUS the pipeline model (cfg.model) — deduped when they're
 * the same — so a profile's ModelRuntime can also serve service sessions
 * (item 15: summary & co. run on KANBAN_MODEL, billed to the owner's key).
 */
export function buildModelsJson(cfg: KanbanConfig, model?: string): Record<string, unknown> {
  const ids = model === undefined || model === cfg.model ? [cfg.model] : [model, cfg.model];
  return {
    providers: {
      [LITELLM_PROVIDER]: {
        baseUrl: cfg.litellm.baseUrl,
        api: "openai-completions",
        models: ids.map((id) => ({
          id,
          name: id,
          reasoning: true,
          input: ["text"],
          contextWindow: 200000,
          maxTokens: 32768,
          // Catalog rates from the proxy's /model/info (see modelCostRates);
          // zero = no cost estimate available (reports show $0.00, tokens
          // still tracked).
          cost: modelCostRates(cfg, id),
        })),
      },
    },
  };
}

export class AgentRuntime {
  readonly dataDir: string;
  /** Service (default) profile's agent dir — the historical path. */
  readonly agentDir: string;
  readonly sessionsDir: string;
  readonly skillsPath: string;
  /** LiteLLM-proxy MCP endpoint (origin of LITELLM_BASE_URL + /mcp). */
  readonly litellmMcpUrl: string;

  private readonly cfg: KanbanConfig;
  private readonly serviceProfile: KeyProfile;
  private readonly profiles = new Map<string, KeyProfile>();
  private readonly sessions = new Set<AgentSessionHandle>();

  private constructor(
    cfg: KanbanConfig,
    serviceProfile: KeyProfile,
    profiles: Map<string, KeyProfile>,
    dirs: { dataDir: string; agentDir: string; sessionsDir: string; skillsPath: string },
    litellmMcpUrl: string,
  ) {
    this.cfg = cfg;
    this.serviceProfile = serviceProfile;
    this.profiles = profiles;
    this.dataDir = dirs.dataDir;
    this.agentDir = dirs.agentDir;
    this.sessionsDir = dirs.sessionsDir;
    this.skillsPath = dirs.skillsPath;
    this.litellmMcpUrl = litellmMcpUrl;
  }

  /**
   * Materialize the app-owned agent dirs (one key profile each: models.json
   * + auth.json) and create the model runtimes. No network access
   * (refreshOnCreate: false). Profiles: `service` (LITELLM_API_KEY, the
   * default) + one per USER_KEYS entry (per-user spend attribution).
   */
  static async create(cfg: KanbanConfig, opts: AgentRuntimeOptions = {}): Promise<AgentRuntime> {
    const dataDir = opts.dataDir ?? process.env.AI_KANBAN_DATA_DIR ?? "/data";
    const sessionsDir = path.join(dataDir, "sessions");
    const skillsPath = path.join(dataDir, "harness", cfg.harness.skillsPath);
    mkdirSync(sessionsDir, { recursive: true });

    const buildProfile = async (name: string, apiKey: string, model: string): Promise<KeyProfile> => {
      const dir =
        name === "service" ? path.join(dataDir, "pi-agent") : path.join(dataDir, `pi-agent-${name}`);
      mkdirSync(dir, { recursive: true });
      writeFileSync(path.join(dir, "models.json"), JSON.stringify(buildModelsJson(cfg, model), null, 2) + "\n");
      writeFileSync(
        path.join(dir, "auth.json"),
        JSON.stringify({ [LITELLM_PROVIDER]: { type: "api_key", key: apiKey } }, null, 2) + "\n",
      );
      const modelRuntime = await ModelRuntime.create({
        authPath: path.join(dir, "auth.json"),
        modelsPath: path.join(dir, "models.json"),
        modelsStorePath: path.join(dir, "models-store.json"),
        refreshOnCreate: false, // static models, no network refresh at boot
      });
      const profileModel = modelRuntime.getModel(LITELLM_PROVIDER, model);
      if (!profileModel) {
        throw new Error(
          `model ${model} not available in the ${LITELLM_PROVIDER} provider config ` +
            `(see ${path.join(dir, "models.json")})`,
        );
      }
      // The pipeline model is always in this profile's models.json (item 15):
      // service sessions run on cfg.model, billed to this profile's key.
      const serviceModel = modelRuntime.getModel(LITELLM_PROVIDER, cfg.model);
      if (!serviceModel) {
        throw new Error(
          `model ${cfg.model} not available in the ${LITELLM_PROVIDER} provider config ` +
            `(see ${path.join(dir, "models.json")})`,
        );
      }
      return { name, dir, modelRuntime, model: profileModel, serviceModel };
    };

    const service = await buildProfile("service", cfg.litellm.apiKey, cfg.model);
    const profiles = new Map<string, KeyProfile>([["service", service]]);
    for (const [name, key] of Object.entries(cfg.userKeys)) {
      // Per-owner pipeline model (item 15): a mapped owner runs on its own
      // model (billed to the owner's key); unmapped owners stay on the
      // pipeline model.
      profiles.set(name, await buildProfile(name, key, cfg.ownerModels[name] ?? cfg.model));
    }

    const u = new URL(cfg.litellm.baseUrl);
    u.pathname = "/mcp";

    return new AgentRuntime(
      cfg,
      service,
      profiles,
      { dataDir, agentDir: service.dir, sessionsDir, skillsPath },
      u.toString(),
    );
  }

  /**
   * Pick the key profile for a session (Phase 2): a mapped owner name runs
   * on that user's key; no owner or an unmapped owner falls back to the
   * service key (with a log note in the latter case).
   */
  profileFor(owner?: string): KeyProfile {
    if (owner && this.profiles.has(owner)) return this.profiles.get(owner)!;
    if (owner) {
      console.warn(
        `[agent] no USER_KEYS entry for owner ${JSON.stringify(owner)} — ` +
          `the session bills to the service key`,
      );
    }
    return this.serviceProfile;
  }

  /** Owner names with a dedicated key profile (USER_KEYS entries). */
  userProfileNames(): string[] {
    return [...this.profiles.keys()].filter((n) => n !== "service");
  }

  /** Per-role thinking level (PLAN.md §3); resolve reuses the QA level. */
  thinkingLevel(role: AgentRole): ThinkingLevel {
    switch (role) {
      case "groom":
        return this.cfg.thinking.groom;
      case "task":
        return this.cfg.thinking.task;
      case "qa":
        return this.cfg.thinking.qa;
      case "summary":
        return this.cfg.thinking.summary;
      case "resolve":
        return this.cfg.thinking.qa;
    }
  }

  /**
   * Create (or resume, via sessionFile) a Pi agent session for a role.
   * Session files are persisted under <data>/sessions.
   */
  async createSession(opts: CreateSessionOptions): Promise<AgentSessionHandle> {
    const thinking = this.thinkingLevel(opts.role);
    const profile = this.profileFor(opts.owner);
    // Item 15: service sessions (summary, ...) run on the pipeline model
    // even for a mapped owner (billed to the owner's key).
    const sessionModel = opts.useServiceModel ? profile.serviceModel : profile.model;
    const loader = new DefaultResourceLoader({
      cwd: opts.cwd,
      agentDir: profile.dir,
      settingsManager: SettingsManager.create(opts.cwd, profile.dir),
      noExtensions: true, // app controls extensions itself
      additionalSkillPaths: [this.skillsPath],
      extensionFactories: [createMcpExtension({ loadConfig: () => this.litellmMcpConfig() })],
      ...(opts.systemPrompt !== undefined ? { systemPrompt: opts.systemPrompt } : {}),
      ...(opts.appendSystemPrompt !== undefined ? { appendSystemPrompt: opts.appendSystemPrompt } : {}),
    });
    await loader.reload();

    const sessionManager = opts.sessionFile
      ? SessionManager.open(opts.sessionFile, this.sessionsDir, opts.cwd)
      : SessionManager.create(opts.cwd, this.sessionsDir);

    const { session } = await createAgentSession({
      cwd: opts.cwd,
      modelRuntime: profile.modelRuntime,
      model: sessionModel,
      thinkingLevel: thinking,
      ...(opts.tools !== undefined ? { tools: opts.tools } : {}),
      resourceLoader: loader,
      sessionManager,
    });

    if (opts.onUsage) {
      const onUsage = opts.onUsage;
      session.subscribe((event) => {
        if (event.type !== "message_end") return;
        const msg = event.message;
        if (msg.role !== "assistant" || !msg.usage) return;
        // The openai-completions API (LiteLLM proxy) prices usage at the
        // model's catalog cost. Our models.json carries the rates fetched
        // from the proxy's /model/info at startup (cfg.modelCost for the
        // pipeline model, cfg.ownerModelCosts for mapped owner models —
        // item 15); if those were unavailable the catalog is all-zero and
        // the SDK's estimate is $0 — recompute only when rates are actually
        // configured for THIS session's model.
        const rates = modelCostRates(this.cfg, sessionModel.id);
        if (rates.input > 0 || rates.output > 0) calculateCost(sessionModel, msg.usage);
        onUsage({
          role: opts.role,
          model: msg.model,
          thinking,
          input: msg.usage.input,
          output: msg.usage.output,
          cacheRead: msg.usage.cacheRead,
          cacheWrite: msg.usage.cacheWrite,
          totalTokens: msg.usage.totalTokens,
          cost: msg.usage.cost?.total ?? 0,
        });
      });
    }

    const handle: AgentSessionHandle = {
      session,
      role: opts.role,
      sessionFile: session.sessionFile,
      dispose: () => session.dispose(),
    };
    this.sessions.add(handle);
    return handle;
  }

  /** Dispose all sessions created by this runtime (idempotent). */
  dispose(): void {
    for (const h of this.sessions) {
      try {
        h.dispose();
      } catch {
        // already disposed
      }
    }
    this.sessions.clear();
  }

  /** LiteLLM-proxy MCP server config (SDK_NOTES.md §4). */
  private litellmMcpConfig() {
    return {
      servers: [
        {
          name: LITELLM_PROVIDER,
          config: {
            type: "http" as const,
            url: this.litellmMcpUrl,
            headers: { Authorization: `Bearer ${this.cfg.litellm.apiKey}` },
          },
          source: "ai-kanban",
          scope: "extension" as const,
        },
      ],
      errors: [] as string[],
    };
  }
}

// ---------------------------------------------------------------------------
// Task session (Slice 3a, PLAN.md §4/§7)
// ---------------------------------------------------------------------------

/**
 * Kickoff prompt sent to the task session. The mission brief is the system
 * prompt (PLAN.md §4: "system prompt = mission brief"); this prompt starts
 * the work and defines the commit/checkpoint discipline.
 */
export const TASK_KICKOFF_PROMPT = [
  "Start executing the task described in your mission brief now.",
  "Work step by step in your working directory and commit after each meaningful step",
  '(git add -A && git commit -m "...").',
  "When the task is complete, end your turn with a short completion summary",
  "(what was done, where the result lives, what the QA gate should check) and STOP:",
  "do not re-run verification loops, re-copy files, or repeat the summary after the",
  "artifact is committed — a clean tree plus the completion summary is terminal.",
  "If a tool or model dependency is unavailable (e.g. a vision model is down), fall back",
  "to deterministic programmatic checks instead of waiting or retrying.",
].join(" ");

/** Thrown when a task run is aborted (stop/pause) — not a failure. */
export class TaskAbortedError extends Error {
  constructor(taskId: number) {
    super(`task ${taskId} run aborted`);
    this.name = "TaskAbortedError";
  }
}

/**
 * A session's LLM call failed with an API error (auth/4xx/5xx/stream error)
 * and the run produced no substantive assistant completion (item 14,
 * loud-fail hardening). The Pi SDK does not reject on API errors — it
 * encodes them as the final assistant message with stopReason "error" +
 * errorMessage (or, rarely, a rejecting prompt()); without this the failure
 * would surface as an empty completion (item 12's 403 bug: task "completes"
 * with nothing, QA gets no parseable verdict, 2 rounds burned, misleading
 * needs_attention reason). The orchestrator catches this and moves the task
 * to needs_attention with the REAL error. Abort is NOT a failure — an
 * aborted run throws TaskAbortedError instead.
 */
export class SessionApiError extends Error {
  /** HTTP status of the failed LLM call (when extractable from the error). */
  readonly status: number | undefined;
  constructor(message: string, status?: number) {
    super(message);
    this.name = "SessionApiError";
    this.status = status;
  }
}

/**
 * Shape a provider error into the loud-fail message. pi-ai's
 * formatProviderError encodes HTTP failures as "<status>: <body>" (e.g.
 * "403: The requested model 'matrix-coder' is not available for this API
 * key"); when the status is extractable the message becomes
 * "HTTP <status> — <body>", otherwise the raw message is kept.
 */
export function formatApiError(message: string): { message: string; status?: number } {
  const m = /^(\d{3})(?=$|\s|:)/.exec(message.trim());
  if (!m) return { message: message.trim() };
  const status = Number(m[1]);
  const body = message.trim().slice(3).replace(/^\s*:?\s*/, "").trim();
  return { message: body ? `HTTP ${status} — ${body}` : `HTTP ${status}`, status };
}

/**
 * Retry prompt for an empty-but-successful completion (HTTP 200, zero
 * content — the matrix-copywriter reasoning quirk): the session settled
 * without any assistant text, so ask for the completion summary (or to
 * continue the work) once before treating the run as complete.
 */
export const EMPTY_RETRY_PROMPT = [
  "Your previous turn ended without any assistant text.",
  "If the task is complete, end your turn now with the short completion summary",
  "(what was done, where the result lives, what the QA gate should check) and STOP.",
  "If more work remains, continue it now.",
].join(" ");

/**
 * Read the API error out of a message_end event, if any: the SDK surfaces a
 * failed LLM call as an assistant message with stopReason "error" +
 * errorMessage (StreamFn contract). Returns the raw errorMessage, or
 * undefined when the event is not an error-bearing assistant message.
 * (stopReason "aborted" is NOT an API error — aborts are not failures.)
 */
export function apiErrorFromEvent(event: TaskSessionEvent): string | undefined {
  if (event.type !== "message_end") return undefined;
  const m = event.message as { role?: string; stopReason?: string; errorMessage?: string } | undefined;
  if (!m || m.role !== "assistant" || m.stopReason !== "error") return undefined;
  return m.errorMessage ?? "LLM API error (no message)";
}

/**
 * Structural subset of the Pi SDK's AgentSessionEvent that the task pipeline
 * consumes for the live log tail. AgentSessionEvent is assignable to this
 * (every SDK event carries a literal `type` string; extra fields are covered
 * by the index signature).
 */
export interface TaskSessionEvent {
  type: string;
  message?: AgentMessage;
  toolName?: string;
  args?: Record<string, unknown>;
  isError?: boolean;
  durationMs?: number;
  aborted?: boolean;
  reason?: string;
  [key: string]: unknown;
}

/**
 * The subset of Pi's AgentSession the task pipeline needs. AgentSession
 * satisfies this structurally; tests provide a mock.
 */
export interface TaskSessionLike {
  /** Run one turn; resolves when the turn settles. */
  prompt(text: string): Promise<void>;
  /** Full transcript (in order). */
  readonly messages: AgentMessage[];
  /** Path of the persisted session file (if any). */
  readonly sessionFile?: string;
  /** Subscribe to session events; returns an unsubscribe function. */
  subscribe(listener: (event: TaskSessionEvent) => void): () => void;
  /** Stop the current run (best effort). */
  abort(): void;
  dispose(): void;
}

export interface TaskSessionCreateOptions {
  taskId: number;
  /** Session working directory (/workspace/task-<id>). */
  cwd: string;
  /** Mission brief (system prompt). */
  systemPrompt: string;
  /** Stable session file path (<sessions>/task-<id>.jsonl). */
  sessionFile: string;
  /** Owner (USER_KEYS name) the session's LLM calls bill to (Phase 2). */
  owner?: string;
  /** Called with usage for each completed assistant message. */
  onUsage?: (usage: UsageSample) => void;
}

export type TaskSessionFactory = (opts: TaskSessionCreateOptions) => Promise<TaskSessionLike>;

// ---------------------------------------------------------------------------
// Git operations (workspace clone / commit tracking)
// ---------------------------------------------------------------------------

/**
 * Git operations for the task workspace. The default implementation shells
 * out to `git`; tests inject a mock (PLAN.md §3: "mocked Pi sessions/git").
 */
export interface GitOps {
  /**
   * Prepare the task workspace: fresh clone of the project repo on a new
   * task branch (or a git-init scratch dir when the project has no repo).
   * With resumeCommit: re-point the task branch at that commit (resume).
   */
  prepareWorkspace(opts: {
    dest: string;
    repoUrl: string | null;
    defaultBranch: string | null;
    branch: string;
    resumeCommit: string | null;
  }): Promise<void>;
  /** Current HEAD sha, or null when the repo has no commits. */
  headCommit(dest: string): Promise<string | null>;
  /** Commit all changes; new HEAD sha, or null when there was nothing to commit. */
  commitAll(dest: string, message: string): Promise<string | null>;
  /** git merge-base <baseRef> HEAD (null when unavailable, e.g. scratch repo). */
  mergeBase(dest: string, baseRef: string): Promise<string | null>;
  /** git diff <base>..HEAD ("" when unavailable). */
  diff(dest: string, base: string): Promise<string>;
}

export interface GitOpsOptions {
  /** Auth token for https clones (GITHUB_TOKEN). */
  token?: string | null;
  /** Commit identity (defaults to ai-kanban <ai-kanban@local>). */
  userName?: string;
  userEmail?: string;
}

/** https://github.com/... → https://x-access-token:<token>@github.com/... */
function authedRepoUrl(url: string, token: string | null | undefined): string {
  if (!token) return url;
  try {
    const u = new URL(url);
    if (u.protocol === "https:") {
      u.username = "x-access-token";
      u.password = token;
      return u.toString();
    }
  } catch {
    // not a URL — use as-is
  }
  return url;
}

/** Default GitOps: shell out to `git` (execFile, no shell). */
export function createGitOps(opts: GitOpsOptions = {}): GitOps {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    GIT_AUTHOR_NAME: opts.userName ?? "ai-kanban",
    GIT_AUTHOR_EMAIL: opts.userEmail ?? "ai-kanban@local",
    GIT_COMMITTER_NAME: opts.userName ?? "ai-kanban",
    GIT_COMMITTER_EMAIL: opts.userEmail ?? "ai-kanban@local",
  };
  const run = async (cwd: string, args: string[]): Promise<string> => {
    const { stdout } = await pExecFile("git", args, {
      cwd,
      env,
      timeout: 300_000,
      maxBuffer: 10 * 1024 * 1024,
    });
    return stdout.trim();
  };
  return {
    async prepareWorkspace({ dest, repoUrl, defaultBranch, branch, resumeCommit }) {
      if (existsSync(path.join(dest, ".git"))) {
        // Existing workspace (resume): re-point the task branch.
        if (resumeCommit) await run(dest, ["checkout", "-B", branch, resumeCommit]);
        else await run(dest, ["checkout", branch]);
        return;
      }
      rmSync(dest, { recursive: true, force: true });
      mkdirSync(path.dirname(dest), { recursive: true });
      if (repoUrl) {
        const url = authedRepoUrl(repoUrl, opts.token);
        await run(
          path.dirname(dest),
          defaultBranch
            ? ["clone", "--branch", defaultBranch, "--single-branch", url, dest]
            : ["clone", url, dest],
        );
        await run(dest, ["checkout", "-b", branch]);
      } else {
        mkdirSync(dest, { recursive: true });
        await run(dest, ["init", "-q"]);
        await run(dest, ["checkout", "-b", branch]);
      }
    },
    async headCommit(dest) {
      try {
        return await run(dest, ["rev-parse", "HEAD"]);
      } catch {
        return null; // not a repo yet, or no commits
      }
    },
    async mergeBase(dest, baseRef) {
      try {
        return await run(dest, ["merge-base", baseRef, "HEAD"]);
      } catch {
        return null; // scratch repo / no common base
      }
    },
    async diff(dest, base) {
      try {
        return await run(dest, ["diff", `${base}..HEAD`]);
      } catch {
        return "";
      }
    },
    async commitAll(dest, message) {
      await run(dest, ["add", "-A"]);
      try {
        await run(dest, ["commit", "-m", message]);
      } catch (err) {
        const out = (err as { stdout?: string }).stdout ?? "";
        if (/nothing to commit/i.test(out)) return null;
        throw err;
      }
      return run(dest, ["rev-parse", "HEAD"]);
    },
  };
}

// ---------------------------------------------------------------------------
// Mission brief (PLAN.md §4/§7: persisted per task, re-injected on resume)
// ---------------------------------------------------------------------------

/** One completed dependency task (what it produced, for the mission brief). */
export interface TaskDepContext {
  ideaId: number;
  text: string;
  branch: string | null;
  lastCommit: string | null;
  /** Completion summary of the dependency task's run. */
  summary: string | null;
}

/** Everything the task session needs to know (project + task + context). */
export interface TaskRunContext {
  taskId: number;
  projectId: number;
  /** Idea text (1:1 with the task). */
  ideaText: string;
  spec: IdeaSpec;
  /** Dep ideas that have done tasks (what they produced). */
  deps: TaskDepContext[];
  /** Accepted resolution plan (Needs Attention → Backlog), if any. */
  resolution: string | null;
  /** Rolling progress summary from a previous run (resume), if any. */
  progressSummary: string | null;
  /** Project fields for the brief. */
  project: {
    name: string;
    goal: string;
    repoUrl: string | null;
    defaultBranch: string | null;
    blogRepoUrl: string | null;
    blogContentPath: string | null;
    mediaPaths: string[] | null;
    constraints: string | null;
    architectureNotes: string | null;
    notes: string | null;
    stateSummary: string | null;
  };
  /** Resume from this commit (checkout instead of a fresh clone). */
  resumeCommit: string | null;
  /**
   * Owner (inherited from the idea at task creation) whose key the session's
   * LLM calls bill to (Phase 2); '' → the service key.
   */
  owner: string;
  /**
   * Custom kickoff prompt (e.g. QA feedback on a re-run after a failed QA
   * round). Defaults to TASK_KICKOFF_PROMPT.
   */
  prompt?: string;
  /** Live log tail sink (task_events `log`). */
  onLog?: (line: string) => void;
  /** New commit detected (task_events `heartbeat` + tasks.last_commit). */
  onCommit?: (commit: string) => void;
  /** Usage sink (usage table, role `task`). */
  onUsage?: (usage: UsageSample) => void;
}

export interface TaskRunResult {
  /** Completion summary (last assistant message text). */
  summary: string;
  /** Final HEAD sha after the run (null when the repo has no commits). */
  lastCommit: string | null;
}

/**
 * Build the mission brief (PLAN.md §4): project spec + task spec + rolling
 * progress summary + what completed dependency tasks produced + accepted
 * resolution plan (if any). Persisted under /data per task.
 */
export function buildMissionBrief(ctx: TaskRunContext, workspace: string): string {
  const p = ctx.project;
  const lines: string[] = [];
  lines.push(`# Mission brief — task ${ctx.taskId}`);
  lines.push("");
  lines.push("You are the execution agent for ai-kanban, an LLM task board.");
  lines.push(`Working directory: ${workspace} (branch task/${ctx.taskId}).`);
  lines.push("Commit after each meaningful step (git add -A && git commit).");
  lines.push("When the task is complete, end your turn with a short completion summary.");
  lines.push("");
  lines.push(`## Project: ${p.name}`);
  if (p.goal) lines.push(`Goal: ${p.goal}`);
  if (p.repoUrl) lines.push(`Repo: ${p.repoUrl}${p.defaultBranch ? ` (branch ${p.defaultBranch})` : ""}`);
  if (p.blogRepoUrl) lines.push(`Blog: ${p.blogRepoUrl}${p.blogContentPath ? ` → ${p.blogContentPath}` : ""}`);
  if (p.mediaPaths && p.mediaPaths.length > 0) lines.push(`Media paths: ${p.mediaPaths.join(", ")}`);
  if (p.constraints) lines.push(`Constraints (never do these): ${p.constraints}`);
  if (p.architectureNotes) lines.push(`Architecture notes: ${p.architectureNotes}`);
  if (p.notes) lines.push(`Notes: ${p.notes}`);
  if (p.stateSummary) lines.push(`Current project state: ${p.stateSummary}`);
  lines.push("");
  lines.push("## Task");
  lines.push(`Idea: ${ctx.ideaText}`);
  // The spec is JSON from the DB — treat every field as runtime-untrusted
  // (a task can carry a minimal spec, e.g. {goal} only): never crash the
  // session pipeline on a missing field, degrade to a placeholder instead.
  const steps = Array.isArray(ctx.spec.steps) ? ctx.spec.steps : [];
  const acceptance = Array.isArray(ctx.spec.acceptance) ? ctx.spec.acceptance : [];
  lines.push(`Goal: ${ctx.spec.goal ?? "(not specified — derive it from the idea text and project context)"}`);
  if (steps.length > 0) {
    lines.push("Steps:");
    steps.forEach((s, i) => lines.push(`${i + 1}. ${s}`));
  }
  if (acceptance.length > 0) {
    lines.push("Acceptance criteria:");
    acceptance.forEach((a) => lines.push(`- ${a}`));
  }
  lines.push(`Kind: ${ctx.spec.kind ?? "(unspecified — treat as general code work)"}`);
  if (Array.isArray(ctx.spec.publish_targets) && ctx.spec.publish_targets.length > 0) {
    lines.push(`Publish targets: ${ctx.spec.publish_targets.join(", ")}`);
  }
  if (ctx.spec.notes) lines.push(`Notes: ${ctx.spec.notes}`);
  lines.push("");
  const publish = publishingInstructions(ctx, workspace);
  if (publish) {
    lines.push("## Publishing");
    lines.push(publish);
    lines.push("");
  }
  lines.push("## Progress so far");
  lines.push(ctx.progressSummary ?? "(fresh start — no previous progress)");
  lines.push("");
  lines.push("## Completed dependency tasks (build on their output)");
  if (ctx.deps.length > 0) {
    for (const d of ctx.deps) {
      lines.push(`- ${d.text}: branch ${d.branch ?? "?"}${d.lastCommit ? `, last commit ${d.lastCommit}` : ""}`);
      if (d.summary) lines.push(`  produced: ${d.summary}`);
    }
  } else {
    lines.push("(none)");
  }
  if (ctx.resolution) {
    lines.push("");
    lines.push("## Accepted resolution plan (follow it)");
    lines.push(ctx.resolution);
  }
  return lines.join("\n");
}

/**
 * Kind-specific publishing instructions (Slice 3b): where the agent puts its
 * output so the Deploy stage can find it (code → branch push; blog →
 * post.md; media → media/ dir).
 */
function publishingInstructions(ctx: TaskRunContext, workspace: string): string | null {
  const p = ctx.project;
  switch (ctx.spec.kind) {
    case "code":
      return p.repoUrl
        ? "After QA passes, the task branch is committed and pushed to GitHub (no PRs). Nothing else to do."
        : null;
    case "blog":
      return [
        `Write the post as ONE markdown file at ${workspace}/post.md (or the first Publish target, if given).`,
        `After QA passes it is published to the blog repo at ${p.blogContentPath ?? "<blog_content_path>"}/<date>-<slug>.md.`,
      ].join(" ");
    case "media":
      return [
        `Place the final media files under ${workspace}/media/ (this directory is published).`,
        `After QA passes they are published to the blog repo's public directory (${ctx.spec.publish_targets?.[0] ?? p.mediaPaths?.[0] ?? "media_paths"}).`,
      ].join(" ");
    default:
      return null;
  }
}

/** Compact one-line JSON for tool args (log tail). */
function compactArgs(args: Record<string, unknown> | undefined): string {
  if (!args) return "";
  try {
    const s = JSON.stringify(args);
    return s.length > 120 ? `${s.slice(0, 119)}…` : s;
  } catch {
    return "";
  }
}

/**
 * Map one session event to a live-log line (task_events `log`), or null when
 * the event is not log-worthy (user messages, streaming deltas, ...).
 */
export function formatTaskLogLine(event: TaskSessionEvent): string | null {
  switch (event.type) {
    case "tool_execution_start": {
      const args = compactArgs(event.args);
      return `[tool] ${event.toolName ?? "tool"}${args ? `: ${args}` : ""}`;
    }
    case "tool_execution_end": {
      const dur = event.durationMs !== undefined ? ` in ${event.durationMs}ms` : "";
      return event.isError
        ? `[tool] ${event.toolName ?? "tool"} failed${dur}`
        : `[tool] ${event.toolName ?? "tool"} done${dur}`;
    }
    case "message_end": {
      const m = event.message;
      if (!m || m.role !== "assistant") return null;
      const text = extractMessageText(m).trim();
      if (text === "") return null;
      const oneLine = text.replace(/\s+/g, " ");
      return `[agent] ${oneLine.length > 200 ? `${oneLine.slice(0, 199)}…` : oneLine}`;
    }
    case "compaction_start":
      return `[compact] context compacted (${event.reason ?? "manual"})`;
    case "agent_settled":
      return event.aborted ? "[session] turn aborted" : null;
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Task session runner
// ---------------------------------------------------------------------------

/**
 * The task execution pipeline the orchestrator drives: prepare the workspace
 * (fresh clone, branch task/<id>), run the Pi task session (TASK_THINKING),
 * track commits + live log + usage, return the completion summary.
 */
export interface TaskRunner {
  run(ctx: TaskRunContext): Promise<TaskRunResult>;
  /** Abort the in-flight run for a task (no-op when not running). */
  abort(taskId: number): void;
}

export interface TaskSessionRunnerOptions {
  /** Create the Pi session (role `task`, TASK_THINKING). Tests inject a mock. */
  sessionFactory?: TaskSessionFactory;
  /** Agent runtime (required when sessionFactory is not given). */
  agent?: AgentRuntime;
  /** Git operations (default: real git via execFile). */
  git?: GitOps;
  /** Workspace root (default: AI_KANBAN_WORKSPACE_DIR env, else /workspace). */
  workspaceRoot?: string;
  /** Session file dir (default: the agent runtime's sessions dir). */
  sessionsDir?: string;
  /** Mission brief dir (default: <dataDir>/missions). */
  missionsDir?: string;
  /** GITHUB_TOKEN for authenticated clones. */
  token?: string | null;
}

export class TaskSessionRunner implements TaskRunner {
  readonly workspaceRoot: string;
  readonly sessionsDir: string;
  readonly missionsDir: string;

  private readonly factory: TaskSessionFactory;
  private readonly git: GitOps;
  /** In-flight runs, per task (for abort). */
  private readonly active = new Map<number, { session: TaskSessionLike; aborted: boolean }>();

  constructor(opts: TaskSessionRunnerOptions) {
    if (opts.sessionFactory) {
      this.factory = opts.sessionFactory;
      const dataDir = process.env.AI_KANBAN_DATA_DIR ?? "/data";
      this.sessionsDir = opts.sessionsDir ?? path.join(dataDir, "sessions");
      this.missionsDir = opts.missionsDir ?? path.join(dataDir, "missions");
    } else if (opts.agent) {
      const agent = opts.agent;
      this.factory = (o) =>
        agent
          .createSession({
            role: "task",
            cwd: o.cwd,
            systemPrompt: o.systemPrompt,
            sessionFile: o.sessionFile, // SessionManager.open semantics (stable path)
            owner: o.owner, // Phase 2: bill to the task owner's key (else service key)
            onUsage: o.onUsage,
          })
          .then((h) => h.session as unknown as TaskSessionLike);
      this.sessionsDir = opts.sessionsDir ?? agent.sessionsDir;
      this.missionsDir = opts.missionsDir ?? path.join(agent.dataDir, "missions");
    } else {
      throw new Error("TaskSessionRunner needs a sessionFactory or an AgentRuntime");
    }
    this.workspaceRoot = opts.workspaceRoot ?? process.env.AI_KANBAN_WORKSPACE_DIR ?? "/workspace";
    this.git = opts.git ?? createGitOps({ token: opts.token });
  }

  /** Task workspace dir (/workspace/task-<id>). */
  workspacePath(taskId: number): string {
    return path.join(this.workspaceRoot, `task-${taskId}`);
  }

  /** Stable persisted session file (<sessions>/task-<id>.jsonl). */
  sessionFile(taskId: number): string {
    return path.join(this.sessionsDir, `task-${taskId}.jsonl`);
  }

  /**
   * Run the task session end-to-end (PLAN.md §4 "Run"):
   *   1. prepare the workspace (fresh clone / resume checkout),
   *   2. build + persist the mission brief (system prompt),
   *   3. run the Pi session (TASK_THINKING) with the kickoff prompt,
   *   4. track commits (heartbeat) + live log tail + usage,
   *   5. checkpoint any uncommitted work, return the completion summary.
   * Throws TaskAbortedError when the run was aborted (stop/pause) — abort is
   * not a failure. Throws SessionApiError when the run's LLM calls failed
   * with an API error (auth/4xx/5xx/stream) and produced no substantive
   * assistant completion (item 14 loud-fail); an empty-but-successful
   * completion (HTTP 200, zero content) retries the prompt ONCE before
   * completing (model behavior, not an API failure).
   */
  async run(ctx: TaskRunContext): Promise<TaskRunResult> {
    const workspace = this.workspacePath(ctx.taskId);
    const branch = `task/${ctx.taskId}`;
    await this.git.prepareWorkspace({
      dest: workspace,
      repoUrl: ctx.project.repoUrl,
      defaultBranch: ctx.project.defaultBranch,
      branch,
      resumeCommit: ctx.resumeCommit,
    });

    const missionBrief = buildMissionBrief(ctx, workspace);
    // Persist the mission brief (PLAN.md §7: persisted in /data per task).
    mkdirSync(this.missionsDir, { recursive: true });
    writeFileSync(path.join(this.missionsDir, `task-${ctx.taskId}.md`), missionBrief + "\n");

    const session = await this.factory({
      taskId: ctx.taskId,
      cwd: workspace,
      systemPrompt: missionBrief,
      sessionFile: this.sessionFile(ctx.taskId),
      owner: ctx.owner, // Phase 2: bill to the task owner's key (else service key)
      onUsage: ctx.onUsage,
    });
    const entry = { session, aborted: false };
    this.active.set(ctx.taskId, entry);
    /** First API error seen during the run (item 14 loud-fail). */
    let firstApiError: string | undefined;

    // Commit tracking: the agent commits after each meaningful step; we
    // detect new HEADs after tool results / assistant messages.
    let lastHead = await this.git.headCommit(workspace).catch(() => null);
    let headChain: Promise<void> = Promise.resolve();
    const scheduleHeadCheck = () => {
      headChain = headChain
        .then(async () => {
          const head = await this.git.headCommit(workspace);
          if (head && head !== lastHead) {
            lastHead = head;
            ctx.onCommit?.(head);
          }
        })
        .catch(() => undefined);
    };

    const unsubscribe = session.subscribe((event) => {
      const line = formatTaskLogLine(event);
      if (line) ctx.onLog?.(line);
      // Loud-fail tracking (item 14): an API error surfaces as an assistant
      // message with stopReason "error" + errorMessage; remember the first
      // one so the run can fail loudly instead of completing empty.
      const apiError = apiErrorFromEvent(event);
      if (apiError) firstApiError ??= apiError;
      if (event.type === "tool_execution_end" || event.type === "message_end") scheduleHeadCheck();
    });

    try {
      let summary: string | undefined;
      try {
        await session.prompt(ctx.prompt ?? TASK_KICKOFF_PROMPT);
      } catch (err) {
        if (!entry.aborted) {
          // prompt() rejected (stream/runtime failure) — loud-fail too.
          const f = formatApiError(err instanceof Error ? err.message : String(err));
          ctx.onLog?.(`[session] LLM API error — failing loudly: ${f.message}`);
          throw new SessionApiError(f.message, f.status);
        }
        // Aborted mid-prompt: the rejection is the abort surfacing —
        // TaskAbortedError is thrown below (abort is not a failure).
      }
      if (!entry.aborted) {
        // Loud-fail + empty-completion handling (item 14): after the run
        // settles, distinguish an API error (fail loudly) from an
        // empty-but-successful completion (retry once, then complete).
        summary = lastAssistantText(session.messages);
        if (summary === undefined) {
          if (firstApiError) {
            const f = formatApiError(firstApiError);
            ctx.onLog?.(`[session] LLM API error with no assistant completion — failing loudly: ${f.message}`);
            throw new SessionApiError(f.message, f.status);
          }
          // Empty-but-successful (HTTP 200, zero content — the
          // matrix-copywriter reasoning quirk): retry the prompt ONCE before
          // treating the run as complete.
          ctx.onLog?.("[session] empty completion (HTTP 200, no content) — retrying the prompt once");
          try {
            await session.prompt(EMPTY_RETRY_PROMPT);
          } catch (err) {
            if (!entry.aborted) {
              // prompt() rejected (stream/runtime failure) — loud-fail too.
              const f = formatApiError(err instanceof Error ? err.message : String(err));
              ctx.onLog?.(`[session] LLM API error — failing loudly: ${f.message}`);
              throw new SessionApiError(f.message, f.status);
            }
            // Aborted during the retry: TaskAbortedError is thrown below
            // (abort is not a failure).
          }
          if (!entry.aborted) {
            summary = lastAssistantText(session.messages);
            if (summary === undefined) {
              if (firstApiError) {
                // The retry's LLM call failed with an API error (the SDK
                // resolves with an error-bearing assistant message) — fail
                // loudly with the REAL error, not a silent empty completion.
                const f = formatApiError(firstApiError);
                ctx.onLog?.(
                  `[session] LLM API error with no assistant completion — failing loudly: ${f.message}`,
                );
                throw new SessionApiError(f.message, f.status);
              }
              ctx.onLog?.(
                "[session] retry also empty — completing with no summary (model behavior, not an API failure)",
              );
            }
          }
        }
      }
      await headChain; // settle in-flight commit checks
      // Safety net: checkpoint any uncommitted work (git is the source of truth).
      const committed = await this.git.commitAll(workspace, `task ${ctx.taskId}: checkpoint after run`).catch(() => null);
      if (committed && committed !== lastHead) {
        lastHead = committed;
        ctx.onCommit?.(committed);
      }
      const head = await this.git.headCommit(workspace).catch(() => null);
      if (head) lastHead = head;
      if (entry.aborted) throw new TaskAbortedError(ctx.taskId);
      return { summary: summary ?? "(no completion summary)", lastCommit: lastHead };
    } finally {
      unsubscribe();
      this.active.delete(ctx.taskId);
      session.dispose();
    }
  }

  /** Abort the in-flight run for a task (stop/pause; no-op when not running). */
  abort(taskId: number): void {
    const entry = this.active.get(taskId);
    if (!entry) return;
    entry.aborted = true;
    try {
      entry.session.abort();
    } catch {
      // best effort — the run settles on its own
    }
  }
}
