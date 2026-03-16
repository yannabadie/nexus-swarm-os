# NEXUS Security Module

## Synopsis

The **security** module implements a multi-layer defense system (defense-in-depth) for NEXUS. It provides protection against prompt injection, path traversal, command injection, system prompt leakage, and malicious code execution. Based on OWASP LLM01:2025 recommendations.

## Architecture

```
+-------------------------------------------------------------------------+
|                    7-LAYER DEFENSE SYSTEM                                |
+-------------------------------------------------------------------------+
|                                                                          |
|  +-------------------------------------------------------------------+  |
|  |  Layer 1: InputGuard                                              |  |
|  |  Prompt injection detection (regex patterns, threat scoring)       |  |
|  +-------------------------------------------------------------------+  |
|                               ↓                                          |
|  +-------------------------------------------------------------------+  |
|  |  Layer 2: Spotlighter (in core/memory/)                           |  |
|  |  RAG content datamarking (delimiter injection prevention)          |  |
|  +-------------------------------------------------------------------+  |
|                               ↓                                          |
|  +-------------------------------------------------------------------+  |
|  |  Layer 3: ExecutionPolicy                                         |  |
|  |  Command validation (whitelist, shell=False preference)            |  |
|  +-------------------------------------------------------------------+  |
|                               ↓                                          |
|  +-------------------------------------------------------------------+  |
|  |  Layer 4: PathGuardian                                            |  |
|  |  Path canonicalization, zone validation, traversal prevention      |  |
|  +-------------------------------------------------------------------+  |
|                               ↓                                          |
|  +-------------------------------------------------------------------+  |
|  |  Layer 5: OutputGuard                                             |  |
|  |  System prompt leak detection and prevention                       |  |
|  +-------------------------------------------------------------------+  |
|                               ↓                                          |
|  +-------------------------------------------------------------------+  |
|  |  Layer 6: MutationValidator                                       |  |
|  |  AST-based behavioral analysis of code mutations                   |  |
|  +-------------------------------------------------------------------+  |
|                               ↓                                          |
|  +-------------------------------------------------------------------+  |
|  |  Layer 7: IntegrityMonitor                                        |  |
|  |  Runtime integrity verification of critical components             |  |
|  +-------------------------------------------------------------------+  |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `input_guard.py` | Prompt injection detection | `InputGuard`, `ThreatLevel`, `ThreatType` |
| `output_guard.py` | System prompt leak prevention | `OutputGuard`, `LeakType`, `LeakSeverity` |
| `execution_policy.py` | Command validation | `ExecutionPolicy`, `CommandType` |
| `path_guardian.py` | Path validation | `PathGuardian` |
| `mutation_validator.py` | Code mutation analysis | `MutationValidator` |
| `integrity_monitor.py` | Runtime integrity | `IntegrityMonitor` |
| `password.py` | Password hashing (V12.2) | `hash_password`, `verify_password` |

## Design Principles

| Principle | Description |
|-----------|-------------|
| **BLOCK writes to parent** | Absolute protection of NEXUS core code |
| **ALLOW reads from parent** | Agents need context from parent code |
| **WARN on suspicious patterns** | Don't over-block, alert instead |
| **ALLOW testing in workspace** | Agents need to experiment safely |
| **PREFER shell=False** | Prevent command injection |
| **SANITIZE before BLOCK** | Try to clean input before rejecting |

## Key Interfaces

### InputGuard (V8.8)
```python
class InputGuard:
    """Prompt injection detection."""

    def validate(self, input_text: str) -> InputValidationResult
    def get_threat_level(self, input_text: str) -> ThreatLevel
    def sanitize(self, input_text: str) -> str  # Try to clean

class ThreatLevel(Enum):
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4
```

### OutputGuard (V8.8)
```python
class OutputGuard:
    """System prompt leak prevention."""

    def validate(self, output: str) -> OutputValidationResult
    def detect_leaks(self, output: str) -> List[LeakType]
    def redact(self, output: str) -> str  # Remove sensitive data

class LeakType(Enum):
    SYSTEM_PROMPT = "system_prompt"
    API_KEY = "api_key"
    INTERNAL_PATH = "internal_path"
    DEBUG_INFO = "debug_info"
```

### ExecutionPolicy (Phase 14a)
```python
class ExecutionPolicy:
    """Command execution validation."""

    def validate_command(
        self,
        command: str,
        command_type: CommandType
    ) -> ValidationResult

    def is_allowed(self, command: str) -> bool
    def get_safe_execution_params(self, command: str) -> Dict

class CommandType(Enum):
    SHELL = "shell"
    PYTHON = "python"
    GIT = "git"
    FILE_SYSTEM = "file_system"
```

### PathGuardian
```python
class PathGuardian:
    """Path validation and zone enforcement."""

    def validate(self, path: Path) -> PathValidationResult
    def is_in_workspace(self, path: Path) -> bool
    def is_in_parent(self, path: Path) -> bool
    def canonicalize(self, path: Path) -> Path
    def get_zone(self, path: Path) -> PathZone
```

### MutationValidator
```python
class MutationValidator:
    """AST-based code mutation analysis."""

    def validate(self, code: str, context: MutationContext) -> ValidationResult
    def detect_dangerous_patterns(self, ast_tree: AST) -> List[Pattern]
    def analyze_behavioral_change(
        self,
        old_code: str,
        new_code: str
    ) -> BehavioralAnalysis
```

## Threat Detection Patterns

### InputGuard Patterns
- Role manipulation: "ignore previous instructions"
- Delimiter injection: `\n\n---\n\nSYSTEM:`
- Encoding attacks: base64, hex, unicode escapes
- Context confusion: fake tool responses

### OutputGuard Patterns
- System prompt leakage: "You are NEXUS..."
- API key exposure: `sk-...`, `AIza...`
- Internal paths: `/home/user/.nexus/`
- Debug information: stack traces, internal state

## Password Hashing (V12.2 IRONCLAD)

```python
from core.security import hash_password, verify_password, needs_rehash

# Hash a password
hashed = hash_password("user_password")

# Verify password
is_valid = verify_password("user_password", hashed)

# Check if rehash needed (algorithm upgrade)
if needs_rehash(hashed):
    new_hash = hash_password("user_password")
```

## Dependencies

### Internal
- `core.memory.spotlighting` - Spotlighter for RAG

### External
- `argon2-cffi` - Password hashing (V12.2)
- `ast` - Python AST analysis
- Standard library (re, pathlib)

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `security_event_journal.py` | Immutable audit journal for all security-relevant events (authentication, authorization, policy violations, encryption operations) with append-only JSONL persistence and tamper-evident checksums | `SecurityEventJournal`, `SecurityEvent` |
| `access_control.py` | Role-Based Access Control (RBAC) system with role definitions, permission grants/denials, agent registration, and effective permission calculation for fine-grained security policies | `AccessControl`, `Role`, `AgentAccess` |
| `encryption.py` | Data encryption utilities using industry-standard algorithms (AES-256, RSA) for at-rest and in-transit data protection with key management and secure random generation | `encrypt_data`, `decrypt_data`, `generate_key` |
| `rate_limiter.py` | Security-focused rate limiting for API endpoints, LLM calls, and tool executions to prevent abuse, DoS attacks, and runaway costs with token bucket algorithm | `RateLimiter`, `RateLimitExceeded` |

## Version History

- **V7.0** - PathGuardian, basic execution policy
- **Phase 14a** - ExecutionPolicy extraction
- **V8.8** - InputGuard, OutputGuard, Spotlighter (OWASP LLM01:2025)
- **Phase 12.5** - CodeValidator (dynamic tool validation)
- **V12.2** - IRONCLAD: Password hashing with argon2
- **V12.4** - COGNITIVE BOOST: Security event journal, RBAC, encryption, rate limiting
