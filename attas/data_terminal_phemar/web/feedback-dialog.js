import {ui,label,applyUI,setUIText} from './i18n.js';
/** Send feedback: one message from this window's Plaza account to its site's support, delivered by that Plaza
 * (feedback.py). The Terminal keeps nothing and holds no mail settings; the dialog shows everything it will send. */
const DETAILS=['terminal_version','language','plaza_host','phema_name'];
export const FEEDBACK_CHARACTERS=5000;
const EMAIL=/^[^@\s<>()[\],;:"\\]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?)+$/;
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
/** When the limit lets this account send again, in the viewer's language and time zone. */
function when(ms,locale){
 if(!ms)return '';
 try{return new Intl.DateTimeFormat(locale,{hour:'2-digit',minute:'2-digit',...(ms-Date.now()>12*3600000?{month:'short',day:'numeric'}:{})}).format(ms);}
 catch{return new Date(ms).toISOString().slice(0,16).replace('T',' ');}
}
export function openFeedbackDialog({request,facts={},account='',now=()=>Date.now()}){
 const dialog=document.createElement('dialog');dialog.className='connected-reader feedback-dialog';dialog.setAttribute('aria-labelledby','feedback-title');
 const known=DETAILS.filter(key=>facts[key]),shown=key=>facts[key]?esc(facts[key]):label('Not known');
 dialog.innerHTML=ui`<h2 id="feedback-title">Send feedback</h2>
  <div class="feedback-row"><label class="feedback-category">Category<select data-category><option value="bug">Bug</option><option value="idea">Idea</option><option value="question">Question</option></select></label>
  <label class="feedback-reply">Reply to<input type="email" data-reply maxlength="254" autocomplete="email" spellcheck="false" value="${esc(account)}" placeholder="name@example.com"></label></div>
  <label class="feedback-message">Message<textarea data-message rows="6" maxlength="${FEEDBACK_CHARACTERS}" placeholder="Describe the bug, idea or question."></textarea></label>
  <small class="feedback-count" data-count>0 / ${FEEDBACK_CHARACTERS}</small>
  <fieldset class="feedback-details"><label class="feedback-check"><input type="checkbox" data-details ${known.length?'checked':'disabled'}> Include technical details</label>
  <dl><dt>Terminal version</dt><dd>${shown('terminal_version')}</dd><dt>Language</dt><dd>${shown('language')}</dd><dt>Plaza host</dt><dd>${shown('plaza_host')}</dd><dt>Current Phema</dt><dd>${shown('phema_name')}</dd></dl></fieldset>
  <p class="feedback-note">Keys, tokens and access links are removed before sending.</p>
  <div class="feedback-actions"><p role="status" data-status></p><button type="button" class="button" data-close>Close</button><button type="button" class="button primary" data-send>Send</button></div>`;
 const $=selector=>dialog.querySelector(selector),status=$('[data-status]'),send=$('[data-send]'),message=$('[data-message]');
 let said='';
 const say=(key,kind='',...args)=>{said=key||'';if(key)setUIText(status,key,...args);else status.textContent='';if(kind)status.dataset.kind=kind;else delete status.dataset.kind;};
 message.oninput=()=>{$('[data-count]').textContent=message.value.length+' / '+FEEDBACK_CHARACTERS;if(status.dataset.kind==='done')say('');};
 // A reply-to address that was refused clears its message once it is a usable address again (or left empty).
 $('[data-reply]').oninput=event=>{const value=event.target.value.trim();if(said==='Enter one email address to reply to.'&&(!value||EMAIL.test(value)))say('');};
 $('[data-details]').onchange=event=>{$('.feedback-details dl').toggleAttribute('data-off',!event.target.checked);};
 $('[data-close]').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();
 send.onclick=async()=>{
  const text=message.value,reply=$('[data-reply]').value.trim();
  if(!text.trim()){say('Write a message first.','error');message.focus();return;}
  if(reply&&!EMAIL.test(reply)){say('Enter one email address to reply to.','error');$('[data-reply]').focus();return;}
  const details=$('[data-details]').checked&&known.length?Object.fromEntries(known.map(key=>[key,String(facts[key])])):undefined;
  send.disabled=true;say('Sending…');
  try{
   const result=await request('/api/feedback',{method:'POST',body:{category:$('[data-category]').value,message:text,...(reply?{reply_to:reply}:{}),...(details?{details}:{})}});
   if(result?.status==='sent'){message.value='';message.oninput();say('Sent. Thank you! Replies go to {0}.','done',result.replyTo||reply||account);return;}
   if(result?.status==='limited'){
    const time=when(result.retryAt,document.documentElement.lang||'en');
    say(result.window==='day'?'You have sent {0} messages in the last 24 hours. Try again after {1}.':'You have sent {0} messages in the last hour. Try again after {1}.','error',String(result.count||''),time);return;
   }
   say('Not sent: {0}','error','');
  }catch(error){say('Not sent: {0}','error',String(error?.message||error));}
  finally{send.disabled=false;}
 };
 document.body.append(dialog);applyUI(dialog);dialog.showModal();message.focus();
 return dialog;
}
