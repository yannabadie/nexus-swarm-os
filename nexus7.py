#!/usr/bin/env python3
"""
NEXUS - The Omniscient REPL
Persistent FSM Orchestrator with Hybrid Drivers
(Version loaded from package metadata / pyproject.toml)

Architecture:
- FSM (Finite State Machine) for persistent state management
- Claude Hybrid Driver (natural language + XML tool blocks)
- Gemini JSON Driver (strict JSON mode)
- Adaptive stagnation detection
- Bootstrap verification at startup
"""

import argparse
import asyncio
import atexit
import contextlib
import importlib.util
import json

# Load version from .env (single source of truth)
import os
import signal
import sys
from pathlib import Path

# Fix Windows ANSI colors - V9.1.2: Ultra-simple approach
# Calling os.system('') triggers cmd.exe to initialize VT100 mode
# This side-effect enables ANSI escape sequences in the console
# Source: https://bugs.python.org/issue40134
if sys.platform == "win32":
    os.system("")  # Enable ANSI escape codes (Windows 10 1607+)
    # Ensure stdout/stderr can emit UTF-8 on Windows consoles.
    for _stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            _stream.reconfigure(encoding="utf-8", errors="replace")

import logging
from datetime import UTC

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - exercised only in dependency-light environments
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False

from core.provider_registry import build_provider_snapshot, get_replacement, refresh_provider_registry
from core.version import NEXUS_CODENAME, NEXUS_VERSION

load_dotenv()

# Configure logging EARLY - FORCE override any existing config
# Default to WARNING to hide INFO messages in production
_log_level = os.getenv("LOG_LEVEL", "WARNING").upper()
_log_level_int = getattr(logging, _log_level, logging.WARNING)
# Force reconfigure by clearing root logger handlers
logging.root.handlers.clear()
logging.basicConfig(
    level=_log_level_int,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,  # Python 3.8+ - forces reconfiguration
)

# Constantes
ENV_TEMPLATE = f"""# NEXUS V{NEXUS_VERSION} {NEXUS_CODENAME} Configuration
GEMINI_CLI_PATH=gemini
CLAUDE_CLI_PATH=claude
MAX_STALEMATE_COUNT=5
STAGNATION_SIMILARITY_THRESHOLD=0.8
WORKSPACE_PATH=./workspace
LOG_LEVEL=WARNING
UI_VERBOSE=False
"""

# =============================================================================
# V8.4.5: Graceful Shutdown Handlers
# =============================================================================

_shutdown_requested = False
_async_factory = None


def _cleanup_processes():
    """
    Cleanup function called at exit.

    V8.4.5: Ensures all subprocess and async processes are terminated.
    """
    global _async_factory

    # V12.4: Legacy driver cleanup removed (SDK drivers handle cleanup automatically)
    # Cleanup async factory if available
    if _async_factory:
        try:
            # Run cleanup in a new event loop since atexit runs outside async context
            loop = asyncio.new_event_loop()
            loop.run_until_complete(_async_factory.cancel_all())
            loop.close()
        except Exception:
            pass


def _signal_handler(signum, frame):
    """
    Signal handler for graceful shutdown.

    V8.4.5: Handles SIGINT and SIGTERM for graceful termination.
    """
    global _shutdown_requested

    if _shutdown_requested:
        # Second signal - force exit
        print("\n[SHUTDOWN] Force exit requested", file=sys.stderr)
        sys.exit(1)

    _shutdown_requested = True
    sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    print(f"\n[SHUTDOWN] Received {sig_name}, cleaning up...", file=sys.stderr)

    # Cleanup will happen via atexit or explicit call
    raise KeyboardInterrupt


def setup_signal_handlers():
    """
    Setup signal handlers for graceful shutdown.

    V8.4.5: Cross-platform signal handling.
    - Windows: SIGINT only (SIGTERM not supported)
    - Unix: SIGINT and SIGTERM
    """
    # Register atexit handler first (always works)
    atexit.register(_cleanup_processes)

    # SIGINT (Ctrl+C) - works on all platforms
    signal.signal(signal.SIGINT, _signal_handler)

    # SIGTERM - Unix only
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _signal_handler)


# =============================================================================
# Runtime-Safe Bootstrap and Headless Overrides
# =============================================================================


def bootstrap(config=None, workspace_path: Path | None = None):
    """Driver-mode aware bootstrap used by the distributed runtime."""
    print(f"NEXUS V{NEXUS_VERSION} {NEXUS_CODENAME} bootstrap...")

    from core.config import load_config
    from core.meta.cli_inspector import CLIInspector

    config = config or load_config()

    print(f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    required_packages = ["prompt_toolkit", "rich", "pydantic", "tiktoken"]
    missing = []
    for pkg in required_packages:
        if not importlib.util.find_spec(pkg):
            missing.append(pkg)

    if missing:
        print(f"Missing packages: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)}")
        sys.exit(1)

    workspace = Path(workspace_path or getattr(config, "workspace_path", "workspace"))
    config.workspace_path = workspace
    for directory in [workspace / "_IO_BUFFER", workspace / ".nexus", workspace / "logs", workspace / "sessions"]:
        directory.mkdir(parents=True, exist_ok=True)

    env_path = Path(".env")
    if not env_path.exists():
        env_path.write_text(ENV_TEMPLATE, encoding="utf-8")

    inspector = CLIInspector()
    provider_snapshot = build_provider_snapshot(config)
    gemini_cli_info = inspector.inspect_gemini()
    claude_cli_info = inspector.inspect_claude()

    driver_mode = config.driver_mode.lower()
    gemini_uses_sdk = driver_mode == "sdk" or (driver_mode == "auto" and bool(config.google_api_key))
    claude_uses_sdk = driver_mode == "sdk" or (driver_mode == "auto" and bool(config.anthropic_api_key))

    if driver_mode == "sdk" and not config.google_api_key:
        print("SDK mode requires GOOGLE_API_KEY or GEMINI_API_KEY for Gemini.")
        sys.exit(1)
    if driver_mode == "sdk" and not config.anthropic_api_key:
        print("SDK mode requires ANTHROPIC_API_KEY for Claude.")
        sys.exit(1)
    if not gemini_uses_sdk and not gemini_cli_info.get("available"):
        print("Gemini CLI not available for the selected runtime path.")
        if "error" in gemini_cli_info:
            print(f"Error: {gemini_cli_info['error']}")
        sys.exit(1)
    if not claude_uses_sdk and not claude_cli_info.get("available"):
        print("Claude CLI not available for the selected runtime path.")
        if "error" in claude_cli_info:
            print(f"Error: {claude_cli_info['error']}")
        sys.exit(1)

    gemini_info = {
        "model": config.gemini_pro_model,
        "flash_model": config.gemini_flash_model,
        "provider": "gemini",
        "driver_mode": "sdk" if gemini_uses_sdk else "cli",
        "context_window": gemini_cli_info.get("context_window", 0),
        "version": gemini_cli_info.get("version", "SDK"),
    }
    claude_info = {
        "model": config.claude_sonnet_model,
        "opus_model": config.claude_opus_model,
        "provider": "claude",
        "driver_mode": "sdk" if claude_uses_sdk else "cli",
        "context_window": claude_cli_info.get("context_window", 0),
        "version": claude_cli_info.get("version", "SDK"),
    }

    print("Provider runtime:")
    print(f"  Gemini: {gemini_info['driver_mode']} | pro={gemini_info['model']} | flash={gemini_info['flash_model']}")
    print(f"  Claude: {claude_info['driver_mode']} | sonnet={claude_info['model']} | opus={claude_info['opus_model']}")
    additional_sdk = [
        provider
        for provider in provider_snapshot.get("available_sdk_providers", [])
        if provider not in {"anthropic", "google"}
    ]
    if additional_sdk:
        print(f"  Additional SDK providers detected: {', '.join(additional_sdk)}")
    for warning in provider_snapshot.get("warnings", []):
        stale_model = warning.split()[0]
        replacement = get_replacement(stale_model)
        if replacement:
            print(f"  Warning: {stale_model} -> {replacement}")
        else:
            print(f"  Warning: {warning}")

    return gemini_info, claude_info


async def headless_main(
    workspace_path: Path,
    task: str | None,
    output_path: str | None,
    config,
) -> int:
    """Unified headless runtime with strict JSON semantics."""
    import json
    from datetime import datetime

    from core.meta.cli_inspector import CLIInspector
    from core.runtime import NexusSessionRuntime

    timestamp = datetime.now(UTC).isoformat()
    config.workspace_path = workspace_path
    result: dict

    try:
        inspector = CLIInspector()
        driver_mode = config.driver_mode.lower()
        gemini_uses_sdk = driver_mode == "sdk" or (driver_mode == "auto" and bool(config.google_api_key))
        claude_uses_sdk = driver_mode == "sdk" or (driver_mode == "auto" and bool(config.anthropic_api_key))

        if driver_mode == "sdk" and (not config.google_api_key or not config.anthropic_api_key):
            raise RuntimeError("SDK mode requires both GOOGLE_API_KEY/GEMINI_API_KEY and ANTHROPIC_API_KEY.")
        if not gemini_uses_sdk and not inspector.inspect_gemini().get("available"):
            raise RuntimeError("Gemini CLI is required for the selected runtime path but is not available.")
        if not claude_uses_sdk and not inspector.inspect_claude().get("available"):
            raise RuntimeError("Claude CLI is required for the selected runtime path but is not available.")

        runtime = NexusSessionRuntime.from_config(config, workspace_path=workspace_path, interaction_mode="headless")
        result = runtime.execute_headless(task, timestamp=timestamp).to_dict()
    except TimeoutError:
        result = {
            "nexus_version": NEXUS_VERSION,
            "codename": NEXUS_CODENAME,
            "mode": "headless",
            "timestamp": timestamp,
            "task": task,
            "status": "failure",
            "driver": None,
            "output": None,
            "error": "Task execution timed out (300s)",
            "error_code": "HEADLESS_TIMEOUT",
            "warnings": [],
            "artifacts": [],
        }
    except Exception as e:
        warnings = []
        with contextlib.suppress(Exception):
            warnings = list(getattr(config, "provider_snapshot", {}).get("warnings", []))
        result = {
            "nexus_version": NEXUS_VERSION,
            "codename": NEXUS_CODENAME,
            "mode": "headless",
            "timestamp": timestamp,
            "task": task,
            "status": "failure",
            "driver": None,
            "output": None,
            "error": str(e),
            "error_code": type(e).__name__.upper(),
            "warnings": warnings,
            "artifacts": [],
        }

    json_output = json.dumps(result, indent=2, ensure_ascii=False)
    if output_path:
        Path(output_path).write_text(json_output, encoding="utf-8")
    else:
        print(json_output)

    return 0 if result["status"] == "success" else 1


# =============================================================================
# V9 CYBORG: Async Entry Point
# =============================================================================


async def async_main(workspace_path: Path, gemini_info: dict, claude_info: dict, pending_metadata: dict | None, config):
    """
    V9 Cyborg Async Entry Point.

    Wraps the V7 REPL in an async context, enabling:
    - Non-blocking user input (prompt_async)
    - Async LLM streaming
    - Graceful Ctrl+C cancellation

    Falls back to sync REPL if run_async() not available.
    """
    global _async_factory

    from core.interface_pkg.interface.repl import InteractiveNexusV7

    # V12.4: Initialize OpenTelemetry (if enabled)
    try:
        from core.observability.telemetry.otel_provider import init_otel

        init_otel(service_name="nexus-backend", service_version=NEXUS_VERSION)
    except Exception:
        pass  # OTel is optional

    # Initialize async driver factory for process management
    try:
        from core.drivers.async_factory import AsyncDriverFactory

        # Create factory instance (will be accessible via get_driver_factory)
        factory = AsyncDriverFactory(config, workspace_path)
        # Store in module for global access
        import core.drivers.async_factory as factory_module

        factory_module._global_factory = factory
        # V8.4.5: Store reference for graceful shutdown
        _async_factory = factory
    except ImportError:
        # Async drivers not available, continue with sync
        pass

    # Display pending review alerts (sync, fast)
    if pending_metadata:
        from core.notifications.repl_alert import get_repl_alert_message, should_block_evolution

        print(get_repl_alert_message(pending_metadata, config))
        if should_block_evolution(pending_metadata, config):
            print("\n[warning] Evolution is BLOCKED until review is completed.")
            print("   Use /review command to evaluate children.\n")

    # V12.4: Check for interrupted sessions (crash recovery)
    try:
        from core.fsm.event_sourcing import get_event_store

        event_store = get_event_store(workspace_path)
        interrupted = event_store.get_interrupted_sessions()
        if interrupted:
            print(f"\n[warning] Detected {len(interrupted)} interrupted session(s):")
            for sess in interrupted[:3]:
                print(
                    f"   - Session {sess['session_id']}: last state={sess['last_state']}, events={sess['event_count']}"
                )
            print("   Sessions can be resumed or will be trimmed on next boot.\n")
    except Exception:
        pass  # Non-critical

    repl = InteractiveNexusV7(workspace_path=workspace_path, gemini_info=gemini_info, claude_info=claude_info)

    # V9 Cyborg: Prefer async, fallback to sync
    if hasattr(repl, "run_async"):
        await repl.run_async()
    else:
        # Sync fallback (V7 mode)
        repl.run()


def main():
    """Entry point for NEXUS interactive REPL."""
    # V8.4.5: Setup graceful shutdown handlers early
    setup_signal_handlers()

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description=f"NEXUS V{NEXUS_VERSION} {NEXUS_CODENAME} - The Omniscient REPL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  nexus                     Launch interactive REPL
  nexus --verify            Verify installation (bootstrap only)
  nexus --version           Show version
  nexus --workspace ./myproject  Use custom workspace

Documentation: https://github.com/yannabadie/NEXUS
        """,
    )

    parser.add_argument("--verify", action="store_true", help="Run bootstrap verification only (no REPL)")

    parser.add_argument("--version", action="store_true", help="Show NEXUS version")

    parser.add_argument(
        "--workspace", type=str, default="./workspace", help="Workspace directory path (default: ./workspace)"
    )

    parser.add_argument(
        "--headless", action="store_true", help="Run in headless mode (no TTY, deterministic JSON output)"
    )

    parser.add_argument("--task", type=str, default=None, help="Task to execute in headless mode (requires --headless)")

    parser.add_argument(
        "--output", type=str, default=None, help="Output file for headless results (default: stdout as JSON)"
    )
    parser.add_argument(
        "--refresh-provider-registry",
        action="store_true",
        help="Refresh core/provider_registry.json from official provider APIs/docs and exit.",
    )

    args = parser.parse_args()

    if args.refresh_provider_registry:
        try:
            registry = refresh_provider_registry()
            print("Provider registry refreshed.")
            print(json.dumps(registry, indent=2, ensure_ascii=False))
            sys.exit(0)
        except Exception as e:
            print(f"Failed to refresh provider registry: {e}", file=sys.stderr)
            sys.exit(1)

    # Handle --version
    if args.version:
        print(f"NEXUS V{NEXUS_VERSION} {NEXUS_CODENAME} - The Omniscient REPL")
        print("Persistent FSM Orchestrator with Hybrid Drivers")
        print("https://github.com/yannabadie/NEXUS")
        sys.exit(0)

    # Headless mode uses the shared non-interactive session runtime.
    if args.headless:
        try:
            workspace_path = Path(args.workspace).resolve()
            workspace_path.mkdir(parents=True, exist_ok=True)

            from core.config import load_config

            config = load_config()
            config.workspace_path = workspace_path

            exit_code = asyncio.run(
                headless_main(workspace_path=workspace_path, task=args.task, output_path=args.output, config=config)
            )
            sys.exit(exit_code)
        except Exception as e:
            result = {
                "nexus_version": NEXUS_VERSION,
                "codename": NEXUS_CODENAME,
                "mode": "headless",
                "status": "failure",
                "error": str(e),
            }
            print(json.dumps(result, indent=2))
            sys.exit(1)

    try:
        workspace_path = Path(args.workspace).resolve()
        workspace_path.mkdir(parents=True, exist_ok=True)

        from core.config import load_config

        config = load_config()
        config.workspace_path = workspace_path

        # Bootstrap system (driver-mode aware verification for interactive mode)
        gemini_info, claude_info = bootstrap(config=config, workspace_path=workspace_path)

        # Handle --verify (exit after bootstrap)
        if args.verify:
            print("\n[ok] Bootstrap verification successful.")
            print(f"   NEXUS V{NEXUS_VERSION} {NEXUS_CODENAME} is ready to use.")
            sys.exit(0)

        # Import config and check pending reviews
        from core.notifications import check_pending_review

        # CHECK FOR PENDING REVIEW (Evolution notification system)
        pending_metadata = check_pending_review(workspace_path)

        # V12.4 PHASE 2: Crash recovery check
        from core.fsm.event_sourcing import FSMEventStore

        event_store = FSMEventStore(workspace_path)
        interrupted = event_store.get_interrupted_sessions()

        if interrupted:
            session_info = interrupted[-1]  # Most recent interrupted session
            print("\n[warning] Detected interrupted session")
            print(f"   Last state: {session_info['last_state']}")
            print(f"   Timestamp: {session_info['last_timestamp']}")
            print(f"   Events: {session_info['event_count']}")

            # Ask user if they want to resume (interactive mode only)
            response = input("\n   Resume previous session? [y/N]: ").strip().lower()
            if response in ("y", "yes"):
                print("   [ok] Resuming previous session state...")
                # Note: Actual state restoration would happen in async_main
                # For now, we just log this and continue with existing events
            else:
                print("   Starting new session (old events preserved for debugging)...")
        else:
            last_state = event_store.get_last_state()
            if last_state:
                print(f"[ok] Previous session ended cleanly ({last_state})")

        # V9 CYBORG: Launch via asyncio.run()
        asyncio.run(
            async_main(
                workspace_path=workspace_path,
                gemini_info=gemini_info,
                claude_info=claude_info,
                pending_metadata=pending_metadata,
                config=config,
            )
        )

    except KeyboardInterrupt:
        print(f"\n\n[shutdown] NEXUS V{NEXUS_VERSION} {NEXUS_CODENAME} terminated by user")
        # V8.4.5: Cleanup handled by atexit and signal handlers
        sys.exit(0)

    except Exception as e:
        print(f"\n[error] Fatal error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
