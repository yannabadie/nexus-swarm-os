"""
Tests for core/constants.py - V9.5

Validates centralized constants are correctly defined and accessible.
"""

import pytest

from core.constants import (
    CONSTANTS_VERSION,
    COST_ESTIMATES,
    DEBATE_LIMITS,
    EXECUTION_LIMITS,
    MEMORY_LIMITS,
    RETRY_LIMITS,
    SAGA_LIMITS,
    THRESHOLDS,
    TIMEOUTS,
)


class TestTimeouts:
    """Test Timeouts constants."""

    def test_timeouts_are_positive(self):
        """All timeouts should be positive numbers."""
        assert TIMEOUTS.BASH_COMMAND > 0
        assert TIMEOUTS.GIT_COMMAND > 0
        assert TIMEOUTS.WEB_SEARCH > 0
        assert TIMEOUTS.WEB_FETCH > 0
        assert TIMEOUTS.CFL_VALIDATION > 0
        assert TIMEOUTS.HIVE_MIND_ASYNC > 0

    def test_timeouts_reasonable_values(self):
        """Timeouts should be within reasonable ranges."""
        # Bash commands: 1-600 seconds
        assert 1 <= TIMEOUTS.BASH_COMMAND <= 600
        # Web operations: 10-300 seconds
        assert 10 <= TIMEOUTS.WEB_SEARCH <= 300
        assert 5 <= TIMEOUTS.WEB_FETCH <= 300

    def test_timeouts_frozen(self):
        """Timeout dataclass should be frozen (immutable)."""
        with pytest.raises(AttributeError):  # FrozenInstanceError
            TIMEOUTS.BASH_COMMAND = 999


class TestRetryLimits:
    """Test RetryLimits constants."""

    def test_retry_limits_positive(self):
        """All retry limits should be positive integers."""
        assert RETRY_LIMITS.MAX_PARSE_FAILURES > 0
        assert RETRY_LIMITS.MAX_TOOL_ITERATIONS > 0
        assert RETRY_LIMITS.MAX_FSM_ITERATIONS > 0
        assert RETRY_LIMITS.MAX_CFL_ITERATIONS > 0

    def test_retry_limits_reasonable(self):
        """Retry limits should prevent infinite loops."""
        assert RETRY_LIMITS.MAX_PARSE_FAILURES <= 10
        assert RETRY_LIMITS.MAX_TOOL_ITERATIONS <= 20
        assert RETRY_LIMITS.MAX_FSM_ITERATIONS <= 100


class TestSagaLimits:
    """Test SagaLimits constants (V9.5 - Gemini feedback)."""

    def test_saga_limits_exist(self):
        """SagaLimits should be defined."""
        assert SAGA_LIMITS is not None

    def test_max_rollback_prevents_infinite_loops(self):
        """MAX_ROLLBACK_ATTEMPTS should be small to prevent loops."""
        assert 1 <= SAGA_LIMITS.MAX_ROLLBACK_ATTEMPTS <= 5
        # Default should be 3 (from plan)
        assert SAGA_LIMITS.MAX_ROLLBACK_ATTEMPTS == 3

    def test_rollback_timeout_positive(self):
        """Rollback timeout should be positive."""
        assert SAGA_LIMITS.ROLLBACK_TIMEOUT > 0

    def test_checkpoint_retention_hours(self):
        """Checkpoint retention should be reasonable."""
        assert 1 <= SAGA_LIMITS.CHECKPOINT_RETENTION_HOURS <= 168  # 1h to 1 week


class TestDebateLimits:
    """Test DebateLimits constants."""

    def test_min_less_than_max(self):
        """MIN_TURNS should be less than MAX_TURNS."""
        assert DEBATE_LIMITS.MIN_TURNS < DEBATE_LIMITS.MAX_TURNS

    def test_complex_range_valid(self):
        """COMPLEX task range should be valid."""
        assert DEBATE_LIMITS.COMPLEX_TURNS_MIN < DEBATE_LIMITS.COMPLEX_TURNS_MAX

    def test_expert_range_valid(self):
        """EXPERT task range should be valid."""
        assert DEBATE_LIMITS.EXPERT_TURNS_MIN < DEBATE_LIMITS.EXPERT_TURNS_MAX

    def test_expert_more_than_complex(self):
        """EXPERT tasks should allow more turns than COMPLEX."""
        assert DEBATE_LIMITS.EXPERT_TURNS_MAX >= DEBATE_LIMITS.COMPLEX_TURNS_MAX


class TestMemoryLimits:
    """Test MemoryLimits constants."""

    def test_rag_chunks_positive(self):
        """RAG chunk limits should be positive."""
        assert MEMORY_LIMITS.RAG_CHUNKS_RETRIEVE > 0
        assert MEMORY_LIMITS.RAG_CHUNKS_MAX > 0

    def test_rag_max_greater_than_retrieve(self):
        """Max chunks should be >= retrieval count."""
        assert MEMORY_LIMITS.RAG_CHUNKS_MAX >= MEMORY_LIMITS.RAG_CHUNKS_RETRIEVE

    def test_similarity_score_valid_range(self):
        """Similarity score should be 0-1."""
        assert 0 <= MEMORY_LIMITS.MIN_SIMILARITY_SCORE <= 1


class TestExecutionLimits:
    """Test ExecutionLimits constants."""

    def test_swarm_max_rounds_positive(self):
        """Swarm max rounds should be positive."""
        assert EXECUTION_LIMITS.SWARM_MAX_ROUNDS > 0

    def test_max_swarm_depth_prevents_inception(self):
        """MAX_SWARM_DEPTH should prevent Inception Trap."""
        assert 1 <= EXECUTION_LIMITS.MAX_SWARM_DEPTH <= 5


class TestThresholds:
    """Test ThresholdConstants."""

    def test_confidence_valid_range(self):
        """Confidence threshold should be 0-1."""
        assert 0 <= THRESHOLDS.DEFAULT_CONFIDENCE <= 1

    def test_penalty_valid_range(self):
        """Fallback penalty should be positive and small."""
        assert 0 < THRESHOLDS.FALLBACK_QUALITY_PENALTY <= 0.5


class TestCostEstimates:
    """Test CostEstimates constants."""

    def test_all_costs_positive(self):
        """All cost estimates should be positive."""
        assert COST_ESTIMATES.ANALYSIS_COMPARE > 0
        assert COST_ESTIMATES.CONSENSUS_CHECK > 0
        assert COST_ESTIMATES.EXECUTION_STEP > 0
        assert COST_ESTIMATES.DEFAULT_OPERATION > 0


class TestConstantsVersion:
    """Test version marker."""

    def test_version_format(self):
        """Version should be semver format."""
        parts = CONSTANTS_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_version_is_9_x(self):
        """Version should be 9.x.x (V9 series)."""
        assert CONSTANTS_VERSION.startswith("9.")
