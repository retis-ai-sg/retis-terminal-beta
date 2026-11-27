"""The agents a viewer may choose for a pulse (`{"$agents": {"pulse": …}}` in a Phema's controls).

Only agents that offer the pulse and that Plaza trusts for this viewer now (or programs on this computer) are listed,
at most 50, by name. Listing grants nothing: a reference that asks the chosen agent is checked again when it runs.
"""
import re

from fastapi import HTTPException, Request

PULSE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')
LIMIT = 50


def offering(rows, pulse):
    """[{agentId, name}] of the rows whose card offers `pulse`, by name."""
    found = {}
    for row in rows or []:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str):
            continue
        pulses = (row.get('meta') or {}).get('supported_pulses') or []
        names = {p.get('pulse_name') or p.get('name') for p in pulses if isinstance(p, dict)}
        if pulse in names:
            name = row.get('name') if isinstance(row.get('name'), str) and row['name'].strip() else row['id']
            found[row['id']] = {'agentId': row['id'], 'name': name.removesuffix(' (Persona)')[:120]}
    return sorted(found.values(), key=lambda row: row['name'].casefold())[:LIMIT]


def install_agent_choice_routes(app, principal, network):
    @app.get('/api/agent-choices')
    async def agent_choices(request: Request):
        user = await principal(request)
        pulse = request.query_params.get('pulse', '')
        if not PULSE.fullmatch(pulse):
            raise HTTPException(422, 'Name the pulse the agents offer.')
        return {'pulse': pulse, 'agents': offering(await network.trusted_agents(user.get('token', '')), pulse)}
