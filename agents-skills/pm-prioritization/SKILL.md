---
name: pm-prioritization
description: Choose which board ideas to groom next — an explicit prioritization framework (ICE by default, RICE when usage data exists, Kano for long feature lists) applied consistently, strategy fit, a written rationale per choice, and a disposition with a reason for every idea that loses (groom, icebox, discard, or not-now). Use at the 'choose ideas' step of the Product Manager workflow (step 4), when the idea pipeline has accumulated, or when asked to prioritize, rank, or triage product ideas.
---

# PM Prioritization

Choosing which ideas to groom — step 4 of the Product Manager workflow.
Fills gap G2 (the workflow audit): prioritization had no framework, no
written rationale, and losing ideas got silence. Grounded in R8
(`docs/research/R8-pm-artifacts.md` — RICE/ICE/Kano formulas, scales,
documented misuses, overrides, the calibration guard, icebox hygiene).

## When to use

- **Use it:** the idea pipeline has accumulated (`board_status` →
  `ideaCounts` growing), a periodic grooming cadence, or a direct ask to
  prioritize / rank / triage product ideas.
- **Skip it:** one idea, an obvious call — record the one-line rationale on
  the card and groom it; a framework for a single item is ceremony.

## Inputs

1. **The idea list** — `list_ideas` on the product project (the pipeline +
   icebox, with the evidence attached by PM-4).
2. **Strategy context** — the current goals; "strategy fit" is fit against
   *these*, not against whatever feels important this week.
3. **Usage data, if it exists** — Plausible is not wired yet (gap G3), so the
   default is ICE; when real usage data lands, upgrade to RICE (Reach
   becomes measurable).
4. **Icebox state** — what's parked and why (re-visit parked items that now
   have new evidence).

## Method

1. **Pick one framework — and keep it consistent within the pass** (R8):
   - **ICE — the default** (no usage data): Impact × Confidence × Ease, each
     1–10. ICE is RICE with Reach dropped and Effort inverted — the right
     default when you can't measure reach.
   - **RICE — when real usage data exists:** (Reach × Impact × Confidence) /
     Effort. Origin-post scales — Impact 3 (massive) / 2 (high) / 1 (medium)
     / 0.5 (low) / 0.25 (minimal); Confidence 100% / 80% / 50%; Effort in
     whole person-months, minimum 0.5, don't get into the weeds.
   - **Kano — only for long feature lists:** classify must-be / performance /
     attractive / indifferent; build all must-be (expected, cheap), pick a
     few attractive, cut indifferent.
   The scales and worked examples live in
   `references/prioritization-frameworks.md` (read it when scoring).
2. **Score with inputs recorded.** Store Reach/Impact/Confidence/Effort (or
   I/C/E) *separately* with a one-line rationale each — not just the product.
   PM-3's pitch and any future re-scoring need the inputs.
3. **Apply strategy fit.** A high score that doesn't serve the current goals
   loses to a lower score that does — record which, and why.
4. **Let the overrides beat the score** (R8): dependency prerequisites ("one
   project may be a dependency for another, so it needs to happen first"),
   the operator's veto, and table-stakes features. An override is a written
   decision, not a silent re-ordering.
5. **Calibration guard.** After the first sort, re-score and challenge the
   outliers — "is this score too high or too low?" If inputs changed between
   items mid-pass, flag it: the method is subjective and inconsistent when
   scales drift (R8).
6. **Dispose of every idea — losers get a reason, not silence:**
   - **Groom** — the shortlist (top N that fit); hand off to PM-2.
   - **Icebox** — parked, with a sub-state: `needs-definition` (needs more
     discussion — stays visible in the backlog view with a tag) or `parked`
     (low priority / out of scope — hidden from the working board).
   - **Discard** — with the reason on the record (`discard_idea`, soft
     delete; the audit trail keeps it). Note: `discard_idea` works on
     idea/grooming state only — an icebox item that's really dead gets moved
     to the backlog and marked there (S1).
   - **Not now** — stays in the pipeline with the reason (e.g. "re-score when
     G3 lands and Reach is measurable").

## Rules

- **One framework per pass** — mixing ICE and RICE in one list is how scores
  stop meaning anything.
- **Inputs, not just scores** — a score without its inputs is un-auditable.
- **Every loser gets a reason** — silence is the failure mode this skill
  exists to kill (G2).
- **Blocked ideas don't score into the WIP** — cards with unresolved
  `blocked_by` are excluded from the shortlist until unblocked (R8 gate).
- **Icebox hygiene** — a periodic icebox review promotes or kills parked
  items; "stories go to die" is the named failure mode (R8).

## Output

- **The prioritized shortlist + rationale** — recorded on the board (idea
  notes / spec notes: score, inputs, strategy fit, overrides) and in the
  session report. A durable copy at
  `docs/roles/pm/prioritization-<YYYY-MM-DD>.md` when the pass is
  significant (a quarterly groom, a strategy shift) — the G12 artifact
  conventions.
- **The disposition list** — every idea in the pipeline with its outcome
  (groom / icebox / discard / not-now) + the reason.

## Handoff

- **→ PM-2 `pm-product-requirements`:** the shortlist gets groomed into PRDs.
- **→ the board:** dispositions land as state changes (`move_to_backlog`,
  `discard_idea`, notes) — the board is the record.
- **→ PM-3 `pm-exec-pitch`:** a shortlisted idea that is really an
  investment decision gets a 1-page pitch before grooming.
