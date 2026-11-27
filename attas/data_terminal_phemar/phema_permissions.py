"""Who may see, open and change the parameters of this account's Phemas: Plaza's lists, shown and set from the New
Data Browser (Alvin, 2026-11-27; prompits/core/access_resources.py).

Generic container infrastructure: the Terminal passes the window's own Plaza session to Plaza and back, and keeps
nothing. Plaza checks that the account owns the Phema and the roles it chooses; the agents that keep the Phemas
enforce the lists.
"""
import httpx
from fastapi import HTTPException

RIGHTS = ('see', 'open', 'change')
MODES = ('everyone', 'owner', 'roles')


async def _plaza(network, user, method, path, body=None):
    try:
        response = await network.client.request(method, network.plaza + path, headers={'Authorization': 'Bearer ' + user['token']},
                                                json=body, timeout=30)
    except httpx.RequestError:
        raise HTTPException(502, 'Plaza is temporarily unavailable. Try again.') from None
    if response.status_code in (401, 403) and method == 'GET':
        raise HTTPException(401, 'Your Plaza session expired. Sign in again.')
    return response


async def lists(network, user):
    """This account's Phemas that agents keep, each with its three lists, and the account's own roles to choose from.
    `available` is false on a Plaza that keeps no such lists yet."""
    response = await _plaza(network, user, 'GET', '/api/access/resources')
    if response.status_code in (404, 405):
        return {'available': False, 'phemas': [], 'roles': []}
    if not response.is_success:
        raise HTTPException(502, 'Plaza is temporarily unavailable. Try again.')
    phemas = [{'agentId': str(row.get('agent_id') or ''), 'key': str(row.get('resource') or ''), 'name': str(row.get('name') or ''),
               'rights': {right: {'mode': (row.get('rights') or {}).get(right, {}).get('mode', 'everyone'),
                                  'roles': [{'id': str(r.get('id') or ''), 'name': str(r.get('name') or '')}
                                            for r in (row.get('rights') or {}).get(right, {}).get('roles') or []]}
                          for right in RIGHTS}}
              for row in (response.json() or {}).get('resources') or [] if row.get('kind') == 'phema']
    roles = await _plaza(network, user, 'GET', '/api/access/roles')
    mine = [{'id': str(r.get('id') or ''), 'name': str(r.get('name') or '')} for r in (roles.json() or {}).get('roles') or []] \
        if roles.is_success else []
    return {'available': True, 'phemas': phemas, 'roles': mine}


def _right(value):
    if not isinstance(value, dict) or value.get('mode') not in MODES:
        raise HTTPException(422, 'Choose everyone, only you, or roles for each list.')
    roles = value.get('roles') or []
    if not isinstance(roles, list) or len(roles) > 20 or not all(isinstance(r, str) and 0 < len(r) <= 64 for r in roles):
        raise HTTPException(422, 'Choose at most 20 roles for a list.')
    return {'mode': value['mode'], 'roles': roles}


async def save(network, user, value):
    """Set the three lists on one of the account's Phemas; Plaza answers with them as it keeps them."""
    if not isinstance(value, dict) or not isinstance(value.get('agentId'), str) or not isinstance(value.get('key'), str):
        raise HTTPException(422, 'Name the Phema by its agent and key.')
    body = {'agent_id': value['agentId'][:200], 'resource': value['key'][:200], **{right: _right(value.get(right)) for right in RIGHTS}}
    response = await _plaza(network, user, 'PUT', '/api/access/resources/rights', body)
    if response.status_code in (404, 422):
        detail = (response.json() or {}).get('detail') if response.headers.get('content-type', '').startswith('application/json') else None
        raise HTTPException(response.status_code, str(detail or 'Plaza refused these lists.'))
    if response.status_code in (401, 403):
        raise HTTPException(401, 'Your Plaza session expired. Sign in again.')
    if not response.is_success:
        raise HTTPException(502, 'Plaza is temporarily unavailable. Try again.')
    return {'rights': (response.json() or {}).get('rights') or {}}
