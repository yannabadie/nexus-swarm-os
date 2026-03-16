"""
Simple smoke tests for Memory V2 implementations (V12.4.1 - Epic 1.4)

These are lightweight tests that validate the API exists and has correct signatures.
Full integration testing with real LanceDB requires optional dependencies.

Author: Claude Opus 4.6
Date: 2026-02-17
Epic: 1.4 (Persistance Stratégique - LanceDB-backed memory)
"""

# Validates that the imports work
from core.memory_pkg.memory import (
    BlacklistedStrategy,
    StrategyBlacklistV2,
    SuccessMemoryV2,
    get_strategy_blacklist_v2,
    get_success_memory_v2,
    reset_strategy_blacklist_v2,
    reset_success_memory_v2,
)
from core.memory_pkg.memory.types import Chunk


class TestSuccessMemoryV2API:
    """Validate that SuccessMemoryV2 has correct API."""

    def test_class_exists(self):
        """SuccessMemoryV2 should be importable."""
        assert SuccessMemoryV2 is not None

    def test_has_record_success_method(self):
        """Should have record_success method."""
        assert hasattr(SuccessMemoryV2, "record_success")
        assert callable(SuccessMemoryV2.record_success)

    def test_has_find_similar_tasks_method(self):
        """Should have find_similar_tasks method (semantic search)."""
        assert hasattr(SuccessMemoryV2, "find_similar_tasks")
        assert callable(SuccessMemoryV2.find_similar_tasks)

    def test_has_get_best_mode_method(self):
        """Should have get_best_mode_for_similar method."""
        assert hasattr(SuccessMemoryV2, "get_best_mode_for_similar")
        assert callable(SuccessMemoryV2.get_best_mode_for_similar)

    def test_has_get_all_method(self):
        """Should have get_all method."""
        assert hasattr(SuccessMemoryV2, "get_all")
        assert callable(SuccessMemoryV2.get_all)

    def test_has_get_stats_method(self):
        """Should have get_stats method."""
        assert hasattr(SuccessMemoryV2, "get_stats")
        assert callable(SuccessMemoryV2.get_stats)

    def test_has_clear_method(self):
        """Should have clear method."""
        assert hasattr(SuccessMemoryV2, "clear")
        assert callable(SuccessMemoryV2.clear)

    def test_record_success_signature(self):
        """record_success should have correct signature."""
        import inspect

        sig = inspect.signature(SuccessMemoryV2.record_success)
        params = list(sig.parameters.keys())

        # Should have: self, task_id, analysis, result, quality_score
        assert "self" in params
        assert "task_id" in params
        assert "analysis" in params
        assert "result" in params
        assert "quality_score" in params

    def test_find_similar_tasks_signature(self):
        """find_similar_tasks should have correct signature."""
        import inspect

        sig = inspect.signature(SuccessMemoryV2.find_similar_tasks)
        params = list(sig.parameters.keys())

        # Should have: self, query, limit, min_score
        assert "self" in params
        assert "query" in params
        assert "limit" in params
        assert "min_score" in params

    def test_global_access_functions(self):
        """Should have global access functions."""
        assert get_success_memory_v2 is not None
        assert callable(get_success_memory_v2)
        assert reset_success_memory_v2 is not None
        assert callable(reset_success_memory_v2)


class TestStrategyBlacklistV2API:
    """Validate that StrategyBlacklistV2 has correct API."""

    def test_class_exists(self):
        """StrategyBlacklistV2 should be importable."""
        assert StrategyBlacklistV2 is not None

    def test_blacklisted_strategy_dataclass(self):
        """BlacklistedStrategy should be a dataclass."""
        from dataclasses import is_dataclass

        assert is_dataclass(BlacklistedStrategy)

    def test_has_add_failed_strategy_method(self):
        """Should have add_failed_strategy method."""
        assert hasattr(StrategyBlacklistV2, "add_failed_strategy")
        assert callable(StrategyBlacklistV2.add_failed_strategy)

    def test_has_is_blacklisted_method(self):
        """Should have is_blacklisted method (semantic check)."""
        assert hasattr(StrategyBlacklistV2, "is_blacklisted")
        assert callable(StrategyBlacklistV2.is_blacklisted)

    def test_has_suggest_alternatives_method(self):
        """Should have suggest_alternatives method."""
        assert hasattr(StrategyBlacklistV2, "suggest_alternatives")
        assert callable(StrategyBlacklistV2.suggest_alternatives)

    def test_has_get_all_method(self):
        """Should have get_all method."""
        assert hasattr(StrategyBlacklistV2, "get_all")
        assert callable(StrategyBlacklistV2.get_all)

    def test_has_get_stats_method(self):
        """Should have get_stats method."""
        assert hasattr(StrategyBlacklistV2, "get_stats")
        assert callable(StrategyBlacklistV2.get_stats)

    def test_has_clear_method(self):
        """Should have clear method."""
        assert hasattr(StrategyBlacklistV2, "clear")
        assert callable(StrategyBlacklistV2.clear)

    def test_add_failed_strategy_signature(self):
        """add_failed_strategy should have correct signature."""
        import inspect

        sig = inspect.signature(StrategyBlacklistV2.add_failed_strategy)
        params = list(sig.parameters.keys())

        # Should have: self, description, swarm_mode, error_message, retry_count, complexity, domains
        assert "self" in params
        assert "description" in params
        assert "swarm_mode" in params
        assert "error_message" in params
        assert "retry_count" in params
        assert "complexity" in params
        assert "domains" in params

    def test_is_blacklisted_signature(self):
        """is_blacklisted should have correct signature."""
        import inspect

        sig = inspect.signature(StrategyBlacklistV2.is_blacklisted)
        params = list(sig.parameters.keys())

        # Should have: self, description, swarm_mode
        assert "self" in params
        assert "description" in params
        assert "swarm_mode" in params

    def test_is_blacklisted_returns_tuple(self):
        """is_blacklisted should return (bool, Optional[str])."""
        import inspect

        sig = inspect.signature(StrategyBlacklistV2.is_blacklisted)
        # Check return annotation if present
        if sig.return_annotation != inspect.Signature.empty:
            # Should be Tuple[bool, Optional[str]]
            assert "Tuple" in str(sig.return_annotation) or "tuple" in str(sig.return_annotation)

    def test_global_access_functions(self):
        """Should have global access functions."""
        assert get_strategy_blacklist_v2 is not None
        assert callable(get_strategy_blacklist_v2)
        assert reset_strategy_blacklist_v2 is not None
        assert callable(reset_strategy_blacklist_v2)


class TestChunkMetadataSupport:
    """Validate that Chunk dataclass supports metadata field."""

    def test_chunk_has_metadata_field(self):
        """Chunk should have optional metadata field."""
        import inspect

        sig = inspect.signature(Chunk.__init__)
        params = list(sig.parameters.keys())

        assert "metadata" in params

    def test_chunk_metadata_optional(self):
        """Chunk metadata should be optional (default None)."""
        # Create chunk without metadata
        chunk = Chunk(file_path="test.py", start_line=1, end_line=10, content="test content")

        assert chunk.metadata is None

    def test_chunk_metadata_can_be_dict(self):
        """Chunk metadata should accept dict."""
        metadata = {"task_id": "123", "quality_score": 0.95}

        chunk = Chunk(file_path="test.py", start_line=1, end_line=10, content="test content", metadata=metadata)

        assert chunk.metadata == metadata
        assert chunk.metadata["task_id"] == "123"
        assert chunk.metadata["quality_score"] == 0.95

    def test_chunk_to_dict_includes_metadata(self):
        """Chunk.to_dict() should include metadata if present."""
        metadata = {"task_id": "123"}

        chunk = Chunk(file_path="test.py", start_line=1, end_line=10, content="test content", metadata=metadata)

        chunk_dict = chunk.to_dict()
        assert "metadata" in chunk_dict
        assert chunk_dict["metadata"] == metadata

    def test_chunk_from_dict_loads_metadata(self):
        """Chunk.from_dict() should load metadata if present."""
        data = {
            "file_path": "test.py",
            "start_line": 1,
            "end_line": 10,
            "content": "test content",
            "metadata": {"task_id": "123"},
        }

        chunk = Chunk.from_dict(data)
        assert chunk.metadata is not None
        assert chunk.metadata["task_id"] == "123"


class TestV2Architecture:
    """Validate architectural decisions of V2 implementations."""

    def test_v2_uses_project_memory_backend(self):
        """V2 classes should use ProjectMemory as backend."""
        import inspect

        # SuccessMemoryV2 should have project_memory attribute
        success_source = inspect.getsource(SuccessMemoryV2.__init__)
        assert "ProjectMemory" in success_source

        # StrategyBlacklistV2 should have project_memory attribute
        blacklist_source = inspect.getsource(StrategyBlacklistV2.__init__)
        assert "ProjectMemory" in blacklist_source

    def test_v2_has_migration_logic(self):
        """V2 classes should have V1->V2 migration logic."""
        import inspect

        # SuccessMemoryV2 should have _migrate_from_v1 method
        assert hasattr(SuccessMemoryV2, "_migrate_from_v1")
        success_source = inspect.getsource(SuccessMemoryV2._migrate_from_v1)
        assert "migration_marker" in success_source

        # StrategyBlacklistV2 should have _migrate_from_v1 method
        assert hasattr(StrategyBlacklistV2, "_migrate_from_v1")
        blacklist_source = inspect.getsource(StrategyBlacklistV2._migrate_from_v1)
        assert "migration_marker" in blacklist_source

    def test_v2_virtual_file_prefix(self):
        """V2 classes should use virtual file prefixes for LanceDB."""
        # SuccessMemoryV2
        assert hasattr(SuccessMemoryV2, "VIRTUAL_FILE_PREFIX")
        assert SuccessMemoryV2.VIRTUAL_FILE_PREFIX == "success_memory://"

        # StrategyBlacklistV2
        assert hasattr(StrategyBlacklistV2, "VIRTUAL_FILE_PREFIX")
        assert StrategyBlacklistV2.VIRTUAL_FILE_PREFIX == "strategy_blacklist://"

    def test_v2_similarity_thresholds(self):
        """V2 classes should have appropriate similarity thresholds."""
        # StrategyBlacklistV2 should have lower threshold (semantic is more precise)
        assert hasattr(StrategyBlacklistV2, "SIMILARITY_THRESHOLD")
        assert StrategyBlacklistV2.SIMILARITY_THRESHOLD == 0.65  # Lower than V1 (0.85)


# Note: Full integration tests require:
# - LanceDB installed (pip install lancedb)
# - sentence-transformers installed (pip install sentence-transformers)
# - Sufficient disk space for vector storage
#
# These can be run manually with:
# pytest tests/test_memory_v2_integration.py -v
#
# (to be created when dependencies are available in CI/CD)
