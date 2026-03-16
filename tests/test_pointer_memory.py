"""
Comprehensive tests for the PointerMemory module.

Tests cover: Pointer/PointerStats dataclasses, summarization heuristics,
token estimation, store/retrieve lifecycle, eviction policies, statistics,
singleton pattern, thread safety, and source-specific behavior.

Target: ~70 tests across 13 test classes.
"""

import hashlib
import threading
import time

import pytest

from core.memory_pkg.memory.pointer_memory import (
    Pointer,
    PointerMemory,
    PointerStats,
    _estimate_tokens,
    _generate_summary,
    get_pointer_memory,
    reset_pointer_memory,
)

# =============================================================================
# Helpers
# =============================================================================


def _make_content(length: int, char: str = "x") -> str:
    """Create a string of exactly `length` characters."""
    return char * length


def _make_large_content(lines: int = 50, line_len: int = 80) -> str:
    """Create multi-line content that exceeds default threshold."""
    return "\n".join(f"Line {i}: " + "a" * (line_len - len(f"Line {i}: ")) for i in range(lines))


def _content_hash(content: str) -> str:
    """Replicate the hashing logic from PointerMemory._hash."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:16]


# =============================================================================
# 1. Pointer Dataclass
# =============================================================================


class TestPointerDataclass:
    """Tests for the Pointer dataclass fields and properties."""

    def test_pointer_fields_defaults(self):
        """Pointer has correct default values for created_at and access_count."""
        before = time.time()
        p = Pointer(
            pointer_id="abc123",
            summary="test summary",
            source="read:file.py",
            content_length=1000,
            token_estimate=200,
        )
        after = time.time()
        assert p.pointer_id == "abc123"
        assert p.summary == "test summary"
        assert p.source == "read:file.py"
        assert p.content_length == 1000
        assert p.token_estimate == 200
        assert before <= p.created_at <= after
        assert p.access_count == 0

    def test_pointer_explicit_fields(self):
        """Pointer accepts explicit created_at and access_count."""
        p = Pointer(
            pointer_id="xyz",
            summary="s",
            source="tool",
            content_length=10,
            token_estimate=2,
            created_at=1000.0,
            access_count=5,
        )
        assert p.created_at == 1000.0
        assert p.access_count == 5

    def test_context_representation_format(self):
        """context_representation uses first 8 chars of pointer_id."""
        p = Pointer(
            pointer_id="abcdef1234567890",
            summary="short summary",
            source="grep:pattern",
            content_length=2000,
            token_estimate=400,
        )
        rep = p.context_representation
        assert rep.startswith("[PTR:abcdef12]")
        assert "grep:pattern" in rep
        assert "2000 chars" in rep
        assert "short summary" in rep

    def test_context_representation_short_id(self):
        """context_representation works with pointer_id shorter than 8 chars."""
        p = Pointer(
            pointer_id="abc",
            summary="summary",
            source="tool",
            content_length=100,
            token_estimate=20,
        )
        rep = p.context_representation
        assert "[PTR:abc]" in rep

    def test_pointer_access_count_mutable(self):
        """access_count can be incremented (used by retrieve)."""
        p = Pointer(
            pointer_id="id1",
            summary="s",
            source="tool",
            content_length=10,
            token_estimate=1,
        )
        p.access_count += 1
        p.access_count += 1
        assert p.access_count == 2


# =============================================================================
# 2. PointerStats Dataclass
# =============================================================================


class TestPointerStatsDataclass:
    """Tests for the PointerStats dataclass."""

    def test_all_fields_present(self):
        """PointerStats stores all expected fields."""
        stats = PointerStats(
            total_stored=10,
            total_retrieved=5,
            tokens_saved=1000,
            active_pointers=8,
            evicted_pointers=2,
            avg_compression_ratio=0.15,
        )
        assert stats.total_stored == 10
        assert stats.total_retrieved == 5
        assert stats.tokens_saved == 1000
        assert stats.active_pointers == 8
        assert stats.evicted_pointers == 2
        assert stats.avg_compression_ratio == pytest.approx(0.15)

    def test_zero_stats(self):
        """PointerStats works with all zeros."""
        stats = PointerStats(0, 0, 0, 0, 0, 0.0)
        assert stats.total_stored == 0
        assert stats.avg_compression_ratio == 0.0

    def test_stats_fields_accessible(self):
        """All fields are accessible as attributes (not dict)."""
        stats = PointerStats(1, 2, 3, 4, 5, 0.5)
        assert hasattr(stats, "total_stored")
        assert hasattr(stats, "total_retrieved")
        assert hasattr(stats, "tokens_saved")
        assert hasattr(stats, "active_pointers")
        assert hasattr(stats, "evicted_pointers")
        assert hasattr(stats, "avg_compression_ratio")


# =============================================================================
# 3. _generate_summary
# =============================================================================


class TestGenerateSummary:
    """Tests for the _generate_summary heuristic function."""

    def test_file_source_short(self):
        """File source with fewer than 5 lines returns all lines."""
        content = "line1\nline2\nline3"
        result = _generate_summary(content, "read:src/main.py")
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result
        assert "lines total" not in result

    def test_file_source_long(self):
        """File source with more than 5 lines shows first 5 plus count."""
        content = "\n".join(f"line{i}" for i in range(20))
        result = _generate_summary(content, "read:src/main.py")
        assert "line0" in result
        assert "line4" in result
        assert "20 lines total" in result

    def test_file_source_prefix(self):
        """Both 'read:' and 'file:' prefixes trigger file summary."""
        content = "\n".join(f"line{i}" for i in range(10))
        r1 = _generate_summary(content, "read:test.py")
        r2 = _generate_summary(content, "file:test.py")
        assert "10 lines total" in r1
        assert "10 lines total" in r2

    def test_file_source_truncates_long_lines(self):
        """File source truncates individual lines to 80 chars."""
        long_line = "A" * 200
        content = long_line + "\n" + "short"
        result = _generate_summary(content, "read:file.py")
        # Each line stripped to 80 chars max
        first_line_in_result = result.split("\n")[0]
        assert len(first_line_in_result) <= 80

    def test_grep_source(self):
        """Grep source returns match count and samples."""
        content = "match1\nmatch2\nmatch3\nmatch4\nmatch5"
        result = _generate_summary(content, "grep:pattern")
        assert "5 matches" in result
        assert "Samples:" in result
        assert "match1" in result

    def test_grep_source_search_prefix(self):
        """'search:' prefix also triggers grep summary."""
        content = "result1\nresult2"
        result = _generate_summary(content, "search:query")
        assert "2 matches" in result

    def test_grep_samples_limited_to_three(self):
        """Grep summary only shows first 3 matches as samples."""
        content = "\n".join(f"match_{i}" for i in range(10))
        result = _generate_summary(content, "grep:pattern")
        assert "match_0" in result
        assert "match_2" in result
        # match_3 should not be in samples (only first 3)
        # But it appears in the count part, so check via semicolons
        samples_part = result.split("Samples: ")[1]
        assert samples_part.count(";") <= 2  # At most 2 separators for 3 items

    def test_web_source(self):
        """Web source returns first paragraph truncated to max_length."""
        content = "First paragraph here.\n\nSecond paragraph."
        result = _generate_summary(content, "web:example.com")
        assert "First paragraph here." in result
        assert "Second paragraph" not in result

    def test_web_source_fetch_prefix(self):
        """'fetch:' prefix triggers web summary."""
        content = "Fetched content.\n\nMore content."
        result = _generate_summary(content, "fetch:api.example.com")
        assert "Fetched content." in result

    def test_web_source_respects_max_length(self):
        """Web summary respects max_length parameter."""
        content = "A" * 500
        result = _generate_summary(content, "web:site.com", max_length=100)
        assert len(result) <= 100

    def test_generic_multiline(self):
        """Generic content with >3 lines shows first and last."""
        content = "first line\nsecond\nthird\nfourth\nlast line"
        result = _generate_summary(content, "tool")
        assert "first line" in result
        assert "last line" in result
        assert "5 lines" in result

    def test_generic_short_content(self):
        """Generic short content (<=3 lines) just truncates."""
        content = "short content"
        result = _generate_summary(content, "tool")
        assert result == "short content"

    def test_empty_content(self):
        """Empty string returns '(empty content)'."""
        assert _generate_summary("", "tool") == "(empty content)"

    def test_whitespace_only_content(self):
        """Whitespace-only content returns '(empty content)'."""
        assert _generate_summary("   \n  \t  ", "tool") == "(empty content)"

    def test_custom_max_length(self):
        """max_length parameter limits generic short content."""
        content = "A" * 300
        result = _generate_summary(content, "tool", max_length=50)
        assert len(result) == 50


# =============================================================================
# 4. _estimate_tokens
# =============================================================================


class TestEstimateTokens:
    """Tests for the _estimate_tokens heuristic."""

    def test_empty_string(self):
        """Empty string returns 1 (minimum)."""
        assert _estimate_tokens("") == 1

    def test_short_string(self):
        """Short string (1-3 chars) returns 1."""
        assert _estimate_tokens("abc") == 1

    def test_four_chars(self):
        """Exactly 4 chars returns 1 token."""
        assert _estimate_tokens("abcd") == 1

    def test_eight_chars(self):
        """8 chars returns 2 tokens."""
        assert _estimate_tokens("abcdefgh") == 2

    def test_large_string(self):
        """Large string returns proportional estimate."""
        text = "x" * 4000
        assert _estimate_tokens(text) == 1000

    def test_minimum_is_one(self):
        """Result is always at least 1."""
        assert _estimate_tokens("") >= 1
        assert _estimate_tokens("a") >= 1


# =============================================================================
# 5. store()
# =============================================================================


class TestStore:
    """Tests for PointerMemory.store()."""

    def setup_method(self):
        self.pm = PointerMemory()

    def test_store_empty_content(self):
        """Empty content returns special 'empty' pointer."""
        p = self.pm.store("", source="tool")
        assert p.pointer_id == "empty"
        assert p.summary == "(empty)"
        assert p.content_length == 0
        assert p.token_estimate == 0

    def test_store_below_threshold_returns_full_content(self):
        """Content below threshold: summary IS the full content."""
        small = "Hello world"
        p = self.pm.store(small, source="tool")
        assert p.summary == small
        assert p.content_length == len(small)
        assert p.token_estimate == 0  # No savings

    def test_store_below_threshold_not_in_external_store(self):
        """Content below threshold is NOT stored externally."""
        small = "Hello world"
        p = self.pm.store(small, source="tool")
        # Should not be in the internal _store dict
        assert p.pointer_id not in self.pm._store

    def test_store_above_threshold(self):
        """Content above threshold is stored externally with summary."""
        large = _make_content(1000)
        p = self.pm.store(large, source="tool")
        assert p.pointer_id in self.pm._store
        assert p.content_length == 1000
        assert p.token_estimate > 0
        assert p.summary != large  # Summary is shorter

    def test_store_returns_correct_pointer_id(self):
        """Pointer ID matches sha256 hash of content."""
        content = _make_content(600)
        p = self.pm.store(content, source="tool")
        expected_id = _content_hash(content)
        assert p.pointer_id == expected_id

    def test_store_increments_total_stored(self):
        """Each store above threshold increments total_stored counter."""
        large = _make_content(600)
        self.pm.store(large, source="tool")
        stats = self.pm.get_stats()
        assert stats.total_stored == 1

    def test_store_below_threshold_does_not_increment_total_stored(self):
        """Store below threshold does not increment total_stored."""
        small = "tiny"
        self.pm.store(small, source="tool")
        stats = self.pm.get_stats()
        assert stats.total_stored == 0

    def test_store_duplicate_content_overwrites(self):
        """Storing the same content again updates the store (same hash)."""
        large = _make_content(600)
        p1 = self.pm.store(large, source="tool")
        p2 = self.pm.store(large, source="tool")
        assert p1.pointer_id == p2.pointer_id
        # total_stored increments each time
        stats = self.pm.get_stats()
        assert stats.total_stored == 2


# =============================================================================
# 6. retrieve()
# =============================================================================


class TestRetrieve:
    """Tests for PointerMemory.retrieve()."""

    def setup_method(self):
        self.pm = PointerMemory()

    def test_retrieve_existing(self):
        """Retrieve returns full content for stored pointer."""
        large = _make_content(600)
        p = self.pm.store(large, source="tool")
        result = self.pm.retrieve(p.pointer_id)
        assert result == large

    def test_retrieve_nonexistent(self):
        """Retrieve returns None for unknown pointer_id."""
        assert self.pm.retrieve("nonexistent_id") is None

    def test_retrieve_increments_access_count(self):
        """Each retrieve increments the pointer's access_count."""
        large = _make_content(600)
        p = self.pm.store(large, source="tool")
        self.pm.retrieve(p.pointer_id)
        self.pm.retrieve(p.pointer_id)
        assert self.pm._pointers[p.pointer_id].access_count == 2

    def test_retrieve_increments_total_retrieved(self):
        """Each successful retrieve increments total_retrieved counter."""
        large = _make_content(600)
        p = self.pm.store(large, source="tool")
        self.pm.retrieve(p.pointer_id)
        stats = self.pm.get_stats()
        assert stats.total_retrieved == 1

    def test_retrieve_miss_does_not_increment(self):
        """Failed retrieve does not increment total_retrieved."""
        self.pm.retrieve("missing")
        stats = self.pm.get_stats()
        assert stats.total_retrieved == 0

    def test_retrieve_lru_ordering(self):
        """Retrieve moves item to end (most recent) in LRU order."""
        # Store 3 items
        c1 = _make_content(600, "a")
        c2 = _make_content(600, "b")
        c3 = _make_content(600, "c")
        p1 = self.pm.store(c1, source="tool")
        p2 = self.pm.store(c2, source="tool")
        self.pm.store(c3, source="tool")

        # Access p1 (moves it to end)
        self.pm.retrieve(p1.pointer_id)

        # The LRU order should now be: p2, p3, p1
        keys = list(self.pm._store.keys())
        assert keys[0] == p2.pointer_id
        assert keys[-1] == p1.pointer_id

    def test_retrieve_below_threshold_not_stored(self):
        """Content stored below threshold cannot be retrieved (not in store)."""
        small = "tiny content"
        p = self.pm.store(small, source="tool")
        result = self.pm.retrieve(p.pointer_id)
        assert result is None


# =============================================================================
# 7. should_store()
# =============================================================================


class TestShouldStore:
    """Tests for PointerMemory.should_store()."""

    def setup_method(self):
        self.pm = PointerMemory()

    def test_below_threshold(self):
        """Content at or below threshold returns False."""
        assert self.pm.should_store("x" * 500) is False
        assert self.pm.should_store("x" * 499) is False

    def test_above_threshold(self):
        """Content above threshold returns True."""
        assert self.pm.should_store("x" * 501) is True

    def test_empty_string(self):
        """Empty string returns False."""
        assert self.pm.should_store("") is False

    def test_custom_threshold(self):
        """Custom threshold via constructor is respected."""
        pm = PointerMemory(size_threshold=100)
        assert pm.should_store("x" * 100) is False
        assert pm.should_store("x" * 101) is True


# =============================================================================
# 8. Eviction
# =============================================================================


class TestEviction:
    """Tests for eviction by count and total size limits."""

    def test_eviction_by_count(self):
        """Oldest entries evicted when count exceeds MAX_POINTERS."""
        pm = PointerMemory(max_pointers=5)
        pointers = []
        for i in range(7):
            content = _make_content(600, chr(ord("a") + i))
            p = pm.store(content, source="tool")
            pointers.append(p)

        # Only 5 should remain (the 5 most recent)
        assert len(pm._store) == 5
        # First 2 should have been evicted
        assert pm.retrieve(pointers[0].pointer_id) is None
        assert pm.retrieve(pointers[1].pointer_id) is None
        # Last 5 should still exist
        assert pm.retrieve(pointers[6].pointer_id) is not None

    def test_eviction_by_count_updates_evicted_counter(self):
        """Evicted count is tracked correctly."""
        pm = PointerMemory(max_pointers=3)
        for i in range(5):
            content = _make_content(600, chr(ord("a") + i))
            pm.store(content, source="tool")
        stats = pm.get_stats()
        assert stats.evicted_pointers == 2

    def test_eviction_by_total_size(self):
        """Entries evicted when total content size exceeds MAX_TOTAL_SIZE."""
        pm = PointerMemory(max_pointers=1000)  # High count limit
        # MAX_TOTAL_SIZE is 500_000 by default
        # Store entries that together exceed the limit
        chunk_size = 100_000  # 100K each
        pointers = []
        for i in range(7):  # 7 * 100K = 700K > 500K
            content = _make_content(chunk_size, chr(ord("a") + i))
            p = pm.store(content, source="tool")
            pointers.append(p)

        # Some entries should have been evicted
        assert pm._total_content_size <= PointerMemory.MAX_TOTAL_SIZE

    def test_eviction_removes_pointer_metadata(self):
        """Evicted entries have their Pointer metadata removed too."""
        pm = PointerMemory(max_pointers=2)
        c1 = _make_content(600, "a")
        c2 = _make_content(600, "b")
        c3 = _make_content(600, "c")
        p1 = pm.store(c1, source="tool")
        pm.store(c2, source="tool")
        pm.store(c3, source="tool")  # Evicts p1

        assert p1.pointer_id not in pm._pointers
        assert p1.pointer_id not in pm._store

    def test_lru_eviction_order(self):
        """LRU: recently accessed items survive eviction."""
        pm = PointerMemory(max_pointers=3)
        c1 = _make_content(600, "a")
        c2 = _make_content(600, "b")
        c3 = _make_content(600, "c")
        p1 = pm.store(c1, source="tool")
        p2 = pm.store(c2, source="tool")
        pm.store(c3, source="tool")

        # Access p1 to make it recently used
        pm.retrieve(p1.pointer_id)

        # Add a 4th item -- should evict p2 (oldest untouched)
        c4 = _make_content(600, "d")
        pm.store(c4, source="tool")

        assert pm.retrieve(p1.pointer_id) is not None  # Survived (recently accessed)
        assert pm.retrieve(p2.pointer_id) is None  # Evicted (oldest)


# =============================================================================
# 9. get_stats()
# =============================================================================


class TestGetStats:
    """Tests for PointerMemory.get_stats()."""

    def setup_method(self):
        self.pm = PointerMemory()

    def test_initial_stats(self):
        """Fresh memory has all-zero stats."""
        stats = self.pm.get_stats()
        assert stats.total_stored == 0
        assert stats.total_retrieved == 0
        assert stats.tokens_saved == 0
        assert stats.active_pointers == 0
        assert stats.evicted_pointers == 0
        assert stats.avg_compression_ratio == 0.0

    def test_stats_after_store(self):
        """Stats reflect stored content correctly."""
        large = _make_content(1000)
        self.pm.store(large, source="tool")
        stats = self.pm.get_stats()
        assert stats.total_stored == 1
        assert stats.active_pointers == 1
        assert stats.tokens_saved > 0

    def test_stats_compression_ratio(self):
        """Compression ratio is summary_length / original_length."""
        large = _make_content(2000)
        self.pm.store(large, source="tool")
        stats = self.pm.get_stats()
        # Summary is much shorter than original -> ratio < 1.0
        assert 0 < stats.avg_compression_ratio < 1.0

    def test_stats_after_retrieve(self):
        """Stats reflect retrieval count."""
        large = _make_content(600)
        p = self.pm.store(large, source="tool")
        self.pm.retrieve(p.pointer_id)
        self.pm.retrieve(p.pointer_id)
        stats = self.pm.get_stats()
        assert stats.total_retrieved == 2

    def test_stats_tokens_saved_accumulate(self):
        """tokens_saved accumulates across multiple stores."""
        for i in range(3):
            content = _make_content(800, chr(ord("a") + i))
            self.pm.store(content, source="tool")
        stats = self.pm.get_stats()
        # Each 800-char content saves approximately (800//4 - summary_tokens) tokens
        assert stats.tokens_saved > 100

    def test_stats_after_eviction(self):
        """Stats correctly track evicted pointers."""
        pm = PointerMemory(max_pointers=2)
        for i in range(4):
            content = _make_content(600, chr(ord("a") + i))
            pm.store(content, source="tool")
        stats = pm.get_stats()
        assert stats.evicted_pointers == 2
        assert stats.active_pointers == 2


# =============================================================================
# 10. clear()
# =============================================================================


class TestClear:
    """Tests for PointerMemory.clear()."""

    def setup_method(self):
        self.pm = PointerMemory()

    def test_clear_empties_store(self):
        """clear() removes all externally stored content."""
        large = _make_content(600)
        p = self.pm.store(large, source="tool")
        self.pm.clear()
        assert self.pm.retrieve(p.pointer_id) is None

    def test_clear_empties_pointers(self):
        """clear() removes all pointer metadata."""
        large = _make_content(600)
        self.pm.store(large, source="tool")
        self.pm.clear()
        assert len(self.pm._pointers) == 0

    def test_clear_resets_content_size(self):
        """clear() resets total content size to 0."""
        large = _make_content(600)
        self.pm.store(large, source="tool")
        self.pm.clear()
        assert self.pm._total_content_size == 0

    def test_clear_preserves_counters(self):
        """clear() does NOT reset total_stored or total_retrieved counters."""
        large = _make_content(600)
        p = self.pm.store(large, source="tool")
        self.pm.retrieve(p.pointer_id)
        self.pm.clear()
        stats = self.pm.get_stats()
        assert stats.total_stored == 1  # Historical count preserved
        assert stats.total_retrieved == 1  # Historical count preserved
        assert stats.active_pointers == 0  # Active is 0 after clear

    def test_clear_allows_new_storage(self):
        """After clear(), new content can be stored and retrieved."""
        large = _make_content(600)
        self.pm.store(large, source="tool")
        self.pm.clear()
        new_content = _make_content(700, "y")
        p = self.pm.store(new_content, source="tool")
        assert self.pm.retrieve(p.pointer_id) == new_content


# =============================================================================
# 11. Singleton Pattern
# =============================================================================


class TestSingleton:
    """Tests for get_pointer_memory() and reset_pointer_memory()."""

    def setup_method(self):
        reset_pointer_memory()

    def teardown_method(self):
        reset_pointer_memory()

    def test_get_returns_instance(self):
        """get_pointer_memory() returns a PointerMemory instance."""
        pm = get_pointer_memory()
        assert isinstance(pm, PointerMemory)

    def test_get_returns_same_instance(self):
        """Repeated calls return the same instance (singleton)."""
        pm1 = get_pointer_memory()
        pm2 = get_pointer_memory()
        assert pm1 is pm2

    def test_reset_clears_singleton(self):
        """reset_pointer_memory() clears the cached instance."""
        pm1 = get_pointer_memory()
        reset_pointer_memory()
        pm2 = get_pointer_memory()
        assert pm1 is not pm2

    def test_reset_new_instance_is_fresh(self):
        """After reset, the new instance has no stored data."""
        pm = get_pointer_memory()
        large = _make_content(600)
        p = pm.store(large, source="tool")
        reset_pointer_memory()
        pm_new = get_pointer_memory()
        assert pm_new.retrieve(p.pointer_id) is None
        stats = pm_new.get_stats()
        assert stats.total_stored == 0


# =============================================================================
# 12. Thread Safety Basics
# =============================================================================


class TestThreadSafety:
    """Basic thread safety tests for concurrent store/retrieve operations."""

    def test_concurrent_stores(self):
        """Multiple threads can store content concurrently without errors."""
        pm = PointerMemory()
        errors = []

        def store_work(idx):
            try:
                content = _make_content(600, chr(ord("a") + idx % 26))
                pm.store(content, source=f"tool:{idx}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=store_work, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0

    def test_concurrent_store_and_retrieve(self):
        """Store and retrieve can run concurrently without errors."""
        pm = PointerMemory()
        large = _make_content(600, "z")
        p = pm.store(large, source="tool")
        errors = []

        def retriever():
            try:
                for _ in range(50):
                    pm.retrieve(p.pointer_id)
            except Exception as e:
                errors.append(e)

        def storer():
            try:
                for i in range(50):
                    content = _make_content(600, chr(ord("a") + i % 26))
                    pm.store(content, source="tool")
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=retriever),
            threading.Thread(target=storer),
            threading.Thread(target=retriever),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0

    def test_concurrent_stats(self):
        """get_stats() is safe to call concurrently."""
        pm = PointerMemory()
        large = _make_content(600)
        pm.store(large, source="tool")
        errors = []

        def stat_work():
            try:
                for _ in range(50):
                    pm.get_stats()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=stat_work) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(errors) == 0

    def test_concurrent_clear_and_store(self):
        """clear() and store() can interleave without crashing."""
        pm = PointerMemory()
        errors = []

        def store_loop():
            try:
                for i in range(30):
                    content = _make_content(600, chr(ord("a") + i % 26))
                    pm.store(content, source="tool")
            except Exception as e:
                errors.append(e)

        def clear_loop():
            try:
                for _ in range(10):
                    pm.clear()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=store_loop)
        t2 = threading.Thread(target=clear_loop)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert len(errors) == 0


# =============================================================================
# 13. Different Source Types Behavior
# =============================================================================


class TestSourceTypeBehavior:
    """Tests that different source prefixes produce appropriate summaries."""

    def setup_method(self):
        self.pm = PointerMemory()

    def _make_multiline(self, lines=20):
        return "\n".join(f"line {i}: some content here with extra padding to ensure length" for i in range(lines))

    def test_read_source_uses_file_summary(self):
        """'read:' source produces file-style summary."""
        content = self._make_multiline(20)
        p = self.pm.store(content, source="read:src/auth.py")
        assert "lines total" in p.summary
        assert "line 0" in p.summary

    def test_file_source_uses_file_summary(self):
        """'file:' source produces file-style summary."""
        content = self._make_multiline(20)
        p = self.pm.store(content, source="file:config.yaml")
        assert "lines total" in p.summary

    def test_grep_source_uses_match_summary(self):
        """'grep:' source produces match-count summary."""
        content = self._make_multiline(15)
        p = self.pm.store(content, source="grep:TODO")
        assert "matches" in p.summary
        assert "Samples:" in p.summary

    def test_search_source_uses_match_summary(self):
        """'search:' source produces match-count summary."""
        content = self._make_multiline(10)
        p = self.pm.store(content, source="search:error")
        assert "matches" in p.summary

    def test_web_source_uses_paragraph_summary(self):
        """'web:' source produces paragraph-based summary."""
        content = "Title of page.\n\nLong paragraph two." + " more" * 200
        p = self.pm.store(content, source="web:docs.example.com")
        assert "Title of page." in p.summary

    def test_fetch_source_uses_paragraph_summary(self):
        """'fetch:' source produces paragraph-based summary."""
        content = "API response here.\n\nDetailed data." + " x" * 300
        p = self.pm.store(content, source="fetch:api.site.com")
        assert "API response here." in p.summary

    def test_generic_source_uses_first_last_lines(self):
        """Generic source uses first + last line summary."""
        lines = [f"line_{i}: " + "padding data " * 5 for i in range(20)]
        content = "\n".join(lines)
        p = self.pm.store(content, source="tool:custom")
        assert "line_0" in p.summary
        assert "line_19" in p.summary
        assert "20 lines" in p.summary

    def test_source_preserved_in_pointer(self):
        """Source string is stored in the Pointer object."""
        content = _make_content(600)
        p = self.pm.store(content, source="read:important/file.py")
        assert p.source == "read:important/file.py"


# =============================================================================
# Additional edge cases
# =============================================================================


class TestEdgeCases:
    """Edge case and boundary tests."""

    def test_store_exactly_at_threshold(self):
        """Content at exactly SIZE_THRESHOLD is below threshold (uses <=)."""
        pm = PointerMemory()
        content = _make_content(500)
        p = pm.store(content, source="tool")
        # At threshold: summary == full content, no external storage
        assert p.summary == content
        assert p.token_estimate == 0

    def test_store_one_above_threshold(self):
        """Content one char above threshold is stored externally."""
        pm = PointerMemory()
        content = _make_content(501)
        p = pm.store(content, source="tool")
        assert p.pointer_id in pm._store
        assert p.token_estimate > 0

    def test_hash_deterministic(self):
        """Same content always produces the same pointer_id."""
        pm = PointerMemory()
        content = _make_content(600)
        p1 = pm.store(content, source="tool")
        p2 = pm.store(content, source="different_source")
        assert p1.pointer_id == p2.pointer_id

    def test_hash_different_for_different_content(self):
        """Different content produces different pointer_ids."""
        pm = PointerMemory()
        c1 = _make_content(600, "a")
        c2 = _make_content(600, "b")
        p1 = pm.store(c1, source="tool")
        p2 = pm.store(c2, source="tool")
        assert p1.pointer_id != p2.pointer_id

    def test_custom_max_pointers(self):
        """Constructor max_pointers parameter is respected."""
        pm = PointerMemory(max_pointers=3)
        assert pm._max_pointers == 3

    def test_custom_size_threshold(self):
        """Constructor size_threshold parameter is respected."""
        pm = PointerMemory(size_threshold=100)
        assert pm._size_threshold == 100

    def test_unicode_content(self):
        """Unicode content is handled correctly."""
        pm = PointerMemory()
        content = "Unicode test: " + "\u00e9\u00e8\u00ea\u00eb\u00e0\u00e2\u00e4\u00e7" * 100
        p = pm.store(content, source="tool")
        if len(content) > pm._size_threshold:
            retrieved = pm.retrieve(p.pointer_id)
            assert retrieved == content

    def test_newline_heavy_content(self):
        """Content with many newlines is handled correctly."""
        pm = PointerMemory()
        content = "\n" * 1000
        p = pm.store(content, source="tool")
        # Mostly whitespace -> _generate_summary returns "(empty content)"
        assert p.pointer_id in pm._store
