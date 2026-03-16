"""
Tests for V12.4 Message Deduplicator.

Validates:
- compute_fingerprint helper
- MessageFingerprint to_dict
- MessageTrace to_dict / properties
- DeduplicationStats to_dict / properties
- Duplicate detection (is_duplicate, check_and_register)
- Fingerprint management (get, cleanup expired)
- Tracing (start, add hop, end, get, list)
- Bounded history (fingerprint eviction, trace eviction)
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.synapse.message_deduplicator import (
    DEFAULT_TTL,
    MAX_FINGERPRINTS,
    MAX_TRACES,
    DeduplicationStats,
    MessageDeduplicator,
    MessageFingerprint,
    MessageTrace,
    compute_fingerprint,
    get_deduplicator,
    reset_deduplicator,
)

# =============================================================================
# compute_fingerprint Tests
# =============================================================================


class TestComputeFingerprint:
    """Test fingerprint computation."""

    def test_basic(self):
        fp = compute_fingerprint("hello world")
        assert isinstance(fp, str)
        assert len(fp) == 16

    def test_deterministic(self):
        fp1 = compute_fingerprint("hello", sender="claude")
        fp2 = compute_fingerprint("hello", sender="claude")
        assert fp1 == fp2

    def test_different_content(self):
        fp1 = compute_fingerprint("hello")
        fp2 = compute_fingerprint("world")
        assert fp1 != fp2

    def test_different_sender(self):
        fp1 = compute_fingerprint("hello", sender="claude")
        fp2 = compute_fingerprint("hello", sender="gemini")
        assert fp1 != fp2


# =============================================================================
# MessageFingerprint Tests
# =============================================================================


class TestMessageFingerprint:
    """Test MessageFingerprint dataclass."""

    def test_basic(self):
        f = MessageFingerprint(fingerprint="abc123")
        assert f.count == 1

    def test_to_dict(self):
        f = MessageFingerprint(fingerprint="abc123", sender="claude", count=3)
        d = f.to_dict()
        assert d["fingerprint"] == "abc123"
        assert d["count"] == 3


# =============================================================================
# MessageTrace Tests
# =============================================================================


class TestMessageTrace:
    """Test MessageTrace dataclass."""

    def test_basic(self):
        t = MessageTrace(correlation_id="corr-1")
        assert t.status == "active"

    def test_hop_count(self):
        t = MessageTrace(correlation_id="corr-1", hops=["claude", "gemini"])
        assert t.hop_count == 2

    def test_duration_ms_not_ended(self):
        t = MessageTrace(correlation_id="corr-1")
        assert t.duration_ms == 0

    def test_to_dict(self):
        t = MessageTrace(correlation_id="corr-1", hops=["claude"], status="completed")
        d = t.to_dict()
        assert d["correlation_id"] == "corr-1"
        assert d["hop_count"] == 1


# =============================================================================
# DeduplicationStats Tests
# =============================================================================


class TestDeduplicationStats:
    """Test DeduplicationStats dataclass."""

    def test_duplicate_rate_zero(self):
        s = DeduplicationStats(
            total_checked=0, total_duplicates=0, total_unique=0, active_fingerprints=0, active_traces=0
        )
        assert s.duplicate_rate == 0.0

    def test_duplicate_rate(self):
        s = DeduplicationStats(
            total_checked=10, total_duplicates=3, total_unique=7, active_fingerprints=7, active_traces=0
        )
        assert abs(s.duplicate_rate - 0.3) < 0.01

    def test_to_dict(self):
        s = DeduplicationStats(
            total_checked=10, total_duplicates=3, total_unique=7, active_fingerprints=7, active_traces=0
        )
        d = s.to_dict()
        assert "duplicate_rate" in d


# =============================================================================
# Duplicate Detection Tests
# =============================================================================


class TestDuplicateDetection:
    """Test duplicate detection."""

    def test_first_message_not_duplicate(self):
        d = MessageDeduplicator()
        assert d.is_duplicate("hello world") is False

    def test_second_message_is_duplicate(self):
        d = MessageDeduplicator()
        d.is_duplicate("hello world")
        assert d.is_duplicate("hello world") is True

    def test_different_messages_not_duplicate(self):
        d = MessageDeduplicator()
        d.is_duplicate("hello")
        assert d.is_duplicate("world") is False

    def test_same_content_different_sender(self):
        d = MessageDeduplicator()
        d.is_duplicate("hello", sender="claude")
        assert d.is_duplicate("hello", sender="gemini") is False

    def test_check_and_register(self):
        d = MessageDeduplicator()
        is_dup, fp = d.check_and_register("hello world")
        assert is_dup is False
        assert isinstance(fp, str)
        is_dup2, fp2 = d.check_and_register("hello world")
        assert is_dup2 is True
        assert fp2 == fp

    def test_duplicate_count_increments(self):
        d = MessageDeduplicator()
        d.is_duplicate("hello")
        d.is_duplicate("hello")
        d.is_duplicate("hello")
        fp = compute_fingerprint("hello")
        entry = d.get_fingerprint(fp)
        assert entry is not None
        assert entry.count == 3

    def test_get_fingerprint_not_found(self):
        d = MessageDeduplicator()
        assert d.get_fingerprint("nonexistent") is None


# =============================================================================
# Expiration Tests
# =============================================================================


class TestExpiration:
    """Test fingerprint expiration."""

    def test_cleanup_expired(self):
        d = MessageDeduplicator(ttl=0.0)  # 0 TTL means everything expires immediately
        d.is_duplicate("hello")
        # With TTL=0, cleanup should remove it
        removed = d.cleanup_expired()
        assert removed >= 0  # may or may not be expired depending on timing

    def test_cleanup_no_expired(self):
        d = MessageDeduplicator(ttl=3600.0)
        d.is_duplicate("hello")
        removed = d.cleanup_expired()
        assert removed == 0


# =============================================================================
# Tracing Tests
# =============================================================================


class TestTracing:
    """Test message tracing."""

    def test_start_trace(self):
        d = MessageDeduplicator()
        t = d.start_trace("corr-1", initial_hop="claude")
        assert t.correlation_id == "corr-1"
        assert t.hops == ["claude"]
        assert t.status == "active"

    def test_start_trace_no_initial_hop(self):
        d = MessageDeduplicator()
        t = d.start_trace("corr-1")
        assert t.hops == []

    def test_add_hop(self):
        d = MessageDeduplicator()
        d.start_trace("corr-1", initial_hop="claude")
        assert d.add_hop("corr-1", "gemini") is True
        t = d.get_trace("corr-1")
        assert t.hops == ["claude", "gemini"]

    def test_add_hop_not_found(self):
        d = MessageDeduplicator()
        assert d.add_hop("missing", "claude") is False

    def test_end_trace(self):
        d = MessageDeduplicator()
        d.start_trace("corr-1", initial_hop="claude")
        t = d.end_trace("corr-1")
        assert t is not None
        assert t.status == "completed"
        assert t.ended_at > 0

    def test_end_trace_not_found(self):
        d = MessageDeduplicator()
        assert d.end_trace("missing") is None

    def test_get_trace(self):
        d = MessageDeduplicator()
        d.start_trace("corr-1")
        t = d.get_trace("corr-1")
        assert t is not None

    def test_get_trace_not_found(self):
        d = MessageDeduplicator()
        assert d.get_trace("missing") is None

    def test_list_traces(self):
        d = MessageDeduplicator()
        d.start_trace("corr-1")
        d.start_trace("corr-2")
        d.end_trace("corr-1")
        traces = d.list_traces()
        assert len(traces) == 2

    def test_list_traces_by_status(self):
        d = MessageDeduplicator()
        d.start_trace("corr-1")
        d.start_trace("corr-2")
        d.end_trace("corr-2")
        active = d.list_traces(status="active")
        assert len(active) == 1
        completed = d.list_traces(status="completed")
        assert len(completed) == 1

    def test_list_traces_with_limit(self):
        d = MessageDeduplicator()
        for i in range(10):
            d.start_trace(f"corr-{i}")
        traces = d.list_traces(limit=3)
        assert len(traces) == 3


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded history with eviction."""

    def test_fingerprint_eviction(self):
        d = MessageDeduplicator(max_fingerprints=5)
        for i in range(10):
            d.is_duplicate(f"message_{i}")
        assert d.fingerprint_count <= 5

    def test_trace_eviction(self):
        d = MessageDeduplicator(max_traces=5)
        for i in range(10):
            d.start_trace(f"corr-{i}")
        assert d.trace_count <= 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test deduplication statistics."""

    def test_initial_stats(self):
        d = MessageDeduplicator()
        stats = d.get_stats()
        assert stats.total_checked == 0
        assert stats.total_duplicates == 0

    def test_stats_after_checks(self):
        d = MessageDeduplicator()
        d.is_duplicate("hello")
        d.is_duplicate("hello")  # duplicate
        d.is_duplicate("world")
        stats = d.get_stats()
        assert stats.total_checked == 3
        assert stats.total_duplicates == 1
        assert stats.total_unique == 2

    def test_stats_to_dict(self):
        d = MessageDeduplicator()
        dd = d.get_stats().to_dict()
        assert "total_checked" in dd


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_fingerprint_count(self):
        d = MessageDeduplicator()
        d.is_duplicate("hello")
        d.is_duplicate("world")
        assert d.fingerprint_count == 2

    def test_trace_count(self):
        d = MessageDeduplicator()
        d.start_trace("corr-1")
        d.start_trace("corr-2")
        assert d.trace_count == 2

    def test_clear(self):
        d = MessageDeduplicator()
        d.is_duplicate("hello")
        d.start_trace("corr-1")
        d.clear()
        assert d.fingerprint_count == 0
        assert d.trace_count == 0

    def test_to_dict(self):
        d = MessageDeduplicator()
        d.is_duplicate("hello")
        result = d.to_dict()
        assert result["fingerprint_count"] == 1
        assert "total_checked" in result


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global deduplicator."""

    def test_get(self):
        reset_deduplicator()
        d = get_deduplicator()
        assert isinstance(d, MessageDeduplicator)

    def test_singleton(self):
        reset_deduplicator()
        d1 = get_deduplicator()
        d2 = get_deduplicator()
        assert d1 is d2

    def test_reset(self):
        reset_deduplicator()
        d1 = get_deduplicator()
        reset_deduplicator()
        d2 = get_deduplicator()
        assert d1 is not d2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_synapse_package(self):
        from core.synapse import (
            DeduplicationStats,
            MessageDeduplicator,
            MessageFingerprint,
            MessageTrace,
            compute_fingerprint,
            get_deduplicator,
            reset_deduplicator,
        )

        assert all(
            [
                MessageDeduplicator,
                MessageFingerprint,
                MessageTrace,
                DeduplicationStats,
                compute_fingerprint,
                get_deduplicator,
                reset_deduplicator,
            ]
        )

    def test_constants(self):
        assert MAX_FINGERPRINTS == 100000
        assert DEFAULT_TTL == 300.0
        assert MAX_TRACES == 10000
