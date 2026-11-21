# Proposal — mcp_kanban Phase 2: per-user LLM spend attribution + per-user spend trend

Status: **implemented** (2026-11-21) — see Rollout/Status
Supersedes: the "Phase 2 (follow-up)" section of `todo_mcp_kanban.md` (Q2 design)
Follows: `proposals/2026-11-21-tier2-mcp-kanban-mcp-first.md` (owner columns)

## Problem

The kanban container makes **all** LLM calls (grooming / task / QA / summary)
with one service key (`LITELLM_API_KEY` in the container). The MCP-first
change (2026-11-21) stamped `owner` on projects/ideas/tasks (the caller's
LiteLLM key → user name), but the *spend* still bills to the service key, and
the reports page only shows total + per-project spend.

## Goal

1. **Per-user spend attribution**: sessions for work owned by user X run
   against the proxy with **X's key**, so LiteLLM bills spend to X's key
   (and X's budget). Fallback: no owner / owner without a key entry →
   service key (as today).
2. **Per-user spend trend on the web UI**: a section on the reports page
   showing $ spend per user over a rolling 12 months. The existing
   **per-project** and **total** aggregates keep spanning **all keys**
   (chuck's call: they must include every key, incl. unattributed/legacy —
   i.e. they are not filtered to known users).

## Design (per the Q2 design in `todo_mcp_kanban.md`)

### 1. User→key map: `USER_KEYS` (container env)

`USER_KEYS=chuck=<full-key>,dylan=<full-key>` — comma-separated
`name=full-LiteLLM-key` pairs. Compose interpolates from the repo `.env`
(`USER_KEYS=chuck=${LITELLM_KEY_CHUCK},dylan=${LITELLM_KEY_DYLAN}`) so the
keys are not duplicated. The names match the `MCP_KEY_OWNERS` names
(`chuck` / `dylan`).

- `KanbanConfig.userKeys: Record<string, string>` (empty when unset).
- **Fail-fast validation at boot** (like the model check): each user key is
  checked against the proxy (`GET /v1/models` with that key); a rejected key
  aborts startup with a clear error (catches rotated/expired keys early).

### 2. Per-user agent key profiles (`AgentRuntime`)

Today `AgentRuntime.create` materializes one app-owned agent dir
(`<data>/pi-agent`) with `models.json` + `auth.json` (service key) and one
`ModelRuntime`. Change:

- A **key profile** = agent dir + `auth.json` + `ModelRuntime` + `Model`.
  - `service` (default): existing `<data>/pi-agent` (unchanged path).
  - Per user: `<data>/pi-agent-<name>` with that user's key.
- `createSession({ ..., owner? })` picks the profile: `owner` present and
  mapped → user profile; else (no owner, or owner without a key entry) →
  service profile (with a one-line log note for the unknown-owner case).
- Session files stay shared under `<data>/sessions` (transcripts carry no
  auth state); resume picks the profile by the same owner (stable).

Owner threading (owner is known at every session-creation site):

| Session | Owner source |
|---|---|
| grooming (seed / message / accept / re-groom) | the idea's `owner` |
| task run (incl. resume) | the task's `owner` (inherited from the idea) |
| QA round | the task's `owner` |
| project summary (post-deploy) | the task's `owner` |

### 3. Usage rows carry the owner

Migration `0003_usage_owner`: `owner VARCHAR(64) NOT NULL DEFAULT ''` on
`usage` (both drivers). `recordUsage` writes the owner at capture time
(denormalized — grooming/summary rows have no task to join through; legacy
rows stay `''`).

### 4. Reports: per-user spend trend (rolling 12 months)

New section on **GET /reports** (between the total-spend and per-project
sections):

- Table: one row per user (owner names present in the window; `''` shown as
  *unattributed*), one column per month (12, matching the existing
  `monthWindow`), plus a 12-month total.
- Horizontal bar chart of per-user 12-month totals.
- **Per-project and total sections unchanged** — they aggregate all usage
  rows (all keys), which is the required behavior.

No MCP surface for this (read-mostly web status view; the existing MCP
status tools are unchanged).

## Files

| File | Change |
|---|---|
| `src/db/migrations.ts` | `0003_usage_owner` (both drivers) |
| `src/db/schema.ts` | `owner` on `usage` (both drivers) |
| `src/config.ts` | `USER_KEYS` parse (`userKeys`), boot validation of user keys |
| `src/agent/sessions.ts` | key profiles (per-user agent dir + auth.json + ModelRuntime); `createSession({ owner })` |
| `src/agent/grooming.ts` | owner into the groom session + usage rows |
| `src/agent/qa.ts`, `src/agent/summary.ts` | owner into the sessions |
| `src/orchestrator.ts` | owner into task/QA/summary sessions + usage rows |
| `src/services/usage.ts` | `UsageRecord.owner` |
| `src/services/reports.ts` | `spendByOwner` (per-user × per-month, rolling 12 mo) |
| `src/services/index.ts` | `ReportsData.owners` |
| `src/http/templates.ts`, `src/http/app.ts` | per-user section (table + hbar chart) |
| tests | config / sessions / db / reports / grooming / orchestrator / http |
| `compose/compose.mcp.yml` | `USER_KEYS=chuck=${LITELLM_KEY_CHUCK},dylan=${LITELLM_KEY_DYLAN}` |
| `.env.example`, `README.md` | `USER_KEYS` + per-user spend docs |
| `src/db/tables.ts` (+ tests) | **Bug fix found in E2E**: driver-conditional table objects (MySQL JSON double-parse) |

## Rollout

- [x] Implement + `npm test` green
- [x] Commit + push
- [x] Deploy on thor (`docker compose -f compose/compose.mcp.yml up -d --build mcp_kanban`)
- [x] Verify: migration `0003_usage_owner` applied; boot validates both user
      keys; a real grooming turn runs on the owner's key (usage row stamped;
      proxy spend lands on the user's key, not the service key); /reports
      renders the per-user section (per-project/total still all-keys)

## Bug found in E2E: MySQL JSON double-parse (fixed, commit 699afbc)

The first live `add_idea` / `list_ideas` calls failed with
"Unexpected end of JSON input" even though the inserts persisted. Root cause:
the service layer queries through the **SQLite** table objects on every
driver (the MySQL drizzle instance is cast at the service boundary). The
SQL is compatible (identical column names), but drizzle maps result rows
through the table's column mappers — and SQLite `text({mode:"json"})`
`JSON.parse()`s driver values, while **mysql2 returns native JSON columns
already parsed (objects)**. Double-parse: `JSON.parse(String([])) ===
JSON.parse("")` → crash. Latent before Phase 2: any full-row read of
`ideas` / `tasks` (or `projects.media_paths` / `task_events.payload`) on
MySQL would have failed — the earlier E2E only exercised the JSON-free
`projects` table.

Fix: `src/db/tables.ts` exports driver-conditional table objects (DB_DRIVER
switch at module load — the driver is fixed for the process lifetime); the
9 service/agent/orchestrator modules import table objects from there (types
+ constants still from `schema.ts`). Regression tests pin the mapper
behavior on both dialects + the env switch.

## Verification record (live, 2026-11-21)

- `list_ideas` / `add_idea` OK on the live MySQL (post-fix; pre-fix both
  crashed with the double-parse despite successful inserts).
- Grooming turn as chuck (idea 10, project 3): usage row
  `role=groom, model=matrix-coder, tokens 4275/1857, cost 0.01156275,
  owner=chuck`. LiteLLM spend log for the same session: exactly 1
  completion, $0.01156275, 6132 tokens — the usage row matches the proxy
  billing exactly, and the spend landed on chuck's key (not the service
  key).
- `/reports`: "Per user — rolling 12 months" shows chuck $0.01 (Nov);
  per-project + total sections show the same $0.01 (all-keys, unchanged).
- Throwaway project 3 (10 test ideas + 1 usage row) cascade-deleted after
  verification.

## Status

Implemented + deployed + verified 2026-11-21.
