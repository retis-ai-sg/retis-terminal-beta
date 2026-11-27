"""A reusable Phemar: one configured block, kept as a Phema so any Phema store can keep, list and open it.

A Phemar is the software that renders a Phema (Alvin, 2026-11-14). A reusable Phemar is that block made reusable: a
one-panel Phema whose `phemacast:reusable-phemar` extension says how a designer places it on another page:

- `panel`: the block as a page plan panel (kind, need or chart and data, inputs, width and height), with its default
  data sources (`sources`, per model: source ids in order of preference, never agent ids) and default theme
  (`theme`: an accent and series colors over the host's theme, and density);
- `parameters`: the page parameters the panel reads, as plan parameter declarations;
- `title` per language, `description`, `tags` and `version`.

The panel and parameters are kept as JSON text, so the `{"$param": name}` inputs inside them never read as this
Phema's own bindings. Nothing here knows what a panel shows: it checks the shape, makes the extension, reads it back
and scores a search.
"""
from __future__ import annotations

import copy
import json
import re

EXTENSION = 'phemacast:reusable-phemar'
VERSION = 1
NAME = re.compile(r'[^\s].{0,119}', re.S)
TAG = re.compile(r'\S{1,40}')
MAX_TAGS = 12
MAX_TEXT = 600


def block(panel, parameters=None, *, title, description='', tags=(), titles=None):
    """The extension value for a panel and the page parameters it reads; ValueError says what is wrong."""
    if not isinstance(panel, dict) or not isinstance(panel.get('id'), str) or not isinstance(panel.get('kind'), str):
        raise ValueError('A Phemar keeps one plan panel with an id and a kind.')
    title = ' '.join(str(title or '').split())
    if not NAME.fullmatch(title):
        raise ValueError('A Phemar needs a name of 1 to 120 characters.')
    kept = [t for t in dict.fromkeys(' '.join(str(tag).split()) for tag in tags or ()) if t and TAG.fullmatch(t)][:MAX_TAGS]
    value = {'version': VERSION, 'title': title, 'description': ' '.join(str(description or '').split())[:MAX_TEXT], 'tags': kept,
             'panel': json.dumps(panel, ensure_ascii=False, sort_keys=True),
             'parameters': json.dumps(parameters or {}, ensure_ascii=False, sort_keys=True)}
    if titles:
        value['titles'] = {str(k)[:12]: ' '.join(str(v).split())[:120] for k, v in titles.items() if str(v).strip()}
    return value


def read(extensions):
    """The block a Phema's extensions keep, with its panel and parameters parsed; None when it keeps none."""
    found = (extensions or {}).get(EXTENSION) if isinstance(extensions, dict) else None
    if not isinstance(found, dict) or found.get('version') != VERSION:
        return None
    try:
        panel = json.loads(found['panel'])
        parameters = json.loads(found.get('parameters') or '{}')
    except (KeyError, TypeError, ValueError):
        return None
    if not isinstance(panel, dict) or not isinstance(parameters, dict):
        return None
    return {**copy.deepcopy(found), 'panel': panel, 'parameters': parameters}


def words(text):
    return [w for w in re.split(r'[\s,，、;；/|]+', str(text or '').casefold()) if w]


def score(found, query):
    """How well a block matches a search: each query word found in its name, tags, description or titles counts; a word in
    the name or a tag counts more. 0 for no match; every block matches an empty query (score 1)."""
    asked = words(query)
    if not asked:
        return 1
    name = str(found.get('title') or '').casefold()
    tags = [str(tag).casefold() for tag in found.get('tags') or []]
    rest = (str(found.get('description') or '') + ' ' + ' '.join((found.get('titles') or {}).values())).casefold()
    total = 0
    for word in asked:
        total += 3 if word in name else 2 if any(word in tag for tag in tags) else 1 if word in rest else 0
    # A request written without spaces (中文) holds the Phemar's name or a tag inside it.
    text = str(query).casefold()
    total += (3 if name and name in text else 0) + sum(2 for tag in tags if len(tag) > 1 and tag in text)
    return total
