"""
NEXUS V9.2 - Context Scoping for Controlled Inheritance

Provides granular control over what context is passed between:
- HiveMind phases (Phase 1 -> Phase 2)
- Parent -> Spawned agents
- Model changes within same task
- Parallel vs Sequential execution

Key Insight: The problem isn't inheritance itself, it's UNCONTROLLED inheritance.
- Parallel agents should NOT share context (isolation)
- Sequential phases SHOULD inherit results (continuity)
- Spawned agents need MINIMAL context (focus)

Author: Claude (NEXUS V9.2)
Date: 2025-12-13
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class ContextScope(str, Enum):
    """
    Defines how much context an agent/phase should inherit.

    FULL: Everything (rare - only for direct continuation)
    TASK_PLUS_RESULTS: Task definition + previous results summary
    RESULTS_ONLY: Only summarized results from previous phases
    TASK_ONLY: Just the task description + relevant files
    MINIMAL: Only the immediate instruction
    FRESH: No inherited context (complete isolation)
    """

    FULL = "full"
    TASK_PLUS_RESULTS = "task_plus_results"
    RESULTS_ONLY = "results_only"
    TASK_ONLY = "task_only"
    MINIMAL = "minimal"
    FRESH = "fresh"


class InheritanceDirection(str, Enum):
    """
    Direction of context flow.

    NONE: No inheritance (parallel isolation)
    PARENT_TO_CHILD: Parent context flows to child (spawn)
    PHASE_TO_PHASE: Sequential phase inheritance
    BIDIRECTIONAL: Full sharing (debugging only)
    """

    NONE = "none"
    PARENT_TO_CHILD = "parent_to_child"
    PHASE_TO_PHASE = "phase_to_phase"
    BIDIRECTIONAL = "bidirectional"


@dataclass
class ScopedContext:
    """
    A context package with explicit scope boundaries.

    This is what gets passed to agents instead of raw prompts,
    ensuring they only see what they need.

    Attributes:
        scope: The scope level applied
        task_description: The core task (always included except FRESH)
        relevant_files: Files pertinent to this specific work
        parent_summary: Summarized findings from parent/previous phase
        full_history: Complete history (only for FULL scope)
        metadata: Additional context metadata
        session_uuid: Unique session for this scoped context
        model_context: Model-specific context (capabilities, etc.)
    """

    scope: ContextScope
    task_description: str = ""
    relevant_files: list[str] = field(default_factory=list)
    parent_summary: str = ""
    full_history: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    session_uuid: str | None = None
    model_context: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    # Token estimates for budget management
    estimated_tokens: int = 0

    def __post_init__(self):
        """Calculate token estimate after initialization."""
        if self.estimated_tokens == 0:
            self.estimated_tokens = self._estimate_tokens()

    def _estimate_tokens(self) -> int:
        """Rough token estimation (~4 chars per token)."""
        total_chars = (
            len(self.task_description)
            + len(self.parent_summary)
            + sum(len(f) for f in self.relevant_files)
            + (len(str(self.full_history)) if self.full_history else 0)
        )
        return total_chars // 4

    def to_prompt_prefix(self) -> str:
        """
        Convert scoped context to a prompt prefix.

        This is what gets prepended to the agent's instruction.
        """
        parts = []

        if self.scope == ContextScope.FRESH:
            # No context prefix for fresh sessions
            return ""

        # Task description (unless MINIMAL/FRESH/RESULTS_ONLY)
        if (
            self.scope not in [ContextScope.MINIMAL, ContextScope.FRESH, ContextScope.RESULTS_ONLY]
            and self.task_description
        ):
            parts.append(f"## Task\n{self.task_description}")

        # Relevant files
        if self.relevant_files and self.scope in [
            ContextScope.FULL,
            ContextScope.TASK_PLUS_RESULTS,
            ContextScope.TASK_ONLY,
        ]:
            files_str = ", ".join(self.relevant_files[:10])  # Limit to 10
            if len(self.relevant_files) > 10:
                files_str += f" (+{len(self.relevant_files) - 10} more)"
            parts.append(f"## Relevant Files\n{files_str}")

        # Parent summary (for inherited context)
        if self.parent_summary and self.scope in [
            ContextScope.FULL,
            ContextScope.TASK_PLUS_RESULTS,
            ContextScope.RESULTS_ONLY,
        ]:
            parts.append(f"## Previous Findings\n{self.parent_summary}")

        # Model context (capabilities reminder)
        if self.model_context:
            parts.append(f"## Your Capabilities\n{self.model_context}")

        if not parts:
            return ""

        return "\n\n".join(parts) + "\n\n---\n\n"

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage/logging."""
        return {
            "scope": self.scope.value,
            "task_description": self.task_description[:200] + "..."
            if len(self.task_description) > 200
            else self.task_description,
            "relevant_files": self.relevant_files,
            "parent_summary": self.parent_summary[:500] + "..."
            if len(self.parent_summary) > 500
            else self.parent_summary,
            "has_full_history": len(self.full_history) > 0,
            "history_items": len(self.full_history),
            "session_uuid": self.session_uuid,
            "estimated_tokens": self.estimated_tokens,
            "created_at": self.created_at,
        }


@dataclass
class ContextScopePolicy:
    """
    Policy defining context inheritance rules for different scenarios.

    Used by HiveMindOrchestrator to determine what context to pass.
    """

    # Phase-to-phase inheritance
    phase_inheritance: dict[str, ContextScope] = field(
        default_factory=lambda: {
            "analysis_to_debate": ContextScope.TASK_PLUS_RESULTS,
            "debate_to_architecture": ContextScope.TASK_PLUS_RESULTS,
            "architecture_to_execution": ContextScope.TASK_PLUS_RESULTS,
            "execution_to_diagnosis": ContextScope.FULL,  # Needs full context for debugging
            "diagnosis_to_retry": ContextScope.TASK_PLUS_RESULTS,
            "execution_to_consolidation": ContextScope.RESULTS_ONLY,
        }
    )

    # Parallel agent isolation
    parallel_scope: ContextScope = ContextScope.TASK_ONLY

    # Spawned agent scope
    spawn_scope: ContextScope = ContextScope.TASK_ONLY

    # Model change behavior
    invalidate_on_model_change: bool = True
    model_change_scope: ContextScope = ContextScope.TASK_PLUS_RESULTS

    def get_phase_scope(self, from_phase: str, to_phase: str) -> ContextScope:
        """Get scope for phase transition."""
        key = f"{from_phase}_to_{to_phase}"
        return self.phase_inheritance.get(key, ContextScope.TASK_PLUS_RESULTS)


# Default policies for different task complexities
SCOPE_POLICIES = {
    "TRIVIAL": ContextScopePolicy(
        parallel_scope=ContextScope.FRESH,  # No overhead for simple tasks
        spawn_scope=ContextScope.MINIMAL,
        invalidate_on_model_change=False,
    ),
    "SIMPLE": ContextScopePolicy(
        parallel_scope=ContextScope.TASK_ONLY,
        spawn_scope=ContextScope.TASK_ONLY,
        invalidate_on_model_change=False,
    ),
    "MODERATE": ContextScopePolicy(
        parallel_scope=ContextScope.TASK_ONLY,
        spawn_scope=ContextScope.TASK_PLUS_RESULTS,
        invalidate_on_model_change=True,
    ),
    "COMPLEX": ContextScopePolicy(
        parallel_scope=ContextScope.TASK_ONLY,
        spawn_scope=ContextScope.TASK_PLUS_RESULTS,
        invalidate_on_model_change=True,
    ),
    "EXPERT": ContextScopePolicy(
        parallel_scope=ContextScope.TASK_ONLY,
        spawn_scope=ContextScope.FULL,  # Experts need full context
        invalidate_on_model_change=True,
        model_change_scope=ContextScope.FULL,
    ),
}


def get_scope_policy(complexity: str) -> ContextScopePolicy:
    """Get scope policy for task complexity level."""
    return SCOPE_POLICIES.get(complexity.upper(), SCOPE_POLICIES["MODERATE"])
