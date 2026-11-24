# mcp_kanban: start_task (and every task state transition) crashes in MySQL mode — `.returning()` is not a function

- slug: kanban-start-task-mysql-returning
- date: 2026-11-22
- status: applied
- applied: 2026-11-23 (pi, thor) — fix commit `58ba806` (2026-11-23): `transition()`
  is driver-conditional — MySQL awaits the plain UPDATE and uses the mysql2
  OkPacket's `affectedRows` as the atomic conditional-WHERE check (Option A);
  SQLite/PG keep `.returning()`; driver-realism test added (Option C). Deployed
  with the mcp_kanban rebuild 2026-11-23 21:43 UTC (container started after the
  fix commit); live task transitions verified during the PWV2 production
  session (the kanban-remote-client-file-intake E2E, 2026-11-23 — see
  `proposals/archive/2026-11-23-tier2-kanban-remote-client-file-intake.md`).
  Housekeeping 2026-11-24: file moved from repo root to `proposals/archive/`
  and the DB row added (both were missing — two-place drift).
- target user: chuck
- target repo: `homelab-ai-harness` → `mcp/servers/kanban/` (fix) + `compose/compose.mcp.yml` (redeploy)
- scope: `Orchestrator.transition()` in `mcp/servers/kanban/src/orchestrator.ts` (~line 986).
  One-line-class bug, but it breaks the ENTIRE task lifecycle in the deployed
  (MySQL) driver. Explicit non-goal: changing the production driver (MySQL is
  the right persistence choice — shared + backed up; fix the code, not the driver).

## Symptom (collected live 2026-11-22, from chuck's Mac via the LiteLLM proxy)

`mcp_kanban_start_task` on every one of 4 backlog tasks (Media project id 7,
tasks 1–4, PWV2 draft cards) returns the response text:

```
this.db.update(...).set(...).where(...).returning is not a function
```

Not an exception — the error string is returned as the tool's text response.
Reproduced 5× (4 tasks + 1 retry). Read paths work fine in the same session:
`task_status`, `board_status`, `project_status`, `list_ideas`, `groom_status`,
`move_to_backlog` (task creation), the full grooming flow (add_idea →
start_grooming → groom_accept → icebox). Only the task **state-transition
write path** fails.

## Root cause (verified against the repo, 2026-11-22)

1. **Driver selection** — `src/db/client.ts`: the container runs with
   `DB_DRIVER` = `sqlite` (better-sqlite3) or `mysql` (mysql2 pool,
   `drizzle-orm/mysql2`, `mysqlSchema`).
2. **Deployed driver is MySQL** — `compose/compose.mcp.yml:311` sets
   `DB_DRIVER=mysql` (the repo's `.env.example` defaults to sqlite, which is
   why local dev/tests never hit this).
3. **The bug** — `src/orchestrator.ts` `transition()` (~line 986):

   ```ts
   const updated = await this.db
     .update(tasks)
     .set({ state: to, stateChangedAt: Date.now(), ...(extra ?? {}) })
     .where(and(eq(tasks.id, taskId), eq(tasks.state, from)))
     .returning({ id: tasks.id });        // ← does not exist on the MySQL builder
   if (updated.length === 0) { …throw 409… }
   ```

   Drizzle implements `.returning()` for **Postgres and SQLite only**.
   MySQL has no `RETURNING` clause, so `MySqlUpdateSet` has no `.returning`
   method → `TypeError: …returning is not a function` at runtime.
4. **Why tests pass** — the unit tests mock the query builder and stub
   `.returning()` (`orchestrator.test.ts:176`, `http.test.ts:236/457/…`,
   `orchestrator-resilience.test.ts:169`, `orchestrator-deploy.test.ts:208`).
   No test exercises `transition()` against a real `drizzle-orm/mysql2`
   instance, so the driver asymmetry is invisible to CI.

## Blast radius (bigger than start_task)

`transition()` is the single state-machine path for **all** task state
changes. In MySQL mode, every one of these crashes:

| Caller | Transition | Effect |
|---|---|---|
| `startTask` (MCP `start_task`) | backlog → running | manual start broken (observed) |
| `tick()` → `startTask` (orchestrator.ts:247) | backlog → running | **auto-pickup broken — backlog tasks NEVER start** |
| `completeTask` | running → deploy | task completion broken |
| `failTask` | * → needs_attention | failure routing broken (a crashing task can't even be recorded as failed) |
| `restartTask` | needs_attention → backlog | resolution re-entry broken |
| `retry_deploy` / pause / resume paths that use `transition()` | various | check each — same call |

NOT affected (verified working live): read paths, idea/grooming state
changes (separate update path, no `.returning`), `move_to_backlog` (INSERT),
`stopTask` (plain conditional UPDATE, no `.returning` — orchestrator.ts
~line 340).

**Operational consequence right now:** the 4 PWV2 draft cards (tasks 1–4)
are stuck in the backlog with no path to start — neither manual
(`start_task`) nor automatic (`tick()`). Until this is fixed, **no kanban
task on this deployment can ever run**.

## Fix

### Option A (recommended) — driver-conditional affected-row check

Follows the codebase's existing "driver-conditional" pattern (commit
699afbc, driver-conditional table objects). In `transition()`:

```ts
const isMysql = this.dbDriver === "mysql"; // plumb from openDb() handle
let affected: number;
if (isMysql) {
  // drizzle mysql2: await update() resolves to the mysql2 OkPacket result
  const [res] = await this.db
    .update(tasks)
    .set({ state: to, stateChangedAt: Date.now(), ...(extra ?? {}) })
    .where(and(eq(tasks.id, taskId), eq(tasks.state, from)));
  affected = (res as { affectedRows?: number }).affectedRows ?? 0;
} else {
  const updated = await this.db
    .update(tasks)
    .set({ state: to, stateChangedAt: Date.now(), ...(extra ?? {}) })
    .where(and(eq(tasks.id, taskId), eq(tasks.state, from)))
    .returning({ id: tasks.id });
  affected = updated.length;
}
if (affected === 0) {
  const current = await this.getTask(taskId);
  throw new ServiceError(409, `task ${taskId} is not ${from} (state: ${current.state})`);
}
```

Keep the conditional `WHERE state = from` (the concurrency guard) — do NOT
replace it with select-then-update.

### Option B (alternative) — drop `.returning()` entirely, verify by re-read

`await` the plain UPDATE on both drivers, then `getTask(taskId)` and check
`state === to` (throw 409 on mismatch). Slightly racy under concurrent
transitions (two transitions could interleave the update+read) — Option A's
`affectedRows` is the atomic check; prefer A.

### Audit sweep (same class, same PR)

- `grep -rn "\.returning(" mcp/servers/kanban/src --include="*.ts" | grep -v test`
  → every hit is a latent MySQL crash. `orchestrator.ts:986` is the only
  non-test hit today, but the sweep should be part of the PR (and a lint
  rule / test per Option C below).
- Check `pauseTask`/`resumeTask`/`retryDeploy` for the same pattern (they
  may call `transition()` — if so they're already covered; if they have
  their own updates, audit those too).

### Option C (regression guard) — driver-realism test

Add ONE integration-style test that builds a real `drizzle-orm/mysql2`
instance over a mocked mysql2 pool (pool.query resolves an OkPacket with
`affectedRows`) and runs `transition()` end-to-end for both the success and
the 409 (affectedRows=0) paths. Mocking the *builder* (what the existing
tests do) is exactly what hid this bug — the new test must not mock the
builder. Cheaper variant: a static assertion test that imports the real
`MySqlUpdateSet` type and fails CI if `transition()`'s chain references a
method absent from it.

## Verification (on thor, after rebuild + restart of the kanban container)

1. `docker logs <kanban container>` — confirm no more
   `returning is not a function`; also scroll back to see how long the
   orchestrator `tick()` has been crash-looping (evidence for the blast
   radius + why nothing auto-started).
2. Scratch project: create project → add idea → groom → icebox →
   `move_to_backlog` → **`start_task`** → `task_status` = `running` with a
   session launched.
3. Exercise the full lifecycle on the scratch task: `pause_task` →
   `resume_task` → `stop_task` → `restart_task` → `retry_deploy` — all
   return clean state changes (no error-string responses).
4. Auto-pickup: leave a dep-free backlog task, wait one tick interval →
   it starts on its own.
5. Existing suite: `npm test` with `DB_DRIVER=sqlite` (default) still green
   (the SQLite path must not regress).
6. Production unblock: re-run `start_task` on PWV2 tasks 1–4 (Media
   project) — they should launch; the drafts then proceed per
   `~/Code/media-film/potato-wars-v2/PLAN.md`.

## Workaround (until the fix ships)

None clean. The task session launch happens in-process
(`launchPipeline`), so hand-flipping the DB row to `running` does NOT start
a session. Running the container on `DB_DRIVER=sqlite` would "work" but
orphan the live MySQL data (projects/ideas/tasks/grooming history) — do not.
The fix + redeploy IS the unblock; it is small (one function + test).

## Notes

- Discovered during the PWV2 (Potato Wars v2) production kickoff: 5 draft
  cards were moved to the Media board's backlog and `start_task` was used to
  bypass the pickup timer — the error string was the first signal.
- The MCP tool layer surfaces this as a *successful response containing the
  error text* (not an MCP error) — consumers must treat a response body
  starting with `this.db.` / `is not a function` as a failure. Consider a
  follow-up: MCP handlers should catch ServiceError/TypeError and return a
  structured `{status:"error"}` body (separate idea, low priority).
