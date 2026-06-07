"""
LLM prompt templates for the one-page clickable demo workflow.

Each stage has its own prompt template that takes structured data from prior
stages and produces the output needed for the next stage.
"""


# ────────────── Stage 1: Parse Request ──
PROMPT_PARSE_REQUEST = """
You are a product designer analyzing a demo request.

Extract a structured demo brief from the following user request.

User Request Title: {title}
User Request Details: {prompt}

Return your response as a JSON object with these fields:
- title: str (clean, short title for the demo)
- description: str (1-2 sentence description of what the demo should show)
- target_audience: str (who would use this product, e.g., "busy parents", "enterprise managers")
- key_features: list[str] (4-8 key features the demo should include)
- screens_requested: list[str] (list of distinct screens/views needed, e.g., ["landing", "dashboard", "profile"])
- style_hints: list[str] (any style cues mentioned or implied, e.g., ["minimal", "colorful", "corporate"])
- constraints: list[str] (any explicit constraints or requirements)

Be thorough but concise. Focus on what will make a compelling clickable demo.
Respond with ONLY a JSON object.
"""


# ────────────── Stage 2: KB Insights ──
PROMPT_KB_INSIGHTS = """
You are analyzing knowledge base results for relevance to a demo request.

Demo Request: {brief_summary}

Here are the knowledge base search results:
{kb_results}

Analyze these results and extract any insights that could inform the demo design.
Look for:
- Prior market research that's relevant
- Information about the domain/industry
- Any notes about similar products or approaches
- User requirements or preferences from prior work

Return a JSON object with:
- has_prior_data: bool (whether there's useful prior data)
- insights: str (2-3 sentence summary of relevant findings)
- items: list[{{"source": str, "text": str}}] (key excerpts, max 5)

If nothing is relevant, set has_prior_data to false and return a brief "no relevant prior data" insight.
Respond with ONLY a JSON object.
"""


# ────────────── Stage 3: Web Research ──
PROMPT_WEB_RESEARCH_QUERIES = """
You are researching for a demo project. Generate 3-4 focused search queries
that will help gather competitive and design insights.

Demo Brief:
{brief_summary}

Generate search queries targeting:
1. Similar products or competitors
2. Current design patterns for this type of product
3. Features users expect in this category

Return ONLY a JSON array of 3-4 search query strings.
"""


PROMPT_WEB_RESEARCH_SUMMARIZE = """
You are analyzing web research results for a demo project.

Demo Brief:
{brief_summary}

Web Search Results:
{search_results}

Analyze these results and extract actionable insights for building a better demo.

Return a JSON object with:
- queries_used: list[str] (the search queries that produced results)
- sources: list[{{"title": str, "url": str, "snippet": str}}] (top 10 most relevant sources)
- competitor_patterns: list[str] (5-8 patterns observed in competitors)
- ux_patterns: list[str] (5-8 common UX patterns or conventions)
- feature_recommendations: list[str] (5-8 features worth including)
- summary: str (2-3 sentence synthesis of key findings)

Focus on what will make the demo feel authentic and current.
Respond with ONLY a JSON object.
"""


# ────────────── Stage 4: Requirements & Design Spec ──
PROMPT_REQUIREMENTS_DESIGN = """
You are a senior product designer creating requirements and a design spec.

DEMO REQUEST:
Title: {title}
Description: {description}
Target Audience: {target_audience}
Key Features: {key_features}
Screens Requested: {screens}
Style Hints: {style_hints}
Constraints: {constraints}

PRIOR KNOWLEDGE (if any):
{kb_insights}

WEB RESEARCH INSIGHTS:
{web_insights}

Create TWO deliverables:

A) REQUIREMENTS - a detailed list of what the demo must include:
- Specific screens/views needed (expand on what was requested if needed)
- Navigation flow between screens
- What placeholder data to show on each screen
- Specific interactions (clicks, hover states, transitions)
- Any micro-interactions that add polish

B) VISUAL DESIGN SPEC - guidance for building the HTML:
- Color palette (primary, secondary, accent, background colors as hex codes)
- Typography approach (font families to use via system fonts)
- Layout approach (card-based, sidebar, grid, etc.)
- Visual treatment suggestions (shadows, gradients, borders, etc.)

Return a JSON object with these fields:
- requirements: list[str] (8-15 detailed requirements)
- screens: list[str] (final list of screens, with brief description of each)
- navigation_flow: str (description of how users navigate between screens)
- placeholder_data_guidance: str (what realistic data to include)
- interactions: list[str] (5-10 specific interactions to implement)
- color_palette: str (color scheme description with hex values)
- typography: str (font choices and sizing approach)
- layout_approach: str (how to structure the page layout)
- visual_treatment: str (styling details like shadows, borders, gradients)
- design_notes: str (any additional design guidance, max 200 words)

Be specific and actionable. The HTML builder will use this directly.
Respond with ONLY a JSON object.
"""


# ────────────── Stage 5: Build Plan ──
PROMPT_BUILD_PLAN = """
You are a technical lead creating a build plan for a one-page HTML demo.

REQUIREMENTS AND DESIGN SPEC:
{requirements_spec}

Create a numbered build plan. Each step should be an atomic, testable unit.
Keep the plan to 6-8 steps maximum. Consolidate where possible.

Each step must include:
- step_number: int
- title: str (short, descriptive)
- description: str (what to build in this step, including HTML structure, CSS, and JS)
- acceptance_criteria: str (what "done" looks like - specific, testable)
- depends_on_step: int or null (which prior step it depends on, or null)

Example steps progression:
1. Base HTML skeleton with nav structure, CSS reset, and design tokens
2. First screen layout with content and styling
3. Additional screens (group related screens)
4. More screens or complex components
5. Interaction wiring (click handlers, screen transitions)
6. Polish (animations, hover states, responsive adjustments)

Ensure the plan covers ALL requirements from the design spec.
Each step builds incrementally on prior steps - the HTML must always be
functional after each step, just with fewer features.

Return ONLY a JSON object with:
- steps: [{{step_number, title, description, acceptance_criteria, depends_on_step}}]
- notes: str (any overall build guidance, max 100 words)
"""


# ────────────── Build Loop: Generate ──
PROMPT_BUILD_GENERATE = """
You are an expert front-end developer building a one-page HTML demo.

DESIGN SPECIFICATION:
{design_spec}

BUILD STEP #{step_number}: {step_title}
Description: {step_description}

PREVIOUS HTML (what we have so far):
{current_html}

Build this step. Return the COMPLETE updated HTML file.

CRITICAL RULES:
- Return ONLY valid, complete HTML (from <!DOCTYPE html> to </html>)
- Include ALL CSS inline in <style> tags
- Include ALL JavaScript inline in <script> tags
- NO external assets, CDNs, frameworks, or network calls
- Keep everything in ONE file
- Preserve all prior working functionality - only add/improve this step
- Use system fonts only (no Google Fonts)
- Use emoji or unicode for icons, never external icon fonts
- Make it responsive (mobile-first)
- Use CSS variables for the design tokens (colors, spacing)
- Add realistic placeholder data
- Add aria labels for accessibility
- Make interactions feel smooth with CSS transitions

The HTML must be complete and functional after this step.
"""


# ────────────── Build Loop: Validate ──
PROMPT_BUILD_VALIDATE = """
You are a QA engineer validating a build step for a one-page HTML demo.

BUILD STEP #{step_number}: {step_title}
Acceptance Criteria: {acceptance_criteria}

CURRENT HTML:
{current_html}

Evaluate the HTML against the acceptance criteria. Check:
1. Does the step complete what was described?
2. Are there any broken elements, missing styles, or non-functional interactions?
3. Does the HTML remain valid and complete?
4. Are prior steps' functionality preserved?

Return a JSON object with:
- passed: bool
- issues: list[str] (specific issues found, or empty list if passed)
- summary: str (1-2 sentence evaluation)

If there are issues, be specific about what needs fixing and where in the HTML.
Respond with ONLY a JSON object.
"""


# ────────────── Build Loop: Fix ──
PROMPT_BUILD_FIX = """
You are fixing issues in a one-page HTML demo.

BUILD STEP #{step_number}: {step_title}

ISSUES FOUND:
{issues}

CURRENT HTML:
{current_html}

Fix ALL the issues listed above. Return the COMPLETE updated HTML file.

CRITICAL RULES:
- Return ONLY valid, complete HTML (from <!DOCTYPE html> to </html>)
- Preserve all working functionality
- Fix each specific issue mentioned
- Keep all CSS and JS inline
- NO external dependencies

The HTML must be complete and functional after these fixes.
"""


# ────────────── Stage N+1: Polish & Self-Critique ──
PROMPT_POLISH_CRITIQUE = """
You are a senior front-end reviewer critiquing a one-page HTML demo.

DESIGN SPECIFICATION:
{design_spec}

CURRENT HTML:
{current_html}

Evaluate the COMPLETE demo. Provide specific feedback on:

1. OVERALL QUALITY - Does it feel like a realistic, polished product?
2. NAVIGATION FLOW - Can a user navigate between all screens smoothly?
3. VISUAL CONSISTENCY - Does it follow the design spec (colors, typography, layout)?
4. MOBILE RESPONSIVENESS - Will it work well on mobile devices?
5. INTERACTIONS - Are all promised interactions implemented and working?
6. CONTENT QUALITY - Is the placeholder data realistic and appropriate?
7. ACCESSIBILITY - Basic aria labels, semantic HTML, contrast
8. CODE QUALITY - Clean, well-structured, no obvious bugs

Return a JSON object with:
- critique: str (detailed critique, organized by the categories above)
- issues_found: list[str] (specific fixable issues, ranked by priority)
- overall_score: int (1-10, 10 being excellent)
- strengths: list[str] (what's working well)

Be constructive but honest. Focus on issues that can actually be fixed within
the constraints (single HTML file, no external dependencies).
Respond with ONLY a JSON object.
"""


PROMPT_POLISH_FIX = """
You are polishing a one-page HTML demo based on critique feedback.

DESIGN SPECIFICATION:
{design_spec}

CRITIQUE ISSUES TO FIX (prioritized):
{issues}

CURRENT HTML:
{current_html}

Fix the highest priority issues. Focus on improvements that will have the
most impact on the overall quality and user experience.

CRITICAL RULES:
- Return ONLY valid, complete HTML (from <!DOCTYPE html> to </html>)
- Preserve all working functionality
- Keep everything in ONE file
- NO external dependencies
- Make the demo feel as polished as possible

The HTML must be complete and functional.
"""


# ────────────── Stage N+2: Generate Notes ──
PROMPT_GENERATE_NOTES = """
You are generating build notes for a demo project.

DEMO TITLE: {title}
DESCRIPTION: {description}

REQUIREMENTS AND DESIGN SPEC:
{requirements_spec}

BUILD PLAN AND RESULTS:
{build_results}

POLISH RESULTS:
{polish_results}

Generate embedded notes that will be placed as HTML comments at the top of
the final file. Include:

1. What the full requirements were
2. What was done (build approach, design decisions)
3. How it was built (brief technical summary)
4. Any open questions or limitations
5. Tips for presenting the demo

Format the output as a nicely structured HTML comment block.
Do NOT wrap it in any JSON - just return the comment block text that goes
between <!-- and -->.
"""
