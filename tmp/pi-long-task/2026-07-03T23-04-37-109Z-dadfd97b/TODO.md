# Pi Long Task TODO

3. Include ## Progress section with unchecked checkboxes
4. Include --- separator before task sections
5. Sequential sections ## TODO N — Title
6. Each task section: **Goal:**, **Status:** (unchecked checkboxes), **Verify:**, **Done when:**
7. Preserve global instructions above ## Progress
8. Keep tasks focused and independently assignable

Let me parse the raw input and structure it properly.

The overall goal is: "Implement Phase 9: Wire the skill runner to actually execute skill modules, and fix MCP call parameter mismatches."

4 tasks total. Let me create each one.

Task 1: Update `skills/runner/main.py` — add sync wrapper class
Task 2: Update `skills/runner/main.py` — rewrite `_execute_skill` to actually execute skills
Task 3: Fix `skills/deep_research/skill.py` — `server_name` → `server_id` in `_SyncLiteLLMClient.mcp_call`
Task 4: Rebuild and test

Let me structure each task with Goal, Status (checkboxes of sub-items), Verify, and Done when.
</think>


Overall goal: Implement Phase 9 — Wire the skill runner to actually execute skill modules, and fix MCP call parameter mismatches.

Global instructions:
- Long task goal: Implement Phase 9: Wire the skill runner to actually execute skill modules, and fix MCP call parameter mismatches. TODO: 1. **Update `skills/runner/main.py` — add sync wrapper class** - After the `LiteLLMClient` class (before `# Skill Execution` section), add a `_SyncLiteLLMWrapper` class that wraps the async `LiteLLMClient` for sync skill code - The wrapper must use `asyncio.new_event_loop()` (NOT `get_running_loop()`) to avoid "event loop already running" crashes in uvloop - Methods: `chat_completion(model, messages, **kwargs)` and `mcp_call(tool_name, arguments, server_id=None, **kwargs)` — note the param is `server_id` to match the runner's `LiteLLMClient` - Has a `base_url` property that delegates to the wrapped client 2. **Update `skills/runner/main.py` — rewrite `_execute_skill` to actually execute skills** - After finding `skill_path`, dynamically import the skill module using `importlib.util` - Create a `_SyncLiteLLMWrapper(litellm_client)` and pass it to `skill_module.run(params, job, client=sync_client)` - Map the skill's return dict back to job fields: `summary`, `artifact_path`, `error` - If the skill returns a result dict with keys like 'answer', 'report', 'sources', merge those into job params or logs - Handle ImportError as a job failure - Log the execution result properly - Keep the approval gate and dry_run logic intact 3. **Fix `skills/deep_research/skill.py` — `server_name` → `server_id` in `_SyncLiteLLMClient.mcp_call`** - The `_SyncLiteLLMClient.mcp_call` method currently sends `{"tool": ..., "server": ...}` to `/mcp-rest/tools/call` - Must be changed to `{"name": ..., "server_id": ...}` to match LiteLLM's API and the runner's wrapper - Same fix in all MCP helper functions: `_search_web`, `_search_recent`, `_search_news`, `_search_knowledge`, `_crawl_url` 4. **Rebuild and test** - `docker compose -f compose/compose.skill-runner.yml build && docker compose -f compose/compose.skill-runner.yml up -d skill-runner` - Test siri_ask (real, no dry_run): `curl -X POST http://localhost:8091/skills/siri_ask -H "Content-Type: application/json" -d '{"params":{"query":"what is 2+2?"}}'` - Test deep_research (dry_run first): `curl -X POST http://localhost:8091/skills/deep_research -H "Content-Type: application/json" -d '{"params":{"query":"test"},"dry_run":true}'` - Verify all 3 skills return "completed" status with actual summary text (not "skeleton placeholder")

## Progress

- [x] TODO 1 — Add `_SyncLiteLLMWrapper` class to `skills/runner/main.py`
- [x] TODO 2 — Rewrite `_execute_skill` to dynamically import and execute skill modules
- [x] TODO 3 — Fix `server_name` → `server_id` MCP parameter mismatch in `skills/deep_research/skill.py`
- [x] TODO 4 — Rebuild and test skill runner end-to-end

---

## TODO 1 — Add `_SyncLiteLLMWrapper` class to `skills/runner/main.py`

**Goal:** Add a synchronous wrapper class for `LiteLLMClient` so sync skill code can safely call async methods without uvloop event loop conflicts.

**Status:**
- [x] Add `_SyncLiteLLMWrapper` class after `LiteLLMClient` (before `# Skill Execution` section)
- [x] Wrapper uses `asyncio.new_event_loop()` (NOT `get_running_loop()`) to avoid "event loop already running" crashes in uvloop
- [x] Implement `chat_completion(model, messages, **kwargs)` method
- [x] Implement `mcp_call(tool_name, arguments, server_id=None, **kwargs)` method — param named `server_id` to match runner's `LiteLLMClient`
- [x] Add `base_url` property that delegates to the wrapped client

**Verify:**
- `_SyncLiteLLMWrapper` appears in `skills/runner/main.py` between `LiteLLMClient` and the `# Skill Execution` section
- `asyncio.new_event_loop()` is used (not `get_running_loop()`)
- Both `chat_completion` and `mcp_call` are implemented with correct signatures
- `base_url` property delegates to the wrapped `LiteLLMClient`

**Done when:** The wrapper class is in place with all required methods and can be instantiated with a `LiteLLMClient` reference.

---

## TODO 2 — Rewrite `_execute_skill` to dynamically import and execute skill modules

**Goal:** Replace the placeholder `_execute_skill` logic so it dynamically imports the skill module, instantiates a sync client, calls `skill_module.run()`, and maps results back to job fields.

**Status:**
- [x] After finding `skill_path`, dynamically import the skill module using `importlib.util`
- [x] Create `_SyncLiteLLMWrapper(litellm_client)` and pass it as `client` to `skill_module.run(params, job, client=sync_client)`
- [x] Map skill return dict to job fields: `summary`, `artifact_path`, `error`
- [x] If skill returns result dict with keys like `answer`, `report`, `sources`, merge those into job params or logs
- [x] Handle `ImportError` as a job failure with proper error message
- [x] Log the execution result properly
- [x] Keep existing approval gate and `dry_run` logic intact

**Verify:**
- `_execute_skill` in `skills/runner/main.py` uses `importlib.util` for dynamic import
- A `_SyncLiteLLMWrapper` is created and passed as `client` to `skill_module.run()`
- Return values from the skill are mapped into `job` fields (`summary`, `artifact_path`, `error`)
- Extra result keys (`answer`, `report`, `sources`) are merged into params or logs
- `ImportError` is caught and sets the job to failed
- Approval gate and `dry_run` checks remain in place
- Proper logging of execution outcome

**Done when:** `_execute_skill` fully imports, runs, and captures results from any skill module, with correct error handling and preserved approval/dry_run gates.

---

## TODO 3 — Fix `server_name` → `server_id` MCP parameter mismatch in `skills/deep_research/skill.py`

**Goal:** Correct the MCP tool call payload in `_SyncLiteLLMClient.mcp_call` and all dependent MCP helper functions so they match LiteLLM's API expectations (`name` + `server_id` instead of `tool` + `server`).

**Status:**
- [x] In `_SyncLiteLLMClient.mcp_call`, change payload from `{"tool": ..., "server": ...}` to `{"name": ..., "server_id": ...}`
- [x] Apply same fix in `_search_web`
- [x] Apply same fix in `_search_recent`
- [x] Apply same fix in `_search_news`
- [x] Apply same fix in `_search_knowledge`
- [x] Apply same fix in `_crawl_url`

**Verify:**
- `skills/deep_research/skill.py` no longer sends `tool` or `server` keys in `/mcp-rest/tools/call` payloads
- All six MCP helper functions use `{"name": ..., "server_id": ...}` format
- No remaining references to the old `server` key in MCP call payloads

**Done when:** All MCP call payloads in `skills/deep_research/skill.py` use `name` and `server_id` to match LiteLLM's API.

---

## TODO 4 — Rebuild and test skill runner end-to-end

**Goal:** Rebuild the skill-runner container, deploy it, and verify that all skills execute correctly and return real results (not skeleton placeholders).

**Status:**
- [x] Run `docker compose -f compose/compose.skill-runner.yml build && docker compose -f compose/compose.skill-runner.yml up -d skill-runner`
- [x] Test `siri_ask` (real, no dry_run): `curl -X POST http://localhost:8091/skills/siri_ask -H "Content-Type: application/json" -d '{"params":{"query":"what is 2+2?"}}'`
- [x] Test `deep_research` (dry_run first): `curl -X POST http://localhost:8091/skills/deep_research -H "Content-Type: application/json" -d '{"params":{"query":"test"},"dry_run":true}'`
- [x] Verify all 3 skills return `"completed"` status with actual summary text (not "skeleton placeholder")

**Verify:**
- `skill-runner` container is rebuilt and running without errors
- `siri_ask` returns a completed job with a real answer (e.g., "4" or equivalent)
- `deep_research` dry_run returns completed status
- All 3 skills produce real summary text, not the skeleton placeholder

**Done when:** The skill runner is rebuilt, deployed, and all 3 skills return completed status with actual summary text via the test curl commands.
