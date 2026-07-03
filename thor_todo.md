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

### Goal

Capture the current Thor state without changing production.

### Qwen Tasks

- [ ] Create `docs/thor_validation_log.md`
- [ ] Create `docs/thor_manual_tasks.md`
- [ ] Create `docs/state/`
- [ ] Run read-only inspection commands:
  - `docker ps`
  - `docker compose ls`
  - `docker network ls`
  - `docker volume ls`
- [ ] Save outputs under `docs/state/`
- [ ] Inspect current compose files
- [ ] Inspect current LiteLLM config
- [ ] Inspect current AI Harness structure
- [ ] Inspect current Caddy config
- [ ] Inspect current Cloudflare config files, if present
- [ ] Inspect existing scripts
- [ ] Do not edit production files

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

### Goal

Build the new Harness foundation locally only.

### Qwen Tasks

Create:

```text
skills/runner/
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

Initial endpoints:

```text
POST /skills/{skill_name}
GET /skills/jobs/{job_id}
GET /skills/jobs/{job_id}/artifact
```

### Note

Dev port: `8091`. (Current AI Harness is on `8090`. Caddy will switch `siri.choukalos.com` from `:8090` to `:8091` after manual cutover.)

### Rules

- Do not bind production port
- Do not replace current Harness
- Do not update Caddy
- Do not update Cloudflare
- Do not restart existing services

## Phase 9 - Implement First Skills

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

## Phase 10 - Draft LiteLLM MCP Config

### Goal

Prepare config, but do not activate it.

### Qwen Tasks

Create draft files only:

```text
litellm/draft/mcp-search.example.yaml
litellm/draft/tool-bundles.example.yaml
litellm/draft/model-aliases.example.yaml
```

Draft bundles:

- `bundle_family`
- `bundle_coding`
- `bundle_research`
- `bundle_investing`
- `bundle_admin`
- `bundle_siri`

### Critical Rule

Do not copy draft config into live LiteLLM config.

### Manual Task

```text
MANUAL TASK FOR CHUCK:
Reason:
Registering MCP tools in LiteLLM may require LiteLLM config reload or proxy restart.
Command:
TBD after Qwen generates tested draft config.
Expected impact:
LiteLLM may briefly interrupt active clients.
Rollback:
Restore previous LiteLLM config and restart/reload LiteLLM.
Validation:
LiteLLM health works, existing model aliases work, Open WebUI can chat, and MCP discovery works for a test key only.
```

## Phase 11 - Presenton Integration

### Goal

Use Presenton both LAN-only and through a controlled skill.

### Rules

- Presenton UI remains LAN-only
- Portal may link to Presenton
- `presentation_build` skill may call Presenton internally
- Remote use should go through Siri/skill path, not direct public Presenton exposure

## Phase 12 - Observability Plan

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

### Goal

Stop before production integration.

### Qwen Tasks

Create `docs/thor_integration_readiness.md`.

Checklist:

- [ ] Backup exists
- [ ] AI inventory complete
- [ ] Channel architecture complete
- [ ] Public access model complete
- [ ] Model alias registry complete
- [ ] Artifact strategy complete
- [ ] Harness rebuild plan complete
- [ ] MCP search works locally
- [ ] MCP knowledge works locally
- [ ] Skill runner works locally
- [ ] First skills work locally
- [ ] Draft LiteLLM config exists
- [ ] Draft tool bundles exist
- [ ] Draft key access restrictions exist
- [ ] Rollback instructions exist
- [ ] Manual LiteLLM task exists
- [ ] Manual Caddy task exists if needed
- [ ] Manual Cloudflare task exists if needed

## Phase 14 - Production Integration

Manual only.

Qwen must not perform this phase.

Potential manual steps:

- Backup live LiteLLM config
- Apply MCP config to LiteLLM
- Reload/restart LiteLLM if required
- Test existing model aliases
- Test Open WebUI
- Test one MCP tool with a test key
- Test Chuck key
- Test son key
- Test Siri key
- Test artifact retrieval
- Roll back if needed

## Future Exploration

- `mcp_code` — MCP server for coding workflows (repo listing, code search, git operations). Revisit after other MCP servers are stable and running.

## Final Desired State

Thor becomes a safe, modular AI platform:

```text
LiteLLM = model gateway
MCP servers = reusable read-mostly tools
Skills = controlled agentic workflows
Rebuilt AI Harness = skill runner and orchestration API
Open WebUI = chat channel
Siri = narrow public skill facade
PI.dev / Claude Code / IDEs = coding channels
Qdrant = retrieval
SearXNG / Crawl4AI = research substrate
Caddy / Cloudflare = controlled exposure
```
