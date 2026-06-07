"""
One-page clickable demo workflow service.

Implements all pipeline stages:
  1. Parse Request
  2. KB Lookup
  3. Web Research
  4. Requirements & Design Spec
  5. Build Plan
  6-N. Build Loop (dynamic per build-step)
  N+1. Polish & Self-Critique
  N+2. Embed Notes & Save Final

Each stage reads from and writes to DemoPipelineState persisted on disk.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from core.config import MEDIA_OUTPUT_DIR, INTERNAL_BASE_URL, PUBLIC_BASE_URL
from core.llm import chat_completion_sync
from family_kb.service import search_kb
from family_kb.schemas import SearchRequest

from demo_workflow.prompts import (
    PROMPT_PARSE_REQUEST,
    PROMPT_KB_INSIGHTS,
    PROMPT_WEB_RESEARCH_QUERIES,
    PROMPT_WEB_RESEARCH_SUMMARIZE,
    PROMPT_REQUIREMENTS_DESIGN,
    PROMPT_BUILD_PLAN,
    PROMPT_BUILD_GENERATE,
    PROMPT_BUILD_VALIDATE,
    PROMPT_BUILD_FIX,
    PROMPT_POLISH_CRITIQUE,
    PROMPT_POLISH_FIX,
    PROMPT_GENERATE_NOTES,
)
from demo_workflow.schemas import (
    DemoBrief,
    KbInsightItem,
    KbInsights,
    WebSearchResult,
    WebInsights,
    RequirementsAndDesignSpec,
    BuildPlan,
    BuildStep,
    BuildStepResult,
    PolishResult,
    FinalSaveResult,
    DemoPipelineState,
    DemoMetadata,
)

logger = logging.getLogger(__name__)

# ─────── Helper: directory management ──


def _demo_dir(slug: str) -> Path:
    """Return the per-demo output directory."""
    base = Path(MEDIA_OUTPUT_DIR) / "demos" / slug
    base.mkdir(parents=True, exist_ok=True)
    return base


def _build_dir(slug: str) -> Path:
    """Return the intermediate build directory."""
    d = _demo_dir(slug) / "build"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_dir(slug: str) -> Path:
    """Return the state JSON directory."""
    d = _demo_dir(slug) / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─────── Helper: slug generation ──


def _make_slug(title: str, date_stamp: str | None = None) -> str:
    """Create a filesystem-safe slug from a title."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).lower().strip("-")
    if len(slug) > 60:
        slug = slug[:60]
    ds = date_stamp or datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    return f"{slug}-{ds}"


# ─────── Helper: state persistence ──


def save_state(state: DemoPipelineState) -> str:
    """Persist pipeline state to disk under the demo's state directory."""
    if not state.slug:
        return ""
    sd = _state_dir(state.slug)
    fp = sd / "state_snapshot.json"
    dump = state.model_dump()
    fp.write_text(json.dumps(dump, indent=2, default=str), encoding="utf-8")
    return str(fp)


def load_state(slug: str) -> DemoPipelineState:
    """Load pipeline state from disk."""
    sd = _state_dir(slug)
    fp = sd / "state_snapshot.json"
    if not fp.exists():
        raise FileNotFoundError(f"State file not found: {fp}")
    data = json.loads(fp.read_text())
    return DemoPipelineState(**data)


def save_stage_json(slug: str, stage_name: str, data: Any) -> str:
    """Save a stage's output as a separate JSON file."""
    sd = _state_dir(slug)
    fp = sd / f"stage_{stage_name}.json"
    fp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return str(fp)


# ─────── Helper: LLM JSON extraction ──


def _extract_json(text: str) -> dict | list:
    """Best-effort JSON extraction from LLM output (handles ``` fences, <json> tags)."""
    text = text.strip()

    # Strip code fences
    for prefix in ["```json", "```html", "```"]:
        if text.startswith(prefix):
            text = text.removeprefix(prefix).strip()
    if text.endswith("```"):
        text = text.removesuffix("```").strip()

    # Strip <json> tags
    if "<json>" in text:
        text = text.split("<json>")[1].split("</json>")[0].strip()

    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Find first { ... } or [ ... ]
    for open_c, close_c in [("{", "}"), ("[", "]")]:
        s = text.find(open_c)
        e = text.rfind(close_c) + 1
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e])
            except (json.JSONDecodeError, ValueError):
                pass

    raise ValueError(f"Could not parse JSON from response ({len(text)} chars)")


def _call_llm(prompt: str, temperature: float = 0.2,
              max_tokens: int | None = None) -> str:
    """Call the LLM synchronously and return raw text."""
    return chat_completion_sync(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )


def _call_json(prompt: str, temperature: float = 0.2,
               max_tokens: int | None = None) -> dict:
    """Call the LLM and return parsed JSON dict."""
    raw = _call_llm(prompt, temperature=temperature, max_tokens=max_tokens)
    return _extract_json(raw)


# ─────── Helper: strip HTML code fences ──


def _extract_html(text: str) -> str:
    """Extract clean HTML from LLM output, stripping code fences."""
    text = text.strip()

    # Strip code fences
    for prefix in ["```html", "```HTML", "```"]:
        if text.startswith(prefix):
            text = text.removeprefix(prefix).strip()
    if text.endswith("```"):
        text = text.removesuffix("```").strip()

    # If it looks like HTML, return as-is
    if "<!DOCTYPE" in text or "<html" in text.lower():
        return text

    # Try to find the HTML start
    doctype_pos = text.find("<!DOCTYPE")
    html_pos = text.find("<html")
    start = 0
    if doctype_pos > 0:
        start = doctype_pos
    elif html_pos > 0:
        start = html_pos

    if start > 0:
        return text[start:]

    return text


# ──────────────────────────────────────────────────────────────────
# STAGE 1 — Parse Request
# ──────────────────────────────────────────────────────────────────

def stage1_parse_request(state: DemoPipelineState) -> dict:
    """Parse the user request into a structured demo brief."""
    t0 = time.time()

    prompt = PROMPT_PARSE_REQUEST.format(
        title=state.title,
        prompt=state.prompt,
    )

    data = _call_json(prompt, temperature=0.2, max_tokens=1500)

    brief = DemoBrief(
        title=data.get("title", state.title),
        description=data.get("description", ""),
        target_audience=data.get("target_audience", ""),
        key_features=data.get("key_features", []),
        screens_requested=data.get("screens_requested", []),
        style_hints=data.get("style_hints", []),
        constraints=data.get("constraints", []),
    )

    state.demo_brief = brief
    state.title = brief.title
    state.slug = _make_slug(brief.title)

    # Save state and stage output
    save_state(state)
    save_stage_json(state.slug, "1_brief", brief.model_dump())

    logger.info("stage1 completed in %.1fs — slug=%s, %d features, %d screens",
                time.time() - t0, state.slug,
                len(brief.key_features), len(brief.screens_requested))
    return {
        "stage": "parse_request",
        "title": brief.title,
        "slug": state.slug,
        "features_count": len(brief.key_features),
        "screens_count": len(brief.screens_requested),
        "duration_s": round(time.time() - t0, 2),
    }


# ──────────────────────────────────────────────────────────────────
# STAGE 2 — KB Lookup
# ──────────────────────────────────────────────────────────────────

def stage2_kb_lookup(state: DemoPipelineState) -> dict:
    """Query the Family KB for relevant prior knowledge."""
    import threading
    t0 = time.time()

    # ── Hard 60s deadline covering embedding model cold download ──
    # SIGALRM won't interrupt blocking C-level I/O (HF download), so use threading
    result_holder: dict[str, Exception | dict] = {}

    class _KbTimeout(Exception):
        pass

    def _kb_worker():
        try:
            kb_results = search_kb(SearchRequest(
                query=state.demo_brief.description if state.demo_brief else state.prompt,
                limit=10,
            ))

            kb_text = json.dumps(kb_results, default=str)

            brief_summary = ""
            if state.demo_brief:
                brief_summary = (
                    f"Title: {state.demo_brief.title}\n"
                    f"Description: {state.demo_brief.description}\n"
                    f"Target Audience: {state.demo_brief.target_audience}"
                )

            prompt = PROMPT_KB_INSIGHTS.format(
                brief_summary=brief_summary,
                kb_results=kb_text,
            )

            data = _call_json(prompt, temperature=0.2, max_tokens=1000)

            items_raw = data.get("items", [])
            items = []
            for it in items_raw:
                if isinstance(it, dict):
                    items.append(KbInsightItem(source=it.get("source", ""), text=it.get("text", "")))

            result_holder["ok"] = {
                "query": state.demo_brief.description if state.demo_brief else state.prompt,
                "has_prior_data": data.get("has_prior_data", False),
                "insights": data.get("insights", "No relevant prior data found."),
                "items": items,
            }
        except Exception as exc:
            result_holder["exc"] = exc

    thread = threading.Thread(target=_kb_worker, daemon=True)
    thread.start()
    thread.join(timeout=60)  # hard 60s deadline

    if result_holder.get("ok") is not None:
        kb_insights_obj = KbInsights(**result_holder["ok"])
    elif thread.is_alive():
        logger.warning("KB lookup timed out after 60s — skipping to avoid blocking pipeline")
        kb_insights_obj = KbInsights(
            query=state.demo_brief.description if state.demo_brief else state.prompt,
            has_prior_data=False,
            insights="KB lookup timed out (embedding model not yet cached). Continuing without prior knowledge.",
            items=[],
        )
    else:
        exc = result_holder.get("exc")
        logger.warning("KB lookup failed (non-fatal): %s — continuing without prior knowledge", exc)
        kb_insights_obj = KbInsights(
            query=state.demo_brief.description if state.demo_brief else state.prompt,
            has_prior_data=False,
            insights="KB lookup failed due to embedding unavailability. Continuing without prior knowledge.",
            items=[],
        )

    state.kb_insights = kb_insights_obj
    save_state(state)
    save_stage_json(state.slug, "2_kb", kb_insights_obj.model_dump())

    logger.info("stage2 completed in %.1fs — has_prior_data=%s, %d items",
                time.time() - t0, kb_insights_obj.has_prior_data, len(kb_insights_obj.items))
    return {
        "stage": "kb_lookup",
        "has_prior_data": kb_insights_obj.has_prior_data,
        "items_count": len(kb_insights_obj.items),
        "duration_s": round(time.time() - t0, 2),
    }


# ──────────────────────────────────────────────────────────────────
# STAGE 3 — Web Research
# ──────────────────────────────────────────────────────────────────

def stage3_web_research(state: DemoPipelineState) -> dict:
    """Search the web for competitive and design insights."""
    t0 = time.time()

    brief_summary = ""
    if state.demo_brief:
        brief_summary = (
            f"Title: {state.demo_brief.title}\n"
            f"Description: {state.demo_brief.description}\n"
            f"Key Features: {', '.join(state.demo_brief.key_features)}\n"
            f"Screens: {', '.join(state.demo_brief.screens_requested)}"
        )

    # Step 3a: Generate search queries
    query_prompt = PROMPT_WEB_RESEARCH_QUERIES.format(brief_summary=brief_summary)
    queries_data = _call_json(query_prompt, temperature=0.5, max_tokens=800)
    queries: list[str] = queries_data if isinstance(queries_data, list) else queries_data.get("queries", [])

    if not queries:
        queries = [f"{state.title} app design", f"{state.title} similar products"]

    # Step 3b: Execute searches via SearXNG directly (sync, inside Celery)
    from core.config import SEARXNG_BASE_URL
    all_results: list[dict] = []
    try:
        for q in queries[:4]:
            params = {
                "q": q,
                "format": "json",
                "categories": "general",
                "language": "en",
                "pageno": 1,
                "safesearch": 1,
            }
            try:
                with httpx.Client(timeout=30.0) as client:
                    r = client.get(f"{SEARXNG_BASE_URL}/search", params=params)
                    r.raise_for_status()
                    data = r.json()
                    for item in data.get("results", [])[:5]:
                        url = item.get("url")
                        if url:
                            all_results.append({
                                "title": item.get("title", ""),
                                "url": url,
                                "content": item.get("content", ""),
                            })
            except Exception as exc:
                logger.warning("Search failed for '%s': %s", q, exc)
    except Exception as exc:
        logger.warning("Web research failed: %s", exc)

    search_text = json.dumps(all_results, default=str)[:12000]

    # Step 3c: Summarize findings
    summary_prompt = PROMPT_WEB_RESEARCH_SUMMARIZE.format(
        brief_summary=brief_summary,
        search_results=search_text,
    )

    data = _call_json(summary_prompt, temperature=0.2, max_tokens=2000)

    # Build structured insights
    web = WebInsights(
        queries_used=data.get("queries_used", queries),
        sources=[WebSearchResult(
            title=s.get("title", ""),
            url=s.get("url", ""),
            snippet=s.get("snippet", s.get("content", "")),
        ) for s in data.get("sources", [])],
        competitor_patterns=data.get("competitor_patterns", []),
        ux_patterns=data.get("ux_patterns", []),
        feature_recommendations=data.get("feature_recommendations", []),
        summary=data.get("summary", ""),
    )

    state.web_insights = web
    save_state(state)
    save_stage_json(state.slug, "3_web", web.model_dump())

    logger.info("stage3 completed in %.1fs — %d sources, %d competitor patterns",
                time.time() - t0, len(web.sources), len(web.competitor_patterns))
    return {
        "stage": "web_research",
        "queries_used": data.get("queries_used", []),
        "sources_count": len(web.sources),
        "competitor_patterns": len(web.competitor_patterns),
        "duration_s": round(time.time() - t0, 2),
    }


# ──────────────────────────────────────────────────────────────────
# STAGE 4 — Requirements & Design Spec
# ──────────────────────────────────────────────────────────────────

def stage4_requirements_design(state: DemoPipelineState) -> dict:
    """Synthesize research into requirements and a visual design spec."""
    t0 = time.time()

    brief = state.demo_brief
    kb_text = ""
    if state.kb_insights and state.kb_insights.has_prior_data:
        kb_text = f"KB Insights:\n{state.kb_insights.insights}"

    web_text = ""
    if state.web_insights:
        wi = state.web_insights
        web_text = (
            f"Competitor Patterns: {', '.join(wi.competitor_patterns)}\n"
            f"UX Patterns: {', '.join(wi.ux_patterns)}\n"
            f"Feature Recommendations: {', '.join(wi.feature_recommendations)}\n"
            f"Summary: {wi.summary}"
        )

    prompt = PROMPT_REQUIREMENTS_DESIGN.format(
        title=brief.title if brief else state.title,
        description=brief.description if brief else state.prompt,
        target_audience=brief.target_audience if brief else "",
        key_features=json.dumps(brief.key_features) if brief else "[]",
        screens=json.dumps(brief.screens_requested) if brief else "[]",
        style_hints=json.dumps(brief.style_hints) if brief else "[]",
        constraints=json.dumps(brief.constraints) if brief else "[]",
        kb_insights=kb_text or "No prior KB data.",
        web_insights=web_text or "No web research data.",
    )

    data = _call_json(prompt, temperature=0.4, max_tokens=3000)

    spec = RequirementsAndDesignSpec(
        requirements=data.get("requirements", []),
        screens=data.get("screens", []),
        navigation_flow=data.get("navigation_flow", ""),
        placeholder_data_guidance=data.get("placeholder_data_guidance", ""),
        interactions=data.get("interactions", []),
        color_palette=data.get("color_palette", ""),
        typography=data.get("typography", ""),
        layout_approach=data.get("layout_approach", ""),
        visual_treatment=data.get("visual_treatment", ""),
        design_notes=data.get("design_notes", ""),
    )

    state.requirements = spec
    save_state(state)
    save_stage_json(state.slug, "4_requirements", spec.model_dump())

    logger.info("stage4 completed in %.1fs — %d requirements, %d screens, %d interactions",
                time.time() - t0, len(spec.requirements), len(spec.screens),
                len(spec.interactions))
    return {
        "stage": "requirements_design",
        "requirements_count": len(spec.requirements),
        "screens_count": len(spec.screens),
        "interactions_count": len(spec.interactions),
        "duration_s": round(time.time() - t0, 2),
    }


# ──────────────────────────────────────────────────────────────────
# STAGE 5 — Build Plan
# ──────────────────────────────────────────────────────────────────

def stage5_build_plan(state: DemoPipelineState) -> dict:
    """Generate a numbered build plan from the requirements/design spec."""
    t0 = time.time()

    spec = state.requirements
    if spec is None:
        return {"error": "No requirements spec found; stage 4 must complete first."}

    spec_text = (
        f"Requirements:\n"
        f"{' '.join(f'- {r}' for r in spec.requirements)}\n\n"
        f"Screens: {', '.join(spec.screens)}\n"
        f"Navigation Flow: {spec.navigation_flow}\n"
        f"Interactions: {', '.join(spec.interactions)}\n"
        f"Color Palette: {spec.color_palette}\n"
        f"Typo: {spec.typography}\n"
        f"Layout: {spec.layout_approach}\n"
        f"Visual: {spec.visual_treatment}\n"
        f"Notes: {spec.design_notes}"
    )

    prompt = PROMPT_BUILD_PLAN.format(requirements_spec=spec_text)

    data = _call_json(prompt, temperature=0.3, max_tokens=2500)

    raw_steps = data.get("steps", [])
    steps = []
    for i, rs in enumerate(raw_steps, start=1):
        step = BuildStep(
            step_number=i,
            title=rs.get("title", f"Step {i}"),
            description=rs.get("description", ""),
            acceptance_criteria=rs.get("acceptance_criteria", ""),
            depends_on_step=rs.get("depends_on_step"),
        )
        steps.append(step)

    # Cap at 8 steps
    if len(steps) > 8:
        logger.warning("Build plan had %d steps, capped to 8", len(steps))
        steps = steps[:8]

    plan = BuildPlan(steps=steps, notes=data.get("notes", ""))

    state.build_plan = plan
    save_state(state)
    save_stage_json(state.slug, "5_build_plan", plan.model_dump())

    logger.info("stage5 completed in %.1fs — %d build steps",
                time.time() - t0, len(steps))
    return {
        "stage": "build_plan",
        "build_steps_count": len(steps),
        "steps": [{"number": s.step_number, "title": s.title} for s in steps],
        "duration_s": round(time.time() - t0, 2),
    }


# ──────────────────────────────────────────────────────────────────
# BUILD LOOP — Generate, Validate, Fix
# ──────────────────────────────────────────────────────────────────

MAX_BUILD_RETRIES = 2


def run_single_build_step(state: DemoPipelineState, step: BuildStep) -> dict:
    """Execute a single build step: generate → validate → fix if needed."""
    t0 = time.time()

    # Design spec summary for the builder
    spec = state.requirements
    design_spec = ""
    if spec:
        design_spec = (
            f"Color Palette: {spec.color_palette}\n"
            f"Typography: {spec.typography}\n"
            f"Layout: {spec.layout_approach}\n"
            f"Visual Treatment: {spec.visual_treatment}\n"
            f"Navigation Flow: {spec.navigation_flow}\n"
            f"Interactions: {', '.join(spec.interactions)}\n"
            f"Data Guidance: {spec.placeholder_data_guidance}\n"
            f"Design Notes: {spec.design_notes}"
        )

    current_html = state.current_html
    retries = 0
    issues_list: list[str] = []
    status = "success"
    validation_result = ""

    # ── Generate ──
    gen_prompt = PROMPT_BUILD_GENERATE.format(
        design_spec=design_spec,
        step_number=step.step_number,
        step_title=step.title,
        step_description=step.description,
        current_html=current_html if current_html else "(Starting from scratch — create the initial HTML skeleton.)",
    )

    raw_html = _call_llm(gen_prompt, temperature=0.4, max_tokens=16000)
    current_html = _extract_html(raw_html)

    # ── Validate ──
    val_prompt = PROMPT_BUILD_VALIDATE.format(
        step_number=step.step_number,
        step_title=step.title,
        acceptance_criteria=step.acceptance_criteria,
        current_html=current_html[-8000:],  # truncate to fit context
    )

    val_data = _call_json(val_prompt, temperature=0.1, max_tokens=1000)
    passed = val_data.get("passed", False)
    issues_list = val_data.get("issues", [])
    validation_result = val_data.get("summary", "")

    # ── Fix if needed ──
    if not passed and issues_list:
        for attempt in range(MAX_BUILD_RETRIES):
            retries += 1
            fix_prompt = PROMPT_BUILD_FIX.format(
                step_number=step.step_number,
                step_title=step.title,
                issues="\n".join(f"- {i}" for i in issues_list),
                current_html=current_html[-8000:],
            )
            fixed_html = _call_llm(fix_prompt, temperature=0.3, max_tokens=16000)
            current_html = _extract_html(fixed_html)

            # Re-validate after fix
            val_prompt = PROMPT_BUILD_VALIDATE.format(
                step_number=step.step_number,
                step_title=step.title,
                acceptance_criteria=step.acceptance_criteria,
                current_html=current_html[-8000:],
            )
            val_data = _call_json(val_prompt, temperature=0.1, max_tokens=1000)
            passed = val_data.get("passed", False)
            issues_list = val_data.get("issues", [])
            validation_result = val_data.get("summary", "")

            if passed:
                break

    if not passed:
        status = "failed"

    # Save intermediate HTML
    bd = _build_dir(state.slug)
    step_html_path = bd / f"step{step.step_number}.html"
    step_html_path.write_text(current_html, encoding="utf-8")

    # Update state
    state.current_html = current_html
    state.build_step_results.append({
        "step_number": step.step_number,
        "step_title": step.title,
        "status": status,
        "validation_result": validation_result,
        "retries_used": retries,
        "issues": issues_list,
    })
    save_state(state)

    logger.info("build step %d '%s' — status=%s, retries=%d, %.1fs",
                step.step_number, step.title, status, retries, time.time() - t0)
    return {
        "stage": f"build_step_{step.step_number}",
        "step_number": step.step_number,
        "step_title": step.title,
        "status": status,
        "validation_result": validation_result,
        "retries_used": retries,
        "issues": issues_list,
        "html_size": len(current_html),
        "duration_s": round(time.time() - t0, 2),
    }


# ──────────────────────────────────────────────────────────────────
# STAGE N+1 — Polish & Self-Critique
# ──────────────────────────────────────────────────────────────────

def stage_polish(state: DemoPipelineState) -> dict:
    """Full-pass critique then one fix pass."""
    t0 = time.time()

    spec = state.requirements
    design_spec = ""
    if spec:
        design_spec = (
            f"Color Palette: {spec.color_palette}\n"
            f"Typography: {spec.typography}\n"
            f"Layout: {spec.layout_approach}\n"
            f"Visual Treatment: {spec.visual_treatment}"
        )

    current_html = state.current_html

    # ── Critique ──
    critique_prompt = PROMPT_POLISH_CRITIQUE.format(
        design_spec=design_spec,
        current_html=current_html[-8000:],
    )

    critique_data = _call_json(critique_prompt, temperature=0.2, max_tokens=2000)
    issues = critique_data.get("issues_found", [])
    critique = critique_data.get("critique", "")
    score = critique_data.get("overall_score", "?")

    polish_result = {
        "critique": critique,
        "issues_found": issues,
        "overall_score": score,
        "issues_fixed": 0,
        "fix_result": "",
    }

    # ── Fix if there are issues ──
    if issues:
        fix_prompt = PROMPT_POLISH_FIX.format(
            design_spec=design_spec,
            issues="\n".join(f"- {i}" for i in issues[:8]),  # top 8 issues
            current_html=current_html[-7000:],  # conservative for fix pass
        )
        fixed_html = _call_llm(fix_prompt, temperature=0.3, max_tokens=16000)
        state.current_html = _extract_html(fixed_html)
        polish_result["issues_fixed"] = min(len(issues), 8)
        polish_result["fix_result"] = "Fix pass completed."
    else:
        polish_result["fix_result"] = "No issues found — demo passes criteria."

    state.polish_result = polish_result
    save_state(state)
    save_stage_json(state.slug, "polish", polish_result)

    logger.info("polish completed — score=%s, %d issues, %.1fs",
                score, len(issues), time.time() - t0)
    return {
        "stage": "polish",
        "overall_score": score,
        "issues_found": len(issues),
        "issues_fixed": polish_result["issues_fixed"],
        "duration_s": round(time.time() - t0, 2),
    }


# ──────────────────────────────────────────────────────────────────
# STAGE N+2 — Embed Notes & Save Final
# ──────────────────────────────────────────────────────────────────

def stage_final_save(state: DemoPipelineState) -> dict:
    """Generate notes, embed as HTML comments, save final file and metadata."""
    t0 = time.time()

    spec = state.requirements
    requirements_spec = ""
    if spec:
        requirements_spec = (
            f"Requirements: {', '.join(spec.requirements)}\n"
            f"Design: {spec.color_palette} | {spec.layout_approach}"
        )

    build_results_text = json.dumps(state.build_step_results, default=str)[:2000]
    polish_text = json.dumps(state.polish_result, default=str)[:1000] if state.polish_result else ""

    # Generate notes text
    notes_prompt = PROMPT_GENERATE_NOTES.format(
        title=state.title,
        description=state.demo_brief.description if state.demo_brief else state.prompt,
        requirements_spec=requirements_spec,
        build_results=build_results_text,
        polish_results=polish_text,
    )

    notes_text = _call_llm(notes_prompt, temperature=0.2, max_tokens=1000)
    # Ensure it's wrapped in comment markers
    if not notes_text.strip().startswith("<!--"):
        # Try to detect if the LLM returned a comment block
        comment_start = notes_text.find("<!--")
        comment_end = notes_text.rfind("-->")
        if comment_start >= 0 and comment_end > comment_start:
            notes_text = notes_text[comment_start:comment_end + 3]
        else:
            notes_text = f"<!--\n{notes_text}\n-->"

    # Embed notes at top of HTML
    final_html = state.current_html
    if "<head>" in final_html:
        final_html = final_html.replace("<head>", f"<head>\n{notes_text}", 1)
    elif "<!DOCTYPE" in final_html:
        final_html = final_html.replace("<!DOCTYPE", f"{notes_text}\n<!DOCTYPE", 1)
    else:
        final_html = f"{notes_text}\n{final_html}"

    # Save final HTML
    dd = _demo_dir(state.slug)
    final_path = dd / "final_demo.html"
    final_path.write_text(final_html, encoding="utf-8")

    # Build metadata
    tags = []
    if state.demo_brief:
        # Generate tags from brief
        tags = [t.lower() for t in state.demo_brief.title.split() if len(t) > 3]
        target = state.demo_brief.target_audience.lower()
        if target:
            tags.extend(target.split())
    tags = list(dict.fromkeys(tags[:10]))  # dedupe, keep first 10

    local_url = f"/media/files/demos/{state.slug}/final_demo.html"
    public_url = f"{PUBLIC_BASE_URL.rstrip('/')}/media/files/demos/{state.slug}/final_demo.html"

    requirements_summary = spec.requirements[0] if spec and spec.requirements else ""
    design_decisions = spec.design_notes if spec else ""

    metadata = DemoMetadata(
        title=state.title,
        slug=state.slug,
        description=state.demo_brief.description if state.demo_brief else state.prompt,
        tags=tags,
        created_at=datetime.now(timezone.utc).isoformat(),
        screens=spec.screens if spec else [],
        local_url=local_url,
        public_url=public_url,
        requirements_summary=requirements_summary,
        design_decisions=design_decisions,
        open_questions=state.open_questions,
    )

    meta_path = dd / "metadata.json"
    fp_meta = save_stage_json(state.slug, "metadata", metadata.model_dump())
    # Also save directly as metadata.json for the discovery index
    meta_path.write_text(json.dumps(metadata.model_dump(), indent=2), encoding="utf-8")

    result = FinalSaveResult(
        final_html_path=str(final_path.relative_to(Path(MEDIA_OUTPUT_DIR))),
        metadata_path=str(meta_path.relative_to(Path(MEDIA_OUTPUT_DIR))),
        build_dir_path=str((dd / "build").relative_to(Path(MEDIA_OUTPUT_DIR))),
        html_size_bytes=final_path.stat().st_size,
        embedded_notes_preview=notes_text[:200],
    )

    save_state(state)
    save_stage_json(state.slug, "final_save", result.model_dump())

    logger.info("final_save completed — html=%d bytes, %.1fs",
                result.html_size_bytes, time.time() - t0)
    return {
        "stage": "final_save",
        "final_html_path": result.final_html_path,
        "metadata_path": result.metadata_path,
        "html_size_bytes": result.html_size_bytes,
        "local_url": local_url,
        "public_url": public_url,
        "duration_s": round(time.time() - t0, 2),
    }


# ──────────────────────────────────────────────────────────────────
# STAGE 6 — Build Loop (iterates all build steps internally)
# ──────────────────────────────────────────────────────────────────

def stage6_build_loop(state: DemoPipelineState) -> dict:
    """Execute all build plan steps sequentially with validation and retries."""
    t0 = time.time()

    if state.build_plan is None:
        return {"error": "No build plan found; stage5 must complete first."}

    steps = state.build_plan.steps
    # Cap at 8 steps
    if len(steps) > 8:
        steps = steps[:8]

    all_results = []
    all_passed = True

    for step in steps:
        result = run_single_build_step(state, step)
        all_results.append(result)
        if result["status"] != "success":
            all_passed = False
            logger.warning(
                "Build step %d '%s' failed after %d retries — continuing anyway.",
                step.step_number, step.title, result["retries_used"],
            )

    save_stage_json(state.slug, "6_build_loop", {
        "steps": [{"number": r["step_number"], "title": r["step_title"],
                   "status": r["status"], "retries": r["retries_used"],
                   "issues": r["issues"]} for r in all_results],
        "total_steps": len(all_results),
        "all_passed": all_passed,
        "final_html_size": len(state.current_html),
    })

    logger.info("build_loop completed — %d steps, %d passed, %.1fs",
                len(all_results), sum(1 for r in all_results if r["status"] == "success"),
                time.time() - t0)
    return {
        "stage": "build_loop",
        "total_steps": len(all_results),
        "all_passed": all_passed,
        "step_summaries": all_results,
        "final_html_size": len(state.current_html),
        "duration_s": round(time.time() - t0, 2),
    }


# ──────────────────────────────────────────────────────────────────
# Pipeline summary map (static stages, indexed for tasks.py)
# ──────────────────────────────────────────────────────────────────

_STAGE_MAP: dict[str, Any] = {
    "parse_request": stage1_parse_request,
    "kb_lookup": stage2_kb_lookup,
    "web_research": stage3_web_research,
    "requirements_design": stage4_requirements_design,
    "build_plan": stage5_build_plan,
    "build_loop": stage6_build_loop,
    "polish": stage_polish,
    "final_save": stage_final_save,
}
