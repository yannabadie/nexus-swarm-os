"""
Memory Manager V7 - Persistent in-RAM state

Architecture:
- Blackboard loaded ONCE at init (not reloaded from disk between turns)
- State persists in RAM throughout session
- Backup to disk only for crash recovery
- Auto-compression via Haiku CLI when >120k tokens

V7.5 Phase 7: Atomic JSON persistence via AtomicJsonStore
- All disk writes use Write-Replace pattern (temp -> fsync -> rename)
- Thread-safe for Swarm PARALLEL mode
"""

import contextlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

import tiktoken

from core.utils.atomic_store import AtomicJsonStore


class MemoryManagerV7:
    """
    Manage blackboard state in-RAM

    State lives in RAM, disk is backup only
    """

    def __init__(self, workspace_path: Path, config):
        self.workspace_path = workspace_path
        self.config = config
        self.blackboard_path = workspace_path / ".nexus" / "blackboard.json"
        self.backup_dir = workspace_path / ".nexus" / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # V7.5 Phase 0c: Thread safety for PARALLEL mode
        self._lock = RLock()

        # V7.5 Phase 7: Atomic JSON stores for safe concurrent writes
        self._blackboard_store = AtomicJsonStore(self.blackboard_path)
        self.global_memory_path = Path.home() / ".nexus" / "global_context.json"
        self._global_memory_store = AtomicJsonStore(self.global_memory_path)

        # Load initial state ONCE
        self.blackboard = self._load_or_create_blackboard()

        # Load Global Memory (Inter-project Persistence)
        self.global_memory = self._load_global_memory()

    def load_initial_state(self) -> dict:
        """
        Load blackboard state (called ONCE at init)

        Returns:
            Blackboard dict
        """
        return self.blackboard

    def _load_global_memory(self) -> dict:
        """Load global memory from user home directory (Phase 7: via AtomicJsonStore)"""
        try:
            data = self._global_memory_store.load_safe()
            if not data:
                return self._create_empty_global_memory()
            return data
        except Exception as e:
            print(f"Warning: Could not load global memory: {e}")
            return self._create_empty_global_memory()

    def _create_empty_global_memory(self) -> dict:
        """Create empty global memory structure"""
        return {
            "user_profile": {},  # Preferences, name, style
            "learned_patterns": {},  # Cross-project coding patterns
            "project_index": [],  # List of known projects
            "metadata": {"created": datetime.now().isoformat(), "version": "1.0"},
        }

    def save_global_memory(self):
        """Save global memory to disk (Phase 7: atomic write via AtomicJsonStore)"""
        with self._lock:
            try:
                self._global_memory_store.save(self.global_memory)
            except Exception as e:
                print(f"Warning: Could not save global memory: {e}")

    def update_global_context(self, category: str, key: str, value: Any):
        """
        Update a value in global memory

        Args:
            category: 'user_profile', 'learned_patterns', etc.
            key: The specific key to update
            value: The value to store
        """
        with self._lock:
            if category in self.global_memory:
                self.global_memory[category][key] = value
        # save_global_memory() has its own lock (RLock allows reentrant)
        self.save_global_memory()

    def get_global_context(self) -> dict:
        """Get the full global memory"""
        return self.global_memory

    def _load_or_create_blackboard(self) -> dict:
        """
        Load blackboard from disk or create new if missing (Phase 7: via AtomicJsonStore)

        Returns:
            Blackboard dict
        """
        try:
            data = self._blackboard_store.load_safe()
            if not data:
                return self._create_empty_blackboard()
            return data
        except Exception as e:
            print(f"Warning: Could not load blackboard: {e}")
            return self._create_empty_blackboard()

    def _create_empty_blackboard(self) -> dict:
        """Create empty blackboard structure"""
        return {
            "objective": "",
            "mode": "Normal",
            "strategic_plan": [],
            "recent_history": [],
            "compressed_history_summary": "",
            "current_state": {
                "iteration": 0,
                "active_agent": "Gemini",
                "stalemate_counter": 0,
                "last_action_signature": "",
                "pending_tool_validation": False,
            },
            "metadata": {"created": datetime.now().isoformat(), "version": "6.0.0"},
        }

    @property
    def history(self) -> list[dict]:
        """
        V12.4: Property to access recent_history from blackboard.

        Added for backward compatibility with code expecting memory.history.
        Thread-safe read access to conversation history.
        """
        with self._lock:
            return self.blackboard.get("recent_history", [])

    def get_last_message(self) -> dict:
        """Get last message from history"""
        with self._lock:
            if self.blackboard["recent_history"]:
                return self.blackboard["recent_history"][-1]
            return {}

    def add_to_history(self, message: dict):
        """
        Add message to history

        Args:
            message: Agent message dict
        """
        with self._lock:
            self.blackboard["recent_history"].append(message)

            # Keep last 50 messages
            if len(self.blackboard["recent_history"]) > 50:
                self.blackboard["recent_history"] = self.blackboard["recent_history"][-50:]

            # Auto-compress if >120k tokens estimated
            self._compress_history_unsafe()

    def save_to_disk(self):
        """
        Save blackboard to disk (for crash recovery)
        Phase 7: Atomic write via AtomicJsonStore

        Called after state transitions to ensure persistence
        """
        with self._lock:
            try:
                self._blackboard_store.save(self.blackboard)
            except Exception as e:
                print(f"Warning: Could not save blackboard: {e}")

    def update_strategic_plan(self, plan: list[dict]):
        """Update strategic plan"""
        with self._lock:
            self.blackboard["strategic_plan"] = plan
        self.save_to_disk()

    def compress_history(self):
        """
        Compress old history if >120k tokens (thread-safe wrapper)

        Uses Haiku CLI to summarize history, preserving key context
        """
        with self._lock:
            self._compress_history_unsafe()

    def _compress_history_unsafe(self):
        """
        Internal compression (must be called with lock held)

        Uses Haiku CLI to summarize history, preserving key context
        """
        try:
            # Estimate tokens in recent_history
            history = self.blackboard.get("recent_history", [])
            if not history:
                return

            # Serialize history to estimate size
            history_text = json.dumps(history, ensure_ascii=False)

            # Use tiktoken for accurate token counting (was: rough 1 token ≈ 4 chars)
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
                estimated_tokens = len(encoding.encode(history_text))
            except Exception:
                # Fallback to rough estimation if tiktoken fails
                estimated_tokens = len(history_text) // 4

            # Compress if >120k tokens
            if estimated_tokens > 120000:
                print(f"[Memory] Compressing history ({estimated_tokens} tokens estimated)...")

                # Create summarization prompt
                prompt = f"""Résume cet historique de conversation NEXUS en préservant :
1. Objectif principal
2. Décisions clés prises
3. Outils utilisés avec succès
4. Blocages rencontrés et solutions

Historique ({len(history)} messages) :
{history_text[:50000]}  # Truncate if too large for prompt

Résumé concis (max 2000 tokens) :"""

                # Call Haiku CLI via subprocess
                try:
                    result = subprocess.run(
                        ["claude", "--model", "claude-haiku-4-5-20251001"],
                        input=prompt,
                        capture_output=True,
                        text=True,
                        timeout=30,
                        encoding="utf-8",
                        errors="replace",
                    )

                    if result.returncode == 0:
                        summary = result.stdout.strip()

                        # Store compressed summary
                        self.blackboard["compressed_history_summary"] = summary

                        # Keep only last 10 messages + summary
                        self.blackboard["recent_history"] = history[-10:]

                        print(f"[Memory] [OK] Compressed to {len(history[-10:])} messages + summary")
                    else:
                        print("[Memory] Warning: Compression failed (Haiku CLI error)")

                except subprocess.TimeoutExpired:
                    print("[Memory] Warning: Compression timeout")
                except FileNotFoundError:
                    print("[Memory] Warning: Claude CLI not found (compression skipped)")

        except Exception as e:
            print(f"[Memory] Warning: Compression error: {e}")

    def create_backup(self, reason: str = "manual") -> Path | None:
        """
        Create timestamped backup of current state
        Phase 7: Atomic write via AtomicJsonStore

        Args:
            reason: Reason for backup (manual, panic, error, checkpoint)

        Returns:
            Path to backup file, or None on error
        """
        with self._lock:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = self.backup_dir / f"blackboard_{timestamp}_{reason}.json"

            try:
                backup_data = {
                    "blackboard": self.blackboard,
                    "metadata": {
                        "reason": reason,
                        "timestamp": datetime.now().isoformat(),
                        "iteration": self.blackboard.get("current_state", {}).get("iteration", 0),
                    },
                }

                # Use AtomicJsonStore for backup file
                backup_store = AtomicJsonStore(backup_file)
                backup_store.save(backup_data)

                # Keep only last 10 backups
                self._cleanup_old_backups()

                return backup_file

            except Exception as e:
                print(f"Warning: Could not create backup: {e}")
                return None

    def restore_from_backup(self, backup_file: Path = None) -> bool:
        """
        Restore state from backup (Phase 7: via AtomicJsonStore)

        Args:
            backup_file: Specific backup to restore (None = latest)

        Returns:
            True if restore successful, False otherwise
        """
        with self._lock:
            try:
                if backup_file is None:
                    # Find latest backup
                    backups = sorted(self.backup_dir.glob("blackboard_*.json"), reverse=True)
                    if not backups:
                        print("No backups found")
                        return False
                    backup_file = backups[0]

                if not backup_file.exists():
                    print(f"Backup file not found: {backup_file}")
                    return False

                # Load backup via AtomicJsonStore
                backup_store = AtomicJsonStore(backup_file)
                backup_data = backup_store.load()
                self.blackboard = backup_data["blackboard"]

                print(f"State restored from: {backup_file.name}")

            except Exception as e:
                print(f"Error restoring backup: {e}")
                return False

        # Save restored state as current (RLock allows reentrant locking)
        self.save_to_disk()
        return True

    def list_backups(self) -> list[dict]:
        """
        List available backups (Phase 7: via AtomicJsonStore)

        Returns:
            List of backup info dicts
        """
        backups = []
        for backup_file in sorted(self.backup_dir.glob("blackboard_*.json"), reverse=True):
            try:
                backup_store = AtomicJsonStore(backup_file)
                data = backup_store.load_safe()
                metadata = data.get("metadata", {})
                backups.append(
                    {
                        "file": backup_file.name,
                        "path": backup_file,
                        "reason": metadata.get("reason", "unknown"),
                        "timestamp": metadata.get("timestamp", "unknown"),
                        "iteration": metadata.get("iteration", 0),
                    }
                )
            except Exception:
                pass
        return backups

    def _cleanup_old_backups(self, keep: int = 10):
        """Keep only N most recent backups"""
        backups = sorted(self.backup_dir.glob("blackboard_*.json"), reverse=True)
        for old_backup in backups[keep:]:
            # V8.5.0: Ignore cleanup failures (file may be locked)
            with contextlib.suppress(Exception):
                old_backup.unlink()
