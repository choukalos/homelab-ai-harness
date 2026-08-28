"""Admin-oriented memory operations (Phase 8).

Backing for the admin REST endpoints. These are authorized by the admin API
key (checked in ``main.py``), so they deliberately BYPASS the
``_valid_user`` gate the chat-path functions use (which rejects
``service``/``unknown``). An admin is explicitly allowed to view and manage
ANY user's memories, including ``service`` and ``household``.

All functions are non-fatal and use the admin timeout budget
(``MEMORY_ADMIN_TIMEOUT_MS``).
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from . import metrics as _metrics
from .config import load_config
from .interface import _as_list, _get_client, _normalize_hit

logger = logging.getLogger("memory.admin")


def list_user(
    user_id: str,
    limit: int = 50,
    query: Optional[str] = None,
    scope: str = "all",
) -> List[dict]:
    """List (or search, if ``query`` is set) a user's memories.

    Bypasses the ``_valid_user`` gate (the admin key is the authorization
    boundary). ``scope`` selects which memories to include:
    ``"private"`` (the user's own), ``"household"``, or ``"all"`` (default).

    Returns normalized hits (``{id, text, score, source, metadata}``).
    On error/timeout, degrades to whatever scopes succeeded (possibly
    ``[]``).
    """
    cfg = load_config()
    if not cfg.enabled or not user_id:
        return []
    client = _get_client()
    t0 = time.monotonic()

    scopes: List[tuple] = []
    if scope in ("private", "all"):
        scopes.append(("private", user_id))
    if scope in ("household", "all") and cfg.household_enabled:
        scopes.append(("household", cfg.household_user_id))

    hits: List[dict] = []
    seen = set()
    degraded = False
    for label, uid in scopes:
        def _op(uid=uid, query=query):
            c = client._ensure_client()
            if query:
                return c.search(query, filters={"user_id": uid}, top_k=limit)
            return c.get_all(filters={"user_id": uid}, top_k=limit)
        try:
            raw = client._with_timeout(_op, timeout_s=cfg.admin_timeout_s)
            for h in _as_list(raw):
                nh = _normalize_hit(h, label)
                if nh["id"] not in seen:
                    seen.add(nh["id"])
                    hits.append(nh)
        except Exception as e:  # noqa: BLE001 - degrade per scope
            logger.warning("admin list (%s) failed for %s: %s", label, user_id, e)
            degraded = True
            _metrics.get_metrics().record_error("admin_list")

    if query:
        hits.sort(key=lambda h: h["score"], reverse=True)
    result = hits[:limit]
    _metrics.get_metrics().record_search(
        "degraded" if degraded else "ok", time.monotonic() - t0, len(result)
    )
    # Refresh the per-user gauge (private count only).
    private_count = sum(1 for h in result if h["source"] == "private")
    _metrics.get_metrics().set_user_count(user_id, private_count)
    return result


def update(memory_id: str, text: str) -> bool:
    """Update a memory's text (admin). Delegates to the interface."""
    from . import interface as _interface
    return _interface.update_memory(memory_id, text)


def delete(memory_id: str) -> bool:
    """Delete a single memory (admin). Delegates to the interface."""
    from . import interface as _interface
    return _interface.delete_memory(memory_id)


def delete_user(user_id: str) -> int:
    """Delete ALL private memories for a user (admin).

    Bypasses the ``_valid_user`` gate. Returns the count deleted
    (best-effort; 0 on error/timeout).
    """
    cfg = load_config()
    if not cfg.enabled or not user_id:
        return 0
    client = _get_client()
    try:
        def _count_op():
            return client._ensure_client().get_all(
                filters={"user_id": user_id}, top_k=1000
            )
        raw = client._with_timeout(_count_op, timeout_s=cfg.admin_timeout_s)
        count = len(_as_list(raw))

        def _delete_all_op():
            client._ensure_client().delete_all(user_id=user_id)
        client._with_timeout(_delete_all_op, timeout_s=cfg.admin_timeout_s)
        _metrics.get_metrics().set_user_count(user_id, 0)
        return count
    except Exception as e:  # noqa: BLE001 - degrade
        logger.warning("admin delete_user failed for %s: %s", user_id, e)
        _metrics.get_metrics().record_error("delete_user")
        return 0


def health() -> Dict:
    """Return memory service health + counters (for GET /api/memory/health)."""
    from . import interface as _interface
    cfg = load_config()
    m = _metrics.get_metrics()
    try:
        healthy = _interface.is_healthy()
    except Exception:  # noqa: BLE001
        healthy = False
    return {
        "healthy": healthy,
        "enabled": cfg.enabled,
        "retrieval_enabled": cfg.retrieval_enabled,
        "writeback_enabled": cfg.writeback_enabled,
        "household_enabled": cfg.household_enabled,
        "counters": {
            "search_total": _counter_dict(m.search_total),
            "writeback_total": _counter_dict(m.writeback_total),
            "errors_total": _counter_dict(m.errors_total),
            "search_hits_total": m.search_hits.value(),
            "writeback_stored_total": m.writeback_stored.value(),
        },
        "user_counts": _gauge_dict(m.user_count),
        "last_writeback_timestamp": m.last_writeback or None,
    }


def _counter_dict(c) -> Dict[str, float]:
    """Render a labelled counter as ``{label_value: count}``."""
    out: Dict[str, float] = {}
    for key, val in c.items():
        if key:
            # key is a sorted tuple of (name, value); use the value part
            out[key[0][1]] = val
        else:
            out["total"] = val
    return out


def _gauge_dict(g) -> Dict[str, float]:
    """Render a labelled gauge as ``{label_value: value}``."""
    out: Dict[str, float] = {}
    for key, val in g.items():
        if key:
            out[key[0][1]] = val
        else:
            out["total"] = val
    return out