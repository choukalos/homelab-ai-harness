---
name: pm-ideation
description: Turn product signal into candidate board ideas — problem-first ideation (the user's problem before the solution), every idea linked to evidence, a dedupe check against existing ideas before adding, and the idea template (value hypothesis, target user, success metric, rough size). Use at the 'ideate features / solve issues' step of the Product Manager workflow (step 3), when market analysis or analytics findings produced signal to convert, or when asked to brainstorm or generate product ideas for the board.
---

# PM Ideation

Signal → candidate board ideas — step 3 of the Product Manager workflow.
Fills gap G1 (the workflow audit): the ideation step had no framework, no
dedupe discipline, no idea shape. Grounded in R8
(`docs/research/R8-pm-artifacts.md` — idea staging, dot-voting convergence,
the Kano pass) and S9's no-fabrication discipline.

## When to use

- **Use it:** a PM-1 `pm-market-analysis` opportunity brief or a BA insight
  report just landed and the signal needs converting into ideas; user
  feedback accumulated; or a direct ask to brainstorm / generate product
  ideas for the board.
- **Skip it:** the signal is a single well-understood fix — it's an idea
  already; dedupe-check it and `add_idea` directly. And don't ideate to fill
  silence — no signal, no session (ideas without evidence are pet projects).

## Inputs

1. **The signal** — a PM-1 opportunity brief, a BA report/insight, user
   feedback, or an incident/blocker pattern. Name the source(s) explicitly —
   every idea below traces to one. (Product analytics from Plausible are not
   wired yet — gap G3; until then the BA reports and board state are the data
   sources.)
2. **Board state** — `list_ideas` on the relevant project (the dedupe base).
3. **Strategy context** — the current goals, so ideas can be framed against
   what the org is optimizing for.

## Method

1. **Problem-first.** For every candidate, state the *user's problem* before
   the solution — "user X struggles with Y when Z." The solution is a
   hypothesis attached to the problem, never the idea itself. An idea that
   starts with a solution ("build a dashboard") goes back to step 1.
2. **Link the evidence.** Each idea carries the signal it came from — the
   opportunity, the data point, the feedback quote. No evidence link → the
   idea is a pet project; label it as such or drop it (S9 discipline: never
   invent the evidence — state the equation + the fastest test when data is
   missing).
3. **Dedupe before adding.** `list_ideas` on the project (ideas + icebox)
   before any `add_idea`. Near-duplicate? Strengthen the existing idea with
   the new evidence (`edit_idea` works in `idea` state) — don't add a second
   card for the same problem.
4. **Shape each idea with the template** — `references/idea-template.md`
   (read it when writing the cards): value hypothesis (if X, then Y, because
   Z), target user, success metric (how we'll know it worked), rough size
   (S/M/L), evidence link, Kano class (must-be / performance / attractive /
   indifferent — R8).
5. **Converge the list** (when it's long):
   - **Dot voting** — each participant (operator + agents) gets a fixed
     number of tokens; the board becomes a heat map (R8).
   - **Kano pass** on the shortlist — must-be = expected (build all,
     they're cheap); attractive = pick a few; indifferent = cut.
   - **1-10-100 framing** — the value of ideas is distributed in orders of
     magnitude, so the job is to find the 10× idea rather than rank the 1×
     ones. *Unverified from a primary source (R8 open question) — use it as a
     framing device and mark it as such in the output, never as a citation.*
6. **Add to the board.** `add_idea` on the product project, one idea per
   problem, template body in the idea text. Raw ideas land in the idea
   pipeline (the staging area) — not directly in the backlog (R8). Board
   ops: S1 `kanban-board`.

## Rules

- **Problem before solution** — the problem statement is the idea; the
  solution is a hypothesis.
- **Every idea linked to evidence** — or explicitly labeled a pet project.
- **The dedupe check is not optional** — `list_ideas` before every `add_idea`
  batch; the board's dedupe failure mode is duplicate cards dying in the
  icebox.
- **Rough size, not a plan** — S/M/L with a one-line basis; detailed sizing
  happens at grooming (PM-2) and breakdown (DEV-2).
- **Don't groom here** — ideation produces ideas ready for *prioritization*
  (PM-5), not specs.

## Output

- **Board ideas ready for grooming** — the idea IDs + a one-line rationale
  each, in the session report. No durable file by default — the board is the
  artifact; the PM-1 brief carries the research.

## Handoff

- **→ PM-5 `pm-prioritization`:** the shortlist gets scored and dispositioned.
- **→ PM-2 `pm-product-requirements`:** chosen ideas get groomed into PRDs.
- **→ BA:** ideas that turn out to be data questions (we can't tell without
  measurement) get routed back as measurement asks — the G3 wiring closes
  this loop.
