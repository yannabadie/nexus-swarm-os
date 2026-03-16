"""NEXUS V7 Meta Module - CLI Inspection"""

# V12.4 COGNITIVE BOOST: System Introspector
from .system_introspector import (
    ComponentInfo,
    IntrospectorStats,
    SystemIntrospector,
    SystemSnapshot,
    get_introspector,
    reset_introspector,
)

__all__ = [
    "SystemIntrospector",
    "ComponentInfo",
    "SystemSnapshot",
    "IntrospectorStats",
    "get_introspector",
    "reset_introspector",
]
