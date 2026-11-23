# Preserve verified reference values across rebuilds

- slug: pinned-reference-values
- date: 2026-11-22
- status: applied (2026-11-23) — `reference.py`: `_merge_market_size` (by
  source+year; `pinned: true` entries survive fresh runs; an empty market
  phase keeps prior values) + `_merge_market_context` (empty-run guard),
  wired into `build_reference` + `retry_market`; tests in `test_reference.py`
- target user: chuck

## What
Add a pinned flag to share_indicators and market-size merge logic so verified seeded values are preserved when a rebuild returns empty or weaker data; only update unpinned fields or require explicit unpinned refresh.

## Why (evidence)
The session shows a full rebuild dropped market-size to 0 estimates and forced re-seeding of verified values.

Evidence refs:
- session:2026-10-13T19-54-31-925Z_01a136d4-b473-7320-b0d9-073b173b7377.part2

## Risk + rollback
Medium risk: pinned values can become stale. Rollback by removing the pinned flag or clearing pinned entries and rerunning the rebuild.

## Files touched
- reference.py

---
_Proposed by the weekly harness_reflection run (Tier 1, propose-only). Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._
