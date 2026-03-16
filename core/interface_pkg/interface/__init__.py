"""NEXUS V7 Interface Module"""

# V12.4: Command Parser
# V12.4 COGNITIVE BOOST: Command Analytics
from .command_analytics import (
    AnalyticsStats,
    CommandAnalytics,
    CommandInvocation,
    CommandMetrics,
    UsagePattern,
    get_command_analytics,
    reset_command_analytics,
)
from .command_parser import (
    Arg,
    ArgType,
    CommandDef,
    CommandParser,
    ParsedCommand,
    Suggestion,
)

__all__ = [
    # V12.4: Command Parser
    "Arg",
    "ArgType",
    "CommandDef",
    "CommandParser",
    "ParsedCommand",
    "Suggestion",
    # V12.4 COGNITIVE BOOST: Command Analytics
    "CommandAnalytics",
    "CommandInvocation",
    "CommandMetrics",
    "UsagePattern",
    "AnalyticsStats",
    "get_command_analytics",
    "reset_command_analytics",
]
