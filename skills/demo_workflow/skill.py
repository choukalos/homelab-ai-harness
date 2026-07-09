#!/usr/bin/env python3
"""
demo_workflow skill — thin wrapper for the AI Harness demo endpoint.

Purpose:
  Takes a prompt, sends it to the AI Harness demo runner, and returns
  the harness response (thread_id, title, slug, status, html_path).
  The Harness handles all deep-agent work (research, build, verify).

Workflow:
  1. Validate the prompt parameter.
  2. POST to HARNESS_URL/demos/run with {"prompt": prompt}.
  3. Return the harness response as-is.
  4. Save metadata to the artifact path.

Constraints:
  - Max runtime: 600 seconds (10 minutes).
  - No MCP tools — direct HTTP call to the AI Harness.
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
    os.environ.get("DEMO_WORKFLOW_ARTIFACT_DIR", "/home/chuck/data/media/presentations")
)
MAX_RUNTIME_SECS = int(os.environ.get("DEMO_WORKFLOW_MAX_RUNTIME", "600"))
HARNESS_URL = os.environ.get("DEMO_WORKFLOW_HARNESS_URL", "http://skill-runner:8091")

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
# Harness HTTP call
# ---------------------------------------------------------------------------


def _call_harness(prompt: str) -> dict[str, Any]:
    """
    POST to the AI Harness demo endpoint with the prompt payload.

    Returns the harness response dict.
    """
    import urllib.request
    import urllib.error

    payload = {"prompt": prompt}
    data = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    req = urllib.request.Request(
        f"{HARNESS_URL}/demos/run",
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=MAX_RUNTIME_SECS) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        raise RuntimeError(f"Harness HTTP error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Cannot reach AI Harness at {HARNESS_URL}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from AI Harness: {exc}") from exc


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Convert a string to a filename-safe slug."""
    return "".join(c if c.isalnum() or c == "-" else "-" for c in value[:60]).strip("-")


def _write_artifact(response: dict[str, Any], prompt: str) -> Optional[str]:
    """
    Save the demo metadata as a JSON artifact file.
    Returns the file path or None on failure.
    """
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        slug = _slugify(prompt)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"demo_{ts}_{slug}.json"
        path = ARTIFACT_DIR / filename

        artifact = {
            "prompt": prompt,
            "timestamp": ts,
            "harness_response": response,
        }
        path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
        logger.info("Artifact written: %s", path)
        return str(path)
    except OSError as exc:
        logger.warning("Could not write artifact: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job) -> dict[str, Any]:
    """
    Execute the demo_workflow skill.

    Thin wrapper: validates prompt, POSTs to AI Harness /demos/run,
    returns the harness response.

    Args:
        params: Skill parameters (prompt).
        job: The runner Job object for logging.

    Returns:
        Dict with harness response fields plus artifact_path.
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
        job.add_log(f"Harness URL: {HARNESS_URL}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")

    # Install timeout
    _install_timeout()

    try:
        # Call the AI Harness demo endpoint
        if hasattr(job, "add_log"):
            job.add_log("Calling AI Harness /demos/run...")

        response = _call_harness(prompt)

        if hasattr(job, "add_log"):
            job.add_log(f"Harness responded: {json.dumps(response)[:200]}")

        # Save metadata artifact
        artifact_path = _write_artifact(response, prompt)

        if hasattr(job, "add_log"):
            if artifact_path:
                job.add_log(f"Artifact saved: {artifact_path}")

        # Build result from harness response
        result: dict[str, Any] = dict(response)
        result["artifact_path"] = artifact_path
        result["prompt"] = prompt

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
        python skill.py --prompt "Test" --harness-url http://localhost:8090
    """
    import argparse

    parser = argparse.ArgumentParser(description="demo_workflow standalone test")
    parser.add_argument("--prompt", required=True, help="Demo topic/description")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print parameters without calling the harness"
    )
    parser.add_argument(
        "--harness-url", default=HARNESS_URL, help=f"AI Harness URL (default: {HARNESS_URL})"
    )
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  Prompt: {args.prompt}")
        print(f"  Harness URL: {args.harness_url}")
        print(f"  Endpoint: {args.harness_url}/demos/run")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Artifact dir: {ARTIFACT_DIR}")
        print()
        print("  Payload: {\"prompt\": \"...\"}")
        print("  Expected response: {thread_id, title, slug, status, html_path}")
        return

    # Override harness URL for CLI usage
    global HARNESS_URL
    HARNESS_URL = args.harness_url

    params = {"prompt": args.prompt}
    result = run(params, _MockJob())

    print(f"\n--- demo_workflow response ---")
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
