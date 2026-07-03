# Pi Long Task TODO

Global instructions:
- Long task goal: Implement phases 6 through 14 of thor_todo.md for the homelab project at /home/chuck/homelab. Follow these absolute rules from thor_todo.md: - Do NOT restart, rebuild, replace, or reconfigure LiteLLM, Open WebUI, Qdrant, Redis, Caddy, Cloudflare Tunnel, or the AI Harness - Do NOT modify production Caddy, LiteLLM, Cloudflare, or compose files - Do NOT run homelab.sh down/rebuild - Do NOT modify .env directly - Do NOT expose new public endpoints or bind new services to production ports - Do NOT delete containers, volumes, images, networks, or data - Do NOT run database migrations or package upgrades on production - Do NOT change ownership or permissions on production paths - Do NOT run destructive Git commands - Do NOT copy draft configs into live LiteLLM config - Create new files, new directories, draft configs, documentation, MCP server code, skill runner code, test scripts — these are all allowed - Run static validation, unit tests, local scripts that don't touch production - Phase 14 is manual only — do NOT perform production integration PHASE 6 - Build First MCP Server: Search - Create mcp/servers/search/ with a working Python MCP server using the MCP Python SDK (mcp library, stdio transport) - Tools: search_web(query, max_results), search_recent(query, days, max_results), search_news(query, max_results) - Backend: SearXNG (check existing Docker state or config for the SearXNG endpoint URL) - Requirements: result limits, timeouts, compact output, no crawling, no browser automation, no writes - Include README.md, server.py, pyproject.toml (or package.json), tests/, examples/ PHASE 7 - Build Knowledge MCP Server - Create mcp/servers/knowledge/ with a working Python MCP server - Tools: kb_search(query, top_k, collection), kb_get_document(doc_id), kb_list_collections(), kb_recent_changes(days) - Rules: read-only, collection allowlist, curated collections only, no arbitrary file access, compact snippets, full docs only by doc_id, no reindexing - Backend: Qdrant (check existing Docker state for Qdrant endpoint) - Include README.md, server.py, pyproject.toml PHASE 8 - Build Skill Runner Skeleton - Create skills/runner/ with a FastAPI-based Python app - Features: job model, job status, artifact path, logging, dry-run mode, approval gate support, tool bundle declaration, model alias declaration - Endpoints: POST /skills/{skill_name}, GET /skills/jobs/{job_id}, GET /skills/jobs/{job_id}/artifact - Dev port: 8091 (NOT 8090 which is the current Harness) - Include README.md, main.py, pyproject.toml, requirements or dependencies PHASE 9 - Implement First Skills - siri_ask: Short mobile answers, safe status lookups, optional artifact links. Strict timeouts, no broad tools, no admin writes. - deep_research: Repeatable research process, cited markdown report, artifact output. Summary, full report, source list, artifact path. - presentation_build: Use Presenton through a controlled skill. Support remote use through Siri path. Keep Presenton LAN-only. - Place skill implementations in their respective directories under skills/ PHASE 10 - Draft LiteLLM MCP Config - Create draft files (DO NOT place in live config): - litellm/draft/mcp-search.example.yaml - litellm/draft/tool-bundles.example.yaml - litellm/draft/model-aliases.example.yaml - Draft tool bundles: bundle_family, bundle_coding, bundle_research, bundle_investing, bundle_admin, bundle_siri - Add a manual task for Chuck to the thor_manual_tasks.md for registering MCP tools with LiteLLM PHASE 11 - Presenton Integration - Document the integration in the presentation_build skill - Presenton UI remains LAN-only - presentation_build skill calls Presenton internally - Remote use through Siri/skill path, not direct public Presenton exposure - Check existing homelab for Presenton configuration to understand its endpoint PHASE 12 - Observability Plan - Create docs/thor_observability_plan.md covering: LiteLLM usage logs, per-key usage, tool-call logs, skill job logs, artifact logs, token counts, context size, latency, tool error rates, timeout rates, model error rates, public endpoint access logs PHASE 13 - Integration Readiness Review - Create docs/thor_integration_readiness.md with a comprehensive checklist as specified in thor_todo.md PHASE 14 - Production Integration - Mark as manual only in thor_manual_tasks.md and thor_todo.md - Do NOT execute any production integration steps - Document potential manual steps: backup live LiteLLM config, apply MCP config, reload/restart LiteLLM, test aliases, test Open WebUI, test MCP tools with test key, test Chuck/son/siri keys, test artifact retrieval, rollback if needed Use the existing design docs in docs/ for references (thor_mcp_architecture.md, thor_skill_architecture.md, thor_ai_harness_rebuild.md, thor_model_alias_registry.md, thor_data_classification.md, thor_artifact_strategy.md). Check the current SearXNG and Qdrant and Presenton Docker service names and ports from docs/state/ and existing config to use correct endpoints in the MCP servers and skills.

- Persisted goal specification: /home/chuck/homelab/tmp/pi-goal-task/goal-2026-07-03T03-27-06-767Z-4509a92c/GOAL_SPEC.json
- Goal specification summary: Software product discovery converted the vague goal into a scoped delivery definition: Implement phases 6 through 14 of thor_todo.md for the homelab project at /home/chuck/homelab. Follow these absolute rules from thor_todo.md: - Do NOT restart, rebuild, replace, or reconfigure LiteLLM, Open WebUI, Qdrant, Redis, Caddy, Cloudflare Tunnel, or the AI Harness - Do NOT modify production Caddy, LiteLLM, Cloudflare, or compose files - Do NOT run homelab.sh down/rebuild - Do NOT modify .env directly - Do NOT expose new public endpoints or bind new services to production ports - Do NOT delete containers, volumes, images, networks, or data - Do NOT run database migrations or package upgrades on production - Do NOT change ownership or permissions on production paths - Do NOT run destructive Git commands - Do NOT copy draft configs into live LiteLLM config - Create new files, new directories, draft configs, documentation, MCP server code, skill runner code, test scripts — these are all allowed - Run static validation, unit tests, local scripts that don't touch production - Phase 14 is manual only — do NOT perform production integration PHASE 6 - Build First MCP Server: Search - Create mcp/servers/search/ with a working Python MCP server using the MCP Python SDK (mcp library, stdio transport) - Tools: search_web(query, max_results), search_recent(query, days, max_results), search_news(query, max_results) - Backend: SearXNG (check existing Docker state or config for the SearXNG endpoint URL) - Requirements: result limits, timeouts, compact output, no crawling, no browser automation, no writes - Include README.md, server.py, pyproject.toml (or package.json), tests/, examples/ PHASE 7 - Build Knowledge MCP Server - Create mcp/servers/knowledge/ with a working Python MCP server - Tools: kb_search(query, top_k, collection), kb_get_document(doc_id), kb_list_collections(), kb_recent_changes(days) - Rules: read-only, collection allowlist, curated collections only, no arbitrary file access, compact snippets, full docs only by doc_id, no reindexing - Backend: Qdrant (check existing Docker state for Qdrant endpoint) - Include README.md, server.py, pyproject.toml PHASE 8 - Build Skill Runner Skeleton - Create skills/runner/ with a FastAPI-based Python app - Features: job model, job status, artifact path, logging, dry-run mode, approval gate support, tool bundle declaration, model alias declaration - Endpoints: POST /skills/{skill_name}, GET /skills/jobs/{job_id}, GET /skills/jobs/{job_id}/artifact - Dev port: 8091 (NOT 8090 which is the current Harness) - Include README.md, main.py, pyproject.toml, requirements or dependencies PHASE 9 - Implement First Skills - siri_ask: Short mobile answers, safe status lookups, optional artifact links. Strict timeouts, no broad tools, no admin writes. - deep_research: Repeatable research process, cited markdown report, artifact output. Summary, full report, source list, artifact path. - presentation_build: Use Presenton through a controlled skill. Support remote use through Siri path. Keep Presenton LAN-only. - Place skill implementations in their respective directories under skills/ PHASE 10 - Draft LiteLLM MCP Config - Create draft files (DO NOT place in live config): - litellm/draft/mcp-search.example.yaml - litellm/draft/tool-bundles.example.yaml - litellm/draft/model-aliases.example.yaml - Draft tool bundles: bundle_family, bundle_coding, bundle_research, bundle_investing, bundle_admin, bundle_siri - Add a manual task for Chuck to the thor_manual_tasks.md for registering MCP tools with LiteLLM PHASE 11 - Presenton Integration - Document the integration in the presentation_build skill - Presenton UI remains LAN-only - presentation_build skill calls Presenton internally - Remote use through Siri/skill path, not direct public Presenton exposure - Check existing homelab for Presenton configuration to understand its endpoint PHASE 12 - Observability Plan - Create docs/thor_observability_plan.md covering: LiteLLM usage logs, per-key usage, tool-call logs, skill job logs, artifact logs, token counts, context size, latency, tool error rates, timeout rates, model error rates, public endpoint access logs PHASE 13 - Integration Readiness Review - Create docs/thor_integration_readiness.md with a comprehensive checklist as specified in thor_todo.md PHASE 14 - Production Integration - Mark as manual only in thor_manual_tasks.md and thor_todo.md - Do NOT execute any production integration steps - Document potential manual steps: backup live LiteLLM config, apply MCP config, reload/restart LiteLLM, test aliases, test Open WebUI, test MCP tools with test key, test Chuck/son/siri keys, test artifact retrieval, rollback if needed Use the existing design docs in docs/ for references (thor_mcp_architecture.md, thor_skill_architecture.md, thor_ai_harness_rebuild.md, thor_model_alias_registry.md, thor_data_classification.md, thor_artifact_strategy.md). Check the current SearXNG and Qdrant and Presenton Docker service names and ports from docs/state/ and existing config to use correct endpoints in the MCP servers and skills.
- Definition of done: Done when all must/should scoped requirements are implemented, acceptance criteria are satisfied, required verification gates pass or record justified blockers, and review evaluates the result against this persisted product definition. Do not treat a partial MVP as complete when the original goal requests a broader product.
- Implementation TODOs must trace to requirements: REQ-1, REQ-2, REQ-3, REQ-4, REQ-5, REQ-6
- Implementation TODOs must satisfy acceptance criteria: AC-1, AC-2, AC-3, AC-4, AC-5, AC-6
- Required verification gates: VG-1, VG-2, VG-3, VG-4
- Implementation TODOs should be sequenced by milestones: MS-1, MS-2, MS-3

## Progress

- [x] TODO 1 — Phase 6: Build MCP Search Server
- [x] TODO 2 — Phase 7: Build Knowledge MCP Server
- [x] TODO 3 — Phase 8: Build Skill Runner Skeleton
- [x] TODO 4 — Phase 9a: Implement siri_ask Skill
- [x] TODO 5 — Phase 9b: Implement deep_research Skill
- [x] TODO 6 — Phase 9c + 11: Implement presentation_build Skill with Presenton Integration
- [ ] TODO 7 — Phase 10: Draft LiteLLM MCP Config
- [ ] TODO 8 — Phase 10: Add Manual Task for MCP Tool Registration
- [ ] TODO 9 — Phase 12: Create Observability Plan
- [ ] TODO 10 — Phase 13: Create Integration Readiness Review
- [ ] TODO 11 — Phase 14: Document Manual Production Integration Steps

---

## TODO 1 — Phase 6: Build MCP Search Server

**Goal:** Create `mcp/servers/search/` with a working Python MCP server using the MCP Python SDK (mcp library, stdio transport) that exposes three tools backed by SearXNG.

**Requirements:**
- Backend: SearXNG at `http://searxng:8080` (internal Docker network) or `http://192.168.4.54:8088` (host). Use environment variable `SEARXNG_URL` defaulting to `http://searxng:8080` for container use.
- Tools:
  - `search_web(query, max_results)` — General web search. Default max_results=5, cap at 20.
  - `search_recent(query, days, max_results)` — Recent search (past N days). Default days=7, max_results=5, cap at 20.
  - `search_news(query, max_results)` — News-specific search. Default max_results=5, cap at 20.
- Each tool must enforce result limits, timeouts (10s HTTP timeout), compact output (title, URL, snippet ≤200 chars).
- No crawling, no browser automation, no writes.
- Use the MCP Python SDK (`mcp` package) with stdio transport.
- Include: `server.py`, `pyproject.toml`, `README.md`, `tests/test_search.py` (mocked tests), `examples/` with at least one usage example.
- Reference: `docs/thor_mcp_architecture.md` for the mcp_search specification.

**Status:**
- [x] Create `mcp/servers/search/` directory structure (server.py, pyproject.toml, README.md, tests/, examples/)
- [x] Implement `server.py` with MCP stdio transport and three tool handlers
- [x] Implement SearXNG client with timeout, result limiting, compact output formatting
- [x] Create `pyproject.toml` with `mcp` dependency and project metadata
- [x] Write `README.md` documenting the server, tools, configuration, and usage
- [x] Write `tests/test_search.py` with mocked HTTP tests for all three tools
- [x] Create `examples/` with a usage example script
- [x] Run `python -c "import ast; ast.parse(open('server.py').read())"` to verify syntax

**Verify:**
- `mcp/servers/search/server.py` exists and imports `mcp` successfully (syntax check)
- `mcp/servers/search/pyproject.toml` exists with `mcp` in dependencies
- `mcp/servers/search/README.md` exists with tool documentation
- `mcp/servers/search/tests/test_search.py` exists and passes when run with `python -m pytest` (mocked)
- No production files modified, no service restarts

**Done when:**
- All files under `mcp/servers/search/` are created, syntactically valid, and tests pass. SearXNG endpoint is configurable via `SEARXNG_URL` env var defaulting to `http://searxng:8080`.

---

## TODO 2 — Phase 7: Build Knowledge MCP Server

**Goal:** Create `mcp/servers/knowledge/` with a working Python MCP server using the MCP Python SDK (mcp library, stdio transport) that provides read-only Qdrant knowledge base access.

**Requirements:**
- Backend: Qdrant at `http://qdrant:6333` (internal Docker network) or `http://192.168.4.54:6333` (host). Use environment variable `QDRANT_URL` defaulting to `http://qdrant:6333` for container use.
- Tools:
  - `kb_search(query, top_k, collection)` — Vector search in a curated collection. Default top_k=5, cap at 20. Collection must be from allowlist.
  - `kb_get_document(doc_id)` — Retrieve full document by ID.
  - `kb_list_collections()` — List available curated collections.
  - `kb_recent_changes(days)` — Show recent changes (metadata scan) in collections. Default days=7.
- Collection allowlist (read-only): `family_curated`, `homelab_curated`, `coding_curated`. Do NOT allow `private_curated` or `finance_curated` by default.
- No arbitrary file access, no reindexing, no writes. Compact snippets in search results.
- Use the MCP Python SDK (`mcp` package) with stdio transport.
- Include: `server.py`, `pyproject.toml`, `README.md`, `tests/test_knowledge.py` (mocked tests).
- Reference: `docs/thor_mcp_architecture.md` (mcp_knowledge spec) and `docs/thor_data_classification.md` (collection definitions).

**Status:**
- [x] Create `mcp/servers/knowledge/` directory structure (server.py, pyproject.toml, README.md, tests/)
- [x] Implement `server.py` with MCP stdio transport and four tool handlers
- [x] Implement Qdrant client with collection allowlist enforcement, read-only operations
- [x] Create `pyproject.toml` with `mcp` and `qdrant-client` dependencies
- [x] Write `README.md` documenting the server, tools, allowlist, configuration
- [x] Write `tests/test_knowledge.py` with mocked HTTP tests for all tools and allowlist enforcement
- [x] Run syntax check on server.py

**Verify:**
- `mcp/servers/knowledge/server.py` exists and is syntactically valid
- `mcp/servers/knowledge/pyproject.toml` exists with correct dependencies
- Collection allowlist is hardcoded and enforced in code
- No write operations exposed; all tools are read-only
- No production files modified, no service restarts

**Done when:**
- All files under `mcp/servers/knowledge/` are created, syntactically valid, and tests pass. Qdrant endpoint is configurable via `QDRANT_URL` env var. Collection allowlist is enforced.

---

## TODO 3 — Phase 8: Build Skill Runner Skeleton

**Goal:** Create `skills/runner/` with a FastAPI-based Python application that provides the skill job lifecycle API on development port 8091.

**Requirements:**
- Dev port: 8091 (NOT 8090 which is the current Harness).
- Endpoints:
  - `POST /skills/{skill_name}` — Launch a skill job. Accepts JSON body with `params`, `requester`, `channel`, `dry_run` (optional, default false).
  - `GET /skills/jobs/{job_id}` — Get job status. Returns job_id, skill, status, created_at, completed_at, summary, artifact path, requester, channel.
  - `GET /skills/jobs/{job_id}/artifact` — Retrieve the skill's output artifact file.
- Job model with status values: `pending`, `running`, `completed`, `failed`, `awaiting_approval`, `cancelled`.
- Job storage: in-memory dict for dev (no database). Artifact path stored per job.
- Logging: structured logging to stdout and optional log file.
- Dry-run mode: when `dry_run=true`, log what would happen without executing.
- Approval gate support: jobs can enter `awaiting_approval` status.
- Tool bundle declaration: jobs declare which tool bundle they need.
- Model alias declaration: jobs declare which model alias to use.
- Include: `main.py`, `pyproject.toml`, `README.md`.
- Reference: `docs/thor_skill_architecture.md` for API shape, `docs/thor_ai_harness_rebuild.md` for runner architecture.

**Status:**
- [x] Create `skills/runner/` directory structure (main.py, pyproject.toml, README.md)
- [x] Implement `main.py` with FastAPI app on port 8091, all three endpoints
- [x] Implement job model with all status values, artifact path, logging
- [x] Implement dry-run mode that logs without executing
- [x] Implement approval gate support (awaiting_approval status)
- [x] Add tool bundle and model alias declaration fields to job model
- [x] Create `pyproject.toml` with `fastapi`, `uvicorn`, and dependencies
- [x] Write `README.md` documenting endpoints, configuration, and dev usage
- [x] Run syntax check and verify FastAPI imports resolve

**Verify:**
- `skills/runner/main.py` exists and is syntactically valid
- `skills/runner/pyproject.toml` exists with fastapi and uvicorn
- All three endpoints defined with correct paths and methods
- Port is 8091 (not 8090)
- Job model includes all required status values
- Dry-run mode, approval gate, tool bundle, and model alias support present
- No production files modified, no service restarts

**Done when:**
- Skill runner skeleton is fully implemented with all endpoints, job model, and support features. Code is syntactically valid and ready for local testing.

---

## TODO 4 — Phase 9a: Implement siri_ask Skill

**Goal:** Implement the `siri_ask` skill under `skills/siri_ask/` providing short mobile answers and safe status lookups.

**Requirements:**
- Purpose: Quick Q&A for Siri/iOS Shortcuts. Short answers, no heavy research.
- Inputs: `query` (string), optional `context` (previous conversation).
- Outputs: Short text answer (<500 tokens).
- Strict timeouts: max 30 seconds total. No broad tools, no admin writes.
- Model alias: `local/qwen-coder` (main model).
- Required tools: model chat only (no MCP tools for siri_ask by default).
- Optional artifact path: `/home/chuck/data/media/siri_outputs/` for logging.
- Skill manifest: `skill.yml` with name, version, description, inputs, tools, model_alias, artifact_path, channels, max_runtime.
- Implementation: `skill.py` with the execution logic.
- Include: `README.md`, `skill.yml`, `skill.py`.
- Reference: `docs/thor_skill_architecture.md` for siri_ask specification.

**Status:**
- [x] Create `skills/siri_ask/` directory structure (skill.py, skill.yml, README.md)
- [x] Implement `skill.py` with siri_ask execution logic (chat with model, short response)
- [x] Create `skill.yml` manifest with all required fields per the architecture doc
- [x] Write `README.md` documenting the skill, inputs, outputs, and constraints
- [x] Enforce strict timeouts (30s max runtime)
- [x] Ensure no broad tools, no admin writes
- [x] Run syntax check

**Verify:**
- `skills/siri_ask/skill.py` exists and is syntactically valid
- `skills/siri_ask/skill.yml` exists with correct manifest format
- `skills/siri_ask/README.md` exists
- Skill enforces 500-token output limit and 30-second timeout
- No admin write tools referenced
- No production files modified

**Done when:**
- siri_ask skill is fully implemented with manifest, execution logic, and documentation. Output limits and timeout constraints are enforced.

---

## TODO 5 — Phase 9b: Implement deep_research Skill

**Goal:** Implement the `deep_research` skill under `skills/deep_research/` providing multi-source research with cited markdown reports and artifact output.

**Requirements:**
- Purpose: Multi-source deep research with citation and artifact generation.
- Inputs: `query` (string), `depth` (quick/comprehensive/exhaustive, default comprehensive), `max_sources` (int, default 10).
- Outputs: Research report (Markdown) with citations, saved as artifact.
- Required tools: `mcp_search`, `mcp_crawl` (optional), `mcp_knowledge` (optional), model chat.
- Model alias: `local/qwen-coder` (main model).
- Expected runtime: 2-15 minutes (max_runtime: 900s).
- No approval gates (read-only research).
- Artifact path: `/home/chuck/data/media/research_reports/`.
- Output structure: summary, full report, source list, artifact path.
- Skill manifest: `skill.yml` with all required fields.
- Implementation: `skill.py` with the multi-step research workflow.
- Include: `README.md`, `skill.yml`, `skill.py`.
- Reference: `docs/thor_skill_architecture.md` for deep_research specification.

**Status:**
- [x] Create `skills/deep_research/` directory structure (skill.py, skill.yml, README.md)
- [x] Implement `skill.py` with multi-step research workflow (search → collect sources → synthesize report)
- [x] Create `skill.yml` manifest with all required fields
- [x] Write `README.md` documenting the skill, research process, and output format
- [x] Implement cited markdown report generation with source list
- [x] Implement artifact saving to `/home/chuck/data/media/research_reports/`
- [x] Enforce source limits and runtime limits
- [x] Run syntax check

**Verify:**
- `skills/deep_research/skill.py` exists and is syntactically valid
- `skills/deep_research/skill.yml` exists with correct manifest format
- `skills/deep_research/README.md` exists
- Skill declares mcp_search, mcp_crawl, mcp_knowledge as required tools
- Artifact path correctly set to `/home/chuck/data/media/research_reports/`
- Output includes summary, full report, source list, artifact path
- No production files modified

**Done when:**
- deep_research skill is fully implemented with manifest, execution logic, artifact generation, and documentation. Multi-step research process is clearly defined.

---

## TODO 6 — Phase 9c + 11: Implement presentation_build Skill with Presenton Integration

**Goal:** Implement the `presentation_build` skill under `skills/presentation_build/` and document its Presenton integration per Phase 11 requirements.

**Requirements:**
- Purpose: Generate presentations from a topic or existing content using Presenton.
- Inputs: `topic` (string), `slide_count` (int), `style` (optional), `content_source` (existing artifact path or text).
- Outputs: Presentation file, artifact link.
- Required tools: Presenton API, model chat, optional `mcp_knowledge` for content.
- Model alias: `local/qwen-coder` (main model).
- Expected runtime: 1-5 minutes (max_runtime: 300s).
- No approval gates (generative, no sensitive data unless provided).
- Artifact path: `/home/chuck/data/media/presentations/`.
- Presenton endpoint: `http://presenton:80` (internal Docker network) or `http://192.168.4.54:5000` (host). Use `PRESENTON_URL` env var defaulting to `http://presenton:80`.
- Presenton UI remains LAN-only. Skill calls Presenton internally. Remote use through Siri/skill path only, NOT direct public Presenton exposure.
- Skill manifest: `skill.yml` with all required fields.
- Implementation: `skill.py` with presentation generation logic (generate content via model, call Presenton API, save artifact).
- Include: `README.md`, `skill.yml`, `skill.py`.
- Phase 11: Document in README that Presenton UI is LAN-only, skill handles all Presenton interaction internally, and remote access is only through the skill runner API.
- Reference: `docs/thor_skill_architecture.md` for presentation_build spec, `docs/thor_ai_harness_rebuild.md` for Presenton integration notes.

**Status:**
- [x] Create `skills/presentation_build/` directory structure (skill.py, skill.yml, README.md)
- [x] Implement `skill.py` with presentation generation workflow (model content gen → Presenton API call → artifact save)
- [x] Create `skill.yml` manifest with all required fields
- [x] Write `README.md` documenting skill, Presenton integration, and LAN-only constraint
- [x] Document Presenton integration: LAN-only UI, internal skill calls, remote via Siri/skill path
- [x] Use `PRESENTON_URL` env var for configurable endpoint
- [x] Run syntax check

**Verify:**
- `skills/presentation_build/skill.py` exists and is syntactically valid
- `skills/presentation_build/skill.yml` exists with correct manifest format
- `skills/presentation_build/README.md` exists and documents Presenton integration
- README clearly states Presenton is LAN-only and skill handles Presenton internally
- Artifact path set to `/home/chuck/data/media/presentations/`
- No production files modified, no Presenton container changes

**Done when:**
- presentation_build skill is fully implemented with Presenton integration documented. LAN-only constraint is clear in documentation. No production Presenton changes.

---

## TODO 7 — Phase 10: Draft LiteLLM MCP Config

**Goal:** Create draft LiteLLM configuration files under `litellm/draft/` for MCP integration, tool bundles, and model aliases. DO NOT place any of these in the live LiteLLM config.

**Requirements:**
- Create three draft files (new, in `litellm/draft/`):
  - `mcp-search.example.yaml` — MCP server registration for the search MCP server. Reference the search server path and stdio transport config.
  - `tool-bundles.example.yaml` — Tool bundle definitions with the following bundles:
    - `bundle_family`: chat, simple lookup tools suitable for family use
    - `bundle_coding`: chat, file-read, code-gen, code-review tools
    - `bundle_research`: chat, web-search, kb-read, deep-research tools
    - `bundle_investing`: chat, stock-data, financial-search tools
    - `bundle_admin`: full tool access for Chuck
    - `bundle_siri`: chat, status-check, short-answer tools
  - `model-aliases.example.yaml` — Model alias definitions matching `docs/thor_model_alias_registry.md` (`local/qwen-coder`, `local/qwen-long`, `local/gemma-family`, `local/experiment`, `local/embed`).
- All files are examples/drafts only. Include a header comment on each file: "DRAFT — Do not copy into live LiteLLM config."
- Include a `README.md` in `litellm/draft/` updating the existing one with references to the new files.
- Reference: `docs/thor_model_alias_registry.md`, `docs/thor_mcp_architecture.md`.

**Status:**
- [ ] Create `litellm/draft/mcp-search.example.yaml` with MCP search server config
- [ ] Create `litellm/draft/tool-bundles.example.yaml` with all six bundles
- [ ] Create `litellm/draft/model-aliases.example.yaml` with all five model aliases
- [ ] Add "DRAFT" warning header to each file
- [ ] Update `litellm/draft/README.md` with references to new files
- [ ] Verify no files in `litellm/config.yml` (live config) are modified
- [ ] Run syntax check on YAML files

**Verify:**
- All three new YAML files exist under `litellm/draft/`
- Each file has a "DRAFT" warning header
- `litellm/draft/tool-bundles.example.yaml` contains all six bundles (family, coding, research, investing, admin, siri)
- `litellm/draft/model-aliases.example.yaml` matches the alias registry from `docs/thor_model_alias_registry.md`
- `litellm/config.yml` (live config) is unmodified
- YAML files parse correctly
- No production files modified

**Done when:**
- All three draft files are created with correct content, draft warnings, and matching the design docs. Live LiteLLM config is untouched.

---

## TODO 8 — Phase 10: Add Manual Task for MCP Tool Registration

**Goal:** Add a manual task to `docs/thor_manual_tasks.md` for Chuck to register MCP tools with LiteLLM after reviewing the draft configs.

**Requirements:**
- Append to `docs/thor_manual_tasks.md` (read existing content, add new section at end).
- Task description: Review draft MCP configs in `litellm/draft/`, merge approved settings into live `litellm/config.yml`, reload/restart LiteLLM container, and verify tool availability.
- Include rollback instructions: restore `config.yml` from backup.
- Include verification steps: test MCP tools via LiteLLM proxy, verify tool bundles work with different API keys.
- Do NOT modify `litellm/config.yml` itself.
- Reference: `litellm/draft/mcp-search.example.yaml`, `litellm/draft/tool-bundles.example.yaml`, `litellm/draft/model-aliases.example.yaml`.

**Status:**
- [ ] Read existing `docs/thor_manual_tasks.md`
- [ ] Append new manual task section with complete instructions
- [ ] Include backup, apply, test, and rollback steps
- [ ] Verify only `thor_manual_tasks.md` is modified (no production files)

**Verify:**
- `docs/thor_manual_tasks.md` contains the new manual task
- Task references the correct draft file paths
- Rollback instructions included
- `litellm/config.yml` is unmodified
- No production files modified

**Done when:**
- `docs/thor_manual_tasks.md` has the new manual task section appended. Only this one file was modified.

---

## TODO 9 — Phase 12: Create Observability Plan

**Goal:** Create `docs/thor_observability_plan.md` covering comprehensive observability for the new platform components.

**Requirements:**
- Cover all specified observability areas:
  - LiteLLM usage logs (token counts, model used, latency per request)
  - Per-key usage (requests per API key, token usage per key)
  - Tool-call logs (which tool was called, by whom, outcome)
  - Skill job logs (job lifecycle events, start/end times, errors)
  - Artifact logs (creation, access, deletion)
  - Token counts (input, output, total per interaction)
  - Context size (context window usage, overflow detection)
  - Latency (per-request, per-skill, per-tool)
  - Tool error rates (failure rate per tool)
  - Timeout rates (frequency of timeouts per tool/skill)
  - Model error rates (provider errors, rate limits, content filtering)
  - Public endpoint access logs (siri.choukalos.com, llm.choukalos.com)
- Structure: section per category with data source, collection method, storage, retention, and alerting recommendations.
- Reference existing infrastructure: Victoria Metrics (port 9090), Grafana (port 3001), LiteLLM metrics endpoint, Docker logging.
- Include a summary of what is already observable vs what needs new instrumentation.
- Do NOT modify any monitoring service configs or production files.

**Status:**
- [ ] Create `docs/thor_observability_plan.md` with comprehensive structure
- [ ] Document each observability area with data source, collection method, storage, retention, alerting
- [ ] Reference existing infrastructure (Victoria Metrics, Grafana, LiteLLM metrics)
- [ ] Include summary of current vs needed observability
- [ ] Ensure no production monitoring configs are modified
- [ ] Run markdown lint (basic check for heading structure)

**Verify:**
- `docs/thor_observability_plan.md` exists and covers all 12 observability areas
- Each section has data source, collection method, and alerting guidance
- Existing monitoring infrastructure (Victoria Metrics, Grafana) is referenced
- No production monitoring files modified
- No service restarts

**Done when:**
- Complete observability plan document exists at `docs/thor_observability_plan.md` covering all required areas with actionable recommendations.

---

## TODO 10 — Phase 13: Create Integration Readiness Review

**Goal:** Create `docs/thor_integration_readiness.md` with a comprehensive checklist for verifying readiness before any production integration.

**Requirements:**
- Create a structured checklist covering:
  - **MCP Servers**: Search server builds, runs with stdio, tools respond correctly with mocked backends, error handling works, timeouts enforced
  - **Knowledge Server**: Builds, runs with stdio, collection allowlist enforced, read-only operations verified, error handling works
  - **Skill Runner**: FastAPI starts on port 8091, all three endpoints respond, job lifecycle works end-to-end, dry-run mode works, approval gate enters awaiting_approval
  - **Skills**: Each skill (siri_ask, deep_research, presentation_build) has valid manifest, runs in dry-run mode, produces expected output structure
  - **Draft Configs**: All three draft YAML files parse correctly, tool bundles are complete, model aliases match registry
  - **Documentation**: All README files are complete, observability plan exists, integration readiness checklist exists
  - **Safety Checks**: No production files modified, no compose files changed, no .env modified, no new public endpoints, no container changes
  - **Testing**: Static validation passes for all Python files, YAML files parse correctly, no imports fail
- Each checklist item must have a verification command or specific check described.
- Include a sign-off section for manual review.
- Do NOT modify any production files.

**Status:**
- [ ] Create `docs/thor_integration_readiness.md` with comprehensive checklist
- [ ] Include sections for MCP servers, knowledge server, skill runner, skills, draft configs, documentation, safety checks, testing
- [ ] Each item has a concrete verification method
- [ ] Include sign-off section
- [ ] Ensure no production files are modified
- [ ] Run markdown syntax check

**Verify:**
- `docs/thor_integration_readiness.md` exists with all required sections
- Checklist covers all phases 6-13 deliverables
- Each item has a concrete verification method
- Sign-off section present
- No production files modified

**Done when:**
- Complete integration readiness checklist exists at `docs/thor_integration_readiness.md` with actionable verification steps for all deliverables.

---

## TODO 11 — Phase 14: Document Manual Production Integration Steps

**Goal:** Document the manual production integration steps in both `docs/thor_manual_tasks.md` and mark Phase 14 as manual-only. Do NOT execute any integration steps.

**Requirements:**
- Append to `docs/thor_manual_tasks.md` (read existing content, add new section at end).
- Document potential manual steps:
  1. Backup live LiteLLM config (`litellm/config.yml`)
  2. Review and apply approved MCP config from `litellm/draft/` into live config
  3. Review and apply approved tool bundles into live config
  4. Review and apply approved model aliases into live config
  5. Reload/restart LiteLLM container (manual)
  6. Test model aliases via LiteLLM proxy
  7. Test Open WebUI with new model aliases
  8. Test MCP tools with test key
  9. Test Chuck/son/siri keys with their respective bundle restrictions
  10. Test artifact retrieval via skill runner
  11. Rollback procedure if issues found
- Include rollback instructions for each step.
- Include explicit "DO NOT AUTOMATE" markers.
- Mark Phase 14 as manual-only in any relevant documentation.
- Do NOT modify `litellm/config.yml`, `compose/`, `.env`, or any production files.

**Status:**
- [ ] Read existing `docs/thor_manual_tasks.md`
- [ ] Append comprehensive Phase 14 manual integration task
- [ ] Include all 11 manual steps with rollback for each
- [ ] Add "DO NOT AUTOMATE" markers
- [ ] Mark Phase 14 as manual-only
- [ ] Verify only `thor_manual_tasks.md` is modified (no production files)

**Verify:**
- `docs/thor_manual_tasks.md` contains the Phase 14 manual integration section
- All 11 manual steps documented with rollback instructions
- "DO NOT AUTOMATE" markers present
- `litellm/config.yml` is unmodified
- No production files modified, no container changes

**Done when:**
- Phase 14 manual integration steps are fully documented in `docs/thor_manual_tasks.md` with rollback procedures. No production files were modified.

---
