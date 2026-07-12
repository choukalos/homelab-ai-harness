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

### C8: `demo_workflow` skill HARNESS_URL ✅ FIXED

Updated to `http://skill-runner:8091` (was `http://ai-harness:8090`).

---

### D1: Add Lego (NAS) to Monitoring Stack

- [ ] **Deploy node-exporter on Lego** (`192.168.4.92`, port 9100)
  - Ensure node-exporter is running on the NAS (systemd or Docker)
- [ ] **Update Victoria Metrics scrape config** (`prometheus/prometheus.yml`)
  - Add `extra_hosts` entry `lego:${LEGO_IP}` in `compose.monitoring.yml`
  - Add new scrape job `node-exporter-lego` with `targets: [lego:9100]` and `labels: {instance: lego}`
- [ ] **Restart Victoria Metrics** to pick up the new scrape target
- [ ] **Verify Grafana dashboards** pick up Lego automatically
  - *node-exporter-full.json* — `Instance` variable should now include `lego:9100`
  - *homelab-overview.json* — `Host` variable should now include `lego`
  - No dashboard JSON edits needed (both use dynamic template variables)

---

### E: Low-Priority Fixes

- [ ] **Alpha Vantage stock prices showing $0.00** (from `todo.md`)
  - Likely Alpha Vantage API rate limit or `PriceHistory` query issue
  - Cost basis and P&L calculations work correctly despite $0.00 prices

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