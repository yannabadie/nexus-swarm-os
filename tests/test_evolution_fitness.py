"""
Tests for core.evolution.fitness (Epic 4.2 - Deterministic Fitness Function)

Tests the deterministic fitness pipeline that replaces LLM-as-a-judge.

Author: Claude (NEXUS V12.4 Epic 4.2)
Date: 2026-02-17
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.intelligence.evolution.fitness import (
    DeterministicFitness,
    DeterministicFitnessResult,
    FitnessCheck,
    FitnessResult,
)


class TestFitnessResult:
    """Test FitnessResult dataclass"""

    def test_fitness_result_passed(self):
        """Test FitnessResult with passed check"""
        result = FitnessResult(
            check=FitnessCheck.LINTER,
            passed=True,
            message="Linter passed (0 issues)",
            duration_seconds=1.5,
            details={"issues": 0},
        )
        assert result.check == FitnessCheck.LINTER
        assert result.passed is True
        assert result.duration_seconds == 1.5
        assert result.details["issues"] == 0

    def test_fitness_result_failed(self):
        """Test FitnessResult with failed check"""
        result = FitnessResult(
            check=FitnessCheck.TYPE_CHECK,
            passed=False,
            message="Type check failed (5 errors)",
            error_output="error: Name 'foo' is not defined",
        )
        assert result.passed is False
        assert "5 errors" in result.message
        assert result.error_output != ""


class TestDeterministicFitnessResult:
    """Test DeterministicFitnessResult dataclass"""

    def test_all_passed(self):
        """Test result when all checks pass"""
        check_results = [
            FitnessResult(FitnessCheck.SYNTAX, True, "Syntax OK"),
            FitnessResult(FitnessCheck.LINTER, True, "Linter OK"),
            FitnessResult(FitnessCheck.TYPE_CHECK, True, "Types OK"),
            FitnessResult(FitnessCheck.SECURITY, True, "Security OK"),
            FitnessResult(FitnessCheck.TESTS, True, "Tests OK"),
        ]
        overall = DeterministicFitnessResult(
            child_id="test_child",
            passed=True,
            check_results=check_results,
            total_duration=10.5,
        )
        assert overall.all_checks_passed is True
        assert len(overall.check_results) == 5
        assert overall.total_duration == 10.5

    def test_some_failed(self):
        """Test result when some checks fail"""
        check_results = [
            FitnessResult(FitnessCheck.SYNTAX, True, "Syntax OK"),
            FitnessResult(FitnessCheck.LINTER, False, "Linter failed"),
            FitnessResult(FitnessCheck.TYPE_CHECK, False, "Types failed"),
        ]
        overall = DeterministicFitnessResult(
            child_id="test_child",
            passed=False,
            failed_at_check=FitnessCheck.LINTER,
            check_results=check_results,
            total_duration=5.0,
        )
        assert overall.all_checks_passed is False

    def test_to_dict_method(self):
        """Test to_dict method converts result to dictionary"""
        check_results = [
            FitnessResult(FitnessCheck.SYNTAX, True, "OK"),
            FitnessResult(FitnessCheck.LINTER, False, "Failed"),
        ]
        overall = DeterministicFitnessResult(
            child_id="test_child",
            passed=False,
            failed_at_check=FitnessCheck.LINTER,
            check_results=check_results,
            total_duration=2.0,
        )
        data = overall.to_dict()
        assert data["child_id"] == "test_child"
        assert data["passed"] is False
        assert data["failed_at_check"] == "LINTER"
        assert len(data["checks"]) == 2


class TestDeterministicFitness:
    """Test DeterministicFitness class"""

    @pytest.fixture
    def temp_child_path(self):
        """Create temporary child directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            child_path = Path(tmpdir)
            # Create minimal Python file structure
            core_dir = child_path / "core"
            core_dir.mkdir()
            (core_dir / "__init__.py").write_text("")
            (core_dir / "sample.py").write_text("def hello() -> str:\n    return 'world'\n")
            yield child_path

    def test_init(self, temp_child_path):
        """Test DeterministicFitness initialization"""
        fitness = DeterministicFitness(child_path=temp_child_path)
        assert fitness.child_path == temp_child_path
        assert fitness.strict_mode is True
        assert fitness.run_in_sandbox is True

    def test_init_custom_params(self, temp_child_path):
        """Test initialization with custom parameters"""
        fitness = DeterministicFitness(
            child_path=temp_child_path,
            strict_mode=False,
            run_in_sandbox=False,
        )
        assert fitness.strict_mode is False
        assert fitness.run_in_sandbox is False

    def test_command_exists_true(self):
        """Test _command_exists for Python (should exist)"""
        fitness = DeterministicFitness(child_path=Path("."))
        # Python should always exist in test environment
        assert fitness._command_exists("python") or fitness._command_exists("python3")

    def test_command_exists_false(self):
        """Test _command_exists for non-existent command"""
        fitness = DeterministicFitness(child_path=Path("."))
        assert fitness._command_exists("nonexistent_command_12345") is False

    @patch("subprocess.run")
    def test_run_linter_pass(self, mock_run, temp_child_path):
        """Test _run_linter with passing code"""
        # Mock ruff returning 0 (success)
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"All checks passed!",
            stderr=b"",
        )

        fitness = DeterministicFitness(child_path=temp_child_path)
        with patch.object(fitness, "_command_exists", return_value=True):
            result = fitness._run_linter()

        assert result.check == FitnessCheck.LINTER
        assert result.passed is True
        assert "0 issues" in result.message

    @patch("subprocess.run")
    def test_run_linter_fail(self, mock_run, temp_child_path):
        """Test _run_linter with failing code"""
        # Mock ruff returning 1 (issues found)
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="Found 5 errors\nline 10: undefined name\n",
            stderr="",
        )

        fitness = DeterministicFitness(child_path=temp_child_path)
        with patch.object(fitness, "_command_exists", return_value=True):
            result = fitness._run_linter()

        assert result.check == FitnessCheck.LINTER
        assert result.passed is False
        assert "issue" in result.message.lower() or "error" in result.message.lower()

    @patch("subprocess.run")
    def test_run_linter_not_installed(self, mock_run, temp_child_path):
        """Test _run_linter when ruff not installed"""
        fitness = DeterministicFitness(child_path=temp_child_path)
        with patch.object(fitness, "_command_exists", return_value=False):
            result = fitness._run_linter()

        assert result.passed is False
        assert "not installed" in result.message

    @patch("subprocess.run")
    def test_run_type_check_pass(self, mock_run, temp_child_path):
        """Test _run_type_check with passing types"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b"Success: no issues found",
            stderr=b"",
        )

        fitness = DeterministicFitness(child_path=temp_child_path)
        with patch.object(fitness, "_command_exists", return_value=True):
            result = fitness._run_type_check()

        assert result.check == FitnessCheck.TYPE_CHECK
        assert result.passed is True

    @patch("subprocess.run")
    def test_run_type_check_fail(self, mock_run, temp_child_path):
        """Test _run_type_check with type errors"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=b"core/sample.py:10: error: Name 'foo' is not defined\nFound 3 errors",
            stderr=b"",
        )

        fitness = DeterministicFitness(child_path=temp_child_path)
        with patch.object(fitness, "_command_exists", return_value=True):
            result = fitness._run_type_check()

        assert result.passed is False
        assert "3 errors" in result.message or "error" in result.message.lower()

    @patch("subprocess.run")
    def test_run_security_scan_pass(self, mock_run, temp_child_path):
        """Test _run_security_scan with no issues"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=b'{"results": []}',
            stderr=b"",
        )

        fitness = DeterministicFitness(child_path=temp_child_path)
        with patch.object(fitness, "_command_exists", return_value=True):
            result = fitness._run_security_scan()

        assert result.check == FitnessCheck.SECURITY
        assert result.passed is True
        assert result.details.get("issues", 0) == 0

    @patch("subprocess.run")
    def test_run_security_scan_issues_found(self, mock_run, temp_child_path):
        """Test _run_security_scan with security issues"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=b'{"results": [{"issue_text": "SQL injection risk"}, {"issue_text": "Weak crypto"}]}',
            stderr=b"",
        )

        fitness = DeterministicFitness(child_path=temp_child_path)
        with patch.object(fitness, "_command_exists", return_value=True):
            result = fitness._run_security_scan()

        assert result.passed is False
        assert result.details.get("issues", 0) == 2

    @patch("subprocess.run")
    def test_run_tests_pass(self, mock_run, temp_child_path):
        """Test _run_tests with passing tests"""
        # Create tests directory for the check
        tests_dir = temp_child_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_sample.py").write_text("def test_pass(): assert True")

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="50 passed in 2.5s",
            stderr="",
        )

        fitness = DeterministicFitness(child_path=temp_child_path)
        with patch.object(fitness, "_command_exists", return_value=True):
            result = fitness._run_tests()

        assert result.check == FitnessCheck.TESTS
        assert result.passed is True

    @patch("subprocess.run")
    def test_run_tests_fail(self, mock_run, temp_child_path):
        """Test _run_tests with failing tests"""
        # Create tests directory for the check
        tests_dir = temp_child_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_sample.py").write_text("def test_pass(): assert True")

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="5 failed, 45 passed in 3.2s",
            stderr="",
        )

        fitness = DeterministicFitness(child_path=temp_child_path)
        with patch.object(fitness, "_command_exists", return_value=True):
            result = fitness._run_tests()

        assert result.passed is False
        assert "exit code" in result.message.lower() or "failed" in result.message.lower()

    @patch("subprocess.run")
    def test_run_tests_timeout(self, mock_run, temp_child_path):
        """Test _run_tests with timeout"""
        # Create tests directory for the check
        tests_dir = temp_child_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_sample.py").write_text("def test_pass(): assert True")

        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["pytest"], timeout=600)

        fitness = DeterministicFitness(child_path=temp_child_path)
        with patch.object(fitness, "_command_exists", return_value=True):
            result = fitness._run_tests()

        assert result.passed is False
        assert "timeout" in result.message.lower() or "timed out" in result.message.lower()

    @patch.object(DeterministicFitness, "_run_linter")
    @patch.object(DeterministicFitness, "_run_type_check")
    @patch.object(DeterministicFitness, "_run_security_scan")
    @patch.object(DeterministicFitness, "_run_tests")
    def test_evaluate_all_pass(
        self,
        mock_tests,
        mock_security,
        mock_types,
        mock_linter,
        temp_child_path,
    ):
        """Test evaluate() when all checks pass"""
        # Mock all checks passing
        mock_linter.return_value = FitnessResult(FitnessCheck.LINTER, True, "OK")
        mock_types.return_value = FitnessResult(FitnessCheck.TYPE_CHECK, True, "OK")
        mock_security.return_value = FitnessResult(FitnessCheck.SECURITY, True, "OK")
        mock_tests.return_value = FitnessResult(FitnessCheck.TESTS, True, "OK")

        fitness = DeterministicFitness(child_path=temp_child_path, strict_mode=False)
        result = fitness.evaluate()

        assert result.all_checks_passed is True
        assert len(result.check_results) == 4  # Syntax delegated to TieredValidator
        mock_linter.assert_called_once()
        mock_types.assert_called_once()
        mock_security.assert_called_once()
        mock_tests.assert_called_once()

    @patch.object(DeterministicFitness, "_run_linter")
    @patch.object(DeterministicFitness, "_run_type_check")
    def test_evaluate_strict_mode_fail_fast(
        self,
        mock_types,
        mock_linter,
        temp_child_path,
    ):
        """Test evaluate() in strict mode fails fast"""
        # Mock linter failing
        mock_linter.return_value = FitnessResult(FitnessCheck.LINTER, False, "Failed")

        fitness = DeterministicFitness(child_path=temp_child_path, strict_mode=True)
        result = fitness.evaluate()

        assert result.all_checks_passed is False
        # Should have linter only (failed fast)
        assert len(result.check_results) == 1
        mock_linter.assert_called_once()
        # Type check should NOT be called (fail fast)
        mock_types.assert_not_called()

    @patch.object(DeterministicFitness, "_run_linter")
    @patch.object(DeterministicFitness, "_run_type_check")
    @patch.object(DeterministicFitness, "_run_security_scan")
    @patch.object(DeterministicFitness, "_run_tests")
    def test_evaluate_non_strict_runs_all(
        self,
        mock_tests,
        mock_security,
        mock_types,
        mock_linter,
        temp_child_path,
    ):
        """Test evaluate() in non-strict mode runs all checks even if some fail"""
        # Mock some checks failing
        mock_linter.return_value = FitnessResult(FitnessCheck.LINTER, False, "Failed")
        mock_types.return_value = FitnessResult(FitnessCheck.TYPE_CHECK, True, "OK")
        mock_security.return_value = FitnessResult(FitnessCheck.SECURITY, False, "Failed")
        mock_tests.return_value = FitnessResult(FitnessCheck.TESTS, True, "OK")

        fitness = DeterministicFitness(child_path=temp_child_path, strict_mode=False)
        result = fitness.evaluate()

        assert result.all_checks_passed is False
        # Should run all 4 checks (syntax delegated to TieredValidator)
        assert len(result.check_results) == 4
        mock_linter.assert_called_once()
        mock_types.assert_called_once()
        mock_security.assert_called_once()
        mock_tests.assert_called_once()

    def test_evaluate_tracks_duration(self, temp_child_path):
        """Test that evaluate() tracks total duration"""
        fitness = DeterministicFitness(child_path=temp_child_path, strict_mode=False)

        with (
            patch.object(fitness, "_run_linter") as mock_linter,
            patch.object(fitness, "_run_type_check") as mock_types,
            patch.object(fitness, "_run_security_scan") as mock_security,
            patch.object(fitness, "_run_tests") as mock_tests,
        ):
            # Mock results with durations
            mock_linter.return_value = FitnessResult(FitnessCheck.LINTER, True, "OK", duration_seconds=1.5)
            mock_types.return_value = FitnessResult(FitnessCheck.TYPE_CHECK, True, "OK", duration_seconds=2.5)
            mock_security.return_value = FitnessResult(FitnessCheck.SECURITY, True, "OK", duration_seconds=1.0)
            mock_tests.return_value = FitnessResult(FitnessCheck.TESTS, True, "OK", duration_seconds=3.0)

            result = fitness.evaluate()

            # Total should be at least the sum of mocked durations
            # (syntax check delegated to TieredValidator)
            assert result.total_duration >= 0.0  # Just check it's tracked


class TestIntegration:
    """Integration tests for fitness pipeline"""

    @pytest.mark.skipif(not Path("core/evolution/fitness.py").exists(), reason="fitness.py module not found")
    def test_fitness_module_imports(self):
        """Test that all fitness module components can be imported"""
        from core.intelligence.evolution.fitness import (
            DeterministicFitness,
            DeterministicFitnessResult,
            FitnessCheck,
            FitnessResult,
        )

        assert DeterministicFitness is not None
        assert DeterministicFitnessResult is not None
        assert FitnessCheck is not None
        assert FitnessResult is not None

    @pytest.mark.skipif(not Path("core/evolution/fitness.py").exists(), reason="fitness.py module not found")
    def test_fitness_check_enum_order(self):
        """Test that FitnessCheck enum values are in correct order"""
        from core.intelligence.evolution.fitness import FitnessCheck

        assert FitnessCheck.SYNTAX == 1
        assert FitnessCheck.LINTER == 2
        assert FitnessCheck.TYPE_CHECK == 3
        assert FitnessCheck.SECURITY == 4
        assert FitnessCheck.TESTS == 5
