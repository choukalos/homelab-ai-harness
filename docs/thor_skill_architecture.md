# Thor Skill Architecture

> Phase 4.6 — Define the skill architecture, API shape, and initial skill inventory.
> Date: 2026-07-03 (design baseline)
> Status: **Implemented and evolved** — skill runner is in production. The July
> inventory below is historical; current state is marked inline.

**Current state (2026-08-31)**
- **15 skills** live (the July 9-skill inventory has grown; `local/*` model
  aliases were never implemented — skills use live aliases, primarily
  `matrix-coder`; the stale `local/qwen-coder` references broke 7 skills and
  were fixed in `auth_todo.md` Phase 9, 2026-08-25). `code_review` / `repo_maintenance`
  are TODO placeholders (no `skill.py`/`skill.yml`, excluded from `GET /skills`).
  Phase 2 (2026-08-31) added 3 agent skills: `business_analyst` (NL→SQL over
  `mcp_mysql`), `content_writer` (multi-format content via `mcp_search`),
  `marketing_strategy` (GTM via `mcp_search`). All 3 verified end-to-end and
  wired into Siri intent dispatch. See `docs/thor_cross_client_skills.md`.
- **Chat gateway:** `POST /api/chat` (intent dispatch → skills / direct LLM /
  MCP tools) + `GET /api/jobs/{job_id}`; Siri via `siri.choukalos.com`
  (Caddy, `X-API-Key`).
- **Skill discovery:** `GET /skills` lists the 15 skills (name, description,
  inputs, max_runtime, channels). Auth mirrors `/api/chat` (enforced when
  `SKILL_RUNNER_API_KEY` set, open when unset). Added 2026-08-29 (skills-todo
  Phase A).
- **Durable job index (MySQL, 2026-08-29):** job state backed by
  `homelab.skill_jobs` (not in-memory-only) — jobs survive skill-runner restarts;
  a job still `running`/`pending` at restart is marked `interrupted`. Best-effort:
  degrades to in-memory-only if MySQL is unreachable. See
  `docs/thor_cross_client_skills.md`.
- **Cross-client access (2026-08-29, skills-todo A–D):** the `mcp_skills` MCP
  server (3 meta-tools) wraps the skill-runner so any MCP client lists + runs
  skills through LiteLLM; 15 skills registered in the LiteLLM Skill Hub
  (`/claude-code/marketplace.json`); `agents-skills/` SKILL.md wrappers for
  per-machine `/skill:name` slash commands. See `docs/thor_cross_client_skills.md`.
- **Identity:** `X-API-Key` → `user_id` map (`memory/identity.py`;
  `MEMORY_USER_KEYS`); jobs run as `service` unless user-triggered.
- **Long-term memory (in-process Mem0, Phases 0–9 complete 2026-08-28):**
  automatic pre-request retrieval + post-turn writeback, household scope,
  secret filtering, admin REST (`/api/memory/*`, `X-Api-Key` header) + CLI +
  `/metrics`. Plan: `memory_todo.md`; state: `docs/memory/IMPLEMENTATION_STATE.md`.
- **Observability:** `/metrics` (Prometheus) scraped by VictoriaMetrics
  (job `skill-runner`).
- **Scheduler:** cron jobs via `dispatch_job()` under `service` identity.

---

## Principle

Skills are controlled, multi-step agentic workflows. They are used when a task has multiple steps, runs longer than a quick chat response, produces artifacts, needs repeatability, needs logging, needs approval gates, or should be exposed through Siri or automation.

```
Channel → Skill Runner → Workflow (MCP tools + model calls) → Artifact
```

---

## Skill API

```
GET  /skills                          — List skills (name, description, inputs, max_runtime, channels)
POST /skills/{skill_name}             — Launch a skill (synchronous: blocks until terminal or approval gate)
GET  /skills/jobs/{job_id}            — Get job status (durable: survives restarts)
GET  /skills/jobs/{job_id}/artifact   — Retrieve artifact
POST /skills/jobs/{job_id}/approve    — Approve a job at an approval gate
POST /skills/jobs/{job_id}/cancel     — Cancel a job
```

### Launch Request

```json
{
  "skill": "deep_research",
  "params": {
    "query": "Latest developments in quantum computing 2026",
    "depth": "comprehensive",
    "max_sources": 10
  },
  "requester": "chuck",
  "channel": "cli"
}
```

### Status Response

```json
{
  "job_id": "job-abc123",
  "skill": "deep_research",
  "status": "completed",
  "created_at": "2026-07-03T10:00:00Z",
  "completed_at": "2026-07-03T10:05:00Z",
  "summary": "Research on quantum computing developments completed. Found 8 key sources.",
  "artifact": "/home/chuck/data/media/research_reports/deep_research_2026-07-03T10-05-00_quantum-computing.md",
  "requester": "chuck",
  "channel": "cli"
}
```

### Status Values

| Status | Meaning |
|---|---|
| `pending` | Queued, waiting for worker |
| `running` | Actively executing |
| `completed` | Finished successfully |
| `failed` | Error during execution |
| `awaiting_approval` | Waiting for manual approval gate |
| `cancelled` | Cancelled by user |
| `interrupted` | Was `running`/`pending` when the runner restarted (durable index) |

---

## Skill Inventory

### 1. `siri_ask`

| Field | Value |
|---|---|
| **Purpose** | Quick Q&A for Siri/iOS Shortcuts. Short answers, no heavy research. |
| **Inputs** | `query` (string), optional `context` (previous conversation) |
| **Outputs** | Short text answer (<500 tokens) |
| **Required tools** | Model chat (`local/qwen-coder`) |
| **Required model alias** | `local/qwen-coder` (main model) |
| **Expected runtime** | <30 seconds |
| **Approval gates** | None |
| **Artifact path** | `/home/chuck/data/media/siri_outputs/` (optional, for logging) |
| **Logging** | Query, model used, response summary, timestamp |
| **Rollback** | None needed — stateless |
| **Channel entry points** | Siri |

---

### 2. `deep_research`

| Field | Value |
|---|---|
| **Purpose** | Multi-source deep research with citation and artifact generation. |
| **Inputs** | `query` (string), `depth` (quick/comprehensive/exhaustive), `max_sources` (int) |
| **Outputs** | Research report (Markdown) with citations, saved as artifact |
| **Required tools** | `mcp_search`, `mcp_crawl`, `mcp_knowledge`, model chat |
| **Required model alias** | `local/qwen-coder` (main model) |
| **Expected runtime** | 2-15 minutes |
| **Approval gates** | None (read-only research) |
| **Artifact path** | `/home/chuck/data/media/research_reports/` |
| **Logging** | Query, sources consulted, model used, artifact path, runtime |
| **Rollback** | Delete artifact on failure |
| **Channel entry points** | CLI, PI, n8n |

---

### 3. `investment_brief`

| Field | Value |
|---|---|
| **Purpose** | Generate investment analysis briefs for specific tickers or sectors. |
| **Inputs** | `ticker` or `sector` (string), `analysis_type` (fundamental/technical/news) |
| **Outputs** | Investment brief (Markdown) with findings, risks, summary |
| **Required tools** | `mcp_stocks`, `mcp_search`, `mcp_crawl`, model chat |
| **Required model alias** | `local/qwen-coder` (main model) |
| **Expected runtime** | 3-10 minutes |
| **Approval gates** | None (read-only analysis) |
| **Artifact path** | `/home/chuck/data/media/investment_briefs/` |
| **Logging** | Ticker/sector, analysis type, data sources, artifact path |
| **Rollback** | Delete artifact on failure |
| **Channel entry points** | CLI, n8n |

---

### 4. `presentation_build`

| Field | Value |
|---|---|
| **Purpose** | Generate presentations from a topic or existing content using Presenton. |
| **Inputs** | `topic` (string), `slide_count` (int), `style` (optional), `content_source` (existing artifact or text) |
| **Outputs** | Presentation file, artifact link |
| **Required tools** | Presenton API, model chat, optional `mcp_knowledge` for content |
| **Required model alias** | `local/qwen-coder` (main model) |
| **Expected runtime** | 1-5 minutes |
| **Approval gates** | None (generative, no sensitive data unless provided) |
| **Artifact path** | `/home/chuck/data/media/presentations/` |
| **Logging** | Topic, slide count, model used, artifact path |
| **Rollback** | Delete presentation on failure |
| **Channel entry points** | CLI, Siri, n8n |

---

### 5. `code_review`

| Field | Value |
|---|---|
| **Purpose** | Review code from a file, PR, or repository. |
| **Inputs** | `repo_path` or `file_path` (string), `scope` (file/branch/repo), `focus` (security/performance/style) |
| **Outputs** | Code review report (Markdown) with findings, ratings, recommendations |
| **Required tools** | `mcp_filesystem_readonly`, model chat |
| **Required model alias** | `local/qwen-coder` |
| **Expected runtime** | 1-10 minutes (depends on scope) |
| **Approval gates** | None (read-only review) |
| **Artifact path** | `/home/chuck/data/media/code_reviews/` |
| **Logging** | Repo/file path, scope, model used, artifact path |
| **Rollback** | Delete artifact on failure |
| **Channel entry points** | CLI, PI |

---

### 6. `repo_maintenance`

| Field | Value |
|---|---|
| **Purpose** | Repository hygiene: dependency updates, cleanup suggestions, documentation gaps. |
| **Inputs** | `repo_path` (string), `task_type` (deps/cleanup/docs/all) |
| **Outputs** | Maintenance report (Markdown) with actionable items |
| **Required tools** | `mcp_filesystem_readonly`, model chat |
| **Required model alias** | `local/qwen-coder` |
| **Expected runtime** | 2-10 minutes |
| **Approval gates** | Approval required before any write operations (currently read-only) |
| **Artifact path** | `/home/chuck/data/media/code_reviews/` |
| **Logging** | Repo path, task type, findings, artifact path |
| **Rollback** | Read-only — no rollback needed. Future write mode needs explicit approval. |
| **Channel entry points** | CLI, PI |

---

### 7. `morning_brief`


| Field | Value |
|---|---|
| **Purpose** | Generate a daily morning briefing: weather, news, calendar, homelab status, investments. |
| **Inputs** | `sections` (weather/news/calendar/homelab/investments — optional, default all) |
| **Outputs** | Morning brief (Markdown) saved as artifact |
| **Required tools** | `mcp_search`, `mcp_homelab_status`, `mcp_stocks`, model chat |
| **Required model alias** | `local/qwen-coder` (main model) |
| **Expected runtime** | 2-5 minutes |
| **Approval gates** | None |
| **Artifact path** | `/home/chuck/data/media/homelab_reports/` |
| **Logging** | Sections included, data sources, artifact path |
| **Rollback** | Delete artifact on failure |
| **Channel entry points** | n8n (scheduled), CLI |

---

### 8. `homelab_report`

| Field | Value |
|---|---|
| **Purpose** | Generate a homelab health and usage report. |
| **Inputs** | `period` (daily/weekly/monthly), `include` (containers/metrics/storage/network — optional) |
| **Outputs** | Homelab report (Markdown) with status, metrics, recommendations |
| **Required tools** | `mcp_homelab_status`, model chat |
| **Required model alias** | `local/qwen-coder` (main model) |
| **Expected runtime** | 1-3 minutes |
| **Approval gates** | None (read-only) |
| **Artifact path** | `/home/chuck/data/media/homelab_reports/` |
| **Logging** | Period, sections included, artifact path |
| **Rollback** | Delete artifact on failure |
| **Channel entry points** | CLI, n8n |

---

## Skill Manifest Format

Each skill is declared in a manifest:

```yaml
name: deep_research
version: "1.0"
description: "Multi-source deep research with citation and artifact generation"
inputs:
  - name: query
    type: string
    required: true
  - name: depth
    type: string
    enum: [quick, comprehensive, exhaustive]
    default: comprehensive
  - name: max_sources
    type: integer
    default: 10
tools:
  - mcp_search
  - mcp_crawl
  - mcp_knowledge
model_alias: local/qwen-coder
artifact_path: /home/chuck/data/media/research_reports/
approval_gates: []
channels: [cli, pi, n8n]
max_runtime: 900  # seconds
```

---

## Rules

- **Implemented.** Skill runner runs in production (`compose/compose.skill-runner.yml`,
  `THOR_IP:8091`); this doc is the design baseline.
- Skills are independent modules with their own manifests.
- Skills compose MCP tools and model calls — they do not directly access backends.
- The skill runner handles job lifecycle, artifact storage, and channel routing.
- New skills require Chuck's approval before being added to the manifest.
