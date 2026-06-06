"""Pydantic models for the task queue API."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class PromptTaskRequest(BaseModel):
    prompt: str = Field(..., description="The user prompt to send to the LLM")
    model: str | None = Field(None, description="Model identifier (optional)")
    system: str | None = Field(None, description="System prompt (optional)")
    max_tokens: int | None = Field(None, description="Max tokens (optional)")


class ChainStep(BaseModel):
    prompt: str = Field(..., description="Prompt for this step")
    system: str | None = Field(None, description="System prompt for this step")


class ChainTaskRequest(BaseModel):
    steps: list[ChainStep] = Field(..., min_length=1, description="Chain steps")
    model: str | None = Field(None, description="Model identifier (optional)")


class PythonExecutorRequest(BaseModel):
    code: str = Field(..., description="Python source code to execute")
    globals_dict: dict[str, Any] | None = Field(None)
    locals_dict: dict[str, Any] | None = Field(None)


class TaskResult(BaseModel):
    task_id: str
    status: TaskStatus
    result: Any = None
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WorkerStatus(BaseModel):
    worker: str
    hostname: str
    pid: int
    clock: float
    active: list
    processed: int


class WorkerListResponse(BaseModel):
    workers: list[WorkerStatus]
