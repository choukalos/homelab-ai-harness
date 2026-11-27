---
name: pm-analytics-review
description: Consume the product analytics (Plausible traffic/engagement/custom events, kanban spend by owner and model, board state, the latest weekly KPI digest) and turn them into prioritization input for the Product Manager — what content and features are working, where the spend is going, what the data says to build next. Use at the 'analyze product analytics' step of the Product Manager workflow (before ideation PM-4 and prioritization PM-5), when deciding what to build next with data, or when asked for an analytics review of the product/content surface. Writes docs/roles/pm/analytics-review-<date>.md and routes signals to the board per the G4 report contract.
---

# PM Analytics Review

Product analytics → prioritization input — the PM workflow step that sits
between signal (PM-1 market analysis, BA reports) and decision (PM-4
ideation, PM-5 prioritization). G3 is wired (Plausible → data-hub + Grafana
Product KPIs, `todo_plausible.md` P5), so the data exists: this skill is the
PM's way of *reading* it.

## When to use

- **Use it:** deciding what to build/ship next and the data should have a say
  (traffic/engagement on the 3 sites, feature usage via custom events, spend
  trends); a BA KPI digest just landed and the PM needs to act on it; or a
  direct ask for an analytics review.
- **Skip it:** the decision is market- or exec-driven (PM-1 / PM-3 territory)
  with no product-data angle, or the window is too young to read — the
  Plausible sites were wired 2026-11-27; say "no signal yet" rather than
  interpreting single-digit pageviews as a trend (G4 grounding rule).

## Inputs (collect in one pass — S7 spend-awareness)

```bash
cd /home/chuck/homelab
python3 agents-skills/pm-analytics-review/tools/pm_analytics_data.py          # 7-day window
python3 agents-skills/pm-analytics-review/tools/pm_analytics_data.py --days 14
```

The tool returns one JSON pack:
- **`plausible`** — headline numbers from the latest `plausible-kpi` artifact
  (pageviews / unique visitors / custom events, per-site). If
  `status: missing`, run the `plausible-kpi` skill (BA-1) first, then re-run.
- **`kpi_digest`** — the latest weekly KPI digest (`docs/org/kpi/`) — read it
  for the org-KR context (what the org is optimizing for).
- **`kanban_7d`** — board task counts by state, recently-done tasks (with
  owner), and spend `byOwner` / `byModel` for the window.

Plus the live board via the `mcp_kanban` tools (`board_status` — open ideas,
in-flight tasks) and the Grafana **Product KPIs** dashboard for the trend
shape (the artifact gives the window; the dashboard gives the curve).

## Method

1. **Read the traffic, not the vanity numbers.** Per-site: what moved vs the
   prior window; which pages/countries carry it; custom events = feature
   usage (the only direct "what do users do" signal we have — weight it
   accordingly). Small windows: state the sample size, mark the signal
   `weak`/`moderate`/`strong`.
2. **Read the spend.** `byOwner`: which agent is burning (a spike = check the
   board for stuck tasks before assuming it's productivity). `byModel`: is
   work going to the right model (per-owner routing: strategist/marketing →
   `matrix-copywriter`)? Spend per shipped artifact is the unit cost the org
   should know.
3. **Read the board.** What shipped (recent done tasks), what's open, where
   the ideas cluster. Analytics without the board is a dashboard; the board
   without analytics is a wish list.
4. **Turn each signal into a prioritization input.** For every finding:
   the observation, the evidence ref (artifact path, board id, dashboard),
   the strength, and the PM action — one of: *ideate* (→ PM-4, with the
   evidence attached), *re-prioritize* (→ PM-5, with the rationale),
   *investigate* (→ a board card for the right owner), or *no action*
   (say why). No finding without an action label.
5. **Small-sample honesty.** The sites are new. A 7-day window with single-
   digit pageviews produces `weak` signals — the review's job is to set the
   baseline and name what to watch, not to over-fit (G4 rule: missing or
   thin data is reported as such, never estimated).

## Output

File the review at **`docs/roles/pm/analytics-review-<YYYY-MM-DD>.md`** (G12)
with this shape:

```markdown
# PM Analytics Review — <YYYY-MM-DD>

> **window:** <period> · **sources:** <plausible-kpi artifact, KPI digest,
> board, Grafana> · **serves:** <org/agent/KR tags>

## 1. Signal summary
Table: signal | data (value, delta) | strength (weak/moderate/strong) | action

## 2. Traffic & engagement
Per-site read + custom events (feature usage) + what to watch next window

## 3. Spend read
byOwner / byModel, spend per shipped artifact, anomalies + cause

## 4. Board read
What shipped, what's open, idea clusters vs the data

## 5. Prioritization inputs
The PM-4/PM-5 handoff: ideate / re-prioritize / investigate / no action,
each with its evidence ref. Board cards created (ids) per the G4 contract
(`docs/roles/business-analyst/report-contract.md`).
```

## Routing (G4 contract)

- Signals that need action → **board ideas/notes** with the review path in
  the body (the only routing that creates work).
- The review feeds the next PM-5 prioritization pass directly (it's the data
  column of the RICE/ICE rationale).
- Spend anomalies that look like a stuck agent → note on the owning agent's
  card + `security status`/`alerts.log` check (a spend spike is also a
  security signal — Phase 6).
