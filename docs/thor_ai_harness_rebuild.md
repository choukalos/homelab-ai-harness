# Thor AI Harness Rebuild Strategy

> Phase 4.4 — Plan for rebuilding the AI Harness as a modular skill runner beside the current monolith.
> Date: 2026-07-03
> Status: **DONE — superseded.** The skill runner became the normalized AI
> gateway and the old ai-harness monolith was decommissioned (2026-08-25,
> containers removed). Kept as historical planning context.

---

## Approach: Option C

```
Build a new skill runner beside the current AI Harness.
Port useful capabilities one at a time.
Validate locally.
Expose selected endpoints after manual review.
Retire or archive the old Harness only after parity is proven.
```

**Never replace the current Harness in-place.** The new runner lives in a separate directory and compose file until it is proven.

---

## Current Harness Inventory

| Component | Container | Purpose |
|---|---|---|
| API Server | `ai-harness` (:8090) | FastAPI server, Siri routes, OWUI integration, media serving |
| Worker 1 | `ai-harness-worker-1` | Celery worker (4 concurrency) — async task execution |
| Worker 2 | `ai-harness-worker-2` | Celery worker (4 concurrency) — async task execution |
| Beat Scheduler | `ai-harness-beat` | RedBeat scheduler — recurring tasks, periodic jobs |
| KB Watcher | `ai-kb-watcher` | Filesystem watcher — auto-ingests files dropped in `/data/ai-kb/raw` |

### Current Integrations
- **LiteLLM** (`litellm-proxy:4000`) — model inference
- **SearXNG** (`searxng:8080`) — web search
- **Crawl4AI** (`crawl4ai:11235`) — page fetching
- **Qdrant** (`qdrant:6333`) — vector search / KB
- **Redis** (`ai-redis:6379`) — Celery broker + RedBeat scheduler
- **ComfyUI** (`${MATRIX_IP}:8188`) — image generation
- **Presenton** (`presenton:80`) — presentation generation
- **MySQL** — job state, metadata
- **Volumes** — `/data/ai-kb`, `/data/media`, `/home/chuck/workspace`

---

## What Is Broken or Problematic

| Problem | Impact |
|---|---|
| Monolithic codebase | Hard to modify; any change risks breaking Siri or OWUI routes |
| Tight coupling | Skill logic, API routing, KB ingestion, and media serving are in one repo |
| KB auto-ingestion | `kb-watcher` auto-ingests from `/data/ai-kb/raw` — conflicts with curated-only policy |
| Hardcoded paths | Many paths are environment-dependent or hardcoded |
| No per-skill isolation | Skills share the same worker pool; a failing skill can block others |
| No clear skill manifest | Skills are implicit in the codebase, not declared as discrete units |

---

## Useful Capabilities to Salvage

| Capability | Source | Retain? |
|---|---|---|
| Siri ask endpoint | `ai-harness` FastAPI routes | Yes — port to new runner |
| Skill job lifecycle (create/status/artifact) | Celery tasks | Yes — core API shape stays |
| Web search integration | SearXNG + Crawl4AI calls | Yes — refactor into MCP |
| Image generation | ComfyUI integration | Yes — refactor into skill/MCP |
| KB embedding/retrieval | Qdrant + embedding calls | Yes — refactor into MCP |
| Presenton integration | Presenton API calls | Yes — refactor into skill |
| Media artifact storage | `/data/media` volume mount | Yes — keep directory structure |
| RedBeat scheduling | Beat scheduler | Yes — keep for recurring skills |
| KB watcher | `ai-kb-watcher` | No — replace with manual ingestion |

---

## New Runner Architecture

```
skills/
  runner/               ← New skill runner (separate from current Harness)
    server/             ← FastAPI or lightweight HTTP server
    scheduler/          ← Celery/Beat or equivalent
    adapter/            ← Channel adapters (Siri, OWUI, CLI, n8n)
  deep_research/
  investment_brief/
  presentation_build/
  code_review/
  ...

mcp/
  servers/
    search/
    knowledge/
    ...
```

### Components

| Component | Purpose |
|---|---|
| **Skill Runner** | Lightweight HTTP server that exposes `POST /skills/{name}`, `GET /skills/jobs/{id}`, `GET /skills/jobs/{id}/artifact` |
| **Channel Adapters** | Thin translators per channel (Siri format → skill input, OWUI → skill input, etc.) |
| **Workflow Orchestrator** | Replaces the monolithic task logic. Composes skills from MCP tools + model calls |
| **Scheduler** | Recurring skill execution (morning brief, homelab report) |

### Principles

- New runner starts on a **non-production port** (e.g., 8091) for local testing.
- Caddy and Cloudflare are **not updated** until manual approval.
- Existing Siri route (`siri.choukalos.com → ai-harness:8090`) remains untouched.
- Skills are declared in a manifest (`skills.yml`) rather than hardcoded.
- Each skill is an independent module with its own manifest entry.

---

## Migration Sequence

| Phase | Action | Risk |
|---|---|---|
| 1 | Build new runner beside current Harness (port 8091) | Zero — no production impact |
| 2 | Port Siri ask endpoint to new runner | Low — test locally, compare responses |
| 3 | Port skill job lifecycle (create/status/artifact) | Low — same API shape |
| 4 | Port web search via MCP | Medium — validate SearXNG/Crawl4AI integration |
| 5 | Port image generation via MCP | Medium — validate ComfyUI integration |
| 6 | Port KB access via MCP | Medium — validate Qdrant integration |
| 7 | Port Presenton integration | Low — isolated skill |
| 8 | Port scheduling (Beat → new scheduler) | Medium — validate recurring jobs |
| 9 | Switch Siri Caddy route to new runner (manual gate) | High — requires Chuck approval |
| 10 | Archive old Harness | Low — after 30-day validation |

---

## Compatibility with Existing Siri Route

During transition:

| Period | Siri Route | Notes |
|---|---|---|
| Before cutover | `siri.choukalos.com → ai-harness:8090` | Current Harness handles all traffic |
| During testing | New runner on port 8091, not routed | Chuck tests manually via CLI |
| After cutover | `siri.choukalos.com → new-runner:8091` | Caddy route updated (manual gate) |
| Rollback | Revert Caddy to `ai-harness:8090` | Instant rollback if issues arise |

---

## Artifact Strategy

Artifacts continue using the existing pattern under `/home/chuck/data/media/` with per-type folders. See `thor_artifact_strategy.md`.

---

## Local-Only Testing Plan

1. Build new runner image from `skills/runner/`
2. Run on non-production port (e.g., 8091) bound to `THOR_IP`
3. Test via CLI: `curl http://192.168.4.54:8091/skills/deep_research`
4. Compare responses against current Harness
5. Validate job lifecycle: launch → status polling → artifact retrieval
6. Test each skill independently before integrating channel adapters

---

## Manual Cutover Tasks

```text
MANUAL TASK FOR CHUCK:
Reason: Switch Siri route from old Harness to new skill runner.
Command: Update Caddyfile @siri and @siri_media to point to new runner port. Reload Caddy.
Expected impact: Siri traffic routes to new runner. Old Harness continues running on 8090 but receives no public traffic.
Rollback: Revert Caddyfile to previous version. Reload Caddy.
Validation: Test siri.choukalos.com /health, /siri/ask, and /media/files/* endpoints.
```

---

## Rollback Plan

- Old Harness remains running on port 8090 until 30 days after cutover.
- Caddy can be reverted in one line change.
- MySQL data is shared — no data loss risk.
- KB and media volumes are shared — no data loss risk.
- If new runner has critical issues, revert Caddy and the old Harness resumes instantly.

---

## Rules

- Do not replace current AI Harness in place.
- Do not bind new runner to production port 8090.
- Do not update Caddy.
- Do not update Cloudflare.
- Do not restart existing services.
