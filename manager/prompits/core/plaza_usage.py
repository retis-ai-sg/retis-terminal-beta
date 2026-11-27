"""Plaza's own usage, as counts only, for its owner and administrators.

- `plaza_usage_active_accounts`: accounts that made a signed-in request in the last hour.
- `plaza_usage_terminal_sessions`: Terminal sessions whose access is live now (their tokens renew hourly).
- `plaza_usage_sign_ins_hour` and `plaza_usage_failed_sign_ins_hour`: password sign-ins accepted and refused in the
  last hour.

Counted in memory and reported as Plaza's own numbers, labelled `{"visibility": "owner"}` so readers without log
access to Plaza never see them. Nothing about who: the counts only. A Plaza restart starts them again.
"""
from __future__ import annotations

import collections
import threading
import time

WINDOW_SEC = 3600
MAX_ACCOUNTS = 100_000
OWNER = {'visibility': 'owner'}


class UsageCounts:
    def __init__(self, *, clock=time.time):
        self.clock = clock
        self.lock = threading.Lock()
        self.accounts: dict = {}
        self.sign_ins = collections.deque()
        self.failed = collections.deque()

    def _forget(self, now):
        cutoff = now - WINDOW_SEC
        for times in (self.sign_ins, self.failed):
            while times and times[0] < cutoff:
                times.popleft()
        if len(self.accounts) > MAX_ACCOUNTS // 2:
            self.accounts = {account: at for account, at in self.accounts.items() if at >= cutoff}

    def seen(self, account_id):
        """A signed-in request by this account."""
        if not account_id:
            return
        now = self.clock()
        with self.lock:
            if account_id not in self.accounts and len(self.accounts) >= MAX_ACCOUNTS:
                self._forget(now)
                if len(self.accounts) >= MAX_ACCOUNTS:
                    return
            self.accounts[str(account_id)] = now

    def sign_in(self, accepted: bool):
        now = self.clock()
        with self.lock:
            (self.sign_ins if accepted else self.failed).append(now)
            self._forget(now)

    def metrics(self, *, terminal_sessions=None) -> list:
        now = self.clock()
        with self.lock:
            self._forget(now)
            active = sum(at >= now - WINDOW_SEC for at in self.accounts.values())
            values = [('plaza_usage_active_accounts', active), ('plaza_usage_sign_ins_hour', len(self.sign_ins)),
                      ('plaza_usage_failed_sign_ins_hour', len(self.failed))]
        if terminal_sessions is not None:
            values.append(('plaza_usage_terminal_sessions', terminal_sessions))
        return [{'name': name, 'value': value, 'unit': 'count', 'kind': 'gauge', 'labels': dict(OWNER)}
                for name, value in values]


def live_terminal_sessions(client_sessions, now=None) -> int:
    """How many Terminal sessions have live access now; 0 when the session store cannot be read."""
    now = time.time() if now is None else now
    try:
        db = client_sessions.connect()
        try:
            return int(db.execute('SELECT COUNT(*) FROM client_sessions WHERE expires>? AND access_expires>?',
                                  (now, now)).fetchone()[0])
        finally:
            db.close()
    except Exception:
        return 0
