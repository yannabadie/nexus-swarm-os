"""
Tests for V12.4 Inference Latency Analyzer.

Validates:
- LatencySample to_dict / properties
- ModelLatencyProfile to_dict / properties
- AnalyzerStats to_dict
- Recording samples
- Model profile updates
- Queries (profiles, fastest, anomalies, recent)
- Bounded history
- Statistics
- State management
- Global singleton
- Module exports
"""

from core.drivers.inference_latency_analyzer import (
    LATENCY_ANOMALY_THRESHOLD_MS,
    MAX_SAMPLES,
    AnalyzerStats,
    InferenceLatencyAnalyzer,
    LatencySample,
    ModelLatencyProfile,
    get_latency_analyzer,
    reset_latency_analyzer,
)

# =============================================================================
# LatencySample Tests
# =============================================================================


class TestLatencySample:
    """Test LatencySample dataclass."""

    def test_is_anomalous_false(self):
        s = LatencySample(latency_ms=1000.0)
        assert s.is_anomalous is False

    def test_is_anomalous_true(self):
        s = LatencySample(latency_ms=LATENCY_ANOMALY_THRESHOLD_MS + 1)
        assert s.is_anomalous is True

    def test_tokens_per_second(self):
        s = LatencySample(response_tokens=100, latency_ms=2000.0)
        # 100 tokens / 2 seconds = 50 tok/s
        assert abs(s.tokens_per_second - 50.0) < 0.01

    def test_tokens_per_second_zero_latency(self):
        s = LatencySample(response_tokens=100, latency_ms=0.0)
        assert s.tokens_per_second == 0.0

    def test_to_dict(self):
        s = LatencySample(sample_id="ls_000001", model_id="claude-opus", latency_ms=500.0)
        d = s.to_dict()
        assert d["model_id"] == "claude-opus"
        assert "is_anomalous" in d
        assert "tokens_per_second" in d


# =============================================================================
# ModelLatencyProfile Tests
# =============================================================================


class TestModelLatencyProfile:
    """Test ModelLatencyProfile dataclass."""

    def test_avg_latency(self):
        m = ModelLatencyProfile(model_id="m", sample_count=4, total_latency_ms=400.0)
        assert abs(m.avg_latency_ms - 100.0) < 0.01

    def test_avg_latency_zero(self):
        m = ModelLatencyProfile(model_id="m")
        assert m.avg_latency_ms == 0.0

    def test_avg_tokens_per_second(self):
        m = ModelLatencyProfile(model_id="m", total_response_tokens=200, total_latency_ms=4000.0)
        # 200 tokens / 4 seconds = 50 tok/s
        assert abs(m.avg_tokens_per_second - 50.0) < 0.01

    def test_to_dict(self):
        m = ModelLatencyProfile(model_id="claude-opus", sample_count=10)
        d = m.to_dict()
        assert "avg_latency_ms" in d
        assert "avg_tokens_per_second" in d


# =============================================================================
# AnalyzerStats Tests
# =============================================================================


class TestAnalyzerStats:
    """Test AnalyzerStats dataclass."""

    def test_to_dict(self):
        s = AnalyzerStats(total_samples=100, unique_models=3, total_anomalies=2)
        d = s.to_dict()
        assert d["total_samples"] == 100


# =============================================================================
# Recording Tests
# =============================================================================


class TestRecording:
    """Test sample recording."""

    def test_record_basic(self):
        a = InferenceLatencyAnalyzer()
        s = a.record_sample("claude-opus", latency_ms=500.0)
        assert s.sample_id == "ls_000000"
        assert a.sample_count == 1

    def test_record_with_tokens(self):
        a = InferenceLatencyAnalyzer()
        s = a.record_sample("gemini-pro", latency_ms=1000.0, prompt_tokens=500, response_tokens=200)
        assert s.prompt_tokens == 500

    def test_auto_incrementing_ids(self):
        a = InferenceLatencyAnalyzer()
        s1 = a.record_sample("m1", latency_ms=100)
        s2 = a.record_sample("m2", latency_ms=200)
        assert s1.sample_id == "ls_000000"
        assert s2.sample_id == "ls_000001"

    def test_profile_updates(self):
        a = InferenceLatencyAnalyzer()
        a.record_sample("claude-opus", latency_ms=100)
        a.record_sample("claude-opus", latency_ms=200)
        a.record_sample("claude-opus", latency_ms=300)
        p = a.get_model_profile("claude-opus")
        assert p is not None
        assert p.sample_count == 3
        assert abs(p.min_latency_ms - 100.0) < 0.01
        assert abs(p.max_latency_ms - 300.0) < 0.01

    def test_multiple_models(self):
        a = InferenceLatencyAnalyzer()
        a.record_sample("claude-opus", latency_ms=100)
        a.record_sample("gemini-pro", latency_ms=200)
        assert len(a.get_all_profiles()) == 2


# =============================================================================
# Query Tests
# =============================================================================


class TestQueries:
    """Test query methods."""

    def test_get_model_profile_not_found(self):
        a = InferenceLatencyAnalyzer()
        assert a.get_model_profile("missing") is None

    def test_get_all_profiles_sorted(self):
        a = InferenceLatencyAnalyzer()
        a.record_sample("model_a", latency_ms=100)
        a.record_sample("model_a", latency_ms=100)
        a.record_sample("model_b", latency_ms=200)
        profiles = a.get_all_profiles()
        assert profiles[0].model_id == "model_a"  # 2 > 1

    def test_get_fastest_models(self):
        a = InferenceLatencyAnalyzer()
        a.record_sample("slow", latency_ms=5000)
        a.record_sample("fast", latency_ms=100)
        a.record_sample("medium", latency_ms=1000)
        fastest = a.get_fastest_models(limit=2)
        assert len(fastest) == 2
        assert fastest[0].model_id == "fast"

    def test_get_anomalies(self):
        a = InferenceLatencyAnalyzer()
        a.record_sample("m", latency_ms=100)
        a.record_sample("m", latency_ms=LATENCY_ANOMALY_THRESHOLD_MS + 100)
        anomalies = a.get_anomalies()
        assert len(anomalies) == 1

    def test_get_recent_samples(self):
        a = InferenceLatencyAnalyzer()
        for i in range(10):
            a.record_sample("m", latency_ms=i * 100)
        recent = a.get_recent_samples(limit=3)
        assert len(recent) == 3

    def test_get_recent_filtered(self):
        a = InferenceLatencyAnalyzer()
        a.record_sample("claude", latency_ms=100)
        a.record_sample("gemini", latency_ms=200)
        a.record_sample("claude", latency_ms=300)
        recent = a.get_recent_samples(model_id="claude")
        assert len(recent) == 2


# =============================================================================
# Bounded History Tests
# =============================================================================


class TestBoundedHistory:
    """Test bounded sample history."""

    def test_eviction(self):
        a = InferenceLatencyAnalyzer(max_samples=5)
        for i in range(10):
            a.record_sample("m", latency_ms=i * 100)
        assert a.sample_count == 5


# =============================================================================
# Statistics Tests
# =============================================================================


class TestStatistics:
    """Test analyzer statistics."""

    def test_initial_stats(self):
        a = InferenceLatencyAnalyzer()
        stats = a.get_stats()
        assert stats.total_samples == 0

    def test_stats_after_recording(self):
        a = InferenceLatencyAnalyzer()
        a.record_sample("claude-opus", latency_ms=100)
        a.record_sample("gemini-pro", latency_ms=200)
        stats = a.get_stats()
        assert stats.total_samples == 2
        assert stats.unique_models == 2

    def test_stats_to_dict(self):
        a = InferenceLatencyAnalyzer()
        d = a.get_stats().to_dict()
        assert "total_samples" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_count(self):
        a = InferenceLatencyAnalyzer()
        a.record_sample("m", latency_ms=100)
        assert a.sample_count == 1

    def test_clear(self):
        a = InferenceLatencyAnalyzer()
        a.record_sample("m", latency_ms=100)
        a.clear()
        assert a.sample_count == 0
        assert a.get_model_profile("m") is None

    def test_to_dict(self):
        a = InferenceLatencyAnalyzer()
        a.record_sample("m", latency_ms=100)
        d = a.to_dict()
        assert "stats" in d


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global latency analyzer."""

    def test_get(self):
        reset_latency_analyzer()
        a = get_latency_analyzer()
        assert isinstance(a, InferenceLatencyAnalyzer)

    def test_singleton(self):
        reset_latency_analyzer()
        a1 = get_latency_analyzer()
        a2 = get_latency_analyzer()
        assert a1 is a2

    def test_reset(self):
        reset_latency_analyzer()
        a1 = get_latency_analyzer()
        reset_latency_analyzer()
        a2 = get_latency_analyzer()
        assert a1 is not a2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_drivers_package(self):
        from core.drivers import (
            AnalyzerStats,
            InferenceLatencyAnalyzer,
            LatencySample,
            ModelLatencyProfile,
            get_latency_analyzer,
            reset_latency_analyzer,
        )

        assert all(
            [
                InferenceLatencyAnalyzer,
                LatencySample,
                ModelLatencyProfile,
                AnalyzerStats,
                get_latency_analyzer,
                reset_latency_analyzer,
            ]
        )

    def test_constants(self):
        from core.drivers.inference_latency_analyzer import (
            LATENCY_ANOMALY_THRESHOLD_MS,
        )

        assert MAX_SAMPLES == 50000
        assert LATENCY_ANOMALY_THRESHOLD_MS == 30000.0
