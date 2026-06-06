# Scheduler — Durable Task Scheduling

> **Read this file whenever you need to interact with the harness scheduler.**
> It documents every capability, API endpoint, integration point, and example
> so you can use and extend scheduling without reading through the code.

---

## Quick Summary

The harness has a persistent scheduler sitting on top of the Celery task queue.
It supports **five ways** to fire a scheduled task:

| Trigger              | Description                               |
|---                    |-------------------------------------------|
| **Onetime**   `onetime`                | Fire once at a specific ISO-8601 datetime |
| **Cron` `cron`                           | Repeated on a standard 5-field cron expression |
| **Interval** `interval`                 | Repeated every N seconds |
| **Condition** `condition`               | Fire when a named event is pushed (e.g. ``kb_ingestion_done``) |
| **Manual trigger**                     | Fire immediately via API or chat command |

Every schedule is **durable** — persisted in Redis even across full restarts.

---

## Architecture

```
Client (curl / OpenWebUI / Siri / Python)
        │
        │ POST /schedules    (create schedule)
        │                     POST /schedules/chat   ("pause morning briefing")
        ▼
┌──────────────────────┐
│   ai-harness (FastAPI)│  ← REST + chat endpoints
│   app:app :8090       │
└─────────┬───────┬─────┘
           │       │
           ▼       ▼
┌─────────────────────┐  ┌───────────────────┐
│  Redis (ai-redis)    │  │ ai-harness-beat   │
│                      │  │ (Celery Beat +    │
│  harness:schedule:*   │  │  redbeat)         │
│  redbeat:*            │  └───────┬───────────┐
└────────────┬─────────┘          │           │
             │                    ▼           ▼
             │         ┌──────────────┐  ┌──────────────┐
             └────────→│ worker-1     │  │ worker-2     │
                       │ (4 conc.)    │  │ (4 conc.)    │
                       └───┬──────────┘  └───┬──────────┘
                           │                 │
                           ▼                 ▼
                   actual task (tasks.run_prompt, etc.)
```

### Key Design Decisions

1. **Redbeat** is the Celery beat scheduler backend.  It stores beat schedules
   in Redis (not in-memory) so schedules survive restarts.
2. **Dual persistence**: Every schedule lives in ``harness:schedule:{id}``
   (our own store) **AND** in redbeat's Redis entries ``redbeat:hb:sch:{id}``.
   The store is the source of truth; redbeat is synced from it.
3. **dispatch_task** is the "thunk" task: redbeat never calls the real task
   directly.  It calls ``scheduler.dispatch_task(schedule_id=...)`` which
   looks up the entry, checks limits, bumps counters, then dispatches the
   actual target task.  This way you can update task kwargs *between*
   scheduled runs without restarting beat.
4. **Condition events** flow through a Redis list channel that a periodic
   beat task (every 15s via redbeat) polls.

---

## File Map

```
scheduler/
  __init__.py           ← package marker
  models.py             ← ScheduleEntry dataclass, ScheduleType, RunState
  store.py              ← Redis CRUD: create/get/update/delete/list
  tasks.py              ← dispatch_task, condition_checker, trigger_condition
  schemas.py            ← Pydantic request/response models
  service.py            ← CRUD + redbeat sync + NLP helpers + chat handler
  router.py             ← FastAPI endpoints at /schedules
  README.md             ← ← YOU ARE HERE
```

Supporting files:

```
core/
  celery_app.py         ← Celery singleton, redbeat wired in, autodiscovers
                         ←   both tasks/ and scheduler/
  llm.py               <- chat_completion_sync() for worker-side LLM calls
```

---

## REST API Endpoints

All under ``/schedules`` (mounted alongside ``/tasks``, ``/kb``, ``/web``, etc.).

### POST /schedules — Create a new schedule

```json
{
  "name": "Morning briefing",
  "description": "Summarises news each morning",
  "type": "cron",
  "task_name": "tasks.run_prompt",
  "task_kwargs": {
    "prompt": "Give me a 5-bullet morning briefing",
    "system": "You are my personal assistant."
  },
  "cron_expr": "0 8 * * *",
  "max_runs": 365
}
```

Response: same shape as the full schedule JSON (see below).

### GET /schedules — List all schedules

Returns an array of schedule objects:

```json
[
  {
    "id": "a1b2c3d4-...",
    "name": "Morning briefing",
    "description": "Summarises news each morning",
    "type": "cron",
    "task_name": "tasks.run_prompt",
    "task_kwargs": { "prompt": "...", "system": "..." },
    "at": null,
    "cron_expr": "0 8 * * *",
    "interval_seconds": null,
    "condition_event": null,
    "max_runs": 365,
    "run_count": 12,
    "state": "active",
    "created_at": "2025-05-15T06:00:00",
    "last_run_at": "2025-06-05T08:00:00",
    "next_run_at": "2025-06-06T08:00:00"
  }
]
```

### GET /schedules/text — Plain-text summary

Returns a human-readable markdown summary.  Use this for voice/Siri/chat
contexts where raw JSON is hard to read.

### GET /schedules/{id} — Single schedule detail

### PATCH /schedules/{id} — Partial update

Only include the fields you want to change:

```json
{
  "state": "paused"
}
```

Valid state values: ``active``, ``paused``.

To change the cron expression:

```json
{ "cron_expr": "0 9 * * 1-5" }
```

To change max runs:

```json
{ "max_runs": 100 }
```

### DELETE /schedules/{id} — Remove permanently

```
{"ok": true}
```

### POST /schedules/{id}/trigger — Fire immediately

Bypasses the schedule clock and dispatches right now.

```json
{
  "status": "dispatched",
  "task_id": "x1y2z3-...",
  "schedule_id": "a1b2c3d4-..."
}
```

You can then poll ``GET /tasks/{task_id}`` to see the actual task result.

### POST /schedules/condition — Push a condition event

```json
{
  "event_name": "kb_ingestion_done",
  "payload": { "files_added": 12, "collection": "work" }
}
```

All active condition-schedules whose ``condition_event`` matches will fire
(within ~15 seconds).  The payload is merged into the task kwargs.

### POST /schedules/chat — NLP command handler

Accept free-form text describing a schedule command and returns a text
response.  Body:

```json
{
  "command": "pause morning briefing and trigger weekly report"
}
```

Recognised patterns (case-insensitive):

| Text pattern                       | Effect                           |
|---                                  |---                               |
| ``list`` / ``show`` / ``what``      | Returns ``describe_schedules_as_text()`` |
| ``pause <name|id>``                 | Pauses the schedule              |
| ``resume <name|id>``                | Unpauses                         |
| ``delete <name|id>`` / ```remove``   | Deletes                          |
| ``trigger <name|id>`` / ``run now`` | Fires immediately                |

---

## Schedule Types — How to Configure Each

### 1. Onetime

Fire a task once at a specific time.

```json
{
  "name": "Deploy reminder",
  "type": "onetime",
  "task_name": "tasks.run_prompt",
  "task_kwargs": {
    "prompt": "Send me a reminder to review today's deployment.",
    "system": "You are my ops assistant."
  },
  "at": "2025-06-10T09:00:00"
}
```

After it fires once, the schedule auto-expires.

### 2. Cron

Recurring on a standard 5-field cron expression
(``minute hour day-of-month month day-of-week``).

```json
{
  "name": "Morning briefing",
  "type": "cron",
  "task_name": "tasks.run_prompt",
  "task_kwargs": {
    "prompt": "Brief me on top news today",
    "system": "You are my morning briefing assistant."
  },
  "cron_expr": "0 8 * * 1-5",
  "max_runs": 260
}
```

Cron is interpreted in the harness timezone (America/Chicago, UTC-5/6 via DST).

### 3. Interval

Fire every N seconds.

```json
{
  "name": "Watchdog poke",
  "type": "interval",
  "task_name": "tasks.python_executor",
  "task_kwargs": {
    "code": "result_var = \"ping at \" + str(__import__('datetime').datetime.utcnow())"
  },
  "interval_seconds": 300
}
```

### 4. Condition

Fire when a named event is published.

```json
{
  "name": "KB digest on new content",
  "type": "condition",
  "task_name": "tasks.run_prompt",
  "task_kwargs": {
    "prompt": "Summarise the latest additions to the knowledge base."
  },
  "condition_event": "kb_ingestion_done"
}
```

Trigger it from any harness code or via the API:

```python
# Programmatic
from scheduler.tasks import trigger_condition
trigger_condition.delay("kb_ingestion_done", {"files_added": 5})

# REST
# POST /schedules/condition
# {"event_name": "kb_ingestion_done", "payload": {"files_added": 5}}
```

The ``condition_checker`` beat task polls every ~15 seconds.

---

## How Scheduling Works Internally

### Step-by-step for a cron schedule:

1. Admin creates schedule via API → ``scheduler/store.create(entry)``
2. Service layer calls ``scheduler/service.sync_redbeat(entry)`` which writes
   a beat schedule entry into redbeat's Redis storage: task = ``scheduler.dispatch_task``,
   kwargs = ``{"schedule_id": "abc-123"}``
3. ``ai-harness-beat`` container runs Celery Beat with redbeat.  Every beat
   tick (default 5s max-interval) it checks redbeat entries.
4. When the cron time hits, beat dispatches ``scheduler.dispatch_task(
   schedule_id="abc-123")`` to the worker pool.
5. ``dispatch_task`` looks up the entry from our store, checks state / run
   count / max_runs limits, bumps ``run_count``, calls the actual target
   task (e.g. ``tasks.run_prompt``), and returns the celery task ID.
6. If it was an onetime schedule, it transitions the entry to ``expired``.

### Step-by-step for a condition schedule:

1. Schedule created with ``type: "condition"``, ``condition_event:
   "kb_ingestion_done"``.
2. When ingress finishes, the KB watcher (or any harness code) calls
   ``trigger_condition.delay("kb_ingestion_done", {...})`` or hits
   ``POST /schedules/condition``.
3. The condition event is pushed onto a Redis list.
4. Every ~15s, the ``condition_checker`` beat task pops events from the
   list and dispatches all matching active condition schedules.

---

## Adding Condition Triggers in Existing Code

From any harness module (e.g., the KB watcher finishing an ingestion):

```python
from scheduler.tasks import trigger_condition

# In your ingestion code, when done:
trigger_condition.delay(
    event_name="kb_ingestion_done",
    payload={"files_processed": 42, "collection": "family"},
)
```

The payload dict is merged into ``task_kwargs`` when the condition schedule
fires, so your target task can accept these extra kwargs.

---

## Programmatic API (Python)

If you are running inside the harness container or have it as a dependency:

```python
from scheduler.service import create_schedule, list_schedules, get_schedule
from scheduler.service import update_schedule, delete_schedule, manual_trigger
from scheduler.schemas import CreateScheduleRequest
from scheduler.tasks import trigger_condition

# Create
resp = create_schedule(CreateScheduleRequest(
    name="Hello scheduler",
    type="onetime",
    task_name="tasks.run_prompt",
    task_kwargs={"prompt": "Say hello!"},
    at="2025-06-10T12:00:00",
))

# List
all_sched = list_schedules()

# Update state
from scheduler.schemas import UpdateScheduleRequest
update_schedule(resp.id, UpdateScheduleRequest(state="paused"))

# Manual trigger
manual_trigger(resp.id)

# Fire condition
trigger_condition.delay("my_event", {"x": 1})
```

---

## Extending — Adding Your Own Task to a Schedule

Any `@celery.task` registered in the harness can be the target of a schedule.
The only requirement is that the task name matches ``task_name`` in the schedule.

```python
# In tasks/tasks.py:
from core.celery_app import celery

@celery.task(bind=True, name="tasks.generate_weekly_report")
def generate_weekly_report(self):
    # heavy work ...
    return {"report_url": "/s3/weekly/2025-23.pdf"}
```

Then schedule it:

```json
POST /schedules {
  "name": "Weekly PDF report",
  "type": "cron",
  "task_name": "tasks.generate_weekly_report",
  "task_kwargs": {},
  "cron_expr": "0 6 * * 0"
}
```

---

## Deployment

The scheduler needs **three** containers to be running:

| Container           | Role                                        |
|---                  |---                                          |
| ``ai-harness``      | Web server — exposes the REST API          |
| ``ai-harness-beat`` | Celery Beat + redbeat — drives schedules    |
| ``ai-harness-worker-1`` / ``worker-2`` | Workers — execute dispatched tasks  |

Rebuild + restart everything after code changes:

```bash
cd /home/chuck/homelab
docker compose -f compose/compose.ai-core.yml -f compose/compose.ai-harness.yml up -d --build
```

### Containers in compose.ai-harness.yml

```yml
home-ai-harness        — uvicorn web server (FastAPI)
home-ai-harness-worker-1 — Celery worker (4 concurrency)
home-ai-harness-worker-2 — Celery worker (4 concurrency)
home-ai-harness-beat   — Celery beat + redbeat (max-interval=5)
home-ai-kb-watcher     — KB file watcher (existing)
```

---

## Troubleshooting

| Symptom                            | Check                                       |
|---                                  |---                                          |
| Schedule created but never fires   | Is ``ai-harness-beat`` running? ``docker ps`` |
| Fired but worker fails             | Check worker logs ``docker logs ai-harness-worker-1`` |
| Condition events not picked up     | Condition checker runs every 15s — be patient; verify beat container logs |
| Schedule seems "forgotten""        | Check Redis key exists: ``redis-cli get "harness:schedule:{id}"`` |
| redbeat out of sync                | Restart beat container — it re-reads on startup |
