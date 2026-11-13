#!/usr/bin/env python3
"""Unit tests for the proposals module (Phase 3) — NO live services.

Ported from branch mac-phase3-parallel (id-based API) to main's
slug-based API (thor's deployed version). Key API differences the port
had to follow:

  - rows are keyed by ``slug`` (str), not ``id`` (int); the row tuple is
    (slug, title, evidence, target_files, status, created_at, reviewed_at)
  - ``get(slug)`` / ``transition(slug, new_status)`` return None on
    missing / invalid instead of raising ``ProposalError``
  - ``list_proposals`` raises ``ProposalsUnavailable`` (not
    ``ProposalError``) only when the DB is down; it does NOT validate the
    status filter (the admin endpoint does)
  - ``count_by_status`` is gone: ``refresh_counts`` / ``counts`` (the
    gauge is in-process; ``refresh_counts`` returns zeros when the DB is
    down and never raises)
  - new: ``insert`` (INSERT IGNORE, slug charset enforced by SLUG_RE),
    ``reset_for_tests``

Covers:
  - init_db (fake connection): DDL issued, success + failure paths
  - insert: DB-down no-op, unsafe-slug refusal (no SQL), bad-status
    coercion to "open", INSERT IGNORE SQL + args (title truncated to 512,
    created_at default/passthrough), failure -> False, gauge refresh
  - list_proposals: SQL args (status filter, limit clamp), row mapping,
    JSON column decoding (str -> object, dict/list passthrough,
    malformed left as-is)
  - get: row mapping, None on missing slug, None on unsafe slug (no SQL),
    raises ProposalsUnavailable when DB down
  - transition: valid lifecycle (open->accepted|dismissed,
    accepted->applied), reviewed_at stamped, invalid transitions
    (open->applied, terminal states, backwards) -> None with no UPDATE,
    unknown status -> None, unknown slug -> None, lost UPDATE race
    (rowcount 0) -> None
  - refresh_counts + counts + exposition (proposals_total{status} gauge,
    all 4 statuses present even at zero)
  - DB down: list_proposals / get / transition raise ProposalsUnavailable
    (the admin endpoints surface 503 — a DB-down must not masquerade as
    404/409); insert returns False; refresh_counts returns zeros;
    exposition still renders the gauge (no "unavailable" marker)
  - reset_for_tests

Run with plain python3 (no pytest, no fastapi, no pymysql):
    python3 skills/runner/tests/test_proposals.py
"""
from __future__ import annotations

import json
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


def _raises(fn, exc_type) -> bool:
    try:
        fn()
    except exc_type:
        return True
    return False


# ---------------------------------------------------------------------------
# Fake MySQL connection (records SQL + args, returns canned rows)
# ---------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, store: dict):
        self.store = store
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, args=None):
        self.store["sqls"].append((sql, args))
        if "execute_error" in self.store:
            raise self.store["execute_error"]
        # transition() relies on the optimistic-concurrency rowcount.
        if sql.lstrip().upper().startswith("UPDATE"):
            self.rowcount = int(self.store.get("update_rowcount", 1))

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


# Canned rows: (slug, title, evidence, target_files, status, created_at,
# reviewed_at) — slug-first, no id column (main's schema).
ROW_OPEN = (
    "add-inflight-job-checkpoint",
    "Record resumable checkpoints for long-running jobs",
    '["memory:b243b2e2"]', '["docs/operations/job-checkpoints.md"]',
    "open", "2026-11-08T19:27:20.315366+00:00", None,
)
ROW_ACCEPTED = (
    "publish-file-subdirectory-enum-test",
    "Add regression test for publish_file subdirectory enum",
    '["git:bd2d2f32d502"]', '["skills/publish_file/SKILL.md"]',
    "accepted", "2026-11-08T19:33:53.740885+00:00", "2026-11-10T12:00:00+00:00",
)


def _with_status(row, status):
    """Copy a canned row with a different status (simulates the UPDATE)."""
    return row[:4] + (status,) + row[5:]


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

print("== init_db ==")
store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
proposals.reset_for_tests()
proposals.init_db()
check("available after init", proposals._DB_AVAILABLE is True)
check("DDL issued", any("CREATE TABLE IF NOT EXISTS proposals" in s for s, _ in store["sqls"]))
check("DDL matches live schema", any(
    "UNIQUE KEY uq_slug (slug)" in s and "KEY idx_status (status)" in s
    for s, _ in store["sqls"]
))
check("gauge seeded at init", any("SELECT status, COUNT(*)" in s for s, _ in store["sqls"]))

store = _fresh_store(execute_error=RuntimeError("MySQL unreachable"))
proposals._db_conn = lambda: FakeConn(store)
proposals._DB_AVAILABLE = True
proposals.init_db()
check("unavailable after failed init", proposals._DB_AVAILABLE is False)

# ---------------------------------------------------------------------------
# insert
# ---------------------------------------------------------------------------

print("== insert ==")
proposals.reset_for_tests()
check("insert no-op when DB down",
      proposals.insert("some-slug", "t", [], []) is False)

proposals._DB_AVAILABLE = True
store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
check("unsafe slug refused (no SQL)",
      proposals.insert("Bad Slug!", "t", [], []) is False and not store["sqls"])
check("uppercase slug refused (no SQL)",
      proposals.insert("UPPER", "t", [], []) is False and not store["sqls"])
check("trailing-newline slug refused",
      proposals.insert("ok-slug\n", "t", [], []) is False and not store["sqls"])

store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
ok = proposals.insert(
    "add-inflight-job-checkpoint", "Record resumable checkpoints",
    ["memory:b243b2e2"], ["docs/operations/job-checkpoints.md"],
)
sql, args = store["sqls"][0]
check("INSERT IGNORE issued",
      ok is True and sql.lstrip().startswith("INSERT IGNORE INTO proposals"))
check("insert args (slug/title/evidence/target_files/status)",
      args[0] == "add-inflight-job-checkpoint"
      and args[1] == "Record resumable checkpoints"
      and json.loads(args[2]) == ["memory:b243b2e2"]
      and json.loads(args[3]) == ["docs/operations/job-checkpoints.md"]
      and args[4] == "open")
check("created_at defaulted", args[5] is not None)

store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
proposals.insert("long-title-slug", "x" * 600, [], [])
check("title truncated to 512", store["sqls"][0][1][1] == "x" * 512)

store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
proposals.insert("bad-status-slug", "t", [], [], status="bogus")
check("bad status coerced to open", store["sqls"][0][1][4] == "open")

store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
proposals.insert("fixed-ts-slug", "t", [], [],
                 created_at="2026-11-08T00:00:00+00:00")
check("created_at passthrough", store["sqls"][0][1][5] == "2026-11-08T00:00:00+00:00")

store = _fresh_store(execute_error=RuntimeError("MySQL unreachable"))
proposals._db_conn = lambda: FakeConn(store)
check("insert failure -> False",
      proposals.insert("insert-fail-slug", "t", [], []) is False)

store = _fresh_store(fetchall_rows=[("open", 1)])
proposals._db_conn = lambda: FakeConn(store)
proposals.insert("post-insert-slug", "t", [], [])
check("gauge refreshed after insert", proposals.counts()["open"] == 1)

# ---------------------------------------------------------------------------
# list_proposals
# ---------------------------------------------------------------------------

print("== list_proposals ==")
proposals._DB_AVAILABLE = True
store = _fresh_store(fetchall_rows=[ROW_OPEN, ROW_ACCEPTED])
proposals._db_conn = lambda: FakeConn(store)
rows = proposals.list_proposals()
check("two rows mapped", len(rows) == 2)
check("slug key", rows[0]["slug"] == "add-inflight-job-checkpoint")
check("status filter: no WHERE when omitted",
      all("WHERE" not in s for s, _ in store["sqls"]))
check("limit arg present", store["sqls"][0][1] == [50])
check("JSON columns decoded", rows[0]["evidence"] == ["memory:b243b2e2"]
      and rows[0]["target_files"] == ["docs/operations/job-checkpoints.md"])
check("reviewed_at None passthrough", rows[0]["reviewed_at"] is None)
check("reviewed_at passthrough", rows[1]["reviewed_at"] == "2026-11-10T12:00:00+00:00")

store = _fresh_store(fetchall_rows=[
    ("dict-cols", "t", {"k": 1}, ["a.md"], "open",
     "2026-11-08T00:00:00+00:00", None),
])
proposals._db_conn = lambda: FakeConn(store)
rows = proposals.list_proposals()
check("dict/list JSON passthrough",
      rows[0]["evidence"] == {"k": 1} and rows[0]["target_files"] == ["a.md"])

store = _fresh_store(fetchall_rows=[
    ("bad-json", "t", "not-json", "also-not-json", "open",
     "2026-11-08T00:00:00+00:00", None),
])
proposals._db_conn = lambda: FakeConn(store)
rows = proposals.list_proposals()
check("malformed JSON left as-is",
      rows[0]["evidence"] == "not-json" and rows[0]["target_files"] == "also-not-json")

store = _fresh_store(fetchall_rows=[ROW_ACCEPTED])
proposals._db_conn = lambda: FakeConn(store)
rows = proposals.list_proposals(status="accepted")
sql, args = store["sqls"][0]
check("status filter in SQL", "WHERE status = %s" in sql and args[0] == "accepted")
check("limit clamp high", proposals.list_proposals(limit=5000) is not None
      and store["sqls"][-1][1][-1] == 200)
check("limit clamp low", proposals.list_proposals(limit=0) is not None
      and store["sqls"][-1][1][-1] == 1)

# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

print("== get ==")
store = _fresh_store(fetchone_rows=[ROW_OPEN])
proposals._db_conn = lambda: FakeConn(store)
row = proposals.get("add-inflight-job-checkpoint")
check("row mapped", row["slug"] == "add-inflight-job-checkpoint"
      and row["status"] == "open")
check("single-row SQL by slug", "WHERE slug = %s" in store["sqls"][0][0]
      and store["sqls"][0][1] == ("add-inflight-job-checkpoint",))

store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
check("missing slug -> None", proposals.get("does-not-exist") is None)

store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
check("unsafe slug -> None, no SQL",
      proposals.get("UPPER CASE") is None and not store["sqls"])

# ---------------------------------------------------------------------------
# transition
# ---------------------------------------------------------------------------

print("== transition ==")
# open -> accepted (fetchone: current row, then get() after the UPDATE)
store = _fresh_store(fetchone_rows=[ROW_OPEN, _with_status(ROW_OPEN, "accepted")])
proposals._db_conn = lambda: FakeConn(store)
out = proposals.transition("add-inflight-job-checkpoint", "accepted")
check("open->accepted ok", out["status"] == "accepted")
updates = [a for s, a in store["sqls"] if s.lstrip().startswith("UPDATE")]
check("UPDATE stamps reviewed_at (slug + current status in WHERE)",
      len(updates) == 1 and updates[0][0] == "accepted"
      and updates[0][1] is not None
      and updates[0][2] == "add-inflight-job-checkpoint"
      and updates[0][3] == "open")

store = _fresh_store(fetchone_rows=[ROW_OPEN, _with_status(ROW_OPEN, "dismissed")])
proposals._db_conn = lambda: FakeConn(store)
proposals.transition("add-inflight-job-checkpoint", "dismissed")
updates = [a for s, a in store["sqls"] if s.lstrip().startswith("UPDATE")]
check("open->dismissed ok", len(updates) == 1 and updates[0][0] == "dismissed")

store = _fresh_store(fetchone_rows=[ROW_ACCEPTED, _with_status(ROW_ACCEPTED, "applied")])
proposals._db_conn = lambda: FakeConn(store)
out = proposals.transition("publish-file-subdirectory-enum-test", "applied")
check("accepted->applied ok", out["status"] == "applied")

for cur, new, label in [
    ("open", "applied", "open->applied"),
    ("dismissed", "applied", "dismissed->applied (terminal)"),
    ("applied", "open", "applied->open (terminal)"),
    ("accepted", "dismissed", "accepted->dismissed"),
]:
    store = _fresh_store(fetchone_rows=[_with_status(ROW_OPEN, cur)])
    proposals._db_conn = lambda: FakeConn(store)
    out = proposals.transition("add-inflight-job-checkpoint", new)
    updates = [s for s, _ in store["sqls"] if s.lstrip().startswith("UPDATE")]
    check(f"reject {label} -> None, no UPDATE", out is None and not updates)

store = _fresh_store(fetchone_rows=[ROW_OPEN])
proposals._db_conn = lambda: FakeConn(store)
check("reject unknown status -> None",
      proposals.transition("add-inflight-job-checkpoint", "bogus") is None)

store = _fresh_store()
proposals._db_conn = lambda: FakeConn(store)
check("reject unknown slug -> None",
      proposals.transition("nope", "accepted") is None)

store = _fresh_store(fetchone_rows=[ROW_OPEN], update_rowcount=0)
proposals._db_conn = lambda: FakeConn(store)
check("lost UPDATE race (rowcount 0) -> None",
      proposals.transition("add-inflight-job-checkpoint", "accepted") is None)

# ---------------------------------------------------------------------------
# refresh_counts + counts + exposition
# ---------------------------------------------------------------------------

print("== refresh_counts + counts + exposition ==")
store = _fresh_store(fetchall_rows=[("open", 5), ("accepted", 2), ("applied", 1)])
proposals._db_conn = lambda: FakeConn(store)
counts = proposals.refresh_counts()
check("counts mapped",
      counts == {"open": 5, "accepted": 2, "dismissed": 0, "applied": 1})
check("counts() mirrors gauge", proposals.counts() == counts)

text = proposals.exposition()
check("gauge HELP/TYPE present",
      "# HELP proposals_total" in text and "# TYPE proposals_total gauge" in text)
for status, n in [("open", 5), ("accepted", 2), ("dismissed", 0), ("applied", 1)]:
    check(f"gauge line {status}={n}",
          f'proposals_total{{status="{status}"}} {n}' in text)

# ---------------------------------------------------------------------------
# DB down
# ---------------------------------------------------------------------------

print("== DB down ==")
proposals.reset_for_tests()
check("list raises ProposalsUnavailable",
      _raises(proposals.list_proposals, proposals.ProposalsUnavailable))
check("get raises ProposalsUnavailable",
      _raises(lambda: proposals.get("add-inflight-job-checkpoint"),
              proposals.ProposalsUnavailable))
check("transition raises ProposalsUnavailable",
      _raises(lambda: proposals.transition("add-inflight-job-checkpoint",
                                           "accepted"),
              proposals.ProposalsUnavailable))
check("insert returns False", proposals.insert("some-slug", "t", [], []) is False)
check("refresh_counts zeros",
      proposals.refresh_counts() == {s: 0 for s in proposals.STATUSES})
check("exposition still renders gauge (no unavailable marker)",
      'proposals_total{status="open"} 0' in proposals.exposition())

# ---------------------------------------------------------------------------
# reset_for_tests
# ---------------------------------------------------------------------------

print("== reset_for_tests ==")
store = _fresh_store(fetchall_rows=[("open", 3)])
proposals._db_conn = lambda: FakeConn(store)
proposals._DB_AVAILABLE = True
proposals.refresh_counts()
check("gauge seeded", proposals.counts()["open"] == 3)
proposals.reset_for_tests()
check("reset clears gauge",
      proposals.counts() == {s: 0 for s in proposals.STATUSES})
check("reset drops availability", proposals._DB_AVAILABLE is False)

# ---------------------------------------------------------------------------

print(f"\n{PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failures:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)