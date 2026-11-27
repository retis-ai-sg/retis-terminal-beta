"""Local Analyst as a data source: the opinions its stock rules kept, served by the data pulses every source speaks.

Alvin, 2026-11-25 ("Keep in local analystdatasource"): the per-news, per-stock opinions stay in Local Analyst's own
state folder (index.py), and Local Analyst serves them itself, as a data source. Like every source it knows only its
own rows. The Data Consultant maps them to the canonical `research.news_sentiment.v1` with its reviewed recipe
(attas/data_consultant_phemar/recipes/local_analyst.research.news_sentiment.v1.json), and a processor that needs them,
such as the Strategy Producer's sentiment templates, runs that plan: its user's Terminal calls `data_fetch` here with
this source's own endpoint and parameters, and the processor maps the reply (phemacast.core.model_plans). A canonical
model request sent here directly is refused with that reason.

It speaks data_spec, data_availability and data_fetch on phemacast's Pulser rather than through the data-source
scaffold, which belongs to another agent (AGENTS.md, Agent boundaries). Its spec is the versioned catalog
attas/data_agent_network/catalogs/local_analyst/, which `python3 -m attas.data_agent_network.analyst.local.source
--write` writes from ENDPOINTS here; the Consultant's kept spec (scripts/reviewed_source_specs.py local_analyst) comes
from that catalog, and both carry the hash this source publishes.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import sys

from jsonschema import Draft202012Validator

from .index import MAX_ROWS, moment

SOURCE_ID = 'local_analyst'
SOURCE_NAME = 'Local Analyst'
OPINIONS = 'analyst.stock_opinions'
PARSER_VERSION = 'LocalAnalystCatalog:1'
REVIEWED_AT = '2026-11-26T00:00:00+00:00'
DATA_PULSES = ('data_spec', 'data_availability', 'data_fetch')
CANONICAL_REFUSED = ('Local Analyst answers its own endpoints only. The Data Consultant plans how its opinions become '
                     'canonical news sentiment, and the program that asked runs that plan.')

TEXT = {'type': 'string'}
TIME = {'type': 'string', 'format': 'date-time'}


def parameter(name, description, schema, *, required=False, examples=()):
    return {'name': name, 'location': 'body', 'description': description, 'required': required, 'schema': schema,
            'default': None, 'examples': list(examples)}


# One row is one analyst's opinion of one news item for one listing its stock rule's named list holds.
OPINION_ROW = {'type': 'object', 'properties': {
    'instrument': {**TEXT, 'description': "The listing's code as the named list holds it (2330.TW, USD)."},
    'member_name': {**TEXT, 'description': 'The name the named list gives the listing.'},
    'list_name': {**TEXT, 'description': 'The named list the stock rule scores.'},
    'rule': {**TEXT, 'description': 'The stock rule that gave the opinion.'},
    'news_id': {**TEXT, 'description': 'The news item, the same for every analyst and listing that scored it.'},
    'title': {**TEXT, 'description': "The news item's headline."},
    'url': {**TEXT, 'description': "The news item's address."},
    'publisher': {**TEXT, 'description': 'Who published the news item.'},
    'news_source': {**TEXT, 'description': 'The news source the Terminal read the item from.'},
    'published_at': {**TIME, 'description': 'When the news item was published, ISO 8601 in UTC.'},
    'analyzed_at': {**TIME, 'description': 'When the analyst gave the opinion, ISO 8601 in UTC.'},
    'available_at': {**TIME, 'description': 'When the opinion became known: the later of published_at and analyzed_at.'},
    'analyst_id': {**TEXT, 'description': 'The analyst (a Persona) that gave the opinion.'},
    'analyst_name': {**TEXT, 'description': 'The analyst as the Terminal names it.'},
    'score': {'type': 'number', 'minimum': -100, 'maximum': 100, 'description': 'From -100 (very negative) to +100 (very positive) for this listing.'},
    'confidence': {'type': ['number', 'null'], 'minimum': 0, 'maximum': 1, 'description': "The analyst's confidence from 0 to 1, when it gave one."},
}}

ENDPOINTS = [{
    'endpoint_id': OPINIONS, 'vendor_id': SOURCE_ID, 'name': 'Stock opinions',
    'description': ("The opinions this computer's stock rules kept for one listing, oldest first by when each became "
                    'known: one row per analyst, news item and listing. At most 10,000 rows; a longer span is refused.'),
    'category': 'News sentiment', 'transport': 'local_pulser', 'operation': OPINIONS,
    'parameters': [
        parameter('instrument', "The listing's code as a named list holds it.", {'type': 'string', 'minLength': 1, 'maxLength': 40},
                  required=True, examples=['2330.TW']),
        parameter('start', 'Opinions known from this time, ISO 8601 (inclusive).', TIME, examples=['2026-11-01T00:00:00Z']),
        parameter('end', 'Opinions known before this time, ISO 8601 (exclusive).', TIME, examples=['2026-11-26T00:00:00Z']),
    ],
    'response_schema': {'type': 'object', 'properties': {
        'instrument': TEXT, 'start': TEXT, 'end': TEXT,
        'items': {'type': 'array', 'maxItems': MAX_ROWS, 'items': OPINION_ROW}}},
    'authentication': {'required': False, 'scheme': 'none'},
    'cost': {'amount': 0, 'currency': 'USD', 'model': 'free', 'notes': [], 'provider_cost': 'Kept on this computer.', 'unit': 'request'},
    'quality': {'status': 'source_defined', 'notes': [
        'Only what stock rules scored since they started: news is never scored again later, so no opinion carries hindsight.',
        'A listing a named list does not hold, such as an index, has no opinions.']},
    'documentation_url': '', 'executable': True, 'pulse_name': 'data_fetch',
    'extensions': {'attas.schema_provenance': 'source_defined', 'attas.specification_only': False},
}]


def content_hash(endpoints=ENDPOINTS):
    """The catalog's content hash: the endpoints as JSON with sorted keys, as a source's snapshot hashes them."""
    return hashlib.sha256(json.dumps(endpoints, sort_keys=True, default=list).encode()).hexdigest()


def spec_hash(endpoints=ENDPOINTS):
    """The hash this source publishes for its spec (no hand-kept vendor notes)."""
    return hashlib.sha256((content_hash(endpoints) + json.dumps({}, sort_keys=True)).encode('utf-8')).hexdigest()


def snapshot_metadata():
    return {'status': 'ready', 'vendor_id': SOURCE_ID, 'retrieved_at': REVIEWED_AT, 'content_hash': content_hash(),
            'spec_hash': spec_hash(), 'parser_version': PARSER_VERSION, 'endpoint_count': len(ENDPOINTS)}


def profile():
    """The card's `data_source`: what the Terminal lists it by. It maps no canonical model itself."""
    return {'source_id': SOURCE_ID, 'source_name': SOURCE_NAME, 'provider': SOURCE_ID,
            'description': "Opinions this computer's stock rules kept: one analyst's score of one news item for one listing.",
            'connectivity': {'status': 'ready', 'transport': 'local_pulser', 'pulse_name': 'data_availability',
                             'authentication': 'none', 'configuration_required': [], 'notes': [],
                             'data_access': {'status': 'available', 'attempt_ready': True}},
            'modelSupport': []}


def card_meta():
    return {'data_source': profile(), 'spec_snapshot': snapshot_metadata()}


def pulse_definitions():
    """The data pulses, with the inputs this source reads."""
    def defined(name, description, properties):
        return {'name': name, 'pulse_name': name, 'pulse_address': 'attas:' + name, 'description': description,
                'tags': ['attas', 'data', 'local'], 'cost': 0, 'cost_points': 0, 'output_schema': {'type': 'object'},
                'input_schema': {'type': 'object', 'properties': properties}}
    return [defined('data_spec', "Local Analyst's endpoints.", {'endpoint_id': TEXT, 'query': TEXT}),
            defined('data_availability', 'How many opinions are kept for each listing, and from when to when.',
                    {'instruments': {'type': 'array', 'maxItems': 100, 'items': TEXT}}),
            defined('data_fetch', "One endpoint's rows, such as a listing's kept opinions over a span.",
                    {'endpoint_id': TEXT, 'parameters': {'type': 'object'}, 'canonical': {'type': 'boolean'}})]


def endpoint(endpoint_id):
    found = next((e for e in ENDPOINTS if e['endpoint_id'] == endpoint_id), None)
    if found is None:
        raise ValueError('Local Analyst has no endpoint ' + str(endpoint_id)[:80] + '.')
    return found


def checked(spec, parameters):
    """The endpoint's parameters, refused when one is unknown, missing or of the wrong kind."""
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {p['name']: p['schema'] for p in spec['parameters']},
              'required': [p['name'] for p in spec['parameters'] if p['required']]}
    errors = sorted(Draft202012Validator(schema).iter_errors(parameters), key=lambda e: list(e.absolute_path))
    if errors:
        raise ValueError('Invalid ' + spec['endpoint_id'] + ' parameters: ' + errors[0].message[:200])
    return dict(parameters)


def when(value, name):
    if value is None:
        return None
    found = moment(value)
    if found is None:
        raise ValueError(name + ' must be an ISO 8601 time.')
    return found


def opinion(row):
    return {'instrument': row['instrument'], 'member_name': row['member_name'], 'list_name': row['list_name'],
            'rule': row['rule'], 'news_id': row['news_id'], 'title': row['title'], 'url': row['url'],
            'publisher': row['publisher'], 'news_source': row['news_source'], 'published_at': row['occurred_at'],
            'analyzed_at': row['analyzed_at'], 'available_at': row['available_at'], 'analyst_id': row['persona_id'],
            'analyst_name': row['persona_name'], 'score': row['score'], 'confidence': row['confidence']}


def public_source():
    return {key: value for key, value in profile().items() if key in ('source_id', 'source_name', 'provider', 'description')}


def data_spec(data):
    wanted = str(data.get('endpoint_id') or '').strip()
    found = [copy.deepcopy(e) for e in ENDPOINTS if not wanted or e['endpoint_id'] == wanted]
    return {'status': 'completed', 'source': public_source(), 'snapshot': snapshot_metadata(), 'endpoints': found,
            'total': len(found), 'warnings': []}


def data_availability(data, index):
    instruments = data.get('instruments') if isinstance(data.get('instruments'), list) else None
    if instruments is not None and (len(instruments) > 100 or any(not isinstance(i, str) for i in instruments)):
        raise ValueError('Name up to 100 listings.')
    return {'status': 'completed', 'source': public_source(), 'snapshot': snapshot_metadata(),
            'endpoints': [{'endpoint_id': e['endpoint_id'], 'name': e['name'], 'executable': e['executable']} for e in ENDPOINTS],
            'coverage': index.coverage(instruments) if index is not None else []}


def data_fetch(data, index):
    """One endpoint's rows; a canonical model request is refused (the Consultant's plan maps these rows)."""
    if data.get('target_model') is not None:
        return {'status': 'failed', 'source': public_source(), 'data': {'items': []}, 'error': CANONICAL_REFUSED}
    spec = endpoint(str(data.get('endpoint_id') or data.get('dataset_id') or ''))
    parameters = checked(spec, data.get('parameters') if isinstance(data.get('parameters'), dict) else {})
    start, end = when(parameters.get('start'), 'start'), when(parameters.get('end'), 'end')
    if start and end and end < start:
        raise ValueError('The end comes before the start.')
    if index is None:
        rows, more = [], False
    else:
        rows, more = index.query([parameters['instrument']], start, end)
    if more:
        return {'status': 'failed', 'source': public_source(), 'endpoint_id': spec['endpoint_id'], 'data': {'items': []},
                'error': f'More than {MAX_ROWS:,} opinions on {parameters["instrument"]} in this span; choose a shorter one.'}
    return {'status': 'completed', 'source': public_source(), 'endpoint_id': spec['endpoint_id'],
            'data': {'instrument': parameters['instrument'], **{k: parameters[k] for k in ('start', 'end') if k in parameters},
                     'items': [opinion(row) for row in rows]}}


def answer(pulse, data, index):
    if not isinstance(data, dict):
        raise ValueError('Send an object.')
    if pulse == 'data_spec':
        return data_spec(data)
    if pulse == 'data_availability':
        return data_availability(data, index)
    return data_fetch(data, index)


# --- the catalog ------------------------------------------------------------------------------------------------

def snapshot():
    return {'vendor_id': SOURCE_ID, 'retrieved_at': REVIEWED_AT, 'content_hash': content_hash(), 'parser_version': PARSER_VERSION,
            'sources': [], 'endpoints': copy.deepcopy(ENDPOINTS), 'warnings': []}


def serialized(value):
    """A catalog file's bytes, as a source's spec repository writes them."""
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + '\n'


def catalog_files():
    """{relative path: text} of the catalog folder this source's spec is kept in."""
    taken = snapshot()
    name = 'snapshots/' + (re.sub(r'[^0-9A-Za-z]+', '', REVIEWED_AT)[:20] or 'snapshot') + '-' + taken['content_hash'][:12] + '.json'
    body = serialized(taken)
    manifest = {'vendor_id': SOURCE_ID, 'active_snapshot': name, 'file_hash': hashlib.sha256(body.encode('utf-8')).hexdigest(),
                'content_hash': taken['content_hash'], 'retrieved_at': REVIEWED_AT, 'parser_version': PARSER_VERSION,
                'endpoint_count': len(ENDPOINTS)}
    return {'manifest.json': serialized(manifest), name: body}


CATALOG = Path(__file__).resolve().parents[2] / 'catalogs' / SOURCE_ID


def write_catalog(folder=CATALOG):
    folder = Path(folder)
    for relative, text in catalog_files().items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    return folder


if __name__ == '__main__':
    if sys.argv[1:] != ['--write']:
        raise SystemExit('Usage: python3 -m attas.data_agent_network.analyst.local.source --write')
    print(write_catalog())
