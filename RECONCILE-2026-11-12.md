# Reconcile thor ↔ GitHub (Mac Phase 3 divergence) — 2026-11-12

**Purpose:** if the agent crashes mid-way, read this file, check "Where am I?",
and continue from the first unchecked step. All steps are idempotent or
explicitly guarded. **Never `git pull` on thor** — use explicit
`git fetch` / `git merge` / `git push`.

## What happened (short version)

- Sun 2026-11-08 (thor): experience-improvement Phase 1–3 committed
  (`a01007e`…`d63d650`) but **never pushed**; Phase 4 (job/learning metrics +
  `harness-learning.json` dashboard) left **uncommitted** (20:31–20:37).
- Tue 11-10 / Wed 11-11 (Mac, stale clone at `2ead2be`): built a **parallel
  Phase 3** (`cc02fa7`: its own `proposals.py`/`main.py`/CLI/tests), redesigned
  the recovery docs (read-only against thor), "recovered" the
  `harness_reflection` skill from thor's live working tree (read-only staging
  in `/home/chuck/workspace/harness-recovery-2026-11-10/` → fresh clone), and
  **pushed 7 commits to origin** (tip `a34c32a`).
- Nothing was lost on thor: all committed work intact; the uncommitted Phase 4
  work was still in the working tree (verified by mtimes + file identity).
- Result: `main` (thor) and `origin/main` **diverged** off base `2ead2be`.
  The live skill-runner container (rebuilt 20:39 Sunday) runs thor's code and
  already exposes the Phase 4 metrics (`skill_jobs_total`,
  `harness_reflection_maintenance_total`) — Phase 4 is live, just uncommitted.

## Key hashes / refs

| ref | value | meaning |
|---|---|---|
| merge base | `2ead2be` | common ancestor (Grafana memory-panel commit) |
| thor tip pre-merge | `d63d650` | Phase 3 dry-run artifacts commit |
| origin tip | `a34c32a` | Mac's "recovered skill + proposals.insert()" |
| `mac-phase3-parallel` | `a34c32a` | preservation branch for all Mac work (step 2) |

Mac-recovered files that are **byte-identical** to thor (verified 2026-11-12):
`skills/harness_reflection/{skill.py,skill.yml,test_skill.py}`,
`proposals/2026-11-08-*.md` (8 files), `scheduler/schedules.json`,
`skills/morning_brief/skill.py` (staged copy). Mac-only files:
`harness_reflection_prep.md`, `proposals/.gitkeep`, its own `proposals.py`,
`main.py` wiring, `cli/proposals.sh` (id-based), `tests/test_proposals*.py`,
recovery-doc changes, `experience_improvement_todo.md` status note.

## Steps

- [x] **0. This doc committed** (commit: `aa2d80c`)
- [x] **1. Commit Phase 4 on thor** (commit: `1aff065`, 6 files, worktree clean)
      Files (exactly these 6, add explicitly, NOT `git add -A`):
      `skills/runner/jobs_metrics.py`, `skills/runner/learning_metrics.py`,
      `grafana/dashboards/harness-learning.json` (new),
      `skills/harness_reflection/skill.py`, `skills/runner/Dockerfile`,
      `skills/runner/main.py` (modified).
      Message: `Phase 4: job + learning metrics (Prometheus) + harness-learning Grafana dashboard`
- [x] **2. Preserve Mac work** (branch `mac-phase3-parallel` @ `a34c32a`, pushed to origin)
- [x] **3. Merge** (merge commit: `e7b4797`, amended per the LESSON above;
      note fix: `be0ed43`). Steps (a) `git rm` of the two Mac test files and
      (b) the `experience_improvement_todo.md` correction were done as
      described.
- [x] **4. Pushed** `9c932a9`; `git rev-parse main origin/main` identical.
- [x] **5. Staging dir archived** (renamed, not deleted):
      `/home/chuck/workspace/harness-recovery-2026-11-10` →
      `/home/chuck/workspace/.staging-archived-2026-11-12`
      (everything in it verified to be in git; delete the archive only after
      Chuck confirms.)

## Where am I? (crash recovery)

Run these first:
```
git -C /home/chuck/homelab status --short
git -C /home/chuck/homelab log --oneline -6
git -C /home/chuck/homelab rev-parse main origin/main 2>/dev/null
git -C /home/chuck/homelab branch --list mac-phase3-parallel
```
Then:
- **Step 1 incomplete:** the 6 Phase 4 files are still modified/untracked in
  the working tree → re-run step 1. (If a commit already exists, check it
  contains exactly those 6 files: `git show --stat HEAD`.)
- **Step 2 incomplete/redo:** `git branch -f` + push are idempotent.
- **Step 3 in progress:** if `git status` shows `MERGING`/unmerged paths →
  `git merge --abort` and redo step 3 from the top. If the merge already
  committed but (a)/(b) are missing → do just (a)/(b).
- **Step 4:** re-running `git push origin main` is safe (fast-forward only;
  if it's rejected, STOP and re-read this doc — someone else pushed).
- **Nothing lost, ever, by re-running:** Mac work is on origin (`main` until
  step 4, `mac-phase3-parallel` from step 2); thor work is committed from
  step 1. Worst case after any crash: redo the current step.

## Merge conflict policy (reference — `-X ours` handles it)

- Code (`proposals.py`, `main.py`, `Dockerfile`, `cli/proposals.sh`,
  `skill.py`, `skill.yml`, `test_skill.py`, `schedules.json`): **thor/ours**
  (deployed + tested; 9 completed jobs, 8 open proposals in MySQL).
- Docs (`harness_reflection_prep.md` — the Mac's recovery-redesign commits
  e85a68a/be27622/8af3c51 all landed here, NOT in
  `docs/thor_ai_harness_rebuild.md`): **Mac/theirs** (local never touched
  them post-base, so they merge clean anyway).
- `experience_improvement_todo.md`: Mac's note merges clean (local untouched
  post-base) → then correct the two wrong claims (below).
- **LESSON (what actually happened):** `-X ours` only resolves *conflicting*
  hunks — the Mac's non-conflicting Phase 3 hunks in `main.py` were applied
  too (+117 lines). Fix applied: `git checkout 1aff065 -- skills/runner/main.py`
  + `git rm` the two Mac test files + `git commit --amend` (merge commit was
  local-only, nothing pushed). Verify with
  `git diff 1aff065 HEAD --stat` → only the 2 Mac doc files.
  If redoing from scratch: `git merge --abort`, then `git merge -s ours`
  (full-tree ours) + `git checkout origin/main -- harness_reflection_prep.md
  experience_improvement_todo.md` + commit.
- Expected conflicts (auto-resolved by `-X ours`): `main.py`,
  `proposals.py`, `Dockerfile`, `cli/proposals.sh`. **But `main.py` still
  needs the manual restore above.**

## Post-merge verification (before step 4)

```
# merge commit brought in ONLY the Mac docs (no code changes):
git diff HEAD^1 HEAD --stat   # → only harness_reflection_prep.md + experience_improvement_todo.md
# code tree identical to pre-merge thor main (Phase 4 commit + d63d650 state):
git diff 1aff065 HEAD -- skills/ cli/ scheduler/   # → empty
# Mac docs present:
git show HEAD:harness_reflection_prep.md >/dev/null && echo prep-doc OK
# Mac tests NOT in main:
git ls-files skills/runner/tests/   # → only test_sessions*.py
# live system untouched:
curl -s http://192.168.4.54:8091/metrics | grep -c skill_jobs_total   # ≥ 1
# host tests still pass:
python3 skills/runner/tests/test_sessions.py | tail -1   # → "PASS: 41 passed, 0 failed"
git status --short   # → clean
```

## Baseline (pre-merge, 2026-11-12)

- `python3 skills/runner/tests/test_sessions.py` → "PASS: 41 passed, 0 failed"
- `python3 skills/runner/tests/test_sessions_endpoint.py` → `ModuleNotFoundError: No module named 'fastapi'` at import (host has no fastapi; pre-existing limitation — this file is unchanged by the merge)
- Live runner (192.168.4.54:8091) exposes Phase 4 metrics: `skill_jobs_total` (incl. `harness_reflection{status="completed"} 9`), `harness_reflection_maintenance_total{kind="lesson"} 4`

## Note corrections (experience_improvement_todo.md, step 3b)

The Mac's 2026-11-10 status note contains two factual errors:
1. "its code was NEVER COMMITTED to this repo (skill lives only in thor's
   working tree)" → **wrong**: Phase 3 was committed on thor
   (`d3cbcd9`…`d63d650`, 2026-11-08 20:22–20:23) but never pushed; the Mac's
   clone was stale at `2ead2be`.
2. "Phase 4 ❌ not started (dashboard)" → **wrong**: Phase 4 was in progress
   on thor (uncommitted 2026-11-08 20:31–20:37) and is now committed (step 1)
   and live in the skill-runner container (metrics visible on :8091).
Edit the note minimally to reflect this (keep the Mac's verified facts:
9 completed jobs, 8 open proposals, schedule `0 23 * * 0` UTC, next run
2026-11-15).

## Out of scope / follow-ups (do NOT do in this run)

- Rebuilding/redeploying the skill-runner container (it already runs the
  Phase 4 code — rebuilt 20:39 Sunday).
- Porting the Mac's `test_proposals*.py` to thor's slug-based API (follow-up).
- Reviewing/applying the 8 open proposals (human task via `cli/proposals.sh`).
- Deleting the archived staging dir (needs Chuck's OK).

## Final state (2026-11-12, all steps done ✅)

- `main` == `origin/main` == `9c932a9` (thor's code, Phases 1–4, Mac docs merged in).
- `mac-phase3-parallel` == `a34c32a` on origin (all Mac work preserved).
- Working tree clean; live runner on :8091 exposes Phase 4 metrics.
- Staging dir at `/home/chuck/workspace/.staging-archived-2026-11-12`
  (delete after Chuck confirms).
- This doc lives at repo root (`RECONCILE-2026-11-12.md`); after the final
  commit, `git show main:RECONCILE-2026-11-12.md` has the checked-off version.