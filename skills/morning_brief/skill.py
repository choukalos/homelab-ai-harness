#!/usr/bin/env python3
"""
morning_brief skill — daily news brief across configurable interest topics.

Purpose:
  Search news for each configured interest topic via LiteLLM's MCP gateway
  (mcp_search-search_news), deduplicate results, synthesize a short-and-sweet
  bullet-point markdown summary via LLM, and save the brief as an artifact —
  all routed through LiteLLM. Never touch MCP servers directly.

Workflow:
  1. Validate inputs and resolve interest topics (input param or config defaults).
  2. Call mcp_search-search_news via LiteLLM for each interest topic.
  3. Deduplicate results across all topics by URL.
  4. Synthesize a short-and-sweet markdown brief via LiteLLM chat completion.
     - Bullet points, 1-2 lines per item, max items per category.
  5. Save the brief as an artifact file.
  6. Return summary, full report, item counts, and artifact path.

Constraints:
  - Max runtime: 180 seconds (3 minutes).
  - Read-only: no writes, no admin operations.
  - All MCP calls go through LiteLLM — never direct MCP server access.
  - News search via mcp_search-search_news.
  - Output format: short_and_sweet (bullet points, 1-2 lines per item, max per category).
  - Artifacts saved to /home/chuck/data/media/homelab_reports/

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
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ARTIFACT_DIR = Path(
    os.environ.get("MORNING_BRIEF_ARTIFACT_DIR", "/home/chuck/data/media/homelab_reports")
)
MAX_RUNTIME_SECS = int(os.environ.get("MORNING_BRIEF_MAX_RUNTIME", "180"))

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("MORNING_BRIEF_MODEL_ALIAS", "matrix-coder")

# Default interest topics from skill.yml config
DEFAULT_INTERESTS = [
    "technology news",
    "smart home security",
    "Ring SimpliSafe Nest Arlo ADT news",
    "Xfinity press release",
    "artificial intelligence news",
]

logger = logging.getLogger("skill.morning_brief")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"morning_brief exceeded {MAX_RUNTIME_SECS}s max runtime")


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
#
# Copied from deep_research pattern — same sync wrapper logic so this
# skill works both standalone (CLI) and via the async runner.
# ---------------------------------------------------------------------------


class _SyncLiteLLMClient:
    """
    Synchronous LiteLLM client for standalone/CLI use.

    Makes HTTP calls to the LiteLLM proxy for:
    - LLM generation via /v1/chat/completions
    - MCP tool calls via /mcp-rest/tools/call

    This class ensures the skill never touches MCP servers directly —
    all MCP interactions go through the LiteLLM proxy.
    """

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
        Call /mcp-rest/tools/call for MCP tool execution.

        All MCP tool calls are routed through LiteLLM — this skill
        never contacts MCP servers directly.
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
            logger.warning("MCP tool call via LiteLLM failed (%s): %s", tool_name, body)
            return {}
        except urllib.error.URLError as exc:
            logger.warning(
                "Cannot reach LiteLLM for MCP tool %s: %s", tool_name, exc
            )
            return {}
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON from LiteLLM MCP call: %s", exc)
            return {}
        except TimeoutError:
            raise  # let timeout propagate


class _SyncAsyncWrapper:
    """
    Wraps an async LiteLLMClient (from the runner) so skill code can
    call it synchronously. Used when the runner passes an async client.
    """

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
    """
    Resolve the LiteLLM client to a sync interface.

    - If litellm_client is an async LiteLLMClient from the runner, wrap it.
    - If litellm_client is already sync, use as-is.
    - Otherwise, create a new sync client from env vars.
    """
    if litellm_client is None:
        return _SyncLiteLLMClient()
    if hasattr(litellm_client, "chat_completion") and hasattr(litellm_client, "mcp_call"):
        import inspect
        if inspect.iscoroutinefunction(litellm_client.chat_completion):
            return _SyncAsyncWrapper(litellm_client)
        return litellm_client
    return _SyncLiteLLMClient()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class NewsItem:
    """A single news item with metadata."""

    def __init__(
        self,
        title: str,
        url: str,
        snippet: str = "",
        source: str = "",
        category: str = "",
    ):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source
        self.category = category  # which interest topic it was found under

    def __repr__(self):
        return f"NewsItem({self.title!r}, {self.url!r})"


# ---------------------------------------------------------------------------
# MCP wrappers — all calls go through LiteLLM
# ---------------------------------------------------------------------------


def _search_news(client: Any, query: str, max_results: int = 5) -> list[NewsItem]:
    """
    Search news via mcp_search-search_news through LiteLLM.

    Returns a list of NewsItem objects.
    """
    result = client.mcp_call(
        "search_news",
        {"query": query, "max_results": max_results},
        server_id="mcp_search",
    )
    if not result:
        logger.warning("News search returned no results for: %s", query[:100])
        return []

    items: list[NewsItem] = []
    results_list = result.get("result", result.get("results", []))
    if isinstance(result.get("result"), dict):
        results_list = result["result"].get("results", result["result"].get("data", []))

    for item in results_list:
        if len(items) >= max_results:
            break
        if isinstance(item, dict):
            items.append(NewsItem(
                title=item.get("title", "Untitled"),
                url=item.get("url", ""),
                snippet=item.get("snippet", item.get("content", ""))[:300],
                source=item.get("source", item.get("engine", "news")),
            ))

    logger.info("News search returned %d results for: %s", len(items), query[:80])
    return items


# ---------------------------------------------------------------------------
# Interest resolution
# ---------------------------------------------------------------------------


def _resolve_interests(params: dict[str, Any], config_interests: list[str]) -> list[str]:
    """
    Resolve interest topics from input param or fall back to config defaults.

    Input `interests` can be:
    - A comma-separated string (most common from skill.yml input)
    - A list of strings (programmatic use)
    - Missing/empty → use config defaults

    Returns a list of non-empty interest topic strings.
    """
    raw = params.get("interests")

    if raw is None or raw == "":
        if config_interests:
            return list(config_interests)
        return list(DEFAULT_INTERESTS)

    if isinstance(raw, list):
        topics = [str(t).strip() for t in raw if str(t).strip()]
    else:
        topics = [t.strip() for t in str(raw).split(",") if t.strip()]

    # If user provided at least one topic, use it (even if fewer than defaults)
    if topics:
        return topics

    # Fall back to defaults if input was empty after parsing
    return list(config_interests) if config_interests else list(DEFAULT_INTERESTS)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _deduplicate_items(items: list[NewsItem]) -> list[NewsItem]:
    """
    Deduplicate news items by normalized URL, keeping the first occurrence.
    Preserves category tags from original search.
    """
    seen_urls: dict[str, NewsItem] = {}

    for item in items:
        normalized_url = item.url.lower().strip().rstrip("/")
        if not normalized_url:
            continue
        if normalized_url not in seen_urls:
            seen_urls[normalized_url] = item

    # Sort by category to keep groupings together, then by insertion order
    result = list(seen_urls.values())
    logger.info("Deduplicated: %d → %d unique items", len(items), len(result))
    return result


# ---------------------------------------------------------------------------
# Grouping by category
# ---------------------------------------------------------------------------


def _group_by_category(
    items: list[NewsItem],
    interests: list[str],
    max_items: int,
) -> dict[str, list[NewsItem]]:
    """
    Group news items by their original interest category,
    capping each category at max_items.
    Items not matching any category go into 'other'.
    """
    categorized: dict[str, list[NewsItem]] = {topic: [] for topic in interests}
    categorized["other"] = []

    interest_keywords = {}
    for topic in interests:
        keywords = set(re.split(r'[\s\-]+', topic.lower()))
        keywords.discard("")
        # Add common compound keywords
        keywords.add(topic.lower())
        interest_keywords[topic] = keywords

    for item in items:
        # If item was tagged with a category, use it directly
        if item.category in categorized:
            if len(categorized[item.category]) < max_items:
                categorized[item.category].append(item)
                continue

        # Try to match against each interest topic
        content = (item.title + " " + item.snippet).lower()
        matched = False
        for topic, keywords in interest_keywords.items():
            if len(categorized[topic]) >= max_items:
                continue
            # Match if any keyword appears in the content
            for kw in keywords:
                if len(kw) > 2 and kw in content:
                    categorized[topic].append(item)
                    matched = True
                    break
            if matched:
                break

        if not matched:
            if len(categorized["other"]) < max_items:
                categorized["other"].append(item)

    # Return only categories with items (plus "other" if non-empty)
    result = {}
    for topic in interests:
        if categorized[topic]:
            result[topic] = categorized[topic]
    if categorized["other"]:
        result["other"] = categorized["other"]

    return result


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a morning brief assistant producing a SHORT AND SWEET news summary.

    You will be given news items grouped by interest category.

    Produce a concise Markdown brief with:

    1. **Header**: Brief title with today's date.
    2. **Per-category sections**: Each interest topic gets its own section with
       bullet-point summaries.
    3. **Bullet format**: Each item is ONE bullet point, 1-2 lines maximum.
       Format: "- **Headline** — brief one-line summary [source](URL)"
       **Every bullet MUST end with a clickable markdown link to the source.**
    4. **Max items per category**: Do not exceed the specified max_items count.
    5. **Tone**: Informative, concise, no fluff.

    Rules:
    - Each bullet is 1-2 lines ONLY — no paragraphs.
    - Use the headline as the bold lead, then a brief summary.
    - **ALWAYS include a clickable link at the end of each bullet**:
      format `[source_name](https://example.com/...)` or `[link](https://...)`.
      The user needs to be able to click through to the original article.
    - Omit duplicate or redundant items.
    - Keep the entire brief scannable in under 30 seconds.
    - Output ONLY the markdown brief — no preamble, no wrapping JSON.
""")


def _build_brief_context(
    interests: list[str],
    categorized: dict[str, list[NewsItem]],
    max_items: int,
) -> str:
    """Build the context string for the LLM synthesis."""
    lines = [
        f"## Morning Brief — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "",
        f"**Format:** short and sweet, bullet points, max {max_items} items per category",
        "",
    ]

    for topic, items in categorized.items():
        if not items:
            continue
        display_topic = topic if topic != "other" else "General / Other"
        lines.append(f"## {display_topic}")
        lines.append("")

        capped = items[:max_items]
        for item in capped:
            # Build a concise bullet: headline + snippet
            headline = item.title.strip()
            snippet = item.snippet.strip() if item.snippet else ""
            source = item.source if item.source and item.source != "news" else ""

            bullet = f"- **{headline}**"
            if snippet:
                # Truncate snippet to one line
                one_liner = snippet.split("\n")[0].strip()
                if len(one_liner) > 120:
                    one_liner = one_liner[:117] + "..."
                bullet += f" — {one_liner}"
            if source:
                bullet += f" ({source})"
            # Always append a clickable markdown link to the URL
            bullet += f" [{source or 'link'}]({item.url})"
            lines.append(bullet)

        lines.append("")

    lines.append("")
    lines.append(
        "Synthesize the above into a clean, scannable morning brief.\n"
        "Keep each bullet to 1-2 lines. Use bold headlines. "
        "Max 5 items per category. Output ONLY the markdown.\n"
    )

    return "\n".join(lines)


def _synthesize_brief(
    client: Any,
    interests: list[str],
    categorized: dict[str, list[NewsItem]],
    max_items: int,
) -> str:
    """Synthesize the morning brief via LLM chat completion through LiteLLM."""
    context = _build_brief_context(interests, categorized, max_items)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]

    result = client.chat_completion(
        MODEL_ALIAS,
        messages,
        max_tokens=4000,
        temperature=0.3,
        stream=False,
    )

    choices = result.get("choices", [])
    if not choices:
        return (
            f"# Morning Brief — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            "**No brief generated.** LLM returned no content.\n"
        )
    content = (choices[0].get("message") or {}).get("content")
    if not content:
        return (
            f"# Morning Brief — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            "**No brief generated.** LLM returned empty content.\n"
        )
    return content


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Convert a string to a filename-safe slug."""
    return "".join(c if c.isalnum() or c == "-" else "-" for c in value[:60]).strip("-")


def _write_artifact(report: str) -> Optional[str]:
    """
    Save the morning brief as an artifact file.
    Returns the file path or None on failure.
    """
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"morning_brief_{ts}.md"
        path = ARTIFACT_DIR / filename
        path.write_text(report, encoding="utf-8")
        logger.info("Artifact written: %s", path)
        return str(path)
    except OSError as exc:
        logger.error("Could not write artifact: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(
    params: dict[str, Any],
    job,
    litellm_client=None,
) -> dict[str, Any]:
    """
    Execute the morning_brief skill.

    All LLM and MCP interactions go through LiteLLM. This skill never
    contacts MCP servers directly.

    Args:
        params: Skill parameters (interests, max_items).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.

    Returns:
        Dict with 'summary', 'report', 'artifact_path', 'categories', 'item_count'.
    """
    # Resolve LiteLLM client (sync interface guaranteed)
    client = _resolve_litellm_client(litellm_client)

    # Resolve interest topics from input or config defaults
    interests = _resolve_interests(params, DEFAULT_INTERESTS)
    max_items = params.get("max_items", 5)

    # Validate max_items
    if not isinstance(max_items, int) or max_items < 1:
        max_items = 5
    max_items = min(max_items, 10)  # hard cap

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing morning_brief: {len(interests)} interest topic(s), max_items={max_items}")
        job.add_log(f"Interests: {', '.join(interests)}")
        job.add_log(f"Model alias: {MODEL_ALIAS}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")
        job.add_log(f"LiteLLM: {client.base_url}")

    # Install timeout
    _install_timeout()

    try:
        # Phase 1: Search news for each interest topic via LiteLLM
        all_items: list[NewsItem] = []

        for topic in interests:
            if hasattr(job, "add_log"):
                job.add_log(f"Phase 1: Searching news for '{topic}' via mcp_search...")

            items = _search_news(client, topic, max_results=max_items)
            for item in items:
                item.category = topic
            all_items.extend(items)

        if hasattr(job, "add_log"):
            job.add_log(f"Phase 1 complete: collected {len(all_items)} raw items")

        if not all_items:
            # No results — generate a fallback brief
            report = (
                f"# Morning Brief — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
                f"**No news results found.** The search returned no results for the configured "
                f"interest topics. Please check your network or try again later.\n\n"
                f"**Topics searched:** {', '.join(interests)}\n"
            )
            if hasattr(job, "add_log"):
                job.add_log("No news results — generating fallback report")

        else:
            # Phase 2: Deduplicate
            if hasattr(job, "add_log"):
                job.add_log("Phase 2: Deduplicating results...")

            unique_items = _deduplicate_items(all_items)

            # Phase 3: Group by category
            if hasattr(job, "add_log"):
                job.add_log("Phase 3: Grouping by category...")

            categorized = _group_by_category(unique_items, interests, max_items)

            # Phase 4: Synthesize brief via LLM
            if hasattr(job, "add_log"):
                job.add_log(f"Phase 4: Synthesizing brief from {len(unique_items)} items via LLM...")

            report = _synthesize_brief(client, interests, categorized, max_items)

            if hasattr(job, "add_log"):
                job.add_log(f"Brief generated ({len(report)} chars)")

        # Phase 5: Save artifact
        artifact_path = _write_artifact(report)

        if hasattr(job, "add_log"):
            if artifact_path:
                job.add_log(f"Artifact saved: {artifact_path}")
            else:
                job.add_log("Warning: artifact save failed, report returned inline only")

        # Extract summary (first few lines)
        summary_lines = report.strip().split("\n")[:5]
        summary = " ".join(summary_lines).strip()

        # Count items per category
        category_counts: dict[str, int] = {}
        # Parse categories from report headers (lines starting with "## ")
        for line in report.split("\n"):
            if line.startswith("## "):
                cat_name = line[3:].strip()
                if cat_name and "Morning Brief" not in cat_name:
                    category_counts[cat_name] = 0

        if hasattr(job, "add_log"):
            total_items = len(all_items)
            job.add_log(f"morning_brief completed: {total_items} raw items, {len(report)} chars")

        return {
            "summary": summary,
            "report": report,
            "artifact_path": artifact_path,
            "categories": list(interests),
            "item_count": len(all_items),
            "model_alias": MODEL_ALIAS,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")

        partial = (
            f"# Morning Brief — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            f"**⚠ Brief timed out after {MAX_RUNTIME_SECS}s.** "
            f"The process was interrupted. Results may be incomplete.\n\n"
            f"**Topics searched:** {', '.join(interests)}\n"
        )
        artifact_path = _write_artifact(partial)

        return {
            "summary": f"Brief timed out after {MAX_RUNTIME_SECS}s. Results may be incomplete.",
            "report": partial,
            "artifact_path": artifact_path,
            "categories": list(interests),
            "item_count": 0,
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")

        partial = (
            f"# Morning Brief — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            f"**⚠ Error during brief generation:** {msg}\n\n"
            f"**Topics searched:** {', '.join(interests)}\n"
        )
        artifact_path = _write_artifact(partial)

        return {
            "summary": f"Brief failed: {msg}",
            "report": partial,
            "artifact_path": artifact_path,
            "categories": list(interests),
            "item_count": 0,
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)

        partial = (
            f"# Morning Brief — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            f"**Error:** {msg}\n\n"
            f"**Topics searched:** {', '.join(interests)}\n"
        )
        artifact_path = _write_artifact(partial)

        return {
            "summary": f"Brief failed: {msg}",
            "report": partial,
            "artifact_path": artifact_path,
            "categories": list(interests),
            "item_count": 0,
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
        python skill.py --interests "technology news,artificial intelligence news"
        python skill.py --interests "technology news" --max-items 5
        python skill.py --dry-run
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="morning_brief standalone test"
    )
    parser.add_argument(
        "--interests",
        default=None,
        help="Comma-separated interest topics (default: uses skill.yml defaults)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=5,
        help="Max news items per category (default: 5)",
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
    args = parser.parse_args()

    if args.dry_run:
        interests = _resolve_interests({"interests": args.interests}, DEFAULT_INTERESTS)
        print("=== DRY RUN ===")
        print(f"  Interests ({len(interests)}):")
        for i, topic in enumerate(interests, 1):
            print(f"    {i}. {topic}")
        print(f"  Max items per category: {args.max_items}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Artifact dir: {ARTIFACT_DIR}")
        print(f"  LiteLLM: {LITELLM_BASE_URL}")
        print()
        print("  All MCP calls go through LiteLLM — no direct MCP server access")
        print("  Tool used via LiteLLM: search_news (mcp_search)")
        print()
        print("  Pipeline: search_news per topic → deduplicate → group by category → LLM synthesis → save artifact")
        return

    # Apply overrides for CLI testing
    base_url = args.base_url or LITELLM_BASE_URL
    api_key = args.api_key or LITELLM_API_KEY

    params = {
        "interests": args.interests,
        "max_items": args.max_items,
    }

    # Pass a sync LiteLLM client for standalone use
    client = _SyncLiteLLMClient(base_url=base_url, api_key=api_key)
    result = run(params, _MockJob(), litellm_client=client)

    print(f"\n--- morning_brief response ---")
    print(f"Summary: {result.get('summary', 'N/A')[:300]}")
    print(f"Categories: {result.get('categories', [])}")
    print(f"Items: {result.get('item_count', 0)}")
    if result.get("artifact_path"):
        print(f"Artifact: {result['artifact_path']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"Model: {result.get('model_alias', 'N/A')}")
    print(f"Report length: {len(result.get('report', ''))} chars")


if __name__ == "__main__":
    main()
