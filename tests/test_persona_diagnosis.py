"""Tests for MultiPersonaDiagnoser - multi-perspective failure analysis."""

from core.intelligence.hive_mind.persona_diagnosis import (
    MultiPersonaDiagnoser,
    MultiPersonaResult,
    PersonaType,
    get_persona_diagnoser,
    reset_persona_diagnoser,
)

# =============================================================================
# Basic Analysis
# =============================================================================


class TestBasicAnalysis:
    def test_analyze_returns_result(self):
        d = MultiPersonaDiagnoser()
        result = d.analyze(
            failure_context="Step 3 failed with timeout after 30s",
            gemini_diagnosis="Timeout due to large input processing",
            claude_diagnosis="API rate limiting caused delay",
        )
        assert isinstance(result, MultiPersonaResult)
        assert len(result.persona_insights) == 4  # All 4 personas

    def test_all_personas_contribute(self):
        d = MultiPersonaDiagnoser()
        result = d.analyze(
            failure_context="Error: NoneType has no attribute 'run'",
            gemini_diagnosis="Null reference in execution path",
            claude_diagnosis="Missing initialization step",
        )
        personas = {i.persona for i in result.persona_insights}
        assert PersonaType.ARCHITECT in personas
        assert PersonaType.DEBUGGER in personas
        assert PersonaType.SECURITY in personas
        assert PersonaType.PERFORMANCE in personas

    def test_custom_personas(self):
        d = MultiPersonaDiagnoser(personas=[PersonaType.DEBUGGER, PersonaType.SECURITY])
        result = d.analyze(
            failure_context="Error in execution",
            gemini_diagnosis="Bug",
            claude_diagnosis="Bug",
        )
        assert len(result.persona_insights) == 2

    def test_synthesis_contains_primary_cause(self):
        d = MultiPersonaDiagnoser()
        result = d.analyze(
            failure_context="Timeout in API call",
            gemini_diagnosis="Timeout after 30 seconds",
            claude_diagnosis="Slow response from external service",
        )
        assert result.primary_root_cause != ""
        assert result.synthesis != ""


# =============================================================================
# Persona-Specific Detection
# =============================================================================


class TestArchitectPersona:
    def test_detects_strategy_issues(self):
        d = MultiPersonaDiagnoser(personas=[PersonaType.ARCHITECT])
        result = d.analyze(
            failure_context="Strategy wrong: approach doesn't address the problem",
            gemini_diagnosis="Incorrect strategy selected",
            claude_diagnosis="Need different approach",
            failure_type="strategy_wrong",
        )
        insight = result.persona_insights[0]
        assert (
            "strategy" in insight.root_cause_hypothesis.lower() or "structural" in insight.root_cause_hypothesis.lower()
        )
        assert insight.confidence >= 0.5

    def test_detects_dependency_issues(self):
        d = MultiPersonaDiagnoser(personas=[PersonaType.ARCHITECT])
        result = d.analyze(
            failure_context="Step B depends on Step A output which was missing",
            gemini_diagnosis="Dependency chain broken",
            claude_diagnosis="Missing prerequisite",
        )
        insight = result.persona_insights[0]
        assert insight.missed_by_others is not None
        assert "dependency" in insight.missed_by_others.lower()


class TestDebuggerPersona:
    def test_detects_runtime_errors(self):
        d = MultiPersonaDiagnoser(personas=[PersonaType.DEBUGGER])
        result = d.analyze(
            failure_context="Exception: KeyError 'user_id' in line 42",
            gemini_diagnosis="Unhandled exception in data processing",
            claude_diagnosis="Missing key in response dictionary",
        )
        insight = result.persona_insights[0]
        assert insight.confidence >= 0.5
        assert len(insight.contributing_factors) > 0

    def test_detects_null_references(self):
        d = MultiPersonaDiagnoser(personas=[PersonaType.DEBUGGER])
        result = d.analyze(
            failure_context="NoneType has no attribute 'execute'",
            gemini_diagnosis="Null reference error",
            claude_diagnosis="Object was None when method called",
        )
        insight = result.persona_insights[0]
        assert insight.missed_by_others is not None
        assert "null" in insight.missed_by_others.lower()


class TestSecurityPersona:
    def test_detects_hallucination_risk(self):
        d = MultiPersonaDiagnoser(personas=[PersonaType.SECURITY])
        result = d.analyze(
            failure_context="LLM generated incorrect file path that doesn't exist",
            gemini_diagnosis="Hallucination: fabricated path",
            claude_diagnosis="Non-existent resource referenced",
            failure_type="hallucination",
        )
        insight = result.persona_insights[0]
        assert insight.confidence >= 0.7
        assert insight.missed_by_others is not None
        assert "hallucination" in insight.missed_by_others.lower()

    def test_detects_sensitive_data(self):
        d = MultiPersonaDiagnoser(personas=[PersonaType.SECURITY])
        result = d.analyze(
            failure_context="Error: credential token expired",
            gemini_diagnosis="Token expiry caused auth failure",
            claude_diagnosis="Need to refresh secret key",
        )
        insight = result.persona_insights[0]
        has_sensitive = any("sensitive" in f.lower() for f in insight.contributing_factors)
        assert has_sensitive


class TestPerformancePersona:
    def test_detects_timeout(self):
        d = MultiPersonaDiagnoser(personas=[PersonaType.PERFORMANCE])
        result = d.analyze(
            failure_context="Operation timed out after 60 seconds",
            gemini_diagnosis="Timeout in step 3",
            claude_diagnosis="Slow execution, exceeded time limit",
            failure_type="timeout",
        )
        insight = result.persona_insights[0]
        assert insight.confidence >= 0.7
        assert "time" in insight.root_cause_hypothesis.lower()

    def test_detects_budget_overrun(self):
        d = MultiPersonaDiagnoser(personas=[PersonaType.PERFORMANCE])
        result = d.analyze(
            failure_context="Token budget exceeded at step 5",
            gemini_diagnosis="Too many tokens used in analysis",
            claude_diagnosis="Budget exceeded, expensive operations",
            failure_type="budget_exceeded",
        )
        insight = result.persona_insights[0]
        assert insight.missed_by_others is not None
        assert "budget" in insight.missed_by_others.lower()

    def test_detects_retry_loops(self):
        d = MultiPersonaDiagnoser(personas=[PersonaType.PERFORMANCE])
        result = d.analyze(
            failure_context="Retry attempt 3: still stuck in same error loop",
            gemini_diagnosis="Repeated failure pattern",
            claude_diagnosis="Same error on retry",
        )
        insight = result.persona_insights[0]
        has_retry = any("repeated" in f.lower() for f in insight.contributing_factors)
        assert has_retry


# =============================================================================
# Synthesis
# =============================================================================


class TestSynthesis:
    def test_synthesis_has_all_fields(self):
        d = MultiPersonaDiagnoser()
        result = d.analyze(
            failure_context="General failure in execution",
            gemini_diagnosis="Something went wrong",
            claude_diagnosis="Error occurred",
        )
        assert result.primary_root_cause != ""
        assert isinstance(result.all_contributing_factors, list)
        assert isinstance(result.all_recommended_changes, list)
        assert 0.0 <= result.confidence <= 1.0
        assert 0.0 <= result.consensus_level <= 1.0

    def test_deduplicates_factors(self):
        d = MultiPersonaDiagnoser()
        result = d.analyze(
            failure_context="Timeout error occurred multiple times",
            gemini_diagnosis="Timeout due to slow processing",
            claude_diagnosis="Slow timeout in API call",
        )
        # Factors should be unique
        assert len(result.all_contributing_factors) == len(set(result.all_contributing_factors))

    def test_unique_insights(self):
        d = MultiPersonaDiagnoser()
        result = d.analyze(
            failure_context="Hallucination: LLM fabricated a dependency that doesn't exist",
            gemini_diagnosis="Hallucinated dependency",
            claude_diagnosis="Non-existent module referenced",
            failure_type="hallucination",
        )
        unique = result.get_unique_insights()
        # Security persona should catch hallucination
        assert len(unique) > 0

    def test_weighted_confidence(self):
        d = MultiPersonaDiagnoser()
        result = d.analyze(
            failure_context="Timeout in step 3",
            gemini_diagnosis="Timeout",
            claude_diagnosis="Timeout",
            failure_type="timeout",
        )
        # Performance persona should have high confidence, pulling average up
        assert result.confidence > 0.4


# =============================================================================
# Stats & Lifecycle
# =============================================================================


class TestStatsAndLifecycle:
    def test_stats_initial(self):
        d = MultiPersonaDiagnoser()
        stats = d.get_stats()
        assert stats["analyses_run"] == 0
        assert stats["personas_active"] == 4

    def test_stats_after_analysis(self):
        d = MultiPersonaDiagnoser()
        d.analyze("failure", "diag1", "diag2")
        stats = d.get_stats()
        assert stats["analyses_run"] == 1

    def test_get_last_result(self):
        d = MultiPersonaDiagnoser()
        assert d.get_last_result() is None
        d.analyze("failure", "diag1", "diag2")
        assert d.get_last_result() is not None

    def test_reset(self):
        d = MultiPersonaDiagnoser()
        d.analyze("failure", "diag1", "diag2")
        d.reset()
        assert d.get_stats()["analyses_run"] == 0
        assert d.get_last_result() is None


# =============================================================================
# Singleton
# =============================================================================


class TestSingleton:
    def test_get_returns_same_instance(self):
        reset_persona_diagnoser()
        d1 = get_persona_diagnoser()
        d2 = get_persona_diagnoser()
        assert d1 is d2

    def test_reset_creates_new_instance(self):
        reset_persona_diagnoser()
        d1 = get_persona_diagnoser()
        reset_persona_diagnoser()
        d2 = get_persona_diagnoser()
        assert d1 is not d2
