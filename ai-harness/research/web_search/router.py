import httpx
from fastapi import APIRouter, Depends

from infra.core.cache import cache_key, get_json, set_json
from infra.core.security import require_auth
from research.web_search.schemas import ResearchBriefRequest, WebSearchRequest
from research.web_search.service import run_research_brief, run_web_search

router = APIRouter(tags=["web"])


@router.post("/search")
async def web_search(
    req: WebSearchRequest,
    _: None = Depends(require_auth),
) -> dict:
    key = cache_key("search", req.model_dump())
    cached = get_json(key)
    if cached:
        return cached

    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await run_web_search(client, req)

    set_json(key, response)
    return response


@router.post("/research")
async def research_brief(
    req: ResearchBriefRequest,
    _: None = Depends(require_auth),
) -> dict:
    key = cache_key("research", req.model_dump())
    cached = get_json(key)
    if cached:
        return cached

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await run_research_brief(
            client=client,
            topic=req.topic,
            max_queries=req.max_queries,
            results_per_query=req.results_per_query,
        )

    set_json(key, response, ttl_seconds=3600)
    return response


