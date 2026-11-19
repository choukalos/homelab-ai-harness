# Record resumable checkpoints for long-running jobs

- slug: add-inflight-job-checkpoint
- date: 2026-11-08
- status: applied
- reviewed: 2026-11-13 — accepted + applied. `checkpoint` / `checkpoint_at`
  fields on the job record + `POST /skills/jobs/{job_id}/checkpoint`
  (write-through to the durable index) + `GET /api/jobs` list endpoint
  (status filter) in skills/runner/main.py; ops doc at
  docs/operations/job-checkpoints.md; 69-check test suite
  (skills/runner/tests/test_jobs_endpoint.py). A rebooted job hydrates as
  `interrupted` with its checkpoint intact — resume from next_step.
- target user: chuck

## What
Add a required checkpoint step to the /jobs durable ledger workflow: before long-running media/tab jobs, write task ID, current stage, and next resumable step to the ledger so work can be restored after a host reboot.

## Why (evidence)
The 2026-11-01 thor host reboot interrupted Back in Black tab work and destroyed in-flight session context.

Evidence refs:
- memory:b243b2e2-8dff-45f8-b4cc-0a3e4213c133
- memory:ed78a372-bfcd-4cd2-9a58-c6dc14cdaafc
- memory:7eea1c46-ed31-4f3d-9f01-3548c74f8f54

## Risk + rollback
Low; rollback by removing the checkpoint requirement and deleting the doc.

## Files touched
- docs/operations/job-checkpoints.md

---
_Proposed by the weekly harness_reflection run (Tier 1, propose-only). Review with `cli/proposals.sh`; applying is a human decision (Tier 2)._
