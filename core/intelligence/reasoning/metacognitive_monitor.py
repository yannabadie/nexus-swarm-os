"""
NEXUS V12.4 - Metacognitive Step-Level Monitor (MASC)

Unsupervised anomaly detection for multi-agent execution steps.
Catches errors the agent itself does not recognize (blind spots).

Based on: MASC - Metacognitive Self-Correction for MAS (arXiv:2510.14319)

Two components:
1. Next-Execution Reconstruction: predicts expected step embedding from history
2. Prototype-Guided Enhancement: learned prototype of 'normal' step embeddings

Uses lightweight TF-IDF cosine similarity (no external models required).

Usage:
    monitor = get_metacognitive_monitor()

    # During Phase 4 execution, after each step:
    score = monitor.score_step(
        step_output="Generated SQL query for auth table",
        history=["Analyzed schema", "Identified auth tables"],
        task_type="debugging",
    )
    if monitor.should_correct(score):
        # Trigger MARS reflection + correction
        ...
"""

import logging
import math
import threading
from collections import Counter
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class AnomalyScore:
    """Result of step-level anomaly scoring."""

    reconstruction_distance: float  # Distance from predicted embedding
    prototype_distance: float  # Distance from learned prototype
    composite_score: float  # Weighted combination (higher = more anomalous)
    step_output_preview: str = ""  # First 100 chars of step output
    task_type: str = ""

    @property
    def is_anomalous(self) -> bool:
        """Whether this score exceeds the default threshold."""
        return self.composite_score > 2.0


@dataclass
class StepPrototype:
    """Running average representation of 'normal' steps per task type."""

    term_frequencies: dict[str, float] = field(default_factory=dict)
    observation_count: int = 0
    avg_length: float = 0.0

    def update(self, tf_vector: dict[str, float], text_length: int) -> None:
        """Update prototype with a new observation via running average."""
        self.observation_count += 1
        n = self.observation_count
        # Running average of term frequencies
        for term, freq in tf_vector.items():
            old = self.term_frequencies.get(term, 0.0)
            self.term_frequencies[term] = old + (freq - old) / n
        # Running average of text length
        self.avg_length = self.avg_length + (text_length - self.avg_length) / n


@dataclass
class MonitorStats:
    """Statistics for the metacognitive monitor."""

    total_steps_scored: int
    anomalies_detected: int
    task_types_tracked: list[str]
    avg_composite_score: float


# =============================================================================
# TF-IDF Lightweight Embedding
# =============================================================================


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer."""
    # Lowercase and split on non-alphanumeric
    tokens = []
    current = []
    for ch in text.lower():
        if ch.isalnum() or ch == "_":
            current.append(ch)
        else:
            if current:
                tokens.append("".join(current))
                current = []
    if current:
        tokens.append("".join(current))
    return tokens


def _term_frequency(tokens: list[str]) -> dict[str, float]:
    """Compute normalized term frequency vector."""
    counts = Counter(tokens)
    total = len(tokens) if tokens else 1
    return {term: count / total for term, count in counts.items()}


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF vectors."""
    if not a or not b:
        return 0.0

    # Dot product
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in set(a) | set(b))

    # Magnitudes
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))

    if mag_a < 1e-10 or mag_b < 1e-10:
        return 0.0

    return dot / (mag_a * mag_b)


# =============================================================================
# Metacognitive Monitor
# =============================================================================


class MetacognitiveMonitor:
    """
    Unsupervised step-level anomaly detection for multi-agent execution.

    Uses TF-IDF cosine similarity as a lightweight embedding proxy.
    Catches cascading failures that self-reported confidence misses.
    Architecture-agnostic: works across all swarm modes.
    """

    DEFAULT_THRESHOLD = 2.0  # Standard deviations for anomaly
    HISTORY_WEIGHT = 0.6  # Weight for reconstruction vs prototype
    PROTOTYPE_WEIGHT = 0.4
    MIN_PROTOTYPE_SAMPLES = 3  # Minimum samples before prototype is reliable

    def __init__(self, threshold: float = 0.0):
        self._threshold = threshold or self.DEFAULT_THRESHOLD
        self._prototypes: dict[str, StepPrototype] = {}
        self._total_scored = 0
        self._anomalies_detected = 0
        self._score_history: list[float] = []  # For computing z-scores
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def score_step(
        self,
        step_output: str,
        history: list[str] | None = None,
        task_type: str = "general",
    ) -> AnomalyScore:
        """
        Score a step's output for anomalousness.

        Args:
            step_output: The output text of the current step
            history: Previous step outputs in this execution
            task_type: Task type for prototype lookup

        Returns:
            AnomalyScore with reconstruction and prototype distances
        """
        if not step_output or not step_output.strip():
            return AnomalyScore(
                reconstruction_distance=0.0,
                prototype_distance=0.0,
                composite_score=0.0,
                step_output_preview="",
                task_type=task_type,
            )

        tokens = _tokenize(step_output)
        tf = _term_frequency(tokens)

        # 1. Reconstruction distance: compare with predicted from history
        reconstruction_dist = self._reconstruction_distance(tf, history or [])

        # 2. Prototype distance: compare with learned normal
        prototype_dist = self._prototype_distance(tf, task_type, len(step_output))

        # 3. Composite score (higher = more anomalous)
        composite = self.HISTORY_WEIGHT * reconstruction_dist + self.PROTOTYPE_WEIGHT * prototype_dist

        # Convert to z-score relative to historical scores
        with self._lock:
            self._score_history.append(composite)
            if len(self._score_history) > 200:
                self._score_history = self._score_history[-200:]
            self._total_scored += 1

        z_score = self._to_z_score(composite)

        # Update prototype with this step (it's the new "normal" data point)
        self._update_prototype(tf, task_type, len(step_output))

        score = AnomalyScore(
            reconstruction_distance=reconstruction_dist,
            prototype_distance=prototype_dist,
            composite_score=z_score,
            step_output_preview=step_output[:100],
            task_type=task_type,
        )

        if score.is_anomalous:
            with self._lock:
                self._anomalies_detected += 1
            logger.warning(
                f"MASC: Anomalous step detected (z={z_score:.2f}) for task_type={task_type}: {step_output[:80]}"
            )

        return score

    def should_correct(self, score: AnomalyScore) -> bool:
        """
        Determine if a step should be corrected based on its anomaly score.

        Args:
            score: The AnomalyScore from score_step()

        Returns:
            True if the step is anomalous and should trigger correction
        """
        return score.composite_score > self._threshold

    def get_stats(self) -> MonitorStats:
        """Get monitor statistics."""
        avg = 0.0
        if self._score_history:
            avg = sum(self._score_history) / len(self._score_history)

        return MonitorStats(
            total_steps_scored=self._total_scored,
            anomalies_detected=self._anomalies_detected,
            task_types_tracked=list(self._prototypes.keys()),
            avg_composite_score=avg,
        )

    @property
    def threshold(self) -> float:
        return self._threshold

    # -------------------------------------------------------------------------
    # Internal: Reconstruction
    # -------------------------------------------------------------------------

    def _reconstruction_distance(self, current_tf: dict[str, float], history: list[str]) -> float:
        """
        Predict expected step embedding from history, measure distance.

        The 'prediction' is the centroid of recent history TF vectors.
        Distance = 1 - cosine_similarity(current, predicted).
        """
        if not history:
            return 0.0  # No history = no reconstruction possible

        # Build predicted TF as average of history
        history_tfs = [_term_frequency(_tokenize(h)) for h in history[-5:]]  # Last 5 steps
        predicted_tf: dict[str, float] = {}
        n = len(history_tfs)
        for tf in history_tfs:
            for term, freq in tf.items():
                predicted_tf[term] = predicted_tf.get(term, 0.0) + freq / n

        similarity = _cosine_similarity(current_tf, predicted_tf)
        return 1.0 - similarity  # Distance = 1 - similarity

    # -------------------------------------------------------------------------
    # Internal: Prototype
    # -------------------------------------------------------------------------

    def _prototype_distance(
        self,
        current_tf: dict[str, float],
        task_type: str,
        text_length: int,
    ) -> float:
        """
        Compare current step with learned prototype for task type.

        Returns distance = 1 - cosine_similarity if prototype has enough samples,
        otherwise 0.0 (no penalty for sparse data — prototype-guided stabilization).
        """
        proto = self._prototypes.get(task_type)
        if not proto or proto.observation_count < self.MIN_PROTOTYPE_SAMPLES:
            return 0.0  # Not enough data for reliable prototype

        similarity = _cosine_similarity(current_tf, proto.term_frequencies)

        # Length anomaly: if text is very different length from prototype avg
        if proto.avg_length > 0:
            length_ratio = text_length / proto.avg_length
            # Penalize extreme length deviations (< 0.2x or > 5x)
            if length_ratio < 0.2 or length_ratio > 5.0:
                return max(1.0 - similarity, 0.5)

        return 1.0 - similarity

    def _update_prototype(self, tf: dict[str, float], task_type: str, text_length: int) -> None:
        """Update the prototype for a task type with new observation."""
        with self._lock:
            if task_type not in self._prototypes:
                self._prototypes[task_type] = StepPrototype()
            self._prototypes[task_type].update(tf, text_length)

    # -------------------------------------------------------------------------
    # Internal: Z-Score
    # -------------------------------------------------------------------------

    def _to_z_score(self, raw_score: float) -> float:
        """Convert raw composite score to z-score using historical distribution."""
        if len(self._score_history) < 5:
            # Not enough history; return raw score scaled
            return raw_score * 2.0

        mean = sum(self._score_history) / len(self._score_history)
        variance = sum((s - mean) ** 2 for s in self._score_history) / len(self._score_history)
        std = math.sqrt(variance) if variance > 0 else 1e-6

        if std < 1e-10:
            return 0.0  # All scores identical = nothing is anomalous

        return (raw_score - mean) / std


# =============================================================================
# Singleton
# =============================================================================

_instance: MetacognitiveMonitor | None = None
_instance_lock = threading.Lock()


def get_metacognitive_monitor() -> MetacognitiveMonitor:
    """Get or create the singleton MetacognitiveMonitor instance."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MetacognitiveMonitor()
    return _instance


def reset_metacognitive_monitor() -> None:
    """Reset the singleton (for testing)."""
    global _instance
    _instance = None
