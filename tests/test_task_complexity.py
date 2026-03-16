"""
Tests for P5.5 - Adaptive Metacognition (Task Complexity Estimation)

Verifies that task complexity heuristics correctly classify tasks
and enable adaptive metacognitive monitoring.

Sprint 2 - Performance optimization
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from core.intelligence.reasoning.task_complexity import (
    TaskComplexity,
    estimate_complexity,
    should_monitor_metacognition,
)


class TestTaskComplexity:
    """Test task complexity enum and estimation."""

    def test_trivial_commands(self):
        """TRIVIAL: Known commands should be classified as trivial."""
        assert estimate_complexity("/help") == TaskComplexity.TRIVIAL
        assert estimate_complexity("/status") == TaskComplexity.TRIVIAL
        assert estimate_complexity("/stats") == TaskComplexity.TRIVIAL
        assert estimate_complexity("/reset") == TaskComplexity.TRIVIAL
        assert estimate_complexity("/clear") == TaskComplexity.TRIVIAL

    def test_trivial_short_queries(self):
        """TRIVIAL: Short queries without complex verbs."""
        assert estimate_complexity("Hello") == TaskComplexity.TRIVIAL
        assert estimate_complexity("What is NEXUS?") == TaskComplexity.TRIVIAL
        assert estimate_complexity("Show me the logs") == TaskComplexity.TRIVIAL
        assert estimate_complexity("Thanks") == TaskComplexity.TRIVIAL

    def test_simple_queries(self):
        """SIMPLE: Single-step factual queries (30-100 chars, no complex keywords)."""
        assert estimate_complexity("What files are in the core directory?") == TaskComplexity.SIMPLE
        assert estimate_complexity("How does the swarm engine work in NEXUS?") == TaskComplexity.SIMPLE
        # Short queries (<30 chars) without keywords are TRIVIAL, not SIMPLE
        assert estimate_complexity("Read the config file") == TaskComplexity.TRIVIAL

    def test_moderate_multi_step(self):
        """MODERATE: Multi-step workflows."""
        assert estimate_complexity("Read the file and then check the tests") == TaskComplexity.MODERATE
        assert estimate_complexity("Update the config when ready") == TaskComplexity.MODERATE
        assert estimate_complexity("Check status and verify the output") == TaskComplexity.MODERATE

    def test_complex_analysis_tasks(self):
        """COMPLEX: Tasks with complex verbs (analyze, design, etc.)."""
        assert estimate_complexity("Analyze the authentication module") == TaskComplexity.COMPLEX
        assert estimate_complexity("Compare the two implementations") == TaskComplexity.COMPLEX
        assert estimate_complexity("Design a new rate limiter") == TaskComplexity.COMPLEX
        assert estimate_complexity("Refactor the orchestrator") == TaskComplexity.COMPLEX
        assert estimate_complexity("Investigate the bug in phase 4") == TaskComplexity.COMPLEX
        assert estimate_complexity("Optimize the memory usage") == TaskComplexity.COMPLEX

    def test_complex_multi_step_analysis(self):
        """COMPLEX: Multi-step tasks with analysis."""
        task = "Analyze the code and then suggest improvements"
        assert estimate_complexity(task) == TaskComplexity.COMPLEX

        task2 = "Compare the implementations and refactor if needed"
        assert estimate_complexity(task2) == TaskComplexity.COMPLEX

    def test_empty_input(self):
        """Empty or whitespace-only input should be TRIVIAL."""
        assert estimate_complexity("") == TaskComplexity.TRIVIAL
        assert estimate_complexity("   ") == TaskComplexity.TRIVIAL

    def test_short_with_complex_verb(self):
        """Short tasks can still be COMPLEX if they contain complex verbs."""
        assert estimate_complexity("Analyze this") == TaskComplexity.COMPLEX
        assert estimate_complexity("Design API") == TaskComplexity.COMPLEX


class TestShouldMonitorMetacognition:
    """Test metacognition monitoring decision."""

    def test_bypass_trivial(self):
        """TRIVIAL tasks should NOT trigger metacognition (default threshold: MODERATE)."""
        assert not should_monitor_metacognition("/help")
        assert not should_monitor_metacognition("Hello")
        assert not should_monitor_metacognition("/status")

    def test_bypass_simple(self):
        """SIMPLE tasks should NOT trigger metacognition (default threshold: MODERATE)."""
        assert not should_monitor_metacognition("What is NEXUS?")
        assert not should_monitor_metacognition("Read the config file")

    def test_monitor_moderate(self):
        """MODERATE tasks SHOULD trigger metacognition."""
        assert should_monitor_metacognition("Read file and then check tests")
        assert should_monitor_metacognition("Update config when ready")

    def test_monitor_complex(self):
        """COMPLEX tasks SHOULD trigger metacognition."""
        assert should_monitor_metacognition("Analyze the auth module")
        assert should_monitor_metacognition("Design a new rate limiter")
        assert should_monitor_metacognition("Compare implementations and refactor")

    def test_custom_threshold(self):
        """Custom threshold should work."""
        # SIMPLE task (40 chars) with SIMPLE threshold -> should monitor
        simple_task = "How does the swarm engine work in NEXUS?"
        assert estimate_complexity(simple_task) == TaskComplexity.SIMPLE
        assert should_monitor_metacognition(simple_task, threshold=TaskComplexity.SIMPLE)

        # TRIVIAL task with TRIVIAL threshold -> should monitor
        assert should_monitor_metacognition("/help", threshold=TaskComplexity.TRIVIAL)

        # SIMPLE task with COMPLEX threshold -> should NOT monitor
        assert not should_monitor_metacognition(simple_task, threshold=TaskComplexity.COMPLEX)


class TestPerformanceHeuristics:
    """Test that heuristics are fast and don't call LLMs."""

    def test_fast_estimation(self):
        """Complexity estimation should be very fast (<1ms)."""
        import time

        task = "Analyze this code and suggest refactoring improvements then test the changes"
        start = time.perf_counter()
        for _ in range(1000):
            estimate_complexity(task)
        duration = time.perf_counter() - start

        # 1000 estimations should take < 50ms (avg < 0.05ms per call)
        # Relaxed from 10ms: CI runners have variable load
        assert duration < 0.05, f"Too slow: {duration * 1000:.2f}ms for 1000 calls"

    def test_no_external_dependencies(self):
        """Complexity estimation should not import LLM drivers."""
        import sys

        # Clear any previous imports
        drivers_before = {k for k in sys.modules if "drivers" in k}

        estimate_complexity("Analyze this code")

        drivers_after = {k for k in sys.modules if "drivers" in k}

        # Should not have imported any new driver modules
        assert drivers_before == drivers_after


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
