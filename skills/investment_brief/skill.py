#!/usr/bin/env python3
"""
investment_brief skill — portfolio status, dividend highlights, and market news.

Purpose:
  Query the InvestorHub database via LiteLLM's MCP gateway (mcp_mysql-run_query),
  fetch latest prices, dividend history, fundamentals, and news per holding,
  flag notable changes, synthesize a concise markdown brief via LLM, and save
  the report as an artifact — all routed through LiteLLM. Never touch MCP
  servers directly.

Workflow:
  1. Validate inputs (user_email, focus, max_holdings).
  2. Look up user by email via mcp_mysql-run_query on database `investorhub`.
  3. Look up portfolio(s) for the found user.
  4. Query holdings (Position JOIN Symbol) per portfolio.
  5. Query latest prices from PriceHistory (order by date desc limit 1).
  6. Query dividend history from DividendHistory (limit 5).
  7. Query fundamentals from SymbolFundamentals.
  8. Call mcp_search-search_news via LiteLLM per ticker for market news.
  9. Flag notable items: price change >5% from 52-week high/low, dividend changes, negative news.
  10. Synthesize a concise markdown bullet-point brief via LLM chat completion.
  11. Save the brief as an artifact file.
  12. Fallback: general market brief for dividend stocks if no portfolios exist.

Constraints:
  - Max runtime: 300 seconds (5 minutes).
  - Read-only: no writes, no admin operations.
  - All MCP calls go through LiteLLM — never direct MCP server access.
  - SQL queries executed via mcp_mysql-run_query on database `investorhub`.
  - Artifacts saved to /home/chuck/data/media/investment_briefs/

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
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
    os.environ.get("INVESTMENT_BRIEF_ARTIFACT_DIR", "/home/chuck/data/media/investment_briefs")
)
MAX_RUNTIME_SECS = int(os.environ.get("INVESTMENT_BRIEF_MAX_RUNTIME", "300"))

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("INVESTMENT_BRIEF_MODEL_ALIAS", "local/qwen-coder")

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
    """Install a signal-based timeout (Unix only)."""
    if sys.platform != "win32":
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUNTIME_SECS)


def _cancel_timeout():
    """Cancel the pending alarm."""
    if sys.platform != "win32":
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
        self.dividends: list[dict] = []
        self.news: list[dict] = []
        self.flags: list[str] = []


# ---------------------------------------------------------------------------
# MCP wrappers — all calls go through LiteLLM
# ---------------------------------------------------------------------------


def _run_sql(client: Any, query: str, database: str = DATABASE) -> list[dict]:
    """
    Execute a SQL query via mcp_mysql-run_query through LiteLLM.

    All database access is read-only and routed through LiteLLM.
    """
    result = client.mcp_call(
        "run_query",
        {"query": query, "database": database},
        server_id="mcp_mysql",
    )
    if not result:
        logger.warning("SQL returned no results: %s", query[:120])
        return []

    # Handle various response formats from LiteLLM MCP gateway
    rows = result.get("result", result.get("rows", result.get("data", [])))
    if isinstance(result.get("result"), dict):
        rows = result["result"].get("rows", result["result"].get("data", []))

    return rows if isinstance(rows, list) else []


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
    results_list = result.get("result", result.get("results", []))
    if isinstance(result.get("result"), dict):
        results_list = result["result"].get("results", result["result"].get("data", []))

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
    """
    query = (
        f"SELECT * FROM `{DATABASE}`.Portfolio "
        f"WHERE user_id = '{user_id}'"
    )
    rows = _run_sql(client, query)
    logger.info("Found %d portfolio(s) for user %s", len(rows), user_id)
    return rows


def _lookup_holdings(client: Any, portfolio_id: str, max_holdings: int = 20) -> list[dict]:
    """
    Query 3: Holdings query — Position JOIN Symbol per portfolio on investorhub.
    """
    query = (
        f"SELECT p.ticker, p.shares, p.avg_cost, p.quantity, p.purchase_date, "
        f"s.name, s.exchange "
        f"FROM `{DATABASE}`.Position p "
        f"JOIN `{DATABASE}`.Symbol s ON p.ticker = s.ticker "
        f"WHERE p.portfolio_id = '{portfolio_id}' "
        f"ORDER BY p.shares DESC "
        f"LIMIT {max_holdings}"
    )
    rows = _run_sql(client, query)
    logger.info("Found %d holdings for portfolio %s", len(rows), portfolio_id)
    return rows


def _lookup_latest_prices(client: Any, tickers: list[str]) -> dict[str, float]:
    """
    Query 4: Latest prices from investorhub.PriceHistory
    (order by date desc limit 1 per ticker).

    Returns {ticker: price}.
    """
    if not tickers:
        return {}

    # Build OR clause for tickers
    escaped = [t.replace("'", "''") for t in tickers]
    or_clause = " OR ".join(f"ticker = '{t}'" for t in escaped)

    query = (
        f"SELECT * FROM ("
        f"  SELECT ticker, price, date, "
        f"  ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn "
        f"  FROM `{DATABASE}`.PriceHistory "
        f"  WHERE {or_clause}"
        f") ranked WHERE rn = 1"
    )
    rows = _run_sql(client, query)

    prices: dict[str, float] = {}
    for row in rows:
        ticker = str(row.get("ticker", ""))
        try:
            prices[ticker] = float(row.get("price", 0))
        except (ValueError, TypeError):
            prices[ticker] = 0.0

    logger.info("Retrieved latest prices for %d tickers", len(prices))
    return prices


def _lookup_dividend_history(client: Any, tickers: list[str], limit: int = 5) -> dict[str, list[dict]]:
    """
    Query 5: Dividend history from investorhub.DividendHistory
    (limit 5 per ticker, ordered by date desc).

    Returns {ticker: [dividend_records]}.
    """
    if not tickers:
        return {}

    escaped = [t.replace("'", "''") for t in tickers]
    or_clause = " OR ".join(f"ticker = '{t}'" for t in escaped)

    query = (
        f"SELECT * FROM ("
        f"  SELECT ticker, amount, ex_date, pay_date, frequency, "
        f"  ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY ex_date DESC) as rn "
        f"  FROM `{DATABASE}`.DividendHistory "
        f"  WHERE {or_clause}"
        f") ranked WHERE rn <= {limit}"
    )
    rows = _run_sql(client, query)

    div_history: dict[str, list[dict]] = {t: [] for t in tickers}
    for row in rows:
        ticker = str(row.get("ticker", ""))
        div_history.setdefault(ticker, []).append({
            "amount": float(row.get("amount", 0)),
            "ex_date": str(row.get("ex_date", "")),
            "pay_date": str(row.get("pay_date", "")),
            "frequency": str(row.get("frequency", "")),
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
    or_clause = " OR ".join(f"ticker = '{t}'" for t in escaped)

    query = (
        f"SELECT ticker, forwardPeRatio, marketCap, grossMargin, "
        f"profitMargin, chowderScore, fiftyTwoWeekHigh, fiftyTwoWeekLow "
        f"FROM `{DATABASE}`.SymbolFundamentals "
        f"WHERE {or_clause}"
    )
    rows = _run_sql(client, query)

    fundamentals: dict[str, dict] = {}
    for row in rows:
        ticker = str(row.get("ticker", ""))
        fundamentals[ticker] = {
            "forwardPeRatio": float(row.get("forwardPeRatio", 0)),
            "marketCap": float(row.get("marketCap", 0)),
            "grossMargin": float(row.get("grossMargin", 0)),
            "profitMargin": float(row.get("profitMargin", 0)),
            "chowderScore": float(row.get("chowderScore", 0)),
            "fiftyTwoWeekHigh": float(row.get("fiftyTwoWeekHigh", 0)),
            "fiftyTwoWeekLow": float(row.get("fiftyTwoWeekLow", 0)),
        }

    logger.info("Retrieved fundamentals for %d tickers", len(fundamentals))
    return fundamentals


# ---------------------------------------------------------------------------
# Data enrichment and flagging
# ---------------------------------------------------------------------------


def _build_holdings(
    client: Any,
    portfolio_id: str,
    user_id: str,
    max_holdings: int = 20,
) -> list[Holding]:
    """
    Gather all data for each holding in a portfolio:
    - Look up holdings (Position JOIN Symbol)
    - Get latest prices, dividend history, fundamentals
    - Fetch news per ticker
    - Apply flagging logic
    """
    holdings_data = _lookup_holdings(client, portfolio_id, max_holdings)
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
        holding.shares = float(hdata.get("shares", hdata.get("quantity", 0)))
        holding.avg_cost = float(hdata.get("avg_cost", 0))
        holding.latest_price = latest_prices.get(ticker, 0.0)
        holding.dividends = div_history.get(ticker, [])

        # Fundamentals
        if ticker in fundamentals:
            fund = fundamentals[ticker]
            holding.forward_pe = fund.get("forwardPeRatio", 0)
            holding.market_cap = fund.get("marketCap", 0)
            holding.gross_margin = fund.get("grossMargin", 0)
            holding.profit_margin = fund.get("profitMargin", 0)
            holding.chowder_score = fund.get("chowderScore", 0)
            holding.week52_high = fund.get("fiftyTwoWeekHigh", 0)
            holding.week52_low = fund.get("fiftyTwoWeekLow", 0)

        # Flagging logic
        holding.flags = _compute_flags(holding)

        holdings.append(holding)

    # Fetch news for each ticker (capped to avoid too many API calls)
    news_tickers = tickers[:10]  # cap news lookups to 10 tickers
    for ticker in news_tickers:
        news = _search_news(client, f"{ticker} stock news")
        for h in holdings:
            if h.ticker == ticker:
                h.news = news
                break

    logger.info("Built %d enriched holdings", len(holdings))
    return holdings


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
                lines.append(f"   - {item['url']}")
            lines.append("")
    else:
        lines.append("_No recent news found for the current focus topic._\n")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a financial analyst preparing a concise investment brief.

    You will be given portfolio holdings with prices, dividends, fundamentals,
    news, and flagged items.

    Produce a well-structured Markdown brief with:

    1. **Header**: Brief title, date, user, and focus.
    2. **Portfolio Summary**: Total holdings, total value, top gainers/losers.
    3. **Key Flags**: Notable price changes, dividend changes, negative news.
    4. **Holding Details**: Per-holding summary with ticker, price, change, key fundamentals, dividend info.
    5. **News Summary**: Top relevant news items.
    6. **Action Items**: Concise bullet-point recommendations.

    Rules:
    - Use bullet points for readability.
    - Keep the brief concise — maximum ~2000 words.
    - Be factual, use the data provided, do not fabricate numbers.
    - Highlight items with flags prominently.
    - Format numbers with 2 decimal places for currency.
    - Output ONLY the markdown brief — no preamble, no wrapping JSON.
""")


def _build_brief_context(
    user_email: str,
    user_name: str,
    focus: str,
    holdings: list[Holding],
    fallback_text: str,
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

    # Build per-holding data
    holding_lines: list[str] = []
    for h in holdings:
        value = h.shares * h.latest_price
        pnl = (h.latest_price - h.avg_cost) * h.shares if h.avg_cost > 0 else 0
        holding_lines.append(f"- **{h.ticker}** ({h.name})")
        holding_lines.append(f"  - Shares: {h.shares}, Cost: ${h.avg_cost:.2f}, Current: ${h.latest_price:.2f}, Value: ${value:.2f}")
        if h.avg_cost > 0:
            holding_lines.append(f"  - P&L: ${pnl:+.2f}")
        if h.forward_pe > 0:
            holding_lines.append(f"  - Fwd P/E: {h.forward_pe:.1f}")
        if h.market_cap > 0:
            holding_lines.append(f"  - Market Cap: ${h.market_cap:,.0f}")
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
            annual = latest_div.get("amount", 0) * (4 if latest_div.get("frequency", "").lower().startswith("quart") else
                                                     12 if latest_div.get("frequency", "").lower().startswith("mont") else 1)
            holding_lines.append(f"  - Latest Div: ${latest_div.get('amount', 0):.4f}, Annualized: ${annual:.4f}")
        if h.flags:
            for flag in h.flags:
                holding_lines.append(f"  - {flag}")
        if h.news:
            holding_lines.append(f"  - News:")
            for n in h.news[:3]:
                holding_lines.append(f"    - {n.get('title', 'N/A')}: {n.get('snippet', '')[:100]}")
        holding_lines.append("")

    return textwrap.dedent(f"""\
        ## User: {user_name} ({user_email})
        ## Focus: {focus}
        ## Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

        ## Holdings ({len(holdings)} total)

        {''.join(holding_lines)}

        Produce the investment brief based on the above data.
    """)


def _synthesize_brief(
    client: Any,
    user_email: str,
    user_name: str,
    focus: str,
    holdings: list[Holding],
    fallback_text: str,
) -> str:
    """Synthesize the investment brief via LLM chat completion through LiteLLM."""
    context = _build_brief_context(user_email, user_name, focus, holdings, fallback_text)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context},
    ]

    result = client.chat_completion(
        MODEL_ALIAS,
        messages,
        max_tokens=6000,
        temperature=0.3,
        stream=False,
    )

    choices = result.get("choices", [])
    if not choices:
        return f"# Investment Brief — {user_email}\n\n**No brief generated.** LLM returned no content.\n"
    return choices[0].get("message", {}).get("content", "# Investment Brief\n\n**No content returned.**\n")


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Convert a string to a filename-safe slug."""
    return "".join(c if c.isalnum() or c == "-" else "-" for c in value[:60]).strip("-")


def _write_artifact(report: str, user_email: str, focus: str) -> Optional[str]:
    """
    Save the investment brief as an artifact file.
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
    Execute the investment_brief skill.

    All LLM and MCP interactions go through LiteLLM. This skill never
    contacts MCP servers directly.

    Args:
        params: Skill parameters (user_email, focus, max_holdings).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.

    Returns:
        Dict with 'summary', 'report', 'artifact_path', 'user_email', 'focus'.
    """
    # Resolve LiteLLM client (sync interface guaranteed)
    client = _resolve_litellm_client(litellm_client)

    # Validate inputs
    user_email = params.get("user_email", "choukalos@yahoo.com")
    focus = params.get("focus", "dividend")
    max_holdings = params.get("max_holdings", 20)

    if not user_email or not str(user_email).strip():
        return {"error": "Missing required 'user_email' parameter"}

    user_email = str(user_email).strip()
    focus = str(focus).strip().lower()
    if focus not in ("dividend", "growth", "general"):
        focus = "dividend"

    if not isinstance(max_holdings, int) or max_holdings < 1:
        max_holdings = 20
    max_holdings = min(max_holdings, 50)  # hard cap

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing investment_brief: user='{user_email}', focus='{focus}', max_holdings={max_holdings}")
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
        if user:
            user_id = str(user.get("id", ""))
            portfolios = _lookup_portfolios(client, user_id)

        # Phase 3: Build holdings or fallback
        holdings: list[Holding] = []
        fallback_text = ""

        if not portfolios:
            if hasattr(job, "add_log"):
                job.add_log("No portfolios found — using fallback market brief")
            fallback_text = _build_fallback_brief(client, focus)
        else:
            # Use the first portfolio (or could merge across portfolios)
            primary_portfolio = portfolios[0]
            portfolio_id = str(primary_portfolio.get("id", ""))
            portfolio_name = primary_portfolio.get("name", "Primary")

            if hasattr(job, "add_log"):
                job.add_log(f"Phase 3: Building holdings for portfolio '{portfolio_name}' ({portfolio_id})...")

            holdings = _build_holdings(client, portfolio_id, user_id if user else "", max_holdings)

        # Phase 4: Synthesize brief via LLM
        if hasattr(job, "add_log"):
            job.add_log("Phase 4: Synthesizing investment brief via LLM...")

        report = _synthesize_brief(client, user_email, user_name, focus, holdings, fallback_text)

        if hasattr(job, "add_log"):
            job.add_log(f"Brief generated ({len(report)} chars)")

        # Phase 5: Save artifact
        artifact_path = _write_artifact(report, user_email, focus)

        if hasattr(job, "add_log"):
            if artifact_path:
                job.add_log(f"Artifact saved: {artifact_path}")
            else:
                job.add_log("Warning: artifact save failed, report returned inline only")

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
            "user_email": user_email,
            "focus": focus,
            "holdings_count": len(holdings),
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
