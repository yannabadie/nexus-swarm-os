"""
NEXUS V12.4 - Interface Package

Consolidated interface components:
- notifications: Email and file-based notifications
- mcp: MCP (Model Context Protocol) client and registry
- interface: Command parsing and analytics

P5.6 Phase 3: Package consolidation for reduced cognitive load.
"""

# Interface exports
from core.interface_pkg.interface import (
    AnalyticsStats,
    Arg,
    ArgType,
    CommandAnalytics,
    CommandDef,
    CommandInvocation,
    CommandMetrics,
    CommandParser,
    ParsedCommand,
    Suggestion,
    UsagePattern,
    get_command_analytics,
    reset_command_analytics,
)

# MCP exports
from core.interface_pkg.mcp import (
    MCP_SERVER_AVAILABLE,
    DiscoveredTool,
    MCPCapabilities,
    MCPClient,
    MCPError,
    MCPRegistry,
    MCPRequest,
    MCPResponse,
    MCPTool,
    MCPToolDiscovery,
    MCPToolResult,
    ToolDiscoveryResult,
    validate_input_schema,
)

# Notifications exports
from core.interface_pkg.notifications import (
    EmailNotificationError,
    check_pending_review,
    create_pending_review,
    get_repl_alert_message,
    send_review_email,
)

__all__ = [
    # Notifications
    "send_review_email",
    "EmailNotificationError",
    "create_pending_review",
    "check_pending_review",
    "get_repl_alert_message",
    # MCP
    "MCPRequest",
    "MCPResponse",
    "MCPTool",
    "MCPToolResult",
    "MCPError",
    "MCPCapabilities",
    "MCPClient",
    "MCPRegistry",
    "MCPToolDiscovery",
    "DiscoveredTool",
    "ToolDiscoveryResult",
    "validate_input_schema",
    "MCP_SERVER_AVAILABLE",
    # Interface
    "Arg",
    "ArgType",
    "CommandDef",
    "CommandParser",
    "ParsedCommand",
    "Suggestion",
    "CommandAnalytics",
    "CommandInvocation",
    "CommandMetrics",
    "UsagePattern",
    "AnalyticsStats",
    "get_command_analytics",
    "reset_command_analytics",
]

__version__ = "12.4.0"
