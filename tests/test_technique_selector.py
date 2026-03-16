"""
Tests for V12.4 Adaptive Prompt Technique Selector.

Validates:
- PromptTechnique enum values
- TECHNIQUE_INSTRUCTIONS completeness
- TaskCluster.keyword_score() matching
- TechniqueSelector.select() for various task types
- Domain hint boosting in select()
- compose_prompt() technique injection
- record_outcome() history tracking
- get_cluster_names() cluster listing
- get_technique_stats() statistics
- SelectionResult dataclass fields
- Persistence (save / reload history)
- Singleton pattern (get_technique_selector, reset_technique_selector)
"""

import json
import tempfile
from pathlib import Path

from core.memory_pkg.prompts.technique_selector import (
    TECHNIQUE_INSTRUCTIONS,
    PromptTechnique,
    SelectionResult,
    TaskCluster,
    TechniqueSelector,
    get_technique_selector,
    reset_technique_selector,
)

# =============================================================================
# PromptTechnique Enum Tests
# =============================================================================


class TestPromptTechnique:
    """Test PromptTechnique enum definition."""

    def test_all_six_values_exist(self):
        members = list(PromptTechnique)
        assert len(members) == 6

    def test_chain_of_thought(self):
        assert PromptTechnique.CHAIN_OF_THOUGHT.value == "cot"

    def test_few_shot(self):
        assert PromptTechnique.FEW_SHOT.value == "few_shot"

    def test_decomposition(self):
        assert PromptTechnique.DECOMPOSITION.value == "decomposition"

    def test_self_consistency(self):
        assert PromptTechnique.SELF_CONSISTENCY.value == "self_consistency"

    def test_role_playing(self):
        assert PromptTechnique.ROLE_PLAYING.value == "role_playing"

    def test_step_by_step(self):
        assert PromptTechnique.STEP_BY_STEP.value == "step_by_step"

    def test_is_str_enum(self):
        """PromptTechnique inherits from str, so values are strings."""
        for tech in PromptTechnique:
            assert isinstance(tech.value, str)
            assert isinstance(tech, str)


# =============================================================================
# TECHNIQUE_INSTRUCTIONS Tests
# =============================================================================


class TestTechniqueInstructions:
    """Test TECHNIQUE_INSTRUCTIONS dictionary."""

    def test_all_techniques_have_instructions(self):
        for tech in PromptTechnique:
            assert tech in TECHNIQUE_INSTRUCTIONS, f"Missing instruction for {tech}"

    def test_instructions_are_non_empty_strings(self):
        for tech, text in TECHNIQUE_INSTRUCTIONS.items():
            assert isinstance(text, str), f"{tech}: instruction is not a string"
            assert len(text.strip()) > 0, f"{tech}: instruction is empty"

    def test_no_extra_keys(self):
        """No stale keys beyond the enum members."""
        assert set(TECHNIQUE_INSTRUCTIONS.keys()) == set(PromptTechnique)


# =============================================================================
# TaskCluster Tests
# =============================================================================


class TestTaskCluster:
    """Test TaskCluster dataclass and keyword_score()."""

    def test_keyword_score_full_match(self):
        cluster = TaskCluster(
            name="test",
            keywords=["bug", "fix"],
            techniques=[],
        )
        score = cluster.keyword_score("fix the bug")
        assert score == 1.0  # 2/2 keywords matched

    def test_keyword_score_partial_match(self):
        cluster = TaskCluster(
            name="test",
            keywords=["bug", "fix", "error", "crash"],
            techniques=[],
        )
        score = cluster.keyword_score("fix the bug")
        assert score == 0.5  # 2/4 keywords matched

    def test_keyword_score_no_match(self):
        cluster = TaskCluster(
            name="test",
            keywords=["security", "vulnerability"],
            techniques=[],
        )
        score = cluster.keyword_score("write a hello world function")
        assert score == 0.0

    def test_keyword_score_case_insensitive(self):
        cluster = TaskCluster(
            name="test",
            keywords=["bug", "error"],
            techniques=[],
        )
        score = cluster.keyword_score("BUG in the ERROR handler")
        assert score == 1.0

    def test_keyword_score_empty_keywords(self):
        cluster = TaskCluster(
            name="empty",
            keywords=[],
            techniques=[],
        )
        # max(0, 1) = 1, hits = 0 => 0/1 = 0.0
        score = cluster.keyword_score("anything")
        assert score == 0.0

    def test_keyword_score_substring_match(self):
        """Keywords match as substrings within text."""
        cluster = TaskCluster(
            name="test",
            keywords=["code"],
            techniques=[],
        )
        score = cluster.keyword_score("refactoring the codebase")
        assert score == 1.0  # "code" is in "codebase"

    def test_default_description(self):
        cluster = TaskCluster(name="t", keywords=[], techniques=[])
        assert cluster.description == ""


# =============================================================================
# TechniqueSelector.select() Tests
# =============================================================================


class TestSelectMethod:
    """Test TechniqueSelector.select() for various task types."""

    def _make_selector(self):
        """Create a TechniqueSelector with a temporary storage path."""
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "history.json"
        return TechniqueSelector(storage_path=path)

    def test_coding_task(self):
        selector = self._make_selector()
        result = selector.select("Implement a new class for user authentication")
        assert result.cluster_name == "coding"
        assert PromptTechnique.DECOMPOSITION in result.techniques
        assert result.cluster_score > 0

    def test_debugging_task(self):
        selector = self._make_selector()
        result = selector.select("Fix the bug causing a crash in the login module")
        assert result.cluster_name == "debugging"
        assert len(result.techniques) >= 1
        assert result.cluster_score > 0

    def test_security_task(self):
        selector = self._make_selector()
        result = selector.select("Audit the application for SQL injection vulnerabilities")
        assert result.cluster_name == "security"
        assert PromptTechnique.ROLE_PLAYING in result.techniques

    def test_unknown_task_fallback(self):
        selector = self._make_selector()
        result = selector.select("xylophone zephyr quintessence")
        assert result.cluster_name == "default"
        assert result.cluster_score == 0.0
        assert PromptTechnique.CHAIN_OF_THOUGHT in result.techniques
        assert "safe default" in result.reasoning.lower()

    def test_research_task(self):
        selector = self._make_selector()
        result = selector.select("Research and analyze the performance bottleneck")
        assert result.cluster_name == "research"
        assert PromptTechnique.CHAIN_OF_THOUGHT in result.techniques

    def test_architecture_task(self):
        selector = self._make_selector()
        result = selector.select("Design the system architecture and schema")
        assert result.cluster_name == "architecture"

    def test_testing_task(self):
        selector = self._make_selector()
        result = selector.select("Write pytest tests for coverage")
        assert result.cluster_name == "testing"

    def test_documentation_task(self):
        selector = self._make_selector()
        result = selector.select("Document this module with docstrings")
        assert result.cluster_name == "documentation"

    def test_review_task(self):
        selector = self._make_selector()
        result = selector.select("Review the code quality and suggest improvements")
        assert result.cluster_name == "review"

    def test_max_techniques_default(self):
        selector = self._make_selector()
        result = selector.select("Debug the error in the code module")
        assert len(result.techniques) <= TechniqueSelector.MAX_TECHNIQUES

    def test_max_techniques_override(self):
        selector = self._make_selector()
        result = selector.select("Debug the error crash traceback", max_techniques=1)
        assert len(result.techniques) == 1

    def test_result_has_reasoning(self):
        selector = self._make_selector()
        result = selector.select("Implement a new function")
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0


# =============================================================================
# TechniqueSelector.select() with Domain Hints
# =============================================================================


class TestSelectWithDomainHints:
    """Test that domain hints boost cluster scores."""

    def _make_selector(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "history.json"
        return TechniqueSelector(storage_path=path)

    def test_domain_hint_boosts_matching_cluster(self):
        selector = self._make_selector()
        # "data" alone does not match security cluster
        result_no_hint = selector.select("process data")
        result_with_hint = selector.select("process data", domains=["security"])
        assert result_with_hint.cluster_name == "security"
        # Without the hint, it should not be security
        assert result_no_hint.cluster_name != "security"

    def test_domain_hint_matches_cluster_name(self):
        selector = self._make_selector()
        result = selector.select("do something", domains=["debugging"])
        assert result.cluster_name == "debugging"
        assert result.cluster_score >= 0.4  # At least the boost

    def test_domain_hint_matches_keyword(self):
        selector = self._make_selector()
        # "exploit" is a keyword in the security cluster
        result = selector.select("process this", domains=["exploit"])
        assert result.cluster_name == "security"

    def test_multiple_domain_hints(self):
        selector = self._make_selector()
        result = selector.select("do work", domains=["coding", "testing"])
        # Should match one of the hinted clusters
        assert result.cluster_name in ("coding", "testing")
        assert result.cluster_score >= 0.4


# =============================================================================
# compose_prompt() Tests
# =============================================================================


class TestComposePrompt:
    """Test TechniqueSelector.compose_prompt() injection."""

    def _make_selector(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "history.json"
        return TechniqueSelector(storage_path=path)

    def test_technique_injection_format(self):
        selector = self._make_selector()
        base = "Fix the login timeout."
        techniques = [PromptTechnique.CHAIN_OF_THOUGHT]
        result = selector.compose_prompt(base, techniques)

        assert "[APPROACH GUIDANCE]" in result
        assert "[END APPROACH GUIDANCE]" in result
        assert result.endswith(base)
        assert TECHNIQUE_INSTRUCTIONS[PromptTechnique.CHAIN_OF_THOUGHT] in result

    def test_multiple_techniques_injected(self):
        selector = self._make_selector()
        base = "Analyze data."
        techniques = [PromptTechnique.DECOMPOSITION, PromptTechnique.STEP_BY_STEP]
        result = selector.compose_prompt(base, techniques)

        assert TECHNIQUE_INSTRUCTIONS[PromptTechnique.DECOMPOSITION] in result
        assert TECHNIQUE_INSTRUCTIONS[PromptTechnique.STEP_BY_STEP] in result

    def test_empty_techniques_returns_base(self):
        selector = self._make_selector()
        base = "Just do it."
        result = selector.compose_prompt(base, [])
        assert result == base

    def test_each_instruction_prefixed_with_dash(self):
        selector = self._make_selector()
        base = "Task"
        techniques = [PromptTechnique.FEW_SHOT]
        result = selector.compose_prompt(base, techniques)
        instruction = TECHNIQUE_INSTRUCTIONS[PromptTechnique.FEW_SHOT]
        assert f"- {instruction}" in result


# =============================================================================
# record_outcome() Tests
# =============================================================================


class TestRecordOutcome:
    """Test TechniqueSelector.record_outcome() history tracking."""

    def _make_selector(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "history.json"
        return TechniqueSelector(storage_path=path)

    def test_single_outcome_recorded(self):
        selector = self._make_selector()
        selector.record_outcome([PromptTechnique.CHAIN_OF_THOUGHT], quality=0.9)
        assert "cot" in selector._history
        assert selector._history["cot"] == [0.9]

    def test_multiple_outcomes_tracked(self):
        selector = self._make_selector()
        selector.record_outcome([PromptTechnique.FEW_SHOT], quality=0.7)
        selector.record_outcome([PromptTechnique.FEW_SHOT], quality=0.8)
        assert len(selector._history["few_shot"]) == 2

    def test_multiple_techniques_per_outcome(self):
        selector = self._make_selector()
        techniques = [PromptTechnique.DECOMPOSITION, PromptTechnique.STEP_BY_STEP]
        selector.record_outcome(techniques, quality=0.85)
        assert "decomposition" in selector._history
        assert "step_by_step" in selector._history

    def test_history_capped_at_50(self):
        selector = self._make_selector()
        for i in range(60):
            selector.record_outcome([PromptTechnique.CHAIN_OF_THOUGHT], quality=float(i) / 60)
        assert len(selector._history["cot"]) == 50

    def test_outcome_influences_historical_score(self):
        selector = self._make_selector()
        # Record many high-quality outcomes
        for _ in range(10):
            selector.record_outcome([PromptTechnique.DECOMPOSITION], quality=0.95)
        score = selector._get_historical_score(PromptTechnique.DECOMPOSITION)
        # EMA should be well above the neutral 0.5
        assert score > 0.8


# =============================================================================
# get_cluster_names() Tests
# =============================================================================


class TestGetClusterNames:
    """Test get_cluster_names() returns all cluster names."""

    def test_returns_all_default_clusters(self):
        tmp = tempfile.mkdtemp()
        selector = TechniqueSelector(storage_path=Path(tmp) / "h.json")
        names = selector.get_cluster_names()
        expected = ["coding", "debugging", "research", "architecture", "security", "testing", "documentation", "review"]
        assert names == expected

    def test_returns_list_of_strings(self):
        tmp = tempfile.mkdtemp()
        selector = TechniqueSelector(storage_path=Path(tmp) / "h.json")
        names = selector.get_cluster_names()
        assert isinstance(names, list)
        for name in names:
            assert isinstance(name, str)


# =============================================================================
# get_technique_stats() Tests
# =============================================================================


class TestGetTechniqueStats:
    """Test get_technique_stats() statistics."""

    def _make_selector(self):
        tmp = tempfile.mkdtemp()
        return TechniqueSelector(storage_path=Path(tmp) / "h.json")

    def test_empty_history_stats(self):
        selector = self._make_selector()
        stats = selector.get_technique_stats()
        assert len(stats) == 6  # One entry per PromptTechnique
        for tech in PromptTechnique:
            entry = stats[tech.value]
            assert entry["observations"] == 0
            assert entry["avg_quality"] == 0.5  # Neutral default

    def test_stats_with_recorded_data(self):
        selector = self._make_selector()
        selector.record_outcome([PromptTechnique.CHAIN_OF_THOUGHT], quality=0.9)
        selector.record_outcome([PromptTechnique.CHAIN_OF_THOUGHT], quality=0.7)
        stats = selector.get_technique_stats()
        cot_stats = stats["cot"]
        assert cot_stats["observations"] == 2
        assert abs(cot_stats["avg_quality"] - 0.8) < 0.01

    def test_stats_keys_match_techniques(self):
        selector = self._make_selector()
        stats = selector.get_technique_stats()
        expected_keys = {tech.value for tech in PromptTechnique}
        assert set(stats.keys()) == expected_keys


# =============================================================================
# SelectionResult Dataclass Tests
# =============================================================================


class TestSelectionResult:
    """Test SelectionResult dataclass fields."""

    def test_fields_present(self):
        result = SelectionResult(
            techniques=[PromptTechnique.CHAIN_OF_THOUGHT],
            cluster_name="coding",
            cluster_score=0.75,
            reasoning="Matched coding cluster",
        )
        assert result.techniques == [PromptTechnique.CHAIN_OF_THOUGHT]
        assert result.cluster_name == "coding"
        assert result.cluster_score == 0.75
        assert result.reasoning == "Matched coding cluster"

    def test_multiple_techniques(self):
        result = SelectionResult(
            techniques=[PromptTechnique.DECOMPOSITION, PromptTechnique.STEP_BY_STEP],
            cluster_name="testing",
            cluster_score=0.5,
            reasoning="test",
        )
        assert len(result.techniques) == 2

    def test_empty_techniques_allowed(self):
        result = SelectionResult(
            techniques=[],
            cluster_name="default",
            cluster_score=0.0,
            reasoning="fallback",
        )
        assert result.techniques == []


# =============================================================================
# Persistence Tests
# =============================================================================


class TestPersistence:
    """Test save and reload of technique history."""

    def test_save_and_reload(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "subdir" / "history.json"

        # First instance: record data
        sel1 = TechniqueSelector(storage_path=path)
        sel1.record_outcome([PromptTechnique.FEW_SHOT], quality=0.88)
        sel1.record_outcome([PromptTechnique.DECOMPOSITION], quality=0.72)

        # Second instance: loads from same path
        sel2 = TechniqueSelector(storage_path=path)
        assert "few_shot" in sel2._history
        assert sel2._history["few_shot"] == [0.88]
        assert "decomposition" in sel2._history
        assert sel2._history["decomposition"] == [0.72]

    def test_persist_creates_parent_dirs(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "a" / "b" / "c" / "history.json"
        sel = TechniqueSelector(storage_path=path)
        sel.record_outcome([PromptTechnique.ROLE_PLAYING], quality=0.6)
        assert path.exists()

    def test_load_nonexistent_file_is_safe(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "nonexistent.json"
        sel = TechniqueSelector(storage_path=path)
        assert sel._history == {}

    def test_load_corrupt_file_is_safe(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "corrupt.json"
        path.write_text("NOT VALID JSON {{{{")
        sel = TechniqueSelector(storage_path=path)
        assert sel._history == {}

    def test_persisted_data_is_valid_json(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "history.json"
        sel = TechniqueSelector(storage_path=path)
        sel.record_outcome([PromptTechnique.STEP_BY_STEP], quality=0.5)

        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)
        assert "step_by_step" in data


# =============================================================================
# Singleton Tests
# =============================================================================


class TestSingleton:
    """Test get_technique_selector and reset_technique_selector."""

    def test_get_returns_instance(self):
        reset_technique_selector()
        sel = get_technique_selector()
        assert isinstance(sel, TechniqueSelector)

    def test_singleton_returns_same_instance(self):
        reset_technique_selector()
        s1 = get_technique_selector()
        s2 = get_technique_selector()
        assert s1 is s2

    def test_reset_clears_singleton(self):
        reset_technique_selector()
        s1 = get_technique_selector()
        reset_technique_selector()
        s2 = get_technique_selector()
        assert s1 is not s2

    def test_reset_then_get_creates_fresh(self):
        reset_technique_selector()
        sel = get_technique_selector()
        sel.record_outcome([PromptTechnique.CHAIN_OF_THOUGHT], quality=0.5)
        reset_technique_selector()
        sel2 = get_technique_selector()
        # Fresh instance should not share in-memory history
        # (it may load from the default file, but in-memory object is different)
        assert sel is not sel2


# =============================================================================
# EMA Historical Score Tests
# =============================================================================


class TestHistoricalScore:
    """Test _get_historical_score() EMA calculation."""

    def _make_selector(self):
        tmp = tempfile.mkdtemp()
        return TechniqueSelector(storage_path=Path(tmp) / "h.json")

    def test_neutral_prior_when_no_history(self):
        selector = self._make_selector()
        score = selector._get_historical_score(PromptTechnique.CHAIN_OF_THOUGHT)
        assert score == 0.5

    def test_single_observation(self):
        selector = self._make_selector()
        selector._history["cot"] = [0.9]
        score = selector._get_historical_score(PromptTechnique.CHAIN_OF_THOUGHT)
        assert score == 0.9  # EMA with one value = that value

    def test_ema_converges_toward_recent(self):
        selector = self._make_selector()
        # Start with low values, end with high values
        selector._history["cot"] = [0.1] * 10 + [0.9] * 10
        score = selector._get_historical_score(PromptTechnique.CHAIN_OF_THOUGHT)
        # EMA with alpha=0.2 should lean more toward recent 0.9 values
        assert score > 0.5

    def test_ema_alpha_value(self):
        assert TechniqueSelector.EMA_ALPHA == 0.2
