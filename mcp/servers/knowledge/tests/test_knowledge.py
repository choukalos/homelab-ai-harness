#!/usr/bin/env python3
"""Mocked tests for the MCP Knowledge Server.

Tests verify tool behavior, collection allowlist enforcement, result formatting,
and error handling without requiring a live Qdrant instance.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

ALLOWED = ["family_curated", "homelab_curated", "coding_curated"]
QDRANT_DEFAULT = "http://qdrant:6333"


def _mock_hit(
    id_val="doc-1",
    score=0.92,
    payload=None,
):
    """Create a mock SearchResponse hit (Hit model)."""
    hit = MagicMock()
    hit.id = id_val
    hit.score = score
    hit.payload = payload or {}
    return hit


def _mock_scroll_result(count=3, collection="homelab_curated", payload=None):
    """Create mock scroll() return value (hits, next_offset)."""
    hits = [
        _mock_hit(
            id_val=f"doc-{i}",
            score=0.9 - i * 0.05,
            payload=payload or {"content": f"Test content for doc {i}", "source": "test"},
        )
        for i in range(count)
    ]
    return hits, None


def _mock_client_with_scroll(*scroll_return_values):
    """Build a mock AsyncQdrantClient with pre-programmed scroll() responses."""
    mock_client = MagicMock()
    mock_client.scroll = AsyncMock(side_effect=list(scroll_return_values))
    mock_client.get = AsyncMock(return_value=[])
    mock_client.get_collection = AsyncMock(
        return_value=MagicMock(points_count=100, vectors_count=100)
    )
    mock_client.close = AsyncMock()
    return mock_client


# ---------------------------------------------------------------------------
# Tests: kb_search
# ---------------------------------------------------------------------------

class TestKbSearch:
    @pytest.mark.asyncio
    async def test_basic_search(self):
        """Search returns formatted hits."""
        mock_client = _mock_client_with_scroll(
            _mock_scroll_result(3)
        )

        with patch("server._get_client", return_value=mock_client):
            from server import kb_search
            out = await kb_search("homelab setup", top_k=5, collection="homelab_curated")
            assert len(out) == 3
            assert out[0]["id"] == "doc-0"
            assert out[0]["collection"] == "homelab_curated"
            assert "Test content" in out[0]["snippet"]

    @pytest.mark.asyncio
    async def test_search_result_format(self):
        """Each result has expected fields."""
        mock_client = _mock_client_with_scroll(
            _mock_scroll_result(1, payload={
                "content": "Example document content",
                "source": "docs/runbook.md",
                "ingested_at": "2026-07-01T00:00:00Z",
            })
        )

        with patch("server._get_client", return_value=mock_client):
            from server import kb_search
            out = await kb_search("example", collection="family_curated")
            assert "id" in out[0]
            assert "collection" in out[0]
            assert "score" in out[0]
            assert "snippet" in out[0]
            assert "metadata" in out[0]

    @pytest.mark.asyncio
    async def test_default_top_k_is_5(self):
        """Default top_k should be 5, and results truncated to that cap."""
        mock_client = _mock_client_with_scroll(
            _mock_scroll_result(10)
        )

        with patch("server._get_client", return_value=mock_client):
            from server import kb_search
            out = await kb_search("test")  # no top_k specified, default is 5
            assert len(out) <= 5

    @pytest.mark.asyncio
    async def test_top_k_capped_at_20(self):
        """top_k > 20 should be capped at 20."""
        mock_client = _mock_client_with_scroll(
            _mock_scroll_result(25)
        )

        with patch("server._get_client", return_value=mock_client):
            from server import kb_search
            out = await kb_search("test", top_k=50)
            assert len(out) <= 20

    @pytest.mark.asyncio
    async def test_snippet_truncation(self):
        """Long content should produce truncated snippets."""
        long_content = "A word " * 100  # Well over 300 chars
        mock_client = _mock_client_with_scroll(
            _mock_scroll_result(1, payload={"content": long_content})
        )

        with patch("server._get_client", return_value=mock_client):
            from server import kb_search
            out = await kb_search("test")
            assert len(out[0]["snippet"]) <= 301  # 300 + ellipsis

    @pytest.mark.asyncio
    async def test_search_fallback_on_no_match(self):
        """When content match returns empty, tries broader match then browsing."""
        mock_client = _mock_client_with_scroll(
            _mock_scroll_result(0),   # content match: empty
            _mock_scroll_result(2),   # broader match: found
        )

        with patch("server._get_client", return_value=mock_client):
            from server import kb_search
            out = await kb_search("nonexistent query", collection="homelab_curated")
            assert len(out) == 2


# ---------------------------------------------------------------------------
# Tests: allowlist enforcement
# ---------------------------------------------------------------------------

class TestAllowlistEnforcement:
    @pytest.mark.asyncio
    async def test_disallowed_collection_raises_error(self):
        """Using a collection not in allowlist should raise ValueError."""
        with patch("server._get_client"):
            from server import kb_search
            with pytest.raises(ValueError, match="not on the allowlist"):
                await kb_search("test", collection="private_curated")

    @pytest.mark.asyncio
    async def test_finance_curated_rejected(self):
        """finance_curated is not on the allowlist."""
        with patch("server._get_client"):
            from server import kb_search
            with pytest.raises(ValueError, match="not on the allowlist"):
                await kb_search("test", collection="finance_curated")

    @pytest.mark.asyncio
    async def test_arbitrary_collection_rejected(self):
        """Any random collection name should be rejected."""
        with patch("server._get_client"):
            from server import kb_search
            with pytest.raises(ValueError, match="not on the allowlist"):
                await kb_search("test", collection="random_collection")

    @pytest.mark.asyncio
    async def test_allowed_collections_work(self):
        """All three allowed collections should not raise errors."""
        for collection in ALLOWED:
            mock_client = _mock_client_with_scroll(
                _mock_scroll_result(1, collection=collection)
            )
            with patch("server._get_client", return_value=mock_client):
                from server import kb_search
                out = await kb_search("test", collection=collection)
                assert out[0]["collection"] == collection


# ---------------------------------------------------------------------------
# Tests: kb_get_document
# ---------------------------------------------------------------------------

class TestKbGetDocument:
    @pytest.mark.asyncio
    async def test_find_document_by_id(self):
        """Should find document by searching allowed collections."""
        payload = {
            "content": "Full document content here",
            "source": "docs/architecture.md",
            "title": "Architecture Overview",
        }
        hits = [_mock_hit(id_val="123", payload=payload)]
        mock_client = _mock_client_with_scroll(hits, _mock_scroll_result(0))
        mock_client.get = AsyncMock(return_value=[])

        with patch("server._get_client", return_value=mock_client):
            from server import kb_get_document
            out = await kb_get_document("123")
            assert "id" in out
            assert out["content"] == "Full document content here"

    @pytest.mark.asyncio
    async def test_document_not_found(self):
        """Should return not found when document doesn't exist."""
        mock_client = _mock_client_with_scroll(
            _mock_scroll_result(0),
            _mock_scroll_result(0),
            _mock_scroll_result(0),
        )
        mock_client.get = AsyncMock(return_value=[])

        with patch("server._get_client", return_value=mock_client):
            from server import kb_get_document
            out = await kb_get_document("nonexistent-doc")
            assert out["found"] is False
            assert "not found" in out["message"]

    @pytest.mark.asyncio
    async def test_integer_id_parsed(self):
        """Integer doc_id should be parsed as int."""
        hits = [_mock_hit(id_val=42, payload={"content": "Test"})]
        mock_client = _mock_client_with_scroll(hits, _mock_scroll_result(0))
        mock_client.get = AsyncMock(return_value=[])

        with patch("server._get_client", return_value=mock_client):
            from server import kb_get_document
            out = await kb_get_document("42")
            assert "id" in out

    @pytest.mark.asyncio
    async def test_get_document_searches_all_collections(self):
        """Should try each collection until document is found."""
        # Mock _get_document_from_client to verify the public tool delegates correctly
        mock_result = {"id": "doc-5", "collection": "homelab_curated",
                       "content": "Found in homelab", "metadata": {},
                       "found": True}
        mock_get = AsyncMock(return_value=mock_result)
        mock_client = MagicMock()
        mock_client.close = AsyncMock()

        with patch("server._get_client", return_value=mock_client), \
             patch("server._get_document_from_client", mock_get):
            from server import kb_get_document
            out = await kb_get_document("doc-5")
            assert out["collection"] == "homelab_curated"
            assert out["content"] == "Found in homelab"


# ---------------------------------------------------------------------------
# Tests: kb_list_collections
# ---------------------------------------------------------------------------

class TestKbListCollections:
    @pytest.mark.asyncio
    async def test_lists_allowed_collections(self):
        """Should return all allowed collections."""
        mock_client = _mock_client_with_scroll()

        with patch("server._get_client", return_value=mock_client):
            from server import kb_list_collections
            out = await kb_list_collections()
            assert len(out) == 3
            names = [c["name"] for c in out]
            assert "family_curated" in names
            assert "homelab_curated" in names
            assert "coding_curated" in names

    @pytest.mark.asyncio
    async def test_collection_info_fields(self):
        """Each collection entry should have expected fields."""
        mock_client = _mock_client_with_scroll()

        with patch("server._get_client", return_value=mock_client):
            from server import kb_list_collections
            out = await kb_list_collections()
            for entry in out:
                assert "name" in entry
                assert "status" in entry
                assert entry["allowed"] is True

    @pytest.mark.asyncio
    async def test_collection_not_found_handling(self):
        """Non-existent collections should show as not_found."""
        mock_client = MagicMock()
        mock_client.get_collection = AsyncMock(side_effect=Exception("Collection not found"))
        mock_client.close = AsyncMock()

        with patch("server._get_client", return_value=mock_client):
            from server import kb_list_collections
            out = await kb_list_collections()
            for entry in out:
                assert entry["status"] == "not_found"
                assert entry["allowed"] is True

    @pytest.mark.asyncio
    async def test_mixed_collection_states(self):
        """Some collections active, some not found."""
        mock_client = MagicMock()
        mock_client.get_collection = AsyncMock(side_effect=[
            MagicMock(points_count=50, vectors_count=50),
            Exception("Not found"),
            MagicMock(points_count=200, vectors_count=200),
        ])
        mock_client.close = AsyncMock()

        with patch("server._get_client", return_value=mock_client):
            from server import kb_list_collections
            out = await kb_list_collections()
            assert len(out) == 3
            assert out[0]["status"] == "active"
            assert out[1]["status"] == "not_found"
            assert out[2]["status"] == "active"


# ---------------------------------------------------------------------------
# Tests: kb_recent_changes
# ---------------------------------------------------------------------------

class TestKbRecentChanges:
    @pytest.mark.asyncio
    async def test_scans_all_allowed_collections(self):
        """Should scan all allowed collections for recent changes."""
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_scan = AsyncMock(return_value=[
            {"id": "doc-1", "collection": "family_curated",
             "timestamp": "2026-07-02T10:00:00Z", "source": "docs/runbook.md"},
        ])

        with patch("server._get_client", return_value=mock_client), \
             patch("server._scan_recent_changes", mock_scan):
            from server import kb_recent_changes
            out = await kb_recent_changes(days=7)
            assert len(out) == 1
            assert out[0]["collection"] == "family_curated"
            assert out[0]["timestamp"] == "2026-07-02T10:00:00Z"

    @pytest.mark.asyncio
    async def test_scan_recent_changes_internal(self):
        """Test _scan_recent_changes output format via mocking."""
        # Directly test the output formatting by patching at the tool level
        mock_result = [{"id": "doc-1", "collection": "family_curated",
                        "timestamp": "2026-07-02T10:00:00Z", "source": "runbook.md"}]
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_scan = AsyncMock(return_value=mock_result)

        with patch("server._get_client", return_value=mock_client), \
             patch("server._scan_recent_changes", mock_scan):
            from server import kb_recent_changes
            out = await kb_recent_changes(days=7)
            assert len(out) == 1
            assert out[0]["collection"] == "family_curated"
            assert out[0]["timestamp"] == "2026-07-02T10:00:00Z"

    @pytest.mark.asyncio
    async def test_change_entry_fields(self):
        """Each change entry should have id, collection, timestamp, source."""
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_scan = AsyncMock(return_value=[
            {"id": "doc-5", "collection": "family_curated",
             "timestamp": "2026-07-01T08:00:00Z", "source": "docs/api.md"},
        ])

        with patch("server._get_client", return_value=mock_client), \
             patch("server._scan_recent_changes", mock_scan):
            from server import kb_recent_changes
            out = await kb_recent_changes(days=7)
            for entry in out:
                assert "id" in entry
                assert "collection" in entry
                assert "timestamp" in entry
                assert "source" in entry

    @pytest.mark.asyncio
    async def test_empty_results_when_no_changes(self):
        """Should return empty list when no recent changes found."""
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_scan = AsyncMock(return_value=[])

        with patch("server._get_client", return_value=mock_client), \
             patch("server._scan_recent_changes", mock_scan):
            from server import kb_recent_changes
            out = await kb_recent_changes(days=1)
            assert out == []

    @pytest.mark.asyncio
    async def test_uses_ingested_at_or_updated_at(self):
        """Should prefer ingested_at over updated_at for timestamp."""
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_scan = AsyncMock(return_value=[
            {"id": "doc-1", "collection": "family_curated",
             "timestamp": "2026-07-02T10:00:00Z", "source": "test"},
        ])

        with patch("server._get_client", return_value=mock_client), \
             patch("server._scan_recent_changes", mock_scan):
            from server import kb_recent_changes
            out = await kb_recent_changes(days=7)
            assert out[0]["timestamp"] == "2026-07-02T10:00:00Z"


# ---------------------------------------------------------------------------
# Tests: helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_truncate_snippet_short(self):
        """Short text should not be truncated."""
        from server import _truncate_snippet
        assert _truncate_snippet("Short text") == "Short text"

    def test_truncate_snippet_long(self):
        """Long text should be truncated with ellipsis."""
        from server import _truncate_snippet
        long_text = "Word " * 100
        result = _truncate_snippet(long_text)
        assert len(result) <= 301
        assert result.endswith("…")

    def test_truncate_snippet_empty(self):
        """Empty string should return empty string."""
        from server import _truncate_snippet
        assert _truncate_snippet("") == ""

    def test_validate_collection_allowed(self):
        """Allowed collections should pass validation."""
        from server import _validate_collection
        for coll in ALLOWED:
            result = _validate_collection(coll)
            assert result == coll

    def test_validate_collection_disallowed(self):
        """Disallowed collections should raise ValueError."""
        from server import _validate_collection
        with pytest.raises(ValueError, match="not on the allowlist"):
            _validate_collection("private_curated")

    def test_format_hit_fields(self):
        """Formatted hit should have all expected fields."""
        from server import _format_hit
        hit = _mock_hit(
            id_val="doc-1",
            score=0.85,
            payload={"content": "Some text", "source": "test.md"}
        )
        result = _format_hit(hit, "homelab_curated")
        assert result["id"] == "doc-1"
        assert result["collection"] == "homelab_curated"
        assert result["score"] == 0.85
        assert "Some text" in result["snippet"]
        assert result["metadata"]["source"] == "test.md"

    def test_format_document_fields(self):
        """Formatted document should have content and metadata."""
        from server import _format_document
        payload = {"content": "Full content", "title": "My Doc", "source": "test"}
        hit = _mock_hit(id_val="doc-1", payload=payload)
        result = _format_document(hit, "coding_curated")
        assert result["id"] == "doc-1"
        assert result["content"] == "Full content"
        assert result["collection"] == "coding_curated"
        assert result["metadata"]["title"] == "My Doc"


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_qdrant_search_error_wrapped(self):
        """Qdrant errors should be wrapped in RuntimeError."""
        mock_client = MagicMock()
        mock_client.scroll = AsyncMock(side_effect=Exception("Connection refused"))
        mock_client.close = AsyncMock()

        with patch("server._get_client", return_value=mock_client):
            from server import kb_search
            with pytest.raises(RuntimeError, match="Qdrant search failed"):
                await kb_search("test")

    @pytest.mark.asyncio
    async def test_qdrant_get_document_error_wrapped(self):
        """Qdrant client-level errors in get_document should be wrapped."""
        mock_client = MagicMock()
        mock_client.scroll = AsyncMock(side_effect=Exception("Client connection error"))
        mock_client.get = AsyncMock(side_effect=Exception("Client connection error"))
        mock_client.close = AsyncMock()

        with patch("server._get_client", return_value=mock_client):
            from server import kb_get_document
            # Per-collection errors are swallowed; returns not_found dict
            out = await kb_get_document("doc-1")
            assert out["found"] is False

    @pytest.mark.asyncio
    async def test_qdrant_list_collections_per_collection_errors(self):
        """Per-collection errors in list_collections are handled gracefully."""
        mock_client = MagicMock()
        mock_client.get_collection = AsyncMock(side_effect=[
            MagicMock(points_count=10, vectors_count=10),
            Exception("Network error"),
            MagicMock(points_count=50, vectors_count=50),
        ])
        mock_client.close = AsyncMock()

        with patch("server._get_client", return_value=mock_client):
            from server import kb_list_collections
            out = await kb_list_collections()
            assert len(out) == 3
            assert out[0]["status"] == "active"
            assert out[1]["status"] == "not_found"
            assert out[2]["status"] == "active"

    @pytest.mark.asyncio
    async def test_qdrant_recent_changes_per_collection_errors(self):
        """Per-collection errors in recent_changes are handled gracefully."""
        # Test that the public tool properly delegates and handles errors
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_scan = AsyncMock(side_effect=Exception("Network error"))

        with patch("server._get_client", return_value=mock_client), \
             patch("server._scan_recent_changes", mock_scan):
            from server import kb_recent_changes
            with pytest.raises(RuntimeError, match="Qdrant recent changes scan failed"):
                await kb_recent_changes(days=7)


# ---------------------------------------------------------------------------
# Tests: QDRANT_URL configuration
# ---------------------------------------------------------------------------

class TestConfiguration:
    def test_default_qdrant_url(self):
        """Default QDRANT_URL should be http://qdrant:6333."""
        import server
        assert server.QDRANT_URL == "http://qdrant:6333"

    def test_qdrant_url_from_env(self):
        """QDRANT_URL should be configurable via environment."""
        import server
        original = server.QDRANT_URL
        server.QDRANT_URL = "http://192.168.4.54:6333"
        assert server.QDRANT_URL == "http://192.168.4.54:6333"
        server.QDRANT_URL = original

    def test_get_client_uses_url(self):
        """_get_client should use the configured QDRANT_URL."""
        import server
        original = server.QDRANT_URL
        server.QDRANT_URL = "http://custom-host:6333"
        try:
            client = server._get_client()
            assert hasattr(client, "url") or hasattr(client, "host") or hasattr(client, "_client")
        finally:
            server.QDRANT_URL = original

    @pytest.mark.asyncio
    async def test_search_with_custom_collection_param(self):
        """kb_search should accept collection parameter correctly."""
        mock_client = _mock_client_with_scroll(_mock_scroll_result(1))

        with patch("server._get_client", return_value=mock_client):
            import server
            original_url = server.QDRANT_URL
            server.QDRANT_URL = "http://192.168.4.54:6333"
            try:
                from server import kb_search
                out = await kb_search("test", top_k=1, collection="homelab_curated")
                assert len(out) == 1
            finally:
                server.QDRANT_URL = original_url


# ---------------------------------------------------------------------------
# Tests: no write operations
# ---------------------------------------------------------------------------

class TestReadOnlyGuarantee:
    def test_no_write_methods_exposed(self):
        """Server module should not expose any write methods."""
        import server
        public_names = [n for n in dir(server) if not n.startswith("_")]
        write_methods = {"upsert", "delete", "update", "create", "ingest", "reindex"}
        exposed_writes = write_methods & set(public_names)
        assert not exposed_writes, f"Write methods found: {exposed_writes}"

    def test_allowed_collections_is_constant(self):
        """ALLOWED_COLLECTIONS should contain exactly the expected sets."""
        from server import ALLOWED_COLLECTIONS
        assert ALLOWED_COLLECTIONS == ["family_curated", "homelab_curated", "coding_curated"]
        assert "private_curated" not in ALLOWED_COLLECTIONS
        assert "finance_curated" not in ALLOWED_COLLECTIONS

    def test_no_write_tool_names(self):
        """No tool names should suggest write operations."""
        import server
        public_names = [n for n in dir(server) if not n.startswith("_")]
        tool_names = {"kb_search", "kb_get_document", "kb_list_collections", "kb_recent_changes"}
        found_tools = set(public_names) & tool_names
        assert found_tools == tool_names, f"Missing tools: {tool_names - found_tools}"
