# Content-ask template + impact-review template

The two point-in-time artifacts of `brand-strategy` (MKT-1). The ask is a
board card (the board is the artifact for in-flight asks); the impact review
is a durable file at `docs/roles/marketing-strategist/impact-reviews/<site>-<YYYY-MM-DD>.md`.

## Content-ask template

The contract with the Content Marketer (R9 Q3 — the union of the Semrush and
HubSpot content-brief elements, trimmed to 1–2 pages). Written into the card
body on the content project. Pin the load-bearing constraints; leave the
craft to the writer ("don't get too granular or rigid" — R9 S7).

```markdown
## <Topic — working title>

**Angle + search intent:** <the angle, and the three Cs for the target query
— dominant content type / format / angle from the SERP (R7 Q3)>
**Format:** <blog post | social | video script | …>
**Funnel stage:** <TOFU | MOFU | BOFU>
**Goal:** <the one goal this piece serves — ladders to the strategy doc's
goal; e.g. "drive lead-form fills", "rank for <query>">
**Constraints:**
- Word count: <range>
- Target keyword(s): <primary + secondary>
- Avoid: <keywords/topics to avoid — content cannibalization guard>
- Required subheadings / structure: <if any>
- Internal links: <to the pillar + related clusters — per the strategy doc's
  link plan>
- Meta: <title tag / meta description requirements, if any>
- CTA: <the conversion action — e.g. the lead form for Bluebovine>
**Voice:** <link to the strategy doc's voice section — the do/don't examples
are the baseline; name the tone for this context>
**Deliverable + deadline:** <what ships (file/card), and when>
**Point person:** <who answers questions — the strategist>
**Filing:** <how/where the completed draft is filed for QA>
**After:** <the CM-1 QA pass runs before finalize; the strategist signs off
exceptions>
```

Field notes:

- **The CM-1 QA pass checks against this card** — goal, funnel stage, intent,
  voice, and the constraint fields are the conformance baseline. A field the
  QA pass needs that the card doesn't carry is a template gap; add it.
- **Never a vague "write something"** — the org rule (the strategist
  workflow): specific, briefed asks only.
- **Open asks** — when the topic is open, the CM pitches 2–3 angles with a
  one-line rationale each (the CM workflow step 2); the strategist picks,
  then the card gets filled.

## Impact-review template

The periodic goal-vs-actual review (R9 Q4 — the 500-vs-320 pattern: compare
how each channel/ask contributed to the actual, identify where performance
was weaker, decide what to continue, change, or stop). Cadence: every 3–6
months for the strategy, more often for active campaigns.

```markdown
# Impact review — <site/brand> — <YYYY-MM-DD>

- **Strategy goal (as of the doc's last update):** <the goal + the KPI set>
- **Review window:** <from–to>
- **Data sources:** <inventory performance column, GSC, Plausible (once G3
  lands), manual spot-checks — name each; "no data yet" is a valid entry>

## Goal vs. actual

| KPI | Target | Actual | Delta | Data source |
|-----|--------|--------|-------|-------------|
| <the ~3 KPIs> | | | | |

## Per-ask / per-channel contribution

| Ask / cluster | Funnel stage | Goal | Actual | Contributed? (yes/partial/no) | Why (one line) |
|---------------|--------------|------|--------|-------------------------------|----------------|

## Pipeline check (planned vs. published)

- Planned (window): <n asks>
- Published (window): <n> — <the inventory rows>
- Slipped / stuck: <which, and why — the pipeline problem, not the content
  problem (R9 S9: planned-vs-published exposes production-pipeline issues)>

## Learnings

- What worked and why: <…>
- What didn't, and why: <…>

## Strategy deltas (continue / change / stop)

| Decision | What | Why | Where it lands |
|----------|------|-----|----------------|
| continue | <…> | | |
| change | <…> | | <strategy doc section / ask pipeline> |
| stop | <…> | | |

## ROI note

<the fixed ROI method (from the strategy doc) applied to the window —
directional, not precise (R7 Q6 / R9 S13); "no data yet" when the G3 wiring
isn't in>
```

Field notes:

- **The deltas are the output** — a review without continue/change/stop
  decisions is a report, not a review. The deltas get applied to the strategy
  doc (edits + "updated <date>" note) in the same session.
- **Cluster-level, not post-level** (R7 Q5) — measure at the cluster/ask
  level; a good TOFU piece looks like a failure at post level.
- **No fabricated figures (S9 discipline)** — every number names its data
  source; missing data is stated as missing (the G3 gap is the reason, not an
  excuse to estimate).
