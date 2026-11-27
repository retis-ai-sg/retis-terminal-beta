"""The site copy of the RSS source: on Plaza it publishes the RSS Feed Groups panel (groups_release.py).

A copy runs as a site source when its config names a Plaza and a `view_releases` folder and has no `local_network`
block; Local RSS, on the user's computer, publishes the RSS Viewer through `local_extras` instead. The release names
the agent's Plaza identity and advertised address, so a new identity (the first registration) needs a new capture; the
card then names it and the agent registers once more. Releases live in `view_releases`, outside the checkout.
"""
from __future__ import annotations

from pathlib import Path

from .groups_release import VIEW


def enabled(source) -> bool:
    config = getattr(source, '_config_data', None) or {}
    return bool(config.get('plaza_url')) and bool(config.get('view_releases')) and not config.get('local_network')


def current(source) -> bool:
    """Whether the card already names a release captured for this agent's identity."""
    manifest = getattr(source, 'rss_groups_manifest', None)
    return bool(manifest) and manifest['publisher']['agentId'] == str(getattr(source, 'agent_id', '') or '')


def publish(source) -> bool:
    """Capture the panel for this agent's identity and address, serve it and name it on the card. False before the
    agent has a Plaza identity."""
    if not enabled(source) or not getattr(source, 'agent_id', None) or getattr(source, 'app', None) is None:
        return False
    origin = str(source._resolve_advertised_address()).rstrip('/')
    directory, manifest = VIEW.capture(str(source.agent_id), origin, Path(source._config_data['view_releases']).expanduser(),
                                       dependencies=None)
    served = getattr(source, 'rss_groups_served', None)
    if served is None:
        served = source.rss_groups_served = set()
    if manifest['release'] not in served:
        VIEW.serve(source.app, directory, manifest['release'])
        served.add(manifest['release'])
    VIEW.advertise(source.agent_card, manifest)
    source.rss_groups_manifest = manifest
    return True
