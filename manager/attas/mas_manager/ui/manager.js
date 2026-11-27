/* Retis MAS Manager view. It runs in the Terminal's confined frame and reaches the manager on this computer
 * only through the Phema's one composition reference (bridge.invoke). The manager keeps no Terminal data. */
(()=>{
const REFERENCE='mas-manager';
const STATES={not_installed:'Not installed',installing:'Installing',stopped:'Stopped',starting:'Starting',running:'Running',
 needs_data:'Needs data',unhealthy:'Unhealthy',restarting:'Restarting',waiting:'Waiting'};
// What a row says while a start, stop, restart, removal or roll back it asked for is under way.
const OPERATIONS={start:'Starting…',stop:'Stopping…',restart:'Restarting…',remove:'Removing…',rollback:'Rolling back…'};
// The manager's own reasons beside a state, in the viewer's language. A reason a component gives is shown as it is.
// Only the app hands over what the bundled Terminal needs (its key): after a restart of this computer it waits for it.
const REASONS={'waiting for handover':'Starts when you open Retis Terminal','port closed':'Not answering','keeps crashing':'Keeps crashing','not ready':'Not ready','loading':'Loading',
 'health check answered in an unknown format':'Its health check answered in an unknown format'};
// Components the viewer depends on while this page is open: an update asks before restarting them.
const ASK_BEFORE_RESTART=new Set(['terminal']);
const HELP=['Each row is one Retis component on this computer: install it, update it, start or stop it, or read its log.',
 'Updates install beside the current version; Roll back returns to the previous one.',
 'Large data never comes with a component: a component that says Needs data offers its own download.',
 'A component works in your Terminal as soon as it runs: no sign-in or pairing.',
 'Remove keeps the component\'s data unless you untick Keep data.'];
const MESSAGES={
 'Refresh':'重新整理','Check for updates':'檢查更新','How to use':'使用說明','This computer':'這台電腦',
 'Component':'元件','Version':'版本','Status':'狀態','Actions':'操作',
 'Not installed':'未安裝','Installing':'安裝中','Stopped':'已停止','Starting':'啟動中','Running':'執行中','Needs data':'需要資料',
 'Unhealthy':'異常','Restarting':'重新啟動中','Waiting':'等待中','Starts when you open Retis Terminal':'開啟 Retis Terminal 時啟動',
 'Starting…':'啟動中…','Stopping…':'停止中…','Restarting…':'重新啟動中…','Removing…':'移除中…','Rolling back…':'復原中…',
 'Loading':'載入中','Not answering':'沒有回應','Keeps crashing':'一再當機','Not ready':'尚未就緒','Attempt {0}':'第 {0} 次嘗試',
 'Health check failed':'健康檢查失敗','Its health check answered in an unknown format':'健康檢查的回應格式無法辨識',
 'Component updates come with new Retis Terminal versions.':'元件更新隨 Retis Terminal 新版本提供。',
 'Install':'安裝','Update':'更新','Start':'啟動','Stop':'停止','Restart':'重新啟動','Roll back':'復原','Logs':'記錄','Remove':'移除',
 'Update to {0}':'更新至 {0}','Not offered for this computer':'此電腦無可用版本',
 'Accept and install':'同意並安裝','Accept and update':'同意並更新','Accept these terms first:':'請先同意以下條款：','Cancel':'取消',
 'Licences':'授權條款','and {0} more':'以及另外 {0} 個','Third-party notices':'第三方授權聲明','No notices.':'沒有授權聲明。',
 'Install downloads these from the Python Package Index (PyPI):':'安裝時會從 Python 套件索引（PyPI）下載以下程式庫：',
 'Restart now':'立即重新啟動','At next start':'下次啟動時','Restart {0} now to finish the update?':'立即重新啟動 {0} 以完成更新？',
 'Remove {0}?':'移除 {0}？','Keep data':'保留資料','Close':'關閉','Recent events':'最近事件','No events in the last 3 days.':'最近 3 天沒有事件。',
 'Parts list {0} · checked {1}':'元件清單 {0} · 檢查於 {1}','Updates not checked yet.':'尚未檢查更新。',
 'These are the licences of the open-source libraries {0} uses, as their authors published them (in English).':
  '以下是 {0} 使用的開源程式庫授權條款，依作者發布的原文（英文）列出。',
 'Last error: {0}':'最近錯誤：{0}','Updates at next start: {0}':'下次啟動時更新：{0}','{0} failed: {1}':'{0} 失敗：{1}',
 'The manager returned no result.':'管理員沒有回應。','Pending':'待處理','Retis MAS Manager':'Retis MAS 管理員',
 'Problem report':'問題回報','Report saved on this computer: {0}':'回報已存於這台電腦：{0}','Download data':'下載資料','Download {0}':'下載 {0}',
 'Stop download':'停止下載','Downloading: {0}':'下載中：{0}','Download finished':'下載完成','Download failed':'下載失敗',
 'CPU {0}% · memory {1}':'CPU {0}% · 記憶體 {1}','{0} on disk':'磁碟用量 {0}','{0} on disk ({1} data)':'磁碟用量 {0}（資料 {1}）','Data download':'資料下載','Free disk: {0}':'可用磁碟：{0}',
 '{0} keeps crashing.':'{0} 一再當機。','{0} has been unhealthy for a while.':'{0} 已異常一段時間。',
 '{0} could not download its data.':'{0} 無法下載資料。',
 'Each row is one Retis component on this computer: install it, update it, start or stop it, or read its log.':'每一列是這台電腦上的一個 Retis 元件：可安裝、更新、啟動、停止或查看記錄。',
 'Updates install beside the current version; Roll back returns to the previous one.':'更新會安裝在目前版本旁；「復原」可回到上一版。',
 'Large data never comes with a component: a component that says Needs data offers its own download.':'大型資料不隨元件安裝；顯示「需要資料」的元件會提供自己的下載。',
 'A component works in your Terminal as soon as it runs: no sign-in or pairing.':'元件一執行，終端即可使用，無需登入或配對。',
 'Remove keeps the component\'s data unless you untick Keep data.':'移除時會保留元件資料，除非取消勾選「保留資料」。'};
// A component's settings (its parts list declares them; their names and notes come in the viewer's language).
Object.assign(MESSAGES,{'Settings':'設定','Save':'儲存','Save and restart':'儲存並重新啟動','One per line':'每行一個',
 'Settings saved':'設定已儲存','{0} restarts with the new settings.':'{0} 已用新設定重新啟動。',
 'Found · {0} models':'已找到 · {0} 個模型','Found · no model ready':'已找到 · 尚無可用模型','Asks for a key':'需要金鑰',
 'Answers, but not as a model server':'有回應，但不是模型伺服器','Not running':'未執行','Found: choose…':'從已找到的選擇…','Usage':'用量'});
// What happened, as Recent events lists it (prompits.components state events, and the manager's own jobs). A kind not
// listed here is shown as it is.
const EVENTS={installed:'Installed',activated:'Version made current',adopted:'Already running: taken over',started:'Started',
 stopped:'Stopped',exited:'Exited',crashed:'Crashed',crash_loop:'Keeps crashing',start_failed:'Could not start',waiting:'Waiting for Retis Terminal',
 updated:'Updated',rolled_back:'Rolled back',removed:'Removed',settings_changed:'Settings changed',parts_list_accepted:'Parts list accepted',
 install_done:'Install finished',install_failed:'Install failed',update_done:'Update finished',update_failed:'Update failed',
 data_download_started:'Data download started',data_downloaded:'Data downloaded',data_download_failed:'Data download failed',
 report_written:'Problem report saved',included_refused:'The copy in the app was not used',tick_failed:'A routine check failed'};
Object.assign(MESSAGES,{'Installed':'已安裝','Version made current':'已切換為此版本','Already running: taken over':'已在執行，改由管理員管理',
 'Started':'已啟動','Exited':'已結束','Crashed':'當機','Could not start':'無法啟動','Waiting for Retis Terminal':'等待 Retis Terminal',
 'Updated':'已更新','Rolled back':'已復原','Removed':'已移除','Settings changed':'設定已變更','Parts list accepted':'已接受元件清單',
 'Install finished':'安裝完成','Install failed':'安裝失敗','Update finished':'更新完成','Update failed':'更新失敗',
 'Data download started':'開始下載資料','Data downloaded':'資料已下載','Data download failed':'資料下載失敗',
 'Problem report saved':'已儲存問題回報','The copy in the app was not used':'未使用 App 內附的版本','A routine check failed':'例行檢查失敗'});
// Why the manager refused settings (prompits.components.settings): it names the field by its id; the page names it as
// the form does and says the rest in the viewer's language.
const REFUSALS=[[/^at most (\d+) entries$/,'at most {0} entries'],[/^must be on or off$/,'must be on or off'],
 [/^must be a number$/,'must be a number'],[/^must be a whole number$/,'must be a whole number'],
 [/^must be from (\S+) to (\S+)$/,'must be from {0} to {1}'],[/^choose one of the offered values$/,'choose one of the offered values'],
 [/^must be text$/,'must be text'],[/^must be 1 to (\d+) characters$/,'must be 1 to {0} characters'],
 [/^(.+) is not allowed here$/,'{0} is not allowed here']];
Object.assign(MESSAGES,{'{0}: {1}':'{0}：{1}','at most {0} entries':'最多 {0} 項','must be on or off':'只能是開或關',
 'must be a number':'必須是數字','must be a whole number':'必須是整數','must be from {0} to {1}':'必須介於 {0} 到 {1}',
 'choose one of the offered values':'請從提供的選項中選擇','must be text':'必須是文字','must be 1 to {0} characters':'必須是 1 到 {0} 個字元',
 '{0} is not allowed here':'不接受 {0}','Unknown settings: {0}':'不明的設定：{0}','{0} has no settings.':'{0} 沒有設定。'});
function language(locale){return /^zh(-|_)?(hant|tw|hk|mo)?/i.test(String(locale||''))?'zh-Hant':'en';}
function translate(lang,key,...values){
 let text=lang==='zh-Hant'&&MESSAGES[key]||key;
 values.forEach((value,index)=>{text=text.split('{'+index+'}').join(String(value));});
 return text;
}
/** The buttons a row offers, in order, for its state. */
function actions(row){
 const list=[];
 const licences=(row.notices||[]).length?['licences']:[];
 if(row.state==='not_installed'){if(row.available_here&&!busy(row))list.push('install');return [...list,...licences];}
 if(row.state==='installing'||busy(row))return list;
 // A component the app bundles (the Terminal) updates with the app: run it, never remove or replace it here.
 if(row.bundled){
  if(row.state==='stopped')list.push('start');
  // Only the app can start a waiting Terminal: it hands over the key.
  else if(row.state!=='waiting')list.push('stop','restart');
  list.push('logs');return list;
 }
 if(row.update&&row.available_here)list.push('update');
 if(['stopped'].includes(row.state))list.push('start');
 if(row.state==='waiting')list.push('stop');
 if(['running','starting','needs_data','unhealthy','restarting'].includes(row.state))list.push('stop','restart');
 if(row.state==='unhealthy'&&row.process&&row.process.crash_loop)list.push('start');
 if(row.previous)list.push('rollback');
 // What the user may change for it (Local LLM's servers, AssetStorage's limits): only a component that declares some.
 if((row.settings||[]).length)list.push('settings');
 list.push('logs','remove',...licences);
 return [...new Set(list)];
}
function busy(row){return !!(row.job&&row.job.state==='running');}
// The actions the manager runs as a background job on a row (its status then says Install · Pending or Update · Pending).
const JOB_KINDS=new Set(['install','update']);
/** A row's state and job as the manager's status gives them: a pressed Install or Update waits for this to change. */
function jobMark(row){const job=row&&row.job||{};return JSON.stringify([row&&row.state,job.kind,job.state,job.started_at]);}
/** How soon to ask again: quickly while something is changing. */
function nextRefresh(rows){
 return rows.some(row=>busy(row)||row.operation||downloading(row)||['installing','starting','restarting'].includes(row.state))?3000:30000;
}
/** The terms a row still needs accepted: those not accepted before at their version. */
function unaccepted(row){return (row.terms||[]).filter(term=>!term.accepted);}
/** What the row says beside its state, or '' when the state says it all (a program starting has no port open yet). */
function reason(row,t){
 const text=String(row.reason||'');
 if(!text||(row.state==='starting'&&text==='port closed'))return '';
 const attempt=/^attempt (\d+)$/.exec(text);
 if(attempt)return t('Attempt {0}',attempt[1]);
 if(text.startsWith('health check failed'))return t('Health check failed');
 return REASONS[text]?t(REASONS[text]):text;
}
/** A refused settings save in the viewer's language, the field named as the form names it; anything else as it came. */
function refusal(message,row,t){
 const text=String(message||''),fields=new Map((row&&row.settings||[]).map(field=>[field.id,field.group?field.group.name+' · '+field.name:field.name]));
 const unknown=/^Unknown settings: (.+)$/.exec(text);if(unknown)return t('Unknown settings: {0}',unknown[1]);
 if(row&&text===row.id+' has no settings.')return t('{0} has no settings.',row.name||row.id);
 const named=/^([a-z][a-z0-9_]*): (.+)$/.exec(text);
 if(!named||!fields.has(named[1]))return text;
 for(const [pattern,key] of REFUSALS){const found=pattern.exec(named[2]);if(found)return t('{0}: {1}',fields.get(named[1])||named[1],t(key,...found.slice(1)));}
 return t('{0}: {1}',fields.get(named[1])||named[1],named[2]);
}
function downloading(row){return !!(row.data_job&&row.data_job.state==='running');}
/** The data sets a row may download now: those its parts list gives a download for, once it is installed. */
function downloads(row){
 if(row.state==='not_installed'||row.state==='installing'||downloading(row))return [];
 return (row.data||[]).filter(item=>Array.isArray(item.command)&&item.command.length);
}
function bytes(value){
 if(value==null)return '—';
 const units=['B','KB','MB','GB','TB'];let n=Number(value),i=0;
 while(n>=1024&&i<units.length-1){n/=1024;i++;}
 return (i?n.toFixed(n<10?1:0):String(n))+' '+units[i];
}
/* Each row action is an icon, with its name as the button's text for screen readers and as its hover text. */
const ICONS={
 install:[['path',{d:'M12 3v12M7 10l5 5 5-5M4 17v3h16v-3'}]],
 update:[['circle',{cx:'12',cy:'12',r:'8.5'}],['path',{d:'M12 16.5v-9M8 11l4-4 4 4'}]],
 start:[['path',{d:'M8 5.5v13l10.5-6.5z',fill:'currentColor'}]],
 stop:[['rect',{x:'6.5',y:'6.5',width:'11',height:'11',rx:'1.5',fill:'currentColor'}]],
 restart:[['path',{d:'M19.5 12a7.5 7.5 0 1 1-2.2-5.3M19.5 4.5v4.5H15'}]],
 rollback:[['path',{d:'M9 14 4 9l5-5M4 9h10.5a5.5 5.5 0 0 1 0 11H11'}]],
 // A gear (Alvin, 2026-11-26: "use gear icon for setting").
 settings:[['path',{d:'M19.4 10.2L22.1 10.6L22.1 13.4L19.4 13.8A7.6 7.6 0 0 1 18.5 15.9L20.1 18.1L18.1 20.1L15.9 18.5A7.6 7.6 0 0 1 13.8 19.4L13.4 22.1L10.6 22.1L10.2 19.4A7.6 7.6 0 0 1 8.1 18.5L5.9 20.1L3.9 18.1L5.5 15.9A7.6 7.6 0 0 1 4.6 13.8L1.9 13.4L1.9 10.6L4.6 10.2A7.6 7.6 0 0 1 5.5 8.1L3.9 5.9L5.9 3.9L8.1 5.5A7.6 7.6 0 0 1 10.2 4.6L10.6 1.9L13.4 1.9L13.8 4.6A7.6 7.6 0 0 1 15.9 5.5L18.1 3.9L20.1 5.9L18.5 8.1A7.6 7.6 0 0 1 19.4 10.2Z'}],['circle',{cx:'12',cy:'12',r:'3'}]],
 logs:[['path',{d:'M6 3h9l4 4v14H6zM14.5 3v4.5H19M9 12h7M9 16h7'}]],
 remove:[['path',{d:'M4 7h16M10 7V4h4v3M6.5 7l1 13h9l1-13M10 11v5M14 11v5'}]],
 licences:[['circle',{cx:'12',cy:'9.5',r:'5.5'}],['path',{d:'M9 14.5 8 21l4-2 4 2-1-6.5'}]],
 download:[['path',{d:'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3'}]],
 stop_download:[['circle',{cx:'12',cy:'12',r:'8.5'}],['path',{d:'M9 9l6 6M15 9l-6 6'}]],
 close:[['path',{d:'M6 6l12 12M18 6 6 18'}]],
 usage:[['path',{d:'M5 20v-8M12 20V5M19 20v-5'}]]};
// An update waiting is no alert: its row shows it (the version cell and the Update button).
const ALERTS={crash_loop:'{0} keeps crashing.',unhealthy:'{0} has been unhealthy for a while.',
 data_failed:'{0} could not download its data.'};
// States in which a component's program runs: saving its settings restarts it so it reads them.
const RUNNING_STATES=['running','starting','needs_data','unhealthy','restarting'];
// What an AI app may ask this view to do (release.py VIEW_ACTIONS), and the only component settings it may change
// (release.py AI_SETTINGS): none decides a connection, a key, trust or where files go.
const AI_ACTION_IDS=Object.freeze(['describe','set_settings']);
const AI_SETTINGS=Object.freeze({'local-analyst':['name']});

function mount(root,bridge){
 const context=bridge.context||{},lang=language(context.locale),t=(key,...values)=>translate(lang,key,...values);
 const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!=null)node.textContent=text;return node;};
 const button=(label,onclick,className='')=>{const node=el('button',className,t(label));node.type='button';node.onclick=onclick;return node;};
 const SVG='http://www.w3.org/2000/svg';
 const icon=kind=>{
  const svg=document.createElementNS(SVG,'svg');
  for(const [name,value] of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'2','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true',focusable:'false'}))svg.setAttribute(name,value);
  for(const [tag,attrs] of ICONS[kind]||[]){const part=document.createElementNS(SVG,tag);for(const [name,value] of Object.entries(attrs))part.setAttribute(name,value);svg.append(part);}
  return svg;
 };
 // An icon button: its name is its text (read aloud, hidden from sight) and its hover text.
 const iconButton=(kind,label,onclick,className='')=>{
  const node=el('button','mm-icon'+(className?' '+className:''));node.type='button';node.title=t(label);
  node.append(icon(kind),el('span','mm-sr',t(label)));node.onclick=onclick;return node;
 };
 const when=seconds=>seconds?new Intl.DateTimeFormat(context.locale||'en',{dateStyle:'short',timeStyle:'short',timeZone:context.timezone}).format(seconds*1000):'—';
 root.className='mm';root.dataset.theme=context.theme||'light';
 const onContext=event=>{root.dataset.theme=event.detail.theme||'light';};
 document.addEventListener('phemacast:context',onContext);
 if(context.sourceMode&&context.sourceMode!=='parameters'){root.replaceChildren(el('p','mm-status','Open this Phema with parameters.'));return ()=>{};}
 /* The view's own name in the viewer's language: the frame's hover text, which is otherwise the view's id ("mas-manager").
  * Sent once; a Terminal that is busy gets it again shortly, and one that refuses it keeps the name it had. */
 const presentTitle=(attempt=0)=>{
  if(typeof bridge.setPresentation!=='function')return;
  Promise.resolve().then(()=>bridge.setPresentation({title:t('Retis MAS Manager')})).catch(error=>{
   if(/Operation is unavailable/.test(error?.message||'')&&attempt<5)setTimeout(()=>presentTitle(attempt+1),300);
  });
 };
 presentTitle();

 const bar=el('div','mm-bar'),host=el('strong','mm-host',t('This computer')),note=el('p','mm-status'),parts=el('span','mm-parts');
 note.setAttribute('role','status');
 // A failed status read says so until a later one answers; what an action or a button reports stays until the next one.
 let statusNote=false;
 const say=(text,fromStatus=false)=>{note.textContent=text;statusNote=fromStatus&&!!text;};
 const help=el('details','mm-help'),helpList=el('ul');
 help.append(el('summary',null,t('How to use')),helpList);helpList.replaceChildren(...HELP.map(line=>el('li',null,t(line))));
 // Where the report was saved: on its own line under the bar, since a long path would wrap into the bar.
 const savedLine=el('p','mm-saved');savedLine.hidden=true;savedLine.setAttribute('role','status');
 const report=button('Problem report',async()=>{
  say('');savedLine.hidden=true;
  try{const saved=await call('mas_report',{});savedLine.textContent=t('Report saved on this computer: {0}',saved.path);savedLine.hidden=false;}
  catch(error){say(error.message);}
 });
 const space=el('span','mm-parts');
 const check=button('Check for updates',async()=>{
  say('');
  try{const result=await call('mas_check_updates',{});if(result&&result.configured===false)say(t('Component updates come with new Retis Terminal versions.'));}
  catch(error){say(error.message);}
  await load();
 });
 // Shown once the first status says there is a parts list to check: a manager without one never flashes it.
 check.hidden=true;
 bar.append(host,button('Refresh',()=>load()),check,report,parts,space,note,help);
 const alertBox=el('ul','mm-alerts');alertBox.hidden=true;
 const dialog=el('section','mm-dialog');dialog.hidden=true;
 const table=el('table','mm-table'),body=el('tbody');
 const head=el('tr');for(const label of ['Component','Version','Status','Actions'])head.append(el('th',null,t(label)));
 const thead=el('thead');thead.append(head);table.append(thead,body);
 const logs=el('section','mm-logs');logs.hidden=true;
 // Recent events are always shown, below the list, and take the rest of the window (Alvin, 2026-11-26: "you still
 // leave a lot of blank under the component list"): the window has no empty band at any height.
 const events=el('section','mm-events');events.setAttribute('aria-label',t('Recent events'));
 // A popup over the page (the frame has no dialog element): a component's settings open here.
 const modal=el('div','mm-modal'),modalBox=el('section','mm-modal-box');modal.hidden=true;
 modalBox.setAttribute('role','dialog');modalBox.setAttribute('aria-modal','true');modal.append(modalBox);
 modal.onclick=event=>{if(event&&event.target===modal)closeModal();};
 if(typeof modalBox.addEventListener==='function')modalBox.addEventListener('keydown',event=>{if(event.key==='Escape')closeModal();});
 // The page fills its window: the list keeps its own height (scrolling only in a short window), and Recent events
 // fill what is left, so nothing ends short of the window's bottom edge.
 const list=el('div','mm-list');list.append(table);
 root.replaceChildren(bar,savedLine,alertBox,dialog,list,logs,events,modal);

 // Operations this page asked for and is waiting on, shown at once: the manager answers when they are done.
 let disposed=false,timer=null,rows=[];const asked=new Map(),usageOpen=new Set();
 // The last status the manager gave and why the last read failed ('' when it answered); the component whose settings
 // are open in the popup ('' when none is).
 let latest=null,statusError='',settingsOpen='';
 // Installs and updates this page asked for, each with its row's mark when pressed: that row's Install or Update stays
 // disabled until the manager's status shows the row changed (its job running, done or failed), so a second press never
 // asks again. A refused request frees it at once.
 const pressed=new Map();
 async function call(operation,parameters){
  const reply=await bridge.invoke({compositionReference:REFERENCE,sourceMode:'parameters',
   input:{operation,parameters,request_key:crypto.randomUUID()}});
  if(reply&&reply.error)throw Error(reply.error);
  if(!reply||!reply.response)throw Error(t('The manager returned no result.'));
  if(reply.response.error)throw Error(reply.response.error);
  if(reply.response.response===undefined)return reply.response;
  return reply.response.response;
 }
 async function run(operation,parameters,label){
  const kind=operation.replace(/^mas_/,''),component=parameters.component,job=!!component&&JOB_KINDS.has(kind);
  if(job){
   if(pressed.has(component))return;
   pressed.set(component,jobMark(rows.find(row=>row.id===component)));render(rows);
  }
  say('');
  if(component&&OPERATIONS[kind]){asked.set(component,{kind});render(rows);}
  try{
   // A start, stop, restart, removal or roll back answers with the row as it is now: show it before the next status.
   // That row is in English (an action carries no language): its name and description stay as the last status gave them.
   const answer=await call(operation,parameters);
   if(answer&&answer.id===component&&answer.state)rows=rows.map(row=>row.id===component?{...answer,name:row.name,description:row.description}:row);
  }
  catch(error){
   if(job&&pressed.delete(component))render(rows);
   say(label?t('{0} failed: {1}',t(label),error.message):error.message);
  }
  finally{if(component&&asked.delete(component))render(rows);}
  await load();
 }
 function schedule(){clearTimeout(timer);if(!disposed)timer=setTimeout(load,nextRefresh(rows));}
 async function load(){
  try{
   const status=await call('mas_status',{language:lang});if(disposed)return;
   latest=status;statusError='';
   rows=status.components||[];
   host.textContent=t('This computer')+' · '+(status.host&&status.host.name||'');
   const list=status.parts_list||{};
   // Without a parts list (the desktop app), components come with the app: there is nothing to check.
   check.hidden=list.configured===false;
   parts.textContent=list.configured===false?t('Component updates come with new Retis Terminal versions.')
    :list.sequence!=null?t('Parts list {0} · checked {1}',list.sequence,when(list.checked_at)):t('Updates not checked yet.');
   if(list.error)say(list.error,true);else if(statusNote)say('');
   space.textContent=status.disk?t('Free disk: {0}',bytes(status.disk.free_bytes)):'';
   renderAlerts(status.alerts||[]);render(rows);renderEvents(status.events||[]);
  }catch(error){if(!disposed){statusError=error.message;say(error.message,true);}}
  schedule();
 }
 function confirmBox(message,choices){
  dialog.replaceChildren(el('p',null,message),...choices);dialog.hidden=false;
 }
 function closeDialog(){dialog.hidden=true;dialog.replaceChildren();}
 function openModal(title,content,footer){
  const head=el('header','mm-modal-head');head.append(el('h3',null,title),iconButton('close','Close',closeModal));
  const main=el('div','mm-modal-body');main.append(...content);
  const foot=el('footer','mm-modal-foot');foot.append(...footer);
  modalBox.setAttribute('aria-label',title);modalBox.replaceChildren(head,main,foot);modal.hidden=false;
 }
 function closeModal(){modal.hidden=true;modalBox.replaceChildren();settingsOpen='';}
 /** Each term in full (a note's text in the viewer's language); for an install, also what it downloads and the licences. */
 function termParts(row,terms,installing){
  const parts=[],notices=row.notices||[];
  for(const term of terms){
   const text=term.texts&&(term.texts[lang]||term.texts.en);
   const title=el('strong',null,(term.names&&term.names[lang]||term.names&&term.names.en||term.id)+' ('+term.version+')');
   if(term.url)title.append(' ',el('code',null,term.url));
   parts.push(title);if(text)parts.push(el('p','mm-note',text));
  }
  if(installing&&notices.length){
   const list=el('ul','mm-notices');
   // The libraries the note names come first; Licences lists every one.
   for(const item of notices.slice(0,5))list.append(el('li',null,item.name+' '+item.version+(item.license?' ('+item.license+')':'')));
   if(notices.length>5)list.append(el('li',null,t('and {0} more',notices.length-5)));
   parts.push(el('p',null,t('Install downloads these from the Python Package Index (PyPI):')),list);
  }
  if(notices.length)parts.push(button('Licences',()=>showNotices(row)));
  return parts;
 }
 function update(row,terms){
  const component=row.id;
  if(ASK_BEFORE_RESTART.has(component)&&row.process&&row.process.running){
   confirmBox(t('Restart {0} now to finish the update?',row.name),[
    button('Restart now',()=>{closeDialog();run('mas_update',{component,restart:true,accept_terms:terms},'Update');}),
    button('At next start',()=>{closeDialog();run('mas_update',{component,restart:false,accept_terms:terms},'Update');}),
    button('Cancel',closeDialog)]);
   return;
  }
  return run('mas_update',{component,restart:true,accept_terms:terms},'Update');
 }
 function act(row,kind){
  const component=row.id;
  if(kind==='install'){
   // Only terms not accepted before at their version: a removal that kept the data kept the acceptance too.
   const needed=unaccepted(row),terms=needed.map(term=>term.id+'@'+term.version);
   if(!terms.length)return run('mas_install',{component},'Install');
   confirmBox(t('Accept these terms first:'),[...termParts(row,needed,true),button('Accept and install',()=>{closeDialog();run('mas_install',{component,accept_terms:terms},'Install');}),button('Cancel',closeDialog)]);
   return;
  }
  if(kind==='update'){
   // A new version may come with new terms: they are shown and accepted before it installs, as for an install.
   const needed=unaccepted(row),terms=needed.map(term=>term.id+'@'+term.version);
   if(terms.length){
    confirmBox(t('Accept these terms first:'),[...termParts(row,needed,false),button('Accept and update',()=>{closeDialog();update(row,terms);}),button('Cancel',closeDialog)]);
    return;
   }
   return update(row,terms);
  }
  if(kind==='remove'){
   const keep=el('input');keep.type='checkbox';keep.checked=true;const label=el('label');label.append(keep,' '+t('Keep data'));
   confirmBox(t('Remove {0}?',row.name),[label,button('Remove',()=>{closeDialog();run('mas_remove',{component,keep_data:keep.checked},'Remove');},'mm-danger'),button('Cancel',closeDialog)]);
   return;
  }
  if(kind==='logs')return showLogs(row);
  if(kind==='settings')return showSettings(row);
  if(kind==='licences')return showNotices(row);
  return run('mas_'+kind,{component},{start:'Start',stop:'Stop',restart:'Restart',rollback:'Roll back'}[kind]);
 }
 let noticesShown=0;
 async function showNotices(row){
  // The notices come in parts (a view takes at most 300,000 characters in one value or one drawing request); each
  // part is added to the text as it arrives, until the last, or until another view of the panel replaces it.
  const shown=++noticesShown;
  try{
   let result=await call('mas_notices',{component:row.id});if(disposed)return;
   const text=el('pre',null,result.text||t('No notices.'));
   // The licence texts stay as their authors published them; a line in the viewer's language says what they are.
   const about=el('p','mm-note',t('These are the licences of the open-source libraries {0} uses, as their authors published them (in English).',row.name));
   logs.replaceChildren(el('h3',null,t('Third-party notices')+' · '+row.name),about,text,button('Close',()=>{logs.hidden=true;}));logs.hidden=false;
   for(let part=1;result.next!=null&&part<200;part++){
    result=await call('mas_notices',{component:row.id,offset:result.next});
    if(disposed||shown!==noticesShown||logs.hidden)return;
    text.append(result.text);
   }
  }catch(error){say(error.message);}
 }
 async function showLogs(row){
  noticesShown++;  // the panel shows the logs now: notices still loading stop
  try{
   const result=await call('mas_logs',{component:row.id,lines:200});if(disposed)return;
   const parts=[el('h3',null,t('Logs')+' · '+row.name)];
   if((result.lines||[]).length||!(result.data_lines||[]).length)parts.push(el('pre',null,(result.lines||[]).join('\n')||'—'));
   if((result.data_lines||[]).length)parts.push(el('h4',null,t('Data download')),el('pre',null,result.data_lines.join('\n')));
   logs.replaceChildren(...parts,button('Close',()=>{logs.hidden=true;}));logs.hidden=false;
  }catch(error){say(error.message);}
 }
 /** The component's settings as a form in a popup over the page: each field's own control, never JSON. Fields of
  * one thing (a group, such as one model server) share a row with what the component says about it now (its health
  * details), the ones it found first; an added entry shows its state under its list, and a field the component can
  * suggest values for offers them. Saving restarts a running component so it reads them; a refused value is said above
  * the buttons and nothing changes. */
 function showSettings(row){
  noticesShown++;  // the panel shows the settings now: notices still loading stop
  const details=row.health&&row.health.details||{},found=details.groups||{},entries=details.items||{},suggested=details.suggestions||{};
  const form=el('div','mm-settings'),controls=[];
  const said=(detail,name)=>{
   if(!detail)return '';
   const text={ready:t('Found · {0} models',detail.count),empty:t('Found · no model ready'),key:t('Asks for a key'),
    error:t('Answers, but not as a model server'),off:t('Not running')}[detail.state]||'';
   return text&&detail.name&&detail.name!==name?text+' · '+detail.name:text;
  };
  const make=field=>{
   let control;
   if(field.type==='boolean'){control=el('input');control.type='checkbox';control.checked=field.value===true;}
   else if(field.type==='list'){
    control=el('textarea');const lines=Array.isArray(field.value)?field.value:[];
    control.rows=Math.min(6,Math.max(2,lines.length+1));control.value=lines.join('\n');control.placeholder=t('One per line');
   }else if(field.type==='choice'){
    control=el('select');
    for(const option of field.options||[]){const node=el('option',null,option.name);node.value=option.value;control.append(node);}
    control.value=field.value;
   }else{
    control=el('input');control.type=field.type==='number'?'number':'text';control.value=field.value==null?'':String(field.value);
    if(field.type==='number'){if(field.minimum!=null)control.min=String(field.minimum);if(field.maximum!=null)control.max=String(field.maximum);control.step=field.integer?'1':'any';}
    else if(field.max_length)control.maxLength=field.max_length;
   }
   controls.push({field,control});return control;
  };
  const groups=new Map(),single=[];
  for(const field of row.settings||[]){
   if(field.group){if(!groups.has(field.group.id))groups.set(field.group.id,{group:field.group,fields:[]});groups.get(field.group.id).fields.push(field);}
   else single.push(field);
  }
  if(groups.size){
   const answering=id=>found[id]&&found[id].state&&found[id].state!=='off'?0:1;
   const table=el('table','mm-groups');
   for(const id of [...groups.keys()].sort((a,b)=>answering(a)-answering(b))){
    const {group,fields}=groups.get(id),tr=el('tr');tr.dataset.state=found[id]&&found[id].state||'';
    const cells=[el('td','mm-group-name',group.name)];
    for(const field of fields){
     const control=make(field),cell=el('td');control.setAttribute('aria-label',group.name+' · '+field.name);
     if(field.type==='boolean'){const label=el('label','mm-check');label.append(control,el('span',null,field.name));cell.append(label);cells.unshift(cell);}
     else{control.title=field.name;cell.append(control);cells.push(cell);}
    }
    tr.append(...cells,el('td','mm-group-state',said(found[id],group.name)));table.append(tr);
   }
   form.append(table);
  }
  for(const field of single){
   const label=el('label',field.type==='boolean'?'mm-field mm-check':'mm-field'),name=el('span',null,field.name),control=make(field);
   if(field.type==='boolean')label.append(control,name);else label.append(name,control);
   const hints=Array.isArray(suggested[field.id])?suggested[field.id]:[];
   if(field.type==='text'&&hints.length){
    // What the component found, to pick from; the box still takes any value.
    const pick=el('select');pick.setAttribute('aria-label',field.name);
    const first=el('option',null,t('Found: choose…'));first.value='';pick.append(first);
    for(const hint of hints){const node=el('option',null,hint);node.value=hint;pick.append(node);}
    pick.onchange=()=>{if(pick.value)control.value=pick.value;};label.append(pick);
   }
   if(field.description)label.append(el('small',null,field.description));
   const states=entries[field.id];
   if(field.type==='list'&&states&&Array.isArray(field.value)){
    const list=el('ul','mm-entries');
    for(const value of field.value){const state=said(states[value],'');if(state)list.append(el('li',null,value+' · '+state));}
    if(list.children.length)label.append(list);
   }
   form.append(label);
  }
  const valueOf=({field,control})=>field.type==='boolean'?control.checked
   :field.type==='list'?String(control.value||'').split('\n').map(line=>line.trim()).filter(Boolean)
   :field.type==='number'?(String(control.value).trim()===''?field.default:Number(control.value)):control.value;
  const running=RUNNING_STATES.includes(row.state);
  const problem=el('p','mm-error');problem.setAttribute('role','alert');problem.hidden=true;
  const save=button(running?'Save and restart':'Save',async()=>{
   const values={};for(const item of controls)values[item.field.id]=valueOf(item);
   save.disabled=true;problem.hidden=true;say('');
   if(running){asked.set(row.id,{kind:'restart'});render(rows);}
   try{
    await call('mas_settings',{component:row.id,values});
    closeModal();say(running?t('{0} restarts with the new settings.',row.name):t('Settings saved'));
   }catch(error){problem.textContent=refusal(error.message,row,t);problem.hidden=false;}
   finally{save.disabled=false;if(asked.delete(row.id))render(rows);}
   await load();
  });
  openModal(t('Settings')+' · '+row.name,[form,problem],[save,button('Cancel',closeModal)]);
  settingsOpen=row.id;
 }
 const LABELS={install:'Install',update:'Update',start:'Start',stop:'Stop',restart:'Restart',rollback:'Roll back',logs:'Logs',remove:'Remove',licences:'Licences',settings:'Settings'};
 function render(list){
  for(const shown of list)if(pressed.has(shown.id)&&pressed.get(shown.id)!==jobMark(shown))pressed.delete(shown.id);
  body.replaceChildren(...list.map(shown=>{
   // An operation this page is waiting on shows before the manager's next status says so.
   const row=shown.operation||!asked.has(shown.id)?shown:{...shown,operation:asked.get(shown.id)};
   const tr=el('tr');tr.dataset.state=row.state;
   const name=el('td','mm-name');name.append(el('span',null,row.name));if(row.description)name.title=row.description;
   if(!row.available_here&&row.state==='not_installed')name.append(el('small',null,t('Not offered for this computer')));
   // One line per row, also in a narrow panel: an update waiting is a mark beside the version, the version it brings
   // in its hover text (and on the Update button's).
   const version=el('td','mm-version',row.version||'—');
   if(row.update){const mark=el('span','mm-up','↑');mark.title=t('Update to {0}',row.update);mark.append(el('span','mm-sr',' '+t('Update to {0}',row.update)));version.append(mark);}
   if(row.pending)version.append(el('small',null,t('Updates at next start: {0}',row.pending)));
   const state=el('td','mm-state');const dot=el('span','mm-dot');dot.dataset.state=row.operation?'changing':row.state;
   let text=t(STATES[row.state]||row.state);
   if(row.state==='installing'&&row.progress&&row.progress.total)text+=' '+Math.floor(row.progress.received*100/row.progress.total)+'%';
   if(busy(row))text=t(row.job.kind==='update'?'Update':'Install')+' · '+t('Pending');
   if(row.operation)text=t(OPERATIONS[row.operation.kind]||'Pending');
   state.append(dot,el('span',null,text));
   // CPU, memory and disk use fold into an icon beside the state: a row keeps one line until it is opened.
   const usage=[];
   if(row.resources)usage.push(t('CPU {0}% · memory {1}',row.resources.cpu_percent,bytes(row.resources.memory_bytes)));
   if(row.disk_bytes)usage.push(row.data_bytes?t('{0} on disk ({1} data)',bytes(row.disk_bytes),bytes(row.data_bytes)):t('{0} on disk',bytes(row.disk_bytes)));
   if(usage.length){
    const more=el('details','mm-usage'),summary=el('summary');summary.title=usage.join('\n');
    summary.append(icon('usage'),el('span','mm-sr',t('Usage')));more.append(summary,...usage.map(line=>el('small',null,line)));
    more.open=usageOpen.has(row.id);more.ontoggle=()=>{if(more.open)usageOpen.add(row.id);else usageOpen.delete(row.id);};
    state.append(more);
   }
   const why=row.operation?'':reason(row,t);
   if(why)state.append(el('small',null,why));
   if(row.job&&row.job.state==='failed')state.append(el('small','mm-error',t('{0} failed: {1}',t(row.job.kind==='update'?'Update':'Install'),row.job.error)));
   else if(row.last_error)state.append(el('small','mm-error',t('Last error: {0}',row.last_error)));
   const job=row.data_job;
   if(job&&job.state==='running')state.append(el('small','mm-badge',t('Downloading: {0}',job.last_line||'…')));
   else if(job&&job.state==='failed')state.append(el('small','mm-error',t('Download failed')));
   else if(job&&job.state==='done')state.append(el('small',null,t('Download finished')));
   // The buttons go in a box inside the cell, which stays a table cell (see manager.css).
   const cell=el('td'),buttons=el('div','mm-actions');cell.append(buttons);
   const offered=downloads(row);
   for(const item of offered){
    const label=offered.length>1?t('Download {0}',item.names&&(item.names[lang]||item.names.en)||item.id):t('Download data');
    const node=iconButton('download',label,()=>run('mas_download_data',{component:row.id,data:item.id},'Download data'));
    buttons.append(node);
   }
   if(downloading(row))buttons.append(iconButton('stop_download','Stop download',()=>run('mas_stop_download',{component:row.id},'Stop download')));
   for(const kind of actions(row)){
    const node=iconButton(kind,LABELS[kind],()=>act(row,kind),kind==='remove'?'mm-danger':JOB_KINDS.has(kind)?'mm-primary':'');
    if(kind==='update'&&row.update)node.title=t('Update to {0}',row.update);
    // A pressed Install or Update waits until the manager's status shows it taken up.
    if(JOB_KINDS.has(kind)&&pressed.has(row.id))node.disabled=true;
    buttons.append(node);
   }
   // While a start, stop, restart, removal or roll back is under way, its buttons stay where they are but wait.
   if(row.operation)for(const node of buttons.children)node.disabled=true;
   tr.append(name,version,state,cell);return tr;
  }));
 }
 function renderAlerts(list){
  const name=id=>(rows.find(row=>row.id===id)||{}).name||id;
  alertBox.replaceChildren(...list.map(alert=>{
   const item=el('li','mm-alert',t(ALERTS[alert.kind]||alert.kind,name(alert.component)));
   item.dataset.severity=alert.severity||'info';return item;
  }));
  alertBox.hidden=!list.length;
 }
 function renderEvents(list){
  const items=el('ul');
  // Each component by its name in the viewer's language, as its row shows it; one no longer listed by its id.
  const name=id=>(rows.find(row=>row.id===id)||{}).name||id||'';
  for(const event of list.slice().reverse())items.append(el('li',null,[when(event.at),name(event.component),t(EVENTS[event.kind]||event.kind)].filter(Boolean).join(' · ')));
  if(!list.length)items.append(el('li','mm-none',t('No events in the last 3 days.')));
  events.replaceChildren(el('h3',null,t('Recent events')),items);
 }
 /* What an AI app may ask for (release.py VIEW_ACTIONS), each with the steps a click takes, so the page shows the
  * outcome as after that click: describe reads the status again as Refresh does, and set_settings saves a stopped
  * component's settings as its form's Save does, only those AI_SETTINGS names. It refuses rather than restart a running
  * component or take over a settings popup the person has open. Components are named as their rows name them (or by
  * their id); answers are in English and carry no other ids. */
 function aiActions(){
  const en=(key,...values)=>translate('en',key,...values),quoted=text=>'“'+text+'”',short=text=>String(text).slice(0,300);
  const nameOf=id=>(rows.find(row=>row.id===id)||{}).name||id||'';
  const settable=row=>(row.settings||[]).filter(field=>(AI_SETTINGS[row.id]||[]).includes(field.id));
  const named=text=>{const wanted=String(text||'').trim().toLowerCase();
   return rows.find(row=>String(row.name||'').trim().toLowerCase()===wanted)||rows.find(row=>row.id===wanted)||null;};
  // The manager's status read again, as Refresh reads it; a read that fails says why.
  async function fresh(){
   if(disposed)throw Error('The view is closed.');
   await load();
   if(disposed)throw Error('The view is closed.');
   if(statusError||!latest)throw Error(statusError||en('The manager returned no result.'));
  }
  function facts(row){
   const found={name:row.name||row.id,state:STATES[row.state]||row.state};
   if(row.version)found.version=row.version;
   if(row.bundled)found.comes_with_the_app=true;
   if(row.update)found.update=row.update;
   if(row.pending)found.updates_at_next_start=row.pending;
   if(row.operation)found.changing=OPERATIONS[row.operation.kind]||'Pending';
   else if(busy(row))found.changing=(row.job.kind==='update'?'Update':'Install')+' · Pending';
   const why=reason(row,en);if(why)found.note=short(why);
   if(row.job&&row.job.state==='failed')found.last_error=short(en('{0} failed: {1}',row.job.kind==='update'?'Update':'Install',row.job.error));
   else if(row.last_error)found.last_error=short(row.last_error);
   if(row.data_job&&row.data_job.state)found.data_download=row.data_job.state;
   if(row.resources)found.usage=en('CPU {0}% · memory {1}',row.resources.cpu_percent,bytes(row.resources.memory_bytes));
   if(row.disk_bytes)found.disk=row.data_bytes?en('{0} on disk ({1} data)',bytes(row.disk_bytes),bytes(row.data_bytes)):en('{0} on disk',bytes(row.disk_bytes));
   const offered=settable(row);if(offered.length)found.settings=Object.fromEntries(offered.map(field=>[field.id,field.value]));
   return found;
  }
  return {
   async describe(){
    await fresh();
    return {computer:latest.host&&latest.host.name||'',components:rows.map(facts),
     ...(latest.disk?{free_disk:bytes(latest.disk.free_bytes)}:{}),
     alerts:(latest.alerts||[]).map(alert=>en(ALERTS[alert.kind]||alert.kind,nameOf(alert.component))),
     recent_events:(latest.events||[]).slice(-10).reverse().map(event=>({...(event.at?{at:new Date(event.at*1000).toISOString()}:{}),
      component:nameOf(event.component),event:EVENTS[event.kind]||event.kind}))};
   },
   async set_settings({component,values}={}){
    await fresh();
    const row=named(component);
    if(!row)throw Error('No component named '+quoted(component)+' on this computer; describe lists them.');
    const offered=settable(row),given=Object.keys(values||{});
    if(!offered.length)throw Error(quoted(row.name)+' has no settings an AI app may change; change them in the window.');
    const others=given.filter(id=>!offered.some(field=>field.id===id));
    if(!given.length||others.length)throw Error(quoted(row.name)+' takes only '+offered.map(field=>quoted(field.id)).join(', ')+' from an AI app.');
    if(settingsOpen===row.id)throw Error(quoted(row.name)+'\'s settings are being edited in the window.');
    if(row.operation||busy(row)||asked.has(row.id)||pressed.has(row.id))throw Error(quoted(row.name)+' is being changed; try again in a moment.');
    if(RUNNING_STATES.includes(row.state))throw Error(quoted(row.name)+' is running, and saving its settings restarts it. Stop it in the window first.');
    // Every field goes, as Save sends them: the ones not named keep their values.
    const before=Object.fromEntries((row.settings||[]).map(field=>[field.id,field.value]));
    try{await call('mas_settings',{component:row.id,values:{...before,...values}});}
    catch(error){throw Error(refusal(error.message,row,en));}
    say(t('Settings saved'));
    await load();
    // Undo: set_settings again with the values before, the component named as its row names it (by its id when that
    // name is shared or too long for the input).
    const earlier=Object.fromEntries(given.map(id=>[id,before[id]])),label=String(row.name||'').trim();
    const by=label&&label.length<=80&&rows.filter(item=>String(item.name||'').trim().toLowerCase()===label.toLowerCase()).length<=1?label:row.id;
    return {component:row.name,before:earlier,after:{...values},
     ...(given.every(id=>earlier[id]!=null)?{undo:{action:'set_settings',input:{component:by,values:earlier}}}:{})};
   },
  };
 }
 // An older host has no `actions`: the page works as before.
 if(typeof bridge.actions?.handle==='function'){const handlers=aiActions();for(const name of AI_ACTION_IDS)bridge.actions.handle(name,handlers[name]);}
 load();
 return ()=>{disposed=true;clearTimeout(timer);document.removeEventListener('phemacast:context',onContext);root.replaceChildren();};
}

globalThis.MasManagerView=Object.freeze({mount,actions,downloads,bytes,nextRefresh,translate,language,unaccepted,reason,refusal,
 MESSAGES,HELP,ALERTS,OPERATIONS,REASONS,EVENTS,AI_ACTION_IDS,AI_SETTINGS});
const bridge=globalThis.phemacastAgentView;
if(bridge&&typeof document!=='undefined'){
 const root=document.querySelector('#mas-manager');
 try{if(root)globalThis.disposeMasManager=mount(root,bridge);}
 catch(error){const message=document.createElement('p');message.setAttribute('role','alert');message.textContent=error.message;root.replaceChildren(message);}
}
})();
