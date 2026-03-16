"""
AsyncClaudeDriver - TRUE Non-blocking Claude CLI Driver.

NEXUS V9.0 Async-First Architecture

CRITICAL ARCHITECTURE DIFFERENCE FROM SYNC DRIVER:
- Uses asyncio.create_subprocess_exec (NOT subprocess.Popen)
- Uses async for line in proc.stdout (NOT iter(readline))
- This ensures the Event Loop is NOT blocked during CLI execution
- Tracks processes by session_uuid via AsyncProcessHandle

This solves:
1. REPL blocking during Claude execution
2. Ctrl+C not working (orphan processes)
3. No streaming capability

Usage:
    driver = AsyncClaudeDriver(config)

    # Non-streaming (collects full response)
    result = await driver.invoke(context, session_uuid="abc123")

    # Streaming (yields tokens)
    async for chunk in driver.invoke_stream(context, session_uuid="abc123"):
        print(chunk, end="")

References:
- https://docs.python.org/3/library/asyncio-subprocess.html
- https://superfastpython.com/asyncio-subprocess/
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from core.foundation.agents.unified_registry import get_registry
from core.foundation.async_primitives import AsyncProcessHandle, CancellationToken, create_safe_task
from core.foundation.async_primitives.process_handle import get_process_registry


@dataclass
class AsyncClaudeDriverConfig:
    """Configuration for AsyncClaudeDriver."""

    cli_path: str = "claude"
    timeout: float = 300.0
    model: str = "claude-sonnet-4-6"
    workspace_path: Path = field(default_factory=Path.cwd)
    verbose: bool = False


class AsyncClaudeDriver:
    """
    TRUE Async Claude CLI Driver.

    Key differences from sync ClaudeDriverHybrid:
    - Uses asyncio.create_subprocess_exec (NOT subprocess.Popen)
    - Uses async for line in proc.stdout (NOT iter(readline))
    - Tracks processes by session_uuid via AsyncProcessHandle
    - Properly handles asyncio.CancelledError with re-raise

    The sync driver blocks the event loop during:
    - proc.stdout.readline() - BLOCKING
    - proc.wait() - BLOCKING (without timeout)

    This async driver uses:
    - async for line in proc.stdout - NON-BLOCKING
    - await proc.wait() - NON-BLOCKING
    """

    def __init__(self, config: AsyncClaudeDriverConfig):
        """
        Initialize async Claude driver.

        Args:
            config: Driver configuration
        """
        self.config = config
        self.workspace_path = Path(config.workspace_path)
        self.io_buffer = self.workspace_path / "_IO_BUFFER"
        self.io_buffer.mkdir(exist_ok=True)

        # Track ALL active processes by UUID for cancellation
        self._active_handles: dict[str, AsyncProcessHandle] = {}

        # Global registry for cross-driver coordination
        self._registry = get_process_registry()

    async def invoke(
        self,
        context: str,
        *,
        session_uuid: str | None = None,
        token: CancellationToken | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Non-blocking invoke that collects full response.

        Args:
            context: Markdown context with system prompt
            session_uuid: Unique ID for file isolation (from SwarmSessionManager)
            token: CancellationToken for graceful cancellation
            task_id: Optional task ID for tracking

        Returns:
            Dict structured NEXUS response with:
            - sender: "Claude"
            - action_type: "TALK" or "TOOL_USE"
            - content: Response text
            - tool_use: Optional tool use dict
            - status: "CONTINUE" or "FINISHED"
            - next_agent: Suggested next agent
        """
        chunks = []
        async for chunk in self.invoke_stream(context, session_uuid=session_uuid, token=token, task_id=task_id):
            chunks.append(chunk)

        full_response = "".join(chunks)
        return self._parse_hybrid_response(full_response)

    async def invoke_stream(
        self,
        context: str,
        *,
        session_uuid: str | None = None,
        token: CancellationToken | None = None,
        task_id: str | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> AsyncIterator[str]:
        """
        TRUE Non-blocking streaming invoke.

        CRITICAL: Uses async for line in proc.stdout
        This does NOT block the Event Loop (unlike iter(readline))

        Args:
            context: Markdown context with system prompt
            session_uuid: Unique ID for isolation (from SwarmSessionManager)
            token: CancellationToken for graceful cancellation
            task_id: Optional task ID for tracking
            on_token: Optional callback for each token (in addition to yield)

        Yields:
            Text chunks as they arrive from Claude CLI
        """
        token = token or CancellationToken()
        unique_id = session_uuid or str(uuid.uuid4())[:8]

        # Write context to isolated file
        context_file = self.io_buffer / f"claude_context_{unique_id}.md"
        context_file.write_text(context, encoding="utf-8")

        # Build command
        cmd = [
            str(self.config.cli_path),
            "-p",
            f"@{context_file}",
            "--dangerously-skip-permissions",
        ]

        # Add model if specified
        if self.config.model:
            cmd.extend(["--model", self.config.model])

        handle: AsyncProcessHandle | None = None

        try:
            # TRUE ASYNC: create_subprocess_exec (NOT Popen!)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace_path),
            )

            # Track by UUID
            handle = AsyncProcessHandle(
                proc=proc, session_uuid=unique_id, task_id=task_id, agent_id="claude", created_at=datetime.now()
            )
            self._active_handles[unique_id] = handle
            await self._registry.register(handle)

            # Register cancellation callback
            async def cancel_process():
                if handle and handle.is_running:
                    await handle.terminate_gracefully()

            # V9.5: Use SafeTaskManager for error tracking
            token.on_cancel(lambda: create_safe_task(cancel_process(), name="claude_cancel"))

            if self.config.verbose:
                print(f"[AsyncClaudeDriver] Started process pid={proc.pid}, uuid={unique_id[:8]}", file=sys.stderr)

            # V11 SYNCHROTRON: Parallel stderr drain to prevent deadlock
            # Problem: If stderr buffer fills (64KB) while we read stdout, subprocess blocks
            # Solution: Background task drains stderr continuously
            stderr_buffer = []

            async def drain_stderr():
                """Background task to drain stderr and prevent buffer fill deadlock."""
                try:
                    async for line_bytes in proc.stderr:
                        stderr_buffer.append(line_bytes.decode("utf-8", errors="replace"))
                except asyncio.CancelledError:
                    pass  # Expected on cleanup

            stderr_task = asyncio.create_task(drain_stderr())

            # TRUE ASYNC STREAMING: async for (NOT iter(readline)!)
            # This yields control to Event Loop between lines
            start_time = datetime.now()
            try:
                async for line_bytes in proc.stdout:
                    token.check()  # Check cancellation between lines

                    # Check timeout
                    elapsed = (datetime.now() - start_time).total_seconds()
                    if elapsed > self.config.timeout:
                        stderr_task.cancel()
                        await handle.terminate_gracefully()
                        raise TimeoutError(f"Claude CLI timed out after {self.config.timeout}s")

                    line = line_bytes.decode("utf-8", errors="replace")
                    if line:
                        yield line
                        if on_token:
                            on_token(line)

                # Wait for process completion with timeout
                try:
                    await asyncio.wait_for(proc.wait(), timeout=10.0)
                except TimeoutError:
                    await handle.terminate_gracefully()

                # Cancel stderr task (should be done by now)
                stderr_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stderr_task

                if proc.returncode != 0:
                    stderr_content = "".join(stderr_buffer)
                    raise RuntimeError(f"Claude CLI failed (code {proc.returncode}): {stderr_content}")

                if self.config.verbose:
                    print(f"[AsyncClaudeDriver] Process completed, code={proc.returncode}", file=sys.stderr)

            except asyncio.CancelledError:
                stderr_task.cancel()
                raise

        except asyncio.CancelledError:
            # CRITICAL: Re-raise after cleanup (don't swallow!)
            if self.config.verbose:
                print("[AsyncClaudeDriver] Cancelled, cleaning up...", file=sys.stderr)
            raise

        finally:
            # Cleanup: terminate process if still running
            if handle and handle.is_running:
                await handle.terminate_gracefully()

            # Remove from tracking
            self._active_handles.pop(unique_id, None)
            await self._registry.unregister(unique_id)

            # Cleanup context file
            try:
                if context_file.exists():
                    context_file.unlink()
            except Exception:
                pass

    async def cancel_by_uuid(self, session_uuid: str) -> bool:
        """
        Cancel a specific task by its session UUID.

        Args:
            session_uuid: The UUID of the process to cancel

        Returns:
            True if process was found and terminated
        """
        handle = self._active_handles.get(session_uuid)
        if handle:
            await handle.terminate_gracefully()
            self._active_handles.pop(session_uuid, None)
            await self._registry.unregister(session_uuid)
            return True
        return False

    async def cancel_all(self) -> int:
        """
        Cancel all active processes (for Ctrl+C handler).

        Returns:
            Number of processes terminated
        """
        count = 0
        for uuid_key in list(self._active_handles.keys()):
            handle = self._active_handles.pop(uuid_key, None)
            if handle and handle.is_running:
                await handle.terminate_gracefully()
                await self._registry.unregister(uuid_key)
                count += 1
        return count

    @property
    def active_process_count(self) -> int:
        """Get count of active processes."""
        return sum(1 for h in self._active_handles.values() if h.is_running)

    def list_active_processes(self) -> list[dict[str, Any]]:
        """List all active processes."""
        return [h.to_dict() for h in self._active_handles.values() if h.is_running]

    def _parse_hybrid_response(self, raw_text: str) -> dict[str, Any]:
        """
        Parse Claude's natural language response with XML tags.

        Claude uses a hybrid format:
        - Natural language response text
        - Tool use in <tool_use name="...">...</tool_use> blocks

        Returns:
            Dict with sender, action_type, content, tool_use, status, next_agent
        """
        # Extract tool use blocks (XML pattern)
        tool_pattern = r'<tool_use\s+name="(\w+)">(.*?)</tool_use>'
        tool_matches = list(re.finditer(tool_pattern, raw_text, re.DOTALL))

        # Extract content (everything OUTSIDE tool blocks)
        content = raw_text
        for match in tool_matches:
            content = content.replace(match.group(0), "")
        content = content.strip()

        # Parse tool use if present
        tool_use = None
        action_type = "TALK"

        if tool_matches:
            match = tool_matches[0]
            tool_name = match.group(1)
            tool_args_raw = match.group(2).strip()

            try:
                arguments = json.loads(tool_args_raw)
            except json.JSONDecodeError:
                # Try parsing as key=value
                arguments = self._parse_keyvalue_args(tool_args_raw)

            tool_use = {
                "tool_name": tool_name,
                "arguments": arguments,
                "expected_outcome": f"Execute {tool_name} successfully",
            }
            action_type = "TOOL_USE"

        # Detect status from content
        status = "CONTINUE"
        finish_keywords = ["task complete", "finished", "done", "terminé", "fini"]
        if any(keyword in content.lower() for keyword in finish_keywords):
            status = "FINISHED"

        # Get display name and alternate from registry
        registry = get_registry()

        return {
            "sender": registry.get_display_name("claude"),
            "action_type": action_type,
            "content": content,
            "tool_use": tool_use,
            "status": status,
            "next_agent": registry.get_alternate("claude"),
        }

    def _parse_keyvalue_args(self, args_text: str) -> dict[str, str]:
        """Parse arguments in key=value format (fallback if not JSON)."""
        args = {}
        for line in args_text.split("\n"):
            line = line.strip()
            if "=" in line:
                key, value = line.split("=", 1)
                args[key.strip()] = value.strip()
        return args

    def invoke_sync(
        self,
        context: str,
        *,
        session_uuid: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Synchronous invoke for backward compatibility.

        DEPRECATED: Use `await invoke()` for async code.

        This method runs the async invoke in a new event loop.
        It's intended for gradual migration from sync to async.

        Args:
            context: Markdown context with system prompt
            session_uuid: Unique ID for file isolation
            task_id: Optional task ID for tracking

        Returns:
            Dict structured NEXUS response

        .. deprecated:: V8.4.4
            Use `await driver.invoke()` in async code.
        """
        import warnings

        warnings.warn(
            "invoke_sync() is deprecated since V8.4.4. Use `await driver.invoke()` in async code.",
            DeprecationWarning,
            stacklevel=2,
        )
        return asyncio.run(self.invoke(context, session_uuid=session_uuid, task_id=task_id))


# Factory function for easy creation
def create_async_claude_driver(config: Any, workspace_path: Path, model: str | None = None) -> AsyncClaudeDriver:
    """
    Create an AsyncClaudeDriver from a NEXUS config object.

    Args:
        config: NEXUS config object with claude_cli_path, timeout, etc.
        workspace_path: Workspace path for file I/O
        model: Optional model override

    Returns:
        Configured AsyncClaudeDriver
    """
    return AsyncClaudeDriver(
        AsyncClaudeDriverConfig(
            cli_path=getattr(config, "claude_cli_path", "claude"),
            timeout=getattr(config, "timeout", 300.0),
            model=model or getattr(config, "claude_sonnet_model", "claude-sonnet-4-6"),
            workspace_path=workspace_path,
            verbose=getattr(config, "verbose", False),
        )
    )
