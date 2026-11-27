"""Answer a processor's data requests for this Terminal's user.

A processor never fetches market data. When it answers a call with a data
request (phemacast.core.data_requests), this Terminal fetches every item as the
user: with the user's own key straight from the vendor, mapped with the Data
Consultant's mappings, or from the source agent on the user's account. Then it
calls the processor again with the answers. Nothing here knows a processor's
business or a particular vendor.
"""
import asyncio
import logging
import re

import httpx
from fastapi import HTTPException

from phemacast.core.data_requests import (AGENTS, LIBRARY_BLOCKS, LLM_GENERATION, LOCAL_RESOURCES, MAX_ROUNDS, MODEL_DATA, SUPPLIED,
                                           answer, bounded, checked_request, is_request)

LOG = logging.getLogger(__name__)


def reason(error):
    detail = getattr(error, 'detail', None)
    return str(detail if isinstance(detail, str) else error)[:300] or type(error).__name__


async def source_data(network, store, user, agent_id, pulse, parameters):
    """One source call, for this user, from exactly the source the processor named: own key to the vendor, else
    that source on the user's account, or the user's own paired copy when that is what it named.

    A processor's source is one its user chose, so a source on Plaza is never swapped for the paired copy here
    (a layout's automatic panels do prefer the copy, content_references.py)."""
    from .source_keys import route, source_of
    from . import local_sources
    agent = await network.agent(agent_id, user['token'])
    await network.require_trusted(agent, user['token'])
    own = route(store, user, agent) if pulse == 'data_fetch' else None
    if own:
        from .direct_vendor import resolve_own_key
        result = await resolve_own_key(network, agent, user, parameters, own)
        connection = 'own'
    elif agent.get('localId'):
        # The user's own paired copy is called directly; Plaza never prices or pays a local resource.
        result = await local_sources.call(network, user, agent, pulse, parameters)
        connection = 'local'
    else:
        result = await network.execute(agent, pulse, parameters, user, store)
        connection = 'source'
    if not isinstance(result, dict) or result.get('status') in {'failed', 'error', 'unavailable', 'auth_required', 'credential_required'}:
        error = (result or {}).get('error') if isinstance(result, dict) else ''
        raise HTTPException(502, (agent.get('name') or agent_id) + ': ' + (error or 'the source did not provide the requested data.'))
    billing = result.pop('_billing', {}) if isinstance(result.get('_billing'), dict) else {}
    result.pop('_connection', None)
    canonical = result.get('canonical_result') if isinstance(result.get('canonical_result'), dict) else {}
    if parameters.get('target_model') and isinstance((result.get('canonical_data') or {}).get('items'), list):
        # A canonical model request is answered by its canonical rows; the source's raw rows and schemas stay here.
        result = {'status': result.get('status'), 'canonical_data': {'items': result['canonical_data']['items']},
                  'canonical_result': {k: canonical[k] for k in ('schema', 'modelRef', 'mappingRefs', 'sourceId', 'execution',
                                                                 'missingFields', 'receivedAt', 'endpointIds', 'verification') if k in canonical}}
    provenance = {'agentId': agent['id'], 'sourceId': source_of(agent).get('source_id', ''), 'connection': connection,
                  'billing': billing, **({'mappingRefs': canonical['mappingRefs']} if canonical.get('mappingRefs') else {})}
    from .run_escrow import CURRENT
    escrow = CURRENT.get()
    if escrow is not None:  # the run's result is then known to be drawn from this source
        escrow.drew(provenance['agentId'], provenance['sourceId'])
    return result, provenance


async def llm_generation(network, store, user, item):
    """One generation with this user's own key for an LLM provider the named agent publishes.

    The key goes only to the provider host pinned when it was saved; the agent is asked for nothing but its
    published endpoint. Using the site's model instead is an ordinary model-data call to that agent."""
    from .direct_vendor import run_llm
    from .source_keys import llm_key, llm_provider
    agent = await network.agent(item['agentId'], user['token'])
    await network.require_trusted(agent, user['token'])
    provider = llm_provider(agent, 'llm.' + item['provider'])
    if provider is None:
        raise HTTPException(409, (agent.get('name') or item['agentId']) + ' does not publish that LLM provider.')
    key, hosts = llm_key(store, user, agent, provider)
    result = await run_llm(provider, item['model'], item['messages'], item.get('maxTokens', 4096), key, hosts,
                           web_fetch=item.get('webFetch'))
    provenance = {'agentId': agent['id'], 'sourceId': 'llm.' + provider['id'], 'connection': 'own',
                  'billing': {'points': 0, 'state': 'own-key'}}
    return result, provenance


async def source_list(network, store, user, models):
    """The sources this user can draw each named model from, with the Data Consultant's mappings."""
    from .direct_vendor import model_mappings
    from .source_keys import route, say, source_of
    mappings = await model_mappings(network, user['token'])
    listed = {s['sourceId']: s for s in mappings['sources'] if isinstance(s, dict) and isinstance(s.get('sourceId'), str)}
    rows = []
    for agent in await network.directory(user['token']):
        profile = source_of(agent)
        offered = listed.get(profile.get('source_id'))
        kept = [m for m in (offered or {}).get('models') or [] if isinstance(m, dict) and m.get('schema') in models]
        if not kept:
            continue
        try:
            await network.require_trusted(agent, user['token'])
        except HTTPException:
            continue
        try:
            own = route(store, user, agent)
            credential = 'own' if own else 'none'
        except HTTPException:
            own, credential = None, 'missing'
        access = (profile.get('connectivity') or {}).get('data_access') or {}
        executes = access.get('status') != 'unavailable' and access.get('attempt_ready') is not False

        def usable(model):
            # A Terminal-run mapping needs the user's key; a source-run model needs a source that executes.
            return bool(own and own.get('key')) if model.get('execution') == 'terminal' else credential == 'none' and executes
        # A source whose key is optional (FinMind) and none is saved here: its Terminal-run models wait for one, so
        # the reason is to add it, not that the source can't serve.
        keyless = bool(own) and not own.get('key') and any(m.get('execution') == 'terminal' for m in kept)
        # A processor offers only the bar sizes, and the history per bar size, the source provides.
        models_out = [{k: m[k] for k in ('schema', 'modelRef', 'fields', 'intervals', 'defaultInterval', 'historyDays', 'execution', 'delivery') if k in m}
                      for m in kept if usable(m)]
        rows.append({'agentId': agent['id'], 'name': agent.get('name') or profile.get('source_name') or agent['id'],
                     'sourceId': profile.get('source_id'), 'credential': credential, 'available': bool(models_out),
                     # The user's own paired copy, so a processor can offer it first.
                     **({'local': True} if agent.get('localId') else {}),
                     # A copy on this computer is not on Plaza, where a view reads a source's credit and licence: the
                     # row carries the ones its card publishes (OpenStreetMap's "© OpenStreetMap contributors").
                     **(card_texts(profile) if agent.get('localId') else {}),
                     # Both reasons in the viewer's language: a view shows them after the source's name.
                     **({} if models_out else {'reason': say(store, user, 'Add your key in Terminal settings → Data sources.') if credential == 'missing' or keyless
                                               else say(store, user, 'This source cannot serve this model now.')}),
                     'models': models_out})
    return rows


LANGUAGE_TAG = re.compile(r'[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,2}')
ENDPOINT_ID = re.compile(r'[A-Za-z0-9_.:-]{1,160}')


def card_texts(profile):
    """A copy's credit and licence as its card publishes them, with that text in other languages ({language tag:
    {description, license}}) and a credit for each of its endpoints ({endpoint id: credit}), all bounded. The Terminal
    passes them on to the view and reads none of them."""
    def text(value, limit):
        return ' '.join(value.split())[:limit] if isinstance(value, str) and value.strip() else ''
    out = {key: words for key, limit in (('attribution', 200), ('license', 400)) if (words := text(profile.get(key), limit))}
    languages = {}
    for tag, fields in list(profile['translations'].items())[:8] if isinstance(profile.get('translations'), dict) else ():
        if isinstance(tag, str) and LANGUAGE_TAG.fullmatch(tag) and isinstance(fields, dict):
            kept = {key: words for key, limit in (('description', 300), ('license', 400)) if (words := text(fields.get(key), limit))}
            if kept:
                languages[tag] = kept
    credits = {key: words for key, value in (list(profile['attributions'].items())[:16] if isinstance(profile.get('attributions'), dict) else ())
               if isinstance(key, str) and ENDPOINT_ID.fullmatch(key) and (words := text(value, 200))}
    return {**out, **({'translations': languages} if languages else {}), **({'attributions': credits} if credits else {})}


MAX_LOCAL_RESOURCES = 16


async def local_resources(network, user, pulses):
    """The programs on this computer (listed by discovery now; Plaza never lists them) that publish every pulse in
    `pulses`. Only each one's Terminal id and name: a processor names that id in model-data items, and those calls
    still go through this Terminal's checks."""
    wanted, found = set(pulses), []
    for entry in await network.directory(user['token']):
        if not entry.get('localId'):
            continue
        published = {p.get('pulse_name') or p.get('name')
                     for p in (entry.get('meta') or {}).get('supported_pulses') or [] if isinstance(p, dict)}
        if wanted <= published:
            found.append({'agentId': entry['id'], 'name': str(entry.get('name') or '')[:120]})
    return sorted(found, key=lambda row: row['agentId'])[:MAX_LOCAL_RESOURCES]


MAX_AGENTS = 32
LLM_NAME = re.compile(r'[A-Za-z0-9_.:/-]{1,120}')


def llm_publication(meta):
    """What an agent publishes about its LLMs (`llm_site`, `llm_providers`), bounded; None for any other agent."""
    site = meta.get('llm_site') if isinstance(meta.get('llm_site'), dict) else {}
    providers = []
    for provider in (meta.get('llm_providers') or [])[:8] if isinstance(meta.get('llm_providers'), list) else ():
        if not isinstance(provider, dict) or not isinstance(provider.get('id'), str) or not LLM_NAME.fullmatch(provider['id']):
            continue
        models = [{'id': m['id'], 'name': str(m.get('name') or m['id'])[:80],
                   **({'points': m['points']} if type(m.get('points')) in (int, float) and m['points'] >= 0 else {})}
                  for m in (provider.get('models') or [])[:20] if isinstance(m, dict) and isinstance(m.get('id'), str) and LLM_NAME.fullmatch(m['id'])]
        if models:
            providers.append({'id': provider['id'], 'name': str(provider.get('name') or provider['id'])[:80], 'models': models})
    chosen = {key: site[key] for key in ('provider', 'model') if isinstance(site.get(key), str) and LLM_NAME.fullmatch(site[key])}
    if not providers and len(chosen) < 2:
        return None
    return {**({'site': chosen} if len(chosen) == 2 else {}), 'providers': providers}


async def agents(network, store, user, pulses):
    """Every agent this user can use (a program on this computer, or one Plaza lists and trusts now) that publishes
    every pulse in `pulses`, in one list: local and site agents alike. Each comes as its Terminal id, its name, whether
    it is on this computer and, for an LLM agent, the models it publishes; its calls still go through this Terminal.
    Each published LLM provider says whether this window holds a usable own key for it (`ownKey`), so a card can grey
    out a choice that would fail; that yes or no is all an agent learns, never the key."""
    from .source_keys import own_llm_key_ready
    wanted, found = set(pulses), []
    for entry in await network.trusted_agents(user['token']):
        meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
        published = {p.get('pulse_name') or p.get('name') for p in meta.get('supported_pulses') or [] if isinstance(p, dict)}
        if not wanted <= published or not isinstance(entry.get('id'), str):
            continue
        llm = llm_publication(meta)
        for provider in (llm or {}).get('providers', []):
            provider['ownKey'] = own_llm_key_ready(store, user, entry, provider['id'])
        found.append({'agentId': entry['id'], 'name': str(entry.get('name') or '')[:120], 'local': bool(entry.get('localId')),
                      **({'llm': llm} if llm else {})})
    return sorted(found, key=lambda row: (row['name'].casefold(), row['agentId']))[:MAX_AGENTS]


async def answer_items(network, store, user, request, agent=None):
    """Every item of one data request, for this Terminal's user. `agent` is the processor that asked (its Plaza
    directory entry); a `library-blocks` item is answered from this Terminal's own library, for that agent's blocks."""
    items = checked_request(request)
    semaphore = asyncio.Semaphore(4)

    async def one(item):
        async with semaphore:
            try:
                if item['kind'] == MODEL_DATA:
                    payload, provenance = await source_data(network, store, user, item['agentId'], item['pulse'], item['parameters'])
                    return item['id'], answer(item, status='completed', payload=payload, provenance=provenance)
                if item['kind'] == LLM_GENERATION:
                    payload, provenance = await llm_generation(network, store, user, item)
                    return item['id'], answer(item, status='completed', payload=payload, provenance=provenance)
                if item['kind'] == LIBRARY_BLOCKS:
                    from . import phema_library
                    payload = phema_library.block_request(store, user['id'], (agent or {}).get('id') or '', item)
                    return item['id'], answer(item, status='completed', payload=payload)
                if item['kind'] == LOCAL_RESOURCES:
                    return item['id'], answer(item, status='completed', resources=await local_resources(network, user, item['pulses']))
                if item['kind'] == AGENTS:
                    return item['id'], answer(item, status='completed', agents=await agents(network, store, user, item['pulses']))
                return item['id'], answer(item, status='completed', sources=await source_list(network, store, user, item['models']))
            except (HTTPException, httpx.HTTPError, ValueError, KeyError) as error:
                LOG.warning('Data request item %s (%s) failed: %s', item['id'], item['kind'], reason(error)[:200])
                return item['id'], answer(item, status='failed', error=reason(error))
    return bounded(dict(await asyncio.gather(*(one(item) for item in items))))


async def run(network, store, user, agent, pulse, inputs, result, call=None):
    """Supply each data request the processor answers with, then call it again (bounded rounds). `call(inputs)` calls
    it again when it is not an agent on Plaza (a program on this computer); by default, through Plaza."""
    for _ in range(MAX_ROUNDS):
        if not is_request(result):
            return result
        supplied = {**(inputs.get(SUPPLIED) or {}), **await answer_items(network, store, user, result, agent)}
        inputs = {**inputs, SUPPLIED: bounded(supplied)}
        result = await (call(inputs) if call else network.execute(agent, pulse, inputs, user, store))
    if is_request(result):
        raise HTTPException(502, 'The agent kept asking for more data; nothing was computed.')
    return result
