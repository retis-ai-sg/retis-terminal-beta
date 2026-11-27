"""Component logs: the child writes straight to its file (so it keeps running if the manager stops), and the
manager rotates by copy-and-truncate. Children open the file in append mode, so truncation is safe.

A credential a component prints (a token, key or password, also one an address carries, such as a launch's
#local-access) does not stay in its log: as the log grows the manager overwrites each one in place with asterisks
of the same length (`mask_secrets`), and whatever it shows or reports from a log passes through `redact` first.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import sys
import time
from collections import deque
from pathlib import Path

# The manager writes a start line before each run, so a component's last error comes from its current run only.
START_LINE = "--- component manager: start "

SECRET_NAMES = r'(?:api[_-]?key|token|secret|password|passwd|authorization|cookie|session|private[_-]?key|access[_-]?key)'
_BEARER = re.compile(r'(?i)\b(bearer\s+)([A-Za-z0-9._~+/=-]{8,})')
_NAMED = re.compile(r'(?i)(["\']?' + SECRET_NAMES + r'["\']?\s*[:=]\s*["\']?)([^\s"\',;]{4,})')
_WHOLE = (
    re.compile(r'\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b'),
    re.compile(r'\b(?:lc|pc|cs)-(?:access|refresh|call)-[A-Za-z0-9_-]{8,}'),
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----'),
)
# A credential an address carries by name in its query or fragment (?ticket=, &code=, #local-access=), also URL-encoded.
URL_PARAMETER = re.compile(r'(?i)((?:[?&#;]|%3F|%26|%23)[\w.-]*?(?:access|token|secret|key|password|ticket|code|state|session|auth)'
                           r'(?:=|%3D))([^\s&#"\'<>]+)')
_NOT_LINE_BREAK = re.compile(r'[^\r\n]')

# How a component writes its own records (`configure_logging`); `last_error` reads their level and time.
RECORD_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'
# A logging record's first line, as components write them: "<time> LEVEL name: message" (the run_local_* launchers),
# "[agent] <time> - name - LEVEL - message" (prompits agents) or "LEVEL: message" (uvicorn, the manager itself).
_TIME = r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?'
_RECORD = re.compile(r'^(?:\[[^\]]{1,100}\]\s+)?(?:' + _TIME + r'[\s|-]+(?:[\w.<>-]{1,100}(?:\s+-)?\s+)?)?'
                     r'(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b')
# Python prints this above the traceback of an exception nothing caught in a thread, which then ended.
_THREAD_EXCEPTION = re.compile(r'^Exception in thread .+:$')
ERROR_LEVELS = frozenset({'ERROR', 'CRITICAL', 'FATAL'})
TRACEBACK = 'Traceback (most recent call last):'


def redact(text: str, *, keep_length: bool = False) -> str:
    """`text` without credentials: each value becomes [removed], or with `keep_length` asterisks of its length (line
    breaks kept), so a file can be masked in place."""
    def hide(value: str) -> str:
        return _NOT_LINE_BREAK.sub('*', value) if keep_length else '[removed]'
    text = URL_PARAMETER.sub(lambda m: m.group(1) + hide(m.group(2)), text)
    text = _BEARER.sub(lambda m: m.group(1) + hide(m.group(2)), text)
    text = _NAMED.sub(lambda m: m.group(1) + hide(m.group(2)), text)
    for pattern in _WHOLE:
        text = pattern.sub(lambda m: hide(m.group(0)), text)
    return text


def configure_logging(*verbose: str) -> None:
    """A component's log as the manager reads it: a time and a level on every record, so "Last error" tells an error
    from a warning and says when it happened. Libraries keep to warnings and errors; the loggers named in `verbose`
    also say what they do (INFO)."""
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout, format=RECORD_FORMAT)
    for name in verbose:
        logging.getLogger(name).setLevel(logging.INFO)


def start_line(component_id: str, version: str, when: float) -> str:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))
    return f"{START_LINE}{component_id} {version} at {stamp} ---\n"


def mask_secrets(path: Path, start: int = 0) -> int:
    """Overwrite each credential in the log, from byte `start` to its last complete line, with asterisks of the same
    length; return the byte the next call starts from. The file's length never changes and the child only appends, so
    nothing it writes meanwhile is lost. A log shorter than `start` was truncated since: it is read from its start."""
    try:
        with open(path, "r+b") as handle:
            size = handle.seek(0, os.SEEK_END)
            start = start if start <= size else 0
            handle.seek(start)
            chunk = handle.read(size - start)
            end = chunk.rfind(b"\n") + 1
            if end:
                text = chunk[:end].decode("latin-1")  # one character for each byte: a mask keeps every byte in place
                masked = redact(text, keep_length=True)
                if masked != text:
                    handle.seek(start)
                    handle.write(masked.encode("latin-1"))
            return start + end
    except FileNotFoundError:
        return 0


def rotate_if_needed(path: Path, *, max_bytes: int = 5 * 1024 * 1024, keep: int = 3) -> bool:
    try:
        if path.stat().st_size <= max_bytes:
            return False
    except FileNotFoundError:
        return False
    for index in range(keep - 1, 0, -1):
        older = path.with_name(f"{path.name}.{index}")
        if older.exists():
            os.replace(older, path.with_name(f"{path.name}.{index + 1}"))
    shutil.copyfile(path, path.with_name(f"{path.name}.1"))
    with open(path, "r+b") as handle:
        handle.truncate(0)
    mask_secrets(path.with_name(f"{path.name}.1"))  # also what the child wrote since the last mask
    return True


def tail(path: Path, lines: int = 200) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return [line.rstrip("\n") for line in deque(handle, maxlen=max(lines, 0))]
    except FileNotFoundError:
        return []


def _records(lines: list[str]) -> list[tuple[str | None, list[str]]]:
    """The lines as records: each starts at a line with a level and takes the lines below it (its traceback, the rest
    of its message). The lines above the first one form a record with no level."""
    records: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in lines:
        found = _RECORD.match(line)
        level = found.group(1) if found else "ERROR" if _THREAD_EXCEPTION.match(line) else None
        if level:
            records.append((level, [line]))
        else:
            records[-1][1].append(line)
    return records


def _exception(lines: list[str]) -> str:
    """The exception the last traceback in `lines` ends in ("OSError: ..."), or "" when they hold none."""
    found, inside = "", False
    for line in lines:
        if line.startswith(TRACEBACK):
            inside = True
        elif inside and line.strip() and not line[0].isspace():
            found, inside = line.strip(), False
    return found


def last_error(path: Path, *, scan: int = 400, crashed: bool = False) -> str:
    """The newest error of the current run, with the time its record gives. Errors are records logged as ERROR,
    CRITICAL or FATAL (with the exception their traceback ends in), an exception nothing caught in a thread, and a
    traceback above every record, such as a start that failed on an import. A traceback below a warning or another
    lower record belongs to that record: a library warns with one about what it handles itself, such as the socket of
    a network adapter that went away. `crashed`: the run ended with an error code, so a traceback that ends the log
    is what ended it, whichever record it follows.

    Lines above the last start line belong to earlier runs; a log rotated since the start holds only the current run."""
    lines = tail(path, scan)
    starts = [index for index, line in enumerate(lines) if line.startswith(START_LINE)]
    records = _records(lines[starts[-1] + 1:] if starts else lines)
    for index in range(len(records) - 1, -1, -1):
        level, body = records[index]
        exception = _exception(body)
        if level in ERROR_LEVELS:
            header = " ".join(body[0].split())
            text = f"{header.rstrip(':')} — {exception}" if exception else header
        elif exception and (level is None or (crashed and index == len(records) - 1)):
            text = exception
        else:
            continue
        return redact(text)[:300]
    return ""
