import json

import httpx
from fastapi import HTTPException

from infra.core.config import CRAWL4AI_BASE_URL, SEARXNG_BASE_URL
from infra.core.llm import chat_completion
from research.web_search.schemas import SearchResult, WebSearchRequest


async def search_searxng(
    client: httpx.AsyncClient,
    req: WebSearchRequest,
) -> list[SearchResult]:
    params = {
        "q": req.query,
        "format": "json",
        "categories": req.category,
        "language": req.language,
        "pageno": 1,
        "safesearch": 1,
    }

    if req.time_range:
        params["time_range"] = req.time_range

    try:
        r = await client.get(f"{SEARXNG_BASE_URL}/search", params=params)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "service": "searxng",
                "status_code": e.response.status_code,
                "body": e.response.text[:1000],
            },
        )

    data = r.json()
    output: list[SearchResult] = []

    for item in data.get("results", [])[: req.max_results]:
        url = item.get("url")
        if not url:
            continue

        output.append(
            SearchResult(
                title=item.get("title"),
                url=url,
                content=item.get("content"),
                engine=item.get("engine"),
                score=item.get("score"),
            )
        )

    return output


async def crawl_url(
    client: httpx.AsyncClient,
    item: SearchResult,
) -> SearchResult:
    try:
        r = await client.post(
            f"{CRAWL4AI_BASE_URL}/crawl",
            json={
                "urls": [item.url],
                "crawler_config": {
                    "type": "CrawlerRunConfig",
                    "params": {
                        "word_count_threshold": 80,
                        "excluded_tags": ["nav", "footer", "aside"],
                    },
                },
            },
            timeout=45.0,
        )
        r.raise_for_status()
        data = r.json()
        item.extracted_markdown = json.dumps(data)[:12000]
        return item

    except Exception as e:
        item.extracted_markdown = f"Crawl failed: {e}"
        return item


async def run_web_search(
    client: httpx.AsyncClient,
    req: WebSearchRequest,
) -> dict:
    results = await search_searxng(client, req)

    crawled: list[SearchResult] = []
    if req.mode != "quick":
        for item in results[: req.crawl_results]:
            crawled.append(await crawl_url(client, item))

    merged = crawled + results[len(crawled):]

    answer = None
    if req.mode == "answer" and req.summarize:
        answer = await synthesize_answer(client, req.query, merged)

    return {
        "query": req.query,
        "mode": req.mode,
        "answer": answer,
        "results": [r.model_dump() for r in merged[: req.max_results]],
    }


async def synthesize_answer(
    client: httpx.AsyncClient,
    query: str,
    results: list[SearchResult],
) -> str:
    source_text = "\n\n".join(
        f"[{i + 1}] {r.title}\nURL: {r.url}\nSnippet: {r.content}\nExtracted: {r.extracted_markdown}"
        for i, r in enumerate(results)
    )

    prompt = f"""
Answer the user's question using only the sources below.

Rules:
- Be concise.
- Cite sources inline as [1], [2], etc.
- If sources are weak or conflicting, say so.
- Do not invent facts.

Question:
{query}

Sources:
{source_text}
""".strip()

    return await chat_completion(client, prompt)


def dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen = set()
    unique = []

    for r in results:
        if r.url in seen:
            continue
        seen.add(r.url)
        unique.append(r)

    return unique


async def generate_research_queries(
    client: httpx.AsyncClient,
    topic: str,
    max_queries: int,
) -> list[str]:
    prompt = f"""
Generate {max_queries} focused web search queries for this research topic.

Topic:
{topic}

Return only JSON:
["query 1", "query 2"]
""".strip()

    text = await chat_completion(client, prompt)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(q) for q in parsed[:max_queries]]
    except Exception:
        pass

    return [topic]


async def run_research_brief(
    client: httpx.AsyncClient,
    topic: str,
    max_queries: int,
    results_per_query: int,
) -> dict:
    queries = await generate_research_queries(client, topic, max_queries)

    all_results: list[SearchResult] = []

    for q in queries:
        search_req = WebSearchRequest(
            query=q,
            max_results=results_per_query,
            crawl_results=0,
            summarize=False,
            mode="sources",
        )
        results = await search_searxng(client, search_req)
        all_results.extend(results)

    unique = dedupe_results(all_results)
    brief = await synthesize_research_brief(client, topic, unique)

    return {
        "topic": topic,
        "queries": queries,
        "brief": brief,
        "sources": [r.model_dump() for r in unique[:20]],
    }


async def synthesize_research_brief(
    client: httpx.AsyncClient,
    topic: str,
    results: list[SearchResult],
) -> str:
    source_text = "\n\n".join(
        f"[{i + 1}] {r.title}\nURL: {r.url}\nSnippet: {r.content}"
        for i, r in enumerate(results[:20])
    )

    prompt = f"""
Create a concise research brief using only these sources.

Topic:
{topic}

Include:
- Executive summary
- Key findings
- Risks / uncertainty
- Recommended next steps
- Source citations like [1], [2]

Sources:
{source_text}
""".strip()

    return await chat_completion(client, prompt)


