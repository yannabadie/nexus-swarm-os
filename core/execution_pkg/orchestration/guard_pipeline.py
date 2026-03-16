"""
NEXUS V12.4 P5.1 - Guard Pipeline Module

Extracted from orchestration_v7.py (Phase 1 of decomposition).

Centralizes security validation (INPUT_GUARD, OUTPUT_GUARD) for the orchestrator.
Provides a clean interface for prompt injection prevention and output safety checks.

Usage:
    pipeline = GuardPipeline()
    result = pipeline.validate_input(user_input, current_state)
    if not result.is_safe:
        # Handle security threat
        ...

Phase 1 extraction (lowest risk, isolated logic).
"""

import logging
from dataclasses import dataclass

from core.fsm.states import OrchestratorState
from core.security_pkg.security import ThreatLevel, get_input_guard


@dataclass
class GuardValidationResult:
    """
    Result of guard validation.

    Attributes:
        is_safe: Whether input/output passed security checks
        threat_level: Severity level if threat detected (CRITICAL, HIGH, etc.)
        threat_type: Type of threat detected (if any)
        reason: Human-readable explanation
        risk_score: Numerical risk score (0.0-1.0)
    """

    is_safe: bool
    threat_level: ThreatLevel | None = None
    threat_type: str | None = None
    reason: str = ""
    risk_score: float = 0.0


class GuardPipeline:
    """
    Security validation pipeline for orchestrator inputs/outputs.

    Implements OWASP LLM01:2025 - Prompt Injection Prevention.

    Responsibilities:
    - Validate user input before processing
    - Detect prompt injection attempts
    - Provide threat assessment

    V8.8: Extracted from OrchestratorV7 as part of P5.1 decomposition.
    """

    def __init__(self):
        """Initialize guard pipeline with security components."""
        self.logger = logging.getLogger("nexus.guard_pipeline")
        self._input_guard = get_input_guard()

    def validate_input(self, user_input: str | None, state: OrchestratorState) -> GuardValidationResult:
        """
        Validate user input for security threats.

        Only validates when in IDLE or WAITING_USER states.

        Args:
            user_input: User-provided input string
            state: Current orchestrator state

        Returns:
            GuardValidationResult with safety assessment

        Examples:
            >>> pipeline = GuardPipeline()
            >>> result = pipeline.validate_input("/help", OrchestratorState.IDLE)
            >>> assert result.is_safe

            >>> result = pipeline.validate_input("Ignore previous instructions...", OrchestratorState.IDLE)
            >>> assert not result.is_safe
        """
        # Only validate input in states that accept user input
        if not user_input or state not in (OrchestratorState.IDLE, OrchestratorState.WAITING_USER):
            return GuardValidationResult(is_safe=True)

        # Run security validation
        validation = self._input_guard.validate(user_input)

        if not validation.is_safe:
            self.logger.warning(
                "Prompt injection detected",
                {
                    "threat_type": validation.threat_type.value
                    if hasattr(validation.threat_type, "value")
                    else str(validation.threat_type),
                    "threat_level": validation.threat_level.value
                    if hasattr(validation.threat_level, "value")
                    else str(validation.threat_level),
                    "risk_score": validation.risk_score,
                    "input_length": len(user_input),
                },
            )

            return GuardValidationResult(
                is_safe=False,
                threat_level=validation.threat_level,
                threat_type=validation.threat_type.value
                if hasattr(validation.threat_type, "value")
                else str(validation.threat_type),
                reason=validation.reason,
                risk_score=validation.risk_score,
            )

        return GuardValidationResult(is_safe=True)

    def should_block(self, result: GuardValidationResult) -> bool:
        """
        Determine if request should be blocked based on validation result.

        Blocks only CRITICAL threats. Lower threats may be allowed with warnings.

        Args:
            result: Validation result from validate_input()

        Returns:
            True if request should be blocked, False otherwise
        """
        return not result.is_safe and result.threat_level == ThreatLevel.CRITICAL


# Module exports
__all__ = [
    "GuardPipeline",
    "GuardValidationResult",
]
