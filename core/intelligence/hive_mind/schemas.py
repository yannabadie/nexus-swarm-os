"""
NEXUS V12.4.1 - HiveMind Phase Output Schemas

Pydantic schemas for structured outputs from each HiveMind phase.
Replaces json_parser.py with type-safe, API-enforced schemas.

Epic 1.2: Structured Outputs
Research: JSONSchemaBench (ArXiv 2501.10868)

Usage:
    from core.intelligence.hive_mind.schemas import AnalysisOutput

    # With Anthropic SDK:
    response = await driver.invoke_structured(
        prompt=prompt,
        output_type=AnalysisOutput,
    )
    parsed = response.raw["parsed"]  # AnalysisOutput instance

    # Or access via JSON:
    data = json.loads(response.content)  # Guaranteed valid

Author: Claude Opus 4.6 (NEXUS Architect)
Date: 2026-02-17
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator

# =============================================================================
# Phase 1: Analysis
# =============================================================================


class TaskComplexity(str, Enum):
    """Task complexity levels."""

    TRIVIAL = "TRIVIAL"
    MODERATE = "MODERATE"
    COMPLEX = "COMPLEX"
    EXPERT = "EXPERT"


class AnalysisOutput(BaseModel):
    """Output schema for Phase 1: Analysis."""

    task_understanding: str = Field(
        description="Clear understanding of what needs to be done",
        min_length=10,
    )
    complexity_assessment: TaskComplexity = Field(description="Complexity level: TRIVIAL, MODERATE, COMPLEX, or EXPERT")
    proposed_approach: str = Field(
        description="Proposed strategy to solve this task",
        min_length=10,
    )
    required_capabilities: list[str] = Field(
        description="List of capabilities needed",
        min_length=1,
    )
    potential_risks: list[str] = Field(
        description="List of potential risks or challenges",
        default_factory=list,
    )
    confidence: float = Field(
        description="Confidence level (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
    )
    reasoning: str = Field(
        description="Why this approach and complexity level were chosen",
        min_length=10,
    )

    class Config:
        json_schema_extra = {
            "example": {
                "task_understanding": "Implement user authentication with JWT",
                "complexity_assessment": "MODERATE",
                "proposed_approach": "Use JWT tokens with refresh mechanism",
                "required_capabilities": ["cryptography", "session management"],
                "potential_risks": ["Token expiry handling", "Secret storage"],
                "confidence": 0.85,
                "reasoning": "JWT is battle-tested and scales well",
            }
        }


# =============================================================================
# Phase 2: Debate
# =============================================================================


class DebateArgument(BaseModel):
    """Single debate argument."""

    speaker: str = Field(description="Agent name: gemini or claude")
    position: str = Field(description="The position taken", min_length=10)
    reasoning: str = Field(description="Supporting reasoning", min_length=10)


class DebateOutput(BaseModel):
    """Output schema for Phase 2: Debate."""

    consensus_reached: bool = Field(description="Whether agents reached consensus")
    final_decision: str = Field(
        description="The final agreed-upon decision or approach",
        min_length=10,
    )
    key_agreements: list[str] = Field(
        description="Points where agents agreed",
        default_factory=list,
    )
    unresolved_disagreements: list[str] = Field(
        description="Points where disagreement remains",
        default_factory=list,
    )
    debate_summary: str = Field(
        description="Brief summary of the debate process",
        min_length=20,
    )

    class Config:
        json_schema_extra = {
            "example": {
                "consensus_reached": True,
                "final_decision": "Use PostgreSQL with B-tree indexes",
                "key_agreements": ["PostgreSQL is reliable", "Need indexes"],
                "unresolved_disagreements": [],
                "debate_summary": "Both agents agreed PostgreSQL is best choice",
            }
        }


# =============================================================================
# Phase 3: Architecture
# =============================================================================


class ExecutionStep(BaseModel):
    """Single execution step in the plan."""

    step_number: int = Field(description="Step sequence number", ge=1)
    description: str = Field(description="What to do", min_length=5)
    tool: str | None = Field(description="Tool to use (if any)", default=None)
    dependencies: list[int] = Field(
        description="Step numbers this depends on",
        default_factory=list,
    )
    expected_outcome: str = Field(
        description="What should result from this step",
        min_length=5,
    )


class ArchitectureOutput(BaseModel):
    """Output schema for Phase 3: Architecture."""

    plan_summary: str = Field(
        description="Brief overview of the execution plan",
        min_length=20,
    )
    steps: list[ExecutionStep] = Field(
        description="Ordered list of execution steps",
        min_length=1,
    )
    success_criteria: list[str] = Field(
        description="How to verify successful completion",
        min_length=1,
    )
    estimated_complexity: TaskComplexity = Field(description="Overall plan complexity")

    @field_validator("steps")
    @classmethod
    def validate_step_numbers(cls, steps: list[ExecutionStep]) -> list[ExecutionStep]:
        """Ensure step numbers are sequential."""
        for i, step in enumerate(steps, 1):
            if step.step_number != i:
                raise ValueError(f"Step numbers must be sequential (expected {i}, got {step.step_number})")
        return steps

    class Config:
        json_schema_extra = {
            "example": {
                "plan_summary": "Implement JWT auth in 3 steps",
                "steps": [
                    {
                        "step_number": 1,
                        "description": "Install JWT library",
                        "tool": "bash",
                        "dependencies": [],
                        "expected_outcome": "JWT library installed",
                    }
                ],
                "success_criteria": ["Tests pass", "Tokens validate correctly"],
                "estimated_complexity": "MODERATE",
            }
        }


# =============================================================================
# Phase 4: Execution
# =============================================================================


class ExecutionResult(BaseModel):
    """Result of a single step execution."""

    step_number: int = Field(description="Step that was executed", ge=1)
    success: bool = Field(description="Whether step succeeded")
    output: str = Field(description="Step output or error message")
    artifacts: list[str] = Field(
        description="Files or resources created",
        default_factory=list,
    )


class ExecutionOutput(BaseModel):
    """Output schema for Phase 4: Execution."""

    overall_success: bool = Field(description="Whether all steps succeeded")
    completed_steps: list[ExecutionResult] = Field(
        description="Results of each step executed",
        min_length=1,
    )
    final_state: str = Field(
        description="Description of final state after execution",
        min_length=10,
    )
    verification_notes: str | None = Field(
        description="Notes on success criteria verification",
        default=None,
    )

    class Config:
        json_schema_extra = {
            "example": {
                "overall_success": True,
                "completed_steps": [
                    {
                        "step_number": 1,
                        "success": True,
                        "output": "JWT library installed successfully",
                        "artifacts": ["package.json"],
                    }
                ],
                "final_state": "JWT auth fully implemented and tested",
                "verification_notes": "All tests passing",
            }
        }


# =============================================================================
# Phase 5: Diagnosis
# =============================================================================


class DiagnosisOutput(BaseModel):
    """Output schema for Phase 5: Diagnosis."""

    root_cause: str = Field(
        description="Identified root cause of the failure",
        min_length=10,
    )
    affected_steps: list[int] = Field(
        description="Step numbers that failed or were affected",
        min_length=1,
    )
    recommended_fix: str = Field(
        description="How to fix the issue",
        min_length=10,
    )
    alternative_approaches: list[str] = Field(
        description="Alternative ways to address the issue",
        default_factory=list,
    )
    confidence: float = Field(
        description="Confidence in diagnosis (0.0 to 1.0)",
        ge=0.0,
        le=1.0,
    )
    reasoning: str = Field(
        description="Why this diagnosis makes sense",
        min_length=10,
    )

    class Config:
        json_schema_extra = {
            "example": {
                "root_cause": "Missing environment variable JWT_SECRET",
                "affected_steps": [2],
                "recommended_fix": "Set JWT_SECRET in .env file",
                "alternative_approaches": ["Use config file", "Use secrets manager"],
                "confidence": 0.95,
                "reasoning": "Error message clearly indicates missing secret",
            }
        }


# =============================================================================
# Phase 7: Consolidation
# =============================================================================


class ConsolidationOutput(BaseModel):
    """Output schema for Phase 7: Consolidation."""

    task_success: bool = Field(description="Whether overall task succeeded")
    key_learnings: list[str] = Field(
        description="What was learned from this task",
        min_length=1,
    )
    patterns_identified: list[str] = Field(
        description="Reusable patterns for future tasks",
        default_factory=list,
    )
    antipatterns_identified: list[str] = Field(
        description="Antipatterns to avoid in future",
        default_factory=list,
    )
    knowledge_to_retain: str = Field(
        description="Key knowledge to remember for future tasks",
        min_length=10,
    )
    performance_notes: str | None = Field(
        description="Notes on agent performance during task",
        default=None,
    )

    class Config:
        json_schema_extra = {
            "example": {
                "task_success": True,
                "key_learnings": ["JWT setup requires careful secret management"],
                "patterns_identified": ["Test auth flow before deploying"],
                "antipatterns_identified": ["Hardcoding secrets in code"],
                "knowledge_to_retain": "Always use environment variables for secrets",
                "performance_notes": "Task completed efficiently with good collaboration",
            }
        }


# =============================================================================
# Schema Registry
# =============================================================================

PHASE_SCHEMAS = {
    "analysis": AnalysisOutput,
    "debate": DebateOutput,
    "architecture": ArchitectureOutput,
    "execution": ExecutionOutput,
    "diagnosis": DiagnosisOutput,
    "consolidation": ConsolidationOutput,
}


def get_schema_for_phase(phase_name: str) -> type[BaseModel]:
    """
    Get the output schema for a specific HiveMind phase.

    Args:
        phase_name: Phase name (analysis, debate, etc.)

    Returns:
        Pydantic model class for that phase

    Raises:
        ValueError: If phase name is unknown
    """
    if phase_name not in PHASE_SCHEMAS:
        raise ValueError(f"Unknown phase: {phase_name}. Valid phases: {', '.join(PHASE_SCHEMAS.keys())}")
    return PHASE_SCHEMAS[phase_name]
