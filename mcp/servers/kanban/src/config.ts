/**
 * Configuration: .env parsing, defaults, and startup validation.
 *
 * Every variable is documented in draft_ai_kanban_requirements.md §4 and
 * mirrored in .env.example. Fail-fast policy: missing/invalid configuration —
 * and a MODEL that the LiteLLM proxy does not serve — aborts startup with a
 * clear error (PLAN.md §1: "Startup validation").
 */
import { readFile } from "node:fs/promises";
import { z } from "zod";

/** Pi thinking levels (from @earendil-works/pi-agent-core). */
export type ThinkingLevel =
  | "off"
  | "minimal"
  | "low"
  | "medium"
  | "high"
  | "xhigh"
  | "max";

const THINKING_LEVELS: readonly ThinkingLevel[] = [
  "off",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
] as const;

const thinkingLevel = z.enum(THINKING_LEVELS);

/** SQLite location inside the persistent /data volume (PLAN.md §2).
 * Overridable via the SQLITE_PATH env var for local dev (default: /data/kanban.db). */
export const SQLITE_PATH = "/data/kanban.db";

export const DEFAULTS = {
  DB_DRIVER: "sqlite",
  SQLITE_PATH: "/data/kanban.db",
  MYSQL_PORT: "3306",
  HOST_WORKSPACE_PATH: "/home/chuck/workspace",
  WORKSPACE_DIR: "/workspace",
  HARNESS_REPO_URL: "https://github.com/choukalos/homelab-ai-harness",
  HARNESS_SKILLS_PATH: "agents-skills",
  GROOM_THINKING: "xhigh",
  TASK_THINKING: "medium",
  QA_THINKING: "xhigh",
  SUMMARY_THINKING: "medium",
  MEDIA_CONCURRENT_TASKS: "1",
  NON_MEDIA_CONCURRENT_TASKS: "2",
  AGENT_CONCURRENT_TASKS: "1",
  AGENT_SLUGS: "",
  BIND_ADDR: "0.0.0.0",
  PORT: "3000",
} as const;

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

/** Optional non-empty string: empty/whitespace values are treated as unset. */
function optionalNonEmpty() {
  return z.preprocess(
    (v) => (typeof v === "string" && v.trim() === "" ? undefined : v),
    z.string().min(1).optional(),
  );
}

const envSchema = z
  .object({
    // LiteLLM proxy (models + MCP tools)
    LITELLM_BASE_URL: z
      .url("LITELLM_BASE_URL is required and must be a valid URL (LiteLLM proxy endpoint)")
      .describe("LiteLLM proxy endpoint (OpenAI-compatible, e.g. https://llm.example.com/v1)"),
    LITELLM_API_KEY: z
      .string()
      .min(1, "LITELLM_API_KEY is required (kanban-user access key)")
      .describe("kanban-user access key for models + MCP tools"),
    MODEL: z
      .string()
      .min(1, "MODEL is required (model ID in the LiteLLM config; validated at startup)")
      .describe("model ID in the LiteLLM config"),
    GITHUB_TOKEN: optionalNonEmpty().describe("git push auth (deploy stage)"),

    // Per-user LLM spend attribution (Phase 2): name=full-key pairs, or
    // name=ENV_VAR_NAME references resolved at boot (Phase 13.5 — the
    // container carries the full .env via env_file, so USER_KEYS can be
    // derived from MEMORY_USER_KEYS, the homelab-wide identity map).
    USER_KEYS: z
      .string()
      .optional()
      .describe(
        "per-user spend attribution: comma-separated name=full-LiteLLM-key pairs " +
          "(e.g. chuck=sk-...,dylan=sk-...), or name=ENV_VAR_NAME references " +
          "resolved from the container environment at boot (e.g. " +
          "chuck=LITELLM_KEY_CHUCK); sessions for work owned by a user run " +
          "against the proxy with that user's key",
      ),

    // Database
    DB_DRIVER: z
      .enum(["sqlite", "mysql"])
      .default(DEFAULTS.DB_DRIVER)
      .describe("sqlite (default) or mysql"),
    SQLITE_PATH: z
      .string()
      .min(1)
      .default(DEFAULTS.SQLITE_PATH)
      .describe("sqlite file location (default /data/kanban.db; override for local dev)"),
    MYSQL_HOST: optionalNonEmpty(),
    MYSQL_PORT: z.coerce
      .number()
      .int("MYSQL_PORT must be an integer")
      .min(1)
      .max(65535)
      .default(3306),
    MYSQL_USER: optionalNonEmpty(),
    MYSQL_PASSWORD: optionalNonEmpty(),
    MYSQL_DATABASE: optionalNonEmpty(),

    // Volumes / workspace
    HOST_WORKSPACE_PATH: z
      .string()
      .min(1)
      .default(DEFAULTS.HOST_WORKSPACE_PATH)
      .describe("host path mounted read-write at /workspace (compose mount source; informational for the app)"),
    AI_KANBAN_WORKSPACE_DIR: z
      .string()
      .min(1)
      .default(DEFAULTS.WORKSPACE_DIR)
      .describe("app-side agent workspace root (task-<id> + groom-<id> dirs); /workspace in the container, override for local dev"),

    // Agent skills (homelab-ai-harness)
    HARNESS_REPO_URL: z
      .string()
      .min(1)
      .default(DEFAULTS.HARNESS_REPO_URL)
      .describe("git URL of the homelab-ai-harness repo"),
    HARNESS_SKILLS_PATH: z
      .string()
      .min(1)
      .default(DEFAULTS.HARNESS_SKILLS_PATH)
      .describe("path within the harness repo where skills live"),

    // Per-role thinking levels
    GROOM_THINKING: thinkingLevel.default(DEFAULTS.GROOM_THINKING),
    TASK_THINKING: thinkingLevel.default(DEFAULTS.TASK_THINKING),
    QA_THINKING: thinkingLevel.default(DEFAULTS.QA_THINKING),
    SUMMARY_THINKING: thinkingLevel.default(DEFAULTS.SUMMARY_THINKING),

    // Orchestrator / server — per-category task slots: media-kind tasks
    // (spec.kind === "media") are GPU-heavy and serialized (1); everything
    // else (code/blog/other) runs up to 2 in parallel.
    MEDIA_CONCURRENT_TASKS: z.coerce
      .number()
      .int("MEDIA_CONCURRENT_TASKS must be an integer")
      .min(1, "MEDIA_CONCURRENT_TASKS must be >= 1")
      .default(1)
      .describe("max media-kind tasks running at once"),
    NON_MEDIA_CONCURRENT_TASKS: z.coerce
      .number()
      .int("NON_MEDIA_CONCURRENT_TASKS must be an integer")
      .min(1, "NON_MEDIA_CONCURRENT_TASKS must be >= 1")
      .default(2)
      .describe("max non-media tasks running at once"),
    AGENT_CONCURRENT_TASKS: z.coerce
      .number()
      .int("AGENT_CONCURRENT_TASKS must be an integer")
      .min(1, "AGENT_CONCURRENT_TASKS must be >= 1")
      .default(1)
      .describe("max standing-agent tasks running at once (owner in AGENT_SLUGS)"),
    AGENT_SLUGS: optionalNonEmpty().describe(
      "comma-separated standing-agent slugs; cards owned by one of them count " +
        "against AGENT_CONCURRENT_TASKS regardless of work kind (unset/empty = " +
        "no agent slot in use)",
    ),
    KANBAN_OWNER_MODELS: optionalNonEmpty().describe(
      "per-owner pipeline models (item 15): comma-separated alias:model pairs " +
        "(e.g. strategist:matrix-copywriter,marketing:matrix-copywriter); all " +
        "sessions for a task owned by a mapped alias (task work + QA + retries) " +
        "run on that model, billed to the owner's USER_KEYS key (absent/empty = " +
        "every session on MODEL)",
    ),
    WORKSPACE_CLEANUP_DAYS: z.coerce
      .number()
      .int("WORKSPACE_CLEANUP_DAYS must be an integer")
      .min(1, "WORKSPACE_CLEANUP_DAYS must be >= 1")
      .default(7)
      .describe("age before /workspace/task-<id> + groom-<id> scratch dirs are swept (transitory — durable results are pushed/published)"),
    BIND_ADDR: z.string().min(1).default(DEFAULTS.BIND_ADDR),
    PORT: z.coerce
      .number()
      .int("PORT must be an integer")
      .min(1)
      .max(65535)
      .default(3000),
  })
  .superRefine((v, ctx) => {
    if (v.DB_DRIVER === "mysql") {
      for (const key of ["MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"] as const) {
        if (!v[key]) {
          ctx.addIssue({
            code: "custom",
            path: [key],
            message: `${key} is required when DB_DRIVER=mysql`,
          });
        }
      }
    }
  });

export interface KanbanConfig {
  litellm: { baseUrl: string; apiKey: string };
  model: string;
  /** Catalog rates in $/M tokens from the proxy's /model/info (undefined → $0 cost estimates). */
  modelCost: ModelCostRates | undefined;
  githubToken: string | undefined;
  /**
   * Per-user LLM spend attribution (Phase 2): owner name → full LiteLLM key.
   * Sessions for work owned by a user run against the proxy with that user's
   * key (LiteLLM bills spend to the user's key/budget). Empty = all work
   * bills to the service key (LITELLM_API_KEY).
   */
  userKeys: Record<string, string>;
  db: {
    driver: "sqlite" | "mysql";
    sqlitePath: string;
    mysql: {
      host: string;
      port: number;
      user: string;
      password: string;
      database: string;
    } | undefined;
  };
  workspace: { hostPath: string; dir: string };
  harness: { repoUrl: string; skillsPath: string };
  thinking: {
    groom: ThinkingLevel;
    task: ThinkingLevel;
    qa: ThinkingLevel;
    summary: ThinkingLevel;
  };
  /** Max media-kind tasks (spec.kind === "media") running at once. */
  mediaConcurrentTasks: number;
  /** Max non-media tasks running at once. */
  nonMediaConcurrentTasks: number;
  /** Max standing-agent tasks (owner in agentSlugs) running at once. */
  agentConcurrentTasks: number;
  /** Standing-agent slugs (cards owned by one of them count against the agent slot). */
  agentSlugs: string[];
  /**
   * Per-owner pipeline model map (KANBAN_OWNER_MODELS, item 15): owner alias →
   * model. All sessions for a task owned by a mapped alias (task work + QA +
   * retries) run on that model, billed to the owner's key; empty = every
   * session on `model`.
   */
  ownerModels: Record<string, string>;
  /**
   * Cost rates per mapped model (from /model/info at boot, keyed by model
   * name; undefined = $0 cost estimates, like the pipeline model's fallback).
   */
  ownerModelCosts: Record<string, ModelCostRates | undefined>;
  /** Age (days) before workspace scratch dirs are swept (default 7). */
  workspaceCleanupDays: number;
  server: { bindAddr: string; port: number };
}

function formatZodError(error: z.ZodError): string {
  const lines = error.issues.map(
    (issue) => `  - ${issue.path.join(".") || "(env)"}: ${issue.message}`,
  );
  return `invalid configuration:\n${lines.join("\n")}`;
}

/**
 * Parse + validate the environment (defaults applied, no network access).
 * @param env environment map; defaults to process.env
 */
export function parseConfig(
  env: Record<string, string | undefined> = process.env,
): KanbanConfig {
  const parsed = envSchema.safeParse(env);
  if (!parsed.success) throw new ConfigError(formatZodError(parsed.error));
  const v = parsed.data;
  return {
    litellm: {
      baseUrl: v.LITELLM_BASE_URL.replace(/\/+$/, ""),
      apiKey: v.LITELLM_API_KEY,
    },
    model: v.MODEL,
    modelCost: undefined, // populated by loadConfig from the proxy's /model/info
    githubToken: v.GITHUB_TOKEN,
    userKeys: parseUserKeys(v.USER_KEYS),
    db: {
      driver: v.DB_DRIVER,
      sqlitePath: v.SQLITE_PATH,
      mysql:
        v.DB_DRIVER === "mysql"
          ? {
              host: v.MYSQL_HOST!,
              port: v.MYSQL_PORT,
              user: v.MYSQL_USER!,
              password: v.MYSQL_PASSWORD!,
              database: v.MYSQL_DATABASE!,
            }
          : undefined,
    },
    workspace: { hostPath: v.HOST_WORKSPACE_PATH, dir: v.AI_KANBAN_WORKSPACE_DIR },
    harness: { repoUrl: v.HARNESS_REPO_URL, skillsPath: v.HARNESS_SKILLS_PATH },
    thinking: {
      groom: v.GROOM_THINKING,
      task: v.TASK_THINKING,
      qa: v.QA_THINKING,
      summary: v.SUMMARY_THINKING,
    },
    mediaConcurrentTasks: v.MEDIA_CONCURRENT_TASKS,
    nonMediaConcurrentTasks: v.NON_MEDIA_CONCURRENT_TASKS,
    agentConcurrentTasks: v.AGENT_CONCURRENT_TASKS,
    agentSlugs: parseAgentSlugs(v.AGENT_SLUGS),
    ownerModels: parseOwnerModels(v.KANBAN_OWNER_MODELS),
    ownerModelCosts: {}, // populated by loadConfig from /model/info
    workspaceCleanupDays: v.WORKSPACE_CLEANUP_DAYS,
    server: { bindAddr: v.BIND_ADDR, port: v.PORT },
  };
}

const ENV_LINE_RE = /^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/;

/**
 * Parse USER_KEYS (`name=full-key,name2=full-key2`, comma-separated).
 * Names are trimmed, must be non-empty and unique; keys must be non-empty.
 * Malformed entries throw a ConfigError (fail fast, PLAN.md §1).
 *
 * Phase 13.5: a key value that looks like an env-var name (`^[A-Z_][A-Z0-9_]*$`)
 * is resolved from the container environment at boot. This lets USER_KEYS be
 * derived from MEMORY_USER_KEYS (the homelab-wide identity map, whose values
 * are env-var NAMES, not literal keys) — single source of truth, and agent
 * stand-up (`key add-agent`) needs no per-agent compose edit. Literal keys
 * never match the pattern (they start with `sk-`), so both forms coexist.
 * An unset/empty referenced var throws (fail fast, consistent with the rest
 * of this parser).
 */
export function parseUserKeys(value: string | undefined): Record<string, string> {
  if (!value || value.trim() === "") return {};
  const out: Record<string, string> = {};
  for (const part of value.split(",")) {
    const entry = part.trim();
    if (entry === "") continue;
    const eq = entry.indexOf("=");
    if (eq <= 0) {
      throw new ConfigError(`USER_KEYS entry ${JSON.stringify(entry)} is malformed (expected name=full-key or name=ENV_VAR_NAME)`);
    }
    const name = entry.slice(0, eq).trim();
    let key = entry.slice(eq + 1).trim();
    if (name === "") throw new ConfigError(`USER_KEYS entry ${JSON.stringify(entry)} has an empty name`);
    if (key === "") throw new ConfigError(`USER_KEYS entry ${JSON.stringify(entry)} has an empty key`);
    if (/^[A-Z_][A-Z0-9_]*$/.test(key)) {
      const rawRef = key;
      const resolved = process.env[rawRef];
      if (!resolved || resolved.trim() === "") {
        throw new ConfigError(`USER_KEYS entry ${JSON.stringify(entry)} references env var ${rawRef}, which is unset or empty`);
      }
      key = resolved;
      // The shared identity map (MEMORY_USER_KEYS) may carry non-LiteLLM
      // credentials (e.g. the siri service token). LiteLLM keys always
      // start with 'sk-'; a resolved reference that isn't one can't
      // authenticate to the proxy or be billed — skip it with a warning
      // instead of failing startup. Literal values keep the fail-fast path
      // (accepted here, rejected by validateUserKeysAtBoot if the proxy
      // doesn't serve them).
      if (!key.startsWith("sk-")) {
        console.warn(`[config] USER_KEYS entry ${JSON.stringify(name)} (env ref ${rawRef}) is not a LiteLLM key — skipped`);
        continue;
      }
    }
    if (name in out) throw new ConfigError(`USER_KEYS has duplicate name ${JSON.stringify(name)}`);
    out[name] = key;
  }
  return out;
}

/**
 * Parse AGENT_SLUGS (`slug1,slug2`, comma-separated). Slugs are trimmed, must
 * be non-empty and unique. Malformed entries throw a ConfigError (fail fast,
 * PLAN.md §1). Empty/unset → [] (no standing agents; the agent slot is inert).
 */
export function parseAgentSlugs(value: string | undefined): string[] {
  if (!value || value.trim() === "") return [];
  const out: string[] = [];
  for (const part of value.split(",")) {
    const slug = part.trim();
    if (slug === "") continue;
    if (out.includes(slug)) {
      throw new ConfigError(`AGENT_SLUGS has duplicate slug ${JSON.stringify(slug)}`);
    }
    out.push(slug);
  }
  return out;
}

/**
 * Parse KANBAN_OWNER_MODELS (`alias:model,alias2:model2`, comma-separated,
 * item 15). Aliases and models are trimmed and must be non-empty; duplicate
 * aliases throw a ConfigError (fail fast, PLAN.md §1 — a typo'd map must not
 * silently re-route an owner's sessions). Empty/unset → {} (every session
 * runs on MODEL).
 */
export function parseOwnerModels(value: string | undefined): Record<string, string> {
  if (!value || value.trim() === "") return {};
  const out: Record<string, string> = {};
  for (const part of value.split(",")) {
    const entry = part.trim();
    if (entry === "") continue;
    const colon = entry.indexOf(":");
    if (colon <= 0) {
      throw new ConfigError(
        `KANBAN_OWNER_MODELS entry ${JSON.stringify(entry)} is malformed (expected alias:model)`,
      );
    }
    const alias = entry.slice(0, colon).trim();
    const model = entry.slice(colon + 1).trim();
    if (alias === "" || model === "") {
      throw new ConfigError(
        `KANBAN_OWNER_MODELS entry ${JSON.stringify(entry)} has an empty alias or model`,
      );
    }
    if (alias in out) {
      throw new ConfigError(`KANBAN_OWNER_MODELS has duplicate alias ${JSON.stringify(alias)}`);
    }
    out[alias] = model;
  }
  return out;
}

/**
 * Parse a .env file body: KEY=VALUE lines, `#` comments, optional `export`
 * prefix, optional single/double quotes, inline comments on unquoted values.
 * Unparseable lines are skipped.
 */
export function parseDotEnv(content: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const m = ENV_LINE_RE.exec(line);
    if (!m) continue;
    const key = m[1]!;
    let value = m[2]!.trim();
    const quoted =
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")));
    if (quoted) {
      value = value.slice(1, -1);
    } else {
      const hash = value.search(/\s#/);
      if (hash !== -1) value = value.slice(0, hash).trim();
    }
    out[key] = value;
  }
  return out;
}

/**
 * Read a .env file (if present) and return its KEY=VALUE vars only.
 */
export async function loadEnvFileVars(
  envFile = ".env",
): Promise<Record<string, string>> {
  try {
    return parseDotEnv(await readFile(envFile, "utf8"));
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
    return {};
  }
}

/**
 * Load a .env file (if present) and merge it under process.env
 * (real environment variables always win).
 */
export async function loadEnv(
  envFile = ".env",
): Promise<Record<string, string | undefined>> {
  const fileVars = await loadEnvFileVars(envFile);
  return { ...fileVars, ...process.env };
}

export type FetchLike = typeof fetch;

/**
 * Validate MODEL against the LiteLLM proxy at boot (fail fast, PLAN.md §1).
 * Returns the list of model IDs the proxy serves.
 */
export async function validateModelAtBoot(
  cfg: Pick<KanbanConfig, "litellm" | "model">,
  fetchImpl: FetchLike = fetch,
): Promise<string[]> {
  const url = `${cfg.litellm.baseUrl}/models`;
  let res: Response;
  try {
    res = await fetchImpl(url, {
      headers: { Authorization: `Bearer ${cfg.litellm.apiKey}` },
      signal: AbortSignal.timeout(15_000),
    });
  } catch (err) {
    throw new ConfigError(
      `cannot reach LiteLLM proxy at ${cfg.litellm.baseUrl} to validate MODEL=${cfg.model}: ` +
        `${(err as Error).message}`,
    );
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ConfigError(
      `LiteLLM proxy rejected model validation (HTTP ${res.status} ${res.statusText}) at ${url}: ` +
        `${body.slice(0, 300) || "(no body)"}`,
    );
  }
  let payload: unknown;
  try {
    payload = await res.json();
  } catch (err) {
    throw new ConfigError(
      `LiteLLM proxy returned invalid JSON from ${url}: ${(err as Error).message}`,
    );
  }
  const ids = extractModelIds(payload);
  if (!ids.includes(cfg.model)) {
    throw new ConfigError(
      `MODEL=${cfg.model} is not served by the LiteLLM proxy at ${url}. ` +
        `Available models: ${ids.slice(0, 20).join(", ") || "(none)"}`,
    );
  }
  return ids;
}

/**
 * Validate the per-user keys (USER_KEYS) against the LiteLLM proxy at boot
 * (fail fast, like validateModelAtBoot): a rejected user key aborts startup
 * with a clear error (catches rotated/expired keys before any work bills
 * to the wrong place).
 */
export async function validateUserKeysAtBoot(
  cfg: Pick<KanbanConfig, "litellm" | "userKeys">,
  fetchImpl: FetchLike = fetch,
): Promise<void> {
  for (const [name, key] of Object.entries(cfg.userKeys)) {
    const url = `${cfg.litellm.baseUrl}/models`;
    let res: Response;
    try {
      res = await fetchImpl(url, {
        headers: { Authorization: `Bearer ${key}` },
        signal: AbortSignal.timeout(15_000),
      });
    } catch (err) {
      throw new ConfigError(
        `cannot validate USER_KEYS entry ${name} against the LiteLLM proxy at ${url}: ` +
          `${(err as Error).message}`,
      );
    }
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new ConfigError(
        `USER_KEYS entry ${name} was rejected by the LiteLLM proxy ` +
          `(HTTP ${res.status} ${res.statusText}) — the user's key is missing/rotated: ` +
          `${body.slice(0, 300) || "(no body)"}`,
      );
    }
  }
}

function extractModelIds(payload: unknown): string[] {
  if (typeof payload !== "object" || payload === null) return [];
  const data = (payload as { data?: unknown }).data;
  if (!Array.isArray(data)) return [];
  return data.flatMap((m): string[] => {
    if (typeof m === "object" && m !== null && typeof (m as { id?: unknown }).id === "string") {
      return [(m as { id: string }).id];
    }
    return [];
  });
}

/** Catalog rates in $/M tokens (the units pi-ai's calculateCost expects). */
export interface ModelCostRates {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
}

/** One entry of the LiteLLM proxy's /model/info `data` array. */
export interface ModelInfoEntry {
  model_name?: string;
  model_info?: Record<string, unknown>;
}

/**
 * Fetch the LiteLLM proxy's /model/info `data` array (the same data the
 * Grafana dashboards use). Returns the entries, or undefined when the
 * endpoint is unavailable (cost estimates + owner-model validation then
 * degrade to the $0 fallback — tokens are still tracked).
 */
export async function fetchModelInfo(
  cfg: Pick<KanbanConfig, "litellm">,
  fetchImpl: FetchLike = fetch,
): Promise<ModelInfoEntry[] | undefined> {
  const url = `${cfg.litellm.baseUrl.replace(/\/v1\/?$/, "")}/model/info`;
  let res: Response;
  try {
    res = await fetchImpl(url, {
      headers: { Authorization: `Bearer ${cfg.litellm.apiKey}` },
      signal: AbortSignal.timeout(15_000),
    });
  } catch (err) {
    console.warn(
      `[config] cannot fetch model info from ${url} (${(err as Error).message}) — cost estimates will be $0`,
    );
    return undefined;
  }
  if (!res.ok) {
    console.warn(`[config] model info fetch failed (HTTP ${res.status}) — cost estimates will be $0`);
    return undefined;
  }
  let payload: unknown;
  try {
    payload = await res.json();
  } catch (err) {
    console.warn(`[config] model info returned invalid JSON — cost estimates will be $0`);
    return undefined;
  }
  const data = (payload as { data?: unknown }).data;
  return Array.isArray(data) ? (data as ModelInfoEntry[]) : undefined;
}

/**
 * Extract $/M-token rates for one model from a /model/info `data` array.
 * Returns the rates, or undefined when the model is unknown or has no
 * configured costs (costs then stay $0 — tokens are still tracked, reports
 * show $0.00).
 *
 * Note: `model_info` only carries `input_cost_per_token`,
 * `output_cost_per_token`, and `cache_creation_input_token_cost` — there is
 * no cache-read price, so cacheRead is 0 (cache-heavy runs slightly
 * under-count spend).
 */
export function extractModelCostRates(
  data: ModelInfoEntry[],
  model: string,
): ModelCostRates | undefined {
  const entry = data.find((m) => m.model_name === model);
  const info = entry?.model_info;
  if (!info) {
    console.warn(`[config] MODEL=${model} not found in /model/info — cost estimates will be $0`);
    return undefined;
  }
  const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : 0);
  const toPerM = (perToken: number) => perToken * 1_000_000;
  const rates: ModelCostRates = {
    input: toPerM(num(info.input_cost_per_token)),
    output: toPerM(num(info.output_cost_per_token)),
    cacheRead: 0, // not exposed by /model/info
    cacheWrite: toPerM(num(info.cache_creation_input_token_cost)),
  };
  if (rates.input === 0 && rates.output === 0) {
    console.warn(`[config] MODEL=${model} has no cost configured in /model/info — cost estimates will be $0`);
    return undefined;
  }
  return rates;
}

/**
 * Fetch the cost rates the LiteLLM proxy has configured for a model from
 * `GET {LITELLM_BASE_URL}/model/info` (the same data the Grafana dashboards
 * use). Returns $/M-token rates, or undefined when the endpoint is
 * unavailable, the model is unknown, or it has no configured costs
 * (costs then stay $0 — tokens are still tracked, reports show $0.00).
 */
export async function fetchModelCostRates(
  cfg: Pick<KanbanConfig, "litellm" | "model">,
  fetchImpl: FetchLike = fetch,
): Promise<ModelCostRates | undefined> {
  const data = await fetchModelInfo(cfg, fetchImpl);
  return data ? extractModelCostRates(data, cfg.model) : undefined;
}

/**
 * Validate the per-owner pipeline model map (KANBAN_OWNER_MODELS, item 15)
 * at boot, and populate cfg.ownerModelCosts from the /model/info data:
 * - a mapped model unknown to the /model/info response fails startup with a
 *   clear error — a typo'd map must not surface mid-session as a 403 / empty
 *   completion (item 12's failure mode);
 * - an alias with no USER_KEYS entry is WARNED + IGNORED (decision: the map
 *   only changes which model an owner's sessions run on; without a USER_KEYS
 *   entry there is no owner key profile to bill to — profileFor falls back
 *   to the service profile + service model with its own warning. Failing
 *   startup on a stale alias (e.g. a removed agent) would be harsher than
 *   the degradation it protects against, so the pipeline keeps running);
 * - /model/info unavailable (modelInfo undefined) → validation is skipped
 *   with a warning and mapped models fall back to $0 rates (same soft
 *   fallback as the pipeline model's cost rates).
 */
export async function validateOwnerModelsAtBoot(
  cfg: Pick<KanbanConfig, "litellm" | "model" | "userKeys" | "ownerModels" | "ownerModelCosts">,
  modelInfo: ModelInfoEntry[] | undefined,
  fetchImpl: FetchLike = fetch,
): Promise<void> {
  const entries = Object.entries(cfg.ownerModels);
  if (entries.length === 0) return;
  if (modelInfo === undefined) {
    console.warn(
      `[config] /model/info unavailable — cannot validate KANBAN_OWNER_MODELS ` +
        `(${entries.map(([a, m]) => `${a}:${m}`).join(", ")}); mapped models will ` +
        `fall back to $0 cost rates`,
    );
    return;
  }
  for (const [alias, model] of entries) {
    if (!(alias in cfg.userKeys)) {
      console.warn(
        `[config] KANBAN_OWNER_MODELS alias ${JSON.stringify(alias)} has no USER_KEYS entry ` +
          `— ignored (sessions for that owner run on the service key + ${cfg.model})`,
      );
      continue;
    }
    if (!modelInfo.some((m) => m.model_name === model)) {
      const available = modelInfo
        .map((m) => m.model_name)
        .filter((n): n is string => typeof n === "string")
        .slice(0, 20)
        .join(", ");
      throw new ConfigError(
        `KANBAN_OWNER_MODELS maps ${alias} to ${model}, which the LiteLLM proxy ` +
          `does not serve (unknown to /model/info). Available models: ${available || "(none)"}`,
      );
    }
    cfg.ownerModelCosts[model] = extractModelCostRates(modelInfo, model);
  }
}

export interface LoadConfigOptions {
  /** Path of the .env file (default ".env" in cwd); missing file is fine. */
  envFile?: string;
  /** Validate MODEL against the proxy (default true). */
  validateModel?: boolean;
  /** Injectable fetch (tests). */
  fetchImpl?: FetchLike;
}

/**
 * Full startup config load: .env + process.env → parse/validate →
 * (optionally) validate MODEL against the LiteLLM proxy + fetch its cost
 * rates (from /model/info, the same data the Grafana dashboards use).
 */
export async function loadConfig(opts: LoadConfigOptions = {}): Promise<KanbanConfig> {
  const fileVars = await loadEnvFileVars(opts.envFile ?? ".env");
  // Apply .env vars to process.env (real environment variables always win)
  // so direct process.env reads (e.g. AI_KANBAN_DATA_DIR in the agent layer)
  // see the same values the config was parsed from.
  for (const [key, value] of Object.entries(fileVars)) {
    if (process.env[key] === undefined) process.env[key] = value;
  }
  const env = { ...fileVars, ...process.env };
  const cfg = parseConfig(env);
  if (!cfg.githubToken) {
    console.warn(
      "[config] GITHUB_TOKEN not set — git push (deploy stage) will fail until it is provided.",
    );
  }
  if (opts.validateModel !== false) {
    await validateModelAtBoot(cfg, opts.fetchImpl);
    // One /model/info fetch covers the pipeline model's cost rates AND the
    // per-owner model map (validation + per-model rates, item 15).
    const modelInfo = await fetchModelInfo(cfg, opts.fetchImpl);
    cfg.modelCost = modelInfo ? extractModelCostRates(modelInfo, cfg.model) : undefined;
    await validateOwnerModelsAtBoot(cfg, modelInfo, opts.fetchImpl);
    await validateUserKeysAtBoot(cfg, opts.fetchImpl);
  }
  return cfg;
}
