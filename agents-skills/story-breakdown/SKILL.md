---
name: story-breakdown
description: Break a spec/PRD (or architecture doc) into buildable stories — independently shippable vertical slices, each with testable acceptance criteria, an S/M/L size with rationale, explicit dependencies (blocked_by/blocks), and a ready check. Use at the "groom/break down stories" step of the Coding Team workflow (step 2, after architecture, before coding), when a board spec needs to become a backlog, or when a story is too big to start.
---

# Story Breakdown

Spec → stories: buildable cards with acceptance criteria, a dependency map,
and sizing — step 2 of the Coding Team workflow. Grounded in R8
(`docs/research/R8-pm-artifacts.md` — story shape, acceptance-criteria
formats, definition of ready, INVEST, sizing, dependency mapping for a
kanban board with icebox).

## When to use

- A board spec/PRD (or DEV-1 `architecture` doc) needs to become a backlog.
- A story fails "ready" (too big, not independent, untestable) — split it or
  record the dependency edge; don't start it.
- Periodic grooming: the board has cards that no longer satisfy the ready
  definition.

## Inputs

1. **The spec/PRD** — or the architecture doc's component list (every
   component maps to an owned story; if a component can't be named as a
   story, it's too big or imaginary — split or delete).
2. **Board state** — existing cards (dedupe before creating), icebox
   (what's parked and why), project `constraints`.

## Breakdown rules

- **Vertical slices, independently shippable.** Each story delivers a sliver
  of end-to-end value — *not* "all the database work" or "all the UI". The
  test: could this story ship and be observed by a user (or operator) on its
  own? If not, it's a task inside a story, not a story.
- **Each story carries its tests** (the program's G5 decision): acceptance
  criteria → tests *during implementation*; tests are part of the story's
  definition of done, not just post-hoc QA (S3 `qa-verify` verifies).
- **Acceptance criteria — testable, outcome-focused.** "Describe the result,
  not the recipe." Default: a checklist of testable outcome statements; use
  Given/When/Then for concrete behavioral scenarios (state → action →
  observable result). **Every AC maps to an executable test or check** — an
  AC that can't be checked isn't an AC.
- **Size S/M/L with rationale.** Relative effort/complexity, not calendar
  time (time estimates create false precision). Record the basis —
  complexity, unknowns, scope — so the estimate is auditable. If a story
  exceeds the team's t-shirt ceiling, split it.
- **Explicit dependencies.** `blocked_by: [<card id>]` / `blocks:
  [<card id>]` — finish-to-start only ("B can't start until A is done").
  LLM grooming proposes the edges (it sees the whole board); the operator
  confirms them.
- **Split or record — don't start unready.** If a story fails "independent"
  or "small", either split it or write the dependency edge. Starting an
  unready story is how boards clog.

## Definition of ready (hard gate before a story enters In Progress)

A story is ready when:

1. **Independent** — no unresolved `blocked_by` (every blocking card is
   done/accepted).
2. **Small** — splittable further if it exceeds the t-shirt ceiling.
3. **Testable** — every acceptance criterion maps to a check.

Soft checks at grooming (record, don't gate):

- **Negotiable** — the card states the *what* and *why*, not the *how*
  (implementation detail stays open to the task agent).
- **Valuable** — has a priority score with rationale (ICE by default —
  Impact × Confidence × Ease, each 1–10; record the inputs, not just the
  score).
- **Estimable** — has a size.

## Output

1. **Story backlog on the board** — one card per story, using
   `references/story-template.md` (read it when writing the cards).
2. **The dependency map** — every edge with a one-line reason, plus the
   critical path (the longest blocked_by chain). Call out any cycle — a
   dependency cycle is a breakdown error, not a board state.

Card fields: title (verb-led, user-observable), the story template body,
`blocked_by`/`blocks`, size + basis, priority score + inputs, links to the
spec/PRD and (if any) the architecture doc.

## Icebox hygiene (while grooming)

Two sub-states, not a graveyard:

- **`needs-definition`** — needs more discussion/planning before it can
  start. Stays visible in the backlog view with a tag (tag it, don't icebox
  it).
- **`parked`** — out of scope or very low priority. Hidden from the working
  board.

A periodic icebox review promotes or kills parked items — "stories go to die"
is the named failure mode.

## Handoff

- **→ Coding (step 3):** each ready story is a task — S2 `codebase-recon` →
  implement (stories carry their tests) → S4 `git-flow`.
- **→ QA (steps 4–6):** S3 `qa-verify` (functionality) → S11
  `security-code-review` (hard gate) → S10 `code-reviewer` (static).
- **→ PM:** stories the operator can't size or that keep failing "ready"
  go back to the spec — a breakdown that can't produce ready stories means
  the spec has open questions.
