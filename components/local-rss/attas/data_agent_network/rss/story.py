"""What the RSS Viewer does with one story: translate it with an LLM the viewer picks, and keep the viewer's own note on
it in an AssetStorage the viewer picks.

Local RSS reaches neither itself. It answers with Terminal data requests (phemacast.core.data_requests):

- LLMs: an `agents` item for `llm_chat` lists every LLM this viewer can use, on this computer and on Plaza alike. A
  site model runs as that agent's `llm_chat` (paid in points), a model of a provider the viewer holds a key for runs
  as an `llm-generation` item (the Terminal calls the vendor with the viewer's key), and a model on this computer runs
  as its Local LLM's `llm_chat` (free). Local models are listed by each Local LLM's `llm_models`.
- Tags: the Local Analyst keeps the tags its analysts gave news items; an `agents` item for its pulse lists it, and a
  `model-data` item asks it (analyst_tags) for the tags of the stories shown, which it answers from its own index.
- Notes: an `agents` item for the AssetStorage pulses lists the stores; a note is a private markdown document there,
  tagged with the story (`asset_list`, `asset_get`, `asset_put` with `replace`, `asset_delete`).

A story is translated part by part (PART_CHARS each, at most MAX_PARTS), one call per part: a slow model on this
computer still answers each part within the view's time limit, and the story fills in as parts come back. Each part
is kept in Local RSS's library (a local service may keep its user's data); a note stays only in the store the
viewer picked.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re

from phemacast.core.data_requests import AGENTS, LLM_GENERATION, MODEL_DATA

LLM_PULSE = 'llm_chat'
MODELS_PULSE = 'llm_models'
STORE_PULSES = ['asset_put', 'asset_get', 'asset_list']
ANALYST_PULSE = 'analyst_local'
MAX_ANALYSTS = 3
NOTE_TAG = 'rssnote'
NOTE_SOURCE = 'attas.rss.note'
MAX_LOCAL_LLMS = 4
PART_CHARS = 900
MAX_PARTS = 12
MAX_TOKENS = 1200
MAX_NOTE = 20000
LANGUAGE_NAMES = {'zh-Hant': 'Traditional Chinese (Taiwan)', 'zh-Hans': 'Simplified Chinese', 'en': 'English', 'ja': 'Japanese'}
MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,199}')
PROVIDER = re.compile(r'[A-Za-z0-9_.:/-]{1,120}')
ASSET = re.compile(r'a-[0-9a-f]{24}')


def short(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def digest(*parts):
    return hashlib.sha256('\n'.join(parts).encode()).hexdigest()


def item_tag(feed, item_id):
    return 'rssitem:' + digest(feed, item_id)[:24]


def completed(entry):
    """A supplied answer's payload, or ValueError with what went wrong."""
    if not isinstance(entry, dict) or entry.get('status') != 'completed':
        raise ValueError(short((entry or {}).get('error') if isinstance(entry, dict) else '', 300) or 'No answer came back.')
    payload = entry.get('payload') if isinstance(entry.get('payload'), dict) else {}
    payload = payload.get('response', payload) if isinstance(payload.get('response'), dict) else payload
    if payload.get('error'):
        raise ValueError(short(payload['error'], 300))
    return payload


def agents_of(entry):
    if not isinstance(entry, dict) or entry.get('status') != 'completed':
        raise ValueError(short((entry or {}).get('error') if isinstance(entry, dict) else '', 300) or 'This Terminal cannot list agents.')
    return [a for a in entry.get('agents') or [] if isinstance(a, dict) and isinstance(a.get('agentId'), str)]


# --- LLMs ----------------------------------------------------------------------------------------------------------
def llm_items(supplied):
    """The data request items still needed to list LLMs, or [] when all are supplied."""
    if 'llms' not in supplied:
        return [{'id': 'llms', 'kind': AGENTS, 'pulses': [LLM_PULSE]}]
    return [item for item in local_model_items(agents_of(supplied['llms'])) if item['id'] not in supplied]


def local_model_items(agents):
    return [{'id': 'models-' + digest(a['agentId'])[:20], 'kind': MODEL_DATA, 'agentId': a['agentId'], 'pulse': MODELS_PULSE,
             'parameters': {}} for a in agents if a.get('local') is True and not a.get('llm')][:MAX_LOCAL_LLMS]


def llm_choices(supplied):
    """Every model this viewer can translate with: on this computer (free), the site's (points), and with the viewer's
    own key. Each is {source, agent, provider, model, name, by} and, for a site model, its points."""
    agents = agents_of(supplied['llms'])
    rows = []
    for agent in agents:
        by = short(agent.get('name'), 80) or 'LLM'
        llm = agent.get('llm') if isinstance(agent.get('llm'), dict) else None
        if llm:
            providers = [p for p in llm.get('providers') or [] if isinstance(p, dict) and PROVIDER.fullmatch(str(p.get('id') or ''))]
            site = llm.get('site') if isinstance(llm.get('site'), dict) else {}
            for provider in providers:
                for model in [m for m in provider.get('models') or [] if isinstance(m, dict) and MODEL.fullmatch(str(m.get('id') or ''))][:20]:
                    if provider['id'] == site.get('provider') and model['id'] == site.get('model'):
                        rows.append({'source': 'site', 'agent': agent['agentId'], 'provider': provider['id'], 'model': model['id'],
                                     'name': short(model.get('name') or model['id'], 80), 'by': by,
                                     **({'points': model['points']} if type(model.get('points')) in (int, float) else {})})
                    if provider.get('ownKey') is True:
                        rows.append({'source': 'own', 'agent': agent['agentId'], 'provider': provider['id'], 'model': model['id'],
                                     'name': short(model.get('name') or model['id'], 80), 'by': short(provider.get('name') or provider['id'], 80)})
        elif agent.get('local') is True:
            item = next((i for i in local_model_items([agent])), None)
            listed = supplied.get(item['id']) if item else None
            try:
                models = completed(listed).get('models') if listed else []
            except ValueError:
                models = []
            for model in [m for m in models or [] if isinstance(m, dict)][:40]:
                if PROVIDER.fullmatch(str(model.get('provider') or '')) and MODEL.fullmatch(str(model.get('model') or '')):
                    rows.append({'source': 'local', 'agent': agent['agentId'], 'provider': model['provider'], 'model': model['model'],
                                 'name': short(model['model'], 80), 'by': short(model.get('server') or by, 80)})
    order = {'local': 0, 'own': 1, 'site': 2}
    return sorted(rows, key=lambda r: (order[r['source']], r['by'].lower(), r['name'].lower()))


def llm_item(item_id, llm, messages):
    if llm['source'] == 'own':
        return {'id': item_id, 'kind': LLM_GENERATION, 'agentId': llm['agent'], 'provider': llm['provider'], 'model': llm['model'],
                'messages': messages, 'maxTokens': MAX_TOKENS}
    return {'id': item_id, 'kind': MODEL_DATA, 'agentId': llm['agent'], 'pulse': LLM_PULSE,
            'parameters': {'messages': messages, 'provider': llm['provider'], 'model': llm['model'], 'max_tokens': MAX_TOKENS}}


# --- translating -----------------------------------------------------------------------------------------------------
SENTENCE_ENDS = ('。', '！', '？', '；', '. ', '! ', '? ', '; ')


def parts_of(article):
    """The story's text in parts of at most PART_CHARS, cut between paragraphs, else after a sentence; at most MAX_PARTS."""
    text = (article.get('content') or article.get('summary') or '').strip()
    parts, current = [], ''
    for paragraph in (p.strip() for p in re.split(r'\n+', text)):
        if not paragraph:
            continue
        while len(paragraph) > PART_CHARS:
            cut = max(paragraph.rfind(mark, 0, PART_CHARS) for mark in SENTENCE_ENDS)
            cut = cut + 1 if cut >= PART_CHARS // 2 else PART_CHARS
            if current:
                parts.append(current)
                current = ''
            parts.append(paragraph[:cut].strip())
            paragraph = paragraph[cut:].strip()
        if current and len(current) + len(paragraph) + 2 > PART_CHARS:
            parts.append(current)
            current = paragraph
        elif paragraph:
            current = current + '\n\n' + paragraph if current else paragraph
    if current:
        parts.append(current)
    return parts[:MAX_PARTS] or ['']


def translation_messages(article, language, part=0, parts=None):
    parts = parts or parts_of(article)
    title, keep = (article.get('title') or '').strip(), 'Keep names, tickers, numbers and dates exact. Plain text only: no notes.'
    if part == 0:
        instructions = (f'Translate this news story into {LANGUAGE_NAMES[language]}. {keep} Answer with the translated headline on '
                        'the first line, an empty line, then the translated text.' +
                        (f' The text is the first of {len(parts)} parts; translate only what is given.' if len(parts) > 1 else ''))
        return [{'role': 'system', 'content': instructions}, {'role': 'user', 'content': title + ('\n\n' + parts[0] if parts[0] else '')}]
    instructions = (f'Translate this passage, part {part + 1} of {len(parts)} of a news story titled "{title}", into '
                    f'{LANGUAGE_NAMES[language]}. {keep} Answer with the translated passage only.')
    return [{'role': 'system', 'content': instructions}, {'role': 'user', 'content': parts[part]}]


def translation_of(entry, headline=True):
    """The translated headline (the first part's first line) and text from the LLM's answer."""
    payload = completed(entry)
    said = payload.get('text') if isinstance(payload.get('text'), str) else payload.get('response')
    said = str(said or '').strip()
    if not said:
        raise ValueError('The model answered with no text.')
    if not headline:
        return '', said[:20000]
    title, _, body = said.partition('\n')
    return short(title, 300), body.strip()[:20000]


# --- notes -----------------------------------------------------------------------------------------------------------
def store_choices(entry):
    return [{'agentId': a['agentId'], 'name': short(a.get('name'), 80) or 'AssetStorage', 'local': a.get('local') is True}
            for a in agents_of(entry)]


def note_list_item(store, feed, item_id):
    return {'id': 'note-list', 'kind': MODEL_DATA, 'agentId': store, 'pulse': 'asset_list',
            'parameters': {'scope': 'mine', 'owner': 'user', 'asset_type': 'document', 'tag': item_tag(feed, item_id), 'limit': 5}}


def newest_note(entry):
    assets = [a for a in completed(entry).get('assets') or [] if isinstance(a, dict) and ASSET.fullmatch(str(a.get('asset_id') or ''))]
    return max(assets, key=lambda a: str(a.get('updated_at') or ''), default=None)


def note_get_item(store, asset_id):
    return {'id': 'note-get', 'kind': MODEL_DATA, 'agentId': store, 'pulse': 'asset_get', 'parameters': {'asset_id': asset_id}}


def note_text(entry):
    payload = completed(entry)
    try:
        return base64.b64decode(payload.get('content_base64') or '', validate=True).decode('utf-8')[:MAX_NOTE]
    except (binascii.Error, UnicodeDecodeError):
        raise ValueError('That note could not be read.')


def note_put_item(store, feed, item_id, article, text, replace=None):
    content = text.encode('utf-8')
    fields = {'asset_type': 'document', 'media_type': 'text/markdown', 'name': short(article.get('title'), 200) or 'RSS note',
              'description': short(article.get('url') or feed, 1000), 'tags': [NOTE_TAG, item_tag(feed, item_id)],
              'visibility': 'private', 'owner': 'user', 'source_ref': NOTE_SOURCE,
              'content_base64': base64.b64encode(content).decode('ascii')}
    if replace:
        fields['replace'] = replace
    return {'id': 'note-put', 'kind': MODEL_DATA, 'agentId': store, 'pulse': 'asset_put', 'parameters': fields}


def note_delete_item(store, asset_id):
    return {'id': 'note-delete', 'kind': MODEL_DATA, 'agentId': store, 'pulse': 'asset_delete', 'parameters': {'asset_id': asset_id}}


# --- tags ------------------------------------------------------------------------------------------------------------
def tags_item(agent, urls, key):
    return {'id': 'tags-' + digest(agent)[:20], 'kind': MODEL_DATA, 'agentId': agent, 'pulse': ANALYST_PULSE,
            'parameters': {'operation': 'analyst_tags', 'parameters': {'urls': list(urls)}, 'request_key': key}}


def tags_of(entries):
    """{story address: [{tag, by: [{analyst, rule, tagged_at, members}]}]} from the analysts' answers; one that failed adds
    nothing. A tag's members are the named-list members the story is about, of that tag's list."""
    found = {}
    for entry in entries:
        try:
            rows = completed(entry).get('items') or []
        except ValueError:
            continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('url'), str):
                continue
            analyst = row.get('analyst') if isinstance(row.get('analyst'), dict) else {}
            entities = [m for m in row.get('entities') or [] if isinstance(m, dict)]
            tags = found.setdefault(row['url'], {})
            for tag in row.get('tags') or []:
                if not isinstance(tag, str) or not tag:
                    continue
                members = [{'code': short(m.get('code'), 40), 'name': short(m.get('name'), 80)} for m in entities if m.get('list') == tag][:20]
                tags.setdefault(tag, []).append({'analyst': short(analyst.get('name'), 80), 'rule': short(row.get('rule'), 80),
                                                 'tagged_at': short(row.get('tagged_at'), 40), 'members': members})
    return {url: [{'tag': tag, 'by': by} for tag, by in sorted(tags.items())] for url, tags in found.items()}

