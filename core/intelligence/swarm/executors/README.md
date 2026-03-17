# NEXUS Swarm Executors Module

## Synopsis

The **executors** module contains the implementations of the 6 Swarm collaboration modes. Each executor handles a specific collaboration pattern between agents, from parallel work to adversarial review.

## Architecture

```
+-------------------------------------------------------------------------+
|                       EXECUTOR REGISTRY                                  |
+-------------------------------------------------------------------------+
|                                                                          |
|  +-------------+  +-------------+  +-------------+  +-------------+    |
|  |  PARALLEL   |  | SEQUENTIAL  |  |LEAD_SUPPORT |  |  PING_PONG  |    |
|  |  ---------  |  |  ---------  |  |  ---------  |  |  ---------  |    |
|  | Both agents |  |  Ordered    |  |  80% lead   |  |   Rapid     |    |
|  |  parallel   |  |  pipeline   |  |  20% review |  | alternation |    |
|  +-------------+  +-------------+  +-------------+  +-------------+    |
|                                                                          |
|  +-------------+  +-------------+                                       |
|  | SPECIALIST  |  |  RED_BLUE   |                                       |
|  |  ---------  |  |  ---------  |                                       |
|  |   Single    |  | Adversarial |                                       |
|  |   expert    |  |   review    |                                       |
|  +-------------+  +-------------+                                       |
|                                                                          |
+-------------------------------------------------------------------------+
```

## Component Map

| File | Mode | Description |
|------|------|-------------|
| `base.py` | - | Abstract executor interface |
| `registry.py` | - | Executor registry and factory |
| `parallel_executor.py` | PARALLEL | Simultaneous agent work |
| `sequential_executor.py` | SEQUENTIAL | Ordered pipeline execution |
| `lead_support_executor.py` | LEAD_SUPPORT | Lead drives, support reviews |
| `ping_pong_executor.py` | PING_PONG | Rapid alternation |
| `specialist_executor.py` | SPECIALIST | Single expert handles all |
| `red_blue_executor.py` | RED_BLUE | Adversarial propose/attack |

## Executor Interface

```python
class ModeExecutor(ABC):
    """Abstract base for all mode executors."""

    @abstractmethod
    async def execute(
        self,
        task: str,
        context: ExecutionContext,
        agents: AgentPool
    ) -> ExecutionResult

    @abstractmethod
    def get_mode(self) -> CollaborationMode

    @abstractmethod
    def get_max_rounds(self) -> int
```

## Mode Implementations

### ParallelExecutor
```python
class ParallelExecutor(ModeExecutor):
    """All active agents work simultaneously, merge results."""

    async def execute(self, task, context, agents) -> ExecutionResult:
        # Run all registered agents in parallel (provider-agnostic)
        tasks = [
            asyncio.create_task(driver.invoke(task))
            for driver in agents.active_drivers()
        ]
        results = await asyncio.gather(*tasks)
        # Merge using configured strategy
        return self.merge_strategy.merge(results)
```

### SequentialExecutor
```python
class SequentialExecutor(ModeExecutor):
    """Ordered execution: first agent, then second."""

    async def execute(self, task, context, agents) -> ExecutionResult:
        # First agent executes
        first_result = await agents.first.invoke(task)
        # Second agent refines
        refined_task = f"Refine this: {first_result.content}"
        return await agents.second.invoke(refined_task)
```

### LeadSupportExecutor
```python
class LeadSupportExecutor(ModeExecutor):
    """Lead (80%) drives, Support (20%) reviews."""

    async def execute(self, task, context, agents) -> ExecutionResult:
        # Lead implements
        lead_result = await agents.lead.invoke(task)
        # Support reviews and suggests
        review_task = f"Review: {lead_result.content}"
        support_review = await agents.support.invoke(review_task)
        # Lead incorporates feedback
        return await agents.lead.invoke(
            f"Incorporate feedback: {support_review.content}"
        )
```

### PingPongExecutor
```python
class PingPongExecutor(ModeExecutor):
    """Rapid alternation until convergence."""

    async def execute(self, task, context, agents) -> ExecutionResult:
        current = task
        for round in range(self.max_rounds):
            if round % 2 == 0:
                result = await agents.first.invoke(current)
            else:
                result = await agents.second.invoke(current)
            if self.is_converged(result):
                break
            current = result.content
        return result
```

### SpecialistExecutor
```python
class SpecialistExecutor(ModeExecutor):
    """Single expert handles everything."""

    async def execute(self, task, context, agents) -> ExecutionResult:
        specialist = self.select_specialist(task, agents)
        return await specialist.invoke(task)
```

### RedBlueExecutor
```python
class RedBlueExecutor(ModeExecutor):
    """Adversarial: Blue proposes, Red attacks, Blue defends."""

    async def execute(self, task, context, agents) -> ExecutionResult:
        # Blue proposes
        proposal = await agents.blue.invoke(f"Propose: {task}")
        # Red attacks
        attack = await agents.red.invoke(f"Attack: {proposal.content}")
        # Blue defends
        defense = await agents.blue.invoke(f"Defend against: {attack.content}")
        # Final synthesis
        return self.synthesize(proposal, attack, defense)
```

## Executor Registry

```python
from core.swarm.executors import get_executor, EXECUTOR_REGISTRY

# Get executor by mode
executor = get_executor(CollaborationMode.PARALLEL)
result = await executor.execute(task, context, agents)

# Registry contents
EXECUTOR_REGISTRY = {
    CollaborationMode.PARALLEL: ParallelExecutor,
    CollaborationMode.SEQUENTIAL: SequentialExecutor,
    CollaborationMode.LEAD_SUPPORT: LeadSupportExecutor,
    CollaborationMode.PING_PONG: PingPongExecutor,
    CollaborationMode.SPECIALIST: SpecialistExecutor,
    CollaborationMode.RED_BLUE: RedBlueExecutor,
}
```

## Dependencies

### Internal
- `core.swarm.collaboration_modes` - Mode definitions
- `core.swarm.merge_strategies` - Result merging
- `core.drivers` - Agent invocation

## Version History

- **V7.0** - Sprint 9: Initial 6 executors
- **V7.5** - Self-healing fallback chains
- **V12.4** - Adaptive round limits
- **V12.4 NX-CG** - Provider-agnostic: executor `base.py` uses `agent_desc.provider.value` instead of hardcoded string checks
