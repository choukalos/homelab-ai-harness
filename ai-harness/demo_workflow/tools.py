"""Build tools for the demo-workflow orchestrator agent.

Five LangChain @tool functions that the orchestrator uses during the
build loop (Phase 6), polish (Phase 7), and save (Phase 8) to iteratively
construct and finalize the demo HTML.

Each tool is a thin wrapper around a LiteLLM call with a dedicated
system prompt.  String I/O keeps the tool contract simple and
avoids complex Pydantic schemas inside the agent loop.
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

from langchain_core.tools import tool

from core.llm import chat_completion_sync
from demo_workflow.prompts import (
    BUILD_GENERATE_SYSTEM,
    BUILD_VALIDATE_SYSTEM,
    BUILD_FIX_SYSTEM,
    CRITIQUE_SYSTEM,
)

logger = logging.getLogger("demo_workflow.tools")

# ---------------------------------------------------------------------------
# HTML size limits — guard against blowing the context window
# ---------------------------------------------------------------------------

MAX_HTML_INPUT_CHARS = 12_000   # truncate incoming HTML to this size
MAX_HTML_OUTPUT_TOKENS = 16_000  # generous ceiling for full HTML files


# ---------------------------------------------------------------------------
# 1. generate_html — produce updated HTML for a build step
# ---------------------------------------------------------------------------

@tool
def generate_html(
    spec: str,
    step_description: str,
    current_html: str,
) -> str:
    """Generate or advance the demo HTML for one build step.

    Takes the design specification, a description of what to build in this
    step, and the current HTML state (which may be empty for the first step).
    Returns the COMPLETE updated HTML with all CSS and JS inline.

    Args:
        spec: The design specification (from design_spec.md).
        step_description: What to build in this step (title + description
            from the build plan, plus acceptance criteria).
        current_html: The current HTML file content (may be empty string
            for the initial step).

    Returns:
        The complete updated HTML file as a string.
    """
    # Truncate current HTML if it's very large
    if len(current_html) > MAX_HTML_INPUT_CHARS:
        current_html = (
            f"[TRUNCATED - {len(current_html)} chars, showing last {MAX_HTML_INPUT_CHARS}]\n"
            + current_html[-MAX_HTML_INPUT_CHARS:]
        )

    user_prompt = (
        f"## Design Spec\n{spec}\n\n"
        f"## Build Step\n{step_description}\n\n"
        f"## Current HTML\n"
        f'```html\n{current_html if current_html.strip() else "(empty - starting from scratch)"}\n```\n\n'
        "Produce the COMPLETE updated HTML. Return ONLY the HTML, nothing else."
    )

    try:
        result = chat_completion_sync(
            messages=[
                {"role": "system", "content": BUILD_GENERATE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=MAX_HTML_OUTPUT_TOKENS,
            timeout=300.0,
        )
        result = _strip_code_fences(result)
        return result
    except Exception as e:
        logger.exception("generate_html failed: %s", e)
        return f"Error generating HTML: {e}"


# ---------------------------------------------------------------------------
# 2. validate_html — check HTML against acceptance criteria
# ---------------------------------------------------------------------------

@tool
def validate_html(
    acceptance_criteria: str,
    html: str,
) -> str:
    """Validate the current HTML against acceptance criteria.

    Checks whether the build step has been completed correctly. Returns a
    structured pass/fail report with any issues found.

    Args:
        acceptance_criteria: The acceptance criteria for this build step.
        html: The current HTML to validate.

    Returns:
        A JSON string with keys: passed (bool), issues (list), summary (str).
    """
    truncated = html[:MAX_HTML_INPUT_CHARS] if len(html) > MAX_HTML_INPUT_CHARS else html

    user_prompt = (
        f"## Acceptance Criteria\n{acceptance_criteria}\n\n"
        f"## Current HTML\n"
        f"```html\n{truncated}\n```\n\n"
        "Return a JSON object: {{\"passed\": true/false, \"issues\": [...], \"summary\": \"...\"}}"
    )

    try:
        result = chat_completion_sync(
            messages=[
                {"role": "system", "content": BUILD_VALIDATE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
            timeout=120.0,
        )
        parsed = _try_parse_json(result)
        if parsed is not None:
            parsed.setdefault("passed", False)
            parsed.setdefault("issues", [])
            parsed.setdefault("summary", "Validation complete.")
            return json.dumps(parsed, indent=2)
        return result
    except Exception as e:
        logger.exception("validate_html failed: %s", e)
        return json.dumps({
            "passed": False,
            "issues": [f"Validation error: {e}"],
            "summary": f"Validation failed with error: {e}",
        })


# ---------------------------------------------------------------------------
# 3. fix_html — correct issues found by validation or critique
# ---------------------------------------------------------------------------

@tool
def fix_html(
    issues: str,
    html: str,
) -> str:
    """Fix issues in the demo HTML based on validation or critique feedback.

    Takes the reported issues and current HTML, produces the corrected
    complete HTML with all fixes applied.

    Args:
        issues: The issues to fix (from validation or critique output).
        html: The current HTML to fix.

    Returns:
        The corrected complete HTML as a string.
    """
    if len(html) > MAX_HTML_INPUT_CHARS:
        html = (
            f"[TRUNCATED - showing last {MAX_HTML_INPUT_CHARS} chars]\n"
            + html[-MAX_HTML_INPUT_CHARS:]
        )

    user_prompt = (
        f"## Issues to Fix\n{issues}\n\n"
        f"## Current HTML\n"
        f"```html\n{html}\n```\n\n"
        "Return the COMPLETE corrected HTML with all fixes applied. "
        "Return ONLY the HTML, nothing else."
    )

    try:
        result = chat_completion_sync(
            messages=[
                {"role": "system", "content": BUILD_FIX_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=MAX_HTML_OUTPUT_TOKENS,
            timeout=300.0,
        )
        result = _strip_code_fences(result)
        return result
    except Exception as e:
        logger.exception("fix_html failed: %s", e)
        return f"Error fixing HTML: {e}"


# ---------------------------------------------------------------------------
# 4. critique_demo — full-pass quality review (Phase 7)
# ---------------------------------------------------------------------------

@tool
def critique_demo(
    design_spec: str,
    html: str,
) -> str:
    """Full-pass quality review of the completed demo.

    Evaluates visual polish, functional correctness, completeness vs.
    requirements, mobile responsiveness, and code quality. Returns a
    structured critique with a score and prioritized issues.

    Args:
        design_spec: The design specification (from design_spec.md).
        html: The current HTML to evaluate.

    Returns:
        A JSON string with keys: overall_score (1-10), critique (str),
        issues_found (list), strengths (list).
    """
    truncated = html[:MAX_HTML_INPUT_CHARS] if len(html) > MAX_HTML_INPUT_CHARS else html

    user_prompt = f"## Design Spec\n{design_spec}\n\n## Current HTML\n```html\n{truncated}\n```\n"

    try:
        result = chat_completion_sync(
            messages=[
                {"role": "system", "content": CRITIQUE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=2000,
            timeout=120.0,
        )
        parsed = _try_parse_json(result)
        if parsed is not None:
            parsed.setdefault("overall_score", 5)
            parsed.setdefault("critique", "")
            parsed.setdefault("issues_found", [])
            parsed.setdefault("strengths", [])
            return json.dumps(parsed, indent=2)
        return result
    except Exception as e:
        logger.exception("critique_demo failed: %s", e)
        return json.dumps({
            "overall_score": 0,
            "critique": f"Critique failed: {e}",
            "issues_found": [f"Critique error: {e}"],
            "strengths": [],
        })


# ---------------------------------------------------------------------------
# 5. save_demo — write final HTML + metadata (Phase 8)
# ---------------------------------------------------------------------------

@tool
def save_demo(
    title: str,
    html: str,
    design_spec: str,
    notes: str,
) -> str:
    """Save the final demo: embed notes as HTML comments, write final_demo.html
    and metadata.json to disk.

    Args:
        title: The demo title.
        html: The final complete HTML content.
        design_spec: The design specification (for metadata extraction).
        notes: Additional notes to embed in the HTML as a comment.

    Returns:
        A JSON string with keys: title, slug, local_url, public_url, html_path.
    """
    import re as _re
    from pathlib import Path

    from core.config import MEDIA_OUTPUT_DIR, INTERNAL_BASE_URL, PUBLIC_BASE_URL

    # Generate slug from title
    slug = _re.sub(r"[^a-zA-Z0-9]+", "-", title).lower().strip("-")
    if len(slug) > 60:
        slug = slug[:60]
    slug = f"{slug}-{datetime.now().strftime('%Y%m%d%H%M')}"

    # Create demo directory
    demo_dir = Path(MEDIA_OUTPUT_DIR) / "demos" / slug
    demo_dir.mkdir(parents=True, exist_ok=True)

    # Embed notes as HTML comment at the end (before </body> or at the end)
    notes_comment = f"\n<!-- Demo Notes\n{notes}\n-->\n"
    if "</body>" in html:
        html = html.replace("</body>", notes_comment + "</body>")
    else:
        html = html + notes_comment

    # Write final HTML
    html_path = demo_dir / "final_demo.html"
    html_path.write_text(html, encoding="utf-8")

    # Extract description from design spec (first paragraph or summary)
    description = ""
    for line in design_spec.split("\n")[:30]:
        line = line.strip()
        if line and not line.startswith("#"):
            description = line[:200]
            break

    # Extract tags from design spec keywords
    tags = []
    spec_lower = design_spec.lower()
    possible_tags = [
        "dashboard", "app", "landing-page", "form", "table", "chart",
        "animation", "interactive", "mobile-responsive", "e-commerce",
        "social", "productivity", "portfolio", "blog",
    ]
    for tag in possible_tags:
        if tag in spec_lower:
            tags.append(tag)
    if not tags:
        tags = ["demo"]

    # Build URLs
    local_url = f"{INTERNAL_BASE_URL}/media/files/demos/{slug}/final_demo.html"
    public_url = f"{PUBLIC_BASE_URL}/media/files/demos/{slug}/final_demo.html"

    # Write metadata.json
    from datetime import datetime as _dt

    metadata = {
        "title": title,
        "slug": slug,
        "description": description,
        "tags": tags,
        "created_at": _dt.now().isoformat(),
        "screens": [],
        "local_url": local_url,
        "public_url": public_url,
        "requirements_summary": design_spec[:500] if design_spec else "",
        "design_decisions": "",
        "open_questions": [],
    }

    meta_path = demo_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.info("Demo saved: %s (slug=%s)", title, slug)

    return json.dumps({
        "title": title,
        "slug": slug,
        "local_url": local_url,
        "public_url": public_url,
        "html_path": str(html_path),
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    """Strip ```html / ``` markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline > 0:
            text = text[first_newline + 1:]
        else:
            return text

        last_fence = text.rfind("\n```")
        if last_fence > 0:
            text = text[:last_fence]
    return text.strip()


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """Try to extract and parse a JSON object from LLM output."""
    text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

    return None
