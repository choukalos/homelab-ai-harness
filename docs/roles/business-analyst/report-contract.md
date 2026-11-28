# BA→Role Report Contract (G4)

> **Gap G4 from `todo_agent_skills.md`** — "No BA→role analytics handoff
> contract (report format + location)". Defined 2026-11-27 when the G3 wiring
> landed (Plausible → data-hub feed + Grafana Product KPIs, `docs/plausible_ops.md`
> P5). This is the contract the Business Analyst role follows when it measures
> what shipped and routes insights back to every role (BA workflow step 3).

## 1. The rule of thumb

**The board carries the work item; the repo carries the artifact.** A BA report
is a durable artifact — it lands in the repo (this contract's location), and a
board card (or card note) carries the *routing* — the one-line insight + the
link, so the owning role sees it in its normal board workflow.

## 2. Report location & naming (G12)

| Artifact | Home |
|---|---|
| BA analysis / KPI reports | `docs/roles/business-analyst/reports/<topic>-<YYYY-MM-DD>.md` |
| Weekly org KPI digest (the standing measurement record) | `docs/org/kpi/<YYYY>-W<WW>.md` (analyst O1 KR1; the W48 baseline issue fixed the format) |
| Dashboards (live, not markdown) | Grafana — `Product KPIs` (Plausible feed), `Security Monitoring`, `Homelab Overview` |

- `<YYYY-MM-DD>` = the date the report was produced (G12 naming rule).
- The weekly KPI digest is the *standing* report — one per ISO week, filed by
  the analyst. Ad-hoc analyses (spot-checks, deep-dives, "why did traffic
  dip?") are separate date-stamped files in `reports/`.
- Grafana carries the live trend; the markdown carries the *analysis* (what
  moved, what it means, what to do). Never duplicate a dashboard's raw series
  into markdown — link it and summarize the delta.

## 3. Report format

Every BA report (digest or ad-hoc) uses this skeleton:

```markdown
# <KPI Digest — YYYY-Www | <topic>> (filed YYYY-MM-DD)

> **serves:** <org/agent/KR tags> · **window:** <period> · **sources:** <named>

## 1. Executive read
3–5 bullets. What moved, vs goal, vs prior period. Lead with the thing the
exec needs to know. Status labels for KRs: `measured` / `proxy` / `missing`
(never estimate a missing value — report it missing).

## 2. KPI table
| KPI | Target | Current | Delta | Status | Source (resolvable ref) |
Every numeric claim carries a resolvable reference: file path, board card id,
commit sha, live URL, or Grafana dashboard + panel.

## 3. Insights by role
### Product Manager
### Marketing Strategist
### Content Marketer
### Coding Team
### Exec
One section per role — even if it says "no signal this period". Each insight:
the observation, the evidence ref, and the suggested action (board idea /
card note / no action).

## 4. Follow-ups
Board cards created this period (id + title + `serves:` tag) that route the
insights in §3. Empty list is a valid answer.

## 5. Source appendix
Every reference used, with how to re-resolve it (command / URL / query).
```

## 4. Insight routing (how a report reaches a role)

1. **Board card (primary).** An insight that needs action becomes a board idea
   or a note on the owning role's card — `serves:` tagged, with the report path
   in the body. The role sees it in `board_status` / its own workflow. This is
   the only routing that *creates work*.
2. **Role review (secondary).** The weekly agent reviews (Part 1:
   accomplishments) and the monthly org review consume the KPI digest
   automatically — the analyst's digest is the evidence source for KR
   scoring. No extra routing needed.
3. **Exec (on demand).** Weekly: the KPI digest + `./homelab.sh security
   status` + board state. Monthly: the monthly org review doc. Deep-dive:
   `presentation-build` / S9 `exec-problem-brief`.
4. **Never:** chat-only insights (lost), or a report with no follow-ups section
   (the exec can't tell what the BA wants done).

## 5. Cadence

| Report | Cadence | Owner |
|---|---|---|
| Weekly KPI digest | Every ISO week, with the weekly reviews (Friday) | analyst agent (O1 KR1) |
| Monthly org review (consumes the digest + board `byModel` usage) | First Friday of the month (reviews the just-ended month) | monthly-org-review skill |
| Ad-hoc analysis | When a signal needs it (spend spike, traffic anomaly, exec question) | analyst agent / any role requesting |
| Plausible KPI report (BA-1 `plausible-kpi` skill) | On demand + when the weekly digest needs fresh traffic numbers | analyst agent |

## 6. KPI registry

KPI definitions (definition, source, target, cadence) live in
`docs/org/goals.md` (the org KRs) + the agent charters (`docs/agents/<slug>/charter.md`).
When a new KPI is proposed, it is added to the goals doc at the cycle boundary
(the monthly review's proposed rewrite) — not ad-hoc into a report. A report
may *flag* a candidate KPI in §3/§4; it does not create one.

## 7. Grounding rules (non-negotiable)

- **One source, no duplicate reporting** — a report consumes existing data
  sources (board, Plausible/ClickHouse, `usage` table, live sites, role
  artifacts). It creates no new data source.
- **Every numeric claim carries a resolvable reference** (§3, §5).
- **Missing data is reported as `missing`, never estimated** (the W48
  baseline set this rule — it caught the G3 gap instead of papering over it).
- **Small windows say so.** The Plausible sites are new (wired 2026-11-27);
  low-traffic windows are a fact to state, not a trend to interpret.
