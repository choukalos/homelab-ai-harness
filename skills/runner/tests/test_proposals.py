#!/usr/bin/env python3
"""Unit tests for the proposals module (Phase 3) — NO live services.

Covers:
  - init_db (fake connection): DDL issued, success + failure paths
  - list_proposals: SQL args (status filter, limit clamp), row mapping,
    JSON column decoding (str -> object, malformed left as-is)
  - get_proposal: not-found error, row mapping
  - transition: valid lifecycle (open->accepted|dismissed, accepted->applied),
    reviewed_at stamped, invalid transitions (open->applied, terminal states),
    unknown status, not-found
  - count_by_status + exposition (proposals_total{status} gauge, all 4
    statuses present even at zero)
  - DB down: every op raises ProposalError; exposition degrades gracefully

Run with plain python3 (no pytest, no fastapi, no pymysql):
    python3 skills/runner/tests/test_proposals.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, RUNNER_ROOT)

import proposals  # noqa: E402

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
# Fake MySQL connection (records SQL + args, returns canned rows)
# ---------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, store: dict):
        self.store = store

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args=None):
        self.store["sqls"].append((sql, args))
        if "execute_error" in self.store:
            raise self.store["execute_error"]

    def fetchone(self):
        rows = self.store.get("fetchone_rows")
        if not rows:
            return None
        return rows.pop(0)

    def fetchall(self):
        return self.store.get("fetchall_rows", [])


class FakeConn:
    def __init__(self, store: dict):
        self.store = store

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        pass

    def close(self):
        pass


def _fresh_store(**kwargs) -> dict:
    store = {"sqls": []}
    store.update(kwargs)
    return store


def _failing_conn():
    raise RuntimeError("MySQL unreachable")


ROW_OPEN = (
    1, "add-inflight-job-checkpoint", "Record resumable checkpoints for long-running jobs",
    '["memory:b243b2e2"]', '["docs/operations/job-checkpoints.md"]',
    "open", "2026-11-08T19:27:20.315366+00:00", None,
)
ROW_ACCEPTED = (
    2, "publish-file-subdirectory-enum-test", "Add regression test for publish_file subdirectory enum",
    '["git:bd2d2f32d502"]', '["skills/publish_file/SKILL.md"]',
    "accepted", "2026-11-08T19:33:53.740885+00:00", "2026-11-10T12:00:00+00:00",
)


def _with_status(row, status):
    """Copy a canned row with a different status (simulates the UPDATE)."""
    return row[:5] + (status,) + row[6:]

# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

print("== init_db ==")
store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
proposals._DB_AVAILABLE = False
proposals.init_db()
check("available after init", proposals.available() is True)
check("DDL issued", any("CREATE TABLE IF NOT EXISTS proposals" in s for s, _ in store["sqls"]))
check("DDL matches live schema", any(
    "UNIQUE KEY uq_slug (slug)" in s and "KEY idx_status (status)" in s
    for s, _ in store["sqls"]
))

store = _fresh_store(execute_error=RuntimeError("MySQL unreachable"))
proposals._db_conn = lambda: FakeConn(store)
proposals._DB_AVAILABLE = True
proposals.init_db()
check("unavailable after failed init", proposals.available() is False)

# ---------------------------------------------------------------------------
# list_proposals
# ---------------------------------------------------------------------------

print("== list_proposals ==")
proposals._DB_AVAILABLE = True
store = _fresh_store(fetchall_rows=[ROW_OPEN, ROW_ACCEPTED])
proposals._db_conn = lambda: FakeConn(store)
rows = proposals.list_proposals()
check("two rows mapped", len(rows) == 2)
check("status filter: no WHERE when omitted",
      all("WHERE" not in s for s, _ in store["sqls"]))
check("limit arg present", store["sqls"][0][1] == [50])
check("JSON columns decoded", rows[0]["evidence"] == ["memory:b243b2e2"]
      and rows[0]["target_files"] == ["docs/operations/job-checkpoints.md"])
check("reviewed_at passthrough", rows[1]["reviewed_at"] == "2026-11-10T12:00:00+00:00")

store = _fresh_store(fetchall_rows=[ROW_ACCEPTED])
proposals._db_conn = lambda: FakeConn(store)
rows = proposals.list_proposals(status="accepted")
sql, args = store["sqls"][0]
check("status filter in SQL", "WHERE status = %s" in sql and args[0] == "accepted")
check("limit clamp high", proposals.list_proposals(limit=5000) is not None
      and store["sqls"][-1][1][-1] == 200)
check("limit clamp low", proposals.list_proposals(limit=0) is not None
      and store["sqls"][-1][1][-1] == 1)

store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
try:
    proposals.list_proposals(status="bogus")
    check("bad status rejected", False)
except proposals.ProposalError as exc:
    check("bad status rejected", "Unknown status" in str(exc))

# ---------------------------------------------------------------------------
# get_proposal
# ---------------------------------------------------------------------------

print("== get_proposal ==")
store = _fresh_store(fetchone_rows=[ROW_OPEN])
proposals._db_conn = lambda: FakeConn(store)
row = proposals.get_proposal(1)
check("row mapped", row["id"] == 1 and row["slug"] == "add-inflight-job-checkpoint")
check("single-row SQL", "WHERE id = %s" in store["sqls"][0][0]
      and store["sqls"][0][1] == (1,))

store = _fresh_store(fetchone_rows=[None])
proposals._db_conn = lambda: FakeConn(store)
try:
    proposals.get_proposal(99)
    check("missing id raises", False)
except proposals.ProposalError as exc:
    check("missing id raises", "not found" in str(exc))

# ---------------------------------------------------------------------------
# transition
# ---------------------------------------------------------------------------

print("== transition ==")
# open -> accepted (fetchone: current status row, then get_proposal row)
store = _fresh_store(fetchone_rows=[(1, "open"), _with_status(ROW_OPEN, "accepted")])
proposals._db_conn = lambda: FakeConn(store)
out = proposals.transition(1, "accepted")
check("open->accepted ok", out["status"] == "accepted")
updates = [a for s, a in store["sqls"] if s.startswith("UPDATE")]
check("UPDATE stamps reviewed_at", len(updates) == 1 and updates[0][0] == "accepted"
      and updates[0][1] is not None and updates[0][2] == 1)

store = _fresh_store(fetchone_rows=[(1, "open"), _with_status(ROW_OPEN, "dismissed")])
proposals._db_conn = lambda: FakeConn(store)
proposals.transition(1, "dismissed")
updates = [a for s, a in store["sqls"] if s.startswith("UPDATE")]
check("open->dismissed ok", len(updates) == 1 and updates[0][0] == "dismissed")

store = _fresh_store(fetchone_rows=[(2, "accepted"), _with_status(ROW_ACCEPTED, "applied")])
proposals._db_conn = lambda: FakeConn(store)
out = proposals.transition(2, "applied")
check("accepted->applied ok", out["status"] == "applied")

for cur, new, label in [
    ("open", "applied", "open->applied"),
    ("dismissed", "applied", "dismissed->applied (terminal)"),
    ("applied", "open", "applied->open (terminal)"),
    ("accepted", "dismissed", "accepted->dismissed"),
]:
    store = _fresh_store(fetchone_rows=[(1, cur)])
    proposals._db_conn = lambda: FakeConn(store)
    try:
        proposals.transition(1, new)
        check(f"reject {label}", False)
    except proposals.ProposalError as exc:
        check(f"reject {label}", "Invalid transition" in str(exc))

store = _fresh_store(fetchone_rows=[(1, "open")])
proposals._db_conn = lambda: FakeConn(store)
try:
    proposals.transition(1, "bogus")
    check("reject unknown status", False)
except proposals.ProposalError as exc:
    check("reject unknown status", "Unknown status" in str(exc))

store = _fresh_store(fetchone_rows=[None])
proposals._db_conn = lambda: FakeConn(store)
try:
    proposals.transition(99, "accepted")
    check("reject missing id", False)
except proposals.ProposalError as exc:
    check("reject missing id", "not found" in str(exc))

# ---------------------------------------------------------------------------
# count_by_status + exposition
# ---------------------------------------------------------------------------

print("== count_by_status + exposition ==")
store = _fresh_store(fetchall_rows=[("open", 5), ("accepted", 2), ("applied", 1)])
proposals._db_conn = lambda: FakeConn(store)
counts = proposals.count_by_status()
check("counts mapped", counts == {"open": 5, "accepted": 2, "applied": 1})

text = proposals.exposition()
check("gauge HELP/TYPE present", "# HELP proposals_total" in text
      and "# TYPE proposals_total gauge" in text)
for status, n in [("open", 5), ("accepted", 2), ("dismissed", 0), ("applied", 1)]:
    check(f"gauge line {status}={n}", f'proposals_total{{status="{status}"}} {n}' in text)

# ---------------------------------------------------------------------------
# DB down
# ---------------------------------------------------------------------------

print("== DB down ==")
proposals._DB_AVAILABLE = False
for label, fn in [
    ("list", lambda: proposals.list_proposals()),
    ("get", lambda: proposals.get_proposal(1)),
    ("transition", lambda: proposals.transition(1, "accepted")),
    ("count", lambda: proposals.count_by_status()),
]:
    try:
        fn()
        check(f"{label} raises when DB down", False)
    except proposals.ProposalError:
        check(f"{label} raises when DB down", True)
check("exposition degrades", "unavailable" in proposals.exposition())

# ---------------------------------------------------------------------------

print(f"\n{PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failures:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)