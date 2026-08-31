#!/usr/bin/env python3
"""
demo_workflow skill — generate an interactive HTML demo from a prompt.

Purpose:
  Takes a prompt describing a demo or interactive flow, uses the LLM to
  generate a self-contained HTML page, saves it to the demos directory,
  and returns the result.

Workflow:
  1. Validate the prompt parameter.
  2. Call LiteLLM to generate a complete HTML page from the prompt.
  3. Save the HTML to the demos artifact directory.
  4. Return title, slug, status, and html_path.

Constraints:
  - Max runtime: 600 seconds (10 minutes).
  - Uses LiteLLM directly (not a separate AI Harness).
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
import urllib.request
import urllib.error

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ARTIFACT_DIR = Path(
    os.environ.get("DEMO_WORKFLOW_ARTIFACT_DIR", "/home/chuck/data/media/presentations")
)
MAX_RUNTIME_SECS = int(os.environ.get("DEMO_WORKFLOW_MAX_RUNTIME", "600"))

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://litellm-proxy:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("DEMO_WORKFLOW_MODEL_ALIAS", "matrix-coder")

logger = logging.getLogger("skill.demo_workflow")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"demo_workflow exceeded {MAX_RUNTIME_SECS}s max runtime")


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
# LiteLLM client
# ---------------------------------------------------------------------------


def _llm_chat_completion(
    model: str,
    messages: list[dict[str, str]],
    **kwargs: Any,
) -> dict[str, Any]:
    """Call LiteLLM /v1/chat/completions for LLM text generation."""
    payload: dict[str, Any] = {"model": model, "messages": messages}
    payload.update(kwargs)

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
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"LiteLLM HTTP error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach LiteLLM at {LITELLM_BASE_URL}: {exc.reason}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from LiteLLM: {exc}") from exc


# ---------------------------------------------------------------------------
# Demo generation
# ---------------------------------------------------------------------------


def _generate_demo_html(prompt: str) -> tuple[str, str]:
    """
    Use the LLM to generate a self-contained interactive HTML demo page.

    Returns (title, html_content).
    """
    system_prompt = textwrap.dedent("""\
        You are an expert frontend developer. Generate a COMPLETE, SELF-CONTAINED
        single-page HTML demo. The HTML must be fully functional with inline CSS
        and JavaScript — no external dependencies, no CDN links, no separate files.

        Rules:
        - Output ONLY raw HTML (no markdown, no code fences, no explanation).
        - Use modern CSS (flexbox/grid, custom properties, smooth transitions).
        - Include interactive elements (forms, buttons, toggles, animations).
        - Make it mobile-responsive with a viewport meta tag.
        - Use a clean, professional design with good typography.
        - The page should be a complete demo that showcases the requested topic.
        - Include a header with the title and a brief description.
    """)

    user_prompt = textwrap.dedent(f"""\
        Create an interactive demo page for:

        {prompt}

        Make it visually impressive and fully functional. Return ONLY the HTML.
    """)

    resp = _llm_chat_completion(
        MODEL_ALIAS,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=16000,
    )

    msg = resp.get("choices", [{}])[0].get("message", {}) or {}
    content = msg.get("content") or ""
    # Reasoning models (e.g. matrix-coder) may return content=None and put the
    # output in reasoning_content. Fall back to it, but only as a last resort.
    if not content.strip():
        content = msg.get("reasoning_content") or ""
    content = content.strip()

    if not content:
        raise RuntimeError(
            "LLM returned empty content (finish_reason="
            f"{resp.get('choices', [{}])[0].get('finish_reason')}). "
            "The reasoning model likely exhausted its token budget on "
            "reasoning_content. Try a simpler prompt or a non-reasoning model."
        )

    # Strip markdown code fences if present
    if content.startswith("```"):
        lines = content.split("\n")
        # Remove first line (```html or ```)
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        # Remove last line if it's ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    # Extract title from HTML if possible
    title = _extract_title(content, prompt)

    return title, content


def _extract_title(html: str, fallback: str) -> str:
    """Extract the <title> from HTML, or generate a fallback."""
    import re
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: first 60 chars of prompt, cleaned up
    return fallback[:60].strip()


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Convert a string to a filename-safe slug."""
    import re
    slug = re.sub(r"[^a-zA-Z0-9\-]+", "-", value).strip("-").lower()
    return slug[:60]


def _save_demo_html(title: str, html_content: str, prompt: str) -> Optional[str]:
    """
    Save the demo HTML to the artifact directory.
    Returns the file path or None on failure.
    """
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        slug = _slugify(title)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"demo_{ts}_{slug}.html"
        path = ARTIFACT_DIR / filename

        path.write_text(html_content, encoding="utf-8")
        logger.info("Demo HTML written: %s", path)
        return str(path)
    except OSError as exc:
        logger.warning("Could not write demo HTML: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job) -> dict[str, Any]:
    """
    Execute the demo_workflow skill.

    Args:
        params: Skill parameters (prompt).
        job: The runner Job object for logging.

    Returns:
        Dict with title, slug, status, html_path, prompt.
    """
    # Validate inputs
    prompt = params.get("prompt")
    if not prompt or not str(prompt).strip():
        result = {"error": "Missing required 'prompt' parameter"}
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing prompt")
        return result

    prompt = str(prompt).strip()

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing demo_workflow: prompt='{prompt[:100]}...'")
        job.add_log(f"LiteLLM URL: {LITELLM_BASE_URL}")
        job.add_log(f"Model: {MODEL_ALIAS}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")

    # Install timeout
    _install_timeout()

    try:
        # Generate the demo via LLM
        if hasattr(job, "add_log"):
            job.add_log("Generating demo HTML via LiteLLM...")

        title, html_content = _generate_demo_html(prompt)

        if hasattr(job, "add_log"):
            job.add_log(f"LLM responded: title='{title}', html size={len(html_content)} chars")

        # Save the HTML artifact
        html_path = _save_demo_html(title, html_content, prompt)

        if hasattr(job, "add_log"):
            if html_path:
                job.add_log(f"Artifact saved: {html_path}")

        slug = _slugify(title)

        result: dict[str, Any] = {
            "title": title,
            "slug": slug,
            "status": "completed",
            "html_path": html_path or "",
            "prompt": prompt,
        }

        if hasattr(job, "add_log"):
            job.add_log("demo_workflow completed successfully")

        return result

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "error": msg,
            "prompt": prompt,
            "status": "timeout",
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")
        return {
            "error": msg,
            "prompt": prompt,
            "status": "error",
        }

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)
        return {
            "error": msg,
            "prompt": prompt,
            "status": "error",
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

    def add_log(self, msg: str) -> None:
        self.logs.append(msg)
        print(f"  [LOG] {msg}")


def main():
    """Standalone test entrypoint.

    Usage:
        python skill.py --prompt "Build a solar system simulator"
        python skill.py --prompt "Test" --dry-run
        python skill.py --prompt "Test" --litellm-url http://localhost:4000
    """
    global LITELLM_BASE_URL, MODEL_ALIAS
    import argparse

    parser = argparse.ArgumentParser(description="demo_workflow standalone test")
    parser.add_argument("--prompt", required=True, help="Demo topic/description")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print parameters without calling the LLM"
    )
    parser.add_argument(
        "--litellm-url",
        default=LITELLM_BASE_URL,
        help=f"LiteLLM base URL (default: {LITELLM_BASE_URL})",
    )
    parser.add_argument(
        "--model",
        default=MODEL_ALIAS,
        help=f"Model alias (default: {MODEL_ALIAS})",
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  Prompt: {args.prompt}")
        print(f"  LiteLLM URL: {args.litellm_url}")
        print(f"  Model: {args.model}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Artifact dir: {ARTIFACT_DIR}")
        print()
        print("  Expected output: {title, slug, status, html_path}")
        return

    LITELLM_BASE_URL = args.litellm_url
    MODEL_ALIAS = args.model
    params = {"prompt": args.prompt}
    result = run(params, _MockJob())

    print(f"\n--- demo_workflow response ---")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()