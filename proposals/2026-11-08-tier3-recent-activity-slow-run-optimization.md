# Reduce recent_activity run duration with bounded scan and caching

- slug: recent-activity-slow-run-optimization
- date: 2026-11-08
- status: open
- tier: 3
- target user: chuck
- reorganized: 2026-11-19 — file renamed with tier prefix (slug unchanged); sibling
  `recent-activity-bounded-scan-cache` dismissed 2026-11-08 (archived).

## What
In the recent_activity skill, cap the default scan window to the last 24h and cache the computed activity summary for 300s; include the scan window and duration in the job log.

## Why (evidence)
recent_activity runs took 176s, 151s, and 133s in jobs 95f3b66a1fc1, 89cffb3b5d79, and ae4c71d2265c.

Still slow a week later (2026-11-15): runs of 142s, 102s, 101s (memory `3709a1e3`;
the reflection agent flagged this three separate occasions — recurring, not one-off).

Evidence refs:
- job:95f3b66a1fc1
- job:89cffb3b5d79
- job:ae4c71d2265c
- memory:3709a1e3 (2026-11-15: 142s / 102s / 101s)

## Risk + rollback
Low; cache can be disabled by setting TTL to 0 and the scan window can be reverted to the previous value.

## Files touched
- skills/recent_activity/SKILL.md

---
_Proposed by the weekly harness_reflection run (Tier 1, propose-only). Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._
