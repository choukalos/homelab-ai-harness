"""
FastAPI router for the demo-workflow module (Deep Agents with MySQL checkpointing).

Endpoints:
  POST   /run                    — Sync demo creation
  POST   /run/stream             — SSE streaming demo creation
  GET    /jobs                   — List recent demo jobs (from metadata on disk)
  GET    /jobs/{thread_id}       — Get job status + output
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
from demo_workflow.schemas import DemoCreateRequest, DemoCreateResponse
from demo_workflow.service import run_demo, get_deep_agent

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
            # Build lightweight metadata on the fly
            filename = entry.name
            # Strip the hash suffix for the title if present (e.g. foo-96d09c.html -> foo)
            name_base = filename.rsplit("-", 1)[0] if "-" in filename[:-5] else filename[:-5]
            # Humanize: replace hyphens with spaces, title case
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


def _serialize_update(update):
    """Convert update dict to JSON-serializable form, handling non-serializable types."""
    if isinstance(update, dict):
        result = {}
        for key, value in update.items():
            if hasattr(value, "model_dump"):
                result[key] = [v.model_dump() for v in value] if isinstance(value, list) else value.model_dump()
            elif hasattr(value, "dict"):
                result[key] = [v.dict() for v in value] if isinstance(value, list) else value.dict()
            else:
                result[key] = value
        return result
    return update


# ──── Endpoints ──────


@router.post("/run", response_model=DemoCreateResponse, status_code=201)
async def run_demo_endpoint(
    req: DemoCreateRequest,
    _: None = Depends(require_harness_auth),
) -> DemoCreateResponse:
    """Run the demo creation agent synchronously.

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
    """Stream the demo creation output as the agent works.

    Yields SSE events as the agent processes tool calls and generates text.
    Useful for live UI updates (e.g. OpenWebUI) while the agent is building.
    """
    thread_id = req.thread_id or str(uuid.uuid4())

    from langchain_core.messages import HumanMessage

    agent = get_deep_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    input_state = {
        "messages": [HumanMessage(content=req.prompt)],
    }

    async def _stream():
        yield json.dumps({
            "event": "start",
            "thread_id": thread_id,
            "prompt": req.prompt,
            "title": req.title,
        }) + "\n"

        try:
            async for event in agent.astream(input_state, config, stream_mode="updates"):
                # event is a tuple of (namespace, update_dict)
                if isinstance(event, tuple):
                    ns, update = event
                    yield json.dumps({
                        "event": "update",
                        "namespace": ns,
                        "update": _serialize_update(update),
                    }) + "\n"
                else:
                    yield json.dumps({
                        "event": "update",
                        "namespace": "default",
                        "update": _serialize_update(event),
                    }) + "\n"

            yield json.dumps({
                "event": "done",
                "thread_id": thread_id,
            }) + "\n"

        except Exception as e:
            logger.exception("Demo stream error: %s", e)
            yield json.dumps({
                "event": "error",
                "message": str(e),
            }) + "\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


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


@router.post("/jobs/{thread_id}/cancel")
def cancel_job(
    thread_id: str,
    _: None = Depends(require_harness_auth),
) -> dict:
    """Cancel a running demo creation job.

    With direct agent invocation, cancellation is best-effort.
    """
    # Check if it's already completed
    meta = _find_demo_metadata(thread_id)
    if meta:
        return {"status": "already_completed", "thread_id": thread_id}

    # Otherwise signal cancellation
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
