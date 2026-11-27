#!/usr/bin/env python3
"""Local Analyst on this computer: tags and scores news with the analysts its user picks; found by Bonjour.

It listens on 127.0.0.1 only and is announced by Bonjour; this computer's Terminal uses it at once, with no Plaza,
sign-in, pairing or token (docs/spec/local-resource-connections.md). It ships the Analyst Sentiment Phema. The
Terminal supplies the news and asks each analyst, the lists and rules stay in the Terminal, and the results go to the
AssetStorage the user picks. It reads only a dynamic named list's public URLs, held in memory until the list's refresh
interval passes. It is also a data source (Alvin, 2026-11-25): a stock rule's opinions are kept in its state folder
too (opinions.sqlite) and served by data_fetch to the user's sentiment strategies. --state holds this component's
identity, its view release and those opinions, outside the program folder. Its name, as the Terminal lists it, is a
setting chosen in Retis MAS Manager (component-settings.json in the same folder), applied at each start.

    python3 scripts/run_local_analyst.py --state <folder> --port 28560 [--health-port 28561]
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prompits.components.logs import configure_logging  # noqa: E402  every start's log format, set before it serves
NAME = 'Local Analyst'


def prepare(state, port):
    from phemacast.network.configure import configure, upgrade, write
    from attas.data_agent_network.analyst.local.contracts import PULSE
    from attas.data_agent_network.analyst.local.source import DATA_PULSES
    state = Path(state).expanduser().resolve()
    if state.is_relative_to(ROOT):
        raise ValueError('Keep runtime state outside the source checkout.')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = state / 'analyst.json'
    if not path.exists():
        configure(path, port=port, name=NAME, kind='pulser', execute=True, pulses=[PULSE, *DATA_PULSES])
    document = json.loads(path.read_text())
    if document['local_network']['port'] != port:
        raise ValueError('Local Analyst already uses another port. Stop it before changing its configuration.')
    network = upgrade(document['local_network'])
    # The name chosen in Retis MAS Manager; none (or one cleared) is Local Analyst again.
    network['name'] = chosen_name(state)
    # A copy set up before it served its opinions (2026-11-25) shares the data pulses from now on.
    network['pulses'] = sorted({*network.get('pulses', []), PULSE, *DATA_PULSES})
    write(path, document)
    return path


def chosen_name(state):
    from prompits.components import settings as component_settings
    name = component_settings.read(state).get('name')
    name = ' '.join(name.split())[:60] if isinstance(name, str) else ''
    return name if name and name.isprintable() else NAME


def build(path):
    from attas.data_agent_network.analyst.local.agent import build as build_pulser
    network = json.loads(Path(path).read_text())['local_network']
    return build_pulser(network, Path(path).parent / 'releases', Path(path).parent / 'opinions.sqlite')


def health():
    from prompits.components.health import health_payload
    return health_payload(ready=True, version='')


async def serve(path, health_port=None):
    from prompits.components.health import serve_health
    pulser, resource = build(path)
    await resource.start()
    checker = await serve_health(health_port, health) if health_port else None
    try:
        await resource.task
    finally:
        if checker:
            checker.close()
        await resource.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--port', type=int, default=28560)
    parser.add_argument('--health-port', type=int, help='Answer the component health check on 127.0.0.1 at this port.')
    args = parser.parse_args()
    configure_logging()  # a time and a level on every record (Retis MAS Manager → Logs, Last error)
    asyncio.run(serve(prepare(args.state, args.port), args.health_port))
