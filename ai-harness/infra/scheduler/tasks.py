"""Celery tasks that power the scheduler.

- ``scheduler.dispatch_task`` — called by Celery beat (via redbeat) for
  onetime / cron / interval schedules.
- ``scheduler.condition_checker`` — periodic poll that watches for condition
  events on a Redis pub/sub channel.
- ``scheduler.trigger_condition`` — public helper called by any harness
  code to announce that a condition has been met (e.g. KB ingestion done).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from infra.core.celery_app import celery
from infra.scheduler.models import RunState, ScheduleType
from infra.scheduler.store import bump_run_count, get, mark_expired, update
from infra.core.config import REDIS_URL
import redis as redis_lib

CONDITION_CHANNEL = "harness:condition_events"


@celery.task(
    bind=True,
    name="scheduler.dispatch_task",
    track_started=True,
)
def dispatch_task(self, schedule_id: str) -> dict[str, Any]:
    """Called by beat to fire a scheduled job.

    Looks up the :class:`~scheduler.models.ScheduleEntry` in our Redis
    store, enforces limits, advances the run count, and delegates to the
    actual target task.
    """
    entry = get(schedule_id)
    if entry is None:
        return {"schedule_id": schedule_id, "status": "not_found"}

    # --- state guard ---
    if entry.state == RunState.EXPIRED:
        return {"schedule_id": schedule_id, "status": "expired", "action": "deleted_from_beat"}
    if entry.state == RunState.PAUSED:
        return {"schedule_id": schedule_id, "status": "paused"}

    # --- onetime cleanup ---
    if entry.type == ScheduleType.ONCE:
        # will expire after this fire
        _ = True  # fall through to dispatch

    # --- hit count guard ---
    if entry.max_runs is not None and entry.run_count >= entry.max_runs:
        mark_expired(schedule_id)
        return {"schedule_id": schedule_id, "status": "max_runs_reached", "action": "expired"}

    # ---- dispatch the real task ----
    try:
        target_task = celery.tasks.get(entry.task_name)
        async_result = target_task.apply_async(kwargs=entry.task_kwargs)
    except KeyError:
        return {
            "schedule_id": schedule_id,
            "status": "error",
            "error": f"Unknown task: {entry.task_name}",
        }

    now_iso = datetime.utcnow().isoformat()
    bump_run_count(schedule_id, last_run=now_iso)

    # expire onetimes
    if entry.type == ScheduleType.ONCE:
        mark_expired(schedule_id)

    return {
        "schedule_id": schedule_id,
        "status": "dispatched",
        "task_id": async_result.id,
        "run_number": entry.run_count + 1,
    }


# ---- Condition helpers ----------------------------------------------------------------

CONDITION_EVENT_KEY = "harness:condition:trigger"


@celery.task(name="scheduler.condition_checker")
def condition_checker() -> dict[str, Any]:
    """Periodic poller (runs every 15 s via redbeat).

    Checks the Redis list ``harness:condition:trigger`` for pending
    condition events.  For each event, looks up any active ``condition``
    schedule entries whose ``condition_event`` name matches, and dispatches
    the target task.

    The event payload is a JSON dict with keys:

      - ``event``    (str)  — the condition name
      - ``payload``  (dict) — arbitrary data merged into task kwargs
    """
    conn = redis_lib.from_url(REDIS_URL, decode_responses=True)

    while True:
        raw = conn.lpop(CONDITION_EVENT_KEY)
        if raw is None:
            break  # no more pending events

        import json
        try:
            event_data = json.loads(raw)
        except Exception:
            continue

        event_name = event_data.get("event", "")
        extra_kwargs = event_data.get("payload", {})

        from infra.scheduler.store import list_all as list_schedules
        for entry in list_schedules():
            if (
                entry.type == ScheduleType.CONDITION
                and entry.condition_event == event_name
                and entry.state == RunState.ACTIVE
            ):
                merged_kwargs = {**entry.task_kwargs, **extra_kwargs}
                try:
                    target_task = celery.tasks.get(entry.task_name)
                    target_task.apply_async(kwargs=merged_kwargs)
                except KeyError:
                    pass

                now_iso = datetime.utcnow().isoformat()
                bump_run_count(entry.id, last_run=now_iso)
                if entry.type == ScheduleType.ONCE:
                    mark_expired(entry.id)


@celery.task(name="scheduler.trigger_condition")
def trigger_condition(
    event_name: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Push a condition event onto the trigger list.

    Call this whenever something interesting happens (e.g. KB ingestion
    finishes, a file appears, an API signal arrives).  The
    ``condition_checker`` beat task will pick it up within ~15 seconds.
    """
    import json
    conn = redis_lib.from_url(REDIS_URL, decode_responses=True)
    conn.rpush(
        CONDITION_EVENT_KEY,
        json.dumps({"event": event_name, "payload": payload or {}}),
    )
    return {"status": "ok", "event": event_name}
