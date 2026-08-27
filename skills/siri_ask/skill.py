#!/usr/bin/env python3
"""
siri_ask skill — short mobile answers, safe status lookups.

Purpose:
  Quick Q&A for Siri/iOS Shortcuts. Returns concise answers suitable for
  spoken delivery or small screens. No heavy research, no admin writes,
  no MCP tool access.

Constraints:
  - Max 30 seconds total runtime (hard timeout).
  - Max 500 output tokens (response truncation).
  - Model chat only — no MCP tools, no filesystem access, no database writes.
  - Stateless: no rollback needed.

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
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
    os.environ.get("ARTIFACT_DIR", "/home/chuck/data/media/siri_outputs")
)
MAX_RUNTIME_SECS = int(os.environ.get("SIRI_ASK_MAX_RUNTIME", "30"))
MAX_OUTPUT_TOKENS = int(os.environ.get("SIRI_ASK_MAX_TOKENS", "500"))
MODEL_ALIAS = os.environ.get("SIRI_ASK_MODEL_ALIAS", "matrix-coder")

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")

logger = logging.getLogger("skill.siri_ask")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"siri_ask exceeded {MAX_RUNTIME_SECS}s max runtime")


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
    You are a concise AI assistant optimized for voice and mobile delivery.

    Rules:
    - Give SHORT, DIRECT answers (one or two sentences when possible).
    - Maximum ~500 tokens. If you would exceed this, summarize instead.
    - NO broad tool usage, NO admin writes, NO heavy research.
    - If you lack information, say so briefly rather than guessing.
    - Use plain language suitable for spoken playback.
    - If the user asks for a status check (homelab, services, etc.),
      give a safe, read-only summary based on what you know.
    - Never expose sensitive credentials, internal IPs, or private paths.
    - If a question requires deep research, suggest using the deep_research skill instead.
""")


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------


def _build_messages(params: dict[str, Any]) -> list[dict[str, str]]:
    """Build the conversation messages from skill parameters."""
    query = params.get("query", "")
    context = params.get("context", "")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if context:
        messages.append({"role": "user", "content": context})
        messages.append({"role": "assistant", "content": "Understood. I have this context."})

    messages.append({"role": "user", "content": query})
    return messages


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """
    Rough token-limit truncation. Uses word count as proxy:
    ~1.3 words per token is a common heuristic for English.
    """
    words = text.split()
    max_words = int(max_tokens * 1.3)
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " [truncated]"


def _memory_block(job, query: str) -> str:
    """Build the ``<long_term_memory>`` block for siri_ask (Phase 7).

    Same render path as ``siri_chat`` / ``_chat_direct`` (via
    ``memory.jobctx.retrieve``), so all call sites stay identical.
    Identity comes from the Job; the per-request switch is
    ``job.memory_enabled``. Non-fatal: any failure degrades to "" so the
    answer is never broken by memory (skills are loaded standalone via
    importlib, so the memory package is imported lazily).
    """
    try:
        from memory import jobctx  # lazy: keep the skill importable standalone
        return jobctx.retrieve(job, query)
    except Exception as exc:  # noqa: BLE001 — never break the skill
        if hasattr(job, "add_log"):
            job.add_log(f"Memory context unavailable (non-fatal): {exc}")
        return ""


def _writeback_turn(job, query: str, answer: str) -> None:
    """Write back a successful siri_ask turn (Phase 7).

    Non-fatal: a writeback failure never breaks the answer. Identity and
    the per-request switch come from the Job.
    """
    try:
        from memory import jobctx  # lazy
        jobctx.writeback_turn(
            job,
            [
                {"role": "user", "content": query},
                {"role": "assistant", "content": answer},
            ],
            source="chat",
        )
    except Exception as exc:  # noqa: BLE001 — never break the skill
        if hasattr(job, "add_log"):
            job.add_log(f"Memory writeback failed (non-fatal): {exc}")


def _call_litellm(messages: list[dict[str, str]]) -> str:
    """
    Call LiteLLM with the model alias. Uses the OpenAI-compatible
    chat completions endpoint that LiteLLM exposes.

    Returns the assistant's text response.
    """
    import urllib.request
    import urllib.error

    payload = {
        "model": MODEL_ALIAS,
        "messages": messages,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0.3,
        "stream": False,
    }
    data = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if LITELLM_API_KEY:
        headers["Authorization"] = f"Bearer {LITELLM_API_KEY}"

    req = urllib.request.Request(
        f"{LITELLM_BASE_URL}/v1/chat/completions",
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=MAX_RUNTIME_SECS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            choices = body.get("choices", [])
            if not choices:
                return "No response generated."
            return choices[0].get("message", {}).get("content", "No content in response.")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"LiteLLM HTTP error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach LiteLLM at {LITELLM_BASE_URL}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from LiteLLM: {exc}") from exc


def _write_artifact(response: str, params: dict[str, Any]) -> Optional[str]:
    """
    Optionally write a log artifact for the interaction.
    Returns the artifact path or None if writing was skipped/failed.
    """
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() or c == "-" else "-" for c in params.get("query", "query")[:50]).strip("-")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"siri_output_{ts}_{slug}.txt"
        path = ARTIFACT_DIR / filename
        content = textwrap.dedent(f"""\
            # Siri Ask Log
            Query: {params.get("query", "")}
            Context: {params.get("context", "none")}
            Model: {MODEL_ALIAS}
            Timestamp: {ts}
            ---
            {response}
        """)
        path.write_text(content, encoding="utf-8")
        return str(path)
    except OSError as exc:
        logger.warning("Could not write artifact: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job) -> dict[str, Any]:
    """
    Execute the siri_ask skill.

    Args:
        params: Skill parameters (query, context).
        job: The runner Job object for logging.

    Returns:
        Dict with 'answer', 'artifact_path', and 'model_alias'.
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

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing siri_ask: query='{query[:100]}...'")
        job.add_log(f"Model alias: {MODEL_ALIAS}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s, max tokens: {MAX_OUTPUT_TOKENS}")

    # Install timeout
    _install_timeout()

    try:
        messages = _build_messages({"query": query, "context": context})

        # Phase 7 — memory retrieval: inject the <long_term_memory> block
        # into the system prompt so the answer can use the caller's
        # durable facts. Identity comes from the Job (user_id/run_id);
        # gated by job.memory_enabled; non-fatal (empty block on error).
        mem_block = _memory_block(job, query)
        if mem_block and messages and messages[0].get("role") == "system":
            messages[0] = {
                "role": "system",
                "content": messages[0]["content"] + "\n\n" + mem_block,
            }

        response = _call_litellm(messages)
        response = _truncate_to_tokens(response, MAX_OUTPUT_TOKENS)

        # Write artifact log
        artifact_path = _write_artifact(response, params)

        if hasattr(job, "add_log"):
            job.add_log(f"Response generated ({len(response)} chars)")
            if artifact_path:
                job.add_log(f"Artifact logged: {artifact_path}")

        # Phase 7 — memory writeback: after a SUCCESSFUL answer, extract
        # + store durable facts from this turn. Non-fatal, budgeted,
        # policy-filtered; identity from the Job.
        _writeback_turn(job, query, response)

        return {
            "answer": response,
            "artifact_path": artifact_path,
            "model_alias": MODEL_ALIAS,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "answer": "Sorry, I couldn't complete that in time. Please try a shorter question or use the deep_research skill for detailed topics.",
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")
        return {
            "answer": "I couldn't reach my backend right now. Please try again in a moment.",
            "error": msg,
            "model_alias": MODEL_ALIAS,
        }

    finally:
        _cancel_timeout()


# ---------------------------------------------------------------------------
# CLI entrypoint (for standalone testing)
# ---------------------------------------------------------------------------

class _MockJob:
    """Dummy job object for standalone testing."""
    def __init__(self):
        self.logs = []
    def add_log(self, msg):
        self.logs.append(msg)


def main():
    """Standalone test entrypoint.

    Usage:
        python skill.py --query "What's the weather?" [--context "Previous conversation"]
        python skill.py --query "Status check" --dry-run
    """
    import argparse

    parser = argparse.ArgumentParser(description="siri_ask standalone test")
    parser.add_argument("--query", required=True, help="Question to ask")
    parser.add_argument("--context", default="", help="Optional conversation context")
    parser.add_argument("--dry-run", action="store_true", help="Print parameters without calling the model")
    parser.add_argument("--base-url", default=LITELLM_BASE_URL, help="LiteLLM base URL")
    parser.add_argument("--api-key", default=LITELLM_API_KEY, help="LiteLLM API key")
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN")
        print(f"  Query: {args.query}")
        print(f"  Context: {args.context}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Max tokens: {MAX_OUTPUT_TOKENS}")
        return

    # Override env vars for CLI usage
    if args.base_url != LITELLM_BASE_URL:
        globals()["LITELLM_BASE_URL"] = args.base_url
    if args.api_key:
        globals()["LITELLM_API_KEY"] = args.api_key

    params = {"query": args.query, "context": args.context}
    result = run(params, _MockJob())

    print(f"\n--- siri_ask response ---")
    print(result.get("answer", "No response"))
    if result.get("artifact_path"):
        print(f"Artifact: {result['artifact_path']}")
    if result.get("error"):
        print(f"Error: {result['error']}")


if __name__ == "__main__":
    main()
