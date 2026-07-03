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
| macstudio | 192.168.4.56 | LM Studio | 1234 |
| host.docker.internal | — | MySQL (Ghost) | 3306 |
