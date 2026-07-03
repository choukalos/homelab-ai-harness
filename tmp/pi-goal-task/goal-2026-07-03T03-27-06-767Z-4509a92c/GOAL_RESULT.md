# Pi Goal Task Result

Run: goal-2026-07-03T03-27-06-767Z-4509a92c
Goal: Implement phases 6 through 14 of thor_todo.md for the homelab project at /home/chuck/homelab.

Follow these absolute rules from thor_todo.md:
- Do NOT restart, rebuild, replace, or reconfigure LiteLLM, Open WebUI, Qdrant, Redis, Caddy, Cloudflare Tunnel, or the AI Harness
- Do NOT modify production Caddy, LiteLLM, Cloudflare, or compose files
- Do NOT run homelab.sh down/rebuild
- Do NOT modify .env directly
- Do NOT expose new public endpoints or bind new services to production ports
- Do NOT delete containers, volumes, images, networks, or data
- Do NOT run database migrations or package upgrades on production
- Do NOT change ownership or permissions on production paths
- Do NOT run destructive Git commands
- Do NOT copy draft configs into live LiteLLM config
- Create new files, new directories, draft configs, documentation, MCP server code, skill runner code, test scripts — these are all allowed
- Run static validation, unit tests, local scripts that don't touch production
- Phase 14 is manual only — do NOT perform production integration

PHASE 6 - Build First MCP Server: Search
- Create mcp/servers/search/ with a working Python MCP server using the MCP Python SDK (mcp library, stdio transport)
- Tools: search_web(query, max_results), search_recent(query, days, max_results), search_news(query, max_results)
- Backend: SearXNG (check existing Docker state or config for the SearXNG endpoint URL)
- Requirements: result limits, timeouts, compact output, no crawling, no browser automation, no writes
- Include README.md, server.py, pyproject.toml (or package.json), tests/, examples/

PHASE 7 - Build Knowledge MCP Server
- Create mcp/servers/knowledge/ with a working Python MCP server
- Tools: kb_search(query, top_k, collection), kb_get_document(doc_id), kb_list_collections(), kb_recent_changes(days)
- Rules: read-only, collection allowlist, curated collections only, no arbitrary file access, compact snippets, full docs only by doc_id, no reindexing
- Backend: Qdrant (check existing Docker state for Qdrant endpoint)
- Include README.md, server.py, pyproject.toml

PHASE 8 - Build Skill Runner Skeleton
- Create skills/runner/ with a FastAPI-based Python app
- Features: job model, job status, artifact path, logging, dry-run mode, approval gate support, tool bundle declaration, model alias declaration
- Endpoints: POST /skills/{skill_name}, GET /skills/jobs/{job_id}, GET /skills/jobs/{job_id}/artifact
- Dev port: 8091 (NOT 8090 which is the current Harness)
- Include README.md, main.py, pyproject.toml, requirements or dependencies

PHASE 9 - Implement First Skills
- siri_ask: Short mobile answers, safe status lookups, optional artifact links. Strict timeouts, no broad tools, no admin writes.
- deep_research: Repeatable research process, cited markdown report, artifact output. Summary, full report, source list, artifact path.
- presentation_build: Use Presenton through a controlled skill. Support remote use through Siri path. Keep Presenton LAN-only.
- Place skill implementations in their respective directories under skills/

PHASE 10 - Draft LiteLLM MCP Config
- Create draft files (DO NOT place in live config):
  - litellm/draft/mcp-search.example.yaml
  - litellm/draft/tool-bundles.example.yaml
  - litellm/draft/model-aliases.example.yaml
- Draft tool bundles: bundle_family, bundle_coding, bundle_research, bundle_investing, bundle_admin, bundle_siri
- Add a manual task for Chuck to the thor_manual_tasks.md for registering MCP tools with LiteLLM

PHASE 11 - Presenton Integration
- Document the integration in the presentation_build skill
- Presenton UI remains LAN-only
- presentation_build skill calls Presenton internally
- Remote use through Siri/skill path, not direct public Presenton exposure
- Check existing homelab for Presenton configuration to understand its endpoint

PHASE 12 - Observability Plan
- Create docs/thor_observability_plan.md covering: LiteLLM usage logs, per-key usage, tool-call logs, skill job logs, artifact logs, token counts, context size, latency, tool error rates, timeout rates, model error rates, public endpoint access logs

PHASE 13 - Integration Readiness Review
- Create docs/thor_integration_readiness.md with a comprehensive checklist as specified in thor_todo.md

PHASE 14 - Production Integration
- Mark as manual only in thor_manual_tasks.md and thor_todo.md
- Do NOT execute any production integration steps
- Document potential manual steps: backup live LiteLLM config, apply MCP config, reload/restart LiteLLM, test aliases, test Open WebUI, test MCP tools with test key, test Chuck/son/siri keys, test artifact retrieval, rollback if needed

Use the existing design docs in docs/ for references (thor_mcp_architecture.md, thor_skill_architecture.md, thor_ai_harness_rebuild.md, thor_model_alias_registry.md, thor_data_classification.md, thor_artifact_strategy.md).

Check the current SearXNG and Qdrant and Presenton Docker service names and ports from docs/state/ and existing config to use correct endpoints in the MCP servers and skills.
Started: 2026-07-03T03:27:06.767Z
State: /home/chuck/homelab/tmp/pi-goal-task/goal-2026-07-03T03-27-06-767Z-4509a92c/GOAL_STATE.json
Trace: /home/chuck/homelab/tmp/pi-goal-task/goal-2026-07-03T03-27-06-767Z-4509a92c/GOAL_TRACE.jsonl
Goal specification: /home/chuck/homelab/tmp/pi-goal-task/goal-2026-07-03T03-27-06-767Z-4509a92c/GOAL_SPEC.json

## Safety limits

- Minimum iterations before completion: 20
- Max iterations: 20
- Run timeout: 172800000ms
- Iteration timeout: 10800000ms
- Reviewer timeout: 1800000ms


## Iteration 1

Status: todo_generated
Started: 2026-07-03T03:27:06.808Z
Updated: 2026-07-03T03:30:45.750Z
Deadline: 2026-07-03T06:27:06.808Z

### Generated TODO

Path: /home/chuck/homelab/tmp/pi-goal-task/goal-2026-07-03T03-27-06-767Z-4509a92c/iterations/01/TODO.md
Summary: Generated TODO with 11 task(s).
