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
    compose.ai-harness.yml
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

MCP (Model Context Protocol) servers are **standalone containers**, each with its own isolated Python environment. They run on the `ai-net` Docker network and communicate with LiteLLM over HTTP (SSE transport).

**Each MCP server is independently deployable and portable.**

| Server | Backend | Status |
|---|---|---|
| `mcp_search` | SearXNG | ✅ Containerized, live in LiteLLM |
| `mcp_knowledge` | Qdrant | 🚧 In LiteLLM (stdio), containerize next |
| `mcp_crawl` | Crawl4AI | 🔲 Not implemented |
| `mcp_filesystem_readonly` | Local filesystem | 🔲 Not implemented |
| `mcp_stocks` | External APIs | 🔲 Not implemented |
| `mcp_homelab_status` | Docker + Victoria Metrics | 🔲 Not implemented |
| `mcp_media` | ComfyUI (Matrix) | 🔲 Not implemented |
| `mcp_home` | Homebridge (Lego) | 🔲 Not implemented |

**Architecture:**
```
LiteLLM (:4000)  →  HTTP/SSE  →  mcp_search container
                                mcp_knowledge container
                                ...
```

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

Custom FastAPI-based AI orchestration layer (replaces old AI Harness).

Runs on dev port 8091. Provides job lifecycle API:
```
POST /skills/{skill_name}
GET  /skills/jobs/{job_id}
GET  /skills/jobs/{job_id}/artifact
```

Skills compose MCP tools into controlled agentic workflows. The skill runner calls MCP servers directly over the Docker network.

---

## Open Web UI

Primary family/local AI chat interface.

Connected to LiteLLM.

---

## Planned AI Services

| Service | Purpose |
|---|---|
| LiteLLM | Model gateway + MCP gateway |
| MCP servers | Reusable tool providers (standalone containers) |
| Skill runner | Agentic workflow orchestration |
| Open Web UI | Chat UI |
| Qdrant | Vector DB |
| SearXNG | Web search |
| Crawl4AI | Web extraction |
| Redis | Queues/cache |
| MkDocs | Family wiki |
| Presenton | Presentation generation |
| Victoria Metrics | Metrics backend |
| Grafana | Dashboards |
| Plausible | Privacy-first web analytics |

---

# Siri / Mobile Access

Planned architecture:

```text
iPhone Shortcut
  -> Cloudflare Tunnel
  -> Caddy
  -> AI Harness API
  -> LiteLLM
```

Only narrow APIs should be publicly exposed.

Example:

```text
https://siri.yourdomain.com/shortcut/ask
```

Avoid exposing internal tooling publicly.

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

Rarely changes. Services communicate with the harness via the shared `ai-net` network.

---

## compose.ai-harness.yml

AI harness (separate Docker Compose project `ai-harness`):
- FastAPI harness
- Celery workers
- Celery beat scheduler
- Knowledge base watcher

Frequently iterated. Rebuilding this project does **not** restart litellm or other ai-core services, so LLM connections stay alive during development.

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
# Bring up the full AI stack (core + harness) or take it down
./homelab.sh up ai
./homelab.sh down ai

# Rebuild only the harness — litellm and other core services stay alive
./homelab.sh rebuild harness-only

# Rebuild only core AI services (no harness rebuild)
./homelab.sh rebuild ai-only

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

**Important:** `ai-core` and `ai-harness` are separate Docker Compose projects.
`rebuild harness-only` will **not** restart litellm, open-webui, qdrant, or redis —
so your LLM connection stays intact during harness development.

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


