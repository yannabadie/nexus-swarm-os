"""
Executor Registry - V9.6 Extracted

Registry of all mode executors and factory function.
"""

from pathlib import Path

from ..collaboration_modes import CollaborationMode
from .base import ModeExecutor

# Lazy imports to avoid circular dependencies
_executor_classes = None


def _load_executor_classes():
    """Lazily load executor classes to avoid circular imports."""
    global _executor_classes
    if _executor_classes is None:
        from .lead_support_executor import LeadSupportExecutor
        from .parallel_executor import ParallelExecutor
        from .ping_pong_executor import PingPongExecutor
        from .red_blue_executor import RedBlueExecutor
        from .sequential_executor import SequentialExecutor
        from .specialist_executor import SpecialistExecutor

        _executor_classes = {
            CollaborationMode.PARALLEL: ParallelExecutor,
            CollaborationMode.SEQUENTIAL: SequentialExecutor,
            CollaborationMode.SPECIALIST: SpecialistExecutor,
            CollaborationMode.LEAD_SUPPORT: LeadSupportExecutor,
            CollaborationMode.PING_PONG: PingPongExecutor,
            CollaborationMode.RED_BLUE: RedBlueExecutor,
        }
    return _executor_classes


# Registry of executor instances (created lazily)
_executor_instances: dict[CollaborationMode, ModeExecutor] = {}


def get_executor(mode: CollaborationMode, workspace_path: Path | None = None) -> ModeExecutor:
    """
    Get executor for a collaboration mode.

    V7.9: PingPongExecutor now accepts workspace_path for artifact verification.

    Args:
        mode: Collaboration mode
        workspace_path: Optional workspace path for artifact verification

    Returns:
        ModeExecutor instance
    """
    classes = _load_executor_classes()

    # PingPong needs workspace_path, create new instance each time
    if mode == CollaborationMode.PING_PONG:
        return classes[mode](workspace_path=workspace_path)

    # For other modes, use cached instances
    if mode not in _executor_instances:
        _executor_instances[mode] = classes[mode]()

    return _executor_instances[mode]


def get_executor_registry() -> dict[CollaborationMode, ModeExecutor]:
    """
    Get the full executor registry.

    Creates instances lazily on first access.

    Returns:
        Dict mapping CollaborationMode to ModeExecutor instances
    """
    classes = _load_executor_classes()

    # Ensure all instances are created
    for mode, cls in classes.items():
        if mode not in _executor_instances:
            if mode == CollaborationMode.PING_PONG:
                _executor_instances[mode] = cls()
            else:
                _executor_instances[mode] = cls()

    return _executor_instances.copy()


# Alias for backward compatibility
EXECUTOR_REGISTRY = property(lambda self: get_executor_registry())
