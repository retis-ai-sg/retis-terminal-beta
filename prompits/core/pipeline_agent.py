"""An agent's use of Pipeline: its identity key, Plaza's offer, and its attachment while it is outbound-only.

An agent opts in with `use_pipeline(agent)`; BaseAgent itself imports none of this, so programs that never use
Pipeline (local components) ship none of it. An opted-in agent that takes no inbound connections registers an Ed25519
identity key in its card (`meta.identity_key`). The key is made when the process starts and is never stored: a restarted agent registers a new
one, and grants naming the old key stop working at the TLS pin. Callers' keys are made the same way, one per process
(`caller_identity`).

When Plaza's heartbeat answer offers Pipeline nodes, with an attach ticket for each (`pipeline_plaza.py`), the agent
attaches to one on its own serving event loop and serves relayed calls to its own app. Whenever its node changes, it
registers again so its card names the node callers dial (`meta.endpoints`).

Set `PROMPITS_PIPELINE=off` to keep an agent out of Pipeline altogether.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Dict, Optional

from . import service_tickets
from .connection_grants import GrantVerifier, RevocationFeed
from .service_tickets import key_id_for, public_key_bytes

LOG = logging.getLogger(__name__)
OFFER_SCHEMA = "prompits.pipeline-offer/1"
_CALLER_KEY = None
_CALLER_LOCK = threading.Lock()


def enabled() -> bool:
    return str(os.environ.get("PROMPITS_PIPELINE") or "").strip().lower() not in ("off", "0", "false", "no")


def _new_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    return Ed25519PrivateKey.generate()


def caller_identity():
    """This process's caller key for connection grants: made once, kept in memory only."""
    global _CALLER_KEY
    with _CALLER_LOCK:
        if _CALLER_KEY is None:
            _CALLER_KEY = _new_key()
        return _CALLER_KEY


def key_record(private_key) -> dict:
    public = public_key_bytes(private_key)
    return {"keyId": key_id_for(public), "publicKey": service_tickets.key_text(public)}


def use_pipeline(agent) -> Optional["AgentPipeline"]:
    """Let `agent` be called through Pipeline while it takes no inbound connections; None when PROMPITS_PIPELINE=off.

    Adds BaseAgent hooks: its card carries the identity key and endpoint, and its heartbeat answers bring Plaza's offer.
    """
    if not enabled():
        return None
    helper = getattr(agent, "_pipeline_helper", None)
    if helper is None:
        helper = agent._pipeline_helper = AgentPipeline(agent)
        agent.card_meta_hooks = [*(getattr(agent, "card_meta_hooks", None) or ()), helper.sync_card]
        agent.heartbeat_answer_hooks = [*(getattr(agent, "heartbeat_answer_hooks", None) or ()),
                                        lambda answer: helper.apply(answer.get("pipeline"))]
        agent._sync_connectivity_metadata()
        if getattr(agent, "plaza_token", None):
            # Already registered (some agents register as they are built): register again so Plaza has the key.
            threading.Thread(target=agent.refresh_registration, daemon=True,
                             name=f"{getattr(agent, 'name', 'agent')}-pipeline-register").start()
    return helper


class AgentPipeline:
    def __init__(self, agent):
        self.agent = agent
        self.identity = _new_key()
        self.feed = RevocationFeed()
        self.keys: Dict[str, bytes] = {}
        self.offer: dict = {}
        self.endpoint: Optional[dict] = None
        self.attachment = None
        self.running = None
        self.lock = threading.Lock()

    def card_meta(self) -> dict:
        """What the card registers: the identity key, and the Pipeline endpoint while attached."""
        return {"identity_key": key_record(self.identity), "endpoints": [dict(self.endpoint)] if self.endpoint else []}

    def sync_card(self, meta: dict, accepts_inbound: bool) -> None:
        """BaseAgent's card hook: only an agent that takes no inbound connections registers these."""
        others = [e for e in meta.get("endpoints") or [] if not (isinstance(e, dict) and e.get("kind") == "pipeline")]
        if accepts_inbound:
            meta.pop("identity_key", None)
            if others:
                meta["endpoints"] = others
            else:
                meta.pop("endpoints", None)
            return
        current = self.card_meta()
        meta["identity_key"] = current["identity_key"]
        meta["endpoints"] = others + current["endpoints"]

    def apply(self, offer) -> None:
        """Take Plaza's offer from a heartbeat answer: keys, revocations, and for an outbound-only agent, nodes."""
        if not isinstance(offer, dict) or offer.get("schema") != OFFER_SCHEMA:
            return
        keys = {}
        for record in offer.get("keys") or ():
            try:
                key_id, public = service_tickets.read_public_key(record)
            except ValueError:
                continue
            keys[key_id] = public
        if keys:
            self.keys = keys
        if not self.feed.apply(offer.get("revocations") or {}):
            self.feed.heard()
        self.offer = offer
        if offer.get("role") == "agent":
            self.ensure_attached()

    def ensure_attached(self) -> bool:
        """Start the attachment on the agent's serving loop once Plaza offers a node; True when it runs."""
        from .pipeline_client import PipelineAttachment
        loop = getattr(self.agent, "_serving_loop", None)
        agent_id = str(getattr(self.agent, "agent_id", "") or "")
        if loop is None or loop.is_closed() or not agent_id or not self.offer.get("nodes"):
            return False
        with self.lock:
            if self.running is not None and not self.running.done():
                return True
            self.attachment = PipelineAttachment(
                agent_id=agent_id, app=self.agent.app, identity_key=self.identity,
                verifier=GrantVerifier(agent_id, lambda: self.keys, self.feed),
                nodes=lambda: list(self.offer.get("nodes") or ()), ticket_for=self._ticket,
                on_endpoint=self._endpoint_changed, plaza_url=str(getattr(self.agent, "plaza_url", "") or ""))
            self.running = asyncio.run_coroutine_threadsafe(self.attachment.run(), loop)
        return True

    def _ticket(self, node_id: str) -> dict:
        ticket = (self.offer.get("tickets") or {}).get(node_id)
        if not isinstance(ticket, dict):
            raise PermissionError("Plaza gave no attach ticket for that node.")
        return ticket

    def _endpoint_changed(self, endpoint: Optional[dict]) -> None:
        if endpoint == self.endpoint:
            return
        self.endpoint = endpoint
        # The card must name the node callers dial. Registering is blocking HTTP; the attachment runs on the loop.
        threading.Thread(target=self.agent.refresh_registration, daemon=True,
                         name=f"{getattr(self.agent, 'name', 'agent')}-pipeline-endpoint").start()

    def stop(self) -> None:
        loop = getattr(self.agent, "_serving_loop", None)
        if self.attachment is not None and loop is not None and not loop.is_closed():
            asyncio.run_coroutine_threadsafe(self.attachment.stop(), loop)
