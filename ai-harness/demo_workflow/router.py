"""
FastAPI router for the one-page clickable demo workflow.

Endpoints:
  POST   /demos/create                 — Start a new demo creation job
  GET    /demos/jobs                   — List recent demo creation jobs
  GET    /demos/jobs/{run_id}          — Get full run state + stage outputs
  POST   /demos/jobs/{run_id}/cancel   — Cancel a running demo creation job
  GET    /demos                        — List all completed demos (metadata index)
  GET    /demos/search                 — Search demos by query
  GET    /demos/{slug}                 — Get a single demo's metadata
  GET    /demos/{slug}/html            — Serve the final HTML file
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from core.config import MEDIA_OUTPUT_DIR, INTERNAL_BASE_URL, PUBLIC_BASE_URL
from core.security import require_harness_auth
from demo_workflow.schemas import DemoCreateRequest, DemoCreateResponse
from workflows.schemas import (
    StepDefinition,
    WorkflowCreateRequest,
    WorkflowRunRequest,
)
from workflows.service import (
    create_run,
    create_workflow,
    get_run,
    list_runs,
    list_workflows,
)
from workflows.schemas import RunUpdateRequest, WorkflowStatus, WorkflowListFilters

logger = logging.getLogger(__name__)

router = APIRouter(tags=["demo-workflow"])

# ────── static workflow steps ─────
# The build loop (stage6) is a single step that iterates all build-sub-steps
# internally.  This avoids needing dynamic step injection in the engine.

_STATIC_STEPS: list[StepDefinition] = [
    StepDefinition(
        name="stage1_parse_request",
        description="Parse user request into structured demo brief",
        task_name="demo_workflow.run_stage",
        task_kwargs={"stage": "parse_request"},
    ),
    StepDefinition(
        name="stage2_kb_lookup",
        description="Query Family KB for relevant prior knowledge",
        task_name="demo_workflow.run_stage",
        task_kwargs={"stage": "kb_lookup"},
        depends_on=["stage1_parse_request"],
    ),
    StepDefinition(
        name="stage3_web_research",
        description="Search web for competitive and design insights",
        task_name="demo_workflow.run_stage",
        task_kwargs={"stage": "web_research"},
        depends_on=["stage2_kb_lookup"],
    ),
    StepDefinition(
        name="stage4_requirements_design",
        description="Synthesize requirements and visual design spec",
        task_name="demo_workflow.run_stage",
        task_kwargs={"stage": "requirements_design"},
        depends_on=["stage3_web_research"],
    ),
    StepDefinition(
        name="stage5_build_plan",
        description="Generate numbered build plan from requirements",
        task_name="demo_workflow.run_stage",
        task_kwargs={"stage": "build_plan"},
        depends_on=["stage4_requirements_design"],
    ),
    StepDefinition(
        name="stage6_build_loop",
        description="Iteratively build the demo HTML step-by-step with validation",
        task_name="demo_workflow.run_stage",
        task_kwargs={"stage": "build_loop"},
        depends_on=["stage5_build_plan"],
    ),
    StepDefinition(
        name="stage7_polish",
        description="Full-pass critique and one fix pass",
        task_name="demo_workflow.run_stage",
        task_kwargs={"stage": "polish"},
        depends_on=["stage6_build_loop"],
    ),
    StepDefinition(
        name="stage8_final_save",
        description="Embed notes, save final HTML, write metadata",
        task_name="demo_workflow.run_stage",
        task_kwargs={"stage": "final_save"},
        depends_on=["stage7_polish"],
    ),
]


def _ensure_workflow() -> str:
    """Create the demo workflow definition if it doesn't already exist."""
    candidates = list_workflows(WorkflowListFilters(limit=50))
    for wf in candidates:
        if wf.get("name") == "demo_creation_pipeline":
            return wf["workflow_id"]

    wf = create_workflow(WorkflowCreateRequest(
        name="demo_creation_pipeline",
        description=(
            "LLM-driven one-page clickable demo generator. "
            "Parses request, checks KB, researches web, creates requirements & design spec, "
            "generates build plan, iterates through build steps with validation, "
            "polishes with self-critique, and saves final HTML with embedded notes."
        ),
        tags=["demo", "html", "automated"],
        steps=_STATIC_STEPS,
    ))
    return wf.workflow_id


def _find_demo_metadata(slug: str) -> dict:
    """Find metadata.json for a given demo slug."""
    demo_root = Path(MEDIA_OUTPUT_DIR) / "demos" / slug
    meta_file = demo_root / "metadata.json"
    if meta_file.exists():
        return json.loads(meta_file.read_text())
    return {}


def _list_all_demos() -> list[dict]:
    """Scan the demos directory for metadata.json files."""
    demos_root = Path(MEDIA_OUTPUT_DIR) / "demos"
    if not demos_root.exists():
        return []

    demos = []
    for slug_dir in sorted(demos_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not slug_dir.is_dir():
            continue
        meta_file = slug_dir / "metadata.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text())
                demos.append(meta)
            except (json.JSONDecodeError, ValueError):
                continue

    return demos


# ──── Endpoints ──────

@router.post("/create", response_model=DemoCreateResponse, status_code=201)
def start_demo(
    req: DemoCreateRequest,
    _: None = Depends(require_harness_auth),
) -> DemoCreateResponse:
    """
    Start a new demo creation job.

    Body::
        { "title": "Pet Adoption App", "prompt": "Build a ...", "model": "" }

    Returns::
        { "run_id": "<uuid>", "workflow_id": "<uuid>",
          "title": "Pet Adoption App", "status": "pending" }
    """
    workflow_id = _ensure_workflow()

    run = create_run(
        workflow_id,
        WorkflowRunRequest(
            metadata={
                "title": req.title,
                "prompt": req.prompt,
                "model_override": req.model,
            },
        ),
    )

    # Dispatch the first step so the pipeline actually starts
    from workflows.service import get_next_pending_step, start_step
    first = get_next_pending_step(run.run_id)
    if first is not None:
        from demo_workflow.tasks import run_stage
        celery_task = run_stage.apply_async(args=[first.input_payload.get("stage", ""), run.run_id])
        start_step(run.run_id, first.name, celery_task_id=celery_task.id)
        logger.info("dispatched first step %s → celery_task_id=%s", first.name, celery_task.id)

    return DemoCreateResponse(
        run_id=run.run_id,
        workflow_id=run.workflow_id,
        title=req.title,
        status=run.status.value,
        steps_count=len(run.steps),
    )


@router.get("/jobs")
def list_jobs(
    status: str | None = Query(default=None, description="Filter by run status"),
    limit: int = Query(default=20, ge=1, le=200),
    _: None = Depends(require_harness_auth),
) -> dict:
    """List recent demo creation jobs."""
    workflow_id = _ensure_workflow()
    runs = list_runs(workflow_id=workflow_id, status=status, limit=limit)

    jobs = []
    for r in runs:
        md = r.get("metadata", {})
        if isinstance(md, str):
            try:
                md = json.loads(md)
            except (json.JSONDecodeError, ValueError):
                md = {}

        jobs.append({
            "run_id": r["run_id"],
            "status": r["status"],
            "title": md.get("title", "?"),
            "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
        })

    return {"jobs": jobs, "total": len(jobs)}


@router.get("/jobs/{run_id}")
def get_job(
    run_id: str,
    _: None = Depends(require_harness_auth),
) -> Any:
    """Get the full run state including all step outputs."""
    try:
        return get_run(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


@router.post("/jobs/{run_id}/cancel")
def cancel_job(
    run_id: str,
    _: None = Depends(require_harness_auth),
) -> dict:
    """Cancel a running demo creation job."""
    try:
        from workflows.service import update_run
        update_run(run_id, RunUpdateRequest(status=WorkflowStatus.CANCELLED))
        return {"status": "cancelled", "run_id": run_id}
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


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
