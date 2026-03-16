"""
Stepwise Confidence Monitor for HiveMind Pipeline.

V12.4 COGNITIVE BOOST

Tracks per-phase confidence scores throughout the 7-phase HiveMind pipeline.
Inspired by stepwise verification (arxiv:2511.07364) and uncertainty
quantification for multi-agent systems (arxiv:2601.15703).

Features:
- Per-phase confidence recording with metadata
- Trajectory analysis (improving, declining, stable)
- Early abort recommendation when confidence drops below threshold
- Minimum viable confidence floor that grows with pipeline depth

Usage:
    from core.intelligence.hive_mind.confidence_monitor import StepwiseConfidenceMonitor

    monitor = StepwiseConfidenceMonitor()
    monitor.record("analysis", 0.85)
    monitor.record("debate", 0.72)

    if monitor.should_abort():
        # Confidence trajectory is declining - consider stopping
        ...

    trajectory = monitor.get_trajectory()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Minimum confidence to continue at each pipeline depth
# Deeper phases require less confidence since we've invested more
DEPTH_FLOOR = {
    0: 0.40,  # analysis - high bar to even start
    1: 0.35,  # debate
    2: 0.30,  # architecture
    3: 0.25,  # execution
    4: 0.20,  # diagnosis
    5: 0.15,  # retry
    6: 0.10,  # consolidation
}

# If confidence drops by more than this between consecutive phases, flag it
DROP_THRESHOLD = 0.25

# If average confidence is below this, recommend abort
AVERAGE_FLOOR = 0.30


# =============================================================================
# Types
# =============================================================================


@dataclass
class PhaseConfidence:
    """Confidence measurement for a single phase."""

    phase: str
    confidence: float
    depth: int
    timestamp: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "confidence": round(self.confidence, 4),
            "depth": self.depth,
            "metadata": self.metadata,
        }


@dataclass
class ConfidenceTrajectory:
    """Summary of confidence across all recorded phases."""

    entries: list[PhaseConfidence]
    trend: str  # "improving", "declining", "stable", "insufficient_data"
    average: float
    minimum: float
    maximum: float
    latest: float
    drop_detected: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "trend": self.trend,
            "average": round(self.average, 4),
            "minimum": round(self.minimum, 4),
            "maximum": round(self.maximum, 4),
            "latest": round(self.latest, 4),
            "drop_detected": self.drop_detected,
            "phases": [e.to_dict() for e in self.entries],
        }


@dataclass
class AbortRecommendation:
    """Recommendation on whether to abort the pipeline."""

    should_abort: bool
    reason: str
    confidence: float  # Current confidence
    threshold: float  # What it was compared against

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_abort": self.should_abort,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
            "threshold": round(self.threshold, 4),
        }


# =============================================================================
# Stepwise Confidence Monitor
# =============================================================================


class StepwiseConfidenceMonitor:
    """
    Tracks confidence across HiveMind pipeline phases.

    Records a confidence score after each phase and provides trajectory
    analysis to detect declining confidence early, avoiding wasted
    computation on tasks that are likely to fail.

    Based on:
    - Stepwise verification (arxiv:2511.07364): per-step quality checks
    - Uncertainty quantification (arxiv:2601.15703): confidence calibration
    """

    def __init__(self, abort_threshold: float = AVERAGE_FLOOR):
        self._entries: list[PhaseConfidence] = []
        self._abort_threshold = abort_threshold

    def record(
        self,
        phase: str,
        confidence: float,
        **metadata: Any,
    ) -> PhaseConfidence:
        """
        Record confidence for a completed phase.

        Args:
            phase: Phase name (analysis, debate, architecture, etc.)
            confidence: Confidence score 0.0 to 1.0
            **metadata: Additional metadata (e.g. agreement_score, consensus)

        Returns:
            The recorded PhaseConfidence entry.
        """
        entry = PhaseConfidence(
            phase=phase,
            confidence=max(0.0, min(1.0, confidence)),
            depth=len(self._entries),
            metadata=metadata,
        )
        self._entries.append(entry)
        _logger.debug(
            "Confidence recorded: phase=%s confidence=%.3f depth=%d",
            phase,
            entry.confidence,
            entry.depth,
        )
        return entry

    def should_abort(self) -> AbortRecommendation:
        """
        Check if the pipeline should abort based on confidence trajectory.

        Checks:
        1. Latest confidence below depth-adjusted floor
        2. Sharp drop between consecutive phases
        3. Average confidence below global floor

        Returns:
            AbortRecommendation with decision and reasoning.
        """
        if not self._entries:
            return AbortRecommendation(
                should_abort=False,
                reason="No confidence data yet",
                confidence=1.0,
                threshold=self._abort_threshold,
            )

        latest = self._entries[-1]
        depth_floor = DEPTH_FLOOR.get(latest.depth, 0.10)

        # Check 1: Below depth floor
        if latest.confidence < depth_floor:
            return AbortRecommendation(
                should_abort=True,
                reason=f"Confidence {latest.confidence:.2f} below floor "
                f"{depth_floor:.2f} at depth {latest.depth} ({latest.phase})",
                confidence=latest.confidence,
                threshold=depth_floor,
            )

        # Check 2: Sharp drop
        if len(self._entries) >= 2:
            prev = self._entries[-2]
            drop = prev.confidence - latest.confidence
            if drop > DROP_THRESHOLD:
                return AbortRecommendation(
                    should_abort=True,
                    reason=f"Sharp confidence drop: {prev.confidence:.2f} -> "
                    f"{latest.confidence:.2f} (Δ={drop:.2f} > {DROP_THRESHOLD})",
                    confidence=latest.confidence,
                    threshold=prev.confidence - DROP_THRESHOLD,
                )

        # Check 3: Average below floor
        avg = sum(e.confidence for e in self._entries) / len(self._entries)
        if avg < self._abort_threshold:
            return AbortRecommendation(
                should_abort=True,
                reason=f"Average confidence {avg:.2f} below threshold {self._abort_threshold:.2f}",
                confidence=avg,
                threshold=self._abort_threshold,
            )

        return AbortRecommendation(
            should_abort=False,
            reason="Confidence within acceptable range",
            confidence=latest.confidence,
            threshold=depth_floor,
        )

    def get_trajectory(self) -> ConfidenceTrajectory:
        """
        Analyze the full confidence trajectory.

        Returns:
            ConfidenceTrajectory with trend, stats, and all entries.
        """
        if not self._entries:
            return ConfidenceTrajectory(
                entries=[],
                trend="insufficient_data",
                average=0.0,
                minimum=0.0,
                maximum=0.0,
                latest=0.0,
                drop_detected=False,
            )

        confidences = [e.confidence for e in self._entries]
        avg = sum(confidences) / len(confidences)
        trend = self._compute_trend(confidences)
        drop = self._detect_drop(confidences)

        return ConfidenceTrajectory(
            entries=list(self._entries),
            trend=trend,
            average=avg,
            minimum=min(confidences),
            maximum=max(confidences),
            latest=confidences[-1],
            drop_detected=drop,
        )

    @property
    def latest_confidence(self) -> float:
        """Get the most recent confidence score."""
        if not self._entries:
            return 1.0
        return self._entries[-1].confidence

    @property
    def phase_count(self) -> int:
        """Number of phases recorded."""
        return len(self._entries)

    def reset(self) -> None:
        """Reset for a new task."""
        self._entries.clear()

    def to_dict(self) -> dict[str, Any]:
        """Serialize monitor state."""
        traj = self.get_trajectory()
        return traj.to_dict()

    # =========================================================================
    # Private Helpers
    # =========================================================================

    @staticmethod
    def _compute_trend(values: list[float]) -> str:
        """Compute trend from sequence of values."""
        if len(values) < 2:
            return "insufficient_data"

        # Simple linear regression slope
        n = len(values)
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        denominator = sum((i - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return "stable"

        slope = numerator / denominator

        if slope > 0.02:
            return "improving"
        elif slope < -0.02:
            return "declining"
        return "stable"

    @staticmethod
    def _detect_drop(values: list[float]) -> bool:
        """Detect any sharp drop in the sequence."""
        return any(values[i - 1] - values[i] > DROP_THRESHOLD for i in range(1, len(values)))
