# Story card template, AC formats, and ready checklist

Read this when writing story cards (DEV-2 `story-breakdown`). Formats from R8
(`docs/research/R8-pm-artifacts.md` — Atlassian's story/AC/DoR/INVEST
guidance, Fowler's Given-When-Then, finish-to-start dependency mapping).

## Story card template

```markdown
## <Verb-led title — user-observable, e.g. "Show trip cost breakdown on the trip page">

**As a** <user/operator>, **I want** <goal>, **so that** <reason>.

**Acceptance criteria**
- <testable, outcome-focused statement — the result, not the recipe>
- <...>
- Given <state>
  When <action>
  Then <observable result>        <- GWT for concrete behavioral scenarios

**Tests** (story DoD — written during implementation, verified by qa-verify)
- <the executable test/check each AC maps to>

**Size:** S | M | L — basis: <complexity / unknowns / scope, one line>
**Priority:** ICE <n> (I <1-10>, C <1-10>, E <1-10>) — <one-line rationale>
**Dependencies**
- blocked_by: [<card ids>] — <one-line reason per edge>
- blocks: [<card ids>]
**Spec:** <board card / PRD / architecture doc link>
**Ready check:** independent ✓ | small ✓ | testable ✓   <- all three, or it doesn't start
```

## Acceptance-criteria formats

- **Default — checklist** of testable, outcome-focused statements. Plain,
  unambiguous, same interpretation across engineering/QA/operator.
- **Given/When/Then** — for concrete behavioral scenarios
  (state → action → observable result). Not every criterion needs GWT; use it
  where the behavior is stateful or sequence-dependent.
- **The rule:** every AC maps cleanly to one or more executable tests or
  checks. "Describe the result, not the recipe" — an AC that prescribes the
  implementation is over-specification (the card states what/why; the task
  agent decides how).

## Sizing

- **S/M/L by default** — relative effort/complexity, never calendar time
  (time estimates create false precision).
- Record the basis (complexity, unknowns, scope) so the estimate is auditable.
- **S** ≈ a focused change one task session can ship with tests.
- **M** ≈ multi-file or multi-component, still one task session with a plan.
- **L** ≈ exceeds the t-shirt ceiling — split it, or record why it stays L
  (and what makes it un-splittable).

## Ready checklist (hard gate)

| Check | Passes when |
|-------|-------------|
| Independent | no unresolved `blocked_by` (every blocking card done/accepted) |
| Small | at or under the t-shirt ceiling, or split |
| Testable | every AC maps to a check |

Soft checks (record at grooming): negotiable (what/why, not how), valuable
(priority score + rationale), estimable (has a size).

## Dependency map format

```markdown
# Dependency map — <spec/feature>

## Edges (finish-to-start only)
- <card B> blocked_by <card A> — <one-line reason>

## Critical path
<card A> → <card B> → <card C>   (longest blocked_by chain)

## Cycles
none   <- a cycle is a breakdown error: fix the edges, don't ship the map
```
