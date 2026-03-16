"""Tests for MemoryDecayScorer (Ebbinghaus forgetting curve)."""

import math
import time

import pytest

from core.memory_pkg.memory.decay_scorer import (
    AccessRecord,
    DecayScorerStats,
    MemoryDecayScorer,
    get_decay_scorer,
    reset_decay_scorer,
)
from core.memory_pkg.memory.types import Chunk, ScoredChunk


@pytest.fixture(autouse=True)
def _reset():
    reset_decay_scorer()
    yield
    reset_decay_scorer()


class TestAccessRecord:
    """Tests for the AccessRecord dataclass."""

    def test_defaults(self):
        r = AccessRecord(chunk_id="test:1-10")
        assert r.access_count == 0
        assert r.retention == 0.5  # Unknown = neutral

    def test_retention_after_one_access(self):
        r = AccessRecord(chunk_id="test:1-10", access_count=1, last_access=time.time())
        # days_since_last ~= 0, so retention = 1 - exp(-1/(0+1)) = 1 - exp(-1) ≈ 0.632
        assert abs(r.retention - (1 - math.exp(-1))) < 0.01

    def test_retention_decays_over_time(self):
        """Older accesses have lower retention."""
        now = time.time()
        recent = AccessRecord(chunk_id="a", access_count=1, last_access=now)
        old = AccessRecord(chunk_id="b", access_count=1, last_access=now - 86400 * 7)
        assert recent.retention > old.retention

    def test_more_accesses_increase_retention(self):
        """Frequently accessed chunks retain better."""
        now = time.time()
        few = AccessRecord(chunk_id="a", access_count=1, last_access=now)
        many = AccessRecord(chunk_id="b", access_count=10, last_access=now)
        assert many.retention > few.retention

    def test_avg_score(self):
        r = AccessRecord(chunk_id="test", access_count=4, total_score=3.2)
        assert abs(r.avg_score - 0.8) < 0.001

    def test_to_dict(self):
        r = AccessRecord(chunk_id="test:1-10", access_count=2, last_access=time.time())
        d = r.to_dict()
        assert d["chunk_id"] == "test:1-10"
        assert d["access_count"] == 2
        assert "retention" in d


class TestMemoryDecayScorer:
    """Tests for the MemoryDecayScorer."""

    def test_record_access(self):
        scorer = MemoryDecayScorer()
        rec = scorer.record_access("file.py:1-10", score=0.8)
        assert rec.access_count == 1
        assert rec.total_score == 0.8

    def test_multiple_accesses(self):
        scorer = MemoryDecayScorer()
        scorer.record_access("file.py:1-10", score=0.8)
        rec = scorer.record_access("file.py:1-10", score=0.6)
        assert rec.access_count == 2
        assert abs(rec.total_score - 1.4) < 0.001

    def test_unknown_chunk_neutral(self):
        scorer = MemoryDecayScorer()
        assert scorer.get_retention("unknown") == 0.5

    def test_adjust_score_unknown(self):
        """Unknown chunks get a neutral decay adjustment."""
        scorer = MemoryDecayScorer(decay_weight=0.3)
        adjusted = scorer.adjust_score("unknown", 1.0)
        # 1.0 * (0.3 * 0.5 + 0.7) = 1.0 * 0.85 = 0.85
        assert abs(adjusted - 0.85) < 0.01

    def test_adjust_score_fresh(self):
        """Freshly accessed chunks get high retention."""
        scorer = MemoryDecayScorer(decay_weight=0.3)
        scorer.record_access("fresh", score=0.9)
        adjusted = scorer.adjust_score("fresh", 1.0)
        # retention ≈ 0.632, so: 1.0 * (0.3 * 0.632 + 0.7) ≈ 0.8896
        assert adjusted > 0.85

    def test_zero_decay_weight(self):
        """With decay_weight=0, no adjustment happens."""
        scorer = MemoryDecayScorer(decay_weight=0.0)
        adjusted = scorer.adjust_score("anything", 0.75)
        assert abs(adjusted - 0.75) < 0.001

    def test_full_decay_weight(self):
        """With decay_weight=1.0, retention fully controls score."""
        scorer = MemoryDecayScorer(decay_weight=1.0)
        # Unknown chunk: retention = 0.5
        adjusted = scorer.adjust_score("unknown", 1.0)
        assert abs(adjusted - 0.5) < 0.01

    def test_apply_decay_to_scored(self):
        """Test applying decay to a list of ScoredChunk objects."""
        scorer = MemoryDecayScorer(decay_weight=0.3)
        # Pre-record one chunk to make it "known"
        scorer.record_access("known:1-10", score=0.9)
        scorer.record_access("known:1-10", score=0.8)

        chunks = [
            ScoredChunk(
                chunk=Chunk(file_path="known", start_line=1, end_line=10, content="..."),
                score=0.8,
                backend="tfidf",
            ),
            ScoredChunk(
                chunk=Chunk(file_path="unknown", start_line=1, end_line=10, content="..."),
                score=0.85,
                backend="tfidf",
            ),
        ]

        result = scorer.apply_decay_to_scored(chunks, record=True)
        # Both should have adjusted scores
        assert all(sc.score > 0 for sc in result)
        # Result should be sorted by adjusted score descending
        assert result[0].score >= result[1].score

    def test_max_tracked_eviction(self):
        """Test that stalest chunks are evicted when limit is reached."""
        scorer = MemoryDecayScorer(max_tracked=3)
        scorer.record_access("a", score=0.5)
        scorer.record_access("b", score=0.5)
        scorer.record_access("c", score=0.5)
        # All 3 tracked, now add a 4th - should evict stalest
        scorer.record_access("d", score=0.5)
        stats = scorer.get_stats()
        assert stats.tracked_chunks == 3

    def test_get_stats(self):
        scorer = MemoryDecayScorer()
        scorer.record_access("a", score=0.8)
        scorer.record_access("b", score=0.6)
        stats = scorer.get_stats()
        assert stats.tracked_chunks == 2
        assert stats.total_accesses == 2
        assert stats.avg_retention > 0

    def test_get_stale_chunks(self):
        scorer = MemoryDecayScorer()
        scorer.record_access("fresh")
        # Manually create a stale record
        scorer._records["stale"] = AccessRecord(
            chunk_id="stale",
            access_count=1,
            first_access=time.time() - 86400 * 30,
            last_access=time.time() - 86400 * 30,
        )
        stale = scorer.get_stale_chunks(limit=5)
        assert stale[0].chunk_id == "stale"

    def test_clear(self):
        scorer = MemoryDecayScorer()
        scorer.record_access("a")
        scorer.clear()
        stats = scorer.get_stats()
        assert stats.tracked_chunks == 0
        assert stats.total_accesses == 0


class TestDecayScorerStats:
    """Tests for DecayScorerStats."""

    def test_to_dict(self):
        stats = DecayScorerStats(
            tracked_chunks=10,
            total_accesses=50,
            avg_retention=0.75,
            stale_chunks=2,
        )
        d = stats.to_dict()
        assert d["tracked_chunks"] == 10
        assert d["stale_chunks"] == 2


class TestSingleton:
    """Tests for global singleton pattern."""

    def test_returns_same(self):
        a = get_decay_scorer()
        b = get_decay_scorer()
        assert a is b

    def test_reset_creates_new(self):
        a = get_decay_scorer()
        reset_decay_scorer()
        b = get_decay_scorer()
        assert a is not b
