"""
Tests for V12.4 Chunk data model refactoring.

Validates:
1. Chunk is frozen (immutable) and hashable
2. frozenset coercion from set for terms
3. ScoredChunk wraps Chunk with retrieval metadata
4. chunk_id uniqueness and stability
5. Serialization round-trip (to_dict / from_dict)
6. HybridBackend RRF scoring with chunk_id keys
"""

import pytest

from core.memory_pkg.memory.types import Chunk, IndexStats, ScoredChunk


class TestChunkImmutability:
    """Chunk must be frozen and hashable for use as dict keys."""

    def test_chunk_is_hashable(self):
        """Chunk should be hashable (required for dict keys in RRF)."""
        chunk = Chunk(
            file_path="test.py",
            start_line=1,
            end_line=10,
            content="def foo(): pass",
            terms=frozenset({"foo", "pass"}),
            chunk_type="function",
            name="foo",
        )
        # Must not raise TypeError
        h = hash(chunk)
        assert isinstance(h, int)

    def test_chunk_as_dict_key(self):
        """Chunk should work as a dictionary key."""
        c1 = Chunk("a.py", 1, 5, "hello", frozenset({"hello"}))
        c2 = Chunk("b.py", 1, 5, "world", frozenset({"world"}))

        d = {c1: 0.9, c2: 0.7}
        assert d[c1] == 0.9
        assert d[c2] == 0.7

    def test_chunk_is_frozen(self):
        """Chunk fields should not be assignable."""
        chunk = Chunk("test.py", 1, 10, "content")
        with pytest.raises(AttributeError):
            chunk.content = "modified"

    def test_chunk_set_coercion(self):
        """Passing a mutable set for terms should auto-coerce to frozenset."""
        chunk = Chunk(
            file_path="test.py",
            start_line=1,
            end_line=10,
            content="def foo(): pass",
            terms={"foo", "pass"},  # Regular set - should be coerced
        )
        assert isinstance(chunk.terms, frozenset)
        assert chunk.terms == frozenset({"foo", "pass"})

        # Must still be hashable after coercion
        h = hash(chunk)
        assert isinstance(h, int)

    def test_chunk_default_terms(self):
        """Default terms should be empty frozenset."""
        chunk = Chunk("test.py", 1, 10, "content")
        assert chunk.terms == frozenset()
        assert isinstance(chunk.terms, frozenset)


class TestChunkIdentity:
    """chunk_id provides stable identity for deduplication."""

    def test_chunk_id_format(self):
        """chunk_id should be file_path:start-end."""
        chunk = Chunk("core/module.py", 42, 100, "content")
        assert chunk.chunk_id == "core/module.py:42-100"

    def test_chunk_id_unique(self):
        """Different chunks should have different chunk_ids."""
        c1 = Chunk("a.py", 1, 10, "content1")
        c2 = Chunk("a.py", 11, 20, "content2")
        c3 = Chunk("b.py", 1, 10, "content3")

        ids = {c1.chunk_id, c2.chunk_id, c3.chunk_id}
        assert len(ids) == 3

    def test_content_hash(self):
        """content_hash should be deterministic."""
        chunk = Chunk("test.py", 1, 5, "hello world")
        h1 = chunk.content_hash
        h2 = chunk.content_hash
        assert h1 == h2
        assert len(h1) == 16


class TestChunkSerialization:
    """Chunk to_dict/from_dict must round-trip correctly."""

    def test_to_dict(self):
        """to_dict should produce JSON-serializable dict."""
        chunk = Chunk(
            file_path="test.py",
            start_line=1,
            end_line=10,
            content="def foo(): pass",
            terms=frozenset({"foo", "pass"}),
            chunk_type="function",
            name="foo",
        )
        d = chunk.to_dict()

        assert d["file_path"] == "test.py"
        assert d["start_line"] == 1
        assert d["chunk_type"] == "function"
        # terms should be a sorted list for JSON
        assert isinstance(d["terms"], list)
        assert set(d["terms"]) == {"foo", "pass"}

    def test_from_dict(self):
        """from_dict should reconstruct Chunk from dict."""
        d = {
            "file_path": "test.py",
            "start_line": 1,
            "end_line": 10,
            "content": "def foo(): pass",
            "terms": ["foo", "pass"],
            "chunk_type": "function",
            "name": "foo",
        }
        chunk = Chunk.from_dict(d)

        assert chunk.file_path == "test.py"
        assert chunk.chunk_type == "function"
        assert chunk.terms == frozenset({"foo", "pass"})
        assert isinstance(chunk.terms, frozenset)

    def test_round_trip(self):
        """to_dict -> from_dict should preserve all fields."""
        original = Chunk(
            file_path="core/sample.py",
            start_line=42,
            end_line=100,
            content="class Foo:\n    pass",
            terms=frozenset({"foo", "class"}),
            chunk_type="class",
            name="Foo",
        )
        restored = Chunk.from_dict(original.to_dict())

        assert restored.file_path == original.file_path
        assert restored.start_line == original.start_line
        assert restored.end_line == original.end_line
        assert restored.content == original.content
        assert restored.terms == original.terms
        assert restored.chunk_type == original.chunk_type
        assert restored.name == original.name


class TestScoredChunk:
    """ScoredChunk wraps Chunk with retrieval metadata."""

    def test_scored_chunk_creation(self):
        """ScoredChunk should wrap a Chunk with score and metadata."""
        chunk = Chunk("test.py", 1, 10, "content")
        scored = ScoredChunk(chunk=chunk, score=0.85, backend="bm25")

        assert scored.score == 0.85
        assert scored.backend == "bm25"
        assert scored.chunk is chunk

    def test_scored_chunk_delegates_properties(self):
        """ScoredChunk should delegate Chunk properties."""
        chunk = Chunk("test.py", 1, 10, "content", frozenset({"term"}), "function", "foo")
        scored = ScoredChunk(chunk=chunk, score=0.9)

        assert scored.file_path == "test.py"
        assert scored.start_line == 1
        assert scored.end_line == 10
        assert scored.content == "content"
        assert scored.terms == frozenset({"term"})
        assert scored.chunk_type == "function"
        assert scored.name == "foo"
        assert scored.chunk_id == "test.py:1-10"

    def test_scored_chunk_mutable_score(self):
        """ScoredChunk score should be mutable (for RRF adjustments)."""
        chunk = Chunk("test.py", 1, 10, "content")
        scored = ScoredChunk(chunk=chunk, score=0.5)
        scored.score = 0.9
        assert scored.score == 0.9

    def test_scored_chunk_metadata(self):
        """ScoredChunk metadata should support arbitrary keys."""
        chunk = Chunk("test.py", 1, 10, "content")
        scored = ScoredChunk(
            chunk=chunk,
            score=0.8,
            metadata={"rrf_rank": 1, "source_backend": "dense"},
        )
        assert scored.metadata["rrf_rank"] == 1


class TestIndexStats:
    """IndexStats dataclass."""

    def test_index_stats_defaults(self):
        """IndexStats should have sensible defaults."""
        stats = IndexStats()
        assert stats.total_files == 0
        assert stats.total_chunks == 0

    def test_index_stats_to_dict(self):
        """IndexStats should serialize to dict."""
        stats = IndexStats(total_files=5, total_chunks=100, total_terms=500)
        d = stats.to_dict()
        assert d["total_files"] == 5
        assert d["total_chunks"] == 100
