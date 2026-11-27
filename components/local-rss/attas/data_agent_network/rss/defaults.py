"""The RSS source's default feeds: public Chinese-language finance and business feeds, each with its tags.

Each address was read through this source on 2026-11-22 and gave articles from that week. Tags say where a feed comes
from, its language and what it covers:

- region: `tw`, `hk`, `cn`, `intl`
- language: `zh-Hant`, `zh-Hans`
- topic: `finance`, `stocks`, `markets`, `industry`, `international`, `cross-strait`, `personal-finance`, `research`,
  `technology`, `business`, `aggregator`
- `keyword` and `stock-news`: a search feed whose address takes a keyword (`template`, with `{keyword}` in it). Stock
  news fills it with the keyword asked for; read as a default feed, it searches its own `keyword`.

Data only: news.py reads these. Feed content belongs to its publishers and comes under their terms.
"""
from __future__ import annotations

from urllib.parse import quote


def _udn(category: str) -> str:
    return f'https://money.udn.com/rssfeed/news/1001/{category}?ch=money'


def _yahoo(category: str) -> str:
    return f'https://tw.stock.yahoo.com/rss?category={category}'


def _google(edition: str, country: str, language: str) -> str:
    return (f'https://news.google.com/rss/headlines/section/topic/BUSINESS?hl={edition}&gl={country}'
            f'&ceid={country}:{language}')


TW, HK = ('tw', 'zh-Hant'), ('hk', 'zh-Hant')
GOOGLE_SEARCH_TW = 'https://news.google.com/rss/search?q={keyword}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant'

FEEDS = (
    {'id': 'udn-money-stocks', 'name': '經濟日報 證券', 'url': _udn('5590'), 'tags': (*TW, 'finance', 'stocks')},
    {'id': 'udn-money-industry', 'name': '經濟日報 產業', 'url': _udn('5591'), 'tags': (*TW, 'finance', 'industry')},
    {'id': 'udn-money-international', 'name': '經濟日報 國際', 'url': _udn('5588'), 'tags': (*TW, 'finance', 'international')},
    {'id': 'udn-money-cross-strait', 'name': '經濟日報 兩岸', 'url': _udn('5589'), 'tags': (*TW, 'finance', 'cross-strait')},
    {'id': 'udn-money-personal-finance', 'name': '經濟日報 理財', 'url': _udn('5592'),
     'tags': (*TW, 'finance', 'personal-finance')},
    {'id': 'cna-finance', 'name': '中央社 產經', 'url': 'https://feeds.feedburner.com/rsscna/finance', 'tags': (*TW, 'finance')},
    {'id': 'cna-technology', 'name': '中央社 科技', 'url': 'https://feeds.feedburner.com/rsscna/technology',
     'tags': (*TW, 'technology')},
    {'id': 'ltn-business', 'name': '自由時報 財經', 'url': 'https://news.ltn.com.tw/rss/business.xml', 'tags': (*TW, 'finance')},
    {'id': 'ettoday-finance', 'name': 'ETtoday 財經', 'url': 'https://feeds.feedburner.com/ettoday/finance',
     'tags': (*TW, 'finance')},
    {'id': 'moneydj-news', 'name': 'MoneyDJ 即時新聞',
     'url': 'https://www.moneydj.com/KMDJ/RssCenter.aspx?svc=NR&fno=1&arg=MB010000', 'tags': (*TW, 'finance', 'stocks')},
    {'id': 'technews-finance', 'name': '財經新報', 'url': 'https://finance.technews.tw/feed/',
     'tags': (*TW, 'finance', 'technology')},
    {'id': 'yahoo-tw-stock-news', 'name': 'Yahoo股市 最新新聞', 'url': _yahoo('news'), 'tags': (*TW, 'finance', 'stocks')},
    {'id': 'yahoo-tw-stock-market', 'name': 'Yahoo股市 台股盤勢', 'url': _yahoo('tw-market'), 'tags': (*TW, 'stocks', 'markets')},
    {'id': 'yahoo-tw-stock-international', 'name': 'Yahoo股市 國際財經', 'url': _yahoo('intl-markets'),
     'tags': (*TW, 'international', 'markets')},
    {'id': 'yahoo-tw-stock-research', 'name': 'Yahoo股市 研究報告', 'url': _yahoo('research'), 'tags': (*TW, 'stocks', 'research')},
    {'id': 'mingpao-economy', 'name': '明報 經濟', 'url': 'https://news.mingpao.com/rss/pns/s00004.xml', 'tags': (*HK, 'finance')},
    {'id': 'mingpao-instant-economy', 'name': '明報 即時 經濟', 'url': 'https://news.mingpao.com/rss/ins/s00002.xml',
     'tags': (*HK, 'finance')},
    {'id': 'ftchinese', 'name': 'FT中文网', 'url': 'https://www.ftchinese.com/rss/feed',
     'tags': ('intl', 'zh-Hans', 'finance', 'international')},
    {'id': 'nytimes-cn-business', 'name': '纽约时报中文网 商业', 'url': 'https://cn.nytimes.com/rss/business/',
     'tags': ('intl', 'zh-Hans', 'business', 'international')},
    {'id': 'dw-chinese-economy', 'name': 'DW 中文 經濟', 'url': 'https://rss.dw.com/rdf/rss-chi-eco',
     'tags': ('intl', 'zh-Hans', 'business', 'international')},
    {'id': 'google-news-tw-business', 'name': 'Google News 台灣 商業', 'url': _google('zh-TW', 'TW', 'zh-Hant'),
     'tags': (*TW, 'business', 'aggregator')},
    {'id': 'google-news-hk-business', 'name': 'Google News 香港 商業', 'url': _google('zh-HK', 'HK', 'zh-Hant'),
     'tags': (*HK, 'business', 'aggregator')},
    {'id': 'google-news-cn-business', 'name': 'Google News 中国 商业', 'url': _google('zh-CN', 'CN', 'zh-Hans'),
     'tags': ('cn', 'zh-Hans', 'business', 'aggregator')},
    {'id': 'google-news-tw-stocks', 'name': 'Google News 台股', 'keyword': '台股', 'template': GOOGLE_SEARCH_TW,
     'url': GOOGLE_SEARCH_TW.replace('{keyword}', quote('台股', safe='')),
     'tags': (*TW, 'stocks', 'aggregator', 'keyword', 'stock-news')},
)
# The group each default feed is listed under in the RSS Viewer: the feed group directory's Traditional Chinese name for
# the group that lists it (feed_groups.json).
GROUP_OF = {
    'udn-money-stocks': '台股', 'moneydj-news': '台股', 'yahoo-tw-stock-news': '台股', 'yahoo-tw-stock-market': '台股',
    'yahoo-tw-stock-research': '台股', 'google-news-tw-stocks': '台股',
    'udn-money-industry': '產業與科技', 'cna-technology': '產業與科技', 'technews-finance': '產業與科技',
    'udn-money-international': '國際與兩岸', 'udn-money-cross-strait': '國際與兩岸', 'yahoo-tw-stock-international': '國際與兩岸',
    'cna-finance': '綜合財經', 'ltn-business': '綜合財經', 'ettoday-finance': '綜合財經', 'google-news-tw-business': '綜合財經',
    'udn-money-personal-finance': '理財',
    'mingpao-economy': '香港財經', 'mingpao-instant-economy': '香港財經', 'google-news-hk-business': '香港財經',
    'ftchinese': '国际财经', 'nytimes-cn-business': '国际财经', 'dw-chinese-economy': '国际财经',
    'google-news-cn-business': '商业与科技',
}
BY_ID = {feed['id']: feed for feed in FEEDS}
TAGS = tuple(sorted({tag for feed in FEEDS for tag in feed['tags']}))


def filled(feed, keyword: str) -> str:
    """A keyword feed's address searching for `keyword`."""
    return feed['template'].replace('{keyword}', quote(keyword, safe=''))
