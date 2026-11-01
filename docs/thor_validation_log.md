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

## Validation Entry — 2026-11-01 (part 3): PDF song sheets (`/files/tabs/*.pdf`)

**Scope:** publish transcribed songs as visually appealing PDFs (the new
primary published artifact — raw `.md`/`.txt` no longer published by
default). Added the `scripts/tab-pdf/` generator (deterministic HTML→PDF,
WeasyPrint 70, no LLM) and transcribed + published three more songs.

**Changes:**
- `scripts/tab-pdf/` — `tab_pdf.py` (parses the pipeline's `tab.md`
  verbatim: header meta chips from `analysis.json` incl. capo suggestion,
  per-section chords + shape hints, boxed monospace tab blocks, lyrics page
  with timestamp-stripped stanzas) + `Dockerfile` (weasyprint + variable
  TTFs baked in: Playfair Display / Inter / JetBrains Mono) + README.
- `agents-skills/song-transcribe/SKILL.md` — step 6 rewritten: PDF is the
  primary published artifact; raw files only on request.

**Validation:**

| Check | Result |
|---|---|
| Font QA: `pdffonts` shows `Inter` + `Playfair-Display-Bold` + `JetBrains-Mono` embedded (no `DejaVu-*` fallback) on all 4 PDFs | ✅ PASS |
| Layout QA: `pdftotext -layout` — header chips (KEY/BPM/TUNING/CAPO), capo + power-chord notes, section heads with time ranges, monospace tab alignment intact, lyrics stanzas | ✅ PASS |
| Riptide PDF: 21 pp, 11 sections, capo chip "1 (C finger)", 50 lyric lines | ✅ PASS |
| Riptide: old `riptide-tab.md` + `riptide-lyrics.txt` removed from the public drop zone (PDF only) | ✅ PASS |
| **Back in Black** (AC/DC official 4K, `99d8f532c3dc`): duration 4:13.8 = 254 s source ✓, A major / 94.0 BPM, 49 s instrumental intro (matches the song), distortion caveat; 20 pp | ✅ PASS |
| **Old Porch** (Mike Foss & Merkules official, `09c97f3624ae`): duration 4:06.8 = 247 s source ✓, D major / 77.1 BPM; 19 pp | ✅ PASS |
| **Submission** (Sex Pistols official, `213ee1a18c47`): duration 4:13.4 = 254 s source ✓, ASR caught "Submission going down"; 26 pp | ✅ PASS |
| Public verification (Cloudflare → Caddy → portal): all 4 PDFs serve 200 `application/pdf`, sha256 matches the local files, browse page lists them | ✅ PASS |

**Notes:**
- WeasyPrint 70 resolves fonts via Pango/fontconfig; its `@font-face` path
  cannot instantiate the JetBrains Mono variable font (silently falls back
  to DejaVu). Fix: use fontconfig family names in CSS (`'JetBrains Mono'`,
  `'Playfair Display'`, `'Inter'`) — no `@font-face` at all.
- Song identity verified by duration match against the source video + key /
  BPM / structure plausibility (the pipeline payload only retains the
  ingested webm path, not the original URL).
- ASR lyrics remain sparse/garbled on dense rock vocals (Back in Black: 8
  lines, Submission: 6) — the known Matrix-side issue; the DSP tab content
  is unaffected.
- A duplicate publish loop (harness replay after compaction) published the
  three new PDFs ~30 s before the explicit publish call; the collision guard
  (`overwrite=false`) made it a harmless no-op — published files verified by
  sha256.

## Validation Entry — 2026-11-01 (part 4): `media_render_tab_pdf` MCP tool

**Scope:** the tab→PDF generator (previously a hand-typed `docker run` of
the `homelab-tab-pdf` container on thor) is now a first-class `mcp_media`
tool, so any client on any machine can render a transcribe job's tab PDF
with one tool call.

**Changes:**
- `mcp/servers/media/tab_pdf.py` — canonical generator source (moved from
  `scripts/tab-pdf/`); new importable `render(song_dir, out_path, title,
  artist) -> {pdf, pages, title, artist, sections, lyric_lines}`; the CLI
  `main()` now wraps it.
- `mcp/servers/media/server.py` — new `media_render_tab_pdf(job_id,
  title?, artist?, slug?)` tool: fetches the job's `tab.md` (required) /
  `lyrics.txt` / `analysis.json` from the GPU host into a temp dir,
  renders in-process (WeasyPrint), writes
  `MEDIA_PIPELINE_FETCH_DIR/<slug>/<slug>-tab.pdf`, returns
  `{local_path, size_bytes, pages, title, artist, sections}`.
- `mcp/servers/media/Dockerfile` — WeasyPrint 70 + pango/cairo system
  deps + the song-sheet fonts (Playfair Display / Inter / JetBrains Mono
  variable TTFs) + poppler-utils baked in.
- `scripts/tab-pdf/` — now a standalone/QA wrapper: `Dockerfile` builds
  from the repo root (`docker build -f scripts/tab-pdf/Dockerfile .`) and
  COPYs the canonical `mcp/servers/media/tab_pdf.py`.
- Docs: media README (tool row + history), song-transcribe skill (step 6
  uses the MCP tool), main README skill line.

**Validation:**

| Check | Result |
|---|---|
| Container: weasyprint 70.0 importable, `tab_pdf.render` callable, all 4 fonts in `/usr/share/fonts/tabpdf/`, `pdffonts` present | ✅ PASS |
| Agent path (LiteLLM `/mcp-rest/tools/call` → `media_render_tab_pdf`), job `99d8f532c3dc` (Back in Black), `slug=bib-mcp`: 20 pp, 16 sections, 8 lyric lines, 66 KB | ✅ PASS |
| Font QA on the MCP-rendered PDF: `Inter` + `Playfair-Display-Bold` + `JetBrains-Mono` embedded, no `DejaVu-*` | ✅ PASS |
| Layout QA (`pdftotext -layout` p1): "Back in Black" / "AC/DC" / chips (KEY A major, BPM 94.0, TUNING Standard, CAPO —) / "VERSE 0:00.0–0:49.4" | ✅ PASS |
| Error: `job_id="../etc/passwd"` → `invalid job_id` (path traversal rejected) | ✅ PASS |
| Error: nonexistent job `deadbeef0000` → `tab.md missing for job deadbeef0000 (run media_transcribe_song first)` | ✅ PASS |
| Error: `slug="Bad_Slug"` → `invalid slug (lowercase letters, digits, dashes)` | ✅ PASS |
| Schema via LiteLLM `tools/list`: 88 tools, `media_render_tab_pdf` params `[job_id, title, artist, slug]`, required `[job_id]` | ✅ PASS |

**Notes:**
- The fontconfig "No writable cache directories" warnings at runtime are
  harmless — the font cache is built at image build time (`fc-cache` as
  root); family names resolve fine.
- Tool count: mcp_media 24 (was 23), LiteLLM 88 (was 87).

## Validation Entry — 2026-11-01 (part 5): chord-over-lyrics PDF layout

**Scope:** the PDF tabs were hard to play AND sing from (lyrics were a
separate page; the fretboard tab carries no lyric alignment). Restructured
the `tab_pdf` generator into a **CHART** part (chords over the word-timed
lyrics — lead-sheet style, play & sing at once) followed by a **TAB** part
(fretboard reference). Same `media_render_tab_pdf` tool — no client change.

**How placement works (all deterministic, from `analysis.json`):**
- `sections[].lyrics[].words[].start_s` = ASR **word-level** timestamps;
  `sections[].chords[].time_s` = chord event times.
- A chord at time t lands on the last word that started at or before t
  (a word is "active" until the next word starts); chords before the first
  word attach to the first word; multiple changes on one word list
  together; chords between lines attach to the first word of the next line.
- Sections with chords but no lyrics (intros/outros) → timed chord strip.
- Fallbacks: lines lacking word timestamps get words interpolated evenly
  across the line window; sections missing from analysis keep the tab.md
  `Lyrics:` lines as plain chart lines. The standalone lyrics page is gone.

**Changes:** `mcp/servers/media/tab_pdf.py` (`parse_analysis_sections`,
`place_chords`, `build_chart_section_html`, new two-part `build_html`,
chart CSS), `server.py` tool description, docs (media README, skill, main
README).

**Validation:**

| Check | Result |
|---|---|
| Riptide (22 pp, 50 chart lines): chord bbox x-center vs word x-center — A5 at x=49–60 above "If" at x=49–56 (same column, 14 pt above) | ✅ PASS |
| Riptide chorus: A5 above "Taking", C5 above "away" (chords 77.3/79.7 s before first word 89.7 s → both on first word, correct lead-sheet behavior) | ✅ PASS |
| Back in Black (21 pp, 8 chart lines): Amaj7 over "be back. Yes, I'm letting loose"; 49 s intro shows as timed strip | ✅ PASS |
| Old Porch (20 pp, 57 chart lines): Dmaj7 over "The best thing about the future…" | ✅ PASS |
| Submission (27 pp, 6 chart lines): D#maj7 over "I'm on a submarine…"; lyric-less chorus renders as G#6 strip | ✅ PASS |
| Fonts on all 4: Inter / Playfair-Display-Bold / JetBrains-Mono(-Bold) embedded, no DejaVu fallback | ✅ PASS |
| All 4 re-published via `publish_file` (overwrite=true) and verified publicly (sha256 match) | ✅ PASS |

**Notes:**
- Root-owned PDFs left by the earlier standalone-container run blocked the
  non-root mcp_media user from overwriting (`Permission denied`) — removed
  the stale files (chuck-owned dirs) so the tool could re-render in place.
- ASR lyric sparseness (Back in Black 8 lines, Submission 6) is unchanged —
  the chart only places chords where lyrics exist; the tab part is
  unaffected.

## Validation Entry — 2026-11-01 (part 6): chord-fingering grid (CHORDS part)

**Scope:** per the owner's suggestion, the PDF now opens (after the header)
with a CHORDS part — a grid of fixed-size chord fingering diagrams
("sheet of tokens"), one per unique chord, each annotated with the fret
the chord starts on. Denser + more visually appealing than ASCII blocks;
client-agnostic (same `media_render_tab_pdf` tool).

**How it works (all deterministic):**
- Shapes from the pipeline's `shape` field: `power`/`barre` generated
  programmatically (base E/A + `fret`; major/minor from the symbol —
  E-shape 022100/022000, A-shape x02220/x02210 shifted to the fret),
  `open` chords from a ~45-shape standard open-shape library
  (C/Cmaj7/C7/C6/G/G7/D/Dmaj7/A/Am/Am7/Emaj7/F/Fm7/B7/…).
- Each token: chord name, 6-string × 4-fret-space diagram (finger dots,
  X/O markers above the nut for open chords), starting-fret annotation
  ("3rd fret" / "open"). Unknown shapes render name-only.
- Rendered as HTML/CSS (crisp at any size, no images, no pre-built
  sheets needed — generated in-process).

**Validation:**

| Check | Result |
|---|---|
| Dot geometry (HTML): C5 power A@3 → dots at (40%,12.5%)+(60%,62.5%); A5 power E@0 → O on 6th str + dot (20%,37.5%); C open x32010 → dots (20,62.5)(40,37.5)(80,12.5) + X/O markers | ✅ PASS |
| **Bug found + fixed**: `is_minor("C#m7")` was False (ends with "7") → C#m7 barre rendered as MAJOR (s2 at 6th fret). Fix: strip numeric quality suffix before the `m` test. Sweep of 10 symbols (C#m7/D#maj7/Am7/Fm7/Cmaj7/Bbm7/…) all correct; C#m7 dots now (80%,37.5%) | ✅ PASS |
| Riptide grid: A5 (open) / C5 (3rd) / G5 (3rd) / F5 (1st) | ✅ PASS |
| Back in Black grid: 9 tokens incl. C#m7 (4th fret barre) | ✅ PASS |
| Old Porch grid: Fm7 / Dmaj7 / C6 / Cmaj7 (open) | ✅ PASS |
| Submission grid: F7 / D#maj7 (6th) / G#6 (4th) / Fmaj7 / A#maj7 (1st) / Cmaj7 / C7 | ✅ PASS |
| All 4 re-rendered via the MCP tool + re-published (overwrite=true) + verified publicly (sha256 match) | ✅ PASS |

**Notes:**
- Layout order is now: header → CHORDS (fingerings) → CHART (chords over
  lyrics) → TAB (fretboard reference).
- The note-event positions in `analysis.json` (per-chord `tab` string/fret)
  are the raw DSP detections — noisy/incomplete (lead notes mixed in), so
  the clean `shape` field is the right source for diagrams.

## Validation Entry — 2026-11-01 (part 7): measure-aligned SCORE layout + chord-shape correctness

**Goal (user):** the PDF should let chuck and a friend jam — see the lyrics,
the chord **shapes** (not just names) at the exact words being sung, and the
solo tab, all in one place. The chord grid at the top was good ("we need to
work on the rest").

**Changes:**

1. **SCORE section (replaces CHART + TAB)**: one measure-aligned block per
   section (7 measures/row) with three lanes:
   - **VOCALS**: words placed in the measure they start in (ASR word
     timestamps vs `bar_length = 240/bpm`, 4/4 assumed); a **mini chord
     diagram** (compact 6-string grid, 16px) floats above the measure where
     each chord change lands — the shape is visible at the exact word sung.
   - **RHYTHM**: chord diagrams per measure (instrumental sections).
   - **SOLO**: compact 6-string tab of the lead notes (string letter + fret
     digits, ≤12 chars, repeats collapsed to `×n`), measure-aligned — the
     solo's position against the singing/rhythm is visible, so a friend can
     play the SOLO lane while chuck sings.
2. **Chord-shape correctness fixes** (found by a MIDI-based note-set audit):
   - **A-shape power chords** were rendered on strings 4+3 (frets 2,3 of the
     fret array) — wrong; now on strings 5+4 (`f[1]=fret, f[2]=fret+2`).
     E-shape was already correct (strings 6+5).
   - **Open-shape library**: 15 entries spelled wrong chords — fixed:
     `C6` (had a D where the B should be → now x32333), `Gm`/`Gm7` (wrong
     2nd string), `Dsus4`, `Am7` (had a G, not a C), `Emaj7` (had a D, not
     the D#/E natural 7th), `Fmaj7`, `B7` (was actually B major, no D#/A),
     `Bmaj7`, `Bbmaj7`, `F#m`, `F#m7`, `C9`, `F9`, `F#maj7`.
   - `is_minor()` strips numeric quality suffixes (part 6) — kept.

**Validation:**

| Check | Result |
|---|---|
| MIDI note-set audit of all 46 open-shape library entries (root/3rd/7th/9th present, no banned notes) | ✅ PASS (3 remaining "missing 5th" = valid voicings) |
| All chord shapes in the 4 published tabs (power/barre/open, incl. C#m7 barre, D#maj7 barre, A#maj7 1st-fret barre) | ✅ PASS |
| A5 power: strings 5+4 (open A + 2nd-fret E) | ✅ PASS (was 4+3 — fixed) |
| SCORE: every lead-note section has a solo cell; every word present; mini tokens == chord changes (all 4 songs) | ✅ PASS |
| All 4 re-rendered via the live MCP tool (`media_render_tab_pdf`) + re-published (`overwrite=true`) + verified publicly (sha256 match) | ✅ PASS |

**Notes:**
- Layout order is now: header → CHORDS (fingerings) → SCORE (SING & PLAY).
- Measure alignment assumes 4/4 (all four songs are 4/4). Sections with no
  BPM fall back to 1 measure/row.
- The solo lane is the **lead** notes from `analysis.json` (role=lead),
  measure-aligned — it is a positional reference, not a rhythmically exact
  transcription (rhythm lives in the raw tab.md).

## Validation Entry — 2026-11-01 (part 8): word-timing sanitization + Back in Black ASR failure

**Goal (user):** Submission's words were "really cramped up on one of the
counts"; Back in Black had lyrics only in the first section and "a ton of
chorus but no lyrics" (some of which are actually verses).

**Root causes (both in the pipeline's `analysis.json`, not the renderer):**

1. **Submission — broken word timestamps.** Whisper word timestamps + the
   LLM polish step (which merges lyric lines) produced: pile-ups (8–20 words
   on one timestamp, e.g. 16 words at 97.86 s), and words spilling 12–76 s
   past their section's end. The SCORE renderer placed words by timestamp
   and clamped out-of-range words to the last measure → a wall of words in
   one measure.
2. **Back in Black — ASR failure.** The raw whisper output
   (`lyrics_raw.txt`) is 8 hallucinated lines ("Be back. Yes, I'm letting
   loose from the news…") on the distorted intro; nothing else was
   transcribed. The pipeline's own caveats flag it: "Only one section
   contains lyrics" (confidence: low). Re-ran the transcribe job with
   `stems=false` (whisper on the full mix instead of the demucs vocal
   stem, job `2c4ea2812fe8`) → **0 words** (VAD detects no speech in the
   distorted mix). The vocal-stem run (`99d8f532c3dc`) is still the best
   available. The section labels are all "chorus" because the deterministic
   segmenter had no lyric content to distinguish verse from chorus.

**Fix (renderer, deterministic):** `tab_pdf.parse_analysis_sections` now
sanitizes word timing. A line is "broken" if any of: non-monotonic
timestamps (gap < −0.05 s), a pile-up (>4 words in any 0.1 s window), an
impossible rate (<0.10 s/word across the span), or a big spill (a word >3 s
outside the section window). Mild spills (≤3 s) are left alone — they clamp
harmlessly into the last measure. If any line in a section is broken, the
whole section is re-timed: the section window is split across the lines
proportionally to word count, words placed evenly (centered) in each slice.
Order is preserved; words land inside the section; no measure gets a wall.

**Validation:**

| Check | Result |
|---|---|
| Riptide: only sections [3] (12 s spill) + [7] (7-word pile-up) re-timed; mild spills (≤1.2 s) untouched | ✅ PASS |
| Old Porch: only section [4] (10-word pile-up) re-timed | ✅ PASS |
| Submission: all 5 broken sections re-timed — max pile-up now 1 (was 8–20), all words inside section windows (was 12–76 s spills) | ✅ PASS |
| Back in Black: 8 hallucinated lines now spread across the 49 s section (was clumped; last line spilled to 79 s) | ✅ PASS |
| All 4: every word in HTML, solo cells intact, mini tokens == chord changes, all chord shapes correct | ✅ PASS |
| All 4 re-rendered via the live MCP tool + re-published (`overwrite=true`) + verified publicly (sha256 match) | ✅ PASS |

**Notes / open item:**
- Back in Black's lyrics are still the 8 ASR hallucinations — the renderer
  can't invent missing data. Options for the user: (a) re-rip a cleaner
  source and re-transcribe, (b) manually add the real lyrics (the section
  boundaries don't align cleanly with the known verse/chorus structure, so
  that's a bigger data edit), (c) leave as-is (chords + solo are fine).
- The re-run job `2c4ea2812fe8` (stems=false) is garbage (0 words) — do not
  use it; `99d8f532c3dc` remains the canonical Back in Black job.

## Validation Entry — 2026-11-01 (part 8): word-timing sanitization (cramped-lyrics fix)

**Goal (user):** Submission's lyrics were "really cramped up on one of the
counts"; Back in Black only had lyrics on the first verse then a ton of
empty "chorus" sections.

**Root causes (data, not layout):**
- Submission: the word timestamps in `analysis.json` are broken — whisper
  word-level timing + the LLM polish step (which merges lyric lines) produced
  pile-ups (8–20 words sharing one timestamp) and words spilling 12–76 s
  past their section end. The renderer clamped out-of-section words into the
  last measure → a wall of words on one count.
- Back in Black: ASR genuinely failed on the track. Raw whisper output
  (`lyrics_raw.txt`) is 8 hallucinated lines over the distorted intro; the
  pipeline flagged `confidence: low` ("Only one section contains lyrics").
  Re-ran with `stems=false` (whisper on full mix, job `2c4ea2812fe8`) →
  0 words (VAD detects nothing in the distorted mix). The old job
  `99d8f532c3dc` (vocal stem) remains canonical.

**Fix (renderer, deterministic):** `tab_pdf.parse_analysis_sections` now
sanitizes word timing. A line is "broken" if: non-monotonic (gap < −0.05 s),
pile-up (>4 words in any 0.1 s window), impossible rate (<0.10 s/word), or a
word >3 s outside the section window. Mild spills (≤3 s) are left alone —
they clamp harmlessly into the last measure. If any line in a section is
broken, the whole section is re-timed: the section window is split across
the lines proportionally to word count; words placed evenly (centered) in
each slice. Order preserved; words land inside the section; no measure gets
a wall.

**Validation:**

| Check | Result |
|---|---|
| Riptide: only [3] (12 s spill) + [7] (7-word pile-up) re-timed; mild spills (≤1.2 s) untouched | ✅ PASS |
| Old Porch: only [4] (10-word pile-up) re-timed | ✅ PASS |
| Submission: all 5 broken sections re-timed — max pile-up now 1 (was 8–20); all words inside section windows (was 12–76 s spills) | ✅ PASS |
| Back in Black: 8 lines now spread across the 49 s section (last line spilled to 79 s before) | ✅ PASS |
| All 4: every word in HTML, solo cells intact, mini tokens == chord changes, chord shapes correct | ✅ PASS |
| All 4 re-rendered via the live MCP tool + re-published (overwrite=true) + verified publicly (sha256 match) | ✅ PASS |

**Open item:** Back in Black's lyrics are still the 8 ASR hallucinations —
the renderer can't invent missing data. Options: (a) re-rip a cleaner source
and re-transcribe, (b) manually add the real lyrics (the detected section
boundaries don't align cleanly with the known verse/chorus structure, so
that's a bigger data edit), (c) leave as-is (chords + solo are fine).
