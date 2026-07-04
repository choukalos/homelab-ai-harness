# Thor AI Platform - Remaining Work

> Created: 2026-07-04
> Replaces: thor_todo.md (completed phases 0-15)

## Current State

- ✅ LiteLLM v1.92.0 running with 4 MCP servers via streamable-http transport
- ✅ All 11 tools verified at `/v1/mcp/tools`
- ✅ Metrics endpoint working (auth bypass in `litellm_settings`)
- ✅ Skills code complete (siri_ask, deep_research, presentation_build)
- ✅ Documentation complete (all thor_*.md docs created)
- ⚠️ Open WebUI MCP integration blocked (see below)

---

## Open WebUI MCP Integration - BLOCKED

### Issue

Open WebUI's built-in MCP client (v1.27.2) connects successfully to MCP servers but the persistent GET stream disconnects immediately after the initial handshake. Tools register in the admin panel but never appear in chat.

### Root Cause

MCP SDK version mismatch: servers use v1.28.1, Open WebUI uses v1.27.2. The GET stream for server→client messages is not stable across these versions.

### Options

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **A: LiteLLM proxy route** | Open WebUI talks to LiteLLM for tools; LiteLLM proxies to MCP | Already working, tested, no version issues | Need to configure in Open WebUI admin |
| **B: Update Open WebUI** | Newer Open WebUI image may have compatible MCP client | Future-proof | Risk of breaking other Open WebUI features |
| **C: Revert to SSE** | Change MCP servers back to `transport: sse` | Open WebUI handles SSE better | Lose streamable HTTP support |
| **D: Skip for now** | Use tools through LiteLLM `/v1/chat/completions` only | Everything works today | No MCP tools in Open WebUI chat UI |

### Decision

**Option D selected.** LiteLLM proxy has all 11 tools working. Revisit when Open WebUI updates its MCP client or we decide to upgrade Open WebUI.

---

## Remaining Work

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
- `mcp_stocks` — financial data
- `mcp_homelab_status` — infrastructure monitoring
- `mcp_media` — media/artifact management
- `mcp_home` — smart home integration

### Skill Runner Deployment

Code is complete but not deployed to production:
- `skills/runner/` needs to be containerized and added to compose
- Caddy config needs update to route `siri.choukalos.com` from port 8090 → 8091

### Additional Skills (Future)

- `code_review`
- `repo_maintenance`
- `family_kb_ingest`
- `morning_brief`
- `homelab_report`

---

## Verification Checklist (After Any Changes)

1. Pre-flight: Confirm backup exists, `ai-net` active
2. LiteLLM health: `/health/readiness` returns 200
3. MCP tools: `GET /v1/mcp/tools` returns 11 tools
4. Tool calls: Test via `/v1/chat/completions`
5. Public services: Open WebUI, `llm.choukalos.com`, `siri.choukalos.com`
6. Metrics: `GET /metrics/` returns 200
7. MCP containers: All 4 containers `Up`
