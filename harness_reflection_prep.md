# Harness Reflection (Phase 3) — State, Recovery & Build-Prep

**Date:** 2026-11-10
**Status (2026-11-10, evening):** F1/F3/F4/F5 implemented in the repo —
`skills/runner/proposals.py` (durable index + admin API + `proposals_total`
gauge), the duplicate-window guard in `main.py`, `cli/proposals.sh`, and the
`weekly-harness-reflection` entry in `schedules.json`. Tests: 37 unit + 25
endpoint checks (all green). Remaining: F2 (dismiss the 3 duplicate open
proposals — one command each once the API is live) and F6 (Phase 4 dashboard).
**Companion to:** `experience_improvement_todo.md` (the plan)
**Why this doc exists:** Phase 3 was built and deployed on thor (2026-11-08) but the
code was **never committed to the repo**. This doc records the verified state, the
recovery steps, and the fix list so Phase 3 can be brought into git and stabilized.

---

## 1. Verified state (2026-11-10, from the live system)

Phase 3 is **built, deployed, scheduled, and working** — it just isn't in git.

| Thing | State | Evidence |
|---|---|---|
| `harness_reflection` skill | Deployed on skill-runner (one of 22 registered skills; channels cli/pi/n8n/scheduler; max_runtime 600s) | `GET /skills` on 192.168.4.54:8091 |
| Scheduled run | `weekly-harness-reflection` — cron `0 23 * * 0` UTC, user=chuck, days=7, enabled. Last run 2026-11-08 23:00 UTC, next 2026-11-15 23:00 UTC | `GET /api/schedule` |
| Jobs | 9 completed runs 2026-11-08 19:25–23:03 UTC (8 deploy-test runs + 1 scheduled) | `skill_jobs` (homelab DB) |
| Proposals | 8 open rows in `proposals` table (created 2026-11-08 19:27–20:17 UTC), all with evidence refs | `proposals` table |
| Memory maintenance | Lessons + supersede statements written with `source`/`agent` = `harness_reflection` (e.g. 4 friction lessons) | `memory_search` |
| Digest artifact | `harness_reflection_20261108_2303.md` under `/home/chuck/data/media/homelab_reports/harness_reflection/` | `GET /skills/jobs/6739464b03b2/artifact` |
| Dedup guardrail | Working in the last run: "0 new this run, 8 open before run" | job summary |
| **Code in repo** | ❌ **NOT committed** — no `skills/harness_reflection/`, no `cli/proposals.sh`, no `proposals` migration, no `schedules.json` entry in git | repo tree @ `2ead2be` |

**Where the code lives:** `compose/compose.skill-runner.yml` mounts
`../skills:/app/skills:ro` — i.e. the skill code is in thor's repo working tree at
`/home/chuck/homelab/skills/harness_reflection/` (uncommitted). The scheduler entry
lives in thor's `/home/chuck/homelab/scheduler/schedules.json` (also uncommitted —
the git-tracked copy has 8 schedules, the live one has 9).

### Live `proposals` schema (for the committed migration)

```sql
CREATE TABLE IF NOT EXISTS proposals (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  slug         VARCHAR(192)  NOT NULL UNIQUE,
  title        VARCHAR(512)  NOT NULL,
  evidence     JSON          NULL,
  target_files JSON          NULL,
  status       VARCHAR(32)   NOT NULL DEFAULT 'open',   -- open|accepted|dismissed|applied
  created_at   VARCHAR(64)   NOT NULL,
  reviewed_at  VARCHAR(64)   NULL,
  KEY idx_status (status)
) ENGINE=InnoDB;
```

### Open proposals (8, as of 2026-11-10)

| id | slug | title | note |
|---|---|---|---|
| 8 | harness-reflection-window-guard | Prevent duplicate harness_reflection jobs in the same window | dup of #5 — fix together |
| 7 | publish-file-dedup | Deduplicate repeated publish_file requests | supersedes #6 (broader evidence) |
| 6 | publish-file-idempotency-dedupe | Deduplicate repeated publish_file jobs | dup of #7 |
| 5 | harness-reflection-idempotency | Make harness_reflection idempotent | dup of #8 |
| 4 | recent-activity-bounded-scan-cache | Bound and cache recent_activity aggregation | dup of #3 |
| 3 | recent-activity-slow-run-optimization | Reduce recent_activity run duration with bounded scan and caching | — |
| 2 | publish-file-subdirectory-enum-test | Add regression test for publish_file subdirectory enum | — |
| 1 | add-inflight-job-checkpoint | Record resumable checkpoints for long-running jobs | — |

---

## 2. Recovery (get Phase 3 code into git) — needs thor access

**Constraint (Chuck, 2026-11-10): NO `git pull` on thor, no changes to the live
repo.** The live container mounts `../skills` ro from the working tree, and the
live tree is 8 commits behind origin — pulling would rewrite the running
harness's files. So the recovery is **read-only against the live repo**:
copy the uncommitted files *out*, commit them in a **fresh clone** in
`/home/chuck/workspace`, push from there. The live tree, the live repo's git
state, and the running container are all untouched.

### Step 1 — inspect + stage (read-only against the live repo)

```bash
# Inspect (read-only git commands — safe)
cd /home/chuck/homelab
git status --short                 # review what's uncommitted
git rev-parse HEAD                 # record live tree's HEAD for provenance

# Stage: copy the uncommitted Phase 3 artifacts OUT of the live tree
mkdir -p /home/chuck/workspace/harness-recovery-2026-11-10
cp -a /home/chuck/homelab/skills/harness_reflection \
      /home/chuck/workspace/harness-recovery-2026-11-10/
# Proposal .md artifacts, if the skill writes them outside the skill dir:
[ -d /home/chuck/homelab/proposals ] && cp -a /home/chuck/homelab/proposals \
      /home/chuck/workspace/harness-recovery-2026-11-10/ || true
# If a thor-local proposals CLI exists, stage it for comparison (the repo
# version is canonical — do NOT commit this one):
[ -f /home/chuck/homelab/cli/proposals.sh ] && cp -a /home/chuck/homelab/cli/proposals.sh \
      /home/chuck/workspace/harness-recovery-2026-11-10/thor-local-proposals.sh || true
find /home/chuck/workspace/harness-recovery-2026-11-10 -type f | sort   # verify completeness
```

Expected uncommitted: `skills/harness_reflection/*` (the only required
artifact). `scheduler/schedules.json` and `cli/proposals.sh` are **already in
the repo** (commit `cc02fa7`) — no need to copy them; if `git status` shows
other modified files, list them and decide separately (guardrail: commit ONLY
the Phase 3 skill).

### Step 2 — commit in a fresh clone + push (isolated from the live repo)

```bash
cd /home/chuck/workspace
git clone https://github.com/choukalos/homelab-ai-harness.git harness-repo-recovery
cd harness-repo-recovery
git log --oneline -1               # must be e85a68a (recovery redesign docs)

mkdir -p skills/harness_reflection
cp -a /home/chuck/workspace/harness-recovery-2026-11-10/skills/harness_reflection/. \
      skills/harness_reflection/
[ -d /home/chuck/workspace/harness-recovery-2026-11-10/proposals ] && \
  cp -a /home/chuck/workspace/harness-recovery-2026-11-10/proposals/. proposals/ || true

git add skills/harness_reflection
[ -d proposals ] && git add proposals
git status --short                 # review exactly what will be committed
git -c user.name=choukalos -c user.email=choukalos@yahoo.com commit \
  -m "Phase 3: recover harness_reflection skill from thor (uncommitted since 2026-11-08)

experience_improvement_todo.md Phase 3. Built + deployed + verified on thor
2026-11-08 (9 completed jobs, 8 open proposals, weekly 0 23 * * 0 UTC) but
never checked in — the skill lived only in the live working tree. Recovered
read-only: files copied out of the live tree (no pull, no live-tree changes);
committed in a fresh clone. Runner-side hardening (window guard, proposals
API, CLI, schedule) already landed in cc02fa7."
git push origin main
```

### Fallback if the push fails (no GitHub credentials on thor)

Nothing is lost: the staged files sit in
`/home/chuck/workspace/harness-recovery-2026-11-10/` (MCP-readable from the
Mac). Say so and the Mac picks them up via the workspace MCP and pushes from
here.

### Verify after (from the Mac)

`git log --oneline -3` shows the recovery commit; `skills/harness_reflection/`
exists in the repo with `skill.py` + `skill.yml` + `test_skill.py`; the live
container on thor is untouched (no restart, no file changes).

**Cleanup (after the Mac verifies):** `rm -rf
/home/chuck/workspace/harness-repo-recovery /home/chuck/workspace/harness-recovery-2026-11-10`

**Note:** the recovery commit changes NOTHING on the running system. The live
tree stays 8 commits behind until a deliberate sync + Tier 3 rebuild (separate
decision — see §3 sequencing).

---

## 3. Fix list (post-recovery, in priority order)

| # | Fix | Target | Notes |
|---|---|---|---|
| F1 | **Idempotency / window guard** — prevent duplicate `harness_reflection` jobs in the same window (proposals #5 + #8) | `skills/runner/jobs.py` and/or the skill | ✅ **Done in repo** — `_JOB_WINDOW_GUARDS` in `skills/runner/main.py` (24h window, same skill+params, blocking statuses pending/running/completed/awaiting_approval; failed jobs don't block; best-effort, never breaks job creation). Covered by endpoint tests. |
| F2 | **Dedupe open proposals** — dismiss #6 (dup of #7), #4 (dup of #3), #5 (dup of #8) | `proposals` table via `cli/proposals.sh dismiss` | 8 open → 5 distinct. The dedup guardrail works now (last run: 0 new) — these are deploy-window stragglers. |
| F3 | **`cli/proposals.sh`** if missing — `list / show / accept / dismiss / mark-applied` (status transitions + `reviewed_at`) | `cli/proposals.sh` | ✅ **Done in repo** — `cli/proposals.sh` (list/show/accept/dismiss/mark-applied), wraps the new `/api/proposals*` admin endpoints (admin-key guarded, same pattern as `memory-admin.sh`). |
| F4 | **Committed `proposals` migration** (idempotent `CREATE TABLE IF NOT EXISTS`, schema in §1) | `skills/runner/` init or a migration script | ✅ **Done in repo** — `skills/runner/proposals.py::init_db()` runs the exact live DDL at startup (idempotent, non-fatal — same pattern as the sessions index). |
| F5 | **`schedules.json` entry** (landed with recovery §2) | `scheduler/schedules.json` | ✅ **Done in repo** — `weekly-harness-reflection`, cron `0 23 * * 0` UTC, user=chuck, days=7 (matches the live entry). |
| F6 | **Phase 4 dashboard** (`grafana/dashboards/harness-learning.json`) | Grafana provisioning | Separate work item — see plan §5. Needs `proposals_total{status}` gauge on skill-runner `/metrics`. |

**Sequencing (updated):** F1/F3/F4/F5 landed in the repo (this commit). On thor:
recover `skills/harness_reflection/` (only uncommitted piece), then rebuild
skill-runner (MANUAL STEP — Tier 3, explicit ask) — the new image picks up the
window guard, proposals API + migration, and the committed schedule. Then F2
(dismiss the 3 duplicate open proposals via `cli/proposals.sh`), then F6.

---

## 4. Guardrails (from the plan — unchanged)

- **Tier 1 only:** the reflection job proposes; it never applies. Proposals are
  reviewed + applied by Chuck.
- **Tier 3:** image rebuilds / container recreates are MANUAL STEPS, applied only
  on explicit ask; `scripts/key-sync-check.sh` after any key/container change.
- **Privacy:** transcripts stay private per-user; memory writes are distilled facts
  only; private-default is invariant.
- **≤5 proposals per run**, every proposal needs ≥1 evidence ref (verified working
  in the 2026-11-08 runs).

---

## 5. Mac-side status (done 2026-11-10)

- ✅ Local clone synced to `origin/main` (`2ead2be`); stale local tailscale commit
  preserved on branch `backup/stale-tailscale-plan` (superseded by `714a7be` on
  remote).
- ✅ `session-memory` + `session-sync` installed into `/Users/chuck/Code/skills/`
  (pi skill dir per `settings.json`); `memory-conventions` synced to the Phase 1
  privacy update.
- ✅ MCP verified on Mac: `mcp_memory` (search/list/remember) + `mcp_knowledge`
  reachable via the litellm gateway; `memory_list` returns `user_id=chuck`.
- ⏳ First Mac session-sync upload: user-initiated, whenever a session is worth
  syncing (the `session-sync` skill).