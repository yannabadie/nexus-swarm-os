"""
NEXUS V12.4 - Uncertainty Propagator (arXiv:2601.15703)

Dual-process uncertainty framework that transforms verbalized uncertainty
into active control signals. Prevents the "Spiral of Hallucination"
where early errors propagate irreversibly through multi-step pipelines.

Based on: "Agentic Uncertainty Quantification" (arXiv:2601.15703)

Two systems:
1. System 1 (Uncertainty-Aware Memory): Implicitly carries forward
   confidence levels between agent turns
2. System 2 (Uncertainty-Aware Reflection): Triggers deeper reasoning
   when uncertainty exceeds threshold

Usage:
    propagator = get_uncertainty_propagator()

    # After each step, propagate uncertainty
    signal = propagator.propagate(
        step_name="Generate SQL",
        confidence=0.7,
        output_preview="SELECT * FROM users WHERE...",
    )

    if signal.needs_reflection:
        # Trigger MARS reflection or alternative approach
        ...

    # Check accumulated uncertainty
    chain = propagator.get_chain_summary()
    if chain.cascade_risk > 0.8:
        # High risk of hallucination spiral — reset or escalate
        ...
"""

import logging
import threading
from collections import deque
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


class UncertaintyLevel(Enum):
    """Confidence classification for control flow decisions."""

    CONFIDENT = "confident"  # > 0.8 — proceed normally
    MODERATE = "moderate"  # 0.5-0.8 — proceed with caution
    UNCERTAIN = "uncertain"  # 0.3-0.5 — consider reflection
    HIGHLY_UNCERTAIN = "highly_uncertain"  # < 0.3 — trigger reflection


@dataclass
class PropagationSignal:
    """Result of propagating uncertainty through a step."""

    step_name: str
    raw_confidence: float  # Stated confidence for this step
    propagated_confidence: float  # Adjusted for upstream uncertainty
    uncertainty_level: UncertaintyLevel
    needs_reflection: bool  # Should trigger System 2?
    cascade_risk: float  # Risk of hallucination cascade (0-1)
    upstream_uncertainty: float  # Accumulated upstream uncertainty
    chain_position: int  # Position in the execution chain

    @property
    def confidence_drop(self) -> float:
        """How much confidence was lost due to upstream uncertainty."""
        return self.raw_confidence - self.propagated_confidence


@dataclass
class ChainSummary:
    """Summary of uncertainty across the execution chain."""

    total_steps: int
    avg_confidence: float
    min_confidence: float
    max_confidence: float
    cascade_risk: float  # Overall cascade risk
    reflection_triggers: int  # How many steps triggered reflection
    weakest_step: str  # Step with lowest propagated confidence
    uncertainty_trend: str  # "increasing", "decreasing", "stable"


@dataclass
class PropagatorStats:
    """Statistics for the uncertainty propagator."""

    total_propagations: int
    total_reflections_triggered: int
    avg_cascade_risk: float
    chains_completed: int


# =============================================================================
# Uncertainty Propagator
# =============================================================================


class UncertaintyPropagator:
    """
    Dual-process uncertainty framework for multi-step execution.

    System 1: Forward propagation — each step's effective confidence
    is reduced by upstream uncertainty (multiplicative decay).

    System 2: Reflection trigger — when propagated confidence drops
    below threshold, flag for deeper reasoning (MARS/alternative approach).

    Prevents cascading hallucination by making uncertainty visible
    and actionable at each step.
    """

    # Thresholds
    REFLECTION_THRESHOLD = 0.4  # Below this -> trigger reflection
    CASCADE_WARNING = 0.6  # Cascade risk above this -> warning
    CASCADE_CRITICAL = 0.8  # Cascade risk above this -> critical

    # Propagation parameters
    DECAY_FACTOR = 0.85  # Upstream uncertainty decay per step
    MAX_CHAIN_LENGTH = 50  # Maximum steps to track
    RECOVERY_BOOST = 0.1  # Confidence boost after successful reflection

    def __init__(self, reflection_threshold: float = 0.0):
        self._threshold = reflection_threshold or self.REFLECTION_THRESHOLD
        self._chain: deque[PropagationSignal] = deque(maxlen=self.MAX_CHAIN_LENGTH)
        self._total_propagations = 0
        self._total_reflections = 0
        self._cascade_risk_sum = 0.0
        self._chains_completed = 0
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def propagate(
        self,
        step_name: str,
        confidence: float,
        output_preview: str = "",
    ) -> PropagationSignal:
        """
        Propagate uncertainty through a step.

        The effective confidence is the step's stated confidence multiplied
        by accumulated upstream confidence. This makes downstream steps
        "aware" of upstream uncertainty.

        Args:
            step_name: Name of the execution step
            confidence: Step's stated confidence (0-1)
            output_preview: First ~100 chars of output (for logging)

        Returns:
            PropagationSignal with propagated confidence and control signals
        """
        raw = max(0.0, min(1.0, confidence))

        # Compute upstream uncertainty
        upstream = self._compute_upstream_uncertainty()

        # System 1: Propagated confidence = raw * upstream_confidence
        upstream_confidence = 1.0 - upstream
        propagated = raw * upstream_confidence

        # Cascade risk: increases with chain length and low confidence
        cascade_risk = self._compute_cascade_risk(propagated)

        # Classify uncertainty level
        level = self._classify_uncertainty(propagated)

        # System 2: Reflection trigger
        needs_reflection = propagated < self._threshold

        chain_position = len(self._chain) + 1

        signal = PropagationSignal(
            step_name=step_name,
            raw_confidence=raw,
            propagated_confidence=propagated,
            uncertainty_level=level,
            needs_reflection=needs_reflection,
            cascade_risk=cascade_risk,
            upstream_uncertainty=upstream,
            chain_position=chain_position,
        )

        with self._lock:
            self._chain.append(signal)
            self._total_propagations += 1
            self._cascade_risk_sum += cascade_risk
            if needs_reflection:
                self._total_reflections += 1

        if needs_reflection:
            logger.warning(
                f"UncertaintyPropagator: reflection triggered at step "
                f"'{step_name}' (propagated={propagated:.2f}, "
                f"cascade_risk={cascade_risk:.2f})"
            )

        return signal

    def record_reflection_success(self) -> None:
        """
        Record that a reflection was performed and succeeded.

        Applies a small confidence recovery boost to mitigate the
        accumulated uncertainty for subsequent steps.
        """
        if not self._chain:
            return

        # We don't modify past signals, but the upstream computation
        # will benefit from the last step having higher confidence
        last = self._chain[-1]
        boosted_confidence = min(1.0, last.propagated_confidence + self.RECOVERY_BOOST)

        # Replace last signal with boosted version
        with self._lock:
            self._chain[-1] = PropagationSignal(
                step_name=last.step_name,
                raw_confidence=last.raw_confidence,
                propagated_confidence=boosted_confidence,
                uncertainty_level=self._classify_uncertainty(boosted_confidence),
                needs_reflection=False,  # Reflection was done
                cascade_risk=last.cascade_risk,
                upstream_uncertainty=last.upstream_uncertainty,
                chain_position=last.chain_position,
            )

    def get_chain_summary(self) -> ChainSummary:
        """Get summary of the current execution chain's uncertainty."""
        signals = list(self._chain)

        if not signals:
            return ChainSummary(
                total_steps=0,
                avg_confidence=1.0,
                min_confidence=1.0,
                max_confidence=1.0,
                cascade_risk=0.0,
                reflection_triggers=0,
                weakest_step="",
                uncertainty_trend="stable",
            )

        confidences = [s.propagated_confidence for s in signals]
        cascade_risks = [s.cascade_risk for s in signals]

        min_idx = confidences.index(min(confidences))
        weakest = signals[min_idx].step_name

        trend = self._compute_trend(confidences)

        return ChainSummary(
            total_steps=len(signals),
            avg_confidence=sum(confidences) / len(confidences),
            min_confidence=min(confidences),
            max_confidence=max(confidences),
            cascade_risk=max(cascade_risks) if cascade_risks else 0.0,
            reflection_triggers=sum(1 for s in signals if s.needs_reflection),
            weakest_step=weakest,
            uncertainty_trend=trend,
        )

    def reset_chain(self) -> None:
        """Reset the current chain (start new task execution)."""
        with self._lock:
            self._chain.clear()
            self._chains_completed += 1

    def get_stats(self) -> PropagatorStats:
        """Get propagator statistics."""
        avg_risk = self._cascade_risk_sum / max(self._total_propagations, 1)
        return PropagatorStats(
            total_propagations=self._total_propagations,
            total_reflections_triggered=self._total_reflections,
            avg_cascade_risk=avg_risk,
            chains_completed=self._chains_completed,
        )

    @property
    def threshold(self) -> float:
        return self._threshold

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _compute_upstream_uncertainty(self) -> float:
        """Compute accumulated upstream uncertainty from the chain."""
        if not self._chain:
            return 0.0

        # Multiplicative decay: each step's uncertainty contributes
        # to downstream uncertainty, with decay
        chain = list(self._chain)
        uncertainty = 0.0

        for i, signal in enumerate(reversed(chain)):
            step_uncertainty = 1.0 - signal.propagated_confidence
            decay = self.DECAY_FACTOR ** (i + 1)
            uncertainty += step_uncertainty * decay

        # Normalize to [0, 1]
        return min(1.0, uncertainty)

    def _compute_cascade_risk(self, propagated_confidence: float) -> float:
        """Compute risk of hallucination cascade."""
        chain_length = len(self._chain)

        if chain_length == 0:
            return 1.0 - propagated_confidence

        # Risk increases with chain length and low confidence
        length_factor = min(1.0, chain_length / 10.0)  # Maxes at 10 steps
        confidence_factor = 1.0 - propagated_confidence

        # Count recent low-confidence steps
        recent = list(self._chain)[-5:]
        low_conf_ratio = sum(1 for s in recent if s.propagated_confidence < 0.5) / max(len(recent), 1)

        risk = 0.4 * confidence_factor + 0.3 * length_factor + 0.3 * low_conf_ratio

        return min(1.0, risk)

    def _classify_uncertainty(self, confidence: float) -> UncertaintyLevel:
        """Classify confidence into uncertainty levels."""
        if confidence > 0.8:
            return UncertaintyLevel.CONFIDENT
        elif confidence > 0.5:
            return UncertaintyLevel.MODERATE
        elif confidence > 0.3:
            return UncertaintyLevel.UNCERTAIN
        else:
            return UncertaintyLevel.HIGHLY_UNCERTAIN

    def _compute_trend(self, values: list[float]) -> str:
        """Compute trend direction from a series of values."""
        if len(values) < 3:
            return "stable"

        # Simple: compare first half average to second half average
        mid = len(values) // 2
        first_half = sum(values[:mid]) / mid
        second_half = sum(values[mid:]) / (len(values) - mid)

        diff = second_half - first_half
        if diff > 0.05:
            return "increasing"
        elif diff < -0.05:
            return "decreasing"
        else:
            return "stable"


# =============================================================================
# Singleton
# =============================================================================

_instance: UncertaintyPropagator | None = None
_instance_lock = threading.Lock()


def get_uncertainty_propagator() -> UncertaintyPropagator:
    """Get or create the singleton UncertaintyPropagator instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = UncertaintyPropagator()
    return _instance


def reset_uncertainty_propagator() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
