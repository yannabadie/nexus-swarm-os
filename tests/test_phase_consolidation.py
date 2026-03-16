"""
Tests for Phase 7: Knowledge Consolidation.

Validates the KnowledgeConsolidationPhase class which handles
post-task reflection and knowledge archival in the HiveMind pipeline.

Coverage:
- ConsolidationPhaseResult dataclass
- REFLECTION_PROMPT / CONSOLIDATION_DEBATE_PROMPT templates
- V12.4 integrations (skill crystallizer, principle library, AutoMemory,
  UncertaintyPropagator reset, ExperienceDistiller) graceful degradation
- _parse_reflection() logic
- Full execute() flow with mocked drivers
- Agent retention decision logic (_merge_agent_decisions)
- Knowledge entry extraction and RAG archival (_merge_knowledge_entries, _archive_knowledge)
- Error handling when V12.4 modules fail
- Budget-limited minimal result path
- Session isolation via HiveMindSessionIntegration
"""

import json
from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.drivers.protocol import DriverResponse, DriverResponseStatus
from core.intelligence.hive_mind.phases.phase_consolidation import (
    CONSOLIDATION_DEBATE_PROMPT,
    REFLECTION_PROMPT,
    ConsolidationPhaseResult,
    KnowledgeConsolidationPhase,
)
from core.intelligence.hive_mind.types import (
    AgentRetention,
    BreakpointResponse,
    KnowledgeConsolidation,
    KnowledgeEntry,
    RetentionDecision,
    UserBreakpoint,
)

# =============================================================================
# Fixtures
# =============================================================================


def _make_reflection_json(
    patterns=None,
    antipatterns=None,
    capabilities=None,
    agents_to_retain=None,
    knowledge_to_archive=None,
    improvements=None,
    overall="Good task.",
    satisfaction=0.8,
):
    """Build a valid reflection JSON string."""
    return json.dumps(
        {
            "learned_patterns": patterns or ["cache results"],
            "learned_antipatterns": antipatterns or ["skip validation"],
            "new_capabilities_identified": capabilities or ["web_search"],
            "agents_to_retain": agents_to_retain or [],
            "knowledge_to_archive": knowledge_to_archive or [],
            "nexus_improvements": improvements or ["faster routing"],
            "overall_reflection": overall,
            "satisfaction": satisfaction,
        }
    )


def _make_user_response(chosen="accept_all"):
    """Build a mock BreakpointResponse."""
    return BreakpointResponse(
        breakpoint_type=UserBreakpoint.KNOWLEDGE_CONSOLIDATION,
        chosen_option=chosen,
    )


def _make_driver_response(content: str, input_tokens: int = 100, output_tokens: int = 50) -> DriverResponse:
    """Create a DriverResponse as returned by invoke() for consolidation tests."""
    return DriverResponse(
        content=content,
        status=DriverResponseStatus.SUCCESS,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


@pytest.fixture
def mock_gemini():
    driver = MagicMock()
    driver.send_message_async = AsyncMock(return_value=_make_reflection_json())
    driver.invoke = AsyncMock(return_value=_make_driver_response(_make_reflection_json()))
    return driver


@pytest.fixture
def mock_claude():
    driver = MagicMock()
    _claude_json = _make_reflection_json(patterns=["use caching"], satisfaction=0.9)
    driver.send_message_async = AsyncMock(return_value=_claude_json)
    driver.invoke = AsyncMock(return_value=_make_driver_response(_claude_json))
    return driver


@pytest.fixture
def mock_cost_estimator():
    est = MagicMock()
    est.can_afford_multiple = MagicMock(return_value=True)
    est.record_cost = MagicMock()
    return est


@pytest.fixture
def mock_context_manager():
    ctx = MagicMock()
    ctx.add_insight = MagicMock()
    ctx.add_item = MagicMock()
    return ctx


@pytest.fixture
def mock_agent_registry():
    reg = MagicMock()
    reg.deactivate_agent = MagicMock()
    reg.record_usage = MagicMock()
    return reg


@pytest.fixture
def mock_user_handler():
    handler = MagicMock()
    handler.knowledge_consolidation = MagicMock(return_value=_make_user_response("accept_all"))
    return handler


@pytest.fixture
def mock_project_memory():
    mem = MagicMock()
    mem.add_document = MagicMock()
    return mem


@pytest.fixture
def phase(
    mock_gemini,
    mock_claude,
    mock_cost_estimator,
    mock_context_manager,
    mock_agent_registry,
    mock_user_handler,
    mock_project_memory,
):
    """Build a fully-mocked KnowledgeConsolidationPhase."""
    return KnowledgeConsolidationPhase(
        gemini_driver=mock_gemini,
        claude_driver=mock_claude,
        cost_estimator=mock_cost_estimator,
        context_manager=mock_context_manager,
        agent_registry=mock_agent_registry,
        user_handler=mock_user_handler,
        project_memory=mock_project_memory,
        task_id="test-task-001",
    )


@pytest.fixture
def phase_no_memory(
    mock_gemini,
    mock_claude,
    mock_cost_estimator,
    mock_context_manager,
    mock_agent_registry,
    mock_user_handler,
):
    """Phase without project_memory -- uses context_manager fallback."""
    return KnowledgeConsolidationPhase(
        gemini_driver=mock_gemini,
        claude_driver=mock_claude,
        cost_estimator=mock_cost_estimator,
        context_manager=mock_context_manager,
        agent_registry=mock_agent_registry,
        user_handler=mock_user_handler,
        project_memory=None,
        task_id="test-task-no-mem",
    )


SAMPLE_EXECUTE_KWARGS = dict(
    task="Implement auth middleware",
    success=True,
    duration=45.3,
    steps_completed=4,
    issues_count=1,
    approach="LEAD_SUPPORT sequential",
    agents_used=["gemini", "claude"],
    agents_spawned=["auth_specialist"],
)


# =============================================================================
# 1. ConsolidationPhaseResult Dataclass
# =============================================================================


class TestConsolidationPhaseResult:
    """Validate ConsolidationPhaseResult dataclass structure and construction."""

    def test_field_names(self):
        names = {f.name for f in fields(ConsolidationPhaseResult)}
        expected = {
            "consolidation",
            "gemini_reflection",
            "claude_reflection",
            "user_decision",
            "archived_to_rag",
            "agents_retained",
            "agents_deleted",
        }
        assert names == expected

    def test_construction(self):
        consolidation = KnowledgeConsolidation(
            learned_patterns=["p1"],
            learned_antipatterns=["a1"],
            new_capabilities_identified=[],
            agents_retention=[],
            knowledge_to_archive=[],
            tools_to_create=[],
            nexus_improvements=[],
            task_success=True,
            confidence_in_decisions=0.9,
            gemini_reflection="ok",
            claude_reflection="ok",
        )
        result = ConsolidationPhaseResult(
            consolidation=consolidation,
            gemini_reflection="g_ref",
            claude_reflection="c_ref",
            user_decision="accept_all",
            archived_to_rag=3,
            agents_retained=["a1"],
            agents_deleted=["a2"],
        )
        assert result.archived_to_rag == 3
        assert result.agents_retained == ["a1"]
        assert result.consolidation.task_success is True

    def test_empty_lists(self):
        consolidation = KnowledgeConsolidation(
            learned_patterns=[],
            learned_antipatterns=[],
            new_capabilities_identified=[],
            agents_retention=[],
            knowledge_to_archive=[],
            tools_to_create=[],
            nexus_improvements=[],
            task_success=False,
            confidence_in_decisions=0.0,
            gemini_reflection="",
            claude_reflection="",
        )
        result = ConsolidationPhaseResult(
            consolidation=consolidation,
            gemini_reflection="",
            claude_reflection="",
            user_decision="skip",
            archived_to_rag=0,
            agents_retained=[],
            agents_deleted=[],
        )
        assert result.agents_retained == []
        assert result.archived_to_rag == 0


# =============================================================================
# 2. Prompt Templates
# =============================================================================


class TestPromptTemplates:
    """Validate prompt template strings and formatting."""

    def test_reflection_prompt_contains_placeholders(self):
        for placeholder in [
            "{task}",
            "{success}",
            "{duration:.1f}",
            "{steps_completed}",
            "{issues_count}",
            "{approach}",
            "{agents_used}",
            "{agents_spawned}",
        ]:
            assert placeholder in REFLECTION_PROMPT, f"Missing placeholder {placeholder} in REFLECTION_PROMPT"

    def test_reflection_prompt_formats_correctly(self):
        formatted = REFLECTION_PROMPT.format(
            task="Build API",
            success="Yes",
            duration=12.3,
            steps_completed=5,
            issues_count=0,
            approach="PARALLEL",
            agents_used="gemini, claude",
            agents_spawned="None",
        )
        assert "Build API" in formatted
        assert "12.3s" in formatted
        assert "PARALLEL" in formatted

    def test_reflection_prompt_requests_json_keys(self):
        for key in [
            "learned_patterns",
            "learned_antipatterns",
            "knowledge_to_archive",
            "agents_to_retain",
            "satisfaction",
        ]:
            assert key in REFLECTION_PROMPT

    def test_debate_prompt_contains_placeholders(self):
        for placeholder in ["{task}", "{your_reflection}", "{other_reflection}"]:
            assert placeholder in CONSOLIDATION_DEBATE_PROMPT

    def test_debate_prompt_formats_correctly(self):
        formatted = CONSOLIDATION_DEBATE_PROMPT.format(
            task="Fix bug",
            your_reflection="Looks good",
            other_reflection="Needs work",
        )
        assert "Fix bug" in formatted
        assert "Looks good" in formatted
        assert "Needs work" in formatted

    def test_debate_prompt_requests_json_keys(self):
        for key in [
            "agreed_patterns",
            "debated_patterns",
            "agreed_agent_decisions",
            "final_recommendation",
        ]:
            assert key in CONSOLIDATION_DEBATE_PROMPT


# =============================================================================
# 3. _parse_reflection
# =============================================================================


class TestParseReflection:
    """Test the _parse_reflection helper that parses LLM JSON output."""

    def test_valid_json(self, phase):
        data = phase._parse_reflection(_make_reflection_json())
        assert data["learned_patterns"] == ["cache results"]
        assert data["satisfaction"] == 0.8

    def test_invalid_json_returns_empty_dict(self, phase):
        data = phase._parse_reflection("This is not json at all")
        assert data == {}

    def test_empty_string_returns_empty_dict(self, phase):
        data = phase._parse_reflection("")
        assert data == {}

    def test_json_with_extra_text(self, phase):
        text = "Here is my analysis:\n" + _make_reflection_json() + "\nEnd."
        data = phase._parse_reflection(text)
        assert "learned_patterns" in data

    def test_dict_input_passthrough(self, phase):
        raw = {"learned_patterns": ["x"], "satisfaction": 0.5}
        data = phase._parse_reflection(raw)
        assert data["learned_patterns"] == ["x"]

    def test_none_input(self, phase):
        data = phase._parse_reflection(None)
        assert data == {}

    def test_numeric_input(self, phase):
        data = phase._parse_reflection(42)
        assert data == {}


# =============================================================================
# 4. _merge_agent_decisions
# =============================================================================


class TestMergeAgentDecisions:
    """Test the agent retention decision merging logic."""

    def test_both_agree_keep(self, phase):
        gemini = [{"agent_id": "a1", "vote": "keep_permanent", "reason": "useful"}]
        claude = [{"agent_id": "a1", "vote": "keep_permanent", "reason": "great"}]
        result = phase._merge_agent_decisions(gemini, claude)
        assert len(result) == 1
        assert result[0].decision == RetentionDecision.KEEP_PERMANENT

    def test_both_agree_delete(self, phase):
        gemini = [{"agent_id": "a1", "vote": "delete", "reason": "bad"}]
        claude = [{"agent_id": "a1", "vote": "delete", "reason": "useless"}]
        result = phase._merge_agent_decisions(gemini, claude)
        assert result[0].decision == RetentionDecision.DELETE

    def test_gemini_keep_claude_delete_keeps(self, phase):
        gemini = [{"agent_id": "a1", "vote": "keep_permanent", "reason": "useful"}]
        claude = [{"agent_id": "a1", "vote": "delete", "reason": "no"}]
        result = phase._merge_agent_decisions(gemini, claude)
        assert result[0].decision == RetentionDecision.KEEP_PERMANENT

    def test_claude_keep_gemini_delete_keeps(self, phase):
        gemini = [{"agent_id": "a1", "vote": "delete", "reason": "no"}]
        claude = [{"agent_id": "a1", "vote": "archive_knowledge", "reason": "save it"}]
        result = phase._merge_agent_decisions(gemini, claude)
        assert result[0].decision == RetentionDecision.ARCHIVE_KNOWLEDGE

    def test_different_keep_types_defaults_to_archive(self, phase):
        gemini = [{"agent_id": "a1", "vote": "keep_permanent", "reason": "r1"}]
        claude = [{"agent_id": "a1", "vote": "merge_into_existing", "reason": "r2"}]
        result = phase._merge_agent_decisions(gemini, claude)
        assert result[0].decision == RetentionDecision.ARCHIVE_KNOWLEDGE

    def test_agent_only_in_gemini(self, phase):
        gemini = [{"agent_id": "a1", "vote": "keep_permanent", "reason": "r"}]
        claude = []
        result = phase._merge_agent_decisions(gemini, claude)
        assert len(result) == 1
        # claude_vote defaults to DELETE; gemini=keep -> keeps
        assert result[0].decision == RetentionDecision.KEEP_PERMANENT

    def test_agent_only_in_claude(self, phase):
        gemini = []
        claude = [{"agent_id": "a1", "vote": "archive_knowledge", "reason": "r"}]
        result = phase._merge_agent_decisions(gemini, claude)
        assert len(result) == 1
        assert result[0].decision == RetentionDecision.ARCHIVE_KNOWLEDGE

    def test_multiple_agents(self, phase):
        gemini = [
            {"agent_id": "a1", "vote": "keep_permanent", "reason": "r1"},
            {"agent_id": "a2", "vote": "delete", "reason": "r2"},
        ]
        claude = [
            {"agent_id": "a1", "vote": "keep_permanent", "reason": "r3"},
            {"agent_id": "a2", "vote": "delete", "reason": "r4"},
        ]
        result = phase._merge_agent_decisions(gemini, claude)
        assert len(result) == 2
        by_id = {r.agent_id: r for r in result}
        assert by_id["a1"].decision == RetentionDecision.KEEP_PERMANENT
        assert by_id["a2"].decision == RetentionDecision.DELETE

    def test_invalid_vote_defaults_to_delete(self, phase):
        gemini = [{"agent_id": "a1", "vote": "INVALID_VALUE", "reason": "r"}]
        claude = [{"agent_id": "a1", "vote": "ALSO_INVALID", "reason": "r"}]
        result = phase._merge_agent_decisions(gemini, claude)
        assert result[0].decision == RetentionDecision.DELETE

    def test_missing_agent_id_skipped(self, phase):
        gemini = [{"vote": "keep_permanent", "reason": "r"}]
        claude = []
        result = phase._merge_agent_decisions(gemini, claude)
        assert len(result) == 0

    def test_empty_inputs(self, phase):
        result = phase._merge_agent_decisions([], [])
        assert result == []

    def test_gemini_and_claude_votes_recorded(self, phase):
        gemini = [{"agent_id": "a1", "vote": "keep_permanent", "reason": "r1"}]
        claude = [{"agent_id": "a1", "vote": "delete", "reason": "r2"}]
        result = phase._merge_agent_decisions(gemini, claude)
        assert result[0].gemini_vote == RetentionDecision.KEEP_PERMANENT
        assert result[0].claude_vote == RetentionDecision.DELETE


# =============================================================================
# 5. _merge_knowledge_entries
# =============================================================================


class TestMergeKnowledgeEntries:
    """Test knowledge entry merging and deduplication."""

    def test_merge_unique_entries(self, phase):
        gemini = [{"category": "pattern", "content": "Use caching", "usefulness": 0.9, "tags": ["perf"]}]
        claude = [{"category": "insight", "content": "Check auth first", "usefulness": 0.7, "tags": ["security"]}]
        result = phase._merge_knowledge_entries(gemini, claude)
        assert len(result) == 2

    def test_deduplication_by_content_prefix(self, phase):
        entry = {
            "category": "pattern",
            "content": "Always validate input data before processing",
            "usefulness": 0.8,
            "tags": [],
        }
        result = phase._merge_knowledge_entries([entry], [entry])
        assert len(result) == 1

    def test_empty_inputs(self, phase):
        result = phase._merge_knowledge_entries([], [])
        assert result == []

    def test_knowledge_entry_type(self, phase):
        entries = [{"category": "recipe", "content": "Step 1, 2, 3", "usefulness": 0.6, "tags": ["howto"]}]
        result = phase._merge_knowledge_entries(entries, [])
        assert isinstance(result[0], KnowledgeEntry)
        assert result[0].category == "recipe"
        assert result[0].usefulness_score == 0.6

    def test_defaults_for_missing_fields(self, phase):
        entries = [{"content": "Some knowledge"}]
        result = phase._merge_knowledge_entries(entries, [])
        assert result[0].category == "insight"
        assert result[0].usefulness_score == 0.5
        assert result[0].tags == []

    def test_source_task_set_to_hive_mind(self, phase):
        entries = [{"category": "pattern", "content": "X", "usefulness": 0.5}]
        result = phase._merge_knowledge_entries(entries, [])
        assert result[0].source_task == "hive_mind"


# =============================================================================
# 6. _apply_agent_decisions
# =============================================================================


class TestApplyAgentDecisions:
    """Test applying agent retention decisions to the registry."""

    def test_delete_deactivates_in_registry(self, phase, mock_agent_registry):
        decisions = [
            AgentRetention(
                agent_id="a1",
                decision=RetentionDecision.DELETE,
                reason="not needed",
                gemini_vote=RetentionDecision.DELETE,
                claude_vote=RetentionDecision.DELETE,
            )
        ]
        retained, deleted = phase._apply_agent_decisions(decisions)
        assert deleted == ["a1"]
        assert retained == []
        mock_agent_registry.deactivate_agent.assert_called_once_with("a1", reason="not needed")

    def test_keep_records_usage_in_registry(self, phase, mock_agent_registry):
        decisions = [
            AgentRetention(
                agent_id="a1",
                decision=RetentionDecision.KEEP_PERMANENT,
                reason="good agent",
                gemini_vote=RetentionDecision.KEEP_PERMANENT,
                claude_vote=RetentionDecision.KEEP_PERMANENT,
            )
        ]
        retained, deleted = phase._apply_agent_decisions(decisions)
        assert retained == ["a1"]
        assert deleted == []
        mock_agent_registry.record_usage.assert_called_once_with("a1", success=True)

    def test_archive_knowledge_retains(self, phase, mock_agent_registry):
        decisions = [
            AgentRetention(
                agent_id="a1",
                decision=RetentionDecision.ARCHIVE_KNOWLEDGE,
                reason="archive",
                gemini_vote=RetentionDecision.ARCHIVE_KNOWLEDGE,
                claude_vote=RetentionDecision.ARCHIVE_KNOWLEDGE,
            )
        ]
        retained, deleted = phase._apply_agent_decisions(decisions)
        assert retained == ["a1"]
        assert deleted == []

    def test_mixed_decisions(self, phase, mock_agent_registry):
        decisions = [
            AgentRetention(
                agent_id="a1",
                decision=RetentionDecision.KEEP_PERMANENT,
                reason="keep",
                gemini_vote=RetentionDecision.KEEP_PERMANENT,
                claude_vote=RetentionDecision.KEEP_PERMANENT,
            ),
            AgentRetention(
                agent_id="a2",
                decision=RetentionDecision.DELETE,
                reason="remove",
                gemini_vote=RetentionDecision.DELETE,
                claude_vote=RetentionDecision.DELETE,
            ),
        ]
        retained, deleted = phase._apply_agent_decisions(decisions)
        assert retained == ["a1"]
        assert deleted == ["a2"]

    def test_empty_decisions(self, phase):
        retained, deleted = phase._apply_agent_decisions([])
        assert retained == []
        assert deleted == []


# =============================================================================
# 7. _archive_knowledge
# =============================================================================


class TestArchiveKnowledge:
    """Test knowledge archival to RAG or context_manager fallback."""

    def test_archive_to_project_memory(self, phase, mock_project_memory):
        entries = [
            KnowledgeEntry(
                category="pattern",
                content="Cache API responses",
                source_task="hive_mind",
                usefulness_score=0.9,
                tags=["perf"],
            )
        ]
        count = phase._archive_knowledge(entries, "Build API")
        assert count == 1
        mock_project_memory.add_document.assert_called_once()
        call_kwargs = mock_project_memory.add_document.call_args
        assert "Cache API responses" in call_kwargs.kwargs.get("content", call_kwargs[1].get("content", ""))

    def test_fallback_to_context_manager_when_no_memory(self, phase_no_memory, mock_context_manager):
        entries = [
            KnowledgeEntry(
                category="insight",
                content="Use retry logic",
                source_task="hive_mind",
                usefulness_score=0.7,
                tags=["resilience"],
            )
        ]
        count = phase_no_memory._archive_knowledge(entries, "Retry task")
        assert count == 1
        mock_context_manager.add_insight.assert_called_once()

    def test_archive_multiple_entries(self, phase, mock_project_memory):
        entries = [
            KnowledgeEntry(category="pattern", content=f"Pattern {i}", source_task="hm", usefulness_score=0.5, tags=[])
            for i in range(5)
        ]
        count = phase._archive_knowledge(entries, "multi-task")
        assert count == 5
        assert mock_project_memory.add_document.call_count == 5

    def test_archive_handles_add_document_exception(self, phase, mock_project_memory):
        mock_project_memory.add_document.side_effect = RuntimeError("DB error")
        entries = [KnowledgeEntry(category="pattern", content="X", source_task="hm", usefulness_score=0.5, tags=[])]
        count = phase._archive_knowledge(entries, "task")
        assert count == 0

    def test_archive_empty_entries(self, phase):
        count = phase._archive_knowledge([], "task")
        assert count == 0

    def test_memory_without_add_document_method(self, phase):
        # If project_memory exists but lacks add_document, archived should be 0
        del phase.project_memory.add_document
        entries = [KnowledgeEntry(category="pattern", content="X", source_task="hm", usefulness_score=0.5, tags=[])]
        count = phase._archive_knowledge(entries, "task")
        assert count == 0


# =============================================================================
# 8. _create_minimal_result
# =============================================================================


class TestCreateMinimalResult:
    """Test budget-limited minimal result creation."""

    def test_minimal_result_structure(self, phase):
        result = phase._create_minimal_result("some task", True)
        assert isinstance(result, ConsolidationPhaseResult)
        assert result.user_decision == "skip"
        assert result.archived_to_rag == 0
        assert result.agents_retained == []
        assert result.agents_deleted == []

    def test_minimal_result_reflects_success(self, phase):
        result = phase._create_minimal_result("task", True)
        assert result.consolidation.task_success is True

    def test_minimal_result_reflects_failure(self, phase):
        result = phase._create_minimal_result("task", False)
        assert result.consolidation.task_success is False

    def test_minimal_result_low_confidence(self, phase):
        result = phase._create_minimal_result("task", True)
        assert result.consolidation.confidence_in_decisions == 0.3

    def test_minimal_result_empty_collections(self, phase):
        result = phase._create_minimal_result("task", True)
        assert result.consolidation.learned_patterns == []
        assert result.consolidation.learned_antipatterns == []
        assert result.consolidation.knowledge_to_archive == []
        assert result.consolidation.agents_retention == []

    def test_minimal_result_budget_limited_reflections(self, phase):
        result = phase._create_minimal_result("task", True)
        assert result.gemini_reflection == "Budget limited"
        assert result.claude_reflection == "Budget limited"


# =============================================================================
# 9. Full execute() flow
# =============================================================================


class TestExecuteFlow:
    """Test the full execute() method with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_execute_success_path(self, phase):
        """Full success path: reflect, debate, consolidate, archive."""
        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch("core.memory_pkg.skills.crystallizer.get_crystallizer", side_effect=ImportError),
            patch.dict(
                "sys.modules",
                {
                    "core.memory_pkg.skills.crystallizer": None,
                    "core.memory_pkg.memory.auto_memory": None,
                    "core.intelligence.reasoning.uncertainty_propagator": None,
                    "core.memory_pkg.skills.experience_distiller": None,
                },
            ),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {
                "gemini": "uuid-g",
                "claude": "uuid-c",
            }
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)

            assert isinstance(result, ConsolidationPhaseResult)
            assert result.user_decision == "accept_all"
            assert isinstance(result.consolidation, KnowledgeConsolidation)

    @pytest.mark.asyncio
    async def test_execute_calls_both_drivers(self, phase, mock_gemini, mock_claude):
        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            await phase.execute(**SAMPLE_EXECUTE_KWARGS)

            mock_gemini.invoke.assert_called_once()
            mock_claude.invoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_records_costs(self, phase, mock_cost_estimator):
        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            await phase.execute(**SAMPLE_EXECUTE_KWARGS)

            # Source uses record_tokens() if available (MagicMock has it), else record_cost()
            # Collect operation names from whichever method was actually called
            token_calls = [c[0][0] for c in mock_cost_estimator.record_tokens.call_args_list]
            cost_calls_list = [c[0][0] for c in mock_cost_estimator.record_cost.call_args_list]
            all_operations = token_calls + cost_calls_list
            # Reflection costs recorded via record_tokens or record_cost
            has_gemini_reflection = "reflection_gemini" in all_operations
            has_claude_reflection = "reflection_claude" in all_operations
            assert has_gemini_reflection, f"Expected reflection_gemini in {all_operations}"
            assert has_claude_reflection, f"Expected reflection_claude in {all_operations}"
            assert "decide_retention" in cost_calls_list
            assert "consolidate" in cost_calls_list

    @pytest.mark.asyncio
    async def test_execute_budget_limited_returns_minimal(self, phase, mock_cost_estimator):
        mock_cost_estimator.can_afford_multiple.return_value = False

        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)

            assert result.user_decision == "skip"
            assert result.consolidation.confidence_in_decisions == 0.3

    @pytest.mark.asyncio
    async def test_execute_gemini_failure_handled(self, phase, mock_gemini):
        mock_gemini.invoke = AsyncMock(side_effect=RuntimeError("Gemini down"))

        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)

            assert "Reflection failed" in result.gemini_reflection
            assert isinstance(result, ConsolidationPhaseResult)

    @pytest.mark.asyncio
    async def test_execute_claude_failure_handled(self, phase, mock_claude):
        mock_claude.invoke = AsyncMock(side_effect=RuntimeError("Claude down"))

        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)

            assert "Reflection failed" in result.claude_reflection

    @pytest.mark.asyncio
    async def test_execute_both_drivers_fail(self, phase, mock_gemini, mock_claude):
        mock_gemini.invoke = AsyncMock(side_effect=RuntimeError("G fail"))
        mock_claude.invoke = AsyncMock(side_effect=RuntimeError("C fail"))

        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)

            assert "Reflection failed" in result.gemini_reflection
            assert "Reflection failed" in result.claude_reflection

    @pytest.mark.asyncio
    async def test_execute_user_rejects_consolidation(self, phase, mock_user_handler):
        mock_user_handler.knowledge_consolidation.return_value = _make_user_response("reject")

        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)

            assert result.user_decision == "reject"
            assert result.archived_to_rag == 0
            assert result.agents_retained == []

    @pytest.mark.asyncio
    async def test_execute_user_selective_option(self, phase, mock_user_handler):
        mock_user_handler.knowledge_consolidation.return_value = _make_user_response("selective")

        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)

            # selective should still proceed with archival
            assert result.user_decision == "selective"

    @pytest.mark.asyncio
    async def test_execute_patterns_added_to_context_manager(self, phase, mock_context_manager):
        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            await phase.execute(**SAMPLE_EXECUTE_KWARGS)

            # Should have added at least one pattern insight and one antipattern insight
            insight_calls = mock_context_manager.add_insight.call_args_list
            [
                c.kwargs.get("category", c[1].get("category", "")) if c[1] else c.kwargs.get("category", "")
                for c in insight_calls
            ]
            # Flexible check: add_insight was called
            assert mock_context_manager.add_insight.call_count > 0

    @pytest.mark.asyncio
    async def test_execute_with_no_agents_spawned(self, phase):
        kwargs = {**SAMPLE_EXECUTE_KWARGS, "agents_spawned": []}

        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**kwargs)

            assert isinstance(result, ConsolidationPhaseResult)

    @pytest.mark.asyncio
    async def test_execute_failed_task(self, phase):
        kwargs = {**SAMPLE_EXECUTE_KWARGS, "success": False}

        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**kwargs)

            assert result.consolidation.task_success is False


# =============================================================================
# 10. _debate_consolidation
# =============================================================================


class TestDebateConsolidation:
    """Test the debate logic that merges two reflections."""

    @pytest.mark.asyncio
    async def test_merges_patterns_as_union(self, phase):
        gemini_json = _make_reflection_json(patterns=["p1", "p2"])
        claude_json = _make_reflection_json(patterns=["p2", "p3"])

        result = await phase._debate_consolidation(
            task="test",
            gemini_reflection=gemini_json,
            claude_reflection=claude_json,
            success=True,
        )
        assert set(result.learned_patterns) == {"p1", "p2", "p3"}

    @pytest.mark.asyncio
    async def test_merges_antipatterns_as_union(self, phase):
        gemini_json = _make_reflection_json(antipatterns=["a1"])
        claude_json = _make_reflection_json(antipatterns=["a2"])

        result = await phase._debate_consolidation(
            task="test",
            gemini_reflection=gemini_json,
            claude_reflection=claude_json,
            success=True,
        )
        assert set(result.learned_antipatterns) == {"a1", "a2"}

    @pytest.mark.asyncio
    async def test_merges_capabilities_as_union(self, phase):
        gemini_json = _make_reflection_json(capabilities=["cap1"])
        claude_json = _make_reflection_json(capabilities=["cap2"])

        result = await phase._debate_consolidation(
            task="test",
            gemini_reflection=gemini_json,
            claude_reflection=claude_json,
            success=True,
        )
        assert set(result.new_capabilities_identified) == {"cap1", "cap2"}

    @pytest.mark.asyncio
    async def test_confidence_is_average_satisfaction(self, phase):
        gemini_json = _make_reflection_json(satisfaction=0.6)
        claude_json = _make_reflection_json(satisfaction=0.8)

        result = await phase._debate_consolidation(
            task="test",
            gemini_reflection=gemini_json,
            claude_reflection=claude_json,
            success=True,
        )
        assert abs(result.confidence_in_decisions - 0.7) < 0.01

    @pytest.mark.asyncio
    async def test_task_success_passed_through(self, phase):
        gemini_json = _make_reflection_json()
        claude_json = _make_reflection_json()

        result = await phase._debate_consolidation(
            task="test",
            gemini_reflection=gemini_json,
            claude_reflection=claude_json,
            success=False,
        )
        assert result.task_success is False

    @pytest.mark.asyncio
    async def test_unparseable_reflections_handled(self, phase):
        result = await phase._debate_consolidation(
            task="test",
            gemini_reflection="Not JSON at all",
            claude_reflection="Also not JSON",
            success=True,
        )
        assert result.learned_patterns == []
        assert result.learned_antipatterns == []
        assert result.confidence_in_decisions == 0.5  # (0.5 + 0.5) / 2 default

    @pytest.mark.asyncio
    async def test_returns_knowledge_consolidation_type(self, phase):
        gemini_json = _make_reflection_json()
        claude_json = _make_reflection_json()

        result = await phase._debate_consolidation(
            task="test",
            gemini_reflection=gemini_json,
            claude_reflection=claude_json,
            success=True,
        )
        assert isinstance(result, KnowledgeConsolidation)

    @pytest.mark.asyncio
    async def test_tools_to_create_always_empty(self, phase):
        gemini_json = _make_reflection_json()
        claude_json = _make_reflection_json()

        result = await phase._debate_consolidation(
            task="test",
            gemini_reflection=gemini_json,
            claude_reflection=claude_json,
            success=True,
        )
        assert result.tools_to_create == []


# =============================================================================
# 11. V12.4 Integration: Skill Crystallizer (graceful degradation)
# =============================================================================


class TestV124SkillCrystallizer:
    """Test that skill crystallization catches exceptions gracefully."""

    @pytest.mark.asyncio
    async def test_crystallizer_import_error_swallowed(self, phase):
        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch.dict("sys.modules", {"core.skills.crystallizer": None}),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            # Should not raise
            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)
            assert isinstance(result, ConsolidationPhaseResult)

    @pytest.mark.asyncio
    async def test_crystallizer_runtime_error_swallowed(self, phase):
        mock_crystallizer = MagicMock()
        mock_crystallizer.detect_patterns.side_effect = RuntimeError("boom")

        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch(
                "core.memory_pkg.skills.crystallizer.get_crystallizer",
                return_value=mock_crystallizer,
            ),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)
            assert isinstance(result, ConsolidationPhaseResult)


# =============================================================================
# 12. V12.4 Integration: Principle Library (graceful degradation)
# =============================================================================


class TestV124PrincipleLibrary:
    """Test that principle extraction catches exceptions gracefully."""

    @pytest.mark.asyncio
    async def test_principle_library_import_error_swallowed(self, phase):
        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch(
                "core.intelligence.hive_mind.principle_library.get_principle_library",
                side_effect=ImportError("no module"),
            ),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)
            assert isinstance(result, ConsolidationPhaseResult)

    @pytest.mark.asyncio
    async def test_principle_library_add_principle_error_swallowed(self, phase):
        mock_lib = MagicMock()
        mock_lib.add_principle.side_effect = ValueError("bad principle")

        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch(
                "core.intelligence.hive_mind.principle_library.get_principle_library",
                return_value=mock_lib,
            ),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)
            assert isinstance(result, ConsolidationPhaseResult)


# =============================================================================
# 13. V12.4 Integration: AutoMemory (graceful degradation)
# =============================================================================


class TestV124AutoMemory:
    """Test that AutoMemory recording catches exceptions gracefully."""

    @pytest.mark.asyncio
    async def test_auto_memory_import_error_swallowed(self, phase):
        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch.dict("sys.modules", {"core.memory.auto_memory": None}),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)
            assert isinstance(result, ConsolidationPhaseResult)

    @pytest.mark.asyncio
    async def test_auto_memory_record_success_error_swallowed(self, phase):
        mock_mem = MagicMock()
        mock_mem.record_success.side_effect = RuntimeError("storage fail")

        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch(
                "core.memory_pkg.memory.auto_memory.get_auto_memory",
                return_value=mock_mem,
            ),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)
            assert isinstance(result, ConsolidationPhaseResult)

    @pytest.mark.asyncio
    async def test_auto_memory_record_failure_path(self, phase):
        mock_mem = MagicMock()

        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch(
                "core.memory_pkg.memory.auto_memory.get_auto_memory",
                return_value=mock_mem,
            ),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            kwargs = {**SAMPLE_EXECUTE_KWARGS, "success": False}
            result = await phase.execute(**kwargs)

            mock_mem.record_failure.assert_called_once()
            assert isinstance(result, ConsolidationPhaseResult)


# =============================================================================
# 14. V12.4 Integration: UncertaintyPropagator (graceful degradation)
# =============================================================================


class TestV124UncertaintyPropagator:
    """Test that UncertaintyPropagator reset catches exceptions gracefully."""

    @pytest.mark.asyncio
    async def test_uncertainty_propagator_import_error_swallowed(self, phase):
        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch.dict("sys.modules", {"core.intelligence.reasoning.uncertainty_propagator": None}),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)
            assert isinstance(result, ConsolidationPhaseResult)

    @pytest.mark.asyncio
    async def test_uncertainty_propagator_reset_error_swallowed(self, phase):
        mock_prop = MagicMock()
        mock_prop.reset_chain.side_effect = RuntimeError("reset fail")

        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch(
                "core.intelligence.reasoning.uncertainty_propagator.get_uncertainty_propagator",
                return_value=mock_prop,
            ),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)
            assert isinstance(result, ConsolidationPhaseResult)


# =============================================================================
# 15. V12.4 Integration: ExperienceDistiller (graceful degradation)
# =============================================================================


class TestV124ExperienceDistiller:
    """Test that ExperienceDistiller catches exceptions gracefully."""

    @pytest.mark.asyncio
    async def test_experience_distiller_import_error_swallowed(self, phase):
        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch.dict("sys.modules", {"core.skills.experience_distiller": None}),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)
            assert isinstance(result, ConsolidationPhaseResult)

    @pytest.mark.asyncio
    async def test_experience_distiller_distill_error_swallowed(self, phase):
        mock_dist = MagicMock()
        mock_dist.distill.side_effect = RuntimeError("distill fail")

        with (
            patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI,
            patch(
                "core.memory_pkg.skills.experience_distiller.get_experience_distiller",
                return_value=mock_dist,
            ),
        ):
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**SAMPLE_EXECUTE_KWARGS)
            assert isinstance(result, ConsolidationPhaseResult)


# =============================================================================
# 16. Reflection Helpers
# =============================================================================


class TestReflectWithDrivers:
    """Test _reflect_with_gemini and _reflect_with_claude."""

    @pytest.mark.asyncio
    async def test_reflect_with_gemini_returns_response(self, phase, mock_gemini):
        response = await phase._reflect_with_gemini("prompt", "session-123")
        # Source uses invoke() which returns DriverResponse; method returns response.content
        assert response == mock_gemini.invoke.return_value.content

    @pytest.mark.asyncio
    async def test_reflect_with_claude_returns_response(self, phase, mock_claude):
        response = await phase._reflect_with_claude("prompt", "session-456")
        assert response == mock_claude.invoke.return_value.content

    @pytest.mark.asyncio
    async def test_reflect_with_gemini_records_cost(self, phase, mock_gemini, mock_cost_estimator):
        # Ensure record_tokens is not on mock so record_cost branch is taken
        del mock_cost_estimator.record_tokens
        await phase._reflect_with_gemini("prompt", None)
        mock_cost_estimator.record_cost.assert_called()
        call_args = mock_cost_estimator.record_cost.call_args
        assert call_args[0][0] == "reflection_gemini"

    @pytest.mark.asyncio
    async def test_reflect_with_claude_records_cost(self, phase, mock_claude, mock_cost_estimator):
        # Ensure record_tokens is not on mock so record_cost branch is taken
        del mock_cost_estimator.record_tokens
        await phase._reflect_with_claude("prompt", None)
        mock_cost_estimator.record_cost.assert_called()
        call_args = mock_cost_estimator.record_cost.call_args
        assert call_args[0][0] == "reflection_claude"

    @pytest.mark.asyncio
    async def test_reflect_with_gemini_raises_on_error(self, phase, mock_gemini):
        mock_gemini.invoke = AsyncMock(side_effect=ConnectionError("offline"))
        with pytest.raises(ConnectionError):
            await phase._reflect_with_gemini("prompt", None)

    @pytest.mark.asyncio
    async def test_reflect_with_claude_raises_on_error(self, phase, mock_claude):
        mock_claude.invoke = AsyncMock(side_effect=TimeoutError("timeout"))
        with pytest.raises(TimeoutError):
            await phase._reflect_with_claude("prompt", None)

    @pytest.mark.asyncio
    async def test_reflect_passes_session_uuid(self, phase, mock_gemini):
        await phase._reflect_with_gemini("prompt", "my-session")
        call_kwargs = mock_gemini.invoke.call_args[1]
        assert call_kwargs.get("session_id") == "my-session"

    @pytest.mark.asyncio
    async def test_reflect_with_none_session(self, phase, mock_claude):
        await phase._reflect_with_claude("prompt", None)
        call_kwargs = mock_claude.invoke.call_args[1]
        assert call_kwargs.get("session_id") is None


# =============================================================================
# 17. Constructor
# =============================================================================


class TestConstructor:
    """Test KnowledgeConsolidationPhase initialization."""

    def test_stores_drivers(self, phase, mock_gemini, mock_claude):
        assert phase.gemini is mock_gemini
        assert phase.claude is mock_claude

    def test_stores_cost_estimator(self, phase, mock_cost_estimator):
        assert phase.cost_estimator is mock_cost_estimator

    def test_stores_context_manager(self, phase, mock_context_manager):
        assert phase.context_manager is mock_context_manager

    def test_stores_registry(self, phase, mock_agent_registry):
        assert phase.registry is mock_agent_registry

    def test_stores_user_handler(self, phase, mock_user_handler):
        assert phase.user_handler is mock_user_handler

    def test_stores_project_memory(self, phase, mock_project_memory):
        assert phase.project_memory is mock_project_memory

    def test_stores_task_id(self, phase):
        assert phase._task_id == "test-task-001"

    def test_generates_task_id_when_none(
        self,
        mock_gemini,
        mock_claude,
        mock_cost_estimator,
        mock_context_manager,
        mock_agent_registry,
        mock_user_handler,
    ):
        p = KnowledgeConsolidationPhase(
            gemini_driver=mock_gemini,
            claude_driver=mock_claude,
            cost_estimator=mock_cost_estimator,
            context_manager=mock_context_manager,
            agent_registry=mock_agent_registry,
            user_handler=mock_user_handler,
            task_id=None,
        )
        assert p._task_id is not None
        assert len(p._task_id) > 0

    def test_session_manager_defaults_to_none(self, phase):
        assert phase._session_manager is None

    def test_project_memory_defaults_to_none(self, phase_no_memory):
        assert phase_no_memory.project_memory is None


# =============================================================================
# 18. Edge Cases
# =============================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_merge_agent_decisions_missing_reason(self, phase):
        gemini = [{"agent_id": "a1", "vote": "keep_permanent"}]
        claude = []
        result = phase._merge_agent_decisions(gemini, claude)
        assert result[0].reason == ""

    def test_merge_knowledge_entries_empty_content(self, phase):
        entries = [{"category": "pattern", "content": "", "usefulness": 0.5}]
        result = phase._merge_knowledge_entries(entries, [])
        assert len(result) == 1
        assert result[0].content == ""

    def test_merge_knowledge_entries_very_long_content_dedupe(self, phase):
        long_content = "A" * 200
        entries = [{"category": "pattern", "content": long_content, "usefulness": 0.5}]
        result = phase._merge_knowledge_entries(entries, entries)
        # Same first 50 chars means dedup
        assert len(result) == 1

    def test_merge_knowledge_entries_different_long_prefixes(self, phase):
        e1 = [{"category": "pattern", "content": "A" * 60, "usefulness": 0.5}]
        e2 = [{"category": "pattern", "content": "B" * 60, "usefulness": 0.5}]
        result = phase._merge_knowledge_entries(e1, e2)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_execute_with_empty_approach(self, phase):
        kwargs = {**SAMPLE_EXECUTE_KWARGS, "approach": ""}

        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            # Should not raise even with empty approach
            result = await phase.execute(**kwargs)
            assert isinstance(result, ConsolidationPhaseResult)

    @pytest.mark.asyncio
    async def test_execute_with_empty_agents_used(self, phase):
        kwargs = {**SAMPLE_EXECUTE_KWARGS, "agents_used": []}

        with patch("core.intelligence.hive_mind.phases.phase_consolidation.HiveMindSessionIntegration") as MockSI:
            mock_si = MagicMock()
            mock_si.get_parallel_sessions.return_value = {"gemini": "g", "claude": "c"}
            MockSI.return_value = mock_si

            result = await phase.execute(**kwargs)
            assert isinstance(result, ConsolidationPhaseResult)

    def test_reflection_prompt_handles_zero_duration(self):
        formatted = REFLECTION_PROMPT.format(
            task="x",
            success="No",
            duration=0.0,
            steps_completed=0,
            issues_count=0,
            approach="none",
            agents_used="",
            agents_spawned="",
        )
        assert "0.0s" in formatted

    def test_archive_knowledge_document_format(self, phase, mock_project_memory):
        entries = [
            KnowledgeEntry(
                category="recipe",
                content="Step 1: Do X\nStep 2: Do Y",
                source_task="hive_mind",
                usefulness_score=0.85,
                tags=["tutorial", "api"],
            )
        ]
        phase._archive_knowledge(entries, "Build REST API")
        call_args = mock_project_memory.add_document.call_args
        content = call_args.kwargs.get("content", call_args[1].get("content", ""))
        assert "recipe" in content
        assert "85%" in content
        assert "tutorial" in content
        metadata = call_args.kwargs.get("metadata", call_args[1].get("metadata", {}))
        assert metadata["type"] == "hive_mind_knowledge"
        assert metadata["category"] == "recipe"
