// What an approved AI app asks this window to show (mcp_access.py, stage 2): open a Phema, set its parameters,
// arrange, close, save a workspace. The page waits for commands with a long poll, which keeps working while the tab is
// in the background, runs each with the page's own actions (the same ones a click uses) and answers. It runs nothing
// the window could not do itself, and only for this window's own approved apps.
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));

export function installAICommands(host){
 let failures=0,running=false;
 async function loop(){
  if(running)return;running=true;
  while(true){
   if(!host.signedIn()){await wait(3000);continue;}
   let reply;
   try{reply=await host.api('/api/mcp/commands/next');failures=0;}
   catch(error){
    if(error.status===404||error.status===403){await wait(60000);continue;}  // no AI apps here, or not a window yet
    failures++;await wait(Math.min(30000,1000*2**Math.min(failures,5)));continue;
   }
   // A server that answered at once without waiting is not a Terminal that serves AI apps: try again later.
   if(!reply||reply.waited!==true){await wait(30000);continue;}
   const command=reply.command;if(!command||typeof command.id!=='string')continue;
   let answer;
   try{answer={ok:true,result:await host.run(String(command.kind||''),command.args&&typeof command.args==='object'?command.args:{},typeof command.by==='string'?command.by.slice(0,80):'')};}
   catch(error){answer={ok:false,error:String(error?.message||error)};}
   await host.api('/api/mcp/commands/'+encodeURIComponent(command.id),{method:'POST',body:answer}).catch(()=>{});
  }
 }
 loop();
}

// "<app> asks to spend up to N more points today": the person's Allow or Deny for more than the AI points budget, in
// the middle of the window where the person sees it (Alvin, 2026-11-27), as the sign-in and action cards are.
// It never blocks the page; an unanswered request counts as Deny before the Terminal stops waiting for it.
export function askToSpend({by,points,what},{label,esc,html}){
 return new Promise(resolve=>{
  const card=document.createElement('div');card.setAttribute('role','alertdialog');card.dataset.aiSpendRequest='';
  card.style.cssText='position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:1001;width:min(24rem,calc(100vw - 32px));box-sizing:border-box;padding:16px;background:var(--raised);color:var(--text);border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.35)';
  card.innerHTML=html`<p><strong>${label('{0} asks to spend up to {1} more points today.',esc(by||'An AI app'),Number(points)||0)}</strong></p><p class="muted">${label('For: {0}',esc(what||''))}</p><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px"><button type="button" class="button subtle" data-spend="deny">${label('Deny')}</button><button type="button" class="button primary" data-spend="allow">${label('Allow')}</button></div>`;
  let done=false;const finish=allowed=>{if(done)return;done=true;card.remove();resolve(allowed);};
  card.addEventListener('click',event=>{const button=event.target.closest('[data-spend]');if(button)finish(button.dataset.spend==='allow');});
  setTimeout(()=>finish(false),110000);
  document.body.append(card);
 });
}

// How Undo puts back an AI app's edit in an agent view, from the view's answer (`undo`): another of its declared edit
// actions and that action's input, run through the view's own code ({action, input}); or 'parameters', when the change
// lives only in the window's parameter values ({parameters: true}). null: the window offers no Undo, since writing
// parameters back can't reach what a view keeps elsewhere (live 2026-11-27, Taiwan Semiconductor Watch).
export function viewUndo(handle,value){
 const undo=value&&typeof value==='object'&&!Array.isArray(value)?value.undo:null;
 if(undo==='parameters')return {parameters:true};
 if(!undo||typeof undo!=='object'||Array.isArray(undo)||typeof undo.action!=='string')return null;
 const input=undo.input===undefined?{}:undo.input;
 if(!input||typeof input!=='object'||Array.isArray(input))return null;
 let declared=[];try{declared=typeof handle?.actions==='function'?handle.actions():[];}catch{}
 if(!Array.isArray(declared)||!declared.some(item=>item?.id===undo.action&&item.effect==='edit'))return null;
 try{return {action:undo.action,input:JSON.parse(JSON.stringify(input))};}catch{return null;}
}

// "<app> changed <view>." with Undo for 60 s: an AI app's edit in an agent view (mcp_access.py view_action). Long
// enough for a person who reads the AI app's answer before looking at the window (Alvin, 2026-11-27: 60, not 30).
export function undoToast({text,onUndo,seconds=60},{label,html}){
 document.querySelector('[data-ai-undo]')?.remove();
 const card=document.createElement('div');card.setAttribute('role','status');card.dataset.aiUndo='';
 card.style.cssText='position:fixed;bottom:16px;left:50%;transform:translateX(-50%);z-index:1001;display:flex;gap:12px;align-items:center;max-width:min(32rem,calc(100vw - 32px));padding:10px 12px;background:var(--raised);color:var(--text);border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.35)';
 card.innerHTML=html`<span>${text}</span><button type="button" class="button subtle" data-ai-undo-button>${label('Undo')}</button>`;
 const close=()=>{clearTimeout(timer);card.remove();};
 const timer=setTimeout(close,seconds*1000);
 card.querySelector('[data-ai-undo-button]').addEventListener('click',async()=>{close();await onUndo();});
 document.body.append(card);
}

// "<app> asks to: <action>" with Allow and Deny, for an action whose owner asks every time (confirm: always).
export function askToAllow({by,what},{label,esc,html}){
 return new Promise(resolve=>{
  const card=document.createElement('div');card.setAttribute('role','alertdialog');card.dataset.aiActionRequest='';
  card.style.cssText='position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:1001;width:min(24rem,calc(100vw - 32px));box-sizing:border-box;padding:16px;background:var(--raised);color:var(--text);border:1px solid var(--line);border-radius:8px;box-shadow:0 6px 24px rgba(0,0,0,.35)';
  card.innerHTML=html`<p><strong>${label('{0} asks to: {1}',esc(by||'An AI app'),esc(what||''))}</strong></p><div style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px"><button type="button" class="button subtle" data-allow="deny">${label('Deny')}</button><button type="button" class="button primary" data-allow="allow">${label('Allow')}</button></div>`;
  let done=false;const finish=allowed=>{if(done)return;done=true;card.remove();resolve(allowed);};
  card.addEventListener('click',event=>{const button=event.target.closest('[data-allow]');if(button)finish(button.dataset.allow==='allow');});
  setTimeout(()=>finish(false),110000);
  document.body.append(card);
 });
}
