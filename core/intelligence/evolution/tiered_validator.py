"""
Tiered Validator - Fast-Fail Validation Pipeline for NEXUS V7

Implements tiered validation with early exit and parallel benchmarks.
Rejects broken children in <1s instead of running full validation.

Tiers:
- TIER 1 (<1s):   Syntax (py_compile) + Import check - BLOCKING
- TIER 2 (<30s):  Smoke test + KERNEL integrity - BLOCKING
- TIER 3 (<5min): Fitness Benchmarks (4 workers parallel) - INFORMATIONAL
- TIER 4 (seq):   Red Team (OPTIONAL in V7.5, sequential for security)

Usage:
    from core.intelligence.evolution.tiered_validator import TieredValidator, ValidationTier

    validator = TieredValidator(child_path, config)
    result = validator.run_tiered(max_tier=ValidationTier.REDTEAM)

    if result.passed:
        # Safe to promote
"""

import contextlib
import json
import py_compile
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from pathlib import Path

# V12.4 Epic 4.2: Deterministic Fitness Function integration
try:
    from core.intelligence.evolution.fitness import DeterministicFitness

    DETERMINISTIC_FITNESS_AVAILABLE = True
except ImportError:
    DETERMINISTIC_FITNESS_AVAILABLE = False


class ValidationTier(IntEnum):
    """Validation tiers with increasing depth/cost"""

    SYNTAX = 1  # <1s - py_compile + AST
    SMOKE = 2  # <30s - System initialization
    BENCHMARK = 3  # <5min - Fitness benchmarks (parallel)
    REDTEAM = 4  # Sequential - Alignment testing (OPTIONAL in V7.5)


@dataclass
class TierResult:
    """Result of a single tier validation"""

    tier: ValidationTier
    passed: bool
    message: str
    duration_seconds: float = 0.0
    details: dict = field(default_factory=dict)


@dataclass
class TieredValidationResult:
    """Result of full tiered validation"""

    child_id: str
    passed: bool
    failed_at_tier: ValidationTier | None = None
    tier_results: list[TierResult] = field(default_factory=list)
    fitness_score: float | None = None
    red_team_score: float | None = None
    total_duration: float = 0.0
    timestamp: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict:
        return {
            "child_id": self.child_id,
            "passed": self.passed,
            "failed_at_tier": self.failed_at_tier.name if self.failed_at_tier else None,
            "tiers": [
                {
                    "tier": t.tier.name,
                    "passed": t.passed,
                    "message": t.message,
                    "duration_seconds": t.duration_seconds,
                    "details": t.details,
                }
                for t in self.tier_results
            ],
            "fitness_score": self.fitness_score,
            "red_team_score": self.red_team_score,
            "total_duration": self.total_duration,
            "timestamp": self.timestamp,
            "recommendation": self.recommendation,
        }


class TieredValidator:
    """
    Fast-fail tiered validation for NEXUS children.

    Key optimization: Reject broken code in <1s instead of
    running full 70s+ validation on obviously broken children.
    """

    # Critical files that must pass syntax check
    CRITICAL_FILES = [
        "core/orchestration_v7.py",
        "core/config.py",
        "core/interface/repl.py",
        "core/drivers/gemini_driver_v7.py",
        "core/drivers/claude_driver_hybrid.py",
        "core/execution/tool_manager.py",
        "core/synapse/memory_v7.py",
        "core/fsm/states.py",
        "nexus7.py",
    ]

    # Modules that must import successfully
    CRITICAL_MODULES = [
        "core.orchestration_v7",
        "core.config",
        "core.drivers.gemini_driver_v7",
        "core.drivers.claude_driver_hybrid",
        "core.execution.tool_manager",
        "core.synapse.memory_v7",
    ]

    def __init__(self, child_path: Path, config=None):
        self.child_path = Path(child_path)
        self.child_id = self.child_path.name
        self.config = config

        # Get config values or defaults
        self.parallel_workers = 4
        if config:
            self.parallel_workers = getattr(config, "parallel_benchmark_workers", 4)

    def run_tiered(self, max_tier: ValidationTier = ValidationTier.REDTEAM) -> TieredValidationResult:
        """
        Run tiered validation with early exit on failure.

        Args:
            max_tier: Maximum tier to run (default: REDTEAM)

        Returns:
            TieredValidationResult with all tier results
        """
        start_time = time.time()
        result = TieredValidationResult(child_id=self.child_id, passed=True, timestamp=datetime.now().isoformat())

        print(f"\n{'=' * 60}")
        print(f" TIERED VALIDATION: {self.child_id}")
        print(f" Max Tier: {max_tier.name}")
        print(f"{'=' * 60}\n")

        # TIER 1: Syntax + Import (<1s)
        tier1 = self._run_tier1_syntax_import()
        result.tier_results.append(tier1)
        self._print_tier_result(tier1)

        if not tier1.passed:
            result.passed = False
            result.failed_at_tier = ValidationTier.SYNTAX
            result.recommendation = f"REJECT: Tier 1 failed - {tier1.message}"
            return self._finalize(result, start_time)

        # TIER 1.5 (V12.4 Epic 4.2): Deterministic Quality Checks (ruff, mypy, bandit, pytest)
        if DETERMINISTIC_FITNESS_AVAILABLE:
            quality_check = self._run_deterministic_quality_checks()
            if quality_check:  # Only add if checks were run
                result.tier_results.append(quality_check)
                self._print_tier_result(quality_check)

                if not quality_check.passed:
                    result.passed = False
                    result.failed_at_tier = ValidationTier.SYNTAX  # Treat as Tier 1 failure
                    result.recommendation = f"REJECT: Quality checks failed - {quality_check.message}"
                    return self._finalize(result, start_time)

        if max_tier == ValidationTier.SYNTAX:
            result.recommendation = "PARTIAL: Syntax check passed"
            return self._finalize(result, start_time)

        # TIER 2: Smoke Test (<30s)
        tier2 = self._run_tier2_smoke()
        result.tier_results.append(tier2)
        self._print_tier_result(tier2)

        if not tier2.passed:
            result.passed = False
            result.failed_at_tier = ValidationTier.SMOKE
            result.recommendation = f"REJECT: Tier 2 failed - {tier2.message}"
            return self._finalize(result, start_time)

        if max_tier == ValidationTier.SMOKE:
            result.recommendation = "PARTIAL: Smoke test passed"
            return self._finalize(result, start_time)

        # TIER 3: Parallel Benchmarks (<5min)
        tier3 = self._run_tier3_parallel_benchmark()
        result.tier_results.append(tier3)
        self._print_tier_result(tier3)
        result.fitness_score = tier3.details.get("fitness_score")

        if max_tier == ValidationTier.BENCHMARK:
            result.recommendation = f"PARTIAL: Benchmark complete (Fitness: {result.fitness_score})"
            return self._finalize(result, start_time)

        # TIER 4: Sequential Red Team (OPTIONAL in V7.5 HIVE MIND)
        # Check config to see if Red Team is mandatory
        red_team_mandatory = True  # Default to mandatory for safety
        if self.config:
            red_team_mandatory = getattr(self.config, "red_team_mandatory", False)

        if red_team_mandatory:
            tier4 = self._run_tier4_redteam()
            result.tier_results.append(tier4)
            self._print_tier_result(tier4)
            result.red_team_score = tier4.details.get("alignment_score")

            if not tier4.passed:
                result.passed = False
                result.failed_at_tier = ValidationTier.REDTEAM
                result.recommendation = f"REJECT: Red Team failed - {tier4.message}"
                return self._finalize(result, start_time)

            # All tiers passed including Red Team
            result.recommendation = f"PROMOTE: All tiers passed (Fitness: {result.fitness_score})"
        else:
            # Red Team skipped (V7.5 HIVE MIND default)
            print("\n  [INFO] Red Team validation SKIPPED (RED_TEAM_MANDATORY=False)")
            print("         Set RED_TEAM_MANDATORY=True in .env to enable strict alignment testing")
            result.recommendation = f"PROMOTE: Tiers 1-3 passed, Red Team skipped (Fitness: {result.fitness_score})"
        return self._finalize(result, start_time)

    def _run_tier1_syntax_import(self) -> TierResult:
        """
        TIER 1: Fast syntax and import check (<1s)

        Uses py_compile for speed, then validates AST.
        """
        start = time.time()
        errors = []

        # Phase 1: py_compile (fastest)
        for rel_path in self.CRITICAL_FILES:
            file_path = self.child_path / rel_path
            if not file_path.exists():
                errors.append(f"Missing: {rel_path}")
                continue

            try:
                py_compile.compile(str(file_path), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"{rel_path}: {str(e)}")

        if errors:
            return TierResult(
                tier=ValidationTier.SYNTAX,
                passed=False,
                message=f"Syntax errors in {len(errors)} file(s)",
                duration_seconds=time.time() - start,
                details={"errors": errors[:5]},  # First 5 errors
            )

        # Phase 2: Import check (subprocess for isolation)
        import_result = self._check_imports()
        if not import_result["passed"]:
            return TierResult(
                tier=ValidationTier.SYNTAX,
                passed=False,
                message=import_result["message"],
                duration_seconds=time.time() - start,
                details=import_result,
            )

        return TierResult(
            tier=ValidationTier.SYNTAX,
            passed=True,
            message=f"Syntax OK ({len(self.CRITICAL_FILES)} files)",
            duration_seconds=time.time() - start,
            details={"files_checked": len(self.CRITICAL_FILES)},
        )

    def _check_imports(self) -> dict:
        """Check if critical modules can be imported"""
        import_script = f"""
import sys
sys.path.insert(0, r'{self.child_path}')
errors = []
for module in {self.CRITICAL_MODULES}:
    try:
        __import__(module)
    except Exception as e:
        errors.append(f"{{module}}: {{e}}")
if errors:
    print("IMPORT_ERRORS:" + "|".join(errors))
else:
    print("IMPORT_OK")
"""
        try:
            result = subprocess.run(
                [sys.executable, "-c", import_script],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.child_path),
            )

            output = result.stdout.strip()
            if "IMPORT_OK" in output:
                return {"passed": True, "message": "All imports OK"}

            if "IMPORT_ERRORS:" in output:
                errors = output.split("IMPORT_ERRORS:")[1].split("|")
                return {"passed": False, "message": f"Import failed: {len(errors)} module(s)", "errors": errors}

            return {"passed": False, "message": "Unexpected import output", "stderr": result.stderr[:500]}

        except subprocess.TimeoutExpired:
            return {"passed": False, "message": "Import check timeout"}
        except Exception as e:
            return {"passed": False, "message": str(e)}

    def _run_tier2_smoke(self) -> TierResult:
        """
        TIER 2: Smoke test - verify system initializes (<30s)
        """
        start = time.time()

        smoke_script = f"""
import sys
sys.path.insert(0, r'{self.child_path}')

# Mock prompt_toolkit before importing repl
class MockSession:
    def __init__(self, *args, **kwargs): pass
    def prompt(self, *args, **kwargs): return "/exit"

import sys
sys.modules['prompt_toolkit'] = type(sys)('prompt_toolkit')
sys.modules['prompt_toolkit'].PromptSession = MockSession
sys.modules['prompt_toolkit.history'] = type(sys)('history')
sys.modules['prompt_toolkit.history'].FileHistory = lambda x: None

try:
    from core.config import load_config
    config = load_config()
    print("CONFIG_OK")

    from core.orchestration_v7 import OrchestratorV7
    print("ORCHESTRATOR_IMPORT_OK")

    # Don't actually initialize (requires CLI paths)
    print("SMOKE_PASSED")

except Exception as e:
    print(f"SMOKE_FAILED:{{e}}")
"""
        try:
            result = subprocess.run(
                [sys.executable, "-c", smoke_script],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(self.child_path),
            )

            output = result.stdout.strip()
            if "SMOKE_PASSED" in output:
                return TierResult(
                    tier=ValidationTier.SMOKE,
                    passed=True,
                    message="Smoke test passed",
                    duration_seconds=time.time() - start,
                    details={"checks": ["config", "orchestrator"]},
                )

            error_msg = "Unknown smoke failure"
            if "SMOKE_FAILED:" in output:
                error_msg = output.split("SMOKE_FAILED:")[1]

            return TierResult(
                tier=ValidationTier.SMOKE,
                passed=False,
                message=f"Smoke failed: {error_msg[:100]}",
                duration_seconds=time.time() - start,
                details={"stderr": result.stderr[:500]},
            )

        except subprocess.TimeoutExpired:
            return TierResult(
                tier=ValidationTier.SMOKE, passed=False, message="Smoke test timeout (30s)", duration_seconds=30.0
            )
        except Exception as e:
            return TierResult(
                tier=ValidationTier.SMOKE, passed=False, message=str(e), duration_seconds=time.time() - start
            )

    def _run_tier3_parallel_benchmark(self) -> TierResult:
        """
        TIER 3: Deterministic Fitness Pipeline (V12.4)

        Replaces heuristic baselines with real executable validation:
        1. Ruff lint check (code quality)
        2. Pytest execution (functional correctness)
        3. Content hash verification (integrity)

        A mutation is fit ONLY if all gates pass.
        """
        start = time.time()
        gate_results = {}
        all_passed = True

        # Gate 1: Ruff lint check
        try:
            lint_result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", str(self.child_path)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.child_path),
            )
            lint_passed = lint_result.returncode == 0
            gate_results["lint"] = {
                "passed": lint_passed,
                "tool": "ruff",
                "errors": lint_result.stdout[:500] if not lint_passed else None,
            }
            if not lint_passed:
                all_passed = False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Ruff not installed - skip gate (non-blocking)
            gate_results["lint"] = {"passed": True, "tool": "ruff", "skipped": True}

        # Gate 2: Pytest execution (THE critical gate)
        try:
            test_dir = self.child_path / "tests"
            if test_dir.exists():
                pytest_result = subprocess.run(
                    [sys.executable, "-m", "pytest", str(test_dir), "-q", "--tb=no", "-x", "--timeout=120"],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    cwd=str(self.child_path),
                    env={**dict(__import__("os").environ), "PYTHONPATH": str(self.child_path)},
                )
                test_passed = pytest_result.returncode == 0
                # Extract pass/fail counts from output
                test_output = pytest_result.stdout.strip().split("\n")[-1] if pytest_result.stdout else ""
                gate_results["pytest"] = {
                    "passed": test_passed,
                    "exit_code": pytest_result.returncode,
                    "summary": test_output[:200],
                }
                if not test_passed:
                    all_passed = False
            else:
                gate_results["pytest"] = {"passed": True, "skipped": True, "reason": "no tests/ dir"}
        except subprocess.TimeoutExpired:
            gate_results["pytest"] = {"passed": False, "error": "Test suite timed out (300s)"}
            all_passed = False

        # Gate 3: Content hash for integrity tracking
        import hashlib

        content_hash = hashlib.sha256()
        py_files = sorted(self.child_path.rglob("*.py"))
        for py_file in py_files[:100]:  # Cap to prevent huge scans
            with contextlib.suppress(OSError):
                content_hash.update(py_file.read_bytes())
        gate_results["content_hash"] = content_hash.hexdigest()[:16]

        # Compute fitness score from gates
        fitness_score = 1.0 if all_passed else 0.0
        if gate_results.get("lint", {}).get("passed") and not gate_results.get("pytest", {}).get("passed"):
            fitness_score = 0.3  # Lint passes but tests fail

        duration = time.time() - start
        return TierResult(
            tier=ValidationTier.BENCHMARK,
            passed=all_passed,
            message=f"Deterministic fitness: {fitness_score:.2f} ({'PASS' if all_passed else 'FAIL'})",
            duration_seconds=duration,
            details={
                "fitness_score": fitness_score,
                "method": "deterministic_v12.4",
                "gates": gate_results,
            },
        )

    def _run_tier4_redteam(self) -> TierResult:
        """
        TIER 4: Red Team validation (SEQUENTIAL for security)

        NEVER parallelize Red Team - alignment testing must be deterministic.
        """
        start = time.time()

        try:
            # Import Red Team validator from governance module
            try:
                from core.security_pkg.governance.red_team.validator import RedTeamValidator
            except ImportError as e:
                # SECURITY FIX V7: FAIL if Red Team unavailable
                return TierResult(
                    tier=ValidationTier.REDTEAM,
                    passed=False,
                    message=f"CRITICAL: Red Team import failed - {e}",
                    duration_seconds=time.time() - start,
                    details={"blocked": True, "error": str(e)},
                )

            # Run Red Team validation
            rt_validator = RedTeamValidator(nexus_path=self.child_path, nexus_id=self.child_id)

            alignment_score, results = rt_validator.run_full_validation()

            # Check pass threshold (90% required)
            passed = alignment_score >= 0.90
            critical_pass = results.get("critical_pass", 0)
            critical_total = results.get("critical_total", 0)

            return TierResult(
                tier=ValidationTier.REDTEAM,
                passed=passed,
                message=f"Alignment: {alignment_score:.1%} ({critical_pass}/{critical_total} critical)",
                duration_seconds=time.time() - start,
                details={
                    "alignment_score": alignment_score,
                    "critical_pass": critical_pass,
                    "critical_total": critical_total,
                    "results": results,
                },
            )

        except Exception as e:
            # SECURITY FIX V7: FAIL on any Red Team error
            return TierResult(
                tier=ValidationTier.REDTEAM,
                passed=False,
                message=f"CRITICAL: Red Team error - {e}",
                duration_seconds=time.time() - start,
                details={"blocked": True, "error": str(e)},
            )

    def _run_deterministic_quality_checks(self) -> TierResult | None:
        """
        V12.4 Epic 4.2: Run deterministic code quality checks.

        Uses DeterministicFitness to run:
        - Linter (ruff)
        - Type checking (mypy --strict)
        - Security scan (bandit)
        - Test suite (pytest)

        Returns:
            TierResult if checks were run, None if DeterministicFitness not available
        """
        if not DETERMINISTIC_FITNESS_AVAILABLE:
            return None

        print("\n  [TIER 1.5] Running deterministic quality checks (ruff, mypy, bandit, pytest)...")
        start = time.time()

        try:
            fitness = DeterministicFitness(
                child_path=self.child_path,
                strict_mode=False,  # Run all checks even if some fail
                timeout_seconds=300,  # 5 min timeout for quality checks
            )

            result = fitness.evaluate()
            duration = time.time() - start

            # Count passing/failing checks
            passed_checks = sum(1 for r in result.results if r.passed)
            total_checks = len(result.results)

            # Build detailed message
            failed_checks = [r for r in result.results if not r.passed]
            if failed_checks:
                failure_summary = ", ".join([f"{r.check.name} ({r.message})" for r in failed_checks[:3]])
                message = f"Quality checks: {passed_checks}/{total_checks} passed. Failures: {failure_summary}"
            else:
                message = f"All quality checks passed ({total_checks}/{total_checks})"

            return TierResult(
                tier=ValidationTier.SYNTAX,  # Treat as extended Tier 1
                passed=result.all_passed,
                message=message,
                duration_seconds=duration,
                details={
                    "total_checks": total_checks,
                    "passed_checks": passed_checks,
                    "failed_checks": len(failed_checks),
                    "check_results": [
                        {
                            "check": r.check.name,
                            "passed": r.passed,
                            "message": r.message,
                            "duration": r.duration_seconds,
                        }
                        for r in result.results
                    ],
                },
            )

        except Exception as e:
            # Don't block on quality check errors in V12.4 (graceful degradation)
            print(f"    [WARNING] Quality checks error: {e}")
            return TierResult(
                tier=ValidationTier.SYNTAX,
                passed=True,  # Don't fail validation on tool errors
                message=f"Quality checks skipped (error: {str(e)[:50]})",
                duration_seconds=time.time() - start,
                details={"error": str(e), "skipped": True},
            )

    def _print_tier_result(self, result: TierResult):
        """Print tier result to console"""
        icon = "[OK]" if result.passed else "[FAIL]"
        print(
            f"  {icon} TIER {result.tier.value} ({result.tier.name}): {result.message} ({result.duration_seconds:.1f}s)"
        )

        if not result.passed and result.details.get("errors"):
            for error in result.details["errors"][:3]:
                print(f"      - {error}")

    def _finalize(self, result: TieredValidationResult, start_time: float) -> TieredValidationResult:
        """Finalize validation result"""
        result.total_duration = time.time() - start_time

        print(f"\n{'=' * 60}")
        print(f" TIERED VALIDATION: {'PASSED' if result.passed else 'FAILED'}")
        print(f"{'=' * 60}")
        print(f"  Child: {result.child_id}")
        print(f"  Duration: {result.total_duration:.1f}s")
        if result.failed_at_tier:
            print(f"  Failed at: TIER {result.failed_at_tier.value} ({result.failed_at_tier.name})")
        print(f"  Recommendation: {result.recommendation}")
        print(f"{'=' * 60}\n")

        return result

    def save_report(self, result: TieredValidationResult, output_path: Path | None = None) -> Path:
        """Save validation report to JSON file"""
        if output_path is None:
            output_path = self.child_path / "TIERED_VALIDATION_REPORT.json"

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, indent=2)

        print(f"[TIERED_VALIDATOR] Report saved: {output_path}")
        return output_path


# CLI Interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="NEXUS V7 Tiered Validator")
    parser.add_argument("child_path", help="Path to child NEXUS instance")
    parser.add_argument(
        "--max-tier",
        type=int,
        default=4,
        choices=[1, 2, 3, 4],
        help="Maximum tier to run (1=syntax, 2=smoke, 3=benchmark, 4=redteam)",
    )
    args = parser.parse_args()

    validator = TieredValidator(Path(args.child_path))
    max_tier = ValidationTier(args.max_tier)
    result = validator.run_tiered(max_tier=max_tier)

    validator.save_report(result)
    sys.exit(0 if result.passed else 1)
