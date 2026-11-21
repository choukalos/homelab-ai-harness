#!/usr/bin/env python3
"""MCP Sessions Server — remote session ingest + owner-scoped read-back
(mcp_sessions Phase 1).

Thin client over skill-runner's SCOPED session endpoints:

  - sessions_ingest(transcript, session_id, host, started_at?, ended_at?)
                    Store the caller's pi session transcript. Server-side
                    split on line boundaries into <=2 MiB parts (the
                    session_id.partN convention); the runner ingest path is
                    unchanged. Hard cap 20 MiB -> explicit error; rate
                    limit ~30 ingests/user/hour (tunable env).
  - sessions_list(since?, limit?)   Metadata-only list of the caller's
                                    ingested sessions.
  - sessions_get(session_id, line_start?, line_end?)
                    Read back the caller's OWN transcript (or a 1-based
                    inclusive line slice of the concatenated part stream)
                    with a verifiable citation header.

Backend: skill-runner (FastAPI, :8091) — ``POST /api/sessions/ingest``,
``GET /api/sessions/ingests`` and ``GET /api/sessions/{session_id}``. All
are user-key authenticated: the caller's LiteLLM key is resolved by
skill-runner's IdentityResolver to a user_id, and reads/writes are scoped
TO THAT user. This server can never read or write another user's
transcripts — cross-user isolation is enforced server-side, not here. The
server NEVER accepts a client-supplied user_id.

Identity threading: the caller's LiteLLM key (forwarded via the
Authorization header when the call routes through LiteLLM) is passed to
skill-runner as X-API-Key. When absent (e.g. pi connecting directly), the
configured SESSIONS_USER_KEY is used — a SINGLE key that must be in
skill-runner's SKILL_RUNNER_API_KEY allow-list (exact-match semantics).

Transport: SSE (HTTP, default 0.0.0.0:8000, path /sse)
"""

import os
import logging
import threading
import time
from collections import deque
from typing import Optional

import httpx
from mcp.server import FastMCP
from mcp.server.fastmcp import Context

from splitter import (
    MAX_TOTAL_BYTES,
    SplitError,
    split_transcript,
    validate_session_id,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SKILL_RUNNER_URL: str = os.environ.get(
    "SKILL_RUNNER_URL", "http://skill-runner:8091"
).rstrip("/")
# Fallback identity key (SINGLE value — skill-runner exact-matches against
# its comma-split allow-list). Set to the user this deployment serves (e.g.
# Chuck's LiteLLM key for the pi-on-Mac deployment).
SESSIONS_USER_KEY: str = os.environ.get("SESSIONS_USER_KEY", "")
MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")
TIMEOUT_S: float = float(os.environ.get("SESSIONS_TIMEOUT_S", "30"))
# Ingest posts can carry up to 2 MiB parts — generous margin.
INGEST_TIMEOUT_S: float = float(os.environ.get("SESSIONS_INGEST_TIMEOUT_S", "120"))
# Rate limit: max sessions_ingest calls per caller key per rolling hour.
RATE_LIMIT_PER_HOUR: int = int(os.environ.get("SESSIONS_RATE_LIMIT", "30"))

logger = logging.getLogger("mcp_sessions")

# ---------------------------------------------------------------------------
# Identity threading (same pattern as mcp_memory)
# ---------------------------------------------------------------------------


def _caller_key(ctx: Optional[Context]) -> Optional[str]:
    """Extract the caller's API key from the forwarded Authorization header."""
    try:
        request = ctx.request_context.request
        auth = request.headers.get("authorization")
        if not auth:
            return None
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return auth.strip()
    except Exception:  # no request context / not an HTTP request
        return None


def _headers(ctx: Optional[Context]) -> dict:
    """X-API-Key = caller's key (forwarded) or the configured user key."""
    key = _caller_key(ctx) or (SESSIONS_USER_KEY or None)
    h = {"Content-Type": "application/json"}
    if key:
        h["X-API-Key"] = key
    return h


def _request(method: str, path: str, ctx: Optional[Context],
             timeout_s: float = None, json: dict = None,
             params: dict = None) -> dict:
    with httpx.Client(timeout=timeout_s or TIMEOUT_S) as client:
        r = client.request(
            method,
            f"{SKILL_RUNNER_URL}{path}",
            json=json,
            params=params,
            headers=_headers(ctx),
        )
    if r.status_code >= 400:
        raise RuntimeError(f"skill-runner {path} failed: {r.status_code} {r.text}")
    return r.json()


# ---------------------------------------------------------------------------
# Rate limiting (in-memory, per caller key, rolling hour)
# ---------------------------------------------------------------------------

_rate_lock = threading.Lock()
_rate_windows: dict[str, deque] = {}


def _rate_limited(key: str) -> bool:
    """True when the caller key has hit RATE_LIMIT_PER_HOUR in the last hour.

    In-memory (per process): the mcp-sessions container is the only client
    of these routes in this deployment, so a process-local window is the
    whole window. Keyed on the caller key (forwarded or fallback) — the
    server never sees a user_id.
    """
    now = time.monotonic()
    with _rate_lock:
        dq = _rate_windows.setdefault(key, deque())
        while dq and now - dq[0] > 3600:
            dq.popleft()
        if len(dq) >= RATE_LIMIT_PER_HOUR:
            return True
        dq.append(now)
        return False


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="mcp_sessions",
    instructions=(
        "Session transcript storage for the authenticated user. "
        "sessions_ingest(transcript, session_id, host) stores the user's own "
        "pi session transcript (verbatim) on the homelab for the reflection "
        "pipeline — server-side splitting handles long sessions; re-ingesting "
        "the same transcript is idempotent (status 'duplicate'). "
        "sessions_get(session_id, line_start?, line_end?) reads back the "
        "user's OWN stored transcript (or a line slice) with a verifiable "
        "citation header. sessions_list() lists the user's ingested sessions "
        "(metadata only). Transcripts are strictly per-user and private: you "
        "will never see or store another user's session."
    ),
    host=MCPS_HOST,
)


@mcp.tool(
    name="sessions_ingest",
    description=(
        "Store the authenticated user's pi session transcript on the "
        "homelab (skill-runner sessions volume, private to the user). "
        "Pass the transcript VERBATIM (the raw .jsonl contents) — the "
        "server splits long transcripts into <=2 MiB parts automatically; "
        "no manual chunking, base64, or byte accounting needed. Hard cap "
        "20 MiB per call; rate limit ~30 calls/hour. Re-ingesting the same "
        "transcript is idempotent (status 'duplicate'). Returns "
        "{status: stored|duplicate, session_id, parts: [{part, "
        "sha256_prefix, bytes, line_range}], total_bytes}."
    ),
)
def sessions_ingest(
    transcript: str,
    session_id: str,
    host: str,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    ctx: Context = None,
) -> dict:
    """Store the user's session transcript.

    Args:
        transcript: The session transcript, verbatim (raw .jsonl).
        session_id: The session id (the .jsonl basename without extension,
            e.g. "2026-11-06T13-30-04-455Z_01a1b10d-...").
        host: The machine the session ran on (e.g. "macbook", "thor.local").
        started_at: Optional ISO-8601 UTC session start.
        ended_at: Optional ISO-8601 UTC session end.

    Returns:
        {status, session_id, parts: [{part, sha256_prefix, bytes,
        line_range}], total_bytes}. status is "stored" when at least one
        part was newly stored, "duplicate" when every part was already on
        the homelab.
    """
    host = (host or "").strip()
    if not host or len(host) > 128:
        raise ValueError("host is required (max 128 chars)")
    if not validate_session_id(session_id):
        raise ValueError(
            "session_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}"
        )
    caller = _caller_key(ctx) or SESSIONS_USER_KEY or "unauthenticated"
    if _rate_limited(caller):
        raise RuntimeError(
            f"rate limit: max {RATE_LIMIT_PER_HOUR} sessions_ingest calls "
            f"per hour — try again later"
        )
    try:
        parts = split_transcript(transcript, session_id)
    except SplitError as exc:
        raise RuntimeError(str(exc))

    results = []
    any_stored = False
    for i, part in enumerate(parts):
        payload: dict = {
            "host": host,
            "session_id": part["session_id"],
            "transcript": part["transcript"],
        }
        if started_at:
            payload["started_at"] = started_at
        if ended_at:
            payload["ended_at"] = ended_at
        resp = _request(
            "POST", "/api/sessions/ingest", ctx,
            timeout_s=INGEST_TIMEOUT_S, json=payload,
        )
        status = resp.get("status", "stored")
        any_stored = any_stored or status == "stored"
        results.append(
            {
                # 0 = single-part transcript (ingested under the bare id)
                "part": 0 if len(parts) == 1 else i + 1,
                "sha256_prefix": (resp.get("sha256") or "")[:16],
                "bytes": resp.get("bytes", len(part["transcript"].encode("utf-8"))),
                "line_range": list(part["lines"]),
            }
        )
    total_bytes = len((transcript or "").encode("utf-8"))
    logger.info(
        "sessions_ingest: session_id=%s host=%s parts=%d status=%s bytes=%d",
        session_id, host, len(parts),
        "stored" if any_stored else "duplicate", total_bytes,
    )
    return {
        "status": "stored" if any_stored else "duplicate",
        "session_id": session_id,
        "parts": results,
        "total_bytes": total_bytes,
    }


@mcp.tool(
    name="sessions_list",
    description=(
        "List the authenticated user's ingested session transcripts "
        "(metadata only — no transcript bodies): id, host, session_id, "
        "started_at, ended_at, sha256, bytes, ingested_at. Newest first. "
        "Use the returned session_id with sessions_get to read a transcript."
    ),
)
def sessions_list(
    since: Optional[str] = None,
    limit: int = 50,
    ctx: Context = None,
) -> dict:
    """List the user's ingested sessions.

    Args:
        since: Optional ISO-8601 UTC lower bound on ingested_at.
        limit: Max rows to return (1-500; default 50).

    Returns:
        {user_id, count, ingests: [{id, user_id, host, session_id,
        started_at, ended_at, sha256, bytes, ingested_at}]}.
    """
    params: dict = {"limit": max(1, min(int(limit), 500))}
    if since:
        params["since"] = since
    return _request("GET", "/api/sessions/ingests", ctx, params=params)


@mcp.tool(
    name="sessions_get",
    description=(
        "Read back the authenticated user's OWN stored session transcript "
        "(owner-only — another user's session is a 404). Returns the "
        "verbatim transcript (or a 1-based inclusive line slice when "
        "line_start/line_end are given; split sessions are read as the "
        "parts concatenated in part order) plus a citation header: "
        "{citation, session_id, part, line_range, total_lines, "
        "sha256_prefix, bytes}. Citation format: "
        "session:{user_id}/{session_id}#L{start}-L{end} (single file) or "
        "#p{N}L{start}-L{end} (split — N is the part holding the first "
        "returned line; line numbers are over the concatenated stream). "
        "sha256_prefix is the first 16 hex chars of that part file's sha256 "
        "(verifiable against the session_ingests index row)."
    ),
)
def sessions_get(
    session_id: str,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
    ctx: Context = None,
) -> dict:
    """Read the user's stored transcript (or a line slice of it).

    Args:
        session_id: The session id as ingested (bare id, or a
            {id}.partN part id to read a single part).
        line_start: Optional 1-based first line (inclusive).
        line_end: Optional 1-based last line (inclusive; clamped to the
            end of the transcript).

    Returns:
        {user_id, session_id, citation, part, line_range, total_lines,
        sha256_prefix, bytes, content}.
    """
    params: dict = {}
    if line_start is not None:
        params["line_start"] = int(line_start)
    if line_end is not None:
        params["line_end"] = int(line_end)
    return _request(
        "GET", f"/api/sessions/{session_id}", ctx, params=params or None
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP sessions server over SSE transport (0.0.0.0:8000, path /sse)."""
    logging.basicConfig(level=logging.INFO)
    logger.info(
        "Starting mcp_sessions, skill-runner=%s, fallback_key=%s, rate_limit=%d/h",
        SKILL_RUNNER_URL,
        "configured" if SESSIONS_USER_KEY else "MISSING (direct calls will 401)",
        RATE_LIMIT_PER_HOUR,
    )
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
