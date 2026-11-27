"""The manager's immutable view release and its Phema.

The view runs in the Terminal's confined frame and reaches the manager only through the Phema's declared
composition reference. The manager serves the release as a local resource (`/local/v2/views/<release>/<file>`),
so its origin is the manager's own address on this computer (`http://127.0.0.1:<port>`).
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from prompits.core.capabilities import digest
from phemacast.agent_view.contracts import MANIFEST, CONFINED_CAPABILITY, validate_manifest, verify_assets
from phemacast.core.composition_permissions import KEY as PERMISSIONS
from phemacast.core.layout import GRAMMAR, from_layout
from .contracts import ENVELOPE, NAME, VIEW_ID

ROOT = Path(__file__).resolve().parent
UI = ROOT / 'ui'
PREFIX = '/local/v2/views/'
FILES = {'script': 'manager.js', 'style': 'manager.css'}
REFERENCE = 'mas-manager'
CHECKOUT = ROOT.parents[1]
PHEMA_VERSION = 1
TITLE = 'Retis MAS Manager'
DESCRIPTION = 'Install, update, start, stop and watch Retis components on this computer.'
MESSAGES = {TITLE: 'Retis MAS 管理員', DESCRIPTION: '在這台電腦上安裝、更新、啟動、停止並監看 Retis 元件。', 'Host': '主機'}
PARAMETERS = {
    # The computer this window manages; "this computer" until the owner's other computers can be chosen.
    'host': {'type': 'string', 'title': 'Host', 'maxLength': 128, 'default': 'this-computer', 'readOnly': True},
}

# What an AI app may ask this view to do (phemacast:ai-actions). The view's own code runs each one with the steps a click
# takes (ui/manager.js aiActions): it reads the components' status, and changes only the component settings named in
# AI_SETTINGS, of a component that is not running, as the settings form's Save does. Installing, updating, starting,
# stopping, restarting, rolling back, removing, data downloads and problem reports act on this computer, and accepting a
# component's terms is the person's, so none is offered.
# ai-actions: none, for every other component setting: Local LLM's model servers (whether each is used, its address and
# the other servers) are connections, and its default model may name a model served from elsewhere; AssetStorage's
# location decides where the person's files go (they move there) and its limits are storage ceilings. Nor for Remove's
# Keep data box and the terms an install or update asks to accept.
AI_SETTINGS = {'local-analyst': ('name',)}
# The settings in AI_SETTINGS, by field id, as the components declare them (scripts/build_components.py).
SETTING_VALUES = {
    'name': {'type': 'string', 'maxLength': 60, 'pattern': '^[^\\u0000-\\u001f\\u007f]*$',
             'description': "Local Analyst's name as this computer's Terminal lists it; empty: Local Analyst."},
}
COMPONENT = {'type': 'string', 'minLength': 1, 'maxLength': 80,
             'description': 'A component as its row names it (e.g. Local Analyst), or its id (e.g. local-analyst).'}


def ai_action(identity, title, description, effect, properties, required=()):
    return {'id': identity, 'title': title, 'description': description, 'effect': effect,
            'inputSchema': {'type': 'object', 'additionalProperties': False, 'properties': properties,
                            **({'required': list(required)} if required else {})},
            'outputSchema': {'type': 'object'}, 'maxPoints': 0, 'confirm': 'auto', 'sourceModes': ['parameters']}


VIEW_ACTIONS = {'version': '1.0.0', 'actions': [
    ai_action('describe', 'Describe the components',
              'Reads the manager\'s status again, as Refresh does, and lists each Retis component on this computer: its '
              'version, state, an update waiting, its last error, a data download, its CPU, memory and disk use, and the '
              'settings an AI app may change; then the alerts and recent events. Nothing changes.', 'read', {}),
    ai_action('set_settings', 'Change a component setting',
              'Changes a stopped component\'s settings as its Settings form\'s Save does: today only Local Analyst\'s '
              'name. Refused while the component runs, since saving restarts it (stop it in the window first), and while '
              'its settings are open in the window. Answers with the values before and after.', 'edit',
              {'component': COMPONENT, 'values': {'type': 'object', 'additionalProperties': False, 'minProperties': 1,
                                                  'properties': deepcopy(SETTING_VALUES),
                                                  'description': 'The settings to change, by name.'}},
              ['component', 'values']),
]}


def view_files():
    return [*sorted(p for p in UI.iterdir() if p.is_file() and p.suffix in ('.js', '.css')), ROOT / 'release.py', ROOT / 'contracts.py']


def bindings():
    return [{'id': REFERENCE, 'schemaDigest': digest(ENVELOPE)}]


def assets():
    return {kind: (UI / name).read_bytes() for kind, name in FILES.items()}


def capture(publisher_id, origin, destination):
    """Write one immutable release outside the checkout; return (directory, manifest).

    `publisher_id` is the id the Terminal lists this local resource under, `origin` its address on this computer.
    """
    destination = Path(destination).expanduser().resolve()
    if destination.is_relative_to(CHECKOUT):
        raise ValueError('Keep view releases outside the source checkout.')
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in view_files()}
    build = digest(hashes)
    files = assets()
    origin = str(origin).rstrip('/')
    # The actions the release offers are part of its identity: a new list is a new release, never a collision.
    release = digest({'build': build, 'publisher': publisher_id, 'origin': origin, 'bindings': bindings(),
                      'assets': {kind: hashlib.sha256(data).hexdigest() for kind, data in files.items()},
                      'aiActions': VIEW_ACTIONS})
    manifest = validate_manifest({
        'schema': MANIFEST, 'version': '1.0.0', 'publisher': {'agentId': publisher_id, 'implementationDigest': build},
        'viewId': VIEW_ID, 'release': release, 'origin': origin,
        'assets': {kind: {'path': PREFIX + release + '/' + FILES[kind], 'digest': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
                   for kind, data in files.items()},
        'html': '<main id="mas-manager"></main>',
        'parameterSchema': {'type': 'object', 'additionalProperties': False,
                            'properties': {'phema_version': {'type': 'integer', 'minimum': 1, 'maximum': 1000}}},
        'operations': [], 'dependencies': [],
        'requirements': [{'id': CONFINED_CAPABILITY['id'], 'version': CONFINED_CAPABILITY['version']}],
        'disclosure': {'codeExecution': True, 'privateData': False, 'localNetwork': True, 'confidentialRequiresEgressGuard': True},
        'extensions': {'phemacast:composition-references': {'version': '1.0.0', 'bindings': bindings()},
                       'phemacast:ai-actions': deepcopy(VIEW_ACTIONS),
                       'attas:mas-manager': {'catalogOwner': 'App Consultant', 'executionOwner': TITLE, 'sourceHashes': hashes}}},
        allow_local=True)
    verify_assets(manifest, files)
    directory = destination / release
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    written = {FILES['script']: files['script'], FILES['style']: files['style'],
               'manifest.json': json.dumps(manifest, sort_keys=True, indent=2).encode()}
    for name, data in written.items():
        target = directory / name
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError('Immutable view release collision.')
            continue
        with os.fdopen(os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400), 'wb') as stream:
            stream.write(data)
    return directory, manifest


def advertise(agent, directory, manifest):
    """Put the release in the agent card's view catalog; return the views map the local resource serves."""
    catalog = agent.agent_card.setdefault('meta', {}).setdefault('phemacast_agent_views', {'schema': 'phemacast:agent-view-catalog/1', 'views': []})
    row = {'viewId': VIEW_ID, 'release': manifest['release'], 'manifestDigest': digest(manifest),
           'manifestPath': PREFIX + manifest['release'] + '/manifest.json'}
    catalog['views'] = [view for view in catalog.get('views', []) if view.get('viewId') != VIEW_ID] + [row]
    return {manifest['release']: Path(directory)}


def phema(agent_id, owner='', extensions=None):
    """The manager Phema. It follows the manager's current view release."""
    refs = [{'id': REFERENCE, 'kind': 'pulse', 'target': {'agentId': agent_id, 'pulse': NAME}, 'inputs': {},
             'interaction': {'inputSchema': deepcopy(ENVELOPE)}, 'refresh': {'trigger': 'manual'}, 'maxAgeSeconds': 0,
             'timeoutSeconds': 120, 'onFailure': 'unavailable'}]
    media = {'agentId': agent_id, 'viewId': VIEW_ID, 'release': 'current', 'manifestDigest': 'current', 'sourceMode': 'parameters',
             'parameters': {'phema_version': PHEMA_VERSION},
             'extensions': {'phemacast:composition-references': {'version': '1.0.0', 'bindings': bindings()}}}
    ui = {'version': 1, 'defaultLocale': 'en', 'messages': {key: {'zh-Hant': value} for key, value in MESSAGES.items()}}
    document = {'id': VIEW_ID, 'name': TITLE, 'description': DESCRIPTION, 'extensions': {'phemacast:ui': ui},
                'design': {'schemaVersion': GRAMMAR, 'id': VIEW_ID, 'title': TITLE, 'params': deepcopy(PARAMETERS), 'dataRequirements': [],
                           'layout': {'id': 'mas-manager-layout', 'type': 'grid', 'columns': 12, 'children': [{
                               'id': 'manager', 'title': TITLE, 'renderer': {'id': CONFINED_CAPABILITY['id'], 'version': '1.0.0'},
                               'position': {'column': 1, 'row': 1, 'columnSpan': 12, 'rowSpan': 6}, 'media': media}]}}}
    # Every call is free and acts only on this computer's components.
    permissions = {'version': '1', 'references': [{'id': REFERENCE, 'effect': 'action', 'classification': 'private', 'maxPoints': 0}],
                   'dataFlows': [], 'mediaOrigins': [], 'localOrigins': [], 'requirements': [], 'privateFields': [], 'plugins': [], 'childAuthority': {}}
    return from_layout(document, owner=owner, references=refs, capabilities=[{'id': PERMISSIONS, 'version': '1.0.0'}],
                       extensions={'phemacast:source_mode': 'parameters', PERMISSIONS: permissions, **deepcopy(extensions or {})})
