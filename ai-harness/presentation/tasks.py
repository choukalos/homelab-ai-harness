"""Presentation module — Celery tasks for async generation.

Session 3: implement the actual Celery task for Siri's fire-and-forget flow.

Tasks
-----
presentation.generate_presentation — full pipeline run in a Celery worker.
    Accepts the same fields as PresentationRequest.  The worker runs the
    complete research → outline → Presenton → save pipeline and returns
    a dict matching PresentationResponse fields.  Siri dispatches this
    via POST /presentation/generate/async and returns immediately.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from core.celery_app import celery
from presentation.schemas import PresentationMetadata, PresentationRequest

logger = logging.getLogger(__name__)


def register():
    """No extra imports needed — decorators are evaluated at module load time.

    celery_app.py already imports this module so the task is registered.
    This function exists for API compatibility with other task modules.
    """
    pass


@celery.task(
    bind=True,
    name="presentation.generate_presentation",
    track_started=True,
    acks_late=True,
)
def generate_presentation_task(
    self,
    title: str,
    content: str,
    *,
    outline: str | None = None,
    research: bool = False,
    kb_search: bool = False,
    n_slides: int = 8,
    template: str = "general",
    tone: str = "default",
    verbosity: str = "standard",
    language: str = "English",
    export_as: str = "pptx",
    version: int | None = None,
    parent_id: str | None = None,
    instructions: str | None = None,
    include_table_of_contents: bool = False,
    include_title_slide: bool = True,
) -> dict[str, Any]:
    """Run the full presentation generation pipeline in a Celery worker.

    Same logic as ``generate_presentation_sync`` in service.py, but runs
    in the background so Siri / async callers get immediate task_id.
    """
    task_id = self.request.id
    logger.info("presentation.generate_presentation[%s] — title=%s", task_id, title)

    try:
        # Build the request model from kwargs
        req = PresentationRequest(
            title=title,
            content=content,
            outline=outline,
            research=research,
            kb_search=kb_search,
            n_slides=n_slides,
            template=template,
            tone=tone,
            verbosity=verbosity,
            language=language,
            export_as=export_as,
            version=version,
            parent_id=parent_id,
            instructions=instructions,
            include_table_of_contents=include_table_of_contents,
            include_title_slide=include_title_slide,
        )

        # Run the sync pipeline (imports here to avoid circular deps at import time)
        from presentation.service import (
            PresentonClient,
            generate_presentation_sync,
        )

        client = PresentonClient()
        try:
            resp = generate_presentation_sync(client, req)
        finally:
            client.close()

        result = resp.model_dump()
        result["task_id"] = task_id
        result["status"] = "completed"
        logger.info(
            "presentation.generate_presentation[%s] — completed: id=%s",
            task_id,
            result.get("presentation_id"),
        )
        return result

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error(
            "presentation.generate_presentation[%s] — failed: %s\n%s",
            task_id,
            exc,
            tb,
        )
        return {
            "task_id": task_id,
            "status": "failed",
            "error": f"{exc}\n{tb}",
        }
