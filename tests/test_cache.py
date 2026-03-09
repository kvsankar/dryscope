"""Tests for dryscope.cache — SQLite-backed caching."""

import pytest

from dryscope.cache import Cache, CacheStats


@pytest.fixture
def cache(tmp_path):
    """Create a Cache instance with a temporary database."""
    db_path = tmp_path / "test_cache.db"
    c = Cache(db_path)
    yield c
    c.close()


class TestCacheCreation:
    def test_creates_db_file(self, tmp_path):
        db_path = tmp_path / "subdir" / "cache.db"
        c = Cache(db_path)
        assert db_path.exists()
        c.close()

    def test_creates_parent_dirs(self, tmp_path):
        db_path = tmp_path / "a" / "b" / "cache.db"
        c = Cache(db_path)
        assert db_path.parent.exists()
        c.close()


class TestEmbeddingRoundtrip:
    def test_set_and_get(self, cache):
        vector = [0.1, 0.2, 0.3, 0.4]
        cache.set_embedding("hello world", "model-a", vector)
        cache.commit()
        result = cache.get_embedding("hello world", "model-a")
        assert result is not None
        assert result == pytest.approx(vector)

    def test_different_model_is_separate(self, cache):
        cache.set_embedding("content", "model-a", [1.0, 2.0])
        cache.set_embedding("content", "model-b", [3.0, 4.0])
        cache.commit()
        assert cache.get_embedding("content", "model-a") == pytest.approx([1.0, 2.0])
        assert cache.get_embedding("content", "model-b") == pytest.approx([3.0, 4.0])

    def test_miss_returns_none(self, cache):
        result = cache.get_embedding("nonexistent", "model-a")
        assert result is None


class TestCodingRoundtrip:
    def test_set_and_get(self, cache):
        cache.set_coding("code content", "gpt-4", "v1", '{"result": "ok"}')
        cache.commit()
        result = cache.get_coding("code content", "gpt-4", "v1")
        assert result == '{"result": "ok"}'

    def test_different_prompt_version(self, cache):
        cache.set_coding("content", "model", "v1", "response-v1")
        cache.set_coding("content", "model", "v2", "response-v2")
        cache.commit()
        assert cache.get_coding("content", "model", "v1") == "response-v1"
        assert cache.get_coding("content", "model", "v2") == "response-v2"

    def test_miss_returns_none(self, cache):
        result = cache.get_coding("nonexistent", "model", "v1")
        assert result is None


class TestCacheStats:
    def test_empty_cache_stats(self, cache):
        cache.commit()
        stats = cache.stats()
        assert stats.entry_count == 0
        assert stats.embedding_count == 0
        assert stats.coding_count == 0

    def test_stats_after_inserts(self, cache):
        cache.set_embedding("a", "m", [1.0])
        cache.set_embedding("b", "m", [2.0])
        cache.set_coding("c", "m", "v1", "resp")
        cache.commit()
        stats = cache.stats()
        assert stats.entry_count == 3
        assert stats.embedding_count == 2
        assert stats.coding_count == 1

    def test_hit_and_miss_counts(self, cache):
        cache.set_embedding("a", "m", [1.0])
        cache.commit()
        cache.get_embedding("a", "m")  # hit
        cache.get_embedding("b", "m")  # miss
        stats = cache.stats()
        assert stats.hit_count == 1
        assert stats.miss_count == 1

    def test_db_size_bytes_positive(self, cache):
        cache.set_embedding("a", "m", [1.0])
        cache.commit()
        stats = cache.stats()
        assert stats.db_size_bytes > 0


class TestCacheClear:
    def test_clear_removes_entries(self, cache):
        cache.set_embedding("a", "m", [1.0])
        cache.set_coding("b", "m", "v1", "resp")
        cache.commit()
        cache.clear()
        stats = cache.stats()
        assert stats.entry_count == 0

    def test_clear_then_get_returns_none(self, cache):
        cache.set_embedding("a", "m", [1.0])
        cache.commit()
        cache.clear()
        assert cache.get_embedding("a", "m") is None


class TestContextManager:
    def test_commits_on_exit(self, tmp_path):
        db_path = tmp_path / "ctx_cache.db"
        with Cache(db_path) as c:
            c.set_embedding("a", "m", [1.0, 2.0])
        # Reopen and verify data persisted
        c2 = Cache(db_path)
        result = c2.get_embedding("a", "m")
        assert result is not None
        assert result == pytest.approx([1.0, 2.0])
        c2.close()
