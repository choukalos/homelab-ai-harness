# Cross-Client Skills System

> How any client (pi, Claude Code, OpenCode, Open WebUI, Siri, n8n, any MCP
> client) lists and runs the homelab's skills through LiteLLM.
> Date: 2026-08-31 (Phases A–D + Phase 2/3 skills complete)
> Plan: `skills-todo.md` · this doc is the live-state reference.

**TL;DR** — skills are **server-side** (they run on `skill-runner`, never on the
client). The client only needs three MCP tools (`mcp_skills`) to list + run
them. Three layers provide access, in order of universality:

1. **`mcp_skills` MCP server** (universal — through LiteLLM) — list + run.
2. **LiteLLM Skill Hub** (universal — through LiteLLM) — system-prompt
   discovery (pi/Claude Code see the skills exist).
3. **`agents-skills/` SKILL.md wrappers** (per-machine) — `/skill:name`
   slash commands in pi + other Agent Skills harnesses.

---

## Architecture

```
Any client (pi / Claude Code / OpenCode / Open WebUI / Siri / n8n / MCP)
   │  (LiteLLM key; Authorization header)
   ▼
LiteLLM (:4000)  ── mcp_servers.mcp_skills (extra_headers: [Authorization])
   │  (forwards caller's Authorization)
   ▼
mcp_skills MCP server (:8000, ai-net)  ── 3 tools
   │  (X-API-Key: caller key for execution, service key for discovery)
   ▼
skill-runner (:8091)  ── GET /skills · POST /skills/{name} · GET /skills/jobs/{id}
   │  (identity: resolve_user_id(X-API-Key) → user_id)
   ▼
skills (deep_research, morning_brief, siri_ask, business_analyst, … 15 total)
```

Only **LiteLLM** is a public surface. `skill-runner` (8091) and `mcp_skills`
(8000) stay on `ai-net` (internal/LAN-only). No client ever talks to
skill-runner directly.

---

## Layer 1 — `mcp_skills` MCP server (universal list + run)

**Location:** `mcp/servers/skills/` (container `mcp_skills`, port 8000,
`ai-net`, NOT exposed to host). Compose: `compose/compose.mcp.yml`.

**Three meta-tools** (low context footprint — only 3 schemas always-on, not
15 per-skill tools):

| Tool | Args | Behavior |
|---|---|---|
| `list_skills` | — | `GET /skills` on skill-runner → `{count, skills:[{name, description, inputs[], max_runtime, channels[]}]}`. Discovery uses the **service key** (not user-specific). |
| `run_skill` | `name`, `prompt?`, `params?`, `max_wait?` | `POST /skills/{name}` — **synchronous** (blocks until terminal or approval gate). `prompt` auto-maps to the skill's primary string input (well-known names → required string → first string). `params` wins over `prompt`. `max_wait` defaults to the skill's `max_runtime` (else 180s); httpx timeout = `max_wait + 30`. Returns the final job (`job_id`, `status`, `summary`, `artifact_path`). On timeout → `RuntimeError` with a `job_id` hint. |
| `get_skill_job` | `job_id` | `GET /skills/jobs/{job_id}` → job status (for long-running jobs that returned a `job_id`). |

**Identity threading:** `_caller_key(ctx)` extracts the caller's LiteLLM key
from the `Authorization` header (LiteLLM forwards it via `extra_headers:
[Authorization]` — plain non-OAuth server, strip logic returns False).
- **Execution** (`run_skill` / `get_skill_job`): presents the **caller key**
  as `X-API-Key` → skill-runner's `resolve_user_id()` attributes the job to
  the right user. Falls back to the service key when absent.
- **Discovery** (`list_skills` / internal `GET /skills`): always the **service
  key** (`SKILL_RUNNER_API_KEY`) — the caller's key (e.g. the LiteLLM master)
  is not in skill-runner's allow-list. (Fixed 2026-08-29: discovery used the
  caller key → 403.)

**LiteLLM registration** (`litellm/config.yml` → `mcp_servers.mcp_skills`):
```yaml
mcp_skills:
  transport: http
  url: http://mcp_skills:8000/mcp
  allow_all_keys: true
  extra_headers: [Authorization]   # forward caller key for attribution
  timeout: 7200                     # run_skill blocks up to max_runtime (deep_research=900s)
```
Tools appear in LiteLLM prefixed with the server name: `mcp_skills-list_skills`,
`mcp_skills-run_skill`, `mcp_skills-get_skill_job`.

**Deps:** `mcp>=1.10,<2`, `httpx>=0.27`. Transport: streamable-http, path `/mcp`.

---

## Layer 2 — LiteLLM Skill Hub (universal discovery)

**Endpoints:** `/claude-code/marketplace.json` (GET), `/claude-code/plugins`
(POST register / GET list), `/claude-code/plugins/{name}/enable|disable`,
`/claude-code/plugins/{name}` (DELETE). Stored in `LiteLLM_ClaudeCodePluginTable`.

**Registered (2026-08-29; +3 on 2026-08-31):** all 15 skills, `source: git-subdir` →
`https://github.com/choukalos/homelab-ai-harness.git` / `agents-skills/<name>`,
`version: 1.0.0`, all **enabled**. `marketplace.json` lists 15 plugins.

**Registration note (2026-08-31):** the `litellm_skill_create` MCP tool
401s on create (its auth differs from the list endpoint). The working path is
the direct `POST /claude-code/plugins` endpoint with the LiteLLM master key
(payload: `name`, `version`, `description`, `source`, `keywords`, `category`).
The 3 Phase-2 skills (`business-analyst`, `content-writer`,
`marketing-strategy`) were registered this way on 2026-08-31.

**Effect:**
- **pi** (`pi-provider-litellm` `listSkills()`): fetches
  `/claude-code/marketplace.json` + `/v1/skills`, injects name+description into
  the system prompt as `<litellm_skills>` guidance. Works on **any machine**
  (no per-machine setup).
- **Claude Code:** `claude plugin marketplace add
  http://thor.local:4000/claude-code/marketplace.json` + install. (Caveat: a
  real Claude Code *plugin* needs a `.claude-plugin/plugin.json` layout; a bare
  SKILL.md dir is useful as a *skill* — covered by Layer 3.)

**Note:** `/v1/skills` (legacy Skills Gateway) requires an Anthropic API key
(not configured) — the Skill Hub (`/claude-code/*`) is the working path.

---

## Layer 3 — `agents-skills/` SKILL.md wrappers (per-machine slash commands)

**Location:** `agents-skills/` in the repo (committed to GitHub). One dir per
skill, each with `agents-skills/<hyphenated-name>/SKILL.md` (standard Agent
Skills layout — portable across pi / Claude Code / OpenCode / Codex).

**SKILL.md shape:**
```markdown
---
name: morning-brief          # hyphenated (Agent Skills rule)
description: <from skill.yml>   # MUST be strict-parseable YAML — see rule below
---
# Morning Brief
<description>
## How to run
Call the `mcp_skills` MCP tool `run_skill` with `name: morning_brief` (underscore),
`prompt: <user request>`, optional `params`.
## Inputs
| Input | Type | Required | Default | Description |
## Example
/skill:morning-brief <topic>
```

**YAML frontmatter rule (2026-09-01):** the frontmatter is parsed by clients
(pi, Claude Code, …) with a strict YAML parser. A `description` value containing
an unquoted `: ` (colon + space) is invalid — YAML reads it as a nested mapping
(`"Nested mappings are not allowed in compact mappings"`), and the client fails
to load the skill. Either **quote** the value or **reword** it (the repo
convention is to reword with an em dash, e.g. `Investment brief — portfolio
status, …`). Keep the SKILL.md description identical to the `skills/<name>/
skill.yml` source of truth. Guardrail: `tests/test_skills_yaml.py` (7 checks:
strict YAML parse, name/dir match, skill.yml validity, source/wrapper
description parity, regression cases) is wired into the pre-commit hook
(`.githooks/pre-commit`, activate with `git config core.hooksPath .githooks`).

**Install on a machine (pi):** `~/.pi/agent/settings.json`
```json
{ "enableSkillCommands": true, "skills": ["/path/to/homelab-ai-harness/agents-skills"] }
```
Then restart pi. `/skill:<name> <prompt>` loads the SKILL.md (which tells the
agent to call `run_skill`) and executes the skill.

**Per-machine caveat:** the `/skill` slash command lists **local** skills only
(the SKILL.md must be on the machine). The Skill Hub (Layer 2) puts the skills
in the system prompt on any machine, but does NOT add them to the `/skill` list.
To get slash commands on a new machine: clone the repo (or copy
`agents-skills/`) + add to pi settings + restart.

---

## Durable job index (MySQL)

Job state is **durable** (survives skill-runner restarts) — backed by MySQL
`homelab.skill_jobs` (not in-memory-only).

- **Table:** `homelab.skill_jobs` — `job_id` (PK), `skill`, `status`,
  `created_at`, `updated_at`, `data` (LONGTEXT, full job JSON).
- **Persist points:** at start (`running`), completion, approval gate, cancel,
  interrupt. Upsert (`INSERT ... ON DUPLICATE KEY UPDATE`).
- **Hydration:** on startup, `_hydrate_jobs()` loads recent jobs into memory.
- **Interrupt semantics:** a job still `running`/`pending` when the runner
  restarts is marked `interrupted` (terminal).
- **Best-effort:** if MySQL is unreachable, the runner degrades to
  in-memory-only (non-fatal).
- **Creds:** `AI_DB_*` env (bare-metal MySQL on Thor, `homelab` DB, `ai@%`
  user). Deps: `pymysql>=1.1.0`.

**Job statuses:** `pending`, `running`, `completed`, `failed`,
`awaiting_approval`, `cancelled`, `interrupted`. Terminal: `completed`,
`failed`, `cancelled`, `interrupted`.

---

## skill-runner API (full)

```
GET  /skills                          — list skills (name, description, inputs, max_runtime, channels)
POST /skills/{skill_name}             — launch a skill job (synchronous: blocks until terminal or approval gate)
GET  /skills/jobs/{job_id}            — get job status (durable: survives restarts)
GET  /skills/jobs/{job_id}/artifact   — retrieve artifact file
POST /skills/jobs/{job_id}/approve    — approve a job at an approval gate
POST /skills/jobs/{job_id}/cancel     — cancel a job
POST /api/chat                        — unified chat with intent detection
GET  /api/jobs/{job_id}               — poll async job status (chat gateway)
POST /api/schedule                    — create a recurring schedule
GET  /api/schedule                    — list all schedules
DELETE /api/schedule/{id}             — remove a schedule
POST /api/schedule/{id}/run-now       — trigger a schedule immediately
```

**Auth:** `SKILL_RUNNER_API_KEY` (comma-separated allow-list; enforced when
set, open when unset). `GET /skills` mirrors `/api/chat` auth.

**Identity:** `X-API-Key` → `user_id` via `memory/identity.py`
(`MEMORY_USER_KEYS`). Per-user key attribution is **complete (2026-09-04/06;
plan closed 2026-09-10)**: one key per user (`LITELLM_KEY_CHUCK` → `chuck`,
`LITELLM_KEY_DYLAN` → `dylan`) — the same value works for LiteLLM and
Siri/skills; Caddy OR-gate accepts chuck / dylan / legacy keys;
`AUTH_KEY_THREADING_ENABLED=true` threads the caller's key to LiteLLM so spend
is attributed per user (verified live: `user="chuck"` series in LiteLLM
metrics incl. pi + skill-runner traffic; scheduler/n8n stays on the master key
by owner decision). Plan file `auth_todo.md` deleted 2026-09-10 — state lives
here + `docs/memory/IMPLEMENTATION_STATE.md`.

---

## The 15 skills

| Skill | Primary input | max_runtime | Channels | Added |
|---|---|---|---|---|
| `deep_research` | `query` | 900s | cli, pi, n8n | baseline |
| `demo_browse` | `query` | 30s | cli, pi, n8n | baseline |
| `demo_workflow` | `prompt` | 600s | cli, pi, n8n | baseline |
| `homelab_report` | `scope` | 120s | cli, pi, n8n | baseline |
| `investment_brief` | `user_email` | 300s | cli, pi, n8n | baseline |
| `morning_brief` | `interests` | 180s | cli, pi, n8n | baseline |
| `presentation_build` | `topic` | 300s | cli, pi, n8n | baseline |
| `presentation_update` | `presentation_title` | 300s | cli, pi, n8n | baseline |
| `publish_file` | `source_path` | 60s | cli, pi, n8n | baseline |
| `research_brief` | `topic` | 120s | cli, pi, n8n | baseline |
| `siri_ask` | `query` | 30s | siri | baseline |
| `siri_chat` | `query` | 120s | siri | baseline |
| `business_analyst` | `prompt` | 300s | cli, pi, n8n, siri | 2026-08-31 (Phase 2) |
| `content_writer` | `prompt` | 480s | cli, pi, n8n, siri | 2026-08-31 (Phase 2) |
| `marketing_strategy` | `prompt` | 300s | cli, pi, n8n, siri | 2026-08-31 (Phase 2) |

(`code_review` / `repo_maintenance` are TODO placeholders — no `skill.py`/
`skill.yml`, excluded from `GET /skills`.)

---

## Verified (2026-08-29 + 2026-08-31)

- **Phase A:** durable MySQL job index (persist-at-start, restart survival,
  interrupted-marking) — live-verified against the real `homelab` DB.
- **Phase B:** `mcp_skills` MCP server — 3 tools registered in LiteLLM;
  `list_skills` (12 skills), `run_skill` (morning_brief, siri_ask completed),
  `get_skill_job` (job retrieval), identity threading (X-API-Key → `service`)
  — all verified **through LiteLLM**.
- **Phase C:** `agents-skills/` (12 SKILL.md) + pi settings (`enableSkillCommands`
  + `skills` array).
- **Phase D:** 12 skills registered + enabled in the LiteLLM Skill Hub
  (`marketplace.json`).
- **Phase 2 (2026-08-31):** 3 new agent skills added — `business_analyst`
  (NL→SQL over `mcp_mysql`, Markdown report + Grafana suggestions),
  `content_writer` (social/blog/video content packs via `mcp_search` research),
  `marketing_strategy` (GTM launch plan via `mcp_search` research). All 3
  verified end-to-end through the MCP gateway (`run_skill` → completed, artifact
  saved) and via the Siri `/api/chat` intent dispatch (jobs `06ffabc27f37`,
  `4be340c16ba9`, `62f5250b9f43` — all completed with artifacts).
- **Phase 3 (2026-08-31):** cross-client QA — all 3 new skills registered in the
  LiteLLM Skill Hub (`marketplace.json` now 15 plugins) + `agents-skills/`
  SKILL.md wrappers on `origin/main`; verified in pi's skill list +
  `<litellm_skills>` prompt section and the Claude Code marketplace. Siri intent
  dispatch wired (see fix log).
- **Per-user keys & attribution (2026-09-04/06, plan closed 2026-09-10):**
  one key per user (chuck/dylan) for LiteLLM + Siri/skills; proxy DB holds
  exactly 3 keys (chuck, dylan, memory-service); Caddy OR-gate (chuck/dylan/
  legacy → 200, invalid → 401); `AUTH_KEY_THREADING_ENABLED=true` live-verified
  (per-user `user="chuck"` series in LiteLLM metrics, incl. Mac pi +
  skill-runner traffic); Grafana per-user Key Usage panels in place. Plan files
  `auth_todo.md` + `TODO.md` deleted 2026-09-10.

## Manual steps (owner)

- Restart LiteLLM to pick up `mcp_servers.mcp_skills` (config change).
- Restart pi session to pick up the `agents-skills/` SKILL.md wrappers.
- Rebuild the skill-runner after `skills/runner/main.py` changes
  (`./homelab.sh rebuild skill-only`) — `main.py` is baked into the image
  (`COPY main.py .`), not volume-mounted. Skill modules under
  `skills/<name>/` ARE mounted (live edits, no rebuild).
- Register new skills in the LiteLLM Skill Hub via `POST /claude-code/plugins`
  (the `litellm_skill_create` MCP tool 401s on create).

## Fix log

- **2026-09-01 — pi.dev `[Skill conflicts]` / YAML parse failure.**
  `investment-brief` + `morning-brief` SKILL.md frontmatter had unquoted `: `
  in `description` → strict YAML parsers rejected the file. Reworded both
  descriptions (em dash instead of colon) in SKILL.md + skill.yml, re-registered
  the two Skill Hub plugins with the new descriptions, added
  `tests/test_skills_yaml.py` + `.githooks/pre-commit` guardrail.
- **2026-08-31 — `mcp_skills` stale + malformed service key.** Container held a
  pre-rotation key AND sent the comma-joined allow-list as a single
  `X-API-Key` (skill-runner exact-matches the split list → 403). Fix:
  `compose/compose.mcp.yml` `SKILL_RUNNER_API_KEY=${LITELLM_KEY_CHUCK}` (single
  key) + container recreated.
- **2026-08-31 — runner LLM per-call timeout too short.** The runner's
  `LiteLLMClient` (gateway mode) defaulted to **120s**, but heavy `matrix-coder`
  synthesis calls exceed it. Fix: `skills/runner/main.py` `LLM_CALL_TIMEOUT` env
  (default **240s**), passed to the client. Skill-runner rebuilt.
- **2026-08-31 — `content_writer` max_runtime too short.** 3 sequential format
  calls (~110s each) exceeded the 300s budget. Fix: `MAX_RUNTIME_SECS` default
  **480s** (`skill.py` + `skill.yml`).
- **2026-08-31 — reasoning-model empty content.** `matrix-coder` sometimes
  returns `content: None` (output in `reasoning_content`). Fix:
  `content_writer` + `marketing_strategy` LLM-output extraction falls back to
  `reasoning_content` (same fix as `demo_workflow`).
- **2026-08-31 — Siri intent dispatch for the 3 new skills.** Added
  `business-analyst` / `content-writer` / `marketing-strategy` to
  `_INTENT_SKILL_MAP` + keyword detection + `_PROMPT_INPUT_SKILLS` (dispatch
  `prompt` not `query`) + `_SKILL_TIMEOUTS` (business_analyst 330s,
  content_writer 510s, marketing_strategy 330s — the default 120s watchdog
  killed the slow reasoning-model jobs). `siri` added to the 3 skills'
  `channels`. Skill-runner rebuilt.
- **2026-08-31 — Skill Hub registration 401.** `litellm_skill_create` MCP tool
  401s on create; the direct `POST /claude-code/plugins` endpoint with the
  master key works. The 3 Phase-2 skills were registered this way.
