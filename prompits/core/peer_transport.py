"""Registered-peer transport with explicit scoped calls, independent of clients.

Applications supply targets, schemas, time budgets and onward declarations. This
module knows nothing about application operations, providers, keys or UI state.
"""
import asyncio
import hashlib
import json
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from .call_grants import CURRENT, binding


def unwrap(value):
    for _ in range(5):
        if isinstance(value,dict) and value.get('status') in ('ok','success') and isinstance(value.get('result'),dict):value=value['result']
        else:break
    return value


_GRANTS={}


def pipeline_route(agent):
    """The Pipeline endpoint to call an agent through: only for an agent that takes no inbound connections."""
    card=agent.get('card') or {};meta=agent.get('meta') or card.get('meta') or {}
    if card.get('accepts_inbound_from_plaza') is not False and meta.get('accepts_inbound_from_plaza') is not False:return None
    return next((e for e in meta.get('endpoints') or () if isinstance(e,dict) and e.get('kind')=='pipeline' and e.get('node')),None)


def _refuse_onward_under_connection_grant(parent):
    # A Pipeline connection grant (connection_grants.py) has no Plaza-stored token to chain from. Until onward
    # delegation through Pipeline exists, a call made while answering one is refused, never silently made as the
    # agent itself; the agent's own upkeep calls go inside call_grants.as_self().
    if parent and parent.get('kind')=='connection-grant':
        raise HTTPException(403,'Onward calls while answering a Pipeline call are not supported yet; use as_self() for the agent\'s own calls.')


class ScopedPeerTransport:
    def __init__(self,plaza,registration,client):
        self.plaza=plaza.rstrip('/');self.registration=registration;self.client=client
        # Compatibility only, for phemacast/agent_view/http_aliases.py. Nothing reads it; it never
        # authorizes a peer (Plaza's current decision does, in trusted_agents() and call_headers()).
        self.trusted_origins=set()
        self.cache=None;self.expiry=0.;self.limit=asyncio.Semaphore(8)

    def require_trusted(self,agent):
        # Legacy synchronous callers use this only to validate a target. The
        # fresh Plaza decision is mandatory at dispatch, in call_headers().
        parsed=urlsplit(agent.get('address',''))
        if (not agent.get('id') or parsed.scheme not in ('http','https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise HTTPException(403,'An exact registered peer and origin are required.')

    async def require_connection(self,agent,token=''):
        self.require_trusted(agent)
        from .peer_connections import accepts_owner_connection
        accepted=await accepts_owner_connection(self.client,self.plaza,self.registration._token,
            actor=self.registration.agent_id,peer=agent['id'],origin=agent['address'])
        if not accepted and token and not token.startswith('pc-call-') and token!=self.registration._token:
            from .plaza_directory_trust import PlazaDirectoryTrust
            await PlazaDirectoryTrust(self.plaza,self.client).require(agent,token)
            accepted=True
        if not accepted:raise HTTPException(403,'Plaza did not accept this registered peer connection.')
        return agent

    async def directory(self,token='',force=False):
        if token.startswith('pc-call-'):
            parent=CURRENT.get()
            if not parent or parent.get('token')!=token:raise HTTPException(403,'Discovery requires the verified current call context.')
            token=self.registration._token or ''
        token=token or self.registration._token or ''
        scope=hashlib.sha256(token.encode()).hexdigest()
        if not force and self.cache and self.cache[0]==scope and time.monotonic()<self.expiry:return self.cache[1]
        token=token or self.registration._token or ''
        response=await self.client.get(self.plaza+'/api/plazas_status',headers={'Authorization':'Bearer '+token} if token else {},params={'include_supported_pulses':'true','live_only':'1'},timeout=httpx.Timeout(20,connect=5),follow_redirects=False)
        response.raise_for_status();entries=[]
        for plaza in response.json().get('plazas',[]):
            if not plaza.get('online'):continue
            for record in plaza.get('agents',[]):
                card=record.get('card') or {};address=card.get('address','').rstrip('/');parsed=urlsplit(address)
                if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:continue
                entries.append({'id':record.get('agent_id') or card.get('name'),'name':card.get('name'),'address':address,
                    'meta':card.get('meta') or {},'card':card,'availability':record.get('availability')})
        from .plaza_directory_trust import directory_entries
        decisions={row['id']:row for row in directory_entries(response.json())}
        for entry in entries:
            decision=decisions.get(entry['id'],{})
            # Plaza's verified registration owner travels with the decision, never the card's claim.
            entry.update(_plazaTrusted=decision.get('_plazaTrusted') is True,_plazaOwner=decision.get('_plazaOwner'),_plazaOwnerName=decision.get('_plazaOwnerName'))
        self.cache,self.expiry=(scope,entries),time.monotonic()+15
        return entries

    async def trusted_agents(self,token=''):
        # Catalog filtering uses Plaza's current per-agent decision. Dispatch
        # still re-verifies the exact peer and origin in call_headers().
        return [row for row in await self.directory(token,force=True) if row['_plazaTrusted'] is True]

    async def call_headers(self,agent,token,method,path,body=None,query=None,*,operation='',delegates=()):
        self.require_trusted(agent);parent=CURRENT.get()
        if parent and parent.get('authority'):raise HTTPException(403,'Typed onward execution requires exact immutable child authority.')
        _refuse_onward_under_connection_grant(parent)
        await self.require_connection(agent,token)
        query_string=str(httpx.QueryParams(query or {}))
        headers={'Authorization':'Bearer '+(self.registration._token if parent else token or self.registration._token or ''),
                 'X-Agent-Token':self.registration._token or ''}
        payload={'audience':agent['id'],'binding':binding(method,path,body,query_string),'operation':operation or path,
                 'delegates':list(delegates),**({'parent':parent['token']} if parent else {})}
        response=await self.client.post(self.plaza+'/api/call-grants',headers=headers,json=payload,timeout=10)
        response.raise_for_status();scoped=response.json().get('token','')
        if not scoped.startswith('pc-call-'):raise HTTPException(403,'Scoped peer authorization unavailable.')
        return {'Authorization':'Bearer '+scoped,'Cache-Control':'no-store'}

    async def pulse(self,agent,name,parameters,token='',*,timeout=40,delegates=(),compile_onward=False,user_id=None):
        self.require_trusted(agent)
        names={pulse.get('pulse_name') or pulse.get('name') for pulse in agent.get('meta',{}).get('supported_pulses',[])}
        if name not in names:raise HTTPException(422,'The selected peer does not publish this operation.')
        if not isinstance(parameters,dict) or type(timeout) not in (int,float) or not 0<timeout<=300:raise ValueError('Typed peer parameters and bounded time budget required.')
        if pipeline_route(agent):
            if delegates or compile_onward:raise HTTPException(403,'Onward delegation through Pipeline is not supported yet.')
            return await self.pipeline_pulse(agent,name,parameters,token,timeout=timeout)
        if compile_onward and CURRENT.get() is None:
            from .declared_dependencies import compile_dependencies
            if delegates:raise PermissionError('Use exactly the selected publisher declaration; do not merge ambient authority.')
            delegates=await compile_dependencies(self,agent,name,parameters,token=token,user_id=user_id)
        path='/use_practice/get_pulse_data'
        payload={'sender':self.registration.agent_id,'receiver':agent['id'],'msg_type':'get_pulse_data',
            'content':{'pulse_name':name,'params':parameters},'caller_agent_name':self.registration.agent_name,
            'caller_agent_address':{'pit_id':self.registration.agent_id,'plazas':[]},
            'caller_agent_url':self.registration.public_url,'caller_protocol_version':'1.0','billing':None}
        headers=await self.call_headers(agent,token,'POST',path,payload,operation=name,delegates=delegates)
        scoped=headers['Authorization'].removeprefix('Bearer ')
        payload.update(caller_plaza_token=scoped,caller_user_token=scoped if token else None)
        async with self.limit:
            response=await self.client.post(agent['address']+path,headers=headers,json=payload,timeout=timeout,follow_redirects=False)
            response.raise_for_status();return unwrap(response.json())

    async def pipeline_pulse(self,agent,name,parameters,token,*,timeout,practice='get_pulse_data',billing=None):
        """A pulse to an agent that takes no inbound connections, through its Pipeline node (pipeline_client.py).

        `practice` is the agent's practice (get_pulse_data, or quote_pulse_data for a price); `billing` is passed on as
        is, for a payment scope the callee checks with Plaza itself."""
        if not isinstance(practice,str) or practice not in ('get_pulse_data','quote_pulse_data'):
            raise HTTPException(403,'Only pulse practices go through Pipeline.')
        from .pipeline_agent import caller_identity
        from .pipeline_client import pipeline_client
        if CURRENT.get() is not None:
            # Answering a call: onward delegation through Pipeline comes later. The agent's own calls use as_self().
            raise HTTPException(403,'Onward calls through Pipeline are not supported yet; use as_self() for the agent\'s own calls.')
        key=caller_identity()
        granted=await self._connection_grant(agent['id'],[name],token,key)
        payload={'sender':self.registration.agent_id,'receiver':agent['id'],'msg_type':'get_pulse_data',
            'content':{'pulse_name':name,'params':parameters},'caller_agent_name':getattr(self.registration,'agent_name',None),
            'caller_agent_address':{'pit_id':self.registration.agent_id,'plazas':[]},
            'caller_agent_url':getattr(self.registration,'public_url',None),'caller_protocol_version':'1.0','billing':billing}
        endpoint={'kind':'pipeline','node':granted['node']['id'],'url':granted['node']['url']}
        async with self.limit:
            async with pipeline_client(endpoint=endpoint,grant=granted['grant'],pass_ticket=granted['pass'],caller_key=key,timeout=timeout) as client:
                response=await client.post('/use_practice/'+practice,json=payload)
                response.raise_for_status();return unwrap(response.json())

    async def _connection_grant(self,audience,operations,token,key):
        """Plaza's connection grant for these operations on `audience`, reused until 30 s before it expires."""
        from .pipeline_agent import key_record
        agent_token=self.registration._token or ''
        record=key_record(key)
        cache=(self.plaza,self.registration.agent_id,audience,tuple(operations),hashlib.sha256((token or '').encode()).hexdigest(),record['keyId'])
        kept=_GRANTS.get(cache)
        if kept and kept['expiresAt']-time.time()>30:return kept
        response=await self.client.post(self.plaza+'/api/connection-grants',
            headers={'Authorization':'Bearer '+(token or agent_token),'X-Agent-Token':agent_token},
            json={'audience':audience,'operations':list(operations),'callerKey':record['publicKey']},timeout=10,follow_redirects=False)
        if response.status_code in (403,409,422):
            try:detail=response.json().get('detail')
            except ValueError:detail=None
            raise HTTPException(response.status_code,detail or 'Plaza refused a connection grant.')
        response.raise_for_status();value=response.json()
        node=value.get('node') if isinstance(value,dict) else None
        if not isinstance(node,dict) or not node.get('id') or not node.get('url') or not isinstance(value.get('grant'),dict) or not isinstance(value.get('pass'),dict):
            raise HTTPException(502,'Plaza answered a connection grant without a Pipeline node.')
        if len(_GRANTS)>=1024:_GRANTS.clear()
        _GRANTS[cache]=value
        return value

    async def events(self,agent,path,parameters,token,sequence=None):
        self.require_trusted(agent)
        if not isinstance(path,str) or not path.startswith('/') or any(value in path for value in ('..','\\','?','#','%')):raise HTTPException(403,'Invalid published event path.')
        headers={**await self.call_headers(agent,token,'GET',path,query=parameters),'Accept':'text/event-stream'}
        if sequence is not None:headers['Last-Event-ID']=str(sequence)
        async with self.client.stream('GET',agent['address']+path,headers=headers,params=parameters,timeout=httpx.Timeout(60,read=90),follow_redirects=False) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if len(line)>500_000:raise ValueError('Peer event exceeds buffer limit.')
                if line.startswith('data:'):
                    yield json.loads(line[5:].strip())
