"""
Parallel Merge Strategies for NEXUS V8.3.3

Strategies for intelligently merging results from PARALLEL mode execution.

Available strategies:
- NAIVE: Simple concatenation (backward compatible, default)
- DEDUPLICATE: Remove semantically similar sentences
- WEIGHTED: Prioritize by domain fit scores from TaskAnalysis

Future strategies (require LLM):
- CONSENSUS: LLM identifies agreements/conflicts
- SUMMARY: LLM synthesizes into coherent summary
"""

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from core.foundation.agents.unified_registry import get_registry  # V8.4.0

if TYPE_CHECKING:
    from .mode_executors import AgentResponse


class MergeStrategyType(Enum):
    """Available merge strategies for PARALLEL mode"""

    NAIVE = "naive"  # Current behavior (backward compat)
    DEDUPLICATE = "deduplicate"  # Remove semantic duplicates
    WEIGHTED = "weighted"  # Weight by domain fit scores
    # Future: requires LLM invocation
    # CONSENSUS = "consensus"    # LLM identifies agreements/conflicts
    # SUMMARY = "summary"        # LLM synthesizes into coherent summary


@dataclass
class MergeContext:
    """
    Context available to merge strategies.

    Contains all information needed to intelligently merge parallel outputs.
    """

    task_input: str
    outputs: list["AgentResponse"]
    task_analysis: dict[str, Any] | None = None  # From blackboard
    agent_assignments: list[Any] | None = None  # AgentAssignment list


@dataclass
class MergeResult:
    """
    Result of a merge operation.

    Contains the merged content and metadata about the merge process.
    """

    content: str
    strategy_used: MergeStrategyType
    metadata: dict[str, Any] = field(default_factory=dict)


class MergeStrategy(ABC):
    """
    Base class for merge strategies.

    Subclasses implement different algorithms for combining
    parallel agent outputs into a single coherent result.
    """

    @property
    @abstractmethod
    def strategy_type(self) -> MergeStrategyType:
        """Return the strategy type enum value"""
        pass

    @abstractmethod
    def merge(self, context: MergeContext) -> MergeResult:
        """
        Merge parallel outputs according to this strategy.

        Args:
            context: MergeContext with outputs and metadata

        Returns:
            MergeResult with merged content and strategy metadata
        """
        pass

    def _get_agent_name(self, agent_id: str) -> str:
        """Extract display name from agent_id (V8.4.0: via registry)"""
        registry = get_registry()
        return registry.get_display_name(agent_id)


class NaiveMergeStrategy(MergeStrategy):
    """
    Naive merge: concatenate outputs with separators.

    This is the V8.3.2 behavior, preserved for backward compatibility.
    Simple but may result in redundant or contradictory content.
    """

    @property
    def strategy_type(self) -> MergeStrategyType:
        return MergeStrategyType.NAIVE

    def merge(self, context: MergeContext) -> MergeResult:
        merged_parts = []

        for output in context.outputs:
            agent_name = self._get_agent_name(output.agent_id)
            if output.status == "error":
                merged_parts.append(f"[{agent_name}] [NO] Error:\n{output.error or output.content}")
            else:
                merged_parts.append(f"[{agent_name}]:\n{output.content}")

        return MergeResult(
            content="\n\n---\n\n".join(merged_parts),
            strategy_used=self.strategy_type,
            metadata={"agent_count": len(context.outputs), "total_chars": sum(len(o.content) for o in context.outputs)},
        )


class DeduplicateMergeStrategy(MergeStrategy):
    """
    Deduplicate merge: remove semantically similar sentences.

    Uses Jaccard similarity on word sets to identify duplicates.
    Keeps the first occurrence of each unique point.
    """

    # Minimum similarity threshold for considering sentences as duplicates
    SIMILARITY_THRESHOLD = 0.6

    @property
    def strategy_type(self) -> MergeStrategyType:
        return MergeStrategyType.DEDUPLICATE

    def merge(self, context: MergeContext) -> MergeResult:
        # Collect all sentences with their source
        all_sentences: list[tuple] = []  # (sentence, agent_name, output_idx)

        for idx, output in enumerate(context.outputs):
            if output.status == "error":
                continue
            agent_name = self._get_agent_name(output.agent_id)
            sentences = self._split_into_sentences(output.content)
            for sentence in sentences:
                if sentence.strip():
                    all_sentences.append((sentence.strip(), agent_name, idx))

        # Deduplicate using Jaccard similarity
        unique_sentences: list[tuple] = []
        duplicates_removed = 0

        for sentence, agent, idx in all_sentences:
            is_duplicate = False
            sentence_words = self._get_word_set(sentence)

            for existing, _, _ in unique_sentences:
                existing_words = self._get_word_set(existing)
                similarity = self._jaccard_similarity(sentence_words, existing_words)
                if similarity >= self.SIMILARITY_THRESHOLD:
                    is_duplicate = True
                    duplicates_removed += 1
                    break

            if not is_duplicate:
                unique_sentences.append((sentence, agent, idx))

        # Group by agent for organized output
        agent_sentences: dict[str, list[str]] = {}
        for sentence, agent, _ in unique_sentences:
            if agent not in agent_sentences:
                agent_sentences[agent] = []
            agent_sentences[agent].append(sentence)

        # Build merged output
        merged_parts = []
        for agent, sentences in agent_sentences.items():
            merged_parts.append(f"[{agent}]:\n" + " ".join(sentences))

        # Add error outputs at the end
        for output in context.outputs:
            if output.status == "error":
                agent_name = self._get_agent_name(output.agent_id)
                merged_parts.append(f"[{agent_name}] [NO] Error:\n{output.error or output.content}")

        return MergeResult(
            content="\n\n---\n\n".join(merged_parts),
            strategy_used=self.strategy_type,
            metadata={
                "agent_count": len(context.outputs),
                "original_sentences": len(all_sentences),
                "unique_sentences": len(unique_sentences),
                "duplicates_removed": duplicates_removed,
                "dedup_ratio": round(duplicates_removed / max(len(all_sentences), 1), 2),
            },
        )

    def _split_into_sentences(self, text: str) -> list[str]:
        """Split text into sentences using basic punctuation rules"""
        # Split on sentence-ending punctuation followed by space or newline
        sentences = re.split(r"(?<=[.!?])\s+", text)
        # Also split on newlines for list items
        result = []
        for s in sentences:
            result.extend(s.split("\n"))
        return [s.strip() for s in result if s.strip()]

    def _get_word_set(self, text: str) -> set:
        """Extract set of lowercase words from text"""
        words = re.findall(r"\b\w+\b", text.lower())
        # Filter out very short words (articles, etc.)
        return set(w for w in words if len(w) > 2)

    def _jaccard_similarity(self, set1: set, set2: set) -> float:
        """Calculate Jaccard similarity between two word sets"""
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0


class WeightedMergeStrategy(MergeStrategy):
    """
    Weighted merge: prioritize outputs by domain fit scores.

    Uses TaskAnalysis fit scores to determine which agent's
    output should be emphasized for the given task domain.
    """

    @property
    def strategy_type(self) -> MergeStrategyType:
        return MergeStrategyType.WEIGHTED

    def merge(self, context: MergeContext) -> MergeResult:
        # Get fit scores from task_analysis
        gemini_fit = 0.5
        claude_fit = 0.5
        primary_domain = None

        if context.task_analysis:
            gemini_fit = context.task_analysis.get("gemini_fit_score", 0.5)
            claude_fit = context.task_analysis.get("claude_fit_score", 0.5)
            primary_domain = context.task_analysis.get("primary_domain")

        # Sort outputs by fit score (higher first) - V8.4.0: via registry
        registry = get_registry()

        def get_fit_score(output) -> float:
            if registry.is_gemini(output.agent_id):
                return gemini_fit
            elif registry.is_claude(output.agent_id):
                return claude_fit
            return 0.5

        sorted_outputs = sorted(context.outputs, key=get_fit_score, reverse=True)

        # Build merged output with fit indicators
        merged_parts = []
        for output in sorted_outputs:
            agent_name = self._get_agent_name(output.agent_id)
            fit_score = get_fit_score(output)

            if output.status == "error":
                merged_parts.append(f"[{agent_name}] [NO] Error:\n{output.error or output.content}")
            else:
                # Add fit indicator for high-scoring agents
                fit_indicator = ""
                if fit_score >= 0.7:
                    fit_indicator = " ⭐ (domain expert)"
                merged_parts.append(f"[{agent_name}{fit_indicator}]:\n{output.content}")

        return MergeResult(
            content="\n\n---\n\n".join(merged_parts),
            strategy_used=self.strategy_type,
            metadata={
                "agent_count": len(context.outputs),
                "primary_domain": primary_domain,
                "gemini_fit_score": gemini_fit,
                "claude_fit_score": claude_fit,
                "lead_agent": sorted_outputs[0].agent_id if sorted_outputs else None,
            },
        )


# Strategy registry
_STRATEGY_REGISTRY: dict[MergeStrategyType, type] = {
    MergeStrategyType.NAIVE: NaiveMergeStrategy,
    MergeStrategyType.DEDUPLICATE: DeduplicateMergeStrategy,
    MergeStrategyType.WEIGHTED: WeightedMergeStrategy,
}


def get_merge_strategy(strategy_type: MergeStrategyType = MergeStrategyType.NAIVE) -> MergeStrategy:
    """
    Factory function for merge strategies.

    Args:
        strategy_type: The type of merge strategy to create

    Returns:
        An instance of the requested merge strategy

    Raises:
        ValueError: If strategy_type is not registered
    """
    if strategy_type not in _STRATEGY_REGISTRY:
        raise ValueError(f"Unknown merge strategy: {strategy_type}. Available: {list(_STRATEGY_REGISTRY.keys())}")
    return _STRATEGY_REGISTRY[strategy_type]()


def get_default_merge_strategy() -> MergeStrategy:
    """
    Get the default merge strategy based on environment configuration.

    Reads NEXUS_PARALLEL_MERGE_STRATEGY from environment.
    Falls back to NAIVE if not set or invalid.
    """
    strategy_name = os.getenv("NEXUS_PARALLEL_MERGE_STRATEGY", "naive").lower()

    try:
        strategy_type = MergeStrategyType(strategy_name)
        return get_merge_strategy(strategy_type)
    except ValueError:
        # Invalid strategy name, fall back to naive
        return NaiveMergeStrategy()
