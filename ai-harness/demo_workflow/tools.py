"""Build tools for the demo-workflow deep agent.

Each tool has a `@tool` wrapper dispatched by the deep agents framework.
Tools that need the LLM (generate_html, validate_html, etc.) use
chat_completion_async internally. The wrappers are async functions so
LangChain's @tool creates a BaseTool with a working .arun() method,
which LangGraph calls during agent.ainvoke().
"""

from __future__ import annotations

from datetime import datetime
import asyncio
import json
import logging
from typing import Any

from langchain_core.tools import tool

from core.config import DEMO_WORKFLOW_MODEL, MEDIA_OUTPUT_DIR, INTERNAL_BASE_URL, PUBLIC_BASE_URL
from core.llm import chat_completion_async

# Import shared research tools from deep_research
from deep_research.tools import search_and_crawl, think_tool

from demo_workflow.prompts import (
    BUILD_GENERATE_SYSTEM,
    BUILD_VALIDATE_SYSTEM,
    BUILD_FIX_SYSTEM,
    CRITIQUE_SYSTEM,
    VERIFY_INTERACTIVITY_SYSTEM,
)

logger = logging.getLogger("demo_workflow.tools")

# ---------------------------------------------------------------------------
# HTML size limits — guard against blowing the context window
# ---------------------------------------------------------------------------

MAX_HTML_INPUT_CHARS = 20_000   # truncate incoming HTML to this size
MAX_HTML_OUTPUT_TOKENS = 16_000  # generous ceiling for full HTML files


# ---------------------------------------------------------------------------
# 1. kb_lookup — search the family knowledge base
# ---------------------------------------------------------------------------

def _kb_lookup_impl(query: str) -> str:
    """Sync implementation of KB lookup."""
    try:
        from family_kb.service import search_kb
        from family_kb.schemas import SearchRequest

        result = search_kb(SearchRequest(query=query, limit=10))

        if not result.get("results"):
            return json.dumps({
                "relevant_findings": [],
                "prior_demos": [],
                "user_preferences": [],
                "domain_insights": [],
            })

        findings = []
        for hit in result["results"]:
            source = hit.get("source", "unknown")
            text = (hit.get("text", "") or "")[:600]
            score = hit.get("score", 0)
            findings.append(f"Source: {source} (score: {score:.3f}): {text}")

        return json.dumps({
            "relevant_findings": findings,
            "prior_demos": [],
            "user_preferences": [],
            "domain_insights": [],
        })

    except Exception as e:
        logger.warning("KB lookup failed (non-fatal): %s", e)
        return json.dumps({
            "relevant_findings": [f"KB unavailable: {e}"],
            "prior_demos": [],
            "user_preferences": [],
            "domain_insights": [],
        })


@tool
def kb_lookup(query: str) -> str:
    """Search the family knowledge base for prior information relevant to
    this demo. Use this before web research to check for existing demos,
    user notes, or domain-specific knowledge.

    Args:
        query: Search query for the knowledge base

    Returns:
        A JSON string with keys: relevant_findings (list), prior_demos (list),
        user_preferences (list), domain_insights (list).
    """
    return _kb_lookup_impl(query)


# ---------------------------------------------------------------------------
# 2. generate_html — produce updated HTML for a build step
# ---------------------------------------------------------------------------

async def _generate_html_impl(
    spec: str,
    step_description: str,
    current_html: str,
    system_prompt: str | None = None,
) -> str:
    """Generate or advance the demo HTML for one build step."""
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

    effective_prompt = system_prompt if system_prompt is not None else BUILD_GENERATE_SYSTEM

    try:
        result = await chat_completion_async(
            messages=[
                {"role": "system", "content": effective_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=DEMO_WORKFLOW_MODEL,
            temperature=0.4,
            max_tokens=MAX_HTML_OUTPUT_TOKENS,
            timeout=300.0,
        )
        result = _strip_code_fences(result)
        return result
    except Exception as e:
        logger.exception("generate_html failed: %s", e)
        return f"Error generating HTML: {e}"


@tool
async def generate_html(
    spec: str,
    step_description: str,
    current_html: str,
    system_prompt: str | None = None,
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
        system_prompt: Optional custom system prompt. Defaults to
            BUILD_GENERATE_SYSTEM. Used by progressive enhancement phases
            to focus on specific aspects like structure, features, or polish.

    Returns:
        The complete updated HTML file as a string.
    """
    return await _generate_html_impl(spec, step_description, current_html, system_prompt)


# ---------------------------------------------------------------------------
# 3. validate_html — check HTML against acceptance criteria
# ---------------------------------------------------------------------------

async def _validate_html_impl(
    acceptance_criteria: str,
    html: str,
) -> str:
    """Validate the current HTML against acceptance criteria."""
    truncated = html[:MAX_HTML_INPUT_CHARS] if len(html) > MAX_HTML_INPUT_CHARS else html

    user_prompt = (
        f"## Acceptance Criteria\n{acceptance_criteria}\n\n"
        f"## Current HTML\n"
        f"```html\n{truncated}\n```\n\n"
        "Return a JSON object: {{\"passed\": true/false, \"issues\": [...], \"summary\": \"...\"}}"
    )

    try:
        result = await chat_completion_async(
            messages=[
                {"role": "system", "content": BUILD_VALIDATE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            model=DEMO_WORKFLOW_MODEL,
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


@tool
async def validate_html(
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
    return await _validate_html_impl(acceptance_criteria, html)


# ---------------------------------------------------------------------------
# 4. fix_html — correct issues found by validation or critique
# ---------------------------------------------------------------------------

async def _fix_html_impl(
    issues: str,
    html: str,
) -> str:
    """Fix issues in the demo HTML based on validation or critique feedback."""
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
        result = await chat_completion_async(
            messages=[
                {"role": "system", "content": BUILD_FIX_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            model=DEMO_WORKFLOW_MODEL,
            temperature=0.3,
            max_tokens=MAX_HTML_OUTPUT_TOKENS,
            timeout=300.0,
        )
        result = _strip_code_fences(result)
        return result
    except Exception as e:
        logger.exception("fix_html failed: %s", e)
        return f"Error fixing HTML: {e}"


@tool
async def fix_html(
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
    return await _fix_html_impl(issues, html)


# ---------------------------------------------------------------------------
# 5. verify_interactivity — static analysis of JS interactivity
# ---------------------------------------------------------------------------

async def _verify_interactivity_impl(
    html: str,
) -> str:
    """Static analysis of JavaScript interactivity in the demo HTML."""
    truncated = html[:MAX_HTML_INPUT_CHARS] if len(html) > MAX_HTML_INPUT_CHARS else html

    user_prompt = (
        f"## Complete HTML Demo\n"
        f"```html\n{truncated}\n```\n\n"
        "Analyze the JavaScript interactivity and return JSON as specified."
    )

    try:
        result = await chat_completion_async(
            messages=[
                {"role": "system", "content": VERIFY_INTERACTIVITY_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            model=DEMO_WORKFLOW_MODEL,
            temperature=0.1,
            max_tokens=3000,
            timeout=120.0,
        )
        parsed = _try_parse_json(result)
        if parsed is not None:
            parsed.setdefault("passed", False)
            parsed.setdefault("score", 0)
            parsed.setdefault("verified_interactions", [])
            parsed.setdefault("missing_handlers", [])
            parsed.setdefault("issues", [])
            parsed.setdefault("recommendations", [])
            parsed.setdefault("mocked_features", [])
            parsed.setdefault("level3_patterns", {
                "simulated_delays": False,
                "loading_indicators": False,
                "toast_notifications": False,
                "confirmation_dialogs": False,
                "data_persistence": False,
                "key_flow_coverage": False,
            })
            return json.dumps(parsed, indent=2)
        return result
    except Exception as e:
        logger.exception("verify_interactivity failed: %s", e)
        return json.dumps({
            "passed": False,
            "score": 0,
            "verified_interactions": [],
            "missing_handlers": [],
            "issues": [f"Verification error: {e}"],
            "recommendations": [],
            "mocked_features": [],
            "level3_patterns": {
                "simulated_delays": False,
                "loading_indicators": False,
                "toast_notifications": False,
                "confirmation_dialogs": False,
                "data_persistence": False,
                "key_flow_coverage": False,
            },
        })


@tool
async def verify_interactivity(
    html: str,
) -> str:
    """Static analysis of JavaScript interactivity in the demo HTML.

    Parses the HTML to verify:
    - All event handlers reference defined functions
    - View navigation works (functions exist, toggle state correctly)
    - Forms have submit/change handlers
    - Buttons have click handlers
    - No obvious JS errors (undefined references, syntax issues)
    - Interactive elements are properly connected

    Args:
        html: The complete HTML to analyze.

    Returns:
        A JSON string with keys: passed (bool), score (1-10),
        verified_interactions (list), missing_handlers (list),
        issues (list), recommendations (list), mocked_features (list).
    """
    return await _verify_interactivity_impl(html)


# ---------------------------------------------------------------------------
# 6. critique_demo — full-pass quality review
# ---------------------------------------------------------------------------

async def _critique_demo_impl(
    design_spec: str,
    html: str,
) -> str:
    """Full-pass quality review of the completed demo."""
    truncated = html[:MAX_HTML_INPUT_CHARS] if len(html) > MAX_HTML_INPUT_CHARS else html

    user_prompt = f"## Design Spec\n{design_spec}\n\n## Current HTML\n```html\n{truncated}\n```\n"

    try:
        result = await chat_completion_async(
            messages=[
                {"role": "system", "content": CRITIQUE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            model=DEMO_WORKFLOW_MODEL,
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
            parsed.setdefault("level3_realism_score", 0)
            return json.dumps(parsed, indent=2)
        return result
    except Exception as e:
        logger.exception("critique_demo failed: %s", e)
        return json.dumps({
            "overall_score": 0,
            "critique": f"Critique failed: {e}",
            "issues_found": [f"Critique error: {e}"],
            "strengths": [],
            "level3_realism_score": 0,
        })


@tool
async def critique_demo(
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
    return await _critique_demo_impl(design_spec, html)


# ---------------------------------------------------------------------------
# 7. save_demo — write final HTML + metadata to disk
# ---------------------------------------------------------------------------

def _save_demo_impl(
    title: str,
    html: str,
    design_spec: str,
    notes: str,
    verification_results: str = "{}",
    discovery_metadata: str = "{}",
) -> str:
    """Save the final demo: embed notes as HTML comments, write final_demo.html
    and metadata.json to disk."""
    import re as _re
    from pathlib import Path

    # Generate slug from title
    slug = _re.sub(r"[^a-zA-Z0-9]+", "-", title).lower().strip("-")
    if len(slug) > 60:
        slug = slug[:60]
    slug = f"{slug}-{datetime.now().strftime('%Y%m%d%H%M')}"

    # Create demo directory — ensure the full path exists, falling back to
    # a local directory if the configured MEDIA_OUTPUT_DIR is inaccessible.
    media_base = Path(MEDIA_OUTPUT_DIR)
    demo_dir = media_base / "demos" / slug
    try:
        demo_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("Cannot create demo dir %s: %s. Falling back to local path.", demo_dir, e)
        # Fallback: use a local directory inside the app's parent
        local_base = Path(__file__).resolve().parent.parent.parent / "local_media"
        demo_dir = local_base / "demos" / slug
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

    # Parse verification results and extract mock behavior / functional areas
    ver_data = {}
    try:
        ver_data = json.loads(verification_results) if verification_results.strip() else {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("save_demo: could not parse verification_results, using defaults")

    # Parse discovery metadata (discovery_notes, complexity_score, complexity_breakdown)
    disc_data = {}
    try:
        disc_data = json.loads(discovery_metadata) if discovery_metadata.strip() else {}
    except (json.JSONDecodeError, TypeError):
        logger.warning("save_demo: could not parse discovery_metadata, using defaults")

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
        # Enhanced verification metadata
        "mocked_features": ver_data.get("mocked_features", []),
        "functional_areas": ver_data.get("verified_interactions", []),
        "code_quality_score": ver_data.get("score", 0),
        "verification_issues": ver_data.get("issues", []),
        "level3_patterns": ver_data.get("level3_patterns", {}),
        "level3_realism_score": ver_data.get("level3_realism_score", 0),
        # Product insights metadata
        "discovery_notes": disc_data.get("discovery_notes", {}),
        "complexity_score": disc_data.get("complexity_score", 0),
        "complexity_breakdown": disc_data.get("complexity_breakdown", {}),
    }

    meta_path = demo_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.info("Demo saved: %s (slug=%s, dir=%s)", title, slug, demo_dir)

    return json.dumps({
        "title": title,
        "slug": slug,
        "local_url": local_url,
        "public_url": public_url,
        "html_path": str(html_path),
    })


@tool
def save_demo(
    title: str,
    html: str,
    design_spec: str,
    notes: str,
    verification_results: str = "{}",
    discovery_metadata: str = "{}",
) -> str:
    """Save the final demo: embed notes as HTML comments, write final_demo.html
    and metadata.json to disk.

    Args:
        title: The demo title.
        html: The final complete HTML content.
        design_spec: The design specification (for metadata extraction).
        notes: Additional notes to embed in the HTML as a comment.
        verification_results: JSON string from verify_interactivity with
            mocked_features, verified_interactions, score, and issues.
            Defaults to empty JSON if not provided.
        discovery_metadata: JSON string with discovery_notes, complexity_score,
            and complexity_breakdown. Defaults to empty JSON.

    Returns:
        A JSON string with keys: title, slug, local_url, public_url, html_path.
    """
    return _save_demo_impl(title, html, design_spec, notes, verification_results, discovery_metadata)


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
