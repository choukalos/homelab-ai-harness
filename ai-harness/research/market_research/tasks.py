"""
Market research Celery tasks.

Provides a single dispatchable task ``market_research.run_stage`` that
the workflow engine calls for each pipeline stage.  The task looks up
the run's shared state from the workflow run's ``input_payload``,
executes the target stage, then calls the workflow engine callback
to mark the step as complete.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from infra.core.celery_app import celery
from infra.workflows.service import complete_step, fail_step

logger = logging.getLogger(__name__)

# Stage index → service function (imported lazily to avoid circular imports)
_STAGE_MAP: dict[int, Any] = {}


def register() -> None:
    """Import stage functions from service.py into the task registry.

    Called once at FastAPI startup so the Celery task is available
    before any workflow dispatch.
    """
    from research.market_research.service import (
        stage1_kb_lookup,
        stage2_competitor_discovery,
        stage3_deep_dive,
        stage4_vector_identification,
        stage5_data_population,
        stage6_tier_analysis,
        stage7_executive_summary,
        stage8_innovation_scouting,
        stage9_visual_planning,
        stage10_report_assembly,
    )
    _STAGE_MAP.update({
        1: stage1_kb_lookup,
        2: stage2_competitor_discovery,
        3: stage3_deep_dive,
        4: stage4_vector_identification,
        5: stage5_data_population,
        6: stage6_tier_analysis,
        7: stage7_executive_summary,
        8: stage8_innovation_scouting,
        9: stage9_visual_planning,
        10: stage10_report_assembly,
    })


@celery.task(
    bind=True,
    name="market_research.run_stage",
    track_started=True,
    acks_late=True,
)
def run_stage(self, stage: int, run_id: str) -> dict[str, Any]:
    """Execute a single pipeline stage.

    Called by the workflow engine.  The *stage* argument selects which
    pipeline stage to execute.  The worker loads the shared state from
    the run's previous step outputs, mutates it, persists results back
    via the workflow engine callback, then returns a summary dict.
    """
    if not _STAGE_MAP:
        register()

    fn = _STAGE_MAP.get(stage)
    if fn is None:
        return {"error": f"Unknown stage: {stage}"}

    logger.info("run_stage[%d] — run_id=%s", stage, run_id)

    try:
        # Load accumulated state from run metadata
        from infra.workflows.service import get_run
        run = get_run(run_id)
        state = _load_state(run)

        # Execute the stage
        result = fn(state)

        # Persist state snapshot back to all steps as output
        _save_state(run_id, state)

        # Mark this step as complete in the workflow engine
        complete_step(
            run_id=run_id,
            step_name=f"stage{stage}",
            output=result,
        )

        return {
            "status": "ok",
            "stage": stage,
            "run_id": run_id,
            "summary": result,
        }

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error("run_stage[%d] failed: %s\n%s", stage, exc, tb)

        fail_step(
            run_id=run_id,
            step_name=f"stage{stage}",
            error=f"{exc}\n{tb}",
        )

        return {
            "status": "error",
            "stage": stage,
            "run_id": run_id,
            "error": str(exc),
        }


def _load_state(run: Any) -> Any:
    """Reconstruct MarketResearchState from the run's step outputs.

    Each step stores its output dict in the workflow step output JSON.
    We reconstruct the state from the market metadata + any previously
    completed step outputs.
    """
    from research.market_research.schemas import MarketResearchState

    md = run.metadata or {}
    state = MarketResearchState(
        market=md.get("market", ""),
        run_id=run.run_id,
        schedule=md.get("schedule", "on_demand"),
        date_stamp=datetime.now(timezone.utc).strftime("%Y%m%d"),
    )

    # Re-attach stage results from previously completed steps
    for step in run.steps:
        if step.status.value not in ("success",) or step.output is None:
            continue
        name = step.name
        d = step.output  # dict from stage return value
        if name == "stage1_kb_lookup":
            from research.market_research.schemas import KbLookupResult
            # Restore from disk instead for richer state
            _restore_stage(state, "kb_result", "KbLookupResult")
        elif name == "stage2_competitor_discovery":
            _restore_stage(state, "competitor_discovery", "CompetitorDiscoveryResult")
        elif name == "stage3_deep_dive":
            _restore_stage(state, "deep_dive", "DeepDiveResult")
        elif name == "stage4_vector_identification":
            _restore_stage(state, "vectors", "VectorIdentificationResult")
        elif name == "stage5_data_population":
            _restore_stage(state, "matrix", "ComparisonMatrixResult")
        elif name == "stage6_tier_analysis":
            _restore_stage(state, "tier_analysis", "TierAnalysisResult")
        elif name == "stage7_executive_summary":
            _restore_stage(state, "executive_summary", "ExecutiveSummaryResult")
        elif name == "stage8_innovation_scouting":
            _restore_stage(state, "innovation", "InnovationScoutingResult")
        elif name == "stage9_visual_planning":
            _restore_stage(state, "layout_plan", "LayoutPlanResult")
        elif name == "stage10_report_assembly":
            _restore_stage(state, "assembly", "ReportAssemblyResult")

    return state


def _restore_stage(state: Any, attr: str, klass: str) -> None:
    """Load a stage result from intermediate JSON on disk."""
    from pathlib import Path
    from infra.core.config import MEDIA_OUTPUT_DIR

    market = state.market
    if not market:
        return

    san = market.replace(" ", "_")
    base = Path(MEDIA_OUTPUT_DIR) / "research" / san

    # Map attribute → filename
    filename_map = {
        "kb_result": "stage1_kb_lookup.json",
        "competitor_discovery": "stage2_competitors.json",
        "deep_dive": "stage3_deep_dive.json",
        "vectors": "stage4_vectors.json",
        "matrix": "stage5_matrix.json",
        "tier_analysis": "stage6_tier_analysis.json",
        "executive_summary": "stage7_executive_summary.json",
        "innovation": "stage8_innovation.json",
        "layout_plan": "stage9_layout_plan.json",
        "assembly": "stage10_assembly.json",
    }
    fn = filename_map.get(attr)
    if not fn:
        return

    fp = base / fn
    if not fp.exists():
        return

    # Import the class and reconstruct
    import importlib
    mod = importlib.import_module("market_research.schemas")
    cls = getattr(mod, klass, None)
    if cls is None:
        return

    data = json.loads(fp.read_text())
    # For TierAnalysisResult, data is wrapped in {"tiers": [...]}
    if klass == "TierAnalysisResult":
        obj = cls(**data)
    else:
        obj = cls(**data)
    setattr(state, attr, obj)


def _save_state(run_id: str, state: Any) -> None:
    """Persist the full state snapshot to disk as intermediate JSON."""
    from pathlib import Path
    from infra.core.config import MEDIA_OUTPUT_DIR

    market = state.market
    if not market:
        return

    san = market.replace(" ", "_")
    base = Path(MEDIA_OUTPUT_DIR) / "research" / san
    base.mkdir(parents=True, exist_ok=True)

    fp = base / "state_snapshot.json"
    dump = state.model_dump()
    # Remove raw_markdown fields to keep file size small
    if dump.get("deep_dive"):
        dd = dump["deep_dive"]
        if isinstance(dd, dict) and "profiles" in dd:
            for p in dd["profiles"]:
                p.pop("raw_markdown", None)
    fp.write_text(json.dumps(dump, indent=2), encoding="utf-8")
