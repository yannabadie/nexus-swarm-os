# NEXUS V8.0 - Technical Constraints

**Purpose**: Reference document for Gemini Deep Think to avoid invalid suggestions.
**Last Updated**: 2025-12-08
**Version**: 1.0

---

## Python Environment

| Constraint | Value | Notes |
|------------|-------|-------|
| Python Version | 3.13+ | Use modern features (match/case, type unions) |
| Async Model | asyncio stdlib | NO external async frameworks |
| Type Checking | Runtime via Pydantic | Static typing for IDE only |

**Features OK to use**:
- `contextvars` (thread-safe context)
- `match/case` (pattern matching)
- `type X = Y` (type aliases)
- `list[str]` (generic builtins)
- `X | None` (union syntax)

**Features to AVOID**:
- Python 3.14 preview features
- `async generators` in critical paths (debugging harder)

---

## Dependencies

### INSTALLED (requirements.txt)

```
# Core
python-dotenv>=1.0.0      # .env loading
pydantic>=2.0.0           # Validation, settings
rich>=13.7.0              # Console output, tables
prompt-toolkit>=3.0.43    # Interactive REPL
tiktoken>=0.5.2           # Token counting

# RAG (Phase 10)
bm25s>=0.2.0              # Sparse retrieval
PyStemmer>=2.2.0          # Stemming
lancedb>=0.4.0            # Vector DB (optional)
sentence-transformers>=2.2.0  # Embeddings (optional)

# Testing
pytest>=7.0.0
pytest-cov>=4.0.0
pytest-asyncio>=0.21.0
```

### NOT INSTALLED - Do NOT Suggest

| Library | Why NOT | Alternative |
|---------|---------|-------------|
| `aiolimiter` | External dep | Custom TokenBucket (asyncio.Lock) |
| `httpx` | Not needed | subprocess for CLI calls |
| `tenacity` | Overkill | Simple while loop + backoff |
| `redis` | No external services | JSON files, LanceDB |
| `celery` | No task queue | asyncio.gather() |
| `fastapi` | CLI-first, no server | prompt-toolkit REPL |
| `sqlalchemy` | No SQL database | LanceDB for vectors |
| `langchain` | Too heavy | Custom RAG pipeline |
| `llama-index` | Too heavy | Custom implementation |

### System Tools (External)

```bash
# Required - installed separately
gemini    # Google AI CLI (gemini chat, gemini code)
claude    # Anthropic CLI (claude chat)

# Optional
git       # Version control (used by tools)
```

---

## Architecture Invariants

### 1. Class Names (EXACT)

| Correct Name | WRONG Names (hallucinations) |
|--------------|------------------------------|
| `TrueHiveMind` | ~~HiveMindPipeline~~, ~~HiveMindOrchestrator~~ |
| `HybridSwarmEngine` | ~~SwarmEngine~~, ~~SwarmOrchestrator~~ |
| `StagnationDetector` | ~~StagnationMonitor~~, ~~LoopDetector~~ |
| `StrategyBlacklist` | ~~FailedStrategyStore~~, ~~BlacklistManager~~ |
| `ProjectMemory` | ~~RAGMemory~~, ~~SemanticMemory~~ |
| `SuccessMemory` | ~~MemoryStore~~, ~~SuccessStore~~ |

### 2. Dataclass Structures (NOT Interchangeable)

```python
# HIVE MIND domain (core/hive_mind/types.py)
@dataclass
class IndependentAnalysis:
    agent_id: str
    task_understanding: str
    complexity_assessment: str  # STRING, not enum!
    proposed_approach: str
    key_challenges: List[str]
    confidence: float

# SWARM domain (core/swarm/task_analyzer.py)
@dataclass
class TaskAnalysis:
    complexity: TaskComplexity  # ENUM
    domains: List[TaskDomain]
    primary_domain: TaskDomain
    reasoning: str
    raw_input: str
```

**CRITICAL**: These are DIFFERENT structures. Adapter required for cross-domain use.

### 3. Protocol Split

| Agent | Protocol | Format |
|-------|----------|--------|
| Gemini | JSON strict | `{"type": "TALK", "content": "..."}` |
| Claude | Hybrid | Natural language + `<tool_use>` XML |

**Never suggest**:
- Claude using JSON protocol
- Gemini using XML tools
- Unified protocol (breaks existing parsing)

### 4. Existing Modules (Do NOT Recreate)

| What Exists | Location | Do NOT Create |
|-------------|----------|---------------|
| Command routing | `core/interface/commands.py` | ~~command_registry.py~~ |
| Agent registry | `core/hive_mind/agent_registry.py` | (for spawned agents only) |
| Memory boost | `core/swarm/mode_selector.py:614` | `_apply_memory_boost()` exists |
| Session modes | `core/swarm/session_manager.py:46` | `SessionMode.EPHEMERAL` exists |

---

## File System Conventions

### Workspace Structure

```
workspace/
+-- .nexus/
|   +-- blackboard.json      # Persistent state (DO NOT encrypt yet)
|   +-- dylan_metrics.json   # Agent performance
|   +-- success_memory.json  # Mode recommendations
+-- agents/                  # Spawned agent definitions
+-- logs/                    # Structured logs (JSONL)
+-- memory/                  # RAG indexes
```

### File Naming

- Python: `snake_case.py`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Test files: `test_*.py`

---

## Performance Constraints

| Metric | Target | Current |
|--------|--------|---------|
| TRIVIAL task latency | <2s | ~45s (needs EPHEMERAL) |
| COMPLEX task latency | <30s | ~45s |
| Memory usage | <500MB | ~200MB |
| Test pass rate | 99%+ | 98.5% |

---

## Security Constraints

### Allowed

- Read any file in workspace
- Execute approved tools (11 tools)
- Spawn child agents (sandboxed)

### Forbidden

- Network calls outside LLM APIs
- File writes outside workspace
- Shell commands without sandbox
- Credential storage in plaintext

---

## Testing Constraints

### Real LLM Tests

```python
# These tests call REAL APIs - need keys
tests/test_llm_context_isolation.py  # 16 flaky tests

# Environment variable to skip
SKIP_LLM_TESTS=1 pytest tests/
```

### Mocking

- `conftest.py` provides `MockDriver`, `MockConfig`
- Always mock LLM calls in unit tests
- Integration tests may use real APIs (mark with `@pytest.mark.integration`)

---

## Integration Points

### CLI Tools (subprocess)

```python
# Gemini CLI
subprocess.run(["gemini", "chat", "-m", model, prompt])

# Claude CLI
subprocess.run(["claude", "-p", prompt, "--output-format", "json"])
```

### No HTTP APIs

NEXUS uses CLI tools, NOT HTTP APIs:
- [NO] `requests.post("https://api.anthropic.com/...")`
- [OK] `subprocess.run(["claude", ...])`

**Exception**: `anthropic` and `google-generativeai` SDKs for specific features.

---

*This document is the source of truth for technical constraints. Update when adding dependencies or changing architecture.*
