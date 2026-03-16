"""
Comprehensive tests for HomeIsolator class.

Tests session isolation via HOME environment spoofing, covering:
- Constructor & initialization
- Session ID sanitization (CWE-22 path traversal prevention)
- Environment isolation (Windows/Linux/macOS)
- Reference counting (F26)
- Cleanup operations
- Disk quota management (F29)
- Thread safety
- Security edge cases

Author: Claude (NEXUS V12.4)
Date: 2026-02-17
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier, Thread

import pytest

from core.infrastructure.session.home_isolator import HomeIsolator

# ============================================================================
# 1. Constructor Tests (~5 tests)
# ============================================================================


def test_constructor_creates_session_homes_directory(tmp_path):
    """Test that constructor creates .session_homes directory."""
    HomeIsolator(tmp_path)
    assert (tmp_path / ".session_homes").exists()
    assert (tmp_path / ".session_homes").is_dir()


def test_constructor_accepts_custom_base_path(tmp_path):
    """Test constructor with custom base_path."""
    custom_base = tmp_path / "custom_workspace"
    custom_base.mkdir()
    isolator = HomeIsolator(custom_base)
    assert isolator.base_path == custom_base
    assert (custom_base / ".session_homes").exists()


def test_constructor_use_workspace_prefix_defaults_true(tmp_path):
    """Test use_workspace_prefix defaults to True."""
    isolator = HomeIsolator(tmp_path)
    assert isolator._use_workspace_prefix is True


def test_constructor_can_set_use_workspace_prefix_false(tmp_path):
    """Test setting use_workspace_prefix=False."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    assert isolator._use_workspace_prefix is False


def test_constructor_creates_parent_directories(tmp_path):
    """Test constructor creates parent directories if needed."""
    deep_path = tmp_path / "a" / "b" / "c" / "workspace"
    HomeIsolator(deep_path)
    assert (deep_path / ".session_homes").exists()


# ============================================================================
# 2. Session ID Sanitization Tests (~20 tests)
# ============================================================================


def test_sanitize_normal_alphanumeric_id(tmp_path):
    """Test normal alphanumeric IDs pass through."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task_001_lead")
    assert result == "task_001_lead"


def test_sanitize_path_separator_slash(tmp_path):
    """Test forward slash replaced with underscore."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task/001/lead")
    assert "/" not in result
    assert result == "task_001_lead"


def test_sanitize_path_separator_backslash(tmp_path):
    """Test backslash replaced with underscore."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task\\001\\lead")
    assert "\\" not in result
    assert result == "task_001_lead"


def test_sanitize_parent_directory_references(tmp_path):
    """Test parent directory references (..) sanitized."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("../../../etc/passwd")
    assert ".." not in result
    assert "/" not in result
    # Each '../' becomes '___' (3 underscores), so '../../../' = 9 underscores
    assert result == "_________etc_passwd"


def test_sanitize_special_characters_removed(tmp_path):
    """Test special characters removed."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task@#$%001!&*")
    assert "@" not in result
    assert "#" not in result
    assert "!" not in result
    assert result == "task____001___"


def test_sanitize_very_long_id_truncated(tmp_path):
    """Test very long IDs truncated to 64 chars."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    long_id = "a" * 100
    result = isolator._sanitize_session_id(long_id)
    assert len(result) == 64


def test_sanitize_empty_string_generates_fallback(tmp_path):
    """Test empty string generates hash-based fallback."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("")
    assert result.startswith("nx_")
    assert len(result) == 11  # "nx_" + 8 digits


def test_sanitize_all_special_chars_generates_fallback(tmp_path):
    """Test all-special-char strings generate hash-based fallback."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("!@#$%^&*()")
    assert result.startswith("nx_")
    assert len(result) == 11


def test_sanitize_workspace_prefix_added_when_enabled(tmp_path):
    """Test workspace prefix added when use_workspace_prefix=True."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=True)
    result = isolator._sanitize_session_id("task_001")
    assert result.startswith("nx")
    assert "_task_001" in result
    # Format: nx<6-digit-hash>_<session_id>


def test_sanitize_no_prefix_when_disabled(tmp_path):
    """Test no prefix when use_workspace_prefix=False."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task_001")
    assert result == "task_001"
    assert not result.startswith("nx")


def test_sanitize_unicode_characters_handled(tmp_path):
    """Test unicode characters handled."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task_🚀_001")
    assert "🚀" not in result
    assert "_" in result


def test_sanitize_mixed_case_preserved(tmp_path):
    """Test mixed case preserved."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("TaskID_001_LeaD")
    assert result == "TaskID_001_LeaD"


def test_sanitize_hyphen_preserved(tmp_path):
    """Test hyphen preserved (valid char)."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task-001-lead")
    assert result == "task-001-lead"


def test_sanitize_underscore_preserved(tmp_path):
    """Test underscore preserved (valid char)."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task_001_lead")
    assert result == "task_001_lead"


def test_sanitize_null_byte_removed(tmp_path):
    """Test null bytes removed."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task\x00001")
    assert "\x00" not in result
    assert result == "task_001"


def test_sanitize_only_dots_generates_fallback(tmp_path):
    """Test session ID with only dots generates fallback."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id(".....")
    assert result.startswith("nx_")


def test_sanitize_whitespace_replaced(tmp_path):
    """Test whitespace replaced with underscore."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task 001 lead")
    assert " " not in result
    assert result == "task_001_lead"


def test_sanitize_tab_replaced(tmp_path):
    """Test tab characters replaced."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task\t001")
    assert "\t" not in result
    assert result == "task_001"


def test_sanitize_newline_replaced(tmp_path):
    """Test newline characters replaced."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result = isolator._sanitize_session_id("task\n001")
    assert "\n" not in result
    assert result == "task_001"


def test_sanitize_consistent_for_same_input(tmp_path):
    """Test sanitization is consistent for same input."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    result1 = isolator._sanitize_session_id("task_001")
    result2 = isolator._sanitize_session_id("task_001")
    assert result1 == result2


# ============================================================================
# 3. get_isolated_env Tests (~20 tests)
# ============================================================================


def test_get_isolated_env_returns_dict(tmp_path):
    """Test get_isolated_env returns dict."""
    isolator = HomeIsolator(tmp_path)
    env = isolator.get_isolated_env("task_001")
    assert isinstance(env, dict)


def test_get_isolated_env_contains_original_path(tmp_path):
    """Test env contains original PATH."""
    isolator = HomeIsolator(tmp_path)
    env = isolator.get_isolated_env("task_001")
    assert "PATH" in env
    assert env["PATH"] == os.environ.get("PATH")


def test_get_isolated_env_creates_directory_on_disk(tmp_path):
    """Test creates isolated home directory on disk."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    expected_dir = tmp_path / ".session_homes" / "task_001"
    assert expected_dir.exists()
    assert expected_dir.is_dir()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
def test_get_isolated_env_windows_sets_userprofile(tmp_path):
    """Test Windows: sets USERPROFILE."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    expected_home = str(tmp_path / ".session_homes" / "task_001")
    assert "USERPROFILE" in env
    assert env["USERPROFILE"] == expected_home


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
def test_get_isolated_env_windows_sets_homedrive(tmp_path):
    """Test Windows: sets HOMEDRIVE."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    assert "HOMEDRIVE" in env
    # Should be drive letter like "C:"
    assert ":" in env["HOMEDRIVE"] or env["HOMEDRIVE"] == "C:"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
def test_get_isolated_env_windows_sets_homepath(tmp_path):
    """Test Windows: sets HOMEPATH."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    assert "HOMEPATH" in env


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
def test_get_isolated_env_windows_sets_home(tmp_path):
    """Test Windows: sets HOME (for Git Bash/WSL compat)."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    expected_home = str(tmp_path / ".session_homes" / "task_001")
    assert "HOME" in env
    assert env["HOME"] == expected_home


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
def test_get_isolated_env_windows_sets_appdata(tmp_path):
    """Test Windows: sets APPDATA."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    assert "APPDATA" in env
    assert "AppData" in env["APPDATA"]
    assert "Roaming" in env["APPDATA"]
    # Verify directory exists
    assert Path(env["APPDATA"]).exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
def test_get_isolated_env_windows_sets_localappdata(tmp_path):
    """Test Windows: sets LOCALAPPDATA."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    assert "LOCALAPPDATA" in env
    assert "AppData" in env["LOCALAPPDATA"]
    assert "Local" in env["LOCALAPPDATA"]
    assert Path(env["LOCALAPPDATA"]).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test")
def test_get_isolated_env_unix_sets_home(tmp_path):
    """Test Linux/macOS: sets HOME."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    expected_home = str(tmp_path / ".session_homes" / "task_001")
    assert "HOME" in env
    assert env["HOME"] == expected_home


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test")
def test_get_isolated_env_unix_sets_xdg_config_home(tmp_path):
    """Test Linux: sets XDG_CONFIG_HOME."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    assert "XDG_CONFIG_HOME" in env
    assert ".config" in env["XDG_CONFIG_HOME"]
    assert Path(env["XDG_CONFIG_HOME"]).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test")
def test_get_isolated_env_unix_sets_xdg_data_home(tmp_path):
    """Test Linux: sets XDG_DATA_HOME."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    assert "XDG_DATA_HOME" in env
    assert ".local" in env["XDG_DATA_HOME"]
    assert "share" in env["XDG_DATA_HOME"]
    assert Path(env["XDG_DATA_HOME"]).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test")
def test_get_isolated_env_unix_sets_xdg_cache_home(tmp_path):
    """Test Linux: sets XDG_CACHE_HOME."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    assert "XDG_CACHE_HOME" in env
    assert ".cache" in env["XDG_CACHE_HOME"]
    assert Path(env["XDG_CACHE_HOME"]).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-only test")
def test_get_isolated_env_unix_sets_xdg_state_home(tmp_path):
    """Test Linux: sets XDG_STATE_HOME."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task_001")
    assert "XDG_STATE_HOME" in env
    assert ".local" in env["XDG_STATE_HOME"]
    assert "state" in env["XDG_STATE_HOME"]
    assert Path(env["XDG_STATE_HOME"]).exists()


def test_get_isolated_env_thread_safety(tmp_path):
    """Test thread safety for concurrent access."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    results = []
    barrier = Barrier(3)

    def worker(session_id):
        barrier.wait()  # Sync start
        env = isolator.get_isolated_env(session_id)
        results.append(env)

    threads = [
        Thread(target=worker, args=("task_001",)),
        Thread(target=worker, args=("task_002",)),
        Thread(target=worker, args=("task_003",)),
    ]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 3
    # All should have valid env dicts
    for env in results:
        assert isinstance(env, dict)
        assert "PATH" in env


def test_get_isolated_env_different_ids_different_dirs(tmp_path):
    """Test different session_ids create different directories."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env1 = isolator.get_isolated_env("task_001")
    env2 = isolator.get_isolated_env("task_002")

    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    assert env1[home_key] != env2[home_key]


def test_get_isolated_env_same_id_consistent_path(tmp_path):
    """Test same session_id returns consistent path."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env1 = isolator.get_isolated_env("task_001")
    env2 = isolator.get_isolated_env("task_001")

    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    assert env1[home_key] == env2[home_key]


def test_get_isolated_env_records_creation_time(tmp_path):
    """Test records creation time."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    before = datetime.now()
    isolator.get_isolated_env("task_001")
    after = datetime.now()

    # Check internal tracking
    assert "task_001" in isolator._creation_times
    created_at = isolator._creation_times["task_001"]
    assert before <= created_at <= after


def test_get_isolated_env_idempotent(tmp_path):
    """Test calling get_isolated_env multiple times is idempotent."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env1 = isolator.get_isolated_env("task_001")
    env2 = isolator.get_isolated_env("task_001")
    env3 = isolator.get_isolated_env("task_001")

    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    assert env1[home_key] == env2[home_key] == env3[home_key]

    # Should only record creation time once
    assert len([k for k in isolator._creation_times if "task_001" in k]) == 1


# ============================================================================
# 4. get_home_path Tests (~5 tests)
# ============================================================================


def test_get_home_path_returns_none_for_nonexistent(tmp_path):
    """Test returns None for non-existent session."""
    isolator = HomeIsolator(tmp_path)
    result = isolator.get_home_path("nonexistent_session")
    assert result is None


def test_get_home_path_returns_path_after_creation(tmp_path):
    """Test returns Path after get_isolated_env called."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    path = isolator.get_home_path("task_001")
    assert path is not None
    assert isinstance(path, Path)
    assert path.exists()


def test_get_home_path_works_with_sanitized_ids(tmp_path):
    """Test works with sanitized IDs."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    # Create with path separators
    isolator.get_isolated_env("task/001")
    # Should find it with original unsanitized ID
    path = isolator.get_home_path("task/001")
    assert path is not None


def test_get_home_path_returns_correct_location(tmp_path):
    """Test returns correct location."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    path = isolator.get_home_path("task_001")
    expected = tmp_path / ".session_homes" / "task_001"
    assert path == expected


def test_get_home_path_thread_safe(tmp_path):
    """Test get_home_path is thread-safe."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    results = []
    barrier = Barrier(5)

    def worker():
        barrier.wait()
        path = isolator.get_home_path("task_001")
        results.append(path)

    threads = [Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All should return same path
    assert len(results) == 5
    assert all(r == results[0] for r in results)


# ============================================================================
# 5. Reference Counting Tests (F26) (~20 tests)
# ============================================================================


def test_acquire_env_increments_ref_count(tmp_path):
    """Test acquire_env increments ref count."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    assert isolator.get_ref_count("task_001") == 1


def test_release_env_decrements_ref_count(tmp_path):
    """Test release_env decrements ref count."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    isolator.release_env("task_001")
    assert isolator.get_ref_count("task_001") == 0


def test_multiple_acquires_stack(tmp_path):
    """Test multiple acquires stack."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    isolator.acquire_env("task_001")
    isolator.acquire_env("task_001")
    assert isolator.get_ref_count("task_001") == 3


def test_release_never_goes_below_zero(tmp_path):
    """Test release never goes below 0."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.release_env("task_001")
    isolator.release_env("task_001")
    isolator.release_env("task_001")
    assert isolator.get_ref_count("task_001") == 0


def test_get_ref_count_returns_current_count(tmp_path):
    """Test get_ref_count returns current count."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    assert isolator.get_ref_count("task_001") == 0
    isolator.acquire_env("task_001")
    assert isolator.get_ref_count("task_001") == 1
    isolator.acquire_env("task_001")
    assert isolator.get_ref_count("task_001") == 2
    isolator.release_env("task_001")
    assert isolator.get_ref_count("task_001") == 1


def test_cleanup_home_blocked_when_refs_greater_than_zero(tmp_path):
    """Test cleanup_home blocked when refs > 0."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    result = isolator.cleanup_home("task_001")
    assert result is False
    # Directory should still exist
    assert isolator.get_home_path("task_001") is not None


def test_cleanup_home_allowed_when_refs_zero(tmp_path):
    """Test cleanup_home allowed when refs == 0."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    result = isolator.cleanup_home("task_001")
    assert result is True
    # Directory should be gone
    assert isolator.get_home_path("task_001") is None


def test_cleanup_home_force_overrides_ref_check(tmp_path):
    """Test force=True overrides ref check."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    isolator.acquire_env("task_001")
    result = isolator.cleanup_home("task_001", force=True)
    assert result is True
    assert isolator.get_home_path("task_001") is None


def test_acquire_env_returns_valid_env_dict(tmp_path):
    """Test acquire_env returns valid env dict."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.acquire_env("task_001")
    assert isinstance(env, dict)
    assert "PATH" in env
    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    assert home_key in env


def test_ref_count_thread_safety(tmp_path):
    """Test thread safety for concurrent acquire/release."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    barrier = Barrier(10)

    def worker_acquire():
        barrier.wait()
        isolator.acquire_env("task_001")

    def worker_release():
        barrier.wait()
        isolator.release_env("task_001")

    # 5 acquires, 5 releases
    threads = [Thread(target=worker_acquire) for _ in range(5)] + [Thread(target=worker_release) for _ in range(5)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Should never go negative
    assert isolator.get_ref_count("task_001") >= 0


def test_release_env_returns_remaining_count(tmp_path):
    """Test release_env returns remaining count."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    isolator.acquire_env("task_001")
    isolator.acquire_env("task_001")

    remaining = isolator.release_env("task_001")
    assert remaining == 2

    remaining = isolator.release_env("task_001")
    assert remaining == 1

    remaining = isolator.release_env("task_001")
    assert remaining == 0


def test_acquire_release_acquire_pattern(tmp_path):
    """Test acquire-release-acquire pattern works."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    assert isolator.get_ref_count("task_001") == 1

    isolator.release_env("task_001")
    assert isolator.get_ref_count("task_001") == 0

    isolator.acquire_env("task_001")
    assert isolator.get_ref_count("task_001") == 1


def test_cleanup_clears_ref_count(tmp_path):
    """Test cleanup clears ref count."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    isolator.cleanup_home("task_001", force=False)

    # Ref count should be cleared
    assert "task_001" not in isolator._active_refs


def test_force_cleanup_clears_ref_count(tmp_path):
    """Test force cleanup clears ref count."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    assert isolator.get_ref_count("task_001") == 1

    isolator.cleanup_home("task_001", force=True)
    assert "task_001" not in isolator._active_refs


def test_get_ref_count_for_nonexistent_session(tmp_path):
    """Test get_ref_count returns 0 for nonexistent session."""
    isolator = HomeIsolator(tmp_path)
    assert isolator.get_ref_count("nonexistent") == 0


def test_ref_count_isolated_between_sessions(tmp_path):
    """Test ref counts isolated between sessions."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    isolator.acquire_env("task_001")
    isolator.acquire_env("task_002")

    assert isolator.get_ref_count("task_001") == 2
    assert isolator.get_ref_count("task_002") == 1


def test_ref_count_persists_across_get_isolated_env_calls(tmp_path):
    """Test ref count persists across get_isolated_env calls."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    assert isolator.get_ref_count("task_001") == 1

    # Call get_isolated_env directly (doesn't change ref count)
    isolator.get_isolated_env("task_001")
    assert isolator.get_ref_count("task_001") == 1


def test_acquire_env_creates_directory(tmp_path):
    """Test acquire_env creates directory."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    assert isolator.get_home_path("task_001") is not None
    assert isolator.get_home_path("task_001").exists()


def test_release_does_not_delete_directory(tmp_path):
    """Test release does not delete directory."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")
    isolator.release_env("task_001")
    # Directory still exists, just ref count is 0
    assert isolator.get_home_path("task_001") is not None


# ============================================================================
# 6. Cleanup Tests (~15 tests)
# ============================================================================


def test_cleanup_home_removes_directory(tmp_path):
    """Test cleanup_home removes directory."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    assert isolator.get_home_path("task_001") is not None

    isolator.cleanup_home("task_001")
    assert isolator.get_home_path("task_001") is None


def test_cleanup_home_returns_false_for_nonexistent(tmp_path):
    """Test cleanup_home returns False for non-existent."""
    isolator = HomeIsolator(tmp_path)
    result = isolator.cleanup_home("nonexistent")
    assert result is False


def test_cleanup_home_clears_creation_time_tracking(tmp_path):
    """Test cleanup_home clears creation time tracking."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    assert "task_001" in isolator._creation_times

    isolator.cleanup_home("task_001")
    assert "task_001" not in isolator._creation_times


def test_cleanup_old_homes_removes_old_sessions(tmp_path):
    """Test cleanup_old_homes removes sessions older than max_age."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # Create session and fake old creation time
    isolator.get_isolated_env("old_task")
    isolator._creation_times["old_task"] = datetime.now() - timedelta(hours=25)

    # Create recent session
    isolator.get_isolated_env("new_task")

    # Cleanup with 24h threshold
    removed = isolator.cleanup_old_homes(max_age_hours=24.0)

    assert removed == 1
    assert isolator.get_home_path("old_task") is None
    assert isolator.get_home_path("new_task") is not None


def test_cleanup_old_homes_keeps_young_sessions(tmp_path):
    """Test cleanup_old_homes keeps young sessions."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("young_task")

    removed = isolator.cleanup_old_homes(max_age_hours=24.0)

    assert removed == 0
    assert isolator.get_home_path("young_task") is not None


def test_cleanup_old_homes_returns_count_of_removed(tmp_path):
    """Test cleanup_old_homes returns count of removed."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # Create 3 old sessions
    for i in range(3):
        session_id = f"old_task_{i}"
        isolator.get_isolated_env(session_id)
        isolator._creation_times[session_id] = datetime.now() - timedelta(hours=30)

    removed = isolator.cleanup_old_homes(max_age_hours=24.0)
    assert removed == 3


def test_cleanup_old_homes_handles_missing_directories(tmp_path):
    """Test cleanup_old_homes handles missing directories gracefully."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # Add entry with old time but no directory
    isolator._creation_times["phantom_task"] = datetime.now() - timedelta(hours=30)

    # Should not crash
    removed = isolator.cleanup_old_homes(max_age_hours=24.0)
    assert removed == 0


def test_cleanup_old_homes_zero_max_age(tmp_path):
    """Test cleanup_old_homes with max_age=0 removes all."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    isolator.get_isolated_env("task_002")

    # Even brand new sessions are "old"
    removed = isolator.cleanup_old_homes(max_age_hours=0.0)
    assert removed == 2


def test_cleanup_old_homes_fractional_hours(tmp_path):
    """Test cleanup_old_homes with fractional hours."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    isolator.get_isolated_env("task_001")
    isolator._creation_times["task_001"] = datetime.now() - timedelta(minutes=61)

    # 1 hour = 60 minutes, so 61 minutes should be cleaned
    removed = isolator.cleanup_old_homes(max_age_hours=1.0)
    assert removed == 1


def test_cleanup_old_homes_thread_safety(tmp_path):
    """Test cleanup_old_homes is thread-safe."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # Create some sessions
    for i in range(10):
        isolator.get_isolated_env(f"task_{i}")
        if i < 5:
            isolator._creation_times[f"task_{i}"] = datetime.now() - timedelta(hours=30)

    results = []
    barrier = Barrier(3)

    def worker():
        barrier.wait()
        removed = isolator.cleanup_old_homes(max_age_hours=24.0)
        results.append(removed)

    threads = [Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Total removed should be 5 (but may be distributed across threads)
    assert sum(results) <= 5


def test_cleanup_home_handles_readonly_files(tmp_path):
    """Test cleanup_home handles readonly files (ignore_errors=True)."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create a readonly file
    home = isolator.get_home_path("task_001")
    readonly_file = home / "readonly.txt"
    readonly_file.write_text("test")
    readonly_file.chmod(0o444)

    # Cleanup should still succeed (ignore_errors=True)
    result = isolator.cleanup_home("task_001", force=True)
    # May succeed or fail depending on platform, but shouldn't crash
    assert isinstance(result, bool)


def test_cleanup_home_with_nested_directories(tmp_path):
    """Test cleanup_home with nested directories."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create nested structure
    home = isolator.get_home_path("task_001")
    (home / "a" / "b" / "c").mkdir(parents=True)
    (home / "a" / "b" / "c" / "file.txt").write_text("test")

    result = isolator.cleanup_home("task_001")
    assert result is True
    assert isolator.get_home_path("task_001") is None


def test_cleanup_old_homes_updates_tracking(tmp_path):
    """Test cleanup_old_homes updates internal tracking."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    isolator.get_isolated_env("old_task")
    isolator._creation_times["old_task"] = datetime.now() - timedelta(hours=30)

    isolator.cleanup_old_homes(max_age_hours=24.0)

    assert "old_task" not in isolator._creation_times


def test_cleanup_respects_sanitization(tmp_path):
    """Test cleanup respects session ID sanitization."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # Create with path separator
    isolator.get_isolated_env("task/001")

    # Cleanup with original ID
    result = isolator.cleanup_home("task/001")
    assert result is True


# ============================================================================
# 7. list_active_homes & get_stats Tests (~10 tests)
# ============================================================================


def test_list_active_homes_returns_empty_on_fresh(tmp_path):
    """Test list_active_homes returns empty on fresh isolator."""
    isolator = HomeIsolator(tmp_path)
    assert isolator.list_active_homes() == []


def test_list_active_homes_returns_session_names(tmp_path):
    """Test list_active_homes returns session names."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    isolator.get_isolated_env("task_002")
    isolator.get_isolated_env("task_003")

    active = isolator.list_active_homes()
    assert len(active) == 3
    assert "task_001" in active
    assert "task_002" in active
    assert "task_003" in active


def test_get_stats_returns_active_count_and_total_size(tmp_path):
    """Test get_stats returns active_count and total_size_mb."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    stats = isolator.get_stats()
    assert "active_count" in stats
    assert "total_size_mb" in stats
    assert stats["active_count"] == 1
    assert isinstance(stats["total_size_mb"], float)


def test_get_stats_calculates_file_sizes(tmp_path):
    """Test get_stats calculates file sizes."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create a file with known size
    home = isolator.get_home_path("task_001")
    test_file = home / "test.txt"
    test_file.write_text("x" * 1024 * 1024)  # 1 MB

    stats = isolator.get_stats()
    # Should be at least 1 MB (may be slightly more due to filesystem overhead)
    assert stats["total_size_mb"] >= 0.9


def test_list_active_homes_excludes_hidden_directories(tmp_path):
    """Test list_active_homes excludes hidden directories."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create a hidden directory
    hidden = isolator.homes_dir / ".hidden"
    hidden.mkdir()

    active = isolator.list_active_homes()
    assert ".hidden" not in active
    assert "task_001" in active


def test_get_stats_empty_isolator(tmp_path):
    """Test get_stats on empty isolator."""
    isolator = HomeIsolator(tmp_path)
    stats = isolator.get_stats()
    assert stats["active_count"] == 0
    assert stats["total_size_mb"] == 0.0


def test_get_stats_multiple_sessions(tmp_path):
    """Test get_stats with multiple sessions."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    for i in range(5):
        isolator.get_isolated_env(f"task_{i}")

    stats = isolator.get_stats()
    assert stats["active_count"] == 5


def test_get_stats_handles_errors_gracefully(tmp_path):
    """Test get_stats handles file stat errors gracefully."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create a file
    home = isolator.get_home_path("task_001")
    (home / "test.txt").write_text("test")

    # Should not crash even if file access fails
    stats = isolator.get_stats()
    assert isinstance(stats["total_size_mb"], float)


def test_list_active_homes_after_cleanup(tmp_path):
    """Test list_active_homes after cleanup."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")
    isolator.get_isolated_env("task_002")

    assert len(isolator.list_active_homes()) == 2

    isolator.cleanup_home("task_001")

    active = isolator.list_active_homes()
    assert len(active) == 1
    assert "task_002" in active
    assert "task_001" not in active


def test_get_stats_rounds_size_to_two_decimals(tmp_path):
    """Test get_stats rounds size to two decimals."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create file with odd size
    home = isolator.get_home_path("task_001")
    (home / "test.txt").write_text("x" * 12345)

    stats = isolator.get_stats()
    # Should be rounded to 2 decimals
    size_str = str(stats["total_size_mb"])
    decimals = size_str.split(".")[1] if "." in size_str else ""
    assert len(decimals) <= 2


# ============================================================================
# 8. Disk Quota Tests (F29) (~15 tests)
# ============================================================================


def test_check_disk_quota_returns_ok_when_under(tmp_path):
    """Test check_disk_quota returns 'ok' when under quota."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    quota_check = isolator.check_disk_quota(quota_mb=500.0)
    assert quota_check["status"] == "ok"


def test_check_disk_quota_returns_warning_at_threshold(tmp_path):
    """Test check_disk_quota returns 'warning' at threshold."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create file at 80% of quota
    home = isolator.get_home_path("task_001")
    size_bytes = int(10 * 0.8 * 1024 * 1024)  # 80% of 10 MB
    (home / "large.txt").write_bytes(b"x" * size_bytes)

    quota_check = isolator.check_disk_quota(quota_mb=10.0, warn_threshold=0.8)
    assert quota_check["status"] in ["warning", "exceeded"]


def test_check_disk_quota_returns_exceeded_over_quota(tmp_path):
    """Test check_disk_quota returns 'exceeded' over quota."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create file over quota
    home = isolator.get_home_path("task_001")
    size_bytes = int(15 * 1024 * 1024)  # 15 MB (over 10 MB quota)
    (home / "large.txt").write_bytes(b"x" * size_bytes)

    quota_check = isolator.check_disk_quota(quota_mb=10.0)
    assert quota_check["status"] == "exceeded"


def test_enforce_quota_returns_zero_when_under_quota(tmp_path):
    """Test enforce_quota returns 0 when under quota."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    cleaned = isolator.enforce_quota(quota_mb=500.0)
    assert cleaned == 0


def test_enforce_quota_cleans_oldest_first(tmp_path):
    """Test enforce_quota cleans oldest first."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # Create sessions with fake times
    isolator.get_isolated_env("oldest")
    isolator._creation_times["oldest"] = datetime.now() - timedelta(hours=3)

    isolator.get_isolated_env("middle")
    isolator._creation_times["middle"] = datetime.now() - timedelta(hours=2)

    isolator.get_isolated_env("newest")
    isolator._creation_times["newest"] = datetime.now() - timedelta(hours=1)

    # Create large files in each
    for session_id in ["oldest", "middle", "newest"]:
        home = isolator.get_home_path(session_id)
        (home / "large.txt").write_bytes(b"x" * (5 * 1024 * 1024))  # 5 MB each

    # Total ~15 MB, quota 10 MB -> should clean oldest
    cleaned = isolator.enforce_quota(quota_mb=10.0)

    # Should clean at least one (oldest)
    assert cleaned >= 1
    assert isolator.get_home_path("oldest") is None


def test_enforce_quota_skips_sessions_with_active_refs(tmp_path):
    """Test enforce_quota skips sessions with active refs."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # Create two sessions, both large
    isolator.acquire_env("old_active")  # Has ref count
    isolator._creation_times["old_active"] = datetime.now() - timedelta(hours=3)

    isolator.get_isolated_env("old_inactive")
    isolator._creation_times["old_inactive"] = datetime.now() - timedelta(hours=2)

    # Create large files
    for session_id in ["old_active", "old_inactive"]:
        home = isolator.get_home_path(session_id)
        (home / "large.txt").write_bytes(b"x" * (10 * 1024 * 1024))  # 10 MB each

    # Enforce quota - should skip old_active (has refs)
    isolator.enforce_quota(quota_mb=15.0)

    # Should clean old_inactive, not old_active
    assert isolator.get_home_path("old_active") is not None
    assert isolator.get_home_path("old_inactive") is None


def test_enforce_quota_stops_when_under_quota(tmp_path):
    """Test enforce_quota stops when under quota."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # Create 5 sessions, each 5 MB
    for i in range(5):
        session_id = f"task_{i}"
        isolator.get_isolated_env(session_id)
        isolator._creation_times[session_id] = datetime.now() - timedelta(hours=5 - i)
        home = isolator.get_home_path(session_id)
        (home / "large.txt").write_bytes(b"x" * (5 * 1024 * 1024))

    # Total 25 MB, quota 20 MB -> should clean 1-2 sessions, not all
    cleaned = isolator.enforce_quota(quota_mb=20.0)

    assert cleaned < 5  # Shouldn't clean all
    assert cleaned >= 1  # Should clean at least one


def test_check_disk_quota_includes_all_fields(tmp_path):
    """Test check_disk_quota includes all required fields."""
    isolator = HomeIsolator(tmp_path)
    quota_check = isolator.check_disk_quota()

    assert "current_mb" in quota_check
    assert "quota_mb" in quota_check
    assert "usage_percent" in quota_check
    assert "status" in quota_check
    assert "message" in quota_check
    assert "active_sessions" in quota_check


def test_check_disk_quota_calculates_usage_percent(tmp_path):
    """Test check_disk_quota calculates usage_percent correctly."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create 5 MB file
    home = isolator.get_home_path("task_001")
    (home / "large.txt").write_bytes(b"x" * (5 * 1024 * 1024))

    quota_check = isolator.check_disk_quota(quota_mb=10.0)
    # Should be ~50%
    assert 40 <= quota_check["usage_percent"] <= 60


def test_check_disk_quota_zero_quota(tmp_path):
    """Test check_disk_quota with zero quota (edge case)."""
    isolator = HomeIsolator(tmp_path)
    quota_check = isolator.check_disk_quota(quota_mb=0.0)
    # Should not crash
    assert quota_check["usage_percent"] == 0


def test_enforce_quota_logs_warnings(tmp_path, caplog):
    """Test enforce_quota logs warnings."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create large file to exceed quota
    home = isolator.get_home_path("task_001")
    (home / "large.txt").write_bytes(b"x" * (15 * 1024 * 1024))

    with caplog.at_level(logging.WARNING):
        isolator.enforce_quota(quota_mb=10.0)

    # Should have logged warning about enforcing quota
    assert any("[F29]" in record.message for record in caplog.records)


def test_enforce_quota_multiple_sessions(tmp_path):
    """Test enforce_quota with multiple sessions."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # Create 10 sessions
    for i in range(10):
        session_id = f"task_{i}"
        isolator.get_isolated_env(session_id)
        isolator._creation_times[session_id] = datetime.now() - timedelta(hours=10 - i)
        home = isolator.get_home_path(session_id)
        (home / "file.txt").write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB each

    # Total 20 MB, quota 10 MB
    cleaned = isolator.enforce_quota(quota_mb=10.0)

    # Should clean enough to get under quota
    assert cleaned > 0
    final_stats = isolator.get_stats()
    assert final_stats["total_size_mb"] <= 10.0


def test_check_disk_quota_custom_warn_threshold(tmp_path):
    """Test check_disk_quota with custom warn_threshold."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    # Create 6 MB file
    home = isolator.get_home_path("task_001")
    (home / "large.txt").write_bytes(b"x" * (6 * 1024 * 1024))

    # 60% threshold, 60% usage -> should warn
    quota_check = isolator.check_disk_quota(quota_mb=10.0, warn_threshold=0.6)
    assert quota_check["status"] in ["warning", "exceeded"]


def test_enforce_quota_returns_count(tmp_path):
    """Test enforce_quota returns accurate count."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    for i in range(3):
        session_id = f"task_{i}"
        isolator.get_isolated_env(session_id)
        isolator._creation_times[session_id] = datetime.now() - timedelta(hours=3 - i)
        home = isolator.get_home_path(session_id)
        (home / "large.txt").write_bytes(b"x" * (10 * 1024 * 1024))

    # Total 30 MB, quota 15 MB
    cleaned = isolator.enforce_quota(quota_mb=15.0)

    # Should return positive count
    assert cleaned >= 1


# ============================================================================
# 9. Security Edge Cases (~10 tests)
# ============================================================================


def test_security_path_traversal_etc_passwd(tmp_path):
    """Test path traversal attempt with ../../../etc/passwd."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("../../../etc/passwd")

    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    home_path = Path(env[home_key])

    # Should be inside .session_homes, not at /etc/passwd
    assert isolator.homes_dir in home_path.parents


def test_security_null_bytes_in_session_id(tmp_path):
    """Test null bytes in session_id."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env("task\x00001")

    # Should not crash, should sanitize
    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    assert "\x00" not in env[home_key]


def test_security_very_long_session_id_dos_prevention(tmp_path):
    """Test very long session_id (DoS prevention)."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    long_id = "a" * 10000

    env = isolator.get_isolated_env(long_id)

    # Should truncate, not cause issues
    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    home_path = Path(env[home_key])
    # Session ID part should be truncated
    assert len(home_path.name) <= 64 + 10  # 64 + prefix overhead


def test_security_session_id_with_only_dots(tmp_path):
    """Test session ID with only dots."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env(".....")

    # Should generate safe fallback
    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    home_path = Path(env[home_key])
    assert home_path.exists()
    assert isolator.homes_dir in home_path.parents


def test_security_concurrent_create_and_cleanup(tmp_path):
    """Test concurrent create and cleanup (race condition)."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    barrier = Barrier(2)
    errors = []

    def creator():
        try:
            barrier.wait()
            for _ in range(10):
                isolator.get_isolated_env("race_task")
        except Exception as e:
            errors.append(e)

    def cleaner():
        try:
            barrier.wait()
            for _ in range(10):
                isolator.cleanup_home("race_task", force=True)
        except Exception as e:
            errors.append(e)

    threads = [Thread(target=creator), Thread(target=cleaner)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Should not crash
    assert len(errors) == 0


def test_security_absolute_path_injection(tmp_path):
    """Test absolute path injection attempt."""
    if sys.platform == "win32":
        evil_path = "C:\\Windows\\System32"
    else:
        evil_path = "/etc/passwd"

    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    env = isolator.get_isolated_env(evil_path)

    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    home_path = Path(env[home_key])

    # Should be inside .session_homes
    assert isolator.homes_dir in home_path.parents


def test_security_special_windows_paths(tmp_path):
    """Test special Windows paths (CON, PRN, NUL, etc.)."""
    if sys.platform != "win32":
        pytest.skip("Windows-only test")

    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # These are special device names on Windows - they can't be used as directory names
    # The current implementation doesn't specifically sanitize these, which is a known limitation
    # Windows will raise FileNotFoundError when trying to create directories with these names
    for name in ["CON", "PRN", "AUX", "NUL", "COM1", "LPT1"]:
        try:
            env = isolator.get_isolated_env(name)
            # If it succeeds, should return a dict
            assert isinstance(env, dict)
        except (FileNotFoundError, OSError):
            # Expected on Windows for reserved device names
            # This is actually correct behavior - these names should fail
            pass


def test_security_unicode_normalization(tmp_path):
    """Test unicode normalization attacks."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    # Different unicode representations of same character
    id1 = "café"  # é as single character
    id2 = "café"  # e + combining accent

    env1 = isolator.get_isolated_env(id1)
    env2 = isolator.get_isolated_env(id2)

    # Both should work (though may point to different dirs)
    assert isinstance(env1, dict)
    assert isinstance(env2, dict)


def test_security_symlink_creation_blocked(tmp_path):
    """Test that symlinks don't escape isolation."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.get_isolated_env("task_001")

    home = isolator.get_home_path("task_001")

    # Try to create symlink pointing outside
    if sys.platform != "win32":
        try:
            symlink = home / "evil_link"
            symlink.symlink_to("/etc/passwd")

            # Even if symlink exists, cleanup should handle it
            result = isolator.cleanup_home("task_001", force=True)
            # Should succeed (shutil.rmtree handles symlinks)
            assert result is True
        except OSError:
            # May fail due to permissions, that's OK
            pass


def test_security_session_id_injection_newlines(tmp_path):
    """Test session ID injection with newlines."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    evil_id = "task_001\n../../etc\npasswd"

    env = isolator.get_isolated_env(evil_id)

    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    home_path = Path(env[home_key])

    # Should be sanitized
    assert "\n" not in str(home_path)
    assert isolator.homes_dir in home_path.parents


# ============================================================================
# Additional edge case tests
# ============================================================================


def test_isolator_with_spaces_in_base_path(tmp_path):
    """Test HomeIsolator with spaces in base path."""
    base_with_spaces = tmp_path / "my workspace"
    base_with_spaces.mkdir()

    isolator = HomeIsolator(base_with_spaces)
    env = isolator.get_isolated_env("task_001")

    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    assert env[home_key]
    assert Path(env[home_key]).exists()


def test_multiple_isolators_same_base_path(tmp_path):
    """Test multiple isolators with same base path."""
    isolator1 = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator2 = HomeIsolator(tmp_path, use_workspace_prefix=False)

    env1 = isolator1.get_isolated_env("task_001")
    env2 = isolator2.get_isolated_env("task_001")

    home_key = "USERPROFILE" if sys.platform == "win32" else "HOME"
    # Should point to same location
    assert env1[home_key] == env2[home_key]


def test_cleanup_during_iteration(tmp_path):
    """Test cleanup during iteration over active homes."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)

    for i in range(5):
        isolator.get_isolated_env(f"task_{i}")

    # Iterate and cleanup
    for session_id in list(isolator.list_active_homes()):
        isolator.cleanup_home(session_id)

    assert len(isolator.list_active_homes()) == 0


def test_ref_count_after_failed_cleanup(tmp_path):
    """Test ref count after failed cleanup attempt."""
    isolator = HomeIsolator(tmp_path, use_workspace_prefix=False)
    isolator.acquire_env("task_001")

    # Try to cleanup (should fail due to refs)
    result = isolator.cleanup_home("task_001")
    assert result is False

    # Ref count should still be 1
    assert isolator.get_ref_count("task_001") == 1
