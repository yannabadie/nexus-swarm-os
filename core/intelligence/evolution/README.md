# NEXUS Evolution Module

## Synopsis

The **evolution** module enables NEXUS self-improvement through emergent mutations. Agents (Gemini + Claude) collaboratively propose code modifications via symbiotic debate, which are then validated through a 5-tier validation pipeline before potential promotion. The module tracks lineage, manages evolution rate limits, and ensures safe self-modification.

## Architecture

```
+-------------------------------------------------------------------------+
|                      EVOLUTION PIPELINE                                  |
+-------------------------------------------------------------------------+
|                                                                          |
|  +-----------------------------------------------------------------+    |
|  |                   Symbiotic Debate                               |    |
|  |               Gemini + Claude Brainstorm                         |    |
|  |              (30 turns max in FSM state)                         |    |
|  +---------------------------+-------------------------------------+    |
|                              |                                           |
|                              v                                           |
|  +-----------------------------------------------------------------+    |
|  |                   MutationProposal                               |    |
|  |              JSON patches from emergent debate                   |    |
|  +---------------------------+-------------------------------------+    |
|                              |                                           |
|                              v                                           |
|  +-----------------------------------------------------------------+    |
|  |                5-Tier Validation Pipeline                        |    |
|  +-----------------------------------------------------------------+    |
|  |  Tier 1: Syntax     | Python AST parsing, JSON validation       |    |
|  |  Tier 2: Import     | All imports resolve                       |    |
|  |  Tier 3: Smoke      | Basic functionality test                  |    |
|  |  Tier 4: Benchmark  | Performance comparison (parallel)         |    |
|  |  Tier 5: RedTeam    | Security analysis by agents               |    |
|  +---------------------------+-------------------------------------+    |
|                              |                                           |
|              +---------------+---------------+                          |
|              v               v               v                          |
|        +----------+   +----------+   +--------------+                  |
|        | PROMOTE  |   | ARCHIVE  |   | USER REVIEW  |                  |
|        | (auto)   |   | (failed) |   | (borderline) |                  |
|        +----------+   +----------+   +--------------+                  |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Purpose | Key Exports |
|------|---------|-------------|
| `manager.py` | Central evolution orchestrator | `EvolutionManager` |
| `models.py` | Dataclasses for evolution ops | `MutationProposal`, `EvolutionResult` |
| `lineage.py` | LINEAGE.json ancestry tracking | `load_lineage`, `add_child`, `get_ancestry` |
| `evaluator.py` | Benchmark execution | `run_benchmarks`, `compare_to_parent` |
| `validator.py` | Legacy validation | `ChildValidator`, `ValidationResult` |
| `tiered_validator.py` | 5-tier fast-fail validation | `TieredValidator`, `ValidationTier` |
| `rate_limiter.py` | Evolution frequency control | `RateLimiter` |
| `mutation_parser.py` | JSON patch parsing | `MutationParser` |
| `service.py` | Service layer (V9.1) | `EvolutionService` |
| `phases/` | Individual phase implementations | Phase handlers |

## Key Interfaces

### EvolutionManager
```python
class EvolutionManager:
    """Central orchestrator for evolution operations."""

    async def evolve(
        self,
        trigger: EvolutionTrigger,
        context: EvolutionContext
    ) -> EvolutionResult

    async def specialize(
        self,
        mission: str,
        base_version: str
    ) -> SpecializationResult

    def get_evolution_status(self) -> EvolutionStatus
```

### TieredValidator (V7 Sprint 2)
```python
class TieredValidator:
    """Fast-fail validation with parallel benchmarks."""

    async def validate(
        self,
        mutation: MutationProposal,
        context: ValidationContext
    ) -> TieredValidationResult

    def get_tier_status(self) -> Dict[ValidationTier, TierResult]

class ValidationTier(Enum):
    SYNTAX = 1      # AST parsing
    IMPORT = 2      # Import resolution
    SMOKE = 3       # Basic functionality
    BENCHMARK = 4   # Performance comparison
    REDTEAM = 5     # Security analysis
```

### Lineage Tracking
```python
# Load lineage tree
lineage = load_lineage()

# Add new child
add_child(
    parent_id="nexus-v12.4",
    child_id="nexus-v12.5-security-specialist",
    mutation=mutation_proposal,
    validation_result=validation_result
)

# Get ancestry
ancestry = get_ancestry("nexus-v12.5-security-specialist")
# Returns: ["nexus-v12.4", "nexus-v12.3", ...]
```

### Models
```python
@dataclass
class MutationProposal:
    """Proposed code mutation from debate."""
    target_file: str
    patches: List[JSONPatch]
    rationale: str
    expected_improvement: str
    risk_assessment: str

@dataclass
class EvolutionResult:
    """Result of evolution attempt."""
    status: EvolutionStatus  # SUCCESS, FAILED, PENDING_REVIEW
    child_id: Optional[str]
    validation_result: TieredValidationResult
    lineage_entry: Optional[LineageEntry]
```

## Evolution Flow

1. **Trigger**: User `/evolve` or automatic (performance plateau detected)
2. **Brainstorm**: Agents enter `EVOLUTION_BRAINSTORM` FSM state (30 turns max)
3. **Proposal**: Extract JSON patches from debate consensus
4. **Validate**: Run through 5-tier validation (fast-fail)
5. **Decide**: Auto-promote, archive, or request user review
6. **Record**: Update LINEAGE.json with result

## Safety Gates

```python
class SafetyGate(Enum):
    KERNEL_IMMUTABLE = "kernel_immutable"    # Cannot modify KERNEL.py
    PARENT_PROTECTED = "parent_protected"    # Cannot modify parent code
    RATE_LIMITED = "rate_limited"            # Max evolutions per day
    USER_APPROVAL = "user_approval"          # Requires human review
```

## Auto-Promotion Criteria

```python
class AutoPromotionDecision(Enum):
    PROMOTE = "promote"          # All tiers passed, performance improved
    ARCHIVE = "archive"          # Validation failed
    USER_REVIEW = "user_review"  # Borderline: passed but no improvement
```

## Rate Limiting

```python
# Default limits
MAX_EVOLUTIONS_PER_HOUR = 2
MAX_EVOLUTIONS_PER_DAY = 10
COOLDOWN_AFTER_FAILURE = 3600  # 1 hour
```

## Dependencies

### Internal
- `core.fsm` - EVOLUTION_BRAINSTORM state
- `core.drivers` - Agent invocation for debate
- `core.security` - MutationValidator

### External
- `ast` - Python AST for syntax validation
- `json` - JSON patch parsing
- Standard library

## V12.4 COGNITIVE BOOST Additions

| File | Purpose | Key Exports |
|------|---------|-------------|
| `mutation_tracker.py` | Records and queries agent mutation genealogy including parent-child relationships, mutation strategies used, and performance comparisons between variants | `get_mutation_tracker`, `MutationTracker` |
| `auto_specializer.py` | Data-driven agent spawning based on domain performance; monitors success rates and proposes specialized agent creation when thresholds are met (85% success triggers specialization) | `AutoSpecializer`, `SpecializationConfig` |
| `agent_reaper.py` | DyLAN-based lifecycle management archiving low-performing or inactive spawned agents based on importance scores, inactivity duration, and success rate thresholds | `AgentReaper`, `ReaperConfig` |
| `strategy_performance_tracker.py` | Tracks mutation strategy effectiveness per domain to determine which strategies (e.g. "code_specialist", "reasoning_enhancer") produce the best fitness improvements for each domain | `get_strategy_tracker`, `StrategyPerformanceTracker` |

## Version History

- **V7.0** - Emergent mutations from AI debate (replaces ASI)
- **V7.5** - Phase 0a: EvolutionManager extraction
- **V7 Sprint 2** - TieredValidator with parallel benchmarks
- **V9.1** - EvolutionService service layer
- **V12.4** - Enhanced safety gates, improved rate limiting, mutation tracking, auto-specialization, agent reaping, strategy performance
