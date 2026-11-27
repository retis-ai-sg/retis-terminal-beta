"""Local RSS's own operations: its user's subscriptions, the articles it keeps, and every RSS source the user can reach.

One pulse, `rss_local`, takes an envelope `{operation, parameters, request_key}` and answers `{response, channel_receipt}`
or a Terminal data request (phemacast.core.data_requests): Local RSS has no Plaza, so the Terminal lists the RSS
sources this user can reach (an `agents` item for `rss_fetch`) and, when the viewer picks another one, calls that
source's `data_fetch` (rss.groups, rss.read_feeds) for it, then calls again with what it supplied. Articles read by
another source are kept here like Local RSS's own reads.

A background reader reads the subscribed feeds that are due, every READ_SECONDS, while Local RSS runs.

One story (story.py): the viewer translates it with an LLM it picks and keeps its own note on it in an AssetStorage it
picks; both run through Terminal data requests too, and only the translation is kept here.
"""
from __future__ import annotations

import re
import threading

from phemacast.core.data_requests import AGENTS, MAX_ITEMS, MODEL_DATA, REQUEST, SUPPLIED

from .contracts import LOCAL_ENVELOPE, LOCAL_OPERATIONS, LOCAL_PULSE, checked
from .feeds import read_feeds
from .groups import directory as local_directory, groups as local_groups
from .library import Library
from . import story
from .subscriptions import LOCAL, Subscriptions

READ_SECONDS = 15
BATCH = 20  # feeds per read, as rss.read_feeds takes
PER_FEED = 30
REFRESH_LIMIT = 60  # feeds one Refresh reads itself; the background reader takes the rest
SOURCES_ITEM = 'sources'
DIRECTORY_ITEM = 'directory'
# A note keeps its line breaks and tabs; any other control character is refused.
NOTE_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def chunks(items, size):
    return [items[start:start + size] for start in range(0, len(items), size)]


def fetched(entry):
    """What a source's data_fetch gave, from one supplied answer; ValueError when it failed."""
    if not isinstance(entry, dict) or entry.get('status') != 'completed':
        raise ValueError(str((entry or {}).get('error') or 'That RSS source did not answer.')[:300]
                         if isinstance(entry, dict) else 'That RSS source did not answer.')
    payload = entry.get('payload')
    payload = payload.get('response', payload) if isinstance(payload, dict) else {}
    if isinstance(payload, dict) and payload.get('status') == 'failed':
        raise ValueError(str(payload.get('error') or 'That RSS source refused the request.')[:300])
    data = payload.get('data', payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        raise ValueError('That RSS source answered with something this Local RSS cannot read.')
    return data


class Local:
    def __init__(self, folder, *, getter, directory=local_directory):
        self.subscriptions = Subscriptions(folder, directory=directory)
        self.library = Library(folder)
        self.getter = getter
        self.directory = directory
        self.agent_id = ''  # set when the local resource is set up: local-<resourceId>
        self.stop_event = threading.Event()
        self.thread = None
        self.reading = threading.Lock()

    # --- the background reader -----------------------------------------------------------------------------------
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, name='local-rss-reader', daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _loop(self):
        while not self.stop_event.wait(READ_SECONDS):
            try:
                self.read(self.library.due(self.subscriptions.active()))
            except Exception:  # one bad pass never stops the reader; the next pass tries again
                pass

    def read(self, feeds):
        """Read these feeds ({url, name}) here and keep what they gave. Returns (read, failed)."""
        done = failed = 0
        with self.reading:
            for batch in chunks(list(feeds), BATCH):
                ask = [{'url': f['url'], 'name': f.get('name') or '', **self.library.validators(f['url'])} for f in batch]
                results = read_feeds(ask, PER_FEED, getter=self.getter, max_bytes=None)['feeds']
                self.library.store(results)
                done += sum(r['status'] in ('ready', 'not_modified') for r in results)
                failed += sum(r['status'] == 'error' for r in results)
        return done, failed

    # --- the pulse -----------------------------------------------------------------------------------------------
    def dispatch(self, data):
        receipt = data.get('request_key') if isinstance(data, dict) and isinstance(data.get('request_key'), str) else None
        try:
            supplied = data.get(SUPPLIED) if isinstance(data, dict) else None
            data = {k: v for k, v in (data or {}).items() if k != SUPPLIED}
            # A note's text is checked on its own: it keeps its line breaks, which every other text refuses.
            raw = data.get('parameters') if isinstance(data.get('parameters'), dict) else None
            note = raw.get('text') if raw is not None and data.get('operation') == 'rss_save_note' else None
            if isinstance(note, str):
                if len(note) > story.MAX_NOTE or NOTE_CONTROL.search(note):
                    raise ValueError(f'A note is at most {story.MAX_NOTE} characters, with no control characters but line breaks and tabs.')
                data = {**data, 'parameters': {**raw, 'text': ''}}
            envelope = checked(LOCAL_ENVELOPE, data, 'Local RSS')
            operation = envelope['operation']
            if operation not in LOCAL_OPERATIONS:
                raise ValueError('Choose a Local RSS operation.')
            params = checked(LOCAL_OPERATIONS[operation], envelope['parameters'], operation.replace('_', ' '))
            if isinstance(note, str):
                params['text'] = note
            supplied = supplied if isinstance(supplied, dict) else {}
            answer = getattr(self, '_' + operation)(params, supplied, envelope['request_key'])
            return answer if answer.get('schema') == REQUEST else {'response': answer, 'channel_receipt': envelope['request_key']}
        except ValueError as error:
            return {'error': str(error)[:300], **({'channel_receipt': receipt} if receipt else {})}

    def request(self, items, receipt):
        return {'schema': REQUEST, 'requests': items, 'channel_receipt': receipt}

    def remote(self, source):
        """Another RSS source the viewer picked, or None for this Local RSS."""
        return source if source and source != self.agent_id else None

    def subscriptions_answer(self, **extra):
        snapshot = self.subscriptions.snapshot()
        status = self.library.status([f['url'] for f in snapshot['feeds']])
        for feed in snapshot['feeds']:
            feed['status'] = status[feed['url']]
            feed['every'] = self.subscriptions.every(feed)
        return {'kind': 'subscriptions', 'self': self.agent_id, **snapshot, **extra}

    def _changed(self, **extra):
        self.library.forget(f['url'] for f in self.subscriptions.snapshot()['feeds'])
        return self.subscriptions_answer(**extra)

    # --- operations ------------------------------------------------------------------------------------------------
    def _rss_sources(self, params, supplied, receipt):
        if SOURCES_ITEM not in supplied:
            return self.request([{'id': SOURCES_ITEM, 'kind': AGENTS, 'pulses': ['rss_fetch']}], receipt)
        entry = supplied[SOURCES_ITEM]
        agents = entry.get('agents') if isinstance(entry, dict) and entry.get('status') == 'completed' else []
        listed, seen = [], set()
        for agent in agents or []:
            if isinstance(agent, dict) and isinstance(agent.get('agentId'), str) and agent['agentId'] not in seen:
                seen.add(agent['agentId'])
                listed.append({'agentId': agent['agentId'], 'name': str(agent.get('name') or agent['agentId'])[:120],
                               'local': agent.get('local') is True, 'self': agent['agentId'] == self.agent_id})
        if self.agent_id and self.agent_id not in seen:
            listed.insert(0, {'agentId': self.agent_id, 'name': 'Local RSS', 'local': True, 'self': True})
        listed.sort(key=lambda a: (not a['self'], not a['local'], a['name'].lower()))
        return {'kind': 'sources', 'sources': listed}

    def _rss_subscriptions(self, params, supplied, receipt):
        return self.subscriptions_answer()

    def _rss_articles(self, params, supplied, receipt):
        feeds = self.subscriptions.active()
        if params.get('group'):
            feeds = [f for f in feeds if f['group'] == params['group']]
        if params.get('feed'):
            feeds = [f for f in feeds if f['url'] == params['feed']]
        return {'kind': 'articles', 'revision': self.subscriptions.revision,
                'items': self.library.articles(feeds, params.get('limit', 300))}

    def _rss_article(self, params, supplied, receipt):
        return {'kind': 'article', 'article': self.library.article(params['feed'], params['id'])}

    def _chosen(self, params):
        feeds = self.subscriptions.active()
        if params.get('group'):
            feeds = [f for f in feeds if f['group'] == params['group']]
        if params.get('feed'):
            feeds = [f for f in feeds if f['url'] == params['feed']]
        return feeds

    def _rss_refresh(self, params, supplied, receipt):
        feeds = self._chosen(params)
        source = self.remote(params.get('source'))
        if source is None:
            # Feeds read in the last minute wait; the rest beyond REFRESH_LIMIT are left to the background reader.
            recent = {f['url'] for f in feeds} - {f['url'] for f in self.library.due([{**f, 'every': 60} for f in feeds])}
            wanted = [f for f in feeds if f['url'] not in recent][:REFRESH_LIMIT]
            done, failed = self.read(wanted)
            return {'kind': 'refreshed', 'source': self.agent_id, 'read': done, 'failed': failed,
                    'waiting': max(0, len(feeds) - len(recent) - len(wanted))}
        batches = chunks(feeds, BATCH)[:MAX_ITEMS]
        items = [{'id': f'read-{n}', 'kind': MODEL_DATA, 'agentId': source, 'pulse': 'data_fetch',
                  'parameters': {'endpoint_id': 'rss.read_feeds', 'parameters': {
                      'feeds': [{'url': f['url'], 'name': f['name'][:100], **self.library.validators(f['url'])} for f in batch],
                      'limit': PER_FEED}}} for n, batch in enumerate(batches)]
        if not items:
            return {'kind': 'refreshed', 'source': source, 'read': 0, 'failed': 0, 'waiting': 0}
        if any(item['id'] not in supplied for item in items):
            return self.request(items, receipt)
        done = failed = 0
        problems = []
        for item in items:
            try:
                results = fetched(supplied[item['id']]).get('feeds') or []
            except ValueError as error:
                problems.append(str(error))
                failed += len(item['parameters']['parameters']['feeds'])
                continue
            results = [r for r in results if isinstance(r, dict)]
            self.library.store(results)
            done += sum(r.get('status') in ('ready', 'not_modified') for r in results)
            failed += sum(r.get('status') == 'error' for r in results)
        return {'kind': 'refreshed', 'source': source, 'read': done, 'failed': failed, 'waiting': 0,
                **({'error': problems[0]} if problems else {})}

    def _listing(self, params, supplied, receipt):
        """The directory from the chosen source: Local RSS's own copy, or a data request to the other source."""
        source = self.remote(params.get('source'))
        query = {key: params[key] for key in ('language', 'topic', 'query') if key in params}
        if source is None:
            return LOCAL, local_groups(query.get('language'), query.get('topic'), query.get('query'))
        if DIRECTORY_ITEM not in supplied:
            return source, self.request([{'id': DIRECTORY_ITEM, 'kind': MODEL_DATA, 'agentId': source, 'pulse': 'data_fetch',
                                          'parameters': {'endpoint_id': 'rss.groups', 'parameters': query}}], receipt)
        listing = fetched(supplied[DIRECTORY_ITEM])
        if not isinstance(listing.get('groups'), list):
            raise ValueError('That RSS source has no feed group directory.')
        self.subscriptions.sync_from(source, listing)
        return source, listing

    def _rss_directory(self, params, supplied, receipt):
        source, listing = self._listing(params, supplied, receipt)
        if listing.get('schema') == REQUEST:
            return listing
        groups = []
        for group in listing['groups']:
            if not isinstance(group, dict) or not isinstance(group.get('id'), str):
                continue
            held = self.subscriptions.followed(source, group['id'])
            groups.append({**group, 'followed': held['key'] if held else None})
        return {'kind': 'directory', 'source': self.agent_id if source == LOCAL else source, 'version': listing.get('version'),
                'reviewed': listing.get('reviewed'), 'topics': listing.get('topics') or [], 'groups': groups}

    def _rss_follow(self, params, supplied, receipt):
        source, listing = self._listing({'source': params.get('source')}, supplied, receipt)
        if listing.get('schema') == REQUEST:
            return listing
        group = next((g for g in listing['groups'] if isinstance(g, dict) and g.get('id') == params['id']), None)
        if group is None:
            raise ValueError('That RSS source lists no group ' + params['id'] + '.')
        self.subscriptions.follow(group, source=source, version=listing.get('version'), name=params.get('name'))
        return self._changed()

    def _rss_set_group(self, params, supplied, receipt):
        self.subscriptions.set_group(params['key'], enabled=params.get('enabled'), refresh_seconds=params.get('refresh_seconds'),
                                     name=params.get('name'), remove=params.get('remove', False))
        return self._changed()

    def _rss_add_feed(self, params, supplied, receipt):
        self.subscriptions.add_feed(params['url'], name=params.get('name', ''), group=params.get('group', ''),
                                    refresh_seconds=params.get('refresh_seconds'))
        return self._changed()

    def _rss_update_feed(self, params, supplied, receipt):
        changes = {key: params[key] for key in ('enabled', 'refresh_seconds', 'name', 'group') if key in params}
        self.subscriptions.update_feed(params['url'], **changes)
        return self._changed()

    def _rss_remove_feed(self, params, supplied, receipt):
        self.subscriptions.remove_feed(params['url'])
        return self._changed()

    def _rss_import(self, params, supplied, receipt):
        counts = self.subscriptions.import_feeds(params['feeds'])
        return self._changed(imported={key: counts[key] for key in ('added', 'listed', 'over', 'refused')})

    # --- one story (story.py) --------------------------------------------------------------------------------------
    def _rss_llms(self, params, supplied, receipt):
        needed = story.llm_items(supplied)
        if needed:
            return self.request(needed, receipt)
        return {'kind': 'llms', 'llms': story.llm_choices(supplied)}

    def _rss_translate(self, params, supplied, receipt):
        """One part of a story's translation (the first carries the headline); the viewer asks for each part in turn."""
        feed, item, language, part = params['feed'], params['id'], params['language'], params.get('part', 0)
        article = self.library.article(feed, item)
        parts = story.parts_of(article)
        if part >= len(parts):
            raise ValueError(f'That story has {len(parts)} parts to translate.')
        base = {'kind': 'translation', 'feed': feed, 'id': item, 'language': language, 'part': part, 'parts': len(parts)}
        kept = None if params.get('fresh') else self.library.translation(feed, item, language, part)
        if kept:
            return {**base, **kept, 'kept': True}
        if 'translate' not in supplied:
            messages = story.translation_messages(article, language, part, parts)
            return self.request([story.llm_item('translate', params['llm'], messages)], receipt)
        title, text = story.translation_of(supplied['translate'], headline=part == 0)
        self.library.keep_translation(feed, item, language, part, title, text, params['llm']['model'])
        return {**base, 'title': title, 'text': text, 'model': params['llm']['model'], 'kept': False}

    def _rss_stores(self, params, supplied, receipt):
        if 'stores' not in supplied:
            return self.request([{'id': 'stores', 'kind': AGENTS, 'pulses': story.STORE_PULSES}], receipt)
        return {'kind': 'stores', 'stores': story.store_choices(supplied['stores'])}

    def _rss_note(self, params, supplied, receipt):
        store, feed, item = params['store'], params['feed'], params['id']
        if 'note-list' not in supplied:
            return self.request([story.note_list_item(store, feed, item)], receipt)
        newest = story.newest_note(supplied['note-list'])
        if newest is None:
            return {'kind': 'note', 'store': store, 'asset_id': None, 'text': '', 'updated': None}
        if 'note-get' not in supplied:
            return self.request([story.note_get_item(store, newest['asset_id'])], receipt)
        return {'kind': 'note', 'store': store, 'asset_id': newest['asset_id'], 'text': story.note_text(supplied['note-get']),
                'updated': newest.get('updated_at')}

    def _rss_save_note(self, params, supplied, receipt):
        store, feed, item, text, kept = params['store'], params['feed'], params['id'], params['text'], params.get('asset_id')
        if not text.strip():
            # An emptied note is removed from the store.
            if not kept:
                return {'kind': 'note', 'store': store, 'asset_id': None, 'text': '', 'saved': False}
            if 'note-delete' not in supplied:
                return self.request([story.note_delete_item(store, kept)], receipt)
            story.completed(supplied['note-delete'])
            return {'kind': 'note', 'store': store, 'asset_id': None, 'text': '', 'saved': True, 'deleted': True}
        if 'note-put' not in supplied:
            try:
                article = self.library.article(feed, item)
            except ValueError:
                article = {'title': '', 'url': ''}  # the note is the viewer's own; it outlives the article here
            return self.request([story.note_put_item(store, feed, item, article, text, kept)], receipt)
        saved = story.completed(supplied['note-put']).get('asset') or {}
        return {'kind': 'note', 'store': store, 'asset_id': saved.get('asset_id'), 'text': text,
                'updated': saved.get('updated_at'), 'saved': True}

    def _rss_tags(self, params, supplied, receipt):
        """The tags analysts gave these stories: the Local Analyst (listed by the Terminal) answers from its own index."""
        if 'analysts' not in supplied:
            return self.request([{'id': 'analysts', 'kind': AGENTS, 'pulses': [story.ANALYST_PULSE]}], receipt)
        try:
            analysts = story.agents_of(supplied['analysts'])[:story.MAX_ANALYSTS]
        except ValueError:
            analysts = []
        items = [story.tags_item(a['agentId'], params['urls'], receipt) for a in analysts]
        needed = [item for item in items if item['id'] not in supplied]
        if needed:
            return self.request(needed, receipt)
        return {'kind': 'tags', 'tags': story.tags_of([supplied[item['id']] for item in items])}


__all__ = ['LOCAL_PULSE', 'Local']
