// Workspace history (workspace_history.py): Terminal settings choose how many ten-minute, daily, weekly and monthly
// versions a window keeps, on top of every minute for the last 10 minutes and every hour for the last 24 hours.
// After each save the page takes a small picture of the window area for that version, which the history list shows.
import {ui as html,label,currentLocale} from './i18n.js';
import {keep} from './ai-capture.js';
import {toJpeg} from './preview-raster.js';

export const TIERS=[['tenMinute','Ten-minute versions'],['daily','Daily versions'],['weekly','Weekly versions'],['monthly','Monthly versions']];
export const DEFAULTS={tenMinute:6,daily:7,weekly:4,monthly:6};
// A picture is at most 480 × 300 (the Terminal takes up to 640 × 400), taken once the window has been quiet a moment.
export const PICTURE_WIDTH=480,PICTURE_HEIGHT=300,QUIET_MS=4000;
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function historyCounts(value){
 const counts={...DEFAULTS};
 for(const [name] of TIERS)if(Number.isInteger(value?.[name])&&value[name]>=0&&value[name]<=999)counts[name]=value[name];
 return counts;
}

/** The Terminal settings section: four counts, the two fixed rules said once. */
export function workspaceHistorySettingsHTML(value){
 const counts=historyCounts(value);
 return html`<h3>Workspace history</h3><form data-connected-form="workspace-history" class="workspace-history-settings"><div class="market-color-fields">${TIERS.map(([name,text])=>html`<label>${label(text)}<input type="number" name="${name}" min="0" max="999" step="1" required value="${counts[name]}"></label>`).join('')}</div><p class="muted">${label('Every minute for the last 10 minutes and every hour for the last 24 hours are always kept.')}</p><button class="button" type="submit">Save workspace history</button></form>`;
}

export function workspaceHistoryValues(values){
 return Object.fromEntries(TIERS.map(([name])=>[name,Number(values[name])]));
}

// The year shows only for versions from another year.
const when=stamp=>{const date=new Date(stamp*1000);return date.toLocaleString(currentLocale(),{...(date.getFullYear()!==new Date().getFullYear()?{year:'numeric'}:{}),month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});};

function entryHTML(entry,current){
 return html`<li class="workspace-history-entry" data-history-revision="${entry.revision}"><figure class="workspace-history-picture" ${entry.picture?'data-history-picture':''}>${entry.picture?'':html`<span>${label('No picture')}</span>`}</figure><div class="workspace-history-meta"><time>${esc(when(entry.updatedAt))}</time>${current?html`<strong>${label('Current')}</strong>`:html`<button type="button" class="button" data-restore-revision="${entry.revision}">${label('Restore revision')}</button>`}</div></li>`;
}

/** The Workspace history dialog: the current version and each kept version with its picture, newest first. */
export async function openWorkspaceHistory({api,persist}){
 await persist();
 const [{records,current},settings]=await Promise.all([api('/api/workspace-state/revisions'),api('/api/settings')]);
 const counts=historyCounts(settings?.preferences?.workspaceHistory);
 const entries=[...records].sort((a,b)=>b.revision-a.revision);
 const dialog=document.createElement('dialog');dialog.className='config-dialog workspace-history-dialog';
 dialog.innerHTML=html`<header class="config-header"><h2>Workspace history</h2><button data-close-history aria-label="Close">×</button></header><div class="config-dialog-body"><p class="muted">${label('Kept: every minute for the last 10 minutes, every hour for the last 24 hours, and the last {0} ten-minute, {1} daily, {2} weekly and {3} monthly versions.',counts.tenMinute,counts.daily,counts.weekly,counts.monthly)}</p><ol class="workspace-history-list">${current?entryHTML(current,true):''}${entries.map(entry=>entryHTML(entry,false)).join('')}</ol><p data-history-status role="status"></p></div>`;
 document.body.append(dialog);dialog.showModal();dialog.addEventListener('close',()=>dialog.remove(),{once:true});
 dialog.addEventListener('click',async event=>{
  if(event.target.closest('[data-close-history]'))dialog.close();
  const value=event.target.closest('[data-restore-revision]')?.dataset.restoreRevision;
  if(value===undefined)return;
  try{await api('/api/workspace-state/rollback',{method:'POST',body:{previousRevision:Number(value),revision:current.revision}});location.reload();}
  catch(error){dialog.querySelector('[data-history-status]').textContent=error.message;}
 });
 // Pictures load after the list shows, a few at a time.
 const pending=[...dialog.querySelectorAll('[data-history-picture]')];
 const next=async()=>{
  for(let figure=pending.shift();figure;figure=pending.shift()){
   if(!dialog.isConnected)return;
   const revision=figure.closest('[data-history-revision]').dataset.historyRevision;
   try{const {image}=await api('/api/workspace-state/pictures/'+encodeURIComponent(revision));
    const img=document.createElement('img');img.src=image;img.alt='';img.loading='lazy';figure.replaceChildren(img);}
   catch{figure.innerHTML=html`<span>${label('No picture')}</span>`;}
  }
 };
 await Promise.all([next(),next(),next()]);
 return dialog;
}

/** Takes a picture of the window area once saves have been quiet for a moment, and files it with that version. */
export function historyPictures({api,area,revision,enabled=()=>true,quiet=QUIET_MS}){
 let timer=null,busy=false;
 const take=async()=>{
  timer=null;
  const node=area(),saved=revision();
  if(busy||!enabled()||document.hidden||!node||!Number.isInteger(saved))return;
  const width=node.clientWidth,height=node.clientHeight;if(!width||!height)return;
  const scale=Math.min(1,PICTURE_WIDTH/width,PICTURE_HEIGHT/height);
  busy=true;
  try{
   const image=await toJpeg(node,{width,height,canvasWidth:Math.round(width*scale),canvasHeight:Math.round(height*scale),pixelRatio:1,skipFonts:true,quality:.6,
    filter:n=>keep(n),backgroundColor:getComputedStyle(node).backgroundColor||getComputedStyle(document.body).backgroundColor});
   // Only file it if nothing was saved while the picture was drawn.
   if(revision()===saved)await api('/api/workspace-state/pictures/'+saved,{method:'PUT',body:{image}});
  }catch{}
  finally{busy=false;}
 };
 return {saved(){clearTimeout(timer);timer=setTimeout(take,quiet);},take};
}
