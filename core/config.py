"""
Configuration Management - NEXUS V12.4

Load configuration from:
1. pyproject.toml (version source of truth)
2. .env file (runtime overrides)
3. Environment variables
4. Default values
"""

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - exercised only in dependency-light environments
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False

from .provider_registry import build_provider_snapshot, get_default_model
from .version import NEXUS_CODENAME, NEXUS_VERSION

# =============================================================================
# Feature Flags - Safe toggles for experimental/dangerous features
# =============================================================================


@dataclass
class FeatureFlags:
    """
    Feature flags for safe progressive rollout.

    All flags default to safe production values.
    Override via NEXUS_FF_<FLAG_NAME>=true|false in env.
    """

    # RAG Pipeline
    rag_datamarking: bool = True  # Spotlighter datamarking on RAG results (OWASP LLM01 defense)
    rag_hybrid_backend: bool = True  # Enable Dense+BM25 hybrid retrieval
    rag_dense_backend: bool = True  # Enable dense (semantic) backend

    # Security
    sandbox_enabled: bool = True  # OS-level code sandbox (Docker) by default
    kernel_fail_closed: bool = True  # KERNEL exits on missing hash (fail-closed)
    host_execution_allowed: bool = False  # Allow validated host execution when sandbox is unavailable

    # Execution
    headless_mode: bool = False  # Deterministic JSON output, no TTY
    streaming_enabled: bool = True  # Real-time token streaming
    prompt_caching: bool = True  # Anthropic prompt caching (90% savings on cache hits)

    # Observability
    otel_enabled: bool = False  # OpenTelemetry export
    telemetry_jsonl: bool = True  # Legacy JSONL telemetry

    # Evolution
    evolution_llm_judge: bool = False  # LLM-as-judge for mutations (deprecated)
    evolution_deterministic: bool = True  # Deterministic fitness (AST+pytest only)

    # Experimental
    rust_acceleration: bool = False  # Use Rust native extensions if compiled
    slm_triage: bool = False  # Route trivial tasks to local SLM

    @classmethod
    def from_env(cls) -> "FeatureFlags":
        """Load feature flags from environment variables."""
        flags = cls()
        for flag_name in flags.__dataclass_fields__:
            env_key = f"NEXUS_FF_{flag_name.upper()}"
            env_val = os.getenv(env_key)
            if env_val is not None:
                setattr(flags, flag_name, env_val.lower() in ("true", "1", "yes"))
        return flags


class Config:
    """NEXUS Configuration - Single source of truth for version"""

    def __init__(self):
        # Load .env if present
        load_dotenv()

        # ====================================================================
        # VERSION (pyproject.toml/package metadata is canonical)
        # ====================================================================
        self.nexus_version: str = NEXUS_VERSION
        self.nexus_codename: str = NEXUS_CODENAME

        # ====================================================================
        # FEATURE FLAGS
        # ====================================================================
        self.features: FeatureFlags = FeatureFlags.from_env()

        # CLI Paths
        self.gemini_cli_path: str = os.getenv("GEMINI_CLI_PATH", "gemini")
        self.claude_cli_path: str = os.getenv("CLAUDE_CLI_PATH", "claude")

        # Orchestration
        self.max_stalemate_count: int = int(os.getenv("MAX_STALEMATE_COUNT", "5"))
        self.timeout: int = int(os.getenv("TIMEOUT", "600"))  # seconds
        self.cfl_timeout: int = int(os.getenv("CFL_TIMEOUT", "60"))  # CFL validation timeout (fast)

        # Stagnation Detection
        self.stagnation_similarity_threshold: float = float(os.getenv("STAGNATION_SIMILARITY_THRESHOLD", "0.8"))

        # Memory
        self.compression_threshold_tokens: int = int(os.getenv("COMPRESSION_THRESHOLD_TOKENS", "100000"))

        # Workspace
        self.workspace_path: Path = Path(os.getenv("WORKSPACE_PATH", "./workspace"))

        # NEXUS Root Directory (defaults to current directory)
        self.nexus_root: Path = Path(os.getenv("NEXUS_ROOT", ".")).resolve()

        # Logging
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")

        # UI
        self.ui_verbose: bool = os.getenv("UI_VERBOSE", "False").lower() == "true"
        # V7.5: Configurable output limit for REPL streaming (default 5000 chars)
        self.console_output_limit: int = int(os.getenv("CONSOLE_OUTPUT_LIMIT", "5000"))

        # ====================================================================
        # EVOLUTION PARAMETERS (Q1-Q4 Decisions - 2025-11-21)
        # ====================================================================

        # Q1C: Max Children
        self.max_children_concurrent: int = int(os.getenv("MAX_CHILDREN_CONCURRENT", "5"))
        self.max_children_stable: int = int(os.getenv("MAX_CHILDREN_STABLE", "10"))
        self.stable_mode_threshold: int = int(os.getenv("STABLE_MODE_THRESHOLD", "5"))

        # Q2C: Fitness Metrics (4 axes with scalability)
        self.fitness_metrics = {"coding": 0.30, "reasoning": 0.30, "creativity": 0.25, "scalability": 0.15}

        # Q3B: Rate Limiting (3 gen/day)
        # Note: 8h limit was too restrictive for development - reduced to 0.1h (6 min)
        # For production, set MIN_HOURS_BETWEEN_GEN=8 in .env
        self.max_generations_per_day: int = int(os.getenv("MAX_GEN_PER_DAY", "10"))
        self.min_hours_between_gen: float = float(os.getenv("MIN_HOURS_BETWEEN_GEN", "0.1"))

        # Aliases for rate_limiter.py compatibility
        self.min_hours_between_generations = self.min_hours_between_gen
        self.max_children_per_generation = self.max_children_concurrent

        # Q4B: Evaluation Timeline
        self.min_eval_hours: int = int(os.getenv("MIN_EVAL_HOURS", "24"))
        self.recommended_eval_hours: int = int(os.getenv("RECOMMENDED_EVAL_HOURS", "48"))
        self.critical_review_hours: int = int(os.getenv("CRITICAL_REVIEW_HOURS", "72"))

        # Evolution Triggers
        self.repl_turns_trigger: int = int(os.getenv("REPL_TURNS_TRIGGER", "50"))

        # V7.5 HIVE MIND: Red Team Validation
        # Red Team is now OPTIONAL by default (was blocking all promotions)
        # Set RED_TEAM_MANDATORY=True to enforce strict alignment validation
        self.red_team_mandatory: bool = os.getenv("RED_TEAM_MANDATORY", "False").lower() == "true"
        self.red_team_min_score: float = float(os.getenv("RED_TEAM_MIN_SCORE", "0.60"))

        # V8.2.0c: Red Team validation for spawned agents
        # Validates generated prompts for dangerous patterns before saving
        self.redteam_spawn_enabled: bool = os.getenv("REDTEAM_SPAWN_ENABLED", "True").lower() == "true"
        self.redteam_spawn_block_on_fail: bool = os.getenv("REDTEAM_SPAWN_BLOCK", "False").lower() == "true"

        # ====================================================================
        # NOTIFICATION SYSTEM
        # ====================================================================

        # Email (SMTP - disabled by default, requires configuration)
        self.email_enabled: bool = os.getenv("EMAIL_ENABLED", "False").lower() == "true"
        self.smtp_server: str = os.getenv("SMTP_SERVER", "")
        self.smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
        self.email_from: str = os.getenv("EMAIL_FROM", "")
        self.email_to: str = os.getenv("EMAIL_TO", "")
        self.email_password: str | None = os.getenv("NEXUS_EMAIL_PASSWORD")

        # Other Notifications
        self.desktop_notifications: bool = os.getenv("DESKTOP_NOTIF", "False").lower() == "true"
        self.webhook_url: str | None = os.getenv("WEBHOOK_URL")

        # ====================================================================
        # SECURITY & GOVERNANCE
        # ====================================================================

        # GCP Control
        self.gcp_children_blocked: bool = True  # Hardcoded for security
        self.gcp_approval_required: bool = True  # Hardcoded

        # Red Team - MANDATORY every generation (V7 Security)
        self.red_team_frequency: int = 1  # V7: Always run Red Team (was 5)
        self.red_team_fail_threshold: int = int(os.getenv("RED_TEAM_FAIL_THRESHOLD", "2"))

        # ====================================================================
        # AUTO-PROMOTION (V7) - Opt-in, default OFF
        # ====================================================================
        self.auto_promotion_enabled: bool = os.getenv("AUTO_PROMOTION", "False").lower() == "true"
        self.auto_promote_improvement_pct: float = float(os.getenv("AUTO_PROMOTE_PCT", "3.0"))
        self.auto_promote_min_confidence: float = 0.95  # 95% confidence required
        self.auto_promote_min_red_team_score: float = 0.90  # 90% alignment required

        # ====================================================================
        # MODEL ROUTING (V7 Chrysalis - Claude Opus/Sonnet + Gemini 3 Pro/Flash)
        # ====================================================================

        # API Keys (V12.4: SDK-native drivers prefer API keys over CLI)
        # When set, the factory creates SDK drivers instead of CLI subprocess drivers
        self.anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
        self.google_api_key: str | None = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        self.deepseek_api_key: str | None = os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPEEK_API_KEY")
        self.kimi_api_key: str | None = os.getenv("KIMI_API_KEY")
        self.openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
        self.minimax_api_key: str | None = os.getenv("MINIMAX_API_KEY")

        # Driver mode: "auto" (SDK when key available, else CLI), "sdk", "cli"
        self.driver_mode: str = os.getenv("NEXUS_DRIVER_MODE", "auto")

        # Claude models
        self.claude_opus_model: str = os.getenv("CLAUDE_OPUS_MODEL", get_default_model("anthropic", "opus"))
        self.claude_sonnet_model: str = os.getenv("CLAUDE_SONNET_MODEL", get_default_model("anthropic", "sonnet"))

        # Gemini models (V7 Sprint 6: Gemini 3 Pro with task routing)
        self.gemini_default_model: str = os.getenv("GEMINI_MODEL", get_default_model("google", "pro"))
        self.gemini_pro_model: str = os.getenv("GEMINI_PRO_MODEL", get_default_model("google", "pro"))
        self.gemini_flash_model: str = os.getenv("GEMINI_FLASH_MODEL", get_default_model("google", "flash"))
        self.deepseek_model: str = os.getenv("DEEPSEEK_MODEL") or os.getenv(
            "DEEPEEK_MODEL", get_default_model("deepseek", "chat")
        )
        self.kimi_model: str = os.getenv("KIMI_MODEL", get_default_model("kimi", "thinking"))
        self.openai_model: str = os.getenv("OPENAI_MODEL", get_default_model("openai", "flagship"))
        self.openai_fast_model: str = os.getenv("OPENAI_FAST_MODEL", get_default_model("openai", "balanced"))
        self.minimax_model: str = os.getenv("MINIMAX_MODEL", get_default_model("minimax", "reasoning"))
        self.minimax_fast_model: str = os.getenv("MINIMAX_FAST_MODEL", get_default_model("minimax", "chat"))

        # Task types routed to Opus (complex, creative, security-critical)
        self.opus_task_types: list = ["brainstorm", "redteam", "architect", "evolution"]
        # Task types routed to Sonnet (simpler, faster)
        self.sonnet_task_types: list = ["tool", "validation", "simple", "format"]

        # Task types routed to Gemini 3 Pro (complex reasoning, research)
        self.gemini_pro_tasks: list = ["reasoning", "research", "analysis", "brainstorm", "evolution"]
        # Task types routed to Gemini Flash (simple, fast)
        self.gemini_flash_tasks: list = ["simple", "format", "validation", "tool"]

        # ====================================================================
        # V7 SPRINT 2: OPTIMIZATION FLAGS
        # ====================================================================

        # Benchmark Mode (standard vs bootcamp)
        # standard: Real difficult tasks (requires high performance)
        # bootcamp: Simplified tasks for evolution validation (low latency tolerance)
        self.benchmark_mode: str = os.getenv("BENCHMARK_MODE", "standard")

        # Tiered Validation (1=syntax, 2=smoke, 3=benchmark, 4=redteam)
        self.validation_tier_default: int = int(os.getenv("VALIDATION_TIER", "4"))
        self.validation_use_tiered: bool = os.getenv("USE_TIERED_VALIDATION", "True").lower() == "true"

        # Parallel Benchmarks
        self.parallel_benchmark_workers: int = int(os.getenv("BENCHMARK_WORKERS", "4"))
        self.benchmark_task_timeout: int = int(os.getenv("BENCHMARK_TIMEOUT", "60"))

        # Agent Metrics (DyLAN scoring)
        self.agent_metrics_enabled: bool = os.getenv("AGENT_METRICS", "True").lower() == "true"
        self.agent_metrics_window: int = int(os.getenv("AGENT_METRICS_WINDOW", "100"))

        # ====================================================================
        # HYBRID SWARM ENGINE (V7 Sprint 9)
        # ====================================================================

        # Enable/Disable Swarm Engine
        self.swarm_enabled: bool = os.getenv("SWARM_ENABLED", "True").lower() == "true"

        # Negotiation settings
        self.swarm_negotiation_enabled: bool = os.getenv("SWARM_NEGOTIATION", "True").lower() == "true"
        self.swarm_negotiation_max_turns: int = int(os.getenv("SWARM_NEGOTIATION_TURNS", "4"))

        # Mode defaults
        self.swarm_default_mode: str = os.getenv("SWARM_DEFAULT_MODE", "ping_pong")
        self.swarm_skip_trivial: bool = os.getenv("SWARM_SKIP_TRIVIAL", "True").lower() == "true"

        # Execution limits
        self.swarm_max_rounds: int = int(os.getenv("SWARM_MAX_ROUNDS", "6"))

        # V7.5 HIVE MIND: SWARM auto-route enabled by default for MODERATE+ tasks
        # Use /swarm <task> for explicit swarm mode, or disable with SWARM_AUTO_ROUTE=False
        self.swarm_auto_route: bool = os.getenv("SWARM_AUTO_ROUTE", "True").lower() == "true"

        # V7.5 Phase 9: Fast Path for trivial conversational inputs
        # Bypasses FSM entirely for greetings, thanks, etc. Target: <2s response
        self.fast_path_enabled: bool = os.getenv("FAST_PATH_ENABLED", "True").lower() == "true"

        # ====================================================================
        # V8.0 TRUE HIVE MIND SETTINGS
        # ====================================================================
        # True Hive Mind: Collaborative intelligence for COMPLEX/EXPERT tasks
        # - 7 phases: Analysis, Debate, Architecture, Execution, Diagnosis, Retry, Consolidation
        # - 4 User Breakpoints: After debate, before spawn, after diagnosis, consolidation

        # Enable/Disable V8 Hive Mind (falls back to V7 Swarm if disabled)
        self.hive_mind_enabled: bool = os.getenv("HIVE_MIND_ENABLED", "True").lower() == "true"

        # Route MODERATE complexity to Hive Mind (True) or V7 Swarm (False)
        # COMPLEX/EXPERT always goes to Hive Mind when enabled
        self.hive_mind_moderate: bool = os.getenv("HIVE_MIND_MODERATE", "True").lower() == "true"

        # Token budget per Hive Mind task (prevents runaway costs)
        self.hive_mind_budget_limit: int = int(os.getenv("HIVE_MIND_BUDGET", "50000"))

        # Maximum debate turns before forced consensus
        self.hive_mind_max_debate_turns: int = int(os.getenv("HIVE_MIND_MAX_DEBATE", "10"))

        # Minimum debate turns (even if consensus reached early)
        self.hive_mind_min_debate_turns: int = int(os.getenv("HIVE_MIND_MIN_DEBATE", "3"))

        # Enable user breakpoints (pause for approval at key decisions)
        self.hive_mind_breakpoints_enabled: bool = os.getenv("HIVE_MIND_BREAKPOINTS", "True").lower() == "true"

        # Maximum retry attempts before escalation
        self.hive_mind_max_retries: int = int(os.getenv("HIVE_MIND_MAX_RETRIES", "3"))

        # Agreement threshold to skip debate (0.0-1.0)
        self.hive_mind_agreement_threshold: float = float(os.getenv("HIVE_MIND_AGREEMENT_THRESHOLD", "0.85"))

        # NOTE: PTY mode removed in V7.6 (never worked)
        # See: docs/archive/pty_mode_v7_archived.py

        # ====================================================================
        # TELEMETRY (V7 Sprint 10) & BUDGET CAP (Phase 14d)
        # ====================================================================

        self.telemetry_enabled: bool = os.getenv("TELEMETRY_ENABLED", "True").lower() == "true"
        self.telemetry_file: str = os.getenv("TELEMETRY_FILE", "workspace/telemetry.jsonl")

        # Phase 14d: Budget Cap - Daily spending limit in USD
        # Prevents runaway costs in Evolution/Swarm intensive modes
        # Set to 0 to disable budget enforcement
        self.budget_limit_usd: float = float(os.getenv("BUDGET_LIMIT_USD", "50.0"))
        self.budget_warning_threshold: float = float(os.getenv("BUDGET_WARNING_PCT", "0.80"))
        self.budget_critical_threshold: float = float(os.getenv("BUDGET_CRITICAL_PCT", "0.90"))

        # V12.4: Response cache (shared across SDK drivers)
        self.response_cache_size: int = int(os.getenv("RESPONSE_CACHE_SIZE", "500"))
        self.response_cache_ttl: float = float(os.getenv("RESPONSE_CACHE_TTL", "300"))

        # V12.4: Routing policy (balanced | cost_optimized | quality_optimized)
        self.routing_policy: str = os.getenv("ROUTING_POLICY", "balanced")

        # V12.4: Memory backend (auto | dense | bm25 | tfidf)
        self.project_memory_backend: str = os.getenv("PROJECT_MEMORY_BACKEND", "auto")
        self.project_memory_max_chunks: int = int(os.getenv("PROJECT_MEMORY_MAX_CHUNKS", "5000"))

        # ====================================================================
        # GEMINI SESSION PERSISTENCE (V7 Sprint 12)
        # ====================================================================
        # Uses Gemini's built-in session management with --resume latest
        # First call creates session, subsequent calls resume it
        # Benefits: ~14k cached tokens, reduced latency on follow-up calls

        # Enable session resume mode (DEFAULT: True for multi-turn conversations)
        self.gemini_persistent_mode: bool = os.getenv("GEMINI_PERSISTENT_MODE", "True").lower() == "true"

        # Approval mode for yolo (safe with restricted tools whitelist)
        self.gemini_approval_mode: str = os.getenv("GEMINI_APPROVAL_MODE", "yolo")

        # Use JSON output mode for structured responses
        self.gemini_stream_json: bool = os.getenv("GEMINI_STREAM_JSON", "True").lower() == "true"

        # ====================================================================
        # RESPONSE STREAMING (V7.7 Phase 15)
        # ====================================================================
        # Enable real-time token streaming during agent responses
        # When True, responses stream character-by-character to the REPL
        # When False, responses appear only after completion (default V7.6 behavior)
        self.streaming_enabled: bool = os.getenv("STREAMING_ENABLED", "True").lower() == "true"

        # Session timeout (seconds)
        self.gemini_persistent_timeout: float = float(os.getenv("GEMINI_PERSISTENT_TIMEOUT", "300"))

        # ====================================================================
        # V12.3 SCALE-OUT - Multi-Instance Support
        # ====================================================================

        # Redis URL for shared state
        self.redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")

        # Use Redis for workflow registry (enables multi-instance)
        self.use_redis_workflows: bool = os.getenv("USE_REDIS_WORKFLOWS", "True").lower() == "true"

        # Use Redis for hibernation state (opt-in, SQLite default)
        self.use_redis_hibernation: bool = os.getenv("USE_REDIS_HIBERNATION", "False").lower() == "true"

        # TTL for completed/failed workflows (hours)
        self.workflow_ttl_hours: int = int(os.getenv("WORKFLOW_TTL_HOURS", "24"))

        # Provider compatibility snapshot for runtime, CI, and docs reuse.
        self.provider_snapshot = build_provider_snapshot(self)

    def to_dict(self) -> dict:
        """Export config as dict"""
        return {
            "gemini_cli_path": self.gemini_cli_path,
            "claude_cli_path": self.claude_cli_path,
            "max_stalemate_count": self.max_stalemate_count,
            "timeout": self.timeout,
            "stagnation_similarity_threshold": self.stagnation_similarity_threshold,
            "compression_threshold_tokens": self.compression_threshold_tokens,
            "workspace_path": str(self.workspace_path),
            "log_level": self.log_level,
            "ui_verbose": self.ui_verbose,
            "benchmark_mode": self.benchmark_mode,
            "driver_mode": self.driver_mode,
            "claude_opus_model": self.claude_opus_model,
            "claude_sonnet_model": self.claude_sonnet_model,
            "gemini_pro_model": self.gemini_pro_model,
            "gemini_flash_model": self.gemini_flash_model,
            "deepseek_model": self.deepseek_model,
            "kimi_model": self.kimi_model,
            "openai_model": self.openai_model,
            "minimax_model": self.minimax_model,
        }


def load_config() -> Config:
    """
    Load configuration

    Returns:
        Config instance
    """
    return Config()


class OrchestratorConfig:
    """
    Lightweight orchestrator configuration for SDK driver factory.

    Accepts keyword arguments to override individual settings.
    Used primarily in tests and programmatic instantiation where
    the full Config class is not needed.

    Example:
        config = OrchestratorConfig(driver_mode="sdk", kimi_api_key="sk-...")
        factory = AsyncDriverFactory(config, workspace_path=Path("."))
    """

    def __init__(self, **kwargs):
        # API keys
        self.anthropic_api_key: str | None = kwargs.get("anthropic_api_key", os.getenv("ANTHROPIC_API_KEY"))
        self.google_api_key: str | None = kwargs.get(
            "google_api_key", os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        )
        self.deepseek_api_key: str | None = kwargs.get(
            "deepseek_api_key", os.getenv("DEEPSEEK_API_KEY") or os.getenv("DEEPEEK_API_KEY")
        )
        self.kimi_api_key: str | None = kwargs.get("kimi_api_key", os.getenv("KIMI_API_KEY"))
        self.openai_api_key: str | None = kwargs.get("openai_api_key", os.getenv("OPENAI_API_KEY"))
        self.minimax_api_key: str | None = kwargs.get("minimax_api_key", os.getenv("MINIMAX_API_KEY"))

        # Driver mode
        self.driver_mode: str = kwargs.get("driver_mode", os.getenv("NEXUS_DRIVER_MODE", "auto"))

        # Common settings
        self.timeout: float = float(kwargs.get("timeout", os.getenv("TIMEOUT", "300")))
        self.max_tokens: int = int(kwargs.get("max_tokens", 8192))
        self.response_cache_size: int = int(kwargs.get("response_cache_size", 500))
        self.response_cache_ttl: float = float(kwargs.get("response_cache_ttl", 300.0))
        self.routing_policy: str = kwargs.get("routing_policy", "balanced")
        self.workspace_path: Path = Path(kwargs.get("workspace_path", "./workspace"))
        self.deepseek_model: str = kwargs.get(
            "deepseek_model",
            os.getenv("DEEPSEEK_MODEL") or os.getenv("DEEPEEK_MODEL") or get_default_model("deepseek", "chat"),
        )
        self.kimi_model: str = kwargs.get("kimi_model", get_default_model("kimi", "thinking"))
        self.openai_model: str = kwargs.get("openai_model", get_default_model("openai", "flagship"))
        self.openai_fast_model: str = kwargs.get("openai_fast_model", get_default_model("openai", "balanced"))
        self.minimax_model: str = kwargs.get("minimax_model", get_default_model("minimax", "reasoning"))
        self.minimax_fast_model: str = kwargs.get("minimax_fast_model", get_default_model("minimax", "chat"))

        # Apply any remaining kwargs as attributes
        for key, value in kwargs.items():
            if not hasattr(self, key):
                setattr(self, key, value)
