"""
Tests for BaseTool caching behaviour.

Regression coverage for the cache-key collision bug: tool methods wrap their
work in a zero-argument closure, so `title`/`language`/etc. never reached
_generate_cache_key and every call to a given method shared one global key
(e.g. "wikipedia|get_article_summary"). Any second request for a different
title was served the first request's article for the whole TTL.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from config import CacheConfig
from services.cache_service import CacheService
from tools.base_tool import BaseTool, CACHE_KEY_VERSION


class DummyTool(BaseTool):
    """Minimal concrete BaseTool for exercising execute_with_monitoring."""

    @property
    def api_name(self) -> str:
        return "dummy"

    async def health_check(self):
        return {"status": "healthy"}


@pytest.fixture
def tool_factory():
    def _make(cache_service):
        return DummyTool(MagicMock(), cache_service, AsyncMock(), AsyncMock())
    return _make


@pytest.fixture
def tool(tool_factory):
    return tool_factory(AsyncMock())


class TestGenerateCacheKey:
    """Unit tests for key construction."""

    def test_different_params_produce_different_keys(self, tool):
        key_a = tool._generate_cache_key("get_article_summary", title="Saltlux", language="ko")
        key_b = tool._generate_cache_key("get_article_summary", title="세종대왕", language="ko")

        assert key_a != key_b

    def test_language_is_part_of_the_key(self, tool):
        key_ko = tool._generate_cache_key("get_article_summary", title="Mercury", language="ko")
        key_en = tool._generate_cache_key("get_article_summary", title="Mercury", language="en")

        assert key_ko != key_en

    def test_same_params_produce_same_key(self, tool):
        params = {"title": "Saltlux", "language": "ko", "include_educational_analysis": True}

        assert tool._generate_cache_key("get_article_summary", **params) == \
            tool._generate_cache_key("get_article_summary", **params)

    def test_key_order_independent(self, tool):
        key_a = tool._generate_cache_key("m", title="T", language="ko")
        key_b = tool._generate_cache_key("m", language="ko", title="T")

        assert key_a == key_b

    def test_key_is_versioned(self, tool):
        """Old, parameter-less entries must not be served after a deploy."""
        key = tool._generate_cache_key("get_article_summary", title="T")

        assert key.startswith(f"{CACHE_KEY_VERSION}|")
        assert key != "dummy|get_article_summary"

    def test_complex_values_hash_deterministically(self, tool):
        """Builtin hash() is randomized per process; keys must not be."""
        key_a = tool._generate_cache_key("m", payload=["a", "b"])
        key_b = tool._generate_cache_key("m", payload=["a", "b"])

        assert key_a == key_b
        assert tool._generate_cache_key("m", payload=["a", "c"]) != key_a

    def test_long_keys_are_truncated_deterministically(self, tool):
        long_value = "x" * 500
        key_a = tool._generate_cache_key("m", payload=long_value)
        key_b = tool._generate_cache_key("m", payload=long_value)

        assert key_a == key_b
        assert len(key_a) <= 250
        assert key_a.startswith(f"{CACHE_KEY_VERSION}:dummy:m:")


class TestExecuteWithMonitoringCaching:
    """Integration tests against a real sqlite-backed CacheService."""

    @pytest.fixture
    async def cache_service(self, tmp_path):
        service = CacheService(CacheConfig(database_path=str(tmp_path / "cache.db")))
        await service.initialize()
        return service

    @pytest.mark.asyncio
    async def test_different_titles_do_not_share_a_cache_entry(self, tool_factory, cache_service):
        """The core regression: title B must not be served title A's article."""
        tool = tool_factory(cache_service)

        async def make_result(title):
            return {"title": title}

        first = await tool.execute_with_monitoring(
            "get_article_summary",
            lambda: make_result("솔트룩스"),
            cache_params={"title": "솔트룩스", "language": "ko"},
        )
        second = await tool.execute_with_monitoring(
            "get_article_summary",
            lambda: make_result("세종대왕"),
            cache_params={"title": "세종대왕", "language": "ko"},
        )

        assert first == {"title": "솔트룩스"}
        assert second == {"title": "세종대왕"}

    @pytest.mark.asyncio
    async def test_identical_params_hit_the_cache(self, tool_factory, cache_service):
        """Caching still works: the second identical call must not re-run the work."""
        tool = tool_factory(cache_service)
        calls = []

        async def work():
            calls.append(1)
            return {"title": "솔트룩스"}

        first = await tool.execute_with_monitoring(
            "get_article_summary", work, cache_params={"title": "솔트룩스", "language": "ko"}
        )
        second = await tool.execute_with_monitoring(
            "get_article_summary", work, cache_params={"title": "솔트룩스", "language": "ko"}
        )

        assert first == second == {"title": "솔트룩스"}
        assert len(calls) == 1, "second call should have been served from cache"

    @pytest.mark.asyncio
    async def test_boolean_flag_splits_cache_entries(self, tool_factory, cache_service):
        """include_educational_analysis=True/False are different results."""
        tool = tool_factory(cache_service)

        enriched = await tool.execute_with_monitoring(
            "get_article_summary",
            lambda: _result({"enriched": True}),
            cache_params={"title": "T", "language": "ko", "include_educational_analysis": True},
        )
        plain = await tool.execute_with_monitoring(
            "get_article_summary",
            lambda: _result({"enriched": False}),
            cache_params={"title": "T", "language": "ko", "include_educational_analysis": False},
        )

        assert enriched == {"enriched": True}
        assert plain == {"enriched": False}

    @pytest.mark.asyncio
    async def test_missing_cache_params_disables_caching(self, tool_factory):
        """Fail-safe: an un-migrated call site must not poison a shared key."""
        cache_service = AsyncMock()
        cache_service.get.return_value = None
        tool = tool_factory(cache_service)

        await tool.execute_with_monitoring("some_method", lambda: _result({"a": 1}))

        cache_service.get.assert_not_called()
        cache_service.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_session_does_not_split_the_cache(self, tool_factory, cache_service):
        """Different sessions asking the same question share one entry."""
        tool = tool_factory(cache_service)
        calls = []

        async def work():
            calls.append(1)
            return {"title": "T"}

        await tool.execute_with_monitoring(
            "get_article_summary", work, user_session="s1", cache_params={"title": "T"}
        )
        await tool.execute_with_monitoring(
            "get_article_summary", work, user_session="s2", cache_params={"title": "T"}
        )

        assert len(calls) == 1


async def _result(value):
    return value


if __name__ == "__main__":
    pytest.main([__file__])
