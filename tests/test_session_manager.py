"""
Unit tests for SwarmSessionManager - Phase 7 Session Isolation.

NEXUS V7.5 HIVE MIND - Session isolation to prevent "Context Bleeding".

Tests cover:
- Task creation and management
- Session UUID generation
- Session isolation per agent-role
- Persistence and recovery
- Cleanup and statistics
- Thread safety

Author: Claude (NEXUS V7.5)
Date: 2025-12-04
"""

import json
import shutil

# Add parent to path for imports
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest import TestCase, main

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.swarm.session_manager import (
    AgentSession,
    SessionMode,
    SessionStatus,
    SwarmSessionManager,
    TaskSession,
    generate_task_id,
)


class TestAgentSession(TestCase):
    """Tests for AgentSession dataclass."""

    def test_create_agent_session(self):
        """Test creating an AgentSession."""
        session = AgentSession(agent_id="gemini", session_uuid="test-uuid-123", role="lead")

        assert session.agent_id == "gemini"
        assert session.session_uuid == "test-uuid-123"
        assert session.role == "lead"
        assert session.status == SessionStatus.ACTIVE
        assert session.mode == SessionMode.FRESH
        assert session.parent_session_uuid is None

    def test_agent_session_to_dict(self):
        """Test serialization to dictionary."""
        session = AgentSession(
            agent_id="claude",
            session_uuid="uuid-456",
            role="worker",
            status=SessionStatus.COMPLETED,
            mode=SessionMode.BRANCH,
            parent_session_uuid="parent-uuid",
        )

        data = session.to_dict()

        assert data["agent_id"] == "claude"
        assert data["session_uuid"] == "uuid-456"
        assert data["role"] == "worker"
        assert data["status"] == "completed"
        assert data["mode"] == "branch"
        assert data["parent_session_uuid"] == "parent-uuid"

    def test_agent_session_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "agent_id": "gemini",
            "session_uuid": "uuid-789",
            "role": "support",
            "status": "failed",
            "mode": "continue",
            "created_at": "2025-12-04T10:00:00",
            "parent_session_uuid": None,
        }

        session = AgentSession.from_dict(data)

        assert session.agent_id == "gemini"
        assert session.session_uuid == "uuid-789"
        assert session.role == "support"
        assert session.status == SessionStatus.FAILED
        assert session.mode == SessionMode.CONTINUE


class TestTaskSession(TestCase):
    """Tests for TaskSession dataclass."""

    def test_create_task_session(self):
        """Test creating a TaskSession."""
        task = TaskSession(task_id="task_001", swarm_mode="PARALLEL")

        assert task.task_id == "task_001"
        assert task.swarm_mode == "PARALLEL"
        assert task.status == SessionStatus.ACTIVE
        assert task.roles == {}
        assert task.metadata == {}

    def test_task_session_with_roles(self):
        """Test TaskSession with agent sessions."""
        session1 = AgentSession(agent_id="gemini", session_uuid="uuid-1", role="lead")
        session2 = AgentSession(agent_id="claude", session_uuid="uuid-2", role="support")

        task = TaskSession(task_id="task_002", swarm_mode="LEAD_SUPPORT", roles={"lead": session1, "support": session2})

        assert len(task.roles) == 2
        assert task.roles["lead"].agent_id == "gemini"
        assert task.roles["support"].agent_id == "claude"

    def test_task_session_to_dict(self):
        """Test TaskSession serialization."""
        session = AgentSession(agent_id="gemini", session_uuid="uuid-1", role="lead")
        task = TaskSession(
            task_id="task_003", swarm_mode="SEQUENTIAL", roles={"lead": session}, metadata={"priority": "high"}
        )

        data = task.to_dict()

        assert data["task_id"] == "task_003"
        assert data["swarm_mode"] == "SEQUENTIAL"
        assert "lead" in data["roles"]
        assert data["metadata"]["priority"] == "high"

    def test_task_session_from_dict(self):
        """Test TaskSession deserialization."""
        data = {
            "task_id": "task_004",
            "swarm_mode": "PING_PONG",
            "status": "completed",
            "created_at": "2025-12-04T10:00:00",
            "completed_at": "2025-12-04T11:00:00",
            "roles": {
                "lead": {
                    "agent_id": "gemini",
                    "session_uuid": "uuid-1",
                    "role": "lead",
                    "status": "completed",
                    "mode": "fresh",
                }
            },
            "metadata": {},
        }

        task = TaskSession.from_dict(data)

        assert task.task_id == "task_004"
        assert task.swarm_mode == "PING_PONG"
        assert task.status == SessionStatus.COMPLETED
        assert len(task.roles) == 1


class TestSwarmSessionManagerBasic(TestCase):
    """Basic functionality tests for SwarmSessionManager."""

    def setUp(self):
        """Create a temporary workspace."""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)

    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_creates_manager(self):
        """Test that SwarmSessionManager initializes correctly."""
        manager = SwarmSessionManager(self.workspace)

        assert manager.workspace_path == self.workspace
        assert manager.registry_path == self.workspace / ".nexus" / "session_registry.json"

    def test_create_task(self):
        """Test creating a new task."""
        manager = SwarmSessionManager(self.workspace)

        task = manager.create_task("task_001", "PARALLEL")

        assert task.task_id == "task_001"
        assert task.swarm_mode == "PARALLEL"
        assert task.status == SessionStatus.ACTIVE

    def test_create_task_with_metadata(self):
        """Test creating a task with metadata."""
        manager = SwarmSessionManager(self.workspace)

        task = manager.create_task("task_002", "SEQUENTIAL", metadata={"priority": "high", "user": "test"})

        assert task.metadata["priority"] == "high"
        assert task.metadata["user"] == "test"

    def test_create_duplicate_task_raises(self):
        """Test that creating duplicate task raises ValueError."""
        manager = SwarmSessionManager(self.workspace)
        manager.create_task("task_001", "PARALLEL")

        with pytest.raises(ValueError) as exc:
            manager.create_task("task_001", "SEQUENTIAL")

        assert "already exists" in str(exc.value)

    def test_get_task(self):
        """Test retrieving a task by ID."""
        manager = SwarmSessionManager(self.workspace)
        manager.create_task("task_001", "PARALLEL")

        task = manager.get_task("task_001")

        assert task is not None
        assert task.task_id == "task_001"

    def test_get_nonexistent_task(self):
        """Test that get_task returns None for nonexistent task."""
        manager = SwarmSessionManager(self.workspace)

        task = manager.get_task("nonexistent")

        assert task is None

    def test_get_or_create_task(self):
        """Test get_or_create_task creates if not exists."""
        manager = SwarmSessionManager(self.workspace)

        # First call creates
        task1 = manager.get_or_create_task("task_001", "PARALLEL")
        # Second call returns existing
        task2 = manager.get_or_create_task("task_001", "SEQUENTIAL")

        assert task1.task_id == task2.task_id
        assert task1.swarm_mode == "PARALLEL"  # Original mode preserved


class TestSwarmSessionManagerSessions(TestCase):
    """Tests for session management."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)
        self.manager = SwarmSessionManager(self.workspace)
        self.manager.create_task("task_001", "PARALLEL")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_or_create_session(self):
        """Test creating a session for a task."""
        uuid = self.manager.get_or_create_session("task_001", "lead", "gemini")

        assert uuid is not None
        assert len(uuid) == 36  # UUID format

    def test_get_or_create_session_returns_same_uuid(self):
        """Test that same role returns same UUID."""
        uuid1 = self.manager.get_or_create_session("task_001", "lead", "gemini")
        uuid2 = self.manager.get_or_create_session("task_001", "lead", "gemini")

        assert uuid1 == uuid2

    def test_different_roles_get_different_uuids(self):
        """Test that different roles get different UUIDs."""
        uuid_lead = self.manager.get_or_create_session("task_001", "lead", "gemini")
        uuid_support = self.manager.get_or_create_session("task_001", "support", "claude")

        assert uuid_lead != uuid_support

    def test_session_not_found_raises(self):
        """Test that session for nonexistent task raises."""
        with pytest.raises(ValueError) as exc:
            self.manager.get_or_create_session("nonexistent", "lead", "gemini")

        assert "not found" in str(exc.value)

    def test_get_session(self):
        """Test retrieving a session by task and role."""
        self.manager.get_or_create_session("task_001", "lead", "gemini")

        session = self.manager.get_session("task_001", "lead")

        assert session is not None
        assert session.agent_id == "gemini"
        assert session.role == "lead"

    def test_get_session_nonexistent(self):
        """Test get_session returns None for nonexistent."""
        session = self.manager.get_session("task_001", "nonexistent_role")
        assert session is None

    def test_get_session_by_uuid(self):
        """Test finding session by UUID."""
        uuid = self.manager.get_or_create_session("task_001", "lead", "gemini")

        session = self.manager.get_session_by_uuid(uuid)

        assert session is not None
        assert session.session_uuid == uuid
        assert session.agent_id == "gemini"

    def test_get_session_by_uuid_not_found(self):
        """Test get_session_by_uuid returns None for unknown UUID."""
        session = self.manager.get_session_by_uuid("nonexistent-uuid")
        assert session is None

    def test_session_with_branch_mode(self):
        """Test creating a branched session."""
        uuid_original = self.manager.get_or_create_session("task_001", "lead", "gemini")

        # Create branched session in another task
        self.manager.create_task("task_002", "SEQUENTIAL")
        self.manager.get_or_create_session(
            "task_002", "lead", "gemini", mode=SessionMode.BRANCH, parent_session_uuid=uuid_original
        )

        session = self.manager.get_session("task_002", "lead")
        assert session.mode == SessionMode.BRANCH
        assert session.parent_session_uuid == uuid_original


class TestSwarmSessionManagerPersistence(TestCase):
    """Tests for persistence and recovery."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_data_persists_to_disk(self):
        """Test that data is saved to disk."""
        manager = SwarmSessionManager(self.workspace)
        manager.create_task("task_001", "PARALLEL")
        manager.get_or_create_session("task_001", "lead", "gemini")

        # Check file exists
        registry_path = self.workspace / ".nexus" / "session_registry.json"
        assert registry_path.exists()

        # Check content
        with open(registry_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "tasks" in data
        assert "task_001" in data["tasks"]

    def test_data_survives_restart(self):
        """Test that data survives manager restart."""
        # Create manager and data
        manager1 = SwarmSessionManager(self.workspace)
        manager1.create_task("task_001", "PARALLEL")
        uuid = manager1.get_or_create_session("task_001", "lead", "gemini")

        # Create new manager instance
        manager2 = SwarmSessionManager(self.workspace)

        # Data should be loaded
        task = manager2.get_task("task_001")
        assert task is not None
        assert task.swarm_mode == "PARALLEL"

        session = manager2.get_session("task_001", "lead")
        assert session is not None
        assert session.session_uuid == uuid

    def test_get_same_uuid_after_restart(self):
        """Test that same role returns same UUID after restart."""
        manager1 = SwarmSessionManager(self.workspace)
        manager1.create_task("task_001", "PARALLEL")
        uuid1 = manager1.get_or_create_session("task_001", "lead", "gemini")

        # Restart
        manager2 = SwarmSessionManager(self.workspace)
        uuid2 = manager2.get_or_create_session("task_001", "lead", "gemini")

        assert uuid1 == uuid2


class TestSwarmSessionManagerLifecycle(TestCase):
    """Tests for task and session lifecycle."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)
        self.manager = SwarmSessionManager(self.workspace)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_complete_task(self):
        """Test marking a task as completed."""
        self.manager.create_task("task_001", "PARALLEL")
        self.manager.get_or_create_session("task_001", "lead", "gemini")

        result = self.manager.complete_task("task_001")

        assert result is True
        task = self.manager.get_task("task_001")
        assert task.status == SessionStatus.COMPLETED
        assert task.completed_at is not None

    def test_complete_task_marks_sessions(self):
        """Test that completing task marks all sessions."""
        self.manager.create_task("task_001", "PARALLEL")
        self.manager.get_or_create_session("task_001", "lead", "gemini")
        self.manager.get_or_create_session("task_001", "support", "claude")

        self.manager.complete_task("task_001")

        lead = self.manager.get_session("task_001", "lead")
        support = self.manager.get_session("task_001", "support")
        assert lead.status == SessionStatus.COMPLETED
        assert support.status == SessionStatus.COMPLETED

    def test_complete_nonexistent_task(self):
        """Test completing nonexistent task returns False."""
        result = self.manager.complete_task("nonexistent")
        assert result is False

    def test_complete_session_individually(self):
        """Test marking individual session as completed."""
        self.manager.create_task("task_001", "PARALLEL")
        self.manager.get_or_create_session("task_001", "lead", "gemini")
        self.manager.get_or_create_session("task_001", "support", "claude")

        result = self.manager.complete_session("task_001", "lead")

        assert result is True
        lead = self.manager.get_session("task_001", "lead")
        support = self.manager.get_session("task_001", "support")
        assert lead.status == SessionStatus.COMPLETED
        assert support.status == SessionStatus.ACTIVE  # Still active

    def test_list_active_sessions(self):
        """Test listing active sessions."""
        self.manager.create_task("task_001", "PARALLEL")
        self.manager.get_or_create_session("task_001", "lead", "gemini")
        self.manager.get_or_create_session("task_001", "support", "claude")

        sessions = self.manager.list_active_sessions()

        assert len(sessions) == 2
        assert any(s["role"] == "lead" for s in sessions)
        assert any(s["role"] == "support" for s in sessions)

    def test_list_active_sessions_excludes_completed(self):
        """Test that completed sessions are excluded."""
        self.manager.create_task("task_001", "PARALLEL")
        self.manager.get_or_create_session("task_001", "lead", "gemini")
        self.manager.complete_task("task_001")

        sessions = self.manager.list_active_sessions()

        assert len(sessions) == 0

    def test_list_active_tasks(self):
        """Test listing active tasks."""
        self.manager.create_task("task_001", "PARALLEL")
        self.manager.create_task("task_002", "SEQUENTIAL")
        self.manager.complete_task("task_001")

        active = self.manager.list_active_tasks()

        assert len(active) == 1
        assert active[0].task_id == "task_002"


class TestSwarmSessionManagerCleanup(TestCase):
    """Tests for cleanup operations."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)
        self.manager = SwarmSessionManager(self.workspace)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cleanup_completed_tasks(self):
        """Test cleanup of old completed tasks."""
        # Create and complete a task
        self.manager.create_task("task_001", "PARALLEL")
        self.manager.complete_task("task_001")

        # Manually set completed_at to old date
        task = self.manager._tasks["task_001"]
        from datetime import datetime, timedelta

        old_time = datetime.now() - timedelta(hours=48)
        task.completed_at = old_time.isoformat()
        self.manager._save_registry()

        # Cleanup with 24 hour threshold
        removed = self.manager.cleanup_completed(max_age_hours=24)

        assert removed == 1
        assert self.manager.get_task("task_001") is None

    def test_cleanup_keeps_recent_tasks(self):
        """Test that recent completed tasks are kept."""
        self.manager.create_task("task_001", "PARALLEL")
        self.manager.complete_task("task_001")

        # Cleanup - task is recent, should be kept
        removed = self.manager.cleanup_completed(max_age_hours=24)

        assert removed == 0
        assert self.manager.get_task("task_001") is not None

    def test_cleanup_ignores_active_tasks(self):
        """Test that active tasks are never cleaned up."""
        self.manager.create_task("task_001", "PARALLEL")

        removed = self.manager.cleanup_completed(max_age_hours=0)  # Even 0 hours

        assert removed == 0
        assert self.manager.get_task("task_001") is not None


class TestSwarmSessionManagerStats(TestCase):
    """Tests for statistics."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)
        self.manager = SwarmSessionManager(self.workspace)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_stats_empty(self):
        """Test stats for empty manager."""
        stats = self.manager.get_stats()

        assert stats["total_tasks"] == 0
        assert stats["active_tasks"] == 0
        assert stats["completed_tasks"] == 0
        assert stats["total_sessions"] == 0
        assert stats["active_sessions"] == 0

    def test_get_stats_with_data(self):
        """Test stats with tasks and sessions."""
        self.manager.create_task("task_001", "PARALLEL")
        self.manager.create_task("task_002", "SEQUENTIAL")
        self.manager.get_or_create_session("task_001", "lead", "gemini")
        self.manager.get_or_create_session("task_001", "support", "claude")
        self.manager.get_or_create_session("task_002", "lead", "gemini")
        self.manager.complete_task("task_001")

        stats = self.manager.get_stats()

        assert stats["total_tasks"] == 2
        assert stats["active_tasks"] == 1
        assert stats["completed_tasks"] == 1
        assert stats["total_sessions"] == 3
        assert stats["active_sessions"] == 1  # Only task_002's lead

    def test_repr(self):
        """Test string representation."""
        self.manager.create_task("task_001", "PARALLEL")

        repr_str = repr(self.manager)

        assert "SwarmSessionManager" in repr_str
        assert "tasks=1" in repr_str


class TestSwarmSessionManagerConcurrency(TestCase):
    """Concurrency tests for thread safety."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_concurrent_task_creation(self):
        """Test concurrent task creation."""
        manager = SwarmSessionManager(self.workspace)
        errors: list[Exception] = []
        created_tasks: list[str] = []
        lock = threading.Lock()

        def create_task(task_num: int):
            try:
                task = manager.create_task(f"task_{task_num:03d}", "PARALLEL")
                with lock:
                    created_tasks.append(task.task_id)
            except Exception as e:
                with lock:
                    errors.append(e)

        # Create 20 tasks concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_task, i) for i in range(20)]
            for future in as_completed(futures):
                future.result()

        assert len(errors) == 0, f"Errors: {errors}"
        assert len(created_tasks) == 20

    def test_concurrent_session_creation(self):
        """Test concurrent session creation for same task."""
        manager = SwarmSessionManager(self.workspace)
        manager.create_task("task_001", "PARALLEL", is_ephemeral=True)

        uuids: list[str] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def create_session(role_num: int):
            try:
                uuid = manager.get_or_create_session("task_001", f"worker_{role_num}", "gemini")
                with lock:
                    uuids.append(uuid)
            except Exception as e:
                with lock:
                    errors.append(e)

        # Create 10 sessions concurrently (reduced from 20 for Windows I/O)
        num_threads = 10
        threads = [threading.Thread(target=create_session, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        alive = [t for t in threads if t.is_alive()]
        assert len(alive) == 0, f"{len(alive)} threads still alive (deadlock or I/O hang)"
        assert len(errors) == 0, f"Errors: {errors}"
        assert len(uuids) == num_threads
        assert len(set(uuids)) == num_threads  # All unique

    def test_concurrent_read_write(self):
        """Test concurrent reads and writes."""
        manager = SwarmSessionManager(self.workspace)
        errors: list[Exception] = []

        def writer(thread_id: int):
            try:
                for i in range(5):
                    task_id = f"task_{thread_id}_{i}"
                    manager.create_task(task_id, "PARALLEL")
                    manager.get_or_create_session(task_id, "lead", "gemini")
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(10):
                    manager.list_active_sessions()
                    manager.list_active_tasks()
                    manager.get_stats()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        # Mix of writers and readers
        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=writer, args=(i,)))
        for _ in range(3):
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Errors: {errors}"


class TestGenerateTaskId(TestCase):
    """Tests for generate_task_id utility."""

    def test_generate_task_id_format(self):
        """Test task ID format: prefix_YYYYMMDD_HHMMSS_shortUUID."""
        task_id = generate_task_id()

        parts = task_id.split("_")
        assert len(parts) == 4
        assert parts[0] == "task"
        assert len(parts[1]) == 8  # YYYYMMDD
        assert len(parts[2]) == 6  # HHMMSS
        assert len(parts[3]) == 8  # Short UUID

    def test_generate_task_id_custom_prefix(self):
        """Test task ID with custom prefix."""
        task_id = generate_task_id(prefix="swarm")

        assert task_id.startswith("swarm_")

    def test_generate_task_id_unique(self):
        """Test that generated IDs are unique."""
        ids = [generate_task_id() for _ in range(100)]
        assert len(set(ids)) == 100


# Run tests if executed directly
if __name__ == "__main__":
    main()
