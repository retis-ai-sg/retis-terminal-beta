"""Versioned, data-only contracts shared by media validators and publishers."""
from copy import deepcopy

TEXT = {'type':'string', 'maxLength':200000}
# The setting a viewer panel keeps: the mode, the page's address, and a picture of at most 1024 px (base64); for a PDF,
# which page that picture shows; for a Phema, which one (its name, the key its storage lists it by, that storage and its
# Phema id), its panels' places on the grid, and the last picture the person's Terminal saved of it.
VIEWER_PICTURE = {'type':'object','properties':{'data':{'type':'string','maxLength':280000},'type':{'enum':['image/jpeg','image/png','image/webp']},
                                                'width':{'type':'integer','minimum':1,'maximum':1024},'height':{'type':'integer','minimum':1,'maximum':1024}},
                  'required':['data','type'],'additionalProperties':False}
VIEWER_CELL = {'type':'number','minimum':0,'maximum':128}
VIEWER_PHEMA = {'type':'object','required':['name','key'],'additionalProperties':False,'properties':{
    'name':{'type':'string','minLength':1,'maxLength':200},'key':{'type':'string','minLength':1,'maxLength':300},
    'storage':{'type':'string','maxLength':300},'phemaId':{'type':'string','maxLength':300},
    'columns':{'type':'integer','minimum':1,'maximum':24},
    'panels':{'type':'array','maxItems':64,'items':{'type':'object','additionalProperties':False,'properties':{
        'label':{'type':'string','maxLength':200},'column':VIEWER_CELL,'row':VIEWER_CELL,'columnSpan':VIEWER_CELL,'rowSpan':VIEWER_CELL}}},
    'image':VIEWER_PICTURE}}
VIEWER_VALUE = {'type':'object','properties':{'mode':{'enum':['web','image','phema']},'url':{'type':'string','maxLength':4096},
                'image':VIEWER_PICTURE,
                'pdf':{'type':'object','required':['name','page','pages'],'additionalProperties':False,'properties':{
                    'name':{'type':'string','maxLength':120},'size':{'type':'integer','minimum':0},
                    'page':{'type':'integer','minimum':1,'maximum':5000},'pages':{'type':'integer','minimum':1,'maximum':5000}}},
                'phema':VIEWER_PHEMA},'additionalProperties':False}
URL = {'type':'string', 'pattern':r'^https://[^/@\s]+(?:/[^\s]*)?$', 'maxLength':4096}
VECTOR = {'type':'array','minItems':3,'maxItems':3,'items':{'type':'number','minimum':-10000,'maximum':10000}}

def obj(properties, required=(), **kw):
    return {'type':'object','properties':properties,'required':list(required), **kw}

TIMELINE = obj({'duration':{'type':'number','exclusiveMinimum':0,'maximum':86400},'loop':{'type':'boolean'},'tracks':{'type':'array','maxItems':100,'items':obj({'target':{'type':'string','maxLength':80},'property':{'enum':['position','rotation','size']},'keyframes':{'type':'array','minItems':2,'maxItems':500,'items':obj({'time':{'type':'number','minimum':0,'maximum':86400},'value':VECTOR},['time','value'],additionalProperties=False)}},['target','property','keyframes'],additionalProperties=False)}}, ['duration','tracks'], additionalProperties=False)
SCENE_OBJECT = obj({'id':{'type':'string','pattern':'^[a-zA-Z0-9_-]{1,80}$'},'shape':{'enum':['box','sphere','mesh']},'position':VECTOR,'rotation':VECTOR,'size':VECTOR,'spin':{'type':'number','minimum':-10,'maximum':10},'color':{'type':'string','pattern':'^#[0-9a-fA-F]{6}$'},'vertices':{'type':'array','maxItems':10000,'items':VECTOR},'faces':{'type':'array','maxItems':20000,'items':{'type':'array','minItems':3,'maxItems':4,'items':{'type':'integer','minimum':0,'maximum':9999}}}}, ['shape'], additionalProperties=False)
MEDIA_SCHEMAS = {
 'text':obj({'text':TEXT,'title':TEXT,'url':URL},['text']),
 'image':obj({'url':URL,'alt':TEXT,'title':TEXT},['url']),
 'scene':obj({'description':TEXT,'objects':{'type':'array','maxItems':100,'items':SCENE_OBJECT},'timeline':TIMELINE,'asset':obj({'url':URL,'format':{'enum':['gltf','glb']},'version':{'type':'string','minLength':1},'animation':{'type':'string'},'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}},['url','format','version'])},['objects']),
 'interactive':obj({'title':TEXT,'description':TEXT,'inputSchema':{'type':'object'},'submitLabel':{'type':'string','maxLength':80},'result':{}},['inputSchema']),
 # A web page or a picture the person chooses to look at, kept in one page setting (`parameter`) that the Phema's owner reads.
 # `value` is that setting, bound in ({"$param": ...}) when the page opens.
 'viewer':obj({'parameter':{'type':'string','pattern':'^[A-Za-z][A-Za-z0-9_]{0,63}$'},'title':TEXT,'value':{'type':'object'}},['parameter']),
}
for kind in ('audio','video'):
 MEDIA_SCHEMAS[kind]=obj({'url':URL,'title':TEXT,'poster':URL,'transcript':TEXT,'captions':{'type':'array','maxItems':32,'items':obj({'url':URL,'language':{'type':'string','maxLength':35},'label':{'type':'string','maxLength':100}},['url','language'])},'playback':obj({'start':{'type':'number','minimum':0},'end':{'type':'number','minimum':0},'loop':{'type':'boolean'},'muted':{'type':'boolean'},'rate':{'type':'number','minimum':0.25,'maximum':4}},additionalProperties=False)},['url'])

CUSTOM_SCHEMAS = {
 'phemacast:display.table':obj({'columns':{'type':'array','minItems':1,'maxItems':50,'items':obj({'key':{'type':'string','maxLength':100},'label':{'type':'string','maxLength':100}},['key'])},'rows':{'type':'array','maxItems':10000,'items':{'type':'object'}}},['columns','rows']),
 'phemacast:display.key-values':obj({'values':{'type':'object','maxProperties':200}},['values'])
}
# Controls the host renders (phemacast/core/controls.py); the other kinds join as their renderers ship.
from .controls import KINDS as _CONTROLS, RENDERERS as _RENDERERS, VERSION as _CONTROL_VERSION, json_schema as _control_schema
CUSTOM_SCHEMAS.update({_RENDERERS[kind]:_control_schema(kind) for kind in _CONTROLS})
# Renderer versions where they differ from the display renderers' 1.1.0.
CUSTOM_VERSIONS={_RENDERERS[kind]:_CONTROL_VERSION for kind in _CONTROLS}

def media_schema(kind):
 return deepcopy(MEDIA_SCHEMAS[kind])
