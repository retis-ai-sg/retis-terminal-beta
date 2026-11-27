"""
Sign-in for AI apps on this computer: an OAuth 2.1 authorization server that a person approves in the host's own UI.

An AI app (Claude Code, Codex, ...) that reaches a host's MCP endpoint without a token follows MCP's sign-in flow:
it registers itself (dynamic client registration), opens the person's browser at the authorization endpoint with a
PKCE challenge and a loopback redirect, and exchanges the code it gets back for a token. This module is that
authorization server, for loopback clients only. It decides nothing about the person: `authorize` parks the request
and sends the browser to the host's approval page (`approval_url`), and the host calls `approve` (with its `grant`,
an opaque JSON object such as an account and a window) or `deny` once the person has chosen. Tokens carry the
approval as their subject, so the host can look the grant up on every call, and revoking an approval ends its
tokens at once.

Only hashes of codes and tokens are stored. Access tokens are short-lived and refresh tokens rotate. It implements
the SDK's `OAuthAuthorizationServerProvider`, so the SDK's own routes (metadata, register, authorize, token, revoke)
and bearer check serve it; it needs the optional MCP SDK 2.x (`prompits/mcp/requirements.txt`) only when they do.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.parse import urlencode, urlsplit

ACCESS_SECONDS = 3600
REFRESH_SECONDS = 30 * 86400
CODE_SECONDS = 300
REQUEST_SECONDS = 900
MAX_PENDING = 20
MAX_CLIENTS = 200


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def loopback_redirect(uri: Any) -> bool:
    """Whether a redirect address is on this computer (http to 127.0.0.1, [::1] or localhost), as RFC 8252 asks."""
    try:
        parts = urlsplit(str(uri))
    except ValueError:
        return False
    if parts.scheme != "http" or not parts.hostname or parts.username or parts.password:
        return False
    if parts.hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        return False


class LocalAuthorization:
    """OAuth 2.1 authorization server for AI apps on this computer, each approved by a person in the host's UI."""

    def __init__(
        self,
        path: Any,
        *,
        issuer: str,
        approval_url: Callable[[str], str],
        access_seconds: int = ACCESS_SECONDS,
        refresh_seconds: int = REFRESH_SECONDS,
        clock: Callable[[], float] = time.time,
    ):
        self.path = Path(path)
        self.issuer = issuer  # exactly as the server's metadata names it: the app checks the `iss` it gets back (RFC 9207)
        self.approval_url = approval_url
        self.access_seconds, self.refresh_seconds = int(access_seconds), int(refresh_seconds)
        self.clock = clock
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, info TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, params TEXT NOT NULL,
                    created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY, client_id TEXT NOT NULL, client_name TEXT NOT NULL,
                    grant_json TEXT NOT NULL, created REAL NOT NULL, last_used REAL, revoked REAL);
                CREATE TABLE IF NOT EXISTS codes (hash TEXT PRIMARY KEY, approval_id TEXT NOT NULL, client_id TEXT NOT NULL,
                    params TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, kind TEXT NOT NULL, approval_id TEXT NOT NULL,
                    client_id TEXT NOT NULL, resource TEXT, scopes TEXT NOT NULL, expires REAL NOT NULL);
                """
            )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _sweep(self, db: sqlite3.Connection) -> None:
        now = self.clock()
        db.execute("DELETE FROM requests WHERE created < ?", (now - REQUEST_SECONDS,))
        db.execute("DELETE FROM codes WHERE expires < ?", (now,))
        db.execute("DELETE FROM tokens WHERE expires < ?", (now,))

    # --- the SDK's provider protocol --------------------------------------------------------------------------

    async def get_client(self, client_id: str):
        from mcp.shared.auth import OAuthClientInformationFull

        with self._lock, self._db() as db:
            row = db.execute("SELECT info FROM clients WHERE id = ?", (client_id,)).fetchone()
        return OAuthClientInformationFull.model_validate_json(row["info"]) if row else None

    async def register_client(self, client_info) -> None:
        from mcp.server.auth.provider import RegistrationError

        uris = list(client_info.redirect_uris or [])
        if not uris or not all(loopback_redirect(uri) for uri in uris):
            raise RegistrationError("invalid_redirect_uri", "Only apps on this computer can sign in: use a loopback redirect.")
        if (client_info.token_endpoint_auth_method or "none") != "none":
            raise RegistrationError("invalid_client_metadata", "Sign in as a public client (token_endpoint_auth_method none).")
        with self._lock, self._db() as db:
            if db.execute("SELECT COUNT(*) FROM clients").fetchone()[0] >= MAX_CLIENTS:
                db.execute("DELETE FROM clients WHERE id IN (SELECT id FROM clients WHERE id NOT IN "
                           "(SELECT client_id FROM approvals WHERE revoked IS NULL) ORDER BY created LIMIT 20)")
            db.execute("INSERT OR REPLACE INTO clients VALUES (?, ?, ?)",
                       (client_info.client_id, client_info.model_dump_json(), self.clock()))

    async def authorize(self, client, params) -> str:
        from mcp.server.auth.provider import AuthorizeError

        if not loopback_redirect(params.redirect_uri):
            raise AuthorizeError("invalid_request", "Only apps on this computer can sign in.")
        request_id = "r-" + secrets.token_hex(16)
        with self._lock, self._db() as db:
            self._sweep(db)
            if db.execute("SELECT COUNT(*) FROM requests").fetchone()[0] >= MAX_PENDING:
                raise AuthorizeError("temporarily_unavailable", "Too many sign-in requests are waiting; try again later.")
            db.execute("INSERT INTO requests VALUES (?, ?, ?, ?)",
                       (request_id, client.client_id, params.model_dump_json(), self.clock()))
        return self.approval_url(request_id)

    async def load_authorization_code(self, client, authorization_code: str):
        from mcp.server.auth.provider import AuthorizationCode

        with self._lock, self._db() as db:
            self._sweep(db)
            row = db.execute("SELECT * FROM codes WHERE hash = ? AND client_id = ?",
                             (_digest(authorization_code), client.client_id)).fetchone()
        if row is None:
            return None
        params = json.loads(row["params"])
        return AuthorizationCode(code=authorization_code, scopes=params.get("scopes") or [], expires_at=row["expires"],
                                 client_id=row["client_id"], code_challenge=params["code_challenge"],
                                 redirect_uri=params["redirect_uri"],
                                 redirect_uri_provided_explicitly=params["redirect_uri_provided_explicitly"],
                                 resource=params.get("resource"), subject=row["approval_id"])

    async def exchange_authorization_code(self, client, authorization_code):
        with self._lock, self._db() as db:
            used = db.execute("DELETE FROM codes WHERE hash = ?", (_digest(authorization_code.code),)).rowcount
        if not used:
            from mcp.server.auth.provider import TokenError

            raise TokenError("invalid_grant", "That sign-in code was already used.")
        return self._issue(client.client_id, authorization_code.subject, authorization_code.resource,
                           authorization_code.scopes)

    async def load_refresh_token(self, client, refresh_token: str):
        from mcp.server.auth.provider import RefreshToken

        row = self._token_row(refresh_token, "refresh")
        if row is None or row["client_id"] != client.client_id:
            return None
        return RefreshToken(token=refresh_token, client_id=row["client_id"], scopes=json.loads(row["scopes"]),
                            expires_at=int(row["expires"]), resource=row["resource"], subject=row["approval_id"])

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        with self._lock, self._db() as db:
            db.execute("DELETE FROM tokens WHERE hash = ?", (_digest(refresh_token.token),))
        return self._issue(client.client_id, refresh_token.subject, refresh_token.resource,
                           scopes or refresh_token.scopes)

    async def load_access_token(self, token: str):
        from mcp.server.auth.provider import AccessToken

        row = self._token_row(token, "access")
        if row is None:
            return None
        with self._lock, self._db() as db:
            db.execute("UPDATE approvals SET last_used = ? WHERE id = ?", (self.clock(), row["approval_id"]))
        return AccessToken(token=token, client_id=row["client_id"], scopes=json.loads(row["scopes"]),
                           expires_at=int(row["expires"]), resource=row["resource"], subject=row["approval_id"],
                           claims={"iss": self.issuer})

    async def revoke_token(self, token) -> None:
        with self._lock, self._db() as db:
            db.execute("DELETE FROM tokens WHERE hash = ?", (_digest(token.token),))

    # --- internals ------------------------------------------------------------------------------------------------

    def _token_row(self, token: str, kind: str):
        with self._lock, self._db() as db:
            self._sweep(db)
            return db.execute(
                "SELECT t.* FROM tokens t JOIN approvals a ON a.id = t.approval_id "
                "WHERE t.hash = ? AND t.kind = ? AND a.revoked IS NULL", (_digest(token), kind)).fetchone()

    def _issue(self, client_id: str, approval_id: Optional[str], resource: Optional[str], scopes: List[str]):
        from mcp.shared.auth import OAuthToken

        access, refresh = "mcp-at-" + secrets.token_urlsafe(32), "mcp-rt-" + secrets.token_urlsafe(32)
        now = self.clock()
        with self._lock, self._db() as db:
            if not approval_id or db.execute("SELECT 1 FROM approvals WHERE id = ? AND revoked IS NULL",
                                             (approval_id,)).fetchone() is None:
                from mcp.server.auth.provider import TokenError

                raise TokenError("invalid_grant", "This app's approval was revoked; sign in again.")
            for value, kind, seconds in ((access, "access", self.access_seconds), (refresh, "refresh", self.refresh_seconds)):
                db.execute("INSERT INTO tokens VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (_digest(value), kind, approval_id, client_id, resource, json.dumps(list(scopes or [])),
                            now + seconds))
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=self.access_seconds,
                          refresh_token=refresh, scope=" ".join(scopes) if scopes else None)

    def _redirect(self, params: Mapping[str, Any], **query: str) -> str:
        values = {**query, **({"state": params["state"]} if params.get("state") else {}), "iss": self.issuer}
        uri = str(params["redirect_uri"])
        return uri + ("&" if urlsplit(uri).query else "?") + urlencode(values)

    # --- what the host calls --------------------------------------------------------------------------------------

    def pending_ids(self) -> List[str]:
        """The sign-in requests waiting for a person, oldest first."""
        with self._lock, self._db() as db:
            self._sweep(db)
            return [row["id"] for row in db.execute("SELECT id FROM requests ORDER BY created")]

    def pending(self, request_id: str) -> Optional[Dict[str, Any]]:
        """A waiting sign-in request: the app's name and where it will be sent back, or None when it is gone."""
        with self._lock, self._db() as db:
            self._sweep(db)
            row = db.execute("SELECT r.*, c.info FROM requests r JOIN clients c ON c.id = r.client_id WHERE r.id = ?",
                             (request_id,)).fetchone()
        if row is None:
            return None
        info, params = json.loads(row["info"]), json.loads(row["params"])
        return {"id": request_id, "client_id": row["client_id"], "client_name": str(info.get("client_name") or "An AI app")[:80],
                "redirect": urlsplit(str(params["redirect_uri"])).netloc, "created": row["created"]}

    def approve(self, request_id: str, grant: Mapping[str, Any]) -> str:
        """Approve a waiting request for `grant`; returns where to send the person's browser (back to the app)."""
        code = "mcp-code-" + secrets.token_urlsafe(32)
        approval_id = "a-" + secrets.token_hex(12)
        with self._lock, self._db() as db:
            self._sweep(db)
            row = db.execute("SELECT r.*, c.info FROM requests r JOIN clients c ON c.id = r.client_id WHERE r.id = ?",
                             (request_id,)).fetchone()
            if row is None:
                raise KeyError("This sign-in request has ended; start again from the AI app.")
            params = json.loads(row["params"])
            name = str(json.loads(row["info"]).get("client_name") or "An AI app")[:80]
            db.execute("DELETE FROM requests WHERE id = ?", (request_id,))
            db.execute("INSERT INTO approvals VALUES (?, ?, ?, ?, ?, NULL, NULL)",
                       (approval_id, row["client_id"], name, json.dumps(dict(grant)), self.clock()))
            db.execute("INSERT INTO codes VALUES (?, ?, ?, ?, ?)",
                       (_digest(code), approval_id, row["client_id"], row["params"], self.clock() + CODE_SECONDS))
        return self._redirect(params, code=code)

    def deny(self, request_id: str) -> str:
        """Refuse a waiting request; returns where to send the person's browser (back to the app, with access_denied)."""
        with self._lock, self._db() as db:
            row = db.execute("SELECT params FROM requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise KeyError("This sign-in request has ended.")
            db.execute("DELETE FROM requests WHERE id = ?", (request_id,))
        return self._redirect(json.loads(row["params"]), error="access_denied")

    def grant(self, approval_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """The grant of an approval that still stands, or None."""
        if not approval_id:
            return None
        with self._lock, self._db() as db:
            row = db.execute("SELECT grant_json FROM approvals WHERE id = ? AND revoked IS NULL", (approval_id,)).fetchone()
        return json.loads(row["grant_json"]) if row else None

    def approvals(self, match: Callable[[Dict[str, Any]], bool] = lambda grant: True) -> List[Dict[str, Any]]:
        """Approvals that still stand and whose grant `match`es, newest first, for the host's list of AI apps."""
        with self._lock, self._db() as db:
            rows = db.execute("SELECT * FROM approvals WHERE revoked IS NULL ORDER BY created DESC").fetchall()
        listed = []
        for row in rows:
            grant = json.loads(row["grant_json"])
            if match(grant):
                listed.append({"id": row["id"], "client_name": row["client_name"], "grant": grant,
                               "created": row["created"], "last_used": row["last_used"]})
        return listed

    def revoke(self, approval_id: str) -> bool:
        """End an approval and every token it issued; returns whether it stood."""
        with self._lock, self._db() as db:
            changed = db.execute("UPDATE approvals SET revoked = ? WHERE id = ? AND revoked IS NULL",
                                 (self.clock(), approval_id)).rowcount
            db.execute("DELETE FROM tokens WHERE approval_id = ?", (approval_id,))
            db.execute("DELETE FROM codes WHERE approval_id = ?", (approval_id,))
        return bool(changed)
