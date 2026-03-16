"""
Tests for V12.4 Auto-Specializer - Data-driven agent spawning.

Validates:
- SpecializationConfig defaults and customization
- DomainProfile metrics (success rate, avg quality)
- SpecializationProposal creation and serialization
- Domain profiling from SuccessMemory entries
- Qualification checks (threshold, min tasks, quality)
- Specialist count tracking
- Cooldown enforcement
- Proposal lifecycle (create, accept, reject, list)
- Domain readiness assessment
- Module exports
"""

from core.intelligence.evolution.auto_specializer import (
    AutoSpecializer,
    DomainProfile,
    SpecializationConfig,
    SpecializationProposal,
)
from core.intelligence.swarm.agent_metrics import AgentPool, AgentProfile

# =============================================================================
# Fixtures
# =============================================================================


class FakeSuccessEntry:
    """Minimal success entry for testing."""

    def __init__(self, domains, quality_score=0.8, swarm_mode="parallel", agents_used=None, duration_seconds=5.0):
        self.domains = domains
        self.quality_score = quality_score
        self.swarm_mode = swarm_mode
        self.agents_used = agents_used or ["gemini_primary"]
        self.duration_seconds = duration_seconds


class FakeSuccessMemory:
    """Minimal success memory for testing."""

    def __init__(self, entries=None):
        self._entries = entries or []

    def get_all(self):
        return self._entries


def _make_pool() -> AgentPool:
    """Create a standard test pool."""
    pool = AgentPool()
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


def _make_domain_entries(domain, count=15, quality=0.85):
    """Generate fake success entries for a domain."""
    return [
        FakeSuccessEntry(
            domains=[domain],
            quality_score=quality,
            agents_used=["gemini_primary", "claude_opus"],
        )
        for _ in range(count)
    ]


# =============================================================================
# SpecializationConfig Tests
# =============================================================================


class TestSpecializationConfig:
    """Test configuration defaults."""

    def test_default_values(self):
        cfg = SpecializationConfig()
        assert cfg.success_threshold == 0.85
        assert cfg.min_domain_tasks == 10
        assert cfg.min_quality_score == 0.7
        assert cfg.max_specialists_per_domain == 2
        assert cfg.cooldown_hours == 24
        assert cfg.excluded_domains == []

    def test_custom_values(self):
        cfg = SpecializationConfig(
            success_threshold=0.9,
            min_domain_tasks=20,
            excluded_domains=["general"],
        )
        assert cfg.success_threshold == 0.9
        assert cfg.min_domain_tasks == 20
        assert "general" in cfg.excluded_domains


# =============================================================================
# DomainProfile Tests
# =============================================================================


class TestDomainProfile:
    """Test domain profile metrics."""

    def test_empty_profile(self):
        p = DomainProfile(domain="coding")
        assert p.success_rate == 0.0
        assert p.avg_quality == 0.0
        assert p.task_count == 0

    def test_profile_metrics(self):
        p = DomainProfile(
            domain="coding",
            task_count=10,
            success_count=8,
            total_quality=7.5,
        )
        assert p.success_rate == 0.8
        assert p.avg_quality == 0.75

    def test_to_dict(self):
        p = DomainProfile(
            domain="research",
            task_count=5,
            success_count=4,
            total_quality=3.5,
            agents_involved=["agent_a"],
        )
        d = p.to_dict()
        assert d["domain"] == "research"
        assert d["task_count"] == 5
        assert d["success_rate"] == 0.8
        assert d["avg_quality"] == 0.7
        assert "agent_a" in d["agents_involved"]


# =============================================================================
# SpecializationProposal Tests
# =============================================================================


class TestSpecializationProposal:
    """Test proposal representation."""

    def test_creation(self):
        p = SpecializationProposal(
            proposal_id="abc123",
            domain="coding",
            agent_name="coding_specialist",
            capabilities=["coding", "debugging"],
            reason="High success rate in coding",
            domain_profile=DomainProfile(domain="coding"),
        )
        assert p.proposal_id == "abc123"
        assert p.domain == "coding"
        assert p.status == "pending"
        assert p.created_at != ""

    def test_to_dict(self):
        p = SpecializationProposal(
            proposal_id="test",
            domain="research",
            agent_name="research_specialist",
            capabilities=["research"],
            reason="Qualifies",
            domain_profile=DomainProfile(domain="research"),
            suggested_model="gemini-3-pro",
        )
        d = p.to_dict()
        assert d["proposal_id"] == "test"
        assert d["domain"] == "research"
        assert d["suggested_model"] == "gemini-3-pro"
        assert d["status"] == "pending"
        assert "domain_profile" in d


# =============================================================================
# AutoSpecializer - Domain Profiling Tests
# =============================================================================


class TestDomainProfiling:
    """Test domain profile building from SuccessMemory."""

    def test_no_memory(self):
        pool = _make_pool()
        specializer = AutoSpecializer(pool, success_memory=None)
        proposals = specializer.evaluate()
        assert proposals == []

    def test_empty_memory(self):
        pool = _make_pool()
        memory = FakeSuccessMemory(entries=[])
        specializer = AutoSpecializer(pool, memory)
        proposals = specializer.evaluate()
        assert proposals == []

    def test_builds_profiles(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        readiness = specializer.get_domain_readiness()

        assert "coding" in readiness
        profile = readiness["coding"]["profile"]
        assert profile["task_count"] == 15
        assert profile["success_rate"] > 0.8

    def test_multiple_domains(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9) + _make_domain_entries(
            "research", count=8, quality=0.7
        )
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        readiness = specializer.get_domain_readiness()

        assert "coding" in readiness
        assert "research" in readiness

    def test_multi_domain_entry(self):
        """Entry with multiple domains should count for each."""
        entries = [FakeSuccessEntry(domains=["coding", "research"], quality_score=0.9) for _ in range(15)]
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        readiness = specializer.get_domain_readiness()

        assert "coding" in readiness
        assert "research" in readiness
        assert readiness["coding"]["profile"]["task_count"] == 15
        assert readiness["research"]["profile"]["task_count"] == 15


# =============================================================================
# AutoSpecializer - Qualification Tests
# =============================================================================


class TestQualification:
    """Test qualification criteria."""

    def test_qualifies_above_threshold(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)

        proposals = specializer.evaluate()
        assert len(proposals) >= 1
        assert proposals[0].domain == "coding"

    def test_below_task_threshold(self):
        """Too few tasks should not qualify."""
        entries = _make_domain_entries("coding", count=5, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)

        proposals = specializer.evaluate()
        assert len(proposals) == 0

    def test_below_success_threshold(self):
        """Low success rate should not qualify."""
        entries = _make_domain_entries("coding", count=15, quality=0.4)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)

        proposals = specializer.evaluate()
        assert len(proposals) == 0

    def test_below_quality_threshold(self):
        """Quality below min should not qualify."""
        entries = _make_domain_entries("coding", count=15, quality=0.65)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        config = SpecializationConfig(min_quality_score=0.7)
        specializer = AutoSpecializer(pool, memory, config=config)

        proposals = specializer.evaluate()
        assert len(proposals) == 0

    def test_excluded_domain(self):
        """Excluded domains should not generate proposals."""
        entries = _make_domain_entries("general", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        config = SpecializationConfig(excluded_domains=["general"])
        specializer = AutoSpecializer(pool, memory, config=config)

        proposals = specializer.evaluate()
        assert len(proposals) == 0


# =============================================================================
# AutoSpecializer - Specialist Count Tests
# =============================================================================


class TestSpecialistLimit:
    """Test specialist agent counting and limits."""

    def test_no_existing_specialists(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)

        proposals = specializer.evaluate()
        assert len(proposals) >= 1

    def test_at_specialist_limit(self):
        """Should not propose when max specialists already exist."""
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()

        # Add existing specialists
        pool.register(
            AgentProfile(
                agent_id="coding_expert_1",
                provider="spawned",
                model="custom",
                capabilities=["coding"],
            )
        )
        pool.register(
            AgentProfile(
                agent_id="coding_expert_2",
                provider="spawned",
                model="custom",
                capabilities=["coding"],
            )
        )

        config = SpecializationConfig(max_specialists_per_domain=2)
        specializer = AutoSpecializer(pool, memory, config=config)

        proposals = specializer.evaluate()
        coding_proposals = [p for p in proposals if p.domain == "coding"]
        assert len(coding_proposals) == 0

    def test_inactive_specialists_not_counted(self):
        """Inactive specialists should not block new proposals."""
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()

        # Add inactive specialist
        profile = AgentProfile(
            agent_id="old_coding",
            provider="spawned",
            model="custom",
            capabilities=["coding"],
        )
        profile.is_active = False
        pool.register(profile)

        config = SpecializationConfig(max_specialists_per_domain=1)
        specializer = AutoSpecializer(pool, memory, config=config)

        proposals = specializer.evaluate()
        coding_proposals = [p for p in proposals if p.domain == "coding"]
        assert len(coding_proposals) >= 1


# =============================================================================
# AutoSpecializer - Cooldown Tests
# =============================================================================


class TestCooldown:
    """Test cooldown between proposals."""

    def test_cooldown_blocks_repeat(self):
        """Second evaluation within cooldown should not produce proposal."""
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        config = SpecializationConfig(cooldown_hours=24)
        specializer = AutoSpecializer(pool, memory, config=config)

        first = specializer.evaluate()
        assert len(first) >= 1

        second = specializer.evaluate()
        coding_second = [p for p in second if p.domain == "coding"]
        assert len(coding_second) == 0

    def test_no_cooldown_if_zero(self):
        """Cooldown of 0 should allow immediate re-proposal."""
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        config = SpecializationConfig(cooldown_hours=0)
        specializer = AutoSpecializer(pool, memory, config=config)

        first = specializer.evaluate()
        assert len(first) >= 1

        second = specializer.evaluate()
        # Won't generate because same proposal_id pattern dedup is not done,
        # but cooldown is not blocking
        # Actually the proposal is already in the list so evaluate skips...
        # Let me check: evaluate generates new proposals regardless of existing ones
        # The cooldown check uses _last_proposal_time which was set in first call
        # With cooldown=0, it should pass the check
        coding_second = [p for p in second if p.domain == "coding"]
        assert len(coding_second) >= 1


# =============================================================================
# AutoSpecializer - Proposal Management Tests
# =============================================================================


class TestProposalManagement:
    """Test proposal lifecycle."""

    def _make_specializer_with_proposal(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        proposals = specializer.evaluate()
        return specializer, proposals

    def test_accept_proposal(self):
        specializer, proposals = self._make_specializer_with_proposal()
        pid = proposals[0].proposal_id
        assert specializer.accept_proposal(pid) is True
        assert specializer.get_proposal(pid).status == "accepted"

    def test_reject_proposal(self):
        specializer, proposals = self._make_specializer_with_proposal()
        pid = proposals[0].proposal_id
        assert specializer.reject_proposal(pid) is True
        assert specializer.get_proposal(pid).status == "rejected"

    def test_accept_nonexistent(self):
        specializer, _ = self._make_specializer_with_proposal()
        assert specializer.accept_proposal("nonexistent") is False

    def test_reject_nonexistent(self):
        specializer, _ = self._make_specializer_with_proposal()
        assert specializer.reject_proposal("nonexistent") is False

    def test_double_accept(self):
        """Cannot accept an already accepted proposal."""
        specializer, proposals = self._make_specializer_with_proposal()
        pid = proposals[0].proposal_id
        specializer.accept_proposal(pid)
        assert specializer.accept_proposal(pid) is False

    def test_list_proposals(self):
        specializer, proposals = self._make_specializer_with_proposal()
        all_proposals = specializer.list_proposals()
        assert len(all_proposals) >= 1

    def test_list_proposals_by_status(self):
        specializer, proposals = self._make_specializer_with_proposal()
        pid = proposals[0].proposal_id
        specializer.accept_proposal(pid)

        specializer.list_proposals(status="pending")
        accepted = specializer.list_proposals(status="accepted")
        assert all(p.status == "accepted" for p in accepted)

    def test_get_proposal(self):
        specializer, proposals = self._make_specializer_with_proposal()
        pid = proposals[0].proposal_id
        p = specializer.get_proposal(pid)
        assert p is not None
        assert p.proposal_id == pid

    def test_get_proposal_not_found(self):
        specializer, _ = self._make_specializer_with_proposal()
        assert specializer.get_proposal("nope") is None


# =============================================================================
# AutoSpecializer - Proposal Content Tests
# =============================================================================


class TestProposalContent:
    """Test proposal metadata and content."""

    def test_proposal_has_agent_name(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        proposals = specializer.evaluate()

        assert proposals[0].agent_name == "coding_specialist"

    def test_proposal_has_capabilities(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        proposals = specializer.evaluate()

        assert "coding" in proposals[0].capabilities

    def test_proposal_has_reason(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        proposals = specializer.evaluate()

        assert "85%" in proposals[0].reason or "success rate" in proposals[0].reason

    def test_proposal_has_model_suggestion(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        proposals = specializer.evaluate()

        assert proposals[0].suggested_model != ""

    def test_coding_domain_extra_capabilities(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        proposals = specializer.evaluate()

        # Coding should get debugging and testing capabilities
        caps = proposals[0].capabilities
        assert "debugging" in caps or "testing" in caps


# =============================================================================
# AutoSpecializer - State Export Tests
# =============================================================================


class TestStateExport:
    """Test state serialization."""

    def test_to_dict_empty(self):
        pool = _make_pool()
        specializer = AutoSpecializer(pool)
        d = specializer.to_dict()
        assert d["proposal_count"] == 0
        assert "config" in d

    def test_to_dict_with_proposals(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        specializer.evaluate()
        d = specializer.to_dict()

        assert d["proposal_count"] >= 1
        assert len(d["proposals"]) >= 1

    def test_domain_readiness(self):
        entries = _make_domain_entries("coding", count=15, quality=0.9)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        readiness = specializer.get_domain_readiness()

        assert "coding" in readiness
        r = readiness["coding"]
        assert r["qualifies"] is True
        assert r["tasks_needed"] == 0
        assert r["success_gap"] == 0.0

    def test_domain_readiness_not_ready(self):
        entries = _make_domain_entries("coding", count=5, quality=0.5)
        memory = FakeSuccessMemory(entries)
        pool = _make_pool()
        specializer = AutoSpecializer(pool, memory)
        readiness = specializer.get_domain_readiness()

        assert "coding" in readiness
        r = readiness["coding"]
        assert r["qualifies"] is False
        assert r["tasks_needed"] == 5  # needs 10, has 5


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test that auto-specializer types are importable."""

    def test_from_evolution_package(self):
        from core.intelligence.evolution import (
            AutoSpecializer,
            SpecializationConfig,
        )

        assert AutoSpecializer is not None
        assert SpecializationConfig is not None

    def test_from_module(self):
        from core.intelligence.evolution.auto_specializer import (
            AutoSpecializer,
            DomainProfile,
            SpecializationConfig,
            SpecializationProposal,
        )

        assert all([AutoSpecializer, SpecializationConfig, SpecializationProposal, DomainProfile])
