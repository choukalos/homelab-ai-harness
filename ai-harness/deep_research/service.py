"""
Deep Research service: LangChain Deep Agent with MySQL checkpoint persistence
and a SearXNG-based web-search tool.

This is the skeleton proof-of-concept — a single search node to validate the
end-to-end flow before expanding into multi-step research workflows.
"""

from __future__ import annotations

import os
import uuid
import logging
from typing import Any

import httpx
from langchain.tools import tool
from deepagents import create_deep_agent
from langgraph.checkpoint.mysql.asyncmy import AsyncMySaver

from core.config import HARNESS_MODEL, LITELLM_API_KEY, LITELLM_BASE_URL, SEARXNG_BASE_URL
from deep_research.schemas import DeepResearchRequest, DeepResearchResponse

logger = logging.getLogger("deep_research")

# ---------------------------------------------------------------------------
# MySQL checkpointer (lazy init so we don't hammer DB on import)
# ---------------------------------------------------------------------------

_checkpointer: AsyncMySaver | None = None


def _build_mysql_uri() -> str:
    """Build a mysql:// URI from the existing env vars used by workflows/db.py."""
    host = os.getenv("MYSQL_DB_HOST", "host.docker.internal")
    port = os.getenv("MYSQL_DB_PORT", "3306")
    user = os.getenv("AI_DB_USER", "root")
    password = os.getenv("AI_DB_PASS", "")
    dbname = os.getenv("AI_DB_NAME", "ai_harness")
    return f"mysql://{user}:{password}@{host}:{port}/{dbname}"


def get_checkpointer() -> AsyncMySaver:
    """Return a singleton AsyncMySaver for LangGraph checkpoints in MySQL."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = AsyncMySaver.from_conn_string(_build_mysql_uri())
    return _checkpointer


async def ensure_checkpointer_tables():
    """Create the checkpoint tables in MySQL if they don't already exist."""
    cp = get_checkpointer()
    await cp.asetup()
    logger.info("Deep-research MySQL checkpoint tables ensured.")


# ---------------------------------------------------------------------------
# Tool: web search via SearXNG
# ---------------------------------------------------------------------------

@tool
def search_web(
    query: str,
    max_results: int = 5,
    category: str = "general",
) -> list[dict[str, Any]]:
    """
    Search the web via SearXNG.

    Returns a list of result dicts with title, url, and content snippet.
    """
    import httpx as _httpx

    params = {
        "q": query,
        "format": "json",
        "categories": category,
        "language": "en",
        "pageno": 1,
        "safesearch": 1,
    }

    try:
        r = _httpx.get(f"{SEARXNG_BASE_URL}/search", params=params, timeout=15.0)
        r.raise_for_status()
    except Exception as e:
        return [{"error": str(e)}]

    items = []
    for item in r.json().get("results", [])[:max_results]:
        items.append({
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
            "engine": item.get("engine", ""),
        })
    return items


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

_agent: Any | None = None  # CompiledStateGraph


def get_deep_agent() -> Any:
    """Build (once) the deep research agent with MySQL checkpointing."""
    global _agent
    if _agent is not None:
        return _agent

    model = os.getenv("HARNESS_MODEL", "gemma-moe")
    # For LiteLLM gateway, use the provider:model syntax that Deep Agents expects.
    # If model string contains no colon, default to openai-style through LiteLLM.
    if ":" not in model:
        # LiteLLM proxy speaks OpenAI-compatible, so prefix with openai:
        model_spec = f"openai:{model}"
    else:
        model_spec = model

    cp = get_checkpointer()

    _agent = create_deep_agent(
        model=model_spec,
        system_prompt=(
            "You are a deep research assistant. Your job is to use the search_web "
            "tool to find accurate, up-to-date information, then synthesize a "
            "clear, well-structured answer with source references."
        ),
        tools=[search_web],
        checkpointer=cp,
    )
    logger.info("Deep research agent initialized (model=%s, checkpointer=MySQL).", model_spec)
    return _agent


# ---------------------------------------------------------------------------
# Public service entrypoint
# ---------------------------------------------------------------------------

async def run_deep_research(
    req: DeepResearchRequest,
    client: httpx.AsyncClient,
) -> DeepResearchResponse:
    """Execute a deep-research query via the Deep Agent and return results."""

    thread_id = req.thread_id or str(uuid.uuid4())

    agent = get_deep_agent()

    # Build the config that LangGraph uses for checkpointing / thread scoping
    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    # Build the input message dict (LangGraph expects this structure)
    input_state = {
        "messages": [{"role": "user", "content": req.query}],
    }

    try:
        result = await agent.ainvoke(input_state, config)

        # Extract the final assistant message from the graph output
        messages = result.get("messages", [])
        answer = _extract_answer(messages)

        # Extract sources from tool results if present
        sources = _extract_sources(messages)
        steps = _extract_steps(messages)

        return DeepResearchResponse(
            thread_id=thread_id,
            query=req.query,
            answer=answer,
            sources=sources,
            steps=steps,
        )

    except Exception as e:
        logger.exception("Deep research failed: %s", e)
        return DeepResearchResponse(
            thread_id=thread_id,
            query=req.query,
            answer=f"Research failed: {e}",
            error=str(e),
        )


# ---------------------------------------------------------------------------
# Helpers: extract structured data from the LangGraph message list
# ---------------------------------------------------------------------------

def _extract_answer(messages: list[dict]) -> str:
    """Find the last assistant text message and return its content."""
    for msg in reversed(messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"]
    return "(No answer generated)"


def _extract_sources(messages: list[dict]) -> list[dict[str, Any]]:
    """Extract search results from tool_result messages."""
    sources: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "tool" or msg.get("tool_call_id"):
            content = msg.get("content", "")
            if content and "error" not in content:
                sources.append({"tool_result": content[:2000]})
    return sources


def _extract_steps(messages: list[dict]) -> list[dict[str, Any]]:
    """Build a high-level step log from tool/tool_result pairs."""
    steps: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                steps.append({
                    "action": tc.get("name", "unknown"),
                    "args": tc.get("args", {}),
                })
        elif role in ("tool", "function") and msg.get("content"):
            steps.append({
                "result_preview": str(msg["content"])[:500],
            })
    return steps
