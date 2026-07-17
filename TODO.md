# Thor AI Platform - Status & Remaining Work

> Updated: 2026-07-12
> Phases A–F completed. Remaining items listed below.

---

## Current State

### ✅ Completed

- **LiteLLM** running with **8 MCP servers** (29 tools) via streamable-http transport
- **MCP servers containerized** (8 active on `ai-net`):
  - `mcp_search`, `mcp_knowledge`, `mcp_crawl`, `mcp_filesystem_readonly`,
  - `mcp_mysql`, `mcp_homelab_status`, `mcp_filesystem`, `mcp_media`
- **Skill Runner** containerized & deployed (`compose.skill-runner.yml`, port 8091)
- **Skills implemented** (13 total):
  - `siri_ask`, `deep_research`, `presentation_build`, `demo_workflow`
  - `investment_brief`, `morning_brief`, `homelab_report`
  - `family_kb_ingest` (approval gate), `code_review`, `repo_maintenance` (approval gate)
  - `presentation_update`, `demo_browse`, `research_brief`
- **Chat gateway** on Skill Runner (`:8091`) with intent detection:
  - `POST /api/chat` — auto-detects: chat, deep-research, build-presentation,
    update-presentation, find-demos, research-brief, media-generate, siri-chat
  - `GET /api/jobs/{job_id}` — poll async job status
- **Lightweight scheduler** — background thread, cron-based schedules, REST API
  - `GET /api/schedule`, `POST /api/schedule`, `DELETE /api/schedule/{id}`,
    `POST /api/schedule/{id}/run-now`
- **Siri API** on `siri.choukalos.com` → Skill Runner `:8091` (Caddy cutover done)
- **Documentation** current (`README.md`, `README_SIRI.md`, `cli/run-skill.sh`)

### ⚠️ Blocked / Deferred

- **Open WebUI MCP integration** — version mismatch (servers v1.28.1, OWUI v1.27.2).
  Decision: skip for now, use LiteLLM proxy. Revisit on OWUI upgrade.

- **Per-Key Access Hardening** (Deferred Indefinitely) — all MCP servers use
  `allow_all_keys: true`. Adding wife/daughter keys and scoped MCP grants is
  deferred for now.

---

## Remaining Work

### ✅ Decommission Legacy Harness (Done 2026-07-07)

The Caddy cutover to Skill Runner was confirmed stable.
The old `ai-harness` source code has been archived to `ai-harness-decommissioned/`
and Docker images pruned.  The compose file `compose.ai-harness.yml.bak` is preserved
for reference if needed.

---

### ✅ Log Rotation & Script Updates (Done 2026-07-07)

**Log Rotation:**
- Added `RotatingFileHandler` to `skills/runner/main.py` (max 10MB, 3 backups)
- Added `logs/` to `.gitignore` to prevent 98MB log files from being committed
- Old log files will auto-truncate on next restart

**CLI Scripts:**
- `siri-script.sh` archived (stale endpoint `8090`)
- `cli/run-skill.sh` updated: `--public` flag for `siri.choukalos.com`, `media-generate` intent, removed duplicate `poll_job`

---

### A2-verify: `mcp_media` — Image Generation via ComfyUI ✅ VERIFIED

**Image backend:** ComfyUI on Matrix (`192.168.4.55:8188`)
- Primary: `comfyui` (local GPU, free)
- Default model in `mcp_media` is `comfyui`

**Full stack test 2026-07-06:**
- `mcp_media` container → ComfyUI via `http://192.168.4.55:8188` ✅
- Workflow: SDXL checkpoint → KSampler → VAE decode → SaveImage ✅
- End-to-end via LiteLLM MCP REST: `generate_image("a geometric abstract logo", "comfyui")` ✅
- Generated: `gen_a geometric abstract logo.png` (1024×1024, 1.6MB) ✅
- Saved to `/home/chuck/data/media/generated/` ✅

**Notes:**
- HF Inference API DNS doesn't resolve from Thor (path left in code but inactive)
- ComfyUI workflow uses `sd_xl_base_1.0.safetensors` (matches your checkpoint)

---

### C2: `media-generate` chat handler ✅ DONE

The `media-generate` intent handler in `main.py` calls `mcp_media.generate_image`
via streamable HTTP and returns the image URL in the chat response.

### C8: `demo_workflow` skill HARNESS_URL ⚠️ NOT WORKING

Rewrote skill to use LiteLLM directly (replaced non-existent `/demos/run` harness call).
Still failing via `--public create-demo`. **Needs investigation:**
- Verify the skill loads the right env vars (`LITELLM_BASE_URL`, `LITELLM_API_KEY`) at runtime
- Check whether the LLM response parsing works with the chosen model
- Consider whether `matrix-coder` is the right model for HTML generation or if another model is needed
- Full end-to-end test of the skill from prompt → LLM → saved HTML → job result

---

### ✅ G1: Morning Brief — Clickable Source URLs (Done 2026-07-17)

- [x] Updated `morning_brief` system prompt to require `[source](URL)` markdown links on every bullet
- [x] Updated context builder to format bullets as `[source_name](url)` instead of `[url]`
- [x] Compiled & verified
- [x] **TESTED**: `--public morning-brief "AI, technology, startups"` — full brief with clickable links ✅

### ✅ G2: Investment Brief — Clickable Source URLs (Done 2026-07-17)

- [x] Updated `investment_brief` system prompt to require `[source](URL)` links on news items
- [x] Added **Key Sources** section to the output structure
- [x] Updated per-holding news context to use `[headline](url)` markdown links
- [x] Updated general news section to use `[title](url)` markdown links
- [x] Compiled & verified
- [x] **TESTED**: `--public investment-brief "tech stocks"` — full LLM-synthesized brief with clickable links ✅

### ✅ G3: Research Brief — Clickable Source URLs & Full Output (Done 2026-07-17)

**Problem:** `--public research-brief` returned only a truncated "speak" with 1 URL,
not the full brief. The LLM synthesis prompt didn't require clickable links.

- [x] Updated `SUMMARY_SYNTHESIS_PROMPT`: every key finding must end with `[read more](url)` or `[source](url)`
- [x] Added **Key Sources** section to the prompt output structure
- [x] Updated `_build_sources_text` to use `[title](url)` markdown links (was bare `URL: ...`)
- [x] Added `sub_query` field to source context for better traceability
- [x] Updated `_fallback_summary` to use `[title](url)` markdown links
- [x] Fixed `_synthesize_brief` to handle `None` content gracefully
- [x] **Runner fix**: Added `brief` to `extra_keys` in `_execute_skill` (was only `report`/`sources`)
- [x] **CLI fix**: Updated `poll_job()` to display `_result_brief` as plain markdown (not JSON-wrapped)
- [x] **Runner rebuild**: Rebuilt skill-runner image to pick up main.py changes (was baked at build time)
- [x] **TESTED**: `--public research-brief "mortality rate for salivary gland cancers"` — full brief with clickable links ✅
- [x] **TESTED**: `--public research-brief "benefits of intermittent fasting"` — full brief with clickable links ✅

---

### ✅ D1: Add Lego (NAS) to Monitoring Stack (Done 2026-07-12)

Completed manually.

- [x] **Deploy node-exporter on Lego** (`192.168.4.92`, port 9100)
- [x] **Update Victoria Metrics scrape config** (`prometheus/prometheus.yml`)
- [x] **Restart Victoria Metrics** to pick up the new scrape target
- [x] **Verify Grafana dashboards** pick up Lego automatically

---



### F: Public API — Fix Non-Chat Intents via `siri.choukalos.com`

**Discovered:** 2026-07-15 (user reported at work: "nothing but chat worked")

**Root Causes:**
1. **CLI polled `/skills/jobs/{id}`** — Caddy only proxies `/api/*` to skill-runner. `/skills/*` hits the 404 fallback. Only `chat` worked (synchronous, no polling).
2. **Caddy `/siri/*` strip_prefix** was in the file but Caddy hadn't reloaded.

**Fixes Applied:**
- [x] **CLI polling URL** (`cli/run-skill.sh`): changed `poll_job()` from `/skills/jobs/` → `/api/jobs/` (both endpoints exist on skill-runner)
- [x] **Caddy reload** — `uri strip_prefix /siri` was already in Caddyfile, just needed `docker exec caddy caddy reload`
- [x] **Commit the CLI fix** (`git add cli/run-skill.sh && git commit`) — committed in `b6da011b`
- [x] **Full end-to-end test via `--public`**: all 12 intent paths verified through `siri.choukalos.com` (2026-07-16)
  - `chat` (sync) ✅
  - `deep-research` (async → poll) ✅
  - `investment-brief` (async → poll) ✅
  - `morning-brief` (async → poll) ✅
  - `media-generate` (async → poll) ✅
  - `list-demos` (async → poll) ✅
  - `list-presentations` (async → poll) ✅
  - `list-images` (async → poll) ✅
  - `create-presentation` (sync fallback) ✅
  - `update-presentation` (async → poll) ✅
  - `find-demo` (sync) ✅
  - `research-brief` (async → poll) ✅
- [x] **Update verification checklist** to include "reload Caddy after Caddyfile changes"

---

## Verification Checklist (After Any Changes)

1. Pre-flight: Confirm backup exists, `ai-net` active
2. LiteLLM health: `/health/readiness` returns 200
3. MCP tools: `GET /v1/mcp/tools` returns correct count (29)
4. Tool calls: Test via `/v1/chat/completions`
5. Public services: Open WebUI, `llm.choukalos.com`, `siri.choukalos.com`
6. Metrics: `GET /metrics/` returns 200
7. MCP containers: All containers `Up`
8. Skill Runner: `GET http://thor.local:8091/health` returns `{"status": "ok"}`
9. Skills: Test each via `POST /api/chat` with appropriate intent
10. Caddy: After any Caddyfile changes, run `docker exec caddy caddy reload` and verify public endpoints