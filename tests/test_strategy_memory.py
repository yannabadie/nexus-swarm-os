"""
Tests for V12.4 Swarm Strategy Memory.

Validates:
- StrategyRecord to_dict / key property
- ModeEffectiveness to_dict / score / success_rate
- ModeSuggestion to_dict
- StrategyStats to_dict
- Recording strategies
- Running average computation
- Mode suggestions (confidence, min_samples)
- Effectiveness queries
- Domain summary / listing
- Bounded history (eviction)
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.intelligence.swarm.strategy_memory import (
    MAX_RECORDS,
    MIN_SAMPLES_FOR_SUGGESTION,
    ModeEffectiveness,
    ModeSuggestion,
    StrategyMemory,
    StrategyRecord,
    StrategyStats,
    get_strategy_memory,
    reset_strategy_memory,
)

# =============================================================================
# StrategyRecord Tests
# =============================================================================


class TestStrategyRecord:
    """Test StrategyRecord dataclass."""

    def test_basic(self):
        r = StrategyRecord(domain="coding", complexity="medium", mode="PARALLEL")
        assert r.domain == "coding"
        assert r.mode == "PARALLEL"

    def test_key(self):
        r = StrategyRecord(domain="coding", complexity="medium", mode="PARALLEL")
        assert r.key == "coding:medium"

    def test_to_dict(self):
        r = StrategyRecord(
            domain="coding",
            complexity="complex",
            mode="LEAD_SUPPORT",
            quality=0.9,
            success=True,
            agents=["claude", "gemini"],
        )
        d = r.to_dict()
        assert d["domain"] == "coding"
        assert d["quality"] == 0.9
        assert d["agents"] == ["claude", "gemini"]


# =============================================================================
# ModeEffectiveness Tests
# =============================================================================


class TestModeEffectiveness:
    """Test ModeEffectiveness dataclass."""

    def test_success_rate_zero(self):
        eff = ModeEffectiveness(mode="PARALLEL")
        assert eff.success_rate == 0.0

    def test_success_rate(self):
        eff = ModeEffectiveness(mode="PARALLEL", total_uses=10, successes=7)
        assert abs(eff.success_rate - 0.7) < 0.01

    def test_score(self):
        eff = ModeEffectiveness(mode="PARALLEL", total_uses=10, successes=8, average_quality=0.9)
        # 0.4 * 0.8 + 0.6 * 0.9 = 0.32 + 0.54 = 0.86
        assert abs(eff.score - 0.86) < 0.01

    def test_to_dict(self):
        eff = ModeEffectiveness(mode="PARALLEL", total_uses=5, successes=4, average_quality=0.85)
        d = eff.to_dict()
        assert d["mode"] == "PARALLEL"
        assert d["total_uses"] == 5
        assert "score" in d


# =============================================================================
# ModeSuggestion Tests
# =============================================================================


class TestModeSuggestion:
    """Test ModeSuggestion dataclass."""

    def test_to_dict(self):
        eff = ModeEffectiveness(mode="PARALLEL", total_uses=10, successes=8, average_quality=0.9)
        s = ModeSuggestion(mode="PARALLEL", confidence=0.8, based_on_samples=10, effectiveness=eff)
        d = s.to_dict()
        assert d["mode"] == "PARALLEL"
        assert d["confidence"] == 0.8
        assert "effectiveness" in d


# =============================================================================
# StrategyStats Tests
# =============================================================================


class TestStrategyStats:
    """Test StrategyStats dataclass."""

    def test_to_dict(self):
        s = StrategyStats(total_records=20, unique_domains=3, unique_keys=5, total_modes_tracked=4)
        d = s.to_dict()
        assert d["total_records"] == 20
        assert d["unique_domains"] == 3


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test strategy recording."""

    def test_record_basic(self):
        mem = StrategyMemory()
        r = mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.8)
        assert r.domain == "coding"
        assert r.mode == "PARALLEL"
        assert mem.record_count == 1

    def test_record_clamps_quality(self):
        mem = StrategyMemory()
        r = mem.record_strategy("coding", "medium", mode="PARALLEL", quality=1.5)
        assert r.quality == 1.0

    def test_record_clamps_negative_quality(self):
        mem = StrategyMemory()
        r = mem.record_strategy("coding", "medium", mode="PARALLEL", quality=-0.5)
        assert r.quality == 0.0

    def test_record_with_agents(self):
        mem = StrategyMemory()
        r = mem.record_strategy("coding", "medium", mode="PARALLEL", agents=["claude", "gemini"])
        assert r.agents == ["claude", "gemini"]

    def test_record_defaults(self):
        mem = StrategyMemory()
        r = mem.record_strategy("coding", "medium", mode="PARALLEL")
        assert r.success is True
        assert r.duration_ms == 0.0
        assert r.agents == []

    def test_multiple_records(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL")
        mem.record_strategy("research", "complex", mode="LEAD_SUPPORT")
        assert mem.record_count == 2


# =============================================================================
# Running Average Tests
# =============================================================================


class TestRunningAverage:
    """Test that effectiveness averages update correctly."""

    def test_quality_average(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.8)
        mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.6)
        effs = mem.get_mode_effectiveness("coding", "medium")
        assert len(effs) == 1
        assert abs(effs[0].average_quality - 0.7) < 0.01

    def test_success_tracking(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL", success=True)
        mem.record_strategy("coding", "medium", mode="PARALLEL", success=False)
        effs = mem.get_mode_effectiveness("coding", "medium")
        assert effs[0].total_uses == 2
        assert effs[0].successes == 1
        assert abs(effs[0].success_rate - 0.5) < 0.01

    def test_duration_average(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL", duration_ms=100)
        mem.record_strategy("coding", "medium", mode="PARALLEL", duration_ms=200)
        effs = mem.get_mode_effectiveness("coding", "medium")
        assert abs(effs[0].average_duration_ms - 150) < 0.01


# =============================================================================
# Suggestion Tests
# =============================================================================


class TestSuggestions:
    """Test mode suggestions."""

    def test_no_data(self):
        mem = StrategyMemory()
        assert mem.suggest_mode("coding", "medium") is None

    def test_insufficient_samples(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.9)
        # Default min_samples is 3, only 1 record
        assert mem.suggest_mode("coding", "medium") is None

    def test_sufficient_samples(self):
        mem = StrategyMemory()
        for _ in range(3):
            mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.9)
        suggestion = mem.suggest_mode("coding", "medium")
        assert suggestion is not None
        assert suggestion.mode == "PARALLEL"

    def test_custom_min_samples(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.9)
        suggestion = mem.suggest_mode("coding", "medium", min_samples=1)
        assert suggestion is not None

    def test_picks_best_mode(self):
        mem = StrategyMemory()
        for _ in range(5):
            mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.5, success=True)
        for _ in range(5):
            mem.record_strategy("coding", "medium", mode="LEAD_SUPPORT", quality=0.9, success=True)
        suggestion = mem.suggest_mode("coding", "medium")
        assert suggestion is not None
        assert suggestion.mode == "LEAD_SUPPORT"

    def test_confidence(self):
        mem = StrategyMemory()
        for _ in range(3):
            mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.9)
        suggestion = mem.suggest_mode("coding", "medium")
        # confidence = 3 / (3 + 3) = 0.5
        assert abs(suggestion.confidence - 0.5) < 0.01

    def test_confidence_increases_with_samples(self):
        mem = StrategyMemory()
        for _ in range(100):
            mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.9)
        suggestion = mem.suggest_mode("coding", "medium")
        # confidence = 100 / (100 + 3) ≈ 0.97
        assert suggestion.confidence > 0.95

    def test_suggestion_to_dict(self):
        mem = StrategyMemory()
        for _ in range(5):
            mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.8)
        suggestion = mem.suggest_mode("coding", "medium")
        d = suggestion.to_dict()
        assert d["mode"] == "PARALLEL"
        assert "effectiveness" in d


# =============================================================================
# Effectiveness Query Tests
# =============================================================================


class TestEffectivenessQueries:
    """Test effectiveness queries."""

    def test_empty(self):
        mem = StrategyMemory()
        assert mem.get_mode_effectiveness("coding", "medium") == []

    def test_multiple_modes(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.8)
        mem.record_strategy("coding", "medium", mode="LEAD_SUPPORT", quality=0.9)
        effs = mem.get_mode_effectiveness("coding", "medium")
        assert len(effs) == 2
        # Sorted by score descending
        assert effs[0].mode == "LEAD_SUPPORT"

    def test_get_all_effectiveness(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL", quality=0.8)
        mem.record_strategy("research", "complex", mode="LEAD_SUPPORT", quality=0.9)
        all_eff = mem.get_all_effectiveness()
        assert "coding:medium" in all_eff
        assert "research:complex" in all_eff


# =============================================================================
# Domain Summary Tests
# =============================================================================


class TestDomainSummary:
    """Test domain summary and listing."""

    def test_domain_summary(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL")
        mem.record_strategy("coding", "medium", mode="PARALLEL")
        mem.record_strategy("coding", "complex", mode="LEAD_SUPPORT")
        summary = mem.get_domain_summary("coding")
        assert summary["PARALLEL"] == 2
        assert summary["LEAD_SUPPORT"] == 1

    def test_domain_summary_empty(self):
        mem = StrategyMemory()
        assert mem.get_domain_summary("missing") == {}

    def test_list_domains(self):
        mem = StrategyMemory()
        mem.record_strategy("research", "medium", mode="PARALLEL")
        mem.record_strategy("coding", "medium", mode="PARALLEL")
        assert mem.list_domains() == ["coding", "research"]

    def test_list_keys(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL")
        mem.record_strategy("coding", "complex", mode="LEAD_SUPPORT")
        keys = mem.list_keys()
        assert "coding:medium" in keys
        assert "coding:complex" in keys


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded record history."""

    def test_eviction(self):
        mem = StrategyMemory(max_records=5)
        for i in range(10):
            mem.record_strategy("coding", "medium", mode="PARALLEL", quality=i * 0.1)
        assert mem.record_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test strategy memory statistics."""

    def test_initial_stats(self):
        mem = StrategyMemory()
        stats = mem.get_stats()
        assert stats.total_records == 0
        assert stats.unique_domains == 0

    def test_stats_after_recording(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL")
        mem.record_strategy("research", "complex", mode="LEAD_SUPPORT")
        stats = mem.get_stats()
        assert stats.total_records == 2
        assert stats.unique_domains == 2
        assert stats.unique_keys == 2
        assert stats.total_modes_tracked == 2

    def test_stats_to_dict(self):
        mem = StrategyMemory()
        d = mem.get_stats().to_dict()
        assert "total_records" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_record_count(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL")
        mem.record_strategy("coding", "medium", mode="PARALLEL")
        assert mem.record_count == 2

    def test_clear(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL")
        mem.clear()
        assert mem.record_count == 0
        assert mem.get_mode_effectiveness("coding", "medium") == []

    def test_to_dict(self):
        mem = StrategyMemory()
        mem.record_strategy("coding", "medium", mode="PARALLEL")
        d = mem.to_dict()
        assert d["record_count"] == 1
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global strategy memory."""

    def test_get(self):
        reset_strategy_memory()
        mem = get_strategy_memory()
        assert isinstance(mem, StrategyMemory)

    def test_singleton(self):
        reset_strategy_memory()
        m1 = get_strategy_memory()
        m2 = get_strategy_memory()
        assert m1 is m2

    def test_reset(self):
        reset_strategy_memory()
        m1 = get_strategy_memory()
        reset_strategy_memory()
        m2 = get_strategy_memory()
        assert m1 is not m2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_swarm_package(self):
        from core.intelligence.swarm import (
            ModeEffectiveness,
            ModeSuggestion,
            StrategyMemory,
            StrategyRecord,
            StrategyStats,
            get_strategy_memory,
            reset_strategy_memory,
        )

        assert all(
            [
                StrategyMemory,
                StrategyRecord,
                ModeEffectiveness,
                ModeSuggestion,
                StrategyStats,
                get_strategy_memory,
                reset_strategy_memory,
            ]
        )

    def test_constants(self):
        assert MAX_RECORDS == 50000
        assert MIN_SAMPLES_FOR_SUGGESTION == 3
