---
name: pm-product-requirements
description: Turn a groomed board idea into the PRD — problem statement, goals and non-goals, user stories with testable acceptance criteria, success metrics, scope, dependencies, and deploy path — so the coding team can build it without guessing. Use at the 'create product requirements' step of the Product Manager workflow (step 5), during or after the kanban grooming loop, when an idea needs to become a spec the Coding Team can pick up, or when a spec has open questions blocking development.
---

# PM Product Requirements

Idea → PRD — step 5 of the Product Manager workflow. The groomed spec *is*
the PRD: the PM's side of the kanban grooming loop (S1 `kanban-board`) plus
the PRD shape. Grounded in R8
(`docs/research/R8-pm-artifacts.md` — PRD template shape for a one-operator
+ LLM team, acceptance-criteria formats, definition of ready, the
spec-driven pipeline: spec → clarify → plan/tasks).

## When to use

- **Use it:** an idea was chosen for grooming (from PM-5
  `pm-prioritization`); the grooming loop needs the PM's side (which
  questions to ask, which assumptions to state); a spec has open questions
  that block development.
- **Skip it:** the idea is already a well-formed spec with testable
  acceptance criteria and a named deploy path — verify the ready gate and
  hand off.

## Inputs

1. **The idea** — the board card + its evidence (from PM-1 / PM-4: the value
   hypothesis, success metric, signal links).
2. **Strategy context** — the goal the idea serves (the PRD's "why" must
   connect to it).
3. **Project constraints** — the kanban project `constraints` (deploy gates,
   trust boundary) — the deploy path must match them.
4. **Board state** — existing cards for the `blocked_by` / `blocks` edges.

## Method

1. **Run the grooming loop** (S1 `kanban-board`): `start_grooming` →
   `groom_message` → `groom_accept` (poll `groom_status` until the spec
   lands). The PM's job inside the loop — the grooming LLM researches and
   asks; the PM steers:
   - **Ask the questions that shape the PRD** — scope (what's in, what's
     explicitly out), success criteria (how "done" is measured — the idea's
     success metric, made testable), the deploy path (where the result
     lands), dependencies on other icebox items.
   - **State assumptions explicitly** — the user (or exec) corrects them; an
     unstated assumption is a future re-groom.
   - **Challenge the solution before the problem is clear** — if the
     conversation is about *how* before *what/why*, steer it back.
2. **Write the PRD** — `references/prd-template.md` (read it when writing).
   1–2 pages for a typical board feature; the PR/FAQ-style narrative (the
   press-release summary section) is required for big bets (new
   services/pipelines) and optional for small features.
3. **Follow the spec-driven pipeline** (R8): spec (this doc) → clarify
   (grooming — the conversation that resolves the open questions) →
   plan/tasks (DEV-2 `story-breakdown`). Requirements-First is the default;
   Design-First only when an existing architecture or strict NFRs drive the
   work. Keep the constitution-level rules (repo conventions, quality gates)
   out of the per-feature PRD.
4. **Run the ready gate** — the PRD is *approved* only when:
   - no open questions (or each is explicitly accepted as open, with the
     risk named),
   - every requirement has testable acceptance criteria (a checklist of
     outcome statements by default; Given/When/Then for concrete behavioral
     scenarios — "describe the result, not the recipe"; every AC maps to an
     executable check),
   - the deploy path is named and matches the project constraints,
   - dependencies are recorded (`blocked_by` / `blocks`, finish-to-start).

## Rules

- **The PRD states the what and the why, not the how** — implementation
  detail stays negotiable for the task agent (R8: the story's "Conversation"
  C). A PRD that dictates the implementation is over-specification.
- **No fabricated figures (S9 discipline)** — targets and estimates are
  ranges with assumptions, or the equation + the fastest test.
- **Cut the legacy PRD baggage** (R8): no requirements matrices, change
  logs, org/stakeholder maps, or sign-off workflows — one-operator shop.
- **Success metrics are explicit** — the BA loop (Phase 3) measures against
  them; a PRD without a success metric can't be evaluated after it ships.
- **Non-goals are mandatory** — the explicit out-of-scope list is the
  negotiable boundary; scope creep without a re-groom is how boards clog.

## Output

1. **The PRD** — the board spec carries it (the grooming finalize produces
   the structured spec); the durable home is
   `docs/roles/pm/prds/<feature>.md` (the G12 artifact conventions) — file
   it there when the work lands (S5 `docs-housekeeping`).
2. **The ready-gate result** — approved (with the gate evidence) or the open
   questions that block approval.

## Handoff

- **→ Coding Team:** an approved PRD is picked up as a task — DEV-2
  `story-breakdown` breaks it into stories (every requirement with testable
  ACs becomes a story with its tests).
- **→ PM-3 `pm-exec-pitch`:** a big bet gets a 1-page pitch (or S9
  `exec-problem-brief`) *before* grooming — the exec approves the bet, then
  the PRD gets built.
- **→ the board:** the spec's `depends_on` edges + the deploy path are the
  coordination record.
