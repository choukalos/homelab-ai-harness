---
name: brand-strategy
description: Own the brand's market position as a durable, versioned strategy doc — positioning, brand/voice definition (voice attributes with do/don't examples, calibrated against existing brand materials and the content inventory), content constraints and guiding principles, pillars, and measurement — then issue briefed content asks and periodic goal-vs-actual impact reviews. Use at the 'strategy / voice / brand image' step of the Marketing Strategist workflow (step 2), when a brand or site needs a strategy doc or a voice definition, when content asks need to be briefed for the Content Marketer, or when shipped content needs an impact review. Wraps S12 content-marketing (the core strategy artifact); grounded in R9 (docs/research/R9-marketing-strategy-operating-cadence.md) and R7 (docs/research/R7-content-marketing-organic-traffic.md).
---

# Brand Strategy

The strategy-artifact step of the Marketing Strategist workflow — owns the
durable, versioned strategy doc, the voice definition, the content-ask
pipeline, and the impact reviews. Wraps S12 `content-marketing` (the core
strategy artifact is S12's; this skill adds the brand/voice layer, the ask
template, and the impact-review template). Grounded in R9
(`docs/research/R9-marketing-strategy-operating-cadence.md` — brand/voice
frameworks, strategy-doc structure, content ops ask → brief → draft → QA →
publish, impact measurement) and R7
(`docs/research/R7-content-marketing-organic-traffic.md` — the content
strategy half).

## When to use

- **Use it:** a site/brand needs a strategy doc or a voice definition (or a
  refresh); the strategist needs to brief content asks for the Content
  Marketer; shipped content needs a goal-vs-actual impact review; the strategy
  is 3–6 months old (the review cadence — R9 Q4).
- **Skip it:** the ask is only the content half (run S12 directly and stop);
  the ask is to write a piece of content (that's the Content Marketer, with
  the strategy doc as input); or a single ask needs briefing (use the ask
  template without running the whole workflow).

## Inputs

1. **Market / reports / analytics** — market research (`deep-research`,
   `market-research-brief`) + what the content is actually doing (BA reports,
   the content inventory's performance column). Product/content analytics are
   not wired yet (gap G3 — Plausible); until then the BA reports, the
   inventory, and manual/GSC spot-checks are the data sources.
2. **Existing brand materials** — the logo, past content, any prior voice
   notes (gap G8: there is no brand asset inventory yet — point at what
   exists; the content inventory
   (`docs/roles/content-marketer/inventory.md`) is the main published-content
   source).
3. **The current strategy doc** (if any) — `docs/roles/marketing-strategist/strategy/<site>.md`.
4. **Web research tools** — `mcp_search` for SERP/competitor checks; curl
   fetch fallback when unavailable (note it in the doc's method note).

## Method

1. **Review the market and the record.** What does the research say the
   audience wants; what is the content actually doing (inventory performance,
   BA reports, manual spot-checks)? This is the "goal vs. actual" baseline for
   the strategy refresh (R9 Q4: the review compares the strategy's goal with
   what happened, per channel/ask, and decides what to continue, change, or
   stop).
2. **Build or refresh the core strategy artifact with S12**
   `content-marketing` — audience & intent, positioning & guiding principles,
   pillars, clusters, funnel mapping, distribution, measurement, calendar.
   S12 owns that layer; don't re-derive it here.
3. **Define the brand/voice** (R9 Q1 — the part S12 doesn't cover):
   - **Calibrate against existing materials (the G8 step).** Inventory the
     brand assets + published content (the CM-2 inventory + any brand
     materials); classify by performance where data exists; extract the voice
     traits from the top performers (the adjective exercise — desired
     adjectives vs. adjectives of the 3–5 top-performing pieces, keep the
     common elements; emulate the feeling, not the words — R9 S1/S2).
   - **3–5 voice attributes, each with a plain-language explanation + do/don't
     examples per content type.** The "well-defined" rule (R9 Q1): a list of
     adjectives without examples is the documented failure mode — "content
     gets haphazard fast" — and it's not machine-checkable by CM-1. Every
     attribute gets: what it means in one sentence, a do example (blog), a do
     example (social), a don't example.
   - **The "who we are not" section** — the antithesis: the words, phrases,
     and stylistic choices the brand avoids (R9 S3/S2).
   - **Tone rules per context** — the voice is stable; the tone varies by
     context (e.g. promo vs. incident vs. tutorial) (R9 S1).
4. **Assemble the strategy doc** — `references/strategy-doc-template.md`
   (read it when writing): **positioning → voice/brand image → content
   constraints/guidance → pillars → measurement**. Positioning comes from the
   three questions (who do we serve / what problem do we solve / what's
   different) + messaging (main value, benefits, differentiators); the
   content-constraints section is the 3–5 "themes the brand should own" + the
   topical lane (R7's site-radius test) + the AI-search stance (R7 Q4);
   pillars/clusters/measurement come from the S12 artifact. One doc per
   site/brand; updates are edits with an "updated <date>" note.
5. **Issue content asks** — `references/ask-and-impact-templates.md` (read it
   when writing asks). Each ask is a board card on the content project with
   the ask template as the body: topic, angle + search intent (the three Cs),
   format, funnel stage, goal, constraints, style-guide link (the voice
   section), deliverable + deadline, point person, filing instructions.
   Never a vague "write something" — and don't get too granular: pin the
   load-bearing constraints, leave the craft to the writer (R9 Q3). For open
   asks the CM pitches 2–3 angles first; the strategist picks.
6. **Impact reviews** (periodic — every 3–6 months for the strategy, more
   often for active campaigns; R9 Q4) — `references/ask-and-impact-templates.md`:
   goal vs. actual (the 500-vs-320 pattern: compare how each channel/ask
   contributed, identify where performance was weaker), the planned-vs-
   published pipeline check (how many asks shipped vs. planned — R9 S9),
   learnings (what worked and why), strategy deltas framed as **continue /
   change / stop**. The data side is blocked on the G3 wiring (Plausible) —
   until then the review runs on whatever data exists (inventory performance,
   GSC, manual spot-checks) and says so.

## Rules

- **The strategy doc is the durable artifact** — one per site/brand, versioned
  in place (edits + "updated <date>" note), at the G12 home
  (`docs/roles/marketing-strategist/strategy/<site>.md`). The board carries
  the asks; the repo carries the strategy.
- **Documented strategy is the differentiator** (R9 Q2): the failure modes
  are the documented ones — no clear goals, unrelated to the customer
  journey, not data-driven, weak audience research. A strategy doc without a
  goal, a KPI set, and a review cadence is a mood board.
- **The voice section is only as good as its examples** (the "well-defined"
  rule, R9 Q1) — CM-1 checks voice against the do/don't examples, so examples
  per content type are mandatory, not optional.
- **Review every piece against the doc before it ships** (R9 Q3: "review
  every campaign against this document before launch") — the doc is the
  baseline for CM-1's QA pass; a draft that can't be checked against the doc
  means the doc is missing a section.
- **Asks are contracts, not suggestions** — every ask carries the fields the
  CM-1 QA pass checks against (goal, funnel stage, intent, voice, required
  checks). Missing fields = the ask goes back unbriefed.
- **No fabricated figures (S9 discipline)** — impact reviews state the
  equation + the data source; when the G3 data is missing, the review says
  "no data yet" instead of inventing a number.
- **The AI-search stance is mandatory** (R7 Q4) — the strategy doc carries it
  (information gain + topical lane + brand mentions); a 2026 strategy without
  it is incomplete.

## Output

1. **The strategy doc** — durable, versioned, at
   `docs/roles/marketing-strategist/strategy/<site>.md` (the G12 artifact
   conventions; `references/strategy-doc-template.md`).
2. **Content asks on the board** — one card per ask on the content project,
   ask template as the body (the board is the artifact for in-flight asks).
3. **Impact reviews** — point-in-time, at
   `docs/roles/marketing-strategist/impact-reviews/<site>-<YYYY-MM-DD>.md`
   (`references/ask-and-impact-templates.md`).

## Handoff

- **→ Content Marketer:** the strategy doc + the briefed asks (the CM reads
  the doc for voice/constraints and the ask for the specific assignment).
- **→ CM-1 `content-qa`:** the doc's voice section (do/don't examples) + each
  ask's fields are the QA baseline.
- **→ CM-2 `content-inventory`:** the inventory is the calibration input for
  the voice step (step 3) and the performance input for impact reviews.
- **→ chuck (exec visibility):** the strategy doc + impact reviews are the
  exec-facing record for the marketing side.
- **→ BA:** the strategy's KPI set + the impact reviews feed the BA loop
  (Phase 3, once the G3 data lands).
