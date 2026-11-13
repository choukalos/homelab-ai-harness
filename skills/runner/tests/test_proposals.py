#!/usr/bin/env python3
"""Unit tests for the proposals module (Phase 3) — NO live services.

Covers:
  - init_db (fake connection): DDL issued, success + failure paths
  - insert: slug validation, status coercion, DB-down / DB-error no-ops
  - list_proposals: SQL args (status filter, limit clamp), row mapping,
    JSON column decoding (str -> object, malformed left as-is),
    DB down -> ProposalsUnavailable
  - get: row mapping, not-found -> None, unsafe slug -> None,
    DB down -> None (PINNED — degrades, does not raise)
  - transition: valid lifecycle (open->accepted|dismissed, accepted->applied),
    reviewed_at stamped, invalid transitions (open->applied, terminal states),
    unknown status, not-found -> None, UPDATE race (rowcount 0) -> None,
    DB down -> None (PINNED — degrades, does not raise)
  - counts + exposition (proposals_total{status} gauge, all 4 statuses
    present even at zero)
  - reset_for_tests: gauge cleared, flag dropped

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
        self.rowcount = store.get("rowcount", 1)

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


# (slug, title, evidence, target_files, status, created_at, reviewed_at)
ROW_OPEN = (
    "add-inflight-job-checkpoint", "Record resumable checkpoints for long-running jobs",
    '["memory:b243b2e2"]', '["docs/operations/job-checkpoints.md"]',
    "open", "2026-11-08T19:27:20.315366+00:00", None,
)
ROW_ACCEPTED = (
    "publish-file-subdirectory-enum-test", "Add regression test for publish_file subdirectory enum",
    '["git:bd2d2f32d502"]', '["skills/publish_file/SKILL.md"]',
    "accepted", "2026-11-08T19:33:53.740885+00:00", "2026-11-10T12:00:00+00:00",
)


def _with_status(row, status):
    """Copy a canned row with a different status (simulates the UPDATE)."""
    return row[:4] + (status,) + row[5:]


# ---------------------------------------------------------------------------
# reset_for_tests
# ---------------------------------------------------------------------------

print("== reset_for_tests ==")
proposals._DB_AVAILABLE = True
proposals._set_gauge({"open": 3, "accepted": 1, "dismissed": 0, "applied": 0})
proposals.reset_for_tests()
check("flag dropped", proposals.available() is False)
check("gauge cleared", proposals.counts() == {s: 0 for s in proposals.STATUSES})

# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

print("== init_db ==")
store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
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
# insert
# ---------------------------------------------------------------------------

print("== insert ==")
proposals.reset_for_tests()
store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
check("DB down: insert no-op False", proposals.insert("slug-x", "t", [], []) is False)
check("DB down: no SQL issued", store["sqls"] == [])

proposals._DB_AVAILABLE = True
store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
check("unsafe slug rejected", proposals.insert("UPPER CASE", "t", [], []) is False)
check("unsafe slug: no SQL issued", store["sqls"] == [])

store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
ok = proposals.insert("slug-x", "Title", ["memory:abc"], ["docs/x.md"])
check("insert ok -> True", ok is True)
sql, args = store["sqls"][0]
check("INSERT IGNORE on slug", "INSERT IGNORE" in sql and "uq_slug" not in sql
      and args[0] == "slug-x")
check("evidence/target_files JSON-encoded", args[2] == '["memory:abc"]'
      and args[3] == '["docs/x.md"]')
check("bad status coerced to open",
      proposals.insert("slug-y", "t", [], [], status="bogus") is True)
inserts = [a for s, a in store["sqls"] if "INSERT IGNORE" in s]
check("coerced status in SQL", len(inserts) == 2 and inserts[-1][4] == "open")

store = _fresh_store(execute_error=RuntimeError("MySQL unreachable"))
proposals._db_conn = lambda: FakeConn(store)
check("DB error: insert False, never raises",
      proposals.insert("slug-x", "t", [], []) is False)

# ---------------------------------------------------------------------------
# list_proposals
# ---------------------------------------------------------------------------

print("== list_proposals ==")
proposals.reset_for_tests()
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

proposals._DB_AVAILABLE = False
try:
    proposals.list_proposals()
    check("DB down: list raises ProposalsUnavailable", False)
except proposals.ProposalsUnavailable:
    check("DB down: list raises ProposalsUnavailable", True)

# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

print("== get ==")
proposals._DB_AVAILABLE = True
store = _fresh_store(fetchone_rows=[ROW_OPEN])
proposals._db_conn = lambda: FakeConn(store)
row = proposals.get("add-inflight-job-checkpoint")
check("row mapped", row["slug"] == "add-inflight-job-checkpoint"
      and row["status"] == "open")
check("slug-based SQL", "WHERE slug = %s" in store["sqls"][0][0]
      and store["sqls"][0][1] == ("add-inflight-job-checkpoint",))

store = _fresh_store(fetchone_rows=[None])
proposals._db_conn = lambda: FakeConn(store)
check("missing slug -> None", proposals.get("nope") is None)

store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
check("unsafe slug -> None, no SQL", proposals.get("UPPER CASE") is None
      and store["sqls"] == [])

proposals._DB_AVAILABLE = False
check("DB down: get -> None (pinned, no raise)", proposals.get("nope") is None)

# ---------------------------------------------------------------------------
# transition
# ---------------------------------------------------------------------------

print("== transition ==")
proposals._DB_AVAILABLE = True

# open -> accepted (fetchone: current row via get, then updated row via get)
_updated_accepted = ROW_OPEN[:4] + ("accepted", ROW_OPEN[5], "2026-11-12T00:00:00+00:00")
store = _fresh_store(fetchone_rows=[ROW_OPEN, _updated_accepted])
proposals._db_conn = lambda: FakeConn(store)
out = proposals.transition("add-inflight-job-checkpoint", "accepted")
check("open->accepted ok", out is not None and out["status"] == "accepted")
updates = [a for s, a in store["sqls"] if s.lstrip().startswith("UPDATE")]
check("UPDATE stamps reviewed_at + slug-qualified",
      len(updates) == 1 and updates[0][0] == "accepted"
      and updates[0][1] is not None
      and updates[0][2] == "add-inflight-job-checkpoint"
      and updates[0][3] == "open")
check("reviewed_at set on returned row", out["reviewed_at"] is not None)

store = _fresh_store(fetchone_rows=[ROW_OPEN, _with_status(ROW_OPEN, "dismissed")])
proposals._db_conn = lambda: FakeConn(store)
out = proposals.transition("add-inflight-job-checkpoint", "dismissed")
check("open->dismissed ok", out is not None and out["status"] == "dismissed")

store = _fresh_store(fetchone_rows=[ROW_ACCEPTED, _with_status(ROW_ACCEPTED, "applied")])
proposals._db_conn = lambda: FakeConn(store)
out = proposals.transition("publish-file-subdirectory-enum-test", "applied")
check("accepted->applied ok", out is not None and out["status"] == "applied")

for cur, new, label in [
    ("open", "applied", "open->applied"),
    ("dismissed", "applied", "dismissed->applied (terminal)"),
    ("applied", "open", "applied->open (terminal)"),
    ("accepted", "dismissed", "accepted->dismissed"),
]:
    store = _fresh_store(fetchone_rows=[_with_status(ROW_OPEN, cur)])
    proposals._db_conn = lambda: FakeConn(store)
    check(f"reject {label} -> None",
          proposals.transition("add-inflight-job-checkpoint", new) is None)

store = _fresh_store(fetchone_rows=[ROW_OPEN])
proposals._db_conn = lambda: FakeConn(store)
check("reject unknown status -> None",
      proposals.transition("add-inflight-job-checkpoint", "bogus") is None)

store = _fresh_store(fetchone_rows=[None])
proposals._db_conn = lambda: FakeConn(store)
check("missing slug -> None", proposals.transition("nope", "accepted") is None)

# Race: SELECT saw 'open' but the UPDATE matched 0 rows (status changed
# concurrently) -> None, no error.
store = _fresh_store(fetchone_rows=[ROW_OPEN, _with_status(ROW_OPEN, "accepted")],
                     rowcount=0)
proposals._db_conn = lambda: FakeConn(store)
check("UPDATE race (rowcount 0) -> None",
      proposals.transition("add-inflight-job-checkpoint", "accepted") is None)

proposals._DB_AVAILABLE = False
check("DB down: transition -> None (pinned, no raise)",
      proposals.transition("nope", "accepted") is None)

# ---------------------------------------------------------------------------
# counts + exposition
# ---------------------------------------------------------------------------

print("== counts + exposition ==")
proposals.reset_for_tests()
proposals._DB_AVAILABLE = True
store = _fresh_store(fetchall_rows=[("open", 5), ("accepted", 2), ("applied", 1)])
proposals._db_conn = lambda: FakeConn(store)
counts = proposals.refresh_counts()
check("counts mapped", counts == {"open": 5, "accepted": 2, "dismissed": 0,
                                  "applied": 1})

text = proposals.exposition()
check("gauge HELP/TYPE present", "# HELP proposals_total" in text
      and "# TYPE proposals_total gauge" in text)
for status, n in [("open", 5), ("accepted", 2), ("dismissed", 0), ("applied", 1)]:
    check(f"gauge line {status}={n}", f'proposals_total{{status="{status}"}} {n}' in text)

# DB down: refresh_counts returns zeros, exposition still renders (zero
# counts — the gauge keeps its last values, zeros on a fresh process).
proposals.reset_for_tests()
check("DB down: refresh_counts zeros",
      proposals.refresh_counts() == {s: 0 for s in proposals.STATUSES})
check("DB down: exposition still renders", "# TYPE proposals_total gauge"
      in proposals.exposition())

# ---------------------------------------------------------------------------

print(f"\n{PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failures:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)