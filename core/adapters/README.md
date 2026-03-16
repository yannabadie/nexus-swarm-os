# Adapters

## Synopsis
Bidirectional conversion layer between Swarm TaskAnalysis and HiveMind IndependentAnalysis types. Enables cross-domain usage of analysis structures with fuzzy complexity mapping and domain detection.

## Component Map
| File | Purpose | Key Exports |
|------|---------|-------------|
| `analysis_adapter.py` | TaskAnalysis ↔ IndependentAnalysis converter | `AnalysisAdapter` |
| `__init__.py` | Module exports | `AnalysisAdapter` |

## Key Interfaces

### AnalysisAdapter
Bidirectional adapter between Swarm and HiveMind analysis types.

**Core Methods:**
```python
# HiveMind -> Swarm
to_task_analysis(
    hive: IndependentAnalysis,
    raw_input: str,
    detect_domains: bool = True
) -> TaskAnalysis

# Swarm -> HiveMind
to_independent_analysis(
    swarm: TaskAnalysis,
    agent_id: str,
    reasoning: str = ""
) -> IndependentAnalysis

# Utility converters
complexity_to_string(complexity: TaskComplexity) -> str
string_to_complexity(text: str) -> TaskComplexity
```

**Field Mappings:**

HiveMind -> Swarm (lossy):
- `complexity_assessment` (str) -> `complexity` (TaskComplexity enum via fuzzy match)
- `task_understanding` -> `raw_input`
- `confidence` -> `confidence`
- LOST: `agent_id`, `reasoning`, `required_capabilities`, `potential_risks`

Swarm -> HiveMind (lossy):
- `complexity` (enum) -> `complexity_assessment` (enum.name)
- `raw_input` -> `task_understanding`
- `domains` -> `required_capabilities` (domain_*)
- LOST: `fit_scores`, `detected_keywords`, `requires_*` flags

**Fuzzy Complexity Mapping:**
```python
{
    "trivial", "simple", "easy" -> TaskComplexity.TRIVIAL/SIMPLE
    "moderate", "medium" -> TaskComplexity.MODERATE
    "complex", "difficult" -> TaskComplexity.COMPLEX
    "expert", "advanced", "critical" -> TaskComplexity.EXPERT
}
```

**Domain Detection:**
Detects TaskDomain from text patterns:
- "code", "coding", "programming" -> CODING
- "bug", "debug", "fix" -> DEBUGGING
- "research", "search" -> RESEARCH
- "analyze", "analysis" -> ANALYSIS
- "security" -> SECURITY
- "design", "architect" -> ARCHITECTURE

## Dependencies
- **Internal**: `core.swarm.task_analyzer` (TaskAnalysis, TaskComplexity, TaskDomain)
- **Internal**: `core.hive_mind.types` (IndependentAnalysis)
- **External**: `datetime`

## Integration Points

**Used By:**
- `core.swarm` - Converts HiveMind analysis for Swarm routing
- `core.hive_mind` - Converts Swarm analysis for HiveMind execution

**Use Cases:**
1. SwarmBridge delegation: HiveMind Phase 4 delegates step to Swarm mode
2. Cross-pipeline compatibility: Share analysis between pipelines
3. Complexity estimation: Convert free-form complexity to enum

**Limitations:**
- Conversion is NOT lossless (fields unique to each type are lost)
- Fuzzy matching for complexity/domains may be imprecise
- See `docs/IMPACT_ANALYSIS_V8.2.md` for detailed field mapping

## Version History
- V8.2.0a: Initial implementation (Claude, 2025-12-09)
- Problem Solved: No unified way to convert between TaskAnalysis and IndependentAnalysis
