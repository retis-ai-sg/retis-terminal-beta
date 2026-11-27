"""The Local Analyst's immutable view and the Phema it ships (the Terminal keeps its own copy, phema_library.py)."""
from copy import deepcopy
from pathlib import Path

from prompits.core.capabilities import digest
from phemacast.agent_view.contracts import CAPABILITY
from phemacast.agent_view.release import ViewRelease
from phemacast.core.composition_permissions import KEY
from phemacast.core.layout import GRAMMAR, from_layout

from .contracts import (ENTRY, ENVELOPE, LIST_SOURCE, MAX_LISTS, MAX_RULE_LISTS, MAX_SENTIMENT_RULES, MAX_SOURCES, MAX_STATIC_ENTRIES,
                        MAX_STOCK_RULES, MAX_TAGGING_RULES, MAX_TAGS, NAME, NAMED_LIST, PERIODS, PULSE, REFERENCE, REFRESH_HOURS,
                        SENTIMENT_RULE, STOCK_RULE, STORE, TAG, TAG_EVERY, TAGGING_RULE, VIEW_ID)

PACKAGE = Path(__file__).resolve().parent
RENDERER = {'id': CAPABILITY['id'], 'version': CAPABILITY['version']}
# Where a local resource serves its view's files (phemacast/network/service.py).
PREFIX = '/local/v2/views/'
# A Terminal takes a new copy of the Phema only when this goes up; a test pins each revision's digest.
# 2 (2026-11-24): rules. Tagging rules and sentiment rules replace the tickers, LLM analysts and windows of revision 1.
# 3 (2026-11-24): named lists (static or read from URLs) that tagging rules use to find who or what each item is about.
# 4 (2026-11-25): its name, description and settings in Traditional Chinese (phemacast:ui), as a Chinese Terminal lists it.
# 5 (2026-11-25): stock rules: an analyst scores each tagged news item for each member of one list, for the sentiment strategies.
PHEMA_REVISION = 5
# What one run may spend: each analyst call costs that analyst's points (usually 2).
RUN_POINTS = 100
TITLE = 'Analyst Sentiment'
DESCRIPTION = ('Analysts you choose tag every news item with your tags and named lists (Taiwan stocks, currencies, industries), '
               "score a tag's news per period, and score each stock's news for the sentiment strategies; results stay in your AssetStorage.")
# The Phema's name, description and settings in the Terminal's language (phemacast:ui); English is the default.
MESSAGES = {TITLE: '分析師情緒',
            DESCRIPTION: '您選擇的分析師為每則新聞加上您的標籤，以及您具名清單（台股、外匯幣別、產業）中的項目，為某個標籤的新聞評分，'
                         '每個時段一筆紀錄，並為每則新聞提到的每檔個股評分，供新聞情緒策略使用；結果保存在您的檔案庫。',
            'Named lists': '具名清單', 'Tagging rules': '標記規則', 'Sentiment rules': '情緒規則', 'Stock rules': '個股情緒規則',
            'AssetStorage': '檔案庫'}
# The viewer's rules, kept by the Terminal as page values. Only the view changes them, with its own controls.
PARAMETERS = {
    'named_lists': {'type': 'array', 'title': 'Named lists', 'maxItems': MAX_LISTS, 'items': deepcopy(NAMED_LIST),
                    'default': [], 'readOnly': True},
    'tagging_rules': {'type': 'array', 'title': 'Tagging rules', 'maxItems': MAX_TAGGING_RULES, 'items': deepcopy(TAGGING_RULE),
                      'default': [], 'readOnly': True},
    'sentiment_rules': {'type': 'array', 'title': 'Sentiment rules', 'maxItems': MAX_SENTIMENT_RULES, 'items': deepcopy(SENTIMENT_RULE),
                        'default': [], 'readOnly': True},
    'stock_rules': {'type': 'array', 'title': 'Stock rules', 'maxItems': MAX_STOCK_RULES, 'items': deepcopy(STOCK_RULE),
                    'default': [], 'readOnly': True},
    'store': {**deepcopy(STORE), 'title': 'AssetStorage', 'readOnly': True},
}


class AnalystViewRelease(ViewRelease):
    def build(self, dependencies, directory):
        entry = Path(self.sources) / self.entry
        return entry.read_bytes(), [entry]


# What an AI app may ask this view to do (manifest extension phemacast:ai-actions). The view's own code (view/analyst.js,
# the `actions` it registers) runs each action with the steps a click takes, so the Terminal keeps the rules as page
# values as it always does. Items are named as people name them: a list by its name, an analyst, news source or
# AssetStorage by the name the window shows, a rule by its number in the window's list of rules. Never declared:
# Remove (rules, lists, sources), Run automatically (it schedules runs that spend points), and anything that would
# change a rule that runs automatically.
def ai_action(identity, title, description, effect, properties, required=(), points=0, **schema):
    return {'id': identity, 'title': title, 'description': description, 'effect': effect,
            'inputSchema': {'type': 'object', 'additionalProperties': False, 'properties': deepcopy(properties),
                            **({'required': list(required)} if required else {}), **schema},
            'outputSchema': {'type': 'object'}, 'maxPoints': points, 'confirm': 'auto', 'sourceModes': ['parameters']}


CHOICE = {'type': 'string', 'minLength': 1, 'maxLength': 120}
RULE_NUMBER = {'type': 'integer', 'minimum': 1, 'maximum': MAX_TAGGING_RULES + MAX_SENTIMENT_RULES + MAX_STOCK_RULES,
               'description': 'The rule\'s number in the window\'s list of rules, top to bottom, as describe lists it.'}
LIST_NAME = {**TAG, 'description': 'A named list, by its name.'}
ENTRIES = {'type': 'array', 'minItems': 1, 'maxItems': MAX_STATIC_ENTRIES, 'items': deepcopy(ENTRY),
           'description': 'A static list\'s members: each a name, with a code (a ticker, currency or industry code) and other names.'}
SOURCES = {'type': 'array', 'minItems': 1, 'maxItems': MAX_SOURCES, 'items': {**deepcopy(LIST_SOURCE), 'required': ['url', 'name']},
           'description': 'A dynamic list\'s public https:// JSON or CSV URLs, each with the columns that hold the name, the code '
                          'and other names, and a suffix for each code (.TW, .TWO).'}
RULE_FIELDS = {
    'analyst': {**CHOICE, 'description': 'The analyst, by the name the window shows.'},
    'news': {**CHOICE, 'description': 'Tagging rules: the news source, by the name the window shows.'},
    'tags': {'type': 'array', 'maxItems': MAX_TAGS, 'uniqueItems': True, 'items': deepcopy(TAG),
             'description': 'Tagging rules: the tags to give every new news item.'},
    'lists': {'type': 'array', 'maxItems': MAX_RULE_LISTS, 'uniqueItems': True, 'items': deepcopy(LIST_NAME),
              'description': 'Tagging rules: the named lists whose members the analyst also finds.'},
    'every_minutes': {'enum': list(TAG_EVERY), 'description': 'Tagging and stock rules: how often a run takes the new news.'},
    'tag': {**TAG, 'description': 'Sentiment rules: the tag whose news is scored, one of the tagging rules\' tags or lists.'},
    'period_hours': {'enum': list(PERIODS), 'description': 'Sentiment rules: the hours one record covers.'},
    'list': {**LIST_NAME, 'description': 'Stock rules: the named list whose members are scored.'},
}
VIEW_ACTIONS = (
    ai_action('describe', 'Describe the rules',
              'Lists the named lists, the rules (numbered as the window lists them, with each one\'s analyst, news, tags, '
              'lists, period and whether it runs automatically), the AssetStorage the records go to, the latest records '
              'and the analysts, news sources, AssetStorages and presets there are to choose from. Nothing changes.', 'read', {}),
    ai_action('show_record', 'Show a record',
              'Opens one sentiment record in the window, as clicking its row does, and answers with its comment, score and '
              'article titles. Name it by its tag and period as describe lists them.', 'view',
              {'tag': deepcopy(TAG), 'period': {'type': 'string', 'minLength': 10, 'maxLength': 40,
                                                'description': 'The period\'s start, as describe lists it.'}}, ['tag', 'period']),
    ai_action('set_store', 'Choose the AssetStorage',
              'Chooses the AssetStorage the rules keep their records in and the window reads them from, as the AssetStorage '
              'menu does.', 'edit', {'store': {**CHOICE, 'description': 'The AssetStorage, by the name the window shows.'}}, ['store']),
    ai_action('add_list', 'Add a named list',
              'Adds a named list as Add list or Add from preset does: a preset by its title, a static list (a name and its '
              'members) or a dynamic list (a name and the URLs it is read from again every refresh_hours). A dynamic list or '
              'a preset is checked once it is added.', 'edit',
              {'preset': {**CHOICE, 'description': 'A preset\'s title, as describe lists it.'}, 'name': deepcopy(LIST_NAME),
               'entries': ENTRIES, 'sources': SOURCES, 'refresh_hours': {'enum': list(REFRESH_HOURS)}}, minProperties=1),
    ai_action('set_list', 'Change a named list',
              'Changes a named list\'s name, a static list\'s members (all of them, as its Entries box does) or a dynamic '
              'list\'s URLs and how often they are read. Refused while a rule using it runs automatically.', 'edit',
              {'list': deepcopy(LIST_NAME), 'name': deepcopy(LIST_NAME), 'entries': ENTRIES, 'sources': SOURCES,
               'refresh_hours': {'enum': list(REFRESH_HOURS)}}, ['list'], minProperties=2),
    ai_action('check_list', 'Check a named list',
              'Reads a named list as a run reads it, as Check does, and answers with its size and each URL\'s columns. Free.',
              'run', {'list': deepcopy(LIST_NAME)}, ['list']),
    ai_action('add_rule', 'Add a rule',
              'Adds a rule as choosing its kind and analyst, Add rule and its menus do. A tagging rule needs its news and tags '
              'or lists, a sentiment rule its tag, a stock rule its list. A new rule does not run automatically.', 'edit',
              {'kind': {'enum': ['tagging', 'sentiment', 'stock']}, **deepcopy(RULE_FIELDS)}, ['kind', 'analyst']),
    ai_action('set_rule', 'Change a rule',
              'Changes a rule\'s analyst, news, tags, lists, tag, list or period, as its menus do. Only what is named changes. '
              'Refused while the rule runs automatically.', 'edit',
              {'rule': RULE_NUMBER, **deepcopy(RULE_FIELDS)}, ['rule'], minProperties=2),
    ai_action('run_rule', 'Run a rule now',
              'Runs a rule once, as Run now does, and answers with what it did. Each analyst call costs that analyst\'s '
              'points (usually 2).', 'run', {'rule': RULE_NUMBER}, ['rule'], RUN_POINTS),
)


VIEW = AnalystViewRelease(view_id=VIEW_ID, sources=PACKAGE / 'view', entry='analyst.js', styles=(str(PACKAGE / 'view/analyst.css'),),
                          prefix=PREFIX, html='<main id="local-analyst"></main>', owner='LocalAnalyst',
                          bindings=({'id': REFERENCE, 'schemaDigest': digest(ENVELOPE)},),
                          implementation=(str(PACKAGE / 'release.py'), str(PACKAGE / 'contracts.py')), ai_actions=VIEW_ACTIONS)


def phema(publisher, owner=''):
    refs = [{'id': REFERENCE, 'kind': 'pulse', 'target': {'agentId': publisher, 'pulse': PULSE}, 'inputs': {},
             'interaction': {'inputSchema': deepcopy(ENVELOPE)}, 'refresh': {'trigger': 'manual'},
             'maxAgeSeconds': 0, 'timeoutSeconds': 240, 'onFailure': 'retain'}]
    ui = {'version': 1, 'defaultLocale': 'en', 'messages': {key: {'zh-Hant': value} for key, value in MESSAGES.items()}}
    document = {'id': VIEW_ID, 'name': TITLE, 'description': DESCRIPTION, 'extensions': {'phemacast:ui': ui},
        'design': {'schemaVersion': GRAMMAR, 'id': VIEW_ID, 'title': TITLE, 'params': deepcopy(PARAMETERS), 'dataRequirements': [],
            'layout': {'id': 'analyst-layout', 'type': 'grid', 'columns': 12, 'children': [
                {'id': 'analyst', 'title': TITLE, 'renderer': deepcopy(RENDERER),
                 'position': {'column': 1, 'row': 1, 'columnSpan': 12, 'rowSpan': 6}, 'media': VIEW.reference(publisher)}]}}}
    # The view's one reference runs every operation; a run may spend up to RUN_POINTS on analysts' calls.
    permissions = {'version': '1', 'references': [{'id': REFERENCE, 'effect': 'action', 'classification': 'private', 'maxPoints': RUN_POINTS}],
                   'dataFlows': [], 'mediaOrigins': [], 'localOrigins': [], 'requirements': [], 'privateFields': [],
                   'plugins': [], 'childAuthority': {}}
    return from_layout(document, owner=owner, references=refs, capabilities=[{'id': KEY, 'version': '1.0.0'}],
                       extensions={'phemacast:source_mode': 'parameters', KEY: permissions})


def shipped(publisher):
    """The Phemas this component ships, as install_pulser_local takes them."""
    return {VIEW_ID: {'name': TITLE, 'revision': PHEMA_REVISION, 'phema': phema(publisher)}}


__all__ = ['NAME', 'PHEMA_REVISION', 'VIEW', 'phema', 'shipped']
