import {displayDateTime,displayTimezone} from './time-display.js';
import {mountTimeInputs} from './time-inputs.js';
import {ui as uiHTML,label,setUIText,t} from './i18n.js';
import {api,esc,runtime,connect} from './connected.js';
import {filterLedger,ledgerCSV,reservationTotals} from './transactions-model.js';
await connect();
const $=id=>document.getElementById(id),pageSize=50;
let data=null,page=0,loading=false;
const number=n=>Number(n).toLocaleString(),signed=n=>(n>0?'+':'')+number(n);
const date=value=>value?displayDateTime(value):'—';
// Beside the summary, whose credits and debits include reservations.
const RESERVATIONS='Reservations reduce available points. Reservation settlements and refunds restore or distribute held points; they are not provider earnings. Grouped net change combines the ledger entries for each execution. “No settlement in returned history” describes the returned ledger, not a confirmed refund entitlement.';
const amount=n=>uiHTML`<span class="ledger-amount ${n<0?'debit':n>0?'credit':''}">${signed(n)}</span>`;
const payees=rows=>[...new Set(rows.map(p=>p.provider_username).filter(Boolean))].join(', ')||'—';
// The agent an entry or execution paid or earned from, named as the Plaza directory lists it; never the entry type.
const agentCell=x=>x.agentLabel?esc(x.agentLabel):x.involvesAgent?label('Unlisted agent'):'—';
// Who reserved an execution's points; Plaza records the reserving Terminal's own registered name, which is not shown.
const RESERVED_BY={this:'Reserved by: this Terminal',other:'Reserved by: another Terminal'};
// Support references stay off the page; the button copies them (the CSV export keeps them too).
const reference=r=>[['Transaction',r.id],['Escrow',r.escrowId],['Request',r.request_id]].filter(([,v])=>v).map(([k,v])=>k+': '+v).join('\n');
function filters(){return {query:$('ledger-search').value,action:$('ledger-action').value,from:$('ledger-from').value,to:$('ledger-to').value,timeZone:displayTimezone()};}
function selectedRows(){return filterLedger(data?.rows||[],filters());}
function entryTable(rows){return uiHTML`<table class="ledger-table"><thead><tr><th>Date / time</th><th>Entry</th><th>Agent / registered recipient</th><th class="numeric">Change</th><th class="numeric">Balance</th><th>Reference & details</th></tr></thead><tbody>${rows.map(r=>uiHTML`<tr><td class="nowrap">${esc(date(r.created_at))}</td><td>${label(r.label)}<small>${label(r.sourceLabel||r.source)}</small></td><td>${agentCell(r)}<small>${esc(r.payees.length?payees(r.payees):r.counterparty||'—')}</small></td><td class="numeric">${amount(r.delta)}</td><td class="numeric">${number(r.credit_points)}<small>from ${number(r.previous_credit_points)}</small></td><td><details><summary>${label('Details')}</summary><p>${esc(r.reason)}</p>${RESERVED_BY[r.reservedBy]?uiHTML`<p>${label(RESERVED_BY[r.reservedBy])}</p>`:''}<dl><dt>Pulse</dt><dd>${esc(r.pulse||r.practice_id||'—')}</dd>${r.payees.map(p=>uiHTML`<dt>Registered payee</dt><dd>${p.provider_username?esc(p.provider_username):label('Not recorded')} · ${p.sameAccount?'Your signed-in account':'Different Plaza account'}</dd>`).join('')}</dl><button type="button" class="ledger-copy" data-copy-reference="${esc(r.id)}">${label('Copy reference')}</button></details></td></tr>`).join('')}</tbody></table>`;}
function renderRows(){
 if(!data)return;
 const rows=selectedRows(),grouped=$('ledger-view').value==='executions',ids=new Set(rows.map(r=>r.id));
 // A matching execution shows its full ledger so its net is never a filtered partial sum.
 const items=grouped?data.executions.filter(g=>g.entries.some(r=>ids.has(r.id))):rows;
 const pages=Math.max(1,Math.ceil(items.length/pageSize));page=Math.min(page,pages-1);const shown=items.slice(page*pageSize,(page+1)*pageSize);
 // A sign-up grant, a top-up or a transfer is grouped on its own but is not an execution.
 const runs=grouped?items.filter(g=>g.execution!==false).length:0;
 if(grouped&&runs<items.length)setUIText($('ledger-count'),'{0} executions · {1} other entries · {2} matching ledger entries',runs,items.length-runs,rows.length);
 else setUIText($('ledger-count'),grouped?'{0} executions · {1} matching ledger entries':'{0} entries · {1} matching ledger entries',items.length,rows.length);
 $('ledger-table').innerHTML=!shown.length?uiHTML`<p class="ledger-empty">No transactions match these filters.</p>`:grouped?uiHTML`<table class="ledger-table"><thead><tr><th>Date / time</th><th>Agent / registered recipient</th><th>Recorded status</th><th class="numeric">Net change</th><th>Ledger entries</th></tr></thead><tbody>${shown.map(g=>uiHTML`<tr><td class="nowrap">${esc(date(g.createdAt))}</td><td>${agentCell(g)}<small>${esc(g.payees.length?payees(g.payees):g.entries[0].counterparty||'—')}</small></td><td>${label(g.status)}</td><td class="numeric">${amount(g.net)}</td><td><details><summary>${label('{0} entries',g.entries.length)}</summary>${entryTable(g.entries)}</details></td></tr>`).join('')}</tbody></table>`:entryTable(shown);
 setUIText($('ledger-page'),'Page {0} of {1}',page+1,pages);$('ledger-previous').disabled=page===0;$('ledger-next').disabled=page===pages-1;$('ledger-export').disabled=!rows.length;
}
function renderSummary(){
 const s=data.summary,a=data.account,reserved=reservationTotals(data.rows);
 $('account-name').textContent=a.name;$('account-balance').textContent=number(a.balance);
 $('profile').innerHTML=uiHTML`<h2>Plaza identity</h2><dl class="profile-facts"><dt>Username</dt><dd>${esc(a.username)}</dd><dt>Plaza</dt><dd>${esc(a.plaza)}</dd><dt>Available points</dt><dd>${number(a.balance)}</dd></dl><p>All Data Browsers in this Terminal window use this Plaza account. Other Terminal windows can use different accounts.</p><p>Provider payments go to the agent’s registered Plaza owner. An agent running on your machine can still be registered to a different account.</p><a href="#transactions">View transaction history →</a><p><a href="./settings.html">Manage login and Terminal settings</a></p>`;
 $('ledger-summary').innerHTML=uiHTML`<div class="ledger-equation"><div><span>Opening balance</span><strong>${number(s.opening)}</strong></div><b>+</b><div><span>Credits</span><strong>${number(s.credits)}</strong></div><b>−</b><div><span>Debits</span><strong>${number(s.debits)}</strong></div><b>=</b><div><span>Closing balance</span><strong>${number(s.closing)}</strong></div><i aria-hidden="true"></i><div class="ledger-net"><span>Net change</span><strong>${amount(s.net)}</strong></div></div>${reserved.open?uiHTML`<p class="ledger-note">${label('Credits and debits include reservations: {0} points held before executions and {1} returned when they settled or were refunded. {2} points are still held for {3} executions with no settlement in this history; reconcile them from Points spending in Terminal settings. The payment entries are the charges, so one execution can add several entries here, while Points spending counts it once.',number(reserved.held),number(reserved.returned),number(reserved.open),reserved.openRuns)}</p>`:reserved.held||reserved.returned?uiHTML`<p class="ledger-note">${label('Credits and debits include reservations: {0} points held before executions and {1} returned when they settled or were refunded. These cancel out; the payment entries are the charges. So one execution can add several entries here, while Points spending in Terminal settings counts it once.',number(reserved.held),number(reserved.returned))}</p>`:''}<p class="ledger-note">${label(RESERVATIONS)}</p><p class="ledger-note">${label('{0} ledger entries returned by Plaza · {1} — {2}.',s.count,date(s.from),date(s.to))} ${label('Time zone: {0}',displayTimezone())}. ${label('Totals cover this returned period.')}</p>${!s.balanced?uiHTML`<p class="ledger-warning">The returned entries do not reconcile to the recorded closing balance. History may be incomplete.</p>`:''}${s.balanceChanged?uiHTML`<p class="ledger-warning">The current balance differs from the latest ledger entry. Refresh to check for newer entries.</p>`:''}${s.truncated?uiHTML`<p class="ledger-warning">${label('Only the latest {0} entries are shown. This is not the full account history.',s.limit)}</p>`:''}<details class="ledger-breakdown"><summary>Balance changes by entry type</summary><table class="ledger-table"><thead><tr><th>Entry type</th><th class="numeric">Count</th><th class="numeric">Net points</th></tr></thead><tbody>${data.actions.map(r=>uiHTML`<tr><td>${label(r.label)}</td><td class="numeric">${r.count}</td><td class="numeric">${amount(r.net)}</td></tr>`).join('')}</tbody></table></details>`;
 $('providers').innerHTML=uiHTML`<p class="ledger-note">These are the recipients recorded at payment time. Provider payments exclude temporary reservations. Different owner accounts do not credit your signed-in account.</p><table class="ledger-table"><thead><tr><th>Agent</th><th>Registered recipient</th><th>Account relationship</th><th class="numeric">Payments</th><th class="numeric">Points paid</th></tr></thead><tbody>${data.providers.map(p=>uiHTML`<tr><td>${p.agent?esc(p.agent):label('Unlisted agent')}</td><td>${esc(p.payee)}</td><td>${label(p.sameAccount===true?'Your account':p.sameAccount===false?'Different Plaza account':'Not recorded')}</td><td class="numeric">${p.calls}</td><td class="numeric">${number(p.points)}</td></tr>`).join('')||uiHTML`<tr><td colspan="5">No provider payments in this period.</td></tr>`}</tbody></table>`;
 const selected=$('ledger-action').value;$('ledger-action').innerHTML=uiHTML`<option value="">All types</option>`+data.actions.map(a=>uiHTML`<option value="${esc(a.action)}">${esc(t(a.label))} (${a.count})</option>`).join('');$('ledger-action').value=selected;
}
async function load(){
 if(loading)return;loading=true;$('ledger-refresh').disabled=true;setUIText($('account-status'),'Loading your Plaza ledger…');
 try{data=await api('/api/account/transactions');runtime.user=data.account;renderSummary();renderRows();setUIText($('account-status'),'Updated {0} · Read-only Plaza ledger',date(data.retrievedAt*1000));}
 catch(error){if(error.status===401||error.status===403){data=null;$('ledger-table').innerHTML='';$('ledger-summary').innerHTML='';$('providers').innerHTML='';$('profile').innerHTML='';$('account-balance').textContent='—';$('ledger-export').disabled=true;}$('account-status').innerHTML=uiHTML`<span class="ledger-warning">${esc(error.message)}</span> <a href="./settings.html">Account settings</a>${data?' · '+label('Previously loaded history is still displayed.'):''}`;}
 finally{loading=false;$('ledger-refresh').disabled=false;}
}
function route(){const profile=location.hash==='#profile';$('profile').hidden=!profile;$('transactions').hidden=profile;for(const id of ['profile','transactions'])$(id+'-link').setAttribute('aria-current',(id==='profile')===profile?'page':'false');}
const ledgerTime=mountTimeInputs([$('ledger-from'),$('ledger-to')],{onChange:()=>{if(data){renderSummary();renderRows();}}});
window.addEventListener('pagehide',()=>ledgerTime.dispose(),{once:true});
$('ledger-filters').addEventListener('submit',e=>e.preventDefault());
$('ledger-filters').addEventListener('input',()=>{page=0;renderRows();});
$('ledger-filters').addEventListener('reset',()=>{setTimeout(()=>{page=0;renderRows();},0);});
async function copyText(text){
 try{await navigator.clipboard.writeText(text);return;}catch{}
 const area=document.createElement('textarea');area.value=text;area.setAttribute('readonly','');area.style.position='fixed';area.style.opacity='0';document.body.append(area);area.select();document.execCommand('copy');area.remove();
}
function toast(key){
 document.querySelector('.ledger-toast')?.remove();
 const note=document.createElement('p');note.className='ledger-toast';note.setAttribute('role','status');note.innerHTML=label(key);document.body.append(note);setTimeout(()=>note.remove(),2500);
}
$('ledger-table').addEventListener('click',async event=>{
 const button=event.target.closest('[data-copy-reference]'),row=button&&data?.rows.find(r=>r.id===button.dataset.copyReference);
 if(!row)return;await copyText(reference(row));toast('Reference copied.');
});
$('ledger-previous').onclick=()=>{page--;renderRows();};$('ledger-next').onclick=()=>{page++;renderRows();};$('ledger-refresh').onclick=load;
$('ledger-export').onclick=()=>{const url=URL.createObjectURL(new Blob([ledgerCSV(selectedRows())],{type:'text/csv;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download='plaza-transactions-'+new Date().toISOString().slice(0,10)+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
window.addEventListener('hashchange',route);route();
api('/api/settings').then(result=>{const theme=result.preferences?.theme||'dark';document.documentElement.dataset.themePreference=theme;document.documentElement.dataset.theme=theme==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):({attas:'light',fugle:'dark'})[theme]||theme;}).catch(()=>{});
await load();
