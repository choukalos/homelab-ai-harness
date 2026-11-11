# Make harness_reflection idempotent

- slug: harness-reflection-idempotency
- date: 2026-11-08
- status: open
- target user: chuck

## What
Update skills/harness_reflection/SKILL.md to add a lock or skip-if-recent-completed-run guard so concurrent or repeated reflection jobs do not duplicate work.

## Why (evidence)
harness_reflection had 3 runs in the same window.

Evidence refs:
- job:6fc164932f0d
- job:72afd0cfd2de
- job:0b58ce4c69ff

## Risk + rollback
Low; it could skip a legitimate manual run. Rollback by removing the guard.

## Files touched
- skills/harness_reflection/SKILL.md

---
_Proposed by the weekly harness_reflection run (Tier 1, propose-only). Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._
