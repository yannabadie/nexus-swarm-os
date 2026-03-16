"""
Tests for V12.4 Context Compressor.

Validates:
- Turn creation and importance scoring
- Adding turns with auto-scoring
- Low importance pattern detection
- High importance pattern detection
- Compression (pruning low-importance turns)
- Pinned turns protection
- Archive tracking
- Context shift detection
- Should-compress threshold
- Pin/unpin operations
- State management
- Global singleton
- Module exports
"""

from core.memory_pkg.memory.context_compressor import (
    CompressionResult,
    CompressTurn,
    ContextCompressor,
    ContextShift,
    get_compressor,
    reset_compressor,
)

# =============================================================================
# CompressTurn Tests
# =============================================================================


class TestCompressTurn:
    """Test CompressTurn dataclass."""

    def test_basic_creation(self):
        turn = CompressTurn(turn_id=0, role="user", content="Hello world")
        assert turn.turn_id == 0
        assert turn.role == "user"
        assert turn.content == "Hello world"

    def test_auto_timestamp(self):
        turn = CompressTurn(turn_id=0, role="user", content="test")
        assert turn.timestamp > 0

    def test_auto_token_estimate(self):
        turn = CompressTurn(turn_id=0, role="user", content="one two three four five")
        assert turn.token_estimate > 0

    def test_to_dict(self):
        turn = CompressTurn(turn_id=1, role="assistant", content="Some response", importance=0.8)
        d = turn.to_dict()
        assert d["turn_id"] == 1
        assert d["role"] == "assistant"
        assert d["importance"] == 0.8


# =============================================================================
# Importance Scoring Tests
# =============================================================================


class TestImportanceScoring:
    """Test automatic importance scoring."""

    def test_low_importance_ok(self):
        c = ContextCompressor()
        turn = c.add_turn("user", "ok")
        assert turn.importance < 0.3

    def test_low_importance_thanks(self):
        c = ContextCompressor()
        turn = c.add_turn("user", "thanks")
        assert turn.importance < 0.3

    def test_low_importance_yes(self):
        c = ContextCompressor()
        turn = c.add_turn("user", "yes")
        assert turn.importance < 0.3

    def test_high_importance_decision(self):
        c = ContextCompressor()
        turn = c.add_turn(
            "assistant",
            "I decided to use the approach with microservices because of the trade-off between scalability and simplicity.",
        )
        assert turn.importance > 0.5

    def test_high_importance_error(self):
        c = ContextCompressor()
        turn = c.add_turn("assistant", "Found a critical error in the auth module that needs fixing.")
        assert turn.importance > 0.5

    def test_system_role_boost(self):
        c = ContextCompressor()
        turn = c.add_turn("system", "You are a helpful assistant")
        assert turn.importance > 0.5

    def test_long_content_boost(self):
        c = ContextCompressor()
        content = " ".join(["word"] * 120)
        turn = c.add_turn("assistant", content)
        assert turn.importance > 0.5

    def test_short_content_penalty(self):
        c = ContextCompressor()
        turn = c.add_turn("user", "what?")
        assert turn.importance < 0.5

    def test_explicit_importance(self):
        c = ContextCompressor()
        turn = c.add_turn("user", "ok", importance=0.9)
        assert turn.importance == 0.9

    def test_importance_clamped(self):
        c = ContextCompressor()
        turn = c.add_turn("user", "test", importance=1.5)
        assert turn.importance == 1.0
        turn2 = c.add_turn("user", "test", importance=-0.5)
        assert turn2.importance == 0.0


# =============================================================================
# Add Turn Tests
# =============================================================================


class TestAddTurn:
    """Test adding turns."""

    def test_add_basic(self):
        c = ContextCompressor()
        turn = c.add_turn("user", "Hello")
        assert turn.role == "user"
        assert c.active_count == 1

    def test_add_multiple(self):
        c = ContextCompressor()
        c.add_turn("user", "Hello")
        c.add_turn("assistant", "Hi there")
        c.add_turn("user", "How are you?")
        assert c.active_count == 3

    def test_add_pinned(self):
        c = ContextCompressor()
        turn = c.add_turn("system", "System prompt", pinned=True)
        assert turn.pinned is True

    def test_add_with_metadata(self):
        c = ContextCompressor()
        turn = c.add_turn("user", "test", metadata={"source": "api"})
        assert turn.metadata == {"source": "api"}

    def test_sequential_ids(self):
        c = ContextCompressor()
        t0 = c.add_turn("user", "first")
        t1 = c.add_turn("user", "second")
        t2 = c.add_turn("user", "third")
        assert t0.turn_id == 0
        assert t1.turn_id == 1
        assert t2.turn_id == 2


# =============================================================================
# Compression Tests
# =============================================================================


class TestCompression:
    """Test compression operations."""

    def test_no_compression_needed(self):
        c = ContextCompressor(max_tokens=10000)
        c.add_turn("user", "Hello")
        result = c.compress()
        assert result.turns_pruned == 0
        assert result.turns_before == result.turns_after

    def test_compress_removes_low_importance(self):
        c = ContextCompressor(max_tokens=100)
        c.add_turn(
            "user",
            "Analyze the auth module for security vulnerabilities and provide a comprehensive report with detailed findings",
        )
        c.add_turn(
            "assistant",
            "I found several critical issues in the authentication system that need immediate attention and fixing right away",
        )
        c.add_turn("user", "ok")
        c.add_turn("user", "thanks")
        c.add_turn("user", "yes")

        result = c.compress(target_tokens=15)
        assert result.turns_pruned > 0
        assert result.turns_after < result.turns_before

    def test_compress_preserves_pinned(self):
        c = ContextCompressor(max_tokens=50)
        c.add_turn("system", "System prompt", pinned=True)
        c.add_turn("user", "ok")
        c.add_turn("user", "thanks")
        c.add_turn("user", "sure")

        c.compress(target_tokens=10)
        active = c.get_active_turns()
        assert any(t.pinned for t in active)

    def test_compress_archives(self):
        c = ContextCompressor(max_tokens=50)
        c.add_turn("user", "ok")
        c.add_turn("user", "thanks")
        c.add_turn("user", "Important detailed analysis with many decision words and rationale")

        c.compress(target_tokens=10)
        assert c.archived_count > 0

    def test_compression_result(self):
        c = ContextCompressor(max_tokens=50)
        c.add_turn("user", "ok")
        c.add_turn("user", "thanks")
        c.add_turn("user", "A longer message with more content")

        result = c.compress(target_tokens=10)
        assert result.tokens_before > 0
        assert result.turns_before == 3
        assert isinstance(result.compression_ratio, float)

    def test_compression_result_to_dict(self):
        result = CompressionResult(
            turns_before=10,
            turns_after=6,
            tokens_before=1000,
            tokens_after=600,
            turns_pruned=4,
            turns_archived=4,
        )
        d = result.to_dict()
        assert d["turns_pruned"] == 4
        assert d["compression_ratio"] == 0.4

    def test_compression_ratio_empty(self):
        result = CompressionResult(
            turns_before=0,
            turns_after=0,
            tokens_before=0,
            tokens_after=0,
            turns_pruned=0,
            turns_archived=0,
        )
        assert result.compression_ratio == 0.0

    def test_multiple_compressions(self):
        c = ContextCompressor(max_tokens=200)
        for i in range(20):
            c.add_turn("user", f"This is message number {i} with some extra words to make it longer")
        c.compress(target_tokens=20)
        for i in range(20):
            c.add_turn("user", f"Another round of messages number {i} with additional padding content")
        c.compress(target_tokens=20)
        assert c.compression_count == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQuery:
    """Test querying turns."""

    def test_get_active_turns(self):
        c = ContextCompressor()
        c.add_turn("user", "Hello")
        c.add_turn("assistant", "Hi")
        turns = c.get_active_turns()
        assert len(turns) == 2

    def test_get_archived_turns(self):
        c = ContextCompressor(max_tokens=50)
        c.add_turn("user", "ok")
        c.add_turn("user", "thanks")
        c.add_turn("user", "Important content with many words in it")
        c.compress(target_tokens=10)
        archived = c.get_archived_turns()
        assert len(archived) > 0

    def test_get_turn_by_id(self):
        c = ContextCompressor()
        t = c.add_turn("user", "Hello")
        found = c.get_turn(t.turn_id)
        assert found is not None
        assert found.content == "Hello"

    def test_get_turn_from_archive(self):
        c = ContextCompressor(max_tokens=50)
        t = c.add_turn("user", "ok")
        c.add_turn("user", "Important content with many decision words and rationale for the approach")
        c.compress(target_tokens=10)
        # The "ok" turn should be archived but still findable
        found = c.get_turn(t.turn_id)
        assert found is not None

    def test_get_turn_not_found(self):
        c = ContextCompressor()
        assert c.get_turn(999) is None

    def test_should_compress(self):
        c = ContextCompressor(max_tokens=100, compress_threshold=0.8)
        # Add turns until we exceed 80% of budget
        for i in range(50):
            c.add_turn("user", f"This is a message with enough content to fill tokens {i}")
        assert c.should_compress() is True

    def test_should_not_compress(self):
        c = ContextCompressor(max_tokens=10000)
        c.add_turn("user", "Short message")
        assert c.should_compress() is False


# =============================================================================
# Pin/Unpin Tests
# =============================================================================


class TestPinUnpin:
    """Test pin/unpin operations."""

    def test_pin_turn(self):
        c = ContextCompressor()
        t = c.add_turn("user", "Important message")
        assert c.pin_turn(t.turn_id) is True
        assert c.get_turn(t.turn_id).pinned is True

    def test_pin_nonexistent(self):
        c = ContextCompressor()
        assert c.pin_turn(999) is False

    def test_unpin_turn(self):
        c = ContextCompressor()
        t = c.add_turn("user", "message", pinned=True)
        assert c.unpin_turn(t.turn_id) is True
        assert c.get_turn(t.turn_id).pinned is False

    def test_unpin_nonexistent(self):
        c = ContextCompressor()
        assert c.unpin_turn(999) is False


# =============================================================================
# Context Shift Tests
# =============================================================================


class TestContextShift:
    """Test context shift detection."""

    def test_no_shift_similar_content(self):
        c = ContextCompressor()
        for _ in range(5):
            c.add_turn("user", "Tell me about Python authentication security")
            c.add_turn("assistant", "Python authentication security involves checking tokens and validating sessions")
        shift = c.detect_context_shift()
        assert shift is None  # Same topic throughout

    def test_shift_detected(self):
        c = ContextCompressor()
        # First half about cooking
        c.add_turn("user", "Tell me about baking chocolate cakes and pastries")
        c.add_turn("assistant", "Baking chocolate cakes requires flour sugar butter eggs and chocolate")
        # Second half about programming
        c.add_turn("user", "Now explain Python Django REST framework microservices")
        c.add_turn("assistant", "Python Django REST framework handles microservices with endpoints serializers views")
        shift = c.detect_context_shift()
        assert shift is not None
        assert shift.confidence > 0.5

    def test_no_shift_too_few_turns(self):
        c = ContextCompressor()
        c.add_turn("user", "Hello")
        c.add_turn("assistant", "Hi")
        assert c.detect_context_shift() is None

    def test_shift_to_dict(self):
        shift = ContextShift(
            turn_id=5,
            old_topic="auth, security",
            new_topic="database, schema",
            confidence=0.85,
        )
        d = shift.to_dict()
        assert d["turn_id"] == 5
        assert d["confidence"] == 0.85


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_active_count(self):
        c = ContextCompressor()
        assert c.active_count == 0
        c.add_turn("user", "Hello")
        assert c.active_count == 1

    def test_archived_count(self):
        c = ContextCompressor()
        assert c.archived_count == 0

    def test_total_tokens(self):
        c = ContextCompressor()
        c.add_turn("user", "one two three")
        assert c.total_tokens > 0

    def test_max_tokens(self):
        c = ContextCompressor(max_tokens=5000)
        assert c.max_tokens == 5000

    def test_utilization(self):
        c = ContextCompressor(max_tokens=1000)
        c.add_turn("user", "Hello world")
        assert 0 < c.utilization < 1.0

    def test_utilization_empty(self):
        c = ContextCompressor(max_tokens=0)
        assert c.utilization == 0.0

    def test_clear(self):
        c = ContextCompressor()
        c.add_turn("user", "Hello")
        c.clear()
        assert c.active_count == 0
        assert c.archived_count == 0
        assert c.compression_count == 0

    def test_to_dict(self):
        c = ContextCompressor(max_tokens=1000)
        c.add_turn("user", "Hello")
        d = c.to_dict()
        assert d["active_count"] == 1
        assert d["max_tokens"] == 1000
        assert "utilization" in d
        assert "should_compress" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global compressor."""

    def test_get_compressor(self):
        reset_compressor()
        c = get_compressor()
        assert isinstance(c, ContextCompressor)

    def test_singleton(self):
        reset_compressor()
        c1 = get_compressor()
        c2 = get_compressor()
        assert c1 is c2

    def test_reset(self):
        reset_compressor()
        c1 = get_compressor()
        reset_compressor()
        c2 = get_compressor()
        assert c1 is not c2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_memory_package(self):
        from core.memory_pkg.memory import (
            CompressionResult,
            CompressTurn,
            ContextCompressor,
            ContextShift,
            get_compressor,
            reset_compressor,
        )

        assert all(
            [
                ContextCompressor,
                CompressTurn,
                CompressionResult,
                ContextShift,
                get_compressor,
                reset_compressor,
            ]
        )

    def test_from_module(self):
        from core.memory_pkg.memory.context_compressor import (
            CompressionResult,
            CompressTurn,
            ContextCompressor,
        )

        assert all([ContextCompressor, CompressTurn, CompressionResult])
