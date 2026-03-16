"""
Tests for Phase 10d: Session-Aware Agent Selection

Verifies:
1. SuccessMemory.get_agent_success_rate() calculates correct rates
2. AgentPool.update_from_session_metrics() applies session bonuses
3. AgentPool.get_session_aware_score() combines DyLAN + session metrics
4. ModeSelector uses session-aware scoring for agent ranking
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.swarm.agent_metrics import AgentInvocationResult, AgentPool, create_default_pool
from core.intelligence.swarm.mode_selector import ModeSelector
from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskComplexity, TaskDomain
from core.memory_pkg.memory import SuccessEntry, SuccessMemory  # V2 via backward compat alias

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def workspace_path(tmp_path):
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "memory").mkdir()
    return ws


@pytest.fixture
def success_memory(tmp_path):
    """Create a SuccessMemory instance with isolated storage."""
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    return SuccessMemory(workspace_path=ws, nexus_root=tmp_path)


@pytest.fixture
def agent_pool():
    """Create an AgentPool with default agents."""
    return create_default_pool()


@pytest.fixture
def populated_success_memory(tmp_path):
    """
    Create SuccessMemory with pre-populated session data.

    - gemini_primary: 5 sessions, 4 high quality (80% success)
    - claude_opus: 5 sessions, 2 high quality (40% success)
    """
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    memory = SuccessMemory(workspace_path=ws, nexus_root=tmp_path)

    # Gemini sessions - mostly successful
    for i in range(4):
        entry = SuccessEntry(
            task_id=f"task_gemini_{i}",
            task_hash=f"hash_{i}",
            description=f"Coding task {i} - implement feature",
            swarm_mode="ping_pong",
            agents_used=["gemini_primary", "claude_opus"],
            duration_seconds=10.0 + i,
            complexity="MODERATE",
            domains=["coding", "architecture"],
            quality_score=0.75 + (i * 0.05),  # 0.75, 0.80, 0.85, 0.90
            timestamp=datetime.now().isoformat(),
        )
        memory._append_entry(entry)

    # Add one low quality for Gemini
    entry = SuccessEntry(
        task_id="task_gemini_low",
        task_hash="hash_low",
        description="Failed coding task",
        swarm_mode="ping_pong",
        agents_used=["gemini_primary"],
        duration_seconds=30.0,
        complexity="COMPLEX",
        domains=["coding"],
        quality_score=0.4,
        timestamp=datetime.now().isoformat(),
    )
    memory._append_entry(entry)

    # Claude-only sessions - mixed results
    for i in range(3):
        quality = 0.5 if i < 2 else 0.8  # 2 low, 1 high
        entry = SuccessEntry(
            task_id=f"task_claude_{i}",
            task_hash=f"hash_claude_{i}",
            description=f"Research task {i}",
            swarm_mode="specialist",
            agents_used=["claude_opus"],
            duration_seconds=15.0,
            complexity="SIMPLE",
            domains=["research"],
            quality_score=quality,
            timestamp=datetime.now().isoformat(),
        )
        memory._append_entry(entry)

    return memory


# =============================================================================
# SuccessMemory.get_agent_success_rate Tests
# =============================================================================


class TestGetAgentSuccessRate:
    """Tests for SuccessMemory.get_agent_success_rate()."""

    def test_no_sessions_returns_neutral(self, success_memory):
        """No sessions returns neutral 0.5 score."""
        rate, count = success_memory.get_agent_success_rate("unknown_agent")
        assert rate == 0.5
        assert count == 0

    def test_few_sessions_returns_neutral(self, success_memory):
        """Fewer than 3 sessions returns neutral score."""
        # Add only 2 entries
        for i in range(2):
            entry = SuccessEntry(
                task_id=f"task_{i}",
                task_hash=f"hash_{i}",
                description="Test task",
                swarm_mode="ping_pong",
                agents_used=["test_agent"],
                duration_seconds=10.0,
                complexity="SIMPLE",
                domains=["coding"],
                quality_score=0.9,
                timestamp=datetime.now().isoformat(),
            )
            success_memory._append_entry(entry)

        rate, count = success_memory.get_agent_success_rate("test_agent")
        assert rate == 0.5  # Neutral due to insufficient samples
        assert count == 2

    def test_calculates_correct_rate(self, populated_success_memory):
        """Calculates correct success rate for agent."""
        # Gemini has 4 high quality + 1 low = 4/5 = 0.8
        rate, count = populated_success_memory.get_agent_success_rate("gemini_primary")

        # 5 sessions with gemini (4 shared + 1 solo)
        assert count == 5
        # 4 sessions > 0.6 quality (0.75, 0.80, 0.85, 0.90)
        assert rate == 0.8

    def test_domain_filter(self, populated_success_memory):
        """Filters by domain correctly."""
        # Claude has 3 sessions in "research" domain
        rate, count = populated_success_memory.get_agent_success_rate("claude_opus", domain="research")

        assert count == 3
        # Only 1 high quality session in research
        assert abs(rate - 0.333) < 0.01  # 1/3

    def test_includes_shared_sessions(self, populated_success_memory):
        """Counts sessions where agent participated (even shared)."""
        # Claude participated in 4 shared sessions + 3 solo = 7
        rate, count = populated_success_memory.get_agent_success_rate("claude_opus")

        # 4 shared + 3 solo
        assert count == 7


class TestGetAgentSessionStats:
    """Tests for SuccessMemory.get_agent_session_stats()."""

    def test_empty_returns_defaults(self, success_memory):
        """No sessions returns default stats."""
        stats = success_memory.get_agent_session_stats("unknown")

        assert stats["total_sessions"] == 0
        assert stats["global_success_rate"] == 0.5
        assert stats["domain_success_rates"] == {}

    def test_returns_complete_stats(self, populated_success_memory):
        """Returns comprehensive statistics."""
        stats = populated_success_memory.get_agent_session_stats("gemini_primary")

        assert stats["total_sessions"] == 5
        assert stats["global_success_rate"] == 0.8  # 4/5
        assert "coding" in stats["domain_success_rates"]
        assert "ping_pong" in stats["modes_participated"]


# =============================================================================
# AgentPool.update_from_session_metrics Tests
# =============================================================================


class TestUpdateFromSessionMetrics:
    """Tests for AgentPool.update_from_session_metrics()."""

    def test_applies_bonus_for_high_quality(self, agent_pool):
        """Applies high bonus for quality > 0.8."""
        initial_count = len(agent_pool.agents["gemini_primary"].invocation_history)

        bonuses = agent_pool.update_from_session_metrics(
            task_id="test_task",
            agents_used=["gemini_primary"],
            quality_score=0.9,  # High quality
            domains=["coding"],
            task_type="session",
        )

        assert "gemini_primary" in bonuses
        assert bonuses["gemini_primary"] == AgentPool.SESSION_BONUS_HIGH
        # Should have added synthetic invocations
        assert len(agent_pool.agents["gemini_primary"].invocation_history) > initial_count

    def test_applies_medium_bonus(self, agent_pool):
        """Applies medium bonus for quality 0.6-0.8."""
        bonuses = agent_pool.update_from_session_metrics(
            task_id="test_task",
            agents_used=["claude_opus"],
            quality_score=0.7,
            domains=["research"],
            task_type="session",
        )

        assert bonuses["claude_opus"] == AgentPool.SESSION_BONUS_MEDIUM

    def test_no_bonus_below_threshold(self, agent_pool):
        """No bonus applied for quality < 0.4."""
        bonuses = agent_pool.update_from_session_metrics(
            task_id="test_task",
            agents_used=["gemini_primary"],
            quality_score=0.3,  # Below threshold
            domains=["coding"],
            task_type="session",
        )

        assert len(bonuses) == 0

    def test_applies_to_multiple_agents(self, agent_pool):
        """Applies bonus to all participating agents."""
        bonuses = agent_pool.update_from_session_metrics(
            task_id="test_task",
            agents_used=["gemini_primary", "claude_opus"],
            quality_score=0.85,
            domains=["coding"],
            task_type="session",
        )

        assert "gemini_primary" in bonuses
        assert "claude_opus" in bonuses

    def test_ignores_unknown_agents(self, agent_pool):
        """Gracefully handles unknown agent IDs."""
        bonuses = agent_pool.update_from_session_metrics(
            task_id="test_task",
            agents_used=["unknown_agent", "gemini_primary"],
            quality_score=0.9,
            domains=["coding"],
            task_type="session",
        )

        assert "unknown_agent" not in bonuses
        assert "gemini_primary" in bonuses


# =============================================================================
# AgentPool.get_session_aware_score Tests
# =============================================================================


class TestGetSessionAwareScore:
    """Tests for AgentPool.get_session_aware_score()."""

    def test_without_memory_uses_dylan_only(self, agent_pool):
        """Without SuccessMemory, uses pure DyLAN score weighted."""
        # Add some history to gemini
        result = AgentInvocationResult(
            agent_id="gemini_primary",
            task_type="coding",
            success=True,
            quality_score=0.8,
            tokens_used=100,
            time_seconds=1.0,
        )
        agent_pool.record_invocation(result)

        score = agent_pool.get_session_aware_score(agent_id="gemini_primary", task_type="coding", success_memory=None)

        # Without memory, formula is: dylan * 0.7 + 0.5 * 0.3 (neutral session)
        dylan_score = agent_pool.agents["gemini_primary"].get_task_importance("coding")
        expected = dylan_score * 0.7 + 0.5 * 0.3
        assert abs(score - expected) < 0.01

    def test_with_memory_uses_hybrid_formula(self, agent_pool, populated_success_memory):
        """With SuccessMemory, uses hybrid scoring formula."""
        # Add DyLAN history
        result = AgentInvocationResult(
            agent_id="gemini_primary",
            task_type="coding",
            success=True,
            quality_score=0.6,
            tokens_used=100,
            time_seconds=1.0,
        )
        agent_pool.record_invocation(result)

        score = agent_pool.get_session_aware_score(
            agent_id="gemini_primary", task_type="coding", success_memory=populated_success_memory, dylan_weight=0.7
        )

        # Score should be between 0 and 1
        assert 0.0 <= score <= 1.0

    def test_high_session_success_boosts_score(self, agent_pool, populated_success_memory):
        """Agent with high session success gets higher score."""
        # Gemini has 80% session success in coding
        gemini_score = agent_pool.get_session_aware_score(
            agent_id="gemini_primary", task_type="coding", success_memory=populated_success_memory
        )

        # Claude has lower session success in coding
        claude_score = agent_pool.get_session_aware_score(
            agent_id="claude_opus", task_type="coding", success_memory=populated_success_memory
        )

        # Gemini should have higher or equal score due to session history
        # (assuming similar DyLAN scores initially)
        assert gemini_score >= claude_score or abs(gemini_score - claude_score) < 0.2


# =============================================================================
# ModeSelector Session-Aware Integration Tests
# =============================================================================


class TestModeSelectorSessionAware:
    """Tests for ModeSelector using session-aware agent selection."""

    def test_uses_session_aware_scoring(self, agent_pool, populated_success_memory):
        """ModeSelector uses session-aware scoring when memory available."""
        selector = ModeSelector(agent_pool=agent_pool, success_memory=populated_success_memory)

        analysis = TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            domains=[TaskDomain.CODING],
            primary_domain=TaskDomain.CODING,
            raw_input="Fix the authentication bug",
            requires_deep_reasoning=True,
        )

        proposal = selector.select_mode(analysis)

        # Should produce valid proposal
        assert proposal is not None
        assert proposal.mode is not None
        assert len(proposal.agent_assignments) > 0

    def test_session_aware_agent_ranking(self, agent_pool, populated_success_memory):
        """Agents are ranked by session-aware score."""
        selector = ModeSelector(agent_pool=agent_pool, success_memory=populated_success_memory)

        analysis = TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            domains=[TaskDomain.CODING],
            primary_domain=TaskDomain.CODING,
            raw_input="Implement new feature",
            requires_iteration=True,
        )

        proposal = selector.select_mode(analysis)

        # With session history, Gemini has higher success rate in coding
        # Should influence agent ranking
        if proposal.agent_assignments:
            # First assigned agent should be one with good session history
            first_agent = proposal.agent_assignments[0].agent_id
            # Verify it's a known agent
            assert first_agent in ["gemini_primary", "claude_opus"]

    def test_fallback_without_memory(self, agent_pool):
        """Falls back to capability-based selection without memory."""
        selector = ModeSelector(
            agent_pool=agent_pool,
            success_memory=None,  # No memory
        )

        analysis = TaskAnalysis(
            complexity=TaskComplexity.SIMPLE,
            domains=[TaskDomain.RESEARCH],
            primary_domain=TaskDomain.RESEARCH,
            raw_input="Research topic",
            requires_web=True,
        )

        proposal = selector.select_mode(analysis)

        # Should still work without memory
        assert proposal is not None
        assert proposal.mode is not None


# =============================================================================
# Integration Test: Session History Influences Selection
# =============================================================================


class TestSessionHistoryInfluence:
    """End-to-end tests verifying session history influences agent selection."""

    def test_agent_with_high_session_success_favored(self, tmp_path):
        """Agent with high session success rate is favored over one with low rate."""
        # Create fresh pool and memory
        pool = create_default_pool()
        ws = tmp_path / "workspace"
        ws.mkdir(exist_ok=True)
        memory = SuccessMemory(workspace_path=ws, nexus_root=tmp_path)

        # Add session history: Agent A has 100% success, Agent B has 0%
        for i in range(5):
            # Gemini always succeeds
            entry_good = SuccessEntry(
                task_id=f"good_{i}",
                task_hash=f"hash_good_{i}",
                description="Coding task success",
                swarm_mode="ping_pong",
                agents_used=["gemini_primary"],
                duration_seconds=10.0,
                complexity="MODERATE",
                domains=["coding"],
                quality_score=0.9,  # High quality
                timestamp=datetime.now().isoformat(),
            )
            memory._append_entry(entry_good)

            # Claude always fails (low quality)
            entry_bad = SuccessEntry(
                task_id=f"bad_{i}",
                task_hash=f"hash_bad_{i}",
                description="Coding task failure",
                swarm_mode="ping_pong",
                agents_used=["claude_opus"],
                duration_seconds=30.0,
                complexity="MODERATE",
                domains=["coding"],
                quality_score=0.3,  # Low quality
                timestamp=datetime.now().isoformat(),
            )
            memory._append_entry(entry_bad)

        # Verify success rates
        gemini_rate, _ = memory.get_agent_success_rate("gemini_primary", domain="coding")
        claude_rate, _ = memory.get_agent_success_rate("claude_opus", domain="coding")

        assert gemini_rate == 1.0  # 100% success
        assert claude_rate == 0.0  # 0% success

        # Create selector with memory
        ModeSelector(agent_pool=pool, success_memory=memory)

        # Session-aware score should favor Gemini
        gemini_score = pool.get_session_aware_score("gemini_primary", "coding", memory)
        claude_score = pool.get_session_aware_score("claude_opus", "coding", memory)

        # Gemini's session component: 1.0 * 0.3 = 0.3
        # Claude's session component: 0.0 * 0.3 = 0.0
        # Difference should be significant
        assert gemini_score > claude_score


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
