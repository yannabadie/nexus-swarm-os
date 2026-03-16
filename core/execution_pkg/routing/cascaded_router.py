"""
CascadedRouter - Multi-Level Routing for Multi-Agent Systems.

NEXUS V12.4 COGNITIVE BOOST - Based on MasRouter (arXiv:2502.11133)

Key Ideas from MasRouter:
- Cascaded controller that progressively determines:
  1. Collaboration mode (PARALLEL, SEQUENTIAL, etc.)
  2. Agent role allocation (lead, support, specialist)
  3. Model routing per agent (Opus/Sonnet, Pro/Flash)
- Plug-and-play with existing MAS frameworks
- Performance improvement + overhead reduction

NEXUS Adaptation:
- Pure Python, rule-based routing (no ML model required)
- Uses DyLAN scores from existing infrastructure
- Three-stage cascading decision pipeline
- Integrates with ModelRouter and DynamicRoleAssigner
- Thread-safe singleton pattern

Architecture:
    +------------------------------------------+
    |           CascadedRouter                  |
    |  +----------+                            |
    |  | Stage 1  | -> Collaboration Mode       |
    |  | (Task)   |   (PARALLEL, SEQUENTIAL..) |
    |  +----+-----+                            |
    |  +----v-----+                            |
    |  | Stage 2  | -> Role Assignment          |
    |  | (Mode)   |   (lead, support, peer)    |
    |  +----+-----+                            |
    |  +----v-----+                            |
    |  | Stage 3  | -> Model Selection          |
    |  | (Role)   |   (Opus/Sonnet, Pro/Flash) |
    |  +----------+                            |
    +------------------------------------------+

Author: Claude (NEXUS V12.4 COGNITIVE BOOST)
Date: 2026-02-17
Reference: arXiv:2502.11133 (MasRouter: Learning to Route LLMs for MAS)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Stage 1: Task complexity -> mode mapping thresholds
COMPLEXITY_THRESHOLDS = {
    "trivial": 0.2,  # Below 0.2 complexity -> SPECIALIST
    "simple": 0.4,  # 0.2-0.4 -> SEQUENTIAL
    "moderate": 0.6,  # 0.4-0.6 -> LEAD_SUPPORT or PING_PONG
    "complex": 0.8,  # 0.6-0.8 -> PARALLEL or RED_BLUE
    "expert": 1.0,  # 0.8-1.0 -> full PARALLEL
}

# Stage 2: Mode -> default role assignments
DEFAULT_ROLE_ASSIGNMENTS = {
    "parallel": {"claude": "peer", "gemini": "peer"},
    "sequential": {"claude": "first", "gemini": "second"},
    "lead_support": {"claude": "lead", "gemini": "support"},
    "ping_pong": {"claude": "initiator", "gemini": "responder"},
    "specialist": {"claude": "specialist", "gemini": "idle"},
    "red_blue": {"claude": "blue_team", "gemini": "red_team"},
}

# Stage 3: Role -> model tier mapping
ROLE_MODEL_MAPPING = {
    # Roles that need the strongest model
    "lead": "high",
    "specialist": "high",
    "blue_team": "high",  # Defender needs thoroughness
    "first": "high",  # First in sequence sets direction
    # Roles that can use a lighter model
    "support": "low",
    "peer": "medium",
    "second": "medium",
    "responder": "medium",
    "red_team": "medium",  # Attacker can be lighter
    "initiator": "medium",
    "idle": "low",
}

# Model tier -> concrete model names
# V12.4: Added DeepSeek (98% cheaper) and Kimi (90% cheaper) for cost optimization
MODEL_TIERS = {
    "high": {
        "claude": "claude-opus-4-6",
        "gemini": "gemini-3-pro-preview",
        "deepseek": "deepseek-chat",  # Fallback for cost-optimized
        "kimi": "kimi-k2.5",  # Fallback for cost-optimized
    },
    "medium": {
        "claude": "claude-sonnet-4-5-20250929",
        "gemini": "gemini-3-pro-preview",
        "deepseek": "deepseek-chat",  # 98% cheaper than Claude
        "kimi": "kimi-k2.5",  # 90% cheaper than Claude, multimodal
    },
    "low": {
        "claude": "claude-sonnet-4-5-20250929",
        "gemini": "gemini-3-pro-preview",
        "deepseek": "deepseek-chat",  # Best for budget-constrained scenarios
        "kimi": "kimi-k2.5",  # Alternative low-cost option
    },
}

# Domain affinities for role assignment
DOMAIN_AFFINITIES = {
    "claude": {"coding", "security", "architecture", "debugging", "analysis"},
    "gemini": {"research", "web_search", "data_analysis", "planning", "creative"},
    "deepseek": {"coding", "reasoning", "analysis", "simple_tasks"},  # V3: Strong at code, R1: Reasoning
    "kimi": {"multimodal", "vision", "agent_swarm", "creative"},  # K2.5: Multimodal + Swarm
}


# =============================================================================
# Data Structures
# =============================================================================


class RoutingStage(Enum):
    """Stages of the cascaded routing pipeline."""

    MODE_SELECTION = "mode_selection"
    ROLE_ASSIGNMENT = "role_assignment"
    MODEL_SELECTION = "model_selection"


@dataclass
class AgentRouting:
    """Routing decision for a single agent."""

    agent_id: str
    role: str
    model_tier: str
    model_name: str
    reasoning: str = ""


@dataclass
class CascadedRoutingDecision:
    """
    Complete routing decision from the cascaded pipeline.

    Contains decisions from all 3 stages.
    """

    collaboration_mode: str
    agent_routings: dict[str, AgentRouting]
    estimated_cost_reduction: float  # vs always using top-tier models
    stage_timings: dict[str, float] = field(default_factory=dict)
    reasoning: str = ""

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "collaboration_mode": self.collaboration_mode,
            "agent_routings": {
                aid: {
                    "role": ar.role,
                    "model_tier": ar.model_tier,
                    "model_name": ar.model_name,
                    "reasoning": ar.reasoning,
                }
                for aid, ar in self.agent_routings.items()
            },
            "estimated_cost_reduction": round(self.estimated_cost_reduction, 3),
            "stage_timings": {k: round(v, 4) for k, v in self.stage_timings.items()},
            "reasoning": self.reasoning,
        }


@dataclass
class RoutingHistory:
    """Historical routing record for learning."""

    task_hash: str
    decision: CascadedRoutingDecision
    outcome_success: bool | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class RouterStats:
    """Statistics about the cascaded router."""

    total_decisions: int
    mode_distribution: dict[str, int]
    tier_distribution: dict[str, int]
    avg_cost_reduction: float
    success_rate: float


# =============================================================================
# CascadedRouter
# =============================================================================


class CascadedRouter:
    """
    Three-stage cascaded routing for multi-agent systems.

    Stage 1: Task Analysis -> Collaboration Mode
    Stage 2: Mode + Agent Capabilities -> Role Assignment
    Stage 3: Role + Task Type -> Model Selection

    Each stage narrows the decision space for the next stage,
    reducing the overall routing complexity.
    """

    def __init__(
        self,
        agent_ids: list[str] | None = None,
        domain_affinities: dict[str, set] | None = None,
        history_size: int = 100,
        routing_policy: str = "balanced",
    ):
        """
        Initialize the cascaded router.

        Args:
            agent_ids: List of available agent IDs
            domain_affinities: Per-agent domain strengths
            history_size: Maximum routing history entries to keep
            routing_policy: "balanced", "cost_optimized", or "quality_optimized"
        """
        self._agent_ids = agent_ids or ["claude", "gemini"]
        self._domain_affinities = domain_affinities or DOMAIN_AFFINITIES
        self._history: list[RoutingHistory] = []
        self._history_size = history_size
        self._routing_policy = routing_policy
        self._lock = threading.RLock()

        # Performance counters
        self._total_decisions = 0
        self._mode_counts: dict[str, int] = {}
        self._tier_counts: dict[str, int] = {}
        self._total_cost_reduction = 0.0
        self._success_count = 0
        self._feedback_count = 0

    def route(
        self,
        task_description: str,
        complexity: float,
        domains: list[str] | None = None,
        agent_scores: dict[str, float] | None = None,
    ) -> CascadedRoutingDecision:
        """
        Execute the full cascaded routing pipeline.

        Args:
            task_description: Description of the task
            complexity: Normalized complexity score (0.0-1.0)
            domains: Task domains (e.g., ["coding", "security"])
            agent_scores: Optional DyLAN scores per agent

        Returns:
            CascadedRoutingDecision with mode, roles, and models
        """
        with self._lock:
            domains = domains or []
            agent_scores = agent_scores or {}
            timings: dict[str, float] = {}

            # Stage 1: Mode Selection
            t0 = time.time()
            mode = self._stage1_mode_selection(complexity, domains)
            timings["stage1_mode"] = time.time() - t0

            # Stage 2: Role Assignment
            t1 = time.time()
            roles = self._stage2_role_assignment(mode, domains, agent_scores)
            timings["stage2_roles"] = time.time() - t1

            # Stage 3: Model Selection
            t2 = time.time()
            routings, cost_reduction = self._stage3_model_selection(roles, complexity)
            timings["stage3_models"] = time.time() - t2

            # Build decision
            decision = CascadedRoutingDecision(
                collaboration_mode=mode,
                agent_routings=routings,
                estimated_cost_reduction=cost_reduction,
                stage_timings=timings,
                reasoning=self._build_reasoning(mode, roles, complexity, domains),
            )

            # Track stats
            self._total_decisions += 1
            self._mode_counts[mode] = self._mode_counts.get(mode, 0) + 1
            for ar in routings.values():
                self._tier_counts[ar.model_tier] = self._tier_counts.get(ar.model_tier, 0) + 1
            self._total_cost_reduction += cost_reduction

            # Add to history
            task_hash = str(hash(task_description[:200]))
            self._history.append(
                RoutingHistory(
                    task_hash=task_hash,
                    decision=decision,
                )
            )
            if len(self._history) > self._history_size:
                self._history = self._history[-self._history_size :]

            logger.debug(f"[MasRouter] Routed: mode={mode}, cost_reduction={cost_reduction:.1%}")
            return decision

    def record_outcome(
        self,
        task_description: str,
        success: bool,
    ) -> None:
        """
        Record the outcome of a routing decision for learning.

        Args:
            task_description: The task that was routed
            success: Whether the task succeeded
        """
        with self._lock:
            task_hash = str(hash(task_description[:200]))
            self._feedback_count += 1

            if success:
                self._success_count += 1

            # Update most recent matching history entry
            for entry in reversed(self._history):
                if entry.task_hash == task_hash and entry.outcome_success is None:
                    entry.outcome_success = success
                    break

    def get_stats(self) -> RouterStats:
        """Get router statistics."""
        with self._lock:
            avg_reduction = self._total_cost_reduction / self._total_decisions if self._total_decisions > 0 else 0.0
            success_rate = self._success_count / self._feedback_count if self._feedback_count > 0 else 0.0

            return RouterStats(
                total_decisions=self._total_decisions,
                mode_distribution=dict(self._mode_counts),
                tier_distribution=dict(self._tier_counts),
                avg_cost_reduction=round(avg_reduction, 3),
                success_rate=round(success_rate, 3),
            )

    # =========================================================================
    # Stage 1: Mode Selection
    # =========================================================================

    def _stage1_mode_selection(
        self,
        complexity: float,
        domains: list[str],
    ) -> str:
        """
        Determine collaboration mode based on task complexity and domains.

        Mapping:
        - TRIVIAL (< 0.2): SPECIALIST
        - SIMPLE (0.2-0.4): SEQUENTIAL
        - MODERATE (0.4-0.6): LEAD_SUPPORT or PING_PONG
        - COMPLEX (0.6-0.8): PARALLEL or RED_BLUE
        - EXPERT (> 0.8): PARALLEL

        Domain overrides:
        - "security" domain -> RED_BLUE (adversarial)
        - Mixed domains -> PARALLEL (each agent tackles their strength)

        Args:
            complexity: 0.0-1.0 complexity score
            domains: Task domains

        Returns:
            Collaboration mode string
        """
        # Domain-based overrides
        if "security" in domains and complexity >= 0.4:
            return "red_blue"

        if len(domains) >= 3 and complexity >= 0.5:
            return "parallel"

        # Complexity-based mapping
        if complexity < COMPLEXITY_THRESHOLDS["trivial"]:
            return "specialist"
        elif complexity < COMPLEXITY_THRESHOLDS["simple"]:
            return "sequential"
        elif complexity < COMPLEXITY_THRESHOLDS["moderate"]:
            # Choose between lead_support and ping_pong
            # Ping-pong for iterative tasks
            iterative_domains = {"debugging", "creative", "refactoring"}
            if set(domains) & iterative_domains:
                return "ping_pong"
            return "lead_support"
        elif complexity < COMPLEXITY_THRESHOLDS["complex"]:
            return "parallel"
        else:
            return "parallel"

    # =========================================================================
    # Stage 2: Role Assignment
    # =========================================================================

    def _stage2_role_assignment(
        self,
        mode: str,
        domains: list[str],
        agent_scores: dict[str, float],
    ) -> dict[str, str]:
        """
        Assign roles to agents based on mode, domains, and scores.

        Args:
            mode: Selected collaboration mode
            domains: Task domains
            agent_scores: DyLAN importance scores per agent

        Returns:
            Dict mapping agent_id -> role
        """
        # Start with default roles for this mode
        roles = dict(DEFAULT_ROLE_ASSIGNMENTS.get(mode, {}))

        # For modes with asymmetric roles, decide who leads
        if mode in ("lead_support", "sequential"):
            leader = self._select_leader(domains, agent_scores)
            follower = [aid for aid in self._agent_ids if aid != leader][0] if len(self._agent_ids) > 1 else leader

            if mode == "lead_support":
                roles[leader] = "lead"
                roles[follower] = "support"
            else:
                roles[leader] = "first"
                roles[follower] = "second"

        elif mode == "specialist":
            specialist = self._select_leader(domains, agent_scores)
            for aid in self._agent_ids:
                roles[aid] = "specialist" if aid == specialist else "idle"

        # Ensure all agents have roles
        for aid in self._agent_ids:
            if aid not in roles:
                roles[aid] = "peer"

        return roles

    def _select_leader(
        self,
        domains: list[str],
        agent_scores: dict[str, float],
    ) -> str:
        """
        Select the best agent to lead based on domain affinity and scores.

        Args:
            domains: Task domains
            agent_scores: DyLAN scores

        Returns:
            Agent ID of the best leader
        """
        scores: dict[str, float] = {}

        for agent_id in self._agent_ids:
            # Base score from DyLAN
            score = agent_scores.get(agent_id, 0.5)

            # Domain affinity bonus
            agent_domains = self._domain_affinities.get(agent_id, set())
            domain_overlap = len(set(domains) & agent_domains)
            if domains:
                score += 0.3 * (domain_overlap / len(domains))

            scores[agent_id] = score

        # Return agent with highest score
        return max(scores, key=scores.get) if scores else self._agent_ids[0]

    # =========================================================================
    # Stage 3: Model Selection
    # =========================================================================

    def _stage3_model_selection(
        self,
        roles: dict[str, str],
        complexity: float,
    ) -> tuple[dict[str, AgentRouting], float]:
        """
        Select model tier for each agent based on their role.

        V12.4: Cost-optimized policy uses DeepSeek/Kimi for significant savings.

        Args:
            roles: Agent -> role mapping
            complexity: Task complexity (for cost estimation)

        Returns:
            Tuple of (agent_routings, estimated_cost_reduction)
        """
        routings: dict[str, AgentRouting] = {}
        total_cost = 0.0
        max_cost = 0.0

        for agent_id, role in roles.items():
            # Determine model tier from role
            tier = ROLE_MODEL_MAPPING.get(role, "medium")

            # Policy-aware model selection (V12.4)
            if self._routing_policy == "cost_optimized":
                # Use low-cost alternatives
                if tier == "low" or tier == "medium":
                    # Use DeepSeek (98% cheaper) for Claude-like tasks
                    if agent_id == "claude":
                        model_name = MODEL_TIERS[tier].get("deepseek", "deepseek-chat")
                    # Use Kimi (90% cheaper) for Gemini-like tasks
                    elif agent_id == "gemini":
                        model_name = MODEL_TIERS[tier].get("kimi", "kimi-k2.5")
                    else:
                        model_name = MODEL_TIERS[tier].get(agent_id, "")
                else:
                    # Keep high tier for quality (but still cheaper than Opus/Pro)
                    model_name = MODEL_TIERS.get(tier, {}).get(
                        agent_id, "claude-sonnet-4-5-20250929" if agent_id == "claude" else "gemini-3-pro-preview"
                    )
            else:
                # Balanced or quality-optimized: use original Claude/Gemini
                model_name = MODEL_TIERS.get(tier, {}).get(
                    agent_id, "claude-sonnet-4-5-20250929" if agent_id == "claude" else "gemini-3-pro-preview"
                )

            routings[agent_id] = AgentRouting(
                agent_id=agent_id,
                role=role,
                model_tier=tier,
                model_name=model_name,
                reasoning=f"Role '{role}' -> tier '{tier}' (policy={self._routing_policy})",
            )

            # Cost estimation (relative, V12.4: updated for DeepSeek/Kimi)
            if self._routing_policy == "cost_optimized" and tier in ["low", "medium"]:
                # DeepSeek/Kimi are 90-98% cheaper
                tier_costs = {"high": 1.0, "medium": 0.01, "low": 0.02}
            else:
                tier_costs = {"high": 1.0, "medium": 0.3, "low": 0.1}

            total_cost += tier_costs.get(tier, 0.3)
            max_cost += 1.0  # If all agents used high tier

        # Cost reduction
        cost_reduction = 1.0 - (total_cost / max_cost) if max_cost > 0 else 0.0

        return routings, max(0.0, cost_reduction)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _build_reasoning(
        self,
        mode: str,
        roles: dict[str, str],
        complexity: float,
        domains: list[str],
    ) -> str:
        """Build human-readable reasoning for the routing decision."""
        parts = [
            f"Complexity {complexity:.2f} -> {mode} mode.",
        ]
        if domains:
            parts.append(f"Domains: {', '.join(domains)}.")

        role_desc = ", ".join(f"{aid}={role}" for aid, role in roles.items())
        parts.append(f"Roles: {role_desc}.")

        return " ".join(parts)


# =============================================================================
# Singleton
# =============================================================================

_router: CascadedRouter | None = None
_router_lock = threading.Lock()


def get_cascaded_router(
    agent_ids: list[str] | None = None,
) -> CascadedRouter:
    """Get or create the global CascadedRouter instance."""
    global _router
    if _router is None:
        with _router_lock:
            if _router is None:
                _router = CascadedRouter(agent_ids=agent_ids)
    return _router


def reset_cascaded_router() -> None:
    """Reset the global instance (for testing)."""
    global _router
    _router = None
