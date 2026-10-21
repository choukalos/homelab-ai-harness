#!/usr/bin/env python3
"""
memory_review skill — weekly memory review digest (trust + pruning).

Purpose:
  List the target user's NEW or UPDATED memories (private + household)
  from the last N days, with per-fact ID, date, source, and importance —
  so the user can review what the assistant has stored about them and
  correct or delete anything wrong before it compounds.

  This is the trust/pruning loop of the memory system (memory_todo 3d):
  extraction is LLM-driven and occasionally wrong; a periodic
  "here's what I've stored about you" digest catches errors early.

Workflow:
  1. Resolve the target user:
     - explicit `user` param -> must be a known personal user (from
       MEMORY_USER_KEYS); never service/unknown.
     - no param -> the job's own identity (interactive runs via the
       caller's key). Scheduled jobs carry the service identity, so
       scheduled runs MUST pass `user`.
  2. interface.list_memories(user, limit) — private + household merged
     (the user's own scopes only; never cross-user).
  3. Keep facts whose created_at or updated_at falls in the window
     (undated facts are kept — over-inclusion beats silently hiding).
  4. Render a markdown digest (per-scope sections, per-fact ID + date +
     source + importance) and save it as a PRIVATE artifact.
  5. Return summary + artifact_path + report.

Constraints:
  - Read-only w.r.t. memory: this skill never writes or deletes memories.
    Correction goes through "remember this: ..." (superseding fact) and
    deletion through the admin CLI / assistant, per the digest footer.
  - The artifact is PRIVATE (per-user dir under homelab_reports); it is
    never published to the public drop zone — it contains personal facts.
  - Max runtime: 120 seconds (list_memories is ~2.4s cold; no LLM).

See skill.yml for the full manifest.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("memory_review")

ARTIFACT_DIR = Path(
    os.environ.get(
        "MEMORY_REVIEW_ARTIFACT_DIR",
        "/home/chuck/data/media/homelab_reports/memory_review",
    )
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _known_users() -> list[str]:
    """All real users from the identity map (excludes 'service')."""
    users: list[str] = []
    for part in os.environ.get("MEMORY_USER_KEYS", "").split(","):
        part = part.strip()
        if "=" not in part:
            continue
        user = part.split("=", 1)[0].strip()
        if user and user != "service" and user not in users:
            users.append(user)
    return users


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (mem0 format). None on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _in_window(hit: dict, days: int, now: datetime) -> bool:
    """True when created_at or updated_at falls in the last `days` days.

    Undated facts (no parseable timestamp) are kept — a trust digest
    over-includes rather than silently hides a fact."""
    seen_ts = False
    for key in ("updated_at", "created_at"):
        ts = _parse_ts(hit.get(key))
        if ts is None:
            continue
        seen_ts = True
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if (now - ts) <= timedelta(days=days):
            return True
    return not seen_ts


def _fact_line(hit: dict) -> str:
    """Render one digest bullet: provenance + text + short ID."""
    date = str(hit.get("created_at") or "")[:10] or "undated"
    meta = hit.get("metadata") or {}
    src = str(meta.get("source") or "").strip()
    imp = str(meta.get("importance") or "").strip()
    written_by = str(meta.get("written_by") or "").strip()
    bits = [date]
    if src:
        bits.append(src)
    if imp == "high":
        bits.append("importance=high")
    if written_by:
        bits.append(f"written by {written_by}")
    mid = str(hit.get("id") or "")[:8]
    return (
        f"- [{' · '.join(bits)}] {str(hit.get('text', '')).strip()}\n"
        f"  `id: {mid}`"
    )


def render_digest(user: str, hits: list[dict], days: int,
                  now: datetime) -> str:
    """Pure markdown renderer (unit-testable without live services)."""
    window_start = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    total = len(hits)
    private = [h for h in hits if h.get("source") != "household"]
    household = [h for h in hits if h.get("source") == "household"]
    lines = [
        f"# Memory Review — {user} ({window_start} → "
        f"{now.strftime('%Y-%m-%d')})",
        "",
        f"Generated {now.strftime('%Y-%m-%d %H:%M')} UTC by the "
        f"`memory_review` job. {total} new/updated memor(y/ies) in the "
        f"last {days} day(s).",
        "",
    ]
    if total == 0:
        lines += [
            "Nothing new or updated this window — the store is unchanged.",
            "",
        ]
    for title, bucket in (
        ("Private", private),
        ("Household (family-shared)", household),
    ):
        lines.append(f"## {title} ({len(bucket)})")
        if not bucket:
            lines.append("_none_")
        for h in bucket:
            lines.append(_fact_line(h))
        lines.append("")
    lines += [
        "## How to correct or delete",
        "",
        '- **Correct**: tell the assistant "remember this: ..." (stores a',
        "  superseding fact) or \"forget that ...\" (targeted delete).",
        "- **Delete a specific fact**: `cli/memory-admin.sh delete <id>`",
        "  (admin key), or ask the assistant.",
        f"- This digest is private to **{user}**. Household facts are",
        "  visible to all family users.",
    ]
    return "\n".join(lines)


def run(params: dict, job: Any) -> dict:
    """Build the weekly memory review digest for one user."""
    days = max(1, min(int(params.get("days", 7) or 7), 31))
    limit = max(1, min(int(params.get("limit", 50) or 50), 200))
    now = _now()

    # 1. Resolve the target user (identity-safe, never cross-user).
    target = str(params.get("user") or "").strip().lower()
    job_user = str(getattr(job, "user_id", "") or "").strip().lower()
    if target:
        if target in ("service", "unknown"):
            return {"error": f"refusing to review non-personal user '{target}'"}
        known = _known_users()
        if known and target not in known:
            return {"error": f"unknown user '{target}' (known: {', '.join(known)})"}
        user = target
    elif job_user and job_user not in ("service", "unknown"):
        user = job_user  # interactive run under the caller's own identity
    else:
        return {
            "error": (
                "no target user: interactive runs use the caller's identity; "
                "scheduled runs must pass the 'user' param"
            )
        }

    # 2. Retrieve the user's own scopes (private + household merged).
    try:
        from memory import interface  # lazy: standalone-importable skill
    except Exception as exc:  # noqa: BLE001
        return {"error": f"memory package unavailable: {exc}"}

    try:
        hits = interface.list_memories(user, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"list_memories failed: {exc}"}

    # 3. Window filter, newest first.
    fresh = [h for h in hits if _in_window(h, days, now)]
    fresh.sort(
        key=lambda h: str(h.get("updated_at") or h.get("created_at") or ""),
        reverse=True,
    )

    # 4. Render + save the PRIVATE artifact (never published).
    md = render_digest(user, fresh, days, now)
    artifact_path = None
    try:
        d = ARTIFACT_DIR / user
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"memory_review_{now.strftime('%Y%m%d_%H%M')}.md"
        p.write_text(md)
        artifact_path = str(p)
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory_review: artifact write failed: %s", exc)

    n_priv = sum(1 for h in fresh if h.get("source") != "household")
    n_hh = len(fresh) - n_priv
    summary_line = (
        f"memory_review: {user} — {len(fresh)} new/updated in {days}d "
        f"(private {n_priv}, household {n_hh}); of {len(hits)} total stored"
    )
    logger.info(summary_line)
    return {
        "summary": summary_line,
        "artifact_path": artifact_path,
        "report": md,
    }