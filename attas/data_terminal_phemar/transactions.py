"""Read-only, owner-scoped view of the Plaza ledger (not local billing estimates)."""

# OBSOLETE BUSINESS IMPLEMENTATION — TO BE REMOVED AFTER OWNER CUTOVER.
# Owner: portfolio. Do not extend this legacy Terminal implementation.
# See BUSINESS_LOGIC_OBSOLETE.json for replacements and retirement gates.
import asyncio
import time
from collections import defaultdict

import httpx
from fastapi import HTTPException

LIMIT = 5000
# Each kind of Plaza ledger entry has its own name, which the page shows in the Terminal's language.
LABELS = {
    'grant': 'Sign-up points',
    'top_up': 'Top-up',
    'adjust': 'Points adjustment',
    'owner_account_transfer_out': 'Owner account transfer out',
    'owner_account_transfer_in': 'Owner account transfer in',
    'report_escrow_reserve': 'Reservation',
    'report_escrow_capture': 'Reservation settlement',
    'report_escrow_refund': 'Reservation refund',
    'report_quote_charge': 'Provider payment (quote)',
    'scope_payment_charge': 'Provider payment (completed job)',
    'report_quote_earn': 'Provider earnings (quote)',
    'scope_payment_earn': 'Provider earnings (completed job)',
    'report_generation_charge': 'Report payment',
    'report_generation_earn': 'Report earnings',
    'remote_practice_charge': 'Agent call payment',
    'remote_practice_earn': 'Agent call earnings',
}
# Plaza's monthly top-up is a top-up whose source is "monthly".
MONTHLY_TOP_UP = 'Monthly top-up'
# Where an entry came from, as Plaza records it, named for the page; anything else shows as recorded.
SOURCES = {
    'signup': 'Sign-up',
    'monthly': 'Monthly',
    'admin': 'Admin',
    'report_escrow': 'Reservation',
    'remote_practice': 'Agent call',
}


def entry_kind(action, source):
    """The type filter's kind: the monthly top-up is listed by its own name, apart from other top-ups."""
    return 'top_up:monthly' if action == 'top_up' and source == 'monthly' else action


def entry_label(action, source):
    if action == 'top_up' and source == 'monthly':
        return MONTHLY_TOP_UP
    return LABELS.get(action, action.replace('_', ' ').capitalize())
PAYMENTS = {'report_quote_charge', 'scope_payment_charge'}
# Plaza names an execution's reservation, settlement and refund after the Terminal that reserved it (the controller),
# not after the agent that was paid; the agent column never shows that name.
ESCROW = {'report_escrow_reserve', 'report_escrow_capture', 'report_escrow_refund'}
# Entries that no agent took part in: they are not executions, and their agent column stays empty.
NO_AGENT = {'grant', 'top_up', 'adjust', 'owner_account_transfer_out', 'owner_account_transfer_in'}


def agent_names(rows, names):
    """The agents these entries paid or earned from: each by its name in the Plaza directory, else the name Plaza
    recorded. A reservation's own agent is the Terminal that reserved it, so only its quote's agent counts."""
    found = []
    for row in rows:
        parties = [(p.get('agent_id'), p.get('agent_name')) for p in row['payees']]
        if row['action'] not in ESCROW:
            parties.append((row['agent_id'], row['agent_name']))
        for agent_id, recorded in parties:
            name = names.get(agent_id) or recorded or ''
            if name and name not in found:
                found.append(name)
    return found


def agent_column(rows, names):
    """What the agent column shows: agent names, else the operation's name; `involvesAgent` tells the page whether
    an empty name is an unlisted agent or an entry no agent took part in. Never the entry type."""
    found = agent_names(rows, names)
    operation = next((r['operationLabel'] or r['pulse'] for r in rows if r['operationLabel'] or r['pulse']), '')
    return {'agentLabel': ', '.join(found)[:200] or operation, 'involvesAgent': any(r['action'] not in NO_AGENT for r in rows)}


def ledger_view(payload, owner, plaza, own_agent='', names=None):
    """`own_agent` is this Terminal's registration for the account, which reserves its executions; `names` maps
    agent ids to their names in the Plaza directory."""
    names = names if isinstance(names, dict) else {}
    profile = payload.get('user') or {}
    if str(profile.get('id') or '') != owner:
        raise HTTPException(502, 'Plaza returned a different account. Transaction history was withheld.')
    history = payload.get('history')
    if not isinstance(history, list):
        raise HTTPException(502, 'Plaza did not return transaction history.')
    rows, seen = [], set()
    for raw in history[:LIMIT]:
        if not isinstance(raw, dict) or str(raw.get('user_id') or '') != owner:
            raise HTTPException(502, 'Plaza returned an unexpected ledger owner. Transaction history was withheld.')
        if not raw.get('id') or raw['id'] in seen:
            continue
        seen.add(raw['id'])
        # Never forward arbitrary metadata, credentials, email addresses or tokens.
        meta = raw.get('metadata') if isinstance(raw.get('metadata'), dict) else {}
        lines = meta.get('quotes') or meta.get('breakdown') or []
        if not isinstance(lines, list):
            lines = []
        parties = []
        for line in [meta, *lines]:
            if not isinstance(line, dict) or not line.get('provider_user_id'):
                continue
            party = {k: str(line.get(k) or '') for k in ('provider_user_id', 'provider_username', 'agent_id', 'agent_name', 'pulse_name')}
            party['sameAccount'] = party['provider_user_id'] == owner
            if party not in parties:
                parties.append(party)
        row = {k: str(raw.get(k) or '') for k in ('id', 'action', 'reason', 'source', 'request_id', 'practice_id', 'agent_id', 'agent_name', 'created_at', 'storage')}
        for key in ('delta', 'previous_credit_points', 'credit_points'):
            value = raw.get(key)
            if type(value) is not int:
                raise HTTPException(502, 'Plaza returned an invalid ledger amount.')
            row[key] = value
        row.update(label=entry_label(row['action'], row['source']), kind=entry_kind(row['action'], row['source']),
                   sourceLabel=SOURCES.get(row['source'], row['source']),
                   escrowId=str(meta.get('escrow_id') or ''),
                   pulse=str(meta.get('pulse_name') or ''), payees=parties,
                   # The name the provider's quote gave the operation it priced; the page shows it in place of the pulse.
                   operationLabel=str(meta.get('quote_label') or '')[:200],
                   counterparty=str(meta.get('counterparty_username') or meta.get('provider_username') or ''),
                   executionId=str(meta.get('execution_id') or ''),
                   # Who reserved an execution's points: this Terminal, or another Terminal of the same account.
                   reservedBy=('this' if own_agent and row['agent_id'] == own_agent else 'other') if row['action'] in ESCROW else '')
        row.update(agent_column([row], names))
        rows.append(row)
    rows.sort(key=lambda row: row['created_at'], reverse=True)
    actions, providers = {}, {}
    for row in rows:
        # The type filter lists each kind once by the name the list shows; its value is the kind.
        action = actions.setdefault(row['kind'], {'action': row['kind'], 'label': row['label'], 'count': 0, 'net': 0})
        action['count'] += 1
        action['net'] += row['delta']
        if row['action'] in PAYMENTS:
            party = next(iter(row['payees']), {})
            key = (row['agent_id'], party.get('provider_user_id', ''))
            provider = providers.setdefault(key, {'agent': names.get(row['agent_id']) or row['agent_name'] or '', 'payee': party.get('provider_username') or 'Not recorded', 'sameAccount': party.get('sameAccount'), 'calls': 0, 'points': 0})
            provider['calls'] += 1
            provider['points'] -= row['delta']
    groups = defaultdict(list)
    for row in rows:
        groups[row['escrowId'] or row['request_id'] or row['id']].append(row)
    executions = []
    for key, items in groups.items():
        actions_present = {r['action'] for r in items}
        payees = []
        for item in items:
            for party in item['payees']:
                if party not in payees:
                    payees.append(party)
        status = ('Refund recorded' if 'report_escrow_refund' in actions_present else
                  'Settlement recorded' if 'report_escrow_capture' in actions_present else
                  'No settlement in returned history' if 'report_escrow_reserve' in actions_present else
                  'Ledger entry')
        executions.append({'id': key, 'createdAt': items[0]['created_at'], 'net': sum(r['delta'] for r in items), 'status': status, 'payees': payees, 'entries': items,
                           # A sign-up grant, a top-up or a transfer is an entry of its own, not an execution.
                           'execution': any(r['escrowId'] or r['executionId'] or r['action'] not in NO_AGENT for r in items),
                           **agent_column(items, names)})
    current = profile.get('credit_points')
    if type(current) is not int:
        raise HTTPException(502, 'Plaza did not return the account balance.')
    net = sum(r['delta'] for r in rows)
    opening = rows[-1]['previous_credit_points'] if rows else current
    closing = rows[0]['credit_points'] if rows else current
    return {'account': {'id': owner, 'name': profile.get('display_name') or profile.get('username') or owner,
                        'username': profile.get('username') or '', 'balance': current, 'plaza': plaza},
            'rows': rows, 'executions': executions, 'actions': list(actions.values()),
            'providers': sorted(providers.values(), key=lambda p: p['points'], reverse=True),
            'summary': {'count': len(rows), 'opening': opening, 'closing': closing, 'net': net,
                        'credits': sum(max(0, r['delta']) for r in rows), 'debits': sum(max(0, -r['delta']) for r in rows),
                        'from': rows[-1]['created_at'] if rows else None, 'to': rows[0]['created_at'] if rows else None,
                        'balanced': opening + net == closing, 'balanceChanged': current != closing,
                        'truncated': len(history) > LIMIT, 'limit': LIMIT}, 'retrievedAt': time.time()}


def own_agent(network):
    """This Terminal's registration for the window's account: the controller Plaza names its reservations after."""
    try:
        return str(getattr(network.registration, 'agent_id', '') or '')
    except HTTPException:
        return ''  # an account that has not approved this Terminal reserves nothing through it


async def directory_names(network, user):
    """Agent names from the Terminal's Plaza directory, so an entry Plaza recorded without a name still shows one.
    The history never waits long for it, and shows the recorded names without it."""
    try:
        agents = await asyncio.wait_for(network.directory(user.get('token', '')), 10)
        return {str(a['id']): str(a['name']) for a in agents if isinstance(a, dict) and a.get('id') and a.get('name')}
    except Exception:  # naming is a convenience: a directory that refuses or fails never withholds the history
        return {}


async def account_transactions(network, user):
    try:
        names = asyncio.ensure_future(directory_names(network, user))
        try:
            response = await network.client.get(network.plaza + '/api/ui_auth/credits/history',
                headers={'Authorization': 'Bearer ' + user['token']}, params={'limit': LIMIT + 1}, timeout=45)
            if response.status_code in (401, 403):
                raise HTTPException(401, 'Your Plaza session expired. Sign in to view transaction history.')
            if not response.is_success:
                raise HTTPException(502, 'Plaza transaction history is temporarily unavailable. No balance was changed.')
            payload = response.json()
        except BaseException:
            names.cancel()
            raise
        return ledger_view(payload, user['id'], network.plaza, own_agent(network), await names)
    except (httpx.RequestError, ValueError):
        raise HTTPException(502, 'Plaza transaction history is temporarily unavailable. No balance was changed.') from None
