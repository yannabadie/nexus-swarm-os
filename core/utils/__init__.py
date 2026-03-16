"""
NEXUS V7.5 HIVE MIND Utility modules.
"""

from .artifact_verifier import ArtifactVerifier
from .async_utils import (
    get_or_create_event_loop,
    run_in_thread,
    run_sync,
)
from .atomic_store import (
    AtomicJsonStore,
    AtomicJsonStoreManager,
    get_store,
)

# V12.4 COGNITIVE BOOST: Config Manager
from .config_manager import ConfigEntry, ConfigManager, get_config_manager, reset_config_manager

# V12.4 COGNITIVE BOOST: Event Bus
from .event_bus import Event, EventBus, get_event_bus, reset_event_bus

# V12.4 COGNITIVE BOOST: Feature Flags
from .feature_flags import FeatureFlags, FlagDefinition, get_flags, reset_flags
from .json_extractor import (
    extract_code_block,
    extract_json,
    extract_json_safe,
    wrap_json,
)

# V12.4 COGNITIVE BOOST: Output Validation
from .output_validator import (
    Field,
    OutputValidator,
    Schema,
    ValidationError,
    ValidationResult,
)

# V12.4 COGNITIVE BOOST: Schema Registry
from .schema_registry import (
    SchemaDefinition,
    SchemaRegistry,
    SchemaValidationResult,
    get_schema_registry,
    reset_schema_registry,
)
from .serialization import (
    NexusJSONEncoder,
    nexus_dumps,
    nexus_loads,
    serialize_for_checkpoint,
)
from .stream_parser import (
    extract_final_result,
    extract_stats,
    extract_tool_info,
    is_result_message,
    is_tool_message,
    parse_stream_chunk,
)

__all__ = [
    "ArtifactVerifier",
    "AtomicJsonStore",
    "AtomicJsonStoreManager",
    "get_store",
    "extract_json",
    "extract_json_safe",
    "extract_code_block",
    "wrap_json",
    "parse_stream_chunk",
    "is_result_message",
    "extract_final_result",
    "extract_stats",
    "is_tool_message",
    "extract_tool_info",
    "run_sync",
    "get_or_create_event_loop",
    "run_in_thread",
    "NexusJSONEncoder",
    "nexus_dumps",
    "nexus_loads",
    "serialize_for_checkpoint",
    # V12.4 COGNITIVE BOOST: Output Validation
    "OutputValidator",
    "Schema",
    "Field",
    "ValidationResult",
    "ValidationError",
    # V12.4 COGNITIVE BOOST: Event Bus
    "EventBus",
    "Event",
    "get_event_bus",
    "reset_event_bus",
    # V12.4 COGNITIVE BOOST: Feature Flags
    "FeatureFlags",
    "FlagDefinition",
    "get_flags",
    "reset_flags",
    # V12.4 COGNITIVE BOOST: Config Manager
    "ConfigManager",
    "ConfigEntry",
    "get_config_manager",
    "reset_config_manager",
    # V12.4 COGNITIVE BOOST: Schema Registry
    "SchemaRegistry",
    "SchemaDefinition",
    "SchemaValidationResult",
    "get_schema_registry",
    "reset_schema_registry",
]
