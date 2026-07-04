# Thor AI Platform - Status & Remaining Work

> Updated: 2026-07-04
> Replaces: thor_todo.md (completed phases 0-15)

---

## Current State

### ✅ Completed

- **LiteLLM v1.92.0** running with 6 MCP servers via streamable-http transport
- **11 tools** verified at `/v1/mcp/tools` across all MCP servers
- **MCP servers containerized** (6 active on `ai-net`):
  - `mcp_search` (SearXNG), `mcp_knowledge` (Qdrant), `mcp_crawl` (Crawl4AI)
  - `mcp_filesystem_readonly`, `mcp_mysql`, `mcp_homelab_status`
- **Skill Runner** containerized & deployed (`compose.skill-runner.yml`, port 8091)
- **Skills implemented** (10 total):
  - `siri_ask`, `deep_research`, `presentation_build`, `demo_workflow`
  - `investment_brief`, `morning_brief`, `homelab_report`
  - `family_kb_ingest` (approval gate), `code_review`, `repo_maintenance` (approval gate)
- **Siri API** fully functional (`siri.choukalos.com`):
  - Chat, research, deep research, image generation
  - Demo pipeline (create/list/find/quality/complexity)
  - Presentation pipeline (create/update/list/find)
- **Documentation** current (`README.md`, `README_SIRI.md`, `siri-script.sh`)
- **Metrics endpoint** working (auth bypass in `litellm_settings`)

### ⚠️ Blocked

- **Open WebUI MCP integration** — version mismatch (servers v1.28.1, OWUI v1.27.2).
  Decision: skip for now, use LiteLLM proxy. Revisit on OWUI upgrade.

---

## Remaining Work

### Caddy / Cloudflare — Skill Runner Public Routing (Next)

Caddy still routes `siri.choukalos.com` to the legacy harness (`:8090`).
When ready for cutover:
- Update Caddy to route to skill runner (`:8091`)
- Update Cloudflare Tunnel config if needed
- Keep legacy harness as fallback during transition

### Per-Key Access Hardening (Deferred)

Currently all MCP servers use `allow_all_keys: true`. Replace with scoped grants when ready:

```yaml
mcp_search:
  transport: http
  url: http://mcp_search:8000/mcp
  allowed_keys:
    - chuck
    - son
    - openwebui
    - siri
    - automation
```

Repeat for each MCP server with appropriate key restrictions.

### Additional MCP Servers (Future)

- `mcp_code` — coding workflows (repo listing, code search, git operations)
- `mcp_stocks` — financial data (README stub exists)
- `mcp_media` — media/artifact management (README stub exists)
- `mcp_home` — smart home integration (README stub exists)

### Additional Skills (Future)

- `morning_brief` — already implemented, add more channel integrations
- `homelab_report` — already implemented, add more channel integrations
- `code_review` — already implemented, add more channel integrations
- `repo_maintenance` — already implemented, add more channel integrations
- `family_kb_ingest` — already implemented, add more channel integrations

---

## Verification Checklist (After Any Changes)

1. Pre-flight: Confirm backup exists, `ai-net` active
2. LiteLLM health: `/health/readiness` returns 200
3. MCP tools: `GET /v1/mcp/tools` returns 11 tools
4. Tool calls: Test via `/v1/chat/completions`
5. Public services: Open WebUI, `llm.choukalos.com`, `siri.choukalos.com`
6. Metrics: `GET /metrics/` returns 200
7. MCP containers: All 6 containers `Up`
8. Skill Runner: `GET http://thor.local:8091/health` returns `{"status": "ok"}`
