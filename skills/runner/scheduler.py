#!/usr/bin/env python3
"""
SimpleScheduler — cron-like task scheduler for the Thor Skill Runner.

Parses a JSON config file containing scheduled job definitions,
matches entries on a cron-like schedule, and dispatches matching
jobs to the skill runner.

Config schema (file path is configurable, default ~/.thor/scheduler.json):

  {
    "schedules": [
      {
        "id": "daily-morning-brief",
        "name": "Daily Morning Brief",
        "cron": "0 7 * * *",
        "skill": "morning_brief",
        "params": {"scope": "homelab", "channel": "siri"},
        "enabled": true,
        "timezone": "UTC"
      }
    ]
  }

Cron format: minute hour day_of_month month day_of_week
  - Supports standard cron fields (0-59, 0-23, 1-31, 1-12, 0-6)
  - Supports wildcards (*), step values (*/15), ranges (1-5), and lists (1,3,5)
  - Default timezone is UTC (can be overridden per-schedule)
"""

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("skill_runner.scheduler")

# ---------------------------------------------------------------------------
# Default config path
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = os.path.join(
    os.path.expanduser("~"), ".thor", "scheduler.json"
)


# ---------------------------------------------------------------------------
# Cron field parser
# ---------------------------------------------------------------------------


class CronField:
    """
    Represents a single cron field (minute, hour, day, month, weekday).

    Supports:
      - ``*``  (any value)
      - ``*/N`` (every N-th value)
      - ``A-B`` (range)
      - ``A,B,C`` (list)
      - Combinations: ``1-5,10,*/2``
    """

    def __init__(self, expression: str, min_val: int, max_val: int) -> None:
        self.min_val = min_val
        self.max_val = max_val
        self.allowed_values: set[int] = set()

        for part in expression.split(","):
            part = part.strip()
            if part == "*":
                self.allowed_values.update(range(min_val, max_val + 1))
            elif part.startswith("*/"):
                step = int(part[2:])
                if step <= 0:
                    raise ValueError(f"Step must be positive: {part}")
                self.allowed_values.update(range(min_val, max_val + 1, step))
            elif "-" in part:
                range_parts = part.split("-")
                if len(range_parts) != 2:
                    raise ValueError(f"Invalid range: {part}")
                start, end = int(range_parts[0]), int(range_parts[1])
                if start > end:
                    raise ValueError(f"Invalid range: {part}")
                self.allowed_values.update(range(start, end + 1))
            else:
                val = int(part)
                if val < min_val or val > max_val:
                    raise ValueError(
                        f"Value {val} out of range [{min_val}-{max_val}] in field '{expression}'"
                    )
                self.allowed_values.add(val)

    def matches(self, value: int) -> bool:
        """Check if the given integer value matches this cron field."""
        return value in self.allowed_values


# ---------------------------------------------------------------------------
# Cron expression parser
# ---------------------------------------------------------------------------


class CronExpression:
    """
    Parses and matches a 5-field cron expression.

    Fields: minute hour day_of_month month day_of_week
    """

    # Cron field specs: (name, min, max)
    _FIELD_SPECS = [
        ("minute", 0, 59),
        ("hour", 0, 23),
        ("day_of_month", 1, 31),
        ("month", 1, 12),
        ("day_of_week", 0, 6),  # 0=Sunday
    ]

    def __init__(self, expression: str) -> None:
        parts = expression.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"Cron expression must have 5 fields, got {len(parts)}: '{expression}'"
            )

        self.fields: list[CronField] = []
        for i, (name, min_val, max_val) in enumerate(self._FIELD_SPECS):
            try:
                self.fields.append(CronField(parts[i], min_val, max_val))
            except ValueError as exc:
                raise ValueError(f"Invalid {name} field '{parts[i]}': {exc}")

    def matches_datetime(self, dt: datetime) -> bool:
        """
        Check if the given datetime matches this cron expression.

        Day-of-week matching follows the standard cron convention:
        when both day_of_month and day_of_week are restricted (not *),
        the job fires when *either* matches (OR logic).
        When only one is restricted, that one is used (AND logic for the other fields).
        """
        # Check minute and hour first (always required)
        if not self.fields[0].matches(dt.minute):
            return False
        if not self.fields[1].matches(dt.hour):
            return False

        # Day matching: standard cron OR logic when both are restricted
        # Month must always match
        if not self.fields[3].matches(dt.month):
            return False

        dom_field = self.fields[2]   # day_of_month
        dow_field = self.fields[4]   # day_of_week
        dom_any = dom_field.allowed_values == set(range(1, 32))
        dow_any = dow_field.allowed_values == set(range(0, 7))

        # Convert Python weekday (0=Mon..6=Sun) to cron weekday (0=Sun..6=Sat)
        cron_wday = (dt.weekday() + 1) % 7

        if dom_any and dow_any:
            return True
        elif dom_any:
            return dow_field.matches(cron_wday)
        elif dow_any:
            return dom_field.matches(dt.day)
        else:
            # Both restricted: OR logic (standard cron behaviour)
            return dom_field.matches(dt.day) or dow_field.matches(cron_wday)

    def next_trigger(self, after: datetime) -> Optional[datetime]:
        """
        Compute the next datetime after ``after`` that matches this expression.

        Brute-force search starting from the next minute. Limits search to 4
        years to avoid infinite loops with invalid expressions.
        """
        from datetime import timedelta

        candidate = after.replace(second=0, microsecond=0)
        # Start from the next minute
        candidate += timedelta(minutes=1)
        max_iterations = 366 * 24 * 60 * 4  # ~4 years of minutes
        for _ in range(max_iterations):
            if self.matches_datetime(candidate):
                return candidate
            candidate += timedelta(minutes=1)
        return None  # No match found within 4 years


# ---------------------------------------------------------------------------
# Schedule entry
# ---------------------------------------------------------------------------


class ScheduleEntry:
    """A single scheduled job definition."""

    def __init__(
        self,
        id: str,
        name: str,
        cron: str,
        skill: str,
        params: Optional[dict[str, Any]] = None,
        enabled: bool = True,
        timezone: str = "UTC",
    ) -> None:
        self.id = id
        self.name = name
        self.cron = cron
        self.skill = skill
        self.params = params or {}
        self.enabled = enabled
        self.timezone = timezone
        self.expression: Optional[CronExpression] = None
        self.last_run_at: Optional[str] = None
        self.next_run_at: Optional[str] = None

        # Parse cron expression
        try:
            self.expression = CronExpression(cron)
        except ValueError as exc:
            logger.error(
                "Invalid cron expression for schedule '%s' (%s): %s",
                self.id, self.name, exc,
            )
            self.enabled = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict (for JSON response)."""
        return {
            "id": self.id,
            "name": self.name,
            "cron": self.cron,
            "skill": self.skill,
            "params": self.params,
            "enabled": self.enabled,
            "timezone": self.timezone,
            "last_run_at": self.last_run_at,
            "next_run_at": self.next_run_at,
        }

    def _local_now(self, now_utc: datetime) -> datetime:
        """Convert a UTC datetime into this schedule's configured timezone.

        Cron matching is done in the entry's local time so that
        ``cron: 0 17 * * *`` + ``timezone: America/Chicago`` fires at 17:00
        CDT, not 17:00 UTC. Invalid/missing timezones fall back to UTC.
        """
        if not self.timezone or self.timezone == "UTC":
            return now_utc
        try:
            from zoneinfo import ZoneInfo
            return now_utc.astimezone(ZoneInfo(self.timezone))
        except Exception as exc:  # noqa: BLE001 - degrade to UTC
            logger.warning(
                "Schedule '%s': invalid timezone '%s' (%s) — using UTC.",
                self.id, self.timezone, exc,
            )
            return now_utc

    def matches_now(self, now: datetime) -> bool:
        """Check if this schedule should fire at the given datetime (UTC).

        The datetime is converted to the schedule's local timezone before
        cron matching (see ``_local_now``).
        """
        if not self.enabled or self.expression is None:
            return False
        return self.expression.matches_datetime(self._local_now(now))

    def compute_next_run(self, after: datetime) -> Optional[str]:
        """Compute next run time as ISO string (local-time wall clock)."""
        if self.expression is None:
            return None
        next_dt = self.expression.next_trigger(self._local_now(after))
        if next_dt:
            self.next_run_at = next_dt.isoformat()
        else:
            self.next_run_at = None
        return self.next_run_at


# ---------------------------------------------------------------------------
# SimpleScheduler
# ---------------------------------------------------------------------------


class SimpleScheduler:
    """
    Lightweight cron-like scheduler for skill dispatch.

    - Loads schedule definitions from a JSON config file.
    - Runs a background thread that checks every 60 seconds.
    - Dispatches matching schedules by creating jobs via the
      registered ``dispatch_fn`` callback.
    - Persists config (with last_run timestamps) back to JSON on changes.

    The scheduler is designed to integrate cleanly with the Thor
    Skill Runner's ``main.py`` — it does not run its own event loop
    or HTTP server.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        dispatch_fn: Optional[Callable[[str, dict[str, Any], dict[str, Any]], None]] = None,
        check_interval: float = 60.0,
    ) -> None:
        """
        Args:
            config_path: Path to JSON config file. Defaults to ``~/.thor/scheduler.json``.
            dispatch_fn: Callback called as ``dispatch_fn(skill, params, meta)`` for each
                         scheduled job. If None, the scheduler logs but does not dispatch.
            check_interval: Seconds between schedule checks (default 60).
        """
        self.config_path = Path(config_path or DEFAULT_CONFIG_PATH)
        self.dispatch_fn = dispatch_fn
        self.check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._schedules: dict[str, ScheduleEntry] = {}
        self._lock = threading.Lock()
        self._last_check_time: Optional[str] = None
        self._shutdown_event = threading.Event()

    # -----------------------------------------------------------------------
    # Lifecycle — start / stop / run loop
    # -----------------------------------------------------------------------

    def _run_loop(self) -> None:
        """
        Main scheduler loop, runs in a dedicated background thread.

        Every ``check_interval`` seconds, scans all enabled schedules and
        dispatches any whose cron expression matches the current time.
        Persists the config (with updated last_run_at timestamps) after
        each dispatch cycle.
        """
        logger.info("Scheduler thread started (check_interval=%.1fs).", self.check_interval)
        self.load_config()

        while not self._shutdown_event.is_set():
            now = datetime.now(timezone.utc)
            self._last_check_time = now.isoformat()

            with self._lock:
                schedules = list(self._schedules.values())

            for sched in schedules:
                if not sched.enabled or sched.expression is None:
                    continue
                if sched.matches_now(now):
                    logger.info(
                        "Schedule '%s' (%s) matched at %s — dispatching skill '%s'.",
                        sched.id, sched.name, now.isoformat(), sched.skill,
                    )
                    sched.last_run_at = now.isoformat()
                    sched.compute_next_run(now)

                    # Dispatch via callback if available
                    if self.dispatch_fn is not None:
                        try:
                            self.dispatch_fn(
                                sched.skill,
                                sched.params,
                                {"schedule_id": sched.id, "schedule_name": sched.name},
                            )
                        except Exception as exc:
                            logger.error(
                                "Dispatch error for schedule '%s': %s",
                                sched.id, exc, exc_info=True,
                            )

            # Persist updated state (last_run_at, next_run_at)
            self.save_config()

            # Wait for next check interval or until shutdown
            self._shutdown_event.wait(self.check_interval)

        logger.info("Scheduler thread stopped.")

    def start(self) -> None:
        """
        Start the scheduler background thread.

        If the thread is already running, does nothing.
        """
        if self._running:
            logger.info("Scheduler is already running — ignoring start().")
            return

        self._running = True
        self._shutdown_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="scheduler-loop",
            daemon=True,  # Won't block process exit if not stopped gracefully
        )
        self._thread.start()
        logger.info("Scheduler background thread started.")

    def stop(self) -> None:
        """
        Gracefully stop the scheduler background thread.

        Signals the thread to finish its current iteration, then joins it
        with a timeout. Saves config one last time.
        """
        if not self._running:
            logger.info("Scheduler is not running — ignoring stop().")
            return

        logger.info("Stopping scheduler background thread…")
        self._running = False
        self._shutdown_event.set()

        if self._thread is not None:
            self._thread.join(timeout=10.0)
            if self._thread.is_alive():
                logger.warning("Scheduler thread did not stop within 10s timeout.")

        # Final persistence
        self.save_config()
        self._thread = None
        logger.info("Scheduler stopped.")

    # -----------------------------------------------------------------------
    # Config loading / saving
    # -----------------------------------------------------------------------

    def load_config(self) -> int:
        """
        Load schedule definitions from the JSON config file.

        Returns the number of schedules loaded (including pre-existing ones
        that were already in memory).

        If the file does not exist, creates a default empty config.
        """
        new_entries: list[dict[str, Any]] = []

        if self.config_path.is_file():
            try:
                raw = self.config_path.read_text(encoding="utf-8")
                data = json.loads(raw)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to read scheduler config: %s", exc)
                self._create_default_config()
                data = {"schedules": []}

            # Preserve in-memory state for existing entries (last_run_at)
            existing = {sid: s for sid, s in self._schedules.items()}

            for entry in data.get("schedules", []):
                sid = entry.get("id", uuid.uuid4().hex[:12])
                if sid in existing:
                    # Preserve runtime state
                    prev = existing[sid]
                    entry.setdefault("last_run_at", prev.last_run_at)
                    entry.setdefault("next_run_at", prev.next_run_at)

                params = entry.get("params", {})
                enabled = entry.get("enabled", True)
                tz_str = entry.get("timezone", "UTC")

                schedule = ScheduleEntry(
                    id=sid,
                    name=entry.get("name", sid),
                    cron=entry.get("cron", "* * * * *"),
                    skill=entry.get("skill", ""),
                    params=params,
                    enabled=enabled,
                    timezone=tz_str,
                )
                schedule.last_run_at = entry.get("last_run_at")
                schedule.next_run_at = entry.get("next_run_at")

                self._schedules[sid] = schedule
                new_entries.append(entry)
                logger.info(
                    "Loaded schedule: id=%s name=%s cron=%s skill=%s enabled=%s",
                    sid, schedule.name, schedule.cron, schedule.skill, enabled,
                )

            # Compute next run for all schedules
            now = datetime.now(timezone.utc)
            for sched in self._schedules.values():
                sched.compute_next_run(now)

        else:
            logger.info("Config file not found at %s — creating default config.", self.config_path)
            self._create_default_config()

        self._last_check_time = datetime.now(timezone.utc).isoformat()
        logger.info("Scheduler config loaded: %d schedule(s).", len(self._schedules))
        return len(self._schedules)

    def _create_default_config(self) -> None:
        """Create a default empty config file."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        default = {"schedules": []}
        self.config_path.write_text(
            json.dumps(default, indent=2), encoding="utf-8"
        )

    def save_config(self) -> None:
        """Persist current schedule state (including last_run_at) back to JSON."""
        with self._lock:
            schedules_data = [s.to_dict() for s in self._schedules.values()]

        data = {"schedules": schedules_data}
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(
                json.dumps(data, indent=2, default=str), encoding="utf-8"
            )
            logger.debug("Scheduler config saved to %s", self.config_path)
        except OSError as exc:
            logger.error("Failed to save scheduler config: %s", exc)

    # -----------------------------------------------------------------------
    # Schedule management
    # -----------------------------------------------------------------------

    def add_schedule(
        self,
        name: str,
        cron: str,
        skill: str,
        params: Optional[dict[str, Any]] = None,
        enabled: bool = True,
        tz: str = "UTC",
    ) -> str:
        """
        Add a new schedule entry.

        Returns the generated schedule ID.
        """
        sid = uuid.uuid4().hex[:12]
        schedule = ScheduleEntry(
            id=sid,
            name=name,
            cron=cron,
            skill=skill,
            params=params or {},
            enabled=enabled,
            timezone=tz,
        )
        with self._lock:
            self._schedules[sid] = schedule

        now = datetime.now(timezone.utc)
        schedule.compute_next_run(now)
        self.save_config()
        logger.info("Added schedule: id=%s name=%s", sid, name)
        return sid

    def remove_schedule(self, schedule_id: str) -> bool:
        """Remove a schedule by ID. Returns True if found and removed."""
        with self._lock:
            removed = self._schedules.pop(schedule_id, None)
        if removed:
            self.save_config()
            logger.info("Removed schedule: id=%s", schedule_id)
            return True
        logger.warning("Schedule not found for removal: id=%s", schedule_id)
        return False

    def get_schedule(self, schedule_id: str) -> Optional[dict[str, Any]]:
        """Get a single schedule as a dict (or None)."""
        with self._lock:
            sched = self._schedules.get(schedule_id)
        return sched.to_dict() if sched else None

    def list_schedules(self) -> list[dict[str, Any]]:
        """List all schedules as dicts."""
        with self._lock:
            return [s.to_dict() for s in self._schedules.values()]

    def update_schedule(
        self,
        schedule_id: str,
        **kwargs: Any,
    ) -> Optional[dict[str, Any]]:
        """
        Update fields of an existing schedule.

        Supported kwargs: name, cron, skill, params, enabled, timezone.
        Returns updated schedule dict or None if not found.
        """
        valid_fields = {"name", "cron", "skill", "params", "enabled", "timezone"}
        updates = {k: v for k, v in kwargs.items() if k in valid_fields and v is not None}

        with self._lock:
            sched = self._schedules.get(schedule_id)
        if not sched:
            logger.warning("Schedule not found for update: id=%s", schedule_id)
            return None

        with self._lock:
            for field, value in updates.items():
                if field == "cron" and value != sched.cron:
                    try:
                        sched.expression = CronExpression(value)
                    except ValueError as exc:
                        logger.error("Invalid cron in update: %s", exc)
                        continue
                    sched.cron = value
                elif field == "params":
                    sched.params = value
                else:
                    setattr(sched, field, value)

            # Recompute next run if cron changed
            if "cron" in updates:
                sched.compute_next_run(datetime.now(timezone.utc))

        self.save_config()
        logger.info("Updated schedule: id=%s fields=%s", schedule_id, list(updates.keys()))
        return sched.to_dict()

    # -----------------------------------------------------------------------
    # Job dispatch
    # -----------------------------------------------------------------------

    def dispatch_job(
        self,
        schedule: ScheduleEntry,
        extra_meta: Optional[dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Dispatch a scheduled job via the registered dispatch callback.

        Returns the job_id if dispatch was successful, None otherwise.
        """
        if not self.dispatch_fn:
            logger.warning(
                "No dispatch function registered — skipping job for schedule '%s'",
                schedule.id,
            )
            return None

        meta = {
            "schedule_id": schedule.id,
            "schedule_name": schedule.name,
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }
        if extra_meta:
            meta.update(extra_meta)

        try:
            result = self.dispatch_fn(schedule.skill, schedule.params, meta)
            job_id = result if isinstance(result, str) else None

            schedule.last_run_at = meta["triggered_at"]
            schedule.compute_next_run(datetime.now(timezone.utc))
            self.save_config()

            logger.info(
                "Dispatched scheduled job: schedule=%s skill=%s job_id=%s",
                schedule.id, schedule.skill, job_id or "(none)",
            )
            return job_id

        except Exception as exc:
            logger.error(
                "Error dispatching scheduled job '%s': %s", schedule.id, exc
            )
            return None

    def run_now(self, schedule_id: str) -> Optional[str]:
        """
        Immediately execute a schedule (ignoring cron timing).

        Returns the job_id if dispatched, None if schedule not found.
        """
        with self._lock:
            sched = self._schedules.get(schedule_id)

        if not sched:
            logger.warning("Schedule not found for run-now: id=%s", schedule_id)
            return None

        if not sched.enabled:
            logger.warning("Schedule is disabled, skipping run-now: id=%s", schedule_id)
            return None

        return self.dispatch_job(
            sched, extra_meta={"trigger": "manual", "run_now": True}
        )

    # -----------------------------------------------------------------------
    # Background scheduler thread
    # -----------------------------------------------------------------------

    # (The new _run_loop / start / stop methods are defined above)

    # -----------------------------------------------------------------------
    # Status / diagnostics
    # -----------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return scheduler status for monitoring."""
        return {
            "running": self._running,
            "config_path": str(self.config_path),
            "schedules_count": len(self._schedules),
            "enabled_count": sum(1 for s in self._schedules.values() if s.enabled),
            "last_check_time": self._last_check_time,
            "check_interval": self.check_interval,
        }