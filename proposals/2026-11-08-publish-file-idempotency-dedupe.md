# Deduplicate repeated publish_file jobs

- slug: publish-file-idempotency-dedupe
- date: 2026-11-08
- status: dismissed
- reviewed: 2026-11-13 — dismissed: duplicate of publish-file-dedup
  (same change, same evidence; that proposal carries the specific
  mechanism — content/intent key, return the existing completed job).
- target user: chuck

## What
Add idempotency or request deduplication to publish_file so identical publish requests in the same window are not retried as separate jobs.

## Why (evidence)
publish_file was flagged as retried with 24 runs during the week, creating duplicate job noise.

Evidence refs:
- job:abbba7d985b2
- job:e1573004cd89
- job:51dc49413e4a
- job:5b847b01aa86

## Risk + rollback
Medium risk if legitimate repeated publishes are suppressed; rollback by removing dedupe or keying on full request payload.

## Files touched
- agents-skills/publish_file/SKILL.md

---
_Proposed by the weekly harness_reflection run (Tier 1, propose-only). Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._
