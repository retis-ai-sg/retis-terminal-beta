"""Model servers on this computer: which ones run now, the models each can answer with, and a pulser that uses them.

Local model servers speak the OpenAI-compatible Chat Completions API on loopback, each on its own default port:
Ollama, LM Studio, vLLM, llama.cpp (and llamafile, LocalAI or mlx_lm.server on the same port), Jan, GPT4All,
Text Generation WebUI, KoboldCpp, Xinference, Docker Model Runner, SGLang and exo. `LocalModels` asks each known port,
plus any server the user added by URL, for its model list (`GET <base>/models`) and keeps the answer for a few
seconds. Products that share a default port are told apart by what their list says (`owned_by`).

Only loopback is ever asked: a prompt never leaves this computer. A server that asks for a key is reported, not used.

`LocalLLMPulser` is an `LLMPulser` whose local providers are the servers that answer now, one provider per server.
A call goes to the server that lists the requested model; with no model named, to the preferred model or the first
one found. Vendor providers in its configuration are published for the viewer's own key only and never called here.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional

import httpx
from fastapi import HTTPException

from phemacast.pulsers.llm_pulser import LOOPBACK, LLMPulser
from phemacast.pulsers.local_servers import KNOWN_SERVERS, default_url

# What a model list's `owned_by` says about the product that serves it.
OWNED_BY = {'vllm': ('vllm', 'vLLM'), 'llamacpp': ('llamacpp', 'llama.cpp'), 'sglang': ('sglang', 'SGLang'),
            'organization_owner': ('lmstudio', 'LM Studio')}
EMBEDDING = re.compile(r'embed', re.IGNORECASE)  # embedding models are listed too, but can't chat
SERVER_ID = re.compile(r'[^a-z0-9]+')
MAX_MODELS = 200
CACHE_SECONDS = 10.0
PROBE_SECONDS = 0.5
LOOKUP_SECONDS = 2.0


def loopback_url(url: Any) -> str:
    """`url` without a trailing slash when it is an http(s) address on this computer's loopback, else ''."""
    if not isinstance(url, str) or not url.strip():
        return ''
    try:
        parsed = httpx.URL(url.strip())
    except Exception:
        return ''
    if parsed.scheme not in ('http', 'https') or parsed.host.lower() not in LOOPBACK or parsed.userinfo or parsed.query:
        return ''
    return str(parsed).rstrip('/')


def _plural(count: int, word: str) -> str:
    return f'{count} {word}' + ('' if count == 1 else 's')


# What status() says, in each language a manager page or a view reads (prompits.components.health `reasons`). English
# is also the one `reason`.
LANGUAGES = ('en', 'zh-Hant')
JIT = {'en': 'turn on Just-in-Time model loading in its server settings.',
       'zh-Hant': '在其伺服器設定中開啟「Just-in-Time」模型載入。'}


def _name(server: Mapping[str, Any], language: str) -> str:
    """A server's name; one the user added without a name is called after its address."""
    if language == 'zh-Hant' and server.get('unnamed'):
        return f"{server['unnamed']} 的模型伺服器"
    return server['name']


def _note(server: Mapping[str, Any], language: str) -> str:
    """What else a server said: the models LM Studio has downloaded, or the status it answered without a model list."""
    downloaded, answered = server.get('downloaded'), server.get('answered')
    if downloaded:
        return f'已下載 {downloaded} 個模型' if language == 'zh-Hant' else _plural(downloaded, 'model') + ' downloaded'
    if answered:
        return f'回應 {answered}，但沒有模型清單' if language == 'zh-Hant' else f'answered {answered} without a model list'
    return ''


def _said(language: str, ready, empty, keyed, failed) -> str:
    """The health line in `language`, for the servers found: some with models, running with none, asking for a key,
    failing, or none at all."""
    zh = language == 'zh-Hant'
    if ready:
        return ' · '.join(f"{_name(s, language)}：{len(s['models'])} 個模型" if zh else
                          f"{_name(s, language)}: {_plural(len(s['models']), 'model')}" for s in ready)
    if empty:
        notes = [(_name(s, language), _note(s, language)) for s in empty]
        lmstudio = [s['id'] == 'lmstudio' for s in empty]
        if zh:
            parts = '、'.join(f'{name}（{note}）' if note else name for name, note in notes)
            hint = ('請在 LM Studio 載入一個模型，或' + JIT['zh-Hant']) if all(lmstudio) else \
                '請在那裡下載或載入一個模型。' + ('使用 LM Studio 時，請載入一個模型，或' + JIT['zh-Hant'] if any(lmstudio) else '')
            return f'{parts} 尚無可用的模型。{hint}'
        parts = ', '.join(f'{name} ({note})' if note else name for name, note in notes)
        hint = ('Load one in LM Studio, or ' + JIT['en']) if all(lmstudio) else \
            'Download or load one there.' + (' In LM Studio, load one or ' + JIT['en'] if any(lmstudio) else '')
        return f'No model is ready in {parts}. {hint}'
    if keyed:
        names = ('、' if zh else ', ').join(_name(s, language) for s in keyed)
        return f'{names} 需要 API 金鑰；本機 LLM 只使用不需金鑰的伺服器。' if zh else \
            f'{names} asks for an API key; Local LLM uses only servers without one.'
    if failed:
        return ('；' if zh else '; ').join(f'{_name(s, language)} {_note(s, language)}' for s in failed)[:300]
    return ('這台電腦上沒有執行中的模型伺服器。請在這台電腦啟動 Ollama、LM Studio、vLLM 或其他與 OpenAI 相容的伺服器。' if zh else
            'No local model server is running. Start Ollama, LM Studio, vLLM or another OpenAI-compatible server on this computer.')


class LocalModels:
    """The model servers that answer on this computer, asked again at most every `cache_seconds`."""

    def __init__(self, servers: Iterable[Mapping[str, Any]] = (), *, scan: bool = True, client: Optional[httpx.Client] = None,
                 cache_seconds: float = CACHE_SECONDS, probe_seconds: float = PROBE_SECONDS,
                 known: Optional[Mapping[str, Mapping[str, Any]]] = None):
        """`servers`: addresses the user added. `known`: per known server id, `enabled` (false: never asked) and its
        `url` when it runs on another address than its usual one (loopback only; anything else keeps the usual)."""
        self.added = []
        for entry in servers:
            url = loopback_url(entry.get('url') if isinstance(entry, Mapping) else entry)
            if not url:
                raise ValueError('A model server must be an http address on this computer, such as http://127.0.0.1:8000/v1.')
            name = entry.get('name') if isinstance(entry, Mapping) and isinstance(entry.get('name'), str) else ''
            address = httpx.URL(url).netloc.decode()
            self.added.append({'url': url, 'name': name.strip()[:80] or 'Model server at ' + address,
                               **({} if name.strip() else {'unnamed': address})})
        self.scan = bool(scan)
        self.known = {key: dict(value) for key, value in (known or {}).items() if isinstance(value, Mapping)}
        self.client = client or httpx.Client(follow_redirects=False, trust_env=False)
        self.cache_seconds, self.probe_seconds = cache_seconds, probe_seconds
        self._lock = threading.Lock()
        self._found: Optional[List[Dict[str, Any]]] = None
        self._at = 0.0

    # --- asking the servers --------------------------------------------------------------------------------

    def candidates(self) -> List[Dict[str, Any]]:
        """Every address to ask: the servers the user added first, then each known server's default."""
        rows = [{'id': '', 'slot': '', 'name': entry['name'], 'url': entry['url'], 'added': True,
                 **({'unnamed': entry['unnamed']} if entry.get('unnamed') else {})} for entry in self.added]
        seen = {row['url'] for row in rows}
        if self.scan:
            for known in KNOWN_SERVERS:
                chosen = self.known.get(known['id'], {})
                if chosen.get('enabled') is False:
                    continue
                url = loopback_url(chosen.get('url')) or default_url(known)
                if url not in seen:
                    seen.add(url)
                    rows.append({'id': known['id'], 'slot': known['id'], 'name': known['name'], 'url': url, 'added': False})
        return rows

    def ask(self, candidate: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """What one address answers: a server with its models, a server that wants a key or failed, or None when
        nothing that looks like a model server is there."""
        server = {'id': candidate['id'], 'slot': candidate.get('slot', ''), 'name': candidate['name'], 'url': candidate['url'],
                  'added': candidate['added'], 'models': [], 'state': 'off', 'note': '',
                  **({'unnamed': candidate['unnamed']} if candidate.get('unnamed') else {})}
        try:
            reply = self.client.get(candidate['url'] + '/models', timeout=self.probe_seconds if not candidate['added'] else LOOKUP_SECONDS)
        except httpx.HTTPError:
            return server if candidate['added'] else None
        try:
            body = reply.json()
        except ValueError:
            body = None
        if reply.status_code == 401 and isinstance(body, dict):
            return {**server, 'state': 'key'}
        rows = body.get('data') if isinstance(body, dict) and reply.status_code == 200 else None
        if not isinstance(rows, list):
            if not candidate['added']:
                return None  # another program on a known port (AirPlay on 5000, a web app on 8000)
            return {**server, 'state': 'error', 'answered': reply.status_code, 'note': f'answered {reply.status_code} without a model list'}
        owners = {row.get('owned_by') for row in rows if isinstance(row, dict)}
        for owner, (product, name) in OWNED_BY.items():
            if owner in owners and not candidate['added']:
                server['id'], server['name'] = product, name
        models = []
        for row in rows[:MAX_MODELS]:
            model = row.get('id') if isinstance(row, dict) else None
            if isinstance(model, str) and model.strip() and len(model) <= 200 and not EMBEDDING.search(model):
                models.append(model.strip())
        server['models'] = list(dict.fromkeys(models))
        server['state'] = 'ready' if server['models'] else 'empty'
        if not server['models'] and server['id'] == 'lmstudio':
            server['downloaded'] = self.lmstudio_downloaded(candidate['url'])
            server['note'] = _note(server, 'en')
        return server

    def lmstudio_downloaded(self, url: str) -> int:
        """LM Studio lists only loaded models, unless its Just-in-Time loading is on: how many it has downloaded."""
        root = url[:-len('/v1')] if url.endswith('/v1') else url
        try:
            body = self.client.get(root + '/api/v1/models', timeout=self.probe_seconds).json()
        except (httpx.HTTPError, ValueError):
            return 0
        rows = body.get('models') if isinstance(body, dict) else None
        return sum(1 for row in rows or [] if isinstance(row, dict) and row.get('type') == 'llm')

    def servers(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """The servers found now, each with a unique id: those with models first, in the order they were asked."""
        with self._lock:
            if refresh or self._found is None or time.monotonic() - self._at > self.cache_seconds:
                found, used = [], set()
                for candidate in self.candidates():
                    server = self.ask(candidate)
                    if server is None:
                        continue
                    base = server['id'] or SERVER_ID.sub('-', server['name'].lower()).strip('-') or 'server'
                    server['id'] = base if base not in used else f"{base}-{httpx.URL(server['url']).port}"
                    used.add(server['id'])
                    found.append(server)
                self._found, self._at = found, time.monotonic()
            return [dict(server, models=list(server['models'])) for server in self._found]

    # --- what a pulser and the manager use ----------------------------------------------------------------

    def provider_entries(self, refresh: bool = False) -> List[Dict[str, Any]]:
        """One `LLMPulser` provider per server that has models: OpenAI-compatible, on loopback, free."""
        return [{'id': server['id'], 'name': server['name'], 'adapter': 'openai-chat', 'local': True,
                 'base_url': server['url'], 'max_tokens_field': 'max_tokens', 'points': 0,
                 'models': [{'id': model, 'name': model, 'points': 0} for model in server['models']]}
                for server in self.servers(refresh) if server['models']]

    def details(self) -> Dict[str, Any]:
        """What the settings form shows beside each server (prompits.components.health `details`): each usual server's
        state by its own id, each added server's by its address, and the models found, to suggest as the default."""
        servers = self.servers()
        groups = {candidate['slot']: {'state': 'off', 'count': 0} for candidate in self.candidates() if candidate['slot']}
        items = {entry['url']: {'state': 'off', 'count': 0} for entry in self.added}
        for server in servers:
            state = {'state': server['state'], 'count': len(server['models'])}
            if server['slot']:
                groups[server['slot']] = {**state, 'name': server['name']}
            else:
                items[server['url']] = state
        models = list(dict.fromkeys(model for server in servers for model in server['models']))[:MAX_MODELS]
        return {'groups': groups, 'items': {'servers': items}, 'suggestions': {'model': models}}

    def has_model(self, model: str) -> bool:
        return any(model in server['models'] for server in self.servers())

    def status(self) -> Dict[str, Any]:
        """For the component health check: ready when some server has a model; `needs` data when servers run with
        none; a short line naming what was found, in English (`reason`) and in each of LANGUAGES (`reasons`)."""
        servers = self.servers()
        ready = [s for s in servers if s['models']]
        empty = [] if ready else [s for s in servers if s['state'] == 'empty']
        keyed = [] if ready or empty else [s for s in servers if s['state'] == 'key']
        failed = [] if ready or empty or keyed else [s for s in servers if s['state'] == 'error']
        reasons = {language: _said(language, ready, empty, keyed, failed) for language in LANGUAGES}
        return {'ready': bool(ready), 'needs': ['data'] if empty else [], 'reason': reasons['en'], 'reasons': reasons}


MODELS = 'llm_models'
# What a caller asks before it offers the models here: each one with the server that has it, and the one used when a
# call names none. Free, and only on this computer (a local resource's operation).
MODELS_PULSE = {
    'party': 'System', 'name': MODELS, 'pulse_address': 'local://' + MODELS, 'tags': ['llm'], 'cost': 0,
    'description': 'The models the servers on this computer can answer with now, and the one a call without a model uses.',
    'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    'output_schema': {'type': 'object', 'properties': {
        'models': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'provider': {'type': 'string'}, 'server': {'type': 'string'}, 'model': {'type': 'string'}}}},
        'default': {'type': 'object', 'properties': {'provider': {'type': 'string'}, 'model': {'type': 'string'}}},
        'reason': {'type': 'string'},
        'reasons': {'type': 'object', 'description': 'The reason in other languages: {language: text}.',
                    'additionalProperties': {'type': 'string'}}}},
    'mapping': {'models': 'models', 'default': 'default', 'reason': 'reason', 'reasons': 'reasons'},
}


class LocalLLMPulser(LLMPulser):
    """`llm_chat` on the model servers running on this computer, one provider per server, and `llm_models` listing them."""

    def __init__(self, *args, local_models: LocalModels, preferred_model: str = '', **kwargs):
        # Set before LLMPulser's own start-up, which already lists the providers to publish them.
        self.local_models = local_models
        self.preferred_model = preferred_model.strip() if isinstance(preferred_model, str) else ''
        super().__init__(*args, **kwargs)

    def provider_entries(self) -> List[Dict[str, Any]]:
        return [*self.local_models.provider_entries(), *super().provider_entries()]

    def http(self) -> httpx.Client:
        return self.local_models.client  # the one client that lists the servers also calls them

    def local_providers(self) -> List[Dict[str, Any]]:
        return [p for p in self.providers() if p.get('local') is True]

    def site_choice(self) -> Dict[str, str]:
        """The preferred model where a server has it, else the first model of the first server found."""
        local = self.local_providers()
        wanted = self.preferred_model
        for provider in local:
            for model in provider['models']:
                if wanted and model['id'] in (wanted, wanted + ':latest'):
                    return {'provider': provider['id'], 'model': model['id']}
        return {'provider': local[0]['id'], 'model': local[0]['default_model']} if local else {}

    def models(self) -> Dict[str, Any]:
        """`llm_models`: looked up afresh, since a person asks it when they are about to choose."""
        self.local_models.servers(refresh=True)
        rows = [{'provider': p['id'], 'server': p['name'], 'model': m['id']} for p in self.local_providers() for m in p['models']]
        status = {} if rows else self.local_models.status()
        return {'models': rows, 'default': self.site_choice(), 'reason': status.get('reason', ''),
                **({'reasons': status['reasons']} if status else {})}

    def fetch_pulse_payload(self, pulse_name: str, input_data: Dict[str, Any], pulse_definition: Dict[str, Any]) -> Dict[str, Any]:
        if pulse_name == MODELS:
            return self.models()
        return super().fetch_pulse_payload(pulse_name, input_data, pulse_definition)

    def resolve(self, input_data: Mapping[str, Any]):
        data = dict(input_data)
        if data.get('provider') == 'local':  # the one provider this pulser had before it served several servers
            data.pop('provider')
        model = data.get('model')
        if isinstance(model, str) and model.strip() and not self.local_models.has_model(model.strip()):
            self.local_models.servers(refresh=True)  # a model loaded or downloaded since the last look
        if not self.local_providers():
            raise HTTPException(status_code=503, detail=self.local_models.status()['reason'])
        provider, chosen = super().resolve(data)
        if provider.get('local') is not True:
            raise HTTPException(status_code=404, detail=f"{provider['name']} is called from your Terminal with your own key, not through Local LLM.")
        return provider, chosen
