# Cross-Client Skills System

> How any client (pi, Claude Code, OpenCode, Open WebUI, Siri, n8n, any MCP
> client) lists and runs the homelab's skills through LiteLLM.
> Date: 2026-08-29 (Phases A–D complete)
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
skills (deep_research, morning_brief, siri_ask, … 12 total)
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

**Registered (2026-08-29):** all 12 skills, `source: git-subdir` →
`https://github.com/choukalos/homelab-ai-harness.git` / `agents-skills/<name>`,
`version: 1.0.0`, all **enabled**. `marketplace.json` lists 12 plugins.

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
description: <from skill.yml>
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
(`MEMORY_USER_KEYS`). See `auth_todo.md` for per-user key work (Phase 1 will
point the `chuck` pair at a personal key; currently `SIRI_API_KEY` resolves to
`service`).

---

## The 12 skills

| Skill | Primary input | max_runtime | Channels |
|---|---|---|---|
| `deep_research` | `query` | 900s | cli, pi, n8n |
| `demo_browse` | `query` | 30s | cli, pi, n8n |
| `demo_workflow` | `prompt` | 600s | cli, pi, n8n |
| `homelab_report` | `scope` | 120s | cli, pi, n8n |
| `investment_brief` | `user_email` | 300s | cli, pi, n8n |
| `morning_brief` | `interests` | 180s | cli, pi, n8n |
| `presentation_build` | `topic` | 300s | cli, pi, n8n |
| `presentation_update` | `presentation_title` | 300s | cli, pi, n8n |
| `publish_file` | `source_path` | 60s | cli, pi, n8n |
| `research_brief` | `topic` | 120s | cli, pi, n8n |
| `siri_ask` | `query` | 30s | siri |
| `siri_chat` | `query` | 120s | siri |

(`code_review` / `repo_maintenance` are TODO placeholders — no `skill.py`/
`skill.yml`, excluded from `GET /skills`.)

---

## Verified (2026-08-29)

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

## Manual steps (owner)

- Restart LiteLLM to pick up `mcp_servers.mcp_skills` (config change).
- Restart pi session to pick up the `agents-skills/` SKILL.md wrappers.
- Per-user keys (`auth_todo.md` Phase 1) for per-user attribution.