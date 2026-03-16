# ARCHITECTURE DISCOVERY - OBSIDIAN V2.0

**Date:** 2025-12-13
**Branch:** N9AF
**Commit:** 69105250ddf9751bb78fabf1331bf4cc278ed31b

---

## Directory Structure

```
NEXUS-N7A/
+-- nexus7.py              # CLI Entry Point (EXCLUDE from web audit)
+-- KERNEL.py              # Security kernel (immutable alignment)
+-- core/
|   +-- adapters/          # Analysis adapters
|   +-- agents/            # Agent registry & service
|   +-- api/               # Rate limiter (potential API layer)
|   +-- async_primitives/  # Async utilities (blackboard, cancellation, etc.)
|   +-- bootstrap/         # Agent loader, auto-bootstrap
|   +-- config.py          # Configuration management
|   +-- constants.py       # System constants
|   +-- drivers/           # LLM drivers (Gemini, Claude) - CRITICAL
|   +-- evolution/         # Agent evolution & spawning
|   +-- execution/         # Tool execution engine
|   +-- fsm/               # Finite State Machine
|   +-- governance/        # Security policies, red team
|   +-- hive_mind/         # High-level orchestration pipeline
|   +-- interface/         # REPL & commands (CLI-ONLY)
|   +-- logging/           # Logging utilities
|   +-- mcp/               # MCP client
|   +-- memory/            # RAG & memory backends
|   +-- meta/              # CLI inspector
|   +-- notifications/     # REPL alerts
|   +-- orchestration/     # Agent invoker
|   +-- prompts/           # System prompts
|   +-- reasoning/         # CoT reasoning
|   +-- resilience/        # Resilience patterns
|   +-- routing/           # Model routing
|   +-- security/          # Security module
|   +-- session/           # Session isolation (V9.7.1 HOME spoofing)
|   +-- swarm/             # Swarm engine & executors
|   +-- synapse/           # Message protocols
|   +-- telemetry/         # Usage telemetry
|   +-- ui/                # UI components
|   +-- utils/             # Utility functions
|   +-- workspace/         # Workspace management
+-- tests/                 # Test suite
+-- docs/                  # Documentation
+-- audit/                 # Audit reports (this directory)
```

---

## Entry Point Classification

### CLI Entry Points (EXCLUDE from Web Audit)
| File | Purpose | Web Risk |
|------|---------|----------|
| `nexus7.py` | Main CLI entry | Contains `input()`, `sys.exit()` - EXPECTED |
| `core/interface/repl.py` | Interactive REPL | Contains `input()` - EXPECTED |
| `core/interface/commands/` | CLI commands | CLI-specific |

### API Entry Points (INCLUDE in Web Audit)
| File | Purpose | Status |
|------|---------|--------|
| `core/api/rate_limiter.py` | Rate limiting | To audit |
| `core/api/__init__.py` | API module | To audit |

### Internal Modules (INCLUDE in Web Audit)
| Module | Critical | Reason |
|--------|----------|--------|
| `core/drivers/` | YES | Subprocess spawning, isolation |
| `core/session/` | YES | Session isolation (V9.7.1) |
| `core/swarm/` | YES | Multi-agent execution |
| `core/execution/` | YES | Tool execution |
| `core/async_primitives/` | YES | Async utilities |

---

## Tech Stack Detected

- **Language:** Python 3.11+
- **Async Framework:** asyncio (native)
- **LLM Integration:** CLI-based (subprocess to `gemini`, `claude`)
- **State Management:** Blackboard pattern (JSON files)
- **Database:** LanceDB (vector store in `.nexus/lancedb/`)
- **No Web Framework Detected:** FastAPI/Flask not present (CLI-first)

---

## Key Isolation Mechanism

**V9.7.1 HOME Spoofing** (implemented 2025-12-13):
- Location: `core/session/home_isolator.py`
- Purpose: Isolate Gemini CLI sessions via HOME environment variable
- Method: Each subprocess gets unique HOME directory
- CWD: Preserved at workspace root (prevents ghost files)

---

## Files to Audit (Scope)

### Critical (Must Pass)
```
core/drivers/gemini_driver_v7.py
core/drivers/async_gemini_driver.py
core/drivers/claude_driver_hybrid.py
core/drivers/async_claude_driver.py
core/session/home_isolator.py
core/session/workspace_manager.py
core/swarm/session_manager.py
core/swarm/executors/base.py
core/orchestration/agent_invoker.py
core/async_primitives/*.py
```

### High Priority
```
core/execution/execution_engine.py
core/execution/handlers/*.py
core/memory/*.py
core/config.py
```

### Excluded from Fatal Checks
```
nexus7.py (CLI entry)
core/interface/*.py (REPL)
tests/*.py (Test code)
```
