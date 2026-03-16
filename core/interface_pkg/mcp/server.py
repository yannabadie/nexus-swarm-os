"""
NEXUS V9.0 MCP Server - Expose NEXUS as a Tool for External Agents

This module implements NEXUS as an MCP (Model Context Protocol) server,
allowing Claude Desktop, VSCode, and other MCP clients to invoke NEXUS
capabilities.

Usage:
    # As a standalone server (stdio transport):
    python -m core.mcp.server

    # In Claude Desktop config:
    {
        "mcpServers": {
            "nexus": {
                "command": "python",
                "args": ["-m", "core.mcp.server"],
                "cwd": "/path/to/nexus"
            }
        }
    }

Reference: https://modelcontextprotocol.io/quickstart/server
"""

import json
import logging
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Configure logging to stderr (stdout is reserved for MCP JSON-RPC)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", stream=sys.stderr)
logger = logging.getLogger("nexus.mcp.server")

# Check for MCP SDK availability
try:
    from mcp.server.fastmcp import FastMCP

    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    logger.warning("MCP SDK not installed. Install with: pip install mcp")


# =============================================================================
# NEXUS Tool Imports (lazy loading to avoid circular imports)
# =============================================================================

_TOOL_MANAGER = None
_ORCHESTRATOR = None
_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="nexus-mcp-job")
_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def get_tool_manager():
    """Lazy load ToolManager to avoid circular imports."""
    global _TOOL_MANAGER
    if _TOOL_MANAGER is not None:
        return _TOOL_MANAGER
    from core.config import Config
    from core.execution_pkg.execution.tool_manager import ToolManager

    config = Config()
    # V8.5.0: ToolManager expects workspace_path, not config
    _TOOL_MANAGER = ToolManager(config.workspace_path)
    return _TOOL_MANAGER


def execute_tool(tool_name: str, params: dict):
    """
    Helper to execute a tool via ToolManager.

    V8.5.0: Wraps ToolManager.execute() with ToolUse object creation.
    """
    from core.synapse.protocol_v7 import ToolUse

    tm = get_tool_manager()
    tool_request = ToolUse(tool_name=tool_name, arguments=params)
    return tm.execute(tool_request)


def get_orchestrator():
    """Lazy load Orchestrator for complex tasks."""
    global _ORCHESTRATOR
    if _ORCHESTRATOR is not None:
        return _ORCHESTRATOR
    from core.config import Config
    from core.runtime import NexusSessionRuntime

    config = Config()
    runtime = NexusSessionRuntime.from_config(config, interaction_mode="headless")
    _ORCHESTRATOR = runtime.orchestrator
    return _ORCHESTRATOR


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_now() -> str:
    return _utc_now().isoformat()


def _resolve_root(root_path: Path | None) -> Path:
    from core.config import Config

    config = Config()
    root = Path(root_path) if root_path else config.nexus_root
    return root.resolve()


def _resolve_workspace(workspace_path: Path | None) -> Path:
    from core.config import Config

    config = Config()
    workspace = Path(workspace_path) if workspace_path else config.workspace_path
    return workspace.resolve()


def _default_index_paths(root: Path) -> list[Path]:
    candidates = []
    for name in ("core", "docs"):
        candidate = root / name
        if candidate.exists():
            candidates.append(candidate)
    return candidates or [root]


def _resolve_index_paths(root: Path, paths: list[str] | None) -> list[Path]:
    if not paths:
        return _default_index_paths(root)

    resolved = []
    for raw_path in paths:
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not candidate.is_relative_to(root):
            raise ValueError(f"Index path must be under NEXUS root: {candidate}")
        resolved.append(candidate)
    return resolved


def _resolve_output_dir(workspace: Path, output_dir: str | None) -> Path | None:
    if output_dir is None:
        return None
    candidate = Path(output_dir)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(workspace):
        raise ValueError(f"Output directory must be under workspace: {candidate}")
    return candidate


async def _run_blocking(func, *args, **kwargs):
    import anyio

    if kwargs:
        import functools

        func = functools.partial(func, **kwargs)
    return await anyio.to_thread.run_sync(func, *args)


def build_memory_search(
    query: str,
    root_path: Path | None = None,
    mode: str = "mock",
    backend: str | None = None,
    limit: int = 5,
    min_score: float = 0.2,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    root = _resolve_root(root_path)
    index_paths = _resolve_index_paths(root, paths)
    logger.info("build_memory_search init root=%s", root)
    from nexus_research import build_research_payload

    payload = build_research_payload(
        question=query,
        root_path=root,
        mode=mode,
        backend=backend,
        limit=limit,
        min_score=min_score,
        paths=[str(p) for p in index_paths],
    )
    payload["query"] = payload.pop("question")
    logger.info("build_memory_search indexed_chunks=%s", payload.get("indexed_chunks"))
    logger.info("build_memory_search results=%s", len(payload.get("sources", [])))
    return payload


def build_evidence_pack(
    question: str,
    root_path: Path | None = None,
    workspace_path: Path | None = None,
    output_dir: str | None = None,
    mode: str = "mock",
    backend: str | None = None,
    limit: int = 5,
    min_score: float = 0.2,
    paths: list[str] | None = None,
    cancel_check=None,
    progress_callback=None,
) -> dict[str, str]:
    if not question or not question.strip():
        raise ValueError("Question cannot be empty.")

    mode = mode.lower()
    if mode not in {"mock", "local"}:
        raise ValueError(f"Unsupported mode: {mode}. Use 'mock' or 'local'.")

    root = _resolve_root(root_path)
    workspace = _resolve_workspace(workspace_path)
    index_paths = _resolve_index_paths(root, paths)
    resolved_output = _resolve_output_dir(workspace, output_dir)

    from nexus_research import run_research

    outputs = run_research(
        question=question,
        root_path=root,
        output_dir=resolved_output,
        mode=mode,
        backend=backend,
        limit=limit,
        min_score=min_score,
        paths=[str(p) for p in index_paths],
        cancel_check=cancel_check,
        progress_callback=progress_callback,
    )

    return {key: str(path) for key, path in outputs.items()}


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _latest_matching_file(candidates: list[Path]) -> Path | None:
    existing = [candidate for candidate in candidates if candidate.exists()]
    if not existing:
        return None
    return max(existing, key=lambda candidate: candidate.stat().st_mtime)


def get_latest_research_evidence(workspace_path: Path | None = None) -> dict[str, Any]:
    workspace = _resolve_workspace(workspace_path)
    matches = [
        path
        for path in workspace.rglob("sources.json")
        if (path.parent / "report.md").exists() and (path.parent / "metrics.json").exists()
    ]
    latest = _latest_matching_file(matches)
    if latest is None:
        return {"found": False, "message": "No evidence pack found under workspace."}

    output_dir = latest.parent
    return {
        "found": True,
        "output_dir": str(output_dir),
        "report": str(output_dir / "report.md"),
        "sources": str(latest),
        "trace": str(output_dir / "trace.jsonl"),
        "graph": str(output_dir / "reasoning_graph.mmd"),
        "metrics": _read_json(output_dir / "metrics.json"),
        "summary": {
            "question": (_read_json(latest) or {}).get("question"),
            "backend": (_read_json(latest) or {}).get("backend"),
            "claim_count": ((_read_json(latest) or {}).get("synthesis") or {}).get("verification_summary", {}).get(
                "claim_count", 0
            ),
        },
    }


def get_latest_swarm_eval(root_path: Path | None = None, workspace_path: Path | None = None) -> dict[str, Any]:
    root = _resolve_root(root_path)
    workspace = _resolve_workspace(workspace_path)
    matches: list[Path] = []
    for base in (root / "artifacts", workspace, workspace / "evals"):
        if not base.exists():
            continue
        matches.extend(path for path in base.rglob("report.json") if "swarm" in path.as_posix().lower())
    latest = _latest_matching_file(matches)
    if latest is None:
        return {"found": False, "message": "No swarm evaluation report found."}

    return {
        "found": True,
        "report": str(latest),
        "payload": _read_json(latest),
    }


def get_latest_provider_canaries(root_path: Path | None = None, workspace_path: Path | None = None) -> dict[str, Any]:
    root = _resolve_root(root_path)
    workspace = _resolve_workspace(workspace_path)
    matches: list[Path] = []
    for base in (root / "artifacts", workspace):
        if not base.exists():
            continue
        matches.extend(base.rglob("provider-canaries.json"))
    latest = _latest_matching_file(matches)
    if latest is None:
        return {"found": False, "message": "No provider canary report found."}

    return {
        "found": True,
        "report": str(latest),
        "payload": _read_json(latest),
    }


def get_latest_evidence_ledger(root_path: Path | None = None, workspace_path: Path | None = None) -> dict[str, Any]:
    root = _resolve_root(root_path)
    workspace = _resolve_workspace(workspace_path)
    matches: list[Path] = []
    for base in (root / "artifacts", workspace):
        if not base.exists():
            continue
        matches.extend(base.rglob("evidence-ledger.json"))
    latest = _latest_matching_file(matches)
    if latest is None:
        return {"found": False, "message": "No evidence ledger found."}

    return {
        "found": True,
        "report": str(latest),
        "payload": _read_json(latest),
    }


def _terminal_job_status(status: str) -> bool:
    return status in {"completed", "failed", "cancelled"}


def _job_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in job.items()
        if not key.startswith("_")
    }


def _update_job(job_id: str, **fields: Any) -> dict[str, Any]:
    with _JOB_LOCK:
        job = _JOBS[job_id]
        job.update(fields)
        return _job_snapshot(job)


def list_recent_jobs(limit: int = 10) -> dict[str, Any]:
    with _JOB_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda job: job["created_at"], reverse=True)[: max(limit, 1)]
        return {"jobs": [_job_snapshot(job) for job in jobs]}


def get_job_status(job_id: str) -> dict[str, Any]:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return {"found": False, "job_id": job_id, "message": "Unknown job id."}
        return {"found": True, **_job_snapshot(job)}


def cancel_job(job_id: str) -> dict[str, Any]:
    with _JOB_LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return {"found": False, "job_id": job_id, "message": "Unknown job id."}
        if _terminal_job_status(job["status"]):
            return {"found": True, **_job_snapshot(job)}

        job["_cancel_event"].set()
        future = job.get("_future")
        if future is not None and future.cancel():
            job["status"] = "cancelled"
            job["finished_at"] = _iso_now()
            job["message"] = "Cancelled before execution started."
            job["progress"] = {
                "phase": "cancelled",
                "completed": 1,
                "total": 1,
                "percentage": 100,
                "message": job["message"],
                "detail": {},
                "ts": _iso_now(),
            }
        else:
            job["status"] = "cancel_requested"
            job["message"] = "Cancellation requested. Waiting for cooperative stop."

        return {"found": True, **_job_snapshot(job)}


def _run_evidence_job(job_id: str) -> None:
    with _JOB_LOCK:
        job = _JOBS[job_id]
        cancel_event = job["_cancel_event"]
        request = job["_request"]
        job["status"] = "running"
        job["started_at"] = _iso_now()
        job["message"] = "Evidence-pack job running."

    def _cancel_check() -> None:
        if cancel_event.is_set():
            from nexus_research import ResearchCancelledError

            raise ResearchCancelledError("Evidence-pack job cancelled.")

    def _progress(payload: dict[str, Any]) -> None:
        with _JOB_LOCK:
            current = _JOBS.get(job_id)
            if current is None or _terminal_job_status(current["status"]):
                return
            current["progress"] = payload
            current["message"] = payload.get("message", current.get("message"))

    try:
        outputs = build_evidence_pack(
            question=request["question"],
            root_path=request["root_path"],
            workspace_path=request["workspace_path"],
            output_dir=request["output_dir"],
            mode=request["mode"],
            backend=request["backend"],
            limit=request["limit"],
            min_score=request["min_score"],
            paths=request["paths"],
            cancel_check=_cancel_check,
            progress_callback=_progress,
        )
        with _JOB_LOCK:
            job = _JOBS[job_id]
            job["finished_at"] = _iso_now()
            job["result"] = outputs
            if cancel_event.is_set():
                job["status"] = "cancelled"
                job["message"] = "Cancellation was requested before the job finished; outputs retained."
            else:
                job["status"] = "completed"
                job["message"] = "Evidence-pack job completed."
            job["progress"] = {
                "phase": "completed",
                "completed": 1,
                "total": 1,
                "percentage": 100,
                "message": job["message"],
                "detail": {"output_dir": outputs.get("output_dir")},
                "ts": _iso_now(),
            }
    except Exception as exc:
        from nexus_research import ResearchCancelledError

        with _JOB_LOCK:
            job = _JOBS[job_id]
            job["finished_at"] = _iso_now()
            if isinstance(exc, ResearchCancelledError):
                job["status"] = "cancelled"
                job["message"] = str(exc)
            else:
                job["status"] = "failed"
                job["message"] = f"Evidence-pack job failed: {exc}"
                job["error"] = str(exc)
            job["progress"] = {
                "phase": job["status"],
                "completed": 1,
                "total": 1,
                "percentage": 100,
                "message": job["message"],
                "detail": {},
                "ts": _iso_now(),
            }


def start_evidence_job(
    question: str,
    root_path: Path | None = None,
    workspace_path: Path | None = None,
    output_dir: str | None = None,
    mode: str = "mock",
    backend: str | None = None,
    limit: int = 5,
    min_score: float = 0.2,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    root = _resolve_root(root_path)
    workspace = _resolve_workspace(workspace_path)
    index_paths = _resolve_index_paths(root, paths)
    resolved_output = _resolve_output_dir(workspace, output_dir)

    job_id = str(uuid.uuid4())
    request = {
        "question": question,
        "root_path": root,
        "workspace_path": workspace,
        "output_dir": str(resolved_output) if resolved_output is not None else None,
        "mode": mode,
        "backend": backend,
        "limit": limit,
        "min_score": min_score,
        "paths": [str(path) for path in index_paths],
    }
    job = {
        "job_id": job_id,
        "kind": "evidence_pack",
        "status": "pending",
        "created_at": _iso_now(),
        "started_at": None,
        "finished_at": None,
        "message": "Evidence-pack job queued.",
        "progress": {
            "phase": "queued",
            "completed": 0,
            "total": 1,
            "percentage": 0,
            "message": "Queued for execution.",
            "detail": {"paths": request["paths"]},
            "ts": _iso_now(),
        },
        "request": {
            "question": question,
            "mode": mode,
            "backend": backend,
            "limit": limit,
            "min_score": min_score,
            "paths": request["paths"],
            "output_dir": request["output_dir"],
        },
        "result": None,
        "error": None,
        "_cancel_event": threading.Event(),
        "_request": request,
    }

    with _JOB_LOCK:
        _JOBS[job_id] = job

    future = _JOB_EXECUTOR.submit(_run_evidence_job, job_id)
    with _JOB_LOCK:
        _JOBS[job_id]["_future"] = future
        return _job_snapshot(_JOBS[job_id])


def build_grounded_research_prompt(
    question: str,
    paths: list[str] | None = None,
    mode: str = "mock",
    backend: str | None = None,
) -> str:
    path_args = ""
    if paths:
        path_args = " ".join(f'--path "{path}"' for path in paths)

    backend_arg = f' --backend "{backend}"' if backend else ""
    return (
        "Use NEXUS as an evidence-first research engine.\n"
        f"Question: {question}\n"
        f"Mode: {mode}\n"
        f"CLI reference: python nexus_research.py \"{question}\" --mode {mode}{backend_arg} {path_args}\n"
        "Workflow:\n"
        "1. Call `nexus_research` for a quick grounded answer.\n"
        "2. Call `nexus_memory_search` if you need raw claims, supporting sources, or contradictions.\n"
        "3. Call `nexus_export_evidence_pack` or start an evidence job if you need persistent artifacts.\n"
        "4. Cite source IDs when summarizing claims.\n"
        "5. If evidence is mixed or weak, say so explicitly instead of smoothing over the conflict.\n"
    )


def build_evidence_review_prompt(output_dir: str | None = None) -> str:
    location = output_dir or "the latest evidence pack under workspace"
    return (
        "Review a NEXUS evidence pack as an auditor, not as a marketer.\n"
        f"Target: {location}\n"
        "Workflow:\n"
        "1. Read `nexus://evidence/latest` if no explicit output directory is known.\n"
        "2. Inspect `report.md`, `sources.json`, and `metrics.json`.\n"
        "3. Check whether verified claims have opposing evidence or weak confidence.\n"
        "4. Call out missing support, contradictions, and path-scope issues before any summary.\n"
        "5. Prefer exact source IDs and artifact paths in the review.\n"
    )


# =============================================================================
# MCP Server Definition
# =============================================================================

if MCP_AVAILABLE:
    # Initialize FastMCP server
    mcp = FastMCP("nexus")

    # =========================================================================
    # File Operations
    # =========================================================================

    @mcp.tool()
    async def nexus_read(file_path: str, offset: int = 0, limit: int = 500) -> str:
        """
        Read file contents from the NEXUS workspace.

        Args:
            file_path: Path to the file (relative to workspace or absolute)
            offset: Line number to start reading from (0-based)
            limit: Maximum number of lines to read

        Returns:
            File contents as a string with line numbers
        """
        try:
            logger.info("nexus_read start file_path=%s", file_path)
            result = await _run_blocking(
                execute_tool,
                "read",
                {
                    "file_path": file_path,
                    "offset": offset,
                    "limit": limit,
                },
            )
            logger.info("nexus_read done status=%s", result.status)
            return result.output if result.status == "SUCCESS" else f"Error: {result.error}"
        except Exception as e:
            logger.error(f"nexus_read error: {e}")
            return f"Error reading file: {e}"

    @mcp.tool()
    async def nexus_glob(pattern: str, path: str = ".") -> str:
        """
        Find files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g., "**/*.py", "src/**/*.ts")
            path: Directory to search in (default: current directory)

        Returns:
            List of matching file paths
        """
        try:
            logger.info("nexus_glob start pattern=%s path=%s", pattern, path)
            result = await _run_blocking(
                execute_tool,
                "glob",
                {
                    "pattern": pattern,
                    "path": path,
                },
            )
            logger.info("nexus_glob done status=%s", result.status)
            return result.output if result.status == "SUCCESS" else f"Error: {result.error}"
        except Exception as e:
            logger.error(f"nexus_glob error: {e}")
            return f"Error searching files: {e}"

    @mcp.tool()
    async def nexus_grep(pattern: str, path: str = ".", file_type: str | None = None, context_lines: int = 0) -> str:
        """
        Search for patterns in files using ripgrep-style regex.

        Args:
            pattern: Regex pattern to search for
            path: Directory or file to search in
            file_type: Filter by file type (e.g., "py", "js", "ts")
            context_lines: Number of context lines before/after match

        Returns:
            Matching lines with file paths and line numbers
        """
        try:
            params = {"pattern": pattern, "path": path}
            if file_type:
                params["type"] = file_type
            if context_lines > 0:
                params["-C"] = context_lines
            result = await _run_blocking(execute_tool, "grep", params)
            return result.output if result.status == "SUCCESS" else f"Error: {result.error}"
        except Exception as e:
            logger.error(f"nexus_grep error: {e}")
            return f"Error searching: {e}"

    # =========================================================================
    # Code Analysis
    # =========================================================================

    @mcp.tool()
    async def nexus_analyze(task: str) -> str:
        """
        Analyze a coding task using NEXUS multi-agent collaboration.

        This invokes NEXUS's brainstorming mode where Gemini and Claude
        collaborate to analyze and solve the task.

        Args:
            task: Description of the task or question to analyze

        Returns:
            Analysis result from the collaborative agents
        """
        try:
            orch = get_orchestrator()
            result = await _run_blocking(orch.process_turn, task)
            return result.get("response", "No response generated")
        except Exception as e:
            logger.error(f"nexus_analyze error: {e}")
            return f"Error analyzing task: {e}"

    @mcp.tool()
    async def nexus_status() -> str:
        """
        Get current NEXUS system status.

        Returns:
            JSON string with FSM state, active agent, memory stats
        """
        try:
            orch = get_orchestrator()
            status = await _run_blocking(orch.get_system_status)
            import json

            return json.dumps(status, indent=2, default=str)
        except Exception as e:
            logger.error(f"nexus_status error: {e}")
            return f"Error getting status: {e}"

    # =========================================================================
    # Research & Evidence Pack
    # =========================================================================

    @mcp.tool()
    async def nexus_research(
        question: str,
        mode: str = "mock",
        backend: str | None = None,
        limit: int = 5,
        min_score: float = 0.2,
        paths: list[str] | None = None,
    ) -> str:
        """
        Run a local-first research lookup over project memory.

        Returns a short summary with matched sources. Use
        nexus_export_evidence_pack to generate full artifacts.
        """
        try:
            payload = await _run_blocking(
                build_memory_search,
                query=question,
                mode=mode,
                backend=backend,
                limit=limit,
                min_score=min_score,
                paths=paths,
            )
            sources = payload.get("sources", [])
            lines = [
                "# Research Summary",
                "",
                f"Question: {payload.get('query')}",
                f"Mode: {payload.get('mode')}",
                f"Backend: {payload.get('backend')}",
                f"Generated: {payload.get('generated_at')}",
                f"Confidence: {payload.get('synthesis', {}).get('overall_confidence', {}).get('label', 'unknown')}",
                (
                    "Claims: "
                    f"{payload.get('synthesis', {}).get('verification_summary', {}).get('claim_count', 0)} "
                    f"(supported {payload.get('synthesis', {}).get('verification_summary', {}).get('supported_claim_count', 0)}, "
                    f"mixed {payload.get('synthesis', {}).get('verification_summary', {}).get('mixed_claim_count', 0)})"
                ),
                f"Subqueries: {len(payload.get('subqueries', []))}",
                "",
                "Answer:",
            ]
            answer_bullets = payload.get("synthesis", {}).get("answer_bullets", [])
            if answer_bullets:
                for bullet in answer_bullets:
                    lines.append(f"- {bullet}")
            else:
                lines.append("- No grounded answer could be synthesized from the current threshold.")
            lines.extend(["", "Sources:"])
            if sources:
                for source in sources:
                    lines.append(
                        f"- [{source.get('source_id')}] {source.get('file_path')} "
                        f"(L{source.get('start_line')}-{source.get('end_line')})"
                    )
            else:
                lines.append("- No sources matched the query at the current threshold.")
            return "\n".join(lines) + "\n"
        except Exception as e:
            logger.error(f"nexus_research error: {e}")
            return f"Error running research: {e}"

    @mcp.tool()
    async def nexus_memory_search(
        query: str,
        mode: str = "mock",
        backend: str | None = None,
        limit: int = 5,
        min_score: float = 0.2,
        paths: list[str] | None = None,
    ) -> str:
        """
        Search indexed project memory and return structured results.
        """
        try:
            logger.info("nexus_memory_search start query=%s", query)
            payload = await _run_blocking(
                build_memory_search,
                query=query,
                mode=mode,
                backend=backend,
                limit=limit,
                min_score=min_score,
                paths=paths,
            )
            import json

            logger.info("nexus_memory_search done sources=%s", len(payload.get("sources", [])))
            return json.dumps(payload, indent=2, ensure_ascii=True)
        except Exception as e:
            logger.error(f"nexus_memory_search error: {e}")
            return f"Error searching memory: {e}"

    @mcp.tool()
    async def nexus_export_evidence_pack(
        question: str,
        mode: str = "mock",
        backend: str | None = None,
        limit: int = 5,
        min_score: float = 0.2,
        output_dir: str | None = None,
        paths: list[str] | None = None,
    ) -> str:
        """
        Generate a full evidence pack (report, sources, trace, graph, manifest).
        """
        try:
            logger.info("nexus_export_evidence_pack start question=%s", question)
            outputs = await _run_blocking(
                build_evidence_pack,
                question=question,
                output_dir=output_dir,
                mode=mode,
                backend=backend,
                limit=limit,
                min_score=min_score,
                paths=paths,
            )
            import json

            logger.info("nexus_export_evidence_pack done output_dir=%s", outputs.get("output_dir"))
            return json.dumps(outputs, indent=2, ensure_ascii=True)
        except Exception as e:
            logger.error(f"nexus_export_evidence_pack error: {e}")
            return f"Error exporting evidence pack: {e}"

    @mcp.tool()
    async def nexus_start_evidence_job(
        question: str,
        mode: str = "mock",
        backend: str | None = None,
        limit: int = 5,
        min_score: float = 0.2,
        output_dir: str | None = None,
        paths: list[str] | None = None,
    ) -> str:
        """Start a background evidence-pack job and return a job id."""
        try:
            job = start_evidence_job(
                question=question,
                mode=mode,
                backend=backend,
                limit=limit,
                min_score=min_score,
                output_dir=output_dir,
                paths=paths,
            )
            return json.dumps(job, indent=2, ensure_ascii=True)
        except Exception as e:
            logger.error(f"nexus_start_evidence_job error: {e}")
            return f"Error starting evidence job: {e}"

    @mcp.tool()
    async def nexus_job_status(job_id: str) -> str:
        """Fetch the latest state for a background job."""
        try:
            return json.dumps(get_job_status(job_id), indent=2, ensure_ascii=True)
        except Exception as e:
            logger.error(f"nexus_job_status error: {e}")
            return f"Error getting job status: {e}"

    @mcp.tool()
    async def nexus_cancel_job(job_id: str) -> str:
        """Request cancellation for a background job."""
        try:
            return json.dumps(cancel_job(job_id), indent=2, ensure_ascii=True)
        except Exception as e:
            logger.error(f"nexus_cancel_job error: {e}")
            return f"Error cancelling job: {e}"

    # =========================================================================
    # Shell Execution (sandboxed or validated host execution)
    # =========================================================================

    @mcp.tool()
    async def nexus_bash(command: str, timeout: int = 30) -> str:
        """
        Execute a shell command in the NEXUS workspace.

        Execution mode is explicit:
        - `sandboxed` when Docker isolation is active
        - `validated_host` when host execution is explicitly allowed

        Args:
            command: Shell command to execute
            timeout: Timeout in seconds (default 30, max 120)

        Returns:
            Command output (stdout + stderr)
        """
        try:
            tool_manager = get_tool_manager()
            bash_handler = tool_manager.tools.get("bash")
            effective_mode = "validated_host"
            if bash_handler and hasattr(bash_handler, "effective_mode"):
                effective_mode = bash_handler.effective_mode()

            result = execute_tool(
                "bash",
                {
                    "command": command,
                    "timeout": min(timeout, 120) * 1000,  # Convert to ms, cap at 120s
                },
            )
            if result.status == "SUCCESS":
                return f"[mode={effective_mode}]\n{result.output}"
            return f"[mode={effective_mode}] Error: {result.error}"
        except Exception as e:
            logger.error(f"nexus_bash error: {e}")
            return f"Error executing command: {e}"

    # =========================================================================
    # Resources (optional - for exposing project context)
    # =========================================================================

    @mcp.resource("nexus://config")
    async def get_nexus_config() -> str:
        """Get NEXUS configuration summary."""
        try:
            from core.config import Config

            config = Config()
            return config.to_string()
        except Exception as e:
            return f"Error loading config: {e}"

    @mcp.resource("nexus://agents")
    async def get_nexus_agents() -> str:
        """Get registered agent information."""
        try:
            from core.foundation.agents.unified_registry import get_registry

            registry = get_registry()
            agents = registry.list_agents()
            import json

            return json.dumps(agents, indent=2, default=str)
        except Exception as e:
            return f"Error loading agents: {e}"

    @mcp.resource("nexus://evidence/latest")
    async def get_latest_evidence_resource() -> str:
        """Get the latest research evidence pack found under the workspace."""
        try:
            return json.dumps(get_latest_research_evidence(), indent=2, ensure_ascii=True)
        except Exception as e:
            return f"Error loading latest evidence pack: {e}"

    @mcp.resource("nexus://swarm-eval/latest")
    async def get_latest_swarm_eval_resource() -> str:
        """Get the latest swarm evaluation report."""
        try:
            return json.dumps(get_latest_swarm_eval(), indent=2, ensure_ascii=True)
        except Exception as e:
            return f"Error loading latest swarm eval: {e}"

    @mcp.resource("nexus://provider-canaries/latest")
    async def get_latest_provider_canaries_resource() -> str:
        """Get the latest provider canary report."""
        try:
            return json.dumps(get_latest_provider_canaries(), indent=2, ensure_ascii=True)
        except Exception as e:
            return f"Error loading latest provider canaries: {e}"

    @mcp.resource("nexus://evidence-ledger/latest")
    async def get_latest_evidence_ledger_resource() -> str:
        """Get the latest CI evidence ledger."""
        try:
            return json.dumps(get_latest_evidence_ledger(), indent=2, ensure_ascii=True)
        except Exception as e:
            return f"Error loading latest evidence ledger: {e}"

    @mcp.resource("nexus://jobs/latest")
    async def get_latest_jobs_resource() -> str:
        """Get recent MCP background jobs."""
        try:
            return json.dumps(list_recent_jobs(), indent=2, ensure_ascii=True)
        except Exception as e:
            return f"Error loading recent jobs: {e}"

    if hasattr(mcp, "prompt"):

        @mcp.prompt(title="Grounded Research")
        def nexus_grounded_research_prompt(
            question: str,
            mode: str = "mock",
            backend: str | None = None,
            paths: list[str] | None = None,
        ) -> str:
            return build_grounded_research_prompt(question=question, paths=paths, mode=mode, backend=backend)

        @mcp.prompt(title="Evidence Review")
        def nexus_evidence_review_prompt(output_dir: str | None = None) -> str:
            return build_evidence_review_prompt(output_dir=output_dir)


# =============================================================================
# Server Entry Point
# =============================================================================


class MCPNotAvailableError(RuntimeError):
    """Raised when MCP SDK is not installed."""

    pass


def main():
    """
    Run NEXUS MCP server.

    V9.8 DETOX: Raises MCPNotAvailableError instead of sys.exit()
    for proper exception handling when imported as a module.
    """
    if not MCP_AVAILABLE:
        raise MCPNotAvailableError("MCP SDK not installed. Install with: pip install mcp")

    logger.info("Starting NEXUS MCP Server...")
    logger.info(
        "Tools: nexus_read, nexus_glob, nexus_grep, nexus_analyze, nexus_status, "
        "nexus_research, nexus_memory_search, nexus_export_evidence_pack, "
        "nexus_start_evidence_job, nexus_job_status, nexus_cancel_job, nexus_bash"
    )
    logger.info(
        "Resources: nexus://config, nexus://agents, nexus://evidence/latest, "
        "nexus://swarm-eval/latest, nexus://provider-canaries/latest, "
        "nexus://evidence-ledger/latest, nexus://jobs/latest"
    )
    if hasattr(mcp, "prompt"):
        logger.info("Prompts: Grounded Research, Evidence Review")

    # Run server with stdio transport
    mcp.run(transport="stdio")


if __name__ == "__main__":
    try:
        main()
    except MCPNotAvailableError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
