"""A component's settings: the fields its parts list entry declares, and the values chosen for it in the manager.

A parts list entry may declare `settings`, a list of fields::

    {"id": "servers", "type": "list", "names": {"en": "Other servers"}, "descriptions": {"en": "One per line."},
     "pattern": "^http://127\\\\.0\\\\.0\\\\.1:[0-9]{1,5}/v1$", "max_items": 8, "default": []}

Types: `text` (`pattern`, `max_length`), `list` of texts (`pattern`, `max_length` of each, `max_items`), `boolean`,
`number` (`minimum`, `maximum`, `integer`) and `choice` (`options`, each `{"value", "names"}`). Fields that share a
`group` (`{"id", "names"}`) belong to one thing, such as one model server, and show together in one row. A manager
shows them as ordinary form controls, never as JSON. What the component says about them while it runs (its health
answer's `details`: each group's state, each list entry's state, values to suggest) shows beside them. The values live beside the component's data, in `component-settings.json` in
its data folder, so they stay through updates, roll backs and a removal that keeps the data. The component reads them
when it starts (`read(state_dir)`), so a change applies at its next start; the manager restarts a running one.
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = 'prompits.component-settings/1'
FILE = 'component-settings.json'
TYPES = ('text', 'list', 'boolean', 'number', 'choice')
MAX_FIELDS = 64
MAX_TEXT = 500
MAX_ITEMS = 32
MAX_OPTIONS = 32
_ID = re.compile(r'^[a-z][a-z0-9_]{0,39}$')
_LANGUAGE = re.compile(r'^[a-z]{2,3}(-[A-Za-z]{2,4})?$')


class SettingsError(ValueError):
    """A settings declaration is malformed, or a value does not fit its field."""


def _texts(value: Any, where: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping) or not all(isinstance(k, str) and _LANGUAGE.match(k) and isinstance(v, str) and len(v) <= 1000
                                                  for k, v in value.items()):
        raise SettingsError(f'{where}: names and descriptions map a language to its text')
    return dict(value)


def _whole(value: Any, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SettingsError(f'{where} must be a whole number from {low} to {high}')
    return value


def parse_fields(component_id: str, raw: Any) -> tuple[dict[str, Any], ...]:
    """The fields a parts list entry declares, checked; () when it declares none."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_FIELDS:
        raise SettingsError(f'{component_id}: settings must be a list of at most {MAX_FIELDS} fields')
    fields, seen = [], set()
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get('id'), str) or not _ID.match(item['id']) or item['id'] in seen:
            raise SettingsError(f'{component_id}: each setting needs its own short lowercase id')
        where = f"{component_id}/{item['id']}"
        kind = item.get('type')
        if kind not in TYPES:
            raise SettingsError(f'{where}: type must be one of {", ".join(TYPES)}')
        field = {'id': item['id'], 'type': kind, 'names': _texts(item.get('names'), where),
                 'descriptions': _texts(item.get('descriptions'), where)}
        group = item.get('group')
        if group is not None:
            if not isinstance(group, Mapping) or not isinstance(group.get('id'), str) or not _ID.match(group['id']):
                raise SettingsError(f'{where}: a group needs its own short lowercase id')
            field['group'] = {'id': group['id'], 'names': _texts(group.get('names'), where)}
        if kind in ('text', 'list'):
            field['max_length'] = _whole(item.get('max_length', 200), where + ' max_length', 1, MAX_TEXT)
            if item.get('pattern') is not None:
                try:
                    re.compile(item['pattern'])
                except (re.error, TypeError) as error:
                    raise SettingsError(f'{where}: pattern is not a regular expression') from error
                field['pattern'] = item['pattern']
        if kind == 'list':
            field['max_items'] = _whole(item.get('max_items', 8), where + ' max_items', 1, MAX_ITEMS)
        if kind == 'number':
            field['integer'] = item.get('integer') is True
            for bound in ('minimum', 'maximum'):
                value = item.get(bound)
                if value is not None:
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                        raise SettingsError(f'{where}: {bound} must be a number')
                    field[bound] = value
        if kind == 'choice':
            options = item.get('options')
            if not isinstance(options, list) or not 1 <= len(options) <= MAX_OPTIONS:
                raise SettingsError(f'{where}: a choice lists 1 to {MAX_OPTIONS} options')
            field['options'] = []
            for option in options:
                if not isinstance(option, Mapping) or not isinstance(option.get('value'), str) or not option['value']:
                    raise SettingsError(f'{where}: each option needs a value')
                field['options'].append({'value': option['value'], 'names': _texts(option.get('names'), where)})
        empty = {'text': '', 'list': [], 'boolean': False, 'number': field.get('minimum', 0),
                 'choice': field['options'][0]['value'] if kind == 'choice' else None}[kind]
        field['default'] = value_of(field, item.get('default', empty))
        seen.add(item['id'])
        fields.append(field)
    return tuple(fields)


def value_of(field: Mapping[str, Any], value: Any) -> Any:
    """`value` checked against its field; SettingsError says why it does not fit."""
    where, kind = field['id'], field['type']
    if kind == 'text':
        return _text(field, value, where, allow_empty=True)
    if kind == 'list':
        if not isinstance(value, list) or len(value) > field['max_items']:
            raise SettingsError(f'{where}: at most {field["max_items"]} entries')
        items = [_text(field, item, where, allow_empty=False) for item in value]
        return list(dict.fromkeys(items))
    if kind == 'boolean':
        if not isinstance(value, bool):
            raise SettingsError(f'{where}: must be on or off')
        return value
    if kind == 'number':
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise SettingsError(f'{where}: must be a number')
        if field.get('integer') and value != int(value):
            raise SettingsError(f'{where}: must be a whole number')
        if 'minimum' in field and value < field['minimum'] or 'maximum' in field and value > field['maximum']:
            raise SettingsError(f'{where}: must be from {field.get("minimum", "any")} to {field.get("maximum", "any")}')
        return int(value) if field.get('integer') else value
    if not any(option['value'] == value for option in field['options']):
        raise SettingsError(f'{where}: choose one of the offered values')
    return value


def _text(field: Mapping[str, Any], value: Any, where: str, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise SettingsError(f'{where}: must be text')
    value = value.strip()
    if not value and allow_empty:
        return ''
    if not value or len(value) > field['max_length']:
        raise SettingsError(f'{where}: must be 1 to {field["max_length"]} characters')
    if field.get('pattern') and not re.fullmatch(field['pattern'], value):
        raise SettingsError(f'{where}: {value[:80]!r} is not allowed here')
    return value


def check_values(fields: Iterable[Mapping[str, Any]], values: Mapping[str, Any]) -> dict[str, Any]:
    """Every field's value: the one given, checked, or its default. A value for no field is refused."""
    fields = list(fields)
    known = {field['id'] for field in fields}
    unknown = sorted(set(values) - known)
    if unknown:
        raise SettingsError('Unknown settings: ' + ', '.join(unknown[:5]))
    return {field['id']: value_of(field, values[field['id']]) if field['id'] in values else field['default'] for field in fields}


def read(state_dir: str | os.PathLike[str], fields: Iterable[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """The values saved for a component, as its program reads them at start: {} when none were saved. With `fields`
    (the manager), each one checked and completed with defaults; a value that no longer fits is left at its default."""
    path = Path(state_dir) / FILE
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        document = {}
    saved = document.get('values') if isinstance(document, dict) and document.get('schema') == SCHEMA else None
    saved = dict(saved) if isinstance(saved, dict) else {}
    if fields is None:
        return saved
    values = {}
    for field in fields:
        try:
            values[field['id']] = value_of(field, saved[field['id']]) if field['id'] in saved else field['default']
        except SettingsError:
            values[field['id']] = field['default']
    return values


def write(data_dir: str | os.PathLike[str], fields: Iterable[Mapping[str, Any]], values: Mapping[str, Any]) -> dict[str, Any]:
    """Check `values` and keep them for the component (owner-only file, replaced at once); return what was kept."""
    checked = check_values(fields, values)
    folder = Path(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / (FILE + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump({'schema': SCHEMA, 'values': checked}, handle, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(temporary, folder / FILE)
    return checked


def shown(fields: Iterable[Mapping[str, Any]], values: Mapping[str, Any], language: str = 'en') -> list[dict[str, Any]]:
    """The fields as a manager page draws them, in `language` (else English), each with its current value."""
    def say(texts):
        return texts.get(language) or texts.get('en') or ''
    rows = []
    for field in fields:
        row = {'id': field['id'], 'type': field['type'], 'name': say(field['names']) or field['id'],
               'description': say(field['descriptions']), 'value': values.get(field['id'], field['default']),
               'default': field['default']}
        for key in ('max_length', 'max_items', 'minimum', 'maximum', 'integer'):
            if key in field:
                row[key] = field[key]
        if 'group' in field:
            row['group'] = {'id': field['group']['id'], 'name': say(field['group']['names']) or field['group']['id']}
        if field['type'] == 'choice':
            row['options'] = [{'value': option['value'], 'name': say(option['names']) or option['value']} for option in field['options']]
        rows.append(row)
    return rows
