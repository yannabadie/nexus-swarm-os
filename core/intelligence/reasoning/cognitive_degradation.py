"""
Cognitive Degradation Detector - Detect declining agent reasoning quality.

V12.4 COGNITIVE BOOST

Monitors agent reasoning evaluations over a rolling window and detects
degradation patterns:
- Trend decline: Composite score dropping over recent evaluations
- Sustained low quality: Extended periods below threshold
- Calibration drift: Confidence diverging from actual outcomes
- Sudden collapse: Sharp single-evaluation drops

When degradation is detected, recommends mitigations:
- CONTEXT_RESET: Context window may be saturated
- AGENT_SWITCH: Switch to the other agent for this task type
- REDUCE_LOAD: Too many concurrent tasks degrading quality
- NONE: Quality is stable

Based on QSAF framework patterns (arxiv:2507.15330).

Usage:
    from core.intelligence.reasoning.cognitive_degradation import get_degradation_detector

    detector = get_degradation_detector()
    signal = detector.check_agent("claude")
    if signal.degraded:
        print(f"Degradation: {signal.reason}, mitigation: {signal.mitigation}")
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .reasoning_quality_scorer import (
    get_quality_scorer,
)

_logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================


class Mitigation(str, Enum):
    """Recommended mitigation action."""

    NONE = "none"
    CONTEXT_RESET = "context_reset"
    AGENT_SWITCH = "agent_switch"
    REDUCE_LOAD = "reduce_load"


class DegradationReason(str, Enum):
    """Why degradation was detected."""

    STABLE = "stable"
    TREND_DECLINE = "trend_decline"
    SUSTAINED_LOW = "sustained_low"
    CALIBRATION_DRIFT = "calibration_drift"
    SUDDEN_COLLAPSE = "sudden_collapse"


@dataclass
class DegradationSignal:
    """Result of a degradation check for a single agent."""

    agent_id: str = ""
    degraded: bool = False
    reason: DegradationReason = DegradationReason.STABLE
    mitigation: Mitigation = Mitigation.NONE
    current_composite: float = 0.0
    trend_slope: float = 0.0  # Negative = declining
    window_size: int = 0
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "degraded": self.degraded,
            "reason": self.reason.value,
            "mitigation": self.mitigation.value,
            "current_composite": round(self.current_composite, 4),
            "trend_slope": round(self.trend_slope, 6),
            "window_size": self.window_size,
            "details": self.details,
        }


@dataclass
class DetectorStats:
    """Overall detector statistics."""

    checks_performed: int = 0
    degradations_detected: int = 0
    agents_monitored: int = 0
    mitigations_issued: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks_performed": self.checks_performed,
            "degradations_detected": self.degradations_detected,
            "agents_monitored": self.agents_monitored,
            "mitigations_issued": dict(self.mitigations_issued),
        }


# =============================================================================
# Detector
# =============================================================================


class CognitiveDegradationDetector:
    """
    Monitors agent reasoning quality for degradation patterns.

    Uses a rolling window of recent evaluations from the ReasoningQualityScorer
    to compute trend analysis and detect quality decline.

    Thresholds:
    - trend_threshold: Slope below this triggers TREND_DECLINE (-0.02 default)
    - low_quality_threshold: Composite below this is "low" (0.4 default)
    - sustained_low_count: Consecutive low evals to trigger SUSTAINED_LOW (3)
    - collapse_drop: Single-eval drop this large triggers SUDDEN_COLLAPSE (0.3)
    - calibration_drift_threshold: Avg calibration below this triggers drift (0.5)
    """

    def __init__(
        self,
        window_size: int = 10,
        trend_threshold: float = -0.02,
        low_quality_threshold: float = 0.4,
        sustained_low_count: int = 3,
        collapse_drop: float = 0.3,
        calibration_drift_threshold: float = 0.5,
    ) -> None:
        self._window_size = window_size
        self._trend_threshold = trend_threshold
        self._low_quality_threshold = low_quality_threshold
        self._sustained_low_count = sustained_low_count
        self._collapse_drop = collapse_drop
        self._calibration_drift_threshold = calibration_drift_threshold
        self._lock = threading.Lock()
        self._checks_performed = 0
        self._degradations_detected = 0
        self._mitigations: dict[str, int] = {}
        self._agents_checked: set = set()

    # =========================================================================
    # Core Check
    # =========================================================================

    def check_agent(self, agent_id: str) -> DegradationSignal:
        """
        Check if an agent shows cognitive degradation.

        Fetches recent evaluations from the global quality scorer and
        analyzes them for degradation patterns.

        Args:
            agent_id: Agent to check (e.g., "claude", "gemini").

        Returns:
            DegradationSignal with degraded flag, reason, and mitigation.
        """
        scorer = get_quality_scorer()
        recent = scorer.get_recent_evaluations(
            limit=self._window_size,
            agent_id=agent_id,
        )
        # get_recent_evaluations returns most-recent-first; reverse to chronological
        recent = list(reversed(recent))

        with self._lock:
            self._checks_performed += 1
            self._agents_checked.add(agent_id)

        if len(recent) < 2:
            return DegradationSignal(
                agent_id=agent_id,
                window_size=len(recent),
                details="Insufficient data for degradation analysis",
            )

        composites = [e.composite_score for e in recent]
        calibrations = [e.confidence_calibration for e in recent]
        current = composites[-1] if composites else 0.0

        # Check patterns in priority order (most severe first)
        signal = self._check_sudden_collapse(agent_id, composites, current)
        if signal.degraded:
            self._record_degradation(signal)
            return signal

        signal = self._check_sustained_low(agent_id, composites, current)
        if signal.degraded:
            self._record_degradation(signal)
            return signal

        signal = self._check_trend_decline(agent_id, composites, current)
        if signal.degraded:
            self._record_degradation(signal)
            return signal

        signal = self._check_calibration_drift(
            agent_id,
            calibrations,
            current,
        )
        if signal.degraded:
            self._record_degradation(signal)
            return signal

        return DegradationSignal(
            agent_id=agent_id,
            current_composite=current,
            trend_slope=self._compute_slope(composites),
            window_size=len(recent),
            details="Quality stable",
        )

    # =========================================================================
    # Pattern Checks
    # =========================================================================

    def _check_sudden_collapse(
        self,
        agent_id: str,
        composites: list[float],
        current: float,
    ) -> DegradationSignal:
        """Detect a sharp single-evaluation quality drop."""
        if len(composites) < 2:
            return DegradationSignal(agent_id=agent_id)

        prev = composites[-2]
        drop = prev - current

        if drop >= self._collapse_drop:
            return DegradationSignal(
                agent_id=agent_id,
                degraded=True,
                reason=DegradationReason.SUDDEN_COLLAPSE,
                mitigation=Mitigation.CONTEXT_RESET,
                current_composite=current,
                trend_slope=self._compute_slope(composites),
                window_size=len(composites),
                details=(f"Quality dropped {drop:.2f} in one evaluation ({prev:.2f} -> {current:.2f})"),
            )

        return DegradationSignal(agent_id=agent_id)

    def _check_sustained_low(
        self,
        agent_id: str,
        composites: list[float],
        current: float,
    ) -> DegradationSignal:
        """Detect extended periods of low quality."""
        tail = composites[-self._sustained_low_count :]
        if len(tail) < self._sustained_low_count:
            return DegradationSignal(agent_id=agent_id)

        if all(c < self._low_quality_threshold for c in tail):
            return DegradationSignal(
                agent_id=agent_id,
                degraded=True,
                reason=DegradationReason.SUSTAINED_LOW,
                mitigation=Mitigation.AGENT_SWITCH,
                current_composite=current,
                trend_slope=self._compute_slope(composites),
                window_size=len(composites),
                details=(
                    f"Last {self._sustained_low_count} evaluations all below "
                    f"{self._low_quality_threshold}: {[round(c, 2) for c in tail]}"
                ),
            )

        return DegradationSignal(agent_id=agent_id)

    def _check_trend_decline(
        self,
        agent_id: str,
        composites: list[float],
        current: float,
    ) -> DegradationSignal:
        """Detect a declining trend via linear regression slope."""
        slope = self._compute_slope(composites)

        if slope < self._trend_threshold:
            return DegradationSignal(
                agent_id=agent_id,
                degraded=True,
                reason=DegradationReason.TREND_DECLINE,
                mitigation=Mitigation.REDUCE_LOAD,
                current_composite=current,
                trend_slope=slope,
                window_size=len(composites),
                details=(f"Declining trend (slope={slope:.4f}, threshold={self._trend_threshold})"),
            )

        return DegradationSignal(agent_id=agent_id)

    def _check_calibration_drift(
        self,
        agent_id: str,
        calibrations: list[float],
        current_composite: float,
    ) -> DegradationSignal:
        """Detect confidence-outcome calibration divergence."""
        if not calibrations:
            return DegradationSignal(agent_id=agent_id)

        avg_cal = sum(calibrations) / len(calibrations)

        if avg_cal < self._calibration_drift_threshold:
            return DegradationSignal(
                agent_id=agent_id,
                degraded=True,
                reason=DegradationReason.CALIBRATION_DRIFT,
                mitigation=Mitigation.REDUCE_LOAD,
                current_composite=current_composite,
                trend_slope=self._compute_slope([current_composite] * len(calibrations)),
                window_size=len(calibrations),
                details=(f"Avg calibration {avg_cal:.2f} below threshold {self._calibration_drift_threshold}"),
            )

        return DegradationSignal(agent_id=agent_id)

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _compute_slope(values: list[float]) -> float:
        """Compute simple linear regression slope over ordered values."""
        n = len(values)
        if n < 2:
            return 0.0

        # Simple least-squares: slope = (n*sum(xy) - sum(x)*sum(y)) / (n*sum(x^2) - sum(x)^2)
        sum_x = sum(range(n))
        sum_y = sum(values)
        sum_xy = sum(i * v for i, v in enumerate(values))
        sum_x2 = sum(i * i for i in range(n))

        denom = n * sum_x2 - sum_x * sum_x
        if denom == 0:
            return 0.0

        return (n * sum_xy - sum_x * sum_y) / denom

    def _record_degradation(self, signal: DegradationSignal) -> None:
        """Record a detected degradation for stats."""
        with self._lock:
            self._degradations_detected += 1
            mit_key = signal.mitigation.value
            self._mitigations[mit_key] = self._mitigations.get(mit_key, 0) + 1

        _logger.warning(
            "Cognitive degradation detected for %s: %s (mitigation: %s)",
            signal.agent_id,
            signal.reason.value,
            signal.mitigation.value,
        )

    # =========================================================================
    # Statistics
    # =========================================================================

    def get_stats(self) -> DetectorStats:
        """Get detector statistics."""
        with self._lock:
            return DetectorStats(
                checks_performed=self._checks_performed,
                degradations_detected=self._degradations_detected,
                agents_monitored=len(self._agents_checked),
                mitigations_issued=dict(self._mitigations),
            )

    def clear(self) -> None:
        """Reset detector state."""
        with self._lock:
            self._checks_performed = 0
            self._degradations_detected = 0
            self._mitigations.clear()
            self._agents_checked.clear()


# =============================================================================
# Global Singleton
# =============================================================================

_detector: CognitiveDegradationDetector | None = None
_detector_lock = threading.Lock()


def get_degradation_detector() -> CognitiveDegradationDetector:
    """Get or create the global degradation detector."""
    global _detector
    if _detector is None:
        with _detector_lock:
            if _detector is None:
                _detector = CognitiveDegradationDetector()
    return _detector


def reset_degradation_detector() -> None:
    """Reset the global degradation detector (for testing)."""
    global _detector
    _detector = None
