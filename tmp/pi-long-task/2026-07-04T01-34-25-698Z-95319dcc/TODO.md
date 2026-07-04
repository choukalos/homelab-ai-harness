# Pi Long Task TODO

# Pi Long Task TODO`
2. Include `## Progress` section with unchecked checkboxes
3. Include `---` separator before task sections
4. Create sequential sections named `## TODO N — Title`
5. Each task section must include **Goal:**, **Status:** with unchecked checkbox items, **Verify:** with concrete verification guidance, and **Done when:**
6. Preserve global instructions/constraints above `## Progress`
7. Output only markdown, no commentary, no code fence

Let me identify the 5 tasks and break them down into sub-items for the Status sections.
</think>


## Key decisions (apply to all tasks)
- All containerized servers follow the same pattern as `mcp_knowledge`: `python:3.12-slim`, pip install from `pyproject.toml`, `COPY server.py`
- SSE transport for all containerized servers: `transport="sse"` with `host="0.0.0.0"` in FastMCP constructor
- FastMCP name matches the `mcp_` prefix (e.g., `mcp_crawl`, `mcp_filesystem_readonly`)
- Do NOT modify the live `litellm/config.yml` — only update the draft config
- `mcp_crawl` uses the existing Crawl4AI container already running on port 11235
- `mcp_filesystem_readonly` needs volume mounts in compose to access host files
- `mcp_search` containerization follows the exact same pattern as `mcp_knowledge`

Global instructions:
- Long task goal: Implement Phase 12 (Observability Plan doc), Phase 13 (Integration Readiness doc), containerize mcp_search (SSE transport), and build mcp_crawl and mcp_filesystem_readonly MCP servers.

## Progress

- [x] TODO 1 — Create thor_observability_plan.md
- [x] TODO 2 — Create thor_integration_readiness.md
- [x] TODO 3 — Containerize mcp_search (SSE transport)
- [x] TODO 4 — Build mcp_crawl MCP server
- [x] TODO 5 — Build mcp_filesystem_readonly MCP server

---

## TODO 1 — Create thor_observability_plan.md

**Goal:** Create `docs/thor_observability_plan.md` documenting the full observability plan.

**Status:**
- [x] Document LiteLLM usage logs
- [x] Document per-key usage tracking
- [x] Document tool-call logs
- [x] Document skill job logs
- [x] Document artifact logs
- [x] Document token counts
- [x] Document context size tracking
- [x] Document latency metrics
- [x] Document tool error rates
- [x] Document timeout rates
- [x] Document model error rates
- [x] Document public endpoint access logs

**Verify:** Open `docs/thor_observability_plan.md` and confirm all 12 observability topics are covered with actionable descriptions.

**Done when:** The file exists at `docs/thor_observability_plan.md` with all 12 sections written and reviewed.

---

## TODO 2 — Create thor_integration_readiness.md

**Goal:** Create `docs/thor_integration_readiness.md` as a checklist covering all items from `thor_todo.md`.

**Status:**
- [x] Review `docs/thor_todo.md` for all readiness items
- [x] Add checklist item: backup exists
- [x] Add checklist item: AI inventory complete
- [x] Add checklist item: channel architecture complete
- [x] Add checklist item: public access model complete
- [x] Add checklist item: model alias registry complete
- [x] Add checklist item: artifact strategy complete
- [x] Add checklist item: harness rebuild plan complete
- [x] Add checklist item: MCP search works in LiteLLM
- [x] Add checklist item: MCP knowledge works in LiteLLM
- [x] Add checklist item: skill runner works locally
- [x] Add checklist item: first skills work locally
- [x] Add checklist item: draft LiteLLM config applied and tested
- [x] Add checklist item: rollback instructions exist
- [x] Add checklist item: manual tasks documented

**Verify:** Open `docs/thor_integration_readiness.md` and confirm all 14 checklist items are present with checkboxes matching the scope from `thor_todo.md`.

**Done when:** The file exists at `docs/thor_integration_readiness.md` with all 14 checklist items documented.

---

## TODO 3 — Containerize mcp_search (SSE transport)

**Goal:** Convert `mcp_search` from stdio to SSE transport and add it as a Docker Compose service, updating the draft LiteLLM config.

**Status:**
- [x] Create `mcp/servers/search/Dockerfile` using `mcp_knowledge` pattern (`python:3.12-slim`, pip install from `pyproject.toml`, `COPY server.py`)
- [x] Modify `mcp/servers/search/server.py`: change `transport="stdio"` to `transport="sse"`
- [x] Modify `mcp/servers/search/server.py`: add `host="0.0.0.0"` to the FastMCP constructor
- [x] Add `mcp_search` service to `compose/compose.mcp.yml`
- [x] Update `litellm/draft/config.phase15.yml`: change mcp_search from stdio to SSE with `url: http://mcp_search:8000/sse`
- [x] Add `mcp_search` to the ai-net network in the compose file

**Verify:**
- `docker compose -f compose/compose.mcp.yml --profile mcp_search up --build mcp_search` builds and starts successfully
- `litellm/draft/config.phase15.yml` shows mcp_search using `transport: sse` with URL `http://mcp_search:8000/sse`
- `mcp/servers/search/server.py` has `transport="sse"` and `host="0.0.0.0"`

**Done when:** mcp_search builds, runs as a container on SSE transport, and is reachable in the draft LiteLLM config on the ai-net network.

---

## TODO 4 — Build mcp_crawl MCP server

**Goal:** Create the `mcp_crawl` MCP server that wraps Crawl4AI for fetching and extracting web pages.

**Status:**
- [x] Create `mcp/servers/crawl/server.py` with tool `crawl_page(url, format?, max_chars?)`
- [x] Implement fetch logic against Crawl4AI at `http://crawl4ai:11235` (`/md` for markdown, `/crawl` for HTML)
- [x] Add security: block internal IPs (192.168.x.x, 10.x.x.x, 172.16-31.x.x) from being crawled
- [x] Add rate limit: 10 concurrent crawls max
- [x] Add max chars limit: 50000
- [x] Create `mcp/servers/crawl/pyproject.toml` with deps: `mcp`, `httpx`
- [x] Create `mcp/servers/crawl/Dockerfile` (`python:3.12-slim`, pip install, COPY server.py)
- [x] Add `mcp_crawl` service to `compose/compose.mcp.yml` (uncommented, SSE transport)
- [x] Update `litellm/draft/config.phase15.yml` to add `mcp_crawl` with `url: http://mcp_crawl:8000/sse`, `transport: sse`
- [x] Update `mcp/servers/crawl/README.md`

**Verify:**
- `docker compose -f compose/compose.mcp.yml build mcp_crawl` succeeds
- `crawl_page` with an external URL returns markdown content
- `crawl_page` with an internal IP (e.g., `192.168.1.1`) returns an error
- `crawl_page` with a page exceeding 50000 chars is truncated
- Draft config shows `mcp_crawl` with SSE transport and correct URL

**Done when:** mcp_crawl builds, runs as a container, serves SSE on port 8000, and is registered in the draft LiteLLM config.

---

## TODO 5 — Build mcp_filesystem_readonly MCP server

**Goal:** Create the `mcp_filesystem_readonly` MCP server for safe, read-only file system access with volume mounts.

**Status:**
- [x] Create `mcp/servers/filesystem_readonly/server.py` with tool `read_file(path)` (max 1MB)
- [x] Add tool `list_directory(path)` to list directory contents
- [x] Add tool `search_files(pattern, path?)` for glob search in allowed dirs
- [x] Restrict allowed paths to: `/home/chuck/workspace`, `/home/chuck/data/media`
- [x] Create `mcp/servers/filesystem_readonly/pyproject.toml` with deps: `mcp`
- [x] Create `mcp/servers/filesystem_readonly/Dockerfile` (`python:3.12-slim`, pip install, COPY server.py)
- [x] Add `mcp_filesystem_readonly` service to `compose/compose.mcp.yml` with volume mounts for both allowed paths
- [x] Update `litellm/draft/config.phase15.yml` to add `mcp_filesystem_readonly` with SSE transport
- [x] Update `mcp/servers/filesystem_readonly/README.md`

**Verify:**
- `docker compose -f compose/compose.mcp.yml build mcp_filesystem_readonly` succeeds
- `read_file` with a path outside the allowed dirs returns an error
- `read_file` with a file >1MB returns an error
- `list_directory` and `search_files` work within allowed paths
- Volume mounts in compose are correct for `/home/chuck/workspace` and `/home/chuck/data/media`
- Draft config shows the server registered with SSE transport

**Done when:** mcp_filesystem_readonly builds, runs as a container with correct volume mounts, enforces path restrictions, and is registered in the draft LiteLLM config.
