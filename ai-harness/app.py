from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.config import MEDIA_OUTPUT_DIR
from web_search.router import router as web_search_router
from family_kb.router import router as family_kb_router
from media.router import router as media_router
from pm_demo.router import router as pm_demo_router
from siri.router import router as siri_router

app = FastAPI(title="AI Harness")

app.include_router(web_search_router, prefix="/web", tags=["web"])
app.include_router(family_kb_router, prefix="/kb", tags=["family-kb"])
app.include_router(media_router, prefix="/media", tags=["media"])
app.include_router(pm_demo_router, prefix="/pm", tags=["pm-demo"])
app.include_router(siri_router, prefix="/siri", tags=["siri"])

app.mount("/media/files", StaticFiles(directory=MEDIA_OUTPUT_DIR), name="media-files")

@app.get("/health")
def health():
    return {"status": "ok"}






