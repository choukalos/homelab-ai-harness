# Thor Validation Log

> Phase 0 — Read-Only Backup and Discovery
> Date: 2026-07-03

---

## Docker State

### Containers (28 running)

| Container | Image | Ports | Network(s) | Role |
|---|---|---|---|---|
| litellm-proxy | ghcr.io/berriai/litellm:main-latest | 4000→4000 | ai-net | AI model gateway |
| open-webui | ghcr.io/open-webui/open-webui:main | 3000→8080 | ai-net | Chat UI |
| qdrant | qdrant/qdrant:latest | 6333→6333 | ai-net | Vector DB |
| ai-redis | redis:7-alpine | 6379 (internal) | ai-net | Task broker / cache |
| searxng | searxng/searxng:latest | 8088→8080 | ai-net | Search engine |
| searxng-valkey | valkey/valkey:9-alpine | 6379 (internal) | ai-net | SearXNG cache |
| crawl4ai | unclecode/crawl4ai:latest | 11235→11235 | ai-net | Web crawler |
| family-wiki | squidfunk/mkdocs-material:latest | 8011→8000 | ai-net | Family wiki |
| presenton | ghcr.io/presenton/presenton:latest | 5000→80 | ai-net | Presentation tool |
| litellm-db | postgres:16-alpine | 5432 (internal) | ai-net | LiteLLM metadata |
| ai-harness | home-ai-harness:local | 192.168.4.54:8090→8090 | ai-net, public-net | AI orchestrator |
| ai-harness-worker-1 | home-ai-harness:local | (internal) | ai-net | Celery worker |
| ai-harness-worker-2 | home-ai-harness:local | (internal) | ai-net | Celery worker |
| ai-harness-beat | home-ai-harness:local | (internal) | ai-net | Celery beat scheduler |
| ai-kb-watcher | home-ai-harness:local | (internal) | ai-net | KB file watcher |
| caddy | caddy:2 | 80, 443/tcp+udp | edge-net, public-net, ai-net | Reverse proxy |
| cloudflared | cloudflare/cloudflared:latest | (internal) | edge-net | Cloudflare tunnel |
| ghost-blog | ghost:5-alpine | 2368 (internal) | public-net | Blog |
| invest-hub-server | invest-hub-server:latest | 4000 (internal) | public-net | Invest Hub API |
| invest-hub-client | invest-hub-client:latest | 80 (internal) | public-net | Invest Hub UI |
| github-runner | myoung34/github-runner:latest | (internal) | public-net | GitHub Actions runner |
| node-exporter | prom/node-exporter:latest | 9100→9100 | monitoring-net | Host metrics |
| cadvisor | gcr.io/cadvisor/cadvisor:latest | 8081→8080 | monitoring-net | Container metrics |
| victoria-metrics | victoriametrics/victoria-metrics:latest | 9090→8428, 9091→8429 | monitoring-net, public-net | Metrics backend |
| grafana | grafana/grafana:latest | 3001→3000 | monitoring-net | Dashboards |
| plausible | ghcr.io/plausible/community-edition:v3.2.0 | 8082→8000 | monitoring-net, public-net | Analytics |
| plausible-db | postgres:16-alpine | 5432 (internal) | monitoring-net | Plausible DB |
| plausible-events-db | clickhouse/clickhouse-server:24.12-alpine | 8123, 9000, 9009 (internal) | monitoring-net | Plausible events |

### Compose Projects (6 active)

| Project | Config File(s) | Services |
|---|---|---|
| ai-core | compose/compose.ai-core.yml | litellm, open-webui, qdrant, ai-redis, searxng, searxng-valkey, crawl4ai, family-wiki, presenton, litellm-db |
| ai-harness | compose/compose.ai-harness.yml | ai-harness (uvicorn), worker-1, worker-2, beat, kb-watcher |
| homelab | compose/compose.core.yml + compose/compose.edge.yml | caddy, cloudflared |
| homelab-ghost | compose/compose.ghost.yml | ghost-blog |
| homelab-invest | compose/compose.invest-hub.yml | github-runner, invest-hub-server, invest-hub-client |
| monitoring | compose/compose.monitoring.yml | node-exporter, cadvisor, victoria-metrics, grafana, plausible, plausible-db, plausible-events-db |

*Note: compose.n8n.yml exists but n8n is not running.*

### Networks (4 used)

| Network | Driver | Used By |
|---|---|---|
| ai-net | bridge | ai-core, ai-harness, homelab |
| edge-net | bridge | homelab (caddy, cloudflared) |
| public-net | bridge | ai-harness, homelab, homelab-ghost, homelab-invest, monitoring |
| monitoring_monitoring-net | bridge | monitoring |

### Data Volumes (persistent paths)

| Path | Used By |
|---|---|
| /home/chuck/data/litellm-postgres/ | LiteLLM metadata DB |
| /home/chuck/data/litellm/ | LiteLLM data |
| /home/chuck/data/open-webui/ | Open WebUI data |
| /home/chuck/data/qdrant/ | Qdrant vector storage |
| /home/chuck/data/redis/ | Redis data |
| /home/chuck/data/searxng/ | SearXNG cache |
| /home/chuck/data/searxng-valkey/ | SearXNG valkey |
| /home/chuck/data/crawl4ai/ | Crawl4AI data |
| /home/chuck/data/ai-kb/ | Knowledge base (repo, raw, processed, failed) |
| /home/chuck/data/media/ | Skill/creative output |
| /home/chuck/data/presenton/ | Presenton storage |
| /home/chuck/data/caddy/ | Caddy data/config |
| /home/chuck/data/grafana/ | Grafana storage |
| /home/chuck/data/victoria-metrics/ | Victoria Metrics storage |
| /home/chuck/data/ghost/ | Ghost content |
| /home/chuck/data/plausible-db/ | Plausible PostgreSQL |
| /home/chuck/data/plausible-events-db/ | Plausible ClickHouse |
| /home/chuck/data/plausible-events-logs/ | Plausible ClickHouse logs |
| /home/chuck/data/invest-hub-runner/ | GitHub runner data |
| /home/chuck/workspace/ | Workspace (mounted RW in harness) |

---

## Compose Files

### compose.ai-core.yml
- **Networks:** ai-net (external)
- **10 services** — the full AI stack
- LiteLLM: `ghcr.io/berriai/litellm:main-latest`, config from `../litellm/config.yml` (ro), extra_hosts for matrix and macstudio
- Open WebUI: `ghcr.io/open-webui/open-webui:main`, connects to litellm:4000 as OpenAI backend, ComfyUI on matrix:8188, harness at ai-harness:8090
- Qdrant, Redis, SearXNG (+valkey), Crawl4AI, family-wiki, presenton all on ai-net
- Presenton: auth-enabled (user: presenton), LLM via litellm-proxy, searxng for search, image generation disabled

### compose.ai-harness.yml
- **Networks:** ai-net + public-net (external)
- **5 services** — uvicorn main + 2 celery workers + beat scheduler + kb-watcher
- Port binding: `${THOR_IP}:8090` → 192.168.4.54:8090 (LAN-only)
- env_file: `../.env`
- Environment: LITELLM, SEARXNG, CRAWL4AI, QDRANT, REDIS, MATRIX/COMFY, MEDIA_OUTPUT_DIR, INTERNAL/PUBLIC_BASE_URL, HARNESS/SIRI_API_KEY, WORKSPACE, PRESENTON, MYSQL
- Volumes: /data/ai-kb, /data/media, /workspace
- Workers: celery concurrency=4 each; beat: redbeat scheduler max-interval=5
- KB watcher: `python family_kb_watch.py`, embed model BAAI/bge-small-en-v1.5

### compose.core.yml
- **Networks:** defines edge-net, public-net, ai-net
- **1 service:** Caddy with Caddyfile mount (ro), data/config volumes
- Ports: 80, 443 (tcp+udp)

### compose.edge.yml
- **1 service:** cloudflared with `tunnel --no-autoupdate run`, TUNNEL_TOKEN from env
- Depends on caddy

### compose.ghost.yml
- **1 service:** ghost:5-alpine, MySQL on host.docker.internal, env_file from ../.env

### compose.invest-hub.yml
- **3 services:** github-runner, invest-hub-server, invest-hub-client
- All on public-net
- github-runner mounts docker.sock and compose dir for self-management

### compose.monitoring.yml
- **7 services:** node-exporter, cadvisor, victoria-metrics, grafana, plausible, plausible-db, plausible-events-db
- Networks: monitoring_monitoring-net + public-net
- victoria-metrics: prometheus.yml mount, 1y retention, extra_hosts for matrix and athena
- grafana: provisioning + dashboards mounts, sign-up disabled
- plausible: registration disabled, clickhouse for events, postgres for app data
- *mysql-exporter commented out* (config parsing issue with v0.15.1+)

### compose.n8n.yml (NOT RUNNING)
- Exists but not part of any active compose project

---

## LiteLLM Config

**File:** `litellm/config.yml`

### Model Definitions (4)

| model_name | Backend | Model | api_base |
|---|---|---|---|
| studio-gemma4-4b | openai/gemma-4b (LM Studio) | Gemma 4B | http://macstudio:1234/v1 |
| matrix-coder | openai/qwen36-27b (vLLM) | Qwen3.6 27B | http://matrix:8000/v1 |
| matrix-gemma4-moe | ollama/gemma4:26b (Ollama) | Gemma4 26B MoE | http://matrix:11434 |
| embeddings | ollama/nomic-embed-text (Ollama) | Nomic Embed | http://matrix:11434 |

### General Settings

| Setting | Value |
|---|---|
| master_key | os.environ/LITELLM_MASTER_KEY |
| database_url | os.environ/LITELLM_DATABASE_URL |
| set_verbose | true |
| debug_level | WARNING |

### Callbacks
- prometheus (for Victoria Metrics scraping)

### Observations
- **No model aliases defined** — clients must use raw `model_name` values
- **No per-key restrictions** — key-level model allowlists not configured
- **No MCP tool configuration**
- **No team configuration**
- Nominal pricing for budget tracking ($0.000001/token chat, $0.0000001/token embeddings)

---

## AI Harness Structure

**Location:** `ai-harness/`

### Top-level files

| File | Purpose |
|---|---|
| app.py | FastAPI main entry point |
| Dockerfile | Build image home-ai-harness:local |
| requirements.txt | Python dependencies |
| family_kb_watch.py | KB watcher entry point |
| architecture.md | Architecture overview |
| STRATEGY.md | Strategy documentation |
| TOOLING_IDEAS.md | Tooling exploration notes |
| README.md | Project documentation |

### Modules

| Module | Sub-modules | Purpose |
|---|---|---|
| **infra/** | core/, scheduler/, tasks/, workflows/ | Celery, redbeat, task definitions, workflow orchestration |
| **apps/** | demo_workflow/, pm_demo/ | Demo/example workflows |
| **channels/** | openwebui/, siri/ | Channel-specific integrations |
| **research/** | deep_research/, market_research/, web_search/ | Research pipelines |
| **knowledge/** | family_kb/ | Knowledge base operations |
| **creative/** | charts/, layout/, presentation/ | Creative generation tools |
| **media/** | comfy_client.py, filename_util.py, router.py, schemas.py, workflows/ | ComfyUI client, media processing |
| **filetools/** | router.py, schemas.py, service.py, README.md | File operations |

### Public Endpoints (via Caddy → siri.choukalos.com)

| Path | Auth | Purpose |
|---|---|---|
| /health | None | Health check |
| /siri/* | X-API-Key: SIRI_API_KEY | Siri actions |
| /media/files/* | None | Media file retrieval |

---

## Caddy Configuration

**File:** `caddy/Caddyfile`

### Global
- `auto_https off` (Cloudflare handles TLS termination)
- Gzip encoding
- Security headers: X-Content-Type-Options, X-Frame-Options, Referrer-Policy

### Routes

| Host | Path | Backend | Auth |
|---|---|---|---|
| www.choukalos.com | all | → redirect to choukalos.com | — |
| choukalos.com | all | ghost-blog:2368 | None (public) |
| invest.choukalos.com | /api/* | invest-hub-server:4000 | None (public) |
| invest.choukalos.com | /* | invest-hub-client:80 | None (public) |
| api.choukalos.com | all | invest-hub-server:4000 | None (public) |
| siri.choukalos.com | /health | ai-harness:8090 | None |
| siri.choukalos.com | /siri/* | ai-harness:8090 | X-API-Key: $SIRI_API_KEY |
| siri.choukalos.com | /media/files/* | ai-harness:8090 | None |
| llm.choukalos.com | all | litellm-proxy:4000 | X-API-Key: $LITELLM_PUBLIC_API_KEY |
| plausible.choukalos.com | /js/*, /api/event | plausible:8000 | None (public narrow) |
| plausible.choukalos.com | everything else | 404 | Blocked |

### Observations
- Caddy is on all 3 networks (edge-net, public-net, ai-net) — can reach all services
- Auth for siri and llm done in Caddy via `$SIRI_API_KEY` and `$LITELLM_PUBLIC_API_KEY` env vars
- No Open WebUI route (LAN-only on :3000)
- No Grafana route (LAN-only on :3001)
- No Presenton route (LAN-only on :5000)
- No SearXNG route (LAN-only on :8088)
- No family-wiki route (LAN-only on :8011)

---

## Cloudflare Configuration

- **No local config files** — tunnel managed via Cloudflare dashboard
- `cloudflared` container: `tunnel --no-autoupdate run` with `TUNNEL_TOKEN` from .env
- All public HTTPS traffic: Cloudflare → cloudflared → Caddy (port 80) → backend services
- Caddy runs with `auto_https off` since Cloudflare terminates TLS

---

## Other Config Files

| File | Purpose |
|---|---|
| searxng/settings.yml | SearXNG search engine config |
| prometheus/prometheus.yml | Victoria Metrics scrape config |
| grafana/provisioning/ | Grafana datasource/dashboard auto-provisioning |
| grafana/dashboards/ | Grafana dashboard JSON files |
| plausible/clickhouse/ | ClickHouse config overrides (logs, ipv4-only, low-resources) |
| compose/compose.n8n.yml | n8n compose (not running) |

---

## Scripts

| Script | Purpose |
|---|---|
| homelab.sh | Main orchestration script — manages compose projects (up/down/rebuild/etc.) |
| siri-script.sh | iOS Siri shortcut integration helper |

---

## External Dependencies

| Host | IP | Service | Port |
|---|---|---|---|
| matrix | 192.168.4.55 | vLLM | 8000 |
| matrix | 192.168.4.55 | Ollama | 11434 |
| matrix | 192.168.4.55 | ComfyUI | 8188 |
| matrix | 192.168.4.55 | media-pipeline | 8189 |
| macstudio | 192.168.4.56 | LM Studio | 1234 |
| host.docker.internal | — | MySQL (Ghost) | 3306 |

---

## Validation Entry — 2026-09-07: Media Pipeline Gap-Fill (Part 2, T2/T3)

Source plan: `/home/chuck/media_pipeline_gaps.md` (updated from v2 contract).
Matrix side (M1–M9) pre-verified live; thor side implemented + verified:

| Check | Result |
|---|---|
| Matrix `/openapi.json` — all 9 new endpoints present (`/trim /freeze /caption /info /upload_local /download /upload /dl_token /dl/{token}` + extended `/assemble`) | ✅ PASS |
| Client conformance `mcp/servers/media/test_client_t2.py` (18 checks: info/trim×3/freeze/caption/upload 400-gate/download/dl_token+byte-identical LAN pull/assemble M4/put/pull+job-id resolution) | ✅ 18/18 PASS |
| `mcp_media` tools/list — 18 tools, schemas correct (`media_pull`: path/ttl_hours/local_dir; `media_assemble`: vo_start/loudnorm; `media_trim`: source/start/end/duration/fps/width/height) | ✅ PASS |
| E2E `tools/call`: `media_put` staging→matrix, `media_pull` signed URL, GPU-path passthrough, staging-gate error for file outside `/home/chuck/workspace/media` | ✅ PASS |
| Caddy `@siri_pipeline` route (option C, `siri.choukalos.com/media/pipeline/*`): `/dl/<token>` 200 + sha256 byte-identical to direct matrix fetch; `/upload` 401 without key / 200 with chuck key; `/dl_token` + `/health` → 404 (LAN-only); bad token → 404 | ✅ 7/7 PASS (LAN) |
| Same checks through the public URL `https://siri.choukalos.com/media/pipeline/*` (Cloudflare tunnel) | ✅ PASS (200/401/404; sha256 match) |
| Staging cleanup script `scripts/cleanup-media-staging.sh` (dry-run + real; `MEDIA_STAGING_MAX_AGE_DAYS=7` in `.env`) | ✅ PASS |
| Off-LAN device acceptance | ⏳ PENDING — manual step for Chuck (only remaining item; CF rules + T1 done 2026-09-07) |

Caddyfile change: `@siri_pipeline` matcher + `handle` block (public `/dl/*`,
key-auth `/upload`, 404 catch-all) — `caddy validate` + reload clean.
Compose change: `mcp_media` env `MEDIA_STAGING_DIR` + `MEDIA_PUBLIC_URL` +
rw mount `/home/chuck/workspace/media:/home/chuck/workspace/media`.
Surgical rebuild: `docker compose --env-file .env -f compose/compose.mcp.yml
build mcp_media && up -d --force-recreate mcp_media` (avoids rebuilding all
10 MCP servers).

**T1 — portal `/files/` cache fix (implemented 2026-09-07, ordered last per
decision):** `portal/server.py` — `FILES_CACHE_MAX_AGE` 3600→60;
`/files/` now sends `Cache-Control: max-age=60, must-revalidate`;
`_send_file()` sends `Last-Modified` (mtime) and answers
`If-Modified-Since` with `304` (no body; cache headers repeated). Deployed
via surgical rebuild of `portal:local` only.

| Check | Result |
|---|---|
| Origin headers: `Cache-Control: max-age=60, must-revalidate` + `Last-Modified` on `/files/video/peanut_doc_final.mp4` | ✅ PASS |
| `If-Modified-Since` = mtime / future → `304` (0 bytes); old date → `200` full body | ✅ PASS |
| Range regression: `Range: bytes=0-99` → `206`, 100 bytes | ✅ PASS |
| Overwrite public file with different size → new content-length at origin immediately | ✅ PASS (2026-09-07 17:19) — 10MB test copy swapped in; no sudo needed (`video/` dir is chuck-writable, delete+recreate) |
| Public URL serves new size within ~2 min | ✅ PASS — bare public URL served the new content-length within 15s (edge `EXPIRED` → revalidated); original restored sha256-verified and live again within ~75s |

**Pending (manual, outside this session):**
- Off-LAN device acceptance (Chuck, from a network outside the LAN) — the
  only remaining item. CF cache rules + purge were completed 2026-09-07
  (dashboard; see `docs/thor_manual_tasks.md` Phase 15): `/files/*` edge
  revalidates every ~60s; `/media/pipeline/dl/*` serves
  `cf-cache-status: DYNAMIC` (edge does not cache — bypass; downloads via
  origin).

---

## Validation Entry — 2026-10-31: Song Transcription (`/transcribe` → `media_transcribe_song`)

Source plan: `docs/song_transcribe_plan.md`; Matrix spec:
`docs/song_transcribe_matrix_handoff.md`. Matrix flow built by the GPU-host
AI; thor side (mcp_media tool + client) built + verified here.

**Matrix-side verification (live, direct pipeline API):**

| Check | Result |
|---|---|
| Happy path (synthesized 40 s ground-truth file: D major, 120 BPM, D–A–Bm–G ×5) → job done, all 5 outputs present | ✅ PASS |
| Key detection vs ground truth | ✅ PASS (D major) |
| BPM vs ground truth | ✅ PASS (123 vs 120, within ±5%) |
| Note events + tab mapping invariant (`open_string + fret == midi`) | ✅ PASS (196/196 mapped notes) |
| Determinism (2nd run, diff of notes/chords/sections/tab data) | ✅ PASS (byte-identical) |
| Error: `instrument="piano"` → 400 at submit | ✅ PASS |
| Error: 5 s clip → clean job error `"audio too short"` | ✅ PASS |
| Metering: `media_work_units_total{kind="transcribe"}` (80.0 = 40 s × 2), `media_cost_usd_total{stage="transcribe"}` at exactly the $3.1e-5/s placeholder rate, user/client stamped | ✅ PASS |
| **Chord detection** (QA item 5: clean I–V–vi–iv file → progression 100%) | ❌ **FAIL — `chords=[]` on both runs; `chord_progression: n/a`** |
| Real song (Riptide, 204 s): key/BPM/chords vs known ground truth | ❌ **Quality FAIL — key C# major (expected D), BPM 103.4 (expected ~96), 1 chord total (expected D–Bm–G–A loop)** |
| Real song: lyrics | ⚠️ PARTIAL — 4 lines in 204 s (first 2 verbatim-correct; "extremely sparse" per the LLM caveat) |

**Thor-side verification (mock pipeline + live E2E):**

| Check | Result |
|---|---|
| Mock-pipeline suite `mcp/servers/media/test_transcribe.py` (finalize_job transcribe branch + regressions, transcribe() blocking/non-blocking, poll running→done, 4-way source resolution incl. staging guard + YouTube regex, tool results, identity, media_fetch) | ✅ 27/27 PASS |
| MCP schema via `tools/list` (23 tools on `mcp_media`) | ✅ PASS |
| Production container rebuild + restart (`docker compose -f compose/compose.mcp.yml up -d --build mcp_media`); startup health OK | ✅ PASS |
| Tool live via LiteLLM `/mcp-rest/tools/list` (87 tools total; `media_transcribe_song` present) | ✅ PASS |
| E2E via LiteLLM `/mcp-rest/tools/call` (chuck's key): YouTube URL → `media_transcribe_song(non_blocking)` → `job_id` in ~1 s | ✅ PASS |
| `media_job_result` poll → done + 5 artifact paths + `location` | ✅ PASS |
| Identity threading: job payload `user=chuck` (resolved from the LiteLLM key), `client=pi` | ✅ PASS |
| `media_fetch` tab.md + lyrics.txt → local media library | ✅ PASS |
| `media_pull` → signed URL → **HTTP 200 through `siri.choukalos.com`** (off-LAN public route), 15,264 bytes = local copy | ✅ PASS |

**Open quality defects (Matrix side, for the next iteration):**
1. **Chord detection returns empty** on both the clean ground-truth file and a
   real song — the CQT/template stage is effectively dead (QA item 5 fails).
   Likely candidates: template scoring/normalization, beat-grid alignment, or
   a silent stage failure. Chords are the backbone of a guitar tab — this is
   the top fix.
2. **Key/BPM drift on real music**: C# major vs D (a semitone — suggests a
   possible 1-bin pitch-class offset in the chroma stage) and BPM biased fast
   (123 vs 120 synthesized; 103.4 vs ~96 Riptide).
3. **Sparse lyrics** on a vocal-heavy song (4 lines / 204 s) — check VAD
   aggressiveness and whether the LLM polish step drops lines (the polish
   validation checks line fidelity but not line *count* preservation — spec
   hole worth closing).
4. Minor: spurious harmonic notes (MIDI 81–93) from bright sources get
   `role=lead/accompaniment` with `tab=null` — spec-compliant (unmappable)
   but pollutes lead stats; filter them at classification.
5. Minor: `title`/`artist` come back `unknown` — the pipeline only sees the
   audio file; consider an optional `metadata` field on `/transcribe`
   (yt-dlp title/uploader) in a future contract revision.

---

## Validation Entry — 2026-10-31 (part 2): `/transcribe` chord-detection fix re-verification

Matrix shipped the chord-detection fix; re-ran the smoke test (synthetic
ground truth + real songs) plus isolation tests.

| Check | Result |
|---|---|
| Chord detection on synthetic ground truth (40 s, D major, 120 BPM, D–A–Bm–G ×5) | ✅ **FIXED — chords now exact: Dmaj7/Amaj7/Bm7/Gmaj7, 5 each** (was `chords=[]`); key D major, BPM 123 |
| 48 kHz WAV variant of the same ground truth | ✅ PASS — D major, 120.2 BPM, same chords (D7/Amaj7/Bm7/Gmaj7 ×5), clean pitch classes |
| Real song #2 — Sweet Home Alabama (webm/opus, 284 s) | ✅ PASS — key G major, chords Gmaj7×22 / Cmaj7×16 / Dmaj7×12 (the D–C–G loop), clean G-major pitch classes |
| Real song #1 — Riptide (webm/opus **and** AAC m4a, 204 s) | ✅ **Correct — see ground-truth correction below** |
| Determinism / cross-format stability (Riptide opus vs AAC: same key/chords/BPM) | ✅ PASS |
| Metering in VictoriaMetrics: `media_cost_usd_total{stage="transcribe",user="chuck"}` ($0.0428) + `media_work_units_total{kind="transcribe"}` (1380 units) via the existing `media-pipeline-matrix` Prometheus scrape | ✅ PASS — AI Work & Spend dashboard (queries `media_cost_usd_total`/`media_work_units_total`) exposes transcribe automatically; no plumbing needed |
| Lyrics sparseness | ❌ **STILL OPEN** — Riptide 4 lines / ~30 expected (first 2 verbatim-correct, rest garbled); SHA 2 lines. Raw ASR quality on real vocals remains the gap (VAD/whisper stage, Matrix side) |

**Ground-truth correction (important):** the earlier "1-semitone offset"
defect report was **a false alarm caused by a wrong ground-truth assumption**,
not a pipeline bug. Riptide's standard guitar tabs are in D major (D–Bm–G–A),
but the official recording is actually in **C# major** (C#–A#m–G#–F#), ~102
BPM. Verified three independent ways:

1. **Raw-audio Goertzel measurement** (pure-Python, on the pipeline's decoded
   `audio.wav`, verse 24–54 s): C#3 14.7e12 vs D3 2.0e12 (7.3×), A#3 8.8e12
   vs A3 0.6e12 (13.8×), G#3 > G3 — the recording's fundamental content is
   C#-major.
2. **Two independent codec paths** (opus webm + AAC m4a) both yield C# major
   with identical chords/BPM — a decoder bug cannot shift both the same way
   while leaving SHA (opus) and both synthetic WAVs (44.1/48 kHz) correct.
3. **External source** (songbpm.com): "Riptide … tempo of 102 BPM … C♯/D♭ key,
   3:24" — matches the pipeline's C# major @ 103.4 BPM (1.4% off).

The pipeline's absolute pitch calibration is therefore **verified correct**
against four independent ground truths (2 synthetic WAVs @ 44.1/48 kHz,
SHA webm, Riptide recording). Key/BPM "drift" is closed.

**Remaining open item (Matrix side):** the lyrics stage — sparse/garbled ASR
on real vocals (Riptide: 4 lines; the LLM caveat confirms the raw ASR was
bad, so this is pre-polish). Tab data (key/chords/notes/structure) is fully
verified.

---

## Validation Entry — 2026-11-01: `/transcribe` chord/key/fingering surface (`media_transcribe_song` update)

Matrix spec: `transcribe_thor_spec.md` (repo root, delivered by the matrix AI
2026-10-31 — "implemented + verified" on the media-pipeline; deterministic
post-processing, worker stage 5.5 — the LLM never sees or touches any of it).
Thor side (mcp_media client + tool + tests + docs) updated + verified here.
The spec file was consumed and removed with this change.

**Contract (what changed):** `/transcribe` gains `tuning` (v1 `standard`
only), `stems` default flipped **false → true**, `full_notes`,
`transpose_semitones` (int −12..12, bool rejected), `target_key` (tonic
`^[A-G][#b]?m?$`, offset from the **detected** key, shortest direction ±6,
wins over `transpose_semitones`), `chord_style` (`as_detected` | `triads` |
`power`, case-insensitive), `capo` (bool), `shape_hints` (bool, default
true). `analysis.json` echoes the four surface fields + `capo_suggestion`
(non-null only when a capo was applied) + `caveats`; chord events gain
`shape` when hints are on; `tab.md` gains `Transposed ±n` / `Capo: n` /
power / triad header lines + per-chord shape rendering.

**Live pipeline 400 contract (direct API, matrix :8189):**

| Check | Result |
|---|---|
| `chord_style="sevenths"` → 400 `chord_style must be as_detected\|triads\|power` | ✅ PASS |
| `transpose_semitones=13` → 400 (range) | ✅ PASS |
| `transpose_semitones=true` → 400 (bool-as-int rejected) | ✅ PASS |
| `target_key="Eb7"` → 400 (tonic regex) | ✅ PASS |
| `capo=1` / `shape_hints="yes"` → 400 (bool-only) | ✅ PASS |
| `tuning="drop_d"` → 400 (v1 standard only) | ✅ PASS |
| `instrument="piano"` → 400 (v1 guitar only) | ✅ PASS |

**Thor-side verification (mock pipeline):**

| Check | Result |
|---|---|
| Mock-pipeline suite `mcp/servers/media/test_transcribe.py` — extended: mock now mirrors the submit-time 400 contract + echoes the new analysis fields (echoed params, per-chord `shape` only when `shape_hints`, `capo_suggestion` only when capo applied, caveats, tab.md headers) | ✅ **57/57 PASS** (was 27/27) |
| Client `transcribe()`: faithful-to-recording defaults in payload (guitar/standard/lyrics=true/stems=**true**/full_notes=false/transpose=0/as_detected/capo=false/shape_hints=true; `whisper_model`/`target_key` omitted when unset) | ✅ PASS |
| Client `transcribe()`: all 9 new params forwarded (case-sensitive values, negative transpose, target_key, whisper_model) | ✅ PASS |
| Client → mock 400 at submit: 13 bad-payload cases (bad style, non-bool flags, ±13, bool-as-int, float transpose, bad tonics, bad tuning/instrument) | ✅ PASS |
| Tool `media_transcribe_song`: new params accepted + `chord_style="POWER"` normalized to `power` in the payload; `target_key="Bb"` forwarded | ✅ PASS |
| Tool: 10 clean client-side validation errors (no POST, no job) — tuning, chord_style, transpose ±13/bool, target_key ×2, capo/shape_hints/full_notes non-bool | ✅ PASS |
| `finalize_job` transcribe branch + `media_job_result` poll (running → done, 5 paths + location) — regression | ✅ PASS |
| `media_fetch` artifacts: analysis.json echoes the surface (defaults + capo job variants), tab.md shape-hint line + capo header | ✅ PASS |

**Live E2E (via LiteLLM `/mcp-rest/tools/call`, chuck's key — the real agent path):**

| Check | Result |
|---|---|
| Tool schema: 13 params on `media_transcribe_song` with correct types/defaults (MCP `tools/list` in-container **and** LiteLLM `/mcp-rest/tools/list`, 87 tools total) | ✅ PASS |
| Tool client-side validation live (4 bad calls → clean errors, no jobs created) | ✅ PASS |
| Job payload recorded on the pipeline carries the full surface + identity (`user=chuck`, `client=pi`) | ✅ PASS |
| **Riptide e2e #1** — YouTube URL (yt-dlp ingest) + `chord_style=power` + `capo=true` + `shape_hints=true`: detected **C# major** (ground truth per 2026-10-31 entry); `capo_suggestion={capo:1, finger_key:C}`; shapes exactly match the spec's example table — A5 `open A5`, G5 `power @ 3 (E-shape)`, C5 `power @ 3 (A-shape)`, F5 `power @ 1 (E-shape)`; tab.md headers `Capo: 1 — chords shown as C finger shapes (sounding key C# major)` + `Chords shown as power chords (root + 5th)`; caveats (capo + power) present | ✅ PASS |
| **Riptide e2e #2** — `target_key="E"`: `transpose_semitones=3` applied (C# → E, shortest direction), key **E major**, caveat `transposed +3 semitones (detected C# major -> E major)`, tab.md header `Transposed +3 semitones from the source recording`, progression C#m7–Bmaj7–Emaj7–Amaj7 (= the spec's +3 example), shape hints on the transposed chords (C#m7 `A-shape barre @ 4`, Emaj7/Bmaj7 `open`), `capo_suggestion: None` | ✅ PASS |
| `media_job_result` poll path (transcribe job): running → done + 5 artifact paths + `location` | ✅ PASS |
| Identity threading on the new-surface jobs (`user=chuck`, `client=pi` in the pipeline payload) | ✅ PASS |

**Notes:**
- `stems` default flipped false → true in the MCP tool to match the server
  default (spec table); demucs failure falls back to full-mix ASR + caveat,
  so the job is never blocked on stems.
- v1 scope per spec: per-chord *easiest* shape (open if available, else
  lowest-fret barre/power); a global "consistent position" pass is a v2
  refinement.
- Lyrics sparseness on real vocals remains the open Matrix-side item (see
  2026-10-31 entries) — unchanged by this update (the surface is
  deterministic post-processing and never touches lyrics).

## Validation Entry — 2026-11-01 (part 2): Song-tab publishing (`/files/tabs/`)

**Scope:** publish transcribed songs (tab + lyrics) to the public blog's
`/files/tabs/` drop zone. Answer to "does the media MCP tool need expanding?"
— **no**: `media_transcribe_song` + `media_fetch` already produce local
artifacts; the only gap was the `publish_file` skill's subdirectory
allowlist (no `tabs`).

**Changes:**
- `skills/publish_file/skill.py`: `tabs` added to `SUBDIRS` allowlist
  (live bind mount — effective immediately, no rebuild/restart).
- `agents-skills/publish-file/SKILL.md` + `skills/publish_file/README.md`:
  `tabs` documented (README also fixed a stale list that wrongly included
  `files`).
- `agents-skills/song-transcribe/SKILL.md`: new step 6 — publish workflow
  (fetch into per-song `subdirectory=<slug>` to dodge the generic
  `tab.md`/`lyrics.txt` basenames, slug-prefixed `destination_name`,
  pre-publish caveats: draft quality, LLM-guessed title, ASR lyrics).

**Validation:**

| Check | Result |
|---|---|
| `publish_file` accepts `subdirectory=tabs` (skill-runner job, real API path) | ✅ PASS |
| Collision guard: second publish of same name fails cleanly (`overwrite=true` required) — exercised live when a duplicate lyrics publish raced the first | ✅ PASS |
| Riptide e2e publish: `media_fetch` (per-song `subdirectory=riptide`) → `publish_file` ×2 → `https://choukalos.com/files/tabs/riptide-tab.md` + `riptide-lyrics.txt` | ✅ PASS |
| Public verification through Cloudflare → Caddy → portal: `/files/tabs/` browse page lists both; both files serve 200 with correct content (`text/markdown` / `text/plain`) | ✅ PASS |
| Tab header corrected before publish (LLM-guessed "Lady" → "Riptide — Vance Joy", known from the source URL) | ✅ PASS |

**Notes:**
- Per-song local organization: `media_fetch(host_path, subdirectory=<slug>)`
  → `/home/chuck/data/media/generated/pipeline/<slug>/` (an approved
  publish source root). No media MCP tool changes needed.
- The portal serves `.md` as raw `text/markdown` (no rendering) — the ASCII
  fretboard renders in the browser's default font, so alignment can look
  slightly off; content is complete. A rendered HTML song page is a
  possible follow-up.
- Lyrics of commercial recordings are ASR output — publishing them is the
  owner's call (stated in the skill's pre-publish caveat).
