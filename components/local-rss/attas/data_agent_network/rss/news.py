"""News from the RSS source's default feeds (defaults.py): a news list, one article, and stock news by keyword.

Every read goes through feeds.read_feeds, so a default feed keeps every rule a feed a user adds has (public
addresses only, 1 MB and 12 s per feed, no HTTPS-to-HTTP redirect, no document types). The default and keyword feeds
are public and the same for everyone, so a successful read is kept in memory for CACHE_SECONDS, at most CACHE_ENTRIES
of them. A feed a user sends through rss.read_feeds or rss_fetch is never kept, and nothing is written to disk.

Stock news has two parts: each keyword feed (a search feed, `template` in defaults.py) asked for the keyword, and the
other chosen default feeds' articles whose headline or summary mention the keyword or one of its aliases. Each article
says which words matched and which part found it (`via`).
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .defaults import BY_ID, FEEDS, filled
from .feeds import MAX_RESULT_BYTES, fetch, read_feeds

PER_FEED = 30  # articles read from each feed, so an article listed earlier can still be found
CACHE_SECONDS = 300
CACHE_ENTRIES = 64
READS_AT_ONCE = 4
SUMMARY = 200
KEYWORD = 'keyword:'
LANGUAGES = ('zh-Hant', 'zh-Hans')
CONTROL = re.compile(r'[\x00-\x1f\x7f]')


class NotFound(ValueError):
    """The article asked for is not in its feed now."""


def mentions(text: str, word: str) -> bool:
    """Whether `text` mentions `word`: a code of letters and digits (2330, AAPL) as a whole code, other words anywhere."""
    if re.fullmatch(r'[A-Za-z0-9.^-]+', word):
        return re.search(r'(?<![A-Za-z0-9])' + re.escape(word) + r'(?![A-Za-z0-9])', text, re.IGNORECASE) is not None
    return word.casefold() in text.casefold()


def _title_key(item: Mapping[str, Any]) -> str:
    """A headline as two copies of one article share it: an aggregator adds " - <publisher>" to the title."""
    title, publisher = str(item.get('title') or ''), str(item.get('publisher') or '')
    if publisher and title.endswith(' - ' + publisher):
        title = title[:-len(publisher) - 3]
    return ' '.join(title.split()).casefold()


def unique(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The first copy of each article, by address or by headline."""
    seen, kept = set(), []
    for item in items:
        keys = {key for key in (item.get('url'), _title_key(item)) if key}
        if keys & seen:
            continue
        seen |= keys
        kept.append(item)
    return kept


def newest(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Newest first; an article without a date comes after the dated ones."""
    items = list(items)
    dated = sorted((i for i in items if i.get('published_at')), key=lambda i: i['published_at'], reverse=True)
    return dated + [i for i in items if not i.get('published_at')]


def bounded(answer: Dict[str, Any]) -> Dict[str, Any]:
    """The answer within MAX_RESULT_BYTES, leaving out the oldest articles first."""
    while len(json.dumps(answer).encode()) > MAX_RESULT_BYTES and answer['items']:
        answer['items'].pop()
        answer['truncated'] = True
    return answer


def language(feed: Mapping[str, Any]) -> str:
    return next((tag for tag in feed['tags'] if tag in LANGUAGES), '')


def described(feed: Mapping[str, Any]) -> Dict[str, Any]:
    return {'id': feed['id'], 'name': feed['name'], 'url': feed['url'], 'language': language(feed), 'tags': list(feed['tags']),
            **({'keyword': feed['keyword'], 'template': feed['template']} if feed.get('template') else {})}


def chosen(tags: Sequence[str] = (), ids: Optional[Sequence[str]] = None) -> List[Mapping[str, Any]]:
    unknown = [i for i in ids or () if i not in BY_ID]
    if unknown:
        raise ValueError('Not a default feed: ' + ', '.join(unknown)[:120] + '. rss.feeds lists them.')
    feeds = [f for f in ([BY_ID[i] for i in ids] if ids else FEEDS) if set(tags) <= set(f['tags'])]
    if not feeds:
        raise ValueError('No default feed has all of these tags. rss.feeds lists each feed with its tags.')
    return feeds


def headline(item: Mapping[str, Any], feed: Mapping[str, Any], key: str) -> Dict[str, Any]:
    value = {'id': item['id'], 'feed': key, 'source': feed['name'], 'publisher': item.get('publisher') or feed['name'],
             'title': item['title'], 'url': item.get('url') or '', 'published_at': item.get('published_at'),
             'summary': (item.get('summary') or '')[:SUMMARY], 'tags': list(feed['tags'])}
    return {k: v for k, v in value.items() if v is not None}


def status(key: str, feed: Mapping[str, Any], result: Mapping[str, Any]) -> Dict[str, Any]:
    return {'feed': key, 'name': feed['name'], 'status': result.get('status', 'error'), 'checked_at': result.get('checked_at', ''),
            **({'error': result['error']} if result.get('error') else {})}


class News:
    """The default feeds' news. `getter(url, validators)` stands in for feeds.fetch in tests; `clock` for the cache."""

    def __init__(self, getter: Callable = fetch, clock: Callable[[], float] = time.monotonic):
        self.getter, self.clock = getter, clock
        self._kept: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    # ----- reading
    def read(self, url: str, name: str) -> Dict[str, Any]:
        """One default or keyword feed, from memory when it was read in the last CACHE_SECONDS."""
        now = self.clock()
        with self._lock:
            hit = self._kept.get(url)
            if hit and now - hit[0] < CACHE_SECONDS:
                return hit[1]
        result = read_feeds([{'url': url, 'name': name}], PER_FEED, getter=self.getter)['feeds'][0]
        if result.get('status') == 'ready':
            with self._lock:
                self._kept[url] = (now, result)
                for stale in sorted(self._kept, key=lambda key: self._kept[key][0])[:max(0, len(self._kept) - CACHE_ENTRIES)]:
                    self._kept.pop(stale)
        return result

    def read_all(self, targets: Sequence[Tuple[str, Mapping[str, Any]]]) -> List[Dict[str, Any]]:
        with ThreadPoolExecutor(max_workers=READS_AT_ONCE) as pool:
            return list(pool.map(lambda target: self.read(target[0], target[1]['name']), targets))

    def resolve(self, key: str) -> Tuple[Mapping[str, Any], str]:
        """A feed as news names it: a default feed's id, or keyword:<feed id>:<keyword> for a keyword feed's search."""
        if key.startswith(KEYWORD):
            identity, _, keyword = key[len(KEYWORD):].partition(':')
            feed = BY_ID.get(identity)
            if not feed or not feed.get('template') or not keyword.strip() or len(keyword) > 40 or CONTROL.search(keyword):
                raise ValueError('Not a keyword feed search: name it keyword:<feed id>:<keyword>, as stock news does.')
            return feed, filled(feed, keyword)
        if key not in BY_ID:
            raise ValueError('Not a default feed. rss.feeds lists them.')
        return BY_ID[key], BY_ID[key]['url']

    # ----- the endpoints
    def feeds(self, tags: Sequence[str] = ()) -> Dict[str, Any]:
        listed = [described(f) for f in FEEDS if set(tags) <= set(f['tags'])]
        return {'feeds': listed, 'tags': sorted({t for f in listed for t in f['tags']})}

    def news_list(self, tags: Sequence[str] = (), ids: Optional[Sequence[str]] = None, limit: int = 30) -> Dict[str, Any]:
        feeds = chosen(tags, ids)
        results = self.read_all([(f['url'], f) for f in feeds])
        listed = [(f, headline(item, f, f['id'])) for f, result in zip(feeds, results) for item in result.get('items') or []]
        # A publisher's own copy of an article comes before an aggregator's link to it.
        own = [item for f, item in listed if 'aggregator' not in f['tags']]
        aggregated = [item for f, item in listed if 'aggregator' in f['tags']]
        return bounded({'items': newest(unique(newest(own) + newest(aggregated)))[:limit],
                        'feeds': [status(f['id'], f, result) for f, result in zip(feeds, results)]})

    def article(self, key: str, identity: str) -> Dict[str, Any]:
        feed, url = self.resolve(key)
        result = self.read(url, feed['name'])
        if result.get('status') != 'ready':
            raise ValueError(result.get('error') or 'The feed could not be read.')
        item = next((i for i in result.get('items') or [] if i['id'] == identity), None)
        if item is None:
            raise NotFound('This article is no longer among its feed’s newest articles.')
        article = {**headline(item, feed, key), 'summary': item.get('summary') or '', 'content': item.get('content') or '',
                   **({'author': item['author']} if item.get('author') else {})}
        return {'article': article, 'feed': status(key, feed, result)}

    def stock_news(self, keyword: str, aliases: Sequence[str] = (), tags: Sequence[str] = (), limit: int = 20) -> Dict[str, Any]:
        keyword = keyword.strip()
        words = [keyword, *[a.strip() for a in aliases if a.strip() and a.strip() != keyword]]
        targets = []
        for feed in chosen(tags):
            if feed.get('template'):
                targets.append((KEYWORD + feed['id'] + ':' + keyword, filled(feed, keyword), feed, 'keyword_feed'))
            else:
                targets.append((feed['id'], feed['url'], feed, 'default_feed'))
        results = self.read_all([(url, feed) for _, url, feed, _ in targets])
        found = {'default_feed': [], 'keyword_feed': []}
        for (key, _, feed, via), result in zip(targets, results):
            for item in result.get('items') or []:
                said = item['title'] + '\n' + (item.get('summary') or '')
                matched = [word for word in words if mentions(said, word)]
                if via == 'default_feed' and not matched:
                    continue
                if via == 'keyword_feed' and keyword not in matched:
                    matched.insert(0, keyword)  # the search matched it, though the headline may not show it
                found[via].append({**headline(item, feed, key), 'matched': matched, 'via': via})
        # A publisher's own copy of an article comes before an aggregator's link to it.
        items = newest(unique(found['default_feed'] + found['keyword_feed']))[:limit]
        return bounded({'keyword': keyword, 'aliases': words[1:], 'items': items,
                        'feeds': [status(key, feed, result) for (key, _, feed, _), result in zip(targets, results)]})
