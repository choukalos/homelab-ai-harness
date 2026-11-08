#!/usr/bin/env python3
"""Endpoint tests for POST /api/sessions/ingest + GET /api/sessions/{user_id}/ingests (Phase 2).

Runs in a throwaway container built from skills/runner/Dockerfile (needs
fastapi + httpx; NO live MySQL — the index degrades to file-only mode,
which is exactly the path exercised here). Uses FastAPI's TestClient
WITHOUT the lifespan (scheduler / DB init / memory warmup are not under
test; the sessions module defaults to DB-down, which the tests assert on).

Covers (per the Phase 2 contract):
  - auth: no key -> 401, unknown key -> 401, admin key NOT accepted -> 401
  - 200 stored: sha256 + bytes correctness, file on disk (0600, right path)
  - size cap: >2 MB -> 413, exactly 2 MB -> 200
  - dedup idempotency: same user+session+sha -> {status: "duplicate"}
  - per-user isolation: chuck's upload is not visible/writable under dylan
  - validation: bad session_id -> 400, missing host -> 400, empty transcript -> 400
  - admin route: user key / no key -> 403; admin key with DB down -> 503
  - /metrics exposes sessions_ingested_total{user_id,status}

Run inside the container:
    python3 tests/test_sessions_endpoint.py
"""
from __future__ import annotations

import hashlib
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone

# Env must be set BEFORE importing main (identity resolver + sessions read
# it at import / first use).
os.environ["SKILL_RUNNER_LOG_DIR"] = "/tmp/sr-test-logs"
os.environ["MEMORY_USER_KEYS"] = "chuck=KEY_CHUCK,dylan=KEY_DYLAN,service=KEY_SERVICE"
os.environ["KEY_CHUCK"] = "sk-test-chuck-key"
os.environ["KEY_DYLAN"] = "sk-test-dylan-key"
os.environ["KEY_SERVICE"] = "sk-test-service-key"
os.environ["MEMORY_ADMIN_API_KEY"] = "sk-test-admin-key"
os.environ["SESSIONS_DATA_ROOT"] = tempfile.mkdtemp(prefix="sessions-e2e-")
os.environ["MEMORY_ENABLED"] = "false"

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, RUNNER_ROOT)

import sessions  # noqa: E402
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


CHUCK = {"X-API-Key": "sk-test-chuck-key"}
DYLAN = {"X-API-Key": "sk-test-dylan-key"}
ADMIN = {"X-API-Key": "sk-test-admin-key"}
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
ROOT = os.environ["SESSIONS_DATA_ROOT"]

T1 = '{"role":"user","content":"hi"}\n{"role":"assistant","content":"hello"}\n'


def body(session_id: str, transcript: str = T1, host: str = "mac") -> dict:
    return {
        "host": host,
        "session_id": session_id,
        "started_at": "2026-11-08T10:00:00+00:00",
        "ended_at": "2026-11-08T11:00:00+00:00",
        "transcript": transcript,
    }


print("== auth ==")
r = client.post("/api/sessions/ingest", json=body("sess-auth"))
check("no key -> 401", r.status_code == 401, r.text[:120])
r = client.post("/api/sessions/ingest", json=body("sess-auth"),
                headers={"X-API-Key": "sk-not-a-real-key"})
check("unknown key -> 401", r.status_code == 401, r.text[:120])
r = client.post("/api/sessions/ingest", json=body("sess-auth"), headers=ADMIN)
check("admin key NOT accepted -> 401", r.status_code == 401, r.text[:120])

print("== 200 stored ==")
r = client.post("/api/sessions/ingest", json=body("sess-1"), headers=CHUCK)
check("chuck key -> 200 stored", r.status_code == 200 and r.json().get("status") == "stored",
      r.text[:200])
j = r.json()
check("sha256 matches transcript hash",
      j.get("sha256") == hashlib.sha256(T1.encode("utf-8")).hexdigest())
check("bytes matches utf-8 length", j.get("bytes") == len(T1.encode("utf-8")))
check("response scoped to caller", j.get("user_id") == "chuck")
fpath = os.path.join(ROOT, "chuck", TODAY, "sess-1.jsonl")
check("file at {root}/{user}/{YYYY-MM-DD}/{session_id}.jsonl", os.path.isfile(fpath), fpath)
check("file mode 0600",
      os.path.isfile(fpath) and stat.S_IMODE(os.stat(fpath).st_mode) == 0o600)
check("file content matches transcript",
      os.path.isfile(fpath) and open(fpath, encoding="utf-8").read() == T1)

print("== dedup idempotency ==")
r = client.post("/api/sessions/ingest", json=body("sess-1"), headers=CHUCK)
check("re-sync same content -> 200 duplicate",
      r.status_code == 200 and r.json().get("status") == "duplicate", r.text[:200])
r = client.post("/api/sessions/ingest", json=body("sess-1", T1 + '{"role":"user","content":"more"}\n'),
                headers=CHUCK)
check("same session_id, new content (new sha) -> stored",
      r.status_code == 200 and r.json().get("status") == "stored", r.text[:200])

print("== size cap ==")
r = client.post("/api/sessions/ingest",
                json=body("sess-big", "a" * (sessions.SESSION_TRANSCRIPT_MAX_BYTES + 1)),
                headers=CHUCK)
check("2 MB + 1 byte -> 413", r.status_code == 413, r.text[:120])
r = client.post("/api/sessions/ingest",
                json=body("sess-max", "a" * sessions.SESSION_TRANSCRIPT_MAX_BYTES),
                headers=CHUCK)
check("exactly 2 MB -> 200 stored", r.status_code == 200
      and r.json().get("status") == "stored", r.text[:120])

print("== per-user isolation ==")
T_D = '{"role":"user","content":"dylan transcript"}\n'
r = client.post("/api/sessions/ingest", json=body("sess-iso", T1), headers=CHUCK)
check("chuck stores sess-iso first",
      r.status_code == 200 and r.json().get("status") == "stored", r.text[:200])
r = client.post("/api/sessions/ingest", json=body("sess-iso", T_D), headers=DYLAN)
check("dylan stores same session_id independently",
      r.status_code == 200 and r.json().get("status") == "stored"
      and r.json().get("user_id") == "dylan", r.text[:200])
c_file = os.path.join(ROOT, "chuck", TODAY, "sess-iso.jsonl")
d_file = os.path.join(ROOT, "dylan", TODAY, "sess-iso.jsonl")
check("chuck's file untouched by dylan's upload",
      os.path.isfile(c_file)
      and open(c_file, encoding="utf-8").read() == T1
      and hashlib.sha256(open(c_file, "rb").read()).hexdigest()
      == hashlib.sha256(T1.encode("utf-8")).hexdigest())
check("dylan's file has dylan's content",
      os.path.isfile(d_file) and open(d_file, encoding="utf-8").read() == T_D)
r = client.post("/api/sessions/ingest", json=body("sess-iso", T1), headers=DYLAN)
check("chuck's content is NOT a duplicate for dylan (per-user dedup)",
      r.status_code == 200 and r.json().get("status") == "stored", r.text[:200])

print("== validation ==")
r = client.post("/api/sessions/ingest", json=body("../evil"), headers=CHUCK)
check("path-traversal session_id -> 400", r.status_code == 400, r.text[:120])
r = client.post("/api/sessions/ingest", json=body("sess-v", host=""), headers=CHUCK)
check("missing host -> 400", r.status_code == 400, r.text[:120])
r = client.post("/api/sessions/ingest", json=body("sess-v", transcript="   "), headers=CHUCK)
check("empty transcript -> 400", r.status_code == 400, r.text[:120])

print("== admin route ==")
r = client.get("/api/sessions/chuck/ingests")
check("no key -> 403", r.status_code == 403, r.text[:120])
r = client.get("/api/sessions/chuck/ingests", headers=CHUCK)
check("user key is not admin -> 403", r.status_code == 403, r.text[:120])
r = client.get("/api/sessions/chuck/ingests", headers=ADMIN)
check("admin key with DB down -> 503 (index unavailable)",
      r.status_code == 503, r.text[:120])

print("== /metrics ==")
r = client.get("/metrics")
check("/metrics exposes sessions_ingested_total",
      r.status_code == 200 and "sessions_ingested_total" in r.text)
check("per-user/status labels present",
      'sessions_ingested_total{status="stored",user_id="chuck"}' in r.text
      and 'sessions_ingested_total{status="duplicate",user_id="chuck"}' in r.text
      and 'sessions_ingested_total{status="stored",user_id="dylan"}' in r.text)
check("memory metrics still present", "memory_search_total" in r.text)

print()
print(f"{'PASS' if FAIL == 0 else 'FAIL'}: {PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failed checks:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
