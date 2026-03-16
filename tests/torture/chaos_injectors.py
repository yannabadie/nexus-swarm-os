"""
Torture Protocol V8 - Chaos Injectors

Provides controlled failure injection for stress testing:
- CrashInjector: Simulate crashes at specific points
- RaceInjector: Introduce race conditions via delays
- CorruptionInjector: Corrupt files and data
"""

import asyncio
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


class CrashInjector:
    """
    Inject crashes at specific checkpoint/rollback points.

    Usage:
        injector = CrashInjector()

        # Crash on second checkpoint
        with injector.crash_after_n_checkpoints(2):
            await saga.checkpoint_phase("analysis", ...)
            await saga.checkpoint_phase("debate", ...)  # CRASH!

        # Crash during persist
        with injector.crash_during_persist():
            await saga._persist()  # CRASH!
    """

    def __init__(self):
        self.crash_count = 0
        self.crash_at = None

    @contextmanager
    def crash_after_n_checkpoints(self, n: int):
        """Crash after N successful checkpoints."""
        self.crash_count = 0
        self.crash_at = n

        def crashing_checkpoint(original_func):
            async def wrapper(*args, **kwargs):
                result = await original_func(*args, **kwargs)
                self.crash_count += 1
                if self.crash_count >= self.crash_at:
                    raise RuntimeError(f"CrashInjector: Crash after checkpoint {self.crash_count}")
                return result

            return wrapper

        try:
            yield crashing_checkpoint
        finally:
            self.crash_count = 0
            self.crash_at = None

    @contextmanager
    def crash_during_persist(self):
        """Crash during _persist() call."""

        async def crashing_persist(*args, **kwargs):
            raise RuntimeError("CrashInjector: Crash during persist")

        with patch("core.intelligence.hive_mind.saga_manager.SagaManager._persist", crashing_persist):
            yield

    @contextmanager
    def crash_during_fsync(self):
        """Crash during os.fsync() call."""

        def crashing_fsync(fd):
            raise OSError("CrashInjector: fsync failed")

        with patch("os.fsync", crashing_fsync):
            yield

    @contextmanager
    def crash_during_rename(self):
        """Crash during os.replace() atomic rename."""

        def crashing_replace(src, dst):
            raise OSError("CrashInjector: rename failed")

        with patch("os.replace", crashing_replace):
            yield

    @contextmanager
    def crash_at_phase(self, phase: str):
        """Crash when specific phase is checkpointed."""

        async def phase_crashing_checkpoint(original_func):
            async def wrapper(self_saga, phase_name, *args, **kwargs):
                if phase_name == phase:
                    raise RuntimeError(f"CrashInjector: Crash at phase {phase}")
                return await original_func(self_saga, phase_name, *args, **kwargs)

            return wrapper

        yield phase_crashing_checkpoint


class RaceInjector:
    """
    Introduce race conditions via delays.

    Usage:
        injector = RaceInjector()

        # Add delay to persist
        with injector.delay_persist(100):  # 100ms delay
            await saga._persist()

        # Concurrent checkpoints
        await injector.concurrent_checkpoints(saga, ["analysis", "debate"])
    """

    def __init__(self):
        self.delays = {}

    @contextmanager
    def delay_persist(self, delay_ms: int):
        """Add delay to _persist() calls."""
        original_persist = None

        async def delayed_persist(self_saga):
            await asyncio.sleep(delay_ms / 1000)
            if original_persist:
                return await original_persist(self_saga)

        # Note: Actual patching requires knowing the module path
        yield delayed_persist

    @contextmanager
    def delay_operation(self, delay_ms: int):
        """Generic delay context for any operation."""
        start = time.time()
        yield
        elapsed = (time.time() - start) * 1000
        if elapsed < delay_ms:
            time.sleep((delay_ms - elapsed) / 1000)

    async def concurrent_checkpoints(self, saga, phases: list, delay_between_ms: int = 0):
        """
        Execute multiple checkpoints concurrently.

        Returns:
            List of results (success/exception) for each checkpoint
        """

        async def checkpoint_with_delay(phase, index):
            if delay_between_ms > 0 and index > 0:
                await asyncio.sleep((delay_between_ms * index) / 1000)
            try:
                await saga.checkpoint_phase(
                    phase=phase, result={"test": True}, state=f"STATE_{phase.upper()}", context_index=index * 5
                )
                return {"phase": phase, "success": True}
            except Exception as e:
                return {"phase": phase, "success": False, "error": str(e)}

        tasks = [checkpoint_with_delay(phase, i) for i, phase in enumerate(phases)]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def concurrent_operations(self, operations: list, stagger_ms: int = 0):
        """
        Execute multiple async operations concurrently.

        Args:
            operations: List of async callables
            stagger_ms: Delay between starting each operation

        Returns:
            List of results
        """

        async def run_with_stagger(op, index):
            if stagger_ms > 0 and index > 0:
                await asyncio.sleep((stagger_ms * index) / 1000)
            try:
                return await op()
            except Exception as e:
                return {"error": str(e)}

        tasks = [run_with_stagger(op, i) for i, op in enumerate(operations)]
        return await asyncio.gather(*tasks, return_exceptions=True)


class CorruptionInjector:
    """
    Corrupt saga files for recovery testing.

    Usage:
        injector = CorruptionInjector()

        # Write corrupted JSON
        injector.corrupt_json(saga_file)

        # Truncate file
        injector.truncate_file(saga_file, bytes_to_keep=100)

        # Create empty file
        injector.create_empty_file(saga_file)
    """

    CORRUPTION_TYPES = [
        "invalid_json",
        "truncated",
        "empty",
        "wrong_encoding",
        "missing_fields",
        "extra_fields",
        "wrong_types",
    ]

    def corrupt_json(self, filepath: Path, corruption_type: str = "invalid_json"):
        """
        Corrupt a JSON file in various ways.

        Args:
            filepath: Path to JSON file
            corruption_type: Type of corruption to apply
        """
        filepath = Path(filepath)

        if corruption_type == "invalid_json":
            filepath.write_text("{invalid json here...", encoding="utf-8")

        elif corruption_type == "truncated":
            if filepath.exists():
                content = filepath.read_text(encoding="utf-8")
                filepath.write_text(content[: len(content) // 2], encoding="utf-8")
            else:
                filepath.write_text('{"truncated": true', encoding="utf-8")

        elif corruption_type == "empty":
            filepath.write_text("", encoding="utf-8")

        elif corruption_type == "wrong_encoding":
            filepath.write_bytes(b"\xff\xfe invalid unicode \x00\x01")

        elif corruption_type == "missing_fields":
            filepath.write_text('{"task_id": "test"}', encoding="utf-8")

        elif corruption_type == "extra_fields":
            if filepath.exists():
                try:
                    data = json.loads(filepath.read_text(encoding="utf-8"))
                    data["unknown_field_12345"] = "unexpected"
                    filepath.write_text(json.dumps(data), encoding="utf-8")
                except Exception:
                    filepath.write_text('{"extra": "field"}', encoding="utf-8")
            else:
                filepath.write_text('{"extra": "field"}', encoding="utf-8")

        elif corruption_type == "wrong_types":
            filepath.write_text('{"task_id": 12345, "checkpoints": "not_a_dict"}', encoding="utf-8")

    def truncate_file(self, filepath: Path, bytes_to_keep: int = 100):
        """Truncate file to specific size."""
        filepath = Path(filepath)
        if filepath.exists():
            content = filepath.read_bytes()
            filepath.write_bytes(content[:bytes_to_keep])
        else:
            filepath.write_bytes(b"x" * bytes_to_keep)

    def create_empty_file(self, filepath: Path):
        """Create an empty file (0 bytes)."""
        Path(filepath).write_text("")

    def create_locked_file(self, filepath: Path):
        """
        Create a file and hold a lock on it.

        Returns a context manager that releases the lock.
        """
        filepath = Path(filepath)

        # Create file if not exists
        if not filepath.exists():
            filepath.write_text("{}")

        # Platform-specific locking
        if os.name == "nt":  # Windows
            import msvcrt

            f = filepath.open("r+")
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return f
        else:  # Unix
            import fcntl

            f = filepath.open("r+")
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f

    def create_saga_with_unknown_phase(self, saga_dir: Path, task_id: str):
        """Create saga file with unknown phase name."""
        saga_file = saga_dir / f"{task_id}.json"
        saga_data = {
            "task_id": task_id,
            "checkpoints": {
                "unknown_phase_xyz": {
                    "phase": "unknown_phase_xyz",
                    "result": {},
                    "state": "UNKNOWN",
                    "timestamp": "2025-01-01T00:00:00",
                    "context_index": 0,
                }
            },
            "context": {},
            "recovery_point": "unknown_phase_xyz",
        }
        saga_file.write_text(json.dumps(saga_data), encoding="utf-8")
        return saga_file

    def create_saga_with_future_timestamp(self, saga_dir: Path, task_id: str):
        """Create saga file with future timestamp."""
        saga_file = saga_dir / f"{task_id}.json"
        saga_data = {
            "task_id": task_id,
            "checkpoints": {
                "analysis": {
                    "phase": "analysis",
                    "result": {},
                    "state": "ANALYSIS_COMPLETE",
                    "timestamp": "2099-12-31T23:59:59",  # Future!
                    "context_index": 5,
                }
            },
            "context": {"analysis_complete": True},
            "recovery_point": "analysis",
        }
        saga_file.write_text(json.dumps(saga_data), encoding="utf-8")
        return saga_file

    def create_incomplete_saga(self, saga_dir: Path, task_id: str):
        """Create saga with incomplete checkpoint chain (skips debate)."""
        saga_file = saga_dir / f"{task_id}.json"
        saga_data = {
            "task_id": task_id,
            "checkpoints": {
                "analysis": {
                    "phase": "analysis",
                    "result": {},
                    "state": "ANALYSIS_COMPLETE",
                    "timestamp": "2025-01-01T00:00:00",
                    "context_index": 5,
                },
                # NOTE: debate is missing!
                "architecture": {
                    "phase": "architecture",
                    "result": {},
                    "state": "ARCHITECTURE_APPROVED",
                    "timestamp": "2025-01-01T00:00:02",
                    "context_index": 15,
                },
            },
            "context": {
                "analysis_complete": True,
                "debate_complete": False,  # Inconsistent!
                "architecture_approved": True,
            },
            "recovery_point": "architecture",
        }
        saga_file.write_text(json.dumps(saga_data), encoding="utf-8")
        return saga_file


class TimeoutInjector:
    """
    Inject timeouts into operations.

    Usage:
        injector = TimeoutInjector()

        # Timeout after 100ms
        with injector.timeout(100):
            await long_operation()  # Will raise TimeoutError
    """

    @contextmanager
    def timeout(self, timeout_ms: int):
        """Apply timeout to block."""
        import signal

        def handler(signum, frame):
            raise TimeoutError(f"Operation timed out after {timeout_ms}ms")

        # Note: signal.alarm only works on Unix
        if hasattr(signal, "SIGALRM"):
            old_handler = signal.signal(signal.SIGALRM, handler)
            signal.setitimer(signal.ITIMER_REAL, timeout_ms / 1000)
            try:
                yield
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old_handler)
        else:
            # Windows fallback - no signal support
            yield

    async def async_timeout(self, coro, timeout_ms: int):
        """Apply timeout to async coroutine."""
        try:
            return await asyncio.wait_for(coro, timeout=timeout_ms / 1000)
        except TimeoutError:
            raise TimeoutError(f"Async operation timed out after {timeout_ms}ms") from None
