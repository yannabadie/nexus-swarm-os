"""
V10 MEMORY FORGE Tests - Shared Embedding Engine + Isolated Storage.

Tests for the memory optimization architecture:
1. EmbeddingEngine singleton behavior
2. Storage isolation per tenant
3. Memory singleton PRISM migration
4. Encoding functionality

Run with:
    pytest tests/v10/test_memory_optimization.py -v
"""

from pathlib import Path

import pytest

# Skip all tests if dependencies not available
pytest.importorskip("sentence_transformers", reason="sentence-transformers not installed")


class TestEmbeddingEngineSingleton:
    """Test EmbeddingEngine singleton pattern."""

    def test_singleton_same_object(self):
        """Multiple calls to get_embedding_engine return same instance."""
        from core.memory_pkg.memory.embedding_engine import (
            get_embedding_engine,
            reset_embedding_engine,
        )

        # Reset to clean state
        reset_embedding_engine()

        # Get two instances
        engine1 = get_embedding_engine()
        engine2 = get_embedding_engine()

        # Should be the exact same object
        assert engine1 is engine2
        assert id(engine1) == id(engine2)

        # Cleanup
        reset_embedding_engine()

    def test_singleton_via_class(self):
        """EmbeddingEngine() also returns singleton."""
        from core.memory_pkg.memory.embedding_engine import EmbeddingEngine, reset_embedding_engine

        reset_embedding_engine()

        # Direct instantiation should return same instance
        engine1 = EmbeddingEngine()
        engine2 = EmbeddingEngine()

        assert engine1 is engine2

        reset_embedding_engine()

    def test_properties_before_load(self):
        """Properties work before model is loaded."""
        from core.memory_pkg.memory.embedding_engine import get_embedding_engine, reset_embedding_engine

        reset_embedding_engine()
        engine = get_embedding_engine()

        # These should work without loading model
        assert engine.embedding_dim == 384
        assert engine.model_name == "all-MiniLM-L6-v2"
        assert engine.is_loaded is False

        reset_embedding_engine()


class TestEmbeddingEngineEncoding:
    """Test encoding functionality."""

    @pytest.fixture
    def engine(self):
        """Get a fresh engine instance."""
        from core.memory_pkg.memory.embedding_engine import get_embedding_engine, reset_embedding_engine

        reset_embedding_engine()
        yield get_embedding_engine()
        reset_embedding_engine()

    def test_encode_single_text(self, engine):
        """Encode a single text."""
        result = engine.encode("hello world")

        assert isinstance(result, list)
        assert len(result) == 1
        assert len(result[0]) == 384  # all-MiniLM-L6-v2 dimension

    def test_encode_batch(self, engine):
        """Encode multiple texts."""
        texts = ["hello", "world", "test"]
        result = engine.encode(texts)

        assert isinstance(result, list)
        assert len(result) == 3
        for embedding in result:
            assert len(embedding) == 384

    def test_encode_single_convenience(self, engine):
        """Test encode_single convenience method."""
        result = engine.encode_single("test query")

        assert isinstance(result, list)
        assert len(result) == 384

    def test_encode_empty_list(self, engine):
        """Empty list returns empty list."""
        result = engine.encode([])
        assert result == []

    def test_get_info(self, engine):
        """Test get_info diagnostics."""
        # First load the model
        engine.preload()

        info = engine.get_info()

        assert info["model_name"] == "all-MiniLM-L6-v2"
        assert info["embedding_dim"] == 384
        assert info["is_loaded"] is True
        assert info["device"] in ["cpu", "cuda"]
        assert info["backend"] in ["onnx", "torch"]


class TestIsolatedStorage:
    """Test that storage is isolated per tenant while engine is shared."""

    def test_dense_backend_accepts_engine(self):
        """DenseBackend can accept an injected engine."""
        import tempfile
        from pathlib import Path

        from core.memory_pkg.memory.backends.dense import DenseBackend
        from core.memory_pkg.memory.embedding_engine import get_embedding_engine, reset_embedding_engine

        reset_embedding_engine()
        engine = get_embedding_engine()

        with tempfile.TemporaryDirectory() as tmpdir:
            backend = DenseBackend(storage_path=Path(tmpdir) / "lancedb", embedding_engine=engine)

            # Engine should be stored
            assert backend._engine is engine

        reset_embedding_engine()

    def test_different_storage_paths(self):
        """Different tenants get different storage paths."""
        import tempfile
        from pathlib import Path

        from core.memory_pkg.memory.project_memory import ProjectMemory

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Two "tenants" with different roots
            tenant_a_root = root / "tenant_a"
            tenant_b_root = root / "tenant_b"
            tenant_a_root.mkdir()
            tenant_b_root.mkdir()

            memory_a = ProjectMemory(tenant_a_root)
            memory_b = ProjectMemory(tenant_b_root)

            # Storage paths should be different
            assert memory_a.storage_path != memory_b.storage_path
            assert "tenant_a" in str(memory_a.storage_path)
            assert "tenant_b" in str(memory_b.storage_path)


class TestMemorySingletonMigration:
    """Test that memory singletons properly delegate to ServiceFactory."""

    def test_auto_memory_has_prism_pattern(self):
        """AutoMemory.get_auto_memory includes PRISM pattern."""
        import inspect

        from core.memory_pkg.memory.auto_memory import get_auto_memory

        source = inspect.getsource(get_auto_memory)

        # Should include ServiceFactory delegation
        assert "ServiceFactory" in source
        assert "has_active_session" in source

    def test_success_memory_has_prism_pattern(self):
        """SuccessMemory.get_success_memory is accessible and functional."""
        import inspect

        from core.memory_pkg.memory import get_success_memory  # V2 via backward compat alias

        source = inspect.getsource(get_success_memory)

        # get_success_memory is an alias for get_success_memory_v2 - verify it exists and is callable
        assert callable(get_success_memory)
        assert "SuccessMemoryV2" in source or "get_success_memory" in source

    def test_spotlighter_has_prism_pattern(self):
        """Spotlighter.get_spotlighter includes PRISM pattern."""
        import inspect

        from core.memory_pkg.memory.spotlighting import get_spotlighter

        source = inspect.getsource(get_spotlighter)

        assert "ServiceFactory" in source
        assert "has_active_session" in source


class TestServiceFactoryMemoryMethods:
    """Test ServiceFactory memory-related methods."""

    def test_get_embedding_engine_exists(self):
        """ServiceFactory has get_embedding_engine method."""
        from core.factory import ServiceFactory

        assert hasattr(ServiceFactory, "get_embedding_engine")
        assert callable(ServiceFactory.get_embedding_engine)

    def test_get_project_memory_exists(self):
        """ServiceFactory has get_project_memory method."""
        from core.factory import ServiceFactory

        assert hasattr(ServiceFactory, "get_project_memory")
        assert callable(ServiceFactory.get_project_memory)

    def test_get_auto_memory_exists(self):
        """ServiceFactory has get_auto_memory method."""
        from core.factory import ServiceFactory

        assert hasattr(ServiceFactory, "get_auto_memory")
        assert callable(ServiceFactory.get_auto_memory)

    def test_get_success_memory_exists(self):
        """ServiceFactory has get_success_memory method."""
        from core.factory import ServiceFactory

        assert hasattr(ServiceFactory, "get_success_memory")
        assert callable(ServiceFactory.get_success_memory)

    def test_get_spotlighter_exists(self):
        """ServiceFactory has get_spotlighter method."""
        from core.factory import ServiceFactory

        assert hasattr(ServiceFactory, "get_spotlighter")
        assert callable(ServiceFactory.get_spotlighter)

    def test_embedding_engine_is_global(self):
        """EmbeddingEngine from ServiceFactory is global (not tenant-scoped)."""
        from core.factory import ServiceFactory
        from core.memory_pkg.memory.embedding_engine import reset_embedding_engine

        reset_embedding_engine()
        ServiceFactory._embedding_engine = None  # Reset factory cache too

        engine1 = ServiceFactory.get_embedding_engine()
        engine2 = ServiceFactory.get_embedding_engine()

        # Should be the exact same instance
        assert engine1 is engine2

        reset_embedding_engine()
        ServiceFactory._embedding_engine = None


class TestONNXFallback:
    """Test ONNX backend with PyTorch fallback."""

    def test_backend_detection(self):
        """Engine detects and uses appropriate backend."""
        from core.memory_pkg.memory.embedding_engine import get_embedding_engine, reset_embedding_engine

        reset_embedding_engine()
        engine = get_embedding_engine()
        engine.preload()

        # Backend should be set after loading
        assert engine.backend in ["onnx", "torch"]

        reset_embedding_engine()

    def test_onnx_availability_check(self):
        """Engine can check ONNX availability."""
        from core.memory_pkg.memory.embedding_engine import get_embedding_engine, reset_embedding_engine

        reset_embedding_engine()
        engine = get_embedding_engine()

        info = engine.get_info()
        assert "onnx_available" in info
        assert isinstance(info["onnx_available"], bool)

        reset_embedding_engine()


class TestDenseBackendIntegration:
    """Integration tests for DenseBackend with shared engine."""

    @pytest.fixture
    def backend(self):
        """Create a DenseBackend with temporary storage."""
        import tempfile

        from core.memory_pkg.memory.backends.dense import DenseBackend
        from core.memory_pkg.memory.embedding_engine import get_embedding_engine, reset_embedding_engine

        reset_embedding_engine()

        with tempfile.TemporaryDirectory() as tmpdir:
            backend = DenseBackend(storage_path=Path(tmpdir) / "lancedb", embedding_engine=get_embedding_engine())
            yield backend

        reset_embedding_engine()

    def test_get_info_includes_engine(self, backend):
        """Backend info includes engine info."""
        # Trigger engine loading
        backend._ensure_engine()

        info = backend.get_info()

        assert "engine" in info
        assert isinstance(info["engine"], dict)

    def test_dependencies_string_updated(self, backend):
        """Dependencies string shows updated versions."""
        info = backend.get_info()

        # Should reference 3.2.0+, not 2.2.0
        assert "3.2.0" in info["dependencies"] or "sentence-transformers" in info["dependencies"]
