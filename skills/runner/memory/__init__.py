"""Long-term memory for the Thor skill runner.

In-process Mem0 backed by Qdrant (collection ``mem0_memories``) with
LiteLLM as the single LLM + embedding gateway (no direct backend access).

Design (memory_todo.md Phase 2):
  - ``config``   — env-driven settings (pure, unit-testable)
  - ``policy``   — inclusion/exclusion rules (pure, unit-testable)
  - ``context``  — renders the <long_term_memory> block (pure)
  - ``client``   — lazy, timeout-guarded Mem0 wrapper
  - ``interface``— the ONLY surface other code calls (graceful degradation)

Non-negotiables honored here:
  - No LiteLLM bypass (all LLM + embedding traffic via litellm-proxy).
  - Graceful degradation: every interface call is non-fatal; on error or
    timeout it returns an empty/degraded result and logs, never raising
    into the chat path (never take the assistant down).
  - Telemetry off (MEM0_TELEMETRY=false, set in client + compose).
"""
from .config import MemoryConfig, load_config
from .interface import (
    delete_memory,
    delete_user_memories,
    list_memories,
    learn_from_turn,
    remember_direct,
    forget_matching,
    search_memory,
    update_memory,
    is_healthy,
    warmup,
)
from .jobctx import (
    job_identity,
    retrieve,
    writeback_turn,
    writeback_outcome,
)

__all__ = [
    "MemoryConfig",
    "load_config",
    "search_memory",
    "learn_from_turn",
    "remember_direct",
    "forget_matching",
    "list_memories",
    "update_memory",
    "delete_memory",
    "delete_user_memories",
    "is_healthy",
    "warmup",
    # Phase 7 — job-aware helpers (identity propagation for skills)
    "job_identity",
    "retrieve",
    "writeback_turn",
    "writeback_outcome",
]