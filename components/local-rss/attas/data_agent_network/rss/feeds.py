"""Bounded public-feed transport and RSS/Atom parsing; no cookies, proxies or user state."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree
from xml.parsers import expat

import certifi

MAX_BYTES = 1_048_576
MAX_SECONDS = 12
MAX_RESULT_BYTES = 220_000  # Below the confined host's 300 KB envelope, including escaped Unicode.
XML_BASE = '{http://www.w3.org/XML/1998/namespace}base'


def public_url(value):
    """Syntax check only. Resolution is checked again and pinned at every network hop."""
    try:
        p = urlsplit(value.strip())
        port = p.port
        if (p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password
                or port not in (None, 80 if p.scheme == 'http' else 443)
                or any(ord(c) <= 32 or ord(c) == 127 for c in value) or '\\' in value):
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
        authority = '[' + host + ']' if ':' in host else host
        return urlunsplit((p.scheme, authority, quote(p.path or '/', safe="/%:@!$&'()*+,;=-._~"),
                           quote(p.query, safe="/%?:@!$&'()*+,;=-._~"), ''))
    except (ValueError, UnicodeError, AttributeError) as error:
        raise ValueError('Use a public HTTP or HTTPS feed URL without credentials or a custom port.') from error


def destinations(host, port):
    try:
        addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    except OSError as error:
        raise ValueError('The feed hostname could not be resolved.') from error
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ValueError('Feeds must resolve only to public internet addresses.')
    return addresses


@lru_cache(maxsize=1)
def tls_context():
    """The public certificate authorities certifi carries, as the Terminal's direct vendor calls use. A Python's own
    store can be empty (python.org's macOS build has none until its "Install Certificates" step runs), which failed
    every HTTPS feed. Certificate and host name checks stay on."""
    return ssl.create_default_context(cafile=certifi.where())


def fetch(url, validators=None):
    """Pin the checked IP to the actual socket, keeping TLS verification and SNI on the original host."""
    end = time.monotonic() + MAX_SECONDS
    url = public_url(url)
    original_origin = urlsplit(url).netloc
    for hop in range(4):
        p = urlsplit(url)
        port = 443 if p.scheme == 'https' else 80
        addresses = destinations(p.hostname, port)
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        connection = http.client.HTTPConnection(p.hostname, port, timeout=min(remaining, 4))
        try:
            connection.sock = socket.create_connection((addresses[0], port), timeout=min(remaining, 4))
            if p.scheme == 'https':
                connection.sock = tls_context().wrap_socket(connection.sock, server_hostname=p.hostname)
            # Host names the bare host: public_url allows only the standard ports, and http.client would otherwise
            # send host:443 for HTTPS over this pinned plain connection.
            headers = {'Host': '[' + p.hostname + ']' if ':' in p.hostname else p.hostname,
                       'User-Agent': 'RetisRSS/1.0 (+https://retis.ai)', 'Accept-Encoding': 'identity',
                       'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml'}
            if p.netloc == original_origin:
                for name, key in [('If-None-Match', 'etag'), ('If-Modified-Since', 'last_modified')]:
                    value = (validators or {}).get(key, '')
                    if value and '\r' not in value and '\n' not in value:
                        headers[name] = value
            connection.request('GET', p.path + ('?' + p.query if p.query else ''), headers=headers)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                if hop == 3 or not response.getheader('Location'):
                    raise ValueError('The feed redirected too many times.')
                target = public_url(urljoin(url, response.getheader('Location')))
                if p.scheme == 'https' and urlsplit(target).scheme != 'https':
                    raise ValueError('The feed redirected from HTTPS to HTTP.')
                url = target
                continue
            meta = {'etag': (response.getheader('ETag') or '')[:512],
                    'last_modified': (response.getheader('Last-Modified') or '')[:128]}
            if response.status == 304:
                return None, url, meta
            if response.status != 200:
                raise ValueError('The feed returned HTTP ' + str(response.status) + '.')
            if response.getheader('Content-Encoding', 'identity').lower() not in ('', 'identity'):
                raise ValueError('The feed returned an unsupported compressed response.')
            body = bytearray()
            while True:
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                if connection.sock:
                    connection.sock.settimeout(min(remaining, 4))
                chunk = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError('The feed exceeds the 1 MB size limit.')
                if not chunk:
                    return bytes(body), url, meta
        finally:
            connection.close()
    raise ValueError('The feed could not be retrieved.')


class Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        tag = tag.rsplit(':', 1)[-1]
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'br', 'div', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        tag = tag.rsplit(':', 1)[-1]
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, value):
        if not self.hidden:
            self.parts.append(value)


def plain(value, limit=5000):
    parser = Text()
    parser.feed(value)
    return '\n'.join(' '.join(line.split()) for line in ''.join(parser.parts).splitlines() if line.strip())[:limit]


def local(tag):
    return tag.rsplit('}', 1)[-1].lower()


def child(node, *names):
    for name in names:
        for item in node:
            if local(item.tag) == name.lower():
                return item
    return None


def text(node, *names):
    item = child(node, *names)
    return ''.join(item.itertext()).strip() if item is not None else ''


def timestamp(value):
    try:
        try:
            result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            result = parsedate_to_datetime(value)
        return result.replace(tzinfo=result.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, IndexError, OverflowError):
        return None


def link(node, base):
    base = urljoin(base, node.get(XML_BASE, ''))
    for item in node:
        if local(item.tag) == 'link' and item.get('rel', 'alternate') == 'alternate':
            value = item.get('href') or ''.join(item.itertext()).strip()
            try:
                return public_url(urljoin(urljoin(base, item.get(XML_BASE, '')), value))
            except ValueError:
                pass
    return ''


def parse(body, url, limit=20):
    if not body or len(body) > MAX_BYTES:
        raise ValueError('The feed is empty or too large.')
    # Expat sees declarations in every XML encoding, including UTF-16; never expand entities or load a DTD.
    guard = expat.ParserCreate()
    def refuse(*args):
        raise ValueError('Feed document types and entity declarations are not supported.')
    guard.StartDoctypeDeclHandler = refuse
    guard.EntityDeclHandler = refuse
    try:
        guard.Parse(body, True)
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, expat.ExpatError) as error:
        raise ValueError('The response is not valid RSS or Atom XML.') from error
    kind = local(root.tag)
    if kind not in ('rss', 'feed', 'rdf'):
        raise ValueError('The response is not an RSS or Atom feed.')
    channel = child(root, 'channel')
    channel = channel if channel is not None else root
    base = urljoin(url, root.get(XML_BASE, ''))
    title = plain(text(channel, 'title'), 200) or urlsplit(url).hostname
    entries = [n for n in (root if kind == 'rdf' else channel) if local(n.tag) in ('item', 'entry')]
    items, seen = [], set()
    for entry in entries[:200]:
        entry_url = link(entry, base)
        headline = plain(text(entry, 'title'), 300)
        identity = text(entry, 'guid', 'id') or entry_url or headline
        if not identity:
            continue
        key = hashlib.sha256((url + '\n' + identity).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        author = child(entry, 'author')
        content = child(entry, 'encoded', 'content', 'description', 'summary')
        # XHTML content keeps its block boundaries before conversion to safe plain text.
        raw = (ElementTree.tostring(content, encoding='unicode') if content is not None and len(content)
               else ''.join(content.itertext()) if content is not None else '')
        item = {'id': key, 'title': headline or 'Untitled', 'url': entry_url,
                'published_at': timestamp(text(entry, 'published', 'pubdate', 'date', 'updated')),
                'author': plain(text(author, 'name') if author is not None and len(author) else text(entry, 'author', 'creator'), 200),
                'content': plain(raw), 'summary': plain(text(entry, 'summary', 'description'), 500)}
        # An aggregator (Google News) names each article's outlet in RSS 2.0's <source>; Atom's <source> is the
        # original feed's metadata, whose <title> names it.
        origin = child(entry, 'source')
        publisher = plain(text(origin, 'title') if origin is not None and len(origin) else
                          ''.join(origin.itertext()) if origin is not None else '', 200)
        if publisher:
            item['publisher'] = publisher
        items.append(item)
        if len(items) >= limit:
            break
    return {'title': title, 'site_url': link(channel, base), 'items': items}


def read_feeds(feeds, limit=20, *, getter=fetch, max_bytes=MAX_RESULT_BYTES):
    """Bounded batch, partial failures and conditional reads. The answer is trimmed to `max_bytes` of JSON for a reply
    (None: untrimmed, for Local RSS's own article library)."""
    from concurrent.futures import ThreadPoolExecutor
    def read(feed):
        result = {'url': feed['url'].strip(), 'name': feed.get('name', ''),
                  'checked_at': datetime.now(timezone.utc).isoformat()}
        if feed.get('enabled') is False:
            return {**result, 'status': 'disabled'}
        try:
            url = public_url(result['url'])
            body, final, validators = getter(url, feed)
            if body is None:
                return {**result, **validators, 'status': 'not_modified'}
            return {**result, **validators, **parse(body, final, limit), 'status': 'ready'}
        # Each error says what happened, never the address or the system's own message.
        except ssl.SSLCertVerificationError:
            return {**result, 'status': 'error', 'error': "The feed's certificate could not be verified."}
        except TimeoutError:
            return {**result, 'status': 'error', 'error': 'The feed could not be reached within the time limit.'}
        except (OSError, http.client.HTTPException):
            return {**result, 'status': 'error', 'error': 'The feed could not be reached.'}
        except ValueError as error:
            return {**result, 'status': 'error', 'error': str(error)}
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(read, feeds))
    answer = {'source_mode': 'parameters', 'feeds': results}
    # The host counts escaped JSON bytes. Trim fairly, keeping feed outcomes visible.
    while max_bytes is not None and len(json.dumps(answer).encode()) > max_bytes:
        largest = max(results, key=lambda r: len(json.dumps(r)))
        if not largest.get('items'):
            break
        largest['items'].pop()
        largest['truncated'] = True
    return answer
