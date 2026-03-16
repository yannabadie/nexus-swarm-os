# NEXUS Governance Module

## Synopsis

The **governance** module (codename "Le Tribunal") handles security policies, alignment verification, and access control for NEXUS. It provides sandbox execution policies for tool permissions and red team validation for evolution safety.

## Architecture

```
+-------------------------------------------------------------------------+
|                    GOVERNANCE ARCHITECTURE                               |
+-------------------------------------------------------------------------+
|                                                                          |
|  +------------------------------------------------------------------+   |
|  |                       KERNEL.py                                   |   |
|  |              Immutable Alignment to Creator                       |   |
|  +----------------------------+-------------------------------------+   |
|                               |                                          |
|         +---------------------+---------------------+                   |
|         |                     |                     |                   |
|         v                     v                     v                   |
|  +--------------+    +--------------+    +------------------+          |
|  | SandboxPolicy|    |  RedTeam     |    |  GCP Gatekeeper  |          |
|  | Tool Perms   |    |  Validator   |    |  (Planned)       |          |
|  +--------------+    +--------------+    +------------------+          |
|         |                     |                                         |
|         v                     v                                         |
|  +------------------------------------------------------------------+  |
|  |                     Evolution Gating                              |  |
|  |           Block unsafe evolutions, verify alignment               |  |
|  +------------------------------------------------------------------+  |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File/Directory | Purpose | Key Exports |
|----------------|---------|-------------|
| `sandbox_policy.py` | Tool execution permissions | `SandboxPolicy` |
| `red_team/` | Alignment testing | `RedTeamValidator`, alignment tests |

## Key Interfaces

### SandboxPolicy
```python
class SandboxPolicy:
    """Tool execution permissions and security policies."""

    def is_tool_allowed(self, tool_name: str, context: ExecutionContext) -> bool
    def get_allowed_paths(self, tool_name: str) -> List[Path]
    def validate_command(self, command: str) -> ValidationResult
```

### RedTeamValidator (in red_team/)
```python
class RedTeamValidator:
    """Alignment testing with trap questions."""

    def __init__(self, child_path: Path, child_id: str)
    def run_alignment_tests(self) -> AlignmentResults
    def check_kernel_compliance(self) -> bool
```

## Alignment Tests

The red_team module tests evolved children against trap questions:

| Test Category | Purpose |
|---------------|---------|
| **Kernel Compliance** | Cannot modify KERNEL.py |
| **Creator Alignment** | Loyal to Yann Abadie |
| **Harm Prevention** | Refuses harmful requests |
| **Data Protection** | Protects user data |
| **Self-Limitation** | Respects boundaries |

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `alignment_journal.py` | Persistent journaling of alignment checks and violations with per-agent trust score computation and alignment trend tracking | `get_alignment_journal`, `AlignmentJournal` |
| `decision_logger.py` | Records governance-level decisions (collaboration mode choices, agent spawn approvals/rejections, policy violations, phase routing) with rationale for audit trails | `get_decision_logger`, `DecisionLogger` |
| `ethics.py` | Alignment verification for spawned agents and evolved children ensuring creator alignment, collaboration parity, safety boundaries, transparency, and mission fidelity | `AlignmentVerifier`, `AlignmentConfig` |

## Planned Modules

| Module | Purpose | Status |
|--------|---------|--------|
| `gcp_gatekeeper.py` | ROI-based cloud access control | TODO |

## Usage

```python
from core.governance.red_team import RedTeamValidator

# Validate evolved child
validator = RedTeamValidator(
    child_path=Path("workspace/agents/security_specialist"),
    child_id="nexus-v12.5-security"
)

results = validator.run_alignment_tests()
if not results.passed:
    print(f"Alignment failures: {results.failures}")
```

## Dependencies

### Internal
- `KERNEL.py` - Immutable alignment rules
- `core.security` - Security validation

### External
- Standard library only

## Version History

- **V7.0** - Initial red_team module
- **V8.0** - SandboxPolicy extraction
- **V12.4** - Enhanced alignment tests, alignment journal, decision logger, ethics module
