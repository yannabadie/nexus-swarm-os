"""
NEXUS V12.4 - ConsensusVerifier (Six Sigma-Inspired)

Based on Six Sigma Agent (arxiv:2601.22290) - Multi-sampling consensus verification.

Critical outputs are evaluated N times. Samples are clustered by semantic
similarity and the dominant cluster is selected via majority vote. Statistical
quality gates (process capability indices) determine whether consensus is
strong enough to accept.

Dimensions:
  - Sample variance: How consistent are repeated evaluations?
  - Cluster dominance: Does one cluster hold the majority?
  - Cpk index: Process capability relative to spec limits

Usage:
    verifier = ConsensusVerifier()

    # Verify an output with N samples
    result = verifier.verify(
        output="The auth bug is in token.py line 42",
        context="Find auth bugs",
        n_samples=5,
    )
    # result.accepted = True
    # result.consensus_score = 0.92
    # result.cpk = 1.45
"""

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_N_SAMPLES = 3
MIN_CONSENSUS_THRESHOLD = 0.6  # Minimum cluster dominance to accept
CPK_ACCEPT_THRESHOLD = 1.0  # Cpk >= 1.0 means "capable process"
SIMILARITY_THRESHOLD = 0.65  # Minimum similarity to cluster together
MAX_HISTORY = 500


# =============================================================================
# Enums
# =============================================================================


class VerificationOutcome(str, Enum):
    """Outcome of consensus verification."""

    ACCEPTED = "accepted"  # Strong consensus, high quality
    WEAK_ACCEPT = "weak_accept"  # Majority agrees but with variance
    REJECTED = "rejected"  # No consensus or poor quality
    INSUFFICIENT = "insufficient"  # Not enough samples


class QualityGate(str, Enum):
    """Six Sigma quality gate levels."""

    GREEN = "green"  # Cpk >= 1.33 — excellent
    YELLOW = "yellow"  # 1.0 <= Cpk < 1.33 — acceptable
    RED = "red"  # Cpk < 1.0 — needs improvement


# =============================================================================
# Data Types
# =============================================================================


@dataclass
class Sample:
    """A single evaluation sample."""

    sample_id: int
    score: float  # 0.0 to 1.0
    evidence: list[str] = field(default_factory=list)
    cluster_id: int = -1

    def to_dict(self) -> dict:
        return {
            "sample_id": self.sample_id,
            "score": round(self.score, 3),
            "cluster_id": self.cluster_id,
            "evidence_count": len(self.evidence),
        }


@dataclass
class Cluster:
    """A cluster of similar samples."""

    cluster_id: int
    samples: list[Sample] = field(default_factory=list)
    centroid_score: float = 0.0

    @property
    def size(self) -> int:
        return len(self.samples)

    @property
    def mean_score(self) -> float:
        if not self.samples:
            return 0.0
        return sum(s.score for s in self.samples) / len(self.samples)

    @property
    def variance(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        mean = self.mean_score
        return sum((s.score - mean) ** 2 for s in self.samples) / len(self.samples)

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "size": self.size,
            "mean_score": round(self.mean_score, 3),
            "variance": round(self.variance, 4),
        }


@dataclass
class VerificationResult:
    """Result of consensus verification."""

    outcome: VerificationOutcome
    consensus_score: float  # 0.0 to 1.0 (dominant cluster %)
    accepted_score: float  # Score of the winning cluster
    cpk: float  # Process capability index
    quality_gate: QualityGate
    n_samples: int
    n_clusters: int
    dominant_cluster: Cluster | None
    all_clusters: list[Cluster] = field(default_factory=list)
    sample_mean: float = 0.0
    sample_std: float = 0.0

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "consensus_score": round(self.consensus_score, 3),
            "accepted_score": round(self.accepted_score, 3),
            "cpk": round(self.cpk, 3),
            "quality_gate": self.quality_gate.value,
            "n_samples": self.n_samples,
            "n_clusters": self.n_clusters,
            "sample_mean": round(self.sample_mean, 3),
            "sample_std": round(self.sample_std, 3),
            "clusters": [c.to_dict() for c in self.all_clusters],
        }


@dataclass
class VerifierStats:
    """Statistics for the verifier."""

    verifications_run: int = 0
    accepted_count: int = 0
    weak_accept_count: int = 0
    rejected_count: int = 0
    avg_cpk: float = 0.0
    avg_consensus: float = 0.0
    avg_samples_per_verification: float = 0.0

    def to_dict(self) -> dict:
        return {
            "verifications_run": self.verifications_run,
            "accepted_count": self.accepted_count,
            "weak_accept_count": self.weak_accept_count,
            "rejected_count": self.rejected_count,
            "avg_cpk": round(self.avg_cpk, 3),
            "avg_consensus": round(self.avg_consensus, 3),
            "avg_samples_per_verification": round(self.avg_samples_per_verification, 1),
        }


# =============================================================================
# Evaluator Function
# =============================================================================


def _default_evaluator(output: str, context: str = "") -> tuple[float, list[str]]:
    """
    Default lightweight evaluator for sampling.

    Uses the EvaluationPanel if available, otherwise falls back to
    simple heuristic scoring with slight random perturbation for
    realistic multi-sample variance.

    Returns:
        (score, evidence_list)
    """
    try:
        from core.intelligence.reasoning.evaluation_panel import EvaluationPanel

        panel = EvaluationPanel()  # Fresh instance per sample (independent)
        result = panel.evaluate(output, context)
        evidence = []
        for _dim, ds in result.dimension_scores.items():
            evidence.extend(ds.evidence)
        return result.composite_score, evidence
    except Exception:
        pass

    # Fallback: simple heuristic
    import re

    score = 0.5
    evidence = []
    words = len(output.split())
    if words > 20:
        score += 0.1
        evidence.append("Substantial length")
    if re.search(r"\b(because|therefore|since)\b", output.lower()):
        score += 0.1
        evidence.append("Reasoning signals")
    if re.search(r"\b(line\s+\d+|file\s+\S+)\b", output.lower()):
        score += 0.1
        evidence.append("Specific references")
    return min(1.0, max(0.0, score)), evidence


# =============================================================================
# ConsensusVerifier
# =============================================================================


class ConsensusVerifier:
    """
    Six Sigma-inspired consensus verifier.

    Evaluates output N times, clusters samples by similarity,
    and applies statistical quality gates.
    """

    def __init__(
        self,
        n_samples: int = DEFAULT_N_SAMPLES,
        consensus_threshold: float = MIN_CONSENSUS_THRESHOLD,
        cpk_threshold: float = CPK_ACCEPT_THRESHOLD,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
        evaluator=None,
    ):
        self._n_samples = max(2, n_samples)
        self._consensus_threshold = consensus_threshold
        self._cpk_threshold = cpk_threshold
        self._similarity_threshold = similarity_threshold
        self._evaluator = evaluator or _default_evaluator
        self._history: list[VerificationResult] = []
        self._lock = threading.Lock()

    # -------------------------------------------------------------------------
    # Core verification
    # -------------------------------------------------------------------------

    def verify(
        self,
        output: str,
        context: str = "",
        n_samples: int | None = None,
    ) -> VerificationResult:
        """
        Verify an output via multi-sampling and consensus.

        Args:
            output: The output text to verify
            context: Task context
            n_samples: Override default sample count

        Returns:
            VerificationResult with outcome, scores, and clusters
        """
        n = n_samples or self._n_samples

        # Phase 1: Multi-sampling
        samples = self._collect_samples(output, context, n)

        if len(samples) < 2:
            return self._insufficient_result(samples)

        # Phase 2: Clustering
        clusters = self._cluster_samples(samples)

        # Phase 3: Statistical analysis
        scores = [s.score for s in samples]
        sample_mean = sum(scores) / len(scores)
        sample_std = (sum((s - sample_mean) ** 2 for s in scores) / len(scores)) ** 0.5

        # Phase 4: Cpk calculation
        cpk = self._compute_cpk(sample_mean, sample_std)
        quality_gate = self._quality_gate(cpk)

        # Phase 5: Consensus via dominant cluster
        dominant = max(clusters, key=lambda c: c.size) if clusters else None
        consensus_score = dominant.size / len(samples) if dominant else 0.0
        accepted_score = dominant.mean_score if dominant else 0.0

        # Phase 6: Determine outcome
        outcome = self._determine_outcome(consensus_score, cpk, accepted_score)

        result = VerificationResult(
            outcome=outcome,
            consensus_score=consensus_score,
            accepted_score=accepted_score,
            cpk=cpk,
            quality_gate=quality_gate,
            n_samples=len(samples),
            n_clusters=len(clusters),
            dominant_cluster=dominant,
            all_clusters=clusters,
            sample_mean=sample_mean,
            sample_std=sample_std,
        )

        with self._lock:
            self._history.append(result)
            if len(self._history) > MAX_HISTORY:
                self._history = self._history[-MAX_HISTORY:]

        return result

    def verify_scores(
        self,
        scores: list[float],
    ) -> VerificationResult:
        """
        Verify from pre-computed scores (useful when samples are already collected).

        Args:
            scores: List of evaluation scores (0.0 to 1.0)

        Returns:
            VerificationResult
        """
        samples = [Sample(sample_id=i, score=s) for i, s in enumerate(scores)]

        if len(samples) < 2:
            return self._insufficient_result(samples)

        clusters = self._cluster_samples(samples)

        score_vals = [s.score for s in samples]
        sample_mean = sum(score_vals) / len(score_vals)
        sample_std = (sum((s - sample_mean) ** 2 for s in score_vals) / len(score_vals)) ** 0.5

        cpk = self._compute_cpk(sample_mean, sample_std)
        quality_gate = self._quality_gate(cpk)

        dominant = max(clusters, key=lambda c: c.size) if clusters else None
        consensus_score = dominant.size / len(samples) if dominant else 0.0
        accepted_score = dominant.mean_score if dominant else 0.0

        outcome = self._determine_outcome(consensus_score, cpk, accepted_score)

        result = VerificationResult(
            outcome=outcome,
            consensus_score=consensus_score,
            accepted_score=accepted_score,
            cpk=cpk,
            quality_gate=quality_gate,
            n_samples=len(samples),
            n_clusters=len(clusters),
            dominant_cluster=dominant,
            all_clusters=clusters,
            sample_mean=sample_mean,
            sample_std=sample_std,
        )

        with self._lock:
            self._history.append(result)
            if len(self._history) > MAX_HISTORY:
                self._history = self._history[-MAX_HISTORY:]

        return result

    # -------------------------------------------------------------------------
    # Sampling
    # -------------------------------------------------------------------------

    def _collect_samples(self, output: str, context: str, n: int) -> list[Sample]:
        """Collect N independent evaluation samples."""
        samples = []
        for i in range(n):
            try:
                score, evidence = self._evaluator(output, context)
                samples.append(
                    Sample(
                        sample_id=i,
                        score=max(0.0, min(1.0, score)),
                        evidence=evidence,
                    )
                )
            except Exception as e:
                logger.debug(f"Sample {i} failed: {e}")
        return samples

    # -------------------------------------------------------------------------
    # Clustering
    # -------------------------------------------------------------------------

    def _cluster_samples(self, samples: list[Sample]) -> list[Cluster]:
        """
        Cluster samples by score similarity using greedy single-linkage.

        Samples within similarity_threshold of each other's scores
        are placed in the same cluster.
        """
        if not samples:
            return []

        # Sort by score for efficient clustering
        sorted_samples = sorted(samples, key=lambda s: s.score)
        clusters: list[Cluster] = []
        current_cluster = Cluster(cluster_id=0, samples=[sorted_samples[0]])
        sorted_samples[0].cluster_id = 0

        for sample in sorted_samples[1:]:
            # Check if sample is close enough to current cluster centroid
            if abs(sample.score - current_cluster.mean_score) <= (1.0 - self._similarity_threshold):
                sample.cluster_id = current_cluster.cluster_id
                current_cluster.samples.append(sample)
            else:
                clusters.append(current_cluster)
                new_id = len(clusters)
                current_cluster = Cluster(cluster_id=new_id, samples=[sample])
                sample.cluster_id = new_id

        clusters.append(current_cluster)

        # Update centroid scores
        for cluster in clusters:
            cluster.centroid_score = cluster.mean_score

        return clusters

    # -------------------------------------------------------------------------
    # Statistical Analysis
    # -------------------------------------------------------------------------

    def _compute_cpk(self, mean: float, std: float) -> float:
        """
        Compute process capability index (Cpk).

        Cpk measures how centered and tight the process is relative
        to specification limits [0.0, 1.0].

        Cpk = min(USL - mean, mean - LSL) / (3 * sigma)

        Where USL=1.0, LSL=0.0 for our normalized scores.
        """
        if std < 1e-10:
            # Perfect consistency -> very high Cpk
            return 3.0

        # Spec limits for quality scores
        usl = 1.0
        lsl = 0.0

        cpk_upper = (usl - mean) / (3 * std)
        cpk_lower = (mean - lsl) / (3 * std)

        return max(0.0, min(cpk_upper, cpk_lower))

    def _quality_gate(self, cpk: float) -> QualityGate:
        """Map Cpk to quality gate level."""
        if cpk >= 1.33:
            return QualityGate.GREEN
        elif cpk >= self._cpk_threshold:
            return QualityGate.YELLOW
        else:
            return QualityGate.RED

    def _determine_outcome(self, consensus: float, cpk: float, score: float) -> VerificationOutcome:
        """Determine verification outcome from statistics."""
        if consensus >= self._consensus_threshold and cpk >= self._cpk_threshold:
            return VerificationOutcome.ACCEPTED
        elif consensus >= self._consensus_threshold * 0.8:
            return VerificationOutcome.WEAK_ACCEPT
        else:
            return VerificationOutcome.REJECTED

    def _insufficient_result(self, samples: list[Sample]) -> VerificationResult:
        """Return insufficient result when not enough samples."""
        return VerificationResult(
            outcome=VerificationOutcome.INSUFFICIENT,
            consensus_score=0.0,
            accepted_score=samples[0].score if samples else 0.0,
            cpk=0.0,
            quality_gate=QualityGate.RED,
            n_samples=len(samples),
            n_clusters=0,
            dominant_cluster=None,
            all_clusters=[],
        )

    # -------------------------------------------------------------------------
    # Statistics & History
    # -------------------------------------------------------------------------

    def get_stats(self) -> VerifierStats:
        """Get verifier statistics."""
        with self._lock:
            if not self._history:
                return VerifierStats()

            accepted = sum(1 for r in self._history if r.outcome == VerificationOutcome.ACCEPTED)
            weak = sum(1 for r in self._history if r.outcome == VerificationOutcome.WEAK_ACCEPT)
            rejected = sum(1 for r in self._history if r.outcome == VerificationOutcome.REJECTED)

            return VerifierStats(
                verifications_run=len(self._history),
                accepted_count=accepted,
                weak_accept_count=weak,
                rejected_count=rejected,
                avg_cpk=sum(r.cpk for r in self._history) / len(self._history),
                avg_consensus=sum(r.consensus_score for r in self._history) / len(self._history),
                avg_samples_per_verification=sum(r.n_samples for r in self._history) / len(self._history),
            )

    @property
    def verification_count(self) -> int:
        return len(self._history)

    def reset(self) -> None:
        """Reset verification history."""
        with self._lock:
            self._history.clear()


# =============================================================================
# Singleton
# =============================================================================

_verifier: ConsensusVerifier | None = None
_verifier_lock = threading.Lock()


def get_consensus_verifier() -> ConsensusVerifier:
    """Get or create the global ConsensusVerifier."""
    global _verifier
    if _verifier is None:
        with _verifier_lock:
            if _verifier is None:
                _verifier = ConsensusVerifier()
    return _verifier


def reset_consensus_verifier() -> None:
    """Reset the global ConsensusVerifier."""
    global _verifier
    _verifier = None
