#!/usr/bin/env python3
"""
market_research_brief — annual reference data (build + render).

Purpose:
  Builds and renders the *annual reference* for a market profile:
  - Market context: size (multiple independent free estimates + CAGRs),
    growth, and per-competitor size/share indicators (revenue for public
    companies; clearly-labeled survey-share / PR-estimate / install-base
    proxies for private ones).
  - Competitor comparison: per-competitor facts on the market's key aspects
    (defined per-market in the profile's `reference:` block) + LLM rubric
    ratings (1-5) + free review-site scores where available.

  The reference is saved to references/<market>.json (git-tracked,
  human-editable) and rendered DETERMINISTICALLY (no LLM) into HTML
  (bar charts, comparison table, ratings heatmap) and markdown.

  The monthly brief (skill.py) loads the JSON and splices the rendered
  section in; the yearly summary gets the full table + a year-over-year
  diff. This module is standalone (stdlib only) so the reference can be
  bootstrapped / rebuilt without touching the monthly pipeline:

      python3 reference.py --market smarthome_homesecurity [--force]
      python3 reference.py --market smarthome_homesecurity --render-only

Constraints:
  - All LLM/MCP traffic via LiteLLM (never direct MCP access).
  - Free sources only; paywalled figures flagged, never fabricated.
  - Max runtime: MARKET_RESEARCH_REFERENCE_MAX_RUNTIME (default 900 s).

See market_research_todo.md for the full plan and schema.
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
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SKILL_DIR = Path(__file__).resolve().parent
PROFILES_DIR = Path(
    os.environ.get("MARKET_RESEARCH_REFERENCE_PROFILES_DIR", str(SKILL_DIR / "profiles"))
)
REFERENCES_DIR = Path(
    os.environ.get("MARKET_RESEARCH_REFERENCE_DIR", str(SKILL_DIR / "references"))
)
ARTIFACT_DIR = Path(
    os.environ.get(
        "MARKET_RESEARCH_BRIEF_ARTIFACT_DIR",
        "/home/chuck/data/media/market_research_briefs",
    )
)

LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("MARKET_RESEARCH_REFERENCE_MODEL_ALIAS", "matrix-coder")

MAX_RUNTIME_SECS = int(os.environ.get("MARKET_RESEARCH_REFERENCE_MAX_RUNTIME", "1800"))

# Volume limits
CRAWL_MAX_CHARS = 9000          # per source page
CONTEXT_MAX_CHARS = 30000       # per-competitor LLM context cap
MARKET_MAX_ITEMS = 5            # web findings per market-size query
CRAWL_WORKERS = 6               # parallel crawls
EXTRACT_WORKERS = 3             # parallel LLM extractions
EXTRACT_MAX_TOKENS = 16000      # per-competitor output budget (reasoning models
                                # burn tokens on internal reasoning — match skill.py)

logger = logging.getLogger("reference")


class TimeoutError(Exception):
    """Raised when the reference build exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"reference build exceeded {MAX_RUNTIME_SECS}s max runtime")


def _install_timeout():
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUNTIME_SECS)


def _cancel_timeout():
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.alarm(0)


# ---------------------------------------------------------------------------
# LiteLLM client (sync, urllib — same pattern as skill.py)
# ---------------------------------------------------------------------------


class LiteLLMClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or LITELLM_BASE_URL).rstrip("/")
        self.api_key = api_key or LITELLM_API_KEY

    def _post(self, path: str, payload: dict, timeout: int) -> dict:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def chat(self, model: str, messages: list, max_tokens: int, temperature: float = 0.2) -> str:
        result = self._post(
            "/v1/chat/completions",
            {"model": model, "messages": messages, "max_tokens": max_tokens,
             "temperature": temperature, "stream": False},
            timeout=180,
        )
        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError("LLM returned no choices")
        content = (choices[0].get("message") or {}).get("content")
        if not content:
            raise RuntimeError(
                f"LLM returned empty content (finish_reason={choices[0].get('finish_reason')})"
            )
        return content

    def mcp_call(self, tool_name: str, arguments: dict, server_id: str) -> dict:
        try:
            return self._post(
                "/mcp-rest/tools/call",
                {"name": tool_name, "arguments": arguments, "server_id": server_id},
                timeout=60,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("MCP call %s failed: %s", tool_name, exc)
            return {}


# ---------------------------------------------------------------------------
# Profile loading
# ---------------------------------------------------------------------------


def load_profile(name: str) -> tuple[dict, dict]:
    """Load profiles/<name>.yml; return (profile, reference_block)."""
    path = None
    for suffix in (".yml", ".yaml", ".json"):
        candidate = PROFILES_DIR / f"{name}{suffix}"
        if candidate.is_file():
            path = candidate
            break
    if path is None:
        available = sorted(
            p.stem for p in PROFILES_DIR.iterdir() if p.suffix in (".yml", ".yaml", ".json")
        )
        raise ValueError(f"Profile '{name}' not found. Available: {', '.join(available) or '(none)'}")
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("title") or not data.get("segments"):
        raise ValueError(f"Profile {path.name} must have 'title' and 'segments'")
    ref = data.get("reference") or {}
    if not ref.get("aspects"):
        raise ValueError(f"Profile {path.name} has no reference.aspects block")
    return data, ref


def all_competitors(profile: dict) -> list[tuple[str, dict]]:
    """Flatten segments to [(segment_label, {name, search, note}), ...]."""
    out = []
    for seg in profile["segments"]:
        if isinstance(seg, str):
            seg = {"label": seg, "competitors": []}
        for comp in seg.get("competitors", []):
            if isinstance(comp, str):
                comp = {"name": comp}
            out.append((seg.get("label", ""), comp))
    return out


def reference_path(market: str) -> Path:
    return REFERENCES_DIR / f"{market}.json"


def reference_is_stale(market: str) -> bool:
    """True when the reference JSON is missing or older than stale_after_days."""
    path = reference_path(market)
    if not path.is_file():
        return True
    try:
        ref = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    days = int(ref.get("stale_after_days") or 365)
    built = str(ref.get("built_at") or "")
    try:
        built_dt = datetime.strptime(built, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - built_dt).days > days


def crawls_cache_path(market: str) -> Path:
    return REFERENCES_DIR / f"{market}.crawls.json"


CRAWL_CACHE_MAX_AGE_H = 24


def load_crawl_cache(market: str) -> dict:
    """Load cached crawls {url: {text, fetched_at}}; drop entries older than the max age."""
    path = crawls_cache_path(market)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    now = datetime.now(timezone.utc)
    fresh = {}
    for url, entry in data.items():
        try:
            fetched = datetime.strptime(str(entry.get("fetched_at", "")), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            if (now - fetched).total_seconds() < CRAWL_CACHE_MAX_AGE_H * 3600:
                fresh[url] = entry
        except ValueError:
            continue
    return fresh


def save_crawl_cache(market: str, cache: dict) -> None:
    try:
        REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
        crawls_cache_path(market).write_text(
            json.dumps(cache, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("Could not save crawl cache: %s", exc)


# ---------------------------------------------------------------------------
# MCP wrappers (via LiteLLM)
# ---------------------------------------------------------------------------


def _items_from(result: dict) -> list[dict]:
    if not isinstance(result, dict):
        return []
    for cand in (result.get("structuredContent"), result.get("result"), result):
        if not isinstance(cand, dict):
            continue
        for key in ("result", "results", "data", "items"):
            val = cand.get(key)
            if isinstance(val, list) and val and isinstance(val[0], dict):
                return val
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                parsed = json.loads(item.get("text", ""))
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict):
                for k in ("result", "results", "data", "items"):
                    val = parsed.get(k)
                    if isinstance(val, list) and val and isinstance(val[0], dict):
                        return val
    return []


def crawl_page(client: LiteLLMClient, url: str, max_chars: int = CRAWL_MAX_CHARS) -> str:
    """Fetch a page as markdown via mcp_crawl-crawl_page (best-effort)."""
    result = client.mcp_call("crawl_page", {"url": url, "max_chars": max_chars}, server_id="mcp_crawl")
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                parsed = json.loads(item["text"])
                if isinstance(parsed, dict) and parsed.get("content"):
                    return str(parsed["content"])[:max_chars]
            except (json.JSONDecodeError, TypeError):
                pass
    return ""


def search_web(client: LiteLLMClient, query: str, max_results: int = MARKET_MAX_ITEMS) -> list[dict]:
    """Web search via mcp_search-search_web (best-effort)."""
    result = client.mcp_call(
        "search_web", {"query": query, "max_results": max_results}, server_id="mcp_search"
    )
    items = []
    seen = set()
    for item in _items_from(result):
        url = str(item.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        items.append({
            "title": str(item.get("title") or "Untitled"),
            "url": url,
            "snippet": str(item.get("snippet") or item.get("content") or "")[:400],
            "source": str(item.get("source") or ""),
        })
        if len(items) >= max_results:
            break
    return items


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------


def _strip_json(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*?)\n?```\s*$", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text


def _parse_json(text: str) -> dict:
    """Parse LLM JSON output, tolerating stray prose around the object."""
    text = _strip_json(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _competitor_extraction_prompt(profile: dict, ref: dict, segment: str, comp: dict) -> str:
    aspects = "\n".join(f"  - {a['id']} ({a['label']}, type {a['type']})" for a in ref["aspects"])
    ratings = "\n".join(f"  - {a['id']} ({a['label']})" for a in ref.get("rating_aspects", []))
    sites = ", ".join(ref.get("review_sites", [])) or "(none)"
    note = f"\nCompetitor note: {comp['note']}" if comp.get("note") else ""
    return textwrap.dedent(f"""\
        You are extracting competitor data for an ANNUAL market reference.
        Market: {profile['title']}. Competitor: {comp['name']} (segment: {segment}).{note}

        Extract these aspects (use EXACTLY these ids):
        {aspects}

        Rubric ratings (1-5 integers, SAME rubric applied to every competitor):
        {ratings}
        Score conservatively from the material only; 3 = solid/average,
        4 = strong, 5 = best-in-class. One-line rationale (<= 20 words).

        Rules:
        - Use ONLY facts present in the provided source material. If a fact
          is not present, set its value to null (do not guess).
        - SOURCE PRIORITY: prefer the competitor's OWN website (primary
          source) for every fact. Use review/comparison sites (SafeHome.org,
          security.org, findprices.com, etc.) ONLY when the vendor pages in
          the material lack the fact, or for review_data scores. Set the
          source/url to the vendor page whenever the fact appears there.
          Review-site numbers still need estimated: true.
        - Distinct products: if the material covers multiple products of the
          same company (e.g. Xfinity Shield app vs Xfinity Home pro system),
          attribute each fact to THIS competitor's product only; never copy
          another product's pricing/features into this row.
        - usd: value = number (USD; per month for monthly aspects), display
          = short human string (e.g. "$10/mo (Standard)").
        - bool: value = true/false, display = "yes"/"no".
        - list: value = list of short strings, display = comma-joined.
        - text: value = short string (<= 12 words).
        - Every non-null fact needs: source (site name), url (exact URL from
          the material), as_of ("YYYY-MM").
        - estimated: true when the number comes from a comparison/review site
          rather than the vendor, or is an estimate (e.g. quote-based pricing).
        - review_data: for each of the review sites ({sites}) present in the
          material that gives {comp['name']} an explicit score/rating,
          add {{"site", "score", "url", "as_of"}}. Empty list if none.
        - Output ONLY JSON, no prose, no code fences:
        {{"facts": {{...}}, "ratings": {{...}}, "review_data": [...]}}
    """)


def _market_extraction_prompt(profile: dict, ref: dict) -> str:
    indicators = "\n".join(
        f"  - {i['competitor']} (type: {i['type']}, source hint: {i.get('source', '')})"
        for i in ref.get("share_indicators", [])
    ) or "  - (none configured)"
    return textwrap.dedent(f"""\
        You are consolidating MARKET CONTEXT for an annual market reference.
        Market: {profile['title']}. Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}.

        From the provided web-search findings (free sources only), produce JSON:
        1. market_size: 2-4 INDEPENDENT estimates (prefer distinct research
           firms) that have a CONCRETE dollar figure in the findings.
           OMIT any estimate for which the findings contain no concrete
           number (never emit null/placeholder entries). Each:
           {{"estimate_usd_b": number (billions USD), "year": int (base year),
             "cagr_pct": number or null, "horizon_year": int or null,
             "scope": short string (e.g. "global home security systems"),
             "source": publisher name, "url": exact URL from the findings,
             "note": e.g. "free page summary; full report paywalled"}}
           Never present paywalled report contents that were not in the
           findings; flag when only free coverage is available.
        2. market_context: 2-4 short bullets (growth drivers, regional notes,
           adoption stats) — each must trace to a finding; append the source
           name + URL inline like "(per Publisher, url)".
        3. share_indicators: one entry per configured (competitor, type) pair
           below — a competitor may appear MULTIPLE times with different
           types (e.g. revenue + install_base). Each:
           {{"competitor", "type" (revenue|survey_share|pr_estimate|
             install_base|other — use the configured type), "value" (short
             string, e.g. "$543M FY2025 revenue" or "~9.5% US market share"),
             "pct": number or null (ONLY when the value is a percentage
             share comparable across competitors — else null),
             "as_of" ("YYYY" or "YYYY-MM"), "source", "url",
             "note": what exactly the number measures (scope, geography,
             methodology). If no free data is found for a competitor, set
             value to null and note "no free data found this period".}}
           Private companies: use survey_share / pr_estimate / install_base /
           other proxies — never fabricate revenue.
        Configured share indicators:
        {indicators}
        Output ONLY JSON: {{"market_size": [...], "market_context": [...],
        "share_indicators": [...]}}
    """)


def _extract_competitor(
    client: LiteLLMClient, profile: dict, ref: dict, segment: str, comp: dict, sources_text: str
) -> dict:
    """One LLM call (with a single retry) → {facts, ratings, review_data}."""
    prompt = _competitor_extraction_prompt(profile, ref, segment, comp)
    context = (
        f"Source material for {comp['name']} (vendor pages, comparison sites, review sites):\n\n"
        f"{sources_text[:CONTEXT_MAX_CHARS]}"
    )
    last_exc: Optional[Exception] = None
    for attempt in (1, 2):
        try:
            out = client.chat(
                MODEL_ALIAS,
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": context},
                ],
                max_tokens=EXTRACT_MAX_TOKENS,
                temperature=0.2,
            )
            break
        except Exception as exc:  # noqa: BLE001 — retry once (transient/timeout)
            last_exc = exc
            if attempt == 1:
                logger.warning("Extraction attempt 1 failed for %s (%s) — retrying", comp["name"], exc)
                time.sleep(2)
    else:
        raise RuntimeError(f"extraction failed after retry: {last_exc}")
    data = _parse_json(out)
    facts = data.get("facts") or {}
    ratings = data.get("ratings") or {}
    review_data = data.get("review_data") or []
    if not isinstance(facts, dict) or not isinstance(ratings, dict):
        raise ValueError("extraction JSON missing facts/ratings objects")
    return {
        "name": comp["name"],
        "segment": segment,
        "note": str(comp.get("note") or ""),
        "facts": facts,
        "ratings": ratings,
        "review_data": review_data if isinstance(review_data, list) else [],
    }


def _extract_market(client: LiteLLMClient, profile: dict, ref: dict, findings_text: str) -> dict:
    """One LLM call (with a single retry) → {market_size, market_context, share_indicators}."""
    prompt = _market_extraction_prompt(profile, ref)
    last_exc: Optional[Exception] = None
    out = ""
    for attempt in (1, 2):
        try:
            out = client.chat(
                MODEL_ALIAS,
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": f"Web-search findings:\n\n{findings_text[:CONTEXT_MAX_CHARS]}"},
                ],
                max_tokens=EXTRACT_MAX_TOKENS,
                temperature=0.2,
            )
            break
        except Exception as exc:  # noqa: BLE001 — retry once
            last_exc = exc
            if attempt == 1:
                logger.warning("Market consolidation attempt 1 failed (%s) — retrying", exc)
                time.sleep(2)
    else:
        raise RuntimeError(f"market consolidation failed after retry: {last_exc}")
    data = _parse_json(out)
    return {
        "market_size": data.get("market_size") or [],
        "market_context": data.get("market_context") or [],
        "share_indicators": data.get("share_indicators") or [],
    }


# ---------------------------------------------------------------------------
# Build orchestration
# ---------------------------------------------------------------------------


def build_reference(market: str, force: bool = False) -> dict:
    """Build (or refresh) references/<market>.json. Returns the reference."""
    profile, ref = load_profile(market)
    path = reference_path(market)

    existing: dict = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Existing reference unreadable — starting fresh")
            existing = {}

    stale_days = int(ref.get("stale_after_days", 365))
    built_at = str(existing.get("built_at") or "")
    if not force and built_at:
        try:
            age = (datetime.now(timezone.utc) - datetime.strptime(built_at, "%Y-%m-%d")).days
            if age < stale_days:
                logger.info(
                    "Reference fresh (built %s, age %d < %d days) — skipping build. "
                    "Use --force to rebuild.",
                    built_at, age, stale_days,
                )
                return existing
        except ValueError:
            pass

    _install_timeout()
    try:
        client = LiteLLMClient()
        today = datetime.now(timezone.utc)
        competitors = all_competitors(profile)

        # ---- Phase 1: crawl sources (parallel, non-fatal per page; cached) ----
        sources = ref.get("sources") or []
        cache = load_crawl_cache(market)
        to_crawl = [s["url"] for s in sources if s["url"] not in cache]
        pages: dict[str, str] = {u: e["text"] for u, e in cache.items() if len(str(e.get("text") or "")) > 200}
        if to_crawl:
            logger.info("Crawling %d source pages (%d from cache)...", len(to_crawl), len(pages))
            with ThreadPoolExecutor(max_workers=CRAWL_WORKERS) as pool:
                futures = {pool.submit(crawl_page, client, u): u for u in to_crawl}
                for fut in as_completed(futures):
                    u = futures[fut]
                    try:
                        text = fut.result()
                        if text:
                            pages[u] = text
                            cache[u] = {"text": text, "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}
                            logger.info("  crawled %s (%d chars)", u, len(text))
                        else:
                            logger.warning("  crawl empty: %s", u)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("  crawl failed %s: %s", u, exc)
            save_crawl_cache(market, cache)
        else:
            logger.info("All %d source pages served from crawl cache", len(pages))

        # ---- Phase 2: per-competitor extraction (parallel, ordered) ----
        def _extract_one(segment: str, comp: dict) -> dict:
            name = comp["name"]
            # Sources for this competitor: named matches + [all] sources.
            my_sources = [
                s for s in sources
                if name in (s.get("competitors") or []) or "all" in (s.get("competitors") or [])
            ]
            chunks = []
            for s in my_sources:
                text = pages.get(s["url"])
                if not text:
                    continue
                chunks.append(f"===== SOURCE: {s['url']} =====\n{text}")
            sources_text = "\n\n".join(chunks)
            if not sources_text:
                logger.warning("No crawlable sources for %s — keeping prior data", name)
            logger.info("Extracting %s (%d chars of source material)...", name, len(sources_text))
            try:
                entry = _extract_competitor(client, profile, ref, segment, comp, sources_text)
                n_facts = sum(1 for f in entry["facts"].values() if isinstance(f, dict) and f.get("value") is not None)
                logger.info("  → %s: %d facts filled", name, n_facts)
                return entry
            except Exception as exc:  # noqa: BLE001 — non-fatal per competitor
                logger.error("Extraction failed for %s: %s", name, exc)
                prior = next((c for c in existing.get("competitors", []) if c.get("name") == name), None)
                if prior:
                    entry = dict(prior)
                    entry["stale"] = True
                else:
                    entry = {
                        "name": name, "segment": segment,
                        "note": str(comp.get("note") or ""),
                        "facts": {}, "ratings": {}, "review_data": [], "stale": True,
                    }
                return entry

        competitor_entries: list[dict] = []
        with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as pool:
            futures = [pool.submit(_extract_one, seg, comp) for seg, comp in competitors]
            for fut in as_completed(futures):
                competitor_entries.append(fut.result())
        # Restore profile order (as_completed is unordered).
        order = {c["name"]: i for i, (_, c) in enumerate(competitors)}
        competitor_entries.sort(key=lambda e: order.get(e["name"], 99))

        # ---- Phase 3: market context (search + crawl top results + consolidate) ----
        findings: list[str] = []
        queries = list(ref.get("market_size_queries") or []) + list(profile.get("market_size_queries") or [])
        for query in dict.fromkeys(queries):
            logger.info("Market search: %r", query)
            items = search_web(client, query)
            for item in items:
                findings.append(
                    f"- {item['title']} | {item['source'] or item['url']}\n"
                    f"  URL: {item['url']}\n  {item['snippet']}"
                )
            # Snippets often lack the concrete figures — crawl the top result
            # pages (research-firm free summaries, vendor IR pages, etc.).
            for item in items[:3]:
                if item["url"] in cache:
                    continue
                try:
                    text = crawl_page(client, item["url"], max_chars=3000)
                except Exception:  # noqa: BLE001
                    text = ""
                if len(text) > 200:
                    cache[item["url"]] = {"text": text[:3000], "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}
                    findings.append(
                        f"===== PAGE CONTENT: {item['url']} =====\n{text[:3000]}"
                    )
        save_crawl_cache(market, cache)
        # Share-indicator source hints (search for the configured sources too).
        for ind in ref.get("share_indicators", []):
            q = str(ind.get("query") or "").strip()
            if not q:
                src_hint = str(ind.get("source") or "")
                q = f"{ind['competitor']} {src_hint}".strip()
            if q:
                logger.info("Share search: %r", q)
                for item in search_web(client, q):
                    findings.append(
                        f"- {item['title']} | {item['source'] or item['url']}\n"
                        f"  URL: {item['url']}\n  {item['snippet']}"
                    )
        findings_text = "\n".join(dict.fromkeys(findings)) or "(no web findings)"
        logger.info("Market findings: %d items", len(findings))
        try:
            market_data = _extract_market(client, profile, ref, findings_text)
        except Exception as exc:  # noqa: BLE001 — non-fatal
            logger.error("Market consolidation failed: %s — keeping prior values", exc)
            market_data = {
                "market_size": existing.get("market_size", []),
                "market_context": existing.get("market_context", []),
                "share_indicators": existing.get("share_indicators", []),
            }

        # ---- Phase 4: assemble + save ----
        reference = {
            "market": market,
            "title": profile["title"],
            "built_at": today.strftime("%Y-%m-%d"),
            "stale_after_days": stale_days,
            "market_size": market_data["market_size"],
            "market_context": market_data["market_context"],
            "share_indicators": _merge_share_indicators(
                existing.get("share_indicators") or [], market_data["share_indicators"]
            ),
            "competitors": competitor_entries,
        }
        REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        logger.info("Reference saved: %s", path)
        return reference

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# Deterministic rendering (no LLM)
# ---------------------------------------------------------------------------


def _esc(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _fact_display(fact: Any) -> str:
    """Render one fact dict ({value, display, source, url, ...}) as HTML."""
    if not isinstance(fact, dict) or fact.get("value") is None:
        return "<span class='na'>–</span>"
    if isinstance(fact.get("value"), list):
        disp = ", ".join(str(v) for v in fact["value"])
    else:
        disp = str(fact.get("display") or fact.get("value"))
    html = _esc(disp)
    if fact.get("estimated"):
        html += " <span class='est' title='Estimated (comparison/review source)'>~</span>"
    url = fact.get("url")
    if url:
        src = _esc(fact.get("source") or "source")
        html += f" <a class='src' href='{_esc(url)}' target='_blank' rel='noopener' title='{src}'>[s]</a>"
    return html


HEAT_COLORS = {1: "#dc2626", 2: "#ea580c", 3: "#ca8a04", 4: "#65a30d", 5: "#16a34a"}


def _bar_chart(indicators: list[dict]) -> str:
    """Horizontal bar chart for share indicators that have a pct value."""
    rows = [i for i in indicators if isinstance(i.get("pct"), (int, float))]
    if not rows:
        return ""
    rows.sort(key=lambda i: -i["pct"])
    max_pct = max(i["pct"] for i in rows) or 1
    out = ['<div class="chart">', '<p class="chart-title">Market share indicators (labeled by type)</p>']
    for i in rows:
        width = max(2, round(100 * i["pct"] / max_pct))
        label = _esc(i.get("competitor", ""))
        note = _esc(i.get("note") or "")
        out.append(
            f"<div class='bar-row'>"
            f"<div class='bar-label' title='{note}'>{label}</div>"
            f"<div class='bar-track'><div class='bar-fill' style='width:{width}%'></div></div>"
            f"<div class='bar-val'>{i['pct']}% <span class='bar-type'>({_esc(i.get('type', ''))})</span></div>"
            f"</div>"
        )
    out.append("</div>")
    return "\n".join(out)


def _share_table(indicators: list[dict]) -> str:
    """Table for ALL share indicators (mixed types, clearly labeled)."""
    if not indicators:
        return ""
    rows = []
    for i in indicators:
        val = i.get("value")
        rows.append(
            "<tr>"
            f"<td>{_esc(i.get('competitor', ''))}</td>"
            f"<td><span class='chip'>{_esc(i.get('type', ''))}</span></td>"
            f"<td>{_esc(val) if val else '<span class=na>–</span>'}</td>"
            f"<td>{_esc(i.get('as_of', ''))}</td>"
            f"<td>{_esc(i.get('source', ''))}"
            + (f" <a href='{_esc(i['url'])}' target='_blank' rel='noopener'>[src]</a>" if i.get("url") else "")
            + "</td>"
            f"<td class='note'>{_esc(i.get('note', ''))}</td>"
            "</tr>"
        )
    return (
        '<div class="ref-section"><h3>Competitor size / share indicators (labeled by type)</h3>'
        '<table class="ref-table"><thead><tr>'
        "<th>Competitor</th><th>Type</th><th>Indicator</th><th>As of</th><th>Source</th><th>What it measures</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        "<p class='note'>Types: revenue = public-company financials; survey_share = consumer/brand surveys; "
        "pr_estimate = company press-release estimate; install_base = usage/install statistics; "
        "other = scale proxy. Proxies are not directly comparable to revenue.</p></div>"
    )


def _market_size_block(ref: dict) -> str:
    sizes = [s for s in (ref.get("market_size") or []) if isinstance(s.get("estimate_usd_b"), (int, float))]
    if not sizes:
        return ""
    rows = []
    for s in sizes:
        cagr = f"{s['cagr_pct']}%" if isinstance(s.get("cagr_pct"), (int, float)) else "–"
        horizon = f"→ {s.get('horizon_year', '?')}" if s.get("horizon_year") else ""
        rows.append(
            "<tr>"
            f"<td>${_esc(s.get('estimate_usd_b', '?'))}B</td>"
            f"<td>{_esc(s.get('year', '?'))}</td>"
            f"<td>{cagr}</td>"
            f"<td>{_esc(horizon)}</td>"
            f"<td>{_esc(s.get('scope', ''))}</td>"
            f"<td>{_esc(s.get('source', ''))}"
            + (f" <a href='{_esc(s['url'])}' target='_blank' rel='noopener'>[src]</a>" if s.get("url") else "")
            + "</td>"
            f"<td class='note'>{_esc(s.get('note', ''))}</td>"
            "</tr>"
        )
    context = "".join(f"<li>{_esc(c)}</li>" for c in ref.get("market_context") or [])
    return (
        '<div class="ref-section"><h3>Market size (independent free estimates — presented as a range)</h3>'
        '<table class="ref-table"><thead><tr>'
        "<th>Estimate</th><th>Base year</th><th>CAGR</th><th>Horizon</th><th>Scope</th><th>Source</th><th>Note</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
        + (f'<ul class="ctx">{context}</ul>' if context else "")
        + "</div>"
    )


def _comparison_table(ref: dict, ref_block: dict, mode: str) -> str:
    """Competitor × aspect table. mode: compact (top aspects + rubric
    scores) or full (all aspects; ratings get their own heatmap block)."""
    aspects = ref_block["aspects"]
    rating_aspects = ref_block.get("rating_aspects") or []
    if mode == "compact":
        # Top aspects: first 8 that have data for >= 50% of competitors.
        comps = ref.get("competitors") or []
        n = max(1, len(comps))
        picked = []
        for a in aspects:
            filled = sum(
                1 for c in comps
                if ((c.get("facts") or {}).get(a["id"]) or {}).get("value") is not None
            )
            if filled >= n / 2:
                picked.append(a)
            if len(picked) >= 8:
                break
        if not picked:
            picked = aspects[:8]
        aspects = picked
    head = "".join(f"<th>{_esc(a['label'])}</th>" for a in aspects)
    # Compact mode appends the rubric score columns (design: top ~8 aspects
    # + 4 rubric scores); full mode keeps the dedicated ratings heatmap.
    compact_ratings = mode == "compact" and bool(rating_aspects)
    if compact_ratings:
        head += "".join(f"<th>{_esc(a['label'])}</th>" for a in rating_aspects)
    body = []
    for comp in ref.get("competitors", []):
        facts = comp.get("facts") or {}
        cells = "".join(f"<td>{_fact_display(facts.get(a['id']))}</td>" for a in aspects)
        if compact_ratings:
            ratings = comp.get("ratings") or {}
            for a in rating_aspects:
                r = ratings.get(a["id"]) or {}
                score = r.get("score")
                if isinstance(score, int) and 1 <= score <= 5:
                    rationale = _esc(r.get("rationale") or "")
                    cells += (
                        f"<td class='heat' style='background:{HEAT_COLORS[score]}' "
                        f"title='{rationale}'><b>{score}</b></td>"
                    )
                else:
                    cells += "<td class='na'>–</td>"
        stale = " <span class='chip stale-chip'>stale</span>" if comp.get("stale") else ""
        body.append(f"<tr><th class='rowhead'>{_esc(comp['name'])}{stale}</th>{cells}</tr>")
    return (
        '<div class="table-scroll"><table class="ref-table cmp">'
        f"<thead><tr><th>Competitor</th>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _ratings_block(ref: dict, ref_block: dict) -> str:
    """Ratings heatmap: rows = competitors, cols = rating aspects."""
    rating_aspects = ref_block.get("rating_aspects") or []
    if not rating_aspects:
        return ""
    head = "".join(f"<th>{_esc(a['label'])}</th>" for a in rating_aspects)
    body = []
    for comp in ref.get("competitors", []):
        ratings = comp.get("ratings") or {}
        cells = []
        for a in rating_aspects:
            r = ratings.get(a["id"]) or {}
            score = r.get("score")
            if isinstance(score, int) and 1 <= score <= 5:
                rationale = _esc(r.get("rationale") or "")
                cells.append(
                    f"<td class='heat' style='background:{HEAT_COLORS[score]}' "
                    f"title='{rationale}'><b>{score}</b></td>"
                )
            else:
                cells.append("<td class='na'>–</td>")
        reviews = " · ".join(
            f"{_esc(r.get('site', ''))} {_esc(r.get('score', ''))}"
            for r in comp.get("review_data", [])
        )
        body.append(
            f"<tr><th class='rowhead'>{_esc(comp['name'])}</th>{''.join(cells)}"
            f"<td class='note'>{reviews}</td></tr>"
        )
    return (
        '<div class="ref-section"><h3>Aspect ratings (LLM rubric 1–5 · review-site scores where available)</h3>'
        '<div class="table-scroll"><table class="ref-table ratings">'
        f"<thead><tr><th>Competitor</th>{head}<th>Review scores</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody></table></div>"
        "<p class='note'>Rubric scores are LLM-consistent (same rubric, all competitors); "
        "review-site scores are shown for reference only and are not averaged in. "
        "Hover a cell for the rationale.</p></div>"
    )


REF_CSS = """
.ref { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  color: #1a1d21; line-height: 1.5; }
.ref h3 { font-size: 1.05rem; margin: 18px 0 8px; }
.ref .ref-section { margin: 14px 0; }
.ref .ref-table { border-collapse: collapse; width: 100%; font-size: 0.86rem; margin: 8px 0; }
.ref .ref-table th, .ref .ref-table td { border: 1px solid #d8dde3; padding: 6px 8px; text-align: left;
  vertical-align: top; }
.ref .ref-table thead th { background: #eef1f4; font-weight: 600; }
.ref .ref-table .rowhead { background: #f7f8fa; font-weight: 600; white-space: nowrap; }
.ref .ref-table .note { color: #5a6472; font-size: 0.8rem; max-width: 260px; }
.ref .na { color: #9aa3af; }
.ref .est { color: #b45309; font-weight: 700; }
.ref .src { font-size: 0.7rem; color: #1d4ed8; text-decoration: none; }
.ref .chip { display: inline-block; background: #e2e8f0; border-radius: 8px; padding: 0 7px;
  font-size: 0.72rem; color: #334155; }
.ref .stale-chip { background: #fef3c7; color: #92400e; }
.ref .table-scroll { overflow-x: auto; }
.ref .chart { margin: 10px 0; }
.ref .chart-title { font-weight: 600; font-size: 0.9rem; margin: 0 0 6px; }
.ref .bar-row { display: flex; align-items: center; gap: 8px; margin: 5px 0; }
.ref .bar-label { flex: 0 0 130px; font-size: 0.82rem; font-weight: 600; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.ref .bar-track { flex: 1; background: #e5e9ee; border-radius: 4px; height: 16px; }
.ref .bar-fill { background: #2563eb; height: 16px; border-radius: 4px; }
.ref .bar-val { flex: 0 0 110px; font-size: 0.8rem; text-align: right; }
.ref .bar-type { color: #5a6472; font-size: 0.72rem; }
.ref .heat { text-align: center; color: #fff; }
.ref ul.ctx { margin: 8px 0; padding-left: 20px; font-size: 0.88rem; }
@media (prefers-color-scheme: dark) {
  .ref { color: #e6e8eb; }
  .ref .ref-table th, .ref .ref-table td { border-color: #2c333d; }
  .ref .ref-table thead th { background: #1c2129; }
  .ref .ref-table .rowhead { background: #171b21; }
  .ref .ref-table .note { color: #9aa3af; }
  .ref .na { color: #6b7480; }
  .ref .est { color: #e0a33a; }
  .ref .src { color: #7aa6ff; }
  .ref .chip { background: #232830; color: #cbd5e1; }
  .ref .stale-chip { background: #3a2f14; color: #e0a33a; }
  .ref .bar-track { background: #232830; }
  .ref .bar-type { color: #9aa3af; }
}
"""


def render_standalone_html(ref: dict, ref_block: dict, mode: str = "full") -> str:
    """Wrap the reference section in a self-contained HTML document."""
    html = render_reference_html(ref, ref_block, mode=mode)
    return (
        "<!DOCTYPE html>\n<html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{_esc(ref.get('title', ''))} — Annual Reference</title>"
        "<style>body{margin:0;padding:16px;background:#f4f5f7;}"
        "@media (prefers-color-scheme: dark){body{background:#0f1216;}}</style>"
        f"</head><body><div style='max-width:1100px;margin:0 auto;'>{html}</div></body></html>\n"
    )


def render_reference_html(ref: dict, ref_block: dict, mode: str = "full") -> str:
    """Render the reference section as self-contained HTML (no JS)."""
    parts = [f'<div class="ref"><style>{REF_CSS}</style>']
    as_of = _esc(ref.get("built_at", ""))
    parts.append(
        f'<p class="meta" style="color:#5a6472;font-size:0.85rem;">'
        f"Annual reference data · as of {as_of} · free sources only · paywalled figures flagged · "
        "rebuilt yearly (January)</p>"
    )
    parts.append(_market_size_block(ref))
    parts.append(_bar_chart(ref.get("share_indicators") or []))
    parts.append(_share_table(ref.get("share_indicators") or []))
    parts.append(
        f'<div class="ref-section"><h3>Competitor comparison'
        f'{" (compact)" if mode == "compact" else ""}</h3>'
        + _comparison_table(ref, ref_block, mode) + "</div>"
    )
    if mode == "full":
        parts.append(_ratings_block(ref, ref_block))
    parts.append("</div>")
    return "\n".join(parts)


def render_reference_md(ref: dict, ref_block: dict) -> str:
    """Render the reference as a markdown section (for the .md artifact)."""
    lines = [
        f"## Competitor Comparison (annual reference, as of {ref.get('built_at', '?')})",
        "",
        "*Free sources only · paywalled figures flagged · rebuilt yearly*",
        "",
        "### Market size (independent free estimates)",
        "",
    ]
    for s in ref.get("market_size") or []:
        if not isinstance(s.get("estimate_usd_b"), (int, float)):
            continue
        cagr = f"{s['cagr_pct']}% CAGR" if isinstance(s.get("cagr_pct"), (int, float)) else "CAGR n/a"
        lines.append(
            f"- **${s.get('estimate_usd_b', '?')}B** ({s.get('year', '?')}, {cagr}, "
            f"{s.get('scope', '')}) — [{s.get('source', 'source')}]({s.get('url', '')})"
            + (f" — {s['note']}" if s.get("note") else "")
        )
    lines += ["", "### Share indicators (labeled by type)", ""]
    for i in ref.get("share_indicators") or []:
        val = i.get("value") or "no free data"
        lines.append(
            f"- **{i.get('competitor')}** [{i.get('type')}]: {val} ({i.get('as_of', '')}) — {i.get('source', '')}"
            + (f" — {i['note']}" if i.get("note") else "")
        )
    lines += ["", "### Comparison", "",
              "| Competitor | " + " | ".join(a["label"] for a in ref_block["aspects"]) + " |",
              "|---" * (len(ref_block["aspects"]) + 1) + "|"]
    for comp in ref.get("competitors", []):
        facts = comp.get("facts") or {}
        cells = []
        for a in ref_block["aspects"]:
            f = facts.get(a["id"]) or {}
            if f.get("value") is None:
                cells.append("–")
            elif isinstance(f.get("value"), list):
                cells.append(", ".join(str(v) for v in f["value"]))
            else:
                cells.append(str(f.get("display") or f.get("value")))
        lines.append(f"| {comp['name']} | " + " | ".join(cells) + " |")
    lines += ["", "### Ratings (LLM rubric 1–5)", ""]
    ra = ref_block.get("rating_aspects") or []
    lines.append("| Competitor | " + " | ".join(a["label"] for a in ra) + " |")
    lines.append("|---" * (len(ra) + 1) + "|")
    for comp in ref.get("competitors", []):
        ratings = comp.get("ratings") or {}
        cells = []
        for a in ra:
            r = ratings.get(a["id"]) or {}
            cells.append(str(r.get("score")) if r.get("score") is not None else "–")
        lines.append(f"| {comp['name']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _merge_competitor_entry(old: dict | None, new: dict) -> dict:
    """Merge a re-extracted competitor entry over the prior one: new non-null
    facts win; new nulls keep the prior value (protects hand fixes and
    non-deterministic extraction losses)."""
    if not old:
        return new
    merged = dict(new)
    old_facts = old.get("facts") or {}
    new_facts = dict(merged.get("facts") or {})
    for aid, of in old_facts.items():
        nf = new_facts.get(aid)
        if (not isinstance(nf, dict) or nf.get("value") is None) and \
                isinstance(of, dict) and of.get("value") is not None:
            new_facts[aid] = of  # keep prior non-null fact
    merged["facts"] = new_facts
    for key in ("ratings", "review_data"):
        if not merged.get(key) and old.get(key):
            merged[key] = old[key]
    merged["note"] = merged.get("note") or old.get("note") or ""
    merged.pop("stale", None)
    return merged


def retry_competitors(market: str, names: list[str]) -> dict:
    """Re-extract the named competitors from the cached crawls and merge them
    into the existing reference (no re-crawl, no market phase)."""
    profile, ref = load_profile(market)
    path = reference_path(market)
    if not path.is_file():
        raise ValueError(f"No existing reference at {path} — run a full build first")
    reference = json.loads(path.read_text(encoding="utf-8"))
    cache = load_crawl_cache(market)
    pages = {u: e["text"] for u, e in cache.items() if len(str(e.get("text") or "")) > 200}
    if not pages:
        logger.warning("Crawl cache is empty/stale — retrying will produce sparse results")
    client = LiteLLMClient()
    wanted = {n.strip() for n in names if n.strip()}
    for segment, comp in all_competitors(profile):
        name = comp["name"]
        if name not in wanted:
            continue
        my_sources = [
            s for s in ref.get("sources", [])
            if name in (s.get("competitors") or []) or "all" in (s.get("competitors") or [])
        ]
        chunks = [f"===== SOURCE: {s['url']} =====\n{pages[s['url']]}"
                  for s in my_sources if s["url"] in pages]
        sources_text = "\n\n".join(chunks)
        if not sources_text:
            logger.warning("No cached material for %s — skipping", name)
            continue
        logger.info("Re-extracting %s (%d chars)...", name, len(sources_text))
        try:
            entry = _extract_competitor(client, profile, ref, segment, comp, sources_text)
            n_facts = sum(1 for f in entry["facts"].values() if isinstance(f, dict) and f.get("value") is not None)
            logger.info("  → %s: %d facts filled", name, n_facts)
            prior = next((c for c in reference["competitors"] if c.get("name") == name), None)
            entry = _merge_competitor_entry(prior, entry)
            for i, c in enumerate(reference["competitors"]):
                if c.get("name") == name:
                    reference["competitors"][i] = entry
                    break
            else:
                reference["competitors"].append(entry)
        except Exception as exc:  # noqa: BLE001
            logger.error("Re-extraction failed for %s: %s", name, exc)
    path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Reference updated: %s", path)
    return reference


def _merge_share_indicators(old: list[dict], new: list[dict]) -> list[dict]:
    """Merge share indicators by (competitor, type): prefer the newest
    non-null entry per key; keep prior entries the new run missed."""
    merged: dict[str, dict] = {}
    for i in old or []:
        if isinstance(i, dict) and i.get("competitor"):
            key = f"{i['competitor']}:{i.get('type') or 'other'}"
            merged[key] = dict(i)
    for i in new or []:
        if not isinstance(i, dict) or not i.get("competitor"):
            continue
        key = f"{i['competitor']}:{i.get('type') or 'other'}"
        prev = merged.get(key)
        if prev and prev.get("pinned"):
            continue  # manually curated entry wins over fresh runs
        if i.get("value") is None and prev and prev.get("value") is not None:
            continue  # keep the prior non-null entry
        merged[key] = dict(i)
    # Preserve the configured order first, then any extras.
    keys = {f"{i['competitor']}:{i.get('type') or 'other'}" for i in (new or []) + (old or []) if isinstance(i, dict) and i.get("competitor")}
    return [merged[k] for k in keys if k in merged]


def retry_market(market: str) -> dict:
    """Re-run only the market-context phase (search + crawl + consolidate)
    and merge the result into the existing reference."""
    profile, ref = load_profile(market)
    path = reference_path(market)
    if not path.is_file():
        raise ValueError(f"No existing reference at {path} — run a full build first")
    reference = json.loads(path.read_text(encoding="utf-8"))
    client = LiteLLMClient()
    cache = load_crawl_cache(market)
    findings: list[str] = []
    queries = list(ref.get("market_size_queries") or []) + list(profile.get("market_size_queries") or [])
    for query in dict.fromkeys(queries):
        logger.info("Market search: %r", query)
        items = search_web(client, query)
        for item in items:
            findings.append(
                f"- {item['title']} | {item['source'] or item['url']}\n"
                f"  URL: {item['url']}\n  {item['snippet']}"
            )
        for item in items[:3]:
            if item["url"] in cache:
                continue
            try:
                text = crawl_page(client, item["url"], max_chars=3000)
            except Exception:  # noqa: BLE001
                text = ""
            if len(text) > 200:
                cache[item["url"]] = {"text": text[:3000], "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}
                findings.append(f"===== PAGE CONTENT: {item['url']} =====\n{text[:3000]}")
    save_crawl_cache(market, cache)
    for ind in ref.get("share_indicators", []):
        q = str(ind.get("query") or "").strip()
        if not q:
            src_hint = str(ind.get("source") or "")
            q = f"{ind['competitor']} {src_hint}".strip()
        if q:
            logger.info("Share search: %r", q)
            for item in search_web(client, q):
                findings.append(
                    f"- {item['title']} | {item['source'] or item['url']}\n"
                    f"  URL: {item['url']}\n  {item['snippet']}"
                )
    findings_text = "\n".join(dict.fromkeys(findings)) or "(no web findings)"
    logger.info("Market findings: %d items", len(findings))
    market_data = _extract_market(client, profile, ref, findings_text)
    reference["market_size"] = market_data["market_size"]
    reference["market_context"] = market_data["market_context"]
    reference["share_indicators"] = _merge_share_indicators(
        reference.get("share_indicators") or [], market_data["share_indicators"]
    )
    path.write_text(json.dumps(reference, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("Reference market phase updated: %s", path)
    return reference


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="market_research_brief annual reference (standalone)")
    parser.add_argument("--market", required=True, help="Profile name (e.g. smarthome_homesecurity)")
    parser.add_argument("--force", action="store_true", help="Rebuild even if a fresh reference exists")
    parser.add_argument("--render-only", action="store_true",
                        help="Skip the build; render the existing reference to HTML")
    parser.add_argument("--mode", choices=["compact", "full"], default="full",
                        help="Render mode (default: full)")
    parser.add_argument("--retry", default="",
                        help="Comma-separated competitor names to re-extract from the cached crawls "
                             "(e.g. 'Wyze,Eufy'); requires an existing reference")
    parser.add_argument("--retry-market", action="store_true",
                        help="Re-run only the market-context phase and merge into the existing reference")
    parser.add_argument("--populate-cache", action="store_true",
                        help="Crawl the profile's source pages into the crawl cache and exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    path = reference_path(args.market)

    if args.populate_cache:
        profile, ref = load_profile(args.market)
        client = LiteLLMClient()
        cache = load_crawl_cache(args.market)
        to_crawl = [s["url"] for s in ref.get("sources", []) if s["url"] not in cache]
        logger.info("Populating crawl cache: %d page(s) to fetch (%d cached)", len(to_crawl), len(cache))
        with ThreadPoolExecutor(max_workers=CRAWL_WORKERS) as pool:
            futures = {pool.submit(crawl_page, client, u): u for u in to_crawl}
            for fut in as_completed(futures):
                u = futures[fut]
                try:
                    text = fut.result()
                    if text:
                        cache[u] = {"text": text, "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}
                        logger.info("  cached %s (%d chars)", u, len(text))
                    else:
                        logger.warning("  crawl empty: %s", u)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("  crawl failed %s: %s", u, exc)
        save_crawl_cache(args.market, cache)
        print(f"Crawl cache: {crawls_cache_path(args.market)} ({len(cache)} pages)")
        return

    if args.retry:
        ref = retry_competitors(args.market, [n for n in args.retry.split(",") if n.strip()])
    elif args.retry_market:
        ref = retry_market(args.market)
    elif not path.is_file() or args.force:
        ref = build_reference(args.market, force=args.force)
    elif args.render_only:
        ref = json.loads(path.read_text(encoding="utf-8"))
    else:
        ref = build_reference(args.market, force=False)

    profile, ref_block = load_profile(args.market)
    doc = render_standalone_html(ref, ref_block, mode=args.mode)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    out = ARTIFACT_DIR / f"reference_{args.market}_{ts}.html"
    out.write_text(doc, encoding="utf-8")
    print(f"\nReference JSON: {path}")
    print(f"Sample HTML:    {out}")
    print(
        f"Built:          {ref.get('built_at')} · {len(ref.get('competitors', []))} competitors · "
        f"{len(ref.get('market_size', []))} market-size estimates · "
        f"{len(ref.get('share_indicators', []))} share indicators"
    )


if __name__ == "__main__":
    main()