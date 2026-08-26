"""Mem0 client wrapper: lazy init, timeouts, health checks.

``mem0`` is imported lazily (inside ``_ensure_client``) so the rest of the
memory package (config/policy/context/interface) can be imported and
unit-tested without mem0 installed or the live services running.

Every mem0 call is wrapped in a thread-pool timeout so a slow/hung Qdrant or
LiteLLM degrades gracefully instead of taking the assistant down
(non-negotiable: never take the assistant down).

Telemetry is disabled (MEM0_TELEMETRY=false) for homelab privacy.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _FuturesTimeout
from typing import Any, Callable, Optional

from .config import MemoryConfig

logger = logging.getLogger("memory.client")

# Disable mem0 telemetry (homelab privacy — no PostHog). Set before mem0
# imports so it takes effect. (Also set in compose env as a backstop.)
os.environ.setdefault("MEM0_TELEMETRY", "false")


class MemoryTimeout(Exception):
    """Raised when a mem0 operation exceeds the configured timeout."""


class MemoryClient:
    """Lazy, timeout-guarded wrapper around a mem0 ``Memory`` instance."""

    def __init__(self, cfg: MemoryConfig):
        self.cfg = cfg
        self._mem: Optional[Any] = None
        self._lock = threading.Lock()
        self._init_error: Optional[str] = None
        # Small pool dedicated to timeout enforcement for sync mem0 calls.
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="memory")
        # Health cache.
        self._healthy: Optional[bool] = None
        self._healthy_at: float = 0.0
        self._health_ttl: float = 30.0  # seconds

    # ── Lazy init ────────────────────────────────────────────────────
    def _ensure_client(self) -> Any:
        """Create (once) and return the mem0 ``Memory`` instance."""
        if self._mem is not None:
            return self._mem
        with self._lock:
            if self._mem is not None:
                return self._mem
            if self._init_error:
                raise RuntimeError(self._init_error)
            try:
                from mem0 import Memory  # lazy import

                config = {
                    "llm": {
                        "provider": "openai",
                        "config": {
                            "model": self.cfg.extraction_model,
                            "api_key": self.cfg.litellm_api_key,
                            "openai_base_url": self.cfg.litellm_base_url,
                            "temperature": 0.1,
                        },
                    },
                    "embedder": {
                        "provider": "openai",
                        "config": {
                            "model": self.cfg.embed_model,
                            "api_key": self.cfg.litellm_api_key,
                            "openai_base_url": self.cfg.litellm_base_url,
                        },
                    },
                    "vector_store": {
                        "provider": "qdrant",
                        "config": {
                            "url": self.cfg.qdrant_url,
                            "collection_name": self.cfg.collection,
                            "embedding_model_dims": self.cfg.embed_dim,
                        },
                    },
                }
                self._mem = Memory.from_config(config)
                logger.info(
                    "mem0 Memory initialized (collection=%s, llm=%s, embed=%s)",
                    self.cfg.collection,
                    self.cfg.extraction_model,
                    self.cfg.embed_model,
                )
                return self._mem
            except Exception as e:  # noqa: BLE001 - degrade, never crash caller
                self._init_error = f"mem0 init failed: {e}"
                logger.warning(self._init_error)
                raise

    @property
    def available(self) -> bool:
        """True if the mem0 client is initialized (or can be)."""
        return self._mem is not None or self._init_error is None

    # ── Timeout wrapper ──────────────────────────────────────────────
    def _with_timeout(self, fn: Callable, *args: Any, timeout_s: Optional[float] = None, **kwargs: Any) -> Any:
        """Run ``fn`` in the pool, enforcing a timeout budget.

        ``timeout_s`` overrides the default ``cfg.timeout_s`` when provided
        (e.g. the writeback/learn path uses a longer budget because it runs
        an LLM extraction). Raises :class:`MemoryTimeout` on timeout. The
        underlying call may continue in the background (it cannot be
        cancelled), but the caller gets a degraded result promptly.
        """
        budget = self.cfg.timeout_s if timeout_s is None else timeout_s
        fut = self._pool.submit(fn, *args, **kwargs)
        try:
            return fut.result(timeout=budget)
        except _FuturesTimeout:
            raise MemoryTimeout(f"memory op timed out after {budget:.2f}s")

    # ── Health ───────────────────────────────────────────────────────
    def is_healthy(self) -> bool:
        """Cheap health check: does the Qdrant collection exist?

        Cached for ``_health_ttl`` seconds to avoid hammering Qdrant.
        """
        now = time.time()
        if self._healthy is not None and (now - self._healthy_at) < self._health_ttl:
            return self._healthy
        healthy = False
        try:
            import httpx

            r = httpx.get(
                f"{self.cfg.qdrant_url}/collections/{self.cfg.collection}",
                timeout=2.0,
            )
            healthy = r.status_code == 200
        except Exception:  # noqa: BLE001 - health check must never raise
            healthy = False
        self._healthy = healthy
        self._healthy_at = now
        if not healthy:
            logger.warning(
                "memory health check failed (qdrant collection %s unreachable)",
                self.cfg.collection,
            )
        return healthy

    # ── Reset (for tests) ────────────────────────────────────────────
    def reset(self) -> None:
        """Drop the cached client (used by tests to force re-init)."""
        with self._lock:
            self._mem = None
            self._init_error = None
            self._healthy = None
            self._healthy_at = 0.0