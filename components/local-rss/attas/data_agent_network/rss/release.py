"""Local RSS's RSS Viewer: its portable Phema and its two immutable view releases, using existing host capabilities.

The Phema (revision 5) names the reader (`rss-reader`, view/reader.js): articles and subscriptions Local RSS keeps,
read and changed through its one `rss_local` reference. Copies of the Phema from before revision 5 name the earlier
viewer (`rss-viewer`, view/viewer.js), which keeps its feeds as page values; Local RSS still serves it, so those copies
keep working until their user takes the update. A Terminal's agent-view channel lets a view call only the agent that
published it (phemacast/agent_view/candidate/composition-channel.mjs); other RSS sources are reached through Local RSS's
data requests."""
import json
from copy import deepcopy
from pathlib import Path
from prompits.core.capabilities import digest
from phemacast.agent_view.contracts import CAPABILITY
from phemacast.agent_view.release import ViewRelease
from phemacast.core.composition_permissions import KEY
from phemacast.core.layout import GRAMMAR, from_layout
from .contracts import (AGENT_ID, GROUP_ENTRY, GROUP_ID, GROUP_NAME, INPUT, LOCAL_ENVELOPE, LOCAL_PULSE, LOCAL_REFERENCE,
                        PULSE, READER_VIEW_ID, REFERENCE, VIEW_ID, VIEWER_FEED, record)
from .defaults import FEEDS as DEFAULT_FEEDS, GROUP_OF

PACKAGE = Path(__file__).resolve().parent
# The panel renderer a Terminal installs for agent views (1.0.0). The release's own manifest asks the confined runtime
# for CONFINED_CAPABILITY (1.1.0); asking the panel for 1.1.0 left the reader "Renderer unavailable" in 28410.
RENDERER = {'id': CAPABILITY['id'], 'version': CAPABILITY['version']}
# A Terminal keeps its own copy of a Phema a component ships and takes a new one only when the advertised revision
# goes up (attas/data_terminal_phemar/phema_library.py). Raise it with every change to the Phema; a test pins the
# digest of each revision. 2: the reader reads its own source, with no source picker, and asks for renderer 1.0.0.
# 3: it starts with the source's default feeds (defaults.py) and keeps up to MAX_FEEDS of them.
# 4: feeds in groups, up to 100; a `groups` page value names the groups taken from a feed group directory; other panels
# may change `feeds` and `groups` (the site's RSS Feed Groups panel adds groups) but only read `source_agent`.
# 5: Local RSS keeps the subscriptions (AGENTS.md: a local service may keep its user's data, Alvin 2026-11-24): the
# reader view, one `rss_local` reference, `source_agent` as the RSS source picked, and `follow` for groups another
# panel asks it to follow. `feeds` and `groups` stay, read once, so an earlier copy's list moves into Local RSS.
PHEMA_REVISION = 5
MAX_FEEDS = 100  # the viewer reads them INPUT's 20 at a time; 100 feeds stay well under a panel value's 32 KB
MAX_GROUPS = 40
PLACEHOLDER = '/*rss-defaults*/[]'


def starting_feeds():
    """The feeds a new RSS Viewer starts with: every default feed, in its group, enabled, read every 15 minutes."""
    return [{'url': feed['url'], 'name': feed['name'], 'enabled': True, 'refresh_seconds': 900, 'group': GROUP_OF[feed['id']]}
            for feed in DEFAULT_FEEDS]

# Where a local resource serves its view's files (phemacast/network/service.py): a Terminal reads a local publisher's
# manifest and assets only under this path (phemacast/agent_view/transport.py LocalPublisherTransport).
PREFIX = '/local/v2/views/'
# A group another panel asks this viewer to follow (the site's RSS Feed Groups panel): a directory group id and the RSS
# source whose directory lists it. The viewer has Local RSS follow it and clears the list.
FOLLOW = record({'id': GROUP_ID, 'source': AGENT_ID, 'name': GROUP_NAME}, ['id'])
PARAMETERS = {
    'source_agent': {'type': 'string', 'title': 'RSS source', 'maxLength': 200, 'readOnly': True},
    'follow': {'type': 'array', 'title': 'Groups to follow', 'maxItems': MAX_GROUPS, 'items': deepcopy(FOLLOW), 'default': [],
               'readOnly': True},
    # An earlier copy's feed list and directory groups, moved into Local RSS the first time the reader opens.
    'feeds': {'type': 'array', 'title': 'Feeds (before revision 5)', 'maxItems': MAX_FEEDS, 'items': deepcopy(VIEWER_FEED),
              'default': [], 'readOnly': True},
    'groups': {'type': 'array', 'title': 'Groups (before revision 5)', 'maxItems': MAX_GROUPS, 'items': deepcopy(GROUP_ENTRY),
               'default': [], 'readOnly': True},
}
# What other open panels may do with this viewer's page values once the user allows it (♧): ask it to follow groups,
# never point it at another source or change its feeds.
PORTS = {'share': {'source_agent': 'read', 'follow': 'readWrite', 'feeds': 'read', 'groups': 'read'}}


def script() -> str:
    """opml.js, then viewer.js with the default feeds written in, so a viewer that has none can start with them."""
    text = (PACKAGE / 'view/viewer.js').read_text(encoding='utf-8')
    assert text.count(PLACEHOLDER) == 1, 'viewer.js must name the default feeds once'
    listed = json.dumps([{'url': f['url'], 'name': f['name'], 'group': GROUP_OF[f['id']]} for f in DEFAULT_FEEDS],
                        ensure_ascii=False, separators=(',', ':'))
    return (PACKAGE / 'view/opml.js').read_text(encoding='utf-8') + '\n' + text.replace(PLACEHOLDER, listed)


# What an AI app may ask these views to do (manifest extension phemacast:ai-actions). Each view's own code runs every
# action with the steps a click takes (the `actions` reader.js, viewer.js and groups.js register), so Local RSS (or, for
# a viewer from before revision 5, the Terminal's page values) keeps the subscriptions as it always does. Subscribing
# and following, turning feeds and groups on or off, their frequencies and names change only the user's own
# subscriptions: they are edits. Never declared: Remove, Remove group and Unfollow (deletes), Translate (it pays a model
# or the user's own key), Open article, and a note left empty (it removes the note). Items are named as people name
# them: a feed by its name or address, a group or a story by its name or title.
def ai_action(identity, title, description, effect, properties, required=(), points=0, modes=('parameters',), **schema):
    return {'id': identity, 'title': title, 'description': description, 'effect': effect,
            'inputSchema': {'type': 'object', 'additionalProperties': False, 'properties': deepcopy(properties),
                            **({'required': list(required)} if required else {}), **schema},
            'outputSchema': {'type': 'object'}, 'maxPoints': points, 'confirm': 'auto', 'sourceModes': list(modes)}


FREQUENCY = {'enum': [0, 60, 300, 900, 1800, 3600, 21600, 86400], 'description': 'Seconds between reads; 0 reads it only on Refresh.'}
FEED_URL = {'type': 'string', 'minLength': 8, 'maxLength': 2048, 'pattern': '^[Hh][Tt][Tt][Pp][Ss]?://',
            'description': "The feed's public http or https address."}
FEED_REF = {'type': 'string', 'minLength': 1, 'maxLength': 2048, 'description': 'A feed, by its name or address.'}
GROUP_REF = {'type': 'string', 'minLength': 1, 'maxLength': 80, 'description': 'A group, by its name.'}
NEW_NAME = {'type': 'string', 'minLength': 1, 'maxLength': 60, 'pattern': '\\S', 'description': 'The new name.'}
TITLE = {'type': 'string', 'minLength': 1, 'maxLength': 500, 'description': 'A story, by its title as describe lists it.'}
OPML = {'type': 'string', 'minLength': 1, 'maxLength': 200000, 'description': 'OPML text, as another reader exports it.'}
NEW_FEED = {'url': FEED_URL, 'name': {'type': 'string', 'maxLength': 100}, 'group': {'type': 'string', 'maxLength': 60},
            'frequency_seconds': FREQUENCY}
SHOW = {'filter': {'type': 'string', 'maxLength': 2048, 'description': 'A group or feed to list, by its name; empty for all feeds.'},
        'search': {'type': 'string', 'maxLength': 200}, 'article': TITLE}
DESCRIBE = ('Lists the subscriptions by group (each feed\'s name, address, whether it is on and how often it is read), the '
            'stories the list shows (titles, feeds, times) and the story open. Nothing changes.')
READER_ACTIONS = (
    ai_action('describe', 'Describe the RSS Viewer', DESCRIBE + ' Also the RSS source picked and the tab shown.', 'read', {},
              modes=('parameters', 'snapshot')),
    ai_action('show', 'Show stories or subscriptions',
              'Shows the Articles or Subscriptions tab, lists one group or feed, searches the list, or opens a story, as '
              'clicking them does. Opening a story answers with its title, feed, time, address and the start of its text.',
              'view', {'tab': {'enum': ['articles', 'subscriptions']}, **SHOW}, minProperties=1),
    ai_action('add_feed', 'Subscribe to a feed',
              'Subscribes to a feed by its address, as Add feed does, in a group of your own (new or existing) or none, '
              'and reads it at once.', 'edit', NEW_FEED, ['url']),
    ai_action('follow_group', 'Follow a feed group',
              'Follows a group from the feed group directory of the RSS source picked (or the one named), as Follow does: '
              'Local RSS keeps it in sync with the directory. Answers with the group\'s feeds.', 'edit',
              {'group': {**GROUP_REF, 'description': "A directory group, by its name (in any of its languages)."},
               'source': {'type': 'string', 'minLength': 1, 'maxLength': 120, 'description': 'An RSS source, by its name.'}}, ['group']),
    ai_action('set_group', 'Change a group',
              'Turns a group of your subscriptions on or off, sets its default frequency or renames it, as its controls do. '
              'Only what is named changes.', 'edit',
              {'group': GROUP_REF, 'on': {'type': 'boolean'}, 'frequency_seconds': FREQUENCY, 'name': NEW_NAME}, ['group'], minProperties=2),
    ai_action('set_feed', 'Change a feed',
              'Turns a subscribed feed on or off or sets its own frequency (null for its group\'s default), as its controls '
              'do.', 'edit', {'feed': FEED_REF, 'on': {'type': 'boolean'},
                              'frequency_seconds': {**FREQUENCY, 'enum': [None, *FREQUENCY['enum']],
                                                    'description': "Seconds between reads, or null for the group's default."}},
              ['feed'], minProperties=2),
    ai_action('import_opml', 'Import OPML', 'Subscribes to the feeds in OPML text, as Import OPML does; feeds already listed '
              'are skipped.', 'edit', {'opml': OPML}, ['opml']),
    ai_action('choose_source', 'Choose the RSS source',
              'Picks the RSS source groups are browsed and feeds refreshed through, as the RSS source menu does.', 'edit',
              {'source': {'type': 'string', 'minLength': 1, 'maxLength': 120, 'description': 'An RSS source, by its name.'}}, ['source']),
    ai_action('refresh', 'Refresh', 'Reads the subscribed feeds now through the RSS source picked, as Refresh does. Free.',
              'run', {}),
    ai_action('save_note', 'Keep a note on a story',
              'Keeps your note on a story in the AssetStorage picked for notes (or the one named), as Save note does. It '
              'replaces the note kept on that story; refused while a note on it is being typed in the window.', 'edit',
              {'article': TITLE, 'text': {'type': 'string', 'minLength': 1, 'maxLength': 20000, 'pattern': '\\S'},
               'store': {'type': 'string', 'minLength': 1, 'maxLength': 120, 'description': 'An AssetStorage, by its name.'}},
              ['article', 'text']),
)
# The RSS Viewer from before revision 5, which keeps its feeds as page values.
VIEWER_ACTIONS = (
    ai_action('describe', 'Describe the RSS Viewer', DESCRIBE, 'read', {}, modes=('parameters', 'snapshot')),
    ai_action('show', 'Show stories', 'Lists one group or feed, searches the list, or opens a story, as clicking them does.',
              'view', SHOW, minProperties=1),
    ai_action('add_feed', 'Subscribe to a feed', 'Adds a feed by its address, as Add feed does, in a group or none.', 'edit',
              NEW_FEED, ['url']),
    ai_action('set_feed', 'Change a feed', "Turns a feed on or off, sets its frequency, or changes its name or group, as its "
              'controls and Edit do. Only what is named changes.', 'edit',
              {'feed': FEED_REF, 'on': {'type': 'boolean'}, 'frequency_seconds': FREQUENCY,
               'name': {'type': 'string', 'maxLength': 100}, 'group': {'type': 'string', 'maxLength': 60}}, ['feed'], minProperties=2),
    ai_action('set_group', 'Change a group', "Turns a group's feeds on or off or renames it, as its controls do.", 'edit',
              {'group': GROUP_REF, 'on': {'type': 'boolean'}, 'name': NEW_NAME}, ['group'], minProperties=2),
    ai_action('import_opml', 'Import OPML', 'Adds the feeds in OPML text, as Import OPML does; feeds already listed are '
              'skipped.', 'edit', {'opml': OPML}, ['opml']),
    ai_action('refresh', 'Refresh', 'Reads every feed that is on now, as Refresh does. Free.', 'run', {}),
)


class RSSViewRelease(ViewRelease):
    def build(self, dependencies, directory):
        entry = Path(self.sources) / self.entry
        return script().encode('utf-8'), [PACKAGE / 'view/opml.js', entry, PACKAGE / 'defaults.py']


VIEW = RSSViewRelease(view_id=VIEW_ID, sources=PACKAGE / 'view', entry='viewer.js',
    styles=(str(PACKAGE / 'view/viewer.css'),), prefix=PREFIX, html='<main id="rss-viewer"></main>',
    owner='RSSDataSource', bindings=({'id': REFERENCE, 'schemaDigest': digest(INPUT)},),
    implementation=(str(PACKAGE / 'release.py'), str(PACKAGE / 'contracts.py'), str(PACKAGE / 'defaults.py'),
                    str(PACKAGE / 'view/opml.js')), ai_actions=VIEWER_ACTIONS)


class ReaderRelease(ViewRelease):
    """opml.js and reader.js in one script, without a bundler."""

    def build(self, dependencies, directory):
        entry = Path(self.sources) / self.entry
        opml = PACKAGE / 'view/opml.js'
        return (opml.read_text(encoding='utf-8') + '\n' + entry.read_text(encoding='utf-8')).encode('utf-8'), [opml, entry]


READER = ReaderRelease(view_id=READER_VIEW_ID, sources=PACKAGE / 'view', entry='reader.js',
    styles=(str(PACKAGE / 'view/viewer.css'), str(PACKAGE / 'view/reader.css')), prefix=PREFIX,
    html='<main id="rss-viewer"></main>', owner='RSSDataSource',
    bindings=({'id': LOCAL_REFERENCE, 'schemaDigest': digest(LOCAL_ENVELOPE)},),
    implementation=(str(PACKAGE / 'release.py'), str(PACKAGE / 'contracts.py'), str(PACKAGE / 'view/opml.js')),
    ai_actions=READER_ACTIONS)


def phema(publisher, owner=''):
    params = deepcopy(PARAMETERS)
    # The RSS source the reader browses and refreshes through; its own Local RSS until the user picks another.
    params['source_agent']['default'] = publisher
    refs = [{'id': LOCAL_REFERENCE, 'kind': 'pulse', 'target': {'agentId': publisher, 'pulse': LOCAL_PULSE},
             'inputs': {}, 'interaction': {'inputSchema': deepcopy(LOCAL_ENVELOPE)}, 'refresh': {'trigger': 'manual'},
             'maxAgeSeconds': 0, 'timeoutSeconds': 120, 'onFailure': 'retain'}]
    document = {'id': VIEW_ID, 'name': 'RSS Viewer', 'description': 'Read the RSS and Atom feeds you subscribe to in Local RSS; browse and follow feed groups.',
        'design': {'schemaVersion': GRAMMAR, 'id': VIEW_ID, 'title': 'RSS Viewer', 'params': params, 'dataRequirements': [],
            'layout': {'id': 'rss-layout', 'type': 'grid', 'columns': 12, 'children': [
                {'id': 'reader', 'title': 'RSS Viewer', 'renderer': deepcopy(RENDERER),
                 'position': {'column': 1, 'row': 1, 'columnSpan': 12, 'rowSpan': 6}, 'media': READER.reference(publisher)}]}}}
    permissions = {'version': '1', 'references': [{'id': LOCAL_REFERENCE, 'effect': 'action', 'classification': 'private',
                                                   'maxPoints': 0}],
                   'dataFlows': [], 'mediaOrigins': [], 'localOrigins': [], 'requirements': [], 'privateFields': [],
                   'plugins': [], 'childAuthority': {}}
    return from_layout(document, owner=owner, references=refs, capabilities=[{'id': KEY, 'version': '1.0.0'}],
                       extensions={'phemacast:source_mode': 'parameters', KEY: permissions, 'phemacast:ports': deepcopy(PORTS)})
