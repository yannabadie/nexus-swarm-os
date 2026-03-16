# Gemini Deep Think - Prompt Template for NEXUS Analysis

**Purpose**: Structured prompt to minimize hallucinations and maximize actionable advice.
**Usage**: Copy template, fill in [TASK], inject context documents.
**Last Updated**: 2025-12-08

---

## How to Use This Template

### Step 1: Prepare Context Documents

Inject these documents IN ORDER before your question:

1. **CODEBASE_SNAPSHOT.md** (~800 lines) - Ground truth structure
2. **CONSTRAINTS.md** (~200 lines) - Technical constraints
3. **ARCHITECTURE_DECISIONS.md** (~300 lines) - Design rationale
4. **ROADMAP.md** (optional) - Current priorities

### Step 2: Copy Prompt Template

```markdown
# NEXUS V8.0 Analysis Request

## Context Documents Provided
You have been given these reference documents:
1. CODEBASE_SNAPSHOT.md - Exact class/method/enum inventory
2. CONSTRAINTS.md - What you CANNOT suggest
3. ARCHITECTURE_DECISIONS.md - WHY decisions were made

## CRITICAL RULES

### Rule 1: Verify Before Suggesting
Before suggesting ANY code:
- [ ] Class name exists in CODEBASE_SNAPSHOT.md?
- [ ] Method signature matches snapshot?
- [ ] Dependency is in CONSTRAINTS.md "INSTALLED" list?
- [ ] Not in "DOES NOT EXIST" anti-hallucination section?

### Rule 2: Respect Architecture Decisions
- Do NOT suggest alternatives to accepted ADRs
- Do NOT propose dependencies marked as "NOT INSTALLED"
- Do NOT unify structures that ADRs say should remain separate

### Rule 3: Use Exact Names
| CORRECT | WRONG (hallucinations) |
|---------|------------------------|
| TrueHiveMind | HiveMindPipeline |
| HybridSwarmEngine | SwarmEngine |
| IndependentAnalysis | TaskAnalysis (different!) |
| commands.py | command_registry.py |

## Your Task

[DESCRIBE YOUR SPECIFIC QUESTION OR TASK HERE]

## Expected Output Format

For each recommendation, provide:

### Recommendation: [Title]

**Verification Checklist**:
- [ ] Class `X` verified at `file.py:line` in snapshot
- [ ] Method `Y` exists/doesn't exist
- [ ] Dependencies: [list] all in INSTALLED

**Code Location**: `core/path/file.py:line_number`

**Implementation**:
```python
# Exact code with correct class/method names
```

**Risk Assessment**:
- Breaking changes: Yes/No
- Files affected: [list]
- ADR alignment: Complies with ADR-XXX

**Alternative Considered**: [if any]
```

### Step 3: Common Task Templates

---

## Template A: Code Review / Gap Analysis

```markdown
# NEXUS Code Review Request

## Context
[Inject CODEBASE_SNAPSHOT.md, CONSTRAINTS.md, ARCHITECTURE_DECISIONS.md]

## Task
Analyze the current implementation of [COMPONENT] and identify:
1. Gaps between design intent and implementation
2. Missing error handling
3. Performance bottlenecks
4. Security concerns

Focus on: `core/[path]/[file].py`

## Constraints
- Only suggest changes using INSTALLED dependencies
- Respect ADR decisions (especially ADR-001: pure asyncio)
- Reference exact line numbers from snapshot

## Output Format
For each finding:
- Location: file:line
- Issue: [description]
- Severity: LOW/MEDIUM/HIGH/CRITICAL
- Fix: [code snippet with verification]
```

---

## Template B: Implementation Proposal

```markdown
# NEXUS Implementation Proposal Request

## Context
[Inject CODEBASE_SNAPSHOT.md, CONSTRAINTS.md, ARCHITECTURE_DECISIONS.md]

## Task
Propose implementation for: [FEATURE NAME]

Requirements:
- [Requirement 1]
- [Requirement 2]
- [Requirement 3]

## Constraints
- Must use only INSTALLED dependencies
- Must align with existing architecture (see ADRs)
- Must integrate with existing classes (verify in snapshot)

## Questions to Answer
1. Where should this code live? (verify path exists)
2. Which existing classes to extend? (verify they exist)
3. What new classes/methods needed?
4. What tests required?

## Output Format
### Implementation Plan

**New Files**:
- `core/path/new_file.py` - [purpose]

**Modified Files**:
- `core/path/existing.py:line` - [change description]

**Code**:
```python
# With verification comments
# VERIFIED: TrueHiveMind exists at orchestrator.py:75
class NewFeature:
    ...
```

**Integration Points**:
- Hook into `ExistingClass.method()` at line X
```

---

## Template C: Debugging / Root Cause Analysis

```markdown
# NEXUS Debugging Request

## Context
[Inject CODEBASE_SNAPSHOT.md, CONSTRAINTS.md]

## Problem
[Describe the bug/issue]

Error message:
```
[Paste exact error]
```

Reproduction steps:
1. [Step 1]
2. [Step 2]

## Known Information
- File involved: `core/path/file.py`
- Suspected area: [if known]

## Questions
1. What is the root cause?
2. Which code path leads to this error?
3. What is the fix?

## Output Format
### Root Cause Analysis

**Call Stack** (from snapshot):
1. `file1.py:method1()` line X
2. `file2.py:method2()` line Y
3. [error location]

**Root Cause**: [explanation]

**Fix**:
```python
# Location: file.py:line
# Before:
[old code]

# After:
[new code]
```

**Verification**: How to confirm fix works
```

---

## Template D: Architecture Question

```markdown
# NEXUS Architecture Question

## Context
[Inject ARCHITECTURE_DECISIONS.md, CODEBASE_SNAPSHOT.md]

## Question
[Your architecture question]

## Relevant ADRs
- ADR-XXX: [title]
- ADR-YYY: [title]

## Constraints
- Answer must align with existing ADRs
- If suggesting change to ADR, explain trade-offs

## Output Format
### Analysis

**Current State**: [from snapshot/ADRs]

**Options**:
1. Option A: [description]
   - Pros: ...
   - Cons: ...
   - ADR alignment: ...

2. Option B: [description]
   - Pros: ...
   - Cons: ...
   - ADR alignment: ...

**Recommendation**: [with justification]
```

---

## Anti-Hallucination Checklist

Before accepting Gemini's response, verify:

| Check | How to Verify |
|-------|---------------|
| Class names correct? | Search in CODEBASE_SNAPSHOT.md |
| Method signatures match? | Check "Critical Methods" section |
| Dependencies available? | Check CONSTRAINTS.md INSTALLED list |
| File paths exist? | Check "Module Structure" in snapshot |
| Not suggesting forbidden pattern? | Check "DOES NOT EXIST" section |
| Aligns with ADRs? | Cross-reference ARCHITECTURE_DECISIONS.md |

---

## Example: Good vs Bad Response

### BAD Response (Hallucinations)
```
To fix this, modify HiveMindPipeline.execute():
```python
from aiolimiter import AsyncLimiter
limiter = AsyncLimiter(50, 60)
```
```

**Problems**:
- `HiveMindPipeline` doesn't exist (it's `TrueHiveMind`)
- `aiolimiter` not installed (see CONSTRAINTS.md)

### GOOD Response (Verified)
```
To fix this, modify TrueHiveMind.process_task() at orchestrator.py:235:

```python
# VERIFIED: TrueHiveMind at orchestrator.py:75
# VERIFIED: process_task at orchestrator.py:235
# VERIFIED: asyncio.Lock in stdlib (ADR-001 compliant)

async def process_task(self, task: str):
    async with self._rate_lock:  # Pure asyncio, no external deps
        ...
```

**Verification**:
- [x] TrueHiveMind exists: orchestrator.py:75
- [x] process_task exists: orchestrator.py:235
- [x] Uses stdlib only: ADR-001 compliant
```

---

## Quick Reference: Common Corrections

| If Gemini Says | Correct To |
|----------------|------------|
| HiveMindPipeline | TrueHiveMind |
| SwarmEngine | HybridSwarmEngine |
| TaskAnalysis (in hive mind context) | IndependentAnalysis |
| record_async() | record_success() (sync) |
| command_registry.py | commands.py (exists) |
| aiolimiter | asyncio.Lock + custom TokenBucket |
| httpx | subprocess (CLI tools) |
| static_map.py | fsm_handlers.py |

---

*Use this template for every Gemini Deep Think session to ensure high-quality, actionable recommendations.*
