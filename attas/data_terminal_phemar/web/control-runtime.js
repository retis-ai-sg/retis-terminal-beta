/** What every control (`phemacast:control.*`) shares: bindings, styles, value checks, the declarative actions, and the
 * page's registry of controls. Host-installed code; a Phema supplies only data (phemacast/core/controls.py checks it).
 * Actions that reach the Terminal travel as DOM events it handles: `phemacast:control-parameters` (page values) and
 * `phemacast:control-action` (run or refresh a reference, show a message, actions between panels). */
import {VOCABULARY} from './control-vocabulary.js';

export const LIMITS=VOCABULARY.limits;
export const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const TOKENS={background:'--bg',surface:'--surface',raised:'--raised',hover:'--hover',line:'--line',lineSoft:'--line-soft',text:'--text',muted:'--muted',dim:'--dim',accent:'--accent',accentBackground:'--accent-bg',positive:'--green',negative:'--red'};
const SPACING={none:'0',tight:'2px 6px',normal:'4px 8px'};
const SIZES={small:'.85em',normal:'1em',large:'1.15em'};
export const LINK=/^https?:\/\/[^/@\s]+(?:\/\S*)?$/;
export const NAME=/^[A-Za-z][A-Za-z0-9_]{0,63}$/;

/** A JSON pointer's value inside `root`; undefined when the path is missing. */
export function pointer(root,path=''){
 if(path==='')return root;
 let value=root;
 for(const raw of String(path).split('/').slice(1)){
  const key=raw.replace(/~1/g,'/').replace(/~0/g,'~');
  if(value===null||typeof value!=='object'||key==='__proto__'||key==='constructor'||key==='prototype'||!Object.hasOwn(value,key))return undefined;
  value=value[key];
 }
 return value;
}
export const bindingKind=value=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).length===1&&Object.keys(value)[0].startsWith('$')?Object.keys(value)[0]:null;

/** A bound value, resolved against this panel's scope: page values, reference results, other controls' state and the
 * event's details. Bindings this Terminal cannot resolve yet (other panels, agent lists) resolve to undefined. */
export function resolve(value,scope={},depth=0){
 if(depth>12)return undefined;
 const kind=bindingKind(value);
 if(kind){
  const target=value[kind];
  if(kind==='$param')return pointer(scope.parameters||{},target);
  if(kind==='$result'){const ref=typeof target==='string'?{reference:target}:target||{};return pointer((scope.results||{})[ref.reference],ref.path||'');}
  if(kind==='$control')return scope.controlState?.(target?.name,target?.property);
  if(kind==='$event')return pointer(scope.event||{},target);
  // Between panels on this Terminal (link groups and the open Phemas): what the host put in this panel's scope.
  if(kind==='$link')return (scope.links||{})[target];
  if(kind==='$opened')return (scope.opened||{})[target];
  if(kind==='$agents')return (scope.agents||{})[target?.pulse];
  if(kind==='$panels'){const want=target||{};return (scope.panels||[]).filter(p=>['phema','workspace','group'].every(key=>want[key]===undefined||p[key]===want[key]));}
  if(kind==='$panel'){const handle=resolve(target?.panel,scope,depth+1),panel=(scope.panels||[]).find(p=>p.panel===handle);return panel?pointer(panel.parameters||{},target?.param||''):undefined;}
  return undefined;
 }
 if(Array.isArray(value))return value.map(item=>resolve(item,scope,depth+1));
 if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,resolve(v,scope,depth+1)]));
 return value;
}

const ALIGN={Left:'left',Center:'center',Right:'right'},VALIGN={top:'top',middle:'middle',bottom:'bottom'};
/** Inline CSS for a style: theme tokens and fixed sizes only, never a value the document wrote. */
export function css(style={}){
 const out=[];
 if(TOKENS[style.backColor])out.push(`background:var(${TOKENS[style.backColor]})`);
 if(TOKENS[style.foreColor])out.push(`color:var(${TOKENS[style.foreColor]})`);
 const font=style.font||{};
 if(font.family==='mono')out.push('font-family:var(--mono)');else if(font.family==='sans')out.push('font-family:var(--sans)');
 if(SIZES[font.size])out.push('font-size:'+SIZES[font.size]);
 if(font.bold===true)out.push('font-weight:600');
 if(font.italic===true)out.push('font-style:italic');
 const align=/^(top|middle|bottom)(Left|Center|Right)$/.exec(style.alignment||'');
 if(align)out.push('text-align:'+ALIGN[align[2]],'vertical-align:'+VALIGN[align[1]]);
 if(style.wrapMode===true)out.push('white-space:normal');else if(style.wrapMode===false)out.push('white-space:nowrap');
 if(SPACING[style.padding])out.push('padding:'+SPACING[style.padding]);
 if(SPACING[style.margin])out.push('margin:'+SPACING[style.margin]);
 return out.join(';');
}

/** A typed value from what the viewer typed; `error` when it doesn't parse. */
export function parseValue(text,valueType){
 if(valueType==='number'||valueType==='integer'){
  if(String(text).trim()==='')return {value:null};
  const value=Number(String(text).replace(/,/g,''));
  if(!Number.isFinite(value)||(valueType==='integer'&&!Number.isInteger(value)))return {error:valueType==='integer'?'Enter a whole number.':'Enter a number.'};
  return {value};
 }
 if(valueType==='boolean')return {value:text===true||text==='true'};
 if(valueType==='date'&&text!==''&&!/^\d{4}-\d{2}-\d{2}$/.test(text))return {error:'Enter a date as YYYY-MM-DD.'};
 return {value:text};
}
/** The declarative checks; the message to show, or null. */
export function validate(value,rules){
 if(!rules)return null;
 const fail=fallback=>rules.message||fallback;
 const empty=value===null||value===undefined||value===''||(Array.isArray(value)&&!value.length);
 if(rules.required&&empty)return fail('A value is required.');
 if(empty)return null;
 if(typeof value==='number'){if(rules.minimum!==undefined&&value<rules.minimum)return fail('The value is too small.');if(rules.maximum!==undefined&&value>rules.maximum)return fail('The value is too large.');}
 if(typeof value==='string'){if(rules.minLength!==undefined&&value.length<rules.minLength)return fail('The text is too short.');if(rules.maxLength!==undefined&&value.length>rules.maxLength)return fail('The text is too long.');}
 if(Array.isArray(rules.oneOf)&&!rules.oneOf.some(item=>item===value||String(item)===String(value)))return fail('Choose one of the allowed values.');
 return null;
}

/** The actions an event runs, with their bindings resolved against the event; unknown actions are skipped. */
export function eventActions(doc,event,details,scope){
 const handlers=doc.events?.[event];
 if(!Array.isArray(handlers))return [];
 const local={...scope,event:details};
 return handlers.slice(0,LIMITS.actionsPerEvent).filter(action=>Object.hasOwn(VOCABULARY.actions,action?.action)).map(action=>Object.fromEntries(Object.entries(action).map(([k,v])=>[k,k==='action'?v:resolve(v,local)])));
}

/** What one user gesture asks of the Terminal: page values to save (merged, unchanged ones dropped) and other
 * requests, in order. setProperty and clearSelection stay inside the page (`local`). */
export function plan(actions,parameters={}){
 const values={},requests=[],local=[];
 for(const action of actions){
  if(action.action==='setParameter'&&NAME.test(action.name))values[action.name]=action.value===undefined?null:action.value;
  else if(action.action==='runReference'){
   for(const [k,v] of Object.entries(action.parameters||{}))if(NAME.test(k))values[k]=v===undefined?null:v;
   requests.push({kind:'runReference',reference:action.reference});
  }
  else if(action.action==='refresh')requests.push({kind:'refresh',reference:action.reference});
  else if(action.action==='showMessage')requests.push({kind:'message',text:String(action.text??'').slice(0,LIMITS.text),level:['info','success','warning','error'].includes(action.level)?action.level:'info'});
  else if(action.action==='openLink'){if(typeof action.url==='string'&&LINK.test(action.url))requests.push({kind:'link',url:action.url});}
  else if(['setProperty','clearSelection'].includes(action.action))local.push(action);
  // Between panels: the host checks each value again (link-groups.js).
  else if(action.action==='publish'&&NAME.test(action.port))requests.push({kind:'publish',port:action.port,value:action.value});
  else if(action.action==='setPanelParameters'&&typeof action.panel==='string'&&action.values&&typeof action.values==='object')requests.push({kind:'setPanelParameters',panel:action.panel,values:action.values});
  else if(action.action==='openPhema'&&typeof action.phema==='string')requests.push({kind:'openPhema',phema:action.phema,parameters:action.parameters||{},where:action.where||'newPanel',link:action.link||'none',...(action.as?{as:action.as}:{})});
 }
 for(const [key,value] of Object.entries(values))if(JSON.stringify(parameters[key])===JSON.stringify(value))delete values[key];
 return {values,requests,local};
}

// ---- In the page: the registry of controls, local actions and what reaches the Terminal. ------------------------
export const states=new Map();      // window|panel|control name → that control's state (with read(property))
export const overrides=new Map();   // window|control name → properties set by setProperty
export const placeOf=host=>({window:host.closest('[data-browser]')?.dataset.browser||'',panel:host.closest('[data-panel-id]')?.dataset.panelId||''});
export const keyOf=(host,name)=>{const {window,panel}=placeOf(host);return window+'|'+panel+'|'+(name||'');};
export function controlState(window){
 return (name,property)=>{
  for(const [key,state] of states)if(key.startsWith(window+'|')&&key.endsWith('|'+name)&&state.read)return state.read(property);
  return undefined;
 };
}
/** Redraw the surfaces in this window that hold the named control (all of them without a name). */
export function rerender(window,name){
 for(const host of document.querySelectorAll('[data-installed-renderer^="phemacast:control."]'))
  if(placeOf(host).window===window&&host._controlRender&&(!name||host._controlNames?.has(name)))host._controlRender();
}
/** Carry out one gesture's plan: local actions on this page, page values and requests through the Terminal. */
export function apply(host,result){
 const {window}=placeOf(host);
 for(const action of result.local){
  const target=window+'|'+action.control;
  if(action.action==='setProperty'&&action.property!=='type'&&action.property!=='name'){overrides.set(target,{...overrides.get(target),[action.property]:action.value});rerender(window,action.control);}
  if(action.action==='clearSelection'){for(const [key,state] of states)if(key.startsWith(window+'|')&&key.endsWith('|'+action.control))state.clear?.();rerender(window,action.control);}
 }
 if(Object.keys(result.values).length){remember(host);host.dispatchEvent(new CustomEvent('phemacast:control-parameters',{bubbles:true,detail:{values:result.values}}));}
 for(const request of result.requests){
  if(request.kind==='link'){globalThis.open?.(request.url,'_blank','noopener,noreferrer');continue;}
  host.dispatchEvent(new CustomEvent('phemacast:control-action',{bubbles:true,detail:request}));
 }
}
// A saved page value redraws the page; the control the viewer was in gets the focus (and caret) back.
let focus=null;
export function remember(host){
 const active=document.activeElement,control=active?.closest?.('[data-control]');
 if(!control||!host.contains(active))return;
 focus={window:placeOf(host).window,name:control.dataset.control,start:active.selectionStart??null,end:active.selectionEnd??null,at:Date.now()};
}
export function restore(host){
 if(!focus||Date.now()-focus.at>3000||placeOf(host).window!==focus.window)return;
 const target=host.querySelector(`[data-control="${CSS.escape(focus.name)}"]`);if(!target)return;
 const input=target.matches('input,select,textarea,button')?target:target.querySelector('input,select,textarea,button,[tabindex]');
 if(!input)return;
 input.focus({preventScroll:true});
 if(focus.start!==null&&typeof input.setSelectionRange==='function')try{input.setSelectionRange(focus.start,focus.end);}catch{}
 focus=null;
}
