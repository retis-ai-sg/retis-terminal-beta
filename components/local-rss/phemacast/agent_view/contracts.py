"""One publisher-owned interaction contract; no application semantics.

Operation resources reuse Prompits' registry grammar. The view manifest adds
presentation, closed bindings and disclosure policy; declarations are not grants.
"""
from copy import deepcopy
import hashlib
import ipaddress
import re
from urllib.parse import urlsplit
from jsonschema import Draft202012Validator
from prompits.core.capabilities import canonical, digest, validate_requirement, validate_definition
from prompits.core.operation_contracts import validate_operation
from prompits.core.resource_registry import validate_ref

CAPABILITY = {'id': 'phemacast:agent-view', 'version': '1.0.0',
    'features': ['pinned-release', 'typed-operations', 'scoped-grants', 'dependencies',
        'revision', 'idempotency', 'status-recovery', 'theme-language', 'selected-refresh',
        'jobs', 'streams', 'snapshots']}
CONFINED_CAPABILITY = {**CAPABILITY, 'version':'1.1.0', 'features': ['pinned-release','typed-operations','scoped-grants','revision','idempotency','status-recovery','theme-language','selected-refresh','snapshots','dependencies','image-selection']}
PROTOCOL = 'phemacast:agent-view-message/1'
MANIFEST = 'phemacast:agent-view-manifest/1'
HASH = re.compile(r'^[a-f0-9]{64}$')
ID = re.compile(r'^[A-Za-z][A-Za-z0-9_.:-]{0,127}$')
LOCAL = re.compile(r'^/[A-Za-z0-9_./:-]{1,255}$')
EFFECT_KEYS = {'writesState','externalSend','paidExecution','startsJob','opensStream'}
# Actions an owner offers to AI apps in its view (manifest extension). The view's own code runs each one in its frame.
AI_ACTIONS = 'phemacast:ai-actions'
AI_ACTION_ID = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
AI_ACTION_EFFECTS = ('read','view','edit','run','schedule','delete','send')
# Control and bidirectional-override characters; the same set the host refuses in a view's title and status.
UNSAFE_TEXT = re.compile(r'[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]')
CREDENTIAL_NAME = re.compile(r'(api.?key|token|secret|password|passwd|credential|cookie|session)', re.I)
POINTER = re.compile(r'(?:/[A-Za-z0-9_~-]+)+')


def exact(value, required, optional=()):
    if not isinstance(value, dict) or set(value)-set(required)-set(optional) or not set(required)<=set(value):
        raise ValueError('Unexpected or missing contract fields.')


def bounded_schema(value):
    # Uses the same no-remote-reference and bounded-depth schema validation as registry.
    validate_definition({'id':'phemacast:agent-view-schema','version':'1.0.0',
        'description':'Generic view binding schema.', 'configurationSchema':{},
        'inputSchema':value, 'outputSchema':{}})
    return deepcopy(value)


def check(schema, value):
    if len(canonical(value).encode()) > 300_000: raise ValueError('Binding payload exceeds its limit.')
    Draft202012Validator(schema).validate(value)
    return deepcopy(value)


def origin(value, *, allow_local=False):
    parsed=urlsplit(value)
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError('Use an exact credential-free origin.')
    if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.port == 0:
        raise ValueError('Invalid owner origin.')
    try:local=ipaddress.ip_address(parsed.hostname).is_private or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:local=parsed.hostname=='localhost' or parsed.hostname.endswith('.local')
    if parsed.scheme!='https' and not (allow_local and local):raise ValueError('Owner views require HTTPS or explicitly paired local transport.')
    if local and not allow_local:raise ValueError('Local-network mounting requires separate approval.')
    return value


def manifest_digest(value):return digest(value)


def _property_names(node, depth=0):
    """Every property name a schema declares or requires, at any depth."""
    if depth>64:return
    if isinstance(node,dict):
        for key,item in node.items():
            if key in ('properties','patternProperties','dependentSchemas','dependentRequired') and isinstance(item,dict):yield from item
            if key=='required' and isinstance(item,list):yield from (name for name in item if isinstance(name,str))
            yield from _property_names(item,depth+1)
    elif isinstance(node,list):
        for item in node:yield from _property_names(item,depth+1)


def _plain_text(value, low, high, field):
    if not isinstance(value,str) or not low<=len(value)<=high or (low and not value.strip()) or UNSAFE_TEXT.search(value):
        raise ValueError(f'An AI action {field} is plain text of {low} to {high} characters.')


def validate_ai_actions(value):
    """Check `extensions['phemacast:ai-actions']`: the actions an AI app may ask the view to take.

    Declaring an action grants nothing. The container still checks each call against this list, its input schema and
    its effect, and never offers `delete` or `send` actions to AI apps.
    """
    if not isinstance(value,dict) or set(value)!={'version','actions'}:raise ValueError('AI actions need exactly a version and an action list.')
    if value['version']!='1.0.0':raise ValueError('Unsupported AI actions version.')
    actions=value['actions']
    if not isinstance(actions,list) or not 1<=len(actions)<=32:raise ValueError('Declare 1 to 32 AI actions.')
    seen=set()
    for action in actions:
        exact(action,['id','title','description','effect','inputSchema','maxPoints','confirm','sourceModes'],['outputSchema','idempotencyPointer'])
        if not isinstance(action['id'],str) or not AI_ACTION_ID.fullmatch(action['id']) or action['id'] in seen:
            raise ValueError('Each AI action needs a unique lower-case id.')
        seen.add(action['id'])
        _plain_text(action['title'],1,80,'title');_plain_text(action['description'],0,500,'description')
        if action['effect'] not in AI_ACTION_EFFECTS:raise ValueError('Declare the AI action effect.')
        schema=action['inputSchema']
        if not isinstance(schema,dict) or schema.get('type')!='object' or schema.get('additionalProperties') is not False:
            raise ValueError('An AI action input is a closed object schema.')
        bounded_schema(schema)
        if len(canonical(schema).encode())>32_000:raise ValueError('An AI action input schema exceeds 32 KB.')
        if any(CREDENTIAL_NAME.search(name) for name in _property_names(schema)):
            raise ValueError('AI action inputs never carry keys, tokens, passwords or other credentials.')
        if 'outputSchema' in action:
            if not isinstance(action['outputSchema'],dict):raise ValueError('An AI action output schema is a schema object.')
            bounded_schema(action['outputSchema'])
        points=action['maxPoints']
        if type(points) is not int or not 0<=points<=100_000:raise ValueError('AI action points are a whole number from 0 to 100000.')
        if action['effect'] in ('read','view') and points:raise ValueError('Read and view actions are free.')
        if 'idempotencyPointer' in action and (not isinstance(action['idempotencyPointer'],str) or not POINTER.fullmatch(action['idempotencyPointer'])):
            raise ValueError('Invalid AI action idempotency pointer.')
        if action['confirm'] not in ('auto','always'):raise ValueError('An AI action confirms auto or always.')
        modes=action['sourceModes']
        if (not isinstance(modes,list) or not modes or any(not isinstance(mode,str) for mode in modes)
                or len(set(modes))!=len(modes) or not set(modes)<={'parameters','snapshot'}):
            raise ValueError('Explicit AI action source modes required.')
        if 'snapshot' in modes and action['effect']!='read':raise ValueError('Only read actions may run on a snapshot.')
    return deepcopy(value)


def ai_actions(manifest):
    """The actions a validated manifest offers to AI apps, as a new list; empty when it offers none."""
    declared=(manifest.get('extensions') or {}).get(AI_ACTIONS)
    return deepcopy(declared['actions']) if declared else []


def validate_manifest(value, *, allow_local=False):
    exact(value,['schema','version','publisher','viewId','release','origin','assets','html',
        'parameterSchema','operations','dependencies','requirements','disclosure'],['extensions'])
    if value['schema']!=MANIFEST or value['version']!='1.0.0':raise ValueError('Unsupported view manifest version.')
    exact(value['publisher'],['agentId','implementationDigest'])
    if not ID.fullmatch(str(value['viewId'])) or not HASH.fullmatch(str(value['release'])):raise ValueError('Invalid immutable view release.')
    if not HASH.fullmatch(str(value['publisher']['implementationDigest'])) or not 1<=len(str(value['publisher']['agentId']))<=200:
        raise ValueError('Publisher identity/build digest required.')
    origin(value['origin'],allow_local=allow_local)
    exact(value['assets'],['script'],['style'])
    for item in value['assets'].values():
        exact(item,['path','digest','bytes'])
        if not LOCAL.fullmatch(str(item['path'])) or '..' in item['path'] or item['path'].startswith('//'):
            raise ValueError('Assets must use pinned owner-relative paths.')
        if not HASH.fullmatch(str(item['digest'])) or type(item['bytes']) is not int or not 0<item['bytes']<=1_000_000:
            raise ValueError('Bounded immutable asset digest required.')
    if not isinstance(value['html'],str) or len(value['html'].encode())>100_000:raise ValueError('Bounded mount markup required.')
    if re.search(r'<\s*(script|iframe|object|embed|base|link|meta)\b|\s(on\w+|src|href|action|srcdoc)\s*=',value['html'],re.I):
        raise ValueError('Mount markup cannot contain executable or network elements.')
    bounded_schema(value['parameterSchema'])
    if not isinstance(value['operations'],list) or len(value['operations'])>128:raise ValueError('Too many operation bindings.')
    seen=set()
    for item in value['operations']:
        exact(item,['id','ref','classification','delivery','sourceModes'],['revisionPointer','idempotencyPointer','extensions'])
        if not ID.fullmatch(str(item['id'])) or item['id'] in seen:raise ValueError('Unique operation binding ID required.')
        seen.add(item['id']);validate_ref(item['ref'])
        if item['classification'] not in ('public','private','confidential'):raise ValueError('Declare data classification.')
        if not isinstance(item['delivery'],list) or not item['delivery'] or not set(item['delivery'])<={'request','job','stream','snapshot','status'}:raise ValueError('Invalid operation delivery.')
        if not isinstance(item['sourceModes'],list) or not item['sourceModes'] or not set(item['sourceModes'])<={'parameters','snapshot'}:raise ValueError('Explicit source modes required.')
        if 'snapshot' in item['sourceModes'] and not set(item['delivery'])<={'snapshot'}:raise ValueError('Snapshot bindings may only read saved snapshots.')
        for key in ('revisionPointer','idempotencyPointer'):
            if key in item and (not isinstance(item[key],str) or not re.fullmatch(r'(?:/[A-Za-z0-9_~-]+)+',item[key])):raise ValueError('Invalid control binding pointer.')
    if not isinstance(value['dependencies'],list) or len(value['dependencies'])>32:raise ValueError('Too many onward dependencies.')
    for dep in value['dependencies']:
        exact(dep,['agentId','operation','ref','maxCalls','fields'])
        validate_ref(dep['ref'])
        if not 1<=len(str(dep['agentId']))<=200 or not ID.fullmatch(str(dep['operation'])) or type(dep['maxCalls']) is not int or not 1<=dep['maxCalls']<=32:raise ValueError('Bound dependency authority.')
        if not isinstance(dep['fields'],list) or len(dep['fields'])>64 or any(not isinstance(f,str) or len(f)>128 for f in dep['fields']):raise ValueError('Declare bounded data flow fields.')
    for requirement in value['requirements']:validate_requirement(requirement)
    exact(value['disclosure'],['codeExecution','privateData','localNetwork','confidentialRequiresEgressGuard'])
    if any(type(v) is not bool for v in value['disclosure'].values()) or not value['disclosure']['codeExecution'] or not value['disclosure']['confidentialRequiresEgressGuard']:
        raise ValueError('Explicit code/disclosure review required; confidential egress guard cannot be disabled.')
    if any(o['classification'] in ('private','confidential') for o in value['operations']) and not value['disclosure']['privateData']:
        raise ValueError('Private bindings require a separate private-data disclosure.')
    extensions=value.get('extensions',{})
    if not isinstance(extensions,dict) or len(extensions)>64 or any(not re.fullmatch(r'[a-z][a-z0-9.-]+:[A-Za-z0-9._-]+',k) for k in extensions):raise ValueError('Use namespaced extensions.')
    if AI_ACTIONS in extensions:validate_ai_actions(extensions[AI_ACTIONS])
    if len(canonical(value).encode())>512_000:raise ValueError('Manifest too large.')
    return deepcopy(value)


def verify_assets(manifest, assets):
    if set(assets)!=set(manifest['assets']):raise ValueError('Release asset set mismatch.')
    for name, descriptor in manifest['assets'].items():
        data=assets[name]
        if len(data)!=descriptor['bytes'] or hashlib.sha256(data).hexdigest()!=descriptor['digest']:
            raise ValueError('Release asset integrity mismatch.')
    return {name:data.decode('utf-8') for name,data in assets.items()}


def resolve_contracts(manifest, resolver):
    """Resolver must check exact ref, current publisher ownership and audience.

    Its implementation is an authenticated registry/paired-owner adapter, never
    metadata supplied by the mounted UI. Test evidence does not grant invocation.
    """
    contracts={}
    for item in manifest['operations']:
        resolved=resolver(item['ref'])
        if resolved['ref']!=item['ref']:raise PermissionError('Contract digest mismatch.')
        resource=validate_operation(resolved['resource'])
        if resource['publisher']!=manifest['publisher']:raise PermissionError('Operation publisher/build mismatch.')
        if resolved.get('verification')!='tested':raise PermissionError('Reviewed contract evidence required for active UI.')
        if ('{' in resource['transport']['path'] or '}' in resource['transport']['path']) and resource.get('inputBinding','body')!='http-envelope':
            raise PermissionError('Parameterized operation needs explicit http-envelope input binding.')
        if resource['constraints']['expectedRevision'] and 'revisionPointer' not in item:
            raise PermissionError('Revision-required operations need a grant-bound input pointer.')
        if resource['constraints']['idempotency']=='required' and 'idempotencyPointer' not in item:
            raise PermissionError('Effect operations need a grant-bound idempotency input pointer.')
        if 'snapshot' in item['sourceModes'] and any(resource['effects'].values()):raise PermissionError('Snapshot operation cannot have effects.')
        selected=item.get('extensions',{}).get('phemacast:dependencies')
        if selected is not None:
            if not isinstance(selected,list) or len(selected)>32 or len({canonical(ref) for ref in selected})!=len(selected):raise PermissionError('Bound unique selected dependencies.')
            if selected!=resource['downstream']:raise PermissionError('View binding must disclose every declared operation dependency.')
            if any(ref not in [dep['ref'] for dep in manifest['dependencies']] for ref in selected):raise PermissionError('Operation dependency is absent from the reviewed view.')
        bounded_schema(resource['inputSchema']);bounded_schema(resource['outputSchema'])
        contracts[item['id']]=resource
    for dep in manifest['dependencies']:
        resolved=resolver(dep['ref']);resource=validate_operation(resolved['resource'])
        if resolved['ref']!=dep['ref'] or resource['publisher']['agentId']!=dep['agentId'] or resource['operation']!=dep['operation'] or resolved.get('verification')!='tested':
            raise PermissionError('Onward dependency does not match reviewed publisher/operation.')
    return contracts


def refresh_binding(manifest,entry,known,resolver):
    """Fresh selected-resource admission; immutable schemas were checked at mount.

    Do not validate or remotely resolve every unrelated binding on each click.
    The exact selected resource must still have current audience/owner/evidence
    from the trusted resolver, and must equal the initially validated content.
    Onward resources are independently rechecked by the verified grant backend.
    """
    resolved=resolver(entry['ref'])
    if (resolved.get('ref')!=entry['ref'] or resolved.get('verification')!='tested'
            or resolved.get('resource')!=known or known['publisher']!=manifest['publisher']):
        raise PermissionError('Current immutable operation admission changed.')
    return known
