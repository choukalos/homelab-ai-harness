"""Pydantic schemas for the deep_research workflow (Deep Agents harness)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------- Request ----------

class DeepResearchRequest(BaseModel):
    """Request to kick off a deep-research run via Deep Agents."""

    query: str = Field(
        description="The research question or topic.",
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


# ---------- Response ----------

class DeepResearchResponse(BaseModel):
    """Response after the deep-research agent finishes (or errors)."""

    thread_id: str = Field(description="Thread ID used for the run (for resumption).")
    query: str = Field(description="Original query.")
    answer: str = Field(description="Agent's final answer / summary.")
    sources: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Search results / source material the agent used.",
    )
    steps: list[dict[str, Any]] = Field(
        default_factory=list,
        description="High-level steps the agent took (todo list, tool calls, etc.).",
    )
    error: str | None = Field(default=None, description="Error message if the run failed.")
