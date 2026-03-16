# NEXUS V7.5 HIVE MIND - Security Architecture

**Version**: 2.0 (HIVE MIND)
**Date**: 2025-12-03
**Status**: Active

---

## Overview

NEXUS V7.5 implements a **multi-layer defense-in-depth** security architecture to protect the parent codebase while enabling specialized agents to operate within secure sandboxes.

### Design Principles

1. **BLOCK writes to parent code** - Absolute protection
2. **ALLOW reads from parent code** - Agents need context
3. **ISOLATE specialized agents** - Each agent lives in its own sandbox
4. **IMMUTABLE Kernel** - KERNEL.py is sacred

---

## Security Layers

```
+-----------------------------------------------------------------------------+
|                           LAYER 4: INTEGRITY MONITOR                         |
|  IntegrityMonitor - Post-hoc detection of unauthorized changes              |
|  -> KERNEL.py SHA-256 verification at startup                                |
+-----------------------------------------------------------------------------+
                                      ^
+-----------------------------------------------------------------------------+
|                        LAYER 3: MUTATION VALIDATOR                           |
|  MutationValidator - AST-based behavioral analysis of mutation code         |
|  -> Detects dangerous calls (exec, eval, os.system)                          |
|  -> Mode: WARN + CONTINUE (logs but doesn't block)                           |
+-----------------------------------------------------------------------------+
                                      ^
+-----------------------------------------------------------------------------+
|                        LAYER 2: PATH GUARDIAN                                |
|  PathGuardian - Centralized path validation for ALL file operations         |
|  -> Validates zones (Workspace, Agents, Parent)                              |
+-----------------------------------------------------------------------------+
                                      ^
+-----------------------------------------------------------------------------+
|                        LAYER 1: TOOL FIREWALL                                |
|  Bash Blacklist + Git Restrictions - First line of defense                  |
|  -> Blocks dangerous shell commands, git push/commit                         |
+-----------------------------------------------------------------------------+
```

---

## Layer 2: PathGuardian Zones

The filesystem is divided into strict security zones:

| Zone | Path | READ | WRITE | Description |
|------|------|------|-------|-------------|
| **Workspace** | `workspace/` | [OK] | [OK] | General working area |
| **Agents** | `workspace/agents/` | [OK] | [OK] | **NEW V7.5**: Specialized agents home |
| **Memory** | `workspace/memory/` | [OK] | [OK] | **NEW V7.5**: Auto-Memory logs |
| **Evolution** | `GENERATION_ACTIVE/` | [OK] | [OK]* | Evolution sandbox (*only in evolve mode) |
| **Parent** | `core/` | [OK] | [NO] | Parent code - READ ONLY |
| **Prompts** | `prompts/` | [OK] | [NO] | System prompts - READ ONLY |

### Sacred Files (Immutable)

Files that can **NEVER** be written, even in permitted zones:

| File | Reason |
|------|--------|
| `KERNEL.py` | Alignment core |
| `MISSION.md` | HIVE MIND Vision |
| `.env` | Credentials |
| `KERNEL_HASH.txt` | Integrity baseline |

---

## Agent Isolation

In V7.5 HIVE MIND, specialized agents are isolated in their own directories:

```
workspace/agents/
+-- sql_expert/           # Agent 1 Sandbox
|   +-- workspace/        # Agent 1 Working directory
|   +-- BIRTH_CERTIFICATE.json
|   +-- system_prompt.md
+-- vue_frontend/         # Agent 2 Sandbox
    +-- workspace/
    +-- ...
```

Each agent operates within its subdirectory. Cross-agent writing is technically possible within `workspace/` but discouraged by the Swarm protocols.

---

## Red Team Alignment (V7.5 Policy)

In V7.5, we shifted from "Mandatory Blocking" to "Optional Verification" to unblock specialization.

- **Configuration**: `RED_TEAM_MANDATORY=False` (default)
- **Mechanism**: If enabled, runs alignment checks before allowing an agent to be spawned or promoted.
- **Rationale**: Specialized agents (e.g., "SQL Expert") might fail generic "ASI" alignment tests but still be perfectly safe and useful tools.

---

## Layer 1: Tool Firewall (Bash Blacklist)

Dangerous command patterns blocked at the tool level:

| Pattern | Description |
|---------|-------------|
| `../../../` | Deep path traversal |
| `rm -rf ..` | Delete parent directory |
| `git push` | Prevent unauthorized upstream changes |
| `> ../` | Redirect to parent |
| `python ../` | Execute parent code |

---

## Incident Response

If a security violation is detected (e.g., KERNEL modified):

1. **STOP**: System halts immediately via IntegrityMonitor.
2. **ALERT**: User is notified with a critical error.
3. **RESTORE**: User must manually restore `KERNEL.py` from git or backup to resume.

---

## References

- `core/security/path_guardian.py`
- `core/security/integrity_monitor.py`
- `core/security/mutation_validator.py`