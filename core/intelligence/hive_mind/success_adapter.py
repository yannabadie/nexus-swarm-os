"""
NEXUS V8.2.0 - HiveMind Success Adapter

Adapter to make HiveMind results compatible with SuccessMemory.
Bridges the gap between HiveMindResult and SuccessMemory.record_success().

The SuccessMemory uses duck typing, expecting objects with specific properties:
- analysis: raw_input, complexity, domains, primary_domain
- result: selected_mode/mode, status, total_time_seconds, execution_result

This module provides pseudo-dataclasses that satisfy those interfaces.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PseudoExecutionResult:
    """
    Pseudo ExecutionResult for SuccessMemory compatibility.

    SuccessMemory looks for:
    - total_rounds
    - agent_outputs (list with agent_id attribute)
    """

    total_rounds: int = 1
    agent_outputs: list[Any] = field(default_factory=list)

    def __post_init__(self):
        if not self.agent_outputs:
            # Create pseudo agent outputs
            self.agent_outputs = [
                type("AgentOutput", (), {"agent_id": "gemini", "status": "success"})(),
                type("AgentOutput", (), {"agent_id": "claude", "status": "success"})(),
            ]


@dataclass
class HiveMindAnalysisAdapter:
    """
    Pseudo-TaskAnalysis for HiveMind -> SuccessMemory compatibility.

    SuccessMemory extracts:
    - raw_input: task description
    - complexity: enum with .name attribute
    - domains: list of enums with .value attribute
    - primary_domain: single enum with .value attribute
    """

    raw_input: str
    complexity: Any = None
    domains: list[str] = field(default_factory=lambda: ["hive_mind"])
    primary_domain: str | None = "hive_mind"

    def __post_init__(self):
        # Create pseudo-complexity enum if not provided
        if self.complexity is None:
            self.complexity = type("Complexity", (), {"name": "MODERATE", "value": 3})()

        # Convert string domains to pseudo-enums with .value
        if self.domains and isinstance(self.domains[0], str):
            self.domains = [type("Domain", (), {"value": d, "name": d.upper()})() for d in self.domains]

        # Convert primary_domain to pseudo-enum
        if isinstance(self.primary_domain, str):
            self.primary_domain = type(
                "Domain", (), {"value": self.primary_domain, "name": self.primary_domain.upper()}
            )()


@dataclass
class HiveMindResultAdapter:
    """
    Pseudo-SwarmResult for HiveMind -> SuccessMemory compatibility.

    SuccessMemory extracts:
    - selected_mode or mode: CollaborationMode enum
    - status: string or enum
    - total_time_seconds: float
    - execution_result: object with total_rounds and agent_outputs
    - agent_outputs: list with agent_id attribute (fallback)
    """

    selected_mode: str = "hive_mind"
    status: str = "completed"
    total_time_seconds: float = 0.0
    execution_result: Any = None
    agent_outputs: list[Any] = field(default_factory=list)
    total_rounds: int = 7  # HiveMind has 7 phases

    def __post_init__(self):
        # Create pseudo execution_result if not provided
        if self.execution_result is None:
            self.execution_result = PseudoExecutionResult(
                total_rounds=self.total_rounds, agent_outputs=self.agent_outputs if self.agent_outputs else None
            )

        # Ensure agent_outputs has fallback
        if not self.agent_outputs:
            self.agent_outputs = self.execution_result.agent_outputs

    @property
    def mode(self):
        """Alias for selected_mode (SuccessMemory checks both)."""
        return self.selected_mode


@dataclass
class SwarmDelegationAnalysisAdapter:
    """
    V8.3.2: Adapter for SwarmBridge delegation -> SuccessMemory.

    Records Swarm delegations so the system learns which modes work best.
    """

    raw_input: str
    complexity: Any = None
    domains: list[str] = field(default_factory=lambda: ["swarm_delegation"])
    primary_domain: str | None = "swarm_delegation"
    mode_used: str = ""

    def __post_init__(self):
        if self.complexity is None:
            self.complexity = type("Complexity", (), {"name": "MODERATE", "value": 3})()
        if self.domains and isinstance(self.domains[0], str):
            self.domains = [type("Domain", (), {"value": d, "name": d.upper()})() for d in self.domains]
        if isinstance(self.primary_domain, str):
            self.primary_domain = type(
                "Domain", (), {"value": self.primary_domain, "name": self.primary_domain.upper()}
            )()


@dataclass
class SwarmDelegationResultAdapter:
    """
    V8.3.2: Adapter for SwarmBridge delegation result -> SuccessMemory.
    """

    selected_mode: str = "specialist"
    status: str = "completed"
    total_time_seconds: float = 0.0
    execution_result: Any = None
    agent_outputs: list[Any] = field(default_factory=list)
    total_rounds: int = 1
    fallback_count: int = 0

    def __post_init__(self):
        if self.execution_result is None:
            self.execution_result = PseudoExecutionResult(
                total_rounds=self.total_rounds, agent_outputs=self.agent_outputs if self.agent_outputs else None
            )
        if not self.agent_outputs:
            self.agent_outputs = self.execution_result.agent_outputs

    @property
    def mode(self):
        return self.selected_mode


def create_swarm_delegation_adapters(
    task: str, mode_used: str, duration: float, success: bool, fallback_count: int = 0, agents_used: list[str] = None
) -> tuple:
    """
    V8.3.2: Create adapters for SwarmBridge delegation.

    Args:
        task: The delegated task description
        mode_used: The collaboration mode that was used
        duration: Execution time in seconds
        success: Whether delegation succeeded
        fallback_count: Number of fallbacks used
        agents_used: List of agent IDs involved

    Returns:
        Tuple of (SwarmDelegationAnalysisAdapter, SwarmDelegationResultAdapter)
    """
    agents_used = agents_used or ["gemini", "claude"]

    analysis = SwarmDelegationAnalysisAdapter(
        raw_input=task, domains=["swarm_delegation", mode_used], mode_used=mode_used
    )

    result = SwarmDelegationResultAdapter(
        selected_mode=mode_used,
        status="completed" if success else "failed",
        total_time_seconds=duration,
        total_rounds=1 + fallback_count,
        fallback_count=fallback_count,
        agent_outputs=[type("AgentOutput", (), {"agent_id": aid, "status": "success"})() for aid in agents_used],
    )

    return analysis, result


def create_hive_mind_adapters(
    task: str, duration: float, success: bool, phases_completed: int = 7, agents_used: list[str] = None
) -> tuple:
    """
    Convenience function to create both adapters.

    Args:
        task: Original task description
        duration: Total execution time in seconds
        success: Whether task succeeded
        phases_completed: Number of phases completed (default 7)
        agents_used: List of agent IDs used

    Returns:
        Tuple of (HiveMindAnalysisAdapter, HiveMindResultAdapter)
    """
    agents_used = agents_used or ["gemini", "claude"]

    analysis = HiveMindAnalysisAdapter(raw_input=task, domains=["hive_mind", "multi_agent"])

    result = HiveMindResultAdapter(
        selected_mode="hive_mind",
        status="completed" if success else "failed",
        total_time_seconds=duration,
        total_rounds=phases_completed,
        agent_outputs=[type("AgentOutput", (), {"agent_id": aid, "status": "success"})() for aid in agents_used],
    )

    return analysis, result
