"""1b bridge-minted signed tokens — path-bound, TTL'd, in-process (SEC-12).

The token IS the credential: `GET /media/files/dl/{token}` serves exactly
the file the token was minted for, until it expires. Unknown / expired /
missing-file -> 404 (never 403 — do not leak which tokens exist). Nothing
sensitive is stored (path + expiry only); the store is in-process, so a
bridge restart invalidates outstanding tokens (they are short-lived).

Minting happens ONLY via the MCP face (`file_push` destination="client") —
there is no public mint endpoint (D10: no new public write surface).
TTL parity with Matrix `/dl_token`: default 24 h, range 1-168 h.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

TOKEN_HEX_LEN = 16  # -> 32-char hex token
DEFAULT_TTL_H = 24.0
MIN_TTL_H = 1.0
MAX_TTL_H = 168.0


def clamp_ttl(ttl_hours: float) -> float:
    """Validate + coerce a TTL in hours (1..168, parity with Matrix)."""
    t = float(ttl_hours)
    if not (MIN_TTL_H <= t <= MAX_TTL_H):
        raise ValueError(f"ttl_hours must be in [{MIN_TTL_H:g}, {MAX_TTL_H:g}]")
    return t


def iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


DEFAULT_PUBLIC_BASE = "https://siri.choukalos.com/media/files"


def public_url(token: str, base: str = DEFAULT_PUBLIC_BASE) -> str:
    """Public URL for a minted token (Caddy /media/files/* on both hosts)."""
    return f"{base.rstrip('/')}/dl/{token}"


class TokenStore:
    """In-process path-bound token store (purged lazily on access)."""

    def __init__(self, now: Callable[[], float] = time.time):
        self._entries: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._now = now

    def mint(self, path: str, ttl_hours: float = DEFAULT_TTL_H) -> tuple[str, float]:
        """Mint a token bound to `path` (absolute). Returns (token, expires)."""
        ttl = clamp_ttl(ttl_hours)
        now = self._now()
        token = secrets.token_hex(TOKEN_HEX_LEN)
        expires = now + ttl * 3600.0
        with self._lock:
            self._purge_locked()
            self._entries[token] = {
                "path": path, "expires": expires, "minted": now, "ttl_h": ttl,
            }
        return token, expires

    def lookup(self, token: str) -> dict | None:
        """Return the live entry for `token` (a copy) or None (unknown or
        expired — expired entries are dropped)."""
        with self._lock:
            e = self._entries.get(token)
            if e is None:
                return None
            if self._now() >= e["expires"]:
                del self._entries[token]
                return None
            return dict(e)

    def _purge_locked(self) -> None:
        now = self._now()
        for t in [t for t, e in self._entries.items() if now >= e["expires"]]:
            del self._entries[t]

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
