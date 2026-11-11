# Prevent duplicate harness_reflection jobs in the same window

- slug: harness-reflection-window-guard
- date: 2026-11-08
- status: open
- target user: chuck

## What
Add an idempotency key such as harness_reflection:<YYYY-MM-DD HH:00> and a scheduler check that skips creation when a harness_reflection job is already running or completed in the same 30-minute window.

## Why (evidence)
Seven harness_reflection jobs were created between 19:25 and 20:15 on 2026-11-08, duplicating reflection work.

Evidence refs:
- job:0b58ce4c69ff
- job:72afd0cfd2de
- job:6fc164932f0d
- job:901823628a3c
- job:5ab2e7cfbbff
- job:2f89c9d16450
- job:669aafc99c7e

## Risk + rollback
Low risk; a missed guard could still create duplicates, and rollback is to remove the idempotency key/check.

## Files touched
- skills/runner/jobs.py

---
_Proposed by the weekly harness_reflection run (Tier 1, propose-only). Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._
