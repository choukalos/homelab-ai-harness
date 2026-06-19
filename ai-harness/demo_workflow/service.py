"""
Demo Workflow service: coordinator pattern with per-phase agent invocations.

Each phase runs as a separate short-lived LLM invocation, passing structured
JSON state between phases instead of accumulating conversation history. This
keeps each invocation well under 30K tokens and avoids vLLM's 70K context
limit.

The old single-agent approach (DEPRECATED but kept for streaming compat):
  User Prompt → Deep Agent (Phases 1-9 in one thread) → Response

New coordinator approach (Progressive Enhancement, Session 6):
  User Prompt → Coordinator (run_demo)
    → Phase 1: Parse Request        (chat_completion_sync)
    → Phase 2: KB Lookup            (kb_lookup tool)
    → Phase 3: Web Research         (chat_completion_sync + search_and_crawl)
    → Phase 4: Requirements & Design (chat_completion_sync)
    → Phase 5: Build Plan           (chat_completion_sync)
    → Phase 6a: Core Structure      (generate_html with BUILD_STRUCTURE_SYSTEM)
    → Phase 6b: Interactive Features (generate_html with BUILD_FEATURES_SYSTEM)
    → Phase 6c: Polish              (generate_html with BUILD_POLISH_SYSTEM)
    → Phase 7: Functional Verification (verify_interactivity + fix_html tools)
    → Phase 8: Polish & Critique    (critique_demo + fix_html tools)
    → Phase 9: Save Final           (save_demo tool)

Phase 6 is split into 3 progressive sub-phases for better failure recovery:
- 6a builds the skeleton (layout, nav, view containers)
- 6b adds interactive features (forms, data, state) on top of 6a
- 6c adds visual polish (transitions, edge cases) on top of 6a+6b
Failure in 6b or 6c doesn't invalidate prior sub-phases.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
import re
import time
import uuid
import logging
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from deepagents import create_deep_agent

from core.config import DEMO_WORKFLOW_MODEL, LITELLM_API_KEY, LITELLM_BASE_URL
from core.llm import chat_completion_async
from demo_workflow.prompts import (
    DEMO_WORKFLOW_INSTRUCTIONS,
    RESEARCHER_INSTRUCTIONS,
    PHASE_PARSE_SYSTEM,
    PHASE_KB_LOOKUP_SYSTEM,
    PHASE_DESIGN_SYSTEM,
    PHASE_PLAN_SYSTEM,
    PHASE_SAVE_SYSTEM,
    BUILD_STRUCTURE_SYSTEM,
    BUILD_FEATURES_SYSTEM,
    BUILD_POLISH_SYSTEM,
)
from demo_workflow.schemas import (
    DemoCreateRequest,
    DemoCreateResponse,
    DemoBuildError,
    DemoCheckpointStatus,
    DemoResumeResponse,
    DemoStreamEvent,
)
from demo_workflow.state import DemoState
from demo_workflow.tools import (
    generate_html,
    validate_html,
    fix_html,
    verify_interactivity,
    critique_demo,
    save_demo,
    _generate_html_impl,
    _validate_html_impl,
    _fix_html_impl,
    _verify_interactivity_impl,
    _critique_demo_impl,
    _save_demo_impl,
)

logger = logging.getLogger("demo_workflow")

# ---------------------------------------------------------------------------
# Checkpoint Manager — file-based checkpointing for pipeline resumption
# ---------------------------------------------------------------------------

_CHECKPOINT_DIR = Path.home() / ".ai-harness" / "demo_checkpoints"
_CHECKPOINT_TTL_HOURS = 24

# Phase index → phase name mapping (matches the phases list in run_demo)
PHASE_NAMES = [
    "Phase 1: Parse Request",
    "Phase 2: KB Lookup",
    "Phase 3: Web Research",
    "Phase 4: Requirements & Design",
    "Phase 5: Build Plan",
    "Phase 6a: Core Structure",
    "Phase 6b: Interactive Features",
    "Phase 6c: Polish & Micro-interactions",
    "Phase 7: Functional Verification",
    "Phase 8: Polish & Critique",
    "Phase 9: Save Final",
]


class CheckpointManager:
    """File-based checkpoint persistence for the demo pipeline.

    Each checkpoint is a JSON file at ~/.ai-harness/demo_checkpoints/{thread_id}.json
    containing the serialized DemoState plus metadata (phase index, timestamps).

    Checkpoints auto-expire after 24 hours. Old checkpoints are cleaned up
    on each save/load operation.
    """

    @staticmethod
    def _checkpoint_path(thread_id: str) -> Path:
        return _CHECKPOINT_DIR / f"{thread_id}.json"

    @staticmethod
    def ensure_dir() -> None:
        _CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def save(cls, thread_id: str, state: DemoState, phase: int) -> None:
        """Persist DemoState after a completed phase.

        Args:
            thread_id: The thread ID for this demo run.
            state: The current DemoState to serialize.
            phase: The index of the phase just completed (0-based).
        """
        cls.ensure_dir()
        now = datetime.now()
        checkpoint = {
            "thread_id": thread_id,
            "phase": phase,
            "phase_name": PHASE_NAMES[phase] if phase < len(PHASE_NAMES) else f"Phase {phase}",
            "state_json": state.to_json(),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(hours=_CHECKPOINT_TTL_HOURS)).isoformat(),
        }
        try:
            cls._checkpoint_path(thread_id).write_text(
                json.dumps(checkpoint, ensure_ascii=False), encoding="utf-8"
            )
            logger.info("Checkpoint saved: thread=%s phase=%s (%s)", thread_id, phase, checkpoint["phase_name"])
        except Exception as e:
            logger.warning("Checkpoint save failed (non-fatal): %s", e)

    @classmethod
    def load(cls, thread_id: str) -> tuple[DemoState, int] | None:
        """Load a checkpoint if it exists and is not expired.

        Returns:
            (state, resume_phase) tuple if a valid checkpoint is found,
            or None if no checkpoint or expired.
            resume_phase is the index of the NEXT phase to run (the phase
            after the one that was last saved).
        """
        path = cls._checkpoint_path(thread_id)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Checkpoint file corrupted, ignoring: %s", e)
            return None

        # Check expiration
        expires_at = datetime.fromisoformat(data.get("expires_at", ""))
        if datetime.now() > expires_at:
            logger.info("Checkpoint expired for thread=%s, removing", thread_id)
            try:
                path.unlink()
            except OSError:
                pass
            return None

        # Deserialize state
        try:
            state = DemoState.from_json(data["state_json"])
        except Exception as e:
            logger.warning("Checkpoint state deserialization failed: %s", e)
            return None

        # Resume from the phase AFTER the one we saved (0-based index)
        resume_phase = data.get("phase", 0) + 1
        logger.info(
            "Checkpoint loaded: thread=%s phase=%s (resuming from %s)",
            thread_id, data.get("phase_name", "?"), PHASE_NAMES[resume_phase] if resume_phase < len(PHASE_NAMES) else "unknown",
        )
        return (state, resume_phase)

    @classmethod
    def get_status(cls, thread_id: str) -> DemoCheckpointStatus | None:
        """Get checkpoint status without deserializing the full state."""
        path = cls._checkpoint_path(thread_id)
        if not path.exists():
            return DemoCheckpointStatus(thread_id=thread_id, exists=False)

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return DemoCheckpointStatus(thread_id=thread_id, exists=False)

        expires_at = datetime.fromisoformat(data.get("expires_at", ""))
        is_expired = datetime.now() > expires_at

        return DemoCheckpointStatus(
            thread_id=thread_id,
            exists=True,
            phase=data.get("phase", 0),
            phase_name=data.get("phase_name", ""),
            title=json.loads(data.get("state_json", "{}"))
                  .get("title", "") if data.get("state_json") else "",
            created_at=data.get("created_at", ""),
            expires_at=data.get("expires_at", ""),
            can_resume=not is_expired,
        )

    @classmethod
    def remove(cls, thread_id: str) -> None:
        """Remove a checkpoint file."""
        path = cls._checkpoint_path(thread_id)
        if path.exists():
            try:
                path.unlink()
                logger.info("Checkpoint removed: thread=%s", thread_id)
            except OSError as e:
                logger.warning("Checkpoint remove failed: %s", e)

    @classmethod
    def cleanup(cls) -> int:
        """Remove all expired checkpoints. Returns the count of removed files."""
        if not _CHECKPOINT_DIR.exists():
            return 0

        removed = 0
        now = datetime.now()
        for path in _CHECKPOINT_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(data.get("expires_at", ""))
                if now > expires_at:
                    path.unlink()
                    removed += 1
            except (json.JSONDecodeError, ValueError, KeyError):
                # Corrupted file — remove it
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        if removed:
            logger.info("Checkpoint cleanup: removed %d expired checkpoints", removed)
        return removed


# Run-time cleanup: on module import, clean expired checkpoints from a prior run
try:
    CheckpointManager.cleanup()
except Exception:
    pass


# ---------------------------------------------------------------------------
# MySQL checkpointer — reuse from deep_research to avoid duplicating init
# ---------------------------------------------------------------------------

from deep_research.service import (
    ensure_checkpointer_tables as _ensure_checkpointer_tables,
    get_checkpointer as _get_checkpointer,
)

ensure_checkpointer_tables = _ensure_checkpointer_tables
get_checkpointer = _get_checkpointer

# ---------------------------------------------------------------------------
# KB Lookup Tool — calls family_kb.search_kb with a timeout guard
# ---------------------------------------------------------------------------

def _kb_lookup_impl(query: str) -> str:
    """Internal implementation of KB lookup, callable directly."""
    try:
        from family_kb.service import search_kb
        from family_kb.schemas import SearchRequest

        result = search_kb(SearchRequest(query=query, limit=10))

        if not result.get("results"):
            return json.dumps({"relevant_findings": [], "prior_demos": [], "user_preferences": [], "domain_insights": []})

        findings = []
        for hit in result["results"]:
            source = hit.get("source", "unknown")
            text = (hit.get("text", "") or "")[:600]
            score = hit.get("score", 0)
            findings.append(f"Source: {source} (score: {score:.3f}): {text}")

        return json.dumps({"relevant_findings": findings, "prior_demos": [], "user_preferences": [], "domain_insights": []})

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
        Relevant knowledge base results or a message if unavailable.
    """
    return _kb_lookup_impl(query)


# ---------------------------------------------------------------------------
# Agent factory: orchestrator + research sub-agent (kept for streaming compat)
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
    """Create or return the cached deep agent instance.

    KEPT for backward compatibility (streaming endpoint) and for use by
    callers that need a full LangGraph agent. The new coordinator pattern
    in run_demo() uses per-phase chat_completion_sync calls instead.
    """
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
# Helper: resolve the model name for chat_completion_sync
# ---------------------------------------------------------------------------

def _resolve_model() -> str:
    model_name = os.getenv("DEMO_WORKFLOW_MODEL", DEMO_WORKFLOW_MODEL)
    if ":" in model_name:
        model_name = model_name.split(":")[-1]
    return model_name


def _try_parse_json(text: str) -> dict | None:
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


# ---------------------------------------------------------------------------
# Phase Implementations — each is a standalone function invoked by the
# coordinator. Takes DemoState, mutates the relevant fields, returns it.
# ---------------------------------------------------------------------------

async def _phase1_parse_request(state: DemoState) -> DemoState:
    """Phase 1: Parse the user's prompt into structured requirements."""
    logger.info("Phase 1: Parse Request")

    # Edge case: empty or trivially short prompt
    if not state.raw_prompt or len(state.raw_prompt.strip()) < 10:
        raise ValueError(
            "Prompt too short to build a meaningful demo. "
            "Please describe what kind of app/demo you want with at least a sentence."
        )

    parsed = _try_parse_json(state.raw_prompt)  # Handle case where user already sent JSON
    if parsed and "title" in parsed and "key_features" in parsed:
        state.parsed_requirements = parsed
        state.title = parsed.get("title", "")
        logger.info("Phase 1: User already provided structured JSON")
        return state

    result = await chat_completion_async(
        messages=[
            {"role": "system", "content": PHASE_PARSE_SYSTEM},
            {"role": "user", "content": state.raw_prompt},
        ],
        model=_resolve_model(),
        temperature=0.2,
        max_tokens=2000,
        timeout=120.0,
    )

    parsed = _try_parse_json(result)
    if parsed:
        state.parsed_requirements = parsed
        state.title = parsed.get("title", state.title or "Untitled Demo")
    else:
        # Fallback: create a minimal structure
        state.parsed_requirements = {
            "title": state.title or "Untitled Demo",
            "description": state.raw_prompt[:200],
            "key_features": [],
            "screens": [],
            "style_hints": {},
            "constraints": [],
        }
        state.title = state.parsed_requirements["title"]

    # Complexity guard: warn if too many screens/features for a 1-page demo
    num_screens = len(state.parsed_requirements.get("screens", []))
    num_features = len(state.parsed_requirements.get("key_features", []))
    state.parsed_requirements["_complexity_warning"] = False
    if num_screens > 8 or num_features > 15:
        state.parsed_requirements["_complexity_warning"] = True
        logger.warning(
            "Phase 1: High complexity detected (%d screens, %d features). "
            "This may be too complex for a 1-page clickable demo.",
            num_screens, num_features,
        )

    logger.info("Phase 1 complete: title=%s", state.title)
    return state


async def _phase2_kb_lookup(state: DemoState) -> DemoState:
    """Phase 2: Search the family knowledge base."""
    logger.info("Phase 2: KB Lookup")

    query = state.parsed_requirements.get("description", state.raw_prompt)[:300]
    raw = _kb_lookup_impl(query)

    kb_data = _try_parse_json(raw)
    if kb_data:
        state.kb_results = kb_data
    else:
        state.kb_results = {"relevant_findings": [raw[:500]]}

    logger.info("Phase 2 complete: %d findings", len(state.kb_results.get("relevant_findings", [])))
    return state


async def _phase3_web_research(state: DemoState) -> DemoState:
    """Phase 3: Web research using search_and_crawl."""
    logger.info("Phase 3: Web Research")

    from deep_research.tools import _search_and_crawl_impl

    desc = state.parsed_requirements.get("description", state.raw_prompt)[:200]
    search_query = (
        f"best practices competitor patterns UX conventions building a {desc} "
        f"web demo. Focus on engaging and polished user experiences."
    )

    raw = _search_and_crawl_impl(search_query)

    state.research_results = {
        "query": search_query,
        "findings": raw[:5000],
    }

    logger.info("Phase 3 complete: %d chars of research", len(raw))
    return state


async def _phase4_design(state: DemoState) -> DemoState:
    """Phase 4: Synthesize requirements + research into a design specification."""
    logger.info("Phase 4: Requirements & Design Spec")

    user_content = (
        f"## User Requirements\n{json.dumps(state.parsed_requirements, indent=2)}\n\n"
        f"## Knowledge Base Findings\n{json.dumps(state.kb_results, indent=2)}\n\n"
        f"## Web Research\n{state.research_results.get('findings', 'No research results')}."
    )

    result = await chat_completion_async(
        messages=[
            {"role": "system", "content": PHASE_DESIGN_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        model=_resolve_model(),
        temperature=0.4,
        max_tokens=8000,
        timeout=600.0,
    )

    state.design_spec = result.strip()

    # Extract discovery_notes JSON from the design spec if present
    # The spec ends with a JSON block under "### Discovery Notes"
    disc_json = _try_parse_json(result)
    if disc_json and "mvp_features" in disc_json:
        state.discovery_notes = disc_json
    else:
        # Try to find a JSON block at the end of the spec
        lines = result.strip().split("\n")
        json_start = None
        for i, line in enumerate(lines):
            if "```json" in line or (line.strip().startswith("{") and i > len(lines) // 2):
                json_start = i
                break
        if json_start is not None:
            json_block = "\n".join(lines[json_start:])
            # Strip ```json fence if present
            json_block = json_block.replace("```json", "").replace("```", "").strip()
            disc = _try_parse_json(json_block)
            if disc and "mvp_features" in disc:
                state.discovery_notes = disc

    logger.info("Phase 4 complete: design spec %d chars, discovery_notes=%s",
                len(state.design_spec), list(state.discovery_notes.keys()) if state.discovery_notes else "none")
    return state


async def _phase5_build_plan(state: DemoState) -> DemoState:
    """Phase 5: Create a numbered build plan with functional acceptance criteria."""
    logger.info("Phase 5: Build Plan")

    result = await chat_completion_async(
        messages=[
            {"role": "system", "content": PHASE_PLAN_SYSTEM},
            {"role": "user", "content": f"## Design Specification\n\n{state.design_spec}"},
        ],
        model=_resolve_model(),
        temperature=0.2,
        max_tokens=4000,
        timeout=120.0,
    )

    parsed = _try_parse_json(result)
    if parsed and "steps" in parsed:
        state.build_plan = parsed
        # Extract complexity metadata
        state.complexity_score = parsed.get("complexity_score", 0)
        state.complexity_breakdown = parsed.get("complexity_breakdown", {})
    else:
        # Fallback: create a minimal 3-step plan
        state.build_plan = {
            "steps": [
                {
                    "number": 1,
                    "title": "HTML skeleton and navigation",
                    "description": "Build the basic HTML structure with nav and placeholder sections for all screens",
                    "acceptance_criteria": "All screen sections exist as hidden divs, navigation has onclick handlers referencing switchView()",
                },
                {
                    "number": 2,
                    "title": "Implement all screens and interactions",
                    "description": "Build each screen with full content, forms, buttons, and JS handlers",
                    "acceptance_criteria": "All buttons have working onclick handlers, forms show feedback on submit, navigation switches views",
                },
                {
                    "number": 3,
                    "title": "Polish styling and transitions",
                    "description": "Add CSS transitions, responsive design, visual polish",
                    "acceptance_criteria": "View transitions use CSS fade/slide, layout is mobile responsive, colors and typography match design spec",
                },
            ]
        }
        state.complexity_score = 0
        state.complexity_breakdown = {}

    logger.info("Phase 5 complete: %d steps, complexity=%d",
                len(state.build_plan.get("steps", [])), state.complexity_score)
    return state


async def _phase6a_core_structure(
    state: DemoState,
    on_progress: Any = None,
) -> DemoState:
    """Phase 6a: Build the HTML skeleton — layout, navigation, view containers.

    Generates the DOM structure with all view sections and navigation switching
    logic. No forms, data, or animations yet.

    Uses BUILD_STRUCTURE_SYSTEM for focused generation.
    Each attempt has its own validate/fix loop (max 3 retries).
    Failure here means no HTML for subsequent sub-phases.
    """
    logger.info("Phase 6a: Core Structure & Navigation")

    max_attempts = 3
    current_html = ""

    # Acceptance criteria for structure: all views exist, nav switches correctly
    acceptance_criteria = (
        "All view/screen sections exist as <section> elements with unique IDs. "
        "Navigation has buttons with onclick handlers calling switchView(viewName). "
        "switchView() function exists and toggles visibility between sections. "
        "Default/first view is shown on page load. "
        "CSS :root variables defined. BEM-like class naming. Mobile responsive base layout."
    )

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Phase 6a: Generate attempt %d", attempt)
            if on_progress:
                await on_progress(
                    f"Attempt {attempt}/{max_attempts}: generating core structure…"
                )

            # If we have HTML from a previous attempt, use it; otherwise start fresh
            html_to_use = current_html if current_html else ""

            html = await _generate_html_impl(
                spec=state.design_spec,
                step_description=(
                    "Build the complete HTML skeleton: <!DOCTYPE html>, head with meta/title/fonts, "
                    "CSS with :root variables and layout, nav with all view buttons, "
                    "one <section> per view with placeholder content, "
                    "IIFE JS with switchView() and initialization."
                ),
                current_html=html_to_use,
                system_prompt=BUILD_STRUCTURE_SYSTEM,
            )

            # Guard: check the output actually looks like HTML
            if "<html" not in html.lower() and "<!doctype" not in html.lower():
                logger.warning("Phase 6a: Generate returned non-HTML, retrying")
                if on_progress:
                    await on_progress("Non-HTML output, retrying…")
                continue

            # Validate
            result = await _validate_html_impl(
                acceptance_criteria=acceptance_criteria,
                html=html,
            )

            parsed = _try_parse_json(result)
            passed = parsed.get("passed", False) if parsed else False

            if passed:
                logger.info("Phase 6a: PASSED on attempt %d", attempt)
                if on_progress:
                    await on_progress(f"Validation passed on attempt {attempt}!")
                current_html = html
                break

            # Fix loop (max 1 fix per attempt)
            if attempt < max_attempts:
                issues = parsed.get("issues", []) if parsed else [result]
                logger.info("Phase 6a: Fix attempt for score", attempt)
                if on_progress:
                    await on_progress(f"Fixing issues ({len(issues)} found)…")
                try:
                    html = await _fix_html_impl(
                        issues=json.dumps(issues, indent=2) if isinstance(issues, list) else str(issues),
                        html=html,
                    )
                    current_html = html
                except Exception as e:
                    logger.exception("Phase 6a: fix_html failed: %s", e)
                    if on_progress:
                        await on_progress(f"Fix failed: {e}")
                    current_html = html  # keep what we had

        except Exception as e:
            logger.exception("Phase 6a: Generate attempt %d failed: %s", attempt, e)
            if on_progress:
                await on_progress(f"Attempt {attempt} failed: {e}")
            if attempt < max_attempts:
                continue

    if not current_html:
        raise RuntimeError(
            "Phase 6a failed: could not generate a valid HTML skeleton after 3 attempts. "
            "The design spec may be too vague or the model may need a more specific prompt."
        )

    state.current_html = current_html
    logger.info("Phase 6a complete: HTML is %d chars", len(current_html))
    return state


async def _phase6b_interactive_features(
    state: DemoState,
    on_progress: Any = None,
) -> DemoState:
    """Phase 6b: Add interactive features — forms, data, state management.

    Takes the skeleton from 6a and adds forms, data displays, sample data,
    and state management. Does NOT modify existing nav or add animations.

    Uses BUILD_FEATURES_SYSTEM for focused generation.
    Each attempt has its own validate/fix loop (max 3 retries).
    Failure here keeps the skeleton from 6a intact.
    """
    logger.info("Phase 6b: Interactive Features & Data")

    max_attempts = 3
    html = state.current_html  # start from 6a's output

    # Acceptance criteria for features: forms work, data is realistic, handlers exist
    acceptance_criteria = (
        "Forms have input validation and submit handlers showing success/error feedback. "
        "Data displays (tables, lists, cards) contain realistic sample data, not Lorem ipsum. "
        "All interactive elements (buttons, inputs, selects) have event handlers. "
        "State management works (add/delete/edit data items). "
        "Existing navigation and view-switching is preserved and functional."
    )

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Phase 6b: Generate attempt %d", attempt)
            if on_progress:
                await on_progress(
                    f"Attempt {attempt}/{max_attempts}: adding interactive features…"
                )

            current_to_pass = html if html else ""

            html = await _generate_html_impl(
                spec=state.design_spec,
                step_description=(
                    "Add interactive features to the existing HTML skeleton: "
                    "forms with validation and submit feedback, data displays with realistic sample data, "
                    "add/delete/edit operations, search/filter functionality. "
                    "PRESERVE existing nav, switchView(), and CSS. APPEND new code with comments."
                ),
                current_html=current_to_pass,
                system_prompt=BUILD_FEATURES_SYSTEM,
            )

            # Guard: check the output actually looks like HTML
            if "<html" not in html.lower() and "<!doctype" not in html.lower():
                logger.warning("Phase 6b: Generate returned non-HTML, retrying")
                if on_progress:
                    await on_progress("Non-HTML output, falling back…")
                # Fall back to previous HTML to try again
                html = state.current_html
                continue

            # Validate
            result = await _validate_html_impl(
                acceptance_criteria=acceptance_criteria,
                html=html,
            )

            parsed = _try_parse_json(result)
            passed = parsed.get("passed", False) if parsed else False

            if passed:
                logger.info("Phase 6b: PASSED on attempt %d", attempt)
                if on_progress:
                    await on_progress(f"Validation passed on attempt {attempt}!")
                state.current_html = html
                break

            # Fix loop (max 1 fix per attempt)
            if attempt < max_attempts:
                issues = parsed.get("issues", []) if parsed else [result]
                logger.info("Phase 6b: Fix attempt", attempt)
                if on_progress:
                    await on_progress(f"Fixing issues ({len(issues)} found)…")
                try:
                    html = await _fix_html_impl(
                        issues=json.dumps(issues, indent=2) if isinstance(issues, list) else str(issues),
                        html=html,
                    )
                except Exception as e:
                    logger.exception("Phase 6b: fix_html failed: %s", e)
                    if on_progress:
                        await on_progress(f"Fix failed: {e}")
                    # Fall back to 6a HTML
                    html = state.current_html

        except Exception as e:
            logger.exception("Phase 6b: Generate attempt %d failed: %s", attempt, e)
            if on_progress:
                await on_progress(f"Attempt {attempt} failed: {e}")
            # Fall back to 6a HTML
            html = state.current_html

    # If we never improved past 6a, keep 6a's output
    state.current_html = html if html else state.current_html
    logger.info("Phase 6b complete: HTML is %d chars", len(state.current_html))
    return state


async def _phase6c_polish(
    state: DemoState,
    on_progress: Any = None,
) -> DemoState:
    """Phase 6c: Add visual polish — transitions, active states, edge cases.

    Takes the feature-complete HTML from 6b and adds CSS transitions,
    active/hover states, feedback UI (toasts), empty states, and loading indicators.

    Uses BUILD_POLISH_SYSTEM for focused generation.
    Each attempt has its own validate/fix loop (max 3 retries).
    Failure here keeps the feature-complete HTML from 6a+6b intact.
    """
    logger.info("Phase 6c: Polish & Micro-interactions")

    max_attempts = 3
    html = state.current_html  # start from 6b's output (or 6a if 6b failed)

    # Acceptance criteria for polish: transitions exist, active states, feedback UI
    acceptance_criteria = (
        "View transitions use CSS (fade, slide) not instant switches. "
        "Navigation has active/hover/focus states with visual distinction. "
        "Feedback UI exists (toast notifications, inline success/error messages). "
        "Empty states show helpful messages when data lists are empty. "
        "Existing functionality (nav, forms, data) is preserved and still works."
    )

    for attempt in range(1, max_attempts + 1):
        try:
            logger.info("Phase 6c: Generate attempt %d", attempt)
            if on_progress:
                await on_progress(
                    f"Attempt {attempt}/{max_attempts}: adding visual polish…"
                )

            current_to_pass = html if html else ""

            html = await _generate_html_impl(
                spec=state.design_spec,
                step_description=(
                    "Add visual polish to the existing demo: CSS transitions on view switches, "
                    "active/hover/focus states on nav and buttons, toast notifications for feedback, "
                    "empty state messages for data lists, loading indicators, "
                    "micro-interactions (button press effects, smooth toggles). "
                    "PRESERVE all existing HTML structure, JS functions, and data logic. "
                    "APPEND new CSS/JS with Polish comments."
                ),
                current_html=current_to_pass,
                system_prompt=BUILD_POLISH_SYSTEM,
            )

            # Guard: check the output actually looks like HTML
            if "<html" not in html.lower() and "<!doctype" not in html.lower():
                logger.warning("Phase 6c: Generate returned non-HTML, retrying")
                if on_progress:
                    await on_progress("Non-HTML output, falling back…")
                # Fall back to previous HTML
                html = state.current_html
                continue

            # Validate
            result = await _validate_html_impl(
                acceptance_criteria=acceptance_criteria,
                html=html,
            )

            parsed = _try_parse_json(result)
            passed = parsed.get("passed", False) if parsed else False

            if passed:
                logger.info("Phase 6c: PASSED on attempt %d", attempt)
                if on_progress:
                    await on_progress(f"Validation passed on attempt {attempt}!")
                state.current_html = html
                break

            # Fix loop (max 1 fix per attempt)
            if attempt < max_attempts:
                issues = parsed.get("issues", []) if parsed else [result]
                logger.info("Phase 6c: Fix attempt", attempt)
                if on_progress:
                    await on_progress(f"Fixing issues ({len(issues)} found)…")
                try:
                    html = await _fix_html_impl(
                        issues=json.dumps(issues, indent=2) if isinstance(issues, list) else str(issues),
                        html=html,
                    )
                except Exception as e:
                    logger.exception("Phase 6c: fix_html failed: %s", e)
                    if on_progress:
                        await on_progress(f"Fix failed: {e}")
                    # Fall back to previous HTML
                    html = state.current_html

        except Exception as e:
            logger.exception("Phase 6c: Generate attempt %d failed: %s", attempt, e)
            if on_progress:
                await on_progress(f"Attempt {attempt} failed: {e}")
            # Fall back to previous HTML
            html = state.current_html

    # If we never improved, keep the previous HTML (from 6a+6b)
    state.current_html = html if html else state.current_html
    logger.info("Phase 6c complete: HTML is %d chars", len(state.current_html))
    return state


async def _phase7_verification(
    state: DemoState,
    on_progress: Any = None,
) -> DemoState:
    """Phase 7: Functional verification — analyze interactivity and fix issues."""
    logger.info("Phase 7: Functional Verification")

    max_attempts = 3
    html = state.current_html

    # Edge case: empty HTML — nothing to verify
    if not html or "<html" not in html.lower():
        logger.warning("Phase 7: No valid HTML to verify, skipping verification")
        state.verification_results = {
            "passed": False,
            "score": 0,
            "issues": ["No valid HTML produced by build phase"],
            "_warning": "Verification skipped due to missing HTML",
        }
        return state

    for attempt in range(1, max_attempts + 1):
        try:
            if on_progress:
                await on_progress(f"Verification attempt {attempt}/{max_attempts}…")
            result = await _verify_interactivity_impl(html=html)
        except Exception as e:
            logger.exception("Phase 7: verify_interactivity failed on attempt %d: %s", attempt, e)
            if on_progress:
                await on_progress(f"Verification error: {e}")
            if attempt < max_attempts:
                continue  # retry
            # All retries failed
            state.verification_results = {
                "passed": False,
                "score": 0,
                "issues": [f"Verification tool failed: {e}"],
                "_warning": "Verification tool unavailable, proceeding without verification",
            }
            return state

        parsed = _try_parse_json(result)

        if parsed is None:
            parsed = {"passed": False, "score": 0, "issues": ["Parse error in verification output"]}

        score = parsed.get("score", 0)
        logger.info("Phase 7: Verification attempt %d, score=%d", attempt, score)
        if on_progress:
            await on_progress(f"Score: {score}/10")

        if score >= 7:
            state.verification_results = parsed
            state.current_html = html
            logger.info("Phase 7 complete: PASSED (score=%d)", score)
            return state

        # Score < 7: attempt fix
        if attempt < max_attempts:
            issues = parsed.get("issues", [])
            recommendations = parsed.get("recommendations", [])
            all_issues = issues + recommendations

            try:
                logger.info("Phase 7: Fix attempt %d/%d for score %d", attempt, max_attempts - 1, score)
                if on_progress:
                    await on_progress(f"Fixing {len(all_issues)} issue(s)…")
                html = await _fix_html_impl(
                    issues=json.dumps(all_issues, indent=2),
                    html=html,
                )
            except Exception as e:
                logger.exception("Phase 7: fix_html failed on attempt %d: %s", attempt, e)
                if on_progress:
                    await on_progress(f"Fix failed: {e}")
                # Try to continue with the same HTML
                continue

    # After max attempts, save whatever we have
    state.verification_results = parsed
    state.current_html = html
    state.verification_results["_warning"] = (
        "Verification score < 7 after 3 fix attempts. "
        "This demo may be too complex for a 1-page clickable demo."
    )
    logger.warning("Phase 7 complete: score=%d (below threshold, proceeding with warnings)",
                    parsed.get("score", 0))
    return state
async def _phase8_polish(
    state: DemoState,
    on_progress: Any = None,
) -> DemoState:
    """Phase 8: Polish & self-critique with optional fixes."""
    logger.info("Phase 8: Polish & Critique")

    # Edge case: no HTML to critique
    if not state.current_html or "<html" not in state.current_html.lower():
        logger.warning("Phase 8: No valid HTML to critique, skipping polish")
        state.critique_results = {
            "overall_score": 0,
            "issues_found": ["No valid HTML to critique"],
            "strengths": [],
        }
        state.final_html = state.current_html
        return state

    try:
        if on_progress:
            await on_progress("Running critique…")
        result = await _critique_demo_impl(
            design_spec=state.design_spec,
            html=state.current_html,
        )
    except Exception as e:
        logger.exception("Phase 8: critique_demo failed: %s", e)
        if on_progress:
            await on_progress(f"Critique failed: {e}")
        state.critique_results = {
            "overall_score": 0,
            "issues_found": [f"Critique tool failed: {e}"],
            "strengths": [],
        }
        state.final_html = state.current_html
        return state

    parsed = _try_parse_json(result)
    if parsed is None:
        parsed = {"overall_score": 5, "issues_found": ["Could not parse critique output"], "strengths": []}

    state.critique_results = parsed
    logger.info("Phase 8: Critique score=%d", parsed.get("overall_score", 0))

    # If there are fixable issues, attempt one fix pass
    issues = parsed.get("issues_found", [])
    if issues and parsed.get("overall_score", 10) < 8:
        logger.info("Phase 8: Applying critique fixes (%d issues)", len(issues))
        if on_progress:
            await on_progress(f"Applying {len(issues)} critique fix(es)…")
        try:
            state.current_html = await _fix_html_impl(
                issues=json.dumps(issues, indent=2),
                html=state.current_html,
            )
        except Exception as e:
            logger.exception("Phase 8: fix_html failed during polish: %s", e)
            if on_progress:
                await on_progress(f"Polish fix failed: {e}")
            # Keep existing HTML

    state.final_html = state.current_html
    logger.info("Phase 8 complete")
    return state
async def _phase9_save(state: DemoState) -> DemoState:
    """Phase 9: Save the final demo with metadata."""
    logger.info("Phase 9: Save Final Demo")

    # Merge verification + critique results for comprehensive metadata
    ver_data = dict(state.verification_results) if state.verification_results else {}
    if state.critique_results:
        ver_data["level3_realism_score"] = state.critique_results.get("level3_realism_score", 0)

    ver_json = json.dumps(ver_data)

    # Merge discovery + complexity metadata
    discovery_json = json.dumps({
        "discovery_notes": state.discovery_notes,
        "complexity_score": state.complexity_score,
        "complexity_breakdown": state.complexity_breakdown,
    })

    result = _save_demo_impl(
        title=state.title or "Untitled Demo",
        html=state.final_html,
        design_spec=state.design_spec,
        notes=f"Built via coordinator pattern. Verification score: {state.verification_results.get('score', 'N/A')}. "
              f"Critique score: {state.critique_results.get('overall_score', 'N/A')}. "
              f"Level 3 realism: {state.critique_results.get('level3_realism_score', 'N/A')}. "
              f"Complexity: {state.complexity_score}/10.",
        verification_results=ver_json,
        discovery_metadata=discovery_json,
    )

    parsed = _try_parse_json(result)
    if parsed:
        state.metadata = parsed
    else:
        state.metadata = {"title": state.title, "error": "Could not parse save_demo output"}

    logger.info("Phase 9 complete: %s", result[:200])
    return state


# ---------------------------------------------------------------------------
# Public service entrypoint — coordinator pattern
# ---------------------------------------------------------------------------

async def run_demo(req: DemoCreateRequest, resume_phase: int = 0) -> DemoCreateResponse:
    """Run the demo creation pipeline using the coordinator pattern.

    Each phase runs as a separate short-lived LLM invocation, passing
    structured JSON state between phases. This avoids the 70K context
    window limit of the vLLM backend.

    Args:
        req: The demo creation request.
        resume_phase: If > 0, skip to this phase index (0-based) for resumption.

    Returns:
        DemoCreateResponse with results.
    """
    thread_id = req.thread_id or str(uuid.uuid4())
    resumed_from = 0

    # Check for existing checkpoint
    checkpoint = CheckpointManager.load(thread_id)
    if checkpoint and resume_phase == 0:
        state, resume_phase = checkpoint
        resumed_from = resume_phase
        logger.info("Resuming demo from checkpoint: thread=%s phase=%d (%s)",
                    thread_id, resume_phase, PHASE_NAMES[resume_phase] if resume_phase < len(PHASE_NAMES) else "unknown")
    else:
        # Initialize fresh state
        state = DemoState(
            raw_prompt=req.prompt,
            thread_id=thread_id,
            title=req.title,
        )
        if resume_phase > 0:
            # Explicit resume request — skip to the given phase
            logger.info("Resuming demo from phase %d (explicit request)", resume_phase)
        else:
            resume_from = 0

    phases = [
        ("Phase 1: Parse Request", _phase1_parse_request),
        ("Phase 2: KB Lookup", _phase2_kb_lookup),
        ("Phase 3: Web Research", _phase3_web_research),
        ("Phase 4: Requirements & Design", _phase4_design),
        ("Phase 5: Build Plan", _phase5_build_plan),
        ("Phase 6a: Core Structure", _phase6a_core_structure),
        ("Phase 6b: Interactive Features", _phase6b_interactive_features),
        ("Phase 6c: Polish & Micro-interactions", _phase6c_polish),
        ("Phase 7: Functional Verification", _phase7_verification),
        ("Phase 8: Polish & Critique", _phase8_polish),
        ("Phase 9: Save Final", _phase9_save),
    ]

    # Timing instrumentation for performance benchmarking
    pipeline_start = time.time()
    phase_timings: dict[str, float] = {}

    # If resuming, record skipped phases as 0s timing
    for i in range(resume_phase):
        if i < len(phases):
            phase_timings[phases[i][0]] = 0.0

    for idx, (phase_name, phase_fn) in enumerate(phases):
        # Skip phases before the resume point
        if idx < resume_phase:
            continue

        phase_start = time.time()
        try:
            logger.info("── Starting %s (thread=%s) ──", phase_name, thread_id)
            state = await phase_fn(state)
            elapsed = time.time() - phase_start
            phase_timings[phase_name] = elapsed
            logger.info("── Completed %s in %.1fs ──", phase_name, elapsed)

            # Save checkpoint after each completed phase
            CheckpointManager.save(thread_id, state, idx)

        except Exception as e:
            elapsed = time.time() - phase_start
            phase_timings[phase_name] = elapsed
            logger.exception("Phase %s failed after %.1fs: %s", phase_name, elapsed, e)
            # Save checkpoint even on failure so we can resume from here
            CheckpointManager.save(thread_id, state, idx)
            return DemoBuildError(
                thread_id=thread_id,
                title=state.title or req.title or "Untitled Demo",
                slug=_make_slug(state.title or req.title or "Untitled Demo"),
                status="error",
                error=f"{phase_name} failed: {e}",
            )

    total_elapsed = time.time() - pipeline_start
    logger.info("Pipeline complete in %.1fs (thread=%s): %s",
                total_elapsed, thread_id,
                ", ".join(f"{k}={v:.1f}s" for k, v in phase_timings.items() if v > 0))

    # Remove checkpoint on successful completion
    CheckpointManager.remove(thread_id)

    # Build response
    slug = state.metadata.get("slug", _make_slug(state.title))
    html_path = state.metadata.get("html_path", "")

    if not state.final_html and not html_path:
        return DemoBuildError(
            thread_id=thread_id,
            title=state.title,
            slug=slug,
            status="error",
            error="Pipeline completed but no HTML was produced. "
                  "This may indicate a model capability issue.",
        )

    # Enrich metadata with timing data
    state.metadata.setdefault("phase_timings", phase_timings)
    state.metadata["total_build_time_seconds"] = round(total_elapsed, 1)

    return DemoCreateResponse(
        thread_id=thread_id,
        title=state.title,
        slug=slug,
        status="completed" if resumed_from == 0 else "resumed",
        build_step="final_save",
        html_path=html_path,
        metadata=state.metadata,
    )


def _make_slug(title: str) -> str:
    """Generate a filesystem slug from a title."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).lower().strip("-")
    if len(slug) > 60:
        slug = slug[:60]
    return f"{slug}-{datetime.now().strftime('%Y%m%d%H%M')}"


# ---------------------------------------------------------------------------
# Resume helpers
# ---------------------------------------------------------------------------

async def resume_demo(thread_id: str) -> DemoCreateResponse:
    """Resume a demo pipeline from a saved checkpoint.

    Loads the checkpoint for the given thread_id and continues from the
    phase after the last saved one. If no checkpoint exists or it is
    expired, returns an error response.
    """
    checkpoint = CheckpointManager.load(thread_id)
    if checkpoint is None:
        return DemoBuildError(
            thread_id=thread_id,
            title="",
            slug=thread_id,
            status="error",
            error=f"No valid checkpoint found for thread '{thread_id}'. "
                  "The checkpoint may have expired (24h TTL) or was never saved.",
        )

    state, resume_phase = checkpoint
    if resume_phase >= len(PHASE_NAMES):
        # Already completed all phases — just remove the stale checkpoint
        CheckpointManager.remove(thread_id)
        return DemoBuildError(
            thread_id=thread_id,
            title=state.title,
            slug=_make_slug(state.title),
            status="error",
            error="Checkpoint indicates all phases already completed. This should have been cleaned up.",
        )

    # Build a minimal request (prompt is already in state)
    req = DemoCreateRequest(
        prompt=state.raw_prompt,
        title=state.title,
        thread_id=thread_id,
    )

    return await run_demo(req, resume_phase=resume_phase)


def get_checkpoint_status(thread_id: str) -> DemoCheckpointStatus:
    """Get the checkpoint status for a thread (or return not-found)."""
    status = CheckpointManager.get_status(thread_id)
    return status if status else DemoCheckpointStatus(thread_id=thread_id, exists=False)


def remove_checkpoint(thread_id: str) -> dict:
    """Remove a checkpoint for a thread. Returns status dict."""
    path = CheckpointManager._checkpoint_path(thread_id)
    existed = path.exists()
    CheckpointManager.remove(thread_id)
    return {
        "thread_id": thread_id,
        "removed": existed,
        "message": "Checkpoint removed" if existed else "No checkpoint found",
    }


# ---------------------------------------------------------------------------
# SSE Streaming — coordinator pipeline with real-time progress events
# ---------------------------------------------------------------------------

def _format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as m:ss (e.g. '0:42', '12:34')."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


async def _run_demo_with_events(
    req: DemoCreateRequest,
) -> DemoStreamEvent:
    """Run the demo pipeline yielding SSE events for real-time progress.

    This is the streaming counterpart to run_demo(). It runs the same
    per-phase coordinator pipeline but yields DemoStreamEvent objects
    at phase boundaries and during long-running build phases.

    Unlike run_demo(), this does NOT save checkpoints — it is ephemeral
    and designed for live SSE connections (e.g. OpenWebUI).

    Yields:
        DemoStreamEvent objects with event_type in:
        pipeline_start, pipeline_resume, phase_start, phase_progress,
        phase_complete, pipeline_complete, error.
    """
    thread_id = req.thread_id or str(uuid.uuid4())
    pipeline_start = time.time()

    # Check for existing checkpoint (for resume support)
    checkpoint = CheckpointManager.load(thread_id)
    if checkpoint:
        state, resume_phase = checkpoint
        yield DemoStreamEvent(
            event_type="pipeline_resume",
            elapsed=_format_elapsed(time.time() - pipeline_start),
            data={
                "thread_id": thread_id,
                "title": state.title,
                "prompt": state.raw_prompt,
                "resume_from_phase": resume_phase,
                "resume_phase_name": PHASE_NAMES[resume_phase] if resume_phase < len(PHASE_NAMES) else "unknown",
            },
        )
    else:
        state = DemoState(
            raw_prompt=req.prompt,
            thread_id=thread_id,
            title=req.title,
        )
        resume_phase = 0
        yield DemoStreamEvent(
            event_type="pipeline_start",
            elapsed=_format_elapsed(time.time() - pipeline_start),
            data={
                "thread_id": thread_id,
                "title": state.title,
                "prompt": state.raw_prompt,
            },
        )

    phases = [
        ("Phase 1: Parse Request", _phase1_parse_request),
        ("Phase 2: KB Lookup", _phase2_kb_lookup),
        ("Phase 3: Web Research", _phase3_web_research),
        ("Phase 4: Requirements & Design", _phase4_design),
        ("Phase 5: Build Plan", _phase5_build_plan),
        ("Phase 6a: Core Structure", _phase6a_core_structure),
        ("Phase 6b: Interactive Features", _phase6b_interactive_features),
        ("Phase 6c: Polish & Micro-interactions", _phase6c_polish),
        ("Phase 7: Functional Verification", _phase7_verification),
        ("Phase 8: Polish & Critique", _phase8_polish),
        ("Phase 9: Save Final", _phase9_save),
    ]

    # Collect metadata for final event (mirrors run_demo timing logic)
    phase_timings: dict[str, float] = {}
    for i in range(resume_phase):
        if i < len(phases):
            phase_timings[phases[i][0]] = 0.0

    for idx, (phase_name, phase_fn) in enumerate(phases):
        if idx < resume_phase:
            continue

        # ── Phase start event ──────────────────────────────────────
        yield DemoStreamEvent(
            event_type="phase_start",
            phase=phase_name,
            phase_number=idx,
            elapsed=_format_elapsed(time.time() - pipeline_start),
            data={"phase_index": idx},
        )

        phase_start = time.time()

        # Collect progress messages during phase execution, then yield
        # after the phase completes (can't yield from a callback).
        progress_msgs: list[str] = []

        async def _collect_progress(msg: str):
            progress_msgs.append(msg)

        try:
            state = await phase_fn(state, on_progress=_collect_progress)
            elapsed = time.time() - phase_start
            phase_timings[phase_name] = elapsed

            # ── Yield any collected progress messages ──────────────
            for msg in progress_msgs:
                yield DemoStreamEvent(
                    event_type="phase_progress",
                    phase=phase_name,
                    phase_number=idx,
                    elapsed=_format_elapsed(time.time() - pipeline_start),
                    data={"message": msg},
                )

            # ── Phase complete event ───────────────────────────────
            summary = ""
            if idx == 0:
                summary = f"Title: {state.title}"
            elif idx == 3:
                summary = f"Design spec: {len(state.design_spec)} chars"
            elif idx == 4:
                summary = f"{len(state.build_plan.get('steps', []))} steps, complexity={state.complexity_score}"
            elif idx in (5, 6, 7):
                summary = f"HTML: {len(state.current_html)} chars"
            elif idx == 8:
                score = state.verification_results.get('score', '?')
                summary = f"Score: {score}/10"
            elif idx == 9:
                score = state.critique_results.get('overall_score', '?')
                summary = f"Score: {score}/10"
            elif idx == 10:
                summary = f"Saved to: {state.metadata.get('slug', '?')}"

            yield DemoStreamEvent(
                event_type="phase_complete",
                phase=phase_name,
                phase_number=idx,
                elapsed=_format_elapsed(time.time() - pipeline_start),
                data={"summary": summary, "phase_elapsed": round(elapsed, 1)},
            )

        except Exception as e:
            elapsed = time.time() - phase_start
            phase_timings[phase_name] = elapsed

            # Yield any progress collected before the error
            for msg in progress_msgs:
                yield DemoStreamEvent(
                    event_type="phase_progress",
                    phase=phase_name,
                    phase_number=idx,
                    elapsed=_format_elapsed(time.time() - pipeline_start),
                    data={"message": msg},
                )

            yield DemoStreamEvent(
                event_type="error",
                phase=phase_name,
                phase_number=idx,
                elapsed=_format_elapsed(time.time() - pipeline_start),
                data={"error": str(e), "phase_elapsed": round(elapsed, 1)},
            )

            yield DemoStreamEvent(
                event_type="pipeline_complete",
                elapsed=_format_elapsed(time.time() - pipeline_start),
                data={
                    "status": "error",
                    "error": str(e),
                    "thread_id": thread_id,
                    "phase_timings": phase_timings,
                    "total_build_time_seconds": round(time.time() - pipeline_start, 1),
                },
            )
            return

    # ── Pipeline complete (success) ────────────────────────────────
    total_elapsed = time.time() - pipeline_start
    slug = state.metadata.get("slug", _make_slug(state.title))
    html_path = state.metadata.get("html_path", "")

    state.metadata.setdefault("phase_timings", phase_timings)
    state.metadata["total_build_time_seconds"] = round(total_elapsed, 1)

    yield DemoStreamEvent(
        event_type="pipeline_complete",
        elapsed=_format_elapsed(total_elapsed),
        data={
            "status": "completed",
            "thread_id": thread_id,
            "title": state.title,
            "slug": slug,
            "html_path": html_path,
            "metadata": state.metadata,
            "phase_timings": phase_timings,
            "total_build_time_seconds": round(total_elapsed, 1),
        },
    )


# ---------------------------------------------------------------------------
# Legacy extraction helpers — kept for streaming endpoint backward compat
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
    """Extract slug from demo_brief content or generate from title."""
    title = _extract_title(messages, "")
    if title:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).lower().strip("-")
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
