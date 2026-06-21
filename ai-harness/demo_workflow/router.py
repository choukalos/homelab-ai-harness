"""
FastAPI router for the demo-workflow module (Deep Agents with MySQL checkpointing).

Endpoints:
  POST   /run                    — Sync demo creation (agent.ainvoke)
  POST   /run/async              — Async demo creation via Celery (fire-and-forget)
  POST   /run/stream             — SSE streaming (agent.astream)
  GET    /jobs                   — List recent demo jobs (from metadata on disk)
  GET    /jobs/{thread_id}       — Get job status + output
  GET    /jobs/async/{task_id}/status — Get Celery task status
  GET    /jobs/{thread_id}/checkpoint — Get checkpoint status (MySQL)
  POST   /jobs/{thread_id}/resume   — Resume from checkpoint (MySQL auto-resume)
  DELETE /jobs/{thread_id}/checkpoint — Remove a checkpoint
  POST   /jobs/{thread_id}/cancel — Cancel a running job (best-effort)
  GET    /                       — List all completed demos (metadata index)
  GET    /search                 — Search demos by query
  GET    /{slug}                 — Get a single demo's metadata
  GET    /{slug}/html            — Serve the final HTML file
"""

from __future__ import annotations

import json
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from core.config import MEDIA_OUTPUT_DIR, INTERNAL_BASE_URL, PUBLIC_BASE_URL
from core.security import require_harness_auth
from demo_workflow.schemas import (
    AsyncTaskResponse,
    AsyncTaskStatus,
    DemoCreateRequest,
    DemoCreateResponse,
)
from demo_workflow.service import (
    run_demo,
    resume_demo,
    get_checkpoint_status,
    remove_checkpoint,
    _run_demo_with_events,
)

logger = logging.getLogger("demo_workflow.router")

router = APIRouter(tags=["demo-workflow"])


# ──── Helpers ──────

def _find_demo_metadata(slug: str) -> dict:
    """Find metadata.json for a given demo slug."""
    demo_root = Path(MEDIA_OUTPUT_DIR) / "demos" / slug
    meta_file = demo_root / "metadata.json"
    if meta_file.exists():
        return json.loads(meta_file.read_text())
    return {}


def _list_all_demos() -> list[dict]:
    """Scan the demos directory for both:
    - Subdirectories with metadata.json (workflow/deep-agent demos)
    - Flat .html files (simple one-click demos)
    """
    demos_root = Path(MEDIA_OUTPUT_DIR) / "demos"
    if not demos_root.exists():
        return []

    demos = []

    # 1. Subdirectories with metadata.json (workflow demos)
    for entry in sorted(demos_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if entry.is_dir():
            meta_file = entry / "metadata.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    demos.append(meta)
                except (json.JSONDecodeError, ValueError):
                    continue
        elif entry.is_file() and entry.suffix == ".html":
            # 2. Flat .html files (simple one-click demos)
            filename = entry.name
            name_base = filename.rsplit("-", 1)[0] if "-" in filename[:-5] else filename[:-5]
            title = name_base.replace("-", " ").title()
            slug = name_base.replace(" ", "-").lower()
            demos.append({
                "title": title,
                "slug": slug,
                "description": f"One-click demo: {title}",
                "tags": ["simple"],
                "filename": filename,
                "local_url": f"{INTERNAL_BASE_URL.rstrip('/')}/media/files/demos/{filename}",
                "public_url": f"{PUBLIC_BASE_URL.rstrip('/')}/media/files/demos/{filename}",
                "created_at": datetime.fromtimestamp(entry.stat().st_mtime).isoformat(),
            })

    return demos


# ──── Endpoints ──────


@router.post("/run", response_model=DemoCreateResponse, status_code=201)
async def run_demo_endpoint(
    req: DemoCreateRequest,
    _: None = Depends(require_harness_auth),
) -> DemoCreateResponse:
    """Run the demo creation agent synchronously.

    Invokes the deep agent with the user's prompt. The agent follows
    DEMO_WORKFLOW_INSTRUCTIONS to research, design, build, verify, and
    save the demo. MySQL checkpointing auto-persists after each step.

    Body::
        { "prompt": "Build a ...", "title": "My Demo" }

    Returns::
        { "thread_id": "...", "title": "...", "slug": "...",
          "status": "completed", "html_path": "..." }
    """
    return await run_demo(req)


@router.post("/run/stream")
async def run_demo_stream(
    req: DemoCreateRequest,
    _: None = Depends(require_harness_auth),
) -> StreamingResponse:
    """Stream the demo creation output via agent.astream().

    Uses the deep agent's astream() for true real-time agent events:
    - pipeline_start: Agent begins the demo build
    - phase_progress: Tool calls, intermediate progress
    - phase_complete: AI responses, tool results
    - pipeline_complete: Final result with metadata
    - error: Unrecoverable errors
    """
    thread_id = req.thread_id or str(uuid.uuid4())

    async def _stream():
        try:
            async for event in _run_demo_with_events(req):
                payload = event.model_dump(mode="json", exclude_none=True)
                yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            logger.exception("Demo stream error: %s", e)
            error_payload = {"event_type": "error", "data": {"error": str(e)}}
            yield f"data: {json.dumps(error_payload)}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.post("/run/async", response_model=AsyncTaskResponse, status_code=202)
def run_demo_async(
    req: DemoCreateRequest,
    _: None = Depends(require_harness_auth),
) -> AsyncTaskResponse:
    """
    Async demo generation via Celery (fire-and-forget).

    Dispatches the full generation pipeline to a Celery worker and returns
    immediately with a task_id. Check status via GET /jobs/async/{task_id}/status.
    Designed for Siri's voice flow where the user can't wait 2-5 minutes.
    """
    # Import lazily to avoid circular deps at import time
    from demo_workflow.tasks import generate_demo_task

    # Dispatch to Celery
    async_result = generate_demo_task.apply_async(
        kwargs={
            "title": req.title or "",
            "prompt": req.prompt,
            "model": req.model,
            "thread_id": req.thread_id,
        },
    )

    logger.info("Async demo task dispatched: task_id=%s, title=%s",
                async_result.id, req.title)

    return AsyncTaskResponse(
        task_id=async_result.id,
        title=req.title or "Demo",
        status="pending",
        message=f"Demo generation started. Check /jobs/async/{async_result.id}/status for status.",
    )


@router.get("/jobs/async/{task_id}/status", response_model=AsyncTaskStatus)
def get_async_task_status(
    task_id: str,
    _: None = Depends(require_harness_auth),
) -> AsyncTaskStatus:
    """
    Get the status of an async demo generation task.

    Returns the Celery task status and result (if completed).
    """
    # Import lazily to avoid circular deps at import time
    from celery.result import AsyncResult
    from core.celery_app import celery

    result = AsyncResult(task_id, app=celery)

    return AsyncTaskStatus(
        task_id=task_id,
        status=result.state,
        result=result.result if result.ready() else {},
    )


@router.get("/jobs")
def list_jobs(
    limit: int = Query(default=20, ge=1, le=200),
    _: None = Depends(require_harness_auth),
) -> dict:
    """List recent demo creation jobs from the completed demos directory."""
    demos = _list_all_demos()

    jobs = []
    for d in demos[:limit]:
        jobs.append({
            "thread_id": d.get("slug", ""),
            "status": "completed",
            "title": d.get("title", "?"),
            "slug": d.get("slug", ""),
            "created_at": d.get("created_at"),
        })

    return {"jobs": jobs, "total": len(jobs)}


@router.get("/jobs/{thread_id}")
def get_job(
    thread_id: str,
    _: None = Depends(require_harness_auth),
) -> dict:
    """Get job status and output for a given thread ID.

    Looks up by slug in the demos directory.
    """
    meta = _find_demo_metadata(thread_id)
    if meta:
        return {
            "thread_id": thread_id,
            "status": "completed",
            "title": meta.get("title", ""),
            "slug": meta.get("slug", ""),
            "metadata": meta,
        }

    raise HTTPException(status_code=404, detail=f"Job '{thread_id}' not found")


@router.get("/jobs/{thread_id}/checkpoint")
def get_checkpoint(
    thread_id: str,
    _: None = Depends(require_harness_auth),
) -> dict:
    """Get the checkpoint status for a given thread ID.

    Queries the MySQL checkpointer to see if a thread has saved state.
    """
    status = get_checkpoint_status(thread_id)
    return status.model_dump(mode="json")


@router.post("/jobs/{thread_id}/resume", response_model=DemoCreateResponse)
async def resume_job(
    thread_id: str,
    _: None = Depends(require_harness_auth),
) -> DemoCreateResponse:
    """Resume a demo from a MySQL checkpoint.

    Re-invokes the agent with the same thread_id. The MySQL checkpointer
    auto-resumes from the last persisted state.
    """
    return await resume_demo(thread_id)


@router.delete("/jobs/{thread_id}/checkpoint")
def delete_checkpoint(
    thread_id: str,
    _: None = Depends(require_harness_auth),
) -> dict:
    """Remove a checkpoint for a given thread ID.

    This allows the user to start a fresh build with the same thread_id.
    """
    return remove_checkpoint(thread_id)


@router.post("/jobs/{thread_id}/cancel")
def cancel_job(
    thread_id: str,
    _: None = Depends(require_harness_auth),
) -> dict:
    """Cancel a running demo creation job.

    With direct agent invocation, cancellation is best-effort.
    """
    meta = _find_demo_metadata(thread_id)
    if meta:
        return {"status": "already_completed", "thread_id": thread_id}

    return {"status": "cancelled", "thread_id": thread_id}


@router.get("/")
def list_demos_ep(
    tag: str | None = Query(default=None, description="Filter by tag"),
    limit: int = Query(default=50, ge=1, le=200),
    _: None = Depends(require_harness_auth),
) -> dict:
    """List all completed demos from the metadata index."""
    all_demos = _list_all_demos()

    if tag:
        all_demos = [
            d for d in all_demos
            if tag.lower() in [t.lower() for t in d.get("tags", [])]
        ]

    demos = all_demos[:limit]

    return {
        "demos": demos,
        "total": len(demos),
    }


@router.get("/search")
def search_demos(
    q: str = Query(..., description="Search query (matches title, description, tags)"),
    local_urls: bool = Query(True, description="Use local URLs (true) or public URLs (false)"),
    limit: int = Query(default=20, ge=1, le=100),
    _: None = Depends(require_harness_auth),
) -> dict:
    """Search demos by natural language query."""
    all_demos = _list_all_demos()

    query_lower = q.lower()
    matches = []
    for d in all_demos:
        title = d.get("title", "").lower()
        desc = d.get("description", "").lower()
        tags = " ".join(d.get("tags", [])).lower()
        combined = f"{title} {desc} {tags}"

        if any(term in combined for term in query_lower.split()):
            matches.append(d)

    matches = matches[:limit]

    for m in matches:
        if not local_urls:
            m["url"] = m.get("public_url", m.get("local_url", ""))
        else:
            m["url"] = m.get("local_url", "")

    return {
        "matches": matches,
        "total": len(matches),
    }


@router.get("/{slug}")
def get_demo_metadata(
    slug: str,
    _: None = Depends(require_harness_auth),
) -> dict:
    """Get a single demo's metadata."""
    meta = _find_demo_metadata(slug)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Demo '{slug}' not found")
    return meta


@router.get("/{slug}/html", response_class=HTMLResponse)
def get_demo_html(
    slug: str,
    _: None = Depends(require_harness_auth),
) -> HTMLResponse:
    """Serve the final HTML file for a demo."""
    demo_root = Path(MEDIA_OUTPUT_DIR) / "demos" / slug
    html_file = demo_root / "final_demo.html"

    if not html_file.exists():
        raise HTTPException(status_code=404, detail=f"Demo HTML for '{slug}' not found")

    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))
