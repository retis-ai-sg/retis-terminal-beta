"""Bonjour finds the local resources running on this computer.

A resource announces `_phemacast._tcp` with its id, name, kind and this computer's addresses. A Terminal keeps an
advert only when one of those addresses is its own computer's, and always connects to `127.0.0.1:<port>`: a
resource listens on loopback only, so an advert from another computer (or a fake one) can point nowhere but at a
program on this computer, and the client checks that the program there answers with the advertised id.
"""
import asyncio
import ipaddress
import logging
import re
import time

LOG = logging.getLogger(__name__)

SERVICE = '_phemacast._tcp.local.'
PROTOCOL = 'phemacast.local/2'
LOOPBACK = '127.0.0.1'
# How often discovery checks its Bonjour sockets and resolves what it found again.
MAINTAIN_SECONDS = 30
# A wait that took this much longer by the wall clock than asked: the computer slept (or the process was
# frozen) in between. Sockets opened before a sleep may no longer hear Bonjour, even on the same addresses.
SLEPT_SECONDS = 60


def own_addresses():
    from .service import host_addresses
    return host_addresses()


def browsed_addresses():
    """The addresses Bonjour browses on (IPv4 only), so a new temporary IPv6 address doesn't count as a new network."""
    return {address for address in own_addresses() if address.version == 4}


def decode_service(info, own=None):
    properties = {k.decode('utf-8', 'strict'): v.decode('utf-8', 'strict') for k, v in info.properties.items() if isinstance(k, bytes) and isinstance(v, bytes)}
    if properties.get('protocol') != PROTOCOL or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}', properties.get('id', '')):
        raise ValueError('Unknown local resource protocol or identity.')
    label = properties.get('name', '')
    if not 1 <= len(label) <= 80 or any(ord(c) < 32 for c in label):
        raise ValueError('Invalid local resource name.')
    if not 1024 <= int(info.port or 0) <= 65535:
        raise ValueError('Invalid local resource port.')
    own = own if own is not None else own_addresses()
    advertised = set()
    for address in info.parsed_addresses()[:16]:
        try:advertised.add(ipaddress.ip_address(address.split('%')[0]))
        except ValueError:pass
    if not advertised & set(own):
        raise ValueError('Resource runs on another computer.')
    return {'id': properties['id'], 'name': label, 'kind': properties.get('kind', '')[:48], 'protocol': PROTOCOL,
            'url': f'http://{LOOPBACK}:{int(info.port)}'}


async def answers(row, timeout=2.0):
    """The program at the row's address is the advertised resource (it answers its descriptor with the same id)."""
    import httpx
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=timeout) as client:
            response = await client.get(row['url'] + '/local/v2/resource')
            return response.status_code == 200 and response.json().get('id') == row['id']
    except (httpx.HTTPError, ValueError):
        return False


class Discovery:
    def __init__(self, *, interfaces=None):
        self.interfaces = interfaces
        self.rows, self.tasks = {}, set()
        # Every service Bonjour still lists. A row leaves `rows` while its resource
        # is unreachable, and Bonjour reports no change when an identical advert
        # returns, so rescans keep resolving these names to bring it back.
        self.names = set()
        self.status = 'stopped'
        self.zc = self.browser = self.maintenance = None
        self.addresses = set()  # this computer's addresses when browsing began

    async def start(self):
        try:
            await self.browse()
            self.status = 'discovering'
        except ImportError:
            self.status = 'unavailable'
            await self.close()
            self.status = 'unavailable'
            return
        except OSError:
            # No network to browse on yet (the Terminal started offline): the maintenance below tries again.
            await self.stop_browsing()
            self.status = 'unavailable'
        async def maintain():
            while True:
                began = time.time()
                await asyncio.sleep(MAINTAIN_SECONDS)
                slept = time.time() - began > MAINTAIN_SECONDS + SLEPT_SECONDS
                try:
                    await self.refresh(reopen=slept)
                    self.status = 'discovering'
                except Exception as exc:  # one failed round never ends discovery: tried again in 30 s
                    LOG.warning('Bonjour discovery failed; trying again: %s', exc)
        self.maintenance = asyncio.create_task(maintain())

    async def browse(self):
        from zeroconf import ServiceStateChange
        from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
        self.addresses = browsed_addresses()
        self.zc = AsyncZeroconf(**({'interfaces': self.interfaces} if self.interfaces else {}))
        def change(zeroconf, service_type, name, state_change):
            if state_change == ServiceStateChange.Removed:
                self.names.discard(name); self.rows.pop(name, None)
            elif len(self.tasks) < 32:
                if len(self.names) < 256:self.names.add(name)
                task = asyncio.create_task(self.resolve(name))
                self.tasks.add(task); task.add_done_callback(self.tasks.discard)
        self.browser = AsyncServiceBrowser(self.zc.zeroconf, SERVICE, handlers=[change])

    async def refresh(self, reopen=False):
        """Every 30 s. After a network change this computer's addresses differ: Bonjour opened its sockets on the
        interfaces of the time, so it browses again on today's, and hears the adverts resources make on their new
        addresses. After the computer slept (`reopen`) it browses again too, since sockets opened before the sleep
        may hear nothing even on the same addresses. Rows found earlier stay until the rescan finds they no longer
        answer."""
        if reopen or self.zc is None or browsed_addresses() != self.addresses:
            await self.stop_browsing()
            try:
                await self.browse()
            except BaseException:
                await self.stop_browsing()  # half-open sockets: the next round opens them again
                raise
        return await self.rescan()

    async def stop_browsing(self):
        browser, zc, self.browser, self.zc = self.browser, self.zc, None, None
        for task in list(self.tasks):task.cancel()  # lookups on the old sockets: the rescan looks again
        await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            if browser:await browser.async_cancel()
            if zc:await zc.async_close()
        except OSError:pass  # sockets of an interface that went away

    async def resolve(self, name):
        if self.zc is None:return  # browsing again after a network change
        try:
            info = await self.zc.async_get_service_info(SERVICE, name, timeout=2000)
            if info:
                row = decode_service(info)
                if (len(self.rows) < 256 or name in self.rows) and await answers(row):
                    self.rows[name] = (time.monotonic() + 120, row)
                else:
                    self.rows.pop(name, None)
        except (ValueError, UnicodeError, OSError):
            self.rows.pop(name, None)

    def resources(self):
        now = time.monotonic()
        self.rows = {k: v for k, v in self.rows.items() if v[0] > now}
        found = {}
        for _, row in self.rows.values():
            found.setdefault(row['id'], row)
        return list(found.values())

    async def rescan(self):
        # Browsing stays active. Resolve known services again to refresh TTLs; a resource that no longer answers
        # leaves the list, and one that returns is found again.
        if self.zc is None:
            return self.resources()
        names = list(dict.fromkeys([*self.rows, *self.names]))[:32]
        await asyncio.gather(*(self.resolve(name) for name in names))
        return self.resources()

    async def close(self):
        if self.maintenance:
            self.maintenance.cancel(); await asyncio.gather(self.maintenance, return_exceptions=True)
        if self.browser:await self.browser.async_cancel()
        for task in list(self.tasks):task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.zc:await self.zc.async_close()
        self.browser = self.zc = None
        self.status = 'stopped'


def advertised_addresses():
    """This computer's addresses to announce: its private LAN addresses, or loopback when no network is up."""
    import socket
    import psutil
    found = []
    for values in psutil.net_if_addrs().values():
        for value in values:
            if value.family == socket.AF_INET:
                address = ipaddress.ip_address(value.address)
                if address.is_private and not address.is_loopback and not address.is_link_local:
                    found.append(value.address)
    return found or [LOOPBACK]


# How long a check waits to hear a resource's own advert answered on this computer (`Advertisement.heard`).
HEARD_SECONDS = 3.0


class Advertisement:
    def __init__(self, config):
        self.config = config
        self.zc = self.info = self.announcing = None
        self.addresses = []

    async def start(self):
        from zeroconf.asyncio import AsyncZeroconf, AsyncServiceInfo
        config = self.config
        self.addresses = addresses = advertised_addresses()
        self.zc = AsyncZeroconf(interfaces=addresses)
        self.info = AsyncServiceInfo(SERVICE, config['resourceId'] + '.' + SERVICE,
            parsed_addresses=addresses, port=int(config['port']), server=config['resourceId'] + '.local.',
            properties={'id': config['resourceId'], 'name': config['name'], 'kind': config['kind'],
                        'protocol': PROTOCOL, 'scope': 'host'})
        try:
            # The first announcements go out in the background over the next half second.
            self.announcing = await self.zc.async_register_service(self.info)
        except BaseException:
            await self.zc.async_close()
            self.zc = None
            raise

    def moved(self):
        """This computer's addresses changed since the advert began (another network): it names addresses a Terminal
        no longer counts as its own computer's."""
        return bool(self.zc) and sorted(advertised_addresses()) != sorted(self.addresses)

    async def heard(self, timeout=HEARD_SECONDS):
        """Whether this computer hears the advert now: True, False, or None when it can't tell.

        A separate Bonjour socket asks for the advert by multicast, as a Terminal does, and must hear the answer. It
        listens on `*:5353` only, never on an address of its own, so it takes no unicast answer meant for another program
        on this computer (the newest socket bound to an address:5353 receives every unicast datagram sent there). On
        2026-11-26 three running resources went unheard for hours while their programs kept running; this fails then."""
        if not self.zc or not self.info:
            return False
        if all(ipaddress.ip_address(address).is_loopback for address in self.addresses):
            return None  # no network: the check's socket has no interface to ask on
        from zeroconf import DNSQuestionType, InterfaceChoice
        from zeroconf.asyncio import AsyncZeroconf
        try:
            probe = AsyncZeroconf(interfaces=InterfaceChoice.Default)
        except OSError:
            return None
        try:
            info = await probe.async_get_service_info(SERVICE, self.info.name, timeout=int(timeout * 1000),
                                                      question_type=DNSQuestionType.QM)
        except (OSError, ValueError):
            return None
        finally:
            try:await probe.async_close()
            except OSError:pass
        return bool(info) and info.port == int(self.config['port']) and \
            (info.properties or {}).get(b'id') == self.config['resourceId'].encode()

    async def close(self, goodbye=True):
        """Stop announcing. With `goodbye`, Terminals drop the resource at once; without it (the advert is replaced right
        away on the same addresses) they keep it until the new advert refreshes it."""
        if self.zc:
            zc, self.zc = self.zc, None
            if isinstance(self.announcing, asyncio.Future) and not self.announcing.done():
                self.announcing.cancel()  # an announcement still to come would follow the goodbye
            try:
                registry = getattr(getattr(zc, 'zeroconf', None), 'registry', None)
                if not goodbye and self.info and registry is not None:
                    registry.async_remove(self.info)
                # Closing sends the goodbye for what is still registered and waits for it. Unregistering first, as before
                # 2026-11-26, only scheduled the goodbye, and closing then dropped it unsent.
                await zc.async_close()
            except OSError:pass  # an address that went away can't send the goodbye
