"""
NEXUS V13.0 MEMORIA UNIVERSALIS - RAG Namespace Manager

Manages multiple RAG namespaces:
- Project RAG: Global knowledge base shared by all agents
- Agent RAGs: Scoped knowledge bases per spawned agent

Architecture:
    .nexus/
    +-- project_knowledge.json      # Project RAG (existing)
    +-- lancedb/project/            # Project vectors
    +-- agent_rags/                 # Agent-specific RAGs
    |   +-- security_expert/
    |   |   +-- knowledge.json
    |   |   +-- lancedb/
    |   +-- {agent_name}/
    +-- rag_config.json             # Namespace configuration

Usage:
    manager = RAGNamespaceManager(nexus_root)

    # Get project RAG (always available)
    project_rag = manager.get_project_rag()

    # Create/get agent-specific RAG
    agent_rag = manager.get_agent_rag("security_expert")

    # List all namespaces
    namespaces = manager.list_namespaces()

    # Merge agent knowledge to project
    manager.merge_to_project("security_expert")
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .project_memory import ProjectMemory

# =============================================================================
# Configuration
# =============================================================================

NAMESPACE_CONFIG_FILE = "rag_config.json"
AGENT_RAGS_DIR = "agent_rags"


# =============================================================================
# Namespace Info
# =============================================================================


class NamespaceInfo:
    """Information about a RAG namespace."""

    def __init__(
        self,
        name: str,
        namespace_type: str,  # "project" or "agent"
        path: Path,
        created_at: str,
        chunks_count: int = 0,
        files_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ):
        self.name = name
        self.namespace_type = namespace_type
        self.path = path
        self.created_at = created_at
        self.chunks_count = chunks_count
        self.files_count = files_count
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "type": self.namespace_type,
            "path": str(self.path),
            "created_at": self.created_at,
            "chunks_count": self.chunks_count,
            "files_count": self.files_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NamespaceInfo":
        """Create from dictionary."""
        return cls(
            name=data["name"],
            namespace_type=data["type"],
            path=Path(data["path"]),
            created_at=data["created_at"],
            chunks_count=data.get("chunks_count", 0),
            files_count=data.get("files_count", 0),
            metadata=data.get("metadata", {}),
        )


# =============================================================================
# RAGNamespaceManager Class
# =============================================================================


class RAGNamespaceManager:
    """
    Manages multiple RAG namespaces for project and agents.

    Provides isolation between different knowledge bases while allowing
    knowledge sharing through merge operations.
    """

    def __init__(self, nexus_root: Path, embedding_engine=None):
        """
        Initialize RAG Namespace Manager.

        Args:
            nexus_root: Root directory of NEXUS installation
            embedding_engine: Optional shared EmbeddingEngine instance
        """
        self.nexus_root = Path(nexus_root)
        self.storage_dir = self.nexus_root / ".nexus"
        self.agent_rags_dir = self.storage_dir / AGENT_RAGS_DIR
        self.config_path = self.storage_dir / NAMESPACE_CONFIG_FILE

        self._logger = logging.getLogger("nexus.namespace_manager")
        self._embedding_engine = embedding_engine

        # Cache for loaded RAG instances
        self._project_rag: ProjectMemory | None = None
        self._agent_rags: dict[str, ProjectMemory] = {}

        # Ensure directories exist
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.agent_rags_dir.mkdir(parents=True, exist_ok=True)

        # Load configuration
        self._config = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load namespace configuration."""
        if self.config_path.exists():
            try:
                return json.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception as e:
                self._logger.warning(f"Failed to load config: {e}")
        return {"namespaces": {}, "created_at": datetime.now().isoformat()}

    def _save_config(self):
        """Save namespace configuration."""
        try:
            self.config_path.write_text(json.dumps(self._config, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            self._logger.error(f"Failed to save config: {e}")

    # =========================================================================
    # Project RAG
    # =========================================================================

    def get_project_rag(self) -> ProjectMemory:
        """
        Get the project-level RAG.

        This is the main, shared knowledge base.

        Returns:
            ProjectMemory instance for project RAG
        """
        if self._project_rag is None:
            self._project_rag = ProjectMemory(self.nexus_root, embedding_engine=self._embedding_engine)
            self._logger.info("Project RAG loaded")
        return self._project_rag

    # =========================================================================
    # Agent RAGs
    # =========================================================================

    def get_agent_rag(self, agent_name: str, create: bool = True) -> ProjectMemory | None:
        """
        Get or create an agent-specific RAG.

        Args:
            agent_name: Name of the agent
            create: If True, create the RAG if it doesn't exist

        Returns:
            ProjectMemory instance for agent RAG, or None if not found and create=False
        """
        # Sanitize agent name
        agent_name = self._sanitize_name(agent_name)

        # Check cache
        if agent_name in self._agent_rags:
            return self._agent_rags[agent_name]

        # Check if exists on disk
        agent_dir = self.agent_rags_dir / agent_name
        if agent_dir.exists():
            rag = self._load_agent_rag(agent_name)
            if rag:
                self._agent_rags[agent_name] = rag
                return rag

        # Create if requested
        if create:
            return self.create_agent_rag(agent_name)

        return None

    def create_agent_rag(self, agent_name: str, metadata: dict[str, Any] | None = None) -> ProjectMemory:
        """
        Create a new agent-specific RAG.

        Args:
            agent_name: Name of the agent
            metadata: Optional metadata about the agent/RAG

        Returns:
            New ProjectMemory instance
        """
        agent_name = self._sanitize_name(agent_name)
        agent_dir = self.agent_rags_dir / agent_name

        # Create directory
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Create ProjectMemory with custom storage path
        # We create a "fake" nexus_root that points to agent dir
        # so the storage goes to agent_dir/.nexus/project_knowledge.json
        agent_nexus_dir = agent_dir
        agent_nexus_dir.mkdir(exist_ok=True)

        # Create a custom ProjectMemory that stores in agent dir
        rag = self._create_agent_project_memory(agent_name, agent_dir)

        # Update config
        self._config["namespaces"][agent_name] = {
            "type": "agent",
            "path": str(agent_dir),
            "created_at": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        self._save_config()

        # Cache
        self._agent_rags[agent_name] = rag

        self._logger.info(f"Created agent RAG: {agent_name}")
        return rag

    def _create_agent_project_memory(self, agent_name: str, agent_dir: Path) -> ProjectMemory:
        """Create a ProjectMemory instance configured for agent storage."""
        # We need to create a ProjectMemory that stores in agent_dir
        # The trick is to create it with agent_dir as nexus_root
        # but we need the .nexus subdir
        nexus_subdir = agent_dir / ".nexus"
        nexus_subdir.mkdir(exist_ok=True)

        return ProjectMemory(agent_dir, embedding_engine=self._embedding_engine)

    def _load_agent_rag(self, agent_name: str) -> ProjectMemory | None:
        """Load an existing agent RAG from disk."""
        agent_dir = self.agent_rags_dir / agent_name
        if not agent_dir.exists():
            return None

        try:
            return self._create_agent_project_memory(agent_name, agent_dir)
        except Exception as e:
            self._logger.warning(f"Failed to load agent RAG {agent_name}: {e}")
            return None

    def delete_agent_rag(self, agent_name: str) -> bool:
        """
        Delete an agent-specific RAG.

        Args:
            agent_name: Name of the agent

        Returns:
            True if deleted, False if not found
        """
        agent_name = self._sanitize_name(agent_name)
        agent_dir = self.agent_rags_dir / agent_name

        if not agent_dir.exists():
            return False

        # Remove from cache
        if agent_name in self._agent_rags:
            del self._agent_rags[agent_name]

        # Remove from config
        if agent_name in self._config.get("namespaces", {}):
            del self._config["namespaces"][agent_name]
            self._save_config()

        # Delete directory
        try:
            shutil.rmtree(agent_dir)
            self._logger.info(f"Deleted agent RAG: {agent_name}")
            return True
        except Exception as e:
            self._logger.error(f"Failed to delete agent RAG {agent_name}: {e}")
            return False

    # =========================================================================
    # Namespace Operations
    # =========================================================================

    def list_namespaces(self) -> list[NamespaceInfo]:
        """
        List all available namespaces.

        Returns:
            List of NamespaceInfo objects
        """
        namespaces = []

        # Project namespace (always exists)
        project_rag = self.get_project_rag()
        stats = project_rag.get_stats()
        namespaces.append(
            NamespaceInfo(
                name="project",
                namespace_type="project",
                path=self.storage_dir,
                created_at=self._config.get("created_at", datetime.now().isoformat()),
                chunks_count=stats.total_chunks,
                files_count=stats.total_files,
            )
        )

        # Agent namespaces
        for agent_name, config in self._config.get("namespaces", {}).items():
            agent_dir = self.agent_rags_dir / agent_name
            if agent_dir.exists():
                # Get stats if loaded
                if agent_name in self._agent_rags:
                    rag = self._agent_rags[agent_name]
                    stats = rag.get_stats()
                    chunks = stats.total_chunks
                    files = stats.total_files
                else:
                    chunks = config.get("chunks_count", 0)
                    files = config.get("files_count", 0)

                namespaces.append(
                    NamespaceInfo(
                        name=agent_name,
                        namespace_type="agent",
                        path=agent_dir,
                        created_at=config.get("created_at", ""),
                        chunks_count=chunks,
                        files_count=files,
                        metadata=config.get("metadata", {}),
                    )
                )

        return namespaces

    def get_namespace_info(self, name: str) -> NamespaceInfo | None:
        """
        Get info about a specific namespace.

        Args:
            name: Namespace name ("project" or agent name)

        Returns:
            NamespaceInfo or None if not found
        """
        for ns in self.list_namespaces():
            if ns.name == name:
                return ns
        return None

    def merge_to_project(self, agent_name: str, clear_agent: bool = False) -> int:
        """
        Merge an agent's RAG knowledge to the project RAG.

        Args:
            agent_name: Name of the agent
            clear_agent: If True, clear the agent RAG after merge

        Returns:
            Number of chunks merged
        """
        agent_name = self._sanitize_name(agent_name)
        agent_rag = self.get_agent_rag(agent_name, create=False)

        if agent_rag is None:
            self._logger.warning(f"Agent RAG not found: {agent_name}")
            return 0

        project_rag = self.get_project_rag()

        # Get chunks from agent RAG
        chunks_merged = 0
        for chunk in agent_rag.chunks:
            # Check if already in project (by content hash or file_path)
            is_duplicate = any(
                c.file_path == chunk.file_path and c.start_line == chunk.start_line for c in project_rag.chunks
            )
            if not is_duplicate:
                project_rag.chunks.append(chunk)
                chunks_merged += 1

        if chunks_merged > 0:
            project_rag._backend_dirty = True
            project_rag.save()

        # Clear agent if requested
        if clear_agent:
            agent_rag.clear()

        self._logger.info(f"Merged {chunks_merged} chunks from {agent_name} to project")
        return chunks_merged

    # =========================================================================
    # Utilities
    # =========================================================================

    def _sanitize_name(self, name: str) -> str:
        """Sanitize namespace name for filesystem safety."""
        # Remove special characters, keep alphanumeric and underscore
        import re

        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
        return sanitized.lower()

    def get_stats(self) -> dict[str, Any]:
        """
        Get overall statistics across all namespaces.

        Returns:
            Dict with aggregated stats
        """
        namespaces = self.list_namespaces()
        total_chunks = sum(ns.chunks_count for ns in namespaces)
        total_files = sum(ns.files_count for ns in namespaces)

        return {
            "namespace_count": len(namespaces),
            "project_namespace": 1,
            "agent_namespaces": len(namespaces) - 1,
            "total_chunks": total_chunks,
            "total_files": total_files,
            "namespaces": [ns.to_dict() for ns in namespaces],
        }


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "RAGNamespaceManager",
    "NamespaceInfo",
]
