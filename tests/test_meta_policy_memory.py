"""
Tests for NEXUS V12.4 Meta-Policy Memory (MPR).

Validates:
- PolicyRule creation, score computation, usage recording
- RuleCategory enum values
- AdmissibilityResult and RetrievalResult dataclasses
- MetaPolicyMemory.consolidate() - new rule creation, duplicate strengthening
- MetaPolicyMemory.retrieve_applicable() - tag matching, context matching, scoring
- MetaPolicyMemory.check_admissibility() - blocking detection, HAC patterns
- MetaPolicyMemory.record_outcome() - score updates
- MetaPolicyMemory.get_stats() - empty and with data
- Persistence - save and reload from file
- Rule cap enforcement
- Singleton pattern (get_meta_policy_memory, reset_meta_policy_memory)
"""

import json
import time
from dataclasses import dataclass

import pytest

from core.intelligence.reasoning.meta_policy_memory import (
    AdmissibilityResult,
    MetaPolicyMemory,
    MPMStats,
    PolicyRule,
    RetrievalResult,
    RuleCategory,
    get_meta_policy_memory,
    reset_meta_policy_memory,
)

# =============================================================================
# Mock for TriplePathwayResult
# =============================================================================


@dataclass
class MockTriplePathwayResult:
    """Mock TriplePathwayResult for testing without importing the real one."""

    principle: str = "Always set timeout on external API calls"
    procedure: str = "Use requests.get(url, timeout=10)"
    synthesis: str = "Set timeout=10s with exponential backoff for all HTTP calls"
    failure_type: str = "timeout"
    mast_codes: list[str] = None

    def __post_init__(self):
        if self.mast_codes is None:
            self.mast_codes = ["COMM_001"]


# =============================================================================
# RuleCategory Tests
# =============================================================================


class TestRuleCategory:
    """Tests for RuleCategory enum."""

    def test_all_values_present(self):
        expected = {"timeout", "validation", "communication", "resource", "retry", "safety", "general"}
        actual = {c.value for c in RuleCategory}
        assert actual == expected

    def test_is_string_enum(self):
        assert isinstance(RuleCategory.TIMEOUT, str)
        assert RuleCategory.TIMEOUT == "timeout"

    def test_from_value(self):
        assert RuleCategory("validation") == RuleCategory.VALIDATION

    def test_invalid_value_raises(self):
        with pytest.raises(ValueError):
            RuleCategory("nonexistent")


# =============================================================================
# PolicyRule Tests
# =============================================================================


class TestPolicyRule:
    """Tests for PolicyRule dataclass and score computation."""

    def _make_rule(self, **overrides) -> PolicyRule:
        defaults = dict(
            id="rule-001",
            predicate="external API call without timeout",
            action="set timeout=10s with backoff",
            category="timeout",
            source_task="Fix API timeout bug",
            failure_type="timeout",
            mast_codes=["COMM_001"],
            tags=["COMM_001", "timeout"],
            created_at=time.time(),
        )
        defaults.update(overrides)
        return PolicyRule(**defaults)

    def test_basic_creation(self):
        rule = self._make_rule()
        assert rule.id == "rule-001"
        assert rule.predicate == "external API call without timeout"
        assert rule.action == "set timeout=10s with backoff"
        assert rule.category == "timeout"

    def test_defaults(self):
        rule = self._make_rule()
        assert rule.usage_count == 0
        assert rule.success_count == 0
        assert rule.last_used is None
        assert rule.confidence == 0.5

    def test_score_initial(self):
        """Initial Bayesian score: (0+1)/(0+2) = 0.5."""
        rule = self._make_rule()
        assert rule.score == pytest.approx(0.5)

    def test_score_after_successes(self):
        """Score after 3 successes: (3+1)/(3+2) = 0.8."""
        rule = self._make_rule(usage_count=3, success_count=3)
        assert rule.score == pytest.approx(0.8)

    def test_score_after_failures(self):
        """Score after 3 failures: (0+1)/(3+2) = 0.2."""
        rule = self._make_rule(usage_count=3, success_count=0)
        assert rule.score == pytest.approx(0.2)

    def test_score_mixed(self):
        """Score with mixed results: (2+1)/(4+2) = 0.5."""
        rule = self._make_rule(usage_count=4, success_count=2)
        assert rule.score == pytest.approx(0.5)

    def test_record_usage_success(self):
        rule = self._make_rule()
        rule.record_usage(success=True)
        assert rule.usage_count == 1
        assert rule.success_count == 1
        assert rule.last_used is not None
        # Confidence EMA: 0.8 * 0.5 + 0.2 * 1.0 = 0.6
        assert rule.confidence == pytest.approx(0.6)

    def test_record_usage_failure(self):
        rule = self._make_rule()
        rule.record_usage(success=False)
        assert rule.usage_count == 1
        assert rule.success_count == 0
        # Confidence EMA: 0.8 * 0.5 + 0.2 * 0.0 = 0.4
        assert rule.confidence == pytest.approx(0.4)

    def test_record_usage_multiple(self):
        rule = self._make_rule()
        rule.record_usage(success=True)
        rule.record_usage(success=True)
        rule.record_usage(success=False)
        assert rule.usage_count == 3
        assert rule.success_count == 2

    def test_to_dict(self):
        rule = self._make_rule()
        d = rule.to_dict()
        assert d["id"] == "rule-001"
        assert d["predicate"] == "external API call without timeout"
        assert d["mast_codes"] == ["COMM_001"]
        assert isinstance(d, dict)

    def test_to_dict_roundtrip(self):
        original = self._make_rule()
        d = original.to_dict()
        reconstructed = PolicyRule(**d)
        assert reconstructed.id == original.id
        assert reconstructed.predicate == original.predicate
        assert reconstructed.score == original.score


# =============================================================================
# AdmissibilityResult Tests
# =============================================================================


class TestAdmissibilityResult:
    """Tests for AdmissibilityResult dataclass."""

    def test_not_blocked(self):
        result = AdmissibilityResult(is_blocked=False)
        assert result.is_blocked is False
        assert result.blocking_rules == []
        assert result.suggested_alternative == ""
        assert result.reason == ""

    def test_blocked(self):
        rule = PolicyRule(
            id="r1",
            predicate="p",
            action="a",
            category="timeout",
            source_task="t",
            failure_type="f",
            mast_codes=[],
            tags=[],
            created_at=time.time(),
        )
        result = AdmissibilityResult(
            is_blocked=True,
            blocking_rules=[rule],
            suggested_alternative="Use timeout",
            reason="Missing timeout",
        )
        assert result.is_blocked is True
        assert len(result.blocking_rules) == 1
        assert result.suggested_alternative == "Use timeout"
        assert result.reason == "Missing timeout"


# =============================================================================
# RetrievalResult Tests
# =============================================================================


class TestRetrievalResult:
    """Tests for RetrievalResult dataclass."""

    def test_empty(self):
        result = RetrievalResult(rules=[], prompt_injection="")
        assert result.rules == []
        assert result.prompt_injection == ""

    def test_with_rules(self):
        rule = PolicyRule(
            id="r1",
            predicate="p",
            action="a",
            category="timeout",
            source_task="t",
            failure_type="f",
            mast_codes=[],
            tags=[],
            created_at=time.time(),
        )
        result = RetrievalResult(rules=[rule], prompt_injection="text")
        assert len(result.rules) == 1
        assert result.prompt_injection == "text"


# =============================================================================
# MetaPolicyMemory Tests
# =============================================================================


class TestMetaPolicyMemoryConsolidate:
    """Tests for MetaPolicyMemory.consolidate()."""

    def test_consolidate_creates_new_rule(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="Always validate input before processing",
            procedure="Use pydantic models for validation",
            synthesis="Validate all inputs with pydantic schema",
            failure_type="validation",
        )
        rule = mpm.consolidate(mars, mast_codes=["VAL_002"], source_task="Fix input bug")
        assert rule.id is not None
        assert rule.predicate == "Always validate input before processing"
        assert rule.action == "Validate all inputs with pydantic schema"
        assert rule.source_task == "Fix input bug"
        assert "VAL_002" in rule.mast_codes
        assert "VAL_002" in rule.tags
        assert "validation" in rule.tags
        assert mpm.rule_count == 1

    def test_consolidate_uses_synthesis_over_procedure(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="principle text",
            procedure="procedure text",
            synthesis="synthesis text",
        )
        rule = mpm.consolidate(mars)
        assert rule.action == "synthesis text"

    def test_consolidate_falls_back_to_procedure(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="principle text",
            procedure="procedure text",
            synthesis="",
        )
        rule = mpm.consolidate(mars)
        assert rule.action == "procedure text"

    def test_consolidate_duplicate_strengthens(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        # Use a principle longer than 80 chars so the prefix matches for duplicates
        base = "Always set timeout on external API calls when making HTTP requests to third-party services"
        mars = MockTriplePathwayResult(principle=base)
        rule1 = mpm.consolidate(mars, mast_codes=["COMM_001"])
        original_confidence = rule1.confidence

        # Same 80-char prefix triggers duplicate detection
        mars2 = MockTriplePathwayResult(
            principle=base + " (updated with more detail)",
        )
        rule2 = mpm.consolidate(mars2, mast_codes=["COMM_001"])

        # Should return the same rule, strengthened
        assert rule2.id == rule1.id
        assert rule2.usage_count == rule1.usage_count  # Same object
        assert rule2.confidence > original_confidence
        assert mpm.rule_count == 1  # No duplicate created

    def test_consolidate_different_predicates_creates_separate(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars1 = MockTriplePathwayResult(principle="Always set timeout")
        mars2 = MockTriplePathwayResult(principle="Always validate input")

        mpm.consolidate(mars1)
        mpm.consolidate(mars2)
        assert mpm.rule_count == 2

    def test_consolidate_truncates_long_predicate(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(principle="x" * 1000)
        rule = mpm.consolidate(mars)
        assert len(rule.predicate) == 500

    def test_consolidate_truncates_long_source_task(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult()
        rule = mpm.consolidate(mars, source_task="y" * 500)
        assert len(rule.source_task) == 200

    def test_consolidate_categorizes_timeout(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="API call hangs with slow timeout",
            failure_type="timeout",
        )
        rule = mpm.consolidate(mars)
        assert rule.category == "timeout"

    def test_consolidate_categorizes_validation(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="must validate schema format check",
            procedure="verify type assertion",
            failure_type="validation_error",
        )
        rule = mpm.consolidate(mars)
        assert rule.category == "validation"

    def test_consolidate_categorizes_general_fallback(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="some obscure rule",
            procedure="do something",
            synthesis="handle it",
            failure_type="unknown_xyz",
        )
        rule = mpm.consolidate(mars)
        assert rule.category == "general"

    def test_consolidate_no_mast_codes(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult()
        rule = mpm.consolidate(mars, mast_codes=None)
        assert rule.mast_codes == []

    def test_consolidate_persists_to_disk(self, tmp_path):
        storage = tmp_path / "rules.jsonl"
        mpm = MetaPolicyMemory(storage_path=storage)
        mars = MockTriplePathwayResult()
        mpm.consolidate(mars, mast_codes=["COMM_001"])
        assert storage.exists()
        lines = storage.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["predicate"] == "Always set timeout on external API calls"


class TestMetaPolicyMemoryRetrieve:
    """Tests for MetaPolicyMemory.retrieve_applicable()."""

    def _populate(self, mpm: MetaPolicyMemory) -> list[PolicyRule]:
        """Add several rules for retrieval tests."""
        rules = []
        configs = [
            MockTriplePathwayResult(
                principle="timeout on external HTTP calls",
                synthesis="use requests timeout parameter",
                failure_type="timeout",
            ),
            MockTriplePathwayResult(
                principle="validate JSON schema before processing",
                synthesis="use pydantic model for validation",
                failure_type="validation",
            ),
            MockTriplePathwayResult(
                principle="retry with exponential backoff on network failure",
                synthesis="implement retry with backoff strategy",
                failure_type="retry",
            ),
        ]
        for i, mars in enumerate(configs):
            rule = mpm.consolidate(mars, mast_codes=[f"CODE_{i:03d}"], source_task=f"Task {i}")
            rules.append(rule)
        return rules

    def test_retrieve_empty(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.retrieve_applicable(context="anything")
        assert result.rules == []
        assert result.prompt_injection == ""

    def test_retrieve_by_context_keywords(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        self._populate(mpm)

        result = mpm.retrieve_applicable(context="timeout on external HTTP calls")
        assert len(result.rules) > 0
        # The timeout rule should score high because of keyword overlap
        predicates = [r.predicate for r in result.rules]
        assert any("timeout" in p for p in predicates)

    def test_retrieve_by_tags(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        self._populate(mpm)

        result = mpm.retrieve_applicable(tags=["CODE_001"])
        assert len(result.rules) > 0

    def test_retrieve_top_k_limits(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        self._populate(mpm)

        result = mpm.retrieve_applicable(context="timeout validate retry", top_k=2)
        assert len(result.rules) <= 2

    def test_retrieve_excludes_low_score_rules(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="some low scoring rule text",
            failure_type="unknown",
        )
        rule = mpm.consolidate(mars)
        # Drive the score below threshold by recording many failures
        for _ in range(20):
            rule.record_usage(success=False)
        # score = (0+1)/(20+2) ~= 0.045 which is below 0.3 threshold
        assert rule.score < MetaPolicyMemory.SCORE_THRESHOLD

        result = mpm.retrieve_applicable(context="some low scoring rule text")
        assert rule not in result.rules

    def test_retrieve_prompt_injection_format(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        self._populate(mpm)

        result = mpm.retrieve_applicable(context="timeout on external HTTP")
        if result.rules:
            assert "[LEARNED RULES" in result.prompt_injection
            assert "[END LEARNED RULES]" in result.prompt_injection
            assert "WHEN:" in result.prompt_injection
            assert "THEN:" in result.prompt_injection

    def test_retrieve_task_type_in_tags(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="debugging specific rule for analysis",
            synthesis="use debugger",
            failure_type="general",
        )
        rule = mpm.consolidate(mars, mast_codes=["debugging"])
        # "debugging" is now in the rule's tags

        result = mpm.retrieve_applicable(task_type="debugging", context="analysis")
        found_ids = [r.id for r in result.rules]
        assert rule.id in found_ids

    def test_retrieve_category_keyword_boost(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="handle slow request latency",
            synthesis="add timeout parameter",
            failure_type="timeout",
        )
        mpm.consolidate(mars)

        # Context contains "slow" which is a keyword for timeout category
        result = mpm.retrieve_applicable(context="slow external service")
        assert len(result.rules) > 0


class TestMetaPolicyMemoryAdmissibility:
    """Tests for MetaPolicyMemory.check_admissibility()."""

    def test_no_blocking_returns_not_blocked(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.check_admissibility("send a normal request with proper timeout")
        assert result.is_blocked is False

    def test_default_hac_no_timeout(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.check_admissibility("call external API without timeout")
        # Matches default HAC pattern "without timeout"
        assert "Default HAC" in result.reason
        assert "timeout" in result.reason.lower()

    def test_default_hac_retry_without_backoff(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.check_admissibility("retry without backoff on failure")
        assert "Default HAC" in result.reason

    def test_default_hac_ignore_error(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.check_admissibility("ignore error and continue")
        assert "Default HAC" in result.reason
        assert "logged" in result.reason.lower()

    def test_default_hac_unbounded_loop(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.check_admissibility("use unbounded loop for polling")
        assert "Default HAC" in result.reason

    def test_default_hac_immediate_retry(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.check_admissibility("do immediate retry on transient failure")
        assert "Default HAC" in result.reason

    def test_default_hac_suppress_exception(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.check_admissibility("suppress exception to avoid crash")
        assert "Default HAC" in result.reason

    def test_default_hac_infinite_retry(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.check_admissibility("use infinite retry strategy")
        assert "Default HAC" in result.reason

    def test_learned_rule_blocks_with_high_confidence(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="external API call without proper timeout configuration",
            synthesis="always set timeout on API calls",
            failure_type="timeout",
        )
        rule = mpm.consolidate(mars)
        # Boost confidence and score to meet thresholds (score>=0.5, confidence>=0.6)
        for _ in range(5):
            rule.record_usage(success=True)

        assert rule.score >= 0.5
        assert rule.confidence >= 0.6

        # Proposed action overlaps >= 3 words with predicate
        result = mpm.check_admissibility("make external API call without proper error handling")
        assert result.is_blocked is True
        assert len(result.blocking_rules) > 0
        assert result.suggested_alternative != ""

    def test_learned_rule_does_not_block_low_confidence(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="external API call without proper timeout configuration",
        )
        rule = mpm.consolidate(mars)
        # Drive confidence below 0.6 threshold
        for _ in range(10):
            rule.record_usage(success=False)
        assert rule.confidence < 0.6

        result = mpm.check_admissibility("make external API call without proper error handling")
        # Should not be blocked by learned rule (low confidence),
        # but default HAC might still flag it -- check only blocking_rules
        assert len(result.blocking_rules) == 0

    def test_hac_case_insensitive(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.check_admissibility("Call API WITHOUT TIMEOUT set")
        assert "Default HAC" in result.reason

    def test_admissibility_suggested_alternative_from_rules(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="external API call without proper timeout configuration",
            synthesis="always set timeout=10s with backoff",
        )
        rule = mpm.consolidate(mars)
        for _ in range(5):
            rule.record_usage(success=True)

        result = mpm.check_admissibility("make external API call without proper error handling")
        if result.is_blocked:
            assert "timeout" in result.suggested_alternative.lower()


class TestMetaPolicyMemoryRecordOutcome:
    """Tests for MetaPolicyMemory.record_outcome()."""

    def test_record_success(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult()
        rule = mpm.consolidate(mars)

        result = mpm.record_outcome(rule.id, success=True)
        assert result is True
        assert rule.usage_count == 1
        assert rule.success_count == 1

    def test_record_failure(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult()
        rule = mpm.consolidate(mars)

        result = mpm.record_outcome(rule.id, success=False)
        assert result is True
        assert rule.usage_count == 1
        assert rule.success_count == 0

    def test_record_unknown_rule_returns_false(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.record_outcome("nonexistent-id", success=True)
        assert result is False

    def test_record_outcome_updates_score(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult()
        rule = mpm.consolidate(mars)
        initial_score = rule.score

        mpm.record_outcome(rule.id, success=True)
        assert rule.score > initial_score  # (1+1)/(1+2) = 0.667 > 0.5

    def test_record_outcome_persists(self, tmp_path):
        storage = tmp_path / "rules.jsonl"
        mpm = MetaPolicyMemory(storage_path=storage)
        mars = MockTriplePathwayResult()
        rule = mpm.consolidate(mars)
        mpm.record_outcome(rule.id, success=True)

        # Reload and verify
        mpm2 = MetaPolicyMemory(storage_path=storage)
        reloaded = mpm2._rules.get(rule.id)
        assert reloaded is not None
        assert reloaded.usage_count == 1
        assert reloaded.success_count == 1


class TestMetaPolicyMemoryGetStats:
    """Tests for MetaPolicyMemory.get_stats()."""

    def test_stats_empty(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        stats = mpm.get_stats()
        assert stats.total_rules == 0
        assert stats.active_rules == 0
        assert stats.categories == {}
        assert stats.avg_score == 0.0
        assert stats.total_activations == 0

    def test_stats_with_rules(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")

        mars1 = MockTriplePathwayResult(
            principle="timeout rule one",
            failure_type="timeout",
        )
        mars2 = MockTriplePathwayResult(
            principle="validate input rule",
            failure_type="validation",
        )
        rule1 = mpm.consolidate(mars1)
        rule2 = mpm.consolidate(mars2)

        # Record some usage
        rule1.record_usage(success=True)
        rule1.record_usage(success=True)
        rule2.record_usage(success=False)

        stats = mpm.get_stats()
        assert stats.total_rules == 2
        assert stats.active_rules == 2  # Both above threshold initially
        assert stats.total_activations == 3
        assert stats.avg_score > 0.0
        assert len(stats.categories) >= 1

    def test_stats_active_count_excludes_low_score(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(principle="low score rule that fails often")
        rule = mpm.consolidate(mars)

        # Drive score below threshold
        for _ in range(20):
            rule.record_usage(success=False)

        stats = mpm.get_stats()
        assert stats.total_rules == 1
        assert stats.active_rules == 0

    def test_stats_returns_mpmstats_instance(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        stats = mpm.get_stats()
        assert isinstance(stats, MPMStats)


class TestMetaPolicyMemoryPersistence:
    """Tests for MetaPolicyMemory save/reload from file."""

    def test_save_and_reload(self, tmp_path):
        storage = tmp_path / "rules.jsonl"

        mpm1 = MetaPolicyMemory(storage_path=storage)
        mars1 = MockTriplePathwayResult(
            principle="rule one for persistence test",
            synthesis="action one",
            failure_type="timeout",
        )
        mars2 = MockTriplePathwayResult(
            principle="rule two for persistence test",
            synthesis="action two",
            failure_type="validation",
        )
        rule1 = mpm1.consolidate(mars1, mast_codes=["A001"])
        rule2 = mpm1.consolidate(mars2, mast_codes=["B002"])
        mpm1.record_outcome(rule1.id, success=True)

        # Reload
        mpm2 = MetaPolicyMemory(storage_path=storage)
        assert mpm2.rule_count == 2

        reloaded1 = mpm2._rules.get(rule1.id)
        reloaded2 = mpm2._rules.get(rule2.id)

        assert reloaded1 is not None
        assert reloaded1.predicate == "rule one for persistence test"
        assert reloaded1.usage_count == 1
        assert reloaded1.success_count == 1
        assert reloaded1.mast_codes == ["A001"]

        assert reloaded2 is not None
        assert reloaded2.predicate == "rule two for persistence test"
        assert reloaded2.mast_codes == ["B002"]

    def test_load_nonexistent_file(self, tmp_path):
        storage = tmp_path / "nonexistent" / "rules.jsonl"
        mpm = MetaPolicyMemory(storage_path=storage)
        assert mpm.rule_count == 0

    def test_load_empty_file(self, tmp_path):
        storage = tmp_path / "rules.jsonl"
        storage.write_text("")
        mpm = MetaPolicyMemory(storage_path=storage)
        assert mpm.rule_count == 0

    def test_load_file_with_blank_lines(self, tmp_path):
        storage = tmp_path / "rules.jsonl"
        mars_data = {
            "id": "test-id-1",
            "predicate": "p",
            "action": "a",
            "category": "general",
            "source_task": "t",
            "failure_type": "f",
            "mast_codes": [],
            "tags": [],
            "created_at": time.time(),
            "usage_count": 0,
            "success_count": 0,
            "last_used": None,
            "confidence": 0.5,
        }
        storage.write_text(f"\n{json.dumps(mars_data)}\n\n")
        mpm = MetaPolicyMemory(storage_path=storage)
        assert mpm.rule_count == 1

    def test_persistence_creates_parent_dirs(self, tmp_path):
        storage = tmp_path / "deep" / "nested" / "dir" / "rules.jsonl"
        mpm = MetaPolicyMemory(storage_path=storage)
        mars = MockTriplePathwayResult()
        mpm.consolidate(mars)
        assert storage.exists()

    def test_load_corrupted_file_does_not_crash(self, tmp_path):
        storage = tmp_path / "rules.jsonl"
        storage.write_text("not valid json\n")
        # Should not raise; logs a warning instead
        mpm = MetaPolicyMemory(storage_path=storage)
        assert mpm.rule_count == 0


class TestMetaPolicyMemoryRuleCap:
    """Tests for rule cap enforcement."""

    def test_cap_enforcement_removes_lowest_scoring(self, tmp_path):
        storage = tmp_path / "rules.jsonl"
        mpm = MetaPolicyMemory(storage_path=storage)
        original_max = MetaPolicyMemory.MAX_RULES

        try:
            # Set a low cap for testing
            MetaPolicyMemory.MAX_RULES = 5

            # Add 7 rules (all with unique predicates)
            rule_ids = []
            for i in range(7):
                mars = MockTriplePathwayResult(
                    principle=f"unique rule number {i} for cap test with padding text",
                )
                rule = mpm.consolidate(mars, source_task=f"task-{i}")
                rule_ids.append(rule.id)

            assert mpm.rule_count <= 5

        finally:
            MetaPolicyMemory.MAX_RULES = original_max

    def test_cap_keeps_higher_scoring_rules(self, tmp_path):
        storage = tmp_path / "rules.jsonl"
        mpm = MetaPolicyMemory(storage_path=storage)
        original_max = MetaPolicyMemory.MAX_RULES

        try:
            MetaPolicyMemory.MAX_RULES = 3

            # Create a high-scoring rule first
            mars_high = MockTriplePathwayResult(
                principle="high scoring rule that should survive cap enforcement",
            )
            high_rule = mpm.consolidate(mars_high)
            # Boost its score
            for _ in range(10):
                high_rule.record_usage(success=True)

            # Create lower-scoring rules to exceed cap
            for i in range(4):
                mars_low = MockTriplePathwayResult(
                    principle=f"low scoring filler rule number {i} created for cap test",
                )
                mpm.consolidate(mars_low)

            # High-scoring rule should still be present
            assert mpm.rule_count <= 3
            assert high_rule.id in mpm._rules

        finally:
            MetaPolicyMemory.MAX_RULES = original_max


class TestMetaPolicyMemoryRuleCount:
    """Tests for MetaPolicyMemory.rule_count property."""

    def test_rule_count_initially_zero(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        assert mpm.rule_count == 0

    def test_rule_count_increments(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(principle="rule A for counting test")
        mpm.consolidate(mars)
        assert mpm.rule_count == 1

        mars2 = MockTriplePathwayResult(principle="rule B for counting test")
        mpm.consolidate(mars2)
        assert mpm.rule_count == 2


class TestMetaPolicyMemoryCategorization:
    """Tests for internal _categorize method."""

    def test_categorize_timeout_keywords(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        cat = mpm._categorize("request hangs unresponsive", "set deadline", "timeout")
        assert cat == "timeout"

    def test_categorize_validation_keywords(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        cat = mpm._categorize("check schema format", "validate assertion", "type_error")
        assert cat == "validation"

    def test_categorize_communication_keywords(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        cat = mpm._categorize("parse json response", "fix message protocol", "comm_err")
        assert cat == "communication"

    def test_categorize_resource_keywords(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        cat = mpm._categorize("memory limit exceeded", "reduce token budget", "oom")
        assert cat == "resource"

    def test_categorize_retry_keywords(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        cat = mpm._categorize("retry with backoff", "fallback recovery", "retry_fail")
        assert cat == "retry"

    def test_categorize_safety_keywords(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        cat = mpm._categorize("security injection risk", "check permission access", "auth")
        assert cat == "safety"

    def test_categorize_general_fallback(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        cat = mpm._categorize("obscure issue xyz", "handle it somehow", "unknown")
        assert cat == "general"


class TestMetaPolicyMemoryFormatForPrompt:
    """Tests for internal _format_for_prompt method."""

    def test_format_empty_list(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        text = mpm._format_for_prompt([])
        assert text == ""

    def test_format_with_rules(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        rule = PolicyRule(
            id="r1",
            predicate="check input type before parsing",
            action="validate with isinstance",
            category="validation",
            source_task="task",
            failure_type="type_error",
            mast_codes=[],
            tags=[],
            created_at=time.time(),
        )
        text = mpm._format_for_prompt([rule])
        assert "[LEARNED RULES" in text
        assert "[END LEARNED RULES]" in text
        assert "WHEN: check input type" in text
        assert "THEN: validate with isinstance" in text
        assert "validation" in text
        assert "reliability:" in text


# =============================================================================
# Singleton Tests
# =============================================================================


class TestSingleton:
    """Tests for get_meta_policy_memory and reset_meta_policy_memory."""

    def test_get_returns_instance(self):
        import core.intelligence.reasoning.meta_policy_memory as mpm_mod

        mpm_mod._instance = None

        instance = get_meta_policy_memory()
        assert instance is not None
        assert isinstance(instance, MetaPolicyMemory)

        # Cleanup
        mpm_mod._instance = None

    def test_get_returns_same_instance(self):
        import core.intelligence.reasoning.meta_policy_memory as mpm_mod

        mpm_mod._instance = None

        inst1 = get_meta_policy_memory()
        inst2 = get_meta_policy_memory()
        assert inst1 is inst2

        # Cleanup
        mpm_mod._instance = None

    def test_reset_clears_instance(self):
        import core.intelligence.reasoning.meta_policy_memory as mpm_mod

        mpm_mod._instance = None

        inst1 = get_meta_policy_memory()
        reset_meta_policy_memory()
        assert mpm_mod._instance is None

        inst2 = get_meta_policy_memory()
        assert inst2 is not inst1

        # Cleanup
        mpm_mod._instance = None

    def test_reset_then_get_creates_new(self):
        import core.intelligence.reasoning.meta_policy_memory as mpm_mod

        mpm_mod._instance = None

        get_meta_policy_memory()
        reset_meta_policy_memory()
        new_inst = get_meta_policy_memory()
        assert new_inst is not None

        # Cleanup
        mpm_mod._instance = None


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_mars_result_without_attributes(self, tmp_path):
        """consolidate handles objects missing expected attributes."""
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")

        class MinimalResult:
            pass

        result = MinimalResult()
        rule = mpm.consolidate(result)
        # Falls back to str(result) for predicate, "" for procedure/synthesis
        assert rule.predicate is not None
        assert rule.action == ""
        assert rule.failure_type == "unknown"

    def test_consolidate_with_empty_strings(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult(
            principle="",
            procedure="",
            synthesis="",
            failure_type="",
        )
        rule = mpm.consolidate(mars)
        assert rule.predicate == ""
        assert rule.action == ""

    def test_retrieve_with_no_context_no_tags(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        mars = MockTriplePathwayResult()
        mpm.consolidate(mars)

        # Should still return rules based on Bayesian score alone
        result = mpm.retrieve_applicable()
        # With no context/tags, relevance = score*0.3 = 0.5*0.3 = 0.15 > 0.1
        assert len(result.rules) >= 1

    def test_check_admissibility_empty_string(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        result = mpm.check_admissibility("")
        assert result.is_blocked is False

    def test_multiple_consolidate_and_retrieve_cycle(self, tmp_path):
        """Full cycle: consolidate, retrieve, record, verify stats."""
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")

        mars = MockTriplePathwayResult(
            principle="always check network connectivity before API call",
            synthesis="ping health endpoint first",
            failure_type="communication",
        )
        rule = mpm.consolidate(mars, mast_codes=["NET_001"])

        result = mpm.retrieve_applicable(context="network API call connectivity")
        assert len(result.rules) > 0

        mpm.record_outcome(rule.id, success=True)
        mpm.record_outcome(rule.id, success=True)

        stats = mpm.get_stats()
        assert stats.total_rules == 1
        assert stats.total_activations == 2

    def test_find_duplicate_prefix_match(self, tmp_path):
        mpm = MetaPolicyMemory(storage_path=tmp_path / "rules.jsonl")
        # Build a prefix that is exactly 80+ chars so both share the same first 80
        prefix_80 = "always validate input data before processing it in the pipeline and ensure safe"  # 80 chars
        mars1 = MockTriplePathwayResult(
            principle=prefix_80 + " handling of edge cases",
        )
        mars2 = MockTriplePathwayResult(
            # Same first 80 chars but different ending
            principle=prefix_80 + " usage of error boundaries",
        )
        rule1 = mpm.consolidate(mars1)
        rule2 = mpm.consolidate(mars2)

        # Should be treated as duplicate (same 80-char prefix)
        assert rule1.id == rule2.id
        assert mpm.rule_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
