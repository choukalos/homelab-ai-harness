---
name: monthly-org-review
description: "Monthly org review, run only on the FIRST Friday of the month (the cron fires every Friday — the skill owns the gate and skips otherwise with {\"status\": \"skipped\", \"reason\": \"not the first Friday of <month>\"}). One LLM synthesis call (matrix-coder) produces: (1) KR scoring 0-1 per org KR with real evidence refs, (2) retro (worked / didn't / friction), (3) goal adaptation — a full PROPOSED rewrite of docs/org/goals.md for the next cycle (rewrite at the cycle boundary, don't append), (4) domain-KB staleness pass — superseded/stale KB facts as kb_forget CANDIDATES with evidence. Conservative application (safety): writes docs/org/reviews/YYYY-MM.md + the sidecar docs/org/goals.proposed-YYYY-MM.md; does NOT overwrite docs/org/goals.md and does NOT call kb_forget UNLESS params.apply_goals=true / params.apply_kb_forget=true (both default false — chuck applies after reading the review; org-doc edits are single-approval per the Q7 autonomy table). Deterministic guardrails: KRs restricted to goals.md, scores clamped to [0,1], evidence refs must match real board card ids / commit shas / file paths / weekly-review paths, the proposed rewrite must cover every domain, kb_forget is two-step (confirm + ids) with at most one point per candidate."
---

# Monthly Org Review — KR scoring + retro + goal adaptation + KB staleness

Scheduled skill (`monthly-org-review` in `scheduler/schedules.json`,
`0 15 1-7 * 5` America/Chicago).

**First-Friday gate (the skill's responsibility):** the skill-runner
scheduler uses standard-cron OR semantics for day/day-of-week, so the job
fires EVERY Friday. The skill runs only on the FIRST Friday of the month;
on any other Friday it returns
`{"status": "skipped", "reason": "not the first Friday of <Month YYYY> ..."}`
and writes nothing. It runs after that week's agent reviews land so it can
consume them.

## The 4-part review (docs/org/reviews/YYYY-MM.md)

1. **KR scoring (0-1)** — every org KR in `docs/org/goals.md` scored with
   evidence refs (real board card ids / commit shas / file paths / weekly
   review paths only; invalid refs dropped deterministically)
2. **Retro** — what worked / what didn't / process friction
3. **Goal adaptation** — the ONLY place org goals may change: a full
   PROPOSED rewrite of `docs/org/goals.md` for the next cycle (rewrite at
   the cycle boundary, don't append), written to the sidecar
   `docs/org/goals.proposed-YYYY-MM.md`
4. **Domain-KB staleness pass** — superseded/stale KB facts listed as
   `kb_forget` CANDIDATES with evidence (via the injected `mcp_knowledge`
   client)

## Conservative application (safety)

- The review doc + the goals sidecar are ALWAYS written.
- `docs/org/goals.md` is overwritten ONLY with `apply_goals=true` AND a
  guardrail-valid proposed rewrite (the rewrite must cover every current
  domain; otherwise it is rejected and goals.md is untouched).
- `kb_forget` is called ONLY with `apply_kb_forget=true` (two-step: match,
  then confirm with ids — at most one point per candidate; permanent).
- Both params default to **false** — chuck applies them after reading the
  review (org-doc edits are single-approval per the Q7 autonomy table).

## Data sources (deterministic collection, best-effort)

- `docs/org/goals.md` (all domains / objectives / KRs), the month's agent
  weekly reviews (`docs/agents/*/reviews/*.md`), board state per project
  (done cards in the month + agent-owned cards, MySQL `ai_kanban`), the
  latest alignment report (`docs/org/alignment/`), domain KB via the
  injected MCP client.
- ONE LLM synthesis call (matrix-coder) with deterministic guardrails:
  KRs restricted to the goals.md list, scores clamped to [0,1], evidence
  refs must match real ids/paths, the proposed rewrite must cover every
  domain, kb candidates need a known collection + valid evidence.

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `monthly_org_review`
- `params`: (optional) the input values below

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| output | string | no | `docs/org/reviews/YYYY-MM.md` | Review doc path template (`YYYY-MM` = calendar month of the run date). |
| goals_sidecar | string | no | `docs/org/goals.proposed-YYYY-MM.md` | Sidecar for the PROPOSED goals rewrite. |
| apply_goals | boolean | no | false | Overwrite `docs/org/goals.md` with the guardrail-valid proposed rewrite. |
| apply_kb_forget | boolean | no | false | Call the two-step `kb_forget` for the stale-fact candidates. |
| force_date | string | no | — | Ops/test override `YYYY-MM-DD` — run for that date instead of today (the first-Friday gate still applies to it). |
| includes | list | no | — | Informational — the 4-part list from the schedule. |

## Output

Result keys: `status` (`generated` / `skipped`), `summary`, `month`,
`gate`, `artifact_path`, `goals_sidecar`, `goals_applied`,
`kb_forget_results`, `guardrail_notes`, `inputs`. Max runtime 300s.
