"""
Model Router - Intelligent Model Selection for NEXUS V7 Chrysalis

Routes tasks to the most appropriate model based on task type and complexity.
Implements routing strategies for both Claude (Opus/Sonnet) and Gemini (Pro/Flash).

V12.4 COGNITIVE BOOST additions:
- RoutingPolicy: COST_OPTIMIZED, QUALITY_OPTIMIZED, BALANCED
- SLM triage: route simple tasks to Haiku/Flash before upgrading
- OTel tracing for routing decisions

Usage:
    from core.execution_pkg.routing import ModelRouter, RoutingPolicy

    router = ModelRouter(config, policy=RoutingPolicy.BALANCED)

    # Claude routing with SLM triage
    model = router.select_claude_model(TaskType.SIMPLE)
    # Returns: "claude-haiku-4-5-20251001" (cost-optimized)
"""

import contextlib
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Optional

from core.provider_registry import get_default_model

if TYPE_CHECKING:
    from core.config import Config
    from core.intelligence.swarm import AgentPool


class RoutingPolicy(Enum):
    """
    Routing policy for model selection (V12.4).

    Controls the cost/quality tradeoff:
    - COST_OPTIMIZED: Prefer cheapest model that can handle the task (SLM first)
    - QUALITY_OPTIMIZED: Always use the most capable model
    - BALANCED: Use task complexity to select tier (default, same as V7 behavior)
    """

    COST_OPTIMIZED = "cost_optimized"
    QUALITY_OPTIMIZED = "quality_optimized"
    BALANCED = "balanced"


class ModelTier(Enum):
    """
    Model capability tiers for SLM triage (V12.4).

    Ordered from cheapest/fastest to most capable:
    LIGHT -> MEDIUM -> HEAVY
    """

    LIGHT = "light"  # Haiku / Flash (cheapest, fastest)
    MEDIUM = "medium"  # Sonnet / Pro (balanced)
    HEAVY = "heavy"  # Opus / Pro-exp (most capable)


class TaskType(Enum):
    """
    Task types for model routing.

    Claude: Complex tasks -> Opus, simpler tasks -> Sonnet
    Gemini: Complex tasks -> 3-Pro, simpler tasks -> Flash
    """

    # Opus/3-Pro routed (complex, creative, security-critical)
    BRAINSTORM = "brainstorm"  # Evolution brainstorming
    REDTEAM = "redteam"  # Security/alignment testing
    ARCHITECT = "architect"  # Architecture decisions
    EVOLUTION = "evolution"  # Child mutation design
    REASONING = "reasoning"  # Complex reasoning (Gemini 3 Pro)
    RESEARCH = "research"  # Web research (Gemini 3 Pro)
    ANALYSIS = "analysis"  # Deep analysis (Gemini 3 Pro)

    # Sonnet/Flash routed (simpler, faster)
    TOOL = "tool"  # Tool execution
    VALIDATION = "validation"  # Code validation
    SIMPLE = "simple"  # Simple queries
    FORMAT = "format"  # Formatting tasks

    # Default
    DEFAULT = "default"


@dataclass
class RoutingDecision:
    """Result of model routing decision"""

    model_id: str
    task_type: TaskType
    reason: str
    is_opus: bool = False
    tier: ModelTier = ModelTier.MEDIUM
    policy: RoutingPolicy = RoutingPolicy.BALANCED


@dataclass
class CascadeRoute:
    """
    Cascade routing plan (arxiv:2410.10347).

    Defines an ordered list of models to try, cheapest first.
    The caller attempts each model in order, escalating only if the
    previous result's quality is below the confidence threshold.
    """

    models: list  # Ordered list of model IDs (cheapest first)
    agent_id: str  # "claude" or "gemini"
    task_type: TaskType
    confidence_threshold: float = 0.7  # Escalate if quality < this


class ModelRouter:
    """
    Routes tasks to appropriate models based on complexity.

    Claude:
        Opus (claude-opus-4-5): Complex reasoning, creativity, security
        Sonnet (claude-sonnet-4-5): Speed, tools, simple tasks

    Gemini:
        3.1 Pro Preview (gemini-3.1-pro-preview): Complex reasoning, research, analysis
        Flash Preview (gemini-3-flash-preview): Simple tasks, validation, formatting
    """

    def __init__(
        self,
        config: Optional["Config"] = None,
        policy: RoutingPolicy | None = None,
    ):
        """
        Initialize router with config and routing policy.

        Args:
            config: NEXUS config with model IDs and task type mappings
            policy: Routing policy (default: BALANCED)
        """
        # V12.4: Routing policy
        self.policy = policy or RoutingPolicy.BALANCED

        # Default Claude model IDs
        self.opus_model = get_default_model("anthropic", "opus")
        self.sonnet_model = get_default_model("anthropic", "sonnet")

        # V12.4: SLM triage - Haiku for light tasks
        self.haiku_model = "claude-haiku-4-5-20251001"

        # Default Gemini model IDs (current canonical snapshot on 2026-03-09)
        self.gemini_model = get_default_model("google", "pro")
        self.gemini_pro_model = get_default_model("google", "pro")
        self.gemini_flash_model = get_default_model("google", "flash")

        # Default Claude task type mappings
        self.opus_tasks = {TaskType.BRAINSTORM, TaskType.REDTEAM, TaskType.ARCHITECT, TaskType.EVOLUTION}
        self.sonnet_tasks = {TaskType.TOOL, TaskType.VALIDATION, TaskType.SIMPLE, TaskType.FORMAT}

        # Default Gemini task type mappings (V7 Sprint 6)
        self.gemini_pro_tasks = {
            TaskType.REASONING,
            TaskType.RESEARCH,
            TaskType.ANALYSIS,
            TaskType.BRAINSTORM,
            TaskType.EVOLUTION,
        }
        self.gemini_flash_tasks = {TaskType.SIMPLE, TaskType.FORMAT, TaskType.VALIDATION, TaskType.TOOL}

        # V12.4: Task type -> tier mapping (for SLM triage)
        self._task_tiers: dict[TaskType, ModelTier] = {
            # Heavy tier (complex reasoning, creativity, security)
            TaskType.BRAINSTORM: ModelTier.HEAVY,
            TaskType.REDTEAM: ModelTier.HEAVY,
            TaskType.ARCHITECT: ModelTier.HEAVY,
            TaskType.EVOLUTION: ModelTier.HEAVY,
            # Medium tier (reasoning, research, analysis)
            TaskType.REASONING: ModelTier.MEDIUM,
            TaskType.RESEARCH: ModelTier.MEDIUM,
            TaskType.ANALYSIS: ModelTier.MEDIUM,
            TaskType.DEFAULT: ModelTier.MEDIUM,
            # Light tier (simple, fast, cheap)
            TaskType.TOOL: ModelTier.LIGHT,
            TaskType.VALIDATION: ModelTier.LIGHT,
            TaskType.SIMPLE: ModelTier.LIGHT,
            TaskType.FORMAT: ModelTier.LIGHT,
        }

        # Override with config if provided
        if config:
            # Routing policy from config/env
            policy_str = getattr(config, "routing_policy", None)
            if policy_str and not policy:
                with contextlib.suppress(ValueError):
                    self.policy = RoutingPolicy(policy_str)

            # Claude models
            self.opus_model = getattr(config, "claude_opus_model", self.opus_model)
            self.sonnet_model = getattr(config, "claude_sonnet_model", self.sonnet_model)
            self.haiku_model = getattr(config, "claude_haiku_model", self.haiku_model)

            # Gemini models (V7 Sprint 6)
            self.gemini_model = getattr(config, "gemini_default_model", self.gemini_model)
            self.gemini_pro_model = getattr(config, "gemini_pro_model", self.gemini_pro_model)
            self.gemini_flash_model = getattr(config, "gemini_flash_model", self.gemini_flash_model)

            # Update Claude task mappings from config lists
            opus_list = getattr(config, "opus_task_types", [])
            sonnet_list = getattr(config, "sonnet_task_types", [])

            if opus_list:
                self.opus_tasks = {TaskType(t) for t in opus_list if t in [e.value for e in TaskType]}
            if sonnet_list:
                self.sonnet_tasks = {TaskType(t) for t in sonnet_list if t in [e.value for e in TaskType]}

            # Update Gemini task mappings from config lists (V7 Sprint 6)
            gemini_pro_list = getattr(config, "gemini_pro_tasks", [])
            gemini_flash_list = getattr(config, "gemini_flash_tasks", [])

            if gemini_pro_list:
                self.gemini_pro_tasks = {TaskType(t) for t in gemini_pro_list if t in [e.value for e in TaskType]}
            if gemini_flash_list:
                self.gemini_flash_tasks = {TaskType(t) for t in gemini_flash_list if t in [e.value for e in TaskType]}

    def select_claude_model(self, task_type: TaskType) -> str:
        """
        Select appropriate Claude model for task type.

        V12.4: Now policy-aware. BALANCED uses original logic,
        COST_OPTIMIZED adds Haiku tier, QUALITY_OPTIMIZED always uses Opus.

        Args:
            task_type: Type of task to perform

        Returns:
            Model ID string (opus, sonnet, or haiku)
        """
        if self.policy == RoutingPolicy.QUALITY_OPTIMIZED:
            return self.opus_model

        if self.policy == RoutingPolicy.COST_OPTIMIZED:
            tier = self._task_tiers.get(task_type, ModelTier.MEDIUM)
            if tier == ModelTier.LIGHT:
                return self.haiku_model
            elif tier == ModelTier.MEDIUM:
                return self.sonnet_model
            else:
                return self.opus_model

        # BALANCED (default): original V7 behavior
        if task_type in self.opus_tasks:
            return self.opus_model
        return self.sonnet_model

    def get_task_tier(self, task_type: TaskType) -> ModelTier:
        """
        Get the model tier for a task type.

        Args:
            task_type: Type of task

        Returns:
            ModelTier (LIGHT, MEDIUM, or HEAVY)
        """
        return self._task_tiers.get(task_type, ModelTier.MEDIUM)

    def select_claude_by_tier(self, tier: ModelTier) -> str:
        """
        Select Claude model directly by tier (V12.4).

        Args:
            tier: Model capability tier

        Returns:
            Model ID string
        """
        if tier == ModelTier.LIGHT:
            return self.haiku_model
        elif tier == ModelTier.HEAVY:
            return self.opus_model
        return self.sonnet_model

    def select_gemini_by_tier(self, tier: ModelTier) -> str:
        """
        Select Gemini model directly by tier (V12.4).

        Args:
            tier: Model capability tier

        Returns:
            Model ID string
        """
        if tier == ModelTier.LIGHT:
            return self.gemini_flash_model
        return self.gemini_pro_model

    def select_claude_model_str(self, task_type_str: str) -> str:
        """
        Select Claude model from string task type.

        Args:
            task_type_str: String like "brainstorm", "tool", etc.

        Returns:
            Model ID string
        """
        try:
            task_type = TaskType(task_type_str.lower())
        except ValueError:
            task_type = TaskType.DEFAULT
        return self.select_claude_model(task_type)

    def route(self, task_type: TaskType) -> RoutingDecision:
        """
        Make a full routing decision with explanation.

        V12.4: Now includes tier and policy in decision.

        Args:
            task_type: Type of task

        Returns:
            RoutingDecision with model, tier, policy, and reasoning
        """
        model = self.select_claude_model(task_type)
        is_opus = model == self.opus_model
        tier = self.get_task_tier(task_type)

        if model == self.haiku_model:
            tier_label = "Haiku (light)"
        elif is_opus:
            tier_label = "Opus (heavy)"
        else:
            tier_label = "Sonnet (medium)"

        reason = f"[{self.policy.value}] Task '{task_type.value}' (tier={tier.value}) -> {tier_label}"

        return RoutingDecision(
            model_id=model,
            task_type=task_type,
            reason=reason,
            is_opus=is_opus,
            tier=tier,
            policy=self.policy,
        )

    def get_gemini_model(self) -> str:
        """Get the default configured Gemini model"""
        return self.gemini_model

    def select_gemini_model(self, task_type: TaskType) -> str:
        """
        Select appropriate Gemini model for task type (V7 Sprint 6).

        V12.4: Now policy-aware.
        QUALITY_OPTIMIZED -> always Pro
        COST_OPTIMIZED -> Flash for LIGHT/MEDIUM tasks
        BALANCED -> original behavior (Pro for complex, Flash for simple)

        Args:
            task_type: Type of task to perform

        Returns:
            Model ID string
        """
        if self.policy == RoutingPolicy.QUALITY_OPTIMIZED:
            return self.gemini_pro_model

        if self.policy == RoutingPolicy.COST_OPTIMIZED:
            tier = self._task_tiers.get(task_type, ModelTier.MEDIUM)
            if tier == ModelTier.HEAVY:
                return self.gemini_pro_model
            return self.gemini_flash_model

        # BALANCED (default): original behavior
        if task_type in self.gemini_pro_tasks:
            return self.gemini_pro_model
        return self.gemini_flash_model

    def select_gemini_model_str(self, task_type_str: str) -> str:
        """
        Select Gemini model from string task type.

        Args:
            task_type_str: String like "reasoning", "research", "tool", etc.

        Returns:
            Model ID string
        """
        try:
            task_type = TaskType(task_type_str.lower())
        except ValueError:
            task_type = TaskType.DEFAULT
        return self.select_gemini_model(task_type)

    def should_use_gemini_pro(self, task_type: TaskType) -> bool:
        """Check if task should use Gemini 3 Pro (V7 Sprint 6)"""
        return task_type in self.gemini_pro_tasks

    def should_use_opus(self, task_type: TaskType) -> bool:
        """Check if task should use Opus"""
        return task_type in self.opus_tasks

    def select_best_agent(
        self, task_type: TaskType, agent_pool: Optional["AgentPool"] = None, min_importance: float = 0.5
    ) -> RoutingDecision:
        """
        Select best agent using DyLAN metrics when available.

        Combines static task type routing with dynamic performance metrics.
        Falls back to static routing if no pool or insufficient metrics.

        Args:
            task_type: Type of task to perform
            agent_pool: Optional AgentPool with performance history
            min_importance: Minimum importance score to consider agent (default 0.5)

        Returns:
            RoutingDecision with model selection and reasoning

        Example:
            router = ModelRouter(config)
            pool = create_default_pool(config)
            decision = router.select_best_agent(TaskType.BRAINSTORM, pool)
            # Uses DyLAN metrics if available, else static routing
        """
        # Base routing decision (static)
        base_model = self.select_claude_model(task_type)
        is_opus = base_model == self.opus_model

        # No pool = use static routing
        if agent_pool is None:
            return RoutingDecision(
                model_id=base_model,
                task_type=task_type,
                reason=f"Static routing: {task_type.value} -> {'Opus' if is_opus else 'Sonnet'}",
                is_opus=is_opus,
            )

        # Get agents with performance for this task type
        task_type_str = task_type.value
        best_agents = agent_pool.select_best_for_task(task_type_str, top_k=2)

        if not best_agents:
            return RoutingDecision(
                model_id=base_model,
                task_type=task_type,
                reason="No agent metrics yet, using static routing",
                is_opus=is_opus,
            )

        # Check if best agent meets minimum importance threshold
        best = best_agents[0]
        best_importance = best.get_task_importance(task_type_str)

        if best_importance < min_importance:
            return RoutingDecision(
                model_id=base_model,
                task_type=task_type,
                reason=f"Best agent importance ({best_importance:.2f}) below threshold ({min_importance})",
                is_opus=is_opus,
            )

        # Use DyLAN-selected agent
        selected_is_opus = "opus" in best.model.lower()
        return RoutingDecision(
            model_id=best.model,
            task_type=task_type,
            reason=f"DyLAN selection: {best.agent_id} (importance={best_importance:.3f}, "
            f"success_rate={best.success_rate:.1%})",
            is_opus=selected_is_opus,
        )

    def route_for_sdk(
        self,
        agent_id: str,
        task_type: TaskType,
    ) -> str:
        """
        Select the best model ID for SDK driver invocation (V12.4).

        Args:
            agent_id: "claude" or "gemini"
            task_type: Type of task

        Returns:
            Model ID string for the SDK driver
        """
        if agent_id.lower() == "claude":
            return self.select_claude_model(task_type)
        elif agent_id.lower() == "gemini":
            return self.select_gemini_model(task_type)
        raise ValueError(f"Unknown agent: {agent_id}")

    # =========================================================================
    # Budget-Aware Routing (V12.4 COGNITIVE BOOST)
    # =========================================================================

    def apply_budget_pressure(self, warning_level: str | None) -> RoutingPolicy | None:
        """
        Adjust routing policy based on budget pressure.

        Saves the original policy on first downgrade, restores it when
        pressure is relieved (warning_level=None).

        Args:
            warning_level: None (OK), "warning" (80%+), "critical" (90%+)

        Returns:
            The applied policy, or None if no change needed
        """
        if warning_level is None:
            # Budget OK — restore original policy if it was saved
            if hasattr(self, "_original_policy"):
                self.policy = self._original_policy
                del self._original_policy
            return None

        # Save original policy on first downgrade
        if not hasattr(self, "_original_policy"):
            self._original_policy = self.policy

        if warning_level == "critical":
            # 90%+ budget: force everything to cheapest tier
            self.policy = RoutingPolicy.COST_OPTIMIZED
        elif warning_level == "warning":
            # 80%+ budget: switch to cost-optimized if not already
            if self.policy == RoutingPolicy.QUALITY_OPTIMIZED:
                self.policy = RoutingPolicy.BALANCED
            elif self.policy == RoutingPolicy.BALANCED:
                self.policy = RoutingPolicy.COST_OPTIMIZED

        return self.policy

    def select_with_budget(
        self,
        agent_id: str,
        task_type: TaskType,
        budget_pct: float = 0.0,
    ) -> str:
        """
        Select model with budget awareness.

        At >=100% budget, returns "ollama" to signal local fallback.
        At >=90%, forces LIGHT tier. Otherwise delegates to normal routing.

        Args:
            agent_id: "claude" or "gemini"
            task_type: Type of task
            budget_pct: Current budget usage as percentage (0-100+)

        Returns:
            Model ID string (may be "ollama" at budget limit)
        """
        # Hard stop: over budget -> local model only
        if budget_pct >= 100.0:
            return "ollama"

        # Critical: force cheapest cloud model
        if budget_pct >= 90.0:
            if agent_id.lower() == "claude":
                return self.haiku_model
            return self.gemini_flash_model

        # Warning: downgrade heavy -> medium
        if budget_pct >= 80.0:
            tier = self._task_tiers.get(task_type, ModelTier.MEDIUM)
            if tier == ModelTier.HEAVY:
                tier = ModelTier.MEDIUM
            if agent_id.lower() == "claude":
                return self.select_claude_by_tier(tier)
            return self.select_gemini_by_tier(tier)

        # Normal routing
        return self.route_for_sdk(agent_id, task_type)

    # =========================================================================
    # Cascade Routing (arxiv:2410.10347 - ICML 2025)
    # =========================================================================

    def route_cascade(
        self,
        agent_id: str,
        task_type: TaskType,
        *,
        confidence_threshold: float = 0.7,
        budget_pct: float = 0.0,
    ) -> CascadeRoute:
        """
        Generate a cascade routing plan: try cheap model first, escalate on low quality.

        Based on arxiv:2410.10347 (Cascade Routing, ICML 2025):
        - Try the cheapest model that could handle the task
        - If quality/confidence is below threshold, escalate to next tier
        - Stops at the most capable model or budget limit

        The caller is responsible for executing the cascade:
            route = router.route_cascade("claude", TaskType.ANALYSIS)
            for model in route.models:
                result = await driver.invoke(prompt, model=model)
                if result.quality >= route.confidence_threshold:
                    break  # Good enough

        Args:
            agent_id: "claude" or "gemini"
            task_type: Type of task
            confidence_threshold: Escalate if output quality < this (0.0-1.0)
            budget_pct: Current budget usage percentage

        Returns:
            CascadeRoute with ordered model list (cheapest first)
        """
        tier = self._task_tiers.get(task_type, ModelTier.MEDIUM)
        is_claude = agent_id.lower() == "claude"

        # Build full cascade (LIGHT -> MEDIUM -> HEAVY)
        if is_claude:
            full_cascade = [self.haiku_model, self.sonnet_model, self.opus_model]
        else:
            full_cascade = [self.gemini_flash_model, self.gemini_pro_model]

        # Budget constraints: cap the cascade
        if budget_pct >= 100.0:
            return CascadeRoute(
                models=["ollama"],
                agent_id=agent_id,
                task_type=task_type,
                confidence_threshold=confidence_threshold,
            )
        if budget_pct >= 90.0:
            # Only allow cheapest model
            return CascadeRoute(
                models=[full_cascade[0]],
                agent_id=agent_id,
                task_type=task_type,
                confidence_threshold=confidence_threshold,
            )

        # Policy constraints
        if self.policy == RoutingPolicy.QUALITY_OPTIMIZED:
            # Skip cascade, go straight to best
            return CascadeRoute(
                models=[full_cascade[-1]],
                agent_id=agent_id,
                task_type=task_type,
                confidence_threshold=confidence_threshold,
            )

        # Normal cascade: start from the tier appropriate to the task
        if tier == ModelTier.HEAVY:
            # Heavy tasks: start from medium, can escalate to heavy
            start_idx = 1 if len(full_cascade) > 2 else 0
        elif tier == ModelTier.LIGHT:
            # Light tasks: start from light, can escalate to medium
            start_idx = 0
        else:
            # Medium tasks: start from light, can escalate to medium then heavy
            start_idx = 0

        cascade = full_cascade[start_idx:]
        return CascadeRoute(
            models=cascade,
            agent_id=agent_id,
            task_type=task_type,
            confidence_threshold=confidence_threshold,
        )

    def get_routing_stats(self, agent_pool: Optional["AgentPool"] = None) -> dict:
        """
        Get routing statistics for debugging.

        Args:
            agent_pool: Optional AgentPool for metrics

        Returns:
            Dict with routing configuration and pool stats
        """
        stats = {
            "policy": self.policy.value,
            "opus_model": self.opus_model,
            "sonnet_model": self.sonnet_model,
            "haiku_model": self.haiku_model,
            "gemini_pro_model": self.gemini_pro_model,
            "gemini_flash_model": self.gemini_flash_model,
            "gemini_model": self.gemini_model,
            "opus_tasks": [t.value for t in self.opus_tasks],
            "sonnet_tasks": [t.value for t in self.sonnet_tasks],
            "task_tiers": {t.value: tier.value for t, tier in self._task_tiers.items()},
            "pool_available": agent_pool is not None,
        }

        if agent_pool:
            pool_stats = agent_pool.get_pool_stats()
            stats["pool_agents"] = pool_stats.get("agents", 0)
            stats["pool_invocations"] = pool_stats.get("total_invocations", 0)
            stats["pool_avg_importance"] = pool_stats.get("average_pool_importance", 0)

        return stats
