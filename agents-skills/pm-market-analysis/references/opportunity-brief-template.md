# Opportunity brief template

The durable artifact of a `pm-market-analysis` run. One file per area per
run: `docs/roles/pm/market-analysis-<area>-<YYYY-MM-DD>.md`.

```markdown
# <Area> — market analysis
- Date: <YYYY-MM-DD>
- Question: <the one-sentence decision frame — what decision this feeds>
- Status: draft | done

## Competitive landscape
Per alternative (the 2–3 closest + the "do nothing / shell script" column):
- <Alternative> — what they do; positioning (who / what problem / why them); gaps

Feature matrix:

| Capability | Us today | <Alt 1> | <Alt 2> | Do nothing |
|---|---|---|---|---|
| <capability> | <state> | <state> | <state> | <state> |

- Why them (top alternative): <one honest paragraph>
- Why us: <one honest paragraph>

## Market signals
- <signal> — source: <link>; date: <date>
- <signal> — [inferred] (flag every unsourced signal)

## Opportunities
Per opportunity (each becomes a board idea):

- **<Opportunity name>** (board idea: <id>)
  - Gap/signal it comes from: <ref above>
  - Size (bottom-up, range): <users> × <value per use> = <range>
  - Assumptions: <explicit list>
  - Evidence: <source links>
  - Fastest test (when data is missing): <the equation + the cheapest check>

## What I did not verify
<honest list — paywalled data, bot-blocked sources, thin coverage>
```

Rules: every claim sourced or flagged; sizes are ranges with an explicit
assumption list (never point estimates, never invented figures); the "do
nothing" column is present; unsourced signals are labeled `[inferred]`.
