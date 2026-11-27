"""The RSS source's feed group directory: public feeds by language and topic (feed_groups.json).

The file is reviewed data. Every feed in it was read through this source (feeds.fetch and feeds.parse) on its
`checked` date, and a feed that did not read cleanly stays out. A change is a commit: add or move feeds, check them,
raise `version`. `rss.groups` returns the groups a request asks for; it needs no network and keeps no user state. The
RSS Viewer keeps the feeds a user takes from here in their Terminal.

Feed content belongs to its publishers and comes under their terms.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .contracts import GROUP_ID, LANGUAGES, TAG, record
from .feeds import public_url

PATH = Path(__file__).with_name('feed_groups.json')
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 200}
NAMES = record({'en': TEXT, 'zh-Hant': TEXT}, ['en', 'zh-Hant'])
FEED = record({'name': {'type': 'string', 'minLength': 1, 'maxLength': 100},
               'url': {'type': 'string', 'minLength': 1, 'maxLength': 2048},
               'checked': {'type': 'string', 'format': 'date', 'pattern': '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'}},
              ['name', 'url', 'checked'])
GROUP = record({'id': GROUP_ID, 'name': NAMES, 'description': NAMES, 'language': {'type': 'string', 'enum': list(LANGUAGES)},
                'region': {'type': 'string', 'pattern': '^[a-z]{2,4}$'},
                'topics': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'uniqueItems': True, 'items': TAG},
                'feeds': {'type': 'array', 'minItems': 1, 'maxItems': 20, 'items': FEED}},
               ['id', 'name', 'description', 'language', 'region', 'topics', 'feeds'])
DIRECTORY = record({'schema': {'type': 'string', 'const': 'rss-feed-groups/1'}, 'version': {'type': 'integer', 'minimum': 1},
                    'reviewed': FEED['properties']['checked'], 'note': {'type': 'string', 'maxLength': 400},
                    'groups': {'type': 'array', 'minItems': 1, 'maxItems': 60, 'items': GROUP}},
                   ['schema', 'version', 'reviewed', 'groups'])


def checked(document):
    """The directory if it is well formed: the schema, unique group ids, public feed addresses, each once per group."""
    errors = list(Draft202012Validator(DIRECTORY).iter_errors(document))
    if errors:
        raise ValueError('The feed group directory is invalid: ' + errors[0].message[:160])
    ids = [group['id'] for group in document['groups']]
    if len(set(ids)) != len(ids):
        raise ValueError('Each feed group id must appear once.')
    for group in document['groups']:
        urls = [public_url(feed['url']) for feed in group['feeds']]
        if len(set(urls)) != len(urls):
            raise ValueError(f"Group {group['id']} lists a feed twice.")
    return document


@lru_cache(maxsize=1)
def directory():
    return checked(json.loads(PATH.read_text(encoding='utf-8')))


def _matches(group, words):
    text = ' '.join([*group['name'].values(), *group['description'].values(), *group['topics'],
                     *(feed['name'] for feed in group['feeds'])]).lower()
    return all(word in text for word in words)


def groups(language=None, topic=None, query=None):
    """The directory's groups for a language, a topic and words, all optional, in the directory's order."""
    document = directory()
    words = [word for word in (query or '').lower().split() if word]
    chosen = [deepcopy(group) for group in document['groups']
              if (not language or group['language'] == language) and (not topic or topic in group['topics'])
              and _matches(group, words)]
    return {'source_mode': 'parameters', 'version': document['version'], 'reviewed': document['reviewed'],
            'languages': list(LANGUAGES), 'topics': sorted({t for group in document['groups'] for t in group['topics']}),
            'groups': chosen}
