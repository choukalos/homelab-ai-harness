"""
Celery tasks for the one-page clickable demo workflow.

Provides the dispatchable task ``demo_workflow.run_stage`` that the workflow
engine calls for each pipeline stage.  Each stage loads shared state from disk,
executes the target stage function, persists results, and marks the step complete.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.celery_app import celery
from workflows.service import complete_step, fail_step, get_run, update_step
from workflows.schemas import StepStatus, StepUpdateRequest
from demo_workflow.service import _STAGE_MAP, save_state, load_state
from demo_workflow.schemas import DemoPipelineState

logger = logging.getLogger(__name__)

# Map stage key → workflow step name (must match StepDefinition "name")
_STAGE_TO_STEP_NAME: dict[str, str] = {
    "parse_request": "stage1_parse_request",
    "kb_lookup": "stage2_kb_lookup",
    "web_research": "stage3_web_research",
    "requirements_design": "stage4_requirements_design",
    "build_plan": "stage5_build_plan",
    "build_loop": "stage6_build_loop",
    "polish": "stage7_polish",
    "final_save": "stage8_final_save",
}


# ── Auto-dispatch: schedule next-ready step ───────────────────────

def _schedule_next_step(run_id: str) -> None:
    """After a step completes, try to dispatch the next pending step with satisfied deps."""
    from workflows.service import get_next_pending_step, start_step

    next_step = get_next_pending_step(run_id)
    if next_step is None:
        return  # no more pending steps or run is terminal

    kwargs: dict = next_step.input_payload or {}  # e.g. {"stage": "kb_lookup"}
    stage_key = kwargs.get("stage", "")
    if not stage_key:
        return  # no stage payload — not one of our tasks
    if stage_key not in _STAGE_MAP:
        return  # not a demo_workflow stage

    # Dispatch the Celery task (not the raw function)
    celery_task = run_stage.apply_async(args=[stage_key, run_id])
    logger.info("dispatched %s (%s) → celery_task_id=%s",
                next_step.name, stage_key, celery_task.id)
    start_step(run_id, next_step.name, celery_task_id=celery_task.id)


def _skip_remaining_steps(run_id: str, failed_stage_fn) -> None:
    """
    When a stage fails, mark all subsequent PENDING steps as SKIPPED.
    This ensures the run can reach a terminal state instead of staying
    stuck at 'running' forever with undispached pending steps.
    """
    from workflows.service import get_run as _get_run

    run = _get_run(run_id)
    for step in run.steps:
        if step.status == StepStatus.PENDING:
            update_step(
                run_id, step.name,
                StepUpdateRequest(
                    status=StepStatus.SKIPPED,
                    error=f"Skipped due to upstream stage '{failed_stage_fn.__name__}' failure.",
                ),
            )
            logger.info("skipped pending step %s in run %s", step.name, run_id)


@celery.task(
    bind=True,
    name="demo_workflow.run_stage",
    track_started=True,
    acks_late=True,
)
def run_stage(self, stage: str, run_id: str) -> dict:
    """
    Execute a single demo pipeline stage.

    **stage** is one of:
    - ``parse_request``, ``kb_lookup``, ``web_research``,
      ``requirements_design``, ``build_plan``, ``build_loop``,
      ``polish``, ``final_save``
    """
    logger.info("run_stage[%s] — run_id=%s", stage, run_id)

    try:
        run = get_run(run_id)

        # ── Resolve slug ──
        slug = _extract_slug(run)

        if slug:
            # Slug already exists → load accumulated state from disk
            state = load_state(slug)
        else:
            # Stage 1 — bootstrap state from run metadata (no slug yet)
            md = run.metadata or {}
            if isinstance(md, str):
                try:
                    md = json.loads(md)
                except (json.JSONDecodeError, ValueError):
                    md = {}
            state = DemoPipelineState(
                run_id=run_id,
                title=md.get("title", ""),
                prompt=md.get("prompt", ""),
                model_override=md.get("model_override"),
            )

        # Execute the stage
        fn = _STAGE_MAP.get(stage)
        if fn is None:
            raise ValueError(f"Unknown stage: {stage!r}")

        result = fn(state)
        save_state(state)

        # Mark step complete — use the workflow step name, not stage key
        step_name = _STAGE_TO_STEP_NAME.get(stage)
        if not step_name:
            raise ValueError(f"No workflow step name for stage {stage!r}")

        complete_step(
            run_id=run_id,
            step_name=step_name,
            output=result,
        )

        # After stage1, update run metadata with the slug so later stages can find it
        if stage == "parse_request":
            _update_slug_in_metadata(run_id, state.slug)

        # Dispatch the next ready step if any
        _schedule_next_step(run_id)

        return {
            "status": "ok",
            "stage": stage,
            "run_id": run_id,
            "summary": result,
        }

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error("run_stage[%s] failed: %s\n%s", stage, exc, tb)

        # Mark step failed — use workflow step name
        step_name = _STAGE_TO_STEP_NAME.get(stage)
        fail_step(
            run_id=run_id,
            step_name=step_name if step_name else stage,
            error=f"{exc}\n{tb}",
        )

        # Mark any remaining PENDING steps as SKIPPED so the run can reach terminal state
        _skip_remaining_steps(run_id, _STAGE_MAP[stage])

        return {
            "status": "error",
            "stage": stage,
            "run_id": run_id,
            "error": str(exc),
        }


# ── Helpers ──


def _extract_slug(run) -> str:
    """Get the demo slug from the run's metadata (set after stage1)."""
    md = run.metadata or {}
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except (json.JSONDecodeError, ValueError):
            md = {}

    if md.get("slug"):
        return md["slug"]

    # Fallback: try to load state from a slug derived from title
    title = md.get("title", "demo")
    return ""  # stage1 will create it


def _update_slug_in_metadata(run_id: str, slug: str) -> None:
    """After stage1 completes, update run metadata with the slug."""
    from workflows.service import update_run
    from workflows.schemas import RunUpdateRequest

    run = get_run(run_id)
    md = run.metadata or {}
    if isinstance(md, str):
        try:
            md = json.loads(md)
        except (json.JSONDecodeError, ValueError):
            md = {}

    md["slug"] = slug
    update_run(run_id, RunUpdateRequest(metadata=md))


# ── Registration ──

def register() -> None:
    """Placeholder for future dynamic registrations."""
    pass
