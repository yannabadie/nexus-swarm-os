# NEXUS V8.0 - Architecture Decision Records (ADR)

**Purpose**: Document WHY architectural decisions were made, not just WHAT.
**Format**: ADR (Architecture Decision Records) - lightweight version
**Last Updated**: 2025-12-08

---

## Index

| ADR | Title | Status | Impact |
|-----|-------|--------|--------|
| ADR-001 | Pure asyncio without external deps | Accepted | HIGH |
| ADR-002 | Dual dataclass structures | Active | HIGH |
| ADR-003 | CLI-first architecture | Accepted | HIGH |
| ADR-004 | Protocol split (JSON/XML) | Accepted | MEDIUM |
| ADR-005 | commands.py as command router | Active | LOW |
| ADR-006 | Swarm modes are negotiated | Accepted | HIGH |
| ADR-007 | SuccessMemory read/write split | Active | MEDIUM |
| ADR-008 | Hot-Swap via StagnationDetector | Accepted | MEDIUM |
| ADR-009 | SessionMode.EPHEMERAL for trivial | Proposed | MEDIUM |
| ADR-010 | contextvars for multi-tenant | Proposed | HIGH |

---

## ADR-001: Pure asyncio Without External Dependencies

**Status**: Accepted (2025-11)
**Context**: NEXUS must be deployable in restricted environments (corporate, air-gapped).

**Decision**:
- Use only Python stdlib `asyncio` for async operations
- No external async libraries (`aiolimiter`, `httpx`, `aiohttp`)
- Custom implementations where needed (TokenBucket, retry loops)

**Consequences**:
- (+) Zero external async deps = simpler deployment
- (+) No version conflicts with enterprise environments
- (-) Must implement TokenBucket manually for rate limiting
- (-) Retry logic is manual (no `tenacity`)

**Implementation**:
```python
# Rate limiting: custom TokenBucket with asyncio.Lock
class ProviderGuard:
    _buckets = {
        "claude": {"tokens": 50.0, "rate": 0.83, "lock": asyncio.Lock()},
        "gemini": {"tokens": 60.0, "rate": 1.00, "lock": asyncio.Lock()}
    }
```

---

## ADR-002: Dual Dataclass Structures (IndependentAnalysis vs TaskAnalysis)

**Status**: Active (technical debt acknowledged)
**Context**: HiveMind and Swarm evolved as separate systems before V8 merge.

**Decision**:
- Keep both structures for backwards compatibility
- `IndependentAnalysis` (hive_mind/types.py) - for phase analysis output
- `TaskAnalysis` (swarm/task_analyzer.py) - for swarm routing decisions
- Create adapter when cross-domain communication needed

**Consequences**:
- (+) No breaking changes to existing code
- (+) Each domain optimized for its use case
- (-) Confusion about which to use where
- (-) Adapter required for SuccessMemory feedback loop

**Key Differences**:
| Field | IndependentAnalysis | TaskAnalysis |
|-------|---------------------|--------------|
| complexity | `str` (free text) | `TaskComplexity` enum |
| domains | Not present | `List[TaskDomain]` |
| confidence | `float` | Not present |
| reasoning | `proposed_approach` | `reasoning` |

**Future**: Consider unifying in V9.0, but not priority for V8.x stability.

---

## ADR-003: CLI-First Architecture

**Status**: Accepted (2025-10)
**Context**: Users interact via terminal, not web UI.

**Decision**:
- Primary interface is `nexus7.py` REPL (prompt-toolkit)
- LLM communication via CLI tools (`gemini`, `claude` commands)
- No HTTP server, no REST API, no WebSocket
- Rich console for output formatting

**Consequences**:
- (+) Simple deployment (just Python + CLI tools)
- (+) Works in SSH sessions, containers, WSL
- (+) No port management, no CORS, no auth tokens
- (-) No web UI (future consideration)
- (-) Subprocess overhead for each LLM call

**Implementation**:
```python
# LLM calls via subprocess
result = subprocess.run(
    ["gemini", "chat", "-m", model, prompt],
    capture_output=True, text=True
)
```

---

## ADR-004: Protocol Split (Gemini=JSON, Claude=XML)

**Status**: Accepted (2025-10)
**Context**: Each LLM has different strengths in structured output.

**Decision**:
- Gemini: Strict JSON protocol (`LightMessageV7`, `HeavyMessageV7`)
- Claude: Hybrid natural language + `<tool_use>` XML blocks
- Parsers are separate (`stream_parser.py` handles both)

**Consequences**:
- (+) Each agent uses its natural format
- (+) Gemini JSON is reliable and parseable
- (+) Claude natural language enables richer collaboration
- (-) Two parsing codepaths to maintain
- (-) Protocol translation needed for some operations

**Never change**:
- Don't force Claude to use JSON-only
- Don't force Gemini to use XML tools
- Unified protocol would break existing parsing

---

## ADR-005: commands.py as Command Router

**Status**: Active
**Context**: System commands (`/reset`, `/help`, etc.) need central routing.

**Decision**:
- `core/interface/commands.py` contains `COMMAND_CATEGORIES` dict
- All slash commands registered here
- FSM handlers check against this registry

**Location**: `core/interface/commands.py:58`
```python
COMMAND_CATEGORIES = {
    "System": {"/reset", "/status", "/stop", "/help", "/version"},
    "Debug": {"/context", "/state", "/blackboard", "/metrics"},
    "Swarm": {"/swarm", "/modes", "/dylan"},
    "Memory": {"/memory", "/forget", "/recall"},
    "Evolution": {"/evolve", "/spawn", "/specialize"},
}
```

**Consequences**:
- (+) Single source of truth for commands
- (+) Easy to add new commands
- (-) Intent resolution still uses string matching in FSM
- Future: V8.1.5 IntentResolver will complement (not replace) this

---

## ADR-006: Swarm Modes are Negotiated

**Status**: Accepted (2025-11, Sprint 9)
**Context**: Optimal collaboration mode depends on task and agent strengths.

**Decision**:
- 6 collaboration modes: PARALLEL, SEQUENTIAL, LEAD_SUPPORT, PING_PONG, SPECIALIST, RED_BLUE
- Mode is negotiated between agents (max 4 turns)
- DyLAN metrics inform initial proposal
- ModeSelector makes final decision

**Consequences**:
- (+) Adaptive collaboration per task
- (+) Agents can advocate for their strengths
- (+) Learning from past successes (SuccessMemory)
- (-) Negotiation overhead (~4 extra turns)
- (-) Complexity in mode_selector.py

**Negotiation Protocol**:
```json
{"proposed_mode": "LEAD_SUPPORT", "my_role": "lead", "reason": "..."}
{"accept": true, "my_role": "support"}
```

---

## ADR-007: SuccessMemory Read/Write Split

**Status**: Active (V8.1.0 will close the loop)
**Context**: ModeSelector needs historical success data for recommendations.

**Current State**:
- **READ**: `_apply_memory_boost()` EXISTS (mode_selector.py:614-685)
  - Queries `success_memory.get_best_mode_for_similar()`
  - Uses semantic similarity for matching
- **WRITE**: `record_success()` NEVER CALLED
  - Method exists but not invoked from pipeline
  - Feedback loop is OPEN (read-only)

**Decision** (V8.1.0):
- Add hook in `TrueHiveMind.process_task()` after successful execution
- Create adapter: `IndependentAnalysis` -> format compatible with `record_success()`
- Add "worthiness" criteria (skip TRIVIAL, require 4+ phases)

**Consequences**:
- (+) System learns from successes
- (+) Mode selection improves over time
- (-) Requires adapter for dataclass mismatch (ADR-002)

---

## ADR-008: Hot-Swap via StagnationDetector

**Status**: Accepted (V8.0.1, 2025-12-08)
**Context**: Agents can get stuck in circular discussions.

**Decision**:
- `StagnationDetector` monitors message similarity (difflib)
- After N stagnations, recommend lead agent swap
- Swap: Gemini <-> Claude
- Report to `StrategyBlacklist` to prevent repeat

**Implementation**: `core/fsm/stagnation_detector.py`
```python
def should_swap_lead(self, current_lead: str, failure_count: int = 2) -> bool:
    return self.is_stagnant() and self._stagnation_count >= failure_count

def get_swap_recommendation(self, current_lead: str) -> dict:
    new_lead = "claude" if current_lead == "gemini" else "gemini"
    return {"should_swap": True, "new_lead": new_lead, ...}
```

**Consequences**:
- (+) Automatic recovery from stagnation
- (+) Both agents get chance to lead
- (-) May swap prematurely if threshold too low

---

## ADR-009: SessionMode.EPHEMERAL for Trivial Tasks

**Status**: Proposed (V8.0.3)
**Context**: TRIVIAL tasks (<2s expected) pay full pipeline overhead.

**Decision**:
- Add fast-track path for complexity < 0.15
- Skip RAG persistence (voluntary amnesia)
- Direct: Input -> Single Agent -> Output
- Use `SessionMode.EPHEMERAL` (already exists, unused)

**Location**: `core/swarm/session_manager.py:46`
```python
class SessionMode(Enum):
    STANDARD = "standard"
    EPHEMERAL = "ephemeral"  # EXISTS but NOT ACTIVATED
    PERSISTENT = "persistent"
```

**Consequences**:
- (+) TRIVIAL: 45s -> <2s latency
- (+) Reduced storage for throwaway queries
- (-) No learning from trivial tasks
- (-) Complexity threshold needs tuning

---

## ADR-010: contextvars for Multi-Tenant Isolation

**Status**: Proposed (V8.2.0)
**Context**: Enterprise deployment needs tenant isolation.

**Decision**:
- Use Python `contextvars` for thread/async-safe context
- `SessionContext` dataclass with `tenant_id`, `permissions`, `workspace_root`
- RAG filters by tenant automatically
- File operations scoped to tenant workspace

**Pattern**:
```python
import contextvars

current_session = contextvars.ContextVar("session_context")

@dataclass
class SessionContext:
    tenant_id: str
    workspace_root: Path
    permissions: list[str]

# Usage
def get_tenant() -> str:
    return current_session.get().tenant_id
```

**Consequences**:
- (+) Standard pattern (Flask, FastAPI use this)
- (+) Works with asyncio automatically
- (+) No global state pollution
- (-) Must propagate to spawned agents explicitly
- (-) contextvars not currently used in codebase

---

## Superseded Decisions

| ADR | Title | Superseded By | Reason |
|-----|-------|---------------|--------|
| - | - | - | (none yet) |

---

## Decision Process

When proposing changes that affect architecture:

1. **Check existing ADRs** - Is this already decided?
2. **Check CONSTRAINTS.md** - Does it violate constraints?
3. **Propose new ADR** if significant change
4. **Update existing ADR** if modifying decision

**ADR Status Values**:
- `Proposed` - Under discussion
- `Accepted` - Implemented or ready to implement
- `Active` - Ongoing, may have tech debt
- `Superseded` - Replaced by newer decision

---

*This document explains WHY. For WHAT exists, see CODEBASE_SNAPSHOT.md. For constraints, see CONSTRAINTS.md.*
