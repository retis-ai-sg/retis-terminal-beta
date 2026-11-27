"""Link groups: the latest value each group of linked panels holds, per value type, for one account on this Terminal.

The viewer puts panels in a group (a colour on each panel's title bar); a value one panel sends reaches the others in
that group (phemacast/core/ports.py). Windows in one browser pass values to each other directly; this record keeps
each group's latest values so a panel that joins a group, or a window opened later, starts from them. It is the
account's own state, kept only in its Terminal. Values are checked against their type and never carry credentials.
"""
import time

from fastapi import HTTPException, Request

from phemacast.core.ports import PortError, TYPES, check_value
from phemacast.core.controls import LINK_GROUPS, NAME

KIND = 'link-group'
GROUPS = LINK_GROUPS


def values(store, owner):
    """{group: {type: {name, value, at}}} for this account."""
    found = {}
    for row in store.list(owner, KIND):
        if row.get('id') in GROUPS and isinstance(row.get('types'), dict):
            found[row['id']] = row['types']
    return found


def put(store, owner, group, port_type, name, value):
    if group not in GROUPS:
        raise HTTPException(422, 'Choose one of the link groups.')
    if port_type not in TYPES:
        raise HTTPException(422, 'Unknown value type.')
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise HTTPException(422, 'Name the port the value came from.')
    try:
        value = check_value(port_type, value)
    except PortError as error:
        raise HTTPException(422, str(error)) from error
    try:
        current = store.get(owner, KIND, group)
    except HTTPException as error:
        if error.status_code != 404:
            raise
        current = {}
    types = dict(current.get('types') or {})
    types[port_type] = {'name': name, 'value': value, 'at': int(time.time() * 1000)}
    store.put(owner, KIND, group, {'types': types})
    return types[port_type]


def install_link_group_routes(app, store, principal):
    @app.get('/api/link-groups')
    async def link_groups(request: Request):
        user = await principal(request)
        return {'groups': values(store, user['id'])}

    @app.put('/api/link-groups/{group}')
    async def link_group_value(group: str, request: Request):
        user = await principal(request)
        body = await request.json()
        if not isinstance(body, dict) or set(body) != {'type', 'name', 'value'}:
            raise HTTPException(422, 'Send the value with its type and the port it came from.')
        return put(store, user['id'], group, body['type'], body['name'], body['value'])
