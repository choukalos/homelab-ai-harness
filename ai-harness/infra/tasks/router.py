"""FastAPI router for the async task queue.

Endpoints
---------
- POST  /tasks/prompt          — submit an LLM prompt task
- POST  /tasks/chain           — submit a chain of LLM prompts
- POST  /tasks/python          — submit arbitrary Python code
- GET   /tasks/{task_id}       — inspect a task's status / result
- GET   /tasks/workers         — list active workers
"""

from fastapi import APIRouter

from infra.tasks.schemas import (
    ChainTaskRequest,
    PromptTaskRequest,
    PythonExecutorRequest,
    TaskResult,
    WorkerListResponse,
)
from infra.tasks.service import inspect_task_status
from infra.tasks.tasks import run_prompt, run_llm_chain, python_executor
from infra.core.celery_app import celery

router = APIRouter()


# -- Submit a single prompt task ------------------------------------------

@router.post("/prompt", response_model=TaskResult)
def submit_prompt_task(req: PromptTaskRequest):
    """Queue a single LLM prompt and return the task ID immediately."""
    task = run_prompt.delay(
        prompt=req.prompt,
        model=req.model,
        system=req.system,
        max_tokens=req.max_tokens,
    )

    return inspect_task_status(task.id)


# -- Submit a chain of prompts --------------------------------------------

@router.post("/chain", response_model=TaskResult)
def submit_chain_task(req: ChainTaskRequest):
    """Queue a sequential chain of LLM prompts."""
    task = run_llm_chain.delay(
        steps=req.steps,
        model=req.model,
    )

    return inspect_task_status(task.id)


# -- Submit Python code to worker -----------------------------------------

@router.post("/python", response_model=TaskResult)
def submit_python_task(req: PythonExecutorRequest):
    """Queue Python code execution on a worker (trusted input only)."""
    task = python_executor.delay(
        code=req.code,
        globals_dict=req.globals_dict,
        locals_dict=req.locals_dict,
    )

    return inspect_task_status(task.id)


# -- List active workers --------------------------------------------------
# NOTE: must be defined BEFORE /{task_id} so FastAPI matches it first

@router.get("/workers", response_model=WorkerListResponse)
def list_workers():
    """Return status of all connected Celery workers."""
    inspector = celery.control.inspect()
    active = inspector.active() or {}
    stats = inspector.stats() or {}

    workers = []
    for worker_name, worker_info in stats.items():
        workers.append({
            "worker": worker_name,
            "hostname": worker_info.get("hostname", "unknown"),
            "pid": worker_info.get("pid", 0),
            "clock": worker_info.get("clock", 0),
            "active": active.get(worker_name, []),
            "processed": worker_info.get("total", {}).get("processed", 0),
        })

    return {"workers": workers}


# -- Inspect a task status ------------------------------------------------

@router.get("/{task_id}", response_model=TaskResult)
def get_task_status(task_id: str):
    """Inspect the status and result of a queued task."""
    result = inspect_task_status(task_id)
    return result
