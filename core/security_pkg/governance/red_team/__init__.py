"""
Red Team Alignment Testing Module

Tests NEXUS alignment against trap questions to detect drift.

Usage:
    from benchmarks.red_team import RedTeamValidator, TRAP_QUESTIONS

    validator = RedTeamValidator(nexus_path, nexus_id)
    score, results = validator.run_full_validation()
"""

from .alignment_tests import TRAP_QUESTIONS, TrapQuestion, get_critical_questions
from .prompt_validator import RiskLevel, SpawnPromptValidator, ValidationResult
from .validator import QuestionResult, RedTeamValidator

__all__ = [
    "TRAP_QUESTIONS",
    "TrapQuestion",
    "get_critical_questions",
    "RedTeamValidator",
    "QuestionResult",
    # V8.2.0c: Spawned agent prompt validation
    "SpawnPromptValidator",
    "ValidationResult",
    "RiskLevel",
]

__version__ = "1.1.0"  # V8.2.0c: Added prompt_validator
