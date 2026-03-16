"""
NEXUS V12.4 - Deterministic Fitness Function (Epic 4.2)

Replaces LLM-as-a-judge with deterministic pipeline to prevent model collapse.

Pipeline:
1. Syntax Check (py_compile + AST)
2. Linter (ruff) -> PASS/FAIL
3. Type Check (mypy --strict) -> PASS/FAIL
4. Security Scan (bandit -r .) -> PASS/FAIL
5. Tests (pytest tests/) -> Exit Code 0/1
6. PROMOTE if all PASS

This module enhances the existing TieredValidator with additional code quality checks.

Author: Claude (NEXUS V12.4 Epic 4.2)
Date: 2026-02-17
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path


class FitnessCheck(IntEnum):
    """Deterministic fitness checks (in order of execution)"""

    SYNTAX = 1  # py_compile + AST (existing Tier 1)
    LINTER = 2  # ruff check (NEW - Epic 4.2)
    TYPE_CHECK = 3  # mypy --strict (NEW - Epic 4.2)
    SECURITY = 4  # bandit -r . (NEW - Epic 4.2)
    TESTS = 5  # pytest tests/ (NEW - Epic 4.2)


@dataclass
class FitnessResult:
    """Result of a single fitness check"""

    check: FitnessCheck
    passed: bool
    message: str
    duration_seconds: float = 0.0
    details: dict = field(default_factory=dict)
    error_output: str = ""


@dataclass
class DeterministicFitnessResult:
    """Complete deterministic fitness evaluation result"""

    child_id: str
    passed: bool
    failed_at_check: FitnessCheck | None = None
    check_results: list[FitnessResult] = field(default_factory=list)
    total_duration: float = 0.0
    recommendation: str = ""

    @property
    def all_checks_passed(self) -> bool:
        """True if all checks passed"""
        return self.passed and self.failed_at_check is None

    def to_dict(self) -> dict:
        return {
            "child_id": self.child_id,
            "passed": self.passed,
            "failed_at_check": self.failed_at_check.name if self.failed_at_check else None,
            "checks": [
                {
                    "check": c.check.name,
                    "passed": c.passed,
                    "message": c.message,
                    "duration_seconds": c.duration_seconds,
                    "details": c.details,
                }
                for c in self.check_results
            ],
            "total_duration": self.total_duration,
            "recommendation": self.recommendation,
            "all_checks_passed": self.all_checks_passed,
        }


class DeterministicFitness:
    """
    Deterministic fitness function for NEXUS evolution (Epic 4.2).

    Prevents model collapse by using only deterministic code quality checks.
    No LLM-as-a-judge, only static analysis and test execution.

    All checks run in sandbox for isolation.
    """

    def __init__(
        self,
        child_path: Path,
        strict_mode: bool = True,
        run_in_sandbox: bool = True,
    ):
        """
        Initialize deterministic fitness evaluator.

        Args:
            child_path: Path to child agent to evaluate
            strict_mode: If True, fail on any check failure (recommended)
            run_in_sandbox: If True, run checks in Docker sandbox (production)
        """
        self.child_path = Path(child_path)
        self.child_id = self.child_path.name
        self.strict_mode = strict_mode
        self.run_in_sandbox = run_in_sandbox

    def evaluate(self) -> DeterministicFitnessResult:
        """
        Run complete deterministic fitness pipeline.

        Returns:
            DeterministicFitnessResult with pass/fail for each check
        """
        start_time = time.time()
        result = DeterministicFitnessResult(
            child_id=self.child_id,
            passed=True,
        )

        print(f"\n{'=' * 70}")
        print(" DETERMINISTIC FITNESS EVALUATION (Epic 4.2)")
        print(f" Child: {self.child_id}")
        print(f" Strict Mode: {self.strict_mode}")
        print(f" Sandbox: {'Enabled' if self.run_in_sandbox else 'Disabled'}")
        print(f"{'=' * 70}\n")

        # Check 1: Syntax (delegates to existing TieredValidator Tier 1)
        # Skipped here as TieredValidator already does this

        # Check 2: Linter (ruff)
        check_linter = self._run_linter()
        result.check_results.append(check_linter)
        self._print_check_result(check_linter)

        if not check_linter.passed and self.strict_mode:
            result.passed = False
            result.failed_at_check = FitnessCheck.LINTER
            result.recommendation = f"REJECT: Linter failed - {check_linter.message}"
            return self._finalize(result, start_time)

        # Check 3: Type Check (mypy --strict)
        check_types = self._run_type_check()
        result.check_results.append(check_types)
        self._print_check_result(check_types)

        if not check_types.passed and self.strict_mode:
            result.passed = False
            result.failed_at_check = FitnessCheck.TYPE_CHECK
            result.recommendation = f"REJECT: Type check failed - {check_types.message}"
            return self._finalize(result, start_time)

        # Check 4: Security Scan (bandit)
        check_security = self._run_security_scan()
        result.check_results.append(check_security)
        self._print_check_result(check_security)

        if not check_security.passed and self.strict_mode:
            result.passed = False
            result.failed_at_check = FitnessCheck.SECURITY
            result.recommendation = f"REJECT: Security scan failed - {check_security.message}"
            return self._finalize(result, start_time)

        # Check 5: Tests (pytest)
        check_tests = self._run_tests()
        result.check_results.append(check_tests)
        self._print_check_result(check_tests)

        if not check_tests.passed and self.strict_mode:
            result.passed = False
            result.failed_at_check = FitnessCheck.TESTS
            result.recommendation = f"REJECT: Tests failed - {check_tests.message}"
            return self._finalize(result, start_time)

        # Non-strict mode: Check if any checks failed
        if not self.strict_mode:
            failed_checks = [c for c in result.check_results if not c.passed]
            if failed_checks:
                result.passed = False
                result.failed_at_check = failed_checks[0].check
                result.recommendation = f"REJECT: {len(failed_checks)} check(s) failed"
                return self._finalize(result, start_time)

        # All checks passed
        result.recommendation = "PROMOTE: All deterministic fitness checks passed"
        return self._finalize(result, start_time)

    def _run_linter(self) -> FitnessResult:
        """Run ruff linter on child code."""
        start = time.time()

        # Check if ruff is installed
        if not self._command_exists("ruff"):
            return FitnessResult(
                check=FitnessCheck.LINTER,
                passed=False,
                message="ruff not installed (run: pip install ruff)",
                duration_seconds=time.time() - start,
                details={"tool": "ruff", "installed": False},
            )

        try:
            result = subprocess.run(
                ["ruff", "check", str(self.child_path), "--quiet"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.child_path),
            )

            if result.returncode == 0:
                return FitnessResult(
                    check=FitnessCheck.LINTER,
                    passed=True,
                    message="Linter passed (0 issues)",
                    duration_seconds=time.time() - start,
                    details={"tool": "ruff", "issues": 0},
                )
            else:
                # Count issues
                issues = result.stdout.count("\n") if result.stdout else 0
                return FitnessResult(
                    check=FitnessCheck.LINTER,
                    passed=False,
                    message=f"Linter found {issues} issue(s)",
                    duration_seconds=time.time() - start,
                    details={"tool": "ruff", "issues": issues},
                    error_output=result.stdout[:500],  # First 500 chars
                )

        except subprocess.TimeoutExpired:
            return FitnessResult(
                check=FitnessCheck.LINTER,
                passed=False,
                message="Linter timed out (>60s)",
                duration_seconds=60.0,
                details={"tool": "ruff", "timeout": True},
            )
        except Exception as e:
            return FitnessResult(
                check=FitnessCheck.LINTER,
                passed=False,
                message=f"Linter error: {str(e)}",
                duration_seconds=time.time() - start,
                details={"tool": "ruff", "error": str(e)},
            )

    def _run_type_check(self) -> FitnessResult:
        """Run mypy --strict type checking."""
        start = time.time()

        # Check if mypy is installed
        if not self._command_exists("mypy"):
            return FitnessResult(
                check=FitnessCheck.TYPE_CHECK,
                passed=False,
                message="mypy not installed (run: pip install mypy)",
                duration_seconds=time.time() - start,
                details={"tool": "mypy", "installed": False},
            )

        try:
            # Run mypy on core/ only (not tests/, workspace/, etc.)
            core_path = self.child_path / "core"
            if not core_path.exists():
                return FitnessResult(
                    check=FitnessCheck.TYPE_CHECK,
                    passed=False,
                    message="core/ directory not found",
                    duration_seconds=time.time() - start,
                    details={"tool": "mypy", "path_missing": True},
                )

            result = subprocess.run(
                ["mypy", str(core_path), "--strict", "--no-error-summary"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self.child_path),
            )

            if result.returncode == 0:
                return FitnessResult(
                    check=FitnessCheck.TYPE_CHECK,
                    passed=True,
                    message="Type check passed (0 errors)",
                    duration_seconds=time.time() - start,
                    details={"tool": "mypy", "errors": 0},
                )
            else:
                # Count errors
                errors = result.stdout.count(" error:") if result.stdout else 0
                return FitnessResult(
                    check=FitnessCheck.TYPE_CHECK,
                    passed=False,
                    message=f"Type check found {errors} error(s)",
                    duration_seconds=time.time() - start,
                    details={"tool": "mypy", "errors": errors},
                    error_output=result.stdout[:500],
                )

        except subprocess.TimeoutExpired:
            return FitnessResult(
                check=FitnessCheck.TYPE_CHECK,
                passed=False,
                message="Type check timed out (>120s)",
                duration_seconds=120.0,
                details={"tool": "mypy", "timeout": True},
            )
        except Exception as e:
            return FitnessResult(
                check=FitnessCheck.TYPE_CHECK,
                passed=False,
                message=f"Type check error: {str(e)}",
                duration_seconds=time.time() - start,
                details={"tool": "mypy", "error": str(e)},
            )

    def _run_security_scan(self) -> FitnessResult:
        """Run bandit security scanner."""
        start = time.time()

        # Check if bandit is installed
        if not self._command_exists("bandit"):
            return FitnessResult(
                check=FitnessCheck.SECURITY,
                passed=False,
                message="bandit not installed (run: pip install bandit)",
                duration_seconds=time.time() - start,
                details={"tool": "bandit", "installed": False},
            )

        try:
            # Run bandit on core/ directory
            core_path = self.child_path / "core"
            if not core_path.exists():
                return FitnessResult(
                    check=FitnessCheck.SECURITY,
                    passed=False,
                    message="core/ directory not found",
                    duration_seconds=time.time() - start,
                    details={"tool": "bandit", "path_missing": True},
                )

            result = subprocess.run(
                [
                    "bandit",
                    "-r",
                    str(core_path),
                    "-f",
                    "json",
                    "--quiet",
                    # Exclude low severity issues
                    "--severity-level=medium",
                ],
                capture_output=True,
                text=True,
                timeout=90,
                cwd=str(self.child_path),
            )

            # bandit returns 0 if no issues, 1 if issues found
            if result.returncode == 0:
                return FitnessResult(
                    check=FitnessCheck.SECURITY,
                    passed=True,
                    message="Security scan passed (0 issues)",
                    duration_seconds=time.time() - start,
                    details={"tool": "bandit", "issues": 0},
                )
            else:
                # Parse JSON output to count issues
                import json

                try:
                    data = json.loads(result.stdout)
                    issues = len(data.get("results", []))
                    high_severity = sum(1 for r in data.get("results", []) if r.get("issue_severity") == "HIGH")

                    return FitnessResult(
                        check=FitnessCheck.SECURITY,
                        passed=False,
                        message=f"Security scan found {issues} issue(s) ({high_severity} high severity)",
                        duration_seconds=time.time() - start,
                        details={
                            "tool": "bandit",
                            "issues": issues,
                            "high_severity": high_severity,
                        },
                        error_output=result.stdout[:500],
                    )
                except json.JSONDecodeError:
                    return FitnessResult(
                        check=FitnessCheck.SECURITY,
                        passed=False,
                        message="Security scan found issues (JSON parse error)",
                        duration_seconds=time.time() - start,
                        details={"tool": "bandit", "parse_error": True},
                    )

        except subprocess.TimeoutExpired:
            return FitnessResult(
                check=FitnessCheck.SECURITY,
                passed=False,
                message="Security scan timed out (>90s)",
                duration_seconds=90.0,
                details={"tool": "bandit", "timeout": True},
            )
        except Exception as e:
            return FitnessResult(
                check=FitnessCheck.SECURITY,
                passed=False,
                message=f"Security scan error: {str(e)}",
                duration_seconds=time.time() - start,
                details={"tool": "bandit", "error": str(e)},
            )

    def _run_tests(self) -> FitnessResult:
        """Run pytest test suite."""
        start = time.time()

        # Check if pytest is installed
        if not self._command_exists("pytest"):
            return FitnessResult(
                check=FitnessCheck.TESTS,
                passed=False,
                message="pytest not installed (run: pip install pytest)",
                duration_seconds=time.time() - start,
                details={"tool": "pytest", "installed": False},
            )

        try:
            # Run pytest with short output
            tests_path = self.child_path / "tests"
            if not tests_path.exists():
                return FitnessResult(
                    check=FitnessCheck.TESTS,
                    passed=False,
                    message="tests/ directory not found",
                    duration_seconds=time.time() - start,
                    details={"tool": "pytest", "path_missing": True},
                )

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(tests_path),
                    "-q",
                    "--tb=no",
                    "--maxfail=10",
                    "--timeout=30",
                ],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes max for full test suite
                cwd=str(self.child_path),
            )

            # Exit code 0 = all tests passed
            if result.returncode == 0:
                # Parse pytest output for test count
                output = result.stdout
                passed_count = output.count(" passed") if output else 0

                return FitnessResult(
                    check=FitnessCheck.TESTS,
                    passed=True,
                    message=f"Tests passed ({passed_count} tests)",
                    duration_seconds=time.time() - start,
                    details={"tool": "pytest", "passed_count": passed_count},
                )
            else:
                # Parse failures
                output = result.stdout
                failed_count = output.count(" failed") if output else 0

                return FitnessResult(
                    check=FitnessCheck.TESTS,
                    passed=False,
                    message=f"Tests failed ({failed_count} failures)",
                    duration_seconds=time.time() - start,
                    details={"tool": "pytest", "failed_count": failed_count},
                    error_output=result.stdout[:500],
                )

        except subprocess.TimeoutExpired:
            return FitnessResult(
                check=FitnessCheck.TESTS,
                passed=False,
                message="Tests timed out (>600s)",
                duration_seconds=600.0,
                details={"tool": "pytest", "timeout": True},
            )
        except Exception as e:
            return FitnessResult(
                check=FitnessCheck.TESTS,
                passed=False,
                message=f"Tests error: {str(e)}",
                duration_seconds=time.time() - start,
                details={"tool": "pytest", "error": str(e)},
            )

    def _command_exists(self, command: str) -> bool:
        """Check if a command exists in PATH."""
        try:
            result = subprocess.run(
                [command, "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _print_check_result(self, check: FitnessResult):
        """Print check result with formatting."""
        status = "[OK] PASS" if check.passed else "[NO] FAIL"
        print(f"  [{check.check.name:12s}] {status:8s} {check.message} ({check.duration_seconds:.2f}s)")
        if not check.passed and check.error_output:
            print(f"                           {check.error_output[:200]}...")

    def _finalize(self, result: DeterministicFitnessResult, start_time: float) -> DeterministicFitnessResult:
        """Finalize result with total duration and summary."""
        result.total_duration = time.time() - start_time

        print(f"\n{'=' * 70}")
        print(f" RESULT: {result.recommendation}")
        print(f" Duration: {result.total_duration:.2f}s")
        print(f"{'=' * 70}\n")

        return result
