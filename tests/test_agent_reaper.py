"""
Tests for V12.4 Agent Reaper - DyLAN-based lifecycle management.

Validates:
- ReaperConfig defaults and customization
- Agent scanning (healthy, candidate, protected, exempt)
- Archival criteria (importance, success rate, inactivity)
- Archive execution (deactivate, file move)
- Health reporting (per-agent and pool-wide)
- Dry run mode
- Module exports
"""

from datetime import UTC, datetime, timedelta

from core.intelligence.evolution.agent_reaper import (
    AgentReaper,
    ArchivalCandidate,
    ArchivalResult,
    ReaperConfig,
    ReaperReport,
)
from core.intelligence.swarm.agent_metrics import AgentInvocationResult, AgentPool, AgentProfile

# =============================================================================
# Fixtures
# =============================================================================


def _make_pool(**extra_agents) -> AgentPool:
    """Create a test agent pool with standard agents."""
    pool = AgentPool()

    # Internal agents (always protected)
    pool.register(
        AgentProfile(
            agent_id="gemini_primary",
            provider="gemini",
            model="gemini-3-pro",
        )
    )
    pool.register(
        AgentProfile(
            agent_id="claude_opus",
            provider="claude",
            model="claude-opus-4-5",
        )
    )

    return pool


def _add_spawned_agent(
    pool: AgentPool,
    agent_id: str,
    invocations: int = 10,
    success_ratio: float = 0.8,
    quality: float = 0.6,
    days_ago: int = 5,
) -> AgentProfile:
    """Add a spawned agent with history to the pool."""
    profile = AgentProfile(
        agent_id=agent_id,
        provider="spawned",
        model="custom",
    )
    pool.register(profile)

    now = datetime.now(UTC)
    for i in range(invocations):
        success = (i / invocations) < success_ratio
        result = AgentInvocationResult(
            agent_id=agent_id,
            task_type="test_task",
            success=success,
            quality_score=quality if success else 0.0,
            tokens_used=100,
            time_seconds=1.0,
            timestamp=now - timedelta(days=days_ago),
        )
        profile.record_invocation(result)

    return profile


# =============================================================================
# ReaperConfig Tests
# =============================================================================


class TestReaperConfig:
    """Test configuration defaults."""

    def test_default_values(self):
        cfg = ReaperConfig()
        assert cfg.min_importance == 0.1
        assert cfg.max_inactivity_days == 30
        assert cfg.min_success_rate == 0.2
        assert cfg.min_invocations == 5
        assert cfg.protect_internal is True
        assert cfg.dry_run is False

    def test_custom_values(self):
        cfg = ReaperConfig(
            min_importance=0.3,
            max_inactivity_days=7,
            min_success_rate=0.5,
        )
        assert cfg.min_importance == 0.3
        assert cfg.max_inactivity_days == 7
        assert cfg.min_success_rate == 0.5


# =============================================================================
# Scan Tests
# =============================================================================


class TestScan:
    """Test agent scanning."""

    def test_empty_pool(self):
        pool = AgentPool()
        reaper = AgentReaper(pool)
        report = reaper.scan()
        assert report.candidate_count == 0
        assert report.total_agents == 0

    def test_internal_agents_protected(self):
        pool = _make_pool()
        reaper = AgentReaper(pool)
        report = reaper.scan()

        assert "gemini_primary" in report.protected
        assert "claude_opus" in report.protected
        assert report.candidate_count == 0

    def test_internal_protection_disabled(self):
        """When protect_internal is False, internal agents are scanned."""
        pool = _make_pool()
        config = ReaperConfig(protect_internal=False, min_invocations=0)
        reaper = AgentReaper(pool, config=config)
        report = reaper.scan()

        # Internal agents with no invocations should be exempt (min_invocations=0 means
        # they still pass since they have 0 invocations and 0 < 0 is False)
        assert "gemini_primary" not in report.protected

    def test_new_agents_exempt(self):
        """Agents with few invocations are exempt from evaluation."""
        pool = _make_pool()
        _add_spawned_agent(pool, "new_agent", invocations=2)  # Below min_invocations=5
        reaper = AgentReaper(pool)
        report = reaper.scan()

        assert "new_agent" in report.exempt

    def test_healthy_agent_passes(self):
        """Agent with good metrics should be healthy."""
        pool = _make_pool()
        _add_spawned_agent(pool, "good_agent", invocations=10, success_ratio=0.9, quality=0.8)
        reaper = AgentReaper(pool)
        report = reaper.scan()

        assert "good_agent" in report.healthy

    def test_low_importance_flagged(self):
        """Agent with low importance should be a candidate."""
        pool = _make_pool()
        _add_spawned_agent(pool, "weak_agent", invocations=10, quality=0.001, success_ratio=1.0)
        config = ReaperConfig(min_importance=0.5)
        reaper = AgentReaper(pool, config=config)
        report = reaper.scan()

        candidate_ids = [c.agent_id for c in report.candidates]
        assert "weak_agent" in candidate_ids

    def test_low_success_rate_flagged(self):
        """Agent with low success rate should be a candidate."""
        pool = _make_pool()
        _add_spawned_agent(pool, "failing_agent", invocations=10, success_ratio=0.1)
        reaper = AgentReaper(pool)
        report = reaper.scan()

        candidate_ids = [c.agent_id for c in report.candidates]
        assert "failing_agent" in candidate_ids

    def test_inactive_agent_flagged(self):
        """Agent inactive for too long should be a candidate."""
        pool = _make_pool()
        _add_spawned_agent(pool, "idle_agent", invocations=10, quality=0.8, days_ago=60)
        config = ReaperConfig(max_inactivity_days=30)
        reaper = AgentReaper(pool, config=config)
        report = reaper.scan()

        candidate_ids = [c.agent_id for c in report.candidates]
        assert "idle_agent" in candidate_ids

    def test_report_has_timestamp(self):
        pool = AgentPool()
        reaper = AgentReaper(pool)
        report = reaper.scan()
        assert report.scanned_at != ""
        datetime.fromisoformat(report.scanned_at)

    def test_report_to_dict(self):
        pool = _make_pool()
        _add_spawned_agent(pool, "test_agent", invocations=10)
        reaper = AgentReaper(pool)
        report = reaper.scan()
        d = report.to_dict()

        assert "scanned_at" in d
        assert "total_agents" in d
        assert "health_ratio" in d
        assert "candidates" in d
        assert "healthy" in d


# =============================================================================
# Reap Tests
# =============================================================================


class TestReap:
    """Test agent archival."""

    def test_reap_deactivates_agent(self):
        """Archived agents should be deactivated in pool."""
        pool = _make_pool()
        _add_spawned_agent(pool, "doomed", invocations=10, success_ratio=0.05)
        reaper = AgentReaper(pool)

        results = reaper.reap()

        assert len(results) >= 1
        archived_ids = [r.agent_id for r in results if r.success]
        assert "doomed" in archived_ids
        assert pool.agents["doomed"].is_active is False

    def test_dry_run_no_changes(self):
        """Dry run should not deactivate agents."""
        pool = _make_pool()
        _add_spawned_agent(pool, "safe_agent", invocations=10, success_ratio=0.05)
        config = ReaperConfig(dry_run=True)
        reaper = AgentReaper(pool, config=config)

        results = reaper.reap()

        assert len(results) >= 1
        assert all(not r.success for r in results)
        assert pool.agents["safe_agent"].is_active is True

    def test_reap_moves_files(self, tmp_path):
        """Should move agent files to archive."""
        # Create agent file
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        agent_file = agents_dir / "old_agent.md"
        agent_file.write_text("# Old Agent\nThis agent is outdated.")

        pool = _make_pool()
        _add_spawned_agent(pool, "old_agent", invocations=10, success_ratio=0.05)
        reaper = AgentReaper(pool, workspace_path=tmp_path)

        results = reaper.reap()

        archived = [r for r in results if r.agent_id == "old_agent"]
        assert len(archived) == 1
        assert archived[0].success
        assert not agent_file.exists()
        assert (tmp_path / "agents" / ".archive" / "old_agent.md").exists()

    def test_reap_without_file(self):
        """Should succeed even without agent file on disk."""
        pool = _make_pool()
        _add_spawned_agent(pool, "no_file_agent", invocations=10, success_ratio=0.05)
        reaper = AgentReaper(pool)

        results = reaper.reap()

        archived = [r for r in results if r.agent_id == "no_file_agent"]
        assert len(archived) == 1
        assert archived[0].success

    def test_reap_with_provided_report(self):
        """Should accept pre-scanned report."""
        pool = _make_pool()
        _add_spawned_agent(pool, "target", invocations=10, success_ratio=0.05)
        reaper = AgentReaper(pool)

        report = reaper.scan()
        results = reaper.reap(report=report)

        assert len(results) >= 1


# =============================================================================
# Health Reporting Tests
# =============================================================================


class TestHealthReporting:
    """Test agent health reporting."""

    def test_agent_health_not_found(self):
        pool = AgentPool()
        reaper = AgentReaper(pool)
        health = reaper.get_agent_health("nonexistent")
        assert health["status"] == "not_found"

    def test_agent_health_new(self):
        pool = _make_pool()
        pool.register(AgentProfile(agent_id="brand_new", provider="spawned", model="m"))
        reaper = AgentReaper(pool)
        health = reaper.get_agent_health("brand_new")
        assert health["status"] == "new"

    def test_agent_health_healthy(self):
        pool = _make_pool()
        _add_spawned_agent(pool, "strong", invocations=10, quality=0.8, success_ratio=0.9)
        reaper = AgentReaper(pool)
        health = reaper.get_agent_health("strong")
        assert health["status"] == "healthy"
        assert health["warnings"] == []

    def test_agent_health_critical(self):
        pool = _make_pool()
        _add_spawned_agent(pool, "dying", invocations=10, quality=0.001, success_ratio=0.1)
        config = ReaperConfig(min_importance=0.5)
        reaper = AgentReaper(pool, config=config)
        health = reaper.get_agent_health("dying")
        assert health["status"] == "critical"
        assert len(health["warnings"]) > 0

    def test_pool_health(self):
        pool = _make_pool()
        _add_spawned_agent(pool, "agent_a", invocations=10, quality=0.8, success_ratio=0.9)
        reaper = AgentReaper(pool)
        health = reaper.get_pool_health()

        assert "total_agents" in health
        assert "health_ratio" in health
        assert "status_distribution" in health
        assert "agents" in health

    def test_health_ratio_calculation(self):
        pool = _make_pool()
        _add_spawned_agent(pool, "good1", invocations=10, quality=0.8)
        _add_spawned_agent(pool, "good2", invocations=10, quality=0.8)
        reaper = AgentReaper(pool)
        report = reaper.scan()

        # 2 healthy spawned + 2 protected internal = all good
        assert report.health_ratio > 0


# =============================================================================
# ArchivalCandidate Tests
# =============================================================================


class TestArchivalCandidate:
    """Test ArchivalCandidate dataclass."""

    def test_creation(self):
        c = ArchivalCandidate(
            agent_id="test",
            reason="Low score",
            importance_score=0.05,
            success_rate=0.5,
            invocation_count=10,
        )
        assert c.agent_id == "test"
        assert c.reason == "Low score"
        assert c.importance_score == 0.05


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that reaper types are importable."""

    def test_from_evolution_package(self):
        from core.intelligence.evolution import AgentReaper, ArchivalCandidate, ReaperConfig, ReaperReport

        assert AgentReaper is not None
        assert ReaperConfig is not None
        assert ReaperReport is not None
        assert ArchivalCandidate is not None

    def test_from_reaper_module(self):
        from core.intelligence.evolution.agent_reaper import (
            AgentReaper,
            ArchivalCandidate,
            ReaperConfig,
        )

        assert all([AgentReaper, ReaperConfig, ReaperReport, ArchivalCandidate, ArchivalResult])
