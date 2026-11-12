"""Harness learning metrics (Phase 4) — reflection outputs for the
harness-learning dashboard (experience_improvement_todo.md, Phase 4).

Emitted on skill-runner ``/metrics`` (appended in ``main.py``), in the
same dependency-free Prometheus text format as ``memory/metrics.py``,
``sessions.py``, ``proposals.py`` and ``jobs_metrics.py``:

  - ``harness_reflection_runs_total`` — total harness_reflection runs
    (one per weekly run-now / cron dispatch; the run itself is
    best-effort and may skip the LLM call when the window has no
    signals).
  - ``harness_reflection_maintenance_total{kind}`` — memory
    maintenance items STORED by the reflection skill, by kind:
    ``supersede`` (contradiction / superseded fact), ``correction``
    (correction preference), ``lesson`` (friction lesson). This is the
    source of the "correction rate (corrections/week)" north star.

The ``harness_reflection`` skill (which runs in-process in this same
runner) calls ``record_run()`` / ``record_maintenance()`` best-effort;
any failure degrades to a no-op and never fails the job. Counters are
in-process only (like the sessions/proposals counters): a runner
restart resets them, which is acceptable for rate()/increase() over
the short weekly cadence (a counter reset is handled by Prometheus).
"""
from __future__ import annotations

import logging
import threading
from typing import Dict

logger = logging.getLogger("skill_runner.learning_metrics")

# Maintenance kinds (stable label set so the series never disappears
# from /metrics — a missing label looks like a scrape gap in Grafana).
_KINDS = ("supersede", "correction", "lesson")

_lock = threading.Lock()
_runs_total: float = 0.0
_maintenance_total: Dict[str, float] = {kind: 0.0 for kind in _KINDS}


def record_run() -> None:
    """Count one harness_reflection run (best-effort)."""
    try:
        global _runs_total
        with _lock:
            _runs_total += 1.0
    except Exception as exc:  # noqa: BLE001 - metrics must never fail a run
        logger.warning("learning_metrics.record_run failed: %s", exc)


def record_maintenance(kind: str, amount: int = 1) -> None:
    """Count maintenance items stored for one ``kind`` (best-effort)."""
    try:
        if kind not in _KINDS or amount <= 0:
            return
        with _lock:
            _maintenance_total[kind] += float(amount)
    except Exception as exc:  # noqa: BLE001 - metrics must never fail a run
        logger.warning("learning_metrics.record_maintenance failed: %s", exc)


def exposition() -> str:
    """Render the learning metrics (appended to /metrics)."""
    try:
        with _lock:
            lines = [
                "# HELP harness_reflection_runs_total Total harness_reflection runs.",
                "# TYPE harness_reflection_runs_total counter",
                f"harness_reflection_runs_total {_runs_total:g}",
                "# HELP harness_reflection_maintenance_total Memory maintenance items "
                "stored by harness_reflection (by kind: supersede/correction/lesson).",
                "# TYPE harness_reflection_maintenance_total counter",
            ]
            for kind in _KINDS:
                lines.append(
                    f'harness_reflection_maintenance_total{{kind="{kind}"}} '
                    f"{_maintenance_total[kind]:g}"
                )
            return "\n".join(lines) + "\n"
    except Exception:  # noqa: BLE001 - metrics must never raise
        return "# learning metrics unavailable\n"


def reset_for_tests() -> None:
    """Test hook: drop the counters."""
    global _runs_total, _maintenance_total
    with _lock:
        _runs_total = 0.0
        _maintenance_total = {kind: 0.0 for kind in _KINDS}