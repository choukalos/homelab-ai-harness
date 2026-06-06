"""
Core business logic for chart generation.

Uses Plotly + Kaleido for server-side rendering of line, bar, and pie charts.
Supports three output modes:
  - PNG  (static raster image saved to /data/media/charts/)
  - SVG  (vector image saved to /data/media/charts/)
  - HTML fragment (interactive Plotly embed, returned inline — no file saved)
"""

import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import plotly.graph_objects as go

from core.config import INTERNAL_BASE_URL, MEDIA_OUTPUT_DIR
from charts.schemas import (
    AnyChartRequest,
    BarChartRequest,
    BarTrace,
    ChartConfig,
    ChartZoneSpec,
    LineChartRequest,
    LineTrace,
    PieChartRequest,
)


# ---------- chart output directory -----------------------------------------

_CHARTS_SUBDIR = Path(MEDIA_OUTPUT_DIR) / "charts"
_CHARTS_SUBDIR.mkdir(parents=True, exist_ok=True)


# ---------- helpers --------------------------------------------------------

def _chart_id() -> str:
    return uuid.uuid4().hex[:12]


def _cfg(override: Optional[ChartConfig]) -> ChartConfig:
    """Return the override config or defaults."""
    return override if override is not None else ChartConfig()


def _layout_kwargs(cfg: ChartConfig) -> dict:
    """
    Return a flat dict of keyword arguments suitable for
    ``fig.update_layout(**kwargs)``.
    """
    if cfg.legend_position in ("right", "left"):
        legend = dict(
            orientation="v", yanchor="middle", xanchor="left",
            x=1.02, y=0.5,
        )
    elif cfg.legend_position == "bottom":
        legend = dict(
            orientation="h", yanchor="top", xanchor="center",
            x=0.5, y=-0.15,
        )
    elif cfg.legend_position == "top":
        legend = dict(
            orientation="h", yanchor="bottom", xanchor="center",
            x=0.5, y=1.08,
        )
    else:
        legend = dict(
            orientation="v", yanchor="middle", xanchor="left",
            x=1.02, y=0.5,
        )

    return dict(
        title_text=cfg.title,
        title_x=cfg.title_x if cfg.title_x is not None else 0.5,
        title_xanchor="center" if cfg.title_x is None else "auto",
        title_font=dict(size=cfg.title_font_size, family=cfg.font_family),
        xaxis_title=cfg.xaxis_title,
        yaxis_title=cfg.yaxis_title,
        template=cfg.template,
        font=dict(family=cfg.font_family, size=cfg.font_size),
        width=cfg.width,
        height=cfg.height,
        margin=dict(
            l=cfg.margin_left,
            r=cfg.margin_right,
            t=cfg.margin_top,
            b=cfg.margin_bottom,
        ),
        showlegend=cfg.show_legend,
        legend=legend,
        paper_bgcolor=cfg.paper_bgcolor,
        plot_bgcolor=cfg.plot_bgcolor,
    )


def _save_chart(fig: go.Figure, fmt: str, cid: str) -> tuple[str, str, int]:
    """Render figure to image bytes, save to disk, return (url, filename, size)."""
    ext = "svg" if fmt == "svg" else "png"
    filename = f"chart-{cid}.{ext}"
    dest = _CHARTS_SUBDIR / filename

    img_bytes = fig.to_image(format=fmt, scale=2)
    dest.write_bytes(img_bytes)

    url = f"{INTERNAL_BASE_URL.rstrip('/')}/media/files/charts/{filename}"
    return url, filename, len(img_bytes)


def _html_fragment(fig: go.Figure) -> str:
    """Return an interactive Plotly HTML embed snippet (no outer <html> wrapper)."""
    import plotly.io as pio
    return pio.to_html(
        fig,
        full_html=False,
        include_plotlyjs="cdn",
        config={"displayModeBar": False},
    )


def _wrap(fig: go.Figure, cid: str, output_format: str, cfg: ChartConfig,
          extra_kws: Optional[dict] = None) -> Dict[str, Any]:
    """Generic response builder for a completed figure."""
    if extra_kws:
        fig.update_layout(**extra_kws)

    if output_format == "html_fragment":
        return {
            "chart_id": cid,
            "output_format": output_format,
            "html_fragment": _html_fragment(fig),
            "width": cfg.width,
            "height": cfg.height,
        }

    url, fname, nbytes = _save_chart(fig, output_format, cid)
    return {
        "chart_id": cid,
        "output_format": output_format,
        "url": url,
        "filename": fname,
        "bytes_written": nbytes,
        "width": cfg.width,
        "height": cfg.height,
    }


# ---------- chart generators -----------------------------------------------

def create_line_chart(req: LineChartRequest) -> Dict[str, Any]:
    """Generate a line chart with one or more data series."""
    cfg = _cfg(req.config)
    cid = _chart_id()
    fig = go.Figure()

    for trace in req.traces:
        line_kw = dict(width=trace.line_width)
        if trace.color:
            line_kw["color"] = trace.color
        fig.add_trace(go.Scatter(
            x=trace.x,
            y=trace.y,
            name=trace.name,
            mode=trace.mode,
            line=line_kw,
            fill=trace.fill,
        ))

    fig.update_layout(**_layout_kwargs(cfg))
    return _wrap(fig, cid, req.output_format, cfg)


def create_bar_chart(req: BarChartRequest) -> Dict[str, Any]:
    """Generate a bar chart (vertical or horizontal, grouped or stacked)."""
    cfg = _cfg(req.config)
    cid = _chart_id()
    fig = go.Figure()

    for trace in req.traces:
        fig.add_trace(go.Bar(
            x=trace.x,
            y=trace.y,
            name=trace.name,
            marker_color=trace.color,
            text=trace.text,
        ))

    fig.update_layout(**_layout_kwargs(cfg), barmode=req.barmode)
    return _wrap(fig, cid, req.output_format, cfg)


def create_pie_chart(req: PieChartRequest) -> Dict[str, Any]:
    """Generate a pie (or donut) chart."""
    cfg = _cfg(req.config)
    cid = _chart_id()

    marker_kw: dict = {}
    if req.colors:
        marker_kw["colors"] = req.colors

    fig = go.Figure(data=[go.Pie(
        labels=req.labels,
        values=req.values,
        hole=req.hole,
        pull=req.pull,
        marker=marker_kw,
        textinfo=req.text_info,
    )])

    fig.update_layout(**_layout_kwargs(cfg))
    return _wrap(fig, cid, req.output_format, cfg)


# ---------- unified entry point --------------------------------------------

def create_chart(req: AnyChartRequest) -> Dict[str, Any]:
    """Route to the correct chart type based on chart_type field."""
    if req.chart_type == "line":
        if not req.line_traces:
            raise ValueError("line_traces is required for line charts")
        return create_line_chart(
            LineChartRequest(
                config=req.config,
                traces=req.line_traces,
                output_format=req.output_format,
            )
        )
    elif req.chart_type == "bar":
        if not req.bar_traces:
            raise ValueError("bar_traces is required for bar charts")
        return create_bar_chart(
            BarChartRequest(
                config=req.config,
                traces=req.bar_traces,
                barmode=req.barmode or "group",
                orientation=req.bar_orientation or "v",
                output_format=req.output_format,
            )
        )
    elif req.chart_type == "pie":
        if not req.pie_labels or not req.pie_values:
            raise ValueError("pie_labels and pie_values are required for pie charts")
        return create_pie_chart(
            PieChartRequest(
                labels=req.pie_labels,
                values=req.pie_values,
                colors=req.pie_colors,
                text_info=req.pie_text_info or "percent",
                hole=req.pie_hole if req.pie_hole is not None else 0.0,
                pull=req.pie_pull if req.pie_pull is not None else 0.05,
                config=req.config,
                output_format=req.output_format,
            )
        )


def chart_from_zone_spec(spec: ChartZoneSpec) -> Dict[str, Any]:
    """
    Entry point from layout zones — generates a chart from a ChartZoneSpec
    and returns the standard response dict.
    """
    any_req = AnyChartRequest(
        chart_type=spec.chart_type,
        config=spec.config,
        output_format=spec.output_format,
        line_traces=spec.line_traces,
        bar_traces=spec.bar_traces,
        barmode=spec.barmode,
        bar_orientation=spec.bar_orientation,
        pie_labels=spec.pie_labels,
        pie_values=spec.pie_values,
        pie_colors=spec.pie_colors,
        pie_text_info=spec.pie_text_info,
        pie_hole=spec.pie_hole,
        pie_pull=spec.pie_pull,
    )
    return create_chart(any_req)
