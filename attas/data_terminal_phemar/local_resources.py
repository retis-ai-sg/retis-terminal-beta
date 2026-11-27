"""This computer's local resources as Terminal settings show them: found by Bonjour, usable at once, no pairing."""
from fastapi import HTTPException, Request

# What a view says when the program on this computer that shows it is not answering. The window reads each in its
# language (web/failure-messages.js and ui-messages.tsv); change them together.
NAMED_NOT_ANSWERING = '{0} is not answering on this computer. Start it again in Retis MAS Manager.'
PROGRAM_NOT_ANSWERING = 'The program on this computer that shows this view is not answering. Start it again in Retis MAS Manager.'
MANAGER_NOT_ANSWERING = ('Retis MAS Manager is not answering on this computer. Try again in a few minutes; '
                         'if it still does not answer, restart the computer.')


def not_answering(network, publisher):
    """What to do when the program on this computer that shows a view is not answering (Bonjour no longer lists it).

    It names the program when this Terminal has seen it since it started. A component starts again in Retis MAS
    Manager. The manager announces itself again within minutes when this computer stops hearing it, and the desktop app
    starts it at login. Reopening the Terminal did not help on 2026-11-26: the programs had to start again."""
    clients = getattr(network, 'local_clients', None)
    known = clients.last_known(str(publisher).removeprefix('local-')) if clients else None
    if not known:
        return PROGRAM_NOT_ANSWERING
    if known.get('kind') == 'manager':
        return MANAGER_NOT_ANSWERING
    name = str(known.get('name') or '').strip()
    if not 1 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
        return PROGRAM_NOT_ANSWERING
    return NAMED_NOT_ANSWERING.replace('{0}', name, 1)


def forget_pairings(store):
    """Remove the pairing records an earlier Terminal kept: local resources no longer pair, so they mean nothing."""
    with store.connect() as db:
        db.execute("DELETE FROM documents WHERE kind='local-resource'")


def install_local_routes(app, network, principal, name, store=None):
    clients = network.local_clients
    if store is not None:
        forget_pairings(store)

    @app.get('/api/local-resources')
    async def resources(request: Request):
        await principal(request)
        return clients.resources()

    @app.post('/api/local-resources/scan')
    async def scan(request: Request):
        await principal(request)
        await clients.discovery.rescan()
        network.expiry = 0
        return clients.resources()

    @app.post('/api/local-resources/call')
    async def call(request: Request):
        await principal(request)
        body = await request.json()
        if not isinstance(body.get('parameters'), dict):raise HTTPException(422, 'Provide parameter values.')
        return await clients.call(body.get('resourceId'), body.get('operation'), body['parameters'])
