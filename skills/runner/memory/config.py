"""Environment-driven configuration for the long-term memory module.

All values come from ``MEMORY_*`` env vars (see compose/compose.skill-runner.yml
and .env). This module is pure (no mem0 import) so it can be unit-tested
without the live services running.

The dedicated service credential (MEMORY_LITELLM_KEY) is a model-restricted
LiteLLM key (user_id=memory-service) that can only reach
matrix-coder / matrix-gemma4-moe / homelab-embedding-v1 — least privilege.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


@dataclass
class MemoryConfig:
    """Runtime settings for the memory module."""

    # Master + per-feature flags. MEMORY_ENABLED is the single kill switch;
    # MEMORY_RETRIEVAL_ENABLED / MEMORY_WRITEBACK_ENABLED are the fine-grained
    # switches (one env var disables retrieval or writeback independently).
    enabled: bool = True
    retrieval_enabled: bool = True
    writeback_enabled: bool = True
    mcp_enabled: bool = False  # Phase 6 (MCP server) — off in v1
    household_enabled: bool = True
    debug_logging: bool = False

    # LiteLLM (the ONLY LLM + embedding gateway — no direct backend access).
    litellm_base_url: str = "http://litellm-proxy:4000/v1"
    litellm_api_key: str = ""  # dedicated, model-restricted key
    extraction_model: str = "matrix-coder"
    embed_model: str = "homelab-embedding-v1"

    # Qdrant vector store.
    # Phase 9 hardening: qdrant_api_key is a JWT RBAC token (HS256, signed
    # with the Qdrant admin key) scoped to THIS collection only (rw). See
    # scripts/qdrant-jwt.py and docs/memory/IMPLEMENTATION_STATE.md.
    # Empty = no auth header (pre-hardening / local dev without auth).
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    collection: str = "mem0_memories"
    embed_dim: int = 768

    # Tuning.
    top_k: int = 6
    # Relevance gate for injected memories: hits scoring below this cosine
    # similarity are dropped (conservative — an unrelated memory injected
    # into an unrelated task is worse than none). 0 disables the gate.
    score_threshold: float = 0.5
    # Retrieval timeout (blocks the chat response — must stay fast).
    timeout_ms: int = 1500
    # Writeback timeout (LLM extraction is slow; runs as a background task
    # in Phase 4/5, so it can be generous).
    writeback_timeout_ms: int = 30000
    # Admin timeout for update/delete/delete_user ops (non-hot-path, no LLM,
    # but a single mem0 delete was measured at ~2.3s — well over the 1.5s
    # retrieval budget). 10s is generous headroom for store ops.
    admin_timeout_ms: int = 10000
    max_context_tokens: int = 1500
    # Phase 5: custom instructions appended to mem0's fact-extraction
    # prompt (inclusion/exclusion + trust rules, PDF §6). Empty string =
    # use policy.DEFAULT_EXTRACTION_INSTRUCTIONS.
    extraction_instructions: str = ""

    # Virtual user_id used to scope household (explicitly shared) facts.
    household_user_id: str = "household"

    @property
    def timeout_s(self) -> float:
        return self.timeout_ms / 1000.0

    @property
    def writeback_timeout_s(self) -> float:
        return self.writeback_timeout_ms / 1000.0

    @property
    def admin_timeout_s(self) -> float:
        return self.admin_timeout_ms / 1000.0

    @property
    def retrieval_allowed(self) -> bool:
        return self.enabled and self.retrieval_enabled

    @property
    def writeback_allowed(self) -> bool:
        return self.enabled and self.writeback_enabled


def load_config() -> MemoryConfig:
    """Build a ``MemoryConfig`` from the process environment."""
    return MemoryConfig(
        enabled=_env_bool("MEMORY_ENABLED", True),
        retrieval_enabled=_env_bool("MEMORY_RETRIEVAL_ENABLED", True),
        writeback_enabled=_env_bool("MEMORY_WRITEBACK_ENABLED", True),
        mcp_enabled=_env_bool("MEMORY_MCP_ENABLED", False),
        household_enabled=_env_bool("MEMORY_HOUSEHOLD_ENABLED", True),
        debug_logging=_env_bool("MEMORY_DEBUG_LOGGING", False),
        litellm_base_url=os.environ.get(
            "MEMORY_LITELLM_BASE_URL", "http://litellm-proxy:4000/v1"
        ),
        litellm_api_key=os.environ.get("MEMORY_LITELLM_KEY", ""),
        extraction_model=os.environ.get("MEMORY_EXTRACTION_MODEL", "matrix-coder"),
        qdrant_url=os.environ.get("MEMORY_QDRANT_URL", "http://qdrant:6333"),
        qdrant_api_key=os.environ.get("MEMORY_QDRANT_API_KEY", ""),
        collection=os.environ.get("MEMORY_COLLECTION", "mem0_memories"),
        embed_dim=_env_int("MEMORY_EMBED_DIM", 768),
        top_k=_env_int("MEMORY_TOP_K", 6),
        score_threshold=_env_float("MEMORY_SCORE_THRESHOLD", 0.5),
        timeout_ms=_env_int("MEMORY_TIMEOUT_MS", 1500),
        writeback_timeout_ms=_env_int("MEMORY_WRITEBACK_TIMEOUT_MS", 30000),
        admin_timeout_ms=_env_int("MEMORY_ADMIN_TIMEOUT_MS", 10000),
        max_context_tokens=_env_int("MEMORY_MAX_CONTEXT_TOKENS", 1500),
        extraction_instructions=os.environ.get(
            "MEMORY_EXTRACTION_INSTRUCTIONS", ""
        ).strip(),
    )