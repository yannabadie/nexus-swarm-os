"""
NEXUS V9.1 - Bootstrap Module

Components:
- AutoBootstrap: Generates NEXUS.md when deployed to a new project
- SpawnedAgentLoader: Discovers spawned agents from workspace/agents/
- BootstrapService: Service layer for bootstrap operations (V9.1)
- SpinoffService: Service layer for specialization/spinoff operations (V9.1)
"""

from .agent_loader import SpawnedAgentConfig, SpawnedAgentLoader, discover_and_register_spawned_agents
from .auto_bootstrap import AutoBootstrap, ProjectAnalysis

# V9.1: Service Layer
from .service import (
    BootstrapService,
    SpinoffService,
    _get_bootstrap_service,
    _get_spinoff_service,
)

# ServiceResult comes from core.observability.telemetry.service (single source of truth)
# V12.4 COGNITIVE BOOST: Startup Analytics
from .startup_analytics import (
    BootStepRecord,
    ComponentProfile,
    StartupAnalytics,
    StartupStats,
    get_startup_analytics,
    reset_startup_analytics,
)

__all__ = [
    "AutoBootstrap",
    "ProjectAnalysis",
    "SpawnedAgentLoader",
    "SpawnedAgentConfig",
    "discover_and_register_spawned_agents",
    # V9.1: Service Layer
    "BootstrapService",
    "SpinoffService",
    "_get_bootstrap_service",
    "_get_spinoff_service",
    # V12.4 COGNITIVE BOOST: Startup Analytics
    "StartupAnalytics",
    "BootStepRecord",
    "ComponentProfile",
    "StartupStats",
    "get_startup_analytics",
    "reset_startup_analytics",
]
