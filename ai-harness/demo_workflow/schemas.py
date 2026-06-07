"""
Pydantic models for the one-page clickable demo workflow pipeline.

Covers:
- API request/response schemas
- Pipeline state (carried across stages)
- Stage-specific output models
"""

from __future__ import annotations

import datetime
from typing import Any
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────
# API Schemas
# ──────────────────────────────────────────────────────────────────────────

class DemoCreateRequest(BaseModel):
    title: str = Field(..., description="Demo title (auto-generated from prompt if not given)")
    prompt: str = Field(..., description="What the demo should be — describe the app, features, style")
    model: str | None = Field(default=None, description="Override default LLM model")


class DemoCreateResponse(BaseModel):
    run_id: str
    workflow_id: str
    title: str
    status: str
    steps_count: int


class DemoMetadata(BaseModel):
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


# ──────────────────────────────────────────────────────────────────────────
# Stage Output Models
# ──────────────────────────────────────────────────────────────────────────

class DemoBrief(BaseModel):
    """Stage 1 output — structured brief from user prompt."""
    title: str
    description: str
    target_audience: str = ""
    key_features: list[str] = []
    screens_requested: list[str] = []
    style_hints: list[str] = []
    constraints: list[str] = []


class KbInsightItem(BaseModel):
    source: str = ""
    text: str = ""


class KbInsights(BaseModel):
    """Stage 2 output — KB lookup results."""
    query: str = ""
    has_prior_data: bool = False
    insights: str = ""
    items: list[KbInsightItem] = []


class WebSearchResult(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""


class WebInsights(BaseModel):
    """Stage 3 output — web research findings."""
    queries_used: list[str] = []
    sources: list[WebSearchResult] = []
    competitor_patterns: list[str] = []
    ux_patterns: list[str] = []
    feature_recommendations: list[str] = []
    summary: str = ""


class RequirementsAndDesignSpec(BaseModel):
    """Stage 4 output — merged requirements + visual design spec."""
    # Requirements
    requirements: list[str] = []
    screens: list[str] = []
    navigation_flow: str = ""
    placeholder_data_guidance: str = ""
    interactions: list[str] = []
    # Design spec
    color_palette: str = ""
    typography: str = ""
    layout_approach: str = ""
    visual_treatment: str = ""
    design_notes: str = ""


class BuildStep(BaseModel):
    """Single step in the build plan (Stage 5)."""
    step_number: int
    title: str
    description: str
    acceptance_criteria: str
    depends_on_step: int | None = None


class BuildPlan(BaseModel):
    """Stage 5 output — numbered implementation plan."""
    steps: list[BuildStep] = []
    notes: str = ""


class BuildStepResult(BaseModel):
    """Result of executing a single build step."""
    step_number: int
    step_title: str
    status: str = "success"          # success | failed
    validation_result: str = ""
    retries_used: int = 0
    issues: list[str] = []


class PolishResult(BaseModel):
    """Stage N+1 output — critique + fix results."""
    critique: str = ""
    issues_found: list[str] = []
    issues_fixed: int = 0
    fix_result: str = ""


class FinalSaveResult(BaseModel):
    """Stage N+2 output — final file paths and metadata."""
    final_html_path: str = ""
    metadata_path: str = ""
    build_dir_path: str = ""
    html_size_bytes: int = 0
    embedded_notes_preview: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Pipeline State (carried across all stages on disk)
# ──────────────────────────────────────────────────────────────────────────

class DemoPipelineState(BaseModel):
    run_id: str = ""
    title: str = ""
    prompt: str = ""
    slug: str = ""                      # generated in stage 1
    model_override: str | None = None

    # Stage outputs
    demo_brief: DemoBrief | None = None
    kb_insights: KbInsights | None = None
    web_insights: WebInsights | None = None
    requirements: RequirementsAndDesignSpec | None = None
    build_plan: BuildPlan | None = None
    build_step_results: list[dict] = []  # list of BuildStepResult dicts

    # HTML accumulator
    current_html: str = ""

    # Polish
    polish_result: dict | None = None   # PolishResult as dict

    # Open questions for final notes
    open_questions: list[str] = []

    class Config:
        arbitrary_types_allowed = True
