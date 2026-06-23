"""Internal data model for scheduled jobs."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any


class ScheduleType(str, Enum):
    ONCE     = "onetime"      # fire a single time at ``at``
    CRON     = "cron"         # fire on a repeated cron expression
    INTERVAL = "interval"     # fire every N seconds
    CONDITION= "condition"    # fire when a named condition event is pushed


class RunState(str, Enum):
    ACTIVE   = "active"
    PAUSED   = "paused"
    EXPIRED  = "expired"   # onetimes have already fired


# --------------- ScheduleEntry ---------------

@dataclass
class ScheduleEntry:
    """Everything needed to describe *what* to run and *when*."""

    # identity
    id: str

    # human‐friendly metadata
    name: str
    description: str = ""

    # what fires
    type: ScheduleType = ScheduleType.ONCE

    # target task identifier — maps to a Celery task name
    # e.g. "tasks.run_prompt", "tasks.python_executor", or any user-defined
    # task name registered in the harness.
    task_name: str = ""

    # kwargs passed to the task each time it fires
    task_kwargs: dict[str, Any] = field(default_factory=dict)

    # schedule‐specific fields
    at: str | None = None            # ISO‐8601 datetime for ``once``
    cron_expr: str | None = None     # "0 9 * * 1" for ``cron``
    interval_seconds: int | None = None  # ``interval``

    # condition
    condition_event: str | None = None  # event name for ``condition`` type

    # safety limits
    max_runs: int | None = None      # leave None for unlimited
    run_count: int = 0

    # state
    state: RunState = RunState.ACTIVE

    # timestamps
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_run_at: str | None = None
    next_run_at: str | None = None

    # ------ helpers ------

    def to_dict(self) -> dict[str, Any]:
        """Return a Redis‐safe dict (all values JSON‐serialisable)."""
        d = asdict(self)
        # Enum → str
        d["type"] = self.type.value
        d["state"] = self.state.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScheduleEntry":
        """Reconstruct from a Redis / JSON dict."""
        d = dict(d)  # shallow copy
        if "type" in d and isinstance(d["type"], str):
            d["type"] = ScheduleType(d["type"])
        if "state" in d and isinstance(d["state"], str):
            d["state"] = RunState(d["state"])
        return cls(**d)
