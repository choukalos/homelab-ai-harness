#!/usr/bin/env python3
"""MCP Crawl Server — Crawl4AI-backed web page extraction.

Provides one tool:
  - crawl_page(url, format?, max_chars?)   Fetch and extract a web page

Backend: Crawl4AI at configurable CRAWL4AI_URL (default: http://crawl4ai:11235)
Transport: SSE (HTTP, default 0.0.0.0:8000)
Security: Internal IP blocking, rate limiting, max content size.
"""

import ipaddress
import logging
import os
import re
from asyncio import Semaphore
from typing import Optional

import httpx
from mcp.server import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CRAWL4AI_URL: str = os.environ.get("CRAWL4AI_URL", "http://crawl4ai:11235")
HTTP_TIMEOUT: float = float(os.environ.get("CRAWL_TIMEOUT", "30"))
MAX_CONCURRENT: int = int(os.environ.get("CRAWL_MAX_CONCURRENT", "10"))
MAX_CHARS: int = int(os.environ.get("CRAWL_MAX_CHARS", "50000"))

logger = logging.getLogger("mcp_crawl")

# ---------------------------------------------------------------------------
# Internal IP blocking
# ---------------------------------------------------------------------------


def _is_internal_ip(url: str) -> bool:
    """Check if the URL resolves to an internal/private IP address.

    Blocks:
    - 192.168.0.0/16 (private class C)
    - 10.0.0.0/8 (private class A)
    - 172.16.0.0/12 (private class B: 172.16.x.x through 172.31.x.x)
    - 127.0.0.0/8 (localhost)
    - ::1 (IPv6 localhost)
    """
    # Extract hostname from URL
    match = re.match(r"https?://([^:/]+)", url)
    if not match:
        # If we can't parse it, block it to be safe
        logger.warning("Could not parse hostname from URL, blocking: %s", url)
        return True

    hostname = match.group(1).lower()

    # Block localhost explicitly (before IP check)
    if hostname in ("localhost", "localhost."):
        return True

    # Check if it's a bare IP address (IPv4 or IPv6)
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        # Not a bare IP — could be a hostname. We don't do DNS resolution here
        # to avoid latency; only block direct IP access.
        return False

    # Block all private and loopback ranges
    if addr.is_private or addr.is_loopback or addr.is_link_local:
        return True

    return False


def _validate_url(url: str) -> None:
    """Validate URL for safety. Raises ValueError if blocked."""
    if not url:
        raise ValueError("URL is required")

    # Must be http or https
    if not re.match(r"https?://", url):
        raise ValueError(f"URL must start with http:// or https://: {url}")

    # Block internal IPs
    if _is_internal_ip(url):
        raise ValueError(
            f"Refusing to crawl internal/private IP address: {url}. "
            "Only public URLs are allowed."
        )


# ---------------------------------------------------------------------------
# Crawl4AI client
# ---------------------------------------------------------------------------


async def _crawl_page_internal(url: str, format_: str = "markdown", max_chars: int = MAX_CHARS) -> dict:
    """Fetch and extract a web page via Crawl4AI.

    Args:
        url: The URL to crawl.
        format_: Output format — "markdown" (default) or "html".
        max_chars: Maximum characters to return (truncated at word boundary).

    Returns:
        Dict with url, format, content, and char count.
    """
    _validate_url(url)

    # Choose Crawl4AI endpoint based on format
    if format_ == "markdown":
        endpoint = "/md"
    elif format_ == "html":
        endpoint = "/crawl"
    else:
        raise ValueError(f"Unsupported format '{format_}'. Use 'markdown' or 'html'.")

    target_url = f"{CRAWL4AI_URL}{endpoint}"

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                target_url,
                json={"url": url},
            )
            resp.raise_for_status()
            content = resp.text
    except httpx.HTTPError as exc:
        logger.error("Crawl4AI request failed for %s: %s", url, exc)
        raise RuntimeError(f"Crawl4AI request failed: {exc}") from exc
    except Exception as exc:
        logger.error("Unexpected error crawling %s: %s", url, exc)
        raise RuntimeError(f"Crawl error: {exc}") from exc

    # Truncate to max_chars at word boundary
    content = _truncate(content, max_chars)

    return {
        "url": url,
        "format": format_,
        "content": content,
        "chars": len(content),
        "truncated": len(content) >= max_chars,
    }


def _truncate(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, ending at a word boundary."""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.5:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "… (truncated, original was longer)"


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")

mcp = FastMCP(
    name="mcp_crawl",
    instructions=(
        "Fetch and extract web page content via Crawl4AI. "
        "Supports markdown (default) and HTML output. "
        "Internal/private IP addresses are blocked. "
        f"Max {MAX_CONCURRENT} concurrent crawls, {MAX_CHARS} chars max."
    ),
    host=MCPS_HOST,
)

# Semaphore for rate limiting concurrent crawls
_crawl_semaphore = Semaphore(MAX_CONCURRENT)


@mcp.tool(
    name="crawl_page",
    description=(
        "Fetch and extract content from a web page. "
        "Returns markdown by default. Pass format='html' for raw HTML. "
        "Content is truncated to 50000 characters. "
        "Internal/private IP addresses are blocked."
    ),
)
async def crawl_page(
    url: str,
    format: Optional[str] = None,
    max_chars: Optional[int] = None,
) -> dict:
    """Fetch and extract a web page.

    Args:
        url: The URL to crawl (must be http:// or https://).
        format: Output format — "markdown" (default) or "html".
        max_chars: Maximum characters to return (default 50000).
    """
    fmt = format or "markdown"
    char_limit = max_chars if max_chars is not None else MAX_CHARS

    async with _crawl_semaphore:
        return await _crawl_page_internal(url, fmt, char_limit)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP crawl server over SSE transport (0.0.0.0:8000)."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_crawl, Crawl4AI at %s", CRAWL4AI_URL)
    logger.info("Rate limit: %d concurrent, %d max chars", MAX_CONCURRENT, MAX_CHARS)
    mcp.run(transport="sse")  # SSE defaults to 0.0.0.0:8000


if __name__ == "__main__":
    main()
