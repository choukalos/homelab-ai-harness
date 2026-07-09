#!/usr/bin/env python3
"""
research_brief skill — lightweight web research with sub-query generation.

Purpose:
  Generate 2-3 targeted sub-queries from a research topic via an LLM,
  search the web for each sub-query via MCP mcp_search (or SearXNG directly),
  and synthesize a concise research brief summarizing all findings.

Workflow:
  1. Validate the topic input.
  2. Use the LLM (via LiteLLM) to generate 2-3 focused sub-queries from the topic.
  3. Search the web for each sub-query via:
     a) MCP mcp_search tool through LiteLLM (primary path), OR
     b) Direct SearXNG HTTP API (fallback path).
  4. Deduplicate and rank results across all sub-queries.
  5. Use the LLM to synthesize a concise research brief from all results.
  6. Return the brief summary, detailed findings, and source list.

Constraints:
  - Max runtime: 120 seconds (2 minutes).
  - Read-only: no writes, no admin operations.
  - Result limits enforced per search call.
  - No crawling, no artifact saving.
  - Sub-queries generated via LLM for better focus.
  - Graceful fallback from MCP → direct SearXNG.

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
import re
import signal
import threading
import sys
import textwrap
from datetime import datetime, timezone
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_RUNTIME_SECS = int(os.environ.get("RESEARCH_BRIEF_MAX_RUNTIME", "120"))

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("RESEARCH_BRIEF_MODEL_ALIAS", "matrix-coder")

# SearXNG endpoint (fallback when MCP is unavailable)
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")
SEARXNG_TIMEOUT = float(os.environ.get("SEARXNG_TIMEOUT", "10"))

# Search limits
MAX_RESULTS_PER_QUERY = int(os.environ.get("RESEARCH_BRIEF_MAX_RESULTS_PER_QUERY", "8"))
MAX_TOTAL_SOURCES = int(os.environ.get("RESEARCH_BRIEF_MAX_TOTAL_SOURCES", "15"))

logger = logging.getLogger("skill.research_brief")


# ---------------------------------------------------------------------------
# Sub-query generation prompt
# ---------------------------------------------------------------------------

SUBQUERY_GENERATION_PROMPT = textwrap.dedent("""\
    You are a research query optimizer. Given a research topic, generate
    exactly {n_queries} focused sub-queries that together cover the topic
    from complementary angles.

    Topic: {topic}

    Rules:
    - Each sub-query should be specific and targeted (3-8 words).
    - Cover different aspects: definitions, recent developments, comparisons, etc.
    - Avoid overly broad queries.
    - Do NOT repeat the exact topic text; rephrase into search-friendly queries.

    Output ONLY a JSON array of strings, no preamble, no code fences.
    Example: ["what is quantum computing 2026", "quantum computing companies comparison"]
""")


# ---------------------------------------------------------------------------
# Summary synthesis prompt
# ---------------------------------------------------------------------------

SUMMARY_SYNTHESIS_PROMPT = textwrap.dedent("""\
    You are a research analyst. Based on the search results below, write a
    concise research brief.

    Topic: {topic}
    Sub-queries used: {sub_queries}

    Search Results:
    {sources_text}

    Produce:
    1. A 2-3 sentence executive summary.
    2. 3-5 key findings as bullet points.
    3. A short "What to watch" or "Next steps" note if applicable.

    Rules:
    - Use ONLY the provided results. Do not fabricate information.
    - If results are thin, acknowledge that honestly.
    - Cite sources with [N] numbers where relevant.
    - Keep it concise: max 500 words total.
    - Output ONLY the brief — no preamble, no wrapping JSON.
""")


# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"research_brief exceeded {MAX_RUNTIME_SECS}s max runtime")


def _install_timeout():
    """Install a signal-based timeout (Unix only, main thread only)."""
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUNTIME_SECS)


def _cancel_timeout():
    """Cancel the pending alarm."""
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.alarm(0)


# ---------------------------------------------------------------------------
# LiteLLM client abstraction
# ---------------------------------------------------------------------------


class _SyncLiteLLMClient:
    """Synchronous LiteLLM client for standalone/CLI use."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or LITELLM_BASE_URL).rstrip("/")
        self.api_key = api_key or LITELLM_API_KEY

    def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Call /v1/chat/completions for LLM text generation."""
        import urllib.request
        import urllib.error

        payload: dict[str, Any] = {"model": model, "messages": messages}
        payload.update(kwargs)

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise RuntimeError(f"LiteLLM HTTP error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Cannot reach LiteLLM at {self.base_url}: {exc.reason}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON from LiteLLM: {exc}") from exc

    def mcp_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        server_id: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Call /mcp-rest/tools/call for MCP tool execution via LiteLLM.
        Returns the parsed response dict, or empty dict on failure.
        """
        import urllib.request
        import urllib.error

        payload: dict[str, Any] = {"name": tool_name, "arguments": arguments}
        if server_id:
            payload["server_id"] = server_id
        payload.update(kwargs)

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            f"{self.base_url}/mcp-rest/tools/call",
            data=data,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            logger.warning("MCP tool call via LiteLLM failed (%s): HTTP %d %s",
                           tool_name, exc.code, body[:200])
            return {}
        except urllib.error.URLError as exc:
            logger.warning("Cannot reach LiteLLM for MCP tool %s: %s", tool_name, exc)
            return {}
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON from LiteLLM MCP call: %s", exc)
            return {}
        except TimeoutError:
            raise  # let timeout propagate


class _SyncAsyncWrapper:
    """Wraps an async LiteLLMClient (from the runner) for synchronous use."""

    def __init__(self, async_client):
        self._client = async_client
        self.base_url = getattr(async_client, "base_url", LITELLM_BASE_URL)

    def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self._client.chat_completion(model, messages, **kwargs)
            )
            return result
        finally:
            loop.close()

    def mcp_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        server_id: Optional[str] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                self._client.mcp_call(tool_name, arguments, server_id=server_id, **kwargs)
            )
            return result
        finally:
            loop.close()


def _resolve_litellm_client(litellm_client=None) -> Any:
    """Resolve the LiteLLM client to a sync interface."""
    if litellm_client is None:
        return _SyncLiteLLMClient()
    if hasattr(litellm_client, "chat_completion") and hasattr(litellm_client, "mcp_call"):
        import inspect
        if inspect.iscoroutinefunction(litellm_client.chat_completion):
            return _SyncAsyncWrapper(litellm_client)
        return litellm_client
    return _SyncLiteLLMClient()


# ---------------------------------------------------------------------------
# Sub-query generation
# ---------------------------------------------------------------------------


def _generate_sub_queries(client: Any, topic: str, n_queries: int = 3) -> list[str]:
    """
    Use the LLM to generate 2-3 focused sub-queries from the topic.

    Falls back to simple variants if LLM is unavailable.
    """
    prompt = SUBQUERY_GENERATION_PROMPT.format(topic=topic, n_queries=n_queries)

    messages = [
        {
            "role": "system",
            "content": (
                "You generate focused search sub-queries. "
                "Output ONLY a JSON array of strings — no code fences, no preamble."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        result = client.chat_completion(
            MODEL_ALIAS,
            messages,
            max_tokens=512,
            temperature=0.7,
            response_format={"type": "json_object"},
            stream=False,
        )

        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError("LLM returned no choices")

        content = choices[0].get("message", {}).get("content", "").strip()

        # Strip code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        queries = json.loads(content)
        if not isinstance(queries, list):
            queries = [queries]

        # Filter to non-empty strings and cap
        queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]
        return queries[:n_queries]

    except Exception as exc:
        logger.warning("LLM sub-query generation failed, using fallback: %s", exc)
        # Fallback: generate simple query variants
        fallback = [topic]
        if n_queries >= 2:
            fallback.append(f"{topic} overview")
        if n_queries >= 3:
            fallback.append(f"{topic} latest news")
        return fallback[:n_queries]


# ---------------------------------------------------------------------------
# Search: MCP via LiteLLM (primary)
# ---------------------------------------------------------------------------


def _search_via_mcp(client: Any, query: str, max_results: int) -> list[dict]:
    """
    Search via MCP mcp_search through LiteLLM.
    Returns list of result dicts: {title, url, snippet, source}.
    """
    result = client.mcp_call(
        "search_web",
        {"query": query, "max_results": max_results},
        server_id="mcp_search",
    )
    if not result:
        return []

    sources: list[dict] = []
    results_list = result.get("result", result.get("results", []))

    # Handle nested result formats from LiteLLM
    if isinstance(result.get("result"), dict):
        results_list = result["result"].get("results", result["result"].get("data", []))

    for item in results_list:
        if len(sources) >= max_results:
            break
        sources.append({
            "title": item.get("title", "Untitled"),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", item.get("content", ""))[:300],
            "source": "web",
            "sub_query": query,
        })

    return sources


# ---------------------------------------------------------------------------
# Search: Direct SearXNG (fallback)
# ---------------------------------------------------------------------------


def _search_via_searxng(query: str, max_results: int) -> list[dict]:
    """
    Search directly via SearXNG HTTP API (fallback when MCP is unavailable).
    Returns list of result dicts: {title, url, snippet, source}.
    """
    import urllib.parse
    import urllib.request
    import urllib.error

    sources: list[dict] = []
    url = f"{SEARXNG_URL}/search"
    params = urllib.parse.urlencode({
        "q": query,
        "format": "json",
        "categories": "general",
        "language": "en",
    })
    req_url = f"{url}?{params}"

    try:
        req = urllib.request.Request(req_url, method="GET")
        with urllib.request.urlopen(req, timeout=SEARXNG_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError) as exc:
        if isinstance(exc, TimeoutError):
            raise
        logger.warning("Direct SearXNG search failed for '%s': %s", query[:80], exc)
        return []

    results = data.get("results", [])
    for item in results[:max_results]:
        snippet = item.get("content", "")
        # Clean HTML tags
        snippet = re.sub(r"<[^>]+>", "", snippet)
        snippet = snippet[:300]
        sources.append({
            "title": item.get("title", "Untitled"),
            "url": item.get("url", ""),
            "snippet": snippet,
            "source": "web",
            "sub_query": query,
        })

    return sources


def _search_query(query: str, max_results: int, client: Any) -> tuple[list[dict], str]:
    """
    Search for a single query. Tries MCP first, falls back to direct SearXNG.
    Returns (sources, method_used).
    """
    # Try MCP via LiteLLM first
    mcp_available = hasattr(client, "mcp_call")
    if mcp_available:
        sources = _search_via_mcp(client, query, max_results)
        if sources:
            return sources, "mcp"

    # Fallback to direct SearXNG
    sources = _search_via_searxng(query, max_results)
    if sources:
        return sources, "searxng"

    return [], "none"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _deduplicate_sources(sources: list[dict], max_sources: int) -> list[dict]:
    """
    Deduplicate sources by URL, keeping the one from the most relevant sub-query.
    Returns at most max_sources unique sources.
    """
    seen: dict[str, dict] = {}

    for source in sources:
        url = source.get("url", "").lower().strip().rstrip("/")
        if not url:
            continue
        if url not in seen:
            seen[url] = source

    unique = list(seen.values())
    return unique[:max_sources]


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------


def _build_sources_text(sources: list[dict]) -> str:
    """Build a numbered sources text for the summarization prompt."""
    lines: list[str] = []
    for i, src in enumerate(sources, 1):
        lines.append(f"[{i}] {src.get('title', 'Untitled')}")
        lines.append(f"    URL: {src.get('url', '')}")
        snippet = src.get('snippet', '')
        if snippet:
            lines.append(f"    {snippet[:200]}")
        lines.append("")
    return "\n".join(lines)


def _synthesize_brief(
    client: Any,
    topic: str,
    sub_queries: list[str],
    sources: list[dict],
) -> str:
    """
    Use the LLM to synthesize a research brief from all collected sources.

    Falls back to a simple text summary if LLM is unavailable.
    """
    sources_text = _build_sources_text(sources)
    prompt = SUMMARY_SYNTHESIS_PROMPT.format(
        topic=topic,
        sub_queries=", ".join(sub_queries),
        sources_text=sources_text,
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a research analyst. Write a concise research brief "
                "based on search results. Output plain text with markdown "
                "formatting — no JSON, no code fences."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        result = client.chat_completion(
            MODEL_ALIAS,
            messages,
            max_tokens=2048,
            temperature=0.3,
            stream=False,
        )

        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError("LLM returned no choices")

        return choices[0].get("message", {}).get("content", "").strip()

    except Exception as exc:
        logger.warning("LLM summarization failed, using fallback: %s", exc)
        # Fallback: simple text summary
        return _fallback_summary(topic, sub_queries, sources)


def _fallback_summary(topic: str, sub_queries: list[str], sources: list[dict]) -> str:
    """
    Generate a basic text summary without LLM when summarization fails.
    """
    lines = [f"# Research Brief: {topic}\n"]
    lines.append(f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n")
    lines.append(f"**Sub-queries:** {', '.join(sub_queries)}\n")
    lines.append(f"**Sources found:** {len(sources)}\n")

    if sources:
        lines.append("## Key Results\n")
        for i, src in enumerate(sources[:10], 1):
            lines.append(f"{i}. **{src.get('title', 'Untitled')}** — {src.get('url', '')}")
            snippet = src.get('snippet', '')[:150]
            if snippet:
                lines.append(f"   {snippet}")
        lines.append("")
    else:
        lines.append("No results found.\n")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(
    params: dict[str, Any],
    job,
    litellm_client=None,
) -> dict[str, Any]:
    """
    Execute the research_brief skill.

    Generates sub-queries via LLM, searches via MCP or SearXNG, and
    synthesizes a research brief.

    Args:
        params: Skill parameters (topic).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.
            If not provided, a sync client is created from env vars.

    Returns:
        Dict with 'summary', 'brief', 'sources', 'sub_queries'.
    """
    # Resolve LiteLLM client (sync interface guaranteed)
    client = _resolve_litellm_client(litellm_client)

    # Validate inputs
    topic = params.get("topic")
    if not topic or not str(topic).strip():
        result = {"error": "Missing required 'topic' parameter"}
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing topic")
        return result

    topic = str(topic).strip()
    n_queries = int(params.get("n_queries", 3))
    n_queries = max(1, min(n_queries, 5))

    if hasattr(job, "add_log"):
        job.add_log(f"Executing research_brief: topic='{topic[:100]}'")
        job.add_log(f"Sub-queries: {n_queries}, max_results/query: {MAX_RESULTS_PER_QUERY}")
        job.add_log(f"Model alias: {MODEL_ALIAS}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")
        if hasattr(client, 'base_url'):
            job.add_log(f"LiteLLM: {client.base_url}")

    # Install timeout
    _install_timeout()

    try:
        # --- Step 1: Generate sub-queries via LLM ---
        if hasattr(job, "add_log"):
            job.add_log("Step 1: Generating sub-queries via LLM...")

        sub_queries = _generate_sub_queries(client, topic, n_queries)

        if hasattr(job, "add_log"):
            job.add_log(f"Generated {len(sub_queries)} sub-queries:")
            for i, q in enumerate(sub_queries):
                job.add_log(f"  [{i+1}] {q}")

        # --- Step 2: Search for each sub-query ---
        all_sources: list[dict] = []
        search_method = "none"

        if hasattr(job, "add_log"):
            job.add_log(f"Step 2: Searching via MCP/SearXNG ({len(sub_queries)} queries)...")

        for i, query in enumerate(sub_queries):
            sources, method = _search_query(query, MAX_RESULTS_PER_QUERY, client)
            if method != "none":
                search_method = method
            all_sources.extend(sources)
            if hasattr(job, "add_log"):
                job.add_log(f"  Query [{i+1}] '{query[:60]}': {len(sources)} results ({method})")

            if len(all_sources) >= MAX_TOTAL_SOURCES * 2:
                break

        if hasattr(job, "add_log"):
            job.add_log(f"Collected {len(all_sources)} raw results via {search_method}")

        # --- Step 3: Deduplicate ---
        deduped = _deduplicate_sources(all_sources, MAX_TOTAL_SOURCES)

        if hasattr(job, "add_log"):
            job.add_log(f"Deduplicated to {len(deduped)} unique sources")

        # --- Step 4: Synthesize brief via LLM ---
        if hasattr(job, "add_log"):
            job.add_log("Step 3: Synthesizing research brief via LLM...")

        brief = _synthesize_brief(client, topic, sub_queries, deduped)

        if hasattr(job, "add_log"):
            job.add_log(f"Brief generated ({len(brief)} chars)")

        # Extract first paragraph as summary
        summary_lines = brief.split("\n")
        summary = ""
        for line in summary_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "-", "*")):
                summary = stripped
                break
        if not summary:
            summary = brief[:200]

        # Build source list for response
        source_list = [
            {
                "title": s.get("title", "Untitled"),
                "url": s.get("url", ""),
                "snippet": s.get("snippet", "")[:150],
                "source": s.get("source", "web"),
                "sub_query": s.get("sub_query", ""),
            }
            for s in deduped
        ]

        if hasattr(job, "add_log"):
            job.add_log(f"research_brief completed: {len(source_list)} sources, method={search_method}")

        return {
            "summary": summary,
            "brief": brief,
            "sub_queries": sub_queries,
            "sources": source_list,
            "source_count": len(source_list),
            "search_method": search_method,
            "model_alias": MODEL_ALIAS,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")

        partial = (
            f"# Partial Research Brief: {topic}\n\n"
            f"**⚠ Timed out after {MAX_RUNTIME_SECS}s.** Results may be incomplete.\n\n"
            f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        )
        return {
            "summary": f"Research timed out after {MAX_RUNTIME_SECS}s.",
            "brief": partial,
            "sub_queries": [],
            "sources": [],
            "source_count": 0,
            "search_method": "none",
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")

        return {
            "summary": f"Research failed: {msg}",
            "brief": f"# Research Brief: {topic}\n\n**Error:** {msg}\n",
            "sub_queries": [],
            "sources": [],
            "source_count": 0,
            "search_method": "none",
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)

        return {
            "summary": f"Research failed: {msg}",
            "brief": f"# Research Brief: {topic}\n\n**Error:** {msg}\n",
            "sub_queries": [],
            "sources": [],
            "source_count": 0,
            "search_method": "none",
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
        python skill.py --topic "latest AI developments"
        python skill.py --topic "quantum computing" --n-queries 2
        python skill.py --topic "test" --dry-run
    """
    import argparse

    parser = argparse.ArgumentParser(description="research_brief standalone test")
    parser.add_argument("--topic", required=True, help="Research topic")
    parser.add_argument(
        "--n-queries", type=int, default=3, help="Number of sub-queries (1-5)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print parameters without calling any services"
    )
    parser.add_argument(
        "--base-url", default=None, help=f"LiteLLM base URL (default: {LITELLM_BASE_URL})"
    )
    parser.add_argument(
        "--api-key", default=None, help="LiteLLM API key"
    )
    parser.add_argument(
        "--searxng-url", default=None, help=f"SearXNG URL (default: {SEARXNG_URL})"
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  Topic: {args.topic}")
        print(f"  Sub-queries: {args.n_queries}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  LiteLLM: {LITELLM_BASE_URL}")
        print(f"  SearXNG: {SEARXNG_URL}")
        print(f"  Max results/query: {MAX_RESULTS_PER_QUERY}")
        print(f"  Max total sources: {MAX_TOTAL_SOURCES}")
        print()
        print("  Workflow:")
        print("    1. LLM generates sub-queries from topic")
        print("    2. Search each sub-query via MCP mcp_search (or SearXNG fallback)")
        print("    3. Deduplicate results")
        print("    4. LLM synthesizes research brief from all results")
        return

    # Apply overrides for CLI testing
    base_url = args.base_url or LITELLM_BASE_URL
    api_key = args.api_key or LITELLM_API_KEY

    params = {
        "topic": args.topic,
        "n_queries": args.n_queries,
    }

    client = _SyncLiteLLMClient(base_url=base_url, api_key=api_key)
    result = run(params, _MockJob(), litellm_client=client)

    print(f"\n--- research_brief response ---")
    print(f"Summary: {result.get('summary', 'N/A')[:200]}")
    if result.get("sub_queries"):
        print(f"Sub-queries: {', '.join(result['sub_queries'])}")
    if result.get("sources"):
        print(f"Sources: {len(result['sources'])}")
        for i, s in enumerate(result["sources"][:5], 1):
            print(f"  [{i}] {s.get('title', 'N/A')} — {s.get('url', 'N/A')}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"Search method: {result.get('search_method', 'N/A')}")
    print(f"Model: {result.get('model_alias', 'N/A')}")
    print(f"Brief length: {len(result.get('brief', ''))} chars")


if __name__ == "__main__":
    main()
