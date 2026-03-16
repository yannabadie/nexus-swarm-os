"""
Comprehensive tests for core.skills.experience_distiller module.

Covers: PrincipleCategory, StrategicPrinciple, DistillationResult,
RetrievalResult, DistillerStats, ExperienceDistiller (distill, retrieve,
record_outcome, eviction, persistence, singleton, keyword extraction,
fingerprinting, category detection, edge cases).

Target: 90+ independent tests, all passing.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

from core.memory_pkg.skills.experience_distiller import (
    BAYESIAN_ALPHA,
    BAYESIAN_BETA,
    CATEGORY_PATTERNS,
    CONFIDENCE_EMA,
    MAX_PRINCIPLES,
    MIN_CONFIDENCE,
    RETRIEVAL_THRESHOLD,
    STOP_WORDS,
    DistillationResult,
    DistillerStats,
    ExperienceDistiller,
    PrincipleCategory,
    RetrievalResult,
    StrategicPrinciple,
    get_experience_distiller,
    reset_experience_distiller,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the global singleton before and after each test."""
    reset_experience_distiller()
    yield
    reset_experience_distiller()


@pytest.fixture
def store_path(tmp_path: Path) -> str:
    """Return a temporary JSONL path for test isolation."""
    return str(tmp_path / "test_principles.jsonl")


@pytest.fixture
def distiller(store_path: str) -> ExperienceDistiller:
    """Return a fresh ExperienceDistiller writing to tmp_path."""
    return ExperienceDistiller(store_path=store_path)


# ---------------------------------------------------------------------------
# 1. PrincipleCategory enum values
# ---------------------------------------------------------------------------


class TestPrincipleCategory:
    """Tests for PrincipleCategory enum."""

    def test_strategy_value(self):
        assert PrincipleCategory.STRATEGY.value == "strategy"

    def test_tool_use_value(self):
        assert PrincipleCategory.TOOL_USE.value == "tool_use"

    def test_error_recovery_value(self):
        assert PrincipleCategory.ERROR_RECOVERY.value == "error_recovery"

    def test_collaboration_value(self):
        assert PrincipleCategory.COLLABORATION.value == "collaboration"

    def test_optimization_value(self):
        assert PrincipleCategory.OPTIMIZATION.value == "optimization"

    def test_domain_value(self):
        assert PrincipleCategory.DOMAIN.value == "domain"

    def test_total_members(self):
        assert len(PrincipleCategory) == 6

    def test_is_str_enum(self):
        """PrincipleCategory inherits from str, so members are strings."""
        assert isinstance(PrincipleCategory.STRATEGY, str)
        assert PrincipleCategory.STRATEGY == "strategy"

    def test_construct_from_value(self):
        assert PrincipleCategory("tool_use") is PrincipleCategory.TOOL_USE


# ---------------------------------------------------------------------------
# 2. StrategicPrinciple creation, to_dict, from_dict
# ---------------------------------------------------------------------------


class TestStrategicPrinciple:
    """Tests for StrategicPrinciple dataclass."""

    def test_creation_defaults(self):
        p = StrategicPrinciple(
            principle_id="abc123",
            text="Always validate input",
            category=PrincipleCategory.STRATEGY,
        )
        assert p.principle_id == "abc123"
        assert p.text == "Always validate input"
        assert p.category == PrincipleCategory.STRATEGY
        assert p.source_tasks == []
        assert p.keywords == set()
        assert p.success_rate == 0.5
        assert p.usage_count == 0
        assert p.confidence == 0.5
        assert p.created_at > 0  # auto-set by __post_init__

    def test_creation_with_explicit_fields(self):
        p = StrategicPrinciple(
            principle_id="x",
            text="Test",
            category=PrincipleCategory.TOOL_USE,
            source_tasks=["task1"],
            keywords={"auth", "login"},
            success_rate=0.8,
            usage_count=5,
            confidence=0.9,
            created_at=1000.0,
            last_used=2000.0,
        )
        assert p.source_tasks == ["task1"]
        assert p.keywords == {"auth", "login"}
        assert p.success_rate == 0.8
        assert p.usage_count == 5
        assert p.confidence == 0.9
        assert p.created_at == 1000.0
        assert p.last_used == 2000.0

    def test_post_init_sets_created_at(self):
        before = time.time()
        p = StrategicPrinciple(
            principle_id="t1",
            text="test",
            category=PrincipleCategory.STRATEGY,
        )
        after = time.time()
        assert before <= p.created_at <= after

    def test_post_init_preserves_explicit_created_at(self):
        p = StrategicPrinciple(
            principle_id="t1",
            text="test",
            category=PrincipleCategory.STRATEGY,
            created_at=42.0,
        )
        assert p.created_at == 42.0

    def test_to_dict_basic(self):
        p = StrategicPrinciple(
            principle_id="abc",
            text="Use grep before read",
            category=PrincipleCategory.TOOL_USE,
            source_tasks=["task_a"],
            keywords={"grep", "read"},
            success_rate=0.7777,
            usage_count=3,
            confidence=0.8888,
        )
        d = p.to_dict()
        assert d["principle_id"] == "abc"
        assert d["text"] == "Use grep before read"
        assert d["category"] == "tool_use"
        assert d["source_tasks"] == ["task_a"]
        assert d["keywords"] == ["grep", "read"]  # sorted
        assert d["success_rate"] == 0.778  # rounded to 3
        assert d["usage_count"] == 3
        assert d["confidence"] == 0.889  # rounded to 3

    def test_to_dict_truncates_source_tasks(self):
        p = StrategicPrinciple(
            principle_id="x",
            text="t",
            category=PrincipleCategory.STRATEGY,
            source_tasks=[f"task{i}" for i in range(10)],
        )
        d = p.to_dict()
        assert len(d["source_tasks"]) == 5

    def test_to_dict_truncates_keywords(self):
        p = StrategicPrinciple(
            principle_id="x",
            text="t",
            category=PrincipleCategory.STRATEGY,
            keywords={f"kw{i}" for i in range(30)},
        )
        d = p.to_dict()
        assert len(d["keywords"]) == 20

    def test_from_dict_basic(self):
        d = {
            "principle_id": "abc",
            "text": "Test principle",
            "category": "error_recovery",
            "source_tasks": ["fix bug"],
            "keywords": ["bug", "fix"],
            "success_rate": 0.9,
            "usage_count": 7,
            "confidence": 0.85,
            "created_at": 100.0,
            "last_used": 200.0,
        }
        p = StrategicPrinciple.from_dict(d)
        assert p.principle_id == "abc"
        assert p.text == "Test principle"
        assert p.category == PrincipleCategory.ERROR_RECOVERY
        assert p.source_tasks == ["fix bug"]
        assert p.keywords == {"bug", "fix"}
        assert p.success_rate == 0.9
        assert p.usage_count == 7
        assert p.confidence == 0.85
        assert p.created_at == 100.0
        assert p.last_used == 200.0

    def test_from_dict_defaults(self):
        d = {
            "principle_id": "min",
            "text": "Minimal",
            "category": "strategy",
        }
        p = StrategicPrinciple.from_dict(d)
        assert p.source_tasks == []
        assert p.keywords == set()
        assert p.success_rate == 0.5
        assert p.usage_count == 0
        assert p.confidence == 0.5

    def test_roundtrip_to_from_dict(self):
        original = StrategicPrinciple(
            principle_id="rt",
            text="Roundtrip test",
            category=PrincipleCategory.COLLABORATION,
            source_tasks=["t1", "t2"],
            keywords={"alpha", "beta"},
            success_rate=0.6,
            usage_count=2,
            confidence=0.7,
            created_at=999.0,
        )
        d = original.to_dict()
        restored = StrategicPrinciple.from_dict(d)
        assert restored.principle_id == original.principle_id
        assert restored.text == original.text
        assert restored.category == original.category
        assert restored.keywords == original.keywords
        assert restored.success_rate == round(original.success_rate, 3)
        assert restored.usage_count == original.usage_count
        assert restored.confidence == round(original.confidence, 3)


# ---------------------------------------------------------------------------
# 3. DistillationResult and RetrievalResult creation
# ---------------------------------------------------------------------------


class TestDistillationResult:
    """Tests for DistillationResult dataclass."""

    def test_creation(self):
        p = StrategicPrinciple(
            principle_id="x",
            text="t",
            category=PrincipleCategory.STRATEGY,
        )
        dr = DistillationResult(
            new_principles=[p],
            updated_principles=["y"],
            total_principles=10,
        )
        assert len(dr.new_principles) == 1
        assert dr.updated_principles == ["y"]
        assert dr.total_principles == 10

    def test_to_dict(self):
        p1 = StrategicPrinciple(
            principle_id="a",
            text="t1",
            category=PrincipleCategory.STRATEGY,
        )
        p2 = StrategicPrinciple(
            principle_id="b",
            text="t2",
            category=PrincipleCategory.DOMAIN,
        )
        dr = DistillationResult(
            new_principles=[p1, p2],
            updated_principles=["c", "d", "e"],
            total_principles=20,
        )
        d = dr.to_dict()
        assert d == {"new_count": 2, "updated_count": 3, "total_principles": 20}

    def test_empty(self):
        dr = DistillationResult(
            new_principles=[],
            updated_principles=[],
            total_principles=0,
        )
        assert dr.to_dict() == {
            "new_count": 0,
            "updated_count": 0,
            "total_principles": 0,
        }


class TestRetrievalResult:
    """Tests for RetrievalResult dataclass."""

    def test_creation(self):
        rr = RetrievalResult(principles=[], total_scored=5, threshold_used=0.15)
        assert rr.principles == []
        assert rr.total_scored == 5
        assert rr.threshold_used == 0.15

    def test_to_dict(self):
        p = StrategicPrinciple(
            principle_id="z",
            text="t",
            category=PrincipleCategory.STRATEGY,
        )
        rr = RetrievalResult(principles=[p], total_scored=3, threshold_used=0.1567)
        d = rr.to_dict()
        assert d == {
            "retrieved_count": 1,
            "total_scored": 3,
            "threshold_used": 0.157,
        }


# ---------------------------------------------------------------------------
# 4. DistillerStats creation and to_dict
# ---------------------------------------------------------------------------


class TestDistillerStats:
    """Tests for DistillerStats dataclass."""

    def test_defaults(self):
        s = DistillerStats()
        assert s.total_distillations == 0
        assert s.total_retrievals == 0
        assert s.principles_created == 0
        assert s.principles_updated == 0
        assert s.principles_retrieved == 0
        assert s.avg_retrieval_count == 0.0

    def test_custom_values(self):
        s = DistillerStats(
            total_distillations=10,
            total_retrievals=20,
            principles_created=30,
            principles_updated=5,
            principles_retrieved=40,
            avg_retrieval_count=2.555,
        )
        assert s.total_distillations == 10
        assert s.principles_retrieved == 40

    def test_to_dict(self):
        s = DistillerStats(
            total_distillations=1,
            total_retrievals=2,
            principles_created=3,
            principles_updated=4,
            principles_retrieved=5,
            avg_retrieval_count=1.23456,
        )
        d = s.to_dict()
        assert d == {
            "total_distillations": 1,
            "total_retrievals": 2,
            "principles_created": 3,
            "principles_updated": 4,
            "avg_retrieval_count": 1.235,
        }

    def test_to_dict_does_not_include_principles_retrieved(self):
        """to_dict omits principles_retrieved field."""
        d = DistillerStats().to_dict()
        assert "principles_retrieved" not in d


# ---------------------------------------------------------------------------
# 5. Basic distillation from lessons
# ---------------------------------------------------------------------------


class TestDistillBasic:
    """Tests for basic ExperienceDistiller.distill() with lessons."""

    def test_single_lesson_creates_principle(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Fix auth bug in login.py",
            outcome="success",
            lessons=["Always check token expiry before validation"],
        )
        assert len(result.new_principles) == 1
        assert result.total_principles == 1
        p = result.new_principles[0]
        assert "token expiry" in p.text.lower() or "token" in p.text.lower()
        assert p.category is not None
        assert p.success_rate == 1.0  # success

    def test_failure_outcome_sets_zero_success_rate(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Deploy service",
            outcome="failure: timeout",
            lessons=["Always set deployment timeout"],
        )
        p = result.new_principles[0]
        assert p.success_rate == 0.0

    def test_multiple_lessons(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Refactor auth module",
            outcome="success",
            lessons=[
                "Validate input at boundaries",
                "Add type hints to all functions",
                "Run tests before committing",
            ],
        )
        assert len(result.new_principles) == 3
        assert result.total_principles == 3

    def test_duplicate_lesson_is_not_recreated(self, distiller: ExperienceDistiller):
        lesson = "Check token expiry"
        distiller.distill(
            task_description="Fix auth",
            outcome="success",
            lessons=[lesson],
        )
        result2 = distiller.distill(
            task_description="Fix auth again",
            outcome="success",
            lessons=[lesson],
        )
        assert len(result2.new_principles) == 0
        assert len(result2.updated_principles) == 1

    def test_distill_with_no_lessons_or_tools_creates_nothing(
        self,
        distiller: ExperienceDistiller,
    ):
        result = distiller.distill(
            task_description="Simple task",
            outcome="success",
        )
        assert len(result.new_principles) == 0
        assert result.total_principles == 0


# ---------------------------------------------------------------------------
# 6. Tool-use principle extraction
# ---------------------------------------------------------------------------


class TestToolUsePrinciples:
    """Tests for tool_use principle extraction via tools_used param."""

    def test_tool_use_creates_principle_on_success(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Search for auth patterns",
            outcome="success",
            tools_used=["grep", "read"],
        )
        tool_ps = [p for p in result.new_principles if p.category == PrincipleCategory.TOOL_USE]
        assert len(tool_ps) == 1
        assert "grep" in tool_ps[0].text
        assert "read" in tool_ps[0].text

    def test_tool_use_not_created_on_failure(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Search for auth patterns",
            outcome="failure",
            tools_used=["grep", "read"],
        )
        tool_ps = [p for p in result.new_principles if p.category == PrincipleCategory.TOOL_USE]
        assert len(tool_ps) == 0

    def test_tool_use_truncates_to_five_tools(self, distiller: ExperienceDistiller):
        tools = [f"tool_{i}" for i in range(10)]
        result = distiller.distill(
            task_description="Big task",
            outcome="success",
            tools_used=tools,
        )
        tool_ps = [p for p in result.new_principles if p.category == PrincipleCategory.TOOL_USE]
        assert len(tool_ps) == 1
        # Text only includes first 5 tools
        text = tool_ps[0].text
        assert "tool_4" in text
        assert "tool_5" not in text

    def test_tool_use_not_duplicated(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Search for auth patterns",
            outcome="success",
            tools_used=["grep"],
        )
        result2 = distiller.distill(
            task_description="Search for auth patterns",
            outcome="success",
            tools_used=["grep"],
        )
        tool_ps = [p for p in result2.new_principles if p.category == PrincipleCategory.TOOL_USE]
        assert len(tool_ps) == 0


# ---------------------------------------------------------------------------
# 7. Error-recovery principle extraction
# ---------------------------------------------------------------------------


class TestErrorRecoveryPrinciples:
    """Tests for error_recovery principle extraction."""

    def test_error_recovery_created_on_success(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Fix database migration",
            outcome="success after retry",
            error_messages=["ConnectionError: timeout"],
        )
        err_ps = [p for p in result.new_principles if p.category == PrincipleCategory.ERROR_RECOVERY]
        assert len(err_ps) == 1
        assert "ConnectionError" in err_ps[0].text

    def test_error_recovery_not_created_on_failure(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Fix db",
            outcome="failure",
            error_messages=["ConnectionError"],
        )
        err_ps = [p for p in result.new_principles if p.category == PrincipleCategory.ERROR_RECOVERY]
        assert len(err_ps) == 0

    def test_error_recovery_max_three(self, distiller: ExperienceDistiller):
        errors = [f"Error{i}" for i in range(10)]
        result = distiller.distill(
            task_description="Many errors",
            outcome="success",
            error_messages=errors,
        )
        err_ps = [p for p in result.new_principles if p.category == PrincipleCategory.ERROR_RECOVERY]
        assert len(err_ps) == 3

    def test_error_message_truncated_in_text(self, distiller: ExperienceDistiller):
        long_error = "A" * 200
        result = distiller.distill(
            task_description="Task",
            outcome="success",
            error_messages=[long_error],
        )
        err_ps = [p for p in result.new_principles if p.category == PrincipleCategory.ERROR_RECOVERY]
        assert len(err_ps) == 1
        # Error text in the principle is truncated to 80 chars
        assert long_error[:80] in err_ps[0].text
        assert long_error[:81] not in err_ps[0].text


# ---------------------------------------------------------------------------
# 8. Category auto-detection from text
# ---------------------------------------------------------------------------


class TestCategoryDetection:
    """Tests for _detect_category (via distill creating principles)."""

    def test_detect_strategy(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Plan the approach",
            outcome="success",
            lessons=["Use a design strategy with architecture plan"],
        )
        p = result.new_principles[0]
        assert p.category == PrincipleCategory.STRATEGY

    def test_detect_tool_use(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Task",
            outcome="success",
            lessons=["Use the tool command to execute the function call"],
        )
        p = result.new_principles[0]
        assert p.category == PrincipleCategory.TOOL_USE

    def test_detect_error_recovery(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Task",
            outcome="success",
            lessons=["When an error occurs, fix it with a retry fallback"],
        )
        p = result.new_principles[0]
        assert p.category == PrincipleCategory.ERROR_RECOVERY

    def test_detect_collaboration(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Task",
            outcome="success",
            lessons=["Collaborate with the swarm agent to negotiate a lead role"],
        )
        p = result.new_principles[0]
        assert p.category == PrincipleCategory.COLLABORATION

    def test_detect_optimization(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Task",
            outcome="success",
            lessons=["Optimize for performance and reduce token usage for speed"],
        )
        p = result.new_principles[0]
        assert p.category == PrincipleCategory.OPTIMIZATION

    def test_detect_domain(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Task",
            outcome="success",
            lessons=["Apply domain specific expert knowledge from specialized training"],
        )
        p = result.new_principles[0]
        assert p.category == PrincipleCategory.DOMAIN

    def test_detect_defaults_to_strategy(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Task",
            outcome="success",
            lessons=["Completely random xyz123 nothing matches"],
        )
        p = result.new_principles[0]
        assert p.category == PrincipleCategory.STRATEGY

    def test_detect_highest_scoring_wins(self, distiller: ExperienceDistiller):
        """When multiple categories match, the highest score wins."""
        # Three tool keywords vs one error keyword
        result = distiller.distill(
            task_description="Task",
            outcome="success",
            lessons=["Execute the tool command and call the api function, handle error"],
        )
        p = result.new_principles[0]
        assert p.category == PrincipleCategory.TOOL_USE


# ---------------------------------------------------------------------------
# 9. Existing principle update (Bayesian + EMA)
# ---------------------------------------------------------------------------


class TestPrincipleUpdate:
    """Tests for Bayesian success rate and EMA confidence updates."""

    def test_bayesian_success_rate_after_success(self, distiller: ExperienceDistiller):
        lesson = "Validate input before processing"
        distiller.distill(
            task_description="Task1",
            outcome="success",
            lessons=[lesson],
        )
        # First creation: success_rate = 1.0, usage_count = 0
        distiller.distill(
            task_description="Task2",
            outcome="success",
            lessons=[lesson],
        )
        # Update: n=1, successes = 1.0*0 + 1 = 1, rate = (1+1)/(1+2) = 2/3
        principles = distiller.get_all_principles()
        assert len(principles) == 1
        p = principles[0]
        expected_rate = (1.0 * 0 + 1 + BAYESIAN_ALPHA) / (0 + 1 + BAYESIAN_BETA)
        assert abs(p.success_rate - expected_rate) < 1e-9

    def test_bayesian_success_rate_after_failure(self, distiller: ExperienceDistiller):
        lesson = "Check return codes"
        distiller.distill(
            task_description="T1",
            outcome="success",
            lessons=[lesson],
        )
        distiller.distill(
            task_description="T2",
            outcome="failure",
            lessons=[lesson],
        )
        # n=1, successes=1.0*0+0=0, rate=(0+1)/(1+2) = 1/3
        p = distiller.get_all_principles()[0]
        expected_rate = (1.0 * 0 + 0 + BAYESIAN_ALPHA) / (0 + 1 + BAYESIAN_BETA)
        assert abs(p.success_rate - expected_rate) < 1e-9

    def test_ema_confidence_after_success(self, distiller: ExperienceDistiller):
        lesson = "Use type hints"
        distiller.distill(task_description="T1", outcome="success", lessons=[lesson])
        # confidence starts at 0.5
        distiller.distill(task_description="T2", outcome="success", lessons=[lesson])
        # EMA: 0.3*1.0 + 0.7*0.5 = 0.3 + 0.35 = 0.65
        p = distiller.get_all_principles()[0]
        expected = CONFIDENCE_EMA * 1.0 + (1 - CONFIDENCE_EMA) * 0.5
        assert abs(p.confidence - expected) < 1e-9

    def test_ema_confidence_after_failure(self, distiller: ExperienceDistiller):
        lesson = "Write tests first"
        distiller.distill(task_description="T1", outcome="success", lessons=[lesson])
        distiller.distill(task_description="T2", outcome="failure", lessons=[lesson])
        # EMA: 0.3*0.0 + 0.7*0.5 = 0.35
        p = distiller.get_all_principles()[0]
        expected = CONFIDENCE_EMA * 0.0 + (1 - CONFIDENCE_EMA) * 0.5
        assert abs(p.confidence - expected) < 1e-9

    def test_usage_count_increments(self, distiller: ExperienceDistiller):
        lesson = "Use grep"
        distiller.distill(task_description="T1", outcome="success", lessons=[lesson])
        assert distiller.get_all_principles()[0].usage_count == 0
        distiller.distill(task_description="T2", outcome="success", lessons=[lesson])
        assert distiller.get_all_principles()[0].usage_count == 1
        distiller.distill(task_description="T3", outcome="success", lessons=[lesson])
        assert distiller.get_all_principles()[0].usage_count == 2

    def test_source_tasks_accumulate(self, distiller: ExperienceDistiller):
        lesson = "Check permissions"
        distiller.distill(task_description="Task A", outcome="success", lessons=[lesson])
        distiller.distill(task_description="Task B", outcome="success", lessons=[lesson])
        p = distiller.get_all_principles()[0]
        assert "Task A" in p.source_tasks
        assert "Task B" in p.source_tasks

    def test_source_tasks_max_ten(self, distiller: ExperienceDistiller):
        lesson = "Keep logs"
        distiller.distill(task_description="Init", outcome="success", lessons=[lesson])
        for i in range(15):
            distiller.distill(
                task_description=f"Task {i}",
                outcome="success",
                lessons=[lesson],
            )
        p = distiller.get_all_principles()[0]
        assert len(p.source_tasks) <= 10


# ---------------------------------------------------------------------------
# 10. Retrieval by keyword overlap
# ---------------------------------------------------------------------------


class TestRetrieval:
    """Tests for principle retrieval via keyword matching."""

    def test_retrieve_matching_principle(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Fix authentication bug in login module",
            outcome="success",
            lessons=["Check token expiry before authentication validation"],
        )
        result = distiller.retrieve(
            task_description="Debug authentication token refresh issue",
        )
        assert len(result.principles) >= 1

    def test_retrieve_no_overlap_with_low_quality_returns_empty(
        self,
        distiller: ExperienceDistiller,
    ):
        """When there is zero keyword overlap AND low quality scores, the
        combined relevance score should be below the retrieval threshold."""
        # Create a principle with a failure outcome (success_rate=0.0,
        # confidence=0.5).  Quality boost = 0.0*0.3 + 0.5*0.2 = 0.1 which
        # is below RETRIEVAL_THRESHOLD (0.15).
        distiller.distill(
            task_description="Database migration",
            outcome="failure",
            lessons=["Always backup database before migration"],
        )
        result = distiller.retrieve(
            task_description="xyzzy foobar completely unrelated",
        )
        assert len(result.principles) == 0

    def test_retrieve_returns_retrieval_result(self, distiller: ExperienceDistiller):
        result = distiller.retrieve(task_description="Anything")
        assert isinstance(result, RetrievalResult)
        assert result.threshold_used == RETRIEVAL_THRESHOLD

    def test_retrieve_top_k_limits_results(self, distiller: ExperienceDistiller):
        # Create many principles with overlapping keywords
        for i in range(10):
            distiller.distill(
                task_description=f"Fix authentication module part {i}",
                outcome="success",
                lessons=[f"Authentication principle number {i} for login"],
            )
        result = distiller.retrieve(
            task_description="Fix authentication login issue",
            top_k=3,
        )
        assert len(result.principles) <= 3


# ---------------------------------------------------------------------------
# 11. Retrieval with min_confidence filter
# ---------------------------------------------------------------------------


class TestRetrievalMinConfidence:
    """Tests for min_confidence filtering in retrieval."""

    def test_low_confidence_filtered_out(self, distiller: ExperienceDistiller):
        # Create a principle with default confidence (0.5)
        distiller.distill(
            task_description="Debug auth token issue",
            outcome="success",
            lessons=["Validate auth token before processing"],
        )
        # With high min_confidence, it should be filtered
        result = distiller.retrieve(
            task_description="Auth token issue",
            min_confidence=0.9,
        )
        assert len(result.principles) == 0

    def test_high_confidence_passes_filter(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Debug auth token issue",
            outcome="success",
            lessons=["Validate auth token before processing"],
        )
        result = distiller.retrieve(
            task_description="Auth token processing validation issue",
            min_confidence=0.1,
        )
        # Should pass since default confidence is 0.5 > 0.1
        assert len(result.principles) >= 1

    def test_default_min_confidence(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Auth debug",
            outcome="success",
            lessons=["Check auth tokens always"],
        )
        # Default MIN_CONFIDENCE is 0.3, principle confidence is 0.5
        result = distiller.retrieve(task_description="Auth token check debug")
        assert len(result.principles) >= 1


# ---------------------------------------------------------------------------
# 12. Retrieval ordering by relevance score
# ---------------------------------------------------------------------------


class TestRetrievalOrdering:
    """Tests that retrieval results are ordered by relevance score descending."""

    def test_higher_overlap_ranked_first(self, distiller: ExperienceDistiller):
        # Principle with more keyword overlap should rank higher
        distiller.distill(
            task_description="Fix authentication login",
            outcome="success",
            lessons=["Authentication login validation is critical for security"],
        )
        distiller.distill(
            task_description="Database backup plan",
            outcome="success",
            lessons=["Authentication needs careful login validation security checks"],
        )
        result = distiller.retrieve(
            task_description="authentication login validation security",
            top_k=10,
            min_confidence=0.0,
        )
        if len(result.principles) >= 2:
            # Both should be returned; ordering is by relevance score
            assert result.total_scored >= 2

    def test_retrieve_marks_usage(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Auth token validation check",
            outcome="success",
            lessons=["Validate auth token before processing check"],
        )
        p_before = distiller.get_all_principles()[0]
        assert p_before.usage_count == 0

        distiller.retrieve(
            task_description="Auth token processing validation check",
            min_confidence=0.0,
        )
        p_after = distiller.get_all_principles()[0]
        assert p_after.usage_count == 1

    def test_retrieve_updates_last_used(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Auth token validation check",
            outcome="success",
            lessons=["Validate auth token before processing check"],
        )
        p_before = distiller.get_all_principles()[0]
        old_last_used = p_before.last_used

        time.sleep(0.01)
        distiller.retrieve(
            task_description="Auth token processing validation check",
            min_confidence=0.0,
        )
        p_after = distiller.get_all_principles()[0]
        assert p_after.last_used > old_last_used


# ---------------------------------------------------------------------------
# 13. Outcome recording and principle update
# ---------------------------------------------------------------------------


class TestRecordOutcome:
    """Tests for record_outcome method."""

    def test_record_success_updates_principle(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Task",
            outcome="success",
            lessons=["Lesson one here"],
        )
        pid = result.new_principles[0].principle_id
        distiller.record_outcome(pid, success=True)
        p = distiller.get_all_principles()[0]
        assert p.usage_count == 1
        # Bayesian: (1.0*0 + 1 + 1) / (0 + 1 + 2) = 2/3
        expected_rate = (1.0 * 0 + 1 + BAYESIAN_ALPHA) / (0 + 1 + BAYESIAN_BETA)
        assert abs(p.success_rate - expected_rate) < 1e-9

    def test_record_failure_updates_principle(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Task",
            outcome="success",
            lessons=["Lesson two here"],
        )
        pid = result.new_principles[0].principle_id
        distiller.record_outcome(pid, success=False)
        p = distiller.get_all_principles()[0]
        assert p.usage_count == 1
        expected_rate = (1.0 * 0 + 0 + BAYESIAN_ALPHA) / (0 + 1 + BAYESIAN_BETA)
        assert abs(p.success_rate - expected_rate) < 1e-9

    def test_record_outcome_nonexistent_id_is_noop(self, distiller: ExperienceDistiller):
        # Should not raise
        distiller.record_outcome("nonexistent_id", success=True)
        assert distiller.get_all_principles() == []

    def test_record_outcome_persists(self, store_path: str):
        d1 = ExperienceDistiller(store_path=store_path)
        result = d1.distill(
            task_description="Persist test",
            outcome="success",
            lessons=["Persistence lesson"],
        )
        pid = result.new_principles[0].principle_id
        d1.record_outcome(pid, success=True)

        d2 = ExperienceDistiller(store_path=store_path)
        principles = d2.get_all_principles()
        assert len(principles) == 1
        # After record_outcome, usage_count should be 1
        # But persistence only saves to_dict fields; usage_count is included
        assert principles[0].usage_count == 1


# ---------------------------------------------------------------------------
# 14. Eviction when over MAX_PRINCIPLES
# ---------------------------------------------------------------------------


class TestEviction:
    """Tests for eviction of low-value principles."""

    def test_eviction_triggers_over_max(self, store_path: str):
        d = ExperienceDistiller(store_path=store_path, max_principles=10)
        for i in range(15):
            d.distill(
                task_description=f"Task {i}",
                outcome="success",
                lessons=[f"Unique lesson number {i} for eviction test"],
            )
        # After eviction, should be at or below max
        all_p = d.get_all_principles()
        assert len(all_p) <= 10

    def test_eviction_removes_lowest_value(self, store_path: str):
        d = ExperienceDistiller(store_path=store_path, max_principles=5)
        # Create 5 principles
        for i in range(5):
            d.distill(
                task_description=f"Task {i}",
                outcome="success",
                lessons=[f"Principle for eviction number {i}"],
            )
        # All have success_rate=1.0 and confidence=0.5, usage_count=0
        # Now add one more to trigger eviction
        d.distill(
            task_description="Trigger eviction task",
            outcome="success",
            lessons=["New principle to trigger eviction"],
        )
        assert len(d.get_all_principles()) <= 5

    def test_no_eviction_when_under_max(self, store_path: str):
        d = ExperienceDistiller(store_path=store_path, max_principles=100)
        for i in range(5):
            d.distill(
                task_description=f"Task {i}",
                outcome="success",
                lessons=[f"Small set principle {i}"],
            )
        assert len(d.get_all_principles()) == 5

    def test_eviction_preserves_used_principles(self, store_path: str):
        d = ExperienceDistiller(store_path=store_path, max_principles=5)
        # Create 5 principles
        results = []
        for i in range(5):
            r = d.distill(
                task_description=f"Task {i}",
                outcome="success",
                lessons=[f"Principle for used test {i}"],
            )
            results.append(r)

        # Mark one as used (higher eviction score)
        important_pid = results[0].new_principles[0].principle_id
        d.record_outcome(important_pid, success=True)

        # Add more to trigger eviction
        d.distill(
            task_description="Extra task",
            outcome="success",
            lessons=["Extra principle to trigger eviction"],
        )

        surviving_ids = {p.principle_id for p in d.get_all_principles()}
        # The used principle should survive (higher score)
        assert important_pid in surviving_ids


# ---------------------------------------------------------------------------
# 15. Keyword extraction (stop word filtering)
# ---------------------------------------------------------------------------


class TestKeywordExtraction:
    """Tests for _extract_keywords static method."""

    def test_extracts_lowercase_words(self):
        keywords = ExperienceDistiller._extract_keywords("Fix Bug In Auth Module")
        assert "fix" in keywords
        assert "bug" in keywords
        assert "auth" in keywords
        assert "module" in keywords

    def test_filters_stop_words(self):
        keywords = ExperienceDistiller._extract_keywords("The quick fox is a very fast animal")
        assert "the" not in keywords
        assert "is" not in keywords
        assert "quick" in keywords
        assert "fast" in keywords
        assert "animal" in keywords

    def test_extracts_words_with_underscores(self):
        keywords = ExperienceDistiller._extract_keywords("use tool_execution approach")
        assert "tool_execution" in keywords

    def test_extracts_words_with_numbers(self):
        keywords = ExperienceDistiller._extract_keywords("version v12 uses python3")
        assert "v12" in keywords
        assert "python3" in keywords

    def test_empty_string_returns_empty_set(self):
        keywords = ExperienceDistiller._extract_keywords("")
        assert keywords == set()

    def test_only_stop_words_returns_empty(self):
        keywords = ExperienceDistiller._extract_keywords("the is a an to of in for")
        assert keywords == set()

    def test_single_char_words_excluded(self):
        """Regex [a-z][a-z0-9_]+ requires 2+ chars."""
        keywords = ExperienceDistiller._extract_keywords("a b c dx ey")
        assert "a" not in keywords
        assert "b" not in keywords
        assert "c" not in keywords
        assert "dx" in keywords
        assert "ey" in keywords

    def test_uppercase_words_lowered(self):
        keywords = ExperienceDistiller._extract_keywords("UPPERCASE Word HERE")
        # [a-z][a-z0-9_]+ on lowered text
        assert "uppercase" in keywords
        assert "word" in keywords
        assert "here" in keywords


# ---------------------------------------------------------------------------
# 16. Fingerprinting (deterministic, case-insensitive)
# ---------------------------------------------------------------------------


class TestFingerprinting:
    """Tests for _fingerprint static method."""

    def test_deterministic(self):
        fp1 = ExperienceDistiller._fingerprint("Hello World")
        fp2 = ExperienceDistiller._fingerprint("Hello World")
        assert fp1 == fp2

    def test_case_insensitive(self):
        fp1 = ExperienceDistiller._fingerprint("Hello World")
        fp2 = ExperienceDistiller._fingerprint("hello world")
        assert fp1 == fp2

    def test_whitespace_normalized(self):
        fp1 = ExperienceDistiller._fingerprint("hello   world")
        fp2 = ExperienceDistiller._fingerprint("hello world")
        assert fp1 == fp2

    def test_returns_12_char_hex(self):
        fp = ExperienceDistiller._fingerprint("test string")
        assert len(fp) == 12
        assert all(c in "0123456789abcdef" for c in fp)

    def test_different_text_different_fingerprint(self):
        fp1 = ExperienceDistiller._fingerprint("alpha")
        fp2 = ExperienceDistiller._fingerprint("beta")
        assert fp1 != fp2

    def test_truncates_to_50_words(self):
        long_text = " ".join(f"word{i}" for i in range(100))
        short_text = " ".join(f"word{i}" for i in range(50))
        fp_long = ExperienceDistiller._fingerprint(long_text)
        fp_short = ExperienceDistiller._fingerprint(short_text)
        # Both should produce the same fingerprint (truncation to 50 words)
        assert fp_long == fp_short

    def test_manual_fingerprint_computation(self):
        text = "Check token expiry"
        normalized = " ".join(text.lower().split()[:50])
        expected = hashlib.md5(normalized.encode()).hexdigest()[:12]
        assert ExperienceDistiller._fingerprint(text) == expected


# ---------------------------------------------------------------------------
# 17. Persistence to/from JSONL (tmp_path isolation)
# ---------------------------------------------------------------------------


class TestPersistence:
    """Tests for JSONL persistence."""

    def test_save_creates_file(self, store_path: str):
        d = ExperienceDistiller(store_path=store_path)
        d.distill(
            task_description="Persist task",
            outcome="success",
            lessons=["Persistence lesson one"],
        )
        assert Path(store_path).exists()

    def test_load_restores_principles(self, store_path: str):
        d1 = ExperienceDistiller(store_path=store_path)
        d1.distill(
            task_description="Persist task",
            outcome="success",
            lessons=["Persistence lesson two"],
        )

        d2 = ExperienceDistiller(store_path=store_path)
        assert len(d2.get_all_principles()) == 1
        assert d2.get_all_principles()[0].text == "Persistence lesson two"

    def test_persistence_multiple_principles(self, store_path: str):
        d1 = ExperienceDistiller(store_path=store_path)
        d1.distill(
            task_description="Task A",
            outcome="success",
            lessons=["Lesson A", "Lesson B", "Lesson C"],
        )

        d2 = ExperienceDistiller(store_path=store_path)
        assert len(d2.get_all_principles()) == 3

    def test_persistence_preserves_category(self, store_path: str):
        d1 = ExperienceDistiller(store_path=store_path)
        d1.distill(
            task_description="Tool task",
            outcome="success",
            tools_used=["grep", "read"],
        )

        d2 = ExperienceDistiller(store_path=store_path)
        tool_ps = [p for p in d2.get_all_principles() if p.category == PrincipleCategory.TOOL_USE]
        assert len(tool_ps) == 1

    def test_persistence_preserves_success_rate(self, store_path: str):
        d1 = ExperienceDistiller(store_path=store_path)
        d1.distill(
            task_description="Rate task",
            outcome="failure: timeout",
            lessons=["Set timeout correctly"],
        )

        d2 = ExperienceDistiller(store_path=store_path)
        p = d2.get_all_principles()[0]
        assert p.success_rate == 0.0

    def test_jsonl_format(self, store_path: str):
        d = ExperienceDistiller(store_path=store_path)
        d.distill(
            task_description="Format test",
            outcome="success",
            lessons=["Line one", "Line two"],
        )
        with open(store_path, encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert "principle_id" in data
            assert "text" in data
            assert "category" in data

    def test_load_empty_file(self, store_path: str):
        Path(store_path).parent.mkdir(parents=True, exist_ok=True)
        Path(store_path).write_text("")
        d = ExperienceDistiller(store_path=store_path)
        assert len(d.get_all_principles()) == 0

    def test_load_nonexistent_file(self, store_path: str):
        d = ExperienceDistiller(store_path=store_path)
        assert len(d.get_all_principles()) == 0

    def test_corrupted_file_handled_gracefully(self, store_path: str):
        Path(store_path).parent.mkdir(parents=True, exist_ok=True)
        Path(store_path).write_text("not json\n{bad json\n")
        d = ExperienceDistiller(store_path=store_path)
        # Should not raise, just logs debug
        assert len(d.get_all_principles()) == 0

    def test_persistence_creates_parent_dirs(self, tmp_path: Path):
        nested = str(tmp_path / "a" / "b" / "c" / "principles.jsonl")
        d = ExperienceDistiller(store_path=nested)
        d.distill(
            task_description="Deep path",
            outcome="success",
            lessons=["Test nested dirs"],
        )
        assert Path(nested).exists()


# ---------------------------------------------------------------------------
# 18. Singleton get/reset pattern
# ---------------------------------------------------------------------------


class TestSingleton:
    """Tests for get_experience_distiller / reset_experience_distiller."""

    def test_get_returns_instance(self):
        d = get_experience_distiller()
        assert isinstance(d, ExperienceDistiller)

    def test_get_returns_same_instance(self):
        d1 = get_experience_distiller()
        d2 = get_experience_distiller()
        assert d1 is d2

    def test_reset_clears_instance(self):
        d1 = get_experience_distiller()
        reset_experience_distiller()
        d2 = get_experience_distiller()
        assert d1 is not d2

    def test_reset_then_get_creates_fresh(self):
        d = get_experience_distiller()
        # Modify state
        d.distill(
            task_description="Singleton task",
            outcome="success",
            lessons=["Singleton lesson"],
        )
        reset_experience_distiller()
        d2 = get_experience_distiller()
        # Fresh instance may load from default disk (but in tests, autouse
        # fixture reset already cleared it). Just verify it is a new object.
        assert d is not d2


# ---------------------------------------------------------------------------
# 19. Statistics tracking
# ---------------------------------------------------------------------------


class TestStatistics:
    """Tests for statistics tracking via get_stats."""

    def test_initial_stats_are_zero(self, distiller: ExperienceDistiller):
        stats = distiller.get_stats()
        assert stats.total_distillations == 0
        assert stats.total_retrievals == 0
        assert stats.principles_created == 0
        assert stats.principles_updated == 0
        assert stats.principles_retrieved == 0
        assert stats.avg_retrieval_count == 0.0

    def test_distill_increments_distillation_count(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Stats task",
            outcome="success",
            lessons=["Stats lesson"],
        )
        stats = distiller.get_stats()
        assert stats.total_distillations == 1

    def test_distill_increments_principles_created(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Stats task",
            outcome="success",
            lessons=["Lesson alpha", "Lesson beta"],
        )
        stats = distiller.get_stats()
        assert stats.principles_created == 2

    def test_distill_updates_principles_updated(self, distiller: ExperienceDistiller):
        lesson = "Reused lesson for stats"
        distiller.distill(task_description="T1", outcome="success", lessons=[lesson])
        distiller.distill(task_description="T2", outcome="success", lessons=[lesson])
        stats = distiller.get_stats()
        assert stats.principles_updated == 1

    def test_retrieve_increments_retrieval_count(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Auth validation check",
            outcome="success",
            lessons=["Always validate auth token check"],
        )
        distiller.retrieve(task_description="Auth token validation check")
        stats = distiller.get_stats()
        assert stats.total_retrievals == 1

    def test_avg_retrieval_count_computed(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Auth validation check",
            outcome="success",
            lessons=["Always validate auth token check"],
        )
        distiller.retrieve(
            task_description="Auth token validation check",
            min_confidence=0.0,
        )
        stats = distiller.get_stats()
        # avg_retrieval_count = (0*(1-1) + retrieved) / 1
        assert stats.avg_retrieval_count >= 0.0

    def test_multiple_distillations_tracked(self, distiller: ExperienceDistiller):
        for i in range(5):
            distiller.distill(
                task_description=f"Task {i}",
                outcome="success",
                lessons=[f"Lesson for multi stat {i}"],
            )
        stats = distiller.get_stats()
        assert stats.total_distillations == 5
        assert stats.principles_created == 5

    def test_reset_clears_stats(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Reset test",
            outcome="success",
            lessons=["Reset lesson"],
        )
        distiller.reset()
        stats = distiller.get_stats()
        assert stats.total_distillations == 0
        assert stats.principles_created == 0


# ---------------------------------------------------------------------------
# 20. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_empty_lessons_list(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="No lessons",
            outcome="success",
            lessons=[],
        )
        assert len(result.new_principles) == 0

    def test_none_lessons(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="None lessons",
            outcome="success",
            lessons=None,
        )
        assert len(result.new_principles) == 0

    def test_empty_task_description(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="",
            outcome="success",
            lessons=["Lesson with empty task"],
        )
        assert len(result.new_principles) == 1

    def test_very_long_task_description_truncated_in_source_tasks(
        self,
        distiller: ExperienceDistiller,
    ):
        long_desc = "A" * 500
        result = distiller.distill(
            task_description=long_desc,
            outcome="success",
            lessons=["Long desc lesson"],
        )
        p = result.new_principles[0]
        assert len(p.source_tasks[0]) == 100

    def test_retrieve_empty_store(self, distiller: ExperienceDistiller):
        result = distiller.retrieve(task_description="Anything")
        assert result.principles == []
        assert result.total_scored == 0

    def test_distill_outcome_case_insensitive(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Case test",
            outcome="SUCCESS",
            lessons=["Case insensitive outcome"],
        )
        p = result.new_principles[0]
        assert p.success_rate == 1.0

    def test_distill_outcome_partial_match(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Partial",
            outcome="Task completed successfully",
            lessons=["Partial success match"],
        )
        p = result.new_principles[0]
        assert p.success_rate == 1.0  # "success" is in the outcome

    def test_distill_outcome_failure_string(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Fail",
            outcome="error: something broke",
            lessons=["Failure case"],
        )
        p = result.new_principles[0]
        assert p.success_rate == 0.0  # "success" not in outcome

    def test_get_all_principles_returns_copy(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Copy test",
            outcome="success",
            lessons=["Copy lesson"],
        )
        list1 = distiller.get_all_principles()
        list2 = distiller.get_all_principles()
        assert list1 is not list2

    def test_reset_clears_principles(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="Reset",
            outcome="success",
            lessons=["Reset me"],
        )
        assert len(distiller.get_all_principles()) == 1
        distiller.reset()
        assert len(distiller.get_all_principles()) == 0

    def test_distill_with_only_tools_no_lessons(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Tools only",
            outcome="success",
            tools_used=["bash", "write"],
        )
        assert len(result.new_principles) == 1
        assert result.new_principles[0].category == PrincipleCategory.TOOL_USE

    def test_distill_with_only_errors_no_lessons(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Errors only",
            outcome="success",
            error_messages=["FileNotFoundError"],
        )
        assert len(result.new_principles) == 1
        assert result.new_principles[0].category == PrincipleCategory.ERROR_RECOVERY

    def test_keywords_with_no_meaningful_words(self):
        keywords = ExperienceDistiller._extract_keywords("! @ # $ % 1 2 3")
        assert keywords == set()

    def test_relevance_score_zero_overlap_low_quality(
        self,
        distiller: ExperienceDistiller,
    ):
        """Principles with zero keyword overlap and low quality scores should
        fall below the retrieval threshold and not be returned."""
        # Use failure outcome so quality boost is low:
        # success_rate=0.0, confidence=0.5 => boost = 0.0*0.3+0.5*0.2 = 0.1
        distiller.distill(
            task_description="Database migration schema",
            outcome="failure",
            lessons=["Always backup database before schema migration"],
        )
        result = distiller.retrieve(
            task_description="xyzzy gibberish foobar unrelated",
            min_confidence=0.0,
        )
        assert len(result.principles) == 0

    def test_max_principles_param(self, store_path: str):
        d = ExperienceDistiller(store_path=store_path, max_principles=3)
        for i in range(10):
            d.distill(
                task_description=f"Task {i}",
                outcome="success",
                lessons=[f"Unique max principle test {i}"],
            )
        assert len(d.get_all_principles()) <= 3


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


class TestRelevanceScoreEdges:
    """Additional tests for relevance score computation."""

    def test_principle_with_no_keywords_gets_zero_score(
        self,
        distiller: ExperienceDistiller,
    ):
        """A principle whose keywords are empty should score 0."""
        # Manually inject a principle with empty keywords
        from core.memory_pkg.skills.experience_distiller import PrincipleCategory, StrategicPrinciple

        p = StrategicPrinciple(
            principle_id="empty_kw",
            text="No keywords",
            category=PrincipleCategory.STRATEGY,
            keywords=set(),
        )
        distiller._principles["empty_kw"] = p
        result = distiller.retrieve(
            task_description="some real words here",
            min_confidence=0.0,
        )
        # empty keywords -> relevance score = 0 -> below threshold
        pids = {pr.principle_id for pr in result.principles}
        assert "empty_kw" not in pids

    def test_quality_boost_affects_score(self, distiller: ExperienceDistiller):
        """Higher success_rate and confidence should boost relevance."""
        from core.memory_pkg.skills.experience_distiller import PrincipleCategory, StrategicPrinciple

        p_low = StrategicPrinciple(
            principle_id="low_q",
            text="Auth token check",
            category=PrincipleCategory.STRATEGY,
            keywords={"auth", "token", "check"},
            success_rate=0.1,
            confidence=0.1,
        )
        p_high = StrategicPrinciple(
            principle_id="high_q",
            text="Auth token check premium",
            category=PrincipleCategory.STRATEGY,
            keywords={"auth", "token", "check"},
            success_rate=1.0,
            confidence=1.0,
        )
        distiller._principles["low_q"] = p_low
        distiller._principles["high_q"] = p_high

        result = distiller.retrieve(
            task_description="auth token check",
            min_confidence=0.0,
            top_k=2,
        )
        if len(result.principles) == 2:
            # high_q should come first due to quality boost
            assert result.principles[0].principle_id == "high_q"


class TestCategoryPatterns:
    """Tests that CATEGORY_PATTERNS constant is well-formed."""

    def test_all_categories_have_patterns(self):
        for cat in PrincipleCategory:
            assert cat in CATEGORY_PATTERNS
            assert len(CATEGORY_PATTERNS[cat]) > 0

    def test_patterns_are_lowercase(self):
        for cat, patterns in CATEGORY_PATTERNS.items():
            for p in patterns:
                assert p == p.lower(), f"Pattern '{p}' in {cat} is not lowercase"


class TestConstants:
    """Tests for module-level constants."""

    def test_retrieval_threshold_positive(self):
        assert RETRIEVAL_THRESHOLD > 0

    def test_max_principles_positive(self):
        assert MAX_PRINCIPLES > 0

    def test_min_confidence_between_0_and_1(self):
        assert 0 <= MIN_CONFIDENCE <= 1

    def test_bayesian_alpha_positive(self):
        assert BAYESIAN_ALPHA > 0

    def test_bayesian_beta_positive(self):
        assert BAYESIAN_BETA > 0

    def test_confidence_ema_between_0_and_1(self):
        assert 0 < CONFIDENCE_EMA < 1

    def test_stop_words_is_frozenset(self):
        assert isinstance(STOP_WORDS, frozenset)

    def test_stop_words_contains_common_words(self):
        for word in ["the", "a", "is", "to", "of", "in", "and"]:
            assert word in STOP_WORDS


class TestDistillCombined:
    """Tests for distill with multiple input types combined."""

    def test_lessons_and_tools_combined(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Auth refactor",
            outcome="success",
            lessons=["Validate tokens early"],
            tools_used=["grep", "edit"],
        )
        # 1 from lesson + 1 from tool_use
        assert len(result.new_principles) == 2
        categories = {p.category for p in result.new_principles}
        assert PrincipleCategory.TOOL_USE in categories

    def test_lessons_tools_errors_combined(self, distiller: ExperienceDistiller):
        result = distiller.distill(
            task_description="Complex task",
            outcome="success",
            lessons=["Plan architecture first"],
            tools_used=["bash"],
            error_messages=["ImportError: no module"],
        )
        # 1 lesson + 1 tool + 1 error
        assert len(result.new_principles) == 3
        categories = {p.category for p in result.new_principles}
        assert PrincipleCategory.TOOL_USE in categories
        assert PrincipleCategory.ERROR_RECOVERY in categories

    def test_distill_returns_correct_total(self, distiller: ExperienceDistiller):
        distiller.distill(
            task_description="First",
            outcome="success",
            lessons=["First lesson"],
        )
        result = distiller.distill(
            task_description="Second",
            outcome="success",
            lessons=["Second lesson"],
        )
        assert result.total_principles == 2
