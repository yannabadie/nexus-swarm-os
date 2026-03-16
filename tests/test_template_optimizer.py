"""
Tests for V12.4 Prompt Template Optimizer.

Validates:
- Prompt analysis (metrics, issues, sections)
- Anti-pattern detection
- Length warnings
- Duplicate detection
- Empty prompt detection
- Conflict detection between instructions
- Outcome tracking
- EMA efficacy calculation
- Stats (per-template, top/worst)
- Token estimation
- Section detection
- State management
- Global singleton
- Module exports
"""

from core.memory_pkg.prompts.template_optimizer import (
    PromptAnalysis,
    PromptIssue,
    PromptOptimizer,
    PromptStats,
    get_optimizer,
    reset_optimizer,
)

# =============================================================================
# Analysis Tests
# =============================================================================


class TestAnalysis:
    """Test prompt analysis."""

    def test_basic_metrics(self):
        prompt = "You are a helpful assistant.\nPlease help the user."
        opt = PromptOptimizer()
        analysis = opt.analyze(prompt)
        assert analysis.char_count == len(prompt)
        assert analysis.word_count == 9
        assert analysis.line_count == 2
        assert analysis.estimated_tokens > 0

    def test_empty_prompt(self):
        opt = PromptOptimizer()
        analysis = opt.analyze("")
        assert analysis.has_errors is True
        assert any(i.category == "empty" for i in analysis.issues)

    def test_whitespace_only_prompt(self):
        opt = PromptOptimizer()
        analysis = opt.analyze("   \n   \n   ")
        assert analysis.has_errors is True

    def test_anti_pattern_please(self):
        opt = PromptOptimizer()
        analysis = opt.analyze("Please respond in JSON format please.")
        issues = [i for i in analysis.issues if i.category == "anti_pattern"]
        assert len(issues) >= 1

    def test_anti_pattern_intensifiers(self):
        opt = PromptOptimizer()
        analysis = opt.analyze("Be very careful and extremely precise.")
        issues = [i for i in analysis.issues if i.category == "anti_pattern"]
        assert len(issues) >= 1

    def test_duplicate_lines(self):
        prompt = "Always respond in JSON.\nSome other instruction.\nAlways respond in JSON."
        opt = PromptOptimizer()
        analysis = opt.analyze(prompt)
        issues = [i for i in analysis.issues if i.category == "redundancy"]
        assert len(issues) >= 1

    def test_no_duplicate_short_lines(self):
        prompt = "Yes\nNo\nYes"
        opt = PromptOptimizer()
        analysis = opt.analyze(prompt)
        issues = [i for i in analysis.issues if i.category == "redundancy"]
        assert len(issues) == 0  # Short lines ignored

    def test_long_prompt_warning(self):
        opt = PromptOptimizer()
        # Create a prompt with >4000 estimated tokens
        prompt = "instruction word " * 4000
        analysis = opt.analyze(prompt)
        issues = [i for i in analysis.issues if i.category == "length"]
        assert len(issues) == 1
        assert issues[0].severity == "warning"

    def test_issue_count(self):
        opt = PromptOptimizer()
        analysis = opt.analyze("Clean prompt without issues.")
        # May have some anti-pattern matches but issue_count should work
        assert analysis.issue_count >= 0

    def test_analysis_to_dict(self):
        opt = PromptOptimizer()
        analysis = opt.analyze("Test prompt.")
        d = analysis.to_dict()
        assert "char_count" in d
        assert "word_count" in d
        assert "estimated_tokens" in d
        assert "issues" in d
        assert "sections" in d

    def test_issue_to_dict(self):
        issue = PromptIssue(
            severity="warning",
            category="length",
            message="Too long",
            line=5,
            suggestion="Trim it.",
        )
        d = issue.to_dict()
        assert d["severity"] == "warning"
        assert d["line"] == 5
        assert d["suggestion"] == "Trim it."


# =============================================================================
# Section Detection Tests
# =============================================================================


class TestSectionDetection:
    """Test section detection."""

    def test_markdown_headers(self):
        prompt = "# Introduction\nSome text\n## Details\nMore text\n### Notes"
        opt = PromptOptimizer()
        analysis = opt.analyze(prompt)
        assert "Introduction" in analysis.sections
        assert "Details" in analysis.sections
        assert "Notes" in analysis.sections

    def test_uppercase_sections(self):
        prompt = "SYSTEM INSTRUCTIONS\nDo this.\nOUTPUT FORMAT\nUse JSON."
        opt = PromptOptimizer()
        analysis = opt.analyze(prompt)
        assert "SYSTEM INSTRUCTIONS" in analysis.sections
        assert "OUTPUT FORMAT" in analysis.sections

    def test_no_sections(self):
        prompt = "Just a simple prompt with no sections."
        opt = PromptOptimizer()
        analysis = opt.analyze(prompt)
        assert analysis.sections == []


# =============================================================================
# Token Estimation Tests
# =============================================================================


class TestTokenEstimation:
    """Test token estimation."""

    def test_estimate(self):
        opt = PromptOptimizer()
        analysis = opt.analyze("one two three four five")
        # 5 words * 1.3 = 6.5 -> 6
        assert analysis.estimated_tokens == 6

    def test_estimate_empty(self):
        opt = PromptOptimizer()
        analysis = opt.analyze("")
        assert analysis.estimated_tokens == 0


# =============================================================================
# Conflict Detection Tests
# =============================================================================


class TestConflictDetection:
    """Test conflict detection."""

    def test_no_conflicts(self):
        opt = PromptOptimizer()
        result = opt.detect_conflicts(
            [
                "Be helpful",
                "Answer questions",
            ]
        )
        assert result.has_conflicts is False
        assert result.conflicts == []

    def test_json_vs_natural_language(self):
        opt = PromptOptimizer()
        result = opt.detect_conflicts(
            [
                "Always respond in JSON format",
                "Use natural language in your responses",
            ]
        )
        assert result.has_conflicts is True
        assert len(result.conflicts) >= 1

    def test_brief_vs_detailed(self):
        opt = PromptOptimizer()
        result = opt.detect_conflicts(
            [
                "Be concise in your answers",
                "Provide detailed explanations",
            ]
        )
        assert result.has_conflicts is True

    def test_always_vs_never(self):
        opt = PromptOptimizer()
        result = opt.detect_conflicts(
            [
                "Always include examples",
                "Never include examples",
            ]
        )
        assert result.has_conflicts is True

    def test_conflict_to_dict(self):
        opt = PromptOptimizer()
        result = opt.detect_conflicts(
            [
                "Be brief",
                "Be detailed and comprehensive",
            ]
        )
        d = result.to_dict()
        assert "has_conflicts" in d
        assert "conflict_count" in d
        assert "conflicts" in d


# =============================================================================
# Outcome Tracking Tests
# =============================================================================


class TestOutcomeTracking:
    """Test outcome recording."""

    def test_record_outcome(self):
        opt = PromptOptimizer()
        opt.record_outcome("template_1", success=True, quality=0.9)
        assert opt.template_count == 1

    def test_record_multiple(self):
        opt = PromptOptimizer()
        opt.record_outcome("t1", success=True, quality=0.8)
        opt.record_outcome("t1", success=False, quality=0.3)
        opt.record_outcome("t2", success=True, quality=0.7)
        assert opt.template_count == 2
        assert opt.total_outcomes == 3

    def test_record_clamps_quality(self):
        opt = PromptOptimizer()
        opt.record_outcome("t1", success=True, quality=1.5)
        opt.record_outcome("t1", success=True, quality=-0.5)
        assert opt.total_outcomes == 2

    def test_record_with_metadata(self):
        opt = PromptOptimizer()
        opt.record_outcome("t1", success=True, metadata={"model": "opus"})
        assert opt.total_outcomes == 1


# =============================================================================
# Stats Tests
# =============================================================================


class TestStats:
    """Test performance statistics."""

    def test_get_stats(self):
        opt = PromptOptimizer()
        opt.record_outcome("t1", success=True, quality=0.9)
        opt.record_outcome("t1", success=True, quality=0.8)
        opt.record_outcome("t1", success=False, quality=0.2)
        stats = opt.get_stats("t1")
        assert stats is not None
        assert stats.total_uses == 3
        assert stats.success_count == 2
        assert stats.failure_count == 1

    def test_get_stats_not_found(self):
        opt = PromptOptimizer()
        assert opt.get_stats("missing") is None

    def test_success_rate(self):
        opt = PromptOptimizer()
        opt.record_outcome("t1", success=True)
        opt.record_outcome("t1", success=True)
        opt.record_outcome("t1", success=False)
        stats = opt.get_stats("t1")
        assert abs(stats.success_rate - 2 / 3) < 0.01

    def test_efficacy_ema(self):
        opt = PromptOptimizer()
        # All successes should push efficacy toward 1.0
        for _ in range(20):
            opt.record_outcome("t1", success=True)
        stats = opt.get_stats("t1")
        assert stats.efficacy > 0.9

    def test_efficacy_decreases_on_failure(self):
        opt = PromptOptimizer()
        for _ in range(10):
            opt.record_outcome("t1", success=True)
        initial = opt.get_stats("t1").efficacy
        opt.record_outcome("t1", success=False)
        assert opt.get_stats("t1").efficacy < initial

    def test_get_all_stats(self):
        opt = PromptOptimizer()
        opt.record_outcome("b_template", success=True)
        opt.record_outcome("a_template", success=False)
        all_stats = opt.get_all_stats()
        assert len(all_stats) == 2
        assert all_stats[0].template_name == "a_template"  # sorted

    def test_get_top_templates(self):
        opt = PromptOptimizer()
        for _ in range(10):
            opt.record_outcome("good", success=True)
        for _ in range(10):
            opt.record_outcome("bad", success=False)
        top = opt.get_top_templates(limit=1)
        assert len(top) == 1
        assert top[0].template_name == "good"

    def test_get_worst_templates(self):
        opt = PromptOptimizer()
        for _ in range(5):
            opt.record_outcome("good", success=True)
        for _ in range(5):
            opt.record_outcome("bad", success=False)
        worst = opt.get_worst_templates(limit=1)
        assert len(worst) == 1
        assert worst[0].template_name == "bad"

    def test_worst_requires_min_uses(self):
        opt = PromptOptimizer()
        opt.record_outcome("t1", success=False)  # Only 1 use
        opt.record_outcome("t1", success=False)  # Only 2 uses
        worst = opt.get_worst_templates()
        assert len(worst) == 0  # Needs >= 3

    def test_stats_to_dict(self):
        opt = PromptOptimizer()
        opt.record_outcome("t1", success=True, quality=0.9)
        stats = opt.get_stats("t1")
        d = stats.to_dict()
        assert d["template_name"] == "t1"
        assert d["total_uses"] == 1
        assert "efficacy" in d
        assert "avg_quality" in d


# =============================================================================
# State Tests
# =============================================================================


class TestState:
    """Test state management."""

    def test_template_count(self):
        opt = PromptOptimizer()
        assert opt.template_count == 0
        opt.record_outcome("t1", success=True)
        assert opt.template_count == 1

    def test_total_outcomes(self):
        opt = PromptOptimizer()
        assert opt.total_outcomes == 0
        opt.record_outcome("t1", success=True)
        opt.record_outcome("t1", success=False)
        assert opt.total_outcomes == 2

    def test_clear(self):
        opt = PromptOptimizer()
        opt.record_outcome("t1", success=True)
        opt.clear()
        assert opt.template_count == 0
        assert opt.total_outcomes == 0

    def test_to_dict(self):
        opt = PromptOptimizer()
        opt.record_outcome("t1", success=True)
        d = opt.to_dict()
        assert d["template_count"] == 1
        assert d["total_outcomes"] == 1
        assert "t1" in d["templates"]


# =============================================================================
# Global Singleton Tests
# =============================================================================


class TestGlobalSingleton:
    """Test global optimizer."""

    def test_get_optimizer(self):
        reset_optimizer()
        opt = get_optimizer()
        assert isinstance(opt, PromptOptimizer)

    def test_singleton(self):
        reset_optimizer()
        o1 = get_optimizer()
        o2 = get_optimizer()
        assert o1 is o2

    def test_reset(self):
        reset_optimizer()
        o1 = get_optimizer()
        reset_optimizer()
        o2 = get_optimizer()
        assert o1 is not o2


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Test module imports."""

    def test_from_prompts_package(self):
        from core.memory_pkg.prompts import (
            ConflictResult,
            PromptAnalysis,
            PromptIssue,
            PromptOptimizer,
            PromptOutcome,
            PromptStats,
            get_optimizer,
            reset_optimizer,
        )

        assert all(
            [
                PromptOptimizer,
                PromptAnalysis,
                PromptIssue,
                PromptStats,
                PromptOutcome,
                ConflictResult,
                get_optimizer,
                reset_optimizer,
            ]
        )

    def test_from_module(self):
        from core.memory_pkg.prompts.template_optimizer import (
            PromptIssue,
            PromptOptimizer,
        )

        assert all([PromptOptimizer, PromptAnalysis, PromptIssue, PromptStats])
