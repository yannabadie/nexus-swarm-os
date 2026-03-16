"""
NEXUS V9.1 - MemoryService

Service Layer for Project Memory (RAG) operations.
Extracted from repl.py to enable proper separation of concerns.

This service handles:
- Learning (indexing files/directories)
- Forgetting (removing from memory)
- Memory status queries
- RAG initialization and queries

Usage:
    from core.memory_pkg.memory.service import MemoryService

    service = MemoryService(project_memory, workspace_path, console)
    service.learn("core/")
    service.forget("old_file.py")
    status = service.get_status()
    results = service.query("how does authentication work?")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.interface_pkg.interface.console_v7 import ConsoleV7
    from core.memory_pkg.memory.project_memory import ProjectMemory
    from core.memory_pkg.memory.types import Chunk

_logger = logging.getLogger(__name__)


@dataclass
class MemoryStatus:
    """Status of project memory."""

    total_files: int
    total_chunks: int
    total_terms: int
    storage_path: str
    indexed_files: list[str]


@dataclass
class LearnResult:
    """Result of a learn operation."""

    success: bool
    chunks_added: int = 0
    error: str | None = None


@dataclass
class ForgetResult:
    """Result of a forget operation."""

    success: bool
    chunks_removed: int = 0
    error: str | None = None


@dataclass
class QueryResult:
    """Result of a RAG query."""

    success: bool
    chunks: list[Chunk] = None
    error: str | None = None


class MemoryService:
    """
    Service for Project Memory (RAG) operations.

    Handles learning, forgetting, status queries, and RAG retrieval.
    Extracted from InteractiveNexusV7 (repl.py) for proper separation of concerns.
    """

    def __init__(self, project_memory: ProjectMemory, workspace_path: Path, console: ConsoleV7):
        """
        Initialize MemoryService.

        Args:
            project_memory: The ProjectMemory instance for RAG operations
            workspace_path: Path to workspace directory
            console: Console for output
        """
        self.project_memory = project_memory
        self.workspace_path = workspace_path
        self.console = console

    # ==================== PUBLIC API ====================

    def learn(self, path_str: str) -> LearnResult:
        """
        Index file or directory into project memory.

        Args:
            path_str: Path to file or directory (relative to project root)

        Returns:
            LearnResult with success status and chunks count
        """
        if not self.project_memory:
            self.console.print_error("Project memory not initialized")
            return LearnResult(success=False, error="Project memory not initialized")

        if not path_str:
            # Default: index core/ directory
            path_str = "core"
            self.console.print(f"[dim]No path specified, indexing default: {path_str}[/dim]")

        path = Path(path_str)

        # Resolve relative to project root
        if not path.is_absolute():
            path = self.project_memory.nexus_root / path

        if not path.exists():
            self.console.print_error(f"Path not found: {path_str}")
            return LearnResult(success=False, error=f"Path not found: {path_str}")

        self.console.print("\n[brain] [bold]Indexing into Project Memory[/bold]")
        self.console.print(f"   Path: {path}")

        try:
            if path.is_file():
                chunks = self.project_memory.index_file(path)
                self.console.print(f"   [checkmark] Indexed 1 file -> {chunks} chunks")
            else:
                chunks = self.project_memory.index_directory(path)
                self.console.print(f"   [checkmark] Indexed directory -> {chunks} chunks")

            # Show updated stats
            stats = self.project_memory.get_stats()
            self.console.print(f"\n   [chart] Total: {stats.total_files} files, {stats.total_chunks} chunks")
            self.console.print(f"   [disk] Saved to: {stats.storage_path}\n")

            return LearnResult(success=True, chunks_added=chunks)

        except Exception as e:
            self.console.print_error(f"Indexing failed: {e}")
            return LearnResult(success=False, error=str(e))

    def forget(self, path_str: str) -> ForgetResult:
        """
        Remove file or directory from project memory.

        Args:
            path_str: Path to file or directory to forget

        Returns:
            ForgetResult with success status and chunks removed
        """
        if not self.project_memory:
            self.console.print_error("Project memory not initialized")
            return ForgetResult(success=False, error="Project memory not initialized")

        if not path_str:
            self.console.print_error("Usage: /forget <path>")
            return ForgetResult(success=False, error="No path specified")

        path = Path(path_str)

        # Resolve relative to project root
        if not path.is_absolute():
            path = self.project_memory.nexus_root / path

        try:
            removed = self.project_memory.forget(path)
            if removed > 0:
                self.console.print("\n[brain] [bold]Removed from Project Memory[/bold]")
                self.console.print(f"   Path: {path_str}")
                self.console.print(f"   [checkmark] Removed {removed} chunks\n")
            else:
                self.console.print(f"[dim]Path not in memory: {path_str}[/dim]")

            return ForgetResult(success=True, chunks_removed=removed)

        except Exception as e:
            self.console.print_error(f"Forget failed: {e}")
            return ForgetResult(success=False, error=str(e))

    def get_status(self) -> MemoryStatus | None:
        """
        Get project memory status and statistics.

        Returns:
            MemoryStatus with stats and indexed files, or None if not initialized
        """
        if not self.project_memory:
            self.console.print_error("Project memory not initialized")
            return None

        stats = self.project_memory.get_stats()
        indexed_files = sorted(self.project_memory.indexed_files)

        lines = [
            "",
            "+" + "=" * 62 + "+",
            "|" + " " * 15 + "[brain] PROJECT MEMORY STATUS" + " " * 17 + "|",
            "+" + "=" * 62 + "+",
            "",
            f"  [folder] Indexed Files:    {stats.total_files}",
            f"  [package] Total Chunks:     {stats.total_chunks}",
            f"  [abc] Unique Terms:     {stats.total_terms}",
            f"  [disk] Storage:          {stats.storage_path}",
            "",
        ]

        if indexed_files:
            lines.append("  [list] Files in memory:")
            for f in indexed_files[:15]:  # Limit display
                lines.append(f"     - {f}")
            if len(indexed_files) > 15:
                lines.append(f"     ... and {len(indexed_files) - 15} more")
        else:
            lines.append("  [dim]No files indexed yet. Use /learn <path> to add files.[/dim]")

        lines.append("")

        for line in lines:
            self.console.console.print(line)

        return MemoryStatus(
            total_files=stats.total_files,
            total_chunks=stats.total_chunks,
            total_terms=stats.total_terms,
            storage_path=str(stats.storage_path),
            indexed_files=indexed_files,
        )

    def query(self, query_str: str, limit: int = 5) -> QueryResult:
        """
        Query project memory for relevant chunks.

        Args:
            query_str: Search query
            limit: Maximum number of results

        Returns:
            QueryResult with matching chunks
        """
        if not self.project_memory:
            self.console.print_error("Project memory not initialized")
            return QueryResult(success=False, error="Project memory not initialized")

        # V12.4: Check cache before running retrieval
        cache_key = f"rag:{query_str}:{limit}"
        try:
            from core.memory_pkg.memory.cache_manager import get_cache_manager

            cache = get_cache_manager()
            cached = cache.get(cache_key)
            if cached is not None:
                _logger.debug(f"RAG cache hit for: {query_str[:40]}")
                chunks = cached
            else:
                chunks = self.project_memory.retrieve(query_str, limit=limit)
                if chunks:
                    cache.put(cache_key, chunks, ttl=120)  # Cache for 2 minutes
        except Exception as e:
            _logger.debug(f"Cache manager unavailable: {e}")
            chunks = self.project_memory.retrieve(query_str, limit=limit)

        if not chunks:
            self.console.print("[yellow]No results found[/yellow]")
            self.console.print("[dim]Try /rag init first, or use different keywords[/dim]")
            return QueryResult(success=True, chunks=[])

        # V12.4: Record access patterns for Ebbinghaus decay scoring
        try:
            from core.memory_pkg.memory.decay_scorer import get_decay_scorer

            scorer = get_decay_scorer()
            for chunk in chunks:
                scorer.record_access(chunk.chunk_id)
        except Exception as e:
            _logger.debug(f"Decay scorer recording failed: {e}")

        self.console.print(f"\n[bold]RAG Results for:[/bold] {query_str}")
        self.console.print(f"[dim]Found {len(chunks)} chunks[/dim]\n")

        for i, chunk in enumerate(chunks, 1):
            self.console.print(f"[cyan]{i}. {chunk.file_path}[/cyan] (L{chunk.start_line}-{chunk.end_line})")
            # Show first 150 chars of content
            preview = chunk.content[:150].replace("\n", " ")
            if len(chunk.content) > 150:
                preview += "..."
            self.console.print(f"   {preview}\n")

        return QueryResult(success=True, chunks=chunks)

    def init_rag(self) -> LearnResult:
        """
        Initialize RAG on workspace/memory/ directory.

        Returns:
            LearnResult with indexing results
        """
        if not self.project_memory:
            self.console.print_error("Project memory not initialized")
            return LearnResult(success=False, error="Project memory not initialized")

        memory_dir = self.workspace_path / "memory"

        if not memory_dir.exists():
            memory_dir.mkdir(parents=True, exist_ok=True)
            self.console.print(f"[dim]Created {memory_dir}[/dim]")

        self.console.print("\n[bold cyan]RAG Initialization[/bold cyan]")
        self.console.print(f"   Target: {memory_dir}")

        # Index workspace/memory/ with all file types
        extensions = [".json", ".jsonl", ".md", ".txt", ".yaml", ".yml", ".log"]
        try:
            chunks = self.project_memory.index_directory(memory_dir, extensions=extensions, recursive=True)

            stats = self.project_memory.get_stats()
            backend_info = self.project_memory.get_backend_info()

            self.console.print(f"   [green]OK[/green] Indexed {chunks} chunks")
            self.console.print(f"   Files: {stats.total_files}")
            self.console.print(f"   Backend: {backend_info.get('backend', 'unknown')}")
            self.console.print("")

            return LearnResult(success=True, chunks_added=chunks)

        except Exception as e:
            self.console.print_error(f"RAG init failed: {e}")
            return LearnResult(success=False, error=str(e))

    def clear(self) -> bool:
        """
        Clear all RAG indexed data.

        Returns:
            True if successful
        """
        if not self.project_memory:
            self.console.print_error("Project memory not initialized")
            return False

        self.project_memory.clear()
        self.console.print("[green]OK[/green] RAG memory cleared")
        return True

    def handle_rag_command(self, args: str) -> None:
        """
        Handle /rag command with subcommands.

        Args:
            args: Subcommand (init, clear, query <text>)
        """
        if not self.project_memory:
            self.console.print_error("Project memory not initialized")
            return

        parts = args.split(maxsplit=1)
        subcmd = parts[0].lower() if parts else ""
        subargs = parts[1] if len(parts) > 1 else ""

        if subcmd == "init":
            self.init_rag()

        elif subcmd == "clear":
            self.clear()

        elif subcmd == "query":
            if not subargs:
                self.console.print_error("Usage: /rag query <your question>")
            else:
                self.query(subargs)

        else:
            self.console.print_error("Usage: /rag <init|clear|query>")
            self.console.print("  /rag init       - Index workspace/memory/")
            self.console.print("  /rag clear      - Clear all indexed data")
            self.console.print("  /rag query <q>  - Test retrieval")
