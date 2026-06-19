"""Pydantic models for the demo workflow (Deep Agents harness).

Covers:
- API request/response schemas
- Demo metadata for discovery/indexing

Stage-specific models (DemoBrief, KbInsights, etc.) have been removed —
the agent handles all structure internally via its message history and
file-based artifacts (demo_brief.md, design_spec.md, build_plan.md).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────
# Request Schema
# ──────────────────────────────────────────────────────────────────────────

class DemoCreateRequest(BaseModel):
    """Request to kick off a demo creation run via Deep Agents."""

    prompt: str = Field(
        ...,
        description="What the demo should be — describe the app, features, style.",
    )
    title: str = Field(
        default="",
        description="Demo title (auto-generated from prompt if not given).",
    )
    thread_id: str | None = Field(
        default=None,
        description=(
            "Optional thread ID for checkpoint persistence / resumption. "
            "If omitted a new UUID is generated."
        ),
    )
    model: str | None = Field(
        default=None,
        description="Optional model override (defaults to HARNESS_MODEL).",
    )


# ──────────────────────────────────────────────────────────────────────────
# Response Schemas
# ──────────────────────────────────────────────────────────────────────────

class DemoCreateResponse(BaseModel):
    """Response after the demo creation agent finishes (or errors)."""

    thread_id: str = Field(description="Thread ID used for the run (for resumption).")
    title: str = Field(description="Demo title.")
    slug: str = Field(description="Filesystem slug for the demo output directory.")
    status: str = Field(
        description="Run status: 'completed', 'error', or the current build step name."
    )
    build_step: str = Field(
        default="",
        description="The last completed build phase (e.g. 'build_step_3', 'final_save').",
    )
    html_path: str = Field(
        default="",
        description="Path to the generated HTML file relative to the media directory.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted demo metadata (title, description, tags, URLs, etc.).",
    )
    error: str | None = Field(
        default=None,
        description="Error message if the run failed.",
    )


class DemoBuildError(BaseModel):
    """Error response for demo creation failures."""

    thread_id: str
    title: str
    slug: str
    status: str = "error"
    error: str


# ──────────────────────────────────────────────────────────────────────────
# Demo Metadata (for discovery / listing — persisted as metadata.json)
# ──────────────────────────────────────────────────────────────────────────

class DemoMetadata(BaseModel):
    """Metadata for a completed demo, persisted as metadata.json per demo."""

    title: str
    slug: str
    description: str
    tags: list[str] = []
    created_at: str = ""
    screens: list[str] = []
    local_url: str = ""
    public_url: str = ""
    requirements_summary: str = ""
    design_decisions: str = ""
    open_questions: list[str] = []
    # Enhanced verification metadata (from Phase 7 functional verification)
    mocked_features: list[dict[str, str]] = Field(
        default_factory=list,
        description="List of {feature, description, mock_type} objects documenting mocked behavior.",
    )
    functional_areas: list[str] = Field(
        default_factory=list,
        description="List of verified working interactions (e.g. 'Button X: onclick → fnY() → view Z').",
    )
    code_quality_score: int = Field(
        default=0,
        description="Score 1-10 from verify_interactivity static analysis.",
    )
    verification_issues: list[str] = Field(
        default_factory=list,
        description="Any remaining interactivity gaps or issues from verification.",
    )
    # Level 3 mock behavior patterns (from Phase 7 functional verification)
    level3_patterns: dict[str, bool] = Field(
        default_factory=dict,
        description="Level 3 mock behavior verification: simulated_delays, loading_indicators, toast_notifications, confirmation_dialogs, data_persistence, key_flow_coverage.",
    )
    # Product insights metadata (from Phase 4 design + Phase 5 plan)
    discovery_notes: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Product discovery insights: mvp_features, nice_to_have, research_insights.",
    )
    complexity_score: int = Field(
        default=0,
        description="Complexity score 1-10 (how complex is the demo to build).",
    )
    complexity_breakdown: dict[str, Any] = Field(
        default_factory=dict,
        description="Breakdown: screen_count, interactive_elements, mocked_features, estimated_build_effort.",
    )


# ──────────────────────────────────────────────────────────────────────────
# Checkpoint / Resume Schemas
# ──────────────────────────────────────────────────────────────────────────

class DemoCheckpointStatus(BaseModel):
    """Status of a checkpoint for a given thread ID."""

    thread_id: str = Field(description="The thread ID this checkpoint is for.")
    exists: bool = Field(description="Whether a checkpoint exists for this thread.")
    phase: int = Field(
        default=0,
        description="The last completed phase number (0 = none, 1-11 = phase index).",
    )
    phase_name: str = Field(
        default="",
        description="Human-readable name of the last completed phase.",
    )
    title: str = Field(
        default="",
        description="Demo title (from checkpoint state).",
    )
    created_at: str = Field(
        default="",
        description="When the checkpoint was created (ISO format).",
    )
    expires_at: str = Field(
        default="",
        description="When the checkpoint will expire (ISO format, 24h TTL).",
    )
    can_resume: bool = Field(
        default=False,
        description="Whether the pipeline can be resumed from this checkpoint.",
    )





# ──────────────────────────────────────────────────────────────────────────
# SSE Streaming Event Schema
# ──────────────────────────────────────────────────────────────────────────

class DemoStreamEvent(BaseModel):
    """A single SSE event emitted by the coordinator during demo creation.

    Supports real-time progress updates through OpenWebUI or any SSE consumer.

    Event types:
      - pipeline_start: Pipeline is about to begin (includes title, prompt, thread_id).
      - pipeline_resume: Resuming from a checkpoint (includes resume phase info).
      - phase_start: A phase has begun (includes phase name, number, estimated time).
      - phase_progress: Intermediate progress within a phase (e.g. attempt N/M).
      - phase_complete: A phase finished successfully (includes elapsed time, summary).
      - pipeline_complete: Entire pipeline finished (includes final metadata).
      - error: An unrecoverable error occurred.
    """

    event_type: str = Field(
        description="Event type: pipeline_start, pipeline_resume, phase_start, phase_progress, phase_complete, pipeline_complete, error.",
    )
    phase: str = Field(
        default="",
        description="Human-readable phase name (e.g. 'Phase 1: Parse Request').",
    )
    phase_number: int = Field(
        default=0,
        description="Phase index (0-based in the phases list, 0 = pre-pipeline).",
    )
    elapsed: str = Field(
        default="0:00",
        description="Elapsed time since pipeline start, formatted as m:ss.",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific payload (summary, metadata, error details, etc.).",
    )
