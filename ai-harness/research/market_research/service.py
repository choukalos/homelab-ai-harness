"""
Market research pipeline service.

Implements the 10-stage pipeline:
  1. KB Lookup
  2. Competitor Discovery & Tiering
  3. Competitor Deep-Dive (parallel crawl + LLM profile)
  4. Vector / Theme Identification
  5. Data Population (comparison matrix)
  6. Tier Analysis & Summarization
  7. Executive Summary
  8. Innovation & Opportunity Scouting
  9. Visual & Layout Planning
 10. Report Assembly & PDF Export

Each stage mutates the shared MarketResearchState and returns a small
summary dict for step-level run tracking.
Celery tasks wrap each stage and drive the workflow engine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from infra.core.config import MEDIA_OUTPUT_DIR, INTERNAL_BASE_URL, SEARXNG_BASE_URL
from infra.core.llm import chat_completion_sync
from research.web_search.schemas import WebSearchRequest, SearchResult as WsSearchResult
from research.web_search.service import crawl_url as _crawl_url
from knowledge.family_kb.schemas import SearchRequest
from knowledge.family_kb.service import search_kb
from research.market_research.prompts import (
    prompt_kb_insights,
    prompt_competitor_queries,
    prompt_tier_competitors,
    prompt_competitor_profile,
    prompt_vector_extraction,
    prompt_populate_cell,
    prompt_tier_analysis,
    prompt_executive_summary,
    prompt_innovation_scouting,
    prompt_visual_planning,
)
from research.market_research.schemas import (
    KbLookupResult,
    CompetitorDiscoveryResult,
    DeepDiveResult,
    VectorIdentificationResult,
    ComparisonMatrixResult,
    TierAnalysisResult,
    TierAnalysis,
    ExecutiveSummaryResult,
    InnovationScoutingResult,
    LayoutPlanResult,
    ReportAssemblyResult,
    MarketResearchState,
)
from research.market_research.schemas import Competitor, ComparisonVector
from research.market_research.schemas import CompetitorProfile, OpportunityFlag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _output_dir(market: str) -> Path:
    """Return the per-market output directory."""
    sanitized = market.replace(" ", "_")
    target = Path(MEDIA_OUTPUT_DIR) / "research" / sanitized
    target.mkdir(parents=True, exist_ok=True)
    return target


def _extract_json(text: str) -> dict | list:
    """Best-effort JSON extraction from LLM text (handles <json> tags)."""
    text = text.strip()
    if "<json>" in text:
        text = text.split("<json>")[1].split("</json>")[0]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass
    # find first { ... }
    s = text.find("{")
    e = text.rfind("}") + 1
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e])
        except (json.JSONDecodeError, ValueError):
            pass
    # find first [ ... ]
    s = text.find("[")
    e = text.rfind("]") + 1
    if s >= 0 and e > s:
        try:
            return json.loads(text[s:e])
        except (json.JSONDecodeError, ValueError):
            pass
    raise ValueError(f"Could not parse JSON from response ({len(text)} chars)")


def _call_json(prompt: str, temperature: float = 0.2,
               max_tokens: int | None = None) -> dict:
    """Call LLM and return parsed JSON dict."""
    raw = chat_completion_sync(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return _extract_json(raw)


def _write_intermediate(path: Path, data: Any) -> str:
    """Save structured data to disk for auditability."""
    if isinstance(data, dict):
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    else:
        path.write_text(str(data), encoding="utf-8")
    return str(path)


def _competitor_names(all_competitors: Any) -> list[str]:
    """Extract competitor name strings regardless of whether items are dict or model."""
    names: list[str] = []
    for c in all_competitors:
        if isinstance(c, Competitor):
            names.append(c.name)
        elif isinstance(c, dict):
            names.append(c.get("name", ""))
        else:
            names.append(str(c))
    return names


# ---------------------------------------------------------------------------
# Stage 1 — KB Lookup
# ---------------------------------------------------------------------------

def stage1_kb_lookup(state: MarketResearchState) -> dict:
    """Query Knowledge Base for existing research on the market."""
    t0 = time.time()
    market = state.market

    kb_results = search_kb(SearchRequest(query=market, limit=10))
    kb_text = json.dumps(kb_results, default=str)

    prompt = prompt_kb_insights(kb_text, market)
    data = _call_json(prompt, temperature=0.2, max_tokens=1000)

    kb_result = KbLookupResult(
        query=market,
        existing_reports=data.get("existing_reports", []),
        prior_vectors=data.get("prior_vectors", []),
        insights=data.get("insights", ""),
        has_prior_data=data.get("has_prior_data", False),
    )

    out = _output_dir(market)
    _write_intermediate(out / "stage1_kb_lookup.json", kb_result.model_dump())
    state.kb_result = kb_result

    logger.info("stage1 completed in %.1fs", time.time() - t0)
    return {
        "stage": "kb_lookup",
        "has_prior_data": kb_result.has_prior_data,
        "prior_vectors_count": len(kb_result.prior_vectors),
        "duration_s": round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# Stage 2 — Competitor Discovery & Tiering
# ---------------------------------------------------------------------------

def stage2_competitor_discovery(state: MarketResearchState) -> dict:
    """Discover competitors via web search and tier them."""
    t0 = time.time()
    market = state.market
    prior = state.kb_result.prior_vectors if state.kb_result else []

    queries_data = _call_json(
        prompt_competitor_queries(market, prior),
        temperature=0.5,
        max_tokens=2000,
    )
    queries: list[str] = queries_data if isinstance(queries_data, list) else queries_data.get("queries", [])

    # Execute searches (runs inside Celery)
    all_results: list[dict] = []
    for q in queries:
        try:
            with httpx.Client(timeout=45.0) as client:
                results = _sync_search(client, WebSearchRequest(query=q, max_results=5, mode="sources"))
                all_results.extend([r.model_dump() for r in results])
        except Exception as exc:
            logger.warning("Search failed for '%s': %s", q, exc)

    search_text = json.dumps(all_results, default=str)[:15000]

    tier_data = _call_json(
        prompt_tier_competitors(market, search_text),
        temperature=0.2,
        max_tokens=4000,
    )

    top = tier_data.get("top_players", [])
    est = tier_data.get("established", [])
    new = tier_data.get("new_entrants", [])
    all_raw = tier_data.get("all_competitors", [])

    _VALID_TIERS = {"top_player", "established", "new_entrant"}

    def norm(c: dict) -> dict:
        c.setdefault("tier", "established")
        if c["tier"] not in _VALID_TIERS:
            c["tier"] = "established"
        return c

    if not all_raw and (top or est or new):
        all_raw = top + est + new

    discovery = CompetitorDiscoveryResult(
        market=market,
        top_players=[norm(c) for c in top],
        established=[norm(c) for c in est],
        new_entrants=[norm(c) for c in new],
        all_competitors=[norm(c) for c in all_raw],
        search_queries_used=queries,
    )

    out = _output_dir(market)
    _write_intermediate(out / "stage2_competitors.json", discovery.model_dump())
    state.competitor_discovery = discovery

    logger.info("stage2 completed in %.1fs — %d competitors", time.time() - t0, len(discovery.all_competitors))
    return {
        "stage": "competitor_discovery",
        "competitor_count": len(discovery.all_competitors),
        "top_players": len(discovery.top_players),
        "established": len(discovery.established),
        "new_entrants": len(discovery.new_entrants),
        "duration_s": round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# Stage 3 — Competitor Deep-Dive
# ---------------------------------------------------------------------------

def stage3_deep_dive(state: MarketResearchState) -> dict:
    """Crawl each competitor URL and generate LLM profiles."""
    t0 = time.time()
    market = state.market
    competitors = state.competitor_discovery.all_competitors if state.competitor_discovery else []

    profiles: list[CompetitorProfile] = []
    failed: list[str] = []

    for comp in competitors:
        try:
            raw = _crawl_single(comp.get("primary_url", ""))
            prompt = prompt_competitor_profile(raw, comp.get("name", ""), market)
            pdata = _call_json(prompt, temperature=0.1, max_tokens=3000)
            md = _profile_to_markdown(pdata)

            profile = CompetitorProfile(
                name=pdata.get("name", comp.get("name", "")),
                tier=comp.get("tier", "established"),
                url=comp.get("primary_url", ""),
                positioning=pdata.get("positioning", ""),
                value_propositions=pdata.get("value_propositions", []),
                offers_services=pdata.get("offers_services", []),
                pricing_tiers=pdata.get("pricing_tiers", []),
                feature_presentations=pdata.get("feature_presentations", []),
                summary=pdata.get("summary", ""),
                raw_markdown=md,
            )
            profiles.append(profile)

            safe = pdata.get("name", "unknown").replace(" ", "_")
            (_output_dir(market) / f"competitor_{safe}.md").write_text(md, encoding="utf-8")
            logger.info("Deep-dived: %s", profile.name)

        except Exception as exc:
            logger.error("Deep-dive failed for %s: %s", comp.get("name", "?"), exc)
            failed.append(comp.get("primary_url", ""))

    result = DeepDiveResult(market=market, profiles=profiles, failed_scrapes=failed)
    out = _output_dir(market)
    _write_intermediate(out / "stage3_deep_dive.json", result.model_dump())
    state.deep_dive = result

    logger.info("stage3 completed in %.1fs — %d profiles, %d failures", time.time() - t0, len(profiles), len(failed))
    return {
        "stage": "deep_dive",
        "profiles_count": len(profiles),
        "failed_scrapes": len(failed),
        "duration_s": round(time.time() - t0, 2),
    }


def _crawl_single(url: str) -> str:
    """Crawl one URL; returns markdown blob."""
    if not url:
        return "(no URL)"

    async def _run():
        async with httpx.AsyncClient(timeout=45.0) as client:
            item = WsSearchResult(url=url, title="", content="")
            r = await _crawl_url(client, item)
            return r.extracted_markdown or ""

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_run()) or "(crawl returned no content)"
        finally:
            loop.close()
    except Exception as exc:
        logger.warning("Crawl failed for %s: %s", url, exc)
        return f"(crawl error: {exc})"


def _profile_to_markdown(d: dict) -> str:
    """Build markdown from a competitor profile dict."""
    sections = [f"# {d.get('name', 'Competitor')}\n"]
    if d.get("positioning"):
        sections += ["## Positioning\n", d["positioning"] + "\n"]
    if d.get("value_propositions"):
        sections += ["## Value Propositions\n"] + [f"- {v}\n" for v in d["value_propositions"]]
    if d.get("offers_services"):
        sections += ["## Offers / Services\n"] + [f"- {v}\n" for v in d["offers_services"]]
    if d.get("pricing_tiers"):
        sections += ["## Pricing Tiers\n"] + [f"- {v}\n" for v in d["pricing_tiers"]]
    if d.get("feature_presentations"):
        sections += ["## Key Features\n"] + [f"- {v}\n" for v in d["feature_presentations"]]
    if d.get("summary"):
        sections += ["## Summary\n", d["summary"]]
    return "\n".join(sections)


# ---------------------------------------------------------------------------
# Stage 4 — Vector / Theme Identification
# ---------------------------------------------------------------------------

def stage4_vector_identification(state: MarketResearchState) -> dict:
    t0 = time.time()
    market = state.market
    profiles = state.deep_dive.profiles if state.deep_dive else []
    prior = state.kb_result.prior_vectors if state.kb_result else []

    pj = json.dumps([p.model_dump() for p in profiles], default=str)[:12000]
    data = _call_json(prompt_vector_extraction(pj, prior, market),
                      temperature=0.2, max_tokens=3000)

    vectors = [ComparisonVector(**v) for v in data.get("vectors", [])]
    result = VectorIdentificationResult(
        vectors=vectors,
        new_vectors_flagged=data.get("new_vectors_flagged", []),
        themes=data.get("themes", []),
    )

    out = _output_dir(market)
    _write_intermediate(out / "stage4_vectors.json", result.model_dump())
    state.vectors = result

    logger.info("stage4 completed in %.1fs — %d vectors", time.time() - t0, len(vectors))
    return {
        "stage": "vector_identification",
        "vectors_count": len(vectors),
        "new_vectors": len(result.new_vectors_flagged),
        "themes": result.themes,
        "duration_s": round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# Stage 5 — Data Population
# ---------------------------------------------------------------------------

def stage5_data_population(state: MarketResearchState) -> dict:
    t0 = time.time()
    market = state.market
    profiles = state.deep_dive.profiles if state.deep_dive else []
    vectors = state.vectors.vectors if state.vectors else []

    headers = [v.name for v in vectors]
    rows: list[dict] = []
    missing = 0

    for prof in profiles:
        row: dict[str, Any] = {"company": prof.name, "tier": prof.tier}
        for vec in vectors:
            try:
                val = chat_completion_sync(
                    messages=[{"role": "user",
                               "content": prompt_populate_cell(
                                   vec.name, vec.description,
                                   prof.name, prof.raw_markdown)}],
                    temperature=0.0,
                    max_tokens=100,
                )
                val = val.strip().strip('"').strip("'")
                row[vec.name] = val if val else "N/A"
                if not val or val == "N/A":
                    missing += 1
            except Exception:
                row[vec.name] = "N/A"
                missing += 1
        rows.append(row)

    result = ComparisonMatrixResult(header_vectors=headers, rows=rows, missing_cells=missing)
    out = _output_dir(market)
    _write_intermediate(out / "stage5_matrix.json", result.model_dump())
    state.matrix = result

    logger.info("stage5 completed in %.1fs — %dx%d matrix, %d missing", time.time() - t0, len(rows), len(headers), missing)
    return {
        "stage": "data_population",
        "rows": len(rows),
        "vectors": len(headers),
        "missing_cells": missing,
        "duration_s": round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# Stage 6 — Tier Analysis
# ---------------------------------------------------------------------------

def stage6_tier_analysis(state: MarketResearchState) -> dict:
    t0 = time.time()
    market = state.market
    comps = state.competitor_discovery.all_competitors if state.competitor_discovery else []
    mat = json.dumps({
        "header_vectors": state.matrix.header_vectors if state.matrix else [],
        "rows": state.matrix.rows if state.matrix else [],
    }, default=str)[:5000]

    tiers_out: list[TierAnalysis] = []

    for label, key in zip(
            ["Top Players", "Established Competitors", "New Entrants"],
            ["top_player", "established", "new_entrant"]):
        tier_comps = [c for c in comps if c.get("tier") == key]
        if not tier_comps:
            tiers_out.append(TierAnalysis(
                tier_name=label, competitor_count=0,
                summary_narrative=f"No competitors found in the {label} tier.",
            ))
            continue

        prompt = prompt_tier_analysis(json.dumps(tier_comps, default=str)[:6000],
                                     label, mat, market)
        try:
            d = _call_json(prompt, temperature=0.3, max_tokens=2000)
            tiers_out.append(TierAnalysis(
                tier_name=label,
                competitor_count=len(tier_comps),
                collective_behaviors=d.get("collective_behaviors", []),
                market_positioning=d.get("market_positioning", ""),
                value_point_clustering=d.get("value_point_clustering", []),
                summary_narrative=d.get("summary_narrative", ""),
            ))
        except Exception:
            tiers_out.append(TierAnalysis(
                tier_name=label, competitor_count=len(tier_comps),
                summary_narrative=f"Analysis of {len(tier_comps)} competitors in the {label} tier.",
            ))

    result = TierAnalysisResult(tiers=tiers_out)
    out = _output_dir(market)
    _write_intermediate(out / "stage6_tier_analysis.json",
                        {"tiers": [t.model_dump() for t in tiers_out]})
    state.tier_analysis = result

    logger.info("stage6 completed in %.1fs", time.time() - t0)
    return {
        "stage": "tier_analysis",
        "tiers_analyzed": len(tiers_out),
        "duration_s": round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# Stage 7 — Executive Summary
# ---------------------------------------------------------------------------

def stage7_executive_summary(state: MarketResearchState) -> dict:
    t0 = time.time()
    market = state.market
    n = len(state.competitor_discovery.all_competitors) if state.competitor_discovery else 0

    tier_text = "\n".join(
        f"### {t.tier_name}\n{t.summary_narrative}\n"
        for t in state.tier_analysis.tiers
    ) if state.tier_analysis else ""

    data = _call_json(
        prompt_executive_summary(market, n, tier_text,
                                state.kb_result.insights if state.kb_result else "",
                                ""),
        temperature=0.2, max_tokens=2000,
    )

    summary = ExecutiveSummaryResult(
        market=market,
        executive_summary=data.get("executive_summary", ""),
        key_findings=data.get("key_findings", []),
        total_competitors_analyzed=n,
    )

    out = _output_dir(market)
    _write_intermediate(out / "stage7_executive_summary.json", summary.model_dump())
    state.executive_summary = summary

    logger.info("stage7 completed in %.1fs", time.time() - t0)
    return {"stage": "executive_summary", "duration_s": round(time.time() - t0, 2)}


# ---------------------------------------------------------------------------
# Stage 8 — Innovation & Opportunity Scouting
# ---------------------------------------------------------------------------

def stage8_innovation_scouting(state: MarketResearchState) -> dict:
    t0 = time.time()
    market = state.market
    mat = json.dumps({
        "header_vectors": state.matrix.header_vectors if state.matrix else [],
        "rows": state.matrix.rows if state.matrix else [],
    }, default=str)[:8000]
    pj = json.dumps([p.model_dump() for p in (state.deep_dive.profiles or [])],
                    default=str)[:6000]

    data = _call_json(prompt_innovation_scouting(mat, pj, market),
                      temperature=0.4, max_tokens=2000)

    opps = [OpportunityFlag(
        category=o.get("category", "emerging_trend"),
        description=o.get("description", ""),
        evidence=o.get("evidence", ""),
    ) for o in data.get("opportunities", [])]

    result = InnovationScoutingResult(
        opportunities=opps,
        emerging_trends=data.get("emerging_trends", []),
        whitespace_summary=data.get("whitespace_summary", ""),
    )

    out = _output_dir(market)
    _write_intermediate(out / "stage8_innovation.json", result.model_dump())
    state.innovation = result

    logger.info("stage8 completed in %.1fs — %d opportunities", time.time() - t0, len(opps))
    return {
        "stage": "innovation_scouting",
        "opportunities_count": len(opps),
        "duration_s": round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# Stage 9 — Visual & Layout Planning
# ---------------------------------------------------------------------------

def stage9_visual_planning(state: MarketResearchState) -> dict:
    t0 = time.time()
    market = state.market

    names = _competitor_names(state.competitor_discovery.all_competitors) if state.competitor_discovery else []
    vec_names = [v.name for v in (state.vectors.vectors or [])]
    mrows = state.matrix.rows if state.matrix else []

    tier_data = "\n".join(
        f"{t.tier_name}: {t.summary_narrative}"
        for t in getattr(state.tier_analysis, "tiers", [])
    ) if state.tier_analysis else ""

    inno = ""
    if state.innovation:
        inno = f"Trends: {state.innovation.emerging_trends}\nWhitespaces: {state.innovation.whitespace_summary}"

    plan_data = _call_json(
        prompt_visual_planning(market, names, vec_names, mrows, tier_data, inno),
        temperature=0.3, max_tokens=3000,
    )

    from research.market_research.schemas import VisualAssetSpec

    assets = [VisualAssetSpec(
        asset_type=a.get("asset_type", "text_block"),
        zone=a.get("zone", ""),
        description=a.get("description", ""),
        title=a.get("title", ""),
    ) for a in plan_data.get("visual_assets", [])]

    plan = LayoutPlanResult(
        template=plan_data.get("template", "magazine"),
        title=plan_data.get("title", f"{market} Market Research Report"),
        visual_assets=assets,
    )

    out = _output_dir(market)
    _write_intermediate(out / "stage9_layout_plan.json", plan.model_dump())
    state.layout_plan = plan

    logger.info("stage9 completed in %.1fs — %d assets", time.time() - t0, len(assets))
    return {
        "stage": "visual_planning",
        "visual_assets_count": len(assets),
        "template": plan.template,
        "duration_s": round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# Stage 10 — Report Assembly & PDF Export
# ---------------------------------------------------------------------------

def stage10_report_assembly(state: MarketResearchState) -> dict:
    """Assemble the final report via Layout Engine (in-process calls) and export PDF."""
    t0 = time.time()
    market = state.market
    ds = datetime.now(timezone.utc).strftime("%Y%m%d")
    san = market.replace(" ", "_")
    out = _output_dir(market)

    # ----- Import layout / chart modules (in-process) -----
    from creative.layout.schemas import (
        CreateLayoutRequest, AddContentRequest,
        RenderLayoutRequest, ExportPdfRequest,
        TableColumnDef, TableStyle, ChartZoneSpec,
    )
    from creative.layout.service import layout_create, layout_add_content, layout_render, layout_export_pdf, _layouts
    from creative.charts.schemas import ChartConfig, ChartFormat

    # 1. Create layout
    lr = layout_create(CreateLayoutRequest(
        orientation="portrait",
        template="magazine",
        title=f"{market} Market Research Report — {ds}",
        background_color="#ffffff",
        text_color="#1a1a1a",
        accent_color="#3b82f6",
    ))
    logger.info("Created layout %s", lr.layout_id)

    ls = _layouts.get(lr.layout_id, {})
    zones = ls.get("zones", [])

    def _add(zone: str, ctype: str, content: str | None = None):
        layout_add_content(AddContentRequest(
            layout_id=lr.layout_id, zone=zone,
            content_type=ctype, content=content, alignment="center",
        ))

    def _pick(*kw: str, fallback: int = -1) -> str | None:
        for z in zones:
            if any(k in z.lower() for k in kw):
                return z
        if zones:
            return zones[fallback]
        return None

    # 2. Executive summary
    if state.executive_summary:
        es = state.executive_summary.executive_summary
        z = _pick("hero_title", fallback=0)
        if z:
            _add(z, "text", es[:500] if "hero" in z.lower() else es)

    # 3. Comparison table
    if state.matrix and state.matrix.rows:
        cols = [TableColumnDef(name="Company", key="company", align="left", width="140px")]
        cols += [TableColumnDef(name=v, key=v, align="left") for v in state.matrix.header_vectors]
        tz = _pick("col_left", "col_center", "column", "gallery", "panel", fallback=1)
        if tz:
            layout_add_content(AddContentRequest(
                layout_id=lr.layout_id, zone=tz, content_type="table",
                table_columns=[c.model_dump() for c in cols],
                table_rows=state.matrix.rows,
                table_style=TableStyle(compact=True, font_size="13px"),
            ))

    # 4. Bar chart — feature coverage
    if state.matrix and state.matrix.rows:
        labels = [r.get("company", "") for r in state.matrix.rows]
        vals = [sum(1 for k, v in r.items()
                    if k not in ("company", "tier") and v and v != "N/A")
                for r in state.matrix.rows]
        cz = _pick("panel_right", "col_right", "panel", fallback=2)
        if cz:
            layout_add_content(AddContentRequest(
                layout_id=lr.layout_id, zone=cz, content_type="chart",
                chart_spec=ChartZoneSpec(
                    chart_type="bar",
                    chart_config=ChartConfig(
                        title="Feature Coverage by Competitor",
                        x_labels=labels, y_values=vals,
                        x_label="Competitor", y_label="Features Covered",
                    ),
                    format=ChartFormat.png, width=800, height=400,
                ),
            ))

    # 5. Pie chart — tier distribution
    if state.competitor_discovery:
        tc = {
            "Top Players": len(state.competitor_discovery.top_players),
            "Established": len(state.competitor_discovery.established),
            "New Entrants": len(state.competitor_discovery.new_entrants),
        }
        nz = {k: v for k, v in tc.items() if v > 0}
        if nz:
            pz = _pick("gallery", "col_left", fallback=-1)
            if pz:
                layout_add_content(AddContentRequest(
                    layout_id=lr.layout_id, zone=pz, content_type="chart",
                    chart_spec=ChartZoneSpec(
                        chart_type="pie",
                        chart_config=ChartConfig(
                            title="Market Tier Distribution",
                            x_labels=list(nz.keys()), y_values=list(nz.values()),
                            x_label="", y_label="Competitors",
                        ),
                        format=ChartFormat.png, width=600, height=400,
                    ),
                ))

    # 6. Tier analysis text
    if state.tier_analysis:
        for tier in state.tier_analysis.tiers:
            if not tier.summary_narrative:
                continue
            sec = f"### {tier.tier_name}\n\n{tier.summary_narrative}"
            if tier.collective_behaviors:
                sec += "\n\n**Key Behaviors:**\n" + "\n".join(f"- {b}" for b in tier.collective_behaviors)
            if zones:
                _add(zones[-1], "text", sec)

    # 7. Innovation text
    if state.innovation:
        im = "### Innovation & Opportunities\n\n"
        if state.innovation.emerging_trends:
            im += "**Emerging Trends:**\n" + "\n".join(f"- {t}" for t in state.innovation.emerging_trends) + "\n\n"
        if state.innovation.opportunities:
            im += "**Opportunities:**\n" + "\n".join(f"- **{o.category}**: {o.description}" for o in state.innovation.opportunities) + "\n"
        if state.innovation.whitespace_summary:
            im += f"\n**Whitespace:** {state.innovation.whitespace_summary}\n"
        if zones:
            _add(zones[-1], "text", im)

    # 8. Render HTML
    rr = layout_render(RenderLayoutRequest(layout_id=lr.layout_id))
    html_name = f"{san}_Research_Report_{ds}.html"
    hp = out / html_name
    hp.write_text(rr.html, encoding="utf-8")

    # 9. Export PDF
    pdf_rel = f"research/{san}/{san}_Research_Report_{ds}.pdf"
    pdf_size = 0
    try:
        pr = layout_export_pdf(ExportPdfRequest(
            layout_id=lr.layout_id, output_path=pdf_rel, page_size="Letter",
        ))
        pdf_size = pr.bytes_written
    except Exception as exc:
        logger.error("PDF export failed: %s", exc)

    pdf_fp = str(Path(MEDIA_OUTPUT_DIR) / pdf_rel)
    pdf_url = f"{INTERNAL_BASE_URL}/media/files/{pdf_rel}"

    intermediate = sorted(
        str(p.relative_to(Path(MEDIA_OUTPUT_DIR)))
        for p in out.glob("*")
        if p.is_file() and p.suffix in (".json", ".md", ".html", ".pdf")
    )

    assembly = ReportAssemblyResult(
        market=market, pdf_path=pdf_fp, pdf_url=pdf_url,
        pdf_bytes=pdf_size, html_path=str(hp),
        intermediate_files=intermediate,
    )
    state.assembly = assembly

    logger.info("stage10 completed in %.1fs — PDF: %d bytes", time.time() - t0, pdf_size)
    return {
        "stage": "report_assembly",
        "pdf_path": pdf_fp,
        "pdf_url": pdf_url,
        "pdf_bytes": pdf_size,
        "html_path": str(hp),
        "intermediate_files": intermediate,
        "duration_s": round(time.time() - t0, 2),
    }


# ---------------------------------------------------------------------------
# Sync web search helper (runs inside Celery workers)
# ---------------------------------------------------------------------------

def _sync_search(client: httpx.Client, req: WebSearchRequest) -> list[WsSearchResult]:
    params = {
        "q": req.query, "format": "json",
        "categories": req.category, "language": req.language,
        "pageno": 1, "safesearch": 1,
    }
    r = client.get(f"{SEARXNG_BASE_URL}/search", params=params)
    r.raise_for_status()
    results: list[WsSearchResult] = []
    for it in r.json().get("results", [])[:req.max_results]:
        url = it.get("url")
        if url:
            results.append(WsSearchResult(title=it.get("title"), url=url,
                                          content=it.get("content"),
                                          engine=it.get("engine"),
                                          score=it.get("score")))
    return results


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

_PIPELINE: list[tuple[str, Any]] = [
    ("stage1_kb_lookup", stage1_kb_lookup),
    ("stage2_competitor_discovery", stage2_competitor_discovery),
    ("stage3_deep_dive", stage3_deep_dive),
    ("stage4_vector_identification", stage4_vector_identification),
    ("stage5_data_population", stage5_data_population),
    ("stage6_tier_analysis", stage6_tier_analysis),
    ("stage7_executive_summary", stage7_executive_summary),
    ("stage8_innovation_scouting", stage8_innovation_scouting),
    ("stage9_visual_planning", stage9_visual_planning),
    ("stage10_report_assembly", stage10_report_assembly),
]


def run_pipeline(state: MarketResearchState) -> MarketResearchState:
    """Execute all 10 stages; each mutates *state* in place."""
    for name, fn in _PIPELINE:
        logger.info("[%s] start", name)
        fn(state)
    logger.info("Pipeline complete for '%s' — PDF: %s",
                state.market,
                state.assembly.pdf_path if state.assembly else "(none)")
    return state
