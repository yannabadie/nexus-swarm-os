"""
NEXUS V8.0 - Hive Mind Phases

The 7-phase architecture for TRUE collaborative intelligence.

Phase Flow:
1. Independent Analysis - Both agents analyze task separately
2. Strategic Debate - Resolve disagreements through argumentation
3. Architecture Generation - Design agent topology and execution plan
4. Monitored Execution - Execute with real-time monitoring
5. Failure Diagnosis - Dual-agent failure analysis
6. Adaptive Retry - Apply changes and retry with blacklist
7. Knowledge Consolidation - Post-task debate on what to retain
"""

from .phase_analysis import IndependentAnalysisPhase
from .phase_architecture import ArchitectureGenerationPhase
from .phase_consolidation import KnowledgeConsolidationPhase
from .phase_debate import StrategicDebatePhase
from .phase_diagnosis import FailureDiagnosisPhase
from .phase_execution import MonitoredExecutionPhase
from .phase_retry import AdaptiveRetryPhase

__all__ = [
    "IndependentAnalysisPhase",
    "StrategicDebatePhase",
    "ArchitectureGenerationPhase",
    "MonitoredExecutionPhase",
    "FailureDiagnosisPhase",
    "AdaptiveRetryPhase",
    "KnowledgeConsolidationPhase",
]
