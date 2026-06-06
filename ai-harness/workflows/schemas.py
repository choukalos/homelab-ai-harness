"""Pydantic schemas for the workflow run state store."""

from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# ---------- Status enums ----------

class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"      # step skipped due to upstream failure or condition


# ---------- Artifact ----------

class ArtifactRecord(BaseModel):
    """A file, URL, or data blob produced by a step."""

    name: str = Field(description="Friendly name / label.")
    url: Optional[str] = Field(default=None, description="URL to the artifact.")
    filename: Optional[str] = Field(default=None, description="On-disk filename.")
    mime_type: Optional[str] = Field(default=None, description="MIME type.")
    size_bytes: int = Field(default=0, description="Size in bytes (if known).")
    metadata: dict = Field(default_factory=dict, description="Free-form extra data.")


# ---------- Step ----------

class StepDefinition(BaseModel):
    """Definition of a single workflow step (declarative, before execution)."""

    name: str = Field(description="Human-readable step name.")
    description: Optional[str] = Field(default=None)
    task_name: Optional[str] = Field(
        default=None,
        description="Celery task name to invoke (e.g. tasks.run_prompt). "
                    "If None the step is a no-op marker.",
    )
    task_kwargs: Optional[dict] = Field(
        default=None,
        description="Kwargs forwarded to the Celery task.",
    )
    depends_on: Optional[list[str]] = Field(
        default=None,
        description="Step names this step depends on. All must complete "
                    "successfully before this step runs.",
    )
    condition: Optional[str] = Field(
        default=None,
        description="Simple expression evaluated at runtime. "
                    "e.g. 'previous_step.output.status == 200'. "
                    "If false the step is SKIPPED.",
    )
    model: Optional[str] = Field(
        default=None,
        description="LLM model identifier (used as default for task_kwargs).",
    )
    max_retries: int = Field(default=0, ge=0, le=10, description="Retries on failure.")
    timeout_seconds: Optional[int] = Field(
        default=None,
        description="Per-step timeout override.",
    )


class StepResult(BaseModel):
    """Mutable state for a step that is actively running or has completed."""

    name: str
    step_index: int
    status: StepStatus = StepStatus.PENDING
    celery_task_id: Optional[str] = Field(
        default=None,
        description="Celery AsyncResult ID when task is dispatched.",
    )
    model: Optional[str] = Field(default=None)
    input_payload: Optional[dict] = Field(
        default=None,
        description="Merged task kwargs actually sent to Celery.",
    )
    output: Optional[dict] = Field(default=None)
    error: Optional[str] = Field(default=None)
    retry_count: int = Field(default=0)
    cost: Optional[float] = Field(
        default=None,
        description="Model cost in USD (if reported).",
    )
    input_tokens: Optional[int] = Field(default=None)
    output_tokens: Optional[int] = Field(default=None)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    started_at: Optional[str] = Field(default=None)
    finished_at: Optional[str] = Field(default=None)


# ---------- Workflow ----------

class WorkflowCreateRequest(BaseModel):
    """Request to create a new workflow definition."""

    name: str = Field(description="Workflow name / title.")
    description: Optional[str] = Field(default="", description="Free-text description.")
    tags: list[str] = Field(default_factory=list)
    steps: list[StepDefinition] = Field(
        min_length=1,
        description="Ordered step definitions.",
    )


class WorkflowRunRequest(BaseModel):
    """
    Optionally override per-run settings.
    If a full redefinition is desired, pass steps.  Otherwise the stored
    definition from WorkflowCreateRequest is used.
    """

    overrides: Optional[dict] = Field(
        default=None,
        description="Top-level overrides merged into step definitions. "
                    "e.g. {'steps': [{'name': 'step-1', 'model': 'gpt-4o'}]}.",
    )
    step_kwargs_overrides: Optional[dict] = Field(
        default=None,
        description="Per-step kwargs override keyed by step name. "
                    "e.g. {'summarize': {'prompt': 'Summarize this ...'}}.",
    )
    metadata: Optional[dict] = Field(default=None, description="Free-form run metadata.")


class WorkflowResponse(BaseModel):
    """Response after creating a workflow."""

    workflow_id: str
    name: str
    description: str
    tags: list[str]
    steps: list[StepDefinition]
    created_at: str


class WorkflowRunResponse(BaseModel):
    """Response after starting (or enqueuing) a workflow run."""

    run_id: str
    workflow_id: str
    status: WorkflowStatus
    steps: list[StepResult]
    metadata: Optional[dict]
    started_at: Optional[str]
    finished_at: Optional[str]


class StepUpdateRequest(BaseModel):
    """Used internally (and via API) to transition a step's state."""

    status: Optional[StepStatus] = None
    model: Optional[str] = None
    input_payload: Optional[dict] = None
    output: Optional[dict] = None
    error: Optional[str] = None
    retry_count: Optional[int] = None
    cost: Optional[float] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    celery_task_id: Optional[str] = None
    artifacts: Optional[list[ArtifactRecord]] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class RunUpdateRequest(BaseModel):
    """Used to update a run's status or metadata."""

    status: Optional[WorkflowStatus] = None
    metadata: Optional[dict] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


# ---------- Query filters ----------

class CompleteStepRequest(BaseModel):
    """Request body for the convenience complete-step endpoint."""

    output: Optional[dict] = Field(default=None, description="Structured step result.")
    model: Optional[str] = Field(default=None, description="LLM model identifier.")
    cost: Optional[float] = Field(default=None, description="Model cost in USD.")
    input_tokens: Optional[int] = Field(default=None)
    output_tokens: Optional[int] = Field(default=None)
    artifacts: Optional[list[ArtifactRecord]] = Field(default=None)


class WorkflowListFilters(BaseModel):
    workflow_id: Optional[str] = None
    status: Optional[WorkflowStatus] = None
    tags: Optional[list[str]] = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
