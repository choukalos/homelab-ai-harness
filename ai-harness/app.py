from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from deep_research.service import ensure_checkpointer_tables

from core.config import MEDIA_OUTPUT_DIR
from web_search.router import router as web_search_router
from family_kb.router import router as family_kb_router
from media.router import router as media_router
from pm_demo.router import router as pm_demo_router
from siri.router import router as siri_router
from filetools.router import router as filetools_router
from layout.router import router as layout_router
from charts.router import router as charts_router
from tasks.router import router as tasks_router
from scheduler.router import router as scheduler_router
from workflows import register as register_workflows
from deep_research.router import router as deep_research_router
from workflows.router import router as workflows_router
from market_research.router import router as market_research_router
from market_research.tasks import register as register_market_tasks
from presentation.tasks import register as register_presentation_tasks
from demo_workflow.router import router as demo_workflow_router
from presentation.router import router as presentation_router

app = FastAPI(title="AI Harness")

# Ensure workflow DB tables exist on startup
register_workflows(app)

# Ensure Deep Agents MySQL checkpoint tables exist (shared by deep_research + demo_workflow)
@app.on_event("startup")
async def _init_deep_research():
    await ensure_checkpointer_tables()

app.include_router(web_search_router, prefix="/web", tags=["web"])
app.include_router(family_kb_router, prefix="/kb", tags=["family-kb"])
app.include_router(media_router, prefix="/media", tags=["media"])
app.include_router(pm_demo_router, prefix="/pm", tags=["pm-demo"])
app.include_router(siri_router, prefix="/siri", tags=["siri"])
app.include_router(filetools_router, prefix="/files", tags=["filetools"])
app.include_router(layout_router, prefix="/layout", tags=["layout"])
app.include_router(charts_router, prefix="/chart", tags=["charts"])
app.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
app.include_router(scheduler_router, prefix="/schedules", tags=["schedules"])
app.include_router(workflows_router)
app.include_router(market_research_router, prefix="/markets", tags=["market-research"])
app.include_router(demo_workflow_router, prefix="/demos", tags=["demo-workflow"])
app.include_router(deep_research_router, prefix="/workflows/deep-research", tags=["deep-research"])
app.include_router(presentation_router, prefix="/presentation", tags=["presentation"])

# Register Celery tasks for market research, demo workflow, and presentation before first dispatch
register_market_tasks()
register_presentation_tasks()

app.mount("/media/files", StaticFiles(directory=MEDIA_OUTPUT_DIR), name="media-files")

@app.get("/health")
def health():
    return {"status": "ok"}






