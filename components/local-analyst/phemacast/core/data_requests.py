"""Data a processor asks its caller's host to fetch, and the host's answer.

A processor (an agent that only computes) never fetches market data itself.
When an operation needs data it answers with a data request instead of a
result. The user's host fetches every item for that user, then calls the same
operation again with the answers as `supplied_data`. Hosts know data models and
sources, never the processor's business.

Six kinds of item exist:
- `model-data`: call one source pulse with exact parameters (for example a
  canonical model request); the answer's `payload` is the source-shaped result.
- `model-sources`: list the sources this user can draw the named canonical
  models from; the answer's `sources` describes each one.
- `llm-generation`: run `messages` with the user's own key for one LLM provider
  an agent publishes (`agentId`, `provider`, `model`, optional `maxTokens`); the
  answer's `payload` carries the generated `text`. The key never leaves the
  host. Message content is text, or text and pictures as vendor-neutral parts,
  and `webFetch` ({"url"}) lets the model read one web page (llm_content.py).
  A processor that wants the site's model instead names that agent's
  `llm_chat` pulse in a `model-data` item.
- `library-blocks`: the person's blocks (Phemas carrying
  `phemacast:reusable-phemar`) in the host's own library. `op` is `list`
  (optional `query`), `get` or `remove` (`block`, the library's record id) or
  `keep` (`name`, `phema`). The host answers from its own store, with no agent
  call, and lets a processor see and change only the blocks it kept itself.
- `local-resources`: the programs on the host's own computer (found there,
  never listed by Plaza) that run every pulse in `pulses` (1 to 8 names). The
  answer's `resources` gives each one's `agentId` and `name`, nothing else; a
  processor then names that id in `model-data` items.
- `agents`: every agent this user can use that runs every pulse in `pulses`
  (1 to 8 names), on the host's own computer and listed by Plaza alike, in one
  list. The answer's `agents` gives each one's `agentId`, `name` and `local`
  (true for a program on the host's computer) and, for an agent that publishes
  LLM providers, `llm`: its default (`site`: provider and model) and the
  providers a viewer may call with their own key (`providers`). A processor
  that runs on the person's own computer has no Plaza, so this is how it
  learns the site's agents beside the local ones.

An item may carry `echo`, an object the host returns unchanged with its answer.
"""
from __future__ import annotations

import copy
import json
import re

from .llm_content import check_messages, https_url

REQUEST = 'phemacast:data-request/1'
SUPPLIED = 'supplied_data'
MODEL_DATA = 'model-data'
MODEL_SOURCES = 'model-sources'
LLM_GENERATION = 'llm-generation'
LIBRARY_BLOCKS = 'library-blocks'
BLOCK_OPS = ('list', 'get', 'keep', 'remove')
BLOCK_ID = re.compile(r'p-[0-9a-f]{24}')
LOCAL_RESOURCES = 'local-resources'
AGENTS = 'agents'
MAX_PULSES = 8
KINDS = (MODEL_DATA, MODEL_SOURCES, LLM_GENERATION, LIBRARY_BLOCKS, LOCAL_RESOURCES, AGENTS)
MAX_MESSAGES = 16
MAX_MESSAGE_BYTES = 100_000
MAX_GENERATION_TOKENS = 4096
ROLES = ('system', 'user', 'assistant')
MAX_ITEMS = 16
MAX_ROUNDS = 8
MAX_SUPPLIED_BYTES = 6_000_000
IDENTIFIER = re.compile(r'[A-Za-z0-9_.:-]{1,128}')
NAME = re.compile(r'[A-Za-z0-9_.-]{1,120}')


def is_request(value):
    return isinstance(value, dict) and value.get('schema') == REQUEST


def checked_request(value):
    """A bounded, well-formed data request; anything else is refused."""
    if not is_request(value) or not isinstance(value.get('requests'), list):
        raise ValueError('Malformed data request.')
    items = value['requests']
    if not 1 <= len(items) <= MAX_ITEMS:
        raise ValueError(f'A data request names 1 to {MAX_ITEMS} items.')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not IDENTIFIER.fullmatch(item['id']) or item['id'] in seen:
            raise ValueError('Every requested item needs its own identifier.')
        seen.add(item['id'])
        if 'echo' in item and not isinstance(item['echo'], dict):
            raise ValueError('An echo is an object.')
        if item.get('kind') == MODEL_DATA:
            if (set(item) - {'id', 'kind', 'agentId', 'pulse', 'parameters', 'echo'}
                    or not isinstance(item.get('agentId'), str) or not item['agentId']
                    or not isinstance(item.get('pulse'), str) or not NAME.fullmatch(item['pulse'])
                    or not isinstance(item.get('parameters'), dict)):
                raise ValueError('A model-data item names one source agent, its pulse and parameters.')
        elif item.get('kind') == MODEL_SOURCES:
            models = item.get('models')
            if (set(item) - {'id', 'kind', 'models', 'echo'} or not isinstance(models, list) or not 1 <= len(models) <= 16
                    or any(not isinstance(m, str) or not NAME.fullmatch(m) for m in models)):
                raise ValueError('A model-sources item names 1 to 16 canonical models.')
        elif item.get('kind') == LLM_GENERATION:
            messages = item.get('messages')
            tokens = item.get('maxTokens', MAX_GENERATION_TOKENS)
            if (set(item) - {'id', 'kind', 'agentId', 'provider', 'model', 'messages', 'maxTokens', 'webFetch', 'echo'}
                    or not isinstance(item.get('agentId'), str) or not item['agentId']
                    or not isinstance(item.get('provider'), str) or not NAME.fullmatch(item['provider'])
                    or not isinstance(item.get('model'), str) or not NAME.fullmatch(item['model'])
                    or type(tokens) is not int or not 1 <= tokens <= MAX_GENERATION_TOKENS):
                raise ValueError('An llm-generation item names one LLM provider and model, and 1 to 16 messages under 100 KB.')
            try:
                # Text stays under 100 KB; at most two pictures travel beside it, each bounded on its own.
                check_messages(messages, roles=ROLES, max_text_bytes=MAX_MESSAGE_BYTES, max_messages=MAX_MESSAGES)
                if 'webFetch' in item:
                    if not isinstance(item['webFetch'], dict) or set(item['webFetch']) != {'url'}:
                        raise ValueError('webFetch names one page: {"url": "https://..."}.')
                    https_url(item['webFetch']['url'])
            except ValueError as exc:
                raise ValueError('An llm-generation item names one LLM provider and model, and 1 to 16 messages under 100 KB: ' + str(exc)) from None
        elif item.get('kind') == LIBRARY_BLOCKS:
            op = item.get('op')
            fields = {'list': {'query'}, 'get': {'block'}, 'remove': {'block'}, 'keep': {'name', 'phema'}}.get(op, set())
            query, name = item.get('query', ''), item.get('name')
            if (op not in BLOCK_OPS or set(item) - {'id', 'kind', 'op', 'echo', *fields}
                    or not isinstance(query, str) or len(query) > 200
                    or op in ('get', 'remove') and not (isinstance(item.get('block'), str) and BLOCK_ID.fullmatch(item['block']))
                    or op == 'keep' and not (isinstance(name, str) and 1 <= len(name.strip()) <= 120 and isinstance(item.get('phema'), dict))):
                raise ValueError("A library-blocks item lists, gets, keeps or removes one block in the person's own library.")
        elif item.get('kind') in (LOCAL_RESOURCES, AGENTS):
            pulses = item.get('pulses')
            if (set(item) - {'id', 'kind', 'pulses', 'echo'} or not isinstance(pulses, list) or not 1 <= len(pulses) <= MAX_PULSES
                    or any(not isinstance(p, str) or not NAME.fullmatch(p) for p in pulses) or len(set(pulses)) != len(pulses)):
                raise ValueError(f"A {item['kind']} item names 1 to {MAX_PULSES} different pulses.")
        else:
            raise ValueError('Unknown data request item.')
    return copy.deepcopy(items)


def answer(item, **fields):
    """One supplied answer, carrying the item's echo back."""
    return {**fields, **({'echo': copy.deepcopy(item['echo'])} if 'echo' in item else {})}


def bounded(supplied):
    size = len(json.dumps(supplied, separators=(',', ':'), default=str))
    if size > MAX_SUPPLIED_BYTES:
        raise ValueError('Requested data exceeds 6 MB; narrow the time range or interval.')
    return supplied
