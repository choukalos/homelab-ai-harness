from fastapi import APIRouter, Depends

from core.security import require_auth
from family_kb.config import COLLECTION, KB_RAW, KB_ROOT
from family_kb.nav_gen import regenerate_all
from family_kb.ingest_files import ingest_existing_raw_files
from family_kb.schemas import IngestResponse, NavRegenResponse, SearchRequest
from family_kb.service import ingest_markdown_repo, search_kb

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "ok",
        "collection": COLLECTION,
        "kb_root": str(KB_ROOT),
        "kb_raw": str(KB_RAW),
    }


@router.post("/ingest", response_model=IngestResponse)
def ingest_repo(_: None = Depends(require_auth)):
    return ingest_markdown_repo()


@router.post("/ingest/raw")
def ingest_raw(_: None = Depends(require_auth)):
    return ingest_existing_raw_files()


@router.post("/search")
def search(req: SearchRequest, _: None = Depends(require_auth)):
    return search_kb(req)


@router.post("/ask")
def ask(req: SearchRequest, _: None = Depends(require_auth)):
    return search_kb(req)


@router.post("/regenerate", response_model=NavRegenResponse)
def regenerate_nav(_: None = Depends(require_auth)):
    """Regenerate category index files and mkdocs.yml navigation."""
    return regenerate_all()


