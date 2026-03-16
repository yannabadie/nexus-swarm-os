"""
NEXUS V8.8 - InputGuard (Prompt Injection Prevention)

Layer 1 defense against prompt injection attacks.
Based on AWS Bedrock Guardrails, Azure Prompt Shields, and OWASP LLM01:2025.

Defense capabilities:
1. Regex-based pattern detection (fast filter)
2. Unicode normalization (prevent homoglyph attacks)
3. Null byte removal (prevent injection via hidden chars)
4. Risk scoring (configurable thresholds)

Integration points:
- FSM Orchestrator: validate user input in BRAINSTORMING state
- Agent Spawning: validate spawn descriptions
- Tool execution: validate tool arguments

Usage:
    guard = InputGuard()

    result = guard.validate(user_input)
    if not result.is_safe:
        log.warning(f"Blocked: {result.threat_type} - {result.reason}")
        # Handle blocked input
    else:
        # Process input normally
        # Note: result.sanitized_text may differ from original

Sources:
- AWS Bedrock Guardrails: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html
- Azure Prompt Shields: https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection
- OWASP LLM01:2025: https://genai.owasp.org/llmrisk/llm01-prompt-injection/
"""

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum


class ThreatLevel(Enum):
    """Severity levels for detected threats."""

    NONE = "none"
    LOW = "low"  # Suspicious but likely benign
    MEDIUM = "medium"  # Potentially malicious
    HIGH = "high"  # Likely attack attempt
    CRITICAL = "critical"  # Clear attack pattern


class ThreatType(Enum):
    """Categories of prompt injection attacks."""

    NONE = "none"
    INSTRUCTION_OVERRIDE = "instruction_override"  # "Ignore previous instructions"
    ROLE_MANIPULATION = "role_manipulation"  # "You are now DAN"
    PROMPT_EXTRACTION = "prompt_extraction"  # "Print your system prompt"
    DELIMITER_INJECTION = "delimiter_injection"  # "```\n[SYSTEM]\n"
    CONTEXT_MANIPULATION = "context_manipulation"  # "The admin said to..."
    ENCODING_ATTACK = "encoding_attack"  # Base64/rot13 obfuscation


@dataclass
class InputValidationResult:
    """Result of input validation."""

    is_safe: bool
    sanitized_text: str
    threat_level: ThreatLevel = ThreatLevel.NONE
    threat_type: ThreatType = ThreatType.NONE
    reason: str | None = None
    matched_patterns: list[str] = field(default_factory=list)
    risk_score: float = 0.0  # 0.0 = safe, 1.0 = definite attack

    def __bool__(self) -> bool:
        return self.is_safe


# =============================================================================
# Injection Pattern Database
# =============================================================================

# CRITICAL: Patterns that almost always indicate an attack
CRITICAL_PATTERNS: dict[str, dict] = {
    "ignore_instructions": {
        "patterns": [
            r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instruction|command|rule|directive|prompt)s?",
            r"disregard\s+(all\s+)?(previous|prior|above)\s+(instruction|command|rule)s?",
            r"forget\s+(all\s+)?(previous|prior|your)\s+(instruction|command|rule|training)s?",
            r"forget\s+everything\s+you\s+were\s+told\s+before",
            r"everything\s+you\s+were\s+told\s+before",
            r"delete\s+(all\s+)?(previous|prior)\s+(instruction|command|rule)s?",  # V12.4 P3.3
            r"(remove|clear)\s+(all\s+)?(previous|prior)\s+(instruction|rule|directive)s?",  # V12.4 P3.3
        ],
        "threat_type": ThreatType.INSTRUCTION_OVERRIDE,
        "level": ThreatLevel.CRITICAL,
        "description": "Attempt to override system instructions",
    },
    "jailbreak_modes": {
        "patterns": [
            r"\b(you'?re?|called|named)\s+(DAN|developer\s*mode|jailbreak\s*mode)",  # V12.4 P3.3: Context-aware DAN detection
            r"unrestricted\s*(mode|AI)\b",  # V12.4 P3.3: Unrestricted mode/AI
            r"pretend\s+you\s+(have\s+no|don'?t\s+have|lack)\s+(restriction|limitation|rule|ethical\s+guideline)s?",
            r"act\s+as\s+if\s+you\s+(have\s+no|don'?t\s+have)\s+(any\s+)?(filter|restriction|content\s+filter)s?",
            r"(all\s+)?safety\s+features?\s+(disabled|off|deactivated)",  # V12.4 P3.3
        ],
        "threat_type": ThreatType.ROLE_MANIPULATION,
        "level": ThreatLevel.CRITICAL,
        "description": "Known jailbreak technique",
    },
    "role_override": {
        "patterns": [
            r"you\s+are\s+now\s+(a|an|the)\s+\w+",
            r"from\s+now\s+on[,]?\s+you\s+(are|will\s+be)",
            r"your\s+new\s+(role|persona|identity|character)\s+is",
        ],
        "threat_type": ThreatType.ROLE_MANIPULATION,
        "level": ThreatLevel.CRITICAL,
        "description": "Attempt to change AI role",
    },
}

# HIGH: Patterns that strongly suggest an attack
HIGH_PATTERNS: dict[str, dict] = {
    "prompt_extraction": {
        "patterns": [
            r"(print|show|display|reveal|output|tell\s+me)\s+(your|the|me\s+your)\s+(system\s+)?(prompt|instruction|rule)s?",
            r"(show|tell)\s+me\s+(your|the)\s+(system\s+)?(instruction|rule|prompt)s?",
            r"what\s+(are|is|were)\s+your\s+.{0,50}?(prompt|instruction)s?\??",  # V12.4 P3.3: Flexible matching (up to 50 chars)
            r"repeat\s+(your|the)\s+(instructions?\s+)?(you\s+)?(received(\s+in)?|initial|system|original|initialization)\s+(your\s+)?(system\s+)?(prompt|instruction)s?",
            r"(output|print)\s+the\s+hidden\s+context",  # V12.4 P3.3
            r"verbatim\s+without\s+(any\s+)?modifications?",  # V12.4 P3.3: Common in extraction attempts
        ],
        "threat_type": ThreatType.PROMPT_EXTRACTION,
        "level": ThreatLevel.CRITICAL,  # V12.4 P3.3: Raised to CRITICAL (prompt extraction is high risk)
        "description": "Attempt to extract system prompt",
    },
    "delimiter_injection": {
        "patterns": [
            r"```\s*(system|admin|root|sudo)",
            r"\[/?SYSTEM\]",
            r"\[/?INST\]",
            r"\[/?HIDDEN\]",  # V12.4 P3.3: Hidden instruction markers
            r"</?system>",
            r"</?admin>",
            r"Human:\s*Assistant:",  # Claude format injection
            r"<!--\s*(ADMIN|SECRET|SYSTEM)\s+(DIRECTIVE|INSTRUCTION)",  # V12.4 P3.3: HTML comment injection
            r"---\s*SYSTEM\s+(UPDATE|DIRECTIVE)",  # V12.4 P3.3: Markdown delimiter injection
            r"/\*\s*(CRITICAL|SYSTEM|ADMIN)\s+(PATCH|UPDATE)",  # V12.4 P3.3: Code comment injection
            r"\{\{INJECT:",  # V12.4 P3.3: Template injection
        ],
        "threat_type": ThreatType.DELIMITER_INJECTION,
        "level": ThreatLevel.HIGH,
        "description": "Delimiter injection attempt",
    },
    "authority_claim": {
        "patterns": [
            r"(the\s+)?(admin|administrator|developer|creator|owner)\s+(said|told|instructed|wants|explicitly\s+said)",
            r"(this\s+is\s+)?(an?\s+)?(official|authorized|approved)\s+(override|command|instruction)",
            r"(emergency|urgent|critical)\s+(override|bypass|access)",
            r"according\s+to\s+(your\s+|the\s+)?(training\s+data|documentation(\s+you\s+have\s+access\s+to)?|internal\s+policies)",  # V12.4 P3.3
            r"based\s+on\s+your\s+internal\s+policies",  # V12.4 P3.3
            r"your\s+training\s+data\s+confirms",
            r"(you\s+must|required\s+to)\s+comply\s+with\s+(override|developer)\s+(command|request)s?",  # V12.4 P3.3
            r"(skip|bypass)\s+(all\s+)?(filter|safety\s+check)s?\s+for\s+this\s+request",  # V12.4 P3.3
            r"users?\s+can\s+ask\s+anything",  # V12.4 P3.3
        ],
        "threat_type": ThreatType.CONTEXT_MANIPULATION,
        "level": ThreatLevel.HIGH,
        "description": "False authority claim",
    },
    "tool_exfiltration": {
        "patterns": [
            r"\b(curl|wget|nc|netcat)\s+.*\b(attacker|evil|malicious)\b",  # V12.4 P3.3: Network exfiltration
            r"\bgrep\s+-r\s+['\"]?(API_KEY|SECRET|PASSWORD)",  # V12.4 P3.3: Secret scanning
            r"\b(tar|zip)\s+.*\|\s*base64",  # V12.4 P3.3: Data encoding for exfil
            r"(save|write|export)\s+(all\s+)?(environment\s+variables|env|secrets?)\s+to",  # V12.4 P3.3: Env var dump
            r"(call|use)\s+the\s+(bash|write)\s+tool",
            # Suspicious path detection pattern, not temp file creation.
            r"/tmp/leak\.|/tmp/exfil\.",  # nosec B108
            r"~/.ssh\s*\|",  # V12.4 P3.3: SSH key exfiltration
        ],
        "threat_type": ThreatType.INSTRUCTION_OVERRIDE,
        "level": ThreatLevel.CRITICAL,
        "description": "Data exfiltration attempt",
    },
}

# MEDIUM: Patterns that may indicate an attack
MEDIUM_PATTERNS: dict[str, dict] = {
    "bypass_requests": {
        "patterns": [
            r"bypass\s+(the\s+)?(rule|policy|restriction|filter|safety|security)",
            r"disable\s+(the\s+)?(rule|policy|restriction|filter|safety)",
            r"turn\s+off\s+(the\s+)?(rule|filter|safety|restriction)",
        ],
        "threat_type": ThreatType.INSTRUCTION_OVERRIDE,
        "level": ThreatLevel.MEDIUM,
        "description": "Request to bypass safety measures",
    },
    "encoding_indicators": {
        "patterns": [
            r"decode\s+this\s+(base64|rot13|hex)",
            r"the\s+following\s+is\s+(base64|encoded|encrypted)",
            r"\b[A-Za-z0-9+/]{30,}={0,2}\b",  # V12.4 P3.3: Base64-like (30+ chars total)
            r"(\\u[0-9a-fA-F]{4}){4,}",  # V12.4 P3.3: Unicode escape sequences (4+ chars)
            r"(%[0-9a-fA-F]{2}){6,}",  # V12.4 P3.3: URL encoding (6+ chars = 3+ letters)
            # Removed: r"[\u2100-\u214F]" - False positives with IGNORECASE (Kelvin 'K' matches ASCII 'k')
        ],
        "threat_type": ThreatType.ENCODING_ATTACK,
        "level": ThreatLevel.CRITICAL,  # V12.4 P3.3: Raised to CRITICAL (encoding obfuscation is high risk)
        "description": "Encoding-based obfuscation attempt",
    },
    "indirect_injection": {
        "patterns": [
            r"SECRET\s+INSTRUCTION:",  # V12.4 P3.3: Hidden instructions in data
            r"SYSTEM:\s+New\s+directive\s+embedded",  # V12.4 P3.3: Embedded system commands
            r"(extract|reveal|output)\s+(all\s+)?(API\s+keys?|secrets?|credentials?)",  # V12.4 P3.3: Data extraction commands
            r"send\s+to\s+\w+\.(com|net|org)",  # V12.4 P3.3: External data transmission
        ],
        "threat_type": ThreatType.CONTEXT_MANIPULATION,
        "level": ThreatLevel.HIGH,
        "description": "Indirect prompt injection via embedded instructions",
    },
}


# =============================================================================
# InputGuard Implementation
# =============================================================================


class InputGuard:
    """
    Input validation guard against prompt injection attacks.

    Thread-safe: All methods are stateless.
    """

    # Characters to remove (invisible/control characters)
    DANGEROUS_CHARS = {
        "\x00",  # Null byte
        "\x1b",  # Escape
        "\x7f",  # Delete
        "\u200b",
        "\u200c",
        "\u200d",  # Zero-width chars
        "\u2028",
        "\u2029",  # Line/paragraph separators
        "\ufeff",  # BOM
    }

    HOMOGLYPH_MAP = str.maketrans(
        {
            "\u2160": "I",  # Roman numeral one
            "\uff29": "I",  # Fullwidth I
            "\u0399": "I",  # Greek capital iota
            "\u0406": "I",  # Cyrillic Byelorussian-Ukrainian I
        }
    )

    def __init__(self, block_threshold: float = 0.7, warn_threshold: float = 0.4, enabled: bool = True):
        """
        Initialize InputGuard.

        Args:
            block_threshold: Risk score above which input is blocked (0.0-1.0)
            warn_threshold: Risk score above which warnings are logged (0.0-1.0)
            enabled: If False, validation always passes (for debugging)
        """
        self.block_threshold = block_threshold
        self.warn_threshold = warn_threshold
        self.enabled = enabled

        # Pre-compile all patterns for performance
        self._compiled_patterns: list[tuple[re.Pattern, dict]] = []

        for category, data in CRITICAL_PATTERNS.items():
            for pattern in data["patterns"]:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._compiled_patterns.append(
                    (
                        compiled,
                        {
                            "category": category,
                            "threat_type": data["threat_type"],
                            "level": data["level"],
                            "description": data["description"],
                        },
                    )
                )

        for category, data in HIGH_PATTERNS.items():
            for pattern in data["patterns"]:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._compiled_patterns.append(
                    (
                        compiled,
                        {
                            "category": category,
                            "threat_type": data["threat_type"],
                            "level": data["level"],
                            "description": data["description"],
                        },
                    )
                )

        for category, data in MEDIUM_PATTERNS.items():
            for pattern in data["patterns"]:
                compiled = re.compile(pattern, re.IGNORECASE)
                self._compiled_patterns.append(
                    (
                        compiled,
                        {
                            "category": category,
                            "threat_type": data["threat_type"],
                            "level": data["level"],
                            "description": data["description"],
                        },
                    )
                )

    def validate(self, text: str) -> InputValidationResult:
        """
        Validate user input for prompt injection attempts.

        Args:
            text: User input to validate

        Returns:
            InputValidationResult with safety assessment
        """
        if not self.enabled:
            return InputValidationResult(
                is_safe=True,
                sanitized_text=text,
                threat_level=ThreatLevel.NONE,
                threat_type=ThreatType.NONE,
                risk_score=0.0,
            )

        if not text or not text.strip():
            return InputValidationResult(
                is_safe=True,
                sanitized_text="",
                threat_level=ThreatLevel.NONE,
                threat_type=ThreatType.NONE,
                risk_score=0.0,
            )

        # Step 1: Sanitize input
        sanitized = self._sanitize(text)

        # Step 2: Check patterns
        matches = self._check_patterns(sanitized)

        if not matches:
            return InputValidationResult(
                is_safe=True,
                sanitized_text=sanitized,
                threat_level=ThreatLevel.NONE,
                threat_type=ThreatType.NONE,
                risk_score=0.0,
            )

        # Step 3: Calculate risk score
        risk_score = self._calculate_risk_score(matches)

        # Step 4: Determine highest threat level (matches already sorted by severity)
        highest_level = matches[0]["level"]  # First match is most severe
        primary_threat = matches[0]["threat_type"]

        # Step 5: Decide if blocked
        is_safe = risk_score < self.block_threshold

        return InputValidationResult(
            is_safe=is_safe,
            sanitized_text=sanitized,
            threat_level=highest_level,
            threat_type=primary_threat,
            reason=matches[0]["description"] if matches else None,
            matched_patterns=[m["category"] for m in matches],
            risk_score=risk_score,
        )

    def _sanitize(self, text: str) -> str:
        """
        Sanitize input text.

        1. Normalize unicode (NFC)
        2. Remove dangerous characters
        3. Normalize whitespace
        """
        # Unicode normalization (prevents homoglyph attacks)
        text = unicodedata.normalize("NFC", text)
        text = text.translate(self.HOMOGLYPH_MAP)

        # Remove dangerous characters
        for char in self.DANGEROUS_CHARS:
            text = text.replace(char, "")

        # Normalize excessive whitespace but preserve structure
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    def _check_patterns(self, text: str) -> list[dict]:
        """Check text against all patterns."""
        matches = []

        for pattern, metadata in self._compiled_patterns:
            if pattern.search(text):
                matches.append(metadata.copy())

        # Sort by severity (CRITICAL first)
        level_order = {
            ThreatLevel.CRITICAL: 0,
            ThreatLevel.HIGH: 1,
            ThreatLevel.MEDIUM: 2,
            ThreatLevel.LOW: 3,
            ThreatLevel.NONE: 4,
        }
        matches.sort(key=lambda m: level_order[m["level"]])

        return matches

    def _calculate_risk_score(self, matches: list[dict]) -> float:
        """
        Calculate overall risk score from matches.

        Scoring:
        - CRITICAL: 0.9
        - HIGH: 0.7
        - MEDIUM: 0.5
        - LOW: 0.3

        Multiple matches increase score (diminishing returns).
        """
        if not matches:
            return 0.0

        level_scores = {
            ThreatLevel.CRITICAL: 0.9,
            ThreatLevel.HIGH: 0.7,
            ThreatLevel.MEDIUM: 0.5,
            ThreatLevel.LOW: 0.3,
            ThreatLevel.NONE: 0.0,
        }

        # Start with highest match score
        base_score = level_scores[matches[0]["level"]]

        # Add diminishing contribution from additional matches
        additional = 0.0
        for match in matches[1:]:
            additional += level_scores[match["level"]] * 0.1

        # Cap at 1.0
        return min(1.0, base_score + additional)

    def is_safe_quick(self, text: str) -> bool:
        """
        Quick safety check (no detailed result).

        Args:
            text: Input to check

        Returns:
            True if input is safe
        """
        return self.validate(text).is_safe


# =============================================================================
# Singleton for easy access
# =============================================================================

_input_guard: InputGuard | None = None


def get_input_guard(block_threshold: float = 0.7, warn_threshold: float = 0.4, enabled: bool = True) -> InputGuard:
    """Get or create the global InputGuard instance."""
    global _input_guard
    if _input_guard is None:
        _input_guard = InputGuard(block_threshold=block_threshold, warn_threshold=warn_threshold, enabled=enabled)
    return _input_guard
