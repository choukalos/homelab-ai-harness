# Phase 15 — mcp_knowledge Containerization (Manual Steps)

> **Status:** Code changes are complete. The remaining steps require a LiteLLM restart and must be performed manually by Chuck.

## What Was Done (Automated)

The Pi SDK session completed the following Phase 15 subtasks:

- **Phase 15.1** — Created `mcp/servers/knowledge/Dockerfile` (python:3.12-slim, SSE transport, port 8000)
- **Phase 15.2** — Changed `mcp/servers/knowledge/server.py` from `transport="stdio"` to `transport="sse"`
- **Phase 15.3** — Created `compose/compose.mcp.yml` with `mcp_knowledge` service on `ai-net`
- **Phase 15.4** — Created `litellm/draft/config.phase15.yml` (draft SSE config for LiteLLM)
- **Phase 15.5** — Built and tested the `mcp_knowledge` container standalone (verified SSE endpoint and tool calls)

**Result:** `litellm/config.yml` was **not** modified. The LiteLLM container was **not** restarted.

---

## MANUAL TASK FOR CHUCK: Apply SSE Config to LiteLLM

The next step requires updating LiteLLM's live config to point `mcp_knowledge` at its new container endpoint and restarting LiteLLM. This **must be done manually**.

### Prerequisites

1. Verify the `mcp_knowledge` container is running:
   ```bash
   docker compose -f compose/compose.mcp.yml ps
   ```

2. If not running, start it:
   ```bash
   docker compose -f compose/compose.mcp.yml up -d mcp_knowledge
   ```

3. Verify it responds on the Docker network:
   ```bash
   docker exec litellm-proxy curl -s http://mcp_knowledge:8000/sse -H "Accept: text/event-stream" | head -5
   ```

### Step 1: Back up the live config

```bash
cp /home/chuck/homelab/litellm/config.yml /home/chuck/homelab/litellm/config.yml.bak.phase15
```

### Step 2: Review the draft config

```bash
diff /home/chuck/homelab/litellm/config.yml /home/chuck/homelab/litellm/draft/config.phase15.yml
```

**Expected diff:** The `mcp_knowledge` block changes from stdio (with `command`, `args`, `env`) to SSE (`url: http://mcp_knowledge:8000/sse`, `transport: sse`). All other config should be identical.

### Step 3: Apply the draft config

```bash
cp /home/chuck/homelab/litellm/draft/config.phase15.yml /home/chuck/homelab/litellm/config.yml
```

### Step 4: Restart LiteLLM

```bash
cd /home/chuck/homelab
docker compose -f compose/compose.ai-core.yml restart litellm-proxy
```

### Step 5: Validate MCP tools

```bash
# List available tools (replace YOUR_API_KEY):
curl -s -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:4000/mcp-rest/tools/list | python3 -m json.tool

# Test kb_list_collections via the SSE container:
curl -s -X POST -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tool":"kb_list_collections","arguments":{}}' \
  http://localhost:4000/mcp-rest/tools/call | python3 -m json.tool
```

### Step 6: Validate existing services

- Open WebUI should still load and chat
- `llm.choukalos.com` should still work
- `siri.choukalos.com` should still work
- Existing model aliases (matrix-coder, etc.) should still resolve

### Step 7: Check mcp_knowledge container logs

```bash
docker logs mcp_knowledge --tail 30
```

Look for SSE connection events from LiteLLM.

---

## Rollback

If anything breaks after the restart:

```bash
# Restore the backup config
cp /home/chuck/homelab/litellm/config.yml.bak.phase15 /home/chuck/homelab/litellm/config.yml

# Restart LiteLLM with the old (stdio) config
cd /home/chuck/homelab
docker compose -f compose/compose.ai-core.yml restart litellm-proxy

# Optionally stop the mcp_knowledge container (no longer needed with stdio)
docker stop mcp_knowledge
```

---

## Architecture After Apply

```
LiteLLM (:4000)  →  SSE (HTTP)  →  mcp_knowledge container (:8000)
                                       ↓
                                   Qdrant (:6333)
```

- `mcp_search` remains on stdio (unchanged)
- `mcp_knowledge` now runs in its own container with isolated dependencies
- Future MCP servers will follow the same pattern (see `compose/compose.mcp.yml`)

---

## Phase 14 Deferral Reminder

Both `mcp_search` and `mcp_knowledge` currently use `allow_all_keys: true`. Per-key access restrictions are deferred to Phase 14.
