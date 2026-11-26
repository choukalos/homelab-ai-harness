# Org Goals

> Living doc — org-level OKRs per domain. Updated **in place** with an
> "updated <date>" note (never a new file per cycle).
>
> **Cadence** (chuck 2026-11-24): org goals reviewed **monthly** — the monthly
> org review is the only scheduled place goals may change (or chuck's explicit
> direction mid-cycle). Agent reviews weekly to start.
> **Authorship**: chuck, with the `okr` skill (S13).
> **Ladder**: ORG GOAL (per domain) → AGENT OBJECTIVE (linked) → KR → TASK.
> Every task carries a `serves:` tag — `org/<domain>/<O#>-KR#`,
> `agent/<agent>/<O#>-KR#`, `exec` (chuck's direct directive — always wins),
> or `bau`. Enforcement is **soft**: unmapped work is flagged at review, never
> blocked; the work-mix check (bau vs OKR vs exec) steers the mix.
>
> **Domains in scope**: homelab, bluebovine. **InvestHub is out of scope for
> agents** (chuck's own — no org goals, no agents; may re-enter scope later).
> **Agents**: `product` (PM), `analyst` (BA), `strategist` (marketing
> strategist), `marketing` (content marketer).
>
> **KR rules**: every KR has definition / source / target / cadence. Outcomes
> over activity (labeled leading indicators allowed alongside). No data? Mark
> `proxy` with a validation note — a KR with no machine check (not even a
> deferred one) is rejected. A **mandatory quality/safety KR** on every
> objective.

## Cycle 2026-12 (first cycle — 2026-12-01 → 2026-12-31; first review: first
Friday of January 2027)

### Homelab

**O1 — Personal-interest content ships on a steady rhythm and is worth coming
back to.**

Pillars: arcade games, guitar, songs/clips, RPGs & war games, cars.

> Anchoring (2026-11-25): the personal-interest content is the main goal.
> "The virtual team ships real work" (harness/agents) is the **means**, not
> the goal — harness upkeep is **BAU** (tagged), not an objective. "Learning
> by building" lives inside the content (the content is the vehicle).
> **Early warning**: if the work-mix check shows `bau` eating the content
> ratio, promote the harness to a second objective at the first monthly review.

| # | KR | Definition | Source | Target | Cadence |
|---|----|------------|--------|--------|---------|
| 1 | Content output (leading) | Pieces published across the pillars (arcade game on /arcade, guitar tab, song clip, RPG content, car piece) | content inventory (`docs/roles/content-marketer/inventory.md` — created at first publish) + board done tasks | ≥ 4 pieces/mo (**proxy** — startup guess) | monthly |
| 2 | Pillar spread (leading) | Pillars with ≥ 1 piece published that month | content inventory | ≥ 2 of 5 pillars active/mo (**proxy**) | monthly |
| 3 | Revisit / traffic (outcome) | Return-visitor share / sessions on choukalos.com content | Plausible (not wired — G3) | +10% MoM sessions (**proxy** — validate when Plausible lands) | monthly |
| 4 | Quality (mandatory) | Published pieces that failed content QA (CM-1 `content-qa`) | QA records on board cards + inventory | 0 | per publish |

### Bluebovine

**O1 — The site compounds trust and traffic.**

| # | KR | Definition | Source | Target | Cadence |
|---|----|------------|--------|--------|---------|
| 1 | Content volume (leading) | Published posts on bluebovinegroup.com | board + site | ≥ 2 posts/mo (**proxy**) | monthly |
| 2 | Traffic growth (outcome) | Sessions MoM | Cloudflare analytics / Plausible (**proxy** — validate when wired) | +10% MoM (**proxy**) | monthly |
| 3 | Engagement (outcome) | Avg. time on site + scroll depth on posts | Cloudflare analytics (**proxy** — validate when wired) | ≥ 1 min avg. time on posts (**proxy**) | monthly |
| 4 | Quality (mandatory) | Published pieces that failed content QA | QA records on board cards + inventory | 0 | per publish |

**O2 — The product is defined and validated, ready to iterate.** *(phase:
define — the monthly org review is the shift point to iterate; rewrite at the
cycle boundary, don't append a third objective.)*

| # | KR | Definition | Source | Target | Cadence |
|---|----|------------|--------|--------|---------|
| 1 | Market analysis | Complete market analysis: competitive scan, market size & share, opportunity list with evidence | `docs/roles/pm/market-analysis-*.md` | 1, by 2026-12-15 | this cycle |
| 2 | Opportunity selected + pitched | Exec pitch delivered + chuck's decision recorded (option + recommendation + the ask) | `docs/roles/pm/pitches/*.md` + board | 1, by 2026-12-22 | this cycle |
| 3 | PRD/spec drafted | PRD groomed to a board spec with testable acceptance criteria | board (groomed idea) + durable copy `docs/roles/pm/prds/<feature>.md` | 1, by 2026-12-31 | this cycle |
| 4 | Quality (mandatory) | PRDs without acceptance criteria | board specs | 0 | per PRD |

## Coverage (who serves what)

| Org goal | Agents serving | Notes |
|---|---|---|
| Homelab O1 | marketing (producer), strategist (content strategy), product (pipeline specs), analyst (KPI digest) | main goal this cycle |
| Bluebovine O1 | strategist (brand + content strategy), marketing (producer), analyst (measurement) | |
| Bluebovine O2 | product (primary), analyst (validation data) | phase: define |

No org goal is chuck-only this cycle; no goal is uncovered.

---
updated 2026-11-26 — first pass (okr skill S13): formalizes the 2026-11-24/25
goal-model + anchoring decisions from `todo_agentic_framework.md` into
four-field KRs. Cycle 2026-12. All traffic/engagement KRs are `proxy` until
Plausible wiring (G3) lands.
