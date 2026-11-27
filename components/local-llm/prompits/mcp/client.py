"""
Generic MCP client for prompits agents.

An agent uses it to reach an outside Model Context Protocol server: list its tools and call one. It wraps the
official MCP Python SDK 2.x, an optional runtime (`pip install -r prompits/mcp/requirements.txt`). Importing this
module never needs the SDK; only opening a connection does, and it says what to install when the SDK is missing.

- Transports: `stdio` (launch a command and talk over its stdin and stdout), `http` (streamable HTTP) and `sse`
  (the older HTTP+SSE transport, kept for servers that have not moved on).
- Protocol: the SDK asks the server for `server/discover` (revision 2026-07-28) and falls back to the `initialize`
  handshake on older servers. `protocol_version` in the config pins a revision instead.
- Capabilities: this client offers none of its own (no sampling, roots or elicitation), so a server never waits for
  an answer the client cannot give.
- Results come back as plain dicts in the protocol's own field names (`structuredContent`, `isError`, ...).
- Secrets: `redact_url` and `redact_value` hide credentials in URLs, headers and environment values before anything
  is logged or returned for debugging.
"""

from __future__ import annotations

import importlib.metadata
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import anyio

TRANSPORTS = ("stdio", "http", "sse")
_TRANSPORT_ALIASES = {
    "streamable-http": "http",
    "streamable_http": "http",
    "streamablehttp": "http",
    "https": "http",
}
REQUIREMENTS_HINT = "pip install -r prompits/mcp/requirements.txt"
DEFAULT_CLIENT_NAME = "prompits-mcp-client"
DEFAULT_CLIENT_VERSION = "1.0.0"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_SSE_READ_TIMEOUT_SECONDS = 300.0
MAX_LIST_PAGES = 100
REDACTED = "***redacted***"
_SENSITIVE_NAME_PARTS = ("auth", "token", "secret", "key", "password", "credential", "signature", "session")
_URL_IN_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"<>]+")


class MCPRuntimeMissing(RuntimeError):
    """The optional MCP SDK 2.x runtime is not installed."""


class MCPConnectionError(RuntimeError):
    """The MCP server refused the connection or a request at the HTTP level (its status is in the message)."""


def runtime_version() -> Optional[str]:
    """Return the installed MCP SDK version, or None when it is not installed."""
    try:
        return importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return None


def require_runtime() -> None:
    """Raise `MCPRuntimeMissing`, naming the requirements file, unless MCP SDK 2.x is installed."""
    version = runtime_version()
    try:
        major = int(str(version).split(".", 1)[0]) if version else 0
    except ValueError:
        major = 0
    if major < 2:
        found = f"mcp {version} is installed" if version else "mcp is not installed"
        raise MCPRuntimeMissing(f"MCP needs the mcp 2.x SDK, but {found}. Install it with: {REQUIREMENTS_HINT}")


def is_sensitive_name(name: Any) -> bool:
    """Return whether a header, parameter or field name looks like it carries a credential."""
    lowered = str(name or "").strip().lower()
    return any(part in lowered for part in _SENSITIVE_NAME_PARTS)


def redact_url(url: Any) -> Any:
    """Hide the userinfo and every credential-like query parameter of a URL; other values pass through."""
    if not isinstance(url, str) or "://" not in url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return REDACTED
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    has_userinfo = "@" in parts.netloc
    if not has_userinfo and not any(is_sensitive_name(key) for key, _value in pairs):
        return url  # nothing to hide: keep the URL byte for byte
    netloc = f"{REDACTED}@{parts.netloc.rpartition('@')[2]}" if has_userinfo else parts.netloc
    query = parts.query
    if pairs:
        query = urlencode([(key, REDACTED if is_sensitive_name(key) else value) for key, value in pairs], safe="*{}")
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def redact_text(text: Any) -> Any:
    """Hide the credentials of every URL inside free text, such as an error message."""
    if not isinstance(text, str) or "://" not in text:
        return text
    return _URL_IN_TEXT.sub(lambda match: redact_url(match.group(0)), text)


def redact_value(value: Any, key_hint: Optional[str] = None) -> Any:
    """Return a copy of `value` with credentials hidden: values under credential-like keys and secrets inside URLs."""
    if key_hint is not None and is_sensitive_name(key_hint) and value not in (None, "", {}, []):
        return REDACTED
    if isinstance(value, Mapping):
        return {str(key): redact_value(item, str(key)) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _optional_float(value: Any, default: Optional[float]) -> Optional[float]:
    if value in (None, ""):
        return default
    number = float(value)
    if number <= 0:
        raise ValueError("MCP timeouts must be greater than 0.")
    return number


@dataclass(frozen=True)
class MCPServerConfig:
    """Where an MCP server is and how to reach it."""

    transport: str
    command: str = ""
    args: Tuple[str, ...] = ()
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    read_timeout: Optional[float] = None
    sse_read_timeout: float = DEFAULT_SSE_READ_TIMEOUT_SECONDS
    protocol_version: str = ""
    client_name: str = DEFAULT_CLIENT_NAME
    client_version: str = DEFAULT_CLIENT_VERSION
    # An httpx2 auth flow for an HTTP server that asks for sign-in, such as the SDK's OAuthClientProvider.
    auth: Any = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if self.transport not in TRANSPORTS:
            raise ValueError(f"Unsupported MCP transport '{self.transport}'. Use one of: {', '.join(TRANSPORTS)}.")
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio MCP transport requires a command.")
        if self.transport in ("http", "sse"):
            if not self.url:
                raise ValueError(f"{self.transport} MCP transport requires a url.")
            if urlsplit(self.url).scheme not in ("http", "https"):
                raise ValueError(f"{self.transport} MCP transport requires an http or https url.")
        if self.transport == "sse" and self.protocol_version:
            raise ValueError("The sse transport only speaks the initialize handshake; leave protocol_version unset.")

    @classmethod
    def from_mapping(
        cls,
        config: Mapping[str, Any],
        *,
        client_name: str = DEFAULT_CLIENT_NAME,
        client_version: str = DEFAULT_CLIENT_VERSION,
    ) -> "MCPServerConfig":
        """Build a config from a plain mapping such as a pulser's `mcp` block.

        Keys: `transport` (or `type`), `command`, `args`, `env`, `cwd`, `url`, `headers`, `timeout`,
        `read_timeout_seconds`, `sse_read_timeout`, `protocol_version` and `client_info` (`name`, `version`).
        Without a transport, a command means stdio and a url means streamable HTTP. Values that are None are dropped.
        """
        if not isinstance(config, Mapping):
            raise ValueError("MCP server config must be a mapping.")
        command = str(config.get("command") or "").strip()
        url = str(config.get("url") or "").strip()
        transport = str(config.get("transport") or config.get("type") or "").strip().lower()
        transport = _TRANSPORT_ALIASES.get(transport, transport)
        if not transport:
            transport = "stdio" if command else "http" if url else ""

        raw_args = config.get("args")
        if raw_args is None:
            args: Tuple[str, ...] = ()
        elif isinstance(raw_args, (list, tuple)):
            args = tuple(str(arg) for arg in raw_args)
        else:
            args = (str(raw_args),)

        raw_env = config.get("env")
        env = (
            {str(key): str(value) for key, value in raw_env.items() if value is not None}
            if isinstance(raw_env, Mapping)
            else None
        )
        raw_headers = config.get("headers")
        headers = (
            {str(key): str(value) for key, value in raw_headers.items() if value is not None}
            if isinstance(raw_headers, Mapping)
            else {}
        )
        client_info = config.get("client_info") or config.get("clientInfo")
        if isinstance(client_info, Mapping):
            client_name = str(client_info.get("name") or client_name)
            client_version = str(client_info.get("version") or client_version)

        cwd = config.get("cwd")
        return cls(
            transport=transport,
            command=command,
            args=args,
            env=env,
            cwd=str(cwd) if cwd not in (None, "") else None,
            url=url,
            headers=headers,
            timeout=_optional_float(config.get("timeout"), DEFAULT_TIMEOUT_SECONDS) or DEFAULT_TIMEOUT_SECONDS,
            read_timeout=_optional_float(config.get("read_timeout_seconds", config.get("read_timeout")), None),
            sse_read_timeout=_optional_float(config.get("sse_read_timeout"), DEFAULT_SSE_READ_TIMEOUT_SECONDS)
            or DEFAULT_SSE_READ_TIMEOUT_SECONDS,
            protocol_version=str(config.get("protocol_version") or config.get("protocolVersion") or "").strip(),
            client_name=client_name,
            client_version=client_version,
        )

    def describe(self) -> Dict[str, Any]:
        """Return the config with every credential hidden, for logs and debug output."""
        return redact_value(
            {
                "transport": self.transport,
                "command": self.command or None,
                "args": list(self.args) or None,
                "env": self.env,
                "cwd": self.cwd,
                "url": self.url or None,
                "headers": self.headers or None,
                "protocol_version": self.protocol_version or None,
                "client_info": {"name": self.client_name, "version": self.client_version},
            }
        )


def _wire(model: Any) -> Dict[str, Any]:
    """Dump an SDK model in the protocol's own field names."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return dict(model)


class MCPConnection:
    """One open connection to an MCP server: a thin view over the SDK client."""

    def __init__(self, client: Any):
        self._client = client

    @property
    def protocol_version(self) -> str:
        """The protocol revision agreed with the server."""
        return str(self._client.protocol_version)

    @property
    def server_info(self) -> Dict[str, Any]:
        """The server's name and version, as it reported them."""
        info = self._client.server_info
        return _wire(info) if info is not None else {}

    @property
    def capabilities(self) -> Dict[str, Any]:
        """The capabilities the server reported."""
        return _wire(self._client.server_capabilities)

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Return every tool the server lists, following its pages."""
        tools: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        for _page in range(MAX_LIST_PAGES):
            listing = await self._client.list_tools(cursor=cursor)
            tools.extend(_wire(tool) for tool in listing.tools)
            cursor = listing.next_cursor
            if not cursor:
                return tools
        raise RuntimeError(f"MCP server listed more than {MAX_LIST_PAGES} pages of tools.")

    async def call_tool(self, name: str, arguments: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        """Call one tool and return its result; a failed tool comes back with `isError` set, not as an exception."""
        if not str(name or "").strip():
            raise ValueError("An MCP tool call needs a tool name.")
        if arguments is not None and not isinstance(arguments, Mapping):
            raise ValueError("MCP tool arguments must be a JSON object.")
        result = await self._client.call_tool(str(name), dict(arguments or {}))
        return _wire(result)


def _client_mode(config: MCPServerConfig) -> str:
    """Map the config's protocol pin to the SDK's connect mode."""
    if config.transport == "sse":
        return "legacy"
    if not config.protocol_version:
        return "auto"
    from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS, MODERN_PROTOCOL_VERSIONS

    if config.protocol_version in MODERN_PROTOCOL_VERSIONS:
        return config.protocol_version
    if config.protocol_version in HANDSHAKE_PROTOCOL_VERSIONS:
        return "legacy"
    known = ", ".join((*HANDSHAKE_PROTOCOL_VERSIONS, *MODERN_PROTOCOL_VERSIONS))
    raise ValueError(f"Unknown MCP protocol version '{config.protocol_version}'. Known versions: {known}.")


class _HttpStatus:
    """The HTTP status of the latest message POST that failed; the SDK's own error leaves it out."""

    def __init__(self) -> None:
        self.status: Optional[int] = None
        self.reason: str = ""

    async def observe(self, response: Any) -> None:
        if getattr(response.request, "method", "") != "POST":
            return  # a refused GET stream is normal: servers without server-to-client streams answer 405
        if response.status_code >= 400:
            self.status, self.reason = response.status_code, str(response.reason_phrase or "")
        else:
            self.status, self.reason = None, ""


@asynccontextmanager
async def _streamable_http_transport(config: MCPServerConfig, http_status: _HttpStatus):
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    timeout = httpx2.Timeout(config.timeout, read=config.sse_read_timeout)
    async with httpx2.AsyncClient(
        headers=dict(config.headers), timeout=timeout, auth=config.auth, event_hooks={"response": [http_status.observe]}
    ) as http_client:
        async with streamable_http_client(config.url, http_client=http_client) as streams:
            yield streams


def _server_target(config: MCPServerConfig, http_status: _HttpStatus) -> Any:
    """What the SDK client connects to for this config."""
    if config.transport == "stdio":
        from mcp import StdioServerParameters

        return StdioServerParameters(command=config.command, args=list(config.args), env=config.env, cwd=config.cwd)
    if config.transport == "http":
        return _streamable_http_transport(config, http_status)
    from mcp.client.sse import sse_client

    return sse_client(
        config.url,
        headers=dict(config.headers) or None,
        timeout=config.timeout,
        sse_read_timeout=config.sse_read_timeout,
    )


def _single_failure(group: BaseExceptionGroup) -> Optional[Exception]:
    """The one real error inside nested task-group wrappers, or None when there are several."""
    current: BaseException = group
    while isinstance(current, BaseExceptionGroup) and len(current.exceptions) == 1:
        current = current.exceptions[0]
    return current if isinstance(current, Exception) and not isinstance(current, BaseExceptionGroup) else None


@asynccontextmanager
async def connect(config: MCPServerConfig) -> AsyncIterator[MCPConnection]:
    """Open a connection to the MCP server `config` names, for one or more calls."""
    require_runtime()
    from mcp import Client
    from mcp_types import Implementation

    mode = _client_mode(config)
    http_status = _HttpStatus()
    client = Client(
        _server_target(config, http_status),
        mode=mode,
        read_timeout_seconds=config.read_timeout,
        client_info=Implementation(name=config.client_name, version=config.client_version),
    )
    try:
        try:
            async with client:
                yield MCPConnection(client)
        except BaseExceptionGroup as group:
            failure = _single_failure(group)
            if failure is None:
                raise
            raise failure from group
    except Exception as exc:
        if http_status.status is None or isinstance(exc, MCPConnectionError):
            raise
        reason = f" {http_status.reason}" if http_status.reason else ""
        raise MCPConnectionError(
            f"MCP server at {redact_url(config.url)} answered HTTP {http_status.status}{reason}: {exc}"
        ) from exc


async def list_tools_async(config: MCPServerConfig) -> List[Dict[str, Any]]:
    """Connect, list every tool and disconnect."""
    async with connect(config) as connection:
        return await connection.list_tools()


async def call_tool_async(
    config: MCPServerConfig, name: str, arguments: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """Connect, call one tool and disconnect."""
    async with connect(config) as connection:
        return await connection.call_tool(name, arguments)


def list_tools(config: MCPServerConfig) -> List[Dict[str, Any]]:
    """Blocking `list_tools_async`, for code that runs outside an event loop."""
    return anyio.run(list_tools_async, config)


def call_tool(config: MCPServerConfig, name: str, arguments: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Blocking `call_tool_async`, for code that runs outside an event loop."""
    return anyio.run(call_tool_async, config, name, arguments)
