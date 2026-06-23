"""
FastAPI router for the presentation module.

Session 1: basic endpoints for generation, listing, download, and deletion.
Session 2: adds outline generation + research integration.
Session 3: adds async Celery tasks for Siri.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from infra.core.celery_app import celery
from infra.core.security import require_harness_auth
from creative.presentation.schemas import (
    AsyncTaskResponse,
    OutlineRequest,
    OutlineResponse,
    PresentationListResponse,
    PresentationMetadata,
    PresentationRequest,
    PresentationResponse,
    PresentationUpdateRequest,
    TaskStatusResponse,
)
from creative.presentation.service import (
    PresentonClient,
    delete_presentation,
    find_presentations,
    get_presentation,
    generate_outline,
    generate_presentation_sync,
    list_presentations,
    regenerate_presentation,
    _PRESENTATIONS_DIR,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["presentation"])


# -- helper: get a client ---------------------------------------------------

def _get_client() -> PresentonClient:
    """Return a Presenton API client. Each request gets a fresh client."""
    return PresentonClient()


# -- outline generation (Session 2) -----------------------------------------

@router.post("/outline", response_model=OutlineResponse)
def generate_outline_endpoint(
    req: OutlineRequest,
    _: None = Depends(require_harness_auth),
):
    """
    Collaborative outline generation.

    Generates an AI-powered presentation outline from a topic description.
    Optionally includes deep research and/or family KB search for grounding.
    The returned outline can be refined iteratively, then passed to /generate.
    """
    client = _get_client()
    try:
        return generate_outline(client, req)
    except Exception as exc:
        logger.error("Outline generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Outline generation failed: {exc}",
        )
    finally:
        client.close()


# -- generation -------------------------------------------------------------

@router.post("/generate", response_model=PresentationResponse)
def generate(
    req: PresentationRequest,
    _: None = Depends(require_harness_auth),
):
    """
    One-shot presentation generation (synchronous).

    Calls Presenton to generate slides from the provided content or outline.
    The generated file is saved to /data/media/presentations/ and metadata
    is persisted alongside it.

    Timeout: ~5 minutes for large presentations.
    """
    client = _get_client()
    try:
        return generate_presentation_sync(client, req)
    except Exception as exc:
        logger.error("Presentation generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Presentation generation failed: {exc}",
        )
    finally:
        client.close()


# -- async generation (Session 3) -------------------------------------------

@router.post("/generate/async", response_model=AsyncTaskResponse)
def generate_async(
    req: PresentationRequest,
    _: None = Depends(require_harness_auth),
):
    """
    Async presentation generation via Celery (fire-and-forget).

    Dispatches the full generation pipeline to a Celery worker and returns
    immediately with a task_id. Check status via GET /tasks/{task_id}.
    Designed for Siri's voice flow where the user can't wait 3-5 minutes.
    """
    # Import lazily to avoid circular deps at import time
    from creative.presentation.tasks import generate_presentation_task

    # Dispatch to Celery
    async_result = generate_presentation_task.apply_async(
        kwargs={
            "title": req.title,
            "content": req.content,
            "outline": req.outline,
            "research": req.research,
            "kb_search": req.kb_search,
            "n_slides": req.n_slides,
            "template": req.template,
            "tone": req.tone,
            "verbosity": req.verbosity,
            "language": req.language,
            "export_as": req.export_as,
            "version": req.version,
            "parent_id": req.parent_id,
            "instructions": req.instructions,
            "include_table_of_contents": req.include_table_of_contents,
            "include_title_slide": req.include_title_slide,
        },
    )

    logger.info("Async presentation task dispatched: task_id=%s, title=%s",
                async_result.id, req.title)

    return AsyncTaskResponse(
        task_id=async_result.id,
        title=req.title,
        status="submitted",
        message=f"Presentation '{req.title}' generation started. "
                "This typically takes 2-5 minutes. "
                "Check /tasks/{async_result.id} for status.",
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: str,
    _: None = Depends(require_harness_auth),
):
    """
    Check the status of an async presentation generation task.

    Returns the Celery task state. When completed, includes the full
    presentation result. When failed, includes the error message.
    """
    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery)

    if result.state == "PENDING":
        return TaskStatusResponse(
            task_id=task_id,
            status="pending",
        )
    elif result.state == "STARTED":
        return TaskStatusResponse(
            task_id=task_id,
            status="started",
        )
    elif result.state == "SUCCESS":
        inner = result.result
        # When tasks catch exceptions and return a dict with status="failed",
        # Celery still marks the task as SUCCESS. Check the inner status.
        if isinstance(inner, dict) and inner.get("status") == "failed":
            return TaskStatusResponse(
                task_id=task_id,
                status="failed",
                error=inner.get("error"),
            )
        return TaskStatusResponse(
            task_id=task_id,
            status="completed",
            result=inner,
        )
    elif result.state == "FAILURE":
        return TaskStatusResponse(
            task_id=task_id,
            status="failed",
            error=str(result.result),
        )
    else:
        return TaskStatusResponse(
            task_id=task_id,
            status=result.state.lower() if result.state else "unknown",
        )


# -- listing ----------------------------------------------------------------

@router.get("/list", response_model=PresentationListResponse)
def lst(
    _: None = Depends(require_harness_auth),
):
    """List all generated presentations, sorted newest first."""
    presentations = list_presentations()
    return PresentationListResponse(
        presentations=presentations,
        total=len(presentations),
    )


# -- find by title (must be BEFORE /{id} to avoid route conflict) ----------

@router.get("/search", response_model=PresentationListResponse)
def search(
    title: str,
    _: None = Depends(require_harness_auth),
):
    """Find presentations matching a title (fuzzy match)."""
    results = find_presentations(title)
    return PresentationListResponse(
        presentations=results,
        total=len(results),
    )


# -- download (must be BEFORE /{presentation_id} to avoid route conflict) ---

@router.get("/download/{filename}")
def download_file(
    filename: str,
    _: None = Depends(require_harness_auth),
):
    """Download a generated presentation file."""
    filepath = _PRESENTATIONS_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/octet-stream",
    )


# -- get by ID --------------------------------------------------------------

@router.get("/{presentation_id}", response_model=PresentationMetadata)
def get(
    presentation_id: str,
    _: None = Depends(require_harness_auth),
):
    """Get details for a specific presentation by its Presenton ID."""
    meta = get_presentation(presentation_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Presentation not found")
    return meta


# -- regenerate (Session 4) -------------------------------------------------

@router.patch("/{presentation_id}", response_model=PresentationResponse)
def regenerate(
    presentation_id: str,
    update: PresentationUpdateRequest,
    _: None = Depends(require_harness_auth),
):
    """
    Regenerate a presentation with modified parameters (creates a new version).

    All fields in the request are optional. Only the provided fields override
    the parent presentation's values. The parent's title is preserved (unless
    explicitly changed), and the version auto-increments.

    This creates a new presentation linked to the original via parent_id.
    """
    client = _get_client()
    try:
        return regenerate_presentation(client, presentation_id, update)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Presentation regeneration failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Presentation regeneration failed: {exc}",
        )
    finally:
        client.close()


# -- async update (Phase 1) -------------------------------------------------

@router.post("/{presentation_id}/update/async", response_model=AsyncTaskResponse)
def update_async(
    presentation_id: str,
    update: PresentationUpdateRequest,
    _: None = Depends(require_harness_auth),
):
    """
    Async presentation update via Celery (fire-and-forget).

    Creates a new version of the specified presentation with the requested
    changes, dispatched as a background Celery task. Check status via
    GET /tasks/{task_id}.

    All fields in the request are optional. Only the provided fields override
    the parent presentation's values.

    Designed for Siri's voice flow where the user can't wait 3-5 minutes.
    """
    from creative.presentation.tasks import update_presentation_task

    # Resolve the title from the parent for the response
    parent_meta = get_presentation(presentation_id)
    if parent_meta is None:
        raise HTTPException(
            status_code=404,
            detail=f"Presentation {presentation_id} not found",
        )

    title = update.title if update.title is not None else parent_meta.title

    # Convert update to flat kwargs for the Celery task
    update_kwargs = {k: v for k, v in update.model_dump().items() if v is not None}

    async_result = update_presentation_task.apply_async(
        kwargs={
            "presentation_id": presentation_id,
            **update_kwargs,
        },
    )

    logger.info("Async presentation update dispatched: task_id=%s, presentation_id=%s, title=%s",
                async_result.id, presentation_id, title)

    return AsyncTaskResponse(
        task_id=async_result.id,
        title=title,
        status="submitted",
        message=f"Presentation '{title}' update started. "
                "This typically takes 2-5 minutes. "
                "Check /tasks/{async_result.id} for status.",
    )


# -- delete -----------------------------------------------------------------

@router.delete("/{presentation_id}")
def delete(
    presentation_id: str,
    _: None = Depends(require_harness_auth),
):
    """Delete a presentation and its metadata."""
    if not delete_presentation(presentation_id):
        raise HTTPException(status_code=404, detail="Presentation not found")
    return {"detail": "Presentation deleted"}