"""NEXUS drivers package.

Exports the current CLI and SDK driver surface plus the shared abstractions used
by the runtime.
"""

# V11 Abstraction Layer (F31-F33)
# V12.4 SDK-Native Drivers (API-First)
from .anthropic_sdk_driver import AnthropicSDKDriver

# V9 Async Drivers (preferred)
from .async_claude_driver import AsyncClaudeDriver, AsyncClaudeDriverConfig, create_async_claude_driver
from .async_factory import (
    AsyncDriverFactory,
    create_driver_factory,
    get_driver_factory,
    set_driver_factory,
)
from .async_gemini_driver import AsyncGeminiDriver, AsyncGeminiDriverConfig, create_async_gemini_driver
from .cli_adapter import (
    ClaudeCLIAdapter,
    GeminiCLIAdapter,
    create_cli_adapter,
)

# V12.4 Context Window Manager
from .context_manager import ContextManager, ContextMessage, estimate_tokens, get_context_window
from .deepseek_sdk_driver import DeepSeekSDKDriver

# V12.4 Driver Health Monitor
from .driver_health_monitor import (
    DriverHealth,
    DriverHealthMonitor,
    HealthAlert,
    HealthStatus,
    MonitorStats,
    get_health_monitor,
    reset_health_monitor,
)

# V12.4 COGNITIVE BOOST: Failover Manager
from .failover_manager import (
    FailoverConfig,
    FailoverDecision,
    FailoverManager,
    FailoverState,
    FailoverStats,
    get_failover_manager,
    reset_failover_manager,
)
from .google_genai_sdk_driver import GoogleGenAISDKDriver

# V12.4 COGNITIVE BOOST: Inference Latency Analyzer
from .inference_latency_analyzer import (
    AnalyzerStats,
    InferenceLatencyAnalyzer,
    LatencySample,
    ModelLatencyProfile,
    get_latency_analyzer,
    reset_latency_analyzer,
)
from .kimi_sdk_driver import KimiSDKDriver
from .minimax_sdk_driver import MiniMaxSDKDriver

# V12.4 Local LLM Driver
from .ollama_driver import OllamaDriver
from .openai_sdk_driver import OpenAISDKDriver
from .protocol import (
    BaseAsyncDriver,
    DriverProtocol,
    DriverResponse,
    DriverResponseStatus,
    SessionProtocol,
    StreamChunk,
    ToolCall,
    ToolExecutorProtocol,
)

# V12.4 Response Cache
from .response_cache import CacheStats, ResponseCache
from .session_abstraction import (
    CLISessionManager,
    SessionManager,
    SessionMetadata,
    SessionMode,
    SessionRegistry,
    SessionState,
    get_session_registry,
)
from .tool_executor import (
    LocalToolExecutor,
    ToolExecutor,
    ToolRegistry,
    ToolResult,
    ToolSchema,
    create_local_executor,
    create_tool_registry,
)

# Legacy sync drivers moved to core/drivers/legacy/
# from .gemini_driver_v7 import GeminiDriverV7
# from .claude_driver_hybrid import ClaudeDriverHybrid

__all__ = [
    # V11 Abstraction Layer (F31)
    "DriverProtocol",
    "DriverResponse",
    "DriverResponseStatus",
    "ToolCall",
    "StreamChunk",
    "SessionProtocol",
    "ToolExecutorProtocol",
    "BaseAsyncDriver",
    "GeminiCLIAdapter",
    "ClaudeCLIAdapter",
    "create_cli_adapter",
    # V11 Session Abstraction (F32)
    "SessionMode",
    "SessionState",
    "SessionMetadata",
    "SessionManager",
    "CLISessionManager",
    "SessionRegistry",
    "get_session_registry",
    # V11 Tool Abstraction (F33)
    "ToolResult",
    "ToolSchema",
    "ToolExecutor",
    "LocalToolExecutor",
    "ToolRegistry",
    "create_local_executor",
    "create_tool_registry",
    # V9 Async (preferred)
    "AsyncClaudeDriver",
    "AsyncClaudeDriverConfig",
    "create_async_claude_driver",
    "AsyncGeminiDriver",
    "AsyncGeminiDriverConfig",
    "create_async_gemini_driver",
    "AsyncDriverFactory",
    "get_driver_factory",
    "set_driver_factory",
    "create_driver_factory",
    # V12.4 SDK-Native (API-First)
    "AnthropicSDKDriver",
    "GoogleGenAISDKDriver",
    "DeepSeekSDKDriver",
    "KimiSDKDriver",
    "OpenAISDKDriver",
    "MiniMaxSDKDriver",
    # V12.4 Local LLM
    "OllamaDriver",
    # V12.4 Response Cache
    "ResponseCache",
    "CacheStats",
    # V12.4 Context Window Manager
    "ContextManager",
    "ContextMessage",
    "estimate_tokens",
    "get_context_window",
    # V12.4 Driver Health Monitor
    "DriverHealthMonitor",
    "DriverHealth",
    "HealthStatus",
    "HealthAlert",
    "MonitorStats",
    "get_health_monitor",
    "reset_health_monitor",
    # V12.4 COGNITIVE BOOST: Failover Manager
    "FailoverManager",
    "FailoverState",
    "FailoverConfig",
    "FailoverDecision",
    "FailoverStats",
    "get_failover_manager",
    "reset_failover_manager",
    # V12.4 COGNITIVE BOOST: Inference Latency Analyzer
    "InferenceLatencyAnalyzer",
    "LatencySample",
    "ModelLatencyProfile",
    "AnalyzerStats",
    "get_latency_analyzer",
    "reset_latency_analyzer",
]
