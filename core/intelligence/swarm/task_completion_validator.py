"""
Task Completion Validator - V7.9 Fix for Premature FINISHED Signal

This module validates that a task is ACTUALLY complete before accepting
an agent's "FINISHED" claim. Prevents premature termination.

Validation Layers:
1. Keyword Detection (basic) - FINISHED, DONE in response
2. Artifact Verification - Files mentioned actually exist
3. Semantic Completion Check - Did the agent address the task?
4. Tool Usage Validation - Were appropriate tools used for the task type?
5. V10 FIX F13: Task Requirement Alignment - Are task requirements addressed?

Usage:
    validator = TaskCompletionValidator(workspace_path)
    is_valid, reason = validator.validate_completion(
        task_input="Fix the auth bug",
        agent_response="I fixed the bug. FINISHED.",
        task_analysis=analysis,
        tool_results=[...]
    )
"""

import re
from dataclasses import dataclass
from pathlib import Path

from core.utils.artifact_verifier import ArtifactVerifier

from .task_analyzer import TaskAnalysis, TaskComplexity, TaskDomain


@dataclass
class CompletionCriteria:
    """Expected completion criteria based on task type."""

    requires_file_changes: bool = False
    requires_code_execution: bool = False
    requires_test_validation: bool = False
    requires_multiple_agents: bool = False
    requires_user_confirmation: bool = False
    min_tool_calls: int = 0
    expected_artifacts: list[str] = None

    def __post_init__(self):
        if self.expected_artifacts is None:
            self.expected_artifacts = []


@dataclass
class ValidationResult:
    """Result of completion validation."""

    is_valid: bool
    confidence: float  # 0.0 to 1.0
    reason: str
    missing_criteria: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "confidence": round(self.confidence, 2),
            "reason": self.reason,
            "missing_criteria": self.missing_criteria,
            "warnings": self.warnings,
        }


class TaskCompletionValidator:
    """
    Validates that a task is actually complete before accepting FINISHED signal.

    Prevents false positives where agents claim completion prematurely.
    """

    # Keywords that signal completion (case-insensitive)
    COMPLETION_KEYWORDS = {"finished", "done", "complete", "completed", "task complete"}

    # Keywords that signal ongoing work (should NOT be finished)
    ONGOING_KEYWORDS = {
        "will",
        "going to",
        "next step",
        "todo",
        "remaining",
        "need to",
        "should",
        "plan to",
        "working on",
    }

    # Keywords indicating actual work was done
    WORK_DONE_KEYWORDS = {
        "created",
        "modified",
        "updated",
        "fixed",
        "implemented",
        "added",
        "removed",
        "refactored",
        "wrote",
        "edited",
    }

    # V10 FIX F13: Action verbs that indicate task requirements
    ACTION_VERBS = {
        "create",
        "write",
        "implement",
        "add",
        "fix",
        "update",
        "modify",
        "delete",
        "remove",
        "refactor",
        "test",
        "validate",
        "check",
        "build",
        "deploy",
        "configure",
        "setup",
        "install",
        "migrate",
        "analyze",
        "review",
        "audit",
        "debug",
        "optimize",
        "document",
    }

    # V10 FIX F13: Minimum semantic alignment score (0.0-1.0)
    SEMANTIC_ALIGNMENT_THRESHOLD = 0.3

    def __init__(self, workspace_path: Path | None = None):
        """
        Initialize validator.

        Args:
            workspace_path: Path to workspace for artifact verification
        """
        self.workspace_path = Path(workspace_path) if workspace_path else Path.cwd()
        self.artifact_verifier = ArtifactVerifier(self.workspace_path)

    def validate_completion(
        self, task_input: str, agent_response: str, task_analysis: TaskAnalysis, tool_results: list[dict] | None = None
    ) -> ValidationResult:
        """
        Validate if task is actually complete.

        Args:
            task_input: Original task description
            agent_response: Agent's final response claiming completion
            task_analysis: Analysis of the task
            tool_results: Results from tool executions during the task

        Returns:
            ValidationResult with validation details
        """
        tool_results = tool_results or []
        response_lower = agent_response.lower()

        # Get criteria based on task analysis
        criteria = self._get_completion_criteria(task_analysis)

        missing_criteria = []
        warnings = []
        checks_passed = 0
        total_checks = 0

        # Check 1: Completion keyword present
        total_checks += 1
        has_completion_keyword = any(kw in response_lower for kw in self.COMPLETION_KEYWORDS)
        if has_completion_keyword:
            checks_passed += 1
        else:
            warnings.append("No explicit completion signal in response")

        # Check 2: No ongoing work indicators
        total_checks += 1
        has_ongoing = any(kw in response_lower for kw in self.ONGOING_KEYWORDS)
        if not has_ongoing:
            checks_passed += 1
        else:
            missing_criteria.append("Response contains future work indicators")

        # Check 3: Work was actually done
        total_checks += 1
        has_work_done = any(kw in response_lower for kw in self.WORK_DONE_KEYWORDS)
        if has_work_done:
            checks_passed += 1
        else:
            warnings.append("No evidence of actual work performed")

        # Check 4: Artifact verification (for file-related tasks)
        if criteria.requires_file_changes:
            total_checks += 1
            artifacts_ok, successes, failures = self.artifact_verifier.verify_from_content(agent_response)
            if artifacts_ok:
                checks_passed += 1
            else:
                missing_criteria.append(f"Artifact verification failed: {failures}")

        # Check 5: Tool usage validation
        if criteria.min_tool_calls > 0:
            total_checks += 1
            actual_tool_calls = len(tool_results)
            if actual_tool_calls >= criteria.min_tool_calls:
                checks_passed += 1
            else:
                missing_criteria.append(
                    f"Expected at least {criteria.min_tool_calls} tool calls, got {actual_tool_calls}"
                )

        # Check 6: Task complexity alignment
        total_checks += 1
        complexity_aligned = self._check_complexity_alignment(task_analysis, agent_response, tool_results)
        if complexity_aligned:
            checks_passed += 1
        else:
            missing_criteria.append(f"Response depth doesn't match {task_analysis.complexity.name} complexity")

        # V10 FIX F13: Check 7 - Semantic alignment (task requirements addressed?)
        total_checks += 1
        alignment_score, unaddressed_reqs = self._calculate_semantic_alignment(task_input, agent_response)
        if alignment_score >= self.SEMANTIC_ALIGNMENT_THRESHOLD:
            checks_passed += 1
        else:
            missing_criteria.append(f"Semantic alignment too low ({alignment_score:.0%}): {unaddressed_reqs[:2]}")

        # Calculate confidence
        confidence = checks_passed / total_checks if total_checks > 0 else 0.0

        # Determine validity based on complexity threshold
        threshold = self._get_confidence_threshold(task_analysis.complexity)
        is_valid = confidence >= threshold and len(missing_criteria) == 0

        # Build reason
        if is_valid:
            reason = f"Task completion validated ({checks_passed}/{total_checks} checks passed)"
        else:
            reason = f"Completion validation failed: {'; '.join(missing_criteria)}"

        return ValidationResult(
            is_valid=is_valid,
            confidence=confidence,
            reason=reason,
            missing_criteria=missing_criteria,
            warnings=warnings,
        )

    def _get_completion_criteria(self, analysis: TaskAnalysis) -> CompletionCriteria:
        """Get completion criteria based on task analysis."""
        criteria = CompletionCriteria()

        # Complexity-based criteria
        if analysis.complexity in [TaskComplexity.COMPLEX, TaskComplexity.EXPERT]:
            criteria.min_tool_calls = 3
            criteria.requires_multiple_agents = True
        elif analysis.complexity == TaskComplexity.MODERATE:
            criteria.min_tool_calls = 1

        # Domain-based criteria
        if TaskDomain.CODING in analysis.domains:
            criteria.requires_file_changes = True
            criteria.min_tool_calls = max(criteria.min_tool_calls, 2)

        if TaskDomain.TESTING in analysis.domains:
            criteria.requires_test_validation = True
            criteria.requires_code_execution = True

        if TaskDomain.DEBUGGING in analysis.domains:
            criteria.requires_code_execution = True

        return criteria

    def _check_complexity_alignment(self, analysis: TaskAnalysis, response: str, tool_results: list[dict]) -> bool:
        """Check if response depth matches task complexity."""
        response_length = len(response)
        tool_count = len(tool_results)

        if analysis.complexity == TaskComplexity.TRIVIAL:
            # Trivial tasks can be short
            return True

        elif analysis.complexity == TaskComplexity.MODERATE:
            # Moderate tasks need some substance
            return response_length > 100 or tool_count > 0

        elif analysis.complexity == TaskComplexity.COMPLEX:
            # Complex tasks need significant response and tools
            return response_length > 300 and tool_count >= 2

        elif analysis.complexity == TaskComplexity.EXPERT:
            # Expert tasks need comprehensive work
            return response_length > 500 and tool_count >= 3

        return True

    def _get_confidence_threshold(self, complexity: TaskComplexity) -> float:
        """Get minimum confidence threshold based on complexity."""
        thresholds = {
            TaskComplexity.TRIVIAL: 0.5,
            TaskComplexity.MODERATE: 0.6,
            TaskComplexity.COMPLEX: 0.7,
            TaskComplexity.EXPERT: 0.8,
        }
        return thresholds.get(complexity, 0.6)

    # =========================================================================
    # V10 FIX F13: Semantic Alignment Validation
    # =========================================================================

    def _extract_task_requirements(self, task_input: str) -> dict[str, set[str]]:
        """
        Extract key requirements from task description.

        V10 FIX F13: Goes beyond keywords to extract semantic requirements.

        Returns:
            Dict with 'actions', 'targets', 'key_terms'
        """
        task_lower = task_input.lower()
        words = set(re.findall(r"\b\w+\b", task_lower))

        # Extract action verbs from task
        actions = words & self.ACTION_VERBS

        # Extract potential targets (nouns after action verbs)
        # Simple heuristic: words near action verbs
        targets = set()
        for match in re.finditer(r"\b(" + "|".join(self.ACTION_VERBS) + r")\s+(?:the\s+)?(\w+)", task_lower):
            targets.add(match.group(2))

        # Extract file patterns
        file_patterns = set(re.findall(r"\b[\w/\\]+\.\w{1,5}\b", task_input))
        targets.update(file_patterns)

        # Extract quoted strings (specific requirements)
        quoted = set(re.findall(r'["\']([^"\']+)["\']', task_input))
        key_terms = set()
        for q in quoted:
            key_terms.update(re.findall(r"\b\w+\b", q.lower()))

        # Add important nouns (excluding common words)
        common_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "can",
            "this",
            "that",
            "these",
            "those",
            "it",
            "its",
            "to",
            "for",
            "in",
            "on",
            "at",
            "by",
            "with",
            "from",
            "of",
            "and",
            "or",
        }
        key_terms.update(words - common_words - self.ACTION_VERBS)

        return {"actions": actions, "targets": targets, "key_terms": key_terms}

    def _calculate_semantic_alignment(self, task_input: str, response: str) -> tuple[float, list[str]]:
        """
        Calculate semantic alignment between task and response.

        V10 FIX F13: Checks if response addresses task requirements.

        Returns:
            Tuple of (alignment_score, unaddressed_requirements)
        """
        requirements = self._extract_task_requirements(task_input)
        response_lower = response.lower()
        response_words = set(re.findall(r"\b\w+\b", response_lower))

        unaddressed = []
        scores = []

        # Check actions: Were requested actions performed?
        if requirements["actions"]:
            # Look for past tense or related words
            action_matches = 0
            for action in requirements["actions"]:
                # Check action or its past tense variants
                past_forms = {
                    action,
                    action + "d",
                    action + "ed",
                    action[:-1] + "ied" if action.endswith("y") else action,
                }
                if any(form in response_lower for form in past_forms):
                    action_matches += 1
                else:
                    unaddressed.append(f"action:{action}")

            action_score = action_matches / len(requirements["actions"])
            scores.append(action_score * 2)  # Weight actions higher

        # Check targets: Were targets mentioned?
        if requirements["targets"]:
            target_matches = sum(1 for t in requirements["targets"] if t in response_lower)
            target_score = target_matches / len(requirements["targets"])
            scores.append(target_score)
            if target_score < 0.5:
                unaddressed.append(f"targets:{list(requirements['targets'] - response_words)[:3]}")

        # Check key terms overlap
        if requirements["key_terms"]:
            overlap = requirements["key_terms"] & response_words
            term_score = len(overlap) / len(requirements["key_terms"])
            scores.append(term_score)

        # Calculate weighted average
        if scores:
            alignment = sum(scores) / len(scores)
        else:
            alignment = 0.5  # No requirements extracted, neutral score

        return min(alignment, 1.0), unaddressed

    def quick_validate(self, response: str) -> tuple[bool, str]:
        """
        Quick validation - just keyword checking.

        Use this for fast feedback, use validate_completion() for thorough check.

        Args:
            response: Agent response text

        Returns:
            Tuple of (has_completion_signal, reason)
        """
        response_lower = response.lower()

        # Check for completion signals
        has_completion = any(kw in response_lower for kw in self.COMPLETION_KEYWORDS)

        # Check for ongoing work signals (red flag)
        has_ongoing = any(kw in response_lower for kw in self.ONGOING_KEYWORDS)

        if has_completion and not has_ongoing:
            return True, "Completion signal found without ongoing work indicators"
        elif has_completion and has_ongoing:
            return False, "Mixed signals: completion claimed but ongoing work detected"
        else:
            return False, "No completion signal found"


def get_adaptive_max_rounds(complexity: TaskComplexity) -> int:
    """
    Get adaptive max_rounds based on task complexity.

    V7.9: max_rounds should scale with task difficulty.

    Args:
        complexity: Task complexity level

    Returns:
        Appropriate max_rounds for the complexity
    """
    rounds_by_complexity = {
        TaskComplexity.TRIVIAL: 3,  # Quick tasks
        TaskComplexity.MODERATE: 6,  # Standard tasks (current default)
        TaskComplexity.COMPLEX: 10,  # Complex tasks need more iterations
        TaskComplexity.EXPERT: 15,  # Expert tasks need thorough work
    }
    return rounds_by_complexity.get(complexity, 6)
