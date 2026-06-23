# Task Queue (Celery + Redis)

> How to use the Celery-backed async task queue built into the AI harness.
> Read this whenever you need to queue work or add new task types.

---

## Architecture at a Glance

```
Client (OpenWebUI / curl / Python)
        │
        │  POST /tasks/...
        ▼
┌──────────────────────┐
│   ai-harness (FastAPI)│  ← serialises the request, dispatches to Celery,
│   app:app :8090       │     returns task_id + initial status immediately
└──────────┬───────────┘
           │  redis://ai-redis:6379/0
           ▼
┌────────────────────────────┐
│  Celery Broker + ResultDB  │  ← a single Redis instance doing double duty
│  (ai-redis container)      │
└────────────┬───────────────┘
             │
    ┌────────┴────────┐
    ▼                 ▼
┌──────────┐     ┌──────────┐
│ worker-1 │     │ worker-2 │
│ (4 conc.)│     │ (4 conc.)│
└──────────┘     └──────────┘
```

- **Broker & Result Backend**: both point to `ai-redis` (Redis 7 Alpine).  No
  extra infrastructure needed.
- **2 workers**, each with **4 concurrent threads**, giving 8 parallel task
  slots.
- **Result storage**: every task result is stored in Redis under its UUID.

---

## File Map

```
core/
  celery_app.py         ← Celery singleton (broker, backend, config, autodiscover)
  llm.py               ← chat_completion_sync() — sync LLM call for workers
tasks/
  __init__.py           ← marks the package for autodiscover
  tasks.py              ← @celery.task implementations (register here)
  router.py             ← FastAPI endpoints (submit, inspect, workers)
  schemas.py            ← Pydantic request / response models
  service.py            ← inspect_task_status(), other shared logic
```

---

## API Endpoints (mounted at `/tasks`)

### POST /tasks/prompt — Queue a single LLM call

```json
{
  "prompt": "Explain quantum entanglement in 3 sentences",
  "model": "gemma-moe",                     // optional
  "system": "You are a physics tutor.",     // optional
  "max_tokens": 200                         // optional
}
```

### POST /tasks/chain — Queue an ordered chain of prompts

Each step's output is injected into the next step via `{{previous}}`.

```json
{
  "steps": [
    { "prompt": "List 5 causes of climate change.", "system": "Be concise." },
    { "prompt": "Rank these by severity: {{previous}} and explain why." }
  ],
  "model": "gemma-moe"  // optional
}
```

### POST /tasks/python — Queue Python code execution

> ⚠️ Code runs inside the **worker process**.  Only trust inputs you control.

```json
{
  "code": "result_var = {\"answer\": 42}",
  "locals_dict": { "x": 10 }
}
```

### GET /tasks/{task_id} — Inspect a task

Returns current status (`PENDING`, `STARTED`, `SUCCESS`, `FAILURE`), result,
timestamps, and any error.

### GET /tasks/workers — Worker health + stats

Returns hostname, PID, clock, active tasks, and total processed count for
each connected worker.

---

## Common Response Shape (TaskResult)

```json
{
  "task_id": "a1b2c3d4-...",
  "status": "PENDING",            // PENDING | STARTED | SUCCESS | FAILURE
  "result": null,                // populated on SUCCESS
  "error": null,                 // populated on FAILURE
  "created_at": "2025-06-06T00:00:00Z",
  "started_at": null,
  "finished_at": null
}
```

On `SUCCESS`, `result` contains the dict returned by the task function
(e.g. `{"result": "...LLM output...", "model": "gemma-moe", "error": null}`).

---

## Adding a New Task Type

### Step 1 — Register the task function

Add a new `@celery.task` in **`tasks/tasks.py`**:

```python
from core.celery_app import celery

@celery.task(bind=True, name="tasks.my_task", track_started=True)
def my_task(self, input_a: str, input_b: int = 5):
    # ... do work ...
    return { "output": f"{input_a} x {input_b}" }
```

- Always `bind=True` so you can access `self.request.id`.
- Use the `tasks.` prefix for the name.
- Return a plain dict (JSON-serialisable).

### Step 2 — (Optional) Add a FastAPI submission endpoint

In **`tasks/schemas.py`** add a Pydantic model:

```python
class MyTaskRequest(BaseModel):
    input_a: str
    input_b: int = Field(5, ge=1)
```

In **`tasks/router.py`** add the POST handler:

```python
from tasks.tasks import my_task

@router.post("/my-endpoint", response_model=TaskResult)
def submit_my_task(req: MyTaskRequest):
    task = my_task.delay(input_a=req.input_a, input_b=req.input_b)
    return inspect_task_status(task.id)
```

### Step 3 — Rebuild & restart

```bash
docker compose -f compose/compose.ai-core.yml -f compose/compose.ai-harness.yml \
  build home-ai-harness
docker compose -f compose/compose.ai-core.yml -f compose/compose.ai-harness.yml \
  up -d
```

Or just:

```bash
docker compose -f compose/compose.ai-core.yml -f compose/compose.ai-harness.yml up -d --build
```

---

## Calling from Programmatic Code (Python)

You do **not** need the HTTP API.  Import the task directly from any Python
context that has the harness environment available (e.g. another container,
a notebook, a cron script):

```python
from tasks.tasks import run_prompt

async_result = run_prompt.delay(
    prompt="What is the capital of France?",
    model="gemma-moe",
)

# later ...
result_dict = async_result.get(timeout=60)  # blocks until done
print(result_dict["result"])
```

---

## Key Celery Configuration

Set in `core/celery_app.py`:

| Setting | Value | Why |
|---|---|---|
| `task_serializer` | `json` | Safe, inspectable payloads |
| `task_acks_late` | `True` | Redeliver if worker crashes mid-task |
| `worker_prefetch_multiplier` | `1` | Fair round-robin across workers |
| `task_time_limit` | 1800 s | Hard kill after 30 min |
| `task_soft_time_limit` | 1500 s | Raise SoftTimeLimit at 25 min |
| `broker_connection_retry_on_startup` | `True` | Survive Redis restarts |

---

## Scaling

To add more workers, clone `home-ai-harness-worker-1` in `compose.ai-harness.yml`
and bump the index.  Each worker draws from the same Redis queue.  To adjust
per-worker concurrency, change `--concurrency=N` in the command line.
