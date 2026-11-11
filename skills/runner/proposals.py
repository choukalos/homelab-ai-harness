"""Harness-change proposal store (experience_improvement_todo.md Phase 3).

The ``proposals`` table in the ``homelab`` DB is the durable index for
``harness_reflection``'s change proposals. The reflection job (Tier 1 —
propose only) inserts ``open`` rows with evidence refs; Chuck reviews and
transitions them via ``cli/proposals.sh`` (admin-key API). Applying a
proposal (Tier 2) is always manual — nothing here ever applies changes.

Same conventions as ``sessions.py``: short-lived connections, idempotent
init, non-fatal degradation (DB down -> API routes return 503), and a
Prometheus exposition appended to ``/metrics``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("skill-runner.proposals")

_TABLE = "proposals"
_DB_AVAILABLE = False
_DB_LOCK = threading.Lock()

# Proposal lifecycle: open -> accepted|dismissed; accepted -> applied.
# dismissed/applied are terminal.
STATUSES = ("open", "accepted", "dismissed", "applied")
_TRANSITIONS = {
    "open": ("accepted", "dismissed"),
    "accepted": ("applied",),
    "dismissed": (),
    "applied": (),
}

_COLS = "id, slug, title, evidence, target_files, status, created_at, reviewed_at"


class ProposalError(RuntimeError):
    """Invalid proposal operation (unknown id, bad transition, DB down)."""


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


def init_db() -> None:
    """Initialise the proposals table (idempotent). Non-fatal on failure.

    The table was created ad-hoc on thor on 2026-11-08; this DDL matches
    the live schema exactly (verified via DESCRIBE) so fresh provisioning
    gets it from git.
    """
    global _DB_AVAILABLE
    try:
        with _DB_LOCK:
            conn = _db_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {_TABLE} (
                            id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                            slug         VARCHAR(192) NOT NULL,
                            title        VARCHAR(512) NOT NULL,
                            evidence     JSON NULL,
                            target_files JSON NULL,
                            status       VARCHAR(32) NOT NULL DEFAULT 'open',
                            created_at   VARCHAR(64) NOT NULL,
                            reviewed_at  VARCHAR(64) NULL,
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
            "Proposals index unavailable (MySQL %s: %s).",
            os.environ.get("AI_DB_NAME", "homelab"),
            exc,
        )


def available() -> bool:
    return _DB_AVAILABLE


def _json_decode(val: Any) -> Any:
    """Decode a JSON column (str/bytes -> object; dict/list pass through)."""
    if isinstance(val, (bytes, bytearray)):
        try:
            val = val.decode("utf-8")
        except UnicodeDecodeError:
            return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except (ValueError, TypeError):
            return val  # leave as-is; malformed JSON is surfaced to the caller
    return val


def _row_to_dict(row: tuple) -> Dict[str, Any]:
    """Map a SELECT row to an API dict (JSON columns decoded to objects).

    Handles both row shapes:
      8-tuple: (id, slug, title, evidence, target_files, status,
                created_at, reviewed_at) — the admin API SELECT
      7-tuple: (slug, title, evidence, target_files, status, created_at,
                reviewed_at) — the live row shape (the skill's dedup path
                + the live-shape regression test in
                skills/harness_reflection/test_skill.py)
    """
    if len(row) == 7:
        return {
            "id": None,
            "slug": row[0],
            "title": row[1],
            "evidence": _json_decode(row[2]),
            "target_files": _json_decode(row[3]),
            "status": row[4],
            "created_at": row[5],
            "reviewed_at": row[6],
        }
    return {
        "id": int(row[0]),
        "slug": row[1],
        "title": row[2],
        "evidence": _json_decode(row[3]),
        "target_files": _json_decode(row[4]),
        "status": row[5],
        "created_at": row[6],
        "reviewed_at": row[7],
    }


def list_proposals(status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List proposals, newest first. ``status`` filters (open/accepted/...)."""
    if not _DB_AVAILABLE:
        raise ProposalError("Proposals index unavailable (MySQL down)")
    if status is not None and status not in STATUSES:
        raise ProposalError(f"Unknown status '{status}' (valid: {', '.join(STATUSES)})")
    limit = max(1, min(int(limit), 200))
    sql = f"SELECT {_COLS} FROM {_TABLE}"
    args: list = []
    if status is not None:
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


def get_proposal(proposal_id: int) -> Dict[str, Any]:
    """Fetch one proposal by id. Raises ProposalError when missing."""
    if not _DB_AVAILABLE:
        raise ProposalError("Proposals index unavailable (MySQL down)")
    with _DB_LOCK:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT {_COLS} FROM {_TABLE} WHERE id = %s", (proposal_id,))
                row = cur.fetchone()
        finally:
            conn.close()
    if row is None:
        raise ProposalError(f"Proposal {proposal_id} not found")
    return _row_to_dict(row)


def insert(
    slug: str,
    title: str,
    evidence: Any,
    target_files: Any,
    status: str = "open",
    created_at: Optional[str] = None,
) -> bool:
    """Insert a proposal (idempotent on slug). Called by the
    ``harness_reflection`` job (Tier 1 — propose only).

    Idempotency: re-running with the same slug refreshes title/evidence/
    target_files but never changes ``status`` — a dismissed or applied
    proposal is never resurrected by a later run.
    """
    if not _DB_AVAILABLE:
        raise ProposalError("Proposals index unavailable (MySQL down)")
    if status not in STATUSES:
        raise ProposalError(f"Unknown status '{status}' (valid: {', '.join(STATUSES)})")
    slug = str(slug or "").strip()
    if not slug:
        raise ProposalError("slug is required")
    created = str(created_at or datetime.now(timezone.utc).isoformat())
    ev = json.dumps(evidence, ensure_ascii=False) if isinstance(evidence, (list, dict)) else evidence
    tf = json.dumps(target_files, ensure_ascii=False) if isinstance(target_files, (list, dict)) else target_files
    with _DB_LOCK:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_TABLE}
                        (slug, title, evidence, target_files, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        title = VALUES(title),
                        evidence = VALUES(evidence),
                        target_files = VALUES(target_files)
                    """,
                    (slug[:192], str(title)[:512], ev, tf, status, created),
                )
            conn.commit()
        finally:
            conn.close()
    return True


def transition(proposal_id: int, new_status: str) -> Dict[str, Any]:
    """Move a proposal to ``new_status`` (validates the lifecycle).

    Every transition stamps ``reviewed_at`` with the current UTC time.
    """
    if new_status not in STATUSES:
        raise ProposalError(f"Unknown status '{new_status}' (valid: {', '.join(STATUSES)})")
    if not _DB_AVAILABLE:
        raise ProposalError("Proposals index unavailable (MySQL down)")
    now = datetime.now(timezone.utc).isoformat()
    with _DB_LOCK:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id, status FROM {_TABLE} WHERE id = %s", (proposal_id,)
                )
                row = cur.fetchone()
                if row is None:
                    raise ProposalError(f"Proposal {proposal_id} not found")
                current = row[1]
                if new_status not in _TRANSITIONS.get(current, ()):
                    raise ProposalError(
                        f"Invalid transition {current} -> {new_status} "
                        f"(allowed from '{current}': "
                        f"{', '.join(_TRANSITIONS.get(current, ())) or 'none — terminal'})"
                    )
                cur.execute(
                    f"UPDATE {_TABLE} SET status = %s, reviewed_at = %s WHERE id = %s",
                    (new_status, now, proposal_id),
                )
            conn.commit()
        finally:
            conn.close()
    return get_proposal(proposal_id)


def count_by_status() -> Dict[str, int]:
    """Proposal counts per status (for the /metrics gauge)."""
    if not _DB_AVAILABLE:
        raise ProposalError("Proposals index unavailable (MySQL down)")
    with _DB_LOCK:
        conn = _db_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT status, COUNT(*) FROM {_TABLE} GROUP BY status")
                rows = cur.fetchall()
        finally:
            conn.close()
    return {status: int(n) for status, n in rows}


def exposition() -> str:
    """Render the proposals gauge (appended to /metrics). Best-effort."""
    try:
        if not _DB_AVAILABLE:
            return "# proposals_total unavailable (index down)\n"
        counts = count_by_status()
        lines = [
            "# HELP proposals_total Harness-change proposals by status.",
            "# TYPE proposals_total gauge",
        ]
        for status in STATUSES:
            lines.append(f'proposals_total{{status="{status}"}} {counts.get(status, 0)}')
        return "\n".join(lines) + "\n"
    except Exception:  # noqa: BLE001 - metrics must never raise
        return "# proposals_total unavailable\n"