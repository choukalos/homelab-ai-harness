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

Search hits are dicts: ``{id, text, score, source, metadata, created_at,
updated_at, raw_score, rank_score}`` where ``source`` is ``"private"`` or
``"household"``, ``score`` is the raw cosine similarity, and
``rank_score`` = raw score x recency boost x importance boost (memory_todo
3a/3e) — the value hits are ranked by.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import context as _context
from . import policy as _policy
from . import metrics as _metrics
from .client import MemoryClient, MemoryTimeout
from .config import MemoryConfig, load_config

logger = logging.getLogger("memory.interface")

# ── Singleton plumbing ────────────────────────────────────────────────
_cfg: Optional[MemoryConfig] = None
_client: Optional[MemoryClient] = None
_lock = threading.Lock()

# ── Search status side-channel (cold-start / degradation flag) ────────
# ``search_memory`` keeps returning a plain list (non-breaking for the
# chat path), but every call updates ``LAST_SEARCH`` so the REST/MCP
# surfaces can surface a "degraded — retry" signal. This matters most
# for COLD START: the first search after process start can hit the
# retrieval timeout while Qdrant/embedding init runs, and an empty
# result then means "transient — retry once", not "no memories".
LAST_SEARCH: Dict[str, Any] = {"degraded": False, "reason": "", "retry": False}
_first_search_done = False


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
    global _cfg, _client, _first_search_done
    with _lock:
        if _client is not None:
            _client.reset()
        _cfg = None
        _client = None
        _first_search_done = False


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
        # mem0 2.0.19 get_all hits carry created_at/updated_at at the TOP
        # LEVEL (not in metadata) — carry them through so callers (sweep
        # lookback, introspection) can filter by age.
        "created_at": hit.get("created_at"),
        "updated_at": hit.get("updated_at"),
    }


def _extract_ids(res: Any) -> List[str]:
    """Best-effort extraction of newly-added memory IDs from an add() result."""
    ids: List[str] = []
    for item in _as_list(res):
        mid = item.get("id")
        if mid:
            ids.append(str(mid))
    return ids


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (mem0 format). ``None`` on failure."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _rank_score(hit: dict, cfg: MemoryConfig, now: Optional[datetime] = None) -> float:
    """Rank score = raw score x recency boost x importance boost (3a/3e).

    The relevance gate (``cfg.score_threshold``) is applied to the RAW
    score before this runs, so a boost can only reorder hits that already
    cleared the gate — it can never admit an irrelevant fact.

    - recency: ``1 + (max-1) * 0.5**(age_days / half_life)`` on
      ``updated_at`` (fallback ``created_at``). A just-updated fact gets
      the full boost; it decays to half at one half-life, so volatile
      topics (medical status, appointments) outrank months-old
      equivalents while stable facts are barely affected.
    - importance: flat multiplier for ``importance=high`` facts.
    """
    score = float(hit.get("score", 0.0) or 0.0)
    if score <= 0.0:
        return score
    boosted = score
    if cfg.recency_boost_max > 1.0:
        ts = _parse_ts(hit.get("updated_at")) or _parse_ts(hit.get("created_at"))
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            now = now or datetime.now(timezone.utc)
            age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
            half = cfg.recency_half_life_days if cfg.recency_half_life_days > 0 else 30.0
            boosted *= 1.0 + (cfg.recency_boost_max - 1.0) * (0.5 ** (age_days / half))
    if (hit.get("metadata") or {}).get("importance") == "high":
        if cfg.importance_boost > 1.0:
            boosted *= cfg.importance_boost
    return boosted


# ── Multi-query retrieval (memory_todo 3b) ────────────────────────────
# Sentence-initial / function words that must not be treated as entities.
_SUBQUERY_STOPWORDS = frozenset({
    "the", "a", "an", "what", "when", "where", "which", "who", "whom",
    "why", "how", "did", "does", "do", "is", "are", "was", "were", "have",
    "has", "had", "i", "you", "he", "she", "it", "we", "they", "my",
    "your", "his", "her", "its", "our", "their", "this", "that", "these",
    "those", "there", "here", "and", "or", "but", "if", "then", "than",
    "so", "not", "no", "yes", "please", "can", "could", "would",
    "should", "will", "about", "for", "with", "from", "to", "of", "in",
    "on", "at", "by",
})


def _derive_subqueries(query: str, max_total: int) -> List[str]:
    """Heuristic subqueries for multi-query retrieval (memory_todo 3b).

    Deterministic, no LLM call: extracts quoted phrases ("..." / '...')
    and capitalized entity sequences (2+ consecutive capitalized words,
    or a single capitalized word of length >= 4). Returns up to
    ``max_total - 1`` subqueries, each distinct from the original query
    (case-insensitive) and from each other, at most 5 words each.
    ``[]`` when the query has fewer than 3 words (short queries don't
    benefit) or nothing qualifies.
    """
    max_total = max(2, int(max_total))
    q = (query or "").strip()
    words = q.split()
    if len(words) < 3:
        return []
    candidates: List[str] = []
    # 1) Quoted phrases.
    for m in re.finditer(r'"([^"\n]{3,60})"|\'([^\'\n]{3,60})\'', q):
        phrase = (m.group(1) or m.group(2) or "").strip()
        if phrase:
            candidates.append(phrase)
    # 2) Capitalized entity sequences.
    caps = [
        i for i, w in enumerate(words)
        if len(w) >= 3 and w[0].isupper()
        and w.lower() not in _SUBQUERY_STOPWORDS
    ]
    i = 0
    while i < len(caps):
        j = i
        while j + 1 < len(caps) and caps[j + 1] == caps[j] + 1:
            j += 1
        span = caps[i:j + 1]
        if len(span) >= 2:
            candidates.append(" ".join(words[k] for k in span))
        elif len(words[span[0]]) >= 4:
            candidates.append(words[span[0]])
        i = j + 1
    # Dedup (case-insensitive), drop the original query, cap at max_total-1.
    out: List[str] = []
    seen = {q.lower()}
    for c in candidates:
        key = c.lower()
        if key in seen or len(c.split()) > 5:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= max_total - 1:
            break
    return out


def _merge_rrf(per_query_hits: List[List[dict]], k: int = 60) -> List[dict]:
    """Reciprocal rank fusion over multiple ranked hit lists (memory_todo 3b).

    ``score`` on merged hits = the BEST raw cosine seen for that id across
    queries (so the relevance gate + score semantics stay comparable);
    ranking uses the RRF score, which is robust to a fact scoring mid on
    several differently-phrased queries. Ties break on raw score.
    """
    rrf: Dict[str, float] = {}
    best: Dict[str, dict] = {}
    for ranked in per_query_hits:
        for rank, h in enumerate(ranked, start=1):
            mid = h.get("id")
            if not mid:
                continue
            rrf[mid] = rrf.get(mid, 0.0) + 1.0 / (k + rank)
            cur = best.get(mid)
            if cur is None or float(h.get("score", 0.0) or 0.0) > \
                    float(cur.get("score", 0.0) or 0.0):
                best[mid] = h
    merged = [dict(h) for h in best.values()]
    for h in merged:
        h["rrf_score"] = rrf[h["id"]]
    merged.sort(key=lambda h: (h["rrf_score"], h.get("score", 0.0)),
                reverse=True)
    return merged


def _search_scopes(
    client: MemoryClient,
    cfg: MemoryConfig,
    user_id: str,
    queries: List[str],
    k: int,
    threshold: float,
) -> tuple:
    """Run all (query, scope) mem0 searches concurrently (memory_todo 3b).

    Each op carries the retrieval timeout (``cfg.timeout_s``); the total
    wait is capped at 2x that (the client pool has enough workers that
    wall time is ~one op, not the sum — the pre-3b single-query path also
    ran 2 ops, sequentially). Returns ``(per_query_hits, degraded,
    reason)`` where ``per_query_hits[i]`` is the scope-merged, deduped,
    threshold-gated hit list for ``queries[i]``. ``reason`` is
    ``"timeout"`` or ``"error"`` when degraded ("" when healthy) so the
    caller can surface a retry hint. Any op failure degrades (empty list
    for that query/scope) — never raises into the chat path.
    """
    scopes = [("private", user_id)]
    if cfg.household_enabled:
        scopes.append(("household", cfg.household_user_id))

    futures = []
    for qi, q in enumerate(queries):
        for scope_name, uid in scopes:
            def _op(q=q, uid=uid):
                return client._ensure_client().search(
                    q, filters={"user_id": uid}, top_k=k
                )
            futures.append((client._pool.submit(_op), qi, scope_name))

    per_query: List[List[dict]] = [[] for _ in queries]
    seen: List[set] = [set() for _ in queries]
    degraded = False
    reason = ""
    budget_end = time.monotonic() + 2.0 * cfg.timeout_s
    for fut, qi, scope_name in futures:
        remaining = max(0.05, budget_end - time.monotonic())
        try:
            raw = fut.result(timeout=remaining)
        except Exception as e:  # noqa: BLE001 - degrade
            logger.warning("memory search (%s, query %d) failed: %s",
                           scope_name, qi, e)
            degraded = True
            if not reason:
                # TimeoutError (built-in) covers
                # concurrent.futures.TimeoutError (budget exhausted);
                # MemoryTimeout is the per-op timeout. Both have empty
                # str(), so classify by type, not message.
                reason = ("timeout"
                          if isinstance(e, (TimeoutError, MemoryTimeout))
                          else "error")
            _metrics.get_metrics().record_error("search")
            continue
        for h in _as_list(raw):
            nh = _normalize_hit(h, scope_name)
            if nh["id"] not in seen[qi] and nh["score"] >= threshold:
                seen[qi].add(nh["id"])
                per_query[qi].append(nh)
    return per_query, degraded, reason


# ── Public API ────────────────────────────────────────────────────────
def search_memory(
    user_id: str,
    query: str,
    top_k: Optional[int] = None,
) -> List[dict]:
    """Search the user's private + household memories for ``query``.

    Returns a list of normalized hits (private + household merged, deduped,
    ranked by ``rank_score`` desc, truncated to ``top_k``). Hits scoring
    below ``cfg.score_threshold`` are dropped (conservative relevance gate
    — an unrelated memory is worse than none). Each hit carries both
    ``score`` (raw cosine) and ``rank_score`` (raw x recency x importance
    boosts — memory_todo 3a/3e). Returns ``[]`` on error, timeout, or when
    retrieval is disabled / the user is unknown.

    Multi-query (memory_todo 3b, ``cfg.multiquery_enabled``): heuristic
    subqueries (quoted phrases / capitalized entities) are searched in
    parallel with the original and merged with reciprocal rank fusion —
    catches facts phrased differently. Each query is still threshold-gated
    on its own raw scores.

    Side-channel: every call updates the module-level ``LAST_SEARCH``
    dict (``{degraded, reason, retry}``) so the REST/MCP surfaces can
    tell a TRANSIENT empty (cold-start timeout — retry once) from a real
    "no memories". The return value stays a plain list.
    """
    global _first_search_done
    cfg = _get_config()
    # Reset the status side-channel for this call — the early returns
    # below leave it clean, so a stale degraded flag from a previous
    # request can never leak into the next REST/MCP response.
    LAST_SEARCH.update(degraded=False, reason="", retry=False)
    if not cfg.retrieval_allowed:
        return []
    if not _valid_user(user_id) or not query or not str(query).strip():
        return []

    k = top_k or cfg.top_k
    threshold = cfg.score_threshold or 0.0
    client = _get_client()
    degraded = False
    t0 = time.monotonic()

    # Multi-query (3b): original + up to cfg.multiquery_max - 1 heuristic
    # subqueries. Short / entity-free queries keep the single-query path.
    queries = [query]
    if cfg.multiquery_enabled:
        subs = _derive_subqueries(query, cfg.multiquery_max)
        if subs:
            queries = [query] + subs

    per_query, degraded, reason = _search_scopes(
        client, cfg, user_id, queries, k, threshold
    )
    hits = per_query[0] if len(queries) == 1 else _merge_rrf(per_query)

    # Status side-channel: surface degradation (esp. cold start) so
    # REST/MCP clients can retry once instead of concluding "no
    # memories". One retry is cheap; the reason string carries the
    # detail (cold_start vs timeout vs error).
    if degraded:
        if not _first_search_done and reason == "timeout":
            reason = ("cold_start: first search after process start "
                      "(Qdrant/embedding init) — retry once")
        LAST_SEARCH.update(degraded=True, reason=reason, retry=True)
    _first_search_done = True

    # Ranking (3a/3e): keep the raw score for transparency, rank by the
    # boosted score. The threshold gate above already ran on raw scores, so
    # the boosts only reorder relevant hits — never admit new ones.
    for h in hits:
        h["raw_score"] = h["score"]
        h["rank_score"] = _rank_score(h, cfg)
    hits.sort(key=lambda h: h["rank_score"], reverse=True)
    result = hits[:k]
    _metrics.get_metrics().record_search(
        "degraded" if degraded else "ok",
        time.monotonic() - t0,
        len(result),
    )
    return result


def learn_from_turn(
    user_id: str,
    messages: List[dict],
    source: str = "chat",
    agent_id: Optional[str] = None,
    run_id: Optional[str] = None,
    importance: str = "normal",
    confidence: str = "normal",
    infer: bool = True,
    prompt: Optional[str] = None,
    household: bool = False,
) -> List[str]:
    """Extract + store durable facts from a conversation turn.

    Runs the policy pre-filter (strip system/tool content, reject
    secret-like content) then calls mem0 ``add``. Returns the list of newly
    added memory IDs (best-effort; may be ``[]`` even on success if mem0's
    response shape omits IDs). Returns ``[]`` on error, timeout, or when
    writeback is disabled / the user is unknown / the turn is not storeable.

    Phase 5 (PDF §6): provenance metadata on every stored fact —
    ``source`` (chat / direct_user / ...), ``importance`` (normal / high),
    ``confidence`` (normal / high — direct user statements are highest
    trust), ``agent``, ``turn_id``.

    NOTE: mem0 2.0.19 strips the identity keys (user_id/agent_id/run_id/
    actor_id) from ``metadata`` and treats top-level agent_id/run_id kwargs
    as *scope* keys (which would also scope mem0's internal dedup search
    per-turn, breaking cross-turn dedup). Provenance is therefore stored
    under the free-form keys ``agent`` / ``turn_id``.

    ``household=True`` writes to the shared family scope
    (``cfg.household_user_id``) instead of the caller's private scope —
    family facts visible in every user's reads (merged by
    search_memory / list_memories). ``user_id`` is still validated as the
    CALLER (provenance ``written_by``), never as the write scope.
    """
    cfg = _get_config()
    if not cfg.writeback_allowed:
        return []
    if not _valid_user(user_id):
        return []
    # Household scope: family-shared facts. The caller is still validated
    # above; the write lands in the shared bucket every user's reads merge.
    write_scope = (
        cfg.household_user_id if (household and cfg.household_enabled) else user_id
    )

    ok, reason = _policy.should_store(messages)
    if not ok:
        if cfg.debug_logging:
            logger.debug("learn_from_turn skipped (%s): %s", user_id, reason)
        return []

    cleaned = _policy.sanitize_turn(messages)
    if not any(m["role"] == "user" for m in cleaned):
        return []

    client = _get_client()
    metadata = {
        "source": source,
        "importance": importance,
        "confidence": confidence,
    }
    if agent_id:
        metadata["agent"] = agent_id
    if run_id:
        metadata["turn_id"] = run_id
    if write_scope != user_id:
        # Provenance: who wrote a household fact (mem0 strips identity keys
        # from metadata, but free-form keys survive).
        metadata["written_by"] = user_id

    def _add_op():
        return client._ensure_client().add(
            cleaned, user_id=write_scope, metadata=metadata, infer=infer, prompt=prompt
        )

    t0 = time.monotonic()
    try:
        res = client._with_timeout(
            _add_op, timeout_s=cfg.writeback_timeout_s
        )
        ids = _extract_ids(res)
        _metrics.get_metrics().record_writeback(
            "ok", time.monotonic() - t0, len(ids)
        )
        if cfg.debug_logging:
            logger.debug("learn_from_turn stored %d fact(s) for %s: %s",
                         len(ids), user_id, ids)
        return ids
    except MemoryTimeout as e:
        logger.warning("learn_from_turn timed out for %s: %s", user_id, e)
        _metrics.get_metrics().record_writeback("timeout", time.monotonic() - t0, 0)
        _metrics.get_metrics().record_error("writeback")
        return []
    except Exception as e:  # noqa: BLE001 - degrade
        logger.warning("learn_from_turn failed for %s: %s", user_id, e)
        _metrics.get_metrics().record_writeback("error", time.monotonic() - t0, 0)
        _metrics.get_metrics().record_error("writeback")
        return []


def remember_direct(
    user_id: str,
    text: str,
    run_id: Optional[str] = None,
) -> List[str]:
    """Explicit "remember this" command (Phase 5 item 5).

    Stores the user's direct statement with ``source=direct_user``,
    ``importance=high``, ``confidence=high`` (PDF §6: direct user
    statements = highest trust). Returns the stored memory IDs (``[]``
    if nothing was stored / writeback disabled / unknown user).

    Deterministic: stored with ``infer=False`` (raw text, no LLM
    extraction) — an explicit remember command must not silently fail
    because the extraction LLM returned malformed JSON or paraphrased
    the statement. The imperative prefix ("remember that ...") is
    stripped first; the policy pre-filter (secret reject) still applies.
    """
    text = _policy.strip_remember_prefix(text)
    if not text:
        return []
    return learn_from_turn(
        user_id,
        [{"role": "user", "content": text}],
        source="direct_user",
        run_id=run_id,
        importance="high",
        confidence="high",
        infer=False,
    )


def forget_matching(
    user_id: str,
    query: str,
    top_k: int = 3,
) -> List[dict]:
    """Explicit "forget that" command (Phase 5 item 5): targeted delete.

    Searches the user's memories for ``query`` and deletes the hits that
    clear the relevance threshold (default ``MEMORY_SCORE_THRESHOLD``).
    Returns the deleted memories as ``[{"id", "text", "score"}, ...]``
    (empty list if nothing matched or on any error — non-fatal).
    """
    query = (query or "").strip()
    if not query or not _valid_user(user_id):
        return []
    cfg = _get_config()
    try:
        hits = search_memory(user_id, query, top_k=top_k)
        if not hits:
            return []
        deleted: List[dict] = []
        for h in hits:
            mid = h.get("id")
            if not mid:
                continue
            if delete_memory(mid):
                deleted.append(
                    {"id": mid, "text": h.get("text", ""), "score": h.get("score")}
                )
        if deleted and cfg.debug_logging:
            logger.info(
                "forget_matching: deleted %d memor(y/ies) for %s: %s",
                len(deleted), user_id, [d["id"] for d in deleted],
            )
        return deleted
    except Exception as e:  # noqa: BLE001 - degrade
        logger.warning("forget_matching failed for %s: %s", user_id, e)
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
        # get_all is a Qdrant scroll: ~2.3s measured cold, so the 1.5s
        # chat-retrieval budget makes it flaky. List runs in non-blocking
        # contexts (sweep, admin, MCP introspection) → admin budget.
        raw = client._with_timeout(_get_all_private, timeout_s=cfg.admin_timeout_s)
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
            raw = client._with_timeout(_get_all_household, timeout_s=cfg.admin_timeout_s)
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
        _metrics.get_metrics().record_error("update")
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
        _metrics.get_metrics().record_error("delete")
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
        _metrics.get_metrics().record_error("delete_user")
        return 0


def is_healthy() -> bool:
    """Return the memory backend health status (cached, cheap)."""
    try:
        return _get_client().is_healthy()
    except Exception:  # noqa: BLE001 - health must never raise
        return False


def warmup() -> bool:
    """Initialize the mem0 client eagerly (idempotent, non-fatal).

    The first mem0 init (lazy import, Qdrant connect, client construction)
    takes several seconds. Called at skill-runner startup in a background
    thread so the one-time cost is NOT paid inside the first chat turn's
    writeback budget (a cold first turn otherwise times out the 30s
    writeback budget and silently loses its facts).

    Returns True when the client is ready, False otherwise (never raises).
    """
    try:
        _get_client()._ensure_client()
        return True
    except Exception as e:  # noqa: BLE001 - warmup must never raise
        logger.warning("memory warmup failed (non-fatal): %s", e)
        return False


def render_context(user_id: str, query: str) -> str:
    """Convenience: search + render the ``<long_term_memory>`` block.

    Returns ``""`` when there is nothing to inject (no hits, below the
    score threshold, error, timeout, disabled, or unknown user). Intended
    for the system-prompt injection path (Phase 4) — the ONE place both
    call sites (``_chat_direct`` and the ``siri_chat`` skill) use, so the
    retrieval + rendering behavior stays identical.
    """
    cfg = _get_config()
    hits = search_memory(user_id, query)
    if not hits:
        return ""
    return _context.render_memory_block(hits, cfg)