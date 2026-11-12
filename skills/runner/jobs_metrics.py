"""Skill job metrics (Phase 4) — job health for the harness-learning
dashboard (experience_improvement_todo.md, Phase 4).

Emitted on skill-runner ``/metrics`` (appended in ``main.py``), in the
same dependency-free Prometheus text format as ``memory/metrics.py``,
``sessions.py`` and ``proposals.py``:

  - ``skill_jobs_total{skill, status}`` — total jobs by skill and
    terminal status (completed / failed / cancelled / interrupted).
    Success rate = completed / total; failures by skill for the
    Friction row.
  - ``skill_job_duration_seconds{skill}`` — histogram of terminal-job
    durations (created_at -> completed_at). p50/p95 via
    ``histogram_quantile`` in Grafana.
  - ``skill_jobs_rerun_total{skill, kind}`` — jobs that re-ran a
    previous same (skill, intent) job. ``kind="user"`` = the intent
    (first of the prompt / query / topic / interests params, same
    convention as harness_reflection's job signals) was non-empty and
    was already seen for that skill — a user-driven retry.
    ``kind="scheduled"`` = no intent params — a recurring scheduled
    run (the "re-run pattern" friction the reflection skill flags).
    North-star "% jobs completing without retry" uses kind="user".

Counting model (no double counting across restarts):

  - ``seed_from_jobs()`` runs at startup AFTER ``_hydrate_jobs()``, so
    the in-memory ``jobs`` store holds the full terminal history; the
    seed counts every job exactly once and observes the duration
    histogram from the stored timestamps.
  - In-process, ``record_terminal()`` (called from ``_persist_job``)
    records a job exactly once when it reaches a terminal state —
    after startup, so it never overlaps the seed.
  - ``record_start()`` (called from ``_execute_skill``) counts a
    re-run when a previous job with the same skill + intent already
    exists in the store.

Best-effort like the rest of the job index: any failure degrades to a
no-op and never crashes the runner. Counters are re-seeded from the
durable history on every restart, so ``increase()``/``rate()`` stay
correct (the seed value only ever grows).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional, Set, Tuple

logger = logging.getLogger("skill_runner.jobs_metrics")

# Duration histogram buckets (seconds): sub-second skills up to a
# 1-hour job (harness_reflection ~2 min, recent_activity ~2 min).
_DURATION_BUCKETS: Tuple[float, ...] = (
    1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0,
)

# Intent keys for re-run detection — same convention as
# harness_reflection._job_signals: the first of these params keys
# (truncated to 120 chars), "" when none is present.
_INTENT_KEYS: Tuple[str, ...] = ("prompt", "query", "topic", "interests")
_INTENT_MAX = 120

# ---------------------------------------------------------------------------
# Module state (all access under _lock)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_jobs_total: Dict[Tuple[str, str], float] = {}  # (skill, status) -> count
_rerun_total: Dict[Tuple[str, str], float] = {}  # (skill, kind) -> count
# skill -> [bucket counts..., count, sum]
_hist: Dict[str, list] = {}
_recorded: Set[str] = set()  # job_ids already recorded (terminal)
_seeded: Set[str] = set()  # job_ids already counted for re-runs (seed)


def _esc(value: str) -> str:
    """Escape a label value for Prometheus exposition."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _status_str(status: Any) -> str:
    """JobStatus enum or plain string -> its value."""
    return str(getattr(status, "value", status) or "unknown")


def _intent_key(params: Any) -> str:
    if not isinstance(params, dict):
        return ""
    for key in _INTENT_KEYS:
        value = params.get(key)
        if value:
            return str(value)[:_INTENT_MAX]
    return ""


def _parse_ts(value: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value))
    except Exception:  # noqa: BLE001 - bad timestamps degrade to None
        return None


def _duration_s(created_at: Any, completed_at: Any) -> Optional[float]:
    created = _parse_ts(created_at)
    completed = _parse_ts(completed_at)
    if created is None or completed is None:
        return None
    seconds = (completed - created).total_seconds()
    return seconds if seconds >= 0 else None


def _hist_observe(skill: str, seconds: float) -> None:
    row = _hist.get(skill)
    if row is None:
        row = _hist[skill] = [0.0] * (len(_DURATION_BUCKETS) + 2)
    for index, bucket in enumerate(_DURATION_BUCKETS):
        if seconds <= bucket:
            row[index] += 1.0
    row[-2] += 1.0  # count
    row[-1] += seconds  # sum


def _record_job(job: Any) -> None:
    """Record one terminal job exactly once (idempotent per job_id)."""
    job_id = str(getattr(job, "job_id", "") or "")
    if not job_id or job_id in _recorded:
        return
    _recorded.add(job_id)
    skill = str(getattr(job, "skill", "") or "unknown")[:120]
    status = _status_str(getattr(job, "status", ""))
    _jobs_total[(skill, status)] = _jobs_total.get((skill, status), 0.0) + 1.0
    duration = _duration_s(
        getattr(job, "created_at", None), getattr(job, "completed_at", None)
    )
    if duration is not None:
        _hist_observe(skill, duration)


def seed_from_jobs(jobs: Dict[str, Any]) -> None:
    """One-time startup seed from the in-memory job store.

    Called in ``main.py`` lifespan AFTER ``_hydrate_jobs()``: the store
    then holds the full terminal history, so every job is counted
    exactly once here and in-process ``record_terminal`` (which only
    sees jobs completing after startup) never overlaps it.
    """
    try:
        with _lock:
            ordered = sorted(
                jobs.values(), key=lambda j: str(getattr(j, "created_at", ""))
            )
            seen: Dict[Tuple[str, str], int] = {}
            for job in ordered:
                _record_job(job)
                job_id = str(getattr(job, "job_id", "") or "")
                if not job_id or job_id in _seeded:
                    continue  # idempotent re-seed: re-run counts once only
                _seeded.add(job_id)
                intent = _intent_key(getattr(job, "params", None))
                skill = str(getattr(job, "skill", "") or "unknown")[:120]
                if intent:
                    key = (skill, intent)
                    if seen.get(key, 0) >= 1:
                        _rerun_total[(skill, "user")] = (
                            _rerun_total.get((skill, "user"), 0.0) + 1.0
                        )
                    seen[key] = seen.get(key, 0) + 1
                else:
                    # Recurring run without intent params (scheduled
                    # cadence): a re-run after the first occurrence.
                    if seen.get((skill, ""), 0) >= 1:
                        _rerun_total[(skill, "scheduled")] = (
                            _rerun_total.get((skill, "scheduled"), 0.0) + 1.0
                        )
                    seen[(skill, "")] = seen.get((skill, ""), 0) + 1
        logger.info(
            "Job metrics seeded from %d job(s): %d status series, %d skills.",
            len(jobs), len(_jobs_total), len(_hist),
        )
    except Exception as exc:  # noqa: BLE001 - metrics must never break startup
        logger.warning("jobs_metrics.seed_from_jobs failed: %s", exc)


def record_terminal(job: Any) -> None:
    """Record a job that just reached a terminal state (exactly once)."""
    try:
        with _lock:
            _record_job(job)
    except Exception as exc:  # noqa: BLE001 - metrics must never fail a job
        logger.warning("jobs_metrics.record_terminal failed: %s", exc)


def record_start(job: Any, jobs: Dict[str, Any]) -> None:
    """Count a re-run when a previous same (skill, intent) job exists.

    Called from ``_execute_skill`` when the job starts; ``jobs`` is the
    module-level store (the current job may or may not be in it yet —
    only strictly-earlier jobs count).
    """
    try:
        skill = str(getattr(job, "skill", "") or "unknown")[:120]
        intent = _intent_key(getattr(job, "params", None))
        kind = "user" if intent else "scheduled"
        created = _parse_ts(getattr(job, "created_at", None))
        with _lock:
            for other in jobs.values():
                if other is job:
                    continue
                if str(getattr(other, "skill", "") or "unknown")[:120] != skill:
                    continue
                if _intent_key(getattr(other, "params", None)) != intent:
                    continue
                other_created = _parse_ts(getattr(other, "created_at", None))
                if created is not None and other_created is not None:
                    if not (other_created < created):
                        continue
                _rerun_total[(skill, kind)] = (
                    _rerun_total.get((skill, kind), 0.0) + 1.0
                )
                return  # one re-run count per job
    except Exception as exc:  # noqa: BLE001 - metrics must never fail a job
        logger.warning("jobs_metrics.record_start failed: %s", exc)


def exposition() -> str:
    """Render the job metrics (appended to /metrics)."""
    try:
        with _lock:
            lines = [
                "# HELP skill_jobs_total Total skill jobs by skill and terminal status.",
                "# TYPE skill_jobs_total counter",
            ]
            for (skill, status), value in sorted(_jobs_total.items()):
                lines.append(
                    f'skill_jobs_total{{skill="{_esc(skill)}",'
                    f'status="{_esc(status)}"}} {value:g}'
                )
            lines += [
                "# HELP skill_jobs_rerun_total Skill jobs that re-ran a previous "
                "same (skill, intent) job (kind=user: user-driven retry; "
                "kind=scheduled: recurring run without intent params).",
                "# TYPE skill_jobs_rerun_total counter",
            ]
            for (skill, kind), value in sorted(_rerun_total.items()):
                lines.append(
                    f'skill_jobs_rerun_total{{skill="{_esc(skill)}",'
                    f'kind="{_esc(kind)}"}} {value:g}'
                )
            lines += [
                "# HELP skill_job_duration_seconds Duration of terminal skill jobs, by skill.",
                "# TYPE skill_job_duration_seconds histogram",
            ]
            for skill in sorted(_hist):
                row = _hist[skill]
                for bucket, count in zip(_DURATION_BUCKETS, row):
                    lines.append(
                        f'skill_job_duration_seconds_bucket'
                        f'{{skill="{_esc(skill)}",le="{bucket:g}"}} {count:g}'
                    )
                lines.append(
                    f'skill_job_duration_seconds_bucket'
                    f'{{skill="{_esc(skill)}",le="+Inf"}} {row[-2]:g}'
                )
                lines.append(
                    f'skill_job_duration_seconds_sum{{skill="{_esc(skill)}"}} '
                    f"{row[-1]:g}"
                )
                lines.append(
                    f'skill_job_duration_seconds_count{{skill="{_esc(skill)}"}} '
                    f"{row[-2]:g}"
                )
            return "\n".join(lines) + "\n"
    except Exception:  # noqa: BLE001 - metrics must never raise
        return "# job metrics unavailable\n"


def reset_for_tests() -> None:
    """Test hook: drop all counters/histograms."""
    global _jobs_total, _rerun_total, _hist, _recorded, _seeded
    with _lock:
        _jobs_total = {}
        _rerun_total = {}
        _hist = {}
        _recorded = set()
        _seeded = set()