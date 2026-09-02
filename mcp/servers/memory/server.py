#!/usr/bin/env python3
"""MCP Memory Server — per-user long-term memory retrieval (Phase 11).

Thin client over skill-runner's SCOPED memory endpoints:

  - memory_search(query, top_k?)   Semantic search over the caller's own
                                    private + household memories.
  - memory_list(limit?)            List the caller's stored memories.

Backend: skill-runner (FastAPI, :8091) — ``POST /api/memory/search`` and
``POST /api/memory/list``. Both are user-key authenticated: the caller's
LiteLLM key is resolved by skill-runner's IdentityResolver to a user_id, and
results are scoped to THAT user (+ household). This MCP server therefore can
never return another user's memories — cross-user isolation is enforced
server-side, not here.

Identity threading: the caller's LiteLLM key (forwarded via the Authorization
header when the call routes through LiteLLM) is passed to skill-runner as
X-API-Key. When absent (e.g. pi connecting directly), the configured
MEMORY_USER_KEY is used — a SINGLE key that must be in skill-runner's
SKILL_RUNNER_API_KEY allow-list (exact-match semantics).

Transport: streamable-http (HTTP, default 0.0.0.0:8000)
"""

import os
import logging
from typing import Optional

import httpx
from mcp.server import FastMCP
from mcp.server.fastmcp import Context

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SKILL_RUNNER_URL: str = os.environ.get(
    "SKILL_RUNNER_URL", "http://skill-runner:8091"
).rstrip("/")
# Fallback identity key (SINGLE value — skill-runner exact-matches against its
# comma-split allow-list). Set to the user this deployment serves (e.g.
# Chuck's LiteLLM key for the pi-on-Mac deployment).
MEMORY_USER_KEY: str = os.environ.get("MEMORY_USER_KEY", "")
MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")
TIMEOUT_S: float = float(os.environ.get("MEMORY_TIMEOUT_S", "15"))

logger = logging.getLogger("mcp_memory")

# ---------------------------------------------------------------------------
# Identity threading (same pattern as mcp_skills)
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
    key = _caller_key(ctx) or (MEMORY_USER_KEY or None)
    h = {"Content-Type": "application/json"}
    if key:
        h["X-API-Key"] = key
    return h


def _post(path: str, payload: dict, ctx: Optional[Context]) -> dict:
    with httpx.Client(timeout=TIMEOUT_S) as client:
        r = client.post(f"{SKILL_RUNNER_URL}{path}", json=payload, headers=_headers(ctx))
    if r.status_code >= 400:
        raise RuntimeError(f"skill-runner {path} failed: {r.status_code} {r.text}")
    return r.json()


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="mcp_memory",
    instructions=(
        "Long-term memory for the authenticated user (Mem0 via skill-runner). "
        "memory_search(query) semantically searches the user's own stored "
        "memories (private + household); memory_list() lists stored memories. "
        "Use these to answer 'what do you know about me / what have I been "
        "doing recently' — combine with kb_search (mcp_knowledge) for the "
        "family knowledge base. Results are strictly per-user: you will never "
        "see another user's memories."
    ),
    host=MCPS_HOST,
)


@mcp.tool(
    name="memory_search",
    description=(
        "Semantic search over the authenticated user's long-term memories "
        "(private + household). Returns hits with id, text, score, source."
    ),
)
def memory_search(
    query: str,
    top_k: Optional[int] = None,
    ctx: Context = None,
) -> dict:
    """Search the user's stored memories.

    Args:
        query: Natural-language query (e.g. "what do you know about my car?").
        top_k: Max hits to return (1-20; default: server config, usually 6).

    Returns:
        {user_id, count, memories: [{id, text, score, source, metadata}]}.
    """
    payload: dict = {"query": query}
    if top_k is not None:
        payload["top_k"] = max(1, min(int(top_k), 20))
    return _post("/api/memory/search", payload, ctx)


@mcp.tool(
    name="memory_list",
    description=(
        "List the authenticated user's stored long-term memories (no query "
        "needed). Useful for 'what do you know about me?'"
    ),
)
def memory_list(
    limit: int = 20,
    ctx: Context = None,
) -> dict:
    """List the user's stored memories.

    Args:
        limit: Max memories to return (1-100; default 20).

    Returns:
        {user_id, count, memories: [{id, text, score, source, metadata}]}.
    """
    return _post("/api/memory/list", {"limit": max(1, min(int(limit), 100))}, ctx)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the MCP memory server over streamable-http transport (0.0.0.0:8000)."""
    logging.basicConfig(level=logging.INFO)
    logger.info(
        "Starting mcp_memory, skill-runner=%s, fallback_key=%s",
        SKILL_RUNNER_URL,
        "configured" if MEMORY_USER_KEY else "MISSING (direct calls will 403)",
    )
    mcp.run(transport="streamable-http")  # defaults to 0.0.0.0:8000


if __name__ == "__main__":
    main()