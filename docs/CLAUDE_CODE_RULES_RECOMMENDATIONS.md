# Claude Code Rules Recommendations for NEXUS

**Date**: 2026-02-18
**Purpose**: Best practices and recommended rules for NEXUS multi-agent orchestration project

---

## 📚 Research Sources

This document synthesizes best practices from:
- [Anthropic Claude Code Official Docs](https://www.anthropic.com/engineering/claude-code-best-practices)
- [Claude Code Best Practices Guide](https://code.claude.com/docs/en/best-practices)
- [Writing a Good CLAUDE.md (HumanLayer)](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Claude Code Showcase Repository](https://github.com/ChrisWiles/claude-code-showcase)
- [Anthropic Claude Code Rules Gist](https://gist.github.com/markomitranic/26dfcf38c5602410ef4c5c81ba27cce1)
- [Azure AI Agent Design Patterns](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns)
- [Deloitte AI Agent Orchestration 2026](https://www.deloitte.com/us/en/insights/industry/technology/technology-media-and-telecom-predictions/2026/ai-agent-orchestration.html)

---

## 🎯 Critical Rule: Verification Protocol

**MANDATORY for NEXUS**: When claiming to have fixed/resolved/completed something, **always verify**:

```markdown
## [warning]️ CRITICAL RULE: Always Verify Your Claims

When you claim to have **fixed**, **resolved**, **completed**, or **verified** something, you MUST:

1. **Execute verification commands** - Don't assume, verify
2. **Check actual output** - Read logs, test results, CI status
3. **Confirm success criteria** - All tests pass? CI green? No errors?
4. **Document evidence** - Show the proof (logs, output, status)

Examples:
- [NO] "I fixed the CI by adding requirements.txt"
- [OK] "Added requirements.txt -> gh run view shows 'success' [OK]"
```

---

## 🏗️ Recommended CLAUDE.md Structure for NEXUS

### 1. Keep It Concise (150-200 Instructions Max)

**Problem**: Frontier LLMs can follow ~150-200 instructions with reasonable consistency.
**Solution**: Ruthlessly prune CLAUDE.md. If Claude already does it correctly, remove the instruction.

**Current NEXUS CLAUDE.md**: ~500 lines -> **Recommended**: < 300 lines

### 2. Essential Sections

```markdown
# NEXUS V12.4 - Claude Instructions

## 🧠 Project Purpose
Multi-agent orchestration platform for collaborative AI intelligence.

## 🔧 Tech Stack
- Python 3.11+
- Pydantic V2 (strict validation)
- FastAPI + Redis + LanceDB
- pytest (2500+ tests)

## 📁 Architecture Map
core/
+-- orchestration_v7.py     # Main FSM orchestrator
+-- hive_mind/              # 7-phase pipeline
+-- swarm/                  # 6 collaboration modes
+-- drivers/                # Gemini + Claude SDK
+-- memory/                 # RAG + SuccessMemory

## 🚀 Essential Commands
pytest tests/                    # Run all tests
pytest tests/test_*.py -v       # Run specific test
ruff check core/ tests/         # Lint
mypy core/memory/types.py       # Type check
git commit -m "type(scope): msg" # Commit format

## [warning]️ Critical Rules
1. **Always verify claims** - Run tests, check CI status
2. **Test before committing** - pytest must pass
3. **Never skip hooks** - Pre-commit checks are mandatory
4. **Verify imports** - Run `python -c "import module"` after creating
5. **Check CI status** - `gh run list --limit 1` after push

## 🧬 Code Patterns
- Composition over inheritance (TaskRouter, StateHandler pattern)
- Dataclasses with frozen=True for immutability
- Pydantic for all message validation
- Event sourcing for FSM transitions
- OTel spans for instrumentation

## 🚫 Anti-Patterns (DO NOT)
- [NO] Modify orchestration_v7.py without reading adjacent modules first
- [NO] Add dependencies without updating both requirements.txt AND pyproject.toml
- [NO] Claim "CI fixed" without running `gh run view` to verify
- [NO] Use bare except: (always specify exception types)
- [NO] Import legacy CLI drivers (use SDK drivers from core/drivers/)
```

---

## 🎣 Hooks Configuration (.claude/settings.json)

### Recommended Hooks for NEXUS

```json
{
  "hooks": {
    "PreToolUse": {
      "Bash": {
        "command": [
          "bash",
          "-c",
          "if [[ \"$CLAUDE_TOOL_ARGS\" == *'git push'* ]] && git branch --show-current | grep -q '^main\\|^NX$'; then echo 'ERROR: Cannot push to protected branch'; exit 2; fi"
        ],
        "description": "Block pushes to main/NX branches"
      }
    },
    "PostToolUse": {
      "Edit": {
        "command": ["ruff", "format", "$CLAUDE_FILE_PATH"],
        "description": "Auto-format Python files after edits"
      },
      "Write": {
        "command": ["python", "-m", "py_compile", "$CLAUDE_FILE_PATH"],
        "description": "Validate Python syntax after file creation"
      }
    },
    "UserPromptSubmit": {
      "command": [
        "bash",
        "-c",
        "echo '💡 Hint: Run /test to validate changes before committing'"
      ],
      "description": "Remind to run tests"
    }
  }
}
```

**Exit Code Meanings**:
- `0` = Success (continue)
- `2` = Blocking error (PreToolUse only - stops execution)
- Other = Non-blocking error (logs warning)

---

## 🛠️ Skills Architecture

### When to Use Skills vs CLAUDE.md

| Use CLAUDE.md | Use Skills |
|---------------|------------|
| Always-on context (stack, commands) | Situational patterns (testing, deployment) |
| Project structure | Domain knowledge (API patterns, DB schemas) |
| Critical rules | Reusable templates |
| < 300 lines | Can be verbose |

### Recommended Skills for NEXUS

**1. `/test-strategy` Skill**
```markdown
---
name: test-strategy
description: NEXUS testing patterns. Use when writing tests or debugging failures.
---

# NEXUS Testing Strategy

## Test File Naming
- `test_*.py` for unit tests
- `test_*_integration.py` for integration tests
- Mirrors module structure: `core/memory/rag.py` -> `tests/test_memory_rag.py`

## Fixtures Pattern
Use module-level fixtures from conftest.py:
- @pytest.fixture(scope="session") for expensive setups
- @pytest.fixture(scope="function") for isolation

## Assertion Style
```python
assert result.status == "success", f"Expected success, got {result.status}"
```

## Coverage Target
40% minimum (enforced by CI)
```

**2. `/commit-format` Skill**
```markdown
---
name: commit-format
description: NEXUS commit message conventions. Use when creating commits.
---

# NEXUS Commit Format

## Structure
```
type(scope): subject

body (optional)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

## Types
- feat: New feature
- fix: Bug fix
- refactor: Code restructuring
- test: Test additions
- docs: Documentation
- chore: Maintenance

## Examples
```
feat(P5.1-Phase3): extract ResultHandler from orchestrator (206 LOC, 22 tests)
fix(ci): add email-validator dependency for pydantic EmailStr
docs(P5.1): finalize session document with Phases 6-7 completion
```
```

---

## 🔐 Security Rules

Add to CLAUDE.md:

```markdown
## 🔐 Security Rules (Non-Negotiable)

1. **Never commit secrets** - Check for API keys, tokens, passwords before committing
2. **KERNEL integrity** - Never modify KERNEL.py or KERNEL_HASH.txt
3. **Sandbox enforcement** - All bash execution must respect NEXUS_FF_SANDBOX_REQUIRED
4. **Input validation** - All user input goes through InputGuard
5. **Fail-closed** - On security errors, exit(1) immediately
```

---

## 📊 Multi-Agent Orchestration Best Practices (2026 Research)

Based on latest industry research:

### 1. Design Patterns to Implement

| Pattern | NEXUS Status | Recommendation |
|---------|--------------|----------------|
| **Swarm (All-to-All)** | [OK] Implemented (6 modes) | Keep current approach |
| **Plan-and-Execute** | [OK] HiveMind Phase 3 | Use for cost optimization (90% savings) |
| **Sequential Workflows** | [OK] SEQUENTIAL mode | Already optimal |
| **Human-in-the-Loop** | [warning]️ Partial (approval prompts) | Add HITL dashboard |

### 2. Model Context Protocol (MCP) Integration

**Status**: NEXUS has MCP client (`core/mcp/client.py`)
**Recommendation**: Add MCP servers for:
- GitHub (issue/PR workflows)
- Slack (notifications)
- PostgreSQL (schema awareness for CEREBRO)

### 3. Observability & Telemetry

**Current**: OTel spans, event sourcing, FSM snapshots [OK]
**Add**:
- Agent performance dashboards
- Cost tracking per collaboration mode
- Failure analysis automation

### 4. Agent Lifecycle Management

**Best Practice (2026)**: Readiness assessments, complete lifecycle management, effective governance.

**NEXUS Enhancement**:
```markdown
## Agent Lifecycle Rules

1. **Spawning**: `/spawn` or EVOLUTION_BRAINSTORM (already implemented)
2. **Monitoring**: Track task completion rate, token usage, error frequency
3. **Retirement**: Archive underperforming agents to workspace/agents/archive/
4. **Governance**: Log all agent decisions to event sourcing (already done)
```

---

## 🎯 Action Items for NEXUS

### Immediate (Priority 0)

1. [OK] **Add verification rule to CLAUDE.md** (DONE - committed 70ebe85)
2. ⏳ **Trim CLAUDE.md to < 300 lines** (currently ~500 lines)
3. ⏳ **Create essential hooks** (.claude/settings.json)
   - PreToolUse: Block protected branch pushes
   - PostToolUse: Auto-format, syntax validation
   - UserPromptSubmit: Test reminder

### Short-term (Sprint)

4. ⏳ **Create core skills**:
   - `/test-strategy` (testing patterns)
   - `/commit-format` (commit conventions)
   - `/swarm-mode` (when to use which mode)
   - `/debug-ci` (CI troubleshooting)

5. ⏳ **Add MCP servers**:
   - GitHub (gh CLI is already used, formalize)
   - Notion (for documentation)
   - Hugging Face (for model research - already configured!)

### Medium-term (Epic)

6. ⏳ **Agent performance dashboard** (integrate with CEREBRO)
7. ⏳ **Cost optimization** (track spend per collaboration mode)
8. ⏳ **HITL interface** (approval workflow UI)

---

## 📖 Key Learnings from Research

### From Industry (2026 State-of-the-Art)

1. **Swarm success rates**: Multi-agent collaboration shows up to **70% higher success** on complex goals vs single agents
2. **Cost optimization**: Plan-and-Execute pattern can reduce costs by **90%** (frontier model plans, cheap models execute)
3. **Governance**: Explainability and audit trails are table stakes for enterprise deployment
4. **MCP adoption**: Linux Foundation backing ensures MCP is the emerging standard

### From Claude Code Community

1. **Instruction limit**: ~150-200 instructions is the practical ceiling before quality degrades
2. **Hooks are critical**: Automated quality gates prevent 80% of common errors
3. **Skills > Long CLAUDE.md**: Reusable skills scale better than monolithic instructions
4. **Verification culture**: "Trust but verify" - always check CI, tests, imports

---

## 🔗 References

### Official Documentation
- [Claude Code Best Practices](https://code.claude.com/docs/en/best-practices)
- [Azure AI Agent Patterns](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns)
- [Anthropic Claude Code GitHub](https://github.com/anthropics/claude-code)

### Industry Research (2026)
- [Deloitte: AI Agent Orchestration](https://www.deloitte.com/us/en/insights/industry/technology/technology-media-and-telecom-predictions/2026/ai-agent-orchestration.html)
- [Multi-Agent AI Systems Guide](https://neomanex.com/posts/multi-agent-ai-systems-orchestration)
- [8 Best Multi-Agent Frameworks 2026](https://www.multimodal.dev/post/best-multi-agent-ai-frameworks)

### Community Best Practices
- [Claude Code Showcase](https://github.com/ChrisWiles/claude-code-showcase)
- [Writing a Good CLAUDE.md](https://www.humanlayer.dev/blog/writing-a-good-claude-md)
- [Awesome Claude Code](https://github.com/hesreallyhim/awesome-claude-code)

---

**Next Steps**: Implement Priority 0 action items (trim CLAUDE.md, create hooks) before continuing with P5.2+ epics.
