# Review Summary — tier3-memory-dedupe-supersede (applied 2026-11-20)

Review summary for `proposals/2026-11-19-tier3-memory-dedupe-supersede.md`
(status: **applied**). All changes are **uncommitted working-tree changes**
for review; nothing was committed and no containers/services were restarted.

## Per-file changes

| File | Change |
|---|---|
| `skills/runner/memory/interface.py` | Write-time dedupe/supersede in `learn_from_turn` for `source="harness_reflection"` single-fact writes (`infer=False`, one user message): search the write scope with the lesson stem (date prefix stripped) via the RAW cosine stage (mem0 2.x `Memory.search` returns a fused hybrid score, so the dedupe search runs `vector_store.search` directly). Hit ≥ `MEMORY_DEDUPE_THRESHOLD` (raw cosine) or a `policy.is_supersede` match clearing the 0.5 floor → refresh IN PLACE via `update_memory` (newer text wins, `updated_at` bumps), existing id returned. Any search/update error degrades to plain insert (non-fatal). All other sources untouched. |
| `skills/runner/memory/policy.py` | `lesson_stem()`, `lesson_date()`, `is_supersede(new, existing)` (same normalized stem / explicit supersede wording). |
| `skills/runner/memory/config.py` | `MEMORY_DEDUPE_THRESHOLD` (default **0.85** raw cosine; 0 disables). |
| `compose/compose.skill-runner.yml` | `MEMORY_DEDUPE_THRESHOLD` env passthrough (value in `.env`, gitignored). |
| `skills/harness_reflection/skill.py` + `README.md` | Supersede convention: write only the current truth (no "superseding earlier counts" variants); the write path merges into the existing entry. |
| `skills/runner/memory/tests/test_dedupe.py` | New test file (no mem0/live services; plain `python3`). |
| `proposals/2026-11-19-tier3-memory-dedupe-supersede.md` | Status `applied` + dated note (what changed, threshold default, cleanup counts/IDs, deferred compaction follow-up). |
| `docs/operations/2026-11-20-memory-dedupe-cleanup.md` | Ops note: method (DRY-RUN first), reviewed would-merge/would-delete table, applied result, kept singletons, out-of-scope remainder, rollback. |

## Test results

`python3 skills/runner/memory/tests/test_dedupe.py` → **ALL PASS (40 checks)**
(2026-11-20): policy stem/date/supersede helpers, config env parsing
(default 0.85, 0.9, 0, invalid→default), and the write path — (a)
near-duplicate lesson → refresh not insert (existing id returned, no second
row, `updated_at` bumped, stem query, write scope, raw-cosine path used —
mem0 fused search NOT called); (a2) same-stem supersede below 0.85 →
refresh; (b) genuinely new lesson → insert with provenance; (c)/(c2)
dedupe-search / update failure → degrades to plain insert; (d)/(d2)
`direct_user` and `chat` sources unaffected (no dedupe search); (e)
threshold=0 disables dedupe.

## Cleanup report (one-time, user `chuck`)

DRY-RUN raw-cosine clustering (≥ 0.85, stem queries) over the 28 existing
`harness_reflection` `Lesson (...)` entries → reviewed table → applied via
in-process `update_memory`/`delete_memory` (short-lived `docker exec
skill-runner python3`; no restarts):

- **28 → 5 entries: 23 deleted, 1 keeper text updated (`0308e8e4`), 0 failures.**
- Keepers: `3709a1e3` (recent_activity slow runs), `da6e729f` (reflection
  job duplication guard), `0308e8e4` (publish_file batch dupes),
  `0d37e5fc` (thor reboot context loss), `1a51831b` (kept singleton —
  0.8495 raw cosine, just under threshold, carries new information).
- Full per-cluster table + deleted ID list:
  `docs/operations/2026-11-20-memory-dedupe-cleanup.md`.
- **Post-apply verification (2026-11-20, read-only):** live store lists
  exactly the 5 keepers; 0 of the 23 deleted IDs present; `0308e8e4`
  `updated_at` = 2026-11-20T01:53Z.
- Out of scope (noted): 5 non-`Lesson` "duplication count is at least N"
  variants (`4b14f019`, `a8500869`, `ebd20df4`, `b3030d8c`, `bda15e71`).

## Deferred follow-up (proposal option 3)

Periodic compaction (weekly near-duplicate merge) is **NOT implemented** —
write-time dedupe + one-time cleanup cover the current pollution; no
standing job needed yet. Revisit if duplicates re-accumulate, or to fold
the 5 remaining non-`Lesson` variants.

## Git snapshot (2026-11-20, all uncommitted)

```
git status --short
 M compose/compose.skill-runner.yml
 M proposals/2026-11-19-tier3-memory-dedupe-supersede.md
 M skills/harness_reflection/README.md
 M skills/harness_reflection/skill.py
 M skills/runner/memory/config.py
 M skills/runner/memory/interface.py
 M skills/runner/memory/policy.py
?? docs/operations/2026-11-20-memory-dedupe-cleanup.md
?? docs/operations/2026-11-20-memory-dedupe-review-summary.md
?? skills/runner/memory/tests/test_dedupe.py

git diff --stat
 compose/compose.skill-runner.yml                   |   3 +
 .../2026-11-19-tier3-memory-dedupe-supersede.md    |  51 +++++++-
 skills/harness_reflection/README.md                |   2 +-
 skills/harness_reflection/skill.py                 |  17 ++-
 skills/runner/memory/config.py                     |   9 ++
 skills/runner/memory/interface.py                  | 137 +++++++++++++++++++++
 skills/runner/memory/policy.py                     |  72 ++++++++++-
 7 files changed, 282 insertions(+), 9 deletions(-)

HEAD: 08e7ede (no new commits — task left uncommitted for review)
```

Note: the running `skill-runner` container still serves the image-baked
`/app/memory` (pre-dedupe) until the image is rebuilt + the container
restarted — deliberately NOT done here (task constraint: no restarts).
The one-time cleanup ran against the mounted working-tree code in-process,
so the store state is final regardless.
