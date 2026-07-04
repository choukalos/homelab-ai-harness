# Pi Long Task TODO

# Pi Long Task TODO`
     - Include `## Progress` section with one unchecked line per task: `- [ ] TODO N — Title`
     - Include `---` separator before task sections.
     - Create sequential sections named `## TODO N — Title`.
     - Each task section must include: `**Goal:**`, `**Status:**` (with unchecked checkbox items), `**Verify:**` (concrete verification guidance), and `**Done when:**`.
     - Preserve global instructions/constraints above `## Progress`.
     - Keep tasks focused and independently assignable.
   - **Raw Input:** 6 tasks related to deploying a skill runner and MCP into a homelab orchestration script.
     - Global constraint from raw input: "Implement the following 6 tasks in order. Use `commit=false`."
     - Task 1: Update `skills/runner/main.py` (SSE to streamable-http)
     - Task 2: Create `compose/compose.skill-runner.yml`
     - Task 3: Update `skills/runner/Dockerfile`
     - Task 4: Update `compose/compose.mcp.yml`
     - Task 5: Update `homelab.sh`
     - Task 6: Update Caddyfile

2.  **Deconstruct Requirements & Map to Raw Input:**
   - **Header:** `# Pi Long Task TODO`
   - **Global Instructions:** "Implement the following 6 tasks in order. Use `commit=false`." (Place this right after the header)
   - **Progress Section:**
     `## Progress`
     `- [ ] TODO 1 — Update skills/runner/main.py: switch from SSE to streamable-http`
     `- [ ] TODO 2 — Create compose/compose.skill-runner.yml`
     `- [ ] TODO 3 — Update skills/runner/Dockerfile`
     `- [ ] TODO 4 — Update compose/compose.mcp.yml`
     `- [ ] TODO 5 — Update homelab.sh orchestration`
     `- [ ] TODO 6 — Update Caddyfile for skill-runner routing`
   - **Separator:** `---`
   - **Task Sections:** For each of the 6 tasks, create `## TODO N — Title` with the required subsections.
     - I need to extract the core action for each task and format it according to the requirements.
     - I'll add placeholder checkboxes under `**Status:**` based on the substeps implied or explicit in the raw input.
     - I'll add concrete verification steps under `**Verify:**`.
     - I'll add a clear completion criteria under `**Done when:**`.

3.  **Draft Construction (Mental Refinement):**

   *Global Instructions:*
   Implement the following 6 tasks in order. Use `commit=false`.

   *Progress:*

Global instructions:
- Long task goal: Deploy skill runner to production and integrate MCP + skill runner into homelab.sh orchestration script.

## Progress

- [x] TODO 1 — Update skills/runner/main.py: switch from SSE to streamable-http
- [x] TODO 2 — Create compose/compose.skill-runner.yml
- [x] TODO 3 — Update skills/runner/Dockerfile
- [x] TODO 4 — Update compose/compose.mcp.yml
- [x] TODO 5 — Update homelab.sh orchestration
- [x] TODO 6 — Update Caddyfile for skill-runner routing

---

## TODO 1 — Update skills/runner/main.py: switch from SSE to streamable-http

**Goal:** Rewrite the MCP client in `skills/runner/main.py` to use the streamable-http protocol instead of SSE.
**Status:**
- [x] Rename `_mcp_call_sse` to `_mcp_call_streamable` and update `mcp_call()` to invoke it
- [x] Implement step 1: POST JSON-RPC `initialize` to `{base_url}/mcp`, handle `X-Session-Id` header
- [x] Implement step 2: POST JSON-RPC `notifications/initialized` to `{base_url}/mcp`
- [x] Implement step 3: POST JSON-RPC `tools/call` to `{base_url}/mcp`, handle 200 direct JSON-RPC result or 202 Accepted
- [x] Implement step 4: On 202, open GET `{base_url}/mcp` to receive SSE stream with response
- [x] Implement step 5: DELETE `{base_url}/mcp` to clean up session
- [x] Update log messages to say "Streamable HTTP MCP call" instead of "SSE MCP call"
**Verify:** Test the updated `_mcp_call_streamable` method against a local or mocked MCP server supporting streamable-http. Confirm initialization, tool calls, and session cleanup work without errors. Check logs for the updated message text.
**Done when:** The method is fully renamed, implements the 5-step streamable-http flow, updates log messages, and successfully executes tool calls via the new protocol.

## TODO 2 — Create compose/compose.skill-runner.yml

**Goal:** Define a new Compose file for the skill-runner service with proper networking, environment, volumes, and dependencies.
**Status:**
- [x] Create `compose/compose.skill-runner.yml` with `name: ai-skill-runner`
- [x] Define `skill-runner` service with build context `../skills/runner` and image `skill-runner:local`
- [x] Configure container name, restart policy, env_file, networks (`ai-net`, `public-net`), and port mapping `${THOR_IP}:8091:8091`
- [x] Set required environment variables (LITELLM, SKILL_RUNNER, ARTIFACT_ROOT, MCP_SERVER_* URLs)
- [x] Mount volumes for skills, media, workspace, and logs
- [x] Add `depends_on` for `litellm-proxy` with `condition: service_healthy`
- [x] Define external networks `ai-net` and `public-net`
**Verify:** Validate YAML syntax with `docker compose -f compose/compose.skill-runner.yml config`. Ensure all referenced variables, networks, and paths exist or are properly templated.
**Done when:** The file is created, passes Compose config validation, and matches the provided specification exactly.

## TODO 3 — Update skills/runner/Dockerfile

**Goal:** Adjust the skill-runner Dockerfile to create required application directories before startup.
**Status:**
- [x] Locate `skills/runner/Dockerfile`
- [x] Add `RUN mkdir -p /app/skills /app/logs` before the `CMD` instruction
- [x] Preserve existing Dockerfile structure and base image
**Verify:** Rebuild the Docker image (`docker build -f skills/runner/Dockerfile -t skill-runner:test ../skills/runner`) and inspect the resulting container filesystem to confirm `/app/skills` and `/app/logs` exist.
**Done when:** The Dockerfile builds successfully and contains the new `mkdir -p` directive in the correct position.

## TODO 4 — Update compose/compose.mcp.yml

**Goal:** Add a project name to the MCP Compose file for proper isolation.
**Status:**
- [x] Open `compose/compose.mcp.yml`
- [x] Add `name: ai-mcp` at the very top of the file, before the `services:` block
- [x] Ensure YAML formatting remains valid
**Verify:** Run `docker compose -f compose/compose.mcp.yml config` and verify the output shows `name: ai-mcp`.
**Done when:** The file contains the `name: ai-mcp` directive at the top and passes Compose validation.

## TODO 5 — Update homelab.sh orchestration

**Goal:** Integrate the new MCP and skill-runner stacks into the homelab.sh orchestration script with proper dispatch logic, usage help, and stack management.
**Status:**
- [x] Add `MCP` and `SKILL_RUNNER` variable references at the top
- [x] Update `usage()` to include `mcp-only`, `skill-only`, and updated `ai`/`ai-only` descriptions
- [x] Update `compose_files()` to handle `mcp-only` and `skill-only` cases
- [x] Create new `run_ai_stack()` function with up/down/restart/rebuild/pull/logs/ps/config handlers in the specified order
- [x] Remove old `HARNESS` reference from `run_ai_stack()` while keeping `harness-only` functional elsewhere
- [x] Update `all` and `all-n8n` in `do_dispatch()` to include MCP and SKILL_RUNNER in up/down/rebuild/pull with correct dependency ordering
- [x] Ensure `ai` dispatch in `do_dispatch()` calls `run_ai_stack`
**Verify:** Run `bash homelab.sh --help` to verify usage output. Run `bash homelab.sh ai up` and `bash homelab.sh ai down` to verify correct service ordering and compose file references. Check that `harness-only` remains untouched.
**Done when:** The script parses correctly, `usage()` reflects all new stacks, `run_ai_stack()` handles all commands with proper up/down ordering, and `all`/`all-n8n` targets include the new stacks in the correct sequence.

## TODO 6 — Update Caddyfile for skill-runner routing

**Goal:** Redirect Caddy reverse proxy rules for `siri.choukalos.com` from the old harness to the new skill-runner service.
**Status:**
- [x] Open `/home/chuck/homelab/caddy/Caddyfile`
- [x] Update `@siri_media` handler to route to `reverse_proxy http://skill-runner:8091`
- [x] Update `@siri /health` handler to route to `reverse_proxy http://skill-runner:8091`
- [x] Update `@siri /siri/*` handler to route to `reverse_proxy http://skill-runner:8091`
- [x] Keep existing auth checks intact
- [x] Comment out old `ai-harness:8090` references for rollback reference
**Verify:** Run `caddy validate --config /home/chuck/homelab/caddy/Caddyfile` to check syntax. Verify that all `@siri` handlers point to `skill-runner:8091` and old harness lines are commented out.
**Done when:** The Caddyfile routes all siri endpoints to `skill-runner:8091`, preserves auth checks, comments out old harness references, and passes Caddy syntax validation.
