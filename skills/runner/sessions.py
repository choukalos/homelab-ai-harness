#!/usr/bin/env python3
"""Session transcript ingest (Phase 2) — storage + index helpers.

Pi session transcripts (esp. from the Mac) are shipped here by the
``session-sync`` skill so the reflection pipeline sees them. This module
owns the storage policy; the FastAPI routes live in ``main.py``:

  - transcripts are stored under ``SESSIONS_ROOT/{user_id}/{YYYY-MM-DD}/
    {session_id}.jsonl`` on the sessions volume, mode 0600 (always private
    to the owning user — there is no household flag for transcripts)
  - the ``session_ingests`` MySQL table (homelab DB) is the index; it is
    best-effort, following the durable job index pattern in ``main.py`` —
    if MySQL is unreachable the runner degrades to file-only storage and
    never crashes
  - dedup: the same ``user_id + session_id + sha256`` is idempotent
    (re-sync -> duplicate)
  - metrics: ``sessions_ingested_total{user_id,status}`` in the
    dependency-free Prometheus text format (appended to ``/metrics``)

Pure stdlib (pymysql imported lazily, like the job index) so it is
unit-testable on the host without the runner's dependencies.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("skill_runner.sessions")

# Where transcripts land inside the container. The compose file mounts
# /home/chuck/data/skill-runner-sessions here (new volume, Phase 2).
SESSIONS_ROOT = Path(os.environ.get("SESSIONS_DATA_ROOT", "/data/sessions"))

# Hard cap on a single transcript (413 above this). 2 MB covers a full
# session jsonl; longer sessions are split (session_id.partN convention).
SESSION_TRANSCRIPT_MAX_BYTES = 2 * 1024 * 1024

# session_id goes into a file name — restrict to a safe charset (the
# split convention "session_id.partN" needs dots). ``\Z`` (not ``$``) so a
# trailing newline can never sneak through.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

# ---------------------------------------------------------------------------
# MySQL index (session_ingests)
# ---------------------------------------------------------------------------
# Same connection pattern + env vars as the durable job index in main.py
# (MYSQL_DB_HOST / AI_DB_USER / AI_DB_PASS / AI_DB_NAME). The `ai` user has
# ALL PRIVILEGES on homelab.* so the table is auto-created if missing.
_TABLE = "session_ingests"
_DB_AVAILABLE = False
_DB_LOCK = threading.Lock()


class SessionIndexUnavailable(RuntimeError):
    """The session_ingests MySQL index is unavailable (degraded mode)."""


def _db_conn():
    """Open a short-lived MySQL connection for the session index."""
    import pymysql  # lazy: main.py imports on the host without pymysql

    return pymysql.connect(
        host=os.environ.get("MYSQL_DB_HOST", "thor.local"),
        port=int(os.environ.get("MYSQL_DB_PORT", "3306")),
        user=os.environ.get("AI_DB_USER", ""),
        password=os.environ.get("AI_DB_PASS", ""),
        database=os.environ.get("AI_DB_NAME", "homelab"),
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )


def init_db() -> None:
    """Initialise the session index (idempotent). Non-fatal on failure."""
    global _DB_AVAILABLE
    try:
        with _DB_LOCK:
            conn = _db_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {_TABLE} (
                            id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                            user_id     VARCHAR(64) NOT NULL,
                            host        VARCHAR(128) NOT NULL,
                            session_id  VARCHAR(192) NOT NULL,
                            started_at  VARCHAR(64),
                            ended_at    VARCHAR(64),
                            sha256      CHAR(64) NOT NULL,
                            bytes       BIGINT UNSIGNED NOT NULL,
                            ingested_at VARCHAR(64) NOT NULL,
                            PRIMARY KEY (id),
                            UNIQUE KEY uq_ingest (user_id, session_id, sha256)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                        """
                    )
                conn.commit()
            finally:
                conn.close()
        _DB_AVAILABLE = True
        logger.info(
            "Session ingest index ready (MySQL %s.%s)",
            os.environ.get("AI_DB_NAME", "homelab"),
            _TABLE,
        )
    except Exception as exc:  # noqa: BLE001 - index must never break startup
        _DB_AVAILABLE = False
        logger.warning(
            "Session ingest index unavailable (MySQL %s: %s); transcripts are "
            "still stored on disk (file-only mode).",
            os.environ.get("AI_DB_NAME", "homelab"),
            exc,
        )


# ---------------------------------------------------------------------------
# Transcript files (source of truth)
# ---------------------------------------------------------------------------

def _transcript_path(user_id: str, session_id: str, day: Optional[str] = None) -> Path:
    """SESSIONS_ROOT/{user_id}/{YYYY-MM-DD}/{session_id}.jsonl (UTC day)."""
    if day is None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return SESSIONS_ROOT / user_id / day / f"{session_id}.jsonl"


def write_transcript(user_id: str, session_id: str, transcript: str) -> Tuple[Path, int]:
    """Write a transcript atomically at mode 0600. Returns (path, bytes).

    The temp file lives in the destination directory so the final
    ``os.replace`` is an atomic rename on the same filesystem.
    """
    dest = _transcript_path(user_id, session_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = transcript.encode("utf-8")
    tmp = dest.parent / f".{session_id}.jsonl.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)
    return dest, len(data)


def sha256_hex(data: bytes) -> str:
    """Hex sha256 of raw bytes (dedup key + integrity check)."""
    return hashlib.sha256(data).hexdigest()


def validate_session_id(session_id: str) -> bool:
    """session_id is part of a file name — safe charset only."""
    return bool(SESSION_ID_RE.match(session_id))


# ---------------------------------------------------------------------------
# Index operations (best-effort; the file is the source of truth)
# ---------------------------------------------------------------------------

def ingest_exists(user_id: str, session_id: str, sha256: str) -> bool:
    """Dedup check: same user_id + session_id + sha256 already ingested?

    A MySQL row is a fast positive signal; the on-disk file hash is always
    the final arbiter (it is also the only signal when MySQL is down or
    the row is missing, e.g. after a degraded-mode write).
    """
    if _DB_AVAILABLE:
        try:
            with _DB_LOCK:
                conn = _db_conn()
                try:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""
                            SELECT 1 FROM {_TABLE}
                            WHERE user_id = %s AND session_id = %s AND sha256 = %s
                            LIMIT 1
                            """,
                            (user_id, session_id, sha256),
                        )
                        if cur.fetchone() is not None:
                            return True
                finally:
                    conn.close()
        except Exception as exc:  # noqa: BLE001 - degrade to the disk check
            logger.warning(
                "session_ingests dedup check failed (%s); using disk fallback",
                exc,
            )
    try:
        dest = _transcript_path(user_id, session_id)
        if dest.is_file():
            return sha256_hex(dest.read_bytes()) == sha256
    except Exception:  # noqa: BLE001 - a read error means "not a duplicate"
        pass
    return False


def insert_ingest(
    user_id: str,
    host: str,
    session_id: str,
    started_at: Optional[str],
    ended_at: Optional[str],
    sha256: str,
    nbytes: int,
    ingested_at: str,
) -> None:
    """Index a stored transcript (no-op if the index is unavailable).

    The UNIQUE KEY (user_id, session_id, sha256) makes a concurrent
    duplicate insert a harmless IntegrityError.
    """
    if not _DB_AVAILABLE:
        return
    try:
        with _DB_LOCK:
            conn = _db_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {_TABLE}
                            (user_id, host, session_id, started_at, ended_at,
                             sha256, bytes, ingested_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            user_id,
                            host,
                            session_id,
                            started_at,
                            ended_at,
                            sha256,
                            nbytes,
                            ingested_at,
                        ),
                    )
                conn.commit()
            finally:
                conn.close()
    except Exception as exc:  # noqa: BLE001 - indexing must never fail a stored ingest
        logger.warning(
            "Failed to index session ingest %s/%s: %s", user_id, session_id, exc
        )


def list_ingests(
    user_id: str, since: Optional[str] = None, limit: int = 100
) -> List[Dict[str, Any]]:
    """Metadata rows for a user's ingests (no transcript bodies).

    ``since`` filters on ``ingested_at >= since`` (ISO-8601 UTC). Raises
    SessionIndexUnavailable when MySQL is down.
    """
    if not _DB_AVAILABLE:
        raise SessionIndexUnavailable("session index unavailable (MySQL)")
    limit = max(1, min(int(limit), 500))
    with _DB_LOCK:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                sql = (
                    f"SELECT id, user_id, host, session_id, started_at, ended_at, "
                    f"sha256, bytes, ingested_at FROM {_TABLE} WHERE user_id = %s"
                )
                args: List[Any] = [user_id]
                if since:
                    sql += " AND ingested_at >= %s"
                    args.append(since)
                sql += " ORDER BY ingested_at DESC LIMIT %s"
                args.append(limit)
                cur.execute(sql, args)
                rows = cur.fetchall()
        finally:
            conn.close()
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "host": row[2],
            "session_id": row[3],
            "started_at": row[4],
            "ended_at": row[5],
            "sha256": row[6],
            "bytes": row[7],
            "ingested_at": row[8],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Read-back (mcp_sessions Phase 1): locate + slice transcripts
# ---------------------------------------------------------------------------
# The ingest path stores {user_id}/{YYYY-MM-DD}/{session_id}.jsonl (UTC day of
# ingest) and, for split sessions, {session_id}.partN.jsonl (the session_id
# passed to ingest already carries the .partN suffix). Read-back therefore
# scans the user dirs; the day directory is an implementation detail.

def _part_number(filename: str, session_id: str) -> Optional[int]:
    """'{sid}.part3.jsonl' -> 3 for base session_id sid; None otherwise."""
    if not filename.endswith(".jsonl"):
        return None
    stem = filename[: -len(".jsonl")]
    prefix = f"{session_id}."
    if not stem.startswith(prefix):
        return None
    rest = stem[len(prefix):]
    if not rest.startswith("part") or not rest[4:].isdigit():
        return None
    return int(rest[4:])


def locate_transcript(
    session_id: str,
) -> Tuple[Optional[str], List[Tuple[int, Path]]]:
    """Find the stored transcript for session_id under SESSIONS_ROOT.

    Scans every user dir (SESSIONS_ROOT/*/). Returns ``(user_id, parts)``
    where parts is a list of ``(part_number, path)`` sorted by part number:

      - single-file transcript: ``[(0, path)]``  ({session_id}.jsonl)
      - split transcript:       ``[(1, p1), (2, p2), ...]`` ({session_id}.partN.jsonl)

    If BOTH a single file and part files exist, the parts win (the split
    convention is canonical for long sessions). Returns ``(None, [])`` when
    nothing is stored. The scan is bounded: user dirs hold one subdir per
    UTC day, each with a handful of files.
    """
    if not SESSIONS_ROOT.is_dir():
        return None, []
    found_user: Optional[str] = None
    single: Optional[Path] = None
    parts: Dict[int, Path] = {}
    for user_dir in sorted(SESSIONS_ROOT.iterdir()):
        if not user_dir.is_dir():
            continue
        for day_dir in user_dir.iterdir():
            if not day_dir.is_dir():
                continue
            for f in day_dir.iterdir():
                name = f.name
                if name.endswith(".jsonl"):
                    if name == f"{session_id}.jsonl":
                        single = f
                    else:
                        n = _part_number(name, session_id)
                        if n is not None:
                            parts[n] = f
        if single is not None or parts:
            found_user = user_dir.name
            break
    if parts:
        return found_user, [(n, parts[n]) for n in sorted(parts)]
    if single is not None:
        return found_user, [(0, single)]
    return None, []


def read_transcript(
    session_id: str,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Read a stored transcript, or a 1-based inclusive line slice of the
    concatenated part stream (parts concatenated in part order).

    Returns None when the session is not stored. Raises ValueError for
    invalid line params (line_start < 1, line_end < line_start) and when
    line_start is past the end of the transcript (the route maps that to
    404). ``line_end`` beyond the end is clamped to the total.

    Result keys:
      user_id            owning user dir
      parts              [(part, path, sha256, bytes)] in part order
      part               part containing the FIRST line of the returned
                         range (0 for a single-file transcript)
      line_range         [start, end] actually returned (1-based, inclusive)
      total_lines        lines in the concatenated transcript
      sha256_prefix      first 16 hex chars of the sha256 of the `part`
                         file (verifiable against the session_ingests row
                         for session_id / session_id.partN)
      content            the returned lines, verbatim (original line endings)
    """
    owner, parts = locate_transcript(session_id)
    if owner is None or not parts:
        return None
    if line_start is not None and int(line_start) < 1:
        raise ValueError("line_start must be >= 1")
    if line_end is not None and line_start is not None and int(line_end) < int(line_start):
        raise ValueError("line_end must be >= line_start")

    part_meta: List[Tuple[int, Path, str, int]] = []
    line_counts: List[Tuple[int, int]] = []  # (part, line count)
    all_lines: List[str] = []
    for part, path in parts:
        raw = path.read_bytes()
        lines = raw.decode("utf-8").splitlines(keepends=True)
        part_meta.append((part, path, sha256_hex(raw), len(raw)))
        line_counts.append((part, len(lines)))
        all_lines.extend(lines)
    total = len(all_lines)
    start = int(line_start) if line_start is not None else 1
    end = int(line_end) if line_end is not None else total
    if start > total:
        raise ValueError("line_start is past the end of the transcript")
    end = min(end, total)

    # Which part holds the first returned line (cumulative line counts)?
    first_part = line_counts[-1][0]
    offset = 0
    for part, n_lines in line_counts:
        if offset + n_lines >= start:
            first_part = part
            break
        offset += n_lines

    content = "".join(all_lines[start - 1 : end])
    return {
        "user_id": owner,
        "parts": [(p, path, sha, n) for p, path, sha, n in part_meta],
        "part": first_part,
        "line_range": [start, end],
        "total_lines": total,
        "sha256_prefix": next(
            sha for p, _path, sha, _n in part_meta if p == first_part
        )[:16],
        "content": content,
    }


# ---------------------------------------------------------------------------
# Metrics (dependency-free Prometheus text, like memory/metrics.py)
# ---------------------------------------------------------------------------

class _Counter:
    """A labelled counter (sorted label tuples as keys). Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._v: Dict[Tuple[Tuple[str, str], ...], float] = {}

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._v[key] = self._v.get(key, 0.0) + amount

    def items(self) -> List[Tuple[Tuple[Tuple[str, str], ...], float]]:
        with self._lock:
            return list(self._v.items())


_ingested_total = _Counter()  # labels: user_id, status


def record_ingest(user_id: str, status: str) -> None:
    """Record a session ingest (non-fatal — metrics must never raise)."""
    try:
        _ingested_total.inc(user_id=user_id, status=status)
    except Exception:  # noqa: BLE001
        pass


def exposition() -> str:
    """Render the session metrics (appended to /metrics)."""
    try:
        lines = [
            "# HELP sessions_ingested_total Total session ingests (by user and status).",
            "# TYPE sessions_ingested_total counter",
        ]
        items = _ingested_total.items()
        if not items:
            lines.append("sessions_ingested_total 0")
        for key, val in items:
            labels = (
                "{" + ",".join(f'{k}="{v}"' for k, v in key) + "}" if key else ""
            )
            lines.append(f"sessions_ingested_total{labels} {val:g}")
        return "\n".join(lines) + "\n"
    except Exception:  # noqa: BLE001 - metrics must never raise
        return "# session metrics unavailable\n"