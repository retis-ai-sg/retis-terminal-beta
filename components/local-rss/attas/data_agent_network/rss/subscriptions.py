"""The RSS subscriptions Local RSS keeps for its user, in its own state folder.

A local service belongs to its user, so it may keep the user's data (AGENTS.md, Alvin 2026-11-24). Local RSS keeps the
groups and feeds its user subscribes to in `<state>/subscriptions.json`; the site copy keeps none.

- A group is followed from a feed group directory (Local RSS's own copy, groups.py, or another RSS source's) or is the
  user's own. A followed group is synced: when the directory's version changes, feeds it added come in, feeds it
  dropped go, and the user's own choices stay (a feed turned off stays off; a frequency override stays). A directory
  group is followed once: following it again from another source that lists the same group keeps the one it has.
- Each group has a default frequency (seconds; 0 reads it only on request) and a feed may override it.
- `revision` goes up with every change, so a view can tell cheaply whether to read the subscriptions again.
- A feed added without a group goes into one own group named in Local RSS's language (未分組); an older Local RSS
  named it `Other`, and that group takes the new name when the file is read.

The file is replaced atomically and readable only by its owner.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import threading

from .feeds import public_url
from .groups import directory as local_directory

SCHEMA = 'rss-subscriptions/1'
FILE = 'subscriptions.json'
FREQUENCIES = (0, 60, 300, 900, 1800, 3600, 21600, 86400)
DEFAULT_REFRESH = 900
MAX_FEEDS = 200
MAX_GROUPS = 60
LOCAL = 'local'  # a group followed from Local RSS's own copy of the directory
# A new Local RSS follows the directory groups that hold its 24 default feeds (defaults.py).
FIRST_GROUPS = ('tw-stocks', 'tw-industry-tech', 'tw-international', 'tw-finance', 'tw-personal-finance', 'hk-finance',
                'cn-international', 'cn-business')
# The own group of feeds added without a group, in Local RSS's language; `Other` is what an older Local RSS named it.
UNSORTED = {'zh-Hant': '未分組', 'zh-Hans': '未分组', 'ja': '未分類', 'en': 'Other'}
LEGACY_UNSORTED = 'Other'


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def text(value, limit):
    return ' '.join(str(value or '').split())[:limit]


def frequency(value, *, allow_none=False):
    if value is None and allow_none:
        return None
    if value not in FREQUENCIES:
        raise ValueError('Choose a frequency of ' + ', '.join(str(f) for f in FREQUENCIES) + ' seconds.')
    return value


class Subscriptions:
    """One user's subscriptions in one state folder. Every change is saved before it returns."""

    def __init__(self, folder, *, directory=local_directory, language='zh-Hant'):
        self.folder = Path(folder).expanduser()
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.folder / FILE
        self.directory = directory
        self.language = language
        self.lock = threading.RLock()
        with self.lock:
            self.document = self._load()

    # --- storage -----------------------------------------------------------------------------------------------
    def _load(self):
        if self.path.exists():
            document = json.loads(self.path.read_text(encoding='utf-8'))
            if document.get('schema') != SCHEMA or not isinstance(document.get('groups'), list) \
                    or not isinstance(document.get('feeds'), list):
                raise ValueError('The RSS subscriptions file is not one this Local RSS can read.')
            self.document = document
            renamed = self._rename_unsorted()
            if self.sync_local():
                return self.document
            if renamed:
                self._save()
            return document
        self.document = {'schema': SCHEMA, 'revision': 0, 'updated': now_iso(), 'groups': [], 'feeds': []}
        listed = {group['id']: group for group in self.directory()['groups']}
        for group_id in FIRST_GROUPS:
            if group_id in listed:
                self._follow(listed[group_id], LOCAL, self.directory()['version'], None)
        self._save()
        return self.document

    def _save(self):
        document = self.document
        document['revision'] = int(document.get('revision') or 0) + 1
        document['updated'] = now_iso()
        temporary = self.path.with_name(self.path.name + '.' + secrets.token_hex(4) + '.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(document, handle, ensure_ascii=False, indent=1)
        os.replace(temporary, self.path)
        os.chmod(self.path, 0o600)

    def snapshot(self):
        with self.lock:
            return {'revision': self.document['revision'], 'updated': self.document['updated'],
                    'directory_version': self.directory()['version'],
                    'groups': deepcopy(self.document['groups']), 'feeds': deepcopy(self.document['feeds'])}

    @property
    def revision(self):
        return self.document['revision']

    # --- lookups -------------------------------------------------------------------------------------------------
    def group(self, key):
        found = next((g for g in self.document['groups'] if g['key'] == key), None)
        if found is None:
            raise ValueError('That group is not in your subscriptions.')
        return found

    def feed(self, url):
        found = next((f for f in self.document['feeds'] if f['url'] == url), None)
        if found is None:
            raise ValueError('That feed is not in your subscriptions.')
        return found

    def followed(self, source, directory_id):
        return next((g for g in self.document['groups'] if g['source'] == 'directory' and g.get('directory_id') == directory_id
                     and g.get('from') == source), None)

    def every(self, feed):
        """The feed's frequency in seconds: its own override, else its group's default."""
        if feed.get('refresh_seconds') is not None:
            return feed['refresh_seconds']
        group = next((g for g in self.document['groups'] if g['key'] == feed['group']), None)
        return group['refresh_seconds'] if group else DEFAULT_REFRESH

    def active(self):
        """The feeds to read: on, in a group that is on, each with its effective frequency."""
        with self.lock:
            on = {g['key']: g for g in self.document['groups'] if g['enabled']}
            return [{'url': f['url'], 'name': f['name'], 'group': f['group'], 'every': self.every(f)}
                    for f in self.document['feeds'] if f['enabled'] and f['group'] in on]

    # --- following directory groups -------------------------------------------------------------------------
    def _name(self, group, name):
        names = group.get('name') or {}
        return text(name or names.get(self.language) or names.get('en') or group['id'], 60)

    def _follow(self, group, source, version, name):
        existing = self.followed(source, group['id'])
        if existing is None:
            # Already followed from another RSS source: one group per directory id, synced from where it was followed.
            elsewhere = next((g for g in self.document['groups'] if g['source'] == 'directory'
                              and g.get('directory_id') == group['id']), None)
            if elsewhere is not None:
                return elsewhere
            if len(self.document['groups']) >= MAX_GROUPS:
                raise ValueError(f'Keep up to {MAX_GROUPS} groups.')
            existing = {'key': 'g-' + secrets.token_hex(6), 'name': self._name(group, name), 'source': 'directory',
                        'directory_id': group['id'], 'from': source, 'version': version, 'language': group.get('language', ''),
                        'enabled': True, 'refresh_seconds': DEFAULT_REFRESH}
            self.document['groups'].append(existing)
        self._sync(existing, group, version)
        return existing

    def _sync(self, held, group, version):
        """Bring a followed group to the directory's feeds: new ones in, dropped ones out, the user's choices kept."""
        listed = {}
        for feed in group['feeds']:
            listed.setdefault(public_url(feed['url']), feed)
        mine = [f for f in self.document['feeds'] if f['group'] == held['key']]
        for feed in mine:
            if feed.get('origin') == 'directory' and feed['url'] not in listed:
                self.document['feeds'].remove(feed)
        have = {f['url'] for f in self.document['feeds']}
        for url, feed in listed.items():
            if url in have:
                continue
            if len(self.document['feeds']) >= MAX_FEEDS:
                raise ValueError(f'Keep up to {MAX_FEEDS} feeds.')
            self.document['feeds'].append({'url': url, 'name': text(feed.get('name'), 100), 'group': held['key'],
                                           'enabled': True, 'refresh_seconds': None, 'origin': 'directory'})
        held['version'] = version

    def follow(self, group, *, source=LOCAL, version=None, name=None):
        """Follow a directory group (a group as rss.groups lists it), or bring it up to date if already followed."""
        with self.lock:
            self._follow(group, source, version, name)
            self._save()
            return self.snapshot()

    def sync_local(self):
        """Sync the groups followed from Local RSS's own directory copy when its version has changed."""
        with self.lock:
            copy = self.directory()
            listed = {g['id']: g for g in copy['groups']}
            changed = False
            for held in self.document['groups']:
                if held['source'] == 'directory' and held.get('from') == LOCAL and held.get('version') != copy['version'] \
                        and held['directory_id'] in listed:
                    self._sync(held, listed[held['directory_id']], copy['version'])
                    changed = True
            if changed:
                self._save()
            return changed

    def sync_from(self, source, listing):
        """Sync the groups followed from `source` with a directory answer from it (rss.groups)."""
        with self.lock:
            listed = {g['id']: g for g in listing.get('groups') or []}
            changed = False
            for held in self.document['groups']:
                if held['source'] == 'directory' and held.get('from') == source and held['directory_id'] in listed \
                        and held.get('version') != listing.get('version'):
                    self._sync(held, listed[held['directory_id']], listing.get('version'))
                    changed = True
            if changed:
                self._save()
            return changed

    # --- changes the user makes -------------------------------------------------------------------------------
    def set_group(self, key, *, enabled=None, refresh_seconds=None, name=None, remove=False):
        with self.lock:
            held = self.group(key)
            if remove:
                self.document['groups'].remove(held)
                self.document['feeds'] = [f for f in self.document['feeds'] if f['group'] != key]
            else:
                if enabled is not None:
                    held['enabled'] = bool(enabled)
                if refresh_seconds is not None:
                    held['refresh_seconds'] = frequency(refresh_seconds)
                if name is not None:
                    if not text(name, 60):
                        raise ValueError('Name the group.')
                    held['name'] = text(name, 60)
            self._save()
            return self.snapshot()

    @property
    def unsorted(self):
        return UNSORTED.get(self.language, LEGACY_UNSORTED)

    def _rename_unsorted(self):
        """An older Local RSS's `Other` group takes the name in Local RSS's language, unless that name is taken."""
        own = [g for g in self.document['groups'] if g['source'] == 'own']
        legacy = next((g for g in own if g['name'] == LEGACY_UNSORTED), None)
        if legacy is None or self.unsorted == LEGACY_UNSORTED or any(g['name'] == self.unsorted for g in own):
            return False
        legacy['name'] = self.unsorted
        return True

    def _own_group(self, name):
        name = text(name, 60) or self.unsorted
        held = next((g for g in self.document['groups'] if g['source'] == 'own' and g['name'] == name), None)
        if held is None:
            if len(self.document['groups']) >= MAX_GROUPS:
                raise ValueError(f'Keep up to {MAX_GROUPS} groups.')
            held = {'key': 'g-' + secrets.token_hex(6), 'name': name, 'source': 'own', 'enabled': True,
                    'refresh_seconds': DEFAULT_REFRESH}
            self.document['groups'].append(held)
        return held

    def add_feed(self, url, *, name='', group='', refresh_seconds=None):
        with self.lock:
            address = public_url(url)
            if any(f['url'] == address for f in self.document['feeds']):
                raise ValueError('A feed with this URL is already in your subscriptions.')
            if len(self.document['feeds']) >= MAX_FEEDS:
                raise ValueError(f'Keep up to {MAX_FEEDS} feeds.')
            held = self._own_group(group)
            self.document['feeds'].append({'url': address, 'name': text(name, 100), 'group': held['key'], 'enabled': True,
                                           'refresh_seconds': frequency(refresh_seconds, allow_none=True), 'origin': 'own'})
            self._save()
            return self.snapshot()

    def update_feed(self, url, **changes):
        with self.lock:
            held = self.feed(url)
            if 'enabled' in changes and changes['enabled'] is not None:
                held['enabled'] = bool(changes['enabled'])
            if 'refresh_seconds' in changes:  # None: the group's default
                held['refresh_seconds'] = frequency(changes['refresh_seconds'], allow_none=True)
            if changes.get('name') is not None:
                held['name'] = text(changes['name'], 100)
            if changes.get('group') is not None:
                if held.get('origin') == 'directory':
                    raise ValueError('A feed from a followed group stays in its group; turn it off instead.')
                held['group'] = self._own_group(changes['group'])['key']
            self._save()
            return self.snapshot()

    def remove_feed(self, url):
        """Remove one of the user's own feeds; a feed of a followed group is turned off, so syncing doesn't add it
        back."""
        with self.lock:
            held = self.feed(url)
            if held.get('origin') == 'directory':
                held['enabled'] = False
            else:
                self.document['feeds'].remove(held)
                if not any(f['group'] == held['group'] for f in self.document['feeds']):
                    self.document['groups'] = [g for g in self.document['groups']
                                               if not (g['key'] == held['group'] and g['source'] == 'own')]
            self._save()
            return self.snapshot()

    def import_feeds(self, feeds):
        """Add feeds (OPML, or a viewer's old feed list) as the user's own; addresses already subscribed are skipped."""
        with self.lock:
            have = {f['url'] for f in self.document['feeds']}
            added = listed = over = refused = 0
            for feed in feeds:
                try:
                    address = public_url(feed['url'])
                except ValueError:
                    refused += 1
                    continue
                if address in have:
                    listed += 1
                    continue
                if len(self.document['feeds']) >= MAX_FEEDS:
                    over += 1
                    continue
                held = self._own_group(feed.get('group') or '')
                every = feed.get('refresh_seconds')
                self.document['feeds'].append({'url': address, 'name': text(feed.get('name'), 100), 'group': held['key'],
                                               'enabled': feed.get('enabled', True) is not False,
                                               'refresh_seconds': every if every in FREQUENCIES else None, 'origin': 'own'})
                have.add(address)
                added += 1
            if added:
                self._save()
            return {'added': added, 'listed': listed, 'over': over, 'refused': refused, **self.snapshot()}
