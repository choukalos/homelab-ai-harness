"""Pydantic schemas for the presentation module."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


# ---------- Request models -------------------------------------------------

class PresentationRequest(BaseModel):
    """One-shot presentation generation request."""

    title: str = Field(description="Presentation title.")
    content: str = Field(
        description="Topic description or raw content prompt for the presentation."
    )
    outline: Optional[str] = Field(
        default=None,
        description="Optional pre-built outline in markdown. If provided, skips AI outline generation.",
    )
    research: bool = Field(
        default=False,
        description="Whether to do deep research before generating the outline.",
    )
    kb_search: bool = Field(
        default=False,
        description="Whether to search the family knowledge base first.",
    )
    n_slides: int = Field(
        default=8, ge=3, le=50,
        description="Target number of slides (excluding title/TOC).",
    )
    template: str = Field(
        default="general",
        description="Presenton template name (e.g. general, academic, dark, creative, etc.).",
    )
    tone: Literal["default", "casual", "professional", "funny", "educational", "sales_pitch"] = Field(
        default="default",
        description="Tone of the presentation.",
    )
    verbosity: Literal["concise", "standard", "text-heavy"] = Field(
        default="standard",
        description="How much text per slide.",
    )
    language: str = Field(default="English", description="Language of the presentation.")
    export_as: Literal["pptx", "pdf"] = Field(
        default="pptx",
        description="Output format: pptx or pdf.",
    )
    version: Optional[int] = Field(
        default=None,
        description="Explicit version number. If omitted, auto-incremented from existing presentations.",
    )
    parent_id: Optional[str] = Field(
        default=None,
        description="Presenton ID of the parent presentation being versioned.",
    )
    instructions: Optional[str] = Field(
        default=None,
        description="Additional instructions for the AI during slide generation.",
    )
    include_table_of_contents: bool = Field(
        default=False,
        description="Include a table of contents slide.",
    )
    include_title_slide: bool = Field(
        default=True,
        description="Include a title slide.",
    )


class OutlineRequest(BaseModel):
    """Collaborative outline generation request."""

    topic: str = Field(description="Topic description for the presentation.")
    existing_outline: Optional[str] = Field(
        default=None,
        description="Existing outline to refine or iterate on.",
    )
    instructions: Optional[str] = Field(
        default=None,
        description="Specific instructions for outline generation.",
    )
    research: bool = Field(
        default=False,
        description="Whether to do deep research before generating the outline.",
    )
    kb_search: bool = Field(
        default=False,
        description="Whether to search the family knowledge base first.",
    )


# ---------- Response models ------------------------------------------------

class OutlineResponse(BaseModel):
    """AI-generated outline response."""

    outline: str = Field(description="Markdown outline text suitable for Presenton.")
    title: str = Field(description="Suggested presentation title.")
    slide_count: int = Field(description="Estimated number of content slides.")
    sources: list[dict] = Field(
        default_factory=list,
        description="Research sources used (if any).",
    )


class PresentationResponse(BaseModel):
    """Response after generating a presentation."""

    presentation_id: str = Field(description="Presenton internal presentation ID.")
    title: str = Field(description="Presentation title.")
    version: int = Field(description="Version number.")
    parent_id: Optional[str] = Field(
        default=None,
        description="Parent presentation ID if this is a version.",
    )
    slide_count: int = Field(description="Number of slides generated.")
    local_path: str = Field(description="Path under /data/media/presentations/.")
    download_url: str = Field(
        description="Public URL for downloading the file (siri.choukalos.com, no auth needed).",
    )
    internal_download_url: str = Field(
        description="Internal API URL for downloading the file (thor.local, auth required).",
    )
    edit_url: Optional[str] = Field(
        default=None,
        description="Presenton web UI edit URL (internal only, home lab network).",
    )
    metadata_path: str = Field(description="Path to the metadata.json file.")


class PresentationMetadata(BaseModel):
    """Single presentation metadata record (stored in metadata.json, returned in list)."""

    presentation_id: str
    title: str
    version: int
    parent_id: Optional[str] = None
    slide_count: int = 0
    filename: str
    local_path: str
    download_url: str = Field(
        default="",
        description="Public URL for downloading the file (siri.choukalos.com, no auth needed).",
    )
    internal_download_url: str = Field(
        default="",
        description="Internal API URL for downloading the file (thor.local, auth required).",
    )
    edit_url: Optional[str] = None
    metadata_path: str
    created_at: str
    outline: Optional[str] = None
    sources: list[dict] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _fill_urls(self) -> "PresentationMetadata":
        """Backfill URLs for old metadata files that lack internal_download_url.

        Old metadata.json files have download_url pointing to the internal API.
        We detect this and rewrite to the public StaticFiles URL while keeping
        the internal one for API clients.
        """
        # Detect old-format download_url (internal API path)
        if self.download_url and "/presentation/download/" in self.download_url:
            # This is an old file — the download_url was actually the internal one
            self.internal_download_url = self.download_url
            # Reconstruct the public URL from the filename
            if self.filename:
                from infra.core.config import PUBLIC_BASE_URL as _pb
                self.download_url = f"{_pb.rstrip('/')}/media/files/presentations/{self.filename}"
        elif self.internal_download_url == "" and self.filename:
            # New format: download_url is public, but internal_download_url wasn't saved
            from infra.core.config import INTERNAL_BASE_URL as _ib
            self.internal_download_url = f"{_ib.rstrip('/')}/presentation/download/{self.filename}"
        return self


class PresentationUpdateRequest(BaseModel):
    """PATCH request for regenerating a presentation (all fields optional)."""

    title: Optional[str] = Field(
        default=None,
        description="New title. If omitted, keeps parent title.",
    )
    content: Optional[str] = Field(
        default=None,
        description="New topic/content prompt. If omitted, keeps parent content.",
    )
    outline: Optional[str] = Field(
        default=None,
        description="New pre-built outline. Overrides any existing outline.",
    )
    research: Optional[bool] = Field(
        default=None,
        description="Whether to do deep research before regenerating.",
    )
    kb_search: Optional[bool] = Field(
        default=None,
        description="Whether to search the family knowledge base first.",
    )
    n_slides: Optional[int] = Field(
        default=None, ge=3, le=50,
        description="New target slide count.",
    )
    template: Optional[str] = Field(
        default=None,
        description="New Presenton template name.",
    )
    tone: Optional[Literal["default", "casual", "professional", "funny", "educational", "sales_pitch"]] = Field(
        default=None,
        description="New tone for the presentation.",
    )
    verbosity: Optional[Literal["concise", "standard", "text-heavy"]] = Field(
        default=None,
        description="New verbosity level.",
    )
    language: Optional[str] = Field(
        default=None,
        description="New language for the presentation.",
    )
    export_as: Optional[Literal["pptx", "pdf"]] = Field(
        default=None,
        description="New output format.",
    )
    instructions: Optional[str] = Field(
        default=None,
        description="Additional instructions for regeneration.",
    )
    include_table_of_contents: Optional[bool] = Field(
        default=None,
        description="Include a table of contents slide.",
    )
    include_title_slide: Optional[bool] = Field(
        default=None,
        description="Include a title slide.",
    )


class PresentationListResponse(BaseModel):
    """List of existing presentations."""

    presentations: list[PresentationMetadata] = Field(
        default_factory=list,
        description="Presentations sorted by creation date (newest first).",
    )
    total: int = Field(description="Total number of presentations.")


class AsyncTaskResponse(BaseModel):
    """Response from async generation endpoint (fire-and-forget)."""

    task_id: str = Field(description="Celery task ID for status tracking.")
    title: str = Field(description="Presentation title.")
    status: str = Field(
        default="submitted",
        description="Current task status (submitted/pending/completed/failed).",
    )
    message: str = Field(
        default="Presentation generation started. Check /tasks/{task_id} for status.",
        description="Human-readable status message.",
    )


class TaskStatusResponse(BaseModel):
    """Response from task status check endpoint."""

    task_id: str = Field(description="Celery task ID.")
    status: str = Field(
        description="Task status: pending / started / completed / failed / unknown.",
    )
    result: Optional[dict[str, Any]] = Field(
        default=None,
        description="Result data (PresentationResponse fields) when completed.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message when failed.",
    )
