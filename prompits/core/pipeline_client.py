"""Pipeline for agents: the callee keeps an attachment, and callers reach it through a node.

Callee side (`PipelineAttachment`):
- An agent that can't take inbound connections attaches to the Pipeline node that rendezvous hashing picks from the
  nodes Plaza lists.
- When the node asks, it joins a stream and runs TLS on it with its identity key (`pipeline_tls`).
- It serves each request to its own ASGI app in-process (`serve_http`). Every request first passes the connection-grant
  check (`connection_grants.guard`).
- A relayed request never looks local: its client address is in the discard-only block `100::/64`, never loopback or a
  private network.

Caller side (`PipelineTransport`, `pipeline_client`): an httpx transport that dials the callee's node with Plaza's
pass, runs TLS pinned to the callee key the grant names, and then speaks ordinary HTTP/1.1.
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
import os
import ssl
import time
from typing import Awaitable, Callable, Iterable, Mapping, Optional, Union
from urllib.parse import quote, unquote

import h11
import httpcore
import httpx
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI
from websockets.protocol import State

from . import connection_grants, pipeline_protocol as protocol, pipeline_tls, service_tickets

LOG = logging.getLogger(__name__)
HOST = "agent.pipeline.invalid"
# RFC 6666's discard-only block: not loopback, not private, so no local-trust check can mistake a relayed call.
RELAYED_CLIENT = ("100::1", 0)
MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_HEAD_BYTES = 64 * 1024
IDLE_SECONDS = 300.0


@functools.lru_cache(maxsize=1)
def node_tls_context() -> ssl.SSLContext:
    """Check a node's certificate against the roots httpx uses.

    A Python with no system roots, such as python.org's macOS build, would otherwise refuse a node the agent's own
    HTTPS calls to Plaza already reach. SSL_CERT_FILE or SSL_CERT_DIR, when set, win, as they do for OpenSSL.
    """
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def node_connect(url, **kwargs):
    """websockets' connect, with `node_tls_context` for a `wss` node unless the caller passes its own."""
    if str(url).startswith("wss:") and "ssl" not in kwargs:
        kwargs["ssl"] = node_tls_context()
    return ws_connect(url, **kwargs)
BACKOFF_SECONDS = (0.5, 1.0, 2.0, 5.0, 10.0)
DROPPED_HEADERS = {b"forwarded", b"x-forwarded-for", b"x-forwarded-host", b"x-forwarded-proto", b"x-real-ip"}
EXTENSION = "prompits.pipeline"
WS_ERRORS = (OSError, ConnectionClosed, InvalidHandshake, InvalidURI, asyncio.TimeoutError)
# Every Pipeline connection turns WebSocket compression off: stream frames are TLS ciphertext, which never compresses,
# and deflating it cut throughput about thirtyfold in the P0 benchmark.


async def _maybe(value):
    return await value if inspect.isawaitable(value) else value


class WebSocketStream:
    """A WebSocket connection as a byte stream: binary frames only."""

    def __init__(self, websocket):
        self.websocket = websocket
        self.buffer = b""
        self.closed = False

    async def recv(self, max_bytes: int = 64 * 1024) -> bytes:
        if not self.buffer:
            if self.closed:
                return b""
            try:
                frame = await self.websocket.recv()
            except ConnectionClosed:
                self.closed = True
                return b""
            if not isinstance(frame, (bytes, bytearray)):
                self.closed = True
                await self.websocket.close(protocol.CLOSE_MALFORMED)
                return b""
            self.buffer = bytes(frame)
        data, self.buffer = self.buffer[:max_bytes], self.buffer[max_bytes:]
        return data

    async def send(self, data: bytes) -> None:
        try:
            await self.websocket.send(bytes(data))
        except ConnectionClosed as exc:
            self.closed = True
            raise ConnectionError("The Pipeline stream closed.") from exc

    async def aclose(self) -> None:
        self.closed = True
        with contextlib.suppress(Exception):
            await self.websocket.close()


# --- Callee side ------------------------------------------------------------------------------------------------

async def _next_event(connection: h11.Connection, stream, idle: float):
    while True:
        event = connection.next_event()
        if event is not h11.NEED_DATA:
            return event
        data = await asyncio.wait_for(stream.recv(), idle)
        connection.receive_data(data)


async def serve_http(stream, app, *, extensions: Optional[dict] = None, idle_seconds: float = IDLE_SECONDS,
                     max_request_bytes: int = MAX_REQUEST_BYTES) -> None:
    """Serve HTTP/1.1 requests from `stream` to the ASGI `app`, one after another, until either side closes."""
    connection = h11.Connection(h11.SERVER, max_incomplete_event_size=MAX_HEAD_BYTES)

    async def write(event):
        data = connection.send(event)
        if data:
            await stream.send(data)

    async def fail(status: int):
        body = b'{"detail":"Bad request."}'
        with contextlib.suppress(Exception):
            await write(h11.Response(status_code=status, headers=[(b"content-type", b"application/json"),
                                                                  (b"content-length", str(len(body)).encode()),
                                                                  (b"connection", b"close")]))
            await write(h11.Data(data=body))
            await write(h11.EndOfMessage())

    try:
        while True:
            try:
                event = await _next_event(connection, stream, idle_seconds)
            except h11.RemoteProtocolError:
                await fail(400)
                return
            if not isinstance(event, h11.Request):
                return
            chunks, size = [], 0
            while True:
                part = await _next_event(connection, stream, idle_seconds)
                if isinstance(part, h11.Data):
                    size += len(part.data)
                    if size > max_request_bytes:
                        await fail(413)
                        return
                    chunks.append(part.data)
                elif isinstance(part, h11.EndOfMessage):
                    break
                else:
                    return
            body = b"".join(chunks)
            raw_path, _, query = event.target.partition(b"?")
            scope = {
                "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
                "method": event.method.decode("ascii"), "scheme": "https",
                "path": unquote(raw_path.decode("latin-1")), "raw_path": raw_path, "query_string": query,
                "root_path": "", "headers": [(name, value) for name, value in event.headers if name not in DROPPED_HEADERS],
                "client": RELAYED_CLIENT, "server": (HOST, 443), "extensions": dict(extensions or {}),
            }
            finished = asyncio.Event()
            state = {"started": False, "done": False, "body_sent": False}

            async def receive():
                if not state["body_sent"]:
                    state["body_sent"] = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await finished.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == "http.response.start":
                    state["started"] = True
                    headers = [(bytes(k), bytes(v)) for k, v in message.get("headers") or ()]
                    await write(h11.Response(status_code=message["status"], headers=headers))
                elif message["type"] == "http.response.body" and state["started"] and not state["done"]:
                    chunk = message.get("body") or b""
                    if chunk:
                        await write(h11.Data(data=chunk))
                    if not message.get("more_body"):
                        await write(h11.EndOfMessage())
                        state["done"] = True

            try:
                await app(scope, receive, send)
            except Exception:
                LOG.exception("Relayed request failed in the agent")
                if not state["started"]:
                    await fail(500)
                return
            finally:
                finished.set()
            if not state["done"]:
                if not state["started"]:
                    await fail(500)
                return
            if connection.our_state is h11.MUST_CLOSE or connection.their_state is h11.MUST_CLOSE:
                return
            try:
                connection.start_next_cycle()
            except h11.LocalProtocolError:
                return
    except (asyncio.TimeoutError, ConnectionError, OSError):
        return
    finally:
        with contextlib.suppress(Exception):
            await stream.aclose()


Nodes = Callable[[], Union[Iterable[Mapping], Awaitable[Iterable[Mapping]]]]
Tickets = Callable[[str], Union[dict, Awaitable[dict]]]


class PipelineAttachment:
    """A callee's attachment to Pipeline: stays attached, re-attaches elsewhere, serves streams.

    - `nodes()` returns the live, trusted Pipeline nodes Plaza lists, each `{id, url, weight?, region?, draining?}`.
    - `ticket_for(node_id)` returns Plaza's attach ticket for this agent and that node.
    - `on_endpoint(endpoint or None)` is told the card endpoint to register whenever it changes.
    """

    def __init__(self, *, agent_id: str, app, identity_key, verifier: connection_grants.GrantVerifier,
                 nodes: Nodes, ticket_for: Tickets, region: str = "",
                 on_endpoint: Optional[Callable[[Optional[dict]], None]] = None, connect=node_connect,
                 backoff: Iterable[float] = BACKOFF_SECONDS, plaza_url: str = ""):
        from .service_tickets import public_key_bytes
        self.agent_id, self.region, self.connect = agent_id, region, connect
        self.nodes, self.ticket_for, self.on_endpoint = nodes, ticket_for, on_endpoint
        self.public_key = public_key_bytes(identity_key)
        self.server_context = pipeline_tls.server_context(identity_key, agent_id)
        self.app = connection_grants.guard(app, verifier, plaza_url=plaza_url)
        self.backoff = tuple(backoff)
        self.node: Optional[dict] = None
        self.drained: set = set()
        self.tasks: set = set()
        self._socket = None
        self._stopped = asyncio.Event()

    def endpoint(self) -> Optional[dict]:
        """The card endpoint for the current node, or None while unattached."""
        if not self.node:
            return None
        return {"kind": "pipeline", "node": self.node["id"], "url": self.node["url"],
                "key": service_tickets.key_text(self.public_key)}

    def _announce(self):
        if self.on_endpoint:
            try:
                self.on_endpoint(self.endpoint())
            except Exception:
                LOG.exception("Pipeline endpoint listener failed")

    async def run(self) -> None:
        attempt = 0
        while not self._stopped.is_set():
            listed = list(await _maybe(self.nodes()))
            listed_ids = {str(node.get("id")) for node in listed}
            self.drained &= listed_ids  # a node Plaza no longer lists needs no exclusion
            for node in protocol.choose_nodes(self.agent_id, listed, region=self.region, exclude=self.drained):
                if self._stopped.is_set():
                    return
                try:
                    if await self._attach(node):
                        attempt = 0
                    break  # attached and later lost (or drained): choose again from a fresh list
                except (*WS_ERRORS, ValueError, PermissionError, KeyError) as exc:
                    LOG.warning("Pipeline node %s unavailable: %s", node.get("id"), exc)
            if self._stopped.is_set():
                return
            delay = self.backoff[min(attempt, len(self.backoff) - 1)]
            attempt += 1
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stopped.wait(), delay)

    async def _attach(self, node) -> bool:
        ticket = await _maybe(self.ticket_for(node["id"]))
        async with self.connect(protocol.node_url(node["url"], "/attach"), max_size=protocol.MAX_CONTROL_BYTES,
                                open_timeout=protocol.HELLO_SECONDS, compression=None) as websocket:
            self._socket = websocket
            await websocket.send(protocol.message("hello", ticket=ticket, protocol=protocol.PROTOCOL))
            reply = protocol.read_message(await asyncio.wait_for(websocket.recv(), protocol.HELLO_SECONDS), "attached")
            self.node = {"id": node["id"], "url": node["url"]}
            self._announce()
            refresher = asyncio.create_task(self._refresh(websocket, node["id"], float(reply["expiresAt"])))
            try:
                async for raw in websocket:
                    note = protocol.read_message(raw, "open", "drain", "refreshed")
                    if note["type"] == "open":
                        task = asyncio.create_task(self._serve(node, str(note["stream"])))
                        self.tasks.add(task)
                        task.add_done_callback(self.tasks.discard)
                    elif note["type"] == "drain":
                        self.drained.add(node["id"])
                        break
            except ConnectionClosed:
                pass
            finally:
                refresher.cancel()
                self._socket = None
                self.node = None
                self._announce()
        return True

    async def _refresh(self, websocket, node_id: str, expires_at: float):
        while True:
            await asyncio.sleep(max(1.0, expires_at - time.time() - protocol.REFRESH_MARGIN_SECONDS))
            ticket = await _maybe(self.ticket_for(node_id))
            await websocket.send(protocol.message("refresh", ticket=ticket))
            expires_at = float(service_tickets.peek(ticket)["expiresAt"])

    async def _serve(self, node, stream_id: str):
        try:
            async with self.connect(protocol.node_url(node["url"], "/s/" + quote(stream_id, safe="")),
                                    max_size=protocol.MAX_FRAME_BYTES, open_timeout=protocol.JOIN_SECONDS,
                                    compression=None) as websocket:
                raw = WebSocketStream(websocket)
                tls = await pipeline_tls.TLSStream.handshake(raw, self.server_context, server_side=True)
                await serve_http(tls, self.app, extensions={EXTENSION: {"node": node["id"], "stream": stream_id}})
        except (*WS_ERRORS, ConnectionError, ValueError) as exc:
            LOG.info("Pipeline stream %s ended: %s", stream_id[:8], exc)
        except Exception:
            LOG.exception("Pipeline stream failed")

    async def stop(self) -> None:
        self._stopped.set()
        if self._socket is not None:
            with contextlib.suppress(Exception):
                await self._socket.close()
        for task in list(self.tasks):
            task.cancel()


# --- Caller side ------------------------------------------------------------------------------------------------

@contextlib.contextmanager
def _httpx_errors():
    try:
        yield
    except httpcore.TimeoutException as exc:
        kind = {httpcore.ConnectTimeout: httpx.ConnectTimeout, httpcore.ReadTimeout: httpx.ReadTimeout,
                httpcore.WriteTimeout: httpx.WriteTimeout, httpcore.PoolTimeout: httpx.PoolTimeout}.get(type(exc), httpx.TimeoutException)
        raise kind(str(exc)) from exc
    except httpcore.ConnectError as exc:
        raise httpx.ConnectError(str(exc)) from exc
    except httpcore.ReadError as exc:
        raise httpx.ReadError(str(exc)) from exc
    except httpcore.WriteError as exc:
        raise httpx.WriteError(str(exc)) from exc
    except httpcore.RemoteProtocolError as exc:
        raise httpx.RemoteProtocolError(str(exc)) from exc
    except httpcore.ProtocolError as exc:
        raise httpx.ProtocolError(str(exc)) from exc


class _NetworkStream(httpcore.AsyncNetworkStream):
    def __init__(self, websocket, pin: bytes):
        self.raw = WebSocketStream(websocket)
        self.pin = pin
        self.tls: Optional[pipeline_tls.TLSStream] = None

    async def read(self, max_bytes: int, timeout: Optional[float] = None) -> bytes:
        source = self.tls or self.raw
        try:
            return await asyncio.wait_for(source.recv(max_bytes), timeout)
        except asyncio.TimeoutError as exc:
            raise httpcore.ReadTimeout("The callee did not answer in time.") from exc
        except (ConnectionError, OSError) as exc:
            raise httpcore.ReadError(str(exc)) from exc

    async def write(self, buffer: bytes, timeout: Optional[float] = None) -> None:
        if not buffer:
            return
        target = self.tls or self.raw
        try:
            await asyncio.wait_for(target.send(buffer), timeout)
        except asyncio.TimeoutError as exc:
            raise httpcore.WriteTimeout("The Pipeline stream did not take the request in time.") from exc
        except (ConnectionError, OSError) as exc:
            raise httpcore.WriteError(str(exc)) from exc

    async def aclose(self) -> None:
        await (self.tls or self.raw).aclose()

    async def start_tls(self, ssl_context, server_hostname=None, timeout: Optional[float] = None):
        # The context httpcore offers is ignored: the callee is authenticated by its exact key, not by an authority.
        try:
            self.tls = await pipeline_tls.connect_pinned(self.raw, self.pin, timeout=timeout or pipeline_tls.HANDSHAKE_SECONDS)
        except PermissionError as exc:
            raise httpcore.ConnectError(str(exc)) from exc
        except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
            raise httpcore.ConnectError(f"TLS to the callee failed: {exc}") from exc
        return self

    def get_extra_info(self, info: str):
        if info == "ssl_object":
            return self.tls.ssl if self.tls else None
        if info == "is_readable":
            # httpcore asks before reusing a kept-alive connection: a stream the node or callee closed (a revoked
            # grant, a drained node) is dropped and a new one opened, never written to.
            return self.raw.closed or self.raw.websocket.state is not State.OPEN
        return None


class _Backend(httpcore.AsyncNetworkBackend):
    def __init__(self, node_origin: str, callee_id: str, pass_ticket, pin: bytes, connect):
        self.url = protocol.node_url(node_origin, "/c/" + quote(callee_id, safe=""))
        self.pass_ticket, self.pin, self.connect = pass_ticket, pin, connect

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        websocket = None
        try:
            websocket = await self.connect(self.url, max_size=protocol.MAX_FRAME_BYTES,
                                           open_timeout=timeout or protocol.HELLO_SECONDS, compression=None)
            ticket = await _maybe(self.pass_ticket() if callable(self.pass_ticket) else self.pass_ticket)
            await websocket.send(protocol.message("connect", **{"pass": ticket, "protocol": protocol.PROTOCOL}))
            protocol.read_message(await asyncio.wait_for(websocket.recv(), protocol.JOIN_SECONDS + 5), "ready")
        except ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd else None
            raise httpcore.ConnectError(f"Pipeline refused the call: {protocol.close_reason(code)}.") from exc
        except (*WS_ERRORS, ValueError) as exc:
            if websocket is not None:
                with contextlib.suppress(Exception):
                    await websocket.close()
            raise httpcore.ConnectError(f"Pipeline node unavailable: {exc}") from exc
        return _NetworkStream(websocket, self.pin)

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("Pipeline has no Unix sockets.")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class _ResponseBody(httpx.AsyncByteStream):
    def __init__(self, response: httpcore.Response):
        self.response = response

    async def __aiter__(self):
        with _httpx_errors():
            async for part in self.response.aiter_stream():
                yield part

    async def aclose(self) -> None:
        with _httpx_errors():
            await self.response.aclose()


class PipelineTransport(httpx.AsyncBaseTransport):
    """httpx transport to one callee through its Pipeline node, TLS pinned to the callee's identity key.

    `pass_ticket` is Plaza's pass, or a callable returning the current one. Each new connection uses it to open a
    stream. A request that fails before any byte was sent raises httpx.ConnectError; nothing is ever replayed.
    """

    def __init__(self, *, node_origin: str, callee_id: str, pass_ticket, callee_key: bytes,
                 max_connections: int = 4, connect=node_connect):
        self.pool = httpcore.AsyncConnectionPool(
            ssl_context=pipeline_tls.client_context(), max_connections=max_connections, http1=True, http2=False,
            network_backend=_Backend(node_origin, callee_id, pass_ticket, callee_key, connect))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core = httpcore.Request(method=request.method,
                                url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host,
                                                 port=request.url.port, target=request.url.raw_path),
                                headers=request.headers.raw, content=request.stream, extensions=request.extensions)
        with _httpx_errors():
            response = await self.pool.handle_async_request(core)
        return httpx.Response(status_code=response.status, headers=response.headers,
                              stream=_ResponseBody(response), extensions=response.extensions)

    async def aclose(self) -> None:
        await self.pool.aclose()


def pipeline_client(*, endpoint: Mapping, grant: dict, pass_ticket, caller_key, connect=node_connect,
                    timeout: float = 30.0, max_connections: int = 4) -> httpx.AsyncClient:
    """An httpx client for one callee reached through Pipeline, signing every request under `grant`.

    `endpoint` is the callee's card endpoint (`{kind: "pipeline", node, url, key}`). The TLS pin comes from the grant
    Plaza signed, never from the card, and the two must agree.
    """
    claims = service_tickets.peek(grant)
    pin = service_tickets.raw_public_key(claims["calleeKey"])
    if endpoint.get("kind") != "pipeline" or claims.get("nodeId") != endpoint.get("node"):
        raise ValueError("The grant is not for this Pipeline endpoint.")
    if endpoint.get("key") and service_tickets.raw_public_key(endpoint["key"]) != pin:
        raise PermissionError("The card's key is not the one Plaza named in the grant.")
    transport = PipelineTransport(node_origin=endpoint["url"], callee_id=claims["calleeId"], pass_ticket=pass_ticket,
                                  callee_key=pin, max_connections=max_connections, connect=connect)
    return httpx.AsyncClient(base_url=f"https://{HOST}", transport=transport,
                             auth=connection_grants.GrantAuth(grant, caller_key), timeout=timeout)
