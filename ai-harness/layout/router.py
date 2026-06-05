"""FastAPI router for layout endpoints."""

from fastapi import APIRouter, Depends

from core.security import require_harness_auth
from layout.schemas import (
    AddContentRequest,
    AddContentResponse,
    CreateLayoutRequest,
    CreateLayoutResponse,
    CreateTableRequest,
    CreateTableResponse,
    ExportPdfRequest,
    ExportPdfResponse,
    ListLayoutsResponse,
    RenderLayoutRequest,
    RenderLayoutResponse,
    SaveLayoutRequest,
    SaveLayoutResponse,
)
from layout.service import (
    layout_add_content,
    layout_create,
    layout_delete,
    layout_export_pdf,
    layout_list,
    layout_render,
    layout_render_table,
    layout_save,
)

router = APIRouter(tags=["layout"])


@router.post("/create", response_model=CreateLayoutResponse)
def create(
    req: CreateLayoutRequest,
    _: None = Depends(require_harness_auth),
):
    """Create a new page or slide layout document."""
    return layout_create(req)


@router.post("/add", response_model=AddContentResponse)
def add_content(
    req: AddContentRequest,
    _: None = Depends(require_harness_auth),
):
    """Add text or image content to a specific zone of an existing layout."""
    return layout_add_content(req)


@router.post("/render", response_model=RenderLayoutResponse)
def render(
    req: RenderLayoutRequest,
    _: None = Depends(require_harness_auth),
):
    """Render the current layout as a complete self-contained HTML document."""
    return layout_render(req)


@router.post("/save", response_model=SaveLayoutResponse)
def save(
    req: SaveLayoutRequest,
    _: None = Depends(require_harness_auth),
):
    """Render and save the layout HTML to a file in the workspace."""
    return layout_save(req)


@router.get("/active", response_model=ListLayoutsResponse)
def active_list(
    _: None = Depends(require_harness_auth),
):
    """List all active in-memory layouts still available for editing."""
    return layout_list()


@router.delete("/{layout_id}")
def delete(
    layout_id: str,
    _: None = Depends(require_harness_auth),
):
    """Discard a layout from active memory."""
    return layout_delete(layout_id)


@router.post("/table", response_model=CreateTableResponse)
def render_table(
    req: CreateTableRequest,
    _: None = Depends(require_harness_auth),
):
    """Render a standalone styled HTML table (no layout needed)."""
    return layout_render_table(req)


@router.post("/export-pdf", response_model=ExportPdfResponse)
def export_pdf(
    req: ExportPdfRequest,
    _: None = Depends(require_harness_auth),
):
    """Render the layout and export as a PDF file to the media directory."""
    return layout_export_pdf(req)
