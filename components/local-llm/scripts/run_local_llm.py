#!/usr/bin/env python3
"""Local LLM pulser on this computer; the user's Terminal finds it by Bonjour and uses it at once.

Two ways to answer `llm_chat`:
- a model on this computer: any model server running here that speaks the OpenAI-compatible API. Ollama, LM Studio,
  vLLM, llama.cpp, Jan, GPT4All, Text Generation WebUI, KoboldCpp, Xinference, Docker Model Runner, SGLang and exo
  are found on their usual ports, and others can be added by URL (`--server`, loopback only). A call goes to the
  server that has the requested model; with none named, to the preferred model (`--model`) or the first one found.
  No key and no vendor: the prompt stays on this computer. Models are downloaded or loaded in the server itself.
- the user's own vendor key: the pulser publishes each vendor's API description (Anthropic, OpenAI), and the
  user's Terminal calls the vendor itself with the key kept in Terminal settings → LLM keys. The key never
  reaches this pulser.

    python3 scripts/run_local_llm.py --state <folder> --port 28480 [--model qwen3:8b]
        [--server http://127.0.0.1:9000/v1 ...] [--health-port 28481]

`--server` replaces the added servers kept in the state folder, and `--model` the preferred model. Without them, the
servers, the default model and whether the usual ports are asked come from the settings chosen in Retis MAS Manager.
"""
import argparse
import asyncio
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prompits.components.logs import configure_logging  # noqa: E402  every start's log format, set before it serves
NAME = 'Local LLM'
SITE_CONFIG = ROOT / 'phemacast/configs/llm.pulser'
OLD_DEFAULT_SERVER = 'http://127.0.0.1:11434/v1'  # the one server this pulser used before it looked for several
# What AI apps on this computer are told about the two pulses they may call at /mcp (phemacast.network.mcp).
MCP_PULSES = {
    'llm_models': 'The models the model servers on this computer (Ollama, LM Studio, vLLM, llama.cpp and others) can '
                  'answer with now, and the one a chat without a model uses.',
    'llm_chat': 'Ask a model running on this computer: give `prompt` or `messages`, and optionally a `model` from '
                'llm_models and `max_tokens`. The prompt and the answer stay on this computer.',
}


def prepare(state, port, *, model=None, servers=None):
    from phemacast.network.configure import configure, upgrade, write
    from phemacast.pulsers.local_models import KNOWN_SERVERS, MODELS, loopback_url
    from prompits.components import settings as component_settings
    state = Path(state).expanduser().resolve()
    if state.is_relative_to(ROOT):
        raise ValueError('Keep runtime state outside the source checkout.')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = state / 'llm.json'
    if not path.exists():
        configure(path, port=port, name=NAME, kind='llm', execute=True, pulses=['llm_chat', MODELS])
    document = json.loads(path.read_text())
    if document['local_network']['port'] != port:
        raise ValueError('The local LLM pulser already uses another port. Stop it before changing its configuration.')
    upgrade(document['local_network'])
    if MODELS not in document['local_network'].setdefault('pulses', []):  # shared since the pulser lists its models
        document['local_network']['pulses'].append(MODELS)
    local = document.setdefault('local_models', {'servers': [], 'model': '', 'scan': True})
    old = document.pop('local_model', None)
    if isinstance(old, dict):  # one server and one model before: an added server unless it was Ollama's default
        server = loopback_url(old.get('server'))
        if server and server != OLD_DEFAULT_SERVER and server not in [s['url'] for s in local['servers']]:
            local['servers'].append({'url': server})
        local['model'] = local.get('model') or str(old.get('model') or '')
    # What the user set in Retis MAS Manager (prompits.components.settings), unless the command line names it. A
    # server there that is not on this computer is left out rather than stopping the component.
    chosen = component_settings.read(state)
    if servers is None and isinstance(chosen.get('servers'), list):
        local['servers'] = [{'url': url} for url in dict.fromkeys(filter(None, map(loopback_url, chosen['servers'])))]
    if model is None and isinstance(chosen.get('model'), str):
        model = chosen['model']
    if isinstance(chosen.get('scan'), bool):
        local['scan'] = chosen['scan']
    # Each usual server on its own: `<id>_on` (asked or not) and `<id>_url` (another address on this computer).
    known = {}
    for server in KNOWN_SERVERS:
        on, url = chosen.get(server['id'] + '_on'), loopback_url(chosen.get(server['id'] + '_url'))
        if isinstance(on, bool) or url:
            known[server['id']] = {**({'enabled': on} if isinstance(on, bool) else {}), **({'url': url} if url else {})}
    if chosen or 'known' not in local:  # saved settings say it all; an address not on this computer keeps the usual one
        local['known'] = known
    if servers is not None:
        urls = [loopback_url(url) for url in servers]
        if not all(urls):
            raise ValueError('A model server must be an http address on this computer, such as http://127.0.0.1:8000/v1.')
        local['servers'] = [{'url': url} for url in dict.fromkeys(urls)]
    if model is not None:
        local['model'] = model.strip()
    write(path, document)
    return path


def pulser_config(document):
    """The pulser's configuration: each vendor for own-key calls only. The local servers are found while it runs."""
    site = json.loads(SITE_CONFIG.read_text())
    providers = []
    for vendor in site['providers']:
        vendor = copy.deepcopy(vendor)
        vendor.pop('key_env', None)  # this pulser has no vendor key; the Terminal calls with the user's own
        providers.append(vendor)
    from phemacast.pulsers.local_models import MODELS_PULSE
    pulses = copy.deepcopy(site['supported_pulses']) + [copy.deepcopy(MODELS_PULSE)]
    for pulse in pulses:
        pulse['cost'] = 0
    network = document['local_network']
    return {'name': NAME, 'host': '127.0.0.1', 'port': network['port'], 'plaza_url': '', 'role': 'pulser',
            'description': 'LLM chat with the models on this computer (Ollama, LM Studio, vLLM, llama.cpp and others), '
                           'or with your own vendor key from your Terminal.',
            'default_points': 0, 'max_tokens': site.get('max_tokens', 8192),
            'providers': providers, 'supported_pulses': pulses, 'local_network': network}


def local_models(document, client=None):
    from phemacast.pulsers.local_models import LocalModels
    local = document.get('local_models') or {}
    return LocalModels(local.get('servers') or [], scan=local.get('scan', True) is not False, client=client,
                       known=local.get('known') or {})


def build(path, *, client=None):
    from phemacast.network.pulser import install_pulser_local
    from phemacast.pulsers.local_models import LocalLLMPulser
    document = json.loads(Path(path).read_text())
    models = local_models(document, client)
    pulser = LocalLLMPulser(config=pulser_config(document), auto_register=False, local_models=models,
                            preferred_model=(document.get('local_models') or {}).get('model') or '')
    resource = install_pulser_local(pulser)
    from phemacast.network.mcp import install_mcp, pulse_tools
    install_mcp(resource, pulse_tools(pulser, MCP_PULSES))  # AI apps on this computer, at /mcp
    return pulser, resource, models


def health(models):
    from prompits.components.health import health_payload
    status = models.status()
    # Each server's state and the models found, beside its settings in Retis MAS Manager.
    return health_payload(ready=status['ready'], version='', reason=status['reason'], needs=status['needs'],
                          reasons=status['reasons'], details=models.details())


async def serve(path, health_port=None):
    from prompits.components.health import serve_health
    pulser, resource, models = build(path)
    await resource.start()
    checker = await serve_health(health_port, lambda: health(models)) if health_port else None
    try:
        await resource.task
    finally:
        if checker:
            checker.close()
        await resource.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--port', type=int, default=28480)
    parser.add_argument('--model', help='The model to use when a call names none, if a server has it.')
    parser.add_argument('--server', action='append', metavar='URL',
                        help='An OpenAI-compatible model server on this computer beyond the usual ports (repeatable).')
    parser.add_argument('--health-port', type=int, help='Answer the component health check on 127.0.0.1 at this port.')
    args = parser.parse_args()
    configure_logging()  # a time and a level on every record (Retis MAS Manager → Logs, Last error)
    asyncio.run(serve(prepare(args.state, args.port, model=args.model, servers=args.server), args.health_port))
