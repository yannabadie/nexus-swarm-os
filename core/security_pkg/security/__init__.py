"""
NEXUS V8.8 Security Module - Multi-Layer Defense System

This module provides defense-in-depth protection:

Layer 1: InputGuard - Prompt injection prevention (V8.8)
Layer 2: Spotlighter - RAG content protection (V8.8, in core/memory/)
Layer 3: ExecutionPolicy - Command validation (Phase 14a)
Layer 4: PathGuardian - Path canonicalization and zone validation
Layer 5: OutputGuard - System prompt leak prevention (V8.8)
Layer 6: MutationValidator - AST-based behavioral analysis
Layer 7: CodeValidator - Dynamic tool code validation (Phase 12.5)

Design Principles:
- BLOCK writes to parent code (absolute protection)
- ALLOW reads from parent code (agents need context)
- WARN on suspicious patterns (don't over-block)
- ALLOW testing in workspace (agents need to experiment)
- PREFER shell=False for command execution (Phase 14a)
- SANITIZE before BLOCK when possible (V8.8)

V8.8 Additions (based on OWASP LLM01:2025):
- InputGuard: Regex-based prompt injection detection
- OutputGuard: System prompt leakage detection
- Spotlighter: RAG content datamarking (in core/memory/)
"""

# V12.4: Access Control
from .access_control import (
    AccessCheckResult,
    AccessControlManager,
    AccessStats,
    AgentAccess,
    Role,
    get_access_controller,
    reset_access_controller,
)

# V12.4: Encryption at Rest
from .encryption import EncryptionConfig, FileEncryptor, derive_key
from .execution_policy import CommandType, ExecutionPolicy, get_execution_policy
from .input_guard import (
    InputGuard,
    InputValidationResult,
    ThreatLevel,
    ThreatType,
    get_input_guard,
)
from .mutation_validator import MutationValidator
from .output_guard import (
    LeakSeverity,
    LeakType,
    OutputGuard,
    OutputValidationResult,
    get_output_guard,
)

# V12.2 IRONCLAD: Password hashing
from .password import hash_password, needs_rehash, verify_password
from .path_guardian import PathGuardian

# V12.4: Rate Limiter
from .rate_limiter import (
    LimiterStats,
    RateLimitConfig,
    RateLimiter,
    RateLimitResult,
    get_rate_limiter,
    reset_rate_limiter,
)

# V8.8: Spotlighter for RAG content datamarking (from memory module)
try:
    from core.memory_pkg.memory.spotlighting import Spotlighter, SpotlightTechnique, get_spotlighter

    SPOTLIGHTER_AVAILABLE = True
except ImportError:
    SPOTLIGHTER_AVAILABLE = False
    Spotlighter = None
    get_spotlighter = None
    SpotlightTechnique = None

# V12.4 COGNITIVE BOOST: Security Event Journal
from .security_event_journal import (
    SecurityEvent,
    SecurityEventJournal,
    SecurityJournalStats,
    ThreatPattern,
    get_security_journal,
    reset_security_journal,
)

__all__ = [
    # Path & Mutation
    "PathGuardian",
    "MutationValidator",
    # Execution Policy
    "ExecutionPolicy",
    "CommandType",
    "get_execution_policy",
    # V8.8: Input Guard
    "InputGuard",
    "ThreatLevel",
    "ThreatType",
    "InputValidationResult",
    "get_input_guard",
    # V8.8: Output Guard
    "OutputGuard",
    "LeakType",
    "LeakSeverity",
    "OutputValidationResult",
    "get_output_guard",
    # V8.8: Spotlighter (RAG datamarking)
    "Spotlighter",
    "get_spotlighter",
    "SpotlightTechnique",
    "SPOTLIGHTER_AVAILABLE",
    # V12.2 IRONCLAD: Password hashing
    "hash_password",
    "verify_password",
    "needs_rehash",
    # V12.4: Encryption at Rest
    "FileEncryptor",
    "EncryptionConfig",
    "derive_key",
    # V12.4: Rate Limiter
    "RateLimiter",
    "RateLimitConfig",
    "RateLimitResult",
    "LimiterStats",
    "get_rate_limiter",
    "reset_rate_limiter",
    # V12.4: Access Control
    "AccessControlManager",
    "Role",
    "AgentAccess",
    "AccessCheckResult",
    "AccessStats",
    "get_access_controller",
    "reset_access_controller",
    # V12.4 COGNITIVE BOOST: Security Event Journal
    "SecurityEventJournal",
    "SecurityEvent",
    "ThreatPattern",
    "SecurityJournalStats",
    "get_security_journal",
    "reset_security_journal",
]
