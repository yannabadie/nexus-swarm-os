# NEXUS Workflows Documentation

**Version**: 12.4 | **Last Updated**: 2025-12-16

This directory contains detailed workflow documentation for the NEXUS system.

---

## Documents

| Document | Description |
|----------|-------------|
| [BACKEND_WORKFLOWS.md](BACKEND_WORKFLOWS.md) | FSM states, HiveMind pipeline, Swarm modes, Tool execution |
| [FRONTEND_WORKFLOWS.md](FRONTEND_WORKFLOWS.md) | Authentication, WebSocket, Task execution, HITL interactions |
| [FULL_SYSTEM_FLOW.md](FULL_SYSTEM_FLOW.md) | End-to-end flow from user input to result |

---

## Quick Reference

### Backend Entry Points

| Entry Point | File | Purpose |
|-------------|------|---------|
| CLI | `nexus7.py` | Interactive REPL |
| API | `core/api/cerebro/app.py` | REST + WebSocket server |

### Core Pipelines

| Pipeline | Trigger | Complexity |
|----------|---------|------------|
| FSM Direct | All tasks | TRIVIAL |
| HiveMind | Auto-route | MODERATE+ |
| Swarm | `/swarm` or mode specified | MODERATE+ |

### Swarm Modes

| Mode | Agents | Pattern |
|------|--------|---------|
| PARALLEL | Both | Independent work, merged results |
| SEQUENTIAL | Both | Ordered execution |
| LEAD_SUPPORT | Both | Expert leads, partner reviews |
| PING_PONG | Both | Rapid alternation |
| SPECIALIST | Single | One agent handles all |
| RED_BLUE | Both | Adversarial propose/attack |

---

*Workflows Index V12.4*
