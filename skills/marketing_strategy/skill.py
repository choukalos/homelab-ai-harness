#!/usr/bin/env python3
"""
marketing_strategy skill — Go-To-Market (GTM) strategy generation.

Purpose:
  Given a product or service brief, research the market (competitors, trends,
  sizing) via LiteLLM's MCP gateway (mcp_search), then synthesize a
  comprehensive GTM strategy via LLM and save it as a Markdown artifact.

  Design adapted from langchain-ai/deepagents `deploy-gtm-agent`:
    - market-researcher subagent  -> research phase (search_web / search_news)
    - GTM coordinator             -> synthesis phase (LLM strategy)

Workflow:
  1. Validate inputs; derive product name + category from the brief.
  2. Market research via mcp_search (search_web):
       - competitors in the segment
       - market size / trends
       - audience / use-case signals
  3. Synthesize a GTM strategy via LiteLLM chat completion.
  4. Save the strategy as a Markdown artifact.
  5. Return summary, full report, and artifact path.

Constraints:
  - Max runtime: 300 seconds.
  - Read-only: no writes outside the artifact dir, no admin operations.
  - All MCP calls go through LiteLLM — never direct MCP server access.
  - Output format: Markdown.
  - Artifacts saved to /home/chuck/data/media/gtm_strategies/

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
    os.environ.get("MARKETING_STRATEGY_ARTIFACT_DIR", "/home/chuck/data/media/gtm_strategies")
)
MAX_RUNTIME_SECS = int(os.environ.get("MARKETING_STRATEGY_MAX_RUNTIME", "300"))

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("MARKETING_STRATEGY_MODEL_ALIAS", "matrix-coder")

# Default research queries (refined at runtime with the product name)
DEFAULT_RESEARCH_QUERIES = [
    "top competitors for {product} market",
    "{category} market size TAM SAM SOM growth trends",
    "{category} industry trends {year} buyer personas",
]

logger = logging.getLogger("skill.marketing_strategy")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"marketing_strategy exceeded {MAX_RUNTIME_SECS}s max runtime")


def _install_timeout():
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(MAX_RUNTIME_SECS)


def _cancel_timeout():
    if sys.platform != "win32" and threading.main_thread() is threading.current_thread():
        signal.alarm(0)


# ---------------------------------------------------------------------------
# LiteLLM client abstraction
# ---------------------------------------------------------------------------


class _SyncLiteLLMClient:
    """Synchronous LiteLLM client for standalone/CLI use."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.base_url = (base_url or LITELLM_BASE_URL).rstrip("/")
        self.api_key = api_key or LITELLM_API_KEY

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat_completion(self, model: str, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        import urllib.request
        import urllib.error

        payload: dict[str, Any] = {"model": model, "messages": messages}
        payload.update(kwargs)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=data, headers=self._headers(), method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise RuntimeError(f"LiteLLM HTTP error {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach LiteLLM at {self.base_url}: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON from LiteLLM: {exc}") from exc

    def mcp_call(self, tool_name: str, arguments: dict[str, Any],
                 server_id: Optional[str] = None, **kwargs: Any) -> dict[str, Any]:
        import urllib.request
        import urllib.error

        payload: dict[str, Any] = {"name": tool_name, "arguments": arguments}
        if server_id:
            payload["server_id"] = server_id
        payload.update(kwargs)
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/mcp-rest/tools/call",
            data=data, headers=self._headers(), method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            logger.warning("MCP tool call via LiteLLM failed (%s): %s", tool_name, body)
            return {}
        except urllib.error.URLError as exc:
            logger.warning("Cannot reach LiteLLM for MCP tool %s: %s", tool_name, exc)
            return {}
        except json.JSONDecodeError as exc:
            logger.warning("Invalid JSON from LiteLLM MCP call: %s", exc)
            return {}


class _SyncAsyncWrapper:
    """Wraps an async LiteLLMClient from the runner so skill code can call it sync."""

    def __init__(self, async_client):
        self._client = async_client
        self.base_url = getattr(async_client, "base_url", LITELLM_BASE_URL)

    def chat_completion(self, model, messages, **kwargs):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self._client.chat_completion(model, messages, **kwargs))
        finally:
            loop.close()

    def mcp_call(self, tool_name, arguments, server_id=None, **kwargs):
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                self._client.mcp_call(tool_name, arguments, server_id=server_id, **kwargs)
            )
        finally:
            loop.close()


def _resolve_litellm_client(litellm_client=None) -> Any:
    if litellm_client is None:
        return _SyncLiteLLMClient()
    if hasattr(litellm_client, "chat_completion") and hasattr(litellm_client, "mcp_call"):
        import inspect
        if inspect.iscoroutinefunction(litellm_client.chat_completion):
            return _SyncAsyncWrapper(litellm_client)
        return litellm_client
    return _SyncLiteLLMClient()


# ---------------------------------------------------------------------------
# Robust MCP result extraction
# ---------------------------------------------------------------------------


def _extract_results(result: Any) -> list[dict]:
    """
    Normalize an MCP tool response into a list of result dicts.

    Handles the response shapes returned by the skill-runner's LiteLLMClient
    and the /mcp-rest gateway:
      - {"structuredContent": {"result": [...]}}  (mcp-rest gateway, primary)
      - {"structuredContent": [...]}               (mcp-rest gateway, list)
      - {"result": {"results": [...]}}             (structuredContent variant)
      - {"result": [...]}                          (structured list)
      - {"results": [...]}
      - {"content": [{"type": "text", "text": "<json>"}]}  (content-only)
      - {"output": [{"type": "text", "text": "<json>"}]}
    """
    if not result:
        return []

    # 0. mcp-rest gateway: structuredContent (primary shape)
    sc = result.get("structuredContent")
    if isinstance(sc, list):
        return [r for r in sc if isinstance(r, dict)]
    if isinstance(sc, dict):
        for key in ("result", "results", "data", "items", "matches"):
            if isinstance(sc.get(key), list):
                return [r for r in sc[key] if isinstance(r, dict)]
        # structuredContent dict that is itself a single record
        if any(k in sc for k in ("title", "url", "snippet", "ticker", "name")):
            return [sc]

    # 1. structured "result" key
    res = result.get("result")
    if isinstance(res, list):
        return [r for r in res if isinstance(r, dict)]
    if isinstance(res, dict):
        for key in ("results", "data", "items", "matches"):
            if isinstance(res.get(key), list):
                return [r for r in res[key] if isinstance(r, dict)]
        return [res]

    # 2. top-level list keys
    for key in ("results", "data", "items", "matches"):
        if isinstance(result.get(key), list):
            return [r for r in result[key] if isinstance(r, dict)]

    # 3. content-only: parse the first text item as JSON (content OR output)
    for key in ("content", "output"):
        output = result.get(key)
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    try:
                        parsed = json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(parsed, list):
                        return [r for r in parsed if isinstance(r, dict)]
                    if isinstance(parsed, dict):
                        for k in ("result", "results", "data", "items", "matches"):
                            if isinstance(parsed.get(k), list):
                                return [r for r in parsed[k] if isinstance(r, dict)]
                        return [parsed]
    return []


def _search(client: Any, tool: str, query: str, max_results: int = 5) -> list[dict]:
    """Run a search tool via mcp_search and return normalized result dicts."""
    result = client.mcp_call(tool, {"query": query, "max_results": max_results},
                             server_id="mcp_search")
    items = _extract_results(result)
    logger.info("%s returned %d results for: %s", tool, len(items), query[:80])
    return items[:max_results]


# ---------------------------------------------------------------------------
# Product brief parsing
# ---------------------------------------------------------------------------


def _derive_product_info(brief: str) -> tuple[str, str]:
    """
    Derive a short product name and a market category from the brief.

    Heuristic: use the first ~6 words as the product name and the first ~10
    words as the category context. Good enough for query templating.
    """
    cleaned = re.sub(r"\s+", " ", brief).strip()
    words = cleaned.split()
    product = " ".join(words[:6]).strip().strip(",.:;")
    if len(product) > 48:
        product = product[:48].rstrip() + "…"
    category = " ".join(words[:10]).strip()
    if len(category) > 60:
        category = category[:60].rstrip() + "…"
    return product, category or "product"


def _build_research_queries(product: str, category: str,
                            competitors: Optional[str]) -> list[str]:
    """Build the list of research queries for the market-research phase."""
    year = datetime.now(timezone.utc).year
    queries = [
        q.format(product=product, category=category, year=year)
        for q in DEFAULT_RESEARCH_QUERIES
    ]
    if competitors and competitors.strip():
        queries.append(f"competitor analysis {competitors.strip()} vs {product}")
    return queries


# ---------------------------------------------------------------------------
# LLM synthesis
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a senior go-to-market (GTM) strategy consultant. You produce
    rigorous, actionable launch plans grounded in real market research.

    You will be given:
      1. A product/service brief.
      2. Market research findings (competitors, market size, trends, audience).

    Produce a comprehensive GTM strategy in Markdown with these sections:

    ## 1. Executive Summary
    - 3-5 sentence overview of the opportunity and recommended approach.

    ## 2. Market Overview
    - Market definition and boundaries.
    - TAM / SAM / SOM estimates WITH methodology (label estimates clearly).
    - Key growth drivers and trends.

    ## 3. Competitive Landscape
    - A comparison table of the top 3-5 competitors:
      | Competitor | Positioning | Pricing | Strengths | Weaknesses |
    - Identify gaps and differentiation opportunities.

    ## 4. Target Audience
    - 2-3 buyer personas (name, role, pain points, buying behavior).
    - Primary vs secondary segments.

    ## 5. Value Proposition & Positioning
    - Core value proposition statement.
    - Positioning statement (for X who Y, Product is Z that W).
    - 3 key messages / proof points.

    ## 6. Pricing Strategy
    - Recommended pricing model and tiers with rationale.

    ## 7. Channel Strategy
    - Prioritized acquisition channels (ranked) with why.
    - Launch sequencing.

    ## 8. Launch Plan
    - 30/60/90-day action plan with concrete tasks.

    ## 9. Risks & Mitigations
    - Top risks and how to mitigate each.

    Rules:
    - Ground every claim in the provided research where possible; cite source
      titles inline in parentheses.
    - Clearly distinguish hard data from estimates/assumptions.
    - Be specific and actionable — avoid generic filler.
    - Use tables where they add clarity.
    - Output ONLY the Markdown strategy — no preamble, no JSON wrapper.
""")


def _format_research(research: list[dict], max_items: int = 30) -> str:
    """Format research findings into a compact context block for the LLM."""
    if not research:
        return (
            "(No external research results were returned. Rely on your "
            "knowledge and clearly label all figures as estimates.)"
        )
    lines = []
    seen_urls: set[str] = set()
    for item in research[:max_items]:
        url = (item.get("url") or "").strip()
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        title = (item.get("title") or "Untitled").strip()
        snippet = (item.get("snippet") or item.get("content") or "").strip()
        line = f"- **{title}**"
        if snippet:
            one = snippet.split("\n")[0].strip()
            if len(one) > 220:
                one = one[:217] + "…"
            line += f" — {one}"
        if url:
            line += f" ({url})"
        lines.append(line)
    return "\n".join(lines)


def _synthesize_strategy(client: Any, brief: str, research: list[dict],
                         competitors: Optional[str]) -> str:
    """Synthesize the GTM strategy via LLM chat completion through LiteLLM."""
    research_block = _format_research(research)

    user_content = textwrap.dedent(f"""\
        # Product / Service Brief
        {brief}

        # Known Competitors (if any)
        {competitors or "(none provided — discover from research)"}

        # Market Research Findings
        {research_block}

        Synthesize the full GTM strategy now. Output ONLY the Markdown.
    """)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    result = client.chat_completion(
        MODEL_ALIAS,
        messages,
        max_tokens=8000,
        temperature=0.4,
        stream=False,
    )

    choices = result.get("choices", [])
    if not choices:
        return "# GTM Strategy\n\n**No strategy generated.** LLM returned no content.\n"
    content = (choices[0].get("message") or {}).get("content")
    if not content:
        return "# GTM Strategy\n\n**No strategy generated.** LLM returned empty content.\n"
    return content.strip()


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\-]+", "-", value).strip("-").lower()
    return slug[:60] or "gtm"


def _write_artifact(report: str, slug: str) -> Optional[str]:
    """Save the GTM strategy as a Markdown artifact. Returns path or None."""
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"gtm_{ts}_{slug}.md"
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


def run(params: dict[str, Any], job, litellm_client=None) -> dict[str, Any]:
    """
    Execute the marketing_strategy (GTM) skill.

    All LLM and MCP interactions go through LiteLLM. This skill never
    contacts MCP servers directly.

    Args:
        params: Skill parameters (prompt, target_market, competitors,
                max_research_queries).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.

    Returns:
        Dict with 'summary', 'report', 'artifact_path', 'product',
        'research_count', 'model_alias'.
    """
    client = _resolve_litellm_client(litellm_client)

    # Validate inputs
    brief = str(params.get("prompt") or "").strip()
    if not brief:
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing 'prompt' (product brief)")
        return {"error": "Missing required 'prompt' parameter (product/service brief)"}

    target_market = (str(params.get("target_market") or "").strip() or None)
    competitors = (str(params.get("competitors") or "").strip() or None)
    max_queries = int(params.get("max_research_queries", 4))
    max_queries = max(1, min(max_queries, 8))  # clamp

    product, category = _derive_product_info(brief)

    if hasattr(job, "add_log"):
        job.add_log(f"Executing marketing_strategy: product='{product}' category='{category}'")
        job.add_log(f"Model alias: {MODEL_ALIAS}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")
        job.add_log(f"LiteLLM: {client.base_url}")
        if target_market:
            job.add_log(f"Target market: {target_market}")
        if competitors:
            job.add_log(f"Known competitors: {competitors}")

    _install_timeout()

    try:
        # Phase 1: Market research via mcp_search
        queries = _build_research_queries(product, category, competitors)[:max_queries]
        if hasattr(job, "add_log"):
            job.add_log(f"Phase 1: market research — {len(queries)} queries")

        research: list[dict] = []
        for q in queries:
            if hasattr(job, "add_log"):
                job.add_log(f"  search_web: {q}")
            research.extend(_search(client, "search_web", q, max_results=5))

        # Deduplicate research by URL
        seen: set[str] = set()
        unique_research: list[dict] = []
        for item in research:
            url = (item.get("url") or "").lower().strip().rstrip("/")
            if not url or url in seen:
                continue
            seen.add(url)
            unique_research.append(item)
        research = unique_research

        if hasattr(job, "add_log"):
            job.add_log(f"Phase 1 complete: {len(research)} unique research items")

        # Phase 2: Synthesize GTM strategy via LLM
        if hasattr(job, "add_log"):
            job.add_log("Phase 2: synthesizing GTM strategy via LLM...")

        report = _synthesize_strategy(client, brief, research, competitors)

        if hasattr(job, "add_log"):
            job.add_log(f"Strategy generated ({len(report)} chars)")

        # Phase 3: Save artifact
        artifact_path = _write_artifact(report, _slugify(product))
        if hasattr(job, "add_log"):
            job.add_log(f"Artifact saved: {artifact_path or '(inline only)'}")

        # Extract summary (first ~5 non-empty lines)
        summary_lines = [ln for ln in report.strip().split("\n") if ln.strip()][:5]
        summary = " ".join(summary_lines).strip()

        return {
            "summary": summary,
            "report": report,
            "artifact_path": artifact_path,
            "product": product,
            "category": category,
            "research_count": len(research),
            "model_alias": MODEL_ALIAS,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "summary": f"GTM strategy timed out after {MAX_RUNTIME_SECS}s.",
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")
        return {"summary": f"GTM strategy failed: {msg}", "error": msg, "model_alias": MODEL_ALIAS}

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)
        return {"summary": f"GTM strategy failed: {msg}", "error": msg, "model_alias": MODEL_ALIAS}

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# CLI entrypoint (for standalone testing)
# ---------------------------------------------------------------------------


class _MockJob:
    def __init__(self):
        self.logs: list[str] = []

    def add_log(self, msg: str) -> None:
        self.logs.append(msg)
        print(f"  [LOG] {msg}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="marketing_strategy standalone test")
    parser.add_argument("--prompt", required=True, help="Product/service brief")
    parser.add_argument("--target-market", default=None, help="Target market/segment")
    parser.add_argument("--competitors", default=None, help="Comma-separated known competitors")
    parser.add_argument("--max-queries", type=int, default=4, help="Max research queries")
    parser.add_argument("--dry-run", action="store_true", help="Print params without calling services")
    parser.add_argument("--base-url", default=None, help=f"LiteLLM base URL (default: {LITELLM_BASE_URL})")
    parser.add_argument("--api-key", default=None, help="LiteLLM API key")
    args = parser.parse_args()

    if args.dry_run:
        product, category = _derive_product_info(args.prompt)
        print("=== DRY RUN ===")
        print(f"  Product: {product}")
        print(f"  Category: {category}")
        print(f"  Target market: {args.target_market or '(none)'}")
        print(f"  Competitors: {args.competitors or '(none)'}")
        print(f"  Max research queries: {args.max_queries}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Artifact dir: {ARTIFACT_DIR}")
        print(f"  LiteLLM: {LITELLM_BASE_URL}")
        print("\n  Research queries:")
        for q in _build_research_queries(product, category, args.competitors)[:args.max_queries]:
            print(f"    - {q}")
        return

    client = _SyncLiteLLMClient(base_url=args.base_url or LITELLM_BASE_URL,
                                api_key=args.api_key or LITELLM_API_KEY)
    params = {
        "prompt": args.prompt,
        "target_market": args.target_market,
        "competitors": args.competitors,
        "max_research_queries": args.max_queries,
    }
    result = run(params, _MockJob(), litellm_client=client)

    print("\n--- marketing_strategy response ---")
    print(f"Summary: {result.get('summary', 'N/A')[:300]}")
    print(f"Product: {result.get('product', 'N/A')}")
    print(f"Research items: {result.get('research_count', 0)}")
    if result.get("artifact_path"):
        print(f"Artifact: {result['artifact_path']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"Report length: {len(result.get('report', ''))} chars")


if __name__ == "__main__":
    main()