#!/usr/bin/env python3
"""Endpoint tests for GET /api/sessions/ingests (user-scoped list) +
GET /api/sessions/{session_id} (owner-only read-back) — mcp_sessions Phase 1.

Same harness as test_sessions_endpoint.py: throwaway container built from
skills/runner/Dockerfile, FastAPI TestClient WITHOUT the lifespan, NO live
MySQL (the index degrades to file-only mode; the list routes assert 503,
auth is asserted before the DB is touched).

Covers (per the proposal):
  - auth: no key -> 401, unknown key -> 401, admin key NOT accepted -> 401
  - owner-only: another user's session -> 404 (existence not leaked);
    the owner gets 200
  - line-range slicing: 1-based inclusive, clamp, out-of-bounds -> 404,
    bad params -> 400
  - part concatenation: {sid}.part1/.part2 ingested via the API ->
    GET {sid} returns the concatenated stream, citation #p{N}L...
  - citation + sha256_prefix correctness (single and multi-part)
  - user-scoped list route: auth before DB (401/401/401), DB down -> 503
  - route matching: GET /api/sessions/ingests does NOT hit {session_id}

Run inside the container:
    python3 tests/test_sessions_get.py
"""
from __future__ import annotations

import hashlib
import os
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
os.environ["SESSIONS_DATA_ROOT"] = tempfile.mkdtemp(prefix="sessions-get-")
os.environ["MEMORY_ENABLED"] = "false"

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, RUNNER_ROOT)

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

L1 = '{"role":"user","content":"line one"}'
L2 = '{"role":"assistant","content":"line two"}'
L3 = '{"role":"user","content":"line three"}'
T3 = L1 + "\n" + L2 + "\n" + L3 + "\n"


def ingest(session_id: str, transcript: str, headers: dict, host: str = "mac") -> dict:
    return client.post(
        "/api/sessions/ingest",
        json={
            "host": host,
            "session_id": session_id,
            "started_at": "2026-11-21T10:00:00+00:00",
            "ended_at": "2026-11-21T11:00:00+00:00",
            "transcript": transcript,
        },
        headers=headers,
    ).json()


print("== seed data ==")
r = ingest("sess-get-1", T3, CHUCK)
check("chuck ingests sess-get-1", r.get("status") == "stored", str(r)[:200])
r = ingest("sess-get-2", T3, DYLAN)
check("dylan ingests sess-get-2", r.get("status") == "stored", str(r)[:200])
# Split session for chuck: two parts of 2 lines each (part2 reuses L2/L3)
r = ingest("sess-split.part1", L1 + "\n" + L2 + "\n", CHUCK)
check("chuck ingests sess-split.part1", r.get("status") == "stored", str(r)[:200])
r = ingest("sess-split.part2", L3 + "\n" + '{"role":"assistant","content":"line four"}\n', CHUCK)
check("chuck ingests sess-split.part2", r.get("status") == "stored", str(r)[:200])

print("== auth (read-back) ==")
r = client.get("/api/sessions/sess-get-1")
check("no key -> 401", r.status_code == 401, r.text[:120])
r = client.get("/api/sessions/sess-get-1", headers={"X-API-Key": "sk-not-a-real-key"})
check("unknown key -> 401", r.status_code == 401, r.text[:120])
r = client.get("/api/sessions/sess-get-1", headers=ADMIN)
check("admin key NOT accepted -> 401", r.status_code == 401, r.text[:120])

print("== owner-only ==")
r = client.get("/api/sessions/sess-get-1", headers=CHUCK)
check("owner GET -> 200", r.status_code == 200, r.text[:200])
j = r.json()
check("content is the verbatim transcript", j.get("content") == T3)
check("user_id scoped to caller", j.get("user_id") == "chuck")
check("total_lines = 3", j.get("total_lines") == 3)
check("citation single-part format",
      j.get("citation") == f"session:chuck/sess-get-1#L1-L3", str(j.get("citation")))
check("part = 0 for single file", j.get("part") == 0)
check("line_range full", j.get("line_range") == [1, 3])
check("sha256_prefix matches file sha (16 hex)",
      j.get("sha256_prefix") == hashlib.sha256(T3.encode("utf-8")).hexdigest()[:16])
check("bytes = utf-8 length of content", j.get("bytes") == len(T3.encode("utf-8")))
r = client.get("/api/sessions/sess-get-1", headers=DYLAN)
check("non-owner GET -> 404 (existence not leaked)", r.status_code == 404, r.text[:120])
r = client.get("/api/sessions/does-not-exist", headers=CHUCK)
check("missing session -> 404", r.status_code == 404, r.text[:120])

print("== line-range slicing ==")
r = client.get("/api/sessions/sess-get-1", params={"line_start": 2, "line_end": 2}, headers=CHUCK)
j = r.json()
check("slice L2..L2 -> 200", r.status_code == 200, r.text[:200])
check("slice content is exactly line 2", j.get("content") == L2 + "\n", repr(j.get("content")))
check("slice citation", j.get("citation") == "session:chuck/sess-get-1#L2-L2",
      str(j.get("citation")))
check("slice line_range", j.get("line_range") == [2, 2])
check("slice bytes", j.get("bytes") == len((L2 + "\n").encode("utf-8")))
r = client.get("/api/sessions/sess-get-1", params={"line_start": 1, "line_end": 99}, headers=CHUCK)
j = r.json()
check("line_end beyond end clamps to total",
      r.status_code == 200 and j.get("line_range") == [1, 3] and j.get("content") == T3)
r = client.get("/api/sessions/sess-get-1", params={"line_start": 4}, headers=CHUCK)
check("line_start past end -> 404", r.status_code == 404, r.text[:120])
r = client.get("/api/sessions/sess-get-1", params={"line_start": 0}, headers=CHUCK)
check("line_start < 1 -> 400", r.status_code == 400, r.text[:120])
r = client.get("/api/sessions/sess-get-1",
               params={"line_start": 3, "line_end": 2}, headers=CHUCK)
check("line_end < line_start -> 400", r.status_code == 400, r.text[:120])

print("== part concatenation ==")
r = client.get("/api/sessions/sess-split", headers=CHUCK)
j = r.json()
check("GET base id -> 200 (parts found)", r.status_code == 200, r.text[:200])
check("concatenated content = part1 + part2",
      j.get("content") == (L1 + "\n" + L2 + "\n" + L3 + "\n"
                           + '{"role":"assistant","content":"line four"}\n'),
      repr(j.get("content"))[:200])
check("total_lines = 4", j.get("total_lines") == 4)
check("citation multi-part format (#p1)",
      j.get("citation") == "session:chuck/sess-split#p1L1-L4", str(j.get("citation")))
check("part = 1 (first line in part1)", j.get("part") == 1)
# sha256_prefix must be part1's file hash
p1 = os.path.join(ROOT, "chuck", TODAY, "sess-split.part1.jsonl")
check("sha256_prefix = part1 file sha (16 hex)",
      j.get("sha256_prefix") == hashlib.sha256(open(p1, "rb").read()).hexdigest()[:16])
# Slice starting in part2
r = client.get("/api/sessions/sess-split", params={"line_start": 3, "line_end": 4}, headers=CHUCK)
j = r.json()
check("slice L3..L4 spans into part2",
      r.status_code == 200 and j.get("content") == L3 + "\n"
      + '{"role":"assistant","content":"line four"}\n', repr(j.get("content"))[:160])
check("slice citation cites the part holding the first line (#p2)",
      j.get("citation") == "session:chuck/sess-split#p2L3-L4", str(j.get("citation")))
check("slice part = 2", j.get("part") == 2)
# Part files are individually readable by their full session_id too
r = client.get("/api/sessions/sess-split.part1", headers=CHUCK)
check("GET partN id directly -> 200", r.status_code == 200, r.text[:160])
r = client.get("/api/sessions/sess-split", headers=DYLAN)
check("non-owner split session -> 404", r.status_code == 404, r.text[:120])

print("== validation ==")
r = client.get("/api/sessions/../evil", headers=CHUCK)
check("path-traversal session_id -> 400 (or 404 from routing)", r.status_code in (400, 404),
      r.text[:120])
r = client.get("/api/sessions/sess-get-1", params={"line_start": "abc"}, headers=CHUCK)
check("non-integer line_start -> 422 (FastAPI)", r.status_code == 422, r.text[:120])

print("== user-scoped list route ==")
r = client.get("/api/sessions/ingests")
check("no key -> 401", r.status_code == 401, r.text[:120])
r = client.get("/api/sessions/ingests", headers={"X-API-Key": "sk-not-a-real-key"})
check("unknown key -> 401", r.status_code == 401, r.text[:120])
r = client.get("/api/sessions/ingests", headers=ADMIN)
check("admin key NOT accepted -> 401", r.status_code == 401, r.text[:120])
r = client.get("/api/sessions/ingests", headers=CHUCK)
check("user key, DB down -> 503 (index unavailable)", r.status_code == 503, r.text[:120])
# Route matching: the literal /ingests path must not be swallowed by
# {session_id} (a 404 'Session not found' would prove it was).
r = client.get("/api/sessions/ingests", headers=CHUCK)
check("literal /ingests route wins over {session_id}",
      r.status_code == 503 and "index unavailable" in r.text.lower(), r.text[:120])

print("== read cap (SSE 1 MiB event limit) ==")
# 600 KB transcript: over the 512 KiB read cap, under the 2 MiB ingest cap
BIG_LINE = '{"role":"user","content":"' + "y" * 900 + '"}'
BIG = (BIG_LINE + "\n") * 600  # ~600 KB
r = ingest("sess-big-read", BIG, CHUCK)
check("chuck ingests 600 KB transcript", r.get("status") == "stored", str(r)[:200])
r = client.get("/api/sessions/sess-big-read", headers=CHUCK)
check("full read-back over cap -> 413 with paging hint",
      r.status_code == 413 and "narrow" in r.text and "total_lines" in r.text, r.text[:160])
r = client.get("/api/sessions/sess-big-read", params={"line_start": 1, "line_end": 100}, headers=CHUCK)
j = r.json()
check("narrow slice under cap -> 200",
      r.status_code == 200 and j.get("line_range") == [1, 100] and j.get("total_lines") == 600,
      r.text[:160])

print()
print(f"{'PASS' if FAIL == 0 else 'FAIL'}: {PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failed checks:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
