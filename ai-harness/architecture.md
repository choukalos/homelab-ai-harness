# AI Harness Refactor Plan

## Goal

Consolidate all custom AI tooling into a single extensible `ai-harness` application.

The harness becomes the unified API/tool layer for:

- OpenWebUI
- Siri Shortcuts / CarPlay
- Knowledge base ingestion + search
- Web search + research briefs
- Future AI tooling

Infrastructure services remain separate containers.

---

# Architecture

```text
OpenWebUI / Siri / Apps
          |
          v
+-------------------+
|    ai-harness     |
|-------------------|
| OpenAPI endpoints |
| KB ingestion      |
| KB semantic search|
| Web search        |
| Research briefs   |
| Siri endpoints    |
+-------------------+
      |
      +--> Qdrant
      +--> SearXNG
      +--> Crawl4AI
      +--> LiteLLM
      +--> ai-kb markdown repo

---

# Adding New Harness Features

Each new capability should be added as a first-class feature module.

## Standard module shape

```text
feature_name/
  __init__.py
  router.py      # FastAPI endpoints
  schemas.py     # Pydantic request/response models
  service.py     # Core business logic
  prompts.py     # LLM prompts, if needed

---

# Task Queue (Celery + Redis)

The harness includes a Celery-backed task queue so long-running operations
(LLM calls, image generation, data processing) can be offloaded to workers
without blocking HTTP responses.

## Infrastructure

- **Broker & Result Backend**: `ai-redis` (Redis 7, already running)
- **Workers**: 2 worker containers, 4 concurrent tasks each
- **Worker management**: `GET /tasks/workers` returns live worker stats

## API Endpoints (`/tasks`)

```
POST /tasks/prompt    — queue a single LLM prompt
POST /tasks/chain     — queue a sequential chain of LLM prompts
POST /tasks/python    — queue Python code execution (trusted only)
GET  /tasks/{task_id} — inspect task status / retrieve result
GET  /tasks/workers   — list active workers + stats
```

## Adding custom tasks

1. Add a new `@celery.task` function in `tasks/tasks.py`
2. (optional) Add a corresponding router endpoint if you want HTTP submission
3. Rebuild the image and restart workers
4. To schedule these tasks — see **Scheduler** below / `scheduler/README.md`

```python
from core.celery_app import celery

@celery.task(bind=True, name="tasks.my_custom_task")
def my_custom_task(self, param1: str, param2: int = 10):
    # do work ...
    return {"output": f"processed {param1} x {param2}"}
```

---

# Scheduler (Celery Beat + Redbeat)

On top of the task queue, the harness has a **durable scheduler** that lets you
fire tasks on a recurrence: once, cron, interval, condition, or manual trigger.

## Components

```
scheduler/
  models.py   — ScheduleEntry dataclass + enums
  store.py    — Redis-backed CRUD
  tasks.py    — dispatch_task & condition_checker
  schemas.py  — Pydantic request/response models
  service.py  — business logic, redbeat sync, NLP helpers
  router.py   — FastAPI REST + chat endpoints
  README.md   — full documentation (read this in future sessions)
```

## How It Works

1. Create a schedule via `POST /schedules` (REST) or `POST /schedules/chat` (NLP).
2. Entry is persisted in Redis (`harness:schedule:{id}`).
3. Active non-condition schedules are synced to **redbeat** (Redis-backed beat).
4. The **beat container** dispatches `scheduler.dispatch_task` at the right time.
5. `dispatch_task` checks limits, bumps run_count, calls the target task.
6. Condition schedules fire when `POST /schedules/condition` pushes an event.

## API Endpoints (`/schedules`)

```
GET    /schedules             — list all (JSON)
GET    /schedules/text        — plain-text summary for voice/chat
GET    /schedules/{id}        — single schedule detail
POST   /schedules             — create
PATCH  /schedules/{id}        — partial update
DELETE /schedules/{id}        — remove
POST   /schedules/{id}/trigger  — fire immediately
POST   /schedules/condition   — push a condition event
POST   /schedules/chat        — NLP command handler
```

## Chat Commands (via POST /schedules/chat)

- "list schedules" — returns all schedules
- "pause morning briefing" — pauses a schedule
- "resume weekly report" — resumes a schedule
- "delete old job" — removes it
- "trigger kb digest now" — fires immediately

See `scheduler/README.md` for full details.
```
