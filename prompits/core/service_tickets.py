"""Plaza-signed tickets that a service checks without asking Plaza.

Plaza signs a small set of claims with its Ed25519 key. A service checks the signature with Plaza's published public
key, cached by key id, so it learns who is asking without one Plaza call per request and never takes the asker's own
word for it. Each ticket kind has its own schema, its own exact claim names and its own longest life.

Kinds so far: Pipeline attach tickets and passes (`prompits.core.pipeline_protocol`) and connection grants
(`prompits.core.connection_grants`). Observer tickets (`prompits.core.observer_tickets`) predate this module and keep
their own code and schema.

A ticket travels as `{claims, signature}`; `encode`/`decode` turn it into one header-safe string.
"""
from __future__ import annotations

import base64
import json
import math
import time
from typing import Iterable, Mapping

import hashlib
import re

from .capabilities import canonical

# The same key ids and raw keys as native_authority.py (a test keeps them equal). Defined here so a Terminal that calls
# through Pipeline ships these few lines, not Plaza's native-operation authority.
KEY_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def public_key_bytes(private_key) -> bytes:
    from cryptography.hazmat.primitives import serialization
    return private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id_for(public_key: bytes) -> str:
    return "ed25519:" + hashlib.sha256(public_key).hexdigest()[:16]

CLOCK_SKEW_SECONDS = 5
MAX_ID_LENGTH = 200
MAX_ENCODED_BYTES = 16 * 1024
TIMES = ("issuedAt", "expiresAt")


class UnknownTicketKey(PermissionError):
    """The ticket is signed with a key the checker does not hold; `key_id` names it, so it can fetch Plaza's keys."""

    def __init__(self, key_id: str):
        super().__init__("The ticket is signed with an unknown Plaza key.")
        self.key_id = key_id


def identity(value) -> bool:
    """An agent, node or grant id: a short printable string."""
    return isinstance(value, str) and 1 <= len(value) <= MAX_ID_LENGTH and value.isprintable()


def sign(private_key, claims: dict) -> dict:
    return {"claims": claims, "signature": base64.b64encode(private_key.sign(canonical(claims).encode())).decode()}


def issue(private_key, schema: str, fields: dict, *, seconds: float, max_seconds: int, clock=time.time) -> dict:
    """Plaza's ticket of kind `schema` with `fields`, good for `seconds` (at most `max_seconds`)."""
    if not 1 <= seconds <= max_seconds:
        raise ValueError(f"A {schema} ticket lives between 1 and {max_seconds} seconds.")
    reserved = {"schema", "keyId", *TIMES} & set(fields)
    if reserved:
        raise ValueError(f"Ticket fields may not set {sorted(reserved)}.")
    # Whole seconds: tickets pass through other agents unchanged and read back the same in any language.
    now = int(clock())
    claims = {"schema": schema, **fields, "keyId": key_id_for(public_key_bytes(private_key)),
              "issuedAt": now, "expiresAt": now + int(seconds)}
    return sign(private_key, claims)


def verify(ticket, *, schema: str, fields: Iterable[str], keys: Mapping[str, bytes], max_seconds: int,
           clock=time.time) -> dict:
    """The ticket's claims once Plaza signed it, it is of kind `schema` with exactly `fields`, and it is current.

    Raises PermissionError otherwise, and UnknownTicketKey (a PermissionError) for a well-formed ticket under a key not
    in `keys`, so the caller can fetch Plaza's current keys and try once more.
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if not isinstance(ticket, dict) or set(ticket) != {"claims", "signature"} or not isinstance(ticket["signature"], str):
        raise PermissionError(f"A signed {schema} ticket is required.")
    c = ticket["claims"]
    expected = {"schema", "keyId", *TIMES, *fields}
    now = clock()
    if (not math.isfinite(now) or not isinstance(c, dict) or set(c) != expected or c["schema"] != schema
            or not isinstance(c["keyId"], str) or not KEY_ID.fullmatch(c["keyId"])
            or any(type(c[name]) not in (int, float) or not math.isfinite(c[name]) for name in TIMES)
            or not c["issuedAt"] < c["expiresAt"] <= c["issuedAt"] + max_seconds):
        raise PermissionError(f"The {schema} ticket is malformed.")
    if c["issuedAt"] > now + CLOCK_SKEW_SECONDS:
        raise PermissionError(f"The {schema} ticket is not valid yet.")
    if c["expiresAt"] <= now:
        raise PermissionError(f"The {schema} ticket has expired.")
    public = keys.get(c["keyId"])
    if public is None:
        raise UnknownTicketKey(c["keyId"])
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(
            base64.b64decode(ticket["signature"], validate=True), canonical(c).encode())
    except (InvalidSignature, ValueError, TypeError):
        raise PermissionError(f"The {schema} ticket signature is invalid.") from None
    return dict(c)


def peek(ticket) -> dict:
    """A ticket's claims without checking them: for its holder, who got it from Plaza over its own connection."""
    if not isinstance(ticket, dict) or not isinstance(ticket.get("claims"), dict):
        raise ValueError("Not a ticket.")
    return dict(ticket["claims"])


def encode(ticket: dict) -> str:
    """One header-safe string for a ticket."""
    return base64.urlsafe_b64encode(canonical(ticket).encode()).decode().rstrip("=")


def decode(value) -> dict:
    if not isinstance(value, str) or not value or len(value) > MAX_ENCODED_BYTES:
        raise PermissionError("A ticket is required.")
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    except (ValueError, TypeError):
        raise PermissionError("The ticket is not readable.") from None
    if not isinstance(data, dict):
        raise PermissionError("The ticket is not readable.")
    return data


def public_key_record(private_key) -> dict:
    """What Plaza publishes so services can check its tickets: `{keyId, publicKey}`."""
    public = public_key_bytes(private_key)
    return {"keyId": key_id_for(public), "publicKey": base64.b64encode(public).decode()}


def read_public_key(record) -> tuple:
    """`(keyId, public key bytes)` from Plaza's published record; raises ValueError unless the two agree."""
    if not isinstance(record, dict) or set(record) != {"keyId", "publicKey"}:
        raise ValueError("Plaza's key record must be {keyId, publicKey}.")
    try:
        public = base64.b64decode(record["publicKey"], validate=True)
    except (TypeError, ValueError):
        public = b""
    if len(public) != 32 or record["keyId"] != key_id_for(public):
        raise ValueError("Plaza's key does not match its key id.")
    return record["keyId"], public


def raw_public_key(value) -> bytes:
    """A 32-byte Ed25519 public key from its base64 text; raises PermissionError otherwise."""
    try:
        public = base64.b64decode(value, validate=True) if isinstance(value, str) else b""
    except (TypeError, ValueError):
        public = b""
    if len(public) != 32:
        raise PermissionError("An Ed25519 public key is required.")
    return public


def key_text(public: bytes) -> str:
    return base64.b64encode(public).decode()
