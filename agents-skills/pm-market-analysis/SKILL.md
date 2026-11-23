---
name: pm-market-analysis
description: Run the competitive and market analysis for a product area — what competitors do, their positioning, the gaps, market signals, and an opportunity list where each opportunity becomes a kanban board idea with its evidence attached. Use at the 'analyze research / competitive market' step of the Product Manager workflow (step 1), when evaluating a new product area or feature direction, when a competitive question needs answering, or when market analysis should feed the idea pipeline.
---

# PM Market Analysis

Competitive / market analysis for a product area → opportunity brief + board
ideas — step 1 of the Product Manager workflow. The output is the signal that
PM-4 `pm-ideation` converts into candidate ideas and PM-3 `pm-exec-pitch`
turns into exec decisions. Grounded in R8
(`docs/research/R8-pm-artifacts.md` — competitive-analysis frameworks for a
solo operator, bottom-up opportunity sizing) and S9 `exec-problem-brief`'s
no-fabrication discipline.

## When to use

- **Use it:** a new product area or feature direction, a competitive question
  ("what do X and Y do about this?"), a periodic refresh of a known area, or
  any market analysis whose output should feed the board (not just a
  read-and-discard answer).
- **Skip it:** a quick fact check — `mcp_search` is enough; or the monthly
  brief for a *tracked* market profile (competitor scan, market size/share,
  analyst watch, retained artifacts) — that's `market-research-brief`.

## Inputs

1. **Product area + the question** — what decision does this analysis feed
   (build/don't-build, a pitch, a strategy update)? The output shape follows
   the decision. If the question is missing, ask before researching.
2. **Board state** — existing ideas in the area (`list_ideas`) — dedupe
   before adding opportunities.
3. **Strategy context** — the current goals (what the org is optimizing for),
   so opportunities can be ranked by fit, not just by size.

## Method

1. **Frame the question.** One sentence: "We are deciding <decision> and
   need <what the analysis must show>." Everything below serves that.
2. **Research with the existing skills** — don't reinvent the research layer:
   - `deep-research` — multi-source, cited; the landscape and the specific
     question.
   - `market-research-brief` — when the area is a tracked market profile.
   - `mcp_search` — targeted checks (a specific feature, pricing, a complaint
     thread).
   Free sources only; paywalled analyst data is flagged, never fabricated.
3. **Competitive landscape.** For the 2–3 closest alternatives — **always
   including the "do nothing / a shell script" column** (for homelab ideas the
   competitor is often doing nothing): what they do, their positioning, the
   gaps. Per candidate area, a one-page competitive note (R8):
   - **Positioning statement** — who it's for, what problem, why this over
     the alternatives.
   - **Feature matrix** — capabilities × alternatives; enough to spot gaps
     and avoid building table-stakes features.
   - **"Why them / why us"** — for the top alternative, one honest paragraph
     each.
   Skip Porter's five forces for homelab tooling (R8) — it answers "is this
   industry profitable?", which a one-operator shop doesn't need to answer.
4. **Market signals.** What is moving — adoption, pricing changes,
   complaints, new entrants, deprecations. Every signal carries a source; an
   unsourced signal is an opinion and gets labeled as one.
5. **Opportunity list.** Gaps + signals → candidate opportunities. Size each
   **bottom-up only** (users × value per use) as a **range with an explicit
   assumption list** — never a point estimate, never an invented figure
   (R8). Top-down analyst numbers only if the artifact might be published or
   monetized — then cite the report and its date and say the slice is a
   guess. When data is missing, state the equation + the fastest empirical
   test (S9 discipline) instead of a number.
6. **Land the opportunities on the board.** Dedupe against `list_ideas`
   first (strengthen an existing idea rather than adding a near-duplicate),
   then `add_idea` on the product project — one idea per opportunity, each
   with its evidence attached (source links, the signal, the sizing
   assumptions). Board ops: S1 `kanban-board`.

## Rules

- **No fabrication (S9 discipline):** never invent figures, benchmarks, or
  adoption numbers. Missing data → the equation + the fastest test, stated
  plainly.
- **Bottom-up sizing only, ranges + assumptions** — the exercise's value is
  forcing the assumption list into the record, not producing a number.
- **Every claim sourced** — a source link, or an explicit `[inferred]` /
  `[assumption]` flag.
- **The "do nothing" column is mandatory** — the strongest competitor for an
  internal tool is usually inaction.
- **One idea per opportunity** — the brief stays the durable artifact; the
  board carries the actionable items.

## Output

1. **The opportunity brief** — durable markdown at
   `docs/roles/pm/market-analysis-<area>-<YYYY-MM-DD>.md` (the G12 artifact
   conventions; `references/opportunity-brief-template.md` — read it when
   writing the brief).
2. **Board ideas** — one kanban idea per opportunity, evidence attached, on
   the product project.

## Handoff

- **→ PM-4 `pm-ideation`:** the opportunity list + signals are the signal
  input for idea generation.
- **→ PM-3 `pm-exec-pitch`:** a top opportunity that needs an exec decision
  gets a 1-page pitch (or S9 `exec-problem-brief` for the deep-dive).
- **→ BA + Marketing Strategist:** market insights feed the strategy loop —
  route the durable brief, not just the board ideas.
