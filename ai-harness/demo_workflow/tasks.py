"""Demo workflow — Celery task for async generation.

Session 7: implement the Celery task for Siri's fire-and-forget flow.

Tasks
-----
demo_workflow.generate_demo — full pipeline run in a Celery worker.
    Accepts the same fields as DemoCreateRequest.  The worker runs the
    complete research → build → save pipeline using agent.ainvoke().
    Siri dispatches this via POST /demos/run/async and returns immediately.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from core.celery_app import celery
from demo_workflow.service import ensure_checkpointer_tables

logger = logging.getLogger(__name__)


def register():
    """No extra imports needed — decorators are evaluated at module load time."""
    pass


@celery.task(
    bind=True,
    name="demo_workflow.generate_demo",
    track_started=True,
    acks_late=True,
)
def generate_demo_task(
    self,
    title: str,
    prompt: str,
    *,
    model: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Run the full demo generation pipeline in a Celery worker.

    Uses the deep agent with MySQL checkpointing. The task runs
    agent.ainvoke() inside an asyncio event loop so the Celery
    worker (which is sync by default) can handle the async agent.
    """
    task_id = self.request.id
    logger.info("demo_workflow.generate_demo[%s] — title=%s, prompt=%s", task_id, title, prompt[:80])

    try:
        self.update_state(state="started", meta={"title": title, "status": "running"})

        # Run the async agent inside a new event loop (Celery workers are sync)
        async def _run():
            # Ensure checkpoint tables + demos dir exist
            await ensure_checkpointer_tables()

            # Import here to avoid circular deps at module load
            from demo_workflow.schemas import DemoCreateRequest
            from demo_workflow.service import run_demo

            req = DemoCreateRequest(
                prompt=prompt,
                title=title,
                thread_id=thread_id,
            )
            if model:
                os.environ["DEMO_WORKFLOW_MODEL"] = model

            resp = await run_demo(req)
            return resp.model_dump()

        result = asyncio.run(_run())
        result["task_id"] = task_id
        result["status"] = result.get("status", "completed")

        self.update_state(state="success", meta={
            "title": result.get("title", ""),
            "slug": result.get("slug", ""),
            "status": "completed",
        })
        logger.info(
            "demo_workflow.generate_demo[%s] — completed: title=%s, slug=%s",
            task_id, result.get("title"), result.get("slug"),
        )
        return result

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error(
            "demo_workflow.generate_demo[%s] — failed: %s\n%s",
            task_id, exc, tb,
        )
        self.update_state(state="failure", meta={"error": str(exc)})
        return {
            "task_id": task_id,
            "title": title,
            "status": "failed",
            "error": f"{exc}\n{tb}",
        }
