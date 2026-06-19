"""Celery application factory + redbeat scheduler for the AI harness.

Two modes of operation
------
1. **Worker** — ``celery -A core.celery_app.celery worker ...``
2. **Beat**   — ``celery beat -A core.celery_app.celery -S redbeat.RedBeatScheduler ...``

The singleton ``celery`` is shared between modes.  Redbeat is wired up so
beat schedules survive restarts without a separate database.
"""

import os

from celery import Celery


def make_celery(
    broker_url: str | None = None,
    backend_url: str | None = None,
) -> Celery:
    """Create and configure a Celery application.

    Both broker and result backend default to the existing ai-redis container
    so no extra infrastructure is needed.
    """
    broker_url = broker_url or os.getenv("REDIS_URL", "redis://ai-redis:6379/0")
    backend_url = backend_url or broker_url  # Redis as result backend by default

    app = Celery(
        "ai-harness",
        broker=broker_url,
        backend=backend_url,
    )

    # --- sensible defaults ---
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="America/Chicago",
        enable_utc=True,
        # Each task has a generous but finite default timeout
        task_time_limit=1800,           # 30 min hard limit
        task_soft_time_limit=1500,      # 25 min soft limit
        task_acks_late=True,            # ack only after task completes
        worker_prefetch_multiplier=1,   # fair dispatch across workers
        broker_connection_retry_on_startup=True,
        # redbeat stores its beat-schedule state under this key prefix in Redis
        redbeat_key_prefix="redbeat:",
    )

    # Wire up redbeat — only if the package is available (beats need it,
    # web/worker processes can live without it).
    try:
        from redbeat import RedBeatScheduler
        app.conf.beat_scheduler = "redbeat.RedBeatScheduler"
    except ImportError:
        pass  # redbeat not installed — fine for web-only containers

    return app


# Module-level singleton so any ``from core.celery_app import celery`` works
celery = make_celery()


# Now that the singleton is fully constructed, import all task modules so that
# @celery.task decorators register against the live app.  These imports are safe
# because `celery` is now a complete object.
import tasks.tasks   # noqa: F401  registers run_prompt, run_llm_chain, python_executor
import scheduler.tasks  # noqa: F401  registers dispatch_task, condition_checker
import presentation.tasks  # noqa: F401  registers generate_presentation
