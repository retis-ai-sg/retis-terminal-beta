"""Controls a Phema surface may declare, rendered by the host (`phemacast:control.<type>`).

A control is document data, never code: its properties are values, and an event's handler is a short list of the
declarative actions below. Names follow .NET Windows Forms (`System.Windows.Forms`: Control, DataGridView,
DataGridViewColumn, DataGridViewCellStyle, TextBox, ComboBox …), written camelCase. Placement stays the Phema layout's
job, so Location, Size, Dock and Anchor are not properties. Colors and fonts are theme tokens, never raw values.

`VOCABULARY` is the single source: `validate_control` checks a document against it, `json_schema` gives the contract a
host publishes for each control renderer, and `write_generated` writes the same vocabulary for the browser
(`phemacast/web/control-vocabulary.js`) and as a schema document (`phemacast/schemas/phema/controls.json`).

A value may be a binding, an object with one `$` key:
- `{"$param": "/name"}` a page value of this panel;
- `{"$result": {"reference": id, "path": "/pointer"}}` a reference's result;
- `{"$control": {"name": control, "property": state}}` another control's state on the same page;
- `{"$event": "/pointer"}` the event's details (inside an action only);
- `{"$link": port}`, `{"$panel": {"panel", "param"}}`, `{"$panels": {...}}`, `{"$opened": name}` other panels on the
  same Terminal (phemacast/core/ports.py);
- `{"$agents": {"pulse": name}}` the agents offering a pulse that the viewer may call.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

VERSION = '1.0.0'
PREFIX = 'phemacast:control.'

LIMITS = {
    'controls': 64,          # controls in one surface, nested ones included
    'depth': 4,              # containers inside containers
    'columns': 50,
    'rows': 5000,            # rows a table draws
    'items': 500,            # static list items
    'actionsPerEvent': 8,
    'styleRules': 16,
    'text': 2000,
    'name': 64,
    'documentBytes': 200000,
}

THEMES = ['terminal', 'dark', 'light', 'attas', 'fugle']
# Theme tokens a color may name; the host maps each to its CSS variable in the chosen theme.
COLORS = ['background', 'surface', 'raised', 'hover', 'line', 'lineSoft', 'text', 'muted', 'dim', 'accent',
          'accentBackground', 'positive', 'negative']
FORMAT_KINDS = ['datetime', 'date', 'time', 'amount', 'percent', 'ratio', 'count', 'number', 'text']
ALIGNMENTS = ['topLeft', 'topCenter', 'topRight', 'middleLeft', 'middleCenter', 'middleRight', 'bottomLeft',
              'bottomCenter', 'bottomRight']
VALUE_TYPES = ['string', 'number', 'integer', 'boolean', 'date', 'dateTime']
BINDINGS = ['$param', '$result', '$control', '$event', '$link', '$panel', '$panels', '$opened', '$agents']
# The state another control or a page value may read from a control (`$control`, `dataBindings`).
STATE = {
    'table': ['rows', 'selectedRows', 'currentRow', 'currentCell', 'sortedColumn', 'sortOrder'],
    'textBox': ['text'], 'numericUpDown': ['value'], 'comboBox': ['selectedValue', 'selectedIndex', 'text'],
    'listBox': ['selectedValues'], 'checkedListBox': ['selectedValues', 'checkedValues'],
    'checkBox': ['checked', 'checkState'], 'radioButton': ['checked', 'value'], 'dateTimePicker': ['value'],
    'trackBar': ['value'], 'tabControl': ['selectedIndex'],
}


def _s(max_length=LIMITS['text'], **kw):
    return {'type': 'string', 'maxLength': max_length, **kw}


def _enum(*values):
    return {'enum': list(values)}


BOOL = {'type': 'boolean'}
NUMBER = {'type': 'number', 'minimum': -1e15, 'maximum': 1e15}
PIXELS = {'type': 'integer', 'minimum': 0, 'maximum': 4000}
COLOR = {'enum': COLORS}
SPACING = _enum('none', 'tight', 'normal')
FONT = {'type': 'object', 'properties': {'family': _enum('sans', 'mono'), 'size': _enum('small', 'normal', 'large'),
                                         'bold': BOOL, 'italic': BOOL}, 'additionalProperties': False}
FORMAT = {'type': 'object', 'properties': {'kind': {'enum': FORMAT_KINDS},
                                           'decimals': {'type': 'integer', 'minimum': 0, 'maximum': 8},
                                           'signed': BOOL, 'dateTime': _enum('compact', 'full')},
          'required': ['kind'], 'additionalProperties': False}
# DataGridViewCellStyle.
CELL_STYLE = {'type': 'object', 'properties': {
    'backColor': COLOR, 'foreColor': COLOR, 'selectionBackColor': COLOR, 'selectionForeColor': COLOR, 'font': FONT,
    'format': FORMAT, 'alignment': {'enum': ALIGNMENTS}, 'wrapMode': BOOL, 'nullValue': _s(80), 'padding': SPACING,
}, 'additionalProperties': False}
OPS = ['=', '!=', '<', '<=', '>', '>=', 'null', 'notNull']
# In place of DataGridView.CellFormatting handler code: a cell whose row meets the condition takes the style.
STYLE_RULE = {'type': 'object', 'properties': {
    'when': {'type': 'object', 'properties': {'field': _s(100), 'op': {'enum': OPS}, 'value': {}},
             'required': ['field', 'op'], 'additionalProperties': False},
    'columns': {'type': 'array', 'maxItems': LIMITS['columns'], 'items': _s(LIMITS['name'])},
    'style': CELL_STYLE,
}, 'required': ['when', 'style'], 'additionalProperties': False}
# Declarative checks in place of Validating handler code. No patterns: a document never supplies a regular expression.
VALIDATION = {'type': 'object', 'properties': {
    'required': BOOL, 'minimum': NUMBER, 'maximum': NUMBER,
    'minLength': {'type': 'integer', 'minimum': 0, 'maximum': LIMITS['text']},
    'maxLength': {'type': 'integer', 'minimum': 0, 'maximum': LIMITS['text']},
    'oneOf': {'type': 'array', 'maxItems': LIMITS['items']}, 'message': _s(200),
}, 'additionalProperties': False}
ITEMS = {'type': 'array', 'maxItems': LIMITS['items']}

# Control: the properties and events every control has.
COMMON_PROPERTIES = {
    'type': {'type': 'string'}, 'name': _s(LIMITS['name']), 'text': _s(), 'enabled': BOOL, 'visible': BOOL,
    'toolTipText': _s(500), 'tabIndex': {'type': 'integer', 'minimum': 0, 'maximum': 999}, 'backColor': COLOR,
    'foreColor': COLOR, 'font': FONT, 'padding': SPACING, 'margin': SPACING, 'theme': {'enum': THEMES},
    'validation': VALIDATION,
}
COMMON_EVENTS = ['click', 'doubleClick', 'enter', 'leave', 'keyDown', 'textChanged', 'validating', 'validated']

# DataGridViewColumn.
COLUMN_PROPERTIES = {
    'name': _s(LIMITS['name']), 'headerText': _s(200), 'dataPropertyName': _s(100),
    'columnType': _enum('textBox', 'checkBox', 'comboBox', 'button', 'link'),
    'width': PIXELS, 'minimumWidth': PIXELS, 'fillWeight': {'type': 'number', 'minimum': 1, 'maximum': 1000},
    'autoSizeMode': _enum('notSet', 'none', 'allCells', 'displayedCells', 'columnHeader', 'fill'),
    'resizable': BOOL, 'visible': BOOL, 'readOnly': BOOL, 'frozen': BOOL,
    'displayIndex': {'type': 'integer', 'minimum': 0, 'maximum': LIMITS['columns']},
    'toolTipText': _s(500), 'defaultCellStyle': CELL_STYLE,
    'sortMode': _enum('automatic', 'programmatic', 'notSortable'), 'valueType': {'enum': VALUE_TYPES},
    'items': ITEMS, 'dataSource': {}, 'displayMember': _s(100), 'valueMember': _s(100),
    'text': _s(200), 'useColumnTextForButtonValue': BOOL, 'validation': VALIDATION,
}

LIST_SOURCE = {'items': ITEMS, 'dataSource': {}, 'displayMember': _s(100), 'valueMember': _s(100)}

KINDS = {
    # DataGridView.
    'table': {'properties': {
        'dataSource': {}, 'autoGenerateColumns': BOOL,
        'columns': {'type': 'array', 'maxItems': LIMITS['columns'], 'items': {'$ref': '#/$defs/column'}},
        'readOnly': BOOL,
        'selectionMode': _enum('cellSelect', 'fullRowSelect', 'fullColumnSelect', 'rowHeaderSelect',
                               'columnHeaderSelect'),
        'multiSelect': BOOL, 'editMode': _enum('editOnEnter', 'editOnKeystroke', 'editProgrammatically'),
        'currentCell': {}, 'allowUserToAddRows': BOOL, 'allowUserToDeleteRows': BOOL,
        'allowUserToOrderColumns': BOOL, 'allowUserToResizeColumns': BOOL,
        'autoSizeColumnsMode': _enum('none', 'allCells', 'displayedCells', 'columnHeader', 'fill'),
        'columnHeadersVisible': BOOL, 'rowHeadersVisible': BOOL,
        'cellBorderStyle': _enum('single', 'none', 'singleHorizontal', 'singleVertical'), 'gridColor': COLOR,
        'defaultCellStyle': CELL_STYLE, 'alternatingRowsDefaultCellStyle': CELL_STYLE,
        'columnHeadersDefaultCellStyle': CELL_STYLE, 'rowsDefaultCellStyle': CELL_STYLE,
        'sortedColumn': _s(LIMITS['name']), 'sortOrder': _enum('none', 'ascending', 'descending'),
        'clipboardCopyMode': _enum('disable', 'enableWithoutHeaderText', 'enableAlwaysIncludeHeaderText'),
        'showCellToolTips': BOOL,
        'cellStyleRules': {'type': 'array', 'maxItems': LIMITS['styleRules'], 'items': STYLE_RULE},
        'rowLimit': {'type': 'integer', 'minimum': 1, 'maximum': LIMITS['rows']},
    }, 'events': ['cellClick', 'cellDoubleClick', 'cellContentClick', 'cellValueChanged', 'cellValidating',
                  'cellEndEdit', 'rowEnter', 'rowLeave', 'userAddedRow', 'userDeletingRow', 'userDeletedRow',
                  'columnHeaderMouseClick', 'sorted', 'selectionChanged', 'currentCellChanged',
                  'dataBindingComplete', 'dataError']},
    'label': {'properties': {'textAlign': {'enum': ALIGNMENTS}, 'autoEllipsis': BOOL}, 'events': []},
    'linkLabel': {'properties': {'link': _s(4096), 'linkVisited': BOOL}, 'events': ['linkClicked']},
    'button': {'properties': {}, 'events': []},
    'textBox': {'properties': {'placeholderText': _s(200), 'maxLength': {'type': 'integer', 'minimum': 0,
                                                                          'maximum': 100000},
                               'multiline': BOOL, 'readOnly': BOOL, 'textAlign': _enum('left', 'center', 'right'),
                               'wordWrap': BOOL, 'acceptsReturn': BOOL}, 'events': []},
    'numericUpDown': {'properties': {'value': {}, 'minimum': NUMBER, 'maximum': NUMBER, 'increment': NUMBER,
                                     'decimalPlaces': {'type': 'integer', 'minimum': 0, 'maximum': 8},
                                     'thousandsSeparator': BOOL}, 'events': ['valueChanged']},
    'comboBox': {'properties': {**LIST_SOURCE, 'selectedValue': {}, 'selectedIndex': {},
                                'dropDownStyle': _enum('dropDown', 'dropDownList'),
                                'autoCompleteMode': _enum('none', 'suggest', 'append', 'suggestAppend'),
                                'maxDropDownItems': {'type': 'integer', 'minimum': 1, 'maximum': 100},
                                'sorted': BOOL},
                 'events': ['selectedIndexChanged', 'selectedValueChanged', 'selectionChangeCommitted', 'dropDown',
                            'dropDownClosed', 'textUpdate']},
    'listBox': {'properties': {**LIST_SOURCE, 'selectionMode': _enum('one', 'multiSimple', 'multiExtended'),
                               'selectedValues': {}}, 'events': ['selectedIndexChanged']},
    'checkedListBox': {'properties': {**LIST_SOURCE, 'selectionMode': _enum('one', 'multiSimple', 'multiExtended'),
                                      'selectedValues': {}, 'checkedValues': {}, 'checkOnClick': BOOL},
                       'events': ['selectedIndexChanged', 'itemCheck']},
    'checkBox': {'properties': {'checked': {}, 'checkState': {}, 'threeState': BOOL},
                 'events': ['checkedChanged', 'checkStateChanged']},
    'radioButton': {'properties': {'checked': {}, 'value': {}, 'groupName': _s(LIMITS['name'])},
                    'events': ['checkedChanged']},
    'dateTimePicker': {'properties': {'value': {}, 'minDate': {}, 'maxDate': {},
                                      'format': _enum('long', 'short', 'time', 'custom'),
                                      'customFormat': {'type': 'object'}, 'showCheckBox': BOOL},
                       'events': ['valueChanged']},
    'trackBar': {'properties': {'value': {}, 'minimum': NUMBER, 'maximum': NUMBER, 'smallChange': NUMBER,
                                'largeChange': NUMBER, 'tickFrequency': NUMBER,
                                'orientation': _enum('horizontal', 'vertical')}, 'events': ['valueChanged', 'scroll']},
    'progressBar': {'properties': {'value': {}, 'minimum': NUMBER, 'maximum': NUMBER,
                                   'style': _enum('blocks', 'continuous', 'marquee')}, 'events': []},
    'groupBox': {'properties': {'borderStyle': _enum('none', 'fixedSingle'), 'controls': {}}, 'events': [],
                 'container': True},
    'panel': {'properties': {'borderStyle': _enum('none', 'fixedSingle'), 'controls': {}}, 'events': [],
              'container': True},
    'tabControl': {'properties': {'tabPages': {}, 'selectedIndex': {}}, 'events': ['selectedIndexChanged'],
                   'container': True},
}
# The kinds a host renders as a whole surface; the others appear inside a container.
SURFACE_KINDS = list(KINDS)


def renderer_id(kind):
    """The renderer a surface names for a control: capability ids are lower case, so `linkLabel` is
    `phemacast:control.link-label`; the document's `type` keeps the Windows Forms name."""
    return PREFIX + re.sub(r'(?<!^)([A-Z])', lambda m: '-' + m.group(1).lower(), kind)


RENDERERS = {kind: renderer_id(kind) for kind in KINDS}

# Event handlers: the declarative actions. Each names its fields; a field may bind a value.
ACTIONS = {
    'setParameter': {'required': ['name', 'value'], 'optional': []},
    'runReference': {'required': ['reference'], 'optional': ['parameters']},
    'refresh': {'required': ['reference'], 'optional': []},
    'setProperty': {'required': ['control', 'property', 'value'], 'optional': []},
    'clearSelection': {'required': ['control'], 'optional': []},
    'openLink': {'required': ['url'], 'optional': []},
    'showMessage': {'required': ['text'], 'optional': ['level']},
    # Between panels on the same Terminal (phemacast/core/ports.py).
    'publish': {'required': ['port', 'value'], 'optional': []},
    'openPhema': {'required': ['phema'], 'optional': ['parameters', 'where', 'link', 'as']},
    'setPanelParameters': {'required': ['panel', 'values'], 'optional': []},
}
WHERE = ['newPanel', 'replaceThis', 'newWorkspace']
# Phemas on one Terminal working together (phemacast/core/ports.py): the value types a port carries, what a page value
# shares, and the viewer's link groups.
PORT_TYPES = ('instrument', 'instruments', 'date', 'dateRange', 'interval', 'text', 'number', 'boolean', 'agent', 'rows')
SHARES = ('readWrite', 'read', 'none')
LINK_GROUPS = ('red', 'amber', 'green', 'teal', 'blue', 'purple')
LEVELS = ['info', 'success', 'warning', 'error']

NAME = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')
PARAMETER = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,63}$')
POINTER = re.compile(r'^(/[^/]{1,100}){0,8}$')
PARAM_POINTER = re.compile(r'^/[A-Za-z][A-Za-z0-9_]{0,63}(/[^/]{1,100}){0,7}$')
REFERENCE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')
LINK = re.compile(r'^https?://[^/@\s]+(?:/\S*)?$')
SECRET = re.compile(r'password|secret|token|api.?key|credential|cookie|authorization', re.IGNORECASE)

VOCABULARY = {
    'version': VERSION, 'limits': LIMITS, 'themes': THEMES, 'colors': COLORS, 'formatKinds': FORMAT_KINDS,
    'alignments': ALIGNMENTS, 'bindings': BINDINGS, 'state': STATE, 'ops': OPS,
    'common': {'properties': sorted(COMMON_PROPERTIES), 'events': COMMON_EVENTS},
    'column': sorted(COLUMN_PROPERTIES),
    'kinds': {kind: {'properties': sorted(spec['properties']), 'events': spec['events'],
                     'container': spec.get('container', False)} for kind, spec in KINDS.items()},
    'actions': ACTIONS, 'where': WHERE, 'levels': LEVELS, 'renderers': RENDERERS,
    'ports': {'types': list(PORT_TYPES), 'share': list(SHARES), 'groups': list(LINK_GROUPS), 'maxValueBytes': 32 * 1024,
              'extension': 'phemacast:ports'},
}


class ControlError(ValueError):
    pass


def _fail(where, message):
    raise ControlError(f'{where}: {message}' if where else message)


def binding_kind(value):
    """The binding a value is (`$param` …), or None for a plain value."""
    if isinstance(value, dict) and len(value) == 1:
        key = next(iter(value))
        if isinstance(key, str) and key.startswith('$'):
            return key
    return None


def check_binding(value, where, *, in_action=False):
    kind = binding_kind(value)
    if kind not in BINDINGS:
        _fail(where, f'unknown binding {kind}.')
    target = value[kind]
    if kind == '$param':
        if not isinstance(target, str) or not PARAM_POINTER.fullmatch(target):
            _fail(where, '$param names a page value, as "/name".')
    elif kind == '$result':
        if isinstance(target, str):
            target = {'reference': target}
        if (not isinstance(target, dict) or set(target) - {'reference', 'path'}
                or not isinstance(target.get('reference'), str) or not REFERENCE.fullmatch(target['reference'])
                or not isinstance(target.get('path', ''), str) or not POINTER.fullmatch(target.get('path', ''))):
            _fail(where, '$result names a reference and an optional path, as {"reference": "quotes", "path": "/rows"}.')
    elif kind == '$control':
        if (not isinstance(target, dict) or set(target) != {'name', 'property'}
                or not isinstance(target['name'], str) or not NAME.fullmatch(target['name'])
                or not isinstance(target['property'], str)
                or target['property'] not in {state for states in STATE.values() for state in states}):
            _fail(where, '$control names a control and one of its states, as {"name": "grid", "property": "currentRow"}.')
    elif kind == '$event':
        if not in_action:
            _fail(where, '$event is available only inside an event\'s actions.')
        if not isinstance(target, str) or not POINTER.fullmatch(target):
            _fail(where, '$event is a path into the event, as "/row/symbol".')
    elif kind == '$link':
        if not isinstance(target, str) or not NAME.fullmatch(target):
            _fail(where, '$link names one of this Phema\'s input ports.')
    elif kind == '$panel':
        if (not isinstance(target, dict) or set(target) != {'panel', 'param'}
                or not isinstance(target['param'], str) or not PARAM_POINTER.fullmatch(target['param'])):
            _fail(where, '$panel names a panel and one of its page values.')
        if binding_kind(target['panel']):
            check_binding(target['panel'], where + '.panel', in_action=in_action)
        elif not isinstance(target['panel'], str) or not 0 < len(target['panel']) <= 200:
            _fail(where, '$panel names a panel handle.')
    elif kind == '$panels':
        if not isinstance(target, dict) or set(target) - {'phema', 'workspace', 'group'} or any(
                not isinstance(v, str) or not 0 < len(v) <= 200 for v in target.values()):
            _fail(where, '$panels may filter by phema, workspace and group.')
    elif kind == '$opened':
        if not isinstance(target, str) or not NAME.fullmatch(target):
            _fail(where, '$opened names a panel this Phema opened with openPhema … as.')
    elif kind == '$agents':
        if (not isinstance(target, dict) or set(target) != {'pulse'} or not isinstance(target['pulse'], str)
                or not REFERENCE.fullmatch(target['pulse'])):
            _fail(where, '$agents names a pulse, as {"pulse": "comment_summary_prompt"}.')


def _plain(value, where, depth=0, *, in_action=False):
    """A literal or bound value: data only, bounded, with no credentials."""
    if depth > 12:
        _fail(where, 'the value is too deeply nested.')
    if binding_kind(value):
        check_binding(value, where, in_action=in_action)
        return
    if isinstance(value, dict):
        if len(value) > 200:
            _fail(where, 'an object holds at most 200 fields.')
        for key, child in value.items():
            if not isinstance(key, str) or key.startswith('$') or key in ('__proto__', 'constructor', 'prototype'):
                _fail(where, f'{key!r} is not a field name.')
            if SECRET.search(key):
                _fail(where, 'credentials belong to the host, not a Phema.')
            _plain(child, f'{where}.{key}', depth + 1, in_action=in_action)
    elif isinstance(value, list):
        if len(value) > LIMITS['rows']:
            _fail(where, f'a list holds at most {LIMITS["rows"]} entries.')
        for i, child in enumerate(value):
            _plain(child, f'{where}[{i}]', depth + 1, in_action=in_action)
    elif isinstance(value, str):
        if len(value) > LIMITS['text'] * 10:
            _fail(where, 'the text is too long.')
    elif value is not None and not isinstance(value, (bool, int, float)):
        _fail(where, 'only JSON values are allowed.')


def _check_schema(value, schema, where):
    """A property's value against its small schema (`enum`, `type`, bounds, nested objects)."""
    if binding_kind(value):
        check_binding(value, where)
        return
    if not schema:
        _plain(value, where)
        return
    if '$ref' in schema:
        return  # columns are checked by `_column`
    if 'enum' in schema:
        if value not in schema['enum']:
            _fail(where, 'use one of ' + ', '.join(map(str, schema['enum'])) + '.')
        return
    kind = schema.get('type')
    if kind == 'boolean' and not isinstance(value, bool):
        _fail(where, 'use true or false.')
    if kind in ('number', 'integer'):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind == 'integer' and not isinstance(value, int)):
            _fail(where, 'use a whole number.' if kind == 'integer' else 'use a number.')
        if value < schema.get('minimum', float('-inf')) or value > schema.get('maximum', float('inf')):
            _fail(where, f'use a value from {schema.get("minimum")} to {schema.get("maximum")}.')
    if kind == 'string':
        if not isinstance(value, str) or len(value) > schema.get('maxLength', LIMITS['text']):
            _fail(where, f'use text of at most {schema.get("maxLength", LIMITS["text"])} characters.')
    if kind == 'array':
        if not isinstance(value, list) or len(value) > schema.get('maxItems', LIMITS['items']):
            _fail(where, f'use a list of at most {schema.get("maxItems", LIMITS["items"])} entries.')
        for i, item in enumerate(value):
            _check_schema(item, schema.get('items') or {}, f'{where}[{i}]')
    if kind == 'object':
        if not isinstance(value, dict):
            _fail(where, 'use an object.')
        properties = schema.get('properties')
        if properties is None:
            _plain(value, where)
            return
        if schema.get('additionalProperties') is False:
            extra = set(value) - set(properties)
            if extra:
                _fail(where, 'unknown ' + ', '.join(sorted(extra)) + '.')
        for key in schema.get('required', []):
            if key not in value:
                _fail(where, f'{key} is required.')
        for key, child in value.items():
            _check_schema(child, properties.get(key, {}), f'{where}.{key}')


def _list_source(doc, where):
    items, source = doc.get('items'), doc.get('dataSource')
    if items is not None and source is not None:
        _fail(where, 'use items or a dataSource, not both.')
    if source is not None and not binding_kind(source) and not isinstance(source, list):
        _fail(where + '.dataSource', 'bind a dataSource, or give a list.')


def _column(column, where, names):
    if not isinstance(column, dict):
        _fail(where, 'a column is an object.')
    extra = set(column) - set(COLUMN_PROPERTIES)
    if extra:
        _fail(where, 'unknown ' + ', '.join(sorted(extra)) + '.')
    name = column.get('name') or column.get('dataPropertyName')
    if not isinstance(name, str) or not name:
        _fail(where, 'a column has a name or a dataPropertyName.')
    if name in names:
        _fail(where, f'two columns are named {name}.')
    names.add(name)
    for key, value in column.items():
        _check_schema(value, COLUMN_PROPERTIES[key], f'{where}.{key}')
    kind = column.get('columnType', 'textBox')
    if kind != 'comboBox' and any(k in column for k in ('items', 'dataSource', 'displayMember', 'valueMember')):
        _fail(where, 'only a comboBox column has items.')
    if kind == 'comboBox':
        _list_source(column, where)
    if kind != 'button' and ('useColumnTextForButtonValue' in column or 'text' in column):
        _fail(where, 'only a button column has its own text.')


def _actions(handlers, where, kind):
    if not isinstance(handlers, list) or not 1 <= len(handlers) <= LIMITS['actionsPerEvent']:
        _fail(where, f'an event runs 1 to {LIMITS["actionsPerEvent"]} actions.')
    for i, action in enumerate(handlers):
        at = f'{where}[{i}]'
        if not isinstance(action, dict) or action.get('action') not in ACTIONS:
            _fail(at, 'use one of the actions ' + ', '.join(ACTIONS) + '.')
        spec = ACTIONS[action['action']]
        fields = set(action) - {'action'}
        missing = set(spec['required']) - fields
        extra = fields - set(spec['required']) - set(spec['optional'])
        if missing:
            _fail(at, 'missing ' + ', '.join(sorted(missing)) + '.')
        if extra:
            _fail(at, 'unknown ' + ', '.join(sorted(extra)) + '.')
        for key, value in action.items():
            if key != 'action':
                _plain(value, f'{at}.{key}', in_action=True)
        name = action['action']
        if name == 'setParameter' and (not isinstance(action['name'], str) or not PARAMETER.fullmatch(action['name'])):
            _fail(at, 'setParameter names a page value.')
        if name in ('runReference', 'refresh') and (not isinstance(action['reference'], str)
                                                    or not REFERENCE.fullmatch(action['reference'])):
            _fail(at, 'name the reference to run.')
        if name == 'runReference' and 'parameters' in action and (
                not isinstance(action['parameters'], dict)
                or any(not PARAMETER.fullmatch(k) for k in action['parameters'])):
            _fail(at, 'runReference sets named page values before it runs.')
        if name in ('setProperty', 'clearSelection') and (not isinstance(action['control'], str)
                                                          or not NAME.fullmatch(action['control'])):
            _fail(at, 'name the control.')
        if name == 'setProperty' and action['property'] not in (
                set(COMMON_PROPERTIES) | {p for spec in KINDS.values() for p in spec['properties']}) - {'type', 'name'}:
            _fail(at, 'setProperty names one of the control\'s properties.')
        if name == 'openLink' and not binding_kind(action['url']) and (
                not isinstance(action['url'], str) or not LINK.fullmatch(action['url'])):
            _fail(at, 'a link is an http or https address.')
        if name == 'showMessage' and action.get('level', 'info') not in LEVELS:
            _fail(at, 'level is one of ' + ', '.join(LEVELS) + '.')
        if name == 'publish' and (not isinstance(action['port'], str) or not NAME.fullmatch(action['port'])):
            _fail(at, 'publish names one of this Phema\'s output ports.')
        if name == 'openPhema':
            if not isinstance(action['phema'], str) or not 0 < len(action['phema']) <= 200:
                _fail(at, 'openPhema names a catalog or library Phema.')
            if action.get('where', 'newPanel') not in WHERE:
                _fail(at, 'where is one of ' + ', '.join(WHERE) + '.')
            if action.get('link', 'none') not in ('sameGroup', 'none'):
                _fail(at, 'link is sameGroup or none.')
            if 'as' in action and (not isinstance(action['as'], str) or not NAME.fullmatch(action['as'])):
                _fail(at, 'as names the opened panel.')
            if 'parameters' in action and (not isinstance(action['parameters'], dict)
                                           or any(not PARAMETER.fullmatch(k) for k in action['parameters'])):
                _fail(at, 'openPhema passes named page values.')
        if name == 'setPanelParameters' and (not isinstance(action['values'], dict) or not action['values']
                                             or any(not PARAMETER.fullmatch(k) for k in action['values'])):
            _fail(at, 'setPanelParameters passes named page values.')


def _control(doc, where, *, kind=None, depth=0, counter, names):
    if not isinstance(doc, dict):
        _fail(where, 'a control is an object.')
    counter[0] += 1
    if counter[0] > LIMITS['controls']:
        _fail(where, f'a surface holds at most {LIMITS["controls"]} controls.')
    declared = doc.get('type')
    if kind and declared not in (None, kind):
        _fail(where, f'this surface draws a {kind}, not a {declared}.')
    kind = kind or declared
    if kind not in KINDS:
        _fail(where, 'type is one of ' + ', '.join(KINDS) + '.')
    spec = KINDS[kind]
    allowed = set(COMMON_PROPERTIES) | set(spec['properties']) | {'events', 'dataBindings'}
    extra = set(doc) - allowed
    if extra:
        _fail(where, f'a {kind} has no ' + ', '.join(sorted(extra)) + '.')
    name = doc.get('name')
    if name is not None:
        if not isinstance(name, str) or not NAME.fullmatch(name):
            _fail(where, 'a name is letters, digits, _ and -, starting with a letter.')
        if name in names:
            _fail(where, f'two controls are named {name}.')
        names.add(name)
    where = f'{where}({name or kind})'
    properties = {**COMMON_PROPERTIES, **spec['properties']}
    for key, value in doc.items():
        if key in ('events', 'dataBindings', 'type', 'columns', 'controls', 'tabPages'):
            continue
        _check_schema(value, properties[key], f'{where}.{key}')
    if kind == 'table':
        columns = doc.get('columns', [])
        if binding_kind(columns) or not isinstance(columns, list) or len(columns) > LIMITS['columns']:
            _fail(where + '.columns', f'list at most {LIMITS["columns"]} columns.')
        seen = set()
        for i, column in enumerate(columns):
            _column(column, f'{where}.columns[{i}]', seen)
        for i, rule in enumerate(doc.get('cellStyleRules', [])):
            for column in rule.get('columns', []):
                if seen and column not in seen:
                    _fail(f'{where}.cellStyleRules[{i}]', f'there is no column {column}.')
        sorted_column = doc.get('sortedColumn')
        if isinstance(sorted_column, str) and seen and sorted_column not in seen:
            _fail(where + '.sortedColumn', f'there is no column {sorted_column}.')
    if kind in ('comboBox', 'listBox', 'checkedListBox'):
        _list_source(doc, where)
    if kind == 'linkLabel' and isinstance(doc.get('link'), str) and not LINK.fullmatch(doc['link']):
        _fail(where + '.link', 'a link is an http or https address.')
    if spec.get('container'):
        if depth >= LIMITS['depth']:
            _fail(where, f'containers nest at most {LIMITS["depth"]} deep.')
        if kind == 'tabControl':
            pages = doc.get('tabPages', [])
            if not isinstance(pages, list) or not 1 <= len(pages) <= 12:
                _fail(where + '.tabPages', 'a tab control has 1 to 12 pages.')
            for i, page in enumerate(pages):
                if not isinstance(page, dict) or set(page) - {'text', 'controls'} or not isinstance(page.get('text'), str):
                    _fail(f'{where}.tabPages[{i}]', 'a tab page has a text and its controls.')
                for j, child in enumerate(page.get('controls', [])):
                    _control(child, f'{where}.tabPages[{i}].controls[{j}]', depth=depth + 1, counter=counter, names=names)
        else:
            children = doc.get('controls', [])
            if not isinstance(children, list):
                _fail(where + '.controls', 'list the controls inside.')
            for i, child in enumerate(children):
                _control(child, f'{where}.controls[{i}]', depth=depth + 1, counter=counter, names=names)
    elif 'controls' in doc or 'tabPages' in doc:
        _fail(where, f'a {kind} holds no other controls.')
    events = doc.get('events', {})
    if not isinstance(events, dict):
        _fail(where + '.events', 'events map an event name to its actions.')
    for event, handlers in events.items():
        if event not in COMMON_EVENTS and event not in spec['events']:
            _fail(f'{where}.events', f'a {kind} has no {event} event.')
        _actions(handlers, f'{where}.events.{event}', kind)
    bindings = doc.get('dataBindings', {})
    if not isinstance(bindings, dict):
        _fail(where + '.dataBindings', 'dataBindings map a state to the page value it is saved to.')
    for state, target in bindings.items():
        if state not in STATE.get(kind, []):
            _fail(f'{where}.dataBindings', f'a {kind} has no {state} to bind.')
        if binding_kind(target) != '$param' or not isinstance(target['$param'], str) \
                or not PARAMETER.fullmatch(target['$param'][1:]) or not target['$param'].startswith('/'):
            _fail(f'{where}.dataBindings.{state}', 'a state is saved to a page value, as {"$param": "/name"}.')
    return kind


def validate_control(doc, kind=None):
    """A control document (a surface's `media` for `phemacast:control.<kind>`), checked; ControlError says what is
    wrong and where. Returns a copy."""
    if kind is not None and kind not in KINDS:
        _fail('', f'there is no {kind} control.')
    try:
        size = len(json.dumps(doc, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ControlError('A control is JSON data.') from exc
    if size > LIMITS['documentBytes']:
        _fail('', f'a control document is at most {LIMITS["documentBytes"]} bytes.')
    _control(doc, 'control', kind=kind, counter=[0], names=set())
    return copy.deepcopy(doc)


def kind_of(renderer):
    """`linkLabel` for `phemacast:control.link-label`; None for any other renderer."""
    return next((kind for kind, rid in RENDERERS.items() if rid == renderer), None)


def json_schema(kind):
    """The contract a host publishes for `phemacast:control.<kind>`: the shape, without the cross-field rules
    `validate_control` adds."""
    spec = KINDS[kind]
    properties = {**COMMON_PROPERTIES, **spec['properties']}
    # A property may be bound ({"$param": …}, {"$result": …} …): one key starting with $, checked by validate_control.
    binding = {'type': 'object', 'minProperties': 1, 'maxProperties': 1, 'propertyNames': {'pattern': '^[$][a-z]+$'}}
    properties = {key: ({'anyOf': [copy.deepcopy(value), binding]} if value and '$ref' not in value else copy.deepcopy(value))
                  for key, value in properties.items()}
    properties['type'] = {'const': kind}
    properties['events'] = {'type': 'object', 'maxProperties': 32,
                            'propertyNames': {'enum': COMMON_EVENTS + spec['events']},
                            'additionalProperties': {'type': 'array', 'minItems': 1,
                                                     'maxItems': LIMITS['actionsPerEvent'],
                                                     'items': {'type': 'object', 'required': ['action'],
                                                               'properties': {'action': {'enum': list(ACTIONS)}}}}}
    properties['dataBindings'] = {'type': 'object', 'propertyNames': {'enum': STATE.get(kind, []) or ['-']}}
    schema = {'type': 'object', 'properties': properties, 'additionalProperties': False}
    if kind == 'table':
        schema['$defs'] = {'column': {'type': 'object', 'properties': copy.deepcopy(COLUMN_PROPERTIES),
                                      'additionalProperties': False}}
    return schema


def schema_document():
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema', 'title': 'Phemacast controls',
            'version': VERSION, 'vocabulary': VOCABULARY,
            'controls': {RENDERERS[kind]: json_schema(kind) for kind in KINDS}}


ROOT = Path(__file__).resolve().parents[1]
GENERATED = {
    ROOT / 'schemas/phema/controls.json': lambda: json.dumps(schema_document(), indent=1, sort_keys=True) + '\n',
    ROOT / 'web/control-vocabulary.js': lambda: (
        '// Generated from phemacast/core/controls.py (python3 -m phemacast.core.controls --write). Do not edit.\n'
        'export const VOCABULARY=' + json.dumps(VOCABULARY, sort_keys=True, separators=(',', ':')) + ';\n'),
}


def write_generated():
    for path, render in GENERATED.items():
        path.write_text(render())


if __name__ == '__main__':
    import sys
    if '--write' in sys.argv:
        write_generated()
    else:
        stale = [str(path) for path, render in GENERATED.items() if not path.exists() or path.read_text() != render()]
        print('\n'.join(stale) or 'up to date')
        sys.exit(1 if stale else 0)
