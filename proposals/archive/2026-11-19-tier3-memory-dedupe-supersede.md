# Memory store: dedupe/supersede at write time (stop the reflection pipeline re-storing lessons)

- slug: tier3-memory-dedupe-supersede
- date: 2026-11-19
- status: applied
- tier: 3
- target user: chuck
- source: workspace/ideas/suggested_mcp_improvements.md (item 5)

## Applied (2026-11-20)

Options (1) + (2) combined, plus the one-time cleanup; option (3)
(periodic compaction) **deferred** — see follow-up below.

**What changed (uncommitted working tree, for review):**
- `skills/runner/memory/interface.py` — `learn_from_turn` write path:
  for `source="harness_reflection"` deterministic single-fact writes
  (`infer=False`, one user message), the write scope is searched first
  with the lesson stem (date prefix stripped). A hit at/above
  `MEMORY_DEDUPE_THRESHOLD` (raw cosine) — or a same-stem / explicit-
  supersede match (`policy.is_supersede`) clearing the 0.5 relevance
  floor — is refreshed IN PLACE via `update_memory` (newer text wins,
  `updated_at` bumps); the existing id is returned instead of a new row.
  Non-fatal: any dedupe search/update error degrades to a plain insert.
  All other sources (`direct_user`, chat, …) are untouched.
  Note: the dedupe search runs mem0's raw semantic stage (embed +
  `vector_store.search`) because mem0 2.x `Memory.search` returns a
  fused hybrid score, not the raw cosine the threshold is defined on.
- `skills/runner/memory/policy.py` — `lesson_stem()`, `lesson_date()`,
  `is_supersede(new, existing)` (same lesson stem / newer date / explicit
  supersede wording).
- `skills/runner/memory/config.py` — `MEMORY_DEDUPE_THRESHOLD` (default
  **0.85** on raw cosine; 0 disables; documented in `.env` +
  `compose/compose.skill-runner.yml` passthrough).
- `skills/harness_reflection/skill.py` + `README.md` — supersede
  convention: when a lesson supersedes an earlier one, write only the
  current truth (no "superseding earlier counts" variants); the write
  path merges it into the existing entry.
- `skills/runner/memory/tests/test_dedupe.py` — new (40 checks: refresh
  not insert, new lesson inserts, search/update failure degrades to
  insert, non-reflection sources unaffected, policy + config tests).

**One-time cleanup (applied 2026-11-20, user `chuck`):** DRY-RUN
raw-cosine clustering (≥ 0.85, stem queries) over the 28 existing
`harness_reflection` `Lesson (...)` entries, then applied via the
in-process `update_memory`/`delete_memory`: **23 deleted, 1 keeper text
updated, 28 → 5 entries** (4 cluster keepers + 1 kept singleton
`1a51831b` at 0.8495 — below threshold, new information). Full ID list
+ per-cluster table: `docs/operations/2026-11-20-memory-dedupe-cleanup.md`.

**Deferred follow-up (option 3):** periodic compaction (weekly merge of
near-duplicate lessons) is NOT implemented — the write-time dedupe plus
this one-time cleanup cover the current pollution, so no standing job is
needed yet. Revisit if duplicates re-accumulate, or to fold the 5
remaining non-`Lesson` "duplication count is at least N" variants
(`4b14f019`, `a8500869`, `ebd20df4`, `b3030d8c`, `bda15e71`) that were
out of scope for the Lesson-only cleanup pass.

## What
The `mcp_memory` store is dominated by "Lesson (date): … -> fix" entries written by `harness_reflection`, and the same lessons are stored **4–8 times each** with minor wording variants (the "N reflection jobs in the same window" lesson exists with N = 3, 4, 6, 7, 8; one entry even notes it is "superseding earlier counts" — the pipeline *knows* it's duplicating but stores the new version anyway, because memory is add-only with no dedup/supersede at write time). Fix (pick one, or combine):
1. **Dedupe at write time in `memory_remember`** — before inserting, search for semantically near-identical existing facts; if found, update/refresh the existing entry (bump `updated_at`, merge counts) instead of inserting a new one.
2. **Supersede-in-place** — a `memory_supersede(old_id, new_text)` tool (or update path) so the reflection agent replaces instead of appending.
3. **Periodic compaction** — a weekly job that merges near-duplicate lessons and keeps the most recent/most complete version.

Recommendation: (1) or (2) as the primary fix, (3) as a safety net.

## Why (evidence)
- A top-10 "improvements" query (2026-11-17) returned the same ~5 lessons repeated; genuine new lessons get buried.
- The duplication feedback loop amplified the 2026-11-08 reflection-job incident (each duplicated run re-observed the duplicates and stored another lesson about them). The job duplication itself is fixed (window guard, `2026-11-08-harness-reflection-window-guard`, applied) — the store pollution remains.
- Evidence memory IDs (short prefixes, 2026-11-17): `da6e729f`, `73d000a3`, `4b14f019`, `8b554d87`, `07a55eea`, `15bd3947`, `543d64b5` (reflection dup), `3709a1e3`, `c0513482`, `fbe21baf`, `9f6e3aa1`, `3a917385`, `e20c6e2e`, `47068276` (recent_activity), `1a51831b`, `0308e8e4`, `1c72d164`, `817f1217`, `8e9d3d71`, `931582a8` (publish_file).

## Risk + rollback
Medium — this touches the memory write path. Rollback = revert. Test with a deliberate near-duplicate write (expect refresh, not a new row) and a genuinely new lesson (expect insert).

## Files touched
- `skills/runner/memory/interface.py` (+ `policy.py` for the supersede convention)
- `skills/harness_reflection/SKILL.md` (use the update path when a lesson supersedes)

---
_Drafted 2026-11-19 (pi, thor) from the workspace/ideas review. Review with `cli/proposals.sh`; applying is a human decision._
