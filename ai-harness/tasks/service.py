"""Service layer for task queue operations."""

from datetime import datetime, timezone
from typing import Any

from celery.result import AsyncResult

from core.celery_app import celery
from tasks.schemas import TaskResult, TaskStatus


def inspect_task_status(task_id: str) -> TaskResult:
    """Look up a Celery task by ID and return a structured result."""

    result = AsyncResult(task_id, app=celery)

    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    if result.date_created:
        created_at = result.date_created.astimezone(timezone.utc)
    if result.date_started:
        started_at = result.date_started.astimezone(timezone.utc)

    status_map = {
        "PENDING": TaskStatus.PENDING,
        "STARTED": TaskStatus.STARTED,
        "SUCCESS": TaskStatus.SUCCESS,
        "FAILURE": TaskStatus.FAILURE,
        "REVOKED": TaskStatus.FAILURE,
    }

    status = status_map.get(result.status, TaskStatus.PENDING)
    raw_result: Any = None
    error: str | None = None

    if result.status == "SUCCESS":
        raw_result = result.result
        finished_at = (
            datetime.now(timezone.utc)
        )  # Celery doesn't always expose finish time
    elif result.status == "FAILURE":
        error = str(result.result)
        finished_at = datetime.now(timezone.utc)

    return TaskResult(
        task_id=task_id,
        status=status,
        result=raw_result,
        error=error,
        created_at=created_at,
        started_at=started_at,
        finished_at=finished_at,
    )
