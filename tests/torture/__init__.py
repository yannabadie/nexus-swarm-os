"""
NEXUS V8.2.0d Torture Protocol Module

Comprehensive stress testing for SagaManager + HiveMind integration.

Usage:
    pytest tests/torture_v8.py -m torture -v
    python tests/torture_v8.py
"""

from .base import TortureBase, TortureResultV8
from .chaos_injectors import CorruptionInjector, CrashInjector, RaceInjector
from .metrics_collector import MetricsCollector, ScenarioMetrics

__all__ = [
    "TortureBase",
    "TortureResultV8",
    "MetricsCollector",
    "ScenarioMetrics",
    "CrashInjector",
    "RaceInjector",
    "CorruptionInjector",
]
