"""
Demo Workflow service: deep agent pattern with MySQL checkpointing.

Uses the same pattern as deep_research:
  User Prompt → FastAPI → run_demo(req) → get_deep_agent().ainvoke(input_state, config)
    Orchestrator Agent (deep agents framework):
      ↳  kb_lookup, search_and_crawl, think_tool, generate_html,
          validate_html, fix_html, verify_interactivity, critique_demo, save_demo
      ↳  task() sub-agent → researcher (search_and_crawl + think_tool)
    MySQL Checkpointing (AsyncMySaver) — auto-persists after each step

The agent follows DEMO_WORKFLOW_INSTRUCTIONS to build demos step-by-step,
using write_file/read_file for intermediate artifacts and write_todos for
progress tracking. The deepagents framework handles context management,
compression, and sub-agent isolation.
"""

from __future__ import annotations

from datetime import datetime
import json
import os
import re
import uuid
import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from deepagents import create_deep_agent
from langgraph.checkpoint.mysql.asyncmy import AsyncMySaver

from core.config import DEMO_WORKFLOW_MODEL, LITELLM_API_KEY, LITELLM_BASE_URL
from demo_workflow.prompts import (
    DEMO_WORKFLOW_INSTRUCTIONS,
    RESEARCHER_INSTRUCTIONS,
)
from demo_workflow.schemas import (
    DemoCreateRequest,
    DemoCreateResponse,
    DemoCheckpointStatus,
    DemoStreamEvent,
)
from demo_workflow.tools import (
    kb_lookup,
    generate_html,
    validate_html,
    fix_html,
    verify_interactivity,
    critique_demo,
    save_demo,
    search_and_crawl,
    think_tool,
)

logger = logging.getLogger("demo_workflow")

# ---------------------------------------------------------------------------
# MySQL checkpointer (matches deep_research pattern)
# ---------------------------------------------------------------------------

_checkpointer_ctx = None
_checkpointer: AsyncMySaver | None = None


def _build_mysql_uri() -> str:
    import os as _os
    host = _os.getenv("MYSQL_DB_HOST", "host.docker.internal")
    port = _os.getenv("MYSQL_DB_PORT", "3306")
    user = _os.getenv("AI_DB_USER", "root")
    password = _os.getenv("AI_DB_PASS", "")
    dbname = _os.getenv("AI_DB_NAME", "ai_harness")
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
    logger.info("Demo-workflow MySQL checkpoint tables ensured.")


# ---------------------------------------------------------------------------
# Agent factory: orchestrator + research sub-agent
# ---------------------------------------------------------------------------

MAX_RESEARCHER_ITERATIONS = 3
_agent: Any | None = None


def _build_research_subagent() -> dict:
    current_date = datetime.now().strftime("%Y-%m-%d")

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
    """Create or return the cached deep agent instance.

    Deep agent with orchestrator + research sub-agent.
    MySQL checkpointing via AsyncMySaver (shared with deep_research).
    """
    global _agent
    if _agent is not None:
        return _agent

    from langchain_openai import ChatOpenAI

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

    orchestrator_tools = [
        search_and_crawl,
        think_tool,
        kb_lookup,
        generate_html,
        validate_html,
        fix_html,
        verify_interactivity,
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
    """Run the demo creation agent synchronously.

    Invokes the deep agent with the user's prompt. The agent follows
    DEMO_WORKFLOW_INSTRUCTIONS to research, design, build, verify, and
    save the demo. MySQL checkpointing auto-persists after each step.

    Args:
        req: The demo creation request.

    Returns:
        DemoCreateResponse with results.
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

        title = _extract_title(messages, req.title or "Untitled Demo")
        slug = _extract_slug(messages) or _make_slug(title)
        metadata = _extract_metadata(messages)
        build_step = _extract_build_step(messages)

        return DemoCreateResponse(
            thread_id=thread_id,
            title=title,
            slug=slug,
            status="completed",
            build_step=build_step,
            html_path=metadata.get("html_path", ""),
            metadata=metadata,
        )

    except Exception as e:
        logger.exception("Demo creation failed: %s", e)
        return DemoCreateResponse(
            thread_id=thread_id,
            title=req.title or "Untitled Demo",
            slug=_make_slug(req.title or "Untitled Demo"),
            status="error",
            build_step="",
            html_path="",
            metadata={},
            error=str(e),
        )


async def resume_demo(thread_id: str) -> DemoCreateResponse:
    """Resume a demo pipeline from a saved MySQL checkpoint.

    Re-invokes the agent with the same thread_id. The MySQL checkpointer
    auto-resumes from the last persisted state.

    Args:
        thread_id: The thread ID of the interrupted run.

    Returns:
        DemoCreateResponse with results.
    """
    agent = get_deep_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    # Re-invoke with empty new message — the checkpointer resumes from
    # the last state. We send a minimal continuation prompt.
    input_state = {
        "messages": [HumanMessage(content="Continue the demo build from where you left off.")],
    }

    try:
        result = await agent.ainvoke(input_state, config)
        messages = result.get("messages", [])

        # Extract title from existing message history
        title = _extract_title(messages, "Untitled Demo")
        slug = _extract_slug(messages) or _make_slug(title)
        metadata = _extract_metadata(messages)

        return DemoCreateResponse(
            thread_id=thread_id,
            title=title,
            slug=slug,
            status="completed",
            build_step=_extract_build_step(messages),
            html_path=metadata.get("html_path", ""),
            metadata=metadata,
        )

    except Exception as e:
        logger.exception("Demo resume failed for thread=%s: %s", thread_id, e)
        return DemoCreateResponse(
            thread_id=thread_id,
            title="",
            slug=thread_id,
            status="error",
            build_step="",
            html_path="",
            metadata={},
            error=f"Resume failed: {e}",
        )


def get_checkpoint_status(thread_id: str) -> DemoCheckpointStatus:
    """Get the checkpoint status for a thread by querying the agent's checkpointer.

    Returns whether a checkpoint exists and basic info about it.
    """
    try:
        agent = get_deep_agent()
        # Try to get state from the checkpointer
        config = {"configurable": {"thread_id": thread_id}}

        # Check if there's any saved state by trying to get the graph state
        # The agent graph stores state in the checkpointer
        try:
            state = agent.get_state(config)
            if state and state.values:
                messages = state.values.get("messages", [])
                if messages:
                    title = _extract_title(messages, "")
                    return DemoCheckpointStatus(
                        thread_id=thread_id,
                        exists=True,
                        title=title,
                        created_at="",
                        expires_at="",
                        can_resume=True,
                    )
        except Exception:
            # No state found or error accessing it
            pass

        return DemoCheckpointStatus(
            thread_id=thread_id,
            exists=False,
        )
    except Exception as e:
        logger.warning("Checkpoint status check failed for thread=%s: %s", thread_id, e)
        return DemoCheckpointStatus(thread_id=thread_id, exists=False)


def remove_checkpoint(thread_id: str) -> dict:
    """Remove a checkpoint for a thread. Returns status dict."""
    try:
        agent = get_deep_agent()
        config = {"configurable": {"thread_id": thread_id}}
        # Delete all checkpoints for this thread
        try:
            agent.checkpointer.delete_thread(thread_id)
            return {
                "thread_id": thread_id,
                "removed": True,
                "message": "Checkpoint removed",
            }
        except Exception:
            return {
                "thread_id": thread_id,
                "removed": False,
                "message": "No checkpoint found",
            }
    except Exception as e:
        logger.warning("Checkpoint removal failed for thread=%s: %s", thread_id, e)
        return {
            "thread_id": thread_id,
            "removed": False,
            "message": f"Error removing checkpoint: {e}",
        }


# ---------------------------------------------------------------------------
# SSE Streaming — agent.astream() for real-time events
# ---------------------------------------------------------------------------

async def _run_demo_with_events(
    req: DemoCreateRequest,
) -> DemoStreamEvent:
    """Stream the demo creation output via agent.astream().

    Maps agent state transitions to DemoStreamEvent events for SSE.
    Each state update (tool call, tool result, AI response) becomes an event.

    Unlike the old coordinator-pattern streaming, this provides true
    real-time agent events from the deep agents framework.

    Yields:
        DemoStreamEvent objects with event_type in:
        pipeline_start, phase_start, phase_progress, phase_complete,
        pipeline_complete, error.
    """
    import time as _time

    thread_id = req.thread_id or str(uuid.uuid4())
    pipeline_start = _time.time()

    agent = get_deep_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    input_state = {
        "messages": [HumanMessage(content=req.prompt)],
    }

    # Emit pipeline start
    yield DemoStreamEvent(
        event_type="pipeline_start",
        elapsed=_format_elapsed(_time.time() - pipeline_start),
        data={
            "thread_id": thread_id,
            "title": req.title or "",
            "prompt": req.prompt,
        },
    )

    try:
        for chunk in await agent.astream(input_state, config):
            elapsed = _format_elapsed(_time.time() - pipeline_start)

            # Process each streamed chunk
            messages = chunk.get("messages", [])
            for msg in messages:
                role = _safe_get(msg, "role") or _safe_get(msg, "type")

                if role in ("ai", "assistant"):
                    # AI message — check for tool calls
                    tool_calls = _safe_get(msg, "tool_calls") or []
                    content = _safe_get(msg, "content")

                    if tool_calls:
                        for tc in tool_calls:
                            tool_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                            yield DemoStreamEvent(
                                event_type="phase_progress",
                                elapsed=elapsed,
                                data={
                                    "message": f"Calling {tool_name}…",
                                    "tool": tool_name,
                                },
                            )
                    elif content:
                        # AI text response
                        yield DemoStreamEvent(
                            event_type="phase_complete",
                            elapsed=elapsed,
                            data={
                                "summary": str(content)[:200],
                            },
                        )

                elif role == "tool":
                    # Tool result
                    content = str(_safe_get(msg, "content", ""))
                    # Try to infer tool name from content
                    if "local_url" in content or "public_url" in content:
                        yield DemoStreamEvent(
                            event_type="phase_complete",
                            elapsed=elapsed,
                            data={"summary": "Demo saved successfully"},
                        )
                    elif "score" in content:
                        yield DemoStreamEvent(
                            event_type="phase_complete",
                            elapsed=elapsed,
                            data={"summary": content[:100]},
                        )
                    else:
                        yield DemoStreamEvent(
                            event_type="phase_progress",
                            elapsed=elapsed,
                            data={"message": content[:150]},
                        )

        # Pipeline complete — extract final results from the last streamed state
        # Use get_state() to read from the MySQL checkpoint (avoids re-running the agent)
        try:
            state = agent.get_state(config)
            messages = list(state.values.get("messages", []))
        except Exception:
            messages = []

        title = _extract_title(messages, req.title or "Untitled Demo")
        slug = _extract_slug(messages) or _make_slug(title)
        metadata = _extract_metadata(messages)

        yield DemoStreamEvent(
            event_type="pipeline_complete",
            elapsed=_format_elapsed(_time.time() - pipeline_start),
            data={
                "status": "completed",
                "thread_id": thread_id,
                "title": title,
                "slug": slug,
                "html_path": metadata.get("html_path", ""),
                "metadata": metadata,
                "total_build_time_seconds": round(_time.time() - pipeline_start, 1),
            },
        )

    except Exception as e:
        logger.exception("Demo stream error: %s", e)
        yield DemoStreamEvent(
            event_type="error",
            elapsed=_format_elapsed(_time.time() - pipeline_start),
            data={"error": str(e)},
        )
        yield DemoStreamEvent(
            event_type="pipeline_complete",
            elapsed=_format_elapsed(_time.time() - pipeline_start),
            data={
                "status": "error",
                "error": str(e),
                "thread_id": thread_id,
                "total_build_time_seconds": round(_time.time() - pipeline_start, 1),
            },
        )


def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as m:ss (e.g. '0:42', '12:34')."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Helpers: extract structured data from LangGraph message list
# ---------------------------------------------------------------------------

def _safe_get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_title(messages: list, fallback: str) -> str:
    """Extract the demo title from write_file targeting demo_brief.md."""
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
                            for line in content.split("\n")[:20]:
                                line = line.strip()
                                if line.startswith("#"):
                                    return line.lstrip("# ").strip()
                            for line in content.split("\n"):
                                line = line.strip()
                                if line and not line.startswith("#"):
                                    return line[:80]
    return fallback if fallback else "Untitled Demo"


def _extract_slug(messages: list) -> str:
    """Extract slug from save_demo tool result (most reliable source)."""
    for msg in messages:
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role == "tool":
            content_str = str(_safe_get(msg, "content", ""))
            if "slug" in content_str:
                try:
                    start = content_str.find("{")
                    end = content_str.rfind("}") + 1
                    if start >= 0 and end > start:
                        data = json.loads(content_str[start:end])
                        slug = data.get("slug", "")
                        if slug:
                            return slug
                except (json.JSONDecodeError, ValueError):
                    pass
    return ""


def _extract_html_path(messages: list) -> str:
    """Extract the final HTML file path from save_demo tool result."""
    for msg in messages:
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role == "tool":
            content_str = str(_safe_get(msg, "content", ""))
            if "html_path" in content_str:
                try:
                    start = content_str.find("{")
                    end = content_str.rfind("}") + 1
                    if start >= 0 and end > start:
                        data = json.loads(content_str[start:end])
                        return data.get("html_path", "")
                except (json.JSONDecodeError, ValueError):
                    pass
    return ""


def _extract_metadata(messages: list) -> dict[str, Any]:
    """Extract demo metadata from save_demo output, enriched with
    verify_interactivity data if save_demo didn't capture it.
    """
    save_demo_meta = None
    for msg in messages:
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role == "tool":
            content_str = str(_safe_get(msg, "content", ""))
            if "local_url" in content_str or "public_url" in content_str:
                try:
                    start = content_str.find("{")
                    end = content_str.rfind("}") + 1
                    if start >= 0 and end > start:
                        save_demo_meta = json.loads(content_str[start:end])
                        break
                except (json.JSONDecodeError, ValueError):
                    pass

    verification_data = None
    for msg in messages:
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role == "tool":
            content_str = str(_safe_get(msg, "content", ""))
            if "score" in content_str and "verified_interactions" in content_str:
                try:
                    start = content_str.find("{")
                    end = content_str.rfind("}") + 1
                    if start >= 0 and end > start:
                        parsed = json.loads(content_str[start:end])
                        if "verified_interactions" in parsed or "mocked_features" in parsed:
                            verification_data = parsed
                            break
                except (json.JSONDecodeError, ValueError):
                    pass

    if save_demo_meta is not None:
        if verification_data and not save_demo_meta.get("mocked_features"):
            save_demo_meta.setdefault("mocked_features", verification_data.get("mocked_features", []))
            save_demo_meta.setdefault("functional_areas", verification_data.get("verified_interactions", []))
            save_demo_meta.setdefault("code_quality_score", verification_data.get("score", 0))
            save_demo_meta.setdefault("verification_issues", verification_data.get("issues", []))
        return save_demo_meta

    title = _extract_title(messages, "")
    slug = _extract_slug(messages)
    html_path = _extract_html_path(messages)
    fallback = {
        "title": title,
        "slug": slug,
        "html_path": html_path,
    }
    if verification_data:
        fallback.setdefault("mocked_features", verification_data.get("mocked_features", []))
        fallback.setdefault("functional_areas", verification_data.get("verified_interactions", []))
        fallback.setdefault("code_quality_score", verification_data.get("score", 0))
        fallback.setdefault("verification_issues", verification_data.get("issues", []))
    return fallback


def _extract_build_step(messages: list) -> str:
    """Track progress from the tool call sequence in the message history.

    Maps tool call patterns to build step names.
    """
    tool_names: list[str] = []
    for msg in messages:
        role = _safe_get(msg, "role") or _safe_get(msg, "type")
        if role in ("ai", "assistant"):
            tool_calls = _safe_get(msg, "tool_calls") or []
            for tc in tool_calls:
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                if name:
                    tool_names.append(name)

    if "save_demo" in tool_names:
        return "final_save"
    if "critique_demo" in tool_names:
        return "critique"
    if "verify_interactivity" in tool_names:
        return "verification"
    if "generate_html" in tool_names:
        # Count how many generate_html calls to determine build step
        count = tool_names.count("generate_html")
        return f"build_step_{count}"
    if "kb_lookup" in tool_names:
        return "kb_lookup"
    if "write_file" in tool_names:
        return "planning"
    return "initializing"


def _make_slug(title: str) -> str:
    """Generate a filesystem slug from a title."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).lower().strip("-")
    if len(slug) > 60:
        slug = slug[:60]
    return f"{slug}-{datetime.now().strftime('%Y%m%d%H%M')}"
