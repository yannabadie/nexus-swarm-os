"""
Task Analyzer - Sprint 9 Hybrid Swarm Engine

V11 SENTINEL: 3-Stage Cost-Aware Classification (F1 Fix)

Analyzes user input to determine:
- Task complexity (TRIVIAL to EXPERT)
- Task domains (CODING, RESEARCH, etc.)
- Agent fit scores (Gemini vs Claude)
- Requirements (web, code execution, deep reasoning)

V11 3-Stage Classification:
    Stage 1 (Regex)     : Instant commands (status, clear, exit). Cost: $0
    Stage 2 (Heuristic) : Context + keywords. Cost: Low (CPU only)
    Stage 3 (LLM)       : Fallback for ambiguous inputs. Cost: API tokens

Used by ModeSelector to choose the optimal collaboration mode.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory_pkg.memory.project_memory import ProjectMemory


class TaskComplexity(IntEnum):
    """Task complexity levels (1-5)"""

    TRIVIAL = 1  # Skip negotiation, direct execution
    SIMPLE = 2  # Basic task, minimal coordination
    MODERATE = 3  # Standard multi-agent task
    COMPLEX = 4  # Requires careful coordination
    EXPERT = 5  # Requires RED_BLUE or specialist


class AnalysisStage(IntEnum):
    """
    V11 SENTINEL: Which classification stage was used.

    Stage 1: Regex instant commands (Cost: $0)
    Stage 2: Heuristic classification (Cost: Low - CPU only)
    Stage 3: LLM fallback for ambiguous (Cost: API tokens)
    """

    STAGE1_REGEX = 1
    STAGE2_HEURISTIC = 2
    STAGE3_LLM = 3


class TaskDomain(Enum):
    """Task domain categories"""

    CODING = "coding"
    RESEARCH = "research"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    DEBUGGING = "debugging"
    SECURITY = "security"
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    ARCHITECTURE = "architecture"
    WEB_INTERACTION = "web_interaction"
    # V12.4 Multi-provider: additional domains for fine-grained strength mapping
    GENERAL = "general"
    WRITING = "writing"
    REASONING = "reasoning"


# Keywords that indicate task domains
DOMAIN_KEYWORDS: dict[TaskDomain, list[str]] = {
    TaskDomain.CODING: [
        "code",
        "implement",
        "function",
        "class",
        "method",
        "script",
        "python",
        "javascript",
        "typescript",
        "rust",
        "go",
        "program",
        "create file",
        "write code",
        "develop",
        "build",
    ],
    TaskDomain.RESEARCH: [
        "search",
        "find",
        "look up",
        "research",
        "investigate",
        "what is",
        "how does",
        "why",
        "compare",
        "difference between",
        "latest",
        "recent",
        "news",
        "documentation",
    ],
    TaskDomain.ANALYSIS: [
        "analyze",
        "examine",
        "review",
        "understand",
        "explain",
        "investigate",
        "study",
        "evaluate",
        "assess",
        "audit",
    ],
    TaskDomain.CREATIVE: [
        "brainstorm",
        "idea",
        "creative",
        "design",
        "propose",
        "suggest",
        "imagine",
        "innovate",
        "improve",
        "enhance",
    ],
    TaskDomain.DEBUGGING: [
        "debug",
        "fix",
        "bug",
        "error",
        "issue",
        "problem",
        "crash",
        "exception",
        "traceback",
        "broken",
        "not working",
    ],
    TaskDomain.SECURITY: [
        "security",
        "vulnerability",
        "exploit",
        "attack",
        "protect",
        "secure",
        "authentication",
        "authorization",
        "injection",
        "xss",
        "csrf",
        "penetration",
    ],
    TaskDomain.DOCUMENTATION: [
        "document",
        "readme",
        "guide",
        "tutorial",
        "explain how",
        "write docs",
        "api reference",
        "changelog",
    ],
    TaskDomain.TESTING: ["test", "pytest", "unittest", "coverage", "mock", "assert", "verify", "validate", "qa"],
    TaskDomain.ARCHITECTURE: [
        "architect",
        "architecture",
        "design pattern",
        "structure",
        "system design",
        "scalability",
        "refactor",
        "reorganize",
        "modular",
        "microservices",
        "distributed",
    ],
    TaskDomain.WEB_INTERACTION: [
        "web",
        "url",
        "fetch",
        "api",
        "http",
        "request",
        "scrape",
        "download",
        "upload",
        "endpoint",
    ],
    # V12.4 Multi-provider: additional domains for fine-grained strength mapping
    TaskDomain.GENERAL: [
        "general",
        "misc",
        "other",
        "anything",
        "help",
        "assist",
        "do",
        "can you",
        "please",
    ],
    TaskDomain.WRITING: [
        "write",
        "draft",
        "compose",
        "essay",
        "article",
        "blog",
        "report",
        "letter",
        "email",
        "content",
        "copywriting",
        "prose",
    ],
    TaskDomain.REASONING: [
        "reason",
        "logic",
        "infer",
        "deduce",
        "conclude",
        "proof",
        "theorem",
        "argument",
        "hypothesis",
        "think through",
        "step by step",
        "chain of thought",
    ],
}

# Agent strengths by domain - all 7 providers
# V12.4 Multi-provider: Extended from 2 (gemini/claude) to 7 providers
AGENT_DOMAIN_STRENGTHS: dict[str, dict[TaskDomain, float]] = {
    "gemini": {
        TaskDomain.RESEARCH: 0.95,  # Grounding, web search
        TaskDomain.WEB_INTERACTION: 0.90,  # Terminal-Bench leader
        TaskDomain.WRITING: 0.85,
        TaskDomain.ANALYSIS: 0.85,  # Long-horizon planning
        TaskDomain.REASONING: 0.85,
        TaskDomain.GENERAL: 0.85,
        TaskDomain.DOCUMENTATION: 0.75,
        TaskDomain.CREATIVE: 0.70,
        TaskDomain.CODING: 0.80,
        TaskDomain.TESTING: 0.65,
        TaskDomain.DEBUGGING: 0.60,
        TaskDomain.ARCHITECTURE: 0.60,
        TaskDomain.SECURITY: 0.65,
    },
    "claude": {
        TaskDomain.CODING: 0.95,  # SWE-bench leader
        TaskDomain.ARCHITECTURE: 0.95,  # Complex reasoning
        TaskDomain.DEBUGGING: 0.90,  # Sustained autonomy
        TaskDomain.REASONING: 0.90,
        TaskDomain.WRITING: 0.90,
        TaskDomain.SECURITY: 0.90,  # Red team expertise
        TaskDomain.CREATIVE: 0.85,
        TaskDomain.ANALYSIS: 0.80,
        TaskDomain.TESTING: 0.80,
        TaskDomain.DOCUMENTATION: 0.75,
        TaskDomain.GENERAL: 0.85,
        TaskDomain.RESEARCH: 0.60,  # No native web search
        TaskDomain.WEB_INTERACTION: 0.50,
    },
    "openai": {
        TaskDomain.CODING: 0.90,
        TaskDomain.REASONING: 0.88,
        TaskDomain.WRITING: 0.88,
        TaskDomain.GENERAL: 0.90,
        TaskDomain.RESEARCH: 0.82,
        TaskDomain.ARCHITECTURE: 0.85,
        TaskDomain.ANALYSIS: 0.85,
        TaskDomain.DEBUGGING: 0.82,
        TaskDomain.SECURITY: 0.80,
        TaskDomain.CREATIVE: 0.82,
        TaskDomain.TESTING: 0.78,
        TaskDomain.DOCUMENTATION: 0.80,
        TaskDomain.WEB_INTERACTION: 0.75,
    },
    "deepseek": {
        TaskDomain.CODING: 0.92,
        TaskDomain.REASONING: 0.90,
        TaskDomain.DEBUGGING: 0.85,
        TaskDomain.GENERAL: 0.80,
        TaskDomain.ARCHITECTURE: 0.80,
        TaskDomain.WRITING: 0.75,
        TaskDomain.ANALYSIS: 0.78,
        TaskDomain.TESTING: 0.78,
        TaskDomain.SECURITY: 0.72,
        TaskDomain.CREATIVE: 0.68,
        TaskDomain.RESEARCH: 0.65,
        TaskDomain.DOCUMENTATION: 0.70,
        TaskDomain.WEB_INTERACTION: 0.55,
    },
    "kimi": {
        TaskDomain.REASONING: 0.90,
        TaskDomain.RESEARCH: 0.85,
        TaskDomain.CODING: 0.82,
        TaskDomain.WRITING: 0.80,
        TaskDomain.GENERAL: 0.80,
        TaskDomain.ARCHITECTURE: 0.78,
        TaskDomain.ANALYSIS: 0.80,
        TaskDomain.DEBUGGING: 0.72,
        TaskDomain.SECURITY: 0.68,
        TaskDomain.CREATIVE: 0.75,
        TaskDomain.TESTING: 0.70,
        TaskDomain.DOCUMENTATION: 0.72,
        TaskDomain.WEB_INTERACTION: 0.70,
    },
    "minimax": {
        TaskDomain.REASONING: 0.82,
        TaskDomain.CODING: 0.80,
        TaskDomain.WRITING: 0.78,
        TaskDomain.GENERAL: 0.78,
        TaskDomain.RESEARCH: 0.75,
        TaskDomain.ARCHITECTURE: 0.72,
        TaskDomain.ANALYSIS: 0.75,
        TaskDomain.DEBUGGING: 0.68,
        TaskDomain.SECURITY: 0.65,
        TaskDomain.CREATIVE: 0.72,
        TaskDomain.TESTING: 0.65,
        TaskDomain.DOCUMENTATION: 0.68,
        TaskDomain.WEB_INTERACTION: 0.60,
    },
    "ollama": {
        TaskDomain.CODING: 0.70,
        TaskDomain.GENERAL: 0.72,
        TaskDomain.WRITING: 0.68,
        TaskDomain.REASONING: 0.65,
        TaskDomain.DEBUGGING: 0.65,
        TaskDomain.RESEARCH: 0.50,
        TaskDomain.ANALYSIS: 0.62,
        TaskDomain.TESTING: 0.58,
        TaskDomain.SECURITY: 0.50,
        TaskDomain.CREATIVE: 0.60,
        TaskDomain.ARCHITECTURE: 0.55,
        TaskDomain.DOCUMENTATION: 0.60,
        TaskDomain.WEB_INTERACTION: 0.40,
    },
}

# =============================================================================
# V11 SENTINEL: Stage 1 Instant Command Patterns (Cost: $0)
# =============================================================================
# These commands are recognized INSTANTLY via regex - no LLM needed
STAGE1_INSTANT_COMMANDS = [
    # System commands (exact match)
    r"^/?(status|state|info)$",
    r"^/?(clear|cls|reset)$",
    r"^/?(exit|quit|bye|q)$",
    r"^/?(help|\?)$",
    r"^/?(version|ver|v)$",
    r"^/?(config|settings|prefs)$",
    r"^/?(history|hist|logs?)$",
    r"^/?(cancel|stop|abort)$",
    # Session commands
    r"^/?(save|load|restore)$",
    r"^/?(undo|redo)$",
]

# V7.5 HIVE MIND: Patterns for trivial conversational inputs (greetings, etc.)
# These inputs should NOT trigger multi-agent collaboration
CONVERSATIONAL_TRIVIAL_PATTERNS = [
    # Greetings (FR/EN/ES/DE)
    r"^(hello|hi|hey|bonjour|salut|coucou|hola|hallo|guten tag)[\s!?.]*$",
    r"^(bonsoir|good morning|good evening|good night)[\s!?.]*$",
    # Farewells
    r"^(bye|goodbye|au revoir|ciao|adieu|à bientôt|a\+)[\s!?.]*$",
    # Acknowledgments
    r"^(ok|okay|d\'accord|oui|yes|non|no|merci|thanks|thank you|thx|ty)[\s!?.]*$",
    r"^(parfait|perfect|great|cool|nice|super|génial)[\s!?.]*$",
    r"^(compris|understood|got it|roger)[\s!?.]*$",
    # Simple questions about the assistant
    r"^(ça va\??|how are you\??|comment vas-tu\??|tu vas bien\??)[\s!?.]*$",
    r"^(qui es-tu\??|who are you\??|what are you\??)[\s!?.]*$",
    # Testing/probing
    r"^(test|testing|1234?|ping|pong)[\s!?.]*$",
    # Continuation prompts
    r"^(continue|continues|go on|vas-y|go ahead)[\s!?.]*$",
    # Empty or whitespace-only (after strip)
    r"^\s*$",
]

# V11 SENTINEL: Minimum confidence threshold for Stage 2 (below = Stage 3 LLM)
STAGE2_CONFIDENCE_THRESHOLD = 0.6

# Keywords that increase complexity
COMPLEXITY_INDICATORS: dict[str, int] = {
    # High complexity (+2) - system-level concerns requiring deep expertise
    "architect": 2,
    "refactor entire": 2,
    "redesign": 2,
    "migrate": 2,
    "critical": 2,
    "production": 2,
    "scalability": 2,
    "microservices": 2,
    "event sourcing": 2,
    # Medium complexity (+1) - notable effort but not system-level
    "security": 1,
    "vulnerability": 1,
    "architecture": 1,
    "implement": 1,
    "debug": 1,
    "analyze": 1,
    "integrate": 1,
    "optimize": 1,
    "test coverage": 1,
    "multiple files": 1,
    "across": 1,
    "complex": 1,
    "distributed": 1,
    "design": 1,
    "platform": 1,
    "cqrs": 1,
    # Low complexity (-1)
    "simple": -1,
    "quick": -1,
    "small": -1,
    "just": -1,
    "only": -1,
    "trivial": -1,
}

# =============================================================================
# V10 FIX F1: Context-Aware Classification Patterns
# =============================================================================

# Sentence structure patterns that indicate task type
TASK_STRUCTURE_PATTERNS = {
    # Multi-step tasks (complexity +1)
    "multi_step": [
        r"\b(first|then|after that|finally|next)\b",
        r"\b(step\s*\d|phase\s*\d)\b",
        r"\d+\.\s+\w+",  # Numbered lists
        r"\band\s+then\b",
    ],
    # Questions (usually ANALYSIS domain)
    "question": [
        r"\?$",
        r"^(what|why|how|where|when|which|who)\b",
        r"^(is|are|do|does|can|could|should|would)\b.*\?",
    ],
    # Imperative commands (direct action)
    "imperative": [
        r"^(create|write|implement|add|remove|delete|fix|update|change)\b",
        r"^(run|execute|test|build|deploy|install)\b",
        r"^(find|search|look|check|verify|validate)\b",
    ],
    # Conditional tasks (complexity +1)
    "conditional": [
        r"\bif\s+.+\s+(then|do|create)\b",
        r"\bwhen\s+.+\s+(then|do|should)\b",
        r"\bunless\b",
        r"\bdepending on\b",
    ],
}

# Context clues that provide additional classification signals
CONTEXT_CLUE_PATTERNS = {
    # File references indicate CODING domain
    "file_reference": [
        r"\b[\w/\\]+\.(py|js|ts|go|rs|java|cpp|c|h|md|json|yaml|yml|toml)\b",
        r"`[^`]+\.(py|js|ts|go|rs|java|cpp|c|h)`",
    ],
    # Code blocks indicate CODING domain
    "code_block": [
        r"```[\w]*\n",
        r"`[^`]{10,}`",  # Inline code longer than 10 chars
    ],
    # URLs indicate WEB_INTERACTION domain
    "url_reference": [
        r"https?://[^\s]+",
        r"\bapi\.[\w.]+\b",
    ],
    # Error messages indicate DEBUGGING domain
    "error_message": [
        r"\b(error|exception|traceback|stack trace)\b.*:",
        r"\bline\s+\d+\b",
        r"\b(TypeError|ValueError|KeyError|AttributeError|ImportError)\b",
    ],
}


@dataclass
class TaskAnalysis:
    """
    Complete analysis of a user task.

    Contains all information needed for mode selection and negotiation.

    V11 SENTINEL: Added analysis_stage to track classification cost.
    """

    # Core analysis
    complexity: TaskComplexity
    domains: list[TaskDomain]
    primary_domain: TaskDomain

    # Requirements
    requires_web: bool = False
    requires_code_execution: bool = False
    requires_deep_reasoning: bool = False
    requires_iteration: bool = False

    # Agent fit scores (0.0-1.0)
    gemini_fit_score: float = 0.5
    claude_fit_score: float = 0.5

    # Raw input for reference
    raw_input: str = ""

    # Confidence in analysis (0.0-1.0)
    confidence: float = 0.5

    # Detected keywords
    detected_keywords: list[str] = field(default_factory=list)

    # V11 SENTINEL: Classification stage used (1=Regex, 2=Heuristic, 3=LLM)
    analysis_stage: AnalysisStage = AnalysisStage.STAGE2_HEURISTIC

    # V11 SENTINEL: Instant command detected (Stage 1)
    instant_command: str | None = None

    @property
    def recommended_lead(self) -> str:
        """Recommend lead agent based on fit scores"""
        if self.gemini_fit_score > self.claude_fit_score + 0.1:
            return "gemini"
        elif self.claude_fit_score > self.gemini_fit_score + 0.1:
            return "claude"
        return "equal"  # No clear leader

    @property
    def should_skip_negotiation(self) -> bool:
        """Whether task is too trivial for negotiation"""
        return self.complexity == TaskComplexity.TRIVIAL

    @property
    def needs_adversarial_mode(self) -> bool:
        """Whether task should use RED_BLUE mode"""
        return self.complexity == TaskComplexity.EXPERT or TaskDomain.SECURITY in self.domains

    def to_dict(self) -> dict:
        return {
            "complexity": self.complexity.name,
            "complexity_value": self.complexity.value,
            "domains": [d.value for d in self.domains],
            "primary_domain": self.primary_domain.value,
            "requires_web": self.requires_web,
            "requires_code_execution": self.requires_code_execution,
            "requires_deep_reasoning": self.requires_deep_reasoning,
            "requires_iteration": self.requires_iteration,
            "gemini_fit_score": round(self.gemini_fit_score, 3),
            "claude_fit_score": round(self.claude_fit_score, 3),
            "recommended_lead": self.recommended_lead,
            "should_skip_negotiation": self.should_skip_negotiation,
            "needs_adversarial_mode": self.needs_adversarial_mode,
            "confidence": round(self.confidence, 3),
            "detected_keywords": self.detected_keywords,
            # V11 SENTINEL: Stage tracking
            "analysis_stage": self.analysis_stage.name,
            "analysis_cost": ["$0", "CPU", "API"][self.analysis_stage.value - 1],
            "instant_command": self.instant_command,
        }

    @classmethod
    def from_dict(cls, data: dict) -> TaskAnalysis:
        """
        V12.4: Create TaskAnalysis from a dictionary (for blackboard deserialization).

        Args:
            data: Dictionary with TaskAnalysis fields (from to_dict)

        Returns:
            TaskAnalysis instance
        """
        # Parse complexity enum
        complexity = TaskComplexity[data.get("complexity", "MODERATE")]

        # Parse domains - they're stored as string values
        domains_raw = data.get("domains", [])
        domains = [TaskDomain(d) for d in domains_raw]
        if not domains:
            domains = [TaskDomain.GENERAL]

        # Parse primary domain
        primary_domain = TaskDomain(data.get("primary_domain", "general"))

        # Parse analysis stage
        stage_name = data.get("analysis_stage", "STAGE2_HEURISTIC")
        try:
            analysis_stage = AnalysisStage[stage_name]
        except KeyError:
            analysis_stage = AnalysisStage.STAGE2_HEURISTIC

        return cls(
            complexity=complexity,
            domains=domains,
            primary_domain=primary_domain,
            requires_web=data.get("requires_web", False),
            requires_code_execution=data.get("requires_code_execution", False),
            requires_deep_reasoning=data.get("requires_deep_reasoning", False),
            requires_iteration=data.get("requires_iteration", False),
            gemini_fit_score=data.get("gemini_fit_score", 0.5),
            claude_fit_score=data.get("claude_fit_score", 0.5),
            raw_input=data.get("raw_input", ""),
            confidence=data.get("confidence", 0.5),
            detected_keywords=data.get("detected_keywords", []),
            analysis_stage=analysis_stage,
            instant_command=data.get("instant_command"),
        )


class TaskAnalyzer:
    """
    Analyzes user input to determine task characteristics.

    Uses keyword matching and heuristics to classify tasks
    for optimal mode selection.

    V10 FIX F1: Enhanced with context-aware classification beyond keywords.
    V11 SENTINEL: 3-Stage cost-aware classification (Regex->Heuristic->LLM).
    V11.2 MEMORIA: RAG-enriched classification for domain hints.
    """

    def __init__(self, project_memory: ProjectMemory | None = None):
        """
        Initialize TaskAnalyzer.

        Args:
            project_memory: Optional ProjectMemory for RAG-enriched classification.
                           If provided, RAG context helps classify task domains.
        """
        self._domain_patterns = self._compile_patterns()
        self._trivial_patterns = self._compile_trivial_patterns()
        # V10 FIX F1: Compile context patterns
        self._structure_patterns = self._compile_structure_patterns()
        self._context_patterns = self._compile_context_patterns()
        # V11 SENTINEL: Compile Stage 1 instant command patterns
        self._instant_command_patterns = self._compile_instant_commands()
        # V11.2 MEMORIA: ProjectMemory for RAG-enriched classification
        self.project_memory = project_memory

    def _compile_structure_patterns(self) -> dict[str, list[re.Pattern]]:
        """V10 FIX F1: Compile task structure patterns."""
        compiled = {}
        for category, patterns in TASK_STRUCTURE_PATTERNS.items():
            compiled[category] = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns]
        return compiled

    def _compile_context_patterns(self) -> dict[str, list[re.Pattern]]:
        """V10 FIX F1: Compile context clue patterns."""
        compiled = {}
        for category, patterns in CONTEXT_CLUE_PATTERNS.items():
            compiled[category] = [re.compile(p, re.IGNORECASE) for p in patterns]
        return compiled

    def _compile_trivial_patterns(self) -> list:
        """Compile regex patterns for trivial conversational inputs"""
        return [re.compile(p, re.IGNORECASE) for p in CONVERSATIONAL_TRIVIAL_PATTERNS]

    def _compile_instant_commands(self) -> list[re.Pattern]:
        """V11 SENTINEL: Compile Stage 1 instant command patterns."""
        return [re.compile(p, re.IGNORECASE) for p in STAGE1_INSTANT_COMMANDS]

    # =========================================================================
    # V11 SENTINEL: Stage 1 - Instant Command Detection (Cost: $0)
    # =========================================================================

    def is_instant_command(self, text: str) -> str | None:
        """
        V11 SENTINEL: Stage 1 - Check if input is an instant command.

        Instant commands are recognized via regex with ZERO LLM cost.
        Examples: status, clear, exit, help, version

        Args:
            text: User input

        Returns:
            Command name if matched, None otherwise
        """
        text_stripped = text.strip().lower()
        for pattern in self._instant_command_patterns:
            match = pattern.match(text_stripped)
            if match:
                # Extract the command from the match
                return match.group(0).lstrip("/")
        return None

    def is_conversational_trivial(self, text: str) -> bool:
        """
        V7 FIX: Detect trivial conversational inputs that don't need multi-agent.

        Examples: "hello", "bonjour", "test", "ok", etc.

        Returns:
            True if input is a simple greeting/acknowledgment
        """
        text_stripped = text.strip()
        return any(pattern.match(text_stripped) for pattern in self._trivial_patterns)

    def _compile_patterns(self) -> dict[TaskDomain, re.Pattern]:
        """Compile regex patterns for domain detection"""
        patterns = {}
        for domain, keywords in DOMAIN_KEYWORDS.items():
            # Create case-insensitive pattern
            pattern = r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b"
            patterns[domain] = re.compile(pattern, re.IGNORECASE)
        return patterns

    def analyze(self, user_input: str) -> TaskAnalysis:
        """
        Analyze user input and return TaskAnalysis.

        V11 SENTINEL: 3-Stage Cost-Aware Classification
            Stage 1: Regex instant commands (Cost: $0)
            Stage 2: Heuristic classification (Cost: Low - CPU only)
            Stage 3: LLM fallback for ambiguous (Cost: API tokens)

        Args:
            user_input: Raw user request text

        Returns:
            TaskAnalysis with complexity, domains, and agent fit scores
        """
        # =====================================================================
        # STAGE 1: Instant Command Detection (Cost: $0)
        # =====================================================================
        instant_cmd = self.is_instant_command(user_input)
        if instant_cmd:
            return TaskAnalysis(
                complexity=TaskComplexity.TRIVIAL,
                domains=[],
                primary_domain=TaskDomain.CREATIVE,
                requires_web=False,
                requires_code_execution=False,
                requires_deep_reasoning=False,
                requires_iteration=False,
                gemini_fit_score=0.5,
                claude_fit_score=0.5,
                raw_input=user_input,
                confidence=1.0,
                detected_keywords=[f"[INSTANT_CMD:{instant_cmd}]"],
                analysis_stage=AnalysisStage.STAGE1_REGEX,
                instant_command=instant_cmd,
            )

        # V7 FIX: Check for trivial conversational inputs (also Stage 1)
        if self.is_conversational_trivial(user_input):
            return TaskAnalysis(
                complexity=TaskComplexity.TRIVIAL,
                domains=[],  # No specific domain
                primary_domain=TaskDomain.CREATIVE,  # Fallback
                requires_web=False,
                requires_code_execution=False,
                requires_deep_reasoning=False,
                requires_iteration=False,
                gemini_fit_score=0.5,
                claude_fit_score=0.5,
                raw_input=user_input,
                confidence=1.0,  # High confidence it's trivial
                detected_keywords=["[TRIVIAL_CONVERSATIONAL]"],
                analysis_stage=AnalysisStage.STAGE1_REGEX,
            )

        # =====================================================================
        # STAGE 2: Heuristic Classification (Cost: Low - CPU only)
        # =====================================================================
        input_lower = user_input.lower()

        # Detect domains
        domains, detected_keywords = self._detect_domains(user_input)

        # V11.2 MEMORIA: Enrich with RAG context (if available)
        rag_domains, complexity_boost = self._enrich_with_rag_context(user_input)
        if rag_domains:
            domains, detected_keywords = self._apply_rag_domain_hints(domains, rag_domains, detected_keywords)

        # Determine primary domain
        primary_domain = domains[0] if domains else TaskDomain.CODING

        # Calculate complexity (V11.2: with RAG boost)
        base_complexity = self._calculate_complexity(input_lower, domains)
        # Apply RAG complexity boost (0.0-0.3 maps to 0-1 complexity levels)
        # V11.2.1 FIX: Use round() instead of int() to avoid truncation
        # int(0.3 * 3) = int(0.9) = 0 <- BUG! round(0.9) = 1 <- CORRECT
        if complexity_boost > 0:
            boost_levels = round(complexity_boost * 3.34)  # 0.3 * 3.34 = 1.0 -> 1 level
            boosted_value = min(5, base_complexity.value + boost_levels)
            complexity = TaskComplexity(boosted_value)
            if boosted_value != base_complexity.value:
                detected_keywords.append(f"[RAG_COMPLEXITY:+{boost_levels}]")
        else:
            complexity = base_complexity

        # Detect requirements
        requires_web = self._detect_web_requirement(input_lower)
        requires_code = self._detect_code_requirement(input_lower, domains)
        requires_reasoning = self._detect_reasoning_requirement(input_lower, complexity)
        requires_iteration = self._detect_iteration_requirement(input_lower, domains)

        # Calculate agent fit scores
        gemini_score, claude_score = self._calculate_agent_fit(domains, requires_web, requires_code, requires_reasoning)

        # Estimate confidence
        confidence = self._estimate_confidence(domains, detected_keywords, user_input)

        # V11 SENTINEL: Stage 2 result (Heuristic)
        # If confidence is below threshold, Stage 3 (LLM) could be triggered
        # but we keep Stage 2 as the default to avoid API costs
        analysis_stage = AnalysisStage.STAGE2_HEURISTIC

        # Mark low-confidence results for potential Stage 3 escalation
        if confidence < STAGE2_CONFIDENCE_THRESHOLD:
            detected_keywords.append(f"[LOW_CONFIDENCE:{confidence:.2f}]")

        return TaskAnalysis(
            complexity=complexity,
            domains=domains if domains else [TaskDomain.CODING],
            primary_domain=primary_domain,
            requires_web=requires_web,
            requires_code_execution=requires_code,
            requires_deep_reasoning=requires_reasoning,
            requires_iteration=requires_iteration,
            gemini_fit_score=gemini_score,
            claude_fit_score=claude_score,
            raw_input=user_input,
            confidence=confidence,
            detected_keywords=detected_keywords,
            analysis_stage=analysis_stage,
        )

    def _detect_domains(self, text: str) -> tuple[list[TaskDomain], list[str]]:
        """
        Detect task domains from text.

        Returns:
            Tuple of (domains list sorted by relevance, detected keywords)
        """
        domain_scores: dict[TaskDomain, int] = {}
        detected_keywords: list[str] = []

        for domain, pattern in self._domain_patterns.items():
            matches = pattern.findall(text)
            if matches:
                domain_scores[domain] = len(matches)
                detected_keywords.extend(matches)

        # V10 FIX F1: Merge context-inferred domains
        context_domains = self._infer_domains_from_context(text)
        for domain in context_domains:
            if domain not in domain_scores:
                domain_scores[domain] = 1  # Context inference counts as 1 match
                detected_keywords.append(f"[CONTEXT:{domain.value}]")

        # Sort by score descending
        sorted_domains = sorted(domain_scores.keys(), key=lambda d: domain_scores[d], reverse=True)

        return sorted_domains, list(set(detected_keywords))

    def _calculate_complexity(self, text: str, domains: list[TaskDomain]) -> TaskComplexity:
        """Calculate task complexity based on indicators and structure (V10 FIX F1).

        V12.4 FIX: Reworked scoring to avoid over-inflation from keyword/domain stacking.
        - Base score starts at 2 (SIMPLE) instead of 3 to give keywords room to push up.
        - Domain bonuses only apply when keywords didn't already cover that domain.
        - "security" alone contributes to MODERATE, not EXPERT.
        - "architect" + scale indicators properly reach EXPERT.
        """
        score = 2  # Start at SIMPLE baseline

        # Apply keyword modifiers (track which domains were boosted by keywords)
        keyword_boosted_domains: set[str] = set()
        for keyword, modifier in COMPLEXITY_INDICATORS.items():
            if keyword in text:
                score += modifier
                # Track domain coverage from keywords to avoid double-counting
                if keyword in ("security", "vulnerability"):
                    keyword_boosted_domains.add("security")
                if keyword in ("architect", "architecture", "microservices",
                               "distributed", "event sourcing"):
                    keyword_boosted_domains.add("architecture")

        # Domain-based modifiers (only if not already boosted by keywords)
        if TaskDomain.SECURITY in domains and "security" not in keyword_boosted_domains:
            score += 1
        if TaskDomain.ARCHITECTURE in domains and "architecture" not in keyword_boosted_domains:
            score += 1
        if len(domains) > 3:  # Multi-domain tasks are more complex
            score += 1

        # Text length heuristic (longer descriptions = more complex tasks)
        if len(text) > 500:
            score += 2
        elif len(text) > 200:
            score += 1

        # V10 FIX F1: Apply structure-based complexity adjustments
        score = self._adjust_complexity_from_structure(score, text)

        # Clamp to valid range
        score = max(1, min(5, score))

        return TaskComplexity(score)

    def _detect_web_requirement(self, text: str) -> bool:
        """Detect if task requires web access"""
        web_indicators = [
            "search",
            "latest",
            "recent",
            "news",
            "web",
            "url",
            "http",
            "fetch",
            "api",
            "online",
            "documentation",
            "look up",
            "find out",
        ]
        return any(indicator in text for indicator in web_indicators)

    def _detect_code_requirement(self, text: str, domains: list[TaskDomain]) -> bool:
        """Detect if task requires code execution"""
        code_indicators = ["run", "execute", "test", "pytest", "build", "compile", "bash", "terminal", "command"]
        has_indicators = any(ind in text for ind in code_indicators)
        has_code_domain = any(d in [TaskDomain.CODING, TaskDomain.TESTING, TaskDomain.DEBUGGING] for d in domains)
        return has_indicators or has_code_domain

    def _detect_reasoning_requirement(self, text: str, complexity: TaskComplexity) -> bool:
        """Detect if task requires deep reasoning"""
        reasoning_indicators = [
            "why",
            "analyze",
            "understand",
            "explain how",
            "design",
            "architecture",
            "complex",
            "trade-off",
        ]
        return any(ind in text for ind in reasoning_indicators) or complexity >= TaskComplexity.COMPLEX

    def _detect_iteration_requirement(self, text: str, domains: list[TaskDomain]) -> bool:
        """Detect if task requires iteration/refinement"""
        iteration_indicators = ["improve", "refine", "iterate", "brainstorm", "creative", "enhance", "optimize"]
        has_indicators = any(ind in text for ind in iteration_indicators)
        has_creative = TaskDomain.CREATIVE in domains
        return has_indicators or has_creative

    def _calculate_agent_fit(
        self, domains: list[TaskDomain], requires_web: bool, requires_code: bool, requires_reasoning: bool
    ) -> tuple[float, float]:
        """
        Calculate fit scores for Gemini and Claude.

        Returns:
            Tuple of (gemini_score, claude_score)
        """
        gemini_total = 0.0
        claude_total = 0.0
        weight_total = 0.0

        # Weight domains by position (first domain = most important)
        for i, domain in enumerate(domains[:3]):
            weight = 1.0 / (i + 1)  # 1.0, 0.5, 0.33
            gemini_total += AGENT_DOMAIN_STRENGTHS["gemini"][domain] * weight
            claude_total += AGENT_DOMAIN_STRENGTHS["claude"][domain] * weight
            weight_total += weight

        # Normalize
        if weight_total > 0:
            gemini_score = gemini_total / weight_total
            claude_score = claude_total / weight_total
        else:
            gemini_score = 0.5
            claude_score = 0.5

        # Apply requirement modifiers
        if requires_web:
            gemini_score += 0.1  # Gemini has native web search
            claude_score -= 0.05

        if requires_code:
            claude_score += 0.05  # Claude excels at SWE tasks

        if requires_reasoning:
            claude_score += 0.05  # Claude for complex reasoning

        # Clamp to 0-1
        gemini_score = max(0.0, min(1.0, gemini_score))
        claude_score = max(0.0, min(1.0, claude_score))

        return gemini_score, claude_score

    def _estimate_confidence(self, domains: list[TaskDomain], keywords: list[str], text: str) -> float:
        """Estimate confidence in the analysis"""
        confidence = 0.5  # Base confidence

        # More keywords = higher confidence
        confidence += min(0.3, len(keywords) * 0.05)

        # Domains detected = higher confidence
        confidence += min(0.2, len(domains) * 0.1)

        # Reasonable length = higher confidence
        if 50 < len(text) < 1000:
            confidence += 0.1

        # V10 FIX F1: Context clues boost confidence
        context_clues = self._detect_context_clues(text)
        if context_clues:
            confidence += min(0.15, len(context_clues) * 0.05)

        return min(1.0, confidence)

    # =========================================================================
    # V10 FIX F1: Context-Aware Analysis Methods
    # =========================================================================

    def _analyze_task_structure(self, text: str) -> dict[str, bool]:
        """
        V10 FIX F1: Analyze task structure beyond keywords.

        Detects:
        - Multi-step tasks (numbered lists, "first...then...")
        - Questions vs commands
        - Conditional logic
        - Imperative style

        Returns:
            Dict with structure flags
        """
        structure = {
            "is_multi_step": False,
            "is_question": False,
            "is_imperative": False,
            "is_conditional": False,
        }

        for category, patterns in self._structure_patterns.items():
            for pattern in patterns:
                if pattern.search(text):
                    structure[f"is_{category}"] = True
                    break

        return structure

    def _detect_context_clues(self, text: str) -> list[str]:
        """
        V10 FIX F1: Detect context clues that inform classification.

        Returns:
            List of detected context clue types
        """
        clues = []

        for category, patterns in self._context_patterns.items():
            for pattern in patterns:
                if pattern.search(text):
                    clues.append(category)
                    break

        return clues

    def _infer_domains_from_context(self, text: str) -> list[TaskDomain]:
        """
        V10 FIX F1: Infer domains from context clues, not just keywords.

        Returns:
            List of inferred domains
        """
        inferred = []
        clues = self._detect_context_clues(text)

        # Map context clues to domains
        clue_domain_map = {
            "file_reference": TaskDomain.CODING,
            "code_block": TaskDomain.CODING,
            "url_reference": TaskDomain.WEB_INTERACTION,
            "error_message": TaskDomain.DEBUGGING,
        }

        for clue in clues:
            if clue in clue_domain_map:
                domain = clue_domain_map[clue]
                if domain not in inferred:
                    inferred.append(domain)

        # Structure-based inference
        structure = self._analyze_task_structure(text)
        if structure.get("is_question") and not inferred:
            inferred.append(TaskDomain.ANALYSIS)

        return inferred

    def _adjust_complexity_from_structure(self, base_complexity: int, text: str) -> int:
        """
        V10 FIX F1: Adjust complexity based on task structure analysis.

        Args:
            base_complexity: Initial complexity score
            text: Task text

        Returns:
            Adjusted complexity score
        """
        structure = self._analyze_task_structure(text)

        # Multi-step tasks are more complex
        if structure.get("is_multi_step"):
            base_complexity += 1

        # Conditional tasks are more complex
        if structure.get("is_conditional"):
            base_complexity += 1

        # Pure questions without action verbs are simpler, but never below SIMPLE(2)
        # Questions still require substantive answers unlike greetings (TRIVIAL)
        if structure.get("is_question") and not structure.get("is_imperative"):
            base_complexity = max(2, base_complexity - 1)

        # Context clues that indicate complexity
        clues = self._detect_context_clues(text)
        if "error_message" in clues:
            base_complexity += 1  # Debugging from error is non-trivial

        return base_complexity

    # =========================================================================
    # V11 SENTINEL: Async Analysis Methods
    # =========================================================================

    async def analyze_async(self, user_input: str) -> TaskAnalysis:
        """
        V11 SENTINEL: Async version of analyze() that yields control.

        This method is designed for use in async contexts (like CEREBRO UI)
        where the event loop must remain responsive.

        For Stage 1 & 2: CPU-bound, runs in thread pool to yield control
        For Stage 3 (future): Would call LLM asynchronously

        Args:
            user_input: Raw user request text

        Returns:
            TaskAnalysis with complexity, domains, and agent fit scores
        """
        # Run CPU-bound analysis in thread pool to yield event loop control
        return await asyncio.to_thread(self.analyze, user_input)

    def needs_stage3_escalation(self, analysis: TaskAnalysis) -> bool:
        """
        V11 SENTINEL: Check if analysis needs Stage 3 (LLM) escalation.

        Returns True if confidence is below threshold AND task appears non-trivial.
        Used by orchestrators to decide whether to spend API tokens on refinement.

        Args:
            analysis: Stage 2 analysis result

        Returns:
            True if LLM escalation recommended
        """
        # Don't escalate trivial tasks
        if analysis.complexity == TaskComplexity.TRIVIAL:
            return False

        # Don't escalate if already high confidence
        if analysis.confidence >= STAGE2_CONFIDENCE_THRESHOLD:
            return False

        # Don't escalate if clear domain detected
        return not (len(analysis.domains) >= 2 and analysis.confidence > 0.4)

    # =========================================================================
    # V11.2 MEMORIA: RAG-Enriched Classification
    # =========================================================================

    def _enrich_with_rag_context(self, user_input: str) -> tuple[list[TaskDomain], float]:
        """
        V11.2 MEMORIA: Get RAG context to help classification.

        Retrieves relevant code chunks from ProjectMemory and infers
        domain hints based on file types and content patterns.

        Args:
            user_input: User's task description

        Returns:
            Tuple of (domain_hints, complexity_boost)
                domain_hints: List of domains inferred from RAG context
                complexity_boost: Additional complexity score (0.0-0.3)
        """
        if not self.project_memory:
            return [], 0.0

        try:
            # Retrieve relevant chunks (limit=2 for speed)
            chunks = self.project_memory.retrieve(user_input, limit=2, min_score=0.1)
            if not chunks:
                return [], 0.0

            domain_hints: list[TaskDomain] = []
            complexity_boost = 0.0

            for chunk in chunks:
                file_path = getattr(chunk, "file_path", getattr(chunk, "source_path", ""))
                content = getattr(chunk, "content", "")

                # Infer domain from file extension
                if file_path.endswith(".py"):
                    if TaskDomain.CODING not in domain_hints:
                        domain_hints.append(TaskDomain.CODING)
                    if ("test_" in file_path or "/tests/" in file_path) and TaskDomain.TESTING not in domain_hints:
                        domain_hints.append(TaskDomain.TESTING)
                elif file_path.endswith(".md"):
                    if TaskDomain.DOCUMENTATION not in domain_hints:
                        domain_hints.append(TaskDomain.DOCUMENTATION)
                elif file_path.endswith((".js", ".ts", ".tsx", ".jsx")):
                    if TaskDomain.CODING not in domain_hints:
                        domain_hints.append(TaskDomain.CODING)

                # Complexity hints from content patterns
                if "async" in content or "await" in content:
                    complexity_boost += 0.1
                if "class " in content:
                    complexity_boost += 0.05
                if "try:" in content or "except" in content:
                    complexity_boost += 0.05
                if "security" in content.lower() or "auth" in content.lower():
                    complexity_boost += 0.1
                    if TaskDomain.SECURITY not in domain_hints:
                        domain_hints.append(TaskDomain.SECURITY)

            return domain_hints, min(0.3, complexity_boost)

        except Exception:
            # Fail silently - RAG enrichment is optional
            return [], 0.0

    def _apply_rag_domain_hints(
        self, detected_domains: list[TaskDomain], rag_domains: list[TaskDomain], detected_keywords: list[str]
    ) -> tuple[list[TaskDomain], list[str]]:
        """
        V11.2 MEMORIA: Merge RAG-inferred domains with keyword-detected domains.

        Args:
            detected_domains: Domains detected via keywords
            rag_domains: Domains inferred from RAG context
            detected_keywords: List of detected keywords (modified in-place)

        Returns:
            Tuple of (merged_domains, updated_keywords)
        """
        merged = list(detected_domains)

        for domain in rag_domains:
            if domain not in merged:
                merged.append(domain)
                detected_keywords.append(f"[RAG:{domain.value}]")

        return merged, detected_keywords


# =============================================================================
# V11 SENTINEL: Exports
# =============================================================================

__all__ = [
    # Enums
    "TaskComplexity",
    "TaskDomain",
    "AnalysisStage",
    # Dataclasses
    "TaskAnalysis",
    # Analyzer
    "TaskAnalyzer",
    # Constants
    "STAGE2_CONFIDENCE_THRESHOLD",
]
