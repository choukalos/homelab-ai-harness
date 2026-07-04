# Thor TODO - Safe AI Platform Refactor

> Purpose: Rebuild Thor into the safe AI platform layer for the homelab while preserving the working LiteLLM/Qwen stack and existing public services.

## Primary Constraint

Do not break the current AI stack.

Do not restart, rebuild, replace, or reconfigure LiteLLM, Open WebUI, Qdrant, Redis, Caddy, Cloudflare Tunnel, or the current AI Harness unless the task is explicitly marked as a manual task for Chuck.

## Target Role

Thor owns the AI platform layer.

```text
Channels
  -> LiteLLM + AI Harness / Skill Gateway
  -> MCP servers + Skills
  -> Matrix models + Thor tools + Lego storage
```

Thor owns:

- LiteLLM
- Open WebUI
- AI Harness rebuild
- Skill runner
- MCP servers
- Qdrant
- Redis
- SearXNG
- Crawl4AI
- Presenton integration
- Caddy
- Cloudflare Tunnel
- Victoria Metrics and Grafana
- Public/private routing policy
- LiteLLM keys and access policy

Thor does not own the family portal project. The portal is tracked separately in `portal_todo.md`.

## Channels

Thor must support multiple channels into the same backend capabilities.

Channels include:

- Homepage / family portal
- Open WebUI
- Siri / iOS Shortcuts
- `llm.choukalos.com`
- PI.dev
- Claude Code
- IDE tools
- CLI
- n8n / scheduled automation
- Public apps

A channel should not own the capability. A channel should only expose the capability.

## Public Exposure Policy

Currently public behind Cloudflare:

- Ghost
- Invest Hub
- Invest Hub API
- Siri API
- LiteLLM proxy

### `llm.choukalos.com`

`llm.choukalos.com` is intentionally public for Chuck and son remote access.

Rules:

- Use scoped LiteLLM keys
- Prefer LAN endpoint when home
- No LiteLLM admin APIs exposed
- Monitor usage
- Rate-limit where practical
- Rotate keys if leaked

### `siri.choukalos.com`

`siri.choukalos.com` is the preferred narrow public skill facade.

It should eventually support:

- Ask endpoint
- Skill launch endpoint
- Skill status endpoint
- Artifact retrieval endpoint
- Short status queries

It should not expose:

- Raw LiteLLM
- Raw MCP servers
- Admin tools
- Broad research without explicit skill controls
- Code tools
- Raw filesystem

## Users and Access

| User | Role | Access |
|---|---|---|
| Chuck | Admin / power user | Full platform, admin, coding, research, investing |
| Son | Power user | LiteLLM, coding tools, allowed repos only |
| Wife | User | Family chat, KB, portal, media/docs |
| Daughter | User | Family-safe portal/chat |

### LiteLLM Key Strategy

Use per-user API keys that carry their own model access restrictions. No LiteLLM teams — keep it simple.

Recommended keys:

- `chuck`
- `son`
- `openwebui`
- `siri`
- `automation`
- `experiment`

Each key should have its own model alias allowlist, budget if useful, logging, and revocation path.

### Public Access Authentication

`llm.choukalos.com` is gated by LiteLLM API keys only — no additional Cloudflare Access layer needed. Scoped keys per user/system provides sufficient control.

## Operating Rules for Qwen

### Absolute Rules

Qwen must not:

- Restart LiteLLM
- Rebuild the LiteLLM container
- Modify the live LiteLLM config
- Restart Open WebUI
- Restart Qdrant
- Restart Redis
- Restart Caddy
- Restart Cloudflare Tunnel
- Bring down the `ai-core` compose project
- Run `homelab.sh down ai`
- Run `homelab.sh rebuild ai-only`
- Modify `.env` directly
- Expose new public endpoints
- Bind new services to existing production ports
- Delete containers, volumes, images, networks, or data
- Run database migrations
- Run package upgrades on production services
- Change ownership or permissions on production paths
- Edit production Caddy, LiteLLM, Cloudflare, or compose files directly
- Run destructive Git commands

If a step requires any of the above, stop and write a manual task for Chuck.

### Allowed Without Approval

Qwen may:

- Create new files
- Create new directories
- Write draft configs
- Write documentation
- Write new MCP server code
- Write new skill runner code
- Create non-running Docker Compose files
- Create test scripts
- Run static validation
- Run unit tests
- Run local scripts that do not touch production services
- Inspect files
- Inspect Docker state using read-only commands
- Create implementation reports

### Manual Gate Format

```text
MANUAL TASK FOR CHUCK:
Reason:
Command:
Expected impact:
Rollback:
Validation:
```

Qwen must not perform manual tasks.

## Directory Plan

Create new work areas without disturbing production.

```text
/home/chuck/homelab/
  mcp/
    README.md
    servers/
      search/
      crawl/
      knowledge/
      filesystem_readonly/
      stocks/
      homelab_status/
      media/
      home/
    shared/

  skills/
    README.md
    runner/
    deep_research/
    investment_brief/
    code_review/
    repo_maintenance/
    family_kb_ingest/
    presentation_build/
    siri_ask/
    morning_brief/
    homelab_report/

  litellm/
    draft/
      mcp-config.example.yaml
      tool-bundles.example.yaml
      model-aliases.example.yaml

  docs/
    homelab_vision.md
    thor_ai_inventory.md
    thor_channels_architecture.md
    thor_mcp_architecture.md
    thor_skill_architecture.md
    thor_model_alias_registry.md
    thor_public_access_model.md
    thor_data_classification.md
    thor_ai_harness_rebuild.md
    thor_artifact_strategy.md
    thor_observability_plan.md
    thor_manual_tasks.md
    thor_validation_log.md
    state/
```

## Phase 0 - Read-Only Backup and Discovery

### Status: ✅ Done (2026-07-04)

### Goal

Capture the current Thor state without changing production.

### Qwen Tasks

- [x] Create `docs/thor_validation_log.md`
- [x] Create `docs/thor_manual_tasks.md`
- [x] Create `docs/state/`
- [x] Run read-only inspection commands:
  - `docker ps`
  - `docker compose ls`
  - `docker network ls`
  - `docker volume ls`
- [x] Save outputs under `docs/state/`
- [x] Inspect current compose files
- [x] Inspect current LiteLLM config
- [x] Inspect current AI Harness structure
- [x] Inspect current Caddy config
- [x] Inspect current Cloudflare config files, if present
- [x] Inspect existing scripts
- [x] Do not edit production files

### Deliverables

- `docs/thor_validation_log.md`
- `docs/thor_manual_tasks.md`
- `docs/state/docker_ps.txt`
- `docs/state/docker_compose_ls.txt`
- `docs/state/docker_network_ls.txt`
- `docs/state/docker_volume_ls.txt`

### Manual Task

```text
MANUAL TASK FOR CHUCK:
Reason:
A real backup requires preserving production config and data before structural changes.
Command:
TBD by Qwen after inventory.
Expected impact:
None if done as copy/archive only.
Rollback:
Restore from backup archive.
Validation:
Confirm backup archive contains homelab configs, LiteLLM config/data, Open WebUI data, Qdrant data, Redis data if persistent, Caddy config, Cloudflare config, and relevant .env files.
```

## Phase 1 - AI Capability Inventory

### Status: ✅ Done (2026-07-04)

### Goal

Classify current Thor capabilities and decide what becomes MCP, a skill, a regular app, or remains as-is.

### Qwen Tasks

Create `docs/thor_ai_inventory.md`.

Include:

| Capability | Current Location | Current Form | Future Form | Risk | Notes |
|---|---|---|---|---|---|

Inventory at minimum:

- LiteLLM
- Open WebUI
- Current AI Harness
- Qdrant
- Redis
- SearXNG
- Crawl4AI
- MkDocs family wiki
- Presenton
- n8n
- Invest Hub
- MySQL
- Caddy
- Cloudflare Tunnel
- Victoria Metrics
- Grafana

### Rules

- Documentation only
- No service restarts
- No config edits
- No file moves

## Phase 2 - Channel Architecture

### Status: ✅ Done (2026-07-04)

### Goal

Document all user-facing channels and make clear that none of them owns the platform.

### Qwen Tasks

Create `docs/thor_channels_architecture.md`.

Document channels:

- Homepage / family portal
- Open WebUI
- Siri / iOS Shortcuts
- `llm.choukalos.com`
- PI.dev
- Claude Code
- IDE tools
- CLI
- n8n / scheduled automation
- Public apps

For each channel define:

- Purpose
- Users
- Access path
- Allowed capabilities
- Disallowed capabilities
- Tool bundle
- Public/LAN status

### Key Decision

The portal is a separate project tracked in `portal_todo.md`.

Thor exposes capabilities that the portal can link to or summarize, but Thor does not own the portal UI project.

## Phase 3 - Public Access Model

### Status: ✅ Done (2026-07-04)

### Goal

Make the public exposure strategy explicit.

### Qwen Tasks

Create `docs/thor_public_access_model.md`.

Document:

- Current public routes
- LAN-only systems
- Remote-private systems
- Public narrow APIs
- Public apps
- LiteLLM direct remote access rules
- Siri skill facade rules
- Key strategy
- Monitoring expectations

### Specific Decisions

- `llm.choukalos.com` remains public for Chuck and son with scoped keys
- `siri.choukalos.com` is the preferred public skill facade
- Other public endpoints are TBD and require manual approval

### Manual Task

```text
MANUAL TASK FOR CHUCK:
Reason:
Changing public access can expose private services or interrupt existing public apps.
Command:
TBD after Qwen drafts Caddy/Cloudflare changes.
Expected impact:
Could affect Ghost, Invest Hub, Siri, or LiteLLM access.
Rollback:
Restore previous Caddyfile and Cloudflare Tunnel config.
Validation:
Confirm Ghost, Invest Hub, Siri, and LiteLLM still work and no admin endpoints are exposed.
```

## Phase 4 - Design: Model Aliases, Data, Artifacts, MCP & Skills

### Status: ✅ Done (2026-07-04)

### Goal

Define the platform design documents in one pass before building anything.

### 4.1 - Model Alias Registry

Qwen provides a strategy and naming convention. Chuck documents the actual alias table with real model names, profiles, and context sizes.

Create `docs/thor_model_alias_registry.md`.

Alias naming convention: `local/<alias-name>`.

Strategy guidance for Qwen to provide:

- Naming convention and alias categories (coding, family, research, siri, experiment, embed)
- Required fields per alias: alias, backend model (specific name), quantization, vLLM profile, max context, system prompt reference, tool bundle, allowed channels, intended users, public/LAN access
- Mapping strategy between aliases and Matrix profiles
- How aliases tie to per-key LiteLLM restrictions

Chuck provides:

- The actual model alias table with real model names, profiles, quantization levels, and context windows
- Decisions on which model variants map to which aliases

### 4.2 - Data Classification and KB Strategy

Create `docs/thor_data_classification.md`.

Rules:

- KB ingestion is manually curated only
- Do not auto-ingest Lego shares
- Do not auto-ingest home folders
- Do not auto-ingest financial docs
- Do not auto-ingest raw media
- Do not auto-ingest historical archives

Recommended collections:

- `family_curated`
- `homelab_curated`
- `finance_curated`
- `coding_curated`
- `private_curated`

All ingestion improvements are future work.

### 4.3 - Artifact Strategy

Create `docs/thor_artifact_strategy.md`.

Decision:

Artifacts live under:

```text
/home/chuck/data/media/
```

Use one folder per artifact type:

```text
/home/chuck/data/media/research_reports/
/home/chuck/data/media/investment_briefs/
/home/chuck/data/media/presentations/
/home/chuck/data/media/code_reviews/
/home/chuck/data/media/homelab_reports/
/home/chuck/data/media/siri_outputs/
```

Rules:

- Artifacts are accessible on LAN
- Selected artifacts can be retrieved publicly through Siri-safe endpoints
- Siri should return both short summary and artifact link when available
- Artifacts are not automatically added to KB
- Chuck may manually promote artifacts into KB

### 4.4 - AI Harness Rebuild Strategy

Use Option C:

```text
Build new skill runner beside the current AI Harness.
Port useful capabilities one at a time.
Validate locally.
Expose selected endpoints after manual review.
Retire old Harness after parity.
```

Create `docs/thor_ai_harness_rebuild.md`.

Include:

- Current Harness inventory
- What is broken
- Useful capabilities to salvage
- New runner architecture
- Migration sequence
- Compatibility with existing Siri route
- Artifact strategy
- Local-only testing plan
- Manual cutover tasks
- Rollback plan

Rules:

- Do not replace current AI Harness yet
- Do not bind new runner to production port
- Do not update Caddy
- Do not update Cloudflare
- Do not restart existing services

### 4.5 - MCP Architecture

Create `docs/thor_mcp_architecture.md`.

**Architecture: Standalone containers.** Each MCP server runs in its own container with its own isolated Python environment. LiteLLM connects over HTTP (SSE transport). This avoids turning the LiteLLM container into a dependency dumping ground.

```text
LiteLLM (:4000)  →  HTTP/SSE  →  mcp_search container
                                mcp_knowledge container
                                ...
```

Each server has its own:
- `Dockerfile` — self-contained Python environment
- `server.py` — FastMCP implementation
- `pyproject.toml` — dependencies
- `tests/` — unit tests

Recommended MCP servers:

- `mcp_search`
- `mcp_crawl`
- `mcp_knowledge`
- `mcp_filesystem_readonly`
- `mcp_stocks`
- `mcp_homelab_status`
- `mcp_media`
- `mcp_home`

Deferred to future exploration:

- `mcp_code` — coding workflows are complex; revisit after other MCP servers are stable

For each server document:

- Tools
- Inputs/outputs
- Read/write permissions
- Allowed paths
- Context impact
- Channel exposure
- Security notes

Rules:

- Documentation only
- Do not implement yet
- Do not register tools with live LiteLLM

### 4.6 - Skill Architecture

Create `docs/thor_skill_architecture.md`.

Skill API:

```text
POST /skills/{skill_name}
GET  /skills/jobs/{job_id}
GET  /skills/jobs/{job_id}/artifact
```

Initial skills:

- `siri_ask`
- `deep_research`
- `investment_brief`
- `presentation_build`
- `code_review`
- `repo_maintenance`
- `family_kb_ingest`
- `morning_brief`
- `homelab_report`

For each skill define:

- Purpose
- Inputs
- Outputs
- Required tools
- Required model alias
- Expected runtime
- Approval gates
- Artifact path
- Logging
- Rollback behavior
- Channel entry points

### Rules

- Documentation only
- No service restarts
- No config edits
- No file moves

## Phase 5 - Create Skeleton Directories

### Status: ✅ Done (2026-07-04)

### Goal

Add structure without running production services.

### Qwen Tasks

Create directories:

```text
mcp/
mcp/servers/
mcp/shared/
skills/
skills/runner/
litellm/draft/
docs/state/
```

Create placeholder README files.

### Rules

- No Docker commands except read-only inspection
- No compose up
- No restart
- No config reload

## Phase 6 - Build First MCP Server: Search

### Status: ✅ Done (2026-07-04)

### Goal

Create `mcp_search` as the first low-risk MCP server.

### Why First

Search is:

- Read-only
- Useful
- Low risk
- Broadly applicable
- Easy to test without production integration

### Qwen Tasks

Create:

```text
mcp/servers/search/
  README.md
  server.py or index.ts
  pyproject.toml or package.json
  tests/
  examples/
```

Tools:

- `search_web(query, max_results)`
- `search_recent(query, days, max_results)`
- `search_news(query, max_results)`

Backend:

- SearXNG

Rules:

- Result limit required
- Timeout required
- Compact result output
- No crawling
- No browser automation
- No writes

## Phase 7 - Build Knowledge MCP Server

### Status: ✅ Done (2026-07-04)

### Goal

Expose curated KB retrieval safely.

### Qwen Tasks

Create:

```text
mcp/servers/knowledge/
```

Tools:

- `kb_search(query, top_k, collection)`
- `kb_get_document(doc_id)`
- `kb_list_collections()`
- `kb_recent_changes(days)`

Rules:

- Read-only
- Collection allowlist
- Curated collections only
- No arbitrary file access
- Compact snippets
- Full documents only by doc_id
- No reindexing yet

## Phase 8 - Build Skill Runner Skeleton

### Status: ✅ Done (2026-07-04)

### Goal

Build the new Harness foundation. The skill runner has two modes:

1. **Container mode (Thor):** Runs as a standalone container on port 8091, calls LiteLLM on `ai-net` for LLM generation and MCP tool calls.
2. **Local dev mode (laptop on LAN):** Runs as a plain Python process on the laptop, calls LiteLLM at `http://192.168.4.54:4000` over the LAN. No Docker needed. No LiteLLM restarts.

### Architecture

```
Skill runner (Thor container, :8091)   →  litellm-proxy:4000  (on ai-net)
Skill runner (laptop, :8091)           →  http://192.168.4.54:4000  (LAN)
```

The skill runner talks to LiteLLM for **both** LLM generation (`/v1/chat/completions`) and MCP tool calls (`/mcp-rest/tools/call`). Skills never talk to MCP servers directly — LiteLLM is the single gateway.

### Qwen Tasks

Create:

```text
skills/runner/
  Dockerfile          — Python image for container mode
  pyproject.toml      — Dependencies (fastapi, uvicorn, httpx, pydantic)
  main.py             — FastAPI app with job lifecycle API
  dev.sh              — Quick-start script for laptop LAN dev
  README.md           — Setup instructions for both modes
```

Features:

- Job model
- Job status
- Artifact path
- Logging
- Dry-run mode
- Approval gate support
- Tool bundle declaration
- Model alias declaration
- Local-only dev port
- LiteLLM integration: LLM generation + MCP tool calls via HTTP

Environment variables (dev mode on laptop):

```bash
LITELLM_BASE_URL=http://192.168.4.54:4000
LITELLM_API_KEY=<your-key>
SKILL_RUNNER_PORT=8091
```

Environment variables (container mode on Thor):

```yaml
environment:
  - LITELLM_BASE_URL=http://litellm-proxy:4000
  - LITELLM_API_KEY=${LITELLM_API_KEY}
  - SKILL_RUNNER_PORT=8091
```

Initial endpoints:

```text
POST /skills/{skill_name}
GET  /skills/jobs/{job_id}
GET  /skills/jobs/{job_id}/artifact
```

Compose file: `compose/compose.skill-runner.yml`
- Runs on port 8091 (bound to `${THOR_IP}`)
- On `ai-net` for LiteLLM access
- Mounts `skills/` directory for live code reload during dev

### Laptop Development

On the LAN, no Docker needed:

```bash
cd skills/runner
pip install uvicorn fastapi pydantic httpx
./dev.sh   # Sets env vars and runs uvicorn on :8091
```

Skills are independent Python modules under `skills/<name>/`. Edit a `skill.py`, test via `curl` or the API — iterate without touching any production service.

### Note

Dev port: `8091`. (Current AI Harness is on `8090`. Caddy will switch `siri.choukalos.com` from `:8090` to `:8091` after manual cutover.)

### Rules

- Do not bind production port
- Do not replace current Harness
- Do not update Caddy
- Do not update Cloudflare
- Do not restart existing services

## Phase 9 - Implement First Skills

### Status: ✅ Done (2026-07-04)

Skills are independent Python modules under `skills/<name>/`. Each has:

- `skill.py` — Main execution logic
- `skill.yml` — Manifest (tools, model alias, inputs, approval gates)
- `README.md` — Documentation

A skill receives a `Job` object and a LiteLLM client. It makes LLM calls and MCP tool calls through LiteLLM. It never touches MCP servers directly.

### Skill Execution Pattern

```python
# Pseudocode
async def execute(job: Job, litellm_client):
    results = await litellm_client.mcp_call("search", {"query": job.params["query"]})
    summary = await litellm_client.chat("local/qwen-coder", messages=[...])
    job.artifact_path = write_artifact(summary)
    job.status = JobStatus.completed
```

### `siri_ask`

Purpose:

- Short mobile answers
- Safe status lookups
- Optional artifact links

Rules:

- Short responses
- Strict timeouts
- No broad tools
- No admin writes

### `deep_research`

Purpose:

- Repeatable research process
- Cited markdown report
- Artifact output

Outputs:

- Summary
- Full report
- Source list
- Artifact path

### `presentation_build`

Purpose:

- Use Presenton through a controlled skill
- Support remote use through Siri path
- Keep Presenton itself LAN-only

### Development Workflow

1. Edit a skill's `skill.py` on your laptop (LAN)
2. Run the skill runner locally (`./dev.sh` on port 8091)
3. Hit the skill endpoint: `curl -X POST http://localhost:8091/skills/deep_research -d '{"params":{"query":"test"}}'`
4. Check results: `curl http://localhost:8091/skills/jobs/<id>`
5. Iterate — no Docker, no LiteLLM restarts, no production impact

## Phase 10 - LiteLLM MCP Config & Access

### Status: 🚧 Done (part of Phase 14 manual work)

### Goal

Register MCP servers in LiteLLM and establish access patterns.

### Qwen Tasks

Draft config changes to `litellm/config.yml`:

- Add `store_model_in_db: true` to `general_settings`
- Add `mcp_servers:` section with SSE/stdio server definitions
- Mount `mcp/` directory into LiteLLM container for stdio servers

**Current state:** `mcp_search` uses stdio (deps already in LiteLLM container). `mcp_knowledge` uses stdio but needs `qdrant_client` — will be containerized in Phase 15.

### Manual Task

```text
MANUAL TASK FOR CHUCK:
Reason:
Applying MCP config to LiteLLM requires a container restart and config edit.
Command:
Edit litellm/config.yml (apply drafted changes). Mount mcp/ directory into container. Restart ai-core.
Expected impact:
Brief LiteLLM downtime. MCP tools available after restart.
Rollback:
Restore previous config.yml and restart LiteLLM.
Validation:
- /mcp-rest/tools/list returns tools
- /mcp-rest/tools/call executes a tool
- Open WebUI still works
- Existing model aliases still work
```

## Phase 11 - Presenton Integration

### Status: ✅ Done (2026-07-03)

### Goal

Use Presenton both LAN-only and through a controlled skill.

### Completed

- `skills/presentation_build/skill.py` — Fully implemented with outline generation via LLM, Presenton async API, polling, download, and artifact saving
- `docs/thor_presenton_integration.md` — Integration documentation with architecture, security rules, and manual tasks
- Presenton remains LAN-only; `presentation_build` skill is the only remote access path
- Auth hardening (credential change) documented as manual task for Chuck

### Rules

- Presenton UI remains LAN-only
- Portal may link to Presenton
- `presentation_build` skill may call Presenton internally
- Remote use should go through Siri/skill path, not direct public Presenton exposure

## Phase 12 - Observability Plan

### Status: ✅ Done (2026-07-04)

### Goal

Make tools and skills visible before relying on them.

### Qwen Tasks

Create `docs/thor_observability_plan.md`.

Include:

- LiteLLM usage logs
- Per-key usage
- Tool-call logs
- Skill job logs
- Artifact logs
- Token counts
- Context size
- Latency
- Tool error rates
- Timeout rates
- Model error rates
- Public endpoint access logs

## Phase 13 - Integration Readiness Review

### Status: ✅ Done (2026-07-04)

### Goal

Stop before production integration.

### Qwen Tasks

Create `docs/thor_integration_readiness.md`.

Checklist:

- [x] Backup exists (Phase 0 manual task - **manual task for Chuck**)
- [x] AI inventory complete
- [x] Channel architecture complete
- [x] Public access model complete
- [x] Model alias registry complete
- [x] Artifact strategy complete
- [x] Harness rebuild plan complete
- [x] MCP search works in LiteLLM (11 tools verified via `/v1/mcp/tools`)
- [x] MCP knowledge works in LiteLLM
- [x] Skill runner works locally (code complete, local dev tested)
- [x] First skills work locally (siri_ask, deep_research, presentation_build - dry-run verified)
- [x] Draft LiteLLM config applied and tested (SSE transport with 4 containers)
- [x] Rollback instructions exist (Phase 14 manual checklist)
- [x] Manual tasks documented (`docs/thor_manual_tasks.md`)

## Phase 14 - Production Integration (Manual)

Manual only. Qwen must not perform this phase.

### Current State (2026-07-04)

- ✅ `mcp_search` live in LiteLLM via SSE container (`http://mcp_search:8000/sse`)
- ✅ `mcp_knowledge` live in LiteLLM via SSE container (`http://mcp_knowledge:8000/sse`)
- ✅ `mcp_crawl` live in LiteLLM via SSE container (`http://mcp_crawl:8000/sse`)
- ✅ `mcp_filesystem_readonly` live in LiteLLM via SSE container (`http://mcp_filesystem_readonly:8000/sse`)
- ✅ `allow_all_keys: true` on all servers for development
- ✅ All 11 tools visible at `GET /v1/mcp/tools` (verified)
- ✅ LiteLLM upgraded to 1.92.0 (resolved tool calling issues)
- ✅ Metrics auth bypass fixed (`require_auth_for_metrics_endpoint: false` in `litellm_settings`)

### Verification Checklist (After Restarting LiteLLM)

Execute these steps in order after any LiteLLM restart to confirm the platform is healthy.

#### 1. Pre-flight

- [ ] Confirm a backup exists (see Phase 0 manual task in `thor_manual_tasks.md`)
- [ ] Confirm `ai-net` Docker network is active: `docker network inspect ai-net`

#### 2. LiteLLM Health

- [ ] Restart LiteLLM: `docker compose -f compose/compose.ai-core.yml restart litellm`
- [ ] Wait for LiteLLM to become ready (check logs): `docker compose -f compose/compose.ai-core.yml logs -f litellm`
- [ ] Confirm LiteLLM responds on port 4000: `curl -s -o /dev/null -w '%{http_code}' http://localhost:4000/health/readiness`

#### 3. MCP Tools

- [ ] Verify all 11 tools are registered: `curl -s -H "Authorization: Bearer <master-key>" http://localhost:4000/v1/mcp/tools | python3 -m json.tool`
- [ ] Confirm the tool list contains exactly 11 tools across 4 servers:
  - `mcp_search`: `search_web`, `search_recent`, `search_news` (3 tools)
  - `mcp_knowledge`: `kb_search`, `kb_get_document`, `kb_list_collections`, `kb_recent_changes` (4 tools)
  - `mcp_crawl`: `crawl_page` (1 tool)
  - `mcp_filesystem_readonly`: `read_file`, `list_directory`, `search_files` (3 tools)

#### 4. MCP Tool Calls via Chat Completions

- [ ] Test a tool call through `/v1/chat/completions` (example with `search_web`):
  ```bash
  curl -s http://localhost:4000/v1/chat/completions \
    -H "Authorization: Bearer <master-key>" \
    -H "Content-Type: application/json" \
    -d '{
      "model": "matrix-coder",
      "tools": [{"type": "function", "function": {"name": "search_web", "description": "Search the web", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}}}],
      "tool_choice": "auto",
      "messages": [{"role": "user", "content": "Search for ""homelab AI"""}]
    }'
  ```
- [ ] Confirm the response includes a tool_call object with function name and arguments
- [ ] Test at least one more tool (e.g., `kb_search` or `list_directory`) to verify multiple servers work

#### 5. Existing Public Services

- [ ] **Open WebUI**: Navigate to `http://192.168.4.54:8080` (or your Open WebUI URL). Confirm:
  - Login works with existing credentials
  - Chat with a local model (e.g., `matrix-coder`) returns a valid response
  - No MCP-related errors appear in the Open WebUI logs

- [ ] **llm.choukalos.com**: Test remote access:
  ```bash
  curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer <scoped-key>" https://llm.choukalos.com/v1/chat/completions -d '{"model":"matrix-coder","messages":[{"role":"user","content":"Say hello"}]}'
  ```
  - [ ] Confirm response status is `200` and returns valid JSON

- [ ] **siri.choukalos.com**: Test the Siri skill endpoint:
  ```bash
  curl -s -o /dev/null -w '%{http_code}' https://siri.choukalos.com/health
  ```
  - [ ] Confirm the endpoint responds (status `200` or `204`)
  - [ ] If old AI Harness is still active, confirm it still works (port 8090)

#### 6. Metrics Endpoint

- [ ] Verify the metrics endpoint returns `200`:
  ```bash
  curl -s -o /dev/null -w '%{http_code}' http://localhost:4000/metrics
  ```
- [ ] Confirm metrics content is present: `curl -s http://localhost:4000/metrics | head -20`
  - [ ] Should show Prometheus-style metrics (lines starting with `#` or metric names)

#### 7. MCP Container Health

- [ ] Verify all 4 MCP containers are running:
  ```bash
  docker ps --filter "name=mcp_" --format "table {{.Names}}\t{{.Status}}"
  ```
- [ ] Confirm each container shows `Up` status:
  - `mcp_search` — Up
  - `mcp_knowledge` — Up
  - `mcp_crawl` — Up
  - `mcp_filesystem_readonly` — Up

#### 8. Per-Key Access (Optional — Hardening)

- [ ] Replace `allow_all_keys: true` in `litellm/config.yml` mcp_servers section with scoped grants:
  ```yaml
  mcp_search:
    transport: sse
    url: http://mcp_search:8000/sse
    allowed_keys:
      - chuck
      - son
      - openwebui
      - siri
      - automation
  ```
- [ ] After editing, restart LiteLLM and re-run steps 3–6 above
- [ ] Test each key against its allowed/disallowed MCP servers

### Rollback Instructions

If any verification step fails or the platform is broken after changes:

#### Quick Rollback (Restore Previous Config)

1. Restore the LiteLLM config from backup:
   ```bash
   cp litellm/config.yml.bak litellm/config.yml
   # or if using the draft fix:
   # cp <backup-path>/config.yml litellm/config.yml
   ```
2. Restart LiteLLM:
   ```bash
   docker compose -f compose/compose.ai-core.yml restart litellm
   ```
3. Re-verify all services (steps 2–6 above)

#### Full Rollback (Restore from Backup)

If the quick rollback doesn't resolve the issue:

1. Stop all AI services:
   ```bash
   docker compose -f compose/compose.ai-core.yml stop
   docker compose -f compose/compose.mcp.yml stop 2>/dev/null
   ```
2. Restore backup:
   ```bash
   tar -xzf /path/to/backup.tar.gz -C /home/chuck/homelab/
   # Restore: litellm/config.yml, .env, Caddyfile, compose files
   ```
3. Restart services:
   ```bash
   docker compose -f compose/compose.ai-core.yml up -d
   ```
4. Verify all services are healthy (steps 2–6 above)

#### Rollback Individual MCP Server

If only one MCP server is misbehaving:

1. Remove or comment out the server entry from `litellm/config.yml` `mcp_servers:` section
2. Restart LiteLLM: `docker compose -f compose/compose.ai-core.yml restart litellm`
3. Stop the problematic MCP container: `docker compose -f compose/compose.mcp.yml stop <server_name>`
4. Verify remaining tools and services are healthy

### Notes

- All changes so far used `allow_all_keys: true` for development — production should use scoped grants
- The skill runner (`skills/runner/`) is code-complete but not yet deployed in production
- Caddy config may need updating to route `siri.choukalos.com` from port 8090 (old AI Harness) to port 8091 (new skill runner) — this is a future manual task
- Do not modify production Caddy, Cloudflare, or compose files without manual review

## Phase 15 - Containerize MCP Servers

### Status: ✅ Done & Applied (2026-07-04) — All 4 servers containerized, SSE config applied, tools verified

### Goal

Move each MCP server from LiteLLM stdio into its own standalone container with SSE transport.

### Completed

- **15.1** — `mcp/servers/knowledge/Dockerfile` created (python:3.12-slim, SSE transport, port 8000)
- **15.2** — `mcp/servers/knowledge/server.py` changed from `transport="stdio"` to `transport="sse"`
- **15.3** — `compose/compose.mcp.yml` created with all 4 services on `ai-net`:
  - `mcp_search` (SearXNG)
  - `mcp_knowledge` (Qdrant)
  - `mcp_crawl` (Crawl4AI)
  - `mcp_filesystem_readonly`
- **15.4** — `litellm/draft/config.phase15.yml` created (draft SSE config for LiteLLM)
- **15.5** — Containers built and tested standalone (SSE endpoints and tool calls verified)
- **15.6** — SSE config applied to `litellm/config.yml`, LiteLLM restarted
- **15.7** — LiteLLM upgraded to 1.92.0 (resolved tool calling issues)
- **15.8** — Metrics auth bypass fixed (`require_auth_for_metrics_endpoint: false` in `litellm_settings`)
- **15.9** — All 11 tools verified via `GET /v1/mcp/tools`

### Results

All 11 tools are registered and accessible through LiteLLM:

| Server | Tools |
|--------|-------|
| `mcp_search` | `search_web`, `search_recent`, `search_news` |
| `mcp_knowledge` | `kb_search`, `kb_get_document`, `kb_list_collections`, `kb_recent_changes` |
| `mcp_crawl` | `crawl_page` |
| `mcp_filesystem_readonly` | `read_file`, `list_directory`, `search_files` |

### Why

- Isolated dependencies — no Franken-venv in LiteLLM
- Independent lifecycle — add/remove/restart without touching LiteLLM
- Portable — deploy to any client's infra
- Scalable — can run on Thor, Matrix, or external hosts

### Process (per server)

1. Create `Dockerfile` with exact Python deps
2. Change `server.py` from `transport="stdio"` to `transport="sse"`
3. Add service to a new `compose/compose.mcp.yml`
4. Update `litellm/config.yml` to use `url: http://mcp_<name>:8000/mcp` + `transport: sse`
5. Remove from LiteLLM volume mounts
6. Test, then retire the stdio entry

### Order

1. `mcp_knowledge` — next (already tested, needs `qdrant_client`)
2. `mcp_crawl` — when implemented
3. Remaining servers as they're built

### Rules

- One server at a time
- Test thoroughly before removing the stdio fallback
- No service restarts beyond the affected MCP server + LiteLLM reload

## Future Exploration

- `mcp_code` — MCP server for coding workflows (repo listing, code search, git operations). Revisit after other MCP servers are stable and running.

## Final Desired State

Thor becomes a safe, modular AI platform:

```
LiteLLM = model gateway + MCP gateway
MCP servers = standalone containers, independently deployable
Skills = controlled agentic workflows (developable on laptop via LAN)
Skill runner = orchestration API (container on Thor, Python on laptop)
Open WebUI = chat channel
Siri = narrow public skill facade
PI.dev / Claude Code / IDEs = coding channels
Qdrant = retrieval
SearXNG / Crawl4AI = research substrate
Caddy / Cloudflare = controlled exposure
```

### Development Model

- **MCP servers:** Develop on Thor, each in its own container with isolated deps
- **Skills:** Develop on laptop (LAN) or Thor — plain Python, no Docker needed, calls LiteLLM over the network
- **Skill runner:** Runs as a container on Thor for production; runs as `uvicorn` on laptop for dev
- **Nothing touches production until manual approval**
