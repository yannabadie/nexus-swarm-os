"""
V9.7.1 Session Isolation Tests (HOME Spoofing).

Tests for HomeIsolator and SessionWorkspaceManager integration
for the Context Bleeding fix in Gemini CLI sessions.

NEXUS V9.7.1 - HOME Spoofing (replaces V9.7 CWD Isolation)

Key insight from V9.7.1:
- V9.7 CWD Isolation caused "ghost files" (writes to wrong directory)
- V9.7.1 uses HOME spoofing: CWD stays at project root, HOME is isolated
- Gemini CLI stores sessions in ~/.gemini/tmp/<hash(cwd)>/chats/
- Different HOME = Different session storage = Isolation without ghost files

Author: Claude (NEXUS V9.7.1)
Date: 2025-12-13
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.infrastructure.session import SessionWorkspaceManager, get_workspace_manager, reset_workspace_manager
from core.infrastructure.session.home_isolator import HomeIsolator


class TestHomeIsolator:
    """Tests for HomeIsolator - V9.7.1 HOME Spoofing."""

    @pytest.fixture
    def workspace(self, tmp_path):
        """Create a temporary workspace directory."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        return workspace

    @pytest.fixture
    def isolator(self, workspace):
        """Create a HomeIsolator instance."""
        return HomeIsolator(workspace)

    def test_init_creates_homes_dir(self, workspace):
        """__init__ should create .session_homes directory."""
        HomeIsolator(workspace)
        assert (workspace / ".session_homes").exists()
        assert (workspace / ".session_homes").is_dir()

    def test_get_isolated_env_returns_dict(self, isolator):
        """get_isolated_env should return environment dict."""
        env = isolator.get_isolated_env("task_001_lead")

        assert isinstance(env, dict)
        # Should have PATH from original environment
        assert "PATH" in env

    def test_get_isolated_env_has_isolated_home_linux(self, isolator, workspace):
        """get_isolated_env should set HOME on Linux/macOS."""
        env = isolator.get_isolated_env("task_001_lead")

        if sys.platform != "win32":
            assert "HOME" in env
            safe_id = isolator._sanitize_session_id("task_001_lead")
            assert str(workspace / ".session_homes" / safe_id) in env["HOME"]

    def test_get_isolated_env_has_isolated_home_windows(self, isolator, workspace):
        """get_isolated_env should set USERPROFILE on Windows."""
        env = isolator.get_isolated_env("task_001_lead")

        if sys.platform == "win32":
            assert "USERPROFILE" in env
            safe_id = isolator._sanitize_session_id("task_001_lead")
            assert str(workspace / ".session_homes" / safe_id) in env["USERPROFILE"]

    def test_get_isolated_env_creates_home_dir(self, isolator, workspace):
        """get_isolated_env should create isolated home directory."""
        isolator.get_isolated_env("task_001_lead")

        safe_id = isolator._sanitize_session_id("task_001_lead")
        isolated_home = workspace / ".session_homes" / safe_id
        assert isolated_home.exists()
        assert isolated_home.is_dir()

    def test_different_sessions_get_different_homes(self, isolator, workspace):
        """Different session IDs get different HOME directories."""
        env1 = isolator.get_isolated_env("task_001_lead")
        env2 = isolator.get_isolated_env("task_002_support")

        home_key = "HOME" if sys.platform != "win32" else "USERPROFILE"
        assert env1[home_key] != env2[home_key]

    def test_same_session_returns_same_home(self, isolator):
        """Calling get_isolated_env twice returns same HOME path."""
        env1 = isolator.get_isolated_env("task_001_lead")
        env2 = isolator.get_isolated_env("task_001_lead")

        home_key = "HOME" if sys.platform != "win32" else "USERPROFILE"
        assert env1[home_key] == env2[home_key]

    def test_cleanup_home_removes_directory(self, isolator, workspace):
        """cleanup_home should remove the isolated directory."""
        isolator.get_isolated_env("task_cleanup")
        safe_id = isolator._sanitize_session_id("task_cleanup")
        isolated_home = workspace / ".session_homes" / safe_id
        assert isolated_home.exists()

        result = isolator.cleanup_home("task_cleanup")

        assert result is True
        assert not isolated_home.exists()

    def test_cleanup_nonexistent_home_returns_false(self, isolator):
        """Cleanup of non-existent home should return False."""
        result = isolator.cleanup_home("nonexistent")
        assert result is False

    def test_get_home_path_existing(self, isolator, workspace):
        """get_home_path should return existing home path."""
        isolator.get_isolated_env("task_get")
        path = isolator.get_home_path("task_get")

        safe_id = isolator._sanitize_session_id("task_get")
        assert path == workspace / ".session_homes" / safe_id

    def test_get_home_path_nonexistent(self, isolator):
        """get_home_path should return None for non-existent."""
        result = isolator.get_home_path("nonexistent")
        assert result is None

    def test_list_active_homes(self, isolator):
        """list_active_homes should return all active."""
        isolator.get_isolated_env("task_1")
        isolator.get_isolated_env("task_2")
        isolator.get_isolated_env("task_3")

        active = isolator.list_active_homes()

        assert len(active) == 3
        assert isolator._sanitize_session_id("task_1") in active
        assert isolator._sanitize_session_id("task_2") in active
        assert isolator._sanitize_session_id("task_3") in active

    def test_get_stats(self, isolator):
        """get_stats should return count and size."""
        isolator.get_isolated_env("task_stats")

        stats = isolator.get_stats()

        assert stats["active_count"] == 1
        assert "total_size_mb" in stats

    def test_cleanup_old_homes(self, isolator):
        """cleanup_old_homes should remove old sessions."""
        isolator.get_isolated_env("task_old")

        # Manually backdate creation time
        from datetime import datetime, timedelta

        safe_id = isolator._sanitize_session_id("task_old")
        isolator._creation_times[safe_id] = datetime.now() - timedelta(hours=48)

        # Cleanup old (max_age=24h)
        removed = isolator.cleanup_old_homes(max_age_hours=24)

        assert removed == 1
        assert isolator.get_home_path("task_old") is None

    def test_thread_safety(self, isolator):
        """Concurrent access should be thread-safe."""
        import threading

        results = []

        def create_home(session_id):
            env = isolator.get_isolated_env(session_id)
            results.append(env)

        threads = []
        for i in range(10):
            t = threading.Thread(target=create_home, args=(f"task_{i}",))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # All envs should be created
        assert len(results) == 10
        # All should have HOME set
        home_key = "HOME" if sys.platform != "win32" else "USERPROFILE"
        for env in results:
            assert home_key in env


class TestSessionWorkspaceManagerV971:
    """Tests for SessionWorkspaceManager V9.7.1 integration."""

    @pytest.fixture
    def workspace(self, tmp_path):
        """Create a temporary workspace directory."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        return workspace

    @pytest.fixture
    def manager(self, workspace):
        """Create a SessionWorkspaceManager instance."""
        return SessionWorkspaceManager(workspace)

    def test_get_isolated_env_returns_dict(self, manager):
        """get_isolated_env should return environment dict."""
        env = manager.get_isolated_env("task_001_lead", "swarm")

        assert isinstance(env, dict)
        assert "PATH" in env  # Should preserve original env

    def test_get_isolated_env_has_isolated_home(self, manager, workspace):
        """get_isolated_env should set HOME to isolated directory."""
        env = manager.get_isolated_env("task_001_lead", "swarm")

        home_key = "HOME" if sys.platform != "win32" else "USERPROFILE"
        assert home_key in env
        assert "swarm_task_001_lead" in env[home_key]

    def test_different_sessions_get_different_envs(self, manager):
        """Different sessions get different HOME directories."""
        env1 = manager.get_isolated_env("task_001", "swarm")
        env2 = manager.get_isolated_env("task_002", "swarm")

        home_key = "HOME" if sys.platform != "win32" else "USERPROFILE"
        assert env1[home_key] != env2[home_key]

    def test_different_types_get_different_envs(self, manager):
        """Different session types get different HOME directories."""
        env_swarm = manager.get_isolated_env("task_001", "swarm")
        env_hive = manager.get_isolated_env("task_001", "hive")

        home_key = "HOME" if sys.platform != "win32" else "USERPROFILE"
        assert env_swarm[home_key] != env_hive[home_key]

    def test_cleanup_isolated_env(self, manager, workspace):
        """cleanup_isolated_env should remove HOME directory."""
        manager.get_isolated_env("task_cleanup", "swarm")
        safe_id = manager._home_isolator._sanitize_session_id("swarm_task_cleanup")
        home_path = workspace / ".session_homes" / safe_id
        assert home_path.exists()

        result = manager.cleanup_isolated_env("task_cleanup", "swarm")

        assert result is True
        assert not home_path.exists()


class TestWorkspaceManagerSingleton:
    """Tests for global singleton management."""

    def test_get_workspace_manager_creates_singleton(self, tmp_path):
        """get_workspace_manager should create singleton."""
        reset_workspace_manager()

        manager = get_workspace_manager(tmp_path)
        manager2 = get_workspace_manager()

        assert manager is manager2

    def test_get_workspace_manager_without_path_raises(self):
        """get_workspace_manager without path on first call should raise."""
        reset_workspace_manager()

        with pytest.raises(ValueError):
            get_workspace_manager()

    def test_reset_workspace_manager(self, tmp_path):
        """reset_workspace_manager should clear singleton."""
        reset_workspace_manager()

        manager1 = get_workspace_manager(tmp_path)
        reset_workspace_manager()
        manager2 = get_workspace_manager(tmp_path)

        assert manager1 is not manager2


class TestSwarmSessionManagerIntegration:
    """Tests for SwarmSessionManager + HomeIsolator integration."""

    @pytest.fixture
    def swarm_session_manager(self, tmp_path):
        """Create SwarmSessionManager with HOME isolation."""
        from core.intelligence.swarm.session_manager import SwarmSessionManager

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        return SwarmSessionManager(workspace)

    def test_get_isolated_env_returns_env(self, swarm_session_manager):
        """get_isolated_env should return environment dict."""
        # V9.7.1: Must create task and session first
        swarm_session_manager.create_task("task_001", "LEAD_SUPPORT")
        swarm_session_manager.get_or_create_session("task_001", "lead", "gemini_primary")

        env = swarm_session_manager.get_isolated_env("task_001", "lead")

        assert env is not None
        assert isinstance(env, dict)
        home_key = "HOME" if sys.platform != "win32" else "USERPROFILE"
        assert home_key in env

    def test_get_isolated_env_without_session_returns_none(self, swarm_session_manager):
        """get_isolated_env without session should return None."""
        swarm_session_manager.create_task("task_nosession", "PARALLEL")
        # Don't create session

        env = swarm_session_manager.get_isolated_env("task_nosession", "lead")

        assert env is None

    def test_complete_task_cleans_home(self, swarm_session_manager, tmp_path):
        """complete_task should cleanup isolated HOME."""
        tmp_path / "workspace"
        swarm_session_manager.create_task("task_cleanup", "SEQUENTIAL")
        swarm_session_manager.get_or_create_session("task_cleanup", "lead", "gemini_primary")

        # Get the HOME path before cleanup
        env = swarm_session_manager.get_isolated_env("task_cleanup", "lead")
        home_key = "HOME" if sys.platform != "win32" else "USERPROFILE"
        home_path = Path(env[home_key])
        assert home_path.exists()

        swarm_session_manager.complete_task("task_cleanup")

        # HOME directory should be cleaned up
        assert not home_path.exists()


class TestExecutionContextIsolatedEnv:
    """Tests for ExecutionContext.get_isolated_env()."""

    def test_get_isolated_env_with_session_manager(self, tmp_path):
        """get_isolated_env should return env from session manager."""
        from core.intelligence.swarm.executors.base import ExecutionContext
        from core.intelligence.swarm.session_manager import SwarmSessionManager

        workspace = tmp_path / "workspace"
        workspace.mkdir()

        session_manager = SwarmSessionManager(workspace)
        session_manager.create_task("task_001", "PARALLEL")
        session_manager.get_or_create_session("task_001", "lead", "gemini")

        context = ExecutionContext(
            task_input="test", agent_assignments=[], task_id="task_001", session_manager=session_manager
        )

        isolated_env = context.get_isolated_env("lead", "gemini")

        assert isolated_env is not None
        assert isinstance(isolated_env, dict)
        home_key = "HOME" if sys.platform != "win32" else "USERPROFILE"
        assert home_key in isolated_env

    def test_get_isolated_env_without_session_manager(self):
        """get_isolated_env without session_manager returns None."""
        from core.intelligence.swarm.executors.base import ExecutionContext

        context = ExecutionContext(
            task_input="test",
            agent_assignments=[],
        )

        isolated_env = context.get_isolated_env("lead", "gemini")

        assert isolated_env is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
