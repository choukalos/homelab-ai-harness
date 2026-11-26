# OKR alignment report — 2026-11-26 — first pass (cycle 2026-12)

## Framing

First org-goals pass, both in-scope domains (homelab, bluebovine). No prior
cycle — this pass formalizes the 2026-11-24/25 goal-model and anchoring
decisions (`todo_agentic_framework.md`) into four-field KRs per the okr skill
(S13). Board state at pass time: 14 done, 2 running (task 15 — PWV2 trilogy
review, homelab content; task 16 — SEC-12 P12-A file bridge, security/BAU),
0 backlog, 0 needs-attention. Plausible is not wired (G3; P1 first-user
bootstrap pending chuck) — all traffic/engagement KRs are `proxy` by design.

## Alignment table

| Org goal (domain) | Agents serving | KRs | Data-source status |
|---|---|---|---|
| Homelab O1 — personal-interest content ships on a steady rhythm and is worth coming back to | marketing, strategist, product, analyst | KR1 output (proxy), KR2 pillar spread (proxy), KR3 revisit/traffic (proxy), KR4 quality | inventory + board: live (machine-checkable); Plausible: not wired — proxy |
| Bluebovine O1 — the site compounds trust and traffic | strategist, marketing, analyst | KR1 volume (proxy), KR2 traffic (proxy), KR3 engagement (proxy), KR4 quality | board: live; CF analytics/Plausible: proxy until wired |
| Bluebovine O2 — the product is defined and validated, ready to iterate (phase: define) | product (primary), analyst | KR1 market analysis, KR2 pitch + decision, KR3 PRD/spec, KR4 quality | board + `docs/roles/pm/` artifacts: live (fully machine-checkable, no proxy) |

## Agent objectives (drafts — for chuck's review)

Full drafts in `docs/agents/<slug>/charter.md` (objectives/KRs sections only).

| Agent | Objectives | Laddered to |
|---|---|---|
| product | (1) Drive the bluebovine product from research to a decision-ready spec; (2) Keep the homelab content pipeline moving — ideas groomed to buildable specs | Bluebovine O2; Homelab O1 |
| analyst | (1) Make the org's progress visible — the weekly KPI digest | Homelab O1 + Bluebovine O1/O2 (measurement) |
| strategist | (1) Own the bluebovine brand position and content strategy; (2) Give the homelab content a strategy — pillars, calendar, repurpose-first | Bluebovine O1; Homelab O1 |
| marketing | (1) Ship personal-interest content on a steady rhythm; (2) Produce bluebovine content to the strategy | Homelab O1; Bluebovine O1 |

## Checks

- [x] every agent objective maps to a domain org goal (no orphans)
- [x] every KR has definition/source/target/cadence (or is explicit `proxy`)
- [x] no activity-metric KR dressed as an outcome — output KRs (pieces/mo,
      posts/mo) are labeled **leading** and each objective carries an outcome
      KR (revisit/traffic; traffic growth; O2's decision-ready spec)
- [x] coverage — every org goal served by ≥ 1 agent; none chuck-only
- [x] work-mix read — in-flight work tagged: task 15 =
      `org/homelab/O1-KR1` (content — the PWV2 trilogy is a personal-interest
      content piece); task 16 + the 12.4 interim fix = `exec` (chuck's
      directive this session). Mix: 1 OKR-serving, 2 exec, 0 bau in flight —
      no bau-eating-content signal yet; the early-warning check is armed.

## Flags

- **All traffic/engagement KRs are `proxy`** — Plausible P1 (first-user
  bootstrap) is the unblock; until then KR3/Homelab and KR2-3/Bluebovine-O1
  run on guess targets and get replaced with real measurements at the first
  monthly review (or earlier, the moment G3 wiring lands).
- **Sharpest starting KR (Q13 input)**: Bluebovine O2's KRs are fully
  machine-checkable right now (artifact files + board state, zero proxy) —
  the `product` agent has the sharpest starting charter. `marketing` is a
  close second (homelab content KRs are checkable via inventory + board), but
  its execution depends on the strategist's content strategy landing first
  (dependency chain: strategy → calendar → production).
- **Q13 decision (chuck, 2026-11-26)**: stand up **`strategist` first, then
  `marketing`** — "the main ones that can get started sooner rather than
  later." Rationale: the homelab content chain (strategist O2 → marketing O1)
  serves the cycle's main goal (Homelab O1) and both agents' skills are built;
  `product` (bluebovine O2) follows after.
- **Content inventory doesn't exist yet** — `docs/roles/content-marketer/
  inventory.md` is created at first publish; KR1/KR2 sources are live from
  day one via board done tasks until then.
- **No 3rd objectives** — scale rule respected (1 per homelab, 2 per
  bluebovine, both per the 2026-11-25 anchoring).
