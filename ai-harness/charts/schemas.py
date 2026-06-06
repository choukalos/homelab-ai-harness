"""Pydantic schemas for chart generation."""

from pydantic import BaseModel, Field
from typing import Optional, Literal


# ---------- Chart configuration ----------

class ChartConfig(BaseModel):
    """Visual style configuration for a chart."""

    title: str = Field(default="", description="Chart title.")
    title_x: Optional[float] = Field(
        default=None,
        description="Horizontal position of title (0–1). Default centers it.",
    )
    xaxis_title: Optional[str] = Field(default=None, description="X-axis label.")
    yaxis_title: Optional[str] = Field(default=None, description="Y-axis label.")
    template: Literal["plotly_white", "plotly_dark", "ggplot2", "seaborn", "simple_white"] = Field(
        default="plotly_white",
        description="Plotly template/theme.",
    )
    font_family: str = Field(
        default="system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
        description="CSS font-family for chart text.",
    )
    font_size: int = Field(default=12, ge=8, le=24, description="Base font size.")
    title_font_size: int = Field(default=18, ge=10, le=36, description="Title font size.")
    width: int = Field(default=800, ge=200, le=1920, description="Chart width in pixels.")
    height: int = Field(default=500, ge=200, le=1080, description="Chart height in pixels.")
    margin_top: int = Field(default=50, ge=0, le=120, description="Top margin in pixels.")
    margin_bottom: int = Field(default=50, ge=0, le=120, description="Bottom margin in pixels.")
    margin_left: int = Field(default=60, ge=0, le=150, description="Left margin in pixels.")
    margin_right: int = Field(default=30, ge=0, le=100, description="Right margin in pixels.")
    show_legend: bool = Field(default=True, description="Show legend.")
    legend_position: Literal["top", "bottom", "left", "right"] = Field(
        default="right",
        description="Legend placement.",
    )
    paper_bgcolor: str = Field(
        default="rgba(255,255,255,0)",
        description="Paper (outer area) background. Use rgba with alpha=0 for transparent.",
    )
    plot_bgcolor: str = Field(
        default="rgba(255,255,255,1)",
        description="Plot area background color.",
    )


class ColorPalette(BaseModel):
    """Named color palette lookup — avoids hard-coding hex codes in traces."""

    palette: Literal[
        "default",
        "pastel",
        "vivid",
        "diverging",
        "sequential",
    ] = Field(default="default", description="Built-in Plotly color cycle.")


# ---------- Line chart ----------

class LineTrace(BaseModel):
    """A single data series for a line chart."""

    name: str = Field(description="Series name (legend label).")
    x: list = Field(description="X-axis values (numbers or strings/dates).")
    y: list = Field(description="Y-axis values (numbers).")
    color: Optional[str] = Field(default=None, description="Override line color (hex).")
    line_width: int = Field(default=3, ge=1, le=10, description="Line width in px.")
    mode: Literal["lines", "markers", "lines+markers"] = Field(
        default="lines+markers",
        description="Line mode.",
    )
    fill: Optional[Literal["tozeroy", "tonexty"]] = Field(
        default=None,
        description="Fill area under line.",
    )


class LineChartRequest(BaseModel):
    """Request to generate a line chart."""

    config: Optional[ChartConfig] = Field(
        default=None,
        description="Chart style overrides.",
    )
    traces: list[LineTrace] = Field(description="Data series.")
    output_format: Literal["png", "svg", "html_fragment"] = Field(
        default="png",
        description="png = static image saved to media dir; svg = vector saved to media dir; html_fragment = interactive HTML snippet (no save).",
    )


# ---------- Bar chart ----------

class BarTrace(BaseModel):
    """A single series for a bar chart."""

    name: str = Field(description="Series name (legend label).")
    x: list = Field(description="X-axis categories.")
    y: list = Field(description="Y-axis values.")
    color: Optional[str] = Field(default=None, description="Override bar color (hex).")
    text: Optional[list[str]] = Field(
        default=None,
        description="Optional text labels on bars.",
    )


class BarChartRequest(BaseModel):
    """Request to generate a bar chart."""

    config: Optional[ChartConfig] = Field(default=None, description="Chart style overrides.")
    traces: list[BarTrace] = Field(description="Data series.")
    barmode: Literal["group", "stack", "relative"] = Field(
        default="group",
        description="Bar layout mode.",
    )
    orientation: Literal["v", "h"] = Field(
        default="v",
        description="v=vertical bars, h=horizontal bars.",
    )
    output_format: Literal["png", "svg", "html_fragment"] = Field(
        default="png",
        description="Output format.",
    )


# ---------- Pie chart ----------

class PieChartRequest(BaseModel):
    """Request to generate a pie (or donut) chart."""

    labels: list[str] = Field(description="Slice labels.")
    values: list[float] = Field(description="Slice values.")
    colors: Optional[list[str]] = Field(
        default=None,
        description="Override per-slice colors (hex). Must match labels length.",
    )
    text_info: Literal["label", "value", "percent", "label+percent", "label+value", "none"] = Field(
        default="percent",
        description="What info to show on each slice.",
    )
    hole: float = Field(
        default=0.0,
        ge=0.0,
        le=0.9,
        description="Hole ratio. 0=pie, >0 = donut.",
    )
    pull: float = Field(
        default=0.05,
        ge=0.0,
        le=0.25,
        description="Explode offset.",
    )
    config: Optional[ChartConfig] = Field(default=None, description="Chart style overrides.")
    output_format: Literal["png", "svg", "html_fragment"] = Field(
        default="png",
        description="Output format.",
    )


# ---------- Unified chart request (any type) ----------

class AnyChartRequest(BaseModel):
    """
    Unified chart request — pick a chart type and supply the matching data.
    Useful when the AI agent does not know the chart type in advance.
    """

    chart_type: Literal["line", "bar", "pie"] = Field(description="Chart type.")
    config: Optional[ChartConfig] = Field(default=None, description="Chart style overrides.")
    output_format: Literal["png", "svg", "html_fragment"] = Field(default="png")

    # Line chart fields
    line_traces: Optional[list[LineTrace]] = Field(default=None)

    # Bar chart fields
    bar_traces: Optional[list[BarTrace]] = Field(default=None)
    barmode: Optional[Literal["group", "stack", "relative"]] = Field(default="group")
    bar_orientation: Optional[Literal["v", "h"]] = Field(default="v")

    # Pie chart fields
    pie_labels: Optional[list[str]] = Field(default=None)
    pie_values: Optional[list[float]] = Field(default=None)
    pie_colors: Optional[list[str]] = Field(default=None)
    pie_text_info: Optional[Literal["label", "value", "percent", "label+percent", "label+value", "none"]] = Field(
        default="percent",
    )
    pie_hole: Optional[float] = Field(default=0.0)
    pie_pull: Optional[float] = Field(default=0.05)


# ---------- Zone content chart spec (for layout integration) ----------

class ChartZoneSpec(BaseModel):
    """
    Chart specification for use inside a ZoneContentSpec so the layout
    build pipeline can generate charts inline.
    """

    chart_type: Literal["line", "bar", "pie"] = Field(description="Chart type.")
    config: Optional[ChartConfig] = Field(default=None, description="Chart style overrides.")
    output_format: Literal["png", "svg", "html_fragment"] = Field(
        default="png",
        description="Format. png/svg saves to media dir; html_fragment embeds inline HTML.",
    )

    # Line
    line_traces: Optional[list[LineTrace]] = Field(default=None)

    # Bar
    bar_traces: Optional[list[BarTrace]] = Field(default=None)
    barmode: Optional[Literal["group", "stack", "relative"]] = Field(default="group")
    bar_orientation: Optional[Literal["v", "h"]] = Field(default="v")

    # Pie
    pie_labels: Optional[list[str]] = Field(default=None)
    pie_values: Optional[list[float]] = Field(default=None)
    pie_colors: Optional[list[str]] = Field(default=None)
    pie_text_info: Optional[str] = Field(default="percent")
    pie_hole: Optional[float] = Field(default=0.0)
    pie_pull: Optional[float] = Field(default=0.05)


# ---------- Response ----------

class ChartResponse(BaseModel):
    """Response after generating a chart."""

    chart_id: str
    output_format: str
    url: Optional[str] = Field(default=None, description="URL to saved file (png/svg).")
    filename: Optional[str] = Field(default=None, description="Saved filename (png/svg).")
    html_fragment: Optional[str] = Field(
        default=None,
        description="Interactive HTML snippet (only when output_format=html_fragment).",
    )
    width: int = 0
    height: int = 0
    bytes_written: int = 0
