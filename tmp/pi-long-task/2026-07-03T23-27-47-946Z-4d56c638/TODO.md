# Pi Long Task TODO

3. Include ## Progress section with unchecked lines
4. Include --- separator before task sections
5. Sequential sections named ## TODO N — Title
6. Each task section must include **Goal:**, **Status:** with unchecked checkbox items, **Verify:**, and **Done when:**
7. Preserve global instructions/constraints above ## Progress
8. Keep tasks focused and independently assignable

Let me map out the 7 tasks:

1. Phase 11 — Confirm Presenton Integration status
2. Phase 15.1 — Create Dockerfile for mcp_knowledge
3. Phase 15.2 — Change server.py from stdio to SSE transport
4. Phase 15.3 — Create compose/compose.mcp.yml
5. Phase 15.4 — Create draft LiteLLM config update
6. Phase 15.5 — Build and test the mcp_knowledge container standalone
7. Phase 15.6 — STOP and document manual tasks

I need to preserve the CRITICAL CONSTRAINT above ## Progress.
</think>


CRITICAL CONSTRAINT: Do NOT modify litellm/config.yml (the live config) and do NOT restart the litellm container. Any LiteLLM config changes go into litellm/draft/ only.

Global instructions:
- Long task goal: Execute Phase 11 (Presenton Integration — confirm status) and Phase 15 (Containerize mcp_knowledge). CRITICAL CONSTRAINT: Do NOT modify litellm/config.yml (the live config) and do NOT restart the litellm container. Any LiteLLM config changes go into litellm/draft/ only. TODO: 1. **Phase 11 — Confirm Presenton Integration status** - Read skills/presentation_build/skill.py to confirm it's fully implemented - Read docs/thor_presenton_integration.md (already exists from earlier) - Update thor_todo.md Phase 11 status to "Done" if the skill is complete - If anything is missing, implement it 2. **Phase 15.1 — Create Dockerfile for mcp_knowledge** - Create mcp/servers/knowledge/Dockerfile - Use python:3.12-slim as base - Install dependencies from pyproject.toml (mcp, qdrant-client) - Set WORKDIR to /app - COPY server.py and pyproject.toml - CMD should run the server with SSE transport - Expose port 8000 3. **Phase 15.2 — Change server.py from stdio to SSE transport** - Edit mcp/servers/knowledge/server.py - Change `mcp.run(transport="stdio")` to `mcp.run(transport="sse")` - Update the `main()` docstring - Ensure the server binds to 0.0.0.0:8000 for the container (FastMCP SSE defaults to port 8000) 4. **Phase 15.3 — Create compose/compose.mcp.yml** - New compose file for MCP server containers - Define `mcp_knowledge` service: - Build from mcp/servers/knowledge/ - Container name: mcp_knowledge - Network: ai-net - No host port binding (LiteLLM will call it on Docker network) - Environment: QDRANT_URL=http://qdrant:6333, QDRANT_TIMEOUT=15 - Restart: unless-stopped - Keep it ready for future MCP servers (mcp_crawl, etc.) 5. **Phase 15.4 — Create draft LiteLLM config update** - Create litellm/draft/config.phase15.yml showing what config.yml should look like AFTER containerization - Change mcp_knowledge entry from stdio to SSE: ```yaml mcp_knowledge: url: http://mcp_knowledge:8000/mcp transport: sse allow_all_keys: true ``` - Keep mcp_search as stdio (unchanged for now) - Add clear comment that this is a DRAFT for Chuck to apply manually - Do NOT modify the live litellm/config.yml 6. **Phase 15.5 — Build and test the mcp_knowledge container standalone** - `docker compose -f compose/compose.mcp.yml build mcp_knowledge` - `docker compose -f compose/compose.mcp.yml up -d mcp_knowledge` - Test SSE endpoint directly: `curl -s http://localhost:8000/mcp -H "Accept: text/event-stream"` (should get SSE messages) - Test a tool call: send an MCP JSON-RPC request to the SSE endpoint for `kb_list_collections` - Verify the container can reach Qdrant on the ai-net network - Check logs: `docker logs mcp_knowledge` - If the container works standalone, Phase 15 code is complete 7. **Phase 15.6 — STOP and document manual tasks** - The next step (applying the SSE config to LiteLLM) requires restarting litellm - Write a MANUAL TASK block for Chuck in litellm/draft/README.phase15.md with exact steps - Update thor_todo.md Phase 15 status - Do NOT restart litellm - Do NOT modify live litellm/config.yml

## Progress

- [x] TODO 1 — Phase 11: Confirm Presenton Integration status
- [x] TODO 2 — Phase 15.1: Create Dockerfile for mcp_knowledge
- [x] TODO 3 — Phase 15.2: Change server.py from stdio to SSE transport
- [x] TODO 4 — Phase 15.3: Create compose/compose.mcp.yml
- [x] TODO 5 — Phase 15.4: Create draft LiteLLM config update
- [x] TODO 6 — Phase 15.5: Build and test the mcp_knowledge container standalone
- [x] TODO 7 — Phase 15.6: STOP and document manual tasks

---

## TODO 1 — Phase 11: Confirm Presenton Integration status

**Goal:** Verify the Presenton integration is fully implemented and update the Phase 11 status in thor_todo.md.

**Status:**
- [x] Read skills/presentation_build/skill.py to confirm it is fully implemented
- [x] Read docs/thor_presenton_integration.md to review prior integration documentation
- [x] Update thor_todo.md Phase 11 status to "Done" if the skill is complete
- [x] If anything is missing, implement the missing pieces

**Verify:** The skill module runs without errors; thor_todo.md reflects Phase 11 as "Done" (or missing items are implemented).

**Done when:** Phase 11 status is accurately confirmed as Done or completed in thor_todo.md.

---

## TODO 2 — Phase 15.1: Create Dockerfile for mcp_knowledge

**Goal:** Create a Dockerfile to containerize the mcp_knowledge server.

**Status:**
- [x] Create mcp/servers/knowledge/Dockerfile
- [x] Use python:3.12-slim as base image
- [x] Install dependencies from pyproject.toml (mcp, qdrant-client)
- [x] Set WORKDIR to /app
- [x] COPY server.py and pyproject.toml into the image
- [x] Set CMD to run the server with SSE transport
- [x] Expose port 8000

**Verify:** Dockerfile builds successfully: `docker build -t mcp_knowledge -f mcp/servers/knowledge/Dockerfile mcp/servers/knowledge/`

**Done when:** Dockerfile exists and builds without errors.

---

## TODO 3 — Phase 15.2: Change server.py from stdio to SSE transport

**Goal:** Update the mcp_knowledge server to use SSE transport instead of stdio for container deployment.

**Status:**
- [x] Edit mcp/servers/knowledge/server.py
- [x] Change `mcp.run(transport="stdio")` to `mcp.run(transport="sse")`
- [x] Update the `main()` docstring to reflect SSE transport
- [x] Ensure the server binds to 0.0.0.0:8000 (FastMCP SSE defaults)

**Verify:** The server starts and listens on 0.0.0.0:8000 with SSE transport when run locally.

**Done when:** server.py uses SSE transport and is ready for containerization.

---

## TODO 4 — Phase 15.3: Create compose/compose.mcp.yml

**Goal:** Create a Docker Compose file dedicated to MCP server containers.

**Status:**
- [x] Create compose/compose.mcp.yml
- [x] Define `mcp_knowledge` service:
  - [x] Build from mcp/servers/knowledge/
  - [x] Container name: mcp_knowledge
  - [x] Network: ai-net
  - [x] No host port binding (LiteLLM calls it on Docker network)
  - [x] Environment: QDRANT_URL=http://qdrant:6333, QDRANT_TIMEOUT=15
  - [x] Restart: unless-stopped
- [x] Structure the file to be extensible for future MCP servers (mcp_crawl, etc.)

**Verify:** `docker compose -f compose/compose.mcp.yml config` parses without errors.

**Done when:** compose.mcp.yml exists with a correctly defined mcp_knowledge service.

---

## TODO 5 — Phase 15.4: Create draft LiteLLM config update

**Goal:** Create a draft LiteLLM config showing the post-containerization changes, without touching the live config.

**Status:**
- [x] Create litellm/draft/config.phase15.yml
- [x] Show what config.yml should look like AFTER containerization
- [x] Change mcp_knowledge entry from stdio to SSE:
  ```yaml
  mcp_knowledge:
    url: http://mcp_knowledge:8000/mcp
    transport: sse
    allow_all_keys: true
  ```
- [ ] Keep mcp_search as stdio (unchanged)
- [ ] Add a clear DRAFT comment indicating this is for Chuck to apply manually
- [ ] Do NOT modify litellm/config.yml

**Verify:** litellm/draft/config.phase15.yml exists, litellm/config.yml is unmodified.

**Done when:** Draft config file is created with SSE entry for mcp_knowledge and a clear manual-apply notice.

---

## TODO 6 — Phase 15.5: Build and test the mcp_knowledge container standalone

**Goal:** Build the container, run it, and verify SSE endpoint and tool calls work correctly.

**Status:**
- [x] Run `docker compose -f compose/compose.mcp.yml build mcp_knowledge`
- [x] Run `docker compose -f compose/compose.mcp.yml up -d mcp_knowledge`
- [x] Test SSE endpoint: `curl -s http://localhost:8000/mcp -H "Accept: text/event-stream"` (should return SSE messages)
- [x] Test a tool call: send an MCP JSON-RPC request to the SSE endpoint for `kb_list_collections`
- [x] Verify the container can reach Qdrant on the ai-net network
- [x] Check logs: `docker logs mcp_knowledge`
- [x] If everything works, Phase 15 code is complete

**Verify:** Container builds, starts, serves SSE on port 8000, responds to tool calls, and connects to Qdrant successfully.

**Done when:** All tests pass and mcp_knowledge runs reliably in a container.

---

## TODO 7 — Phase 15.6: STOP and document manual tasks

**Goal:** Stop automation here and document the remaining manual steps for Chuck, without restarting LiteLLM or modifying the live config.

**Status:**
- [x] Write a MANUAL TASK block in litellm/draft/README.phase15.md with exact steps for Chuck to apply the SSE config to LiteLLM
- [x] Update thor_todo.md Phase 15 status
- [x] Do NOT restart litellm
- [x] Do NOT modify live litellm/config.yml

**Verify:** litellm/draft/README.phase15.md exists with clear manual instructions; thor_todo.md Phase 15 is updated; litellm/config.yml is untouched.

**Done when:** Documentation is written, Phase 15 status is updated, and no live configs or containers were modified.
