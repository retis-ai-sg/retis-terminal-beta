"""An agent's own view as an immutable release: capture it outside the checkout, advertise it, serve it.

Every agent that serves a view did this with its own copy of the same code; this is the generic version. A release
holds only the view's script and style. Its data never enters it: the view asks its own agent through the declared
composition references, as the Terminal's confined host allows.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from prompits.core.capabilities import digest
from phemacast.agent_view.contracts import MANIFEST, CONFINED_CAPABILITY, validate_manifest, verify_assets

ROOT = Path(__file__).resolve().parents[2]
CATALOG = 'phemacast:agent-view-catalog/1'
BINDINGS = 'phemacast:composition-references'


@dataclass(frozen=True)
class ViewRelease:
    """One view an agent serves. `sources` is the folder of its own view code; only it, Phemacast and Prompits may
    enter the bundle."""
    view_id: str
    sources: Path
    entry: str
    styles: tuple
    prefix: str
    html: str
    owner: str
    bindings: tuple = ()
    parameters: dict = field(default_factory=dict)
    implementation: tuple = ()
    # The actions an AI app may ask this view to take (phemacast:ai-actions, contracts.validate_ai_actions); the view's
    # own code registers each with phemacastAgentView.actions.handle. Empty: the view offers none.
    ai_actions: tuple = ()

    files = {'script': 'view.js', 'style': 'view.css'}

    def binding_list(self):
        return [dict(row) for row in self.bindings]

    def parameter_schema(self, agent_id):
        return {'type': 'object', 'additionalProperties': False, 'required': ['publisher_id'],
                'properties': {'publisher_id': {'const': agent_id}, **deepcopy(self.parameters)}}

    def build(self, dependencies, directory):
        esbuild = Path(dependencies).expanduser().resolve() / 'node_modules/.bin/esbuild'
        if not esbuild.is_file():
            raise FileNotFoundError('esbuild is required to capture the view ' + self.view_id + ': ' + str(esbuild))
        output, meta = Path(directory) / self.files['script'], Path(directory) / 'meta.json'
        subprocess.run([str(esbuild), str(Path(self.sources) / self.entry), '--bundle', '--format=iife', '--minify',
                        '--outfile=' + str(output), '--metafile=' + str(meta)], cwd=ROOT, check=True, capture_output=True)
        inputs = [(ROOT / path).resolve() for path in json.loads(meta.read_text())['inputs']]
        allowed = [ROOT / 'phemacast', ROOT / 'prompits', Path(self.sources).resolve()]
        if any(not any(path.is_relative_to(layer) for layer in allowed) for path in inputs):
            raise ValueError('The view ' + self.view_id + ' may bundle only its own code, Phemacast and Prompits.')
        return output.read_bytes(), inputs

    def style(self):
        return b'\n'.join(path.read_bytes() for path in map(Path, self.styles))

    def capture(self, agent_id, origin, destination, *, dependencies):
        """Write the release outside the checkout; the same sources give the same release."""
        destination = Path(destination).expanduser().resolve()
        if destination.is_relative_to(ROOT):
            raise ValueError('Keep view releases outside the source checkout.')
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.TemporaryDirectory(dir=destination, prefix='.build-') as directory:
            script, inputs = self.build(dependencies, directory)
        style = self.style()
        sources = [*inputs, *map(Path, self.styles), *map(Path, self.implementation)]
        hashes = {str(Path(p).resolve().relative_to(ROOT)): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sorted(set(sources))}
        implementation = digest(hashes)
        assets = {'script': script, 'style': style}
        actions = [deepcopy(dict(row)) for row in self.ai_actions]
        release = digest({'build': implementation, 'assets': {k: hashlib.sha256(v).hexdigest() for k, v in assets.items()},
                          'bindings': self.binding_list(), 'publisher': agent_id, 'origin': origin, 'view': self.view_id,
                          **({'aiActions': actions} if actions else {})})
        manifest = validate_manifest({
            'schema': MANIFEST, 'version': '1.0.0', 'publisher': {'agentId': agent_id, 'implementationDigest': implementation},
            'viewId': self.view_id, 'release': release, 'origin': origin,
            'assets': {key: {'path': self.prefix + release + '/' + self.files[key], 'digest': hashlib.sha256(data).hexdigest(),
                             'bytes': len(data)} for key, data in assets.items()},
            'html': self.html, 'parameterSchema': self.parameter_schema(agent_id), 'operations': [], 'dependencies': [],
            'requirements': [{'id': CONFINED_CAPABILITY['id'], 'version': CONFINED_CAPABILITY['version']}],
            'disclosure': {'codeExecution': True, 'privateData': True, 'localNetwork': origin.startswith('http://'),
                           'confidentialRequiresEgressGuard': True},
            'extensions': {BINDINGS: {'version': '1.0.0', 'bindings': self.binding_list()},
                           'phemacast:view-release': {'executionOwner': self.owner, 'sourceHashes': hashes},
                           **({'phemacast:ai-actions': {'version': '1.0.0', 'actions': actions}} if actions else {})}},
            allow_local=True)
        verify_assets(manifest, assets)
        target = destination / release
        target.mkdir(exist_ok=True, mode=0o700)
        for name, data in {self.files['script']: script, self.files['style']: style,
                           'manifest.json': json.dumps(manifest, sort_keys=True, indent=2).encode()}.items():
            path = target / name
            if path.exists() and path.read_bytes() != data:
                raise ValueError('Immutable view release collision: ' + self.view_id)
            if not path.exists():
                with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400), 'wb') as stream:
                    stream.write(data)
        return target, manifest

    def load(self, directory, agent_id):
        directory = Path(directory).expanduser().resolve()
        manifest = validate_manifest(json.loads((directory / 'manifest.json').read_text()), allow_local=True)
        if manifest['publisher']['agentId'] != agent_id or manifest['viewId'] != self.view_id:
            raise ValueError('This view release belongs to another publisher or view.')
        verify_assets(manifest, {key: (directory / name).read_bytes() for key, name in self.files.items()})
        return directory, manifest

    def advertise(self, card, manifest):
        """Name the current release in the card's agent-view catalog, replacing this view's older entry."""
        meta = card.setdefault('meta', {})
        catalog = meta.setdefault('phemacast_agent_views', {'schema': CATALOG, 'views': []})
        catalog['views'] = [v for v in catalog.get('views', []) if v.get('viewId') != self.view_id] + [
            {'viewId': self.view_id, 'release': manifest['release'], 'manifestDigest': digest(manifest),
             'manifestPath': self.prefix + manifest['release'] + '/manifest.json'}]
        return catalog

    def serve(self, app, directory, release):
        """Serve one release's three files on `app`."""
        from fastapi import HTTPException
        from fastapi.responses import FileResponse
        names = ('manifest.json', *self.files.values())

        async def asset(asset: str):
            if asset not in names:
                raise HTTPException(404, 'View asset unavailable.')
            return FileResponse(Path(directory) / asset, headers={'Cache-Control': 'public,max-age=31536000,immutable',
                                                                  'X-Content-Type-Options': 'nosniff'})
        app.add_api_route(self.prefix + release + '/{asset}', asset, methods=['GET'])

    def reference(self, publisher, parameters=None):
        """The agent-view node media for this view: it follows the publisher's current release."""
        return {'agentId': publisher, 'viewId': self.view_id, 'release': 'current', 'manifestDigest': 'current',
                'sourceMode': 'parameters', 'parameters': {'publisher_id': publisher, **deepcopy(parameters or {})},
                'extensions': {BINDINGS: {'version': '1.0.0', 'bindings': self.binding_list()}}}
