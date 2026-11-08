#!/usr/bin/env python3
"""Unit tests for the session ingest module (Phase 2) — NO live services.

Covers:
  - session_id validation (safe charset, split convention, path traversal)
  - sha256 correctness
  - transcript file layout + 0600 mode + atomic overwrite
  - dedup: disk fallback (DB down) + MySQL path (fake connection)
  - index insert/list (fake connection): SQL args, since filter, limit clamp
  - init_db (fake connection): success + failure paths
  - metrics exposition (sessions_ingested_total{user_id,status})

Run with plain python3 (no pytest, no fastapi, no pymysql):
    python3 skills/runner/tests/test_sessions.py
"""
from __future__ import annotations

import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER_ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, RUNNER_ROOT)

import sessions  # noqa: E402

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
        return self.store.get("fetchone_row")

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


TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# ---------------------------------------------------------------------------
# session_id validation
# ---------------------------------------------------------------------------

print("== session_id validation ==")
for sid, want in [
    ("abc123", True),
    ("session-2026-11-08", True),
    ("sess.part2", True),          # split convention: session_id.partN
    ("a-b_c.d", True),
    ("A" * 128, True),
    ("0start", True),
    ("", False),
    (".hidden", False),            # leading dot: hidden-file / traversal-ish
    ("../etc", False),             # path traversal
    ("a b", False),                # space
    ("abc/def", False),            # slash
    ("A" * 129, False),            # too long
    ("abc\n", False),
]:
    check(f"{'accept' if want else 'reject'} {sid[:12]!r}{'…' if len(sid) > 12 else ''}",
          sessions.validate_session_id(sid) is want)

# ---------------------------------------------------------------------------
# sha256
# ---------------------------------------------------------------------------

print("== sha256 ==")
KNOWN = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
check("known vector (b'hello')", sessions.sha256_hex(b"hello") == KNOWN)
check("deterministic on utf-8 bytes",
      sessions.sha256_hex("héllo".encode("utf-8"))
      == sessions.sha256_hex("héllo".encode("utf-8")))

# ---------------------------------------------------------------------------
# transcript file layout + mode + atomic overwrite
# ---------------------------------------------------------------------------

print("== transcript file layout ==")
tmp_root = Path(tempfile.mkdtemp(prefix="sessions-unit-"))
sessions.SESSIONS_ROOT = tmp_root
sessions._DB_AVAILABLE = False

dest, nbytes = sessions.write_transcript("chuck", "sess-1", '{"a": 1}\n')
check("file at SESSIONS_ROOT/{user}/{YYYY-MM-DD}/{session_id}.jsonl",
      dest == tmp_root / "chuck" / TODAY / "sess-1.jsonl" and dest.is_file(),
      str(dest))
check("content round-trips", dest.read_text() == '{"a": 1}\n')
check("returns byte count", nbytes == len('{"a": 1}\n'.encode("utf-8")))
mode = stat.S_IMODE(dest.stat().st_mode)
check("file mode 0600", mode == 0o600, oct(mode))
check("no leftover temp file", not (dest.parent / ".sess-1.jsonl.tmp").exists())

dest2, nbytes2 = sessions.write_transcript("chuck", "sess-1", '{"a": 2}\n')
check("re-write (new sha) replaces file atomically",
      dest2 == dest and dest.read_text() == '{"a": 2}\n'
      and nbytes2 == len('{"a": 2}\n'.encode("utf-8")))

# ---------------------------------------------------------------------------
# dedup: disk fallback (DB down)
# ---------------------------------------------------------------------------

print("== dedup (disk fallback, DB down) ==")
sha_a = sessions.sha256_hex(b'{"a": 1}\n')
sha_b = sessions.sha256_hex(b'{"a": 2}\n')
check("ingest_exists False before write (fresh user)",
      sessions.ingest_exists("dylan", "sess-1", sha_a) is False)
check("ingest_exists True after write (same sha)",
      sessions.ingest_exists("chuck", "sess-1", sha_b) is True)
check("ingest_exists False for different sha",
      sessions.ingest_exists("chuck", "sess-1", sha_a) is False)

# ---------------------------------------------------------------------------
# dedup: MySQL path (fake connection)
# ---------------------------------------------------------------------------

print("== dedup (MySQL path, fake connection) ==")
store = _fresh_store(fetchone_row=(1,))
sessions._DB_AVAILABLE = True
sessions._db_conn = lambda: FakeConn(store)  # noqa: E731
check("ingest_exists True when DB row exists",
      sessions.ingest_exists("chuck", "sess-x", "sha-x") is True)
check("dedup SQL binds (user_id, session_id, sha256) on session_ingests",
      len(store["sqls"]) == 1
      and store["sqls"][0][1] == ("chuck", "sess-x", "sha-x")
      and "FROM session_ingests" in store["sqls"][0][0])
store2 = _fresh_store(fetchone_row=None)
sessions._db_conn = lambda: FakeConn(store2)  # noqa: E731
check("DB row missing falls back to disk check",
      sessions.ingest_exists("chuck", "sess-1", sha_b) is True)
check("DB row missing + no file -> False",
      sessions.ingest_exists("chuck", "sess-none", "sha-none") is False)
store3 = _fresh_store(execute_error=RuntimeError("db down mid-request"))
sessions._db_conn = lambda: FakeConn(store3)  # noqa: E731
check("DB error degrades to disk check (no raise)",
      sessions.ingest_exists("chuck", "sess-1", sha_b) is True)

# ---------------------------------------------------------------------------
# index insert (fake connection)
# ---------------------------------------------------------------------------

print("== index insert (fake connection) ==")
store = _fresh_store()
sessions._db_conn = lambda: FakeConn(store)  # noqa: E731
sessions.insert_ingest(
    "chuck", "mac", "sess-x",
    "2026-11-08T10:00:00+00:00", "2026-11-08T11:00:00+00:00",
    "sha-x", 123, "2026-11-08T11:01:00+00:00",
)
check("insert SQL targets session_ingests with all columns",
      len(store["sqls"]) == 1
      and "INSERT INTO session_ingests" in store["sqls"][0][0]
      and "sha256" in store["sqls"][0][0]
      and "ingested_at" in store["sqls"][0][0])
check("insert args in column order",
      store["sqls"][0][1]
      == ("chuck", "mac", "sess-x", "2026-11-08T10:00:00+00:00",
          "2026-11-08T11:00:00+00:00", "sha-x", 123, "2026-11-08T11:01:00+00:00"))
sessions._DB_AVAILABLE = False
try:
    sessions.insert_ingest("chuck", "mac", "sess-x", None, None, "sha-x", 1, "t")
    check("insert is a no-op when DB unavailable", True)
except Exception as exc:  # noqa: BLE001
    check("insert is a no-op when DB unavailable", False, repr(exc))

# ---------------------------------------------------------------------------
# list_ingests (fake connection)
# ---------------------------------------------------------------------------

print("== list_ingests (fake connection) ==")
rows = [
    (1, "chuck", "mac", "s1", "2026-11-08T10:00:00+00:00",
     "2026-11-08T11:00:00+00:00", "sha1", 100, "2026-11-08T11:01:00+00:00"),
]
store = _fresh_store(fetchall_rows=rows)
sessions._DB_AVAILABLE = True
sessions._db_conn = lambda: FakeConn(store)  # noqa: E731
out = sessions.list_ingests("chuck")
check("list returns metadata dicts (no transcript bodies)",
      out == [{
          "id": 1, "user_id": "chuck", "host": "mac", "session_id": "s1",
          "started_at": "2026-11-08T10:00:00+00:00",
          "ended_at": "2026-11-08T11:00:00+00:00",
          "sha256": "sha1", "bytes": 100,
          "ingested_at": "2026-11-08T11:01:00+00:00",
      }])
check("list SQL scoped to user_id with default limit",
      "WHERE user_id = %s" in store["sqls"][-1][0]
      and "ORDER BY ingested_at DESC" in store["sqls"][-1][0]
      and store["sqls"][-1][1] == ["chuck", 100])
store = _fresh_store(fetchall_rows=[])
sessions._db_conn = lambda: FakeConn(store)  # noqa: E731
sessions.list_ingests("chuck", since="2026-11-01T00:00:00+00:00", limit=10000)
check("since filter appended to SQL + args; limit clamped to 500",
      "AND ingested_at >= %s" in store["sqls"][-1][0]
      and store["sqls"][-1][1] == ["chuck", "2026-11-01T00:00:00+00:00", 500])
sessions.list_ingests("chuck", limit=0)
check("limit clamped up to 1", store["sqls"][-1][1] == ["chuck", 1])
sessions._DB_AVAILABLE = False
try:
    sessions.list_ingests("chuck")
    check("list raises SessionIndexUnavailable when DB down", False)
except sessions.SessionIndexUnavailable:
    check("list raises SessionIndexUnavailable when DB down", True)

# ---------------------------------------------------------------------------
# init_db (fake connection)
# ---------------------------------------------------------------------------

print("== init_db (fake connection) ==")
store = _fresh_store()
sessions._DB_AVAILABLE = False
sessions._db_conn = lambda: FakeConn(store)  # noqa: E731
sessions.init_db()
check("init_db runs idempotent DDL and marks available",
      sessions._DB_AVAILABLE is True
      and "CREATE TABLE IF NOT EXISTS session_ingests" in store["sqls"][0][0]
      and "UNIQUE KEY" in store["sqls"][0][0]
      and "sha256" in store["sqls"][0][0])
sessions._db_conn = _failing_conn
sessions._DB_AVAILABLE = True
sessions.init_db()
check("init_db failure leaves index unavailable (non-fatal)",
      sessions._DB_AVAILABLE is False)

# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

print("== metrics ==")
sessions.record_ingest("chuck", "stored")
sessions.record_ingest("chuck", "duplicate")
sessions.record_ingest("dylan", "stored")
expo = sessions.exposition()
check("exposition has HELP/TYPE lines",
      "# HELP sessions_ingested_total" in expo
      and "# TYPE sessions_ingested_total counter" in expo)
check("labelled rows present with correct counts (labels sorted, like memory/metrics.py)",
      'sessions_ingested_total{status="stored",user_id="chuck"} 1' in expo
      and 'sessions_ingested_total{status="duplicate",user_id="chuck"} 1' in expo
      and 'sessions_ingested_total{status="stored",user_id="dylan"} 1' in expo)

print()
print(f"{'PASS' if FAIL == 0 else 'FAIL'}: {PASS} passed, {FAIL} failed")
if FAILURES:
    print("Failed checks:")
    for name in FAILURES:
        print(f"  - {name}")
    sys.exit(1)
