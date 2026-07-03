#!/usr/bin/env python3
"""
deep_research skill — multi-source deep research with cited markdown reports.

Purpose:
  Execute a structured research workflow: search the web and knowledge base,
  collect and deduplicate sources, synthesize a cited markdown report, and
  save the result as an artifact.

Workflow:
  1. Validate inputs and determine search parameters from depth setting.
  2. Search mcp_search (web) for relevant sources.
  3. Optionally search mcp_knowledge for internal knowledge.
  4. Collect, deduplicate, and rank sources up to max_sources.
  5. Optionally crawl top pages via mcp_crawl for deeper content.
  6. Synthesize a cited markdown report via the model.
  7. Save the report as an artifact file.
  8. Return summary, full report, source list, and artifact path.

Constraints:
  - Max runtime: 900 seconds (15 minutes).
  - Read-only: no writes, no admin operations.
  - Result limits enforced per search call.
  - No crawling beyond max_sources.
  - No browser automation.
  - Artifacts saved to /home/chuck/data/media/research_reports/

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
import re
import signal
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ARTIFACT_DIR = Path(
    os.environ.get("DEEP_RESEARCH_ARTIFACT_DIR", "/home/chuck/data/media/research_reports")
)
MAX_RUNTIME_SECS = int(os.environ.get("DEEP_RESEARCH_MAX_RUNTIME", "900"))

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("DEEP_RESEARCH_MODEL_ALIAS", "local/qwen-coder")

# MCP server endpoints (configured per environment)
MCP_SEARCH_URL = os.environ.get("MCP_SEARCH_URL", "http://localhost:8080")
MCP_CRAWL_URL = os.environ.get("MCP_CRAWL_URL", "http://localhost:11235")
MCP_KNOWLEDGE_URL = os.environ.get("MCP_KNOWLEDGE_URL", "http://localhost:6333")

logger = logging.getLogger("skill.deep_research")

# ---------------------------------------------------------------------------
# Depth settings — controls search breadth and crawl depth
# ---------------------------------------------------------------------------

DEPTH_CONFIG = {
    "quick": {
        "search_queries": 1,
        "max_results_per_query": 5,
        "max_sources": 5,
        "crawl_top": 0,       # no crawling for quick
        "kb_search": False,
    },
    "comprehensive": {
        "search_queries": 3,
        "max_results_per_query": 8,
        "max_sources": 10,
        "crawl_top": 3,       # crawl top 3 sources
        "kb_search": True,
    },
    "exhaustive": {
        "search_queries": 5,
        "max_results_per_query": 10,
        "max_sources": 15,
        "crawl_top": 5,       # crawl top 5 sources
        "kb_search": True,
    },
}


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"deep_research exceeded {MAX_RUNTIME_SECS}s max runtime")


def _install_timeout():
    """Install a signal-based timeout (Unix only)."""
    if sys.platform != "win32":
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUNTIME_SECS)


def _cancel_timeout():
    """Cancel the pending alarm."""
    if sys.platform != "win32":
        signal.alarm(0)


# ---------------------------------------------------------------------------
# MCP tool callers (HTTP-based, non-stdio for skill runner use)
# ---------------------------------------------------------------------------


def _http_post(url: str, payload: dict, timeout: int = 60) -> Optional[dict]:
    """
    Generic HTTP POST helper for MCP tool calls.
    Returns parsed JSON dict or None on failure.
    """
    import urllib.request
    import urllib.error

    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError) as exc:
        logger.warning("HTTP call failed to %s: %s", url, exc)
        return None
    except TimeoutError:
        raise  # let timeout propagate
    except Exception as exc:
        logger.warning("Unexpected error calling %s: %s", url, exc)
        return None


class Source:
    """A single research source with citation metadata."""

    def __init__(
        self,
        title: str,
        url: str,
        snippet: str = "",
        source_name: str = "",
        content: str = "",
        score: float = 0.0,
    ):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source_name = source_name
        self.content = content      # full text if crawled
        self.score = score
        self.citation_id = ""      # assigned during report generation

    def __repr__(self):
        return f"Source({self.title!r}, {self.url!r})"


def _search_web(query: str, max_results: int = 10) -> list[Source]:
    """
    Search the web via mcp_search (SearXNG backend).
    Returns a list of Source objects.
    """
    # SearXNG search API: POST /search with json
    payload = {
        "q": query,
        "format": "json",
        "categories": "general",
        "language": "en",
        "engines": ["google", "bing", "duckduckgo", "wikipedia"],
    }

    result = _http_post(f"{MCP_SEARCH_URL}/search", payload, timeout=60)
    if not result:
        logger.warning("Web search returned no results for: %s", query[:100])
        return []

    sources: list[Source] = []
    for item in result.get("results", []):
        if len(sources) >= max_results:
            break
        sources.append(
            Source(
                title=item.get("title", "Untitled"),
                url=item.get("url", ""),
                snippet=item.get("content", item.get("snippet", ""))[:500],
                source_name=item.get("engine", "web"),
                score=float(item.get("score", 0)),
            )
        )

    logger.info("Web search returned %d results for: %s", len(sources), query[:80])
    return sources


def _search_recent(query: str, days: int = 30, max_results: int = 10) -> list[Source]:
    """Search for recent results (within N days)."""
    payload = {
        "q": query,
        "format": "json",
        "categories": "general",
        "language": "en",
        "time_range": f"{days}d",
    }

    result = _http_post(f"{MCP_SEARCH_URL}/search", payload, timeout=60)
    if not result:
        return []

    sources: list[Source] = []
    for item in result.get("results", []):
        if len(sources) >= max_results:
            break
        sources.append(
            Source(
                title=item.get("title", "Untitled"),
                url=item.get("url", ""),
                snippet=item.get("content", item.get("snippet", ""))[:500],
                source_name=item.get("engine", "web"),
                score=float(item.get("score", 0)),
            )
        )
    return sources


def _search_news(query: str, max_results: int = 10) -> list[Source]:
    """Search news specifically."""
    payload = {
        "q": query,
        "format": "json",
        "categories": "news",
        "language": "en",
    }

    result = _http_post(f"{MCP_SEARCH_URL}/search", payload, timeout=60)
    if not result:
        return []

    sources: list[Source] = []
    for item in result.get("results", []):
        if len(sources) >= max_results:
            break
        sources.append(
            Source(
                title=item.get("title", "Untitled"),
                url=item.get("url", ""),
                snippet=item.get("content", item.get("snippet", ""))[:500],
                source_name="news",
                score=float(item.get("score", 0)),
            )
        )
    return sources


def _search_knowledge(query: str, top_k: int = 5, collections: list[str] = None) -> list[Source]:
    """
    Search the knowledge base via mcp_knowledge (Qdrant backend).
    Returns a list of Source objects from internal knowledge.
    """
    if collections is None:
        collections = ["family_curated", "homelab_curated"]

    results = []
    for collection in collections:
        payload = {
            "query": query,
            "collection": collection,
            "top_k": top_k,
        }
        result = _http_post(f"{MCP_KNOWLEDGE_URL}/api/v1/search", payload, timeout=30)
        if not result:
            continue

        for item in result.get("matches", result.get("results", [])):
            results.append(
                Source(
                    title=item.get("title", f"KB: {collection}"),
                    url=item.get("url", f"kb://{collection}/{item.get('id', 'unknown')}"),
                    snippet=item.get("text", item.get("payload", {}).get("text", ""))[:500],
                    source_name=f"kb:{collection}",
                    score=float(item.get("score", 0)),
                )
            )

    logger.info("Knowledge search returned %d results", len(results))
    return results


def _crawl_url(url: str, max_chars: int = 5000) -> Optional[str]:
    """
    Fetch and extract content from a URL via mcp_crawl (Crawl4AI backend).
    Returns extracted text or None on failure.
    """
    payload = {
        "url": url,
        "max_chars": max_chars,
        "format": "text",
    }
    result = _http_post(f"{MCP_CRAWL_URL}/crawl", payload, timeout=120)
    if not result:
        return None
    return result.get("content", result.get("text", ""))


# ---------------------------------------------------------------------------
# Source collection and deduplication
# ---------------------------------------------------------------------------


def _generate_search_queries(query: str, num_queries: int) -> list[str]:
    """
    Generate multiple search query variants from the original query.
    For num_queries > 1, creates variations (broad, specific, recent).
    """
    queries = [query]

    if num_queries >= 2:
        queries.append(f"{query} latest developments")
    if num_queries >= 3:
        queries.append(f"{query} analysis overview")
    if num_queries >= 4:
        queries.append(f"{query} review 2024 2025 2026")
    if num_queries >= 5:
        queries.append(f"what is {query}")

    return queries[:num_queries]


def _deduplicate_sources(sources: list[Source], max_sources: int) -> list[Source]:
    """
    Deduplicate sources by URL and score, keeping the best match.
    Returns at most max_sources unique sources sorted by score.
    """
    seen_urls: dict[str, Source] = {}

    for source in sources:
        normalized_url = source.url.lower().strip().rstrip("/")
        if not normalized_url:
            continue
        existing = seen_urls.get(normalized_url)
        if existing is None or source.score > existing.score:
            seen_urls[normalized_url] = source

    # Sort by score descending
    unique = sorted(seen_urls.values(), key=lambda s: s.score, reverse=True)
    return unique[:max_sources]


def _collect_sources(query: str, depth: str, max_sources: int) -> list[Source]:
    """
    Phase 1: Collect research sources from web and knowledge base.
    """
    config = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["comprehensive"])

    # Apply max_sources cap from config or user override
    effective_max = min(config["max_sources"], max_sources)
    per_query_max = config["max_results_per_query"]

    all_sources: list[Source] = []

    # Web searches with varied queries
    queries = _generate_search_queries(query, config["search_queries"])
    for i, q in enumerate(queries):
        logger.info("Search query %d/%d: %s", i + 1, len(queries), q[:80])
        results = _search_web(q, max_results=per_query_max)
        all_sources.extend(results)
        if len(all_sources) >= effective_max * 2:
            break

    # Knowledge base search
    if config["kb_search"]:
        kb_results = _search_knowledge(query, top_k=min(effective_max, 5))
        all_sources.extend(kb_results)

    # Deduplicate and cap
    sources = _deduplicate_sources(all_sources, effective_max)
    logger.info("Collected %d unique sources (max requested: %d)", len(sources), max_sources)
    return sources


def _crawl_top_sources(sources: list[Source], crawl_count: int) -> list[Source]:
    """
    Phase 2: Crawl the top N web sources for full content.
    Only crawls web URLs (not KB sources).
    """
    if crawl_count <= 0:
        return sources

    crawled = 0
    for source in sources[:crawl_count]:
        if not source.url.startswith(("http://", "https://")):
            continue
        if crawled >= crawl_count:
            break
        content = _crawl_url(source.url, max_chars=8000)
        if content:
            source.content = content
            crawled += 1
            logger.info("Crawled: %s (%d chars)", source.title, len(content))

    return sources


# ---------------------------------------------------------------------------
# Report synthesis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a research analyst preparing a thorough, cited research report.

    You will be given a research query and a collection of sources
    (with titles, URLs, snippets, and optionally full content).

    Your task is to produce a well-structured Markdown research report with:

    1. **Summary**: A concise 2-3 paragraph executive summary of findings.
    2. **Full Report**: A detailed analysis organized into logical sections.
    3. **Citations**: Every factual claim must include a citation in the form [N]
       where N is the source number in the source list.
    4. **Source List**: A numbered list of all sources consulted with title, URL, and type.

    Rules:
    - Use ONLY the provided sources. Do not fabricate information.
    - If sources are insufficient, acknowledge gaps honestly.
    - Cite every factual claim with [N] references.
    - Keep the report factual and analytical, not promotional.
    - Use markdown formatting: headers, bullet lists, bold for key terms.
    - The report should be self-contained and readable on its own.
    - Include a "Key Findings" section with 3-5 bullet points at the top.
    - Include a "Limitations" section noting what was not covered or needs further research.
    - Output ONLY the markdown report — no preamble, no wrapping JSON.
""")


def _build_research_context(query: str, sources: list[Source]) -> str:
    """Build the context string from collected sources for the model."""
    lines = [f"## Research Query\n\n{query}\n\n"]
    lines.append("## Sources\n\n")

    for i, source in enumerate(sources, 1):
        lines.append(f"### Source [{i}] — {source.title}")
        lines.append(f"- **URL:** {source.url}")
        lines.append(f"- **Type:** {source.source_name}")
        lines.append(f"- **Snippet:** {source.snippet[:300]}")
        if source.content:
            content_preview = source.content[:2000]
            lines.append(f"- **Content (excerpt):** {content_preview}")
        lines.append("")

    lines.append(
        "\n---\n\n"
        "Produce a complete cited research report based on the above sources.\n"
        "Format: Summary, Key Findings, Full Report, Limitations, Source List.\n"
    )

    return "\n".join(lines)


def _call_litellm(messages: list[dict[str, str]], max_tokens: int = 8000) -> str:
    """
    Call LiteLLM for report synthesis.
    """
    import urllib.request
    import urllib.error

    payload = {
        "model": MODEL_ALIAS,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"

    req = urllib.request.Request(
        f"{LITELLM_BASE_URL}/v1/chat/completions",
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            choices = body.get("choices", [])
            if not choices:
                return "No response generated."
            return choices[0].get("message", {}).get("content", "No content in response.")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"LiteLLM HTTP error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach LiteLLM at {LITELLM_BASE_URL}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from LiteLLM: {exc}") from exc


def _synthesize_report(query: str, sources: list[Source]) -> str:
    """
    Phase 3: Synthesize the cited markdown report from collected sources.
    """
    context = _build_research_context(query, sources)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]

    # Determine max_tokens based on depth
    max_tokens = 8000
    if len(context) > 15000:
        max_tokens = 12000

    return _call_litellm(messages, max_tokens=max_tokens)


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Convert a string to a filename-safe slug."""
    return "".join(c if c.isalnum() or c == "-" else "-" for c in value[:60]).strip("-")


def _write_artifact(report: str, query: str) -> Optional[str]:
    """
    Save the research report as an artifact file.
    Returns the file path or None on failure.
    """
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        slug = _slugify(query)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"deep_research_{ts}_{slug}.md"
        path = ARTIFACT_DIR / filename
        path.write_text(report, encoding="utf-8")
        logger.info("Artifact written: %s", path)
        return str(path)
    except OSError as exc:
        logger.error("Could not write artifact: %s", exc)
        return None


def _extract_summary(report: str) -> str:
    """
    Extract the summary/overview portion from the report for the response.
    Looks for the first major section or the first few paragraphs.
    """
    lines = report.split("\n")
    summary_lines: list[str] = []
    in_summary = False
    found_first_header = False

    for line in lines:
        if line.startswith("## "):
            if not found_first_header:
                found_first_header = True
                if "summary" in line.lower() or "overview" in line.lower() or "key findings" in line.lower():
                    in_summary = True
                continue
            else:
                break
        if not found_first_header and (line.strip() or not summary_lines):
            summary_lines.append(line)
            if len(summary_lines) >= 10:
                break

    return "\n".join(summary_lines)[:500]


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job) -> dict[str, Any]:
    """
    Execute the deep_research skill.

    Args:
        params: Skill parameters (query, depth, max_sources).
        job: The runner Job object for logging.

    Returns:
        Dict with 'summary', 'report', 'sources', 'artifact_path'.
    """
    # Validate inputs
    query = params.get("query")
    if not query or not str(query).strip():
        result = {"error": "Missing required 'query' parameter"}
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing query")
        return result

    query = str(query).strip()
    depth = params.get("depth", "comprehensive")
    max_sources = params.get("max_sources", 10)

    # Validate depth
    if depth not in ("quick", "comprehensive", "exhaustive"):
        if hasattr(job, "add_log"):
            job.add_log(f"Invalid depth '{depth}', defaulting to comprehensive")
        depth = "comprehensive"

    # Validate max_sources
    if not isinstance(max_sources, int) or max_sources < 1:
        max_sources = 10
    max_sources = min(max_sources, 30)  # hard cap

    # Enforce depth config max_sources cap
    config = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["comprehensive"])
    effective_max = min(config["max_sources"], max_sources)

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing deep_research: query='{query[:100]}...'")
        job.add_log(f"Depth: {depth}, max_sources: {effective_max}")
        job.add_log(f"Model alias: {MODEL_ALIAS}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")

    # Install timeout
    _install_timeout()

    try:
        # Phase 1: Collect sources
        if hasattr(job, "add_log"):
            job.add_log("Phase 1: Collecting sources...")

        sources = _collect_sources(query, depth, effective_max)

        if not sources:
            report = (
                f"# Research Report: {query}\n\n"
                f"**No sources found.** The research query returned no relevant results. "
                f"Please try a different query or broader terms.\n\n"
                f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
            )
            if hasattr(job, "add_log"):
                job.add_log("No sources found — generating empty report")
        else:
            # Phase 2: Crawl top sources (if depth allows)
            crawl_count = config.get("crawl_top", 0)
            if crawl_count > 0:
                if hasattr(job, "add_log"):
                    job.add_log(f"Phase 2: Crawling top {crawl_count} sources...")
                sources = _crawl_top_sources(sources, crawl_count)

            # Phase 3: Synthesize report
            if hasattr(job, "add_log"):
                job.add_log(f"Phase 3: Synthesizing report from {len(sources)} sources...")

            report = _synthesize_report(query, sources)

            if hasattr(job, "add_log"):
                job.add_log(f"Report generated ({len(report)} chars)")

        # Phase 4: Save artifact
        artifact_path = _write_artifact(report, query)

        if hasattr(job, "add_log"):
            if artifact_path:
                job.add_log(f"Artifact saved: {artifact_path}")
            else:
                job.add_log("Warning: artifact save failed, report returned inline only")

        # Extract summary
        summary = _extract_summary(report)

        # Build source list
        source_list = [
            {"title": s.title, "url": s.url, "type": s.source_name}
            for s in sources
        ]

        if hasattr(job, "add_log"):
            job.add_log(f"deep_research completed: {len(source_list)} sources, {len(report)} chars")

        return {
            "summary": summary,
            "report": report,
            "sources": source_list,
            "artifact_path": artifact_path,
            "model_alias": MODEL_ALIAS,
            "depth": depth,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")

        # Return partial report if we have one
        partial = (
            f"# Partial Research Report: {query}\n\n"
            f"**⚠ Research timed out after {MAX_RUNTIME_SECS}s.** "
            f"The process was interrupted. Results may be incomplete.\n\n"
            f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        )
        artifact_path = _write_artifact(partial, query)

        return {
            "summary": f"Research timed out after {MAX_RUNTIME_SECS}s. Results may be incomplete.",
            "report": partial,
            "sources": [],
            "artifact_path": artifact_path,
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")

        partial = (
            f"# Research Report: {query}\n\n"
            f"**⚠ Error during research:** {msg}\n\n"
            f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        )
        artifact_path = _write_artifact(partial, query)

        return {
            "summary": f"Research failed: {msg}",
            "report": partial,
            "sources": [],
            "artifact_path": artifact_path,
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)

        partial = f"# Research Report: {query}\n\n**Error:** {msg}\n"
        artifact_path = _write_artifact(partial, query)

        return {
            "summary": f"Research failed: {msg}",
            "report": partial,
            "sources": [],
            "artifact_path": artifact_path,
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# CLI entrypoint (for standalone testing)
# ---------------------------------------------------------------------------


class _MockJob:
    """Dummy job object for standalone testing."""

    def __init__(self):
        self.logs: list[str] = []

    def add_log(self, msg: str) -> None:
        self.logs.append(msg)
        print(f"  [LOG] {msg}")


def main():
    """Standalone test entrypoint.

    Usage:
        python skill.py --query "Latest developments in quantum computing"
        python skill.py --query "AI trends 2026" --depth exhaustive --max-sources 15
        python skill.py --query "Test" --dry-run
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="deep_research standalone test"
    )
    parser.add_argument("--query", required=True, help="Research topic or question")
    parser.add_argument(
        "--depth",
        default="comprehensive",
        choices=["quick", "comprehensive", "exhaustive"],
        help="Research depth",
    )
    parser.add_argument(
        "--max-sources",
        type=int,
        default=10,
        help="Maximum number of sources to consult",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print parameters without calling any services",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=f"LiteLLM base URL (default: {LITELLM_BASE_URL})",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="LiteLLM API key",
    )
    parser.add_argument(
        "--search-url",
        default=None,
        help=f"SearXNG URL (default: {MCP_SEARCH_URL})",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  Query: {args.query}")
        print(f"  Depth: {args.depth}")
        print(f"  Max sources: {args.max_sources}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Artifact dir: {ARTIFACT_DIR}")
        print(f"  LiteLLM: {LITELLM_BASE_URL}")
        print(f"  SearXNG: {MCP_SEARCH_URL}")
        print(f"  Crawl: {MCP_CRAWL_URL}")
        print(f"  Knowledge: {MCP_KNOWLEDGE_URL}")

        config = DEPTH_CONFIG[args.depth]
        print(f"  Depth config: {config}")
        return

    # Apply overrides for CLI testing
    if args.base_url:
        globals()["LITELLM_BASE_URL"] = args.base_url
    if args.api_key:
        globals()["LITELLM_API_KEY"] = args.api_key
    if args.search_url:
        globals()["MCP_SEARCH_URL"] = args.search_url

    params = {
        "query": args.query,
        "depth": args.depth,
        "max_sources": args.max_sources,
    }
    result = run(params, _MockJob())

    print(f"\n--- deep_research response ---")
    print(f"Summary: {result.get('summary', 'N/A')[:200]}")
    if result.get("sources"):
        print(f"Sources: {len(result['sources'])}")
        for i, s in enumerate(result["sources"][:5], 1):
            print(f"  [{i}] {s.get('title', 'N/A')} — {s.get('url', 'N/A')}")
    if result.get("artifact_path"):
        print(f"Artifact: {result['artifact_path']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"Model: {result.get('model_alias', 'N/A')}")
    print(f"Report length: {len(result.get('report', ''))} chars")


if __name__ == "__main__":
    main()
