# Thor MCP Architecture

> Phase 4.5 — Define the MCP server architecture for the new platform.
> Date: 2026-07-03
> Status: **Implemented** — all 10 servers below are live in LiteLLM (streamable-http,
> `ai-net`, 56 tools as of 2026-08-29 — 46 + 6 new `mcp_knowledge` v2 tools + 3
> `mcp_skills` tools; legacy media tools removed 2026-08-28). This doc is the design
> baseline; the "Current state" notes reflect the live system.

**Current state (2026-08-29)**
- 10 servers live: `mcp_search` (3), `mcp_crawl` (1), `mcp_knowledge` (11),
  `mcp_filesystem_readonly` (3), `mcp_filesystem` (5), `mcp_homelab_status` (4),
  `mcp_media` (10), `mcp_mysql` (11), `mcp_vision` (5), `mcp_skills` (3) — 56 tools total.
- **`mcp_knowledge` v2 (2026-08-29 — D6 closed):** family KB rebuilt on Qdrant
  `kb_*` collections (one per domain, 768-dim nomic, created on the fly;
  11 tools: `kb_search`, `kb_get_document`, `kb_list_documents`, `kb_overview`,
  `kb_recent_changes`, `kb_add_fact`, `kb_ingest_file`, `kb_delete_document`,
  `kb_forget`, `kb_correct`, `kb_backup`). The `kb_` prefix code-gate is the
  security boundary (the server cannot touch any non-`kb_` collection, incl.
  `mem0_memories`). Runs on a **global-`m`** key (`sub=mcp-knowledge`) —
  per-collection scoping cannot cover on-the-fly collection creation (proven
  2026-08-29). Legacy `family_kb` (384-dim) snapshotted + dropped; the
  `family_kb_ingest` skill is retired. See `mcp/servers/knowledge/README.md`.
- **Qdrant has JWT RBAC auth** (2026-08-28, memory project Phase 9):
  `JWT_RBAC=true`; skill-runner memory uses a scoped JWT (`mem0_memories`
  rw, no expiry); `mcp_knowledge` uses the global-`m` key above (prefix
  gate is its boundary). The admin key (`QDRANT_ADMIN_API_KEY`) is
  OPS-only (backups, ops scripts) and is NOT held by any runtime service.
  Qdrant is pinned `qdrant/qdrant:v1.18.1`.
- `mcp_media` now runs the **GPU-host media-pipeline** (192.168.4.55:8189) —
  10 `media_*` tools (storyboard, image gen/edit, I2V shots, TTS, music, SFX,
  upscale, assemble, fetch) live 2026-08-28. Legacy ComfyUI/HF tools removed the
  same day (old flows decommissioned). See `mcp/servers/media/README.md` for the
  full tool table and pipeline endpoint reference.
- `mcp_mysql` gained **schema intelligence** (2026-08-28): new `schema_overview`
  tool (all columns, FKs, inferred soft relations, join graph, curated hints,
  samples); fixed three key-casing bugs that made the NL-to-SQL schema context
  fail silently; NL-to-SQL now runs on `matrix-coder` with thinking disabled.
  Verified e2e on `investorhub` (portfolio + index join queries).
- `mcp_vision` added (2026-08-28): image/video analysis via `matrix-coder`
  vision (5 images per LLM call — server-side batching, no session budget).
  5 tools: `vision_analyze_image`, `vision_analyze_video` (scene + raw
  full-FPS modes, frame-budget guarded), `vision_extract_frames` (no LLM),
  `vision_cleanup`, `vision_probe`. Sources: local paths (allowlisted), any
  http(s) URL (2 GB cap), YouTube (yt-dlp). `focus=commercial` QA's
  mcp_media-generated media (PASS/FAIL verdict). Artifacts are ephemeral and
  NON-public (`/home/chuck/data/workspace/vision/<slug>/`; cleaned via
  `vision_cleanup` or `scripts/cleanup-vision.sh`). Registered in LiteLLM with
  `timeout: 7200` (batched owner reload with the `mcp_knowledge` 7200s timeout
  for KB K3). See `mcp/servers/vision/README.md` and `mcp-vision-todo.md`.
- **`mcp_skills` added (2026-08-29 — cross-client skill gateway):** 3 meta-tools
  (`list_skills`, `run_skill`, `get_skill_job`) wrapping the skill-runner so any
  MCP client can list + run skills through LiteLLM (low context: 3 schemas
  always-on, not 15 per-skill tools). `run_skill` is synchronous (blocks up to the
  skill's `max_runtime`, else returns a `job_id`); `get_skill_job` retrieves it.
  Identity threading: LiteLLM forwards the caller's `Authorization` header
  (`extra_headers: [Authorization]`); the server presents it as `X-API-Key` for
  execution (per-user attribution) and uses the service key for discovery
  (`GET /skills`). `timeout: 7200`. See `mcp/servers/skills/README.md` and
  `docs/thor_cross_client_skills.md`.

---

## Principle

MCP servers are discrete, independently deployable tool providers. Each one exposes a specific set of tools with clear permissions, paths, and channel exposure.

```
Channel → Skill Runner → MCP Servers → Backend Services
```

Skills compose multiple MCP tools. MCP servers do not know about skills or channels.

---

## Recommended MCP Servers

| Server | Purpose | Backend |
|---|---|---|
| `mcp_search` | Web search via SearXNG | `searxng:8080` |
| `mcp_crawl` | Page fetching and content extraction | `crawl4ai:11235` |
| `mcp_knowledge` | Family KB (Qdrant kb_* collections): ingest, search, correct, forget, backup | `qdrant:6333` |
| `mcp_filesystem_readonly` | Read-only file access to workspace and media | `/home/chuck/workspace`, `/home/chuck/data/media` |
| `mcp_filesystem` | Writable file ops (workspace/media) — 5 tools | same mounts |
| `mcp_mysql` | Read-mostly MySQL introspection + guarded queries — 10 tools | host MySQL |
| `mcp_homelab_status` | Homelab health, metrics, Docker state | `docker`, `victoria-metrics` |
| `mcp_media` | Media ops: **GPU media-pipeline (10 tools, live 2026-08-28)** | GPU host `:8189` |
| `mcp_vision` | Image/video analysis via matrix-coder vision (5 tools, live 2026-08-28) | LiteLLM `matrix-coder` + ffmpeg + yt-dlp |
| `mcp_skills` | Cross-client skill gateway: list/run/get skill jobs (3 tools, live 2026-08-29) | skill-runner `:8091` |
| `mcp_stocks` | ~~Stock market data~~ (never implemented) | — |
| `mcp_home` | Home automation (future, read-only) | Homebridge on Lego |

### Deferred

| Server | Reason |
|---|---|
| `mcp_code` | Coding workflows are complex with security implications. Revisit after other MCP servers are stable. |

---

## Server Specifications

### 1. `mcp_search`

| Field | Value |
|---|---|
| **Purpose** | Web search via SearXNG |
| **Tools** | `search(query, max_results?, categories?, language?)` |
| **Inputs** | Query string, optional filters |
| **Outputs** | List of results (title, URL, snippet, source) |
| **Read/write** | Read-only (queries SearXNG) |
| **Allowed paths** | `http://searxng:8080/search` |
| **Context impact** | Low — returns compact result summaries |
| **Channel exposure** | CLI, PI, Open WebUI (via skill runner) |
| **Security** | Read-only. No auth needed (internal network). Rate-limit at SearXNG. |

---

### 2. `mcp_crawl`

| Field | Value |
|---|---|
| **Purpose** | Fetch and extract content from web pages |
| **Tools** | `crawl(url, max_chars?, format?)` |
| **Inputs** | URL, optional max characters and output format |
| **Outputs** | Extracted text/markdown from the page |
| **Read/write** | Read-only (fetches external URLs) |
| **Allowed paths** | `http://crawl4ai:11235` |
| **Context impact** | Medium — page content can be large; enforce max_chars |
| **Channel exposure** | CLI, PI (via skill runner) |
| **Security** | Read-only. Crawl4AI runs in container. Rate-limit to avoid abuse. Block internal IPs from being crawled. |

---

### 3. `mcp_knowledge`

| Field | Value |
|---|---|
| **Purpose** | Family KB: ingest, search, correct, forget, backup (Qdrant `kb_*` collections) |
| **Tools (live)** | `kb_search(query, top_k?, kb?)`, `kb_get_document(source, kb)`, `kb_list_documents(kb?)`, `kb_overview()`, `kb_recent_changes(days?)`, `kb_add_fact(text, kb, description?)`, `kb_ingest_file(path, kb, description?)`, `kb_delete_document(source, kb?)`, `kb_forget(query, kb?, confirm?, ids?)`, `kb_correct(old_query, new_text, kb?)`, `kb_backup(include_sources?)` — **read + write** |
| **Inputs** | Query string, KB name (friendly, slugified to `kb_<slug>`), source path, fact text |
| **Outputs** | Ranked chunks with kb/source/page_range, document chunks, KB map, change log, ingest/backup reports |
| **Read/write** | **Read + write** (2026-08-29 v2: server is the KB operator; writes are gated by the `kb_` prefix code-gate, not a read-only key) |
| **Allowed paths** | `http://qdrant:6333`; sources under `/data/media`, `/data/workspace`, `/data/ai-kb/raw` (ro mounts); embeddings + vision via LiteLLM |
| **Context impact** | Low-Medium — returns compact chunks/snippets |
| **Security** | Global-`m` Qdrant key (`sub=mcp-knowledge`) + **`kb_` prefix code-gate** (structural: every Qdrant operation validates the collection name; adversarial-tested). The prefix gate, not the JWT, is the boundary — `mem0_memories` is unreachable by construction. |

**D6 status: ✅ CLOSED 2026-08-29.** The v1 gaps (allowlisted-but-nonexistent
collections, exact-match scroll instead of vector search, 384-dim legacy
embeddings, broken `family_kb_ingest` skill) were all resolved by the v2
rebuild: real `kb_*` collections with 768-dim nomic embeddings, vector +
keyword search, LLM-driven ingest (`kb_ingest_file` / `kb_add_fact`), and the
retired skill. Restore E2E-verified (`kb_gaming` snapshot → disposable node →
589/589 points byte-identical). See `mcp/servers/knowledge/README.md`.

---

### 4. `mcp_filesystem_readonly`

| Field | Value |
|---|---|
| **Purpose** | Read-only file system access for workspace and media |
| **Tools** | `read_file(path)`, `list_directory(path)`, `search_files(pattern, path?)` |
| **Inputs** | File path, glob pattern |
| **Outputs** | File contents, directory listing, search results |
| **Read/write** | Read-only |
| **Allowed paths** | `/home/chuck/workspace/**`, `/home/chuck/data/media/**` |
| **Context impact** | Low-Medium — file contents can be large; enforce size limits |
| **Channel exposure** | CLI, PI, Claude Code (via skill runner or direct) |
| **Security** | Strict read-only. Path validation prevents escape from allowed directories. No symlink following. Size limits per read. |

---

### 5. `mcp_stocks` — NOT IMPLEMENTED / NOT USED

> This server is documented as a future possibility but has never been built.
> Alpha Vantage and other external stock APIs are **not active providers**.

| Field | Value |
|---|---|
| **Purpose** | ~~Stock market data, prices, financial lookups~~ (not implemented) |
| **Tools** | `get_price(ticker)`, `get_historical(ticker, period?)`, `get_news(ticker)`, `get_financials(ticker)` |
| **Inputs** | Ticker symbol, optional period |
| **Outputs** | Price data, historical series, news snippets, financial statements |
| **Read/write** | Read-only (external APIs) |
| **Allowed paths** | N/A — Alpha Vantage and similar APIs are **not used** |
| **Context impact** | Low — returns compact structured data |
| **Channel exposure** | CLI, n8n, PI (via skill runner) |
| **Security** | Read-only. API keys stored in environment. Rate-limit per external provider limits. |

---

### 6. `mcp_homelab_status`

| Field | Value |
|---|---|
| **Purpose** | Homelab health monitoring, Docker state, service status |
| **Tools** | `docker_ps()`, `service_status(service_name)`, `get_metrics(query?)`, `get_logs(service, tail?)` |
| **Inputs** | Service name, optional query or tail count |
| **Outputs** | Container status, metrics data, log lines |
| **Read/write** | Read-only |
| **Allowed paths** | Docker socket (read-only), Victoria Metrics |
| **Context impact** | Low — returns compact status data |
| **Channel exposure** | CLI (full), n8n (status checks) |
| **Security** | Read-only Docker inspection. No container control. Metrics query limited to pre-approved Victoria Metrics endpoints. |

---

### 7. `mcp_media`

| Field | Value |
|---|---|
| **Purpose** | Media operations via the GPU-host media-pipeline |
| **Tools (live)** | **10** — `media_storyboard`, `media_generate_image`, `media_edit_image`, `media_generate_shot`, `media_text_to_speech`, `media_generate_music`, `media_sfx`, `media_upscale_video`, `media_assemble`, `media_fetch` |
| **Backends** | **GPU-host media-pipeline `192.168.4.55:8189` (live 2026-08-28)** — ComfyUI + VLLM + TTS/music/SFX workers on Matrix |
| **Path model** | No shared FS with GPU host: pipeline tools return **GPU-host paths** (needed for `media_assemble` chaining); `media_fetch` downloads to `/home/chuck/data/media/generated/pipeline/`; input tools auto-fetch GPU-host paths before upload. LiteLLM `timeout: 7200` for this server (flows block up to 2h) |
| **Read/write** | Write (generate/edit/assemble to GPU host) + `media_fetch` downloads to `/home/chuck/data/media/generated/pipeline/` |
| **Security** | Pipeline + ComfyUI over LAN. Output write-scoped to the media dir. |
| **Notes** | Legacy ComfyUI/HF tools (`generate_image`, `edit_image`, `image_info`, `list_images`) removed 2026-08-28 (old ComfyUI flows decommissioned); `media-generate` skill now uses `media_generate_image` + `media_fetch`. Queue back-pressure: 1 concurrent GPU job + 5 queued; 503 → `retry_after_seconds`. |

**Media pipeline (GPU host, `192.168.4.55:8189`)** — the service `mcp_media` wraps. Stdlib-only client (`media_pipeline_client.py`, vendored verbatim; no auth, LAN-only). Endpoints, each mapped 1:1 to an MCP tool:

| Endpoint | MCP tool | Model/worker | Typical time |
|---|---|---|---|
| `POST /storyboard` | `media_storyboard` | VLLM (shot-list JSON) | ~30s |
| `POST /images` | `media_generate_image` | ComfyUI (SD3 keyframes) | 30–60s |
| `POST /images/edit` | `media_edit_image` | ComfyUI (img2img edit) | ~30s |
| `POST /shots` | `media_generate_shot` | LTXV I2V (~4s clips) | ~10–60s (measured 10s, 97f @ 768×512) |
| `POST /tts` | `media_text_to_speech` | TTS worker (default voice: movie-trailer) | 15–60s |
| `POST /music` | `media_generate_music` | ACE-Step | 10–30 min |
| `POST /sfx` | `media_sfx` | MMAudio (synced to a clip) | 10–30 min |
| `POST /upscale` | `media_upscale_video` | SeedVR2 (`b`) / 4xUltrasharp (`a2`) | 1–5 min |
| `POST /assemble` | `media_assemble` | ffmpeg concat + audio mix | 1–10 min |
| `GET /files/{name}` | `media_fetch` | — (download) | seconds |
| `GET /health` | — (probes only) | — | — |

Queue model: **1 concurrent GPU job + 5 queued** (max pending 6); a full queue returns 503 with `retry_after_seconds` — the MCP tools surface it as a structured error. Job artifacts live under `/home/chuck/data/comfyui/run/media_jobs/{job_id}/` on Matrix. Typical video flow: `media_storyboard` → per-shot `media_generate_image` → `media_generate_shot` → `media_text_to_speech` + `media_generate_music` → `media_assemble` (shots must stay GPU-host paths) → `media_fetch` for the final mp4.

### 7b. `mcp_mysql` (added after the July design)

| Field | Value |
|---|---|
| **Purpose** | MySQL introspection + guarded query execution for the host MySQL (InvestorHub, homelab) |
| **Tools (live)** | `list_databases`, `list_tables`, `describe_table`, `sample_table`, `schema_overview`, `run_query`, `run_query_to_csv`, `nl_to_sql_then_run`, `explain_sql`, `list_indexes`, `foreign_keys` (11 tools) |
| **Schema intelligence (2026-08-28)** | `schema_overview` returns full per-database intelligence: every table with **all** columns + indexes + row counts, declared FKs, **inferred soft relations** (ORM-style `xxxId` reference columns without declared FKs — the join graph works even for FK-less databases), the join graph, curated domain hints, and sample rows. NL-to-SQL receives this as prompt context. |
| **NL-to-SQL** | `matrix-coder` (Qwen3.6-27B via vLLM) with thinking disabled (`LITELLM_DISABLE_THINKING`, Qwen thinking models otherwise burn the token budget on reasoning and return empty content). 2000-token budget. |
| **Curated hints** | `mcp/servers/mysql/schema_hints.json` (mounted read-only; edit + restart, no rebuild). `investorhub` has 14 hints: returns stored as fractions, `adjClose` for performance, precomputed return tables, integer years, timestamp TZ artifacts, `Index` reserved-word backticks, portfolio value formulas, app-internal tables to ignore. |
| **Read/write** | Strictly read-only: app-level DDL/DML regex **and** `SET SESSION transaction_read_only=1` (server-side write rejection). |
| **Security** | DSN via env; no public exposure (ai-net only) |
| **Notes** | 2026-08-28: fixed three key-casing bugs that made the schema context builder fail silently (NL-to-SQL had been running with **zero** schema context); removed 15-column truncation; samples now cover all tables; EXPLAIN pre-flight (max examined rows, max joins, full-scan block) unchanged. Verified e2e: 3–4 table join queries on `investorhub` (portfolio positions, S&P 500 YTD via latest snapshot, dividend-yield screen, multi-year returns) all translate + execute correctly in 2–3s. |

---

### 7c. `mcp_vision` (added 2026-08-28)

| Field | Value |
|---|---|
| **Purpose** | Image/video analysis via the `matrix-coder` vision model (Qwen3.6-27B) — ported from the owner's `video-analyze` pi skill; server-side batching replaces the skill's per-subagent session-budget pattern |
| **Tools (live)** | `vision_analyze_image`, `vision_analyze_video`, `vision_extract_frames`, `vision_cleanup`, `vision_probe` (5 tools) |
| **Sources** | Local path (allowlisted roots: media/, workspace/, ai-kb/raw — symlink/`../` escape rejected) · any http(s) URL (2 GB cap) · YouTube (yt-dlp, metadata first) |
| **Video modes** | `scene` (scene-change detection; single-pass <5 min, chunked longer; 200-frame cap) · `raw` (full native FPS, precise per-frame timestamps, **frame-budget guarded** — 3000 default, refuses before extracting) |
| **Focus templates** | `general` · `gameplay` · `tutorial` · `commercial` (QA of mcp_media-generated media: PASS/FAIL verdict + fix suggestions; pass the generation brief in `prompt`) |
| **Batching** | ≤5 images per fresh LLM call (provider limit, probed 2026-08-27); unlimited calls; thinking OFF (`chat_template_kwargs.enable_thinking=false` — Qwen3 thinking burns the completion budget) |
| **Artifacts** | `/home/chuck/data/workspace/vision/<slug>/` — frames, `summary.md`, `chapters.json`, `frame_metadata.jsonl`, `report.md`. **Ephemeral + NON-public** (no Caddy route, never under `media/public/`); cleaned via `vision_cleanup` or `scripts/cleanup-vision.sh` (manual, no cron) |
| **Read/write** | Reads sources (ro mounts); writes only the artifact dir (rw mount nested in ro workspace) |
| **Security** | ffmpeg/ffprobe/yt-dlp as arg lists (no shell); LiteLLM master key in-container; ai-net only |
| **LiteLLM** | `allow_all_keys: true`, `timeout: 7200` (long videos = minutes) |
| **Notes** | A1/A2 E2E 2026-08-28: local mp4 (scene + commercial QA), GIF (40 frames), remote URL, YouTube (18 s e2e), raw mode (precise timestamps), budget guard, cleanup. See `mcp/servers/vision/README.md` + `mcp-vision-todo.md`. |

---

### 7d. `mcp_skills` (added 2026-08-29)

| Field | Value |
|---|---|
| **Purpose** | Cross-client skill gateway: lets any MCP client list + run the homelab's skills through LiteLLM, without exposing skill-runner. Low context footprint — 3 meta-tools always-on, not 15 per-skill tools. |
| **Tools (live)** | `list_skills()`, `run_skill(name, prompt?, params?, max_wait?)`, `get_skill_job(job_id)` — **3 tools** |
| **Behavior** | `list_skills` → `GET /skills` (discovery, service key). `run_skill` → `POST /skills/{name}` — **synchronous** (blocks until terminal or approval gate); `prompt` auto-maps to the skill's primary string input (well-known names → required string → first string); `params` wins over `prompt`; `max_wait` defaults to the skill's `max_runtime` (else 180s); httpx timeout = `max_wait + 30`; on timeout → `RuntimeError` with a `job_id` hint. `get_skill_job` → `GET /skills/jobs/{job_id}`. |
| **Identity threading** | `_caller_key(ctx)` reads the caller's LiteLLM key from the `Authorization` header (LiteLLM forwards it via `extra_headers: [Authorization]` — plain non-OAuth server, strip logic returns False). **Execution** (`run_skill`/`get_skill_job`) presents the caller key as `X-API-Key` → skill-runner `resolve_user_id()` attributes the job to the right user (falls back to the service key). **Discovery** (`list_skills`) always uses the service key (`SKILL_RUNNER_API_KEY`) — the caller's key (e.g. the LiteLLM master) is not in skill-runner's allow-list. (Fixed 2026-08-29: discovery used the caller key → 403.) |
| **Backend** | skill-runner `:8091` (`GET /skills`, `POST /skills/{name}`, `GET /skills/jobs/{id}`) |
| **Read/write** | Read (`list_skills`, `get_skill_job`) + write (`run_skill` — executes a skill, may produce artifacts) |
| **Security** | ai-net only (NOT exposed to host). No client ever talks to skill-runner directly. Per-user attribution via the caller key (complete 2026-09-04/06: `MEMORY_USER_KEYS` maps chuck/dylan to personal keys; `AUTH_KEY_THREADING_ENABLED=true` — see `docs/thor_cross_client_skills.md`). |
| **LiteLLM** | `allow_all_keys: true`, `extra_headers: [Authorization]`, `timeout: 7200` (run_skill blocks up to max_runtime; deep_research=900s) |
| **Deps** | `mcp>=1.10,<2`, `httpx>=0.27`. Transport: streamable-http, path `/mcp`. |
| **Notes** | Verified through LiteLLM 2026-08-29: `mcp_skills-list_skills` (15 skills as of 2026-08-31), `mcp_skills-run_skill` (morning_brief, siri_ask, business_analyst, content_writer, marketing_strategy completed), `mcp_skills-get_skill_job` (job retrieval), identity threading (X-API-Key → `service`). See `mcp/servers/skills/README.md` + `docs/thor_cross_client_skills.md`. |

---

### 8. `mcp_home`

| Field | Value |
|---|---|
| **Purpose** | Home automation status (read-only) |
| **Tools** | `get_device_status(device_id?)`, `get_all_devices()`, `get_scene_status(scene_name?)` |
| **Inputs** | Optional device ID or scene name |
| **Outputs** | Device states, scene states |
| **Read/write** | Read-only (no device control yet) |
| **Allowed paths** | Homebridge on Lego (`192.168.4.x:8581`) |
| **Context impact** | Low — compact status data |
| **Channel exposure** | CLI, Portal (future) |
| **Security** | Read-only. No device control. Future write access requires explicit approval. Homebridge stays on Lego. |

---

## Channel → MCP Exposure Matrix

| MCP Server | CLI | PI | Open WebUI | Siri | n8n | llm.choukalos.com | Portal |
|---|---|---|---|---|---|---|---|
| `mcp_search` | ✅ | ✅ | ✅ | — | ✅ | — | — |
| `mcp_crawl` | ✅ | ✅ | — | — | ✅ | — | — |
| `mcp_knowledge` | ✅ | ✅ | Read | — | Ingest | — | Read |
| `mcp_filesystem_readonly` | ✅ | ✅ | — | — | ✅ | — | — |
| `mcp_stocks` | ❌ | — | — | — | ❌ | — | — |
| `mcp_homelab_status` | ✅ | — | — | — | ✅ | — | — |
| `mcp_media` | ✅ | — | ✅ | — | ✅ | — | — |
| `mcp_vision` | ✅ | ✅ | ✅ | — | — | — | — |
| `mcp_skills` | ✅ | ✅ | ✅ | — | ✅ | — | — |
| `mcp_home` | ✅ | — | — | — | — | — | Read (future) |

---

## Rules

- **Implemented.** All 10 servers run as containers on `ai-net` (streamable-http, port 8000)
  and are registered in `litellm/config.yml` (`mcp_servers`, `allow_all_keys: true` —
  decided 2026-08-25: every valid key may call every tool; no scoped grants).
  `mcp_skills` additionally forwards the caller's `Authorization` header
  (`extra_headers: [Authorization]`) for per-user skill attribution.
- MCP servers run as separate containers on Thor (`compose/compose.mcp.yml`).
- The skill runner composes MCP tools into workflows — MCP servers do not know about skills.
- `mcp_code` is deferred to future exploration.
- Qdrant-backed servers must use scoped keys where possible; the documented
  exception is `mcp_knowledge` (global-`m` key + `kb_` prefix code-gate —
  on-the-fly collection creation requires global access, proven 2026-08-29).
  The Qdrant admin key stays OPS-only.
