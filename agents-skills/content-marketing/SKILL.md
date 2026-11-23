---
name: content-marketing
description: Build the content marketing strategy — the 'what to write and why' layer — for a site or brand. Produces the durable strategy doc with audience and search-intent mapping, positioning and guiding principles, 3–5 content pillars, topic clusters with SEO notes, funnel mapping (TOFU/MOFU/BOFU), distribution, measurement KPIs, and a sequenced 30/60/90 content calendar. Use when a site or brand needs a content or traffic strategy (e.g. 'grow organic traffic for the Homelab Blog', 'drive qualified leads for Bluebovine'), when the Marketing Strategist workflow reaches the strategy step, or when content output is ad-hoc because no documented strategy exists. Grounded in R7 (docs/research/R7-content-marketing-organic-traffic.md); the core artifact that MKT-1 brand-strategy wraps.
---

# Content Marketing Strategy

The "what to write and why" layer — step 2 of the Marketing Strategist
workflow (strategy artifact). Fills the gap between the two existing skills:
`marketing-strategy` is GTM/**launch** planning (product market-entry), and
`content-writer` is **execution** (writes a given topic). Neither answers
*"what guiding principles and areas should we be writing content to drive
traffic?"* — that is this skill. Grounded in R7
(`docs/research/R7-content-marketing-organic-traffic.md` — pillars/clusters,
search-intent mapping, SEO for 2025–2026 incl. AI search, funnel mapping,
measurement KPIs; source list and verified quotes in that digest).

## When to use

- **Use it:** a site or brand has a content/traffic goal but no documented
  strategy; the strategy doc is stale (new goal, new site, AI-search shift);
  the strategist needs the content half of the MKT-1 strategy doc.
- **Skip it:** the ask is GTM/launch planning (use `marketing-strategy`); the
  ask is to write a specific piece of content (use `content-writer` with the
  strategy doc as input); or only one section of an existing strategy doc needs
  refreshing (update that section in place, with an "updated <date>" note).

## Inputs

1. **Brand/site + goal** — e.g. "Homelab Blog — grow organic traffic" or
   "Bluebovine — drive qualified leads". Bluebovine has a `leads` D1 table, so
   its funnel ends in lead capture (the BOFU action is the lead form).
2. **Existing content** — the content inventory
   (`docs/roles/content-marketer/inventory.md`, CM-2) if it exists — the
   topical-lane check and the calendar's dedupe base.
3. **Voice/brand context** — any existing voice definition or brand materials
   (MKT-1 owns the voice definition; this skill takes the guiding-principles
   input it produces, or works from the site's existing content if the voice
   isn't defined yet).
4. **Web research tools** — `mcp_search` (search_web / crawl_page) for SERP
   checks. If unavailable (worker sessions without MCP web tools), fall back
   to direct fetch (curl) of the top-ranking pages for the target queries and
   say so in the doc's method note.

## Method

Produce the strategy doc in order — `references/strategy-template.md` (read it
when writing the doc). Each section below carries the R7-grounded rule that
makes it work.

1. **Audience & intent.** Who the reader is, and what they actually search
   for. Per topic area: the four intent buckets (informational / commercial /
   transactional / navigational — note that many queries carry multiple
   intents). For each target query: the **three Cs** from the SERP — dominant
   content *type*, *format*, *angle* — and "follow the crowd" (R7 Q3). This is
   where `mcp_search` earns its keep: pull the top-5 SERP for the target query
   and read what type/format/angle dominates.
2. **Positioning & guiding principles.** The site's **topical lane** (the
   site-radius test: would a first-time visitor immediately understand what
   this site is about? off-topic content dilutes the authority signal — R7
   Q2); the **information-gain stance** (what original data / firsthand
   experience / real effort this site brings that copycat content can't — R7
   Q4); the **brand-vs-information position** (what makes this a brand, not an
   info blog — information-only content is the surface AI answers eat first).
3. **Content pillars.** 3–5 core topics (narrow from the buyer problems; seed
   keywords "specific enough to stay focused but broad enough to have
   meaningful subtopics"). Each pillar: a format chosen from what's already
   ranking (guide / what-is / how-to), and the **three filters** per subtopic
   (meaningful search demand? relevant to the business? within topical focus?
   — a subtopic failing any one is cut). Pillars are mutually exclusive and
   collectively cover the strategy — no overlap, no gaps.
4. **Topic clusters.** Pillar → cluster → concrete article topics. Each topic
   carries: search intent + the three Cs, rough demand, the subtopic list
   (from the top-ranking pages / content-gap check), and the internal-link
   plan (cluster ↔ pillar with the same hyperlinked keyword, cross-links
   between related clusters, no orphaned pages). The **"do nothing" exclusion
   list** (off-topic ideas that are interesting but off-lane) is part of the
   strategy — site focus is a hard constraint (R7 Q2).
5. **Funnel mapping.** Every cluster/topic tagged **TOFU** (awareness/traffic
   — informational-intent clusters; this is the surface AI Overviews appear
   on, so TOFU content must carry information gain) / **MOFU** (consideration
   — comparisons, honest "best X", category coverage) / **BOFU** (conversion
   — for Bluebovine the lead form; for the Homelab Blog, the site's conversion
   action). Pillar pages optimize for conversion; cluster pages optimize for
   traffic (R7 Q5).
6. **Distribution.** Owned channels first (the blog; YouTube — the #2
   most-cited domain in AI answers per R7 S6); repurposing as the cost lever
   (one cluster article → social posts, newsletter, video script via
   `content-writer` formats); "search everywhere" awareness (off-Google
   presence feeds AI visibility — R7 Q4).
7. **Measurement.** The KPI set (R7 Q6): search visibility (share of voice),
   conversions from organic, non-branded traffic, and the AI KPIs (mentions,
   AI share of voice) once tooling exists — **cluster-level, not post-level**
   measurement (a good TOFU post looks like a failure at post level). Pick the
   ROI method **up front** (conversion analysis / lifetime traffic value /
   signup attribution — one, applied consistently; directional, not precise)
   and record the **refresh triggers** (traffic drop from peak, superseded
   stat, changed tool, competitor update, dropped out of an AI Overview) as
   the maintenance cadence.
8. **Content calendar.** First 30/60/90 days, sequenced **pillar first, then
   clusters** ("start with your pillar pages and work outward"); cadence set
   against realistic output for a solo operator + agents (the "content
   output" North Star pattern — a cadence you can miss is a cadence you will
   miss).

## Rules

- **Documented strategy is the deliverable** — the failure modes are the
  documented ones (R7 S6): no clear goals, unrelated to the customer journey,
  not data-driven, weak audience research. A strategy doc without a goal and a
  KPI set is a mood board.
- **Volume is not a strategy** — "adding more content to a poor existing site
  architecture can make it even harder for Google to find and rank your
  content" (R7 S1). The doc answers *what and why*, never just *how much*.
- **The AI-search stance is mandatory** — in 2026 a content strategy without
  an AI-visibility section (information gain + topical lane + brand mentions)
  is incomplete (R7 Q4). No llms.txt work (R7: 97% of published files are
  never fetched).
- **Selectivity is part of the strategy** — the exclusion list (what we will
  *not* write) ships with the pillar list (R7 Q2, site focus / site radius).
- **No fabricated figures (S9 discipline)** — demand estimates are rough
  ranges with the method named (SERP volume, competitor coverage), or the
  equation + the fastest test. Never invented numbers.
- **One site per doc** — Homelab Blog and Bluebovine are different strategies
  (traffic goal vs. lead-gen goal, different funnels); don't merge them.

## Output

1. **The strategy doc** — durable markdown at
   `docs/roles/marketing-strategist/strategy/<site>.md` (the G12 artifact
   conventions; `references/strategy-template.md` — read it when writing).
   New doc: full 8 sections. Refresh: the changed sections + an "updated
   <date>" note; the doc header carries the goal, date, and status.
2. **The research note** — which SERP checks / sources grounded the intent
   and cluster sections (the digest-style source list, or a pointer to a
   `deep-research` run), so the next refresh can re-verify.

## Handoff

- **→ `content-writer`:** the strategy produces the *what*; the writer
  produces the *how* (the ask carries the topic, angle, format, funnel stage,
  goal, constraints — MKT-1's ask template).
- **→ MKT-1 `brand-strategy`:** this doc is MKT-1's core artifact; MKT-1
  wraps it with the voice definition, the ask pipeline, and the impact
  reviews.
- **→ CM-1 `content-qa`:** the doc's intent/three-Cs, topical-lane, and
  internal-link sections are the QA baseline for every draft.
- **→ the board:** the calendar's first 30 days become briefed content asks
  (content project cards), not a silent spreadsheet.
