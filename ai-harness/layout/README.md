# layout — HTML Page / Slide Layout Engine + PDF Export

AI-driven page and presentation layout service for the AI Harness. Create visually
appealing, self-contained HTML documents with multiple layout templates, portrait
(document) or slide (16:9 presentation) orientation, zone-based content placement,
and **PDF export** for shareable, printable output.

---

## Quick Summary

| Concept | Detail |
|---------|--------|
| **Purpose** | Let an AI agent compose visually structured HTML pages or presentation slides programmatically |
| **Orientation** | `portrait` (A4-style document) or `slide` (1920×1080, 16:9) |
| **Templates** | 10 built-in: `minimal`, `hero`, `grid`, `split`, `gallery`, `cards`, `timeline`, `magazine`, `pitch`, `blank` |
| **Content types** | `text` (markdown → HTML), `image` (URL-based), `table` (styled HTML table) |
| **Output formats** | HTML (self-contained), **PDF** (via WeasyPrint) |
| **PDF storage** | Any subdirectory under `/data/media/` — each workflow chooses its own (e.g. `presentation/`, `research/`). Served publicly via `/media/files/` |
| **Storage** | In-memory during container lifecycle; `/layout/save` persists HTML to workspace; `/layout/export-pdf` persists PDF to media |
| **Integration** | Works with existing `filetools` (workspace file I/O) and `media` (image generation) modules |

---

## Core Concepts

### Zones

Each template defines **zones** — named regions where the AI can place content.
Think of zones as "slots" on a page. The AI calls `/layout/add` for each zone
it wants to fill.

```
┌──────────────────────────────────────┐
│  [ header zone ]                     │
├────────────┬─────────────────────────┤
│            │                         │
│ col_left   │      col_center         │
│  zone      │        zone             │
│            │                         │
├────────────┴─────────────────────────┤
│  [ footer zone ]                     │
└──────────────────────────────────────┘
```

### The AI Workflow Pattern

```
POST /layout/create  →  { layout_id: "abc123" }
POST /media/image    →  { files: [{ url: "..." }] }   (optional)
POST /layout/add     →  zone: "header",      type: "text", content: "..."
POST /layout/add     →  zone: "col_left",    type: "image", image_url: "..."
POST /layout/add     →  zone: "col_center",  type: "text", content: "..."
POST /layout/add     →  zone: "footer",      type: "text", content: "..."
POST /layout/render  →  { html: "<!DOCTYPE html>..." }

# Save as HTML
POST /layout/save    →  { path: "output/pitch-deck.html" }

# OR save as PDF (see PDF Export section below)
POST /layout/export-pdf → { path: "presentation/slide1.pdf", url: "/media/files/presentation/slide1.pdf" }
```

---

## PDF Export

**Key capability:** Export any layout to a PDF file that is:
1. **Persisted** under a workflow-specific subdirectory within `/data/media/` (e.g. `/data/media/presentation/report.pdf`, `/data/media/research/analysis.pdf`)
2. **Publicly accessible** via `/media/files/<subdirectory>/<filename>.pdf` — the same static file server that serves images
3. **Properly paginated** with configurable page size and margins

### Workflow Directory Design

There is no hardcoded "pdf" subdirectory. Each workflow module that uses the layout
engine owns its own subdirectory under the media root. The `output_path` you pass
to `/layout/export-pdf` determines where the PDF lands:

| Workflow | Example `output_path` | On-disk location | Public URL |
|----------|-----------------------|------------------|------------|
| Presentations | `presentation/q4-deck.pdf` | `/data/media/presentation/q4-deck.pdf` | `/media/files/presentation/q4-deck.pdf` |
| Research | `research/saas-analysis.pdf` | `/data/media/research/saas-analysis.pdf` | `/media/files/research/saas-analysis.pdf` |
| Reports | `reports/annual-summary.pdf` | `/data/media/reports/annual-summary.pdf` | `/media/files/reports/annual-summary.pdf` |

The parent directory is created automatically if it doesn't exist. The PDFs are
served by the **same** `StaticFiles` mount (`/media/files/`) that serves generated
images — no separate mount is needed.

### How It Works

```
         ┌───────────────┐
         │  AI workflow  │
         ├───────────────┤
         │ 1. /create    │  Build layout in memory (zones, content)
         │ 2. /add × N   │  Fill zones with text, images, tables
         │ 3. /export-pdf│  ──► HTML rendered with PDF-specific CSS
         │               │     ──► WeasyPrint converts to PDF bytes
         │               │     ──► Written to /data/media/<workflow>/
         │               │     ──► Returns path + public URL
         └───────────────┘
                │
                ▼
         ┌───────────────┐
         │  Static Serve  │  /media/files/ mounted as FastAPI StaticFiles
         │  (app.py)     │  Accessible at http://<harness>/media/files/<path>/
         └───────────────┘
```

### `POST /layout/export-pdf`

Render the layout and export as a PDF file.

**Request:**

```jsonc
{
  "layout_id": "abc123def456",       // required — from /layout/create
  "output_path": "presentation/q4-deck.pdf",  // required — path relative to /data/media/
  "page_size": "Letter",            // optional — "A4" | "Letter" | "Legal" | "A3" | "A5" (default: Letter)
  "margins": {                      // optional — page margins in mm (default: {top:20, bottom:20, left:15, right:15})
    "top": 20,
    "bottom": 20,
    "left": 15,
    "right": 15
  }
}
```

**Response:**

```jsonc
{
  "layout_id": "abc123def456",
  "path": "presentation/q4-deck.pdf",
  "url": "/media/files/presentation/q4-deck.pdf",
  "bytes_written": 45678
}
```

The PDF is immediately available at:
- **Internal:** `http://thor.local:8090/media/files/presentation/q4-deck.pdf`
- **Via Caddy (Siri-facing):** `https://siri.choukalos.com/media/files/presentation/q4-deck.pdf`

### PDF-Specific Rendering

The PDF export uses a *different CSS pipeline* than the browser HTML render:

| Aspect | Browser HTML | PDF Export |
|--------|---------------|------------|
| Page size | Fixed dimensions (slide) or full-width (portrait) | Driven by `page_size` parameter (A4/Letter/etc.) via `@page` |
| Viewport meta | Included | Stripped (irrelevant for PDF) |
| Backgrounds | Standard CSS | Forces `@page { background: ... }` so WeasyPrint renders solid colors |
| Pagination | Single-page layout | WeasyPrint paginates automatically; `page` CSS page breaks respected |
| Engine | Browser rendering | WeasyPrint (HTML/CSS → PDF, headless) |

### PDF Export — Usage as an AI Agent

When asked to produce a PDF, follow this pattern:

```
// Step 1: Create the layout (portrait is best for documents)
POST /layout/create {
  "orientation": "portrait",
  "template": "minimal",          // or "magazine", "grid", etc.
  "title": "Market Research — SaaS Sector Q2 2025",
  "background_color": "#ffffff",
  "text_color": "#1a1a1a",
  "accent_color": "#2563eb"
}
→ { "layout_id": "a1b2c3" }

// Step 2: Fill zones
POST /layout/add {
  "layout_id": "a1b2c3",
  "zone": "header",
  "content_type": "text",
  "content": "# **Market Research Report**\n\nSaaS Sector — Q2 2025"
}

POST /layout/add {
  "layout_id": "a1b2c3",
  "zone": "content",
  "content_type": "text",
  "content": "## Executive Summary\n\nThis report analyzes the SaaS market..."
}

POST /layout/add {
  "layout_id": "a1b2c3",
  "zone": "content",
  "content_type": "table",
  "table_columns": [
    { "name": "Company", "key": "company" },
    { "name": "Revenue", "key": "revenue", "align": "right" },
    { "name": "Growth", "key": "growth", "align": "center" }
  ],
  "table_rows": [
    { "company": "Acme Inc", "revenue": "$12.4M", "growth": "+22%" },
    { "company": "Globex", "revenue": "$8.1M", "growth": "+15%" }
  ],
  "append": true
}

// Step 3: Export to PDF — choose your workflow directory
POST /layout/export-pdf {
  "layout_id": "a1b2c3",
  "output_path": "research/saas-market-q2-2025.pdf",
  "page_size": "Letter"
}
→ { "path": "research/saas-market-q2-2025.pdf", "url": "/media/files/research/saas-market-q2-2025.pdf" }

// Share the URL with the user
"The PDF is available at http://thor.local:8090/media/files/research/saas-market-q2-2025.pdf"
```

### Multi-Page PDF Strategy

The layout engine works with *single-page layouts*. For multi-page documents
(e.g., a 20-page market research report), the AI should:

1. **Create multiple layouts** — one per page (use the template that fits each page's content)
2. **Export each to a separate PDF** via `/layout/export-pdf`
3. **Merge PDFs** using an external tool (future: a `/layout/merge-pdfs` endpoint)

> **Future enhancement:** Add a `/layout/merge-pdfs` endpoint that takes multiple
> PDF filenames (anywhere under `/data/media/`) and merges them into a single
> multi-page PDF using `pypdf`.

### Choosing a Workflow Directory

When building a new workflow that produces PDFs, pick a sensible subdirectory name
under `/data/media/`. Some guidelines:

| Workflow type | Recommended directory | Rationale |
|---------------|----------------------|-----------|
| Presentations, pitch decks, slide shows | `presentation/` | Clear, self-documenting |
| Market research, analysis reports | `research/` | Separates research output from other content |
| Business reports, summaries | `reports/` | Generic catch-all for report-style output |

The directory is created automatically by the service — you only need to decide
on the name when wiring up your workflow.

---

## Orientation Modes

| Mode | Value | Dimensions | Use Case |
|------|-------|------------|----------|
| **Portrait** | `portrait` | ~8.5×11 (full-width browser) | Reports, articles, long-form content, essays |
| **Slide** | `slide` | 1920×1080 (16:9) | Presentations, pitch decks, single-screen slides |

---

## Built-in Templates

### `minimal`
Clean single-column with header, content, and footer.
- **Zones:** `header`, `content`, `footer`

### `hero`
Full-width hero banner with title/subtitle overlay + body section.
- **Zones:** `hero_background` (image), `hero_title`, `hero_subtitle`, `body`

### `grid`
Three-column grid with header and footer.
- **Zones:** `header`, `col_left`, `col_center`, `col_right`, `footer`

### `split`
Two-column layout (50/50) with header and footer.
- **Zones:** `header`, `panel_left`, `panel_right`, `footer`

### `gallery`
Masonry-style image grid with header and caption area.
- **Zones:** `header`, `gallery_grid`, `caption`

### `cards`
Four card slots in a 2×2 grid with header and footer.
- **Zones:** `header`, `card_1`, `card_2`, `card_3`, `card_4`, `footer`

### `timeline`
Vertical timeline with 4 milestone markers (circle + content).
- **Zones:** `header`, `timeline_1`, `timeline_2`, `timeline_3`, `timeline_4`, `footer`

### `magazine`
Editorial two-column layout with pull quote and image area.
- **Zones:** `header`, `lead`, `column_a`, `column_b`, `pull_quote`, `image_area`, `footer`

### `pitch`
Pitch-deck style: hero background, large headline, supporting text, CTA button.
- **Zones:** `hero_bg` (image), `headline`, `supporting_text`, `cta`

### `blank`
No predefined zones. AI can create arbitrary zone names with custom CSS grid positioning.
- **Zones:** None — fully custom

---

## Endpoints

Base: `/layout` — all require `HARNESS_API_KEY` auth.

### `POST /layout/create`

Create a new layout.

```jsonc
{
  "orientation": "slide",          // "portrait" | "slide"
  "template": "pitch",            // template name
  "title": "My Product Launch",
  "background_color": "#0f172a",   // hex, rgb, or named CSS color
  "text_color": "#f1f5f9",
  "accent_color": "#38bdf8",
  "font_family": "Georgia, serif" // optional override
}
```

**Response:**

```jsonc
{
  "layout_id": "abc123def456",
  "orientation": "slide",
  "template": "pitch",
  "title": "My Product Launch",
  "zones": ["hero_bg", "headline", "supporting_text", "cta"],
  "content_count": 0
}
```

### `POST /layout/add`

Push content into a zone.

```jsonc
// Text content
{
  "layout_id": "abc123def456",
  "zone": "headline",
  "content_type": "text",
  "content": "# **Launch Day**\n\nThe future is here.",
  "alignment": "center"
}

// Image content
{
  "layout_id": "abc123def456",
  "zone": "hero_bg",
  "content_type": "image",
  "image_url": "http://thor.local:8090/media/files/images/hero-shot.png"
}

// Append text to existing zone
{
  "layout_id": "abc123def456",
  "zone": "body",
  "content_type": "text",
  "content": "\n\nAdditional paragraph here.",
  "append": true
}
```

### `POST /layout/table`

Render a standalone styled HTML table — **no layout needed**.

```jsonc
{
  "title": "Q4 Sales Summary",
  "columns": [
    { "name": "Region", "key": "region", "align": "left" },
    { "name": "Revenue", "key": "revenue", "align": "right", "width": "120px" },
    { "name": "Growth", "key": "growth", "align": "center" }
  ],
  "rows": [
    { "region": "North America", "revenue": "$1.2M", "growth": "+18%" },
    { "region": "Europe", "revenue": "$890K", "growth": "+7%" },
    { "region": "Asia Pacific", "revenue": "$650K", "growth": "+24%" }
  ],
  "standalone": true,   // full HTML document (default) vs fragment only
  "style": {            // optional — all fields have sensible defaults
    "header_bg": "#1e3a5f",
    "header_color": "#ffffff",
    "row_alt_bg": "#f8fafc",
    "border_color": "#e2e8f0",
    "text_color": "#334155",
    "font_size": "14px",
    "border_radius": 8,
    "striping": true,
    "hover": true,
    "compact": false
  }
}
```

**Response:** `{ "html": "<!DOCTYPE html>...", "file_size_bytes": 2345 }`

### `POST /layout/add` — table content

Place a styled table inside an existing layout zone.

```jsonc
{
  "layout_id": "abc123def456",
  "zone": "content",
  "content_type": "table",
  "table_columns": [
    { "name": "Name", "key": "name" },
    { "name": "Score", "key": "score", "align": "center" }
  ],
  "table_rows": [
    { "name": "Alice", "score": "95" },
    { "name": "Bob", "score": "87" }
  ],
  "table_style": { "header_bg": "#3b82f6", "compact": true },
  "append": false
}
```

The table inherits the layout's `accent_color` for the wrapper styling and is
returned as a fragment (no `<html>` wrapper) so it renders cleanly inside the zone.

### `POST /layout/render`

Render to HTML (preview before saving).

```jsonc
{
  "layout_id": "abc123def456",
  "include_meta": true,
  "minify": false
}
```

**Response:** `{ "layout_id": "...", "html": "<!DOCTYPE html>...", "file_size_bytes": 12345 }`

### `POST /layout/save`

Render and save to workspace.

```jsonc
{
  "layout_id": "abc123def456",
  "output_path": "presentations/q4-review.html"
}
```

**Response:** `{ "layout_id": "...", "path": "presentations/q4-review.html", "bytes_written": 12345 }`

### `POST /layout/export-pdf`

Render and export as a PDF file. See the **PDF Export** section above for full details.

### `GET /layout/active`

List all in-memory layouts.

### `DELETE /layout/{layout_id}`

Discard a layout.

---

## Markdown Support

Text content accepts a **lightweight markdown subset** (no external library — pure Python):

| Syntax | Renders As |
|--------|------------|
| `# H1` … `###### H6` | Headings |
| `**bold**` | Bold |
| `*italic*` | Italic |
| `` `code` `` | Inline code |
| `[text](url)` | Hyperlink (opens in new tab) |
| `- item` | Unordered list |
| `![alt](url)` | Inline image |

AI can also pass raw HTML snippets directly for fine-grained control.

---

## Integration with Existing Modules

### With `media` (image generation)

```
# 1. Generate an image
POST /media/image { "prompt": "futuristic cityscape at sunset, 16:9" }
→ { "files": [{ "url": "/media/files/images/...", "filename": "..." }] }

# 2. Use that image in a layout
POST /layout/add {
  "layout_id": "...",
  "zone": "hero_bg",
  "content_type": "image",
  "image_url": "http://thor.local:8090/media/files/images/..."
}
```

### With `filetools` (workspace file management)

```
# Save the layout as HTML
POST /layout/save { "output_path": "output/my-doc.html" }

# Verify with filetools
POST /files/read { "path": "output/my-doc.html" }

# Clean up
POST /files/delete { "path": "output/my-doc.html" }
```

### PDF Output — File Lifecycle

```
# PDFs are saved anywhere under /data/media/ — the same tree as images.
# They are served by the SAME static server that serves /media/files/.

# Export to workflow-specific directory
POST /layout/export-pdf {
  "layout_id": "abc123",
  "output_path": "research/my-report.pdf"
}
→ { "url": "/media/files/research/my-report.pdf" }

# The PDF is now at:
#   Container:  /data/media/research/my-report.pdf
#   Internal:   http://thor.local:8090/media/files/research/my-report.pdf
#   Public (Caddy): https://siri.choukalos.com/media/files/research/my-report.pdf
```

---

## Design Decisions

1. **In-memory layouts** — no database dependency. Layouts live until the container restarts.
   Use `/layout/active` to discover existing layouts. For multi-page documents, the AI
   creates separate layouts and saves each independently.

2. **Self-contained HTML** — all CSS is inline. No external stylesheets, CDNs, or fonts.
   The generated file works offline and in any browser.

3. **Zone-based, not free-form** — templates constrain the AI to produce consistent
   visual output. The `blank` template exists for maximum creativity when needed.

4. **No server-side image handling** — image zones reference URLs. The AI is responsible
   for generating/storing images via the `media` module before referencing them.

5. **PDF via WeasyPrint** — the layout HTML is rendered through WeasyPrint's HTML→PDF
   engine. CSS `@page` rules control page size and margins. Backgrounds are explicitly
   set on `@page` so WeasyPrint (which strips backgrounds by default) includes them.

6. **PDFs live in the media tree** — no separate `/pdfs/` directory. PDFs go wherever
   the workflow code says they belong (`presentation/`, `research/`, etc.). The
   existing `/media/files/` static mount serves the entire `/data/media/` tree,
   including any subdirectory the workflow creates.

7. **Workflow-owned directories** — each workflow module decides its own output path
   within `/data/media/`. The service creates parent directories automatically. No
   hardcoded paths or separate static files mounts are needed.

---

## Extending Templates

To add a new template, edit `service.py` and add to `_register_templates()`:

```python
_TEMPLATES["my_template"] = {
    "zones": ["header", "main_zone", "sidebar", "footer"],
    "grid_rows": "auto 1fr auto",
    "grid_cols": "2fr 1fr",
    "zone_map": {
        "header": "header",
        "main_zone": "main",
        "sidebar": "side",
        "footer": "footer",
    },
}
```

Then add template-specific CSS in `_build_stylesheet()` under the `tpl == "my_template"` branch.

---

## Future Development Notes

### Multi-page PDF Merge

Add a `/layout/merge-pdfs` endpoint that takes multiple PDF filenames from
anywhere under `/data/media/` and merges them into a single multi-page PDF using
`pypdf`. Workflow:
1. AI creates N layouts (one per page)
2. Exports each to PDF via `/layout/export-pdf`
3. Calls `/layout/merge-pdfs` with the list of filenames
4. Result: single combined PDF ready for sharing

### Slide Transitions

For presentation-mode slide layouts:
- Could add `<style>` transition CSS between pages
- Add keyboard navigation (←→ keys to flip pages)

### Dynamic Images

Currently images are URL-referenced. Future option:
- Embed images as base64 data URIs for fully portable output
- Require an endpoint that reads the image bytes and inlines them

### PDF Cover Pages / Table of Contents

For report-style PDFs:
- Add endpoint or template support for auto-generated TOC
- Add cover page template with title, subtitle, date, author

### Theming

- Pre-built theme presets (dark mode, corporate, playful, etc.)
- Pass `theme: "dark"` instead of individual colors

### Rich Content Types

- Tables are fully implemented (`content_type: "table"`). See above.
- `chart` — inline SVG chart generation (bar, pie, line) — planned
- `video` — embed video clips from media module — planned

### Validation Hooks

- Add zone validation (reject adding content to non-existent zones in strict mode)
- Add content length guards for slide templates (keep text scannable)

---

## API Key & Auth

All endpoints require `HARNESS_API_KEY` via either:
- `X-API-Key: <key>` header
- `Authorization: Bearer <key>` header

Same auth as the rest of the AI Harness (`core/security.py`).

---

## Quick Reference — Adding PDF to a Workflow

When asked to add PDF output to a workflow, follow this checklist:

1. **The layout is already built** (via `/layout/create` + `/layout/add` calls)
2. **Call `/layout/export-pdf` with:**
   - `layout_id` from the create step
   - `output_path` as `<workflow-subdir>/filename.pdf` (e.g. `"research/report.pdf"`)
   - `page_size` matching the document type (`Letter` for US reports, `A4` for international)
3. **Return the `url` from the response** to the user/client — it will be
   `/media/files/<the-output-path-you-gave>`
4. **For multi-page documents:** create multiple layouts, export each, then call (future) `/layout/merge-pdfs`

### When wiring up a new workflow module:
1. Decide on a subdirectory name under `/data/media/` (e.g. if building a presentation module, use `"presentation/"`)
2. Hard-code that prefix into your workflow's export calls, or pass it as a config
3. No other configuration needed — the directory is auto-created, and `/media/files/` already serves it
