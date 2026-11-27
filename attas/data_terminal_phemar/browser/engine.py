"""Owner-scoped Browser lifecycle, deterministic binding and bounded updates."""

# OBSOLETE BUSINESS BRANCHES — remove after their owning-agent cutovers.
# Keep only generic container/transport primitives; do not extend domain branches.
# See BUSINESS_LOGIC_OBSOLETE.json. This marker does not retire live routes.
# Analyst commentary branches are obsolete: owner_v1/service.py and watch.py
# in AnalystDataSource own interpretation triggers, state and confirmations.
from __future__ import annotations

import asyncio
import copy
import json
import math
import secrets
import time
import hashlib
import re
from datetime import datetime, timezone

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from attas.data_terminal_phemar.contracts import identifier, layout_operation
from .interactions import interaction_parameters



















def component_update(viewer):
    """The newer copy of a refused page that a component on this computer ships (native_trust.component_pages), as
    the window shows it: the component's name, its Phema library key and revision."""
    value=viewer.get('_nativeTrustNewer') if isinstance(viewer,dict) else None
    if not isinstance(value,dict) or not isinstance(value.get('key'),str) or not value['key'].startswith('local:'):return None
    return {'name':str(value.get('name') or '')[:80],'key':value['key'][:200],'revision':value.get('revision') if type(value.get('revision')) is int else 1}


# A panel whose program on this computer is not answering (native_trust.stopped_local). The window reads `message`
# (local_resources.not_answering) in its language and reloads the layout once `program` runs again.
NOT_ANSWERING='local-not-answering'


def not_answering(viewer,phema):
    """({reference path: its panel's result}, the result for the layout's other panels) for the programs on this computer
    the Phema calls that are not answering; ({}, None) when every one answers."""
    stopped=viewer.get('_nativeTrustNotAnswering') if isinstance(viewer,dict) else None
    if not isinstance(stopped,dict):return {},None
    stopped={agent:text for agent,text in stopped.items() if isinstance(agent,str) and agent.startswith('local-') and isinstance(text,str)}
    if not stopped:return {},None
    from phemacast.core.composition import reference_paths
    result=lambda agent:{'status':'unavailable','reason':NOT_ANSWERING,'message':stopped[agent][:300],'program':agent.removeprefix('local-')}
    panels={path:result(agent) for path,ref in reference_paths(phema).items()
            if isinstance(agent:=ref.get('target',{}).get('agentId'),str) and agent in stopped}
    return panels,result(min(stopped))


class BrowserEngine:
    def __init__(self, store, network):
        self.store, self.network = store, network
        self.instances = {}
        self.jobs = {}
        self.semaphore = asyncio.Semaphore(6)
        self.cache = {}
        self._saved_results = {}
        self.terminal_window = ''

    def owned(self, id, user):
        instance = self.instances.get(id)
        if not instance or instance['owner'] != user['id']:
            raise HTTPException(404, 'Browser instance unavailable.')
        return instance

    def public(self,instance):
        result = {k: v for k, v in instance.items() if k not in ('owner', 'token') and not k.startswith('_')}
        if instance.get('phema'):
            from ..phema_security import approval,binding_scope
            from phemacast.core.composition_permissions import manifest
            viewer=instance.get('_nativeTrustUser') or {'id':instance['owner'],'terminalWindow':self.terminal_window}
            grant=approval(self.store,viewer,instance['phema'],binding_scope(instance))
            # A program on this computer the Phema calls is not answering: its panels say so, approved or not. Until it
            # answers, the layout's other panels wait for it too (native_trust asks Plaza nothing meanwhile).
            stopped,waits=not_answering(viewer,instance['phema'])
            # Plaza did not answer the trust check: still not trusted, but not a 'no' either.
            unconfirmed=not grant and not waits and viewer.get('_nativeTrustUnconfirmed') is True
            # A component on this computer ships a newer copy of this refused page: the window offers to take it.
            newer=component_update(viewer)
            result['security']={'approved':bool(grant), 'mediaOrigins':[], 'localOrigins':[], 'authorityBindings':binding_scope(instance),
                                **({'trustUnconfirmed':True} if unconfirmed else {}),**({'componentUpdate':newer} if newer else {})}
            result['results']=copy.deepcopy(result.get('results',{}))
            for requirement in instance.get('entry',{}).get('design',{}).get('dataRequirements',[]):
                from phemacast.core.composition_permissions import requirement_permissions
                rules=requirement_permissions([requirement],(manifest(instance['phema']) or {}).get('requirements',[]))
                if rules[0]['classification']!='public' and not (grant or {}).get('privateData'):
                    result['results'][requirement['id']]={'status':'blocked','rows':[],'error':'Private data permission required.'}
            if instance.get('content'):
                result['content']=copy.deepcopy(instance['content'])
                from phemacast.core.composition import walk_compositions
                private_ids={ref['id'] for _,node in walk_compositions(instance['phema']) for ref in (manifest(node) or {}).get('references',[]) if ref['classification']!='public'}
                def redact(value,path=''):
                    for id in value.get('results',{}):
                        said=stopped.get('/'.join(filter(None,(path,id))))
                        if not grant and waits:
                            value['results'][id]=copy.deepcopy(said or waits)
                        elif not grant or id in private_ids and not grant.get('privateData'):
                            value['results'][id]={'status':'blocked','reason':'trust-unconfirmed' if unconfirmed else 'permission-required'}
                        elif said and value['results'][id].get('status') in ('failed','unavailable'):
                            # Approved: what was read before stays; a read that failed says why.
                            value['results'][id]=copy.deepcopy(said)
                    for name,child in value.get('components',{}).items():redact(child,'/'.join(filter(None,(path,name))))
                redact(result['content'])
            if grant:
                from phemacast.core.composition import walk_compositions
                for _,current in walk_compositions(instance['phema']):
                    permissions=manifest(current) or {}
                    result['security']['mediaOrigins']+=permissions.get('mediaOrigins',[])
                    if grant.get('localNetwork'):result['security']['localOrigins']+=permissions.get('localOrigins',[])
            from phemacast.core.composition import reference_paths
            required = [id for id,r in reference_paths(instance['phema']).items() if r.get('required', True)]
            if any(instance.get('content', {}).get('results', {}).get(id, {}).get('status') != 'ready' for id in required) and result.get('status') in ('ready','completed'):
                result['status'] = 'partial'
        return result

    @staticmethod
    def called(phema):
        """The agents the Phema's links call by id. A target the viewer chooses ({"$param": …}) has no id here."""
        from phemacast.core.composition import reference_paths,walk_compositions
        return {a for _,current in walk_compositions(phema) for r in reference_paths(current).values() if isinstance(a:=r.get('target',{}).get('agentId'),str)}

    async def local_names(self,user,phema):
        """The programs running on this computer that the Phema's links call, by the name each announces (empty when
        it announces none). None of them is on Plaza: the permissions dialog says the inputs stay on this computer.
        The Terminal's directory lists them (a browser process reads it from the Terminal); a Plaza agent's address is
        always http(s), never this computer's own `phemacast-local://`."""
        wanted=self.called(phema)
        if not wanted:return {}
        try:entries=await self.network.directory(user.get('token',''))
        except Exception:return {}
        name=lambda entry:entry['name'].strip() if isinstance(entry.get('name'),str) else ''
        return {entry['id']:name(entry) for entry in entries if isinstance(entry,dict) and entry.get('id') in wanted
                and entry.get('local') is True and str(entry.get('address','')).startswith('phemacast-local://')}

    async def agent_names(self,user,phema):
        """Plaza's listed name for each agent the Phema's links call; an agent Plaza does not list stays unnamed."""
        wanted=self.called(phema)
        authority=getattr(self.network,'plaza_trust',None)
        if not wanted or not authority or not user.get('token'):return {}
        try:rows=await authority.answer(user['token'])
        except Exception:return {}
        return {row['id']:row['name'] for row in rows if row.get('id') in wanted and isinstance(row.get('name'),str) and row['name'].strip()}

    def settings_fingerprint(self, owner, include_selections=False):
        return hashlib.sha256(json.dumps([owner, self.terminal_window]).encode()).hexdigest()

    def preferences(self, owner):
        return {}


    def restore_results(self, instance, user):
        # Legacy observations are preserved in the migration export. Only the
        # owning agent may interpret/revalidate them; no local data fallback.
        return None

    async def cancel(self, id):
        job = self.jobs.pop(id, None)
        instance=self.instances.get(id,{})
        tasks=list(instance.pop('_requirementTasks',{}).values())
        tasks.extend(instance.pop('_manualContentTasks',{}).values())
        content_task=instance.pop('_contentTask',None)
        if content_task: tasks.append(content_task)
        instance.pop('_restartRequirements',None)
        instance.pop('_configureRefresh',None)
        instance.pop('_reconcileRequirements',None)
        if job:tasks.append(job)
        for task in tasks:task.cancel()
        if tasks:await asyncio.gather(*tasks, return_exceptions=True)

    async def close_owner(self, owner):
        for id in list(self.instances):
            if self.instances[id]['owner'] == owner:
                await self.cancel(id)
                self.instances.pop(id, None)

    async def close_all(self):
        for id in list(self.jobs):
            await self.cancel(id)
        self.instances.clear()

    async def reap(self, interval=15):
        while True:
            await asyncio.sleep(interval)
            for id, instance in list(self.instances.items()):
                if time.time() > instance['leaseUntil'] and not instance['activeSubscribers']:
                    await self.cancel(id)
                    self.instances.pop(id, None)

    async def route(self, rest, request, user):
        parts = rest.strip('/').split('/') if rest.strip('/') else []
        if not parts:
            if request.method == 'DELETE':
                await self.close_owner(user['id'])
                return {'status': 'closed'}
            if request.method == 'GET':
                return {'instances': [self.public(i) for i in self.instances.values() if i['owner'] == user['id']]}
            if request.method != 'POST':
                raise HTTPException(405)
            if len(self.instances) >= 512 or sum(i['owner'] == user['id'] for i in self.instances.values()) >= 384:
                raise HTTPException(429, 'Browser instance limit reached.')
            body = await request.json()
            from ..phema_transfer import accept
            phema, entry = await accept(body)
            from .nested import project
            entry, nested_layouts, nested_interactions = project(phema, body.get('instrumentOverrides'), body.get('parameterValues'))
            id = secrets.token_hex(16)
            range = body.get('range', '1M')
            if range not in ('1D', '1W', '1M', '3M', '1Y'):
                raise HTTPException(422, 'Unsupported chart range.')
            instance = {'id': id, 'owner': user['id'], 'workspaceId': identifier(body.get('workspaceId')), 'entry': copy.deepcopy(entry), 'command': str(body.get('command', entry['command']))[:499], 'range': range, 'generation': 1, 'status': 'loading', 'results': {}, 'updatedAt': time.time(), 'messages': [], 'sequence': 0, 'activeSubscribers': 0, 'leaseUntil': time.time()+90}
            language=body.get('uiLanguage')
            if language is not None and language not in ('en','zh-Hant','zh-Hans','ja','es','fr'):raise HTTPException(422,'Unsupported UI language.')
            instance['uiLanguage']=language
            instance['phema'] = phema
            # What the client sent, before any revision is authored from it: sending the same page again is no edit.
            from prompits.core.capabilities import digest
            instance['_acceptedDigest'] = digest(phema)
            instance['parameterValues'] = copy.deepcopy(body.get('parameterValues') or {})
            instance['instrumentOverrides'] = copy.deepcopy(body.get('instrumentOverrides') or {})
            from ..content_policy import validate_overrides
            instance['contentOverrides']=validate_overrides(phema,body.get('contentOverrides',{}))
            instance['nestedLayouts'] = nested_layouts
            instance['layoutTabs'] = body.get('layoutTabs') or {}
            instance['_nestedInteractions'] = nested_interactions
            instance['sourceMode'] = 'parameters'
            instance['refreshOverrides']=self.validate_refresh_overrides(body.get('refreshOverrides',{}),entry)
            instance['fieldBindings']={}
            messages=body.get('messages',[])
            interactive_ids={n['id'] for n in [*entry['design']['layout']['children'], *nested_interactions] if n['type']=='phemar' or n.get('template')=='pulse-chat'}
            if not isinstance(messages,list) or len(messages)>40:
                raise HTTPException(422,'Conversation state must contain at most 40 messages.')
            for message in messages:
                if not isinstance(message,dict) or message.get('role') not in ('user','assistant') or not isinstance(message.get('nodeId'),str) or len(message['nodeId'])>80 or not isinstance(message.get('text'),str) or len(message['text'])>8000:
                    raise HTTPException(422,'Invalid saved conversation state.')
            instance['messages']=[{k:v for k,v in m.items() if k in ('role','text','nodeId','agentId','pulseName','pulseId')} for m in messages if m['nodeId'] in interactive_ids]
            instance['_settingsFingerprint'] = self.settings_fingerprint(user['id'])
            # The worker attaches Plaza's current trust to existing instances before each call; a new
            # one takes it from this call, or a snapshot, whose content never changes, stays locked.
            instance['_nativeTrustUser'] = dict(user)
            self.restore_results(instance,user)
            self.instances[id] = instance
            if body.get('sourceMode')=='snapshot':
                from .content import restore_snapshot
                try:
                    if body.get('snapshotId'):
                        await restore_snapshot(self,instance,user,body['snapshotId'])
                    else:
                        from phemacast.core.snapshot_mount import resolved_snapshot
                        instance['content']=resolved_snapshot(phema)
                        instance['results']={};instance['sourceMode']='snapshot';instance['status']='ready'
                except BaseException:
                    self.instances.pop(id,None);raise
            else:
                self.jobs[id] = asyncio.create_task(self.run(instance, user))
            return self.public(instance)
        id = identifier(parts[0])
        instance = self.owned(id, user)
        if len(parts)==2 and parts[1]=='permissions' and request.method in ('GET','POST'):
            from ..phema_security import review,binding_scope
            body=await request.json() if request.method=='POST' else None
            result=review(self.store,user,instance['phema'],body,binding_scope(instance))
            # The dialog names each link by the panel it fills, the agent it goes to and the symbols it reads.
            from .content import panel_titles
            local=await self.local_names(user,instance['phema'])
            newer=component_update(instance.get('_nativeTrustUser') or {})
            result={**result,'panelTitles':panel_titles(instance),
                    'agentNames':{**await self.agent_names(user,instance['phema']),**{k:v for k,v in local.items() if v}},
                    'localAgents':sorted(local),**({'componentUpdate':newer} if newer else {}),
                    'parameters':{k:v['default'] for k,v in instance['entry']['design']['params'].items() if 'default' in v}}
            # The other-panels choice alone changes nothing the Browser shows: no reload.
            if request.method=='POST' and set(body)!={'panelAccess'}:
                if body.get('revoke'):
                    tasks=list(instance.get('_manualContentTasks',{}).values())
                    for task in tasks:task.cancel()
                    await asyncio.gather(*tasks,return_exceptions=True)
                if instance.get('sourceMode')=='snapshot':
                    # A snapshot keeps its saved content: the decision only changes what this view may show.
                    instance['sequence']+=1
                else:
                    from .content import refresh_content
                    await refresh_content(self,instance,user,references=None,trigger='open')
            return result
        if len(parts)==2 and parts[1]=='sources' and request.method=='GET':
            # The source menus in the Browser's data panel headings (its per-panel source choice).
            from .content import panel_sources
            return {'byPanel':await panel_sources(self,instance,user)}
        if len(parts)==2 and parts[1]=='content' and request.method in ('GET','POST'):
            from .content import content_route
            return await content_route(self,instance,request,user)
        # The Terminal polls workers over IPC, rather than subscribing to their
        # SSE route. Any authorized activity renews the worker's own lease too.
        instance['leaseUntil'] = time.time() + 90
        if len(parts) == 1:
            if request.method == 'GET':
                return self.public(instance)
            if request.method == 'DELETE':
                await self.cancel(id)
                self.instances.pop(id, None)
                return {'status': 'closed'}
            if request.method == 'PUT':
                body = await request.json()
                if set(body)=={'uiLanguage'}:
                    language=body['uiLanguage']
                    if language is not None and language not in ('en','zh-Hant','zh-Hans','ja','es','fr'):raise HTTPException(422,'Unsupported UI language.')
                    instance['uiLanguage']=language
                    instance['sequence']+=1
                    return self.public(instance)
                if instance.get('sourceMode')=='snapshot' and set(body)-{'uiLanguage'}:
                    raise HTTPException(409,'Switch to parameter mode before changing or refreshing a snapshot.')
                if 'fieldBindings' in body and not ('entry' in body or 'phema' in body):
                    raise HTTPException(410, 'Configure data bindings in the owning agent workspace.')
                    bindings={}
                    old=instance.get('fieldBindings',{})
                    changed={rid for rid in set(old)|set(bindings) if old.get(rid)!=bindings.get(rid)}
                    callback=instance.get('_restartRequirements')
                    if changed and not callback:raise HTTPException(409,'Browser is still initializing. Try again shortly.')
                    instance['fieldBindings']=bindings
                    if changed:await callback(changed)
                    return self.public(instance)
                if ('refreshOverrides' in body or 'refreshRequirement' in body) and not ('entry' in body or 'phema' in body):
                    overrides=self.validate_refresh_overrides(body.get('refreshOverrides',instance.get('refreshOverrides',{})),instance['entry'])
                    rid=body.get('refreshRequirement')
                    ids={r['id'] for r in instance['entry']['design']['dataRequirements'] if r['mode']!='interactive'}
                    if rid is not None and rid not in ids:raise HTTPException(422,'Unknown refresh dataset.')
                    callback=instance.get('_configureRefresh')
                    if not callback:raise HTTPException(409,'Browser is still initializing. Try again shortly.')
                    await callback(overrides,rid)
                    return self.public(instance)
                accepted=None
                if 'entry' in body or 'phema' in body:
                    from ..phema_transfer import accept
                    from prompits.core.capabilities import digest
                    updated_phema, updated_entry = await accept(body)
                    accepted=digest(updated_phema)
                    from ..phema_transfer import to_entry
                    if instance.get('phema') and accepted==instance.get('_acceptedDigest'):
                        # The same page sent again with new page values (a viewer's picture, a control's value): no
                        # edit, so no new revision. The Phema keeps its fingerprint, so views mounted on it and the
                        # viewer's approval of it stay as they were.
                        updated_phema = instance['phema']
                    else:
                        # An in-place edit is a new authored revision. Refresh its
                        # declarations and invalidate consent without changing the
                        # immutable publication from which the Browser was opened.
                        from ..phema_security import upgrade
                        updated_phema = upgrade(updated_phema)
                    updated_entry = to_entry(updated_phema)
                    from .nested import project
                    same_layout=updated_entry['id']==instance['entry']['id']
                    parameters=body.get('parameterValues',instance.get('parameterValues') if same_layout else None)
                    instruments=body.get('instrumentOverrides',instance.get('instrumentOverrides') if same_layout else None)
                    updated_entry, nested_layouts, nested_interactions = project(updated_phema, instruments, parameters)
                else:
                    updated_phema, updated_entry = instance.get('phema'), instance['entry']
                updated_range = body.get('range', instance['range'])
                if updated_range not in ('1D','1W','1M','3M','1Y'):
                    raise HTTPException(422, 'Unsupported chart range.')
                previous_requirements={r['id']:r for r in instance['entry']['design']['dataRequirements']}
                old_tabs=instance.get('layoutTabs',{})
                tabs=body.get('layoutTabs',old_tabs)
                range_changed=updated_range!=instance['range']
                editing='entry' in body or 'phema' in body
                settings=None
                if editing:
                    from .settings import saved_settings
                    valid={r['id']:r for r in updated_entry['design']['dataRequirements'] if r.get('mode')!='interactive'}
                    bindings={rid:{**binding,'fields':{f:v for f,v in binding['fields'].items() if f in valid[rid]['fields'] or f in binding['joinKeys']}} for rid,binding in instance.get('fieldBindings',{}).items() if rid in valid}
                    from phemacast.core.composition import reference_paths
                    content_ids=set(reference_paths(updated_phema))
                    settings=saved_settings(updated_phema,updated_entry,{
                        'fieldBindings':body.get('fieldBindings',bindings),
                        'refreshOverrides':body.get('refreshOverrides',{k:v for k,v in instance.get('refreshOverrides',{}).items() if k in valid}),
                        'contentOverrides':body.get('contentOverrides',{k:v for k,v in instance.get('contentOverrides',{}).items() if k in content_ids}),
                        'instrumentOverrides':instruments or {},'parameterValues':parameters or {},
                        'range':updated_range,'layoutTabs':tabs,'uiLanguage':body.get('uiLanguage',instance.get('uiLanguage'))})
                # Presentation edits keep subscriptions and loaded datasets alive.
                # Reconcile changed requirements separately when discovery is ready.
                from .nested import visible_requirements
                same_requirements=updated_entry['design']['dataRequirements']==instance['entry']['design']['dataRequirements'] and visible_requirements(updated_entry,nested_layouts if editing else instance.get('nestedLayouts',{}),tabs)==visible_requirements(instance['entry'],instance.get('nestedLayouts',{}),old_tabs)
                if editing and not range_changed and not body.get('suspended') and (same_requirements or instance.get('_reconcileRequirements')):
                    from .content import run_content
                    from phemacast.core.composition import reference_paths, content_hash
                    before=reference_paths(instance['phema']);after=reference_paths(updated_phema)
                    changed={id for id,ref in after.items() if before.get(id)!=ref}
                    old_bindings=instance.get('fieldBindings',{})
                    binding_changes={rid for rid in set(old_bindings)|set(settings['fieldBindings']) if old_bindings.get(rid)!=settings['fieldBindings'].get(rid)}
                    instance['entry']=copy.deepcopy(updated_entry);instance['phema']=updated_phema
                    if accepted:instance['_acceptedDigest']=accepted
                    instance['command']=str(body.get('command',instance['command']))[:499]
                    instance['nestedLayouts']=nested_layouts;instance['_nestedInteractions']=nested_interactions
                    old_refresh=instance.get('refreshOverrides',{})
                    old_content_overrides=instance.get('contentOverrides',{})
                    instance.update({k:v for k,v in settings.items() if k!='refreshOverrides'})
                    if not same_requirements:
                        contract_changes={r['id'] for r in updated_entry['design']['dataRequirements'] if previous_requirements.get(r['id'])!=r}
                        binding_changes-=contract_changes
                        await instance['_reconcileRequirements']()
                    if binding_changes and instance.get('_restartRequirements'):await instance['_restartRequirements'](binding_changes)
                    if old_refresh!=settings['refreshOverrides'] and instance.get('_configureRefresh'):await instance['_configureRefresh'](settings['refreshOverrides'],None)
                    else:instance['refreshOverrides']=settings['refreshOverrides']
                    if instance.get('content'):instance['content']['contentHash']=content_hash(updated_phema)
                    if before!=after or settings['contentOverrides']!=old_content_overrides:
                        task=instance.pop('_contentTask',None)
                        if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
                        if instance.get('content'):
                            instance['content']['contentHash']=content_hash(updated_phema)
                            instance['content']['results']={id:r for id,r in instance['content'].get('results',{}).items() if id in after and id not in changed}
                        instance['_contentTask']=asyncio.create_task(run_content(self,instance,user,changed=changed))
                    instance['sequence']+=1
                    return self.public(instance)
                preserved={r['id']:instance['results'][r['id']] for r in updated_entry['design']['dataRequirements'] if previous_requirements.get(r['id'])==r and r['id'] in instance['results'] and not (range_changed and r.get('schema')=='market.history.v1')}
                await self.cancel(id)
                instance['entry'] = copy.deepcopy(updated_entry)
                instance['phema'] = updated_phema
                if accepted:instance['_acceptedDigest']=accepted
                if 'entry' in body or 'phema' in body:
                    instance['nestedLayouts']=nested_layouts;instance['_nestedInteractions']=nested_interactions
                valid={r['id']:r for r in updated_entry['design']['dataRequirements'] if r.get('mode')!='interactive'}
                instance['fieldBindings']={rid:{**binding,'fields':{f:v for f,v in binding['fields'].items() if f in valid[rid]['fields'] or f in binding['joinKeys']}} for rid,binding in instance.get('fieldBindings',{}).items() if rid in valid}
                instance['layoutTabs']=tabs
                if settings:instance.update(settings)
                instance['range'] = updated_range
                instance['command'] = str(body.get('command', instance['command']))[:499]
                instance['generation'] += 1
                instance['status'] = 'suspended' if body.get('suspended') else 'loading'
                if body.get('suspended'):instance['error']=body.get('error') or 'Browser paused because its Terminal session could not be verified.'
                else:instance.pop('error',None)
                if instance['status'] != 'suspended':
                    instance['results'] = preserved
                    self.restore_results(instance,user)
                    instance['sequence'] += 1
                    self.jobs[id] = asyncio.create_task(self.run(instance, user))
                return self.public(instance)
        if len(parts) == 2 and parts[1] == 'events' and request.method == 'GET':
            async def events():
                instance['activeSubscribers'] += 1
                sequence = -1
                try:
                    while id in self.instances:
                        if await request.is_disconnected():
                            break
                        instance['leaseUntil'] = time.time() + 90
                        if sequence != instance['sequence']:
                            sequence = instance['sequence']
                            yield f'id: {sequence}\nevent: update\ndata: {json.dumps(self.public(instance), allow_nan=False)}\n\n'
                        else:
                            yield ': heartbeat\n\n'
                        await asyncio.sleep(2)
                finally:
                    instance['activeSubscribers'] -= 1
            return StreamingResponse(events(), media_type='text/event-stream', headers={'X-Accel-Buffering': 'no'})
        if len(parts) == 2 and parts[1] == 'conversation' and request.method == 'POST':
            from .interactions import submit
            return await submit(self, instance, user, await request.json())
        raise HTTPException(404)

    @staticmethod
    def validate_refresh_overrides(value, entry):
        if not isinstance(value, dict):
            raise HTTPException(422, 'Invalid container settings.')
        # Retained metadata may remain in an imported workspace. It confers no
        # execution authority; refresh policy belongs to the selected owner.
        return {}

    async def run(self, instance, user):
        from .content import run_content
        instance['results'] = {r['id']: {'status': 'unavailable', 'rows': [],
            'error': 'Open the owning agent Phema to resolve this legacy dataset.'}
            for r in instance['entry']['design'].get('dataRequirements', [])}
        instance['status'] = 'partial' if instance['results'] else 'ready'
        instance['sequence'] += 1
        if instance.get('phema'):
            instance['_contentTask'] = asyncio.create_task(run_content(self, instance, user))
            await instance['_contentTask']
            instance['sequence'] += 1
