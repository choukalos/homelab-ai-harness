"""Pydantic schemas for the market research workflow."""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, Literal


# ---------- Job input ----------

class MarketResearchRequest(BaseModel):
    """
    Top-level request to kick off a market research report.

    Input is intentionally minimal — a single market string. Everything
    else is derived by the pipeline.
    """

    market: str = Field(
        ...,
        min_length=1,
        description="Target market name (e.g. 'Smart Home', 'Electric Vehicles').",
    )
    schedule: Literal["annual", "quarterly", "monthly", "on_demand"] = Field(
        default="on_demand",
        description="Desired report cadence.",
    )


# ---------- Stage 1: KB Lookup ----------

class KbLookupResult(BaseModel):
    """Result of querying the Knowledge Base for prior research."""

    query: str
    existing_reports: list[str] = Field(default_factory=list)
    prior_vectors: list[str] = Field(
        default_factory=list,
        description="Previously used comparison vectors for this market.",
    )
    insights: str = Field(
        default="",
        description="Narrative summary of KB findings.",
    )
    has_prior_data: bool = False


# ---------- Stage 2: Competitor Discovery & Tiering ----------

class Competitor(BaseModel):
    """A single market player discovered during research."""

    name: str
    tier: Literal["top_player", "established", "new_entrant"] = Field(
        default="established",
        description="Market tier classification.",
    )
    primary_url: str = Field(default="", description="Main company / product URL.")
    description: str = Field(
        default="",
        description="One-line description of the company/product.",
    )
    founded_year: Optional[int] = None
    headquarters: Optional[str] = None


class CompetitorDiscoveryResult(BaseModel):
    """Output of the competitor discovery & tiering stage."""

    market: str
    top_players: list[Competitor] = Field(default_factory=list)
    established: list[Competitor] = Field(default_factory=list)
    new_entrants: list[Competitor] = Field(default_factory=list)
    all_competitors: list[Competitor] = Field(default_factory=list)
    search_queries_used: list[str] = Field(default_factory=list)


# ---------- Stage 3: Competitor Deep-Dive ----------

class CompetitorProfile(BaseModel):
    """
    Detailed competitive profile generated for a single entity.
    Written to a per-competitor markdown file on disk.
    """

    name: str
    tier: str
    url: str
    positioning: str = Field(
        default="",
        description="How the company positions itself in the market.",
    )
    value_propositions: list[str] = Field(default_factory=list)
    offers_services: list[str] = Field(default_factory=list)
    pricing_tiers: list[str] = Field(default_factory=list)
    feature_presentations: list[str] = Field(default_factory=list)
    summary: str = Field(
        default="",
        description="Condensed one-paragraph summary.",
    )
    raw_markdown: str = Field(
        default="",
        description="Full markdown content written to disk.",
    )


class DeepDiveResult(BaseModel):
    """Aggregate result for the deep-dive stage."""

    market: str
    profiles: list[CompetitorProfile] = Field(default_factory=list)
    failed_scrapes: list[str] = Field(
        default_factory=list,
        description="URLs that failed to scrape.",
    )


# ---------- Stage 4: Vector / Theme Identification ----------

class ComparisonVector(BaseModel):
    """A single comparison dimension across competitors."""

    name: str
    description: str = Field(default="", description="What this vector measures.")
    source: Literal["kb", "discovered"] = Field(
        default="discovered",
        description="Whether the vector came from KB or was newly discovered.",
    )
    rationale: str = Field(
        default="",
        description="Why this vector was included (for newly discovered).",
    )


class VectorIdentificationResult(BaseModel):
    """Result of vector/theme identification."""

    vectors: list[ComparisonVector] = Field(default_factory=list)
    new_vectors_flagged: list[ComparisonVector] = Field(
        default_factory=list,
        description="Newly discovered vectors proposed for KB.",
    )
    themes: list[str] = Field(default_factory=list)


# ---------- Stage 5: Data Population ----------

class ComparisonCell(BaseModel):
    """A single cell in the comparison matrix."""

    value: Optional[str] = Field(default=None)
    normalized: bool = Field(
        default=False,
        description="Whether the value was normalized from raw text.",
    )
    source_stage: Optional[int] = None


class ComparisonMatrixResult(BaseModel):
    """Populated comparison matrix (competitors x vectors)."""

    header_vectors: list[str] = Field(default_factory=list)
    rows: list[dict] = Field(
        default_factory=list,
        description="List of dicts keyed by vector name.",
    )
    missing_cells: int = Field(default=0)


# ---------- Stage 6: Tier Analysis ----------

class TierAnalysis(BaseModel):
    """Narrative analysis for a single tier."""

    tier_name: str
    competitor_count: int = 0
    collective_behaviors: list[str] = Field(default_factory=list)
    market_positioning: str = ""
    value_point_clustering: list[str] = Field(default_factory=list)
    summary_narrative: str = ""


class TierAnalysisResult(BaseModel):
    """Combined tier analyses."""

    tiers: list[TierAnalysis] = Field(default_factory=list)


# ---------- Stage 7: Executive Summary ----------

class ExecutiveSummaryResult(BaseModel):
    """High-level executive summary text."""

    market: str
    executive_summary: str = Field(default="")
    key_findings: list[str] = Field(default_factory=list)
    total_competitors_analyzed: int = 0


# ---------- Stage 8: Innovation & Opportunity ----------

class OpportunityFlag(BaseModel):
    """A whitespace / opportunity spotted in the data."""

    category: Literal["emerging_trend", "untested_feature", "pricing_divergence", "market_whitespace"]
    description: str
    evidence: str = Field(
        default="",
        description="Supporting evidence from the dataset.",
    )


class InnovationScoutingResult(BaseModel):
    """Innovation & opportunity analysis."""

    opportunities: list[OpportunityFlag] = Field(default_factory=list)
    emerging_trends: list[str] = Field(default_factory=list)
    whitespace_summary: str = ""


# ---------- Stage 9: Visual & Layout Planning ----------

class VisualAssetSpec(BaseModel):
    """Specification for a visual element in the final report."""

    asset_type: Literal["chart", "table", "image", "text_block"]
    zone: str = Field(description="Target layout zone name.")
    chart_config: Optional[dict] = None
    table_columns: Optional[list[dict]] = None
    table_rows: Optional[list[dict]] = None
    text_content: Optional[str] = None
    description: str = ""
    title: str = ""


class LayoutPlanResult(BaseModel):
    """Complete visual & layout plan for the report."""

    template: str = Field(default="minimal")
    title: str = ""
    visual_assets: list[VisualAssetSpec] = Field(default_factory=list)


# ---------- Stage 10: Report Assembly ----------

class ReportAssemblyResult(BaseModel):
    """Final report assembly result."""

    market: str
    pdf_path: str = ""
    pdf_url: str = ""
    pdf_bytes: int = 0
    html_path: str = ""
    intermediate_files: list[str] = Field(
        default_factory=list,
        description="Paths to intermediate markdown / JSON files.",
    )
    total_cost: float = Field(default=0.0, description="Total USD cost of LLM calls.")
    total_tokens_input: int = Field(default=0)
    total_tokens_output: int = Field(default=0)


# ---------- Intermediate state (shared across stages) ----------

class MarketResearchState(BaseModel):
    """
    Mutable state that flows through the 11-stage pipeline.

    Stored in MySQL via the workflow engine as JSON on each run.
    Each stage reads what it needs and enriches the state.
    """

    market: str = ""
    run_id: str = ""
    schedule: str = "on_demand"
    date_stamp: str = ""

    # Stage outputs (populated progressively)
    kb_result: Optional[KbLookupResult] = None
    competitor_discovery: Optional[CompetitorDiscoveryResult] = None
    deep_dive: Optional[DeepDiveResult] = None
    vectors: Optional[VectorIdentificationResult] = None
    matrix: Optional[ComparisonMatrixResult] = None
    tier_analysis: Optional[TierAnalysisResult] = None
    executive_summary: Optional[ExecutiveSummaryResult] = None
    innovation: Optional[InnovationScoutingResult] = None
    layout_plan: Optional[LayoutPlanResult] = None
    assembly: Optional[ReportAssemblyResult] = None

    # Accumulators
    total_cost: float = 0.0
    total_tokens_input: int = 0
    total_tokens_output: int = 0
    intermediate_files: list[str] = Field(default_factory=list)
