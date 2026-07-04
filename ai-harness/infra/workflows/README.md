# Workflows — Multi-step Workflow Run State Engine

> **Read this file whenever you need to interact with the workflow engine.**
> It documents every capability, API endpoint, integration point, and example
> so you can build and manage multi-step, long-running workflows.

---

## Quick Summary

The workflow engine is a durable, MySQL-backed state store that tracks
**workflows** (multi-step pipeline definitions), **runs** (individual executions),
and **steps** (per-step execution state). It integrates with the existing
Celery task queue so each step can dispatch real work to workers.

### What it tracks per step

| Field                | Description                                     |
|---                    |---                                              |
| `step_id`             | Unique step UUID                                |
| `run_id`              | Parent run UUID                                 |
| `step_index`          | Position in the workflow pipeline               |
| `name`                | Human-readable step name                        |
| `status`              | `pending` / `running` / `success` / `failed` / `skipped` |
| `celery_task_id`      | Celery AsyncResult ID when dispatched            |
| `model`               | LLM model identifier                            |
| `input_payload`       | Merged task kwargs actually sent to the task     |
| `output`              | Structured result from the task                  |
| `error`               | Error message on failure                        |
| `retry_count`          | Number of retries attempted                     |
| `cost`                | Model cost in USD (if reported)                 |
| `input_tokens`        | Tokens consumed for input                       |
| `output_tokens`       | Tokens produced in output                       |
| `artifacts`           | List of produced files / URLs                   |
| `started_at`          | ISO-8601 timestamp when step started             |
| `finished_at`         | ISO-8601 timestamp when step finished            |

---

## Architecture

```
Client (OpenWebUI / curl / Python)
        │
        │  POST /workflows/...
        ▼
┌──────────────────────┐
│   ai-harness (FastAPI)│  ← REST API — create workflows, start runs,
│   app:app :8090       │     transition steps, inspect state
└───┬─────────────┬────┘
    │             │
    ▼             ▼
┌──────────┐  ┌──────────────┐
│  MySQL   │  │  Celery + Redis │
│  (bare)  │  │  (workers)     │
│          │  │                │
│ workflows│  │ Dispatches     │
│ runs     │  │ actual Celery  │
│ steps    │  │ tasks for each │
└──────────┘  │ workflow step  │
              └──────────────┘
```

### Key Design Decisions

1. **MySQL (bare metal)** is the persistence layer.  MySQL already runs
   on the host (`thor.local:3306`) via the `homelab` database and `ai`
   user.  No extra database containers needed.
2. **Three tables**: `workflows` (definitions), `workflow_runs`
   (executions), and `workflow_steps` (per-step state).  Foreign keys
   cascade-delete runs when a workflow is deleted.
3. **Steps are definition-driven**: a workflow definition is stored
   declaratively with ordered steps, dependencies, conditions,
   and retry limits.  Each run clones the definition into live
   step rows with `status=pending`.
4. **Auto-completion**: when all steps reach terminal states
   (`success`, `failed`, `skipped`) the parent run transitions
   automatically to `success` or `failed`.
5. **Works with existing Celery tasks**: each step references a
   Celery task name (`tasks.run_prompt`, `tasks.run_llm_chain`, etc.)
   so no new worker infrastructure is needed.

---

## File Map

```
workflows/
  __init__.py           ← register() — creates tables on app startup
  db.py                 ← MySQL connection, DDL, cursor context manager
  schemas.py            ← Pydantic models + enums
  service.py            ← CRUD + step transitions + completion logic
  router.py             ← FastAPI endpoints at /workflows
  README.md             ← ← YOU ARE HERE
```

Supporting files:

```
core/
  celery_app.py         ← Celery singleton (broker, backend, config)
  llm.py               ← chat_completion_sync() for worker-side LLM calls
tasks/
  tasks.py             ← run_prompt, run_llm_chain, python_executor
scheduler/
  tasks.py             ← dispatch_task, condition_checker
```

---

## REST API Endpoints

All under `/workflows`.

### POST /workflows/ — Create a workflow definition

Define a new multi-step pipeline:

```json
{
  "name": "Research & Summarize",
  "description": "Search the web, summarize findings, then draft a report.",
  "tags": ["research", "summary"],
  "steps": [
    {
      "name": "web-search",
      "description": "Search the web for latest info",
      "task_name": "tasks.run_prompt",
      "task_kwargs": {
        "prompt": "Find the latest trends in AI homelabs",
        "system": "Be thorough but concise."
      },
      "model": "gemma-moe",
      "max_retries": 2
    },
    {
      "name": "summarize",
      "description": "Summarize the research",
      "task_name": "tasks.run_prompt",
      "task_kwargs": {
        "prompt": "Summarize these findings into a report",
        "system": "You are a technical writer."
      },
      "depends_on": ["web-search"],
      "model": "gemma-moe",
      "max_retries": 1
    }
  ]
}
```

Response:

```json
{
  "workflow_id": "a1b2c3d4-...",
  "name": "Research & Summarize",
  "description": "Search the web, summarize findings, then draft a report.",
  "tags": ["research", "summary"],
  "steps": [...],
  "created_at": "2025-06-06T..."
}
```

### GET /workflows/ — List workflow definitions

Optional query params:
- `workflow_id` — filter by ID
- `tags` — comma-separated tag filter (e.g. `tags=research,summary`)
- `limit` / `offset` — pagination (default 50 / 0)

### GET /workflows/{workflow_id} — Single workflow definition

```json
{
  "workflow_id": "a1b2c3d4-...",
  "name": "Research & Summarize",
  "description": "Search the web, summarize findings, then draft a report.",
  "tags": ["research"],
  "steps": [...],
  "created_at": "2025-06-06T...",
  "updated_at": "2025-06-06T..."
}
```

### DELETE /workflows/{workflow_id} — Delete permanently

Cascades to all associated runs and steps.  HTTP 204 on success.

---

### POST /workflows/{workflow_id}/runs — Start a new run

Creates a run with all steps cloned as `pending`.  Optional overrides in body:

```json
{
  "overrides": {
    "steps": [{"name": "summarize", "model": "gpt-4o"}]
  },
  "step_kwargs_overrides": {
    "summarize": {"prompt": "Summarize this for a technical audience"}
  },
  "metadata": {
    "triggered_by": "user-42",
    "run_purpose": "quarterly-review"
  }
}
```

Response:

```json
{
  "run_id": "x1y2z3a4-...",
  "workflow_id": "a1b2c3d4-...",
  "status": "pending",
  "steps": [
    { "name": "web-search", "step_index": 0, "status": "pending", ... },
    { "name": "summarize", "step_index": 1, "status": "pending", ... }
  ],
  "metadata": { ... },
  "started_at": null,
  "finished_at": null
}
```

### GET /workflows/runs — List runs

Optional query params:
- `workflow_id` — filter by parent workflow
- `status` — filter by status (`pending`, `running`, `success`, `failed`, `cancelled`)
- `limit` / `offset` — pagination

### GET /workflows/runs/{run_id} — Full run state

Returns the complete run including all step details, outputs, costs, artifacts.

### PATCH /workflows/runs/{run_id} — Update run status or metadata

```json
{ "status": "cancelled" }
```

---

### Step Transitions — Manual control

#### PATCH /workflows/runs/{run_id}/steps/{step_name} — Transition a step

Supports any field in `StepUpdateRequest`.  Common pattern: mark running,
then mark complete.

```json
{ "status": "running", "celery_task_id": "abc-123" }
```

When all steps reach terminal states (`success` / `failed` / `skipped`),
the parent run is **auto-transitioned** to `success` or `failed`
via `check_run_completion`.

#### POST /workflows/runs/{run_id}/next-step — Peek at next ready step

Returns the next `pending` step whose dependencies are all `success`.
Returns `{"next_step": null}` if no pending steps or run is complete.

#### POST /workflows/runs/{run_id}/complete-step/{step_name} — Convenience: mark success

Quick way to finish a step with optional cost/token tracking:

```
POST /workflows/runs/{run_id}/complete-step/web-search
Query params: output, model, cost, input_tokens, output_tokens, artifacts
```

Example:

```
POST /workflows/runs/{run_id}/complete-step/web-search?model=gemma-moe&cost=0.002&input_tokens=150&output_tokens=500
```

#### POST /workflows/runs/{run_id}/check-completion — Force check

Inspects all steps and transitions the run if all are terminal.

---

## Step Definition Schema

```python
class StepDefinition:
    name: str                    # Human-readable name (also used for PATCHing)
    description: str | None
    task_name: str | None        # Celery task name (e.g. "tasks.run_prompt")
    task_kwargs: dict | None     # Kwargs forwarded to the Celery task
    depends_on: list[str] | None # Other step names that must succeed first
    condition: str | None        # Runtime expression (future: evaluate to skip)
    model: str | None            # LLM model identifier
    max_retries: int             # 0-10 retries on failure
    timeout_seconds: int | None  # Per-step timeout override
```

---

## Workflow Status Lifecycle

```
workflow definition (POST /workflows/)
        │
        ▼
run created                  status: pending
        │
        ▼
first step starts            status: running, current_step set
        │
        ▼
all steps terminal ──┬── any failed? ───yes──→ status: failed
                     │
                     └──────────────────no───→ status: success
```

Step statuses:

```
pending → running → success
                  → failed
                  → skipped  (dependency failed or condition false)
```

---

## Typical Usage Pattern

### Scenario: 3-step research pipeline

```bash
# 1. Create the workflow definition
WF_ID=$(curl -sS -X POST http://thor.local:8090/workflows/ \
  -H "X-API-Key: ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Research Pipeline",
    "tags": ["research"],
    "steps": [
      { "name": "search",     "task_name": "tasks.run_prompt",
        "task_kwargs": { "prompt": "Find top 5 AI homelab trends",
                         "system": "Be thorough." } },
      { "name": "summarize",  "task_name": "tasks.run_prompt",
        "depends_on": ["search"],
        "task_kwargs": { "prompt": "Summarize these findings",
                         "system": "Technical writer." } },
      { "name": "format",     "task_name": "tasks.run_prompt",
        "depends_on": ["summarize"],
        "task_kwargs": { "prompt": "Format as markdown report",
                         "system": "Markdown expert." } }
    ]
  }' | jq -r '.workflow_id')

# 2. Start a run
RUN_ID=$(curl -sS -X POST http://thor.local:8090/workflows/$WF_ID/runs \
  -H "X-API-Key: ${LITELLM_MASTER_KEY}" \
  -H "Content-Type: application/json" \
  | jq -r '.run_id')

# 3. Execute steps one by one
for step in search summarize format; do
  # Dispatch to Celery
  TASK_ID=$(curl -sS -X POST http://thor.local:8090/tasks/prompt \
    -H "X-API-Key: ${LITELLM_MASTER_KEY}" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "...", "system": "..."}' \
    | jq -r '.task_id')

  # Mark step running
  curl -sS -X PATCH http://thor.local:8090/workflows/runs/$RUN_ID/steps/$step \
    -H "X-API-Key: ${LITELLM_MASTER_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"status\": \"running\", \"celery_task_id\": \"$TASK_ID\"}"

  # Wait for task to complete
  until curl -sS http://thor.local:8090/tasks/$TASK_ID \
    -H "X-API-Key: ${LITELLM_MASTER_KEY}" | jq -r '.status' | grep -q SUCCESS; do
    sleep 2
  done

  # Mark step complete
  curl -sS -X POST http://thor.local:8090/workflows/runs/$RUN_ID/complete-step/$step \
    -H "X-API-Key: ${LITELLM_MASTER_KEY}"
done

# 4. Check final run status
curl -sS http://thor.local:8090/workflows/runs/$RUN_ID \
  -H "X-API-Key: ${LITELLM_MASTER_KEY}"
```

---

## Integration with Scheduler

Workflows and the scheduler complement each other.  You can schedule a
workflow via the scheduler by using `tasks.run_llm_chain` or by writing
a custom Celery task that orchestrates workflow runs:

```python
from core.celery_app import celery
from workflows.service import create_run

@celery.task(bind=True, name="tasks.run_workflow")
def run_workflow(self, workflow_id: str):
    """Schedule-friendly wrapper that starts a workflow run."""
    run = create_run(workflow_id)
    # ... execute steps sequentially or via next-step polling ...
    return {"run_id": run.run_id}
```

Then schedule it:

```json
POST /schedules {
  "name": "Weekly research pipeline",
  "type": "cron",
  "task_name": "tasks.run_workflow",
  "task_kwargs": { "workflow_id": "a1b2c3d4-..." },
  "cron_expr": "0 8 * * 1"
}
```

---

## Database Schema

### `workflows` — Pipeline definitions

| Column       | Type         | Notes                         |
|---            |---           |---                            |
| `workflow_id` | CHAR(36)     | PK, UUID4                     |
| `name`        | VARCHAR(255) | Human-readable name           |
| `description` | TEXT         | Free-text description         |
| `tags`        | JSON         | Array of strings              |
| `steps`       | JSON         | Serialized StepDefinition[]   |
| `created_at`  | TIMESTAMP    | Auto                          |
| `updated_at`  | TIMESTAMP    | Auto on update                |

### `workflow_runs` — Execution instances

| Column              | Type         | Notes                               |
|---                  |---           |---                                  |
| `run_id`            | CHAR(36)     | PK, UUID4                           |
| `workflow_id`       | CHAR(36)     | FK → workflows (cascade delete)     |
| `status`            | VARCHAR(20)  | pending / running / success / failed|
| `overrides`         | JSON         | Run-level step overrides            |
| `step_kwargs_overrides` | JSON    | Per-step kwargs overrides           |
| `metadata`          | JSON         | Free-form run metadata              |
| `current_step`      | INT          | Index of step currently executing   |
| `started_at`        | TIMESTAMP    | Set on first step start             |
| `finished_at`       | TIMESTAMP    | Set on completion                   |

### `workflow_steps` — Per-step execution state

| Column            | Type         | Notes                                  |
|---                |---           |---                                     |
| `step_id`         | CHAR(36)     | PK, UUID4                              |
| `run_id`          | CHAR(36)     | FK → workflow_runs (cascade delete)    |
| `step_index`      | INT          | Position in pipeline                   |
| `name`            | VARCHAR(255) | Step name (patch handle)               |
| `status`          | VARCHAR(20)  | pending / running / success / failed / skipped |
| `celery_task_id`  | CHAR(36)     | AsyncResult ID                         |
| `model`           | VARCHAR(128) | LLM model identifier                  |
| `input_payload`   | JSON         | Merged task kwargs sent to task        |
| `output`          | JSON         | Structured result                      |
| `error`           | TEXT         | Error details on failure               |
| `retry_count`     | INT          | Retries attempted (0-10)               |
| `cost`            | DECIMAL(10,6)| Cost in USD                            |
| `input_tokens`    | INT          | Tokens consumed                        |
| `output_tokens`   | INT          | Tokens produced                        |
| `artifacts`       | JSON         | Array of ArtifactRecord                |
| `started_at`      | TIMESTAMP    | Step start time                        |
| `finished_at`     | TIMESTAMP    | Step finish time                       |

---

## Environment Variables

All read from `.env`:

| Variable          | Default                  | Description                |
|---                |---                       |---                         |
| `MYSQL_DB_HOST`   | `host.docker.internal`   | MySQL host                 |
| `MYSQL_DB_PORT`   | `3306`                   | MySQL port                 |
| `AI_DB_USER`      | `root`                   | MySQL user                 |
| `AI_DB_PASS`      | (empty)                  | MySQL password             |
| `AI_DB_NAME`      | `ai_harness`             | Database name              |

---

## Deployment

The workflow engine needs MySQL running (bare metal on the host) and the
harness container restarted:

```bash
cd /home/chuck/homelab
docker compose -f compose/compose.ai-harness.yml up -d --build
```

The harness web server calls `register_workflows(app)` on startup which
creates the three tables if they do not exist.  No manual migration needed.

---

## Troubleshooting

| Symptom                                    | Check                                                     |
|---                                         |---                                                        |
| `Cannot connect to MySQL`                  | Verify `host.docker.internal` resolves from container     |
| `Table 'workflows' doesn't exist`           | Tables auto-create on startup — check app logs for errors |
| Step not transitioning to `success`         | Check all steps are terminal; call `/check-completion`    |
| `Foreign key constraint fails`             | Ensure workflow exists before creating run                |
| Cost/tokens not persisting                 | Pass them via `complete-step` or `PATCH /steps/`          |
