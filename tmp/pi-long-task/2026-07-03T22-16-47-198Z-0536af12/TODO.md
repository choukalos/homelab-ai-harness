# Pi Long Task TODO

All skills must call LiteLLM for LLM + MCP interactions; they must never touch MCP servers directly. Defer per-key MCP access restrictions to Phase 14.

Global instructions:
- Long task goal: Implement Phase 8 and Phase 9 from /home/chuck/homelab/thor_todo.md. Phase 8 — Skill Runner Skeleton: - skills/runner/Dockerfile (Python image for container mode) - skills/runner/pyproject.toml (fastapi, uvicorn, httpx, pydantic) - skills/runner/main.py (FastAPI app, job lifecycle API, LiteLLM HTTP client for both /v1/chat/completions and /mcp-rest/tools/call) - skills/runner/dev.sh (laptop LAN dev quickstart: LITELLM_BASE_URL=http://192.168.4.54:4000) - skills/runner/README.md (setup for both container and laptop modes) - compose/compose.skill-runner.yml (port 8091 on ai-net, mounts skills/ dir) Phase 9 — Implement 3 skills (siri_ask, deep_research, presentation_build): - Each gets skills/<name>/skill.py (execution logic), skill.yml (manifest), README.md - Skills call LiteLLM for LLM + MCP, never touch MCP servers directly Phase 10 prep — Update litellm/draft/config.yml and explicitly describe the manual steps Chuck needs to take. Defer per-key MCP access restrictions to Phase 14.

## Progress

- [x] TODO 1 — Create skill runner skeleton (Dockerfile, pyproject.toml, main.py)
- [x] TODO 2 — Create skill runner dev tooling (dev.sh, README.md)
- [x] TODO 3 — Create skill runner Compose service (compose.skill-runner.yml)
- [x] TODO 4 — Implement siri_ask skill
- [x] TODO 5 — Implement deep_research skill
- [x] TODO 6 — Implement presentation_build skill
- [x] TODO 7 — Update LiteLLM draft config for Phase 10

---

## TODO 1 — Create skill runner skeleton (Dockerfile, pyproject.toml, main.py)

**Goal:** Build the core FastAPI-based skill runner application with job lifecycle API and LiteLLM HTTP client.

**Status:**
- [x] Create `skills/runner/Dockerfile` using a Python base image for container mode
- [x] Create `skills/runner/pyproject.toml` with dependencies: fastapi, uvicorn, httpx, pydantic
- [x] Create `skills/runner/main.py` implementing:
  - FastAPI app with job lifecycle endpoints (submit, status, result)
  - LiteLLM HTTP client supporting both `/v1/chat/completions` and `/mcp-rest/tools/call`

**Verify:**
- `docker build -t skill-runner -f skills/runner/Dockerfile skills/runner` succeeds
- `uvicorn skills.runner.main:app --port 8091` starts without import errors (with dependencies installed)
- Job lifecycle API returns valid JSON responses for submit/status/result

**Done when:** All three files exist and the FastAPI app starts successfully with both LiteLLM endpoint patterns wired up.

---

## TODO 2 — Create skill runner dev tooling (dev.sh, README.md)

**Goal:** Provide laptop LAN dev quickstart script and comprehensive setup documentation for both container and laptop modes.

**Status:**
- [x] Create `skills/runner/dev.sh` with `LITELLM_BASE_URL=http://192.168.4.54:4000` as the default dev environment
- [x] Create `skills/runner/README.md` documenting:
  - Container mode setup
  - Laptop mode setup
  - Environment variable configuration
  - How to run the skill runner locally

**Verify:**
- `bash skills/runner/dev.sh --help` or running dev.sh shows the expected LITELLM_BASE_URL configuration
- README.md covers both container and laptop modes with clear setup instructions

**Done when:** Both files exist and the dev script correctly configures the LITELLM_BASE_URL environment variable.

---

## TODO 3 — Create skill runner Compose service (compose.skill-runner.yml)

**Goal:** Define the Compose service for the skill runner with proper networking and volume mounts.

**Status:**
- [x] Create `compose/compose.skill-runner.yml` with:
  - Port mapping to 8091
  - Attached to `ai-net` network
  - Volume mount for the `skills/` directory

**Verify:**
- `docker compose -f compose/compose.skill-runner.yml config` validates the service definition
- Port 8091 is exposed and the service is on the `ai-net` network
- Skills directory is properly mounted

**Done when:** Compose file validates and contains the correct port, network, and volume configuration.

---

## TODO 4 — Implement siri_ask skill

**Goal:** Create the siri_ask skill with execution logic, manifest, and documentation.

**Status:**
- [x] Create `skills/siri_ask/skill.py` with execution logic that calls LiteLLM for LLM + MCP
- [x] Create `skills/siri_ask/skill.yml` manifest file
- [x] Create `skills/siri_ask/README.md` with usage documentation

**Verify:**
- skill.py imports and uses the LiteLLM HTTP client (never touches MCP servers directly)
- skill.yml contains a valid skill manifest with name, description, and version
- README.md explains what the skill does and how to use it

**Done when:** All three files exist, the skill calls LiteLLM correctly, and the manifest is valid.

---

## TODO 5 — Implement deep_research skill

**Goal:** Create the deep_research skill with execution logic, manifest, and documentation.

**Status:**
- [x] Create `skills/deep_research/skill.py` with execution logic that calls LiteLLM for LLM + MCP
- [x] Create `skills/deep_research/skill.yml` manifest file
- [x] Create `skills/deep_research/README.md` with usage documentation

**Verify:**
- skill.py imports and uses the LiteLLM HTTP client (never touches MCP servers directly)
- skill.yml contains a valid skill manifest with name, description, and version
- README.md explains what the skill does and how to use it

**Done when:** All three files exist, the skill calls LiteLLM correctly, and the manifest is valid.

---

## TODO 6 — Implement presentation_build skill

**Goal:** Create the presentation_build skill with execution logic, manifest, and documentation.

**Status:**
- [x] Create `skills/presentation_build/skill.py` with execution logic that calls LiteLLM for LLM + MCP
- [x] Create `skills/presentation_build/skill.yml` manifest file
- [x] Create `skills/presentation_build/README.md` with usage documentation

**Verify:**
- skill.py imports and uses the LiteLLM HTTP client (never touches MCP servers directly)
- skill.yml contains a valid skill manifest with name, description, and version
- README.md explains what the skill does and how to use it

**Done when:** All three files exist, the skill calls LiteLLM correctly, and the manifest is valid.

---

## TODO 7 — Update LiteLLM draft config for Phase 10

**Goal:** Update the LiteLLM draft configuration file and document the manual steps Chuck needs to take.

**Status:**
- [x] Update `litellm/draft/config.yml` with any necessary configuration for the new skill runner and skills
- [x] Document explicit manual steps Chuck needs to perform to complete Phase 10
- [x] Note that per-key MCP access restrictions are deferred to Phase 14

**Verify:**
- config.yml reflects the skill runner and new skills integration
- Clear, numbered manual steps are provided for Chuck to follow
- Phase 14 deferral is explicitly noted

**Done when:** config.yml is updated and a clear set of manual steps is documented for Chuck to complete Phase 10.
