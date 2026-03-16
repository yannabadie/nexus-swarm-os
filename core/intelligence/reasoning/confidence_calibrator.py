"""
NEXUS V12.4 - Confidence Calibrator (arXiv:2404.09127)

Training-free confidence calibration for multi-agent deliberation.
Detects and corrects overconfidence/underconfidence in agent outputs
by tracking calibration history and outcome correlation.

Based on: "Confidence Calibration and Rationalization for LLMs
via Multi-Agent Deliberation" (arXiv:2404.09127)

Key insight: Agents that express confidence and see peers' reasoning
produce significantly better-calibrated confidence scores.

This module:
1. Records confidence estimates paired with outcomes
2. Computes Expected Calibration Error (ECE) per agent
3. Applies Platt-scaling-inspired correction to raw confidence
4. Detects overconfidence/underconfidence bias

Usage:
    calibrator = get_confidence_calibrator()

    # Record an agent's confidence vs actual outcome
    calibrator.record(
        agent_id="claude",
        stated_confidence=0.9,
        actual_success=True,
        task_type="coding",
    )

    # Get calibrated confidence from raw
    calibrated = calibrator.calibrate(
        agent_id="claude",
        raw_confidence=0.85,
    )
    # calibrated.adjusted_confidence may be lower if agent is overconfident

    # Check calibration quality
    profile = calibrator.get_agent_profile("claude")
    # profile.ece = 0.15, profile.bias = "overconfident"
"""

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


class ConfidenceBias(Enum):
    """Direction of confidence miscalibration."""

    WELL_CALIBRATED = "well_calibrated"
    OVERCONFIDENT = "overconfident"
    UNDERCONFIDENT = "underconfident"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class CalibrationRecord:
    """A single confidence-outcome observation."""

    agent_id: str
    stated_confidence: float  # Agent's stated confidence [0, 1]
    actual_success: bool  # True if the output was correct/successful
    task_type: str = "general"
    timestamp: float = field(default_factory=time.time)


@dataclass
class CalibratedConfidence:
    """Result of calibrating a raw confidence score."""

    raw_confidence: float  # Original stated confidence
    adjusted_confidence: float  # Calibrated confidence
    correction: float  # Amount of adjustment (positive = boosted)
    agent_bias: ConfidenceBias  # Detected bias direction
    reliability: float  # How reliable is this calibration (0-1)

    @property
    def is_significant_correction(self) -> bool:
        """Whether the correction was meaningful (> 0.1)."""
        return abs(self.correction) > 0.1


@dataclass
class AgentCalibrationProfile:
    """Calibration statistics for a single agent."""

    agent_id: str
    total_observations: int
    ece: float  # Expected Calibration Error (lower = better)
    bias: ConfidenceBias
    avg_stated_confidence: float
    avg_actual_success_rate: float
    correction_factor: float  # Multiplicative correction
    bins: dict[str, dict]  # Binned calibration data


@dataclass
class CalibratorStats:
    """Overall calibrator statistics."""

    total_records: int
    agents_tracked: list[str]
    avg_ece: float
    best_calibrated_agent: str
    worst_calibrated_agent: str


# =============================================================================
# Confidence Calibrator
# =============================================================================


class ConfidenceCalibrator:
    """
    Training-free confidence calibration for multi-agent systems.

    Tracks confidence-outcome pairs per agent and computes calibration
    curves. Uses binned calibration with Platt-scaling-inspired correction
    to adjust raw confidence scores.

    No external models required — pure statistical calibration.
    """

    NUM_BINS = 10  # Number of calibration bins
    MIN_OBSERVATIONS = 5  # Minimum observations before calibrating
    MAX_HISTORY = 500  # Max records per agent
    ECE_GOOD_THRESHOLD = 0.1  # ECE below this = well calibrated
    BIAS_THRESHOLD = 0.05  # Difference threshold for bias detection

    def __init__(self):
        self._records: dict[str, list[CalibrationRecord]] = defaultdict(list)
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def record(
        self,
        agent_id: str,
        stated_confidence: float,
        actual_success: bool,
        task_type: str = "general",
    ) -> None:
        """
        Record a confidence-outcome pair for an agent.

        Args:
            agent_id: Agent identifier (e.g., "claude", "gemini")
            stated_confidence: Agent's stated confidence [0, 1]
            actual_success: Whether the output was correct/successful
            task_type: Task type for finer-grained calibration
        """
        confidence = max(0.0, min(1.0, stated_confidence))

        record = CalibrationRecord(
            agent_id=agent_id,
            stated_confidence=confidence,
            actual_success=actual_success,
            task_type=task_type,
        )

        with self._lock:
            history = self._records[agent_id]
            history.append(record)
            # Cap history size
            if len(history) > self.MAX_HISTORY:
                self._records[agent_id] = history[-self.MAX_HISTORY :]

    def calibrate(
        self,
        agent_id: str,
        raw_confidence: float,
    ) -> CalibratedConfidence:
        """
        Calibrate a raw confidence score using the agent's history.

        Args:
            agent_id: Agent identifier
            raw_confidence: Raw confidence score [0, 1]

        Returns:
            CalibratedConfidence with adjusted score and bias info
        """
        raw = max(0.0, min(1.0, raw_confidence))

        with self._lock:
            history = self._records.get(agent_id, [])

        if len(history) < self.MIN_OBSERVATIONS:
            return CalibratedConfidence(
                raw_confidence=raw,
                adjusted_confidence=raw,
                correction=0.0,
                agent_bias=ConfidenceBias.INSUFFICIENT_DATA,
                reliability=0.0,
            )

        # Compute calibration curve
        bins = self._compute_bins(history)
        bias = self._detect_bias(history)
        correction_factor = self._compute_correction_factor(history)
        reliability = min(1.0, len(history) / 50.0)

        # Apply correction
        adjusted = self._apply_correction(raw, bins, correction_factor)

        return CalibratedConfidence(
            raw_confidence=raw,
            adjusted_confidence=adjusted,
            correction=adjusted - raw,
            agent_bias=bias,
            reliability=reliability,
        )

    def get_agent_profile(self, agent_id: str) -> AgentCalibrationProfile:
        """Get calibration profile for a specific agent."""
        with self._lock:
            history = self._records.get(agent_id, [])

        if not history:
            return AgentCalibrationProfile(
                agent_id=agent_id,
                total_observations=0,
                ece=0.0,
                bias=ConfidenceBias.INSUFFICIENT_DATA,
                avg_stated_confidence=0.0,
                avg_actual_success_rate=0.0,
                correction_factor=1.0,
                bins={},
            )

        bins = self._compute_bins(history)
        ece = self._compute_ece(bins)
        bias = self._detect_bias(history)
        correction = self._compute_correction_factor(history)

        avg_conf = sum(r.stated_confidence for r in history) / len(history)
        avg_success = sum(1 for r in history if r.actual_success) / len(history)

        return AgentCalibrationProfile(
            agent_id=agent_id,
            total_observations=len(history),
            ece=ece,
            bias=bias,
            avg_stated_confidence=avg_conf,
            avg_actual_success_rate=avg_success,
            correction_factor=correction,
            bins={k: v for k, v in bins.items()},
        )

    def get_stats(self) -> CalibratorStats:
        """Get overall calibrator statistics."""
        with self._lock:
            all_agents = list(self._records.keys())
            total = sum(len(v) for v in self._records.values())

        if not all_agents:
            return CalibratorStats(
                total_records=0,
                agents_tracked=[],
                avg_ece=0.0,
                best_calibrated_agent="",
                worst_calibrated_agent="",
            )

        # Compute ECE per agent
        eces = {}
        for agent_id in all_agents:
            profile = self.get_agent_profile(agent_id)
            if profile.total_observations >= self.MIN_OBSERVATIONS:
                eces[agent_id] = profile.ece

        if not eces:
            return CalibratorStats(
                total_records=total,
                agents_tracked=all_agents,
                avg_ece=0.0,
                best_calibrated_agent=all_agents[0] if all_agents else "",
                worst_calibrated_agent=all_agents[0] if all_agents else "",
            )

        avg_ece = sum(eces.values()) / len(eces)
        best = min(eces, key=eces.get)
        worst = max(eces, key=eces.get)

        return CalibratorStats(
            total_records=total,
            agents_tracked=all_agents,
            avg_ece=avg_ece,
            best_calibrated_agent=best,
            worst_calibrated_agent=worst,
        )

    # -------------------------------------------------------------------------
    # Internal: Binned Calibration
    # -------------------------------------------------------------------------

    def _compute_bins(self, history: list[CalibrationRecord]) -> dict[str, dict]:
        """Compute calibration bins from history."""
        bins: dict[str, dict] = {}

        for i in range(self.NUM_BINS):
            low = i / self.NUM_BINS
            high = (i + 1) / self.NUM_BINS
            bin_key = f"{low:.1f}-{high:.1f}"

            bin_records = [
                r
                for r in history
                if low <= r.stated_confidence < high or (i == self.NUM_BINS - 1 and r.stated_confidence == high)
            ]

            if bin_records:
                avg_conf = sum(r.stated_confidence for r in bin_records) / len(bin_records)
                avg_acc = sum(1 for r in bin_records if r.actual_success) / len(bin_records)
                bins[bin_key] = {
                    "avg_confidence": avg_conf,
                    "avg_accuracy": avg_acc,
                    "count": len(bin_records),
                    "gap": avg_conf - avg_acc,
                }
            else:
                bins[bin_key] = {
                    "avg_confidence": (low + high) / 2,
                    "avg_accuracy": 0.0,
                    "count": 0,
                    "gap": 0.0,
                }

        return bins

    def _compute_ece(self, bins: dict[str, dict]) -> float:
        """Compute Expected Calibration Error from bins."""
        total_samples = sum(b["count"] for b in bins.values())
        if total_samples == 0:
            return 0.0

        ece = sum((b["count"] / total_samples) * abs(b["gap"]) for b in bins.values() if b["count"] > 0)

        return ece

    # -------------------------------------------------------------------------
    # Internal: Bias Detection
    # -------------------------------------------------------------------------

    def _detect_bias(self, history: list[CalibrationRecord]) -> ConfidenceBias:
        """Detect if the agent is systematically over/under-confident."""
        if len(history) < self.MIN_OBSERVATIONS:
            return ConfidenceBias.INSUFFICIENT_DATA

        avg_confidence = sum(r.stated_confidence for r in history) / len(history)
        avg_success = sum(1 for r in history if r.actual_success) / len(history)

        gap = avg_confidence - avg_success

        if abs(gap) <= self.BIAS_THRESHOLD:
            return ConfidenceBias.WELL_CALIBRATED
        elif gap > 0:
            return ConfidenceBias.OVERCONFIDENT
        else:
            return ConfidenceBias.UNDERCONFIDENT

    # -------------------------------------------------------------------------
    # Internal: Correction
    # -------------------------------------------------------------------------

    def _compute_correction_factor(self, history: list[CalibrationRecord]) -> float:
        """Compute multiplicative correction factor."""
        if len(history) < self.MIN_OBSERVATIONS:
            return 1.0

        avg_confidence = sum(r.stated_confidence for r in history) / len(history)
        avg_success = sum(1 for r in history if r.actual_success) / len(history)

        if avg_confidence < 0.01:
            return 1.0

        return avg_success / avg_confidence

    def _apply_correction(
        self,
        raw: float,
        bins: dict[str, dict],
        correction_factor: float,
    ) -> float:
        """Apply calibration correction to raw confidence."""
        # Find the bin this confidence falls into
        bin_idx = min(int(raw * self.NUM_BINS), self.NUM_BINS - 1)
        bin_key = f"{bin_idx / self.NUM_BINS:.1f}-{(bin_idx + 1) / self.NUM_BINS:.1f}"

        bin_data = bins.get(bin_key, {})
        bin_count = bin_data.get("count", 0)

        if bin_count >= 3:
            # Use bin-level correction (more precise)
            gap = bin_data.get("gap", 0.0)
            adjusted = raw - gap * 0.7  # Partial correction (70% of gap)
        else:
            # Use global correction factor
            adjusted = raw * correction_factor

        return max(0.0, min(1.0, adjusted))


# =============================================================================
# Singleton
# =============================================================================

_instance: ConfidenceCalibrator | None = None
_instance_lock = threading.Lock()


def get_confidence_calibrator() -> ConfidenceCalibrator:
    """Get or create the singleton ConfidenceCalibrator instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ConfidenceCalibrator()
    return _instance


def reset_confidence_calibrator() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
