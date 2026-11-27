"""RSS and Atom feeds as a Data Source: the public feeds a user adds, read by the computer this source runs on.

Its catalog is built from the definitions below, so `build_snapshot()` is deterministic and needs no documentation
download; the committed catalog under catalogs/rss/ is that snapshot. `rss.read_feeds` reads the feeds a request
sends; `rss_fetch`, the pulse the RSS Viewer asks for, runs the same code. `rss.feeds`, `rss.news_list`,
`rss.article` and `rss.stock_news` read the source's default feeds (defaults.py, news.py). `rss.groups` lists the
reviewed feed group directory (groups.py, feed_groups.json) by language and topic; the site copy's RSS Feed Groups
panel browses it and has a user's RSS Viewer follow chosen groups (site.py).

Local RSS, the copy on the user's own computer, keeps that user's subscriptions and their articles in its state folder
(subscriptions.py, library.py; AGENTS.md: a local service may keep its user's data) and reads the subscribed feeds in
the background at their frequencies. Its RSS Viewer calls `rss_local` for them, and for every RSS source the user can
reach, which it asks the Terminal for (a data request).

Most HTTP sources call a fixed list of vendor hosts. An RSS reader reads whatever public feed its user adds, so
feeds.py stands in for that list: public addresses only, the checked address pinned at every hop, no HTTPS-to-HTTP
redirect, 1 MB and 12 s per feed. An rss.read_feeds call keeps nothing: it carries the feeds it reads. The default feeds
are public and the same for everyone; news.py keeps their last reads in memory for a few minutes. Only Local RSS keeps
a user's subscriptions and articles (below); the site copy keeps no one's.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from fastapi import HTTPException

from ..scaffold.models import (EndpointExecutionResult, EndpointParameterSpec, EndpointSpec, EndpointSpecSnapshot,
                               VendorSpecSource)
from ..scaffold.sources import AbstractDataSource
from .contracts import (ARTICLE_INPUT, FEED, FEEDS_INPUT, GROUPS_ENDPOINT_ID, GROUPS_INPUT, INPUT, NEWS_LIST_INPUT, PULSE,
                        STOCK_NEWS_INPUT, VIEW_ID, check, checked, definition)
from .feeds import MAX_RESULT_BYTES, fetch, read_feeds
from .news import News
from . import local as local_operations

VENDOR_ID = 'rss'
ENDPOINT_ID = 'rss.read_feeds'
# 2: the default feeds' news list, article and stock news; articles name their publisher. 3: the feed group directory
# (rss.groups), and a feed may name its group.
PARSER_VERSION = 'RSSCatalog:3'
# The catalog's date: when this definition was last checked against the RSS 2.0 and Atom specifications.
REVIEWED_AT = '2026-11-23T00:00:00+00:00'
RSS_SPEC = 'https://www.rssboard.org/rss-specification'
ATOM_SPEC = 'https://www.rfc-editor.org/rfc/rfc4287'
SYMBOLOGY = {'contract_version': 'source-symbology/1', 'status': 'not_applicable', 'input_types': [], 'output_types': [],
             'notes': 'Reads feeds by their public address; no instrument symbology.', 'evidence': []}


def leaf(kind, description, **extra):
    return {'type': kind, 'description': description, **extra}


ITEM = {'type': 'object', 'description': 'One article of the feed, as plain text.', 'properties': {
    'id': leaf('string', 'Stable id of the article: a hash of the feed address and the entry guid, id, link or title.'),
    'title': leaf('string', 'Headline of the article, plain text.'),
    'url': leaf('string', "Public address of the article on the publisher's site, when the entry gives one."),
    'published_at': leaf('string', 'When the article was published or last updated, ISO 8601 in UTC.', format='date-time'),
    'author': leaf('string', 'Author named by the entry.'),
    'publisher': leaf('string', "The outlet an aggregator's entry names in its source element (RSS 2.0 <source>)."),
    'summary': leaf('string', 'Summary or description of the article, plain text, at most 500 characters.'),
    'content': leaf('string', 'Article text the feed supplies (possibly an excerpt), HTML converted to plain text.'),
}, 'required': ['id', 'title']}
FEED_RESULT = {'type': 'object', 'description': 'What reading one feed gave.', 'properties': {
    'url': leaf('string', 'The feed address as requested.'),
    'name': leaf('string', 'The name the user gave the feed.'),
    'status': leaf('string', 'ready (articles read), not_modified (unchanged since the validators sent), disabled or error.',
                   enum=['ready', 'not_modified', 'disabled', 'error']),
    'checked_at': leaf('string', 'When the feed was read, ISO 8601 in UTC.', format='date-time'),
    'title': leaf('string', "The feed's own title."),
    'site_url': leaf('string', "Public address of the feed's site."),
    'etag': leaf('string', 'ETag the publisher sent, for the next conditional read.'),
    'last_modified': leaf('string', 'Last-Modified the publisher sent, for the next conditional read.'),
    'items': {'type': 'array', 'description': 'The newest articles, at most `limit`.', 'items': ITEM},
    'truncated': leaf('boolean', 'True when articles were left out to keep the answer under its size limit.'),
    'error': leaf('string', 'Why the feed could not be read.'),
}, 'required': ['url', 'status', 'checked_at']}
RESPONSE = {'type': 'object', 'description': 'The feeds read, in the order requested.', 'properties': {
    'source_mode': leaf('string', 'Always parameters: the feeds came with the request.', enum=['parameters']),
    'feeds': {'type': 'array', 'description': 'One result for each feed requested.', 'items': FEED_RESULT},
}, 'required': ['source_mode', 'feeds']}


def endpoint_spec() -> EndpointSpec:
    return EndpointSpec(
        endpoint_id=ENDPOINT_ID, vendor_id=VENDOR_ID, name='Read feeds',
        description='Read up to 20 public RSS 2.0, RSS 1.0 (RDF) or Atom feeds and return their newest articles as plain '
                    'text. Sending the ETag or Last-Modified from an earlier read asks only for what changed.',
        category='News and feeds', transport='https', operation=ENDPOINT_ID,
        parameters=(
            EndpointParameterSpec(name='feeds', location='body', required=True, schema=copy.deepcopy(INPUT['properties']['feeds']),
                                  description='The feeds to read: each a public http(s) address on the standard port, with '
                                              'its optional name, enabled flag, refresh interval and validators.',
                                  examples=([{'url': 'https://example.com/feed.xml', 'name': 'Example'}],)),
            EndpointParameterSpec(name='limit', location='body', schema=copy.deepcopy(INPUT['properties']['limit']), default=20,
                                  description='The most articles to return from each feed (1 to 30).'),
        ),
        response_schema=copy.deepcopy(RESPONSE),
        authentication={'required': False, 'scheme': 'public_provider'},
        cost={'model': 'free', 'amount': 0, 'currency': 'USD', 'unit': 'request', 'notes': [],
              'provider_cost': 'Public feeds are free to read; each publisher sets its own terms.'},
        quality={'status': 'provider_documented',
                 'notes': ['Articles are what each feed publishes, often an excerpt; HTML becomes plain text.',
                           'Feed content belongs to its publishers.']},
        documentation_url=RSS_SPEC, executable=True,
        extensions={'attas.http_method': 'GET', 'attas.schema_provenance': 'curated_provider_documentation',
                    'attas.specification_only': False, 'attas.vendor_version': '',
                    'attas.max_response_bytes': MAX_RESULT_BYTES})


FEEDS_ENDPOINT, NEWS_LIST_ENDPOINT, ARTICLE_ENDPOINT, STOCK_NEWS_ENDPOINT = 'rss.feeds', 'rss.news_list', 'rss.article', 'rss.stock_news'
GROUPS_ENDPOINT = GROUPS_ENDPOINT_ID
TAG_LIST = {'type': 'array', 'description': "The feed's tags: region, language and topics.", 'items': {'type': 'string'}}
DEFAULT_FEED = {'type': 'object', 'description': 'One default feed.', 'properties': {
    'id': leaf('string', 'The feed id the news endpoints take.'),
    'name': leaf('string', "The feed's name."),
    'url': leaf('string', "The feed's public address."),
    'language': leaf('string', 'zh-Hant or zh-Hans.'),
    'tags': TAG_LIST,
    'keyword': leaf('string', 'For a keyword feed: the keyword it searches when read as a default feed.'),
    'template': leaf('string', 'For a keyword feed: its address with {keyword} where stock news puts the keyword.'),
}, 'required': ['id', 'name', 'url', 'tags']}
NEWS_ITEM = {'type': 'object', 'description': 'One article, newest first in a list.', 'properties': {
    'id': leaf('string', 'Stable id of the article; rss.article takes it with `feed`.'),
    'feed': leaf('string', 'The feed it came from: a default feed id, or keyword:<feed id>:<keyword> for a keyword search.'),
    'source': leaf('string', 'Name of that feed.'),
    'publisher': leaf('string', 'The outlet that published it: the one an aggregator names, else the feed.'),
    'title': leaf('string', 'Headline, plain text.'),
    'url': leaf('string', "Public address of the article on the publisher's site (an aggregator's link for its entries)."),
    'published_at': leaf('string', 'When it was published or last updated, ISO 8601 in UTC.', format='date-time'),
    'summary': leaf('string', 'Summary, plain text, at most 200 characters.'),
    'tags': TAG_LIST,
}, 'required': ['id', 'feed', 'source', 'title']}
STOCK_ITEM = {**NEWS_ITEM, 'properties': {
    **NEWS_ITEM['properties'],
    'matched': {'type': 'array', 'description': 'The keyword and aliases its headline or summary mention; a keyword search '
                                                'result always names the keyword.', 'items': {'type': 'string'}},
    'via': leaf('string', 'keyword_feed (a keyword feed searched for the keyword) or default_feed (a default feed '
                          'article that mentions it).', enum=['keyword_feed', 'default_feed']),
}, 'required': ['id', 'feed', 'source', 'title', 'matched', 'via']}
FEED_STATUS = {'type': 'object', 'description': 'How reading one feed went.', 'properties': {
    'feed': leaf('string', 'The feed, as `feed` names it on articles.'),
    'name': leaf('string', "The feed's name."),
    'status': leaf('string', 'ready or error.', enum=['ready', 'error']),
    'checked_at': leaf('string', 'When it was read, ISO 8601 in UTC; an earlier time when the read was kept from the '
                                 'last few minutes.', format='date-time'),
    'error': leaf('string', 'Why the feed could not be read.'),
}, 'required': ['feed', 'name', 'status']}
TRUNCATED = leaf('boolean', 'True when the oldest articles were left out to keep the answer under its size limit.')
NEWS_RESPONSES = {
    FEEDS_ENDPOINT: {'type': 'object', 'description': 'The default feeds.', 'properties': {
        'feeds': {'type': 'array', 'items': DEFAULT_FEED}, 'tags': {'type': 'array', 'items': {'type': 'string'},
                                                                     'description': 'Every tag the listed feeds have.'}},
        'required': ['feeds', 'tags']},
    NEWS_LIST_ENDPOINT: {'type': 'object', 'description': 'The newest articles across the chosen default feeds.', 'properties': {
        'items': {'type': 'array', 'items': NEWS_ITEM}, 'feeds': {'type': 'array', 'items': FEED_STATUS}, 'truncated': TRUNCATED},
        'required': ['items', 'feeds']},
    ARTICLE_ENDPOINT: {'type': 'object', 'description': 'One article with the text its feed carries.', 'properties': {
        'article': {**NEWS_ITEM, 'properties': {
            **NEWS_ITEM['properties'],
            'summary': leaf('string', 'Summary, plain text, at most 500 characters.'),
            'content': leaf('string', 'The text the feed carries, often an excerpt; HTML converted to plain text.'),
            'author': leaf('string', 'Author named by the entry.')}},
        'feed': FEED_STATUS}, 'required': ['article', 'feed']},
    STOCK_NEWS_ENDPOINT: {'type': 'object', 'description': 'Articles about a keyword, such as a stock code.', 'properties': {
        'keyword': leaf('string', 'The keyword asked for.'),
        'aliases': {'type': 'array', 'items': {'type': 'string'}, 'description': 'The aliases asked for.'},
        'items': {'type': 'array', 'items': STOCK_ITEM}, 'feeds': {'type': 'array', 'items': FEED_STATUS}, 'truncated': TRUNCATED},
        'required': ['keyword', 'items', 'feeds']},
    GROUPS_ENDPOINT: {'type': 'object', 'description': 'Groups of public feeds from the reviewed directory.', 'properties': {
        'version': leaf('integer', "The directory's version; a changed directory has a higher one."),
        'reviewed': leaf('string', 'When the directory was last reviewed.', format='date'),
        'languages': {'type': 'array', 'items': {'type': 'string'}, 'description': 'The languages groups may have.'},
        'topics': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Every topic a group has.'},
        'groups': {'type': 'array', 'description': 'The matching groups, in the directory\'s order.', 'items': {
            'type': 'object', 'properties': {
                'id': leaf('string', 'The group id.'),
                'name': {'type': 'object', 'description': 'The group name in English (en) and Traditional Chinese (zh-Hant).'},
                'description': {'type': 'object', 'description': 'What the group covers, in en and zh-Hant.'},
                'language': leaf('string', "The feeds' language: zh-Hant, zh-Hans, en or ja."),
                'region': leaf('string', 'Where the feeds come from, such as tw, hk, cn, jp, asia or intl.'),
                'topics': {'type': 'array', 'items': {'type': 'string'}},
                'feeds': {'type': 'array', 'items': {'type': 'object', 'properties': {
                    'name': leaf('string', "The feed's name."), 'url': leaf('string', "The feed's public address."),
                    'checked': leaf('string', 'When the feed was last read through this source.', format='date')},
                    'required': ['name', 'url']}}},
            'required': ['id', 'name', 'language', 'topics', 'feeds']}}},
        'required': ['version', 'groups']},
}
NEWS_ENDPOINTS = (
    (FEEDS_ENDPOINT, 'Default feeds', FEEDS_INPUT,
     'List the default feeds (public Chinese-language finance and business feeds) with their tags; reads no feed.',
     {'tags': 'Only feeds that have every one of these tags, such as ["tw", "stocks"].'}),
    (NEWS_LIST_ENDPOINT, 'News list', NEWS_LIST_INPUT,
     'The newest articles across the default feeds, newest first, one copy of each: headline, time, address, a short '
     'summary, its feed and tags. Narrow it by tags or by feed id.',
     {'tags': 'Only feeds that have every one of these tags.', 'feeds': 'Only these default feeds, by id.',
      'limit': 'The most articles to return (1 to 100, default 30).'}),
    (ARTICLE_ENDPOINT, 'Article', ARTICLE_INPUT,
     "One article from its feed, with the text the feed carries (often an excerpt) and its publisher's address.",
     {'feed': 'The article\'s `feed`, as the news list or stock news gave it.', 'id': 'The article\'s `id`.'}),
    (STOCK_NEWS_ENDPOINT, 'Stock news', STOCK_NEWS_INPUT,
     'Articles about a keyword, such as a stock code (2330, AAPL): each keyword feed searched for it, and the default '
     "feeds' articles whose headline or summary mention it or an alias (a company name such as 台積電).",
     {'keyword': 'What to search for: a stock code or name.', 'aliases': 'Up to four other words for it, matched in the '
      'default feeds.', 'tags': 'Only feeds that have every one of these tags.',
      'limit': 'The most articles to return (1 to 50, default 20).'}),
    (GROUPS_ENDPOINT, 'Feed groups', GROUPS_INPUT,
     'Groups of public feeds by language (zh-Hant, zh-Hans, en, ja) and topic, from the reviewed directory: each feed '
     "was read through this source before it was listed. Reads no feed; a reader takes a group's feeds to read them.",
     {'language': 'Only groups in this language.', 'topic': 'Only groups with this topic, such as stocks or technology.',
      'query': 'Only groups whose names, description or feed names have these words.'}),
)
NEWS_EXAMPLES = {STOCK_NEWS_ENDPOINT: {'keyword': '2330', 'aliases': ['台積電']}, NEWS_LIST_ENDPOINT: {'tags': ['tw', 'stocks']},
                 GROUPS_ENDPOINT: {'language': 'en', 'topic': 'markets'}}


def news_endpoint_spec(endpoint_id, name, schema, description, notes) -> EndpointSpec:
    required = set(schema.get('required') or ())
    parameters = tuple(
        EndpointParameterSpec(name=key, location='body', required=key in required, schema=copy.deepcopy(value),
                              description=notes[key],
                              examples=((NEWS_EXAMPLES[endpoint_id][key],) if key in NEWS_EXAMPLES.get(endpoint_id, {}) else ()))
        for key, value in schema['properties'].items())
    return EndpointSpec(
        endpoint_id=endpoint_id, vendor_id=VENDOR_ID, name=name, description=description, category='News and feeds',
        transport='https', operation=endpoint_id, parameters=parameters, response_schema=copy.deepcopy(NEWS_RESPONSES[endpoint_id]),
        authentication={'required': False, 'scheme': 'public_provider'},
        cost={'model': 'free', 'amount': 0, 'currency': 'USD', 'unit': 'request', 'notes': [],
              'provider_cost': 'Public feeds are free to read; each publisher sets its own terms.'},
        quality={'status': 'provider_documented',
                 'notes': ['Articles are what each default feed publishes, often an excerpt; HTML becomes plain text.',
                           "A keyword feed is a news search; its matches are the search's, not this source's.",
                           'Feed content belongs to its publishers.']},
        documentation_url=RSS_SPEC, executable=True,
        extensions={'attas.http_method': 'GET', 'attas.schema_provenance': 'curated_provider_documentation',
                    'attas.specification_only': False, 'attas.vendor_version': '',
                    'attas.max_response_bytes': MAX_RESULT_BYTES})


def spec_sources() -> Tuple[VendorSpecSource, ...]:
    return (VendorSpecSource(source_id='rss-2-0-specification', vendor_id=VENDOR_ID, kind='document', location=RSS_SPEC,
                             media_type='text/html', description='RSS 2.0 specification; the endpoint is curated from it.',
                             options={'curated': True}),
            VendorSpecSource(source_id='atom-rfc-4287', vendor_id=VENDOR_ID, kind='document', location=ATOM_SPEC,
                             media_type='text/html', description='The Atom Syndication Format (RFC 4287).',
                             options={'curated': True}))


def build_snapshot() -> EndpointSpecSnapshot:
    """The RSS catalog from its definition; the same code always gives the same snapshot."""
    endpoints = (endpoint_spec(), *(news_endpoint_spec(*row) for row in NEWS_ENDPOINTS))
    digest = hashlib.sha256(json.dumps([asdict(e) for e in endpoints], sort_keys=True, default=list).encode()).hexdigest()
    return EndpointSpecSnapshot(vendor_id=VENDOR_ID, retrieved_at=REVIEWED_AT, content_hash=digest,
                                parser_version=PARSER_VERSION, sources=spec_sources(), endpoints=endpoints)


class RSSDataSource(AbstractDataSource):
    """Public RSS and Atom feeds. `getter(url, validators)` stands in for feeds.fetch in tests and checks."""

    def __init__(self, config=None, *, getter=None, **kwargs):
        self.feed_getter = getter or fetch
        self.news = News(self.feed_getter)
        # Local RSS keeps its user's subscriptions and articles in its state folder. They exist before the base class,
        # which sets up the local resource (local_extras) inside its own __init__.
        state = config.get('subscriptions_state') if isinstance(config, Mapping) else None
        # Its reads go through this source's feed getter as it is at the time (tests stand one in after building).
        self.local = local_operations.Local(state, getter=lambda url, validators: self.feed_getter(url, validators)) if state else None
        # Registered here, once the card is whole: the base class would register before rss_fetch and the site panel.
        auto_register = bool(kwargs.pop('auto_register', True))
        super().__init__(config=config, auto_register=False, **kwargs)
        # The catalog comes from the definition, never from a documentation download.
        self.spec_ingestion.parsers = ()
        # rss_fetch is what the RSS Viewer asks; it runs the same read as data_fetch rss.read_feeds.
        self.supported_pulses.append(definition())
        self.agent_card.setdefault('meta', {})['supported_pulses'] = self.supported_pulses
        from . import site
        if site.enabled(self):
            # A saved Plaza identity is known before registration; a new one after it (register below).
            self._load_plaza_credentials_from_pool()
            self._publish_site_panel()
        if self.plaza_url and auto_register:
            self.register()

    def _publish_site_panel(self):
        from . import site
        try:
            return site.publish(self)
        except (OSError, ValueError) as error:
            self.logger.error(f'The RSS Feed Groups panel could not be published: {error}')
            return False

    def register(self, **kwargs):
        # Plaza keeps the card a registration sends. A first registration assigns the identity the site panel's release
        # names: publish for it, then send the card once more.
        response = super().register(**kwargs)
        from . import site
        if site.enabled(self) and getattr(self, 'agent_id', None) and not site.current(self) and self._publish_site_panel():
            self._force_plaza_register_once = True
            response = super().register(**kwargs)
        return response

    def source_profile(self) -> Mapping[str, Any]:
        configured = self._config_data.get('source_profile') if isinstance(self._config_data.get('source_profile'), Mapping) else {}
        profile = {
            'source_id': VENDOR_ID, 'source_name': 'RSS Data Source', 'provider': 'Public RSS and Atom feeds',
            'description': 'Public RSS 2.0, RSS 1.0 (RDF) and Atom feeds the user adds, read as plain-text articles.',
            'translations': {'zh-Hant': {'description': '使用者新增的公開 RSS 2.0、RSS 1.0（RDF）與 Atom 訂閱，以純文字文章讀取。'}},
            'symbology': {**copy.deepcopy(SYMBOLOGY), 'evidence': [f'attas/data_agent_network/catalogs/{VENDOR_ID}/manifest.json']},
            'connectivity': {'status': 'configured', 'transport': 'https', 'pulse_name': 'data_availability',
                             'authentication': 'No key is required.', 'configuration_required': [],
                             'notes': ['Reads only public addresses on the standard ports; private, local and '
                                       'redirected-to-HTTP addresses are refused.']},
            'coverage': {'asset_classes': []},
            'entitlement': {'status': 'provider-terms', 'allowed_output_forms': ['request-scoped provider response'],
                            'notes': ['Feed content belongs to its publishers and comes under their terms.']},
        }
        return {**profile, **copy.deepcopy(dict(configured)),
                'symbology': copy.deepcopy(dict(configured.get('symbology') or profile['symbology']))}

    def spec_sources(self) -> Tuple[VendorSpecSource, ...]:
        return spec_sources()

    def data_access_status(self) -> Dict[str, Any]:
        """Ready, as other keyless sources are (yfinance): a Terminal offers a source for a model, in the Watch or a
        panel's source choice, only when its card says it can attempt a fetch."""
        configured = self._configured_data_access()
        if configured is not None:
            return self._normalized_data_access(configured)
        return self._normalized_data_access(
            fetch_ready=True, attempt_ready=True, credential_required=False, credential_configured=False,
            verification='public', reason='Reads public RSS and Atom feeds without a credential.')

    def refresh_spec_catalog(self, ingestion):
        snapshot = build_snapshot()
        self.spec_repository.save(snapshot)
        self.spec_snapshot = snapshot
        if hasattr(self, 'data_catalog'):
            self.data_catalog = self._catalog_entries(snapshot)
            self._apply_source_card()
        return snapshot

    def execute_endpoint(self, endpoint, parameters, auth_context):
        def answer(status, **extra):
            return EndpointExecutionResult(status=status, endpoint_id=endpoint.endpoint_id,
                                           data_schema=endpoint.response_schema, cost=endpoint.cost, **extra)
        run = {ENDPOINT_ID: self._read_feeds, FEEDS_ENDPOINT: self._feeds, NEWS_LIST_ENDPOINT: self._news_list,
               ARTICLE_ENDPOINT: self._article, STOCK_NEWS_ENDPOINT: self._stock_news,
               GROUPS_ENDPOINT: self._groups}.get(endpoint.operation)
        if run is None:
            return answer('not_executable', error='This source answers only its catalog endpoints.')
        try:
            return answer('completed', data=run(dict(parameters or {})))
        except ValueError as error:
            return answer('failed', error=str(error))

    def _read_feeds(self, parameters):
        request = check(parameters)
        return read_feeds(request['feeds'], request.get('limit', 20), getter=self.feed_getter)

    def _feeds(self, parameters):
        return self.news.feeds(checked(FEEDS_INPUT, parameters, 'feeds').get('tags', ()))

    def _news_list(self, parameters):
        request = checked(NEWS_LIST_INPUT, parameters, 'news list')
        return self.news.news_list(request.get('tags', ()), request.get('feeds'), request.get('limit', 30))

    def _article(self, parameters):
        request = checked(ARTICLE_INPUT, parameters, 'article')
        return self.news.article(request['feed'], request['id'])

    def _groups(self, parameters):
        from .groups import groups
        request = checked(GROUPS_INPUT, parameters, 'feed groups')
        return groups(request.get('language'), request.get('topic'), request.get('query'))

    def _stock_news(self, parameters):
        request = checked(STOCK_NEWS_INPUT, parameters, 'stock news')
        return self.news.stock_news(request['keyword'], request.get('aliases', ()), request.get('tags', ()),
                                    request.get('limit', 20))

    def fetch_pulse_payload(self, pulse_name, input_data, pulse_definition):
        if pulse_name == local_operations.LOCAL_PULSE:
            if self.local is None:
                raise HTTPException(404, 'This RSS source keeps no subscriptions.')
            return self.local.dispatch({key: value for key, value in dict(input_data or {}).items() if key != '_caller'})
        if pulse_name != PULSE:
            return super().fetch_pulse_payload(pulse_name, input_data, pulse_definition)
        # Plaza adds verified caller context; it is never a feed input.
        data = {key: value for key, value in dict(input_data or {}).items() if key != '_caller'}
        result = self.data_fetch({'endpoint_id': ENDPOINT_ID, 'parameters': data, 'canonical': False})
        if result.get('status') != 'completed':
            raise HTTPException(422, str(result.get('error') or 'Invalid RSS request.'))
        return {'response': result['data']}

    def local_extras(self, config) -> Mapping[str, Any]:
        """What this source's local resource offers beside the data pulses (local_resources.source_local): rss_fetch and,
        when it keeps subscriptions, rss_local; the RSS Viewer's Phema and its two view releases (the reader its Phema
        names now, and the earlier viewer that copies from before revision 5 still name). Releases are captured in
        `view_releases`, outside the checkout."""
        pulses = (PULSE, local_operations.LOCAL_PULSE) if self.local else (PULSE,)
        folder = self._config_data.get('view_releases')
        publisher = 'local-' + config['resourceId']
        if self.local:
            self.local.agent_id = publisher
        if not folder:
            return {'pulses': pulses}
        from phemacast.network.service import endpoint
        from .release import PHEMA_REVISION, READER, VIEW, phema
        origin = endpoint(config)['url'].rstrip('/')
        views = {}
        for release in (VIEW, READER):
            directory, manifest = release.capture(publisher, origin, Path(folder), dependencies=None)
            release.advertise(self.agent_card, manifest)
            views[manifest['release']] = directory
        return {'pulses': pulses, 'views': views,
                'phemas': {VIEW_ID: {'name': 'RSS Viewer', 'revision': PHEMA_REVISION, 'phema': phema(publisher)}}}

    def start_reader(self):
        """Read the subscribed feeds in the background while this Local RSS runs."""
        if self.local:
            self.local.start()


__all__ = ['ARTICLE_ENDPOINT', 'ENDPOINT_ID', 'FEED', 'FEEDS_ENDPOINT', 'NEWS_LIST_ENDPOINT', 'PARSER_VERSION', 'RSSDataSource',
           'STOCK_NEWS_ENDPOINT', 'VENDOR_ID', 'build_snapshot']
