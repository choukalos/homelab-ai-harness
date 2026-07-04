#!/usr/bin/env python3
"""MCP Search Server — SearXNG-backed web search.

Provides three tools:
  - search_web(query, max_results)     General web search
  - search_recent(query, days, max_results)  Recent search (past N days)
  - search_news(query, max_results)   News-specific search

Backend: SearXNG at configurable SEARXNG_URL (default: http://searxng:8080)
Transport: stdio
"""

import os
import re
import logging
from typing import Optional

import httpx
from mcp.server import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SEARXNG_URL: str = os.environ.get("SEARXNG_URL", "http://searxng:8080")
HTTP_TIMEOUT: float = float(os.environ.get("SEARXNG_TIMEOUT", "10"))
MAX_RESULTS_CAP: int = 20
SNIPPET_MAX_CHARS: int = 200

logger = logging.getLogger("mcp_search")

# ---------------------------------------------------------------------------
# SearXNG client helpers
# ---------------------------------------------------------------------------

def _clean_html(text: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    return text.strip()


def _truncate_snippet(text: str, max_chars: int = SNIPPET_MAX_CHARS) -> str:
    """Truncate text to max_chars, ending at a word boundary."""
    text = _clean_html(text)
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.5:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "…"


def _format_result(item: dict) -> dict:
    """Format a single SearXNG result into a compact dict."""
    return {
        "title": item.get("title", "").strip()[:200],
        "url": item.get("url", "").strip(),
        "snippet": _truncate_snippet(item.get("content", "")),
    }


async def _searxng_search(
    query: str,
    categories: str = "general",
    time_range: Optional[str] = None,
    max_results: int = 5,
) -> list[dict]:
    """Query SearXNG and return compact results."""
    max_results = min(max(1, max_results), MAX_RESULTS_CAP)

    url = f"{SEARXNG_URL}/search"
    params: dict[str, str] = {
        "q": query,
        "format": "json",
        "categories": categories,
        "language": "en",
    }
    if time_range:
        params["time_range"] = time_range

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.error("SearXNG request failed: %s", exc)
        raise RuntimeError(f"SearXNG request failed: {exc}") from exc

    results = data.get("results", [])
    formatted = [_format_result(r) for r in results[:max_results]]
    return formatted


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="mcp_search",
    host="0.0.0.0",
    instructions="Read-only web search via SearXNG. "
    "Results include title, URL, and a truncated snippet.",
)


@mcp.tool(
    name="search_web",
    description="Search the web for results matching the given query.",
)
async def search_web(query: str, max_results: int = 5) -> list[dict]:
    """General web search.

    Args:
        query: The search query string.
        max_results: Maximum number of results (default 5, cap 20).
    """
    return await _searxng_search(query, categories="general", max_results=max_results)


@mcp.tool(
    name="search_recent",
    description="Search for recently published results within the last N days.",
)
async def search_recent(query: str, days: int = 7, max_results: int = 5) -> list[dict]:
    """Recent search limited to the past N days.

    Args:
        query: The search query string.
        days: Number of days to look back (default 7).
        max_results: Maximum number of results (default 5, cap 20).
    """
    # Map days to SearXNG time_range values
    if days <= 1:
        time_range = "day"
    elif days <= 7:
        time_range = "week"
    elif days <= 31:
        time_range = "month"
    else:
        time_range = "year"

    return await _searxng_search(
        query, categories="general", time_range=time_range, max_results=max_results
    )


@mcp.tool(
    name="search_news",
    description="Search news sources for results matching the given query.",
)
async def search_news(query: str, max_results: int = 5) -> list[dict]:
    """News-specific search.

    Args:
        query: The search query string.
        max_results: Maximum number of results (default 5, cap 20).
    """
    return await _searxng_search(query, categories="news", max_results=max_results)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP search server over SSE."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_search on %s", SEARXNG_URL)
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
