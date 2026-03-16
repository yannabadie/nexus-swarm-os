"""
MCP Protocol Types - JSON-RPC 2.0 over stdio

Zero-dependency implementation of MCP protocol types.
Based on Model Context Protocol specification (2024).

JSON-RPC 2.0 Reference: https://www.jsonrpc.org/specification
MCP Reference: https://modelcontextprotocol.io/
"""

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# =============================================================================
# JSON-RPC 2.0 Base Types
# =============================================================================

JSONRPC_VERSION = "2.0"


@dataclass
class MCPRequest:
    """
    JSON-RPC 2.0 Request object.

    Example:
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {}
        }
    """

    method: str
    id: int
    params: dict[str, Any] | None = None
    jsonrpc: str = JSONRPC_VERSION

    def to_json(self) -> str:
        """Serialize to JSON string."""
        data = {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
            "method": self.method,
        }
        if self.params is not None:
            data["params"] = self.params
        return json.dumps(data)

    @classmethod
    def from_dict(cls, data: dict) -> "MCPRequest":
        """Deserialize from dict."""
        return cls(
            method=data.get("method", ""),
            id=data.get("id", 0),
            params=data.get("params"),
            jsonrpc=data.get("jsonrpc", JSONRPC_VERSION),
        )


@dataclass
class MCPError:
    """
    JSON-RPC 2.0 Error object.

    Standard error codes:
        -32700: Parse error
        -32600: Invalid Request
        -32601: Method not found
        -32602: Invalid params
        -32603: Internal error
    """

    code: int
    message: str
    data: Any | None = None

    def to_dict(self) -> dict:
        """Serialize to dict."""
        result = {
            "code": self.code,
            "message": self.message,
        }
        if self.data is not None:
            result["data"] = self.data
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "MCPError":
        """Deserialize from dict."""
        return cls(
            code=data.get("code", -32603),
            message=data.get("message", "Unknown error"),
            data=data.get("data"),
        )


@dataclass
class MCPResponse:
    """
    JSON-RPC 2.0 Response object.

    Example success:
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [...]}
        }

    Example error:
        {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "Method not found"}
        }
    """

    id: int
    result: Any | None = None
    error: MCPError | None = None
    jsonrpc: str = JSONRPC_VERSION

    @property
    def is_error(self) -> bool:
        """Check if response is an error."""
        return self.error is not None

    @property
    def is_success(self) -> bool:
        """Check if response is successful."""
        return self.error is None

    def to_json(self) -> str:
        """Serialize to JSON string."""
        data = {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
        }
        if self.error is not None:
            data["error"] = self.error.to_dict()
        else:
            data["result"] = self.result
        return json.dumps(data)

    @classmethod
    def from_dict(cls, data: dict) -> "MCPResponse":
        """Deserialize from dict."""
        error = None
        if "error" in data:
            error = MCPError.from_dict(data["error"])

        return cls(
            id=data.get("id", 0),
            result=data.get("result"),
            error=error,
            jsonrpc=data.get("jsonrpc", JSONRPC_VERSION),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "MCPResponse":
        """Deserialize from JSON string."""
        return cls.from_dict(json.loads(json_str))


# =============================================================================
# MCP-Specific Types
# =============================================================================


@dataclass
class MCPToolInputSchema:
    """
    JSON Schema for tool input parameters.

    Example:
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"}
            },
            "required": ["path"]
        }
    """

    type: str = "object"
    properties: dict[str, Any] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "type": self.type,
            "properties": self.properties,
            "required": self.required,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MCPToolInputSchema":
        """Deserialize from dict."""
        return cls(
            type=data.get("type", "object"),
            properties=data.get("properties", {}),
            required=data.get("required", []),
        )


@dataclass
class MCPTool:
    """
    MCP Tool definition.

    Example:
        {
            "name": "read_file",
            "description": "Read the contents of a file",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"}
                },
                "required": ["path"]
            }
        }
    """

    name: str
    description: str = ""
    inputSchema: MCPToolInputSchema | None = None

    def to_dict(self) -> dict:
        """Serialize to dict."""
        result = {
            "name": self.name,
            "description": self.description,
        }
        if self.inputSchema is not None:
            result["inputSchema"] = self.inputSchema.to_dict()
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "MCPTool":
        """Deserialize from dict."""
        input_schema = None
        if "inputSchema" in data:
            input_schema = MCPToolInputSchema.from_dict(data["inputSchema"])

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            inputSchema=input_schema,
        )


class MCPContentType(Enum):
    """Content types for tool results."""

    TEXT = "text"
    IMAGE = "image"
    RESOURCE = "resource"


@dataclass
class MCPContent:
    """
    Content item in tool result.

    Example:
        {
            "type": "text",
            "text": "File contents here..."
        }
    """

    type: str  # "text", "image", "resource"
    text: str | None = None
    data: str | None = None  # Base64 for images
    mimeType: str | None = None
    uri: str | None = None  # For resources

    def to_dict(self) -> dict:
        """Serialize to dict."""
        result = {"type": self.type}
        if self.text is not None:
            result["text"] = self.text
        if self.data is not None:
            result["data"] = self.data
        if self.mimeType is not None:
            result["mimeType"] = self.mimeType
        if self.uri is not None:
            result["uri"] = self.uri
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "MCPContent":
        """Deserialize from dict."""
        return cls(
            type=data.get("type", "text"),
            text=data.get("text"),
            data=data.get("data"),
            mimeType=data.get("mimeType"),
            uri=data.get("uri"),
        )


@dataclass
class MCPToolResult:
    """
    Result from tool execution.

    Example:
        {
            "content": [
                {"type": "text", "text": "File contents..."}
            ],
            "isError": false
        }
    """

    content: list[MCPContent] = field(default_factory=list)
    isError: bool = False

    @property
    def text(self) -> str:
        """Get combined text content."""
        texts = []
        for item in self.content:
            if item.type == "text" and item.text:
                texts.append(item.text)
        return "\n".join(texts)

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "content": [c.to_dict() for c in self.content],
            "isError": self.isError,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MCPToolResult":
        """Deserialize from dict."""
        content = []
        for item in data.get("content", []):
            content.append(MCPContent.from_dict(item))

        return cls(
            content=content,
            isError=data.get("isError", False),
        )


@dataclass
class MCPCapabilities:
    """
    Server capabilities returned during initialization.

    Example:
        {
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {}
            }
        }
    """

    tools: bool = False
    resources: bool = False
    prompts: bool = False
    logging: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "MCPCapabilities":
        """Deserialize from dict (handles nested 'capabilities' key)."""
        caps = data.get("capabilities", data)
        return cls(
            tools="tools" in caps,
            resources="resources" in caps,
            prompts="prompts" in caps,
            logging="logging" in caps,
        )


@dataclass
class MCPServerInfo:
    """
    Server information returned during initialization.

    Example:
        {
            "name": "filesystem-server",
            "version": "1.0.0"
        }
    """

    name: str = "unknown"
    version: str = "0.0.0"

    @classmethod
    def from_dict(cls, data: dict) -> "MCPServerInfo":
        """Deserialize from dict."""
        return cls(
            name=data.get("name", "unknown"),
            version=data.get("version", "0.0.0"),
        )


@dataclass
class MCPInitializeResult:
    """
    Result from initialize request.

    Example:
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {...},
            "serverInfo": {...}
        }
    """

    protocolVersion: str = "2024-11-05"
    capabilities: MCPCapabilities | None = None
    serverInfo: MCPServerInfo | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "MCPInitializeResult":
        """Deserialize from dict."""
        caps = None
        if "capabilities" in data:
            caps = MCPCapabilities.from_dict(data)

        server_info = None
        if "serverInfo" in data:
            server_info = MCPServerInfo.from_dict(data["serverInfo"])

        return cls(
            protocolVersion=data.get("protocolVersion", "2024-11-05"),
            capabilities=caps,
            serverInfo=server_info,
        )


# =============================================================================
# MCP Method Constants
# =============================================================================


class MCPMethod:
    """MCP protocol method names."""

    # Lifecycle
    INITIALIZE = "initialize"
    INITIALIZED = "notifications/initialized"
    SHUTDOWN = "shutdown"

    # Tools
    TOOLS_LIST = "tools/list"
    TOOLS_CALL = "tools/call"

    # Resources (optional)
    RESOURCES_LIST = "resources/list"
    RESOURCES_READ = "resources/read"

    # Prompts (optional)
    PROMPTS_LIST = "prompts/list"
    PROMPTS_GET = "prompts/get"


# =============================================================================
# Error Codes
# =============================================================================


class MCPErrorCode:
    """JSON-RPC 2.0 and MCP error codes."""

    # JSON-RPC 2.0 standard
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    # MCP-specific (reserved range: -32000 to -32099)
    SERVER_NOT_INITIALIZED = -32002
    UNKNOWN_ERROR = -32001
