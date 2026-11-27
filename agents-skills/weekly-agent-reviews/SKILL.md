---
name: weekly-agent-reviews
description: "Weekly 7-part review for each ACTIVE agent (product only — Q13; strategist/marketing/analyst are OFF and never targeted): prior-week accomplishments with real evidence refs, KR progress vs trajectory, work-mix check (bau vs OKR vs exec + agent-key spend line), machine-checked quality KR status, upcoming plan (suggestions only), learnings + domain-KB line, and a placeholder part 7 for chuck's feedback. Non-stacking gate: skips an agent when the most recent prior review's part 7 has no feedback/ack; bootstrap (no prior doc) runs unconditionally. One LLM synthesis call (matrix-coder) with deterministic guardrails (evidence refs must match real board card ids / commit shas / file paths; KRs restricted to the charter; window dates enforced; deterministic skeleton on LLM failure). Writes docs/agents/<slug>/reviews/YYYY-WW.md."
---

# Weekly Agent Reviews — 7-part weekly review for active agents

Scheduled skill (`weekly-agent-reviews` in `scheduler/schedules.json`,
Friday 15:00 America/Chicago). Produces the 7-part weekly review for each
ACTIVE agent (Q13: `product` is the only active agent;
`strategist`/`marketing`/`analyst` are OFF and never targeted).

The doc (one per agent per ISO week) has exactly these parts:

1. **Prior-week accomplishments** — with evidence/links (board card ids +
   states, commit shas, artifact file paths — only real refs; a
   zero-activity agent gets the honest "no board cards assigned yet" line)
2. **KR progress vs trajectory** — per charter KR: evidence vs target vs
   cadence (honest "no movement" is valid)
3. **Work-mix check** — bau vs OKR vs exec work + the spend line
   (agent-key total via LiteLLM `/spend/keys`)
4. **Quality KR status** — the mandatory quality KRs, machine-checked from
   board spec state
5. **Upcoming plan** — proposed cards (suggestions only; the agent does not
   create cards here)
6. **Learnings + domain-KB line** — facts added/corrected/forgotten +
   collision log (from the KB window query; degrades honestly when the KB
   is unavailable)
7. **chuck's feedback** — always the empty placeholder
   "(pending — appended after chuck responds)"

## Non-stacking gate

If the previous week's review doc exists AND its part 7 has no substantive
feedback (or explicit ack) appended, this agent is skipped for the cycle
(write nothing, log the reason). First cycle (no prior doc) runs
unconditionally — bootstrap.

## Data sources (deterministic collection, best-effort)

- Board: MySQL `ai_kanban` (`KANBAN_DB_*` env) — the agent's tasks (all
  states), task events in the window, per-project done counts
- Charter: `docs/agents/<slug>/charter.md` (objectives + KR table)
- Org goals: `docs/org/goals.md` (ladder targets)
- Prior review doc (delta input); domain KB via the injected MCP client
  (`mcp_knowledge`; product owns `kb_bluebovine`)
- ONE LLM synthesis call (matrix-coder) with deterministic guardrails on
  the output (evidence refs must match real board ids / commits / file
  paths; KRs restricted to the charter's list; dates must fall in the
  window)

## How to run

Call the `mcp_skills` MCP tool **`run_skill`** with:

- `name`: `weekly_agent_reviews`
- `params`: (optional) the input values below

## Inputs

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| agents | list | no | `["product"]` | Agent slugs to review (inactive agents are skipped with a note). |
| output | string | no | `docs/agents/<slug>/reviews/YYYY-WW.md` | Output path template (`<slug>`, `YYYY-WW` substituted). |
| parts | list | no | — | Informational — the 7-part list from the schedule; the doc format is canonical. |
| non_stacking | boolean | no | true | Skip an agent when the prior week's part 7 has no feedback/ack. |
| note | string | no | — | Informational schedule note. |

## Output

Result keys: `summary`, `week`, `agents` (per-agent `status` /
`skip_reason` / `path` / `guardrail_notes` / `inputs`), `artifact_path`.
Writes ONLY to `docs/agents/<slug>/reviews/` in the repo. Max runtime
300s.
