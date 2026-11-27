"""Closed inputs for the stateless RSS source: rss.read_feeds and rss_fetch (the feeds a request sends; feed preferences
belong to the Terminal), the default feeds' news endpoints and the feed group directory (rss.groups)."""
import re
from copy import deepcopy
from jsonschema import Draft202012Validator

PULSE = 'rss_fetch'
REFERENCE = 'rss-content'
VIEW_ID = 'rss-viewer'
# The site source's RSS Feed Groups panel: its view and its one reference, to this source's data_fetch rss.groups.
GROUPS_VIEW_ID = 'rss-groups'
GROUPS_REFERENCE = 'rss-groups'
GROUPS_ENDPOINT_ID = 'rss.groups'


def record(properties, required=()):
    return {'type': 'object', 'additionalProperties': False, 'properties': properties, 'required': list(required)}


FEED = record({
    'url': {'type': 'string', 'minLength': 1, 'maxLength': 2048},
    'name': {'type': 'string', 'maxLength': 100},
    'enabled': {'type': 'boolean'},
    'refresh_seconds': {'type': 'integer', 'enum': [0, 60, 300, 900, 1800, 3600, 21600, 86400]},
    'etag': {'type': 'string', 'maxLength': 512, 'pattern': '^[^\r\n]*$'},
    'last_modified': {'type': 'string', 'maxLength': 128, 'pattern': '^[^\r\n]*$'},
}, ['url'])
# A feed as the RSS Viewer keeps it (its `feeds` page value): FEED and the group the viewer lists it under, a name the
# user sees and can change. Reads send FEED alone, so INPUT, and the digest a mounted viewer checks, stays the same.
VIEWER_FEED = {**FEED, 'properties': {**FEED['properties'], 'group': {'type': 'string', 'maxLength': 60}}}
INPUT = record({'feeds': {'type': 'array', 'maxItems': 20, 'items': FEED},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 30}}, ['feeds'])


def check(value):
    errors = list(Draft202012Validator(INPUT).iter_errors(value))
    if errors:
        raise ValueError('Invalid RSS request: ' + errors[0].message[:160])
    urls = [f['url'].strip() for f in value['feeds']]
    if len(set(urls)) != len(urls):
        raise ValueError('Each feed URL must appear once.')
    return deepcopy(value)


# The default feeds' news (news.py). Feeds are named by their id in defaults.py; tags narrow them.
TAG = {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z-]{0,30}$'}
TAGS = {'type': 'array', 'maxItems': 8, 'uniqueItems': True, 'items': TAG,
        'description': 'Only feeds that have every one of these tags.'}
FEED_ID = {'type': 'string', 'pattern': '^[a-z0-9][a-z0-9-]{0,63}$'}
# A word to search for: a stock code (2330, AAPL) or a name (台積電). `checked` refuses control characters in any text.
WORD = {'type': 'string', 'minLength': 1, 'maxLength': 40, 'pattern': '\\S'}
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
FEEDS_INPUT = record({'tags': TAGS})
NEWS_LIST_INPUT = record({'tags': TAGS, 'feeds': {'type': 'array', 'maxItems': 30, 'uniqueItems': True, 'items': FEED_ID},
                          'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}})
ARTICLE_INPUT = record({
    'feed': {'type': 'string', 'minLength': 1, 'maxLength': 120,
             'description': 'A default feed id, or keyword:<feed id>:<keyword> for an article stock news found.'},
    'id': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}}, ['feed', 'id'])
STOCK_NEWS_INPUT = record({'keyword': WORD, 'aliases': {'type': 'array', 'maxItems': 4, 'uniqueItems': True, 'items': WORD},
                           'tags': TAGS, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}, ['keyword'])


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _texts(item)


def checked(schema, value, what):
    """A closed request for one of the news endpoints, or ValueError saying what is wrong."""
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        raise ValueError(f'Invalid {what} request: ' + errors[0].message[:160])
    # A schema pattern's $ also matches before a final newline, so control characters are refused here.
    if any(CONTROL.search(text) for text in _texts(value)):
        raise ValueError(f'Invalid {what} request: text may not contain control characters.')
    return deepcopy(value)


def definition():
    return {'name': PULSE, 'pulse_name': PULSE, 'pulse_address': 'plaza://pulse/' + PULSE,
            'description': 'Read public RSS and Atom feeds; subscriptions and refresh preferences stay in your Terminal.',
            'tags': ['attas', 'rss', 'atom', 'data-source'], 'cost': 0, 'cost_points': 0,
            'input_schema': deepcopy(INPUT), 'output_schema': {'type': 'object'}}


# The feed group directory (groups.py, feed_groups.json): groups of public feeds by language and topic.
LANGUAGES = ('zh-Hant', 'zh-Hans', 'en', 'ja')
GROUP_ID = {'type': 'string', 'pattern': '^[a-z][a-z0-9-]{0,63}$'}
GROUPS_INPUT = record({'language': {'type': 'string', 'enum': list(LANGUAGES)}, 'topic': TAG,
                       'query': {**WORD, 'description': 'Words in a group or feed name or description.'}})
# What the RSS Feed Groups panel sends: the rss.groups endpoint through data_fetch, the pulse a site's gateway forwards
# to a data source.
GROUPS_FETCH = record({'endpoint_id': {'type': 'string', 'const': GROUPS_ENDPOINT_ID}, 'parameters': GROUPS_INPUT},
                      ['endpoint_id', 'parameters'])
# A group the RSS Viewer took from a directory: its id there, the name it lists the group's feeds under, the directory
# that gave it and that directory's version. The viewer keeps these in its `groups` page value.
GROUP_ENTRY = record({'id': GROUP_ID, 'name': {'type': 'string', 'minLength': 1, 'maxLength': 60},
                      'source': {'type': 'string', 'maxLength': 100}, 'version': {'type': 'integer', 'minimum': 0}},
                     ['name'])


# Local RSS's own operations (subscriptions.py, library.py): one pulse with an envelope, as the Retis MAS Manager and
# Local Analyst have, so the reader's Phema never changes when an operation is added. Only Local RSS answers it.
LOCAL_PULSE = 'rss_local'
LOCAL_REFERENCE = 'rss-local'
READER_VIEW_ID = 'rss-reader'
AGENT_ID = {'type': 'string', 'minLength': 1, 'maxLength': 128, 'pattern': '^[A-Za-z0-9_.:-]+$'}
GROUP_KEY = {'type': 'string', 'pattern': '^g-[0-9a-f]{12}$'}
URL = {'type': 'string', 'minLength': 1, 'maxLength': 2048}
ITEM_ID = {'type': 'string', 'minLength': 1, 'maxLength': 80}
# The LLM a story is translated with, as rss_llms lists it.
LLM_CHOICE = record({'source': {'enum': ['local', 'own', 'site']}, 'agent': AGENT_ID,
                     'provider': {'type': 'string', 'pattern': '^[A-Za-z0-9_.:/-]{1,120}$'},
                     'model': {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,199}$'}}, ['source', 'agent', 'provider', 'model'])
FEED_NAME = {'type': 'string', 'maxLength': 100}
GROUP_NAME = {'type': 'string', 'maxLength': 60}
EVERY = {'type': 'integer', 'enum': [0, 60, 300, 900, 1800, 3600, 21600, 86400]}
EVERY_OR_DEFAULT = {'enum': [None, 0, 60, 300, 900, 1800, 3600, 21600, 86400],
                    'description': 'Seconds, or null for the group default.'}
LOCAL_OPERATIONS = {
    # Every RSS source this viewer can reach, on this computer and on Plaza (a Terminal data request).
    'rss_sources': record({}),
    'rss_subscriptions': record({}),
    'rss_articles': record({'group': GROUP_KEY, 'feed': URL, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500}}),
    'rss_article': record({'feed': URL, 'id': {'type': 'string', 'minLength': 1, 'maxLength': 80}}, ['feed', 'id']),
    # Read now: every subscribed feed, a group or a feed; through another RSS source when `source` names one.
    'rss_refresh': record({'source': AGENT_ID, 'group': GROUP_KEY, 'feed': URL}),
    'rss_directory': {**GROUPS_INPUT, 'properties': {**GROUPS_INPUT['properties'], 'source': AGENT_ID}},
    'rss_follow': record({'source': AGENT_ID, 'id': GROUP_ID, 'name': GROUP_NAME}, ['id']),
    'rss_set_group': record({'key': GROUP_KEY, 'enabled': {'type': 'boolean'}, 'refresh_seconds': EVERY, 'name': GROUP_NAME,
                             'remove': {'const': True}}, ['key']),
    'rss_add_feed': record({'url': URL, 'name': FEED_NAME, 'group': GROUP_NAME, 'refresh_seconds': EVERY}, ['url']),
    'rss_update_feed': record({'url': URL, 'enabled': {'type': 'boolean'}, 'refresh_seconds': EVERY_OR_DEFAULT, 'name': FEED_NAME,
                               'group': GROUP_NAME}, ['url']),
    'rss_remove_feed': record({'url': URL}, ['url']),
    'rss_import': record({'feeds': {'type': 'array', 'minItems': 1, 'maxItems': 500, 'items': record(
        {'url': URL, 'name': FEED_NAME, 'group': GROUP_NAME, 'enabled': {'type': 'boolean'},
         'refresh_seconds': EVERY_OR_DEFAULT}, ['url'])}}, ['feeds']),
    # One story (story.py): the LLMs this viewer can use and a translation with the one picked, the AssetStorages it
    # can use and its own note on the story in the one picked.
    'rss_llms': record({}),
    'rss_translate': record({'feed': URL, 'id': ITEM_ID, 'language': {'enum': list(LANGUAGES)}, 'llm': LLM_CHOICE,
                             'part': {'type': 'integer', 'minimum': 0, 'maximum': 11}, 'fresh': {'type': 'boolean'}},
                            ['feed', 'id', 'language', 'llm']),
    'rss_stores': record({}),
    # The tags analysts gave these stories (Local Analyst keeps them), by the stories' addresses.
    'rss_tags': record({'urls': {'type': 'array', 'minItems': 1, 'maxItems': 300, 'items': URL}}, ['urls']),
    'rss_note': record({'feed': URL, 'id': ITEM_ID, 'store': AGENT_ID}, ['feed', 'id', 'store']),
    'rss_save_note': record({'feed': URL, 'id': ITEM_ID, 'store': AGENT_ID, 'text': {'type': 'string', 'maxLength': 20000},
                             'asset_id': {'type': 'string', 'pattern': '^a-[0-9a-f]{24}$'}}, ['feed', 'id', 'store', 'text']),
}
LOCAL_ENVELOPE = record({'operation': {'type': 'string', 'pattern': '^rss_[a-z_]{1,32}$'}, 'parameters': {'type': 'object'},
                         'request_key': AGENT_ID}, ['operation', 'parameters', 'request_key'])
# What the pulse takes: the envelope, and what the Terminal supplied for a data request it answered.
LOCAL_INPUT = {**LOCAL_ENVELOPE, 'properties': {**LOCAL_ENVELOPE['properties'], 'supplied_data': {'type': 'object'}}}


def local_definition():
    return {'name': LOCAL_PULSE, 'pulse_name': LOCAL_PULSE, 'pulse_address': 'plaza://pulse/' + LOCAL_PULSE,
            'description': "Local RSS's subscriptions, its kept articles and the RSS sources this user can reach.",
            'tags': ['attas', 'rss', 'local'], 'cost': 0, 'cost_points': 0,
            'input_schema': deepcopy(LOCAL_INPUT), 'output_schema': {'type': 'object'}}
