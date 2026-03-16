# Reasoning Module

## Synopsis
The Reasoning module is a placeholder for advanced reasoning pattern implementations including Graph of Thought (GoT), Chain of Thought (CoT), and Tree of Thought (ToT). Currently in a lazy-loading state where GoT components are optional and loaded only when available, preventing system blocking if not implemented.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `__init__.py` | Module initialization with optional lazy loading of GoT | `GOT_AVAILABLE` (flag), optionally `GraphOfThought`, `ThoughtNode`, `ThoughtGraph`, `ThoughtStatus`, `ThoughtType` |

## Key Interfaces

### Lazy Loading System

**`GOT_AVAILABLE: bool`**
- Global flag indicating whether Graph of Thought implementation exists
- Currently `False` - implementations pending
- Consumers should check this flag before attempting to use GoT

### Optional Components (Not Yet Implemented)

**`GraphOfThought`** (planned)
- Non-linear exploration with branching and merging paths
- Requires `core/reasoning/graph_of_thought.py` to be implemented

**`ThoughtNode`** (planned)
- Individual thought node in the reasoning graph

**`ThoughtGraph`** (planned)
- Graph structure for thought exploration

**`ThoughtStatus`** (planned)
- Enum for thought node status (active, explored, pruned, etc.)

**`ThoughtType`** (planned)
- Enum for thought types (hypothesis, observation, conclusion, etc.)

### Planned Reasoning Patterns

1. **Graph of Thought (GoT)**: Non-linear exploration with branching and merging
2. **Chain of Thought (CoT)**: Linear step-by-step reasoning
3. **Tree of Thought (ToT)**: Tree-based exploration with pruning

## Dependencies & Integration

### Internal Dependencies
- None currently (lazy loading prevents hard dependencies)

### Integration Points
- **HybridSwarmEngine**: Intended consumer of GoT implementation
- **Lazy Loading Pattern**: System continues functioning without GoT implementation

### Usage Pattern (When Implemented)
```python
from core.intelligence.reasoning import GOT_AVAILABLE

if GOT_AVAILABLE:
    from core.intelligence.reasoning import GraphOfThought, ThoughtNode
    # Use GoT reasoning
    graph = GraphOfThought()
else:
    # Fallback to simpler reasoning patterns
    pass
```

### Design Notes
- **Lazy Loading**: Prevents system blocking if GoT not implemented
- **Optional Enhancement**: GoT is a future enhancement, not required for core functionality
- **Graceful Degradation**: Import errors caught and handled with `None` assignments
- **Export Pattern**: `__all__` changes based on successful imports

## V12.4 COGNITIVE BOOST Additions

V12.4 implements the previously-planned reasoning components and adds quality scoring:

| File | Purpose | Key Exports |
|------|---------|-------------|
| `graph_of_thought.py` | Graph-based reasoning with DAG thought exploration supporting sequential chains, parallel exploration, decision trees, and custom DAG structures; decomposes problems, executes thoughts, and aggregates results | `GraphOfThought`, `ThoughtNode`, `ThoughtGraph` |
| `reasoning_quality_scorer.py` | Scores and tracks agent reasoning quality across depth, coherence, completeness, and confidence calibration dimensions; builds per-agent profiles for routing and evolution decisions | `get_quality_scorer`, `ReasoningQualityScorer` |
| `thought_evaluator.py` | Evaluates individual thoughts and reasoning paths for quality scoring, redundancy detection between thoughts, path comparison/ranking, and confidence calibration | `get_thought_evaluator`, `ThoughtEvaluator` |
