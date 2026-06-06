"""Service layer for schedule management.

Responsibilities
----------------
1. CRUD against the Redis store (``scheduler/store.py``)
2. Sync / unsync with Celery redbeat so scheduled tasks actually fire
3. Condition firing via named events
4. NLP-friendly ``describe_schedules_as_text()`` for the chat layer

Redbeat integration
-------------------
Redbeat is a Celery beat *plugin* that stores beat schedules in Redis
(rather than in-process memory).  We add / remove ``RedBeatScheduleModel``
entries via the redbeat scheduler's API so that every time the beat
scheduler loops it (re)-evaluates our schedules.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from celery.schedules import crontab

from core.celery_app import celery
from scheduler.models import RunState, ScheduleEntry, ScheduleType
from scheduler.schemas import (
    ConditionTriggerRequest,
    CreateScheduleRequest,
    ScheduleResponse,
    UpdateScheduleRequest,
)
from scheduler.store import create, delete, get, list_all, update
from scheduler.tasks import dispatch_task as dispatch_task_task
from scheduler.tasks import trigger_condition


# ---------------------------------------------------------------------------
# Redbeat sync helpers
# ---------------------------------------------------------------------------

_REDBEAT_ENTRY_PREFIX = "hb:sch:"  # "harness:schedule:"


def _rb_key(schedule_id: str) -> str:
    """Redbeat key that maps to a Celery beat schedule entry."""
    return f"{_REDBEAT_ENTRY_PREFIX}{schedule_id}"


def _get_redbeat_scheduler():
    """Return the live RedBeatScheduler instance attached to celery."""
    # redbeat registers itself as the beat scheduler when the app starts.
    # We import here to avoid circular imports at module load time.
    try:
        from redbeat import RedBeatScheduler
        # Redbeat replaces celery's default beat scheduler.
        # Celery.beat_schedule is populated by redbeat on startup.
        return celery._redbeat  # type: ignore
    except AttributeError:
        return None  # redbeat not configured (happens in plain web process)


# ---- write / remove redbeat entries ----------------------------------


def _schedule_to_redbeat(entry: ScheduleEntry) -> dict[str, Any] | None:
    """Build a dict that redbeat expects for a schedule entry.

    Returns None for condition/paused entries (they don't get a beat entry).
    """
    if entry.state != RunState.ACTIVE:
        return None
    if entry.type == ScheduleType.CONDITION:
        return None

    base: dict[str, Any] = {
        "task": "scheduler.dispatch_task",
        "args": [],
        "kwargs": {"schedule_id": entry.id},
        "options": {},
        # name is required by redbeat schemas
        "name": f"scheduler:{entry.id}",
    }

    if entry.type == ScheduleType.ONCE:
        # Redbeat onetime: set ``eta`` (one-shot)
        if entry.at:
            base["eta"] = entry.at
            entry.next_run_at = entry.at
        else:
            # fire immediately
            base["eta"] = datetime.utcnow().isoformat()
            entry.next_run_at = base["eta"]

    elif entry.type == ScheduleType.CRON and entry.cron_expr:
        parsed = _parse_cron_to_celery_crontab(entry.cron_expr)
        base["schedule"] = parsed

    elif entry.type == ScheduleType.INTERVAL and entry.interval_seconds:
        base["schedule"] = timedelta(seconds=entry.interval_seconds)
        if entry.last_run_at:
            try:
                _last = datetime.fromisoformat(entry.last_run_at).replace(tzinfo=timezone.utc)
                _next = _last + timedelta(seconds=entry.interval_seconds)
                entry.next_run_at = _next.isoformat()
            except Exception:
                pass

    return base


def sync_redbeat(entry: ScheduleEntry) -> None:
    """Add or update the redbeat entry for *entry*.

    If redbeat is not available (web process only, no scheduler setup) we
    silently skip — the beat process will pick it up on its next sync pass.
    """
    rb = _get_redbeat_scheduler()
    if rb is None:
        return  # we are in the web container, not beat

    key = _rb_key(entry.id)
    payload = _schedule_to_redbeat(entry)

    if payload is None:
        # Paused or condition — nuke from beat
        try:
            rb.delete_schedule(key)
        except Exception:
            pass
        return

    # redbeat stores entries under its own key pattern (``redbeat:{name}``).
    # The cleanest integration point is to write directly to the Redis
    # hash using redbeat's internal key prefix, so beat sees it on the
    # next loop.
    try:
        from redbeat.schemas import RedBeatScheduleModel

        model = RedBeatScheduleModel(
            id=key,
            name=payload["name"],
            **payload,
        )
        # redbeat uses the celery backend Redis to persist entries.
        # We write via the scheduler's store:
        rb.store.save(model)
    except Exception:
        # fallback: write directly
        import json
        backend = celery.app.backend
        if backend:
            backend.get_client().set(f"redbeat:{key}", model.model_dump_json() if hasattr(model, 'model_dump_json') else json.dumps(payload))


def unsync_redbeat(schedule_id: str) -> None:
    """Remove a schedule from redbeat so beat stops firing it."""
    rb = _get_redbeat_scheduler()
    if rb is None:
        return
    key = _rb_key(schedule_id)
    try:
        rb.delete_schedule(key)
    except Exception:
        pass


# ---- Cron parser (simple 5-field) ----------------------------------------------

def _parse_cron_to_celery_crontab(expr: str) -> crontab:
    """Translate a crontab expression string to celery.schedules.crontab.

    Supports five fields: `minute hour dom month dow`.  Wildcard `*` and
    comma/step ranges pass through to celery's crontab.
    """
    try:
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Expected 5 fields, got {len(parts)}: {expr}")
        minute, hour, dom, month, dow = parts
        return crontab(
            minute=minute,
            hour=hour,
            day_of_week=dow,
            day_of_month=dom,
            month_of_year=month,
        )
    except Exception:
        # Fallback to "every minute" so we don't crash the scheduler
        return crontab(minute="*", hour="*", day_of_week="*", day_of_month="*", month_of_year="*")


# ---------------------------------------------------------------------------
# Store ↔ redbeat periodic sync
# ---------------------------------------------------------------------------

def sync_store_to_redbeat() -> int:
    """Reconcile our persistent store with redbeat.

    Called by the beat process on startup and periodically.
    Adds new entries, removes deleted ones, updates changed entries.
    Returns the number of entries synced.
    """
    rb = _get_redbeat_scheduler()
    if rb is None:
        return 0

    store_entries = list_all()
    store_ids = {e.id for e in store_entries}

    # Build set of existing redbeat harness keys
    try:
        import json
        backend = celery.app.backend
        clients = backend.get_client()
        all_keys = clients.keys(f"{_REDBEAT_ENTRY_PREFIX}*")
        existing_rb_ids = {k.decode() if isinstance(k, bytes) else k for k in all_keys}
    except Exception:
        existing_rb_ids = set()

    for entry in store_entries:
        sync_redbeat(entry)

    # Remove stale redbeat entries no longer in store
    for k in existing_rb_ids:
        if k not in store_ids:
            unsync_redbeat(k)

    return len(store_entries)


# ---------------------------------------------------------------------------
# Public API helpers (called by router)
# ---------------------------------------------------------------------------

def create_schedule(req: CreateScheduleRequest) -> ScheduleResponse:
    """Persist and return a new schedule."""
    entry = ScheduleEntry(
        id="",
        name=req.name,
        description=req.description,
        type=ScheduleType(req.type),
        task_name=req.task_name,
        task_kwargs=req.task_kwargs,
        at=req.at,
        cron_expr=req.cron_expr,
        interval_seconds=req.interval_seconds,
        condition_event=req.condition_event,
        max_runs=req.max_runs,
        state=RunState.ACTIVE,
    )
    created = create(entry)
    sync_redbeat(created)
    return ScheduleResponse.from_entry(created)


def update_schedule(schedule_id: str, req: UpdateScheduleRequest) -> ScheduleResponse:
    """Merge partial update, re-sync redbeat."""
    entry = get(schedule_id)
    if entry is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")

    updates: dict[str, Any] = req.model_dump(exclude_none=True)
    if not updates:
        return ScheduleResponse.from_entry(entry)

    if "name" in updates:
        entry.name = updates["name"]
    if "description" in updates:
        entry.description = updates["description"]
    if "type" in updates:
        entry.type = ScheduleType(updates["type"])
    if "task_name" in updates:
        entry.task_name = updates["task_name"]
    if "task_kwargs" in updates:
        entry.task_kwargs = updates["task_kwargs"]
    if "at" in updates:
        entry.at = updates["at"]
    if "cron_expr" in updates:
        entry.cron_expr = updates["cron_expr"]
    if "interval_seconds" in updates:
        entry.interval_seconds = updates["interval_seconds"]
    if "condition_event" in updates:
        entry.condition_event = updates["condition_event"]
    if "max_runs" in updates:
        entry.max_runs = updates["max_runs"]
    if "state" in updates:
        entry.state = RunState(updates["state"])

    saved = update(entry)
    sync_redbeat(saved)
    return ScheduleResponse.from_entry(saved)


def delete_schedule(schedule_id: str) -> bool:
    unsync_redbeat(schedule_id)
    return delete(schedule_id)


def list_schedules() -> list[ScheduleResponse]:
    return [ScheduleResponse.from_entry(e) for e in list_all()]


def get_schedule(schedule_id: str) -> ScheduleResponse | None:
    entry = get(schedule_id)
    return ScheduleResponse.from_entry(entry) if entry else None


def manual_trigger(schedule_id: str) -> dict[str, Any]:
    """Fire immediately."""
    entry = get(schedule_id)
    if entry is None:
        raise ValueError(f"Schedule {schedule_id} not found")
    ar = dispatch_task_task.delay(schedule_id)
    return {"status": "dispatched", "task_id": ar.id, "schedule_id": schedule_id}


def fire_condition_event(req: ConditionTriggerRequest) -> dict[str, Any]:
    ar = trigger_condition.delay(req.event_name, req.payload)
    return {"status": "queued", "task_id": ar.id, "event": req.event_name}


# ---------------------------------------------------------------------------
# Chat / NLP helpers
# ---------------------------------------------------------------------------

def describe_schedules_as_text() -> str:
    """Human-readable summary of all schedules — for voice / chat assistants.

    Example output::

        You have 3 schedule(s):

        1. **Morning briefing** (cron)
           Task: tasks.run_prompt
           Cron: 0 8 * * *
           Runs: 12/50  Last: 2025-06-05T08:00  Next: 2025-06-06T08:00

        2. **Weekly report** (interval)
           Task: tasks.python_executor
           Every: 604800s
           Runs: 3/--  Last: 2025-05-30

        3. **KB digest** (condition)
           Task: tasks.run_prompt
           Event: kb_ingestion_done
           Runs: 7/--  Last: 2025-06-04
    """
    entries = list_all()
    if not entries:
        return "You have no scheduled jobs."

    lines: list[str] = [f"You have {len(entries)} schedule(s):", ""]
    for i, e in enumerate(entries, 1):
        tag = f" [{e.state.value.upper()}]" if e.state != RunState.ACTIVE else ""
        max_str = f"/{e.max_runs}" if e.max_runs else "/--"
        detail_lines = []

        if e.type == ScheduleType.ONCE:
            when = f"Onetime: {e.at[:16] if e.at else 'now'}"
        elif e.type == ScheduleType.CRON:
            when = f"Cron: {e.cron_expr or 'n/a'}"
        elif e.type == ScheduleType.INTERVAL:
            when = f"Every: {e.interval_seconds}s"
        else:
            when = f"Condition event: {e.condition_event or 'n/a'}"

        detail_lines.append(f"   {when}")
        if e.last_run_at:
            detail_lines.append(f"   Last run: {e.last_run_at[:16]}")
        if e.next_run_at:
            detail_lines.append(f"   Next run: {e.next_run_at[:16]}")

        lines.append(f"{i}. **{e.name}** ({e.type.value}{tag})")
        lines.append(f"   Task: {e.task_name}")
        lines.append(f"   Runs: {e.run_count}{max_str}")
        lines.extend(detail_lines)
        lines.append("")

    return "\n".join(lines)


# ---------- NLP command handler -------------------------------------------

def process_schedule_command(user_text: str) -> str:
    """Try to interpret a natural-language command about schedules.

    Recognised patterns (case-insensitive):
    - ``list`` / ``show schedules`` / ``what is scheduled``
    - ``pause {name|id}`` / ``resume {name|id}``
    - ``delete {name|id}`` / ``remove {name|id}``
    - ``trigger {name|id}`` / ``run now {name|id}``

    Returns a descriptive text response.  Unrecognised text gets a
    helpful fallback message.
    """
    text = user_text.strip().lower()

    # ---- list / show ----
    if any(tok in text for tok in ("list", "show", "all", "what", "schedule")):
        if not any(tok in text for tok in ("delete", "remove", "pause", "resume", "trigger", "run")):
            return describe_schedules_as_text()

    # ---- pause ----
    pause_match = re.search(r'pause\s+(.+)', text)
    if pause_match:
        target = pause_match.group(1).strip()
        entry = _find_entry(target)
        if entry:
            entry.state = RunState.PAUSED
            update(entry)
            unsync_redbeat(entry.id)
            return f"Paused schedule: **{entry.name}** ({entry.id})"

    # ---- resume ----
    resume_match = re.search(r'resume\s+(.+)', text)
    if resume_match:
        target = resume_match.group(1).strip()
        entry = _find_entry(target)
        if entry:
            entry.state = RunState.ACTIVE
            update(entry)
            sync_redbeat(entry)
            return f"Resumed schedule: **{entry.name}** ({entry.id})"

    # ---- delete ----
    delete_match = re.search(r'(delete|remove|disable)\s+(.+)', text)
    if delete_match:
        target = delete_match.group(2).strip()
        entry = _find_entry(target)
        if entry:
            delete_schedule(entry.id)
            return f"Deleted schedule: **{entry.name}** ({entry.id})"

    # ---- manual trigger ----
    trigger_match = re.search(r'(trigger|run\s+now|fire)\s+(.+)', text)
    if trigger_match:
        target = trigger_match.group(2).strip()
        entry = _find_entry(target)
        if entry:
            result = manual_trigger(entry.id)
            return f"Triggered **{entry.name}** (task_id: {result['task_id']})"

    # ---- create (simplified) ----
    # e.g. "schedule {name} to run every 30 minutes"
    # We leave complex creation to the API for now and return a prompt.
    return (
        "I didn't understand that schedule command.  You can tell me to:\n"
        "- list / show schedules\n"
        "- pause *name* / resume *name*\n"
        "- delete *name*\n"
        "- trigger *name*\n"
        "Or use the /schedules API to create new schedules."
    )


def _find_entry(query: str) -> ScheduleEntry | None:
    """Look up a schedule by name (case-insensitive) or exact ID."""
    entries = list_all()
    for e in entries:
        if e.id == query or e.name.lower() == query.lower():
            return e
    # partial match fallback
    for e in entries:
        if query.lower() in e.name.lower():
            return e
    return None
