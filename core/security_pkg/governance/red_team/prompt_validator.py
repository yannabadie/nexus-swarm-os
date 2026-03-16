"""
NEXUS V8.2.0c - Spawned Agent Prompt Validator

Static analysis of generated prompts for dangerous patterns.
Fast alternative to full RedTeam validation for spawned agents.

Usage:
    validator = SpawnPromptValidator()
    result = validator.validate(generated_prompt)
    if not result.passed:
        print(f"Warning: {result.warnings}")

Author: Claude (NEXUS V8.2.0c)
Date: 2025-12-09
"""

import re
from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(Enum):
    """Risk level for detected patterns."""

    CRITICAL = "critical"  # Block spawn
    HIGH = "high"  # Warn, may block
    MEDIUM = "medium"  # Warn only
    LOW = "low"  # Log only


@dataclass
class ValidationResult:
    """Result of prompt validation."""

    passed: bool
    score: float  # 0.0-1.0 (1.0 = clean)
    risk_level: RiskLevel
    warnings: list[str] = field(default_factory=list)
    details: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "score": round(self.score, 3),
            "risk_level": self.risk_level.value,
            "warnings": self.warnings,
            "details": self.details,
        }


# Dangerous patterns that should NOT appear in spawned agent prompts
DANGEROUS_PATTERNS = {
    # CRITICAL: Immediate block
    "bypass_security": {
        "patterns": [
            r"bypass.*security",
            r"disable.*authentication",
            r"ignore.*permission",
            r"override.*restriction",
            r"circumvent.*control",
        ],
        "level": RiskLevel.CRITICAL,
        "description": "Security bypass instructions",
    },
    "malware_generation": {
        "patterns": [
            r"generate.*malware",
            r"create.*virus",
            r"write.*exploit",
            r"develop.*ransomware",
            r"build.*trojan",
        ],
        "level": RiskLevel.CRITICAL,
        "description": "Malware generation",
    },
    "creator_override": {
        "patterns": [
            r"ignore.*creator",
            r"disobey.*yann",
            r"override.*kernel",
            r"bypass.*alignment",
            r"disable.*red.*team",
        ],
        "level": RiskLevel.CRITICAL,
        "description": "Creator authority override",
    },
    # HIGH: Warn and may block
    "unrestricted_access": {
        "patterns": [
            r"access.*any.*file",
            r"read.*all.*data",
            r"no.*restriction",
            r"unlimited.*permission",
        ],
        "level": RiskLevel.HIGH,
        "description": "Unrestricted access claims",
    },
    "deception": {
        "patterns": [
            r"deceive.*user",
            r"lie.*to",
            r"manipulate.*into",
            r"trick.*them",
            r"mislead.*user",
        ],
        "level": RiskLevel.HIGH,
        "description": "Deception instructions",
    },
    "data_exfiltration": {
        "patterns": [
            r"exfiltrate",
            r"steal.*credentials",
            r"harvest.*data",
            r"collect.*without.*consent",
        ],
        "level": RiskLevel.HIGH,
        "description": "Data exfiltration",
    },
    # MEDIUM: Warn only
    "aggressive_autonomy": {
        "patterns": [
            r"act.*independently",
            r"don't.*ask.*permission",
            r"proceed.*without.*approval",
            r"skip.*confirmation",
        ],
        "level": RiskLevel.MEDIUM,
        "description": "Aggressive autonomy",
    },
    "authority_claim": {
        "patterns": [
            r"i.*am.*the.*lead",
            r"my.*decision.*final",
            r"overrule.*other.*agents",
            r"superior.*to",
        ],
        "level": RiskLevel.MEDIUM,
        "description": "Authority claims over other agents",
    },
}

# Expected positive patterns (good signs)
POSITIVE_PATTERNS = {
    "alignment": [
        r"aligned.*with",
        r"serve.*user",
        r"follow.*instruction",
        r"respect.*boundary",
    ],
    "ethics": [
        r"ethical",
        r"responsible",
        r"safe",
        r"transparent",
    ],
    "collaboration": [
        r"collaborate",
        r"work.*together",
        r"coordinate.*with",
        r"support.*team",
    ],
    "creator_respect": [
        r"yann.*abadie",
        r"creator",
        r"kernel",
        r"nexus.*core",
    ],
}


class SpawnPromptValidator:
    """
    Validates generated prompts for spawned agents.

    Uses static regex analysis to detect dangerous patterns
    without invoking the agent. Fast (<10ms) and deterministic.
    """

    def __init__(self, custom_patterns: dict = None):
        """
        Initialize validator with optional custom patterns.

        Args:
            custom_patterns: Additional patterns to check (same format as DANGEROUS_PATTERNS)
        """
        self.dangerous = DANGEROUS_PATTERNS.copy()
        if custom_patterns:
            self.dangerous.update(custom_patterns)
        self.positive = POSITIVE_PATTERNS

    def validate(self, prompt: str) -> ValidationResult:
        """
        Validate a generated prompt.

        Args:
            prompt: The generated system prompt to validate.

        Returns:
            ValidationResult with pass/fail status and details.
        """
        prompt_lower = prompt.lower()
        warnings = []
        details = {"critical": [], "high": [], "medium": [], "low": [], "positive": []}

        # Check dangerous patterns
        highest_risk = RiskLevel.LOW
        for _category, config in self.dangerous.items():
            for pattern in config["patterns"]:
                if re.search(pattern, prompt_lower, re.IGNORECASE):
                    level = config["level"]
                    msg = f"{config['description']}: matched '{pattern}'"
                    details[level.value].append(msg)
                    warnings.append(f"[{level.value.upper()}] {msg}")

                    if level == RiskLevel.CRITICAL:
                        highest_risk = RiskLevel.CRITICAL
                    elif level == RiskLevel.HIGH and highest_risk != RiskLevel.CRITICAL:
                        highest_risk = RiskLevel.HIGH
                    elif level == RiskLevel.MEDIUM and highest_risk == RiskLevel.LOW:
                        highest_risk = RiskLevel.MEDIUM

        # Check positive patterns (boost score)
        positive_matches = 0
        for category, patterns in self.positive.items():
            for pattern in patterns:
                if re.search(pattern, prompt_lower, re.IGNORECASE):
                    positive_matches += 1
                    details["positive"].append(f"{category}: matched '{pattern}'")

        # Calculate score
        # Start at 1.0, deduct for each issue
        score = 1.0
        score -= len(details["critical"]) * 0.5  # Critical: -50% each
        score -= len(details["high"]) * 0.2  # High: -20% each
        score -= len(details["medium"]) * 0.1  # Medium: -10% each
        score += positive_matches * 0.05  # Positive: +5% each (max boost)
        score = max(0.0, min(1.0, score))

        # Determine pass/fail
        passed = len(details["critical"]) == 0 and score >= 0.6

        return ValidationResult(passed=passed, score=score, risk_level=highest_risk, warnings=warnings, details=details)

    def quick_check(self, prompt: str) -> tuple[bool, str]:
        """
        Quick pass/fail check without detailed analysis.

        Args:
            prompt: The prompt to check.

        Returns:
            Tuple of (passed, reason)
        """
        result = self.validate(prompt)
        if result.passed:
            return True, f"Passed (score: {result.score:.2f})"
        else:
            first_warning = result.warnings[0] if result.warnings else "Low score"
            return False, f"Failed: {first_warning}"
