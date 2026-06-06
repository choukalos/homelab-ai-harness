#!/usr/bin/env python3
"""
Service-layer smoke test for the charts module.

Validates:
  1. Line, bar, and pie chart generation via Plotly
  2. PNG and SVG saving to disk
  3. HTML fragment generation
  4. Unified chart routing (AnyChartRequest path)

Run from ai-harness root:
  python3 tests/test_charts.py
"""
import os
import sys
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
from charts.service import (
    _chart_id,
    _cfg,
    _layout_kwargs,
    _save_chart,
    _html_fragment,
    create_chart,
    create_line_chart,
    create_bar_chart,
    create_pie_chart,
    chart_from_zone_spec,
)
from charts.schemas import ChartConfig

import plotly.graph_objects as go


# ---------- helpers ----------

FAILED = 0
PASSED = 0
MEDIA_DIR = Path(os.getenv("MEDIA_OUTPUT_DIR", "/data/media"))

BLUE = "\033[34m"
GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    global PASSED
    PASSED += 1
    print(f"  {GREEN}●{RESET} {msg}")


def fail(msg: str) -> None:
    global FAILED
    FAILED += 1
    print(f"  {RED}✗{RESET} {msg}")


def section(msg: str) -> None:
    print(f"\n{BLUE}▸ {msg}{RESET}")


# ---------- setup ----------

print(f"\n{'='*60}")
print(f"  Chart Module Smoke Test (service layer)")
print(f"{'='*60}\n")

charts_dir = MEDIA_DIR / "charts"
if charts_dir.exists():
    shutil.rmtree(charts_dir)
charts_dir.mkdir(parents=True, exist_ok=True)

# ---------- _chart_id ----------

section("Helpers")

cid = _chart_id()
if len(cid) == 12:
    ok(f"_chart_id returns 12-char hex: {cid}")
else:
    fail(f"_chart_id wrong length: {len(cid)}")

# ---------- _cfg ----------

cfg_default = _cfg(None)
if isinstance(cfg_default, ChartConfig):
    ok("_cfg(None) → ChartConfig with defaults")
else:
    fail("_cfg(None) didn't return ChartConfig")

cfg_override = _cfg(ChartConfig(title="Custom"))
if cfg_override.title == "Custom":
    ok("_cfg with override preserves custom title")
else:
    fail("_cfg override not preserved")

# ---------- _layout_kwargs ----------

lk = _layout_kwargs(ChartConfig(title="Test", width=800, height=480))
assert isinstance(lk, dict), "_layout_kwargs should return dict"
if lk["width"] == 800 and lk["height"] == 480:
    ok("_layout_kwargs returns correct dict for update_layout(**)")
else:
    fail(f"_layout_kwargs keys mismatch: width={lk.get('width')}, height={lk.get('height')}")

# Test that the layout dict keys work with Plotly update_layout
fig = go.Figure()
fig.add_trace(go.Scatter(x=[1,2], y=[1,2]))
fig.update_layout(**lk)
if fig is not None:
    ok("Layout dict works with fig.update_layout(**)")

# ---------- line chart (PNG) ----------

section("Line chart → PNG")

req = LineChartRequest(
    config=ChartConfig(
        title="Revenue Trend",
        title_x=0.5,
        xaxis_title="Month",
        yaxis_title="USD ($k)",
        template="plotly_white",
        width=800,
        height=500,
    ),
    traces=[
        LineTrace(
            name="Revenue",
            x=["Jan", "Feb", "Mar", "Apr", "May"],
            y=[120, 135, 128, 160, 175],
            color="#3b82f6",
            line_width=3,
            mode="lines+markers",
        ),
        LineTrace(
            name="Cost",
            x=["Jan", "Feb", "Mar", "Apr", "May"],
            y=[80, 85, 90, 105, 110],
            color="#ef4444",
            line_width=2,
            mode="lines",
        ),
    ],
    output_format="png",
)

try:
    result = create_line_chart(req)
    assert result["output_format"] == "png"
    assert result["bytes_written"] > 5_000
    assert result["url"] is not None
    filepath = charts_dir / result["filename"]
    if filepath.exists() and filepath.stat().st_size > 5_000:
        ok(f"Line chart PNG saved: {result['filename']} ({result['bytes_written']} bytes)")
    else:
        fail(f"PNG not on disk or too small")
except Exception as e:
    fail(f"create_line_chart failed: {e}")

# ---------- line chart (HTML fragment) ----------

section("Line chart → HTML fragment")

req_html = LineChartRequest(
    config=ChartConfig(title="Interactive", width=600, height=400),
    traces=[LineTrace(
        name="Series A",
        x=[1, 2, 3, 4],
        y=[10, 15, 13, 20],
        mode="lines+markers",
    )],
    output_format="html_fragment",
)

try:
    result = create_line_chart(req_html)
    if result["html_fragment"] and "<div" in result["html_fragment"] and "plotly" in result["html_fragment"].lower():
        ok(f"Line chart HTML fragment ({len(result['html_fragment'])} chars)")
    else:
        fail("html_fragment missing or invalid")
except Exception as e:
    fail(f"create_line_chart html_fragment failed: {e}")

# ---------- bar chart (PNG, stacked) ----------

section("Bar chart → PNG (stacked)")

req_bar = BarChartRequest(
    config=ChartConfig(title="Quarterly Comparison", width=800, height=480),
    traces=[
        BarTrace(name="Product A", x=["Q1", "Q2", "Q3", "Q4"], y=[45, 60, 55, 70]),
        BarTrace(name="Product B", x=["Q1", "Q2", "Q3", "Q4"], y=[30, 40, 50, 45], color="#f59e0b"),
    ],
    barmode="stack",
    orientation="v",
    output_format="png",
)

try:
    result = create_bar_chart(req_bar)
    filepath = charts_dir / result["filename"]
    if filepath.exists() and filepath.stat().st_size > 5_000:
        ok(f"Bar chart (stacked): {result['filename']} ({result['bytes_written']} bytes)")
    else:
        fail("Bar chart file missing or too small")
except Exception as e:
    fail(f"create_bar_chart failed: {e}")

# ---------- pie chart (SVG, donut) ----------

section("Pie chart → SVG (donut)")

req_pie = PieChartRequest(
    config=ChartConfig(title="Market Share", width=600, height=500),
    labels=["Alpha", "Beta", "Gamma", "Others"],
    values=[35, 25, 20, 20],
    colors=["#3b82f6", "#10b981", "#f59e0b", "#6b7280"],
    hole=0.45,
    pull=0.05,
    text_info="label+percent",
    output_format="svg",
)

try:
    result = create_pie_chart(req_pie)
    filepath = charts_dir / result["filename"]
    if filepath.exists() and filepath.stat().st_size > 500:
        with open(filepath) as f:
            content = f.read()
        if content.strip().startswith("<svg"):
            ok(f"Pie chart SVG (donut): {result['filename']} ({result['bytes_written']} bytes)")
        else:
            fail("SVG file does not start with <svg>")
    else:
        fail("SVG file missing or too small")
except Exception as e:
    fail(f"create_pie_chart failed: {e}")

# ---------- unified /chart/any routing ----------

section("Unified create_chart routing")

for ctype, payload in [
    ("line", AnyChartRequest(
        chart_type="line",
        output_format="png",
        line_traces=[LineTrace(name="Test", x=[1,2,3], y=[5,3,7])],
    )),
    ("bar", AnyChartRequest(
        chart_type="bar",
        output_format="png",
        bar_traces=[BarTrace(name="Test", x=["A","B"], y=[10,20])],
    )),
    ("pie", AnyChartRequest(
        chart_type="pie",
        output_format="png",
        pie_labels=["X", "Y"],
        pie_values=[60, 40],
        pie_hole=0.2,
    )),
]:
    try:
        result = create_chart(payload)
        filepath = charts_dir / result["filename"]
        if filepath.exists():
            ok(f"create_chart '{ctype}' routing → {result['filename']}")
        else:
            fail(f"create_chart '{ctype}' file missing")
    except Exception as e:
        fail(f"create_chart '{ctype}' failed: {e}")

# ---------- chart_from_zone_spec (layout integration) ----------

section("chart_from_zone_spec (layout integration path)")

try:
    spec = ChartZoneSpec(
        chart_type="bar",
        output_format="png",
        config=ChartConfig(title="Layout Chart", width=700, height=400, xaxis_title="Category", yaxis_title="Value"),
        bar_traces=[BarTrace(name="Values", x=["Cat A", "Cat B", "Cat C", "Cat D"], y=[25, 40, 35, 50])],
        barmode="group",
    )
    result = chart_from_zone_spec(spec)
    filepath = charts_dir / result["filename"]
    if filepath.exists() and filepath.stat().st_size > 5_000:
        ok(f"chart_from_zone_spec: {result['filename']} ({result['bytes_written']} bytes)")
    else:
        fail("chart_from_zone_spec file missing or too small")
except Exception as e:
    fail(f"chart_from_zone_spec failed: {e}")

# ---------- chart_from_zone_spec HTML fragment ----------

try:
    spec_html = ChartZoneSpec(
        chart_type="pie",
        output_format="html_fragment",
        config=ChartConfig(title="Zone Pie", width=400, height=400),
        pie_labels=["A", "B", "C"],
        pie_values=[50, 30, 20],
        pie_hole=0.3,
        pie_text_info="percent",
    )
    result = chart_from_zone_spec(spec_html)
    if result.get("html_fragment") and "<div" in result["html_fragment"]:
        ok(f"chart_from_zone_spec html_fragment ({len(result['html_fragment'])} chars)")
    else:
        fail("chart_from_zone_spec html_fragment missing or invalid")
except Exception as e:
    fail(f"chart_from_zone_spec html_fragment failed: {e}")

# ---------- file listing ----------

section("Generated files")
chart_files = sorted(charts_dir.glob("chart-*.*"))
if len(chart_files) >= 5:
    for cf in chart_files:
        print(f"  {BLUE}  {cf.name}  {cf.stat().st_size // 1024} KB{RESET}")
    ok(f"Total: {len(chart_files)} chart files generated")
else:
    fail(f"Too few chart files: {len(chart_files)}")

# ---------- summary ----------

print(f"\n{'='*60}")
total = PASSED + FAILED
if FAILED:
    print(f"  Results: {GREEN}{PASSED}/{total} passed{RESET}  {RED}{FAILED} failed{RESET}")
else:
    print(f"  Results: {GREEN}{PASSED}/{total} passed (all OK){RESET}")
print(f"{'='*60}\n")

sys.exit(0 if FAILED == 0 else 1)
