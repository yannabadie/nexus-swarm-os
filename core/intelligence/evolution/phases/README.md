# NEXUS Evolution Phases Module

## Synopsis

The **phases** module contains the implementation of individual evolution phases: brainstorm, create, and promote. These phases handle the lifecycle of agent mutation proposals from initial debate through child creation to final promotion.

## Architecture

```
+-------------------------------------------------------------------------+
|                      EVOLUTION PHASES                                    |
+-------------------------------------------------------------------------+
|                                                                          |
|  +-------------+      +-------------+      +-------------+              |
|  | BRAINSTORM  |----->|   CREATE    |----->|  PROMOTE    |              |
|  |             |      |             |      |             |              |
|  | Gemini +    |      | Apply JSON  |      | Validate &  |              |
|  | Claude      |      | patches to  |      | replace     |              |
|  | debate      |      | create child|      | parent      |              |
|  +-------------+      +-------------+      +-------------+              |
|        |                    |                    |                       |
|        v                    v                    v                       |
|  MutationProposal     ChildCreation        PromotionResult              |
|                        Result                                            |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Phase | Purpose |
|------|-------|---------|
| `brainstorm.py` | Brainstorm | Symbiotic debate for mutation proposals |
| `create.py` | Create | Apply patches to create child agent |
| `promote.py` | Promote | Validate and promote child to parent |

## Phase Implementations

### Brainstorm Phase
```python
class BrainstormPhase:
    """Symbiotic debate between Gemini and Claude."""

    async def brainstorm(
        self,
        trigger: EvolutionTrigger,
        context: EvolutionContext,
        max_turns: int = 30
    ) -> BrainstormResult

    async def extract_mutations(
        self,
        debate_history: List[Message]
    ) -> List[MutationProposal]
```

### Create Phase
```python
class CreatePhase:
    """Apply JSON patches to create child."""

    async def create(
        self,
        mutation: MutationProposal,
        parent_path: Path,
        child_id: str
    ) -> ChildCreationResult

    def apply_patches(
        self,
        source_code: str,
        patches: List[JSONPatch]
    ) -> str
```

### Promote Phase
```python
class PromotePhase:
    """Validate and promote child to replace parent."""

    async def promote(
        self,
        child_path: Path,
        child_id: str,
        validation_result: TieredValidationResult
    ) -> PromotionResult

    async def archive_parent(
        self,
        parent_path: Path
    ) -> ArchiveResult
```

## Phase Flow

```
1. BRAINSTORM
   |
   +-► Gemini proposes mutation ideas
   +-► Claude critiques and refines
   +-► Consensus on JSON patches (30 turns max)
   |
   v
2. CREATE
   |
   +-► Parse JSON patches
   +-► Apply to parent code
   +-► Create child directory
   |
   v
3. PROMOTE (if validation passes)
   |
   +-► Run 5-tier validation
   +-► Archive parent
   +-► Promote child to parent location
   +-► Update LINEAGE.json
```

## Usage

```python
from core.intelligence.evolution.phases import BrainstormPhase, CreatePhase, PromotePhase

# Phase 1: Brainstorm
brainstorm = BrainstormPhase(drivers, config)
result = await brainstorm.brainstorm(trigger, context)

# Phase 2: Create
create = CreatePhase(workspace_path)
child = await create.create(result.mutation, parent_path, child_id)

# Phase 3: Promote (if validation passes)
promote = PromotePhase(workspace_path)
promotion = await promote.promote(child.path, child.id, validation)
```

## Dependencies

### Internal
- `core.evolution.models` - Phase dataclasses
- `core.evolution.validator` - Validation pipeline
- `core.drivers` - Agent invocation

## Version History

- **V7.5** - Phase 0a: Extraction from EvolutionManager
- **V12.4** - Enhanced patch parsing, improved debate
