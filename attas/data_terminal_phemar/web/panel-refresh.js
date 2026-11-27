import {scopedUIBundles} from './phema-i18n.js';
import {applyUI,resolvedLocale} from './i18n.js';
import {captureValueState,flashChangedValues} from './market-appearance.js';
/** Keep an open native source menu attached while other panels receive updates. */
export function sourceControlBusy(panel,activeElement){
 return Boolean(panel.querySelector('[data-source-saving]') ||
   (activeElement?.matches?.('select[data-requirement-source]') || activeElement?.matches?.('select[data-source-type]')) && panel.contains(activeElement));
}
/** The address a person is typing in a viewer panel's box and has not sent yet (the panel marks it `data-typing`), and
 * whether the box has focus: a redraw that lands meanwhile, such as the one for the address they sent a moment ago,
 * must not refill the box or take the caret away. A box nobody is typing in shows what is drawn. */
export function typedAddress(panel,activeElement){
 const box=panel?.querySelector?.('[data-viewer-url]');
 if(!box)return null;
 const focused=activeElement===box,typed=box.dataset?.typing==='1';
 return typed||focused?{value:typed?box.value:null,focused,start:box.selectionStart,end:box.selectionEnd}:null;
}
/** Put what `typedAddress` kept back into the redrawn panel's box, still marked as being typed. */
export function keepTyping(panel,kept){
 const box=kept&&panel?.querySelector?.('[data-viewer-url]');
 if(!box)return;
 if(kept.value!==null){box.value=kept.value;box.dataset.typing='1';}
 if(kept.focused){box.focus();try{box.setSelectionRange(kept.start,kept.end);}catch{}}
}
function refreshAnalystIdentity(panel,fresh){
 const identity=panel.querySelector(':scope > .analyst-identity');
 const next=fresh.querySelector(':scope > .analyst-identity');
 if(identity?.outerHTML===next?.outerHTML)return;
 if(!next){identity?.remove();return;}
 if(identity)identity.replaceWith(next);
 else panel.querySelector(':scope > .panel-heading')?.after(next);
}
export function refreshPanels(container,html){
 const template=container.ownerDocument.createElement('template');template.innerHTML=html;applyUI(template.content,resolvedLocale(container),scopedUIBundles(container));
 const next=[...template.content.children],ids=new Set(next.map(panel=>panel.dataset.panelId));
 for(const panel of [...container.children])if(!ids.has(panel.dataset.panelId))panel.remove();
 for(const fresh of next){
  const old=[...container.children].find(panel=>panel.dataset.panelId===fresh.dataset.panelId);
  if(!old){container.append(fresh);continue;}
  if(old.dataset.contentRender&&old.dataset.contentRender===fresh.dataset.contentRender){
   // Publisher metadata may arrive after the media. Keep the player attached; its place (a moved or hidden panel) follows.
   if(old.getAttribute('style')!==fresh.getAttribute('style'))old.setAttribute('style',fresh.getAttribute('style')||'');
   refreshAnalystIdentity(old,fresh);continue;
  }
  // Editor handles are decoration, not data. Their presence must not force
  // unchanged panels (including players) to remount on every poll.
  let comparable=old;
  if(old.querySelector('[data-phema-handles]')){comparable=old.cloneNode(true);comparable.querySelectorAll('[data-phema-handles]').forEach(n=>n.remove());}
  if(sourceControlBusy(old,container.ownerDocument.activeElement)||comparable.outerHTML===fresh.outerHTML)continue;
  const nested=old.querySelector(':scope > .nested-phema-layout'),nextNested=fresh.querySelector(':scope > .nested-phema-layout');
  if(nested&&nextNested){old.setAttribute('style',fresh.getAttribute('style')||'');nested.setAttribute('style',nextNested.getAttribute('style')||'');nested.dataset.phemaUi=nextNested.dataset.phemaUi||'{}';const heading=old.querySelector(':scope > .panel-heading'),nextHeading=fresh.querySelector(':scope > .panel-heading');if(heading.outerHTML!==nextHeading.outerHTML)heading.replaceWith(nextHeading);refreshPanels(nested,nextNested.innerHTML);continue;}
  const content=old.querySelector(':scope > [data-tab-content]'),nextContent=fresh.querySelector(':scope > [data-tab-content]');
  if(content&&nextContent){
   old.setAttribute('style',fresh.getAttribute('style')||'');
   const nav=old.querySelector(':scope > nav'),nextNav=fresh.querySelector(':scope > nav');
   if(nav.outerHTML!==nextNav.outerHTML){
    const focused=nav.contains(container.ownerDocument.activeElement)?container.ownerDocument.activeElement.id:null;
    nav.replaceWith(nextNav);if(focused)container.ownerDocument.getElementById(focused)?.focus();
   }
   for(const attr of ['style','aria-labelledby'])content.setAttribute(attr,nextContent.getAttribute(attr)||'');
   refreshPanels(content,nextContent.innerHTML);continue;
  }
  const scrolls=[...old.querySelectorAll('.connected-table-scroll')].map(n=>[n.scrollLeft,n.scrollTop]);
  const details=[...old.querySelectorAll('details')].map(n=>n.open);
  const values=captureValueState(old),typing=typedAddress(old,container.ownerDocument.activeElement);
  old.replaceWith(fresh);
  keepTyping(fresh,typing);
  flashChangedValues(values,fresh);
  fresh.querySelectorAll('.connected-table-scroll').forEach((n,i)=>{n.scrollLeft=scrolls[i]?.[0]||0;n.scrollTop=scrolls[i]?.[1]||0;});
  fresh.querySelectorAll('details').forEach((n,i)=>{n.open=details[i]||false;});
 }
}
