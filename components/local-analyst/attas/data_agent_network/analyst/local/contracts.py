"""The Local Analyst's one pulse, its operations and their exact parameter schemas.

Alvin, 2026-11-24: the analysts are the analyst Personas this Terminal can use (on this computer, the site's Plaza, a
linked Plaza such as tw-001, or behind Pipeline), not LLM models; the settings are rules. A tagging rule has one analyst
tag every new news item from a list of tags; a sentiment rule has one analyst score the news of one tag, one record per
period (for example Naomi on tw-001, Taiwan Stock, every 6 hours; Sora behind Pipeline, FX, every hour).

Alvin, 2026-11-24 (later): named lists for named-entity recognition, configured here. A list is static (typed entries) or
dynamic (source URLs and how often to read them again): all Taiwan stocks, currencies, industries. A tagging rule may
use lists as well as, or instead of, tags; an item that names a list's member is tagged with the list's name.

Alvin, 2026-11-25 ("Yes, send it", to wiring Local Analyst into the sentiment strategy templates): a stock rule has one
analyst score each tagged news item for each member of one named list it names (2330.TW, USD), from -100 to +100 with a
confidence. These per-news, per-stock opinions are what the sentiment strategies read (index.py, source.py).
"""
from copy import deepcopy

from jsonschema import Draft202012Validator

PULSE = 'analyst_local'
REFERENCE = 'analyst-local'
VIEW_ID = 'local-analyst'
NAME = 'Local Analyst'
# The Persona pulse both jobs use: every analyst Persona offers it (phemacast/agents/persona.py), at its own price.
ANALYST_PULSE = 'articles_summary'
NEWS_MODEL = 'research.news_feed.v1'
NEWS_FIELDS = ['headline', 'publishedAt', 'url', 'publisher', 'summary']  # only the model's own fields; an item's id comes from its url
MAX_TAGGING_RULES = 8
MAX_SENTIMENT_RULES = 16
MAX_STOCK_RULES = 8
MAX_TAGS = 12
MAX_LISTS = 12
MAX_RULE_LISTS = 6
MAX_SOURCES = 4
MAX_STATIC_ENTRIES = 300
REFRESH_HOURS = [1, 6, 24, 168]
TAG_BATCH = 20  # news items an analyst tags in one call
MAX_TAG_ITEMS = 80  # items one tagging run tags; the rest wait for the next run
CALLS_PER_ROUND = 4
CATCH_UP = 3  # complete periods a sentiment run looks back over, so a missed run is made up
TAG_EVERY = [15, 30, 60, 180, 360, 1440]  # minutes
PERIODS = [1, 2, 3, 4, 6, 12, 24]  # hours
LANGUAGES = {'en': 'English', 'zh-Hant': 'Traditional Chinese (Taiwan)', 'zh-Hans': 'Simplified Chinese', 'ja': 'Japanese'}

ID = {'type': 'string', 'minLength': 1, 'maxLength': 128, 'pattern': '^[A-Za-z0-9_.:-]+$'}
RULE_ID = {'type': 'string', 'pattern': '^[a-z0-9]{1,12}$'}
LABEL = {'type': 'string', 'maxLength': 120}
# A tag is a short word people read, in any language: it also names AssetStorage tags (`tag:<it>`, at most 40 characters).
TAG = {'type': 'string', 'minLength': 1, 'maxLength': 30, 'pattern': '^[\\w .-]+$'}


def record(properties, required=()):
    return {'type': 'object', 'additionalProperties': False, 'properties': deepcopy(properties), 'required': list(required)}


# An analyst: a Persona the Terminal listed, as the Terminal names it, and whether it runs on this computer.
ANALYST = record({'agentId': ID, 'name': LABEL, 'local': {'type': 'boolean'}}, ['agentId'])
NEWS_SOURCE = record({'agentId': ID, 'name': LABEL, 'local': {'type': 'boolean'}, 'modelRef': {'type': 'object'}}, ['agentId', 'modelRef'])
STORE = record({'agentId': ID, 'name': LABEL, 'local': {'type': 'boolean'}}, ['agentId'])
# A rule needs tags, lists or both; the run says so when it has neither.
TAGGING_RULE = record({'id': RULE_ID, 'analyst': ANALYST, 'news': NEWS_SOURCE,
                       'tags': {'type': 'array', 'maxItems': MAX_TAGS, 'uniqueItems': True, 'items': TAG},
                       'lists': {'type': 'array', 'maxItems': MAX_RULE_LISTS, 'uniqueItems': True, 'items': RULE_ID},
                       'every_minutes': {'enum': TAG_EVERY}, 'enabled': {'type': 'boolean'}},
                      ['id', 'analyst', 'news', 'tags', 'every_minutes'])
TEXT = {'type': 'string', 'maxLength': 80}
COLUMN = {'type': 'string', 'minLength': 1, 'maxLength': 80}
# A list member: a code (a ticker, currency or industry code), the name news uses, and other names.
ENTRY = record({'code': {'type': 'string', 'maxLength': 40}, 'name': {**TEXT, 'minLength': 1},
                'aliases': {'type': 'array', 'maxItems': 6, 'items': TEXT}}, ['name'])
# A dynamic list's source: a public HTTPS URL giving JSON or CSV rows, and which columns hold the code, name and other
# names; the suffix goes after each code (.TW for TWSE, .TWO for TPEx).
LIST_SOURCE = record({'url': {'type': 'string', 'minLength': 9, 'maxLength': 500, 'pattern': '^https://'},
                      'code': COLUMN, 'name': COLUMN, 'aliases': {'type': 'array', 'maxItems': 3, 'items': COLUMN},
                      'suffix': {'type': 'string', 'maxLength': 8, 'pattern': '^[.A-Za-z0-9-]*$'}}, ['url'])
NAMED_LIST = record({'id': RULE_ID, 'name': TAG, 'kind': {'enum': ['static', 'dynamic']},
                     'entries': {'type': 'array', 'maxItems': MAX_STATIC_ENTRIES, 'items': ENTRY},
                     'sources': {'type': 'array', 'minItems': 1, 'maxItems': MAX_SOURCES, 'items': LIST_SOURCE},
                     'refresh_hours': {'enum': REFRESH_HOURS}}, ['id', 'name', 'kind'])
# A stock rule: one analyst scores each news item a tagging run found a member of this named list in, per member.
STOCK_RULE = record({'id': RULE_ID, 'analyst': ANALYST, 'list': RULE_ID, 'every_minutes': {'enum': TAG_EVERY},
                     'enabled': {'type': 'boolean'}}, ['id', 'analyst', 'list', 'every_minutes'])
SENTIMENT_RULE = record({'id': RULE_ID, 'analyst': ANALYST, 'tag': TAG, 'period_hours': {'enum': PERIODS},
                         'enabled': {'type': 'boolean'}}, ['id', 'analyst', 'tag', 'period_hours'])
LANGUAGE = {'enum': list(LANGUAGES)}
ASSET = {'type': 'string', 'pattern': '^a-[0-9a-f]{24}$'}

SCHEMAS = {
    # The analysts, news sources and AssetStorages this person can use, local and remote alike.
    'analyst_choices': record({}),
    # The tags analysts gave these news items (by their addresses), from the Local Analyst's own index: one call, no
    # data request, so another agent can ask it inside its own request (the RSS Viewer, through Local RSS).
    'analyst_tags': record({'urls': {'type': 'array', 'minItems': 1, 'maxItems': 300,
                                     'items': {'type': 'string', 'minLength': 1, 'maxLength': 1000}}}, ['urls']),
    # One tagging rule's run: its analyst tags the items that are new since its last run.
    # Its lists come with it: the named lists the rule uses, as the view keeps them.
    'analyst_tag': record({'rule': TAGGING_RULE, 'store': STORE, 'language': LANGUAGE,
                           'lists': {'type': 'array', 'maxItems': MAX_RULE_LISTS, 'items': NAMED_LIST}}, ['rule', 'store']),
    # One named list read as a run reads it: its size, a few entries and each source's columns to choose from.
    'analyst_list_check': record({'list': NAMED_LIST}, ['list']),
    # One sentiment rule's run: its analyst scores each recent complete period's news with its tag.
    'analyst_score': record({'rule': SENTIMENT_RULE, 'store': STORE, 'language': LANGUAGE}, ['rule', 'store']),
    # One stock rule's run: its analyst scores the news tagged with its list's members since its last run, per member.
    # Its list comes with it, as the view keeps it (only its name is used).
    'analyst_stock_score': record({'rule': STOCK_RULE, 'store': STORE, 'language': LANGUAGE,
                                   'lists': {'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': NAMED_LIST}}, ['rule', 'store', 'lists']),
    # The kept sentiment records and tagging runs, newest first.
    'analyst_history': record({'store': STORE, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}, ['store']),
    # One kept record in full.
    'analyst_detail': record({'store': STORE, 'asset_id': ASSET}, ['store', 'asset_id']),
}
# One envelope for the view's reference; the operation's own schema is checked here.
ENVELOPE = record({'operation': {'type': 'string', 'pattern': '^analyst_[a-z_]{1,32}$'}, 'parameters': {'type': 'object'},
                   'request_key': ID}, ['operation', 'parameters', 'request_key'])
PULSE_INPUT = {**deepcopy(ENVELOPE), 'properties': {**deepcopy(ENVELOPE['properties']), 'supplied_data': {'type': 'object'}}}


def check(schema, value):
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.absolute_path))
    if errors:
        where = '/'.join(str(part) for part in errors[0].absolute_path)
        raise ValueError(('Invalid ' + where + ': ' if where else 'Invalid request: ') + errors[0].message[:200])
    return deepcopy(value)


def definition():
    return {'name': PULSE, 'pulse_name': PULSE, 'pulse_address': 'attas:' + PULSE,
            'description': 'Free, on this computer: runs your tagging and sentiment rules with the analysts you choose and '
                           'keeps the results in your AssetStorage. Your Terminal supplies the news and asks each analyst; '
                           'it reads only the public list URLs you give it.',
            'tags': ['attas', 'analyst', 'sentiment', 'local'], 'input_schema': deepcopy(PULSE_INPUT),
            'output_schema': {'type': 'object'}, 'cost': 0, 'cost_points': 0}
