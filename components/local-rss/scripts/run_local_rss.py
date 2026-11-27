#!/usr/bin/env python3
"""Local RSS on this computer: reads the public RSS and Atom feeds its user adds; the Terminal finds it by Bonjour.

It listens on 127.0.0.1 only and is announced by Bonjour; this computer's Terminal uses it at once, with no Plaza,
sign-in, pairing or token (docs/spec/local-resource-connections.md). It ships the RSS Viewer Phema. A local service may
keep its user's data (AGENTS.md): --state, outside the program folder, holds this source's identity, its viewer
releases, the user's subscriptions (subscriptions.json) and the articles read for them (articles.sqlite), which it
reads in the background while it runs.

    python3 scripts/run_local_rss.py --state <folder> --port 28520 [--health-port 28521]
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prompits.components.logs import configure_logging  # noqa: E402  every start's log format, set before it serves
NAME = 'Local RSS'


def prepare(state, port):
    from phemacast.network.configure import configure, upgrade, write
    state = Path(state).expanduser().resolve()
    if state.is_relative_to(ROOT):
        raise ValueError('Keep runtime state outside the source checkout.')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = state / 'source.json'
    if not path.exists():
        configure(path, port=port, name=NAME, kind='data-source', execute=True)
    document = json.loads(path.read_text())
    if document['local_network']['port'] != port:
        raise ValueError('Local RSS already uses another port. Stop it before changing its configuration.')
    upgrade(document['local_network'])
    write(path, document)
    return path


def build(path):
    from attas.data_agent_network.rss.source import RSSDataSource
    config = json.loads(Path(path).read_text())['local_network']
    source = RSSDataSource(config={'name': NAME, 'host': '127.0.0.1', 'port': config['port'], 'plaza_url': '',
                                   'local_network': config, 'data_fetch_cost_points': 0,
                                   'view_releases': str(Path(path).parent / 'releases'),
                                   'subscriptions_state': str(Path(path).parent)},
                           auto_register=False)
    if source.local and config.get('allowExecution'):  # AI apps on this computer read its feeds at /mcp
        from attas.data_agent_network.rss.mcp_tools import TOOLS
        from phemacast.network.mcp import install_mcp
        install_mcp(source._local_resource, TOOLS)
    return source, source._local_resource


def health(source, resource):
    from prompits.components.health import health_payload
    return health_payload(ready=True, version='')


async def serve(path, health_port=None):
    from prompits.components.health import serve_health
    source, resource = build(path)
    await resource.start()
    source.start_reader()
    checker = await serve_health(health_port, lambda: health(source, resource)) if health_port else None
    try:
        await resource.task
    finally:
        if checker:
            checker.close()
        await resource.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--port', type=int, default=28520)
    parser.add_argument('--health-port', type=int, help='Answer the component health check on 127.0.0.1 at this port.')
    args = parser.parse_args()
    configure_logging()  # a time and a level on every record (Retis MAS Manager → Logs, Last error)
    asyncio.run(serve(prepare(args.state, args.port), args.health_port))
