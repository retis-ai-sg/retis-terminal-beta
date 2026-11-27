// A Terminal tab's own name. It is saved in this tab's Terminal settings and shown in
// the title bar and the browser tab, so several Terminal tabs can be told apart.
import {ui as uiHTML,t,attribute,setUIText} from './i18n.js';
import {runtime,api} from './connected.js';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// The tab is titled by the product: "Retis Terminal", or the kit's "Data Terminal" in the interface language. A session
// name goes in front ("Fugle · Retis Terminal"). A fixed "· Research workspace" after it read as the name of the
// workspace on screen (研究工作區 is also the default workspace's name), so it is gone.
const PRODUCT_TITLE='Data Terminal',NAMED_TITLE='{0} · Data Terminal',NAMED_PRODUCT='{0} · {1}';
// A package that names its Terminal (Retis Terminal for the desktop app) puts that name in the tab title, so it can be told
// apart from another Terminal in the same browser; the kit keeps "Data Terminal" in the interface language.
const product=()=>{const value=typeof runtime.product==='string'?runtime.product.trim():'';return value&&value!=='Data Terminal'?value:'';};

export function sessionName(){const value=runtime.settings?.preferences?.sessionName;return typeof value==='string'?value.trim():'';}

export function sessionNameTagHTML(){
 const name=sessionName();
 return `<span class="session-name" data-session-name-label ${name?'':'hidden'}>${esc(name)}</span>`;
}

export function applySessionName(){
 const name=sessionName(),title=document.querySelector('title');
 if(title){
  const app=product(),[key,args]=titleMessage(name,app);
  if(key){
   // The title keeps its message key, so a language change redraws it with the name.
   title.dataset.uiKey=key;title.dataset.uiArgs=JSON.stringify(args.map(esc));
   title.textContent=t(key,...args);
  }else{
   // A product's own name is not translated: nothing to redraw.
   delete title.dataset.uiKey;delete title.dataset.uiArgs;
   title.textContent=app;
  }
 }
 document.querySelectorAll('[data-session-name-label]').forEach(node=>{node.textContent=name;node.hidden=!name;});
}

/** [message key, arguments] of a tab's title, or [null] for a product's own name as it is. */
export function titleMessage(name,app){
 if(name)return app?[NAMED_PRODUCT,[name,app]]:[NAMED_TITLE,[name]];
 return app?[null,[]]:[PRODUCT_TITLE,[]];
}

export function sessionNameSettingsHTML(){
 return uiHTML`<form class="session-name-setting" data-session-name-form><h3>Session name</h3><div class="session-name-row"><input name="sessionName" maxlength="60" value="${esc(sessionName())}" ${attribute('aria-label','Session name')} ${attribute('placeholder','e.g. Morning research')}><button class="button" type="submit">Save name</button></div><small>Shown in the title bar and the browser tab.</small><p data-session-name-feedback role="status"></p></form>`;
}

document.addEventListener('submit',async event=>{
 const form=event.target.closest?.('[data-session-name-form]');if(!form)return;
 event.preventDefault();event.stopImmediatePropagation();
 const feedback=form.querySelector('[data-session-name-feedback]'),button=form.querySelector('[type="submit"]');
 button.disabled=true;
 try{
  const saved=await api('/api/settings',{method:'PUT',body:{sessionName:form.elements.sessionName.value}});
  runtime.settings.preferences={...runtime.settings.preferences,sessionName:saved.sessionName||''};
  form.elements.sessionName.value=sessionName();applySessionName();setUIText(feedback,'Saved.');
 }catch(error){feedback.textContent=error.message;}finally{button.disabled=false;}
},true);
