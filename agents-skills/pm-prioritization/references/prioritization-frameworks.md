# Prioritization frameworks — scales and worked examples

The scoring reference for `pm-prioritization`. Source: R8
(`docs/research/R8-pm-artifacts.md`, Q6 — formulas and scales verified from
the origin posts).

## ICE (the default — no usage data)

`ICE score = Impact × Confidence × Ease`, each rated 1–10.

- **Impact** — how much the idea moves the target metric (the org goal or the
  idea's success metric). 10 = a step change; 5 = clearly useful; 1 =
  marginal.
- **Confidence** — how certain we are it will have the predicted impact.
  10 = we've seen it work / the evidence is direct; 5 = plausible, untested;
  1 = a guess.
- **Ease** — the inverse of effort. 10 = a day's work; 5 = a week-ish; 1 = a
  multi-month project.

Worked example: an idea that would clearly improve the goal (Impact 8), is
well-evidenced (Confidence 7), and is a few days of work (Ease 8) →
8 × 7 × 8 = 448. Record the three inputs + the rationale, then the product.

## RICE (upgrade when usage data exists)

`RICE score = (Reach × Impact × Confidence) / Effort` — "total impact per
time worked."

- **Reach** — how many users the project affects in a defined period (e.g.
  "3 sites × ~N visitors/month" from Plausible once G3 lands).
- **Impact** — multiple choice: 3 (massive) / 2 (high) / 1 (medium) / 0.5
  (low) / 0.25 (minimal).
- **Confidence** — 100% (high) / 80% (medium) / 50% (low).
- **Effort** — total person-months across the work, whole numbers, minimum
  0.5. Don't get into the weeds of estimation.

Worked example: (Reach 300 × Impact 2 × Confidence 0.8) / Effort 0.5 = 960.

Documented misuses (R8): bias toward pet ideas and clever ideas; "RICE scores
shouldn't be used as a hard and fast rule" — a lower-scoring project may have
to go first because it's a dependency, or another feature may be table
stakes.

## Kano (long feature lists only)

Classify by the customer's emotional response, not benefit/cost (R8):

- **must-be** — expected; absence causes dissatisfaction, presence is taken
  for granted. Build all — they're cheap.
- **performance** — more = more satisfaction, linear. Score normally.
- **attractive** — delighters; absence doesn't hurt, presence delights. Pick
  a few.
- **indifferent** — no effect. Cut.

Misuses: highly quantitative and time-consuming; categories drift (today's
delighter becomes tomorrow's must-be); without real customer data it encodes
the operator's own preferences — say so when it does.

## Choosing

| Situation | Framework |
|---|---|
| No data, many ideas, fast decision | ICE (dot voting first for convergence) |
| Real usage data exists | RICE (Reach measured, not guessed) |
| Long feature list, table-stakes vs delighter | Kano classification |
| Two ideas, gut call | value/effort quadrant or operator judgment — record the rationale either way |

## Overrides that beat the score

1. **Dependency prerequisites** — the lower-scoring project that the higher
   one needs goes first.
2. **Operator veto** — chuck's call; record it as an override, not a
   re-score.
3. **Table stakes** — expected features don't need a high score to be built.
