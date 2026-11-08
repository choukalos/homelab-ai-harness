# Bound and cache recent_activity aggregation

- slug: recent-activity-bounded-scan-cache
- date: 2026-11-08
- status: open
- target user: chuck

## What
Update skills/recent_activity/SKILL.md to use a bounded scan window and a short-lived cache for activity aggregation, and log the scan duration when the window is exceeded.

## Why (evidence)
recent_activity runs took 176s, 151s, and 133s.

Evidence refs:
- job:95f3b66a1fc1
- job:89cffb3b5d79
- job:ae4c71d2265c
- memory:e4f14f8b-75b3-4e04-b7d9-191fbb203ddd

## Risk + rollback
Low; a bounded window may omit older activity. Rollback by reverting the skill change.

## Files touched
- skills/recent_activity/SKILL.md

---
_Proposed by the weekly harness_reflection run (Tier 1, propose-only). Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._
