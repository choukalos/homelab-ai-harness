#!/usr/bin/env python3
"""
market_research_brief skill — market research brief for a configured market.

Purpose:
  For a market profile (profiles/<market>.yml), gather research material for
  the last N days (default 30):
  - Per-competitor news (mcp_search-search_news, freshness-filtered)
  - Broad seed-query news (market-level sweep)
  - Market size / market share findings (mcp_search-search_web, free sources)
  - Analyst-firm activity (e.g. Parks Associates, Gartner — free coverage only)
  - Owner context: long-term memory (memory.jobctx) + family KB
    (mcp_knowledge-kb_search)
  Then synthesize a structured market research brief via LLM (LiteLLM):
  executive summary, market size & share, per-competitor scan (last month's
  moves + trend line), analyst watch, trends & outlook. Render as a
  self-contained mobile-friendly HTML page.

Retention & cadence:
  - Timestamped artifacts (.md + .html) are KEPT (no pruning) so a few years
    of monthly briefs accumulate for trend analysis.
  - On the January run (profile `yearly_month`), a yearly summary is
    synthesized from the last 12 distinct monthly briefs and published.
  - Publishing (publish=true): the latest brief overwrites
    <public>/briefs/<slug>.html, plus a dated copy
    <public>/briefs/market_research/<slug>_YYYY-MM.html (last 3 dated copies
    retained per market). Yearly summaries publish to
    <public>/briefs/<slug>_yearly_<label>.html (all retained).

Constraints:
  - Max runtime: 600 seconds.
  - All LLM/MCP traffic is routed through LiteLLM. Never touch MCP servers
    directly.
  - Free sources only: paywalled analyst data (Parks Associates, Gartner) is
    referenced via free press coverage and explicitly flagged — never
    fabricated.
  - Artifacts: /home/chuck/data/media/market_research_briefs/
  - Public output: /home/chuck/data/media/public/briefs/ (blog drop zone,
    served at https://choukalos.com/files/briefs/)

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
    os.environ.get(
        "MARKET_RESEARCH_BRIEF_ARTIFACT_DIR",
        "/home/chuck/data/media/market_research_briefs",
    )
)
PROFILES_DIR = Path(
    os.environ.get(
        "MARKET_RESEARCH_BRIEF_PROFILES_DIR",
        str(Path(__file__).resolve().parent / "profiles"),
    )
)
# Public blog drop zone (served at https://choukalos.com/files/).
PUBLIC_ROOT = Path(
    os.environ.get("MARKET_RESEARCH_BRIEF_PUBLIC_ROOT", "/home/chuck/data/media/public")
)
PUBLIC_BASE = os.environ.get("MARKET_RESEARCH_BRIEF_PUBLIC_BASE", "https://choukalos.com/files")
# Dated copies live under <public>/briefs/market_research/<slug>_YYYY-MM.html.
DATED_DIRNAME = os.environ.get("MARKET_RESEARCH_BRIEF_DATED_DIR", "market_research")
# Keep only the last N dated copies per market on the blog ("when we get
# there" — pruning is a no-op until 4 exist).
DATED_RETENTION = int(os.environ.get("MARKET_RESEARCH_BRIEF_DATED_RETENTION", "3"))
# Yearly summary: generated on the run whose UTC month == YEARLY_MONTH, from
# the last 12 distinct monthly briefs (needs >= YEARLY_MIN_BRIEFS).
YEARLY_MONTH = int(os.environ.get("MARKET_RESEARCH_BRIEF_YEARLY_MONTH", "1"))
YEARLY_MIN_BRIEFS = int(os.environ.get("MARKET_RESEARCH_BRIEF_YEARLY_MIN_BRIEFS", "12"))
# Per-monthly-brief truncation inside the yearly-summary LLM context.
YEARLY_BRIEF_CHARS = 4000

MAX_RUNTIME_SECS = int(os.environ.get("MARKET_RESEARCH_BRIEF_MAX_RUNTIME", "600"))

# Volume / freshness defaults
DEFAULT_PERIOD_DAYS = 30
DEFAULT_MAX_ITEMS = 5
HARD_MAX_ITEMS = 10
COMPETITOR_SNIPPET_CHARS = 300
MARKET_SNIPPET_CHARS = 400
KB_TOP_K = 5
KB_SNIPPET_CHARS = 500

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("MARKET_RESEARCH_BRIEF_MODEL_ALIAS", "matrix-coder")

logger = logging.getLogger("skill.market_research_brief")

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("MARKET_RESEARCH_BRIEF_MODEL_ALIAS", "matrix-coder")

# Research volume defaults
DEFAULT_PERIOD_DAYS = 30            # "last month"
DEFAULT_MAX_ITEMS = 5               # per query
HARD_MAX_ITEMS = 10
COMPETITOR_SNIPPET_CHARS = 300      # per news item in the LLM context
MARKET_SNIPPET_CHARS = 400          # per market-size web finding
KB_TOP_K = 5                        # KB snippets in the LLM context
KB_SNIPPET_CHARS = 500
YEARLY_MIN_BRIEFS = 12              # monthly briefs needed for a yearly summary
YEARLY_MONTH = 1                    # generate the yearly summary on the January run
YEARLY_BRIEF_CHARS = 4000           # per-brief truncation inside the yearly context

logger = logging.getLogger("skill.market_research_brief")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"market_research_brief exceeded {MAX_RUNTIME_SECS}s max runtime")


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
# Copied from the morning_brief / deep_research pattern — same sync wrapper
# logic so this skill works both standalone (CLI) and via the async runner.
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
# Market profiles
# ---------------------------------------------------------------------------


class ProfileError(ValueError):
    """Raised when a market profile is missing or malformed."""


def _available_profiles() -> list[str]:
    """List market profile names (files in the profiles dir)."""
    try:
        names = {
            p.stem for p in PROFILES_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in (".yml", ".yaml", ".json")
        }
    except OSError:
        return []
    return sorted(names)


def _load_profile(name: str) -> dict:
    """
    Load and normalize a market profile from profiles/<name>.{yml,yaml,json}.

    Returns a dict with keys:
      market, title, description, segments (list of {id,label,competitors}),
      analyst_firms (list of {name,note}), seed_queries, market_size_queries,
      yearly_month, yearly_min_briefs, slug
    Competitors are normalized to {name, search: [terms], note}.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name or ""):
        raise ProfileError(f"Invalid market profile name: {name!r}")
    path = None
    for suffix in (".yml", ".yaml", ".json"):
        candidate = PROFILES_DIR / f"{name}{suffix}"
        if candidate.is_file():
            path = candidate
            break
    if path is None:
        raise ProfileError(
            f"Market profile '{name}' not found in {PROFILES_DIR}. "
            f"Available: {', '.join(_available_profiles()) or '(none)'}"
        )

    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            data = json.loads(text)
        else:
            import yaml  # lazy: stdlib-only import path stays clean
            data = yaml.safe_load(text)
    except Exception as exc:
        raise ProfileError(f"Could not parse profile {path.name}: {exc}") from exc

    if not isinstance(data, dict) or not data.get("title") or not data.get("segments"):
        raise ProfileError(
            f"Profile {path.name} must be a mapping with 'title' and 'segments'"
        )

    segments: list[dict] = []
    for i, seg in enumerate(data["segments"]):
        if isinstance(seg, str):
            seg = {"id": seg.lower().replace(" ", "_"), "label": seg, "competitors": []}
        if not isinstance(seg, dict) or not seg.get("competitors"):
            raise ProfileError(f"Profile segment #{i} is missing 'competitors'")
        competitors: list[dict] = []
        for comp in seg["competitors"]:
            if isinstance(comp, str):
                comp = {"name": comp}
            if not isinstance(comp, dict) or not comp.get("name"):
                raise ProfileError(f"Bad competitor entry in segment '{seg.get('label')}'")
            search = comp.get("search") or [comp["name"]]
            if isinstance(search, str):
                search = [search]
            competitors.append({
                "name": str(comp["name"]).strip(),
                "search": [str(s).strip() for s in search if str(s).strip()],
                "note": str(comp.get("note") or ""),
            })
        segments.append({
            "id": str(seg.get("id") or seg.get("label") or f"segment_{i}").strip(),
            "label": str(seg.get("label") or seg.get("id") or "").strip(),
            "competitors": competitors,
        })

    analyst_firms: list[dict] = []
    for firm in data.get("analyst_firms") or []:
        if isinstance(firm, str):
            firm = {"name": firm}
        if isinstance(firm, dict) and firm.get("name"):
            analyst_firms.append({
                "name": str(firm["name"]).strip(),
                "note": str(firm.get("note") or ""),
            })

    slug = str(
        (data.get("publish") or {}).get("slug")
        or name
    ).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", slug):
        raise ProfileError(f"Invalid publish slug in profile: {slug!r}")

    return {
        "market": str(data.get("market") or name),
        "title": str(data["title"]).strip(),
        "description": str(data.get("description") or "").strip(),
        "segments": segments,
        "analyst_firms": analyst_firms,
        "seed_queries": [str(q).strip() for q in (data.get("seed_queries") or []) if str(q).strip()],
        "market_size_queries": [
            str(q).strip() for q in (data.get("market_size_queries") or []) if str(q).strip()
        ],
        "yearly_month": int(data.get("yearly_month", YEARLY_MONTH)),
        "yearly_min_briefs": int(data.get("yearly_min_briefs", YEARLY_MIN_BRIEFS)),
        "slug": slug,
    }


def _all_competitors(profile: dict) -> list[tuple[str, dict]]:
    """Flatten segments to [(segment_label, competitor), ...] in report order."""
    out: list[tuple[str, dict]] = []
    for seg in profile["segments"]:
        for comp in seg["competitors"]:
            out.append((seg["label"], comp))
    return out


# ---------------------------------------------------------------------------
# MCP wrappers — all calls go through LiteLLM
# ---------------------------------------------------------------------------


def _extract_items(result: Any) -> list[dict]:
    """
    Extract the list of result items from an MCP search/kb response.

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


def _friendly_source(source: str, url: str) -> str:
    """Map a bare domain (e.g. 'reuters.com') to a friendly publisher name."""
    s = (source or "").strip()
    low = s.lower()
    if low.startswith("www."):
        low = low[4:]
    if low and low not in ("news", "search"):
        return s
    try:
        host = urllib.parse.urlsplit(url or "").netloc.lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return host


def _normalize_url(url: str) -> str:
    """Normalize a URL for dedup (drops query/fragment, www.)."""
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"{host}{parts.path.rstrip('/')}".lower()


def _search_news(
    client: Any, query: str, max_results: int = 5, days: Optional[int] = None
) -> list[dict]:
    """Search news via mcp_search-search_news through LiteLLM.

    `days` restricts results to the last N days (SearXNG time_range).
    Returns a list of {title, url, snippet, source, published_date}.
    """
    args: dict[str, Any] = {"query": query, "max_results": max_results}
    if days is not None:
        args["days"] = days
    result = client.mcp_call("search_news", args, server_id="mcp_search")
    if not result:
        return []
    items: list[dict] = []
    seen: set[str] = set()
    for item in _extract_items(result):
        if len(items) >= max_results:
            break
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        key = _normalize_url(url)
        if not url or key in seen:
            continue
        seen.add(key)
        items.append({
            "title": str(item.get("title") or "Untitled").strip(),
            "url": url,
            "snippet": str(item.get("snippet") or item.get("content") or "")[:400],
            "source": _friendly_source(str(item.get("source") or ""), url),
            "published_date": str(item.get("published_date") or ""),
        })
    logger.info("search_news %r → %d items", query[:60], len(items))
    return items


def _search_web(client: Any, query: str, max_results: int = 5) -> list[dict]:
    """General web search via mcp_search-search_web through LiteLLM."""
    result = client.mcp_call(
        "search_web", {"query": query, "max_results": max_results}, server_id="mcp_search"
    )
    if not result:
        return []
    items: list[dict] = []
    seen: set[str] = set()
    for item in _extract_items(result):
        if len(items) >= max_results:
            break
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        key = _normalize_url(url)
        if not url or key in seen:
            continue
        seen.add(key)
        items.append({
            "title": str(item.get("title") or "Untitled").strip(),
            "url": url,
            "snippet": str(item.get("snippet") or item.get("content") or "")[:400],
            "source": _friendly_source(str(item.get("source") or ""), url),
            "published_date": str(item.get("published_date") or ""),
        })
    logger.info("search_web %r → %d items", query[:60], len(items))
    return items


def _kb_search(client: Any, query: str, top_k: int = KB_TOP_K) -> list[dict]:
    """Search the family KB via mcp_knowledge-kb_search through LiteLLM.

    Returns a list of {kb, source, page_range, snippet}. Best-effort:
    returns [] on any failure.
    """
    result = client.mcp_call(
        "kb_search", {"query": query, "top_k": top_k}, server_id="mcp_knowledge"
    )
    if not isinstance(result, dict):
        return []
    # kb_search returns {query, mode, results: [...]} — find the results list.
    # The payload may be nested under structuredContent/result, or JSON-
    # embedded in a text content item (raw MCP CallToolResult shape).
    candidates: list[dict] = []
    if isinstance(result.get("structuredContent"), dict):
        candidates.append(result["structuredContent"])
    if isinstance(result.get("result"), dict):
        candidates.append(result["result"])
    candidates.append(result)
    for item in result.get("content") or []:
        if not (isinstance(item, dict) and item.get("type") == "text"):
            continue
        try:
            parsed = json.loads(item.get("text", ""))
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)
    for cand in candidates:
        hits = cand.get("results")
        if isinstance(hits, list):
            out: list[dict] = []
            for hit in hits[:top_k]:
                if not isinstance(hit, dict):
                    continue
                snippet = str(hit.get("snippet") or "")[:KB_SNIPPET_CHARS]
                if not snippet:
                    continue
                out.append({
                    "kb": str(hit.get("kb") or ""),
                    "source": str(hit.get("source") or ""),
                    "page_range": str(hit.get("page_range") or ""),
                    "snippet": snippet,
                })
            return out
    return []


# ---------------------------------------------------------------------------
# Owner context: long-term memory + KB
# ---------------------------------------------------------------------------


def _memory_block(job, profile: dict) -> str:
    """Retrieve the owner's durable facts relevant to this market (Phase 7).

    Identity comes from the Job; gated by job.memory_enabled; non-fatal —
    any failure degrades to "" so the brief is never broken by memory.
    The memory package is imported lazily so the skill stays importable
    standalone (importlib, stdlib-only by design).
    """
    try:
        from memory import jobctx  # lazy
        query = (
            f"market research brief for {profile['title']}: competitor "
            "interests, market preferences, standing notes, prior findings"
        )
        return jobctx.retrieve(job, query)
    except Exception as exc:  # noqa: BLE001 — never break the skill
        if hasattr(job, "add_log"):
            job.add_log(f"Memory context unavailable (non-fatal): {exc}")
        return ""


# ---------------------------------------------------------------------------
# Research context building
# ---------------------------------------------------------------------------


def _fmt_item(i: int, item: dict, snippet_chars: int) -> list[str]:
    """Render one research item as context lines."""
    lines: list[str] = []
    meta = " | ".join(
        x for x in (item.get("source") or "", item.get("published_date") or "") if x
    )
    lines.append(f"{i}. {item['title']}" + (f" | {meta}" if meta else ""))
    lines.append(f"   URL: {item['url']}")
    snippet = (item.get("snippet") or "").strip()
    if snippet:
        lines.append(f"   Snippet: {snippet[:snippet_chars]}")
    return lines


def _build_context(
    profile: dict,
    competitor_news: list[tuple[str, dict, list[dict]]],
    seed_results: list[tuple[str, list[dict]]],
    market_results: list[tuple[str, list[dict]]],
    kb_hits: list[dict],
    memory_block: str,
    period_days: int,
    today: str,
) -> str:
    """Assemble the full LLM context for the monthly brief."""
    lines: list[str] = [
        f"Today's date: {today}",
        f"Market: {profile['title']} — {profile['description'] or 'no description'}",
        f"Period: last {period_days} days (through {today}).",
        "",
        "=== COMPETITOR NEWS (per competitor, last period) ===",
    ]
    for segment_label, comp, items in competitor_news:
        lines.append(f"--- {comp['name']} (segment: {segment_label}) ---")
        if comp["note"]:
            lines.append(f"Note: {comp['note']}")
        if not items:
            lines.append("No news items found for this period.")
        else:
            for i, item in enumerate(items, 1):
                lines.extend(_fmt_item(i, item, COMPETITOR_SNIPPET_CHARS))
        lines.append("")

    if seed_results:
        lines.append("=== SEED QUERY NEWS (broad market-level sweep) ===")
        for query, items in seed_results:
            lines.append(f"(query: {query!r})")
            if not items:
                lines.append("No items found.")
            else:
                for i, item in enumerate(items, 1):
                    lines.extend(_fmt_item(i, item, COMPETITOR_SNIPPET_CHARS))
            lines.append("")

    if market_results:
        lines.append("=== MARKET SIZE & SHARE FINDINGS (web search, free sources) ===")
        for query, items in market_results:
            lines.append(f"(query: {query!r})")
            if not items:
                lines.append("No items found.")
            else:
                for i, item in enumerate(items, 1):
                    lines.extend(_fmt_item(i, item, MARKET_SNIPPET_CHARS))
            lines.append("")

    if profile["analyst_firms"]:
        lines.append("=== ANALYST FIRMS TO WATCH ===")
        for firm in profile["analyst_firms"]:
            line = f"- {firm['name']}"
            if firm["note"]:
                line += f" — {firm['note']}"
            lines.append(line)
        lines.append("")

    if memory_block or kb_hits:
        lines.append("=== OWNER CONTEXT (long-term memory + family KB) ===")
        lines.append("Use this as background context only. It has no URLs; do not")
        lines.append("cite it with links. Prefer fresh sourced findings over stale notes.")
        if memory_block:
            lines.append(memory_block.strip())
        if kb_hits:
            lines.append("Knowledge-base hits:")
            for hit in kb_hits:
                where = " ".join(x for x in (hit["kb"], hit["source"], hit["page_range"]) if x)
                lines.append(f"- [{where}] {hit['snippet']}" if where else f"- {hit['snippet']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM synthesis — monthly brief
# ---------------------------------------------------------------------------


def _monthly_system_prompt(profile: dict, period_days: int) -> str:
    """Build the system prompt with the profile's exact competitor list."""
    competitor_list = "\n".join(
        f"- {comp['name']} (segment: {label})" + (f" — {comp['note']}" if comp["note"] else "")
        for label, comp in _all_competitors(profile)
    )
    firms = ", ".join(f["name"] for f in profile["analyst_firms"]) or "(none configured)"
    month_year = datetime.now(timezone.utc).strftime("%B %Y")

    return textwrap.dedent(f"""\
        You are a market research analyst producing a monthly market research
        brief for the market: {profile['title']}.

        You will be given research material collected for the last
        {period_days} days: per-competitor news, broad market-level news,
        market-size/share web findings, and the owner's context (memory +
        knowledge base, which may be empty).

        Produce a markdown report with EXACTLY this structure:

        # {profile['title']} — Market Research Brief — {month_year}

        ## Executive Summary
        - 4-6 bullets: the period's most important developments across the
          market (launches, pricing, partnerships, market-size updates, share
          shifts).

        ## Market Size & Share
        - 2-4 bullets: current market size, growth, and competitive share
          where identifiable, each with an inline [Publisher](url) citation.
        - Free sources only. If a figure traces to a paywalled analyst
          report and only free coverage is available, say so explicitly
          (e.g. "per free coverage of a paywalled Parks Associates report").
        - If no new market-size data was found this period, say so and
          restate the most recent known figure from the provided context.

        ## Competitor Scan
        For EACH competitor below, in the given order, produce a subsection:

        ### <Competitor> — <Segment>
        **Last month:**
        - 1-3 bullets on what they did, shipped, or announced during the
          period, each with an inline [Publisher](url) citation.
        **Trend:**
        - One sentence: the direction they appear to be heading and why.

        Competitors (in order):
        {competitor_list}

        ## Analyst Watch
        - 1-3 bullets on activity from: {firms}. New reports, free coverage,
          forecast shifts. Cite sources. If nothing new was found, say so.

        ## Trends & Outlook
        - 3-5 bullets: cross-competitor trends and what to watch in the
          coming period.

        Rules:
        - Use ONLY facts from the provided material. Never invent facts,
          numbers, quotes, or URLs.
        - Every claim sourced from a news item or web finding must carry an
          inline [Publisher](url) citation using the exact URL provided.
        - If a competitor has NO news items for the period, write
          "**Last month:** No significant news found in the provided sources
          for this period." and keep the Trend line cautious (based on prior
          context, or "insufficient data this period").
        - Publisher names and URLs must be used exactly as provided.
        - Free sources only: never present paywalled report contents that
          were not provided; flag when the best data sits behind a paywall.
        - Output ONLY the markdown report — no preamble, no code fences,
          no trailing commentary.
    """)


def _strip_code_fence(text: str) -> str:
    """Strip a wrapping ```markdown ... ``` fence if the LLM added one."""
    text = text.strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n(.*?)\n?```\s*$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _synthesize(
    client: Any,
    system_prompt: str,
    context: str,
    job=None,
    max_tokens: int = 16000,
) -> str:
    """One LLM synthesis call via LiteLLM, with a single retry on empty
    visible content (reasoning models can burn the token budget on
    reasoning_content)."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": context},
    ]

    def _call_once() -> tuple[Optional[str], str]:
        result = client.chat_completion(
            MODEL_ALIAS, messages, max_tokens=max_tokens, temperature=0.3, stream=False
        )
        choices = result.get("choices", []) if isinstance(result, dict) else []
        if not choices:
            return None, "no_choices"
        message = choices[0].get("message") or {}
        finish = str(choices[0].get("finish_reason") or "")
        return message.get("content") or None, finish

    content, finish = _call_once()
    if not content:
        if hasattr(job, "add_log"):
            job.add_log(f"LLM returned empty content (finish_reason={finish}) — retrying once")
        content, finish = _call_once()
    if not content:
        if hasattr(job, "add_log"):
            job.add_log(f"LLM retry also returned empty content (finish_reason={finish})")
        raise RuntimeError(
            f"LLM returned empty content (finish_reason={finish}; the model likely "
            "spent its token budget on internal reasoning)"
        )
    return _strip_code_fence(content)


# ---------------------------------------------------------------------------
# Yearly summary
# ---------------------------------------------------------------------------


def _monthly_artifact_paths(market: str) -> list[tuple[str, Path]]:
    """
    Find monthly .md artifacts for a market: [(YYYY-MM, path), ...] sorted
    ascending, one entry per month (latest artifact wins per month).
    Monthly names: market_research_brief_<market>_<ts>.md (ts = YYYY-MM-DDTHH-MM-SS).
    Yearly artifacts (…_yearly_…) never match the pattern.
    """
    ts_re = re.compile(rf"^market_research_brief_{re.escape(market)}_(\d{{4}}-\d{{2}})-\d{{2}}T\d{{2}}-\d{{2}}-\d{{2}}\.md$")
    by_month: dict[str, tuple[str, Path]] = {}
    try:
        for p in ARTIFACT_DIR.glob(f"market_research_brief_{market}_2*.md"):
            m = ts_re.match(p.name)
            if not m:
                continue
            month = m.group(1)
            if month not in by_month or p.name > by_month[month][0]:
                by_month[month] = (p.name, p)
    except OSError:
        return []
    return [(month, path) for month, (_, path) in sorted(by_month.items())]


def _yearly_label(months: list[str]) -> str:
    """Label a yearly summary from its covered months ('2025' or '2025-2026')."""
    years = sorted({m[:4] for m in months})
    return years[0] if len(years) == 1 else f"{years[0]}-{years[-1]}"


def _yearly_system_prompt(profile: dict, label: str, months: list[str]) -> str:
    month_names = [datetime.strptime(m, "%Y-%m").strftime("%B %Y") for m in (months[0], months[-1])]
    return textwrap.dedent(f"""\
        You are a market research analyst producing a YEARLY summary of the
        market: {profile['title']}, synthesized from the 12 monthly market
        research briefs provided below (covering {month_names[0]} through
        {month_names[1]}).

        Produce a markdown report with EXACTLY this structure:

        # {profile['title']} — Yearly Summary {label}

        ## Year in Review
        - 6-8 bullets: the biggest developments of the year.

        ## Market Size & Share — Year Over Year
        - How size/share estimates moved across the year, with inline
          [Publisher](url) citations where the monthly briefs provide them.

        ## Competitor Trends
        - One bullet per major competitor: their trajectory over the year
          (launches, pivots, pricing, market position).

        ## Winners & Losers
        - 2-4 bullets: who gained ground and who lost it, and why.

        ## Outlook
        - 3-5 bullets: where the market is heading.

        Rules:
        - Use ONLY facts from the monthly briefs below. Never invent facts,
          numbers, quotes, or URLs.
        - Cite sources inline as [Publisher](url) when a monthly brief
          provides them.
        - Output ONLY the markdown report — no preamble, no code fences.
    """)


def _yearly_context(profile: dict, briefs: list[tuple[str, str]]) -> str:
    """Assemble the yearly-summary context from (month, report_md) pairs."""
    lines = [
        f"Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        f"Market: {profile['title']}",
        f"The following {len(briefs)} monthly briefs cover the year (oldest first).",
        "",
    ]
    for month, report in briefs:
        lines.append(f"===== MONTHLY BRIEF — {month} =====")
        lines.append(report[:YEARLY_BRIEF_CHARS])
        lines.append("")
    return "\n".join(lines)


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
    """Convert inline markdown to HTML (escape first, then link/bold/italic/code)."""
    out = _escape_html(text)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>',
        out,
    )
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(^|[^*])\*([^*\n]+)\*", r"\1<em>\2</em>", out)
    return out


def _md_to_html(md: str) -> str:
    """Convert a markdown subset (headings, paragraphs, lists, blockquotes,
    hr, code fences, inline formatting) to HTML. Line-based state machine."""
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

        if stripped.startswith("```"):
            flush_para()
            close_lists()
            i += 1
            code: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(f"<pre><code>{_escape_html(chr(10).join(code))}</code></pre>")
            continue

        if not stripped:
            flush_para()
            close_lists()
            i += 1
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            close_lists()
            level = len(m.group(1))
            out.append(f"<h{level}>{_md_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para()
            close_lists()
            out.append("<hr>")
            i += 1
            continue

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

        para.append(stripped)
        i += 1

    flush_para()
    close_lists()
    return "\n".join(out)


_HTML_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 16px;
  background: #f4f5f7; color: #1a1d21;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  line-height: 1.55; font-size: 16px; -webkit-text-size-adjust: 100%;
}
.wrap { max-width: 760px; margin: 0 auto; padding: 24px 0 40px; }
header.brief h1 { font-size: 1.55rem; margin: 0 0 4px; line-height: 1.25; }
.meta { color: #5a6472; font-size: 0.95rem; margin: 0 0 4px; }
.report { background: #ffffff; border: 1px solid #e2e5ea; border-radius: 14px;
  padding: 22px 22px 10px; margin: 18px 0;
  box-shadow: 0 1px 3px rgba(16,24,40,0.05); }
.report h1 { font-size: 1.4rem; margin: 0 0 10px; }
.report h2 { font-size: 1.25rem; margin: 26px 0 8px; padding-bottom: 6px;
  border-bottom: 2px solid #e2e5ea; }
.report h3 { font-size: 1.08rem; margin: 18px 0 6px; color: #111827; }
.report p { margin: 8px 0; }
.report ul, .report ol { margin: 8px 0; padding-left: 22px; }
.report li { margin: 5px 0; }
.report a { color: #1d4ed8; overflow-wrap: anywhere; }
.report code { background: #f0f1f3; padding: 1px 5px; border-radius: 4px; font-size: 0.9em; }
.report blockquote { margin: 8px 0; padding: 8px 14px; border-left: 3px solid #cbd5e1;
  color: #4a5569; background: #fafbfc; }
.report hr { border: none; border-top: 1px solid #e2e5ea; margin: 18px 0; }
footer { margin-top: 28px; color: #8a94a3; font-size: 0.8rem; text-align: center; }
@media (prefers-color-scheme: dark) {
  body { background: #0f1216; color: #e6e8eb; }
  .meta, footer { color: #9aa3af; }
  .report { background: #171b21; border-color: #262c35; box-shadow: none; }
  .report h2 { border-bottom-color: #262c35; }
  .report h3 { color: #e6e8eb; }
  .report a { color: #7aa6ff; }
  .report code { background: #232830; }
  .report blockquote { background: #171b21; border-left-color: #3a424e; color: #94a3b8; }
  .report hr { border-top-color: #262c35; }
}
"""


def _html_document(title: str, meta_line: str, body_html: str, footer_note: str) -> str:
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
        f"<footer>Generated {now} by the market research brief skill. {footer_note}</footer>\n"
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )


def _render_report_html(
    report_md: str, title: str, meta_line: str, footer_note: str
) -> str:
    """Render the markdown report to the final HTML page (section layout)."""
    body = f'<div class="report">{_md_to_html(report_md)}</div>'
    return _html_document(title, meta_line, body, footer_note)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Artifact generation + publishing
# ---------------------------------------------------------------------------


def _write_artifact(report: str, market: str, ext: str = "md", suffix: str = "") -> Optional[str]:
    """Save a timestamped artifact (.md raw or .html rendered). Artifacts are
    KEPT (no pruning) so a few years of monthly briefs accumulate."""
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        name = f"market_research_brief_{market}_{suffix}{ts}.{ext}" if suffix \
            else f"market_research_brief_{market}_{ts}.{ext}"
        path = ARTIFACT_DIR / name
        path.write_text(report, encoding="utf-8")
        logger.info("Artifact written: %s", path)
        return str(path)
    except OSError as exc:
        logger.error("Could not write artifact: %s", exc)
        return None


def _publish(html: str, target: Path, job=None) -> Optional[str]:
    """Atomically publish HTML to a public-drop-zone path."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(html, encoding="utf-8")
        os.replace(tmp, target)  # atomic on POSIX
        logger.info("Published: %s", target)
        if hasattr(job, "add_log"):
            job.add_log(f"Published to {target}")
        return str(target)
    except OSError as exc:
        logger.error("Could not publish to %s: %s", target, exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Publish FAILED ({target}): {exc}")
        return None


def _public_url(path: Path) -> str:
    """Map a public-drop-zone path to its https URL."""
    try:
        rel = path.resolve().relative_to(PUBLIC_ROOT.resolve())
        return f"{PUBLIC_BASE}/{rel.as_posix()}"
    except (ValueError, OSError):
        return f"{PUBLIC_BASE}/briefs/{path.name}"


def _prune_dated(slug: str, job=None) -> int:
    """Keep only the last DATED_RETENTION dated copies for a slug on the blog.

    Dated names: <slug>_YYYY-MM.html under <public>/briefs/market_research/.
    No-op until more than the retention count exist ("when we get there").
    """
    dated_dir = PUBLIC_ROOT / "briefs" / DATED_DIRNAME
    if not dated_dir.is_dir():
        return 0
    try:
        files = sorted(
            (p for p in dated_dir.glob(f"{slug}_*.html")
             if re.fullmatch(rf"{re.escape(slug)}_\d{{4}}-\d{{2}}\.html", p.name)),
            key=lambda p: p.name,
            reverse=True,
        )
    except OSError:
        return 0
    removed = 0
    for stale in files[DATED_RETENTION:]:
        try:
            stale.unlink()
            removed += 1
            logger.info("Pruned dated brief: %s", stale)
        except OSError as exc:
            logger.warning("Could not prune %s: %s", stale, exc)
    if removed and hasattr(job, "add_log"):
        job.add_log(f"Pruned {removed} old dated brief(s) (retention {DATED_RETENTION})")
    return removed


def _publish_dated(html: str, slug: str, job=None) -> tuple[Optional[str], Optional[str]]:
    """Publish a dated copy (<slug>_YYYY-MM.html) and prune old ones.

    Returns (path, url) or (None, None).
    """
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    target = PUBLIC_ROOT / "briefs" / DATED_DIRNAME / f"{slug}_{month}.html"
    path = _publish(html, target, job)
    if not path:
        return None, None
    _prune_dated(slug, job)
    return path, _public_url(Path(path))




# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(
    params: dict[str, Any],
    job,
    litellm_client=None,
) -> dict[str, Any]:
    """
    Execute the market_research_brief skill.

    All LLM and MCP interactions go through LiteLLM. This skill never
    contacts MCP servers directly.

    Args:
        params: Skill parameters (market, period_days, max_items, publish,
                publish_path).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.

    Returns:
        Dict with summary, report, artifact paths, publish paths/urls,
        yearly-summary info, and research statistics.
    """
    params = params or {}
    client = _resolve_litellm_client(litellm_client)

    # ---- Resolve the market profile ----
    market = str(params.get("market") or "").strip()
    if not market:
        return {
            "error": (
                "market_research_brief requires a 'market' parameter "
                f"(one of: {', '.join(_available_profiles()) or 'none available'})"
            ),
        }
    try:
        profile = _load_profile(market)
    except ProfileError as exc:
        return {"error": str(exc)}

    try:
        period_days = int(params.get("period_days", DEFAULT_PERIOD_DAYS))
    except (TypeError, ValueError):
        period_days = DEFAULT_PERIOD_DAYS
    period_days = max(7, min(period_days, 365))

    try:
        max_items = int(params.get("max_items", DEFAULT_MAX_ITEMS))
    except (TypeError, ValueError):
        max_items = DEFAULT_MAX_ITEMS
    max_items = max(1, min(max_items, HARD_MAX_ITEMS))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    month_label = datetime.now(timezone.utc).strftime("%B %Y")
    title = f"{profile['title']} — Market Research Brief — {month_label}"
    slug = profile["slug"]

    if hasattr(job, "add_log"):
        job.add_log(
            f"Executing market_research_brief: market={profile['market']}, "
            f"period_days={period_days}, max_items={max_items}"
        )
        job.add_log(f"Model alias: {MODEL_ALIAS}")

    _install_timeout()
    try:
        # ---- Phase 1: owner context (memory + KB) — non-fatal ----
        memory_block = _memory_block(job, profile)
        kb_hits: list[dict] = []
        try:
            kb_hits = _kb_search(
                client,
                f"{profile['title']} market competitors trends market size",
            )
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("KB search failed (non-fatal): %s", exc)
        if hasattr(job, "add_log"):
            job.add_log(
                f"Owner context: memory={'yes' if memory_block else 'no'}, "
                f"kb_hits={len(kb_hits)}"
            )

        # ---- Phase 2: competitor news (freshness-filtered) ----
        competitors = _all_competitors(profile)
        deadline = time.monotonic() + MAX_RUNTIME_SECS - 150
        competitor_news: list[tuple[str, dict, list[dict]]] = []
        for segment_label, comp in competitors:
            if time.monotonic() > deadline:
                if hasattr(job, "add_log"):
                    job.add_log(
                        "Time budget reached — remaining competitors "
                        "use whatever was collected so far"
                    )
                competitor_news.append((segment_label, comp, []))
                continue
            items: list[dict] = []
            seen: set[str] = set()
            for term in comp["search"][:2]:
                if time.monotonic() > deadline:
                    break
                if hasattr(job, "add_log"):
                    job.add_log(f"Searching news: {term} (last {period_days} days)")
                for item in _search_news(
                    client, f"{term} news", max_results=max_items, days=period_days
                ):
                    key = _normalize_url(item["url"])
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append(item)
                    if len(items) >= max_items:
                        break
            competitor_news.append((segment_label, comp, items))
            if hasattr(job, "add_log"):
                job.add_log(f"  → {len(items)} item(s) for {comp['name']}")

        # ---- Phase 3: seed queries + market size (web) ----
        seed_results: list[tuple[str, list[dict]]] = []
        for query in profile["seed_queries"]:
            if time.monotonic() > deadline:
                break
            seed_results.append(
                (query, _search_news(client, query, max_results=max_items, days=period_days))
            )

        market_results: list[tuple[str, list[dict]]] = []
        for query in profile["market_size_queries"]:
            if time.monotonic() > deadline:
                break
            market_results.append((query, _search_web(client, query, max_results=max_items)))

        items_found = sum(len(items) for _, _, items in competitor_news)
        if hasattr(job, "add_log"):
            job.add_log(
                f"Research collected: {items_found} competitor item(s), "
                f"{sum(len(i) for _, i in seed_results)} seed item(s), "
                f"{sum(len(i) for _, i in market_results)} market item(s)"
            )

        # ---- Phase 4: synthesize the monthly brief via LLM ----
        if hasattr(job, "add_log"):
            job.add_log("Synthesizing market research brief via LLM...")
        context = _build_context(
            profile, competitor_news, seed_results, market_results,
            kb_hits, memory_block, period_days, today,
        )
        report = _synthesize(client, _monthly_system_prompt(profile, period_days), context, job)
        if hasattr(job, "add_log"):
            job.add_log(f"Brief generated ({len(report)} chars)")

        # ---- Phase 5: render HTML + save artifacts (retained) ----
        meta_line = (
            f"{len(competitors)} competitors · last {period_days} days · "
            f"{items_found} news item(s)"
        )
        footer_note = (
            "Competitor scan covers the last "
            f"{period_days} days; market data uses free sources only "
            "(paywalled analyst figures are flagged, never fabricated)."
        )
        html = _render_report_html(report, title, meta_line, footer_note)
        artifact_path = _write_artifact(report, profile["market"])
        html_artifact_path = _write_artifact(html, profile["market"], "html")

        # ---- Phase 6: publish to the blog drop zone ----
        published_path = published_url = None
        dated_path = dated_url = None
        if params.get("publish"):
            target = Path(params.get("publish_path") or str(PUBLIC_ROOT / "briefs" / f"{slug}.html"))
            published_path = _publish(html, target, job)
            if published_path:
                published_url = _public_url(Path(published_path))
            dated_path, dated_url = _publish_dated(html, slug, job)

        # ---- Phase 7: yearly summary (January run, 12+ monthly briefs) ----
        yearly: dict[str, Any] = {}
        if datetime.now(timezone.utc).month == profile["yearly_month"]:
            months_paths = _monthly_artifact_paths(profile["market"])
            if len(months_paths) >= profile["yearly_min_briefs"]:
                picked = months_paths[-profile["yearly_min_briefs"]:]
                label = _yearly_label([m for m, _ in picked])
                if hasattr(job, "add_log"):
                    job.add_log(f"Generating yearly summary ({label}) from {len(picked)} monthly briefs")
                briefs = []
                for month, path in picked:
                    try:
                        briefs.append((month, path.read_text(encoding="utf-8")))
                    except OSError as exc:
                        logger.warning("Could not read %s: %s", path, exc)
                if briefs:
                    yearly_report = _synthesize(
                        client,
                        _yearly_system_prompt(profile, label, [m for m, _ in briefs]),
                        _yearly_context(profile, briefs),
                        job,
                    )
                    yearly_title = f"{profile['title']} — Yearly Summary {label}"
                    yearly_html = _render_report_html(
                        yearly_report, yearly_title,
                        f"covering {briefs[0][0]} through {briefs[-1][0]}",
                        "Synthesized from the 12 most recent monthly briefs.",
                    )
                    yearly_md = _write_artifact(
                        yearly_report, profile["market"], "md", suffix=f"yearly_{label}_"
                    )
                    yearly_html_path = _write_artifact(
                        yearly_html, profile["market"], "html", suffix=f"yearly_{label}_"
                    )
                    yearly = {
                        "label": label,
                        "months": [m for m, _ in briefs],
                        "artifact_path": yearly_md,
                        "html_artifact_path": yearly_html_path,
                        "published_path": None,
                        "published_url": None,
                    }
                    if params.get("publish"):
                        yearly_target = (
                            PUBLIC_ROOT / "briefs" / f"{slug}_yearly_{label}.html"
                        )
                        yearly["published_path"] = _publish(yearly_html, yearly_target, job)
                        if yearly["published_path"]:
                            yearly["published_url"] = _public_url(yearly_target)
            else:
                if hasattr(job, "add_log"):
                    job.add_log(
                        f"Yearly summary skipped: {len(months_paths)} monthly brief(s) "
                        f"< {profile['yearly_min_briefs']} required"
                    )

        with_news = sum(1 for _, _, items in competitor_news if items)
        summary = (
            f"{profile['title']}: {items_found} news item(s) across "
            f"{with_news}/{len(competitors)} competitors"
        )
        if yearly.get("label"):
            summary += f"; yearly summary {yearly['label']} generated"

        return {
            "summary": summary[:300],
            "report": report,
            "artifact_path": artifact_path,
            "html_artifact_path": html_artifact_path,
            "published_path": published_path,
            "published_url": published_url,
            "dated_publish_path": dated_path,
            "dated_publish_url": dated_url,
            "yearly": yearly or None,
            "market": profile["market"],
            "period_days": period_days,
            "competitors_scanned": len(competitors),
            "competitors_with_news": with_news,
            "items_found": items_found,
            "memory_used": bool(memory_block),
            "kb_used": bool(kb_hits),
        }

    except TimeoutError as exc:
        report = (
            f"# {title}\n\n"
            f"## ⚠️ **Timeout** — the market research brief could not complete.\n\n"
            f"The skill exceeded its {MAX_RUNTIME_SECS}s max runtime. "
            "Partial results may be available in the artifact directory.\n"
        )
        html = _render_report_html(report, title, "timeout", "Run timed out.")
        artifact_path = _write_artifact(report, market)
        html_artifact_path = _write_artifact(html, market, "html")
        published_path = published_url = None
        if params.get("publish"):
            target = Path(params.get("publish_path") or str(PUBLIC_ROOT / "briefs" / f"{slug}.html"))
            published_path = _publish(html, target, job)
            if published_path:
                published_url = _public_url(Path(published_path))
        return {
            "summary": f"market_research_brief timed out after {MAX_RUNTIME_SECS}s",
            "report": report,
            "artifact_path": artifact_path,
            "html_artifact_path": html_artifact_path,
            "published_path": published_path,
            "published_url": published_url,
            "market": market,
            "period_days": period_days,
            "competitors_scanned": 0,
            "competitors_with_news": 0,
            "items_found": 0,
        }

    except (RuntimeError, ProfileError) as exc:
        report = (
            f"# {title}\n\n"
            f"## ⚠️ **Error** — the market research brief could not be generated.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            "Check the LiteLLM proxy status and try again.\n"
        )
        html = _render_report_html(report, title, "error", "Run failed.")
        artifact_path = _write_artifact(report, market)
        html_artifact_path = _write_artifact(html, market, "html")
        published_path = published_url = None
        if params.get("publish"):
            target = Path(params.get("publish_path") or str(PUBLIC_ROOT / "briefs" / f"{slug}.html"))
            published_path = _publish(html, target, job)
            if published_path:
                published_url = _public_url(Path(published_path))
        return {
            "summary": f"market_research_brief failed: {type(exc).__name__}: {exc}",
            "report": report,
            "artifact_path": artifact_path,
            "html_artifact_path": html_artifact_path,
            "published_path": published_path,
            "published_url": published_url,
            "market": market,
            "period_days": period_days,
            "competitors_scanned": 0,
            "competitors_with_news": 0,
            "items_found": 0,
        }

    except Exception as exc:  # noqa: BLE001 — catch-all for graceful degradation
        report = (
            f"# {title}\n\n"
            f"## ⚠️ **Error** — the market research brief could not be generated.\n\n"
            f"An unexpected error occurred: {type(exc).__name__}: {exc}\n\n"
            "Check the skill logs and try again.\n"
        )
        html = _render_report_html(report, title, "error", "Run failed.")
        artifact_path = _write_artifact(report, market)
        html_artifact_path = _write_artifact(html, market, "html")
        published_path = published_url = None
        if params.get("publish"):
            target = Path(params.get("publish_path") or str(PUBLIC_ROOT / "briefs" / f"{slug}.html"))
            published_path = _publish(html, target, job)
            if published_path:
                published_url = _public_url(Path(published_path))
        return {
            "summary": f"market_research_brief failed: {type(exc).__name__}: {exc}",
            "report": report,
            "artifact_path": artifact_path,
            "html_artifact_path": html_artifact_path,
            "published_path": published_path,
            "published_url": published_url,
            "market": market,
            "period_days": period_days,
            "competitors_scanned": 0,
            "competitors_with_news": 0,
            "items_found": 0,
        }

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# CLI entrypoint (standalone testing)
# ---------------------------------------------------------------------------


def main() -> None:
    """Standalone CLI for testing the market_research_brief skill."""
    import argparse

    parser = argparse.ArgumentParser(description="market_research_brief skill (standalone)")
    parser.add_argument("--market", default="",
                        help="Market profile name (default: error listing available profiles)")
    parser.add_argument("--period-days", type=int, default=DEFAULT_PERIOD_DAYS,
                        help="Lookback window in days (default: %(default)s)")
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS,
                        help="Max news items per query (default: %(default)s)")
    parser.add_argument("--publish", action="store_true", default=False,
                        help="Publish the HTML brief to the public drop zone")
    parser.add_argument("--publish-path", default="",
                        help="Override the published 'latest' file path")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show resolved config without executing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    params: dict[str, Any] = {
        "period_days": args.period_days,
        "max_items": args.max_items,
        "publish": args.publish,
    }
    if args.market:
        params["market"] = args.market
    if args.publish_path:
        params["publish_path"] = args.publish_path

    if args.dry_run:
        print("Resolved configuration:")
        print(f"  market:        {params.get('market') or '(not set — will error with profile list)'}")
        print(f"  period_days:   {params['period_days']}")
        print(f"  max_items:     {params['max_items']}")
        print(f"  publish:       {args.publish}")
        print(f"  publish_path:  {args.publish_path or '(profile default)'}")
        print(f"  model_alias:   {MODEL_ALIAS}")
        print(f"  litellm:       {LITELLM_BASE_URL}")
        print(f"  artifact_dir:  {ARTIFACT_DIR}")
        print(f"  public_root:   {PUBLIC_ROOT}")
        print(f"  profiles:      {', '.join(_available_profiles()) or '(none)'}")
        return

    class _CLIJob:
        def add_log(self, msg: str) -> None:
            print(f"[log] {msg}")

    job = _CLIJob()
    result = run(params, job)

    print("\n" + "=" * 70)
    print("SUMMARY:")
    for key in ("summary", "artifact_path", "html_artifact_path",
                "published_path", "published_url",
                "dated_publish_path", "dated_publish_url"):
        if result.get(key) is not None:
            print(f"  {key}: {result[key]}")
    yearly = result.get("yearly")
    if yearly:
        print(f"  yearly.label:        {yearly.get('label')}")
        print(f"  yearly.artifact:     {yearly.get('artifact_path')}")
        print(f"  yearly.published:    {yearly.get('published_url')}")
    for key in ("market", "period_days", "competitors_scanned",
                "competitors_with_news", "items_found", "memory_used", "kb_used"):
        print(f"  {key}: {result.get(key)}")
    print("=" * 70)

    if result.get("error"):
        print(f"\nERROR: {result['error']}")
        sys.exit(1)
    if result.get("report"):
        print("\nREPORT:\n")
        print(result["report"])


if __name__ == "__main__":
    main()
