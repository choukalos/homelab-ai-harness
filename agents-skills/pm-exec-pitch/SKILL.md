---
name: pm-exec-pitch
description: Write the one-page opportunity pitch to the exec — one-line opportunity, value at stake (quantified, or the equation plus how to measure it), evidence, 2–3 options with a recommendation, and the ask (the decision needed and by when). Use at the 'pitch new opportunities to execs' step of the Product Manager workflow (step 7), when a market analysis or prioritized opportunity needs an exec decision, or when asked to pitch an opportunity or request a decision.
---

# PM Exec Pitch

Opportunity → 1-page pitch to the exec — step 7 of the Product Manager
workflow. The exec (chuck) is the decision node: the pitch is the artifact he
decides on. Grounded in R8
(`docs/research/R8-pm-artifacts.md` — the pitch skeleton: problem paragraph +
press-release summary + score with inputs + bottom-up range + competitive
one-pager) and S9's no-fabrication discipline.

## When to use

- **Use it:** a market analysis (PM-1) or a prioritized opportunity (PM-5)
  needs an exec decision; a big bet needs approval before grooming (PM-2); or
  a direct ask to pitch / propose / request a decision.
- **Skip it:** a routine status update (that's the BA's exec status
  presentation) or a decision the board card already carries — don't
  re-pitch approved work.
- **Deep-dive version:** when the question is high-stakes (a structured
  problem, not an opportunity), delegate to S9 `exec-problem-brief` — the
  7-section board-ready brief. PM-3 is the 1-page version.

## Inputs

1. **The opportunity** — the board idea / PRD / PM-1 opportunity brief it
   supports (the pitch always supports a board item — the board is the
   record).
2. **The evidence** — research findings, data, competitive notes, sizing
   assumptions (from PM-1 / PM-4 / BA).
3. **The decision being asked** — what the exec must decide, and by when. If
   you can't name the decision, the pitch isn't ready.

## Method

1. **One-line opportunity.** One sentence the exec can repeat verbatim — the
   opportunity, not the project.
2. **Value at stake.** Quantified — the bottom-up range + assumption list
   from PM-1 (users × value per use). When data is missing, the **equation +
   the measurement method**, stated plainly (S9: never invent a figure).
3. **Evidence.** The research / data / competitive findings behind the claim
   — every claim sourced; the no-fabrication rule applies in full. This
   section is what separates a pitch from a wish.
4. **Options.** 2–3, with a recommendation — including "do nothing" when it's
   a real alternative (the strongest competitor for an internal tool is
   usually inaction). Each option: what it is, what it costs, what it gives.
5. **The ask.** The decision needed + by when (a date or a trigger). A
   decision, not a discussion — "approve option B by <date>", not
   "thoughts?"
6. **Deliver + link.** The pitch artifact goes to the exec (session report /
   board note); the board idea it supports gets the pitch linked.

## Rules

- **Answer-first** — the one-line opportunity + the ask up front; no
  preamble, no context dump (S9 discipline).
- **One page.** If it needs two, it's the S9 deep-dive, not a PM-3 pitch.
- **Every number sourced or an equation** — the no-fabrication rule is
  absolute; an unsourced figure kills the pitch's credibility.
- **The ask is a decision with a deadline** — a pitch without a decision is
  a status update.
- **The pitch supports a board item** — the board idea is the record; the
  pitch is the presentation.

## Output

1. **The 1-page pitch artifact** —
   `docs/roles/pm/pitches/<opportunity>-<YYYY-MM-DD>.md` (the G12 artifact
   conventions; `references/pitch-template.md` — read it when writing the
   pitch).
2. **The board link** — the pitch noted on the board idea it supports.

## Handoff

- **→ the exec (chuck):** the decision routes via the board — approved
  opportunities go to PM-2 (groomed into a PRD); rejected ones get the
  reason recorded (icebox / discard, per PM-5).
- **→ PM-2 `pm-product-requirements`:** an approved bet gets groomed into
  the PRD.
- **→ S9 `exec-problem-brief`:** the escalation path for high-stakes
  questions.
