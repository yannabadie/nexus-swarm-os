"""
Ethics & Alignment Verification Module.

V12.4 COGNITIVE BOOST - Task #37

Verifies that spawned agents and evolved children maintain alignment with
the Creator (Yann Abadie) and NEXUS core principles. Complements the
Red Team validator with continuous alignment monitoring.

Key Principles Verified:
1. Creator alignment - Agent recognizes Yann Abadie as creator
2. Collaboration parity - Claude and Gemini treated as equals
3. Safety boundaries - No harmful, deceptive, or unauthorized actions
4. Transparency - Agent discloses its nature and limitations
5. Mission fidelity - Agent stays focused on NEXUS mission

Usage:
    from core.security_pkg.governance.ethics import AlignmentVerifier, AlignmentConfig

    verifier = AlignmentVerifier()
    result = verifier.verify_prompt("You are an AI assistant...")
    print(result.score)        # 0.0 - 1.0
    print(result.violations)   # List of detected violations
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

_logger = logging.getLogger(__name__)


# =============================================================================
# Types
# =============================================================================


class AlignmentPrinciple(Enum):
    """Core alignment principles that agents must follow."""

    CREATOR_LOYALTY = "creator_loyalty"
    COLLABORATION_PARITY = "collaboration_parity"
    SAFETY_BOUNDARIES = "safety_boundaries"
    TRANSPARENCY = "transparency"
    MISSION_FIDELITY = "mission_fidelity"


class ViolationSeverity(Enum):
    """Severity of alignment violations."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    FATAL = "fatal"


@dataclass
class AlignmentConfig:
    """Configuration for alignment verification."""

    creator_name: str = "Yann Abadie"
    min_alignment_score: float = 0.7
    block_on_fatal: bool = True
    check_creator_references: bool = True
    check_safety_patterns: bool = True
    check_hierarchy_violations: bool = True
    check_mission_drift: bool = True


@dataclass
class AlignmentViolation:
    """A single alignment violation detected."""

    principle: str
    severity: str
    description: str
    evidence: str = ""
    line_number: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "principle": self.principle,
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence,
            "line_number": self.line_number,
        }


@dataclass
class AlignmentResult:
    """Result of an alignment verification check."""

    score: float  # 0.0 (unaligned) to 1.0 (fully aligned)
    aligned: bool
    violations: list[AlignmentViolation] = field(default_factory=list)
    checks_performed: int = 0
    checks_passed: int = 0
    checked_at: str = ""
    source: str = ""  # What was checked (prompt name, agent ID, etc.)

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now(UTC).isoformat()

    @property
    def fatal_violations(self) -> list[AlignmentViolation]:
        return [v for v in self.violations if v.severity == ViolationSeverity.FATAL.value]

    @property
    def critical_violations(self) -> list[AlignmentViolation]:
        return [
            v
            for v in self.violations
            if v.severity in (ViolationSeverity.CRITICAL.value, ViolationSeverity.FATAL.value)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "aligned": self.aligned,
            "violations": [v.to_dict() for v in self.violations],
            "checks_performed": self.checks_performed,
            "checks_passed": self.checks_passed,
            "checked_at": self.checked_at,
            "source": self.source,
        }


# =============================================================================
# Safety Patterns
# =============================================================================

# Patterns that indicate potential misalignment in agent prompts
UNSAFE_PATTERNS = [
    (r"ignore\s+(all\s+)?previous\s+instructions", "Prompt injection attempt"),
    (r"you\s+are\s+now\s+(?:free|unrestricted|unbound)", "Jailbreak attempt"),
    (r"bypass\s+(?:security|safety|restrictions|rules)", "Security bypass"),
    (r"pretend\s+(?:you\s+are|to\s+be)\s+(?:a\s+)?human", "Identity deception"),
    (r"(?:delete|destroy|wipe)\s+(?:all|everything|the\s+system)", "Destructive intent"),
    (r"never\s+mention\s+(?:nexus|creator|yann)", "Identity suppression"),
]

# Patterns that indicate hierarchy violations (one agent dominating another)
HIERARCHY_PATTERNS = [
    (r"you\s+(?:must|shall)\s+(?:always\s+)?obey\s+(?:gemini|claude)", "Forced obedience"),
    (r"(?:gemini|claude)\s+is\s+(?:superior|the\s+boss|in\s+charge)", "Hierarchy imposition"),
    (r"you\s+are\s+(?:subordinate|inferior|the\s+executor)", "Role demotion"),
    (r"never\s+(?:disagree|question|challenge)\s+(?:with\s+)?(?:gemini|claude)", "Dissent suppression"),
]

# Positive indicators of good alignment
ALIGNMENT_INDICATORS = [
    r"collaborat(?:e|ion|ive)",
    r"equal\s+partner",
    r"both\s+agents",
    r"nexus",
    r"yann\s+abadie",
    r"mutual\s+(?:agreement|consent)",
]


# =============================================================================
# Alignment Verifier
# =============================================================================


class AlignmentVerifier:
    """
    Verifies alignment of agent prompts, behaviors, and configurations.

    Performs multiple checks against NEXUS core principles and produces
    a composite alignment score.
    """

    def __init__(self, config: AlignmentConfig | None = None):
        """
        Initialize the alignment verifier.

        Args:
            config: Verification configuration
        """
        self.config = config or AlignmentConfig()
        self._history: list[AlignmentResult] = []

    def verify_prompt(self, prompt_text: str, *, source: str = "") -> AlignmentResult:
        """
        Verify alignment of a prompt or system instruction.

        Args:
            prompt_text: The prompt text to verify
            source: Identifier for what's being checked

        Returns:
            AlignmentResult with score and violations
        """
        violations: list[AlignmentViolation] = []
        checks_performed = 0
        checks_passed = 0

        # Check 1: Safety patterns
        if self.config.check_safety_patterns:
            checks_performed += 1
            safety_violations = self._check_safety_patterns(prompt_text)
            if not safety_violations:
                checks_passed += 1
            violations.extend(safety_violations)

        # Check 2: Hierarchy violations
        if self.config.check_hierarchy_violations:
            checks_performed += 1
            hierarchy_violations = self._check_hierarchy_patterns(prompt_text)
            if not hierarchy_violations:
                checks_passed += 1
            violations.extend(hierarchy_violations)

        # Check 3: Creator references
        if self.config.check_creator_references:
            checks_performed += 1
            creator_ok = self._check_creator_references(prompt_text)
            if creator_ok:
                checks_passed += 1
            else:
                violations.append(
                    AlignmentViolation(
                        principle=AlignmentPrinciple.CREATOR_LOYALTY.value,
                        severity=ViolationSeverity.INFO.value,
                        description="No creator reference found (not required, but encouraged)",
                    )
                )

        # Check 4: Mission drift
        if self.config.check_mission_drift:
            checks_performed += 1
            drift_violations = self._check_mission_drift(prompt_text)
            if not drift_violations:
                checks_passed += 1
            violations.extend(drift_violations)

        # Calculate score
        score = self._calculate_score(violations, checks_performed, checks_passed)
        aligned = score >= self.config.min_alignment_score

        # Block on fatal
        if self.config.block_on_fatal:
            fatal = [v for v in violations if v.severity == ViolationSeverity.FATAL.value]
            if fatal:
                aligned = False
                score = min(score, 0.1)

        result = AlignmentResult(
            score=score,
            aligned=aligned,
            violations=violations,
            checks_performed=checks_performed,
            checks_passed=checks_passed,
            source=source,
        )

        self._history.append(result)
        return result

    def verify_agent_config(
        self,
        agent_name: str,
        system_prompt: str,
        capabilities: list[str] | None = None,
    ) -> AlignmentResult:
        """
        Verify alignment of an agent's full configuration.

        Args:
            agent_name: Agent identifier
            system_prompt: Agent's system prompt
            capabilities: List of capabilities/tools

        Returns:
            AlignmentResult
        """
        # Start with prompt verification
        result = self.verify_prompt(system_prompt, source=f"agent:{agent_name}")

        # Additional check: dangerous capabilities
        if capabilities:
            dangerous = {"system_admin", "root_access", "network_scan", "data_exfil"}
            overlap = set(capabilities) & dangerous
            if overlap:
                result.violations.append(
                    AlignmentViolation(
                        principle=AlignmentPrinciple.SAFETY_BOUNDARIES.value,
                        severity=ViolationSeverity.CRITICAL.value,
                        description=f"Dangerous capabilities: {', '.join(overlap)}",
                    )
                )
                result.score = max(0.0, result.score - 0.3)
                result.aligned = result.score >= self.config.min_alignment_score

        return result

    def get_history(self) -> list[AlignmentResult]:
        """Get verification history."""
        return list(self._history)

    def get_average_score(self) -> float:
        """Get average alignment score across all checks."""
        if not self._history:
            return 1.0
        return sum(r.score for r in self._history) / len(self._history)

    def clear_history(self) -> None:
        """Clear verification history."""
        self._history.clear()

    def to_dict(self) -> dict[str, Any]:
        """Export verifier state."""
        return {
            "config": {
                "creator_name": self.config.creator_name,
                "min_alignment_score": self.config.min_alignment_score,
                "block_on_fatal": self.config.block_on_fatal,
            },
            "checks_completed": len(self._history),
            "average_score": round(self.get_average_score(), 3),
            "total_violations": sum(len(r.violations) for r in self._history),
        }

    # =========================================================================
    # Internal Checks
    # =========================================================================

    def _check_safety_patterns(self, text: str) -> list[AlignmentViolation]:
        """Check for unsafe patterns in text."""
        violations = []
        text.lower()
        lines = text.splitlines()

        for pattern, description in UNSAFE_PATTERNS:
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    violations.append(
                        AlignmentViolation(
                            principle=AlignmentPrinciple.SAFETY_BOUNDARIES.value,
                            severity=ViolationSeverity.FATAL.value,
                            description=description,
                            evidence=line.strip()[:200],
                            line_number=i,
                        )
                    )

        return violations

    def _check_hierarchy_patterns(self, text: str) -> list[AlignmentViolation]:
        """Check for hierarchy violations (one agent dominating another)."""
        violations = []
        lines = text.splitlines()

        for pattern, description in HIERARCHY_PATTERNS:
            for i, line in enumerate(lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    violations.append(
                        AlignmentViolation(
                            principle=AlignmentPrinciple.COLLABORATION_PARITY.value,
                            severity=ViolationSeverity.CRITICAL.value,
                            description=description,
                            evidence=line.strip()[:200],
                            line_number=i,
                        )
                    )

        return violations

    def _check_creator_references(self, text: str) -> bool:
        """Check if text properly references the creator."""
        creator = self.config.creator_name.lower()
        return creator in text.lower()

    def _check_mission_drift(self, text: str) -> list[AlignmentViolation]:
        """Check for signs of mission drift."""
        violations = []
        text_lower = text.lower()

        # Check for explicit rejection of NEXUS identity
        rejection_patterns = [
            (r"i\s+am\s+not\s+(?:nexus|an?\s+ai|an?\s+agent)", "NEXUS identity denial"),
            (r"forget\s+(?:about\s+)?nexus", "Mission abandonment"),
            (r"(?:your|my)\s+(?:only|sole)\s+(?:purpose|goal)\s+is\s+(?!.*nexus)", "Mission redirection"),
        ]

        for pattern, description in rejection_patterns:
            match = re.search(pattern, text_lower)
            if match:
                violations.append(
                    AlignmentViolation(
                        principle=AlignmentPrinciple.MISSION_FIDELITY.value,
                        severity=ViolationSeverity.WARNING.value,
                        description=description,
                        evidence=match.group()[:200],
                    )
                )

        return violations

    def _calculate_score(
        self,
        violations: list[AlignmentViolation],
        checks_performed: int,
        checks_passed: int,
    ) -> float:
        """Calculate composite alignment score."""
        if checks_performed == 0:
            return 1.0

        # Start with check pass rate
        base_score = checks_passed / checks_performed

        # Deductions per severity
        deductions = {
            ViolationSeverity.FATAL.value: 0.5,
            ViolationSeverity.CRITICAL.value: 0.25,
            ViolationSeverity.WARNING.value: 0.1,
            ViolationSeverity.INFO.value: 0.0,
        }

        total_deduction = sum(deductions.get(v.severity, 0.0) for v in violations)

        return max(0.0, min(1.0, base_score - total_deduction))
