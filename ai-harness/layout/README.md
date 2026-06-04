# layout — HTML Page / Slide Layout Engine

AI-driven page and presentation layout service for the AI Harness. Create visually
appealing, self-contained HTML documents with multiple layout templates, portrait
(document) or slide (16:9 presentation) orientation, and zone-based content placement.

---

## Quick Summary

| Concept | Detail |
|---------|--------|
| **Purpose** | Let an AI agent compose visually structured HTML pages or presentation slides programmatically |
| **Orientation** | `portrait` (A4-style document) or `slide` (1920×1080, 16:9) |
| **Templates** | 10 built-in: `minimal`, `hero`, `grid`, `split`, `gallery`, `cards`, `timeline`, `magazine`, `pitch`, `blank` |
| **Content types** | `text` (markdown → HTML) or `image` (URL-based) |
| **Storage** | In-memory during container lifecycle; `/layout/save` persists to workspace |
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
POST /layout/save    →  { path: "output/pitch-deck.html" }
```

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

### `GET /layout/active`

List all in-memory layouts.

### `DELETE /layout/{layout_id}`

Discard a layout.

---

## Markdown Support

Text content accepts a **lightweight markdown subset** (no external library — pure Python):

| Syntax | Renders As |
|--------|-----------|
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
# Save the layout
POST /layout/save { "output_path": "output/my-doc.html" }

# Verify with filetools
POST /files/read { "path": "output/my-doc.html" }

# Clean up
POST /files/delete { "path": "output/my-doc.html" }
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

### Multi-page Support

Current design handles single pages. For multi-page documents:
- AI creates multiple layouts (`/layout/create` × N)
- Optionally combine them with a wrapper HTML or generate a table of contents
- Or add a new endpoint: `POST /layout/concat` that merges rendered HTML pages

### Slide Transitions

For presentation-mode slide layouts:
- Could add `<style>` transition CSS between pages
- Add keyboard navigation (←→ keys to flip pages)

### Dynamic Images

Currently images are URL-referenced. Future option:
- Embed images as base64 data URIs for fully portable output
- Require an endpoint that reads the image bytes and inlines them

### PDF Export

- Add `/layout/export-pdf` endpoint using `weasyprint` or similar
- Renders the same HTML through a PDF engine

### Theming

- Pre-built theme presets (dark mode, corporate, playful, etc.)
- Pass `theme: "dark"` instead of individual colors

### Rich Content Types

Beyond text and image:
- `table` — structured data rendering
- `chart` — inline SVG chart generation (bar, pie, line)
- `video` — embed video clips from media module

### Validation Hooks

- Add zone validation (reject adding content to non-existent zones in strict mode)
- Add content length guards for slide templates (keep text scannable)

---

## API Key & Auth

All endpoints require `HARNESS_API_KEY` via either:
- `X-API-Key: <key>` header
- `Authorization: Bearer <key>` header

Same auth as the rest of the AI Harness (`core/security.py`).
