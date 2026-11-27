"""Role-based access to agents' operations, decided and stored by Plaza (Alvin, 2026-11-13).

Like IAM groups and the policies a service ships:

- A role is a named set of Plaza accounts. It belongs to the account that created it; that account adds members.
- An agent declares permission groups in its registration card (``meta.permission_groups``): named sets of its own
  operations, each a pulse name, practice id or API path, exactly as a call grant names the operation.
- The agent's owner, the account Plaza recorded when the agent registered, attaches its own roles to those groups.

An operation listed in any of the agent's groups is role-only: the agent's owner and the members of a role attached
to a group listing it may call it, and nobody else. A group may be declared open (Alvin 2026-11-24):
its operations stay open to everyone until the owner attaches a role to it, and are role-only from then on. An agent
lists open groups under ``meta.open_permission_groups``: a Plaza older than open groups reads only
``meta.permission_groups``, so there those operations simply stay open instead of becoming owner-only. Operations
no group lists, operations only unattached open groups list, and agents that declare no groups keep Plaza's other
rules. Every decision is Plaza's, made when it issues a call or operation grant and again when
the grant is used, so a change takes effect on the next call. Agents keep nothing.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException, Request
from fastapi.concurrency import run_in_threadpool

MAX_GROUPS = 50
MAX_OPERATIONS = 200
MAX_ROLES = 200
MAX_MEMBERS = 1000
GROUP_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._:-]{0,63}$')
# Control characters, and characters that hide or reorder text (zero-width marks, bidirectional controls).
CONTROL = re.compile('[\x00-\x1f\x7f​-‏‪-‮⁠-⁩﻿]')
OWNER = 'owner'
ROLE = 'role'
# Practices whose request body chooses the pulse they run (a Pulser's): the pulse is what a group names.
PULSE_DISPATCH = frozenset({'get_pulse_data', 'quote_pulse_data', 'quote_request'})
# What an unreadable declaration requires: a group nobody can attach a role to, so only the owner may call the agent.
INVALID = '(invalid declaration)'
# Where an agent's card lists its open groups (see the module docstring); ``"open": true`` in permission_groups also works.
OPEN_GROUPS = 'open_permission_groups'


def _text(value, limit):
    text = str(value or '').strip()
    if len(text) > limit or CONTROL.search(text):
        raise ValueError('Text is too long or holds control or invisible characters.')
    return text


def _declared(card) -> Any:
    """The card's groups as one list: its permission groups, then its open groups marked open."""
    card = card if isinstance(card, dict) else {}
    meta = card.get('meta') if isinstance(card.get('meta'), dict) else {}
    raw = meta.get('permission_groups', card.get('permission_groups'))
    opened = meta.get(OPEN_GROUPS, card.get(OPEN_GROUPS))
    if opened in (None, []):
        return raw
    if not isinstance(opened, list) or not isinstance(raw, (list, type(None))):
        return {'unreadable': True}  # fails normalize_groups: an invalid declaration, so the owner only
    return [*(raw or []), *({**group, 'open': True} if isinstance(group, dict) else group for group in opened)]


@lru_cache(maxsize=1024)
def _parsed(text: str):
    """A declaration's groups and its operation -> group names index, parsed once per distinct declaration."""
    groups = normalize_groups(json.loads(text))
    index: Dict[str, set] = {}
    for group in groups:
        for operation in group['operations']:
            index.setdefault(operation, set()).add(group['name'])
    return tuple((g['name'], g['description'], tuple(g['operations']), g['open']) for g in groups), \
        {operation: frozenset(names) for operation, names in index.items()}


def declaration(card):
    """(groups, index, valid) for an agent's card. A declaration Plaza cannot read is invalid, not absent."""
    raw = _declared(card)
    if raw in (None, []):
        return [], {}, True
    try:
        groups, index = _parsed(json.dumps(raw, sort_keys=True))
    except (ValueError, TypeError):
        return [], {}, False
    return [{'name': n, 'description': d, 'operations': list(o), 'open': x} for n, d, o, x in groups], index, True


def permission_groups(card: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The permission groups an agent declares in its card, normalized; none when the declaration is invalid."""
    return declaration(card)[0]


def normalize_groups(raw: Any) -> List[Dict[str, Any]]:
    """Validate a permission-group declaration: [{name, description, operations: [...], open?}, ...].

    ``open`` (default false): the group's operations stay open to everyone until the owner attaches a role to it."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list) or len(raw) > MAX_GROUPS:
        raise ValueError(f'Declare at most {MAX_GROUPS} permission groups as a list.')
    groups, names = [], set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError('Each permission group is an object.')
        name = str(item.get('name') or '').strip()
        if not GROUP_NAME.match(name) or name.lower() in names:
            raise ValueError(f'Permission group names are unique, 1-64 letters, digits, spaces or ._:- ({name!r}).')
        operations = item.get('operations')
        if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
            raise ValueError(f'Permission group {name!r} lists 1-{MAX_OPERATIONS} operations.')
        ops = []
        for operation in operations:
            # A grant names a practice without its route prefix; a templated or wildcard entry would match nothing.
            text = _text(operation, 200).removeprefix('/use_practice/')
            if not text:
                raise ValueError(f'Permission group {name!r} lists an empty operation.')
            if any(mark in text for mark in '{}*'):
                raise ValueError(f'Permission group {name!r} lists {text!r}: name exact operations, without templates or wildcards.')
            if text not in ops:
                ops.append(text)
        if item.get('open', False) not in (True, False):
            raise ValueError(f'Permission group {name!r}: open is true or false.')
        names.add(name.lower())
        groups.append({'name': name, 'description': _text(item.get('description'), 300), 'operations': ops,
                       'open': item.get('open', False) is True})
    return groups


def _pulses(card) -> List[Dict[str, Any]]:
    card = card if isinstance(card, dict) else {}
    meta = card.get('meta') if isinstance(card.get('meta'), dict) else {}
    pulses = meta.get('supported_pulses') or card.get('supported_pulses') or []
    return [p for p in pulses if isinstance(p, dict)] if isinstance(pulses, list) else []


def _pulse_keys(pulse) -> set:
    """Every way a caller may name this pulse: its name, pulse name, id, aliases and address."""
    keys = {str(pulse.get(k) or '').strip() for k in ('name', 'pulse_name', 'id', 'pulse_address')}
    keys |= {str(alias).strip() for alias in (pulse.get('aliases') or []) if isinstance(pulse.get('aliases'), list)}
    return {key for key in keys if key}


def canonical_operations(card, operation) -> set:
    """The names Plaza checks for one requested operation: the name as given (without a route prefix), every declared
    name of each pulse it can resolve to on this agent (by name, id, alias or address, ignoring case and spaces, as the
    agent may resolve it), and any grouped entry it equals ignoring case."""
    op = str(operation or '').strip().removeprefix('/use_practice/')
    if not op:
        return set()
    folded = op.casefold()
    names = {op}
    for pulse in _pulses(card):
        keys = _pulse_keys(pulse)
        if folded in {key.casefold() for key in keys}:
            names |= {str(pulse.get(k) or '').strip() for k in ('name', 'pulse_name')} - {''}
    names |= {entry for entry in declaration(card)[1] if entry.casefold() == folded}
    return names


def requirements(card, operation) -> List[frozenset]:
    """What calling `operation` on this agent needs: a list of group sets, each met by a role attached to any group in
    it. Empty when no group covers the operation (Plaza's other rules apply)."""
    groups, index, valid = declaration(card)
    if not valid:
        return [frozenset({INVALID})]  # Fail closed: the owner only, until the agent declares groups Plaza can read.
    op = str(operation or '').strip().removeprefix('/use_practice/')
    if not groups or not op:
        return []
    needs = []
    if op in PULSE_DISPATCH:
        # A call that names no pulse lets the request body choose one: every grouped pulse of the agent must be allowed.
        for pulse in _pulses(card):
            covering = frozenset().union(*(index.get(key, frozenset()) for key in _pulse_keys(pulse)))
            if covering:
                needs.append(covering)
    covering = frozenset().union(*(index.get(name, frozenset()) for name in canonical_operations(card, op)))
    if covering:
        needs.append(covering)
    return needs


def covering_groups(card, operation: str) -> List[str]:
    """Names of the agent's groups that cover this operation (a pulse name, practice id or API path)."""
    return sorted(set().union(*requirements(card, operation))) if requirements(card, operation) else []


class AccessRoles:
    """Plaza's role store: roles, their members, and which roles an agent's owner attached to its groups."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS access_roles(id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, '
                       "description TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL, UNIQUE(owner, name))")
            db.execute('CREATE TABLE IF NOT EXISTS access_role_members(role TEXT NOT NULL, account TEXT NOT NULL, '
                       'added_by TEXT NOT NULL, added REAL NOT NULL, PRIMARY KEY(role, account))')
            db.execute('CREATE INDEX IF NOT EXISTS access_role_members_account ON access_role_members(account)')
            db.execute('CREATE TABLE IF NOT EXISTS access_attachments(agent TEXT NOT NULL, grp TEXT NOT NULL, role TEXT NOT NULL, '
                       'attached_by TEXT NOT NULL, attached REAL NOT NULL, PRIMARY KEY(agent, grp, role))')
            db.execute('CREATE INDEX IF NOT EXISTS access_attachments_role ON access_attachments(role)')
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        """One transaction on a connection that is always closed."""
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    # --- roles -------------------------------------------------------------------------------------------------
    def _role(self, db, role_id, owner):
        row = db.execute('SELECT id, owner, name, description, created, updated FROM access_roles WHERE id=?', (role_id,)).fetchone()
        if not row or row[1] != owner:
            raise HTTPException(404, 'That role is not one of yours, or it was deleted.')
        return dict(zip(('id', 'owner', 'name', 'description', 'created', 'updated'), row))

    def create_role(self, owner, name, description=''):
        name, description = _text(name, 64), _text(description, 300)
        if not name:
            raise HTTPException(422, 'Name the role.')
        role = {'id': 'role-' + uuid.uuid4().hex, 'owner': owner, 'name': name, 'description': description,
                'created': time.time(), 'updated': time.time()}
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT COUNT(*) FROM access_roles WHERE owner=?', (owner,)).fetchone()[0] >= MAX_ROLES:
                raise HTTPException(409, f'An account keeps at most {MAX_ROLES} roles.')
            try:
                db.execute('INSERT INTO access_roles VALUES(?,?,?,?,?,?)', tuple(role.values()))
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'You already have a role with that name.') from None
        return role

    def update_role(self, owner, role_id, *, name=None, description=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            role = self._role(db, role_id, owner)
            if name is not None:
                role['name'] = _text(name, 64)
                if not role['name']:
                    raise HTTPException(422, 'Name the role.')
            if description is not None:
                role['description'] = _text(description, 300)
            role['updated'] = time.time()
            try:
                db.execute('UPDATE access_roles SET name=?, description=?, updated=? WHERE id=?',
                           (role['name'], role['description'], role['updated'], role_id))
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'You already have a role with that name.') from None
        return role

    def delete_role(self, owner, role_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._role(db, role_id, owner)
            for table in ('access_role_members', 'access_attachments'):
                db.execute(f'DELETE FROM {table} WHERE role=?', (role_id,))
            db.execute('DELETE FROM access_roles WHERE id=?', (role_id,))

    def roles_of(self, owner) -> List[Dict[str, Any]]:
        with self.connect() as db:
            roles = [dict(zip(('id', 'owner', 'name', 'description', 'created', 'updated'), row)) for row in db.execute(
                'SELECT id, owner, name, description, created, updated FROM access_roles WHERE owner=? ORDER BY name', (owner,))]
            for role in roles:
                role['members'] = [row[0] for row in db.execute(
                    'SELECT account FROM access_role_members WHERE role=? ORDER BY added', (role['id'],))]
                role['attachments'] = [{'agent': row[0], 'group': row[1]} for row in db.execute(
                    'SELECT agent, grp FROM access_attachments WHERE role=? ORDER BY agent, grp', (role['id'],))]
        return roles

    def add_member(self, owner, role_id, account):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._role(db, role_id, owner)
            if db.execute('SELECT 1 FROM access_role_members WHERE role=? AND account=?', (role_id, account)).fetchone():
                return  # already a member, whatever the count
            if db.execute('SELECT COUNT(*) FROM access_role_members WHERE role=?', (role_id,)).fetchone()[0] >= MAX_MEMBERS:
                raise HTTPException(409, f'A role holds at most {MAX_MEMBERS} accounts.')
            db.execute('INSERT INTO access_role_members VALUES(?,?,?,?)', (role_id, account, owner, time.time()))

    def leave(self, account, role_id):
        """A member leaves a role someone else put it in; True when it was a member."""
        with self.connect() as db:
            return db.execute('DELETE FROM access_role_members WHERE role=? AND account=?', (role_id, account)).rowcount > 0

    def remove_member(self, owner, role_id, account):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._role(db, role_id, owner)
            db.execute('DELETE FROM access_role_members WHERE role=? AND account=?', (role_id, account))

    def membership(self, role_id, account) -> Optional[Dict[str, Any]]:
        """One account's relation to one role: whether it is a member; None when no such role exists."""
        with self.connect() as db:
            row = db.execute('SELECT owner, name FROM access_roles WHERE id=?', (role_id,)).fetchone()
            if not row:
                return None
            member = bool(db.execute('SELECT 1 FROM access_role_members WHERE role=? AND account=?', (role_id, account)).fetchone())
        return {'owner': row[0], 'name': row[1], 'member': member}

    def memberships(self, account) -> List[Dict[str, Any]]:
        """The roles an account belongs to, with the agent groups each one opens."""
        with self.connect() as db:
            rows = db.execute('SELECT r.id, r.owner, r.name, r.description FROM access_roles r JOIN access_role_members m '
                              'ON m.role=r.id WHERE m.account=? ORDER BY r.name', (account,)).fetchall()
            result = []
            for role_id, owner, name, description in rows:
                attachments = [{'agent': a, 'group': g} for a, g in db.execute(
                    'SELECT agent, grp FROM access_attachments WHERE role=? ORDER BY agent, grp', (role_id,))]
                result.append({'id': role_id, 'owner': owner, 'name': name, 'description': description, 'attachments': attachments})
        return result

    # --- attachments ---------------------------------------------------------------------------------------------
    def attach(self, owner, agent, group, role_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._role(db, role_id, owner)
            db.execute('INSERT OR IGNORE INTO access_attachments VALUES(?,?,?,?,?)', (agent, group, role_id, owner, time.time()))

    def detach(self, owner, agent, group, role_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._role(db, role_id, owner)
            db.execute('DELETE FROM access_attachments WHERE agent=? AND grp=? AND role=?', (agent, group, role_id))

    def attachments(self, agent, owner) -> Dict[str, List[Dict[str, Any]]]:
        """{group: [role]} for roles the agent's current owner attached; a previous owner's attachments do not count."""
        with self.connect() as db:
            rows = db.execute('SELECT a.grp, r.id, r.name FROM access_attachments a JOIN access_roles r ON r.id=a.role '
                              'WHERE a.agent=? AND r.owner=? ORDER BY a.grp, r.name', (agent, owner)).fetchall()
        result: Dict[str, List[Dict[str, Any]]] = {}
        for group, role_id, name in rows:
            result.setdefault(group, []).append({'id': role_id, 'name': name})
        return result

    def attached(self, agent, groups: Iterable[str], owner) -> bool:
        """Whether the agent's current owner attached any role to one of these groups."""
        groups = list(groups)
        if not groups or not owner:
            return False
        marks = ','.join('?' * len(groups))
        with self.connect() as db:
            row = db.execute(f'SELECT 1 FROM access_attachments a JOIN access_roles r ON r.id=a.role AND r.owner=? '
                             f'WHERE a.agent=? AND a.grp IN ({marks}) LIMIT 1', (owner, agent, *groups)).fetchone()
        return bool(row)

    def allowed(self, account, agent, groups: Iterable[str], owner) -> bool:
        """Whether the account is in a role the agent's current owner attached to one of these groups."""
        groups = list(groups)
        if not account or not groups or not owner:
            return False
        marks = ','.join('?' * len(groups))
        with self.connect() as db:
            row = db.execute(f'SELECT 1 FROM access_attachments a JOIN access_roles r ON r.id=a.role AND r.owner=? '
                             f'JOIN access_role_members m ON m.role=a.role WHERE a.agent=? AND m.account=? AND a.grp IN ({marks}) LIMIT 1',
                             (owner, agent, account, *groups)).fetchone()
        return bool(row)


# --- Plaza's decision ----------------------------------------------------------------------------------------------
def recorded_owner(plaza, agent_id) -> str:
    """The owner Plaza recorded for the agent's authenticated registration; never the card's own claim."""
    from .registered_owners import verified_owner
    state = plaza._get_plaza_practice().state
    card = state.agent_cards.get(agent_id) or {}
    try:
        owner = verified_owner(plaza, {'agent_id': agent_id, 'card': card})
    except Exception:  # an agent without a live registration has no verified owner
        owner = None
    if not owner:
        owner = plaza._registered_agent_owners().owner_of(agent_id)
    return str(owner or '')


def decide(plaza, user_id, agent_id, operation, *, actor=None):
    """None when no permission group of the agent covers the operation, or only open groups no role is attached to
    (Plaza's other rules apply); 'owner' or 'role' when the call may run; False when the operation is role-only and it
    may not.

    The account is the call's user. A call with no user is its calling agent's own: the owner's agents call each other's
    role-only operations as the owner, as same-owner agents connect automatically; any other agent with no user is refused.
    """
    store = getattr(plaza, 'access_roles', None)
    if store is None or not agent_id:
        return None
    practice = plaza._get_plaza_practice()
    state = getattr(practice, 'state', None)
    if state is None:
        return None
    card = state.agent_cards.get(agent_id) or {}
    needs = requirements(card, operation)
    if not needs:
        return None
    owner = recorded_owner(plaza, agent_id)
    # A need met only by open groups no role is attached to yet asks nothing: those operations stay open to everyone.
    opened = {group['name'] for group in declaration(card)[0] if group['open']}
    if opened:
        needs = [need for need in needs if not (need <= opened and not store.attached(agent_id, need, owner))]
        if not needs:
            return None
    user_id = str(user_id or '')
    if owner and user_id == owner:
        return OWNER
    if not user_id:
        return OWNER if owner and actor and recorded_owner(plaza, actor) == owner else False
    if any(INVALID in need for need in needs):
        return False
    return ROLE if all(store.allowed(user_id, agent_id, need, owner) for need in needs) else False


def decide_all(plaza, user_id, agent_id, operations, *, actor=None):
    """False when any of these names of one call is refused; else what the strictest of them allows."""
    results = [decide(plaza, user_id, agent_id, operation, actor=actor) for operation in dict.fromkeys(o for o in operations if o)]
    if any(result is False for result in results):
        return False
    return ROLE if ROLE in results else (OWNER if OWNER in results else None)


DENIED = 'Your account is not in a role this agent\'s owner allows for that operation.'
# The token another Plaza presents for a link an account approved here (access_links.py).
LINK_PREFIX = 'access-link-'


# --- routes ------------------------------------------------------------------------------------------------------
def install_access_roles(plaza):
    store = AccessRoles(plaza._client_sessions().path.with_name('access-roles.sqlite'))
    plaza.access_roles = store

    def account(request: Request, linked: bool = True) -> Dict[str, Any]:
        """The signed-in account, from its own Plaza session, or from a user's call grant an operator agent presents.

        On the role routes (`linked`), also the account that approved a link another Plaza presents (access_links.py);
        a link never manages links, so it can't be passed on to a third Plaza.
        """
        grant = request.headers.get('x-call-grant', '')
        if not grant:
            header = request.headers.get('authorization', '')
            token = header[7:].strip() if header.lower().startswith('bearer ') else ''
            if token.startswith(LINK_PREFIX):
                links = getattr(plaza, 'access_links', None)
                if not linked:
                    raise HTTPException(403, 'A link from another Plaza manages roles only.')
                account_id = links.resolve(token) if links is not None else None
                profile = plaza._get_ui_user(account_id, include_preferences_fallback=False, include_credit_ledger=False) if account_id else None
                if not profile or not plaza._ui_user_status_is_active(profile):
                    raise HTTPException(401, 'This link expired or was revoked.')
                return profile
            return plaza._require_ui_user(request)
        from fastapi.security import HTTPAuthorizationCredentials
        from .approved_access import approval_owner
        state = plaza._get_plaza_practice().state
        try:
            actor = state.verify_token(HTTPAuthorizationCredentials(scheme='Bearer', credentials=plaza._extract_bearer_token(request)))
            value = plaza.call_grants.read(grant, include_consumed=True)
        except (HTTPException, PermissionError, KeyError):
            raise HTTPException(401, 'Call grant expired or revoked.') from None
        user_id = str((value.get('user') or {}).get('id') or '')
        actor_owner = recorded_owner(plaza, actor['agent_id'])
        # The Plaza operator, named as Plaza's observability routes name it.
        operator = str(os.environ.get('PROMPITS_AGENT_TRUST_OWNER_ID') or os.environ.get('PROMPITS_CLIENT_ENROLLMENT_OWNER_ID')
                       or ((getattr(plaza, 'raw_config', {}) or {}).get('plaza_owner_account') or {}).get('user_id')
                       or approval_owner(plaza) or '')
        # Only an agent the account itself or the Plaza operator runs may manage roles for the account it serves.
        if value.get('audience') != actor['agent_id'] or value.get('authority') or not user_id or not actor_owner \
                or actor_owner not in (user_id, operator):
            raise HTTPException(403, 'This agent cannot manage roles for that account.')
        # And only with a grant the account gave it for role management: an operation the agent declares as such
        # (card meta.access_management_operations). Any other grant to it, for any other call, manages nothing.
        card = state.agent_cards.get(actor['agent_id']) or {}
        declared = (card.get('meta') or {}).get('access_management_operations') if isinstance(card.get('meta'), dict) else None
        if not isinstance(declared, list) or str(value.get('operation') or '') not in {str(o) for o in declared}:
            raise HTTPException(403, 'This grant was not given for managing roles.')
        profile = plaza._get_ui_user(user_id, include_preferences_fallback=False, include_credit_ledger=False)
        if not profile or not plaza._ui_user_status_is_active(profile):
            raise HTTPException(401, 'This account is disabled.')
        return profile

    def person(account_id):
        profile = plaza._get_ui_user(account_id, include_preferences_fallback=False, include_credit_ledger=False) or {}
        return {'id': account_id, 'username': profile.get('username') or '', 'display_name': profile.get('display_name') or ''}

    def find_account(value) -> Dict[str, Any]:
        """One account named exactly by its id, username or email; nothing is listed or searched."""
        text = str(value or '').strip()
        if not text or len(text) > 320:
            raise HTTPException(422, 'Name the account by its exact username, email or id.')
        found = plaza._get_ui_user(text, include_preferences_fallback=False, include_credit_ledger=False)
        if not found and '@' in text:
            found = plaza._find_ui_user_by_email(text)
        if not found:
            found = plaza._find_ui_user_by_username(text)
        if not found or not plaza._ui_user_status_is_active(found):
            raise HTTPException(404, 'No active Plaza account has that exact username, email or id.')
        return found

    def owned_agent(owner, agent_id):
        state = plaza._get_plaza_practice().state
        card = state.agent_cards.get(agent_id)
        if not card or recorded_owner(plaza, agent_id) != owner:
            raise HTTPException(404, 'That agent is not one you own.')
        return card

    async def body(request: Request) -> Dict[str, Any]:
        if len(await request.body()) > 16384:
            raise HTTPException(413, 'Request is too large.')
        try:
            value = await request.json()
        except ValueError:
            raise HTTPException(422, 'Send a JSON object.') from None
        if not isinstance(value, dict):
            raise HTTPException(422, 'Send a JSON object.')
        return value

    def sync(function):
        async def run(*args):
            try:
                return await run_in_threadpool(function, *args)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
        return run

    def roles_view(owner):
        roles = store.roles_of(owner)
        state = plaza._get_plaza_practice().state
        for role in roles:
            role['members'] = [person(member) for member in role['members']]
            for item in role['attachments']:
                item['agent_name'] = str((state.agent_cards.get(item['agent']) or {}).get('name') or '')
        return {'roles': roles}

    @plaza.app.get('/api/access/roles')
    async def list_roles(request: Request):
        return await sync(lambda: roles_view(account(request)['id']))()

    @plaza.app.post('/api/access/roles')
    async def create_role(request: Request):
        data = await body(request)
        return await sync(lambda: store.create_role(account(request)['id'], data.get('name'), data.get('description', '')))()

    @plaza.app.patch('/api/access/roles/{role_id}')
    async def update_role(role_id: str, request: Request):
        data = await body(request)
        return await sync(lambda: store.update_role(account(request)['id'], role_id, name=data.get('name'),
                                                    description=data.get('description')))()

    @plaza.app.delete('/api/access/roles/{role_id}')
    async def delete_role(role_id: str, request: Request):
        await sync(lambda: store.delete_role(account(request)['id'], role_id))()
        return {'deleted': role_id}

    @plaza.app.post('/api/access/roles/{role_id}/members')
    async def add_member(role_id: str, request: Request):
        data = await body(request)

        def run():
            owner = account(request)['id']
            member = find_account(data.get('account'))
            store.add_member(owner, role_id, str(member['id']))
            # Only that it worked: the role's member list, which its owner reads, names the people in it.
            return {'added': True}
        return await sync(run)()

    @plaza.app.delete('/api/access/roles/{role_id}/members/{account_id}')
    async def remove_member(role_id: str, account_id: str, request: Request):
        await sync(lambda: store.remove_member(account(request)['id'], role_id, account_id))()
        return {'removed': account_id}

    @plaza.app.get('/api/access/agents')
    async def list_agents(request: Request):
        """The agents this account owns, the permission groups each declares and the roles attached to them."""
        def run():
            owner = account(request)['id']
            state = plaza._get_plaza_practice().state
            agents = []
            for agent_id in sorted(set(plaza._registered_agent_owners().agents_of(owner))):
                card = state.agent_cards.get(agent_id)
                if not card or recorded_owner(plaza, agent_id) != owner:
                    continue
                attached = store.attachments(agent_id, owner)
                declared, _, valid = declaration(card)
                groups = [{**group, 'roles': attached.get(group['name'], [])} for group in declared]
                # An unreadable declaration leaves the agent to its owner only; say so rather than show no groups.
                agents.append({'agent_id': agent_id, 'name': str(card.get('name') or ''), 'groups': groups,
                               'invalid_declaration': not valid})
            return {'agents': sorted(agents, key=lambda agent: (agent['name'].lower(), agent['agent_id']))}
        return await sync(run)()

    @plaza.app.post('/api/access/agents/{agent_id}/groups/{group}/roles')
    async def attach_role(agent_id: str, group: str, request: Request):
        data = await body(request)

        def run():
            owner = account(request)['id']
            card = owned_agent(owner, agent_id)
            if group not in {g['name'] for g in permission_groups(card)}:
                raise HTTPException(404, 'The agent declares no permission group with that name.')
            store.attach(owner, agent_id, group, str(data.get('role_id') or ''))
            return {'agent_id': agent_id, 'group': group, 'roles': store.attachments(agent_id, owner).get(group, [])}
        return await sync(run)()

    @plaza.app.delete('/api/access/agents/{agent_id}/groups/{group}/roles/{role_id}')
    async def detach_role(agent_id: str, group: str, role_id: str, request: Request):
        def run():
            owner = account(request)['id']
            owned_agent(owner, agent_id)
            store.detach(owner, agent_id, group, role_id)
            return {'agent_id': agent_id, 'group': group, 'roles': store.attachments(agent_id, owner).get(group, [])}
        return await sync(run)()

    @plaza.app.post('/api/access/decide')
    async def decide_for_call(request: Request):
        """Whether the account an agent is serving may do one of that agent's own grouped operations which the agent
        checks itself, not through a call of its own (an App Consultant publishing a block to its site). The agent
        presents its own token and the call grant it is serving, and learns for that one account: owner, role, open (no
        group lists the operation: the agent's other rules apply) or denied. Nothing about roles or members."""
        data = await body(request)

        def run():
            from fastapi.security import HTTPAuthorizationCredentials
            state = plaza._get_plaza_practice().state
            try:
                actor = state.verify_token(HTTPAuthorizationCredentials(scheme='Bearer', credentials=plaza._extract_bearer_token(request)))
                value = plaza.call_grants.read(str(data.get('token') or ''), include_consumed=True)
            except (HTTPException, PermissionError, KeyError):
                raise HTTPException(401, 'Call grant expired or revoked.') from None
            if value.get('audience') != actor['agent_id']:
                raise HTTPException(403, 'An agent asks only about calls made to it.')
            operation = _text(data.get('operation'), 200)
            if not operation:
                raise ValueError('Name one operation.')
            account_id = str((value.get('user') or {}).get('id') or '')
            result = decide(plaza, account_id, actor['agent_id'], operation, actor=value.get('actor'))
            return {'account': account_id, 'operation': operation,
                    'decision': 'open' if result is None else 'denied' if result is False else result}
        return await sync(run)()

    @plaza.app.get('/api/access/roles/{role_id}/membership')
    async def role_membership(role_id: str, request: Request):
        """Whether the calling account owns or belongs to one role. An agent serving a viewer (its call grant) or an
        author learns this for that account only; nothing about the role's other members is ever returned. Agents
        that share their own resources with a role, such as an App Consultant sharing a Phema, check access this way."""
        def run():
            me = str(account(request)['id'])
            info = store.membership(role_id, me)
            if info is None:
                raise HTTPException(404, 'No such role.')
            if not info['member'] and info['owner'] != me:
                return {'role_id': role_id, 'member': False, 'owned': False}  # nothing about a role you are not in
            return {'role_id': role_id, 'name': info['name'], 'owner': person(info['owner']),
                    'member': info['member'], 'owned': info['owner'] == me}
        return await sync(run)()

    @plaza.app.get('/api/access/memberships')
    async def my_memberships(request: Request):
        """The roles this account is in, who owns each, and the agent groups each opens."""
        def run():
            state = plaza._get_plaza_practice().state
            roles = store.memberships(account(request)['id'])
            for role in roles:
                # Only what the role opens now: attachments its owner made to agents it still owns.
                role['attachments'] = [{**item, 'agent_name': str((state.agent_cards.get(item['agent']) or {}).get('name') or '')}
                                       for item in role['attachments'] if recorded_owner(plaza, item['agent']) == role['owner']]
                role['owner'] = person(role['owner'])
            return {'roles': roles}
        return await sync(run)()

    @plaza.app.delete('/api/access/memberships/{role_id}')
    async def leave_role(role_id: str, request: Request):
        """A member leaves a role another account put it in; nobody is kept in a role against its will."""
        def run():
            if not store.leave(str(account(request)['id']), role_id):
                raise HTTPException(404, 'You are not in that role.')
            return {'left': role_id}
        return await sync(run)()

    def named(account_id):
        value = person(account_id)
        return {'username': value['username'], 'display_name': value['display_name']}

    # Links to and from other Plazas (access_links.py, installed by Plaza) use the same sign-in and names.
    plaza.access_account, plaza.access_person = account, named
    return store

