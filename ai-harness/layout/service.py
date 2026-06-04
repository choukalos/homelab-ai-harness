"""
Core business logic for the layout module.

Manages in-memory layout documents and renders them as
self-contained HTML with inline CSS.
"""

import html as html_mod
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

# ------------------------------------------------------------------
# In-memory layout store
# ------------------------------------------------------------------

_layouts: Dict[str, Dict[str, Any]] = {}


# ------------------------------------------------------------------
# Template definitions
# Each template defines:
#   zones        – list of zone names
#   grid_template_rows / columns – CSS grid definitions
#   zone_map     – zone name -> grid-area CSS assignment
#   zone_styles  – optional per-zone extra CSS
# ------------------------------------------------------------------

_TEMPLATES: Dict[str, Dict[str, Any]] = {}


def _register_templates():
    """Populate _TEMPLATES with all layout definitions."""

    _TEMPLATES["hero"] = {
        "zones": ["hero_background", "hero_title", "hero_subtitle", "body"],
        "grid_rows": "auto 1fr",
        "grid_cols": "1fr",
        "zone_map": {
            "hero_background": "hero",
            "hero_title": "hero",
            "hero_subtitle": "hero",
            "body": "main",
        },
        "portrait_css": {
            "grid_template_rows": "auto 1fr",
        },
        "slide_css": {
            "grid_template_rows": "60% 40%",
        },
    }

    _TEMPLATES["grid"] = {
        "zones": ["header", "col_left", "col_center", "col_right", "footer"],
        "grid_rows": "auto 1fr auto",
        "grid_cols": "1fr 1fr 1fr",
        "zone_map": {
            "header": "header",
            "col_left": "left",
            "col_center": "center",
            "col_right": "right",
            "footer": "footer",
        },
    }

    _TEMPLATES["split"] = {
        "zones": ["header", "panel_left", "panel_right", "footer"],
        "grid_rows": "auto 1fr auto",
        "grid_cols": "1fr 1fr",
        "zone_map": {
            "header": "header",
            "panel_left": "left",
            "panel_right": "right",
            "footer": "footer",
        },
    }

    _TEMPLATES["gallery"] = {
        "zones": ["header", "gallery_grid", "caption"],
        "grid_rows": "auto 1fr auto",
        "grid_cols": "1fr",
        "zone_map": {
            "header": "header",
            "gallery_grid": "gallery",
            "caption": "caption",
        },
    }

    _TEMPLATES["cards"] = {
        "zones": ["header", "card_1", "card_2", "card_3", "card_4", "footer"],
        "grid_rows": "auto 1fr 1fr auto",
        "grid_cols": "1fr 1fr",
        "zone_map": {
            "header": "header",
            "card_1": "card1",
            "card_2": "card2",
            "card_3": "card3",
            "card_4": "card4",
            "footer": "footer",
        },
    }

    _TEMPLATES["minimal"] = {
        "zones": ["header", "content", "footer"],
        "grid_rows": "auto 1fr auto",
        "grid_cols": "1fr",
        "zone_map": {
            "header": "header",
            "content": "content",
            "footer": "footer",
        },
    }

    _TEMPLATES["timeline"] = {
        "zones": [
            "header",
            "timeline_1",
            "timeline_2",
            "timeline_3",
            "timeline_4",
            "footer",
        ],
        "grid_rows": "auto 1fr 1fr 1fr 1fr auto",
        "grid_cols": "1fr",
        "zone_map": {
            "header": "header",
            "timeline_1": "t1",
            "timeline_2": "t2",
            "timeline_3": "t3",
            "timeline_4": "t4",
            "footer": "footer",
        },
    }

    _TEMPLATES["magazine"] = {
        "zones": [
            "header",
            "lead",
            "column_a",
            "column_b",
            "pull_quote",
            "image_area",
            "footer",
        ],
        "grid_rows": "auto auto 1fr 1fr auto auto auto",
        "grid_cols": "1fr 1fr",
        "zone_map": {
            "header": "header",
            "lead": "lead",
            "column_a": "colA",
            "column_b": "colB",
            "pull_quote": "pullQuote",
            "image_area": "imageArea",
            "footer": "footer",
        },
    }

    _TEMPLATES["pitch"] = {
        "zones": ["hero_bg", "headline", "supporting_text", "cta"],
        "grid_rows": "1fr 1fr auto",
        "grid_cols": "1fr",
        "zone_map": {
            "hero_bg": "hero",
            "headline": "hero",
            "supporting_text": "body",
            "cta": "cta",
        },
    }

    _TEMPLATES["blank"] = {
        "zones": [],
        "grid_rows": "1fr 1fr 1fr 1fr",
        "grid_cols": "1fr 1fr 1fr 1fr",
        "zone_map": {},
    }
    _register_templates()


_init_done = False


def _ensure_init():
    global _init_done
    if not _init_done:
        _register_templates()
        _init_done = True


_ensure_init()


# ------------------------------------------------------------------
# Markdown-lite to HTML conversion
# ------------------------------------------------------------------

def _md_to_html(text: str) -> str:
    """Convert a lightweight subset of markdown to HTML.

    Supports: headings, bold, italic, links, lists, inline code, and
    paragraphs. No external dependencies — pure Python.
    """
    s = text

    # Escape HTML entities first
    s = html_mod.escape(s)

    # Headings (# h1 .. ###### h6)
    s = re.sub(
        r"^######\s+(.+)$", r'<h6>\1</h6>', s, flags=re.MULTILINE
    )
    s = re.sub(
        r"^#####\s+(.+)$", r'<h5>\1</h5>', s, flags=re.MULTILINE
    )
    s = re.sub(
        r"^####\s+(.+)$", r'<h4>\1</h4>', s, flags=re.MULTILINE
    )
    s = re.sub(
        r"^###\s+(.+)$", r'<h3>\1</h3>', s, flags=re.MULTILINE
    )
    s = re.sub(
        r"^##\s+(.+)$", r'<h2>\1</h2>', s, flags=re.MULTILINE
    )
    s = re.sub(
        r"^#\s+(.+)$", r'<h1>\1</h1>', s, flags=re.MULTILINE
    )

    # Bold and italic
    s = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)

    # Inline code
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)

    # Links
    s = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank">\1</a>',
        s,
    )

    # Unordered list items
    s = re.sub(r"^\s*-\s+(.+)$", r'<li>\1</li>', s, flags=re.MULTILINE)
    s = re.sub(r"(<li>.*?</li>)", r"<ul>\1</ul>", s, flags=re.DOTALL)
    # Merge adjacent <ul> blocks
    s = re.sub(r"</ul>\s*<ul>", "", s)

    # Images (markdown syntax) — only if not already an <img> tag
    s = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        r'<img src="\2" alt="\1" class="md-image" />',
        s,
    )

    # Paragraphs: wrap any remaining block text
    lines = s.split("\n")
    result_lines: list[str] = []
    buf: list[str] = []
    block_tags = ("h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li")

    def _flush_buf():
        nonlocal buf
        if buf:
            text_chunk = "\n".join(buf).strip()
            if text_chunk:
                result_lines.append(f"<p>{text_chunk}</p>")
            buf = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            _flush_buf()
            continue
        # Check if it starts with a block tag
        is_block = any(stripped.startswith(f"<{tag}") for tag in block_tags)
        if is_block:
            _flush_buf()
            result_lines.append(line)
        else:
            buf.append(line)

    _flush_buf()
    return "\n".join(result_lines)


# ------------------------------------------------------------------
# Core service functions
# ------------------------------------------------------------------

def layout_create(req) -> Dict[str, Any]:
    """Create a new layout document."""
    _ensure_init()

    template_name = req.template.lower()
    if template_name not in _TEMPLATES:
        available = ", ".join(sorted(_TEMPLATES.keys()))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown template: {template_name}. Available: {available}",
        )

    template_def = _TEMPLATES[template_name]
    layout_id = uuid.uuid4().hex[:12]

    _layouts[layout_id] = {
        "layout_id": layout_id,
        "template": template_name,
        "orientation": req.orientation,
        "title": req.title,
        "background_color": req.background_color,
        "text_color": req.text_color,
        "accent_color": req.accent_color,
        "font_family": req.font_family,
        "page_margin": req.page_margin,
        "zones": {},  # zone_name -> list of content items
        "zone_order": template_def["zones"][:],
        "template_def": template_def,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "layout_id": layout_id,
        "orientation": req.orientation,
        "template": template_name,
        "title": req.title,
        "zones": template_def["zones"][:],
        "content_count": 0,
    }


def _get_layout(layout_id: str) -> Dict[str, Any]:
    """Fetch an active layout or raise 404."""
    if layout_id not in _layouts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Layout not found: {layout_id}",
        )
    return _layouts[layout_id]


def layout_add_content(req) -> Dict[str, Any]:
    """Add content (text or image) to a specific zone."""
    layout = _get_layout(req.layout_id)

    item: Dict[str, Any] = {
        "type": req.content_type,
        "alignment": req.alignment or "center",
        "style_class": req.style_class or "",
    }

    if req.content_type == "text":
        if not req.content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="content is required when content_type='text'",
            )
        item["content"] = req.content
        item["html"] = _md_to_html(req.content)
    else:
        if not req.image_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="image_url is required when content_type='image'",
            )
        item["image_url"] = req.image_url

    zone = req.zone
    if zone not in layout["zones"]:
        layout["zones"][zone] = []
        layout["zone_order"].append(zone)

    if req.append:
        layout["zones"][zone].append(item)
    else:
        layout["zones"][zone] = [item]

    return {
        "layout_id": req.layout_id,
        "zone": zone,
        "content_type": req.content_type,
        "status": "placed",
    }


def layout_render(req) -> Dict[str, Any]:
    """Render a layout as full self-contained HTML."""
    layout = _get_layout(req.layout_id)
    html_doc = _build_html(layout, include_meta=req.include_meta)

    if req.minify:
        html_doc = _minify(html_doc)

    return {
        "layout_id": req.layout_id,
        "html": html_doc,
        "file_size_bytes": len(html_doc.encode("utf-8")),
    }


def layout_save(req) -> Dict[str, Any]:
    """Render and save the layout to a file on disk."""
    from core.config import WORKSPACE
    from pathlib import Path

    layout = _get_layout(req.layout_id)
    html_doc = _build_html(layout, include_meta=True)

    target = Path(WORKSPACE) / req.output_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html_doc, encoding="utf-8")

    return {
        "layout_id": req.layout_id,
        "path": req.output_path,
        "bytes_written": len(html_doc.encode("utf-8")),
    }


def layout_list() -> Dict[str, Any]:
    """List all active in-memory layouts."""
    items = []
    for lid, ld in _layouts.items():
        count = sum(len(v) for v in ld["zones"].values())
        items.append({
            "layout_id": lid,
            "template": ld["template"],
            "orientation": ld["orientation"],
            "title": ld["title"],
            "content_count": count,
            "created_at": ld["created_at"],
        })
    return {"layouts": items}


def layout_delete(layout_id: str) -> Dict[str, Any]:
    """Delete an in-memory layout."""
    if layout_id not in _layouts:
        raise HTTPException(status_code=404, detail=f"Layout not found: {layout_id}")
    del _layouts[layout_id]
    return {"layout_id": layout_id, "deleted": True}


# ------------------------------------------------------------------
# HTML generation
# ------------------------------------------------------------------

def _build_html(layout: Dict[str, Any], include_meta: bool = True) -> str:
    """Build the full HTML document for a layout."""
    tpl = layout["template"]
    orientation = layout["orientation"]
    title = layout["title"] or "Untitled"
    bg = layout["background_color"]
    text_col = layout["text_color"]
    accent = layout["accent_color"]
    font = layout["font_family"]
    margin = layout["page_margin"]
    template_def = layout["template_def"]
    zones_content = layout["zones"]

    # Orientation-specific dimensions
    if orientation == "slide":
        page_width = "1920px"
        page_height = "1080px"
    else:
        page_width = "100%"
        page_height = "100%"

    # Build grid areas from zone_map
    zone_map = template_def["zone_map"]
    grid_rows = template_def.get("grid_rows", "1fr")
    grid_cols = template_def.get("grid_cols", "1fr")

    # Build CSS grid-template-areas
    grid_areas = _compute_grid_areas(zone_map, grid_rows, grid_cols)

    # Build zone HTML
    zone_html = _build_zone_html(zones_content, zone_map, tpl, accent, text_col, font)

    # Orientation-specific CSS overrides
    orientation_css = ""
    if orientation == "slide":
        portrait_override = template_def.get("slide_css", {})
        if portrait_override:
            rules = ";\n      ".join(
                f"{k}: {v}" for k, v in portrait_override.items()
            )
            orientation_css = f"\n        .page {{\n      {rules};\n        }}"

    # Base stylesheet
    css = _build_stylesheet(
        bg=bg,
        text_col=text_col,
        accent=accent,
        font=font,
        margin=margin,
        page_width=page_width,
        page_height=page_height,
        grid_rows=grid_rows,
        grid_cols=grid_cols,
        grid_areas=grid_areas,
        tpl=tpl,
        orientation_css=orientation_css,
    )

    parts: list[str] = ['<!DOCTYPE html>\n<html lang="en">']

    if include_meta:
        parts.append(f'<head>\n  <meta charset="UTF-8" />\n')
        parts.append('  <meta name="viewport" content="width=device-width, initial-scale=1.0" />\n')
        parts.append(f'  <title>{html_mod.escape(title)}</title>\n')
        parts.append(f"  <style>\n{css}\n  </style>\n</head>")
    else:
        parts.append(f"<style>\n{css}\n</style>")

    parts.append("<body>")
    parts.append(f'<div class="page">')
    parts.append(zone_html)
    parts.append("</div>\n</body>\n</html>")

    return "\n".join(parts)


def _compute_grid_areas(
    zone_map: Dict[str, str],
    grid_rows: str,
    grid_cols: str,
) -> str:
    """Compute CSS grid-template-areas string from zone assignments."""
    rows = grid_rows.split()
    cols = grid_cols.split()
    n_rows = len(rows)
    n_cols = len(cols)

    # Build a 2D grid — each cell defaults to empty
    area_grid: list[list[str]] = [[""] * n_cols for _ in range(n_rows)]

    # Count how many zones map to each grid-area name
    area_zone_count: Dict[str, int] = {}
    for area_name in zone_map.values():
        area_zone_count[area_name] = area_zone_count.get(area_name, 0) + 1

    # Distribute zones across the grid evenly
    # Simple: fill row by row, each unique area gets all its zones as one block
    area_to_row: Dict[str, int] = {}
    next_row = 0
    for area_name in zone_map.values():
        if area_name not in area_to_row:
            area_to_row[area_name] = next_row
            next_row += 1

    # For each zone in zone_map, assign to cell
    # Since zones sharing the same area name should span, we just mark the first occurrence
    filled: set[str] = set()
    r, c = 0, 0
    for area_name in zone_map.values():
        pos = f"{r},{c}"
        if pos not in filled:
            area_grid[r][c] = f'"{area_name}"'
            filled.add(pos)
            c += 1
            if c >= n_cols:
                c = 0
                r += 1

    # Fill remaining empty cells with empty names
    for ri in range(n_rows):
        for ci in range(n_cols):
            if not area_grid[ri][ci]:
                area_grid[ri][ci] = '""'

    # Join rows
    grid_areas_parts = []
    for ri in range(n_rows):
        row_str = " ".join(area_grid[ri][ci] for ci in range(n_cols))
        grid_areas_parts.append(f"  {row_str};")

    return "\n".join(grid_areas_parts)


def _build_zone_html(
    zones_content: Dict[str, list],
    zone_map: Dict[str, str],
    tpl: str,
    accent: str,
    text_col: str,
    font: str,
) -> str:
    """Build the HTML for each zone."""
    parts: list[str] = []

    for zone_name in zones_content:
        items = zones_content[zone_name]
        grid_area = zone_map.get(zone_name, zone_name)
        alignment_class = _alignment_class(zone_name)
        zone_class = f"zone zone-{zone_name}"

        for item in items:
            extra_classes = item.get("style_class", "")
            cls = f"{zone_class} {alignment_class} {extra_classes}".strip()

            if item["type"] == "text":
                raw_html = item.get("html", _md_to_html(item["content"]))
                if tpl == "hero" and zone_name == "hero_title":
                    parts.append(f'<div class="{cls}"><h1 class="hero-title">{raw_html}</h1></div>')
                elif tpl == "hero" and zone_name == "hero_subtitle":
                    parts.append(f'<div class="{cls}"><h2 class="hero-subtitle">{raw_html}</h2></div>')
                elif tpl == "pitch" and zone_name == "headline":
                    parts.append(f'<div class="{cls}"><h1 class="pitch-headline">{raw_html}</h1></div>')
                elif tpl == "pitch" and zone_name == "supporting_text":
                    parts.append(f'<div class="{cls}"><p class="pitch-body">{raw_html}</p></div>')
                elif tpl == "pitch" and zone_name == "cta":
                    parts.append(f'<div class="{cls}"><div class="pitch-cta">{raw_html}</div></div>')
                elif tpl == "magazine" and zone_name == "pull_quote":
                    parts.append(f'<div class="{cls}"><blockquote class="pull-quote">{raw_html}</blockquote></div>')
                elif tpl == "magazine" and zone_name == "header":
                    parts.append(f'<div class="{cls}"><h1 class="magazine-title">{raw_html}</h1></div>')
                elif tpl == "timeline":
                    milestone_num = zone_name.replace("timeline_", "")
                    parts.append(f'<div class="{cls}"><div class="timeline-item"><span class="timeline-marker">{milestone_num}</span><div class="timeline-content">{raw_html}</div></div></div>')
                else:
                    parts.append(f'<div class="{cls}">{raw_html}</div>')
            else:
                img_url = item.get("image_url", "")
                if tpl == "hero" and zone_name == "hero_background":
                    parts.append(
                        f'<div class="{cls}" style="background-image:url(\'{img_url}\');'
                        f'background-size:cover;background-position:center;"></div>'
                    )
                else:
                    parts.append(
                        f'<div class="{cls}">'
                        f'<img src="{img_url}" class="zone-image" alt="" />'
                        f"</div>"
                    )

    return "\n".join(parts)


def _alignment_class(zone_name: str) -> str:
    """Default alignment per zone for specific templates."""
    # Hero zones default to center
    if zone_name.startswith("hero"):
        return "align-center"
    # Pitch zones default to center
    if zone_name in ("headline", "cta"):
        return "align-center"
    return "align-center"


def _build_stylesheet(
    bg: str,
    text_col: str,
    accent: str,
    font: str,
    margin: int,
    page_width: str,
    page_height: str,
    grid_rows: str,
    grid_cols: str,
    grid_areas: str,
    tpl: str,
    orientation_css: str,
) -> str:
    """Build the inline CSS stylesheet."""

    base_css = f"""
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      background: #111;
      display: flex;
      justify-content: center;
      align-items: center;
      min-height: 100vh;
      font-family: {font};
      color: {text_col};
    }}
    .page {{
      width: {page_width};
      height: {page_height};
      max-width: 1400px;
      background: {bg};
      color: {text_col};
      font-family: {font};
      padding: {margin}px;
      display: grid;
      grid-template-rows: {grid_rows};
      grid-template-columns: {grid_cols};
      grid-template-areas:
{grid_areas}
      gap: 16px;
      overflow: auto;
    }}
    .zone {{
      padding: 16px;
      overflow: hidden;
    }}
    .align-left {{ text-align: left; }}
    .align-center {{ text-align: center; }}
    .align-right {{ text-align: right; }}
    .zone-image {{
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      display: block;
      margin: 0 auto;
      border-radius: 4px;
    }}
    .md-image {{
      max-width: 100%;
      border-radius: 4px;
    }}
    a {{ color: {accent}; text-decoration: underline; }}
    code {{
      background: rgba(0,0,0,0.06);
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 0.9em;
    }}
    h1, h2, h3, h4, h5, h6 {{ color: {accent}; }}
    """

    # Template-specific CSS
    tpl_css = ""
    if tpl == "hero":
        tpl_css = f"""
    .zone-hero {{
      position: relative;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
    }}
    .zone-hero_background {{
      position: absolute;
      top: 0; left: 0; right: 0; bottom: 0;
      z-index: 0;
    }}
    .hero-title {{
      font-size: 3.5em;
      font-weight: 800;
      color: {text_col};
      z-index: 1;
      text-shadow: 0 2px 8px rgba(0,0,0,0.4);
      margin-bottom: 0.15em;
    }}
    .hero-subtitle {{
      font-size: 1.5em;
      font-weight: 300;
      color: {text_col};
      z-index: 1;
      opacity: 0.85;
      text-shadow: 0 1px 4px rgba(0,0,0,0.3);
    }}
    .zone-body {{
      grid-area: main;
    }}
    """
    elif tpl == "grid":
        tpl_css = """
    .zone-header { grid-area: header; font-weight: 700; font-size: 1.4em; }
    .zone-col_left { grid-area: left; }
    .zone-col_center { grid-area: center; }
    .zone-col_right { grid-area: right; }
    .zone-footer { grid-area: footer; font-size: 0.85em; opacity: 0.7; }
    """
    elif tpl == "split":
        tpl_css = """
    .zone-header { grid-area: header; font-weight: 700; font-size: 1.4em; }
    .zone-panel_left { grid-area: left; }
    .zone-panel_right { grid-area: right; }
    .zone-footer { grid-area: footer; font-size: 0.85em; opacity: 0.7; }
    """
    elif tpl == "gallery":
        tpl_css = """
    .zone-header { grid-area: header; font-weight: 700; font-size: 1.4em; }
    .zone-gallery_grid {
      grid-area: gallery;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
      gap: 8px;
    }
    .zone-gallery_grid img { border-radius: 6px; object-fit: cover; width: 100%; }
    .zone-caption { grid-area: caption; font-size: 0.85em; opacity: 0.7; }
    """
    elif tpl == "cards":
        tpl_css = f"""
    .zone-header {{ grid-area: header; font-weight: 700; font-size: 1.4em; }}
    .zone-card_1 {{ grid-area: card1; }}
    .zone-card_2 {{ grid-area: card2; }}
    .zone-card_3 {{ grid-area: card3; }}
    .zone-card_4 {{ grid-area: card4; }}
    .zone-footer {{ grid-area: footer; font-size: 0.85em; opacity: 0.7; }}
    .zone-card_1, .zone-card_2, .zone-card_3, .zone-card_4 {{
      background: rgba(128,128,128,0.08);
      border-radius: 12px;
      padding: 24px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }}
    """
    elif tpl == "timeline":
        tpl_css = f"""
    .zone-header {{ grid-area: header; font-weight: 700; font-size: 1.4em; }}
    .zone-timeline_1 {{ grid-area: t1; }}
    .zone-timeline_2 {{ grid-area: t2; }}
    .zone-timeline_3 {{ grid-area: t3; }}
    .zone-timeline_4 {{ grid-area: t4; }}
    .zone-footer {{ grid-area: footer; font-size: 0.85em; opacity: 0.7; }}
    .timeline-item {{
      display: flex;
      align-items: flex-start;
      gap: 16px;
    }}
    .timeline-marker {{
      flex-shrink: 0;
      width: 40px; height: 40px;
      border-radius: 50%;
      background: {accent};
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 700;
      font-size: 1.2em;
    }}
    .timeline-content {{
      flex: 1;
      padding-top: 8px;
    }}
    """
    elif tpl == "magazine":
        tpl_css = f"""
    .zone-header {{ grid-area: header; }}
    .magazine-title {{ font-size: 2.8em; font-weight: 800; line-height: 1.1; }}
    .zone-lead {{ grid-area: lead; font-size: 1.1em; font-style: italic; opacity: 0.8; }}
    .zone-column_a {{ grid-area: colA; }}
    .zone-column_b {{ grid-area: colB; }}
    .zone-pull_quote {{ grid-area: pullQuote; display: grid; grid-column: 1 / -1; }}
    .pull-quote {{
      border-left: 4px solid {accent};
      padding: 16px 24px;
      margin: 16px 0;
      font-size: 1.3em;
      font-style: italic;
      color: {accent};
      background: rgba(128,128,128,0.04);
      border-radius: 0 8px 8px 0;
    }}
    .zone-image_area {{ grid-area: imageArea; display: grid; grid-column: 1 / -1; }}
    .zone-footer {{ grid-area: footer; font-size: 0.85em; opacity: 0.7; }}
    """
    elif tpl == "pitch":
        tpl_css = f"""
    .zone-hero_bg {{
      position: absolute;
      top: 0; left: 0; right: 0; bottom: 0;
      z-index: 0;
      opacity: 0.3;
    }}
    .page {{ position: relative; }}
    .zone-headline {{ z-index: 1; }}
    .pitch-headline {{
      font-size: 3em;
      font-weight: 800;
      line-height: 1.1;
      color: {text_col};
    }}
    .pitch-body {{
      font-size: 1.25em;
      line-height: 1.6;
      opacity: 0.9;
      z-index: 1;
    }}
    .pitch-cta {{
      display: inline-block;
      padding: 16px 48px;
      background: {accent};
      color: #fff;
      border-radius: 8px;
      font-size: 1.2em;
      font-weight: 700;
      text-decoration: none;
      z-index: 1;
    }}
    """

    return base_css + tpl_css + orientation_css


def _minify(html_str: str) -> str:
    """Basic HTML minification (strip whitespace, remove comments)."""
    # Remove HTML comments
    html_str = re.sub(r"<!--.*?-->", "", html_str, flags=re.DOTALL)
    # Collapse whitespace
    html_str = re.sub(r"\s+", " ", html_str)
    html_str = re.sub(r"> <", "><", html_str)
    return html_str
