"""One current Plaza connection decision for Phemas whose links are pulse calls."""
import sys
import time
from phemacast.core.composition import composition,walk_compositions,reference_paths
from phemacast.core.composition_permissions import fingerprint


OWNER='phemacast:owner'
# How long a Phema whose agent Plaza does not list or could not evaluate retries before asking for approval.
UNCONFIRMED_GRACE=120
# A layout's requests wait for its trust check; one that takes this long is written to terminal.log.
SLOW_CHECK=1.0


async def owner_accepted(phema,rows,user,authority):
    """The Phema's owner, as Plaza decides it for this viewer now.

    A Phema's own owner record (stamp version 2) is signed by Plaza for the
    account that owns it; Plaza says whether it is genuine and whether this
    viewer trusts that account now: their own, the Plaza owner for an approved
    Terminal, or an account they trust. The record must name this Phema. Older
    stamps (version 1) are proved by an agent the owner registered.
    """
    stamp=composition(phema).get('extensions',{}).get(OWNER) or {}
    if stamp.get('version')!=2:return owner_trusted(phema,rows,user['id'])
    record=stamp.get('record')
    if not isinstance(record,dict) or record.get('subject')!=phema.get('id'):return False
    try:decision=await authority.owner(user['token'],record)
    except Exception as exc:
        # An unanswered check never trusts. Plaza refusing is a 'no'; Plaza not answering is None, not a decision.
        return False if getattr(exc,'status_code',500)<500 else None
    return decision.get('valid') is True and decision.get('trusted') is True and decision.get('account')==record.get('account')


def owner_trusted(phema,rows,viewer):
    """The Phema's own owner is the viewer, or an account Plaza trusts for them.

    An App Consultant names the owner in the composition, with an agent whose
    Plaza-verified registrant is that account; the claim counts only when that
    agent's decision for this viewer says so. The name survives the Terminal's
    entry round trip, which resets the Phema's top-level owner. A Phema naming
    the viewer as owner gets no more than before: each agent it calls is still
    checked.
    """
    stamp=composition(phema).get('extensions',{}).get(OWNER) or {}
    account=stamp.get('account') if stamp.get('version')==1 else None
    if viewer and (account==viewer or not account and phema.get('owner')==viewer):return True
    if not account:return False
    matches=[row for row in rows if row['id']==stamp.get('agent')]
    return (len(matches)==1 and matches[0].get('_plazaOwner')==account
            and matches[0].get('_plazaTrusted') is True and matches[0].get('_plazaViewer')==viewer)


def local_agents(network):
    """Agent ids of the local resources running on this computer now.

    A program on this computer is never on Plaza: being on this computer is its trust, and
    `Network.require_trusted` checks it is still running on every call.
    """
    clients=getattr(network,'local_clients',None)
    return {'local-'+row['id'] for row in clients.discovery.resources()} if clients else set()


# The agent id of every program on this computer: 'local-' and the id it announces (phemacast/network/configure.py).
LOCAL_RESOURCE='local-resource-'


def stopped_local(network,agents):
    """{agent id: what to do} for the programs on this computer among `agents` that discovery does not list now.

    Plaza never lists a program on this computer, so one that stopped is not Plaza's to retry or refuse: its panels say
    it is not answering, by the name this Terminal last saw (local_resources.not_answering), until it runs again. A
    Terminal that uses no local resources leaves such an id to Plaza, as before.
    """
    if not getattr(network,'local_clients',None):return {}
    from .local_resources import not_answering
    running=local_agents(network)
    return {agent:not_answering(network,agent) for agent in sorted(agents)
            if isinstance(agent,str) and agent.startswith(LOCAL_RESOURCE) and agent not in running}


def behaviour(phema):
    """What a Phema shows and calls: its identity, inputs and composition, without envelope fields.

    A reopened Browser keeps a trimmed copy that drops Plaza envelope fields (address, tags, empty section
    descriptions); none of them changes what the Phema shows or calls.
    """
    from prompits.core.capabilities import digest
    keys=('id','name','description','owner','input_schema','resolution_mode')
    return digest({**{k:phema.get(k) for k in keys},
                   'content':[section.get('content') for section in phema.get('sections') or [] if isinstance(section,dict)]})


async def bundled(network,user,phema):
    """The Phema is one this Terminal package ships (`seed_phemas`), as this computer's local resources bind it.

    A bundled Phema has no owner record: it comes with the Terminal the viewer runs, so it counts as their own.
    It must match the shipped definition exactly; any change makes it an ordinary Phema again.
    """
    from phemacast.core.composition import validate_composition
    from .phema_library import seeds
    from .local_view_needs import bound
    directory=await network.directory(user.get('token','')) if getattr(network,'local_clients',None) else []
    target=behaviour(phema)
    for seed in seeds():
        try:candidate=validate_composition(bound(seed['phema'],directory))
        except (ValueError,TypeError,KeyError):continue
        if behaviour(candidate)==target:return True
    return False


async def component_pages(network,phema,agents):
    """(exact, newer): what the local resources in `agents` ship now (their descriptors' Phemas), as they serve them.

    `exact` is True when one ships this Phema exactly. A component's own page, such as Retis MAS Manager's, counts as
    the viewer's own: it comes from a program the viewer runs on this computer. Any change makes it an ordinary Phema
    again. Otherwise `newer` names the component that ships another revision of the same page (the same Phema id),
    for the viewer to take: {'name', 'key' (its key in this Terminal's Phema library), 'revision'}. A window keeps its
    copy of a page when the component updates, so an older copy is no longer the component's page.
    """
    clients=getattr(network,'local_clients',None)
    if not clients:return False,None
    target,newer=behaviour(phema),None
    names={row['id']:row.get('name') for row in clients.discovery.resources()}
    for agent in sorted(agents):
        local_id=agent.removeprefix('local-')
        try:described=await clients.describe(local_id)
        except Exception:continue
        for item in described.get('phemas') or []:
            try:value=(await clients.phema(local_id,item['id']))['phema']
            except Exception:continue
            if behaviour(value)==target:return True,None
            if newer is None and isinstance(phema.get('id'),str) and value.get('id')==phema['id'] and isinstance(item.get('id'),str):
                try:revision=max(1,int(item.get('revision') or 1))
                except (TypeError,ValueError):revision=1
                name=names.get(local_id)
                newer={'name':name.strip()[:80] if isinstance(name,str) else '','key':'local:'+item['id'],'revision':revision}
    return False,newer


async def shipped(network,phema,agents):
    """The Phema is exactly one that a local resource it calls ships, as that resource serves it now."""
    return (await component_pages(network,phema,agents))[0]


class NativeTrust:
    def __init__(self,network):
        self.network=network
        # A 'not trusted' answer is remembered for 10 seconds per viewer, window and Phema.
        self.declined={}
        # When Plaza first could not confirm an agent of a Phema, per viewer, window and Phema.
        self.waiting={}
        self.logged={}
        # The refusal last written to terminal.log for each viewer, window and Phema: written once until it changes.
        self.said={}
        # A newer copy of a refused page that a component on this computer ships, kept as long as the refusal.
        self.newer={}

    @staticmethod
    def unconfirmed(user):
        # Not trusted, and not remembered either: the next request asks Plaza again.
        user['_nativeTrustUnconfirmed']=True
        return user

    def decline(self,key,user,newer=None):
        if len(self.declined)>=256:
            self.declined={k:v for k,v in self.declined.items() if v>time.time()}
            self.newer={k:v for k,v in self.newer.items() if k in self.declined}
        self.declined[key]=time.time()+10
        user['_nativeTrustNewer']=newer or None
        if newer:self.newer[key]=newer
        else:self.newer.pop(key,None)
        return user

    def pending(self,key,user):
        """Plaza does not list an agent now, or could not evaluate it: not a 'no'.

        After Plaza or this Terminal was briefly unreachable, an agent is listed again only with its next
        heartbeat. Until then the layout retries; one still unconfirmed after UNCONFIRMED_GRACE of checks asks for
        approval, and keeps asking until Plaza lists the agent again. A layout not checked for 30 seconds starts over.
        """
        now=time.time()
        if len(self.waiting)>=256:self.waiting={k:v for k,v in self.waiting.items() if now-v[1]<30}
        first,last=self.waiting.get(key,(now,now))
        if now-last>30:first=now
        self.waiting[key]=(first,now)
        return None if now-first>=UNCONFIRMED_GRACE else self.unconfirmed(user)

    def log(self,key,phema,outcome,detail):
        """One terminal.log line per outcome a minute for each viewer, window and Phema, so a report shows it.

        A refusal is written once until the answer changes: an approved layout whose agents Plaza
        does not trust is checked on every request, and its refusal said nothing new each minute."""
        now=time.time()
        if outcome=='declined':
            if self.said.get(key)==detail:return
            if len(self.said)>=512:self.said={}
            self.said[key]=detail
        elif outcome in ('unlisted','unanswered','not-answering'):self.said.pop(key,None)
        if outcome!='declined' and now-self.logged.get((key,outcome),0)<60:return
        if len(self.logged)>=512:self.logged={k:v for k,v in self.logged.items() if now-v<60}
        self.logged[(key,outcome)]=now
        name=str((phema or {}).get('name') or (phema or {}).get('id') or 'layout')[:120]
        level='INFO:    ' if outcome=='declined' else 'WARNING: '
        print(time.strftime('%Y-%m-%d %H:%M:%S%z')+' '+level+' Plaza trust: '+name+' — '+detail,file=sys.stderr,flush=True)

    async def apply(self,user,phema,*,force=False):
        """Plaza's current decision for this viewer and Phema. Requests wait for it, so a slow one is logged."""
        started,steps=time.monotonic(),{}
        try:return await self._check(user,phema,force,steps)
        finally:
            took=time.monotonic()-started
            if phema and took>=SLOW_CHECK:self.slow(user,phema,took,steps)

    def slow(self,user,phema,took,steps):
        """One terminal.log line a minute per viewer, window and Phema: how long Plaza's answers took."""
        key=(user['id'],user.get('terminalWindow',''),fingerprint(phema))
        parts=[name+' '+format(steps[step],'.1f')+' s' for step,name in (('owner','owner check'),('agents','agent check')) if step in steps]
        self.log(key,phema,'slow','checking Plaza before its requests took '+format(took,'.1f')+' s'
                 +(' ('+', '.join(parts)+')' if parts else '')+'; the requests waited for it.')

    async def _check(self,user,phema,force,steps):
        proof=user.get('_nativeTrust') or {}
        if not force and phema and proof.get('actor')==user['id'] and proof.get('window')==user.get('terminalWindow','') and proof.get('fingerprint')==fingerprint(phema) and proof.get('expires',0)>time.time():return user
        user['_nativeTrust']=None
        user.pop('_nativeTrustUnconfirmed',None)
        # Set, never removed: a browser process merges each call's viewer into the one it keeps.
        user['_nativeTrustNewer']=None
        # The same: the programs on this computer the Phema calls that are not answering (stopped_local).
        user['_nativeTrustNotAnswering']=None
        if not phema:return user
        key=(user['id'],user.get('terminalWindow',''),fingerprint(phema))
        if not force and self.declined.get(key,0)>time.time():
            if self.newer.get(key):user['_nativeTrustNewer']=self.newer[key]
            return user
        refs=[]
        for _,current in walk_compositions(phema):
            node=composition(current)
            if node.get('presentation',{}).get('document',{}).get('design',{}).get('dataRequirements'):return user
            refs.extend(reference_paths(current).values())
        # A panel calling a program on this computer that stopped says so, also in a layout the viewer approved.
        stopped=stopped_local(self.network,{a for r in refs if isinstance(a:=r['target'].get('agentId'),str)})
        if stopped:user['_nativeTrustNotAnswering']=stopped
        # Plaza's current decision covers every pulse call, operation-bound or ordinary.
        if not refs or any(r.get('kind')!='pulse' for r in refs):return user
        if stopped:
            # Not Plaza's to decide, so Plaza is not asked, and not a 'no': nothing is remembered, and the first check
            # after the program answers again decides as usual.
            self.declined.pop(key,None);self.waiting.pop(key,None);self.newer.pop(key,None)
            self.log(key,phema,'not-answering','the program on this computer it calls is not answering ('+', '.join(stopped)
                     +'); its panels say to start it again in Retis MAS Manager. Plaza is not asked: it never lists programs on this computer.')
            return user
        from prompits.core.plaza_directory_trust import PlazaDirectoryTrust
        # The Terminal's shared lookup reuses each account's Plaza answer for 10 seconds.
        authority=getattr(self.network,'plaza_trust',None) or PlazaDirectoryTrust(self.network.plaza,self.network.client)
        # A Phema's own owner record is one small question to Plaza. An owner this
        # viewer does not trust declines before the whole directory is read, so its
        # panels ask for approval at once instead of first appearing to load.
        recorded=(composition(phema).get('extensions',{}).get(OWNER) or {}).get('version')==2
        if recorded:
            began=time.monotonic()
            try:accepted=await owner_accepted(phema,(),user,authority)
            finally:steps['owner']=time.monotonic()-began
            if accepted is None:
                self.log(key,phema,'unanswered','Plaza did not answer the owner check; retrying.')
                return self.unconfirmed(user)
            if not accepted:
                self.log(key,phema,'declined','Plaza does not trust its owner for this account; it asks for approval.')
                return self.decline(key,user)
        # A local resource on this computer is trusted by being here; Plaza decides every other agent.
        local=local_agents(self.network)
        # An agent the viewer chooses ({"$param": …}) is checked when the reference runs (require_trusted).
        agents=sorted({a for r in refs if isinstance(a:=r['target'].get('agentId'),str)}-local)
        # Only an older owner stamp (version 1) is proved by an agent Plaza lists.
        stamped=(composition(phema).get('extensions',{}).get(OWNER) or {}).get('version')==1
        began=time.monotonic()
        try:
            try:rows=await authority.decisions(user['token']) if agents or stamped else []
            finally:steps['agents']=time.monotonic()-began
        except Exception as exc:
            if getattr(exc,'status_code',500)<500:raise
            self.log(key,phema,'unanswered','Plaza did not answer the agent check; retrying.')
            return self.unconfirmed(user)
        for pub in agents:
            matches=[row for row in rows if row['id']==pub]
            # Plaza not listing an agent now, or not able to evaluate it, is not Plaza saying no.
            if not matches or len(matches)==1 and matches[0].get('_plazaEvaluated') is False:
                if self.pending(key,user) is not None:
                    self.log(key,phema,'unlisted','Plaza '+('does not list agent ' if not matches else 'could not check agent ')+pub+' now; retrying.')
                    return user
                self.log(key,phema,'declined','Plaza still '+('does not list agent ' if not matches else 'could not check agent ')+pub+'; it asks for approval.')
                return self.decline(key,user)
            if (len(matches)!=1 or matches[0].get('_plazaTrusted') is not True
                    or matches[0].get('_plazaViewer') != user['id']):
                self.waiting.pop(key,None)
                self.log(key,phema,'declined','Plaza does not trust agent '+pub+' for this account; it asks for approval.')
                return self.decline(key,user)
        if not recorded and not owner_trusted(phema,rows,user['id']) and not await bundled(self.network,user,phema):
            # The pages of the local resources it calls; a link whose agent the viewer chooses may reach any of them.
            named={a for r in refs if isinstance(a:=r['target'].get('agentId'),str)}
            chosen=any(not isinstance(r['target'].get('agentId'),str) for r in refs)
            exact,newer=await component_pages(self.network,phema,local&named|(local if chosen else set()))
            if not exact:
                self.log(key,phema,'declined','an earlier version of the page '+(newer['name'] or 'a program on this computer')
                         +' ships now; it asks for approval or an update.' if newer else
                         'Plaza does not trust its owner for this account; it asks for approval.')
                return self.decline(key,user,newer)
        self.declined.pop(key,None);self.waiting.pop(key,None);self.said.pop(key,None);self.newer.pop(key,None)
        user['_nativeTrust']={'actor':user['id'],'window':user.get('terminalWindow',''),
                              'fingerprint':fingerprint(phema),'expires':time.time()+15}
        return user
