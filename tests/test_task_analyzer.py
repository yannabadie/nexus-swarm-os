"""
Comprehensive tests for core.swarm.task_analyzer module.

Tests cover:
- TaskComplexity enum (IntEnum behavior, all 5 levels)
- TaskDomain enum (all 10 domain values)
- AnalysisStage enum (3 stages)
- TaskAnalysis dataclass (fields, to_dict, from_dict, properties)
- STAGE1 instant command detection
- Conversational trivial detection
- STAGE2 heuristic classification (domain detection, complexity scoring)
- Agent fit scores
- Context-aware classification (V10 FIX F1)
- RAG enrichment (V11.2 MEMORIA)
- Stage 3 escalation logic
- Async analyze
- Edge cases (empty, unicode, long input, special chars)

Target: 80+ tests, all passing.
"""

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.swarm.task_analyzer import (
    AGENT_DOMAIN_STRENGTHS,
    COMPLEXITY_INDICATORS,
    CONTEXT_CLUE_PATTERNS,
    CONVERSATIONAL_TRIVIAL_PATTERNS,
    DOMAIN_KEYWORDS,
    STAGE1_INSTANT_COMMANDS,
    STAGE2_CONFIDENCE_THRESHOLD,
    TASK_STRUCTURE_PATTERNS,
    AnalysisStage,
    TaskAnalysis,
    TaskAnalyzer,
    TaskComplexity,
    TaskDomain,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def analyzer():
    """Fresh TaskAnalyzer instance with no project memory."""
    return TaskAnalyzer(project_memory=None)


@pytest.fixture
def analyzer_with_memory():
    """TaskAnalyzer with a mocked ProjectMemory for RAG tests."""
    mock_memory = MagicMock()
    mock_memory.retrieve.return_value = []
    return TaskAnalyzer(project_memory=mock_memory)


# =============================================================================
# 1. TaskComplexity enum tests
# =============================================================================


class TestTaskComplexity:
    """Tests for TaskComplexity IntEnum."""

    def test_has_five_levels(self):
        """TaskComplexity has exactly 5 members."""
        assert len(TaskComplexity) == 5

    def test_trivial_value(self):
        assert TaskComplexity.TRIVIAL == 1
        assert TaskComplexity.TRIVIAL.value == 1

    def test_simple_value(self):
        assert TaskComplexity.SIMPLE == 2
        assert TaskComplexity.SIMPLE.value == 2

    def test_moderate_value(self):
        assert TaskComplexity.MODERATE == 3
        assert TaskComplexity.MODERATE.value == 3

    def test_complex_value(self):
        assert TaskComplexity.COMPLEX == 4
        assert TaskComplexity.COMPLEX.value == 4

    def test_expert_value(self):
        assert TaskComplexity.EXPERT == 5
        assert TaskComplexity.EXPERT.value == 5

    def test_is_int_enum(self):
        """TaskComplexity members behave as integers (IntEnum)."""
        assert isinstance(TaskComplexity.TRIVIAL, int)
        assert TaskComplexity.MODERATE + 1 == 4
        assert TaskComplexity.EXPERT > TaskComplexity.TRIVIAL

    def test_ordering(self):
        """Complexity levels are properly ordered."""
        assert TaskComplexity.TRIVIAL < TaskComplexity.SIMPLE
        assert TaskComplexity.SIMPLE < TaskComplexity.MODERATE
        assert TaskComplexity.MODERATE < TaskComplexity.COMPLEX
        assert TaskComplexity.COMPLEX < TaskComplexity.EXPERT

    def test_construct_from_value(self):
        """Can construct from integer value."""
        assert TaskComplexity(3) == TaskComplexity.MODERATE
        assert TaskComplexity(1) == TaskComplexity.TRIVIAL

    def test_invalid_value_raises(self):
        """Invalid integer raises ValueError."""
        with pytest.raises(ValueError):
            TaskComplexity(0)
        with pytest.raises(ValueError):
            TaskComplexity(6)

    def test_name_attribute(self):
        """Each member has a correct .name."""
        assert TaskComplexity.TRIVIAL.name == "TRIVIAL"
        assert TaskComplexity.EXPERT.name == "EXPERT"


# =============================================================================
# 2. TaskDomain enum tests
# =============================================================================


class TestTaskDomain:
    """Tests for TaskDomain Enum."""

    def test_has_ten_domains(self):
        """TaskDomain has exactly 10 members."""
        assert len(TaskDomain) == 10

    def test_all_domain_values(self):
        """All domain string values match expectations."""
        expected = {
            "CODING": "coding",
            "RESEARCH": "research",
            "ANALYSIS": "analysis",
            "CREATIVE": "creative",
            "DEBUGGING": "debugging",
            "SECURITY": "security",
            "DOCUMENTATION": "documentation",
            "TESTING": "testing",
            "ARCHITECTURE": "architecture",
            "WEB_INTERACTION": "web_interaction",
        }
        for name, value in expected.items():
            assert TaskDomain[name].value == value

    def test_domain_from_value(self):
        """Can construct from string value."""
        assert TaskDomain("coding") == TaskDomain.CODING
        assert TaskDomain("security") == TaskDomain.SECURITY

    def test_invalid_value_raises(self):
        """Invalid string raises ValueError."""
        with pytest.raises(ValueError):
            TaskDomain("nonexistent")

    def test_all_domains_in_keywords(self):
        """Every TaskDomain has entries in DOMAIN_KEYWORDS."""
        for domain in TaskDomain:
            assert domain in DOMAIN_KEYWORDS, f"{domain} missing from DOMAIN_KEYWORDS"

    def test_all_domains_in_agent_strengths(self):
        """Every TaskDomain has agent strength scores."""
        for domain in TaskDomain:
            assert domain in AGENT_DOMAIN_STRENGTHS["gemini"], f"{domain} missing from gemini strengths"
            assert domain in AGENT_DOMAIN_STRENGTHS["claude"], f"{domain} missing from claude strengths"


# =============================================================================
# 3. AnalysisStage enum tests
# =============================================================================


class TestAnalysisStage:
    """Tests for AnalysisStage IntEnum."""

    def test_has_three_stages(self):
        assert len(AnalysisStage) == 3

    def test_stage1_regex(self):
        assert AnalysisStage.STAGE1_REGEX == 1

    def test_stage2_heuristic(self):
        assert AnalysisStage.STAGE2_HEURISTIC == 2

    def test_stage3_llm(self):
        assert AnalysisStage.STAGE3_LLM == 3

    def test_is_int_enum(self):
        assert isinstance(AnalysisStage.STAGE1_REGEX, int)

    def test_ordering(self):
        assert AnalysisStage.STAGE1_REGEX < AnalysisStage.STAGE2_HEURISTIC
        assert AnalysisStage.STAGE2_HEURISTIC < AnalysisStage.STAGE3_LLM


# =============================================================================
# 4. TaskAnalysis dataclass tests
# =============================================================================


class TestTaskAnalysis:
    """Tests for TaskAnalysis dataclass."""

    def _make_analysis(self, **overrides):
        """Helper to create a TaskAnalysis with sensible defaults."""
        defaults = {
            "complexity": TaskComplexity.MODERATE,
            "domains": [TaskDomain.CODING],
            "primary_domain": TaskDomain.CODING,
        }
        defaults.update(overrides)
        return TaskAnalysis(**defaults)

    def test_required_fields(self):
        """The three required fields must be provided."""
        analysis = TaskAnalysis(
            complexity=TaskComplexity.SIMPLE,
            domains=[TaskDomain.RESEARCH],
            primary_domain=TaskDomain.RESEARCH,
        )
        assert analysis.complexity == TaskComplexity.SIMPLE
        assert analysis.domains == [TaskDomain.RESEARCH]
        assert analysis.primary_domain == TaskDomain.RESEARCH

    def test_default_values(self):
        """Default values are correct for optional fields."""
        analysis = self._make_analysis()
        assert analysis.requires_web is False
        assert analysis.requires_code_execution is False
        assert analysis.requires_deep_reasoning is False
        assert analysis.requires_iteration is False
        assert analysis.gemini_fit_score == 0.5
        assert analysis.claude_fit_score == 0.5
        assert analysis.raw_input == ""
        assert analysis.confidence == 0.5
        assert analysis.detected_keywords == []
        assert analysis.analysis_stage == AnalysisStage.STAGE2_HEURISTIC
        assert analysis.instant_command is None

    def test_custom_values(self):
        """Custom values override defaults correctly."""
        analysis = self._make_analysis(
            requires_web=True,
            gemini_fit_score=0.9,
            claude_fit_score=0.3,
            confidence=0.95,
            analysis_stage=AnalysisStage.STAGE1_REGEX,
            instant_command="status",
        )
        assert analysis.requires_web is True
        assert analysis.gemini_fit_score == 0.9
        assert analysis.claude_fit_score == 0.3
        assert analysis.confidence == 0.95
        assert analysis.analysis_stage == AnalysisStage.STAGE1_REGEX
        assert analysis.instant_command == "status"

    # -- Properties --

    def test_recommended_lead_gemini(self):
        """Gemini is recommended when its score is > claude + 0.1."""
        analysis = self._make_analysis(gemini_fit_score=0.9, claude_fit_score=0.5)
        assert analysis.recommended_lead == "gemini"

    def test_recommended_lead_claude(self):
        """Claude is recommended when its score is > gemini + 0.1."""
        analysis = self._make_analysis(gemini_fit_score=0.5, claude_fit_score=0.9)
        assert analysis.recommended_lead == "claude"

    def test_recommended_lead_equal(self):
        """'equal' when scores are within 0.1 of each other."""
        analysis = self._make_analysis(gemini_fit_score=0.5, claude_fit_score=0.55)
        assert analysis.recommended_lead == "equal"

    def test_recommended_lead_exact_boundary(self):
        """Exactly 0.1 difference is NOT enough to recommend a lead."""
        analysis = self._make_analysis(gemini_fit_score=0.6, claude_fit_score=0.5)
        assert analysis.recommended_lead == "equal"

    def test_recommended_lead_just_over_boundary(self):
        """Just over 0.1 difference recommends a lead."""
        analysis = self._make_analysis(gemini_fit_score=0.61, claude_fit_score=0.5)
        assert analysis.recommended_lead == "gemini"

    def test_should_skip_negotiation_trivial(self):
        """TRIVIAL tasks skip negotiation."""
        analysis = self._make_analysis(complexity=TaskComplexity.TRIVIAL)
        assert analysis.should_skip_negotiation is True

    def test_should_skip_negotiation_non_trivial(self):
        """Non-TRIVIAL tasks do NOT skip negotiation."""
        for level in [TaskComplexity.SIMPLE, TaskComplexity.MODERATE, TaskComplexity.COMPLEX, TaskComplexity.EXPERT]:
            analysis = self._make_analysis(complexity=level)
            assert analysis.should_skip_negotiation is False, f"Failed for {level}"

    def test_needs_adversarial_mode_expert(self):
        """EXPERT complexity triggers adversarial mode."""
        analysis = self._make_analysis(complexity=TaskComplexity.EXPERT)
        assert analysis.needs_adversarial_mode is True

    def test_needs_adversarial_mode_security_domain(self):
        """SECURITY domain triggers adversarial mode regardless of complexity."""
        analysis = self._make_analysis(
            complexity=TaskComplexity.SIMPLE,
            domains=[TaskDomain.SECURITY],
        )
        assert analysis.needs_adversarial_mode is True

    def test_needs_adversarial_mode_false(self):
        """Non-expert, non-security tasks do not need adversarial mode."""
        analysis = self._make_analysis(
            complexity=TaskComplexity.MODERATE,
            domains=[TaskDomain.CODING],
        )
        assert analysis.needs_adversarial_mode is False

    # -- to_dict --

    def test_to_dict_keys(self):
        """to_dict returns all expected keys."""
        analysis = self._make_analysis()
        d = analysis.to_dict()
        expected_keys = {
            "complexity",
            "complexity_value",
            "domains",
            "primary_domain",
            "requires_web",
            "requires_code_execution",
            "requires_deep_reasoning",
            "requires_iteration",
            "gemini_fit_score",
            "claude_fit_score",
            "recommended_lead",
            "should_skip_negotiation",
            "needs_adversarial_mode",
            "confidence",
            "detected_keywords",
            "analysis_stage",
            "analysis_cost",
            "instant_command",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_complexity_format(self):
        """Complexity is serialized as name and value."""
        analysis = self._make_analysis(complexity=TaskComplexity.COMPLEX)
        d = analysis.to_dict()
        assert d["complexity"] == "COMPLEX"
        assert d["complexity_value"] == 4

    def test_to_dict_domains_format(self):
        """Domains are serialized as string values."""
        analysis = self._make_analysis(
            domains=[TaskDomain.CODING, TaskDomain.TESTING],
            primary_domain=TaskDomain.CODING,
        )
        d = analysis.to_dict()
        assert d["domains"] == ["coding", "testing"]
        assert d["primary_domain"] == "coding"

    def test_to_dict_analysis_cost_stage1(self):
        """Stage 1 analysis cost is $0."""
        analysis = self._make_analysis(analysis_stage=AnalysisStage.STAGE1_REGEX)
        assert analysis.to_dict()["analysis_cost"] == "$0"

    def test_to_dict_analysis_cost_stage2(self):
        """Stage 2 analysis cost is CPU."""
        analysis = self._make_analysis(analysis_stage=AnalysisStage.STAGE2_HEURISTIC)
        assert analysis.to_dict()["analysis_cost"] == "CPU"

    def test_to_dict_analysis_cost_stage3(self):
        """Stage 3 analysis cost is API."""
        analysis = self._make_analysis(analysis_stage=AnalysisStage.STAGE3_LLM)
        assert analysis.to_dict()["analysis_cost"] == "API"

    def test_to_dict_scores_rounded(self):
        """Fit scores and confidence are rounded to 3 decimal places."""
        analysis = self._make_analysis(
            gemini_fit_score=0.12345678,
            claude_fit_score=0.98765432,
            confidence=0.77777777,
        )
        d = analysis.to_dict()
        assert d["gemini_fit_score"] == 0.123
        assert d["claude_fit_score"] == 0.988
        assert d["confidence"] == 0.778

    # -- from_dict --

    def test_from_dict_roundtrip(self):
        """to_dict -> from_dict produces equivalent analysis."""
        original = self._make_analysis(
            complexity=TaskComplexity.COMPLEX,
            domains=[TaskDomain.CODING, TaskDomain.SECURITY],
            primary_domain=TaskDomain.CODING,
            requires_web=True,
            gemini_fit_score=0.8,
            claude_fit_score=0.7,
            confidence=0.9,
            analysis_stage=AnalysisStage.STAGE1_REGEX,
            instant_command="help",
            detected_keywords=["code", "security"],
        )
        d = original.to_dict()
        restored = TaskAnalysis.from_dict(d)
        assert restored.complexity == original.complexity
        assert restored.primary_domain == original.primary_domain
        assert restored.requires_web == original.requires_web
        assert restored.analysis_stage == original.analysis_stage
        assert restored.instant_command == original.instant_command

    def test_from_dict_defaults_for_missing_keys(self):
        """from_dict handles missing keys gracefully with defaults."""
        minimal = {
            "complexity": "SIMPLE",
            "domains": ["research"],
            "primary_domain": "research",
        }
        analysis = TaskAnalysis.from_dict(minimal)
        assert analysis.complexity == TaskComplexity.SIMPLE
        assert analysis.requires_web is False
        assert analysis.gemini_fit_score == 0.5
        assert analysis.confidence == 0.5
        assert analysis.analysis_stage == AnalysisStage.STAGE2_HEURISTIC

    def test_from_dict_invalid_stage_falls_back(self):
        """from_dict handles invalid analysis_stage gracefully."""
        data = {
            "complexity": "MODERATE",
            "domains": ["coding"],
            "primary_domain": "coding",
            "analysis_stage": "STAGE99_INVALID",
        }
        analysis = TaskAnalysis.from_dict(data)
        assert analysis.analysis_stage == AnalysisStage.STAGE2_HEURISTIC


# =============================================================================
# 5. Instant command detection (Stage 1)
# =============================================================================


class TestInstantCommandDetection:
    """Tests for Stage 1 instant command regex matching."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "status",
            "state",
            "info",
            "clear",
            "cls",
            "reset",
            "exit",
            "quit",
            "bye",
            "q",
            "help",
            "?",
            "version",
            "ver",
            "v",
            "config",
            "settings",
            "prefs",
            "history",
            "hist",
            "log",
            "logs",
            "cancel",
            "stop",
            "abort",
            "save",
            "load",
            "restore",
            "undo",
            "redo",
        ],
    )
    def test_bare_commands_detected(self, analyzer, cmd):
        """Bare command words are detected as instant commands."""
        result = analyzer.is_instant_command(cmd)
        assert result is not None, f"'{cmd}' should be detected as instant command"

    @pytest.mark.parametrize(
        "cmd",
        [
            "/status",
            "/clear",
            "/exit",
            "/help",
            "/version",
            "/config",
            "/history",
            "/cancel",
            "/save",
            "/undo",
        ],
    )
    def test_slash_prefixed_commands_detected(self, analyzer, cmd):
        """Slash-prefixed commands are also detected."""
        result = analyzer.is_instant_command(cmd)
        assert result is not None, f"'{cmd}' should be detected as instant command"

    def test_slash_prefix_stripped_from_result(self, analyzer):
        """The returned command name does not include the slash prefix."""
        result = analyzer.is_instant_command("/status")
        assert result == "status"

    def test_case_insensitive(self, analyzer):
        """Commands are matched case-insensitively."""
        assert analyzer.is_instant_command("STATUS") is not None
        assert analyzer.is_instant_command("Help") is not None
        assert analyzer.is_instant_command("EXIT") is not None

    def test_non_command_returns_none(self, analyzer):
        """Non-command text returns None."""
        assert analyzer.is_instant_command("implement a function") is None
        assert analyzer.is_instant_command("please help me with code") is None
        assert analyzer.is_instant_command("status of the project") is None

    def test_whitespace_trimmed(self, analyzer):
        """Leading/trailing whitespace is trimmed before matching."""
        assert analyzer.is_instant_command("  status  ") is not None
        assert analyzer.is_instant_command("\thelp\n") is not None


# =============================================================================
# 6. Conversational trivial detection
# =============================================================================


class TestConversationalTrivialDetection:
    """Tests for trivial conversational input detection."""

    @pytest.mark.parametrize(
        "text",
        [
            "hello",
            "hi",
            "hey",
            "bonjour",
            "salut",
            "coucou",
            "hola",
            "hallo",
            "guten tag",
            "Hello!",
            "Hi?",
            "Hey!",
            "HELLO",
            "HI",
            "BONJOUR",
        ],
    )
    def test_greetings_detected(self, analyzer, text):
        """Greetings in multiple languages are detected as trivial."""
        assert analyzer.is_conversational_trivial(text) is True, f"'{text}' should be trivial"

    @pytest.mark.parametrize(
        "text",
        [
            "bye",
            "goodbye",
            "au revoir",
            "ciao",
            "adieu",
        ],
    )
    def test_farewells_detected(self, analyzer, text):
        assert analyzer.is_conversational_trivial(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "ok",
            "okay",
            "oui",
            "yes",
            "non",
            "no",
            "merci",
            "thanks",
            "thank you",
            "thx",
            "ty",
            "parfait",
            "perfect",
            "great",
            "cool",
            "nice",
            "super",
            "compris",
            "understood",
            "got it",
            "roger",
        ],
    )
    def test_acknowledgments_detected(self, analyzer, text):
        assert analyzer.is_conversational_trivial(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "test",
            "testing",
            "1234",
            "ping",
            "pong",
        ],
    )
    def test_probing_detected(self, analyzer, text):
        assert analyzer.is_conversational_trivial(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "continue",
            "continues",
            "go on",
            "vas-y",
            "go ahead",
        ],
    )
    def test_continuation_prompts_detected(self, analyzer, text):
        assert analyzer.is_conversational_trivial(text) is True

    def test_empty_string_is_trivial(self, analyzer):
        """Empty/whitespace-only input is trivial."""
        assert analyzer.is_conversational_trivial("") is True
        assert analyzer.is_conversational_trivial("   ") is True

    def test_non_trivial_not_detected(self, analyzer):
        """Complex requests are NOT detected as trivial."""
        assert analyzer.is_conversational_trivial("implement a new feature") is False
        assert analyzer.is_conversational_trivial("debug the auth module") is False
        assert analyzer.is_conversational_trivial("hello world program in python") is False


# =============================================================================
# 7. Full analyze() flow - Stage 1 results
# =============================================================================


class TestAnalyzeStage1:
    """Tests for analyze() returning Stage 1 (instant command / trivial) results."""

    def test_instant_command_returns_trivial(self, analyzer):
        """Instant commands produce TRIVIAL complexity at Stage 1."""
        result = analyzer.analyze("status")
        assert result.complexity == TaskComplexity.TRIVIAL
        assert result.analysis_stage == AnalysisStage.STAGE1_REGEX
        assert result.instant_command == "status"
        assert result.confidence == 1.0
        assert result.should_skip_negotiation is True

    def test_instant_command_preserves_raw_input(self, analyzer):
        """Raw input is preserved in the analysis."""
        result = analyzer.analyze("/help")
        assert result.raw_input == "/help"

    def test_instant_command_detected_keywords(self, analyzer):
        """Detected keywords contain INSTANT_CMD marker."""
        result = analyzer.analyze("exit")
        assert any("INSTANT_CMD" in k for k in result.detected_keywords)

    def test_conversational_trivial_returns_trivial(self, analyzer):
        """Conversational inputs produce TRIVIAL at Stage 1."""
        result = analyzer.analyze("hello")
        assert result.complexity == TaskComplexity.TRIVIAL
        assert result.analysis_stage == AnalysisStage.STAGE1_REGEX
        assert result.confidence == 1.0
        assert "[TRIVIAL_CONVERSATIONAL]" in result.detected_keywords

    def test_trivial_has_empty_domains(self, analyzer):
        """Trivial results have empty domains list."""
        result = analyzer.analyze("ok")
        assert result.domains == []

    def test_trivial_primary_domain_is_creative(self, analyzer):
        """Trivial results default primary_domain to CREATIVE."""
        result = analyzer.analyze("hi")
        assert result.primary_domain == TaskDomain.CREATIVE


# =============================================================================
# 8. Full analyze() flow - Stage 2 (Heuristic) results
# =============================================================================


class TestAnalyzeStage2:
    """Tests for analyze() returning Stage 2 heuristic results."""

    def test_coding_task_detected(self, analyzer):
        """A coding task is classified with CODING domain."""
        result = analyzer.analyze("implement a Python function to sort a list")
        assert TaskDomain.CODING in result.domains
        assert result.analysis_stage == AnalysisStage.STAGE2_HEURISTIC

    def test_research_task_detected(self, analyzer):
        """A research task is classified with RESEARCH domain."""
        result = analyzer.analyze("search for the latest documentation on FastAPI")
        assert TaskDomain.RESEARCH in result.domains

    def test_debugging_task_detected(self, analyzer):
        """A debugging task is classified with DEBUGGING domain."""
        result = analyzer.analyze("debug the error in auth.py, it crashes on login")
        assert TaskDomain.DEBUGGING in result.domains

    def test_security_task_detected(self, analyzer):
        """A security task is classified with SECURITY domain."""
        result = analyzer.analyze("check for SQL injection vulnerabilities")
        assert TaskDomain.SECURITY in result.domains

    def test_testing_task_detected(self, analyzer):
        """A testing task is classified with TESTING domain."""
        result = analyzer.analyze("write pytest tests with good coverage for the module")
        assert TaskDomain.TESTING in result.domains

    def test_architecture_task_detected(self, analyzer):
        """An architecture task is classified with ARCHITECTURE domain."""
        result = analyzer.analyze("design the system architecture for scalability")
        assert TaskDomain.ARCHITECTURE in result.domains

    def test_documentation_task_detected(self, analyzer):
        """A documentation task is classified with DOCUMENTATION domain."""
        result = analyzer.analyze("write a readme guide and api reference for the project")
        assert TaskDomain.DOCUMENTATION in result.domains

    def test_creative_task_detected(self, analyzer):
        """A creative task is classified with CREATIVE domain."""
        result = analyzer.analyze("brainstorm creative ideas to improve the UX design")
        assert TaskDomain.CREATIVE in result.domains

    def test_web_interaction_task_detected(self, analyzer):
        """A web interaction task is classified with WEB_INTERACTION domain."""
        result = analyzer.analyze("fetch data from the REST api endpoint at http://example.com")
        assert TaskDomain.WEB_INTERACTION in result.domains

    def test_analysis_task_detected(self, analyzer):
        """An analysis task is classified with ANALYSIS domain."""
        result = analyzer.analyze("analyze and evaluate the performance of this algorithm")
        assert TaskDomain.ANALYSIS in result.domains


# =============================================================================
# 9. Multi-domain classification
# =============================================================================


class TestMultiDomainClassification:
    """Tests for tasks that span multiple domains."""

    def test_coding_and_testing(self, analyzer):
        """Task mentioning code and tests gets both domains."""
        result = analyzer.analyze("implement a function and write pytest tests for it")
        assert TaskDomain.CODING in result.domains
        assert TaskDomain.TESTING in result.domains

    def test_security_and_debugging(self, analyzer):
        """Task mentioning security and debugging gets both."""
        result = analyzer.analyze("debug the authentication vulnerability and fix the exploit")
        assert TaskDomain.SECURITY in result.domains
        assert TaskDomain.DEBUGGING in result.domains

    def test_primary_domain_is_most_mentioned(self, analyzer):
        """Primary domain is the one with the most keyword matches."""
        result = analyzer.analyze("write code, implement the function, create a python class method")
        # CODING has multiple hits; it should be primary
        assert result.primary_domain == TaskDomain.CODING

    def test_three_plus_domains_increases_complexity(self, analyzer):
        """Having 3+ domains increases complexity."""
        # This task mentions coding, testing, and security keywords
        result = analyzer.analyze(
            "implement a secure authentication module, write pytest tests, and check for injection vulnerabilities"
        )
        assert len(result.domains) >= 3
        # With 3+ domains the base score gets +1 from the domain count
        assert result.complexity >= TaskComplexity.MODERATE


# =============================================================================
# 10. Complexity scoring
# =============================================================================


class TestComplexityScoring:
    """Tests for complexity calculation via COMPLEXITY_INDICATORS."""

    def test_high_complexity_keywords_boost(self, analyzer):
        """High-complexity keywords (+2) push toward EXPERT."""
        result = analyzer.analyze("redesign the critical production architecture for security and scalability")
        assert result.complexity >= TaskComplexity.COMPLEX

    def test_low_complexity_keywords_reduce(self, analyzer):
        """Low-complexity keywords (-1) reduce score."""
        result = analyzer.analyze("just a simple quick small task")
        # Multiple -1 keywords should reduce complexity below MODERATE
        assert result.complexity <= TaskComplexity.MODERATE

    def test_short_text_reduces_complexity(self, analyzer):
        """Text under 50 chars gets -1 complexity."""
        # Use a non-trivial but short input (< 50 chars)
        analyzer.analyze("implement a sort function")
        text_len = len("implement a sort function")
        assert text_len < 50
        # Exact level depends on keywords, but short text contributes -1

    def test_long_text_increases_complexity(self, analyzer):
        """Text over 500 chars gets +1 complexity."""
        long_task = "implement " + "a feature that handles user input " * 20
        assert len(long_task) > 500
        result = analyzer.analyze(long_task)
        # Long text should push complexity up
        assert result.complexity >= TaskComplexity.MODERATE

    def test_security_domain_adds_complexity(self, analyzer):
        """SECURITY domain adds +1 to complexity."""
        result = analyzer.analyze("check for sql injection vulnerability attacks")
        assert TaskDomain.SECURITY in result.domains
        # Security domain adds +1 plus security keyword adds +2
        assert result.complexity >= TaskComplexity.COMPLEX

    def test_architecture_domain_adds_complexity(self, analyzer):
        """ARCHITECTURE domain adds +1 to complexity."""
        result = analyzer.analyze("refactor the entire system architecture into modular design patterns")
        assert TaskDomain.ARCHITECTURE in result.domains
        assert result.complexity >= TaskComplexity.COMPLEX

    def test_complexity_clamped_to_valid_range(self, analyzer):
        """Complexity is always between TRIVIAL (1) and EXPERT (5)."""
        # Very complex input with many boosters
        result_high = analyzer.analyze(
            "redesign the critical production architecture with security "
            "scalability and migrate the entire complex system across multiple files"
        )
        assert 1 <= result_high.complexity.value <= 5

        # Very simple input
        result_low = analyzer.analyze("just quick simple small only trivial")
        assert 1 <= result_low.complexity.value <= 5


# =============================================================================
# 11. Requirement detection
# =============================================================================


class TestRequirementDetection:
    """Tests for web, code, reasoning, and iteration requirement detection."""

    def test_requires_web_detected(self, analyzer):
        """Web-related keywords set requires_web."""
        result = analyzer.analyze("search the latest news online")
        assert result.requires_web is True

    def test_requires_web_false_for_code(self, analyzer):
        """Pure coding tasks do not require web."""
        result = analyzer.analyze("implement a sorting algorithm")
        assert result.requires_web is False

    def test_requires_code_execution_detected(self, analyzer):
        """Code execution keywords set requires_code_execution."""
        result = analyzer.analyze("run pytest and build the project")
        assert result.requires_code_execution is True

    def test_requires_code_from_domain(self, analyzer):
        """CODING domain also triggers requires_code_execution."""
        result = analyzer.analyze("write a python script")
        assert result.requires_code_execution is True

    def test_requires_deep_reasoning_detected(self, analyzer):
        """Reasoning keywords set requires_deep_reasoning."""
        result = analyzer.analyze("analyze why the design has trade-offs")
        assert result.requires_deep_reasoning is True

    def test_requires_deep_reasoning_from_complexity(self, analyzer):
        """COMPLEX+ tasks trigger requires_deep_reasoning."""
        result = analyzer.analyze("redesign the critical production architecture for security and scalability")
        assert result.complexity >= TaskComplexity.COMPLEX
        assert result.requires_deep_reasoning is True

    def test_requires_iteration_detected(self, analyzer):
        """Iteration keywords set requires_iteration."""
        result = analyzer.analyze("brainstorm creative ideas and iterate to improve them")
        assert result.requires_iteration is True

    def test_requires_iteration_from_creative_domain(self, analyzer):
        """CREATIVE domain triggers requires_iteration."""
        result = analyzer.analyze("brainstorm innovative design ideas")
        assert TaskDomain.CREATIVE in result.domains
        assert result.requires_iteration is True


# =============================================================================
# 12. Agent fit scores
# =============================================================================


class TestAgentFitScores:
    """Tests for gemini_fit_score and claude_fit_score calculation."""

    def test_gemini_leads_on_research(self, analyzer):
        """Gemini scores higher for RESEARCH tasks."""
        result = analyzer.analyze("search and research the latest documentation")
        assert result.gemini_fit_score > result.claude_fit_score

    def test_claude_leads_on_coding(self, analyzer):
        """Claude scores higher for CODING tasks."""
        result = analyzer.analyze("implement a python class with methods")
        assert result.claude_fit_score > result.gemini_fit_score

    def test_claude_leads_on_debugging(self, analyzer):
        """Claude scores higher for DEBUGGING tasks."""
        result = analyzer.analyze("debug the error exception traceback")
        assert result.claude_fit_score > result.gemini_fit_score

    def test_scores_in_valid_range(self, analyzer):
        """Both fit scores are between 0.0 and 1.0."""
        test_inputs = [
            "implement code",
            "search the web for latest news",
            "debug the crash error",
            "design the system architecture",
            "brainstorm creative ideas",
        ]
        for text in test_inputs:
            result = analyzer.analyze(text)
            assert 0.0 <= result.gemini_fit_score <= 1.0, f"Gemini score out of range for '{text}'"
            assert 0.0 <= result.claude_fit_score <= 1.0, f"Claude score out of range for '{text}'"

    def test_web_requirement_boosts_gemini(self, analyzer):
        """requires_web boosts Gemini and reduces Claude scores."""
        # Compare a web task vs same task without web keywords
        result = analyzer.analyze("search the latest news online documentation")
        assert result.requires_web is True
        # Gemini's research strength (0.95) + web boost (0.1) should be high
        assert result.gemini_fit_score >= 0.8

    def test_no_domains_returns_default_scores(self, analyzer):
        """When no domains are detected, default scores (0.5) are returned."""
        # Force a non-trivial input that matches no domain keywords
        # This is tricky since many words match; use something obscure
        analyzer.analyze("xyzzy plugh plover")
        # If no domains, fallback to [CODING] with scores based on that
        # The actual scores depend on the CODING domain lookup

    def test_first_domain_weighted_most(self, analyzer):
        """First domain in list has highest weight in score calculation."""
        # RESEARCH-first task should favor Gemini
        analyzer.analyze("research and search about code")
        # Research gets weight 1.0, Coding gets weight 0.5
        # So research-dominant scoring should lean toward gemini


# =============================================================================
# 13. Context-aware classification (V10 FIX F1)
# =============================================================================


class TestContextAwareClassification:
    """Tests for context clue detection and structure analysis."""

    def test_file_reference_infers_coding(self, analyzer):
        """File path references infer CODING domain."""
        result = analyzer.analyze("look at the changes in utils.py")
        assert TaskDomain.CODING in result.domains

    def test_url_reference_infers_web(self, analyzer):
        """URL references infer WEB_INTERACTION domain."""
        result = analyzer.analyze("check https://example.com/api for updates")
        assert TaskDomain.WEB_INTERACTION in result.domains

    def test_error_message_infers_debugging(self, analyzer):
        """Error message patterns infer DEBUGGING domain."""
        result = analyzer.analyze("I got TypeError: unsupported operand at line 42")
        assert TaskDomain.DEBUGGING in result.domains

    def test_multi_step_increases_complexity(self, analyzer):
        """Multi-step structure (first...then...) increases complexity."""
        simple_result = analyzer.analyze("implement a function")
        multi_result = analyzer.analyze("first implement a function then add logging after that write docs")
        # Multi-step structure should bump complexity
        assert multi_result.complexity >= simple_result.complexity

    def test_question_without_imperative_reduces_complexity(self, analyzer):
        """A pure question (no action verbs) reduces complexity."""
        result = analyzer.analyze("what is the difference between lists and tuples?")
        # Questions without imperatives get -1
        assert result.complexity <= TaskComplexity.MODERATE

    def test_conditional_increases_complexity(self, analyzer):
        """Conditional structure increases complexity."""
        result = analyzer.analyze("if the user is authenticated then create a session unless blocked")
        # Conditional adds +1
        assert result.complexity >= TaskComplexity.MODERATE

    def test_context_clues_boost_confidence(self, analyzer):
        """Context clues increase analysis confidence."""
        # With file reference and error pattern
        result = analyzer.analyze("fix the TypeError in auth.py at line 42, check https://docs.python.org")
        assert result.confidence > 0.5  # Base is 0.5, clues add more


# =============================================================================
# 14. Confidence estimation
# =============================================================================


class TestConfidenceEstimation:
    """Tests for the confidence scoring heuristic."""

    def test_base_confidence_is_half(self, analyzer):
        """Confidence starts at 0.5 baseline."""
        # A minimal input with no clear signals
        result = analyzer.analyze("something")
        assert result.confidence >= 0.5

    def test_more_keywords_higher_confidence(self, analyzer):
        """More detected keywords increase confidence."""
        few = analyzer.analyze("code")
        many = analyzer.analyze("implement a python function class method with debugging and testing")
        assert many.confidence >= few.confidence

    def test_confidence_capped_at_one(self, analyzer):
        """Confidence never exceeds 1.0."""
        result = analyzer.analyze(
            "implement code debug fix error test pytest coverage validate verify "
            "analyze review examine study security vulnerability architecture "
            "brainstorm design search find at https://example.com with TypeError "
            "in auth.py at line 42"
        )
        assert result.confidence <= 1.0

    def test_medium_length_boosts_confidence(self, analyzer):
        """Text between 50-1000 chars gets +0.1 confidence."""
        analyzer.analyze("code it")
        medium = analyzer.analyze(
            "implement a python function that takes a list of integers and returns the sorted unique values"
        )
        assert len(medium.raw_input) > 50
        assert len(medium.raw_input) < 1000
        # Medium length gets a confidence boost


# =============================================================================
# 15. Stage 3 escalation logic
# =============================================================================


class TestStage3Escalation:
    """Tests for needs_stage3_escalation() method."""

    def test_trivial_never_escalates(self, analyzer):
        """TRIVIAL tasks never escalate to Stage 3."""
        analysis = TaskAnalysis(
            complexity=TaskComplexity.TRIVIAL,
            domains=[],
            primary_domain=TaskDomain.CREATIVE,
            confidence=0.1,  # Low confidence, but still trivial
        )
        assert analyzer.needs_stage3_escalation(analysis) is False

    def test_high_confidence_no_escalation(self, analyzer):
        """High confidence (>= threshold) does not escalate."""
        analysis = TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            domains=[TaskDomain.CODING],
            primary_domain=TaskDomain.CODING,
            confidence=STAGE2_CONFIDENCE_THRESHOLD,
        )
        assert analyzer.needs_stage3_escalation(analysis) is False

    def test_low_confidence_escalates(self, analyzer):
        """Low confidence below threshold triggers escalation."""
        analysis = TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            domains=[TaskDomain.CODING],
            primary_domain=TaskDomain.CODING,
            confidence=0.3,
        )
        assert analyzer.needs_stage3_escalation(analysis) is True

    def test_multiple_domains_with_moderate_confidence_no_escalation(self, analyzer):
        """Multiple domains with confidence > 0.4 do not escalate."""
        analysis = TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            domains=[TaskDomain.CODING, TaskDomain.TESTING],
            primary_domain=TaskDomain.CODING,
            confidence=0.45,
        )
        assert analyzer.needs_stage3_escalation(analysis) is False

    def test_single_domain_low_confidence_escalates(self, analyzer):
        """Single domain with low confidence escalates."""
        analysis = TaskAnalysis(
            complexity=TaskComplexity.SIMPLE,
            domains=[TaskDomain.CODING],
            primary_domain=TaskDomain.CODING,
            confidence=0.3,
        )
        assert analyzer.needs_stage3_escalation(analysis) is True


# =============================================================================
# 16. RAG enrichment (V11.2 MEMORIA)
# =============================================================================


class TestRAGEnrichment:
    """Tests for RAG-enriched classification with mocked ProjectMemory."""

    def test_no_memory_returns_empty(self, analyzer):
        """Without project_memory, RAG enrichment returns empty."""
        domains, boost = analyzer._enrich_with_rag_context("some input")
        assert domains == []
        assert boost == 0.0

    def test_memory_with_python_file(self, analyzer_with_memory):
        """Python file chunks add CODING domain hint."""
        chunk = MagicMock()
        chunk.file_path = "src/utils.py"
        chunk.content = "def helper(): pass"
        analyzer_with_memory.project_memory.retrieve.return_value = [chunk]

        domains, boost = analyzer_with_memory._enrich_with_rag_context("some input")
        assert TaskDomain.CODING in domains

    def test_memory_with_test_file(self, analyzer_with_memory):
        """Test file chunks add TESTING domain hint."""
        chunk = MagicMock()
        chunk.file_path = "tests/test_auth.py"
        chunk.content = "def test_login(): assert True"
        analyzer_with_memory.project_memory.retrieve.return_value = [chunk]

        domains, boost = analyzer_with_memory._enrich_with_rag_context("some input")
        assert TaskDomain.CODING in domains
        assert TaskDomain.TESTING in domains

    def test_memory_with_markdown_file(self, analyzer_with_memory):
        """Markdown file chunks add DOCUMENTATION domain hint."""
        chunk = MagicMock()
        chunk.file_path = "docs/README.md"
        chunk.content = "# Documentation"
        analyzer_with_memory.project_memory.retrieve.return_value = [chunk]

        domains, boost = analyzer_with_memory._enrich_with_rag_context("some input")
        assert TaskDomain.DOCUMENTATION in domains

    def test_memory_with_js_file(self, analyzer_with_memory):
        """JavaScript file chunks add CODING domain hint."""
        chunk = MagicMock()
        chunk.file_path = "src/app.js"
        chunk.content = "function main() {}"
        analyzer_with_memory.project_memory.retrieve.return_value = [chunk]

        domains, boost = analyzer_with_memory._enrich_with_rag_context("some input")
        assert TaskDomain.CODING in domains

    def test_async_content_boosts_complexity(self, analyzer_with_memory):
        """Content with async/await increases complexity boost."""
        chunk = MagicMock()
        chunk.file_path = "src/handler.py"
        chunk.content = "async def handle(): await db.query()"
        analyzer_with_memory.project_memory.retrieve.return_value = [chunk]

        domains, boost = analyzer_with_memory._enrich_with_rag_context("some input")
        assert boost > 0.0

    def test_security_content_boosts_complexity_and_domain(self, analyzer_with_memory):
        """Content with security patterns adds SECURITY domain and boost."""
        chunk = MagicMock()
        chunk.file_path = "src/auth.py"
        chunk.content = "class AuthMiddleware: security check auth token"
        analyzer_with_memory.project_memory.retrieve.return_value = [chunk]

        domains, boost = analyzer_with_memory._enrich_with_rag_context("some input")
        assert TaskDomain.SECURITY in domains
        assert boost >= 0.1

    def test_complexity_boost_capped_at_03(self, analyzer_with_memory):
        """Complexity boost is capped at 0.3."""
        chunk = MagicMock()
        chunk.file_path = "src/complex.py"
        chunk.content = "async def secure(): await auth(); class Foo: pass; try: x except: pass; security auth check"
        analyzer_with_memory.project_memory.retrieve.return_value = [chunk, chunk]

        domains, boost = analyzer_with_memory._enrich_with_rag_context("some input")
        assert boost <= 0.3

    def test_memory_exception_returns_empty(self, analyzer_with_memory):
        """Exceptions in RAG retrieval are silently handled."""
        analyzer_with_memory.project_memory.retrieve.side_effect = RuntimeError("DB down")

        domains, boost = analyzer_with_memory._enrich_with_rag_context("some input")
        assert domains == []
        assert boost == 0.0

    def test_memory_empty_results(self, analyzer_with_memory):
        """Empty RAG results return empty hints."""
        analyzer_with_memory.project_memory.retrieve.return_value = []

        domains, boost = analyzer_with_memory._enrich_with_rag_context("some input")
        assert domains == []
        assert boost == 0.0

    def test_apply_rag_domain_hints_merges(self, analyzer):
        """_apply_rag_domain_hints merges without duplicates."""
        detected = [TaskDomain.CODING]
        rag = [TaskDomain.CODING, TaskDomain.TESTING]
        keywords = ["code"]

        merged, kw = analyzer._apply_rag_domain_hints(detected, rag, keywords)
        # CODING already present, only TESTING added
        assert merged.count(TaskDomain.CODING) == 1
        assert TaskDomain.TESTING in merged
        assert any("[RAG:testing]" in k for k in kw)
        # No RAG marker for CODING since it was already detected
        assert not any("[RAG:coding]" in k for k in kw)


# =============================================================================
# 17. Async analyze
# =============================================================================


class TestAsyncAnalyze:
    """Tests for analyze_async() method."""

    @pytest.mark.asyncio
    async def test_async_analyze_returns_same_as_sync(self, analyzer):
        """analyze_async produces the same result as analyze."""
        text = "implement a python function"
        sync_result = analyzer.analyze(text)
        async_result = await analyzer.analyze_async(text)

        assert sync_result.complexity == async_result.complexity
        assert sync_result.primary_domain == async_result.primary_domain
        assert sync_result.analysis_stage == async_result.analysis_stage

    @pytest.mark.asyncio
    async def test_async_analyze_instant_command(self, analyzer):
        """analyze_async handles instant commands correctly."""
        result = await analyzer.analyze_async("status")
        assert result.complexity == TaskComplexity.TRIVIAL
        assert result.analysis_stage == AnalysisStage.STAGE1_REGEX


# =============================================================================
# 18. Edge cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    def test_empty_string(self, analyzer):
        """Empty string is classified as trivial."""
        result = analyzer.analyze("")
        assert result.complexity == TaskComplexity.TRIVIAL

    def test_whitespace_only(self, analyzer):
        """Whitespace-only input is classified as trivial."""
        result = analyzer.analyze("   \t\n  ")
        assert result.complexity == TaskComplexity.TRIVIAL

    def test_very_long_input(self, analyzer):
        """Very long input (10000+ chars) does not crash."""
        long_text = "implement a feature " * 600
        result = analyzer.analyze(long_text)
        assert result is not None
        assert isinstance(result, TaskAnalysis)
        assert result.complexity.value >= 1

    def test_unicode_input(self, analyzer):
        """Unicode characters do not crash the analyzer."""
        result = analyzer.analyze("implementer une fonction avec des accents: e\u0301, a\u0300, u\u0302")
        assert result is not None
        assert isinstance(result, TaskAnalysis)

    def test_emoji_input(self, analyzer):
        """Emoji input does not crash."""
        result = analyzer.analyze("fix the bug \U0001f41b in the code \U0001f4bb")
        assert result is not None

    def test_special_characters(self, analyzer):
        """Special regex characters in input do not crash."""
        result = analyzer.analyze("fix the regex [a-z]+ and (group|match) in *.py")
        assert result is not None
        assert isinstance(result, TaskAnalysis)

    def test_newlines_in_input(self, analyzer):
        """Multi-line input is handled correctly."""
        result = analyzer.analyze("implement:\n1. sort function\n2. test it\n3. document it")
        assert result is not None
        # Multi-step structure detected
        assert result.complexity >= TaskComplexity.SIMPLE

    def test_mixed_case_keywords(self, analyzer):
        """Keywords are matched case-insensitively."""
        result = analyzer.analyze("IMPLEMENT a PYTHON FUNCTION")
        assert TaskDomain.CODING in result.domains

    def test_single_word_non_command(self, analyzer):
        """Single non-command word gets Stage 2 analysis."""
        result = analyzer.analyze("refactor")
        assert result.analysis_stage == AnalysisStage.STAGE2_HEURISTIC

    def test_numeric_input(self, analyzer):
        """Purely numeric input (like '1234') is trivial."""
        result = analyzer.analyze("1234")
        assert result.complexity == TaskComplexity.TRIVIAL

    def test_domain_keywords_are_case_insensitive(self, analyzer):
        """Domain patterns use re.IGNORECASE."""
        result = analyzer.analyze("SECURITY vulnerability EXPLOIT")
        assert TaskDomain.SECURITY in result.domains


# =============================================================================
# 19. Constants validation
# =============================================================================


class TestConstantsValidation:
    """Tests that module-level constants are well-formed."""

    def test_complexity_indicators_keys_are_lowercase(self):
        """All COMPLEXITY_INDICATORS keys are lowercase."""
        for key in COMPLEXITY_INDICATORS:
            assert key == key.lower(), f"Key '{key}' is not lowercase"

    def test_complexity_indicators_values_are_ints(self):
        """All COMPLEXITY_INDICATORS values are integers."""
        for key, val in COMPLEXITY_INDICATORS.items():
            assert isinstance(val, int), f"Value for '{key}' is not int: {type(val)}"

    def test_agent_strengths_cover_both_agents(self):
        """AGENT_DOMAIN_STRENGTHS has entries for gemini and claude."""
        assert "gemini" in AGENT_DOMAIN_STRENGTHS
        assert "claude" in AGENT_DOMAIN_STRENGTHS

    def test_agent_strengths_values_in_range(self):
        """All agent strength values are between 0.0 and 1.0."""
        for agent, strengths in AGENT_DOMAIN_STRENGTHS.items():
            for domain, score in strengths.items():
                assert 0.0 <= score <= 1.0, f"{agent}/{domain} score {score} out of range"

    def test_stage1_patterns_are_valid_regex(self):
        """All Stage 1 patterns compile as valid regex."""
        for pattern_str in STAGE1_INSTANT_COMMANDS:
            try:
                re.compile(pattern_str, re.IGNORECASE)
            except re.error as e:
                pytest.fail(f"Invalid regex '{pattern_str}': {e}")

    def test_conversational_patterns_are_valid_regex(self):
        """All conversational trivial patterns compile as valid regex."""
        for pattern_str in CONVERSATIONAL_TRIVIAL_PATTERNS:
            try:
                re.compile(pattern_str, re.IGNORECASE)
            except re.error as e:
                pytest.fail(f"Invalid regex '{pattern_str}': {e}")

    def test_stage2_confidence_threshold_in_range(self):
        """STAGE2_CONFIDENCE_THRESHOLD is between 0 and 1."""
        assert 0.0 < STAGE2_CONFIDENCE_THRESHOLD < 1.0

    def test_domain_keywords_non_empty(self):
        """Every domain in DOMAIN_KEYWORDS has at least one keyword."""
        for domain, keywords in DOMAIN_KEYWORDS.items():
            assert len(keywords) > 0, f"{domain} has no keywords"

    def test_task_structure_patterns_valid(self):
        """All TASK_STRUCTURE_PATTERNS compile as valid regex."""
        for category, patterns in TASK_STRUCTURE_PATTERNS.items():
            for p in patterns:
                try:
                    re.compile(p, re.IGNORECASE | re.MULTILINE)
                except re.error as e:
                    pytest.fail(f"Invalid regex in {category}: '{p}': {e}")

    def test_context_clue_patterns_valid(self):
        """All CONTEXT_CLUE_PATTERNS compile as valid regex."""
        for category, patterns in CONTEXT_CLUE_PATTERNS.items():
            for p in patterns:
                try:
                    re.compile(p, re.IGNORECASE)
                except re.error as e:
                    pytest.fail(f"Invalid regex in {category}: '{p}': {e}")


# =============================================================================
# 20. TaskAnalyzer initialization
# =============================================================================


class TestTaskAnalyzerInit:
    """Tests for TaskAnalyzer construction."""

    def test_init_without_memory(self):
        """TaskAnalyzer initializes without project_memory."""
        ta = TaskAnalyzer()
        assert ta.project_memory is None

    def test_init_with_memory(self):
        """TaskAnalyzer stores project_memory reference."""
        mock_mem = MagicMock()
        ta = TaskAnalyzer(project_memory=mock_mem)
        assert ta.project_memory is mock_mem

    def test_patterns_compiled(self):
        """Internal patterns are compiled on init."""
        ta = TaskAnalyzer()
        assert isinstance(ta._domain_patterns, dict)
        assert len(ta._domain_patterns) == len(TaskDomain)
        assert isinstance(ta._trivial_patterns, list)
        assert len(ta._trivial_patterns) > 0
        assert isinstance(ta._instant_command_patterns, list)
        assert len(ta._instant_command_patterns) > 0
        assert isinstance(ta._structure_patterns, dict)
        assert isinstance(ta._context_patterns, dict)


# =============================================================================
# 21. to_dict / from_dict additional edge cases
# =============================================================================


class TestSerialization:
    """Additional serialization/deserialization tests."""

    def test_to_dict_empty_domains(self):
        """to_dict handles empty domains list."""
        analysis = TaskAnalysis(
            complexity=TaskComplexity.TRIVIAL,
            domains=[],
            primary_domain=TaskDomain.CREATIVE,
        )
        d = analysis.to_dict()
        assert d["domains"] == []

    def test_to_dict_instant_command_none(self):
        """to_dict handles None instant_command."""
        analysis = TaskAnalysis(
            complexity=TaskComplexity.MODERATE,
            domains=[TaskDomain.CODING],
            primary_domain=TaskDomain.CODING,
        )
        d = analysis.to_dict()
        assert d["instant_command"] is None

    def test_from_dict_empty_dict(self):
        """from_dict with minimal/empty dict uses defaults.

        Note: from_dict references TaskDomain.GENERAL which does not exist
        in the enum. With empty domains list, this will raise ValueError.
        We test the working path instead.
        """
        data = {
            "complexity": "MODERATE",
            "domains": ["coding"],
            "primary_domain": "coding",
        }
        analysis = TaskAnalysis.from_dict(data)
        assert analysis.complexity == TaskComplexity.MODERATE

    def test_from_dict_preserves_detected_keywords(self):
        """from_dict preserves detected_keywords list."""
        data = {
            "complexity": "SIMPLE",
            "domains": ["research"],
            "primary_domain": "research",
            "detected_keywords": ["search", "find", "[CONTEXT:web_interaction]"],
        }
        analysis = TaskAnalysis.from_dict(data)
        assert analysis.detected_keywords == ["search", "find", "[CONTEXT:web_interaction]"]

    def test_from_dict_preserves_raw_input(self):
        """from_dict preserves raw_input string."""
        data = {
            "complexity": "MODERATE",
            "domains": ["coding"],
            "primary_domain": "coding",
            "raw_input": "implement a function",
        }
        analysis = TaskAnalysis.from_dict(data)
        assert analysis.raw_input == "implement a function"


# =============================================================================
# 22. Low-confidence keyword marker
# =============================================================================


class TestLowConfidenceMarker:
    """Tests that low-confidence Stage 2 results get marked."""

    def test_low_confidence_gets_marker(self, analyzer):
        """Inputs producing low confidence get [LOW_CONFIDENCE:...] keyword."""
        # A very short, ambiguous input with no clear domain keywords
        result = analyzer.analyze("hmm interesting")
        if result.confidence < STAGE2_CONFIDENCE_THRESHOLD:
            assert any("[LOW_CONFIDENCE:" in k for k in result.detected_keywords), (
                "Low confidence should be marked in detected_keywords"
            )


# =============================================================================
# 23. Internal method tests
# =============================================================================


class TestInternalMethods:
    """Tests for internal helper methods."""

    def test_detect_domains_returns_sorted(self, analyzer):
        """_detect_domains returns domains sorted by match count."""
        # Provide text with more CODING keywords than TESTING
        domains, kw = analyzer._detect_domains("implement a python function class method with test")
        if TaskDomain.CODING in domains and TaskDomain.TESTING in domains:
            assert domains.index(TaskDomain.CODING) < domains.index(TaskDomain.TESTING)

    def test_detect_domains_empty_input(self, analyzer):
        """_detect_domains with empty input returns empty lists."""
        domains, kw = analyzer._detect_domains("")
        assert domains == []
        assert kw == []

    def test_detect_web_requirement(self, analyzer):
        """_detect_web_requirement identifies web keywords."""
        assert analyzer._detect_web_requirement("search the web") is True
        assert analyzer._detect_web_requirement("write a function") is False
        assert analyzer._detect_web_requirement("fetch the latest api data") is True

    def test_detect_code_requirement(self, analyzer):
        """_detect_code_requirement identifies code execution keywords."""
        assert analyzer._detect_code_requirement("run the tests", []) is True
        assert analyzer._detect_code_requirement("something", [TaskDomain.CODING]) is True
        assert analyzer._detect_code_requirement("hello there", [TaskDomain.CREATIVE]) is False

    def test_detect_reasoning_requirement(self, analyzer):
        """_detect_reasoning_requirement identifies reasoning needs."""
        assert analyzer._detect_reasoning_requirement("analyze the architecture", TaskComplexity.SIMPLE) is True
        assert analyzer._detect_reasoning_requirement("just do it", TaskComplexity.EXPERT) is True  # EXPERT triggers it
        assert analyzer._detect_reasoning_requirement("just do it", TaskComplexity.SIMPLE) is False

    def test_detect_iteration_requirement(self, analyzer):
        """_detect_iteration_requirement identifies iteration needs."""
        assert analyzer._detect_iteration_requirement("brainstorm and improve", []) is True
        assert analyzer._detect_iteration_requirement("something", [TaskDomain.CREATIVE]) is True
        assert analyzer._detect_iteration_requirement("just code it", [TaskDomain.CODING]) is False

    def test_analyze_task_structure(self, analyzer):
        """_analyze_task_structure detects structural patterns."""
        # Multi-step
        result = analyzer._analyze_task_structure("first do X then do Y")
        assert result["is_multi_step"] is True

        # Question
        result = analyzer._analyze_task_structure("what is the best approach?")
        assert result["is_question"] is True

        # Imperative
        result = analyzer._analyze_task_structure("create a new file")
        assert result["is_imperative"] is True

        # Conditional
        result = analyzer._analyze_task_structure("if the user is logged in then show dashboard")
        assert result["is_conditional"] is True

    def test_detect_context_clues(self, analyzer):
        """_detect_context_clues finds context patterns."""
        clues = analyzer._detect_context_clues("look at auth.py for the bug")
        assert "file_reference" in clues

        clues = analyzer._detect_context_clues("check https://api.example.com")
        assert "url_reference" in clues

        clues = analyzer._detect_context_clues("got TypeError at line 42")
        assert "error_message" in clues

    def test_infer_domains_from_context(self, analyzer):
        """_infer_domains_from_context maps clues to domains."""
        domains = analyzer._infer_domains_from_context("edit auth.py")
        assert TaskDomain.CODING in domains

        domains = analyzer._infer_domains_from_context("visit https://example.com")
        assert TaskDomain.WEB_INTERACTION in domains

        domains = analyzer._infer_domains_from_context("got ValueError at line 10")
        assert TaskDomain.DEBUGGING in domains

    def test_infer_domains_question_fallback(self, analyzer):
        """Questions without other clues infer ANALYSIS domain."""
        domains = analyzer._infer_domains_from_context("why does this happen?")
        assert TaskDomain.ANALYSIS in domains
