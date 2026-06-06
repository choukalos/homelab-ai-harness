"""
FastAPI router for the market research workflow.

Endpoints
---------
POST  /markets/research          – Kick off a new market research report job.
GET   /markets/research/jobs     – List recent research jobs (runs).
GET   /markets/research/jobs/<run_id>   – Get full run state + stage outputs.
POST  /markets/research/jobs/<run_id>/cancel   – Cancel a running job.
GET   /markets/research/jobs/<run_id>/files    – List intermediate output files.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from core.security import require_harness_auth
from market_research.schemas import MarketResearchRequest, MarketResearchState
from workflows.schemas import (
    StepDefinition,
    WorkflowCreateRequest,
    WorkflowStatus,
    WorkflowRunRequest,
)
from workflows.service import (
    create_workflow,
    create_run,
    get_run,
    update_run,
    delete_workflow,
    fail_step,
)
from workflows.schemas import RunUpdateRequest, WorkflowRunResponse

router = APIRouter(tags=["market-research"])

# ---------- Workflow definition -----

_MARKET_RESEARCH_STEPS: list[StepDefinition] = [
    StepDefinition(
        name="stage1_kb_lookup",
        description="Query Knowledge Base for prior research on the market",
        task_name="market_research.run_stage",
        task_kwargs={"stage": 1},
    ),
    StepDefinition(
        name="stage2_competitor_discovery",
        description="Discover competitors via web search and tier them",
        task_name="market_research.run_stage",
        task_kwargs={"stage": 2},
        depends_on=["stage1_kb_lookup"],
    ),
    StepDefinition(
        name="stage3_deep_dive",
        description="Crawl each competitor URL and generate LLM profiles",
        task_name="market_research.run_stage",
        task_kwargs={"stage": 3},
        depends_on=["stage2_competitor_discovery"],
    ),
    StepDefinition(
        name="stage4_vector_identification",
        description="Extract comparison vectors / themes",
        task_name="market_research.run_stage",
        task_kwargs={"stage": 4},
        depends_on=["stage3_deep_dive"],
    ),
    StepDefinition(
        name="stage5_data_population",
        description="Populate the comparison matrix (competitors x vectors)",
        task_name="market_research.run_stage",
        task_kwargs={"stage": 5},
        depends_on=["stage4_vector_identification"],
    ),
    StepDefinition(
        name="stage6_tier_analysis",
        description="Generate narrative analysis per tier",
        task_name="market_research.run_stage",
        task_kwargs={"stage": 6},
        depends_on=["stage5_data_population"],
    ),
    StepDefinition(
        name="stage7_executive_summary",
        description="Synthesize an executive summary",
        task_name="market_research.run_stage",
        task_kwargs={"stage": 7},
        depends_on=["stage6_tier_analysis"],
    ),
    StepDefinition(
        name="stage8_innovation_scouting",
        description="Identify whitespace opportunities and emerging trends",
        task_name="market_research.run_stage",
        task_kwargs={"stage": 8},
        depends_on=["stage5_data_population", "stage7_executive_summary"],
    ),
    StepDefinition(
        name="stage9_visual_planning",
        description="Plan visual layout of the final report",
        task_name="market_research.run_stage",
        task_kwargs={"stage": 9},
        depends_on=["stage8_innovation_scouting"],
    ),
    StepDefinition(
        name="stage10_report_assembly",
        description="Assemble final report via Layout Engine and export PDF",
        task_name="market_research.run_stage",
        task_kwargs={"stage": 10},
        depends_on=["stage9_visual_planning"],
    ),
]


def _ensure_workflow() -> str:
    """
    Create the market research workflow definition if it doesn't already
    exist and return its ID.

    We use a fixed name so we can detect whether it's already registered.
    """
    from workflows.service import list_workflows, get_workflow
    from workflows.schemas import WorkflowListFilters

    candidates = list_workflows(WorkflowListFilters(limit=50))
    for wf in candidates:
        if wf.get("name") == "market_research_pipeline":
            return wf["workflow_id"]

    wf = create_workflow(WorkflowCreateRequest(
        name="market_research_pipeline",
        description=(
            "LLM-driven market research report generator. "
            "Queries KB, discovers competitors, deep-dives each player, "
            "builds a comparison matrix, generates tier analysis, "
            "executive summary, innovation scouting, and assembles a "
            "final PDF report via the Layout Engine."
        ),
        tags=["market-research", "automated"],
        steps=_MARKET_RESEARCH_STEPS,
    ))
    return wf.workflow_id


# ---------- Endpoints ----------

@router.post("/", response_model=dict, status_code=201)
def start_research(
    req: MarketResearchRequest,
    _: None = Depends(require_harness_auth),
) -> dict:
    """
    Kick off a market research report job.

    Body:
        { "market": "Smart Home", "schedule": "on_demand" }

    Returns:
        { "run_id": "<uuid>", "workflow_id": "<uuid>",
          "market": "Smart Home", "status": "pending" }
    """
    workflow_id = _ensure_workflow()

    run = create_run(
        workflow_id,
        WorkflowRunRequest(
            metadata={
                "market": req.market,
                "schedule": req.schedule,
            },
        ),
    )

    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow_id,
        "market": req.market,
        "status": run.status.value,
        "steps_count": len(run.steps),
    }


@router.get("/jobs")
def list_jobs(
    market: str | None = Query(default=None, description="Filter by market name"),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    _: None = Depends(require_harness_auth),
) -> dict:
    """List recent market research jobs."""
    from workflows.service import list_runs

    workflow_id = _ensure_workflow()
    runs = list_runs(workflow_id=workflow_id, status=status, limit=limit)

    jobs = []
    for r in runs:
        md = {}
        try:
            import json as _j
            md = _j.loads(str(r.get("metadata")))
        except Exception:
            pass
        if market and md.get("market") != market:
            continue
        jobs.append({
            "run_id": r["run_id"],
            "status": r["status"],
            "market": md.get("market", "?"),
            "started_at": r.get("started_at"),
            "finished_at": r.get("finished_at"),
        })

    return {"jobs": jobs, "total": len(jobs)}


@router.get("/jobs/{run_id}")
def get_job(
    run_id: str,
    _: None = Depends(require_harness_auth),
) -> WorkflowRunResponse:
    """
    Get the full run state including all step details and outputs.
    """
    try:
        return get_run(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


@router.post("/jobs/{run_id}/cancel")
def cancel_job(
    run_id: str,
    _: None = Depends(require_harness_auth),
) -> dict:
    """Mark a running job as cancelled."""
    try:
        update_run(run_id, RunUpdateRequest(status=WorkflowStatus.CANCELLED))
        return {"status": "cancelled", "run_id": run_id}
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")


@router.get("/jobs/{run_id}/files")
def list_files(
    run_id: str,
    _: None = Depends(require_harness_auth),
) -> list[str]:
    """List intermediate output files for a research job."""
    try:
        run = get_run(run_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    # Look at the last completed step's artifacts
    files: list[str] = []
    for step in run.steps:
        for art in step.artifacts:
            if art.filename:
                files.append(art.filename)
    return files
