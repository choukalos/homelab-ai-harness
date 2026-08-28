# Thor MCP Architecture

> Phase 4.5 — Define the MCP server architecture for the new platform.
> Date: 2026-07-03
> Status: **Implemented** — all 8 servers below are live in LiteLLM (streamable-http,
> `ai-net`, 41 tools as of 2026-08-28 — 34 + 10 media-pipeline tools, legacy media tools removed, + mcp_mysql schema_overview). This doc is the design baseline; the
> "Current state" notes reflect the live system.

**Current state (2026-08-28)**
- 8 servers live: `mcp_search` (3), `mcp_crawl` (1), `mcp_knowledge` (4),
  `mcp_filesystem_readonly` (3), `mcp_filesystem` (5), `mcp_homelab_status` (4),
  `mcp_media` (10), `mcp_mysql` (11) — 41 tools total via `GET /v1/mcp/tools`.
- **Qdrant now has JWT RBAC auth** (2026-08-28, memory project Phase 9):
  `JWT_RBAC=true`; `mcp_knowledge` uses a **read-only** API key
  (`QDRANT_READ_ONLY_API_KEY` — list/scroll/search only; create/upsert/delete
  → 403). The admin key (`QDRANT_ADMIN_API_KEY`) is OPS-only (backups, ops
  scripts) and is NOT held by any runtime service. Qdrant is pinned
  `qdrant/qdrant:v1.18.1`.
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
| `mcp_knowledge` | Knowledge base READ via Qdrant (read-only key) | `qdrant:6333` |
| `mcp_filesystem_readonly` | Read-only file access to workspace and media | `/home/chuck/workspace`, `/home/chuck/data/media` |
| `mcp_filesystem` | Writable file ops (workspace/media) — 5 tools | same mounts |
| `mcp_mysql` | Read-mostly MySQL introspection + guarded queries — 10 tools | host MySQL |
| `mcp_homelab_status` | Homelab health, metrics, Docker state | `docker`, `victoria-metrics` |
| `mcp_media` | Media ops: **GPU media-pipeline (10 tools, live 2026-08-28)** + legacy ComfyUI/HF (4 tools) | GPU host `:8189`, legacy `${MATRIX_IP}:8188` |
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
| **Purpose** | Knowledge base READ via Qdrant |
| **Tools (live)** | `kb_search(query, collection, top_k?)`, `kb_get_document(collection, doc_id)`, `kb_list_collections()`, `kb_recent_changes(collection, since?)` — **all read-only; no write tools exist** |
| **Inputs** | Query string, collection name, doc id |
| **Outputs** | Matching documents with scores, document content, collection listing |
| **Read/write** | **Read-only** (2026-08-28: server runs with a Qdrant read-only API key; writes would 403 at Qdrant even if a tool were added) |
| **Allowed paths** | `http://qdrant:6333` |
| **Context impact** | Low-Medium — returns compact document chunks |
| **Security** | Read-only Qdrant key (`QDRANT_READ_ONLY_API_KEY`); collection allowlist in the server config |

**Known gaps (D6 — separate workstream, open as of 2026-08-28):**
- Server allowlists `family_curated`/`homelab_curated`/`coding_curated`, but the
  only real KB collection is `family_kb` → `kb_search` finds nothing / `kb_list_collections`
  returns `not_found` for the allowlisted names.
- `kb_search` does exact-match `scroll` over payload text, NOT vector search.
- `family_kb` is **384-dim** (legacy harness embeddings) while the current
  `embeddings`/`homelab-embedding-v1` aliases return **768-dim** — never mix
  collections or re-embed in place; a v2 KB migration needs a new collection.
- The `family_kb_ingest` skill still targets the decommissioned harness
  `/knowledge/ingest` endpoint — broken; ingestion is currently manual
  (Qdrant API / ops script with the admin key).

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
| `mcp_home` | ✅ | — | — | — | — | — | Read (future) |

---

## Rules

- **Implemented.** All 8 servers run as containers on `ai-net` (streamable-http, port 8000)
  and are registered in `litellm/config.yml` (`mcp_servers`, `allow_all_keys: true` —
  decided 2026-08-25: every valid key may call every tool; no scoped grants).
- MCP servers run as separate containers on Thor (`compose/compose.mcp.yml`).
- The skill runner composes MCP tools into workflows — MCP servers do not know about skills.
- `mcp_code` is deferred to future exploration.
- Qdrant-backed servers must use scoped keys (read-only for `mcp_knowledge`);
  the Qdrant admin key stays OPS-only.
