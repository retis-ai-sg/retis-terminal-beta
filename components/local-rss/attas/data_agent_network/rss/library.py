"""The articles Local RSS keeps for its user's subscribed feeds, in `<state>/articles.sqlite`.

A local service may keep its user's data (AGENTS.md, Alvin 2026-11-24). Each feed keeps its status, its validators
(ETag, Last-Modified) and its newest MAX_PER_FEED articles; a failed read keeps the articles it had. `due` says which
feeds to read now: one never read, or read longer ago than its frequency; a feed that has never been read and failed
is tried again after RETRY_SECONDS rather than after its frequency.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import time

from .feeds import MAX_RESULT_BYTES

FILE = 'articles.sqlite'
MAX_PER_FEED = 50
RETRY_SECONDS = 60
SUMMARY = 300
MAX_TRANSLATIONS = 3000


class Library:
    def __init__(self, folder, *, clock=time.time):
        self.path = Path(folder).expanduser() / FILE
        self.clock = clock
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.path.chmod(0o600)
        with self.lock, self.db:
            # Translations are kept by part since translating went part by part; an earlier table holds only a cache.
            columns = [row[1] for row in self.db.execute('PRAGMA table_info(translations)')]
            if columns and 'part' not in columns:
                self.db.execute('DROP TABLE translations')
            self.db.executescript('''
              CREATE TABLE IF NOT EXISTS feeds(url TEXT PRIMARY KEY, title TEXT, site_url TEXT, status TEXT, error TEXT,
                checked_at TEXT, etag TEXT, last_modified TEXT, read_at REAL, failed_at REAL, ok INTEGER DEFAULT 0);
              CREATE TABLE IF NOT EXISTS items(feed_url TEXT, id TEXT, title TEXT, url TEXT, published_at TEXT, author TEXT,
                publisher TEXT, summary TEXT, content TEXT, seen REAL, PRIMARY KEY(feed_url, id));
              CREATE INDEX IF NOT EXISTS items_by_time ON items(feed_url, published_at);
              CREATE TABLE IF NOT EXISTS translations(feed_url TEXT, id TEXT, language TEXT, part INTEGER, title TEXT,
                text TEXT, model TEXT, at REAL, PRIMARY KEY(feed_url, id, language, part));''')

    def close(self):
        self.db.close()

    # --- what to read --------------------------------------------------------------------------------------------
    def due(self, feeds, now=None):
        """The feeds of `feeds` ({url, every}) to read now; a frequency of 0 is read only on request."""
        now = self.clock() if now is None else now
        with self.lock:
            rows = {r[0]: r[1:] for r in self.db.execute('SELECT url, read_at, failed_at, ok FROM feeds')}
        chosen = []
        for feed in feeds:
            read_at, failed_at, ok = rows.get(feed['url'], (None, None, 0))
            if not ok and failed_at and now - failed_at < RETRY_SECONDS:
                continue
            if not ok and not failed_at:
                chosen.append(feed)
            elif not ok:
                chosen.append(feed)  # never read yet; its retry wait has passed
            elif feed['every'] > 0 and now - max(read_at or 0, failed_at or 0) >= feed['every']:
                chosen.append(feed)
        return chosen

    def validators(self, url):
        with self.lock:
            row = self.db.execute('SELECT etag, last_modified FROM feeds WHERE url=?', (url,)).fetchone()
        return {'etag': (row or ('', ''))[0] or '', 'last_modified': (row or ('', ''))[1] or ''}

    # --- storing a read ------------------------------------------------------------------------------------------
    def store(self, results, now=None):
        """Keep what reading some feeds gave (rss.read_feeds results, from this source or another)."""
        now = self.clock() if now is None else now
        with self.lock, self.db:
            for row in results:
                url = row.get('url')
                if not isinstance(url, str):
                    continue
                status = row.get('status')
                if status in ('ready', 'not_modified'):
                    self.db.execute('''INSERT INTO feeds(url, title, site_url, status, error, checked_at, etag, last_modified,
                        read_at, failed_at, ok) VALUES(?,?,?,?,?,?,?,?,?,NULL,1) ON CONFLICT(url) DO UPDATE SET
                        title=COALESCE(excluded.title, feeds.title), site_url=COALESCE(excluded.site_url, feeds.site_url),
                        status='ready', error=NULL, checked_at=excluded.checked_at,
                        etag=COALESCE(NULLIF(excluded.etag,''), feeds.etag),
                        last_modified=COALESCE(NULLIF(excluded.last_modified,''), feeds.last_modified),
                        read_at=excluded.read_at, failed_at=NULL, ok=1''',
                                    (url, row.get('title'), row.get('site_url'), 'ready', None, row.get('checked_at'),
                                     row.get('etag') or '', row.get('last_modified') or '', now))
                    for item in row.get('items') or []:
                        if not isinstance(item, dict) or not item.get('id'):
                            continue
                        self.db.execute('''INSERT INTO items(feed_url, id, title, url, published_at, author, publisher, summary,
                            content, seen) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(feed_url, id) DO UPDATE SET
                            title=excluded.title, url=excluded.url, published_at=excluded.published_at,
                            author=excluded.author, publisher=excluded.publisher, summary=excluded.summary,
                            content=excluded.content''',
                                        (url, str(item['id'])[:80], item.get('title') or '', item.get('url') or '',
                                         item.get('published_at') or '', item.get('author') or '', item.get('publisher') or '',
                                         item.get('summary') or '', item.get('content') or '', now))
                    # The newest MAX_PER_FEED stay: by publication time, then by when this source first saw them.
                    self.db.execute('''DELETE FROM items WHERE feed_url=? AND rowid NOT IN (SELECT rowid FROM items
                        WHERE feed_url=? ORDER BY published_at DESC, seen DESC LIMIT ?)''', (url, url, MAX_PER_FEED))
                elif status == 'error':
                    self.db.execute('''INSERT INTO feeds(url, status, error, checked_at, failed_at, ok) VALUES(?,?,?,?,?,0)
                        ON CONFLICT(url) DO UPDATE SET status='error', error=excluded.error, checked_at=excluded.checked_at,
                        failed_at=excluded.failed_at''',
                                    (url, 'error', str(row.get('error') or 'The feed could not be read.')[:300],
                                     row.get('checked_at'), now))

    def forget(self, keep):
        """Drop the articles of feeds no longer subscribed."""
        keep = set(keep)
        with self.lock, self.db:
            gone = [r[0] for r in self.db.execute('SELECT url FROM feeds') if r[0] not in keep]
            for url in gone:
                self.db.execute('DELETE FROM items WHERE feed_url=?', (url,))
                self.db.execute('DELETE FROM feeds WHERE url=?', (url,))
                self.db.execute('DELETE FROM translations WHERE feed_url=?', (url,))
        return len(gone)

    # --- reading the library -------------------------------------------------------------------------------------
    def status(self, urls):
        with self.lock:
            rows = {r[0]: r for r in self.db.execute('SELECT url, title, status, error, checked_at, ok FROM feeds')}
        return {url: ({'title': rows[url][1] or '', 'status': rows[url][2] or 'waiting', 'error': rows[url][3] or '',
                       'checked_at': rows[url][4] or '', 'read': bool(rows[url][5])} if url in rows else
                      {'title': '', 'status': 'waiting', 'error': '', 'checked_at': '', 'read': False}) for url in urls}

    def articles(self, feeds, limit=300, max_bytes=MAX_RESULT_BYTES):
        """The newest articles of `feeds` ({url, name, group}), newest first, each with a short summary."""
        names = {f['url']: f for f in feeds}
        if not names:
            return []
        marks = ','.join('?' * len(names))
        with self.lock:
            rows = self.db.execute(f'''SELECT feed_url, id, title, url, published_at, author, publisher, summary, content
                FROM items WHERE feed_url IN ({marks}) ORDER BY published_at DESC, seen DESC LIMIT ?''',
                                   (*names, int(limit))).fetchall()
        listed, size = [], 2
        for feed_url, item_id, title, url, published, author, publisher, summary, content in rows:
            entry = {'feed': feed_url, 'feed_name': names[feed_url].get('name') or '', 'group': names[feed_url].get('group') or '',
                     'id': item_id, 'title': title, 'url': url, 'published_at': published, 'author': author,
                     'publisher': publisher, 'summary': (summary or content or '')[:SUMMARY]}
            size += len(json.dumps(entry).encode()) + 1
            if size > max_bytes:
                break
            listed.append(entry)
        return listed

    def article(self, feed_url, item_id):
        with self.lock:
            row = self.db.execute('''SELECT title, url, published_at, author, publisher, summary, content FROM items
                WHERE feed_url=? AND id=?''', (feed_url, item_id)).fetchone()
        if row is None:
            raise ValueError('That article is no longer kept.')
        return dict(zip(('title', 'url', 'published_at', 'author', 'publisher', 'summary', 'content'), row),
                    feed=feed_url, id=item_id)

    # --- translations the viewer asked for -----------------------------------------------------------------------
    def translation(self, feed_url, item_id, language, part=0):
        with self.lock:
            row = self.db.execute('SELECT title, text, model FROM translations WHERE feed_url=? AND id=? AND language=? AND part=?',
                                  (feed_url, item_id, language, part)).fetchone()
        return dict(zip(('title', 'text', 'model'), row)) if row else None

    def keep_translation(self, feed_url, item_id, language, part, title, text, model, now=None):
        """Keep one part of a translation; the newest MAX_TRANSLATIONS parts stay."""
        now = self.clock() if now is None else now
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO translations(feed_url, id, language, part, title, text, model, at) VALUES(?,?,?,?,?,?,?,?)',
                            (feed_url, item_id, language, part, title, text, model, now))
            self.db.execute('DELETE FROM translations WHERE rowid NOT IN (SELECT rowid FROM translations ORDER BY at DESC LIMIT ?)',
                            (MAX_TRANSLATIONS,))
