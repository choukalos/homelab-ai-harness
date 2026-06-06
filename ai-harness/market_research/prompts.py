"""LLM prompt templates for each market research pipeline stage.

All prompts are parameterized via Python f-strings so the market name
and intermediate results can be injected at runtime.
"""

# ---------- Stage 1: KB Lookup ----------

def prompt_kb_insights(kb_results: str, market: str) -> str:
    """Synthesize KB search results into research insights."""
    return f"""
You are a market research analyst. Synthesize the following knowledge base
search results into insights relevant to researching the **{market}** market.

Knowledge base results:
{kb_results if kb_results else "(no prior data found)"}

Return JSON with the following structure:
<json>
{{
  "existing_reports": ["title or path of any prior reports found"],
  "prior_vectors": ["list of previously tracked comparison dimensions/vectors if any"],
  "insights": "A 3-5 sentence summary of what the KB tells us about this market. Include any gaps or areas needing fresh research.",
  "has_prior_data": true | false
}}
</json>
"""


# ---------- Stage 2: Competitor Discovery & Tiering ----------

def prompt_competitor_queries(market: str, prior_vectors: list[str]) -> str:
    """Generate targeted search queries for competitor discovery."""
    vector_hints = ""
    if prior_vectors:
        vector_hints = (
            f"\n\nPrior comparison vectors for this market: {', '.join(prior_vectors)}.\n"
            "Use these to focus your queries."
        )
    return f"""
Generate 5 focused web search queries to discover active competitors in
the **{market}** market.

Queries should target:
1. Market overview and key players
2. Established competitors and their products
3. New entrants and startups
4. Market share / tier rankings
5. Recent product launches and partnerships{vector_hints}

Return ONLY a JSON array of 5 query strings:
["query 1", "query 2", "query 3", "query 4", "query 5"]
"""


def prompt_tier_competitors(market: str, search_results: str) -> str:
    """
    Analyze search results to classify competitors into tiers.
    Returns JSON list of Competitor objects.
    """
    return f"""
You are a market analyst. Based on the search results below, identify all
active competitors in the **{market}** market and classify each into a tier:

- **top_player**: Market leaders with >10% estimated share, widespread brand recognition
- **established**: Well-funded companies with significant market presence
- **new_entrant**: Recent launches, startups, or disruptive newcomers

Search results:
{search_results}

Return a JSON object:
<json>
{{
  "top_players": [
    {{ "name": "...", "tier": "top_player", "primary_url": "...",
      "description": "One-line description", "founded_year": 20XX, "headquarters": "City, Country" }}
  ],
  "established": [ ...same schema... ],
  "new_entrants": [ ...same schema... ],
  "all_competitors": [ ...flat list of all above... ]
}}
</json>

Be thorough but conservative — only include companies you can identify from
the results. Aim for 5-15 total competitors. Every entry must have a
primary_url.
"""


# ---------- Stage 3: Competitor Deep-Dive ----------

def prompt_competitor_profile(raw_content: str, company_name: str, market: str) -> str:
    """Generate a detailed competitive profile from crawled page content."""
    return f"""
You are a competitive intelligence analyst. Analyze the following content
from **{company_name}**'s website and produce a detailed profile.

Market context: **{market}**

Website content:
{raw_content[:8000]}

Produce a JSON profile:
<json>
{{
  "name": "{company_name}",
  "positioning": "How they position themselves in the {market} market (2-3 sentences)",
  "value_propositions": ["prop1", "prop2", ...],
  "offers_services": ["service/offering 1", "offering 2", ...],
  "pricing_tiers": ["tier description", ...],
  "feature_presentations": ["featured feature 1", ...],
  "summary": "One concise paragraph summarizing this competitor."
}}
</json>
"""


# ---------- Stage 4: Vector / Theme Identification ----------

def prompt_vector_extraction(profiles_json: str, prior_vectors: list[str], market: str) -> str:
    """
    Analyze competitor profiles to extract recurring comparison vectors.
    """
    prior_str = ", ".join(prior_vectors) if prior_vectors else "None"
    return f"""
You are a market research analyst. Analyze the following competitor profiles
for the **{market}** market and identify recurring features, themes, or
comparison vectors that would make sense as columns in a comparison table.

Prior vectors (if any): {prior_str}

Competitor profiles:
{profiles_json[:12000]}

Return JSON:
<json>
{{
  "vectors": [
    {{ "name": "vector name", "description": "what it measures",
      "source": "kb" | "discovered",
      "rationale": "why it should be included" }}
  ],
  "new_vectors_flagged": [ ...only vectors with source=discovered... ],
  "themes": ["theme 1", "theme 2", ...]
}}
</json>

Include 8-15 vectors that span features, pricing, positioning, services, and
differentiators. Each vector should be measurable across competitors.
"""


# ---------- Stage 5: Data Population ----------

def prompt_populate_cell(
    vector_name: str, vector_desc: str, company_name: str, raw_markdown: str
) -> str:
    """Extract a specific vector value for a specific competitor."""
    return f"""
Extract the value for the comparison vector **"{vector_name}"** ({vector_desc})
for the company **{company_name}** from the following raw profile data.

Profile data:
{raw_markdown[:4000]}

Return ONLY a concise value (max 80 characters). If the data is missing or
unclear, return "N/A". Do not add commentary.
"""


# ---------- Stage 6: Tier Analysis ----------

def prompt_tier_analysis(competitors_json: str, tier_name: str, matrix_json: str, market: str) -> str:
    """Generate narrative analysis for a single tier."""
    return f"""
Write a tier analysis for the **{tier_name}** tier of the **{market}** market.

Competitors in this tier:
{competitors_json[:6000]}

Comparison matrix data:
{matrix_json[:4000]}

Return JSON:
<json>
{{
  "tier_name": "{tier_name}",
  "competitor_count": <number>,
  "collective_behaviors": ["behavior 1", ...],
  "market_positioning": "2-3 sentences on how this tier positions collectively",
  "value_point_clustering": ["cluster 1", ...],
  "summary_narrative": "A 150-200 word narrative paragraph suitable for a research report."
}}
</json>
"""


# ---------- Stage 7: Executive Summary ----------

def prompt_executive_summary(
    market: str,
    competitors_count: int,
    tier_analysis_text: str,
    kb_insights: str,
    innovation_flags: str,
) -> str:
    """Synthesize an executive summary leadership-ready."""
    return f"""
You are a senior market research analyst. Write an executive summary for a
comprehensive report on the **{market}** market.

Context:
- {competitors_count} competitors were analyzed across 3 tiers
- Tier analysis findings:
{tier_analysis_text[:4000]}

- Prior research insights:
{kb_insights[:2000]}

- Innovation & opportunity flags:
{innovation_flags[:2000]}

Return JSON:
<json>
{{
  "executive_summary": "A 200-300 word high-level summary suitable for C-suite review. "
    "Cover: market landscape, competitive dynamics, key trends, and strategic implications.",
  "key_findings": ["Finding 1", "Finding 2", ...],
  "total_competitors_analyzed": {competitors_count}
}}
</json>
"""


# ---------- Stage 8: Innovation & Opportunity Scouting ----------

def prompt_innovation_scouting(matrix_json: str, profiles_json: str, market: str) -> str:
    """Identify whitespace opportunities and divergent strategies."""
    return f"""
Analyze the **{market}** market data to identify innovation opportunities,
emerging trends, and whitespace.

Comparison matrix:
{matrix_json[:8000]}

Competitor profiles:
{profiles_json[:6000]}

Return JSON:
<json>
{{
  "opportunities": [
    {{ "category": "emerging_trend" | "untested_feature" | "pricing_divergence" | "market_whitespace",
      "description": "One-sentence description of the opportunity",
      "evidence": "Supporting evidence from the data" }}
  ],
  "emerging_trends": ["trend 1", ...],
  "whitespace_summary": "80-150 word summary of untapped market space."
}}
</json>

Look for:
- Features no one offers (potential whitespace)
- Pricing strategies that diverge from the norm
- Emerging technologies or business models
- Customer segments not being served
"""


# ---------- Stage 9: Visual Asset Planning ----------

def prompt_visual_planning(
    market: str,
    competitor_names: list[str],
    vectors: list[str],
    matrix_rows: list[dict],
    tier_data: str,
    innovation_data: str,
) -> str:
    """Plan the visual layout of the final report."""
    return f"""
You are a report designer. Plan the visual layout for a market research
report on the **{market}** market.

Competitors: {", ".join(competitor_names)}
Comparison vectors: {", ".join(vectors)}
Matrix data: {str(matrix_rows[:3])}
Tier data: {tier_data[:2000]}
Innovation data: {innovation_data[:2000]}

Return JSON describing the layout:
<json>
{{
  "template": "magazine",
  "title": "{market} Market Research Report",
  "visual_assets": [
    {{
      "asset_type": "text" | "chart" | "table" | "image",
      "zone": "which zone to place it in",
      "description": "What this element shows",
      "title": "Section title"
    }}
  ]
}}
</json>

Include:
1. Title/header text (zone: header)
2. Executive summary text (zone: lead or content)
3. A comparison table (zone: column_a or column_b)
4. A bar chart showing competitor features count (zone: panel_right or col_center)
5. A pie chart showing market tier distribution (zone: col_left or gallery_grid)
6. Tier analysis sections
7. Innovation & opportunities section
"""


def prompt_chart_data_gen(
    competitors: list[str], vectors: list[str], market: str
) -> str:
    """Generate chart-ready data from competitor matrix."""
    return f"""
Generate chart-ready data for a bar chart showing feature coverage across
competitors in the **{market}** market.

Competitors: {competitors}
Vectors (features): {vectors}

Return JSON:
<json>
{{
  "labels": ["competitor1", "competitor2", ...],
  "values": [<feature_count_for_comp1>, <feature_count_for_comp2>, ...]
}}
</json>

Count how many vectors each competitor has non-"N/A" values for.
"""
