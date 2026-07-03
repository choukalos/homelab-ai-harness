#!/usr/bin/env python3
"""Mocked tests for the MCP Search Server.

Tests verify tool behavior, result formatting, limits, and error handling
without requiring a live SearXNG instance.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import Request, Response


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SEARXNG_DEFAULT = "http://searxng:8080"


def _mock_response(results=None, status_code=200):
    """Create a mock SearXNG JSON response."""
    if results is None:
        results = []
    return Response(
        status_code,
        json={"results": results, "number_of_results": len(results)},
        request=Request("GET", SEARXNG_DEFAULT + "/search"),
    )


def _sample_result(
    title="Test Page",
    url="https://example.com/test",
    content="A short description of the page.",
) -> dict:
    return {"title": title, "url": url, "content": content}


def _mock_client(resp):
    """Build a mock AsyncClient that returns *resp* from .get() as a coroutine."""
    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


# ---------------------------------------------------------------------------
# Tests: search_web
# ---------------------------------------------------------------------------

class TestSearchWeb:
    @pytest.mark.asyncio
    async def test_basic_search(self):
        results = [_sample_result(title=f"Result {i}") for i in range(3)]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_web
            out = await search_web("test query", max_results=5)
            assert len(out) == 3
            assert out[0]["title"] == "Result 0"
            assert out[0]["url"] == "https://example.com/test"

    @pytest.mark.asyncio
    async def test_max_results_cap(self):
        """Results should be capped at 20 even if max_results > 20."""
        results = [_sample_result(title=f"Result {i}") for i in range(25)]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_web
            out = await search_web("test", max_results=50)
            assert len(out) <= 20

    @pytest.mark.asyncio
    async def test_snippet_truncation(self):
        """Long snippets should be truncated to ~200 chars."""
        long_content = "A " * 100  # 200+ chars
        results = [_sample_result(content=long_content)]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_web
            out = await search_web("test")
            assert len(out[0]["snippet"]) <= 201  # 200 + ellipsis char

    @pytest.mark.asyncio
    async def test_default_max_results_is_5(self):
        results = [_sample_result(title=f"Result {i}") for i in range(10)]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_web
            out = await search_web("test")  # no max_results specified
            assert len(out) == 5


# ---------------------------------------------------------------------------
# Tests: search_recent
# ---------------------------------------------------------------------------

class TestSearchRecent:
    @pytest.mark.asyncio
    async def test_day_mapping(self):
        """1 day should map to 'day' time_range."""
        results = [_sample_result()]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_recent
            await search_recent("test", days=1, max_results=1)
            call_kwargs = mock_client.get.call_args.kwargs
            assert call_kwargs["params"]["time_range"] == "day"

    @pytest.mark.asyncio
    async def test_week_mapping(self):
        """7 days should map to 'week' time_range."""
        results = [_sample_result()]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_recent
            await search_recent("test", days=7, max_results=1)
            call_kwargs = mock_client.get.call_args.kwargs
            assert call_kwargs["params"]["time_range"] == "week"

    @pytest.mark.asyncio
    async def test_month_mapping(self):
        """31 days should map to 'month' time_range."""
        results = [_sample_result()]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_recent
            await search_recent("test", days=31, max_results=1)
            call_kwargs = mock_client.get.call_args.kwargs
            assert call_kwargs["params"]["time_range"] == "month"

    @pytest.mark.asyncio
    async def test_year_mapping(self):
        """More than 31 days should map to 'year' time_range."""
        results = [_sample_result()]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_recent
            await search_recent("test", days=60, max_results=1)
            call_kwargs = mock_client.get.call_args.kwargs
            assert call_kwargs["params"]["time_range"] == "year"

    @pytest.mark.asyncio
    async def test_uses_general_category(self):
        """Recent search should use 'general' category."""
        results = [_sample_result()]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_recent
            await search_recent("test", days=7, max_results=1)
            call_kwargs = mock_client.get.call_args.kwargs
            assert call_kwargs["params"]["categories"] == "general"


# ---------------------------------------------------------------------------
# Tests: search_news
# ---------------------------------------------------------------------------

class TestSearchNews:
    @pytest.mark.asyncio
    async def test_news_category(self):
        """News search should use 'news' category."""
        results = [_sample_result(title="Breaking News")]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_news
            out = await search_news("technology", max_results=3)
            call_kwargs = mock_client.get.call_args.kwargs
            assert call_kwargs["params"]["categories"] == "news"
            assert len(out) == 1
            assert out[0]["title"] == "Breaking News"

    @pytest.mark.asyncio
    async def test_news_no_time_range(self):
        """News search should not set a time_range."""
        results = [_sample_result()]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_news
            await search_news("test", max_results=1)
            call_kwargs = mock_client.get.call_args.kwargs
            assert "time_range" not in call_kwargs["params"]


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_http_error_raises_runtime_error(self):
        """HTTP errors should be wrapped in RuntimeError."""
        err_resp = Response(
            500,
            json={"error": "Internal Server Error"},
            request=Request("GET", SEARXNG_DEFAULT + "/search"),
        )
        mock_client = _mock_client(err_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_web
            with pytest.raises(RuntimeError, match="SearXNG request failed"):
                await search_web("test")

    @pytest.mark.asyncio
    async def test_connection_error_raises_runtime_error(self):
        """Connection errors should be wrapped in RuntimeError."""
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_web
            with pytest.raises(RuntimeError, match="SearXNG request failed"):
                await search_web("test")

    @pytest.mark.asyncio
    async def test_timeout_error_raises_runtime_error(self):
        """Timeout errors should be wrapped in RuntimeError."""
        mock_client = MagicMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Request timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from server import search_web
            with pytest.raises(RuntimeError, match="SearXNG request failed"):
                await search_web("test")


# ---------------------------------------------------------------------------
# Tests: HTML cleaning
# ---------------------------------------------------------------------------

class TestCleanHTML:
    def test_strips_tags(self):
        from server import _clean_html
        assert _clean_html("<b>Bold</b> text") == "Bold text"

    def test_decodes_entities(self):
        from server import _clean_html
        assert _clean_html("a &amp; b &lt; c") == "a & b < c"

    def test_handles_empty(self):
        from server import _clean_html
        assert _clean_html("") == ""

    def test_handles_nested_tags(self):
        from server import _clean_html
        assert _clean_html("<div><p>Hello <b>world</b></p></div>") == "Hello world"


# ---------------------------------------------------------------------------
# Tests: result formatting
# ---------------------------------------------------------------------------

class TestFormatResult:
    def test_basic_format(self):
        from server import _format_result
        item = {"title": "Test", "url": "https://example.com", "content": "Description"}
        out = _format_result(item)
        assert out["title"] == "Test"
        assert out["url"] == "https://example.com"
        assert out["snippet"] == "Description"

    def test_missing_fields(self):
        from server import _format_result
        out = _format_result({})
        assert out["title"] == ""
        assert out["url"] == ""
        assert out["snippet"] == ""

    def test_long_title_truncated(self):
        from server import _format_result
        long_title = "T" * 300
        item = {"title": long_title, "url": "https://example.com", "content": "ok"}
        out = _format_result(item)
        assert len(out["title"]) <= 200


# ---------------------------------------------------------------------------
# Tests: SearXNG URL configuration
# ---------------------------------------------------------------------------

class TestConfiguration:
    @pytest.mark.asyncio
    async def test_uses_custom_searxng_url(self):
        """When SEARXNG_URL is set, the server should use it."""
        results = [_sample_result()]
        mock_resp = _mock_response(results)
        mock_client = _mock_client(mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import server
            original_url = server.SEARXNG_URL
            server.SEARXNG_URL = "http://192.168.4.54:8088"
            try:
                from server import search_web
                await search_web("test", max_results=1)
                # Verify the URL used contains our custom host
                call_args = mock_client.get.call_args
                assert "192.168.4.54:8088" in call_args.args[0]
            finally:
                server.SEARXNG_URL = original_url
