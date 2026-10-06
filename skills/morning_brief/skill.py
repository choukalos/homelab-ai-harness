#!/usr/bin/env python3
"""
morning_brief skill — daily "new stories" digest across configurable interest topics.

Purpose:
  Search news for each configured interest topic via LiteLLM's MCP gateway
  (mcp_search-search_news with a freshness window), track which stories have
  already been surfaced (persistent seen-store), fetch the article content of
  each NEW story (mcp_crawl-crawl_page, best-effort), and synthesize a per-story
  digest (1-2 paragraph summary + key data points + source link) via LLM.
  The final report is rendered as a self-contained, mobile-friendly HTML page
  with large tap-friendly source links and published to the public drop zone.
  All LLM/MCP traffic is routed through LiteLLM. Never touch MCP servers directly.

Workflow:
  1. Validate inputs; resolve interest topics, max_age_days, max_stories.
  2. Search news per topic via mcp_search-search_news (days=max_age_days ->
     SearXNG time_range, so only ~last-month stories are returned).
  3. Deduplicate results across topics by normalized URL.
  4. Seen-store: skip stories already surfaced in a previous run; prune
     entries older than the retention window.
  5. Cap at max_stories (round-robin across topics for diversity).
  6. Fetch each story's article content via mcp_crawl-crawl_page
     (best-effort; snippet fallback when a fetch fails — paywalls/anti-bot).
  7. Synthesize the per-story digest via LiteLLM chat completion.
  8. Save artifacts: markdown (raw digest) + HTML (rendered page).
  9. Publish the HTML to the public drop zone (single-file retention).
 10. Record surfaced stories in the seen-store.

Constraints:
  - Max runtime: 300 seconds (5 minutes).
  - Read-only w.r.t. external systems; writes only its own artifacts,
    the seen-store, and the public drop zone target.
  - All MCP calls go through LiteLLM — never direct MCP server access.
  - Freshness: stories must come from the last `max_age_days` (default 30).
  - No-repeat: stories already surfaced are tracked and not resurfaced.
  - Artifacts saved to /home/chuck/data/media/homelab_reports/
  - Public output: /home/chuck/data/media/public/briefs/latest.html
    (served at https://choukalos.com/files/briefs/latest.html)

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
import re
import signal
import sys
import threading
import time
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ARTIFACT_DIR = Path(
    os.environ.get("MORNING_BRIEF_ARTIFACT_DIR", "/home/chuck/data/media/homelab_reports")
)
# Public drop zone (single-file retention: latest digest, overwritten each run).
# Served at https://choukalos.com/files/briefs/latest.html
PUBLISH_PATH = Path(
    os.environ.get("MORNING_BRIEF_PUBLISH_PATH", "/home/chuck/data/media/public/briefs/latest.html")
)
# Public base URL for the drop zone (path is appended below /files/).
PUBLIC_BASE = os.environ.get("MORNING_BRIEF_PUBLIC_BASE", "https://choukalos.com/files")
PUBLIC_ROOT = Path(os.environ.get("MORNING_BRIEF_PUBLIC_ROOT", "/home/chuck/data/media/public"))
# Persistent seen-store: stories already surfaced, so they are not repeated.
SEEN_STORE_PATH = Path(
    os.environ.get("MORNING_BRIEF_SEEN_STORE", str(ARTIFACT_DIR / "morning_brief_seen.json"))
)
MAX_RUNTIME_SECS = int(os.environ.get("MORNING_BRIEF_MAX_RUNTIME", "300"))

# Freshness / volume defaults
DEFAULT_MAX_AGE_DAYS = 30          # "last month or so"
DEFAULT_MAX_STORIES = 6            # new stories per digest
HARD_MAX_STORIES = 10
SEEN_RETENTION_DAYS = 60           # keep seen-entries for 2 months
CRAWL_MAX_CHARS = 12000            # per-article fetch cap
CONTENT_CHARS_PER_STORY = 9000     # per-article cap inside the LLM context

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("MORNING_BRIEF_MODEL_ALIAS", "matrix-coder")

# Default interest topics from skill.yml config
DEFAULT_INTERESTS = [
    "technology news",
    "artificial intelligence news",
    "car news",
    "sports car manual transmission news",
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
                "Cannot reach LiteLLM for MCP tool %s: %s", tool_name, exc.reason
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
    """A single news story with metadata and (optionally) fetched content."""

    def __init__(
        self,
        title: str,
        url: str,
        snippet: str = "",
        source: str = "",
        category: str = "",
        published_date: str = "",
    ):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.source = source
        self.category = category  # which interest topic it was found under
        self.published_date = published_date  # ISO date (YYYY-MM-DD) when known
        self.content: Optional[str] = None  # fetched article text (None = unavailable)

    def __repr__(self):
        return f"NewsItem({self.title!r}, {self.url!r})"


# ---------------------------------------------------------------------------
# URL normalization / seen-store
# ---------------------------------------------------------------------------


def _normalize_url(url: str) -> str:
    """Normalize a URL for dedup/seen-store keys (drops query/fragment, www.)."""
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    return f"{host}{path}".lower()


# Friendly display names for common news domains (publisher fallback when the
# search engine does not report one).
_PUBLISHER_NAMES = {
    "reuters.com": "Reuters",
    "apnews.com": "AP News",
    "msn.com": "MSN",
    "bloomberg.com": "Bloomberg",
    "cnbc.com": "CNBC",
    "cnn.com": "CNN",
    "nytimes.com": "The New York Times",
    "wsj.com": "The Wall Street Journal",
    "washingtonpost.com": "The Washington Post",
    "theguardian.com": "The Guardian",
    "bbc.com": "BBC",
    "bbc.co.uk": "BBC",
    "foxnews.com": "Fox News",
    "nbcnews.com": "NBC News",
    "cbsnews.com": "CBS News",
    "abcnews.go.com": "ABC News",
    "usatoday.com": "USA Today",
    "theverge.com": "The Verge",
    "arstechnica.com": "Ars Technica",
    "techcrunch.com": "TechCrunch",
    "venturebeat.com": "VentureBeat",
    "engadget.com": "Engadget",
    "wired.com": "Wired",
    "fortune.com": "Fortune",
    "axios.com": "Axios",
    "politico.com": "Politico",
    "forbes.com": "Forbes",
    "businessinsider.com": "Business Insider",
    "theinformation.com": "The Information",
}


def _publisher_from_url(url: str) -> str:
    """Derive a publisher name from a URL (domain-based, best-effort)."""
    if not url:
        return ""
    try:
        host = urllib.parse.urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    if host in _PUBLISHER_NAMES:
        return _PUBLISHER_NAMES[host]
    parts = host.split(".")
    if len(parts) >= 2:
        domain = ".".join(parts[-2:])
        if domain in _PUBLISHER_NAMES:
            return _PUBLISHER_NAMES[domain]
        return domain
    return host


def _relative_date(iso_date: str) -> str:
    """Render an ISO date as a compact relative label ('3d ago', 'Sep 28')."""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return iso_date
    days = (datetime.now(timezone.utc).date() - d).days
    if days <= 0:
        return "today"
    if days == 1:
        return "1d ago"
    if days < 7:
        return f"{days}d ago"
    return d.strftime("%b %d")


def _friendly_source(source: str) -> str:
    """Map a bare domain (e.g. 'reuters.com') to a friendly publisher name."""
    s = (source or "").strip()
    if not s:
        return ""
    low = s.lower()
    if low.startswith("www."):
        low = low[4:]
    if low in _PUBLISHER_NAMES:
        return _PUBLISHER_NAMES[low]
    parts = low.split(".")
    if len(parts) >= 2:
        domain = ".".join(parts[-2:])
        if domain in _PUBLISHER_NAMES:
            return _PUBLISHER_NAMES[domain]
    return s


def _load_seen_store() -> dict:
    """Load the seen-store (stories already surfaced). Returns {'stories': {}} on any error."""
    try:
        if SEEN_STORE_PATH.exists():
            data = json.loads(SEEN_STORE_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("stories"), dict):
                return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load seen-store %s: %s", SEEN_STORE_PATH, exc)
    return {"version": 1, "stories": {}}


def _save_seen_store(store: dict, job=None) -> None:
    """Atomically write the seen-store."""
    try:
        store["updated_at"] = datetime.now(timezone.utc).isoformat()
        SEEN_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = SEEN_STORE_PATH.with_name(SEEN_STORE_PATH.name + ".tmp")
        tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
        os.replace(tmp, SEEN_STORE_PATH)
        if hasattr(job, "add_log"):
            job.add_log(
                f"Seen-store updated: {len(store.get('stories', {}))} tracked story(ies)"
            )
    except OSError as exc:
        logger.error("Could not save seen-store: %s", exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Warning: seen-store save failed: {exc}")


def _prune_seen_store(store: dict, retention_days: int = SEEN_RETENTION_DAYS) -> int:
    """Drop seen-entries whose last_surfaced is older than retention_days."""
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    stories = store.get("stories", {})
    pruned = 0
    for key in list(stories.keys()):
        entry = stories[key]
        last = entry.get("last_surfaced") if isinstance(entry, dict) else None
        if last:
            try:
                ts = datetime.fromisoformat(last).timestamp()
            except ValueError:
                stories.pop(key, None)
                pruned += 1
                continue
            if ts < cutoff:
                stories.pop(key)
                pruned += 1
    return pruned


# ---------------------------------------------------------------------------
# MCP wrappers — all calls go through LiteLLM
# ---------------------------------------------------------------------------


def _extract_news_items(result: Any) -> list:
    """
    Extract the list of news items from an MCP search_news response.

    Handles the raw MCP CallToolResult shape
    ({"content": [...], "structuredContent": {...}}) as well as the
    runner-normalized shape ({"result": {...}, "output": [...]}).
    """
    if not isinstance(result, dict):
        return []

    candidates: list[dict] = []
    if isinstance(result.get("structuredContent"), dict):
        candidates.append(result["structuredContent"])
    if isinstance(result.get("result"), dict):
        candidates.append(result["result"])
    candidates.append(result)

    for cand in candidates:
        for key in ("result", "results", "data", "items", "matches"):
            val = cand.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val

    # Last resort: JSON embedded in text content items
    for key in ("content", "output"):
        for item in result.get(key) or []:
            if not (isinstance(item, dict) and item.get("type") == "text"):
                continue
            try:
                parsed = json.loads(item.get("text", ""))
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return parsed
            if isinstance(parsed, dict):
                for k in ("result", "results", "data", "items", "matches"):
                    val = parsed.get(k)
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        return val
    return []


def _search_news(
    client: Any, query: str, max_results: int = 5, days: Optional[int] = None
) -> list[NewsItem]:
    """
    Search news via mcp_search-search_news through LiteLLM.

    `days` restricts results to the last N days (SearXNG time_range).
    Returns a list of NewsItem objects.
    """
    args: dict[str, Any] = {"query": query, "max_results": max_results}
    if days is not None:
        args["days"] = days
    result = client.mcp_call("search_news", args, server_id="mcp_search")
    if not result:
        logger.warning("News search returned no results for: %s", query[:100])
        return []

    items: list[NewsItem] = []
    results_list = _extract_news_items(result)

    for item in results_list:
        if len(items) >= max_results:
            break
        if isinstance(item, dict):
            url = item.get("url", "")
            source = _friendly_source(item.get("source") or _publisher_from_url(url))
            items.append(NewsItem(
                title=item.get("title", "Untitled"),
                url=url,
                snippet=item.get("snippet", item.get("content", ""))[:300],
                source=source,
                published_date=item.get("published_date", ""),
            ))

    logger.info("News search returned %d results for: %s", len(items), query[:80])
    return items


def _fetch_article(
    client: Any, url: str, max_chars: int = CRAWL_MAX_CHARS
) -> Optional[str]:
    """
    Fetch article content via mcp_crawl-crawl_page through LiteLLM (best-effort).

    Returns the article text (markdown) or None when the fetch fails
    (paywall, anti-bot, network error, non-2xx). Never raises.
    """
    if not url.startswith(("http://", "https://")):
        return None
    try:
        result = client.mcp_call(
            "crawl_page",
            {"url": url, "max_chars": max_chars},
            server_id="mcp_crawl",
        )
    except Exception as exc:  # noqa: BLE001 — best-effort fetch
        logger.warning("Crawl failed for %s: %s", url[:80], exc)
        return None
    if not isinstance(result, dict) or result.get("isError"):
        return None

    # 1) Runner-normalized / wrapped shape: {"content": "<text>"} / {"markdown": ...}
    candidates: list[dict] = []
    if isinstance(result.get("structuredContent"), dict):
        candidates.append(result["structuredContent"])
    if isinstance(result.get("result"), dict):
        candidates.append(result["result"])
    candidates.append(result)
    for cand in candidates:
        for key in ("markdown", "content"):
            val = cand.get(key)
            if isinstance(val, str) and len(val) > 200:
                return val[:max_chars]

    # 2) JSON embedded in text content items
    for item in result.get("content") or []:
        if not (isinstance(item, dict) and item.get("type") == "text"):
            continue
        text = item.get("text", "")
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text[:max_chars] if len(text) > 200 else None
        if isinstance(parsed, str) and len(parsed) > 200:
            return parsed[:max_chars]
        if isinstance(parsed, dict):
            for key in ("markdown", "content", "html"):
                val = parsed.get(key)
                if isinstance(val, str) and len(val) > 200:
                    return val[:max_chars]
    return None


# ---------------------------------------------------------------------------
# Interest resolution
# ---------------------------------------------------------------------------


def _resolve_interests(params: dict[str, Any], config_interests: list[str]) -> list[str]:
    """
    Resolve interest topics from input param or fall back to config defaults.

    Input `interests` can be:
    - A comma-separated string (most common from skill.yml input)
    - A list of strings (programmatic use)
    - Missing/empty -> use config defaults

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
# Deduplication + new-story selection
# ---------------------------------------------------------------------------


def _deduplicate_items(items: list[NewsItem]) -> list[NewsItem]:
    """Deduplicate news items by normalized URL, keeping the first occurrence."""
    seen_urls: dict[str, NewsItem] = {}

    for item in items:
        normalized_url = _normalize_url(item.url)
        if not normalized_url:
            continue
        if normalized_url not in seen_urls:
            seen_urls[normalized_url] = item

    result = list(seen_urls.values())
    logger.info("Deduplicated: %d → %d unique items", len(items), len(result))
    return result


def _select_new_stories(
    items: list[NewsItem],
    interests: list[str],
    seen_store: dict,
    max_stories: int,
    job=None,
) -> tuple[list[NewsItem], int]:
    """
    Pick the NEW stories for this digest:
    - skip stories already in the seen-store (surfaced in a previous run)
    - round-robin across interest topics (diversity) up to max_stories

    Returns (selected_items, skipped_seen_count).
    """
    seen_urls = set(seen_store.get("stories", {}).keys())
    by_topic: dict[str, list[NewsItem]] = {topic: [] for topic in interests}
    skipped_seen = 0

    for item in items:
        key = _normalize_url(item.url)
        if key in seen_urls:
            skipped_seen += 1
            continue
        topic = item.category if item.category in by_topic else interests[0]
        by_topic[topic].append(item)

    selected: list[NewsItem] = []
    while len(selected) < max_stories:
        added = False
        for topic in interests:
            if len(selected) >= max_stories:
                break
            if by_topic[topic]:
                selected.append(by_topic[topic].pop(0))
                added = True
        if not added:
            break

    if hasattr(job, "add_log"):
        job.add_log(
            f"Story selection: {len(selected)} new story(ies) selected, "
            f"{skipped_seen} skipped (already surfaced before)"
        )
    return selected, skipped_seen


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a news digest assistant producing a "new stories" digest.

    You will be given NEW news stories (all published within the last N days),
    each with a headline, source, URL, and — where available — the fetched
    article content.

    For EACH story, produce a section in EXACTLY this structure:

    ## <story headline>
    **Source:** [Publisher name](story URL)

    <1-2 paragraph summary: what happened, who is involved, and why it matters.
    60-120 words total.>

    **Key data points:**
    - <concrete fact, number, date, price, or quote from the article>
    - <another concrete point>

    Rules:
    - One section per story, in the order given. Do not merge or reorder stories.
    - Write the summary fresh — do not just restate the headline or snippet.
    - 2-4 key data points per story. Every data point must be a concrete,
      verifiable fact from the provided content (numbers, dates, names, prices,
      percentages). No filler, no opinions.
    - If a story's article content is marked as unavailable, write the summary
      from the headline and snippet only, and add the line
      "(article could not be fetched — summary based on headline and snippet)"
      directly after the Source line.
    - Never invent facts, numbers, or quotes that are not in the provided content.
    - Use the exact URL provided for each story's Source link.
    - Use the source name given for each story in the Source line exactly as
      provided (never write "unknown" when a source name is given).
    - Output ONLY the markdown digest — no preamble, no trailing commentary,
      no wrapping code fences.
""")


def _build_digest_context(
    stories: list[NewsItem],
    max_age_days: int,
) -> str:
    """Build the per-story context string for the LLM synthesis."""
    lines = [
        f"Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        f"All stories below were published within the last {max_age_days} days.",
        f"Write a digest section for each of the {len(stories)} story(ies) below.",
        "",
    ]
    for i, item in enumerate(stories, 1):
        lines.append(f"### Story {i}")
        lines.append(f"Headline: {item.title.strip()}")
        source = item.source if item.source and item.source.lower() != "news" else ""
        lines.append(f"Source: {source or 'unknown'}")
        if item.published_date:
            lines.append(f"Published: {item.published_date}")
        lines.append(f"URL: {item.url}")
        if item.category:
            lines.append(f"Topic: {item.category}")
        if item.content:
            lines.append("Article content (truncated):")
            lines.append(item.content[:CONTENT_CHARS_PER_STORY])
            lines.append("")
        else:
            lines.append("Article content: UNAVAILABLE (fetch failed)")
            if item.snippet:
                lines.append(f"Snippet: {item.snippet}")
            lines.append("")
    return "\n".join(lines)


def _memory_block(job, interests: list[str]) -> str:
    """Build the ``<long_term_memory>`` block for the morning brief (Phase 7).

    Retrieves the caller's durable facts relevant to personalizing the
    brief (preferences, schedule, standing interests). Identity comes
    from the Job; the per-request switch is ``job.memory_enabled``.
    Non-fatal: any failure degrades to "" so the brief is never broken
    by memory. The memory package is imported lazily so the skill stays
    importable standalone (importlib, stdlib-only by design).
    """
    if not interests:
        return ""
    try:
        from memory import jobctx  # lazy
        query = "personalize morning brief for interests: " + ", ".join(interests)
        return jobctx.retrieve(job, query)
    except Exception as exc:  # noqa: BLE001 — never break the skill
        if hasattr(job, "add_log"):
            job.add_log(f"Memory context unavailable (non-fatal): {exc}")
        return ""


def _strip_code_fence(text: str) -> str:
    """Strip a wrapping ```markdown ... ``` fence if the LLM added one."""
    text = text.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*?)\n?```\s*$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _synthesize_digest(
    client: Any,
    stories: list[NewsItem],
    max_age_days: int,
    job=None,
) -> str:
    """Synthesize the per-story digest via LLM chat completion through LiteLLM."""
    context = _build_digest_context(stories, max_age_days)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]

    # Phase 7 — memory retrieval: personalize the digest with the caller's
    # durable facts. Identity comes from the Job (user_id/run_id); gated by
    # job.memory_enabled; non-fatal (no block on error). A scheduled job runs
    # under the 'service' identity, which has no personal memory, so this is a
    # no-op there — a user-triggered digest inherits the user.
    mem_block = _memory_block(job, [s.category for s in stories if s.category])
    if mem_block:
        messages[0] = {
            "role": "system",
            "content": messages[0]["content"] + "\n\n" + mem_block,
        }

    def _call_once() -> tuple[Optional[str], str]:
        """One LLM call -> (content, finish_reason)."""
        result = client.chat_completion(
            MODEL_ALIAS,
            messages,
            max_tokens=16000,
            temperature=0.3,
            stream=False,
        )
        choices = result.get("choices", []) if isinstance(result, dict) else []
        if not choices:
            return None, "no_choices"
        message = choices[0].get("message") or {}
        finish = str(choices[0].get("finish_reason") or "")
        return message.get("content") or None, finish

    # Reasoning models can burn the token budget on reasoning_content and
    # return empty visible content; retry once before giving up.
    content, finish = _call_once()
    if not content:
        if hasattr(job, "add_log"):
            job.add_log(f"LLM returned empty content (finish_reason={finish}) — retrying once")
        content, finish = _call_once()

    if not content:
        if hasattr(job, "add_log"):
            job.add_log(f"LLM retry also returned empty content (finish_reason={finish})")
        hint = (
            f" (finish_reason={finish}; the model likely spent its token budget on "
            "internal reasoning)"
            if finish in ("length", "no_choices") else ""
        )
        return (
            f"# New Stories — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            f"**No digest generated.** LLM returned empty content{hint}.\n"
        )
    return _strip_code_fence(content)


# ---------------------------------------------------------------------------
# Markdown → HTML rendering (stdlib only — no markdown lib in the container)
# ---------------------------------------------------------------------------


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _md_inline(text: str) -> str:
    """
    Convert inline markdown to HTML. Input is RAW (unescaped); the function
    escapes first, then applies link/bold/italic/code substitutions.
    """
    out = _escape_html(text)
    # Inline code (protect its contents from further substitution)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    # Links: [text](url)
    out = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>',
        out,
    )
    # Bold
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    # Italic (single stars left over after bold)
    out = re.sub(r"(^|[^*])\*([^*\n]+)\*", r"\1<em>\2</em>", out)
    return out


def _md_to_html(md: str) -> str:
    """
    Convert a markdown subset (headings, paragraphs, lists, blockquotes,
    hr, code fences, inline formatting) to HTML. Line-based state machine.
    """
    lines = md.splitlines()
    out: list[str] = []
    para: list[str] = []
    in_ul = False
    in_ol = False
    in_quote = False
    i = 0

    def flush_para():
        nonlocal para
        if para:
            out.append(f"<p>{_md_inline(' '.join(para))}</p>")
            para = []

    def close_lists():
        nonlocal in_ul, in_ol, in_quote
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False
        if in_quote:
            out.append("</blockquote>")
            in_quote = False

    while i < len(lines):
        raw = lines[i].rstrip()
        stripped = raw.strip()

        # Code fence
        if stripped.startswith("```"):
            flush_para()
            close_lists()
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            out.append(f"<pre><code>{_escape_html(chr(10).join(code))}</code></pre>")
            continue

        # Blank line
        if not stripped:
            flush_para()
            close_lists()
            i += 1
            continue

        # Heading
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            close_lists()
            level = len(m.group(1))
            out.append(f"<h{level}>{_md_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para()
            close_lists()
            out.append("<hr>")
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            flush_para()
            if in_ul or in_ol:
                close_lists()
            if not in_quote:
                out.append("<blockquote>")
                in_quote = True
            out.append(f"<p>{_md_inline(stripped.lstrip('>').strip())}</p>")
            i += 1
            continue

        # Unordered list item
        m = re.match(r"^[-*+]\s+(.*)$", stripped)
        if m:
            flush_para()
            if in_ol:
                close_lists()
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_md_inline(m.group(1))}</li>")
            i += 1
            continue

        # Ordered list item
        m = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if m:
            flush_para()
            if in_ul:
                close_lists()
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_md_inline(m.group(1))}</li>")
            i += 1
            continue

        # Paragraph line
        para.append(stripped)
        i += 1

    flush_para()
    close_lists()
    return "\n".join(out)


# --- Story-card rendering (structured parse of the digest) -----------------

_STORY_URL_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _story_card_html(
    headline: str,
    url: str,
    publisher: str,
    body_html: str,
    data_points: list[str],
    published_date: str = "",
) -> str:
    """Render one story card with a large tap-friendly source link."""
    parts = ['<article class="story">']
    headline_html = _escape_html(headline)
    if url:
        parts.append(
            f'<h2><a href="{_escape_html(url)}" target="_blank" rel="noopener">'
            f"{headline_html}</a></h2>"
        )
    else:
        parts.append(f"<h2>{headline_html}</h2>")
    badges = []
    if publisher and publisher.lower() != "unknown":
        badges.append(f'<span class="badge src">{_escape_html(publisher)}</span>')
    if published_date:
        badges.append(
            f'<span class="badge date">{_escape_html(_relative_date(published_date))}</span>'
        )
    if badges:
        parts.append(f'<div class="badges">{"".join(badges)}</div>')
    if body_html:
        parts.append(body_html)
    if data_points:
        lis = "\n".join(f"<li>{_md_inline(p)}</li>" for p in data_points)
        parts.append(
            f'<div class="datapoints"><span class="label">Key data points</span>'
            f"<ul>{lis}</ul></div>"
        )
    if url:
        parts.append(
            f'<a class="readlink" href="{_escape_html(url)}" target="_blank" rel="noopener">'
            "Read the full story &rarr;</a>"
        )
    parts.append("</article>")
    return "\n".join(parts)


def _render_story_cards(md: str, stories: Optional[list] = None) -> tuple[str, int]:
    """
    Parse the digest markdown into story cards.

    Each story is a `## <headline>` block containing a
    `**Source:** [Publisher](url)` line, 1-2 paragraphs, and a
    `**Key data points:**` bullet list. Returns (cards_html, story_count).
    Returns ("", 0) when no story blocks are found (caller falls back to
    generic markdown rendering).
    """
    blocks = re.split(r"(?m)^##\s+", md)
    cards: list[str] = []

    for block in blocks[1:]:
        lines = block.splitlines()
        if not lines:
            continue
        headline = lines[0].strip()
        if not headline:
            continue

        # Source URL + publisher: prefer the **Source:** line, else first link
        source_line = next(
            (ln for ln in lines[1:] if ln.strip().lower().startswith("**source:**")),
            "",
        )
        link = _STORY_URL_RE.search(source_line) or _STORY_URL_RE.search(block)
        url = link.group(2) if link else ""
        publisher = link.group(1) if link else ""
        published_date = ""
        if stories:
            meta = next(
                (s for s in stories if _normalize_url(s.url) == _normalize_url(url)),
                None,
            )
            if meta is not None:
                published_date = getattr(meta, "published_date", "") or ""
                if not publisher or publisher.lower() == "unknown":
                    publisher = getattr(meta, "source", "") or publisher

        # Split body vs key data points
        body_lines: list[str] = []
        data_points: list[str] = []
        in_data = False
        for ln in lines[1:]:
            s = ln.strip()
            if not s:
                continue
            if re.search(r"key\s*data\s*points?", s, re.IGNORECASE):
                in_data = True
                continue
            if in_data:
                dm = re.match(r"^[-*+]\s+(.*)$", s)
                if dm:
                    data_points.append(dm.group(1))
                    continue
                in_data = False  # non-list line ends the data-points list
            if s.lower().startswith("**source:**"):
                continue  # rendered as the badge instead
            body_lines.append(s)

        body_html = _md_to_html("\n".join(body_lines))
        cards.append(
            _story_card_html(headline, url, publisher, body_html, data_points, published_date)
        )

    if not cards:
        return "", 0
    return "\n".join(cards), len(cards)


# --- Full HTML document -----------------------------------------------------

_HTML_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 16px;
  background: #f4f5f7; color: #1a1d21;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  line-height: 1.55; font-size: 16px; -webkit-text-size-adjust: 100%;
}
.wrap { max-width: 720px; margin: 0 auto; padding: 24px 0 40px; }
header.brief h1 { font-size: 1.65rem; margin: 0 0 4px; line-height: 1.25; }
.meta { color: #5a6472; font-size: 0.95rem; margin: 0 0 4px; }
.story {
  background: #ffffff; border: 1px solid #e2e5ea; border-radius: 14px;
  padding: 20px 20px 16px; margin: 18px 0;
  box-shadow: 0 1px 3px rgba(16,24,40,0.05);
}
.story h2 { font-size: 1.22rem; margin: 0 0 8px; line-height: 1.3; }
.story h2 a { color: inherit; text-decoration: none; }
.story h2 a:hover, .story h2 a:active { text-decoration: underline; }
.badges { margin: 0 0 10px; display: flex; gap: 8px; flex-wrap: wrap; }
.badge {
  font-size: 0.74rem; font-weight: 700; letter-spacing: 0.03em;
  padding: 3px 10px; border-radius: 999px;
  background: #eef2ff; color: #3b4a9f; text-transform: uppercase;
}
.badge.src { background: #e7f6ee; color: #0a7a4b; text-transform: none; }
.badge.date { background: #f3f4f6; color: #6b7280; text-transform: none; font-weight: 600; }
.story p { margin: 8px 0; }
.datapoints { margin: 10px 0 2px; }
.datapoints .label { display: block; margin-bottom: 4px; font-weight: 700; font-size: 0.9rem; color: #374151; }
.datapoints ul { margin: 0; padding-left: 20px; }
.datapoints li { margin: 4px 0; }
.readlink {
  display: flex; align-items: center; justify-content: center;
  min-height: 52px; margin-top: 14px; padding: 13px 16px;
  background: #111827; color: #ffffff !important;
  font-weight: 700; font-size: 1rem; text-decoration: none; border-radius: 10px;
}
.readlink:hover, .readlink:active { background: #374151; }
a { color: #1d4ed8; }
code { background: #f0f1f3; padding: 1px 5px; border-radius: 4px; font-size: 0.9em; }
blockquote { margin: 8px 0; padding: 8px 14px; border-left: 3px solid #cbd5e1; color: #4a5569; background: #fafbfc; }
hr { border: none; border-top: 1px solid #e2e5ea; margin: 18px 0; }
footer { margin-top: 28px; color: #8a94a3; font-size: 0.8rem; text-align: center; }
@media (prefers-color-scheme: dark) {
  body { background: #0f1216; color: #e6e8eb; }
  .meta, footer { color: #9aa3af; }
  .story { background: #171b21; border-color: #262c35; box-shadow: none; }
  .badge { background: #232c4d; color: #aab8ff; }
  .badge.src { background: #123527; color: #7fd6a8; }
.badge.date { background: #262b33; color: #9aa3af; }
  .datapoints .label { color: #cbd5e1; }
  .readlink { background: #e6e8eb; color: #111827 !important; }
  .readlink:hover, .readlink:active { background: #c9ccd2; }
  a { color: #7aa6ff; }
  code { background: #232830; }
  blockquote { background: #171b21; border-left-color: #3a424e; color: #94a3b8; }
  hr { border-top-color: #262c35; }
}
"""


def _html_document(title: str, meta_line: str, body_html: str) -> str:
    """Wrap body HTML in a self-contained, mobile-friendly document."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    meta = f'<p class="meta">{_escape_html(meta_line)}</p>' if meta_line else ""
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_escape_html(title)}</title>\n"
        f"<style>{_HTML_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="wrap">\n'
        f"<header class=\"brief\">\n<h1>{_escape_html(title)}</h1>\n{meta}\n</header>\n"
        f"{body_html}\n"
        f'<footer>Generated {now} by the daily morning brief skill. '
        "Stories are limited to the freshness window and are not repeated once surfaced.</footer>\n"
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )


def _render_report_html(
    report_md: str, title: str, meta_line: str, stories: Optional[list] = None
) -> str:
    """
    Render the markdown report to the final HTML page.

    Story digests are parsed into story cards (big tap-friendly source links);
    fallback reports (no results / error / timeout) use generic markdown
    rendering.
    """
    cards, count = _render_story_cards(report_md, stories)
    if count:
        body = cards
    else:
        body = f"<div>{_md_to_html(report_md)}</div>"
    return _html_document(title, meta_line, body)


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _write_artifact(report: str, ext: str = "md") -> Optional[str]:
    """Save the report as an artifact file (.md raw or .html rendered)."""
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"morning_brief_{ts}.{ext}"
        path = ARTIFACT_DIR / filename
        path.write_text(report, encoding="utf-8")
        logger.info("Artifact written: %s", path)
        return str(path)
    except OSError as exc:
        logger.error("Could not write artifact: %s", exc)
        return None


def _publish_report(html: str, publish_path: Path, job) -> Optional[str]:
    """
    Atomically publish the HTML digest to the public drop zone.

    Single-file retention: the target is overwritten on every run, so the
    public folder always holds exactly one digest (the latest).
    """
    try:
        publish_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = publish_path.with_name(publish_path.name + ".tmp")
        tmp.write_text(html, encoding="utf-8")
        os.replace(tmp, publish_path)  # atomic on POSIX
        logger.info("Digest published: %s", publish_path)
        if hasattr(job, "add_log"):
            job.add_log(f"Published to {publish_path}")
        return str(publish_path)
    except OSError as exc:
        logger.error("Could not publish digest to %s: %s", publish_path, exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Publish FAILED ({publish_path}): {exc}")
        return None


def _public_url(publish_path: Path) -> str:
    """Map a public-drop-zone path to its https URL."""
    try:
        rel = publish_path.resolve().relative_to(PUBLIC_ROOT.resolve())
        return f"{PUBLIC_BASE}/{rel.as_posix()}"
    except (ValueError, OSError):
        return f"{PUBLIC_BASE}/briefs/{publish_path.name}"


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
        params: Skill parameters (interests, max_items, max_age_days,
                max_stories, publish, publish_path).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.

    Returns:
        Dict with 'summary', 'report', 'artifact_path', 'html_artifact_path',
        'published_path', 'published_url', 'categories', 'item_count',
        'stories_surfaced', 'stories_skipped_seen', 'max_age_days'.
    """
    # Resolve LiteLLM client (sync interface guaranteed)
    client = _resolve_litellm_client(litellm_client)

    # Resolve interest topics from input or config defaults
    interests = _resolve_interests(params, DEFAULT_INTERESTS)

    # Freshness window (days) — stories must be from the last N days
    max_age_days = params.get("max_age_days", DEFAULT_MAX_AGE_DAYS)
    try:
        max_age_days = int(max_age_days)
    except (TypeError, ValueError):
        max_age_days = DEFAULT_MAX_AGE_DAYS
    max_age_days = max(1, min(max_age_days, 365))

    # Per-topic search depth (kept for backward compatibility with `max_items`)
    max_items = params.get("max_items", DEFAULT_MAX_STORIES)
    if not isinstance(max_items, int) or max_items < 1:
        max_items = DEFAULT_MAX_STORIES
    max_items = min(max_items, HARD_MAX_STORIES)

    # Cap on new stories surfaced in the digest
    max_stories = params.get("max_stories", DEFAULT_MAX_STORIES)
    try:
        max_stories = int(max_stories)
    except (TypeError, ValueError):
        max_stories = DEFAULT_MAX_STORIES
    max_stories = max(1, min(max_stories, HARD_MAX_STORIES))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"New Stories — {today}"

    if hasattr(job, "add_log"):
        job.add_log(
            f"Executing morning_brief: {len(interests)} interest topic(s), "
            f"max_age_days={max_age_days}, max_stories={max_stories}"
        )
        job.add_log(f"Interests: {', '.join(interests)}")
        job.add_log(f"Model alias: {MODEL_ALIAS}")

    _install_timeout()
    try:
        # ---- Phase 1: search news per topic (freshness-filtered) ----
        all_items: list[NewsItem] = []
        for topic in interests:
            if hasattr(job, "add_log"):
                job.add_log(f"Searching news: {topic} (last {max_age_days} days)")
            items = _search_news(client, topic, max_results=max_items, days=max_age_days)
            for item in items:
                item.category = topic
            all_items.extend(items)

        if hasattr(job, "add_log"):
            job.add_log(f"Total raw news items across topics: {len(all_items)}")

        # ---- No results: publish a fallback report ----
        if not all_items:
            report = (
                f"# {title}\n\n"
                f"**No new stories found.** The search returned no results "
                f"published within the last {max_age_days} days for the "
                "configured interest topics.\n\n"
                f"**Topics searched:** {', '.join(interests)}\n"
            )
            html = _render_report_html(report, title, f"0 new stories · last {max_age_days} days")
            artifact_path = _write_artifact(report)
            html_artifact_path = _write_artifact(html, "html")
            published_path = None
            published_url = None
            if params.get("publish"):
                target = Path(params.get("publish_path", str(PUBLISH_PATH)))
                published_path = _publish_report(html, target, job)
                if published_path:
                    published_url = _public_url(Path(published_path))
            return {
                "summary": "No new stories found in the last "
                           f"{max_age_days} days across {len(interests)} topic(s).",
                "report": report,
                "artifact_path": artifact_path,
                "html_artifact_path": html_artifact_path,
                "published_path": published_path,
                "published_url": published_url,
                "categories": interests,
                "item_count": 0,
                "stories_surfaced": 0,
                "stories_skipped_seen": 0,
                "max_age_days": max_age_days,
            }

        # ---- Phase 2: deduplicate across topics ----
        unique_items = _deduplicate_items(all_items)

        # ---- Phase 3: seen-store — skip stories already surfaced ----
        seen_store = _load_seen_store()
        pruned = _prune_seen_store(seen_store)
        if pruned and hasattr(job, "add_log"):
            job.add_log(f"Seen-store pruned {pruned} stale entr(ies)")
        stories, skipped_seen = _select_new_stories(
            unique_items, interests, seen_store, max_stories, job
        )

        # ---- Nothing new: publish a fallback report ----
        if not stories:
            report = (
                f"# {title}\n\n"
                f"**No new stories this run.** All {len(unique_items)} story(ies) "
                f"found (published within the last {max_age_days} days) were "
                "already surfaced in a previous digest. Nothing new to report.\n\n"
                f"**Topics searched:** {', '.join(interests)}\n"
            )
            html = _render_report_html(report, title, f"0 new stories · last {max_age_days} days")
            artifact_path = _write_artifact(report)
            html_artifact_path = _write_artifact(html, "html")
            published_path = None
            published_url = None
            if params.get("publish"):
                target = Path(params.get("publish_path", str(PUBLISH_PATH)))
                published_path = _publish_report(html, target, job)
                if published_path:
                    published_url = _public_url(Path(published_path))
            return {
                "summary": f"No new stories: {skipped_seen} found were already surfaced before.",
                "report": report,
                "artifact_path": artifact_path,
                "html_artifact_path": html_artifact_path,
                "published_path": published_path,
                "published_url": published_url,
                "categories": interests,
                "item_count": len(unique_items),
                "stories_surfaced": 0,
                "stories_skipped_seen": skipped_seen,
                "max_age_days": max_age_days,
            }

        # ---- Phase 4: fetch article content (best-effort, deadline-aware) ----
        # Reserve time for LLM synthesis + publish; stop fetching when the
        # budget is reached (remaining stories fall back to snippet-only).
        deadline = time.monotonic() + MAX_RUNTIME_SECS - 75
        fetched = 0
        for item in stories:
            if time.monotonic() > deadline:
                if hasattr(job, "add_log"):
                    job.add_log("Time budget reached — remaining stories use snippet only")
                break
            if hasattr(job, "add_log"):
                job.add_log(f"Fetching article: {item.url[:100]}")
            item.content = _fetch_article(client, item.url)
            if item.content:
                fetched += 1
            if hasattr(job, "add_log"):
                job.add_log(
                    f"  → {'fetched ' + str(len(item.content)) + ' chars' if item.content else 'fetch failed (snippet fallback)'}"
                )
        if hasattr(job, "add_log"):
            job.add_log(f"Article fetch: {fetched}/{len(stories)} succeeded")

        # ---- Phase 5: synthesize the per-story digest via LLM ----
        if hasattr(job, "add_log"):
            job.add_log("Synthesizing per-story digest via LLM...")
        report = _synthesize_digest(client, stories, max_age_days, job)
        if hasattr(job, "add_log"):
            job.add_log(f"Digest generated ({len(report)} chars)")

        # ---- Phase 6: render HTML + save artifacts ----
        meta_line = f"{len(stories)} new stories · last {max_age_days} days"
        html = _render_report_html(report, title, meta_line, stories)
        artifact_path = _write_artifact(report)
        html_artifact_path = _write_artifact(html, "html")

        # ---- Phase 7: publish HTML to the public drop zone ----
        published_path = None
        published_url = None
        if params.get("publish"):
            target = Path(params.get("publish_path", str(PUBLISH_PATH)))
            published_path = _publish_report(html, target, job)
            if published_path:
                published_url = _public_url(Path(published_path))

        # ---- Phase 8: record surfaced stories in the seen-store ----
        # Only mark stories as surfaced when the digest actually rendered
        # them (a broken/empty digest must not consume the stories).
        digest_ok = any(ln.startswith("## ") for ln in report.splitlines())
        if digest_ok:
            now_iso = datetime.now(timezone.utc).isoformat()
            for item in stories:
                key = _normalize_url(item.url)
                if not key:
                    continue
                entry = seen_store["stories"].setdefault(
                    key, {"title": item.title, "first_seen": now_iso}
                )
                entry["last_surfaced"] = now_iso
                entry["title"] = item.title
                if item.category:
                    entry["category"] = item.category
            _save_seen_store(seen_store, job)
        elif hasattr(job, "add_log"):
            job.add_log("Digest has no story sections — seen-store NOT updated")

        # Summary: story count + first headline
        first_headline = next(
            (ln.lstrip("# ").strip() for ln in report.splitlines() if ln.startswith("## ")),
            "",
        )
        summary = f"{len(stories)} new stories" + (f": {first_headline}" if first_headline else "")

        return {
            "summary": summary[:300],
            "report": report,
            "artifact_path": artifact_path,
            "html_artifact_path": html_artifact_path,
            "published_path": published_path,
            "published_url": published_url,
            "categories": interests,
            "item_count": len(unique_items),
            "stories_surfaced": len(stories),
            "stories_skipped_seen": skipped_seen,
            "max_age_days": max_age_days,
        }

    except TimeoutError as exc:
        report = (
            f"# {title}\n\n"
            f"## ⚠️ **Timeout** — the morning brief could not complete.\n\n"
            f"The skill exceeded its {MAX_RUNTIME_SECS}s max runtime. "
            "Partial results may be available in the artifact directory.\n"
        )
        html = _render_report_html(report, title, "timeout")
        artifact_path = _write_artifact(report)
        html_artifact_path = _write_artifact(html, "html")
        published_path = None
        published_url = None
        if params.get("publish"):
            target = Path(params.get("publish_path", str(PUBLISH_PATH)))
            published_path = _publish_report(html, target, job)
            if published_path:
                published_url = _public_url(Path(published_path))
        return {
            "summary": f"morning_brief timed out after {MAX_RUNTIME_SECS}s",
            "report": report,
            "artifact_path": artifact_path,
            "html_artifact_path": html_artifact_path,
            "published_path": published_path,
            "published_url": published_url,
            "categories": interests,
            "item_count": 0,
            "stories_surfaced": 0,
            "stories_skipped_seen": 0,
            "max_age_days": max_age_days,
        }

    except RuntimeError as exc:
        report = (
            f"# {title}\n\n"
            f"## ⚠️ **Error** — the morning brief could not be generated.\n\n"
            f"LiteLLM error: {type(exc).__name__}: {exc}\n\n"
            "Check the LiteLLM proxy status and try again.\n"
        )
        html = _render_report_html(report, title, "error")
        artifact_path = _write_artifact(report)
        html_artifact_path = _write_artifact(html, "html")
        published_path = None
        published_url = None
        if params.get("publish"):
            target = Path(params.get("publish_path", str(PUBLISH_PATH)))
            published_path = _publish_report(html, target, job)
            if published_path:
                published_url = _public_url(Path(published_path))
        return {
            "summary": f"morning_brief failed: {type(exc).__name__}: {exc}",
            "report": report,
            "artifact_path": artifact_path,
            "html_artifact_path": html_artifact_path,
            "published_path": published_path,
            "published_url": published_url,
            "categories": interests,
            "item_count": 0,
            "stories_surfaced": 0,
            "stories_skipped_seen": 0,
            "max_age_days": max_age_days,
        }

    except Exception as exc:  # noqa: BLE001 — catch-all for graceful degradation
        report = (
            f"# {title}\n\n"
            f"## ⚠️ **Error** — the morning brief could not be generated.\n\n"
            f"An unexpected error occurred: {type(exc).__name__}: {exc}\n\n"
            "Check the skill logs and try again.\n"
        )
        html = _render_report_html(report, title, "error")
        artifact_path = _write_artifact(report)
        html_artifact_path = _write_artifact(html, "html")
        published_path = None
        published_url = None
        if params.get("publish"):
            target = Path(params.get("publish_path", str(PUBLISH_PATH)))
            published_path = _publish_report(html, target, job)
            if published_path:
                published_url = _public_url(Path(published_path))
        return {
            "summary": f"morning_brief failed: {type(exc).__name__}: {exc}",
            "report": report,
            "artifact_path": artifact_path,
            "html_artifact_path": html_artifact_path,
            "published_path": published_path,
            "published_url": published_url,
            "categories": interests,
            "item_count": 0,
            "stories_surfaced": 0,
            "stories_skipped_seen": 0,
            "max_age_days": max_age_days,
        }

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# CLI entrypoint (standalone testing)
# ---------------------------------------------------------------------------


def main() -> None:
    """Standalone CLI for testing the morning_brief skill."""
    import argparse

    parser = argparse.ArgumentParser(description="morning_brief skill (standalone)")
    parser.add_argument("--interests", default="", help="Comma-separated interest topics")
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_STORIES,
                        help="Per-topic search depth (default: %(default)s)")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS,
                        help="Only stories published in the last N days (default: %(default)s)")
    parser.add_argument("--max-stories", type=int, default=DEFAULT_MAX_STORIES,
                        help="Max new stories to surface (default: %(default)s)")
    parser.add_argument("--publish", action="store_true", default=False,
                        help="Publish the HTML digest to the public drop zone")
    parser.add_argument("--publish-path", default=str(PUBLISH_PATH),
                        help="Publish target (default: %(default)s)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show resolved config without executing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    params: dict[str, Any] = {
        "max_items": args.max_items,
        "max_age_days": args.max_age_days,
        "max_stories": args.max_stories,
        "publish": args.publish,
        "publish_path": args.publish_path,
    }
    if args.interests:
        params["interests"] = args.interests

    if args.dry_run:
        print("Resolved configuration:")
        print(f"  interests:      {_resolve_interests(params, DEFAULT_INTERESTS)}")
        print(f"  max_items:      {params['max_items']}")
        print(f"  max_age_days:   {params['max_age_days']}")
        print(f"  max_stories:    {params['max_stories']}")
        print(f"  publish:        {args.publish}")
        print(f"  publish_path:   {args.publish_path}")
        print(f"  model_alias:    {MODEL_ALIAS}")
        print(f"  litellm:        {LITELLM_BASE_URL}")
        print(f"  artifact_dir:   {ARTIFACT_DIR}")
        print(f"  seen_store:     {SEEN_STORE_PATH}")
        return

    class _CLIJob:
        def add_log(self, msg: str) -> None:
            print(f"[log] {msg}")

    job = _CLIJob()
    result = run(params, job)

    print("\n" + "=" * 70)
    print("SUMMARY:")
    print(f"  {result['summary']}")
    print(f"  stories_surfaced:     {result.get('stories_surfaced')}")
    print(f"  stories_skipped_seen: {result.get('stories_skipped_seen')}")
    print(f"  artifact_path:        {result.get('artifact_path')}")
    print(f"  html_artifact_path:   {result.get('html_artifact_path')}")
    print(f"  published_path:       {result.get('published_path')}")
    print(f"  published_url:        {result.get('published_url')}")
    print("=" * 70)

    if result.get("report"):
        print("\nREPORT:\n")
        print(result["report"])


if __name__ == "__main__":
    main()