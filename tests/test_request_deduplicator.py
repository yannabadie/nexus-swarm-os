"""
Tests for V12.4 Request Deduplicator.

Validates:
- Fingerprinting (deterministic, content-based)
- Check and register (new vs duplicate)
- Complete and fail status transitions
- Cached result retrieval
- TTL expiration
- Entry removal
- Cleanup
- Max entries enforcement
- Statistics tracking
- State management
- Global singleton
- Module exports
"""

import time

from core.infrastructure.resilience.request_deduplicator import (
    DeduplicationEntry,
    RequestDeduplicator,
    get_deduplicator,
    reset_deduplicator,
)

# =============================================================================
# DeduplicationEntry Tests
# =============================================================================


class TestDeduplicationEntry:
    """Test DeduplicationEntry dataclass."""

    def test_basic_creation(self):
        e = DeduplicationEntry(
            request_id="req1",
            fingerprint="abc123",
            status="pending",
        )
        assert e.request_id == "req1"
        assert e.status == "pending"

    def test_auto_timestamp(self):
        e = DeduplicationEntry(
            request_id="req1",
            fingerprint="abc",
            status="pending",
        )
        assert e.created_at > 0

    def test_not_expired(self):
        e = DeduplicationEntry(
            request_id="req1",
            fingerprint="abc",
            status="pending",
            ttl_seconds=300,
        )
        assert e.is_expired is False

    def test_expired(self):
        e = DeduplicationEntry(
            request_id="req1",
            fingerprint="abc",
            status="pending",
            ttl_seconds=0.0,  # Immediately expired
            created_at=time.monotonic() - 1,
        )
        assert e.is_expired is True

    def test_to_dict(self):
        e = DeduplicationEntry(
            request_id="req1",
            fingerprint="abcdef123456789",
            status="completed",
        )
        d = e.to_dict()
        assert d["request_id"] == "req1"
        assert d["status"] == "completed"
        assert len(d["fingerprint"]) == 12


# =============================================================================
# Check Tests
# =============================================================================


class TestCheck:
    """Test deduplication checking."""

    def test_first_check_not_duplicate(self):
        dd = RequestDeduplicator()
        result = dd.check("tool_exec", {"tool": "bash", "cmd": "ls"})
        assert result.is_duplicate is False
        assert result.status == "new"

    def test_second_check_is_duplicate(self):
        dd = RequestDeduplicator()
        dd.check("tool_exec", {"tool": "bash", "cmd": "ls"})
        result = dd.check("tool_exec", {"tool": "bash", "cmd": "ls"})
        assert result.is_duplicate is True
        assert result.status == "pending"

    def test_different_fields_not_duplicate(self):
        dd = RequestDeduplicator()
        dd.check("tool_exec", {"tool": "bash", "cmd": "ls"})
        result = dd.check("tool_exec", {"tool": "bash", "cmd": "pwd"})
        assert result.is_duplicate is False

    def test_different_operation_not_duplicate(self):
        dd = RequestDeduplicator()
        dd.check("tool_exec", {"cmd": "ls"})
        result = dd.check("api_call", {"cmd": "ls"})
        assert result.is_duplicate is False

    def test_check_returns_fingerprint(self):
        dd = RequestDeduplicator()
        result = dd.check("op", {"key": "val"})
        assert result.fingerprint
        assert len(result.fingerprint) == 64  # SHA-256

    def test_deterministic_fingerprint(self):
        dd = RequestDeduplicator()
        r1 = dd.check("op", {"a": 1, "b": 2})
        dd.clear()
        r2 = dd.check("op", {"b": 2, "a": 1})  # Same fields, different order
        assert r1.fingerprint == r2.fingerprint

    def test_check_increments_count(self):
        dd = RequestDeduplicator()
        dd.check("op", {"key": "val"})
        assert dd.entry_count == 1

    def test_is_duplicate_simple(self):
        dd = RequestDeduplicator()
        assert dd.is_duplicate("op", {"k": "v"}) is False
        dd.check("op", {"k": "v"})
        assert dd.is_duplicate("op", {"k": "v"}) is True


# =============================================================================
# Complete / Fail Tests
# =============================================================================


class TestCompleteAndFail:
    """Test status transitions."""

    def test_complete(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        assert dd.complete("op", {"k": "v"}, result="done") is True
        entry = dd.get_entry("op", {"k": "v"})
        assert entry.status == "completed"
        assert entry.result == "done"

    def test_complete_not_found(self):
        dd = RequestDeduplicator()
        assert dd.complete("op", {"k": "v"}) is False

    def test_complete_cached_result(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        dd.complete("op", {"k": "v"}, result={"data": [1, 2, 3]})
        result = dd.check("op", {"k": "v"})
        assert result.is_duplicate is True
        assert result.cached_result == {"data": [1, 2, 3]}
        assert result.status == "completed"

    def test_fail(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        assert dd.fail("op", {"k": "v"}) is True
        entry = dd.get_entry("op", {"k": "v"})
        assert entry.status == "failed"

    def test_fail_not_found(self):
        dd = RequestDeduplicator()
        assert dd.fail("op", {"k": "v"}) is False

    def test_fail_still_deduplicates(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        dd.fail("op", {"k": "v"})
        result = dd.check("op", {"k": "v"})
        assert result.is_duplicate is True
        assert result.status == "failed"


# =============================================================================
# Remove Tests
# =============================================================================


class TestRemove:
    """Test entry removal."""

    def test_remove(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        assert dd.remove("op", {"k": "v"}) is True
        assert dd.entry_count == 0

    def test_remove_not_found(self):
        dd = RequestDeduplicator()
        assert dd.remove("op", {"k": "v"}) is False

    def test_remove_allows_retry(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        dd.remove("op", {"k": "v"})
        result = dd.check("op", {"k": "v"})
        assert result.is_duplicate is False


# =============================================================================
# TTL Tests
# =============================================================================


class TestTTL:
    """Test TTL expiration."""

    def test_expired_not_duplicate(self):
        dd = RequestDeduplicator(default_ttl=0.01)  # 10ms TTL
        dd.check("op", {"k": "v"})
        time.sleep(0.02)  # Wait for expiration
        result = dd.check("op", {"k": "v"})
        assert result.is_duplicate is False

    def test_custom_ttl(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"}, ttl=0.01)
        time.sleep(0.02)
        result = dd.check("op", {"k": "v"})
        assert result.is_duplicate is False

    def test_cleanup_expired(self):
        dd = RequestDeduplicator(default_ttl=0.01)
        dd.check("op1", {"k": "a"})
        dd.check("op2", {"k": "b"})
        time.sleep(0.02)
        count = dd.cleanup_expired()
        assert count == 2
        assert dd.entry_count == 0


# =============================================================================
# Max Entries Tests
# =============================================================================


class TestMaxEntries:
    """Test max entries enforcement."""

    def test_max_entries(self):
        dd = RequestDeduplicator(max_entries=3)
        dd.check("op", {"i": 1})
        dd.check("op", {"i": 2})
        dd.check("op", {"i": 3})
        dd.check("op", {"i": 4})
        assert dd.entry_count == 3


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test statistics tracking."""

    def test_stats_initial(self):
        dd = RequestDeduplicator()
        stats = dd.get_stats()
        assert stats.total_checks == 0
        assert stats.duplicates_caught == 0

    def test_stats_after_checks(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        dd.check("op", {"k": "v"})  # duplicate
        dd.check("op", {"k": "v2"})
        stats = dd.get_stats()
        assert stats.total_checks == 3
        assert stats.duplicates_caught == 1

    def test_duplicate_rate(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        dd.check("op", {"k": "v"})
        stats = dd.get_stats()
        assert stats.duplicate_rate == 0.5

    def test_stats_to_dict(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        stats = dd.get_stats()
        d = stats.to_dict()
        assert "total_checks" in d
        assert "duplicates_caught" in d
        assert "duplicate_rate" in d

    def test_check_result_to_dict(self):
        dd = RequestDeduplicator()
        result = dd.check("op", {"k": "v"})
        d = result.to_dict()
        assert d["is_duplicate"] is False
        assert d["status"] == "new"


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_entry_count(self):
        dd = RequestDeduplicator()
        assert dd.entry_count == 0
        dd.check("op", {"k": "v"})
        assert dd.entry_count == 1

    def test_pending_count(self):
        dd = RequestDeduplicator()
        dd.check("op1", {"k": "a"})
        dd.check("op2", {"k": "b"})
        dd.complete("op1", {"k": "a"})
        assert dd.pending_count == 1
        assert dd.completed_count == 1

    def test_clear(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        dd.check("op", {"k": "v"})
        dd.clear()
        assert dd.entry_count == 0
        stats = dd.get_stats()
        assert stats.total_checks == 0

    def test_to_dict(self):
        dd = RequestDeduplicator()
        dd.check("op", {"k": "v"})
        d = dd.to_dict()
        assert d["entry_count"] == 1
        assert "total_checks" in d
        assert "duplicate_rate" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global deduplicator."""

    def test_get_deduplicator(self):
        reset_deduplicator()
        dd = get_deduplicator()
        assert isinstance(dd, RequestDeduplicator)

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

    def test_from_resilience_package(self):
        from core.infrastructure.resilience import (
            CheckResult,
            DeduplicationEntry,
            DeduplicationStats,
            RequestDeduplicator,
            get_deduplicator,
            reset_deduplicator,
        )

        assert all(
            [
                RequestDeduplicator,
                DeduplicationEntry,
                CheckResult,
                DeduplicationStats,
                get_deduplicator,
                reset_deduplicator,
            ]
        )

    def test_from_module(self):
        from core.infrastructure.resilience.request_deduplicator import (
            DEFAULT_TTL_SECONDS,
            MAX_ENTRIES,
        )

        assert DEFAULT_TTL_SECONDS == 300
        assert MAX_ENTRIES == 10_000
