// The page an AI app opens to sign in to this Terminal (mcp_access.py). It signs nothing in itself: it waits until a
// person chooses Allow or Deny in one of this Terminal's windows, then sends the browser back to the AI app.
import {setLocale,t} from './i18n.js';
const preferred=(navigator.languages||[navigator.language||'en']).map(String);
const pick=preferred.map(l=>/^zh-(TW|HK|MO|Hant)/i.test(l)?'zh-Hant':/^zh/i.test(l)?'zh-Hans':l.slice(0,2)).find(l=>['en','zh-Hant','zh-Hans','ja','es','fr'].includes(l))||'en';
setLocale(pick,{persist:false});
const status=document.getElementById('status'),request=new URLSearchParams(location.search).get('request')||'';
const say=(key,...args)=>{status.textContent=t(key,...args);};
async function poll(){
 try{
  const reply=await fetch('/api/mcp/requests/'+encodeURIComponent(request)+'/status',{cache:'no-store'});
  const value=await reply.json();
  if(value.status==='decided'){say('Done. Returning to the AI app…');location.replace(value.redirect);return;}
  if(value.status==='ended'){say('This sign-in request has ended. Start again from the AI app.');return;}
  // This page opened in a new tab, in front of the Terminal's own: say plainly where the Allow is.
  say('Switch to your Terminal window or tab: {0} is waiting there for your Allow.',value.clientName||t('An AI app'));
 }catch{say('Waiting for this Terminal…');}
 setTimeout(poll,1500);
}
if(/^r-[0-9a-f]{32}$/.test(request))poll();else say('This sign-in request has ended. Start again from the AI app.');
