"""
Generic MCP server for a table of tools, served over streamable HTTP.

A host program describes each tool (`ToolSpec`: a name, a description, a JSON Schema for its arguments, hints about
its effects and an async handler) and mounts the server on its own Starlette or FastAPI app (`ToolServer.mount`).
The server lists the tools, checks each call's arguments against the tool's schema, runs the handler and returns
the result: a dict as structured content (and the same JSON as text), anything else as text. A handler's exception
becomes a tool error that tells the AI app what went wrong, never a traceback.

It decides nothing about who may call: the host's own boundary does (for a local resource, loopback only and no
browser pages). It keeps no state between calls (stateless streamable HTTP, plain JSON replies), so it answers
2026-07-28 clients and older ones that use the initialize handshake alike. It needs the optional MCP SDK 2.x
(`prompits/mcp/requirements.txt`); `available()` says whether it is installed, and nothing is imported before a server
is built.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence, Union

from prompits.mcp.client import MCPRuntimeMissing, redact_text, require_runtime

LOG = logging.getLogger(__name__)
TOOL_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# What one tool result may carry back to an AI app; a larger answer asks the app to narrow its request.
MAX_RESULT_CHARS = 2_000_000
MAX_ERROR_CHARS = 2_000
MAX_IMAGE_BYTES = 4_000_000  # base64 characters of one image an answer carries
IMAGE_TYPES = ('image/png', 'image/jpeg', 'image/webp')
DEFAULT_PATH = "/mcp"

ToolHandler = Callable[[Dict[str, Any]], Awaitable[Any]]


class ToolFailure(Exception):
    """Raise from a handler to report a failure in plain words; any other exception is reported by its message."""


@dataclass(frozen=True)
class ToolSpec:
    """One tool: what an AI app sees in the list, and the handler that runs it."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: ToolHandler = field(compare=False, repr=False)
    title: Optional[str] = None
    read_only: Optional[bool] = None
    destructive: Optional[bool] = None
    idempotent: Optional[bool] = None
    open_world: Optional[bool] = None

    def __post_init__(self) -> None:
        if not TOOL_NAME.fullmatch(self.name or ""):
            raise ValueError(f"MCP tool name '{self.name}' must be 1-128 letters, digits, '.', '_' or '-'.")
        if not isinstance(self.input_schema, Mapping) or self.input_schema.get("type") != "object":
            raise ValueError(f"MCP tool '{self.name}' needs an object JSON Schema for its arguments.")
        if not callable(self.handler):
            raise ValueError(f"MCP tool '{self.name}' needs a handler.")


@dataclass(frozen=True)
class ToolImage:
    """An answer that is a picture: base64 `data` of `mime_type`, with `details` (a dict) as its structured content."""

    data: str
    mime_type: str = "image/jpeg"
    details: Mapping[str, Any] = field(default_factory=dict)


def available() -> bool:
    """Whether the MCP SDK 2.x this server needs is installed."""
    try:
        require_runtime()
    except MCPRuntimeMissing:
        return False
    return True


class _Forward:
    """The MCP route's ASGI app: hands each request to the running lifespan's handler (a class, so Starlette treats it
    as an ASGI app rather than a request function)."""

    def __init__(self, live: List[Any]):
        self.live = live

    async def __call__(self, scope, receive, send):
        if not self.live:
            body = b'{"detail":"The MCP server is not running."}'
            await send({"type": "http.response.start", "status": 503, "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.live[-1](scope, receive, send)


def current_access_token():
    """The bearer token of the MCP request being handled (the SDK's `AccessToken`), or None without sign-in."""
    from mcp.server.auth.middleware.auth_context import get_access_token

    return get_access_token()


def error_text(exc: BaseException) -> str:
    """What an AI app reads about a failed call: the exception's own words (an HTTP error's detail), no traceback."""
    detail = getattr(exc, "detail", None)
    text = str(detail if detail not in (None, "") else exc).strip() or type(exc).__name__
    text = redact_text(text)
    return text if len(text) <= MAX_ERROR_CHARS else text[: MAX_ERROR_CHARS - 3] + "..."


class ToolServer:
    """An MCP server for a table of tools (a fixed list, or a function that returns the current list)."""

    def __init__(
        self,
        name: str,
        tools: Union[Sequence[ToolSpec], Callable[[], Sequence[ToolSpec]]],
        *,
        version: str = "",
        instructions: Optional[str] = None,
    ):
        require_runtime()
        self.name, self.version, self.instructions = name, version, instructions
        self._tools = tools
        self._server = self._build_server()
        self._endpoint = None
        self._live: List[Any] = []  # the request handlers of the lifespans running now, newest last

    def tools(self) -> List[ToolSpec]:
        """The tools as they stand now; names must be unique."""
        current = list(self._tools() if callable(self._tools) else self._tools)
        names = [tool.name for tool in current]
        if len(names) != len(set(names)):
            raise ValueError("MCP tool names must be unique.")
        return current

    def _find(self, name: str) -> Optional[ToolSpec]:
        return next((tool for tool in self.tools() if tool.name == name), None)

    def _build_server(self):
        import mcp_types as types
        from mcp.server.lowlevel import Server

        def listed(tool: ToolSpec):
            hints = {
                "read_only_hint": tool.read_only,
                "destructive_hint": tool.destructive,
                "idempotent_hint": tool.idempotent,
                "open_world_hint": tool.open_world,
            }
            hints = {key: value for key, value in hints.items() if value is not None}
            return types.Tool(
                name=tool.name,
                title=tool.title,
                description=tool.description,
                input_schema=dict(tool.input_schema),
                annotations=types.ToolAnnotations(**hints) if hints else None,
            )

        async def on_list_tools(_ctx, _params):
            return types.ListToolsResult(tools=[listed(tool) for tool in self.tools()])

        async def on_call_tool(_ctx, params):
            return await self.call(params.name, params.arguments)

        def input_schema(name: str):
            tool = self._find(name)
            return dict(tool.input_schema) if tool else None

        return Server(
            self.name,
            version=self.version,
            instructions=self.instructions,
            on_list_tools=on_list_tools,
            on_call_tool=on_call_tool,
            get_tool_input_schema=input_schema,
        )

    async def call(self, name: str, arguments: Optional[Mapping[str, Any]]):
        """Run one tool call and return the protocol's `CallToolResult` (a failure is a result with `isError`)."""
        import jsonschema
        import mcp_types as types

        def failed(text: str):
            return types.CallToolResult(content=[types.TextContent(text=text)], is_error=True)

        tool = self._find(name)
        if tool is None:
            return failed(f"Unknown tool: {name}")
        values = dict(arguments or {})
        try:
            jsonschema.validate(values, dict(tool.input_schema))
        except jsonschema.ValidationError as exc:
            where = "/".join(str(part) for part in exc.absolute_path) or "arguments"
            return failed(f"Invalid arguments for {name} ({where}): {exc.message}")
        try:
            value = await tool.handler(values)
        except ToolFailure as exc:  # a refusal the tool meant: the AI app reads it, the log needn't
            return failed(error_text(exc))
        except Exception as exc:  # the AI app reads why; the host's log keeps the type
            LOG.warning("MCP tool %s failed: %s", name, type(exc).__name__)
            return failed(error_text(exc))
        return self.result(value)

    @staticmethod
    def result(value: Any):
        """A handler's answer as a `CallToolResult`: a dict is structured content, a list is `{"items": [...]}`."""
        import mcp_types as types

        if isinstance(value, ToolImage):
            if value.mime_type not in IMAGE_TYPES or not value.data or len(value.data) > MAX_IMAGE_BYTES:
                return types.CallToolResult(content=[types.TextContent(text="The picture is too large or not an image.")],
                                            is_error=True)
            details = json.loads(json.dumps(dict(value.details), ensure_ascii=False, default=str))
            return types.CallToolResult(content=[types.ImageContent(data=value.data, mime_type=value.mime_type),
                                                 types.TextContent(text=json.dumps(details, ensure_ascii=False))],
                                        structured_content=details)
        if isinstance(value, list):
            value = {"items": value}
        if isinstance(value, dict):
            text = json.dumps(value, ensure_ascii=False, default=str)
            structured: Optional[Dict[str, Any]] = json.loads(text)
        else:
            text, structured = ("" if value is None else str(value)), None
        if len(text) > MAX_RESULT_CHARS:
            return types.CallToolResult(
                content=[types.TextContent(text="The answer is too large for an AI app; ask for less, such as a smaller limit.")],
                is_error=True,
            )
        return types.CallToolResult(content=[types.TextContent(text=text)], structured_content=structured)

    def _ensure_endpoint(self):
        if self._endpoint is None:
            self._endpoint = _Forward(self._live)
        return self._endpoint

    @asynccontextmanager
    async def running(self):
        """Keep the server's request handling running; the host enters this for as long as it serves.

        Each run gets its own SDK session manager (one may run only once), so a host whose lifespan runs again, as a
        test client's does, serves again. Enter and leave it in the same task, as the SDK's task group requires.
        """
        from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

        # Stateless with plain JSON replies: no session kept between calls, and no stream left open.
        self._server.streamable_http_app(stateless_http=True, json_response=True)
        manager = self._server.session_manager
        async with manager.run():
            handler = StreamableHTTPASGIApp(manager)
            self._live.append(handler)
            try:
                yield
            finally:
                self._live.remove(handler)

    def mount(
        self,
        app: Any,
        path: str = DEFAULT_PATH,
        *,
        verifier: Any = None,
        resource_url: Optional[str] = None,
        resource_metadata_url: Optional[str] = None,
        required_scopes: Sequence[str] = (),
    ) -> None:
        """Serve the tools at `path` on a Starlette or FastAPI app, running while the app runs (its lifespan).

        The app's own middleware still applies, so its boundary decides who reaches the tools. With a `verifier` (the
        SDK's `TokenVerifier`, such as `local_auth.LocalAuthorization` through `ProviderTokenVerifier`), every request
        needs a bearer token issued for `resource_url`; a request without one is answered 401 with a pointer to
        `resource_metadata_url`, which starts the AI app's sign-in. A handler reads the caller's token with
        `current_access_token()`.
        """
        from starlette.routing import Route

        endpoint = self._ensure_endpoint()
        if verifier is not None:
            from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
            from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
            from pydantic import AnyHttpUrl
            from starlette.middleware.authentication import AuthenticationMiddleware

            metadata = AnyHttpUrl(resource_metadata_url) if resource_metadata_url else None
            backend = BearerAuthBackend(verifier, resource_server_url=AnyHttpUrl(resource_url) if resource_url else None)
            endpoint = AuthenticationMiddleware(
                AuthContextMiddleware(RequireAuthMiddleware(endpoint, list(required_scopes), metadata)), backend=backend)
        # First, so a host's catch-all page route (such as `/{filename}`) never takes the MCP path.
        app.router.routes.insert(0, Route(path, endpoint=endpoint, methods=["GET", "POST", "DELETE"]))
        original = app.router.lifespan_context
        server = self

        @asynccontextmanager
        async def lifespan(scope_app):
            async with server.running():
                async with original(scope_app) as state:
                    yield state

        app.router.lifespan_context = lifespan
