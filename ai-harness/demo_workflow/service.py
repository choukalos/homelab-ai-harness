"""
Demo Workflow service: multi-agent demo creation with sub-agent delegation,
MySQL checkpoint persistence, and research tools.

Orchestrator agent follows the 8-phase demo creation workflow, delegates
research to sub-agents, and iteratively builds single-file HTML demos.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
import re
import uuid
import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from deepagents import create_deep_agent

from core.config import DEMO_WORKFLOW_MODEL, LITELLM_API_KEY, LITELLM_BASE_URL
from demo_workflow.prompts import DEMO_WORKFLOW_INSTRUCTIONS, RESEARCHER_INSTRUCTIONS
from demo_workflow.schemas import DemoCreateRequest, DemoCreateResponse, DemoBuildError
from demo_workflow.tools import generate_html, validate_html, fix_html, critique_demo, save_demo

logger = logging.getLogger("demo_workflow")

# ---------------------------------------------------------------------------
# MySQL checkpointer — reuse from deep_research to avoid duplicating init
# ---------------------------------------------------------------------------

# Both deep_research and demo_workflow use the same MySQL checkpoint tables
# in the same Python process. We import deep_research's checkpointer init
# and share it. The checkpointer is process-global and thread-safe.
from deep_research.service import (
    ensure_checkpointer_tables as _ensure_checkpointer_tables,
    get_checkpointer as _get_checkpointer,
)

ensure_checkpointer_tables = _ensure_checkpointer_tables
get_checkpointer = _get_checkpointer

# ---------------------------------------------------------------------------
# KB Lookup Tool — calls family_kb.search_kb with a timeout guard
# ---------------------------------------------------------------------------

@tool
def kb_lookup(query: str) -> str:
    """Search the family knowledge base for prior information relevant to
    this demo. Use this before web research to check for existing demos,
    user notes, or domain-specific knowledge.

    Args:
        query: Search query for the knowledge base

    Returns:
        Relevant knowledge base results or a message if unavailable.
    """
    import httpx
    from core.config import SEARXNG_BASE_URL

    try:
        from family_kb.service import search_kb
        from family_kb.schemas import SearchRequest

        result = search_kb(SearchRequest(query=query, limit=10))

        if not result.get("results"):
            return f"No prior knowledge found for '{query}'."

        lines = [f"## KB Results for '{query}'\n"]
        for hit in result["results"]:
            source = hit.get("source", "unknown")
            text = (hit.get("text", "") or "")[:600]
            score = hit.get("score", 0)
            lines.append(f"- **Source**: {source} (score: {score:.3f})\n  {text}")

        return "\n".join(lines)

    except Exception as e:
        # KB may fail due to embedding model not being cached (cold start)
        logger.warning("KB lookup failed (non-fatal): %s", e)
        return (
            f"KB lookup unavailable: {e}. "
            "This can happen on first use when the embedding model is downloading. "
            "Proceed with web research instead."
        )


# ---------------------------------------------------------------------------
# Agent factory: orchestrator + research sub-agent
# ---------------------------------------------------------------------------

MAX_RESEARCHER_ITERATIONS = 3
_agent: Any | None = None


def _build_research_subagent() -> dict:
    current_date = datetime.now().strftime("%Y-%m-%d")
    from deep_research.tools import search_and_crawl, think_tool

    return {
        "name": "research-agent",
        "description": (
            "Delegate research to the sub-agent. Research competitor products, "
            "UX patterns, and best practices for the demo being built. "
            "Give the researcher one focused topic at a time."
        ),
        "system_prompt": RESEARCHER_INSTRUCTIONS.format(date=current_date),
        "tools": [search_and_crawl, think_tool],
    }


def get_deep_agent() -> Any:
    global _agent
    if _agent is not None:
        return _agent

    from langchain_openai import ChatOpenAI
    from deep_research.tools import search_and_crawl, think_tool

    model_name = os.getenv("DEMO_WORKFLOW_MODEL", DEMO_WORKFLOW_MODEL)
    if ":" in model_name:
        model_name = model_name.split(":")[-1]

    model_instance = ChatOpenAI(
        model=model_name,
        openai_api_base=f"{LITELLM_BASE_URL.rstrip('/')}/v1",
        openai_api_key=LITELLM_API_KEY,
    )

    cp = get_checkpointer()
    research_subagent = _build_research_subagent()

    # Orchestrator tools:
    # - search_and_crawl, think_tool (direct research if needed)
    # - kb_lookup (family knowledge base)
    # - generate_html, validate_html, fix_html (Phase 6 build loop)
    # - critique_demo (Phase 7 polish)
    # - save_demo (Phase 8 final save)
    # - write_file, read_file (provided by deepagents framework)
    orchestrator_tools = [
        search_and_crawl,
        think_tool,
        kb_lookup,
        generate_html,
        validate_html,
        fix_html,
        critique_demo,
        save_demo,
    ]
    _agent = create_deep_agent(
        model=model_instance,
        tools=orchestrator_tools,
        system_prompt=DEMO_WORKFLOW_INSTRUCTIONS,
        subagents=[research_subagent],
        checkpointer=cp,
    )
    logger.info(
        "Demo workflow agent initialized (model=%s, checkpointer=MySQL, subagents=1, tools=%d).",
        model_name,
        len(orchestrator_tools),
    )
    return _agent


# ---------------------------------------------------------------------------
# Public service entrypoint
# ---------------------------------------------------------------------------

async def run_demo(req: DemoCreateRequest) -> DemoCreateResponse:
    """Run the demo creation agent pipeline.

    The agent follows the 8-phase workflow (parse → KB lookup → research →
    design → build plan → build loop → polish → save) using its system
    prompt and available tools.
    """
    thread_id = req.thread_id or str(uuid.uuid4())
    agent = get_deep_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    input_state = {
        "messages": [HumanMessage(content=req.prompt)],
    }

    try:
        result = await agent.ainvoke(input_state, config)
        messages = result.get("messages", [])

        # Extract outputs from agent message history
        title = _extract_title(messages, req.title)
        slug = _extract_slug(messages)
        html_path = _extract_html_path(messages)
        metadata = _extract_metadata(messages)

        # Validate that the agent actually completed the workflow by calling save_demo.
        # If html_path is empty the agent never reached Phase 8 (files were never written).
        if not html_path:
            logger.warning(
                "Demo run completed without calling save_demo (agent may be overwhelmed "
                "by prompt/tool complexity). Returning error for thread_id=%s",
                thread_id,
            )
            return DemoBuildError(
                thread_id=thread_id,
                title=title if title else req.title or "Untitled Demo",
                slug=slug,
                status="error",
                error=(
                    "Agent completed without calling save_demo. "
                    "This usually means the model couldn't handle the tool-calling workflow. "
                    "Try a more capable model or simplify the prompt."
                ),
            )

        return DemoCreateResponse(
            thread_id=thread_id,
            title=title,
            slug=slug,
            status="completed",
            build_step="final_save",
            html_path=html_path,
            metadata=metadata,
        )

    except Exception as e:
        logger.exception("Demo creation failed: %s", e)
        return DemoBuildError(
            thread_id=thread_id,
            title=req.title,
            slug="",
            status="error",
            error=str(e),
        )


# ---------------------------------------------------------------------------
# Helpers: extract structured data from the LangGraph message list
# ---------------------------------------------------------------------------

def _safe_get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_title(messages: list, fallback: str) -> str:
    """Extract the demo title from write_file targeting demo_brief.md,
    or from the final AI message, or fall back to the request title."""
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
                            args = json.loads(args)
                        except Exception:
                            pass
                    if not isinstance(args, dict):
                        continue
                    path = args.get("path", "")
                    if "demo_brief.md" in str(path):
                        content = args.get("content", "")
                        if content:
                            # Try to extract title from the brief content
                            for line in content.split("\n")[:20]:
                                line = line.strip()
                                if line.startswith("#"):
                                    return line.lstrip("# ").strip()
                            # Fallback: first meaningful line
                            for line in content.split("\n"):
                                line = line.strip()
                                if line and not line.startswith("#"):
                                    return line[:80]
    # Fallback
    return fallback if fallback else "Untitled Demo"


def _extract_slug(messages: list) -> str:
    """Extract slug from demo_brief content or generate from title."""
    import re as _re
    title = _extract_title(messages, "")
    if title:
        slug = _re.sub(r"[^a-zA-Z0-9]+", "-", title).lower().strip("-")
        if len(slug) > 60:
            slug = slug[:60]
        return f"{slug}-{datetime.now().strftime('%Y%m%d%H%M')}"
    return ""


def _extract_html_path(messages: list) -> str:
    """Extract the final HTML file path from write_file calls."""
    for msg in reversed(messages):
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role in ("ai", "assistant"):
            tool_calls = _safe_get(msg, "tool_calls") or []
            for tc in reversed(tool_calls):
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                if name == "write_file":
                    args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            pass
                    if not isinstance(args, dict):
                        continue
                    path = args.get("path", "")
                    if "final_demo.html" in str(path):
                        return str(path)
    return ""


def _extract_metadata(messages: list) -> dict[str, Any]:
    """Extract demo metadata from save_demo output or write_file calls."""
    for msg in messages:
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role == "tool":
            content_str = str(_safe_get(msg, "content", ""))
            # Look for save_demo result containing URLs
            if "local_url" in content_str or "public_url" in content_str:
                try:
                    # Try to extract JSON from the tool output
                    start = content_str.find("{")
                    end = content_str.rfind("}") + 1
                    if start >= 0 and end > start:
                        return json.loads(content_str[start:end])
                except (json.JSONDecodeError, ValueError):
                    pass

    # Fallback: basic metadata
    title = _extract_title(messages, "")
    slug = _extract_slug(messages)
    html_path = _extract_html_path(messages)
    return {
        "title": title,
        "slug": slug,
        "html_path": html_path,
    }


def _extract_final_html(messages: list) -> str:
    """Extract the final HTML content from save_demo or write_file targeting
    final_demo.html.

    Priority 1: Find write_file targeting final_demo.html and extract content
                from the tool call args.
    Priority 2: Find write_file targeting current_build.html.
    Priority 3: Scan for any large HTML-like content in tool results.
    """
    # Priority 1: write_file targeting final_demo.html
    for msg in reversed(messages):
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role in ("ai", "assistant"):
            tool_calls = _safe_get(msg, "tool_calls") or []
            for tc in reversed(tool_calls):
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                if name == "write_file":
                    args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            pass
                    if not isinstance(args, dict):
                        continue
                    path = args.get("path", "")
                    if "final_demo.html" in str(path):
                        content = args.get("content", "")
                        if content:
                            return str(content)

    # Priority 2: write_file targeting current_build.html
    for msg in reversed(messages):
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role in ("ai", "assistant"):
            tool_calls = _safe_get(msg, "tool_calls") or []
            for tc in reversed(tool_calls):
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                if name == "write_file":
                    args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            pass
                    if not isinstance(args, dict):
                        continue
                    path = args.get("path", "")
                    if "current_build.html" in str(path):
                        content = args.get("content", "")
                        if content:
                            return str(content)

    # Priority 3: Look for HTML in save_demo or generate_html tool results
    for msg in reversed(messages):
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role == "tool":
            content = _safe_get(msg, "content", "")
            if content and "<!DOCTYPE html>" in str(content):
                return str(content)

    return ""
