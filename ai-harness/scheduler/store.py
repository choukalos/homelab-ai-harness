"""Redis-backed persistent store for scheduled jobs.

All schedule entries are kept in a Redis hash set keyed by
``harness:schedules``.  Individual entries are stored as JSON hashes under
``harness:schedule:{id}``.

This makes schedules durable across restarts without needing a separate
database.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from redis import Redis

from core.config import REDIS_URL
from scheduler.models import RunState, ScheduleEntry

SET_KEY = "harness:schedules"
ENTRY_KEY_PREFIX = "harness:schedule:"


def _get_conn() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


# -- collection helpers --

def _entry_key(entry_id: str) -> str:
    return f"{ENTRY_KEY_PREFIX}{entry_id}"


def _entry_exists(conn: Redis, entry_id: str) -> bool:
    return conn.exists(_entry_key(entry_id)) > 0


def _add_to_set(conn: Redis, entry_id: str) -> None:
    conn.sadd(SET_KEY, entry_id)


def _remove_from_set(conn: Redis, entry_id: str) -> None:
    conn.srem(SET_KEY, entry_id)


# -- CRUD --

def create(entry: ScheduleEntry) -> ScheduleEntry:
    """Persist a new schedule entry.  Assigns an ID if not set."""
    if not entry.id:
        entry.id = str(uuid.uuid4())
    conn = _get_conn()
    pipe = conn.pipeline(True)
    pipe.set(_entry_key(entry.id), json.dumps(entry.to_dict()))
    pipe.sadd(SET_KEY, entry.id)
    pipe.execute()
    return entry


def get(entry_id: str) -> ScheduleEntry | None:
    """Fetch a single entry by ID."""
    conn = _get_conn()
    raw = conn.get(_entry_key(entry_id))
    if raw is None:
        return None
    return ScheduleEntry.from_dict(json.loads(raw))


def update(entry: ScheduleEntry) -> ScheduleEntry:
    """Overwrite an existing entry."""
    if not entry.id:
        raise ValueError("Cannot update entry without an id")
    conn = _get_conn()
    pipe = conn.pipeline(True)
    pipe.set(_entry_key(entry.id), json.dumps(entry.to_dict()))
    pipe.sadd(SET_KEY, entry.id)  # ensure it's in the set
    pipe.execute()
    return entry


def delete(entry_id: str) -> bool:
    """Remove a schedule entry.  Returns True if it existed."""
    conn = _get_conn()
    pipe = conn.pipeline(True)
    raw = conn.get(_entry_key(entry_id))
    if raw is None:
        return False
    # Also nuke any redbeat schedule entry so beat won't fire it again
    pipe.delete(_entry_key(entry_id))
    pipe.srem(SET_KEY, entry_id)
    pipe.execute()
    return True


def list_all() -> list[ScheduleEntry]:
    """Return every persisted schedule entry."""
    conn = _get_conn()
    ids = conn.smembers(SET_KEY)
    entries: list[ScheduleEntry] = []
    for eid in ids:
        raw = conn.get(_entry_key(eid))
        if raw:
            entries.append(ScheduleEntry.from_dict(json.loads(raw)))
    return entries


def bump_run_count(entry_id: str, last_run: str | None = None) -> None:
    """Increment run_count and optionally set last_run_at (read-modify-write)."""
    entry = get(entry_id)
    if entry is None:
        return
    entry.run_count += 1
    if last_run:
        entry.last_run_at = last_run
    update(entry)


def mark_expired(entry_id: str) -> None:
    """Transition an entry to EXPIRED state."""
    entry = get(entry_id)
    if entry is None:
        return
    entry.state = RunState.EXPIRED
    update(entry)
