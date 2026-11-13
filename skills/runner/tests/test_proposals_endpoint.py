#!/usr/bin/env python3
"""Endpoint tests for the proposals admin API + duplicate-window guard (Phase 3).

Runs in a throwaway container built from skills/runner/Dockerfile (needs
fastapi + httpx; NO live MySQL — the proposals index degrades to DB-down,
which the auth/503 paths exercise; the window guard exercises its
in-memory path, which is the hot path anyway). Uses FastAPI's TestClient
WITHOUT the lifespan (scheduler / DB init / memory warmup are not under
test), same pattern as test_sessions_endpoint.py.

Covers:
  - proposals admin API: no key -> 403, wrong key -> 403, admin key + DB
    down -> 503 (list) / 404 (get) / 409 (transition) — see note below
  - duplicate-window guard (experience_improvement_todo.md F1):
    * completed harness_reflection job in-window + same params -> launch
      returns the EXISTING job (no new job created)
    * failed job in-window -> guard does NOT block (retry allowed)
    * different params -> guard does NOT block
    * job older than the window -> guard does NOT block
    * non-guarded skill -> two launches, two jobs (unchanged behaviour)
  - /metrics exposes the proposals gauge (zero counts when DB down)

DB-DOWN DEGRADATION — PINNED, NOT FIXED (2026-11-12):
  ``proposals.get()`` / ``proposals.transition()`` degrade to ``None`` when
  the index is unavailable, so ``GET /api/proposals/{slug}`` returns 404
  ("not found") and ``POST /api/proposals/{slug}/{new_status}`` returns 409
  ("not allowed") instead of 503 — "index unavailable" masquerades as
  "not found / not allowed". Only ``list_proposals`` raises
  ``ProposalsUnavailable`` -> 503. The checks below pin this behaviour on
  purpose: a future fix (e.g. get/transition raising ProposalsUnavailable
  -> 503) is a conscious, test-updating API change, not a silent one.
  (Separately, a MySQL outage AFTER startup raises pymysql errors from
  get/transition -> 502; that path needs a live DB to exercise and is not
  covered here.)

Run inside the container:
    python3 tests/test_proposals_endpoint.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

# Env must be set BEFORE importing main (identity resolver + modules read
# it at import / first use).
os.environ["SKILL_RUNNER_LOG_DIR"] = "/tmp/sr-test-logs"
os.environ["MEMORY_USER_KEYS"] = "chuck=KEY_CHUCK,dylan=KEY_DYLAN,service=KEY_SERVICE"
os.environ["KEY_CHUCK"] = "sk-test-chuck-key"
os.environ["KEY_DYLAN"] = "sk-test-dylan-key"
os.environ["KEY_SERVICE"] = "sk-test-service-key"
os.environ["MEMORY_ADMIN_API_KEY"] = "sk-test-admin-key"
os.environ["SESSIONS_DATA_ROOT"] = tempfile.mkdtemp(prefix="proposals-e2e-")
os.environ["MEMORY_ENABLED"] = "false"

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, RUNNER_ROOT)

import proposals  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)

PASS = 0
FAIL = 0
FAILURES = []


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    print(f"  {'PASS' if cond else 'FAIL'}: {name}" + (f" — {detail}" if detail else ""))
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(name)


ADMIN = {"X-API-Key": "sk-test-admin-key"}
USER = {"X-API-Key": "sk-test-chuck-key"}

# Ensure DB-down state (no lifespan ran; assert the degradation is real).
check("proposals index DB-down (no live MySQL in test)", proposals.available() is False)

REFLECT_PARAMS = {"user": "chuck", "days": 7}
SLUG = "test-slug"


def seed_job(skill: str, params: dict, status: str, age_hours: float = 0.0) -> main.Job:
    """Insert a job into the in-memory store as if it had already run."""
    job = main.Job(skill=skill, params=params, requester="scheduler",
                   channel="scheduler", dry_run=True)
    if age_hours:
        job.created_at = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    job.status = status
    job.completed_at = datetime.now(timezone.utc).isoformat()
    main.jobs[job.job_id] = job
    return job


# ---------------------------------------------------------------------------
# Proposals admin API — auth + degradation
# ---------------------------------------------------------------------------

print("== proposals admin API: auth ==")
for headers, label in [(None, "no key"), (USER, "user key")]:
    r = client.get("/api/proposals", headers=headers)
    check(f"list {label} -> 403", r.status_code == 403, f"got {r.status_code}")
    r = client.get(f"/api/proposals/{SLUG}", headers=headers)
    check(f"get {label} -> 403", r.status_code == 403, f"got {r.status_code}")
    r = client.post(f"/api/proposals/{SLUG}/accepted", headers=headers)
    check(f"transition {label} -> 403", r.status_code == 403, f"got {r.status_code}")

print("== proposals admin API: DB down (pinned degradation codes) ==")
r = client.get("/api/proposals", headers=ADMIN)
check("list admin + DB down -> 503", r.status_code == 503, f"got {r.status_code}")
# PINNED (not fixed): get() degrades to None -> 404 masquerades "index
# unavailable" as "not found". A future fix to 503 must update this check.
r = client.get(f"/api/proposals/{SLUG}", headers=ADMIN)
check("get admin + DB down -> 404 (pinned)", r.status_code == 404, f"got {r.status_code}")
# PINNED (not fixed): transition() degrades to None -> 409 masquerades
# "index unavailable" as "not allowed". A future fix to 503 must update it.
r = client.post(f"/api/proposals/{SLUG}/accepted", headers=ADMIN)
check("transition admin + DB down -> 409 (pinned)", r.status_code == 409,
      f"got {r.status_code}")

# ---------------------------------------------------------------------------
# Duplicate-window guard (in-memory path)
# ---------------------------------------------------------------------------

print("== duplicate-window guard ==")

# 1. Completed job in-window, same params -> launch returns the existing job.
seeded = seed_job("harness_reflection", REFLECT_PARAMS, main.JobStatus.completed)
before = len(main.jobs)
r = client.post("/skills/harness_reflection",
                json={"params": REFLECT_PARAMS, "dry_run": True})
check("guard hit: 200", r.status_code == 200, f"got {r.status_code}")
body = r.json()
check("guard hit: returns existing job_id", body.get("job_id") == seeded.job_id,
      f"got {body.get('job_id')} want {seeded.job_id}")
check("guard hit: no new job created", len(main.jobs) == before,
      f"jobs {before} -> {len(main.jobs)}")
check("guard hit: duplicate logged on existing job",
      any("window guard" in line for line in seeded.logs))
main.jobs.pop(seeded.job_id, None)  # tidy up — must not leak into the next case

# 2. Failed job in-window -> guard does NOT block (retry allowed).
failed = seed_job("harness_reflection", REFLECT_PARAMS, main.JobStatus.failed)
before = len(main.jobs)
r = client.post("/skills/harness_reflection",
                json={"params": REFLECT_PARAMS, "dry_run": True})
new_id = r.json().get("job_id")
check("failed job: new job launched", r.status_code == 200
      and new_id is not None and new_id != failed.job_id,
      f"got {new_id}")
check("failed job: job count grew", len(main.jobs) == before + 1)
main.jobs.pop(new_id, None)  # tidy up
main.jobs.pop(failed.job_id, None)

# 3. Different params -> guard does NOT block.
seeded3 = seed_job("harness_reflection", {"user": "chuck", "days": 30},
                   main.JobStatus.completed)
before = len(main.jobs)
r = client.post("/skills/harness_reflection",
                json={"params": REFLECT_PARAMS, "dry_run": True})
new_id = r.json().get("job_id")
check("different params: new job launched", r.status_code == 200
      and new_id is not None and new_id != seeded3.job_id)
check("different params: job count grew", len(main.jobs) == before + 1)
main.jobs.pop(new_id, None)  # tidy up
main.jobs.pop(seeded3.job_id, None)

# 4. Job older than the window (25h > 24h) -> guard does NOT block.
seeded4 = seed_job("harness_reflection", REFLECT_PARAMS, main.JobStatus.completed,
                   age_hours=25)
before = len(main.jobs)
r = client.post("/skills/harness_reflection",
                json={"params": REFLECT_PARAMS, "dry_run": True})
new_id = r.json().get("job_id")
check("stale job: new job launched", r.status_code == 200
      and new_id is not None and new_id != seeded4.job_id)
check("stale job: job count grew", len(main.jobs) == before + 1)
main.jobs.pop(new_id, None)  # tidy up
main.jobs.pop(seeded4.job_id, None)

# 5. Non-guarded skill -> two launches, two distinct jobs (unchanged behaviour).
r1 = client.post("/skills/siri_ask", json={"params": {"q": "hi"}, "dry_run": True})
r2 = client.post("/skills/siri_ask", json={"params": {"q": "hi"}, "dry_run": True})
check("non-guarded: two distinct jobs",
      r1.status_code == 200 and r2.status_code == 200
      and r1.json().get("job_id") != r2.json().get("job_id"))

# 6. Guard config sanity: harness_reflection is the only guarded skill.
check("guard config: harness_reflection 24h",
      main._JOB_WINDOW_GUARDS.get("harness_reflection") == 24.0)
check("guard config: siri_ask not guarded", "siri_ask" not in main._JOB_WINDOW_GUARDS)

# ---------------------------------------------------------------------------
# /metrics — proposals gauge (zero counts when DB down)
# ---------------------------------------------------------------------------

print("== /metrics ==")
r = client.get("/metrics")
check("/metrics 200", r.status_code == 200)
check("proposals gauge present (all 4 status labels)",
      all(f'proposals_total{{status="{s}"}}' in r.text
          for s in ("open", "accepted", "dismissed", "applied")))
check("proposals gauge zero when DB down",
      'proposals_total{status="open"} 0' in r.text)

# ---------------------------------------------------------------------------

print(f"\n{PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failures:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)