"""Identity resolution for the memory subsystem (memory_todo.md Phase 3).

Maps an incoming ``X-API-Key`` value to a stable ``user_id`` via an explicit
map so that raw key values never appear in config, code, fixtures, or logs.

Map format (``MEMORY_USER_KEYS`` env var): comma-separated ``user_id=ENV_VAR``
pairs, e.g.::

    MEMORY_USER_KEYS=chuck=SKILL_RUNNER_API_KEY,service=SIRI_KEY_SERVICE

Each entry names an *env var* (not a key value). At resolve time the incoming
key is compared (constant-time) against the value(s) of the referenced env
var. A referenced env var may itself hold a comma-separated key list (legacy
``SKILL_RUNNER_API_KEY`` behaviour) — every listed value maps to that user.

Rules:
- known key      -> mapped user_id (e.g. "chuck")
- unmapped key   -> "unknown" (no retrieval, no writeback; logged)
- missing key    -> "unknown"
- never defaults to a real user.

Adding a new principal later is one line: ``son=SIRI_KEY_SON`` (plus the env
var in .env and compose).

This module is pure stdlib (no mem0, no FastAPI) so it is unit-testable on the
host and importable from ``main.py`` at startup.
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Mapping, Optional

logger = logging.getLogger("memory.identity")

# ── Identity constants ────────────────────────────────────────────────
USER_UNKNOWN = "unknown"   # unmapped/missing key: no retrieval, no writeback
USER_SERVICE = "service"   # scheduler jobs / unattributed jobs (D10)
HOUSEHOLD_ID = "family"    # v1 single household scope

# Per-request context, task-scoped (asyncio tasks copy the context, so a value
# set in one request handler never leaks into another request).
_current_context: "ContextVar[Optional[RequestContext]]" = ContextVar(
    "memory_request_context", default=None
)


@dataclass(frozen=True)
class RequestContext:
    """Per-request identity carried through api_chat -> dispatch_job -> skill.

    ``run_id`` correlates every job/memory op of one request; ``source`` is
    the entry point (siri | web | job | cli). ``agent_id`` is reserved for
    multi-agent runs (Phase 7+); None in v1.
    """

    user_id: str
    household_id: str = HOUSEHOLD_ID
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    source: str = "web"
    agent_id: Optional[str] = None
    # Key threading (auth_todo.md Phase 2.2): the caller's X-API-Key value,
    # used to thread the per-user LiteLLM key through skill execution.
    api_key: Optional[str] = None


def set_current_context(ctx: RequestContext) -> object:
    """Set the request context for the current task. Returns a reset token."""
    return _current_context.set(ctx)


def get_current_context() -> Optional[RequestContext]:
    """Return the current task's request context, or None outside a request."""
    return _current_context.get()


def reset_current_context(token: object) -> None:
    """Restore the context to its state before ``set_current_context``."""
    _current_context.reset(token)


class IdentityResolver:
    """Resolve X-API-Key values to user_ids via env-var-name references.

    ``map_spec`` is the ``MEMORY_USER_KEYS`` format (see module docstring).
    ``environ`` is injectable for tests; defaults to ``os.environ``.
    """

    def __init__(
        self,
        map_spec: str = "",
        environ: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._entries: list[tuple[str, str]] = []  # (user_id, env_var_name)
        self._environ: Mapping[str, str] = os.environ if environ is None else environ
        for part in map_spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                logger.warning(
                    "MEMORY_USER_KEYS entry %r malformed (expected user_id=ENV_VAR); skipped",
                    part,
                )
                continue
            user_id, env_name = part.split("=", 1)
            user_id = user_id.strip()
            env_name = env_name.strip()
            if not user_id or not env_name:
                logger.warning("MEMORY_USER_KEYS entry %r incomplete; skipped", part)
                continue
            self._entries.append((user_id, env_name))
        if self._entries:
            logger.debug(
                "Identity map loaded: %d user(s) via env vars %s",
                len(self._entries),
                ", ".join(env for _, env in self._entries),
            )
        self._warn_on_conflicts()

    def _warn_on_conflicts(self) -> None:
        """Phase 3.1: detect key values claimed by more than one user_id.

        ``resolve()`` is first-match-wins, so when a key value appears in the
        env-var pools of two different users the later entry is SHADOWED and
        silently resolves to the earlier user (privacy bug 2026-09-02: the
        legacy ``chuck=SKILL_RUNNER_API_KEY`` entry shadowed
        ``dylan=LITELLM_KEY_DYLAN`` because SKILL_RUNNER_API_KEY held both
        users' keys). We cannot change resolution semantics without breaking
        the documented first-match contract, so we make the conflict loud at
        startup instead. Key VALUES are never logged — only env var names and
        key positions (ordinal within the pool).
        """
        claimed: dict[str, list[tuple[str, str]]] = {}  # value -> [(user, env)]
        for user_id, env_name in self._entries:
            raw = self._environ.get(env_name, "")
            for candidate in (v.strip() for v in raw.split(",")):
                if candidate:
                    claimed.setdefault(candidate, []).append((user_id, env_name))
        for value, claims in claimed.items():
            users = {u for u, _ in claims}
            if len(users) > 1:
                logger.warning(
                    "MEMORY_USER_KEYS CONFLICT: a key value claimed by %s "
                    "(%s) resolves to the FIRST user in map order — later "
                    "entries are shadowed. Make each key value map to exactly "
                    "one user_id (e.g. user=LITELLM_KEY_<USER> per user).",
                    ", ".join(sorted(users)),
                    ", ".join(f"{u}={e}" for u, e in claims),
                )

    def resolve(self, x_api_key: Optional[str]) -> str:
        """Return the user_id for an incoming key value.

        Unknown/missing keys resolve to ``USER_UNKNOWN`` — never to a real
        user. Only the resolved user_id (and env var *names*) are logged;
        key values are never logged.
        """
        if not x_api_key or not str(x_api_key).strip():
            return USER_UNKNOWN
        incoming = str(x_api_key).strip().encode("utf-8")
        for user_id, env_name in self._entries:
            raw = self._environ.get(env_name, "")
            for candidate in (v.strip() for v in raw.split(",")):
                if not candidate:
                    continue
                if hmac.compare_digest(incoming, candidate.encode("utf-8")):
                    logger.debug(
                        "Identity resolved: user_id=%s (source env %s)",
                        user_id,
                        env_name,
                    )
                    return user_id
        # Key present but not in the map -> safe default, no memory access.
        logger.info(
            "Unmapped API key: user_id=%s (no retrieval, no writeback)",
            USER_UNKNOWN,
        )
        return USER_UNKNOWN


# ── Process-wide resolver singleton ───────────────────────────────────
_resolver: Optional[IdentityResolver] = None
_resolver_lock = threading.Lock()


def get_resolver() -> IdentityResolver:
    """Lazy singleton built from ``MEMORY_USER_KEYS`` (non-reentrant safe)."""
    global _resolver
    if _resolver is None:
        with _resolver_lock:
            if _resolver is None:
                _resolver = IdentityResolver(os.environ.get("MEMORY_USER_KEYS", ""))
    return _resolver


def resolve_user_id(x_api_key: Optional[str]) -> str:
    """Resolve an X-API-Key value to a user_id (see module docstring)."""
    return get_resolver().resolve(x_api_key)


def reset_resolver() -> None:
    """Test hook: drop the singleton so the next call re-reads the env."""
    global _resolver
    with _resolver_lock:
        _resolver = None