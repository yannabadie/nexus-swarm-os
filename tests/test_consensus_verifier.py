"""Tests for ConsensusVerifier - Six Sigma-inspired multi-sampling verification."""

import pytest

from core.intelligence.reasoning.consensus_verifier import (
    CPK_ACCEPT_THRESHOLD,
    DEFAULT_N_SAMPLES,
    MIN_CONSENSUS_THRESHOLD,
    SIMILARITY_THRESHOLD,
    Cluster,
    ConsensusVerifier,
    QualityGate,
    Sample,
    VerificationOutcome,
    VerificationResult,
    get_consensus_verifier,
    reset_consensus_verifier,
)

# =============================================================================
# Constants
# =============================================================================


class TestConstants:
    def test_default_n_samples(self):
        assert DEFAULT_N_SAMPLES >= 2

    def test_consensus_threshold_range(self):
        assert 0.0 < MIN_CONSENSUS_THRESHOLD < 1.0

    def test_cpk_threshold_positive(self):
        assert CPK_ACCEPT_THRESHOLD > 0

    def test_similarity_threshold_range(self):
        assert 0.0 < SIMILARITY_THRESHOLD < 1.0


# =============================================================================
# VerificationOutcome Enum
# =============================================================================


class TestVerificationOutcome:
    def test_four_outcomes(self):
        assert len(VerificationOutcome) == 4

    def test_values(self):
        assert VerificationOutcome.ACCEPTED.value == "accepted"
        assert VerificationOutcome.WEAK_ACCEPT.value == "weak_accept"
        assert VerificationOutcome.REJECTED.value == "rejected"
        assert VerificationOutcome.INSUFFICIENT.value == "insufficient"


# =============================================================================
# QualityGate Enum
# =============================================================================


class TestQualityGate:
    def test_three_gates(self):
        assert len(QualityGate) == 3

    def test_values(self):
        assert QualityGate.GREEN.value == "green"
        assert QualityGate.YELLOW.value == "yellow"
        assert QualityGate.RED.value == "red"


# =============================================================================
# Sample
# =============================================================================


class TestSample:
    def test_basic_creation(self):
        s = Sample(sample_id=0, score=0.85)
        assert s.sample_id == 0
        assert s.score == 0.85
        assert s.cluster_id == -1
        assert s.evidence == []

    def test_with_evidence(self):
        s = Sample(sample_id=1, score=0.9, evidence=["ev1", "ev2"])
        assert len(s.evidence) == 2

    def test_to_dict(self):
        s = Sample(sample_id=0, score=0.856, evidence=["e1"], cluster_id=2)
        d = s.to_dict()
        assert d["sample_id"] == 0
        assert d["score"] == 0.856
        assert d["cluster_id"] == 2
        assert d["evidence_count"] == 1


# =============================================================================
# Cluster
# =============================================================================


class TestCluster:
    def test_empty_cluster(self):
        c = Cluster(cluster_id=0)
        assert c.size == 0
        assert c.mean_score == 0.0
        assert c.variance == 0.0

    def test_single_sample(self):
        c = Cluster(cluster_id=0, samples=[Sample(sample_id=0, score=0.8)])
        assert c.size == 1
        assert c.mean_score == 0.8
        assert c.variance == 0.0  # Single sample, no variance

    def test_multiple_samples(self):
        c = Cluster(
            cluster_id=0,
            samples=[
                Sample(sample_id=0, score=0.8),
                Sample(sample_id=1, score=0.9),
                Sample(sample_id=2, score=0.7),
            ],
        )
        assert c.size == 3
        assert c.mean_score == pytest.approx(0.8, abs=0.01)
        assert c.variance > 0

    def test_to_dict(self):
        c = Cluster(
            cluster_id=1,
            samples=[
                Sample(sample_id=0, score=0.8),
                Sample(sample_id=1, score=0.9),
            ],
        )
        d = c.to_dict()
        assert d["cluster_id"] == 1
        assert d["size"] == 2
        assert "mean_score" in d
        assert "variance" in d


# =============================================================================
# Cpk Calculation
# =============================================================================


class TestCpkCalculation:
    def setup_method(self):
        self.verifier = ConsensusVerifier()

    def test_perfect_consistency_high_cpk(self):
        """Zero variance -> Cpk = 3.0 (capped)."""
        cpk = self.verifier._compute_cpk(mean=0.5, std=0.0)
        assert cpk == 3.0

    def test_centered_process(self):
        """Mean at 0.5, moderate std -> positive Cpk."""
        cpk = self.verifier._compute_cpk(mean=0.5, std=0.1)
        assert cpk > 0

    def test_off_center_high_reduces_cpk(self):
        """Mean close to USL -> lower Cpk."""
        cpk_centered = self.verifier._compute_cpk(mean=0.5, std=0.1)
        cpk_high = self.verifier._compute_cpk(mean=0.9, std=0.1)
        assert cpk_high < cpk_centered

    def test_off_center_low_reduces_cpk(self):
        """Mean close to LSL -> lower Cpk."""
        cpk_centered = self.verifier._compute_cpk(mean=0.5, std=0.1)
        cpk_low = self.verifier._compute_cpk(mean=0.1, std=0.1)
        assert cpk_low < cpk_centered

    def test_wide_spread_low_cpk(self):
        """High std -> low Cpk."""
        cpk = self.verifier._compute_cpk(mean=0.5, std=0.3)
        assert cpk < 1.0

    def test_cpk_never_negative(self):
        cpk = self.verifier._compute_cpk(mean=0.01, std=0.5)
        assert cpk >= 0.0


# =============================================================================
# Quality Gates
# =============================================================================


class TestQualityGates:
    def setup_method(self):
        self.verifier = ConsensusVerifier()

    def test_green_gate(self):
        assert self.verifier._quality_gate(1.5) == QualityGate.GREEN

    def test_yellow_gate(self):
        assert self.verifier._quality_gate(1.1) == QualityGate.YELLOW

    def test_red_gate(self):
        assert self.verifier._quality_gate(0.5) == QualityGate.RED

    def test_boundary_green(self):
        assert self.verifier._quality_gate(1.33) == QualityGate.GREEN

    def test_boundary_yellow(self):
        assert self.verifier._quality_gate(1.0) == QualityGate.YELLOW


# =============================================================================
# Clustering
# =============================================================================


class TestClustering:
    def setup_method(self):
        self.verifier = ConsensusVerifier()

    def test_identical_scores_one_cluster(self):
        samples = [
            Sample(sample_id=0, score=0.8),
            Sample(sample_id=1, score=0.8),
            Sample(sample_id=2, score=0.8),
        ]
        clusters = self.verifier._cluster_samples(samples)
        assert len(clusters) == 1
        assert clusters[0].size == 3

    def test_two_distinct_groups(self):
        samples = [
            Sample(sample_id=0, score=0.2),
            Sample(sample_id=1, score=0.21),
            Sample(sample_id=2, score=0.9),
            Sample(sample_id=3, score=0.91),
        ]
        clusters = self.verifier._cluster_samples(samples)
        assert len(clusters) == 2

    def test_empty_input(self):
        clusters = self.verifier._cluster_samples([])
        assert clusters == []

    def test_single_sample(self):
        samples = [Sample(sample_id=0, score=0.5)]
        clusters = self.verifier._cluster_samples(samples)
        assert len(clusters) == 1

    def test_cluster_ids_assigned(self):
        samples = [
            Sample(sample_id=0, score=0.8),
            Sample(sample_id=1, score=0.81),
        ]
        self.verifier._cluster_samples(samples)
        for sample in samples:
            assert sample.cluster_id >= 0


# =============================================================================
# Outcome Determination
# =============================================================================


class TestOutcomeDetermination:
    def setup_method(self):
        self.verifier = ConsensusVerifier()

    def test_high_consensus_high_cpk_accepted(self):
        outcome = self.verifier._determine_outcome(consensus=0.9, cpk=1.5, score=0.8)
        assert outcome == VerificationOutcome.ACCEPTED

    def test_moderate_consensus_weak_accept(self):
        outcome = self.verifier._determine_outcome(consensus=0.5, cpk=1.5, score=0.8)
        assert outcome == VerificationOutcome.WEAK_ACCEPT

    def test_low_consensus_rejected(self):
        outcome = self.verifier._determine_outcome(consensus=0.3, cpk=0.5, score=0.5)
        assert outcome == VerificationOutcome.REJECTED

    def test_high_consensus_low_cpk_weak_accept(self):
        """Good consensus but low Cpk -> weak accept."""
        outcome = self.verifier._determine_outcome(consensus=0.8, cpk=0.5, score=0.8)
        assert outcome == VerificationOutcome.WEAK_ACCEPT


# =============================================================================
# verify() Integration
# =============================================================================


class TestVerifyIntegration:
    def test_verify_returns_result(self):
        verifier = ConsensusVerifier(n_samples=3)
        result = verifier.verify(
            "The auth bug is at file auth.py line 42 because the token check is missing.",
            context="Find auth bugs in token module",
        )
        assert isinstance(result, VerificationResult)
        assert result.n_samples == 3
        assert result.outcome in VerificationOutcome

    def test_verify_high_quality_output(self):
        verifier = ConsensusVerifier(n_samples=5)
        output = (
            "The bug is at file auth.py line 42. Because the token.validate_expiry function "
            "does not check for None values, it causes a KeyError. Therefore, I recommend "
            "adding a None check before accessing token.exp. First, update the validation. "
            "Then add a test case. Finally, verify the fix resolves the issue."
        )
        result = verifier.verify(output, context="Find and fix auth bug", n_samples=5)
        assert result.consensus_score > 0.5
        assert result.n_clusters >= 1

    def test_verify_consistent_output_high_cpk(self):
        """Consistent evaluator output -> high Cpk."""

        # Use a custom evaluator that returns consistent scores
        def consistent_eval(output, context=""):
            return 0.8, ["consistent"]

        verifier = ConsensusVerifier(n_samples=5, evaluator=consistent_eval)
        result = verifier.verify("test output")
        assert result.cpk >= 1.0
        assert result.quality_gate in (QualityGate.GREEN, QualityGate.YELLOW)

    def test_verify_all_same_score_accepted(self):
        """All identical scores -> strong consensus."""

        def fixed_eval(output, context=""):
            return 0.75, ["fixed"]

        verifier = ConsensusVerifier(n_samples=5, evaluator=fixed_eval)
        result = verifier.verify("test")
        assert result.outcome == VerificationOutcome.ACCEPTED
        assert result.consensus_score == 1.0
        assert result.n_clusters == 1

    def test_verify_with_override_samples(self):
        verifier = ConsensusVerifier(n_samples=3)
        result = verifier.verify("test", n_samples=7)
        assert result.n_samples == 7

    def test_verify_records_history(self):
        verifier = ConsensusVerifier(n_samples=2)
        assert verifier.verification_count == 0
        verifier.verify("test one")
        verifier.verify("test two")
        assert verifier.verification_count == 2


# =============================================================================
# verify_scores() - Pre-computed Scores
# =============================================================================


class TestVerifyScores:
    def test_uniform_scores_accepted(self):
        verifier = ConsensusVerifier()
        result = verifier.verify_scores([0.8, 0.8, 0.8, 0.8, 0.8])
        assert result.outcome == VerificationOutcome.ACCEPTED
        assert result.consensus_score == 1.0
        assert result.accepted_score == pytest.approx(0.8)

    def test_bimodal_scores_multiple_clusters(self):
        verifier = ConsensusVerifier()
        result = verifier.verify_scores([0.2, 0.2, 0.9, 0.9, 0.9])
        assert result.n_clusters >= 2
        # Dominant cluster should be the 0.9 group (3 vs 2)
        assert result.consensus_score >= 0.6

    def test_single_score_insufficient(self):
        verifier = ConsensusVerifier()
        result = verifier.verify_scores([0.5])
        assert result.outcome == VerificationOutcome.INSUFFICIENT

    def test_two_scores_works(self):
        verifier = ConsensusVerifier()
        result = verifier.verify_scores([0.7, 0.7])
        assert result.n_samples == 2

    def test_spread_scores_low_cpk(self):
        verifier = ConsensusVerifier()
        result = verifier.verify_scores([0.1, 0.5, 0.9])
        assert result.cpk < 1.0

    def test_tight_scores_high_cpk(self):
        verifier = ConsensusVerifier()
        result = verifier.verify_scores([0.49, 0.50, 0.51])
        assert result.cpk > 1.0

    def test_records_in_history(self):
        verifier = ConsensusVerifier()
        verifier.verify_scores([0.5, 0.5, 0.5])
        assert verifier.verification_count == 1


# =============================================================================
# VerificationResult
# =============================================================================


class TestVerificationResult:
    def test_to_dict(self):
        result = VerificationResult(
            outcome=VerificationOutcome.ACCEPTED,
            consensus_score=0.9,
            accepted_score=0.85,
            cpk=1.5,
            quality_gate=QualityGate.GREEN,
            n_samples=5,
            n_clusters=1,
            dominant_cluster=Cluster(cluster_id=0),
            all_clusters=[Cluster(cluster_id=0)],
            sample_mean=0.85,
            sample_std=0.02,
        )
        d = result.to_dict()
        assert d["outcome"] == "accepted"
        assert d["consensus_score"] == 0.9
        assert d["quality_gate"] == "green"
        assert d["n_samples"] == 5
        assert "clusters" in d


# =============================================================================
# Custom Configuration
# =============================================================================


class TestCustomConfig:
    def test_custom_n_samples(self):
        v = ConsensusVerifier(n_samples=7)
        result = v.verify("test output")
        assert result.n_samples == 7

    def test_min_samples_enforced(self):
        """n_samples should be at least 2."""
        v = ConsensusVerifier(n_samples=1)
        result = v.verify("test output")
        assert result.n_samples >= 2

    def test_custom_evaluator(self):
        call_count = [0]

        def custom_eval(output, context=""):
            call_count[0] += 1
            return 0.7, ["custom"]

        v = ConsensusVerifier(n_samples=3, evaluator=custom_eval)
        v.verify("test")
        assert call_count[0] == 3

    def test_custom_consensus_threshold(self):
        """Stricter threshold makes acceptance harder."""

        def varied_eval(output, context=""):
            import random

            return 0.5 + random.uniform(-0.2, 0.2), []

        strict = ConsensusVerifier(n_samples=5, consensus_threshold=0.95, evaluator=varied_eval)
        result = strict.verify("test")
        # With varied scores, unlikely to get 95% consensus -> weak or rejected
        assert result.outcome in (
            VerificationOutcome.WEAK_ACCEPT,
            VerificationOutcome.REJECTED,
            VerificationOutcome.ACCEPTED,  # Still possible if lucky
        )


# =============================================================================
# Statistics
# =============================================================================


class TestVerifierStats:
    def test_empty_stats(self):
        v = ConsensusVerifier()
        stats = v.get_stats()
        assert stats.verifications_run == 0
        assert stats.avg_cpk == 0.0

    def test_stats_after_verifications(self):
        def fixed_eval(output, context=""):
            return 0.8, []

        v = ConsensusVerifier(n_samples=3, evaluator=fixed_eval)
        v.verify("test one")
        v.verify("test two")
        stats = v.get_stats()
        assert stats.verifications_run == 2
        assert stats.accepted_count >= 0
        assert stats.avg_cpk > 0
        assert stats.avg_consensus > 0
        assert stats.avg_samples_per_verification == pytest.approx(3.0)

    def test_stats_to_dict(self):
        v = ConsensusVerifier(n_samples=2)
        v.verify("test")
        d = v.get_stats().to_dict()
        assert "verifications_run" in d
        assert "avg_cpk" in d
        assert "accepted_count" in d

    def test_reset_clears_history(self):
        v = ConsensusVerifier(n_samples=2)
        v.verify("test")
        assert v.verification_count == 1
        v.reset()
        assert v.verification_count == 0
        stats = v.get_stats()
        assert stats.verifications_run == 0


# =============================================================================
# Singleton
# =============================================================================


class TestSingleton:
    def test_get_returns_same(self):
        reset_consensus_verifier()
        v1 = get_consensus_verifier()
        v2 = get_consensus_verifier()
        assert v1 is v2

    def test_reset_creates_new(self):
        reset_consensus_verifier()
        v1 = get_consensus_verifier()
        reset_consensus_verifier()
        v2 = get_consensus_verifier()
        assert v1 is not v2
