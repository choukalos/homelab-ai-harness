#!/usr/bin/env python3
"""
investment_brief skill — portfolio status, dividend highlights, and market news.

Purpose:
  Query the InvestorHub database via LiteLLM's MCP gateway (mcp_mysql-run_query),
  aggregate holdings across ALL of the user's portfolios, fetch latest prices,
  dividend history, fundamentals, and news per holding, flag notable changes,
  synthesize a concise markdown brief (positions reported as portfolio weight
  % and P&L %, not dollars/share counts) via LLM, save the report as an
  artifact, and publish a self-contained HTML page (with clickable source
  links + InvestorHub link) to the public blog drop zone — all routed through
  LiteLLM. Never touch MCP servers directly.

Workflow:
  1. Validate inputs (user_email, focus, max_holdings, publish).
  2. Look up user by email via mcp_mysql-run_query on database `investorhub`.
  3. Look up ALL portfolios for the found user.
  4. Query holdings aggregated per ticker across all portfolios
     (Position JOIN Symbol, SUM shares, weighted-avg cost basis).
  5. Query latest prices from PriceHistory (JOIN Symbol, adjClose).
  6. Query dividend history from DividendHistory (JOIN Symbol, limit 5).
  7. Query fundamentals from SymbolFundamentals (JOIN Symbol).
  8. Call mcp_search-search_news via LiteLLM per ticker for market news.
  9. Flag notable items: price change >5% from 52-week high/low, dividend changes, negative news.
  10. Synthesize a concise markdown bullet-point brief via LLM chat completion
      (weights/P&L as percentages, clickable source links required).
  11. Save the brief as an artifact file (pruned to latest 3 per user).
  12. Render + publish HTML to the public drop zone
      (https://choukalos.com/files/briefs/investment_brief.html) unless publish=false.
  13. Fallback: general market brief for dividend stocks if no portfolios exist.

Constraints:
  - Max runtime: 300 seconds (5 minutes).
  - Read-only w.r.t. InvestorHub: no writes, no admin operations.
  - All MCP calls go through LiteLLM — never direct MCP server access.
  - SQL queries executed via mcp_mysql-run_query on database `investorhub`.
  - Artifacts saved to /home/chuck/data/media/investment_briefs/
  - Public HTML: /home/chuck/data/media/public/briefs/investment_brief.html
    (single-file retention, overwritten each run)

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
    os.environ.get("INVESTMENT_BRIEF_ARTIFACT_DIR", "/home/chuck/data/media/investment_briefs")
)
MAX_RUNTIME_SECS = int(os.environ.get("INVESTMENT_BRIEF_MAX_RUNTIME", "300"))
# Self-cleanup: keep only the N most recent brief artifacts per user.
MAX_ARTIFACTS = int(os.environ.get("INVESTMENT_BRIEF_MAX_ARTIFACTS", "3"))

# Public drop zone (single-file retention: latest brief, overwritten each run).
# Served at https://choukalos.com/files/briefs/investment_brief.html
PUBLISH_PATH = Path(
    os.environ.get("INVESTMENT_BRIEF_PUBLISH_PATH", "/home/chuck/data/media/public/briefs/investment_brief.html")
)
PUBLIC_BASE = os.environ.get("INVESTMENT_BRIEF_PUBLIC_BASE", "https://choukalos.com/files")
PUBLIC_ROOT = Path(os.environ.get("INVESTMENT_BRIEF_PUBLIC_ROOT", "/home/chuck/data/media/public"))
# Link target in the published page header (portfolio data source).
INVESTOR_HUB_URL = os.environ.get("INVESTMENT_BRIEF_HUB_URL", "https://invest.choukalos.com")

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("INVESTMENT_BRIEF_MODEL_ALIAS", "matrix-coder")

# InvestorHub database name
DATABASE = os.environ.get("INVESTORHUB_DATABASE", "investorhub")

logger = logging.getLogger("skill.investment_brief")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"investment_brief exceeded {MAX_RUNTIME_SECS}s max runtime")


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


class Holding:
    """A single portfolio holding with enriched data."""

    def __init__(self):
        self.ticker: str = ""
        self.name: str = ""
        self.shares: float = 0.0
        self.avg_cost: float = 0.0
        self.latest_price: float = 0.0
        self.previous_price: float = 0.0
        self.price_change_pct: float = 0.0
        self.forward_pe: float = 0.0
        self.market_cap: float = 0.0
        self.gross_margin: float = 0.0
        self.profit_margin: float = 0.0
        self.chowder_score: float = 0.0
        self.week52_high: float = 0.0
        self.week52_low: float = 0.0
        self.dividend_yield: float = 0.0
        self.dividends: list[dict] = []
        self.news: list[dict] = []
        self.flags: list[str] = []


# ---------------------------------------------------------------------------
# MCP wrappers — all calls go through LiteLLM
# ---------------------------------------------------------------------------


def _f(value: Any, default: float = 0.0) -> float:
    """NULL-safe float conversion (DB columns may be NULL)."""
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def _run_sql(client: Any, query: str, database: str = DATABASE) -> list[dict]:
    """
    Execute a SQL query via mcp_mysql-run_query through LiteLLM.

    All database access is read-only and routed through LiteLLM.
    """
    result = client.mcp_call(
        "run_query",
        {"sql": query, "database": database},
        server_id="mcp_mysql",
    )
    if not result:
        logger.warning("SQL returned no results: %s", query[:120])
        return []

    # Handle various response formats from the LiteLLM MCP gateway:
    # - raw MCP CallToolResult: {"content": [{type: text, text: json}], "structuredContent": ...}
    # - runner-normalized: {"result": {...}, "output": [{type: text, ...}]}
    # - flat: {"rows": [...]} / {"data": [...]}
    rows: Any = None

    # 1. structuredContent (raw MCP)
    sc = result.get("structuredContent")
    if isinstance(sc, dict):
        rows = sc.get("rows", sc.get("data", sc.get("results")))

    # 2. runner-normalized result key
    if rows is None and isinstance(result.get("result"), dict):
        inner = result["result"]
        rows = inner.get("rows", inner.get("data", inner.get("results")))

    # 3. flat top-level
    if rows is None:
        rows = result.get("rows", result.get("data"))

    # 4. JSON embedded in text content items (raw "content" or runner "output")
    if not isinstance(rows, list):
        for key in ("content", "output"):
            items = result.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not (isinstance(item, dict) and item.get("type") == "text"):
                    continue
                try:
                    extracted = json.loads(item.get("text", "[]"))
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(extracted, list):
                    rows = extracted
                    break
                if isinstance(extracted, dict):
                    # run_query returns {rows: [...], columns: [...], count: N}
                    rows = extracted.get("rows", extracted.get("data", [extracted]))
                    break
            if isinstance(rows, list):
                break

    # If rows is a single dict (not a list), wrap it
    if isinstance(rows, dict):
        rows = [rows]

    return rows if isinstance(rows, list) else []


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


def _search_news(client: Any, query: str, max_results: int = 5) -> list[dict]:
    """
    Search news via mcp_search-search_news through LiteLLM.

    Returns a list of news items as dicts with title, url, snippet.
    """
    result = client.mcp_call(
        "search_news",
        {"query": query, "max_results": max_results},
        server_id="mcp_search",
    )
    if not result:
        logger.warning("News search returned no results for: %s", query[:100])
        return []

    items: list[dict] = []
    results_list = _extract_news_items(result)

    for item in results_list:
        if len(items) >= max_results:
            break
        if isinstance(item, dict):
            items.append({
                "title": item.get("title", "Untitled"),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", item.get("content", ""))[:300],
                "source": item.get("source", item.get("engine", "news")),
            })

    logger.info("News search returned %d results for: %s", len(items), query[:80])
    return items


# ---------------------------------------------------------------------------
# SQL queries — all executed via mcp_mysql-run_query on database `investorhub`
# ---------------------------------------------------------------------------


def _lookup_user(client: Any, email: str) -> Optional[dict]:
    """
    Query 1: Look up a user by email on investorhub.User.
    """
    query = f"SELECT * FROM `{DATABASE}`.User WHERE email = '{email.replace(chr(39), chr(39) + chr(39))}'"
    rows = _run_sql(client, query)
    if not rows:
        logger.info("No user found for email: %s", email)
        return None
    logger.info("Found user: %s", rows[0].get("name", rows[0].get("id", "unknown")))
    return rows[0]


def _lookup_portfolios(client: Any, user_id: str) -> list[dict]:
    """
    Query 2: Look up portfolios for a user on investorhub.Portfolio.
    Note: DB column is 'userId' (camelCase), not 'user_id'.
    """
    query = (
        f"SELECT * FROM `{DATABASE}`.Portfolio "
        f"WHERE userId = '{user_id}'"
    )
    rows = _run_sql(client, query)
    logger.info("Found %d portfolio(s) for user %s", len(rows), user_id)
    return rows


def _lookup_holdings(client: Any, portfolio_ids: list[str], max_holdings: int = 50) -> list[dict]:
    """
    Query 3: Holdings across ALL of the user's portfolios — Position JOIN
    Symbol, aggregated per ticker (sum of shares, weighted-average cost
    basis). Note: DB uses camelCase column names (confirmed schema:
    id, portfolioId, symbolId, quantity, costBasis).
    """
    if not portfolio_ids:
        return []

    escaped = [str(pid).replace("'", "''") for pid in portfolio_ids]
    in_clause = ", ".join(f"'{pid}'" for pid in escaped)

    query = (
        f"SELECT s.ticker, s.name, "
        f"SUM(p.quantity) AS shares, "
        f"SUM(p.quantity * p.costBasis) / NULLIF(SUM(p.quantity), 0) AS avg_cost "
        f"FROM `{DATABASE}`.Position p "
        f"JOIN `{DATABASE}`.Symbol s ON p.symbolId = s.id "
        f"WHERE p.portfolioId IN ({in_clause}) "
        f"GROUP BY s.ticker, s.name "
        f"ORDER BY s.ticker "
        f"LIMIT {int(max_holdings)}"
    )
    rows = _run_sql(client, query)
    logger.info(
        "Found %d distinct holdings across %d portfolio(s)",
        len(rows), len(portfolio_ids),
    )
    return rows


def _lookup_latest_prices(client: Any, tickers: list[str]) -> dict[str, float]:
    """
    Query 4: Latest prices from investorhub.PriceHistory (JOIN Symbol),
    using adjClose (adjusted for splits/dividends), newest row per ticker.

    Returns {ticker: price}.
    """
    if not tickers:
        return {}

    escaped = [t.replace("'", "''") for t in tickers]
    in_clause = ", ".join(f"'{t}'" for t in escaped)

    query = (
        f"SELECT * FROM ("
        f"  SELECT s.ticker, ph.adjClose AS price, ph.date, "
        f"  ROW_NUMBER() OVER (PARTITION BY s.ticker ORDER BY ph.date DESC) AS rn "
        f"  FROM `{DATABASE}`.PriceHistory ph "
        f"  JOIN `{DATABASE}`.Symbol s ON ph.symbolId = s.id "
        f"  WHERE s.ticker IN ({in_clause}) "
        f") ranked WHERE rn = 1"
    )
    rows = _run_sql(client, query)

    prices: dict[str, float] = {}
    for row in rows:
        ticker = str(row.get("ticker", ""))
        prices[ticker] = _f(row.get("price"))

    logger.info("Retrieved latest prices for %d tickers", len(prices))
    return prices


def _lookup_prices_before(client: Any, tickers: list[str], date_str: str) -> dict[str, tuple[float, str]]:
    """
    Query 4b: Latest adjClose at or before `date_str` per ticker
    (investorhub.PriceHistory, split/dividend-adjusted). Used for
    YTD / 1Y / 5Y period-return calculations vs the S&P 500 benchmark.

    Returns {ticker: (price, date)} for tickers with history before the date.
    """
    if not tickers:
        return {}

    escaped = [t.replace("'", "''") for t in tickers]
    in_clause = ", ".join(f"'{t}'" for t in escaped)

    query = (
        f"SELECT * FROM ("
        f"  SELECT s.ticker, ph.adjClose AS price, ph.date, "
        f"    ROW_NUMBER() OVER (PARTITION BY s.ticker ORDER BY ph.date DESC) AS rn "
        f"  FROM `{DATABASE}`.PriceHistory ph "
        f"  JOIN `{DATABASE}`.Symbol s ON ph.symbolId = s.id "
        f"  WHERE s.ticker IN ({in_clause}) AND ph.date <= '{date_str}'"
        f") ranked WHERE rn = 1"
    )
    rows = _run_sql(client, query)

    prices: dict[str, tuple[float, str]] = {}
    for row in rows:
        ticker = str(row.get("ticker", "")).upper()
        price = _f(row.get("price"))
        if price > 0:
            prices[ticker] = (price, str(row.get("date", ""))[:10])

    logger.info("Retrieved %s prices for %d/%d tickers", date_str, len(prices), len(tickers))
    return prices


def _compute_market_context(
    client: Any,
    holdings: list[Holding],
    benchmark_ticker: str = "SPY",
) -> dict[str, Any]:
    """
    Compute portfolio period returns (YTD / 1Y / 5Y) vs the S&P 500
    benchmark, plus the portfolio-wide weighted dividend yield.

    Returns are price-based total returns using adjClose (adjusted for
    splits and dividends), weighted by CURRENT portfolio weights — a
    standard approximation that avoids needing historical position data.
    Periods with incomplete history report coverage (n/total tickers).
    """
    from datetime import datetime, timezone

    tickers = [h.ticker for h in holdings if h.latest_price > 0]
    if not tickers:
        return {}

    latest: dict[str, float] = {h.ticker: h.latest_price for h in holdings if h.latest_price > 0}
    shares: dict[str, float] = {h.ticker: h.shares for h in holdings}
    total_value = sum(shares[t] * latest[t] for t in latest)
    if total_value <= 0:
        return {}

    today = datetime.now(timezone.utc)
    periods = {
        "YTD": today.replace(month=1, day=1).strftime("%Y-%m-%d"),
        "1Y": today.replace(year=today.year - 1).strftime("%Y-%m-%d"),
        "5Y": today.replace(year=today.year - 5).strftime("%Y-%m-%d"),
    }

    # Benchmark's own latest price (SPY is not part of the user's holdings)
    _benchmark_latest = _lookup_latest_prices(client, [benchmark_ticker])

    returns: dict[str, dict] = {}
    for name, start in periods.items():
        hist = _lookup_prices_before(client, tickers + [benchmark_ticker], start)
        port_ret, covered, covered_value = 0.0, 0, 0.0
        for t in tickers:
            if t not in hist:
                continue
            start_price = hist[t][0]
            if start_price <= 0:
                continue
            w = shares[t] * latest[t]
            port_ret += w * (latest[t] / start_price - 1)
            covered += 1
            covered_value += w
        if covered_value <= 0:
            continue
        port_ret /= covered_value
        spy_ret = None
        if benchmark_ticker in hist:
            spy_start = hist[benchmark_ticker][0]
            spy_latest = _benchmark_latest.get(benchmark_ticker, 0.0)
            if spy_start > 0 and spy_latest > 0:
                spy_ret = spy_latest / spy_start - 1
        returns[name] = {
            "portfolio_pct": port_ret * 100,
            "spy_pct": (spy_ret * 100) if spy_ret is not None else None,
            "excess_pp": ((port_ret - spy_ret) * 100) if spy_ret is not None else None,
            "coverage": f"{covered}/{len(tickers)}",
            "spy_start": hist.get(benchmark_ticker, (None, ""))[1],
        }

    if not returns:
        return {}

    # Portfolio-wide weighted dividend yield (% of current value)
    yield_sum = 0.0
    for h in holdings:
        if h.latest_price <= 0 or h.shares <= 0:
            continue
        w = (h.shares * h.latest_price) / total_value
        yield_pct = h.dividend_yield  # already in percent
        if yield_pct <= 0 and h.dividends:
            annual = _annualize_dividends(h.dividends)
            yield_pct = (annual / h.latest_price) * 100
        yield_sum += w * yield_pct

    return {"returns": returns, "portfolio_yield_pct": yield_sum, "benchmark": benchmark_ticker}


def _lookup_dividend_history(client: Any, tickers: list[str], limit: int = 5) -> dict[str, list[dict]]:
    """
    Query 5: Dividend history from investorhub.DividendHistory (JOIN Symbol),
    limit 5 per ticker, ordered by date desc. The table has no frequency
    column — only date/amount/currency.

    Returns {ticker: [dividend_records]}.
    """
    if not tickers:
        return {}

    escaped = [t.replace("'", "''") for t in tickers]
    in_clause = ", ".join(f"'{t}'" for t in escaped)

    query = (
        f"SELECT * FROM ("
        f"  SELECT s.ticker, dh.amount, dh.date AS ex_date, dh.currency, "
        f"  ROW_NUMBER() OVER (PARTITION BY s.ticker ORDER BY dh.date DESC) AS rn "
        f"  FROM `{DATABASE}`.DividendHistory dh "
        f"  JOIN `{DATABASE}`.Symbol s ON dh.symbolId = s.id "
        f"  WHERE s.ticker IN ({in_clause}) "
        f") ranked WHERE rn <= {limit}"
    )
    rows = _run_sql(client, query)

    div_history: dict[str, list[dict]] = {t: [] for t in tickers}
    for row in rows:
        ticker = str(row.get("ticker", ""))
        div_history.setdefault(ticker, []).append({
            "amount": _f(row.get("amount")),
            "ex_date": str(row.get("ex_date", "")),
            "currency": str(row.get("currency", "USD")),
        })

    logger.info("Retrieved dividend history for %d tickers", sum(len(v) for v in div_history.values()))
    return div_history


def _lookup_fundamentals(client: Any, tickers: list[str]) -> dict[str, dict]:
    """
    Query 6: Fundamentals from investorhub.SymbolFundamentals
    (forwardPeRatio, marketCap, grossMargin, profitMargin, chowderScore,
     fiftyTwoWeekHigh, fiftyTwoWeekLow).

    Returns {ticker: fundamentals_dict}.
    """
    if not tickers:
        return {}

    escaped = [t.replace("'", "''") for t in tickers]
    in_clause = ", ".join(f"'{t}'" for t in escaped)

    query = (
        f"SELECT s.ticker, sf.forwardPeRatio, sf.marketCap, sf.grossMargin, "
        f"sf.profitMargin, sf.chowderScore, sf.fiftyTwoWeekHigh, sf.fiftyTwoWeekLow, "
        f"sf.dividendYield "
        f"FROM `{DATABASE}`.SymbolFundamentals sf "
        f"JOIN `{DATABASE}`.Symbol s ON sf.symbolId = s.id "
        f"WHERE s.ticker IN ({in_clause})"
    )
    rows = _run_sql(client, query)

    fundamentals: dict[str, dict] = {}
    for row in rows:
        ticker = str(row.get("ticker", ""))
        fundamentals[ticker] = {
            "forwardPeRatio": _f(row.get("forwardPeRatio")),
            "marketCap": _f(row.get("marketCap")),
            "grossMargin": _f(row.get("grossMargin")),
            "profitMargin": _f(row.get("profitMargin")),
            "chowderScore": _f(row.get("chowderScore")),
            "fiftyTwoWeekHigh": _f(row.get("fiftyTwoWeekHigh")),
            "fiftyTwoWeekLow": _f(row.get("fiftyTwoWeekLow")),
            "dividendYield": _f(row.get("dividendYield")),
        }

    logger.info("Retrieved fundamentals for %d tickers", len(fundamentals))
    return fundamentals


# ---------------------------------------------------------------------------
# Data enrichment and flagging
# ---------------------------------------------------------------------------


def _build_holdings(
    client: Any,
    portfolio_ids: list[str],
    user_id: str,
    max_holdings: int = 50,
) -> list[Holding]:
    """
    Gather all data for each distinct holding across ALL of the user's
    portfolios (aggregated per ticker):
    - Look up holdings (Position JOIN Symbol, aggregated)
    - Get latest prices, dividend history, fundamentals
    - Fetch news per ticker
    - Apply flagging logic
    """
    holdings_data = _lookup_holdings(client, portfolio_ids, max_holdings)
    if not holdings_data:
        return []

    tickers = list({h.get("ticker", "").upper() for h in holdings_data if h.get("ticker")})

    if not tickers:
        return []

    # Fetch supporting data
    latest_prices = _lookup_latest_prices(client, tickers)
    div_history = _lookup_dividend_history(client, tickers, limit=5)
    fundamentals = _lookup_fundamentals(client, tickers)

    holdings: list[Holding] = []
    for hdata in holdings_data:
        ticker = hdata.get("ticker", "").upper()
        if not ticker:
            continue

        holding = Holding()
        holding.ticker = ticker
        holding.name = hdata.get("name", ticker)
        holding.shares = _f(hdata.get("shares", hdata.get("quantity", 0)))
        holding.avg_cost = _f(hdata.get("avg_cost"))
        holding.latest_price = latest_prices.get(ticker, 0.0)
        holding.dividends = div_history.get(ticker, [])

        # Fundamentals (margin/yield columns are stored as fractions, e.g. 0.486 = 48.6%)
        if ticker in fundamentals:
            fund = fundamentals[ticker]
            holding.forward_pe = fund.get("forwardPeRatio", 0)
            holding.market_cap = fund.get("marketCap", 0)
            holding.gross_margin = fund.get("grossMargin", 0) * 100
            holding.profit_margin = fund.get("profitMargin", 0) * 100
            holding.chowder_score = fund.get("chowderScore", 0)
            holding.week52_high = fund.get("fiftyTwoWeekHigh", 0)
            holding.week52_low = fund.get("fiftyTwoWeekLow", 0)
            holding.dividend_yield = fund.get("dividendYield", 0) * 100

        # Flagging logic
        holding.flags = _compute_flags(holding)

        holdings.append(holding)

    # Fetch news for each ticker (cap keeps runtime within budget; ~0.5s
    # per search, so 25 tickers ≈ 12s)
    news_tickers = tickers[:25]
    for ticker in news_tickers:
        news = _search_news(client, f"{ticker} stock news")
        for h in holdings:
            if h.ticker == ticker:
                h.news = news
                break

    logger.info("Built %d enriched holdings", len(holdings))
    return holdings


def _annualize_dividends(dividends: list[dict]) -> float:
    """
    Estimate the annualized per-share dividend from recent payment records.
    DividendHistory has no frequency column, so infer the payment cadence
    from the median gap between dates: ~30 days -> monthly (x12),
    ~90 days -> quarterly (x4), ~180 days -> semi-annual (x2), else x1.
    Returns 0.0 when there is no data.
    """
    if not dividends:
        return 0.0
    latest = dividends[0].get("amount", 0)
    if len(dividends) < 2:
        return latest
    dates = []
    for d in dividends:
        try:
            dates.append(datetime.strptime(str(d.get("ex_date", ""))[:10], "%Y-%m-%d"))
        except ValueError:
            continue
    if len(dates) < 2:
        return latest
    gaps = sorted(abs((b - a).days) for a, b in zip(dates, dates[1:]))
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return latest
    median_gap = gaps[len(gaps) // 2]
    if median_gap <= 45:
        return latest * 12
    if median_gap <= 120:
        return latest * 4
    if median_gap <= 240:
        return latest * 2
    return latest


def _compute_flags(holding: Holding) -> list[str]:
    """
    Flag notable items:
    - Price change >5% from 52-week high or low
    - Dividend changes (increase/decrease)
    - Negative news indicators
    """
    flags: list[str] = []

    # Price relative to 52-week range
    if holding.week52_high > 0 and holding.latest_price > 0:
        pct_from_high = (holding.latest_price - holding.week52_high) / holding.week52_high * 100
        if pct_from_high < -5:
            flags.append(
                f"⚠️  Price is {abs(pct_from_high):.1f}% below 52-week high (${holding.week52_high:.2f})"
            )

    if holding.week52_low > 0 and holding.latest_price > 0:
        pct_from_low = (holding.latest_price - holding.week52_low) / holding.week52_low * 100
        if pct_from_low > 5:
            flags.append(
                f"📈 Price is {pct_from_low:.1f}% above 52-week low (${holding.week52_low:.2f})"
            )

    # Dividend changes (check for recent increases or cuts)
    if len(holding.dividends) >= 2:
        latest_div = holding.dividends[0].get("amount", 0)
        prev_div = holding.dividends[1].get("amount", 0)
        if prev_div > 0 and latest_div > prev_div:
            flags.append(
                f"📈 Dividend increased: ${prev_div:.4f} → ${latest_div:.4f}"
            )
        elif prev_div > 0 and latest_div < prev_div:
            flags.append(
                f"⚠️  Dividend cut: ${prev_div:.4f} → ${latest_div:.4f}"
            )

    # Negative news indicators
    for article in holding.news:
        snippet_lower = (article.get("snippet", "") + " " + article.get("title", "")).lower()
        negative_keywords = ["layoff", "lawsuit", "fraud", "scandal", "investigation",
                            "bankruptcy", "downgrade", "recall", "breach", "sued"]
        for kw in negative_keywords:
            if kw in snippet_lower:
                flags.append(f"⚠️  Negative news: {article.get('title', 'N/A')}")
                break

    return flags


# ---------------------------------------------------------------------------
# Fallback: general market brief when no portfolios exist
# ---------------------------------------------------------------------------


def _build_fallback_brief(client: Any, focus: str) -> str:
    """
    Fallback path: when no portfolios exist, produce a general market
    brief focused on dividend stocks (or growth/general per config).

    Uses mcp_search via LiteLLM for broad market context.
    """
    if focus == "dividend":
        query = "dividend aristocrats REITs yield market outlook 2026"
        section_title = "Dividend Market Overview"
    elif focus == "growth":
        query = "top growth stocks tech IPOs market outlook 2026"
        section_title = "Growth Market Overview"
    else:
        query = "market overview S&P 500 bonds commodities 2026"
        section_title = "General Market Overview"

    news_items = _search_news(client, query, max_results=10)

    lines = [f"## {section_title}", ""]
    if news_items:
        for i, item in enumerate(news_items[:5], 1):
            lines.append(f"{i}. **{item['title']}**")
            if item.get("snippet"):
                lines.append(f"   {item['snippet'][:200]}")
            if item.get("url"):
                lines.append(f"   - [{item['title']}]({item['url']})")
            lines.append("")
    else:
        lines.append("_No recent news found for the current focus topic._\n")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a financial analyst preparing a concise investment brief.

    You will be given the user's holdings aggregated across ALL of their
    portfolios, with portfolio weight (%), P&L (%), current market prices,
    dividends, fundamentals, news, and flagged items.

    Produce a well-structured Markdown brief with:

    1. **Header**: Brief title, date, and focus.
    2. **Portfolio Summary**: Total distinct holdings, overall P&L (%),
       portfolio YTD / 1Y / 5Y total return vs the S&P 500 (state the
       excess/shortfall in percentage points), portfolio-wide dividend
       yield (%), and top gainers/losers (by P&L %). NEVER state the total
       portfolio value in dollars.
    3. **Key Flags**: Notable price changes, dividend changes, negative news.
    4. **Action Items**: Concise bullet-point recommendations. These come
       BEFORE the holding details so they are seen first. Frame every
       recommendation against the portfolio goal (see Rules).
    5. **Holding Details**: Per-holding summary in MARKDOWN TABLES grouped by
       bucket — one table per bucket, columns: Ticker, Weight, P&L, Price,
       Yield, Notes. Put the holding name in the Ticker cell (e.g. **AAPL**
       (Apple)). Keep Notes concise (fundamentals + any flags). Buckets:
       Core Equity & Index Funds (broad index funds/ETFs + individual
       stocks), Dividend & Income (dividend-focused funds + dividend payers),
       Bond & Cash (bond funds/ETFs + money market). Classify by the
       holding's NATURE, not its yield: total-market/total-world and S&P 500
       index funds (VT, VFIAX, VOO, FXAIX) belong in Core Equity, never in
       Bond & Cash. ABOVE EACH TABLE, add a bold status line with the
       bucket's target % (from the portfolio goal), the actual % (sum of
       the weights in that table), and how many percentage points over or
       under target it is. Do NOT use a long nested bullet list for the
       holdings — the tables keep each symbol visually separated.
    6. **News Summary**: Top relevant news items.
       **Each news item MUST include a clickable link**: `[source](url)` or `[read more](url)`.
    7. **Key Sources**: A section at the end listing all source URLs with clickable links
       so the user can click through to the original articles.

    Rules:
    - Use bullet points for readability.
    - Keep the brief concise — maximum ~2500 words.
    - Be factual, use the data provided, do not fabricate numbers.
    - Highlight items with flags prominently.
    - **Report positions in PERCENTAGES, not dollars or share counts**: e.g.
      "AAPL is 24.3% of the portfolio with a +58.5% gain" — never share counts,
      cost basis, or per-holding dollar P&L. Current market prices, market cap,
      and per-share dividends are public data and may be shown in dollars.
    - **PRIVACY RULE — this brief is published publicly**: NEVER disclose the
      total portfolio value, the dollar value of any holding, cost basis,
      or share counts. Only portfolio weight %, P&L %, and public market data
      (prices, market cap, per-share dividends). If a line of the input data
      shows a dollar total, omit it entirely rather than quoting it.
    - **Portfolio goal (user-stated)**: target allocation is roughly
      60% growth / 30% dividend income / 10% bonds. Bucket guidance: broad
      market index funds/ETFs (e.g. VOO, FXAIX, VT, VFIAX) and individual
      stocks held for growth count toward the GROWTH bucket; dividend-focused
      funds and dividend payers (yield ≳ 2%) count toward the DIVIDEND
      bucket; bond funds/ETFs count toward BONDS; money market funds are cash.
      Report the approximate current bucket allocation and compare it to the
      60/30/10 target. Broad index concentration is FINE when it sits within
      the growth target — do not flag it as a problem. If the dividend bucket
      is below target, the key recommendation is GROWING the dividend payers
      (new contributions and dividend reinvestment toward that bucket).
    - Format numbers with 1-2 decimal places.
    - **ALWAYS include clickable markdown links for news items and in the Key Sources section**:
      format `[headline or source](https://example.com/...)`.
      The user needs to be able to click through to the original articles.
    - Output ONLY the markdown brief — no preamble, no wrapping JSON.
""")


def _fmt_market_cap(value: float) -> str:
    """Format a market cap in dollars as T/B/M for readability."""
    if value >= 1e12:
        return f"${value / 1e12:.2f}T"
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    if value >= 1e6:
        return f"${value / 1e6:.1f}M"
    return f"${value:,.0f}"


def _build_brief_context(
    user_email: str,
    user_name: str,
    focus: str,
    holdings: list[Holding],
    fallback_text: str,
    market_context: Optional[dict] = None,
) -> str:
    """Build the context string for the LLM synthesis."""

    if not holdings and fallback_text:
        return textwrap.dedent(f"""\
            ## User: {user_name} ({user_email})
            ## Focus: {focus}
            ## Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

            No portfolios found for this user. Here is a general market brief:

            {fallback_text}

            Produce the investment brief based on the above fallback market data.
        """)

    # Portfolio-level stats (for % framing)
    total_value = sum(h.shares * h.latest_price for h in holdings if h.latest_price > 0)
    total_cost = sum(h.shares * h.avg_cost for h in holdings if h.avg_cost > 0)
    total_pnl_pct = ((total_value - total_cost) / total_cost * 100) if total_cost > 0 else 0.0

    # Build per-holding data (percentages, not personal $/share counts)
    holding_lines: list[str] = []
    for h in holdings:
        value = h.shares * h.latest_price
        weight_pct = (value / total_value * 100) if total_value > 0 else 0.0
        pnl_pct = ((h.latest_price - h.avg_cost) / h.avg_cost * 100) if h.avg_cost > 0 else 0.0
        pnl_word = "gain" if pnl_pct >= 0 else "loss"
        holding_lines.append(f"- **{h.ticker}** ({h.name})")
        holding_lines.append(f"  - Weight: {weight_pct:.1f}% of portfolio | P&L: {pnl_pct:+.1f}% ({pnl_word})")
        if h.latest_price > 0:
            holding_lines.append(f"  - Current price: ${h.latest_price:.2f}")
        if h.forward_pe > 0:
            holding_lines.append(f"  - Fwd P/E: {h.forward_pe:.1f}")
        if h.market_cap > 0:
            holding_lines.append(f"  - Market Cap: {_fmt_market_cap(h.market_cap)}")
        if h.gross_margin > 0:
            holding_lines.append(f"  - Gross Margin: {h.gross_margin:.1f}%")
        if h.profit_margin > 0:
            holding_lines.append(f"  - Profit Margin: {h.profit_margin:.1f}%")
        if h.chowder_score > 0:
            holding_lines.append(f"  - Chowder Score: {h.chowder_score:.1f}")
        if h.week52_high > 0 or h.week52_low > 0:
            holding_lines.append(f"  - 52W Range: ${h.week52_low:.2f} – ${h.week52_high:.2f}")
        if h.dividends:
            latest_div = h.dividends[0]
            annual = _annualize_dividends(h.dividends)
            div_line = f"  - Latest Div: ${latest_div.get('amount', 0):.4f}, Annualized: ${annual:.4f}"
            if h.dividend_yield > 0:
                div_line += f", Yield: {h.dividend_yield:.2f}%"
            holding_lines.append(div_line)
        if h.flags:
            for flag in h.flags:
                holding_lines.append(f"  - {flag}")
        if h.news:
            holding_lines.append(f"  - News:")
            for n in h.news[:3]:
                title = n.get('title', 'N/A')
                snippet = n.get('snippet', '')[:100]
                url = n.get('url', '')
                if url:
                    holding_lines.append(f"    - [{title}]({url}): {snippet}")
                else:
                    holding_lines.append(f"    - {title}: {snippet}")
        holding_lines.append("")

    # Benchmark / returns / yield block (may be empty if no history)
    market_block = ""
    if market_context and market_context.get("returns"):
        lines = [
            "## Benchmark & Returns (vs S&P 500 via SPY, total return on adjClose,",
            "## current-weight approximation)",
        ]
        for period in ("YTD", "1Y", "5Y"):
            r = market_context["returns"].get(period)
            if not r or r.get("spy_pct") is None:
                continue
            direction = ("outperforming" if r["excess_pp"] >= 0 else "underperforming")
            lines.append(
                f"- {period}: portfolio {r['portfolio_pct']:+.1f}% vs S&P 500 {r['spy_pct']:+.1f}% "
                f"({direction} by {abs(r['excess_pp']):.1f}pp; {r['coverage']} tickers with full history)"
            )
        lines.append(
            f"- Portfolio-wide dividend yield (value-weighted): "
            f"{market_context.get('portfolio_yield_pct', 0):.2f}%"
        )
        lines.append("")
        lines.append("## Portfolio Goal (user-stated)")
        lines.append("- Target allocation: ~60% growth / 30% dividend income / 10% bonds.")
        lines.append("- Broad market index funds (VOO, FXAIX, VT, VFIAX) and growth stocks")
        lines.append("  count toward the GROWTH bucket; dividend payers (yield ~2%+) toward")
        lines.append("  DIVIDEND; bond funds/ETFs toward BONDS; money market funds are cash.")
        lines.append("- Compare the current allocation to this target; broad index")
        lines.append("  concentration within the growth target is fine. If the dividend bucket")
        lines.append("  is below target, the key action is growing the dividend payers.")
        market_block = "\n".join(lines)

    return textwrap.dedent(f"""\
        ## User: {user_name} ({user_email})
        ## Focus: {focus}
        ## Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

        ## Portfolio (all portfolios combined)
        - Distinct holdings: {len(holdings)}
        - Overall P&L: {total_pnl_pct:+.1f}% vs cost basis
        - (Total dollar value is intentionally omitted — the brief is
          published publicly and must not disclose it.)

        {market_block}

        ## Holdings ({len(holdings)} total)

        {''.join(holding_lines)}

        Produce the investment brief based on the above data. Report each
        holding's portfolio weight and P&L as percentages (not dollars or
        share counts).
    """)


def _synthesize_brief(
    client: Any,
    user_email: str,
    user_name: str,
    focus: str,
    holdings: list[Holding],
    fallback_text: str,
    market_context: Optional[dict] = None,
) -> str:
    """Synthesize the investment brief via LLM chat completion through LiteLLM."""
    context = _build_brief_context(
        user_email, user_name, focus, holdings, fallback_text, market_context
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]

    # 2026-10-05: matrix-coder (Qwen3.8-27B) is a reasoning model. With
    # thinking enabled it exhausted the output budget on reasoning_content
    # and returned content=null (finish_reason=length), producing empty
    # briefs (same failure class as homelab_report, 2026-09-21). This skill
    # is a data-extraction/synthesis task, so thinking is disabled via
    # chat_template_kwargs (verified through the LiteLLM proxy: ~5s,
    # finish_reason=stop). max_tokens 8192 leaves headroom for 20-holding
    # briefs with news.
    result = client.chat_completion(
        MODEL_ALIAS,
        messages,
        max_tokens=8192,
        temperature=0.3,
        stream=False,
        chat_template_kwargs={"enable_thinking": False},
    )

    choices = result.get("choices", [])
    if choices and "message" in choices[0]:
        content = choices[0]["message"].get("content")
        if content:
            return content
        finish = choices[0].get("finish_reason", "unknown")
        return (
            f"# Investment Brief — {user_email}\n\n"
            f"**⚠ No brief generated:** LLM returned empty content "
            f"(finish_reason={finish}). The reasoning model likely exhausted "
            f"its token budget on internal reasoning. Re-run the skill or "
            f"raise max_tokens.\n"
        )
    return f"# Investment Brief — {user_email}\n\n**No brief generated.** LLM returned no choices.\n"


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Convert a string to a filename-safe slug."""
    return "".join(c if c.isalnum() or c == "-" else "-" for c in value[:60]).strip("-")


def _prune_artifacts(user_email: str, keep: int = MAX_ARTIFACTS) -> int:
    """
    Delete old investment brief artifacts for this user, keeping only the
    `keep` most recent runs (by mtime). Files that don't match the expected
    naming pattern or belong to other users are left untouched.
    Returns the number of files removed.
    """
    try:
        if not ARTIFACT_DIR.is_dir() or keep < 1:
            return 0
        slug = _slugify(user_email)
        marker = f"_{slug}_"  # exact segment match: investment_brief_{ts}_{slug}_{focus}.md
        candidates = [
            path
            for path in ARTIFACT_DIR.iterdir()
            if path.is_file()
            and path.name.startswith("investment_brief_")
            and path.name.endswith(".md")
            and marker in path.name
        ]
        if len(candidates) <= keep:
            return 0
        candidates.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
        removed = 0
        for path in candidates[keep:]:
            try:
                path.unlink()
                removed += 1
                logger.info("Pruned old artifact: %s", path.name)
            except OSError as exc:
                logger.warning("Could not prune artifact %s: %s", path.name, exc)
        return removed
    except OSError as exc:
        logger.warning("Artifact pruning failed: %s", exc)
        return 0


def _write_artifact(report: str, user_email: str, focus: str) -> Optional[str]:
    """
    Save the investment brief as an artifact file, then prune older runs
    for this user so only the latest MAX_ARTIFACTS briefs remain.
    Returns the file path or None on failure.
    """
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        slug = _slugify(user_email)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"investment_brief_{ts}_{slug}_{focus}.md"
        path = ARTIFACT_DIR / filename
        path.write_text(report, encoding="utf-8")
        logger.info("Artifact written: %s", path)
        _prune_artifacts(user_email)
        return str(path)
    except OSError as exc:
        logger.error("Could not write artifact: %s", exc)
        return None


# ---------------------------------------------------------------------------
# HTML rendering + public publish (same pattern as morning_brief)
# ---------------------------------------------------------------------------

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
.meta a { color: #1d4ed8; }
.card {
  background: #ffffff; border: 1px solid #e2e5ea; border-radius: 14px;
  padding: 20px 20px 16px; margin: 18px 0;
  box-shadow: 0 1px 3px rgba(16,24,40,0.05);
}
.card h2 { font-size: 1.22rem; margin: 0 0 8px; line-height: 1.3; }
.card h3 { font-size: 1.05rem; margin: 14px 0 6px; }
.card p { margin: 8px 0; }
.card ul, .card ol { margin: 8px 0; padding-left: 22px; }
.card li { margin: 5px 0; }
/* Nested lists (holding sub-details) get breathing room between blocks */
.card li > ul, .card li > ol { margin: 6px 0 2px; padding-left: 20px; }
.card li:has(> ul) { margin-bottom: 14px; }
.table-wrap { overflow-x: auto; margin: 10px 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.93rem; table-layout: auto; }
th, td { border: 1px solid #dde1e7; padding: 7px 10px; text-align: left; vertical-align: top; }
th { background: #eef1f5; font-weight: 600; white-space: nowrap; }
tbody tr:nth-child(even) { background: #f7f8fa; }
a { color: #1d4ed8; }
footer { color: #5a6472; font-size: 0.85rem; margin-top: 28px; }
"""


def _escape_html(value: str) -> str:
    """Escape HTML special characters."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _md_inline(text: str) -> str:
    """
    Convert inline markdown (links, bold, italic, code) to HTML.
    Links are escaped then wrapped in <a> tags so source URLs stay clickable.
    """
    # Extract [text](url) links first so their contents aren't mangled.
    links: list[str] = []

    def stash_link(m: "re.Match[str]") -> str:
        label = _escape_html(m.group(1))
        url = m.group(2)
        links.append(f'<a href="{_escape_html(url)}" rel="noopener noreferrer" target="_blank">{label}</a>')
        return f"\x00LINK{len(links) - 1}\x00"

    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", stash_link, text)
    text = _escape_html(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)

    def restore(m: "re.Match[str]") -> str:
        return links[int(m.group(1))]

    return re.sub(r"\x00LINK(\d+)\x00", restore, text)


def _md_to_html(md: str) -> str:
    """
    Convert a markdown subset (headings, paragraphs, lists incl. nested,
    pipe tables, hr, inline formatting) to HTML. Line-based state machine
    (same approach as morning_brief).
    """
    lines = md.splitlines()
    out: list[str] = []
    para: list[str] = []
    # Stack of open lists (indent, type) so indented bullets nest inside
    # their parent item instead of being flattened.
    list_stack: list[tuple[int, str]] = []
    li_stack: list[int] = []  # indents of currently open <li> elements
    i = 0

    def flush_para():
        nonlocal para
        if para:
            out.append(f"<p>{_md_inline(' '.join(para))}</p>")
            para = []

    def close_all_lists():
        while li_stack:
            d = li_stack.pop()
            out.append("</li>")
            if list_stack and list_stack[-1][0] == d:
                out.append(f"</{list_stack.pop()[1]}>")
        while list_stack:
            out.append(f"</{list_stack.pop()[1]}>")

    def is_table_row(line: str) -> bool:
        return line.strip().startswith("|") and line.strip().endswith("|") and line.count("|") >= 2

    def is_table_separator(line: str) -> bool:
        s = line.strip()
        if not (s.startswith("|") and s.endswith("|")):
            return False
        cells = [c.strip() for c in s.strip("|").split("|")]
        return bool(cells) and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)

    while i < len(lines):
        raw = lines[i].rstrip()
        stripped = raw.strip()

        # Blank line
        if not stripped:
            flush_para()
            close_all_lists()
            i += 1
            continue

        # Heading
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            close_all_lists()
            level = len(m.group(1))
            out.append(f"<h{level}>{_md_inline(m.group(2))}</h{level}>")
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            flush_para()
            close_all_lists()
            out.append("<hr>")
            i += 1
            continue

        # Markdown table: header row, separator row, then body rows
        if is_table_row(stripped) and i + 1 < len(lines) and is_table_separator(lines[i + 1].strip()):
            flush_para()
            close_all_lists()

            def parse_row(row: str) -> list[str]:
                return [c.strip() for c in row.strip().strip("|").split("|")]

            header = parse_row(stripped)
            i += 2
            body_rows: list[list[str]] = []
            while i < len(lines) and is_table_row(lines[i].strip()):
                body_rows.append(parse_row(lines[i].strip()))
                i += 1

            out.append('<div class="table-wrap"><table>')
            out.append("<thead><tr>" + "".join(f"<th>{_md_inline(c)}</th>" for c in header) + "</tr></thead>")
            out.append("<tbody>")
            for row in body_rows:
                # Pad/truncate to header width
                cells = (row + [""] * len(header))[: len(header)]
                out.append("<tr>" + "".join(f"<td>{_md_inline(c)}</td>" for c in cells) + "</tr>")
            out.append("</tbody></table></div>")
            continue

        # List items (unordered or ordered), nesting by indent depth
        m = re.match(r"^(\s*)([-*+]\s+|\d+[.)]\s+)(.*)$", raw)
        if m:
            flush_para()
            indent = len(m.group(1).expandtabs(4))
            list_type = "ol" if m.group(2)[0].isdigit() else "ul"
            content = m.group(3).strip()
            # Close open <li> elements at this indent or deeper. When the
            # last <li> of a deeper list closes, close that list too so the
            # nesting stays balanced (</li> ... </ul> ... </li> order).
            while li_stack and li_stack[-1] >= indent:
                d = li_stack.pop()
                out.append("</li>")
                if d > indent and list_stack and list_stack[-1][0] == d:
                    out.append(f"</{list_stack.pop()[1]}>")
            # Same indent, different list type: swap the list.
            if list_stack and list_stack[-1][0] == indent and list_stack[-1][1] != list_type:
                out.append(f"</{list_stack.pop()[1]}>")
            if not list_stack or list_stack[-1][0] != indent:
                out.append(f"<{list_type}>")
                list_stack.append((indent, list_type))
            out.append(f"<li>{_md_inline(content)}")
            li_stack.append(indent)
            i += 1
            continue

        # Paragraph text
        flush_para()
        close_all_lists()
        para.append(stripped)
        i += 1

    flush_para()
    close_all_lists()
    return "\n".join(out)


def _render_brief_html(report_md: str, title: str, meta_html: str) -> str:
    """Render the markdown brief into a self-contained, mobile-friendly HTML page."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = f'<div class="card">{_md_to_html(report_md)}</div>'
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
        f'<header class="brief">\n<h1>{_escape_html(title)}</h1>\n{meta_html}\n</header>\n'
        f"{body}\n"
        f'<footer>Generated {now} by the investment brief skill. Portfolio data is '
        f'aggregated across all linked InvestorHub portfolios; source articles are '
        f'linked inline and in the Key Sources section.</footer>\n'
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )


def _publish_brief(html: str, job) -> Optional[str]:
    """
    Atomically publish the HTML brief to the public drop zone.

    Single-file retention: the target is overwritten on every run, so the
    public folder always holds exactly one brief (the latest).
    """
    try:
        PUBLISH_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PUBLISH_PATH.with_name(PUBLISH_PATH.name + ".tmp")
        tmp.write_text(html, encoding="utf-8")
        os.replace(tmp, PUBLISH_PATH)  # atomic on POSIX
        logger.info("Brief published: %s", PUBLISH_PATH)
        if hasattr(job, "add_log"):
            job.add_log(f"Published to {PUBLISH_PATH}")
        return str(PUBLISH_PATH)
    except OSError as exc:
        logger.error("Could not publish brief to %s: %s", PUBLISH_PATH, exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Publish FAILED ({PUBLISH_PATH}): {exc}")
        return None


def _public_url() -> str:
    """Map the publish path to its public https URL."""
    try:
        rel = PUBLISH_PATH.resolve().relative_to(PUBLIC_ROOT.resolve())
        return f"{PUBLIC_BASE}/{rel.as_posix()}"
    except (ValueError, OSError):
        return f"{PUBLIC_BASE}/briefs/{PUBLISH_PATH.name}"


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(
    params: dict[str, Any],
    job,
    litellm_client=None,
) -> dict[str, Any]:
    """
    Execute the investment_brief skill.

    All LLM and MCP interactions go through LiteLLM. This skill never
    contacts MCP servers directly.

    Args:
        params: Skill parameters (user_email, focus, max_holdings).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.

    Returns:
        Dict with 'summary', 'report', 'artifact_path', 'published_url',
        'user_email', 'focus', 'holdings_count', 'portfolio_count'.
    """
    # Resolve LiteLLM client (sync interface guaranteed)
    client = _resolve_litellm_client(litellm_client)

    # Validate inputs
    user_email = params.get("user_email", "choukalos@yahoo.com")
    focus = params.get("focus", "dividend")
    max_holdings = params.get("max_holdings", 50)
    publish = params.get("publish", True)

    if not user_email or not str(user_email).strip():
        return {"error": "Missing required 'user_email' parameter"}

    user_email = str(user_email).strip()
    focus = str(focus).strip().lower()
    if focus not in ("dividend", "growth", "general"):
        focus = "dividend"

    if not isinstance(max_holdings, int) or max_holdings < 1:
        max_holdings = 50
    max_holdings = min(max_holdings, 50)  # hard cap
    if isinstance(publish, str):
        publish = publish.strip().lower() not in ("0", "false", "no", "off")

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing investment_brief: user='{user_email}', focus='{focus}', max_holdings={max_holdings}, publish={publish}")
        job.add_log(f"Model alias: {MODEL_ALIAS}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")
        job.add_log(f"LiteLLM: {client.base_url}")
        job.add_log(f"Database: {DATABASE}")

    # Install timeout
    _install_timeout()

    try:
        # Phase 1: Look up user
        if hasattr(job, "add_log"):
            job.add_log("Phase 1: Looking up user via mcp_mysql-run_query...")

        user = _lookup_user(client, user_email)
        user_name = user.get("name", user_email.split("@")[0]) if user else user_email

        # Phase 2: Look up portfolios
        if hasattr(job, "add_log"):
            job.add_log("Phase 2: Looking up portfolios via mcp_mysql-run_query...")

        portfolios = []
        portfolio_ids: list[str] = []
        if user:
            user_id = str(user.get("id", ""))
            portfolios = _lookup_portfolios(client, user_id)
            portfolio_ids = [str(p.get("id", "")) for p in portfolios if p.get("id") is not None]

        # Phase 3: Build holdings (aggregated across ALL portfolios) or fallback
        holdings: list[Holding] = []
        fallback_text = ""

        if not portfolio_ids:
            if hasattr(job, "add_log"):
                job.add_log("No portfolios found — using fallback market brief")
            fallback_text = _build_fallback_brief(client, focus)
        else:
            if hasattr(job, "add_log"):
                job.add_log(f"Phase 3: Building holdings across {len(portfolio_ids)} portfolio(s)...")

            holdings = _build_holdings(client, portfolio_ids, user_id if user else "", max_holdings)

        # Phase 3b: Benchmark returns (YTD/1Y/5Y vs SPY) + portfolio yield
        market_context: Optional[dict] = None
        if holdings:
            try:
                if hasattr(job, "add_log"):
                    job.add_log("Phase 3b: Computing period returns vs S&P 500 (SPY)...")
                market_context = _compute_market_context(client, holdings)
            except Exception as exc:
                logger.warning("Market context computation failed: %s", exc)
                if hasattr(job, "add_log"):
                    job.add_log(f"Warning: market context unavailable ({exc})")

        # Phase 4: Synthesize brief via LLM
        if hasattr(job, "add_log"):
            job.add_log("Phase 4: Synthesizing investment brief via LLM...")

        report = _synthesize_brief(
            client, user_email, user_name, focus, holdings, fallback_text, market_context
        )

        if hasattr(job, "add_log"):
            job.add_log(f"Brief generated ({len(report)} chars)")

        # Phase 5: Save artifact
        artifact_path = _write_artifact(report, user_email, focus)

        if hasattr(job, "add_log"):
            if artifact_path:
                job.add_log(f"Artifact saved: {artifact_path}")
            else:
                job.add_log("Warning: artifact save failed, report returned inline only")

        # Phase 6: Render HTML + publish to the public drop zone
        published_path: Optional[str] = None
        published_url: Optional[str] = None
        if publish:
            title = f"Investment Brief — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
            meta_html = (
                f'<p class="meta">Focus: {_escape_html(focus)} · '
                f'{len(holdings)} holdings across {len(portfolio_ids)} portfolio(s) · '
                f'Portfolio data: <a href="{_escape_html(INVESTOR_HUB_URL)}" '
                f'rel="noopener noreferrer" target="_blank">InvestorHub</a></p>'
            )
            html = _render_brief_html(report, title, meta_html)
            published_path = _publish_brief(html, job)
            if published_path:
                published_url = _public_url()

        # Extract summary (first few lines)
        summary_lines = report.strip().split("\n")[:5]
        summary = " ".join(summary_lines).strip()

        # Collect flagged items
        all_flags: list[str] = []
        for h in holdings:
            all_flags.extend(h.flags)

        if hasattr(job, "add_log"):
            job.add_log(f"investment_brief completed: {len(holdings)} holdings, {len(all_flags)} flags, {len(report)} chars")

        return {
            "summary": summary,
            "report": report,
            "artifact_path": artifact_path,
            "published_path": published_path,
            "published_url": published_url,
            "user_email": user_email,
            "focus": focus,
            "holdings_count": len(holdings),
            "portfolio_count": len(portfolio_ids),
            "flags_count": len(all_flags),
            "model_alias": MODEL_ALIAS,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")

        partial = (
            f"# Investment Brief — {user_email}\n\n"
            f"**⚠ Brief timed out after {MAX_RUNTIME_SECS}s.** "
            f"The process was interrupted. Results may be incomplete.\n\n"
            f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        )
        artifact_path = _write_artifact(partial, user_email, focus)

        return {
            "summary": f"Brief timed out after {MAX_RUNTIME_SECS}s. Results may be incomplete.",
            "report": partial,
            "artifact_path": artifact_path,
            "user_email": user_email,
            "focus": focus,
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")

        partial = (
            f"# Investment Brief — {user_email}\n\n"
            f"**⚠ Error during brief generation:** {msg}\n\n"
            f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        )
        artifact_path = _write_artifact(partial, user_email, focus)

        return {
            "summary": f"Brief failed: {msg}",
            "report": partial,
            "artifact_path": artifact_path,
            "user_email": user_email,
            "focus": focus,
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)

        partial = (
            f"# Investment Brief — {user_email}\n\n"
            f"**Error:** {msg}\n\n"
            f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
        )
        artifact_path = _write_artifact(partial, user_email, focus)

        return {
            "summary": f"Brief failed: {msg}",
            "report": partial,
            "artifact_path": artifact_path,
            "user_email": user_email,
            "focus": focus,
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# FUTURE TODO: Advanced analysis features (to be implemented in future PRs)
# ---------------------------------------------------------------------------
#
# TODO: P&L Analysis
#   - Calculate unrealized P&L per holding (current_value - cost_basis)
#   - Calculate realized P&L from transaction history
#   - Generate total portfolio P&L with percentage returns
#   - Compare against benchmark index (S&P 500, etc.)
#
# TODO: Sector Allocation Analysis
#   - Map each holding to its GICS sector
#   - Calculate sector weightings (% of total portfolio)
#   - Compare against benchmark sector allocation
#   - Flag over/under-weighted sectors
#   - Generate sector diversification score
#
# TODO: Rebalancing Suggestions
#   - Compare current allocation vs. target allocation
#   - Identify holdings that need rebalancing
#   - Calculate dollar amounts needed to rebalance
#   - Prioritize rebalancing by tax impact (tax-loss harvesting)
#   - Generate specific buy/sell recommendations
#
# TODO: Tax-Loss Harvesting
#   - Identify positions with unrealized losses > $300 (Wash Sale minimum)
#   - Check wash sale rules for recent transactions
#   - Suggest tax-loss harvesting candidates
#
# TODO: Dividend Yield Optimization
#   - Calculate portfolio-weighted dividend yield
#   - Identify dividend aristocrats in portfolio
#   - Suggest dividend reinvestment (DRIP) opportunities
#   - Flag dividend sustainability risks (payout ratio > 80%)
# ---------------------------------------------------------------------------


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
        python skill.py --email choukalos@yahoo.com
        python skill.py --email choukalos@yahoo.com --focus dividend --max-holdings 10
        python skill.py --email choukalos@yahoo.com --dry-run
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="investment_brief standalone test"
    )
    parser.add_argument("--email", default="choukalos@yahoo.com", help="User email")
    parser.add_argument(
        "--focus",
        default="dividend",
        choices=["dividend", "growth", "general"],
        help="Brief focus",
    )
    parser.add_argument(
        "--max-holdings",
        type=int,
        default=20,
        help="Max holdings to analyze",
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
        print("=== DRY RUN ===")
        print(f"  Email: {args.email}")
        print(f"  Focus: {args.focus}")
        print(f"  Max holdings: {args.max_holdings}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Artifact dir: {ARTIFACT_DIR}")
        print(f"  LiteLLM: {LITELLM_BASE_URL}")
        print(f"  Database: {DATABASE}")
        print()
        print("  All MCP calls go through LiteLLM — no direct MCP server access")
        print("  SQL queries via mcp_mysql-run_query on database `investorhub`:")
        print("    1. User lookup by email")
        print("    2. Portfolio lookup by user_id")
        print("    3. Holdings (Position JOIN Symbol)")
        print("    4. Latest prices (PriceHistory)")
        print("    5. Dividend history (DividendHistory)")
        print("    6. Fundamentals (SymbolFundamentals)")
        print("  News via mcp_search-search_news per ticker")
        print()
        print("  FUTURE TODO: P&L analysis, sector allocation, rebalancing suggestions")
        return

    # Apply overrides for CLI testing
    base_url = args.base_url or LITELLM_BASE_URL
    api_key = args.api_key or LITELLM_API_KEY

    params = {
        "user_email": args.email,
        "focus": args.focus,
        "max_holdings": args.max_holdings,
    }

    # Pass a sync LiteLLM client for standalone use
    client = _SyncLiteLLMClient(base_url=base_url, api_key=api_key)
    result = run(params, _MockJob(), litellm_client=client)

    print(f"\n--- investment_brief response ---")
    print(f"Summary: {result.get('summary', 'N/A')[:200]}")
    print(f"Holdings: {result.get('holdings_count', 0)}")
    print(f"Flags: {result.get('flags_count', 0)}")
    if result.get("artifact_path"):
        print(f"Artifact: {result['artifact_path']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"Model: {result.get('model_alias', 'N/A')}")
    print(f"Report length: {len(result.get('report', ''))} chars")


if __name__ == "__main__":
    main()
