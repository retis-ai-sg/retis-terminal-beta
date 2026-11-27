/** Phemas on one Terminal working together (Terminal controls C4; phemacast/core/ports.py).
 *
 * - Link groups: the viewer puts panels in a group (the colour chip on each panel's title bar). A value a panel sends
 *   through one of its ports reaches every other panel in the group that receives that type. Windows in this browser
 *   pass values over a BroadcastChannel; the Terminal keeps each group's latest values for this account
 *   (/api/link-groups), so a panel that joins a group, or a window opened later, starts from them.
 * - The open Phemas: each window tells the others which panels it holds, with the page values they share, for
 *   `$panels` / `$panel` bindings; setPanelParameters passes values to one of them.
 * Values are data, held to their type and size, never credentials; only the same account's windows take part. */
import {VOCABULARY} from './control-vocabulary.js';
import {terminalWindow} from './terminal-session.js';

const PORTS=VOCABULARY.ports,EXT=PORTS.extension;
export const GROUPS=PORTS.groups;
const NAME=/^[A-Za-z][A-Za-z0-9_]{0,63}$/,SECRET=/password|secret|token|api.?key|credential|cookie|authorization/i;
const DATE=/^\d{4}-\d{2}-\d{2}$/,INTERVAL=/^[1-9][0-9]{0,3}(s|m|h|d|wk|w|mo|y)$/,SYMBOL=/^[A-Za-z0-9^][A-Za-z0-9.^=_:/-]{0,39}$/,AGENT=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$/;
const STALE_MS=60000,ANNOUNCE_MS=20000,SAVE_MS=250;

let host=null,channel=null,groups={},announceTimer=null;
const seen=new Map();        // browser id → its page values as last seen (JSON)
const windows=new Map();     // other window → {at, panels}
const saving=new Map();      // group|type → timer
const windowId=(()=>{try{const kept=sessionStorage.getItem('phemacast-link-window');if(kept)return kept;const made=terminalWindow()||crypto.randomUUID();sessionStorage.setItem('phemacast-link-window',made);return made;}catch{return terminalWindow()||'window';}})();

const secretIn=(value,depth=0)=>depth>8||(Array.isArray(value)?value.some(v=>secretIn(v,depth+1)):value&&typeof value==='object'&&Object.entries(value).some(([k,v])=>SECRET.test(k)||secretIn(v,depth+1)));
const instrument=value=>{if(typeof value==='string')value={symbol:value};if(!value||typeof value!=='object'||!SYMBOL.test(value.symbol||'')||Object.keys(value).some(k=>!['symbol','market'].includes(k)))throw Error('An instrument is {symbol, market?}.');return value;};
/** A value for a port of `type`, checked as phemacast/core/ports.py check_value does; throws when it doesn't fit. */
export function checkValue(type,value){
 const text=JSON.stringify(value);
 if(text===undefined||text.length>PORTS.maxValueBytes)throw Error('A port value is JSON data of at most 32 KB.');
 if(secretIn(value))throw Error('Credentials never travel between panels.');
 switch(type){
  case 'instrument':return instrument(value);
  case 'instruments':if(!Array.isArray(value)||value.length>50)throw Error('At most 50 instruments.');return value.map(instrument);
  case 'date':if(typeof value!=='string'||!DATE.test(value))throw Error('A date is YYYY-MM-DD.');return value;
  case 'dateRange':if(!value||typeof value!=='object'||!DATE.test(value.start||'')||!DATE.test(value.end||'')||value.start>value.end)throw Error('A date range is {start, end}.');return {start:value.start,end:value.end};
  case 'interval':if(typeof value!=='string'||!INTERVAL.test(value))throw Error('An interval is a bar size.');return value;
  case 'text':if(typeof value!=='string'||value.length>2000)throw Error('Text is at most 2,000 characters.');return value;
  case 'number':if(typeof value!=='number'||!Number.isFinite(value))throw Error('Use a number.');return value;
  case 'boolean':if(typeof value!=='boolean')throw Error('Use true or false.');return value;
  case 'agent':if(typeof value!=='string'||!AGENT.test(value))throw Error('An agent is named by its id.');return value;
  case 'rows':if(!value||!Array.isArray(value.fields)||!Array.isArray(value.rows)||value.rows.length>500)throw Error('Rows are {fields, rows}.');return value;
 }
 throw Error('Unknown port type.');
}

export const portsOf=b=>{const ports=b?.customLayout?.composition?.extensions?.[EXT];return ports&&typeof ports==='object'?ports:null;};
const shareOf=(b,name)=>(portsOf(b)?.share||{})[name]||'readWrite';
const pageValue=(values,pointer)=>{let value=values;for(const key of String(pointer).split('/').slice(1)){if(!value||typeof value!=='object'||!Object.hasOwn(value,key))return undefined;value=value[key];}return value;};
/** The receiving ports a sent value reaches in one panel: same type, and the same name too when it has several. */
export function receivers(ports,sender){
 const same=(ports?.subscribes||[]).filter(port=>port.type===sender.type);
 return same.length<=1?same:same.filter(port=>port.name===sender.name);
}
// A received instrument fits the page value it goes to: a page that declares a string takes the symbol, a list of
// strings the symbols (Terminal pages name instruments by symbol); otherwise the value as sent.
export function fitted(b,name,type,value){
 const declared=b?.design?.params?.[name]||{};
 if(type==='instrument'&&declared.type==='string')return value.symbol;
 if(type==='instruments'&&declared.type==='array'&&(declared.items?.type||'string')==='string')return value.map(item=>item.symbol);
 return value;
}
const account=()=>host?.account?.()||null;
const post=message=>{try{channel?.postMessage({...message,account:account()});}catch{}};

/** Join this Terminal window's link groups and its list of open Phemas. */
export function installLinkGroups(options){
 host=options;
 try{channel=new BroadcastChannel('phemacast-link-groups');channel.onmessage=event=>receive(event.data);}catch{channel=null;}
 addEventListener('pagehide',()=>post({kind:'bye',window:windowId}));
 announceTimer=setInterval(()=>{announce();for(const [id,entry] of windows)if(Date.now()-entry.at>STALE_MS)windows.delete(id);},ANNOUNCE_MS);
 post({kind:'hello',window:windowId});
 return {reload};
}
/** The groups' latest values, read again after sign-in or a reload. */
export async function reload(){
 if(!host||!account())return;
 try{const answer=await host.api('/api/link-groups');groups=answer?.groups&&typeof answer.groups==='object'?answer.groups:{};}catch{groups={};}
 announce();
}

function receive(message){
 if(!message||typeof message!=='object'||!account()||message.account!==account())return;
 if(message.kind==='value'&&GROUPS.includes(message.group)){
  let value;try{value=checkValue(message.type,message.value);}catch{return;}
  groups[message.group]={...groups[message.group],[message.type]:{name:message.name,value,at:message.at||Date.now()}};
  deliver(message.group,{type:message.type,name:message.name},value,null);
 }
 else if(message.kind==='panels'&&typeof message.window==='string'&&message.window!==windowId&&Array.isArray(message.panels))windows.set(message.window,{at:Date.now(),panels:message.panels.slice(0,64)});
 else if(message.kind==='hello'&&message.window!==windowId)announce();
 else if(message.kind==='bye')windows.delete(message.window);
 else if(message.kind==='set'&&message.window===windowId){const b=host.allBrowsers().find(x=>x.id===message.browser);if(b)applyValues(b,message.values);}
}

/** Called with the shown workspace's Browsers on every sync: a page value a Browser publishes that changed is sent. */
export function observeLinks(browsers){
 let changed=false;
 for(const b of browsers||[]){
  const now=JSON.stringify(b.parameterValues||{}),before=seen.get(b.id);
  if(before===now)continue;
  seen.set(b.id,now);changed=true;
  if(before===undefined||!b.linkGroup)continue;   // a Browser just opened sends nothing; it receives
  const old=JSON.parse(before);
  for(const port of portsOf(b)?.publishes||[]){
   const pointer=port.from?.$param;if(typeof pointer!=='string')continue;
   const next=pageValue(b.parameterValues||{},pointer);
   if(next===undefined||JSON.stringify(next)===JSON.stringify(pageValue(old,pointer)))continue;
   send(b,port,next);
  }
 }
 if(changed)scheduleAnnounce();
}

/** Send one value from a Browser's port to its group: this window at once, the others over the channel, the Terminal
 * keeps it as the group's latest (writes merged within 250 ms). A value the group already holds is not sent again. */
export function send(b,port,raw){
 const group=b?.linkGroup;if(!GROUPS.includes(group)||!port||!PORTS.types.includes(port.type))return false;
 let value;try{value=checkValue(port.type,raw);}catch(error){host?.notice?.(error.message);return false;}
 if(JSON.stringify(groups[group]?.[port.type]?.value)===JSON.stringify(value))return false;
 const at=Date.now();
 groups[group]={...groups[group],[port.type]:{name:port.name,value,at}};
 deliver(group,port,value,b.id);
 post({kind:'value',window:windowId,group,type:port.type,name:port.name,value,at});
 const key=group+'|'+port.type;clearTimeout(saving.get(key));
 saving.set(key,setTimeout(()=>{saving.delete(key);host?.api('/api/link-groups/'+group,{method:'PUT',body:{type:port.type,name:port.name,value:groups[group][port.type].value}}).catch(()=>{});},SAVE_MS));
 return true;
}
/** The `publish` action: a control sends a value through one of its Phema's ports. */
export function publishPort(b,name,value){
 const port=(portsOf(b)?.publishes||[]).find(p=>p.name===name);
 if(!port){host?.notice?.(host.text('This page has no port named {0}.',name));return false;}
 return send(b,port,value);
}

// A value reaches the Browsers of this window in the group (hidden workspaces too: they show it when opened).
function deliver(group,sender,value,origin){
 for(const b of host.allBrowsers()){
  if(b.linkGroup!==group||b.id===origin)continue;
  const values={};
  for(const port of receivers(portsOf(b),sender)){const name=String(port.to).split('/')[1];if(NAME.test(name)&&shareOf(b,name)==='readWrite')values[name]=fitted(b,name,sender.type,value);}
  if(Object.keys(values).length)applyValues(b,values,{quiet:true});
 }
}
/** Page values set on a Browser from outside it (a link group or another Phema): shared ones only, unchanged ones
 * skipped; the Browser re-runs with them as when the viewer changes them. */
function applyValues(b,values,{quiet=false}={}){
 if(!values||typeof values!=='object')return false;
 const next={...(b.parameterValues||{})};let changed=false;
 for(const [name,value] of Object.entries(values).slice(0,64)){
  if(!NAME.test(name)||shareOf(b,name)!=='readWrite'||secretIn(value)||JSON.stringify(value).length>PORTS.maxValueBytes)continue;
  if(JSON.stringify(next[name])!==JSON.stringify(value)){next[name]=structuredClone(value);changed=true;}
 }
 if(!changed)return false;
 b.parameterValues=next;
 if(quiet)seen.set(b.id,JSON.stringify(next));   // a received value is not sent on again
 host.changed(b);
 return true;
}

/** The viewer moves a Browser into a group (or out of all of them); it takes the group's latest values. */
export function joinGroup(b,group){
 b.linkGroup=GROUPS.includes(group)?group:null;
 if(b.linkGroup){
  const values={};
  for(const [type,held] of Object.entries(groups[b.linkGroup]||{}))
   for(const port of receivers(portsOf(b),{type,name:held.name})){const name=String(port.to).split('/')[1];if(NAME.test(name)&&shareOf(b,name)==='readWrite')values[name]=fitted(b,name,type,held.value);}
  if(!applyValues(b,values,{quiet:true}))host.changed(b);
 }else host.changed(b);
 scheduleAnnounce();
}
export const nextGroup=group=>{const i=GROUPS.indexOf(group);return i<0?GROUPS[0]:i===GROUPS.length-1?null:GROUPS[i+1];};

// ---- The list of open Phemas, across this account's windows in this browser. ---------------------------------
function panelsHere(){
 return host.allBrowsers().slice(0,64).map(b=>{
  const ports=portsOf(b),values={};
  for(const [name,value] of Object.entries(b.parameterValues||{}))if(shareOf(b,name)!=='none')values[name]=value;
  return {panel:windowId+'|'+b.id,title:String(b.customLayout?.name||b.ticker||'Browser').slice(0,120),phema:b.customLayout?.id||null,
   workspace:String(host.workspaceName(b)||'').slice(0,80),window:windowId,group:b.linkGroup||null,parameters:values,
   accepts:Object.keys(b.design?.params||{}).filter(name=>shareOf(b,name)==='readWrite').slice(0,64)};
 });
}
function announce(){if(host&&account())post({kind:'panels',window:windowId,panels:panelsHere()});}
function scheduleAnnounce(){clearTimeout(scheduleAnnounce.timer);scheduleAnnounce.timer=setTimeout(announce,300);}
/** Every open Phema this account has in this browser's Terminal windows (for `$panels`). */
export function openPanels(){
 const rows=host?panelsHere():[];
 for(const [id,entry] of windows)if(Date.now()-entry.at<=STALE_MS)rows.push(...entry.panels.filter(p=>p&&typeof p.panel==='string'&&p.window===id));
 return rows.slice(0,256);
}
/** The `setPanelParameters` action: values for another open Phema, here or in another window. */
export function setPanelParameters(handle,values){
 const [win,id]=String(handle||'').split('|');
 if(!win||!id||!values||typeof values!=='object')return false;
 if(win===windowId){const b=host.allBrowsers().find(x=>x.id===id);return b?applyValues(b,values):false;}
 if(!windows.has(win)){host?.notice?.(host.text('That panel is no longer open.'));return false;}
 post({kind:'set',window:win,browser:id,values});
 return true;
}

/** What a control on this Browser may read: its subscribed ports' group values ($link), the open Phemas ($panels,
 * $panel) and the panels it opened ($opened). */
export function linkScope(b){
 const links={};
 for(const port of portsOf(b)?.subscribes||[]){const held=b.linkGroup?groups[b.linkGroup]?.[port.type]:null;if(held)links[port.name]=held.value;}
 return {links,panels:openPanels(),opened:b?.opened&&typeof b.opened==='object'?b.opened:{}};
}
export const thisWindow=()=>windowId;

/** The group chip on a Browser's title bar. */
export function linkChipHTML(b,{esc,attribute,label}){
 const group=GROUPS.includes(b.linkGroup)?b.linkGroup:null;
 const name=group?{red:'Red',amber:'Amber',green:'Green',teal:'Teal',blue:'Blue',purple:'Purple'}[group]:'Not linked';
 return `<button class="icon-button link-chip" data-action="link-group" data-id="${esc(b.id)}" ${attribute('title','Link group: {0}',{uiMessage:name,args:[]})} ${attribute('aria-label','Link group: {0}',{uiMessage:name,args:[]})}><span class="link-dot" data-link="${group||'none'}"></span></button>`;
}

/** The other open Phemas as one Browser's agent views see them (never that Browser itself); the composition channel
 * lets a view use this only after the viewer allows it in the Phema's permission review. */
export function otherPanelsFor(browserId){
 const self=windowId+'|'+browserId,others=()=>openPanels().filter(p=>p.panel!==self);
 return {
  list:()=>others().map(({panel,title,phema,workspace,group,parameters,accepts})=>({panel,title,phema,workspace,group,parameters,accepts})),
  read:handle=>others().find(p=>p.panel===handle)||null,
  set:(handle,values)=>handle!==self&&setPanelParameters(handle,values),
 };
}
