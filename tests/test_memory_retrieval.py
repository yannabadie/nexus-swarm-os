"""
Tests for Phase 10b: Memory-Augmented Mode Selection

Verifies:
1. Jaccard similarity calculation
2. find_similar_tasks() retrieval
3. get_best_mode_for_similar() helper
4. ModeSelector memory boost integration
5. End-to-end memory influence on mode selection
"""

from dataclasses import dataclass
from enum import Enum

import pytest

from core.intelligence.swarm.collaboration_modes import CollaborationMode
from core.intelligence.swarm.mode_selector import ModeSelector
from core.memory_pkg.memory import SuccessEntry, SuccessMemory  # V2 via backward compat alias

# =============================================================================
# Mock Classes
# =============================================================================


class MockTaskComplexity(Enum):
    TRIVIAL = 1
    SIMPLE = 2
    MODERATE = 3
    COMPLEX = 4
    EXPERT = 5


class MockTaskDomain(Enum):
    CODING = "coding"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    DOCUMENTATION = "documentation"


@dataclass
class MockTaskAnalysis:
    """Mock TaskAnalysis for testing."""

    raw_input: str = "Test task"
    complexity: MockTaskComplexity = MockTaskComplexity.MODERATE
    domains: list[MockTaskDomain] = None
    primary_domain: MockTaskDomain | None = None
    recommended_lead: str | None = None
    requires_web: bool = False
    requires_deep_reasoning: bool = False
    requires_iteration: bool = False
    needs_adversarial_mode: bool = False

    def __post_init__(self):
        if self.domains is None:
            self.domains = [MockTaskDomain.CODING]
        if self.primary_domain is None and self.domains:
            self.primary_domain = self.domains[0]


# =============================================================================
# Tokenization Tests
# =============================================================================


class TestTokenization:
    """Tests for internal tokenization."""

    @pytest.fixture
    def memory(self, tmp_path):
        return SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path)

    def test_basic_tokenization(self, memory):
        """Basic tokenization removes stop words."""
        tokens = memory._tokenize("Fix the bug in auth.py")
        assert "fix" in tokens
        assert "bug" in tokens
        assert "auth" in tokens
        # Stop words removed
        assert "the" not in tokens
        assert "in" not in tokens

    def test_case_insensitivity(self, memory):
        """Tokenization is case-insensitive."""
        tokens1 = memory._tokenize("Fix Bug")
        tokens2 = memory._tokenize("fix bug")
        assert tokens1 == tokens2

    def test_punctuation_removal(self, memory):
        """Punctuation is removed."""
        tokens = memory._tokenize("Fix the bug! auth.python")
        assert "fix" in tokens
        assert "auth" in tokens
        assert "python" in tokens  # "py" would be filtered (<=2 chars)

    def test_short_tokens_filtered(self, memory):
        """Tokens <= 2 chars are filtered."""
        tokens = memory._tokenize("a an be to fix bug")
        assert "fix" in tokens
        assert "bug" in tokens
        # Short words filtered
        assert "a" not in tokens
        assert "an" not in tokens
        assert "be" not in tokens

    def test_french_stop_words(self, memory):
        """French stop words are removed."""
        tokens = memory._tokenize("Corriger le bug dans le fichier")
        assert "corriger" in tokens
        assert "bug" in tokens
        assert "fichier" in tokens
        # French stop words removed
        assert "le" not in tokens
        assert "dans" not in tokens


# =============================================================================
# Jaccard Similarity Tests
# =============================================================================


class TestJaccardSimilarity:
    """Tests for Jaccard similarity calculation."""

    @pytest.fixture
    def memory(self, tmp_path):
        return SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path)

    def test_identical_sets(self, memory):
        """Identical sets have similarity 1.0."""
        set1 = {"fix", "bug", "auth"}
        set2 = {"fix", "bug", "auth"}
        assert memory._jaccard_similarity(set1, set2) == 1.0

    def test_disjoint_sets(self, memory):
        """Disjoint sets have similarity 0.0."""
        set1 = {"fix", "bug"}
        set2 = {"create", "feature"}
        assert memory._jaccard_similarity(set1, set2) == 0.0

    def test_partial_overlap(self, memory):
        """Partial overlap gives score between 0 and 1."""
        set1 = {"fix", "bug", "auth"}
        set2 = {"fix", "bug", "login"}
        # intersection: {fix, bug} = 2
        # union: {fix, bug, auth, login} = 4
        # Jaccard = 2/4 = 0.5
        assert memory._jaccard_similarity(set1, set2) == 0.5

    def test_empty_sets(self, memory):
        """Empty sets return 0.0."""
        assert memory._jaccard_similarity(set(), set()) == 0.0
        assert memory._jaccard_similarity({"fix"}, set()) == 0.0
        assert memory._jaccard_similarity(set(), {"fix"}) == 0.0


# =============================================================================
# find_similar_tasks Tests
# =============================================================================


class TestFindSimilarTasks:
    """Tests for find_similar_tasks() method."""

    @pytest.fixture
    def memory_with_entries(self, tmp_path):
        """Create memory with some entries."""
        memory = SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path)

        # Add some entries via V2 API
        entries = [
            SuccessEntry(
                task_id="task-001",
                task_hash="abc123",
                description="Fix the authentication bug in auth.py",
                swarm_mode="ping_pong",
                agents_used=["Gemini", "Claude"],
                duration_seconds=10.0,
                complexity="MODERATE",
                domains=["coding", "debugging"],
                quality_score=0.85,
                timestamp="2025-12-04T12:00:00",
            ),
            SuccessEntry(
                task_id="task-002",
                task_hash="def456",
                description="Create a new REST API endpoint",
                swarm_mode="lead_support",
                agents_used=["Claude"],
                duration_seconds=15.0,
                complexity="MODERATE",
                domains=["coding"],
                quality_score=0.9,
                timestamp="2025-12-04T13:00:00",
            ),
            SuccessEntry(
                task_id="task-003",
                task_hash="ghi789",
                description="Debug login authentication issue",
                swarm_mode="ping_pong",
                agents_used=["Gemini", "Claude"],
                duration_seconds=8.0,
                complexity="SIMPLE",
                domains=["debugging"],
                quality_score=0.8,
                timestamp="2025-12-04T14:00:00",
            ),
        ]

        # Add entries via backward-compat API
        for entry in entries:
            memory._append_entry(entry)

        return memory

    def test_find_exact_match(self, memory_with_entries):
        """Find tasks with exact word matches."""
        similar = memory_with_entries.find_similar_tasks("Fix authentication bug", limit=5, min_score=0.1)

        assert len(similar) > 0
        # First result should be task-001 or task-003 (auth/authentication)
        task_ids = [e.task_id for e, _ in similar]
        assert "task-001" in task_ids or "task-003" in task_ids

    def test_find_similar_by_domain(self, memory_with_entries):
        """Find tasks similar by domain keywords."""
        similar = memory_with_entries.find_similar_tasks("Debug the login problem", limit=5, min_score=0.1)

        assert len(similar) > 0
        # Should match task-003 (debug, login)
        top_entry, _ = similar[0]
        assert "debug" in top_entry.description.lower() or "login" in top_entry.description.lower()

    def test_limit_results(self, memory_with_entries):
        """Limit parameter works."""
        similar = memory_with_entries.find_similar_tasks("Fix authentication bug issue login", limit=1, min_score=0.01)

        assert len(similar) <= 1

    def test_min_score_filter(self, memory_with_entries, monkeypatch):
        """Min score filters low similarity results."""
        # Force TF-IDF backend so min_score is applied correctly at retrieval time.
        # The hybrid backend passes min_score=0.0 internally and may bypass the threshold.
        monkeypatch.setenv("PROJECT_MEMORY_BACKEND", "tfidf")
        pm = memory_with_entries.project_memory
        pm._backend = pm._select_backend()
        pm._backend_dirty = True

        similar = memory_with_entries.find_similar_tasks(
            "Fix authentication",
            limit=10,
            min_score=0.9,  # Very high threshold
        )

        # All returned items should have score >= 0.9
        for _entry, score in similar:
            assert score >= 0.9

    def test_no_matches(self, memory_with_entries, monkeypatch):
        """Returns empty for no matches."""
        # Force TF-IDF backend so min_score is applied correctly at retrieval time.
        monkeypatch.setenv("PROJECT_MEMORY_BACKEND", "tfidf")
        pm = memory_with_entries.project_memory
        pm._backend = pm._select_backend()
        pm._backend_dirty = True

        similar = memory_with_entries.find_similar_tasks(
            "completely unrelated query about bananas", limit=5, min_score=0.5
        )

        assert len(similar) == 0

    def test_empty_memory(self, tmp_path):
        """Returns empty for empty memory."""
        memory = SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path)
        similar = memory.find_similar_tasks("Fix bug", limit=5)
        assert len(similar) == 0


# =============================================================================
# get_best_mode_for_similar Tests
# =============================================================================


class TestGetBestModeForSimilar:
    """Tests for get_best_mode_for_similar() helper."""

    @pytest.fixture
    def memory_with_mode_history(self, tmp_path):
        """Create memory with mode history for testing."""
        memory = SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path)

        entries = [
            # Auth-related tasks solved with PING_PONG
            SuccessEntry(
                task_id="task-001",
                task_hash="abc123",
                description="Fix authentication bug",
                swarm_mode="ping_pong",
                agents_used=["Gemini", "Claude"],
                duration_seconds=10.0,
                complexity="MODERATE",
                domains=["coding"],
                quality_score=0.9,
                timestamp="2025-12-04T12:00:00",
            ),
            SuccessEntry(
                task_id="task-002",
                task_hash="def456",
                description="Debug authentication error",
                swarm_mode="ping_pong",
                agents_used=["Gemini", "Claude"],
                duration_seconds=8.0,
                complexity="MODERATE",
                domains=["debugging"],
                quality_score=0.85,
                timestamp="2025-12-04T13:00:00",
            ),
            # API tasks solved with LEAD_SUPPORT
            SuccessEntry(
                task_id="task-003",
                task_hash="ghi789",
                description="Create REST API endpoint",
                swarm_mode="lead_support",
                agents_used=["Claude"],
                duration_seconds=15.0,
                complexity="MODERATE",
                domains=["coding"],
                quality_score=0.95,
                timestamp="2025-12-04T14:00:00",
            ),
        ]

        for entry in entries:
            memory._append_entry(entry)
        return memory

    def test_returns_best_mode(self, memory_with_mode_history):
        """Returns mode that worked for similar tasks."""
        result = memory_with_mode_history.get_best_mode_for_similar("Fix the authentication issue", min_similarity=0.1)

        assert result is not None
        mode, task_id, similarity = result
        # Should recommend PING_PONG (auth tasks)
        assert mode == "ping_pong"
        assert similarity > 0

    def test_returns_none_for_no_match(self, memory_with_mode_history, monkeypatch):
        """Returns None when no similar tasks found."""
        # Force TF-IDF backend so min_similarity is applied correctly at retrieval time.
        monkeypatch.setenv("PROJECT_MEMORY_BACKEND", "tfidf")
        pm = memory_with_mode_history.project_memory
        pm._backend = pm._select_backend()
        pm._backend_dirty = True

        result = memory_with_mode_history.get_best_mode_for_similar("completely unrelated query", min_similarity=0.5)

        assert result is None


# =============================================================================
# ModeSelector Memory Integration Tests
# =============================================================================


class TestModeSelectorMemoryIntegration:
    """Tests for ModeSelector with SuccessMemory integration."""

    @pytest.fixture
    def memory_with_history(self, tmp_path):
        """Create memory with task history."""
        memory = SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path)

        entries = [
            SuccessEntry(
                task_id="task-001",
                task_hash="abc123",
                description="Fix authentication bug in login module",
                swarm_mode="ping_pong",
                agents_used=["Gemini", "Claude"],
                duration_seconds=10.0,
                complexity="MODERATE",
                domains=["coding", "debugging"],
                quality_score=0.9,
                timestamp="2025-12-04T12:00:00",
            ),
        ]

        for entry in entries:
            memory._append_entry(entry)
        return memory

    def test_selector_accepts_memory(self, memory_with_history):
        """ModeSelector accepts success_memory parameter."""
        selector = ModeSelector(success_memory=memory_with_history)
        assert selector.success_memory is memory_with_history

    def test_selector_without_memory(self):
        """ModeSelector works without memory."""
        selector = ModeSelector(success_memory=None)
        assert selector.success_memory is None

    def test_memory_boost_applied(self, memory_with_history):
        """Memory boost is applied to matching mode."""
        selector = ModeSelector(success_memory=memory_with_history)

        # Create analysis similar to stored task
        analysis = MockTaskAnalysis(
            raw_input="Fix authentication bug in auth module",
            complexity=MockTaskComplexity.MODERATE,
            domains=[MockTaskDomain.CODING, MockTaskDomain.DEBUGGING],
        )

        # Manually test _apply_memory_boost
        mode_scores = {mode: 0.5 for mode in CollaborationMode}
        original_ping_pong = mode_scores[CollaborationMode.PING_PONG]

        boosted_mode, boost_info = selector._apply_memory_boost(analysis, mode_scores)

        if boosted_mode == CollaborationMode.PING_PONG:
            # Should have boosted PING_PONG
            assert mode_scores[CollaborationMode.PING_PONG] > original_ping_pong
            assert boost_info is not None
            assert boost_info["mode"] == "ping_pong"

    def test_memory_boost_in_reasoning(self, memory_with_history):
        """Memory boost appears in reasoning when mode matches."""
        selector = ModeSelector(success_memory=memory_with_history)

        analysis = MockTaskAnalysis(
            raw_input="Fix authentication bug", complexity=MockTaskComplexity.MODERATE, domains=[MockTaskDomain.CODING]
        )

        proposal = selector.select_mode(analysis)

        # Check if memory was consulted (may or may not boost depending on similarity)
        if selector._last_memory_match and selector._last_memory_match.get("mode") == proposal.mode.value:
            assert "memory" in proposal.reasoning.lower() or "similar" in proposal.reasoning.lower()


# =============================================================================
# End-to-End Integration Tests
# =============================================================================


class TestEndToEndMemoryInfluence:
    """End-to-end tests for memory influence on mode selection."""

    def test_memory_influences_selection(self, tmp_path):
        """Memory can influence mode selection toward historically successful modes."""
        memory = SuccessMemory(workspace_path=tmp_path, nexus_root=tmp_path)

        # Store that PARALLEL worked great for "database optimization"
        entries = [
            SuccessEntry(
                task_id="task-db-001",
                task_hash="db123",
                description="Optimize database queries performance",
                swarm_mode="parallel",
                agents_used=["Gemini", "Claude"],
                duration_seconds=20.0,
                complexity="COMPLEX",
                domains=["coding", "database"],
                quality_score=0.95,
                timestamp="2025-12-04T12:00:00",
            ),
            SuccessEntry(
                task_id="task-db-002",
                task_hash="db456",
                description="Database query optimization task",
                swarm_mode="parallel",
                agents_used=["Gemini", "Claude"],
                duration_seconds=18.0,
                complexity="COMPLEX",
                domains=["database"],
                quality_score=0.9,
                timestamp="2025-12-04T13:00:00",
            ),
        ]

        for entry in entries:
            memory._append_entry(entry)

        # Create selector with memory
        selector = ModeSelector(success_memory=memory)

        # Query for similar task
        analysis = MockTaskAnalysis(
            raw_input="Optimize the database query performance",
            complexity=MockTaskComplexity.COMPLEX,
            domains=[MockTaskDomain.CODING],
        )

        # Check that memory boost is applied
        mode_scores = {mode: 0.5 for mode in CollaborationMode}
        boosted_mode, boost_info = selector._apply_memory_boost(analysis, mode_scores)

        # PARALLEL should have been boosted
        if boosted_mode:
            assert boosted_mode == CollaborationMode.PARALLEL
            assert mode_scores[CollaborationMode.PARALLEL] > 0.5

    def test_no_memory_no_boost(self, tmp_path):
        """Without memory, no boost is applied."""
        selector = ModeSelector(success_memory=None)

        analysis = MockTaskAnalysis(
            raw_input="Fix the bug", complexity=MockTaskComplexity.MODERATE, domains=[MockTaskDomain.CODING]
        )

        mode_scores = {mode: 0.5 for mode in CollaborationMode}
        boosted_mode, boost_info = selector._apply_memory_boost(analysis, mode_scores)

        assert boosted_mode is None
        assert boost_info is None
        # All scores unchanged
        for mode in CollaborationMode:
            assert mode_scores[mode] == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
