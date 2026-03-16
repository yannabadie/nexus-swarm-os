"""
Tests for core/hive_mind/context_scope.py - V9.6

Validates context scoping for controlled inheritance between
HiveMind phases, spawned agents, and parallel execution.
"""

from datetime import datetime

from core.intelligence.hive_mind.context_scope import (
    SCOPE_POLICIES,
    ContextScope,
    ContextScopePolicy,
    InheritanceDirection,
    ScopedContext,
    get_scope_policy,
)


class TestContextScope:
    """Test ContextScope enum."""

    def test_all_scope_values_exist(self):
        """All 6 scope levels should exist."""
        assert ContextScope.FULL
        assert ContextScope.TASK_PLUS_RESULTS
        assert ContextScope.RESULTS_ONLY
        assert ContextScope.TASK_ONLY
        assert ContextScope.MINIMAL
        assert ContextScope.FRESH

    def test_scope_string_values(self):
        """Scopes should have correct string values."""
        assert ContextScope.FULL.value == "full"
        assert ContextScope.TASK_PLUS_RESULTS.value == "task_plus_results"
        assert ContextScope.RESULTS_ONLY.value == "results_only"
        assert ContextScope.TASK_ONLY.value == "task_only"
        assert ContextScope.MINIMAL.value == "minimal"
        assert ContextScope.FRESH.value == "fresh"

    def test_scope_is_string_enum(self):
        """ContextScope should inherit from str."""
        assert isinstance(ContextScope.FULL, str)
        assert ContextScope.FULL == "full"

    def test_scope_comparison(self):
        """Scopes should be comparable by value."""
        assert ContextScope.FULL != ContextScope.FRESH
        assert ContextScope("full") == ContextScope.FULL


class TestInheritanceDirection:
    """Test InheritanceDirection enum."""

    def test_all_direction_values_exist(self):
        """All 4 direction values should exist."""
        assert InheritanceDirection.NONE
        assert InheritanceDirection.PARENT_TO_CHILD
        assert InheritanceDirection.PHASE_TO_PHASE
        assert InheritanceDirection.BIDIRECTIONAL

    def test_direction_string_values(self):
        """Directions should have correct string values."""
        assert InheritanceDirection.NONE.value == "none"
        assert InheritanceDirection.PARENT_TO_CHILD.value == "parent_to_child"
        assert InheritanceDirection.PHASE_TO_PHASE.value == "phase_to_phase"
        assert InheritanceDirection.BIDIRECTIONAL.value == "bidirectional"


class TestScopedContext:
    """Test ScopedContext dataclass."""

    def test_create_basic_context(self):
        """Should create context with required scope."""
        ctx = ScopedContext(scope=ContextScope.TASK_ONLY)
        assert ctx.scope == ContextScope.TASK_ONLY
        assert ctx.task_description == ""
        assert ctx.relevant_files == []

    def test_create_full_context(self):
        """Should create context with all fields."""
        ctx = ScopedContext(
            scope=ContextScope.FULL,
            task_description="Implement feature X",
            relevant_files=["src/main.py", "tests/test_main.py"],
            parent_summary="Previous phase completed analysis",
            full_history=[{"role": "user", "content": "test"}],
            metadata={"phase": "execution"},
            session_uuid="test-uuid-123",
            model_context="You are an expert Python developer",
        )
        assert ctx.scope == ContextScope.FULL
        assert ctx.task_description == "Implement feature X"
        assert len(ctx.relevant_files) == 2
        assert ctx.parent_summary == "Previous phase completed analysis"
        assert len(ctx.full_history) == 1
        assert ctx.session_uuid == "test-uuid-123"

    def test_created_at_auto_generated(self):
        """Should auto-generate created_at timestamp."""
        ctx = ScopedContext(scope=ContextScope.MINIMAL)
        assert ctx.created_at is not None
        # Should be parseable as ISO datetime
        datetime.fromisoformat(ctx.created_at)

    def test_estimated_tokens_calculation(self):
        """Should estimate tokens based on content."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            task_description="A" * 400,  # 400 chars = ~100 tokens
        )
        assert ctx.estimated_tokens >= 90
        assert ctx.estimated_tokens <= 110

    def test_estimated_tokens_includes_files(self):
        """Token estimate should include file names."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            relevant_files=["file1.py", "file2.py", "file3.py"],
        )
        assert ctx.estimated_tokens > 0

    def test_estimated_tokens_includes_summary(self):
        """Token estimate should include parent summary."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_PLUS_RESULTS,
            parent_summary="B" * 800,  # 800 chars = ~200 tokens
        )
        assert ctx.estimated_tokens >= 180
        assert ctx.estimated_tokens <= 220


class TestScopedContextPromptPrefix:
    """Test to_prompt_prefix() method."""

    def test_fresh_scope_empty_prefix(self):
        """FRESH scope should return empty prefix."""
        ctx = ScopedContext(
            scope=ContextScope.FRESH,
            task_description="Should be ignored",
        )
        assert ctx.to_prompt_prefix() == ""

    def test_minimal_scope_excludes_task(self):
        """MINIMAL scope should exclude task description."""
        ctx = ScopedContext(
            scope=ContextScope.MINIMAL,
            task_description="This task should not appear",
        )
        prefix = ctx.to_prompt_prefix()
        assert "## Task" not in prefix

    def test_task_only_includes_task(self):
        """TASK_ONLY should include task description."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            task_description="Implement feature X",
        )
        prefix = ctx.to_prompt_prefix()
        assert "## Task" in prefix
        assert "Implement feature X" in prefix

    def test_task_only_includes_files(self):
        """TASK_ONLY should include relevant files."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            relevant_files=["main.py", "utils.py"],
        )
        prefix = ctx.to_prompt_prefix()
        assert "## Relevant Files" in prefix
        assert "main.py" in prefix

    def test_task_only_excludes_summary(self):
        """TASK_ONLY should exclude parent summary."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            parent_summary="Previous findings here",
        )
        prefix = ctx.to_prompt_prefix()
        assert "## Previous Findings" not in prefix

    def test_results_only_includes_summary(self):
        """RESULTS_ONLY should include parent summary."""
        ctx = ScopedContext(
            scope=ContextScope.RESULTS_ONLY,
            parent_summary="Analysis found 3 issues",
        )
        prefix = ctx.to_prompt_prefix()
        assert "## Previous Findings" in prefix
        assert "Analysis found 3 issues" in prefix

    def test_results_only_excludes_task(self):
        """RESULTS_ONLY should exclude task description."""
        ctx = ScopedContext(
            scope=ContextScope.RESULTS_ONLY,
            task_description="This should not appear",
        )
        prefix = ctx.to_prompt_prefix()
        assert "## Task" not in prefix

    def test_task_plus_results_includes_both(self):
        """TASK_PLUS_RESULTS should include task and summary."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_PLUS_RESULTS,
            task_description="Build the feature",
            parent_summary="Previous analysis complete",
        )
        prefix = ctx.to_prompt_prefix()
        assert "## Task" in prefix
        assert "Build the feature" in prefix
        assert "## Previous Findings" in prefix
        assert "Previous analysis complete" in prefix

    def test_full_scope_includes_all(self):
        """FULL scope should include everything."""
        ctx = ScopedContext(
            scope=ContextScope.FULL,
            task_description="Complete task",
            relevant_files=["file.py"],
            parent_summary="Previous work done",
            model_context="Expert capabilities",
        )
        prefix = ctx.to_prompt_prefix()
        assert "## Task" in prefix
        assert "## Relevant Files" in prefix
        assert "## Previous Findings" in prefix
        assert "## Your Capabilities" in prefix

    def test_files_truncated_at_10(self):
        """Should truncate files list at 10."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            relevant_files=[f"file{i}.py" for i in range(15)],
        )
        prefix = ctx.to_prompt_prefix()
        assert "(+5 more)" in prefix

    def test_prefix_ends_with_separator(self):
        """Non-empty prefix should end with separator."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            task_description="Test task",
        )
        prefix = ctx.to_prompt_prefix()
        assert prefix.endswith("---\n\n")


class TestScopedContextToDict:
    """Test to_dict() serialization."""

    def test_basic_serialization(self):
        """Should serialize basic context."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            task_description="Test task",
        )
        data = ctx.to_dict()
        assert data["scope"] == "task_only"
        assert data["task_description"] == "Test task"

    def test_truncates_long_task(self):
        """Should truncate long task descriptions."""
        long_task = "A" * 500
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            task_description=long_task,
        )
        data = ctx.to_dict()
        assert len(data["task_description"]) < 250
        assert data["task_description"].endswith("...")

    def test_truncates_long_summary(self):
        """Should truncate long parent summaries."""
        long_summary = "B" * 1000
        ctx = ScopedContext(
            scope=ContextScope.RESULTS_ONLY,
            parent_summary=long_summary,
        )
        data = ctx.to_dict()
        assert len(data["parent_summary"]) < 550
        assert data["parent_summary"].endswith("...")

    def test_includes_history_metadata(self):
        """Should include history count, not full history."""
        ctx = ScopedContext(
            scope=ContextScope.FULL,
            full_history=[{"msg": i} for i in range(10)],
        )
        data = ctx.to_dict()
        assert data["has_full_history"] is True
        assert data["history_items"] == 10
        assert "full_history" not in data  # Full history not serialized

    def test_includes_session_uuid(self):
        """Should include session UUID."""
        ctx = ScopedContext(
            scope=ContextScope.MINIMAL,
            session_uuid="uuid-12345",
        )
        data = ctx.to_dict()
        assert data["session_uuid"] == "uuid-12345"


class TestContextScopePolicy:
    """Test ContextScopePolicy dataclass."""

    def test_default_policy_creation(self):
        """Should create policy with defaults."""
        policy = ContextScopePolicy()
        assert policy.parallel_scope == ContextScope.TASK_ONLY
        assert policy.spawn_scope == ContextScope.TASK_ONLY
        assert policy.invalidate_on_model_change is True

    def test_custom_policy_creation(self):
        """Should create policy with custom values."""
        policy = ContextScopePolicy(
            parallel_scope=ContextScope.FRESH,
            spawn_scope=ContextScope.MINIMAL,
            invalidate_on_model_change=False,
        )
        assert policy.parallel_scope == ContextScope.FRESH
        assert policy.spawn_scope == ContextScope.MINIMAL
        assert policy.invalidate_on_model_change is False

    def test_default_phase_inheritance(self):
        """Should have default phase inheritance rules."""
        policy = ContextScopePolicy()
        assert "analysis_to_debate" in policy.phase_inheritance
        assert "execution_to_diagnosis" in policy.phase_inheritance

    def test_get_phase_scope_known_transition(self):
        """Should return correct scope for known transitions."""
        policy = ContextScopePolicy()

        # Normal transitions get TASK_PLUS_RESULTS
        assert policy.get_phase_scope("analysis", "debate") == ContextScope.TASK_PLUS_RESULTS

        # Diagnosis needs FULL context for debugging
        assert policy.get_phase_scope("execution", "diagnosis") == ContextScope.FULL

        # Consolidation only needs results
        assert policy.get_phase_scope("execution", "consolidation") == ContextScope.RESULTS_ONLY

    def test_get_phase_scope_unknown_transition(self):
        """Should return TASK_PLUS_RESULTS for unknown transitions."""
        policy = ContextScopePolicy()
        scope = policy.get_phase_scope("unknown", "phase")
        assert scope == ContextScope.TASK_PLUS_RESULTS


class TestScopePolicies:
    """Test SCOPE_POLICIES dict."""

    def test_all_complexity_levels_exist(self):
        """All 5 complexity levels should have policies."""
        assert "TRIVIAL" in SCOPE_POLICIES
        assert "SIMPLE" in SCOPE_POLICIES
        assert "MODERATE" in SCOPE_POLICIES
        assert "COMPLEX" in SCOPE_POLICIES
        assert "EXPERT" in SCOPE_POLICIES

    def test_trivial_uses_fresh_parallel(self):
        """TRIVIAL should use FRESH for parallel scope."""
        policy = SCOPE_POLICIES["TRIVIAL"]
        assert policy.parallel_scope == ContextScope.FRESH

    def test_trivial_no_model_invalidation(self):
        """TRIVIAL should not invalidate on model change."""
        policy = SCOPE_POLICIES["TRIVIAL"]
        assert policy.invalidate_on_model_change is False

    def test_simple_uses_task_only(self):
        """SIMPLE should use TASK_ONLY for parallel/spawn."""
        policy = SCOPE_POLICIES["SIMPLE"]
        assert policy.parallel_scope == ContextScope.TASK_ONLY
        assert policy.spawn_scope == ContextScope.TASK_ONLY

    def test_expert_uses_full_spawn(self):
        """EXPERT should use FULL for spawn scope."""
        policy = SCOPE_POLICIES["EXPERT"]
        assert policy.spawn_scope == ContextScope.FULL

    def test_expert_full_model_change_scope(self):
        """EXPERT should use FULL scope on model change."""
        policy = SCOPE_POLICIES["EXPERT"]
        assert policy.model_change_scope == ContextScope.FULL

    def test_moderate_complex_similar(self):
        """MODERATE and COMPLEX should have similar policies."""
        moderate = SCOPE_POLICIES["MODERATE"]
        complex_p = SCOPE_POLICIES["COMPLEX"]
        assert moderate.parallel_scope == complex_p.parallel_scope
        assert moderate.invalidate_on_model_change == complex_p.invalidate_on_model_change


class TestGetScopePolicy:
    """Test get_scope_policy() function."""

    def test_returns_correct_policy(self):
        """Should return correct policy for each complexity."""
        assert get_scope_policy("TRIVIAL") == SCOPE_POLICIES["TRIVIAL"]
        assert get_scope_policy("SIMPLE") == SCOPE_POLICIES["SIMPLE"]
        assert get_scope_policy("MODERATE") == SCOPE_POLICIES["MODERATE"]
        assert get_scope_policy("COMPLEX") == SCOPE_POLICIES["COMPLEX"]
        assert get_scope_policy("EXPERT") == SCOPE_POLICIES["EXPERT"]

    def test_case_insensitive(self):
        """Should be case-insensitive."""
        assert get_scope_policy("trivial") == SCOPE_POLICIES["TRIVIAL"]
        assert get_scope_policy("Trivial") == SCOPE_POLICIES["TRIVIAL"]
        assert get_scope_policy("TRIVIAL") == SCOPE_POLICIES["TRIVIAL"]

    def test_unknown_returns_moderate(self):
        """Unknown complexity should return MODERATE."""
        policy = get_scope_policy("UNKNOWN")
        assert policy == SCOPE_POLICIES["MODERATE"]

    def test_empty_returns_moderate(self):
        """Empty string should return MODERATE."""
        policy = get_scope_policy("")
        assert policy == SCOPE_POLICIES["MODERATE"]


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_context(self):
        """Should handle completely empty context."""
        ctx = ScopedContext(scope=ContextScope.FRESH)
        assert ctx.to_prompt_prefix() == ""
        data = ctx.to_dict()
        assert data["scope"] == "fresh"

    def test_very_long_file_list(self):
        """Should handle very long file lists."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            relevant_files=[f"path/to/file{i}.py" for i in range(100)],
        )
        prefix = ctx.to_prompt_prefix()
        assert "(+90 more)" in prefix

    def test_empty_strings(self):
        """Should handle empty string fields."""
        ctx = ScopedContext(
            scope=ContextScope.FULL,
            task_description="",
            parent_summary="",
            model_context="",
        )
        # Should not crash
        ctx.to_prompt_prefix()
        data = ctx.to_dict()
        assert data is not None

    def test_token_estimate_never_negative(self):
        """Token estimate should never be negative."""
        ctx = ScopedContext(scope=ContextScope.FRESH)
        assert ctx.estimated_tokens >= 0

    def test_none_session_uuid(self):
        """Should handle None session UUID."""
        ctx = ScopedContext(
            scope=ContextScope.MINIMAL,
            session_uuid=None,
        )
        data = ctx.to_dict()
        assert data["session_uuid"] is None

    def test_special_characters_in_content(self):
        """Should handle special characters."""
        ctx = ScopedContext(
            scope=ContextScope.TASK_ONLY,
            task_description="Task with special chars: <>&\"'\n\t",
            relevant_files=["path/with spaces/file.py"],
        )
        prefix = ctx.to_prompt_prefix()
        assert "special chars" in prefix
