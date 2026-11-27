"""How Phemas on the same Terminal work together: the values a Phema sends and receives (its ports), and what each
page value lets other panels see and change (`share`).

A Phema declares them as document data, in its composition's `phemacast:ports` extension:

    "phemacast:ports": {
      "publishes":  [{"name": "instrument", "type": "instrument", "title": {"en": "Selected instrument"},
                      "from": {"$param": "/instrument"}}],
      "subscribes": [{"name": "instrument", "type": "instrument", "title": {"en": "Instrument"},
                      "to": "/instrument"}],
      "share": {"account": "none", "range": "read"},
      "panels": "read"
    }

The viewer decides which panels are linked (link groups); the document never does. Ports match by type, and also by
name when a Phema has two inputs of the same type. `share` says what each page value lets other panels do: `readWrite`
(the default), `read`, or `none`, which keeps it out of the Terminal's list of open Phemas and from other panels.
`panels` asks that the Phema's agent views may list the other open Phemas and read (`read`) or also set
(`readWrite`) their shared page values; the viewer allows it in the Phema's permission review.

Values are data: `check_value` holds each to its type and size and refuses anything that looks like a credential.
"""
from __future__ import annotations

import copy
import json
import re

from .controls import NAME, PARAM_POINTER, SECRET, PORT_TYPES, SHARES, binding_kind, check_binding, ControlError

MAX_PORTS = 16
MAX_VALUE_BYTES = 32 * 1024
MAX_ROWS = 500
MAX_INSTRUMENTS = 50
SHARE = SHARES
DEFAULT_SHARE = 'readWrite'
TYPES = PORT_TYPES
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
INTERVAL = re.compile(r'^[1-9][0-9]{0,3}(s|m|h|d|wk|w|mo|y)$')
SYMBOL = re.compile(r'^[A-Za-z0-9^][A-Za-z0-9.^=_:/-]{0,39}$')
AGENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$')


class PortError(ValueError):
    pass


def _title(value, where):
    if value is None:
        return
    if (not isinstance(value, dict) or not isinstance(value.get('en'), str) or not value['en'].strip()
            or any(not isinstance(k, str) or not isinstance(v, str) or not v.strip() or len(v) > 80 for k, v in value.items())):
        raise PortError(f'{where}: a title is {{language: text}} with English, each at most 80 characters.')


def validate_ports(ports, page_parameters=None):
    """A Phema's `ports` declaration, checked against its page values when given; PortError says what is wrong."""
    if not isinstance(ports, dict) or set(ports) - {'publishes', 'subscribes', 'share', 'panels'}:
        raise PortError('ports lists what the Phema publishes, what it subscribes to and what it shares.')
    if ports.get('panels', 'read') not in ('read', 'readWrite'):
        raise PortError('panels is read or readWrite.')
    declared = page_parameters if isinstance(page_parameters, dict) else None
    shares = ports.get('share', {})
    if not isinstance(shares, dict) or len(shares) > 64 or any(v not in SHARE for v in shares.values()):
        raise PortError('share maps a page value to readWrite, read or none.')
    for name in shares:
        if not isinstance(name, str) or (declared is not None and name not in declared):
            raise PortError(f'share: the page has no value {name}.')
    for side in ('publishes', 'subscribes'):
        rows = ports.get(side, [])
        if not isinstance(rows, list) or len(rows) > MAX_PORTS:
            raise PortError(f'{side}: at most {MAX_PORTS} ports.')
        names, types = set(), {}
        for i, port in enumerate(rows):
            where = f'{side}[{i}]'
            allowed = {'name', 'type', 'title', 'from' if side == 'publishes' else 'to'}
            if not isinstance(port, dict) or set(port) - allowed or {'name', 'type'} - set(port):
                raise PortError(f'{where}: a port has a name, a type, a title and where its value '
                                + ('comes from.' if side == 'publishes' else 'goes.'))
            if not isinstance(port['name'], str) or not NAME.fullmatch(port['name']) or port['name'] in names:
                raise PortError(f'{where}: each port has its own name.')
            names.add(port['name'])
            if port['type'] not in TYPES:
                raise PortError(f'{where}: type is one of ' + ', '.join(TYPES) + '.')
            types.setdefault(port['type'], []).append(port['name'])
            _title(port.get('title'), where)
            if side == 'publishes':
                source = port.get('from')
                if source is not None:
                    if binding_kind(source) not in ('$param', '$control'):
                        raise PortError(f'{where}: a port sends a page value or a control\'s state.')
                    try:
                        check_binding(source, where + '.from')
                    except ControlError as exc:
                        raise PortError(str(exc)) from exc
                    if binding_kind(source) == '$param' and declared is not None:
                        _declared(source['$param'], declared, where)
            else:
                target = port.get('to')
                if not isinstance(target, str) or not PARAM_POINTER.fullmatch(target):
                    raise PortError(f'{where}: a received value goes to a page value, as "/instrument".')
                if declared is not None:
                    _declared(target, declared, where)
                if share_of(ports, target.split('/')[1]) != 'readWrite':
                    raise PortError(f'{where}: {target.split("/")[1]} is not shared for other panels to change.')
    return copy.deepcopy(ports)


def _declared(pointer, declared, where):
    name = pointer.split('/')[1]
    if name not in declared:
        raise PortError(f'{where}: the page has no value {name}.')
    return name


def share_of(ports, name):
    """What a page value lets other panels do: readWrite (the default), read or none."""
    share = ((ports or {}).get('share') or {}).get(name, DEFAULT_SHARE)
    if share not in SHARE:
        raise PortError('share is readWrite, read or none.')
    return share


def shared(ports, values, *, writing=False):
    """The page values another panel may see (`writing=False`) or set (`writing=True`)."""
    allowed = ('readWrite',) if writing else ('readWrite', 'read')
    return {name: copy.deepcopy(value) for name, value in (values or {}).items() if share_of(ports, name) in allowed}


EXTENSION = 'phemacast:ports'


def panel_access(phema):
    """What the Phema's agent views ask to do with the other open Phemas: read, readWrite, or None."""
    from .composition import composition
    ports = ((composition(phema) or {}).get('extensions') or {}).get(EXTENSION) or {}
    return ports.get('panels') if ports.get('panels') in ('read', 'readWrite') else None


def page_parameters(phema):
    """A Phema's page values as it declares them: its layout's `params`, else its input schema's properties."""
    from .composition import composition
    document = ((composition(phema) or {}).get('presentation') or {}).get('document') or {}
    params = (document.get('design') or {}).get('params')
    if isinstance(params, dict):
        return params
    return ((phema.get('input_schema') or {}).get('properties') or {})


def _no_secrets(value, depth=0):
    if depth > 8:
        raise PortError('The value is too deeply nested.')
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or SECRET.search(key):
                raise PortError('Credentials never travel between panels.')
            _no_secrets(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _no_secrets(child, depth + 1)


def _instrument(value):
    if isinstance(value, str):
        value = {'symbol': value}
    if (not isinstance(value, dict) or set(value) - {'symbol', 'market'} or not isinstance(value.get('symbol'), str)
            or not SYMBOL.fullmatch(value['symbol'])
            or not isinstance(value.get('market', ''), str) or len(value.get('market', '')) > 40):
        raise PortError('An instrument is {symbol, market?}, as the source writes it.')
    return value


def check_value(port_type, value):
    """A value sent through a port of `port_type`, checked; returns it in its canonical form."""
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise PortError('A port value is JSON data.') from exc
    if size > MAX_VALUE_BYTES:
        raise PortError(f'A port value is at most {MAX_VALUE_BYTES // 1024} KB.')
    _no_secrets(value)
    if port_type == 'instrument':
        return _instrument(value)
    if port_type == 'instruments':
        if not isinstance(value, list) or len(value) > MAX_INSTRUMENTS:
            raise PortError(f'Instruments are a list of at most {MAX_INSTRUMENTS}.')
        return [_instrument(item) for item in value]
    if port_type == 'date':
        if not isinstance(value, str) or not DATE.fullmatch(value):
            raise PortError('A date is YYYY-MM-DD.')
        return value
    if port_type == 'dateRange':
        if (not isinstance(value, dict) or set(value) != {'start', 'end'}
                or not all(isinstance(value[k], str) and DATE.fullmatch(value[k]) for k in value)
                or value['start'] > value['end']):
            raise PortError('A date range is {start, end}, each YYYY-MM-DD, start first.')
        return value
    if port_type == 'interval':
        if not isinstance(value, str) or not INTERVAL.fullmatch(value):
            raise PortError('An interval is a bar size, such as 1d or 5m.')
        return value
    if port_type == 'text':
        if not isinstance(value, str) or len(value) > 2000:
            raise PortError('Text is at most 2,000 characters.')
        return value
    if port_type == 'number':
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PortError('Use a number.')
        return value
    if port_type == 'boolean':
        if not isinstance(value, bool):
            raise PortError('Use true or false.')
        return value
    if port_type == 'agent':
        if not isinstance(value, str) or not AGENT.fullmatch(value):
            raise PortError('An agent is named by its id.')
        return value
    if port_type == 'rows':
        if (not isinstance(value, dict) or set(value) - {'fields', 'rows', 'model'}
                or not isinstance(value.get('fields'), list) or len(value['fields']) > 50
                or any(not isinstance(f, str) or len(f) > 100 for f in value['fields'])
                or not isinstance(value.get('rows'), list) or len(value['rows']) > MAX_ROWS
                or any(not isinstance(r, dict) for r in value['rows'])):
            raise PortError(f'Rows are {{fields, rows}} with at most {MAX_ROWS} rows.')
        model = value.get('model')
        if model is not None and (not isinstance(model, dict) or set(model) - {'id', 'version'}
                                  or not all(isinstance(model.get(k), str) and model[k] for k in ('id', 'version'))):
            raise PortError('A model is named by {id, version}.')
        return value
    raise PortError('Port type is one of ' + ', '.join(TYPES) + '.')


def matches(sender, receivers):
    """The receiving ports a sent value reaches in one panel: same type, and the same name too when the panel has
    several inputs of that type."""
    same_type = [port for port in receivers if port['type'] == sender['type']]
    if len(same_type) <= 1:
        return same_type
    return [port for port in same_type if port['name'] == sender['name']]
