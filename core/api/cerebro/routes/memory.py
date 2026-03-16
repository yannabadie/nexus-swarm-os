"""
NEXUS V13.0 MEMORIA UNIVERSALIS - Memory Management API

Endpoints for managing RAG memory:
- GET /api/memory/stats : Get memory statistics
- GET /api/memory/namespaces : List all namespaces
- POST /api/memory/namespaces : Create new agent namespace
- DELETE /api/memory/namespaces/{name} : Delete agent namespace
- POST /api/memory/ingest : Upload and ingest files
- POST /api/memory/learn : Learn from path (file or directory)
- POST /api/memory/forget : Forget a file from memory
- POST /api/memory/query : Query the RAG

Security Features:
- V11.6.1 IRONCLAD: MANDATORY authentication
- V12.2 IRONCLAD: RBAC permission checks
- File size limits for upload (10MB)
- Path validation for learn/forget operations
"""

import contextlib
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..deps import AuthenticatedUser
from ..rbac import Permission, require_permission

logger = logging.getLogger(__name__)

router = APIRouter()

# =============================================================================
# Constants
# =============================================================================

MAX_UPLOAD_SIZE = 10_000_000  # 10MB for document uploads


# =============================================================================
# Request/Response Models
# =============================================================================


class NamespaceCreateRequest(BaseModel):
    """Request body for creating an agent namespace."""

    name: str = Field(..., min_length=1, max_length=50, description="Namespace name")
    metadata: dict[str, Any] | None = Field(default=None, description="Optional metadata")


class LearnRequest(BaseModel):
    """Request body for learning from path."""

    path: str = Field(..., description="Path to file or directory")
    recursive: bool = Field(default=True, description="Include subdirectories")
    namespace: str | None = Field(default=None, description="Target namespace (default: project)")


class ForgetRequest(BaseModel):
    """Request body for forgetting a file."""

    path: str = Field(..., description="Path to file to forget")
    namespace: str | None = Field(default=None, description="Target namespace (default: project)")


class QueryRequest(BaseModel):
    """Request body for RAG query."""

    query: str = Field(..., min_length=1, description="Search query")
    limit: int = Field(default=5, ge=1, le=20, description="Max results")
    namespace: str | None = Field(default=None, description="Target namespace (default: project)")


class ChunkResponse(BaseModel):
    """Response model for a retrieved chunk."""

    file_path: str
    start_line: int
    end_line: int
    content: str
    chunk_type: str
    name: str | None
    score: float = 0.0


# =============================================================================
# Helper Functions
# =============================================================================


def _get_namespace_manager():
    """Get RAGNamespaceManager instance."""
    try:
        from core.config import Config
        from core.memory_pkg.memory import RAGNamespaceManager

        config = Config()
        nexus_root = Path(config.nexus_root)
        return RAGNamespaceManager(nexus_root)
    except Exception as e:
        logger.error(f"Failed to get namespace manager: {e}")
        raise HTTPException(500, f"Memory system error: {e}") from e


def _get_rag_for_namespace(manager, namespace: str | None):
    """Get the appropriate RAG for a namespace."""
    if namespace is None or namespace == "project":
        return manager.get_project_rag()
    else:
        rag = manager.get_agent_rag(namespace, create=False)
        if rag is None:
            raise HTTPException(404, f"Namespace not found: {namespace}")
        return rag


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/stats")
async def memory_stats(
    namespace: str | None = Query(None, description="Namespace to get stats for"),
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_READ, "memory")),
) -> dict[str, Any]:
    """
    Get memory statistics.

    Args:
        namespace: Optional namespace (default: all)
        user: Authenticated user

    Returns:
        Statistics about indexed content
    """
    manager = _get_namespace_manager()

    if namespace:
        rag = _get_rag_for_namespace(manager, namespace)
        stats = rag.get_stats()
        backend_info = rag.get_backend_info()
        return {
            "namespace": namespace,
            "stats": {
                "total_files": stats.total_files,
                "total_chunks": stats.total_chunks,
                "total_terms": stats.total_terms,
                "indexed_at": stats.indexed_at,
            },
            "backend": backend_info,
        }
    else:
        # Return overall stats
        return manager.get_stats()


@router.get("/namespaces")
async def list_namespaces(
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_READ, "memory")),
) -> dict[str, Any]:
    """
    List all available namespaces.

    Returns:
        List of namespace info objects
    """
    manager = _get_namespace_manager()
    namespaces = manager.list_namespaces()

    return {
        "namespaces": [ns.to_dict() for ns in namespaces],
        "total": len(namespaces),
    }


@router.post("/namespaces")
async def create_namespace(
    body: NamespaceCreateRequest,
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_WRITE, "memory")),
) -> dict[str, Any]:
    """
    Create a new agent namespace.

    Args:
        body: Namespace creation request
        user: Authenticated user

    Returns:
        Created namespace info
    """
    manager = _get_namespace_manager()

    # Check if namespace already exists
    existing = manager.get_namespace_info(body.name)
    if existing:
        raise HTTPException(409, f"Namespace already exists: {body.name}")

    # Create namespace
    manager.create_agent_rag(body.name, metadata=body.metadata)
    info = manager.get_namespace_info(body.name)

    logger.info(f"[MEMORIA] Created namespace: {body.name} by user={user.user_id}")

    return {
        "status": "created",
        "namespace": info.to_dict() if info else {"name": body.name},
    }


@router.delete("/namespaces/{name}")
async def delete_namespace(
    name: str,
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_WRITE, "memory")),
) -> dict[str, str]:
    """
    Delete an agent namespace.

    Args:
        name: Namespace name to delete
        user: Authenticated user

    Returns:
        Status message
    """
    if name == "project":
        raise HTTPException(403, "Cannot delete project namespace")

    manager = _get_namespace_manager()

    if not manager.delete_agent_rag(name):
        raise HTTPException(404, f"Namespace not found: {name}")

    logger.info(f"[MEMORIA] Deleted namespace: {name} by user={user.user_id}")

    return {"status": "deleted", "namespace": name}


@router.post("/ingest")
async def ingest_file(
    file: UploadFile = File(..., description="File to ingest"),
    namespace: str | None = Form(None, description="Target namespace"),
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_WRITE, "memory")),
) -> dict[str, Any]:
    """
    Upload and ingest a file into memory.

    Supports: PDF, DOCX, PPTX, XLSX, images, code files, text files.

    Args:
        file: Uploaded file
        namespace: Target namespace (default: project)
        user: Authenticated user

    Returns:
        Ingestion result with chunk count
    """
    # Check file size
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, f"File too large: {len(content)} bytes > {MAX_UPLOAD_SIZE} limit")

    # Save to temp file
    suffix = Path(file.filename).suffix if file.filename else ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        manager = _get_namespace_manager()
        rag = _get_rag_for_namespace(manager, namespace)

        # Index the file
        chunks_created = rag.index_file(tmp_path, force=True)
        rag.save()

        logger.info(f"[MEMORIA] Ingested {file.filename}: {chunks_created} chunks by user={user.user_id}")

        return {
            "status": "ingested",
            "filename": file.filename,
            "size": len(content),
            "chunks_created": chunks_created,
            "namespace": namespace or "project",
        }

    finally:
        # Clean up temp file
        with contextlib.suppress(Exception):
            tmp_path.unlink()


@router.post("/learn")
async def learn_path(
    body: LearnRequest,
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_WRITE, "memory")),
) -> dict[str, Any]:
    """
    Learn from a path (file or directory).

    Args:
        body: Learn request with path
        user: Authenticated user

    Returns:
        Learning result with chunk count
    """
    manager = _get_namespace_manager()
    rag = _get_rag_for_namespace(manager, body.namespace)

    # Security: Validate path with PathGuardian (prevents path traversal)
    from core.config import Config
    from core.security_pkg.security.path_guardian import PathGuardian

    config = Config()
    nexus_root = Path(config.nexus_root).resolve()
    guardian = PathGuardian(Path(config.workspace_path).resolve(), nexus_root)

    path = Path(body.path)
    if not path.is_absolute():
        path = nexus_root / path

    is_valid, resolved_path, message = guardian.validate_read(str(path))
    if not is_valid:
        raise HTTPException(403, f"Path access denied: {message}")

    path = Path(resolved_path)
    if not path.exists():
        raise HTTPException(404, f"Path not found: {body.path}")

    if path.is_file():
        chunks = rag.index_file(path, force=True)
    else:
        chunks = rag.index_directory(path, recursive=body.recursive)

    rag.save()

    logger.info(f"[MEMORIA] Learned {body.path}: {chunks} chunks by user={user.user_id}")

    return {
        "status": "learned",
        "path": body.path,
        "chunks_created": chunks,
        "namespace": body.namespace or "project",
    }


@router.post("/forget")
async def forget_path(
    body: ForgetRequest,
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_WRITE, "memory")),
) -> dict[str, Any]:
    """
    Forget a file from memory.

    Args:
        body: Forget request with path
        user: Authenticated user

    Returns:
        Result with chunks removed count
    """
    manager = _get_namespace_manager()
    rag = _get_rag_for_namespace(manager, body.namespace)

    # Security: Validate path with PathGuardian (prevents path traversal)
    from core.config import Config
    from core.security_pkg.security.path_guardian import PathGuardian

    config = Config()
    nexus_root = Path(config.nexus_root).resolve()
    guardian = PathGuardian(Path(config.workspace_path).resolve(), nexus_root)

    path = Path(body.path)
    if not path.is_absolute():
        path = nexus_root / path

    is_valid, resolved_path, message = guardian.validate_read(str(path))
    if not is_valid:
        raise HTTPException(403, f"Path access denied: {message}")

    path = Path(resolved_path)
    chunks_removed = rag.forget(path)

    logger.info(f"[MEMORIA] Forgot {body.path}: {chunks_removed} chunks by user={user.user_id}")

    return {
        "status": "forgotten",
        "path": body.path,
        "chunks_removed": chunks_removed,
        "namespace": body.namespace or "project",
    }


@router.post("/query")
async def query_memory(
    body: QueryRequest,
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_READ, "memory")),
) -> dict[str, Any]:
    """
    Query the RAG memory.

    Args:
        body: Query request
        user: Authenticated user

    Returns:
        Retrieved chunks
    """
    manager = _get_namespace_manager()
    rag = _get_rag_for_namespace(manager, body.namespace)

    chunks = rag.retrieve(body.query, limit=body.limit)

    return {
        "query": body.query,
        "namespace": body.namespace or "project",
        "results": [
            {
                "file_path": c.file_path,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "content": c.content[:500] + "..." if len(c.content) > 500 else c.content,
                "chunk_type": c.chunk_type,
                "name": c.name,
            }
            for c in chunks
        ],
        "total": len(chunks),
    }


@router.post("/merge")
async def merge_to_project(
    namespace: str = Query(..., description="Agent namespace to merge"),
    clear_agent: bool = Query(False, description="Clear agent namespace after merge"),
    user: AuthenticatedUser = Depends(require_permission(Permission.FILE_WRITE, "memory")),
) -> dict[str, Any]:
    """
    Merge an agent namespace to the project namespace.

    Args:
        namespace: Agent namespace to merge
        clear_agent: Whether to clear the agent namespace after merge
        user: Authenticated user

    Returns:
        Merge result
    """
    if namespace == "project":
        raise HTTPException(400, "Cannot merge project to itself")

    manager = _get_namespace_manager()
    chunks_merged = manager.merge_to_project(namespace, clear_agent=clear_agent)

    logger.info(f"[MEMORIA] Merged {namespace}: {chunks_merged} chunks by user={user.user_id}")

    return {
        "status": "merged",
        "namespace": namespace,
        "chunks_merged": chunks_merged,
        "agent_cleared": clear_agent,
    }
