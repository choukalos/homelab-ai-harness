"""FastAPI router for workflow run state storage and lifecycle management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from infra.core.security import require_harness_auth
from infra.workflows.schemas import (
    CompleteStepRequest,
    StepStatus,
    StepUpdateRequest,
    WorkflowCreateRequest,
    WorkflowListFilters,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowResponse,
    WorkflowStatus,
    RunUpdateRequest,
)
from infra.workflows.service import (
    check_run_completion,
    complete_step,
    create_run,
    create_workflow,
    fail_step,
    get_next_pending_step,
    get_run,
    get_workflow,
    list_runs,
    list_workflows,
    update_step,
    update_run,
    delete_workflow,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])

# ── NOTE: All /runs routes MUST be defined before /{workflow_id}
#           so FastAPI does not match "runs" to the {workflow_id} param. ──

# ---------- run CRUD (must come before /{workflow_id}) ------------

@router.post("/{workflow_id}/runs", response_model=WorkflowRunResponse, status_code=201)
def create_run_ep(
    workflow_id: str,
    req: WorkflowRunRequest | None = None,
    _: None = Depends(require_harness_auth),
):
    """
    Start a new run for an existing workflow.

    Creates a run with all steps cloned as pending, returning
    the initial run state.
    """
    try:
        return create_run(workflow_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/runs", responses={200: {"content": {"application/json": {}}}})
def list_runs_ep(
    workflow_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(require_harness_auth),
):
    """List workflow runs with optional filters."""
    return list_runs(workflow_id=workflow_id, status=status, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=WorkflowRunResponse)
def get_run_ep(run_id: str, _: None = Depends(require_harness_auth)):
    """
    Get the full run state including all step details.
    """
    try:
        return get_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/runs/{run_id}", response_model=WorkflowRunResponse)
def patch_run_ep(
    run_id: str,
    req: RunUpdateRequest,
    _: None = Depends(require_harness_auth),
):
    """Update a run's status, metadata, or timestamps."""
    try:
        return update_run(run_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------- step transitions -----------------------------------------------

@router.patch("/runs/{run_id}/steps/{step_name}", response_model=WorkflowRunResponse)
def patch_step_ep(
    run_id: str,
    step_name: str,
    req: StepUpdateRequest,
    _: None = Depends(require_harness_auth),
):
    """
    Update a single step's state within a run.

    Supports any field in StepUpdateRequest.  When all steps reach
    terminal states (SUCCESS/FAILED/SKIPPED) the parent run is
    auto-transitioned via check_run_completion.
    """
    try:
        return update_step(run_id, step_name, req)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/runs/{run_id}/next-step", response_model=Any)
def next_pending_step_ep(
    run_id: str,
    _: None = Depends(require_harness_auth),
):
    """
    Inspect a run and return the next step that is ready to execute
    (PENDING with all dependencies satisfied).

    Returns None if no pending steps or run is complete.
    """
    try:
        step = get_next_pending_step(run_id)
        if step is None:
            return {"next_step": None}
        return {"next_step": step.model_dump()}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/runs/{run_id}/complete-step/{step_name}", response_model=WorkflowRunResponse)
def complete_step_ep(
    run_id: str,
    step_name: str,
    req: CompleteStepRequest = Body(default=None),
    _: None = Depends(require_harness_auth),
):
    """
    Convenience endpoint: mark a step SUCCESS with optional cost/token tracking.

    Sends JSON body:
      { "output": {...}, "cost": 0.002, "input_tokens": 150,
        "output_tokens": 500, "model": "gemma-moe" }
    """
    if req is None:
        req = CompleteStepRequest()
    return complete_step(
        run_id=run_id,
        step_name=step_name,
        output=req.output,
        model=req.model,
        cost=req.cost,
        input_tokens=req.input_tokens,
        output_tokens=req.output_tokens,
        artifacts=req.artifacts,
    )


# ---------- completion check ------------------------------------------------

@router.post("/runs/{run_id}/check-completion", response_model=WorkflowRunResponse)
def check_completion_ep(
    run_id: str,
    _: None = Depends(require_harness_auth),
):
    """
    Force-check whether all steps have reached terminal states.
    If so, transition the parent run to SUCCESS or FAILED accordingly.
    """
    try:
        return check_run_completion(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------- workflow CRUD (must come AFTER /runs) ---------------------------

@router.post("/", response_model=WorkflowResponse, status_code=201)
def create_workflow_ep(
    req: WorkflowCreateRequest,
    _: None = Depends(require_harness_auth),
):
    """Create a new workflow definition with ordered steps."""
    return create_workflow(req)


@router.get("/", responses={200: {"content": {"application/json": {}}}})
def list_workflows_ep(
    workflow_id: str | None = Query(default=None),
    tags: str | None = Query(default=None, description="Comma-separated tag filter"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(require_harness_auth),
):
    """List workflow definitions with optional filters."""
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    filters = WorkflowListFilters(
        workflow_id=workflow_id,
        tags=tag_list,
        limit=limit,
        offset=offset,
    )
    return list_workflows(filters)


@router.get("/{workflow_id}")
def get_workflow_ep(workflow_id: str, _: None = Depends(require_harness_auth)):
    """Get a single workflow definition by ID."""
    wf = get_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id!r} not found")
    return wf


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow_ep(workflow_id: str, _: None = Depends(require_harness_auth)):
    """Delete a workflow definition and all its runs."""
    deleted = delete_workflow(workflow_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id!r} not found")
