import './agent-view-renderer.js';
import {submitOperationForm,mountOperationRecovery,formInputs} from './neutral-operation-form.js';
import {reloadBrowserPhema as reloadPhemaOnly} from './browser-reload.js';
import {openPhemaPermissions} from './phema-permissions.js';
import './local-resources.js';
import {chatForm,selectTarget,parseArguments,targetKey} from './pulse-chat.js';
import {normalizeContentOverrides} from './content-policies.js';
import {requestFailure,NOT_APPROVED,NOT_ANSWERING} from './failure-messages.js';
import {noteSignedOut,clearSignedOut} from './window-signed-out.js';
import {installRendererModules} from './composition-renderers.js';
import {ui as uiHTML,label,message,t,configureLocale,languageSettingsHTML,setUIText,clearUIText,attribute,setUIAttribute,validLocale,applyUI,currentLocale} from './i18n.js';
import {entryToPhema,phemaToEntry,browserCapabilities,hydratePhemaPayload,setBrowserAdvertisement} from './phema-transfer.js';
import {contentPanel,mountContent,openContentSnapshots,openContentPolicy} from './phema-browser.js';
import {screenshot} from './workspace-previews.js';
import {normalizeFieldBindings} from './field-bindings.js';
import {applyDisplayTimezone,displayTime,displayDateTime,displayTimeTitle,timezoneSettingsHTML} from './time-display.js';
import {applyMarketAppearance,marketSettingsHTML,MARKET_DEFAULTS,valueDirection} from './market-appearance.js';
import {applyDisplayFormat,displayFormatSettingsHTML,displayFormatValues} from './display-format.js';
import {normalizeRefreshOverrides,refreshPolicy,refreshLabel,refreshFields,refreshMessage,refreshTooltip} from './block-refresh.js';
import {browserDesign} from './browser-instruments.js';
import {layoutKind} from './layout-library.js';
import {hostedPath,providerOrigin} from './host-context.js';
import {terminalHeaders,terminalWindow,terminalURL,allowWindowHandover,onWindowHandedOver} from './terminal-session.js';
import {watchBrowserInstance} from './browser-updates.js';
import {openingLoad,permissionReferences} from './open-refresh.js';
import {normalizeMessages,normalizeDiscussionDrafts,normalizeInteractionDrafts} from './workspace-storage.js';
import {setPulseCatalog,setCatalogError} from './plaza-pulses.js';
import {sourceSettingsHTML,installSourceSettings} from './source-settings.js';
import {pointsRowsHTML,openPointsHistory,spendingRows} from './points-history.js';
import {operationNamer} from './operation-names.js';
import {scheduledRunsHTML,installScheduledRuns} from './scheduled-runs.js';
import {aiAppsHTML,installAIApps} from './ai-apps.js';
import {workspaceHistorySettingsHTML,workspaceHistoryValues} from './workspace-history.js';
import {agentTrustHTML,installAgentTrust} from './agent-trust.js';
import {watchRefresh,failedRefreshes} from './refresh-outcome.js';
import {observeLinks,publishPort,setPanelParameters} from './link-groups.js';
import {configureAgentChoices} from './agent-choices.js';
import {waitForPlaza} from './plaza-unreachable.js';
export const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
import './terminal-connection.js';
import './window-signin.js';
import {terminalStopped,unreachable,terminalPresence,onTerminalPresence,decideRestart,presenceLauncher,terminalReplaced,windowMoved,movedText,movedMessage,restartedMessage} from './terminal-presence.js';
export const runtime={user:null,plaza:{},consultants:[],kind:'data-terminal',catalog:{publishers:[],pulses:[]},settings:{preferences:{},connections:[]}};
export async function api(path, options={}) {
  const requestedBy=runtime.user?.id;
  if(options.body?.entry && (/^\/api\/instances(?:\/|$)/.test(path))){
    const {entry,...body}=options.body;
    options={...options,body:{...body,phema:entryToPhema(entry),capabilities:browserCapabilities()}};
  }
  // This tab gave its window to a newer tab after its Terminal restarted (terminal-session.js): it sends nothing more.
  if(terminalPresence()==='moved'){const error=new Error(movedText(runtime.launcherApp));error.status=0;error.windowMoved=true;throw error;}
  let response;
  // No answer at all means the Terminal stopped: say that in the tab's language, never the browser's "Failed to fetch".
  try{response=await fetch(path,{credentials:'same-origin',...options,headers:terminalHeaders({'Content-Type':'application/json','X-Phemacast-Model-Contract':'model-requirement/1',...options.headers}),body:options.body===undefined?undefined:JSON.stringify(options.body)});}
  catch(error){if(unreachable(error))throw terminalStopped(error);throw error;}
  // Every answer to a signed-in window carries its account's points as Plaza last reported them (top bar).
  const reported=response.headers?.get?.('X-Plaza-Points');
  if(reported!=null&&requestedBy&&runtime.user?.id===requestedBy)notePoints(Number(reported),Number(response.headers.get('X-Plaza-Points-At'))||0);
  const body=await response.json();
  if(response.ok&&requestedBy&&/\/api\/instances(?:\/|\?|$)/.test(path))notePaidResults(body);
  // A guest request can finish after sign-in. It must not discard the newly
  // adopted account or restart its document.
  // The reloaded page is a signed-out window; it says it was signed out (window-signed-out.js).
  if(response.status===401&&requestedBy&&runtime.user?.id===requestedBy){runtime.user=null;noteSignedOut(body.detail);location.reload();}
  if(!response.ok){const detail=typeof body.detail==='string'?body.detail:body.detail?.message||JSON.stringify(body.detail||body);const error=new Error(requestFailure(detail));error.status=response.status;error.detail=detail;throw error;}
  return hydratePhemaPayload(body);
}

// Sign-in needs this computer's user: the printed address carries the proof (terminal-session.js).
function localAccessNotice(){
  if(typeof document==='undefined'||document.querySelector('[data-local-access-notice]'))return;
  const note=document.createElement('p');note.setAttribute('role','alert');note.className='local-access-notice';note.dataset.localAccessNotice='';
  // Started by an app (Retis Terminal): its icon's menu opens the Terminal; there is no terminal.py.
  if(runtime.launcherApp)setUIText(note,'To sign in, open this Terminal from the {0} icon\'s menu: choose Open.',runtime.launcherApp);
  else setUIText(note,'To sign in, open this Terminal from the address that "python3 terminal.py up" printed, or run "python3 terminal.py open".');
  document.body.prepend(note);
}

// The account's language comes first; while Plaza can't confirm the account, the language this window's
// account last chose; before anyone signs in, the installation's language.
function applyLocale(){
  const installation=runtime.installationLanguage||{};
  configureLocale({scope:'terminal:'+new URL(runtime.plaza.url||location.origin).origin+':'+(runtime.user?.id||'guest')+':'+terminalWindow(),
   saved:runtime.settings.preferences?.uiLanguage||runtime.plazaUnreachable?.uiLanguage||installation.value,
   onSave:runtime.user?async value=>{await api('/api/settings',{method:'PUT',body:{uiLanguage:value}});runtime.settings.preferences.uiLanguage=value;}
    :installation.canChoose?async value=>{await api('/api/installation-language',{method:'PUT',body:{uiLanguage:value}});installation.value=value;}:null});
}
export async function connect({requireUser=false}={}) {
  const request=requireUser?(path,options={})=>api(path,{...options,signal:AbortSignal.timeout(10000)}):api;
  try {
    const companion=/\/(?:app-consultant|producer-browser|strategy-consultant)\.html$/.test(location.pathname);
    if(terminalWindow()&&!companion)await request('/api/auth/window-session',{method:'POST',body:{}}).catch(()=>{});
    const bootstrap=await request('/api/bootstrap?discovery=background');
    if(requireUser&&!bootstrap.user)throw new Error('Sign-in status could not be confirmed. Please retry.');
    Object.assign(runtime,bootstrap);presenceLauncher(runtime.launcherApp);
    if(runtime.user)clearSignedOut();
    if(bootstrap.localAccess==='required')localAccessNotice();
    // A signed-in window whose Plaza can't be reached waits for it in its account's language, instead of starting signed out.
    if(!requireUser&&bootstrap.plazaUnreachable?.windowSignedIn){applyLocale();await waitForPlaza(plazaHost()||'Plaza');}
    const rendererFailures=runtime.user?await installRendererModules(request):[],advertised=await request('/api/capabilities');
    advertised.capabilities=advertised.capabilities.filter(c=>!rendererFailures.some(f=>f.id===c.id));
    setBrowserAdvertisement(advertised);
    if(runtime.user)runtime.settings=await request('/api/settings');
    delete runtime.error;
  } catch(error) {runtime.error=error.message;if(requireUser)throw error;}
  applyLocale();
  applyMarketAppearance(runtime.settings.preferences?.marketAppearance);
  applyDisplayTimezone(runtime.settings.preferences?.displayTimezone);
  applyDisplayFormat(runtime.settings.preferences?.displayFormat);
  refreshDiscovery();
  watchRegistration();
  watchApproval();
  return runtime;
}
// Sign-in waits only so long for Plaza to approve the account for this Terminal. When the approval comes back after
// the window loaded, the window catches up: its Plaza account panel, its agents, and any Data Browser it could not
// open before.
let approvalWatch=0;
function watchApproval(){
 if(approvalWatch||!runtime.user||!runtime.plaza.delegatedLogin||runtime.plaza.trusted||typeof document==='undefined')return;
 const started=Date.now();
 const tick=async()=>{
  approvalWatch=0;
  if(!runtime.user||runtime.plaza.trusted||await checkApproval())return;
  // Every few seconds at first, then every half minute while the Plaza owner decides.
  approvalWatch=setTimeout(tick,Date.now()-started<60000?3000:30000);
 };
 approvalWatch=setTimeout(tick,3000);
}
async function checkApproval(){
 try{
  const state=await api('/api/auth/connect/status');
  if(['approved','signed-in'].includes(state.status)&&!state.blocked&&!state.offline&&!state.refused){approvedNow();return true;}
 }catch{}
 return false;
}
function approvedNow(){
 if(!runtime.plaza.trusted){
  runtime.plaza.trusted=true;
  document.dispatchEvent(new CustomEvent('connected:settings'));
  refreshDiscovery();
 }
 reopenRefused();
}
if(typeof document!=='undefined')document.addEventListener('plaza-access:approved',()=>{if(runtime.user)approvedNow();});
// A Data Browser refused because its account had not approved this Terminal yet opens again.
function reopenRefused(){
 let any=false;
 for(const entry of nodes.values())if(entry?.notApproved&&!entry.remoteId&&!entry.cancelled){entry.signature=null;entry.designSignature=null;any=true;}
 if(any&&runtime.user)syncBrowsers(latest,currentWorkspace,rendering);
}
// Until this window's Plaza lists the Terminal, the top bar checks every few seconds and turns Connected without a reload.
let registrationWatch=0;
function watchRegistration(){
 if(registrationWatch||runtime.plaza.localOnly||runtime.plaza.registered||!runtime.plaza.url||typeof document==='undefined')return;
 registrationWatch=setInterval(async()=>{
  try{
   const response=await fetch('/health',{credentials:'same-origin',cache:'no-store',headers:terminalHeaders()});if(!response.ok)return;
   const health=await response.json();
   if(health.plazaRegistered){clearInterval(registrationWatch);registrationWatch=0;}
   if(health.plazaRegistered===runtime.plaza.registered&&health.plazaState===runtime.plaza.state)return;
   Object.assign(runtime.plaza,{registered:!!health.plazaRegistered,state:health.plazaState});
   redrawStatus();
  }catch{}
 },5000);
}
function redrawStatus(){
 const shown=typeof document!=='undefined'&&document.querySelector('.topbar details.plaza-status');if(!shown)return;
 const next=document.createElement('template');next.innerHTML=statusHTML();
 const status=next.content.firstElementChild;status.open=shown.open;shown.replaceWith(status);
}
// The top bar follows whether this tab's Terminal answers (terminal-presence.js).
onTerminalPresence(redrawStatus);
// When the Terminal answers again, it is the same process if it still has one of this tab's panels; a new process
// answers that the panel is unknown (a restart), and the tab offers a reload.
decideRestart(async()=>{
 const remoteId=[...nodes.values()].find(node=>node?.remoteId)?.remoteId;if(!remoteId)return false;
 try{await api('/api/instances/'+remoteId);return false;}
 catch(error){if(error.terminalUnreachable)throw error;return error.status===404&&error.detail==='Browser unavailable in this Terminal window.';}
});
// After a restart the Terminal opens a new tab. This tab gives it its window (and so its workspace) only once its own
// Terminal stopped or was replaced; then it says so and sends nothing more (api above, terminalHeaders).
allowWindowHandover(terminalReplaced);
onWindowHandedOver(windowMoved);
async function refreshDiscovery(){
 try{Object.assign(runtime,await api('/api/discovery'));document.dispatchEvent(new CustomEvent('plaza:discovery'));}catch{}
}
export async function loadCatalog() {
 try {
  let offset=0,pulses=[],result;
  do {
    result=await api('/api/catalog?offset='+offset+'&limit=500'+(result?.snapshot?'&snapshot='+encodeURIComponent(result.snapshot):''));pulses.push(...result.pulses);offset+=result.pulses.length;
  } while(offset<result.total && result.pulses.length);
  runtime.catalog={...result,pulses};setPulseCatalog(runtime.catalog);
  runtime.catalogError='';document.dispatchEvent(new CustomEvent('catalog:updated'));
  return runtime.catalog;
 } catch(error) {setCatalogError(error.message);runtime.catalogError=error.message;document.dispatchEvent(new CustomEvent('catalog:updated'));throw error;}
}
document.addEventListener('catalog:refresh',()=>loadCatalog().catch(()=>{}));
export function scopedStorage(storage=sessionStorage) {
  const scope='retis-terminal:'+new URL(runtime.plaza.url||location.origin).origin+':'+(runtime.user?.id||'guest')+':'+terminalWindow()+':';
  return {getItem:key=>storage.getItem(scope+key),setItem:(key,value)=>storage.setItem(scope+key,value),removeItem:key=>storage.removeItem(scope+key)};
}
// The top bar shows the signed-in account's available Plaza points beside the Plaza name. Plaza keeps the points; the
// Terminal shows only the number Plaza reports. Every answer to this window carries the number from its last session
// check with Plaza (X-Plaza-Points, at most about half a minute old), so most updates cost Plaza nothing. The window
// asks on purpose (/api/account/balance, Plaza's account profile) only at sign-in, just after a result it paid for, when
// it comes back to the front a minute or more after the last number, and once a minute while Plaza is not answering.
// The number is kept per Plaza and account; while Plaza is not answering the last one stays, marked as not current.
const POINTS_AGAIN=60000;
const idlePoints=key=>({key,value:null,at:0,read:0,stale:false,loading:null,again:false,timer:0,retry:0});
let points=idlePoints('');
const pointsKey=()=>runtime.user&&!runtime.plaza.localOnly&&!runtime.user.authentication?(runtime.plaza.url||'')+'|'+runtime.user.id:'';
function pointsFor(key){if(points.key!==key){clearTimeout(points.timer);clearTimeout(points.retry);points=idlePoints(key);}return points;}
function notePoints(value,at){
 const key=pointsKey();if(!key||!Number.isInteger(value))return;
 const state=pointsFor(key);
 // An answer older than the number shown says nothing new; nor does the same one while Plaza is not answering.
 if(at&&(at<state.at||at===state.at&&state.stale))return;
 const changed=state.value!==value||state.stale;
 Object.assign(state,{value,at:at||Date.now()/1000,stale:false});clearTimeout(state.retry);
 if(changed)drawPoints();
}
export function readPoints(){
 const key=pointsKey();if(!key)return Promise.resolve();
 const state=pointsFor(key);
 if(state.loading){state.again=true;return state.loading;}
 state.read=Date.now();
 state.loading=api('/api/account/balance').then(answer=>notePoints(answer.balance,Number(answer.at)||0),error=>{
  if(points!==state)return;
  // A window without a Plaza account shows none; otherwise the last number stays, marked as not current.
  if(error.status===409)state.value=null;
  else{state.stale=state.value!==null;clearTimeout(state.retry);state.retry=setTimeout(()=>{if(!document.hidden)readPoints();},POINTS_AGAIN);}
  drawPoints();
 }).finally(()=>{state.loading=null;if(state.again&&points===state){state.again=false;readPoints();}});
 return state.loading;
}
// Just after a result this window paid for, once the payments of the same moment have settled.
function soonPoints(){if(!pointsKey())return;clearTimeout(points.timer);points.timer=setTimeout(readPoints,1500);}
function pointsAgain(){if(pointsKey()&&!document.hidden&&Date.now()-Math.max(points.read,points.at*1000)>=POINTS_AGAIN)readPoints();}
if(typeof window!=='undefined'){window.addEventListener('focus',pointsAgain);document.addEventListener('visibilitychange',pointsAgain);}
// A new result whose provenance says it was paid (content_references) means the account's points changed. The first
// answer for a Data Browser only notes the results it already had: results kept from before were paid before.
const paidSeen=new Set(),browsersSeen=new Set();
function notePaidResults(state){
 const results=state?.content?.results,first=!!state?.id&&!browsersSeen.has(state.id);
 if(first)browsersSeen.add(state.id);
 if(!results||typeof results!=='object')return;
 let paid=false;
 for(const result of Object.values(results)){
  const billing=result?.provenance?.billing;if(!(billing?.points>0))continue;
  const id=billing.executionId||String(result.resolvedAt);if(paidSeen.has(id))continue;
  if(paidSeen.size>=500)paidSeen.clear();
  paidSeen.add(id);paid=!first;
 }
 if(paid)soonPoints();
}
// Up to 99,999 the whole number; above it a short form in the window's language (1.2M, 120萬), the whole number in the title.
function shortPoints(value){
 try{return new Intl.NumberFormat(currentLocale(),Math.abs(value)<100000?{}:{notation:'compact',maximumFractionDigits:1}).format(value);}catch{return String(value);}
}
const shownPoints=()=>pointsKey()&&points.key===pointsKey()&&Number.isInteger(points.value);
// The first top bar for an account asks once; a page without the top bar (account, settings) never asks.
function wantPoints(){const key=pointsKey();if(key&&(points.key!==key||!points.read))readPoints();}
const titleArgs=()=>[points.stale?'Last known Plaza points: {0}. Plaza is not answering, so this may not be current.':'Available Plaza points: {0}. Open points spending.',points.value.toLocaleString()];
const pointsTitle=()=>shownPoints()?attribute('title',...titleArgs()):'';
const pointsCell=()=>shownPoints()?points.value.toLocaleString():'—';
function pointsHTML(){
 if(!shownPoints())return '';
 return `<span class="plaza-status-points${points.stale?' is-stale':''}" data-plaza-balance="${points.value}" ${points.stale?'data-stale':''} data-action="plaza" ${pointsTitle()}> <span class="plaza-status-points-separator" aria-hidden="true">·</span> ${label('{0} points',(points.stale?'~':'')+shortPoints(points.value))}</span>`;
}
// Only the points change in place: the menu, if open, stays as it is.
function drawPoints(){
 if(typeof document==='undefined')return;
 const status=document.querySelector('.topbar details.plaza-status'),line=status?.querySelector('[data-plaza-state]');
 if(line){line.querySelector('[data-plaza-balance]')?.remove();line.insertAdjacentHTML('beforeend',pointsHTML());}
 const cell=status?.querySelector('[data-plaza-points]');
 if(cell){cell.textContent=pointsCell();if(shownPoints())setUIAttribute(cell,'title',...titleArgs());else{cell.removeAttribute('title');cell.removeAttribute('data-ui-attr-title');}}
}
// The points open the Plaza account settings (app.js, data-action="plaza") at Points spending, not the menu.
if(typeof document!=='undefined')document.addEventListener('click',event=>{
 if(!event.target.closest?.('.topbar [data-plaza-balance]'))return;
 event.preventDefault();
 requestAnimationFrame(()=>document.querySelector('dialog[open] [data-points-spending]')?.scrollIntoView({block:'start'}));
},true);
const REGISTRY_STATES={registered:'Registered',success:'Registered',idle:'Not registered',retry:'Retrying',unauthorized:'Not authorized',configuration_error:'Configuration error'};
// The top bar names the Plaza this window is connecting to, or is connected to, by its host.
const plazaHost=()=>{try{return new URL(runtime.plaza.url).host;}catch{return '';}};
export function statusHTML() {
  if(runtime.plaza.localOnly)return uiHTML`<details class="plaza-status is-demo-connected"><summary aria-label="Local connection status"><span class="plaza-status-dot"></span>Local / <strong>Ready</strong></summary><section class="plaza-status-popover"><p>Using paired local Phemacast resources. Plaza login is not required.</p><button data-action="settings">Terminal settings</button></section></details>`;
  const host=plazaHost(),presence=terminalPresence();
  wantPoints();
  if(presence!=='up')return uiHTML`<details class="plaza-status is-terminal-stopped"><summary aria-label="Plaza connection status" title="${esc(runtime.plaza.url||'')}"><span class="plaza-status-dot"></span><span class="plaza-status-label">${host?`<span class="plaza-status-name" data-plaza-name>${esc(host)}</span>`:'Plaza'} <span class="plaza-status-separator" aria-hidden="true">/</span> <strong>${label(presence==='stopped'?'Terminal stopped':presence==='moved'?'Open in another tab':'Terminal restarted')}</strong></span></summary><section class="plaza-status-popover"><p>${presence==='moved'?label(...movedMessage(runtime.launcherApp)):presence==='stopped'?label('This Terminal is not responding. It may have stopped.'):label(...restartedMessage(runtime.launcherApp))}</p></section></details>`;
  return uiHTML`<details class="plaza-status ${runtime.plaza.registered?'is-demo-connected':''}"><summary aria-label="Plaza connection status" title="${esc(runtime.plaza.url||'')}"><span class="plaza-status-dot"></span><span class="plaza-status-label">${host?`<span class="plaza-status-name" data-plaza-name>${esc(host)}</span>`:'Plaza'} <span class="plaza-status-separator" aria-hidden="true">/</span> <span class="plaza-status-state" data-plaza-state><strong>${label(runtime.plaza.registered?'Connected':host?'Connecting':'Not connected')}</strong>${pointsHTML()}</span></span></summary><section class="plaza-status-popover"><h3>${label(runtime.user?'Signed in':'Guest')}</h3><p>${runtime.user?.name?esc(runtime.user.name):label('Sign in to retrieve data and save consultant layouts.')}</p><dl class="plaza-status-facts">${host?uiHTML`<div><dt>Plaza address</dt><dd title="${esc(runtime.plaza.url)}">${esc(host)}</dd></div>`:''}<div><dt title="This Terminal's registration in the Plaza directory">Plaza directory</dt><dd>${label(REGISTRY_STATES[runtime.plaza.state]||runtime.plaza.state||'Not registered')}</dd></div><div><dt title="App Consultants this Terminal found on Plaza. They provide the layouts you can open.">Connected App Consultants</dt><dd>${runtime.consultants.length}</dd></div>${runtime.user?uiHTML`<div><dt>Available Plaza points</dt><dd data-plaza-points ${pointsTitle()}>${esc(pointsCell())}</dd></div>`:''}</dl><button data-action="plaza">Account settings ↗</button>${runtime.user?uiHTML`<p><a href="./account.html#transactions" target="_blank" rel="noopener">Transaction history ↗</a></p>`:''}</section></details>`;
}
const publisherName=id=>runtime.catalog.publishers.find(p=>p.id===id)?.name||'';
// An operation shows by the name its agent publishes in the catalog, in this window's language (operation-names.js).
let namer={catalog:null,name:null};
const operationName=row=>{if(namer.catalog!==runtime.catalog)namer={catalog:runtime.catalog,name:operationNamer(runtime.catalog)};return namer.name(row);};
// Points spending reads Plaza's ledger, which keeps every charge (agents such as the Strategy Producer
// charge there), with this Terminal's own executions; a short cache keeps re-renders from reading it again.
let spending={at:0,rows:null,error:'',loading:null,balance:null};
const fresh=()=>spending.at&&Date.now()-spending.at<30000;
function loadSpending({force=false}={}){
 if(spending.loading)return spending.loading;
 // A failed read also counts as an answer for a short while, so a redraw does not ask again at once.
 if(!force&&fresh())return spending.rows?Promise.resolve(spending.rows):Promise.reject(new Error(spending.error));
 const done=next=>{spending={...next,at:Date.now(),loading:null};document.dispatchEvent(new CustomEvent('connected:settings'));};
 spending.loading=(async()=>{
  const own=(await api('/api/billing/history')).rows||[];
  let ledger=null,error='';
  try{ledger=await api('/api/account/transactions');}catch(failure){error=failure.message||'Plaza did not answer.';}
  // The same read gives the account's available points, shown at the top of the section.
  const balance=ledger?.account?.balance;
  if(Number.isInteger(balance))notePoints(balance,Number(ledger.retrievedAt)||0);
  done({rows:spendingRows(own,ledger),error,balance:Number.isInteger(balance)?balance:null});
  return spending.rows;
 })().catch(failure=>{if(spending.loading)done({rows:null,error:failure.message||'Points spending could not be read.'});throw failure;});
 return spending.loading;
}
function pointsSpendingHTML(){
 if(!spending.loading&&!fresh())loadSpending().catch(()=>{});
 const balance=Number.isInteger(spending.balance)?uiHTML`<p class="points-balance"><span>Available Plaza points</span> <strong>${esc(spending.balance.toLocaleString())}</strong></p>`:'';
 const all=spending.rows||runtime.settings.billing||[],rows=all.slice(0,10),total=spending.rows?all.length:(runtime.settings.billingTotal??rows.length);
 const older=(runtime.settings.billingToReconcile||0)-rows.filter(row=>row.canReconcile).length;
 const note=!spending.rows?(spending.error&&fresh()?uiHTML`<p class="points-warning" title="${esc(spending.error)}">Points spending could not be read. Open settings again in a moment.</p>`:uiHTML`<p class="points-note" role="status">Reading Plaza charges…</p>`):spending.error?uiHTML`<p class="points-warning" title="${esc(spending.error)}">Plaza charges could not be read; only this Terminal’s own payments are listed.</p>`:'';
 if(!total)return spending.rows?uiHTML`${balance}${note}<p>No points spent yet.</p>`:uiHTML`${balance}${note}`;
 return uiHTML`${balance}${note}<div class="points-recent-head"><small>${label('Latest {0} of {1} executions',rows.length,total)}</small><button type="button" class="button" data-connected-action="points-history">Open history</button></div><p class="points-count-note">${label('Each execution counts once here. Transaction history lists every ledger entry, and one execution can have several: its reservation, the settlement and the payment.')}</p>${pointsRowsHTML(rows,publisherName,operationName)}${older>0?`<p class="points-warning">${label('{0} older executions need checking. Open the history to reconcile them.',older)}</p>`:''}`;
}
// Whether the signed-in account receives the newsletter, and in which language. Plaza keeps both with the account
// (2026-11-18); this only remembers the last answer so a redraw does not ask Plaza again. A Plaza that does not keep the
// choice shows no box, and one that keeps no language shows no menu. '' is no single language (繁體中文 + English).
let newsletter={user:null,value:null,language:null,loading:false,status:''};
const NEWSLETTER_LANGUAGES=[['','繁體中文 + English'],['en','English'],['zh-Hant','繁體中文'],['zh-Hans','简体中文'],['ja','日本語'],['es','Español'],['fr','Français']];
function newsletterHTML(){
 if(newsletter.user!==runtime.user.id){
  newsletter={user:runtime.user.id,value:null,language:null,loading:true,status:''};const user=newsletter.user;
  api('/api/account/newsletter').then(({newsletter:value,language})=>{if(newsletter.user===user)Object.assign(newsletter,{value,language:typeof language==='string'?language:null,loading:false,status:value===null?'none':''});},
   error=>{if(newsletter.user===user)Object.assign(newsletter,{loading:false,status:error.message||'Plaza could not read the newsletter choice.'});})
   .finally(()=>document.dispatchEvent(new CustomEvent('connected:settings')));
 }
 if(newsletter.status==='none')return '';
 const status=newsletter.status==='saved'?label('Saved.'):newsletter.status?esc(t(newsletter.status)):'';
 const disabled=newsletter.loading||typeof newsletter.value!=='boolean'?'disabled':'';
 const options=NEWSLETTER_LANGUAGES.map(([value,name])=>`<option value="${esc(value)}" ${value===newsletter.language?'selected':''}>${esc(name)}</option>`).join('');
 const menu=typeof newsletter.language==='string'?uiHTML`<label>Newsletter language <select data-newsletter-language ${disabled}>${options}</select></label>`:'';
 return uiHTML`<p class="newsletter-setting"><label><input type="checkbox" data-newsletter ${newsletter.value?'checked':''} ${disabled}> Receive newsletter</label> ${menu} <small data-newsletter-status role="status">${status}</small></p>`;
}
document.addEventListener('change',async event=>{
 const box=event.target.closest?.('[data-newsletter]'),menu=event.target.closest?.('[data-newsletter-language]');
 if((!box&&!menu)||!runtime.user)return;
 const user=runtime.user.id,body=box?{newsletter:box.checked}:{language:menu.value};(box||menu).disabled=true;
 try{const {newsletter:value,language}=await api('/api/account/newsletter',{method:'PUT',body});if(newsletter.user===user)Object.assign(newsletter,{value,language:typeof language==='string'?language:newsletter.language,status:'saved'});}
 catch(error){if(newsletter.user===user)newsletter.status=error.message||'Plaza could not save the newsletter choice.';}
 document.dispatchEvent(new CustomEvent('connected:settings'));
});
export function settingsHTML(tab='all') {
 const p=runtime.settings.preferences||{},hosted=location.pathname.startsWith('/phemar-proxy/');
 const canConfigure=runtime.permissions?.canConfigure===true;
 const account=runtime.plaza.localOnly?uiHTML`<p>Local device · Plaza is not required</p>`:hosted&&!terminalWindow()?uiHTML`<p>${esc(runtime.user?.name||'Sign in through Attas')}</p><p>Plaza login is managed by Attas.</p><a class="button" href="/" target="_top">Open Attas account</a>${runtime.kind==='data-terminal'?uiHTML`<p><a href="${esc(hostedPath("/settings.html",location))}" target="_blank" rel="noopener">Open Terminal account settings</a> to disconnect this Terminal before switching accounts.</p>`:''}`:runtime.user?uiHTML`<p>${esc(runtime.user.name)}</p><button class="button" data-connected-action="signout">Sign out</button>${newsletterHTML()}${runtime.plaza.delegatedLogin?uiHTML`<p><label><input type="checkbox" data-network-local checked> Prefer verified sources on this local network</label></p><p data-network-status role="status">Direct HTTPS · no tunnel</p>`:''}`:runtime.plaza.delegatedLogin?uiHTML`<section class="plaza-access" data-plaza-access><p><small data-access-step></small><br><strong data-access-title>Checking Plaza access…</strong></p><p data-connect-status role="status"></p><div data-access-actions><button class="button primary" data-connect-plaza>Request access</button><p data-window-signin-status role="status"></p></div></section>`:uiHTML`<button class="button primary" data-window-signin>Sign in to Plaza</button><button class="button" data-window-signin data-alternate>Use another account</button><p data-window-signin-status role="status"></p><details class="manual-connection"><summary>Advanced: manual sign-in</summary><form data-connected-form="signin"><label>Plaza identifier<input name="identifier" autocomplete="username" required></label><label>Password<input name="password" type="password" autocomplete="current-password" required></label><button class="button primary">Sign in to Plaza</button></form></details>`;
 const restricted=runtime.user?uiHTML`<h3>Agent settings</h3><p>Only this agent’s owner can change its configuration, layouts, and data-source connections.</p>`:uiHTML`<p>Sign in to Plaza to manage connections and save settings.</p>`;
 const sections={
  workspace:languageSettingsHTML()+(canConfigure?uiHTML`${timezoneSettingsHTML(p.displayTimezone,p.specifiedTimezone)}${displayFormatSettingsHTML(p.displayFormat)}${marketSettingsHTML(p.marketAppearance)}${workspaceHistorySettingsHTML(p.workspaceHistory)}`:''),
  connections:(runtime.user&&!runtime.plaza.localOnly?agentTrustHTML():uiHTML`<p>Sign in to Plaza to see the agents you trust and your connection history.</p>`)+uiHTML`<p>Open an agent workspace to manage its connections and data policy.</p>`,
  sources:runtime.user||runtime.plaza.localOnly?sourceSettingsHTML():uiHTML`<p>Sign in to Plaza to manage connections and save settings.</p>`,
  runs:runtime.user||runtime.plaza.localOnly?scheduledRunsHTML():uiHTML`<p>Sign in to Plaza to see this window's scheduled runs.</p>`,
  plaza:uiHTML`<h3>Plaza account</h3>${!runtime.plaza.localOnly&&(runtime.plaza.url||runtime.plaza.canChangeAddress)?(runtime.plaza.canChangeAddress&&!hosted?uiHTML`<form class="plaza-address-form" data-plaza-address-form><label>Plaza address<input name="url" type="url" value="${esc(runtime.plaza.url)}" data-plaza-address required autocomplete="url" spellcheck="false" ${runtime.user?'disabled':''}></label><button type="submit" class="button" ${runtime.user?'disabled':''}>Connect</button><p data-plaza-address-status role="status">${runtime.user?label('Sign out of this window before changing its Plaza address.'):!runtime.plaza.url?label('Enter a Plaza address to connect this Terminal.'):''}</p></form>`:uiHTML`<dl class="plaza-login-address"><dt>Plaza address</dt><dd data-plaza-address>${esc(runtime.plaza.url)}</dd></dl>`):''}${runtime.plaza.delegatedLogin?uiHTML`<section data-trusted-plazas><h3>Trusted Plazas</h3><div data-trusted-plazas-list></div><p data-trusted-plazas-status role="status"></p><details><summary>How to connect</summary><p>Request access, wait for the Plaza owner to approve this Terminal, then sign in. Each window uses one Plaza at a time; choose Connect beside a trusted Plaza to switch this window. Each Plaza keeps its own approval and credentials.</p></details></section>`:''}${runtime.kind==='data-terminal'?uiHTML`<p>Each Terminal window has its own Plaza login, settings and open Phemas.</p>`:''}${account}${runtime.user&&runtime.plaza.delegatedLogin&&!runtime.plaza.trusted?uiHTML`<button class="button" data-connect-plaza>Request access</button><p data-connect-status role="status"></p>`:''}${runtime.user?uiHTML`<p><a class="button" href="./account.html#profile" target="_blank" rel="noopener">Account profile ↗</a> <a class="button" href="./account.html#transactions" target="_blank" rel="noopener">Transaction history ↗</a></p>`:''}${canConfigure?uiHTML`<h3 data-points-spending>Points spending</h3><p>Execution payments use Plaza points. Each owning agent controls its operations, permissions and data policy.</p>${pointsSpendingHTML()}`:''}`
 };
 // Built only when shown: it asks this Terminal for the window's approved AI apps.
 if(tab==='ai')sections.ai=runtime.user||runtime.plaza.localOnly?aiAppsHTML():uiHTML`<p>Sign in to Plaza to let AI apps control this window.</p>`;
 const local=runtime.plaza.localDiscovery?uiHTML`<section data-local-resources><h3>On this computer</h3><button type="button" data-local-scan>Discover</button><details><summary>How it works</summary><p>Retis components running on this computer are found automatically and work at once: no sign-in or pairing. Nothing on another computer can use them.</p></details><div data-local-list></div><p data-local-status role="status"></p></section>`:'';
 const content=tab==='all'?sections.workspace+local+sections.connections+sections.sources+sections.plaza:(tab==='connections'?local:'')+(sections[tab]||'');
 return uiHTML`<section class="connected-settings">${content}<p data-connected-feedback role="status"></p></section>`;
}
document.addEventListener('submit',async event=>{
 const form=event.target.closest('[data-connected-form]');if(!form)return;event.preventDefault();event.stopImmediatePropagation();
 const feedback=form.parentElement.querySelector('[data-connected-feedback]')||document.querySelector('[data-connected-feedback]');
 const values=Object.fromEntries(new FormData(form));
 try {
  if(form.dataset.connectedForm==='signin'){await api('/api/auth/signin',{method:'POST',body:values});location.reload();return;}
  if(form.dataset.connectedForm==='time-display')await api('/api/settings',{method:'PUT',body:{displayTimezone:values.timeZoneMode==='specified'?values.specifiedTimezone:values.timeZoneMode,specifiedTimezone:form.elements.specifiedTimezone.value}});
  if(form.dataset.connectedForm==='display-format')await api('/api/settings',{method:'PUT',body:{displayFormat:displayFormatValues(values)}});
  if(form.dataset.connectedForm==='workspace-history')await api('/api/settings',{method:'PUT',body:{workspaceHistory:workspaceHistoryValues(values)}});
  if(form.dataset.connectedForm==='market-appearance'){await api('/api/settings',{method:'PUT',body:{marketAppearance:{upColor:values.upColor,downColor:values.downColor,colorChanges:values.colorChanges==='on',flashEnabled:values.flashEnabled==='on',flashColor:values.flashColor,flashDurationMs:Math.round(Number(values.flashDuration)*1000)}}});}
  runtime.settings=await api('/api/settings');applyMarketAppearance(runtime.settings.preferences.marketAppearance);applyDisplayTimezone(runtime.settings.preferences.displayTimezone);applyDisplayFormat(runtime.settings.preferences.displayFormat);if(form.dataset.connectedForm==='display-format')rendering();if(form.dataset.connectedForm==='time-display'){try{scopedStorage().setItem('display-timezone',runtime.settings.preferences.displayTimezone);}catch{}rendering();}if(form.dataset.connectedForm==='market-appearance'){try{scopedStorage().setItem('market-appearance',JSON.stringify(runtime.settings.preferences.marketAppearance));}catch{}setUIText(form.querySelector('[data-market-feedback]'),'Saved.');}if(feedback)setUIText(feedback,'Saved.');
  document.dispatchEvent(new CustomEvent('connected:settings'));
 }catch(error){if(feedback){clearUIText(feedback);feedback.textContent=error.message;}}
},true);
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-connected-action]');if(!button)return;
 try {
  if(button.dataset.connectedAction==='signout'){await api('/api/auth/signout',{method:'POST',body:{}});clearSignedOut();location.reload();}
  if(button.dataset.connectedAction==='points-history'){openPointsHistory({load:async()=>({rows:await loadSpending()}),agentName:publisherName,operationName});return;}
  if(button.dataset.connectedAction==='reconcile'){await api('/api/billing/'+button.dataset.id+'/reconcile',{method:'POST',body:{}});runtime.settings=await api('/api/settings');spending.at=0;document.dispatchEvent(new CustomEvent('connected:settings'));return;}
 }catch(error){const f=document.querySelector('[data-connected-feedback]');if(f)f.textContent=error.message;}
});


const nodes=new Map();let latest=[];let currentWorkspace;let rendering=()=>{};
document.addEventListener('catalog:updated',()=>rendering());
// Opening the account menu shows the points the top bar shows, read again when they are a minute old.
document.addEventListener('toggle',event=>{if(event.target.matches?.('details.plaza-status[open]'))pointsAgain();},true);
window.addEventListener('pagehide',()=>{for(const node of nodes.values()){node.events?.close();if(node.remoteId&&!node.viewOnly)fetch('/api/instances/'+node.remoteId,{method:'DELETE',credentials:'same-origin',keepalive:true,headers:terminalHeaders()}).catch(()=>{});}});
export function syncBrowsers(browsers,workspaceId,onUpdate) {
 latest=browsers;currentWorkspace=workspaceId;rendering=onUpdate;
 // A page value a Browser publishes to its link group goes out as it changes (link-groups.js).
 observeLinks(browsers);
 if(!runtime.user)return;
 const ids=new Set(browsers.map(b=>b.id));
 for(const [id,entry] of nodes)if(!ids.has(id)){entry.cancelled=true;entry.events?.close();if(entry.remoteId)api('/api/instances/'+entry.remoteId,{method:'DELETE'}).catch(()=>{});nodes.delete(id);}
 for(const b of browsers){
  const design=browserDesign(b.design,b.instrumentOverrides);
  b.fieldBindings=normalizeFieldBindings(b.fieldBindings,browserState(b).entry?.design.dataRequirements||design.dataRequirements);
  const signature=JSON.stringify([design,b.customLayout?.composition,b.instrumentOverrides,b.parameterValues,b.layoutTabs]);let entry=nodes.get(b.id);let released=Promise.resolve();
  if(entry?.signature===signature){
    if(entry.remoteId&&entry.range!==b.range){
      entry.range=b.range;const range=b.range;
      entry.rangeUpdate=(entry.rangeUpdate||Promise.resolve()).catch(()=>{}).then(()=>{
        if(entry.cancelled)return;
        return api('/api/instances/'+entry.remoteId,{method:'PUT',body:{range}}).then(remote=>{if(!entry.cancelled&&entry.range===range){entry.state=remote;rendering();}});
      }).catch(error=>{entry.state.error=error.message;rendering();});
    }
    continue;
  }
  if(entry?.remoteId&&entry.designSignature===JSON.stringify(design)){
    entry.signature=signature;
    // Kept so a control's runReference runs only once the instance has its new page values. The values sent and the
    // sequence that answered them let a slower read of the instance be told apart from a newer one (keptValues).
    entry.sentValues=JSON.stringify(b.parameterValues||{});entry.inflight=(entry.inflight||0)+1;
    entry.update=api('/api/instances/'+entry.remoteId,{method:'PUT',body:{entry:{...b.customLayout,design},layoutTabs:b.layoutTabs,parameterValues:b.parameterValues,instrumentOverrides:b.instrumentOverrides}}).then(remote=>{entry.putSequence=Math.max(entry.putSequence??-1,remote?.sequence??-1);entry.state=remote;rendering();}).catch(error=>{entry.state.error=error.message;rendering();}).finally(()=>{entry.inflight-=1;});continue;
  }
  if(entry){entry.cancelled=true;entry.events?.close();if(entry.remoteId)released=api('/api/instances/'+entry.remoteId,{method:'DELETE'}).catch(()=>{});}
  entry={signature,designSignature:JSON.stringify(design),range:b.range,state:{status:'loading',results:{}},sentValues:JSON.stringify(b.parameterValues||{}),inflight:0};nodes.set(b.id,entry);
  if(!b.customLayout){nodes.delete(b.id);continue;}
  const layout=b.customLayout;
  entry.ready=released.then(()=>api('/api/instances',{method:'POST',body:{workspaceId,layoutTabs:b.layoutTabs,parameterValues:b.parameterValues,instrumentOverrides:b.instrumentOverrides,sourceMode:b.sourceMode||'parameters',snapshotId:b.contentSnapshotId,uiLanguage:b.uiLanguage||null,fieldBindings:normalizeFieldBindings(b.fieldBindings),contentOverrides:normalizeContentOverrides(b.contentOverrides),refreshOverrides:normalizeRefreshOverrides(b.refreshOverrides),range:b.range,command:b.command,messages:normalizeMessages(b.messages),entry:{...layout,design}}})).then(async remote=>{
    if(entry.cancelled){await api('/api/instances/'+remote.id,{method:'DELETE'});return;}
    entry.remoteId=remote.id;entry.state=remote;loadPanelSources(b,entry);if((b.uiLanguage||null)!==(remote.uiLanguage||null))await api('/api/instances/'+remote.id,{method:'PUT',body:{uiLanguage:b.uiLanguage||null}});if(entry.range!==b.range)syncBrowsers(latest,currentWorkspace,rendering);
    entry.events=watchBrowserInstance(api,'/api/instances/'+remote.id,state=>{entry.state=state;retryUnconfirmedTrust(b,state);noticeFailedRefresh(b.id,entry,state);
      if(state.phema){const current=phemaToEntry(state.phema);if(JSON.stringify(current)!==JSON.stringify(b.customLayout)){
        b.customLayout=current;b.design=browserDesign(current.design,state.instrumentOverrides);b.layoutId=layoutKind(current.baseLayoutId);
        const mine=keptValues(entry,b,state);
        b.parameterValues=mine?b.parameterValues:state.parameterValues||{};b.instrumentOverrides=state.instrumentOverrides||{};b.layoutTabs=state.layoutTabs||{};
        // Kept values are signed as the server has them, so the next sync sends them again and the instance catches up.
        const design=browserDesign(b.design,b.instrumentOverrides);entry.designSignature=JSON.stringify(design);entry.signature=JSON.stringify([design,current.composition,b.instrumentOverrides,mine?state.parameterValues||{}:b.parameterValues,b.layoutTabs]);
        if(mine)queueMicrotask(()=>syncBrowsers(latest,currentWorkspace,rendering));
        document.dispatchEvent(new CustomEvent('browser:phema-edited',{detail:{id:b.id}}));document.dispatchEvent(new CustomEvent('browser:interaction'));
      }}
const contentChanged=b.sourceMode!==(entry.state.sourceMode||'parameters')||(entry.state.sourceMode==='snapshot'&&b.contentSnapshotId!==entry.state.content?.snapshotId);b.sourceMode=entry.state.sourceMode||'parameters';b.contentSnapshotId=b.sourceMode==='snapshot'?entry.state.content?.snapshotId:undefined;if(contentChanged)document.dispatchEvent(new CustomEvent('browser:interaction'));b.uiLanguage=entry.state.uiLanguage||null;const messages=normalizeMessages(entry.state.messages);if(JSON.stringify(messages)!==JSON.stringify(b.messages||[])){b.messages=messages;document.dispatchEvent(new CustomEvent('browser:interaction'));}loadOpenedPanels(entry,b);rendering();},error=>{
      if(entry.cancelled)return;entry.state.transport='Reconnecting';
      if(error.status===404){entry.signature=null;entry.designSignature=null;syncBrowsers(latest,currentWorkspace,rendering);return;}
      if(error.status===401){noteSignedOut(error.detail);location.reload();}else rendering();
    },{initial:remote});loadOpenedPanels(entry,b);rendering();
  }).catch(error=>{entry.state={status:'unavailable',error:error.message,results:{}};
    entry.notApproved=error.status===403&&error.detail===NOT_APPROVED;if(entry.notApproved)watchApproval();rendering();});
 }
}
/** Whether this window's page values are newer than an instance read that also brings a changed Phema: an update
 * of its own is still on the way, values it set are not sent yet, or the read is older than its last answered update.
 * A value a linked page delivered (or a row clicked) just after the Phema was saved again is then not replaced by the
 * value the instance held a moment earlier. */
export function keptValues(entry,b,state){
 const local=JSON.stringify(b.parameterValues||{});
 if(local===JSON.stringify(state?.parameterValues||{}))return false;
 return (entry.inflight||0)>0||local!==entry.sentValues||(entry.putSequence!=null&&(state?.sequence??-1)<entry.putSequence);
}
/** The picture saved with a Browser snapshot, shown when New Data Browser offers that snapshot. */
async function saveSnapshotScreenshot(browserId,snapshotId){
 const node=document.querySelector(`[data-browser="${CSS.escape(browserId)}"]`);
 if(!/^[a-f0-9]{64}$/.test(snapshotId||'')||!node?.isConnected||!node.clientWidth||!node.clientHeight||node.classList.contains('focus-hidden'))return;
 const image=await screenshot(node);
 if(image)await api('/api/snapshot-previews/'+snapshotId,{method:'PUT',body:{image,capturedAt:Date.now()},signal:AbortSignal.timeout(8000)});
}
/** Once per Phema opened from New Data Browser, its panels that wait for ↻ load together, as one ↻ for each. */
function loadOpenedPanels(entry,b){
 if(!b.loadOnOpen||!entry.remoteId||entry.cancelled)return;
 const references=openingLoad(entry.state,b.customLayout);if(!references)return;
 b.loadOnOpen=false;
 if(references.length)api('/api/instances/'+entry.remoteId+'/content',{method:'POST',body:{references}}).then(()=>rendering()).catch(()=>{});
}
/** After ♧ approves or revokes, the panels say so at once, without ↻: revoked ones ask for approval
 * again; approved ones show Loading while their reads load again, as one ↻ for each. */
function reloadAfterPermission(entry,b,change='approved'){
 if(!entry?.remoteId||entry.cancelled)return;
 const id=entry.remoteId;
 // The Terminal's own view of the decision replaces this page's, whatever the next poll brings.
 const reread=()=>api('/api/instances/'+id).then(state=>{if(!entry.cancelled&&entry.remoteId===id){entry.state=state;rendering();}}).catch(()=>{});
 // A snapshot shows its saved content; approving or revoking never loads live data.
 if(entry.state?.sourceMode==='snapshot'){reread();return;}
 const results=entry.state?.content?.results||{};
 const references=change==='revoked'?[]:permissionReferences(entry.state?.phema||b?.customLayout,results);
 const shown=(ref,result)=>change==='revoked'?{status:'blocked',reason:'permission-required'}
  :references.includes(ref)||result?.status==='blocked'?{...result,status:'resolving',reason:undefined}:result;
 if(entry.state?.content)entry.state={...entry.state,content:{...entry.state.content,results:Object.fromEntries(Object.entries(results).map(([ref,result])=>[ref,shown(ref,result)]))}};
 rendering();
 if(!references.length){reread();return;}
 api('/api/instances/'+id+'/content',{method:'POST',body:{references}}).then(()=>rendering()).catch(()=>reread());
}
/** Update the same Browser process; presentation changes do not reconnect data. */
export async function applyBrowserPhemaEdit(b,next,settings){
 let node=nodes.get(b.id);if(node?.ready&&!node.remoteId)await node.ready;node=nodes.get(b.id);if(!node?.remoteId)throw new Error('Browser is still initializing. Try again shortly.');
 const body={entry:next,command:next.command,parameterValues:b.parameterValues||{},instrumentOverrides:b.instrumentOverrides||{},layoutTabs:b.layoutTabs||{},...(settings||{})};
 const remote=await api('/api/instances/'+node.remoteId,{method:'PUT',body});
 b.customLayout=next;b.layoutId=layoutKind(next.baseLayoutId);b.design=browserDesign(next.design,remote.instrumentOverrides);b.command=remote.command;b.commandDraft=remote.command;b.ticker=remote.entry.design.params.ticker?.default||remote.entry.design.params.portfolioId?.default||'';b.tickers=remote.entry.design.params.tickers?.default||[];
 for(const key of ['fieldBindings','refreshOverrides','contentOverrides','instrumentOverrides','parameterValues','layoutTabs','range','uiLanguage'])b[key]=remote[key]??(key==='range'?'1M':key==='uiLanguage'?null:{});
 delete b.layoutConflict;delete b.layoutPublication;delete b.consultantId;
 node.state=remote;node.events?.accept(remote);const design=browserDesign(b.design,b.instrumentOverrides);
 node.designSignature=JSON.stringify(design);node.signature=JSON.stringify([design,next.composition,b.instrumentOverrides,b.parameterValues,b.layoutTabs]);node.range=b.range;
 document.dispatchEvent(new CustomEvent('browser:interaction'));rendering();return remote;
}
// A Browser with no layout has nothing to load: it says so instead of Loading forever.
/** The Browser process an open Browser window runs in (its id on this Terminal), or null before it starts. */
export function remoteIdOf(id){return nodes.get(id)?.remoteId||null;}
export function browserState(b){const state=nodes.get(b.id)?.state||{status:runtime.user?(b.customLayout?'loading':'empty'):'Sign in to retrieve data',results:{}};return b.layoutConflict?{...state,layoutConflict:b.layoutConflict}:state;}
export function browserRequirements(b){return browserState(b).entry?.design.dataRequirements||b.design.dataRequirements;}
export function browserPanels(b){return [...b.design.layout.children,...Object.values(browserState(b).nestedLayouts||{}).flatMap(entry=>entry.design.layout.children)];}
export function browserCompany(b){const values=Object.values(browserState(b).results||{});return values.flatMap(v=>v.rows||[]).find(r=>r.ticker===b.ticker&&r.name)?.name||b.ticker;}

// Editors may stay open while polling replaces a worker after a host restart.
// Resolve its current handle at submission, not when the dialog was opened.
async function requestBrowserInstance(b,suffix='',options={}){
 for(let attempt=0;attempt<2;attempt++){
  let node=nodes.get(b.id);
  if(node?.ready&&!node.remoteId)await node.ready;
  node=nodes.get(b.id);
  if(!latest.includes(b)||!node?.remoteId)throw new Error('Browser is connecting. Try again shortly.');
  try{
   const value=await api('/api/instances/'+node.remoteId+suffix,options);
   if(!suffix&&options.method==='PUT'){node.state=value;node.events?.accept(value);}
   return value;
  }catch(error){
   // This specific pool error occurs before execution. Do not replay other
   // failures, or resurrect an explicitly closed/view-only Browser.
   if(attempt||error.status!==404||error.detail!=='Browser unavailable in this Terminal window.'||node.viewOnly||!latest.includes(b))throw error;
   if(nodes.get(b.id)===node){node.signature=null;node.designSignature=null;syncBrowsers(latest,currentWorkspace,rendering);}
  }
 }
}
export function panelHTML(panel,b,style){
 const state=browserState(b);
 // A generic content page draws its own panels, references or not (a page of controls with fixed data has none).
 if(b.customLayout?.composition||b.customLayout?.baseLayoutId==='content'){const content=contentPanel(panel,b,state,style);requestAnimationFrame(()=>mountProtectedContent());if(content!==null)return content;}
 return uiHTML`<section class="template-panel" data-panel-id="${esc(panel.id)}"><p>Open publisher-provided content from an agent workspace.</p></section>`;
}
function replyText(value) {
 if(typeof value==='string') {try {const parsed=JSON.parse(value);if(parsed&&typeof parsed==='object')return replyText(parsed);}catch{}return value;}
 if(!value||typeof value!=='object')return String(value??'');
 for(const key of ['outgoing_text','answer','text','response','message','content','result','output'])if(value[key]!=null)return replyText(value[key]);
 return JSON.stringify(value,null,2);
}

// A short note in the Terminal's toast line.
function notice(text){const toast=document.getElementById('toast');if(!toast)return;toast.textContent=text;toast.classList.add('visible');clearTimeout(notice.timer);notice.timer=setTimeout(()=>toast.classList.remove('visible'),3500);}
// Plaza did not answer the trust check: the panels say so, and the Browser reloads once, a few seconds later, as ↻ would.
const trustRetries=new Map();
const refreshWatches=new Map();
// A ↻ the Terminal accepted that ends with only earlier data says so, as a ↻ it couldn't accept does.
function noticeFailedRefresh(browserId,entry,state){if(failedRefreshes(refreshWatches,browserId,entry.remoteId,state).length)notice(t('Couldn’t get new data. The panel still shows earlier data; press ↻ again once the connection is back.'));}
/** Panels that failed only because the user's own local source stopped answering reload by themselves once a local
 * source runs again, as one ↻ for each. A local source costs nothing; panels reading from Plaza still wait for ↻.
 * Retries back off from 15 seconds to 2 minutes. */
const LOCAL_DOWN='local-source-unreachable',localRetries=new Map();
export function localSourcePanels(state){
 if(state?.sourceMode==='snapshot')return [];
 return Object.entries(state?.content?.results||{}).filter(([,r])=>['unavailable','failed','stale'].includes(r?.status)&&r.reason===LOCAL_DOWN).map(([ref])=>ref);
}
export async function retryLocalSources(now=Date.now()){
 const waiting=[];
 for(const [id,entry] of nodes){
  const references=entry.remoteId&&!entry.cancelled?localSourcePanels(entry.state):[];
  if(!references.length){localRetries.delete(id);continue;}
  const last=localRetries.get(id);
  if(!last||now>=last.next)waiting.push([id,entry,references,last?.attempts||0]);
 }
 if(!waiting.length)return;
 let value;try{value=await api('/api/local-resources');}catch{return;}
 // Discovery lists what runs on this computer now.
 if(!(value?.resources||[]).some(r=>r.online===true))return;
 for(const [id,entry,references,attempts] of waiting){
  localRetries.set(id,{attempts:attempts+1,next:now+Math.min(15000*2**attempts,120000)});
  api('/api/instances/'+entry.remoteId+'/content',{method:'POST',body:{references}}).then(()=>rendering()).catch(()=>{});
 }
}
setInterval(()=>{if(!document.hidden)retryLocalSources().catch(()=>{});},15000);
/** The programs on this computer a layout's panels wait for because they are not answering (NOT_ANSWERING), by the id
 * each announces. Plaza is not asked about them: such a layout reloads by itself, as its ↻ would, once Bonjour lists one
 * of them again, and the Terminal checks it afresh then. Checked every 15 seconds while the window shows. */
export function stoppedPrograms(state){
 return [...new Set(Object.values(state?.content?.results||{}).filter(r=>r?.status==='unavailable'&&r.reason===NOT_ANSWERING&&typeof r.program==='string').map(r=>r.program))];
}
export async function retryStoppedPrograms(){
 const waiting=[...nodes].filter(([,entry])=>entry.remoteId&&!entry.cancelled&&stoppedPrograms(entry.state).length);
 if(!waiting.length)return [];
 let value;try{value=await api('/api/local-resources');}catch{return [];}
 const online=new Set((value?.resources||[]).filter(r=>r?.online===true).map(r=>r.id));
 const back=waiting.filter(([,entry])=>stoppedPrograms(entry.state).some(program=>online.has(program))).map(([id])=>id);
 if(!back.length)return [];
 // The Terminal reads this computer's programs afresh first, so the layout's check finds the one that came back.
 try{await api('/api/local-resources/scan',{method:'POST',body:{}});}catch{}
 for(const id of back)document.querySelector('[data-action="reload-phema"][data-id="'+CSS.escape(id)+'"]')?.click();
 return back;
}
setInterval(()=>{if(!document.hidden)retryStoppedPrograms().catch(()=>{});},15000);
// Each data panel's source menu: the sources this viewer can use for its data and the one chosen, read once the
// Browser's content is connected (the Terminal's per-panel source choice; the layout itself is unchanged).
async function loadPanelSources(b,entry){
 if(!b||!entry?.remoteId||entry.viewOnly||b._panelSourcesFor===entry.remoteId)return;
 b._panelSourcesFor=entry.remoteId;
 try{const answer=await api('/api/instances/'+entry.remoteId+'/sources');b.panelSources=answer?.byPanel||{};rendering();}
 catch{b._panelSourcesFor=null;}
}
document.addEventListener('change',async event=>{
 const select=event.target?.closest?.('select[data-panel-source]');if(!select)return;
 const [browserId,...parts]=select.dataset.panelSource.split('/'),reference=parts.join('/');
 const entry=nodes.get(browserId),b=latest.find(item=>item.id===browserId);
 if(!entry?.remoteId||!b){notice(t('This layout is still opening. Press ↻ again in a moment.'));return;}
 select.disabled=true;
 try{
  const answer=await api('/api/instances/'+entry.remoteId+'/content',{method:'POST',body:{operation:'source',source:select.value||null,reference}});
  // The Browser keeps the choice with its saved settings, as the content dialog's choice is kept.
  b.contentOverrides=normalizeContentOverrides(answer.contentOverrides);b.panelSources=answer.dataSources?.byPanel||b.panelSources;
  document.dispatchEvent(new CustomEvent('browser:interaction'));rendering();
 }catch(error){notice(error.message);rendering();}
 finally{select.disabled=false;}
});
function retryUnconfirmedTrust(b,state){
 if(!state?.security?.trustUnconfirmed||trustRetries.has(b.id))return;
 trustRetries.set(b.id,setTimeout(()=>{trustRetries.delete(b.id);document.querySelector('[data-action="reload-phema"][data-id="'+CSS.escape(b.id)+'"]')?.click();},5000));
}
document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-content-refresh],[data-content-settings],[data-content-config],[data-phema-permissions]');if(!button)return;
 const [browserId,...parts]=(button.dataset.contentRefresh||button.dataset.contentSettings||button.dataset.contentConfig||button.dataset.phemaPermissions).split('/');const reference=parts.join('/');let entry=nodes.get(browserId);
 // After a connection comes back the Browser is opened again; a ↻ pressed meanwhile runs once it is ready.
 if(!entry?.remoteId&&entry?.ready&&button.dataset.contentRefresh){button.disabled=true;try{await entry.ready;}catch{}finally{button.disabled=false;}entry=nodes.get(browserId);}
 // A Browser refused before its account approved this Terminal: ↻ asks again, and opens it once the account is approved.
 if(!entry?.remoteId&&entry?.notApproved&&button.dataset.contentRefresh){
  button.disabled=true;
  try{if(await checkApproval())await nodes.get(browserId)?.ready;}catch{}finally{button.disabled=false;}
  entry=nodes.get(browserId);
  if(!entry?.remoteId){notice(entry?.state?.error||t('This layout is still opening. Press ↻ again in a moment.'));return;}
 }
 if(!entry?.remoteId){if(button.dataset.phemaPermissions)notice(t('Permissions open once this layout has loaded.'));else if(button.dataset.contentRefresh)notice(t('This layout is still opening. Press ↻ again in a moment.'));return;}
 try{if(button.dataset.phemaPermissions){await openPhemaPermissions(entry.remoteId,api,change=>reloadAfterPermission(entry,latest.find(b=>b.id===browserId),change),button.closest('[data-browser]'));}else if(button.dataset.contentConfig){await openContentPolicy(entry.remoteId,reference,api,values=>{const b=latest.find(b=>b.id===browserId);if(b){b.contentOverrides=normalizeContentOverrides(values);document.dispatchEvent(new CustomEvent('browser:interaction'));}});}else if(reference){button.disabled=true;const answer=await api('/api/instances/'+entry.remoteId+'/content',{method:'POST',body:{references:[reference]}});watchRefresh(refreshWatches,browserId,entry.remoteId,reference,answer);rendering();}else await openContentSnapshots(entry.remoteId,api,snapshotId=>saveSnapshotScreenshot(browserId,snapshotId),values=>{const b=latest.find(b=>b.id===browserId);if(b){b.contentOverrides=normalizeContentOverrides(values);document.dispatchEvent(new CustomEvent('browser:interaction'));}});}
 catch(error){button.title=error.message;
  // A ↻ that can't reach its data says so, and the layout shows it still has the earlier data.
  if(button.dataset.contentRefresh&&reference){notice(t('Couldn’t get new data. The panel still shows earlier data; press ↻ again once the connection is back.'));if(entry.state&&(!error.status||error.status>=500)){entry.state.transport='Reconnecting';rendering();}}}
 finally{button.disabled=false;}
});
function renderMessages(messages) {return messages.map(m=>uiHTML`<article class="conversation-message"><strong>${m.role==='user'?label('You'):esc(runtime.catalog.publishers.find(p=>p.id===m.agentId)?.name||t('Pulser'))}${m.pulseName?' · '+esc(m.pulseName):''}</strong><div style="white-space:pre-wrap">${esc(replyText(m.text))}</div></article>`).join('');}
function rememberChat(form){
 const b=latest.find(b=>b.id===form.dataset.conversation);if(!b)return;
 const nodeId=form.elements.nodeId.value,prior=b.interactionDrafts?.[nodeId]||{};
 const active={agentId:form.elements.agentId.value,pulseId:form.elements.pulseId.value,text:form.elements.text.value,arguments:Object.fromEntries([...form.querySelectorAll('[data-argument]')].map(f=>[f.dataset.argument,f.value])),...(form.querySelector('[data-raw-arguments]')?{rawArguments:form.querySelector('[data-raw-arguments]').value}:{})};
 b.interactionDrafts=normalizeInteractionDrafts({...b.interactionDrafts,[nodeId]:{...active,targets:{...prior.targets,[targetKey(active.agentId,active.pulseId)]:active}}});
 document.dispatchEvent(new CustomEvent('browser:interaction'));
}
document.addEventListener('input',event=>{const form=event.target.closest('[data-conversation]');if(form&&!['agentId','pulseId'].includes(event.target.name))rememberChat(form);});
document.addEventListener('change',event=>{
 const form=event.target.closest('[data-conversation]');if(!form||!['agentId','pulseId'].includes(event.target.name)||form.dataset.pending)return;
 const b=latest.find(b=>b.id===form.dataset.conversation);if(!b)return;
 const nodeId=form.elements.nodeId.value,prior=b.interactionDrafts?.[nodeId]||{};
 const agentId=form.elements.agentId.value,pulseId=event.target.name==='agentId'?'':form.elements.pulseId.value;
 b.interactionDrafts=normalizeInteractionDrafts({...b.interactionDrafts,[nodeId]:{agentId,pulseId,targets:prior.targets||{}}});
 const surface=form.closest('dialog')||form.parentElement.parentElement;form.parentElement.outerHTML=discussionHTML(b,nodeId);applyUI(surface);document.dispatchEvent(new CustomEvent('browser:interaction'));
});
export function discussionHTML(b,nodeId='') {
 const child=browserPanels(b).find(n=>n.id===nodeId)||browserPanels(b).find(n=>n.type==='phemar'||n.template==='pulse-chat');
 if(!child)return uiHTML`<p>No Pulse chat in this layout.</p>`;
 const saved=b.interactionDrafts?.[child.id]||{},target=selectTarget(runtime.catalog,child,saved),requirement=browserRequirements(b).find(r=>r.id===child.requirementId);
 const history=(browserState(b).messages||b.messages||[]).filter(m=>m.nodeId===child.id&&(!m.agentId||m.agentId===target.agentId)&&(!m.pulseId||m.pulseId===target.pulse?.id));
 return uiHTML`<div class="settings-body pulse-chat"><h2>${esc(child.title||'Pulse chat')}</h2>${chatForm({catalog:runtime.catalog,child,saved,arguments:requirement?.arguments||{},draft:b.discussionDrafts?.[child.id]||'',browserId:b.id,snapshot:(browserState(b).sourceMode||b.sourceMode)==='snapshot',label})}<div class="conversation-history" data-conversation-result>${renderMessages(history)}</div></div>`;
}
document.addEventListener('submit',async e=>{
 const f=e.target.closest('[data-conversation]');if(!f)return;e.preventDefault();e.stopImmediatePropagation();if(f.dataset.pending)return;
 const feedback=f.querySelector('[role=status]'),out=f.parentElement.querySelector('[data-conversation-result]'),button=f.querySelector('[data-chat-submit]');
 try{
  const id=nodes.get(f.dataset.conversation)?.remoteId;if(!id)throw new Error('Sign in and wait for the Browser instance.');
  const argumentsValue=parseArguments([...f.querySelectorAll('[data-argument]')].map(field=>({key:field.dataset.argument,type:field.dataset.argumentType,value:field.value})),f.querySelector('[data-raw-arguments]')?.value);
  rememberChat(f);const body={nodeId:f.elements.nodeId.value,agentId:f.elements.agentId.value,pulseId:f.elements.pulseId.value,text:f.elements.text.value,arguments:argumentsValue};
  f.dataset.pending='true';const controls=[...f.elements].map(node=>[node,node.disabled]);controls.forEach(([node])=>node.disabled=true);f._controls=controls;setUIText(feedback,'Waiting for Pulser…');
  const r=await api('/api/instances/'+id+'/conversation',{method:'POST',body});
  const selected=r.messages.filter(m=>(!m.agentId||m.agentId===body.agentId)&&(!m.pulseId||m.pulseId===body.pulseId));out.innerHTML=renderMessages(selected);
  const b=latest.find(b=>b.id===f.dataset.conversation);if(b){b.messages=normalizeMessages([...(b.messages||[]).filter(m=>m.nodeId!==body.nodeId),...r.messages]);b.discussionDrafts??={};delete b.discussionDrafts[body.nodeId];const remote=nodes.get(b.id);if(remote?.state)remote.state.messages=b.messages;}
  f.elements.text.value='';rememberChat(f);setUIText(feedback,'Complete');
 }catch(error){clearUIText(feedback);feedback.textContent=error.message;}
 finally{delete f.dataset.pending;f._controls?.forEach(([node,disabled])=>node.disabled=disabled);delete f._controls;}
},true);

export async function attachBrowserInstance(id,onUpdate) {
 const remote=await api('/api/instances/'+encodeURIComponent(id));
 const b={customLayout:remote.phema?phemaToEntry(remote.phema):remote.entry,contentOverrides:remote.contentOverrides||{},instrumentOverrides:remote.instrumentOverrides||{},sourceMode:remote.sourceMode,layoutTabs:remote.layoutTabs||{},parameterValues:remote.parameterValues||{},uiLanguage:remote.uiLanguage||null,fieldBindings:remote.fieldBindings||{},refreshOverrides:remote.refreshOverrides||{},id:remote.id,layoutId:remote.entry.baseLayoutId,design:remote.entry.design,range:remote.range,command:remote.command,ticker:remote.entry.design.params.ticker?.default||remote.entry.design.params.tickers?.default?.join(' / ')||remote.entry.design.params.portfolioId?.default||''};
 try{const saved=JSON.parse(scopedStorage().getItem('browser-draft:'+b.id)||'{}');b.discussionDrafts=normalizeDiscussionDrafts(saved.discussionDrafts);b.interactionDrafts=normalizeInteractionDrafts(saved.interactionDrafts);}catch{}
 rendering=()=>onUpdate(b);
 latest.push(b);const entry={remoteId:remote.id,state:remote,viewOnly:true};nodes.set(b.id,entry);
 entry.events=watchBrowserInstance(api,hostedPath('/api/instances/'+remote.id,location),state=>{entry.state=state;retryUnconfirmedTrust(b,state);noticeFailedRefresh(b.id,entry,state);const contentChanged=b.sourceMode!==(entry.state.sourceMode||'parameters')||(entry.state.sourceMode==='snapshot'&&b.contentSnapshotId!==entry.state.content?.snapshotId);b.sourceMode=entry.state.sourceMode||'parameters';b.contentSnapshotId=b.sourceMode==='snapshot'?entry.state.content?.snapshotId:undefined;if(contentChanged)document.dispatchEvent(new CustomEvent('browser:interaction'));b.layoutTabs=entry.state.layoutTabs||{};b.parameterValues=entry.state.parameterValues||{};b.uiLanguage=entry.state.uiLanguage||null;b.fieldBindings=entry.state.fieldBindings||{};b.refreshOverrides=entry.state.refreshOverrides||{};b.customLayout=entry.state.phema?phemaToEntry(entry.state.phema):entry.state.entry;b.instrumentOverrides=entry.state.instrumentOverrides||{};b.contentOverrides=entry.state.contentOverrides||{};b.design=entry.state.entry.design;b.range=entry.state.range;b.command=entry.state.command;b.ticker=b.design.params.ticker?.default||b.design.params.tickers?.default?.join(' / ')||b.design.params.portfolioId?.default||'';onUpdate(b);},error=>{entry.state.transport='Reconnecting';if(error.status===404)entry.state.error='This browser instance has closed.';onUpdate(b);},{initial:remote});
 return b;
}

document.addEventListener('browser:interaction',()=>{for(const b of latest)if(nodes.get(b.id)?.viewOnly)try{scopedStorage().setItem('browser-draft:'+b.id,JSON.stringify({discussionDrafts:b.discussionDrafts,interactionDrafts:b.interactionDrafts}));}catch{}});

document.addEventListener('click',async event=>{
 const button=event.target.closest('[data-block-config],[data-block-refresh]');if(!button)return;
 const [browserId,id]=(button.dataset.blockConfig||button.dataset.blockRefresh).split('/');
 const b=latest.find(b=>b.id===browserId),remote=nodes.get(browserId);if(!b||!remote)return;
 const send=async body=>{const state=await requestBrowserInstance(b,'',{method:'PUT',body});b.fieldBindings=state.fieldBindings||{};b.refreshOverrides=state.refreshOverrides||{};document.dispatchEvent(new CustomEvent('browser:interaction'));rendering();};
 const dialog=document.createElement('dialog');dialog.className='connected-reader block-settings';dialog.dataset.uiLocale=b.uiLanguage||'';
 document.body.append(dialog);dialog.onclose=()=>dialog.remove();
 if(button.dataset.blockRefresh){
  button.disabled=true;
  try{await send({refreshRequirement:id});dialog.remove();}catch(error){dialog.innerHTML=uiHTML`<p role="alert">${esc(error.message)}</p><button data-dismiss>Close</button>`;dialog.querySelector('button').onclick=()=>dialog.close();dialog.showModal();}finally{button.disabled=false;}return;
 }
 const panel=browserPanels(b).find(p=>p.id===id);if(!panel){dialog.remove();return;}
 const reqs=browserRequirements(b).filter(r=>[panel.requirementId,...(panel.supplementalRequirementIds||[])].includes(r.id)&&r.mode!=='interactive');
 dialog.innerHTML=uiHTML`<form><h2>${label('{0} · Settings',message(panel.title))}</h2><p>Updates for this browser. App Consultant maintains the layout defaults.</p>${reqs.map(r=>uiHTML`<fieldset data-rid="${esc(r.id)}"><legend>${label(r.label)}</legend><label><input type="checkbox" name="useDefault" ${b.refreshOverrides?.[r.id]?'':'checked'}> ${label('Use App Consultant default ({0})',refreshMessage(r))}</label><div class="config-grid">${refreshFields(refreshPolicy(r,b.refreshOverrides))}</div></fieldset>`).join('')}<p>Manual waits for Refresh or Generate. Templates sharing a dataset share its schedule.</p><p role="alert"></p><footer><button type="button" data-dismiss>Cancel</button><button type="submit">Apply</button></footer></form>`;
 const update=()=>{for(const field of dialog.querySelectorAll('fieldset')){const useDefault=field.querySelector('[name="useDefault"]').checked,mode=field.querySelector('select');mode.disabled=useDefault;field.querySelector('[name="refreshSeconds"]').disabled=useDefault||mode.value!=='interval';}};
 dialog.onchange=update;update();dialog.querySelector('[data-dismiss]').onclick=()=>dialog.close();
 dialog.querySelector('form').onsubmit=async e=>{e.preventDefault();const overrides=normalizeRefreshOverrides(b.refreshOverrides);for(const field of dialog.querySelectorAll('fieldset')){const rid=field.dataset.rid;if(field.querySelector('[name="useDefault"]').checked)delete overrides[rid];else{const mode=field.querySelector('select').value;overrides[rid]={refreshMode:mode,...(mode==='interval'?{refreshSeconds:Number(field.querySelector('[name="refreshSeconds"]').value)}:{})};}}const submit=dialog.querySelector('[type="submit"]');submit.disabled=true;try{await send({refreshOverrides:overrides});dialog.close();}catch(error){dialog.querySelector('[role="alert"]').textContent=error.message;}finally{submit.disabled=false;}};
 dialog.showModal();
});

document.addEventListener('click',event=>{if(!event.target.closest('[data-market-defaults]'))return;const form=event.target.closest('form');for(const [key,value] of Object.entries(MARKET_DEFAULTS)){const field=form.elements[key==='flashDurationMs'?'flashDuration':key];if(typeof value==='boolean')field.checked=value;else field.value=key==='flashDurationMs'?value/1000:value;}setUIText(form.querySelector('[data-market-feedback]'),'Defaults restored. Save to apply.');});
window.addEventListener('storage',event=>{if(event.key===`retis-terminal:${new URL(runtime.plaza.url||location.origin).port}:${runtime.user?.id||'guest'}:${terminalWindow()}:market-appearance`){try{applyMarketAppearance(JSON.parse(event.newValue||'{}'));}catch{}}});
window.addEventListener('focus',async()=>{if(!runtime.user)return;try{const settings=await api('/api/settings');runtime.settings.preferences.displayTimezone=settings.preferences.displayTimezone;runtime.settings.preferences.specifiedTimezone=settings.preferences.specifiedTimezone;applyDisplayTimezone(settings.preferences.displayTimezone);runtime.settings.preferences.displayFormat=settings.preferences.displayFormat;applyDisplayFormat(settings.preferences.displayFormat);rendering();runtime.settings.preferences.marketAppearance=settings.preferences.marketAppearance;applyMarketAppearance(settings.preferences.marketAppearance);}catch{}});

window.addEventListener('storage',async event=>{if(event.key===`retis-terminal:${new URL(runtime.plaza.url||location.origin).origin}:${runtime.user?.id||'guest'}:${terminalWindow()}:display-timezone`&&runtime.user){try{const settings=await api('/api/settings');runtime.settings.preferences.displayTimezone=settings.preferences.displayTimezone;runtime.settings.preferences.specifiedTimezone=settings.preferences.specifiedTimezone;applyDisplayTimezone(settings.preferences.displayTimezone);rendering();}catch{}}});


export async function setBrowserLanguage(b,value){
 if(value!==null&&!validLocale(value))throw new Error('Unsupported UI language.');
 const node=nodes.get(b.id);
 if(node?.remoteId)await api('/api/instances/'+node.remoteId,{method:'PUT',body:{uiLanguage:value}});
 b.uiLanguage=value;
 document.dispatchEvent(new CustomEvent('browser:interaction'));
}

document.addEventListener('submit',async event=>{
 const form=event.target.closest('[data-phema-interaction]');if(!form)return;event.preventDefault();event.stopImmediatePropagation();
 const [browserId,...parts]=form.closest('[data-content-interaction]').dataset.contentInteraction.split('/'),reference=parts.join('/'),instance=nodes.get(browserId),status=form.querySelector('[role=status]'),submit=form.querySelector('[type=submit]');
 let nativeHandled=false;try{if(!instance?.remoteId)throw new Error('Browser is still initializing.');nativeHandled=await submitOperationForm({form,reference,instance,request:api,setStatus:setUIText,text:t});if(nativeHandled)return;const inputs=formInputs(form);submit.disabled=true;await api('/api/instances/'+instance.remoteId+'/content',{method:'POST',body:{operation:'interact',references:[reference],inputs}});setUIText(status,'Waiting for publisher…');}catch(error){status.textContent=error.message;}finally{if(!nativeHandled)submit.disabled=false;}
},true);

// Mode changes are drafts until the existing server-backed settings form is saved.
document.addEventListener('change',event=>{if(!event.target.matches('[name=timeZoneMode]'))return;const form=event.target.closest('[data-connected-form="time-display"]');if(!form)return;const specified=event.target.value==='specified';form.querySelector('[data-specified-zone]').hidden=!specified;form.elements.specifiedTimezone.disabled=!specified;});

export async function reloadBrowserPhema(b,{readLayout}={}) {
 if(!runtime.user)return {guest:true};
 return reloadPhemaOnly(b,{readLayout,request:(suffix='',options={})=>requestBrowserInstance(b,suffix,options),
  isCurrent:()=>latest.includes(b),entry:()=>({...b.customLayout,design:browserDesign(b.design,b.instrumentOverrides)}),
  accept:remote=>{const node=nodes.get(b.id);if(!node)return;node.state=remote;node.events?.accept(remote);
   const design=browserDesign(b.design,b.instrumentOverrides);node.designSignature=JSON.stringify(design);
   node.signature=JSON.stringify([design,b.customLayout?.composition,b.instrumentOverrides,b.parameterValues,b.layoutTabs]);
   node.range=b.range;rendering();}});
}

function mountProtectedContent(){
 mountContent();
 for(const form of document.querySelectorAll('[data-phema-interaction]')){
  const section=form.closest('[data-content-interaction]');if(!section)continue;
  const [browserId,...parts]=section.dataset.contentInteraction.split('/'),instance=nodes.get(browserId);
  if(instance?.remoteId)mountOperationRecovery({form,reference:parts.join('/'),instance,request:api,setStatus:setUIText,text:t});
 }
}

// Where a mounted view lives: its window and reference. A full re-render moves open views aside and puts them back
// at the next frame (composition-renderers.js keepMounted, panelHTML); meanwhile the view is outside its window, so it
// keeps the place it was mounted in. Walk of 2026-11-18: a view still starting up looked up its
// instance in that moment, found none and said "This view lost its Phema connection".
const viewPlaces=new WeakMap();
function viewPlace(root){
 const surface=root.closest('[data-content-interaction]');
 if(!surface)return viewPlaces.get(root)||{browserId:'',prefix:''};
 const [browserId,...path]=surface.dataset.contentInteraction.split('/'),place={browserId,prefix:path.filter(Boolean).join('/')};
 viewPlaces.set(root,place);return place;
}
export function compositionViewInstance(root){
 const {browserId,prefix}=viewPlace(root);
 return {instance:nodes.get(browserId),prefix};
}
// A mounted view's parameter values are Browser state: save them with the workspace and
// let the ordinary sync re-run the instance with them. Null removes a value.
export function setCompositionViewParameters(root,values){
 const {browserId}=viewPlace(root);
 const b=latest.find(item=>item.id===browserId);if(!b)throw new Error('This view is not open in a Browser.');
 const next={...(b.parameterValues||{})};
 for(const [key,value] of Object.entries(values)){if(value===null)delete next[key];else next[key]=structuredClone(value);}
 b.parameterValues=next;syncBrowsers(latest,currentWorkspace,rendering);
 document.dispatchEvent(new CustomEvent('browser:interaction'));
 return structuredClone(next);
}
// A viewer panel (a web page or picture the person chooses) keeps the choice as its page setting, as a view does.
document.addEventListener('phemacast:viewer-change',event=>{
 const {parameter,value}=event.detail||{};if(!parameter||!value)return;
 // A viewer panel sits in a Data Browser window, not in a view's frame: the window names the Browser it belongs to.
 const browserId=event.target?.closest?.('[data-browser]')?.dataset?.browser||'';
 const b=latest.find(item=>item.id===browserId);if(!b){console.warn('Viewer setting not kept: the panel is not in a Browser.');return;}
 b.parameterValues={...(b.parameterValues||{}),[parameter]:structuredClone(value)};syncBrowsers(latest,currentWorkspace,rendering);
 document.dispatchEvent(new CustomEvent('browser:interaction'));
});
// A control (phemacast:control.*) keeps page values as a viewer panel does, and asks for a reference's data as ↻
// does. Its actions are data from the Phema, checked here again: named values only, bounded, never credentials.
const CONTROL_VALUE=/^[A-Za-z][A-Za-z0-9_]{0,63}$/,CONTROL_SECRET=/password|secret|token|api.?key|credential|cookie|authorization/i;
const controlSecret=(value,depth=0)=>depth>12||(Array.isArray(value)?value.some(item=>controlSecret(item,depth+1)):value&&typeof value==='object'&&Object.entries(value).some(([key,item])=>CONTROL_SECRET.test(key)||controlSecret(item,depth+1)));
function controlBrowser(event){const id=event.target?.closest?.('[data-browser]')?.dataset?.browser||'';return latest.find(item=>item.id===id);}
function setControlValues(b,values){
 if(!values||typeof values!=='object'||Array.isArray(values))return false;
 const next={...(b.parameterValues||{})};let changed=false;
 for(const [key,value] of Object.entries(values).slice(0,64)){
  if(!CONTROL_VALUE.test(key))continue;
  if(value===null||value===undefined){if(Object.hasOwn(next,key)){delete next[key];changed=true;}continue;}
  if(JSON.stringify(value).length>280000||controlSecret(value))continue;
  if(JSON.stringify(next[key])!==JSON.stringify(value)){next[key]=structuredClone(value);changed=true;}
 }
 if(!changed)return false;
 b.parameterValues=next;syncBrowsers(latest,currentWorkspace,rendering);
 document.dispatchEvent(new CustomEvent('browser:interaction'));
 return true;
}
document.addEventListener('phemacast:control-parameters',event=>{
 const b=controlBrowser(event);if(!b){console.warn('Control values not kept: the panel is not in a Browser.');return;}
 setControlValues(b,event.detail?.values);
});
document.addEventListener('phemacast:control-action',async event=>{
 const detail=event.detail||{},b=controlBrowser(event);
 if(detail.kind==='message'){notice(String(detail.text||'').slice(0,2000));return;}
 // Between panels: a port's value to the link group, page values to another open Phema (openPhema is app.js's).
 if(detail.kind==='publish'){if(b&&typeof detail.port==='string')publishPort(b,detail.port,detail.value);return;}
 if(detail.kind==='setPanelParameters'){if(!setPanelParameters(detail.panel,detail.values))notice(t('That panel is no longer open.'));return;}
 if(detail.kind==='openPhema')return;
 if(!['refresh','runReference'].includes(detail.kind)||!b||typeof detail.reference!=='string'||!/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(detail.reference))return;
 let entry=nodes.get(b.id);
 try{await entry?.ready;await entry?.update;}catch{}
 entry=nodes.get(b.id);
 if(!entry?.remoteId){notice(t('This layout is still opening. Press ↻ again in a moment.'));return;}
 try{const answer=await api('/api/instances/'+entry.remoteId+'/content',{method:'POST',body:{references:[detail.reference]}});watchRefresh(refreshWatches,b.id,entry.remoteId,detail.reference,answer);rendering();}
 catch{notice(t('Couldn’t get new data. The panel still shows earlier data; press ↻ again once the connection is back.'));}
});
// The agents a viewer may choose for a pulse ($agents); a newly read list redraws the panels that show it.
configureAgentChoices({request:api,changed:()=>rendering?.()});
installSourceSettings({api});
installAgentTrust({api});
installScheduledRuns({api,signedIn:()=>!!(runtime.user||runtime.plaza.localOnly),onChange:()=>document.dispatchEvent(new CustomEvent('scheduled-runs:changed'))});
installAIApps({api,signedIn:()=>!!((runtime.user||runtime.plaza.localOnly)&&terminalWindow()),preferences:()=>runtime.settings?.preferences||{}});
