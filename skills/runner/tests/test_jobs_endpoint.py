#!/usr/bin/env python3
"""Endpoint + unit tests for job checkpoints (add-inflight-job-checkpoint).

Covers the resumable-checkpoint feature landed 2026-11-13:

  - Job model: checkpoint / checkpoint_at default to None; the whole job
    record (including checkpoint) is what the durable index stores
  - set_job_checkpoint: canonical shape {task_id, stage, next_step, data,
    updated_at}, runner-stamped updated_at + checkpoint_at, log line,
    write-through persist (INSERT data JSON carries the checkpoint)
  - hydration/recovery: a running job with a checkpoint in the durable
    index hydrates as `interrupted` with its checkpoint intact (the
    post-reboot resume story); corrupt rows are skipped
  - POST /skills/jobs/{id}/checkpoint (+ /api/jobs alias): 200 echo,
    404 unknown job, partial body, free-form data preserved, lenient on
    terminal jobs
  - GET /api/jobs list endpoint: durable-index path (status filter,
    limit clamp), invalid status -> 400, in-memory fallback when the DB
    is down

The durable index is faked with a mini in-memory emulation of the
skill_jobs table (status column + data JSON), so the DB code paths
(hydrate SELECT, list SELECT with WHERE status, persist INSERT) run for
real against the fake.

Run inside the container:
    python3 tests/test_jobs_endpoint.py
(or on a host with a venv: pip install fastapi httpx)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

# Env must be set BEFORE importing main (identity resolver + modules read
# it at import / first use).
os.environ["SKILL_RUNNER_LOG_DIR"] = "/tmp/sr-test-logs"
os.environ["MEMORY_USER_KEYS"] = "chuck=KEY_CHUCK,service=KEY_SERVICE"
os.environ["KEY_CHUCK"] = "sk-test-chuck-key"
os.environ["KEY_SERVICE"] = "sk-test-service-key"
os.environ["MEMORY_ADMIN_API_KEY"] = "sk-test-admin-key"
os.environ["SESSIONS_DATA_ROOT"] = tempfile.mkdtemp(prefix="jobs-e2e-")
os.environ["MEMORY_ENABLED"] = "false"

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, RUNNER_ROOT)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from main import (  # noqa: E402
    Job,
    JobCheckpointRequest,
    JobListResponse,
    JobStatus,
    set_job_checkpoint,
)

# No `with` block -> lifespan does not run -> no real MySQL init.
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


# ---------------------------------------------------------------------------
# Fake durable job index — mini in-memory emulation of the skill_jobs table
# (status column + data JSON). Records SQL; emulates CREATE TABLE,
# INSERT ... ON DUPLICATE KEY UPDATE, and SELECT [WHERE status = %s]
# [ORDER BY ...] [LIMIT %s].
# ---------------------------------------------------------------------------

class FakeJobsDB:
    def __init__(self):
        # job_id -> (status, data_json)
        self.rows: dict[str, tuple[str, str]] = {}
        self.sqls: list[tuple[str, object]] = []
        self.execute_error = None

    def conn(self):
        return FakeConn(self)


class FakeConn:
    def __init__(self, db: FakeJobsDB):
        self.db = db

    def cursor(self):
        return FakeCursor(self.db)

    def commit(self):
        pass

    def close(self):
        pass


class FakeCursor:
    def __init__(self, db: FakeJobsDB):
        self.db = db
        self._rows: list = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args=None):
        self.db.sqls.append((sql, args))
        if self.db.execute_error is not None:
            raise self.db.execute_error
        s = sql.lstrip().upper()
        if s.startswith("CREATE TABLE"):
            self._rows = []
        elif s.startswith("INSERT INTO"):
            # (job_id, skill, status, created_at, updated_at, data)
            job_id, _skill, status, _created, _updated, data = args
            self.db.rows[job_id] = (status, data)
        elif s.startswith("SELECT"):
            rows = list(self.db.rows.values())
            if "WHERE STATUS" in s:
                rows = [r for r in rows if r[0] == args[0]]
            limit = args[-1] if args else None
            picked = rows[:limit] if limit is not None else rows
            self._rows = [(data,) for (_status, data) in picked]
        elif s.startswith("UPDATE"):
            self.rowcount = 1
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None


db = FakeJobsDB()
main._jobs_db_conn = lambda: db.conn()
main._JOBS_DB_AVAILABLE = True

# ---------------------------------------------------------------------------
# Job model + set_job_checkpoint (unit)
# ---------------------------------------------------------------------------

print("== Job model: checkpoint fields ==")

j0 = Job(skill="deep_research")
check("Job default: checkpoint is None", j0.checkpoint is None)
check("Job default: checkpoint_at is None", j0.checkpoint_at is None)
check("Job dump: checkpoint serialised (None)",
      json.loads(j0.model_dump_json())["checkpoint"] is None)

print("== set_job_checkpoint ==")

job = Job(skill="media_pipeline")
job.status = JobStatus.running
set_job_checkpoint(job, {
    "task_id": "bib-tabs",
    "stage": "transcribing",
    "next_step": "resume from track 14",
    "data": {"done": 13, "total": 29},
}, source="test")
cp = job.checkpoint
check("checkpoint shape: task_id", cp["task_id"] == "bib-tabs")
check("checkpoint shape: stage", cp["stage"] == "transcribing")
check("checkpoint shape: next_step", cp["next_step"] == "resume from track 14")
check("checkpoint shape: data", cp["data"] == {"done": 13, "total": 29})
check("checkpoint shape: updated_at stamped by runner", cp["updated_at"] is not None)
check("checkpoint_at set", job.checkpoint_at is not None)
check("checkpoint_at == checkpoint.updated_at", job.checkpoint_at == cp["updated_at"])
check("log line added",
      any("Checkpoint (test)" in line for line in job.logs),
      f"logs={job.logs[-1:] if job.logs else 'none'}")
check("log names the stage",
      any("stage=transcribing" in line for line in job.logs))

# Write-through persist: the INSERT data JSON must carry the checkpoint.
inserts = [a for (sql, a) in db.sqls if sql.lstrip().upper().startswith("INSERT")]
check("set_job_checkpoint persisted (INSERT issued)", len(inserts) >= 1)
if inserts:
    data_json = json.loads(inserts[-1][5])
    check("persisted data JSON carries checkpoint",
          data_json["checkpoint"]["next_step"] == "resume from track 14")
    check("persisted data JSON carries checkpoint_at",
          data_json["checkpoint_at"] is not None)

# Partial input: missing keys -> None / {} (not KeyError).
job2 = Job(skill="media_pipeline")
set_job_checkpoint(job2, {"stage": "starting"}, source="unit")
check("partial input: stage set", job2.checkpoint["stage"] == "starting")
check("partial input: task_id -> None", job2.checkpoint["task_id"] is None)
check("partial input: next_step -> None", job2.checkpoint["next_step"] is None)
check("partial input: data -> {}", job2.checkpoint["data"] == {})

# _job_to_response surfaces the checkpoint.
resp = main._job_to_response(job)
check("_job_to_response includes checkpoint",
      resp.checkpoint["task_id"] == "bib-tabs")
check("_job_to_response includes checkpoint_at", resp.checkpoint_at is not None)

# Request / list models.
rq = JobCheckpointRequest()
check("JobCheckpointRequest defaults",
      rq.task_id is None and rq.stage is None and rq.next_step is None
      and rq.data == {})
rq2 = JobCheckpointRequest(stage="s", data={"k": 1})
check("JobCheckpointRequest partial", rq2.stage == "s" and rq2.data == {"k": 1})
lst = JobListResponse(count=0, jobs=[])
check("JobListResponse model", lst.count == 0 and lst.jobs == [])

# ---------------------------------------------------------------------------
# Hydration / recovery simulation (the post-reboot resume story)
# ---------------------------------------------------------------------------

print("== hydration: running job with checkpoint -> interrupted, intact ==")

# Seed the fake durable index: a job that was RUNNING when the "host died",
# with a checkpoint written at the last stage boundary.
bib = Job(skill="media_pipeline", job_id="bibjob000001")
bib.status = JobStatus.running
bib.checkpoint = {
    "task_id": "back-in-black-tabs",
    "stage": "transcribing",
    "next_step": "resume from track 14",
    "data": {"done": 13, "total": 29},
    "updated_at": "2026-11-01T02:00:00+00:00",
}
bib.checkpoint_at = "2026-11-01T02:00:00+00:00"
main._persist_job(bib)
check("seed: running job in durable index",
      db.rows.get("bibjob000001", (None,))[0] == "running")

# And a corrupt row that must be skipped without breaking hydration.
db.rows["corrupt00001"] = ("running", "NOT-VALID-JSON{{{")

main._hydrate_jobs()
hydrated = main.jobs.get("bibjob000001")
check("hydrated job present", hydrated is not None)
check("hydrated job marked interrupted",
      hydrated is not None and hydrated.status == JobStatus.interrupted)
check("interrupted job got error message",
      hydrated is not None and hydrated.error == "Interrupted by runner restart")
check("interrupted job got completed_at",
      hydrated is not None and hydrated.completed_at is not None)
check("checkpoint SURVIVED hydration (the whole point)",
      hydrated is not None
      and hydrated.checkpoint is not None
      and hydrated.checkpoint["next_step"] == "resume from track 14"
      and hydrated.checkpoint["data"] == {"done": 13, "total": 29})
check("corrupt row skipped (not in store)", "corrupt00001" not in main.jobs)
check("corrupt row did not break hydration", hydrated is not None)
check("durable row updated to interrupted",
      db.rows.get("bibjob000001", (None,))[0] == "interrupted")

# ---------------------------------------------------------------------------
# HTTP: POST /skills/jobs/{job_id}/checkpoint
# ---------------------------------------------------------------------------

print("== POST /skills/jobs/{id}/checkpoint ==")

r = client.post("/skills/deep_research", json={"params": {"topic": "x"}, "dry_run": True})
check("launch dry-run job -> 200", r.status_code == 200, f"got {r.status_code}")
job_id = r.json()["job_id"]
check("dry-run job completed", r.json()["status"] == "completed")

r = client.post(f"/skills/jobs/{job_id}/checkpoint", json={
    "task_id": "research-2026-11-13",
    "stage": "writing",
    "next_step": "finish section 3",
    "data": {"sections_done": 2, "sections_total": 3},
})
check("checkpoint -> 200", r.status_code == 200, f"got {r.status_code}")
body = r.json()
check("response echoes checkpoint.task_id",
      body["checkpoint"]["task_id"] == "research-2026-11-13")
check("response echoes checkpoint.stage", body["checkpoint"]["stage"] == "writing")
check("response echoes checkpoint.next_step",
      body["checkpoint"]["next_step"] == "finish section 3")
check("response echoes checkpoint.data",
      body["checkpoint"]["data"] == {"sections_done": 2, "sections_total": 3})
check("response checkpoint_at set", body["checkpoint_at"] is not None)
check("status unchanged by checkpoint", body["status"] == "completed")

r = client.get(f"/skills/jobs/{job_id}")
check("GET /skills/jobs/{id} returns checkpoint",
      r.status_code == 200 and r.json()["checkpoint"]["task_id"] == "research-2026-11-13")
r = client.get(f"/api/jobs/{job_id}")
check("GET /api/jobs/{id} alias returns checkpoint",
      r.status_code == 200 and r.json()["checkpoint"]["stage"] == "writing")

r = client.post("/skills/jobs/doesnotexist01/checkpoint", json={"stage": "x"})
check("checkpoint on unknown job -> 404", r.status_code == 404, f"got {r.status_code}")

# Partial body via HTTP.
r = client.post(f"/skills/jobs/{job_id}/checkpoint", json={"stage": "reviewing"})
check("partial body -> 200", r.status_code == 200)
pb = r.json()["checkpoint"]
check("partial body: stage updated", pb["stage"] == "reviewing")
check("partial body: task_id -> None", pb["task_id"] is None)
check("partial body: data -> {}", pb["data"] == {})

# Free-form data preserved.
r = client.post(f"/skills/jobs/{job_id}/checkpoint", json={
    "stage": "reviewing",
    "data": {"offset": 42, "queue": ["a", "b"], "nested": {"x": 1}},
})
check("free-form data preserved",
      r.json()["checkpoint"]["data"] == {"offset": 42, "queue": ["a", "b"], "nested": {"x": 1}})

# Lenient on terminal jobs (a late checkpoint is harmless).
r = client.post(f"/skills/jobs/{job_id}/checkpoint", json={"stage": "final"})
check("checkpoint on completed job allowed (lenient)", r.status_code == 200,
      f"got {r.status_code}")

# ---------------------------------------------------------------------------
# HTTP: GET /api/jobs list endpoint
# ---------------------------------------------------------------------------

print("== GET /api/jobs list endpoint (durable-index path) ==")

r = client.get("/api/jobs")
check("list -> 200", r.status_code == 200, f"got {r.status_code}")
lst = r.json()
check("list payload {count, jobs}", "count" in lst and "jobs" in lst)
check("list count >= 2 (launched + hydrated)", lst["count"] >= 2, f"count={lst['count']}")
ids = [j["job_id"] for j in lst["jobs"]]
check("list includes launched job", job_id in ids)
check("list includes hydrated interrupted job", "bibjob000001" in ids)
check("list jobs carry checkpoint when set",
      any(j["job_id"] == job_id and j["checkpoint"]["stage"] == "final" for j in lst["jobs"]))

r = client.get("/api/jobs?status=completed")
check("list?status=completed -> 200", r.status_code == 200)
comp = r.json()
check("status filter: only completed",
      comp["count"] >= 1 and all(j["status"] == "completed" for j in comp["jobs"]))
check("status filter: launched job present",
      any(j["job_id"] == job_id for j in comp["jobs"]))

r = client.get("/api/jobs?status=interrupted")
check("list?status=interrupted -> 200 (recovery path)", r.status_code == 200)
intr = r.json()
check("recovery: interrupted job listed with checkpoint",
      intr["count"] >= 1
      and all(j["status"] == "interrupted" for j in intr["jobs"])
      and any(j["job_id"] == "bibjob000001"
              and j["checkpoint"]["next_step"] == "resume from track 14"
              for j in intr["jobs"]))

r = client.get("/api/jobs?status=bogus")
check("list?status=bogus -> 400", r.status_code == 400, f"got {r.status_code}")

r = client.get("/api/jobs?limit=0")
check("limit=0 clamped to 1 -> 200", r.status_code == 200 and r.json()["count"] <= 1)
r = client.get("/api/jobs?limit=1000")
check("limit=1000 clamped to 200 -> 200", r.status_code == 200)
r = client.get("/api/jobs?limit=-5")
check("negative limit clamped -> 200", r.status_code == 200)

# ---------------------------------------------------------------------------
# HTTP: GET /api/jobs in-memory fallback (DB down)
# ---------------------------------------------------------------------------

print("== GET /api/jobs in-memory fallback (DB down) ==")

main._JOBS_DB_AVAILABLE = False
r = client.get("/api/jobs")
check("DB-down list -> 200 (in-memory fallback)", r.status_code == 200,
      f"got {r.status_code}")
fallback = r.json()
check("fallback sees in-memory jobs",
      fallback["count"] >= 1 and any(j["job_id"] == job_id for j in fallback["jobs"]))
r = client.get("/api/jobs?status=interrupted")
check("DB-down status filter works in-memory",
      r.status_code == 200
      and any(j["job_id"] == "bibjob000001" for j in r.json()["jobs"]))

# ---------------------------------------------------------------------------

print(f"\n{PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failures:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)