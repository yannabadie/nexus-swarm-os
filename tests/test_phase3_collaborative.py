"""
Tests for Phase 3 Collaborative Architecture (V12.4)

Tests the new collaborative architecture generation:
- Phase 3a: Claude generates initial architecture
- Phase 3b: Gemini validates and optimizes
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_driver_response(content: str, is_success: bool = True):
    """Create a mock DriverResponse for use in driver.invoke() mocks."""
    response = MagicMock()
    response.is_success = is_success
    response.content = content
    response.error_message = None if is_success else "Error"
    response.input_tokens = 100
    response.output_tokens = 50
    return response


# Helper to build a DebateResult with current fields
def make_debate_result(final_approach="Test approach", final_capabilities=None):
    from core.intelligence.hive_mind.types import DebateResult

    if final_capabilities is None:
        final_capabilities = ["coding"]

    return DebateResult(
        status="CONSENSUS_REACHED",
        final_approach=final_approach,
        final_capabilities=final_capabilities,
        final_mode="sequential",
        debate_history=[],
        total_turns=1,
        resolved_disagreements=[],
        unresolved_disagreements=[],
        consensus_confidence=0.9,
        satisfactions={"gemini": 0.9, "claude": 0.9},
    )


# Test the feature flag
def test_feature_flag_default_enabled():
    """Feature flag should be enabled by default."""
    from core.intelligence.hive_mind.phases.phase_architecture import COLLABORATIVE_ARCHITECTURE

    assert COLLABORATIVE_ARCHITECTURE is True


def test_feature_flag_can_be_disabled():
    """Feature flag can be disabled via environment variable."""
    import os

    with patch.dict(os.environ, {"NEXUS_COLLABORATIVE_ARCHITECTURE": "false"}):
        # Need to reimport to pick up new env var
        import importlib

        from core.intelligence.hive_mind.phases import phase_architecture

        importlib.reload(phase_architecture)
        assert phase_architecture.COLLABORATIVE_ARCHITECTURE is False

        # Reset
        with patch.dict(os.environ, {"NEXUS_COLLABORATIVE_ARCHITECTURE": "true"}):
            importlib.reload(phase_architecture)


class TestCollaborativeArchitecture:
    """Test suite for collaborative architecture generation."""

    @pytest.fixture
    def mock_claude_driver(self):
        """Mock Claude driver."""
        driver = MagicMock()
        claude_content = json.dumps(
            {
                "agents_to_use": ["claude", "gemini"],
                "agents_to_spawn": [],
                "execution_strategy": "sequential",
                "execution_steps": [
                    {
                        "name": "analyze",
                        "agent_id": "claude",
                        "action": "Analyze the task",
                        "expected_duration": 30,
                        "depends_on": [],
                        "verification_required": True,
                    },
                    {
                        "name": "execute",
                        "agent_id": "gemini",
                        "action": "Execute the plan",
                        "expected_duration": 60,
                        "depends_on": ["analyze"],
                        "verification_required": False,
                    },
                ],
                "rag_config": {"enabled": True, "depth": "standard", "sources": ["codebase"], "max_chunks": 10},
                "reasoning": "Claude designed this architecture",
            }
        )
        driver.invoke = AsyncMock(return_value=_make_driver_response(claude_content))
        # Keep send_message_async as a tracked mock for backward compat assertions
        driver.send_message_async = driver.invoke
        return driver

    @pytest.fixture
    def mock_gemini_driver(self):
        """Mock Gemini driver."""
        driver = MagicMock()
        gemini_content = json.dumps(
            {
                "validation": "APPROVED",
                "optimizations": ["Added verification to second step"],
                "architecture": {
                    "agents_to_use": ["claude", "gemini"],
                    "agents_to_spawn": [],
                    "execution_strategy": "sequential",
                    "execution_steps": [
                        {
                            "name": "analyze",
                            "agent_id": "claude",
                            "action": "Analyze the task",
                            "expected_duration": 30,
                            "depends_on": [],
                            "verification_required": True,
                        },
                        {
                            "name": "execute",
                            "agent_id": "gemini",
                            "action": "Execute the plan",
                            "expected_duration": 60,
                            "depends_on": ["analyze"],
                            "verification_required": True,  # Gemini added this
                        },
                    ],
                    "rag_config": {"enabled": True, "depth": "standard", "sources": ["codebase"], "max_chunks": 10},
                    "reasoning": "Optimized by Gemini",
                },
            }
        )
        driver.invoke = AsyncMock(return_value=_make_driver_response(gemini_content))
        # Keep send_message_async as a tracked mock for backward compat assertions
        driver.send_message_async = driver.invoke
        return driver

    @pytest.fixture
    def mock_cost_estimator(self):
        """Mock cost estimator that always approves."""
        estimator = MagicMock()
        estimator.can_afford = MagicMock(return_value=True)
        estimator.can_afford_multiple = MagicMock(return_value=True)
        estimator.record_cost = MagicMock()
        return estimator

    @pytest.fixture
    def mock_context_manager(self):
        """Mock context manager."""
        return MagicMock()

    @pytest.fixture
    def mock_agent_registry(self):
        """Mock agent registry."""
        registry = MagicMock()
        registry.get_active_agents = MagicMock(return_value=[])
        registry.find_similar = MagicMock(return_value=None)
        return registry

    @pytest.fixture
    def mock_user_handler(self):
        """Mock user interaction handler."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_collaborative_calls_claude_then_gemini(
        self,
        mock_claude_driver,
        mock_gemini_driver,
        mock_cost_estimator,
        mock_context_manager,
        mock_agent_registry,
        mock_user_handler,
        tmp_path,
    ):
        """Collaborative mode should call Claude first, then Gemini."""
        from core.intelligence.hive_mind.phases.phase_architecture import ArchitectureGenerationPhase

        phase = ArchitectureGenerationPhase(
            gemini_driver=mock_gemini_driver,
            claude_driver=mock_claude_driver,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            agent_registry=mock_agent_registry,
            user_handler=mock_user_handler,
            workspace_path=tmp_path,
        )

        debate_result = make_debate_result(
            final_approach="Test approach",
            final_capabilities=["coding", "analysis"],
        )

        result = await phase.execute(task="Test task", debate_result=debate_result)

        # Both drivers should have been called
        mock_claude_driver.send_message_async.assert_called_once()
        mock_gemini_driver.send_message_async.assert_called_once()

        # Architecture should be returned
        assert result.architecture is not None
        assert result.architecture.agents_to_use == ["claude", "gemini"]

    @pytest.mark.asyncio
    async def test_collaborative_falls_back_to_claude_on_budget(
        self,
        mock_claude_driver,
        mock_gemini_driver,
        mock_cost_estimator,
        mock_context_manager,
        mock_agent_registry,
        mock_user_handler,
        tmp_path,
    ):
        """Should use Claude-only architecture when budget is exceeded."""
        from core.intelligence.hive_mind.phases.phase_architecture import ArchitectureGenerationPhase

        # Make budget check fail for validation step
        mock_cost_estimator.can_afford = MagicMock(side_effect=lambda x: x != "validate_architecture")

        phase = ArchitectureGenerationPhase(
            gemini_driver=mock_gemini_driver,
            claude_driver=mock_claude_driver,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            agent_registry=mock_agent_registry,
            user_handler=mock_user_handler,
            workspace_path=tmp_path,
        )

        debate_result = make_debate_result(
            final_approach="Test approach",
            final_capabilities=["coding"],
        )

        await phase.execute(task="Test task", debate_result=debate_result)

        # Only Claude should have been called
        mock_claude_driver.send_message_async.assert_called_once()
        mock_gemini_driver.send_message_async.assert_not_called()

    @pytest.mark.asyncio
    async def test_collaborative_falls_back_on_gemini_error(
        self,
        mock_claude_driver,
        mock_gemini_driver,
        mock_cost_estimator,
        mock_context_manager,
        mock_agent_registry,
        mock_user_handler,
        tmp_path,
    ):
        """Should use Claude architecture when Gemini validation fails."""
        from core.intelligence.hive_mind.phases.phase_architecture import ArchitectureGenerationPhase

        # Make Gemini fail
        mock_gemini_driver.invoke = AsyncMock(side_effect=Exception("Gemini error"))
        mock_gemini_driver.send_message_async = mock_gemini_driver.invoke

        phase = ArchitectureGenerationPhase(
            gemini_driver=mock_gemini_driver,
            claude_driver=mock_claude_driver,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            agent_registry=mock_agent_registry,
            user_handler=mock_user_handler,
            workspace_path=tmp_path,
        )

        debate_result = make_debate_result(
            final_approach="Test approach",
            final_capabilities=["coding"],
        )

        result = await phase.execute(task="Test task", debate_result=debate_result)

        # Architecture should still be returned (from Claude)
        assert result.architecture is not None
        mock_claude_driver.send_message_async.assert_called_once()


class TestLegacyArchitecture:
    """Test suite for legacy (Gemini-only) architecture generation."""

    @pytest.fixture
    def mock_gemini_driver(self):
        """Mock Gemini driver."""
        driver = MagicMock()
        gemini_content = json.dumps(
            {
                "agents_to_use": ["gemini"],
                "agents_to_spawn": [],
                "execution_strategy": "sequential",
                "execution_steps": [
                    {
                        "name": "execute",
                        "agent_id": "gemini",
                        "action": "Do the task",
                        "expected_duration": 60,
                        "depends_on": [],
                        "verification_required": False,
                    }
                ],
                "rag_config": {"enabled": True, "depth": "shallow", "sources": ["codebase"], "max_chunks": 5},
                "reasoning": "Gemini solo architecture",
            }
        )
        driver.invoke = AsyncMock(return_value=_make_driver_response(gemini_content))
        driver.send_message_async = driver.invoke
        return driver

    @pytest.mark.asyncio
    async def test_legacy_mode_only_calls_gemini(self, mock_gemini_driver, tmp_path):
        """Legacy mode should only call Gemini."""
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"NEXUS_COLLABORATIVE_ARCHITECTURE": "false"}):
            # Reimport to pick up env var
            import importlib

            from core.intelligence.hive_mind.phases import phase_architecture

            importlib.reload(phase_architecture)

            mock_claude_driver = MagicMock()
            mock_claude_driver.invoke = AsyncMock()
            mock_claude_driver.send_message_async = mock_claude_driver.invoke
            mock_cost_estimator = MagicMock()
            mock_cost_estimator.can_afford_multiple = MagicMock(return_value=True)
            mock_cost_estimator.record_cost = MagicMock()

            phase = phase_architecture.ArchitectureGenerationPhase(
                gemini_driver=mock_gemini_driver,
                claude_driver=mock_claude_driver,
                cost_estimator=mock_cost_estimator,
                context_manager=MagicMock(),
                agent_registry=MagicMock(get_active_agents=MagicMock(return_value=[])),
                user_handler=MagicMock(),
                workspace_path=tmp_path,
            )

            debate_result = make_debate_result(
                final_approach="Test",
                final_capabilities=["test"],
            )

            await phase.execute(task="Test", debate_result=debate_result)

            # Only Gemini should be called (via invoke, aliased to send_message_async)
            mock_gemini_driver.send_message_async.assert_called_once()
            mock_claude_driver.send_message_async.assert_not_called()

            # Reset
            with patch.dict(os.environ, {"NEXUS_COLLABORATIVE_ARCHITECTURE": "true"}):
                importlib.reload(phase_architecture)
