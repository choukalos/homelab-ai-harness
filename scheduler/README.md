# Scheduler — scheduled skill jobs

Scheduled jobs for the Thor Skill Runner (`skills/runner/scheduler.py`).

## Files

| File | Tracked? | Purpose |
|---|---|---|
| `scheduler/schedules.json` (this dir) | ✅ git | **Definitions** — the job list. Edit here, commit, done. |
| `/home/chuck/data/scheduler/state.json` | ❌ | **Run state** — `last_run_at` / `next_run_at` per job id. Scheduler-managed; never edit by hand. |

The split (2026-09-04) keeps the working tree clean: the scheduler rewrites
state after every job run, so state lives outside git.

## How changes take effect

The definitions file is mounted **read-only** into the skill-runner
(`SCHEDULER_CONFIG_PATH=/app/scheduler/schedules.json`). The scheduler checks
the file's mtime every 60s and **hot-reloads** on change — edit + save is
enough, no `docker compose up -d` needed. (A container restart also works.)

## Adding a job

Append an entry to `schedules.json`:

```json
{
  "id": "unique-stable-id",
  "name": "Human-readable name",
  "cron": "0 9 * * 1-5",
  "skill": "morning_brief",
  "params": { "publish": true },
  "enabled": true,
  "timezone": "America/Chicago"
}
```

- `id` — stable, unique; run state is keyed by it (renaming an id resets its state).
- `cron` — 5 fields: `minute hour day_of_month month day_of_week`
  (supports `*`, `*/N`, `A-B`, `A,B,C`).
- `skill` — a skill name from `skills/`.
- `params` — passed to the skill's `run(params, job)` (see the skill's
  `skill.yml` inputs).
- `timezone` — IANA name; cron matches **local** wall-clock time
  (`America/Chicago` = CST/CDT with DST). Default `UTC`.

## Current jobs

| id | Schedule | Skill | Notes |
|---|---|---|---|
| `daily-recent-activity` | `0 17 * * *` (17:00 CT, daily) | `recent_activity` | 7-day window; reports stay in `/home/chuck/data/media/homelab_reports/` |
| `weekday-morning-brief` | `0 9 * * 1-5` (09:00 CT, Mon–Fri) | `morning_brief` | `publish: true` → overwrites `/home/chuck/data/media/public/briefs/latest.md` → https://choukalos.com/files/briefs/latest.md (single-file retention) |

## Ops

- **Status:** `curl -s http://192.168.4.54:8091/api/schedule` (all jobs + next run times)
- **Run now:** `curl -s -X POST http://192.168.4.54:8091/api/schedule/<id>/run-now` → returns `job_id`
- **Logs:** `docker logs skill-runner 2>&1 | grep -i sched`
- **Disable a job:** set `"enabled": false` (hot-reloaded) — or `DELETE /api/schedule/<id>`
  (dev only; the definitions file is read-only in production, so prefer the git edit).