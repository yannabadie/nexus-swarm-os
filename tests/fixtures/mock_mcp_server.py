#!/usr/bin/env python3
"""
Mock MCP Server for Testing

A simple MCP server that responds to JSON-RPC 2.0 requests on stdio.
Used for testing the MCPClient without external dependencies.

Usage:
    python mock_mcp_server.py

Protocol:
    - Reads JSON-RPC 2.0 requests from stdin (one per line)
    - Writes JSON-RPC 2.0 responses to stdout (one per line)
"""

import json
import sys

# =============================================================================
# Server State
# =============================================================================

SERVER_NAME = "mock-mcp-server"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"

# Mock tools provided by this server
MOCK_TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the input message",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string", "description": "Message to echo"}},
            "required": ["message"],
        },
    },
    {
        "name": "add",
        "description": "Add two numbers",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"},
            },
            "required": ["a", "b"],
        },
    },
    {
        "name": "fail",
        "description": "Always fails (for testing error handling)",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# =============================================================================
# Request Handlers
# =============================================================================


def handle_initialize(params: dict) -> dict:
    """Handle initialize request."""
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def handle_tools_list(params: dict) -> dict:
    """Handle tools/list request."""
    return {"tools": MOCK_TOOLS}


def handle_tools_call(params: dict) -> dict:
    """Handle tools/call request."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name == "echo":
        message = arguments.get("message", "")
        return {"content": [{"type": "text", "text": f"Echo: {message}"}], "isError": False}

    elif tool_name == "add":
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)
        return {"content": [{"type": "text", "text": str(a + b)}], "isError": False}

    elif tool_name == "fail":
        return {"content": [{"type": "text", "text": "This tool always fails"}], "isError": True}

    else:
        return {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True}


def handle_shutdown(params: dict) -> dict:
    """Handle shutdown request."""
    return {}


# =============================================================================
# Request Router
# =============================================================================

HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    "shutdown": handle_shutdown,
}


def handle_request(request: dict) -> dict | None:
    """
    Handle a JSON-RPC 2.0 request.

    Args:
        request: Parsed JSON-RPC request

    Returns:
        Response dict or None for notifications
    """
    method = request.get("method", "")
    params = request.get("params", {})
    request_id = request.get("id")

    # Notifications (no id) don't get responses
    if request_id is None:
        return None

    # Find handler
    handler = HANDLERS.get(method)

    if handler is None:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}

    try:
        result = handler(params)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(e)}}


# =============================================================================
# Main Loop
# =============================================================================


def main():
    """Main server loop."""
    # Disable buffering for stdin/stdout
    sys.stdout.reconfigure(line_buffering=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {e}"}}
            print(json.dumps(response), flush=True)
            continue

        response = handle_request(request)

        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
