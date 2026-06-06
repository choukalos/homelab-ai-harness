"""Pydantic models for the scheduler HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScheduleTypeModel(str):
    """Alias for documentation — values aligned with models.ScheduleType."""
    ONETIME = "onetime"
    CRON = "cron"
    INTERVAL = "interval"
    CONDITION = "condition"


# ---------- Create / Update requests ----------

class CreateScheduleRequest(BaseModel):
    """Request body for POST /schedules."""
    name: str = Field(..., min_length=1, description="Human-readable name")
    description: str = Field("", description="Optional description")

    type: str = Field(
        "onetime",
        description="onetime | cron | interval | condition",
    )
    task_name: str = Field(
        ...,
        description="Celery task name to execute (e.g. tasks.run_prompt)",
    )
    task_kwargs: dict[str, Any] = Field(
        default_factory=dict,
        description="Keyword arguments forwarded to the task",
    )

    at: str | None = Field(
        None,
        description="ISO-8601 run time (required for onetime)",
    )
    cron_expr: str | None = Field(
        None,
        description="Cron expression (required for cron type)",
    )
    interval_seconds: int | None = Field(
        None,
        ge=1,
        description="Seconds between runs (required for interval type)",
    )
    condition_event: str | None = Field(
        None,
        description="Event name to watch (required for condition type)",
    )
    max_runs: int | None = Field(
        None,
        ge=1,
        description="After this many successful fires, expire the schedule",
    )


class UpdateScheduleRequest(BaseModel):
    """PATCH /schedules/{id} body — every field is optional."""
    name: str | None = None
    description: str | None = None
    type: str | None = None
    task_name: str | None = None
    task_kwargs: dict[str, Any] | None = None
    at: str | None = None
    cron_expr: str | None = None
    interval_seconds: int | None = None
    condition_event: str | None = None
    max_runs: int | None = None
    state: str | None = None   # "active" | "paused"


# ---------- Responses ----------

class ScheduleResponse(BaseModel):
    id: str
    name: str
    description: str
    type: str
    task_name: str
    task_kwargs: dict[str, Any]
    at: str | None
    cron_expr: str | None
    interval_seconds: int | None
    condition_event: str | None
    max_runs: int | None
    run_count: int
    state: str
    created_at: str | None
    last_run_at: str | None
    next_run_at: str | None

    @classmethod
    def from_entry(cls, e):
        return cls(
            id=e.id,
            name=e.name,
            description=e.description,
            type=e.type.value,
            task_name=e.task_name,
            task_kwargs=e.task_kwargs,
            at=e.at,
            cron_expr=e.cron_expr,
            interval_seconds=e.interval_seconds,
            condition_event=e.condition_event,
            max_runs=e.max_runs,
            run_count=e.run_count,
            state=e.state.value,
            created_at=e.created_at,
            last_run_at=e.last_run_at,
            next_run_at=e.next_run_at,
        )


class ConditionTriggerRequest(BaseModel):
    event_name: str = Field(..., description="Name of the condition/event")
    payload: dict[str, Any] = Field(default_factory=dict)
