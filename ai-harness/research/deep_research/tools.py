"""Research tools for the deep-research agent.

Adapted from langchain-ai/deepagents/examples/deep_research/research_agent/tools.py
Uses SearXNG + Crawl4AI (already in your harness) instead of Tavily.
"""

import httpx
from langchain_core.tools import tool


def _search_and_crawl_impl(
    query: str,
    max_results: int = 3,
    category: str = "general",
    crawl_top_n: int = 2,
) -> str:
    """Internal implementation of search_and_crawl, callable directly."""
    from infra.core.config import SEARXNG_BASE_URL, CRAWL4AI_BASE_URL

    parts: list[str] = []

    # Step 1: Search via SearXNG
    try:
        params = {
            "q": query,
            "format": "json",
            "categories": category,
            "language": "en",
            "pageno": 1,
            "safesearch": 1,
        }
        r = httpx.get(f"{SEARXNG_BASE_URL}/search", params=params, timeout=15.0)
        r.raise_for_status()
        results = r.json().get("results", [])[:max_results]
    except Exception as e:
        return f"Search failed: {e}"

    if not results:
        return f"No results found for '{query}'."

    # Step 2: Crawl top N results for full content
    crawled = 0
    for item in results:
        url = item.get("url", "")
        title = item.get("title", "Untitled")
        snippet = item.get("content", "")[:500]

        if crawled < crawl_top_n and url:
            # Attempt full crawl via Crawl4AI
            full_content = _crawl_url(url)
        else:
            full_content = None

        result_text = f"## {title}\n**URL:** {url}\n\n"
        if full_content:
            # Truncate to avoid excessive token usage per result (~8000 chars)
            content = full_content[:8000]
            result_text += f"### Snippet\n{snippet}\n\n### Full Content\n{content}\n"
        else:
            result_text += f"{snippet}\n"
        result_text += "\n---\n"
        parts.append(result_text)

        if full_content:
            crawled += 1

    return (
        f"Found {len(parts)} result(s) for '{query}':\n\n"
        + "\n".join(parts)
    )


@tool
def search_and_crawl(
    query: str,
    max_results: int = 3,
    category: str = "general",
    crawl_top_n: int = 2,
) -> str:
    """Search the web for information and fetch full page content.

    Searches via SearXNG to discover relevant URLs, then fetches full webpage
    content via Crawl4AI as clean markdown. Use this to gather detailed
    information on any topic.

    Args:
        query: Search query to execute
        max_results: Maximum number of search results to discover (default: 3)
        category: Search category — 'general', 'news', 'images', 'video', 'music' (default: 'general')
        crawl_top_n: Number of top results to crawl for full content (default: 2)

    Returns:
        Formatted search results with full webpage content for top results.
    """
    return _search_and_crawl_impl(query, max_results, category, crawl_top_n)


def _crawl_url(url: str) -> str | None:
    """Fetch full page content via Crawl4AI, returning markdown or None on failure."""
    from infra.core.config import CRAWL4AI_BASE_URL

    try:
        r = httpx.post(
            f"{CRAWL4AI_BASE_URL}/crawl",
            json={
                "urls": [url],
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
        # Crawl4AI returns markdown in the response — extract it
        # The response structure varies; try common paths
        if isinstance(data, dict):
            # Try to get markdown from the response
            md = data.get("markdown", data.get("content", data.get("result", "")))
            if md:
                return str(md)
        # Fallback: return raw JSON as string
        return str(data)[:10000]
    except Exception:
        return None


@tool
def think_tool(reflection: str) -> str:
    """Tool for strategic reflection on research progress and decision-making.

    Use this tool after each search to analyze results and plan next steps
    systematically. This creates a deliberate pause in the research workflow
    for quality decision-making.

    When to use:
    - After receiving search results: What key information did I find?
    - Before deciding next steps: Do I have enough to answer comprehensively?
    - When assessing research gaps: What specific information am I still missing?
    - Before concluding research: Can I provide a complete answer now?

    Reflection should address:
    1. Analysis of current findings — What concrete information have I gathered?
    2. Gap assessment — What crucial information is still missing?
    3. Quality evaluation — Do I have sufficient evidence/examples for a good answer?
    4. Strategic decision — Should I continue searching or provide my answer?

    Args:
        reflection: Your detailed reflection on research progress, findings, gaps, and next steps

    Returns:
        Confirmation that reflection was recorded for decision-making.
    """
    return f"Reflection recorded: {reflection}"
