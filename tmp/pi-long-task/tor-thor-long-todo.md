# Pi Long Task TODO

Global instructions:

- Do NOT restart, rebuild, or modify LiteLLM or any production service
- All file changes are new files or files in draft/ directories
- Follow thor_todo.md structure and constraints
- Work is in /home/chuck/homelab/
- After all tasks, update thor_todo.md Phase 14 manual checklist with what Chuck needs to verify

## Progress

- [ ] TODO 1 — Phase 0: Read-Only Backup and Discovery
- [ ] TODO 2 — Phase 1: AI Capability Inventory
- [ ] TODO 3 — Phase 2: Channel Architecture
- [ ] TODO 4 — Phase 3: Public Access Model
- [ ] TODO 5 — Phase 4: Design Documents (Model Aliases, Data, Artifacts, Harness, MCP, Skills)
- [ ] TODO 6 — Phase 5: Create Skeleton Directories
- [ ] TODO 7 — Phase 6: Build MCP Search Server
- [ ] TODO 8 — Phase 7: Build MCP Knowledge Server
- [ ] TODO 9 — Phase 8: Build Skill Runner Skeleton
- [ ] TODO 10 — Phase 9: Implement First Skills (siri_ask, deep_research, presentation_build)
- [ ] TODO 11 — Phase 12: Observability Plan
- [ ] TODO 12 — Phase 13: Integration Readiness Review
- [ ] TODO 13 — Update Phase 14 manual checklist in thor_todo.md

---

## TODO 1 — Phase 0: Read-Only Backup and Discovery

**Goal:** Capture current Thor state without changing production.

**Status:**

- [ ] Create docs/thor_validation_log.md
- [ ] Create docs/thor_manual_tasks.md
- [ ] Create docs/state/ directory
- [ ] Run docker ps and save to docs/state/docker_ps.txt
- [ ] Run docker compose ls and save to docs/state/docker_compose_ls.txt
- [ ] Run docker network ls and save to docs/state/docker_network_ls.txt
- [ ] Run docker volume ls and save to docs/state/docker_volume_ls.txt

**Verify:**

- All state files exist in docs/state/
- Validation log and manual tasks docs created

**Done when:**

- All discovery artifacts are in place under docs/

## TODO 2 — Phase 1: AI Capability Inventory

**Goal:** Classify current Thor capabilities in docs/thor_ai_inventory.md.

**Status:**

- [ ] Create docs/thor_ai_inventory.md with inventory table

**Verify:**

- File exists with all 16 capabilities inventoried

**Done when:**

- docs/thor_ai_inventory.md is complete

## TODO 3 — Phase 2: Channel Architecture

**Goal:** Document all user-facing channels in docs/thor_channels_architecture.md.

**Status:**

- [ ] Create docs/thor_channels_architecture.md

**Verify:**

- All 10 channels documented with purpose, users, access path, allowed/disallowed capabilities, tool bundle, public/LAN status

**Done when:**

- docs/thor_channels_architecture.md is complete

## TODO 4 — Phase 3: Public Access Model

**Goal:** Make public exposure strategy explicit in docs/thor_public_access_model.md.

**Status:**

- [ ] Create docs/thor_public_access_model.md

**Verify:**

- Document covers public routes, LAN-only systems, remote-private, key strategy, monitoring

**Done when:**

- docs/thor_public_access_model.md is complete

## TODO 5 — Phase 4: Design Documents

**Goal:** Create all design documents from Phase 4.1 through 4.6.

**Status:**

- [ ] Create docs/thor_model_alias_registry.md
- [ ] Create docs/thor_data_classification.md
- [ ] Create docs/thor_artifact_strategy.md
- [ ] Create docs/thor_ai_harness_rebuild.md
- [ ] Create docs/thor_mcp_architecture.md
- [ ] Create docs/thor_skill_architecture.md

**Verify:**

- All 6 design documents exist and follow thor_todo.md specs

**Done when:**

- All Phase 4 docs are complete

## TODO 6 — Phase 5: Create Skeleton Directories

**Goal:** Add structure without running production services.

**Status:**

- [ ] Create mcp/, mcp/servers/, mcp/shared/, skills/, skills/runner/, litellm/draft/, docs/state/
- [ ] Create placeholder README.md files in each

**Verify:**

- All directories exist with README placeholders

**Done when:**

- All skeleton directories and READMEs are in place

## TODO 7 — Phase 6: Build MCP Search Server

**Goal:** Create mcp_search server with search_web, search_recent, search_news tools backed by SearXNG.

**Status:**

- [ ] Create mcp/servers/search/README.md
- [ ] Create mcp/servers/search/server.py (FastMCP, SSE transport, port 8000)
- [ ] Create mcp/servers/search/pyproject.toml
- [ ] Create mcp/servers/search/Dockerfile
- [ ] Create mcp/servers/search/tests/ with basic tests

**Verify:**

- Server code follows thor_todo.md rules (result limits, timeouts, compact output, no crawling)

**Done when:**

- mcp/servers/search/ is complete with all files

## TODO 8 — Phase 7: Build MCP Knowledge Server

**Goal:** Create mcp_knowledge server with kb_search, kb_get_document, kb_list_collections, kb_recent_changes tools backed by Qdrant.

**Status:**

- [ ] Create mcp/servers/knowledge/server.py (if not already done in Phase 15)
- [ ] Create mcp/servers/knowledge/Dockerfile (if not already done)
- [ ] Create mcp/servers/knowledge/pyproject.toml
- [ ] Create mcp/servers/knowledge/README.md
- [ ] Create mcp/servers/knowledge/tests/

**Verify:**

- Follows rules: read-only, collection allowlist, curated only, no arbitrary file access

**Done when:**

- mcp/servers/knowledge/ is complete (update existing Phase 15 files as needed)

## TODO 9 — Phase 8: Build Skill Runner Skeleton

**Goal:** Build the new Harness foundation with container and local dev modes.

**Status:**

- [ ] Create skills/runner/Dockerfile
- [ ] Create skills/runner/pyproject.toml
- [ ] Create skills/runner/main.py (FastAPI app)
- [ ] Create skills/runner/dev.sh
- [ ] Create skills/runner/README.md
- [ ] Create compose/compose.skill-runner.yml

**Verify:**

- Follows architecture: talks to LiteLLM for LLM + MCP calls, endpoints match spec
- Dev port is 8091, does not bind production port

**Done when:**

- skills/runner/ skeleton is complete with all files

## TODO 10 — Phase 9: Implement First Skills

**Goal:** Implement siri_ask, deep_research, and presentation_build skills.

**Status:**

- [ ] Create skills/siri_ask/skill.py, skill.yml, README.md
- [ ] Create skills/deep_research/skill.py, skill.yml, README.md
- [ ] Update skills/presentation_build/ (already done in Phase 11, ensure it follows new skill format)

**Verify:**

- Each skill has skill.py, skill.yml, README.md
- Follows skill execution pattern from thor_todo.md

**Done when:**

- All 3 skill directories are complete

## TODO 11 — Phase 12: Observability Plan

**Goal:** Create docs/thor_observability_plan.md.

**Status:**

- [ ] Create docs/thor_observability_plan.md

**Verify:**

- Covers all items from thor_todo.md: usage logs, per-key, tool calls, skill jobs, artifacts, tokens, latency, errors, timeouts

**Done when:**

- docs/thor_observability_plan.md is complete

## TODO 12 — Phase 13: Integration Readiness Review

**Goal:** Create docs/thor_integration_readiness.md with updated checklist.

**Status:**

- [ ] Create docs/thor_integration_readiness.md
- [ ] Mark completed items from this run
- [ ] Mark remaining items as pending

**Verify:**

- Checklist accurately reflects what was done vs what still needs manual verification

**Done when:**

- docs/thor_integration_readiness.md is complete with accurate status

## TODO 13 — Update Phase 14 Manual Checklist

**Goal:** Update thor_todo.md Phase 14 "Next steps (manual)" with the full list of manual verification tasks Chuck needs to do after restarting LiteLLM.

**Status:**

- [ ] Add verification checklist items for: restart litellm, verify /v1/mcp/tools returns all 11 tools, test MCP tool calls through /v1/chat/completions, verify Open WebUI still works, verify llm.choukalos.com still works, verify siri.choukalos.com still works, verify metrics endpoint returns 200
- [ ] Add rollback instructions
- [ ] Update thor_todo.md Phase 14 section

**Verify:**

- Phase 14 in thor_todo.md has comprehensive manual checklist

**Done when:**

- thor_todo.md Phase 14 is updated with complete manual tasks
