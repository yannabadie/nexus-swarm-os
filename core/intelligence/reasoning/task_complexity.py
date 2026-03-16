"""
NEXUS V12.4 - Task Complexity Estimation (P5.5)

Fast heuristic-based task complexity estimation to optimize metacognitive monitoring.

Problem:
- MetacognitiveMonitor runs TF-IDF scoring on EVERY step, even trivial commands
- 15-30% latency overhead on simple queries (/help, /status, short factual queries)

Solution:
- Classify tasks into 4 complexity levels (TRIVIAL to COMPLEX)
- Bypass metacognition for TRIVIAL/SIMPLE tasks
- Only run deep monitoring for MODERATE+ complexity

Heuristics (no LLM calls, <1ms overhead):
1. Command pattern: / prefix -> TRIVIAL
2. Length: <30 chars + no complex verbs -> TRIVIAL
3. Simple queries: single factual request -> SIMPLE
4. Multi-step: "then", "after", "also" -> MODERATE
5. Complex verbs: "analyze", "compare", "design" -> MODERATE+

Sprint 2 (P5.5): Adaptive Metacognition
Ref: MASTER_ACTION_PLAN.md P5.5, nexus-audit-nxcg-1.md P2.1
"""

from enum import IntEnum


class TaskComplexity(IntEnum):
    """
    Task complexity levels for adaptive processing.

    Higher values indicate more complex tasks requiring deeper monitoring.
    """

    TRIVIAL = 0  # Commands, <30 chars, no analysis required
    SIMPLE = 1  # Single-step factual queries, straightforward requests
    MODERATE = 2  # Multi-step workflows, requires context analysis
    COMPLEX = 3  # Multi-agent debate, architectural decisions, evolution


# Keywords indicating task complexity
COMPLEX_VERBS: set[str] = {
    "analyze",
    "analyse",
    "compare",
    "evaluate",
    "design",
    "architect",
    "refactor",
    "optimize",
    "debug",
    "investigate",
    "research",
    "implement",
    "create",
    "build",
    "develop",
    "evolve",
    "mutate",
}

MODERATE_INDICATORS: set[str] = {
    "then",
    "after",
    "also",
    "and",
    "while",
    "if",
    "when",
    "review",
    "check",
    "validate",
    "verify",
    "test",
    "update",
}

TRIVIAL_COMMANDS: set[str] = {
    "/help",
    "/status",
    "/stats",
    "/reset",
    "/clear",
    "/exit",
    "/list",
    "/show",
    "/get",
    "/ping",
    "/version",
    "/info",
}


def estimate_complexity(task: str) -> TaskComplexity:
    """
    Estimate task complexity using fast heuristics (no LLM calls).

    Args:
        task: User task input string

    Returns:
        TaskComplexity level (TRIVIAL to COMPLEX)

    Examples:
        >>> estimate_complexity("/help")
        TaskComplexity.TRIVIAL

        >>> estimate_complexity("What is NEXUS?")
        TaskComplexity.SIMPLE

        >>> estimate_complexity("Analyze the auth module and suggest improvements")
        TaskComplexity.COMPLEX

    Heuristics (checked in order):
    1. Known trivial command -> TRIVIAL
    2. Short text (<30 chars) without complex verbs -> TRIVIAL
    3. Contains complex verbs (analyze, design, etc.) -> COMPLEX
    4. Contains moderate indicators (then, also, etc.) -> MODERATE
    5. Default for longer queries -> SIMPLE
    """
    if not task or not task.strip():
        return TaskComplexity.TRIVIAL

    task_lower = task.strip().lower()

    # 1. Known trivial commands
    if task_lower in TRIVIAL_COMMANDS:
        return TaskComplexity.TRIVIAL

    # 2. Check for command-like patterns (starts with /)
    if task_lower.startswith("/"):
        return TaskComplexity.TRIVIAL

    # 3. Check for complex verbs FIRST (analysis, design work)
    # These override length heuristics
    if any(verb in task_lower for verb in COMPLEX_VERBS):
        # If also has multi-step indicators, it's VERY complex
        if any(indicator in task_lower for indicator in MODERATE_INDICATORS):
            return TaskComplexity.COMPLEX
        return TaskComplexity.COMPLEX

    # 4. Check for moderate complexity (multi-step, conditional)
    # This also overrides length heuristics
    if any(indicator in task_lower for indicator in MODERATE_INDICATORS):
        return TaskComplexity.MODERATE

    # 5. Length-based heuristics (only if no keywords found)
    if len(task) < 30:
        # Very short without complex markers -> TRIVIAL
        return TaskComplexity.TRIVIAL
    elif len(task) < 100:
        # Moderate length, single-step -> SIMPLE
        return TaskComplexity.SIMPLE
    else:
        # Long query without markers -> likely multi-context, MODERATE
        return TaskComplexity.MODERATE


def should_monitor_metacognition(task: str, threshold: TaskComplexity = TaskComplexity.MODERATE) -> bool:
    """
    Determine if metacognitive monitoring should be enabled for this task.

    Args:
        task: User task input
        threshold: Minimum complexity to trigger monitoring (default: MODERATE)

    Returns:
        True if task complexity >= threshold, False otherwise

    Usage:
        >>> if should_monitor_metacognition(task):
        ...     anomaly = metacog_monitor.score_step(...)
    """
    return estimate_complexity(task) >= threshold


# Module exports
__all__ = [
    "TaskComplexity",
    "estimate_complexity",
    "should_monitor_metacognition",
]
