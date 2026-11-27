"""
Model Context Protocol support for prompits.

`prompits.mcp.client` lets an agent reach an outside MCP server: list its tools and call one. `prompits.mcp.server`
serves a table of tools to AI apps over streamable HTTP, mounted on a host's own app behind its own boundary. The MCP
SDK both build on is an optional runtime (`prompits/mcp/requirements.txt`); importing this package never needs it.
"""

from prompits.mcp.client import (
    MCPConnection,
    MCPConnectionError,
    MCPRuntimeMissing,
    MCPServerConfig,
    call_tool,
    call_tool_async,
    connect,
    list_tools,
    list_tools_async,
    redact_text,
    redact_url,
    redact_value,
    require_runtime,
    runtime_version,
)

__all__ = [
    "MCPConnection",
    "MCPConnectionError",
    "MCPRuntimeMissing",
    "MCPServerConfig",
    "call_tool",
    "call_tool_async",
    "connect",
    "list_tools",
    "list_tools_async",
    "redact_text",
    "redact_url",
    "redact_value",
    "require_runtime",
    "runtime_version",
]
