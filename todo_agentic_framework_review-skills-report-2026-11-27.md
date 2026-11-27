# Build report — review skill modules (WS3 step-6 GAP closeout), product-first

- date: 2026-11-27
- run: pi long task `2026-11-27T03-56-42-315Z-ded2e76d` (worker sessions
  TODO 1–3; TODO 4 = plan doc + this report)
- constraint honored: **no git commits in the homelab repo** — everything
  below is uncommitted in the working tree; the main session commits +
  pushes after the run. No live container touched or restarted — the real
  runs execute in a throwaway `python:3.14-slim` container on `ai-net` with
  `/home/chuck/homelab` bind-mounted (the same environment the skill-runner
  scheduler has: thor.local + litellm-proxy DNS names, real env).
- closes: **Gap #1** of `todo_agentic_framework_build-report-2026-11-27.md`
  (the two cron jobs referenced skill modules that did not exist — "the jobs
  fail at first fire (2026-11-27 15:00 CT) until the modules land"). The
  first fire has NOT happened yet (this run finished ~05:00 UTC Friday
  2026-11-27 / ~23:00 CT Thursday 2026-11-26) — the fire at **2026-11-27
  15:00 CT** will now run the real skills.

## What was built

1. **`skills/weekly_agent_reviews/`** (skill.py + skill.yml + test_skill.py)
   — the 7-part weekly review for each ACTIVE agent (product only;
   strategist/marketing/analyst are OFF and never targeted, even if listed):
   non-stacking gate, deterministic collection (board / charter / org goals /
   prior review / domain KB / agent-key spend), ONE matrix-coder synthesis
   call, deterministic guardrails, output
   `docs/agents/<slug>/reviews/YYYY-WW.md`.
2. **`skills/monthly_org_review/`** (same layout) — the monthly org review,
   first-Friday gate only: KR scoring 0-1 with real evidence refs, retro,
   goal adaptation (a PROPOSED rewrite of `docs/org/goals.md`), domain-KB
   staleness pass (kb_forget candidates). **Conservative-apply design**:
   proposals by default (see the dedicated section below).
3. **Skill Hub wrappers** — `agents-skills/weekly-agent-reviews/SKILL.md` +
   `agents-skills/monthly-org-review/SKILL.md` (hyphenated per the hub API
   name rule `^[a-z0-9-]+$`; descriptions copied verbatim from the
   skill.yml manifests so the `tests/test_skills_yaml.py` drift check
   passes).
4. **Real bootstrap weekly review artifact** —
   `docs/agents/product/reviews/2026-W48.md` (real LLM synthesis; kept for
   commit).

## Per-item evidence (command → result)

### TODO 1 — weekly_agent_reviews skill

- Files: `skills/weekly_agent_reviews/{skill.py, skill.yml, test_skill.py}`
  (new, untracked). `skill.yml`: `max_runtime: 300`, `channels: [cli, pi,
  n8n]`, `tools: [mcp_knowledge]`, `model_alias: matrix-coder`.
- Conformance to the `weekly-agent-reviews` params in
  `scheduler/schedules.json`: `agents: ["product"]` (default + OFF-agents
  never targeted), `output: docs/agents/<slug>/reviews/YYYY-WW.md`, the
  7-part `parts` list (the doc format is canonical so the non-stacking gate
  can read part 7), `non_stacking: true`.
- `python3 skills/weekly_agent_reviews/test_skill.py` → **PASS: 75  FAIL: 0**
  (15 test functions — gate: feedback→run / no-feedback→skip /
  no-prior→bootstrap / ack→run / disabled→run; guardrails: fake evidence
  refs / non-charter KRs / out-of-window dates dropped; output path +
  7-part order + part-7 placeholder; LLM-failure → deterministic skeleton,
  no crash; one LLM call; inactive agents never targeted; KB window facts +
  missing collection; bad params). **Re-verified 2026-11-27 04:5x UTC by
  TODO 4** (same command, same result).
- AST import scan: stdlib only + lazy `import pymysql`; `py_compile` OK.
- Live schema check (throwaway read-only mysql client on ai-net):
  `tasks` (id, owner, state, state_changed_at bigint **ms**, last_commit,
  project_id, spec, created_at) + `task_events` + `projects` (id, name)
  match the skill's queries; `SELECT COUNT(*) FROM tasks WHERE
  owner='product'` → 0.
- Live spend check: `/spend/keys` with `LITELLM_MASTER_KEY` → product key
  found (spend 0.0, created 2026-11-27); `/key/info` → 404 (the docstring's
  n/a-fallback claim is accurate).

### TODO 2 — monthly_org_review skill

- Files: `skills/monthly_org_review/{skill.py, skill.yml, test_skill.py}`
  (new, untracked). `skill.yml`: `max_runtime: 300`, `channels: [cli, pi,
  n8n]`; inputs include `apply_goals` (default false), `apply_kb_forget`
  (default false), `force_date` (ops/test override — the cron never sets
  it).
- Conformance to the `monthly-org-review` params in
  `scheduler/schedules.json`: `output: docs/org/reviews/YYYY-MM.md`, the
  4-part `includes` list, the first-Friday caveat (the cron `0 15 1-7 * 5`
  fires every Friday under standard-cron OR semantics — the skill owns the
  gate and skips otherwise).
- `python3 skills/monthly_org_review/test_skill.py` → **PASS: 108  FAIL: 0**
  (first-Friday gate: 2026-11-27 → skip; 2026-12-04 first Friday → run;
  boundary cases; conservative-apply defaults: no goals overwrite / no
  kb_forget without the params; output path/format; LLM-failure fallback).
  **Re-verified 2026-11-27 04:5x UTC by TODO 4** (same command, same
  result).
- `_parse_org_goals()` on the real `docs/org/goals.md` → 2 domains / 12 KRs;
  alignment-report + weekly-review collectors verified against the real
  repo.
- Runner contract: `skills/runner/main.py` `_execute_skill` injects the MCP
  client when `run()` declares it (signature confirmed).

### TODO 3 — end-to-end verification + Skill Hub registration

Full capture: `tmp/e2e_review_skills/EVIDENCE.md` (gitignored; runner
scripts `bootstrap_weekly.py` / `forced_monthly.py` kept there).

**Unit tests** (plain python3, same pattern as
`skills/harness_reflection/test_skill.py`):

```
$ python3 skills/weekly_agent_reviews/test_skill.py
PASS: 75  FAIL: 0

$ python3 skills/monthly_org_review/test_skill.py
PASS: 108  FAIL: 0
```

**Real bootstrap weekly run (product, 2026-W48)** — throwaway
`python:3.14-slim` on ai-net, the EXACT `weekly-agent-reviews` params from
`schedules.json`, `client=None` (the MCP client is only injected by the
runner — the skill degrades gracefully and the doc's KB line says so):

- Result: `1 generated, 0 skipped, 0 error(s) — product=generated`, mode
  `bootstrap + llm` (REAL LLM synthesis), gate_reason `bootstrap: no prior
  review doc`, inputs `{board_tasks: 0, board_events: 0, charter_krs: 6,
  kb_docs_in_window: 0, spend: 0.0}`.
- Artifact (KEPT — main session commits it):
  `docs/agents/product/reviews/2026-W48.md` — all 7 parts; honest bootstrap
  content: part 1 "Agent stood up 2026-11-27; no board cards assigned yet
  (honest bootstrap state — nothing was done this window)"; part 2 — 6
  charter KRs (5 "no movement", 1 "on track"); part 3 spend "$0.00
  (agent-key total — LiteLLM /spend/keys; key created 2026-11-27 ...)";
  part 4 both quality KRs machine-checked "pass" (0/0); part 6 KB line
  "n/a (no MCP client injected — KB unavailable)"; part 7 = the empty
  placeholder. Guardrail notes: zero-activity line applied, duplicate KR
  progress dropped. Chowned to chuck (1000:1000) after the container run so
  part-7 feedback can be appended.

**Monthly gate proof** (host, no I/O — the gate returns before any
collection):

```
$ python3 -c "... monthly_org_review.skill.run({}, None, None) ..."
{"status": "skipped",
 "reason": "not the first Friday of November 2026 (today 2026-11-27 is the
            4th Friday; first Friday was 2026-11-06)", ...}
```

Nothing written: `docs/org/reviews/` does not exist; no
`docs/org/goals.proposed-*` sidecar; `git diff` empty. **Re-verified
2026-11-27 04:5x UTC by TODO 4** (same result; `docs/org/reviews/` still
absent, no sidecar).

**Forced temp run** (proving the synthesis path — TEMP location, NOT
`docs/org/reviews/`, NOT a repo sidecar):

- params: `force_date=2026-11-06` (first Friday of the current month — real
  November data), `output=/repo/tmp/e2e_review_skills/mor_forced/2026-11.md`,
  `goals_sidecar=.../goals.proposed-2026-11.md`;
  `MONTHLY_ORG_REVIEW_LLM_TIMEOUT=200`.
- Result: `{"status": "generated", "mode": "forced + llm", 12 KR(s) scored,
  sidecar=proposed, goals not applied, kb_forget 0/0 applied,
  guardrail_notes: []}`; inputs `{goals_krs: 12, weekly_reviews: 1 (the new
  2026-W48 product review — consumed as designed), board_done_in_month: 16,
  board_cards: 16, alignment: docs/org/alignment/2026-11-26-first-pass.md}`.
  KR scores carried real validated evidence refs (task:15,
  file:docs/org/alignment/2026-11-26-first-pass.md, review:product/2026-W48).
- Note: the first forced attempt used the default 120s LLM timeout and the
  synthesis call timed out (large payload + full goals rewrite) — the skill
  degraded to the deterministic skeleton exactly as designed (status still
  "generated"). Re-run with the documented `MONTHLY_ORG_REVIEW_LLM_TIMEOUT=200`
  → real `forced + llm` synthesis.
- Temp artifacts DELETED after capture (`tmp/e2e_review_skills/mor_forced/`
  is gone).

**Skill Hub registration**:

```
$ python3 tests/test_skills_yaml.py
Ran 7 tests ... OK                          # 7/7

$ ./scripts/skill-hub-register.sh
note: http://localhost:4000 unreachable — using http://192.168.4.54:4000
added   monthly-org-review (registered + enabled)
added   weekly-agent-reviews (registered + enabled)
Done: 2 added, 54 already registered, 0 failed.

$ ./scripts/skill-hub-register.sh --list | grep -E "weekly-agent-reviews|monthly-org-review"
  weekly-agent-reviews
  monthly-org-review
```

Gateway list total: 56 (54 before + 2). **Re-verified 2026-11-27 04:5x UTC
by TODO 4** (`--list` shows both; 56 total). First attempt with underscored
names was rejected by the hub API (422: name must match `^[a-z0-9-]+$`) —
fixed by the hyphenated `agents-skills/<name>/` wrappers above.

**Secret scan**:

```
$ git diff | grep -cE 'sk-[A-Za-z0-9]{8,}'
0
$ git ls-files --others --exclude-standard | xargs grep -lE 'sk-[A-Za-z0-9]{8,}'
(no output — 0 matches across all untracked files)
```

No actual secret values from `.env` (LITELLM_MASTER_KEY, LITELLM_API_KEY,
KANBAN_DB_PASS, LITELLM_KEY_PRODUCT, ...) appear in any new/changed file —
env-only confirmed; no hardcoded `password=`/`api_key=`/`master_key=`
literals in the new code.

## Conservative-apply design decision (monthly_org_review) + why

**Decision**: the monthly review is **PROPOSAL-ONLY by default**. It always
writes (a) the review doc `docs/org/reviews/YYYY-MM.md` and (b) the sidecar
`docs/org/goals.proposed-YYYY-MM.md` (banner + the full PROPOSED rewrite of
`docs/org/goals.md` for the next cycle, or an explicit "no change proposed"
+ the current baseline). It does NOT overwrite `docs/org/goals.md` and does
NOT call `kb_forget` UNLESS `params.apply_goals=true` /
`params.apply_kb_forget=true` — both default **false** (the cron sets
neither). Applying is chuck's explicit act after reading the review.
`kb_forget`, when applied, is the server's two-step semantic delete (step 1
`kb_forget(query, kb)` returns matches and deletes nothing; step 2
`kb_forget(confirm=true, ids=[top match id])` deletes at most ONE point per
candidate; manifests are never deleted).

**Why**:

1. **Q7 autonomy table** (chuck-approved 2026-11-25): "Edit org/charter
   docs (`docs/org/`, `charter.md`)" = **single-approval** — a scheduled
   skill must not unilaterally rewrite org goals; the review doc is the
   approval record, and applying the sidecar is the approval.
2. **This run's global constraint**: "Do NOT modify the product charter or
   `docs/org/goals.md` (org goals stay untouched — proposals only)".
3. **`kb_forget` is a deletion of durable state** — Q7 tier "Explicit ask";
   the staleness pass therefore only lists candidates WITH evidence, and
   the two-step delete runs only with the explicit param.
4. **Never trust the LLM at the write boundary**: even with
   `apply_goals=true`, the guardrails still veto — the proposed rewrite must
   cover every domain in the current `goals.md` (else it is rejected and
   the sidecar says "no change proposed"); KRs are restricted to the
   goals.md list; scores clamped to [0,1]; evidence refs validated. A bad
   rewrite can never reach `goals.md`.
5. **The weekly skill is conservative by the same principle**: upcoming
   plans are SUGGESTIONS only (the agent does not create cards there — card
   promotion is single-approval at the review per Q7), and the board is
   read-only.

**Operational consequence**: at the first real monthly fire (2026-12-04,
first Friday), the review + sidecar land and wait; chuck reads the review,
then applies with `apply_goals=true` / `apply_kb_forget=true` (or edits the
sidecar first — it's a plain file).

## Uncommitted homelab diff (main session commits + pushes after the run)

The previous run's diff (21 files — `b155d5b`) was committed by the main
session before this run. This run's diff is purely additive:

`git status --short` (2026-11-27, after TODO 3; TODO 4 adds this report +
the plan-doc update):

```text
?? agents-skills/monthly-org-review/
?? agents-skills/weekly-agent-reviews/
?? docs/agents/product/reviews/
?? skills/monthly_org_review/
?? skills/weekly_agent_reviews/
```

No tracked file modified by this run (`git diff` empty);
`docs/org/goals.md` untouched.

## Gaps / notes (action needed)

1. **The 15:00 CT fire will regenerate the bootstrap doc.** The weekly job
   fires 2026-11-27 15:00 CT with the bootstrap doc already present — the
   non-stacking gate scans for a *prior-week* doc (strictly before the
   current ISO week), finds none, and runs unconditionally (bootstrap),
   overwriting `docs/agents/product/reviews/2026-W48.md` with a fresh
   synthesis — this time with the injected MCP client (the KB line will be
   real instead of "n/a (no MCP client injected)"). Expected behavior; the
   doc is a weekly artifact, not an append-only log.
2. **KB unavailable in the bootstrap artifact.** The real run used
   `client=None` (the MCP client is only injected by the skill-runner
   `_execute_skill`), so the KB line is the honest "n/a" — the first cron
   fire fixes it (see #1). `kb_bluebovine` does not exist yet (creates on
   first write — Q15); the skill handles the missing collection gracefully.
3. **Monthly LLM timeout headroom.** The monthly synthesis payload (full
   `goals.md` + all weekly reviews + board + the full proposed rewrite) can
   exceed the default 120s LLM timeout — the first forced run proved the
   degradation path (deterministic skeleton, status still "generated"); the
   documented `MONTHLY_ORG_REVIEW_LLM_TIMEOUT` env (set to 200 for the
   verification run) is the tuning knob. Consider setting it in the
   skill-runner env if the first real monthly fire degrades.
