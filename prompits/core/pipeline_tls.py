"""TLS from a caller straight to a callee, over any byte stream (a Pipeline stream, for one).

A Pipeline node joins two WebSocket connections and passes their frames on unread. The caller and the callee run TLS
1.3 inside them, so the node can't read or change what they say.

The callee's certificate is self-signed with its Ed25519 identity key, the key its card advertises and Plaza copies
into each connection grant. The caller doesn't use certificate authorities. It accepts the handshake only when the
callee's public key is exactly the one the grant names. TLS 1.3's CertificateVerify proves the callee holds that
key's private half, and OpenSSL checks it whatever the verify mode.

A byte stream is any object with `async recv() -> bytes` (b"" at the end), `async send(bytes)` and `async aclose()`.
"""
from __future__ import annotations

import asyncio
import datetime
import hmac
import os
import secrets
import shutil
import ssl
import tempfile

HANDSHAKE_SECONDS = 10.0
READ_BYTES = 64 * 1024
ALPN = ["http/1.1"]


def identity_certificate(private_key, common_name: str, *, days: int = 30) -> tuple:
    """`(certificate PEM, key PEM)`: a certificate self-signed with the agent's Ed25519 identity key."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.x509.oid import NameOID
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, (common_name or "prompits-agent")[:64])])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                   .public_key(private_key.public_key()).serial_number(int.from_bytes(secrets.token_bytes(16), "big") >> 1)
                   .not_valid_before(now - datetime.timedelta(hours=1)).not_valid_after(now + datetime.timedelta(days=days))
                   .sign(private_key, algorithm=None))
    key = private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption())
    return certificate.public_bytes(serialization.Encoding.PEM), key


def server_context(private_key, common_name: str) -> ssl.SSLContext:
    """The callee's TLS 1.3 context, serving its identity certificate."""
    certificate, key = identity_certificate(private_key, common_name)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.set_alpn_protocols(ALPN)
    # ssl loads certificate chains only from files: write both to a private folder, load, and remove it.
    folder = tempfile.mkdtemp(prefix="prompits-tls-")
    try:
        os.chmod(folder, 0o700)
        certificate_path, key_path = os.path.join(folder, "certificate.pem"), os.path.join(folder, "key.pem")
        for path, data in ((certificate_path, certificate), (key_path, key)):
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
        context.load_cert_chain(certificate_path, key_path)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return context


def client_context() -> ssl.SSLContext:
    """The caller's TLS 1.3 context. It trusts no authority; `connect_pinned` checks the callee's exact key."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.set_alpn_protocols(ALPN)
    return context


def peer_public_key(ssl_object) -> bytes:
    """The raw Ed25519 public key in the peer's certificate; raises PermissionError for any other key."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    der = ssl_object.getpeercert(binary_form=True)
    if not der:
        raise PermissionError("The callee presented no certificate.")
    key = x509.load_der_x509_certificate(der).public_key()
    if not isinstance(key, Ed25519PublicKey):
        raise PermissionError("The callee's certificate is not its Ed25519 identity.")
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


class TLSStream:
    """TLS over a byte stream, with `ssl.MemoryBIO`. It is itself a byte stream."""

    def __init__(self, inner, ssl_object: ssl.SSLObject, incoming: ssl.MemoryBIO, outgoing: ssl.MemoryBIO):
        self.inner, self.ssl, self.incoming, self.outgoing = inner, ssl_object, incoming, outgoing
        self._write_lock = asyncio.Lock()
        self._eof = False
        self.closed = False

    @classmethod
    async def handshake(cls, inner, context: ssl.SSLContext, *, server_side: bool, server_hostname=None,
                        timeout: float = HANDSHAKE_SECONDS) -> "TLSStream":
        incoming, outgoing = ssl.MemoryBIO(), ssl.MemoryBIO()
        stream = cls(inner, context.wrap_bio(incoming, outgoing, server_side=server_side,
                                             server_hostname=server_hostname), incoming, outgoing)
        await asyncio.wait_for(stream._handshake(), timeout)
        return stream

    async def _handshake(self):
        while True:
            try:
                self.ssl.do_handshake()
                break
            except ssl.SSLWantReadError:
                await self._flush()
                chunk = await self.inner.recv()
                if not chunk:
                    raise ConnectionError("The stream closed during the TLS handshake.")
                self.incoming.write(chunk)
        await self._flush()

    async def _flush(self):
        async with self._write_lock:
            data = self.outgoing.read()
            if data:
                await self.inner.send(data)

    async def recv(self, max_bytes: int = READ_BYTES) -> bytes:
        while True:
            try:
                data = self.ssl.read(max_bytes)
            except ssl.SSLWantReadError:
                await self._flush()
                if self._eof:
                    return b""
                chunk = await self.inner.recv()
                if chunk:
                    self.incoming.write(chunk)
                else:
                    self._eof = True
                    self.incoming.write_eof()
                continue
            except (ssl.SSLZeroReturnError, ssl.SSLEOFError):
                return b""
            await self._flush()  # TLS 1.3 may answer post-handshake messages
            return data

    async def send(self, data: bytes) -> None:
        if self.closed:
            raise ConnectionError("The TLS stream is closed.")
        view = memoryview(data)
        while view:
            written = self.ssl.write(view[:READ_BYTES])
            view = view[written:]
            await self._flush()

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.ssl.unwrap()
        except (ssl.SSLError, ValueError):
            pass
        try:
            await self._flush()
        except (ConnectionError, OSError, RuntimeError):
            pass
        await self.inner.aclose()


async def connect_pinned(inner, expected_key: bytes, *, timeout: float = HANDSHAKE_SECONDS) -> TLSStream:
    """TLS to a callee over `inner`, accepted only when its identity key is exactly `expected_key`."""
    stream = await TLSStream.handshake(inner, client_context(), server_side=False,
                                       server_hostname="agent.pipeline.invalid", timeout=timeout)
    try:
        presented = peer_public_key(stream.ssl)
        if len(expected_key) != 32 or not hmac.compare_digest(presented, expected_key):
            raise PermissionError("The callee's identity key is not the one Plaza named.")
    except BaseException:
        await stream.aclose()
        raise
    return stream
