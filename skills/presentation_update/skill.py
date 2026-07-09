#!/usr/bin/env python3
"""
presentation_update skill — Update existing presentations via Presenton.

Purpose:
  Find a presentation by title, parse natural-language update instructions
  into structured parameters using an LLM, and dispatch an async update
  to Presenton to regenerate the presentation with the requested changes.

Workflow:
  1. Validate inputs (presentation_title, instructions).
  2. Search Presenton for the presentation by title (list all, fuzzy match).
  3. Use the LLM (via LiteLLM) to parse the user's instructions into
     structured update parameters (UPDATE_INSTRUCTION_PROMPT pattern).
  4. Build an update payload merging current values with requested changes.
  5. Dispatch async generation via Presenton's /generate-async with parent_id.
  6. Return task_id, summary, and matched presentation info.

Constraints:
  - Max runtime: 300 seconds (5 minutes).
  - Presenton UI remains LAN-only — this skill is the only remote path.
  - All LLM interactions go through LiteLLM.
  - Uses async Presenton API to avoid holding long-lived connections.

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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_RUNTIME_SECS = int(os.environ.get("PRESENTATION_UPDATE_MAX_RUNTIME", "300"))

# LiteLLM endpoint (set by skill runner or environment)
LITELLM_BASE_URL = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000")
LITELLM_API_KEY = os.environ.get("LITELLM_API_KEY", "")
MODEL_ALIAS = os.environ.get("PRESENTATION_UPDATE_MODEL_ALIAS", "local/qwen-coder")

# Presenton endpoint (set by skill runner or environment)
# Default: Docker internal network (presenton:80). Override with PRESENTON_URL env var.
PRESENTON_URL = os.environ.get("PRESENTON_URL", "http://presenton:80")
PRESENTON_USERNAME = os.environ.get("PRESENTON_AUTH_USERNAME", "presenton")
PRESENTON_PASSWORD = os.environ.get("PRESENTON_AUTH_PASSWORD")
PRESENTON_GENERATION_TIMEOUT = float(
    os.environ.get("PRESENTON_GENERATION_TIMEOUT", "240")
)  # seconds for Presenton polling

logger = logging.getLogger("skill.presentation_update")

# ---------------------------------------------------------------------------
# UPDATE_INSTRUCTION_PROMPT — from old harness
# ---------------------------------------------------------------------------

UPDATE_INSTRUCTION_PROMPT = textwrap.dedent("""\
    You are a presentation update assistant. Parse the user's natural-language
    instructions into structured update parameters for an existing presentation.

    Presentation title: {title}
    Current version: {version}
    Current slide count: {slide_count}
    Current template: {template}
    Current tone: {tone}
    Current verbosity: {verbosity}
    Current language: {language}

    User's update instructions: {instructions}

    Output ONLY a JSON object with the fields that should change. Valid fields:
    - title (string) - new presentation title
    - content (string) - new content description
    - outline (string) - new markdown outline
    - n_slides (integer, 3-50) - new slide count
    - template (string, e.g. "general", "academic", "dark", "creative")
    - tone (string: "default", "casual", "professional", "funny", "educational", "sales_pitch")
    - verbosity (string: "concise", "standard", "text-heavy")
    - language (string) - new language
    - export_as (string: "pptx" or "pdf") - output format
    - instructions (string) - additional free-form instructions for the AI
    - include_table_of_contents (boolean) - include TOC slide
    - include_title_slide (boolean) - include title slide
    - research (boolean) - whether to do deep research
    - kb_search (boolean) - whether to search knowledge base

    Only include fields that the user explicitly asked to change. Omit fields
    the user didn't mention. If the user said something ambiguous or complex
    that doesn't map cleanly to a field, put it in the "instructions" field
    as free-text for the AI to interpret.

    Examples:
    - "more casual" -> {{"tone": "casual"}}
    - "12 slides" -> {{"n_slides": 12}}
    - "dark template" -> {{"template": "dark"}}
    - "less text per slide" -> {{"verbosity": "concise"}}
    - "add a slide about budget" -> {{"instructions": "add a slide about budget"}}
    - "make it professional and use the dark template" -> {{"tone": "professional", "template": "dark"}}

    Output ONLY the JSON object — no preamble, no explanation, no code fences.
""")

# ---------------------------------------------------------------------------
# Timeout enforcement
# ---------------------------------------------------------------------------


class TimeoutError(Exception):
    """Raised when the skill exceeds its maximum runtime."""


def _timeout_handler(signum, frame):
    raise TimeoutError(f"presentation_update exceeded {MAX_RUNTIME_SECS}s max runtime")


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
# HTTP helpers (stdlib only, no external deps)
# ---------------------------------------------------------------------------


def _http_post(url: str, payload: dict, headers: dict = None, timeout: int = 60) -> Optional[tuple[int, dict]]:
    """Generic HTTP POST. Returns (status_code, parsed_json) or (status_code, {}) on error."""
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


def _http_basic_headers() -> dict:
    """Build auth headers with HTTP Basic auth for Presenton."""
    import base64
    credentials = f"{PRESENTON_USERNAME}:{PRESENTON_PASSWORD}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {encoded}"}


# ---------------------------------------------------------------------------
# LiteLLM client abstraction (mirrors presentation_build conventions)
# ---------------------------------------------------------------------------


class _SyncLiteLLMClient:
    """Synchronous LiteLLM client for standalone/CLI use."""

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
    """Wraps an async LiteLLMClient (from the runner) so skill code can call it synchronously."""

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
    """Resolve the LiteLLM client to a sync interface."""
    if litellm_client is None:
        return _SyncLiteLLMClient()
    if hasattr(litellm_client, "chat_completion"):
        import inspect
        if inspect.iscoroutinefunction(litellm_client.chat_completion):
            return _SyncAsyncWrapper(litellm_client)
        return litellm_client
    return _SyncLiteLLMClient()


# ---------------------------------------------------------------------------
# Instruction parsing via LLM
# ---------------------------------------------------------------------------


def _parse_instructions(
    client: Any,
    presentation_title: str,
    version: int,
    slide_count: int,
    template: str,
    tone: str,
    verbosity: str,
    language: str,
    instructions: str,
) -> dict[str, Any]:
    """
    Use the LLM to parse natural-language instructions into structured
    update parameters.

    Returns a dict of fields that should be changed.
    On LLM failure, falls back to {"instructions": instructions}.
    """
    prompt = UPDATE_INSTRUCTION_PROMPT.format(
        title=presentation_title,
        version=version,
        slide_count=slide_count,
        template=template,
        tone=tone,
        verbosity=verbosity,
        language=language,
        instructions=instructions,
    )

    messages = [
        {"role": "system", "content": (
            "You are a presentation update assistant. Parse user instructions "
            "into a JSON object of structured update parameters. "
            "Output ONLY valid JSON — no code fences, no preamble."
        )},
        {"role": "user", "content": prompt},
    ]

    try:
        result = client.chat_completion(
            MODEL_ALIAS,
            messages,
            max_tokens=2048,
            temperature=0.2,
            response_format={"type": "json_object"},
            stream=False,
        )

        choices = result.get("choices", [])
        if not choices:
            raise RuntimeError("LLM returned no choices")

        llm_json_str = choices[0].get("message", {}).get("content", "").strip()

        # Strip code fences if present
        if llm_json_str.startswith("```"):
            llm_json_str = llm_json_str.split("\n", 1)[-1]
            if llm_json_str.endswith("```"):
                llm_json_str = llm_json_str[:-3]
            llm_json_str = llm_json_str.strip()

        update_payload = json.loads(llm_json_str)
        logger.info(
            "LLM parsed update instructions for '%s': %s",
            presentation_title, update_payload,
        )
        return update_payload

    except Exception as exc:
        logger.warning(
            "LLM instruction parsing failed for '%s', falling back to raw instructions: %s",
            presentation_title, exc,
        )
        return {"instructions": instructions}


# ---------------------------------------------------------------------------
# Presenton API — presentation search
# ---------------------------------------------------------------------------


def _list_presentations() -> list[dict]:
    """
    List all presentations from Presenton.
    Returns a list of presentation metadata dicts.
    """
    url = f"{PRESENTON_URL}/api/v1/ppt/presentations"
    auth_headers = _http_basic_headers()
    result = _http_get(url, headers=auth_headers, timeout=30)

    if not result:
        logger.error("Presenton list returned no response")
        return []

    status, body = result
    if status != 200:
        logger.error("Presenton list failed with HTTP %d: %s", status, body)
        return []

    # Presenton returns {"presentations": [...]} or just a list
    if isinstance(body, list):
        return body
    return body.get("presentations", body.get("presentations", []))


def _find_presentation(title: str) -> Optional[dict]:
    """
    Find a presentation by title (fuzzy match).
    Returns the best match (most recent version) or None.
    """
    presentations = _list_presentations()
    if not presentations:
        logger.warning("No presentations found in Presenton")
        return None

    target = title.lower().strip()
    # Strip common trailing words for matching
    target_clean = re.sub(
        r"\s+(presentation|presentations|slide|slides|deck|decks)\s*$",
        "", target, flags=re.IGNORECASE
    ).strip()

    matches = []
    for pres in presentations:
        pres_title = pres.get("title", "")
        pres_slug = pres_title.lower().strip()
        # Fuzzy match: check if target is in the title or title is in target
        if target_clean in pres_slug or pres_slug in target_clean:
            matches.append(pres)

    if not matches:
        logger.info("No presentations matching '%s' (found %d total)", title, len(presentations))
        return None

    # Pick the most recent version (highest version number, or last created)
    best = max(
        matches,
        key=lambda p: (p.get("version", 0), p.get("created_at", "")),
    )

    logger.info(
        "Found presentation '%s' (id=%s, v%d, %d slides) — matched from %d candidates",
        best.get("title"), best.get("presentation_id", best.get("id")),
        best.get("version", 1), best.get("slide_count", 0), len(matches),
    )
    return best


# ---------------------------------------------------------------------------
# Presenton API — async update dispatch
# ---------------------------------------------------------------------------


def _dispatch_async_update(
    presentation_id: str,
    presentation_title: str,
    update_payload: dict,
    parent_outline: str = "",
    parent_slide_count: int = 8,
    parent_template: str = "general",
    parent_tone: str = "default",
    parent_verbosity: str = "standard",
    parent_language: str = "English",
) -> Optional[dict]:
    """
    Dispatch an async update to Presenton.

    Merges the update_payload with parent values, then submits via
    /generate-async with parent_id set.

    Returns the Presenton task response dict (with id/task_id) on success.
    Returns None on failure.
    """
    # Resolve effective values by merging parent defaults with updates
    effective = {
        "n_slides": parent_slide_count,
        "template": parent_template,
        "tone": parent_tone,
        "verbosity": parent_verbosity,
        "language": parent_language,
        "export_as": "pptx",
        "parent_id": presentation_id,
    }

    # Apply updates
    for key, value in update_payload.items():
        if key in effective or key in ("title", "content", "outline", "instructions",
                                         "include_table_of_contents", "include_title_slide",
                                         "research", "kb_search"):
            effective[key] = value

    # Build the content for Presenton — use updated outline or fall back to parent outline
    content = effective.pop("outline", None) or effective.pop("content", None) or parent_outline
    if not content:
        # If no outline provided, reconstruct from title
        content = effective.get("title", presentation_title)

    payload = {
        "content": content,
        "n_slides": effective.get("n_slides", parent_slide_count),
        "template": effective.get("template", parent_template),
        "tone": effective.get("tone", parent_tone),
        "verbosity": effective.get("verbosity", parent_verbosity),
        "language": effective.get("language", parent_language),
        "export_as": effective.get("export_as", "pptx"),
        "parent_id": presentation_id,
        "include_table_of_contents": effective.get("include_table_of_contents", False),
        "include_title_slide": effective.get("include_title_slide", True),
    }

    instructions = effective.get("instructions")
    if instructions:
        payload["instructions"] = instructions

    url = f"{PRESENTON_URL}/api/v1/ppt/presentation/generate/async"
    auth_headers = _http_basic_headers()
    result = _http_post(url, payload, headers=auth_headers, timeout=30)

    if not result:
        logger.error("Presenton async update returned no response")
        return None

    status, body = result
    if status != 200:
        logger.error("Presenton async update failed with HTTP %d: %s", status, body)
        return None

    task_id = body.get("id") or body.get("task_id")
    if not task_id:
        logger.error("Presenton async update returned no task ID: %s", body)
        return None

    logger.info("Presenton async update dispatched: task_id=%s, presentation_id=%s",
                task_id, presentation_id)
    # ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run(params: dict[str, Any], job, litellm_client=None) -> dict[str, Any]:
    """
    Execute the presentation_update skill.

    All LLM interactions go through LiteLLM. Presenton is accessed directly
    as it is not an MCP server.

    Args:
        params: Skill parameters (presentation_title, instructions).
        job: The runner Job object for logging.
        litellm_client: Optional LiteLLM client from the runner.
            If not provided, a sync client is created from env vars.

    Returns:
        Dict with 'summary', 'presentation_id', 'task_id', and metadata.
    """
    # Resolve LiteLLM client (sync interface guaranteed)
    client = _resolve_litellm_client(litellm_client)

    # Validate inputs
    presentation_title = params.get("presentation_title")
    if not presentation_title or not str(presentation_title).strip():
        result = {"error": "Missing required 'presentation_title' parameter"}
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing presentation_title")
        return result
    presentation_title = str(presentation_title).strip()

    instructions = params.get("instructions")
    if not instructions or not str(instructions).strip():
        result = {"error": "Missing required 'instructions' parameter"}
        if hasattr(job, "add_log"):
            job.add_log("Validation failed: missing instructions")
        return result
    instructions = str(instructions).strip()

    # Log the invocation
    if hasattr(job, "add_log"):
        job.add_log(f"Executing presentation_update: title='{presentation_title[:100]}'")
        job.add_log(f"Instructions: '{instructions[:200]}'")
        job.add_log(f"Model alias: {MODEL_ALIAS}")
        job.add_log(f"Presenton URL: {PRESENTON_URL}")
        job.add_log(f"Max runtime: {MAX_RUNTIME_SECS}s")

    # Install timeout
    _install_timeout()

    try:
        # --- Step 1: Find the presentation by title ---
        if hasattr(job, "add_log"):
            job.add_log("Step 1: Searching Presenton for presentation...")

        pres = _find_presentation(presentation_title)
        if not pres:
            msg = f"No presentation found matching '{presentation_title}'"
            if hasattr(job, "add_log"):
                job.add_log(f"Error: {msg}")
                job.add_log("Try 'list my presentations' to see what's available.")
            return {
                "summary": msg,
                "error": msg,
                "presentation_id": None,
                "task_id": None,
                "model_alias": MODEL_ALIAS,
            }

        presentation_id = pres.get("presentation_id") or pres.get("id")
        pres_title = pres.get("title", presentation_title)
        pres_version = pres.get("version", 1)
        pres_slide_count = pres.get("slide_count", 8)
        pres_template = pres.get("template", "general")
        pres_tone = pres.get("tone", "default")
        pres_verbosity = pres.get("verbosity", "standard")
        pres_language = pres.get("language", "English")
        pres_outline = pres.get("outline", pres_title)

        if hasattr(job, "add_log"):
            job.add_log(
                f"Found: '{pres_title}' (id={presentation_id}, v{pres_version}, "
                f"{pres_slide_count} slides, {pres_template}/{pres_tone})"
            )

        # --- Step 2: Parse instructions via LLM ---
        if hasattr(job, "add_log"):
            job.add_log("Step 2: Parsing instructions via LLM...")

        update_payload = _parse_instructions(
            client=client,
            presentation_title=pres_title,
            version=pres_version,
            slide_count=pres_slide_count,
            template=pres_template,
            tone=pres_tone,
            verbosity=pres_verbosity,
            language=pres_language,
            instructions=instructions,
        )

        if hasattr(job, "add_log"):
            job.add_log(f"Parsed update params: {json.dumps(update_payload)}")

        # If no meaningful update (LLM returned empty or only instructions field)
        if not update_payload:
            msg = f"No changes detected in instructions for '{pres_title}'"
            if hasattr(job, "add_log"):
                job.add_log(f"Info: {msg}")
            return {
                "summary": (
                    f"Found '{pres_title}' (v{pres_version}, {pres_slide_count} slides). "
                    f"Please specify what changes you'd like."
                ),
                "error": None,
                "presentation_id": presentation_id,
                "found_title": pres_title,
                "found_version": pres_version,
                "task_id": None,
                "model_alias": MODEL_ALIAS,
            }

        # --- Step 3: Dispatch async update ---
        if hasattr(job, "add_log"):
            job.add_log("Step 3: Dispatching async update to Presenton...")

        task_result = _dispatch_async_update(
            presentation_id=presentation_id,
            presentation_title=pres_title,
            update_payload=update_payload,
            parent_outline=pres_outline,
            parent_slide_count=pres_slide_count,
            parent_template=pres_template,
            parent_tone=pres_tone,
            parent_verbosity=pres_verbosity,
            parent_language=pres_language,
        )

        if not task_result:
            msg = f"Presenton async update dispatch failed for '{pres_title}'"
            if hasattr(job, "add_log"):
                job.add_log(f"Error: {msg}")
            return {
                "summary": msg,
                "error": msg,
                "presentation_id": presentation_id,
                "found_title": pres_title,
                "found_version": pres_version,
                "task_id": None,
                "update_params": update_payload,
                "model_alias": MODEL_ALIAS,
            }

        task_id = task_result.get("id") or task_result.get("task_id")

        # Build a human-readable summary of what's changing
        changes = []
        if update_payload.get("tone"):
            changes.append(f"tone to {update_payload['tone']}")
        if update_payload.get("template"):
            changes.append(f"template to {update_payload['template']}")
        if update_payload.get("n_slides"):
            changes.append(f"{update_payload['n_slides']} slides")
        if update_payload.get("verbosity"):
            changes.append(f"verbosity to {update_payload['verbosity']}")
        if update_payload.get("language"):
            changes.append(f"language to {update_payload['language']}")
        if update_payload.get("export_as"):
            changes.append(f"format to {update_payload['export_as']}")
        if update_payload.get("title") and update_payload["title"] != pres_title:
            changes.append(f"title to '{update_payload['title']}'")
        if update_payload.get("instructions"):
            changes.append(f"custom: {update_payload['instructions']}")

        changes_str = ", ".join(changes) if changes else "custom changes"

        if hasattr(job, "add_log"):
            job.add_log(
                f"Update dispatched: task_id={task_id}, changes={changes_str}"
            )

        return {
            "summary": (
                f"Update started for '{pres_title}' — {changes_str}. "
                f"This typically takes 2-5 minutes."
            ),
            "presentation_id": presentation_id,
            "found_title": pres_title,
            "found_version": pres_version,
            "task_id": task_id,
            "update_params": update_payload,
            "model_alias": MODEL_ALIAS,
        }

    except TimeoutError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Timeout: {msg}")
        return {
            "summary": f"Presentation update timed out after {MAX_RUNTIME_SECS}s.",
            "error": msg,
            "presentation_id": None,
            "task_id": None,
            "model_alias": MODEL_ALIAS,
        }

    except RuntimeError as exc:
        msg = str(exc)
        if hasattr(job, "add_log"):
            job.add_log(f"Runtime error: {msg}")
        return {
            "summary": f"Presentation update failed: {msg}",
            "error": msg,
            "presentation_id": None,
            "task_id": None,
            "model_alias": MODEL_ALIAS,
        }

    except Exception as exc:
        msg = f"Unexpected error: {exc}"
        if hasattr(job, "add_log"):
            job.add_log(msg)
        return {
            "summary": f"Presentation update failed: {msg}",
            "error": msg,
            "presentation_id": None,
            "task_id": None,
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
        python skill.py --title "Q4 Review" --instructions "make it more casual"
        python skill.py --title "AI Homelab" --instructions "dark template, 12 slides" --dry-run
    """
    import argparse

    parser = argparse.ArgumentParser(description="presentation_update standalone test")
    parser.add_argument("--title", required=True, help="Presentation title to update")
    parser.add_argument("--instructions", required=True, help="Natural-language update instructions")
    parser.add_argument("--dry-run", action="store_true", help="Print parameters without calling any services")
    parser.add_argument("--base-url", default=LITELLM_BASE_URL, help="LiteLLM base URL")
    parser.add_argument("--api-key", default=LITELLM_API_KEY, help="LiteLLM API key")
    parser.add_argument("--presenton-url", default=PRESENTON_URL, help="Presenton base URL")
    parser.add_argument("--presenton-user", default=PRESENTON_USERNAME, help="Presenton username")
    parser.add_argument("--presenton-pass", default=PRESENTON_PASSWORD, help="Presenton password")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN ===")
        print(f"  Title: {args.title}")
        print(f"  Instructions: {args.instructions}")
        print(f"  Model: {MODEL_ALIAS}")
        print(f"  Max runtime: {MAX_RUNTIME_SECS}s")
        print(f"  LiteLLM: {LITELLM_BASE_URL}")
        print(f"  Presenton: {PRESENTON_URL}")
        print(f"  Presenton user: {PRESENTON_USERNAME}")
        print()
        print("  Step 1: List presentations from Presenton, fuzzy-match by title")
        print("  Step 2: LLM parses instructions via UPDATE_INSTRUCTION_PROMPT")
        print("  Step 3: Submit async update to Presenton /generate-async with parent_id")
        print("  Step 4: Return task_id + summary")
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
        "presentation_title": args.title,
        "instructions": args.instructions,
    }
    client = _SyncLiteLLMClient(base_url=LITELLM_BASE_URL, api_key=LITELLM_API_KEY)
    result = run(params, _MockJob(), litellm_client=client)

    print(f"\n--- presentation_update response ---")
    print(f"Summary: {result.get('summary', 'N/A')}")
    if result.get("task_id"):
        print(f"Task ID: {result['task_id']}")
    if result.get("presentation_id"):
        print(f"Presentation ID: {result['presentation_id']}")
    if result.get("found_title"):
        print(f"Found title: {result['found_title']}")
    if result.get("found_version"):
        print(f"Found version: {result['found_version']}")
    if result.get("update_params"):
        print(f"Update params: {json.dumps(result['update_params'])}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print(f"Model: {result.get('model_alias', 'N/A')}")


if __name__ == "__main__":
    main()
