// The readable name of an operation someone paid for, as its owning agent publishes it. An agent names each pulse with
// its definition's `title` and translates it in the definition's own phemacast:ui catalog, as a Phema names itself; the
// label an agent's quote gave Plaza names the operation that quote priced. The Terminal knows no agent's operations:
// without a label or a title, the pulse name stands.
import {currentLocale} from './i18n.js';
import {resolveUIMessage,validateUIBundle} from './phema-i18n.js';

const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/** A namer over a pulse catalog ({pulses:[{publisherId,operation,title,ui}]}): row ({agentId,pulse,label}) → name. */
export function operationNamer(catalog){
 const agents=new Map();
 for(const pulse of catalog?.pulses||[]){
  if(!agents.has(pulse.publisherId))agents.set(pulse.publisherId,{titles:new Map(),bundles:[]});
  const agent=agents.get(pulse.publisherId);
  if(typeof pulse.title==='string'&&pulse.title.trim())agent.titles.set(pulse.operation,pulse.title);
  if(pulse.ui)try{agent.bundles.push(validateUIBundle(pulse.ui));}catch{}
 }
 return (row={})=>{
  const raw=String(row.pulse||''),label=String(row.label||''),agent=agents.get(row.agentId);
  // Plaza records the pulse name as the label when a quote gave none.
  const key=(label&&label!==raw?label:'')||agent?.titles.get(raw)||raw;
  const bundle=agent?.bundles.find(b=>Object.hasOwn(b.messages,key));
  return {key,raw,bundle:bundle?{version:1,defaultLocale:bundle.defaultLocale,messages:{[key]:bundle.messages[key]}}:null};
 };
}

export const plainOperation=operationNamer(null);

/** The name in a language: the owner's translation, else the name it published. */
export function operationText(name,language=currentLocale()){
 return name.bundle?resolveUIMessage([name.bundle],language,name.key,(_,key)=>key):name.key;
}

/** Markup that follows the Terminal's language: the owner's catalog is scoped to the name (data-phema-ui). */
export function operationHTML(name){
 if(!name.key)return '—';
 const text=esc(operationText(name));
 return name.bundle?`<span data-phema-ui="${esc(JSON.stringify(name.bundle))}"><span data-ui-key="${esc(name.key)}" data-ui-args="[]">${text}</span></span>`:text;
}
