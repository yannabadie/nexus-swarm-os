"""
NEXUS V8.2.0a - Unified Analysis Adapter

Bidirectional adapter between Swarm TaskAnalysis and HiveMind IndependentAnalysis.

Problem Solved:
- TaskAnalysis (Swarm) uses TaskComplexity enum
- IndependentAnalysis (HiveMind) uses complexity_assessment: str
- No unified way to convert between them for cross-domain usage

Usage:
    from core.adapters import AnalysisAdapter

    # HiveMind -> Swarm
    task_analysis = AnalysisAdapter.to_task_analysis(independent_analysis, raw_input)

    # Swarm -> HiveMind
    independent = AnalysisAdapter.to_independent_analysis(task_analysis, agent_id)

Note: Conversion is NOT lossless - some fields don't have equivalents.
See IMPACT_ANALYSIS_V8.2.md for field mapping details.

Author: Claude (NEXUS V8.2.0a)
Date: 2025-12-09
"""

from datetime import datetime

from core.intelligence.hive_mind.types import IndependentAnalysis
from core.intelligence.swarm.task_analyzer import TaskAnalysis, TaskComplexity, TaskDomain


class AnalysisAdapter:
    """
    Bidirectional adapter between Swarm and HiveMind analysis types.

    Handles the complexity mismatch:
    - TaskAnalysis.complexity: TaskComplexity enum
    - IndependentAnalysis.complexity_assessment: str (free-form)

    Field Mapping (HiveMind -> Swarm):
    - complexity_assessment -> complexity (fuzzy match)
    - confidence -> confidence
    - task_understanding -> raw_input (fallback)
    - LOST: agent_id, reasoning, required_capabilities, potential_risks

    Field Mapping (Swarm -> HiveMind):
    - complexity -> complexity_assessment (enum name)
    - raw_input -> task_understanding
    - confidence -> confidence
    - LOST: domains, requires_*, fit_scores, detected_keywords
    """

    # Fuzzy mapping from string patterns to TaskComplexity enum
    COMPLEXITY_MAP = {
        "trivial": TaskComplexity.TRIVIAL,
        "simple": TaskComplexity.SIMPLE,
        "easy": TaskComplexity.SIMPLE,
        "moderate": TaskComplexity.MODERATE,
        "medium": TaskComplexity.MODERATE,
        "complex": TaskComplexity.COMPLEX,
        "difficult": TaskComplexity.COMPLEX,
        "expert": TaskComplexity.EXPERT,
        "advanced": TaskComplexity.EXPERT,
        "critical": TaskComplexity.EXPERT,
    }

    # Domain detection from string patterns
    DOMAIN_PATTERNS = {
        "code": TaskDomain.CODING,
        "coding": TaskDomain.CODING,
        "programming": TaskDomain.CODING,
        "bug": TaskDomain.DEBUGGING,
        "debug": TaskDomain.DEBUGGING,
        "fix": TaskDomain.DEBUGGING,
        "research": TaskDomain.RESEARCH,
        "search": TaskDomain.RESEARCH,
        "analyze": TaskDomain.ANALYSIS,
        "analysis": TaskDomain.ANALYSIS,
        "security": TaskDomain.SECURITY,
        "design": TaskDomain.ARCHITECTURE,
        "architect": TaskDomain.ARCHITECTURE,
        "structure": TaskDomain.ARCHITECTURE,
        "document": TaskDomain.DOCUMENTATION,
        "test": TaskDomain.TESTING,
        "web": TaskDomain.WEB_INTERACTION,
        "creative": TaskDomain.CREATIVE,
    }

    @classmethod
    def to_task_analysis(cls, hive: IndependentAnalysis, raw_input: str, detect_domains: bool = True) -> TaskAnalysis:
        """
        Convert HiveMind IndependentAnalysis to Swarm TaskAnalysis.

        Args:
            hive: IndependentAnalysis from HiveMind pipeline.
            raw_input: Original user task string.
            detect_domains: Whether to auto-detect domains from text.

        Returns:
            TaskAnalysis instance for Swarm usage.

        Note: Some fields will use defaults as IndependentAnalysis
              doesn't have equivalents (requires_*, fit_scores, etc.)
        """
        # Fuzzy match complexity
        complexity_str = str(hive.complexity_assessment).lower()
        complexity = TaskComplexity.MODERATE  # Default

        for pattern, complexity_enum in cls.COMPLEXITY_MAP.items():
            if pattern in complexity_str:
                complexity = complexity_enum
                break

        # Detect domains from text if requested
        # Note: TaskDomain has no UNKNOWN value, use CODING as fallback
        domains: list[TaskDomain] = [TaskDomain.CODING]
        primary_domain = TaskDomain.CODING

        if detect_domains:
            text_to_search = f"{raw_input} {hive.task_understanding} {hive.proposed_approach}".lower()
            detected = []
            for pattern, domain in cls.DOMAIN_PATTERNS.items():
                if pattern in text_to_search and domain not in detected:
                    detected.append(domain)

            if detected:
                domains = detected
                primary_domain = detected[0]

        # Estimate fit scores from capabilities mentioned
        gemini_fit = 0.5
        claude_fit = 0.5

        capabilities_str = " ".join(hive.required_capabilities).lower()
        if any(kw in capabilities_str for kw in ["search", "web", "grounding"]):
            gemini_fit += 0.2
        if any(kw in capabilities_str for kw in ["code", "security", "reasoning"]):
            claude_fit += 0.2

        return TaskAnalysis(
            complexity=complexity,
            domains=domains,
            primary_domain=primary_domain,
            requires_web="web" in capabilities_str or "search" in capabilities_str,
            requires_code_execution="execute" in capabilities_str or "run" in capabilities_str,
            requires_deep_reasoning=complexity in (TaskComplexity.COMPLEX, TaskComplexity.EXPERT),
            requires_iteration="iterate" in capabilities_str or "refine" in capabilities_str,
            gemini_fit_score=min(1.0, gemini_fit),
            claude_fit_score=min(1.0, claude_fit),
            raw_input=raw_input,
            confidence=hive.confidence,
            detected_keywords=[],  # Would need NLP to populate
        )

    @classmethod
    def to_independent_analysis(cls, swarm: TaskAnalysis, agent_id: str, reasoning: str = "") -> IndependentAnalysis:
        """
        Convert Swarm TaskAnalysis to HiveMind IndependentAnalysis.

        Args:
            swarm: TaskAnalysis from Swarm pipeline.
            agent_id: Agent ID performing the analysis.
            reasoning: Optional reasoning string.

        Returns:
            IndependentAnalysis instance for HiveMind usage.

        Note: Some fields will use defaults or derive from TaskAnalysis
              as it doesn't have direct equivalents.
        """
        # Build required capabilities from requirements
        capabilities = []
        if swarm.requires_web:
            capabilities.append("web_search")
        if swarm.requires_code_execution:
            capabilities.append("code_execution")
        if swarm.requires_deep_reasoning:
            capabilities.append("deep_reasoning")
        if swarm.requires_iteration:
            capabilities.append("iterative_refinement")

        # Add domain-based capabilities
        for domain in swarm.domains:
            capabilities.append(f"domain_{domain.value}")

        # Build approach from analysis
        approach_parts = []
        if swarm.recommended_lead != "equal":
            approach_parts.append(f"Lead: {swarm.recommended_lead}")
        if swarm.needs_adversarial_mode:
            approach_parts.append("Use adversarial RED_BLUE mode")
        approach_parts.append(f"Primary domain: {swarm.primary_domain.value}")

        return IndependentAnalysis(
            agent_id=agent_id,
            task_understanding=swarm.raw_input,
            complexity_assessment=swarm.complexity.name,  # Enum name as string
            proposed_approach=" | ".join(approach_parts) if approach_parts else "Standard approach",
            required_capabilities=capabilities,
            potential_risks=[],  # Would need analysis to populate
            confidence=swarm.confidence,
            reasoning=reasoning or f"Converted from TaskAnalysis (complexity: {swarm.complexity.name})",
            timestamp=datetime.now(),
        )

    @classmethod
    def complexity_to_string(cls, complexity: TaskComplexity) -> str:
        """Convert TaskComplexity enum to descriptive string."""
        descriptions = {
            TaskComplexity.TRIVIAL: "trivial (single-step, immediate)",
            TaskComplexity.SIMPLE: "simple (few steps, straightforward)",
            TaskComplexity.MODERATE: "moderate (multiple steps, some coordination)",
            TaskComplexity.COMPLEX: "complex (many steps, significant coordination)",
            TaskComplexity.EXPERT: "expert (advanced, requires deep expertise)",
        }
        return descriptions.get(complexity, complexity.name)

    @classmethod
    def string_to_complexity(cls, text: str) -> TaskComplexity:
        """Convert string to TaskComplexity enum with fuzzy matching."""
        text_lower = text.lower()
        for pattern, complexity in cls.COMPLEXITY_MAP.items():
            if pattern in text_lower:
                return complexity
        return TaskComplexity.MODERATE  # Default
