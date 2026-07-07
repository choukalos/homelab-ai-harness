# Thor AI Platform - Status & Remaining Work

> Updated: 2026-07-06
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
- **Documentation** current (`README.md`, `README_SIRI.md`, `siri-script.sh`)

### ⚠️ Blocked / Deferred

- **Open WebUI MCP integration** — version mismatch (servers v1.28.1, OWUI v1.27.2).
  Decision: skip for now, use LiteLLM proxy. Revisit on OWUI upgrade.

- **Per-Key Access Hardening** (Deferred Indefinitely) — all MCP servers use
  `allow_all_keys: true`. Adding wife/daughter keys and scoped MCP grants is
  deferred for now.

---

## Remaining Work

### 🛑 Decommission Legacy Harness (Manual — Chuck)

The Caddy cutover to Skill Runner is confirmed stable. Stop the old harness:

```bash
docker compose -f compose/compose.ai-harness.yml down
```

The `ai-harness` image can be pruned after stopping.

---

### A2-verify: `mcp_media` — End-to-End Image Generation (Manual — Chuck)

The `mcp_media` server is deployed and the 4 tools are registered with LiteLLM
(`generate_image`, `edit_image`, `image_info`, `list_images`). The server code
is complete and the container is healthy.

**Image backend configured:**
- **Primary:** Hugging Face `stable-diffusion-3-medium` via your `HF_TOKEN`
- **Fallback:** ComfyUI on `matrix:8188` (auto-triggers on HF rate-limit)
- Default model in `mcp_media` is `hf-sd3`

**What's left to verify end-to-end:**

1. **Restart LiteLLM** to pick up the new `hf-sd3` model config + `HF_TOKEN`:
   ```bash
   docker compose -f compose/compose.ai-core.yml restart litellm
   ```

2. **Test** by calling `generate_image("a sunset over Tokyo skyline")` via
   the LiteLLM proxy `/v1/images/generate` or via the skill runner chat gateway.

Once verified, confirm:
- `generate_image(...)` → saves to `/home/chuck/data/media/generated/images/`
- `list_images()` → returns the generated image
- `image_info(...)` → returns dimensions
- HF rate-limit fallback to ComfyUI works (spin up ComfyUI to test)

---

### C2: `media-generate` chat handler (Chuck or AI)

The `media-generate` intent is detected in `_detect_intent()` but the inline
handler in `main.py` is still a stub. Needs a real implementation that:
- Constructs an MCP tool call to `mcp_media.generate_image`
- Returns the result with the image artifact path

Also needed: **C8 — Fix `demo_workflow` skill HARNESS_URL** — the skill still
points to `http://ai-harness:8090`. Update to use the skill runner or
standalone mode.

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