# Homelab Vision

> Purpose: Define the long-term direction for the homelab so Qwen can build incrementally without turning the system into a fragile portal-shaped monolith or breaking the working LiteLLM/Qwen stack.

## North Star

The homelab is a privacy-first, AI-native family and power-user platform.

It should support:

- Local AI and LLM experimentation
- Agentic coding and research workflows
- Family knowledge and household services
- Public web apps and selected remote access
- Safe use by Chuck, son, wife, and daughter
- Incremental evolution without unnecessary downtime

The goal is not to create one giant app. The goal is to expose shared capabilities through multiple channels.

## Core Principle

```text
Capabilities live in the platform.
Channels expose capabilities.
```

No single channel owns the platform.

The portal is a channel.
Open WebUI is a channel.
Siri is a channel.
PI.dev is a channel.
Claude Code is a channel.
IDEs are channels.
CLI and scheduled automation are channels.

The reusable platform is:

```text
LiteLLM           — model gateway + MCP gateway
MCP servers       — standalone containers, each with isolated deps
Skill runner      — agentic workflow orchestration
Knowledge stores  — Qdrant (vector), Redis (cache)
Workflow services — SearXNG, Crawl4AI, Presenton
Model aliases     — local/* naming, per-key restrictions
Access policies   — per-key MCP server/tool permissions
Observability     — Victoria Metrics, Grafana
```

### MCP Architecture

MCP servers are **standalone containers**, each independently deployable.

```text
LiteLLM (:4000)  →  HTTP/SSE  →  mcp_search container
                                mcp_knowledge container
                                ...
```

Each server:
- Runs in its own container with its own Python venv
- Communicates with LiteLLM over HTTP (SSE transport)
- Lives on the `ai-net` Docker network
- Has its own `Dockerfile`, `server.py`, `pyproject.toml`, `tests/`
- Is independently deployable to any client's infrastructure

**Why standalone:** Avoids turning LiteLLM into a dependency dumping ground.
Each server owns its dependencies, lifecycle, and scaling.
This is the portable unit of the platform.

## Machine Responsibilities

### Thor

Thor is the AI platform and orchestration host.

Thor owns:

- LiteLLM
- Open WebUI
- AI Harness rebuild / skill runner
- MCP servers
- Skills and workflows
- Qdrant
- Redis
- SearXNG
- Crawl4AI
- Presenton integration
- Caddy
- Cloudflare Tunnel
- Monitoring and dashboards
- Public and private API routing
- Access policy and key management

Thor should not run large GPU workloads.

### Matrix

Matrix is the AI compute appliance.

Matrix owns:

- vLLM inference
- Large local model storage and serving
- Embeddings if required by architecture
- ComfyUI and image/video generation
- GPU metrics
- Model profiles and launch scripts
- Runtime mode switching

Matrix should not own:

- Public routing
- Family apps
- AI orchestration
- MCP gateway policy
- Skill runner
- User-facing portal
- Reverse proxy
- Vector DB unless a deliberate exception is approved

### Lego

Lego is durable family storage and always-on household services.

Lego owns:

- NAS storage
- Multimedia library
- Family shared folders
- Historical home folders
- Homebridge
- Plex
- Backups
- Long-term artifact storage if appropriate
- Portal hosting if stable as an always-on container

Lego should remain boring, stable, and always on.

## Channels

### Homepage / Family Portal

Purpose:

- LAN-only family landing page
- Service discovery
- Simple summary/status tiles
- Links to household services
- Friendly entry point for non-technical users

Hosting preference:

- Run as a container on Lego
- Bind to port 80
- LAN only
- No login required initially

The portal should not own AI capabilities. It should link to services or display summarized status pulled from services.

### Open WebUI

Purpose:

- Family and power-user chat
- Model presets
- Family KB assistant
- Selected safe AI workflows

Open WebUI is useful, but it is not the main integration runtime.

### Siri / iOS Shortcuts

Purpose:

- Public/mobile entry point for short actions
- Skill launch
- Skill status
- Artifact retrieval
- Short KB lookups
- Status checks

Preferred public skill facade:

```text
siri.choukalos.com
```

Siri should expose narrow endpoints, not broad infrastructure.

### LiteLLM Remote Access

Purpose:

- Remote model access for Chuck and son
- Direct OpenAI-compatible access when traveling or away at college
- LAN access preferred when home

Public endpoint:

```text
llm.choukalos.com
```

Security expectations:

- Separate scoped keys per user/system
- No admin APIs exposed
- Monitor usage
- Rate-limit where practical
- Prefer LAN endpoint when on home network

### PI.dev

Purpose:

- Coding agent channel
- Skill-aware development workflows
- Power-user experimentation

PI.dev should consume the shared LiteLLM aliases, MCP tools, and skills rather than becoming a separate backend architecture.

### Claude Code

Purpose:

- Coding workflow for son and Chuck
- Repo-level coding assistance

Claude Code should use the same scoped model aliases and approved MCP/tooling patterns.

### IDE Tools

Purpose:

- Continue, Aider, OpenCode, and editor-native coding workflows

Rule:

- IDEs should use LiteLLM aliases, not Matrix ports.

### CLI and n8n

Purpose:

- Admin operations
- Scheduled automation
- Recurring summaries
- Power-user workflows

These channels should call skills or safe APIs, not raw infrastructure unless explicitly admin-only.

## Public Exposure Model

Currently public:

- Ghost blog
- Invest Hub
- Invest Hub API
- Siri API
- LiteLLM proxy

Public services are behind Cloudflare.

### Public Access Tiers

#### Tier 0 - LAN Only

Never public:

- Matrix vLLM ports
- Matrix Ollama ports
- Qdrant
- Redis
- MySQL
- Docker API
- Raw MCP servers
- Raw admin dashboards
- Grafana admin
- Homebridge admin unless explicitly protected

#### Tier 1 - Remote Private

Protected by Cloudflare Access, VPN, Tailscale, Authentik, or equivalent if exposed:

- Open WebUI
- Portal, if ever exposed beyond LAN
- Admin dashboards
- Selected internal apps

#### Tier 2 - Public Narrow API

Protected by API keys and ideally additional Cloudflare controls:

- Siri ask endpoint
- Skill launch endpoint
- Skill status endpoint
- Skill artifact endpoint

#### Tier 3 - Public Apps

Deliberately public:

- Ghost
- Invest Hub
- Selected future public demos or portfolio apps

#### Special Case - LiteLLM

`llm.choukalos.com` is intentionally public for Chuck and son remote model access.

Rules:

- Use scoped keys
- Separate keys by user/system
- No LiteLLM admin routes
- Monitor usage
- Rotate keys if leaked
- Use LAN endpoint when at home

## Users and Access Classes

| User | Role | Access intent |
|---|---|---|
| Chuck | Admin / power user | Full platform, admin, coding, research, investing |
| Son | Power user | LiteLLM, coding tools, allowed repos only |
| Wife | User | Portal, family chat, family KB, media/docs |
| Daughter | User | Family-safe portal/chat only |

Portal access is LAN-only and unauthenticated initially.

Access control matters for:

- LiteLLM keys
- Open WebUI profiles
- Skills
- Public endpoints
- Repo access
- Admin dashboards

## Model Access Strategy

Clients should not reference Matrix ports directly.

Clients should use LiteLLM aliases such as:

- `local/qwen-coder`
- `local/qwen-long`
- `local/qwen-family`
- `local/qwen-siri`
- `local/gemma-tools`
- `local/experiment`
- `local/embed`

A dedicated model alias registry should define:

- Alias
- Backend model
- Matrix profile
- Context size
- Tool bundle
- Allowed channels
- Intended users
- Public/LAN access

## AI Harness Rebuild Strategy

The existing AI Harness is not the long-term foundation.

Use Option C:

```text
Build a new skill runner beside the current AI Harness.
Port useful capabilities one by one.
Validate locally.
Expose selected endpoints after manual review.
Retire or archive the old Harness only after parity is proven.
```

Principles:

- Do not replace the current Harness in place
- Do not break existing Siri or public routes
- Do not restart production services during draft phases
- Do not bind new services to production ports until manually approved
- Keep skill artifacts outside the KB unless manually promoted

## Skills

Skills are controlled agentic workflows. They compose MCP tools and LLM calls into repeatable processes.

```
Skill runner  →  calls MCP servers directly (ai-net)
                →  calls LiteLLM for LLM generation
                →  writes artifacts to /home/chuck/data/media/
```

**Skills vs MCP:** MCP servers provide atomic tools (search, kb lookup, crawl). Skills orchestrate multiple tools into a workflow (e.g. deep_research = search → crawl → kb_lookup → LLM synthesis → artifact).

**Who calls skills:**
- Clients via the skill runner API (`POST /skills/{name}`)
- n8n for scheduled automation
- Siri/iOS shortcuts for remote mobile access

Use skills when the task:

- Has multiple steps
- Runs for more than a quick chat response
- Produces artifacts
- Needs repeatability
- Needs logging
- Needs approval gates
- Should be exposed through Siri or automation

Recommended skills:

- `siri_ask`
- `deep_research`
- `investment_brief`
- `presentation_build`
- `code_review`
- `repo_maintenance`
- `family_kb_ingest`
- `morning_brief`
- `homelab_report`

Skill API shape:

```text
POST /skills/{skill_name}
GET  /skills/jobs/{job_id}
GET  /skills/jobs/{job_id}/artifact
```

## Skill Artifacts

Artifacts should continue using the existing broad pattern under:

```text
/home/chuck/data/media/
```

Use a folder per artifact type, for example:

```text
/home/chuck/data/media/research_reports/
/home/chuck/data/media/investment_briefs/
/home/chuck/data/media/presentations/
/home/chuck/data/media/code_reviews/
/home/chuck/data/media/homelab_reports/
/home/chuck/data/media/siri_outputs/
```

Artifacts should be accessible:

- On LAN
- Publicly through narrow Siri-safe retrieval when appropriate

Artifacts should not automatically enter the KB.
Chuck may manually move or specify selected artifacts for KB inclusion.

## Knowledge Base Strategy

The KB is curated-only for now.

Do not automatically ingest:

- Lego home folders
- Lego Share folder
- Financial documents
- Raw NAS folders
- Multimedia files
- Historical personal archives

Approved ingestion path:

```text
Manually curated files only
```

Future ingestion can be improved after the pipeline is reliable.

## Portal Strategy

The portal is a separate project tracked in `portal_todo.md`.

Portal principles:

- LAN only
- Family-wide
- No auth initially
- Containerized
- Prefer hosting on Lego port 80
- Links to services
- Pulls safe summary/status data where useful
- Does not become the AI runtime
- Does not replace Open WebUI
- Does not expose admin systems

## Presenton Strategy

Presenton should be available in two ways:

1. LAN-only tile/link behind the family portal
2. Skill integration for remote use through the Siri path

This gives Chuck remote presentation generation without exposing Presenton broadly.

## Home Automation Strategy

Homebridge remains the smart home layer for now.

Rules:

- Keep Homebridge on Lego
- No Home Assistant migration in current plan
- No broad home-control MCP tools yet
- Future home tools should start read-only/status-only

## Operating Philosophy for Qwen

Qwen should build incrementally and safely.

Default behavior:

- Create docs
- Create draft configs
- Create new files/directories
- Build local/test-only components
- Run read-only inspections
- Produce validation reports

Qwen should not:

- Restart production services
- Rebuild production containers
- Modify live LiteLLM config
- Modify live Caddy or Cloudflare routing
- Change `.env` directly
- Expose new public endpoints
- Bind to existing production ports
- Delete containers, volumes, images, networks, or data
- Run migrations without manual approval
- Upgrade production packages without manual approval
- Change ownership or permissions on production paths without manual approval

Any risky step must be written as a manual task for Chuck.

## Desired End State

```text
Family and power users
  -> channels
  -> shared platform capabilities
  -> Thor orchestration and tools
  -> Matrix models
  -> Lego durable storage
```

The system should feel simple to the family, powerful to Chuck and son, and safe enough that Qwen can help build it without breaking the parts already working.
