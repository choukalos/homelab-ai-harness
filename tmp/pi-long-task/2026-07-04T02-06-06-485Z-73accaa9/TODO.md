# Pi Long Task TODO

3. Include ## Progress section with unchecked checkboxes
4. --- separator before task sections
5. Sequential sections ## TODO N — Title
6. Each section: **Goal:**, **Status:** (unchecked checkboxes), **Verify:**, **Done when:**
7. Preserve global instructions/constraints above ## Progress
8. Keep tasks focused and independently assignable

The raw input has 5 steps but also some global context about the SSE protocol and the overall goal. Let me map these out:

- Overall goal: Fix skill runner to use direct SSE instead of LiteLLM's /mcp-rest/tools/call
- Global context: SSE protocol description, important notes about httpx usage
- Task 1: Add _mcp_call_sse method
- Task 2: Replace async mcp_call body
- Task 3: Update Dockerfile with env vars
- Task 4: Rebuild and test

I'll note that step 4 from the raw input ("Keep the sync mcp_call wrapper unchanged") is more of a constraint/reminder than a separate task - it applies to Task 2. So I'll include it as a note in the relevant task.

Let me structure this properly.
</think>


Overall goal: Fix the skill runner to call MCP servers via direct SSE instead of LiteLLM's /mcp-rest/tools/call (which has an allow_all_keys auth bug in LiteLLM 1.82.6).

Global constraints — SSE protocol details:
- GET /sse returns a text/event-stream. First event is "event: endpoint" followed by "data: /messages/?session_id=XXXXX"
- Then POST to {base_url} + endpoint_path with the JSON-RPC body
- The response is also SSE: "event: message" followed by "data: {json-rpc response}"
- Use httpx.AsyncClient with stream=True for both calls
- Parse SSE manually by reading lines and checking for "event:" and "data:" prefixes

Global instructions:
- Long task goal: Fix the skill runner to call MCP servers via direct SSE instead of LiteLLM's /mcp-rest/tools/call (which has an allow_all_keys auth bug in LiteLLM 1.82.6). 1. In skills/runner/main.py, add a new method to LiteLLMClient called `_mcp_call_sse(self, server_id, tool_name, arguments)` that: - Looks up the MCP server URL from environment variable `MCP_SERVER_<name>_URL` where name is server_id without the "mcp_" prefix (e.g., `MCP_SERVER_KNOWLEDGE_URL`) - Falls back to `http://<server_id>:8000` if no env var is set - Uses httpx.AsyncClient to stream GET /sse and parse the first `event: endpoint` line to extract the POST URL - Constructs a JSON-RPC 2.0 request: {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}} - POSTs to the endpoint URL and streams the response to parse `event: message` for the JSON-RPC result - Parses the result content from the response - Returns the same dict format as the existing mcp_call: {"output": [...], "is_error": bool} 2. Replace the body of `LiteLLMClient.mcp_call` (the async version around line 230) to call `_mcp_call_sse` instead of the REST endpoint. Keep the same method signature and return format. 3. Add environment variable defaults to the Dockerfile for MCP server URLs: - MCP_SERVER_SEARCH_URL=http://mcp_search:8000 - MCP_SERVER_KNOWLEDGE_URL=http://mcp_knowledge:8000 - MCP_SERVER_CRAWL_URL=http://mcp_crawl:8000 - MCP_SERVER_FILESYSTEM_READONLY_URL=http://mcp_filesystem_readonly:8000 4. Rebuild the skill-runner container and test by calling deep_research (non-dry-run). Important: The SSE protocol works like this: - GET /sse returns a text/event-stream. First event is "event: endpoint" followed by "data: /messages/?session_id=XXXXX" - Then POST to {base_url} + endpoint_path with the JSON-RPC body - The response is also SSE: "event: message" followed by "data: {json-rpc response}" - Use httpx.AsyncClient with stream=True for both calls - Parse SSE manually by reading lines and checking for "event:" and "data:" prefixes

## Progress

- [x] TODO 1 — Add `_mcp_call_sse` method to `LiteLLMClient` for direct SSE MCP calls
- [x] TODO 2 — Replace async `mcp_call` body to use `_mcp_call_sse`
- [x] TODO 3 — Add MCP server URL environment variable defaults to Dockerfile
- [x] TODO 4 — Rebuild skill-runner container and test via `deep_research` (non-dry-run)

---

## TODO 1 — Add `_mcp_call_sse` method to `LiteLLMClient` for direct SSE MCP calls

**Goal:** Implement a new async method `_mcp_call_sse(self, server_id, tool_name, arguments)` on the `LiteLLMClient` class in `skills/runner/main.py` that calls MCP servers directly over SSE using `httpx.AsyncClient`.

**Status:**
- [x] Determine server URL from env var `MCP_SERVER_<name>_URL` (strip "mcp_" prefix from server_id, e.g. `MCP_SERVER_KNOWLEDGE_URL` for `mcp_knowledge`), falling back to `http://<server_id>:8000`
- [x] Use `httpx.AsyncClient` with `stream=True` to GET /sse and parse the first `event: endpoint` line to extract the POST endpoint path
- [x] Construct JSON-RPC 2.0 request: `{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}}`
- [x] POST the JSON-RPC request to `{base_url}{endpoint_path}` with streaming, and parse `event: message` lines for the JSON-RPC response
- [x] Parse the result content and return the same dict format as existing `mcp_call`: `{"output": [...], "is_error": bool}`
- [x] Ensure proper cleanup (closing streams/clients) even on errors

**Verify:**
- Confirm the method exists on `LiteLLMClient` and is async
- Verify env var lookup strips "mcp_" prefix correctly
- Verify SSE parsing extracts the endpoint path from `event: endpoint` / `data: ...`
- Verify the JSON-RPC request structure matches the spec
- Verify the return dict matches `{"output": [...], "is_error": bool}`

**Done when:** The `_mcp_call_sse` method is implemented and returns the correct format; manual or unit-level inspection confirms SSE handshake and JSON-RPC round-trip logic is correct.

---

## TODO 2 — Replace async `mcp_call` body to use `_mcp_call_sse`

**Goal:** Update the async `mcp_call` method (around line 230 in `skills/runner/main.py`) so its body delegates to `_mcp_call_sse` instead of calling LiteLLM's `/mcp-rest/tools/call` REST endpoint. Preserve the method signature and return format.

**Status:**
- [x] Locate the async `mcp_call` method in `skills/runner/main.py` (~line 230)
- [x] Replace its implementation body with a call to `await self._mcp_call_sse(server_id, tool_name, arguments)`
- [x] Keep the method signature and return type unchanged
- [x] Confirm the sync `mcp_call` wrapper (around line 335) is left untouched — it wraps the async version

**Verify:**
- The async `mcp_call` now calls `_mcp_call_sse` internally
- The sync `mcp_call` wrapper is unchanged and still functions as before
- Method signature of async `mcp_call` is preserved
- No other call sites break

**Done when:** The async `mcp_call` delegates to `_mcp_call_sse`, returns the same dict format, and the sync wrapper remains intact.

---

## TODO 3 — Add MCP server URL environment variable defaults to Dockerfile

**Goal:** Add `ENV` directives to the skill-runner Dockerfile with default MCP server URLs so `_mcp_call_sse` can resolve servers without explicit overrides.

**Status:**
- [x] Add `ENV MCP_SERVER_SEARCH_URL=http://mcp_search:8000`
- [x] Add `ENV MCP_SERVER_KNOWLEDGE_URL=http://mcp_knowledge:8000`
- [x] Add `ENV MCP_SERVER_CRAWL_URL=http://mcp_crawl:8000`
- [x] Add `ENV MCP_SERVER_FILESYSTEM_READONLY_URL=http://mcp_filesystem_readonly:8000`

**Verify:**
- Inspect the Dockerfile and confirm all four ENV lines are present
- Confirm the naming convention matches `MCP_SERVER_<name>_URL` with the correct service hostnames

**Done when:** All four environment variable defaults are present in the Dockerfile.

---

## TODO 4 — Rebuild skill-runner container and test via `deep_research` (non-dry-run)

**Goal:** Rebuild the skill-runner Docker image with the updated code and Dockerfile, then perform a real (non-dry-run) `deep_research` invocation to verify end-to-end SSE-based MCP tool calls work.

**Status:**
- [x] Rebuild the skill-runner Docker container
- [x] Deploy/restart the container in the homelab stack
- [x] Invoke `deep_research` with a non-dry-run call
- [x] Observe logs/output to confirm MCP tools are being called via SSE (not REST)
- [x] Verify the final result is correct and complete

**Verify:**
- Container builds without errors
- `deep_research` completes successfully in non-dry-run mode
- Logs show SSE-based calls (no `/mcp-rest/tools/call` endpoints in LiteLLM logs)
- Result output is well-formed and contains expected content

**Done when:** `deep_research` runs end-to-end successfully using the new SSE-based MCP calling path.
