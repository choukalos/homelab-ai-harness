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

from infra.core.celery_app import celery
from creative.presentation.schemas import PresentationMetadata, PresentationRequest

logger = logging.getLogger(__name__)


def register():
    """No extra imports needed.

    celery_app.py already imports this module so the tasks are registered.
    This function exists for API compatibility with other task modules.
    """
    pass


@celery.task(
    bind=True,
    name="presentation.update_presentation",
    track_started=True,
    acks_late=True,
)
def update_presentation_task(
    self,
    presentation_id: str,
    *,
    title: str | None = None,
    content: str | None = None,
    outline: str | None = None,
    research: bool | None = None,
    kb_search: bool | None = None,
    n_slides: int | None = None,
    template: str | None = None,
    tone: str | None = None,
    verbosity: str | None = None,
    language: str | None = None,
    export_as: str | None = None,
    instructions: str | None = None,
    include_table_of_contents: bool | None = None,
    include_title_slide: bool | None = None,
) -> dict[str, Any]:
    """Run a presentation update pipeline in a Celery worker.

    Uses Presenton's /generate-async endpoint + polling so the HTTP
    connection is never held open for 10-20 minutes.

    All parameters except presentation_id are optional and mirror
    PresentationUpdateRequest fields. Only provided values override
    the parent presentation's values.
    """
    task_id = self.request.id
    logger.info("presentation.update_presentation[%s] — presentation_id=%s", task_id, presentation_id)

    try:
        # Build the update request model from kwargs
        from creative.presentation.schemas import PresentationUpdateRequest

        update_kwargs = {}
        if title is not None:
            update_kwargs["title"] = title
        if content is not None:
            update_kwargs["content"] = content
        if outline is not None:
            update_kwargs["outline"] = outline
        if research is not None:
            update_kwargs["research"] = research
        if kb_search is not None:
            update_kwargs["kb_search"] = kb_search
        if n_slides is not None:
            update_kwargs["n_slides"] = n_slides
        if template is not None:
            update_kwargs["template"] = template
        if tone is not None:
            update_kwargs["tone"] = tone
        if verbosity is not None:
            update_kwargs["verbosity"] = verbosity
        if language is not None:
            update_kwargs["language"] = language
        if export_as is not None:
            update_kwargs["export_as"] = export_as
        if instructions is not None:
            update_kwargs["instructions"] = instructions
        if include_table_of_contents is not None:
            update_kwargs["include_table_of_contents"] = include_table_of_contents
        if include_title_slide is not None:
            update_kwargs["include_title_slide"] = include_title_slide

        update = PresentationUpdateRequest(**update_kwargs)

        from creative.presentation.service import (
            PresentonClient,
            regenerate_presentation,
        )

        client = PresentonClient()
        try:
            self.update_state(
                state="started",
                meta={"presentation_id": presentation_id},
            )
            resp = regenerate_presentation(
                client, presentation_id, update, use_async=True,
            )
        finally:
            client.close()

        result = resp.model_dump()
        # Include the effective generation params from task kwargs for verification
        logger.info(
            "presentation.update_presentation[%s] — task kwargs: %s",
            task_id, self.request.kwargs,
        )
        for field in ["n_slides", "template", "tone", "verbosity", "language", "export_as"]:
            val = self.request.kwargs.get(field)
            if val is not None:
                result[field] = val
        result["task_id"] = task_id
        result["status"] = "completed"
        self.update_state(state="success", meta=result)
        logger.info(
            "presentation.update_presentation[%s] — completed: id=%s, extra_fields=%s",
            task_id,
            result.get("presentation_id"),
            {f: result.get(f) for f in ["n_slides", "template", "tone"] if f in result},
        )
        return result

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error(
            "presentation.update_presentation[%s] — failed: %s\n%s",
            task_id,
            exc,
            tb,
        )
        self.update_state(state="failure", meta={"error": str(exc)})
        return {
            "task_id": task_id,
            "status": "failed",
            "error": f"{exc}\n{tb}",
        }


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

    Uses Presenton's /generate-async endpoint + polling so the HTTP
    connection is never held open for 10-20 minutes.
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

        # Run the pipeline using async Presenton endpoint (so we don't hold
        # a single HTTP connection open for 10-20 min and kill the worker)
        from creative.presentation.service import (
            PresentonClient,
            generate_presentation_for_worker,
        )

        client = PresentonClient()
        try:
            self.update_state(state="started", meta={"title": title})
            resp = generate_presentation_for_worker(client, req)
        finally:
            client.close()

        result = resp.model_dump()
        # Include the effective generation params from task kwargs for verification
        for field in ["n_slides", "template", "tone", "verbosity", "language", "export_as"]:
            val = self.request.kwargs.get(field)
            if val is not None:
                result[field] = val
        result["task_id"] = task_id
        result["status"] = "completed"
        self.update_state(state="success", meta=result)
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
        self.update_state(state="failure", meta={"error": str(exc)})
        return {
            "task_id": task_id,
            "status": "failed",
            "error": f"{exc}\n{tb}",
        }
