# Cross-Client Skills/Agents — Plan

> **Fresh plan, 2026-08-29.** Goal: every client (pi, opencode, openchamber,
> Open WebUI, Claude Code, Siri) can **list** the family skills/agents and
> **run** one by name + a short prompt (`/skill:morning-brief smart home
> competitors`), with a negligible always-on context footprint.
>
> **No secret values here — ever.** (Key names/paths yes; key contents no.)
> **The implementing model never runs container lifecycle commands** —
> restarts/rebuilds are manual steps run by Chuck between turns.
>
> **Do NOT touch/restart the LiteLLM proxy** — that's the owner's job; a
> LiteLLM restart kills the implementing agent's own session (it runs through
> LiteLLM). Minimize owner manual steps: batch code changes and ask for a
> single restart per coherent chunk. **Phase A (skill-runner only) does not
> touch LiteLLM.** Phase B (register `mcp_skills` in `config.yml`) is the
> first step that needs a LiteLLM restart — owner runs it.

## 0. Requirements (from Chuck, 2026-08-29)

1. Any client should be able to **list all** available skills/agents and
   **execute** one as `/name` + short prompt.
2. **No context bloat** — 15 always-on MCP tool schemas per client interaction
   is a non-starter (and it is: MCP tool schemas are injected into every
   context, cost scales with tool count).
3. Today the skills are only reachable via the harness (`skill-runner`) and
   Siri — confirmed.

## 1. Verified current state (2026-08-29, live)

### What clients see from `litellm-proxy` (v1.92.0)
| What | Endpoint | Status |
|---|---|---|
| Models | `/model/info` + `/v1/models` | ✅ |
| MCP tools | `/mcp-rest/tools/list` | ✅ (9 servers) |
| Skills | `/claude-code/marketplace.json` + `/v1/skills` | ❌ empty / error |

- **Skill Hub (Claude Code Marketplace)**: `/claude-code/*` endpoints work.
  `LiteLLM_ClaudeCodePluginTable` in litellm-db has **0 rows** — nothing ever
  registered. Entries = metadata + **git source ref** (`github` / `url` /
  `git-subdir`); clients clone from git. pi's provider reads
  `marketplace.json` and injects **name + description only** into the system
  prompt (no git clone).
- **Legacy `/v1/skills`**: Anthropic-only pass-through; 500s with
  `ANTHROPIC_API_KEY ... required`. Dead on this self-hosted proxy unless we
  add Anthropic creds (would only list *Anthropic-cloud* skills — not useful).

### skill-runner (port 8091)
- `POST /skills/{skill_name}` — execute (job-based; `GET /skills/jobs/{id}`,
  approve/cancel, artifact endpoint). ✅
- **No `GET /skills` list endpoint** — but manifests are on disk
  (`skills/<name>/skill.yml`: name, description, inputs, channels,
  model_alias, max_runtime). Trivial to expose.
- 15 skills, all `skill.py` + `skill.yml` (executable pipelines, **not**
  SKILL.md). `skill.yml` already declares `channels: [cli, pi, n8n]` — the
  pi-exposure intent was always there.
- Repo is public: `github.com/choukalos/homelab-ai-harness` (git verified).

### pi skill system (researched 2026-08-29, docs/skills.md)
- pi implements the **Agent Skills standard** (agentskills.io) — the same
  SKILL.md standard used by Claude Code, OpenAI Codex, OpenCode, Cursor.
- **Progressive disclosure**: at startup only name + description go into the
  system prompt; the full SKILL.md loads on-demand (or when forced). →
  solves the context-bloat requirement by design.
- **Skills register as `/skill:name` commands**: `/skill:pdf-tools extract`
  loads the skill; args are appended as `User: <args>`. Requires
  `enableSkillCommands: true` (settings.json or `/settings`).
- Discovery locations: `~/.pi/agent/skills/`, `~/.agents/skills/` (global);
  `.pi/skills/`, `.agents/skills/` (project, cwd→git root); `skills/` dirs or
  `pi.skills` in package.json; **settings `skills` array (any files/dirs —
  can point at `~/.claude/skills`, a git checkout, etc.)**; `--skill` CLI.
- Name rules: lowercase a-z/0-9/hyphens (so `morning_brief` →
  `morning-brief`). pi does NOT require name == parent dir.
- Cross-harness: `~/.agents/skills/` is a shared location; settings `skills`
  array can import Claude Code / Codex skill dirs.

## 2. Recommended architecture (3 layers)

```
┌─ Layer 3: client-native UX ─────────────────────────────────────┐
│  SKILL.md wrappers (git subfolder) → pi /skill:name, Claude    │
│  Code + OpenCode + Codex Agent Skills (same files)             │
├─ Layer 2: universal transport ─────────────────────────────────┤
│  mcp_skills MCP server — 2 meta-tools: list_skills(),         │
│  run_skill(name, prompt) → Open WebUI, opencode, openchamber, │
│  Siri, any MCP client                                          │
├─ Layer 1: execution (existing) ────────────────────────────────┤
│  skill-runner :8091 — POST /skills/{name}, jobs, artifacts    │
└────────────────────────────────────────────────────────────────┘
```

**Why 2 meta-tools, not 15 MCP tools (the context math):**
- 15 tools = 15 descriptions + 15 input schemas in every context, every turn.
- 2 meta-tools = 2 tiny schemas always-on (`list_skills` takes no args;
  `run_skill` takes `{name, prompt?, params?}` — generic, no per-skill
  schemas). Per-skill detail is fetched **on demand** via `list_skills()`.
- This is the standard "tool gateway" pattern and directly satisfies req. 2.

**Per-client coverage:**
| Client | List | Run | Mechanism |
|---|---|---|---|
| pi | ✅ | ✅ `/skill:name <prompt>` | Layer 3 (native, slash command) + Layer 2 |
| Claude Code | ✅ | ✅ (model-invoked skills) | Layer 3 (Agent Skills) |
| OpenCode / openchamber | ✅ | ✅ (native skill tool) | Layer 3 (Agent Skills) + Layer 2 |
| Open WebUI | ✅ | ✅ | Layer 2 (MCP) — no SKILL.md support |
| Siri | ✅ | ✅ | Layer 2 (or existing harness API) |
| Any future MCP client | ✅ | ✅ | Layer 2 |

The literal `/slash` box is a client UI feature: pi gives `/skill:name`
natively; other clients surface the same capability as agent tools /
command palettes. The **capability** (list + run-by-name + short prompt) is
universal via the two layers.

## 3. Work items

### W1. skill-runner: `GET /skills` + durable job index — small

**Status: DONE (deployed + verified live, 2026-08-29).** `./homelab.sh rebuild skill-only`
run; container healthy. Verified against the live `homelab` DB:
`GET /skills` returns the 12 real skills (auth allow-list enforced when
`SKILL_RUNNER_API_KEY` set → 403 without key, open when unset); a real
`morning_brief` run persisted a job to `skill_jobs`; a completed job survives a
restart (hydrated, still queryable via `GET /skills/jobs/{id}`); and a job
killed mid-run is correctly marked `interrupted` ("Interrupted by runner
restart") on the next startup. `code_review`/`repo_maintenance` are TODO
placeholders (no `skill.py`) → correctly excluded. Also fixed 6 `skill.yml` +
3 `skill.py` + 1 docstring pinning the dead `local/qwen-coder` alias →
`matrix-coder` (pre-step; unblocks real runs). Added `pyyaml` + `pymysql`
(Dockerfile + pyproject). Compose: MySQL env (`MYSQL_DB_HOST`/`AI_DB_*`) replacing
the old `JOBS_DB_PATH` + `jobs.db` volume (see §7: MySQL, not SQLite).

**Persist-at-start:** `_persist_job(job)` is also called when a job first
transitions to `running` (in `_execute_skill`), so an in-flight job is in the
DB immediately and `hydrate()` marks it `interrupted` on restart instead of
losing it. (Completion/approval/cancel paths also persist.)

- New endpoint in `skills/runner/main.py`: walk the skills dir, parse each
  `skill.yml`, return `[{name, description, inputs, channels, model_alias,
  max_runtime, version}]`. No secrets. Auth: same inbound allow-list as
  other endpoints.
- This becomes the single source of truth for Layer 2's `list_skills()`.
- **Durable job index:** persist job records to **MySQL** (`skill_jobs` table
  in the `homelab` DB; see §7) so `get_skill_job` survives a runner restart.
  On startup, hydrate the in-memory `jobs` dict from the table (terminal-state
  jobs stay queryable; in-flight jobs from a prior run are marked
  `interrupted`). Write-through on every status change. The `data` column holds
  the full Job JSON; `job_id` is the PK. Keeps the existing in-memory fast
  path; MySQL is the durable backing store. (Makes §5 decision 2's retrieval
  durable across restarts.)

### W2. `mcp_skills` MCP server (item 2) — small

**Status: DONE (deployed + verified live, 2026-08-29).**

- New server `mcp/servers/skills/` (FastMCP, same pattern as the other 9):
  - `list_skills()` → `GET /skills` on skill-runner → name + description +
    inputs.
  - `run_skill(name, prompt?, params?)` → `POST /skills/{name}`. `prompt`
    (short natural-language) is auto-mapped to the skill's primary string
    input (well-known name first, then first required string input); `params`
    (explicit input dict) wins. `POST /skills/{name}` is **synchronous** (the
    runner blocks until the job reaches a terminal state or an approval gate),
    so `run_skill` issues the POST with a generous timeout (skill's
    `max_runtime`, else 180s) and returns the final job — no poll loop needed.
  - `get_skill_job(job_id)` → `GET /skills/jobs/{id}` (durable — survives a
    runner restart via the MySQL job index).
- Holds the skill-runner service key (`SKILL_RUNNER_API_KEY`) as a fallback;
  registered in `litellm/config.yml` `mcp_servers` (`url:
  http://mcp_skills:8000/mcp`, `allow_all_keys: true`, `extra_headers:
  [Authorization]` for identity threading, `timeout: 7200` since `run_skill`
  blocks up to `max_runtime`).
- **Identity threading:** the caller's LiteLLM key (forwarded by LiteLLM via
  the `Authorization` header) is passed to skill-runner as `X-API-Key`, so
  the job attributes to the right user (`resolve_user_id()`). Falls back to
  the service key when no caller key is present. (See auth_todo.md note on
  the pre-existing `SIRI_API_KEY` → `service` mapping detail.)
- Compose: service added to `compose.mcp.yml` (network `ai-net`, env for
  runner URL + key).
- **Verified live:** `list_skills` (12 skills, correct inputs), `run_skill`
  (`morning_brief` + `siri_ask` completed, returned job_id/status/summary/
  artifact_path), `get_skill_job` (retrieved a completed job). The `mcp_skills`
  container is up on `ai-net`; the 3 tools are registered and working. **One
  manual step remains:** restart LiteLLM to pick up the `mcp_servers` entry
  (config.yml changed).

### W3. SKILL.md wrappers + pi install (item 4) — small
- New git subfolder `agents-skills/` in homelab-ai-harness: one dir per
  skill, `agents-skills/<name>/SKILL.md` (standard layout — portable across
  harnesses; flat root `.md` is a pi-only leniency, avoid).
- Frontmatter: `name` (hyphenated, e.g. `morning-brief`), `description`
  (from `skill.yml`).
- Body: how to run it —
  1. preferred: call the `run_skill` MCP tool (client has `mcp_skills`) —
     no secrets in the skill file;
  2. fallback: `curl -X POST http://thor.local:8091/skills/<name>` with
     `X-API-Key: $SKILL_RUNNER_API_KEY` (user-set env; **no secrets in repo**;
     aligns with auth_todo.md v2 per-user keys).
  3. note the skill's declared inputs so the agent maps the short prompt
     onto them (e.g. interests → "smart home competitors").
- **Install on pi** (pick one):
  - `git clone`/existing checkout + settings: `"skills": ["~/homelab/agents-skills"]`
    in `~/.pi/agent/settings.json`; or
  - symlink each wrapper dir into `~/.pi/agent/skills/`; or
  - project-level: `agents-skills/` at repo root + `.pi/settings.json`
    `skills` entry when running pi from inside the repo.
- Set `enableSkillCommands: true` → `/skill:morning-brief <prompt>` works.
- Same files also serve Claude Code / OpenCode / Codex (Agent Skills
  standard) — e.g. point their skill dirs at the same checkout.

### W4. Skill Hub registration (item 1) — optional, do last
- Script: for each skill, `POST /claude-code/plugins`
  `{"name": "<hyphenated>", "source": {"source": "git-subdir",
  "url": "https://github.com/choukalos/homelab-ai-harness.git",
  "path": "agents-skills/<name>"}, "description": "...", "version": "1.0"}`
  (auth: master/admin key), then `POST /claude-code/plugins/<name>/enable`.
- Effect: `marketplace.json` lists them; pi injects name+description as
  prompt guidance; Claude Code can `plugin marketplace add` + install.
- **Caveat:** for Claude Code to treat the clone as a real plugin it needs a
  plugin layout (`.claude-plugin/plugin.json` etc.); a bare SKILL.md dir is
  only useful as a skill. Since W3 already covers Claude Code via Agent
  Skills, W4's incremental value today is mostly the registry + pi prompt
  hints. Low priority.

## 4. Phases & manual steps (Chuck runs between turns)

| Phase | Items | Manual steps |
|---|---|---|
| A | W1 | **DONE (deployed + verified live, 2026-08-29):** `./homelab.sh rebuild skill-only` run; `GET /skills` (12 skills, auth), a real `morning_brief` job persisted to `skill_jobs`, completed job survives restart, in-flight job → `interrupted`. Does NOT touch LiteLLM. |
| B | W2 | **DONE (deployed + verified live, 2026-08-29):** `mcp_skills` built + up on `ai-net`; `list_skills`/`run_skill`/`get_skill_job` verified against the running skill-runner. **One manual step remains:** `docker compose -f compose/compose.ai-core.yml restart litellm` (config.yml `mcp_servers` entry added) — the container is up but LiteLLM hasn't picked up the new entry yet. |
| C | W3 | commit `agents-skills/` to GitHub; edit `~/.pi/agent/settings.json` (`skills` array + `enableSkillCommands`); restart pi session |
| D | W4 (optional) | run registration script (idempotent; re-POST updates) |

## 5. Decisions (resolved 2026-08-29)

1. **Naming/UX:** keep pi's native `/skill:name <prompt>` form. No bare-
   `/name` alias extension.
2. **run_skill semantics:** block up to the skill's `max_runtime`; if the job
   is still running beyond that, return `job_id` + status. Retrieval of a
   finished long job = call `get_skill_job(job_id)` (see §6). The job store
   is **in-memory** (`jobs: dict` in runner/main.py), so W1 adds a **durable
   MySQL job index** (`skill_jobs` table in the `homelab` DB; see §7) —
   write-through on status change, hydrated on startup — so retrieval
   survives a runner restart (artifacts on disk already survive).
3. **Wrapper location:** subfolder `agents-skills/` in homelab-ai-harness.
4. **Auth:** per-user keys per auth_todo.md v2 (see §6 identity threading).
5. **OWUI:** on hold for now (user deciding after discussion). Leave the
   existing harness path untouched.

## 6. Execution model + public-access clarification (confirmed)

**The skill does NOT run on the client.** The client only holds the SKILL.md
(instructions, small, on-demand). Execution happens server-side on
skill-runner. Call path for the recommended route:

```
client (pi/opencode/…)  →  LiteLLM (public, :4000 / llm.choukalos.com)
   →  mcp_skills MCP server (internal)
   →  skill-runner (internal, :8091)   ← executes skill.py (LLM + MCP tools + data)
   ←  result / artifact back up the chain
```

- **Only LiteLLM is a public surface** (already public). skill-runner (8091)
  stays **internal/LAN-only** — clients never call it directly. Skills are
  "publicly accessible" in the sense that any client that can reach LiteLLM
  can invoke them; the skill-runner API itself is never exposed.
- The "direct curl to skill-runner" fallback (in SKILL.md) is only for LAN
  clients that can't use MCP; remote/public clients always go via LiteLLM.
- The 9 MCP tools are used in two independent ways: (a) the client uses them
  directly via LiteLLM for general agent work; (b) skill-runner uses them
  server-side while executing a skill. Both go through LiteLLM.

### Per-user identity threading (requirement 4) — verified viable

skill-runner already resolves `X-API-Key` → `user_id` via `MEMORY_USER_KEYS`
(`user_id=ENV_VAR` map; unknown key → `unknown`, never a real user).
To keep per-user attribution through the MCP path:

1. Client authenticates to LiteLLM with the end user's LiteLLM key
   (`Authorization: Bearer <key>`).
2. Configure the `mcp_skills` server in LiteLLM with
   `extra_headers: ["Authorization"]` (or a custom header). For a plain
   non-OAuth MCP server LiteLLM forwards the caller's `Authorization`
   upstream (strip logic `_should_strip_caller_authorization` returns False
   for non-OAuth servers).
3. `mcp_skills` reads the forwarded key and passes it to skill-runner as
   `X-API-Key`; skill-runner's `resolve_user_id()` maps it to the user.

**One config-alignment decision:** the per-user LiteLLM keys (auth_todo.md
v2) must be the same keys (or map to the same env vars) that skill-runner's
`MEMORY_USER_KEYS` recognizes — otherwise MCP-invoked jobs attribute to
`unknown`. Owner: user (auth_todo.md v2).
## 7. Durable job index: MySQL, not SQLite (2026-08-29)

**Decision (Chuck):** back the durable job index with **MySQL** (installed
baremetal on thor) instead of the originally-planned single SQLite file.
Rationale: MySQL is already a core, managed part of the homelab; a shared
table is easier to inspect/backup/monitor than a per-container `.db` file,
and it removes the `jobs.db` volume from the skill-runner compose project.

**Where:** the `homelab` database (the `ai` MySQL user has `ALL PRIVILEGES ON
homelab.*`, so the table auto-creates if missing). The other DBs are not used:
`ai_harness` (not needed) and the existing `homelab` workflow/checkpoint tables
(`workflows`, `workflow_runs`, `workflow_steps`, `checkpoints`, `checkpoint_*`)
are leftovers from the bailed-on workflow/checkpoint work and are left alone.

**Table** `homelab.skill_jobs` (auto-created by the runner at startup):

```
job_id     VARCHAR(64)   PRIMARY KEY
skill      VARCHAR(128)  NOT NULL
status     VARCHAR(32)   NOT NULL
created_at VARCHAR(64)   NOT NULL
updated_at VARCHAR(64)   NOT NULL
data       LONGTEXT      NOT NULL   -- full Job JSON (model_dump_json)
```
ENGINE=InnoDB, utf8mb4. Write-through on every status change
(`INSERT … ON DUPLICATE KEY UPDATE`); hydrated into the in-memory `jobs` dict
at startup (terminal-state jobs stay queryable; in-flight jobs from a prior
run are marked `interrupted`). Best-effort: if MySQL is unreachable the runner
degrades to in-memory-only and never crashes.

**Creds (from `.env`, gitignored):** `MYSQL_DB_HOST` (thor.local) : `3306`,
`AI_DB_NAME` (homelab), `AI_DB_USER` / `AI_DB_PASS`. Wired into the
skill-runner compose `environment:` (replacing the old `JOBS_DB_PATH` env +
`jobs.db` volume). Dep: `pymysql>=1.1.0` (Dockerfile + pyproject).

**Verified (2026-08-29, against the live `homelab` DB):** table auto-creates;
persist → hydrate round-trip works across a fresh process; a `completed` job
stays `completed` and a `running` job is correctly marked `interrupted`
("Interrupted by runner restart"). Test rows cleaned up after.

### Command correction (homelab.sh)
The skill-runner-only rebuild/restart is:
```
./homelab.sh rebuild skill-only
```
(`COMMAND=$1`=rebuild, `STACK=$2`=skill-only → `compose.skill-runner.yml` only:
`down` then `up -d --build --force-recreate --remove-orphans`.) This does **not**
touch LiteLLM or any other service. The full `./homelab.sh rebuild` is what
restarts LiteLLM (and would kill an active pi session), so it stays a manual
owner step.
