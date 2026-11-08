#!/usr/bin/env python3
"""Harness change proposals (Phase 3) — proposals table + gauge metrics.

The ``harness_reflection`` skill (Tier 1, PROPPOSE ONLY) stores each
harness change proposal as:

  - a markdown file ``proposals/YYYY-MM-DD-<slug>.md`` in the homelab repo
    (written by the skill itself; the repo is mounted read-only except
    for the ``proposals/`` subdir, so the kernel enforces the
    "no file outside proposals/ modified" rule), and
  - a row in the ``proposals`` MySQL table (homelab DB) — this module.

Statuses: ``open -> accepted | dismissed -> applied``. Transitions are
done by Chuck via ``cli/proposals.sh`` (or the admin REST endpoints in
``main.py``) — the reflection skill NEVER transitions a proposal, it only
creates ``open`` rows (propose-only, Tier 1; applying is Tier 2 and
requires a human).

Best-effort MySQL, following the durable job index / session_ingests
pattern in ``main.py`` / ``sessions.py``: if MySQL is unreachable the
module degrades to no-ops and never crashes the runner (the proposal
file on disk remains the source of truth).

Metrics: ``proposals_total{status}`` gauge in the dependency-free
Prometheus text format (appended to ``/metrics``). The gauge is
refreshed from the table at startup and after every in-process mutation
(the skill and the admin endpoints run in this same process).

Pure stdlib (pymysql imported lazily) so it is unit-testable on the host
without the runner's dependencies.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("skill_runner.proposals")

# ---------------------------------------------------------------------------
# MySQL index (proposals)
# ---------------------------------------------------------------------------
# Same connection pattern + env vars as the durable job index in main.py
# (MYSQL_DB_HOST / AI_DB_USER / AI_DB_PASS / AI_DB_NAME). The `ai` user has
# ALL PRIVILEGES on homelab.* so the table is auto-created if missing.
_TABLE = "proposals"
_DB_AVAILABLE = False
_DB_LOCK = threading.Lock()

# Status lifecycle (propose-only: the skill creates `open` rows; humans
# drive the rest via cli/proposals.sh / the admin endpoints).
STATUSES = ("open", "accepted", "dismissed", "applied")
# Allowed transitions (single-step; a proposal is never silently reopened).
_TRANSITIONS = {
    "open": ("accepted", "dismissed"),
    "accepted": ("applied",),
    # dismissed / applied are terminal
}

# slug goes into a file name (proposals/YYYY-MM-DD-<slug>.md) — safe
# kebab charset only. ``\Z`` (not ``$``) so a trailing newline can never
# sneak through.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}\Z")


class ProposalsUnavailable(RuntimeError):
    """The proposals MySQL index is unavailable (degraded mode)."""


def _db_conn():
    """Open a short-lived MySQL connection for the proposals index."""
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Initialise the proposals index (idempotent). Non-fatal on failure."""
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
                            slug        VARCHAR(192) NOT NULL,
                            title       VARCHAR(512) NOT NULL,
                            evidence    JSON,
                            target_files JSON,
                            status      VARCHAR(32) NOT NULL DEFAULT 'open',
                            created_at  VARCHAR(64) NOT NULL,
                            reviewed_at VARCHAR(64),
                            PRIMARY KEY (id),
                            UNIQUE KEY uq_slug (slug),
                            KEY idx_status (status)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                        """
                    )
                conn.commit()
            finally:
                conn.close()
        _DB_AVAILABLE = True
        logger.info(
            "Proposals index ready (MySQL %s.%s)",
            os.environ.get("AI_DB_NAME", "homelab"),
            _TABLE,
        )
    except Exception as exc:  # noqa: BLE001 - index must never break startup
        _DB_AVAILABLE = False
        logger.warning(
            "Proposals index unavailable (MySQL %s: %s); proposals are still "
            "written as files (file-only mode).",
            os.environ.get("AI_DB_NAME", "homelab"),
            exc,
        )
    # Seed the gauge from the table (best-effort; no-op when DB is down).
    refresh_counts()


def _row_to_dict(row: tuple) -> Dict[str, Any]:
    """(slug, title, evidence, target_files, status, created_at, reviewed_at) -> dict."""
    def _json(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, (str, bytes)):
            try:
                return json.loads(value)
            except Exception:  # noqa: BLE001 - keep raw string on bad JSON
                return value
        return value

    return {
        "slug": row[0],
        "title": row[1],
        "evidence": _json(row[2]),
        "target_files": _json(row[3]),
        "status": row[4],
        "created_at": row[5],
        "reviewed_at": row[6],
    }


def insert(
    slug: str,
    title: str,
    evidence: List[Any],
    target_files: List[str],
    status: str = "open",
    created_at: Optional[str] = None,
) -> bool:
    """Insert a proposal row (no-op when the index is unavailable).

    Idempotent on slug (INSERT IGNORE): the reflection skill dedups
    against open proposals before calling this, and a re-run on the same
    day must never create a second row for the same slug. Returns True
    when the row exists after the call (inserted or pre-existing),
    False on failure / unavailable index.
    """
    if not _DB_AVAILABLE:
        return False
    if not SLUG_RE.match(slug or ""):
        logger.warning("proposals.insert: refusing unsafe slug %r", slug)
        return False
    if status not in STATUSES:
        status = "open"
    try:
        with _DB_LOCK:
            conn = _db_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT IGNORE INTO {_TABLE}
                            (slug, title, evidence, target_files, status,
                             created_at, reviewed_at)
                        VALUES (%s, %s, %s, %s, %s, %s, NULL)
                        """,
                        (
                            slug,
                            title[:512],
                            json.dumps(evidence or [], default=str),
                            json.dumps(target_files or [], default=str),
                            status,
                            created_at or _now_iso(),
                        ),
                    )
                conn.commit()
            finally:
                conn.close()
        refresh_counts()
        return True
    except Exception as exc:  # noqa: BLE001 - indexing must never fail a proposal
        logger.warning("Failed to insert proposal %s: %s", slug, exc)
        return False


def list_proposals(status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List proposal rows, newest first. ``status`` filters (one of the 4).

    Named ``list_proposals`` (not ``list``) on purpose: a module-level
    ``def list`` shadows the builtin ``list`` in this module's globals,
    which breaks ``isinstance(value, (dict, list))`` inside
    ``_row_to_dict`` ("isinstance() arg 2 must be a type...") whenever a
    real row is converted. Same naming convention as sessions.list_ingests.

    Raises ProposalsUnavailable when MySQL is down (callers surface a
    503 / degrade to file-only).
    """
    if not _DB_AVAILABLE:
        raise ProposalsUnavailable("proposals index unavailable (MySQL)")
    limit = max(1, min(int(limit), 200))
    sql = (
        f"SELECT slug, title, evidence, target_files, status, created_at, "
        f"reviewed_at FROM {_TABLE}"
    )
    args: List[Any] = []
    if status:
        sql += " WHERE status = %s"
        args.append(status)
    sql += " ORDER BY created_at DESC, id DESC LIMIT %s"
    args.append(limit)
    with _DB_LOCK:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args)
                rows = cur.fetchall()
        finally:
            conn.close()
    return [_row_to_dict(r) for r in rows]


def get(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch one proposal by slug (None when missing or MySQL is down)."""
    if not _DB_AVAILABLE:
        return None
    if not SLUG_RE.match(slug or ""):
        return None
    with _DB_LOCK:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT slug, title, evidence, target_files, status,
                           created_at, reviewed_at
                    FROM {_TABLE} WHERE slug = %s LIMIT 1
                    """,
                    (slug,),
                )
                row = cur.fetchone()
        finally:
            conn.close()
    return _row_to_dict(row) if row else None


def transition(slug: str, new_status: str) -> Optional[Dict[str, Any]]:
    """Apply a status transition (human-driven, via CLI / admin endpoint).

    Allowed: open -> accepted | dismissed; accepted -> applied.
    Returns the updated row, or None when the slug is unknown, the
    transition is invalid (terminal / backwards), or MySQL is down.
    Sets ``reviewed_at`` on the transition.
    """
    if new_status not in STATUSES:
        return None
    row = get(slug)
    if row is None:
        return None
    if new_status not in _TRANSITIONS.get(row["status"], ()):
        logger.warning(
            "proposals.transition: %s -> %s not allowed (current status %s)",
            slug,
            new_status,
            row["status"],
        )
        return None
    with _DB_LOCK:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {_TABLE}
                    SET status = %s, reviewed_at = %s
                    WHERE slug = %s AND status = %s
                    """,
                    (new_status, _now_iso(), slug, row["status"]),
                )
                updated = cur.rowcount
            conn.commit()
        finally:
            conn.close()
    if not updated:
        return None
    refresh_counts()
    return get(slug)


# ---------------------------------------------------------------------------
# Metrics (dependency-free Prometheus text, like memory/metrics.py)
# ---------------------------------------------------------------------------

_gauge: Dict[str, float] = {}
_gauge_lock = threading.Lock()


def _set_gauge(counts: Dict[str, int]) -> None:
    with _gauge_lock:
        # Always carry all four status labels so the series is stable
        # for Grafana (a missing label would look like a scrape gap).
        for s in STATUSES:
            _gauge[s] = float(counts.get(s, 0))


def refresh_counts() -> Dict[str, int]:
    """Recompute the proposals_total{status} gauge from the table.

    Called at startup (init_db) and after every in-process mutation so
    /metrics stays accurate without a DB hit per Prometheus scrape.
    Keeps the previous gauge values when MySQL is down / the query fails.
    """
    counts: Dict[str, int] = {s: 0 for s in STATUSES}
    if not _DB_AVAILABLE:
        return counts
    try:
        with _DB_LOCK:
            conn = _db_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT status, COUNT(*) FROM {_TABLE} GROUP BY status"
                    )
                    rows = cur.fetchall()
            finally:
                conn.close()
        for status, n in rows:
            if status in counts:
                counts[status] = int(n)
    except Exception as exc:  # noqa: BLE001 - metrics must never raise
        logger.warning("proposals.refresh_counts failed: %s", exc)
        with _gauge_lock:
            return {s: int(v) for s, v in _gauge.items()}
    _set_gauge(counts)
    return counts


def counts() -> Dict[str, int]:
    """Current gauge values (int)."""
    with _gauge_lock:
        return {s: int(_gauge.get(s, 0)) for s in STATUSES}


def exposition() -> str:
    """Render the proposals metrics (appended to /metrics)."""
    try:
        lines = [
            "# HELP proposals_total Harness change proposals by status.",
            "# TYPE proposals_total gauge",
        ]
        for s in STATUSES:
            lines.append(f'proposals_total{{status="{s}"}} {counts().get(s, 0):g}')
        return "\n".join(lines) + "\n"
    except Exception:  # noqa: BLE001 - metrics must never raise
        return "# proposals metrics unavailable\n"


def reset_for_tests() -> None:
    """Test hook: drop the gauge + DB-availability flag."""
    global _DB_AVAILABLE
    with _gauge_lock:
        _gauge.clear()
    _DB_AVAILABLE = False