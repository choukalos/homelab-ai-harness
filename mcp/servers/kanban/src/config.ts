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
  CONCURRENT_TASKS: "1",
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

    // Orchestrator / server
    CONCURRENT_TASKS: z.coerce
      .number()
      .int("CONCURRENT_TASKS must be an integer")
      .min(1, "CONCURRENT_TASKS must be >= 1")
      .default(1),
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
  concurrentTasks: number;
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
    concurrentTasks: v.CONCURRENT_TASKS,
    server: { bindAddr: v.BIND_ADDR, port: v.PORT },
  };
}

const ENV_LINE_RE = /^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/;

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

/**
 * Fetch the cost rates the LiteLLM proxy has configured for a model from
 * `GET {LITELLM_BASE_URL}/model/info` (the same data the Grafana dashboards
 * use). Returns $/M-token rates, or undefined when the endpoint is
 * unavailable, the model is unknown, or it has no configured costs
 * (costs then stay $0 — tokens are still tracked, reports show $0.00).
 *
 * Note: `model_info` only carries `input_cost_per_token`,
 * `output_cost_per_token`, and `cache_creation_input_token_cost` — there is
 * no cache-read price, so cacheRead is 0 (cache-heavy runs slightly
 * under-count spend).
 */
export async function fetchModelCostRates(
  cfg: Pick<KanbanConfig, "litellm" | "model">,
  fetchImpl: FetchLike = fetch,
): Promise<ModelCostRates | undefined> {
  const url = `${cfg.litellm.baseUrl.replace(/\/v1\/?$/, "")}/model/info`;
  let res: Response;
  try {
    res = await fetchImpl(url, {
      headers: { Authorization: `Bearer ${cfg.litellm.apiKey}` },
      signal: AbortSignal.timeout(15_000),
    });
  } catch (err) {
    console.warn(
      `[config] cannot fetch model cost rates from ${url} (${(err as Error).message}) — cost estimates will be $0`,
    );
    return undefined;
  }
  if (!res.ok) {
    console.warn(`[config] model cost rates fetch failed (HTTP ${res.status}) — cost estimates will be $0`);
    return undefined;
  }
  let payload: unknown;
  try {
    payload = await res.json();
  } catch (err) {
    console.warn(`[config] model cost rates returned invalid JSON — cost estimates will be $0`);
    return undefined;
  }
  const data = (payload as { data?: unknown }).data;
  if (!Array.isArray(data)) return undefined;
  const entry = data.find(
    (m) => typeof m === "object" && m !== null && (m as { model_name?: unknown }).model_name === cfg.model,
  ) as { model_info?: Record<string, unknown> } | undefined;
  const info = entry?.model_info;
  if (!info) {
    console.warn(`[config] MODEL=${cfg.model} not found in /model/info — cost estimates will be $0`);
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
    console.warn(`[config] MODEL=${cfg.model} has no cost configured in /model/info — cost estimates will be $0`);
    return undefined;
  }
  return rates;
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
    cfg.modelCost = await fetchModelCostRates(cfg, opts.fetchImpl);
  }
  return cfg;
}
