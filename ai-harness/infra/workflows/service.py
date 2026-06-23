"""
Workflow run state service.

All business logic for creating workflows, starting runs, transitioning steps,
and tracking execution state.  Backed by MySQL via `workflows.db`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from infra.workflows.schemas import (
    ArtifactRecord,
    StepDefinition,
    StepResult,
    StepStatus,
    StepUpdateRequest,
    WorkflowCreateRequest,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowResponse,
    WorkflowStatus,
    WorkflowListFilters,
    RunUpdateRequest,
)
from infra.workflows.db import get_cursor, ensure_tables

# ---------- helpers ----------

def _now_iso() -> str:
    """Current UTC timestamp in ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


def _gen_id() -> str:
    return str(uuid.uuid4())


def _json_serialize(obj: Any) -> str:
    """Serialize a Pydantic model or dict to JSON string for MySQL storage."""
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump())
    if isinstance(obj, dict):
        return json.dumps(obj)
    return json.dumps(obj)


# ---------- workflow CRUD ----------

def create_workflow(req: WorkflowCreateRequest) -> WorkflowResponse:
    """Persist a new workflow definition to MySQL and return the response."""
    workflow_id = _gen_id()

    with get_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO workflows (workflow_id, name, description, tags, steps)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                workflow_id,
                req.name,
                req.description or "",
                _json_serialize(req.tags),
                _json_serialize([s.model_dump() for s in req.steps]),
            ),
        )

    return WorkflowResponse(
        workflow_id=workflow_id,
        name=req.name,
        description=req.description or "",
        tags=req.tags,
        steps=req.steps,
        created_at=_now_iso(),
    )


def list_workflows(filters: WorkflowListFilters | None = None) -> list[dict]:
    """List workflow definitions with optional filtering and pagination."""
    if filters is None:
        filters = WorkflowListFilters()

    clauses: list[str] = []
    params: list[Any] = []

    if filters.workflow_id:
        clauses.append("workflow_id = %s")
        params.append(filters.workflow_id)
    if filters.tags:
        # Simple check: tags JSON array contains at least one of the requested tags
        for tag in filters.tags:
            clauses.append("JSON_CONTAINS(tags, %s)")
            params.append(json.dumps(tag))

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    with get_cursor() as cursor:
        query = f"SELECT * FROM workflows {where_sql} ORDER BY created_at DESC LIMIT %s OFFSET %s"
        cursor.execute(query, params + [filters.limit, filters.offset])
        rows = cursor.fetchall()

    results = []
    for row in rows:
        results.append({
            **row,
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "steps": json.loads(row["steps"]) if row["steps"] else [],
        })
    return results


def get_workflow(workflow_id: str) -> dict | None:
    """Return a complete workflow definition by ID."""
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM workflows WHERE workflow_id = %s", (workflow_id,))
        row = cursor.fetchone()
    if row is None:
        return None
    row["tags"] = json.loads(row["tags"]) if row["tags"] else []
    row["steps"] = json.loads(row["steps"]) if row["steps"] else []
    return row


def delete_workflow(workflow_id: str) -> bool:
    """Delete a workflow definition and cascade-delete all runs and steps."""
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT workflow_id FROM workflows WHERE workflow_id = %s",
            (workflow_id,),
        )
        exists = cursor.fetchone() is not None
        if exists:
            cursor.execute(
                "DELETE FROM workflows WHERE workflow_id = %s",
                (workflow_id,),
            )
    return exists


# ---------- run CRUD ----------

def create_run(
    workflow_id: str,
    req: WorkflowRunRequest | None = None,
) -> WorkflowRunResponse:
    """
    Create a new run for an existing workflow definition.

    Each step definition is cloned into a StepResult row with status=PENDING.
    """
    if req is None:
        req = WorkflowRunRequest()

    wf = get_workflow(workflow_id)
    if wf is None:
        raise ValueError(f"Workflow {workflow_id!r} not found")

    run_id = _gen_id()
    overrides = req.overrides or {}

    # Merge overrides: replace any step definition by name
    steps: list[StepDefinition] = [
        StepDefinition(**s) for s in (wf.get("steps") or [])
    ]
    override_steps = overrides.get("steps")
    if override_steps:
        override_map = {s["name"]: s for s in override_steps}
        for i, step in enumerate(steps):
            if step.name in override_map:
                steps[i] = StepDefinition(**override_map[step.name])

    # Apply per-step kwargs overrides
    kwargs_overrides = req.step_kwargs_overrides or {}

    with get_cursor() as cursor:
        # Insert the run
        cursor.execute(
            """
            INSERT INTO workflow_runs
                (run_id, workflow_id, status, overrides, step_kwargs_overrides, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                workflow_id,
                WorkflowStatus.PENDING.value,
                _json_serialize(req.overrides or {}),
                _json_serialize(req.step_kwargs_overrides or {}),
                _json_serialize(req.metadata or {}),
            ),
        )

        # Insert step rows
        for idx, step in enumerate(steps):
            step_id = _gen_id()
            # Merge task_kwargs with kwargs_overrides
            merged_kwargs = dict(step.task_kwargs or {})
            if kwargs_overrides.get(step.name):
                merged_kwargs.update(kwargs_overrides[step.name])

            cursor.execute(
                """
                INSERT INTO workflow_steps
                    (step_id, run_id, step_index, name, status, celery_task_id, model,
                     input_payload, retry_count)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    step_id,
                    run_id,
                    idx,
                    step.name,
                    StepStatus.PENDING.value,
                    None,
                    step.model,
                    _json_serialize(merged_kwargs),
                    0,
                ),
            )

    return _build_run_response(run_id)


def _build_run_response(run_id: str) -> WorkflowRunResponse:
    """Fetch a run + its step rows and assemble into WorkflowRunResponse."""
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM workflow_runs WHERE run_id = %s", (run_id,))
        row = cursor.fetchone()
        if row is None:
            raise ValueError(f"Run {run_id!r} not found")

        cursor.execute(
            "SELECT * FROM workflow_steps WHERE run_id = %s ORDER BY step_index",
            (run_id,),
        )
        step_rows = cursor.fetchall()

    metadata_raw = row.get("metadata")
    metadata = json.loads(metadata_raw) if metadata_raw else None

    return WorkflowRunResponse(
        run_id=run_id,
        workflow_id=row["workflow_id"],
        status=WorkflowStatus(row["status"]),
        steps=[_step_row_to_result(s) for s in step_rows],
        metadata=metadata,
        started_at=_to_iso(row.get("started_at")),
        finished_at=_to_iso(row.get("finished_at")),
    )


def get_run(run_id: str) -> WorkflowRunResponse:
    """Return the full run response for a given run ID."""
    return _build_run_response(run_id)


def list_runs(workflow_id: str | None = None, status: str | None = None,
              limit: int = 50, offset: int = 0) -> list[dict]:
    """List workflow runs with optional filters."""
    clauses: list[str] = []
    params: list[Any] = []

    if workflow_id:
        clauses.append("workflow_id = %s")
        params.append(workflow_id)
    if status:
        clauses.append("status = %s")
        params.append(status)

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    with get_cursor() as cursor:
        query = f"SELECT * FROM workflow_runs {where_sql} ORDER BY created_at DESC LIMIT %s OFFSET %s"
        cursor.execute(query, params + [limit, offset])
        rows = cursor.fetchall()

    return [dict(r) for r in rows]


def update_run(run_id: str, req: RunUpdateRequest) -> WorkflowRunResponse:
    """Update a run's status, metadata, or timestamps."""
    parts, params = [], []
    if req.status is not None:
        parts.append("status = %s")
        params.append(req.status.value)
    if req.metadata is not None:
        parts.append("metadata = %s")
        params.append(_json_serialize(req.metadata))
    if req.started_at is not None:
        parts.append("started_at = %s")
        params.append(req.started_at)
    if req.finished_at is not None:
        parts.append("finished_at = %s")
        params.append(req.finished_at)

    if not parts:
        return get_run(run_id)

    with get_cursor() as cursor:
        sql = f"UPDATE workflow_runs SET {', '.join(parts)} WHERE run_id = %s"
        cursor.execute(sql, params + [run_id])

    return _build_run_response(run_id)


# ---------- step transitions ----------

def update_step(run_id: str, step_name: str, req: StepUpdateRequest) -> WorkflowRunResponse:
    """
    Transition a step to a new state.

    If status changes to SUCCESS or FAILED the step is marked finished (if not
    already).  If multiple steps are updated and all reach terminal states
    the parent run is auto-transitioned (see `check_run_completion`).
    """
    parts, params = [], []

    if req.status is not None:
        parts.append("status = %s")
        params.append(req.status.value)
    if req.model is not None:
        parts.append("model = %s")
        params.append(req.model)
    if req.input_payload is not None:
        parts.append("input_payload = %s")
        params.append(_json_serialize(req.input_payload))
    if req.output is not None:
        parts.append("output = %s")
        params.append(_json_serialize(req.output))
    if req.error is not None:
        parts.append("error = %s")
        params.append(req.error)
    if req.retry_count is not None:
        parts.append("retry_count = %s")
        params.append(req.retry_count)
    if req.cost is not None:
        parts.append("cost = %s")
        params.append(req.cost)
    if req.input_tokens is not None:
        parts.append("input_tokens = %s")
        params.append(req.input_tokens)
    if req.output_tokens is not None:
        parts.append("output_tokens = %s")
        params.append(req.output_tokens)
    if req.celery_task_id is not None:
        parts.append("celery_task_id = %s")
        params.append(req.celery_task_id)
    if req.artifacts is not None:
        parts.append("artifacts = %s")
        params.append(_json_serialize([a.model_dump() for a in req.artifacts]))
    if req.started_at is not None:
        parts.append("started_at = %s")
        params.append(req.started_at)
    if req.finished_at is not None:
        parts.append("finished_at = %s")
        params.append(req.finished_at)

    if not parts:
        return get_run(run_id)

    with get_cursor() as cursor:
        sql = f"UPDATE workflow_steps SET {', '.join(parts)}, updated_at = NOW() WHERE run_id = %s AND name = %s"
        cursor.execute(sql, params + [run_id, step_name])

    # Auto-transition run when all steps are terminal
    check_run_completion(run_id)
    return _build_run_response(run_id)


def start_step(run_id: str, step_name: str, celery_task_id: str | None = None,
               model: str | None = None) -> WorkflowRunResponse:
    """Convenience: set a step to RUNNING, stamp started_at, store celery_task_id."""
    update_step(
        run_id, step_name,
        StepUpdateRequest(
            status=StepStatus.RUNNING,
            started_at=_now_iso(),
            celery_task_id=celery_task_id,
            model=model,
        ),
    )
    # Also advance run status and current_step
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT step_index FROM workflow_steps WHERE run_id = %s AND name = %s",
            (run_id, step_name),
        )
        row = cursor.fetchone()
        if row:
            cursor.execute(
                """UPDATE workflow_runs SET status = %s, current_step = %s,
                   started_at = %s
                   WHERE run_id = %s AND status IN ('pending','running')""",
                (WorkflowStatus.RUNNING.value, row["step_index"], _now_iso(), run_id),
            )
    return _build_run_response(run_id)


def complete_step(
    run_id: str,
    step_name: str,
    output: dict | None = None,
    model: str | None = None,
    cost: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    artifacts: list[ArtifactRecord] | None = None,
) -> WorkflowRunResponse:
    """Convenience: mark step SUCCESS and auto-transition run."""
    update_step(
        run_id, step_name,
        StepUpdateRequest(
            status=StepStatus.SUCCESS,
            finished_at=_now_iso(),
            output=output,
            model=model,
            cost=cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            artifacts=artifacts,
        ),
    )
    return _build_run_response(run_id)


def fail_step(run_id: str, step_name: str, error: str,
              retry_count: int | None = None) -> WorkflowRunResponse:
    """Convenience: mark step FAILED and auto-transition run."""
    update_step(
        run_id, step_name,
        StepUpdateRequest(
            status=StepStatus.FAILED,
            finished_at=_now_iso(),
            error=error,
            retry_count=retry_count,
        ),
    )
    return _build_run_response(run_id)


# ---------- run completion ----------

def check_run_completion(run_id: str) -> WorkflowRunResponse:
    """
    Inspect all step rows.  If every step is in a terminal state
    (SUCCESS, FAILED, SKIPPED) transition the run to SUCCESS or FAILED
    accordingly.
    """
    with get_cursor() as cursor:
        cursor.execute(
            """
            SELECT status, COUNT(*) as cnt
            FROM workflow_steps
            WHERE run_id = %s
            GROUP BY status
            """,
            (run_id,),
        )
        rows = cursor.fetchall()

    if not rows:
        return _build_run_response(run_id)

    terminal_states = {StepStatus.SUCCESS, StepStatus.FAILED, StepStatus.SKIPPED}
    all_terminal = all(StepStatus(r["status"]) in terminal_states for r in rows)

    if all_terminal:
        has_failure = any(StepStatus(r["status"]) == StepStatus.FAILED for r in rows)
        final_status = WorkflowStatus.FAILED if has_failure else WorkflowStatus.SUCCESS

        with get_cursor() as cursor:
            cursor.execute(
                """UPDATE workflow_runs
                   SET status = %s, finished_at = %s
                   WHERE run_id = %s AND status IN ('pending','running')""",
                (final_status.value, _now_iso(), run_id),
            )

    return _build_run_response(run_id)


def _to_iso(val):
    """Convert a datetime or string to ISO-8601 or None (pymysql helper)."""
    if val is None:
        return None
    if isinstance(val, str):
        return val
    # pymysql returns datetime objects for TIMESTAMP columns
    return val.isoformat()

def _step_row_to_result(row: dict) -> StepResult:
    """Convert a raw workflow_steps dict row into a StepResult."""
    return StepResult(
        name=row["name"],
        step_index=row["step_index"],
        status=StepStatus(row["status"]),
        celery_task_id=row.get("celery_task_id"),
        model=row.get("model"),
        input_payload=json.loads(row["input_payload"]) if row.get("input_payload") else None,
        output=json.loads(row["output"]) if row.get("output") else None,
        error=row.get("error"),
        retry_count=row.get("retry_count", 0),
        cost=float(row["cost"]) if row.get("cost") is not None else None,
        input_tokens=row.get("input_tokens"),
        output_tokens=row.get("output_tokens"),
        artifacts=[ArtifactRecord(**a) for a in json.loads(row["artifacts"])]
            if row.get("artifacts") else [],
        started_at=_to_iso(row.get("started_at")),
        finished_at=_to_iso(row.get("finished_at")),
    )


def get_next_pending_step(run_id: str) -> StepResult | None:
    """
    Return the next PENDING step whose dependencies are all SUCCESS.
    Steps are returned in definition order (step_index ASC).
    """
    # Fetch workflow_id from the run (needed to resolve depends_on).
    # Do this *before* entering the steps cursor to avoid nested connections.
    workflow_id: str | None = None
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT workflow_id FROM workflow_runs WHERE run_id = %s",
            (run_id,),
        )
        run_row = cursor.fetchone()
        if run_row:
            workflow_id = run_row["workflow_id"]

    # Load step dependency map from the workflow definition.
    dep_map: dict[str, list[str]] = {}
    if workflow_id:
        wf = get_workflow(workflow_id)
        if wf:
            for sd in wf.get("steps", []):
                if sd.get("depends_on"):
                    dep_map[sd["name"]] = sd["depends_on"]

    with get_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM workflow_steps WHERE run_id = %s ORDER BY step_index",
            (run_id,),
        )
        all_steps = cursor.fetchall()

        # Build a quick lookup: step name -> step status
        status_lookup = {s["name"]: s["status"] for s in all_steps}

        for step in all_steps:
            if step["status"] != StepStatus.PENDING.value:
                continue

            # Check dependencies: all must be SUCCESS
            dep_names = dep_map.get(step["name"], [])
            deps_ok = all(
                status_lookup.get(dname) == StepStatus.SUCCESS.value
                for dname in dep_names
            )

            if deps_ok:
                return _step_row_to_result(step)

    return None
