"""
NEXUS V12.4 - Adaptive Prompt Technique Selector

Dynamically selects the optimal prompting technique(s) for each task
based on task clustering and historical effectiveness.

Based on: Automatic Prompt Generation via Adaptive Selection (arXiv:2510.18162)

Instead of fixed prompt templates, NEXUS adapts the prompting strategy:
- Coding tasks -> decomposition + step-by-step
- Research tasks -> chain-of-thought + web guidance
- Security reviews -> role-playing (red-team) + self-consistency
- Debugging -> few-shot + decomposition

Usage:
    selector = get_technique_selector()
    techniques = selector.select("Fix the auth timeout bug", domains=["debugging"])
    enhanced_prompt = selector.compose_prompt(base_prompt, techniques)
    # ... after task completes:
    selector.record_outcome(techniques, quality=0.9)
"""

import json
import logging
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


# =============================================================================
# Prompt Techniques
# =============================================================================


class PromptTechnique(str, Enum):
    """Available prompting techniques."""

    CHAIN_OF_THOUGHT = "cot"
    FEW_SHOT = "few_shot"
    DECOMPOSITION = "decomposition"
    SELF_CONSISTENCY = "self_consistency"
    ROLE_PLAYING = "role_playing"
    STEP_BY_STEP = "step_by_step"


# Technique instruction templates injected into prompts
TECHNIQUE_INSTRUCTIONS: dict[PromptTechnique, str] = {
    PromptTechnique.CHAIN_OF_THOUGHT: (
        "Think through this step by step, showing your reasoning chain. "
        "Explain each inference before reaching a conclusion."
    ),
    PromptTechnique.FEW_SHOT: (
        "Consider similar past examples to guide your approach. Apply patterns from analogous situations."
    ),
    PromptTechnique.DECOMPOSITION: (
        "Break this task into smaller, independent sub-tasks. Solve each sub-task separately, then combine the results."
    ),
    PromptTechnique.SELF_CONSISTENCY: (
        "Generate multiple independent solutions, then compare them. "
        "Choose the answer that appears most consistently across approaches."
    ),
    PromptTechnique.ROLE_PLAYING: (
        "Approach this as a domain expert would. Consider adversarial scenarios, "
        "edge cases, and potential failure modes from a specialist perspective."
    ),
    PromptTechnique.STEP_BY_STEP: (
        "Follow a structured, sequential process. Complete each step fully "
        "before moving to the next. Verify each step's output."
    ),
}


# =============================================================================
# Task Clusters
# =============================================================================


@dataclass
class TaskCluster:
    """A cluster of task types with associated effective techniques."""

    name: str
    keywords: list[str]  # Semantic anchor words
    techniques: list[tuple[str, float]]  # (technique_value, efficacy)
    description: str = ""

    def keyword_score(self, text: str) -> float:
        """Score how well text matches this cluster's keywords."""
        text_lower = text.lower()
        hits = sum(1 for kw in self.keywords if kw in text_lower)
        return hits / max(len(self.keywords), 1)


def _default_clusters() -> list[TaskCluster]:
    """Initialize default task clusters from prompt engineering knowledge."""
    return [
        TaskCluster(
            name="coding",
            keywords=["code", "implement", "function", "class", "module", "refactor", "write", "create"],
            techniques=[
                (PromptTechnique.DECOMPOSITION.value, 0.9),
                (PromptTechnique.STEP_BY_STEP.value, 0.8),
            ],
            description="Code implementation and refactoring tasks",
        ),
        TaskCluster(
            name="debugging",
            keywords=["debug", "fix", "bug", "error", "crash", "fail", "broken", "issue", "traceback"],
            techniques=[
                (PromptTechnique.DECOMPOSITION.value, 0.85),
                (PromptTechnique.FEW_SHOT.value, 0.8),
                (PromptTechnique.CHAIN_OF_THOUGHT.value, 0.75),
            ],
            description="Bug fixing and error diagnosis",
        ),
        TaskCluster(
            name="research",
            keywords=["research", "find", "search", "investigate", "explore", "analyze", "understand"],
            techniques=[
                (PromptTechnique.CHAIN_OF_THOUGHT.value, 0.9),
                (PromptTechnique.DECOMPOSITION.value, 0.7),
            ],
            description="Research and analysis tasks",
        ),
        TaskCluster(
            name="architecture",
            keywords=["design", "architect", "plan", "structure", "pattern", "system", "schema"],
            techniques=[
                (PromptTechnique.CHAIN_OF_THOUGHT.value, 0.9),
                (PromptTechnique.SELF_CONSISTENCY.value, 0.8),
                (PromptTechnique.DECOMPOSITION.value, 0.7),
            ],
            description="System design and architecture tasks",
        ),
        TaskCluster(
            name="security",
            keywords=["security", "vulnerability", "audit", "pentest", "attack", "exploit", "injection"],
            techniques=[
                (PromptTechnique.ROLE_PLAYING.value, 0.95),
                (PromptTechnique.SELF_CONSISTENCY.value, 0.8),
                (PromptTechnique.CHAIN_OF_THOUGHT.value, 0.7),
            ],
            description="Security review and adversarial analysis",
        ),
        TaskCluster(
            name="testing",
            keywords=["test", "coverage", "assertion", "pytest", "unittest", "validate", "verify"],
            techniques=[
                (PromptTechnique.DECOMPOSITION.value, 0.85),
                (PromptTechnique.FEW_SHOT.value, 0.8),
                (PromptTechnique.STEP_BY_STEP.value, 0.75),
            ],
            description="Test writing and validation",
        ),
        TaskCluster(
            name="documentation",
            keywords=["document", "readme", "docstring", "explain", "describe", "comment", "docs"],
            techniques=[
                (PromptTechnique.STEP_BY_STEP.value, 0.85),
                (PromptTechnique.FEW_SHOT.value, 0.7),
            ],
            description="Documentation and explanation tasks",
        ),
        TaskCluster(
            name="review",
            keywords=["review", "critique", "feedback", "quality", "improve", "suggest", "evaluate"],
            techniques=[
                (PromptTechnique.SELF_CONSISTENCY.value, 0.85),
                (PromptTechnique.ROLE_PLAYING.value, 0.8),
                (PromptTechnique.CHAIN_OF_THOUGHT.value, 0.75),
            ],
            description="Code review and quality evaluation",
        ),
    ]


# =============================================================================
# Technique Selector
# =============================================================================


@dataclass
class SelectionResult:
    """Result of technique selection."""

    techniques: list[PromptTechnique]
    cluster_name: str
    cluster_score: float
    reasoning: str


class TechniqueSelector:
    """
    Adaptive prompt technique selection based on task clustering.

    Matches tasks to clusters via keyword scoring, returns ranked
    techniques with effectiveness history. Learns from outcomes
    via EMA updates.
    """

    EMA_ALPHA = 0.2  # Learning rate for outcome updates
    MAX_TECHNIQUES = 3  # Max techniques to apply simultaneously

    def __init__(self, storage_path: Path | None = None):
        self._clusters = _default_clusters()
        self._history: dict[str, list[float]] = {}  # technique -> outcome scores
        self._storage_path = storage_path or Path("workspace/.nexus/technique_history.json")
        self._lock = threading.Lock()
        self._load()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def select(
        self,
        task_description: str,
        domains: list[str] | None = None,
        max_techniques: int = 0,
    ) -> SelectionResult:
        """
        Select optimal prompting techniques for a task.

        Args:
            task_description: Free-text task description
            domains: Optional domain hints (e.g., ["coding", "debugging"])
            max_techniques: Override for max techniques (0 = use default)

        Returns:
            SelectionResult with ranked techniques
        """
        limit = max_techniques or self.MAX_TECHNIQUES

        # Score each cluster
        scored_clusters: list[tuple[float, TaskCluster]] = []
        for cluster in self._clusters:
            score = cluster.keyword_score(task_description)

            # Boost if domain hint matches
            if domains:
                for domain in domains:
                    if domain.lower() == cluster.name or domain.lower() in cluster.keywords:
                        score += 0.4

            if score > 0:
                scored_clusters.append((score, cluster))

        if not scored_clusters:
            # Fallback: chain-of-thought is a safe default
            return SelectionResult(
                techniques=[PromptTechnique.CHAIN_OF_THOUGHT],
                cluster_name="default",
                cluster_score=0.0,
                reasoning="No cluster matched; using chain-of-thought as safe default",
            )

        # Pick best cluster
        scored_clusters.sort(key=lambda x: x[0], reverse=True)
        best_score, best_cluster = scored_clusters[0]

        # Get techniques ranked by cluster efficacy + historical performance
        technique_scores: list[tuple[float, PromptTechnique]] = []
        for tech_value, efficacy in best_cluster.techniques:
            technique = PromptTechnique(tech_value)
            # Combine cluster efficacy with learned history
            historical = self._get_historical_score(technique)
            combined = 0.6 * efficacy + 0.4 * historical
            technique_scores.append((combined, technique))

        technique_scores.sort(key=lambda x: x[0], reverse=True)
        selected = [t for _, t in technique_scores[:limit]]

        return SelectionResult(
            techniques=selected,
            cluster_name=best_cluster.name,
            cluster_score=best_score,
            reasoning=f"Matched cluster '{best_cluster.name}' (score={best_score:.2f}): {best_cluster.description}",
        )

    def compose_prompt(
        self,
        base_prompt: str,
        techniques: list[PromptTechnique],
    ) -> str:
        """
        Enhance a base prompt by injecting technique-specific instructions.

        Args:
            base_prompt: The original prompt text
            techniques: Techniques to inject

        Returns:
            Enhanced prompt with technique instructions prepended
        """
        if not techniques:
            return base_prompt

        lines = ["[APPROACH GUIDANCE]"]
        for tech in techniques:
            instruction = TECHNIQUE_INSTRUCTIONS.get(tech, "")
            if instruction:
                lines.append(f"- {instruction}")
        lines.append("[END APPROACH GUIDANCE]")
        lines.append("")

        return "\n".join(lines) + base_prompt

    def record_outcome(
        self,
        techniques: list[PromptTechnique],
        quality: float,
    ) -> None:
        """
        Record task outcome to learn technique effectiveness.

        Args:
            techniques: Techniques that were used
            quality: Quality score 0.0-1.0 of the result
        """
        with self._lock:
            for tech in techniques:
                key = tech.value
                if key not in self._history:
                    self._history[key] = []
                self._history[key].append(quality)
                # Keep last 50 observations
                if len(self._history[key]) > 50:
                    self._history[key] = self._history[key][-50:]

        self._persist()

    # -------------------------------------------------------------------------
    # Info
    # -------------------------------------------------------------------------

    def get_cluster_names(self) -> list[str]:
        """Return all cluster names."""
        return [c.name for c in self._clusters]

    def get_technique_stats(self) -> dict[str, dict]:
        """Get historical effectiveness per technique."""
        stats = {}
        for tech in PromptTechnique:
            scores = self._history.get(tech.value, [])
            stats[tech.value] = {
                "observations": len(scores),
                "avg_quality": sum(scores) / len(scores) if scores else 0.5,
            }
        return stats

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _get_historical_score(self, technique: PromptTechnique) -> float:
        """Get EMA-weighted historical score for a technique."""
        scores = self._history.get(technique.value, [])
        if not scores:
            return 0.5  # Neutral prior

        # EMA over recent observations
        ema = scores[0]
        for s in scores[1:]:
            ema = self.EMA_ALPHA * s + (1 - self.EMA_ALPHA) * ema
        return ema

    def _load(self) -> None:
        """Load history from file."""
        if not self._storage_path.exists():
            return
        try:
            with open(self._storage_path) as f:
                self._history = json.load(f)
        except Exception as e:
            logger.debug(f"TechniqueSelector: Failed to load history: {e}")

    def _persist(self) -> None:
        """Save history to file."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._storage_path, "w") as f:
                json.dump(self._history, f)
        except Exception as e:
            logger.debug(f"TechniqueSelector: Failed to persist history: {e}")


# =============================================================================
# Singleton
# =============================================================================

_instance: TechniqueSelector | None = None
_instance_lock = threading.Lock()


def get_technique_selector() -> TechniqueSelector:
    """Get or create the singleton TechniqueSelector instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TechniqueSelector()
    return _instance


def reset_technique_selector() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
