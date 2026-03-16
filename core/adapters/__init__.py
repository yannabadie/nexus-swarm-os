"""
NEXUS V8.2.0a - Adapters Module

Provides bidirectional adapters between different analysis types
used in Swarm and HiveMind pipelines.

Adapters:
- AnalysisAdapter: TaskAnalysis <-> IndependentAnalysis
"""

from .analysis_adapter import AnalysisAdapter

__all__ = ["AnalysisAdapter"]
