"""
Tests for TrajectoryPruner - V12.4 COGNITIVE BOOST

Tests the AgentDiet trajectory pruning pipeline:
- TrajectoryMessage creation and token estimation
- PruneResult / PrunerStats dataclass methods
- Empty/tiny message pruning
- Protected roles (system, user)
- Staleness detection (superseded messages)
- Redundancy detection (trigram Jaccard similarity)
- Irrelevance detection (task context)
- Token budget enforcement
- Aggressive pruning (trajectory > MAX_TRAJECTORY_LENGTH)
- Message priority scoring
- Singleton get/reset pattern
- Thread safety of stats updates
- Statistics tracking
- Edge cases and integration tests
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.synapse.trajectory_pruner import (
    MAX_TRAJECTORY_LENGTH,
    MIN_CONTENT_LENGTH,
    PROTECTED_ROLES,
    RECENCY_WEIGHT,
    REDUNDANCY_THRESHOLD,
    STALENESS_WINDOW,
    PruneDecision,
    PruneReason,
    PruneResult,
    PrunerStats,
    TrajectoryMessage,
    TrajectoryPruner,
    get_trajectory_pruner,
    reset_trajectory_pruner,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the global singleton before and after every test."""
    reset_trajectory_pruner()
    yield
    reset_trajectory_pruner()


@pytest.fixture
def pruner() -> TrajectoryPruner:
    """Return a fresh TrajectoryPruner instance (not the singleton)."""
    return TrajectoryPruner()


@pytest.fixture
def now() -> float:
    return time.time()


def _msg(
    content: str,
    role: str = "assistant",
    agent_id: str = "a1",
    ts: float = 0.0,
    token_estimate: int = 0,
    metadata: dict | None = None,
) -> TrajectoryMessage:
    """Helper to build a TrajectoryMessage with sensible defaults."""
    return TrajectoryMessage(
        content=content,
        role=role,
        agent_id=agent_id,
        timestamp=ts if ts else time.time(),
        token_estimate=token_estimate,
        metadata=metadata or {},
    )


# ===================================================================
# 1. TrajectoryMessage creation and token estimation
# ===================================================================


class TestTrajectoryMessage:
    """Tests for TrajectoryMessage dataclass."""

    def test_basic_creation(self):
        msg = TrajectoryMessage(content="hello world")
        assert msg.content == "hello world"
        assert msg.role == "assistant"
        assert msg.agent_id == ""
        assert msg.timestamp > 0
        assert msg.token_estimate >= 1

    def test_token_estimation_from_content(self):
        """Token estimate ~= len(content) // 4, min 1."""
        msg = TrajectoryMessage(content="a" * 100)
        assert msg.token_estimate == 25  # 100 // 4

    def test_token_estimation_minimum_one(self):
        msg = TrajectoryMessage(content="hi")
        assert msg.token_estimate == 1  # max(1, 2 // 4)

    def test_token_estimation_empty_content(self):
        msg = TrajectoryMessage(content="")
        assert msg.token_estimate == 1  # max(1, 0 // 4)

    def test_explicit_token_estimate_not_overridden(self):
        msg = TrajectoryMessage(content="hello", token_estimate=999)
        assert msg.token_estimate == 999

    def test_timestamp_auto_assigned(self):
        before = time.time()
        msg = TrajectoryMessage(content="test")
        after = time.time()
        assert before <= msg.timestamp <= after

    def test_explicit_timestamp_preserved(self):
        msg = TrajectoryMessage(content="test", timestamp=42.0)
        assert msg.timestamp == 42.0

    def test_metadata_default_empty(self):
        msg = TrajectoryMessage(content="test")
        assert msg.metadata == {}

    def test_metadata_isolation(self):
        """Each message gets its own metadata dict."""
        m1 = TrajectoryMessage(content="a")
        m2 = TrajectoryMessage(content="b")
        m1.metadata["key"] = "val"
        assert "key" not in m2.metadata

    def test_all_roles(self):
        for role in ("user", "assistant", "system", "tool"):
            msg = TrajectoryMessage(content="x", role=role)
            assert msg.role == role


# ===================================================================
# 2. PruneResult and PrunerStats dataclass methods
# ===================================================================


class TestPruneResult:
    """Tests for PruneResult dataclass."""

    def test_to_dict_fields(self):
        result = PruneResult(
            original_count=10,
            pruned_count=3,
            kept_count=7,
            original_tokens=1000,
            pruned_tokens=300,
            token_reduction_pct=30.0,
        )
        d = result.to_dict()
        assert d["original_count"] == 10
        assert d["pruned_count"] == 3
        assert d["kept_count"] == 7
        assert d["original_tokens"] == 1000
        assert d["pruned_tokens"] == 300
        assert d["token_reduction_pct"] == 30.0

    def test_to_dict_rounds_reduction(self):
        result = PruneResult(
            original_count=0,
            pruned_count=0,
            kept_count=0,
            original_tokens=0,
            pruned_tokens=0,
            token_reduction_pct=33.33333,
        )
        assert result.to_dict()["token_reduction_pct"] == 33.33

    def test_to_dict_excludes_messages_and_decisions(self):
        result = PruneResult(
            original_count=0,
            pruned_count=0,
            kept_count=0,
            original_tokens=0,
            pruned_tokens=0,
            token_reduction_pct=0.0,
            decisions=[PruneDecision(index=0, keep=True)],
            kept_messages=[TrajectoryMessage(content="kept")],
        )
        d = result.to_dict()
        assert "decisions" not in d
        assert "kept_messages" not in d

    def test_default_lists_empty(self):
        result = PruneResult(
            original_count=0,
            pruned_count=0,
            kept_count=0,
            original_tokens=0,
            pruned_tokens=0,
            token_reduction_pct=0.0,
        )
        assert result.decisions == []
        assert result.kept_messages == []


class TestPrunerStats:
    """Tests for PrunerStats dataclass."""

    def test_default_values(self):
        stats = PrunerStats()
        assert stats.total_calls == 0
        assert stats.total_messages_seen == 0
        assert stats.total_messages_pruned == 0
        assert stats.total_tokens_saved == 0
        assert stats.avg_reduction_pct == 0.0

    def test_to_dict(self):
        stats = PrunerStats(
            total_calls=5,
            total_messages_seen=100,
            total_messages_pruned=40,
            total_tokens_saved=3200,
            avg_reduction_pct=32.456,
        )
        d = stats.to_dict()
        assert d["total_calls"] == 5
        assert d["total_messages_seen"] == 100
        assert d["total_messages_pruned"] == 40
        assert d["total_tokens_saved"] == 3200
        assert d["avg_reduction_pct"] == 32.46

    def test_to_dict_rounds(self):
        stats = PrunerStats(avg_reduction_pct=0.12345)
        assert stats.to_dict()["avg_reduction_pct"] == 0.12


# ===================================================================
# 3. PruneDecision dataclass
# ===================================================================


class TestPruneDecision:
    """Tests for PruneDecision dataclass."""

    def test_keep_decision(self):
        d = PruneDecision(index=0, keep=True)
        assert d.index == 0
        assert d.keep is True
        assert d.reason is None
        assert d.confidence == 1.0

    def test_prune_decision(self):
        d = PruneDecision(index=3, keep=False, reason=PruneReason.STALE, confidence=0.8)
        assert d.index == 3
        assert d.keep is False
        assert d.reason == PruneReason.STALE
        assert d.confidence == 0.8


# ===================================================================
# 4. PruneReason enum
# ===================================================================


class TestPruneReason:
    """Tests for PruneReason enum."""

    def test_all_values(self):
        assert PruneReason.STALE == "stale"
        assert PruneReason.REDUNDANT == "redundant"
        assert PruneReason.IRRELEVANT == "irrelevant"
        assert PruneReason.EXPIRED == "expired"
        assert PruneReason.EMPTY == "empty"

    def test_is_string_enum(self):
        assert isinstance(PruneReason.STALE, str)
        assert PruneReason.STALE == "stale"


# ===================================================================
# 5. Basic pruning - empty input, single message
# ===================================================================


class TestBasicPruning:
    """Tests for basic prune() behavior."""

    def test_empty_input(self, pruner):
        result = pruner.prune([])
        assert result.original_count == 0
        assert result.pruned_count == 0
        assert result.kept_count == 0
        assert result.original_tokens == 0
        assert result.pruned_tokens == 0
        assert result.token_reduction_pct == 0.0
        assert result.kept_messages == []

    def test_single_message_kept(self, pruner):
        msg = _msg("This is a perfectly normal message with enough content.")
        result = pruner.prune([msg])
        assert result.original_count == 1
        assert result.kept_count == 1
        assert result.pruned_count == 0
        assert len(result.kept_messages) == 1
        assert result.kept_messages[0].content == msg.content

    def test_single_message_returns_correct_tokens(self, pruner):
        msg = _msg("a" * 200)  # 200 chars => 50 token estimate
        result = pruner.prune([msg])
        assert result.original_tokens == 50
        assert result.pruned_tokens == 0

    def test_two_distinct_messages_both_kept(self, pruner):
        m1 = _msg("The authentication module needs a refactor for security.")
        m2 = _msg("Database migration scripts should run in parallel mode.")
        result = pruner.prune([m1, m2])
        assert result.kept_count == 2
        assert result.pruned_count == 0


# ===================================================================
# 6. Empty/tiny message pruning (below MIN_CONTENT_LENGTH)
# ===================================================================


class TestEmptyMessagePruning:
    """Tests for Phase 1: empty/tiny message removal."""

    def test_empty_content_pruned(self, pruner):
        msg = _msg("", role="assistant")
        result = pruner.prune([msg])
        assert result.pruned_count == 1
        assert result.kept_count == 0
        assert result.decisions[0].reason == PruneReason.EMPTY

    def test_whitespace_only_pruned(self, pruner):
        msg = _msg("   \n\t  ", role="assistant")
        result = pruner.prune([msg])
        assert result.pruned_count == 1

    def test_tiny_content_pruned(self, pruner):
        msg = _msg("ok", role="assistant")
        assert len("ok") < MIN_CONTENT_LENGTH
        result = pruner.prune([msg])
        assert result.pruned_count == 1
        assert result.decisions[0].reason == PruneReason.EMPTY

    def test_at_threshold_kept(self, pruner):
        content = "x" * MIN_CONTENT_LENGTH
        msg = _msg(content, role="assistant")
        result = pruner.prune([msg])
        assert result.kept_count == 1

    def test_just_below_threshold_pruned(self, pruner):
        content = "x" * (MIN_CONTENT_LENGTH - 1)
        msg = _msg(content, role="assistant")
        result = pruner.prune([msg])
        assert result.pruned_count == 1

    def test_empty_confidence(self, pruner):
        msg = _msg("", role="assistant")
        result = pruner.prune([msg])
        assert result.decisions[0].confidence == 0.95

    def test_system_empty_not_pruned(self, pruner):
        """System messages are protected even if empty."""
        msg = _msg("", role="system")
        result = pruner.prune([msg])
        assert result.kept_count == 1

    def test_user_empty_not_pruned(self, pruner):
        """User messages are protected even if empty."""
        msg = _msg("ok", role="user")
        result = pruner.prune([msg])
        assert result.kept_count == 1

    def test_tool_empty_pruned(self, pruner):
        msg = _msg("ok", role="tool")
        result = pruner.prune([msg])
        assert result.pruned_count == 1


# ===================================================================
# 7. Protected roles
# ===================================================================


class TestProtectedRoles:
    """Tests that system and user messages are never pruned."""

    def test_protected_roles_constant(self):
        assert "system" in PROTECTED_ROLES
        assert "user" in PROTECTED_ROLES
        assert "assistant" not in PROTECTED_ROLES
        assert "tool" not in PROTECTED_ROLES

    def test_system_message_protected_from_empty_prune(self, pruner):
        msg = _msg("hi", role="system")
        result = pruner.prune([msg])
        assert result.kept_count == 1

    def test_user_message_protected_from_empty_prune(self, pruner):
        msg = _msg("hi", role="user")
        result = pruner.prune([msg])
        assert result.kept_count == 1

    def test_system_message_protected_from_staleness(self, pruner, now):
        old_ts = now - STALENESS_WINDOW - 100
        sys_msg = _msg(
            "Initial system setup and configuration details.",
            role="system",
            agent_id="a1",
            ts=old_ts,
        )
        correction = _msg(
            "Updated system setup and configuration details.",
            role="assistant",
            agent_id="a1",
            ts=now,
        )
        result = pruner.prune([sys_msg, correction])
        kept_contents = [m.content for m in result.kept_messages]
        assert sys_msg.content in kept_contents

    def test_user_message_protected_from_redundancy(self, pruner):
        """Even identical user messages are kept."""
        m1 = _msg("Exactly the same content repeated verbatim here now.", role="user", ts=1.0)
        m2 = _msg("Exactly the same content repeated verbatim here now.", role="user", ts=2.0)
        result = pruner.prune([m1, m2])
        assert result.kept_count == 2

    def test_system_protected_from_budget_enforcement(self, pruner):
        sys_msg = _msg("System prompt with critical instructions.", role="system", token_estimate=500)
        asst_msg = _msg("Some assistant response that is long enough.", role="assistant", token_estimate=500)
        result = pruner.prune([sys_msg, asst_msg], token_budget=600)
        kept_roles = [m.role for m in result.kept_messages]
        assert "system" in kept_roles


# ===================================================================
# 8. Staleness detection - superseded messages
# ===================================================================


class TestStalenessDetection:
    """Tests for Phase 2: staleness marking."""

    def test_old_message_superseded_by_correction(self, pruner, now):
        old_ts = now - STALENESS_WINDOW - 100
        old = _msg(
            "the auth module uses token validation for user sessions in production",
            role="assistant",
            agent_id="a1",
            ts=old_ts,
        )
        newer = _msg(
            "actually the auth module uses token validation for user sessions updated in production",
            role="assistant",
            agent_id="a1",
            ts=now,
        )
        result = pruner.prune([old, newer])
        assert result.pruned_count >= 1
        # The old message should be pruned as stale
        stale_decisions = [d for d in result.decisions if d.reason == PruneReason.STALE]
        assert len(stale_decisions) >= 1

    def test_recent_message_not_stale(self, pruner, now):
        """Messages within the staleness window are not marked stale."""
        recent = _msg(
            "The auth module uses basic token validation for user sessions.",
            role="assistant",
            agent_id="a1",
            ts=now - 10,
        )
        newer = _msg(
            "Actually the auth module was updated and corrected for sessions.",
            role="assistant",
            agent_id="a1",
            ts=now,
        )
        result = pruner.prune([recent, newer])
        stale_decisions = [d for d in result.decisions if d.reason == PruneReason.STALE]
        assert len(stale_decisions) == 0

    def test_different_agent_no_supersede(self, pruner, now):
        """Staleness only applies within same agent_id."""
        old_ts = now - STALENESS_WINDOW - 100
        old = _msg(
            "The auth module uses basic token validation for user sessions.",
            role="assistant",
            agent_id="a1",
            ts=old_ts,
        )
        newer = _msg(
            "Actually the auth module was updated and corrected for sessions.",
            role="assistant",
            agent_id="a2",
            ts=now,
        )
        result = pruner.prune([old, newer])
        stale_decisions = [d for d in result.decisions if d.reason == PruneReason.STALE]
        assert len(stale_decisions) == 0

    def test_no_supersede_pattern_no_staleness(self, pruner, now):
        """Without supersede keywords, no staleness."""
        old_ts = now - STALENESS_WINDOW - 100
        old = _msg(
            "The auth module handles validation logic for token generation.",
            role="assistant",
            agent_id="a1",
            ts=old_ts,
        )
        newer = _msg(
            "The database layer needs connection pooling for performance.",
            role="assistant",
            agent_id="a1",
            ts=now,
        )
        result = pruner.prune([old, newer])
        stale_decisions = [d for d in result.decisions if d.reason == PruneReason.STALE]
        assert len(stale_decisions) == 0

    def test_supersede_requires_word_overlap(self, pruner, now):
        """Supersede pattern alone is not enough; need word overlap > 0.3."""
        old_ts = now - STALENESS_WINDOW - 100
        old = _msg(
            "The graphics rendering engine uses OpenGL shaders extensively.",
            role="assistant",
            agent_id="a1",
            ts=old_ts,
        )
        newer = _msg(
            "Actually the database connection pooling was corrected yesterday.",
            role="assistant",
            agent_id="a1",
            ts=now,
        )
        result = pruner.prune([old, newer])
        stale_decisions = [d for d in result.decisions if d.reason == PruneReason.STALE]
        assert len(stale_decisions) == 0

    def test_custom_staleness_window(self, now):
        """Custom staleness window is respected."""
        pruner = TrajectoryPruner(staleness_window=10.0)
        old_ts = now - 20  # 20 seconds ago, window is 10
        old = _msg(
            "The module uses basic token validation for user sessions.",
            role="assistant",
            agent_id="a1",
            ts=old_ts,
        )
        newer = _msg(
            "Actually the module was updated with corrected token validation.",
            role="assistant",
            agent_id="a1",
            ts=now,
        )
        result = pruner.prune([old, newer])
        stale_decisions = [d for d in result.decisions if d.reason == PruneReason.STALE]
        assert len(stale_decisions) >= 1


# ===================================================================
# 9. Redundancy detection via trigram Jaccard similarity
# ===================================================================


class TestRedundancyDetection:
    """Tests for Phase 3: near-duplicate detection."""

    def test_identical_messages_marked_redundant(self, pruner):
        content = "The deployment pipeline should include automated testing and rollback capabilities."
        m1 = _msg(content, role="assistant", ts=1.0)
        m2 = _msg(content, role="assistant", ts=2.0)
        result = pruner.prune([m1, m2])
        redundant = [d for d in result.decisions if d.reason == PruneReason.REDUNDANT]
        assert len(redundant) >= 1

    def test_identical_keeps_newer(self, pruner):
        content = "The deployment pipeline should include automated testing and rollback capabilities."
        m1 = _msg(content, role="assistant", ts=1.0)
        m2 = _msg(content, role="assistant", ts=2.0)
        result = pruner.prune([m1, m2])
        assert result.kept_count >= 1
        # The newer message (m2) should be kept
        kept_ts = [m.timestamp for m in result.kept_messages]
        assert 2.0 in kept_ts

    def test_very_different_messages_not_redundant(self, pruner):
        m1 = _msg(
            "The authentication system processes JWT tokens via middleware hooks.",
            role="assistant",
            ts=1.0,
        )
        m2 = _msg(
            "Database migrations require careful planning and staged rollout procedures.",
            role="assistant",
            ts=2.0,
        )
        result = pruner.prune([m1, m2])
        redundant = [d for d in result.decisions if d.reason == PruneReason.REDUNDANT]
        assert len(redundant) == 0

    def test_only_same_role_compared(self, pruner):
        """Redundancy only applies between messages of the same role."""
        content = "The deployment pipeline should include automated testing and rollback capabilities."
        m1 = _msg(content, role="assistant", ts=1.0)
        m2 = _msg(content, role="tool", ts=2.0)
        result = pruner.prune([m1, m2])
        redundant = [d for d in result.decisions if d.reason == PruneReason.REDUNDANT]
        assert len(redundant) == 0

    def test_near_duplicate_above_threshold(self, pruner):
        """Slightly different messages above threshold are redundant."""
        base = "the deployment pipeline should include automated testing and rollback"
        m1 = _msg(base + " capabilities for production systems and environments", role="assistant", ts=1.0)
        m2 = _msg(base + " capabilities for production systems and platforms", role="assistant", ts=2.0)
        result = pruner.prune([m1, m2])
        redundant = [d for d in result.decisions if d.reason == PruneReason.REDUNDANT]
        assert len(redundant) >= 1

    def test_custom_redundancy_threshold(self, now):
        """Very low threshold triggers more redundancy detection."""
        pruner = TrajectoryPruner(redundancy_threshold=0.01)
        m1 = _msg("Alpha bravo charlie delta echo foxtrot.", role="assistant", ts=1.0)
        m2 = _msg("Alpha bravo charlie golf hotel india.", role="assistant", ts=2.0)
        result = pruner.prune([m1, m2])
        redundant = [d for d in result.decisions if d.reason == PruneReason.REDUNDANT]
        assert len(redundant) >= 1

    def test_high_threshold_no_redundancy(self):
        """Very high threshold means nothing is redundant except exact duplicates with many trigrams."""
        pruner = TrajectoryPruner(redundancy_threshold=0.99)
        m1 = _msg(
            "The deployment pipeline includes automated testing and rollback capabilities.",
            role="assistant",
            ts=1.0,
        )
        m2 = _msg(
            "The deployment pipeline includes automated testing and rollback procedures.",
            role="assistant",
            ts=2.0,
        )
        result = pruner.prune([m1, m2])
        redundant = [d for d in result.decisions if d.reason == PruneReason.REDUNDANT]
        assert len(redundant) == 0

    def test_protected_role_not_pruned_for_redundancy(self, pruner):
        """Even if redundant, protected role messages are kept."""
        content = "The deployment pipeline should include automated testing and rollback capabilities."
        m1 = _msg(content, role="user", ts=1.0)
        m2 = _msg(content, role="user", ts=2.0)
        result = pruner.prune([m1, m2])
        assert result.kept_count == 2


# ===================================================================
# 10. Irrelevance detection with task context
# ===================================================================


class TestIrrelevanceDetection:
    """Tests for Phase 4: irrelevance marking."""

    def test_no_task_context_no_irrelevance(self, pruner):
        """Without task_context, irrelevance phase is skipped."""
        msg = _msg("A" * 1000, role="tool", token_estimate=300)
        result = pruner.prune([msg])
        irrelevant = [d for d in result.decisions if d.reason == PruneReason.IRRELEVANT]
        assert len(irrelevant) == 0

    def test_relevant_message_kept(self, pruner):
        msg = _msg(
            "The authentication module validates JWT tokens using the secret key.",
            role="assistant",
        )
        result = pruner.prune([msg], task_context="Fix JWT authentication bug")
        assert result.kept_count == 1

    def test_irrelevant_large_tool_output_pruned(self, pruner):
        """Large tool output with zero task overlap is pruned."""
        # Build content that matches TOOL_OUTPUT_PATTERNS (line-numbered output)
        lines = "\n".join(f"  {i}\u2192  some_var = unrelated_value_{i}" for i in range(100))
        msg = _msg(lines, role="tool", token_estimate=500)
        result = pruner.prune([msg], task_context="fix authentication bug")
        irrelevant = [d for d in result.decisions if d.reason == PruneReason.IRRELEVANT]
        assert len(irrelevant) >= 1

    def test_system_message_protected_from_irrelevance(self, pruner):
        lines = "\n".join(f"  {i}\u2192  random_data = {i}" for i in range(100))
        msg = _msg(lines, role="system", token_estimate=500)
        result = pruner.prune([msg], task_context="fix auth bug")
        assert result.kept_count == 1

    def test_small_tool_output_not_pruned(self, pruner):
        """Small tool outputs (< 200 tokens) are not pruned for irrelevance."""
        lines = "\n".join(f"  {i}\u2192  val = {i}" for i in range(5))
        msg = _msg(lines, role="tool", token_estimate=50)
        result = pruner.prune([msg], task_context="fix auth bug")
        irrelevant = [d for d in result.decisions if d.reason == PruneReason.IRRELEVANT]
        assert len(irrelevant) == 0


# ===================================================================
# 11. Token budget enforcement
# ===================================================================


class TestTokenBudgetEnforcement:
    """Tests for Phase 5: token budget pruning."""

    def test_no_budget_no_pruning(self, pruner):
        msgs = [
            _msg(f"unique message number {i} about topic {i * 7} in detail", role="assistant", token_estimate=100)
            for i in range(5)
        ]
        result = pruner.prune(msgs, token_budget=0)
        assert result.kept_count == 5

    def test_budget_within_limit_no_pruning(self, pruner):
        msgs = [
            _msg(f"distinct content for item {i} discussing area {i * 11}", role="assistant", token_estimate=100)
            for i in range(3)
        ]
        result = pruner.prune(msgs, token_budget=1000)  # 300 < 1000
        assert result.kept_count == 3

    def test_budget_exceeded_prunes_lowest_priority(self, pruner):
        msgs = [_msg("message content number " * 5, role="assistant", token_estimate=100) for _ in range(5)]
        # Total = 500 tokens, budget = 200 => need to prune at least 300
        result = pruner.prune(msgs, token_budget=200)
        kept_tokens = sum(m.token_estimate for m in result.kept_messages)
        assert kept_tokens <= 200

    def test_budget_protects_system_messages(self, pruner):
        sys_msg = _msg("System instructions.", role="system", token_estimate=200)
        assistant_msgs = [
            _msg(f"Assistant response number {i} with content.", role="assistant", token_estimate=200) for i in range(3)
        ]
        all_msgs = [sys_msg] + assistant_msgs
        # budget = 300 => must keep system (200) + at most 1 assistant (200)
        result = pruner.prune(all_msgs, token_budget=300)
        kept_roles = [m.role for m in result.kept_messages]
        assert "system" in kept_roles

    def test_budget_prunes_by_priority(self, pruner):
        """Lower priority messages (older, tool role) are pruned first."""
        msgs = [
            _msg("Tool output from first step.", role="tool", token_estimate=100, ts=1.0),
            _msg("Important assistant analysis for the task.", role="assistant", token_estimate=100, ts=2.0),
            _msg("Final assistant summary and recommendation.", role="assistant", token_estimate=100, ts=3.0),
        ]
        result = pruner.prune(msgs, token_budget=200)
        kept_contents = [m.content for m in result.kept_messages]
        # Tool message should be pruned first (lowest priority)
        assert "Tool output from first step." not in kept_contents


# ===================================================================
# 12. Aggressive pruning (trajectory > MAX_TRAJECTORY_LENGTH)
# ===================================================================


class TestAggressivePruning:
    """Tests for Phase 6: aggressive pruning when too many messages."""

    def test_below_max_no_aggressive(self, pruner):
        msgs = [_msg(f"Message {i} with reasonable content.", role="assistant") for i in range(10)]
        result = pruner.prune(msgs)
        assert result.kept_count == 10

    def test_above_max_triggers_aggressive(self):
        small_max = 5
        pruner = TrajectoryPruner(max_trajectory=small_max)
        msgs = [_msg(f"Message number {i} content here.", role="assistant", ts=float(i)) for i in range(10)]
        result = pruner.prune(msgs)
        assert result.kept_count <= small_max

    def test_aggressive_uses_expired_reason(self):
        small_max = 3
        pruner = TrajectoryPruner(max_trajectory=small_max)
        msgs = [_msg(f"Msg number {i} with longer content here.", role="assistant", ts=float(i)) for i in range(6)]
        result = pruner.prune(msgs)
        expired = [d for d in result.decisions if d.reason == PruneReason.EXPIRED]
        assert len(expired) >= 1

    def test_aggressive_protects_roles(self):
        small_max = 3
        pruner = TrajectoryPruner(max_trajectory=small_max)
        msgs = [
            _msg("System prompt.", role="system", ts=0.0),
            _msg("User question.", role="user", ts=1.0),
        ] + [_msg(f"Assistant response {i}.", role="assistant", ts=float(i + 2)) for i in range(10)]
        result = pruner.prune(msgs)
        kept_roles = [m.role for m in result.kept_messages]
        assert "system" in kept_roles
        assert "user" in kept_roles

    def test_aggressive_expired_confidence(self):
        small_max = 3
        pruner = TrajectoryPruner(max_trajectory=small_max)
        msgs = [_msg(f"Message content number {i}.", role="assistant", ts=float(i)) for i in range(8)]
        result = pruner.prune(msgs)
        expired = [d for d in result.decisions if d.reason == PruneReason.EXPIRED]
        for d in expired:
            assert d.confidence == 0.5


# ===================================================================
# 13. Message priority scoring
# ===================================================================


class TestMessagePriority:
    """Tests for _message_priority scoring."""

    def test_newer_message_higher_priority(self, pruner):
        msgs = [_msg("content " * 10, role="assistant") for _ in range(10)]
        p_first = pruner._message_priority(msgs[0], 10, 0)
        p_last = pruner._message_priority(msgs[9], 10, 9)
        assert p_last > p_first

    def test_system_role_highest_weight(self, pruner):
        sys_msg = _msg("system content " * 10, role="system")
        tool_msg = _msg("tool content " * 10, role="tool")
        p_sys = pruner._message_priority(sys_msg, 10, 5)
        p_tool = pruner._message_priority(tool_msg, 10, 5)
        assert p_sys > p_tool

    def test_user_role_higher_than_assistant(self, pruner):
        user_msg = _msg("user content " * 10, role="user")
        asst_msg = _msg("assistant content " * 10, role="assistant")
        p_user = pruner._message_priority(user_msg, 10, 5)
        p_asst = pruner._message_priority(asst_msg, 10, 5)
        assert p_user > p_asst

    def test_short_message_bonus(self, pruner):
        short = _msg("short msg", role="assistant", token_estimate=10)
        long = _msg("long " * 200, role="assistant", token_estimate=600)
        p_short = pruner._message_priority(short, 10, 5)
        p_long = pruner._message_priority(long, 10, 5)
        assert p_short > p_long

    def test_single_message_recency(self, pruner):
        """Single message (total=1) should not cause division by zero."""
        msg = _msg("only message", role="assistant")
        priority = pruner._message_priority(msg, 1, 0)
        assert isinstance(priority, float)
        assert priority >= 0


# ===================================================================
# 14. Internal helpers: trigrams, jaccard, word_overlap, normalize
# ===================================================================


class TestHelperMethods:
    """Tests for static helper methods."""

    def test_trigrams_basic(self):
        result = TrajectoryPruner._trigrams("the quick brown fox jumps")
        assert ("the", "quick", "brown") in result
        assert ("quick", "brown", "fox") in result
        assert ("brown", "fox", "jumps") in result

    def test_trigrams_short_text(self):
        result = TrajectoryPruner._trigrams("hello world")
        assert result == frozenset(["hello", "world"])

    def test_trigrams_single_word(self):
        result = TrajectoryPruner._trigrams("hello")
        assert result == frozenset(["hello"])

    def test_trigrams_empty(self):
        result = TrajectoryPruner._trigrams("")
        assert result == frozenset()

    def test_trigrams_case_insensitive(self):
        result = TrajectoryPruner._trigrams("The Quick Brown")
        assert ("the", "quick", "brown") in result

    def test_trigrams_capped_at_100_words(self):
        text = " ".join(f"word{i}" for i in range(200))
        result = TrajectoryPruner._trigrams(text)
        # With 100 words capped, max trigrams = 98
        assert len(result) <= 98

    def test_jaccard_identical(self):
        s = frozenset(["a", "b", "c"])
        assert TrajectoryPruner._jaccard(s, s) == 1.0

    def test_jaccard_disjoint(self):
        a = frozenset(["a", "b"])
        b = frozenset(["c", "d"])
        assert TrajectoryPruner._jaccard(a, b) == 0.0

    def test_jaccard_partial_overlap(self):
        a = frozenset(["a", "b", "c"])
        b = frozenset(["b", "c", "d"])
        # intersection = {b, c} = 2, union = {a, b, c, d} = 4
        assert TrajectoryPruner._jaccard(a, b) == 0.5

    def test_jaccard_both_empty(self):
        assert TrajectoryPruner._jaccard(frozenset(), frozenset()) == 1.0

    def test_jaccard_one_empty(self):
        assert TrajectoryPruner._jaccard(frozenset(["a"]), frozenset()) == 0.0
        assert TrajectoryPruner._jaccard(frozenset(), frozenset(["a"])) == 0.0

    def test_word_overlap_identical(self):
        assert TrajectoryPruner._word_overlap("hello world", "hello world") == 1.0

    def test_word_overlap_partial(self):
        overlap = TrajectoryPruner._word_overlap("hello world foo", "hello world bar")
        # intersection = {hello, world} = 2, min(3,3) = 3
        assert abs(overlap - 2 / 3) < 0.01

    def test_word_overlap_no_overlap(self):
        assert TrajectoryPruner._word_overlap("alpha beta", "gamma delta") == 0.0

    def test_word_overlap_empty(self):
        assert TrajectoryPruner._word_overlap("", "hello") == 0.0
        assert TrajectoryPruner._word_overlap("hello", "") == 0.0

    def test_normalize_removes_punctuation(self):
        assert TrajectoryPruner._normalize("Hello, World!") == "hello world"

    def test_normalize_strips_whitespace(self):
        assert TrajectoryPruner._normalize("  hello  ") == "hello"

    def test_normalize_lowercase(self):
        assert TrajectoryPruner._normalize("HELLO") == "hello"

    def test_normalize_keeps_numbers(self):
        assert TrajectoryPruner._normalize("v12.4") == "v124"


# ===================================================================
# 15. Singleton get/reset pattern
# ===================================================================


class TestSingletonPattern:
    """Tests for get_trajectory_pruner and reset_trajectory_pruner."""

    def test_get_returns_instance(self):
        pruner = get_trajectory_pruner()
        assert isinstance(pruner, TrajectoryPruner)

    def test_get_returns_same_instance(self):
        p1 = get_trajectory_pruner()
        p2 = get_trajectory_pruner()
        assert p1 is p2

    def test_reset_clears_instance(self):
        p1 = get_trajectory_pruner()
        reset_trajectory_pruner()
        p2 = get_trajectory_pruner()
        assert p1 is not p2

    def test_reset_then_get_fresh_stats(self):
        pruner = get_trajectory_pruner()
        pruner.prune([_msg("Some content for the pruner.")])
        assert pruner.get_stats().total_calls == 1
        reset_trajectory_pruner()
        fresh = get_trajectory_pruner()
        assert fresh.get_stats().total_calls == 0


# ===================================================================
# 16. Thread safety of stats updates
# ===================================================================


class TestThreadSafety:
    """Tests for thread-safe stats updates."""

    def test_concurrent_prune_calls(self, pruner):
        """Multiple threads pruning concurrently should not corrupt stats."""
        n_threads = 10
        n_calls_per_thread = 20
        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            for _ in range(n_calls_per_thread):
                msgs = [_msg("Thread-safe message content here.", role="assistant")]
                pruner.prune(msgs)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        stats = pruner.get_stats()
        assert stats.total_calls == n_threads * n_calls_per_thread

    def test_concurrent_stats_read(self, pruner):
        """Reading stats while pruning should not raise."""
        errors = []

        def reader():
            for _ in range(50):
                try:
                    pruner.get_stats()
                except Exception as exc:
                    errors.append(exc)

        def writer():
            for _ in range(50):
                pruner.prune([_msg("concurrent content here.")])

        t1 = threading.Thread(target=reader)
        t2 = threading.Thread(target=writer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len(errors) == 0

    def test_concurrent_reset_and_get(self):
        """Concurrent reset and get should not raise."""
        errors = []

        def resetter():
            for _ in range(50):
                try:
                    reset_trajectory_pruner()
                except Exception as exc:
                    errors.append(exc)

        def getter():
            for _ in range(50):
                try:
                    get_trajectory_pruner()
                except Exception as exc:
                    errors.append(exc)

        t1 = threading.Thread(target=resetter)
        t2 = threading.Thread(target=getter)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert len(errors) == 0


# ===================================================================
# 17. Statistics tracking
# ===================================================================


class TestStatisticsTracking:
    """Tests for stats accumulation across prune calls."""

    def test_single_call_stats(self, pruner):
        msgs = [_msg("Content for statistics tracking.")]
        pruner.prune(msgs)
        stats = pruner.get_stats()
        assert stats.total_calls == 1
        assert stats.total_messages_seen == 1
        assert stats.total_messages_pruned == 0

    def test_multiple_calls_accumulate(self, pruner):
        for _ in range(3):
            pruner.prune([_msg("Reasonable content for pruning.")])
        stats = pruner.get_stats()
        assert stats.total_calls == 3
        assert stats.total_messages_seen == 3

    def test_pruned_tokens_tracked(self, pruner):
        msgs = [
            _msg("", role="assistant", token_estimate=50),  # Will be pruned (empty)
            _msg("Kept message with actual content."),
        ]
        pruner.prune(msgs)
        stats = pruner.get_stats()
        assert stats.total_tokens_saved == 50
        assert stats.total_messages_pruned == 1

    def test_avg_reduction_pct(self, pruner):
        # First call: prune 1 of 2 messages
        msgs1 = [
            _msg("", role="tool", token_estimate=100),
            _msg("Valid content message here.", role="assistant", token_estimate=100),
        ]
        pruner.prune(msgs1)
        stats1 = pruner.get_stats()
        assert stats1.avg_reduction_pct == pytest.approx(50.0)

        # Second call: no pruning
        msgs2 = [_msg("Another valid message with content.", role="assistant", token_estimate=100)]
        pruner.prune(msgs2)
        stats2 = pruner.get_stats()
        # Average of 50.0 and 0.0 = 25.0
        assert stats2.avg_reduction_pct == pytest.approx(25.0)

    def test_reset_clears_stats(self, pruner):
        pruner.prune([_msg("Some content to generate stats.")])
        pruner.reset()
        stats = pruner.get_stats()
        assert stats.total_calls == 0
        assert stats.total_messages_seen == 0
        assert stats.total_tokens_saved == 0

    def test_get_stats_returns_copy(self, pruner):
        """Modifying returned stats should not affect internal state."""
        pruner.prune([_msg("Content for stats.")])
        stats = pruner.get_stats()
        stats.total_calls = 999
        assert pruner.get_stats().total_calls == 1

    def test_empty_prune_stats(self, pruner):
        pruner.prune([])
        stats = pruner.get_stats()
        # Empty input does early return before stats update
        assert stats.total_calls == 0


# ===================================================================
# 18. Edge cases
# ===================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_all_messages_protected(self, pruner):
        msgs = [
            _msg("System message.", role="system"),
            _msg("User message.", role="user"),
        ]
        result = pruner.prune(msgs)
        assert result.kept_count == 2
        assert result.pruned_count == 0

    def test_all_messages_empty_assistant(self, pruner):
        msgs = [_msg("", role="assistant") for _ in range(5)]
        result = pruner.prune(msgs)
        assert result.kept_count == 0
        assert result.pruned_count == 5

    def test_all_identical_assistant_messages(self, pruner):
        content = "The exact same content repeated across many messages for redundancy testing."
        msgs = [_msg(content, role="assistant", ts=float(i)) for i in range(5)]
        result = pruner.prune(msgs)
        # At least some should be pruned as redundant
        assert result.pruned_count >= 1
        # At least the newest should be kept
        assert result.kept_count >= 1

    def test_alternating_protected_and_prunable(self, pruner):
        msgs = []
        for i in range(6):
            if i % 2 == 0:
                msgs.append(_msg(f"User question {i}?", role="user"))
            else:
                msgs.append(_msg("ok", role="assistant"))  # Tiny => pruned
        result = pruner.prune(msgs)
        # All user messages kept, all "ok" assistant messages pruned
        assert result.kept_count == 3
        assert result.pruned_count == 3

    def test_very_long_message(self, pruner):
        content = "word " * 10000
        msg = _msg(content, role="assistant")
        result = pruner.prune([msg])
        assert result.kept_count == 1
        assert msg.token_estimate > 0

    def test_message_with_special_characters(self, pruner):
        msg = _msg("Hello! @#$%^&*() unicode: \u00e9\u00e8\u00ea \u2603 tabs\there", role="assistant")
        result = pruner.prune([msg])
        assert result.kept_count == 1

    def test_token_budget_zero_means_no_budget(self, pruner):
        msgs = [_msg("Content " * 20, role="assistant", token_estimate=1000)]
        result = pruner.prune(msgs, token_budget=0)
        assert result.kept_count == 1

    def test_token_budget_of_one(self, pruner):
        msgs = [
            _msg("Message A content.", role="assistant", token_estimate=100),
            _msg("Message B content.", role="assistant", token_estimate=100),
        ]
        result = pruner.prune(msgs, token_budget=1)
        # Should prune as many as possible to fit budget
        kept_tokens = sum(m.token_estimate for m in result.kept_messages)
        # Both are assistant so both prunable; may end up with 0 if both get pruned
        assert kept_tokens <= 100  # At most 1 kept

    def test_max_trajectory_one(self):
        pruner = TrajectoryPruner(max_trajectory=1)
        msgs = [_msg(f"Message content number {i}.", role="assistant", ts=float(i)) for i in range(5)]
        result = pruner.prune(msgs)
        assert result.kept_count <= 1

    def test_no_assistant_messages(self, pruner):
        """Only system and user messages, all protected."""
        msgs = [
            _msg("You are a helpful assistant.", role="system"),
            _msg("What is 2+2?", role="user"),
            _msg("Now explain it.", role="user"),
        ]
        result = pruner.prune(msgs)
        assert result.kept_count == 3
        assert result.pruned_count == 0

    def test_messages_with_zero_timestamp(self, pruner):
        """Messages with timestamp 0.0 get auto-assigned."""
        msg = TrajectoryMessage(content="Test message content here.", timestamp=0.0)
        assert msg.timestamp > 0  # __post_init__ assigns current time

    def test_result_decisions_match_message_count(self, pruner):
        msgs = [_msg(f"Message {i} content.", role="assistant") for i in range(5)]
        result = pruner.prune(msgs)
        assert len(result.decisions) == 5

    def test_min_content_length_custom(self):
        pruner = TrajectoryPruner(min_content_length=50)
        msg = _msg("Short but above default threshold.", role="assistant")
        assert len("Short but above default threshold.") < 50
        result = pruner.prune([msg])
        assert result.pruned_count == 1


# ===================================================================
# 19. Constants verification
# ===================================================================


class TestConstants:
    """Verify module-level constants have expected values."""

    def test_redundancy_threshold(self):
        assert REDUNDANCY_THRESHOLD == 0.65

    def test_staleness_window(self):
        assert STALENESS_WINDOW == 300.0

    def test_min_content_length(self):
        assert MIN_CONTENT_LENGTH == 15

    def test_max_trajectory_length(self):
        assert MAX_TRAJECTORY_LENGTH == 50

    def test_recency_weight(self):
        assert RECENCY_WEIGHT == 0.3

    def test_protected_roles_frozen(self):
        assert isinstance(PROTECTED_ROLES, frozenset)
        with pytest.raises(AttributeError):
            PROTECTED_ROLES.add("tool")  # type: ignore[attr-defined]


# ===================================================================
# 20. Integration: full pipeline with multiple prune reasons
# ===================================================================


class TestIntegration:
    """Integration tests exercising multiple pruning phases together."""

    def test_full_pipeline_mixed_reasons(self, now):
        """Messages pruned for different reasons in a single call."""
        pruner = TrajectoryPruner(staleness_window=60.0)
        old_ts = now - 120  # 2 minutes ago (> 60s window)

        msgs = [
            # System - protected
            _msg("You are a helpful coding assistant.", role="system", ts=old_ts - 10),
            # Empty assistant - pruned as EMPTY
            _msg("", role="assistant", agent_id="a1", ts=old_ts - 5),
            # Old message that will be superseded
            _msg(
                "The database connection uses a single pooled connection manager.",
                role="assistant",
                agent_id="a1",
                ts=old_ts,
            ),
            # User question - protected
            _msg("How does the database connect?", role="user", ts=old_ts + 30),
            # Newer correction (supersedes #2)
            _msg(
                "Actually the database connection was updated and corrected to use multiple pools.",
                role="assistant",
                agent_id="a1",
                ts=now,
            ),
            # Redundant duplicate of correction
            _msg(
                "Actually the database connection was updated and corrected to use multiple pools.",
                role="assistant",
                agent_id="a1",
                ts=now + 1,
            ),
        ]

        result = pruner.prune(msgs, task_context="database connection pooling")

        # Verify mixed decisions
        reasons = [d.reason for d in result.decisions if not d.keep]
        assert PruneReason.EMPTY in reasons
        # The stale and/or redundant reasons should appear
        assert len(reasons) >= 2  # At least empty + one other
        # System and user are always kept
        kept_roles = [m.role for m in result.kept_messages]
        assert "system" in kept_roles
        assert "user" in kept_roles

    def test_pipeline_with_budget_and_staleness(self, now):
        """Budget enforcement after staleness marking."""
        pruner = TrajectoryPruner(staleness_window=30.0)
        old_ts = now - 60

        msgs = [
            _msg("System prompt.", role="system", token_estimate=50, ts=old_ts - 10),
            _msg(
                "Old analysis of auth system with basic token validation.",
                role="assistant",
                agent_id="a1",
                token_estimate=200,
                ts=old_ts,
            ),
            _msg(
                "Updated analysis: auth system was corrected with JWT validation.",
                role="assistant",
                agent_id="a1",
                token_estimate=200,
                ts=now,
            ),
            _msg("User asks a follow up.", role="user", token_estimate=20, ts=now + 1),
        ]

        result = pruner.prune(msgs, token_budget=300)
        # System and user protected
        kept_roles = [m.role for m in result.kept_messages]
        assert "system" in kept_roles
        assert "user" in kept_roles
        kept_tokens = sum(m.token_estimate for m in result.kept_messages)
        assert kept_tokens <= 300

    def test_pipeline_aggressive_with_many_messages(self):
        """Aggressive pruning with max_trajectory=10 and 20 messages."""
        pruner = TrajectoryPruner(max_trajectory=10)
        msgs = [
            _msg("System instructions for the agent.", role="system", ts=0.0),
            _msg("User's initial question about the system.", role="user", ts=1.0),
        ] + [
            _msg(f"Assistant response step {i} with detailed analysis.", role="assistant", ts=float(i + 2))
            for i in range(18)
        ]

        result = pruner.prune(msgs)
        assert result.kept_count <= 10
        # System and user should survive aggressive pruning
        kept_roles = [m.role for m in result.kept_messages]
        assert "system" in kept_roles
        assert "user" in kept_roles

    def test_pipeline_preserves_order(self, pruner):
        """Kept messages retain their original order."""
        msgs = [
            _msg("First message with content.", role="assistant", ts=1.0),
            _msg("Second message with content.", role="assistant", ts=2.0),
            _msg("Third message with content.", role="assistant", ts=3.0),
        ]
        result = pruner.prune(msgs)
        timestamps = [m.timestamp for m in result.kept_messages]
        assert timestamps == sorted(timestamps)

    def test_pipeline_stats_after_multiple_calls(self, pruner):
        """Stats accumulate correctly after mixed prune calls."""
        # Call 1: some pruning
        msgs1 = [
            _msg("", role="assistant", token_estimate=50),
            _msg("Valid content here.", role="assistant", token_estimate=100),
        ]
        pruner.prune(msgs1)

        # Call 2: no pruning
        msgs2 = [_msg("Another valid message.", role="assistant", token_estimate=100)]
        pruner.prune(msgs2)

        stats = pruner.get_stats()
        assert stats.total_calls == 2
        assert stats.total_messages_seen == 3
        assert stats.total_messages_pruned == 1
        assert stats.total_tokens_saved == 50

    def test_pipeline_all_phases_in_sequence(self, now):
        """Verify that all phases execute in order without interfering."""
        pruner = TrajectoryPruner(
            staleness_window=30.0,
            max_trajectory=20,
            redundancy_threshold=0.65,
        )
        old_ts = now - 60

        # Build a trajectory that exercises every phase
        lines = "\n".join(f"  {i}\u2192  unrelated_data = {i}" for i in range(100))
        msgs = [
            # Phase 1: Empty
            _msg("ok", role="tool", ts=old_ts - 5),
            # Phase 2: Stale (will be superseded)
            _msg(
                "The auth module uses basic validation with token checking.",
                role="assistant",
                agent_id="a1",
                ts=old_ts,
            ),
            # Superseder for staleness
            _msg(
                "Actually the auth module was corrected to use JWT-based checking.",
                role="assistant",
                agent_id="a1",
                ts=now,
            ),
            # Phase 3: Redundant pair
            _msg(
                "The deployment pipeline includes automated testing and rollback procedures.",
                role="assistant",
                agent_id="a2",
                ts=now + 1,
            ),
            _msg(
                "The deployment pipeline includes automated testing and rollback procedures.",
                role="assistant",
                agent_id="a2",
                ts=now + 2,
            ),
            # Phase 4: Irrelevant tool output
            _msg(lines, role="tool", token_estimate=500, ts=now + 3),
            # Protected
            _msg("System prompt.", role="system", ts=0.0),
            _msg("User query.", role="user", ts=now + 4),
        ]

        result = pruner.prune(msgs, task_context="fix authentication bug")
        reasons_found = {d.reason for d in result.decisions if d.reason is not None}
        # Should have at least EMPTY + one of STALE/REDUNDANT
        assert PruneReason.EMPTY in reasons_found
        assert len(reasons_found) >= 2
        # Protected survived
        kept_roles = {m.role for m in result.kept_messages}
        assert "system" in kept_roles
        assert "user" in kept_roles

    def test_idempotent_double_prune(self, pruner):
        """Pruning already-pruned output should not change anything."""
        msgs = [
            _msg("Valid message one with content.", role="assistant"),
            _msg("", role="assistant"),  # Will be pruned
            _msg("Valid message two with content.", role="assistant"),
        ]
        result1 = pruner.prune(msgs)
        result2 = pruner.prune(result1.kept_messages)
        assert result2.kept_count == result1.kept_count
        assert result2.pruned_count == 0

    def test_reduction_percentage_calculation(self, pruner):
        """Verify token_reduction_pct is calculated correctly."""
        msgs = [
            _msg("", role="assistant", token_estimate=100),  # Pruned
            _msg("Kept message with content.", role="assistant", token_estimate=100),
        ]
        result = pruner.prune(msgs)
        # 100 pruned out of 200 total = 50%
        assert result.token_reduction_pct == pytest.approx(50.0)
        assert result.original_tokens == 200
        assert result.pruned_tokens == 100
