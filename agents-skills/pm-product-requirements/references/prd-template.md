# PRD template

The durable shape of a `pm-product-requirements` output. Source: R8
(`docs/research/R8-pm-artifacts.md`, Q1 — include/cut list for a one-operator
+ LLM team). 1–2 pages for a typical feature; the Summary section is required
for big bets, optional for small features.

```markdown
# <Feature name> — PRD
- Status: draft | grooming | approved | in-progress | done
- Participants: operator + <agent roles>
- Target date: <date or "unscheduled">

## Why (problem, customer POV, 1–3 sentences)
<who hits this, what it costs them today — the PR/FAQ Problem Paragraph
shape; connects to the org goal>

## Summary (one-paragraph "press release")
<heading + who it's for + what they gain — required for big bets>

## Requirements
<user stories: "As a [user], I want [goal] so that [reason]", each with
acceptance criteria:
  - default — a checklist of testable, outcome-focused statements
    ("describe the result, not the recipe")
  - Given/When/Then for concrete behavioral scenarios
    (state → action → observable result)
  - every AC maps to an executable test or check>

## Non-goals / out of scope
<explicit list — the negotiable boundary>

## Success metrics
<the one number or observable that decides success — from the idea's success
metric, made measurable>

## Dependencies
blocked_by: [<card ids>] / blocks: [<card ids>]   (finish-to-start only)

## Deploy path
<where the result lands — branch, blog path, media target — must match the
project constraints>

## Sizing & priority
size: S | M | L (basis: <complexity / unknowns / scope>) |
score: <ICE or RICE, with the inputs recorded separately>

## Open questions
<unresolved items — gates the "approved" status; each either resolved or
explicitly accepted with the risk named>
```

Cut from legacy PRDs (R8): requirements matrices, change logs,
org/stakeholder maps, marketing plans, formal sign-off workflows.

Ready gate ("approved" only when): no open questions (or each accepted with
the risk named); every requirement has testable ACs; the deploy path is named
and matches the project constraints; dependencies are recorded.
