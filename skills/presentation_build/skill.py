#!/usr/bin/env python3
"""
presentation_build skill — AI-powered presentation generation via Presenton.

Purpose:
  Generate slide deck presentations from a topic or existing content using
  the Presenton engine. The skill generates an outline via the LLM, submits
  it to Presenton for slide generation, downloads the exported file, and saves
  it as an artifact.

Workflow:
  1. Validate inputs (topic, slide_count, style, content_source).
  2. If content_source is provided, read existing content; otherwise generate
     a presentation outline via the model LLM.
  3. Submit the outline to Presenton's async generation API (/generate-async).
  4. Poll Presenton until the generation completes.
  5. Download the exported presentation file (pptx by default).
  6. Save the artifact to /home/chuck/data/media/presentations/.
  7. Return summary, presentation metadata, and artifact path.

Constraints:
  - Max runtime: 300 seconds (5 minutes).
  - Presenton UI remains LAN-only — this skill is the ONLY remote path.
  - Remote access is through the skill runner API, NOT direct Presenton exposure.
  - Read-only from the homelab perspective: no container changes, no config edits.
  - Artifacts saved to /home/chuck/data/media/presentations/

See skill.yml for the full manifest and README.md for usage.
"""

import json
import logging
import os
import re
import signal
import sys
import textwrap
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ARTIFACT_DIR = Path(
    os.environ.get("PRESENTATION_BUILD_ARTIFACT_DIR", "/home/chuck/data/media/presentations")
)
MAX_RUNTIME_SECS = int(os.environ.get("PRESENTATION_BUILD_MAX_RUNTIME", "300"))

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("PRESENTATION_BUILD_MODEL_ALIAS", "local/qwen-coder")

# Presenton endpoint (set by skill runner or environment)
# Default: Docker internal network (presenton:80). Override with PRESENTON_URL env var.
PRESENTON_URL = os.environ.get("PRESENTON_URL", "http://presenton:80")
PRESENTON_USERNAME = os.environ.get("PRESENTON_AUTH_USERNAME", "presenton")
PRESENTON_PASSWORD = os.environ.get("PRESENTON_AUTH_PASSWORD")
PRESENTON_GENERATION_TIMEOUT = float(
    os.environ.get("PRESENTON_GENERATION_TIMEOUT", "240")
)  # seconds for Presenton polling

# Mapping from skill "style" to Presenton template names
STYLE_TO_TEMPLATE = {
    "modern": "general",
    "minimal": "general",
    "bold": "dark",
    "elegant": "creative",
    "academic": "academic",
    "creative": "creative",
    "dark": "dark",
}

logger = logging.getLogger("skill.presentation_build")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"presentation_build exceeded {MAX_RUNTIME_SECS}s max runtime")


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
# HTTP helpers (stdlib only, no external deps)
# ---------------------------------------------------------------------------


def _http_post(url: str, payload: dict, headers: dict = None, timeout: int = 60) -> Optional[tuple[int, dict]]:
    """
    Generic HTTP POST. Returns (status_code, parsed_json) or (status_code, {}) on error.
    Uses HTTP Basic auth if credentials are in headers.
    """
    import urllib.request
    import urllib.error

    data = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return (resp.status, body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else "{}"
        try:
            body_json = json.loads(body)
        except json.JSONDecodeError:
            body_json = {"error": body}
        return (exc.code, body_json)
    except urllib.error.URLError as exc:
        logger.warning("URL error calling %s: %s", url, exc)
        return (0, {"error": str(exc)})
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON from %s: %s", url, exc)
        return (0, {"error": str(exc)})
    except TimeoutError:
        raise
    except Exception as exc:
        logger.warning("Unexpected error calling %s: %s", url, exc)
        return (0, {"error": str(exc)})


def _http_get(url: str, headers: dict = None, timeout: int = 60) -> Optional[tuple[int, dict]]:
    """Generic HTTP GET. Returns (status_code, parsed_json)."""
    import urllib.request
    import urllib.error

    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, headers=req_headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return (resp.status, body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else "{}"
        try:
            body_json = json.loads(body)
        except json.JSONDecodeError:
            body_json = {"error": body}
        return (exc.code, body_json)
    except urllib.error.URLError as exc:
        logger.warning("URL error calling %s: %s", url, exc)
        return (0, {"error": str(exc)})
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON from %s: %s", url, exc)
        return (0, {"error": str(exc)})
    except TimeoutError:
        raise
    except Exception as exc:
        logger.warning("Unexpected error calling %s: %s", url, exc)
        return (0, {"error": str(exc)})


def _http_get_binary(url: str, headers: dict = None, timeout: int = 60) -> Optional[tuple[int, bytes]]:
    """Generic HTTP GET returning binary content. Returns (status_code, bytes_data)."""
    import urllib.request
    import urllib.error

    req_headers = {"Accept": "*/*"}
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, headers=req_headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (resp.status, resp.read())
    except urllib.error.HTTPError as exc:
        return (exc.code, b"")
    except urllib.error.URLError as exc:
        logger.warning("URL error calling %s: %s", url, exc)
        return (0, b"")
    except TimeoutError:
        raise
    except Exception as exc:
        logger.warning("Unexpected error calling %s: %s", url, exc)
        return (0, b"")


def _http_basic_headers() -> dict:
    """Build auth headers with HTTP Basic auth for Presenton."""
    import base64
    credentials = f"{PRESENTON_USERNAME}:{PRESENTON_PASSWORD}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


# ---------------------------------------------------------------------------
# LiteLLM client abstraction
#
# When running through the skill runner, the runner passes an async
# LiteLLMClient instance. When running standalone (CLI), we fall back to
# synchronous urllib calls to the LiteLLM proxy.
# ---------------------------------------------------------------------------


class _SyncLiteLLMClient:
    """
    Synchronous LiteLLM client for standalone/CLI use.

    Makes HTTP calls to the LiteLLM proxy for LLM generation via
    /v1/chat/completions. This class ensures the skill never touches
    MCP servers directly — all LLM interactions go through LiteLLM.
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


class _SyncAsyncWrapper:
    """
    Wraps an async LiteLLMClient (from the runner) so skill code can
    call it synchronously.
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


def _resolve_litellm_client(litellm_client=None) -> Any:
    """
    Resolve the LiteLLM client to a sync interface.

    - If litellm_client is an async LiteLLMClient from the runner, wrap it.
    - If litellm_client is already sync, use as-is.
    - Otherwise, create a new sync client from env vars.
    """
    if litellm_client is None:
        return _SyncLiteLLMClient()
    if hasattr(litellm_client, "chat_completion"):
        import inspect
        if inspect.iscoroutinefunction(litellm_client.chat_completion):
            return _SyncAsyncWrapper(litellm_client)
        return litellm_client
    return _SyncLiteLLMClient()


# ---------------------------------------------------------------------------
# Outline generation via LLM (uses resolved LiteLLM client)
# ---------------------------------------------------------------------------

OUTLINE_PROMPT_TEMPLATE = textwrap.dedent("""\
    You are an expert presentation designer. Create a structured outline for a
    presentation on the following topic.

    Topic: {topic}

    {instructions}
    {content_context}

    Requirements:
    - Generate approximately {n_slides} content slides (not counting title or TOC).
    - Use the following format EXACTLY (this is what the presentation engine expects):

        # Presentation Title

        ## 1. Slide Title
        - Key point or bullet 1
        - Key point or bullet 2
        - Key point or bullet 3

        ## 2. Next Slide Title
        - Key point or bullet 1
        - Key point or bullet 2

    - Each slide should have 3-5 bullet points max — keep them concise and impactful.
    - Use the following tone: {tone}
    - Use the following verbosity level: {verbosity}
    - Make each slide title descriptive and action-oriented.
    - Number slides sequentially starting from 1.

    Output ONLY the markdown outline — no preamble, no explanation, no wrapping
    quotes or code fences.
""")


def _build_outline_prompt(topic: str, n_slides: int, style: str, content_context: str = "", instructions: str = "") -> str:
    """Build the outline generation prompt."""
    tone = _style_to_tone(style)
    verbosity = "standard"
    if style in ("minimal",):
        verbosity = "concise"

    return OUTLINE_PROMPT_TEMPLATE.format(
        topic=topic,
        n_slides=n_slides,
        tone=tone,
        verbosity=verbosity,
        content_context=content_context or "No additional content provided.",
        instructions=instructions or "No additional instructions.",
    )


def _style_to_tone(style: str) -> str:
    """Map skill style to Presenton-compatible tone."""
    tone_map = {
        "modern": "default",
        "minimal": "default",
        "bold": "professional",
        "elegant": "professional",
        "academic": "educational",
        "creative": "casual",
        "dark": "professional",
    }
    return tone_map.get(style.lower(), "default")


def _call_litellm(client: Any, messages: list[dict[str, str]], max_tokens: int = 4096) -> str:
    """
    Call LiteLLM for outline generation via the resolved client.
    """
    result = client.chat_completion(
        MODEL_ALIAS,
        messages,
        max_tokens=max_tokens,
        temperature=0.3,
        stream=False,
    )

    choices = result.get("choices", [])
    if not choices:
        return "No response generated."
    return choices[0].get("message", {}).get("content", "No content in response.")


def _generate_outline(client: Any, topic: str, n_slides: int, style: str, content_context: str = "") -> str:
    """
    Generate a presentation outline via the LLM.
    Returns the markdown outline text.
    """
    prompt = _build_outline_prompt(topic, n_slides, style, content_context)

    messages = [
        {"role": "user", "content": prompt},
    ]

    return _call_litellm(client, messages, max_tokens=4096)


# ---------------------------------------------------------------------------
# Content source reader
# ---------------------------------------------------------------------------


def _read_content_source(content_source: str) -> str:
    """
    Read content from a file path or return raw text.
    If content_source looks like a file path and exists, read it.
    Otherwise treat it as raw text content.
    """
    if not content_source:
        return ""

    # Check if it's a file path
    path = Path(content_source)
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Could not read content source file %s: %s", path, exc)
            return ""

    # Treat as raw text
    return content_source


# ---------------------------------------------------------------------------
# Presenton API integration
# ---------------------------------------------------------------------------


def _submit_async_generation(outline: str, n_slides: int, style: str) -> Optional[str]:
    """
    Submit a presentation generation job to Presenton's async API.
    Returns the task_id on success, or None on failure.
    """
    template = STYLE_TO_TEMPLATE.get(style.lower(), "general")
    tone = _style_to_tone(style)
    verbosity = "concise" if style in ("minimal",) else "standard"

    payload = {
        "content": outline,
        "n_slides": n_slides,
        "template": template,
        "tone": tone,
        "verbosity": verbosity,
        "language": "English",
        "export_as": "pptx",
        "include_table_of_contents": False,
        "include_title_slide": True,
    }

    url = f"{PRESENTON_URL}/api/v1/ppt/presentation/generate/async"
    auth_headers = _http_basic_headers()
    result = _http_post(url, payload, headers=auth_headers, timeout=30)

    if not result:
        logger.error("Presenton async submit returned no response")
        return None

    status, body = result
    if status != 200:
        logger.error("Presenton async submit failed with HTTP %d: %s", status, body)
        return None

    task_id = body.get("id") or body.get("task_id")
    if not task_id:
        logger.error("Presenton async submit returned no task ID: %s", body)
        return None

    logger.info("Presenton async task submitted: task_id=%s", task_id)
    return task_id


def _poll_task(task_id: str, timeout: float = None, poll_interval: float = 5.0) -> Optional[dict]:
    """
    Poll Presenton for task completion.
    Returns the result dict (with presentation_id, path, edit_path) on success.
    Returns None on failure or timeout.
    """
    if timeout is None:
        timeout = PRESENTON_GENERATION_TIMEOUT

    deadline = time.time() + timeout
    auth_headers = _http_basic_headers()

    while time.time() < deadline:
        url = f"{PRESENTON_URL}/api/v1/ppt/presentation/status/{task_id}"
        result = _http_get(url, headers=auth_headers, timeout=15)

        if not result:
            logger.warning("Presenton status poll failed, retrying...")
            time.sleep(poll_interval)
            continue

        status_code, body = result
        if status_code != 200:
            logger.warning("Presenton status poll returned HTTP %d: %s", status_code, body)
            time.sleep(poll_interval)
            continue

        task_status = body.get("status", "").lower()

        if task_status == "completed":
            data = body.get("data")
            if not data:
                logger.error("Presenton task completed but data is empty")
                return None
            logger.info("Presenton task %s completed", task_id)
            return data

        if task_status == "error":
            error = body.get("error") or body.get("message") or "Unknown error"
            logger.error("Presenton task %s failed: %s", task_id, error)
            return None

        logger.info(
            "Presenton task %s in progress (%s), polling in %.0fs…",
            task_id, body.get("message", task_status), poll_interval,
        )
        time.sleep(poll_interval)

    logger.error("Presenton task %s timed out after %.0fs", task_id, timeout)
    return None


def _download_presentation(export_path: str) -> Optional[bytes]:
    """
    Download the presentation file from Presenton.
    Returns the binary content or None on failure.
    """
    url = f"{PRESENTON_URL}{export_path}"
    auth_headers = _http_basic_headers()
    result = _http_get_binary(url, headers=auth_headers, timeout=120)

    if not result:
        logger.error("Presenton download returned no response")
        return None

    status, data = result
    if status != 200:
        logger.error("Presenton download failed with HTTP %d", status)
        return None

    if not data:
        logger.error("Presenton download returned empty content")
        return None

    logger.info("Downloaded presentation file (%d bytes)", len(data))
    return data


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _slugify(value: str) -> str:
    """Convert a string to a filename-safe slug."""
    slug = value.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    slug = slug.strip("-")
    return slug or "presentation"


def _write_artifact(file_bytes: bytes, topic: str, extension: str = "pptx") -> Optional[str]:
    """
    Save the presentation file as an artifact.
    Returns the file path or None on failure.
    """
    try:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        slug = _slugify(topic)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        filename = f"presentation_{ts}_{slug}.{extension}"
        path = ARTIFACT_DIR / filename
        path.write_bytes(file_bytes)
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
    Execute the presentation_build skill.

    All LLM interactions go through LiteLLM. Presenton is accessed directly
    as it is not an MCP server (see Phase 11 for architecture).

    Args:
        params: Skill parameters (topic, slide_count, style, content_source).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.
            If not provided, a sync client is created from env vars.

    Returns:
        Dict with 'summary', 'presentation_id', 'artifact_path', and metadata.
    """
    # Resolve LiteLLM client (sync interface guaranteed)
    client = _resolve_litellm_client(litellm_client)
    # Validate inputs
    topic = params.get("topic")
    if not topic or not str(topic).strip():
        result = {"error": "Missing required 'topic' parameter"}
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing topic")
        return result

    topic = str(topic).strip()

    slide_count = params.get("slide_count", 8)
    if not isinstance(slide_count, int) or slide_count < 1:
        slide_count = 8
    slide_count = max(1, min(slide_count, 50))  # hard cap

    style = params.get("style", "modern")
    if style not in STYLE_TO_TEMPLATE:
        style = "modern"

    content_source = params.get("content_source", "")

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing presentation_build: topic='{topic[:100]}...'")
        job.add_log(f"Slides: {slide_count}, style: {style}")
        job.add_log(f"Model alias: {MODEL_ALIAS}")
        job.add_log(f"Presenton URL: {PRESENTON_URL}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")
        if content_source:
            job.add_log(f"Content source provided: {content_source[:100]}")

    # Install timeout
    _install_timeout()

    try:
        # Phase 1: Get content (from source file or raw text)
        content_context = _read_content_source(content_source)
        if content_context and hasattr(job, "add_log"):
            job.add_log(f"Loaded content source ({len(content_context)} chars)")

        # Phase 2: Generate outline via LLM
        if hasattr(job, "add_log"):
            job.add_log("Phase 1: Generating outline via LLM...")

        outline = _generate_outline(client, topic, slide_count, style, content_context)

        if hasattr(job, "add_log"):
            job.add_log(f"Outline generated ({len(outline)} chars)")

        # Validate outline has content
        if not outline or len(outline.strip()) < 20:
            msg = "LLM returned an empty or very short outline"
            if hasattr(job, "add_log"):
                job.add_log(f"Error: {msg}")
            return {
                "error": msg,
                "summary": f"Failed to generate outline for topic: {topic}",
            }

        # Phase 3: Submit to Presenton (async)
        if hasattr(job, "add_log"):
            job.add_log("Phase 2: Submitting to Presenton...")

        task_id = _submit_async_generation(outline, slide_count, style)
        if not task_id:
            msg = "Presenton async submission failed"
            if hasattr(job, "add_log"):
                job.add_log(f"Error: {msg}")
            return {
                "error": msg,
                "summary": f"Failed to submit presentation to Presenton for topic: {topic}",
            }

        # Phase 4: Poll for completion
        if hasattr(job, "add_log"):
            job.add_log("Phase 3: Polling Presenton for completion...")

        result_data = _poll_task(task_id, timeout=PRESENTON_GENERATION_TIMEOUT)
        if not result_data:
            msg = "Presenton generation timed out or failed"
            if hasattr(job, "add_log"):
                job.add_log(f"Error: {msg}")
            return {
                "error": msg,
                "summary": f"Presenton generation failed for topic: {topic}",
            }

        presentation_id = result_data.get("presentation_id") or result_data.get("id") or uuid.uuid4().hex[:12]
        export_path = result_data.get("path")
        edit_url = result_data.get("edit_path")

        if hasattr(job, "add_log"):
            job.add_log(f"Presenton generation complete: presentation_id={presentation_id}")

        # Phase 5: Download the file
        if hasattr(job, "add_log"):
            job.add_log("Phase 4: Downloading presentation file...")

        file_bytes = _download_presentation(export_path) if export_path else None
        if not file_bytes:
            msg = "Presenton file download failed"
            if hasattr(job, "add_log"):
                job.add_log(f"Error: {msg}")
            return {
                "error": msg,
                "summary": f"Failed to download generated presentation for topic: {topic}",
            }

        # Phase 6: Save artifact
        if hasattr(job, "add_log"):
            job.add_log("Phase 5: Saving artifact...")

        artifact_path = _write_artifact(file_bytes, topic, "pptx")

        if hasattr(job, "add_log"):
            if artifact_path:
                job.add_log(f"Artifact saved: {artifact_path}")
            else:
                job.add_log("Warning: artifact save failed")

        # Build summary
        summary = (
            f"Presentation generated: '{topic}' — "
            f"{slide_count} slides, style={style}"
        )
        if artifact_path:
            summary += f" (artifact: {artifact_path})"

        return {
            "summary": summary,
            "presentation_id": presentation_id,
            "title": topic,
            "slide_count": slide_count,
            "style": style,
            "outline": outline,
            "artifact_path": artifact_path,
            "edit_url": f"{PRESENTON_URL}/presentation?id={presentation_id}" if presentation_id else None,
            "model_alias": MODEL_ALIAS,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "summary": f"Presentation build timed out after {MAX_RUNTIME_SECS}s.",
            "error": msg,
            "presentation_id": None,
            "artifact_path": None,
            "model_alias": MODEL_ALIAS,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")
        return {
            "summary": f"Presentation build failed: {msg}",
            "error": msg,
            "presentation_id": None,
            "artifact_path": None,
            "model_alias": MODEL_ALIAS,
        }

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)
        return {
            "summary": f"Presentation build failed: {msg}",
            "error": msg,
            "presentation_id": None,
            "artifact_path": None,
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
        self.logs: list[str] = []

    def add_log(self, msg: str) -> None:
        self.logs.append(msg)
        print(f"  [LOG] {msg}")


def main():
    """Standalone test entrypoint.

    Usage:
        python skill.py --topic "AI in Healthcare" --slide-count 8
        python skill.py --topic "Q3 Review" --style bold --slide-count 12
        python skill.py --topic "Test" --dry-run
    """
    import argparse

    parser = argparse.ArgumentParser(description="presentation_build standalone test")
    parser.add_argument("--topic", required=True, help="Presentation topic")
    parser.add_argument("--slide-count", type=int, default=8, help="Number of slides (1-50)")
    parser.add_argument("--style", default="modern", choices=list(STYLE_TO_TEMPLATE.keys()), help="Presentation style")
    parser.add_argument("--content-source", default="", help="Path to content file or raw text")
    parser.add_argument("--dry-run", action="store_true", help="Print parameters without calling any services")
    parser.add_argument("--base-url", default=LITELLM_BASE_URL, help="LiteLLM base URL")
    parser.add_argument("--api-key", default=LITELLM_API_KEY, help="LiteLLM API key")
    parser.add_argument("--presenton-url", default=PRESENTON_URL, help="Presenton base URL")
    parser.add_argument("--presenton-user", default=PRESENTON_USERNAME, help="Presenton username")
    parser.add_argument("--presenton-pass", default=PRESENTON_PASSWORD, help="Presenton password")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  Topic: {args.topic}")
        print(f"  Slide count: {args.slide_count}")
        print(f"  Style: {args.style}")
        print(f"  Template: {STYLE_TO_TEMPLATE.get(args.style.lower(), 'general')}")
        print(f"  Content source: {args.content_source or '(none)'}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  Artifact dir: {ARTIFACT_DIR}")
        print(f"  LiteLLM: {LITELLM_BASE_URL}")
        print(f"  Presenton: {PRESENTON_URL}")
        print(f"  Presenton user: {PRESENTON_USERNAME}")
        print()
        print("  Phase 1: LLM generates markdown outline from topic")
        print("  Phase 2: Submit outline to Presenton /generate-async")
        print("  Phase 3: Poll /status/{task_id} until completed")
        print("  Phase 4: Download exported pptx from Presenton")
        print("  Phase 5: Save artifact to /home/chuck/data/media/presentations/")
        return

    # Override env vars for CLI usage
    if args.base_url != LITELLM_BASE_URL:
        globals()["LITELLM_BASE_URL"] = args.base_url
    if args.api_key:
        globals()["LITELLM_API_KEY"] = args.api_key
    if args.presenton_url != PRESENTON_URL:
        globals()["PRESENTON_URL"] = args.presenton_url
    if args.presenton_user != PRESENTON_USERNAME:
        globals()["PRESENTON_USERNAME"] = args.presenton_user
    if args.presenton_pass != PRESENTON_PASSWORD:
        globals()["PRESENTON_PASSWORD"] = args.presenton_pass

    params = {
        "topic": args.topic,
        "slide_count": args.slide_count,
        "style": args.style,
        "content_source": args.content_source,
    }
    # Pass a sync LiteLLM client for standalone use
    client = _SyncLiteLLMClient(base_url=base_url, api_key=api_key)
    result = run(params, _MockJob(), litellm_client=client)

    print(f"\n--- presentation_build response ---")
    print(f"Summary: {result.get('summary', 'N/A')}")
    if result.get("presentation_id"):
        print(f"Presentation ID: {result['presentation_id']}")
    if result.get("artifact_path"):
        print(f"Artifact: {result['artifact_path']}")
    if result.get("edit_url"):
        print(f"Edit URL: {result['edit_url']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"Model: {result.get('model_alias', 'N/A')}")


if __name__ == "__main__":
    main()
