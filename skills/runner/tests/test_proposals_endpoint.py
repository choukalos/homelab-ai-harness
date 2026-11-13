#!/usr/bin/env python3
"""Endpoint tests for the proposals admin API (Phase 3, slug-based).

Ported from branch mac-phase3-parallel (id-based API:
``GET /api/proposals/{id}``, ``POST /api/proposals/{id}/transition``) to
main's slug-based routes (thor's deployed version):

  GET  /api/proposals[?status=&limit=]
  GET  /api/proposals/{slug}
  POST /api/proposals/{slug}/{new_status}

Runs in a throwaway container built from skills/runner/Dockerfile (needs
fastapi + httpx; NO live MySQL — the proposals index degrades to DB-down,
which the auth/503 paths exercise; the happy path stubs the module
functions in-process). Uses FastAPI's TestClient WITHOUT the lifespan
(scheduler / DB init / memory warmup are not under test), same pattern as
test_sessions_endpoint.py.

Covers:
  - auth: no key -> 403, user key -> 403 (list/show/transition)
  - validation: bad status filter -> 400 (list), bad new_status -> 400
    (transition)
  - DB down: list -> 503; show -> 404; transition -> 409. Pinned
    deliberately: main's module degrades get/transition to None (only
    list_proposals raises ProposalsUnavailable), so a future change that
    surfaces 503 for all three is a deliberate, test-updating change.
  - happy path (module stubbed with an in-memory store): list payload
    {count, proposals} newest-first, status filter, show 200/404,
    transition 200 + invalid-transition 409
  - duplicate-window guard (F1, re-landed 2026-11-13): completed job
    in-window + same params -> existing job returned; failed job /
    different params / older-than-window / non-guarded skill -> no block
  - /metrics exposes the proposals_total{status} gauge (zero lines when
    DB down; main always renders the gauge — the branch's
    "proposals_total unavailable" marker no longer exists)

NOTE: the branch version also covered the duplicate-window guard
(``main._JOB_WINDOW_GUARDS``) in the job dispatch path. That feature was
dropped from main by the 2026-11-12 reconcile merge (e7b4797, "keep thor
(deployed) code"). The guard was re-landed 2026-11-13 (F1), and the
guard cases below were re-added with it.

Run inside the container:
    python3 tests/test_proposals_endpoint.py
(or on a host with a venv: pip install fastapi httpx)
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

SLUG_A = "add-inflight-job-checkpoint"
SLUG_B = "publish-file-subdirectory-enum-test"

# Ensure DB-down state (no lifespan ran; assert the degradation is real).
check("proposals index DB-down (no live MySQL in test)",
      proposals._DB_AVAILABLE is False)

# ---------------------------------------------------------------------------
# Auth (DB-down state — 403 must fire before any DB access)
# ---------------------------------------------------------------------------

print("== proposals admin API: auth ==")
for headers, label in [(None, "no key"), (USER, "user key")]:
    r = client.get("/api/proposals", headers=headers)
    check(f"list {label} -> 403", r.status_code == 403, f"got {r.status_code}")
    r = client.get(f"/api/proposals/{SLUG_A}", headers=headers)
    check(f"show {label} -> 403", r.status_code == 403, f"got {r.status_code}")
    r = client.post(f"/api/proposals/{SLUG_A}/accepted", headers=headers)
    check(f"transition {label} -> 403", r.status_code == 403, f"got {r.status_code}")

# ---------------------------------------------------------------------------
# Validation (DB down — 400 must fire before any DB access)
# ---------------------------------------------------------------------------

print("== proposals admin API: validation ==")
r = client.get("/api/proposals?status=bogus", headers=ADMIN)
check("list bad status -> 400", r.status_code == 400, f"got {r.status_code}")
r = client.post(f"/api/proposals/{SLUG_A}/bogus", headers=ADMIN)
check("transition bad status -> 400", r.status_code == 400, f"got {r.status_code}")

# ---------------------------------------------------------------------------
# DB down degradation
# ---------------------------------------------------------------------------

print("== proposals admin API: DB down ==")
r = client.get("/api/proposals", headers=ADMIN)
check("list admin + DB down -> 503", r.status_code == 503, f"got {r.status_code}")
r = client.get(f"/api/proposals/{SLUG_A}", headers=ADMIN)
check("show admin + DB down -> 404", r.status_code == 404, f"got {r.status_code}")
r = client.post(f"/api/proposals/{SLUG_A}/accepted", headers=ADMIN)
check("transition admin + DB down -> 409", r.status_code == 409, f"got {r.status_code}")

r = client.get("/metrics")
check("/metrics 200 (DB down)", r.status_code == 200, f"got {r.status_code}")
check("gauge zero lines when DB down",
      'proposals_total{status="open"} 0' in r.text
      and 'proposals_total{status="applied"} 0' in r.text)

# ---------------------------------------------------------------------------
# Happy path — stub the module functions with an in-memory store.
# (The endpoints call proposals.* through the module at request time, so
# attribute monkeypatching is enough; the SQL layer is covered by
# test_proposals.py.)
# ---------------------------------------------------------------------------

STORE = {
    SLUG_A: {
        "slug": SLUG_A,
        "title": "Record resumable checkpoints for long-running jobs",
        "evidence": ["memory:b243b2e2"],
        "target_files": ["docs/operations/job-checkpoints.md"],
        "status": "open",
        "created_at": "2026-11-08T19:27:20.315366+00:00",
        "reviewed_at": None,
    },
    SLUG_B: {
        "slug": SLUG_B,
        "title": "Add regression test for publish_file subdirectory enum",
        "evidence": ["git:bd2d2f32d502"],
        "target_files": ["skills/publish_file/SKILL.md"],
        "status": "accepted",
        "created_at": "2026-11-08T19:33:53.740885+00:00",
        "reviewed_at": "2026-11-10T12:00:00+00:00",
    },
}
_ALLOWED = {"open": ("accepted", "dismissed"), "accepted": ("applied",)}


def _stub_list(status=None, limit=50):
    rows = [dict(r) for r in STORE.values()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["created_at"], reverse=True)
    return rows[:max(1, min(int(limit), 200))]


def _stub_get(slug):
    row = STORE.get(slug)
    return dict(row) if row else None


def _stub_transition(slug, new_status):
    row = STORE.get(slug)
    if row is None or new_status not in _ALLOWED.get(row["status"], ()):
        return None
    updated = dict(row)
    updated["status"] = new_status
    updated["reviewed_at"] = "2026-11-12T00:00:00+00:00"
    STORE[slug] = updated
    return dict(updated)


proposals.list_proposals = _stub_list
proposals.get = _stub_get
proposals.transition = _stub_transition
proposals._DB_AVAILABLE = True

print("== proposals admin API: happy path (stubbed module) ==")
r = client.get("/api/proposals", headers=ADMIN)
check("list 200", r.status_code == 200, f"got {r.status_code}")
body = r.json()
check("list payload shape",
      body.get("count") == 2 and len(body.get("proposals", [])) == 2)
check("list newest first", body["proposals"][0]["slug"] == SLUG_B)
check("list rows carry slug payload",
      body["proposals"][1]["slug"] == SLUG_A
      and body["proposals"][1]["title"]
      == "Record resumable checkpoints for long-running jobs"
      and body["proposals"][1]["status"] == "open")

r = client.get("/api/proposals?status=accepted", headers=ADMIN)
check("list status filter",
      r.status_code == 200 and r.json()["count"] == 1
      and r.json()["proposals"][0]["slug"] == SLUG_B)

r = client.get(f"/api/proposals/{SLUG_A}", headers=ADMIN)
check("show 200",
      r.status_code == 200 and r.json()["slug"] == SLUG_A
      and r.json()["status"] == "open")

r = client.get("/api/proposals/does-not-exist", headers=ADMIN)
check("show missing -> 404", r.status_code == 404, f"got {r.status_code}")

r = client.post(f"/api/proposals/{SLUG_A}/accepted", headers=ADMIN)
check("transition open->accepted 200",
      r.status_code == 200 and r.json()["status"] == "accepted"
      and r.json()["reviewed_at"] is not None)

r = client.post(f"/api/proposals/{SLUG_A}/applied", headers=ADMIN)
check("transition accepted->applied 200",
      r.status_code == 200 and r.json()["status"] == "applied")

r = client.post(f"/api/proposals/{SLUG_B}/dismissed", headers=ADMIN)
check("transition accepted->dismissed -> 409",
      r.status_code == 409, f"got {r.status_code}")

r = client.post(f"/api/proposals/does-not-exist/accepted", headers=ADMIN)
check("transition unknown slug -> 409", r.status_code == 409, f"got {r.status_code}")

# ---------------------------------------------------------------------------
# Duplicate-window guard (in-memory path) — F1, re-landed 2026-11-13.
# The guard's hot path is the in-memory job store; no live DB needed.
# ---------------------------------------------------------------------------

print("== duplicate-window guard ==")

REFLECT_PARAMS = {"user": "chuck", "days": 7}


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
# /metrics — gauge series with a seeded (non-zero) value
# ---------------------------------------------------------------------------

print("== /metrics ==")
# Seed the real in-process gauge (the stubbed module does not touch it).
proposals._set_gauge({"open": 1, "accepted": 1, "dismissed": 0, "applied": 1})
r = client.get("/metrics")
check("/metrics 200", r.status_code == 200)
check("proposals gauge series present",
      'proposals_total{status="open"} 1' in r.text
      and 'proposals_total{status="accepted"} 1' in r.text
      and 'proposals_total{status="dismissed"} 0' in r.text
      and 'proposals_total{status="applied"} 1' in r.text)

# ---------------------------------------------------------------------------

print(f"\n{PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failures:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)