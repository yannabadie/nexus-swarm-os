"""
NEXUS Session Management Module.

V9.7.1 - Context Bleeding Fix (Improved)

This module provides session isolation for parallel task execution
without context bleeding between agents.

Key Components:
- SessionWorkspaceManager: Isolated workspaces per session/task
- HomeIsolator: HOME environment spoofing for Gemini session isolation (V9.7.1)

V9.7.1 HOME Spoofing (replaces V9.7 CWD Isolation):
- V9.7 CWD Isolation caused "ghost files" (writes to wrong directory)
- V9.7.1 uses HOME spoofing: CWD stays at project root, HOME is isolated
- Gemini CLI stores sessions in ~/.gemini/tmp/<hash(cwd)>/chats/
- Different HOME = Different session storage = Isolation without ghost files

Usage:
    from core.infrastructure.session import SessionWorkspaceManager, HomeIsolator

    # Create managers
    manager = SessionWorkspaceManager(workspace_path)

    # Get isolated environment for Gemini subprocess (V9.7.1)
    isolated_env = manager.get_isolated_env("task_123_lead", "swarm")

    # Pass to subprocess (CWD stays at project root!)
    subprocess.Popen(cmd, env=isolated_env, cwd=workspace_path)

    # Cleanup after task completion
    manager.cleanup_workspace("task_123_lead", "swarm")
"""

from .home_isolator import HomeIsolator

# V12.4 COGNITIVE BOOST: Session Analytics
from .session_analytics import (
    AgentAction,
    AnalyticsStats,
    PhaseMetric,
    SessionAnalytics,
    SessionMetrics,
    get_session_analytics,
    reset_session_analytics,
)

# V12.4 COGNITIVE BOOST: Session Efficiency Scorecard
from .session_efficiency_scorecard import (
    MAX_SESSION_RECORDS,
    ScorecardStats,
    SessionEfficiencyScorecard,
    SessionProfile,
    SessionRecord,
    get_session_scorecard,
    reset_session_scorecard,
)

# V12.4: State Recovery Manager
from .state_recovery import (
    RecoveryResult,
    RecoveryStats,
    SnapshotReason,
    StateRecoveryManager,
    StateSnapshot,
    get_recovery_manager,
    reset_recovery_manager,
)
from .workspace_manager import (
    SessionWorkspaceManager,
    get_workspace_manager,
    reset_workspace_manager,
)

__all__ = [
    "SessionWorkspaceManager",
    "get_workspace_manager",
    "reset_workspace_manager",
    "HomeIsolator",
    # V12.4: State Recovery
    "StateRecoveryManager",
    "StateSnapshot",
    "RecoveryResult",
    "RecoveryStats",
    "SnapshotReason",
    "get_recovery_manager",
    "reset_recovery_manager",
    # V12.4 COGNITIVE BOOST: Session Analytics
    "SessionAnalytics",
    "PhaseMetric",
    "AgentAction",
    "SessionMetrics",
    "AnalyticsStats",
    "get_session_analytics",
    "reset_session_analytics",
    # V12.4 COGNITIVE BOOST: Session Efficiency Scorecard
    "SessionRecord",
    "SessionProfile",
    "ScorecardStats",
    "SessionEfficiencyScorecard",
    "get_session_scorecard",
    "reset_session_scorecard",
    "MAX_SESSION_RECORDS",
]
