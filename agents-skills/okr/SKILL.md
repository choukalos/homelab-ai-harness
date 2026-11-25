---
name: okr
description: "OKR workflow for the homelab agent org — writes org + agent OKRs per domain (homelab, bluebovine), ladders agent objectives and KRs to org goals, runs the alignment check (no orphans, no activity-metric KRs, full coverage), and emits the artifacts (docs/org/goals.md, charter drafts, alignment report). Use when setting or updating org goals, drafting or reviewing an agent charter's objectives + KRs, checking whether work actually serves the goals (ladder alignment, serves tags), or closing out an OKR cycle (KR scoring, next cycle's draft)."
---

# OKR — org + agent goal workflow

Write org + agent OKRs for the homelab agent org and verify the ladder — that
agent work actually serves the org's goals. The agent org is a control system;
OKRs are the setpoints. This skill is the tool for the monthly org cycle and
for ad-hoc goal work between cycles.

Grounding — OKR Institute OKR-driven agentic pattern (outcomes over outputs,
mandatory quality KR, human decision rights, close the loop); Webex
goal-writing do's/don'ts (short purpose-only mission lines); the 2026-11-24/25
decisions in `todo_agentic_framework.md` (goal model, org-goal anchoring,
charter workflow).

## When to use

- Setting or updating org goals (monthly org review, or on chuck's explicit
  direction)
- Drafting or reviewing an agent charter's objectives + KRs from the org goals
- Ladder alignment check — "is the work actually serving the goals?"
- OKR cycle closeout — KR scoring → retro → next cycle's draft

## Inputs

- `docs/org/goals.md` — per-domain org goals. If it doesn't exist, this is the
  first pass — ground in `homelab_vision.md` + the anchoring decisions in
  `todo_agentic_framework.md` (org-goal anchoring section).
- Board state — `mcp_kanban` board status; what work exists / is in flight,
  `serves:` tags on cards.
- `docs/org/kpi/YYYY-WW.md` — the BA's weekly KPI digest (when it exists).
- `docs/agents/<slug>/reviews/` — prior-cycle records.
- `docs/agents/<slug>/charter.md` — existing charters (objectives/KRs
  sections).

## The ladder (must hold)

```
ORG GOAL (per domain) → AGENT OBJECTIVE (linked) → KR → TASK
```

- **Domains in scope** — homelab, bluebovine. **InvestHub is out of scope for
  agents** (chuck's own; no org goals, no agents).
- **Agents** — `product` (PM), `analyst` (BA), `strategist` (marketing
  strategist), `marketing` (content marketer). A researcher is not in the
  roster (yet).
- **Task tags** — every task (kanban card or direct TODO) carries a `serves:`
  tag — `org/<domain>/<O#>-KR#`, `agent/<agent>/<O#>-KR#`, `exec` (chuck's
  direct directive — always wins), or `bau` (business-as-usual).
- **Enforcement is soft** — unmapped work is *flagged* at review, never
  blocked. The work-mix check (bau vs OKR vs exec) is how the mix gets
  steered.

## Workflow

### 1. Frame the domain

Which domain(s) this pass covers; what changed since the last cycle — board
movement, BA KPI data, chuck's direction, review records. State it in one
short paragraph at the top of the alignment report.

### 2. Draft org objectives

1–2 per domain per cycle; 3 only with an explicit justification (surface it in
the alignment report). Objective in **outcome language** — "make X feel
effortless for Y", not "deploy Z". One sentence each.

### 3. Write KRs

2–4 per objective. Every KR gets the four fields — **definition, source,
target, cadence**. Rules:

- **Outcomes over activity** — "N posts written" is a leading indicator, not
  the KR; the KR is the outcome the posts drive. Labeled leading indicators
  are allowed alongside.
- **No data? Guess** — mark the KR `proxy` with a validation note ("validate
  when Plausible/data-hub lands"). First passes are guesses by design — but a
  KR with *no* machine check (not even a deferred one) is rejected.
- **Mandatory quality/safety KR** on every domain and every agent — e.g.
  "0 published pieces that failed content QA", "0 PRDs without acceptance
  criteria".
- **Machine-measurable** — every KR reduces to a check (test, metric,
  artifact state, resolvable citation, published record). No check → not a
  KR.

### 4. Derive agent objectives

For each in-scope agent — 1–2 objectives, each **explicitly laddered** to a
domain org goal (cite the org goal it serves); 2–4 KRs per objective (same
four-field + quality-KR rules). Charters are agent-suggested →
chuck-approved: this step produces the **draft** for chuck's review, never a
final charter.

### 5. Alignment check (the core value)

Run every check; report pass/fail per item:

- every agent objective maps to a domain org goal (no orphans)
- every KR has definition/source/target/cadence (or is explicitly `proxy`)
- no activity-metric KR dressed up as an outcome
- **coverage** — every org goal is served by ≥1 agent (or explicitly marked
  "chuck-only" / "no agent yet")
- work-mix read — `serves:` tags on in-flight work vs the goals (flag
  unmapped work; don't block it)

Emit the **alignment report** (template below) — it ships with every pass.

### 6. Emit artifacts

- `docs/org/goals.md` — per-domain sections, updated **in place** with an
  "updated <date>" note (living doc — never a new file per cycle).
- Agent charter drafts — objectives/KRs sections only, for chuck's review
  (charter home — `docs/agents/<slug>/charter.md`; chuck approves).
- The alignment report.

## Cycle closeout (monthly org review)

The monthly org review is the only scheduled place goals may change (or
chuck's explicit direction mid-cycle). Procedure:

1. Score every KR 0.0–1.0 against its check; 0.6–0.7 on a stretch KR is a
   *success* — don't punish ambition.
2. Short retro — what the loops caught, what they missed.
3. Rewrite next cycle's objectives/KRs. Phases shift at the boundary (e.g.
   bluebovine product track define → iterate) — rewrite, don't append.
4. Record at `docs/org/reviews/YYYY-MM.md`; update `docs/org/goals.md` in the
   same pass.

## Quality bar (reject the pass if any fail)

- objectives in outcome language, 1–2 per domain (3 justified)
- 2–4 KRs per objective; every KR has the four fields
- proxy KRs flagged with validation notes; quality/safety KR present on every
  domain + every agent
- ladder links explicit; alignment report ships with the pass

## Gotchas

- **Strict YAML** in any frontmatter you touch — an unquoted `: ` (colon +
  space) in a description field breaks client skill loading (repo convention:
  em dash or quote the value).
- **Don't write InvestHub goals** — out of scope for agents.
- **Don't invent agents** — the roster is the four slugs above.
- **Goals change at the cycle boundary or on chuck's direction** — not on an
  agent's initiative; between cycles the skill may *flag* drift, not rewrite
  goals.
- **Proxy KRs are fine, silent KRs are not** — a guess marked `proxy` is
  honest; an unmeasurable KR with no deferred check is a hope, not a KR.
- **Charter drafts are drafts** — the agent suggests, chuck approves; never
  write a final charter without his sign-off.

## Alignment report template

```markdown
# OKR alignment report — <date> — <cycle / ad-hoc>

## Framing
<one short paragraph — domains covered, what changed since last cycle>

## Alignment table
| Org goal (domain) | Agents serving | KRs | Data-source status |
|---|---|---|---|
| O1 <outcome language> | marketing | KR1 (proxy), KR2, KR3 (quality) | Plausible not wired — proxy |

## Checks
- [ ] every agent objective maps to a domain org goal (no orphans)
- [ ] every KR has definition/source/target/cadence (or explicit proxy)
- [ ] no activity-metric KR dressed as an outcome
- [ ] coverage — every org goal served or marked chuck-only / no agent yet
- [ ] work-mix read — unmapped work flagged (not blocked)

## Flags
<unmapped work, at-risk KRs, justified 3rd objectives, drift notes>
```
