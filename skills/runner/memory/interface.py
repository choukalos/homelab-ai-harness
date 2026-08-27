"""The ONLY public surface other code calls for long-term memory.

Every function is NON-FATAL: on error, timeout, or when disabled by config
it logs and returns a safe/degraded result (empty list / False / 0) instead
of raising into the chat path. This is the graceful-degradation
non-negotiable: memory must never take the assistant down.

Functions:
    search_memory(user_id, query, top_k=None) -> list[dict]
    learn_from_turn(user_id, messages, source="chat", agent_id=None, run_id=None)
        -> list[str]
    list_memories(user_id, limit=20) -> list[dict]
    update_memory(memory_id, text) -> bool
    delete_memory(memory_id) -> bool
    delete_user_memories(user_id) -> int
    is_healthy() -> bool

Search hits are dicts: ``{id, text, score, source, metadata}`` where
``source`` is ``"private"`` or ``"household"``.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from . import context as _context
from . import policy as _policy
from .client import MemoryClient, MemoryTimeout
from .config import MemoryConfig, load_config

logger = logging.getLogger("memory.interface")

# ── Singleton plumbing ────────────────────────────────────────────────
_cfg: Optional[MemoryConfig] = None
_client: Optional[MemoryClient] = None
_lock = threading.Lock()


def _get_config() -> MemoryConfig:
    global _cfg
    if _cfg is None:
        with _lock:
            if _cfg is None:
                _cfg = load_config()
    return _cfg


def _get_client() -> MemoryClient:
    global _client
    if _client is None:
        # Resolve the config OUTSIDE the lock: _get_config() acquires the
        # same non-reentrant _lock, so calling it from inside `with _lock:`
        # self-deadlocks the first caller in a process (e.g. is_healthy()
        # before any search/learn ran). Config load is pure/idempotent, so
        # concurrent double-compute is harmless.
        cfg = _get_config()
        with _lock:
            if _client is None:
                _client = MemoryClient(cfg)
    return _client


def _reset_singleton() -> None:
    """Test hook: drop the cached config + client."""
    global _cfg, _client
    with _lock:
        if _client is not None:
            _client.reset()
        _cfg = None
        _client = None


def _valid_user(user_id: Optional[str]) -> bool:
    """Reject empty/unknown principals (no retrieval or writeback for them)."""
    if not user_id:
        return False
    u = str(user_id).strip().lower()
    return u not in ("", "unknown", "service")


# ── Response-shape helpers (mem0 2.x varies these) ───────────────────
def _as_list(res: Any) -> List[dict]:
    if isinstance(res, dict):
        return res.get("results", res.get("memories", [])) or []
    if isinstance(res, list):
        return res
    return []


def _hit_text(hit: dict) -> str:
    return str(hit.get("memory", hit.get("text", "")) or "")


def _normalize_hit(hit: dict, source: str) -> Dict[str, Any]:
    return {
        "id": hit.get("id"),
        "text": _hit_text(hit),
        "score": float(hit.get("score", 0.0) or 0.0),
        "source": source,
        "metadata": hit.get("metadata", {}) or {},
    }


def _extract_ids(res: Any) -> List[str]:
    """Best-effort extraction of newly-added memory IDs from an add() result."""
    ids: List[str] = []
    for item in _as_list(res):
        mid = item.get("id")
        if mid:
            ids.append(str(mid))
    return ids


# ── Public API ────────────────────────────────────────────────────────
def search_memory(
    user_id: str,
    query: str,
    top_k: Optional[int] = None,
) -> List[dict]:
    """Search the user's private + household memories for ``query``.

    Returns a list of normalized hits (private + household merged, deduped,
    sorted by score desc, truncated to ``top_k``). Returns ``[]`` on error,
    timeout, or when retrieval is disabled / the user is unknown.
    """
    cfg = _get_config()
    if not cfg.retrieval_allowed:
        return []
    if not _valid_user(user_id) or not query or not str(query).strip():
        return []

    k = top_k or cfg.top_k
    client = _get_client()
    hits: List[dict] = []
    seen_ids = set()

    # Private memories.
    try:
        def _private_op():
            return client._ensure_client().search(
                query, filters={"user_id": user_id}, top_k=k
            )

        raw = client._with_timeout(_private_op)
        for h in _as_list(raw):
            nh = _normalize_hit(h, "private")
            if nh["id"] not in seen_ids:
                seen_ids.add(nh["id"])
                hits.append(nh)
    except (MemoryTimeout, Exception) as e:  # noqa: BLE001 - degrade
        logger.warning("memory search (private) failed for %s: %s", user_id, e)

    # Household memories (explicitly shared facts), if enabled.
    if cfg.household_enabled:
        try:
            def _household_op():
                return client._ensure_client().search(
                    query, filters={"user_id": cfg.household_user_id}, top_k=k
                )

            raw = client._with_timeout(_household_op)
            for h in _as_list(raw):
                nh = _normalize_hit(h, "household")
                if nh["id"] not in seen_ids:
                    seen_ids.add(nh["id"])
                    hits.append(nh)
        except (MemoryTimeout, Exception) as e:  # noqa: BLE001 - degrade
            logger.warning("memory search (household) failed: %s", e)

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:k]


def learn_from_turn(
    user_id: str,
    messages: List[dict],
    source: str = "chat",
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> List[str]:
    """Extract + store durable facts from a conversation turn.

    Runs the policy pre-filter (strip system/tool content, reject
    secret-like content) then calls mem0 ``add``. Returns the list of newly
    added memory IDs (best-effort; may be ``[]`` even on success if mem0's
    response shape omits IDs). Returns ``[]`` on error, timeout, or when
    writeback is disabled / the user is unknown / the turn is not storeable.
    """
    cfg = _get_config()
    if not cfg.writeback_allowed:
        return []
    if not _valid_user(user_id):
        return []

    ok, reason = _policy.should_store(messages)
    if not ok:
        if cfg.debug_logging:
            logger.debug("learn_from_turn skipped (%s): %s", user_id, reason)
        return []

    cleaned = _policy.sanitize_turn(messages)
    if not any(m["role"] == "user" for m in cleaned):
        return []

    client = _get_client()
    metadata = {"source": source}
    if agent_id:
        metadata["agent_id"] = agent_id
    if run_id:
        metadata["run_id"] = run_id

    def _add_op():
        return client._ensure_client().add(
            cleaned, user_id=user_id, metadata=metadata
        )

    try:
        res = client._with_timeout(
            _add_op, timeout_s=cfg.writeback_timeout_s
        )
        ids = _extract_ids(res)
        if cfg.debug_logging:
            logger.debug("learn_from_turn stored %d fact(s) for %s: %s",
                         len(ids), user_id, ids)
        return ids
    except MemoryTimeout as e:
        logger.warning("learn_from_turn timed out for %s: %s", user_id, e)
        return []
    except Exception as e:  # noqa: BLE001 - degrade
        logger.warning("learn_from_turn failed for %s: %s", user_id, e)
        return []


def list_memories(user_id: str, limit: int = 20) -> List[dict]:
    """List a user's stored memories (private + household if enabled).

    Returns normalized hits (score omitted/0). Returns ``[]`` on error or
    when the user is unknown.
    """
    cfg = _get_config()
    if not cfg.enabled or not _valid_user(user_id):
        return []
    client = _get_client()
    hits: List[dict] = []
    seen_ids = set()

    def _get_all_private():
        return client._ensure_client().get_all(
            filters={"user_id": user_id}, top_k=limit
        )

    try:
        raw = client._with_timeout(_get_all_private)
        for h in _as_list(raw):
            nh = _normalize_hit(h, "private")
            if nh["id"] not in seen_ids:
                seen_ids.add(nh["id"])
                hits.append(nh)
    except (MemoryTimeout, Exception) as e:  # noqa: BLE001 - degrade
        logger.warning("list_memories (private) failed for %s: %s", user_id, e)

    if cfg.household_enabled:
        def _get_all_household():
            return client._ensure_client().get_all(
                filters={"user_id": cfg.household_user_id}, top_k=limit
            )

        try:
            raw = client._with_timeout(_get_all_household)
            for h in _as_list(raw):
                nh = _normalize_hit(h, "household")
                if nh["id"] not in seen_ids:
                    seen_ids.add(nh["id"])
                    hits.append(nh)
        except (MemoryTimeout, Exception) as e:  # noqa: BLE001 - degrade
            logger.warning("list_memories (household) failed: %s", e)

    return hits[:limit]


def update_memory(memory_id: str, text: str) -> bool:
    """Update a memory's text. Returns False on error/timeout.

    Uses the admin budget (MEMORY_ADMIN_TIMEOUT_MS) — store ops, not the
    hot retrieval path (a single mem0 delete/update can take >1.5s).
    """
    cfg = _get_config()
    if not cfg.enabled or not memory_id or not text:
        return False
    client = _get_client()
    def _update_op():
        client._ensure_client().update(memory_id, text)

    try:
        client._with_timeout(_update_op, timeout_s=cfg.admin_timeout_s)
        return True
    except (MemoryTimeout, Exception) as e:  # noqa: BLE001 - degrade
        logger.warning("update_memory failed for %s: %s", memory_id, e)
        return False


def delete_memory(memory_id: str) -> bool:
    """Delete a single memory. Returns False on error/timeout.

    Uses the admin budget (MEMORY_ADMIN_TIMEOUT_MS): a single mem0 delete
    was measured at ~2.3s live — over the 1.5s retrieval budget, so the
    op would succeed in the background but the caller would get False.
    """
    cfg = _get_config()
    if not cfg.enabled or not memory_id:
        return False
    client = _get_client()
    def _delete_op():
        client._ensure_client().delete(memory_id)

    try:
        client._with_timeout(_delete_op, timeout_s=cfg.admin_timeout_s)
        return True
    except (MemoryTimeout, Exception) as e:  # noqa: BLE001 - degrade
        logger.warning("delete_memory failed for %s: %s", memory_id, e)
        return False


def delete_user_memories(user_id: str) -> int:
    """Delete ALL memories for a user. Returns count deleted (best-effort).

    The count reflects only this user's OWN (private) memories — the
    household view is excluded, so it matches what ``delete_all`` actually
    removes. (The merged ``list_memories`` view would over-count for
    non-household users whenever household facts exist: every user's list
    includes the household scope, but ``delete_all(user_id=...)`` only
    removes that user's own points.)

    Both the count and the delete use the admin budget
    (MEMORY_ADMIN_TIMEOUT_MS) — a cold-client get_all can exceed the 1.5s
    retrieval budget, which would degrade the count to 0.

    Returns 0 on error/timeout or when the user is unknown.
    """
    cfg = _get_config()
    if not cfg.enabled or not _valid_user(user_id):
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
        return count
    except (MemoryTimeout, Exception) as e:  # noqa: BLE001 - degrade
        logger.warning("delete_user_memories failed for %s: %s", user_id, e)
        return 0


def is_healthy() -> bool:
    """Return the memory backend health status (cached, cheap)."""
    try:
        return _get_client().is_healthy()
    except Exception:  # noqa: BLE001 - health must never raise
        return False


def render_context(user_id: str, query: str) -> str:
    """Convenience: search + render the ``<long_term_memory>`` block.

    Returns ``""`` when there is nothing to inject. Intended for the system
    prompt injection path (Phase 4).
    """
    cfg = _get_config()
    hits = search_memory(user_id, query)
    if not hits:
        return ""
    return _context.render_memory_block(hits, cfg)