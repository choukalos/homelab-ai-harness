"""
Deep Research service: multi-agent deep research with sub-agent delegation,
MySQL checkpoint persistence, and SearXNG + Crawl4AI web research tools.

Orchestrator agent plans research via TODOs, delegates to researcher sub-agents,
synthesizes findings, and writes a final report.
"""

from __future__ import annotations

from datetime import datetime
import os
import re
import uuid
import logging
from typing import Any

from langchain_core.messages import HumanMessage
from deepagents import create_deep_agent
from langgraph.checkpoint.mysql.asyncmy import AsyncMySaver

from core.config import DEEP_RESEARCH_MODEL, LITELLM_API_KEY, LITELLM_BASE_URL
from deep_research.prompts import (
    RESEARCH_WORKFLOW_INSTRUCTIONS,
    RESEARCHER_INSTRUCTIONS,
    SUBAGENT_DELEGATION_INSTRUCTIONS,
)
from deep_research.schemas import DeepResearchRequest, DeepResearchResponse
from deep_research.tools import search_and_crawl, think_tool

logger = logging.getLogger("deep_research")

# ---------------------------------------------------------------------------
# MySQL checkpointer (lazy init so we don't hammer DB on import)
# ---------------------------------------------------------------------------

_checkpointer_ctx = None
_checkpointer: AsyncMySaver | None = None


def _build_mysql_uri() -> str:
    host = os.getenv("MYSQL_DB_HOST", "host.docker.internal")
    port = os.getenv("MYSQL_DB_PORT", "3306")
    user = os.getenv("AI_DB_USER", "root")
    password = os.getenv("AI_DB_PASS", "")
    dbname = os.getenv("AI_DB_NAME", "ai_harness")
    return f"mysql://{user}:{password}@{host}:{port}/{dbname}"


def get_checkpointer() -> AsyncMySaver:
    global _checkpointer
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialized. Call ensure_checkpointer_tables() first.")
    return _checkpointer


async def ensure_checkpointer_tables():
    global _checkpointer, _checkpointer_ctx
    if _checkpointer is None:
        _checkpointer_ctx = AsyncMySaver.from_conn_string(_build_mysql_uri())
        _checkpointer = await _checkpointer_ctx.__aenter__()
        await _checkpointer.setup()
    logger.info("Deep-research MySQL checkpoint tables ensured.")


# ---------------------------------------------------------------------------
# Agent factory: orchestrator + researcher sub-agent
# ---------------------------------------------------------------------------

MAX_CONCURRENT_RESEARCH_UNITS = 3
MAX_RESEARCHER_ITERATIONS = 3
_agent: Any | None = None


def _build_instructions() -> str:
    return (
        RESEARCH_WORKFLOW_INSTRUCTIONS
        + "\n\n"
        + "=" * 80
        + "\n\n"
        + SUBAGENT_DELEGATION_INSTRUCTIONS.format(
            max_concurrent_research_units=MAX_CONCURRENT_RESEARCH_UNITS,
            max_researcher_iterations=MAX_RESEARCHER_ITERATIONS,
        )
    )


def _build_research_subagent() -> dict:
    current_date = datetime.now().strftime("%Y-%m-%d")
    return {
        "name": "research-agent",
        "description": (
            "Delegate research to the sub-agent researcher. "
            "Only give this researcher one topic at a time."
        ),
        "system_prompt": RESEARCHER_INSTRUCTIONS.format(date=current_date),
        "tools": [search_and_crawl, think_tool],
    }


def get_deep_agent() -> Any:
    global _agent
    if _agent is not None:
        return _agent

    from langchain_openai import ChatOpenAI

    model_name = os.getenv("DEEP_RESEARCH_MODEL", DEEP_RESEARCH_MODEL)
    if ":" in model_name:
        model_name = model_name.split(":")[-1]

    model_instance = ChatOpenAI(
        model=model_name,
        openai_api_base=f"{LITELLM_BASE_URL.rstrip('/')}/v1",
        openai_api_key=LITELLM_API_KEY,
    )

    cp = get_checkpointer()
    instructions = _build_instructions()
    research_subagent = _build_research_subagent()

    _agent = create_deep_agent(
        model=model_instance,
        tools=[search_and_crawl, think_tool],
        system_prompt=instructions,
        subagents=[research_subagent],
        checkpointer=cp,
    )
    logger.info(
        "Deep research agent initialized (model=%s, checkpointer=MySQL, subagents=1).",
        model_name,
    )
    return _agent


# ---------------------------------------------------------------------------
# Public service entrypoint
# ---------------------------------------------------------------------------

async def run_deep_research(req: DeepResearchRequest) -> DeepResearchResponse:
    thread_id = req.thread_id or str(uuid.uuid4())
    agent = get_deep_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    input_state = {
        "messages": [HumanMessage(content=req.query)],
    }

    try:
        result = await agent.ainvoke(input_state, config)
        messages = result.get("messages", [])
        answer = _extract_answer(messages)
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

def _safe_get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_answer(messages: list) -> str:
    """Extract the final report with citations.

    Priority 1: Find write_file tool call for /final_report.md and extract
                the report content directly from args.content.
                This is concurrency-safe — each run has its own isolated
                message list scoped by thread_id, so no file collisions.
    Priority 2: Fallback to last AI message.
    """
    import json as _json

    # Scan for write_file targeting final_report.md, extract from args
    for msg in messages:
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role in ("ai", "assistant"):
            tool_calls = _safe_get(msg, "tool_calls") or []
            for tc in tool_calls:
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                if name == "write_file":
                    args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                    if isinstance(args, str):
                        try:
                            args = _json.loads(args)
                        except Exception:
                            pass
                    if not isinstance(args, dict):
                        continue
                    path = args.get("path", "")
                    if "final_report.md" in str(path):
                        # Extract the actual report content from the tool call args
                        content = args.get("content", "") or args.get("text", "")
                        if content:
                            return str(content)

    # Fallback: last AI message
    for msg in reversed(messages):
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role in ("ai", "assistant"):
            content = _safe_get(msg, "content")
            if content:
                return str(content)
    return "(No answer generated)"


def _extract_sources(messages: list) -> list[dict[str, Any]]:
    """Extract source URLs from search_and_crawl tool results.

    Parses markdown format: ## Title\n**URL:** url\n...
    Deduplicates by URL. Returns [{title, url}] list.
    """
    seen_urls: set[str] = set()
    sources: list[dict[str, Any]] = []

    for msg in messages:
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role != "tool":
            continue
        content_str = str(_safe_get(msg, "content", ""))

        # Skip pure errors
        if not content_str or ("error" in content_str.lower() and "## " not in content_str):
            if "error" in content_str.lower():
                sources.append({"error": content_str[:500]})
            continue

        # Parse ## Title\n**URL:** url pattern
        for match in re.finditer(r'## (.+?)\n\*\*URL:\*\*\s*(.+?)\n', content_str):
            title = match.group(1).strip()
            url = match.group(2).strip()
            if url in seen_urls or not url.startswith("http"):
                continue
            seen_urls.add(url)
            sources.append({
                "title": title,
                "url": url,
            })

    return sources


def _extract_steps(messages: list) -> list[dict[str, Any]]:
    """Build a high-level step log from tool/tool_result pairs."""
    steps: list[dict[str, Any]] = []
    for msg in messages:
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        tool_calls = _safe_get(msg, "tool_calls")
        content = _safe_get(msg, "content")

        if role in ("ai", "assistant") and tool_calls:
            for tc in tool_calls:
                steps.append({
                    "action": tc.get("name", "unknown") if isinstance(tc, dict) else getattr(tc, "name", "unknown"),
                    "args": tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {}),
                })
        elif role == "tool" and content:
            steps.append({
                "result_preview": str(content)[:500],
            })
    return steps
