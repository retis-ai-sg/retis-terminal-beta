"""Pipeline's wire protocol (`pipeline/1`): what agents, callers and Pipeline nodes say to each other.

Pipeline carries calls to agents that cannot take inbound connections. Plaza authenticates and lists; Pipeline only
carries bytes, and the receiving agent decides every call itself.

Connections (all WebSocket, so they pass home NAT, CGNAT, mobile carriers and most proxies on 443):

- `/attach`: the agent's control channel, opened outbound by the agent. First message `hello` with Plaza's attach
  ticket for this agent and this node; the node answers `attached`. The node later sends `open` (a caller is waiting
  on stream *s*) and `drain` (move to another node); the agent sends `refresh` with a newer ticket before the current
  one expires.
- `/c/<callee>`: a caller. First message `connect` with Plaza's pass for this callee and this node; the node answers
  `ready` once the callee has joined, and from then on carries binary frames both ways, unread.
- `/s/<stream>`: the callee joining stream *s*. Knowing *s* is the proof: the node sent it only over the callee's own
  attached control channel. Binary frames both ways from the start.

Inside a stream the caller runs TLS to the callee itself (`prompits.core.pipeline_tls`), so a node sees who connects
to whom, when and how many bytes, never what they say.

Plaza signs two ticket kinds here (`prompits.core.service_tickets`): attach tickets (one agent, one node, at most ten
minutes) and passes (one connection grant's callee at one node, no user and no operation, so a node learns no more
than it needs).
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Iterable, List, Mapping, Optional
from urllib.parse import urlsplit

from . import service_tickets

PROTOCOL = "pipeline/1"
ATTACH_SCHEMA = "prompits.pipeline-attach/1"
PASS_SCHEMA = "prompits.pipeline-pass/1"
ATTACH_FIELDS = ("agentId", "nodeId")
PASS_FIELDS = ("grantId", "calleeId", "nodeId")
ATTACH_SECONDS = 600
PASS_SECONDS = 300

# Sizes and times. A node refuses anything larger or slower.
MAX_CONTROL_BYTES = 16 * 1024
MAX_FRAME_BYTES = 1024 * 1024
HELLO_SECONDS = 10.0
JOIN_SECONDS = 10.0
REFRESH_MARGIN_SECONDS = 120.0

# WebSocket close codes a node uses (application range 4000-4999).
CLOSE_MALFORMED = 4400
CLOSE_TICKET = 4401
CLOSE_PASS = 4403
CLOSE_ABSENT = 4404
CLOSE_TIMEOUT = 4408
CLOSE_REPLACED = 4409
CLOSE_REVOKED = 4410
CLOSE_LIMIT = 4429
CLOSE_DRAINING = 4503
CLOSE_REASONS = {
    CLOSE_MALFORMED: "malformed", CLOSE_TICKET: "ticket rejected", CLOSE_PASS: "pass rejected",
    CLOSE_ABSENT: "not attached here", CLOSE_TIMEOUT: "timed out", CLOSE_REPLACED: "attached again",
    CLOSE_REVOKED: "revoked", CLOSE_LIMIT: "limit reached", CLOSE_DRAINING: "node draining",
}


def issue_attach_ticket(private_key, *, agent_id: str, node_id: str, seconds: float = ATTACH_SECONDS, clock=time.time) -> dict:
    """Plaza's ticket: `agent_id` may attach to `node_id` until it expires."""
    if not service_tickets.identity(agent_id) or not service_tickets.identity(node_id):
        raise ValueError("An attach ticket names one agent and one node.")
    return service_tickets.issue(private_key, ATTACH_SCHEMA, {"agentId": agent_id, "nodeId": node_id},
                                 seconds=seconds, max_seconds=ATTACH_SECONDS, clock=clock)


def verify_attach_ticket(ticket, *, node_id: str, keys: Mapping[str, bytes], clock=time.time) -> dict:
    claims = service_tickets.verify(ticket, schema=ATTACH_SCHEMA, fields=ATTACH_FIELDS, keys=keys,
                                    max_seconds=ATTACH_SECONDS, clock=clock)
    if not service_tickets.identity(claims["agentId"]) or claims["nodeId"] != node_id:
        raise PermissionError("The attach ticket is for another node.")
    return claims


def issue_pass(private_key, *, grant_id: str, callee_id: str, node_id: str, seconds: float = PASS_SECONDS,
               clock=time.time) -> dict:
    """Plaza's pass: a caller holding connection grant `grant_id` may reach `callee_id` at `node_id`."""
    if not all(service_tickets.identity(value) for value in (grant_id, callee_id, node_id)):
        raise ValueError("A pass names one grant, one callee and one node.")
    return service_tickets.issue(private_key, PASS_SCHEMA, {"grantId": grant_id, "calleeId": callee_id, "nodeId": node_id},
                                 seconds=seconds, max_seconds=PASS_SECONDS, clock=clock)


def verify_pass(ticket, *, node_id: str, callee_id: str, keys: Mapping[str, bytes], clock=time.time) -> dict:
    claims = service_tickets.verify(ticket, schema=PASS_SCHEMA, fields=PASS_FIELDS, keys=keys,
                                    max_seconds=PASS_SECONDS, clock=clock)
    if claims["nodeId"] != node_id or claims["calleeId"] != callee_id or not service_tickets.identity(claims["grantId"]):
        raise PermissionError("The pass is for another callee or node.")
    return claims


def message(kind: str, **fields) -> str:
    return json.dumps({"type": kind, **fields}, separators=(",", ":"))


def read_message(raw, *expected: str) -> dict:
    """A control message of one of the `expected` types; raises ValueError for anything else."""
    if isinstance(raw, (bytes, bytearray)) or not isinstance(raw, str) or len(raw) > MAX_CONTROL_BYTES:
        raise ValueError("Control messages are short JSON text.")
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("type") not in expected:
        raise ValueError(f"Expected {', '.join(expected)}.")
    return value


def node_url(origin: str, path: str) -> str:
    """The WebSocket URL for `path` on a node published at `origin` (https or http)."""
    parts = urlsplit(origin.rstrip("/"))
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.query or parts.fragment or parts.username:
        raise ValueError("A Pipeline node is published at an http(s) origin.")
    scheme = "wss" if parts.scheme == "https" else "ws"
    return f"{scheme}://{parts.netloc}{parts.path.rstrip('/')}{path}"


def choose_nodes(agent_id: str, nodes: Iterable[Mapping], *, region: str = "", exclude: Iterable[str] = ()) -> List[dict]:
    """The nodes an agent should try, best first: weighted rendezvous hashing over live, non-draining nodes.

    Each agent lands on the same node while the list stays the same, and adding a node moves only its share of agents.
    Nodes in the agent's own region come first. A node is `{id, url, weight?, region?, draining?}`.
    """
    excluded = set(exclude)
    scored = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        if not node_id or node_id in excluded or node.get("draining") or not node.get("url"):
            continue
        weight = float(node.get("weight") or 1.0)
        if not math.isfinite(weight) or weight <= 0:
            continue
        digest = hashlib.sha256(f"{agent_id}\n{node_id}".encode()).digest()
        uniform = (int.from_bytes(digest[:8], "big") + 1) / (2 ** 64 + 2)
        score = weight / -math.log(uniform)
        local = bool(region) and node.get("region") == region
        scored.append((not local, -score, node_id, dict(node)))
    return [row[3] for row in sorted(scored)]


def close_reason(code: Optional[int]) -> str:
    return CLOSE_REASONS.get(code or 0, "closed")
