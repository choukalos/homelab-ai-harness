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
