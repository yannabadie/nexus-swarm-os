# NEXUS Claude Code Subagents

This directory contains Claude Code subagent configurations for autonomous development,
debugging, and documentation of the NEXUS V12.4 multi-agent orchestrator.

## Quick Start

```bash
# Available slash commands:
/dev "implement feature X"     # Development automation
/debug                         # Debug failing tests
/docs audit                    # Audit documentation
/test                          # Run test suite
/review                        # Code review
```

## Directory Structure

```
.claude/
+-- agents/                    # Subagent definitions
|   +-- nexus-system-auditor.md  # Full codebase documentation (opus)
|   +-- dev-automator.md         # Development automation (opus)
|   +-- debugger.md              # Test debugging (sonnet)
|   +-- doc-writer.md            # Documentation agent (opus)
+-- commands/                  # Slash commands
|   +-- dev.md                 # /dev - Development automation
|   +-- debug.md               # /debug - Test debugging
|   +-- docs.md                # /docs - Documentation
|   +-- test.md                # /test - Test runner
|   +-- review.md              # /review - Code review
+-- hooks/                     # Automation hooks (Python, cross-platform)
|   +-- session_start.py       # Session initialization
|   +-- post_test.py           # Post-test summary
+-- settings.json              # Claude Code configuration
+-- settings.local.json        # Local overrides (git-ignored)
+-- README.md                  # This file
```

## Subagents

### NEXUS System Auditor (`nexus-system-auditor`)
Full codebase documentation and architectural auditing agent.

**Model**: opus (complex multi-file operations)

**Capabilities**:
- Bottom-up README generation for all modules
- Architecture documentation (dependency graphs, workflows)
- Blind spot audit (strengths, weaknesses, security)
- Mandatory Write + Verify loop

### Development Automator (`/dev`)
Autonomous feature implementation with test-driven development workflow.

**Model**: opus (complex implementations)

**Usage**:
```bash
/dev "Add caching to MemoryService"
/dev refactor core/orchestration_v7.py
```

**Capabilities**:
- Feature implementation with tests
- Code refactoring with validation
- NEXUS coding standards enforcement
- Mandatory Edit + Verify loop

### Debugger (`/debug`)
Diagnoses test failures and iteratively fixes issues.

**Model**: sonnet (fast iteration)

**Usage**:
```bash
/debug                          # Fix all failing tests
/debug tests/core/swarm/        # Debug specific module
/debug ImportError              # Debug error type
```

**Capabilities**:
- Test failure categorization
- NEXUS-specific error pattern database
- Root cause analysis
- Minimal fix implementation

### Documentation Writer (`/docs`)
Generates and maintains documentation.

**Model**: opus (comprehensive docs)

**Usage**:
```bash
/docs audit                     # Full documentation audit
/docs generate core/swarm       # Generate module README
/docs fix-versions              # Update V8.x -> V12.4
```

**Capabilities**:
- Module README generation
- Version synchronization
- Docstring generation
- Mandatory Write + Verify loop

## Commands

| Command | Description | Agent |
|---------|-------------|-------|
| `/dev` | Implement features, refactor code | dev-automator (opus) |
| `/debug` | Diagnose and fix test failures | debugger (sonnet) |
| `/docs` | Generate/update documentation | doc-writer (opus) |
| `/test` | Run pytest with analysis | - |
| `/review` | Code review for quality/security | - |

## Key Design Decisions

### 1. Explicit Tool Usage
All agents that write files have explicit instructions:
```
YOU MUST USE THE Write/Edit TOOL TO MODIFY FILES.
Natural language descriptions do NOT create files.
```

### 2. Mandatory Verification
After every Write/Edit operation:
```
Read(file_path="path/to/file")
# Confirm: "Verified: changes applied"
```

### 3. Model Selection
- **opus**: Complex multi-file operations (dev, docs, auditor)
- **sonnet**: Fast iteration, read-heavy tasks (debugger)

### 4. Cross-Platform Hooks
Hooks are Python scripts (not bash) for Windows/Linux/macOS compatibility.

## NEXUS V12.4 Architecture Reference

These agents are designed for NEXUS V12.4 "COGNITIVE BOOST":

**Orchestration Layers**:
- **FSM**: 12 states in `core/fsm/states.py`
- **HiveMind**: 7 phases in `core/hive_mind/`
- **Swarm**: 6 collaboration modes in `core/swarm/`

**Key Files**:
- Entry: `nexus7.py`
- Orchestrator: `core/orchestration_v7.py`
- HiveMind: `core/hive_mind/true_hive_mind.py`
- Swarm: `core/swarm/hybrid_swarm_engine.py`
- Memory: `core/memory/project_memory.py`
- Synapse: `core/synapse/messages.py`

## Usage Examples

### Implement a New Feature
```bash
/dev "Add rate limiting to API endpoints"
# Agent will:
# 1. Search for existing rate limit patterns
# 2. Plan implementation with TodoWrite
# 3. Write tests first
# 4. Implement feature with Edit tool
# 5. Verify each change with Read tool
# 6. Validate with full test suite
```

### Fix Failing Tests
```bash
/debug
# Agent will:
# 1. Run pytest to identify failures
# 2. Categorize by error type
# 3. Trace root cause
# 4. Apply fix with Edit tool
# 5. Verify fix with Read tool
# 6. Re-run until green
```

### Generate Documentation
```bash
/docs audit
# Returns: gaps, version mismatches, priorities

/docs generate core/governance
# Agent will:
# 1. Analyze module with Glob/Grep/Read
# 2. Write README.md with Write tool
# 3. Verify with Read tool
# 4. Report: "[OK] core/governance/README.md - X lines verified"
```

## Troubleshooting

**Commands not found?**
- Ensure you're in the NEXUS directory
- Check `.claude/commands/` exists

**Hooks not running?**
- Check Python is available: `python --version`
- Check `settings.json` hook configuration

**Agent not writing files?**
- Agents must use Write/Edit tools explicitly
- Check agent has verification step
- Consider using opus model for complex tasks

**Tests failing?**
- Run `/debug` for automated diagnosis
- Check `tests/conftest.py` for fixture issues
