"""
NEXUS V9.1 - Agents Module

Centralized agent management, registry, and services.
"""

# V12.4 Agent Lifecycle
from .agent_lifecycle import (
    AgentHealthSnapshot,
    AgentLifecycleManager,
    LifecycleEvent,
    LifecycleStats,
    RetirementPolicy,
    get_lifecycle_manager,
    reset_lifecycle_manager,
)

# V12.4 Capability Profiler
from .capability_profiler import (
    KNOWN_CAPABILITIES,
    AgentProfile,
    CapabilityProfiler,
    CapabilityRecord,
    MatchResult,
)
from .service import (
    AgentInfo,
    AgentService,
    PoolStats,
    SpawnResult,
)
from .unified_registry import (
    AgentCapability,
    AgentDescriptor,
    AgentProvider,
    DriverProtocol,
    UnifiedAgentRegistry,
    get_registry,
)

__all__ = [
    # Registry
    "UnifiedAgentRegistry",
    "AgentDescriptor",
    "AgentProvider",
    "AgentCapability",
    "DriverProtocol",
    "get_registry",
    # Service (V9.1)
    "AgentService",
    "SpawnResult",
    "AgentInfo",
    "PoolStats",
    # V12.4 Capability Profiler
    "CapabilityProfiler",
    "AgentProfile",
    "CapabilityRecord",
    "MatchResult",
    "KNOWN_CAPABILITIES",
    # V12.4 Agent Lifecycle
    "AgentLifecycleManager",
    "RetirementPolicy",
    "AgentHealthSnapshot",
    "LifecycleEvent",
    "LifecycleStats",
    "get_lifecycle_manager",
    "reset_lifecycle_manager",
]
