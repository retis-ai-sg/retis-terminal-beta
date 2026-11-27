"""The RSS Feed Groups panel: browse the feed group directory and hand chosen groups to an RSS Viewer.

The site copy of the RSS source publishes this view on Plaza under its own identity (site.py). The App Consultant's
catalog stores its Phema with an agent placeholder (deploy/aws/tw-test/catalog.py) and binds it, when it is opened, to
the agent that advertises the view. The view calls only that agent: `data_fetch` for `rss.groups`, the pulse a site's
gateway forwards to a data source. Adding groups to the user's RSS Viewer goes through the Terminal's panel link
(`setPanelParameters`), which the user allows in this Phema's permissions (♧); nothing is kept on the agent.
"""
from copy import deepcopy
from pathlib import Path

from prompits.core.capabilities import digest
from phemacast.agent_view.contracts import CAPABILITY
from phemacast.agent_view.release import ViewRelease
from phemacast.core.composition_permissions import KEY
from phemacast.core.layout import GRAMMAR, from_layout

from .contracts import GROUPS_FETCH, GROUPS_REFERENCE, GROUPS_VIEW_ID, LANGUAGES
from .release import ai_action

PACKAGE = Path(__file__).resolve().parent
RENDERER = {'id': CAPABILITY['id'], 'version': CAPABILITY['version']}
# A site's gateway forwards only view files under /api/<path>/<release>/<file> that the card names.
PREFIX = '/api/rss/view-releases/'
NEED = 'rss-groups'
PULSE = 'data_fetch'
TITLE = 'RSS Feed Groups'
DESCRIPTION = 'Browse groups of checked public feeds by language and topic, and add them to your RSS Viewer.'
UI = {'version': 1, 'defaultLocale': 'en', 'messages': {
    TITLE: {'zh-Hant': 'RSS 訂閱群組'},
    DESCRIPTION: {'zh-Hant': '依語言與主題瀏覽檢查過的公開訂閱群組，並加入您的 RSS 閱讀器。'}}}
PARAMETERS = {
    'language': {'type': 'string', 'title': 'Language', 'enum': ['', *LANGUAGES], 'default': '', 'readOnly': True},
    'topic': {'type': 'string', 'title': 'Topic', 'maxLength': 31, 'default': '', 'readOnly': True},
}


# What an AI app may ask this view to do (manifest extension phemacast:ai-actions); view/groups.js runs each with the
# steps a click takes. Following groups in an open RSS Viewer only adds to the user's own subscriptions in Local RSS
# (through the panel link the user allowed, ♧). Copy as OPML is not an action.
GROUPS_ACTIONS = (
    ai_action('describe', 'Describe the feed groups',
              'Lists the groups the panel shows (name, language, topics, number of feeds), its language, topic and search, the '
              'groups chosen and the RSS Viewers open in this Terminal. Nothing changes.', 'read', {}),
    ai_action('browse', 'Browse the feed groups',
              'Lists the groups of one language or topic, or those a search finds, as the menus and search box do. The '
              'language and topic stay with this panel.', 'edit',
              {'language': {'enum': ['', *LANGUAGES], 'description': 'A language code, or empty for all.'},
               'topic': {'type': 'string', 'maxLength': 31, 'pattern': '^([A-Za-z][A-Za-z-]{0,30})?$',
                         'description': 'A topic, as describe lists them, or empty for all.'},
               'search': {'type': 'string', 'maxLength': 40}}, minProperties=1),
    ai_action('follow_in_viewer', 'Follow groups in an RSS Viewer',
              'Chooses groups and has an RSS Viewer open in this Terminal follow them, as ticking them and Follow in RSS '
              'Viewer do. Its Local RSS keeps them in sync with the directory.', 'edit',
              {'groups': {'type': 'array', 'minItems': 1, 'maxItems': 40, 'uniqueItems': True,
                          'items': {'type': 'string', 'minLength': 1, 'maxLength': 80}, 'description': 'Groups, by their names.'},
               'viewer': {'type': 'string', 'minLength': 1, 'maxLength': 200,
                          'description': 'An open RSS Viewer, by its title as describe lists it; the one chosen otherwise.'}},
              ['groups']),
)


class GroupsViewRelease(ViewRelease):
    """opml.js and groups.js in one script, without a bundler."""

    def build(self, dependencies, directory):
        entry = Path(self.sources) / self.entry
        opml = PACKAGE / 'view/opml.js'
        return (opml.read_text(encoding='utf-8') + '\n' + entry.read_text(encoding='utf-8')).encode('utf-8'), [opml, entry]


VIEW = GroupsViewRelease(view_id=GROUPS_VIEW_ID, sources=PACKAGE / 'view', entry='groups.js',
    styles=(str(PACKAGE / 'view/groups.css'),), prefix=PREFIX, html='<main id="rss-groups"></main>',
    owner='RSSDataSource', bindings=({'id': GROUPS_REFERENCE, 'schemaDigest': digest(GROUPS_FETCH)},),
    implementation=(str(PACKAGE / 'groups_release.py'), str(PACKAGE / 'contracts.py'), str(PACKAGE / 'view/opml.js')),
    ai_actions=GROUPS_ACTIONS)


def phema(publisher, owner='', extensions=None):
    """The RSS Feed Groups Phema for one publisher (or a catalog placeholder the App Consultant fills when opened)."""
    refs = [{'id': GROUPS_REFERENCE, 'kind': 'pulse', 'target': {'agentId': publisher, 'pulse': PULSE},
             'inputs': {}, 'interaction': {'inputSchema': deepcopy(GROUPS_FETCH)}, 'refresh': {'trigger': 'manual'},
             'maxAgeSeconds': 0, 'timeoutSeconds': 30, 'onFailure': 'retain'}]
    document = {'id': GROUPS_VIEW_ID, 'name': TITLE, 'description': DESCRIPTION, 'extensions': {'phemacast:ui': deepcopy(UI)},
        'design': {'schemaVersion': GRAMMAR, 'id': GROUPS_VIEW_ID, 'title': TITLE, 'params': deepcopy(PARAMETERS),
            'dataRequirements': [],
            'layout': {'id': 'rss-groups-layout', 'type': 'grid', 'columns': 12, 'children': [
                {'id': 'groups', 'title': TITLE, 'renderer': deepcopy(RENDERER),
                 'position': {'column': 1, 'row': 1, 'columnSpan': 12, 'rowSpan': 6}, 'media': VIEW.reference(publisher)}]}}}
    # Reading the directory is free. The Terminal classes every pulse as an action and refuses an action marked public
    # (phema_security.check), so the reference is private like every agent view's. Changing another panel needs the
    # viewer's own tick in this Phema's permissions.
    permissions = {'version': '1', 'references': [{'id': GROUPS_REFERENCE, 'effect': 'action', 'classification': 'private',
                                                   'maxPoints': 0}],
                   'dataFlows': [], 'mediaOrigins': [], 'localOrigins': [], 'requirements': [], 'privateFields': [],
                   'plugins': [], 'childAuthority': {}}
    return from_layout(document, owner=owner, references=refs, capabilities=[{'id': KEY, 'version': '1.0.0'}],
                       extensions={'phemacast:source_mode': 'parameters', KEY: permissions,
                                   'phemacast:ports': {'panels': 'readWrite'}, **deepcopy(extensions or {})})
