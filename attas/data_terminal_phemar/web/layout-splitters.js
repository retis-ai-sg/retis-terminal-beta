/** The border a Phema's split container declares (phemacast/web/layout-split.js), drawn between its two panels: drag it,
 * press ← → on it, or hide a panel to a strip with its ‹ › buttons or a double-click. Where the person leaves it is
 * this window's state (`layoutSplits`), saved with the workspace; the Phema only gives the starting point. Phema Edit
 * shows the page's own grid, so panels move on whole cells there. */
import {ui as uiHTML,attribute} from './i18n.js';
import {layoutStyle} from './layout-geometry.js';
import {splitContainers,splitState,splitColumns,splitStyle,shareAt,normalizeSplits} from './layout-split.js';

const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const browserSplits=b=>b?.editMode||!b?.design?.layout?[]:splitContainers(b.customLayout,b.design.layout);
export const browserLayoutStyle=b=>layoutStyle(b.design.layout)+splitStyle(browserSplits(b),b.layoutSplits);

/** The panels a person hid to a strip, by panel id. */
export function hiddenPanels(b){
 const hidden=new Set();
 for(const split of browserSplits(b)){const state=splitState(split,b.layoutSplits?.[split.name]);if(state.collapsed)hidden.add(split[state.collapsed]);}
 return hidden;
}

export function splittersHTML(b){
 return browserSplits(b).map(split=>{
  const state=splitState(split,b.layoutSplits?.[split.name]),open=split.from+split.first;
  const place=state.collapsed==='panel1'?`grid-column:${split.from}/span ${split.first}`:state.collapsed==='panel2'?`grid-column:${open}/span ${split.second}`:`grid-column:${open}/span 1`;
  const toggle=(which,arrow,key,title)=>uiHTML`<button type="button" data-split-toggle="${which}" ${attribute('aria-label',key,title)} ${attribute('title',key,title)}>${arrow}</button>`;
  const buttons=split.fixed?'':state.collapsed==='panel1'?toggle('','›','Show {0}',split.title1):state.collapsed==='panel2'?toggle('','‹','Show {0}',split.title2)
   :toggle('panel1','‹','Hide {0}',split.title1)+toggle('panel2','›','Hide {0}',split.title2);
  return uiHTML`<section data-panel-id="split:${esc(split.name)}" class="layout-splitter${state.collapsed?' is-collapsed':''}${split.fixed?' is-fixed':''}" data-split-browser="${esc(b.id)}" data-split-name="${esc(split.name)}" role="separator" aria-orientation="vertical" tabindex="${split.fixed?-1:0}" aria-valuemin="5" aria-valuemax="95" aria-valuenow="${Math.round(state.distance*100)}" ${split.fixed?'':attribute('title','Drag to resize. Double-click to hide or show {0}.',split.title1)} style="${place};grid-row:${split.row}/span ${split.rowSpan}"><span class="layout-splitter-grip" aria-hidden="true"></span>${buttons?uiHTML`<span class="layout-splitter-buttons">${buttons}</span>`:''}</section>`;
 }).join('');
}

/** Pointer, keyboard and button handling for every window's borders; `changed(b)` redraws and saves that window. */
export function installSplitters(findBrowser,changed){
 let drag=null;
 const found=handle=>{const b=findBrowser(handle?.dataset.splitBrowser),split=b&&browserSplits(b).find(s=>s.name===handle.dataset.splitName);return split?{b,split}:null;};
 const keep=(b,split,state)=>{b.layoutSplits={...normalizeSplits(b.layoutSplits),[split.name]:{distance:state.distance,collapsed:state.collapsed}};changed(b);};
 const flip=(b,split,which)=>{const state=splitState(split,b.layoutSplits?.[split.name]);keep(b,split,{...state,collapsed:state.collapsed===which?'':which});};
 const show=(layout,b,override)=>{const columns=splitColumns(browserSplits(b),b.layoutSplits,override);layout.style.setProperty('--layout-columns',columns);layout.style.setProperty('grid-template-columns',columns);};
 const end=()=>{
  if(!drag)return;const {b,split,handle,state,moved}=drag;drag=null;
  handle.classList.remove('is-dragging');document.documentElement.classList.remove('layout-split-dragging');
  if(moved)keep(b,split,state);
 };
 document.addEventListener('pointerdown',event=>{
  const handle=event.target.closest?.('.layout-splitter');if(!handle||event.button!==0||event.target.closest('button'))return;
  const match=found(handle);if(!match||match.split.fixed||handle.classList.contains('is-collapsed'))return;
  const layout=handle.parentElement,box=id=>[...layout.children].find(n=>n.dataset.panelId===id)?.getBoundingClientRect();
  const one=box(match.split.panel1),two=box(match.split.panel2);if(!one||!two)return;
  drag={...match,handle,layout,left:one.left,width:two.right-one.left,x:event.clientX,moved:false,state:splitState(match.split,match.b.layoutSplits?.[match.split.name])};
  try{handle.setPointerCapture(event.pointerId);}catch{}
  handle.classList.add('is-dragging');document.documentElement.classList.add('layout-split-dragging');event.preventDefault();
 });
 document.addEventListener('pointermove',event=>{
  if(!drag)return;if(Math.abs(event.clientX-drag.x)>2)drag.moved=true;if(!drag.moved)return;
  drag.state={distance:shareAt(drag.split,event.clientX,drag.left,drag.width),collapsed:''};
  show(drag.layout,drag.b,{[drag.split.name]:drag.state});drag.handle.setAttribute('aria-valuenow',String(Math.round(drag.state.distance*100)));
 });
 for(const type of ['pointerup','pointercancel'])document.addEventListener(type,end);
 window.addEventListener('blur',end);
 document.addEventListener('click',event=>{
  const button=event.target.closest?.('.layout-splitter [data-split-toggle]');if(!button)return;
  const match=found(button.closest('.layout-splitter'));if(!match||match.split.fixed)return;
  const state=splitState(match.split,match.b.layoutSplits?.[match.split.name]),which=button.dataset.splitToggle;
  keep(match.b,match.split,{...state,collapsed:which});
 });
 document.addEventListener('dblclick',event=>{
  const handle=event.target.closest?.('.layout-splitter');if(!handle||event.target.closest('button'))return;
  const match=found(handle);if(match&&!match.split.fixed)flip(match.b,match.split,splitState(match.split,match.b.layoutSplits?.[match.split.name]).collapsed||'panel1');
 });
 document.addEventListener('keydown',event=>{
  const handle=event.target.closest?.('.layout-splitter');if(!handle||event.target!==handle)return;
  const match=found(handle);if(!match||match.split.fixed)return;
  const state=splitState(match.split,match.b.layoutSplits?.[match.split.name]);
  if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();keep(match.b,match.split,{distance:Math.min(.95,Math.max(.05,state.distance+(event.key==='ArrowLeft'?-.02:.02))),collapsed:''});}
  else if(event.key==='Enter'){event.preventDefault();flip(match.b,match.split,state.collapsed||'panel1');}
  else return;
  // The redraw replaces the border; the keyboard stays on it.
  const again=()=>[...document.querySelectorAll('.layout-splitter')].find(n=>n.dataset.splitBrowser===handle.dataset.splitBrowser&&n.dataset.splitName===handle.dataset.splitName)?.focus();
  again();requestAnimationFrame(again);
 });
}
