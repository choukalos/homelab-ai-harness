# Homelab Setup

Personal homelab focused on:

- Local AI / LLM experimentation
- AI agent harnesses & workflows
- Family knowledge base
- Public web applications
- CI/CD driven self-hosted services
- Privacy-first architecture

---

# Goals

This setup is designed around a few principles:

1. Keep infrastructure simple and debuggable
2. Separate config from persistent data
3. Keep AI workloads modular
4. Support rapid iteration on AI tooling/apps
5. Keep sensitive/private data local
6. Use Docker Compose instead of Kubernetes
7. Use Cloudflare Tunnel instead of router port forwarding

---

# Machines

## Thor (Ryzen Mini PC)

Primary homelab orchestration/server box.

Runs:
- Docker
- LiteLLM
- Open Web UI
- AI Harness APIs
- Ghost blog
- Invest Hub
- Qdrant
- Redis
- Caddy
- Cloudflare Tunnel
- Crawl4AI
- SearXNG
- MkDocs family wiki
- Presenton (presentation generation)
- Victoria Metrics (Prometheus-compatible metrics collection)
- Grafana (dashboards)
- Plausible (web analytics)

Also runs:
- Bare metal MySQL
- Node Exporter + cAdvisor (host/container metrics)

---

## AI Workstation

Dedicated GPU AI box.

Runs:
- Ollama
- ComfyUI
- CUDA workloads
- Large local models
- Image/video generation

Current GPU:
- RTX 5000 72GB

---

## NAS

Used for:
- Backups
- Media
- Archived source documents
- Long-term storage

Mounted via SMB/CIFS.

---

# Directory Structure

## Config / Source Controlled

```text
/home/chuck/homelab/
```

Contains:
- compose files
- configs
- scripts
- Dockerfiles
- AI harness code
- Caddy config
- MkDocs config

Safe to commit to GitHub.

---

## Persistent Data

```text
/home/chuck/data/
```

Contains:
- databases
- uploads
- embeddings
- vector stores
- knowledge base data
- application state

NOT committed to GitHub.

---

# Homelab Layout

```text
/home/chuck/homelab/
  compose/
    compose.core.yml
    compose.edge.yml
    compose.ghost.yml
    compose.ai-core.yml
    compose.mcp.yml          # MCP server containers (6 active)
    compose.skill-runner.yml # Skill orchestration API (port 8091)
    compose.invest-hub.yml
    compose.monitoring.yml
    compose.n8n.yml

  caddy/
    Caddyfile

  cloudflared/

  litellm/
    config.yml

  mkdocs/
    mkdocs.yml

  plausible/
    clickhouse/

  prometheus/
    prometheus.yml          # Victoria Metrics scrape config (Prometheus-compatible)

  mysql-exporter/
    .my.cnf

  skills/                   # Skill runner + skill implementations
    runner/                 # FastAPI orchestration API + chat gateway + scheduler
    siri_ask/               # Quick mobile Q&A
    deep_research/          # Multi-source cited research
    presentation_build/     # Presenton-powered presentations
    demo_workflow/          # Full demo pipeline
    investment_brief/       # Portfolio + market analysis
    morning_brief/          # Daily news summary
    homelab_report/         # Infrastructure health report
    family_kb_ingest/       # KB ingestion (approval gate)
    code_review/            # Code quality review
    repo_maintenance/       # Repo hygiene (approval gate)
    siri_chat/              # Enhanced chat with MCP tool access
    presentation_update/    # Update existing presentations
    demo_browse/            # Search/browse demos by keyword
    research_brief/         # Lightweight web research + summarization

  mcp/                      # MCP server implementations
    servers/                # Individual MCP server dirs
    shared/                 # Shared utilities

  scripts/

  homelab.sh

  .env
  .gitignore
  README.md
```

---

# Data Layout

```text
/home/chuck/data/
  ai-kb/
    repo/
    raw/
    processed/
    reports/
    embeddings/

  caddy/
    config/
    data/

  crawl4ai/

  ghost/

  grafana/

  litellm/
  litellm-postgres/

  n8n/

  open-webui/

  postgres/

  plausible-db/
  plausible-events-db/

  presenton/

  qdrant/

  redis/

  searxng/

  searxng-valkey/

  victoria-metrics/
```

---

# Knowledge Base Design

Family/private knowledge base is intentionally LOCAL ONLY.

The KB repo is:

```text
/home/chuck/data/ai-kb/repo
```

It is:
- Git initialized locally
- NOT pushed to GitHub
- NOT exposed publicly

Purpose:
- retain version history
- support AI-assisted edits
- allow rollback/review
- maintain privacy

---

# Networking Model

## Networks

Four Docker networks are used:

| Network | Purpose |
|---|---|
| edge-net | Public ingress |
| public-net | Public apps |
| ai-net | AI/private services |
| monitoring-net | Monitoring infra (bridges to public-net for scraping) |

---

# Public Exposure Model

Internet exposure uses:

```text
Internet
  -> Cloudflare
  -> Cloudflare Tunnel
  -> Caddy
  -> Internal services
```

No direct router port forwarding required.

Use API Keys for publically exposing API services along with appropriate request headers.

Generate strong keys via:
openssl rand -hex 32

Request headers via:
X-API-Key: your-secret-key


---

# Reverse Proxy

## Caddy

Caddy acts as:
- internal reverse proxy
- hostname router
- future auth integration point
- internal TLS layer

Config:

```
/home/chuck/homelab/caddy/Caddyfile
```

### Routed Hostnames

| Hostname | Service | Auth |
|---|---|---|
| `choukalos.com` | Ghost blog | None |
| `invest.choukalos.com` | Invest Hub (client + API) | None |
| `api.choukalos.com` | Invest Hub backend API | None |
| `siri.choukalos.com` | AI Harness Siri API | `X-API-Key` |
| `llm.choukalos.com` | LiteLLM proxy | `X-API-Key` |
| `plausible.choukalos.com` | Plausible script + API only (admin blocked from internet) | None (script/API); admin via LAN only at `192.168.4.54:8082` |

Grafana is LAN-only (port 3001, SSH tunnel only).

---

# Cloudflare Tunnel Setup

## 1. Create Tunnel

In Cloudflare Dashboard:

```text
Zero Trust
  -> Networks
  -> Tunnels
```

Create a tunnel.

---

## 2. Configure Public Hostnames

Point hostnames to:

```text
Service Type: HTTP
URL: caddy:80
```

Examples:

```text
blog.yourdomain.com
invest.yourdomain.com
ai.yourdomain.com
siri.yourdomain.com
```

---

## 3. Update `.env`

Add:

```bash
CF_TUNNEL_TOKEN=
DOMAIN_NAME=
```

---

## 4. Secure Sensitive Apps

Use:

```text
Cloudflare Zero Trust
  -> Access
  -> Applications
```

Add:
- Google login
- GitHub login
- One-time PIN
- service token auth

Recommended for:
- Open Web UI
- AI APIs
- admin dashboards

---

# AI Architecture

## LiteLLM

LiteLLM acts as:
- model gateway
- OpenAI-compatible endpoint
- model router
- MCP gateway (routes tool calls to standalone MCP server containers)

Clients talk to LiteLLM instead of directly to Ollama.

---

## MCP Servers

MCP (Model Context Protocol) servers are **standalone containers**, each with its own isolated Python environment. They run on the `ai-net` Docker network and communicate with the Skill Runner (and LiteLLM) over **streamable HTTP** transport.

**Eight MCP servers are currently deployed** via `compose.mcp.yml` (29 tools total).

| Server | Backend | Status | Deployed |
|---|---|---|---|
| `mcp_search` | SearXNG | ✅ Implemented | ✅ Container on `ai-net` |
| `mcp_knowledge` | Qdrant | ✅ Implemented | ✅ Container on `ai-net` |
| `mcp_crawl` | Crawl4AI | ✅ Implemented | ✅ Container on `ai-net` |
| `mcp_filesystem_readonly` | Local filesystem | ✅ Implemented | ✅ Container on `ai-net` |
| `mcp_mysql` | MySQL (InvestorHub) | ✅ Implemented | ✅ Container on `ai-net` |
| `mcp_homelab_status` | Docker API + Victoria Metrics | ✅ Implemented | ✅ Container on `ai-net` |
| `mcp_filesystem` | Read/write `/home/chuck/workspace` | ✅ Implemented | ✅ Container on `ai-net` |
| `mcp_media` | Media generation via GPU-host media-pipeline | ✅ Implemented | ✅ Container on `ai-net` |
| `mcp_stocks` | External APIs | 📋 Planned (README stub) | 🔲 Not yet |
| `mcp_home` | Homebridge (Lego) | 📋 Planned (README stub) | 🔲 Not yet |

**Architecture:**
```
Skill Runner (:8091)  →  Streamable HTTP  →  mcp_search container
                                           mcp_knowledge container
                                           mcp_crawl container
                                           mcp_filesystem_readonly container
                                           mcp_mysql container
                                           mcp_homelab_status container
                                           mcp_filesystem container
                                           mcp_media container

LiteLLM (:4000)       →  Streamable HTTP  →  same MCP servers (for tool routing)
```

The Skill Runner is the **primary gateway** for MCP tool calls in skill workflows.
LiteLLM also proxies MCP calls for tool routing via `/mcp-rest/tools/call`.

Each server has its own directory under `mcp/servers/<name>/` with:
- `server.py` — FastMCP server implementation
- `Dockerfile` — Self-contained Python environment
- `pyproject.toml` — Dependencies
- `README.md` — Tool documentation
- `tests/` — Unit tests

**Why standalone containers:**
- Isolated dependencies — no Franken-venv in LiteLLM
- Independent lifecycle — add/remove/restart without touching LiteLLM
- Portable — deploy to any client's infra
- Scalable — can run on Thor, Matrix, or external hosts

---

## Skill Runner

Custom FastAPI-based AI orchestration layer. Runs on port 8091 via `compose.skill-runner.yml`.

Provides the **chat gateway** (unified Siri/API interface) and the **job lifecycle API**:
```
POST /api/chat                        — Unified chat with intent detection
GET  /api/jobs/{job_id}               — Poll async job status
POST /api/schedule                    — Create a recurring schedule
GET  /api/schedule                    — List all schedules
DELETE /api/schedule/{id}             — Remove a schedule
POST /api/schedule/{id}/run-now       — Trigger a schedule immediately
```

**Job lifecycle API** (direct skill invocation):
```
POST /skills/{skill_name}             — Launch a skill job
GET  /skills/jobs/{job_id}            — Get job status
GET  /skills/jobs/{job_id}/artifact   — Retrieve artifact file
POST /skills/jobs/{job_id}/approve    — Approve a job at an approval gate
POST /skills/jobs/{job_id}/cancel     — Cancel a job
```

Skills compose MCP tools into controlled agentic workflows. The skill runner calls MCP servers **directly** over streamable HTTP on the Docker network (no LiteLLM proxy for tool calls).

**Built-in scheduler:** A background thread (`scheduler.py`) checks a JSON config file every 60 seconds and dispatches matching scheduled jobs.

### Skills Inventory

| Skill | Tools Used | Approval Gate | Channels | Description |
|---|---|---|---|---|
| `siri_ask` | model_chat | No | Siri | Quick mobile Q&A, safe status lookups (30s timeout) |
| `deep_research` | mcp_search, mcp_knowledge, mcp_crawl | No | Siri, CLI, Pi | Multi-source cited markdown reports |
| `presentation_build` | model_chat + Presenton API | No | Siri, CLI, Pi | Slide deck generation via Presenton |
| `demo_workflow` | model_chat | No | CLI, Pi, n8n | Full 8-phase demo pipeline (research→build→verify) |
| `investment_brief` | mcp_mysql, mcp_search | No | CLI, Pi, n8n | Portfolio status, dividend highlights, market news |
| `morning_brief` | mcp_search | No | CLI, Pi, n8n | Daily news summary across interest topics |
| `homelab_report` | mcp_homelab_status | No | CLI, Pi, n8n | Infrastructure health report (containers, system) |
| `family_kb_ingest` | — | **Yes** | CLI, Pi, n8n | Curated KB ingestion into Qdrant |
| `code_review` | — | No | CLI, Pi, n8n | Code quality review |
| `repo_maintenance` | — | **Yes** | CLI, Pi, n8n | Repository health, cleanup |
| `siri_chat` | mcp_search, mcp_knowledge, mcp_homelab_status | No | Siri | Enhanced chat with MCP tool access |
| `presentation_update` | model_chat + Presenton API | No | Siri | Update existing presentations (tone, content, etc.) |
| `demo_browse` | Local filesystem | No | Siri | Search/browse demos by keyword in `/home/chuck/data/media/demos/` |
| `research_brief` | mcp_search | No | Siri | Lightweight web research with summarization (faster than deep_research) |
| `list-demos` | Local filesystem | No | Siri, CLI | List all demos with accessible URLs |
| `list-presentations` | Presenton API | No | Siri, CLI | List presentations with view/edit URLs |
| `list-images` | Local filesystem | No | Siri, CLI | List generated images with accessible URLs |

Skills with **approval gates** (`family_kb_ingest`, `repo_maintenance`) pause at `awaiting_approval` until explicitly approved via the API.

---

## Open Web UI

Primary family/local AI chat interface.

Connected to LiteLLM.

---

## AI Services

| Service | Purpose | Status |
|---|---|---|
| LiteLLM | Model gateway + MCP gateway | ✅ Running |
| MCP servers | Reusable tool providers (standalone containers) | ✅ 8 deployed (29 tools) |
| Skill runner | Agentic workflow orchestration + chat gateway + scheduler | ✅ Running (:8091) |
| AI Harness (legacy) | Siri/CarPlay gateway, Celery workers | ⏳ Decommission pending |
| Open Web UI | Family/local AI chat interface | ✅ Running |
| Qdrant | Vector DB for knowledge base | ✅ Running |
| SearXNG | Privacy-first web search | ✅ Running |
| Crawl4AI | Web page extraction | ✅ Running |
| Redis | Queues/cache (Celery broker) | ✅ Running |
| MkDocs | Family wiki | ✅ Running |
| Presenton | Presentation generation | ✅ Running |
| Victoria Metrics | Prometheus-compatible metrics | ✅ Running |
| Grafana | Dashboard visualization | ✅ Running (LAN) |
| Plausible | Privacy-first web analytics | ✅ Running |

---

# Siri / Mobile Access

Two pathways coexist:

**1. Skill Runner (current public path):**
```
iPhone Shortcut  →  Cloudflare Tunnel  →  Caddy  →  Skill Runner (:8091)  →  MCP servers / LiteLLM
```
Endpoint: `POST https://siri.choukalos.com/api/chat`
Auth: `X-API-Key` header (`SIRI_API_KEY` from `.env`)

Intent routing in `_detect_intent()` auto-detects from the user's `text`:
- **chat** — General Q&A via `siri_chat` skill
- **deep-research** — Multi-source deep research (~180s)
- **research-brief** — Lightweight web research (~30-60s)
- **build-presentation** — Create a new presentation deck
- **update-presentation** — Update an existing presentation (tone, content)
- **find-demos** / **list-demos** — Browse/search demos
- **list-presentations** — List existing presentations
- **list-images** — List generated images with accessible URLs
- **media-generate** — Generate an image via `mcp_media.media_generate_image` (GPU-host media-pipeline) + `media_fetch`

### Media Generation (Image)

The `media-generate` intent dispatches directly to the `mcp_media` MCP server
(GPU-host media-pipeline on Matrix) without spawning a background skill job.
It calls `media_generate_image` (blocks until the GPU job finishes, ~30–60 sec
plus any queue wait), then `media_fetch` to download the result to
`/home/chuck/data/media/generated/pipeline/` and serves it via the media URL.

**Keywords that trigger it:** `generate image`, `create image`, `make image`,
`create media`, `media generate`, `generate media`, `image generate`

**Example:**
```bash
curl -s -X POST https://siri.choukalos.com/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $SIRI_API_KEY" \
  -d '{"text": "generate image of a geometric abstract logo"}'
```

**Response:**
```json
{
  "speak": "I've generated an image. View it at https://siri.choukalos.com/media/files/generated/pipeline/mp_a1b2c3d4e5f6_00001_.png",
  "display": "Image generated from prompt: generate image of a geometric abstract logo",
  "job_id": "abc123",
  "media": "/home/chuck/data/media/generated/pipeline/mp_a1b2c3d4e5f6_00001_.png",
  "data": {
    "skill": "mcp_media",
    "intent": "media-generate",
    "image_url": "https://siri.choukalos.com/media/files/generated/pipeline/mp_a1b2c3d4e5f6_00001_.png"
  }
}
```

**Generated images** are saved to `/home/chuck/data/media/generated/pipeline/` as PNG files (named `mp_{job_id}_{seq}.png`).
The response includes accessible URLs — `image_url` is a public URL that can be
viewed directly in a browser or embedded in markdown.

Requires the `mcp_media` container to be running on `ai-net`.
Prerequisite: the media-pipeline must be running on the AI Workstation (Matrix, port 8189).

### Media URL Structure

All generated assets are served through a single route proxied by Caddy:

| Path | Local directory | Accessible URL (public) | Accessible URL (LAN) |
|---|---|---|---|
| `/media/files/*` | `/home/chuck/data/media/*` | `https://siri.choukalos.com/media/files/generated/img.png` | `http://192.168.4.54:8091/media/files/generated/img.png` |

Subdirectories:
- **`generated/`** — images from `media-generate` (GPU-host media-pipeline; under `generated/pipeline/`)
- **`demos/`** — demo HTML files from `demo_workflow` / `demo_browse`
- **`images/`** — static images
- **`presentations/`** — PPTX exports (downloadable, not the Presenton web portal)

### Listing Intents

Three listing intents scan local files/Presenton and return accessible URLs:

| Intent | Source | What it lists |
|---|---|---|
| `list-images` | `/media/generated/`, `/media/images/` | Generated images with view URLs |
| `list-demos` | `/media/demos/` | Demo HTML files with view URLs |
| `list-presentations` | Presenton API (`/api/v1/ppt/presentation/all`) | Presentations with view/edit URLs |

All listing intents dispatch asynchronously. The CLI polls for results.

**CLI usage:**
```bash
# List all generated images
./cli/run-skill.sh list-images

# Filter by keyword
./cli/run-skill.sh list-images sunset

# List demos (all or by keyword)
./cli/run-skill.sh list-demos
./cli/run-skill.sh list-demos taskflow

# List presentations
./cli/run-skill.sh list-presentations

# Use public endpoint (--public proxies through siri.choukalos.com)
./cli/run-skill.sh --public list-images
```

Presentations use a separate web portal: `https://siri.choukalos.com/presentations/{id}` → Presenton

### Listing Images

The `list-images` intent scans `/media/generated/` and `/media/images/` and
returns each image with accessible URLs:

```bash
./cli/run-skill.sh list-images                    # list all images
./cli/run-skill.sh list-images "sunset"           # filter by keyword
./cli/run-skill.sh --public list-images "rose"    # public endpoint
```

**Response** includes per-image `view_url` (public) and `view_url_lan` (LAN):
```json
{
  "speak": "I found 15 images.",
  "display": "Found 15 images:\n- a sunset (2.0MB, generated, 2026-07-08T10:30:00+00:00)\n...",
  "data": {
    "count": 15,
    "images": [
      {
        "name": "a sunset",
        "filename": "gen_a sunset.png",
        "directory": "generated",
        "size_human": "2.0MB",
        "view_url": "https://siri.choukalos.com/media/files/generated/gen_a sunset.png",
        "view_url_lan": "http://192.168.4.54:8091/media/files/generated/gen_a sunset.png"
      }
    ]
  }
}
```

**2. Siri/Mobile Access (Skill Runner):**
```
iPhone Shortcut  →  Cloudflare Tunnel  →  Caddy  →  Skill Runner (:8091)  →  LiteLLM / MCP
```

The legacy AI Harness (`ai-harness/`) has been **decommissioned** (replaced by Skill Runner).
Source code archived as `ai-harness-decommissioned/`.

See [README_SIRI.md](README_SIRI.md) for full Siri API reference and Shortcut configuration.

---

# Compose File Structure

## compose.core.yml

Shared infrastructure:
- Caddy
- Docker networks

---

## compose.edge.yml

Public ingress:
- Cloudflare Tunnel

---

## compose.ghost.yml

Stable public blog stack.

Rarely changes.

---

## compose.ai-core.yml

AI infrastructure (separate Docker Compose project `ai-core`):
- LiteLLM
- Open Web UI
- Qdrant
- Redis
- SearXNG
- Crawl4AI
- MkDocs family wiki

Rarely changes. Services communicate via the shared `ai-net` network.

---

## compose.mcp.yml

MCP server containers (separate Docker Compose project `ai-mcp`):
- `mcp_search` — Web search via SearXNG
- `mcp_knowledge` — KB retrieval via Qdrant
- `mcp_crawl` — Web page extraction via Crawl4AI
- `mcp_filesystem_readonly` — Read-only filesystem access
- `mcp_mysql` — Database queries via MySQL (InvestorHub): read-only SELECTs, NL-to-SQL with full schema intelligence (join graph, curated domain hints, data samples)
- `mcp_homelab_status` — Infrastructure health (Docker API + Victoria Metrics)
- `mcp_filesystem` — Read/write filesystem access (scoped to `/home/chuck/workspace`)
- `mcp_media` — Media generation via the GPU-host media-pipeline on Matrix (storyboard, image gen/edit, I2V shots, TTS, music, SFX, upscale, assemble, fetch)

All run on `ai-net`. Accessed by the skill runner over streamable HTTP.

---

## compose.skill-runner.yml

Skill orchestration API (separate Docker Compose project `ai-skill-runner`):
- FastAPI server on port 8091
- Skills directory mounted read-only (live edits without rebuild)
- Artifacts written to `/home/chuck/data/media/`
- Logs written to `/home/chuck/homelab/logs/skill_runner/`

Talks to LiteLLM for LLM generation and MCP servers directly for tool calls.

---

## compose.invest-hub.yml

Investment tooling stack.

### Architecture

```
Browser (invest.choukalos.com)
  -> Caddy (route /api/* -> invest-hub-server:4000)
  -> Caddy (route /*    -> invest-hub-client:80)
```

All requests stay same-origin on `invest.choukalos.com` — no CORS issues.
Caddy proxies `/api/*` directly to the backend; everything else goes to the
React client.

### Key notes

- **Server** (`invest-hub-server`): Node/Express + Prisma + MySQL on Thor
- **Client** (`invest-hub-client`): React/Vite served via nginx, `VITE_API_BASE_URL=/api` (relative)
- **MySQL** accessed via `extra_hosts: "thor.local:192.168.4.54"` (see MySQL section)
- **Prisma client** is regenerated in the entrypoint (`npx prisma generate`) before DB operations
- **Cron job**: runs `updateAllActiveSymbols()` at 1 AM Mon–Sat
- **Docker image** pins Prisma to v6 (not v7) to avoid `url` config deprecation

CI/CD driven.  
Frequently iterated.

---

## compose.monitoring.yml

Monitoring infrastructure:
- Node Exporter (host-level metrics)
- cAdvisor (container-level metrics)
- Victoria Metrics (Prometheus-compatible metrics collection, scrapes local + remote hosts)
- Grafana (dashboard visualization, LAN-only via port 3001)
- Plausible + Postgres + ClickHouse (web analytics)
- MySQL Exporter (bare-metal MySQL monitoring)

Shares `public-net` with apps so Victoria Metrics can scrape `/metrics` endpoints.
Admin UI for Plausible is LAN-only at `192.168.4.54:8082`.

---

## compose.n8n.yml

Optional workflow experimentation.

Kept separate intentionally.

---

# Running Services

Primary control script:

```bash
/home/chuck/homelab/homelab.sh
```

Examples:

```bash
# Bring up the full AI stack (core + MCP servers + skill runner) or take it down
./homelab.sh up ai
./homelab.sh down ai

# Rebuild only core AI services
./homelab.sh rebuild ai-only

# Manage MCP servers independently
./homelab.sh up mcp-only
./homelab.sh rebuild mcp-only

# Manage skill runner independently
./homelab.sh up skill-only
./homelab.sh rebuild skill-only

# Manage monitoring stack
./homelab.sh up monitoring
./homelab.sh restart monitoring

# Manage other stacks
./homelab.sh restart invest
./homelab.sh up public
./homelab.sh logs ai -f
./homelab.sh ps all

# Manage all stacks at once
./homelab.sh up all         # everything except n8n
./homelab.sh up all-n8n     # everything including n8n

# LiteLLM key management
./homelab.sh key list
./homelab.sh key info <user>
./homelab.sh key add <user> [--budget 10]
```

**Important:** The `ai` stack comprises **three** separate Docker Compose projects:
`ai-core` (litellm, open-webui, qdrant, redis, searxng, etc.), `ai-mcp` (MCP servers),
and `ai-skill-runner` (skill runner). Rebuilding `mcp-only` or `skill-only` will **not**
restart litellm or other ai-core services — your LLM connection stays alive.

---

# CI/CD Philosophy

## Stable Infrastructure

Manually managed:
- Caddy
- Cloudflare Tunnel
- Ghost
- databases
- Redis
- Qdrant

---

## Fast-Changing Apps

GitHub Actions:
- build images
- push to GHCR
- deploy via Docker Compose pull/restart

Examples:
- Invest Hub
- AI Harness

---

# MySQL

MySQL runs bare metal on Thor.

Containers access MySQL via:

```text
thor.local:3306
```

Compose files that need MySQL add both host entries:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
  - "thor.local:192.168.4.54"
```

Using `thor.local` (resolved via `extra_hosts`) is preferred over
`host.docker.internal` because it gives a stable hostname that works
consistently across Alpine-based containers (e.g. invest-hub-server).

The `DATABASE_URL` is set in `.env` with the resolved host:

```bash
DATABASE_URL=mysql://investor:***@thor.local:3306/investorhub
```

---

# Security Philosophy

## Public Exposure

Only expose:
- Ghost
- Siri endpoint
- Invest Hub
- specific AI APIs if needed

Never expose:
- Redis
- Qdrant
- internal dashboards
- admin APIs
- raw Ollama endpoints

---

## Secrets

Secrets stored in:

```text
/home/chuck/homelab/.env
```

Never committed to GitHub.

---

# Backups

Critical backups:
- MySQL
- ai-kb repo
- Ghost content
- Open Web UI DB
- Qdrant data
- LiteLLM Postgres
- Plausible DB + ClickHouse
- Victoria Metrics data
- Grafana dashboards + configs

Long-term backups stored on NAS.

---

# Future Expansion

Potential future additions:
- Home automation MCP server (read-only)
- Code MCP server (repo listing, git operations)
- More skill implementations (investment_brief, code_review, morning_brief, etc.)
- MCP server containerization (all remaining servers)
- CI/CD for MCP servers and skills
- Remote client deployment patterns

---

# Philosophy

This homelab intentionally avoids:
- Kubernetes
- over-engineering
- excessive cloud dependencies

Goals:
- understandable
- reproducible
- hackable
- privacy-first
- AI-native
- easy to debug


