# Memory store: dedupe/supersede at write time (stop the reflection pipeline re-storing lessons)

- slug: tier3-memory-dedupe-supersede
- date: 2026-11-19
- status: open
- tier: 3
- target user: chuck
- source: workspace/ideas/suggested_mcp_improvements.md (item 5)

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
