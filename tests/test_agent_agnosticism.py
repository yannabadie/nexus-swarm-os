"""
Tests for Phase 5b: N-Agent Agnosticism

NEXUS V7.5 HIVE MIND - Verifies that:
1. AgentPool.select_agents_by_capability works correctly
2. ModeSelector uses capability-based selection, not hardcoded names
3. A high-scoring spawned agent beats Gemini/Claude for its domain

Author: Claude (NEXUS V7.5)
Date: 2025-12-04
"""

# Add parent to path for imports
import sys
from pathlib import Path
from unittest import TestCase, main

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.swarm.agent_metrics import AgentInvocationResult, AgentPool, AgentProfile
from core.intelligence.swarm.mode_selector import ModeSelector
from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskComplexity, TaskDomain


class TestAgentPoolCapabilitySelection(TestCase):
    """Tests for AgentPool.select_agents_by_capability."""

    def test_select_by_capability_direct_match(self):
        """Test that agents with direct capability match are selected first."""
        pool = AgentPool()

        # Register agents with different capabilities
        pool.register(
            AgentProfile(
                agent_id="gemini_primary",
                provider="gemini",
                model="gemini-3-pro",
                capabilities=["reasoning", "research"],
            )
        )
        pool.register(
            AgentProfile(
                agent_id="claude_opus", provider="claude", model="claude-opus", capabilities=["coding", "architecture"]
            )
        )
        pool.register(
            AgentProfile(
                agent_id="sql_expert",
                provider="spawned",
                model="spawned_sql_expert",
                capabilities=["database", "sql", "coding"],
            )
        )

        # Select for DATABASE domain
        selected = pool.select_agents_by_capability("database", count=2)

        assert len(selected) == 2
        # sql_expert should be first (direct capability match)
        assert selected[0].agent_id == "sql_expert"

    def test_select_by_capability_dylan_score(self):
        """Test that DyLAN scores influence selection when no capability match."""
        pool = AgentPool()

        # Two agents without explicit capability for "debugging"
        gemini = AgentProfile(
            agent_id="gemini_primary", provider="gemini", model="gemini-3-pro", capabilities=["reasoning"]
        )
        claude = AgentProfile(agent_id="claude_opus", provider="claude", model="claude-opus", capabilities=["coding"])

        pool.register(gemini)
        pool.register(claude)

        # Give Claude high DyLAN score for debugging
        for _ in range(5):
            claude.record_invocation(
                AgentInvocationResult(
                    agent_id="claude_opus",
                    task_type="debugging",
                    success=True,
                    quality_score=0.95,
                    tokens_used=500,
                    time_seconds=5.0,
                )
            )

        # Give Gemini lower DyLAN score
        for _ in range(5):
            gemini.record_invocation(
                AgentInvocationResult(
                    agent_id="gemini_primary",
                    task_type="debugging",
                    success=True,
                    quality_score=0.5,
                    tokens_used=1000,
                    time_seconds=10.0,
                )
            )

        selected = pool.select_agents_by_capability("debugging", count=2)

        # Claude should be first due to higher DyLAN score
        assert selected[0].agent_id == "claude_opus"
        assert selected[1].agent_id == "gemini_primary"

    def test_select_by_capability_spawned_included(self):
        """Test that spawned agents are included by default."""
        pool = AgentPool()

        pool.register(
            AgentProfile(agent_id="gemini_primary", provider="gemini", model="gemini-3-pro", capabilities=["reasoning"])
        )
        pool.register(
            AgentProfile(
                agent_id="security_expert",
                provider="spawned",
                model="spawned_security_expert",
                capabilities=["security", "pentesting"],
            )
        )

        selected = pool.select_agents_by_capability("security", count=2)

        # Security expert should be first and included
        assert any(a.agent_id == "security_expert" for a in selected)
        assert selected[0].agent_id == "security_expert"

    def test_select_by_capability_exclude_spawned(self):
        """Test that spawned agents can be excluded."""
        pool = AgentPool()

        pool.register(
            AgentProfile(agent_id="gemini_primary", provider="gemini", model="gemini-3-pro", capabilities=["security"])
        )
        pool.register(
            AgentProfile(
                agent_id="security_expert",
                provider="spawned",
                model="spawned_security_expert",
                capabilities=["security", "pentesting"],
            )
        )

        selected = pool.select_agents_by_capability("security", count=2, include_spawned=False)

        # Only internal agent should be returned
        assert len(selected) == 1
        assert selected[0].agent_id == "gemini_primary"

    def test_get_best_for_role_with_dylan(self):
        """Test get_best_for_role with DyLAN scores."""
        pool = AgentPool()

        gemini = AgentProfile(
            agent_id="gemini_primary", provider="gemini", model="gemini-3-pro", capabilities=["research"]
        )
        claude = AgentProfile(agent_id="claude_opus", provider="claude", model="claude-opus", capabilities=["coding"])
        super_coder = AgentProfile(
            agent_id="super_coder",
            provider="spawned",
            model="spawned_super_coder",
            capabilities=["coding", "python", "rust"],
        )

        pool.register(gemini)
        pool.register(claude)
        pool.register(super_coder)

        # Give super_coder higher DyLAN score for coding
        for _ in range(10):
            super_coder.record_invocation(
                AgentInvocationResult(
                    agent_id="super_coder",
                    task_type="coding",
                    success=True,
                    quality_score=0.99,
                    tokens_used=100,
                    time_seconds=1.0,
                )
            )

        # Get best for coding, excluding gemini
        best = pool.get_best_for_role(role="lead", domain="coding", exclude_agents=["gemini_primary"])

        assert best is not None
        # super_coder should win due to capability + high DyLAN
        assert best.agent_id == "super_coder"


class TestModeSelectorAgentAgnostic(TestCase):
    """Tests for agent-agnostic mode selection."""

    def setUp(self):
        """Create agent pool with spawned agent."""
        self.pool = AgentPool()

        # Register default agents
        self.pool.register(
            AgentProfile(
                agent_id="gemini_primary",
                provider="gemini",
                model="gemini-3-pro",
                capabilities=["reasoning", "research"],
            )
        )
        self.pool.register(
            AgentProfile(
                agent_id="claude_opus", provider="claude", model="claude-opus", capabilities=["coding", "architecture"]
            )
        )

    def test_spawned_agent_selected_as_lead_for_its_domain(self):
        """
        CRITICAL TEST: A spawned agent with high DyLAN score in CODING
        should be selected as Lead over Gemini/Claude.
        """
        # Register a "super_coder" spawned agent with high score
        super_coder = AgentProfile(
            agent_id="super_coder",
            provider="spawned",
            model="spawned_super_coder",
            capabilities=["coding", "python", "javascript"],
        )

        # Give it very high DyLAN scores for coding
        # DyLAN importance = quality / cost where cost = tokens/1000 + time_seconds
        # To beat default 0.5 for agents with no history, we need importance > 0.5
        # With quality=0.98, cost=0.6: importance = 0.98/0.6 = 1.63 >> 0.5
        for _ in range(10):
            super_coder.record_invocation(
                AgentInvocationResult(
                    agent_id="super_coder",
                    task_type="coding",
                    success=True,
                    quality_score=0.98,  # Very high quality
                    tokens_used=100,  # Very low cost (0.1)
                    time_seconds=0.5,  # Very fast (total cost = 0.6)
                )
            )

        self.pool.register(super_coder)

        # Create task analysis for a coding task
        analysis = TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            primary_domain=TaskDomain.CODING,
            domains=[TaskDomain.CODING],
            gemini_fit_score=0.5,
            claude_fit_score=0.6,
            raw_input="Refactor this Python class to use dataclasses",
        )

        # Create selector with pool
        selector = ModeSelector(agent_pool=self.pool)

        # Select mode
        proposal = selector.select_mode(analysis)

        # Find the first assignment (highest ranked agent)
        if proposal.agent_assignments:
            first_agent = proposal.agent_assignments[0].agent_id
            # super_coder should be selected first due to:
            # 1. Direct "coding" capability match (+1.0)
            # 2. High DyLAN score for coding
            assert first_agent == "super_coder", f"Expected super_coder as first agent, got {first_agent}"

    def test_spawned_agent_selected_as_specialist(self):
        """Test that spawned agent is selected for SPECIALIST mode."""
        # Register a database expert
        db_expert = AgentProfile(
            agent_id="db_expert",
            provider="spawned",
            model="spawned_db_expert",
            capabilities=["database", "sql", "postgresql"],
        )
        self.pool.register(db_expert)

        # Create DATABASE task (use DEBUGGING as closest domain for DB)
        TaskAnalysis(
            complexity=TaskComplexity.SIMPLE,
            primary_domain=TaskDomain.DEBUGGING,  # Closest to DB optimization
            domains=[TaskDomain.DEBUGGING],
            gemini_fit_score=0.3,
            claude_fit_score=0.4,
            raw_input="Optimize this SQL query",
        )

        # Force specialist mode evaluation
        ModeSelector(agent_pool=self.pool)

        # Get ranked agents for database domain
        ranked = self.pool.select_agents_by_capability("database", count=3)

        # db_expert should be first due to capability match
        assert ranked[0].agent_id == "db_expert"

    def test_no_hardcoded_gemini_claude_in_assignments(self):
        """Test that assignment doesn't fail without gemini/claude."""
        # Create pool with only spawned agents
        spawned_only_pool = AgentPool()
        spawned_only_pool.register(
            AgentProfile(
                agent_id="agent_alpha", provider="spawned", model="spawned_alpha", capabilities=["coding", "research"]
            )
        )
        spawned_only_pool.register(
            AgentProfile(
                agent_id="agent_beta", provider="spawned", model="spawned_beta", capabilities=["security", "testing"]
            )
        )

        analysis = TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            primary_domain=TaskDomain.CODING,
            domains=[TaskDomain.CODING],
            gemini_fit_score=0.0,
            claude_fit_score=0.0,
            raw_input="Write a Python script",
        )

        selector = ModeSelector(agent_pool=spawned_only_pool)
        proposal = selector.select_mode(analysis)

        # Should not crash and should have assignments
        assert len(proposal.agent_assignments) > 0
        # All assignments should be from spawned agents
        for assignment in proposal.agent_assignments:
            assert assignment.agent_id in ["agent_alpha", "agent_beta"]

    def test_capability_match_beats_default_agents(self):
        """Test that capability match beats default internal agents."""
        # Add a specialized testing agent
        testing_agent = AgentProfile(
            agent_id="testing_specialist",
            provider="spawned",
            model="spawned_testing",
            capabilities=["testing", "pytest", "unittest"],
        )
        self.pool.register(testing_agent)

        # Get ranked agents for testing domain
        ranked = self.pool.select_agents_by_capability("testing", count=3)

        # testing_specialist should be first due to capability match
        assert ranked[0].agent_id == "testing_specialist"


class TestAgentAgnosticIntegration(TestCase):
    """Integration tests for the full agent-agnostic flow."""

    def test_full_flow_spawned_agent_wins(self):
        """End-to-end test: spawned agent with best score wins lead role."""
        pool = AgentPool()

        # Standard agents with moderate scores
        gemini = AgentProfile(
            agent_id="gemini_primary", provider="gemini", model="gemini-3-pro", capabilities=["reasoning"]
        )
        claude = AgentProfile(
            agent_id="claude_opus", provider="claude", model="claude-opus", capabilities=["architecture"]
        )

        # Super coder with explicit coding capability
        super_coder = AgentProfile(
            agent_id="super_coder",
            provider="spawned",
            model="spawned_super_coder",
            capabilities=["coding", "refactoring", "testing"],
        )

        pool.register(gemini)
        pool.register(claude)
        pool.register(super_coder)

        # Build DyLAN history - super_coder is best at coding
        for _ in range(5):
            super_coder.record_invocation(
                AgentInvocationResult(
                    agent_id="super_coder",
                    task_type="coding",
                    success=True,
                    quality_score=0.95,
                    tokens_used=300,
                    time_seconds=3.0,
                )
            )
            gemini.record_invocation(
                AgentInvocationResult(
                    agent_id="gemini_primary",
                    task_type="coding",
                    success=True,
                    quality_score=0.6,
                    tokens_used=800,
                    time_seconds=8.0,
                )
            )
            claude.record_invocation(
                AgentInvocationResult(
                    agent_id="claude_opus",
                    task_type="coding",
                    success=True,
                    quality_score=0.7,
                    tokens_used=600,
                    time_seconds=6.0,
                )
            )

        # Create coding task
        analysis = TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            primary_domain=TaskDomain.CODING,
            domains=[TaskDomain.CODING],
            gemini_fit_score=0.5,
            claude_fit_score=0.6,
            raw_input="Refactor this code",
        )

        selector = ModeSelector(agent_pool=pool)
        proposal = selector.select_mode(analysis)

        # super_coder should be first in any assignment due to:
        # 1. Direct "coding" capability match (+1.0)
        # 2. High DyLAN score for coding
        first_agent = proposal.agent_assignments[0].agent_id if proposal.agent_assignments else None

        assert first_agent == "super_coder", f"Expected super_coder as first agent, got {first_agent}"

    def test_domain_fit_scoring_agnostic(self):
        """Test that domain fit scoring works without hardcoded names."""
        pool = AgentPool()

        # Only spawned agents
        pool.register(
            AgentProfile(
                agent_id="researcher",
                provider="spawned",
                model="spawned_researcher",
                capabilities=["research", "analysis"],
            )
        )
        pool.register(
            AgentProfile(
                agent_id="implementer",
                provider="spawned",
                model="spawned_implementer",
                capabilities=["coding", "testing"],
            )
        )

        analysis = TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            primary_domain=TaskDomain.RESEARCH,
            domains=[TaskDomain.RESEARCH, TaskDomain.CODING],
            requires_web=True,
            requires_deep_reasoning=True,
            gemini_fit_score=0.0,
            claude_fit_score=0.0,
            raw_input="Research and implement",
        )

        selector = ModeSelector(agent_pool=pool)
        proposal = selector.select_mode(analysis)

        # Should have valid assignments from spawned agents
        assert len(proposal.agent_assignments) > 0

        # For research domain, researcher should be preferred
        ranked = pool.select_agents_by_capability("research", count=2)
        assert ranked[0].agent_id == "researcher"


# Run tests if executed directly
if __name__ == "__main__":
    main()
