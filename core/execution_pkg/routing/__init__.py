"""
NEXUS V7 Model Routing Module

Routes tasks to appropriate models based on complexity and task type.
Supports Opus/Sonnet selection for Claude and model variants for Gemini.
"""

# V12.4 COGNITIVE BOOST: Cascaded Router (arxiv:2502.11133)
from .cascaded_router import (
    AgentRouting,
    CascadedRouter,
    CascadedRoutingDecision,
    RouterStats,
    RoutingStage,
    get_cascaded_router,
    reset_cascaded_router,
)

# V12.4: Decision Cache
from .decision_cache import (
    CachedDecision,
    DecisionCacheStats,
    DecisionOutcome,
    RoutingDecisionCache,
    get_decision_cache,
    reset_decision_cache,
)
from .model_router import (
    CascadeRoute,
    ModelRouter,
    ModelTier,
    RoutingDecision,
    RoutingPolicy,
    TaskType,
)

# V12.4: Resource Optimizer
from .resource_optimizer import (
    ModelSpec,
    OptimizationDecision,
    OptimizationReport,
    ResourceOptimizer,
    UsageRecord,
    get_resource_optimizer,
    reset_resource_optimizer,
)
from .routing_effectiveness_analyzer import (
    AnalyzerStats as RoutingAnalyzerStats,
)

# V12.4 COGNITIVE BOOST: Routing Effectiveness Analyzer
from .routing_effectiveness_analyzer import (
    PolicyMetrics,
    RoutingDecisionRecord,
    RoutingEffectivenessAnalyzer,
    get_routing_analyzer,
    reset_routing_analyzer,
)

__all__ = [
    "ModelRouter",
    "TaskType",
    "RoutingDecision",
    "RoutingPolicy",
    "ModelTier",
    "CascadeRoute",
    # V12.4: Resource Optimizer
    "ResourceOptimizer",
    "ModelSpec",
    "OptimizationDecision",
    "OptimizationReport",
    "UsageRecord",
    "get_resource_optimizer",
    "reset_resource_optimizer",
    # V12.4: Decision Cache
    "RoutingDecisionCache",
    "CachedDecision",
    "DecisionOutcome",
    "DecisionCacheStats",
    "get_decision_cache",
    "reset_decision_cache",
    # V12.4 COGNITIVE BOOST: Routing Effectiveness Analyzer
    "RoutingEffectivenessAnalyzer",
    "RoutingDecisionRecord",
    "PolicyMetrics",
    "RoutingAnalyzerStats",
    "get_routing_analyzer",
    "reset_routing_analyzer",
    # V12.4 COGNITIVE BOOST: Cascaded Router (arxiv:2502.11133)
    "CascadedRouter",
    "CascadedRoutingDecision",
    "AgentRouting",
    "RoutingStage",
    "RouterStats",
    "get_cascaded_router",
    "reset_cascaded_router",
]
