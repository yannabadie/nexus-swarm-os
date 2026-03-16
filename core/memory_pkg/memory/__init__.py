"""
NEXUS V13.0 MEMORIA UNIVERSALIS Memory Module

Memory systems for NEXUS:
- AutoMemory: Learning from task execution patterns (V7.5)
- SuccessMemory: Swarm task success storage (V7.6 Phase 10a)
- SuccessMemoryV2: LanceDB-backed semantic success storage (V12.4.1 Epic 1.4)
- StrategyBlacklistV2: LanceDB-backed failure tracking (V12.4.1 Epic 1.4)
- ProjectMemory: Project knowledge RAG (V7.8 Phase 10c)
- Backend Abstraction: Pluggable retrieval backends (V7.9 Phase 10f)
- Dense Embeddings: Semantic retrieval (V7.9 Phase 10g)
- MemoryService: Service Layer for memory operations (V9.1)
- UniversalIngestor: Multi-format document ingestion (V13.0)
- RAGNamespaceManager: Multi-namespace RAG support (V13.0)
"""

from .auto_memory import AutoMemory, MemoryEntry, get_auto_memory

# V7.9 Phase 10f + 10g: Backend exports
from .backends import (
    BM25S_AVAILABLE,
    LANCEDB_AVAILABLE,
    SENTENCE_TRANSFORMERS_AVAILABLE,
    Bm25Backend,
    DenseBackend,
    MemoryBackend,
    TfidfBackend,
)
from .project_memory import ProjectMemory

# V9.1: Service Layer
from .service import (
    ForgetResult,
    LearnResult,
    MemoryService,
    MemoryStatus,
    QueryResult,
)
from .strategy_blacklist_v2 import (
    BlacklistedStrategy,
    StrategyBlacklistV2,
    get_strategy_blacklist_v2,
    reset_strategy_blacklist_v2,
)

# V12.4.1 Epic 1.4: LanceDB-backed memory V2 (CANONICAL)
from .success_memory_v2 import (
    SuccessEntry,  # SuccessEntry is now in V2
    SuccessMemoryV2,
    get_success_memory_v2,
    reset_success_memory_v2,
)
from .types import Chunk, IndexStats, ScoredChunk

# V13.0 MEMORIA UNIVERSALIS: Multi-format ingestion
try:
    from .ingestors import DOCLING_AVAILABLE, UniversalIngestor
except ImportError:
    UniversalIngestor = None
    DOCLING_AVAILABLE = False

# V13.0 MEMORIA UNIVERSALIS: Multi-namespace RAG
# V12.4 COGNITIVE BOOST: Adaptive Memory Organizer (arxiv:2502.12110)
from .adaptive_memory_organizer import (  # noqa: E402  # after optional dependency block
    AdaptiveMemoryOrganizer,
    MemoryNote,
    OrganizerStats,
    get_adaptive_memory_organizer,
    reset_adaptive_memory_organizer,
)
from .adaptive_memory_organizer import (  # noqa: E402
    RetrievalResult as MemoryRetrievalResult,
)

# V12.4 COGNITIVE BOOST: Cache Manager
from .cache_manager import (  # noqa: E402
    CacheEntry,
    CacheManager,
    CacheStats,
    get_cache_manager,
    reset_cache_manager,
)

# V12.4 COGNITIVE BOOST: Context Compressor
from .context_compressor import (  # noqa: E402
    CompressionResult,
    CompressTurn,
    ContextCompressor,
    ContextShift,
    get_compressor,
    reset_compressor,
)

# V12.4 COGNITIVE BOOST: Context Window Tracker
from .context_window_tracker import (  # noqa: E402
    CompressionEvent,
    ContextTrackerStats,
    ContextUsageRecord,
    ContextWindowTracker,
    get_context_tracker,
    reset_context_tracker,
)

# V12.4 COGNITIVE BOOST: Conversation history
from .conversation_store import (  # noqa: E402
    ConversationSession,
    ConversationStore,
    ConversationSummary,
    ConversationTurn,
)
from .conversation_store import (  # noqa: E402
    SearchResult as ConversationSearchResult,
)

# V12.4 COGNITIVE BOOST: Memory Decay Scorer (Ebbinghaus forgetting curve)
from .decay_scorer import (  # noqa: E402
    AccessRecord,
    DecayScorerStats,
    MemoryDecayScorer,
    get_decay_scorer,
    reset_decay_scorer,
)

# V12.4 COGNITIVE BOOST: Memory Pressure Monitor
from .memory_pressure_monitor import (  # noqa: E402
    EvictionEvent,
    MemoryPressureMonitor,
    MemorySnapshot,
    PressureLevel,
    PressureStats,
    get_pressure_monitor,
    reset_pressure_monitor,
)
from .namespace_manager import NamespaceInfo, RAGNamespaceManager  # noqa: E402

# V12.4 COGNITIVE BOOST: Plan-Aware Context Filter (arxiv:2512.16970)
from .plan_context_filter import (  # noqa: E402
    FilterResult,
    FilterStats,
    PlanContextFilter,
    ScoredItem,
    get_plan_context_filter,
    reset_plan_context_filter,
)

# V12.4 COGNITIVE BOOST: Pointer Memory (arxiv:2511.22729)
from .pointer_memory import (  # noqa: E402
    Pointer,
    PointerMemory,
    PointerStats,
    get_pointer_memory,
    reset_pointer_memory,
)

# V12.4 OPERATION PRISM: Multi-tenant memory isolation
from .tenant_memory import DEFAULT_TENANT, TenantMemoryService  # noqa: E402

# Backward compatibility aliases (DEPRECATED - remove in V13.0)
# Allows legacy imports to work transparently while we migrate
SuccessMemory = SuccessMemoryV2
get_success_memory = get_success_memory_v2

__all__ = [
    # Auto-Memory (V7.5)
    "AutoMemory",
    "get_auto_memory",
    "MemoryEntry",
    # Success Memory (V7.6)
    "SuccessMemory",
    "SuccessEntry",
    "get_success_memory",
    # V12.4.1 Epic 1.4: LanceDB-backed memory V2
    "SuccessMemoryV2",
    "get_success_memory_v2",
    "reset_success_memory_v2",
    "StrategyBlacklistV2",
    "BlacklistedStrategy",
    "get_strategy_blacklist_v2",
    "reset_strategy_blacklist_v2",
    # Project Memory RAG (V7.8 Phase 10c)
    "ProjectMemory",
    "Chunk",
    "ScoredChunk",
    "IndexStats",
    # Backend Abstraction (V7.9 Phase 10f + 10g)
    "MemoryBackend",
    "TfidfBackend",
    "Bm25Backend",
    "DenseBackend",
    "BM25S_AVAILABLE",
    "LANCEDB_AVAILABLE",
    "SENTENCE_TRANSFORMERS_AVAILABLE",
    # Service Layer (V9.1)
    "MemoryService",
    "MemoryStatus",
    "LearnResult",
    "ForgetResult",
    "QueryResult",
    # V13.0 MEMORIA UNIVERSALIS
    "UniversalIngestor",
    "DOCLING_AVAILABLE",
    "RAGNamespaceManager",
    "NamespaceInfo",
    # V12.4 OPERATION PRISM: Multi-tenant
    "TenantMemoryService",
    "DEFAULT_TENANT",
    # V12.4 COGNITIVE BOOST: Conversation history
    "ConversationStore",
    "ConversationSession",
    "ConversationTurn",
    "ConversationSummary",
    "ConversationSearchResult",
    # V12.4 COGNITIVE BOOST: Context Compressor
    "ContextCompressor",
    "CompressTurn",
    "CompressionResult",
    "ContextShift",
    "get_compressor",
    "reset_compressor",
    # V12.4 COGNITIVE BOOST: Cache Manager
    "CacheManager",
    "CacheEntry",
    "CacheStats",
    "get_cache_manager",
    "reset_cache_manager",
    # V12.4 COGNITIVE BOOST: Memory Pressure Monitor
    "MemoryPressureMonitor",
    "MemorySnapshot",
    "EvictionEvent",
    "PressureLevel",
    "PressureStats",
    "get_pressure_monitor",
    "reset_pressure_monitor",
    # V12.4 COGNITIVE BOOST: Context Window Tracker
    "ContextWindowTracker",
    "ContextUsageRecord",
    "CompressionEvent",
    "ContextTrackerStats",
    "get_context_tracker",
    "reset_context_tracker",
    # V12.4 COGNITIVE BOOST: Memory Decay Scorer (Ebbinghaus curve)
    "MemoryDecayScorer",
    "AccessRecord",
    "DecayScorerStats",
    "get_decay_scorer",
    "reset_decay_scorer",
    # V12.4 COGNITIVE BOOST: Pointer Memory (arxiv:2511.22729)
    "PointerMemory",
    "Pointer",
    "PointerStats",
    "get_pointer_memory",
    "reset_pointer_memory",
    # V12.4 COGNITIVE BOOST: Plan-Aware Context Filter (arxiv:2512.16970)
    "PlanContextFilter",
    "ScoredItem",
    "FilterResult",
    "FilterStats",
    "get_plan_context_filter",
    "reset_plan_context_filter",
    # V12.4 COGNITIVE BOOST: Adaptive Memory Organizer (arxiv:2502.12110)
    "AdaptiveMemoryOrganizer",
    "MemoryNote",
    "MemoryRetrievalResult",
    "OrganizerStats",
    "get_adaptive_memory_organizer",
    "reset_adaptive_memory_organizer",
]
