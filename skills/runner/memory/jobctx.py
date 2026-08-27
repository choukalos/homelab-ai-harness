"""Job-aware memory helpers (Phase 7 — jobs/agents/skills integration).

Bridges the runner's ``Job`` object (which carries ``user_id`` /
``run_id`` / ``memory_enabled`` from the Phase 3/4 identity work) and the
memory ``interface``, so that ANY skill — conversational (``siri_ask``,
``siri_chat``) or long-running (briefs, ``deep_research``) — can retrieve
and write back memory with the correct identity, without each skill
re-implementing the gating / non-fatality / logging.

This is the single propagation path: ``dispatch_job()`` resolves the
identity into the ``Job``; ``_execute_skill`` hands the ``Job`` to
``skill.run(params, job)``; this module reads it back. Skills that call
LiteLLM directly (sub-agent calls) therefore inherit the caller's
identity automatically.

Non-negotiables honored here:
  - Non-fatal: every function degrades to a no-op (empty block / no
    writeback) on any error and logs to the job. Memory must never break
    a skill.
  - Identity-safe: ``service`` / ``unknown`` / missing identity never
    touch personal memory (the interface's ``_valid_user`` rejects them),
    so a job with no resolved user is a no-op, not a leak.
  - Lazy import: the ``memory`` package is imported inside each function
    so skills stay importable standalone (importlib, stdlib-only by
    design) and a memory import failure degrades gracefully.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

logger = logging.getLogger("memory.jobctx")

# A job with no resolved identity falls back to "unknown" (never a
# personal user) — the interface's _valid_user rejects it, so retrieval
# and writeback both no-op safely.
_UNKNOWN = "unknown"


def job_identity(job: Any) -> Tuple[str, Optional[str], bool]:
    """Extract ``(user_id, run_id, memory_enabled)`` from a runner Job.

    Safe defaults when ``job`` is None or lacks the fields:
    ``("unknown", None, True)``. The per-request switch
    (``memory_enabled``) defaults to True so an older Job object (no
    field) still gets memory; the identity flags + ``_valid_user`` are
    the real gate (service/unknown never get personal memory).
    """
    if job is None:
        return _UNKNOWN, None, True
    user_id = getattr(job, "user_id", None) or _UNKNOWN
    run_id = getattr(job, "run_id", None)
    memory_enabled = getattr(job, "memory_enabled", True)
    return user_id, run_id, bool(memory_enabled)


def _job_log(job: Any, msg: str) -> None:
    """Log to the job (if it has add_log) and to the module logger."""
    logger.debug(msg)
    if job is not None and hasattr(job, "add_log"):
        try:
            job.add_log(msg)
        except Exception:  # noqa: BLE001 — logging must never raise
            pass


def retrieve(job: Any, query: str) -> str:
    """Render the ``<long_term_memory>`` block for this job (gated).

    Returns ``""`` when memory is off for this job, the identity is
    service/unknown, there are no hits, or anything fails. Non-fatal.
    """
    user_id, _run_id, memory_enabled = job_identity(job)
    if not memory_enabled or not (query or "").strip():
        return ""
    try:
        from memory import interface  # lazy: keep skills importable standalone
        block = interface.render_context(user_id, query)
        _job_log(job, f"Memory retrieve: user_id={user_id} block_chars={len(block)}")
        return block
    except Exception as exc:  # noqa: BLE001 — never break the skill
        _job_log(job, f"Memory retrieve failed (non-fatal): {exc}")
        return ""


def writeback_turn(
    job: Any,
    messages: List[dict],
    source: str = "chat",
    importance: str = "normal",
    confidence: str = "normal",
) -> List[str]:
    """Write back a conversational turn for this job (gated, non-fatal).

    Returns the stored memory IDs (``[]`` when off / service / unknown /
    nothing durable / error). The job's ``run_id`` is carried as the
    ``turn_id`` provenance tag.
    """
    user_id, run_id, memory_enabled = job_identity(job)
    if not memory_enabled:
        return []
    try:
        from memory import interface  # lazy
        ids = interface.learn_from_turn(
            user_id,
            messages,
            source=source,
            run_id=run_id,
            importance=importance,
            confidence=confidence,
        )
        _job_log(job, f"Memory writeback: user_id={user_id} stored={len(ids)}")
        return ids
    except Exception as exc:  # noqa: BLE001 — never break the skill
        _job_log(job, f"Memory writeback failed (non-fatal): {exc}")
        return []


def writeback_outcome(job: Any, text: str, agent: Optional[str] = None) -> List[str]:
    """Write back a durable OUTCOME from a (long-running) job (Phase 7).

    For long-running jobs the durable outcome is written only at
    completion / checkpoint (never mid-run). Agent-generated facts are
    stored with ``source=agent_result`` and ``confidence=normal`` (lower
    trust than a direct user statement), with the skill name as the
    ``agent`` provenance tag and the job's ``run_id`` for correlation.

    ``text`` should be a concise durable outcome (e.g. the job summary),
    NOT a full artifact / report — the extraction step pulls the durable
    facts. Returns stored IDs (``[]`` when off / service / unknown /
    nothing durable / error). Non-fatal.
    """
    user_id, run_id, memory_enabled = job_identity(job)
    if not memory_enabled or not (text or "").strip():
        return []
    try:
        from memory import interface  # lazy
        ids = interface.learn_from_turn(
            user_id,
            [{"role": "user", "content": text}],
            source="agent_result",
            agent_id=agent,
            run_id=run_id,
            importance="normal",
            confidence="normal",
        )
        _job_log(
            job,
            f"Memory outcome writeback: user_id={user_id} agent={agent} "
            f"stored={len(ids)}",
        )
        return ids
    except Exception as exc:  # noqa: BLE001 — never break the skill
        _job_log(job, f"Memory outcome writeback failed (non-fatal): {exc}")
        return []