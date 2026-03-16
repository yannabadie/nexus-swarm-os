"""
Memory Coordinator - V12.4 COGNITIVE BOOST

Coordinates SuccessMemory (episodic) and AutoMemory (procedural) for:
1. Unified query interface
2. Conflict resolution
3. Score normalization
4. Consolidation (episodic -> procedural)
5. V12.4: Adaptive weights per domain

Design Pattern: Adapter + Facade
- Keeps both memories intact
- Adds coordination without breaking existing code
- Gradual migration path

Architecture:
    +-----------------+   +-----------------+
    |  SuccessMemory  |   |   AutoMemory    |
    |  (Episodic)     |   |  (Procedural)   |
    |                 |   |                 |
    |  - Similarity   |   |  - Task type    |
    |  - Time decay   |   |  - Lead/Mode    |
    +--------+--------+   +--------+--------+
             |                     |
             +----------+----------+
                        |
              +---------v---------+
              | MemoryCoordinator |
              | - Normalize       |
              | - Adaptive Weight | <- V12.4
              | - Resolve         |
              +---------+---------+
                        |
              +---------v---------+
              | UnifiedRec        |
              | - mode            |
              | - lead            |
              | - confidence      |
              | - source          |
              +-------------------+

V12.4 Adaptive Weights:
- Learns optimal semantic/procedural weights per domain
- Tracks recommendation outcomes (success/failure)
- Adjusts weights using exponential moving average
- Starts with defaults, improves over time

Author: Claude (NEXUS V11.2 MEMORIA + V12.4 COGNITIVE BOOST)
Date: 2025-12-15 / Updated: 2025-12-16
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .auto_memory import AutoMemory
    from .success_memory import SuccessMemory


# =============================================================================
# V12.4 Adaptive Weights Configuration
# =============================================================================

# Default weights (used for cold start)
DEFAULT_SEMANTIC_WEIGHT = 0.6
DEFAULT_PROCEDURAL_WEIGHT = 0.4

# Learning rate for weight adaptation (exponential moving average)
# Higher = faster adaptation, more volatile
# Lower = slower adaptation, more stable
LEARNING_RATE = 0.1

# Minimum samples before adapting weights for a domain
MIN_SAMPLES_FOR_ADAPTATION = 5


@dataclass
class DomainWeights:
    """
    V12.4: Learned weights for a specific domain.

    Attributes:
        semantic_weight: Weight for SuccessMemory (similarity-based)
        procedural_weight: Weight for AutoMemory (task-type-based)
        sample_count: Number of feedback samples received
        success_count: Number of successful recommendations
    """

    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT
    procedural_weight: float = DEFAULT_PROCEDURAL_WEIGHT
    sample_count: int = 0
    success_count: int = 0

    @property
    def success_rate(self) -> float:
        """Success rate for this domain's recommendations."""
        return self.success_count / self.sample_count if self.sample_count > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "semantic_weight": round(self.semantic_weight, 3),
            "procedural_weight": round(self.procedural_weight, 3),
            "sample_count": self.sample_count,
            "success_count": self.success_count,
            "success_rate": round(self.success_rate, 3),
        }


class MemorySource(Enum):
    """Which memory provided the recommendation."""

    SUCCESS = "success_memory"  # Episodic (semantic similarity)
    AUTO = "auto_memory"  # Procedural (task type)
    BOTH = "both"  # Both agree
    NONE = "none"  # Neither has data


@dataclass
class UnifiedRecommendation:
    """
    Normalized recommendation from unified memory.

    Attributes:
        mode: Recommended swarm mode (or None)
        lead: Recommended lead agent (or None)
        confidence: Normalized 0.0-1.0 confidence score
        source: Which memory provided this recommendation
        modes_to_avoid: List of modes to penalize
        reasoning: Human-readable explanation
    """

    mode: str | None
    lead: str | None
    confidence: float
    source: MemorySource
    modes_to_avoid: list[str]
    reasoning: str

    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "mode": self.mode,
            "lead": self.lead,
            "confidence": round(self.confidence, 3),
            "source": self.source.value,
            "modes_to_avoid": self.modes_to_avoid,
            "reasoning": self.reasoning,
        }


class MemoryCoordinator:
    """
    Coordinates SuccessMemory and AutoMemory.

    Query Flow:
    1. Query both memories in parallel (well, sequentially but fast)
    2. Normalize scores to 0-1
    3. Apply weighting (V12.4: adaptive per domain)
    4. Resolve conflicts
    5. Return UnifiedRecommendation

    Consolidation Flow:
    1. Periodically scan SuccessMemory for patterns
    2. Extract mode/lead success rates by task_type
    3. Log insights (AutoMemory update could be added later)

    V12.4 Adaptive Weights:
    - SEMANTIC_WEIGHT (default 0.6): SuccessMemory similarity-based
    - PROCEDURAL_WEIGHT (default 0.4): AutoMemory task-type-based
    - Weights adapt per domain based on recommendation success rate
    - Uses exponential moving average with configurable learning rate

    Rationale: Semantic similarity is more specific (finds exact matches),
    while categorical is broader (works with less data). Different domains
    may benefit from different weight balances.
    """

    # Default weights for combining scores (V12.4: now class constants, instance can override)
    SEMANTIC_WEIGHT = DEFAULT_SEMANTIC_WEIGHT
    PROCEDURAL_WEIGHT = DEFAULT_PROCEDURAL_WEIGHT

    # Thresholds
    MIN_CONFIDENCE = 0.3  # Below this, don't recommend
    HIGH_CONFIDENCE = 0.7  # Above this, strong recommendation

    def __init__(
        self, success_memory: SuccessMemory | None, auto_memory: AutoMemory | None, weights_path: Path | None = None
    ):
        """
        Initialize the coordinator.

        Args:
            success_memory: SuccessMemory instance (episodic)
            auto_memory: AutoMemory instance (procedural)
            weights_path: V12.4 - Path to persist learned weights (optional)
        """
        self.success = success_memory
        self.auto = auto_memory
        self._logger = logging.getLogger("nexus.memory.coordinator")

        # V12.4: Adaptive weights per domain
        self._domain_weights: dict[str, DomainWeights] = {}
        self._weights_path = weights_path
        self._last_recommendation: tuple[str, MemorySource] | None = None  # (domain, source)

        # Load persisted weights if available
        if weights_path and weights_path.exists():
            self._load_weights()

    def get_recommendation(
        self, task_description: str, task_type: str, domains: list[str] | None = None
    ) -> UnifiedRecommendation:
        """
        Get unified recommendation from both memory systems.

        Algorithm:
        1. Query SuccessMemory with semantic similarity
        2. Query AutoMemory with task_type lookup
        3. Normalize and weight scores (V12.4: domain-adaptive)
        4. Resolve conflicts (if any)
        5. Return unified recommendation

        Args:
            task_description: Full task description for semantic search
            task_type: Task category for categorical lookup (e.g., "coding")
            domains: Optional list of domains for domain boosting

        Returns:
            UnifiedRecommendation with normalized confidence
        """
        # V12.4: Determine primary domain for weight lookup
        primary_domain = task_type  # Use task_type as domain key
        if domains:
            primary_domain = domains[0]

        self._logger.debug(f"[COORDINATOR] Getting recommendation for domain={primary_domain}")

        # 1. Query SuccessMemory (semantic)
        success_rec = None
        success_score = 0.0
        if self.success:
            try:
                result = self.success.get_best_mode_for_similar(
                    query=task_description,
                    min_similarity=0.2,
                    apply_decay=True,
                    query_domains=domains,
                    domain_boost=0.15,
                )
                if result:
                    success_rec = {"mode": result[0], "task_id": result[1], "similarity": result[2]}
                    success_score = result[2]  # similarity is 0-1
                    self._logger.debug(f"[COORDINATOR] SuccessMemory: mode={result[0]}, similarity={result[2]:.3f}")
            except Exception as e:
                self._logger.warning(f"[COORDINATOR] SuccessMemory query failed: {e}")

        # 2. Query AutoMemory (procedural)
        auto_rec = None
        auto_score = 0.0
        if self.auto:
            try:
                result = self.auto.get_recommendation(task_type, task_description)
                if result and result.get("confidence", 0) > 0:
                    auto_rec = result
                    auto_score = result["confidence"]  # already 0-1
                    self._logger.debug(
                        f"[COORDINATOR] AutoMemory: mode={result.get('suggested_mode')}, confidence={auto_score:.3f}"
                    )
            except Exception as e:
                self._logger.warning(f"[COORDINATOR] AutoMemory query failed: {e}")

        # 3. Handle cases
        if not success_rec and not auto_rec:
            self._logger.debug("[COORDINATOR] No memory data (cold start)")
            return UnifiedRecommendation(
                mode=None,
                lead=None,
                confidence=0.0,
                source=MemorySource.NONE,
                modes_to_avoid=[],
                reasoning="No memory data available (cold start)",
            )

        # V12.4: Get domain-specific weights
        semantic_w, procedural_w = self.get_weights_for_domain(primary_domain)

        # 4. Both have data - combine
        if success_rec and auto_rec:
            rec = self._combine_recommendations(
                success_rec, success_score, auto_rec, auto_score, task_description, semantic_w, procedural_w
            )
            # V12.4: Track for feedback
            self._last_recommendation = (primary_domain, rec.source)
            return rec

        # 5. Only one has data
        if success_rec:
            weighted_conf = success_score * semantic_w
            rec = UnifiedRecommendation(
                mode=success_rec["mode"],
                lead=None,
                confidence=weighted_conf,
                source=MemorySource.SUCCESS,
                modes_to_avoid=[],
                reasoning=f"Similar task '{success_rec['task_id'][:20]}...' used {success_rec['mode']}",
            )
            self._last_recommendation = (primary_domain, MemorySource.SUCCESS)
            return rec

        # Only auto_rec
        weighted_conf = auto_score * procedural_w
        rec = UnifiedRecommendation(
            mode=auto_rec.get("suggested_mode"),
            lead=auto_rec.get("suggested_lead"),
            confidence=weighted_conf,
            source=MemorySource.AUTO,
            modes_to_avoid=auto_rec.get("modes_to_avoid", []),
            reasoning=f"Task type '{task_type}' typically uses {auto_rec.get('suggested_mode')}",
        )
        self._last_recommendation = (primary_domain, MemorySource.AUTO)
        return rec

    def _combine_recommendations(
        self,
        success_rec: dict,
        success_score: float,
        auto_rec: dict,
        auto_score: float,
        task_description: str,
        semantic_weight: float,
        procedural_weight: float,
    ) -> UnifiedRecommendation:
        """
        Combine recommendations when both memories have data.

        Conflict Resolution:
        - If both agree: combine confidence scores
        - If they differ: prioritize based on weighted scores
        - Semantic (SuccessMemory) wins ties due to specificity

        V12.4: Uses domain-adaptive weights instead of class constants.

        Args:
            success_rec: SuccessMemory recommendation dict
            success_score: Raw similarity score (0-1)
            auto_rec: AutoMemory recommendation dict
            auto_score: Raw confidence score (0-1)
            task_description: Original task (for logging)

        Returns:
            UnifiedRecommendation
        """
        success_mode = success_rec["mode"]
        auto_mode = auto_rec.get("suggested_mode")

        # Agreement case - both recommend same mode
        if success_mode == auto_mode:
            combined_confidence = success_score * semantic_weight + auto_score * procedural_weight
            self._logger.debug(
                f"[COORDINATOR] Agreement: both recommend {success_mode}, combined_confidence={combined_confidence:.3f}"
            )
            return UnifiedRecommendation(
                mode=success_mode,
                lead=auto_rec.get("suggested_lead"),
                confidence=min(1.0, combined_confidence),
                source=MemorySource.BOTH,
                modes_to_avoid=auto_rec.get("modes_to_avoid", []),
                reasoning=f"Both memories agree: {success_mode}",
            )

        # Conflict case - different recommendations
        # Prioritize based on weighted scores (V12.4: domain-adaptive)
        weighted_success = success_score * semantic_weight
        weighted_auto = auto_score * procedural_weight

        self._logger.debug(
            f"[COORDINATOR] Conflict: success={success_mode} ({weighted_success:.3f}) "
            f"vs auto={auto_mode} ({weighted_auto:.3f})"
        )

        if weighted_success >= weighted_auto:
            # Semantic similarity wins (more specific)
            return UnifiedRecommendation(
                mode=success_mode,
                lead=auto_rec.get("suggested_lead"),  # Still use lead from auto
                confidence=weighted_success,
                source=MemorySource.SUCCESS,
                modes_to_avoid=auto_rec.get("modes_to_avoid", []),
                reasoning=f"Semantic match ({success_score:.2f}) beats categorical ({auto_score:.2f})",
            )
        else:
            # Categorical wins (more samples)
            return UnifiedRecommendation(
                mode=auto_mode,
                lead=auto_rec.get("suggested_lead"),
                confidence=weighted_auto,
                source=MemorySource.AUTO,
                modes_to_avoid=auto_rec.get("modes_to_avoid", []),
                reasoning=f"Categorical confidence ({auto_score:.2f}) beats semantic ({success_score:.2f})",
            )

    def consolidate(self) -> int:
        """
        Consolidate episodic patterns into procedural memory.

        Scans SuccessMemory for recurring patterns by domain.
        Logs insights that could be used to update AutoMemory.

        Should be called periodically (e.g., end of session).

        Returns:
            Number of patterns found
        """
        if not self.success:
            return 0

        try:
            entries = self.success.get_all()
        except Exception as e:
            self._logger.warning(f"[CONSOLIDATE] Failed to get entries: {e}")
            return 0

        if len(entries) < 10:
            self._logger.debug("[CONSOLIDATE] Not enough data (<10 entries)")
            return 0

        # Group by primary_domain (task_type equivalent)
        from collections import defaultdict

        by_domain: dict[str, list] = defaultdict(list)

        for entry in entries:
            domain = entry.primary_domain or (entry.domains[0] if entry.domains else "general")
            by_domain[domain].append(entry)

        consolidated = 0
        for domain, domain_entries in by_domain.items():
            if len(domain_entries) < 5:
                continue

            # Find most successful mode
            mode_scores: dict[str, list[float]] = defaultdict(list)
            for entry in domain_entries:
                mode_scores[entry.swarm_mode].append(entry.quality_score)

            if not mode_scores:
                continue

            best_mode = max(mode_scores.keys(), key=lambda m: sum(mode_scores[m]) / len(mode_scores[m]))
            avg_score = sum(mode_scores[best_mode]) / len(mode_scores[best_mode])

            # Log the insight (AutoMemory update could be added here)
            self._logger.info(
                f"[CONSOLIDATE] {domain}: {best_mode} (avg={avg_score:.2f}, n={len(mode_scores[best_mode])})"
            )
            consolidated += 1

        return consolidated

    def get_stats(self) -> dict:
        """
        Get coordinator statistics.

        Returns:
            Dictionary with status of both memories
        """
        stats = {
            "success_memory_available": self.success is not None,
            "auto_memory_available": self.auto is not None,
            "semantic_weight": self.SEMANTIC_WEIGHT,
            "procedural_weight": self.PROCEDURAL_WEIGHT,
            # V12.4: Adaptive weights stats
            "adaptive_domains": len(self._domain_weights),
            "domain_weights": {k: v.to_dict() for k, v in self._domain_weights.items()},
        }

        if self.success:
            try:
                sm_stats = self.success.get_stats()
                stats["success_memory_entries"] = sm_stats.get("total_entries", 0)
            except Exception:
                stats["success_memory_entries"] = -1

        if self.auto:
            try:
                am_stats = self.auto.get_stats()
                stats["auto_memory_successes"] = am_stats.get("total_successes", 0)
                stats["auto_memory_failures"] = am_stats.get("total_failures", 0)
            except Exception:
                stats["auto_memory_successes"] = -1

        return stats

    # =========================================================================
    # V12.4 COGNITIVE BOOST - Adaptive Weights
    # =========================================================================

    def get_weights_for_domain(self, domain: str) -> tuple[float, float]:
        """
        Get semantic/procedural weights for a specific domain.

        V12.4: Returns learned weights if available, otherwise defaults.

        Args:
            domain: Domain name (e.g., "coding", "research")

        Returns:
            Tuple of (semantic_weight, procedural_weight)
        """
        if domain in self._domain_weights:
            dw = self._domain_weights[domain]
            return (dw.semantic_weight, dw.procedural_weight)
        return (DEFAULT_SEMANTIC_WEIGHT, DEFAULT_PROCEDURAL_WEIGHT)

    def record_feedback(self, domain: str, source: MemorySource, success: bool) -> None:
        """
        Record feedback on a recommendation outcome.

        V12.4: Updates domain weights based on success/failure.

        Learning Algorithm (EMA-based):
        - If SUCCESS source's weight increases slightly
        - If BOTH succeeded, both weights validated (no change)
        - Weights always sum to 1.0

        Args:
            domain: Domain the recommendation was for
            source: Which memory source provided the recommendation
            success: Whether the recommendation led to task success
        """
        # Initialize domain weights if needed
        if domain not in self._domain_weights:
            self._domain_weights[domain] = DomainWeights()

        dw = self._domain_weights[domain]
        dw.sample_count += 1

        if success:
            dw.success_count += 1

        # Only adapt weights after minimum samples
        if dw.sample_count < MIN_SAMPLES_FOR_ADAPTATION:
            self._logger.debug(
                f"[ADAPTIVE] {domain}: Collecting samples ({dw.sample_count}/{MIN_SAMPLES_FOR_ADAPTATION})"
            )
            return

        # Adapt weights based on outcome
        if source == MemorySource.BOTH:
            # Both agreed and succeeded - weights are good
            self._logger.debug(f"[ADAPTIVE] {domain}: BOTH succeeded, weights unchanged")
            return

        if not success:
            # Failed - reduce winning source's weight
            self._adapt_weights(dw, source, decrease=True)
        else:
            # Succeeded - increase winning source's weight
            self._adapt_weights(dw, source, decrease=False)

        # Persist weights
        self._save_weights()

    def _adapt_weights(self, dw: DomainWeights, source: MemorySource, decrease: bool) -> None:
        """
        Adapt weights using exponential moving average.

        Args:
            dw: DomainWeights to update
            source: Source that won the recommendation
            decrease: If True, decrease source's weight; if False, increase
        """
        # Calculate adjustment (small step towards better balance)
        adjustment = LEARNING_RATE * (1.0 - dw.success_rate)

        if source == MemorySource.SUCCESS:
            if decrease:
                # Semantic failed - reduce its weight
                dw.semantic_weight = max(0.2, dw.semantic_weight - adjustment)
            else:
                # Semantic succeeded - increase its weight
                dw.semantic_weight = min(0.8, dw.semantic_weight + adjustment)
        elif source == MemorySource.AUTO:
            if decrease:
                # Procedural failed - reduce its weight
                dw.procedural_weight = max(0.2, dw.procedural_weight - adjustment)
            else:
                # Procedural succeeded - increase its weight
                dw.procedural_weight = min(0.8, dw.procedural_weight + adjustment)

        # Normalize to sum to 1.0
        total = dw.semantic_weight + dw.procedural_weight
        dw.semantic_weight /= total
        dw.procedural_weight /= total

        self._logger.debug(
            f"[ADAPTIVE] Updated weights: semantic={dw.semantic_weight:.3f}, procedural={dw.procedural_weight:.3f}"
        )

    def _load_weights(self) -> None:
        """Load persisted domain weights from file."""
        if not self._weights_path or not self._weights_path.exists():
            return

        try:
            with open(self._weights_path, encoding="utf-8") as f:
                data = json.load(f)

            for domain, weights_dict in data.items():
                self._domain_weights[domain] = DomainWeights(
                    semantic_weight=weights_dict.get("semantic_weight", DEFAULT_SEMANTIC_WEIGHT),
                    procedural_weight=weights_dict.get("procedural_weight", DEFAULT_PROCEDURAL_WEIGHT),
                    sample_count=weights_dict.get("sample_count", 0),
                    success_count=weights_dict.get("success_count", 0),
                )

            self._logger.info(f"[ADAPTIVE] Loaded weights for {len(self._domain_weights)} domains")

        except Exception as e:
            self._logger.warning(f"[ADAPTIVE] Failed to load weights: {e}")

    def _save_weights(self) -> None:
        """Persist domain weights to file."""
        if not self._weights_path:
            return

        try:
            # Ensure parent directory exists
            self._weights_path.parent.mkdir(parents=True, exist_ok=True)

            data = {domain: dw.to_dict() for domain, dw in self._domain_weights.items()}

            with open(self._weights_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            self._logger.warning(f"[ADAPTIVE] Failed to save weights: {e}")
