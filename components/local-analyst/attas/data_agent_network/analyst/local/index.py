"""The per-news, per-stock opinions this computer's stock rules kept, indexed for the sentiment strategies.

Alvin, 2026-11-24: a local service may keep any of its user's data in its own state folder. The Local Analyst keeps one
copy of each opinion here as well as in the AssetStorage the user picked, so a strategy backtest can read a stock's
opinions over any span in one call (AssetStorage files are batches; reading months of them would take thousands of
calls). The rows are the AssetStorage batches' own opinions: a batch AssetStorage refused to keep is not indexed.

An opinion becomes known when its analyst gave it (`analyzed_at`), never before the news was published: a strategy
reads it from then, so a backtest never sees an opinion before it existed.

The tags analysts gave news items are indexed here too (`tags`), from every tagging batch the Local Analyst keeps or
reads, so a reader such as the RSS Viewer can show a story's tags in one call (analyst_tags). Only tagged items are
kept, for TAG_DAYS.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import threading

MAX_ROWS = 10000  # a strategy replay reads at most this many rows; a longer span is narrowed by the caller
TAG_DAYS = 90
MAX_TAG_URLS = 300
COLUMNS = ('rule', 'news_id', 'instrument', 'list_name', 'member_name', 'title', 'url', 'publisher', 'news_source',
           'occurred_at', 'analyzed_at', 'available_at', 'persona_id', 'persona_name', 'score', 'confidence')


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def moment(value):
    try:
        found = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


class OpinionIndex:
    """A small SQLite file; every write is one transaction, and a row is replaced when the same rule scores the same
    news item for the same instrument again."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.Lock()
        with closing(self.connect()) as db, db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE IF NOT EXISTS opinions (rule TEXT NOT NULL, news_id TEXT NOT NULL, instrument TEXT NOT NULL, '
                       'list_name TEXT, member_name TEXT, title TEXT, url TEXT, publisher TEXT, news_source TEXT, '
                       'occurred_at TEXT NOT NULL, analyzed_at TEXT NOT NULL, available_at TEXT NOT NULL, persona_id TEXT NOT NULL, '
                       'persona_name TEXT, score REAL NOT NULL, confidence REAL, PRIMARY KEY (rule, news_id, instrument))')
            db.execute('CREATE INDEX IF NOT EXISTS opinions_by_instrument ON opinions (instrument, available_at)')
            db.execute('CREATE TABLE IF NOT EXISTS tags (rule TEXT NOT NULL, news_id TEXT NOT NULL, url TEXT, title TEXT, '
                       'published_at TEXT, tagged_at TEXT, persona_id TEXT, persona_name TEXT, tags TEXT NOT NULL, entities TEXT, '
                       'PRIMARY KEY (rule, news_id))')
            db.execute('CREATE INDEX IF NOT EXISTS tags_by_url ON tags (url)')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def keep(self, rule, analyst, list_name, items, analyzed_at):
        """Index one kept batch's opinions; returns how many rows it wrote."""
        rows = []
        for item in items:
            occurred = moment(item.get('published_at'))
            if occurred is None:
                continue
            available = max(occurred, analyzed_at)
            for said in item.get('opinions') or []:
                rows.append((rule, item['id'], said['code'], list_name, said.get('name') or '', item.get('title') or '',
                             item.get('url') or '', item.get('publisher') or '', item.get('news_source') or '',
                             iso(occurred), iso(analyzed_at), iso(available), analyst['agentId'], analyst.get('name') or '',
                             float(said['score']), None if said.get('confidence') is None else float(said['confidence'])))
        if rows:
            with self.lock, closing(self.connect()) as db, db:
                db.executemany('INSERT OR REPLACE INTO opinions (' + ','.join(COLUMNS) + ') VALUES (' + ','.join('?' * len(COLUMNS)) + ')', rows)
        return len(rows)

    def keep_tags(self, document):
        """Index one tagging batch (its document, as kept in AssetStorage): each tagged item's tags and the named-list
        members it is about, by the rule and analyst that tagged it. Returns how many items it wrote."""
        if not isinstance(document, dict):
            return 0
        analyst = document.get('analyst') if isinstance(document.get('analyst'), dict) else {}
        rule, tagged_at = str(document.get('rule') or '')[:128], str(document.get('tagged_at') or '')[:40]
        rows = []
        for item in document.get('items') or []:
            if not isinstance(item, dict) or not item.get('id'):
                continue
            tags = [str(t)[:80] for t in item.get('tags') or [] if isinstance(t, str) and t.strip()][:24]
            if not tags:
                continue
            entities = [{key: str(m.get(key) or '')[:120] for key in ('list', 'code', 'name')}
                        for m in item.get('entities') or [] if isinstance(m, dict)][:40]
            rows.append((rule, str(item['id'])[:120], str(item.get('url') or '')[:1000], str(item.get('title') or '')[:300],
                         str(item.get('published_at') or '')[:40], tagged_at, str(analyst.get('agentId') or '')[:128],
                         str(analyst.get('name') or '')[:80], json.dumps(tags, ensure_ascii=False), json.dumps(entities, ensure_ascii=False)))
        if not rows:
            return 0
        cutoff = iso(datetime.now(timezone.utc) - timedelta(days=TAG_DAYS))
        with self.lock, closing(self.connect()) as db, db:
            db.executemany('INSERT OR REPLACE INTO tags (rule, news_id, url, title, published_at, tagged_at, persona_id, persona_name, '
                           'tags, entities) VALUES (?,?,?,?,?,?,?,?,?,?)', rows)
            db.execute('DELETE FROM tags WHERE tagged_at < ?', (cutoff,))
        return len(rows)

    def tags_for(self, urls):
        """The tags kept for these news items (by their addresses), one row per rule that tagged each."""
        wanted = [u for u in dict.fromkeys(urls or []) if isinstance(u, str) and u][:MAX_TAG_URLS]
        if not wanted:
            return []
        with self.lock, closing(self.connect()) as db:
            rows = db.execute('SELECT * FROM tags WHERE url IN (' + ','.join('?' * len(wanted)) + ') ORDER BY tagged_at', wanted).fetchall()
        return [{'url': row['url'], 'news_id': row['news_id'], 'title': row['title'], 'rule': row['rule'], 'tagged_at': row['tagged_at'],
                 'analyst': {'agentId': row['persona_id'], 'name': row['persona_name']}, 'tags': json.loads(row['tags']),
                 'entities': json.loads(row['entities'] or '[]')} for row in rows]

    def query(self, instruments=None, start=None, end=None, limit=MAX_ROWS):
        """Opinions known in [start, end), oldest first, for the instruments asked (all when none); `more` says the span
        held more than `limit`."""
        where, args = [], []
        if instruments:
            where.append('instrument IN (' + ','.join('?' * len(instruments)) + ')')
            args.extend(instruments)
        if start is not None:
            where.append('available_at >= ?')
            args.append(iso(start))
        if end is not None:
            where.append('available_at < ?')
            args.append(iso(end))
        sql = ('SELECT * FROM opinions' + (' WHERE ' + ' AND '.join(where) if where else '')
               + ' ORDER BY available_at, instrument, news_id, persona_id LIMIT ?')
        with closing(self.connect()) as db:
            found = [dict(row) for row in db.execute(sql, [*args, limit + 1])]
        return found[:limit], len(found) > limit

    def coverage(self, instruments=None):
        """For each instrument: how many opinions, and the first and last time one became known."""
        where = ' WHERE instrument IN (' + ','.join('?' * len(instruments)) + ')' if instruments else ''
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(
                'SELECT instrument, COUNT(*) AS opinions, MIN(available_at) AS first, MAX(available_at) AS last FROM opinions'
                + where + ' GROUP BY instrument ORDER BY instrument LIMIT 5000', list(instruments or []))]
