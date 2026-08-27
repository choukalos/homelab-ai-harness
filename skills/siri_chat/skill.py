#!/usr/bin/env python3
"""
siri_chat skill — conversational chat with MCP tool access.

Purpose:
  Enhanced chat that can use web search, knowledge base lookup, and homelab
  status tools via MCP. Designed for Siri/iOS Shortcuts and API consumers
  that need more than plain chat — the model can autonomously call tools
  (search, knowledge, docker status) to provide informed, accurate answers.

Workflow:
  1. Validate inputs (query is required).
  2. Build the tools array (search_web, family_kb_search, family_kb_ask,
     docker_status) in LiteLLM/OpenAI function-calling format.
  3. Call litellm_client.chat_completion with system prompt + tools.
  4. If the model requests tool calls, execute each tool via
     litellm_client.mcp_call (mapped to the correct MCP server).
  5. Feed tool results back and repeat — up to 3 rounds before forcing
     a final answer.
  6. Return {"answer": text, "sources": [...], "model_alias": model}.

Constraints:
  - Max runtime: 120 seconds (hard timeout).
  - Max 3 tool-calling rounds before forcing a final answer.
  - All MCP calls go through LiteLLM — never direct MCP server access.
  - Read-only tools only (no writes, no admin operations).
  - Stateless: no rollback needed.

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
import signal
import threading
import sys
import time
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ARTIFACT_DIR = Path(
    os.environ.get("ARTIFACT_DIR", "/home/chuck/data/media/siri_outputs")
)
MAX_RUNTIME_SECS = int(os.environ.get("SIRI_CHAT_MAX_RUNTIME", "120"))
MAX_TOOL_ROUNDS = int(os.environ.get("SIRI_CHAT_MAX_TOOL_ROUNDS", "3"))
MODEL_ALIAS = os.environ.get("SIRI_CHAT_MODEL_ALIAS", "matrix-coder")

logger = logging.getLogger("skill.siri_chat")

# ---------------------------------------------------------------------------
# Tool-to-server mapping
# ---------------------------------------------------------------------------

# Maps each tool name to the MCP server ID that provides it.
TOOL_SERVER_MAP: dict[str, str] = {
    "search_web": "mcp_search",
    "family_kb_search": "mcp_knowledge",
    "family_kb_ask": "mcp_knowledge",
    "docker_ps": "mcp_homelab_status",
    "system_info": "mcp_homelab_status",
}

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"siri_chat exceeded {MAX_RUNTIME_SECS}s max runtime")


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
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = textwrap.dedent("""\
    You are a helpful AI assistant optimised for voice and mobile delivery.

    Rules:
    - Give SHORT, DIRECT answers (one or two sentences when possible).
    - Use plain language suitable for spoken playback.
    - When you have access to tools (search_web, family_kb_search,
      family_kb_ask, docker_status), USE them to get accurate information
      rather than guessing.
    - Always cite your sources when you use a tool — briefly mention
      where the information came from.
    - If you lack information, say so briefly rather than guessing.
    - If a question requires deep research, suggest using the deep_research
      skill instead.
    - Never expose sensitive credentials, internal IPs, or private paths.
    - For homelab status checks, give a safe, read-only summary.
    - Keep responses under 300 words unless the user explicitly asks for
      a detailed explanation.
""")

# ---------------------------------------------------------------------------
# Tool definitions (OpenAI/LiteLLM function-calling format)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the web for current information. "
                "Use this for facts, news, or anything that might have "
                "changed since your training data."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query string.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "family_kb_search",
            "description": (
                "Search the family knowledge base for stored notes, "
                "memories, and reference material. Use this for personal "
                "facts, family info, or previously saved content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query for the knowledge base.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "family_kb_ask",
            "description": (
                "Ask a natural-language question to the family knowledge base. "
                "Use this for questions that require semantic understanding "
                "of stored content, not just keyword matching."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The natural-language question to ask.",
                    }
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "docker_ps",
            "description": (
                "List all Docker containers with their current status, "
                "image name, exposed ports, and uptime. "
                "Use this when the user asks about service health or infrastructure."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_info",
            "description": (
                "Get system resource usage: CPU, memory, and disk usage. "
                "Use this when the user asks about system health or resources."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# LiteLLM client interaction
# ---------------------------------------------------------------------------


def _extract_tool_calls(response: dict) -> Optional[list[dict]]:
    """
    Extract tool_calls from a LiteLLM chat completion response.
    Returns None if the assistant did not request any tool calls.
    """
    choices = response.get("choices", [])
    if not choices:
        return None
    message = choices[0].get("message", {})
    tool_calls = message.get("tool_calls")
    if tool_calls:
        return tool_calls
    return None


def _extract_assistant_text(response: dict) -> str:
    """Extract the assistant's text content from a LiteLLM response."""
    choices = response.get("choices", [])
    if not choices:
        return ""
    message = choices[0].get("message", {})
    return message.get("content", "") or ""


def _extract_finish_reason(response: dict) -> str:
    """Extract the finish_reason from a LiteLLM response."""
    choices = response.get("choices", [])
    if not choices:
        return "unknown"
    return choices[0].get("finish_reason", "unknown")


def _execute_tool_calls(
    tool_calls: list[dict],
    litellm_client: Any,
    sources: list[str],
) -> list[dict]:
    """
    Execute each tool call requested by the LLM and collect results.
    Returns a list of messages in the format expected by LiteLLM:
    [{"role": "tool", "tool_call_id": "...", "content": "..."}, ...]
    """
    tool_results: list[dict] = []

    for tc in tool_calls:
        call_id = tc.get("id", "")
        func_name = tc.get("function", {}).get("name", "")
        func_args_str = tc.get("function", {}).get("arguments", "{}")

        try:
            func_args = json.loads(func_args_str)
        except json.JSONDecodeError:
            func_args = {}

        server_id = TOOL_SERVER_MAP.get(func_name)
        if not server_id:
            result_text = f"Unknown tool: {func_name}"
            logger.warning("Unknown tool requested: %s", func_name)
        else:
            try:
                result = litellm_client.mcp_call(
                    tool_name=func_name,
                    arguments=func_args,
                    server_id=server_id,
                )
                result_text = _format_tool_result(func_name, result)
                # Track sources
                if func_name in ("search_web", "family_kb_search"):
                    result_text_sources = _extract_urls_from_result(result)
                    sources.extend(result_text_sources)
            except Exception as exc:
                result_text = f"Tool {func_name} failed: {exc}"
                logger.error("Tool %s failed: %s", func_name, exc)

        tool_results.append({
            "role": "tool",
            "tool_call_id": call_id,
            "content": result_text,
        })

    return tool_results


def _format_tool_result(tool_name: str, result: dict) -> str:
    """Format a tool result into a readable text string."""
    if result.get("is_error"):
        return json.dumps(result.get("output", []), ensure_ascii=False)

    output = result.get("output", [])
    if not output:
        # Check for structured result
        if "result" in result:
            return json.dumps(result["result"], ensure_ascii=False)
        return "No output from tool."

    # Collect text content from the output list
    parts: list[str] = []
    for item in output:
        if isinstance(item, dict):
            if item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif item.get("_structured"):
                parts.append(json.dumps(item["_structured"], ensure_ascii=False))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        elif isinstance(item, str):
            parts.append(item)

    return "\n".join(parts) if parts else "No readable output."


def _extract_urls_from_result(result: dict) -> list[str]:
    """Extract source URLs from a tool result for the sources list."""
    sources: list[str] = []
    output = result.get("output", [])
    for item in output:
        if isinstance(item, dict):
            if item.get("type") == "text":
                text = item.get("text", "")
                # Try to extract URLs from the text
                if "url" in text.lower() or "http" in text.lower():
                    sources.append(text[:200])
            elif item.get("_structured"):
                sc = item["_structured"]
                results = sc.get("results", sc.get("matches", []))
                if isinstance(results, list):
                    for r in results:
                        if isinstance(r, dict) and r.get("url"):
                            sources.append(r["url"])
                        elif isinstance(r, dict) and r.get("source"):
                            sources.append(r["source"])
    # Also check the result key
    if "result" in result:
        sc = result["result"]
        results = sc.get("results", sc.get("matches", []))
        if isinstance(results, list):
            for r in results:
                if isinstance(r, dict) and r.get("url"):
                    url = r["url"]
                    if url not in sources:
                        sources.append(url)
    return list(dict.fromkeys(sources))  # deduplicate while preserving order


# ---------------------------------------------------------------------------
# Main chat loop
# ---------------------------------------------------------------------------


def _chat_with_tools(
    messages: list[dict],
    model: str,
    litellm_client: Any,
    sources: list[str],
) -> str:
    """
    Chat with the LLM, handling tool calls in a loop.
    Max MAX_TOOL_ROUNDS rounds of tool calls before forcing a final answer.
    """
    for round_num in range(MAX_TOOL_ROUNDS + 1):
        try:
            response = litellm_client.chat_completion(
                model=model,
                messages=messages,
                tools=TOOLS,
                temperature=0.3,
                max_tokens=1024,
            )
        except Exception as exc:
            raise RuntimeError(f"LiteLLM chat_completion failed: {exc}") from exc

        finish_reason = _extract_finish_reason(response)
        tool_calls = _extract_tool_calls(response)

        if not tool_calls:
            # Final answer from the model
            return _extract_assistant_text(response)

        # Model requested tool calls — execute them
        if round_num >= MAX_TOOL_ROUNDS:
            # Forced final answer — don't call more tools
            messages.append({
                "role": "assistant",
                "content": _extract_assistant_text(response) or "Let me give you my best answer now.",
            })
            messages.append({
                "role": "system",
                "content": (
                    "You have reached the maximum number of tool calls. "
                    "Please give your final answer now based on the information "
                    "you have gathered."
                ),
            })
            continue

        # Add the assistant's message with tool_calls to conversation
        messages.append({
            "role": "assistant",
            "content": _extract_assistant_text(response) or None,
            "tool_calls": tool_calls,
        })

        # Execute the tools
        tool_results = _execute_tool_calls(tool_calls, litellm_client, sources)
        messages.extend(tool_results)

        logger.info(
            "Tool round %d complete (%d tool calls executed)", round_num + 1,
            len(tool_calls)
        )

    # Should not reach here, but safety net
    return "I've used my available tools. Based on what I found, let me share my answer."


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def _memory_block(user_id: Optional[str], query: str) -> str:
    """Build the ``<long_term_memory>`` block for the siri_chat system prompt.

    Phase 4 — same render path as ``_chat_direct`` (``memory.interface.
    render_context``), so both call sites stay identical. The skill is
    loaded standalone (importlib, stdlib-only by design), so the memory
    package is imported lazily and any failure degrades to no block —
    chat must never break because of memory (non-negotiable #7).

    ``user_id`` comes from the Job (Phase 3 identity); 'service'/'unknown'/
    None resolve to no retrieval inside the interface.
    """
    if not user_id or not query:
        return ""
    try:
        from memory import interface  # lazy: keep the skill importable standalone
        block = interface.render_context(user_id, query)
        return block or ""
    except Exception as exc:  # noqa: BLE001 — degrade, never break chat
        logger.warning("memory context unavailable for siri_chat: %s", exc)
        return ""


def run(
    params: dict[str, Any],
    job,
    litellm_client: Any,
) -> dict[str, Any]:
    """
    Execute the siri_chat skill.

    Args:
        params: Skill parameters.
            - query (str, required): The user's question or request.
            - context (str, optional): Previous conversation context.
            - model (str, optional): Model alias (default: matrix-coder).
        job: The runner Job object for logging.
        litellm_client: Sync wrapper around LiteLLMClient (chat_completion,
                        mcp_call available).

    Returns:
        Dict with 'answer', 'sources', and 'model_alias'.
    """
    # Validate inputs
    query = params.get("query")
    if not query or not query.strip():
        result = {"error": "Missing required 'query' parameter"}
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing query")
        return result

    query = query.strip()
    context = params.get("context", "")
    model = params.get("model", MODEL_ALIAS)

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing siri_chat: query='{query[:100]}...'")
        job.add_log(f"Model: {model}")
        job.add_log(f"Max tool rounds: {MAX_TOOL_ROUNDS}")

    # Install timeout
    _install_timeout()

    try:
        # Build conversation messages
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Long-term memory (Phase 4): inject the memory block into the
        # system prompt. Identity comes from the Job (user_id/run_id);
        # the per-request switch (ChatRequest.memory) is carried as
        # job.memory_enabled. Non-fatal: on error the block is empty.
        mem_block = ""
        if getattr(job, "memory_enabled", True):
            mem_user = getattr(job, "user_id", None)
            t0 = time.time()
            mem_block = _memory_block(mem_user, query)
            mem_ms = int((time.time() - t0) * 1000)
            if hasattr(job, "add_log"):
                job.add_log(
                    f"Memory: user_id={mem_user or 'unknown'} "
                    f"block_chars={len(mem_block)} latency_ms={mem_ms}"
                )
        if mem_block:
            messages[0] = {
                "role": "system",
                "content": SYSTEM_PROMPT + "\n\n" + mem_block,
            }

        if context:
            messages.append({"role": "user", "content": context})
            messages.append(
                {"role": "assistant", "content": "Understood. I have this context."}
            )

        messages.append({"role": "user", "content": query})

        # Sources tracking
        sources: list[str] = []

        # Run the chat loop with tool support
        answer = _chat_with_tools(messages, model, litellm_client, sources)

        if hasattr(job, "add_log"):
            job.add_log(f"Response generated ({len(answer)} chars)")
            if sources:
                job.add_log(f"Sources: {len(sources)} found")

        # Phase 5 writeback — after a SUCCESSFUL response, extract + store
        # durable facts from this turn. Non-fatal (a writeback failure never
        # breaks the answer), budgeted (MEMORY_WRITEBACK_TIMEOUT_MS), policy-
        # filtered. Identity comes from the Job (Phase 3); the per-request
        # switch (ChatRequest.memory) is carried as job.memory_enabled.
        if getattr(job, "memory_enabled", True):
            try:
                from memory import interface as _mem_iface  # lazy (standalone import)
                _wb_ids = _mem_iface.learn_from_turn(
                    getattr(job, "user_id", None) or "unknown",
                    [
                        {"role": "user", "content": query},
                        {"role": "assistant", "content": answer},
                    ],
                    source="chat",
                    run_id=getattr(job, "run_id", None),
                )
                if hasattr(job, "add_log"):
                    job.add_log(f"Memory writeback: stored={len(_wb_ids)}")
            except Exception as exc:  # noqa: BLE001 — never break chat
                if hasattr(job, "add_log"):
                    job.add_log(f"Memory writeback failed (non-fatal): {exc}")

        return {
            "answer": answer,
            "sources": sources,
            "model_alias": model,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "answer": (
                "Sorry, I couldn't complete that in time. "
                "Please try a shorter question or use the deep_research skill "
                "for detailed topics."
            ),
            "error": msg,
            "sources": [],
            "model_alias": model,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")
        return {
            "answer": (
                "I couldn't reach my backend right now. "
                "Please try again in a moment."
            ),
            "error": msg,
            "sources": [],
            "model_alias": model,
        }

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# CLI entrypoint (for standalone testing)
# ---------------------------------------------------------------------------


class _MockJob:
    """Dummy job object for standalone testing."""

    def __init__(self):
        self.logs: list[str] = []

    def add_log(self, msg: str):
        self.logs.append(msg)
        print(f"  [log] {msg}")


class _MockLiteLLMClient:
    """Mock LiteLLM client for dry-run testing."""

    def chat_completion(self, model, messages, **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": f"[Mock response for model={model}] "
                                   f"Messages: {len(messages)}",
                    },
                    "finish_reason": "stop",
                }
            ]
        }

    def mcp_call(self, tool_name, arguments, server_id=None, **kwargs):
        return {
            "output": [
                {
                    "type": "text",
                    "text": f"[Mock MCP result: {tool_name}({arguments})]",
                }
            ],
            "is_error": False,
        }


def main():
    """Standalone test entrypoint.

    Usage:
        python skill.py --query "What's the weather?" [--context "..."] [--model matrix-coder]
        python skill.py --query "Status check" --dry-run
    """
    import argparse

    parser = argparse.ArgumentParser(description="siri_chat standalone test")
    parser.add_argument("--query", required=True, help="Question to ask")
    parser.add_argument("--context", default="", help="Optional conversation context")
    parser.add_argument("--model", default=MODEL_ALIAS, help="Model alias")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print parameters without calling the model"
    )
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN")
        print(f"  Query: {args.query}")
        print(f"  Context: {args.context}")
        print(f"  Model: {args.model}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Max tool rounds: {MAX_TOOL_ROUNDS}")
        print(f"  Tools: {[t['function']['name'] for t in TOOLS]}")
        return

    params = {
        "query": args.query,
        "context": args.context,
        "model": args.model,
    }

    print(f"\n--- siri_chat ---")
    print(f"  Query: {args.query}")
    print(f"  Model: {args.model}")
    print(f"  Max tool rounds: {MAX_TOOL_ROUNDS}")

    # Use mock client for standalone testing (no LiteLLM server needed)
    litellm_client = _MockLiteLLMClient()
    result = run(params, _MockJob(), litellm_client)

    print(f"\n--- siri_chat response ---")
    print(f"  Answer: {result.get('answer', 'No response')}")
    print(f"  Model: {result.get('model_alias')}")
    if result.get("sources"):
        print(f"  Sources: {len(result['sources'])} found")
        for s in result["sources"]:
            print(f"    - {s}")
    if result.get("error"):
        print(f"  Error: {result['error']}")


if __name__ == "__main__":
    main()
