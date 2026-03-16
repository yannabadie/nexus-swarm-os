---
name: swarm-modes
description: NEXUS Swarm Engine collaboration modes. Use when deciding how Gemini and Claude should collaborate on a task.
---

# NEXUS Swarm Engine - Collaboration Modes

## Overview

The Swarm Engine provides 6 collaboration modes for dynamic multi-agent task execution. Mode selection is based on task analysis (complexity, domains, requirements).

## The 6 Collaboration Modes

### 1. PARALLEL - Independent Simultaneous Work

**When to use**:
- Task has independent subtasks
- No dependencies between subtasks
- Can merge results afterward

**Example**:
```
Task: "Analyze code quality and write documentation"
-> PARALLEL
  - Gemini: Code quality analysis
  - Claude: Documentation writing
  -> Merge: Combined report
```

**Characteristics**:
- Fastest mode (true parallelism)
- No agent blocking
- Requires clear subtask division

### 2. SEQUENTIAL - Ordered Execution

**When to use**:
- Output of one step feeds into next
- Clear dependency chain
- Order matters

**Example**:
```
Task: "Design API, then implement it, then write tests"
-> SEQUENTIAL
  1. Gemini: API design
  2. Claude: Implementation
  3. Gemini: Test suite
```

**Characteristics**:
- Linear workflow
- Each step builds on previous
- Clear handoff points

### 3. LEAD_SUPPORT - Primary + Assistant

**When to use**:
- One agent has expertise
- Other agent reviews/assists
- Complex implementation tasks

**Example**:
```
Task: "Refactor orchestration_v7.py (1200 lines)"
-> LEAD_SUPPORT
  - Lead (Claude): Code refactoring
  - Support (Gemini): Code review, suggestions, validation
```

**Characteristics**:
- Lead drives execution
- Support provides quality gates
- Catches errors early

### 4. PING_PONG - Rapid Alternation

**When to use**:
- Iterative refinement needed
- Quick back-and-forth valuable
- Converging on solution

**Example**:
```
Task: "Design optimal database schema"
-> PING_PONG
  - Gemini: Initial schema proposal
  - Claude: Critique + improvements
  - Gemini: Refined schema
  - Claude: Final validation
  -> Convergence in 3-4 turns
```

**Characteristics**:
- High-frequency alternation
- Rapid iteration
- Converges quickly (max 10 turns)

### 5. SPECIALIST - Single Expert

**When to use**:
- Clear domain expertise
- Task fits one agent perfectly
- No collaboration needed

**Example**:
```
Task: "Explain this Python code"
-> SPECIALIST (Claude)
  - Claude handles entirely
  - No Gemini involvement
```

**Characteristics**:
- Most efficient when applicable
- No coordination overhead
- One agent = one output

### 6. RED_BLUE - Adversarial Testing

**When to use**:
- Security critical
- Need edge case discovery
- Validation/verification tasks

**Example**:
```
Task: "Validate InputGuard security"
-> RED_BLUE
  - Red (Gemini): Attack (craft malicious inputs)
  - Blue (Claude): Defend (verify InputGuard blocks)
  -> Multiple rounds until robust
```

**Characteristics**:
- Adversarial relationship
- Finds edge cases
- Improves robustness

## Mode Selection Criteria

### Task Complexity

| Complexity | Preferred Modes |
|------------|----------------|
| TRIVIAL | SPECIALIST |
| SIMPLE | SPECIALIST, SEQUENTIAL |
| MODERATE | PING_PONG, LEAD_SUPPORT |
| COMPLEX | LEAD_SUPPORT, SEQUENTIAL |
| EXPERT | PARALLEL (decompose), LEAD_SUPPORT |

### Task Domains

| Domain | Suggested Mode |
|--------|---------------|
| CODING | LEAD_SUPPORT (one lead, one review) |
| RESEARCH | PARALLEL (split topics) |
| ANALYSIS | PING_PONG (iterative refinement) |
| SECURITY | RED_BLUE (adversarial) |
| ARCHITECTURE | PING_PONG (design iteration) |
| TESTING | PARALLEL (write tests independently) |

## Auto-Routing (V7.5+)

**NEXUS auto-selects mode** based on:
1. Task complexity analysis
2. Domain detection
3. DyLAN agent metrics (performance history)

**Enable auto-routing**:
```python
# .env
SWARM_AUTO_ROUTE=True  # Default: True
```

**Manual override**:
```bash
nexus7> /swarm <mode> <task>
# Example: /swarm ping_pong "Design the API schema"
```

## Negotiation Protocol (V7 Sprint 9)

Agents can **negotiate** the best mode:

```
Claude: "I propose LEAD_SUPPORT with me as lead for this refactoring.
<negotiate>{"proposed_mode": "LEAD_SUPPORT", "my_role": "lead"}</negotiate>"

Gemini: "Agreed, I'll support with security review.
<negotiate>{"accept": true, "my_role": "support"}</negotiate>"

-> Mode selected: LEAD_SUPPORT (Claude lead)
```

**Max negotiation turns**: 4 (then fallback to PING_PONG)

## Performance Optimization

### Cost Optimization (Plan-and-Execute)

**Use SEQUENTIAL with cheap execution**:
```
1. Frontier model (Opus/3-Pro): Create plan
2. Cheap model (Sonnet/Flash): Execute steps
-> 90% cost reduction
```

### Speed Optimization

**Use PARALLEL when possible**:
- 2x speedup vs SEQUENTIAL
- No blocking on agent availability
- Ideal for independent subtasks

## Real NEXUS Examples

### Code Refactoring (P5.1)
```
Task: Decompose orchestration_v7.py God Object
Mode: LEAD_SUPPORT
- Lead (Claude): Extract modules progressively
- Support (Gemini): Review each phase, suggest improvements
Result: 1276 -> 1074 lines, 4 modules, 82 tests
```

### Security Hardening
```
Task: Strengthen InputGuard patterns
Mode: RED_BLUE
- Red (Gemini): Craft prompt injections
- Blue (Claude): Update InputGuard rules
Result: <5% bypass rate (from 12%)
```

### Documentation Generation
```
Task: Document all 125 new modules
Mode: PARALLEL
- Gemini: Document modules A-M
- Claude: Document modules N-Z
Result: Faster completion, merged outputs
```

## Debugging Swarm Issues

**If mode not working well**:
1. Check task analysis: `TaskAnalyzer.analyze(user_input)`
2. Try different mode: `/swarm <different_mode> <task>`
3. Check agent metrics: `DyLAN scores` in blackboard
4. Manual decomposition: Break task into smaller pieces

**Swarm logs**:
```bash
# Check swarm session
cat workspace/.nexus/blackboard.json | jq '.swarm_session'

# Event logs
cat workspace/logs/events_YYYYMMDD.jsonl | grep swarm
```

## Best Practices

[OK] **Do**:
- Let auto-routing choose when unsure
- Use SPECIALIST for clear single-agent tasks
- Use RED_BLUE for security/validation
- Trust the negotiation process

[NO] **Don't**:
- Force PARALLEL on dependent subtasks
- Use SPECIALIST for complex multi-domain tasks
- Override auto-routing without good reason
- Expect instant convergence in PING_PONG (takes 3-5 turns)

## Mode Selection Cheat Sheet

```
Simple single-domain task -> SPECIALIST
Complex coding task -> LEAD_SUPPORT
Independent subtasks -> PARALLEL
Dependent steps -> SEQUENTIAL
Iterative design -> PING_PONG
Security/validation -> RED_BLUE
```

**When in doubt**: Let auto-routing decide [OK]
