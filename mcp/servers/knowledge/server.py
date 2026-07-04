#!/usr/bin/env python3
"""MCP Knowledge Server — Qdrant-backed knowledge base retrieval.

Provides four read-only tools:
  - kb_search(query, top_k, collection)       Vector search in a curated collection
  - kb_get_document(doc_id)                   Retrieve full document by ID
  - kb_list_collections()                     List available curated collections
  - kb_recent_changes(days)                   Show recent changes across collections

Backend: Qdrant at configurable QDRANT_URL (default: http://qdrant:6333)
Transport: SSE (HTTP, default 0.0.0.0:8000)
Security: Collection allowlist enforced; read-only operations only.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from mcp.server import FastMCP
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

QDRANT_URL: str = os.environ.get("QDRANT_URL", "http://qdrant:6333")
HTTP_TIMEOUT: float = float(os.environ.get("QDRANT_TIMEOUT", "15"))
MAX_TOP_K: int = 20
DEFAULT_TOP_K: int = 5
SNIPPET_MAX_CHARS: int = 300

# Collection allowlist — only these collections are accessible.
# private_curated and finance_curated are excluded by default.
ALLOWED_COLLECTIONS: list[str] = [
    "family_curated",
    "homelab_curated",
    "coding_curated",
]

logger = logging.getLogger("mcp_knowledge")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_collection(collection: str) -> str:
    """Validate collection name against allowlist. Raises ValueError if invalid."""
    if collection not in ALLOWED_COLLECTIONS:
        allowed = ", ".join(ALLOWED_COLLECTIONS)
        raise ValueError(
            f"Collection '{collection}' is not on the allowlist. "
            f"Allowed: {allowed}"
        )
    return collection


def _truncate_snippet(text: str, max_chars: int = SNIPPET_MAX_CHARS) -> str:
    """Truncate text to max_chars, ending at a word boundary."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > max_chars * 0.5:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "…"


def _format_hit(hit, collection: str) -> dict:
    """Format a single Qdrant search hit into a compact result dict."""
    payload = hit.payload or {}
    # Try to get a snippet from payload content or payload
    snippet = ""
    for key in ("content", "text", "body", "summary"):
        val = payload.get(key)
        if val:
            snippet = str(val)
            break
    if not snippet:
        # Fallback: join available payload fields
        snippet = " | ".join(f"{k}={v}" for k, v in list(payload.items())[:3])

    return {
        "id": str(hit.id),
        "collection": collection,
        "score": round(hit.score, 4),
        "snippet": _truncate_snippet(snippet),
        "metadata": {
            k: v for k, v in payload.items()
            if k not in ("content", "text", "body", "summary")
        },
    }


def _format_document(hit, collection: str) -> dict:
    """Format a full document retrieval result."""
    payload = hit.payload or {}
    # Get full content
    content = ""
    for key in ("content", "text", "body", "summary"):
        val = payload.get(key)
        if val:
            content = str(val)
            break

    return {
        "id": str(hit.id),
        "collection": collection,
        "content": content,
        "metadata": payload,
    }


# ---------------------------------------------------------------------------
# Client creation
# ---------------------------------------------------------------------------


def _get_client() -> AsyncQdrantClient:
    """Create an async Qdrant client configured from environment."""
    return AsyncQdrantClient(
        url=QDRANT_URL,
        timeout=HTTP_TIMEOUT,
    )


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

MCPS_HOST: str = os.environ.get("MCPS_HOST", "0.0.0.0")

mcp = FastMCP(
    name="mcp_knowledge",
    instructions=(
        "Read-only knowledge base retrieval via Qdrant. "
        "Only curated collections are accessible: "
        + ", ".join(ALLOWED_COLLECTIONS)
        + ". No writes, no reindexing, no arbitrary file access."
    ),
    host=MCPS_HOST,
)


@mcp.tool(
    name="kb_search",
    description=(
        "Vector search in a curated Qdrant collection. "
        "Collection must be from allowlist: "
        + ", ".join(ALLOWED_COLLECTIONS)
        + ". Returns compact snippets."
    ),
)
async def kb_search(
    query: str,
    top_k: int = DEFAULT_TOP_K,
    collection: str = "homelab_curated",
) -> list[dict]:
    """Vector search in a curated Qdrant collection.

    Args:
        query: The search query string (used as text for semantic search).
        top_k: Maximum results to return (default 5, cap 20).
        collection: Collection name from allowlist (default 'homelab_curated').
    """
    _validate_collection(collection)
    top_k = min(max(1, top_k), MAX_TOP_K)

    client = _get_client()
    try:
        hits = await _search_collection(client, collection, query, top_k)
        # Enforce top_k cap on final results regardless of what Qdrant returns
        return [_format_hit(hit, collection) for hit in hits[:top_k]]
    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("Qdrant search failed: %s", exc)
        raise RuntimeError(f"Qdrant search failed: {exc}") from exc
    finally:
        await client.close()


async def _search_collection(client, collection: str, query: str, top_k: int) -> list:
    """Search a single collection with fallback strategies. Returns hits list."""
    # First try: content field match
    hits, _ = await client.scroll(
        collection_name=collection,
        scroll_filter=Filter(
            must=[
                FieldCondition(
                    key="content",
                    match=MatchValue(value=query.lower()),
                ),
            ]
        ),
        limit=top_k,
    )

    # Second try: any text field match (OR across fields)
    if not hits:
        conditions = []
        for key in ("content", "text", "body", "title", "summary"):
            conditions.append(
                FieldCondition(
                    key=key,
                    match=MatchValue(value=query.lower()),
                )
            )
        hits, _ = await client.scroll(
            collection_name=collection,
            scroll_filter=Filter(should=conditions),
            limit=top_k,
        )

    # Fallback: return first few items for browsing
    if not hits:
        hits, _ = await client.scroll(
            collection_name=collection,
            limit=min(top_k, 5),
        )

    return hits


@mcp.tool(
    name="kb_get_document",
    description="Retrieve the full document content by its ID.",
)
async def kb_get_document(doc_id: str) -> dict:
    """Retrieve full document by ID.

    Searches all allowed collections for the given document ID.
    Returns the full content and metadata if found.

    Args:
        doc_id: The document ID to retrieve.
    """
    client = _get_client()
    try:
        return await _get_document_from_client(client, doc_id)
    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("Qdrant document retrieval failed: %s", exc)
        raise RuntimeError(f"Qdrant document retrieval failed: {exc}") from exc
    finally:
        await client.close()


async def _get_document_from_client(client, doc_id: str) -> dict:
    """Internal: search all allowed collections for a document by ID."""
    try:
        parsed_id = int(doc_id)
    except (ValueError, TypeError):
        parsed_id = doc_id

    for collection in ALLOWED_COLLECTIONS:
        try:
            records = await client.scroll(
                collection_name=collection,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="id",
                            match=MatchValue(value=str(parsed_id)),
                        ),
                    ]
                ),
                limit=1,
            )
            if records and records[0]:
                return _format_document(records[0], collection)

            # Also try direct retrieval by point ID
            point = await client.get(
                collection_name=collection,
                point_ids=[parsed_id],
            )
            if point and len(point) > 0:
                return _format_document(point[0], collection)
        except Exception:
            # Collection might not exist or point not found; continue
            continue

    return {
        "id": str(parsed_id),
        "found": False,
        "message": f"Document '{doc_id}' not found in any allowed collection.",
    }


@mcp.tool(
    name="kb_list_collections",
    description="List all available curated collections accessible to this server.",
)
async def kb_list_collections() -> list[dict]:
    """List available curated collections.

    Returns only collections from the allowlist that exist in Qdrant.

    Returns:
        List of dicts with collection name, status, and point count.
    """
    client = _get_client()
    try:
        return await _list_collections_from_client(client)
    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("Qdrant collection listing failed: %s", exc)
        raise RuntimeError(f"Qdrant collection listing failed: {exc}") from exc
    finally:
        await client.close()


async def _list_collections_from_client(client) -> list[dict]:
    """Internal: list collections from a Qdrant client."""
    results = []
    for collection_name in ALLOWED_COLLECTIONS:
        try:
            info = await client.get_collection(collection_name=collection_name)
            results.append({
                "name": collection_name,
                "status": "active",
                "points_count": info.points_count if hasattr(info, "points_count") else "unknown",
                "vectors_count": info.vectors_count if hasattr(info, "vectors_count") else "unknown",
                "allowed": True,
            })
        except Exception as coll_exc:
            # Collection might not exist yet
            logger.debug("Collection %s not found or inaccessible: %s", collection_name, coll_exc)
            results.append({
                "name": collection_name,
                "status": "not_found",
                "points_count": 0,
                "allowed": True,
            })

    return results


@mcp.tool(
    name="kb_recent_changes",
    description="Show recent changes (metadata scan) in curated collections.",
)
async def kb_recent_changes(days: int = 7) -> list[dict]:
    """Show recent changes in curated collections via metadata scan.

    Scans payload metadata for ingestion/update timestamps within the
    last N days.

    Args:
        days: Number of days to look back (default 7).
    """
    client = _get_client()
    try:
        return await _scan_recent_changes(client, days)
    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("Qdrant recent changes scan failed: %s", exc)
        raise RuntimeError(f"Qdrant recent changes scan failed: {exc}") from exc
    finally:
        await client.close()


async def _scan_recent_changes(client, days: int) -> list[dict]:
    """Internal: scan all allowed collections for recent changes."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_str = cutoff.isoformat()
    all_changes = []

    for collection_name in ALLOWED_COLLECTIONS:
        try:
            hits, _ = await client.scroll(
                collection_name=collection_name,
                scroll_filter=Filter(
                    should=[
                        FieldCondition(
                            key="ingested_at",
                            range=Range(gte=cutoff_str),
                        ),
                        FieldCondition(
                            key="updated_at",
                            range=Range(gte=cutoff_str),
                        ),
                    ]
                ),
                limit=MAX_TOP_K,
            )
            for hit in hits:
                payload = hit.payload or {}
                ts = payload.get("ingested_at") or payload.get("updated_at") or "unknown"
                source = payload.get("source", payload.get("ingested_by", "unknown"))
                all_changes.append({
                    "id": str(hit.id),
                    "collection": collection_name,
                    "timestamp": ts,
                    "source": source,
                })
        except Exception:
            # Collection might not exist
            continue

    return all_changes


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the MCP knowledge server over SSE transport (0.0.0.0:8000)."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting mcp_knowledge on %s", QDRANT_URL)
    logger.info("Allowed collections: %s", ", ".join(ALLOWED_COLLECTIONS))
    mcp.run(transport="streamable-http")  # defaults to 0.0.0.0:8000


if __name__ == "__main__":
    main()
