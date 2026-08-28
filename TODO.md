# Thor AI Platform — Status

> Updated: 2026-08-28 (memory workstream closed; MCP tool count refreshed)
> **Active workstreams:** `auth_todo.md` (user auth, per-user usage tracking,
> OWUI removal, budgets/ROI, skill fixes) and `media_mcp_tool_todo.md`
> (media-mcp → GPU media-pipeline :8189, 9 new tools). `memory_todo.md` is
> **COMPLETE** (Phases 0–9, 2026-08-28 — see
> `docs/memory/IMPLEMENTATION_STATE.md`). This file is status/history only —
> no open work lives here.

---

## Completed (July 2026)

- **Long-term memory (memory_todo.md, Phases 0–9) — COMPLETE 2026-08-28.**
  In-process Mem0 in skill-runner → Qdrant `mem0_memories` (768-dim); identity
  map, retrieval + writeback, household scope, secret filtering, admin REST +
  CLI + `/metrics` (scraped by VictoriaMetrics), backups
  (`scripts/backup-memory.sh`), regression suite (`scripts/memory-regression.sh`,
  70/70), Qdrant JWT RBAC + scoped keys, image pins (litellm v1.92.0,
  qdrant v1.18.1), embedding-migration runbook. State:
  `docs/memory/IMPLEMENTATION_STATE.md`. Phase 6 (optional MCP memory tools)
  remains the only deferred phase — gated on a week of production use.
- **LiteLLM** running with **8 MCP servers (34 tools as of 2026-08-28)** via
  streamable-http (`mcp_search` 3, `mcp_crawl` 1, `mcp_knowledge` 4,
  `mcp_filesystem_readonly` 3, `mcp_filesystem` 5, `mcp_mysql` 10,
  `mcp_homelab_status` 4, `mcp_media` 4).
  **MCP access model (decided 2026-08-25):** `allow_all_keys: true` is
  intentional — every valid key may call every MCP tool; no scoped grants
  planned (the old "per-key access hardening" deferral is dropped).
- **Skill Runner** containerized & deployed (`compose.skill-runner.yml`,
  port 8091); 13 skills; chat gateway with intent detection
  (`POST /api/chat`, `GET /api/jobs/{job_id}`); lightweight cron scheduler
  with REST API.
- **Siri API** on `siri.choukalos.com` → Skill Runner (Caddy cutover).
- **F: Public API non-chat intents** — all 12 intent paths verified end-to-end
  through `siri.choukalos.com` (2026-07-16): chat, deep-research,
  investment-brief, morning-brief, media-generate, list-demos,
  list-presentations, list-images, create-presentation, update-presentation,
  find-demo, research-brief.
- **G1/G2/G3: Clickable source URLs** in morning / investment / research
  briefs — all tested ✅ (2026-07-17).
- **A2: `mcp_media` image generation** via ComfyUI on Matrix (192.168.4.55)
  — full stack verified (2026-07-06). (HF Inference API path left inactive —
  DNS doesn't resolve from Thor.)
- **C2: `media-generate` chat handler** — done.
- **D1: Lego (NAS) in monitoring** — node-exporter on 192.168.4.92:9100,
  VictoriaMetrics scrape updated, Grafana picked it up (2026-07-12).
- **Legacy `ai-harness` decommissioned** (2026-07-07) — source archived to
  `ai-harness-decommissioned/`, images pruned, `compose.ai-harness.yml.bak`
  kept for reference.
- **Log rotation** — `RotatingFileHandler` in `skills/runner/main.py`
  (10MB, 3 backups); `logs/` gitignored. (The two log files that were
  committed before the gitignore are untracked in `auth_todo.md` Phase 9.)

---

## Open items — tracked in `auth_todo.md`

- **C8: `create-demo` / `demo_workflow`** — root cause found 2026-08-25:
  stale `model_alias: local/qwen-coder` (alias no longer exists in LiteLLM;
  7 skills affected). Fix → `auth_todo.md` Phase 9.
- **Presenton** — presentation fetch path verified working (2026-08-25,
  HTTP 200). Env var name mismatch + password rotation → `auth_todo.md`
  Phase 9.
- **Open WebUI** — deprecated (no longer used); removal → `auth_todo.md`
  Phase 6. The old "Frontier Integration Plan" (OWUI MCP + OpenAPI tools,
  2026-07-22) is **dropped** with it — the capability survives anyway: all 8
  MCP servers are registered in LiteLLM, so any OpenAI-compatible client
  (pi, opencode) can call the 29 MCP tools directly via
  `llm.choukalos.com`.
- **Repo hygiene** — git-committed log files untracked → `auth_todo.md`
  Phase 9.

---

## Verification checklist (after any changes)

1. Pre-flight: confirm backup exists, `ai-net` active
2. LiteLLM health: `/health/readiness` returns 200
3. MCP tools: `GET /v1/mcp/tools` returns correct count (29)
4. Tool calls: test via `/v1/chat/completions`
5. Public services: `llm.choukalos.com`, `siri.choukalos.com`
6. Metrics: `GET /metrics/` returns 200
7. MCP containers: all containers `Up`
8. Skill Runner: `GET http://thor.local:8091/health` returns `{"status": "ok"}`
9. Skills: test each via `POST /api/chat` with appropriate intent
10. Caddy: after any Caddyfile change, verify public endpoints (Caddy
    auto-reloads the bind-mounted Caddyfile — confirm in `docker logs caddy`)