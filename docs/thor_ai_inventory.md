# Thor AI Capability Inventory

> Phase 1 — Classify current capabilities and decide what becomes MCP, a skill, a regular app, or remains as-is.
> Date: 2026-07-03
> Status: Documentation only. No service restarts, config edits, or file moves.

---

## Capability Inventory

| Capability | Current Location | Current Form | Future Form | Risk | Notes |
|---|---|---|---|---|---|
| **LiteLLM** | `compose/compose.ai-core.yml`, `litellm/config.yml` | Standalone proxy on ai-net:4000, 4 model defs, postgres backend, prometheus callback | **As-is (foundation)** — stays as the single model gateway; future: add model aliases, per-key restrictions, MCP tool routes | Low | Production core. Zero-touch. New config drafted separately, never edited in-place. |
| **Open WebUI** | `compose/compose.ai-core.yml` | LAN-only UI on :3000, connects to LiteLLM as OpenAI backend | **As-is** — primary human chat interface; no structural changes needed | Low | LAN-only by design. No public route in Caddy. |
| **AI Harness** | ~~`compose/compose.ai-harness.yml` + `ai-harness/`~~ | FastAPI uvicorn on LAN :8090, 2 celery workers, beat scheduler, kb-watcher | **✅ Replaced by Skill Runner** — channels call skills via skill runner, not apps directly. Harness code archived. | **Done** | Refactored 2026-07-06. Source archived to `ai-harness-decommissioned/`. |
| **AI Harness — Channels** | `ai-harness-decommissioned/channels/` (openwebui/, siri/) | Channel-specific routers (Siri API, Open WebUI callbacks) | **MCP + Skill Gateway** — each channel gets a thin adapter; shared capabilities go through skill runner | **High** | Siri already has X-API-Key auth in Caddy. Open WebUI uses harness for image gen + actions. |
| **AI Harness — Research** | `ai-harness-decommissioned/research/` (deep_research/, market_research/, web_search/) | Deep research pipeline, market research, web search via Crawl4AI/SearXNG | **MCP servers** — web_search, deep_research, market_research as discrete MCP tools | Medium | Well-structured. Good MCP candidates. Uses Crawl4AI + SearXNG internally. |
| **AI Harness — Knowledge** | `ai-harness-decommissioned/knowledge/family_kb/` + kb-watcher | File watcher → Qdrant embedding pipeline, BAAI/bge-small-en-v1.5 | **MCP server (knowledge-mcp)** — Qdrant-based RAG for family knowledge base | Medium | kb-watcher is a background daemon. RAG queries become an MCP tool. |
| **AI Harness — Creative** | `ai-harness-decommissioned/creative/` (charts/, layout/, presentation/) | Chart generation, layout, presentation modules | **Skills** — self-contained scripts the skill runner executes | Low | Presenton already handles presentations. Charts/layout could be skills or merged into Presenton. |
| **AI Harness — Media** | `ai-harness-decommissioned/media/` (comfy_client.py, workflows/) | ComfyUI client on Matrix:8188, filename utils, media workflows | **Skills** — image generation workflows run by skill runner on Matrix | Medium | Depends on ComfyUI on Matrix. Skill runner needs to orchestrate remote workflow. |
| **AI Harness — Filetools** | `ai-harness-decommissioned/filetools/` (service.py, router.py, schemas.py) | File operations service with REST API | **Skill + MCP** — file read/write/list as a skill or MCP tool | Low | Straightforward refactor. |
| **AI Harness — Infra** | `ai-harness-decommissioned/infra/` (core/, scheduler/, tasks/, workflows/) | Celery core, redbeat scheduler, task definitions, workflow orchestration | **As-is (infra)** — task queue/scheduler stays; skill runner may eventually replace Celery for simple tasks | Low | Not touched. Celery handles async/background work. |
| **Qdrant** | `compose/compose.ai-core.yml` | Vector DB on ai-net:6333, storage at /data/qdrant | **As-is** — RAG backend. Query access through knowledge MCP or skill | Low | Production. No config changes. |
| **Redis (ai-redis)** | `compose/compose.ai-core.yml` | Celery broker/cache on ai-net:6379 | **As-is** — Celery message broker for harness workers | Low | Production. Not touched. |
| **SearXNG** | `compose/compose.ai-core.yml` | Private search on ai-net:8088, valkey cache | **MCP server (search-mcp)** — expose as `web_search` MCP tool | Low | Already running well. MCP just wraps the API. |
| **SearXNG Valkey** | `compose/compose.ai-core.yml` | SearXNG cache (valkey:9) | **As-is** — cache backend for SearXNG | Low | Not touched. |
| **Crawl4AI** | `compose/compose.ai-core.yml` | Web crawler on ai-net:11235 | **MCP server** — `web_crawl` tool for deep research | Low | Already running. MCP wraps the API. |
| **MkDocs Family Wiki** | `compose/compose.ai-core.yml` | LAN-only wiki on :8011, docs at /data/ai-kb/repo | **As-is** — human-readable reference; also indexed into Qdrant by kb-watcher | Low | Not an AI capability per se. Stays as documentation source. |
| **Presenton** | `compose/compose.ai-core.yml` | LAN-only presentation tool on :5000, LiteLLM as LLM backend, SearXNG for search, auth-enabled | **As-is** — standalone presentation app; could be exposed to channels via skill later | Low | Already well-integrated with LiteLLM. Low priority to change. |
| **n8n** | `compose/compose.n8n.yml` (NOT RUNNING) | Workflow automation platform | **As-is (future)** — re-enable when needed for scheduled/automated workflows | Low | Compose file exists but project not running. Keep for future automation needs. |
| **Caddy** | `compose/compose.core.yml`, `caddy/Caddyfile` | Reverse proxy on ports 80/443, routes all public services, on 3 networks | **As-is (foundation)** — routing layer for all public access | Low | Production core. New routes drafted separately, never edited in-place. |
| **Cloudflare Tunnel** | `compose/compose.edge.yml` | `cloudflared` with tunnel token, routes HTTPS → Caddy | **As-is (foundation)** — zero-trust internet ingress | Low | Production core. Tunnel routes managed in Cloudflare dashboard. |
| **Victoria Metrics** | `compose/compose.monitoring.yml` | Metrics backend on :9090, scrapes LiteLLM prometheus + node/cadvisor | **As-is** — observability backend; will add skill runner + MCP metrics later | Low | Already scraping LiteLLM. Extend scrape config for new services. |
| **Grafana** | `compose/compose.monitoring.yml` | Dashboards on :3001, provisioned datasources/dashboards | **As-is** — observability UI; will add skill runner/MCP dashboards later | Low | Provisioned config stays. New dashboards added, not edited. |
| **Invest Hub** | `compose/compose.invest-hub.yml` | Client + server on public-net, GitHub runner for CI/CD | **Not Thor** — separate project (invest-hub), not part of AI platform refactor | N/A | Out of scope. Leave untouched. |
| **Ghost Blog** | `compose/compose.ghost.yml` | Blog on public-net, MySQL on host | **Not Thor** — content site, not AI platform | N/A | Out of scope. Leave untouched. |
| **Plausible** | `compose/compose.monitoring.yml` | Analytics (postgres + clickhouse), admin on LAN :8082, narrow public routes | **Not Thor** — analytics, not AI platform | N/A | Out of scope. Leave untouched. |
| **MySQL (bare-metal)** | Host docker, not in Docker | Database for Ghost, invest-hub, AI harness (AI_DB_*) | **As-is** — shared database on host | Low | Not managed by Thor. Used by multiple services. |

---

## Classification Summary

### As-Is (Foundation — Zero Touch)
These stay exactly as they are. New work drafts alongside, never edits in-place.

| Capability | Reason |
|---|---|
| LiteLLM | Single model gateway. Foundation of the platform. |
| Open WebUI | Primary human chat interface. |
| Qdrant | Vector DB. RAG backend. |
| Redis | Celery broker. |
| SearXNG Valkey | SearXNG cache. |
| Caddy | Reverse proxy. Public ingress. |
| Cloudflare Tunnel | Internet ingress. |
| Victoria Metrics | Observability backend. |
| Grafana | Observability UI. |
| MkDocs Family Wiki | Documentation source. |
| MySQL (bare-metal) | Host DB. Not Thor-managed. |

### As-Is (Application — No Changes Needed)
These work well and don't need structural changes.

| Capability | Reason |
|---|---|
| Presenton | Well-integrated with LiteLLM. Low priority. |
| n8n | Not running, but keep for future automation. |

### → MCP Servers (New)
Current harness capabilities that should become discrete MCP tools.

| New MCP Server | Source Capability | Description |
|---|---|---|
| **search-mcp** | SearXNG + Crawl4AI | `web_search`, `web_crawl` tools |
| **knowledge-mcp** | Harness knowledge/family_kb + Qdrant | RAG query over family knowledge base |
| **research-mcp** | Harness research/ (deep_research, market_research) | Deep research pipeline, market research |

### → Skills (New)
Current harness capabilities that should become executable skill scripts.

| Skill | Source Capability | Description |
|---|---|---|
| **chart-gen** | Harness creative/charts | Generate charts from data |
| **layout** | Harness creative/layout | Layout design |
| **image-gen** | Harness media/comfy_client | Image generation via ComfyUI on Matrix |
| **file-tools** | Harness filetools/ | File read/write/list operations |

### → Rebuild: Skill Gateway (New)
The current AI Harness is too monolithic. It becomes a thin gateway that routes channel requests to the right MCP server or skill.

| New Component | Replaces | Description |
|---|---|---|
| **Skill Runner** | harness apps/channels/creative/media/filetools | Executable skill scripts with isolated context |
| **Channel Adapters** | harness channels/siri/, channels/openwebui/ | Thin adapters per channel (Siri, OWUI, llm.choukalos.com, etc.) |
| **Workflow Orchestrator** | harness infra/workflows/, infra/scheduler/ | Multi-step workflows composed of MCP calls + skills |

### Out of Scope
| Capability | Reason |
|---|---|
| Invest Hub | Separate project, not AI platform |
| Ghost Blog | Content site, not AI platform |
| Plausible | Analytics, not AI platform |

---

## Observations

1. **LiteLLM is the right gateway layer.** It handles model routing, budgeting, and metrics. The only gap is no model aliases or per-key restrictions yet.
2. **The harness does too much.** It mixes channel routing, app logic, and orchestration. The goal is to extract capabilities into MCP servers and skills, leaving the harness as a thin gateway.
3. **SearXNG and Crawl4AI are perfect MCP candidates.** They're already clean APIs on ai-net. Wrapping them as MCP tools is low-risk.
4. **Qdrant knowledge is a natural RAG MCP.** The kb-watcher handles ingestion; an MCP just adds the query interface.
5. **Creative/media skills are self-contained.** They execute in isolation and produce files. Perfect for the skill runner.
6. **Presenton is already well-architected.** It talks to LiteLLM directly, uses SearXNG for search, and has its own auth. Low priority to change.
7. **Caddy and Cloudflare are the public ingress.** All public access flows through them. Any new public endpoint needs a Caddy route + optional Cloudflare tunnel route.
8. **n8n is parked but not dead.** The compose file exists. It can be re-enabled for scheduled/automated workflows when needed.

---

## Next Step

Phase 2 — Channel Architecture. Design how each channel (Siri, OWUI, llm.choukalos.com, PI, Claude Code, etc.) accesses the MCP servers and skill runner.
