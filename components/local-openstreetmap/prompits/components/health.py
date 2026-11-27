"""The one request every component answers about itself, and the manager's probe for it.

A component serves `GET <health_path>` (default `/health`) on 127.0.0.1 at its port and answers with
`health_payload(...)`::

    {"schema": "prompits.component-health/1", "up": true, "ready": false, "version": "1.2.0",
     "reason": "downloading data", "needs": ["data"]}

`needs` lists what the user still has to provide before the component is ready, using short codes the
manager understands: `data` (a download the component offers). Other codes are shown as reasons.

`reasons` (optional) gives the reason in other languages, `{language: text}` (such as `{"zh-Hant": "..."}`), the way a
parts list names a component: the manager shows the one in the viewer's language, else `reason`.

`details` (optional, an object of at most 32 KB) is what the component tells its settings form now:
`{"groups": {group id: {"state", "count"}}, "items": {field id: {value: {"state", "count"}}},
"suggestions": {field id: [values]}}`, such as which model servers it found (prompits.components.settings).
"""
from __future__ import annotations

import asyncio
import json
import re
import socket
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterable

SCHEMA = "prompits.component-health/1"


MAX_DETAILS = 32 * 1024
MAX_REASONS = 8
MAX_REASON = 600
LANGUAGE = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})?")


def _reasons(value) -> dict:
    """The reason in other languages, when it is a small {language: text} object; anything else is left out."""
    if not isinstance(value, dict):
        return {}
    return {key: text[:MAX_REASON] for key, text in list(value.items())[:MAX_REASONS]
            if isinstance(key, str) and LANGUAGE.fullmatch(key) and isinstance(text, str) and text}


def health_payload(*, ready: bool, version: str, up: bool = True, reason: str = "",
                   needs: Iterable[str] = (), details: dict | None = None, reasons: dict | None = None) -> dict:
    payload = {"schema": SCHEMA, "up": bool(up), "ready": bool(ready), "version": str(version),
               "reason": str(reason), "needs": [str(item) for item in needs]}
    if _reasons(reasons):
        payload["reasons"] = _reasons(reasons)
    if details:
        payload["details"] = details
    return payload


def _details(value) -> dict:
    """A component's details for its settings form, when they are an object of a bounded size; else none."""
    if not isinstance(value, dict):
        return {}
    try:
        return value if len(json.dumps(value)) <= MAX_DETAILS else {}
    except (TypeError, ValueError):
        return {}


@dataclass(frozen=True)
class HealthReport:
    reachable: bool
    up: bool = False
    ready: bool = False
    version: str = ""
    reason: str = ""
    needs: tuple[str, ...] = field(default_factory=tuple)
    details: dict = field(default_factory=dict, compare=False)
    reasons: dict = field(default_factory=dict, compare=False)

    def as_dict(self) -> dict:
        return {"reachable": self.reachable, "up": self.up, "ready": self.ready, "version": self.version,
                "reason": self.reason, "needs": list(self.needs), **({"reasons": self.reasons} if self.reasons else {}),
                **({"details": self.details} if self.details else {})}

    def reason_in(self, language: str) -> str:
        """The reason in `language` when the component gave it, else as given."""
        return self.reasons.get(language) or self.reason


def port_open(port: int, *, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


_LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def probe(port: int, path: str = "/health", *, timeout: float = 2.0) -> HealthReport:
    """Ask the component on 127.0.0.1:`port` how it is. A closed port or a bad answer is a report, not an error."""
    if not port_open(port, timeout=min(timeout, 0.5)):
        return HealthReport(reachable=False, reason="port closed")
    try:
        with _LOCAL.open(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
            body = json.loads(response.read(64 * 1024).decode("utf-8"))
    except Exception as error:  # an unanswered or malformed check is reported, never raised
        return HealthReport(reachable=True, reason=f"health check failed: {type(error).__name__}")
    if not isinstance(body, dict) or body.get("schema") != SCHEMA:
        return HealthReport(reachable=True, reason="health check answered in an unknown format")
    needs = body.get("needs") if isinstance(body.get("needs"), list) else []
    return HealthReport(reachable=True, up=bool(body.get("up")), ready=bool(body.get("ready")),
                        version=str(body.get("version") or ""), reason=str(body.get("reason") or ""),
                        needs=tuple(str(item) for item in needs), details=_details(body.get("details")),
                        reasons=_reasons(body.get("reasons")))


async def serve_health(port: int, report: Callable[[], dict], *, path: str = "/health", host: str = "127.0.0.1"):
    """Answer `GET <path>` on 127.0.0.1:`port` with `report()` (a `health_payload`); return the asyncio server.

    It reads one request line and its headers, runs `report` off the event loop, answers and closes.
    Anything else gets 404. It listens on loopback only, for the manager on this computer.
    """
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            line = await asyncio.wait_for(reader.readline(), 5)
            for _ in range(100):
                header = await asyncio.wait_for(reader.readline(), 5)
                if header in (b"\r\n", b"\n", b""):
                    break
            parts = line.decode("latin-1").split()
            if len(parts) >= 2 and parts[0] == "GET" and parts[1] == path:
                try:
                    body, status = json.dumps(await asyncio.to_thread(report)).encode(), "200 OK"
                except Exception as error:  # a failing report is itself the health answer
                    body, status = json.dumps(health_payload(ready=False, version="", up=False, reason=type(error).__name__)).encode(), "200 OK"
            else:
                body, status = b"{}", "404 Not Found"
            writer.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                         f"Cache-Control: no-store\r\nConnection: close\r\n\r\n".encode() + body)
            await writer.drain()
        except (asyncio.TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, host, port)
