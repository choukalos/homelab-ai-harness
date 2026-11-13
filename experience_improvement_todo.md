# Experience Improvement Loop — TODO (Tier 0 + Tier 1)

**Date:** 2026-11-08

> **STATUS (verified 2026-11-10, from Mac; corrected 2026-11-12 on thor):**
> Phase 1 ✅ committed + installed on Mac.
> Phase 2 ✅ committed + deployed (ingest endpoint live; 0 ingests so far).
> **Phase 3 is BUILT + DEPLOYED + SCHEDULED on thor** (`harness_reflection` skill
> registered, 9 completed jobs 2026-11-08, 8 open proposals in the `proposals`
> table, weekly schedule `0 23 * * 0` UTC — next run 2026-11-15) **and its code
> was committed on thor all along** (`d3cbcd9`…`d63d650`, 2026-11-08) — it was
> simply never pushed, so the Mac's stale clone (at `2ead2be`) couldn't see it.
> The runner-side hardening (F1 window guard, F3 `cli/proposals.sh`, F4
> `proposals` table, F5 schedule entry) is in the repo, and
> `skills/harness_reflection/` is in the repo too (re-verified by the Mac's
> read-only recovery, `harness_reflection_prep.md`).
> Note (2026-11-12): the thor↔GitHub reconcile merge (kept thor's `main.py`,
> took the Mac docs) dropped the Mac hardening commit's CODE — F1 window
> guard + `tests/test_proposals*.py` — while the docs above survived, which
> is why this note looked stale. F1 was re-landed on main 2026-11-13: guard
> at all three launch sites + the Mac's ported test suites (60 unit /
> 40 endpoint, guard cases re-added) all green. The DB-down 404 (get) / 409
> (transition) degradation codes are pinned by test, not fixed — a future
> 503 fix is a conscious, test-updating change.
> Phase 4 ✅ committed + live (job/learning metrics on :8091 +
> `harness-learning.json` dashboard; committed 2026-11-12).
> Note: the Mac also built a parallel Phase 3 from its stale clone — preserved
> on branch `mac-phase3-parallel`, NOT in main (main runs the thor version).
**Origin:** Conversation about auto-improving the harness + memory. The voice-note
gap (wife's medical transcriptions done on the Mac never reached any store) exposed
the capture holes. This plan builds the capture + reflect/propose layers only.
**Scope:** **Tier 0 (capture) and Tier 1 (reflect/propose/measure) only.**
Tier 2 (apply harness changes) and Tier 3 (operational changes) are explicitly
out of scope — apply steps require an explicit ask (standing rules: no restarts /
no reboots / no whole-stack teardown without explicit request).

---

## 0. Tier definitions (governs everything below)

| Tier | Action | Who | This plan |
|------|--------|-----|-----------|
| 0 | Capture — store memories, lessons, session transcripts | automatic (user-initiated triggers allowed) | ✅ in scope |
| 1 | Reflect — analyze, propose harness changes, measure | automatic; humans review | ✅ in scope |
| 2 | Apply harness changes (skills, prompts, config) | human approves + applies | ❌ out of scope |
| 3 | Operational changes (restarts, reboots, deploys) | Chuck only | ❌ out of scope (manual steps flagged) |

**Privacy invariant (non-negotiable):** personal content defaults to `private`
(caller's own identity). `household=true` only on explicit user request. Session
transcripts are always private — never household.

---

## 1. Current state (verified 2026-11-08)

| Thing | State |
|---|---|
| Memory store | mem0 + Qdrant via skill-runner. `chuck`=38, `dylan`=7, `service`=3. Identity via `MEMORY_USER_KEYS` (chuck/dylan/service LiteLLM keys). Add-only. |
| Write paths | (a) skill-runner chat-loop writeback (siri flows), (b) explicit `memory_remember` MCP, (c) scheduled skills (`recent_activity`, `memory_review`) |
| Read paths | skill-runner chat `render_context` injection **only**. Pi sessions (homelab + Mac) do NOT read memory at start. |
| Conventions | `agents-skills/memory-conventions/SKILL.md` exists (memory vs `kb_medical` KB, provenance, when-to-remember) — but Mac pi doesn't have it, and its household guidance conflicts with Chuck's stated preference (medical voice notes = private to him) |
| Jobs ledger | `skill_jobs` MySQL table + `GET /api/jobs/{id}` (added 2026-11-04) |
| Scheduler | `scheduler/schedules.json` (git-tracked) → `~/.thor/scheduler.json` in container |
| Observability | Prometheus (skill-runner `/metrics` incl. `memory_*` series) + Grafana (`grafana/dashboards/`, provisioned) |
| **Holes** | 1. Mac pi sessions invisible to everything on the homelab. 2. Pi never reads memory at session start. 3. Voice-note/personal transcription content reaches no store. 4. `memory_review` is digest-only — no reflection, no lessons, no proposals. 5. No measurement of harness improvement. |

---

## 2. Phase 1 — `session-memory` pi skill (QW1, Tier 0)

**Goal:** pi sessions (homelab AND Mac) use memory at session start and close out
durable facts at session end. Closes holes 2 + 3.

**Deliverable:** `agents-skills/session-memory/SKILL.md` (pi skill — no code, no
rebuild; works on any pi connected to the litellm gateway).

**SKILL.md content requirements:**
- Frontmatter: `name: session-memory`, description tuned for routing: "Use at the
  start of any substantive session and before ending one — fetches relevant long-term
  memory and captures durable session outcomes."
- **Session start** (first substantive request, or `/skill:session-memory`):
  1. `memory_search` for the topic(s) the user is working on (top_k 5–10).
  2. If the session touches family/health/projects, also check `kb_search`
     (`kb_medical` for medical) per `memory-conventions`.
  3. Surface retrieved context briefly with provenance ("per your note 2026-11-02…"),
     or note "no relevant memory found" — never fabricate.
- **During session:** defer to `memory-conventions` for `memory_remember` / KB rules
  (do not duplicate those rules here — reference the skill).
- **Voice-note / personal transcription rule** (explicit, this is the gap that
  motivated this plan): after transcribing a personal voice note (medical, family,
  personal), follow `memory-conventions`: evolving reference material →
  `kb_medical`; durable facts → `memory_remember`. **Default scope: private to the
  caller.** `household=true` only if the user explicitly says the family should know.
  Never auto-upload raw transcript text to memory — store distilled facts only.
- **Session closeout** (user ends the session, or says "wrap up / close out"):
  1. If durable outcomes occurred (decisions, new facts, completed work worth
     remembering), call `memory_remember` with 1–3 distilled facts (importance=high
     for medical/key dates).
  2. If nothing durable: do nothing (no noise writes).
  3. Offer (don't do): "Want me to sync this session transcript to the homelab?
     (`session-sync` skill)" — only if that skill is installed.
- **Constraints:** no raw transcript content in memory facts; no writes on behalf of
  another identity; respect the no-restart/no-reboot standing rules (this skill never
  touches services).

**Also (Tier 1, proposed — not applied):** `memory-conventions` currently says
"family-relevant research (e.g. the wife's medical condition) → also household=true".
Chuck stated (2026-11-08) his wife's medical voice notes should be **private to him**.
Phase 3's reflection job should surface this as a **convention-update proposal**
(default: private; household only on explicit request). Do NOT edit
`memory-conventions/SKILL.md` in this phase.

**Acceptance:**
- On the homelab pi: new session, first request → memory search runs and is surfaced
  with provenance (visible in transcript).
- Force-load works: `/skill:session-memory`.
- Closeout produces ≤3 distilled facts when warranted, zero writes when not.

**Mac ingestion:** see §6. No rebuild. Commit + Chuck pulls on the Mac.

---

## 3. Phase 2 — `session-sync` pi skill + ingest endpoint (QW2, Tier 0)

**Goal:** pi session transcripts (esp. Mac) can be shipped to the homelab so the
reflection job (Phase 3) sees Mac activity. Closes hole 1.

### 3a. skill-runner endpoint (code)

- New route in `skills/runner/main.py`: `POST /api/sessions/ingest`
  - **Auth:** caller's LiteLLM key → `user_id` (same IdentityResolver as memory).
    Unknown key → 401. (Admin key NOT accepted — this is a user-scoped capture path.)
  - **Body:** `{host, session_id, started_at, ended_at, transcript, tags?}` where
    `transcript` is the session jsonl (or plain text) — **max 2 MB** (413 above).
  - **Storage:** `data/sessions/{user_id}/{YYYY-MM-DD}/{session_id}.jsonl` on the
    skill-runner data volume (new volume mount if needed — check compose).
  - **Index:** new MySQL table `session_ingests` (homelab DB):
    `id, user_id, host, session_id, started_at, ended_at, sha256, bytes, ingested_at`.
  - **Dedup:** same `user_id + session_id + sha256` → 200 `{status: "duplicate"}`
    (idempotent re-sync).
  - **Scope:** always private to the caller's user_id. No household flag exists here.
  - **Metrics:** Prometheus counter `sessions_ingested_total{user_id, status}`.
- Unit tests: auth 401/200, size cap 413, dedup, per-user isolation (chuck's upload
  not visible in dylan's list), sha256 correctness.
- New read route (admin-key, like `/api/memory/*`):
  `GET /api/sessions/{user_id}/ingests?since=...` (metadata only, no transcript
  bodies) — used by the reflection job + debugging.
- **MANUAL STEP (Tier 3):** rebuild `skill-runner:local` image + recreate container.
  Prepare + commit only; apply on explicit ask. Run `scripts/key-sync-check.sh`
  after (standing rule).

### 3b. `session-sync` pi skill (markdown)

**Deliverable:** `agents-skills/session-sync/SKILL.md`

- Description: "Ship the current pi session transcript to the homelab skill-runner
  for the reflection pipeline. Use when the user asks to sync/upload this session,
  or at session closeout when the user agrees."
- Workflow:
  1. Locate the current session jsonl under `~/.pi/agent/sessions/` (largest
     recently-modified file in the cwd's project dir).
  2. `curl -X POST http://<thor>:8091/api/sessions/ingest` with
     `Authorization: Bearer <LiteLLM key>` (from env / pi settings — never print
     the key), body per 3a.
  3. Report result (stored / duplicate / error).
- **Privacy rules (in the skill text):**
  - User-initiated only — never auto-upload mid-session.
  - Warn once before first upload that the transcript (which may contain personal
    content, e.g. medical voice notes) will be stored on the homelab under the
    caller's private identity.
  - Refuse to upload if the user says no; remember the choice for the session.
- **Constraints:** 2 MB cap — for longer sessions, sync the last N messages or
  split (document the split convention: `session_id.partN`).

**Acceptance:**
- From Mac pi: sync a session → row in `session_ingests`, file on disk, metrics
  counter increments. Re-sync → `duplicate`.
- dylan's key cannot read chuck's ingests (isolation test).
- Skill refuses auto-upload; requires user OK.

---

## 4. Phase 3 — `harness_reflection` skill (QW3, Tier 1)

**Status (2026-11-10, Mac; corrected 2026-11-12):** skill live on thor (see
header). The deployed runner-side code in main is thor's version:
`skills/runner/proposals.py` (durable `proposals` index — idempotent DDL at
startup, admin API `GET /api/proposals[?status=]`, `GET /api/proposals/{slug}`,
`POST /api/proposals/{slug}/{new_status}` (slug-based),
`proposals_total{status}` gauge on `/metrics`),
`cli/proposals.sh` (list/show/accept/dismiss/mark-applied by slug), and the
`weekly-harness-reflection` entry in `scheduler/schedules.json`.
NOTE (2026-11-12 reconcile): the duplicate-window guard (`_JOB_WINDOW_GUARDS`,
24h for `harness_reflection`) was Mac-only work and was DROPPED from main.py by
merge e7b4797 ("keep thor (deployed) code"). (Earlier note claimed it was in
main — corrected.) Re-landed on main 2026-11-13 (guard at all three launch
sites; its endpoint tests re-added alongside the ported suites).
The Mac's parallel id-based variant lives on branch `mac-phase3-parallel`;
its `tests/test_proposals*.py` were ported to main's slug-based API on
2026-11-13 (skills/runner/tests/test_proposals*.py).
Remaining: rebuild (Tier 3, manual), F2 dedupe via `cli/proposals.sh dismiss`.

**Goal:** weekly closed-loop reflection: memories + ingested sessions + jobs ledger
→ memory maintenance, lessons, and **harness change proposals** (propose only).
Closes hole 4.

**Deliverable:** new skill-runner skill `skills/harness_reflection/`
(`skill.py` + `skill.yml` + `test_skill.py`), in-process like `recent_activity`.
`memory_review` stays untouched (user-facing digest).

**Inputs (7-day window, per user, default chuck):**
1. New/updated memories (in-process `interface.list_memories`, both scopes).
2. Ingested sessions (`session_ingests` + transcript files, Phase 2).
3. `skill_jobs`: failures, retries, durations, approvals/cancels.
4. Git log of the homelab repo (what changed, by whom).
5. Existing open proposals (dedup — never re-propose).

**Outputs (three classes):**

1. **Memory maintenance (Tier 0 writes, add-only semantics):**
   - Contradictions / superseded facts → `memory_remember` supersede statements
     (self-contained, per existing convention).
   - **Corrections detected in sessions** (user corrected the agent: "no, …",
     "I told you …", repeated same correction ≥2×) → preference memory,
     `importance=high`, provenance tag (session ref + date).
   - **Friction lessons** (failed jobs, lost work, restarts, retries) → structured
     lesson memory: `Lesson (<date>): <what happened> → <what to do differently>.`
2. **Harness change proposals (Tier 1 — propose only, never apply):**
   - Each proposal: `proposals/YYYY-MM-DD-<slug>.md` in the repo + row in new MySQL
     table `proposals` (`id, slug, title, evidence, target_files, status,
     created_at, reviewed_at`). Statuses: `open → accepted|dismissed → applied`
     (transitions done by Chuck via `cli/proposals.sh` — new small CLI:
     `list / show / accept / dismiss / mark-applied`).
   - Proposal format: **What** (concrete diff or instruction), **Why** (evidence:
     memory IDs, job IDs, session refs), **Risk + rollback**, **Files touched**.
   - Guardrails: **≤5 proposals per run**; every proposal needs ≥1 evidence ref;
     no proposal may touch `.env`, compose restart semantics, or memory privacy
     scoping; proposals that would change `memory-conventions` scope rules are
     allowed (that's the point) but must quote the user's statement as evidence.
   - **Expected first proposal (known, from this week):** update
     `memory-conventions` household guidance — wife's medical content defaults to
     **private**, household only on explicit request (Chuck, 2026-11-08).
3. **Review digest (Tier 1 output):** short artifact (≤1 page): N memories
   maintained, N lessons stored, N proposals open (with one-line summaries).
   Push into the next `morning_brief` context (or append to `memory_review`
   digest) so Chuck sees it without hunting.

**Scheduling:** add to `scheduler/schedules.json` (git-tracked): weekly, Sunday
23:00 UTC, `user=chuck`, skill `harness_reflection`, `days=7`. (Scheduled runs
inherit `service` identity per D10 — the skill must run the analysis as `service`
but WRITE memory as the target user via the in-process interface, exactly like
`recent_activity` does. Verify this identity path in the first test run.)

**Acceptance:**
- Dry run (`run-now`): digest artifact produced; ≤5 proposals; all proposals have
  evidence refs; no file outside `proposals/` modified by the job itself.
- A planted correction ("no, use triads for metal — I said that last week too")
  → preference memory stored with `importance=high`.
- `cli/proposals.sh list` shows the open proposals; `accept` transitions status.
- No Tier 2/3 actions anywhere in the run (assert in tests: job never calls
  compose/restart/apply paths).

**MANUAL STEP (Tier 3):** skill-runner image rebuild + recreate (can share the
Phase 2 rebuild if both land before apply). Scheduler config change takes effect on
container start.

---

## 5. Phase 4 — Harness health dashboard (QW4, Tier 1)

**Goal:** measure whether the loop is working. Closes hole 5.

**Deliverable:** `grafana/dashboards/harness-learning.json` (provisioned — drop in
the existing dashboards dir; no rebuild).

**Panels (rows):**
1. **Jobs** — success rate, p50/p95 duration, failures/retries (from `skill_jobs`
   via existing job metrics; 7d/30d).
2. **Memory** — search hit rate, writeback stored/total, errors by op, per-user
   memory counts (existing `memory_*` series).
3. **Capture** — `sessions_ingested_total` by user/host (Phase 2 metric), ingest
   volume over time.
4. **Learning** — new memories/week, lessons stored/week (tag via metadata
   `source`/`agent`), proposals: open / accepted / dismissed / applied (from
   `proposals` table — expose as a small gauge endpoint on skill-runner
   `/metrics`, e.g. `proposals_total{status}`).
5. **Friction** — job failures by skill, restart/recreate events (docker events or
   manual annotations), time-to-completion for recurring task types.

**North-star metrics (top row, big numbers):**
- Correction rate (corrections per week, trending down)
- % of jobs completing without retry
- Proposals accepted / total proposed (loop quality)

**Acceptance:** dashboard loads with live data for every panel; no panel depends on
a metric not emitted by Phases 2–3.

---

## 6. Mac skill ingestion — yes, this works

Pi discovers skills recursively from user/project skill dirs, including
`~/.agents/skills/` (user-level, all projects) and `<project>/.agents/skills/`.
The homelab repo is git — so the flow is:

1. **Homelab:** commit `agents-skills/session-memory/` (+ `session-sync/`) to the
   repo.
2. **Mac (ask pi to do this — one prompt):**
   ```
   Pull the homelab repo (clone it if you don't have a clone, e.g. via ssh to
   thor:/home/chuck/homelab), then install the pi skills session-memory and
   session-sync by symlinking them into ~/.agents/skills/ (create the dir if
   needed). Verify pi can see them (/reload, check startup diagnostics).
   ```
   Symlinks keep the Mac in lockstep with the repo — future skill updates are a
   `git pull` away.
3. **Verify MCP access on the Mac:** the skills need `mcp_memory` (+ `mcp_knowledge`)
   tools. Ask the Mac pi: "list your MCP tools; confirm mcp_memory is present and
   that memory_list returns user_id=chuck." If missing, the Mac pi's settings need
   the litellm gateway MCP entry (same config this homelab pi uses) + Chuck's
   LiteLLM key — so everything lands under `chuck`, never another identity.
4. **Trust:** pi warns on unfamiliar project skills — these are Chuck's own repo,
   but review the SKILL.md text before first use on the Mac (they contain
   privacy-relevant instructions; that's the point).

**Reliability caveat (known):** skills are instruction-based — the model loads the
SKILL.md when the task matches, and can be forced with `/skill:name`. There is no
hard session-start hook. If routing proves unreliable in practice, the upgrade path
is a pi **extension** (JS hook, same git+symlink distribution, into the extensions
dir) — not in this plan, revisit after 2 weeks of data.

---

## 7. Out of scope (explicit)

- **Tier 2:** auto-applying any proposal. Proposals are reviewed + applied by Chuck
  (or by an explicit future ask).
- **Tier 3:** restarts/reboots/deploys. All image rebuilds + container recreates are
  flagged MANUAL STEP and applied only on explicit ask; `scripts/key-sync-check.sh`
  after any key/container change (standing rule).
- **Auto-upload of transcripts** — session-sync is user-initiated only.
- **Privacy scope changes** — private default is invariant; household only via
  explicit flag/statement.
- **Raw transcript storage in memory/KB** — distilled facts only; transcripts live
  in `data/sessions/` (private, admin-readable) and are NOT indexed into Qdrant
  full-text (the reflection job reads them directly, in-window, then they can be
  pruned — retention: 90 days default, configurable).

---

## 8. Rollout order + dependencies

| Order | Phase | Rebuild? | Depends on |
|---|---|---|---|
| 1 | Phase 1 `session-memory` skill | ❌ (markdown only) | — |
| 2 | Phase 2 endpoint + `session-sync` skill | ✅ skill-runner (manual step) | Phase 1 (closeout offer) |
| 3 | Phase 3 `harness_reflection` | ✅ (can share Phase 2 rebuild) | Phase 2 (session inputs) — runs with memory+git+jobs inputs even without Phase 2 |
| 4 | Phase 4 dashboard | ❌ (Grafana provisioning) | Phases 2–3 metrics |

Suggested first ask after this plan lands: "Build Phase 1 and Phase 2 of
experience_improvement_todo.md (code + skills + tests, prepared and committed —
do not rebuild or recreate containers)."