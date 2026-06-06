# Charts — Data Visualization Module

Server-side chart generation using **Plotly + Kaleido**. Produces static images (PNG/SVG) saved to disk, or interactive HTML fragments embedded inline. Integrated with the layout pipeline so charts can appear as zone content in dashboards.

## Module Structure

| File | Purpose |
|------|---------|
| `schemas.py` | Pydantic request/response models (chart configs, trace types, zone spec) |
| `service.py` | Core business logic — Plotly figure construction, rendering, file saving |
| `router.py` | FastAPI endpoints (`POST /chart/line`, `/bar`, `/pie`, `/any`) |

## Architecture

```
HTTP POST /chart/{type}
    │
    ▼
router.py (FastAPI endpoints, auth via require_harness_auth)
    │
    ▼
service.py (create_line_chart / create_bar_chart / create_pie_chart / create_chart)
    │
    ├── go.Figure() → Plotly figure construction
    ├── _layout_kwargs(cfg) → chart styling via ChartConfig
    │
    ├── PNG/SVG:  _save_chart() → fig.to_image() → saved to /data/media/charts/
    └── HTML:     _html_fragment() → pio.to_html(full_html=False) → returned inline
```

## Supported Chart Types

### 1. Line Charts (`POST /chart/line`)

Multiple data series with configurable modes (lines, markers, or both), fill areas, colors, and line widths.

**Request schema:** `LineChartRequest`
- `traces`: list of `LineTrace` — each has `name`, `x`, `y`, optional `color`, `line_width`, `mode`, `fill`

### 2. Bar Charts (`POST /chart/bar`)

Grouped, stacked, or relative bars in vertical or horizontal orientation.

**Request schema:** `BarChartRequest`
- `traces`: list of `BarTrace` — each has `name`, `x`, `y`, optional `color`, `text`
- `barmode`: `"group"` | `"stack"` | `"relative"` (default: `"group"`)
- `orientation`: `"v"` (vertical) | `"h"` (horizontal) (default: `"v"`)

### 3. Pie / Donut Charts (`POST /chart/pie`)

Pie charts with optional donut hole, slice colors, and info display.

**Request schema:** `PieChartRequest`
- `labels`, `values`: required
- `hole`: 0.0–0.9 (0 = full pie, >0 = donut)
- `text_info`: `"label"` | `"value"` | `"percent"` | `"label+percent"` | `"label+value"` | `"none"`
- `colors`: optional per-slice color override

### 4. Unified Endpoint (`POST /chart/any`)

Accepts `AnyChartRequest` with `chart_type` field that routes internally to line/bar/pie. Fields are flat (all chart-type data is optional at top level). This is the easiest endpoint to call when chart type is determined dynamically (e.g., by an AI agent).

## Chart Configuration (`ChartConfig`)

Every chart type accepts an optional `config` field of type `ChartConfig` for styling:

| Field | Default | Description |
|-------|---------|-------------|
| `title` | `""` | Chart title |
| `title_x` | `None` | Title horizontal position (0–1). `None` = centered |
| `xaxis_title` / `yaxis_title` | `None` | Axis labels |
| `template` | `"plotly_white"` | Theme: `plotly_white`, `plotly_dark`, `ggplot2`, `seaborn`, `simple_white` |
| `font_family` | system-ui stack | Font family for all chart text |
| `font_size` | 12 (8–24) | Base font size |
| `title_font_size` | 18 (10–36) | Title font size |
| `width` / `height` | 800 / 500 | Chart dimensions in px |
| `margin_*` | t:50, b:50, l:60, r:30 | Margins in px |
| `show_legend` | `true` | Toggle legend visibility |
| `legend_position` | `"right"` | `"top"` | `"bottom"` | `"left"` | `"right"` |
| `paper_bgcolor` | transparent | Outer area background |
| `plot_bgcolor` | white | Plot area background |

## Output Formats

All chart request schemas support `output_format`:

| Format | Behavior |
|--------|----------|
| `"png"` (default) | Raster image at 2x scale, saved to `/data/media/charts/chart-{id}.png` |
| `"svg"` | Vector image, saved to `/data/media/charts/chart-{id}.svg` |
| `"html_fragment"` | Interactive Plotly HTML embed (includes plotly.js via CDN), returned inline in response — **no file saved** |

Saved files are accessible at `{INTERNAL_BASE_URL}/media/files/charts/{filename}`.

## Response (`ChartResponse`)

| Field | Present When |
|-------|-------------|
| `chart_id` | Always (12-char hex) |
| `output_format` | Always |
| `url` | PNG or SVG (full internal URL to the saved file) |
| `filename` | PNG or SVG |
| `bytes_written` | PNG or SVG |
| `html_fragment` | `"html_fragment"` format (full interactive HTML snippet) |
| `width` / `height` | Always |

## Layout Integration (Zones)

Charts can be embedded inside layout zones via the `ZoneContentSpec` schema. Each zone can declare:

```json
{
  "content_type": "chart",
  "chart_spec": { ... }
}
```

### `ChartZoneSpec` (in `schemas.py`)

A chart-specific zone content spec mirroring `AnyChartRequest` fields. The layout service calls `chart_from_zone_spec()` which converts it to an `AnyChartRequest` and delegates to `create_chart()`.

### How Layout Uses Charts (in `layout/service.py`)

1. Layout build encounters a zone with `content_type == "chart"`
2. Calls `_charts.chart_from_zone_spec(req.chart_spec)`
3. Gets back a `ChartResponse` dict
4. For PNG/SVG: zone content references the chart URL
5. For HTML fragment: zone content embeds the HTML directly

### Example: Zone with a Line Chart

```json
{
  "content_type": "chart",
  "chart_spec": {
    "chart_type": "line",
    "output_format": "html_fragment",
    "config": {
      "title": "System CPU Usage",
      "template": "plotly_dark",
      "width": 600,
      "height": 300
    },
    "line_traces": [
      {
        "name": "Core 0",
        "x": [1, 2, 3, 4, 5],
        "y": [45, 52, 38, 61, 49],
        "mode": "lines"
      },
      {
        "name": "Core 1",
        "x": [1, 2, 3, 4, 5],
        "y": [30, 42, 55, 48, 37],
        "mode": "lines"
      }
    ]
  }
}
```

## Key Implementation Details

- **Chart IDs**: 12-char hex from `uuid.uuid4().hex[:12]`
- **Image rendering**: Uses Kaleido via `fig.to_image(format=..., scale=2)` for 2x resolution PNGs
- **HTML fragments**: Use `pio.to_html(full_html=False, include_plotlyjs="cdn")` — no outer HTML wrapper, loads Plotly.js from CDN
- **Legend positioning**: Right/left = vertical legend outside plot area; top/bottom = horizontal legend outside plot area
- **File storage**: All saved charts go to `{MEDIA_OUTPUT_DIR}/charts/` (created at import time if missing)
- **Auth**: All endpoints require harness auth via `require_harness_auth` dependency
