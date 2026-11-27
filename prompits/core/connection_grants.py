"""Connection grants: Plaza lets one caller call one callee for a few minutes, with no Plaza call per call.

Plaza decides exactly as it does for a call grant (`prompits.core.call_grants`): same owner, an agent the owner
approved, or a published practice. Instead of one stored single-use token per call, it signs one grant for a short
window with its Ed25519 key. The grant names the caller and its key, the callee and its key, the operations allowed,
the user the calls act for and why Plaza allowed them.

Each call carries the grant and an envelope the caller signs with its own key: the grant id, the exact request
binding (method, path, query and body, as call grants bind them), a nonce and the time. The callee checks both
itself: Plaza's signature, that it is the callee, the caller's signature, the binding, the operation, the clock and
that the nonce is new. It needs no Plaza call. Revocation reaches it in Plaza's feed (`RevocationFeed`), carried by
heartbeat answers, so it lags by at most one heartbeat; a callee that has not heard from Plaza recently refuses
everything.

Paid operations, operation grants with an authority and onward delegation chains keep single-use call grants.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import math
import secrets
import time
from typing import Callable, Dict, Iterable, Mapping, Optional

import httpx

from . import pipeline_protocol, service_tickets
from .call_grants import CURRENT, binding, request_operation
from .capabilities import canonical

LOG = logging.getLogger(__name__)
GRANT_SCHEMA = "prompits.connection-grant/1"
ENVELOPE_SCHEMA = "prompits.call-envelope/1"
GRANT_FIELDS = ("grantId", "callerId", "callerKey", "calleeId", "calleeKey", "nodeId", "operations", "basis", "user", "epoch")
ENVELOPE_FIELDS = {"schema", "grantId", "binding", "nonce", "ts"}
GRANT_SECONDS = 300
ENVELOPE_SKEW_SECONDS = 30
FEED_STALE_SECONDS = 60
MAX_OPERATIONS = 128
MAX_NONCES = 100_000
MAX_BODY_BYTES = 16 * 1024 * 1024
HEADER_GRANT = "X-Prompits-Grant"
HEADER_ENVELOPE = "X-Prompits-Envelope"
ANY_OPERATION = "*"
EXTENSION = "prompits.connection_grant"


def _operations(value) -> list:
    if (not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_OPERATIONS
            or any(not isinstance(op, str) or not op or len(op) > 200 for op in value)):
        raise ValueError("A grant names 1-128 operations.")
    return list(dict.fromkeys(value))


def issue(private_key, *, caller_id: str, caller_key: bytes, callee_id: str, callee_key: bytes, operations,
          basis: str, user: Optional[dict] = None, epoch: int = 0, node_id: Optional[str] = None,
          seconds: float = GRANT_SECONDS, clock=time.time) -> dict:
    """Plaza's grant, and a Pipeline pass when the callee is reached through node `node_id`: `{grant, pass?}`."""
    if not all(service_tickets.identity(value) for value in (caller_id, callee_id, basis)):
        raise ValueError("A grant names one caller, one callee and the reason Plaza allowed it.")
    if len(caller_key) != 32 or len(callee_key) != 32:
        raise ValueError("Caller and callee keys are Ed25519 public keys.")
    if user is not None and (not isinstance(user, dict) or not service_tickets.identity(str(user.get("id") or ""))):
        raise ValueError("A grant's user is an account with an id.")
    if type(epoch) is not int or epoch < 0:
        raise ValueError("A grant carries Plaza's revocation epoch.")
    grant_id = secrets.token_hex(16)
    fields = {"grantId": grant_id, "callerId": caller_id, "callerKey": service_tickets.key_text(caller_key),
              "calleeId": callee_id, "calleeKey": service_tickets.key_text(callee_key), "nodeId": node_id or "",
              "operations": _operations(operations), "basis": basis, "user": user, "epoch": epoch}
    result = {"grant": service_tickets.issue(private_key, GRANT_SCHEMA, fields, seconds=seconds,
                                             max_seconds=GRANT_SECONDS, clock=clock)}
    if node_id:
        result["pass"] = pipeline_protocol.issue_pass(private_key, grant_id=grant_id, callee_id=callee_id,
                                                      node_id=node_id, seconds=seconds, clock=clock)
    return result


def request_binding(method: str, path: str, query: str, body: bytes) -> str:
    """The hash a call envelope binds: call grants' binding over the parsed JSON body, or over the body's digest."""
    parsed = None
    if body:
        try:
            parsed = json.loads(body)
            return binding(method, path, parsed, query)
        except (ValueError, UnicodeDecodeError):
            parsed = {"sha256": hashlib.sha256(body).hexdigest()}
    return binding(method, path, parsed, query)


def _operation(path: str, body: bytes) -> str:
    try:
        parsed = json.loads(body) if body else None
    except (ValueError, UnicodeDecodeError):
        parsed = None
    return request_operation(path, parsed)


def sign_envelope(private_key, grant_id: str, *, method: str, path: str, query: str = "", body: bytes = b"",
                  clock=time.time) -> dict:
    """The caller's signed envelope for one request under grant `grant_id`."""
    claims = {"schema": ENVELOPE_SCHEMA, "grantId": grant_id, "binding": request_binding(method, path, query, body),
              "nonce": secrets.token_urlsafe(18), "ts": int(clock())}
    return service_tickets.sign(private_key, claims)


class RevocationFeed:
    """Plaza's revocations as this agent or node last heard them, from heartbeat answers.

    A feed update is `{epoch, grants?: [grantId], agents?: {agentId: revokedAt}, notBefore?}`:
    - `grants`: grants revoked outright;
    - `agents`: every grant naming that agent, as caller or callee, issued at or before `revokedAt`, is void (an agent
      blocked, deregistered, re-keyed, or its owner changed);
    - `notBefore`: every grant issued before this time is void (Plaza's restart or key change).
    """

    KEEP_GRANT_SECONDS = GRANT_SECONDS + 60

    def __init__(self, *, clock=time.time, stale_after: float = FEED_STALE_SECONDS):
        self.clock, self.stale_after = clock, stale_after
        self.epoch = 0
        self.grants: Dict[str, float] = {}
        self.agents: Dict[str, float] = {}
        self.not_before = 0.0
        self.heard_at: Optional[float] = None
        self.listeners: list = []

    def heard(self) -> None:
        """Plaza answered with nothing new."""
        self.heard_at = self.clock()

    def apply(self, feed: Mapping) -> bool:
        """Apply Plaza's update; returns False (and changes nothing) for an older epoch or a malformed update."""
        epoch = feed.get("epoch") if isinstance(feed, Mapping) else None
        if type(epoch) is not int or epoch < self.epoch:
            return False
        grants, agents = feed.get("grants") or [], feed.get("agents") or {}
        not_before = feed.get("notBefore", 0)
        if (not isinstance(grants, list) or not isinstance(agents, Mapping) or type(not_before) not in (int, float)
                or any(not service_tickets.identity(g) for g in grants)
                or any(not service_tickets.identity(a) or type(t) not in (int, float) or not math.isfinite(t)
                       for a, t in agents.items())):
            return False
        now = self.clock()
        self.epoch = epoch
        for grant in grants:
            self.grants[grant] = now + self.KEEP_GRANT_SECONDS
        for agent, at in agents.items():
            self.agents[agent] = max(float(at), self.agents.get(agent, 0.0))
        self.not_before = max(self.not_before, float(not_before))
        self.grants = {g: until for g, until in self.grants.items() if until > now}
        self.heard_at = now
        for listener in list(self.listeners):
            try:
                listener(self)
            except Exception:  # a listener's failure never stops revocation reaching the others
                LOG.exception("Revocation listener failed")
        return True

    def fresh(self) -> bool:
        return self.heard_at is not None and self.clock() - self.heard_at <= self.stale_after

    def revoked(self, *, grant_id: str, issued_at: float, agents: Iterable[str] = ()) -> Optional[str]:
        """Why a grant issued at `issued_at` naming `agents` is void, or None while it stands."""
        if grant_id in self.grants:
            return "grant revoked"
        if issued_at < self.not_before:
            return "issued before Plaza's last reset"
        for agent in agents:
            at = self.agents.get(agent)
            if at is not None and issued_at <= at:
                return "agent revoked"
        return None


class GrantVerifier:
    """A callee's check of each call made under a connection grant: no Plaza call per call."""

    def __init__(self, agent_id: str, keys: Callable[[], Mapping[str, bytes]] | Mapping[str, bytes],
                 feed: RevocationFeed, *, clock=time.time, max_nonces: int = MAX_NONCES):
        self.agent_id, self.feed, self.clock, self.max_nonces = agent_id, feed, clock, max_nonces
        self._keys = keys
        self.nonces: Dict[tuple, float] = {}

    def keys(self) -> Mapping[str, bytes]:
        return self._keys() if callable(self._keys) else self._keys

    def verify(self, grant, envelope, *, method: str, path: str, query: str = "", body: bytes = b"") -> dict:
        """The grant's claims when this call may run; raises PermissionError with the reason otherwise."""
        if not self.feed.fresh():
            raise PermissionError("No recent word from Plaza; direct calls are refused until it answers again.")
        claims = service_tickets.verify(grant, schema=GRANT_SCHEMA, fields=GRANT_FIELDS, keys=self.keys(),
                                        max_seconds=GRANT_SECONDS, clock=self.clock)
        if claims["calleeId"] != self.agent_id:
            raise PermissionError("The grant is for another callee.")
        reason = self.feed.revoked(grant_id=claims["grantId"], issued_at=claims["issuedAt"],
                                   agents=(claims["callerId"], claims["calleeId"]))
        if reason:
            raise PermissionError(f"The grant is void: {reason}.")
        operations = _operations(claims["operations"])
        envelope_claims = self._envelope(envelope, claims)
        if envelope_claims["binding"] != request_binding(method, path, query, body):
            raise PermissionError("The envelope binds another request.")
        operation = _operation(path, body)
        if ANY_OPERATION not in operations and operation not in operations:
            raise PermissionError("The grant does not cover this operation.")
        self._new_nonce(claims, envelope_claims["nonce"])
        return {**claims, "operation": operation}

    def _envelope(self, envelope, claims) -> dict:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        if not isinstance(envelope, dict) or set(envelope) != {"claims", "signature"}:
            raise PermissionError("A signed call envelope is required.")
        e = envelope["claims"]
        if (not isinstance(e, dict) or set(e) != ENVELOPE_FIELDS or e["schema"] != ENVELOPE_SCHEMA
                or e["grantId"] != claims["grantId"] or not isinstance(e["binding"], str) or len(e["binding"]) != 64
                or not isinstance(e["nonce"], str) or not 16 <= len(e["nonce"]) <= 64
                or type(e["ts"]) is not int):
            raise PermissionError("The call envelope is malformed.")
        if abs(self.clock() - e["ts"]) > ENVELOPE_SKEW_SECONDS:
            raise PermissionError("The call envelope is too old or from the future.")
        caller_key = service_tickets.raw_public_key(claims["callerKey"])
        try:
            signature = base64.b64decode(envelope["signature"], validate=True)
            Ed25519PublicKey.from_public_bytes(caller_key).verify(
                signature, canonical(e).encode())
        except (InvalidSignature, ValueError, TypeError):
            raise PermissionError("The call envelope is not signed by the grant's caller.") from None
        return e

    def _new_nonce(self, claims, nonce) -> None:
        now = self.clock()
        if len(self.nonces) >= self.max_nonces:
            self.nonces = {key: until for key, until in self.nonces.items() if until > now}
            if len(self.nonces) >= self.max_nonces:
                raise PermissionError("Too many calls in flight under current grants.")
        key = (claims["grantId"], nonce)
        if key in self.nonces:
            raise PermissionError("The call envelope was already used.")
        # Kept until the envelope's clock window and the grant have both passed.
        self.nonces[key] = max(float(claims["expiresAt"]), now + ENVELOPE_SKEW_SECONDS)


def _header(scope, name: str) -> str:
    wanted = name.lower().encode()
    for key, value in scope.get("headers") or ():
        if key.lower() == wanted:
            return value.decode("latin-1")
    return ""


def current_call(claims: dict, *, plaza_url: str = "", method: str = "", path: str = "", query: str = "") -> dict:
    """The verified call as `call_grants.CURRENT` carries it, so `verified_context()` and the agent's caller check
    accept it. `kind` marks a connection grant: it has no Plaza-stored token, so it can't be a parent for onward
    calls (`peer_transport` refuses those until onward delegation through Pipeline exists)."""
    return {"kind": "connection-grant", "id": claims["grantId"], "root": claims["grantId"], "token": None,
            "actor": claims["callerId"], "actorName": "", "audience": claims["calleeId"], "user": claims.get("user"),
            "delegates": [], "depth": 0, "operation": claims.get("operation"), "basis": claims.get("basis"),
            "plaza": plaza_url, "transport": {"method": method, "path": path, "query": query, "via": "pipeline"}}


def guard(app, verifier: GrantVerifier, *, max_body: int = MAX_BODY_BYTES, plaza_url: str = ""):
    """ASGI middleware: every HTTP request must carry a connection grant and envelope that `verifier` accepts.

    The accepted grant's claims are in `scope["extensions"][EXTENSION]`, and the call is the current verified call
    (`call_grants.CURRENT`) while `app` handles it. Anything else gets 403 and never reaches `app`.
    """
    async def deny(send, status: int, detail: str):
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})

    async def guarded(scope, receive, send):
        if scope["type"] != "http":
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            return await app(scope, receive, send)
        chunks, size = [], 0
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            chunk = event.get("body") or b""
            size += len(chunk)
            if size > max_body:
                return await deny(send, 413, "The request is too large.")
            chunks.append(chunk)
            if not event.get("more_body"):
                break
        body = b"".join(chunks)
        try:
            claims = verifier.verify(service_tickets.decode(_header(scope, HEADER_GRANT)),
                                     service_tickets.decode(_header(scope, HEADER_ENVELOPE)),
                                     method=scope["method"], path=scope["path"],
                                     query=(scope.get("query_string") or b"").decode("latin-1"), body=body)
        except PermissionError as exc:
            LOG.warning("Connection grant rejected for %s: %s", scope.get("path", "")[:120], str(exc)[:200])
            return await deny(send, 403, "Call grant rejected.")
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        scope = {**scope, "extensions": {**(scope.get("extensions") or {}), EXTENSION: claims}}
        mark = CURRENT.set(current_call(claims, plaza_url=plaza_url, method=scope["method"], path=scope["path"],
                                        query=(scope.get("query_string") or b"").decode("latin-1")))
        try:
            await app(scope, replay, send)
        finally:
            CURRENT.reset(mark)

    return guarded


class GrantAuth(httpx.Auth):
    """httpx auth for a caller: adds the grant and a freshly signed envelope to every request."""

    requires_request_body = True

    def __init__(self, grant: dict, caller_key, *, clock=time.time):
        self.grant_id = service_tickets.peek(grant)["grantId"]
        self.encoded, self.caller_key, self.clock = service_tickets.encode(grant), caller_key, clock

    def auth_flow(self, request: httpx.Request):
        envelope = sign_envelope(self.caller_key, self.grant_id, method=request.method, path=request.url.path,
                                 query=request.url.query.decode("latin-1"), body=request.content, clock=self.clock)
        request.headers[HEADER_GRANT] = self.encoded
        request.headers[HEADER_ENVELOPE] = service_tickets.encode(envelope)
        yield request
