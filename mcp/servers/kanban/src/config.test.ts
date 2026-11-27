import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import {
  ConfigError,
  DEFAULTS,
  fetchModelCostRates,
  loadConfig,
  loadEnv,
  loadEnvFileVars,
  parseAgentSlugs,
  parseConfig,
  parseDotEnv,
  parseUserKeys,
  validateModelAtBoot,
  validateUserKeysAtBoot,
  type FetchLike,
} from "./config.js";

const baseEnv = {
  LITELLM_BASE_URL: "https://llm.choukalos.com/v1",
  LITELLM_API_KEY: "sk-test",
  MODEL: "matrix-coder",
};

test("applies defaults for optional vars", () => {
  const cfg = parseConfig({ ...baseEnv });
  assert.equal(cfg.litellm.baseUrl, "https://llm.choukalos.com/v1");
  assert.equal(cfg.litellm.apiKey, "sk-test");
  assert.equal(cfg.model, "matrix-coder");
  assert.equal(cfg.githubToken, undefined);
  assert.equal(cfg.db.driver, "sqlite");
  assert.equal(cfg.db.sqlitePath, "/data/kanban.db");
  assert.equal(cfg.db.mysql, undefined);
  assert.equal(cfg.workspace.hostPath, DEFAULTS.HOST_WORKSPACE_PATH);
  assert.equal(cfg.harness.repoUrl, DEFAULTS.HARNESS_REPO_URL);
  assert.equal(cfg.harness.skillsPath, DEFAULTS.HARNESS_SKILLS_PATH);
  assert.deepEqual(cfg.thinking, {
    groom: "xhigh",
    task: "medium",
    qa: "xhigh",
    summary: "medium",
  });
  assert.equal(cfg.mediaConcurrentTasks, 1);
  assert.equal(cfg.nonMediaConcurrentTasks, 2);
  assert.equal(cfg.agentConcurrentTasks, 1);
  assert.deepEqual(cfg.agentSlugs, []);
  assert.equal(cfg.server.bindAddr, DEFAULTS.BIND_ADDR);
  assert.equal(cfg.server.port, 3000);
});

test("normalizes trailing slashes on LITELLM_BASE_URL", () => {
  const cfg = parseConfig({ ...baseEnv, LITELLM_BASE_URL: "https://llm.example.com/v1///" });
  assert.equal(cfg.litellm.baseUrl, "https://llm.example.com/v1");
});

test("missing required vars fail fast with a clear error", () => {
  const noModel = { ...baseEnv, MODEL: "" };
  assert.throws(() => parseConfig(noModel), /MODEL is required/);
  const noUrl = { ...baseEnv, LITELLM_BASE_URL: "" };
  assert.throws(() => parseConfig(noUrl), /LITELLM_BASE_URL/);
  const noKey = { ...baseEnv, LITELLM_API_KEY: "" };
  assert.throws(() => parseConfig(noKey), /LITELLM_API_KEY is required/);
});

test("invalid DB_DRIVER fails", () => {
  assert.throws(() => parseConfig({ ...baseEnv, DB_DRIVER: "postgres" }), /DB_DRIVER/);
});

test("SQLITE_PATH override", () => {
  const cfg = parseConfig({ ...baseEnv, SQLITE_PATH: "/tmp/local/kanban.db" });
  assert.equal(cfg.db.sqlitePath, "/tmp/local/kanban.db");
});

test("mysql driver requires all MYSQL_* vars", () => {
  assert.throws(
    () => parseConfig({ ...baseEnv, DB_DRIVER: "mysql" }),
    (err: unknown) =>
      err instanceof ConfigError &&
      /MYSQL_HOST is required/.test(err.message) &&
      /MYSQL_USER is required/.test(err.message) &&
      /MYSQL_PASSWORD is required/.test(err.message) &&
      /MYSQL_DATABASE is required/.test(err.message),
  );
});

test("mysql driver parses all vars", () => {
  const cfg = parseConfig({
    ...baseEnv,
    DB_DRIVER: "mysql",
    MYSQL_HOST: "thor",
    MYSQL_PORT: "3307",
    MYSQL_USER: "kanban",
    MYSQL_PASSWORD: "secret",
    MYSQL_DATABASE: "kanban",
  });
  assert.equal(cfg.db.driver, "mysql");
  assert.deepEqual(cfg.db.mysql, {
    host: "thor",
    port: 3307,
    user: "kanban",
    password: "secret",
    database: "kanban",
  });
});

test("invalid thinking level fails", () => {
  assert.throws(
    () => parseConfig({ ...baseEnv, GROOM_THINKING: "ultra" }),
    /GROOM_THINKING/,
  );
});

test("media/non-media concurrency must be positive integers", () => {
  for (const bad of ["0", "-1", "abc", "2.5"]) {
    assert.throws(
      () => parseConfig({ ...baseEnv, MEDIA_CONCURRENT_TASKS: bad }),
      /MEDIA_CONCURRENT_TASKS/,
      `expected MEDIA_CONCURRENT_TASKS=${bad} to fail`,
    );
    assert.throws(
      () => parseConfig({ ...baseEnv, NON_MEDIA_CONCURRENT_TASKS: bad }),
      /NON_MEDIA_CONCURRENT_TASKS/,
      `expected NON_MEDIA_CONCURRENT_TASKS=${bad} to fail`,
    );
    assert.throws(
      () => parseConfig({ ...baseEnv, AGENT_CONCURRENT_TASKS: bad }),
      /AGENT_CONCURRENT_TASKS/,
      `expected AGENT_CONCURRENT_TASKS=${bad} to fail`,
    );
  }
  const cfg = parseConfig({ ...baseEnv, MEDIA_CONCURRENT_TASKS: "2", NON_MEDIA_CONCURRENT_TASKS: "3" });
  assert.equal(cfg.mediaConcurrentTasks, 2);
  assert.equal(cfg.nonMediaConcurrentTasks, 3);
});

test("AGENT_SLUGS: comma-separated slugs (trimmed, unique); empty/unset = []", () => {
  const cfg = parseConfig({ ...baseEnv, AGENT_SLUGS: "product, analyst ,marketing" });
  assert.deepEqual(cfg.agentSlugs, ["product", "analyst", "marketing"]);
  assert.throws(
    () => parseConfig({ ...baseEnv, AGENT_SLUGS: "product,product" }),
    /duplicate slug/,
  );
  assert.deepEqual(parseAgentSlugs(undefined), []);
  assert.deepEqual(parseAgentSlugs("   "), []);
});

test("PORT must be a valid port", () => {
  for (const bad of ["0", "70000", "nope"]) {
    assert.throws(() => parseConfig({ ...baseEnv, PORT: bad }), /PORT/, `PORT=${bad}`);
  }
  assert.equal(parseConfig({ ...baseEnv, PORT: "8080" }).server.port, 8080);
});

test("parseDotEnv handles comments, quotes, export prefix, inline comments", () => {
  const vars = parseDotEnv(
    [
      "# full-line comment",
      "",
      "A=plain",
      "B=with space # inline comment",
      "C=\"quoted # not a comment\"",
      "D='single quoted'",
      "export E=exported",
      "not a valid line",
      "F=",
    ].join("\n"),
  );
  assert.deepEqual(vars, {
    A: "plain",
    B: "with space",
    C: "quoted # not a comment",
    D: "single quoted",
    E: "exported",
    F: "",
  });
});

test("loadEnv merges .env under process.env (env wins)", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-cfg-"));
  try {
    const envFile = path.join(dir, ".env");
    await writeFile(
      envFile,
      ["SHARED=from-file", "ONLY_FILE=1", `SHADOWED=from-file`].join("\n"),
    );
    const saved = process.env.SHADOWED;
    process.env.SHADOWED = "from-env";
    try {
      const env = await loadEnv(envFile);
      assert.equal(env.SHARED, "from-file");
      assert.equal(env.ONLY_FILE, "1");
      assert.equal(env.SHADOWED, "from-env");
    } finally {
      if (saved === undefined) delete process.env.SHADOWED;
      else process.env.SHADOWED = saved;
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("loadEnv tolerates a missing .env file", async () => {
  const env = await loadEnv("/nonexistent/.env");
  assert.equal(env.PATH, process.env.PATH);
});

// --- boot-time model validation (mocked fetch) ---------------------------

interface MockFetchOpts {
  status?: number;
  body?: unknown;
  text?: string;
  networkError?: Error;
}

function mockFetch(opts: MockFetchOpts, seenUrls: string[] = []): FetchLike {
  return (async (input) => {
    seenUrls.push(String(input));
    if (opts.networkError) throw opts.networkError;
    const body = opts.body !== undefined ? JSON.stringify(opts.body) : (opts.text ?? "");
    return new Response(body, {
      status: opts.status ?? 200,
      headers: { "content-type": "application/json" },
    });
  }) as FetchLike;
}

const bootCfg = { litellm: { baseUrl: "https://llm.example.com/v1", apiKey: "sk-x" }, model: "matrix-coder" };

test("validateModelAtBoot accepts a model served by the proxy", async () => {
  const seen: string[] = [];
  const ids = await validateModelAtBoot(
    bootCfg,
    mockFetch({ body: { data: [{ id: "matrix-coder" }, { id: "other" }] } }, seen),
  );
  assert.deepEqual(ids, ["matrix-coder", "other"]);
  assert.equal(seen[0], "https://llm.example.com/v1/models");
});

test("validateModelAtBoot fails when MODEL is not in the proxy list", async () => {
  await assert.rejects(
    validateModelAtBoot(bootCfg, mockFetch({ body: { data: [{ id: "other" }] } })),
    (err: unknown) =>
      err instanceof ConfigError &&
      /MODEL=matrix-coder is not served/.test(err.message) &&
      /other/.test(err.message),
  );
});

test("validateModelAtBoot fails on HTTP errors", async () => {
  await assert.rejects(
    validateModelAtBoot(bootCfg, mockFetch({ status: 401, text: "invalid key" })),
    /HTTP 401/,
  );
});

test("validateModelAtBoot fails on network errors", async () => {
  await assert.rejects(
    validateModelAtBoot(bootCfg, mockFetch({ networkError: new Error("ECONNREFUSED") })),
    (err: unknown) =>
      err instanceof ConfigError && /cannot reach LiteLLM proxy/.test(err.message),
  );
});

test("validateModelAtBoot fails on invalid JSON", async () => {
  await assert.rejects(
    validateModelAtBoot(bootCfg, mockFetch({ text: "<html>oops</html>" })),
    /invalid JSON/,
  );
});

test("parseUserKeys: name=key pairs (trimmed, order kept)", () => {
  assert.deepEqual(parseUserKeys(undefined), {});
  assert.deepEqual(parseUserKeys(""), {});
  assert.deepEqual(parseUserKeys("  "), {});
  assert.deepEqual(parseUserKeys("chuck=sk-chuck,dylan=sk-dylan"), {
    chuck: "sk-chuck",
    dylan: "sk-dylan",
  });
  assert.deepEqual(parseUserKeys(" chuck = sk-chuck , , dylan=sk-dylan "), {
    chuck: "sk-chuck",
    dylan: "sk-dylan",
  });
});

test("parseUserKeys: malformed entries fail fast", () => {
  assert.throws(() => parseUserKeys("sk-no-name"), /malformed/);
  assert.throws(() => parseUserKeys("chuck="), /empty key/);
  assert.throws(() => parseUserKeys("=sk-no-name"), /malformed|empty name/);
  assert.throws(() => parseUserKeys("chuck=sk-1,chuck=sk-2"), /duplicate name/);
});

test("parseUserKeys: env-var-name references resolve at boot (Phase 13.5)", () => {
  // Save/restore — the test runner's environment may already carry these.
  const saved = {
    chuck: process.env.LITELLM_KEY_CHUCK,
    dylan: process.env.LITELLM_KEY_DYLAN,
    empty: process.env.EMPTY_REF_TEST,
    siri: process.env.SIRI_KEY_SERVICE,
  };
  process.env.LITELLM_KEY_CHUCK = "sk-resolved-chuck";
  process.env.LITELLM_KEY_DYLAN = "sk-resolved-dylan";
  try {
    // MEMORY_USER_KEYS template form: name=ENV_VAR_NAME.
    assert.deepEqual(
      parseUserKeys("chuck=LITELLM_KEY_CHUCK,dylan=LITELLM_KEY_DYLAN"),
      { chuck: "sk-resolved-chuck", dylan: "sk-resolved-dylan" },
    );
    // Mixed: literal keys and references coexist (literal keys start with
    // 'sk-' and never match the env-var pattern).
    assert.deepEqual(
      parseUserKeys("chuck=LITELLM_KEY_CHUCK,other=sk-other"),
      { chuck: "sk-resolved-chuck", other: "sk-other" },
    );
    // Unset reference → fail fast.
    assert.throws(() => parseUserKeys("ghost=NO_SUCH_VAR_XYZ"), /unset or empty/);
    // Empty reference → fail fast.
    process.env.EMPTY_REF_TEST = "";
    assert.throws(() => parseUserKeys("ghost=EMPTY_REF_TEST"), /unset or empty/);
    // Resolved reference that is NOT a LiteLLM key (the shared identity map
    // may carry non-LiteLLM credentials, e.g. the siri service token) →
    // skipped with a warning, not a startup failure.
    process.env.SIRI_KEY_SERVICE = "24d3abcdef00ff94";
    assert.deepEqual(
      parseUserKeys("chuck=LITELLM_KEY_CHUCK,service=SIRI_KEY_SERVICE"),
      { chuck: "sk-resolved-chuck" },
    );
  } finally {
    for (const [k, v] of Object.entries({ LITELLM_KEY_CHUCK: saved.chuck, LITELLM_KEY_DYLAN: saved.dylan, EMPTY_REF_TEST: saved.empty, SIRI_KEY_SERVICE: saved.siri })) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
});

test("parseConfig: USER_KEYS lands in cfg.userKeys (absent → {})", () => {
  const withKeys = parseConfig({ ...baseEnv, USER_KEYS: "chuck=sk-chuck,dylan=sk-dylan" });
  assert.deepEqual(withKeys.userKeys, { chuck: "sk-chuck", dylan: "sk-dylan" });
  assert.deepEqual(parseConfig({ ...baseEnv }).userKeys, {});
});

test("validateUserKeysAtBoot: accepts keys the proxy serves, fails on rejection", async () => {
  const cfg = {
    litellm: { baseUrl: "https://llm.example.com/v1", apiKey: "sk-service" },
    userKeys: { chuck: "sk-chuck", dylan: "sk-dylan" },
  };
  // Both keys accepted (200).
  await validateUserKeysAtBoot(cfg, mockFetch({ body: { data: [{ id: "m" }] } }));
  // One key rejected (403) → ConfigError naming the user.
  const failing: FetchLike = (async (_input, init) => {
    const headers = (init?.headers ?? {}) as Record<string, string>;
    const auth = headers.Authorization ?? "";
    const rejected = auth === "Bearer sk-dylan";
    return new Response(rejected ? "" : JSON.stringify({ data: [{ id: "m" }] }), {
      status: rejected ? 403 : 200,
      headers: { "content-type": "application/json" },
    });
  }) as FetchLike;
  await assert.rejects(() => validateUserKeysAtBoot(cfg, failing), /USER_KEYS entry dylan/);
  // No user keys → no-op.
  await validateUserKeysAtBoot({ litellm: cfg.litellm, userKeys: {} }, mockFetch({}));
});

test("loadConfig reads .env and skips model validation when told", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-cfg-"));
  const keys = ["LITELLM_BASE_URL", "LITELLM_API_KEY", "MODEL", "MEDIA_CONCURRENT_TASKS", "NON_MEDIA_CONCURRENT_TASKS", "AGENT_CONCURRENT_TASKS", "AGENT_SLUGS", "PORT"];
  const saved: Record<string, string | undefined> = {};
  try {
    for (const k of keys) saved[k] = process.env[k];
    const envFile = path.join(dir, ".env");
    await writeFile(
      envFile,
      [
        "LITELLM_BASE_URL=https://llm.example.com/v1",
        "LITELLM_API_KEY=sk-file",
        "MODEL=file-model",
        "MEDIA_CONCURRENT_TASKS=1",
        "NON_MEDIA_CONCURRENT_TASKS=2",
        "AGENT_CONCURRENT_TASKS=1",
        "AGENT_SLUGS=product,analyst",
        "PORT=4567",
      ].join("\n"),
    );
    const cfg = await loadConfig({ envFile, validateModel: false });
    assert.equal(cfg.model, "file-model");
    assert.equal(cfg.litellm.apiKey, "sk-file");
    assert.equal(cfg.mediaConcurrentTasks, 1);
    assert.equal(cfg.nonMediaConcurrentTasks, 2);
    assert.equal(cfg.server.port, 4567);
    assert.equal(cfg.agentConcurrentTasks, 1);
    assert.deepEqual(cfg.agentSlugs, ["product", "analyst"]);
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
    await rm(dir, { recursive: true, force: true });
  }
});

test("loadConfig validates MODEL against the proxy by default", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-cfg-"));
  const keys = ["LITELLM_BASE_URL", "LITELLM_API_KEY", "MODEL"];
  const saved: Record<string, string | undefined> = {};
  try {
    for (const k of keys) saved[k] = process.env[k];
    const envFile = path.join(dir, ".env");
    await writeFile(
      envFile,
      [
        "LITELLM_BASE_URL=https://llm.example.com/v1",
        "LITELLM_API_KEY=sk-file",
        "MODEL=good-model",
      ].join("\n"),
    );
    const cfg = await loadConfig({
      envFile,
      fetchImpl: mockFetch({ body: { data: [{ id: "good-model" }] } }),
    });
    assert.equal(cfg.model, "good-model");
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
    await rm(dir, { recursive: true, force: true });
  }
});

// --- model cost rates from /model/info (Grafana's data source) -----------

const modelInfoBody = {
  data: [
    {
      model_name: "matrix-coder",
      model_info: {
        input_cost_per_token: 7.5e-7,
        output_cost_per_token: 4.5e-6,
        cache_creation_input_token_cost: 7.5e-8,
      },
    },
    { model_name: "other", model_info: { input_cost_per_token: 1e-7 } },
  ],
};

test("fetchModelCostRates: per-token rates → $/M for the configured model", async () => {
  const seen: string[] = [];
  const rates = await fetchModelCostRates(bootCfg, mockFetch({ body: modelInfoBody }, seen));
  assert.equal(seen[0], "https://llm.example.com/model/info");
  assert.deepEqual(rates, { input: 0.75, output: 4.5, cacheRead: 0, cacheWrite: 0.075 });
});

test("fetchModelCostRates: baseUrl without /v1 works too", async () => {
  const seen: string[] = [];
  const rates = await fetchModelCostRates(
    { ...bootCfg, litellm: { baseUrl: "https://llm.example.com", apiKey: "sk-x" } },
    mockFetch({ body: modelInfoBody }, seen),
  );
  assert.equal(seen[0], "https://llm.example.com/model/info");
  assert.equal(rates?.input, 0.75);
});

test("fetchModelCostRates: unknown model → undefined (no throw)", async () => {
  const rates = await fetchModelCostRates(bootCfg, mockFetch({ body: { data: [] } }));
  assert.equal(rates, undefined);
});

test("fetchModelCostRates: no costs configured → undefined (no throw)", async () => {
  const rates = await fetchModelCostRates(
    bootCfg,
    mockFetch({ body: { data: [{ model_name: "matrix-coder", model_info: {} }] } }),
  );
  assert.equal(rates, undefined);
});

test("fetchModelCostRates: HTTP error / network error / bad JSON → undefined (no throw)", async () => {
  assert.equal(await fetchModelCostRates(bootCfg, mockFetch({ status: 401, text: "nope" })), undefined);
  assert.equal(
    await fetchModelCostRates(bootCfg, mockFetch({ networkError: new Error("ECONNREFUSED") })),
    undefined,
  );
  assert.equal(await fetchModelCostRates(bootCfg, mockFetch({ text: "<html>oops</html>" })), undefined);
});

test("loadConfig fetches model cost rates alongside model validation", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "ai-kanban-cfg-"));
  const keys = ["LITELLM_BASE_URL", "LITELLM_API_KEY", "MODEL"];
  const saved: Record<string, string | undefined> = {};
  try {
    for (const k of keys) saved[k] = process.env[k];
    const envFile = path.join(dir, ".env");
    await writeFile(
      envFile,
      [
        "LITELLM_BASE_URL=https://llm.example.com/v1",
        "LITELLM_API_KEY=sk-file",
        "MODEL=matrix-coder",
      ].join("\n"),
    );
    const cfg = await loadConfig({
      envFile,
      fetchImpl: (async (input) => {
        const url = String(input);
        if (url.endsWith("/models")) {
          return new Response(JSON.stringify({ data: [{ id: "matrix-coder" }] }), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
        }
        return new Response(JSON.stringify(modelInfoBody), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }) as FetchLike,
    });
    assert.deepEqual(cfg.modelCost, { input: 0.75, output: 4.5, cacheRead: 0, cacheWrite: 0.075 });
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
    await rm(dir, { recursive: true, force: true });
  }
});
