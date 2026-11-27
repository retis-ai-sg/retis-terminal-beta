"""SplitContainer, after Windows Forms' SplitContainer: two panels of a page side by side, with a border the person
drags and a panel they can hide to a strip.

A Phema declares it in its layout document's extension `phemacast:split-containers`, so the Phema decides which
panels share a border, where it starts and whether it moves. A host that does not know the extension shows the page's
grid as it is. The host keeps where the person left the border as that window's own state; the Phema only gives the
starting point. Names follow SplitContainer, written camelCase: `orientation`, `splitterDistance` (here a percentage
of the two panels' width, not pixels, since a Phema does not know the window's size), `panel1MinSize`,
`panel2MinSize`, `isSplitterFixed`, `panel1Collapsed` and `panel2Collapsed`. Only `vertical` (panels side by side,
WinForms' default) exists so far.
"""
from jsonschema import Draft202012Validator

EXTENSION = 'phemacast:split-containers'
MAX_SPLITS = 4
EPSILON = 1e-7
SURFACE_ID = {'type': 'string', 'pattern': '^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$'}
PIXELS = {'type': 'integer', 'minimum': 0, 'maximum': 2000}
SCHEMA = {
    'type': 'array', 'maxItems': MAX_SPLITS,
    'items': {'type': 'object', 'additionalProperties': False, 'required': ['name', 'panel1', 'panel2'], 'properties': {
        'name': {'type': 'string', 'pattern': '^[A-Za-z][A-Za-z0-9_-]{0,63}$'},
        'orientation': {'enum': ['vertical']},
        'panel1': SURFACE_ID, 'panel2': SURFACE_ID,
        'splitterDistance': {'type': 'number', 'minimum': 5, 'maximum': 95},
        'panel1MinSize': PIXELS, 'panel2MinSize': PIXELS,
        'isSplitterFixed': {'type': 'boolean'},
        'panel1Collapsed': {'type': 'boolean'}, 'panel2Collapsed': {'type': 'boolean'},
    }},
}


def whole(value):
    return isinstance(value, (int, float)) and abs(value - round(value)) < EPSILON


def validate_split_containers(document):
    """Check a layout document's split containers against its own grid; a document without any passes."""
    splits = (document.get('extensions') or {}).get(EXTENSION)
    if splits is None:
        return []
    errors = list(Draft202012Validator(SCHEMA).iter_errors(splits))
    if errors:
        raise ValueError('Invalid split container: ' + errors[0].message)
    grid = document['design']['layout']
    if grid.get('columns') != 12 or grid.get('snapToGrid') is False:
        raise ValueError('A split container needs the 12-column grid with grid snapping.')
    surfaces = {node['id']: node for node in grid['children']}
    names, used, spans = set(), set(), []
    for split in splits:
        if split['name'] in names:
            raise ValueError('Split container names must be unique.')
        names.add(split['name'])
        one, two = surfaces.get(split['panel1']), surfaces.get(split['panel2'])
        if not one or not two or one is two:
            raise ValueError('A split container joins two different surfaces of the page.')
        if one.get('tabId') or two.get('tabId'):
            raise ValueError('A split container joins surfaces outside the tabbed view.')
        if {one['id'], two['id']} & used:
            raise ValueError('A surface belongs to one split container at most.')
        used |= {one['id'], two['id']}
        a, b = one['position'], two['position']
        if not all(whole(v) for v in (*a.values(), *b.values())):
            raise ValueError('A split container joins surfaces on whole grid cells.')
        if a['row'] != b['row'] or a['rowSpan'] != b['rowSpan'] or round(a['column'] + a['columnSpan']) != round(b['column']):
            raise ValueError('A vertical split container joins two surfaces side by side in the same rows, panel1 on the left.')
        start, end = round(a['column']), round(b['column'] + b['columnSpan']) - 1
        if any(start <= other_end and other_start <= end for other_start, other_end in spans):
            raise ValueError('Split containers move columns, so two of them cannot share a column.')
        spans.append((start, end))
        if split.get('panel1Collapsed') and split.get('panel2Collapsed'):
            raise ValueError('A split container shows at least one of its panels.')
    return splits
