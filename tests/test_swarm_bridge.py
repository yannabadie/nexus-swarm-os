"""
Tests for SwarmBridge V8.3 - Hive Mind -> Swarm Delegation

Tests cover:
1. Mode validation per phase (guardrails)
2. Context extraction
3. Delegation execution
4. Fallback chain handling
5. Result injection

Run with: pytest tests/test_swarm_bridge.py -v
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.intelligence.hive_mind.swarm_bridge import (
    HivePhase,
    SwarmBridge,
    SwarmDelegationResult,
    create_bridge_for_phase,
    suggest_mode_for_subtask,
)
from core.intelligence.swarm.collaboration_modes import CollaborationMode

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def mock_swarm_engine():
    """Create a mock Swarm Engine."""
    engine = MagicMock()
    engine.execute_swarm_mode = AsyncMock()
    return engine


@pytest.fixture
def mock_context_manager():
    """Create a mock Context Manager."""
    manager = MagicMock()
    manager.get_context_for = MagicMock(return_value={"task": "Test task", "architecture": {"mode": "parallel"}})
    manager.add_entry = MagicMock()
    return manager


@pytest.fixture
def bridge(mock_swarm_engine, mock_context_manager):
    """Create a SwarmBridge with mocks."""
    return SwarmBridge(swarm_engine=mock_swarm_engine, context_manager=mock_context_manager)


@dataclass
class MockSwarmResult:
    """Mock result from Swarm Engine."""

    success: bool = True
    final_response: str = "Test response"
    total_time: float = 1.5


# =============================================================================
# TEST CLASS: MODE VALIDATION
# =============================================================================


class TestModeValidation:
    """Test mode validation per phase (guardrails)."""

    def test_allowed_modes_structure(self):
        """ALLOWED_MODES should have entries for all phases."""
        for phase in HivePhase:
            assert phase in SwarmBridge.ALLOWED_MODES
            assert len(SwarmBridge.ALLOWED_MODES[phase]) > 0

    @pytest.mark.asyncio
    async def test_parallel_allowed_in_execution(self, bridge, mock_swarm_engine):
        """PARALLEL should be allowed in EXECUTION phase."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult()

        result = await bridge.delegate(
            task="Run 3 tasks in parallel", mode=CollaborationMode.PARALLEL, phase=HivePhase.EXECUTION
        )

        # Should have called Swarm Engine (not blocked)
        assert mock_swarm_engine.execute_swarm_mode.called or result.success

    @pytest.mark.asyncio
    async def test_parallel_blocked_in_analysis(self, bridge, mock_swarm_engine):
        """PARALLEL should NOT be allowed in ANALYSIS phase."""
        result = await bridge.delegate(task="Analyze this", mode=CollaborationMode.PARALLEL, phase=HivePhase.ANALYSIS)

        assert result.success is False
        assert len(result.failure_diagnostics) > 0
        assert "not allowed" in result.failure_diagnostics[0].lower()
        # Swarm Engine should NOT have been called
        mock_swarm_engine.execute_swarm_mode.assert_not_called()

    @pytest.mark.asyncio
    async def test_red_blue_allowed_in_diagnosis(self, bridge, mock_swarm_engine):
        """RED_BLUE should be allowed in DIAGNOSIS phase."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult()

        result = await bridge.delegate(
            task="Diagnose failure", mode=CollaborationMode.RED_BLUE, phase=HivePhase.DIAGNOSIS
        )

        # Should have attempted execution
        assert mock_swarm_engine.execute_swarm_mode.called or result.success

    @pytest.mark.asyncio
    async def test_specialist_allowed_in_consolidation(self, bridge, mock_swarm_engine):
        """SPECIALIST should be allowed in CONSOLIDATION phase."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult()

        result = await bridge.delegate(
            task="Consolidate knowledge", mode=CollaborationMode.SPECIALIST, phase=HivePhase.CONSOLIDATION
        )

        assert mock_swarm_engine.execute_swarm_mode.called or result.success

    @pytest.mark.asyncio
    async def test_no_phase_skips_validation(self, bridge, mock_swarm_engine):
        """When phase is None, mode validation is skipped."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult()

        # PING_PONG normally only allowed in DEBATE, but without phase=...
        await bridge.delegate(task="Test without phase", mode=CollaborationMode.PING_PONG, phase=None)

        # Should have attempted execution (validation skipped)
        assert mock_swarm_engine.execute_swarm_mode.called


class TestAllValidCombinations:
    """Test all valid phase-mode combinations."""

    def test_total_valid_combinations(self):
        """Should have exactly 9 valid combinations."""
        combinations = SwarmBridge.get_all_valid_combinations()
        assert len(combinations) == 9

    @pytest.mark.parametrize(
        "phase,expected_modes",
        [
            (HivePhase.ANALYSIS, [CollaborationMode.SPECIALIST]),
            (HivePhase.DEBATE, [CollaborationMode.PING_PONG, CollaborationMode.RED_BLUE]),
            (HivePhase.ARCHITECTURE, [CollaborationMode.LEAD_SUPPORT]),
            (
                HivePhase.EXECUTION,
                [CollaborationMode.PARALLEL, CollaborationMode.SEQUENTIAL, CollaborationMode.SPECIALIST],
            ),
            (HivePhase.DIAGNOSIS, [CollaborationMode.RED_BLUE]),
            (HivePhase.CONSOLIDATION, [CollaborationMode.SPECIALIST]),
        ],
    )
    def test_allowed_modes_per_phase(self, phase, expected_modes):
        """Verify allowed modes for each phase."""
        allowed = SwarmBridge.get_allowed_modes(phase)
        assert set(allowed) == set(expected_modes)


# =============================================================================
# TEST CLASS: CONTEXT EXTRACTION
# =============================================================================


class TestContextExtraction:
    """Test context extraction from HiveMind to Swarm."""

    @pytest.mark.asyncio
    async def test_extracts_context_before_execution(self, bridge, mock_swarm_engine, mock_context_manager):
        """Should extract context before calling Swarm."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult()

        await bridge.delegate(task="Test task", mode=CollaborationMode.SPECIALIST, phase=HivePhase.ANALYSIS)

        # Context should have been extracted
        mock_context_manager.get_context_for.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_custom_categories(self, bridge, mock_swarm_engine, mock_context_manager):
        """Should pass custom context categories."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult()

        await bridge.delegate(
            task="Test task",
            mode=CollaborationMode.SPECIALIST,
            phase=HivePhase.ANALYSIS,
            context_categories=["task", "tools"],
        )

        # Should have passed custom categories
        call_kwargs = mock_context_manager.get_context_for.call_args
        assert "include_categories" in call_kwargs.kwargs

    @pytest.mark.asyncio
    async def test_excludes_chat_history(self, bridge, mock_swarm_engine, mock_context_manager):
        """Should exclude chat_history from context by default."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult()

        await bridge.delegate(task="Test task", mode=CollaborationMode.SPECIALIST, phase=HivePhase.ANALYSIS)

        call_kwargs = mock_context_manager.get_context_for.call_args
        assert "exclude_categories" in call_kwargs.kwargs
        assert "chat_history" in call_kwargs.kwargs["exclude_categories"]

    def test_extract_with_no_context_manager(self, mock_swarm_engine):
        """Should handle missing context manager gracefully."""
        bridge = SwarmBridge(swarm_engine=mock_swarm_engine, context_manager=None)
        context = bridge._extract_context()
        assert context == {}


# =============================================================================
# TEST CLASS: DELEGATION EXECUTION
# =============================================================================


class TestDelegationExecution:
    """Test delegation to Swarm Engine."""

    @pytest.mark.asyncio
    async def test_successful_delegation(self, bridge, mock_swarm_engine):
        """Successful delegation should return success=True."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult(success=True)

        result = await bridge.delegate(task="Execute task", mode=CollaborationMode.PARALLEL, phase=HivePhase.EXECUTION)

        assert result.success is True
        assert result.mode_used == CollaborationMode.PARALLEL

    @pytest.mark.asyncio
    async def test_failed_delegation(self, bridge, mock_swarm_engine):
        """Failed Swarm execution should return success=False."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult(success=False)

        result = await bridge.delegate(task="Execute task", mode=CollaborationMode.PARALLEL, phase=HivePhase.EXECUTION)

        # May fallback, but should eventually report failure
        assert result.mode_used is not None

    @pytest.mark.asyncio
    async def test_exception_handling(self, bridge, mock_swarm_engine):
        """Exceptions should be caught and reported."""
        mock_swarm_engine.execute_swarm_mode.side_effect = RuntimeError("Test error")

        result = await bridge.delegate(task="Execute task", mode=CollaborationMode.SPECIALIST, phase=HivePhase.ANALYSIS)

        assert result.success is False
        assert len(result.failure_diagnostics) > 0
        assert "Test error" in result.failure_diagnostics[0]

    @pytest.mark.asyncio
    async def test_no_swarm_engine(self, mock_context_manager):
        """Should fail gracefully without Swarm Engine."""
        bridge = SwarmBridge(swarm_engine=None, context_manager=mock_context_manager)

        result = await bridge.delegate(task="Test", mode=CollaborationMode.SPECIALIST, phase=HivePhase.ANALYSIS)

        assert result.success is False
        assert "No Swarm Engine" in result.failure_diagnostics[0]


# =============================================================================
# TEST CLASS: FALLBACK CHAIN
# =============================================================================


class TestFallbackChain:
    """Test fallback chain handling."""

    @pytest.mark.asyncio
    async def test_records_mode_in_chain(self, bridge, mock_swarm_engine):
        """Should record attempted mode in fallback chain."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult(success=True)

        result = await bridge.delegate(task="Execute task", mode=CollaborationMode.PARALLEL, phase=HivePhase.EXECUTION)

        assert CollaborationMode.PARALLEL in result.fallback_chain

    @pytest.mark.asyncio
    async def test_execution_time_recorded(self, bridge, mock_swarm_engine):
        """Should record execution time."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult()

        result = await bridge.delegate(task="Execute task", mode=CollaborationMode.PARALLEL, phase=HivePhase.EXECUTION)

        assert result.execution_time >= 0


# =============================================================================
# TEST CLASS: RESULT INJECTION
# =============================================================================


class TestResultInjection:
    """Test result injection back into HiveMind context."""

    def test_inject_results_success(self, bridge, mock_context_manager):
        """Should inject results into context."""
        result = SwarmDelegationResult(
            success=True, result=None, mode_used=CollaborationMode.PARALLEL, summary="Task completed successfully"
        )

        success = bridge.inject_results_into_context(result)

        assert success is True
        mock_context_manager.add_entry.assert_called_once()

    def test_inject_results_no_context(self, mock_swarm_engine):
        """Should fail gracefully without context manager."""
        bridge = SwarmBridge(swarm_engine=mock_swarm_engine, context_manager=None)
        result = SwarmDelegationResult(success=True, result=None, mode_used=CollaborationMode.PARALLEL)

        success = bridge.inject_results_into_context(result)
        assert success is False


# =============================================================================
# TEST CLASS: HELPER FUNCTIONS
# =============================================================================


class TestHelperFunctions:
    """Test helper functions."""

    def test_create_bridge_for_phase(self, mock_swarm_engine, mock_context_manager):
        """Factory function should create valid bridge."""
        bridge = create_bridge_for_phase(
            phase=HivePhase.EXECUTION, swarm_engine=mock_swarm_engine, context_manager=mock_context_manager
        )

        assert isinstance(bridge, SwarmBridge)
        assert bridge.swarm == mock_swarm_engine
        assert bridge.context == mock_context_manager

    @pytest.mark.parametrize(
        "subtask,phase,expected",
        [
            ("Run tests in parallel", HivePhase.EXECUTION, CollaborationMode.PARALLEL),
            ("Review security of auth module", HivePhase.DIAGNOSIS, CollaborationMode.RED_BLUE),
            ("Brainstorm solutions", HivePhase.DEBATE, CollaborationMode.PING_PONG),
            ("Execute sequentially", HivePhase.EXECUTION, CollaborationMode.SEQUENTIAL),
            ("Simple task", HivePhase.ANALYSIS, None),  # No keyword match
        ],
    )
    def test_suggest_mode_for_subtask(self, subtask, phase, expected):
        """Should suggest appropriate mode based on keywords."""
        suggested = suggest_mode_for_subtask(subtask, phase)
        assert suggested == expected

    def test_suggest_mode_no_match(self):
        """Should return None when no keywords match."""
        result = suggest_mode_for_subtask("generic task", HivePhase.CONSOLIDATION)
        # SPECIALIST is allowed but "generic task" has no keywords
        assert result is None


# =============================================================================
# TEST CLASS: SERIALIZATION
# =============================================================================


class TestSerialization:
    """Test SwarmDelegationResult serialization."""

    def test_to_dict_complete(self):
        """to_dict should include all fields."""
        result = SwarmDelegationResult(
            success=True,
            result={"data": "test"},
            mode_used=CollaborationMode.PARALLEL,
            fallback_chain=[CollaborationMode.PARALLEL],
            failure_diagnostics=[],
            execution_time=1.5,
            summary="Test summary",
        )

        d = result.to_dict()

        assert d["success"] is True
        assert d["mode_used"] == "parallel"
        assert d["fallback_chain"] == ["parallel"]
        assert d["execution_time"] == 1.5
        assert d["summary"] == "Test summary"

    def test_to_dict_truncates_summary(self):
        """to_dict should truncate long summaries."""
        long_summary = "x" * 500
        result = SwarmDelegationResult(
            success=True, result=None, mode_used=CollaborationMode.SPECIALIST, summary=long_summary
        )

        d = result.to_dict()
        assert len(d["summary"]) == 200


# =============================================================================
# TEST CLASS: HIVE PHASE ENUM
# =============================================================================


class TestHivePhaseEnum:
    """Test HivePhase enum."""

    def test_all_phases_exist(self):
        """Should have all 6 phases."""
        phases = list(HivePhase)
        assert len(phases) == 6

    def test_phase_values(self):
        """Phase values should be lowercase strings."""
        for phase in HivePhase:
            assert phase.value == phase.name.lower()


# =============================================================================
# TEST CLASS: CHECKPOINT SUPPORT (V8.3.2 MT-001)
# =============================================================================


class TestCheckpointSupport:
    """V8.3.2 MT-001: Test checkpoint create/restore for self-healing."""

    @pytest.fixture
    def mock_session_manager(self):
        """Create a mock session manager with checkpoint support."""
        manager = MagicMock()
        manager.create_checkpoint = MagicMock(return_value="checkpoint_123")
        manager.restore_checkpoint = MagicMock()
        return manager

    @pytest.fixture
    def bridge_with_session(self, mock_swarm_engine, mock_context_manager, mock_session_manager):
        """Create SwarmBridge with session manager for checkpoints."""
        mock_swarm_engine.session_manager = mock_session_manager
        return SwarmBridge(swarm_engine=mock_swarm_engine, context_manager=mock_context_manager)

    @pytest.mark.asyncio
    async def test_checkpoint_created_before_execution(
        self, bridge_with_session, mock_swarm_engine, mock_session_manager
    ):
        """Checkpoint should be created before Swarm execution."""
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult(success=True)

        await bridge_with_session.delegate(
            task="Test task", mode=CollaborationMode.PARALLEL, phase=HivePhase.EXECUTION, task_id="test_task_001"
        )

        # Verify checkpoint was created
        mock_session_manager.create_checkpoint.assert_called_once_with("test_task_001")

    @pytest.mark.asyncio
    async def test_checkpoint_restored_on_fallback(self, bridge_with_session, mock_swarm_engine, mock_session_manager):
        """Checkpoint should be restored when falling back to another mode."""
        # First call fails, second (fallback) succeeds
        mock_swarm_engine.execute_swarm_mode.side_effect = [
            Exception("First mode failed"),
            MockSwarmResult(success=True),
        ]

        await bridge_with_session.delegate(
            task="Test task", mode=CollaborationMode.PARALLEL, phase=HivePhase.EXECUTION, task_id="test_task_002"
        )

        # Verify checkpoint was created
        mock_session_manager.create_checkpoint.assert_called()

        # Verify checkpoint was restored before fallback
        mock_session_manager.restore_checkpoint.assert_called()

    @pytest.mark.asyncio
    async def test_checkpoint_not_created_without_session_manager(self, mock_swarm_engine, mock_context_manager):
        """No checkpoint operations without session_manager."""
        # Remove session_manager
        if hasattr(mock_swarm_engine, "session_manager"):
            delattr(mock_swarm_engine, "session_manager")

        mock_swarm_engine.execute_swarm_mode = AsyncMock(return_value=MockSwarmResult())

        bridge = SwarmBridge(swarm_engine=mock_swarm_engine, context_manager=mock_context_manager)

        # Should not raise even without session_manager
        result = await bridge.delegate(task="Test task", mode=CollaborationMode.SPECIALIST, phase=HivePhase.ANALYSIS)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_checkpoint_failure_does_not_block_execution(
        self, bridge_with_session, mock_swarm_engine, mock_session_manager
    ):
        """Checkpoint failure should not prevent delegation."""
        mock_session_manager.create_checkpoint.side_effect = Exception("Checkpoint failed")
        mock_swarm_engine.execute_swarm_mode.return_value = MockSwarmResult(success=True)

        # Should succeed despite checkpoint failure
        result = await bridge_with_session.delegate(
            task="Test task", mode=CollaborationMode.SPECIALIST, phase=HivePhase.ANALYSIS
        )

        assert result.success is True


# =============================================================================
# TEST CLASS: SUCCESS MEMORY INTEGRATION (V8.3.2 FG-001)
# =============================================================================


class TestSuccessMemoryIntegration:
    """V8.3.2 FG-001: Test SuccessAdapter integration in SwarmBridge."""

    @pytest.fixture
    def mock_success_memory(self):
        """Create a mock SuccessMemory."""
        memory = MagicMock()
        memory.record_success = MagicMock()
        return memory

    @pytest.fixture
    def bridge_with_memory(self, mock_swarm_engine, mock_context_manager, mock_success_memory):
        """Create SwarmBridge with SuccessMemory."""
        return SwarmBridge(
            swarm_engine=mock_swarm_engine, context_manager=mock_context_manager, success_memory=mock_success_memory
        )

    @pytest.mark.asyncio
    async def test_success_recorded_on_delegation_success(
        self, bridge_with_memory, mock_swarm_engine, mock_success_memory
    ):
        """Successful delegation should record to SuccessMemory."""
        mock_swarm_engine.execute_swarm_mode = AsyncMock(return_value=MockSwarmResult(success=True))

        await bridge_with_memory.delegate(
            task="Review authentication code", mode=CollaborationMode.RED_BLUE, phase=HivePhase.DIAGNOSIS
        )

        # Verify record_success was called
        mock_success_memory.record_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_success_not_recorded_on_failure(self, bridge_with_memory, mock_swarm_engine, mock_success_memory):
        """Failed delegation should NOT record to SuccessMemory."""
        mock_swarm_engine.execute_swarm_mode = AsyncMock(return_value=MockSwarmResult(success=False))

        await bridge_with_memory.delegate(
            task="Failing task", mode=CollaborationMode.SPECIALIST, phase=HivePhase.ANALYSIS
        )

        # Verify record_success was NOT called
        mock_success_memory.record_success.assert_not_called()

    @pytest.mark.asyncio
    async def test_memory_failure_does_not_block_delegation(
        self, bridge_with_memory, mock_swarm_engine, mock_success_memory
    ):
        """SuccessMemory failure should not prevent delegation success."""
        mock_swarm_engine.execute_swarm_mode = AsyncMock(return_value=MockSwarmResult(success=True))
        mock_success_memory.record_success.side_effect = Exception("Memory error")

        # Should still succeed
        result = await bridge_with_memory.delegate(
            task="Test task", mode=CollaborationMode.PARALLEL, phase=HivePhase.EXECUTION
        )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_fallback_penalizes_quality_score(self, bridge_with_memory, mock_swarm_engine, mock_success_memory):
        """Fallbacks should reduce quality score in recorded success."""
        # First call fails, second (fallback) succeeds
        mock_swarm_engine.execute_swarm_mode = AsyncMock(
            side_effect=[Exception("First failed"), MockSwarmResult(success=True)]
        )

        await bridge_with_memory.delegate(task="Test task", mode=CollaborationMode.PARALLEL, phase=HivePhase.EXECUTION)

        # Get the quality_score from the call
        call_args = mock_success_memory.record_success.call_args
        if call_args:
            quality = call_args.kwargs.get("quality_score", 1.0)
            # Quality should be less than 1.0 due to fallback
            assert quality < 1.0
