"""
Tests for V12.4 Context Window Manager.

Validates:
- Token estimation (character-based heuristic)
- Model context window lookup
- ContextMessage creation and auto-estimation
- ContextManager tracking (used, remaining, utilization)
- Smart truncation (pinned messages preserved, LRU trimming)
- Can-fit budget checking
- Context utilization report
- Module exports
"""

from core.drivers.context_manager import (
    DEFAULT_CONTEXT_WINDOW,
    MODEL_CONTEXT_WINDOWS,
    ContextManager,
    ContextMessage,
    ContextUtilization,
    estimate_tokens,
    get_context_window,
)

# =============================================================================
# Token Estimation Tests
# =============================================================================


class TestEstimateTokens:
    """Test token estimation."""

    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        assert estimate_tokens("Hi") >= 1

    def test_known_length(self):
        # 100 chars / 4 chars_per_token = 25 tokens
        text = "x" * 100
        assert estimate_tokens(text) == 25

    def test_minimum_one_token(self):
        assert estimate_tokens("a") >= 1


# =============================================================================
# Context Window Lookup Tests
# =============================================================================


class TestGetContextWindow:
    """Test model context window lookup."""

    def test_claude_opus(self):
        assert get_context_window("claude-opus-4-6-20250116") == 200_000

    def test_claude_sonnet(self):
        assert get_context_window("claude-sonnet-4-5-20250929") == 200_000

    def test_gemini_pro(self):
        assert get_context_window("gemini-3-pro") == 1_000_000

    def test_llama(self):
        assert get_context_window("llama3.1") == 128_000

    def test_unknown_model(self):
        assert get_context_window("unknown-model-xyz") == DEFAULT_CONTEXT_WINDOW

    def test_model_context_windows_populated(self):
        assert len(MODEL_CONTEXT_WINDOWS) >= 8


# =============================================================================
# ContextMessage Tests
# =============================================================================


class TestContextMessage:
    """Test ContextMessage dataclass."""

    def test_basic_creation(self):
        msg = ContextMessage(role="user", content="Hello world")
        assert msg.role == "user"
        assert msg.content == "Hello world"
        assert msg.token_count > 0

    def test_auto_estimation(self):
        msg = ContextMessage(role="user", content="x" * 400)
        assert msg.token_count == 100  # 400 / 4

    def test_explicit_token_count(self):
        msg = ContextMessage(role="user", content="Hello", token_count=50)
        assert msg.token_count == 50

    def test_pinned_default(self):
        msg = ContextMessage(role="user", content="test")
        assert msg.pinned is False

    def test_pinned_explicit(self):
        msg = ContextMessage(role="system", content="You are helpful", pinned=True)
        assert msg.pinned is True

    def test_to_dict(self):
        msg = ContextMessage(role="assistant", content="Hello!", token_count=10, pinned=True)
        d = msg.to_dict()
        assert d["role"] == "assistant"
        assert d["content_length"] == 6
        assert d["token_count"] == 10
        assert d["pinned"] is True


# =============================================================================
# ContextManager - Initialization Tests
# =============================================================================


class TestContextManagerInit:
    """Test context manager initialization."""

    def test_default_init(self):
        ctx = ContextManager()
        assert ctx.model == "claude-sonnet-4-6"
        assert ctx.max_tokens == 200_000
        assert ctx.message_count == 0

    def test_custom_model(self):
        ctx = ContextManager(model="gemini-3-pro")
        assert ctx.max_tokens == 1_000_000

    def test_custom_max_tokens(self):
        ctx = ContextManager(max_tokens=50_000)
        assert ctx.max_tokens == 50_000

    def test_initial_state(self):
        ctx = ContextManager()
        assert ctx.used_tokens == 0
        assert ctx.remaining_tokens == ctx.max_tokens
        assert ctx.utilization == 0.0


# =============================================================================
# ContextManager - Message Tracking Tests
# =============================================================================


class TestMessageTracking:
    """Test message tracking and token counting."""

    def test_add_message(self):
        ctx = ContextManager()
        msg = ctx.add_message("user", "Hello world")
        assert msg.role == "user"
        assert ctx.message_count == 1
        assert ctx.used_tokens > 0

    def test_multiple_messages(self):
        ctx = ContextManager()
        ctx.add_message("system", "You are helpful")
        ctx.add_message("user", "What is NEXUS?")
        ctx.add_message("assistant", "NEXUS is a multi-agent orchestrator.")
        assert ctx.message_count == 3
        assert ctx.used_tokens > 0

    def test_used_tokens_accumulate(self):
        ctx = ContextManager()
        ctx.add_message("user", "x" * 400, token_count=100)
        ctx.add_message("assistant", "y" * 800, token_count=200)
        assert ctx.used_tokens == 300

    def test_remaining_decreases(self):
        ctx = ContextManager(max_tokens=1000)
        initial = ctx.remaining_tokens
        ctx.add_message("user", "Hello", token_count=100)
        assert ctx.remaining_tokens == initial - 100

    def test_utilization(self):
        ctx = ContextManager(max_tokens=1000)
        ctx.add_message("user", "Hello", token_count=100)
        assert ctx.utilization == 0.1  # 100/1000

    def test_pinned_message(self):
        ctx = ContextManager()
        msg = ctx.add_message("system", "You are helpful", pinned=True)
        assert msg.pinned is True

    def test_get_messages(self):
        ctx = ContextManager()
        ctx.add_message("user", "A")
        ctx.add_message("assistant", "B")
        msgs = ctx.get_messages()
        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[1].role == "assistant"


# =============================================================================
# ContextManager - Budget Checking Tests
# =============================================================================


class TestBudgetChecking:
    """Test budget checking."""

    def test_can_fit_within_budget(self):
        ctx = ContextManager(max_tokens=10000, reserve_tokens=1000)
        assert ctx.can_fit(5000) is True

    def test_cannot_fit_over_budget(self):
        ctx = ContextManager(max_tokens=10000, reserve_tokens=1000)
        assert ctx.can_fit(10000) is False  # Exceeds effective remaining

    def test_effective_remaining(self):
        ctx = ContextManager(max_tokens=10000, reserve_tokens=2000)
        assert ctx.effective_remaining == 8000

    def test_effective_remaining_with_messages(self):
        ctx = ContextManager(max_tokens=10000, reserve_tokens=2000)
        ctx.add_message("user", "test", token_count=3000)
        assert ctx.effective_remaining == 5000  # 10000 - 3000 - 2000


# =============================================================================
# ContextManager - Truncation Tests
# =============================================================================


class TestTruncation:
    """Test smart truncation."""

    def test_no_truncation_within_budget(self):
        ctx = ContextManager(max_tokens=10000, reserve_tokens=1000)
        ctx.add_message("user", "A", token_count=100)
        ctx.add_message("assistant", "B", token_count=100)
        msgs = ctx.get_truncated_history()
        assert len(msgs) == 2

    def test_truncates_oldest(self):
        ctx = ContextManager(max_tokens=500, reserve_tokens=100)
        ctx.add_message("user", "Old", token_count=200)
        ctx.add_message("user", "Mid", token_count=200)
        ctx.add_message("user", "New", token_count=200)
        # Budget = 500 - 100 = 400. Total = 600 > 400
        msgs = ctx.get_truncated_history()
        assert len(msgs) == 2
        assert msgs[0].content == "Mid"
        assert msgs[1].content == "New"

    def test_pinned_never_truncated(self):
        ctx = ContextManager(max_tokens=500, reserve_tokens=100)
        ctx.add_message("system", "PINNED", token_count=200, pinned=True)
        ctx.add_message("user", "Old", token_count=200)
        ctx.add_message("user", "New", token_count=200)
        # Budget = 400. Pinned uses 200. Remaining 200 for unpinned.
        msgs = ctx.get_truncated_history()
        assert any(m.content == "PINNED" for m in msgs)
        assert any(m.content == "New" for m in msgs)

    def test_truncation_preserves_order(self):
        ctx = ContextManager(max_tokens=1000, reserve_tokens=100)
        ctx.add_message("system", "SYS", token_count=100, pinned=True)
        ctx.add_message("user", "U1", token_count=100)
        ctx.add_message("assistant", "A1", token_count=100)
        ctx.add_message("user", "U2", token_count=100)
        ctx.add_message("assistant", "A2", token_count=600)
        # Budget = 900. Total = 1000. Need to drop oldest non-pinned.
        msgs = ctx.get_truncated_history()
        # System should be first
        assert msgs[0].content == "SYS"
        # Order should be preserved
        roles = [m.role for m in msgs]
        assert roles[0] == "system"

    def test_custom_reserve_in_truncation(self):
        ctx = ContextManager(max_tokens=500, reserve_tokens=100)
        ctx.add_message("user", "A", token_count=200)
        ctx.add_message("user", "B", token_count=200)
        # Default reserve=100, budget=400: both fit
        msgs = ctx.get_truncated_history()
        assert len(msgs) == 2
        # Custom reserve=300, budget=200: only one fits
        msgs = ctx.get_truncated_history(reserve_tokens=300)
        assert len(msgs) == 1


# =============================================================================
# ContextManager - Utilization Report Tests
# =============================================================================


class TestUtilizationReport:
    """Test utilization report."""

    def test_basic_report(self):
        ctx = ContextManager(max_tokens=10000)
        ctx.add_message("user", "Hello", token_count=100)
        report = ctx.get_utilization_report()
        assert report.model == ctx.model
        assert report.max_tokens == 10000
        assert report.used_tokens == 100
        assert report.remaining_tokens == 9900
        assert report.utilization == 0.01
        assert report.message_count == 1

    def test_pinned_tokens_in_report(self):
        ctx = ContextManager(max_tokens=10000)
        ctx.add_message("system", "SYS", token_count=200, pinned=True)
        ctx.add_message("user", "USER", token_count=100)
        report = ctx.get_utilization_report()
        assert report.pinned_tokens == 200
        assert report.truncatable_tokens == 100

    def test_report_to_dict(self):
        ctx = ContextManager(max_tokens=10000)
        ctx.add_message("user", "Test", token_count=100)
        d = ctx.get_utilization_report().to_dict()
        assert "model" in d
        assert "used_tokens" in d
        assert "utilization" in d


# =============================================================================
# ContextManager - Clear and State Tests
# =============================================================================


class TestClearAndState:
    """Test clear and state export."""

    def test_clear(self):
        ctx = ContextManager()
        ctx.add_message("user", "A")
        ctx.add_message("assistant", "B")
        ctx.clear()
        assert ctx.message_count == 0
        assert ctx.used_tokens == 0

    def test_to_dict(self):
        ctx = ContextManager(max_tokens=10000)
        ctx.add_message("user", "Hello", token_count=100)
        d = ctx.to_dict()
        assert d["max_tokens"] == 10000
        assert d["used_tokens"] == 100
        assert d["message_count"] == 1
        assert "utilization" in d

    def test_to_dict_empty(self):
        ctx = ContextManager()
        d = ctx.to_dict()
        assert d["used_tokens"] == 0
        assert d["message_count"] == 0


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_drivers_package(self):
        from core.drivers import (
            ContextManager,
            ContextMessage,
            estimate_tokens,
            get_context_window,
        )

        assert all([ContextManager, ContextMessage, estimate_tokens, get_context_window])

    def test_from_module(self):
        from core.drivers.context_manager import (
            MODEL_CONTEXT_WINDOWS,
            ContextManager,
            ContextMessage,
            estimate_tokens,
            get_context_window,
        )

        assert all([ContextManager, ContextMessage, ContextUtilization, estimate_tokens, get_context_window])
        assert len(MODEL_CONTEXT_WINDOWS) >= 8
