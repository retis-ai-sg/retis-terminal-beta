"""What components use (CPU, memory, disk), what needs attention, and the one-shot jobs that fetch their data.

- `Usage`: CPU and memory of a component's process and its children, from psutil, sampled between calls.
- `folder_size`: bytes under a folder as last measured. Folders are walked on a background thread, never by
  the caller, because data folders can hold gigabytes and a status page must answer at once.
- `DataJobs`: a component's data download, run as its own process (the parts list names its command), with its
  output in its own log, so a download survives the page closing and is never part of the package.
- `alerts`: the conditions the manager's page shows at the top: a component that keeps crashing or has been
  unhealthy for a while, a data download that failed. Free disk space is shown, never warned about: the user's
  disk is the user's business. An update waiting is no alert either: the component's own row says so (Alvin,
  2026-11-26).
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from prompits.core.process_utils import background_popen_kwargs, terminate_process

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

UNHEALTHY_ALERT_SECONDS = 600


class Usage:
    """CPU percent (since the previous sample of the same process) and resident memory, children included."""

    def __init__(self):
        self._processes: dict[int, Any] = {}

    def sample(self, pid: int | None) -> dict[str, Any] | None:
        if not pid or psutil is None:
            return None
        try:
            process = self._processes.get(pid)
            if process is None or not process.is_running():
                process = self._processes[pid] = psutil.Process(pid)
                process.cpu_percent(None)  # the first reading starts the interval
            family = [process]
            try:
                family += process.children(recursive=True)
            except psutil.Error:
                pass
            cpu = memory = 0.0
            for member in family:
                try:
                    if member.pid != pid:
                        cached = self._processes.setdefault(member.pid, member)
                        cpu += cached.cpu_percent(None)
                    else:
                        cpu += process.cpu_percent(None)
                    memory += member.memory_info().rss
                except psutil.Error:
                    continue
            return {'cpu_percent': round(cpu, 1), 'memory_bytes': int(memory), 'processes': len(family)}
        except psutil.Error:
            self._processes.pop(pid, None)
            return None


_SIZES: dict[str, tuple[float, int]] = {}
_WANTED: dict[str, Callable[[], float]] = {}   # folders to measure, in the order asked, each with the clock it is kept by
_MEASURING: list[str] = []                       # the folder being walked now, if any
_CHANGED: set[str] = set()                       # folders that changed while being walked: their walk is out of date
_SIZE_LOCK = threading.Condition()
_SIZE_WORKER: list[threading.Thread] = []


def forget_size(path: Path) -> None:
    """Measure a folder again at the next read; its last size is shown until the new one is known."""
    key = str(path)
    with _SIZE_LOCK:
        if key in _SIZES:
            _SIZES[key] = (-math.inf, _SIZES[key][1])
        if key in _MEASURING:   # a walk that started before the change may have missed it
            _CHANGED.add(key)


def folder_size(path: Path, *, max_age: float = 300.0, clock: Callable[[], float] = time.monotonic) -> int | None:
    """Bytes under `path` as last measured, or None before the first measurement is done.

    It never walks the folder itself: a measurement older than `max_age` is renewed on one background thread, one
    folder at a time. A status page asks for every component's folders on each refresh, and walking tens of thousands
    of files on a busy disk took the manager's status from milliseconds to minutes (2026-11-26)."""
    key = str(path)
    with _SIZE_LOCK:
        cached = _SIZES.get(key)
        if (cached is None or clock() - cached[0] >= max_age) and key not in _WANTED and key not in _MEASURING:
            _WANTED[key] = clock
            if not _SIZE_WORKER or not _SIZE_WORKER[0].is_alive():
                _SIZE_WORKER[:] = [threading.Thread(target=_measure_folders, name='folder-sizes', daemon=True)]
                _SIZE_WORKER[0].start()
            _SIZE_LOCK.notify()
        return cached[1] if cached else None


def _measure_folders():
    while True:
        with _SIZE_LOCK:
            while not _WANTED:
                _SIZE_LOCK.wait()
            key, clock = next(iter(_WANTED.items()))
            del _WANTED[key]
            _MEASURING[:] = [key]
        try:
            total = measure_folder(Path(key))
        except Exception:   # never stops measuring: the folder keeps its last size and is asked for again later
            total = None
        with _SIZE_LOCK:
            _MEASURING.clear()
            last = _SIZES.get(key)
            if total is None and last is None:
                continue
            # A walk that missed a change counts as old at once, so the next read measures it again.
            _SIZES[key] = (-math.inf if key in _CHANGED or total is None else clock(), last[1] if total is None else total)
            _CHANGED.discard(key)


def measure_folder(path: Path) -> int:
    """Bytes in the files under `path` now (links are counted, not followed); 0 when it does not exist."""
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def disk(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    return {'free_bytes': usage.free, 'total_bytes': usage.total}


class DataJobs:
    """At most one data download per component, run as a separate process with its own log."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self.jobs: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, subprocess.Popen] = {}

    def start(self, component_id: str, data_id: str, command: list[str], env: dict[str, str], cwd: Path, log_path: Path):
        if self.running(component_id):
            raise RuntimeError(f'{component_id} is already downloading its data.')
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, 'ab') as log:
            process = subprocess.Popen(command, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT, **background_popen_kwargs())
        self._processes[component_id] = process
        self.jobs[component_id] = {'data': data_id, 'state': 'running', 'started_at': self.clock(), 'log': str(log_path)}
        return dict(self.jobs[component_id])

    def running(self, component_id: str) -> bool:
        process = self._processes.get(component_id)
        return process is not None and process.poll() is None

    def poll(self) -> list[dict[str, Any]]:
        """Finish jobs whose process ended; return those jobs."""
        ended = []
        for component_id, process in list(self._processes.items()):
            code = process.poll()
            if code is None:
                continue
            self._processes.pop(component_id)
            job = self.jobs[component_id]
            job.update(state='done' if code == 0 else 'failed', code=code, ended_at=self.clock())
            ended.append({'component': component_id, **job})
        return ended

    def stop(self, component_id: str):
        process = self._processes.pop(component_id, None)
        if process is not None:
            terminate_process(process)
            self.jobs[component_id].update(state='stopped', ended_at=self.clock())

    def view(self, component_id: str) -> dict[str, Any] | None:
        job = self.jobs.get(component_id)
        if not job:
            return None
        from prompits.components.logs import tail
        lines = tail(Path(job['log']), 1)
        return {**job, 'last_line': lines[-1][:300] if lines else ''}


def alerts(rows: list[dict[str, Any]], *, now: float) -> list[dict[str, Any]]:
    found = []
    for row in rows:
        process = row.get('process') or {}
        if process.get('crash_loop'):
            found.append({'kind': 'crash_loop', 'component': row['id'], 'severity': 'error'})
        elif row.get('state') == 'unhealthy' and process.get('started_at') and now - process['started_at'] > UNHEALTHY_ALERT_SECONDS:
            found.append({'kind': 'unhealthy', 'component': row['id'], 'severity': 'warning', 'reason': row.get('reason', '')})
        job = row.get('data_job') or {}
        if job.get('state') == 'failed':
            found.append({'kind': 'data_failed', 'component': row['id'], 'severity': 'warning'})
    return found
