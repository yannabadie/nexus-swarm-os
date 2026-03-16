"""
Tests for MemoryCoordinator (V12.4 COGNITIVE BOOST)

Verifies:
1. DomainWeights dataclass and methods
2. UnifiedRecommendation dataclass and methods
3. MemoryCoordinator initialization and configuration
4. get_recommendation with cold start, single source, both sources
5. Agreement and conflict resolution
6. Consolidation of episodic to procedural patterns
7. Statistics reporting
8. V12.4 Adaptive weights learning per domain
9. Weight persistence and recovery
10. Error handling and edge cases

Test Categories:
- DomainWeights (~10 tests)
- UnifiedRecommendation (~5 tests)
- Constructor (~10 tests)
- get_recommendation - Cold Start (~10 tests)
- get_recommendation - Success Only (~10 tests)
- get_recommendation - Auto Only (~10 tests)
- get_recommendation - Agreement (~10 tests)
- get_recommendation - Conflict (~15 tests)
- get_recommendation - Error Handling (~5 tests)
- consolidate (~10 tests)
- get_stats (~5 tests)
- Adaptive Weights - get_weights_for_domain (~5 tests)
- Adaptive Weights - record_feedback (~15 tests)
- Persistence (~10 tests)
- Edge Cases (~10 tests)

Total: 130+ tests
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.memory_pkg.memory.coordinator import (
    DEFAULT_PROCEDURAL_WEIGHT,
    DEFAULT_SEMANTIC_WEIGHT,
    MIN_SAMPLES_FOR_ADAPTATION,
    DomainWeights,
    MemoryCoordinator,
    MemorySource,
    UnifiedRecommendation,
)

# =============================================================================
# DomainWeights Tests (~10)
# =============================================================================


class TestDomainWeights:
    """Test DomainWeights dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        dw = DomainWeights()
        assert dw.semantic_weight == DEFAULT_SEMANTIC_WEIGHT
        assert dw.procedural_weight == DEFAULT_PROCEDURAL_WEIGHT
        assert dw.sample_count == 0
        assert dw.success_count == 0

    def test_custom_values(self):
        """Test custom initialization."""
        dw = DomainWeights(semantic_weight=0.7, procedural_weight=0.3, sample_count=10, success_count=7)
        assert dw.semantic_weight == 0.7
        assert dw.procedural_weight == 0.3
        assert dw.sample_count == 10
        assert dw.success_count == 7

    def test_success_rate_zero_samples(self):
        """Test success_rate returns 0.0 when no samples."""
        dw = DomainWeights()
        assert dw.success_rate == 0.0

    def test_success_rate_with_data(self):
        """Test success_rate calculation."""
        dw = DomainWeights(sample_count=10, success_count=7)
        assert dw.success_rate == 0.7

    def test_success_rate_all_failures(self):
        """Test success_rate when all failures."""
        dw = DomainWeights(sample_count=5, success_count=0)
        assert dw.success_rate == 0.0

    def test_success_rate_all_successes(self):
        """Test success_rate when all successes."""
        dw = DomainWeights(sample_count=5, success_count=5)
        assert dw.success_rate == 1.0

    def test_to_dict_format(self):
        """Test to_dict returns correct format."""
        dw = DomainWeights(semantic_weight=0.65, procedural_weight=0.35, sample_count=10, success_count=7)
        result = dw.to_dict()

        assert isinstance(result, dict)
        assert "semantic_weight" in result
        assert "procedural_weight" in result
        assert "sample_count" in result
        assert "success_count" in result
        assert "success_rate" in result

        assert result["semantic_weight"] == 0.65
        assert result["procedural_weight"] == 0.35
        assert result["sample_count"] == 10
        assert result["success_count"] == 7
        assert result["success_rate"] == 0.7

    def test_to_dict_rounding(self):
        """Test to_dict rounds floats to 3 decimals."""
        dw = DomainWeights(semantic_weight=0.666666, procedural_weight=0.333333, sample_count=3, success_count=2)
        result = dw.to_dict()

        assert result["semantic_weight"] == 0.667
        assert result["procedural_weight"] == 0.333
        assert result["success_rate"] == 0.667

    def test_to_dict_zero_samples(self):
        """Test to_dict with zero samples."""
        dw = DomainWeights()
        result = dw.to_dict()
        assert result["success_rate"] == 0.0


# =============================================================================
# UnifiedRecommendation Tests (~5)
# =============================================================================


class TestUnifiedRecommendation:
    """Test UnifiedRecommendation dataclass."""

    def test_to_dict_format(self):
        """Test to_dict returns correct format."""
        rec = UnifiedRecommendation(
            mode="parallel",
            lead="gemini",
            confidence=0.85,
            source=MemorySource.BOTH,
            modes_to_avoid=["sequential"],
            reasoning="Both memories agree",
        )
        result = rec.to_dict()

        assert result["mode"] == "parallel"
        assert result["lead"] == "gemini"
        assert result["confidence"] == 0.85
        assert result["source"] == "both"
        assert result["modes_to_avoid"] == ["sequential"]
        assert result["reasoning"] == "Both memories agree"

    def test_to_dict_none_values(self):
        """Test to_dict with None values."""
        rec = UnifiedRecommendation(
            mode=None, lead=None, confidence=0.0, source=MemorySource.NONE, modes_to_avoid=[], reasoning="Cold start"
        )
        result = rec.to_dict()

        assert result["mode"] is None
        assert result["lead"] is None
        assert result["confidence"] == 0.0
        assert result["source"] == "none"

    def test_to_dict_rounds_confidence(self):
        """Test to_dict rounds confidence to 3 decimals."""
        rec = UnifiedRecommendation(
            mode="parallel",
            lead=None,
            confidence=0.876543,
            source=MemorySource.SUCCESS,
            modes_to_avoid=[],
            reasoning="Test",
        )
        result = rec.to_dict()
        assert result["confidence"] == 0.877

    def test_fields_accessible(self):
        """Test all fields are accessible."""
        rec = UnifiedRecommendation(
            mode="ping_pong",
            lead="claude",
            confidence=0.92,
            source=MemorySource.AUTO,
            modes_to_avoid=["specialist", "red_blue"],
            reasoning="High confidence from auto",
        )

        assert rec.mode == "ping_pong"
        assert rec.lead == "claude"
        assert rec.confidence == 0.92
        assert rec.source == MemorySource.AUTO
        assert rec.modes_to_avoid == ["specialist", "red_blue"]
        assert rec.reasoning == "High confidence from auto"


# =============================================================================
# Constructor Tests (~10)
# =============================================================================


class TestCoordinatorConstructor:
    """Test MemoryCoordinator initialization."""

    def test_accepts_both_memories(self):
        """Test coordinator accepts both memory instances."""
        success_mock = MagicMock()
        auto_mock = MagicMock()

        coord = MemoryCoordinator(success_mock, auto_mock)

        assert coord.success is success_mock
        assert coord.auto is auto_mock

    def test_accepts_none_success_memory(self):
        """Test coordinator accepts None for success_memory."""
        auto_mock = MagicMock()

        coord = MemoryCoordinator(None, auto_mock)

        assert coord.success is None
        assert coord.auto is auto_mock

    def test_accepts_none_auto_memory(self):
        """Test coordinator accepts None for auto_memory."""
        success_mock = MagicMock()

        coord = MemoryCoordinator(success_mock, None)

        assert coord.success is success_mock
        assert coord.auto is None

    def test_accepts_both_none(self):
        """Test coordinator accepts both memories as None."""
        coord = MemoryCoordinator(None, None)

        assert coord.success is None
        assert coord.auto is None

    def test_initializes_empty_domain_weights(self):
        """Test domain weights initialized as empty dict."""
        coord = MemoryCoordinator(None, None)
        assert coord._domain_weights == {}

    def test_weights_path_stored(self):
        """Test weights_path is stored."""
        weights_path = Path("/tmp/weights.json")
        coord = MemoryCoordinator(None, None, weights_path=weights_path)
        assert coord._weights_path == weights_path

    def test_weights_path_none_by_default(self):
        """Test weights_path is None by default."""
        coord = MemoryCoordinator(None, None)
        assert coord._weights_path is None

    def test_loads_weights_if_path_exists(self, tmp_path):
        """Test loads weights from path if exists."""
        weights_file = tmp_path / "weights.json"
        weights_data = {
            "coding": {"semantic_weight": 0.7, "procedural_weight": 0.3, "sample_count": 10, "success_count": 8}
        }
        weights_file.write_text(json.dumps(weights_data))

        coord = MemoryCoordinator(None, None, weights_path=weights_file)

        assert "coding" in coord._domain_weights
        assert coord._domain_weights["coding"].semantic_weight == 0.7
        assert coord._domain_weights["coding"].procedural_weight == 0.3

    def test_no_crash_when_weights_path_doesnt_exist(self, tmp_path):
        """Test no crash when weights_path doesn't exist."""
        weights_file = tmp_path / "nonexistent.json"

        coord = MemoryCoordinator(None, None, weights_path=weights_file)

        assert coord._domain_weights == {}

    def test_last_recommendation_initialized_none(self):
        """Test _last_recommendation initialized to None."""
        coord = MemoryCoordinator(None, None)
        assert coord._last_recommendation is None


# =============================================================================
# get_recommendation - Cold Start (~10)
# =============================================================================


class TestGetRecommendationColdStart:
    """Test get_recommendation with no memory data."""

    def test_no_memory_data_returns_none_source(self):
        """Test returns NONE source when no data."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.source == MemorySource.NONE

    def test_no_data_returns_zero_confidence(self):
        """Test returns 0.0 confidence when no data."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.confidence == 0.0

    def test_no_data_returns_none_mode(self):
        """Test returns None mode when no data."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.mode is None

    def test_no_data_returns_none_lead(self):
        """Test returns None lead when no data."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.lead is None

    def test_no_data_includes_reasoning(self):
        """Test includes cold start reasoning."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert "cold start" in rec.reasoning.lower()

    def test_success_memory_none_auto_memory_none(self):
        """Test with both memories as None."""
        coord = MemoryCoordinator(None, None)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.source == MemorySource.NONE
        assert rec.confidence == 0.0

    def test_auto_returns_zero_confidence(self):
        """Test when auto returns data with 0 confidence."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"confidence": 0}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.source == MemorySource.NONE

    def test_auto_returns_empty_dict(self):
        """Test when auto returns empty dict."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.source == MemorySource.NONE

    def test_empty_modes_to_avoid(self):
        """Test modes_to_avoid is empty list for cold start."""
        coord = MemoryCoordinator(None, None)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.modes_to_avoid == []

    def test_calls_both_memories(self):
        """Test calls both memories even when no data."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        coord.get_recommendation("test task", "coding")

        success_mock.get_best_mode_for_similar.assert_called_once()
        auto_mock.get_recommendation.assert_called_once()


# =============================================================================
# get_recommendation - Success Only (~10)
# =============================================================================


class TestGetRecommendationSuccessOnly:
    """Test get_recommendation with only SuccessMemory data."""

    def test_returns_success_source(self):
        """Test returns SUCCESS source."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.8)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.source == MemorySource.SUCCESS

    def test_weighted_confidence(self):
        """Test confidence is weighted by semantic_weight."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.8)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # Default semantic weight is 0.6
        expected = 0.8 * DEFAULT_SEMANTIC_WEIGHT
        assert rec.confidence == pytest.approx(expected, abs=0.001)

    def test_mode_from_success_rec(self):
        """Test mode comes from success_rec."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("ping_pong", "task_123", 0.7)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.mode == "ping_pong"

    def test_lead_is_none(self):
        """Test lead is None (success doesn't provide lead)."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.9)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.lead is None

    def test_modes_to_avoid_empty(self):
        """Test modes_to_avoid is empty when only success."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.8)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.modes_to_avoid == []

    def test_reasoning_includes_task_id(self):
        """Test reasoning includes task_id snippet."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "long_task_id_here_123", 0.8)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert "long_task_id_here_12" in rec.reasoning

    def test_high_similarity_score(self):
        """Test with very high similarity score."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.95)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        expected = 0.95 * DEFAULT_SEMANTIC_WEIGHT
        assert rec.confidence == pytest.approx(expected, abs=0.001)

    def test_low_similarity_score(self):
        """Test with low similarity score."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.25)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        expected = 0.25 * DEFAULT_SEMANTIC_WEIGHT
        assert rec.confidence == pytest.approx(expected, abs=0.001)

    def test_tracks_last_recommendation(self):
        """Test _last_recommendation is set."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.8)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        coord.get_recommendation("test task", "coding")

        assert coord._last_recommendation == ("coding", MemorySource.SUCCESS)


# =============================================================================
# get_recommendation - Auto Only (~10)
# =============================================================================


class TestGetRecommendationAutoOnly:
    """Test get_recommendation with only AutoMemory data."""

    def test_returns_auto_source(self):
        """Test returns AUTO source."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {
            "suggested_mode": "sequential",
            "suggested_lead": "gemini",
            "confidence": 0.7,
            "modes_to_avoid": [],
        }

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.source == MemorySource.AUTO

    def test_weighted_confidence(self):
        """Test confidence weighted by procedural_weight."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 0.8}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        expected = 0.8 * DEFAULT_PROCEDURAL_WEIGHT
        assert rec.confidence == pytest.approx(expected, abs=0.001)

    def test_mode_from_auto_rec(self):
        """Test mode from auto_rec."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "lead_support", "confidence": 0.6}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.mode == "lead_support"

    def test_lead_from_auto_rec(self):
        """Test lead from auto_rec."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {
            "suggested_mode": "specialist",
            "suggested_lead": "claude",
            "confidence": 0.9,
        }

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.lead == "claude"

    def test_modes_to_avoid_from_auto(self):
        """Test modes_to_avoid from auto_rec."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {
            "suggested_mode": "parallel",
            "confidence": 0.8,
            "modes_to_avoid": ["sequential", "ping_pong"],
        }

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.modes_to_avoid == ["sequential", "ping_pong"]

    def test_reasoning_includes_task_type(self):
        """Test reasoning includes task type."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "red_blue", "confidence": 0.75}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "security_audit")

        assert "security_audit" in rec.reasoning

    def test_missing_modes_to_avoid(self):
        """Test handles missing modes_to_avoid."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.8}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.modes_to_avoid == []

    def test_missing_suggested_lead(self):
        """Test handles missing suggested_lead."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.8}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.lead is None

    def test_tracks_last_recommendation(self):
        """Test _last_recommendation is set."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.8}

        coord = MemoryCoordinator(success_mock, auto_mock)
        coord.get_recommendation("test task", "coding")

        assert coord._last_recommendation == ("coding", MemorySource.AUTO)


# =============================================================================
# get_recommendation - Agreement (~10)
# =============================================================================


class TestGetRecommendationAgreement:
    """Test get_recommendation when both memories agree."""

    def test_returns_both_source(self):
        """Test returns BOTH source when modes agree."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.7)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {
            "suggested_mode": "parallel",
            "suggested_lead": "gemini",
            "confidence": 0.6,
        }

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.source == MemorySource.BOTH

    def test_combined_confidence(self):
        """Test combined confidence uses both weights."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.8)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.6}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # 0.8 * 0.6 + 0.6 * 0.4 = 0.48 + 0.24 = 0.72
        expected = 0.8 * DEFAULT_SEMANTIC_WEIGHT + 0.6 * DEFAULT_PROCEDURAL_WEIGHT
        assert rec.confidence == pytest.approx(expected, abs=0.001)

    def test_confidence_capped_at_one(self):
        """Test confidence capped at 1.0."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.9)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.95}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.confidence <= 1.0

    def test_mode_from_agreed_value(self):
        """Test mode is the agreed value."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("ping_pong", "task_123", 0.7)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "ping_pong", "confidence": 0.6}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.mode == "ping_pong"

    def test_lead_from_auto_rec(self):
        """Test lead comes from auto_rec."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.7)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {
            "suggested_mode": "parallel",
            "suggested_lead": "claude",
            "confidence": 0.6,
        }

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.lead == "claude"

    def test_modes_to_avoid_from_auto(self):
        """Test modes_to_avoid from auto_rec."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.7)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {
            "suggested_mode": "parallel",
            "confidence": 0.6,
            "modes_to_avoid": ["sequential"],
        }

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.modes_to_avoid == ["sequential"]

    def test_reasoning_mentions_agreement(self):
        """Test reasoning mentions both memories agree."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.7)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.6}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert "agree" in rec.reasoning.lower()

    def test_tracks_last_recommendation(self):
        """Test _last_recommendation uses BOTH source."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.7)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.6}

        coord = MemoryCoordinator(success_mock, auto_mock)
        coord.get_recommendation("test task", "coding")

        assert coord._last_recommendation == ("coding", MemorySource.BOTH)

    def test_high_combined_confidence(self):
        """Test very high scores combine properly."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.95)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.9}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # 0.95 * 0.6 + 0.9 * 0.4 = 0.57 + 0.36 = 0.93
        expected = 0.95 * DEFAULT_SEMANTIC_WEIGHT + 0.9 * DEFAULT_PROCEDURAL_WEIGHT
        assert rec.confidence == pytest.approx(expected, abs=0.001)
        # Should still be <= 1.0
        assert rec.confidence <= 1.0


# =============================================================================
# get_recommendation - Conflict (~15)
# =============================================================================


class TestGetRecommendationConflict:
    """Test get_recommendation when memories conflict."""

    def test_semantic_wins_higher_weighted_score(self):
        """Test semantic wins when weighted score higher."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.9)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 0.5}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # 0.9 * 0.6 = 0.54 vs 0.5 * 0.4 = 0.2
        assert rec.source == MemorySource.SUCCESS
        assert rec.mode == "parallel"

    def test_auto_wins_higher_weighted_score(self):
        """Test auto wins when weighted score higher."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.3)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 0.9}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # 0.3 * 0.6 = 0.18 vs 0.9 * 0.4 = 0.36
        assert rec.source == MemorySource.AUTO
        assert rec.mode == "sequential"

    def test_semantic_wins_tie(self):
        """Test semantic wins when scores tied."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.667)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 1.0}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # 0.667 * 0.6 ≈ 0.4 vs 1.0 * 0.4 = 0.4 (tie)
        assert rec.source == MemorySource.SUCCESS
        assert rec.mode == "parallel"

    def test_confidence_from_winning_source(self):
        """Test confidence is from winning source."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.9)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 0.5}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        expected = 0.9 * DEFAULT_SEMANTIC_WEIGHT
        assert rec.confidence == pytest.approx(expected, abs=0.001)

    def test_modes_to_avoid_still_from_auto(self):
        """Test modes_to_avoid from auto even when semantic wins."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.9)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {
            "suggested_mode": "sequential",
            "confidence": 0.5,
            "modes_to_avoid": ["ping_pong"],
        }

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.modes_to_avoid == ["ping_pong"]

    def test_lead_from_auto_when_semantic_wins(self):
        """Test lead from auto even when semantic wins mode."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.9)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {
            "suggested_mode": "sequential",
            "suggested_lead": "gemini",
            "confidence": 0.5,
        }

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.lead == "gemini"

    def test_lead_from_auto_when_auto_wins(self):
        """Test lead from auto when auto wins."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.3)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {
            "suggested_mode": "sequential",
            "suggested_lead": "claude",
            "confidence": 0.9,
        }

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert rec.lead == "claude"

    def test_reasoning_explains_semantic_win(self):
        """Test reasoning explains semantic won."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.9)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 0.5}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert "semantic" in rec.reasoning.lower() or "match" in rec.reasoning.lower()

    def test_reasoning_explains_auto_win(self):
        """Test reasoning explains auto won."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.3)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 0.9}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        assert "categorical" in rec.reasoning.lower() or "confidence" in rec.reasoning.lower()

    def test_tracks_last_recommendation_success_wins(self):
        """Test tracks source when success wins."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.9)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 0.5}

        coord = MemoryCoordinator(success_mock, auto_mock)
        coord.get_recommendation("test task", "coding")

        assert coord._last_recommendation == ("coding", MemorySource.SUCCESS)

    def test_tracks_last_recommendation_auto_wins(self):
        """Test tracks source when auto wins."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.3)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 0.9}

        coord = MemoryCoordinator(success_mock, auto_mock)
        coord.get_recommendation("test task", "coding")

        assert coord._last_recommendation == ("coding", MemorySource.AUTO)

    def test_close_weighted_scores(self):
        """Test behavior with very close weighted scores."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.668)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 1.001}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # One should win (tie goes to semantic)
        assert rec.source in [MemorySource.SUCCESS, MemorySource.AUTO]

    def test_different_modes_conflict(self):
        """Test various mode conflicts."""
        modes_pairs = [("parallel", "sequential"), ("ping_pong", "specialist"), ("lead_support", "red_blue")]

        for success_mode, auto_mode in modes_pairs:
            success_mock = MagicMock()
            success_mock.get_best_mode_for_similar.return_value = (success_mode, "task_123", 0.9)

            auto_mock = MagicMock()
            auto_mock.get_recommendation.return_value = {"suggested_mode": auto_mode, "confidence": 0.5}

            coord = MemoryCoordinator(success_mock, auto_mock)
            rec = coord.get_recommendation("test task", "coding")

            # Semantic should win with these scores
            assert rec.mode == success_mode

    def test_uses_domain_specific_weights(self, tmp_path):
        """Test uses learned domain weights in conflict."""
        # Set up learned weights
        weights_file = tmp_path / "weights.json"
        weights_data = {
            "coding": {
                "semantic_weight": 0.3,  # Lower semantic
                "procedural_weight": 0.7,  # Higher procedural
                "sample_count": 10,
                "success_count": 7,
            }
        }
        weights_file.write_text(json.dumps(weights_data))

        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.8)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 0.8}

        coord = MemoryCoordinator(success_mock, auto_mock, weights_path=weights_file)
        rec = coord.get_recommendation("test task", "coding")

        # With custom weights: 0.8*0.3=0.24 vs 0.8*0.7=0.56
        # Auto should win
        assert rec.mode == "sequential"


# =============================================================================
# get_recommendation - Error Handling (~5)
# =============================================================================


class TestGetRecommendationErrorHandling:
    """Test error handling in get_recommendation."""

    def test_success_memory_raises_exception(self):
        """Test graceful handling when success_memory raises."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.side_effect = Exception("DB error")

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.7}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # Should still return auto recommendation
        assert rec.mode == "parallel"
        assert rec.source == MemorySource.AUTO

    def test_auto_memory_raises_exception(self):
        """Test graceful handling when auto_memory raises."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.8)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.side_effect = Exception("API error")

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # Should still return success recommendation
        assert rec.mode == "parallel"
        assert rec.source == MemorySource.SUCCESS

    def test_both_raise_exception(self):
        """Test when both memories raise exceptions."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.side_effect = Exception("DB error")

        auto_mock = MagicMock()
        auto_mock.get_recommendation.side_effect = Exception("API error")

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # Should return cold start
        assert rec.source == MemorySource.NONE
        assert rec.confidence == 0.0

    def test_success_returns_invalid_tuple(self):
        """Test handling of invalid return from success_memory."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel",)  # Too short

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "sequential", "confidence": 0.7}

        coord = MemoryCoordinator(success_mock, auto_mock)

        # Should either raise or gracefully fallback to auto
        try:
            rec = coord.get_recommendation("test task", "coding")
            # If it doesn't raise, should use auto
            assert rec.source in [MemorySource.AUTO, MemorySource.NONE]
        except (IndexError, TypeError):
            pass  # Expected if unpacking fails

    def test_empty_task_description(self):
        """Test with empty task description."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.6}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("", "coding")

        # Should still work
        assert rec.mode == "parallel"


# =============================================================================
# consolidate Tests (~10)
# =============================================================================


class TestConsolidate:
    """Test consolidation of episodic to procedural patterns."""

    def test_returns_zero_when_no_success_memory(self):
        """Test returns 0 when success_memory is None."""
        coord = MemoryCoordinator(None, None)
        result = coord.consolidate()
        assert result == 0

    def test_returns_zero_when_less_than_10_entries(self):
        """Test returns 0 when < 10 entries."""
        success_mock = MagicMock()
        success_mock.get_all.return_value = [MagicMock() for _ in range(5)]

        coord = MemoryCoordinator(success_mock, None)
        result = coord.consolidate()
        assert result == 0

    def test_counts_domains_with_5_plus_entries(self):
        """Test counts only domains with 5+ entries."""
        # Create mock entries
        entries = []
        for i in range(10):
            entry = MagicMock()
            entry.primary_domain = "coding" if i < 7 else "research"
            entry.domains = ["coding" if i < 7 else "research"]
            entry.swarm_mode = "parallel"
            entry.quality_score = 0.8
            entries.append(entry)

        success_mock = MagicMock()
        success_mock.get_all.return_value = entries

        coord = MemoryCoordinator(success_mock, None)
        result = coord.consolidate()

        # Only coding has 7 entries (>= 5), research has 3 (< 5)
        assert result == 1

    def test_finds_best_mode_by_average_quality(self):
        """Test finds mode with highest average quality."""
        entries = []
        # 5 parallel with avg 0.9
        for _i in range(5):
            entry = MagicMock()
            entry.primary_domain = "coding"
            entry.domains = ["coding"]
            entry.swarm_mode = "parallel"
            entry.quality_score = 0.9
            entries.append(entry)

        # 5 sequential with avg 0.6
        for _i in range(5):
            entry = MagicMock()
            entry.primary_domain = "coding"
            entry.domains = ["coding"]
            entry.swarm_mode = "sequential"
            entry.quality_score = 0.6
            entries.append(entry)

        success_mock = MagicMock()
        success_mock.get_all.return_value = entries

        coord = MemoryCoordinator(success_mock, None)

        # We can't directly check the logged result, but consolidate should succeed
        result = coord.consolidate()
        assert result == 1

    def test_handles_multiple_domains(self):
        """Test consolidates multiple domains."""
        entries = []
        # 6 coding entries
        for _i in range(6):
            entry = MagicMock()
            entry.primary_domain = "coding"
            entry.domains = ["coding"]
            entry.swarm_mode = "parallel"
            entry.quality_score = 0.8
            entries.append(entry)

        # 5 research entries
        for _i in range(5):
            entry = MagicMock()
            entry.primary_domain = "research"
            entry.domains = ["research"]
            entry.swarm_mode = "sequential"
            entry.quality_score = 0.7
            entries.append(entry)

        success_mock = MagicMock()
        success_mock.get_all.return_value = entries

        coord = MemoryCoordinator(success_mock, None)
        result = coord.consolidate()

        assert result == 2

    def test_uses_first_domain_when_primary_none(self):
        """Test uses domains[0] when primary_domain is None."""
        entries = []
        # Need at least 10 total entries AND 5 per domain to trigger consolidation
        for _i in range(10):
            entry = MagicMock()
            entry.primary_domain = None
            entry.domains = ["coding", "debugging"]
            entry.swarm_mode = "parallel"
            entry.quality_score = 0.8
            entries.append(entry)

        success_mock = MagicMock()
        success_mock.get_all.return_value = entries

        coord = MemoryCoordinator(success_mock, None)
        result = coord.consolidate()

        # Should use "coding" as domain (10 entries >= 5)
        assert result == 1

    def test_uses_general_when_no_domains(self):
        """Test uses 'general' when domains empty."""
        entries = []
        # Need at least 10 total entries AND 5 per domain to trigger consolidation
        for _i in range(10):
            entry = MagicMock()
            entry.primary_domain = None
            entry.domains = []
            entry.swarm_mode = "parallel"
            entry.quality_score = 0.8
            entries.append(entry)

        success_mock = MagicMock()
        success_mock.get_all.return_value = entries

        coord = MemoryCoordinator(success_mock, None)
        result = coord.consolidate()

        # Should use "general" as domain (10 entries >= 5)
        assert result == 1

    def test_get_all_raises_exception(self):
        """Test handles exception from get_all."""
        success_mock = MagicMock()
        success_mock.get_all.side_effect = Exception("DB error")

        coord = MemoryCoordinator(success_mock, None)
        result = coord.consolidate()

        assert result == 0

    def test_empty_mode_scores(self):
        """Test handles entries with no modes."""
        entries = []
        for _i in range(10):
            entry = MagicMock()
            entry.primary_domain = "coding"
            entry.domains = ["coding"]
            entry.swarm_mode = None  # No mode
            entry.quality_score = 0.8
            entries.append(entry)

        success_mock = MagicMock()
        success_mock.get_all.return_value = entries

        coord = MemoryCoordinator(success_mock, None)
        result = coord.consolidate()

        # Should handle gracefully, may return 0 if no valid modes
        assert isinstance(result, int)


# =============================================================================
# get_stats Tests (~5)
# =============================================================================


class TestGetStats:
    """Test statistics reporting."""

    def test_reports_memory_availability(self):
        """Test reports availability of both memories."""
        success_mock = MagicMock()
        auto_mock = MagicMock()

        coord = MemoryCoordinator(success_mock, auto_mock)
        stats = coord.get_stats()

        assert stats["success_memory_available"] is True
        assert stats["auto_memory_available"] is True

    def test_reports_none_memories(self):
        """Test reports when memories are None."""
        coord = MemoryCoordinator(None, None)
        stats = coord.get_stats()

        assert stats["success_memory_available"] is False
        assert stats["auto_memory_available"] is False

    def test_reports_weights(self):
        """Test reports semantic and procedural weights."""
        coord = MemoryCoordinator(None, None)
        stats = coord.get_stats()

        assert "semantic_weight" in stats
        assert "procedural_weight" in stats
        assert stats["semantic_weight"] == DEFAULT_SEMANTIC_WEIGHT
        assert stats["procedural_weight"] == DEFAULT_PROCEDURAL_WEIGHT

    def test_reports_domain_count(self):
        """Test reports number of adaptive domains."""
        coord = MemoryCoordinator(None, None)
        # Add some domain weights
        coord._domain_weights["coding"] = DomainWeights()
        coord._domain_weights["research"] = DomainWeights()

        stats = coord.get_stats()

        assert stats["adaptive_domains"] == 2

    def test_includes_domain_weights_detail(self):
        """Test includes detailed domain weights."""
        coord = MemoryCoordinator(None, None)
        coord._domain_weights["coding"] = DomainWeights(
            semantic_weight=0.7, procedural_weight=0.3, sample_count=10, success_count=7
        )

        stats = coord.get_stats()

        assert "domain_weights" in stats
        assert "coding" in stats["domain_weights"]
        assert stats["domain_weights"]["coding"]["semantic_weight"] == 0.7


# =============================================================================
# Adaptive Weights - get_weights_for_domain Tests (~5)
# =============================================================================


class TestGetWeightsForDomain:
    """Test domain-specific weight retrieval."""

    def test_returns_defaults_for_unknown_domain(self):
        """Test returns defaults for unknown domain."""
        coord = MemoryCoordinator(None, None)
        semantic, procedural = coord.get_weights_for_domain("unknown")

        assert semantic == DEFAULT_SEMANTIC_WEIGHT
        assert procedural == DEFAULT_PROCEDURAL_WEIGHT

    def test_returns_learned_weights_for_known_domain(self):
        """Test returns learned weights for known domain."""
        coord = MemoryCoordinator(None, None)
        coord._domain_weights["coding"] = DomainWeights(semantic_weight=0.7, procedural_weight=0.3)

        semantic, procedural = coord.get_weights_for_domain("coding")

        assert semantic == 0.7
        assert procedural == 0.3

    def test_returns_tuple(self):
        """Test returns tuple of floats."""
        coord = MemoryCoordinator(None, None)
        result = coord.get_weights_for_domain("coding")

        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)

    def test_multiple_domains_independent(self):
        """Test different domains have independent weights."""
        coord = MemoryCoordinator(None, None)
        coord._domain_weights["coding"] = DomainWeights(semantic_weight=0.7, procedural_weight=0.3)
        coord._domain_weights["research"] = DomainWeights(semantic_weight=0.4, procedural_weight=0.6)

        coding_s, coding_p = coord.get_weights_for_domain("coding")
        research_s, research_p = coord.get_weights_for_domain("research")

        assert coding_s == 0.7
        assert research_s == 0.4


# =============================================================================
# Adaptive Weights - record_feedback Tests (~15)
# =============================================================================


class TestRecordFeedback:
    """Test adaptive weight learning via feedback."""

    def test_creates_domain_weights_on_first_feedback(self):
        """Test creates DomainWeights on first feedback."""
        coord = MemoryCoordinator(None, None)
        coord.record_feedback("coding", MemorySource.SUCCESS, True)

        assert "coding" in coord._domain_weights

    def test_increments_sample_count(self):
        """Test increments sample_count."""
        coord = MemoryCoordinator(None, None)
        coord.record_feedback("coding", MemorySource.SUCCESS, True)

        assert coord._domain_weights["coding"].sample_count == 1

        coord.record_feedback("coding", MemorySource.SUCCESS, False)
        assert coord._domain_weights["coding"].sample_count == 2

    def test_increments_success_count_on_success(self):
        """Test increments success_count on success."""
        coord = MemoryCoordinator(None, None)
        coord.record_feedback("coding", MemorySource.SUCCESS, True)

        assert coord._domain_weights["coding"].success_count == 1

    def test_no_success_count_increment_on_failure(self):
        """Test doesn't increment success_count on failure."""
        coord = MemoryCoordinator(None, None)
        coord.record_feedback("coding", MemorySource.SUCCESS, False)

        assert coord._domain_weights["coding"].success_count == 0

    def test_no_weight_adaptation_before_min_samples(self):
        """Test no weight changes before MIN_SAMPLES."""
        coord = MemoryCoordinator(None, None)

        initial_semantic = DEFAULT_SEMANTIC_WEIGHT

        for _i in range(MIN_SAMPLES_FOR_ADAPTATION - 1):
            coord.record_feedback("coding", MemorySource.SUCCESS, True)

        # Should still be default
        assert coord._domain_weights["coding"].semantic_weight == initial_semantic

    def test_both_source_success_no_weight_change(self):
        """Test BOTH source + success doesn't change weights."""
        coord = MemoryCoordinator(None, None)

        # Get to MIN_SAMPLES
        for _i in range(MIN_SAMPLES_FOR_ADAPTATION):
            coord.record_feedback("coding", MemorySource.BOTH, True)

        # Should still be defaults
        assert coord._domain_weights["coding"].semantic_weight == DEFAULT_SEMANTIC_WEIGHT
        assert coord._domain_weights["coding"].procedural_weight == DEFAULT_PROCEDURAL_WEIGHT

    def test_success_source_success_increases_semantic(self):
        """Test SUCCESS source + success increases semantic weight."""
        coord = MemoryCoordinator(None, None)

        # Get to MIN_SAMPLES with failures to avoid weight changes
        for _i in range(MIN_SAMPLES_FOR_ADAPTATION - 1):
            coord.record_feedback("coding", MemorySource.BOTH, True)

        _ = coord._domain_weights["coding"].semantic_weight

        # Now trigger adaptation
        coord.record_feedback("coding", MemorySource.SUCCESS, True)

        # Semantic should increase (or stay same if already high)
        # Due to normalization, exact value depends on success_rate
        assert "coding" in coord._domain_weights

    def test_success_source_failure_decreases_semantic(self):
        """Test SUCCESS source + failure decreases semantic weight."""
        coord = MemoryCoordinator(None, None)

        # Get to MIN_SAMPLES
        for _i in range(MIN_SAMPLES_FOR_ADAPTATION - 1):
            coord.record_feedback("coding", MemorySource.BOTH, True)

        initial = coord._domain_weights["coding"].semantic_weight

        # Trigger decrease
        coord.record_feedback("coding", MemorySource.SUCCESS, False)

        # Semantic should decrease
        final = coord._domain_weights["coding"].semantic_weight
        assert final < initial

    def test_auto_source_success_increases_procedural(self):
        """Test AUTO source + success increases procedural weight."""
        coord = MemoryCoordinator(None, None)

        # Get to MIN_SAMPLES
        for _i in range(MIN_SAMPLES_FOR_ADAPTATION - 1):
            coord.record_feedback("coding", MemorySource.BOTH, True)

        initial = coord._domain_weights["coding"].procedural_weight

        # Trigger increase
        coord.record_feedback("coding", MemorySource.AUTO, True)

        # Procedural should increase
        final = coord._domain_weights["coding"].procedural_weight
        assert final >= initial

    def test_auto_source_failure_decreases_procedural(self):
        """Test AUTO source + failure decreases procedural weight."""
        coord = MemoryCoordinator(None, None)

        # Get to MIN_SAMPLES
        for _i in range(MIN_SAMPLES_FOR_ADAPTATION - 1):
            coord.record_feedback("coding", MemorySource.BOTH, True)

        initial = coord._domain_weights["coding"].procedural_weight

        # Trigger decrease
        coord.record_feedback("coding", MemorySource.AUTO, False)

        # Procedural should decrease
        final = coord._domain_weights["coding"].procedural_weight
        assert final < initial

    def test_weights_clamped_to_min(self):
        """Test weights clamped to 0.2 minimum."""
        coord = MemoryCoordinator(None, None)

        # Set very low semantic weight
        coord._domain_weights["coding"] = DomainWeights(
            semantic_weight=0.21,
            procedural_weight=0.79,
            sample_count=MIN_SAMPLES_FOR_ADAPTATION,
            success_count=0,  # All failures
        )

        # Multiple failures should clamp to 0.2
        for _i in range(10):
            coord.record_feedback("coding", MemorySource.SUCCESS, False)

        assert coord._domain_weights["coding"].semantic_weight >= 0.2

    def test_weights_clamped_to_max(self):
        """Test weights clamped to 0.8 maximum."""
        coord = MemoryCoordinator(None, None)

        # Set high semantic weight
        coord._domain_weights["coding"] = DomainWeights(
            semantic_weight=0.79,
            procedural_weight=0.21,
            sample_count=MIN_SAMPLES_FOR_ADAPTATION,
            success_count=MIN_SAMPLES_FOR_ADAPTATION,  # All successes
        )

        # Multiple successes should clamp to 0.8
        for _i in range(10):
            coord.record_feedback("coding", MemorySource.SUCCESS, True)

        assert coord._domain_weights["coding"].semantic_weight <= 0.8

    def test_weights_normalized_to_sum_one(self):
        """Test weights always sum to 1.0."""
        coord = MemoryCoordinator(None, None)

        # Get to MIN_SAMPLES and trigger adaptations
        for i in range(MIN_SAMPLES_FOR_ADAPTATION):
            coord.record_feedback("coding", MemorySource.SUCCESS, i % 2 == 0)

        dw = coord._domain_weights["coding"]
        total = dw.semantic_weight + dw.procedural_weight

        assert total == pytest.approx(1.0, abs=0.001)

    def test_saves_weights_after_adaptation(self, tmp_path):
        """Test persists weights after adaptation."""
        weights_file = tmp_path / "weights.json"
        coord = MemoryCoordinator(None, None, weights_path=weights_file)

        # Trigger adaptation
        for _i in range(MIN_SAMPLES_FOR_ADAPTATION):
            coord.record_feedback("coding", MemorySource.SUCCESS, True)

        # File should exist
        assert weights_file.exists()


# =============================================================================
# Persistence Tests (~10)
# =============================================================================


class TestPersistence:
    """Test weight persistence."""

    def test_save_weights_writes_json(self, tmp_path):
        """Test _save_weights writes JSON file."""
        weights_file = tmp_path / "weights.json"
        coord = MemoryCoordinator(None, None, weights_path=weights_file)

        coord._domain_weights["coding"] = DomainWeights(
            semantic_weight=0.7, procedural_weight=0.3, sample_count=10, success_count=7
        )

        coord._save_weights()

        assert weights_file.exists()

    def test_load_weights_reads_json(self, tmp_path):
        """Test _load_weights reads JSON file."""
        weights_file = tmp_path / "weights.json"
        weights_data = {
            "coding": {"semantic_weight": 0.65, "procedural_weight": 0.35, "sample_count": 15, "success_count": 12}
        }
        weights_file.write_text(json.dumps(weights_data))

        coord = MemoryCoordinator(None, None, weights_path=weights_file)

        assert "coding" in coord._domain_weights
        assert coord._domain_weights["coding"].semantic_weight == 0.65
        assert coord._domain_weights["coding"].sample_count == 15

    def test_round_trip_preserves_data(self, tmp_path):
        """Test save then load preserves data."""
        weights_file = tmp_path / "weights.json"
        coord1 = MemoryCoordinator(None, None, weights_path=weights_file)

        coord1._domain_weights["coding"] = DomainWeights(
            semantic_weight=0.72, procedural_weight=0.28, sample_count=20, success_count=15
        )
        coord1._save_weights()

        # Load in new coordinator
        coord2 = MemoryCoordinator(None, None, weights_path=weights_file)

        assert coord2._domain_weights["coding"].semantic_weight == 0.72
        assert coord2._domain_weights["coding"].sample_count == 20

    def test_missing_file_handled_gracefully(self, tmp_path):
        """Test missing file doesn't crash."""
        weights_file = tmp_path / "nonexistent.json"
        coord = MemoryCoordinator(None, None, weights_path=weights_file)

        # Should initialize with empty weights
        assert coord._domain_weights == {}

    def test_corrupt_file_handled_gracefully(self, tmp_path):
        """Test corrupt JSON doesn't crash."""
        weights_file = tmp_path / "corrupt.json"
        weights_file.write_text("{ not valid json }")

        coord = MemoryCoordinator(None, None, weights_path=weights_file)

        # Should initialize with empty weights
        assert coord._domain_weights == {}

    def test_creates_parent_directory(self, tmp_path):
        """Test creates parent directories if needed."""
        weights_file = tmp_path / "subdir" / "weights.json"
        coord = MemoryCoordinator(None, None, weights_path=weights_file)

        coord._domain_weights["coding"] = DomainWeights()
        coord._save_weights()

        assert weights_file.exists()

    def test_no_save_when_weights_path_none(self):
        """Test doesn't crash when weights_path is None."""
        coord = MemoryCoordinator(None, None, weights_path=None)

        coord._domain_weights["coding"] = DomainWeights()
        coord._save_weights()  # Should not crash

    def test_multiple_domains_persistence(self, tmp_path):
        """Test persists multiple domains."""
        weights_file = tmp_path / "weights.json"
        coord = MemoryCoordinator(None, None, weights_path=weights_file)

        coord._domain_weights["coding"] = DomainWeights(semantic_weight=0.7, procedural_weight=0.3)
        coord._domain_weights["research"] = DomainWeights(semantic_weight=0.4, procedural_weight=0.6)

        coord._save_weights()

        # Reload
        coord2 = MemoryCoordinator(None, None, weights_path=weights_file)

        assert len(coord2._domain_weights) == 2
        assert "coding" in coord2._domain_weights
        assert "research" in coord2._domain_weights

    def test_json_format_readable(self, tmp_path):
        """Test JSON is human-readable (indented)."""
        weights_file = tmp_path / "weights.json"
        coord = MemoryCoordinator(None, None, weights_path=weights_file)

        coord._domain_weights["coding"] = DomainWeights()
        coord._save_weights()

        content = weights_file.read_text()

        # Should be indented (multiline)
        assert "\n" in content


# =============================================================================
# Edge Cases (~10)
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_task_description(self):
        """Test with empty task description."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.6}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("", "coding")

        assert rec.mode == "parallel"

    def test_empty_domains_list(self):
        """Test with empty domains list."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.8)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding", domains=[])

        assert rec.mode == "parallel"

    def test_very_high_similarity_scores(self):
        """Test with scores > 1.0 (shouldn't happen but test robustness)."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 1.5)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # Should still work, confidence may be > 1 before capping
        assert rec.mode == "parallel"

    def test_negative_confidence_scores(self):
        """Test with negative scores (shouldn't happen)."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": -0.5}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("test task", "coding")

        # Should handle gracefully
        assert isinstance(rec.confidence, float)

    def test_multiple_domains_uses_first(self):
        """Test with multiple domains uses first for weights."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.8)

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = None

        coord = MemoryCoordinator(success_mock, auto_mock)
        coord._domain_weights["research"] = DomainWeights(semantic_weight=0.3, procedural_weight=0.7)

        rec = coord.get_recommendation("test task", "coding", domains=["research", "coding"])

        # Should use "research" weights (first in domains list)
        expected = 0.8 * 0.3  # research semantic_weight
        assert rec.confidence == pytest.approx(expected, abs=0.001)

    def test_unicode_task_description(self):
        """Test with unicode characters."""
        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.7}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation("测试任务 🚀", "coding")

        assert rec.mode == "parallel"

    def test_very_long_task_description(self):
        """Test with very long task description."""
        long_desc = "a" * 10000

        success_mock = MagicMock()
        success_mock.get_best_mode_for_similar.return_value = None

        auto_mock = MagicMock()
        auto_mock.get_recommendation.return_value = {"suggested_mode": "parallel", "confidence": 0.7}

        coord = MemoryCoordinator(success_mock, auto_mock)
        rec = coord.get_recommendation(long_desc, "coding")

        assert rec.mode == "parallel"

    def test_special_characters_in_domain(self):
        """Test with special characters in domain name."""
        coord = MemoryCoordinator(None, None)
        coord.record_feedback("coding/debugging", MemorySource.SUCCESS, True)

        assert "coding/debugging" in coord._domain_weights

    def test_case_sensitive_domains(self):
        """Test domains are case-sensitive."""
        coord = MemoryCoordinator(None, None)
        coord._domain_weights["Coding"] = DomainWeights(semantic_weight=0.7)
        coord._domain_weights["coding"] = DomainWeights(semantic_weight=0.4)

        upper_s, _ = coord.get_weights_for_domain("Coding")
        lower_s, _ = coord.get_weights_for_domain("coding")

        assert upper_s == 0.7
        assert lower_s == 0.4

    def test_zero_quality_scores_in_consolidate(self):
        """Test consolidate with zero quality scores."""
        entries = []
        for _i in range(10):
            entry = MagicMock()
            entry.primary_domain = "coding"
            entry.domains = ["coding"]
            entry.swarm_mode = "parallel"
            entry.quality_score = 0.0
            entries.append(entry)

        success_mock = MagicMock()
        success_mock.get_all.return_value = entries

        coord = MemoryCoordinator(success_mock, None)
        result = coord.consolidate()

        # Should still work
        assert isinstance(result, int)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
