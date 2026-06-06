"""Pydantic schemas for layout operations."""

from pydantic import BaseModel, Field
from typing import Optional, Literal

from charts.schemas import ChartZoneSpec


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
    content_type: Literal["text", "image", "table", "chart"] = Field(
        default="text",
        description="Type of content: text (markdown/html), image, table, or chart.",
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
    table_columns: Optional[list[TableColumnDef]] = Field(
        default=None,
        description="Column definitions when content_type='table'.",
    )
    table_rows: Optional[list[dict]] = Field(
        default=None,
        description="Row data dicts when content_type='table'.",
    )
    table_style: Optional[TableStyle] = Field(
        default=None,
        description="Style options when content_type='table'.",
    )
    chart_spec: Optional[ChartZoneSpec] = Field(
        default=None,
        description="Chart specification when content_type='chart'. See ChartZoneSpec.",
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


# ------ Styled HTML Table ------

class TableColumnDef(BaseModel):
    """Definition of a single table column."""

    name: str = Field(description="Column header text.")
    key: str = Field(description="Key used to look up cell values in row dicts.")
    align: Literal["left", "center", "right"] = Field(default="left")
    width: Optional[str] = Field(
        default=None,
        description="CSS width string, e.g. '120px' or '20%'.",
    )


class TableStyle(BaseModel):
    """Visual style knobs for the generated HTML table."""

    header_bg: str = Field(default="#1e3a5f", description="Header row background.")
    header_color: str = Field(default="#ffffff", description="Header text color.")
    row_alt_bg: str = Field(default="#f8fafc", description="Even-row alternating background.")
    border_color: str = Field(default="#e2e8f0", description="Cell border color.")
    text_color: str = Field(default="#334155", description="Body text color.")
    font_family: str = Field(
        default="system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
    )
    font_size: str = Field(default="14px")
    border_radius: int = Field(default=8, ge=0, le=24)
    striping: bool = Field(default=True)
    hover: bool = Field(default=True)
    compact: bool = Field(default=False)


class CreateTableRequest(BaseModel):
    """Request to generate a standalone styled HTML table."""

    title: str = Field(default="", description="Optional table title / caption.")
    columns: list[TableColumnDef] = Field(description="Column definitions.")
    rows: list[dict] = Field(description="Row data — list of dicts keyed by column keys.")
    style: Optional[TableStyle] = None
    standalone: bool = Field(
        default=True,
        description="If True wrap in a full HTML document; if False return only the table fragment.",
    )


class CreateTableResponse(BaseModel):
    """Response with the generated HTML table."""

    html: str
    file_size_bytes: int


# ------ PDF Export ------

class AddGeneratedImageRequest(BaseModel):
    """Request to generate an image and insert it into a layout zone in one step."""

    layout_id: str = Field(description="Layout ID from create endpoint.")
    zone: str = Field(description="Zone name to place the generated image in.")
    prompt: str = Field(description="Prompt for image generation.")
    negative_prompt: str = Field(
        default="blurry, distorted, low quality",
        description="Negative prompt for image generation.",
    )
    width: int = Field(
        default=1024,
        ge=256,
        le=2048,
        description="Generated image width.",
    )
    height: int = Field(
        default=576,
        ge=256,
        le=2048,
        description="Generated image height.",
    )
    seed: int = Field(
        default=-1,
        description="Seed for reproducibility (-1 for random).",
    )
    steps: int = Field(
        default=30,
        ge=1,
        le=80,
        description="Denoising steps for generation.",
    )
    cfg: float = Field(
        default=7.0,
        ge=1.0,
        le=20.0,
        description="CFG scale for generation.",
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


class AddGeneratedImageResponse(BaseModel):
    """Response after generating an image and inserting it into a layout."""

    layout_id: str
    zone: str
    image_url: str
    image_filename: str
    job_id: str
    status: str = "generated_and_placed"


class BuildDocumentRequest(BaseModel):
    """
    Request to build a complete document by orchestrating layout creation,
    content placement (text, images, tables), and rendering in a single API call.

    The AI agent provides a high-level document spec and the service handles
    the full pipeline: create layout → generate images → add content → render & save.
    """

    orientation: Literal["portrait", "slide"] = Field(
        default="portrait",
        description="Page orientation: portrait (document) or slide (presentation).",
    )
    template: str = Field(
        default="minimal",
        description="Layout template name.",
    )
    title: str = Field(
        default="",
        description="Document title.",
    )
    background_color: str = Field(
        default="#ffffff",
        description="Background color.",
    )
    text_color: str = Field(
        default="#1a1a1a",
        description="Primary text color.",
    )
    accent_color: str = Field(
        default="#3b82f6",
        description="Accent color.",
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
    zones: list["ZoneContentSpec"] = Field(
        description="List of zone content specifications.",
    )
    output_path: str = Field(
        description="Path to save the rendered HTML (e.g. 'output/report.html').",
    )
    export_pdf: bool = Field(
        default=False,
        description="If True, also export as PDF to media directory.",
    )
    pdf_path: Optional[str] = Field(
        default=None,
        description="PDF output path in media directory (used when export_pdf=True).",
    )
    pdf_page_size: Literal["A4", "Letter", "Legal", "A3", "A5"] = Field(
        default="Letter",
        description="PDF page size.",
    )


class ZoneContentSpec(BaseModel):
    """Specification for a single zone's content in a document build."""

    zone: str = Field(description="Zone name to populate.")
    content_type: Literal["text", "image", "table", "gen_image", "chart"] = Field(
        description="Content type. Use 'gen_image' for inline image gen, 'chart' for charts.",
    )
    content: Optional[str] = Field(
        default=None,
        description="Text content (markdown/HTML). Required when content_type='text'.",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="URL to existing image. Required when content_type='image'.",
    )
    image_prompt: Optional[str] = Field(
        default=None,
        description="Prompt for image generation. Required when content_type='gen_image'.",
    )
    image_negative_prompt: Optional[str] = Field(
        default="blurry, distorted, low quality",
        description="Negative prompt for image generation.",
    )
    image_width: Optional[int] = Field(
        default=1024,
        description="Width for generated image.",
    )
    image_height: Optional[int] = Field(
        default=576,
        description="Height for generated image.",
    )
    image_seed: Optional[int] = Field(default=-1, description="Seed for generated image.")
    image_steps: Optional[int] = Field(default=30, description="Steps for generated image.")
    image_cfg: Optional[float] = Field(default=7.0, description="CFG for generated image.")
    alignment: Optional[Literal["left", "center", "right"]] = Field(
        default="center",
        description="Content alignment within the zone.",
    )
    style_class: Optional[str] = Field(default="", description="Additional CSS classes.")
    append: bool = Field(default=False, description="Append to existing zone content.")
    table_columns: Optional[list[TableColumnDef]] = Field(
        default=None,
        description="Column definitions when content_type='table'.",
    )
    table_rows: Optional[list[dict]] = Field(
        default=None,
        description="Row data when content_type='table'.",
    )
    table_style: Optional[TableStyle] = Field(
        default=None,
        description="Style options when content_type='table'.",
    )
    chart_spec: Optional[ChartZoneSpec] = Field(
        default=None,
        description="Chart specification when content_type='chart'."
    )


class BuildDocumentResponse(BaseModel):
    """Response after building a complete document."""

    layout_id: str
    html_path: str
    html_bytes: int
    pdf_path: Optional[str] = None
    pdf_url: Optional[str] = None
    pdf_bytes: Optional[int] = None
    generated_images: list[dict] = Field(
        default_factory=list,
        description="List of generated image info (filename, url).",
    )


class ExportPdfRequest(BaseModel):
    """Request to export a layout as a PDF file."""

    layout_id: str = Field(description="Layout ID from create endpoint.")
    output_path: str = Field(
        description=(
            "Path within the media directory where the PDF will be saved. "
            "Includes subdirectory for workflow organization. "
            "Examples: 'presentation/report.pdf', 'research/analysis.pdf'. "
            "Parent directories are created automatically."
        ),
    )
    page_size: Literal["A4", "Letter", "Legal", "A3", "A5"] = Field(
        default="Letter",
        description="PDF page size. Defaults to Letter to match portrait document use case.",
    )
    margins: Optional[dict] = Field(
        default=None,
        description="Page margins as dict with keys: top, bottom, left, right. Values in mm (e.g. {'top': 20, 'bottom': 20, 'left': 15, 'right': 15}).",
    )


class ExportPdfResponse(BaseModel):
    """Response after saving PDF."""

    layout_id: str
    path: str
    url: str
    bytes_written: int
