"""Named lists for tagging: which listed company, currency or industry a news item is about (named-entity recognition).

Alvin, 2026-11-24: a named list is static (entries typed in the view) or dynamic (source URLs and how often to read
them again), for example all Taiwan stocks, currencies or industries; an analyst tags every news item against them.

Recognition has two steps. A gazetteer match finds each list's names, other names and codes in an item's headline and
summary, longest first, with 臺 read as 台 and company suffixes such as 股份有限公司 dropped. A bare number counts as a
code only in brackets or with its exchange suffix (台積電(2330), 2330.TW), and a name of two characters or a short
Latin word is only a candidate to check: many Taiwan short names are also common words (統一, 幸福, 地球). The analyst
then keeps the candidates the item is really about and names list members the match missed, which are looked up in
the same lists. Nothing outside a list becomes an entity.

A dynamic list's URLs are the one thing this component reads itself: public HTTPS addresses the person typed, read
from this computer with no key (checked at every hop, as Local RSS reads feeds), kept in memory until the list's
refresh interval passes (lost on restart) and never stored.
"""
from datetime import datetime, timezone
import csv
import hashlib
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
import unicodedata
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import certifi

MAX_BYTES = 8 * 1024 * 1024
MAX_SECONDS = 30
MAX_COLUMNS = 60
MAX_ENTRIES = 6000  # one list, all its sources together
MAX_CANDIDATES = 12  # per news item, strongest first
CACHED_URLS = 16
CJK = re.compile(r'[぀-ヿ㐀-鿿豈-﫿가-힯]')
FOLD = str.maketrans({'臺': '台'})
CORPORATE = re.compile(r'(股份有限公司|有限公司|股份公司|\s*(co\.?,?\s*ltd\.?|corporation|corp\.?|inc\.?|limited|ltd\.?|plc|company))$', re.I)
LATIN_WORD = re.compile(r'[0-9a-z]')
NUMBER = re.compile(r'(?<![\d.,])(\d{4,6}[A-Z]?)(\.TWO|\.TW)?(?![\d])')
LETTERS = re.compile(r'(?<![A-Za-z0-9])([A-Z]{3,6})(?![A-Za-z0-9])')
OPEN, CLOSE = set('(（[【〔「'), set(')）]】〕」')


# --- presets ---------------------------------------------------------------------------------------------------------
TWSE = 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L'
TPEX = 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O'
CURRENCIES = [
    ('USD', '美元', ['美金', 'US dollar', 'U.S. dollar', 'greenback']), ('TWD', '新台幣', ['台幣', 'NT dollar', 'Taiwan dollar']),
    ('JPY', '日圓', ['日元', '日幣', 'Japanese yen', 'yen']), ('EUR', '歐元', ['euro']), ('CNY', '人民幣', ['renminbi', 'Chinese yuan', 'yuan']),
    ('HKD', '港幣', ['港元', 'Hong Kong dollar']), ('KRW', '韓元', ['韓圜', 'Korean won']), ('GBP', '英鎊', ['sterling', 'British pound']),
    ('AUD', '澳幣', ['澳元', 'Australian dollar']), ('CAD', '加幣', ['加元', 'Canadian dollar']), ('CHF', '瑞郎', ['瑞士法郎', 'Swiss franc']),
    ('SGD', '新加坡幣', ['星元', 'Singapore dollar']), ('NZD', '紐幣', ['紐元', 'New Zealand dollar']), ('INR', '印度盧比', ['Indian rupee', 'rupee']),
    ('THB', '泰銖', ['Thai baht', 'baht']), ('MYR', '馬幣', ['令吉', 'ringgit']), ('IDR', '印尼盾', ['rupiah']), ('VND', '越南盾', ['Vietnamese dong']),
    ('PHP', '菲律賓披索', ['Philippine peso']), ('ZAR', '南非幣', ['南非蘭特', 'South African rand']), ('MXN', '墨西哥披索', ['Mexican peso']),
    ('BRL', '巴西里拉', ['Brazilian real']), ('SEK', '瑞典克朗', ['Swedish krona']), ('NOK', '挪威克朗', ['Norwegian krone'])]
# TWSE and TPEx industry codes (產業別), as both exchanges' company lists give them, with the short words news uses
# (two-character ones are only candidates to check).
INDUSTRIES = [
    ('01', '水泥工業', ['水泥', 'cement']), ('02', '食品工業', ['食品股', 'food industry']), ('03', '塑膠工業', ['塑化', 'plastics']),
    ('04', '紡織纖維', ['紡織', 'textiles']), ('05', '電機機械', ['電機', 'electric machinery']), ('06', '電器電纜', ['電線電纜', 'electrical and cable']),
    ('08', '玻璃陶瓷', ['glass and ceramics']), ('09', '造紙工業', ['造紙', 'paper and pulp']), ('10', '鋼鐵工業', ['鋼鐵', 'iron and steel', 'steel']),
    ('11', '橡膠工業', ['橡膠', 'rubber']), ('12', '汽車工業', ['汽車股', 'automobile', 'automotive']),
    ('14', '建材營造', ['營建', '營造', 'building materials and construction']), ('15', '航運業', ['航運', 'shipping']),
    ('16', '觀光餐旅', ['觀光', 'tourism and hospitality']), ('17', '金融保險', ['金融股', '金控', 'finance and insurance']),
    ('18', '貿易百貨', ['百貨', 'trading and consumer goods']), ('20', '其他業', []), ('21', '化學工業', ['化工', 'chemicals']),
    ('22', '生技醫療', ['生技', 'biotechnology', 'biotech', 'healthcare']), ('23', '油電燃氣', ['油電', 'oil, gas and electricity']),
    ('24', '半導體業', ['半導體', '晶圓', 'semiconductor', 'semiconductors', 'chipmaker', 'chipmakers']),
    ('25', '電腦及週邊設備', ['電腦週邊', 'computer and peripheral equipment']), ('26', '光電業', ['光電', 'optoelectronics']),
    ('27', '通信網路', ['網通', '電信', 'communications and internet']), ('28', '電子零組件', ['零組件', '被動元件', 'electronic components']),
    ('29', '電子通路', ['electronic distribution']), ('30', '資訊服務', ['資服', 'information services']), ('31', '其他電子', ['other electronics']),
    ('32', '文化創意', ['文創', 'cultural and creative']), ('33', '農業科技', ['農科', 'agricultural technology']),
    ('35', '綠能環保', ['綠能', 'green energy']), ('36', '數位雲端', ['雲端', 'digital and cloud', 'cloud computing']),
    ('37', '運動休閒', ['運動休閒股', 'sports and leisure']), ('38', '居家生活', ['home living'])]
PRESETS = [
    {'id': 'taiwan-stocks', 'title': {'en': 'All Taiwan stocks (TWSE and TPEx)', 'zh': '全部台股（上市與上櫃）'},
     'list': {'name': 'Taiwan Stock', 'kind': 'dynamic', 'refresh_hours': 24, 'sources': [
         {'url': TWSE, 'code': '公司代號', 'name': '公司簡稱', 'aliases': ['公司名稱', '英文簡稱'], 'suffix': '.TW'},
         {'url': TPEX, 'code': 'SecuritiesCompanyCode', 'name': 'CompanyAbbreviation', 'aliases': ['CompanyName', 'Symbol'], 'suffix': '.TWO'}]}},
    {'id': 'fx', 'title': {'en': 'Currencies (FX)', 'zh': '外匯幣別'},
     'list': {'name': 'FX', 'kind': 'static', 'entries': [{'code': c, 'name': n, 'aliases': a} for c, n, a in CURRENCIES]}},
    {'id': 'industries', 'title': {'en': 'Taiwan industries', 'zh': '台灣產業別'},
     'list': {'name': 'Industries', 'kind': 'static', 'entries': [{'code': c, 'name': n, 'aliases': a} for c, n, a in INDUSTRIES]}},
]


# --- reading a public URL --------------------------------------------------------------------------------------------
def public_url(value):
    """A public HTTPS URL without credentials or a custom port, or ValueError (checked again at every hop)."""
    try:
        p = urlsplit(str(value).strip())
        if (p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443)
                or any(ord(c) <= 32 or ord(c) == 127 for c in str(value)) or '\\' in str(value)):
            raise ValueError()
        host = p.hostname.encode('idna').decode('ascii').lower()
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError as error:
            if ':' in host or host.replace('.', '').isdigit():
                raise ValueError() from error
        return urlunsplit(('https', host, quote(p.path or '/', safe="/%:@!$&'()*+,;=-._~"),
                           quote(p.query, safe="/%?:@!$&'()*+,;=-._~"), ''))
    except (ValueError, UnicodeError, AttributeError) as error:
        raise ValueError('A list URL is a public https:// address without a user name or a custom port.') from error


def fetch_url(url):
    """(body, content type) of a public HTTPS URL, each hop's address checked and pinned, at most MAX_BYTES."""
    end, url = time.monotonic() + MAX_SECONDS, public_url(url)
    context = ssl.create_default_context(cafile=certifi.where())
    for hop in range(4):
        p = urlsplit(url)
        try:
            addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM)))
        except OSError as error:
            raise ValueError('The list host could not be found.') from error
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ValueError('A list URL must reach only public internet addresses.')
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise ValueError('The list took too long to read.')
        connection = http.client.HTTPConnection(p.hostname, 443, timeout=min(remaining, 10))
        try:
            connection.sock = context.wrap_socket(socket.create_connection((addresses[0], 443), timeout=min(remaining, 10)),
                                                  server_hostname=p.hostname)
            connection.request('GET', p.path + ('?' + p.query if p.query else ''), headers={
                'Host': p.hostname, 'User-Agent': 'RetisLocalAnalyst/1.0 (+https://retis.ai)', 'Accept-Encoding': 'identity',
                'Accept': 'application/json, text/csv, text/plain;q=0.5'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                if hop == 3 or not response.getheader('Location'):
                    raise ValueError('The list URL redirected too many times.')
                url = public_url(urljoin(url, response.getheader('Location')))
                continue
            if response.status != 200:
                raise ValueError(f'The list URL answered HTTP {response.status}.')
            if response.getheader('Content-Encoding', 'identity').lower() not in ('', 'identity'):
                raise ValueError('The list URL answered with an unsupported compression.')
            body = bytearray()
            while len(body) <= MAX_BYTES:
                if time.monotonic() > end:
                    raise ValueError('The list took too long to read.')
                chunk = response.read1(65536)
                if not chunk:
                    return bytes(body), (response.getheader('Content-Type') or '').split(';')[0].strip().lower()
                body += chunk
            raise ValueError('The list is larger than 8 MB.')
        except (OSError, http.client.HTTPException) as error:
            raise ValueError('The list URL could not be read: ' + (str(error) or type(error).__name__)[:160]) from error
        finally:
            connection.close()
    raise ValueError('The list URL redirected too many times.')


def cell(value):
    if isinstance(value, bool) or value is None or isinstance(value, (dict, list)):
        return ''
    return unicodedata.normalize('NFKC', str(value)).strip()[:200]


def parse_rows(body, content_type=''):
    """(rows, columns) from a JSON array of objects, an object holding one, a {code: name} object, or CSV."""
    text = None
    for encoding in ('utf-8-sig', 'cp950'):
        try:
            text = body.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError('The list is neither UTF-8 nor Big5 text.')
    rows = None
    if 'csv' not in content_type:
        try:
            found = json.loads(text)
        except json.JSONDecodeError:
            found = None
        if isinstance(found, dict):
            arrays = [v for k, v in sorted(found.items(), key=lambda kv: kv[0] not in ('data', 'items', 'rows', 'results', 'result'))
                      if isinstance(v, list) and v and all(isinstance(x, dict) for x in v[:20])]
            if arrays:
                found = arrays[0]
            elif found and all(isinstance(v, (str, int, float)) for v in found.values()):
                found = [{'key': k, 'value': v} for k, v in found.items()]
            elif found and all(isinstance(v, dict) for v in found.values()):
                found = [{'key': k, **v} for k, v in found.items()]
        if isinstance(found, list):
            rows = [row for row in found if isinstance(row, dict)]
    if rows is None:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t|')
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if not rows:
        raise ValueError('The list has no rows: use a JSON array of objects, a {code: name} object, or CSV with a header.')
    columns = []
    for row in rows[:50]:
        for column in row:
            if isinstance(column, str) and column.strip() and column not in columns and len(columns) < MAX_COLUMNS:
                columns.append(column)
    return [{k: cell(v) for k, v in row.items() if k in columns} for row in rows], columns


_CACHE, _LOCK = {}, threading.Lock()


def forget():
    with _LOCK:
        _CACHE.clear()


def read_source(url, refresh_hours, now):
    """(rows, columns, fetched_at, note) for one URL, read again once its copy is older than refresh_hours."""
    url = public_url(url)
    with _LOCK:
        kept = _CACHE.get(url)
    if kept and now - kept['at'] < refresh_hours * 3600:
        return kept['rows'], kept['columns'], kept['fetched_at'], ''
    try:
        body, content_type = fetch_url(url)
        rows, columns = parse_rows(body, content_type)
    except ValueError as error:
        if kept:  # an older copy beats none; the note says so
            return kept['rows'], kept['columns'], kept['fetched_at'], 'kept the copy read at ' + kept['fetched_at'] + ': ' + str(error)[:160]
        raise
    fetched = datetime.fromtimestamp(int(now), timezone.utc).isoformat().replace('+00:00', 'Z')
    with _LOCK:
        _CACHE[url] = {'at': now, 'rows': rows, 'columns': columns, 'fetched_at': fetched}
        while len(_CACHE) > CACHED_URLS:
            _CACHE.pop(min(_CACHE, key=lambda k: _CACHE[k]['at']))
    return rows, columns, fetched, ''


# --- entries ---------------------------------------------------------------------------------------------------------
def entry(code, name, aliases=()):
    code, name = cell(code)[:40], cell(name)[:80]
    others = [a for a in dict.fromkeys(cell(a)[:80] for a in aliases) if a and a != name]
    return {'code': code, 'name': name or code, 'aliases': others[:6]} if name or code else None


def source_entries(rows, source):
    """A dynamic source's entries from its rows, by the columns the person chose; the suffix is added to each code."""
    if not source.get('name'):
        raise ValueError('Choose the column that has the names.')
    suffix, found = source.get('suffix') or '', []
    for row in rows:
        made = entry(row.get(source.get('code') or '', ''), row.get(source['name'], ''),
                     [row.get(column, '') for column in source.get('aliases') or []])
        if made:
            if made['code']:
                made['code'] = (made['code'] + suffix)[:40]
            found.append(made)
    return found


def materialize(named, now=None):
    """{id, name, entries, fetched_at, notes} for a named list; ValueError when a dynamic source cannot be read."""
    now = time.time() if now is None else now
    if named['kind'] == 'static':
        entries, fetched, notes = [e for e in (entry(x.get('code'), x.get('name'), x.get('aliases') or []) for x in named.get('entries') or []) if e], None, []
    else:
        entries, fetched, notes = [], None, []
        for source in named.get('sources') or []:
            rows, _, at, note = read_source(source['url'], named.get('refresh_hours', 24), now)
            entries += source_entries(rows, source)
            fetched = min(fetched, at) if fetched else at
            if note:
                notes.append(note)
    unique, seen = [], set()
    for item in entries:
        key = (item['code'] or item['name']).casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    if not unique:
        raise ValueError(f'The list "{named["name"]}" has no entries.')
    return {'id': named['id'], 'name': named['name'], 'kind': named['kind'], 'entries': unique[:MAX_ENTRIES],
            'fetched_at': fetched, 'notes': notes, 'cut': max(0, len(unique) - MAX_ENTRIES)}


def check(named, now=None):
    """What the view shows for a list: its size, a few entries, and each source's columns to choose from."""
    now = time.time() if now is None else now
    sources = []
    for source in (named.get('sources') or []) if named['kind'] == 'dynamic' else []:
        rows, columns, at, note = read_source(source['url'], named.get('refresh_hours', 24), now)
        sources.append({'url': source['url'], 'columns': columns, 'rows': len(rows), 'fetched_at': at,
                        'sample': [{k: row.get(k, '')[:60] for k in columns[:8]} for row in rows[:3]], **({'note': note} if note else {})})
    try:
        made = materialize(named, now)
    except ValueError as error:
        return {'status': 'incomplete', 'reason': str(error)[:300], 'sources': sources}
    return {'status': 'ready', 'entries': len(made['entries']), 'cut': made['cut'], 'fetched_at': made['fetched_at'],
            'sample': made['entries'][:5], 'sources': sources, 'notes': made['notes']}


# --- matching --------------------------------------------------------------------------------------------------------
def fold(value):
    return unicodedata.normalize('NFKC', value).translate(FOLD).lower().strip()


def forms_of(item):
    """The names an entry is found by: its name, other names, and each without a company suffix."""
    for value in [item['name'], *item.get('aliases', [])]:
        value = fold(value)
        yield value
        bare = CORPORATE.sub('', value).strip(' ,.')
        if bare != value:
            yield bare


def strength_of(form):
    """'strong', 'check' (a candidate the analyst must confirm) or None (too short to look for)."""
    if CJK.search(form):
        return 'strong' if len(form) >= 3 else 'check' if len(form) == 2 else None
    if len(form) < 3:
        return None
    return 'strong' if len(form) >= 5 or ' ' in form else 'check'


class Matcher:
    """Finds the entries of several lists in text; built once per set of lists and reused."""

    def __init__(self, lists):
        self.lists = lists  # [{id, name, entries}]
        self.forms, self.codes, self.starts = {}, {}, {}
        for li, named in enumerate(lists):
            for ei, item in enumerate(named['entries']):
                for form in forms_of(item):
                    if strength_of(form):
                        self.forms.setdefault(form, set()).add((li, ei))
                code = item['code'].split('.')[0] if item['code'] else ''
                if code and (code.isdigit() or code.isupper()) and len(code) >= 3:
                    self.codes.setdefault(code, set()).add((li, ei))
        for form in self.forms:
            self.starts.setdefault(form[0], set()).add(len(form))
        self.starts = {c: sorted(lengths, reverse=True) for c, lengths in self.starts.items()}

    def candidate(self, li, ei, strength, seen):
        named, item = self.lists[li], self.lists[li]['entries'][ei]
        key = item['code'] or item['name']
        return {'id': named['name'] + ':' + key, 'list': named['name'], 'code': item['code'], 'name': item['name'],
                'strength': strength, 'seen': seen}

    def find(self, text):
        """The candidates in one text, strongest first: names (longest at each place) and codes in context."""
        found = {}

        def add(hits, strength, seen):
            strength = strength if len(hits) == 1 else 'check'  # a name two entries share needs the analyst
            for li, ei in sorted(hits):
                made = self.candidate(li, ei, strength, seen)
                if made['id'] not in found or (found[made['id']]['strength'] == 'check' and strength == 'strong'):
                    found[made['id']] = made
        low = fold(text)
        i = 0
        while i < len(low):
            for length in self.starts.get(low[i], ()):
                form = low[i:i + length]
                if len(form) == length and form in self.forms:
                    latin = not CJK.search(form)
                    if latin and ((i and LATIN_WORD.match(low[i - 1])) or (i + length < len(low) and LATIN_WORD.match(low[i + length]))):
                        continue
                    add(self.forms[form], strength_of(form), form)
                    i += length - 1
                    break
            i += 1
        plain = unicodedata.normalize('NFKC', text)
        for match in NUMBER.finditer(plain):
            code, suffix = match.group(1), match.group(2)
            before, after = plain[:match.start()].rstrip()[-1:], plain[match.end():].lstrip()[:1]
            if code in self.codes and (suffix or (before in OPEN and after in CLOSE)):
                add(self.codes[code], 'strong', match.group(0))
        for match in LETTERS.finditer(plain):
            if match.group(1) in self.codes:
                add(self.codes[match.group(1)], 'strong', match.group(1))
        ranked = sorted(found.values(), key=lambda c: (c['strength'] != 'strong', c['id']))
        return ranked[:MAX_CANDIDATES]

    def resolve(self, value):
        """The one entry a name, code or 'List:code' the analyst gave stands for, or None."""
        if not isinstance(value, str) or not value.strip():
            return None
        value = value.strip()
        for named in self.lists:
            prefix = named['name'] + ':'
            if value.startswith(prefix):
                key = value[len(prefix):].strip().casefold()
                for item in named['entries']:
                    if key in ((item['code'] or '').casefold(), item['name'].casefold()):
                        return self.candidate(self.lists.index(named), named['entries'].index(item), 'analyst', value)
                return None
        hits = self.forms.get(fold(value)) or self.codes.get(value.split('.')[0].upper()) or set()
        if len(hits) != 1:
            return None
        li, ei = next(iter(hits))
        return self.candidate(li, ei, 'analyst', value)


_MATCHERS = {}


def matcher(lists):
    """A Matcher for these materialized lists, reused while their entries stay the same."""
    print_ = hashlib.sha256(json.dumps([[x['name'], x['entries']] for x in lists], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with _LOCK:
        found = _MATCHERS.get(print_)
    if found is None:
        found = Matcher(lists)
        with _LOCK:
            _MATCHERS[print_] = found
            while len(_MATCHERS) > 8:
                _MATCHERS.pop(next(iter(_MATCHERS)))
    return found
