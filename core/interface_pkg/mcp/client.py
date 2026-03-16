"""
MCP Client - Subprocess communication with MCP servers

Zero-dependency implementation using JSON-RPC 2.0 over stdio.
Manages server subprocess lifecycle and message exchange.
"""

import contextlib
import json
import logging
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .protocol import (
    MCPCapabilities,
    MCPError,
    MCPInitializeResult,
    MCPMethod,
    MCPRequest,
    MCPResponse,
    MCPTool,
    MCPToolResult,
)

# V9 Cyborg Hardening: Logger for MCP debugging
_logger = logging.getLogger(__name__)

# =============================================================================
# Exceptions
# =============================================================================


class MCPClientError(Exception):
    """Base exception for MCP client errors."""

    pass


class MCPConnectionError(MCPClientError):
    """Failed to connect to MCP server."""

    pass


class MCPTimeoutError(MCPClientError):
    """Request timed out."""

    pass


class MCPServerError(MCPClientError):
    """Server returned an error."""

    def __init__(self, error: MCPError):
        self.error = error
        super().__init__(f"MCP Error {error.code}: {error.message}")


# =============================================================================
# Client State
# =============================================================================


@dataclass
class MCPClientState:
    """Internal state of MCP client."""

    initialized: bool = False
    server_info: dict | None = None
    capabilities: MCPCapabilities | None = None
    available_tools: list[MCPTool] = field(default_factory=list)


# =============================================================================
# MCP Client
# =============================================================================


class MCPClient:
    """
    MCP Client for communicating with MCP servers via stdio.

    Usage:
        client = MCPClient(command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"])
        try:
            client.initialize()
            tools = client.list_tools()
            result = client.call_tool("read_file", {"path": "/tmp/test.txt"})
        finally:
            client.close()

    Or with context manager:
        with MCPClient(command=["..."]) as client:
            tools = client.list_tools()
    """

    # Client identification
    CLIENT_NAME = "nexus-mcp-client"
    CLIENT_VERSION = "7.6.0"
    PROTOCOL_VERSION = "2024-11-05"

    # Timeouts
    DEFAULT_TIMEOUT = 30.0  # seconds
    INIT_TIMEOUT = 30.0  # seconds

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        """
        Initialize MCP client.

        Args:
            command: Command to start the MCP server (e.g., ["npx", "-y", "server-name"])
            env: Environment variables for subprocess
            cwd: Working directory for subprocess
            timeout: Default timeout for requests
        """
        self.command = command
        self.env = env
        self.cwd = cwd
        self.timeout = timeout

        # Internal state
        self._process: subprocess.Popen | None = None
        self._state = MCPClientState()
        self._request_id = 0
        self._lock = threading.Lock()

        # Response queue for async reading
        self._response_queue: queue.Queue = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._stderr_thread: threading.Thread | None = None
        self._stderr_stop = threading.Event()

    def __enter__(self) -> "MCPClient":
        """Context manager entry."""
        self.start()
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def start(self) -> None:
        """
        Start the MCP server subprocess.

        Raises:
            MCPConnectionError: If subprocess fails to start
        """
        if self._process is not None:
            raise MCPClientError("Client already started")

        try:
            # Start subprocess with stdio pipes
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.env,
                cwd=str(self.cwd) if self.cwd else None,
                text=True,
                bufsize=1,  # Line buffered
            )

            # Start reader thread
            self._reader_stop.clear()
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name="mcp-reader",
            )
            self._reader_thread.start()

            # Start stderr reader thread to avoid pipe backpressure
            self._stderr_stop.clear()
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop,
                daemon=True,
                name="mcp-stderr",
            )
            self._stderr_thread.start()

            # Give server time to start
            time.sleep(0.1)

            # Check if process is still running
            if self._process.poll() is not None:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                raise MCPConnectionError(
                    f"Server process exited immediately. Command: {' '.join(self.command)}\nStderr: {stderr}"
                )

        except FileNotFoundError as e:
            raise MCPConnectionError(
                f"Command not found: {self.command[0]}. Make sure the MCP server is installed."
            ) from e
        except Exception as e:
            raise MCPConnectionError(f"Failed to start MCP server: {e}") from e

    def initialize(self) -> MCPInitializeResult:
        """
        Perform MCP initialization handshake.

        Returns:
            MCPInitializeResult with server capabilities

        Raises:
            MCPClientError: If initialization fails
        """
        if self._process is None:
            self.start()

        # Send initialize request
        response = self._send_request(
            MCPMethod.INITIALIZE,
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": self.CLIENT_NAME,
                    "version": self.CLIENT_VERSION,
                },
            },
            timeout=self.INIT_TIMEOUT,
        )

        if response.is_error:
            raise MCPServerError(response.error)

        # Parse result
        result = MCPInitializeResult.from_dict(response.result or {})
        self._state.initialized = True
        self._state.capabilities = result.capabilities
        self._state.server_info = response.result

        # Send initialized notification (no response expected)
        self._send_notification(MCPMethod.INITIALIZED, {})

        return result

    def close(self) -> None:
        """
        Close connection and terminate server subprocess.
        """
        # Stop reader thread
        self._reader_stop.set()
        self._stderr_stop.set()

        if self._process is not None:
            try:
                # Try graceful shutdown
                if self._state.initialized:
                    with contextlib.suppress(Exception):
                        self._send_request(MCPMethod.SHUTDOWN, {}, timeout=2.0)

                # Close pipes
                if self._process.stdin:
                    self._process.stdin.close()
                if self._process.stdout:
                    self._process.stdout.close()
                if self._process.stderr:
                    self._process.stderr.close()

                # Terminate process
                self._process.terminate()
                try:
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()

            finally:
                self._process = None
                self._state = MCPClientState()

        # Wait for reader thread
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        if self._stderr_thread and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=1.0)

    @property
    def is_connected(self) -> bool:
        """Check if connected to server."""
        return self._process is not None and self._process.poll() is None

    @property
    def is_initialized(self) -> bool:
        """Check if initialization handshake completed."""
        return self._state.initialized

    # =========================================================================
    # Tool Operations
    # =========================================================================

    def list_tools(self) -> list[MCPTool]:
        """
        List available tools from server.

        Returns:
            List of MCPTool definitions

        Raises:
            MCPServerError: If server returns an error
        """
        self._ensure_initialized()

        response = self._send_request(MCPMethod.TOOLS_LIST, {})

        if response.is_error:
            raise MCPServerError(response.error)

        # Parse tools
        tools = []
        result = response.result or {}
        for tool_data in result.get("tools", []):
            tools.append(MCPTool.from_dict(tool_data))

        self._state.available_tools = tools
        return tools

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> MCPToolResult:
        """
        Call a tool on the server.

        Args:
            name: Tool name
            arguments: Tool arguments
            timeout: Optional timeout override

        Returns:
            MCPToolResult with tool output

        Raises:
            MCPServerError: If server returns an error
        """
        self._ensure_initialized()

        response = self._send_request(
            MCPMethod.TOOLS_CALL,
            {
                "name": name,
                "arguments": arguments or {},
            },
            timeout=timeout,
        )

        if response.is_error:
            raise MCPServerError(response.error)

        # Parse result
        return MCPToolResult.from_dict(response.result or {})

    def get_tool(self, name: str) -> MCPTool | None:
        """
        Get a specific tool by name.

        Args:
            name: Tool name

        Returns:
            MCPTool or None if not found
        """
        if not self._state.available_tools:
            self.list_tools()

        for tool in self._state.available_tools:
            if tool.name == name:
                return tool
        return None

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _ensure_initialized(self) -> None:
        """Ensure client is initialized."""
        if not self._state.initialized:
            raise MCPClientError("Client not initialized. Call initialize() first.")

    def _next_request_id(self) -> int:
        """Get next request ID (thread-safe)."""
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send_request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> MCPResponse:
        """
        Send a request and wait for response.

        Args:
            method: JSON-RPC method name
            params: Request parameters
            timeout: Request timeout

        Returns:
            MCPResponse

        Raises:
            MCPTimeoutError: If request times out
            MCPConnectionError: If connection is lost
        """
        if not self.is_connected:
            raise MCPConnectionError("Not connected to server")

        # Build request
        request_id = self._next_request_id()
        request = MCPRequest(method=method, id=request_id, params=params)

        # Send request
        try:
            message = request.to_json() + "\n"
            self._process.stdin.write(message)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise MCPConnectionError(f"Failed to send request: {e}") from e

        # Wait for response
        timeout = timeout or self.timeout
        try:
            response_data = self._response_queue.get(timeout=timeout)
        except queue.Empty:
            raise MCPTimeoutError(f"Request timed out after {timeout}s") from None

        # Parse response
        if isinstance(response_data, Exception):
            raise response_data

        return MCPResponse.from_dict(response_data)

    def _send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        """
        Send a notification (no response expected).

        Args:
            method: JSON-RPC method name
            params: Notification parameters
        """
        if not self.is_connected:
            return

        # Notifications have no id
        message = (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params or {},
                }
            )
            + "\n"
        )

        try:
            self._process.stdin.write(message)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass  # Ignore notification errors

    def _reader_loop(self) -> None:
        """
        Background thread that reads responses from server stdout.
        """
        try:
            while not self._reader_stop.is_set():
                if self._process is None or self._process.stdout is None:
                    break

                # Check if process is still running
                if self._process.poll() is not None:
                    break

                try:
                    line = self._process.stdout.readline()
                    if not line:
                        break

                    line = line.strip()
                    if not line:
                        continue

                    # Parse JSON response
                    try:
                        data = json.loads(line)
                        self._response_queue.put(data)
                    except json.JSONDecodeError as e:
                        # V9: Log JSON parse errors for debugging
                        _logger.warning(f"[MCP] JSON parse error: {e} | Line preview: {line[:100]}")

                except Exception as e:
                    if not self._reader_stop.is_set():
                        self._response_queue.put(MCPConnectionError(f"Reader error: {e}"))
                    break

        except Exception as e:
            _logger.debug(f"[MCP] Reader thread exiting: {e}")

    def _stderr_loop(self) -> None:
        """
        Background thread that drains server stderr to avoid blocking.
        """
        try:
            while not self._stderr_stop.is_set():
                if self._process is None or self._process.stderr is None:
                    break

                line = self._process.stderr.readline()
                if not line:
                    break

                line = line.strip()
                if line:
                    _logger.debug(f"[MCP][stderr] {line}")

        except Exception as e:
            _logger.debug(f"[MCP] Stderr thread exiting: {e}")


# =============================================================================
# Convenience Functions
# =============================================================================


def create_mcp_client(
    command: list[str],
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    auto_initialize: bool = True,
) -> MCPClient:
    """
    Create and optionally initialize an MCP client.

    Args:
        command: Command to start the MCP server
        env: Environment variables
        cwd: Working directory
        auto_initialize: If True, start and initialize immediately

    Returns:
        MCPClient instance
    """
    client = MCPClient(command=command, env=env, cwd=cwd)

    if auto_initialize:
        client.start()
        client.initialize()

    return client
