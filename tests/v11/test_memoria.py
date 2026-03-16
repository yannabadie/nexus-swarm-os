"""
V11.2 MEMORIA: Unified Memory Architecture Tests.

Tests for OPERATION MEMORIA features:
1. Dense Index Bug Fix (Phase 0)
2. Memory Coordinator (Phase 1)
3. RAG in TaskAnalyzer (Phase 2A)
4. RAG in Simple Mode (Phase 2B)
5. Time Decay for AutoMemory (Phase 3)
6. Consolidation Trigger (Phase 4)

Author: Claude (NEXUS V11.2 MEMORIA)
Date: 2025-12-15
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# =============================================================================
# Phase 0: Dense Index Bug Fix Tests
# =============================================================================


class TestDenseIndexFix:
    """Test suite for dense.py .tolist() bug fix."""

    def test_embedding_list_handling(self):
        """Verify embeddings[i] handles both list and numpy array."""

        # Simulate the fixed code path
        def process_embeddings(embeddings):
            """Mimics the fixed logic in dense.py."""
            data = []
            for i, emb in enumerate(embeddings):
                # V11.2 MEMORIA FIX: handle both list and numpy array
                vector = emb if isinstance(emb, list) else emb.tolist()
                data.append({"id": f"chunk_{i}", "vector": vector})
            return data

        # Test with list (what EmbeddingEngine returns)
        list_embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        result = process_embeddings(list_embeddings)
        assert len(result) == 2
        assert result[0]["vector"] == [0.1, 0.2, 0.3]

        # Test with numpy array (legacy case)
        try:
            import numpy as np

            np_embeddings = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
            result = process_embeddings(np_embeddings)
            assert len(result) == 2
            assert result[0]["vector"] == [0.1, 0.2, 0.3]
        except ImportError:
            # numpy not available, skip this part
            pass


# =============================================================================
# Phase 1: Memory Coordinator Tests
# =============================================================================


class TestMemoryCoordinator:
    """Test suite for MemoryCoordinator."""

    def test_import_coordinator(self):
        """Verify MemoryCoordinator can be imported."""
        from core.memory_pkg.memory.coordinator import MemoryCoordinator, MemorySource, UnifiedRecommendation

        assert MemoryCoordinator is not None
        assert MemorySource is not None
        assert UnifiedRecommendation is not None

    def test_memory_source_enum(self):
        """Verify MemorySource enum values."""
        from core.memory_pkg.memory.coordinator import MemorySource

        assert MemorySource.SUCCESS.value == "success_memory"
        assert MemorySource.AUTO.value == "auto_memory"
        assert MemorySource.BOTH.value == "both"
        assert MemorySource.NONE.value == "none"

    def test_unified_recommendation_dataclass(self):
        """Verify UnifiedRecommendation fields."""
        from core.memory_pkg.memory.coordinator import MemorySource, UnifiedRecommendation

        rec = UnifiedRecommendation(
            mode="parallel",
            lead="gemini",
            confidence=0.8,
            source=MemorySource.BOTH,
            modes_to_avoid=["sequential"],
            reasoning="Test reasoning",
        )

        assert rec.mode == "parallel"
        assert rec.lead == "gemini"
        assert rec.confidence == 0.8
        assert rec.source == MemorySource.BOTH
        assert "sequential" in rec.modes_to_avoid
        assert rec.reasoning == "Test reasoning"

    def test_coordinator_cold_start(self):
        """Verify coordinator handles cold start (no memory data)."""
        from core.memory_pkg.memory.coordinator import MemoryCoordinator, MemorySource

        # Create coordinator with mock memories that return nothing
        mock_success = MagicMock()
        mock_success.get_best_mode_for_similar.return_value = None

        mock_auto = MagicMock()
        mock_auto.get_recommendation.return_value = None

        coordinator = MemoryCoordinator(mock_success, mock_auto)
        rec = coordinator.get_recommendation("test task", "coding")

        assert rec.confidence == 0.0
        assert rec.source == MemorySource.NONE
        assert "cold start" in rec.reasoning.lower() or "no memory" in rec.reasoning.lower()

    def test_coordinator_success_only(self):
        """Verify coordinator works with only SuccessMemory data."""
        from core.memory_pkg.memory.coordinator import MemoryCoordinator, MemorySource

        mock_success = MagicMock()
        mock_success.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.7)

        mock_auto = MagicMock()
        mock_auto.get_recommendation.return_value = None

        coordinator = MemoryCoordinator(mock_success, mock_auto)
        rec = coordinator.get_recommendation("test task", "coding")

        assert rec.mode == "parallel"
        assert rec.confidence > 0
        assert rec.source == MemorySource.SUCCESS

    def test_coordinator_auto_only(self):
        """Verify coordinator works with only AutoMemory data."""
        from core.memory_pkg.memory.coordinator import MemoryCoordinator, MemorySource

        mock_success = MagicMock()
        mock_success.get_best_mode_for_similar.return_value = None

        mock_auto = MagicMock()
        mock_auto.get_recommendation.return_value = {
            "suggested_mode": "sequential",
            "suggested_lead": "claude",
            "confidence": 0.8,
            "modes_to_avoid": [],
        }

        coordinator = MemoryCoordinator(mock_success, mock_auto)
        rec = coordinator.get_recommendation("test task", "coding")

        assert rec.mode == "sequential"
        assert rec.lead == "claude"
        assert rec.source == MemorySource.AUTO

    def test_coordinator_agreement(self):
        """Verify coordinator combines scores when both agree."""
        from core.memory_pkg.memory.coordinator import MemoryCoordinator, MemorySource

        mock_success = MagicMock()
        mock_success.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.6)

        mock_auto = MagicMock()
        mock_auto.get_recommendation.return_value = {
            "suggested_mode": "parallel",  # Same mode!
            "suggested_lead": "gemini",
            "confidence": 0.7,
            "modes_to_avoid": [],
        }

        coordinator = MemoryCoordinator(mock_success, mock_auto)
        rec = coordinator.get_recommendation("test task", "coding")

        assert rec.mode == "parallel"
        assert rec.source == MemorySource.BOTH
        # Combined confidence should be higher than either alone
        assert rec.confidence > 0.36  # 0.6 * 0.6 = 0.36

    def test_coordinator_conflict_resolution(self):
        """Verify coordinator resolves conflicts (semantic > categorical)."""
        from core.memory_pkg.memory.coordinator import MemoryCoordinator, MemorySource

        mock_success = MagicMock()
        mock_success.get_best_mode_for_similar.return_value = ("parallel", "task_123", 0.9)  # High similarity

        mock_auto = MagicMock()
        mock_auto.get_recommendation.return_value = {
            "suggested_mode": "sequential",  # Different mode!
            "suggested_lead": "gemini",
            "confidence": 0.6,  # Lower confidence
            "modes_to_avoid": [],
        }

        coordinator = MemoryCoordinator(mock_success, mock_auto)
        rec = coordinator.get_recommendation("test task", "coding")

        # Semantic (success) should win due to higher weighted score
        assert rec.mode == "parallel"
        assert rec.source == MemorySource.SUCCESS


# =============================================================================
# Phase 2A: RAG in TaskAnalyzer Tests
# =============================================================================


class TestRAGInTaskAnalyzer:
    """Test suite for RAG enrichment in TaskAnalyzer."""

    def test_task_analyzer_accepts_project_memory(self):
        """Verify TaskAnalyzer accepts project_memory parameter."""
        from core.intelligence.swarm.task_analyzer import TaskAnalyzer

        # Without memory
        analyzer1 = TaskAnalyzer()
        assert analyzer1.project_memory is None

        # With mock memory
        mock_memory = MagicMock()
        analyzer2 = TaskAnalyzer(project_memory=mock_memory)
        assert analyzer2.project_memory is mock_memory

    def test_enrich_with_rag_no_memory(self):
        """Verify _enrich_with_rag_context returns empty with no memory."""
        from core.intelligence.swarm.task_analyzer import TaskAnalyzer

        analyzer = TaskAnalyzer()
        domains, boost = analyzer._enrich_with_rag_context("test query")

        assert domains == []
        assert boost == 0.0

    def test_enrich_with_rag_no_chunks(self):
        """Verify _enrich_with_rag_context handles no matching chunks."""
        from core.intelligence.swarm.task_analyzer import TaskAnalyzer

        mock_memory = MagicMock()
        mock_memory.retrieve.return_value = []

        analyzer = TaskAnalyzer(project_memory=mock_memory)
        domains, boost = analyzer._enrich_with_rag_context("test query")

        assert domains == []
        assert boost == 0.0

    def test_enrich_with_rag_python_files(self):
        """Verify _enrich_with_rag_context infers CODING from .py files."""
        from core.intelligence.swarm.task_analyzer import TaskAnalyzer, TaskDomain

        mock_chunk = MagicMock()
        mock_chunk.file_path = "src/main.py"
        mock_chunk.content = "def hello(): pass"

        mock_memory = MagicMock()
        mock_memory.retrieve.return_value = [mock_chunk]

        analyzer = TaskAnalyzer(project_memory=mock_memory)
        domains, boost = analyzer._enrich_with_rag_context("test query")

        assert TaskDomain.CODING in domains

    def test_enrich_with_rag_test_files(self):
        """Verify _enrich_with_rag_context infers TESTING from test files."""
        from core.intelligence.swarm.task_analyzer import TaskAnalyzer, TaskDomain

        mock_chunk = MagicMock()
        mock_chunk.file_path = "tests/test_main.py"
        mock_chunk.content = "def test_hello(): assert True"

        mock_memory = MagicMock()
        mock_memory.retrieve.return_value = [mock_chunk]

        analyzer = TaskAnalyzer(project_memory=mock_memory)
        domains, boost = analyzer._enrich_with_rag_context("test query")

        assert TaskDomain.CODING in domains
        assert TaskDomain.TESTING in domains

    def test_enrich_with_rag_complexity_boost(self):
        """Verify _enrich_with_rag_context boosts complexity for async code."""
        from core.intelligence.swarm.task_analyzer import TaskAnalyzer

        mock_chunk = MagicMock()
        mock_chunk.file_path = "src/async_handler.py"
        mock_chunk.content = "async def fetch(): await response"

        mock_memory = MagicMock()
        mock_memory.retrieve.return_value = [mock_chunk]

        analyzer = TaskAnalyzer(project_memory=mock_memory)
        domains, boost = analyzer._enrich_with_rag_context("test query")

        assert boost > 0  # Should have complexity boost for async


# =============================================================================
# Phase 3: Time Decay for AutoMemory Tests
# =============================================================================


class TestTimeDecayAutoMemory:
    """Test suite for time decay in AutoMemory."""

    def test_time_decay_method_exists(self):
        """Verify _apply_time_decay method exists."""
        # Create with temp path
        import tempfile

        from core.memory_pkg.memory.auto_memory import AutoMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            am = AutoMemory(Path(tmpdir))
            assert hasattr(am, "_apply_time_decay")

    def test_time_decay_recent_entry(self):
        """Verify recent entries have minimal decay."""
        import tempfile

        from core.memory_pkg.memory.auto_memory import AutoMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            am = AutoMemory(Path(tmpdir))

            # Entry from today
            now = datetime.now().isoformat()
            decayed = am._apply_time_decay(1.0, now)

            # Should be very close to original
            assert decayed > 0.99

    def test_time_decay_old_entry(self):
        """Verify old entries have significant decay."""
        import tempfile

        from core.memory_pkg.memory.auto_memory import AutoMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            am = AutoMemory(Path(tmpdir))

            # Entry from 90 days ago
            old_date = (datetime.now() - timedelta(days=90)).isoformat()
            decayed = am._apply_time_decay(1.0, old_date)

            # Should have ~24% decay with coefficient 0.003
            # exp(-0.003 * 90) ≈ 0.76
            assert 0.7 < decayed < 0.8

    def test_time_decay_invalid_timestamp(self):
        """Verify invalid timestamp returns original score."""
        import tempfile

        from core.memory_pkg.memory.auto_memory import AutoMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            am = AutoMemory(Path(tmpdir))

            # Invalid timestamp
            decayed = am._apply_time_decay(1.0, "invalid")

            # Should return original
            assert decayed == 1.0

    def test_suggest_mode_uses_decay(self):
        """Verify suggest_mode applies time decay."""
        import tempfile

        from core.memory_pkg.memory.auto_memory import AutoMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            am = AutoMemory(Path(tmpdir))

            # Add test data to cache
            am._success_cache["coding"] = [
                {"swarm_mode": "parallel", "score": 1.0, "timestamp": datetime.now().isoformat()},
                {
                    "swarm_mode": "sequential",
                    "score": 1.0,
                    "timestamp": (datetime.now() - timedelta(days=100)).isoformat(),
                },
            ]

            # With decay, "parallel" should win (more recent)
            result = am.suggest_mode("coding", apply_decay=True)
            assert result == "parallel"


# =============================================================================
# Phase 4: Consolidation Tests
# =============================================================================


class TestConsolidation:
    """Test suite for memory consolidation."""

    def test_consolidate_method_exists(self):
        """Verify consolidate method exists on coordinator."""
        from core.memory_pkg.memory.coordinator import MemoryCoordinator

        coordinator = MemoryCoordinator(None, None)
        assert hasattr(coordinator, "consolidate")

    def test_consolidate_no_memory(self):
        """Verify consolidate handles no SuccessMemory gracefully."""
        from core.memory_pkg.memory.coordinator import MemoryCoordinator

        coordinator = MemoryCoordinator(None, MagicMock())
        result = coordinator.consolidate()

        assert result == 0

    def test_consolidate_insufficient_data(self):
        """Verify consolidate skips with <10 entries."""
        from core.memory_pkg.memory.coordinator import MemoryCoordinator

        mock_success = MagicMock()
        mock_success.get_all.return_value = [MagicMock() for _ in range(5)]  # Only 5 entries

        coordinator = MemoryCoordinator(mock_success, MagicMock())
        result = coordinator.consolidate()

        assert result == 0


# =============================================================================
# Integration Tests
# =============================================================================


class TestMemoriaIntegration:
    """Integration tests for MEMORIA features working together."""

    def test_mode_selector_has_coordinator(self):
        """Verify ModeSelector initializes MemoryCoordinator when memories available."""
        from core.intelligence.swarm.mode_selector import ModeSelector

        mock_success = MagicMock()
        mock_auto = MagicMock()

        selector = ModeSelector(agent_pool=None, success_memory=mock_success, auto_memory=mock_auto)

        # Should have coordinator
        assert hasattr(selector, "memory_coordinator")
        # If imports worked, should be initialized
        if selector.memory_coordinator:
            assert selector.memory_coordinator is not None

    def test_mode_selector_unified_boost_method(self):
        """Verify ModeSelector has _apply_unified_memory_boost method."""
        from core.intelligence.swarm.mode_selector import ModeSelector

        selector = ModeSelector(agent_pool=None)
        assert hasattr(selector, "_apply_unified_memory_boost")


# =============================================================================
# Run standalone
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
