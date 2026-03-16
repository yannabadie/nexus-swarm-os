"""
NEXUS V7.9 - Dense Backend Tests (Phase 10g)

Tests for LanceDB + Sentence-Transformers semantic retrieval backend.
Tests are skipped if dependencies (lancedb, sentence-transformers) are not installed.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

# Import availability flags
from core.memory_pkg.memory.backends import LANCEDB_AVAILABLE, SENTENCE_TRANSFORMERS_AVAILABLE, DenseBackend
from core.memory_pkg.memory.types import Chunk

# Skip all tests if dependencies not available
DENSE_AVAILABLE = LANCEDB_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE
pytestmark = pytest.mark.skipif(
    not DENSE_AVAILABLE, reason="Dense backend dependencies not installed (lancedb, sentence-transformers)"
)


@pytest.fixture
def temp_storage():
    """Create a temporary directory for LanceDB storage."""
    temp_dir = tempfile.mkdtemp(prefix="nexus_test_dense_")
    yield Path(temp_dir)
    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_chunks():
    """Create sample chunks for testing."""
    return [
        Chunk(
            file_path="src/auth.py",
            start_line=1,
            end_line=20,
            content="def authenticate_user(username, password):\n    '''Authenticate user credentials.'''\n    if not validate_credentials(username, password):\n        raise AuthenticationError('Invalid credentials')\n    return create_session(username)",
            terms={"authenticate", "user", "username", "password", "validate", "credentials"},
            chunk_type="function",
            name="authenticate_user",
        ),
        Chunk(
            file_path="src/auth.py",
            start_line=25,
            end_line=40,
            content="def create_session(username):\n    '''Create a new session for authenticated user.'''\n    session_id = generate_uuid()\n    store_session(session_id, username)\n    return session_id",
            terms={"create", "session", "username", "generate", "uuid", "store"},
            chunk_type="function",
            name="create_session",
        ),
        Chunk(
            file_path="src/database.py",
            start_line=1,
            end_line=30,
            content="class DatabaseConnection:\n    '''Manage database connections.'''\n    def connect(self):\n        self.conn = psycopg2.connect(self.dsn)\n    def disconnect(self):\n        self.conn.close()",
            terms={"database", "connection", "connect", "disconnect", "psycopg2"},
            chunk_type="class",
            name="DatabaseConnection",
        ),
        Chunk(
            file_path="src/utils.py",
            start_line=1,
            end_line=15,
            content="def validate_email(email):\n    '''Validate email format.'''\n    import re\n    pattern = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\\.[a-zA-Z0-9-.]+$'\n    return bool(re.match(pattern, email))",
            terms={"validate", "email", "format", "regex", "pattern"},
            chunk_type="function",
            name="validate_email",
        ),
    ]


class TestDenseBackendAvailability:
    """Test backend availability detection."""

    def test_is_available_when_deps_installed(self):
        """Test is_available returns True when deps are installed."""
        # If we're running these tests, deps must be installed
        assert DenseBackend.is_available() is True

    def test_lancedb_available(self):
        """Test LanceDB is importable."""
        assert LANCEDB_AVAILABLE is True

    def test_sentence_transformers_available(self):
        """Test Sentence-Transformers is importable."""
        assert SENTENCE_TRANSFORMERS_AVAILABLE is True


class TestDenseBackendInit:
    """Test backend initialization."""

    def test_init_creates_backend(self, temp_storage):
        """Test backend initializes without errors."""
        backend = DenseBackend(temp_storage / "lancedb")
        assert backend is not None
        assert backend.name == "dense"

    def test_init_not_ready_before_index(self, temp_storage):
        """Test backend is not ready before indexing."""
        backend = DenseBackend(temp_storage / "lancedb")
        assert backend.is_ready is False

    def test_get_info_before_index(self, temp_storage):
        """Test get_info works before indexing."""
        backend = DenseBackend(temp_storage / "lancedb")
        info = backend.get_info()
        assert info["backend"] == "dense"
        assert info["lancedb_available"] is True
        assert info["sentence_transformers_available"] is True
        assert info["index_built"] is False


class TestDenseBackendIndexing:
    """Test chunk indexing."""

    def test_build_index_empty(self, temp_storage):
        """Test indexing with no chunks."""
        backend = DenseBackend(temp_storage / "lancedb")
        backend.build_index([])
        assert backend.is_ready is False

    def test_build_index_with_chunks(self, temp_storage, sample_chunks):
        """Test indexing chunks successfully."""
        backend = DenseBackend(temp_storage / "lancedb")
        backend.build_index(sample_chunks)
        assert backend.is_ready is True

        info = backend.get_info()
        assert info["index_built"] is True
        assert info["chunk_count"] == len(sample_chunks)

    def test_rebuild_index_replaces_old(self, temp_storage, sample_chunks):
        """Test rebuilding index replaces previous data."""
        backend = DenseBackend(temp_storage / "lancedb")

        # First index
        backend.build_index(sample_chunks)
        assert backend.get_info()["chunk_count"] == 4

        # Rebuild with fewer chunks
        backend.build_index(sample_chunks[:2])
        assert backend.get_info()["chunk_count"] == 2


class TestDenseBackendRetrieval:
    """Test semantic retrieval."""

    def test_retrieve_requires_raw_query(self, temp_storage, sample_chunks):
        """Test retrieval requires raw_query parameter."""
        backend = DenseBackend(temp_storage / "lancedb")
        backend.build_index(sample_chunks)

        # Without raw_query should return empty
        results = backend.retrieve(query_terms=["auth"], chunks=sample_chunks, limit=5, min_score=0.0, raw_query=None)
        assert results == []

    def test_retrieve_semantic_match(self, temp_storage, sample_chunks):
        """Test semantic retrieval finds related content."""
        backend = DenseBackend(temp_storage / "lancedb")
        backend.build_index(sample_chunks)

        # Query about authentication
        results = backend.retrieve(
            query_terms=[], chunks=sample_chunks, limit=2, min_score=0.0, raw_query="How do I authenticate a user?"
        )

        assert len(results) > 0
        # Should find auth-related chunks
        auth_chunks = [c for c in results if "auth" in c.file_path]
        assert len(auth_chunks) > 0

    def test_retrieve_respects_limit(self, temp_storage, sample_chunks):
        """Test retrieval respects limit parameter."""
        backend = DenseBackend(temp_storage / "lancedb")
        backend.build_index(sample_chunks)

        results = backend.retrieve(
            query_terms=[], chunks=sample_chunks, limit=1, min_score=0.0, raw_query="database connection"
        )

        assert len(results) <= 1

    def test_retrieve_empty_index(self, temp_storage, sample_chunks):
        """Test retrieval on empty index returns empty."""
        backend = DenseBackend(temp_storage / "lancedb")
        # Don't build index

        results = backend.retrieve(query_terms=[], chunks=sample_chunks, limit=5, min_score=0.0, raw_query="test query")

        assert results == []


class TestDenseBackendClear:
    """Test clearing the index."""

    def test_clear_removes_index(self, temp_storage, sample_chunks):
        """Test clear removes the index."""
        backend = DenseBackend(temp_storage / "lancedb")
        backend.build_index(sample_chunks)
        assert backend.is_ready is True

        backend.clear()
        assert backend.is_ready is False
        assert backend.get_info()["chunk_count"] == 0


class TestDenseBackendPersistence:
    """Test index persistence across instances."""

    def test_index_persists_to_disk(self, temp_storage, sample_chunks):
        """Test that indexed data persists to disk."""
        storage_path = temp_storage / "lancedb"

        # Create and index
        backend1 = DenseBackend(storage_path)
        backend1.build_index(sample_chunks)
        assert backend1.get_info()["chunk_count"] == 4

        # Create new instance with same path
        backend2 = DenseBackend(storage_path)
        # Should load existing index
        info = backend2.get_info()
        assert info["chunk_count"] == 4 or info["index_built"] is True


class TestDenseBackendSemanticCapabilities:
    """Test semantic understanding capabilities."""

    def test_semantic_synonym_matching(self, temp_storage, sample_chunks):
        """Test that semantic search handles synonyms/related concepts."""
        backend = DenseBackend(temp_storage / "lancedb")
        backend.build_index(sample_chunks)

        # Query using different words than in the content
        # "login" should match "authenticate"
        results = backend.retrieve(
            query_terms=[], chunks=sample_chunks, limit=3, min_score=0.0, raw_query="user login process"
        )

        # Should find authentication-related chunk
        assert len(results) > 0
        found_auth = any("authenticate" in c.content.lower() for c in results)
        assert found_auth, "Semantic search should find 'authenticate' for 'login' query"

    def test_semantic_database_query(self, temp_storage, sample_chunks):
        """Test semantic search for database concepts."""
        backend = DenseBackend(temp_storage / "lancedb")
        backend.build_index(sample_chunks)

        results = backend.retrieve(
            query_terms=[], chunks=sample_chunks, limit=2, min_score=0.0, raw_query="SQL database management"
        )

        assert len(results) > 0
        # Should rank database chunk highly
        db_in_top = any("database" in c.file_path.lower() for c in results)
        assert db_in_top


# Integration test with ProjectMemory (if DenseBackend becomes primary)
class TestDenseBackendIntegration:
    """Integration tests with ProjectMemory facade."""

    def test_backend_selection_with_env_var(self, temp_storage, monkeypatch):
        """Test backend selection via environment variable."""
        from core.memory_pkg.memory import ProjectMemory

        # Force dense backend selection
        monkeypatch.setenv("PROJECT_MEMORY_BACKEND", "dense")

        memory = ProjectMemory(temp_storage)
        info = memory.get_backend_info()

        assert info["backend"] == "dense"
