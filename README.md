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

Also runs:
- Bare metal MySQL

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
    compose.ai.yml
    compose.invest-hub.yml
    compose.n8n.yml

  caddy/
    Caddyfile

  cloudflared/

  litellm/
    config.yml

  mkdocs/
    mkdocs.yml

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

  litellm/

  n8n/

  open-webui/

  postgres/

  qdrant/

  redis/

  searxng/

  searxng-valkey/
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

Three Docker networks are used:

| Network | Purpose |
|---|---|
| edge-net | Public ingress |
| public-net | Public apps |
| ai-net | AI/private services |

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

```text
/home/chuck/homelab/caddy/Caddyfile
```

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

Clients talk to LiteLLM instead of directly to Ollama.

---

## Open Web UI

Primary family/local AI chat interface.

Connected to LiteLLM.

---

## AI Harness

Custom FastAPI-based AI orchestration layer.

Purpose:
- web search
- crawling
- knowledge base
- workflows
- agents
- Siri shortcut APIs
- visual document generation (HTML + PDF with layout templates, styled tables, and AI-generated images)

### Visual Document Pipeline

The harness can produce polished HTML documents and PDFs by combining:
- **Layout engine** — 10+ templates (magazine, split, grid, pitch, etc.), zone-based content
- **Image generation** — inline AI image generation via ComfyUI, placed directly into layout zones
- **Styled tables** — fully themed HTML tables with configurable colors, striping, hover
- **PDF export** — WeasyPrint converts layouts to PDFs with configurable page sizes and margins
- **One-shot build** — `/layout/build` orchestrates the entire pipeline (create, generate images, populate, render, export) in a single call

Docs: `ai-harness/layout/README.md`

---

## Planned AI Services

| Service | Purpose |
|---|---|
| LiteLLM | Model gateway |
| Open Web UI | Chat UI |
| Qdrant | Vector DB |
| SearXNG | Web search |
| Crawl4AI | Web extraction |
| Redis | Queues/cache |
| MkDocs | Family wiki |
| Harness API | Agent orchestration |

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

## compose.ai.yml

AI infrastructure:
- LiteLLM
- Open Web UI
- Qdrant
- Redis
- SearXNG
- Crawl4AI
- AI Harness

Frequently iterated.

---

## compose.invest-hub.yml

Investment tooling stack.

CI/CD driven.

Frequently iterated.

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
./homelab.sh up ai
./homelab.sh down ai

./homelab.sh restart invest

./homelab.sh up public

./homelab.sh logs ai -f
```

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
host.docker.internal
```

Compose files use:

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
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

Long-term backups stored on NAS.

---

# Future Expansion

Potential future additions:
- Home Assistant integration
- Voice assistant pipeline
- MCP servers
- LangGraph workflows
- Local code agents
- Local iOS APIs
- Family task automation
- Automated investment research
- Personal RAG systems
- Shared family AI assistant

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


