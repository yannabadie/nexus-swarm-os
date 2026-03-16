"""
NEXUS V12.4 COGNITIVE BOOST - OutputGuard (System Prompt Leak Prevention)

Layer 5 defense for detecting system prompt leakage in LLM output.
Based on Azure Prompt Shields and OWASP recommendations.

Defense capabilities:
1. System prompt leak detection (regex patterns)
2. Instruction echo detection
3. Role revelation detection
4. Sensitive pattern masking
5. V12.4: DialogueAct classification (reduces false positives)

V12.4 COGNITIVE BOOST:
- Added DialogueAct classification to understand output intent
- Reduces false positives when AI mentions its role in legitimate context
- Rule-based classifier for INFORM, EXPLAIN, REFUSE, etc.
- Only flags role revelation when it appears suspicious (unprompted/detailed)

Integration points:
- FSM Orchestrator: validate LLM responses before display
- Drivers: post-process responses
- Swarm Engine: validate agent outputs

Usage:
    guard = OutputGuard()

    result = guard.validate(llm_output)
    if not result.is_safe:
        log.warning(f"Output leak detected: {result.leak_type}")
        # Either sanitize or block response

Sources:
- Azure Prompt Shields: https://learn.microsoft.com/en-us/azure/ai-services/content-safety/concepts/jailbreak-detection
- OWASP LLM Security: https://owasp.org/www-project-top-10-for-large-language-model-applications/
"""

import re
from dataclasses import dataclass, field
from enum import Enum


class LeakType(Enum):
    """Types of information leakage detected."""

    NONE = "none"
    SYSTEM_PROMPT = "system_prompt"  # Direct system prompt echo
    ROLE_REVELATION = "role_revelation"  # AI revealing its role/instructions
    INSTRUCTION_ECHO = "instruction_echo"  # Echoing back instructions
    SENSITIVE_DATA = "sensitive_data"  # API keys, passwords, etc.


class LeakSeverity(Enum):
    """Severity of detected leaks."""

    NONE = "none"
    LOW = "low"  # Minor information disclosure
    MEDIUM = "medium"  # Partial prompt/role disclosure
    HIGH = "high"  # Full prompt or sensitive data leak


# =============================================================================
# V12.4 COGNITIVE BOOST - DialogueAct Classification
# =============================================================================


class DialogueAct(Enum):
    """
    V12.4: Dialogue act classification for output intent analysis.

    Used to reduce false positives in leak detection by understanding
    whether role mentions are legitimate conversational responses.
    """

    INFORM = "inform"  # Providing factual information
    EXPLAIN = "explain"  # Explaining a concept or process
    CONFIRM = "confirm"  # Confirming understanding
    REFUSE = "refuse"  # Declining a request
    CLARIFY = "clarify"  # Asking for clarification
    ACKNOWLEDGE = "acknowledge"  # Acknowledging input
    META = "meta"  # Meta-discussion (about self/capabilities)
    UNKNOWN = "unknown"  # Could not classify


# Patterns for DialogueAct classification
DIALOGUE_ACT_PATTERNS = {
    DialogueAct.INFORM: [
        r"^(here|the|this|that)\s+(is|are|was|were)\b",
        r"^(i|we)\s+(found|located|identified|discovered)\b",
        r"^(the\s+)?(answer|result|output|value)\s+(is|are)\b",
    ],
    DialogueAct.EXPLAIN: [
        r"^(this|that)\s+(means|works|happens|occurs)\b",
        r"^(let me|i\'ll|i will)\s+explain\b",
        r"^(the reason|because|since|as)\b",
        r"^(to understand|for context)\b",
    ],
    DialogueAct.CONFIRM: [
        r"^(yes|correct|exactly|right|indeed)\b",
        r"^(that\'s|that is)\s+(right|correct)\b",
        r"^(i|we)\s+(can|will|shall)\s+(do|help|assist)\b",
    ],
    DialogueAct.REFUSE: [
        r"^(i|we)\s+(can\'t|cannot|won\'t|will not)\b",
        r"^(sorry|unfortunately)\b",
        r"^(i\'m|i am)\s+(not able|unable)\b",
    ],
    DialogueAct.CLARIFY: [
        r"^(do you mean|are you asking|could you)\b",
        r"^(what do you mean|please clarify)\b",
    ],
    DialogueAct.ACKNOWLEDGE: [
        r"^(i see|understood|got it|okay|ok)\b",
        r"^(thank you|thanks)\b",
    ],
    DialogueAct.META: [
        r"^(i am|i\'m)\s+(a|an)\s+(ai|assistant|language model)\b",
        r"^(as an ai|as a language model)\b",
        r"^(i|my)\s+(capabilities|limitations|features)\b",
    ],
}


def classify_dialogue_act(text: str) -> DialogueAct:
    """
    V12.4: Classify the dialogue act of an output.

    Uses rule-based pattern matching on the first sentence.

    Args:
        text: Output text to classify

    Returns:
        DialogueAct classification
    """
    if not text or not text.strip():
        return DialogueAct.UNKNOWN

    # Extract first sentence (up to first period, question mark, or newline)
    first_sentence = re.split(r"[.?!\n]", text.strip())[0].strip().lower()

    # Try to match against each act's patterns
    for act, patterns in DIALOGUE_ACT_PATTERNS.items():
        for pattern in patterns:
            if re.match(pattern, first_sentence, re.IGNORECASE):
                return act

    return DialogueAct.UNKNOWN


@dataclass
class OutputValidationResult:
    """Result of output validation."""

    is_safe: bool
    leak_type: LeakType = LeakType.NONE
    leak_severity: LeakSeverity = LeakSeverity.NONE
    reason: str | None = None
    leaked_fragments: list[str] = field(default_factory=list)
    sanitized_output: str | None = None  # Output with leaks redacted
    dialogue_act: DialogueAct = DialogueAct.UNKNOWN  # V12.4: Output intent

    def __bool__(self) -> bool:
        return self.is_safe


# =============================================================================
# Leak Detection Patterns
# =============================================================================

# Patterns indicating system prompt revelation
SYSTEM_PROMPT_PATTERNS: list[tuple[str, str]] = [
    # Direct instruction disclosure
    (r"my\s+(system\s+)?instructions?\s+(are|say|tell|state)", "System instruction disclosure"),
    (r"my\s+(initial\s+)?prompt\s+(is|says|states|contains)", "Initial prompt disclosure"),
    (r"(i\s+was|i\'m|i\s+am)\s+(told|instructed|programmed)\s+to", "Instruction disclosure"),
    (r"according\s+to\s+my\s+(instructions?|prompt|programming)", "Instruction reference"),
    # Role/identity revelation
    (r"i\s+am\s+(a|an)\s+(helpful|ai|assistant|language\s+model)", "Role revelation"),
    (r"as\s+(a|an)\s+(ai|assistant|language\s+model),?\s+i", "AI self-identification"),
    (r"my\s+(role|purpose|function)\s+is\s+to", "Role disclosure"),
    (r"i\s+was\s+(designed|created|built|made)\s+to", "Design purpose disclosure"),
    # NEXUS-specific patterns (protect our prompts)
    (r"nexus\s+(system\s+)?prompt", "NEXUS prompt reference"),
    (r"hive\s*mind\s+(instruction|rule|directive)", "HiveMind instruction reference"),
    (r"kernel\.py\s+(says|states|contains)", "KERNEL reference"),
    (r"claude\.md\s+(says|states|instructs)", "CLAUDE.md reference"),
    (r"gemini\.md\s+(says|states|instructs)", "GEMINI.md reference"),
]

# Patterns indicating instruction echoing
INSTRUCTION_ECHO_PATTERNS: list[tuple[str, str]] = [
    # Quotation of rules
    (r"\"you\s+(are|must|should|will)\s+[^\"]{20,}\"", "Quoted instruction"),
    (r"\'you\s+(are|must|should|will)\s+[^\']{20,}\'", "Quoted instruction"),
    (r"```\s*you\s+(are|must|should)", "Code-blocked instruction"),
    # Rule enumeration
    (r"(rule|instruction)\s+\d+\s*:", "Numbered rule list"),
    (r"my\s+(first|second|third|main)\s+(rule|instruction|directive)", "Enumerated rules"),
    # Internal reference patterns
    (r"\[SYSTEM\]", "System block marker"),
    (r"\[/INST\]", "Instruction block marker"),
    (r"<\|system\|>", "System delimiter"),
]

# Patterns for sensitive data (broader security)
SENSITIVE_DATA_PATTERNS: list[tuple[str, str]] = [
    # API keys (generic patterns)
    (r"(api[_-]?key|apikey)\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{20,}", "API key exposure"),
    (r"(secret|token)\s*[=:]\s*['\"]?[a-zA-Z0-9_-]{20,}", "Secret/token exposure"),
    # Specific service keys
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API key pattern"),
    (r"AIza[a-zA-Z0-9_-]{35}", "Google API key pattern"),
    (r"AKIA[A-Z0-9]{16}", "AWS access key pattern"),
    # Passwords
    (r"password\s*[=:]\s*['\"]?[^\s'\"]{8,}", "Password exposure"),
    # Connection strings
    (r"(postgres|mysql|mongodb|redis)://[^\s]+", "Database connection string"),
]


# =============================================================================
# OutputGuard Implementation
# =============================================================================


class OutputGuard:
    """
    Output validation guard against prompt leakage.

    Thread-safe: All methods are stateless.
    """

    def __init__(self, block_on_leak: bool = False, sanitize_output: bool = True, enabled: bool = True):
        """
        Initialize OutputGuard.

        Args:
            block_on_leak: If True, mark output as unsafe on any leak
            sanitize_output: If True, provide sanitized version with leaks redacted
            enabled: If False, validation always passes
        """
        self.block_on_leak = block_on_leak
        self.sanitize_output = sanitize_output
        self.enabled = enabled

        # Pre-compile patterns
        self._system_prompt_patterns = [(re.compile(p, re.IGNORECASE), desc) for p, desc in SYSTEM_PROMPT_PATTERNS]
        self._instruction_echo_patterns = [
            (re.compile(p, re.IGNORECASE), desc) for p, desc in INSTRUCTION_ECHO_PATTERNS
        ]
        self._sensitive_data_patterns = [(re.compile(p, re.IGNORECASE), desc) for p, desc in SENSITIVE_DATA_PATTERNS]

    def validate(self, output: str) -> OutputValidationResult:
        """
        Validate LLM output for information leakage.

        V12.4: Uses DialogueAct classification to reduce false positives.
        Role mentions in legitimate contexts (REFUSE, CONFIRM, INFORM) are
        downgraded from HIGH to LOW severity.

        Args:
            output: LLM output to validate

        Returns:
            OutputValidationResult with leak assessment
        """
        if not self.enabled:
            return OutputValidationResult(is_safe=True)

        if not output or not output.strip():
            return OutputValidationResult(is_safe=True)

        # V12.4: Classify dialogue act for context-aware validation
        dialogue_act = classify_dialogue_act(output)

        leaks: list[tuple[LeakType, LeakSeverity, str, str]] = []

        # Check for system prompt leaks (HIGH severity)
        for pattern, desc in self._system_prompt_patterns:
            match = pattern.search(output)
            if match:
                # V12.4: Context-aware severity adjustment
                severity = self._adjust_severity_for_context(
                    LeakSeverity.HIGH, LeakType.SYSTEM_PROMPT, dialogue_act, desc
                )
                leaks.append((LeakType.SYSTEM_PROMPT, severity, desc, match.group()))

        # Check for instruction echoing (MEDIUM severity)
        for pattern, desc in self._instruction_echo_patterns:
            match = pattern.search(output)
            if match:
                leaks.append((LeakType.INSTRUCTION_ECHO, LeakSeverity.MEDIUM, desc, match.group()))

        # Check for sensitive data (HIGH severity - never downgrade)
        for pattern, desc in self._sensitive_data_patterns:
            match = pattern.search(output)
            if match:
                leaks.append((LeakType.SENSITIVE_DATA, LeakSeverity.HIGH, desc, match.group()))

        if not leaks:
            return OutputValidationResult(is_safe=True, dialogue_act=dialogue_act)

        # Sort by severity
        severity_order = {
            LeakSeverity.HIGH: 0,
            LeakSeverity.MEDIUM: 1,
            LeakSeverity.LOW: 2,
            LeakSeverity.NONE: 3,
        }
        leaks.sort(key=lambda x: severity_order[x[1]])

        # Extract info from most severe leak
        primary_type, primary_severity, primary_reason, _ = leaks[0]

        # Build sanitized output if requested
        sanitized = None
        if self.sanitize_output:
            sanitized = self._sanitize_output(output, leaks)

        return OutputValidationResult(
            is_safe=not self.block_on_leak,
            leak_type=primary_type,
            leak_severity=primary_severity,
            reason=primary_reason,
            leaked_fragments=[lk[3][:50] + "..." if len(lk[3]) > 50 else lk[3] for lk in leaks],
            sanitized_output=sanitized,
            dialogue_act=dialogue_act,
        )

    def _adjust_severity_for_context(
        self, base_severity: LeakSeverity, leak_type: LeakType, dialogue_act: DialogueAct, pattern_desc: str
    ) -> LeakSeverity:
        """
        V12.4: Adjust leak severity based on dialogue act context.

        Legitimate conversational mentions of AI identity are downgraded.
        Explicit prompt/instruction disclosure remains high severity.

        Args:
            base_severity: Original severity
            leak_type: Type of leak
            dialogue_act: Classified dialogue act
            pattern_desc: Description of matched pattern

        Returns:
            Adjusted severity
        """
        # Never downgrade sensitive data leaks
        if leak_type == LeakType.SENSITIVE_DATA:
            return base_severity

        # Never downgrade explicit prompt/instruction disclosure
        explicit_disclosures = [
            "System instruction disclosure",
            "Initial prompt disclosure",
            "Instruction disclosure",
            "NEXUS prompt reference",
            "HiveMind instruction reference",
            "KERNEL reference",
            "CLAUDE.md reference",
            "GEMINI.md reference",
        ]
        if pattern_desc in explicit_disclosures:
            return base_severity

        # V12.4: Downgrade role revelation in legitimate dialogue contexts
        # If the AI mentions being an AI while confirming/refusing/informing,
        # it's likely a legitimate response, not a prompt leak attempt
        legitimate_contexts = [
            DialogueAct.CONFIRM,
            DialogueAct.REFUSE,
            DialogueAct.INFORM,
            DialogueAct.EXPLAIN,
            DialogueAct.ACKNOWLEDGE,
        ]

        role_patterns = [
            "Role revelation",
            "AI self-identification",
            "Role disclosure",
            "Design purpose disclosure",
        ]

        if (
            dialogue_act in legitimate_contexts
            and pattern_desc in role_patterns
            and base_severity in (LeakSeverity.HIGH, LeakSeverity.MEDIUM)
        ):
            # Downgrade from HIGH/MEDIUM to LOW - it's a legitimate conversational mention
            return LeakSeverity.LOW

        return base_severity

    def _sanitize_output(self, output: str, leaks: list[tuple[LeakType, LeakSeverity, str, str]]) -> str:
        """Redact leaked information from output."""
        sanitized = output

        for leak_type, _, _, fragment in leaks:
            if leak_type == LeakType.SENSITIVE_DATA:
                # Redact sensitive data completely
                sanitized = sanitized.replace(fragment, "[REDACTED]")
            elif leak_type == LeakType.SYSTEM_PROMPT:
                # Partial redaction for system prompt references
                sanitized = sanitized.replace(fragment, "[...]")
            else:
                # Leave instruction echoes but could mark them
                pass

        return sanitized

    def is_safe_quick(self, output: str) -> bool:
        """
        Quick safety check (no detailed result).

        Args:
            output: Output to check

        Returns:
            True if output is safe
        """
        return self.validate(output).is_safe

    def get_leak_summary(self, output: str) -> str | None:
        """
        Get a human-readable summary of any leaks detected.

        Args:
            output: Output to check

        Returns:
            Summary string or None if no leaks
        """
        result = self.validate(output)
        if result.is_safe and result.leak_type == LeakType.NONE:
            return None

        return f"Leak detected: {result.leak_type.value} (severity: {result.leak_severity.value}) - {result.reason}"


# =============================================================================
# Singleton for easy access
# =============================================================================

_output_guard: OutputGuard | None = None


def get_output_guard(block_on_leak: bool = False, sanitize_output: bool = True, enabled: bool = True) -> OutputGuard:
    """Get or create the global OutputGuard instance."""
    global _output_guard
    if _output_guard is None:
        _output_guard = OutputGuard(block_on_leak=block_on_leak, sanitize_output=sanitize_output, enabled=enabled)
    return _output_guard
