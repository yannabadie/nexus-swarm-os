"""
Agent Reaper - DyLAN-based lifecycle management for spawned agents.

V12.4 COGNITIVE BOOST - Task #28

Provides garbage collection for spawned agents based on:
- DyLAN importance scores (low-performing agents archived)
- Inactivity duration (unused agents archived)
- Success rate thresholds (failing agents flagged)

Usage:
    from core.intelligence.evolution.agent_reaper import AgentReaper, ReaperConfig

    reaper = AgentReaper(agent_pool, workspace_path)
    report = reaper.scan()
    print(f"Found {len(report.candidates)} archival candidates")

    # Archive low-performing agents
    archived = reaper.reap()
    print(f"Archived {len(archived)} agents")
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class ReaperConfig:
    """
    Configuration for the agent reaper.

    Attributes:
        min_importance: Minimum DyLAN importance score to keep (default 0.1)
        max_inactivity_days: Maximum days without invocation before archival (default 30)
        min_success_rate: Minimum success rate to keep (default 0.2)
        min_invocations: Minimum invocations before scoring (new agents exempt)
        protect_internal: Never archive internal agents (gemini, claude)
        dry_run: If True, scan but don't actually archive
    """

    min_importance: float = 0.1
    max_inactivity_days: int = 30
    min_success_rate: float = 0.2
    min_invocations: int = 5
    protect_internal: bool = True
    dry_run: bool = False


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class ArchivalCandidate:
    """An agent identified for potential archival."""

    agent_id: str
    reason: str
    importance_score: float
    success_rate: float
    invocation_count: int
    last_active: str | None = None
    days_inactive: int = 0
    provider: str = ""


@dataclass
class ReaperReport:
    """Results from a reaper scan."""

    candidates: list[ArchivalCandidate] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)
    healthy: list[str] = field(default_factory=list)
    exempt: list[str] = field(default_factory=list)
    scanned_at: str = ""
    total_agents: int = 0

    def __post_init__(self):
        if not self.scanned_at:
            self.scanned_at = datetime.now(UTC).isoformat()

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def health_ratio(self) -> float:
        """Ratio of healthy agents to total scanned."""
        total = len(self.healthy) + len(self.candidates) + len(self.exempt)
        return len(self.healthy) / total if total > 0 else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned_at": self.scanned_at,
            "total_agents": self.total_agents,
            "candidates": [
                {
                    "agent_id": c.agent_id,
                    "reason": c.reason,
                    "importance_score": round(c.importance_score, 4),
                    "success_rate": round(c.success_rate, 4),
                    "invocation_count": c.invocation_count,
                    "days_inactive": c.days_inactive,
                }
                for c in self.candidates
            ],
            "protected": self.protected,
            "healthy": self.healthy,
            "exempt": self.exempt,
            "health_ratio": round(self.health_ratio, 2),
        }


@dataclass
class ArchivalResult:
    """Result of archiving a single agent."""

    agent_id: str
    success: bool
    archive_path: str | None = None
    error: str = ""


# =============================================================================
# Agent Reaper
# =============================================================================


class AgentReaper:
    """
    DyLAN-based agent lifecycle manager.

    Scans the agent pool and identifies underperforming or inactive agents
    for archival. Internal agents (gemini, claude) are always protected.

    The reaper operates in two phases:
    1. scan() - Identifies archival candidates, returns a report
    2. reap() - Archives candidates (moves files, deactivates in pool)
    """

    INTERNAL_PROVIDERS = {"gemini", "claude"}

    def __init__(
        self,
        agent_pool: Any,
        workspace_path: Path | None = None,
        config: ReaperConfig | None = None,
    ):
        """
        Initialize the agent reaper.

        Args:
            agent_pool: AgentPool instance with agent profiles
            workspace_path: Path to workspace (for agent file archival)
            config: Reaper configuration (defaults used if None)
        """
        self._pool = agent_pool
        self._workspace = Path(workspace_path) if workspace_path else None
        self.config = config or ReaperConfig()

    def scan(self) -> ReaperReport:
        """
        Scan agent pool and identify archival candidates.

        Returns:
            ReaperReport with candidates, protected, healthy, and exempt agents
        """
        report = ReaperReport(total_agents=len(self._pool.agents))
        now = datetime.now(UTC)

        for agent_id, profile in self._pool.agents.items():
            # Skip inactive agents (already archived)
            if not profile.is_active:
                continue

            # Internal agents are always protected
            if self.config.protect_internal and profile.provider in self.INTERNAL_PROVIDERS:
                report.protected.append(agent_id)
                continue

            # New agents with too few invocations are exempt
            if len(profile.invocation_history) < self.config.min_invocations:
                report.exempt.append(agent_id)
                continue

            # Check archival criteria
            candidate = self._evaluate_agent(agent_id, profile, now)
            if candidate:
                report.candidates.append(candidate)
            else:
                report.healthy.append(agent_id)

        _logger.info(
            f"Reaper scan: {report.candidate_count} candidates, "
            f"{len(report.healthy)} healthy, {len(report.protected)} protected, "
            f"{len(report.exempt)} exempt"
        )

        return report

    def reap(self, report: ReaperReport | None = None) -> list[ArchivalResult]:
        """
        Archive agents identified as candidates.

        Args:
            report: ReaperReport from scan() (runs scan if None)

        Returns:
            List of ArchivalResult for each archived agent
        """
        if report is None:
            report = self.scan()

        if self.config.dry_run:
            _logger.info(f"Dry run: would archive {report.candidate_count} agents")
            return [ArchivalResult(agent_id=c.agent_id, success=False, error="dry_run") for c in report.candidates]

        results: list[ArchivalResult] = []
        for candidate in report.candidates:
            result = self._archive_agent(candidate)
            results.append(result)

        archived_count = sum(1 for r in results if r.success)
        _logger.info(f"Reaped {archived_count}/{len(results)} agents")

        return results

    def get_agent_health(self, agent_id: str) -> dict[str, Any]:
        """
        Get health report for a specific agent.

        Returns:
            Dict with health metrics or None if agent not found
        """
        if agent_id not in self._pool.agents:
            return {"agent_id": agent_id, "status": "not_found"}

        profile = self._pool.agents[agent_id]
        now = datetime.now(UTC)
        days_inactive = self._get_days_inactive(profile, now)

        # Determine health status
        importance = profile.average_importance
        success_rate = profile.success_rate
        inv_count = len(profile.invocation_history)

        status = "healthy"
        warnings = []

        if inv_count >= self.config.min_invocations:
            if importance < self.config.min_importance:
                status = "critical"
                warnings.append(f"Low importance: {importance:.4f}")
            if success_rate < self.config.min_success_rate:
                status = "critical"
                warnings.append(f"Low success rate: {success_rate:.2%}")
            if days_inactive > self.config.max_inactivity_days:
                status = "warning" if status == "healthy" else status
                warnings.append(f"Inactive for {days_inactive} days")
        elif inv_count == 0:
            status = "new"
        else:
            status = "warming_up"

        return {
            "agent_id": agent_id,
            "provider": profile.provider,
            "status": status,
            "is_active": profile.is_active,
            "importance_score": round(importance, 4),
            "success_rate": round(success_rate, 4),
            "invocation_count": inv_count,
            "days_inactive": days_inactive,
            "warnings": warnings,
        }

    def get_pool_health(self) -> dict[str, Any]:
        """
        Get health report for the entire agent pool.

        Returns:
            Dict with pool-wide health metrics
        """
        report = self.scan()
        agents_health = {}
        for agent_id in self._pool.agents:
            agents_health[agent_id] = self.get_agent_health(agent_id)

        status_counts = {}
        for h in agents_health.values():
            s = h["status"]
            status_counts[s] = status_counts.get(s, 0) + 1

        return {
            "total_agents": report.total_agents,
            "health_ratio": round(report.health_ratio, 2),
            "archival_candidates": report.candidate_count,
            "status_distribution": status_counts,
            "agents": agents_health,
        }

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _evaluate_agent(self, agent_id: str, profile: Any, now: datetime) -> ArchivalCandidate | None:
        """Evaluate a single agent against archival criteria."""
        importance = profile.average_importance
        success_rate = profile.success_rate
        inv_count = len(profile.invocation_history)
        days_inactive = self._get_days_inactive(profile, now)

        # Check low importance
        if importance < self.config.min_importance:
            return ArchivalCandidate(
                agent_id=agent_id,
                reason=f"Low importance score: {importance:.4f} < {self.config.min_importance}",
                importance_score=importance,
                success_rate=success_rate,
                invocation_count=inv_count,
                days_inactive=days_inactive,
                provider=profile.provider,
            )

        # Check low success rate
        if success_rate < self.config.min_success_rate:
            return ArchivalCandidate(
                agent_id=agent_id,
                reason=f"Low success rate: {success_rate:.2%} < {self.config.min_success_rate:.2%}",
                importance_score=importance,
                success_rate=success_rate,
                invocation_count=inv_count,
                days_inactive=days_inactive,
                provider=profile.provider,
            )

        # Check inactivity
        if days_inactive > self.config.max_inactivity_days:
            return ArchivalCandidate(
                agent_id=agent_id,
                reason=f"Inactive for {days_inactive} days > {self.config.max_inactivity_days} max",
                importance_score=importance,
                success_rate=success_rate,
                invocation_count=inv_count,
                days_inactive=days_inactive,
                provider=profile.provider,
            )

        return None

    def _get_days_inactive(self, profile: Any, now: datetime) -> int:
        """Get number of days since last invocation."""
        if not profile.invocation_history:
            return 0

        last_inv = profile.invocation_history[-1]
        last_ts = last_inv.timestamp
        if isinstance(last_ts, str):
            last_ts = datetime.fromisoformat(last_ts)

        # Ensure both are tz-aware for comparison
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=UTC)

        delta = now - last_ts
        return delta.days

    def _archive_agent(self, candidate: ArchivalCandidate) -> ArchivalResult:
        """Archive a single agent."""
        agent_id = candidate.agent_id

        try:
            # Deactivate in pool
            if agent_id in self._pool.agents:
                self._pool.agents[agent_id].is_active = False

            # Move agent files if workspace available
            archive_path = None
            if self._workspace:
                agents_dir = self._workspace / "agents"
                archive_dir = self._workspace / "agents" / ".archive"
                agent_file = agents_dir / f"{agent_id}.md"

                if agent_file.exists():
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    dest = archive_dir / f"{agent_id}.md"
                    shutil.move(str(agent_file), str(dest))
                    archive_path = str(dest)

            _logger.info(f"Archived agent '{agent_id}': {candidate.reason}")

            return ArchivalResult(
                agent_id=agent_id,
                success=True,
                archive_path=archive_path,
            )

        except Exception as e:
            _logger.error(f"Failed to archive agent '{agent_id}': {e}")
            return ArchivalResult(
                agent_id=agent_id,
                success=False,
                error=str(e),
            )
