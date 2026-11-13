# Job Checkpoints — Resuming Long-Running Work After a Reboot

_Ops doc for the `add-inflight-job-checkpoint` proposal (applied 2026-11-13).
Mechanism: `checkpoint` field on the job record + `POST /skills/jobs/{job_id}/checkpoint`
+ `GET /api/jobs` list endpoint, in `skills/runner/main.py`.

## Why

The 2026-11-01 thor host reboot interrupted Back in Black tab work and
destroyed the in-flight session context — the media pipeline had to redo
completed stages. The durable job index (`skill_jobs` MySQL table) already
survives restarts, but a job's record said nothing about *where* the work
left off. Checkpoints close that gap: a job now carries its "where I left
off" marker, so a reboot costs a resume, not a redo.

## What a checkpoint is

A checkpoint is a small JSON blob stored on the job record:

```json
{
  "task_id": "back-in-black-tabs-2026-11-13",
  "stage": "transcribing",
  "next_step": "resume transcription from track 14 (tracks 1-13 done, in /home/chuck/data/media/work/bib/)",
  "data": {"done": 13, "total": 29, "workdir": "/home/chuck/data/media/work/bib/"},
  "updated_at": "2026-11-13T03:12:44.123456+00:00"
}
```

- **task_id** — stable name for the overall piece of work (may span several
  job records).
- **stage** — the stage the job was in when it wrote the checkpoint.
- **next_step** — the exact next resumable action, written for a human or
  agent who did not do the work.
- **data** — free-form resume context: offsets, file lists, partial outputs,
  queue state.
- **updated_at** — stamped by the runner (not the caller).

The checkpoint lives on the job record itself, and the whole record is
write-through to MySQL (`skill_jobs.data`), so it survives both a runner
restart and a host reboot (MySQL data is on disk).

## Writing a checkpoint

```bash
curl -s -X POST "http://192.168.4.54:8091/skills/jobs/<job_id>/checkpoint" \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "back-in-black-tabs-2026-11-13",
    "stage": "transcribing",
    "next_step": "resume from track 14; tracks 1-13 in /home/chuck/data/media/work/bib/",
    "data": {"done": 13, "total": 29}
  }'
```

Also at `POST /api/jobs/<job_id>/checkpoint`. Returns the updated job (200),
404 for an unknown job id. Lenient by design: allowed on any job status —
the meaningful case is `pending`/`running`.

### Workflow rule (the "required" part)

Long-running media/tab jobs **must** write a checkpoint:

1. **Before starting** — `stage: "starting"`, `next_step` = the first stage,
   `data` = the full work plan (file list, workdir, totals).
2. **At each stage boundary** — update `stage` + `next_step` as each stage
   completes (e.g. after every track in a transcription batch).
3. **On failure** — the job's `error` field records what broke; the last
   checkpoint still says where to resume.

Short jobs (publish_file, recent_activity, …) do not need checkpoints —
they are cheap to redo.

## Recovery after a host reboot

On startup the runner hydrates the durable index and marks every in-flight
job `interrupted` — **with its checkpoint intact**.

```bash
# 1. Find what was running when the host died:
curl -s "http://192.168.4.54:8091/api/jobs?status=interrupted" | python3 -m json.tool

# 2. Read each job's checkpoint:
curl -s "http://192.168.4.54:8091/api/jobs/<job_id>" | python3 -c '
import json,sys
j = json.load(sys.stdin)
print("stage:     ", j["checkpoint"]["stage"])
print("next_step: ", j["checkpoint"]["next_step"])
print("data:      ", j["checkpoint"]["data"])'

# 3. Resume from checkpoint.next_step — either continue the same work in a
#    new session (the interrupted job stays terminal as the audit trail) or
#    re-launch the skill with the checkpoint data in params.
```

`GET /api/jobs` (a.k.a. the list endpoint) supports `?status=...`
(pending|running|completed|failed|awaiting_approval|cancelled|interrupted)
and `?limit=N` (clamped 1..200, default 50), newest first. It reads the
durable index when MySQL is up and falls back to the in-memory store
otherwise.

## Invariants

- Checkpoints never block or fail the job — a failed checkpoint write is
  logged and the job continues (same best-effort posture as the durable
  index itself).
- The runner stamps `updated_at`; callers cannot forge timestamps.
- An interrupted job is terminal — resuming means new work referencing the
  checkpoint, not reviving the old job record.
- No auth on job endpoints (LAN-only service, same as approve/cancel).