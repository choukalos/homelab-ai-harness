"""Pydantic schemas for layout operations."""

from pydantic import BaseModel, Field
from typing import Optional, Literal


# ------ Layout Creation ------

class CreateLayoutRequest(BaseModel):
    """Request to create a new page/slide layout."""

    orientation: Literal["portrait", "slide"] = Field(
        default="portrait",
        description="Page orientation: portrait (document) or slide (16:9 presentation)",
    )
    template: str = Field(
        default="minimal",
        description="Layout template name. See README for available templates.",
    )
    title: str = Field(
        default="",
        description="Page or slide title.",
    )
    background_color: str = Field(
        default="#ffffff",
        description="Background color (hex, rgb, or named CSS color).",
    )
    text_color: str = Field(
        default="#1a1a1a",
        description="Primary text color.",
    )
    accent_color: str = Field(
        default="#3b82f6",
        description="Accent color for headings, links, highlights.",
    )
    font_family: str = Field(
        default="system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        description="CSS font-family string.",
    )
    page_margin: int = Field(
        default=40,
        ge=0,
        le=120,
        description="Page margin in pixels.",
    )


class ZoneInfo(BaseModel):
    """Describes a single content zone in a layout."""

    name: str
    description: str
    grid_area: Optional[str] = None  # CSS grid area name


class LayoutState(BaseModel):
    """Internal snapshot of a layout's state (for responses and diagnostics)."""

    layout_id: str
    orientation: str
    template: str
    title: str
    zones: list[str] = Field(default_factory=list)
    content_count: int = 0
    created_at: Optional[str] = None


class CreateLayoutResponse(BaseModel):
    """Response after creating a new layout."""

    layout_id: str
    orientation: str
    template: str
    title: str
    zones: list[str] = Field(default_factory=list)
    content_count: int = 0


# ------ Content Placement ------

class AddContentRequest(BaseModel):
    """Request to add content to a specific zone of a layout."""

    layout_id: str = Field(description="Layout ID from create endpoint.")
    zone: str = Field(description="Zone name to place content in.")
    content_type: Literal["text", "image"] = Field(
        default="text",
        description="Type of content: text (markdown/html) or image.",
    )
    content: Optional[str] = Field(
        default=None,
        description="Text content (markdown or HTML snippet). Required when content_type='text'.",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="URL to image. Required when content_type='image'.",
    )
    alignment: Optional[Literal["left", "center", "right"]] = Field(
        default="center",
        description="Content alignment within the zone.",
    )
    style_class: Optional[str] = Field(
        default="",
        description="Additional CSS class name(s) to apply.",
    )
    append: bool = Field(
        default=False,
        description="If True, append to existing zone content instead of replacing.",
    )


class AddContentResponse(BaseModel):
    """Response after adding content to a layout."""

    layout_id: str
    zone: str
    content_type: str
    status: str = "placed"


# ------ Render ------

class RenderLayoutRequest(BaseModel):
    """Request to render the layout as HTML."""

    layout_id: str = Field(description="Layout ID from create endpoint.")
    include_meta: bool = Field(
        default=True,
        description="Include viewport meta tags and title.",
    )
    minify: bool = Field(
        default=False,
        description="Minify the output HTML.",
    )


class RenderLayoutResponse(BaseModel):
    """Response with rendered HTML."""

    layout_id: str
    html: str
    file_size_bytes: int


# ------ Save ------

class SaveLayoutRequest(BaseModel):
    """Request to save the rendered layout to a file in workspace."""

    layout_id: str = Field(description="Layout ID from create endpoint.")
    output_path: str = Field(
        description="Relative path within workspace (e.g. 'presentations/q4.html').",
    )


class SaveLayoutResponse(BaseModel):
    """Response after saving layout HTML."""

    layout_id: str
    path: str
    bytes_written: int
    url: str = ""


# ------ List ------

class ActiveLayout(BaseModel):
    """Summary of an active in-memory layout."""

    layout_id: str
    template: str
    orientation: str
    title: str
    content_count: int
    created_at: Optional[str] = None


class ListLayoutsResponse(BaseModel):
    """Response listing all active layouts."""

    layouts: list[ActiveLayout] = Field(default_factory=list)
