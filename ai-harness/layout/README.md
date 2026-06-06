# layout — HTML Page / Slide Layout Engine + PDF Export

AI-driven document composition service for the AI Harness. Build visually structured
HTML documents and presentation slides with zone-based templates, styled tables,
AI-generated images (inline via ComfyUI), and PDF export — from the step-by-step
pattern all the way up to one-shot multi-zone document builds.

---

## Quick Summary

| Concept | Detail |
|---------|--------|
| **Endpoint prefix** | `/layout` — all require API-key auth |
| **Purpose** | Compose visually structured HTML pages, presentation slides, and PDFs programmatically |
| **Orientation** | `portrait` (document) or `slide` (1920×1080, 16:9) |
| **Templates** | 10 built-in: `minimal`, `hero`, `grid`, `split`, `gallery`, `cards`, `timeline`, `magazine`, `pitch`, `blank` |
| **Content types** | `text`, `image`, `table`, `gen_image`, **`chart`** (Plotly line/bar/pie) |
| **Output formats** | HTML (self-contained, offline-ready), **PDF** (via WeasyPrint) |
| **Storage** | HTML saved to workspace (`/layout/save`); PDFs and images saved to `/data/media/` |
| **Chart engine** | Plotly + Kaleido — line, bar, pie/donut charts as PNG, SVG, or interactive HTML |

---

## API Endpoints

| Method | Path | Description |
|--------|------|--|-|
| `POST` | `/layout/create` | Create a new layout document |
| `POST` | `/layout/add` | Add content (text / image / table) to a zone |
| `POST` | `/layout/add-generated-image` | Generate an image via ComfyUI and place it in a zone |
| `POST` | `/layout/build` | One-shot: create + populate (with inline images) + render + save |
| `POST` | `/layout/render` | Preview layout as HTML (no save) |
| `POST` | `/layout/save` | Render layout and save HTML to workspace |
| `POST` | `/layout/export-pdf` | Render layout and export PDF to media directory |
| `POST` | `/layout/table` | Render a standalone styled HTML table (no layout needed) |
| `POST` | `/chart/line` | Generate a line chart (PNG, SVG, or interactive HTML) |
| `POST` | `/chart/bar` | Generate a bar chart (grouped/stacked, PNG/SVG/HTML) |
| `POST` | `/chart/pie` | Generate a pie or donut chart (PNG/SVG/HTML) |
| `POST` | `/chart/any` | Unified chart endpoint — auto-routes by `chart_type` |
| `GET` | `/layout/active` | List all active in-memory layouts |
| `DELETE` | `/layout/{layout_id}` | Discard a layout |

---

## Workflow Patterns

Three patterns are available, from granular to one-shot:

### Pattern A — Step-by-step build (original)

```
POST /layout/create      → { layout_id: "abc123" }
POST /media/image        → { files: [{ url: "..." }] }   // optional, generate images separately
POST /layout/add         → zone: "header",   content_type: "text", content: "..."
POST /layout/add         → zone: "body",     content_type: "image", image_url: "..."
POST /layout/render      → { html: "<!DOCTYPE html>..." }
POST /layout/save        → { path: "output/my-doc.html" }
POST /layout/export-pdf  → { path: "reports/my-doc.pdf", url: "/media/files/reports/my-doc.pdf" }
```

### Pattern B — Inline image generation

Same as above, but skip the separate `/media/image` call. Use
`/layout/add-generated-image` to generate and place the image in one step:

```
POST /layout/create           → { layout_id: "abc123" }
POST /layout/add              → zone: "header", content_type: "text", content: "..."
POST /layout/add-generated-image → zone: "hero_bg",
  prompt: "cinematic sunset over futuristic cityscape, volumetric light",
  width: 1920, height: 1080
POST /layout/render           → { html: "..." }
POST /layout/save             → { path: "output/deck.html" }
```

The image is generated, saved to `/data/media/images/`, and its URL is
automatically placed into the zone. No intermediate URL tracking required.

### Pattern C — One-shot document build

```
POST /layout/build  →  {
  orientation: "portrait",
  template: "magazine",
  title: "AI Market Report",
  zones: [
    { zone: "header",    content_type: "text",       content: "# Report ..." },
    { zone: "image_area",content_type: "gen_image",  image_prompt: "infographic ..." },
    { zone: "column_a",  content_type: "text",       content: "## Summary ..." },
    { zone: "column_b",  content_type: "table",      table_columns: [...], table_rows: [...] },
  ],
  output_path: "reports/ai-report.html",
  export_pdf: true,
  pdf_path: "reports/ai-report.pdf",
  pdf_page_size: "Letter"
}
→  {
    html_path: "reports/ai-report.html",
    html_bytes: 45678,
    pdf_path: "reports/ai-report.pdf",
    pdf_url: "/media/files/reports/ai-report.pdf",
    generated_images: [{ filename: "...", url: "...", zone: "image_area" }],
  }
```

---

## Core Concepts

### Zones

Each template defines **zones** — named regions where content is placed. Think of
zones as "slots" on a page. The AI fills each zone via `/layout/add`,
`/layout/add-generated-image`, or by specifying them in `/layout/build`.

```
┌──────────────────────────────────┐
│  [ header zone ]                 │
├─────────────┬────────────────────┤
│             │                   │
│  col_left   │    col_center     │
│  zone       │    zone           │
│             │                   │
├─────────────┴────────────────────┤
│  [ footer zone ]                 │
└──────────────────────────────────┘
```

### Two-Stage Content Placement

The AI always works in two stages:

1. **Create** — define the layout shell (template, orientation, colors)
2. **Fill zones** — push content into zones one at a time
   - Multiple calls to the same zone **replace** unless `append: true`

### Append vs. Replace

Default behavior: each call to `/layout/add` **replaces** the zone's previous
content. Set `"append": true` to add to existing content instead.

---

## Templates Reference

### `minimal` — Clean single-column
- **Zones:** `header`, `content`, `footer`

### `hero` — Full-width hero banner with overlay title + body
- **Zones:** `hero_background` (image, rendered as CSS background), `hero_title`, `hero_subtitle`, `body`

### `grid` — Three-column grid
- **Zones:** `header`, `col_left`, `col_center`, `col_right`, `footer`

### `split` — Two-column (50/50)
- **Zones:** `header`, `panel_left`, `panel_right`, `footer`

### `gallery` — Masonry-style image grid
- **Zones:** `header`, `gallery_grid`, `caption`

### `cards` — Four card slots (2×2)
- **Zones:** `header`, `card_1`, `card_2`, `card_3`, `card_4`, `footer`

### `timeline` — Vertical timeline with 4 milestone markers
- **Zones:** `header`, `timeline_1`, `timeline_2`, `timeline_3`, `timeline_4`, `footer`

### `magazine` — Editorial two-column with pull quote and spanning image area
- **Zones:** `header` (large masthead title), `lead` (italic summary), `column_a`, `column_b`, `pull_quote`, `image_area`, `footer`

### `pitch` — Pitch-deck style with hero background, headline, body, CTA button
- **Zones:** `hero_bg` (image, 30% opacity overlay), `headline`, `supporting_text`, `cta`

### `blank` — No predefined zones — fully custom CSS grid
- **Zones:** None — define arbitrary zone names with custom CSS grid positioning

---

## Endpoint Reference

### `POST /layout/create`

Create a new layout. Returns a `layout_id` used by all subsequent calls.

**Request — `CreateLayoutRequest`:**

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `orientation` | `portrait | slide` | `"portrait"` | portrait = document, slide = 1920×1080 |
| `template` | string | `"minimal"` | One of the 10 template names |
| `title` | string | `""` | Page title (appears in HTML \<title\>) |
| `background_color` | string | `"#ffffff"` | Hex, rgb, or named CSS color |
| `text_color` | string | `"#1a1a1a"` | Primary text color |
| `accent_color` | string | `"#3b82f6"` | Headings, links, highlights |
| `font_family` | string | `"system-ui, ..."` | CSS font-family string |
| `page_margin` | int (0–120) | `40` | Page margin in pixels |

**Response:**

```json
{
  "layout_id": "abc123def456",
  "orientation": "portrait",
  "template": "minimal",
  "title": "My Doc",
  "zones": ["header", "content", "footer"],
  "content_count": 0
}
```

---

### `POST /layout/add`

Push content into a zone.

**Request — `AddContentRequest`:**

| Field | Type | Required When | Notes |
|-------|------|--|-------|
| `layout_id` | string | always | From `/layout/create` |
| `zone` | string | always | Zone name for the chosen template |
| `content_type` | `text | image | table | chart` | always | |
| `content` | string | `content_type == "text"` | Markdown or raw HTML snippet |
| `image_url` | string | `content_type == "image"` | **Absolute** URL (http/https) |
| `table_columns` | array | `content_type == "table"` | Column definitions (see below) |
| `table_rows` | array of dicts | `content_type == "table"` | Row data keyed by column `key` |
| `table_style` | object | | Optional table style override |
| `chart_spec` | `ChartZoneSpec` object | `content_type == "chart"` | Chart data + style (see Chart section) |
| `alignment` | `left | center | right` | | Default `"center"` |

**Table column definition:**

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | string | | Header text |
| `key` | string | | Lookup key for row values |
| `align` | `left | center | right` | `"left"` | |
| `width` | string | | CSS width e.g. `"120px"` |

**Table style (optional override):**

| Field | Type | Default |
|-------|------|---------|
| `header_bg` | string | `"#1e3a5f"` |
| `header_color` | string | `"#ffffff"` |
| `row_alt_bg` | string | `"#f8fafc"` |
| `border_color` | string | `"#e2e8f0"` |
| `text_color` | string | `"#334155"` |
| `font_family` | string | `"system-ui, ..."` |
| `font_size` | string | `"14px"` |
| `border_radius` | int | `8` |
| `striping` | bool | `true` |
| `hover` | bool | `true` |
| `compact` | bool | `false` |

---

### `POST /layout/add-generated-image`

Generate an image via ComfyUI and place it directly into a zone in one call.

**Request — `AddGeneratedImageRequest`:**

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `layout_id` | string | | From `/layout/create` |
| `zone` | string | | Zone name |
| `prompt` | string | | Image generation prompt |
| `negative_prompt` | string | `"blurry, distorted, low quality"` | |
| `width` | int (256–2048) | `1024` | |
| `height` | int (256–2048) | `576` | |
| `seed` | int | `-1` | `-1` = random; positive = reproducible |
| `steps` | int (1–80) | `30` | Denoising steps |
| `cfg` | float (1.0–20.0) | `7.0` | CFG scale |
| `alignment` | `left | center | right` | `"center"` | |
| `style_class` | string | `""` | Additional CSS class names |
| `append` | bool | `false` | Append to existing zone content |

**Response — `AddGeneratedImageResponse`:**

```json
{
  "layout_id": "abc123def456",
  "zone": "hero_bg",
  "image_url": "http://thor.local:8090/media/files/images/...png",
  "image_filename": "my-prompt-hash.png",
  "job_id": "a1b2c3",
  "status": "generated_and_placed"
}
```

The image is saved to `/data/media/images/` and the absolute URL is placed into
the layout zone automatically.

---

### `POST /layout/build`

Build a complete document in a **single call**. Orchestrates the entire pipeline:
create layout → populate zones (with inline image generation) → render → save HTML
→ optionally export PDF.

**Request — `BuildDocumentRequest`:**

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `orientation` | `portrait | slide` | `"portrait"` | |
| `template` | string | `"minimal"` | |
| `title` | string | `""` | |
| `background_color` | string | `"#ffffff"` | |
| `text_color` | string | `"#1a1a1a"` | |
| `accent_color` | string | `"#3b82f6"` | |
| `font_family` | string | `"system-ui, ..."` | |
| `page_margin` | int (0–120) | `40` | |
| `zones` | array of `ZoneContentSpec` | **required** | Zone content specs (see below) |
| `output_path` | string | **required** | Path within workspace (e.g. `"reports/q2.html"`) |
| `export_pdf` | bool | `false` | If `true`, also export PDF |
| `pdf_path` | string | | Required when `export_pdf=true` |
| `pdf_page_size` | `A4 | Letter | Legal | A3 | A5` | `"Letter"` | |

**Zone content spec — `ZoneContentSpec`:**

| Field | Type | Required When | Notes |
|-------|------|--|-------|
| `zone` | string | always | Zone name |
| `content_type` | `text | image | table | gen_image | chart` | always | Use `gen_image` for inline AI image gen, `chart` for charts |
| `content` | string | `content_type == "text"` | Markdown or HTML snippet |
| `image_url` | string | `content_type == "image"` | Absolute URL |
| `image_prompt` | string | `content_type == "gen_image"` | Prompt for ComfyUI |
| `image_negative_prompt` | string | | Default `"blurry, distorted, low quality"` |
| `image_width` | int | | Default `1024` |
| `image_height` | int | | Default `576` |
| `image_seed` | int | | Default `-1` (random) |
| `image_steps` | int | | Default `30` |
| `image_cfg` | float | | Default `7.0` |
| `table_columns` | array of column defs | `content_type == "table"` | Same as `/layout/add` table columns |
| `table_rows` | array of dicts | `content_type == "table"` | Same as `/layout/add` table rows |
| `table_style` | object | | Optional table style |
| `chart_spec` | `ChartZoneSpec` object | `content_type == "chart"` | Chart data + style (see Chart section) |
| `alignment` | `left | center | right` | | Default `"center"` |

**Response — `BuildDocumentResponse`:**

```json
{
  "layout_id": "a1b2c3d4e5",
  "html_path": "reports/q2-report.html",
  "html_bytes": 45678,
  "pdf_path": "reports/q2-report.pdf",
  "pdf_url": "/media/files/reports/q2-report.pdf",
  "pdf_bytes": 123456,
  "generated_images": [
    {
      "filename": "infographic-hash.png",
      "url": "http://thor.local:8090/media/files/images/infographic-hash.png",
      "zone": "image_area"
    }
  ]
}
```

---

### `POST /layout/render`

Preview the layout as HTML without saving.

**Request — `RenderLayoutRequest`:**

| Field | Type | Default |
|-------|------|---------|
| `layout_id` | string | (required) |
| `include_meta` | bool | `true` |
| `minify` | bool | `false` |

**Response:** `{ "layout_id": "...", "html": "<!DOCTYPE html>...", "file_size_bytes": 12345 }`

---

### `POST /layout/save`

Render and save the layout as self-contained HTML to workspace.

**Request — `SaveLayoutRequest`:**

| Field | Type | Notes |
|-------|------|-------|
| `layout_id` | string | |
| `output_path` | string | Relative path within workspace, e.g. `"presentations/q4.html"` |

**Response:** `{ "layout_id": "...", "path": "...", "bytes_written": 12345 }`

---

### `POST /layout/export-pdf`

Render and export the layout as a PDF to the media directory.

**Request — `ExportPdfRequest`:**

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `layout_id` | string | | |
| `output_path` | string | | Path under `/data/media/`, e.g. `"reports/rpt.pdf"` |
| `page_size` | `A4 | Letter | Legal | A3 | A5` | `"Letter"` | |
| `margins` | `{ top, bottom, left, right }` | `{ top:20, bottom:20, left:15, right:15 }` | Values in mm |

**Response:** `{ "layout_id": "...", "path": "...", "url": "/media/files/...", "bytes_written": 45678 }`

The PDF is immediately available at:
- Internal: `http://thor.local:8090/media/files/<output_path>`
- Via Caddy: `https://siri.choukalos.com/media/files/<output_path>`

PDFs live in the **same media tree** as images and are served by the same
`/media/files/` static mount.

---

### `POST /layout/table`

Render a standalone styled HTML table — no layout needed.

**Request — `CreateTableRequest`:**

| Field | Type | Notes |
|-------|------|-------|
| `title` | string | Optional table title |
| `columns` | array of column defs | Required |
| `rows` | array of dicts | Required |
| `style` | TableStyle object | Optional — all fields have defaults |
| `standalone` | bool | Default `true` (full HTML doc); `false` returns fragment only |

**Response:** `{ "html": "<!DOCTYPE html>...", "file_size_bytes": 2345 }`

---

### `GET /layout/active`

List all active in-memory layouts. Returns an array of `{ layout_id, template, orientation, title, content_count, created_at }`.

### `DELETE /layout/{layout_id}`

Discard a layout from memory. Returns `{ "layout_id": "...", "deleted": true }`.

---

## Markdown Support

Text content (`content_type: "text"`) accepts a lightweight markdown subset
(converted to HTML in pure Python, no external library):

| Syntax | Renders | Notes |
|--------|---------|-------|
| `# H1` … `###### H6` | Headings | |
| `**bold**` | Bold | |
| `*italic*` | Italic | |
| `***bold italic***` | Bold + Italic | |
| `` `code` `` | Inline code | |
| `[text](url)` | Hyperlink | Opens in new tab |
| `- item` | Unordered list | Consecutive `-` items merge into one \<ul\> |
| `![alt](url)` | Inline image | Uses `.md-image` CSS class |

Raw HTML snippets can also be passed directly for fine-grained control.

---

## PDF Export

PDF export uses WeasyPrint with PDF-specific CSS rendering:

| Aspect | Browser HTML | PDF |
|--------|:--:|:--:|
| Page size | Fixed (slide) or full-width (portrait) | Driven by `page_size` via `@page` |
| Viewport meta | Included | Stripped |
| Backgrounds | Standard CSS | Forces `@page { background: ... }` |
| Pagination | Single-page | Auto-paginates; CSS page breaks respected |
| Engine | Browser | WeasyPrint (headless) |

### Multi-Page Documents

Each layout is a single page. For multi-page documents:
1. Create multiple layouts (one per page)
2. Export each to PDF via `/layout/export-pdf`
3. Merge PDFs externally (future: `/layout/merge-pdfs`)

### Choosing a Workflow Directory

Under `/data/media/`, pick a subdirectory that matches your workflow:

| Workflow | Recommended directory |
|----------|------|
| Presentations | `presentation/` |
| Research / analysis | `research/` |
| Business reports | `reports/` |
| Documents / articles | `documents/` |

The service creates parent directories automatically.

---

## File Locations

| What | Where | Served At |
|------|-------|----------|
| HTML (from `/layout/save`) | `/home/chuck/workspace/` | Workspace file system |
| Images (generated) | `/data/media/images/` | `/media/files/images/` |
| Charts (PNG/SVG) | `/data/media/charts/` | `/media/files/charts/` |
| PDFs (from `/layout/export-pdf` or `/layout/build`) | `/data/media/<your-path>/` | `/media/files/<your-path>/` |

---

## Design Decisions

1. **In-memory layouts** — no database. Layouts persist until the container restarts.
   Use `GET /layout/active` to discover existing layouts.

2. **Self-contained HTML** — all CSS inline, no external dependencies, CDNs, or fonts.
   Works offline in any browser.

3. **Zone-based, not free-form** — templates constrain the AI to consistent output.
   `blank` template exists for maximum freedom.

4. **Images are URL-referenced** — absolute URLs in image zones. The AI may:
   - Generate via `/media/image` then reference the returned URL
   - Use `/layout/add-generated-image` (auto-managed URL)
   - Use `/layout/build` with `content_type: "gen_image"` (fully inline)

5. **PDF via WeasyPrint** — CSS `@page` rules control size and margins. Backgrounds
   are explicitly set on `@page` so WeasyPrint renders solid colors.

7. **Charts via Plotly + Kaleido** — line, bar, and pie/donut charts rendered to
   PNG (raster), SVG (vector), or interactive HTML fragments. Charts save to
   `/data/media/charts/` and are served alongside images via `/media/files/charts/`.
   For PDF output use `png` or `svg` — the layout engine embeds the image URL.
   For browser viewing, `html_fragment` gives interactive zoom/tooltip support.

---

## Auth

All endpoints require `HARNESS_API_KEY` via either:
- `X-API-Key: <key>` header
- `Authorization: Bearer <key>` header

---

## Extending Templates

To add a custom template, edit `service.py` and register in `_register_templates()`:

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

Then add template-specific CSS in `_build_stylesheet()` under a new
`tpl == "my_template"` branch.

---

## OpenWebUI Tool

The `create_document()` tool (harness_tools v0.5.0) exposes the full document build
pipeline from OpenWebUI. Call it with a title, template, JSON zones spec, and optional
PDF export settings:

```python
create_document(
    title="Q2 Market Report",
    template="magazine",
    orientation="portrait",
    zones='[
      {"zone": "header", "content_type": "text", "content": "# Q2 Report"},
      {"zone": "image_area", "content_type": "gen_image", "image_prompt": "AI market infographic"},
      {"zone": "column_a", "content_type": "text", "content": "## Summary\n\n..."},
    ]',
    output_path="reports/q2-report.html",
    export_pdf=True,
    pdf_path="reports/q2-report.pdf",
)
```

This is the highest-level interface — one tool call produces a complete formatted
document (HTML + optional PDF) with AI-generated images placed automatically.

---

## Charts (Plotly + Kaleido)

The harness includes a first-class **charts** module backed by Plotly + Kaleido,
supporting line, bar, and pie/donut graphs. Charts can be generated standalone via
`</chart/>` endpoints **or** placed directly into layout zones via `content_type: "chart"`.

### Chart endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chart/line` | Line chart with one or more data series |
| `POST` | `/chart/bar` | Bar chart (grouped, stacked, vertical/horizontal) |
| `POST` | `/chart/pie` | Pie or donut chart |
| `POST` | `/chart/any` | Unified endpoint — specify `chart_type` and matching data |

All require `HARNESS_API_KEY` auth (same as layout endpoints).

### Output formats

Every chart endpoint accepts `output_format`:

| Format | Description |
|--------|-------------|
| `png` | Static raster image saved to `/data/media/charts/`; response includes `url` |
| `svg` | Vector image saved to `/data/media/charts/`; response includes `url` |
| `html_fragment` | Interactive Plotly HTML embed (CDN-loaded Plotly.js); response includes `html_fragment` |

Saved charts are served at `%INTERNAL_BASE_URL%/media/files/charts/<filename>` alongside
images and PDFs.

### Chart configuration (`ChartConfig`)

All chart types accept an optional `config` object:

| Field | Default | Description |
|-------|---------|-------------|
| `title` | `""` | Chart title |
| `title_x` | `0.5` | Horizontal position (0–1, 0.5 = center) |
| `xaxis_title` | | X-axis label |
| `yaxis_title` | | Y-axis label |
| `template` | `"plotly_white"` | `plotly_white`, `plotly_dark`, `ggplot2`, `seaborn`, `simple_white` |
| `font_family` | `"system-ui, ..."` | CSS font-family for chart text |
| `font_size` | `12` | Base font size |
| `title_font_size` | `18` | Title font size |
| `width` | `800` | Chart width in px (200–1920) |
| `height` | `500` | Chart height in px (200–1080) |
| `show_legend` | `true` | Show legend |
| `legend_position` | `"right"` | `top`, `bottom`, `left`, `right` |

### Embedding charts in layouts

Use `content_type: "chart"` with a `chart_spec` in `AddContentRequest` or
`ZoneContentSpec` (inside `/layout/build`).

**`/layout/build` example — line chart in a report:**

```json
POST /layout/build  {
  "orientation": "portrait",
  "template": "minimal",
  "title": "Q3 Sales Report",
  "zones": [
    {"zone": "header", "content_type": "text",
     "content": "# Q3 Sales Report"},
    {"zone": "content", "content_type": "chart",
     "chart_spec": {
       "chart_type": "line",
       "output_format": "png",
       "config": {
         "title": "Monthly Revenue",
         "xaxis_title": "Month",
         "yaxis_title": "$ (thousands)"
       },
       "line_traces": [
         {
           "name": "Revenue",
           "x": ["Jan","Feb","Mar","Apr","May","Jun"],
           "y": [120, 135, 128, 160, 175, 190],
           "line_width": 3,
           "mode": "lines+markers"
         },
         {
           "name": "Costs",
           "x": ["Jan","Feb","Mar","Apr","May","Jun"],
           "y": [90, 95, 100, 105, 110, 120],
           "line_width": 2,
           "mode": "lines"
         }
       ]
     }},
    {"zone": "footer", "content_type": "text",
     "content": "Generated by AI Harness"}
  ],
  "output_path": "reports/q3.html",
  "export_pdf": true,
  "pdf_path": "reports/q3.pdf"
}
```

### Chart type request schemas

#### Line chart — `POST /chart/line`

**`LineChartRequest`**: `traces` (array of `LineTrace`), `config`, `output_format`.

`LineTrace` fields:

| Field | Default | Description |
|-------|---------|-------------|
| `name` | *(required)* | Series name (legend label) |
| `x` | *(required)* | X-axis values (numbers or strings) |
| `y` | *(required)* | Y-axis values (numbers) |
| `color` | | Override line color (hex) |
| `line_width` | `3` | Line thickness (1–10) |
| `mode` | `"lines+markers"` | `"lines"`, `"markers"`, `"lines+markers"` |
| `fill` | | `"tozeroy"` or `"tonexty"` |

#### Bar chart — `POST /chart/bar`

**`BarChartRequest`**: `traces` (array of `BarTrace`), `barmode`, `orientation`, `config`, `output_format`.

`BarTrace` fields:

| Field | Default | Description |
|-------|---------|-------------|
| `name` | *(required)* | Series name |
| `x` | *(required)* | X-axis categories |
| `y` | *(required)* | Y-axis values |
| `color` | | Override bar color (hex) |
| `text` | | Optional value labels on bars |

`barmode`: `"group"`, `"stack"`, `"relative"`.  `orientation`: `"v"` (vertical), `"h"` (horizontal).

#### Pie chart — `POST /chart/pie`

**`PieChartRequest`**: `labels`, `values`, plus optional `colors`, `text_info`, `hole`, `pull`, `config`, `output_format`.

| Field | Default | Description |
|-------|---------|-------------|
| `labels` | *(required)* | Slice labels |
| `values` | *(required)* | Slice values |
| `colors` | | Per-slice color overrides (hex array) |
| `text_info` | `"percent"` | `"label"`, `"value"`, `"percent"`, `"label+percent"`, `"label+value"`, `"none"` |
| `hole` | `0.0` | 0 = pie, 0.4 = donut, up to 0.9 |
| `pull` | `0.05` | Explore offset |

### `ChartZoneSpec` (for layout integration)

When using `content_type: "chart"` inside a layout zone spec, wrap the chart
data in a `chart_spec` object. It uses a unified shape with the same fields
as above plus a `chart_type` discriminator:

```json
{
  "chart_type": "pie",
  "output_format": "png",
  "config": { "title": "Market Share", "width": 600, "height": 500 },
  "pie_labels": ["Alpha", "Beta", "Gamma", "Others"],
  "pie_values": [35, 25, 20, 20],
  "pie_hole": 0.4,
  "pie_text_info": "label+percent"
}
```

For line charts inside zones, use `line_traces`; for bar charts, use `bar_traces`.

### Chart response (`ChartResponse`)

```json
{
  "chart_id": "a1b2c3d4e5f6",
  "output_format": "png",
  "url": "http://thor.local:8090/media/files/charts/chart-a1b2c3d4e5f6.png",
  "filename": "chart-a1b2c3d4e5f6.png",
  "bytes_written": 45678,
  "width": 800,
  "height": 500
}
```

For `output_format: "html_fragment"`, the response includes `html_fragment` instead
of `url`/`filename`/`bytes_written`.

---

## Future Development

| Feature | Status |
|---------|--------|
| `/layout/merge-pdfs` — merge multiple page PDFs | Planned |
| Slide transitions + keyboard navigation | Planned |
| Base64 image embedding for fully portable HTML | Planned |
| Auto-generated TOC / cover pages | Planned |
| Theme presets (`theme: "dark"`, etc.) | Planned |
| `Inline SVG charts (bar, pie, line)` | ✅ Shipped |
| Video embedding from media module | Planned |
| Strict zone validation mode | Planned |
| Content length guards for slide templates | Planned |
