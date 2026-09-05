# Thor AI Platform — Status

> Updated: 2026-09-04 (credential rotation closed; presenton LAN-only;
> pre-commit secrets guard added; scheduler split + weekday morning brief)>
> **Workstreams:** `auth_todo.md` v2 (per-user LiteLLM keys, per-user
> usage attribution, tooling/scripts — old Phase 9 folded into Phase 5)
> is the only active plan. The three completed plans
> (`memory_todo.md`, `mcp-vision-todo.md`, `kb-todo.md`) were **deleted
> 2026-08-29**; their state lives in the canonical state docs:
> `docs/memory/IMPLEMENTATION_STATE.md`, `mcp/servers/vision/README.md`,
> `mcp/servers/knowledge/README.md`. This file is status/history only —
> no open work lives here.

---

## Completed (July 2026)

- **Scheduler definitions/state split + weekday morning brief — 2026-09-04.**
  Skill-runner scheduler now reads git-tracked definitions from
  `homelab/scheduler/schedules.json` (read-only mount, hot-reloaded on file
  change — no restart) and persists run state (`last_run_at`/`next_run_at`) to
  untracked `/home/chuck/data/scheduler/state.json` (atomic writes). Old
  `data/scheduler/scheduler.json` (runtime churn in the working tree) removed
  from git; legacy single-file format auto-migrates. New job
  `weekday-morning-brief` (Mon–Fri 09:00 `America/Chicago`) runs
  `morning_brief` with `publish: true` → atomically overwrites
  `/home/chuck/data/media/public/briefs/latest.md` →
  `https://choukalos.com/files/briefs/latest.md` (single-file retention).
  `homelab.sh` rebuild paths now rebuild the `skill-runner:local` image first
  (runner core is baked into the image; `restart`/`up` do NOT rebuild — a
  stale Sept-1 image had silently shadowed live core code until the image
  was rebuilt).
- **Credential rotation — COMPLETE 2026-09-04** (trigger: leaked
  credentials zip, 2026-09-02). All `.env` values re-issued and synced to
  every backing store: LiteLLM (master + per-user keys, proxy DB re-seeded —
  exactly 3 virtual keys remain), MySQL `investor`/`ai`/root, Postgres
  `plausible` (peer-auth `ALTER USER`), Caddy Presenton basic-auth. Fixed
  fallout: `plausible` (`PLAUSIBLE_DB_PASS` was missing from `.env`),
  invest-hub 502s (MySQL `investor` password drift), `LITELLM_API_KEY`
  (was a self-referential `${LITELLM_MASTER_KEY}` placeholder), github-runner
  (GitHub had deleted the stale registration; re-registered + updated image,
  runner v2.337.0). Leaked/intermediate secret artifacts removed from `/tmp`
  and the repo. Tracked files scanned clean (no live secret values).
- **Presenton LAN-only, passwordless — 2026-09-04.** Public
  `siri.choukalos.com/presentations/*` Caddy route removed; port bound to
  `${THOR_IP}:5000` (LAN only, `DISABLE_AUTH=true`). Family use:
  `http://thor.local:5000`. (Closes auth_todo.md Phase 5.5 manual step G +
  Q3.)
- **Pre-commit secrets guard — 2026-09-04.** `.githooks/pre-commit` (via
  `core.hooksPath .githooks`) now blocks staged `.env`/key/keystore files by
  name, known token formats (AWS, OpenAI/LiteLLM `sk-`, GitHub, Slack), PEM
  private keys, base64 Basic-auth blobs, and high-entropy literals assigned
  to secret-looking variable names. `${VAR}` references and placeholders
  pass. Bypass: `git commit --no-verify` (then rotate).
- **Family KB rebuild (K0–K7) — COMPLETE 2026-08-29.** mcp_knowledge v2
  live (Qdrant `kb_*` collections, 768-dim, 11 tools, `kb_` prefix
  code-gate); legacy `family_kb` (384-dim) snapshotted + dropped;
  family-wiki + `family_kb_ingest` retired; `scripts/backup-kb.sh` +
  restore E2E verified; verification green (regression 70/70, audit-log
  scan, auth matrix, secret scan). Plan file deleted 2026-08-29; state:
  `mcp/servers/knowledge/README.md`.
- **`mcp_vision` (A0–A3) — COMPLETE 2026-08-28.** Image/video
  analysis via `matrix-coder` vision (5 images per LLM call — server-side
  batching replaces the video-analyze skill's per-subagent session-budget
  pattern). 5 tools: `vision_analyze_image`, `vision_analyze_video` (scene +
  raw full-FPS modes, frame-budget guarded), `vision_extract_frames` (no
  LLM), `vision_cleanup`, `vision_probe`. Sources: local (allowlisted), any
  http(s) URL (2 GB cap), YouTube (yt-dlp). `focus=commercial` QA's
  mcp_media-generated media (PASS/FAIL + fix suggestions). Artifacts ephemeral
  + NON-public (`workspace/vision/<slug>/`; `scripts/cleanup-vision.sh`). A1/A2
  E2E green (local mp4, GIF, remote URL, YouTube 18 s, raw timestamps, budget
  guard). LiteLLM registration + `mcp_knowledge` 7200s timeout (KB K3) batched
  in one owner reload. See `mcp/servers/vision/README.md`.
- **Long-term memory (Phases 0–9) — COMPLETE 2026-08-28.**
  In-process Mem0 in skill-runner → Qdrant `mem0_memories` (768-dim); identity
  map, retrieval + writeback, household scope, secret filtering, admin REST +
  CLI + `/metrics` (scraped by VictoriaMetrics), backups
  (`scripts/backup-memory.sh`), regression suite (`scripts/memory-regression.sh`,
  70/70), Qdrant JWT RBAC + scoped keys, image pins (litellm v1.92.0,
  qdrant v1.18.1), embedding-migration runbook. State:
  `docs/memory/IMPLEMENTATION_STATE.md`. Phase 6 (optional MCP memory tools)
  remains the only deferred phase — gated on a week of production use.
- **LiteLLM** running with **9 MCP servers (53 tools as of 2026-08-29 — 10 media-pipeline tools, legacy media tools removed, + `schema_overview` on mcp_mysql, + 5 mcp_vision tools, + 7 KB tools from the mcp_knowledge v2 rebuild)** via
  streamable-http (`mcp_search` 3, `mcp_crawl` 1, `mcp_knowledge` 11,
  `mcp_filesystem_readonly` 3, `mcp_filesystem` 5, `mcp_mysql` 11,
  `mcp_homelab_status` 4, `mcp_media` 10, `mcp_vision` 5).
  **MCP access model (decided 2026-08-25):** `allow_all_keys: true` is
  intentional — every valid key may call every MCP tool; no scoped grants
  planned (the old "per-key access hardening" deferral is dropped).
- **Skill Runner** containerized & deployed (`compose.skill-runner.yml`,
  port 8091); 15 skills; chat gateway with intent detection
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
  committed before the gitignore are untracked in `auth_todo.md` v2 Phase 5.)

---

## Open items — tracked in `auth_todo.md` (v2)

`auth_todo.md` v2 (fresh plan, 2026-08-29) is the only active plan —
per-user LiteLLM keys + per-user usage attribution, with the surviving
old-Phase-9 tooling items (C8, Presenton, repo hygiene) folded into
Phase 5. OWUI removal is **on hold** (owner decision 2026-08-29 — not
scheduled for deletion). Phases:

- **Phase 1 — Key foundation (no restart):** `chuck` + `dylan` LiteLLM
  keys (regenerate or supply values — Q1) via `cli/litellm-keys.sh`,
  `.env` vars, delete `simba` + stray test keys, per-key verification.
- **Phase 2 — skill-runner key threading:** `LiteLLMClient` per-user
  `Bearer` behind `AUTH_KEY_THREADING_ENABLED` (default off),
  `MEMORY_USER_KEYS` += dylan, unit + container tests, manual rebuild (B).
- **Phase 3 — Caddy OR-gate:** edge accepts chuck / dylan / legacy keys
  (hot reload, no manual step).
- **Phase 4 — Grafana:** verify per-user Key Usage panels show
  chuck / dylan after threading.
- **Phase 5 — Tooling & scripts (old Phase 9):** `cli/litellm-keys.sh`,
  `run-skill.sh --user`, fix stale `local/qwen-coder` aliases (C8 —
  6 `skill.yml` + 2 `skill.py` + docstring → `matrix-coder`),
  `PRESENTON_BASE_URL` → `PRESENTON_URL`, Presenton passwordless
  (`DISABLE_AUTH=true`), untrack git-committed log files (repo hygiene),
  rebuild + e2e (`create-demo`).
- **Phase 6 — Device migration (owner, later):** Siri shortcut, son's
  laptop, Mac pi; 24–48 h observation.
- **Phase 7 — Legacy key retirement (owner, after migration):** remove
  `SIRI_API_KEY` from list + Caddy, delete old keys, docs. **COMPLETE
  2026-09-04** (verified: proxy DB holds exactly the 3 current keys —
  chuck, dylan, memory; no legacy/stray keys).

The old "Frontier Integration Plan" (OWUI MCP + OpenAPI tools,
2026-07-22) is **dropped** — the capability survives anyway: all 9 MCP
servers are registered in LiteLLM, so any OpenAI-compatible client
(pi, opencode) can call the 53 MCP tools directly via
`llm.choukalos.com`.

---

## Verification checklist (after any changes)

1. Pre-flight: confirm backup exists, `ai-net` active
2. LiteLLM health: `/health/readiness` returns 200
3. MCP tools: `GET /v1/mcp/tools` returns correct count (53)
4. Tool calls: test via `/v1/chat/completions`
5. Public services: `llm.choukalos.com`, `siri.choukalos.com`
6. Metrics: `GET /metrics/` returns 200
7. MCP containers: all containers `Up`
8. Skill Runner: `GET http://thor.local:8091/health` returns `{"status": "ok"}`
9. Skills: test each via `POST /api/chat` with appropriate intent
10. Caddy: after any Caddyfile change, verify public endpoints. **Gotcha
    (2026-09-04):** editors that replace the file atomically (rename over the
    inode) break Caddy's inotify watch — the running config goes stale. If
    `docker logs caddy` shows no reload, run
    `docker exec caddy caddy reload --config /etc/caddy/Caddyfile`.