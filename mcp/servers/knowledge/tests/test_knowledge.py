#!/usr/bin/env python3
"""Unit tests for the MCP Knowledge Server v2 (family KB, kb-todo.md K2-K7).

Focus: the `kb_` prefix code-gate (the security boundary for the global-`m`
KB key), friendly-name slugification, deterministic point IDs, the
manifest/superseded search filter, and chunking/pagination. No live Qdrant
or LiteLLM needed (pure helpers + mocked client for the tool path).

Run:  cd mcp/servers/knowledge && python3 -m pytest tests/ -q
"""

import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402
from server import (  # noqa: E402
    _chunk_markdown,
    _is_missing_collection,
    _kb_name,
    _manifest_id,
    _point_id,
    _search_filter,
    _truncate,
    _validate_collection,
)


# ---------------------------------------------------------------------------
# The `kb_` prefix gate — the boundary that keeps the global-`m` KB key
# from ever touching mem0_memories or any non-kb_ collection.
# ---------------------------------------------------------------------------


class TestPrefixGate:
    @pytest.mark.parametrize("name", [
        "kb_gaming", "kb_family", "kb_side_biz_blah",
        "kb_a", "kb_0", "kb_" + "a" * 60,
    ])
    def test_valid_names_accepted(self, name):
        assert _validate_collection(name) == name

    @pytest.mark.parametrize("name", [
        "mem0_memories",          # the memory collection — MUST be rejected
        "family_kb",              # the old 384-dim collection
        "kb", "kb_",              # bare prefix
        "KB_gaming", "Kb_gaming",  # wrong case
        "kb-gaming", "kb gaming", "kb.gaming",
        "kb_../mem0",             # traversal attempt
        "kb_" + "a" * 61,         # too long
        "", None, 123,            # non-string / empty
    ])
    def test_invalid_names_rejected(self, name):
        with pytest.raises(ValueError):
            _validate_collection(name)

    def test_gate_is_structural(self):
        """Every collection name the server can produce must pass the gate.
        _kb_name is the only name generator; fuzz it with adversarial
        inputs and require the output to always be a valid kb_ name."""
        adversarial = [
            "mem0_memories", "../mem0_memories", "mem0_memories; DROP TABLE",
            "Side Biz Project Blah", "kb_gaming", "KB_GAMING",
            "gaming!!", "  spaced  name  ", "a" * 200, "___",
        ]
        for raw in adversarial:
            try:
                name = _kb_name(raw)
            except ValueError:
                continue  # rejection is also gate-correct behavior
            assert _validate_collection(name) == name  # no exception
            assert name.startswith("kb_")
            assert name != "mem0_memories"

    def test_no_friendly_name_can_target_mem0_memories(self):
        """Even if the LLM passes the memory collection name as the KB,
        it slugifies to a kb_-prefixed name — never mem0_memories."""
        assert _kb_name("mem0_memories") == "kb_mem0_memories"


class TestSlugify:
    @pytest.mark.parametrize("friendly,expected", [
        ("Side Biz Project Blah", "kb_side_biz_project_blah"),
        ("Gaming", "kb_gaming"),
        ("kb_gaming", "kb_gaming"),          # no double-prefix
        ("KB_GAMING", "kb_gaming"),          # case-folded
        ("Gaming! & Fun", "kb_gaming_fun"),
        ("  family  ", "kb_family"),
    ])
    def test_slugify(self, friendly, expected):
        assert _kb_name(friendly) == expected

    def test_collapse_and_strip_underscores(self):
        assert _kb_name("__gaming___") == "kb_gaming"

    def test_truncated_to_40_chars(self):
        name = _kb_name("a" * 100)
        assert len(name) <= 43  # kb_ + 40

    @pytest.mark.parametrize("bad", ["", "   ", "!!!", "---", None])
    def test_unusable_names_rejected(self, bad):
        with pytest.raises(ValueError):
            _kb_name(bad)

    def test_adversarial_names_never_escape_prefix(self):
        """No friendly name can produce a collection without the kb_ prefix.
        (The global-`m` key + this gate is the isolation boundary.)"""
        adversarial = [
            "mem0_memories", "../mem0", "..", "kb_../mem0",
            "mem0; DROP TABLE x", "a" * 500, "KB_" + "a" * 90,
            "mem0_memories\n", " kb_family",
        ]
        pat = re.compile(r"^kb_[a-z0-9_]{1,60}$")
        for name in adversarial:
            try:
                out = _kb_name(name)
            except ValueError:
                continue
            assert pat.fullmatch(out), f"{name!r} -> {out!r}"


# ---------------------------------------------------------------------------
# Deterministic point IDs (idempotent re-ingest, exact deletes)
# ---------------------------------------------------------------------------


class TestPointIds:
    def test_point_id_deterministic(self):
        a = _point_id("/data/media/x.pdf", 3)
        b = _point_id("/data/media/x.pdf", 3)
        c = _point_id("/data/media/x.pdf", 1)
        assert a == b and isinstance(a, uuid.UUID)
        assert a != c

    def test_point_id_unique_per_chunk(self):
        ids = {_point_id("/data/media/x.pdf", i) for i in range(50)}
        assert len(ids) == 50

    def test_point_id_distinct_sources(self):
        assert _point_id("/a.md", 0) != _point_id("/b.md", 0)

    def test_manifest_id_stable_and_distinct(self):
        assert _manifest_id("kb_gaming") == _manifest_id("kb_gaming")
        assert _manifest_id("kb_gaming") != _manifest_id("kb_family")
        # Manifest IDs must never collide with fact/doc point IDs.
        assert _manifest_id("kb_gaming") != _point_id("manifest:kb_gaming", 0)


# ---------------------------------------------------------------------------
# Search filter: manifest + superseded points are excluded from results
# ---------------------------------------------------------------------------


class TestSearchFilter:
    def test_excludes_manifest_and_superseded(self):
        f = _search_filter()
        assert len(f.must_not) == 2
        # (1) exclude kind == manifest
        cond = f.must_not[0]
        assert cond.key == "kind"
        assert cond.match.value == "manifest"
        # (2) exclude points whose superseded_by is NOT empty:
        # nested must_not[ is_empty(superseded_by) ]
        inner = f.must_not[1].must_not[0]
        assert inner.is_empty.key == "superseded_by"


# ---------------------------------------------------------------------------
# Chunking + pagination
# ---------------------------------------------------------------------------


class TestChunking:
    def test_page_ranges_and_indices(self):
        md = (
            "<!-- page 1 -->\n" + "alpha " * 500 + "\n\n"
            "<!-- page 2 -->\n" + "beta " * 500 + "\n\n"
            "<!-- page 3 -->\n" + "gamma " * 500
        )
        chunks = _chunk_markdown(md)
        assert len(chunks) >= 2
        assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))
        pages = [c["page_range"] for c in chunks if c["page_range"]]
        assert pages and all(p[0] <= p[1] for p in pages)
        # page 1 content must appear in some chunk with a page_range
        # covering page 1.
        assert any(1 in (p or []) for p in pages)

    def test_no_page_markers_gives_none_range(self):
        chunks = _chunk_markdown("just a short fact without pages")
        assert len(chunks) == 1
        assert chunks[0]["page_range"] is None

    def test_empty_input(self):
        assert _chunk_markdown("") == []
        assert _chunk_markdown("   \n\n  ") == []

    def test_overlap_present_for_long_docs(self):
        md = "\n\n".join(f"paragraph {i} " + "word " * 200 for i in range(20))
        chunks = _chunk_markdown(md)
        assert len(chunks) >= 2
        # 15% overlap: consecutive chunks share some text.
        shared = set(chunks[0]["text"].split()) & set(chunks[1]["text"].split())
        assert shared, "expected overlapping tokens between consecutive chunks"


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_truncate_short_unchanged(self):
        assert _truncate("hello", 10) == "hello"

    def test_truncate_long(self):
        t = _truncate("word " * 100, 40)
        assert len(t) <= 41  # + ellipsis
        assert t.endswith("…")

    def test_truncate_empty(self):
        assert _truncate("", 40) == ""

    def test_as_id(self):
        assert server._as_id(42) == 42
        assert server._as_id("42") == 42
        u = uuid.uuid4()
        assert server._as_id(str(u)) == u

    def test_missing_collection_detection(self):
        from qdrant_client.http.exceptions import UnexpectedResponse
        assert _is_missing_collection(UnexpectedResponse(404, "nf", b"{}", {}))
        assert not _is_missing_collection(UnexpectedResponse(500, "x", b"{}", {}))
        assert not _is_missing_collection(ValueError("404"))


# ---------------------------------------------------------------------------
# Tool-level (mocked Qdrant client): the kb_ gate holds on the live path
# ---------------------------------------------------------------------------


class TestToolLevelGate:
    @pytest.mark.asyncio
    async def test_kb_search_never_targets_non_kb_collection(self):
        """kb_search(kb='mem0_memories') must resolve to kb_mem0_memories —
        the collection passed to Qdrant always carries the kb_ prefix."""
        fake_point = MagicMock()
        fake_point.id = str(uuid.uuid4())
        fake_point.score = 0.9
        fake_point.payload = {"kind": "doc", "text": "hit", "source": "s"}
        fake_resp = MagicMock()
        fake_resp.points = [fake_point]

        fake_client = MagicMock()
        gc = MagicMock()
        c = MagicMock(); c.name = "kb_mem0_memories"
        gc.collections = [c]
        fake_client.get_collections = AsyncMock(return_value=gc)
        fake_client.query_points = AsyncMock(return_value=fake_resp)
        fake_client.close = AsyncMock()

        with patch.object(server, "_client", return_value=fake_client), \
             patch.object(server, "_embed",
                          AsyncMock(return_value=[[0.0] * 768])):
            out = await server.kb_search("test query", kb="mem0_memories")

        called_with = fake_client.query_points.await_args.kwargs
        col = called_with.get("collection_name")
        assert col == "kb_mem0_memories"
        assert col != "mem0_memories"
        assert out["results"][0]["snippet"] == "hit"

    @pytest.mark.asyncio
    async def test_kb_search_omitted_kb_scrolls_only_kb_collections(self):
        """With no kb arg, only kb_* collections are searched."""
        names = ["mem0_memories", "kb_gaming", "kb_family", "other_col"]
        fake_client = MagicMock()

        def _get_collections():
            r = MagicMock()
            r.collections = []
            for n in names:  # `name=` kwarg is a MagicMock repr pitfall
                c = MagicMock()
                c.name = n
                r.collections.append(c)
            return r

        fake_client.get_collections = AsyncMock(return_value=_get_collections())
        fake_client.query_points = AsyncMock(return_value=MagicMock(points=[]))
        fake_client.scroll = AsyncMock(return_value=([], None))
        fake_client.close = AsyncMock()

        with patch.object(server, "_client", return_value=fake_client), \
             patch.object(server, "_embed",
                          AsyncMock(return_value=[[0.0] * 768])):
            await server.kb_search("anything")

        searched = [c.kwargs.get("collection_name")
                    for c in fake_client.query_points.await_args_list]
        assert searched == ["kb_family", "kb_gaming"]
    @pytest.mark.asyncio
    async def test_kb_overview_counts_distinct_sources(self):
        """kb_overview counts distinct source documents, not points."""
        from types import SimpleNamespace
        pts = [
            SimpleNamespace(id=1, payload={"kind": "manifest", "source": "manifest",
                                           "text": "Gaming KB", "ingested_at": "2026-01-01T00:00:00+00:00"}),
            SimpleNamespace(id=2, payload={"kind": "doc", "source": "/data/a.pdf",
                                           "text": "x", "ingested_at": "2026-08-01T00:00:00+00:00"}),
            SimpleNamespace(id=3, payload={"kind": "doc", "source": "/data/a.pdf",
                                           "text": "y", "ingested_at": "2026-08-01T00:00:00+00:00"}),
            SimpleNamespace(id=4, payload={"kind": "doc", "source": "/data/b.txt",
                                           "text": "z", "ingested_at": "2026-08-02T00:00:00+00:00"}),
        ]
        fake_client = MagicMock()
        gc = MagicMock(); gc.collections = [MagicMock(name="kb_gaming")]
        # `name=` is a MagicMock repr kwarg — set attribute post-construction.
        gc.collections[0].name = "kb_gaming"
        fake_client.get_collections = AsyncMock(return_value=gc)
        fake_client.get_collection = AsyncMock(return_value=MagicMock(points_count=4))
        fake_client.scroll = AsyncMock(return_value=(pts, None))
        fake_client.close = AsyncMock()
        with patch.object(server, "_client", return_value=fake_client):
            out = await server.kb_overview()
        kb = out["kbs"][0]
        assert kb["documents"] == 2      # distinct sources, not 3 points
        assert kb["chunks"] == 3
        assert kb["points"] == 4
        assert kb["description"] == "Gaming KB"

    @pytest.mark.asyncio
    async def test_kb_recent_changes_with_index(self):
        """order_by fast path: only points within the window, newest first."""
        from types import SimpleNamespace
        now = "2026-08-29T00:00:00+00:00"
        old = "2026-01-01T00:00:00+00:00"
        pts = [
            SimpleNamespace(id=1, payload={"kind": "doc", "source": "a", "ingested_at": now}),
            SimpleNamespace(id=2, payload={"kind": "doc", "source": "b", "ingested_at": old}),
            SimpleNamespace(id=3, payload={"kind": "manifest", "ingested_at": now}),
        ]
        fake_client = MagicMock()
        gc = MagicMock(); gc.collections = [MagicMock()]
        gc.collections[0].name = "kb_family"
        fake_client.get_collections = AsyncMock(return_value=gc)
        fake_client.scroll = AsyncMock(return_value=(pts, None))
        fake_client.close = AsyncMock()
        with patch.object(server, "_client", return_value=fake_client):
            out = await server.kb_recent_changes(days=7)
        assert [c["id"] for c in out["changes"]] == ["1"]
        assert "order_by" in fake_client.scroll.await_args.kwargs

    @pytest.mark.asyncio
    async def test_kb_recent_changes_fallback_without_index(self):
        """Pre-migration collections have no ingested_at index: order_by
        fails and the tool must fall back to an unsorted scroll."""
        from types import SimpleNamespace
        now = "2026-08-29T00:00:00+00:00"
        pts = [
            SimpleNamespace(id=1, payload={"kind": "doc", "source": "a", "ingested_at": now}),
            SimpleNamespace(id=2, payload={"kind": "manifest", "ingested_at": now}),
        ]

        async def _scroll(*a, **kw):
            if "order_by" in kw:
                raise Exception("No range index for `order_by` key: `ingested_at`")
            return (pts, None)

        fake_client = MagicMock()
        gc = MagicMock(); gc.collections = [MagicMock()]
        gc.collections[0].name = "kb_family"
        fake_client.get_collections = AsyncMock(return_value=gc)
        fake_client.scroll = AsyncMock(side_effect=_scroll)
        fake_client.close = AsyncMock()
        with patch.object(server, "_client", return_value=fake_client):
            out = await server.kb_recent_changes(days=7)
        assert [c["id"] for c in out["changes"]] == ["1"]
        assert fake_client.scroll.await_count == 2  # failed + fallback

    @pytest.mark.asyncio
    async def test_keyword_search_does_not_use_order_by(self):
        """_keyword_search must not require a payload index (plain scroll)."""
        from types import SimpleNamespace
        pts = [SimpleNamespace(id=1, payload={"kind": "doc", "source": "a",
                                              "text": "guitar chords here"})]
        fake_client = MagicMock()
        fake_client.scroll = AsyncMock(return_value=(pts, None))
        hits = await server._keyword_search(fake_client, ["kb_guitar"], "guitar chords", 5)
        assert len(hits) == 1
        assert "order_by" not in fake_client.scroll.await_args.kwargs

    @pytest.mark.asyncio
    async def test_kb_search_missing_kb_returns_note_not_error(self):
        """kb='nonexistent' must not raise a raw 404 — friendly note."""
        fake_client = MagicMock()
        gc = MagicMock()
        c = MagicMock(); c.name = "kb_family"
        gc.collections = [c]
        fake_client.get_collections = AsyncMock(return_value=gc)
        fake_client.close = AsyncMock()
        with patch.object(server, "_client", return_value=fake_client), \
             patch.object(server, "_embed",
                          AsyncMock(return_value=[[0.0] * 768])):
            out = await server.kb_search("anything", kb="mem0_memories")
        assert out["results"] == []
        assert "does not exist" in out["note"]
        # query_points must never have been called (no 404 raised).
        assert not fake_client.query_points.called
