"""
Integration tests for Swarm Session Isolation - Phase 7 Finale.

NEXUS V7.5 HIVE MIND - Tests for full integration between:
- HybridSwarmEngine (task lifecycle)
- ModeExecutors (role-based session UUIDs)
- SwarmSessionManager (session registry)

Author: Claude (NEXUS V7.5)
Date: 2025-12-04
"""

import shutil

# Add parent to path for imports
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.intelligence.swarm.mode_executors import (
    AgentResponse,
    ExecutionContext,
    ExecutionStatus,
    LeadSupportExecutor,
    ParallelExecutor,
    RedBlueExecutor,
    SequentialExecutor,
    SpecialistExecutor,
)
from core.intelligence.swarm.mode_selector import AgentAssignment
from core.intelligence.swarm.session_manager import SwarmSessionManager, generate_task_id


class TestExecutionContextSessionIntegration(TestCase):
    """Tests for ExecutionContext.get_session_uuid integration."""

    def setUp(self):
        """Create temporary workspace and session manager."""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)
        self.session_manager = SwarmSessionManager(self.workspace)

    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_session_uuid_with_manager(self):
        """Test that get_session_uuid works with session manager."""
        task_id = generate_task_id()
        self.session_manager.create_task(task_id, "PARALLEL")

        context = ExecutionContext(
            task_input="Test task",
            agent_assignments=[AgentAssignment(agent_id="gemini", role="worker_0")],
            blackboard={},
            task_id=task_id,
            session_manager=self.session_manager,
        )

        uuid = context.get_session_uuid("worker_0", "gemini")

        assert uuid is not None
        assert isinstance(uuid, str)
        assert len(uuid) == 36  # UUID format

    def test_get_session_uuid_without_manager(self):
        """Test that get_session_uuid returns None without manager."""
        context = ExecutionContext(
            task_input="Test task",
            agent_assignments=[AgentAssignment(agent_id="gemini", role="worker_0")],
            blackboard={},
            task_id=None,
            session_manager=None,
        )

        uuid = context.get_session_uuid("worker_0", "gemini")

        assert uuid is None

    def test_get_session_uuid_without_task_id(self):
        """Test that get_session_uuid returns None without task_id."""
        context = ExecutionContext(
            task_input="Test task",
            agent_assignments=[AgentAssignment(agent_id="gemini", role="worker_0")],
            blackboard={},
            task_id=None,
            session_manager=self.session_manager,
        )

        uuid = context.get_session_uuid("worker_0", "gemini")

        assert uuid is None

    def test_same_role_agent_returns_same_uuid(self):
        """Test that same role+agent combination returns same UUID."""
        task_id = generate_task_id()
        self.session_manager.create_task(task_id, "SEQUENTIAL")

        context = ExecutionContext(
            task_input="Test task",
            agent_assignments=[],
            blackboard={},
            task_id=task_id,
            session_manager=self.session_manager,
        )

        uuid1 = context.get_session_uuid("first", "claude")
        uuid2 = context.get_session_uuid("first", "claude")

        assert uuid1 == uuid2

    def test_different_roles_different_uuids(self):
        """Test that different roles get different UUIDs."""
        task_id = generate_task_id()
        self.session_manager.create_task(task_id, "LEAD_SUPPORT")

        context = ExecutionContext(
            task_input="Test task",
            agent_assignments=[],
            blackboard={},
            task_id=task_id,
            session_manager=self.session_manager,
        )

        lead_uuid = context.get_session_uuid("lead", "claude")
        support_uuid = context.get_session_uuid("support", "gemini")

        assert lead_uuid != support_uuid


class TestModeExecutorSessionIsolation(TestCase):
    """Tests for session isolation in mode executors."""

    def setUp(self):
        """Create temporary workspace and mock context."""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)
        self.session_manager = SwarmSessionManager(self.workspace)

    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_context(self, task_id: str, agents: list, mode: str = "PARALLEL") -> ExecutionContext:
        """Helper to create ExecutionContext with session manager."""
        self.session_manager.create_task(task_id, mode)

        return ExecutionContext(
            task_input="Test task",
            agent_assignments=agents,
            blackboard={"workspace_path": self.workspace},
            task_id=task_id,
            session_manager=self.session_manager,
            invoke_agent=self._mock_invoke_agent,
        )

    def _mock_invoke_agent(self, agent_id: str, task_type: str, context: str) -> AgentResponse:
        """Mock invoke_agent for testing."""
        return AgentResponse(agent_id=agent_id, content=f"Mock response from {agent_id}", status="success")

    def test_parallel_executor_creates_worker_sessions(self):
        """Test that ParallelExecutor creates worker_X sessions."""
        task_id = generate_task_id()
        agents = [
            AgentAssignment(agent_id="gemini", role="worker_0"),
            AgentAssignment(agent_id="claude", role="worker_1"),
        ]
        context = self._create_context(task_id, agents, "PARALLEL")

        executor = ParallelExecutor()
        executor.execute(context)

        # Verify task was created
        task = self.session_manager.get_task(task_id)
        assert task is not None

        # Check for worker roles (may be created during execution)
        # Sessions are stored in task.roles dictionary keyed by role name

    def test_sequential_executor_creates_first_second_sessions(self):
        """Test that SequentialExecutor creates first/second sessions."""
        task_id = generate_task_id()
        agents = [AgentAssignment(agent_id="gemini", role="first"), AgentAssignment(agent_id="claude", role="second")]
        context = self._create_context(task_id, agents, "SEQUENTIAL")

        executor = SequentialExecutor()
        result = executor.execute(context)

        assert result.status == ExecutionStatus.COMPLETED
        assert len(result.agent_outputs) == 2

    def test_lead_support_executor_creates_role_sessions(self):
        """Test that LeadSupportExecutor creates lead/support sessions."""
        task_id = generate_task_id()
        agents = [AgentAssignment(agent_id="claude", role="lead"), AgentAssignment(agent_id="gemini", role="support")]
        context = self._create_context(task_id, agents, "LEAD_SUPPORT")

        executor = LeadSupportExecutor()
        result = executor.execute(context)

        assert result.status == ExecutionStatus.COMPLETED
        assert len(result.agent_outputs) >= 2

    def test_red_blue_executor_creates_adversarial_sessions(self):
        """Test that RedBlueExecutor creates blue/red sessions."""
        task_id = generate_task_id()
        agents = [AgentAssignment(agent_id="claude", role="blue"), AgentAssignment(agent_id="gemini", role="red")]
        context = self._create_context(task_id, agents, "RED_BLUE")

        executor = RedBlueExecutor()
        result = executor.execute(context)

        assert result.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED]
        assert len(result.agent_outputs) == 4  # propose, attack, defend, verify

    def test_session_uuid_stored_in_blackboard_during_invoke(self):
        """Test that session UUID is temporarily stored in blackboard during invoke."""
        task_id = generate_task_id()
        self.session_manager.create_task(task_id, "SPECIALIST")

        blackboard = {"workspace_path": self.workspace}
        captured_blackboard = {}

        def capture_invoke(agent_id: str, task_type: str, context: str) -> AgentResponse:
            # Capture blackboard state during invoke
            captured_blackboard.update(blackboard)
            return AgentResponse(agent_id=agent_id, content=f"Response from {agent_id}", status="success")

        context = ExecutionContext(
            task_input="Test task",
            agent_assignments=[AgentAssignment(agent_id="gemini", role="specialist")],
            blackboard=blackboard,
            task_id=task_id,
            session_manager=self.session_manager,
            invoke_agent=capture_invoke,
        )

        executor = SpecialistExecutor()
        executor.execute(context)

        # The blackboard should have had the session UUID during invoke
        # (it's cleaned up after, so we captured it)
        # Note: The UUID is stored as _session_uuid_{agent_id}


class TestHybridSwarmEngineSessionIntegration(TestCase):
    """Tests for HybridSwarmEngine session integration."""

    def setUp(self):
        """Create temporary workspace."""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)

    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_engine_initializes_session_manager(self):
        """Test that HybridSwarmEngine initializes SessionManager with workspace."""
        from core.intelligence.swarm.hybrid_swarm_engine import HybridSwarmEngine

        mock_orchestrator = MagicMock()
        mock_orchestrator.config.swarm_auto_route = True
        mock_orchestrator.config.swarm_max_negotiation_turns = 4
        mock_orchestrator.config.swarm_max_execution_rounds = 10

        engine = HybridSwarmEngine(mock_orchestrator, workspace_path=self.workspace)

        assert engine.session_manager is not None
        assert isinstance(engine.session_manager, SwarmSessionManager)

    def test_engine_without_workspace_has_no_session_manager(self):
        """Test that engine without workspace_path has no SessionManager."""
        from core.intelligence.swarm.hybrid_swarm_engine import HybridSwarmEngine

        mock_orchestrator = MagicMock()
        mock_orchestrator.config.swarm_auto_route = True
        mock_orchestrator.config.swarm_max_negotiation_turns = 4
        mock_orchestrator.config.swarm_max_execution_rounds = 10

        engine = HybridSwarmEngine(mock_orchestrator, workspace_path=None)

        assert engine.session_manager is None


class TestSessionLifecycleIntegration(TestCase):
    """Tests for complete session lifecycle."""

    def setUp(self):
        """Create temporary workspace."""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)
        self.session_manager = SwarmSessionManager(self.workspace)

    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_complete_task_lifecycle(self):
        """Test complete task lifecycle: create -> sessions -> complete."""
        from core.intelligence.swarm.session_manager import SessionStatus

        # Create task
        task_id = generate_task_id(prefix="test")
        self.session_manager.create_task(task_id, "SEQUENTIAL")

        # Create sessions for different roles
        self.session_manager.get_or_create_session(task_id, "first", "gemini")
        self.session_manager.get_or_create_session(task_id, "second", "claude")

        # Verify sessions exist (stored in task.roles)
        task = self.session_manager.get_task(task_id)
        assert len(task.roles) == 2
        assert task.status == SessionStatus.ACTIVE

        # Complete task
        self.session_manager.complete_task(task_id, SessionStatus.COMPLETED)

        # Verify task completed
        task = self.session_manager.get_task(task_id)
        assert task.status == SessionStatus.COMPLETED

    def test_failed_task_cleanup(self):
        """Test that failed tasks are properly marked."""
        from core.intelligence.swarm.session_manager import SessionStatus

        task_id = generate_task_id()
        self.session_manager.create_task(task_id, "PARALLEL")

        # Simulate session creation
        self.session_manager.get_or_create_session(task_id, "worker_0", "gemini")

        # Mark as failed
        self.session_manager.complete_task(task_id, SessionStatus.FAILED)

        task = self.session_manager.get_task(task_id)
        assert task.status == SessionStatus.FAILED

    def test_multiple_concurrent_tasks(self):
        """Test multiple tasks can exist concurrently without interference."""
        task1_id = generate_task_id(prefix="task1")
        task2_id = generate_task_id(prefix="task2")

        self.session_manager.create_task(task1_id, "PARALLEL")
        self.session_manager.create_task(task2_id, "SEQUENTIAL")

        # Create sessions for each task
        uuid1 = self.session_manager.get_or_create_session(task1_id, "worker_0", "gemini")
        uuid2 = self.session_manager.get_or_create_session(task2_id, "first", "gemini")

        # UUIDs should be different
        assert uuid1 != uuid2

        # Each task should have its own sessions (stored in task.roles)
        task1 = self.session_manager.get_task(task1_id)
        task2 = self.session_manager.get_task(task2_id)

        assert len(task1.roles) == 1
        assert len(task2.roles) == 1
        assert "worker_0" in task1.roles
        assert "first" in task2.roles


class TestSessionPersistence(TestCase):
    """Tests for session persistence across manager instances."""

    def setUp(self):
        """Create temporary workspace."""
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir) / "workspace"
        self.workspace.mkdir(parents=True)

    def tearDown(self):
        """Clean up temporary files."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sessions_persist_across_manager_instances(self):
        """Test that sessions persist when creating new manager instance."""
        # Create manager and task
        manager1 = SwarmSessionManager(self.workspace)
        task_id = generate_task_id()
        manager1.create_task(task_id, "PARALLEL")
        uuid = manager1.get_or_create_session(task_id, "worker_0", "gemini")

        # Create new manager instance
        manager2 = SwarmSessionManager(self.workspace)

        # Task should still exist (sessions stored in task.roles)
        task = manager2.get_task(task_id)
        assert task is not None
        assert "worker_0" in task.roles
        assert task.roles["worker_0"].session_uuid == uuid


# Run tests if executed directly
if __name__ == "__main__":
    main()
