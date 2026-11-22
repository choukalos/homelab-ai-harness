# Trigger eval protocol

How to test whether a skill's `description` fires on the right prompts and not the
wrong ones. Based on the Agent Skills guide "Optimizing skill descriptions"
(agentskills.io/skill-creation/optimizing-descriptions, fetched 2026-11-22 — see
`authoring-best-practices.md` sources).

Use this when: a skill fails to trigger (or over-triggers) in real use; when
optimizing a description; or as part of the smoke test for a new skill with a
high-stakes trigger (gates, security, publish paths).

## 1. Build the query set

~20 realistic user prompts, labeled `should_trigger: true/false`:

- **8–10 should-trigger** — vary along four axes:
  - *Phrasing*: formal, casual, typos/abbreviations.
  - *Explicitness*: some name the domain directly, some describe the need without
    naming it.
  - *Detail*: terse one-liners alongside context-heavy prompts.
  - *Complexity*: single-step tasks alongside multi-step workflows where the skill's
    job is buried in a larger chain.
  - The most useful positives are ones where the skill would help but the connection
    isn't obvious from the query alone.
- **8–10 should-not-trigger** — the valuable ones are **near-misses**: queries that
  share keywords/concepts with the skill but actually need something different.
  ("Write a fibonacci function" tests nothing; "update the formulas in my Excel
  budget spreadsheet" when the skill is CSV analysis tests precision.)
- **Realism**: file paths, personal context ("my manager asked me to…"), specific
  details, casual language.

## 2. Run

- Run each query **3 times** (model behaviour is nondeterministic) with the skill
  available; count how many times the skill was actually loaded/consulted.
  - In a pi session: the skill is "triggered" when the agent reads the SKILL.md (or
    explicitly invokes `/skill:<name>`); not triggered when it proceeds without it.
  - In a kanban worker: check the task log for the skill being loaded.
- **Trigger rate** = fraction of runs the skill was invoked.
- A should-trigger query passes if trigger rate **> 0.5**; a should-not-trigger
  query passes if trigger rate **< 0.5**.

## 3. Split to avoid overfitting

- **Train (~60%)** — used to identify failures and guide description changes.
- **Validation (~40%)** — set aside; only used to check whether changes generalize.
- Both sets keep a proportional mix of positives/negatives; keep the split fixed
  across iterations.

## 4. Optimize loop (≈5 iterations)

1. Evaluate on train + validation.
2. From **train failures only**: should-trigger misses → description too narrow
   (broaden scope, add context); false triggers → too broad (state what it does
   *not* do, clarify the boundary with adjacent skills).
3. Revise with **generalization**: don't add the specific keywords of failed queries
   (that's overfitting) — name the general category those queries represent. If
   stuck after a few iterations, try a structurally different description rather than
   incremental tweaks. Keep under 1024 characters (descriptions grow during
   optimization).
4. Repeat until all train queries pass or improvement stops.
5. **Select the best iteration by validation pass rate** — the best description may
   not be the last one (later ones can overfit the train set).

If performance isn't improving after ~5 iterations, the problem is likely the
queries (too easy/hard, mislabeled), not the description.

## 5. Apply and verify

1. Update the `description` in the frontmatter.
2. Verify it's under 1024 characters and still strict-YAML-safe (no unquoted `: `).
3. Sanity check: 5–10 **fresh** queries (never seen during optimization), mixed
   should/should-not — an honest check that the description generalizes.
4. Re-register in the Skill Hub if the description changed
   (`scripts/skill-hub-register.sh` updates existing registrations).

## Scale note

The full protocol (20 queries × 3 runs = 60 invocations) is for high-stakes skills.
For a routine skill, a **lite version** is acceptable: 4–6 queries (2 obvious
positives, 1 near-miss positive, 2 near-miss negatives), 1–2 runs each, manual
observation in real sessions. Record the lite result in the skill's "applied +
verified" note.
