"""
NEXUS V8.2.0a - AnalysisAdapter Tests

Tests for bidirectional conversion between TaskAnalysis and IndependentAnalysis.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.adapters import AnalysisAdapter
from core.intelligence.hive_mind.types import IndependentAnalysis
from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskComplexity, TaskDomain


class TestAnalysisAdapter:
    """Tests for AnalysisAdapter bidirectional conversion."""

    def test_import(self):
        """Test that AnalysisAdapter can be imported."""
        assert AnalysisAdapter is not None

    def test_complexity_to_string(self):
        """Test complexity enum to string conversion."""
        result = AnalysisAdapter.complexity_to_string(TaskComplexity.MODERATE)
        assert "moderate" in result.lower()

    def test_string_to_complexity(self):
        """Test string to complexity enum conversion."""
        assert AnalysisAdapter.string_to_complexity("simple task") == TaskComplexity.SIMPLE
        assert AnalysisAdapter.string_to_complexity("Complex multi-step") == TaskComplexity.COMPLEX
        assert AnalysisAdapter.string_to_complexity("EXPERT level") == TaskComplexity.EXPERT
        assert AnalysisAdapter.string_to_complexity("unknown") == TaskComplexity.MODERATE  # Default

    def test_to_task_analysis_basic(self):
        """Test basic HiveMind -> Swarm conversion."""
        hive = IndependentAnalysis(
            agent_id="gemini_primary",
            task_understanding="Implement a login form",
            complexity_assessment="moderate",
            proposed_approach="Use React for frontend",
            required_capabilities=["code_execution", "web_search"],
            potential_risks=["Security issues"],
            confidence=0.8,
            reasoning="Standard web task",
            timestamp=datetime.now(),
        )

        result = AnalysisAdapter.to_task_analysis(hive, "Create a login page")

        assert isinstance(result, TaskAnalysis)
        assert result.complexity == TaskComplexity.MODERATE
        assert result.confidence == 0.8
        assert result.raw_input == "Create a login page"
        assert result.requires_web  # Because "web_search" in capabilities

    def test_to_task_analysis_complexity_mapping(self):
        """Test different complexity mappings."""
        test_cases = [
            ("trivial one-liner", TaskComplexity.TRIVIAL),
            ("simple straightforward", TaskComplexity.SIMPLE),
            ("moderate complexity", TaskComplexity.MODERATE),
            ("complex architecture", TaskComplexity.COMPLEX),
            ("expert-level security audit", TaskComplexity.EXPERT),
        ]

        for complexity_str, expected in test_cases:
            hive = IndependentAnalysis(
                agent_id="test",
                task_understanding="test",
                complexity_assessment=complexity_str,
                proposed_approach="test",
                required_capabilities=[],
                potential_risks=[],
                confidence=0.5,
                reasoning="test",
                timestamp=datetime.now(),
            )
            result = AnalysisAdapter.to_task_analysis(hive, "test")
            assert result.complexity == expected, f"Failed for '{complexity_str}'"

    def test_to_independent_analysis_basic(self):
        """Test basic Swarm -> HiveMind conversion."""
        swarm = TaskAnalysis(
            complexity=TaskComplexity.COMPLEX,
            domains=[TaskDomain.CODING, TaskDomain.SECURITY],
            primary_domain=TaskDomain.CODING,
            requires_web=True,
            requires_code_execution=True,
            requires_deep_reasoning=True,
            requires_iteration=False,
            gemini_fit_score=0.6,
            claude_fit_score=0.9,
            raw_input="Audit the authentication module",
            confidence=0.85,
            detected_keywords=["audit", "authentication"],
        )

        result = AnalysisAdapter.to_independent_analysis(swarm, "claude_opus")

        assert isinstance(result, IndependentAnalysis)
        assert result.agent_id == "claude_opus"
        assert result.complexity_assessment == "COMPLEX"
        assert result.confidence == 0.85
        assert "web_search" in result.required_capabilities
        assert "deep_reasoning" in result.required_capabilities

    def test_roundtrip_preserves_key_fields(self):
        """Test that roundtrip conversion preserves key fields."""
        original = IndependentAnalysis(
            agent_id="test_agent",
            task_understanding="Fix bug in parser",
            complexity_assessment="moderate",
            proposed_approach="Debug and fix",
            required_capabilities=["debugging"],
            potential_risks=["Regression"],
            confidence=0.75,
            reasoning="Standard bug fix",
            timestamp=datetime.now(),
        )

        # HiveMind -> Swarm
        swarm = AnalysisAdapter.to_task_analysis(original, "Fix the parser bug")

        # Swarm -> HiveMind
        recovered = AnalysisAdapter.to_independent_analysis(swarm, "test_agent")

        # Key fields should be preserved (with some transformation)
        assert recovered.confidence == original.confidence
        assert recovered.complexity_assessment == "MODERATE"  # Normalized

    def test_domain_detection(self):
        """Test automatic domain detection."""
        hive = IndependentAnalysis(
            agent_id="test",
            task_understanding="Write unit tests for the API",
            complexity_assessment="moderate",
            proposed_approach="Use pytest",
            required_capabilities=[],
            potential_risks=[],
            confidence=0.5,
            reasoning="test",
            timestamp=datetime.now(),
        )

        result = AnalysisAdapter.to_task_analysis(hive, "Create tests for the REST API endpoints", detect_domains=True)

        # Should detect TESTING and possibly WEB_INTERACTION
        assert TaskDomain.TESTING in result.domains


@pytest.mark.skip(reason="V12.4.1: SuccessMemoryV2 uses LanceDB semantic search, not time decay")
class TestSuccessMemoryDecay:
    """Tests for time decay in SuccessMemory."""

    def test_decay_function_exists(self):
        """Test that _apply_time_decay method exists."""
        import tempfile
        from pathlib import Path

        from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

        with tempfile.TemporaryDirectory() as tmp:
            memory = SuccessMemory(Path(tmp))
            assert hasattr(memory, "_apply_time_decay")

    def test_decay_recent_entry(self):
        """Test that recent entries have minimal decay."""
        import tempfile
        from pathlib import Path

        from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

        with tempfile.TemporaryDirectory() as tmp:
            memory = SuccessMemory(Path(tmp))

            # Today's timestamp
            recent = datetime.now().isoformat()
            score = memory._apply_time_decay(1.0, recent)

            # Should be close to 1.0 (minimal decay)
            assert score >= 0.95

    def test_decay_old_entry(self):
        """Test that old entries have significant decay."""
        import tempfile
        from datetime import timedelta
        from pathlib import Path

        from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

        with tempfile.TemporaryDirectory() as tmp:
            memory = SuccessMemory(Path(tmp))

            # 52 weeks ago
            old = (datetime.now() - timedelta(weeks=52)).isoformat()
            score = memory._apply_time_decay(1.0, old)

            # Should be significantly decayed (around 0.28)
            assert score < 0.35

    def test_decay_invalid_timestamp(self):
        """Test that invalid timestamps return original score."""
        import tempfile
        from pathlib import Path

        from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

        with tempfile.TemporaryDirectory() as tmp:
            memory = SuccessMemory(Path(tmp))

            # Invalid timestamp should return original
            score = memory._apply_time_decay(0.5, "invalid-timestamp")
            assert score == 0.5

    def test_get_best_mode_with_decay(self):
        """Test that get_best_mode_for_similar accepts apply_decay parameter."""
        import inspect
        import tempfile
        from pathlib import Path

        from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

        with tempfile.TemporaryDirectory() as tmp:
            memory = SuccessMemory(Path(tmp))

            # Check signature includes apply_decay
            sig = inspect.signature(memory.get_best_mode_for_similar)
            assert "apply_decay" in sig.parameters

    def test_exponential_decay_curve(self):
        """V8.8: Test exponential decay produces expected curve."""
        import tempfile
        from datetime import datetime, timedelta
        from pathlib import Path

        from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

        with tempfile.TemporaryDirectory() as tmp:
            memory = SuccessMemory(Path(tmp))

            # Test decay at various ages
            test_cases = [
                (0, 1.0),  # Today: no decay
                (7, 0.97),  # 1 week: ~3% decay
                (28, 0.89),  # 4 weeks: ~11% decay
                (84, 0.71),  # 12 weeks: ~29% decay
                (364, 0.23),  # 52 weeks: ~77% decay
            ]

            for age_days, expected_approx in test_cases:
                timestamp = (datetime.now() - timedelta(days=age_days)).isoformat()
                score = memory._apply_time_decay(1.0, timestamp)

                # Allow 5% tolerance for floating point and time differences
                assert abs(score - expected_approx) < 0.05, (
                    f"At {age_days} days, expected ~{expected_approx}, got {score}"
                )

    def test_domain_bonus_parameter(self):
        """V8.8: Test domain_bonus parameter in _apply_time_decay."""
        import tempfile
        from datetime import datetime
        from pathlib import Path

        from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

        with tempfile.TemporaryDirectory() as tmp:
            memory = SuccessMemory(Path(tmp))

            timestamp = datetime.now().isoformat()

            # Without bonus
            score_no_bonus = memory._apply_time_decay(0.5, timestamp, domain_bonus=0.0)
            # With bonus
            score_with_bonus = memory._apply_time_decay(0.5, timestamp, domain_bonus=0.15)

            # Score with bonus should be higher
            assert score_with_bonus > score_no_bonus
            assert abs(score_with_bonus - score_no_bonus - 0.15) < 0.01

    def test_get_best_mode_with_query_domains(self):
        """V8.8: Test query_domains parameter in get_best_mode_for_similar."""
        import inspect
        import tempfile
        from pathlib import Path

        from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

        with tempfile.TemporaryDirectory() as tmp:
            memory = SuccessMemory(Path(tmp))

            # Check signature includes query_domains
            sig = inspect.signature(memory.get_best_mode_for_similar)
            assert "query_domains" in sig.parameters
            assert "domain_boost" in sig.parameters

    def test_decay_capped_at_one(self):
        """V8.8: Test that decayed score doesn't exceed 1.0."""
        import tempfile
        from datetime import datetime
        from pathlib import Path

        from core.memory_pkg.memory import SuccessMemory  # V2 via backward compat alias

        with tempfile.TemporaryDirectory() as tmp:
            memory = SuccessMemory(Path(tmp))

            timestamp = datetime.now().isoformat()

            # With high domain bonus, score should still be capped at 1.0
            score = memory._apply_time_decay(0.9, timestamp, domain_bonus=0.3)
            assert score <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
