// AI apps that control this Terminal window (mcp_access.py). An AI app on this computer asks to sign in; this page shows
// "<app> wants to control this window" with Allow and Deny, and Terminal settings → AI apps holds the points AI apps
// may spend per day and the approved apps, each with Revoke. The Terminal decides nothing an app does beyond this.
import {ui as html,label,t} from './i18n.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let api,signedIn=()=>false,preferences=()=>({}),approvals=[],loaded=false,available=true,warning='',timer=null,asking=new Set();
// A sign-in opens the AI app's waiting page in a new tab, which hides this one: a hidden window keeps checking, less
// often, and flags its tab title, so the person can find the window that asks.
export const VISIBLE_MS=3000,HIDDEN_MS=15000;
let checked=-Infinity,flagged=null;

const time=value=>value?new Date(value*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):label('Never');
const address=()=>location.origin+'/mcp';

function paint(){
 for(const container of document.querySelectorAll('[data-ai-apps]')){
  const body=container.querySelector('[data-ai-app-list]');
  body.innerHTML=!available?html`<tr><td colspan="3">${label('AI apps can’t connect to this Terminal.')}</td></tr>`
   :approvals.length?approvals.map(a=>html`<tr><td><strong>${esc(a.clientName)}</strong></td><td>${time(a.created)} · ${time(a.lastUsed)}</td><td><button type="button" class="text-button" data-revoke-ai-app="${esc(a.id)}">${label('Revoke')}</button></td></tr>`).join('')
   :html`<tr><td colspan="3">${label(loaded?'No AI app is approved for this window.':'Loading…')}</td></tr>`;
  container.querySelector('[data-ai-app-warning]').textContent=warning;
 }
}

async function load(){
 if(!signedIn()){approvals=[];loaded=true;paint();return;}
 try{approvals=(await api('/api/mcp/approvals')).approvals||[];warning='';}
 catch(error){if(error.status===404)available=false;else warning=error.message;}
 finally{loaded=true;paint();}
}

export function aiAppsHTML(){
 queueMicrotask(()=>load());
 const budget=Number(preferences().aiPointsPerDay||0);
 return html`<section data-ai-apps><p>${label('AI apps on this computer, such as Claude Code or Codex, can read this window once you allow them here.')}</p>
<form class="ai-app-budget" data-ai-app-budget><label>${label('Points AI apps may spend per day')}<input name="points" type="number" min="0" max="1000000" step="1" value="${budget}" required></label><button class="button subtle" type="submit">${label('Save')}</button></form>
<p class="muted">${label('0 means AI apps can use only free actions.')}</p>
<details><summary>${label('How to connect')}</summary><p>${label('Connect an AI app at {0}. It asks you to allow it in this window.',address())}</p><p class="mono">claude mcp add --transport http retis-terminal ${esc(address())}</p></details>
<h3>${label('Approved AI apps')}</h3><table class="scheduled-runs"><thead><tr><th>${label('AI app')}</th><th>${label('Approved · last used')}</th><th></th></tr></thead><tbody data-ai-app-list></tbody></table>
<p data-ai-app-warning role="status"></p></section>`;
}

// --- "<app> wants to control this window": Allow / Deny ------------------------------------------------------------
function prompt(requests,budget){
 let card=document.querySelector('[data-ai-app-request]');
 const open=requests.filter(r=>!asking.has(r.id));
 if(!open.length){card?.remove();return;}
 if(!card){card=document.createElement('div');card.dataset.aiAppRequest='';card.setAttribute('role','alertdialog');
  // In the middle of the window, where the person looks, not a corner they may miss (Alvin, 2026-11-26).
  card.style.cssText='position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:1000;width:min(24rem,calc(100vw - 32px));box-sizing:border-box;padding:16px;background:var(--raised);color:var(--text);border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.35)';
  document.body.append(card);}
 const r=open[0];
 card.innerHTML=html`<p><strong>${label('{0} wants to control this window.',esc(r.clientName))}</strong></p><p class="muted">${label('AI points budget: {0} per day',budget)}</p><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px"><button type="button" class="button subtle" data-ai-app-decision="deny" data-request="${esc(r.id)}">${label('Deny')}</button><button type="button" class="button primary" data-ai-app-decision="allow" data-request="${esc(r.id)}">${label('Allow')}</button></div>`;
}

// "● <app> is waiting for your Allow" in the tab title while this window is hidden and a request waits. The title's own
// translation key steps aside meanwhile (as app.js does for status titles) and comes back unchanged.
function flag(requests){
 const node=document.querySelector('title'),waiting=document.hidden&&requests.find(r=>!asking.has(r.id));
 if(waiting&&!flagged){flagged={title:document.title,key:node?.dataset.uiKey,args:node?.dataset.uiArgs,text:''};if(node){delete node.dataset.uiKey;delete node.dataset.uiArgs;}}
 if(waiting){flagged.text='● '+t('{0} is waiting for your Allow',waiting.clientName||t('An AI app'));if(document.title!==flagged.text)document.title=flagged.text;return;}
 if(!flagged)return;
 const was=flagged;flagged=null;
 if(document.title===was.text)document.title=was.title;
 if(node&&was.key!==undefined){node.dataset.uiKey=was.key;node.dataset.uiArgs=was.args??'[]';}
}

async function watch(now=Date.now()){
 if(!available||!signedIn()){flag([]);return;}
 if(document.hidden&&now-checked<HIDDEN_MS)return;
 checked=now;
 try{const value=await api('/api/mcp/requests');const requests=value.requests||[];prompt(requests,Number(value.aiPointsPerDay||0));flag(requests);}
 catch(error){if(error.status===404){available=false;flag([]);}}
}

export function installAIApps(deps){
 ({api}=deps);if(deps.signedIn)signedIn=deps.signedIn;if(deps.preferences)preferences=deps.preferences;
 document.addEventListener('click',async event=>{
  const revoke=event.target.closest('[data-revoke-ai-app]');
  if(revoke){revoke.disabled=true;
   try{await api('/api/mcp/approvals/'+encodeURIComponent(revoke.dataset.revokeAiApp)+'/revoke',{method:'POST',body:{}});await load();}
   catch(error){warning=error.message;revoke.disabled=false;paint();}
   return;}
  const decision=event.target.closest('[data-ai-app-decision]');
  if(decision){const id=decision.dataset.request;asking.add(id);document.querySelector('[data-ai-app-request]')?.remove();flag([]);
   try{await api('/api/mcp/requests/'+encodeURIComponent(id),{method:'POST',body:{decision:decision.dataset.aiAppDecision}});await load();}
   catch{asking.delete(id);}}
 });
 document.addEventListener('submit',async event=>{
  const form=event.target.closest('[data-ai-app-budget]');if(!form)return;event.preventDefault();
  try{const points=Number(form.elements.points.value);await api('/api/settings',{method:'PUT',body:{aiPointsPerDay:points}});
   const p=preferences();if(p)p.aiPointsPerDay=points;warning=label('Saved.');}
  catch(error){warning=error.message;}
  paint();
 });
 // A sign-in request waits a few minutes: check every 3 s in front, every 15 s hidden, and at once on coming back.
 if(!timer){
  const back=()=>{if(!document.hidden){checked=-Infinity;watch();}};
  document.addEventListener('visibilitychange',back);window.addEventListener('focus',back);
  watch();timer=setInterval(()=>watch(),VISIBLE_MS);
 }
}
