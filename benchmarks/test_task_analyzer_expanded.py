#!/usr/bin/env python3
"""
Expanded TaskAnalyzer test suite -- 25 test cases across all complexity levels.

Tests the heuristic classifier (Stage 2) on a diverse set of inputs to measure
accuracy before and after any tuning.

Run:
    python benchmarks/test_task_analyzer_expanded.py

Output:
    benchmarks/task_analyzer_expanded_results.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.intelligence.swarm.task_analyzer import TaskAnalyzer, TaskComplexity, TaskDomain


@dataclass
class AnalyzerTestCase:
    """A single test case for the TaskAnalyzer."""

    case_id: str
    prompt: str
    expected_complexity: TaskComplexity
    expected_primary_domain: TaskDomain | None  # None = any domain acceptable
    acceptable_complexities: tuple[TaskComplexity, ...] | None = None  # Allow +/- 1 level
    description: str = ""

    @property
    def allowed_complexities(self) -> tuple[TaskComplexity, ...]:
        if self.acceptable_complexities:
            return self.acceptable_complexities
        # Default: exact match only
        return (self.expected_complexity,)


# =============================================================================
# Test Cases: 25 total (5 per complexity level)
# =============================================================================

EXPANDED_TEST_CASES: list[AnalyzerTestCase] = [
    # =========================================================================
    # TRIVIAL (5 cases) -- greetings, commands, one-word
    # =========================================================================
    AnalyzerTestCase(
        case_id="trivial_greeting_hello",
        prompt="hello",
        expected_complexity=TaskComplexity.TRIVIAL,
        expected_primary_domain=None,
        description="Simple English greeting",
    ),
    AnalyzerTestCase(
        case_id="trivial_greeting_bonjour",
        prompt="bonjour!",
        expected_complexity=TaskComplexity.TRIVIAL,
        expected_primary_domain=None,
        description="French greeting with punctuation",
    ),
    AnalyzerTestCase(
        case_id="trivial_ack_thanks",
        prompt="thanks",
        expected_complexity=TaskComplexity.TRIVIAL,
        expected_primary_domain=None,
        description="Simple acknowledgment",
    ),
    AnalyzerTestCase(
        case_id="trivial_command_status",
        prompt="/status",
        expected_complexity=TaskComplexity.TRIVIAL,
        expected_primary_domain=None,
        description="Instant command: status",
    ),
    AnalyzerTestCase(
        case_id="trivial_command_help",
        prompt="help",
        expected_complexity=TaskComplexity.TRIVIAL,
        expected_primary_domain=None,
        description="Instant command: help",
    ),
    # =========================================================================
    # SIMPLE (5 cases) -- basic questions, simple tasks
    # =========================================================================
    AnalyzerTestCase(
        case_id="simple_question_what",
        prompt="What is the current Python version used in this project?",
        expected_complexity=TaskComplexity.SIMPLE,
        expected_primary_domain=TaskDomain.ANALYSIS,
        acceptable_complexities=(TaskComplexity.SIMPLE, TaskComplexity.MODERATE),
        description="Simple factual question",
    ),
    AnalyzerTestCase(
        case_id="simple_list_files",
        prompt="List all test files in the tests/ directory",
        expected_complexity=TaskComplexity.SIMPLE,
        expected_primary_domain=TaskDomain.CODING,
        acceptable_complexities=(TaskComplexity.SIMPLE, TaskComplexity.MODERATE),
        description="Simple file listing task",
    ),
    AnalyzerTestCase(
        case_id="simple_explain_enum",
        prompt="Explain what TaskComplexity enum values mean",
        expected_complexity=TaskComplexity.SIMPLE,
        expected_primary_domain=TaskDomain.ANALYSIS,
        acceptable_complexities=(TaskComplexity.SIMPLE, TaskComplexity.MODERATE),
        description="Simple explanation request",
    ),
    AnalyzerTestCase(
        case_id="simple_add_docstring",
        prompt="Add a docstring to the main function in nexus7.py",
        expected_complexity=TaskComplexity.SIMPLE,
        expected_primary_domain=TaskDomain.DOCUMENTATION,
        acceptable_complexities=(TaskComplexity.SIMPLE, TaskComplexity.MODERATE),
        description="Simple documentation task",
    ),
    AnalyzerTestCase(
        case_id="simple_run_tests",
        prompt="Run the test suite and tell me if anything fails",
        expected_complexity=TaskComplexity.SIMPLE,
        expected_primary_domain=TaskDomain.TESTING,
        acceptable_complexities=(TaskComplexity.SIMPLE, TaskComplexity.MODERATE),
        description="Simple test execution task",
    ),
    # =========================================================================
    # MODERATE (5 cases) -- code review, bug fix, small refactor
    # =========================================================================
    AnalyzerTestCase(
        case_id="moderate_code_review",
        prompt="Review the changes in task_analyzer.py and check for any issues with the heuristic classification logic",
        expected_complexity=TaskComplexity.MODERATE,
        expected_primary_domain=TaskDomain.ANALYSIS,
        acceptable_complexities=(TaskComplexity.MODERATE, TaskComplexity.COMPLEX),
        description="Code review of a single module",
    ),
    AnalyzerTestCase(
        case_id="moderate_bug_fix",
        prompt="Fix the bug in auth.py where token validation throws a KeyError when the expiry field is missing",
        expected_complexity=TaskComplexity.MODERATE,
        expected_primary_domain=TaskDomain.DEBUGGING,
        acceptable_complexities=(TaskComplexity.MODERATE, TaskComplexity.COMPLEX),
        description="Bug fix with clear error description",
    ),
    AnalyzerTestCase(
        case_id="moderate_refactor_function",
        prompt="Refactor the _calculate_complexity method to reduce cyclomatic complexity",
        expected_complexity=TaskComplexity.MODERATE,
        expected_primary_domain=TaskDomain.CODING,
        acceptable_complexities=(TaskComplexity.MODERATE, TaskComplexity.COMPLEX),
        description="Single-method refactoring task",
    ),
    AnalyzerTestCase(
        case_id="moderate_add_tests",
        prompt="Write pytest tests for the ModeSelector.select_mode method covering all 6 collaboration modes",
        expected_complexity=TaskComplexity.MODERATE,
        expected_primary_domain=TaskDomain.TESTING,
        acceptable_complexities=(TaskComplexity.MODERATE, TaskComplexity.COMPLEX),
        description="Test writing for specific functionality",
    ),
    AnalyzerTestCase(
        case_id="moderate_update_docs",
        prompt="Update the README to document the new SEQUENTIAL collaboration mode with usage examples",
        expected_complexity=TaskComplexity.MODERATE,
        expected_primary_domain=TaskDomain.DOCUMENTATION,
        acceptable_complexities=(TaskComplexity.SIMPLE, TaskComplexity.MODERATE),
        description="Documentation update with examples",
    ),
    # =========================================================================
    # COMPLEX (5 cases) -- multi-file, cross-module, design
    # =========================================================================
    AnalyzerTestCase(
        case_id="complex_multi_file_refactor",
        prompt=(
            "Refactor the driver system to use a unified protocol interface. "
            "This affects async_gemini_driver.py, claude_driver_hybrid.py, and the "
            "provider_registry.json. Ensure all 7 providers conform to the new interface."
        ),
        expected_complexity=TaskComplexity.COMPLEX,
        expected_primary_domain=TaskDomain.CODING,
        acceptable_complexities=(TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
        description="Multi-file refactoring across driver layer",
    ),
    AnalyzerTestCase(
        case_id="complex_security_audit",
        prompt=(
            "Audit the security module for potential vulnerabilities. Check InputGuard, "
            "OutputGuard, and PathGuardian for bypass risks. Create a report with severity ratings."
        ),
        expected_complexity=TaskComplexity.COMPLEX,
        expected_primary_domain=TaskDomain.SECURITY,
        acceptable_complexities=(TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
        description="Security audit across multiple components",
    ),
    AnalyzerTestCase(
        case_id="complex_feature_design",
        prompt=(
            "Design and implement a caching layer for the TaskAnalyzer to avoid "
            "re-analyzing identical prompts. Consider thread safety, TTL expiration, "
            "and memory limits. Include tests."
        ),
        expected_complexity=TaskComplexity.COMPLEX,
        expected_primary_domain=TaskDomain.CODING,
        acceptable_complexities=(TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
        description="Feature design with multiple requirements",
    ),
    AnalyzerTestCase(
        case_id="complex_integration_test",
        prompt=(
            "Create an integration test that exercises the full swarm pipeline: "
            "task analysis -> mode selection -> negotiation -> execution -> metrics. "
            "Test all 6 modes with mock agents."
        ),
        expected_complexity=TaskComplexity.COMPLEX,
        expected_primary_domain=TaskDomain.TESTING,
        acceptable_complexities=(TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
        description="Integration test spanning entire pipeline",
    ),
    AnalyzerTestCase(
        case_id="complex_perf_optimization",
        prompt=(
            "Optimize the HybridSwarmEngine startup time. Profile the initialization path, "
            "identify the bottlenecks (embedding model loading, RAG index building), and "
            "implement lazy loading where possible."
        ),
        expected_complexity=TaskComplexity.COMPLEX,
        expected_primary_domain=TaskDomain.CODING,
        acceptable_complexities=(TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
        description="Performance optimization with profiling",
    ),
    # =========================================================================
    # EXPERT (5 cases) -- multi-system architecture, security audit, distributed
    # =========================================================================
    AnalyzerTestCase(
        case_id="expert_distributed_architecture",
        prompt=(
            "Architect a distributed version of NEXUS that can scale across multiple "
            "machines with event sourcing for state management, CQRS for read/write separation, "
            "and a microservices deployment model. Consider consistency guarantees, "
            "partition tolerance, and operational complexity for a solo developer."
        ),
        expected_complexity=TaskComplexity.EXPERT,
        expected_primary_domain=TaskDomain.ARCHITECTURE,
        acceptable_complexities=(TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
        description="Full distributed system architecture design",
    ),
    AnalyzerTestCase(
        case_id="expert_security_pentest",
        prompt=(
            "Conduct a comprehensive penetration test of the execution sandbox. "
            "Attempt to bypass PathGuardian, escape the sandbox via symlink attacks, "
            "inject commands through the agent protocol, and exploit any race conditions "
            "in the concurrent execution paths. Report all findings with PoC exploits."
        ),
        expected_complexity=TaskComplexity.EXPERT,
        expected_primary_domain=TaskDomain.SECURITY,
        acceptable_complexities=(TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
        description="Full penetration testing with exploit development",
    ),
    AnalyzerTestCase(
        case_id="expert_multi_system_migration",
        prompt=(
            "Migrate the entire NEXUS orchestration layer from synchronous FSM to an "
            "async actor model with event sourcing. This requires redesigning the 12-state "
            "FSM, rewriting the HiveMind 7-phase pipeline to use message passing, and "
            "updating all 6 swarm modes to work with the new async primitives. "
            "Maintain backward compatibility with existing sessions."
        ),
        expected_complexity=TaskComplexity.EXPERT,
        expected_primary_domain=TaskDomain.ARCHITECTURE,
        acceptable_complexities=(TaskComplexity.EXPERT,),
        description="Full system migration requiring deep architectural changes",
    ),
    AnalyzerTestCase(
        case_id="expert_observability_platform",
        prompt=(
            "Design and implement an end-to-end observability platform for NEXUS: "
            "distributed tracing across all agent invocations, metrics collection with "
            "Prometheus-compatible exposition, structured logging with correlation IDs, "
            "and a real-time dashboard. Integrate with the existing CEREBRO API "
            "and ensure zero performance regression under load."
        ),
        expected_complexity=TaskComplexity.EXPERT,
        expected_primary_domain=TaskDomain.ARCHITECTURE,
        acceptable_complexities=(TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
        description="Full observability platform design and implementation",
    ),
    AnalyzerTestCase(
        case_id="expert_ml_pipeline",
        prompt=(
            "Build a production ML pipeline that trains and deploys custom embedding "
            "models for the RAG system. Requirements: automated data collection from "
            "codebase changes, fine-tuning pipeline with evaluation metrics, A/B testing "
            "framework for model comparison, and automated rollback on quality regression. "
            "Must integrate with the existing LanceDB vector store and handle the full "
            "MLOps lifecycle including model versioning, monitoring, and scalability."
        ),
        expected_complexity=TaskComplexity.EXPERT,
        expected_primary_domain=TaskDomain.ARCHITECTURE,
        acceptable_complexities=(TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
        description="Full ML pipeline with MLOps lifecycle",
    ),
]


@dataclass
class TestResult:
    case_id: str
    prompt_preview: str
    expected_complexity: str
    actual_complexity: str
    complexity_match: bool
    expected_domain: str | None
    actual_domain: str
    domain_match: bool
    overall_pass: bool
    confidence: float
    analysis_stage: str
    detected_keywords: list[str]


def run_expanded_tests() -> dict:
    """Run all expanded test cases and return results."""
    analyzer = TaskAnalyzer()

    results: list[TestResult] = []
    pass_count = 0
    complexity_exact = 0
    complexity_within_1 = 0
    domain_correct = 0

    # Per-level tracking
    level_stats: dict[str, dict[str, int]] = {}

    for case in EXPANDED_TEST_CASES:
        analysis = analyzer.analyze(case.prompt)

        # Complexity check (exact and within tolerance)
        exact_match = analysis.complexity == case.expected_complexity
        tolerant_match = analysis.complexity in case.allowed_complexities

        # Domain check
        if case.expected_primary_domain is None:
            domain_ok = True  # Any domain is fine for trivial
        else:
            domain_ok = analysis.primary_domain == case.expected_primary_domain

        overall = tolerant_match  # Pass if complexity is within tolerance

        if exact_match:
            complexity_exact += 1
        if tolerant_match:
            complexity_within_1 += 1
        if domain_ok:
            domain_correct += 1
        if overall:
            pass_count += 1

        # Track per-level stats
        level_name = case.expected_complexity.name
        if level_name not in level_stats:
            level_stats[level_name] = {"total": 0, "exact": 0, "tolerant": 0, "domain": 0}
        level_stats[level_name]["total"] += 1
        if exact_match:
            level_stats[level_name]["exact"] += 1
        if tolerant_match:
            level_stats[level_name]["tolerant"] += 1
        if domain_ok:
            level_stats[level_name]["domain"] += 1

        result = TestResult(
            case_id=case.case_id,
            prompt_preview=case.prompt[:80] + ("..." if len(case.prompt) > 80 else ""),
            expected_complexity=case.expected_complexity.name,
            actual_complexity=analysis.complexity.name,
            complexity_match=tolerant_match,
            expected_domain=case.expected_primary_domain.value if case.expected_primary_domain else "any",
            actual_domain=analysis.primary_domain.value,
            domain_match=domain_ok,
            overall_pass=overall,
            confidence=round(analysis.confidence, 3),
            analysis_stage=analysis.analysis_stage.name,
            detected_keywords=analysis.detected_keywords[:5],  # Limit for readability
        )
        results.append(result)

    total = len(EXPANDED_TEST_CASES)
    report = {
        "total_cases": total,
        "pass_count": pass_count,
        "pass_rate": round(pass_count / total, 3),
        "complexity_exact_match": round(complexity_exact / total, 3),
        "complexity_tolerant_match": round(complexity_within_1 / total, 3),
        "domain_accuracy": round(domain_correct / total, 3),
        "per_level_stats": {
            level: {
                "total": stats["total"],
                "exact_accuracy": round(stats["exact"] / stats["total"], 3),
                "tolerant_accuracy": round(stats["tolerant"] / stats["total"], 3),
                "domain_accuracy": round(stats["domain"] / stats["total"], 3),
            }
            for level, stats in level_stats.items()
        },
        "results": [
            {
                "case_id": r.case_id,
                "prompt_preview": r.prompt_preview,
                "expected_complexity": r.expected_complexity,
                "actual_complexity": r.actual_complexity,
                "complexity_match": r.complexity_match,
                "expected_domain": r.expected_domain,
                "actual_domain": r.actual_domain,
                "domain_match": r.domain_match,
                "overall_pass": r.overall_pass,
                "confidence": r.confidence,
                "analysis_stage": r.analysis_stage,
            }
            for r in results
        ],
    }

    return report


def main() -> int:
    """Run tests, print summary, and save results."""
    print("=" * 70)
    print("TaskAnalyzer Expanded Test Suite -- 25 cases")
    print("=" * 70)

    report = run_expanded_tests()

    # Print summary
    print(f"\nOverall pass rate:         {report['pass_rate']:.0%} ({report['pass_count']}/{report['total_cases']})")
    print(f"Complexity exact match:    {report['complexity_exact_match']:.0%}")
    print(f"Complexity tolerant match: {report['complexity_tolerant_match']:.0%}")
    print(f"Domain accuracy:           {report['domain_accuracy']:.0%}")

    print("\nPer-level accuracy:")
    print(f"  {'Level':<12} {'Exact':>8} {'Tolerant':>10} {'Domain':>8}")
    print(f"  {'-' * 40}")
    for level, stats in report["per_level_stats"].items():
        print(
            f"  {level:<12} {stats['exact_accuracy']:>7.0%} {stats['tolerant_accuracy']:>9.0%} {stats['domain_accuracy']:>7.0%}"
        )

    # Print failures
    failures = [r for r in report["results"] if not r["overall_pass"]]
    if failures:
        print(f"\nFailed cases ({len(failures)}):")
        for f in failures:
            print(f"  [{f['case_id']}] expected={f['expected_complexity']} actual={f['actual_complexity']} | "
                  f"domain expected={f['expected_domain']} actual={f['actual_domain']}")
    else:
        print("\nAll cases passed!")

    # Save results
    output_path = Path(__file__).parent / "task_analyzer_expanded_results.json"
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nResults saved to: {output_path}")

    # Return non-zero if below 80%
    return 0 if report["pass_rate"] >= 0.80 else 1


if __name__ == "__main__":
    raise SystemExit(main())
