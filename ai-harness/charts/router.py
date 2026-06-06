"""FastAPI router for chart endpoints."""

from fastapi import APIRouter, Depends

from core.security import require_harness_auth
from charts.schemas import (
    AnyChartRequest,
    BarChartRequest,
    ChartResponse,
    LineChartRequest,
    PieChartRequest,
)
from charts.service import (
    create_bar_chart,
    create_chart,
    create_line_chart,
    create_pie_chart,
)

router = APIRouter(tags=["charts"])


@router.post("/line", response_model=ChartResponse)
def line_chart(
    req: LineChartRequest,
    _: None = Depends(require_harness_auth),
):
    """Generate a line chart with one or more data series."""
    return create_line_chart(req)


@router.post("/bar", response_model=ChartResponse)
def bar_chart(
    req: BarChartRequest,
    _: None = Depends(require_harness_auth),
):
    """Generate a bar chart (vertical or horizontal, grouped or stacked)."""
    return create_bar_chart(req)


@router.post("/pie", response_model=ChartResponse)
def pie_chart(
    req: PieChartRequest,
    _: None = Depends(require_harness_auth),
):
    """Generate a pie or donut chart."""
    return create_pie_chart(req)


@router.post("/any", response_model=ChartResponse)
def any_chart(
    req: AnyChartRequest,
    _: None = Depends(require_harness_auth),
):
    """
    Unified chart endpoint — specify chart_type and matching data fields.
    Routes to line, bar, or pie internally.
    """
    return create_chart(req)
