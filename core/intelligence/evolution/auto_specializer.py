"""
Auto-Specializer - Data-driven agent spawning based on domain performance.

V12.4 COGNITIVE BOOST - Task #30

Monitors domain success rates across the agent pool and automatically
proposes specialized agent spawning when performance thresholds are met.
Implements the "85% success in domain triggers specialization" vision.

Uses:
- SuccessMemory for domain-level performance tracking
- AgentPool DyLAN scores for agent capability assessment
- Evolution system for agent creation proposals

Usage:
    from core.intelligence.evolution.auto_specializer import AutoSpecializer, SpecializationConfig

    specializer = AutoSpecializer(agent_pool, success_memory)
    proposals = specializer.evaluate()

    for proposal in proposals:
        print(f"Propose: {proposal.agent_name} for {proposal.domain}")
        if approved:
            specializer.accept_proposal(proposal)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class SpecializationConfig:
    """
    Configuration for auto-specialization triggers.

    Attributes:
        success_threshold: Minimum success rate in a domain to trigger (default 0.85)
        min_domain_tasks: Minimum tasks in a domain before evaluating (default 10)
        min_quality_score: Minimum average quality score (default 0.7)
        max_specialists_per_domain: Maximum specialist agents per domain (default 2)
        cooldown_hours: Minimum hours between proposals for same domain (default 24)
        excluded_domains: Domains to never auto-specialize
    """

    success_threshold: float = 0.85
    min_domain_tasks: int = 10
    min_quality_score: float = 0.7
    max_specialists_per_domain: int = 2
    cooldown_hours: int = 24
    excluded_domains: list[str] = field(default_factory=list)


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class DomainProfile:
    """Accumulated performance profile for a domain."""

    domain: str
    task_count: int = 0
    success_count: int = 0
    total_quality: float = 0.0
    agents_involved: list[str] = field(default_factory=list)
    modes_used: dict[str, int] = field(default_factory=dict)
    avg_duration: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.task_count if self.task_count > 0 else 0.0

    @property
    def avg_quality(self) -> float:
        return self.total_quality / self.task_count if self.task_count > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "task_count": self.task_count,
            "success_rate": round(self.success_rate, 4),
            "avg_quality": round(self.avg_quality, 4),
            "agents_involved": self.agents_involved,
            "modes_used": self.modes_used,
            "avg_duration": round(self.avg_duration, 2),
        }


@dataclass
class SpecializationProposal:
    """A proposed specialization for a domain."""

    proposal_id: str
    domain: str
    agent_name: str
    capabilities: list[str]
    reason: str
    domain_profile: DomainProfile
    suggested_model: str = ""
    created_at: str = ""
    status: str = "pending"  # pending, accepted, rejected

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "domain": self.domain,
            "agent_name": self.agent_name,
            "capabilities": self.capabilities,
            "reason": self.reason,
            "domain_profile": self.domain_profile.to_dict(),
            "suggested_model": self.suggested_model,
            "created_at": self.created_at,
            "status": self.status,
        }


# =============================================================================
# Auto-Specializer Engine
# =============================================================================


class AutoSpecializer:
    """
    Data-driven auto-specialization engine.

    Monitors domain success rates and proposes specialized agent spawning
    when performance thresholds are consistently met.

    The specializer operates in two modes:
    1. evaluate() - Analyze domains and generate proposals
    2. accept_proposal() - Mark a proposal as accepted for execution
    """

    # Suggested models per domain type
    MODEL_SUGGESTIONS: dict[str, str] = {
        "coding": "claude-sonnet-4-5-20250929",
        "research": "gemini-3-pro-preview",
        "creative": "claude-opus-4-6-20250116",
        "analysis": "gemini-3-pro-preview",
        "security": "claude-opus-4-6-20250116",
        "database": "claude-sonnet-4-5-20250929",
        "devops": "claude-sonnet-4-5-20250929",
    }

    def __init__(
        self,
        agent_pool: Any,
        success_memory: Any | None = None,
        config: SpecializationConfig | None = None,
    ):
        """
        Initialize the auto-specializer.

        Args:
            agent_pool: AgentPool instance with DyLAN metrics
            success_memory: SuccessMemory for domain performance data
            config: Specialization configuration
        """
        self._pool = agent_pool
        self._memory = success_memory
        self.config = config or SpecializationConfig()
        self._proposals: dict[str, SpecializationProposal] = {}
        self._last_proposal_time: dict[str, str] = {}  # domain -> ISO timestamp

    def evaluate(self) -> list[SpecializationProposal]:
        """
        Evaluate all domains and generate specialization proposals.

        Analyzes domain performance from SuccessMemory and checks
        whether thresholds are met for spawning specialist agents.

        Returns:
            List of new SpecializationProposal objects
        """
        domain_profiles = self._build_domain_profiles()
        new_proposals = []

        for domain, profile in domain_profiles.items():
            # Skip excluded domains
            if domain.lower() in [d.lower() for d in self.config.excluded_domains]:
                continue

            # Check if domain qualifies for specialization
            if not self._qualifies(domain, profile):
                continue

            # Check if under specialist limit
            if self._count_specialists(domain) >= self.config.max_specialists_per_domain:
                continue

            # Check cooldown
            if self._in_cooldown(domain):
                continue

            # Generate proposal
            proposal = self._create_proposal(domain, profile)
            self._proposals[proposal.proposal_id] = proposal
            self._last_proposal_time[domain] = proposal.created_at
            new_proposals.append(proposal)

        _logger.info(
            f"Auto-specializer: evaluated {len(domain_profiles)} domains, generated {len(new_proposals)} proposals"
        )

        return new_proposals

    def accept_proposal(self, proposal_id: str) -> bool:
        """
        Mark a proposal as accepted.

        Args:
            proposal_id: ID of the proposal to accept

        Returns:
            True if proposal was found and accepted
        """
        proposal = self._proposals.get(proposal_id)
        if proposal and proposal.status == "pending":
            proposal.status = "accepted"
            return True
        return False

    def reject_proposal(self, proposal_id: str) -> bool:
        """
        Mark a proposal as rejected.

        Args:
            proposal_id: ID of the proposal to reject

        Returns:
            True if proposal was found and rejected
        """
        proposal = self._proposals.get(proposal_id)
        if proposal and proposal.status == "pending":
            proposal.status = "rejected"
            return True
        return False

    def get_proposal(self, proposal_id: str) -> SpecializationProposal | None:
        """Get a proposal by ID."""
        return self._proposals.get(proposal_id)

    def list_proposals(self, status: str | None = None) -> list[SpecializationProposal]:
        """
        List all proposals, optionally filtered by status.

        Args:
            status: Filter by status (pending, accepted, rejected)
        """
        proposals = list(self._proposals.values())
        if status:
            proposals = [p for p in proposals if p.status == status]
        return proposals

    def get_domain_readiness(self) -> dict[str, dict[str, Any]]:
        """
        Get readiness assessment for all domains.

        Returns:
            Dict mapping domain -> readiness metrics
        """
        profiles = self._build_domain_profiles()
        readiness = {}

        for domain, profile in profiles.items():
            excluded = domain.lower() in [d.lower() for d in self.config.excluded_domains]
            at_limit = self._count_specialists(domain) >= self.config.max_specialists_per_domain
            qualifies = self._qualifies(domain, profile)

            readiness[domain] = {
                "profile": profile.to_dict(),
                "qualifies": qualifies,
                "excluded": excluded,
                "at_specialist_limit": at_limit,
                "in_cooldown": self._in_cooldown(domain),
                "tasks_needed": max(0, self.config.min_domain_tasks - profile.task_count),
                "success_gap": max(0.0, self.config.success_threshold - profile.success_rate),
            }

        return readiness

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _build_domain_profiles(self) -> dict[str, DomainProfile]:
        """Build performance profiles for each domain from SuccessMemory."""
        profiles: dict[str, DomainProfile] = {}

        if not self._memory:
            return profiles

        entries = self._memory.get_all()

        for entry in entries:
            for domain in entry.domains:
                domain_lower = domain.lower()
                if domain_lower not in profiles:
                    profiles[domain_lower] = DomainProfile(domain=domain_lower)

                profile = profiles[domain_lower]
                profile.task_count += 1

                is_success = entry.quality_score > 0.6
                if is_success:
                    profile.success_count += 1

                profile.total_quality += entry.quality_score

                for agent_id in entry.agents_used:
                    if agent_id not in profile.agents_involved:
                        profile.agents_involved.append(agent_id)

                mode = entry.swarm_mode
                profile.modes_used[mode] = profile.modes_used.get(mode, 0) + 1

                # Running average duration
                n = profile.task_count
                profile.avg_duration = (profile.avg_duration * (n - 1) + entry.duration_seconds) / n

        return profiles

    def _qualifies(self, domain: str, profile: DomainProfile) -> bool:
        """Check if a domain qualifies for specialization."""
        if profile.task_count < self.config.min_domain_tasks:
            return False

        if profile.success_rate < self.config.success_threshold:
            return False

        return not profile.avg_quality < self.config.min_quality_score

    def _count_specialists(self, domain: str) -> int:
        """Count existing specialist agents for a domain."""
        domain_lower = domain.lower()
        count = 0

        for _agent_id, profile in self._pool.agents.items():
            if not profile.is_active:
                continue
            if profile.provider != "spawned":
                continue

            # Check capabilities
            caps_lower = [c.lower() for c in profile.capabilities]
            if domain_lower in caps_lower:
                count += 1

        return count

    def _in_cooldown(self, domain: str) -> bool:
        """Check if a domain is in cooldown period."""
        domain_lower = domain.lower()
        last_time_str = self._last_proposal_time.get(domain_lower)
        if not last_time_str:
            return False

        try:
            last_time = datetime.fromisoformat(last_time_str)
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=UTC)

            now = datetime.now(UTC)
            hours_elapsed = (now - last_time).total_seconds() / 3600
            return hours_elapsed < self.config.cooldown_hours
        except (ValueError, TypeError):
            return False

    def _create_proposal(self, domain: str, profile: DomainProfile) -> SpecializationProposal:
        """Create a specialization proposal for a domain."""
        import hashlib

        proposal_id = hashlib.sha256(f"{domain}-{datetime.now(UTC).isoformat()}".encode()).hexdigest()[:8]

        agent_name = f"{domain}_specialist"

        # Determine capabilities from domain
        capabilities = [domain]
        if domain in ("coding", "devops"):
            capabilities.extend(["debugging", "testing"])
        elif domain in ("research", "analysis"):
            capabilities.extend(["data", "synthesis"])
        elif domain == "creative":
            capabilities.extend(["writing", "brainstorming"])
        elif domain == "security":
            capabilities.extend(["audit", "vulnerability"])

        # Suggest model
        suggested_model = self.MODEL_SUGGESTIONS.get(domain, "claude-sonnet-4-5-20250929")

        reason = (
            f"Domain '{domain}' has reached {profile.success_rate:.0%} success rate "
            f"across {profile.task_count} tasks with {profile.avg_quality:.2f} avg quality. "
            f"Qualifies for auto-specialization (threshold: "
            f"{self.config.success_threshold:.0%} over {self.config.min_domain_tasks}+ tasks)."
        )

        return SpecializationProposal(
            proposal_id=proposal_id,
            domain=domain,
            agent_name=agent_name,
            capabilities=capabilities,
            reason=reason,
            domain_profile=profile,
            suggested_model=suggested_model,
        )

    def to_dict(self) -> dict[str, Any]:
        """Export specializer state."""
        return {
            "config": {
                "success_threshold": self.config.success_threshold,
                "min_domain_tasks": self.config.min_domain_tasks,
                "min_quality_score": self.config.min_quality_score,
                "max_specialists_per_domain": self.config.max_specialists_per_domain,
                "cooldown_hours": self.config.cooldown_hours,
            },
            "proposals": {pid: p.to_dict() for pid, p in self._proposals.items()},
            "proposal_count": len(self._proposals),
        }
