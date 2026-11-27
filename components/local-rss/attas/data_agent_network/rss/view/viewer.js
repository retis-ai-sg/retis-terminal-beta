/* RSS content belongs to this source. Preferences and kept results belong to the mounted Terminal Phema. */
(()=>{
'use strict';
const REF='rss-content',KEPT='rss:v1:content',FILLED='rss:v1:defaults-filled';
// The source's default feeds, written in when its release is built (release.py); a viewer with none starts with them.
const DEFAULTS=/*rss-defaults*/[];
const MAX_FEEDS=100,BATCH=20; // a viewer keeps up to 100 feeds; the source reads at most 20 in one request
const KEPT_LIMIT=280000; // the Terminal keeps at most 300 KB of escaped JSON per kept result
const WAKE_MS=30000; // the confined runtime holds one timer for at most 30 seconds
const RETRY_MS=60000; // a feed never read yet is tried again after a minute, not after its interval
const FREQUENCIES=[[0,'Manual'],[60,'1 min'],[300,'5 min'],[900,'15 min'],[1800,'30 min'],[3600,'1 hour'],[21600,'6 hours'],[86400,'1 day']];
const ZH={'RSS Viewer':'RSS 閱讀器','Refresh':'更新','Feeds':'訂閱來源','How to Use':'使用說明','Add feed':'新增訂閱','Feed URL':'訂閱網址','Name (optional)':'名稱（選填）','Frequency':'更新頻率','Search articles':'搜尋文章','All feeds':'所有訂閱','Manual':'手動','1 min':'1 分鐘','5 min':'5 分鐘','15 min':'15 分鐘','30 min':'30 分鐘','1 hour':'1 小時','6 hours':'6 小時','1 day':'1 天','Edit':'編輯','Remove':'移除','Cancel':'取消','Save feed':'儲存訂閱','No articles yet. Add a feed, then refresh.':'尚無文章。請新增訂閱並更新。','Select an article to read.':'選取文章閱讀。','Reading feed content':'閱讀訂閱內容','Loading…':'載入中…','Snapshot':'快照','View Content':'檢視內容','No saved snapshots.':'沒有已儲存的快照。','Snapshot content · refresh is off.':'快照內容 · 已關閉更新。','Settings could not be saved: ':'無法儲存設定：','A feed with this URL already exists.':'此訂閱網址已存在。','Use a public HTTP or HTTPS feed URL.':'請使用公開的 HTTP 或 HTTPS 訂閱網址。','Add up to 100 feeds.':'最多可新增 100 個訂閱。','Updated':'已更新','articles':'篇文章','feed errors':'個訂閱錯誤','Last content kept; refresh failed: ':'保留上次內容；更新失敗：','No articles match.':'沒有符合的文章。','Group (optional)':'群組（選填）','Group name':'群組名稱','Other':'未分組','feeds':'個訂閱','Rename':'重新命名','Remove group':'移除群組','Import OPML':'匯入 OPML','Export OPML':'匯出 OPML','Choose file':'選擇檔案','Import':'匯入','Close':'關閉','Paste OPML here, or choose an OPML file.':'在此貼上 OPML，或選擇 OPML 檔案。','Copy this OPML into another reader.':'將此 OPML 複製到其他閱讀器。','Imported':'已匯入','already listed':'個已存在','over the limit':'個超過上限','No feeds found in this OPML.':'此 OPML 中沒有訂閱。','All in':'全部：','Groups need the updated RSS Viewer. In New Data Browser, select RSS Viewer, click 更新 and open a new one.':'群組需要更新後的 RSS 閱讀器。請在「新增資料瀏覽器」選取 RSS Viewer，按「更新」後開啟新的閱讀器。','Use a public HTTP or HTTPS feed URL without credentials or a custom port.':'請使用公開的 HTTP 或 HTTPS 訂閱網址，不含帳號密碼或自訂連接埠。','The feed hostname could not be resolved.':'找不到這個訂閱網址的主機。','Feeds must resolve only to public internet addresses.':'訂閱網址只能指向公開的網際網路位址。','The feed redirected too many times.':'這個訂閱轉址太多次。','The feed redirected from HTTPS to HTTP.':'這個訂閱從 HTTPS 轉址到 HTTP，已停止讀取。','The feed returned an unsupported compressed response.':'這個訂閱回應了不支援的壓縮格式。','The feed exceeds the 1 MB size limit.':'這個訂閱超過 1 MB 的大小上限。','The feed could not be retrieved.':'無法取得這個訂閱。','The feed is empty or too large.':'這個訂閱是空的，或內容太大。','Feed document types and entity declarations are not supported.':'不支援含文件類型或實體宣告的訂閱。','The response is not valid RSS or Atom XML.':'回應的內容不是有效的 RSS 或 Atom XML。','The response is not an RSS or Atom feed.':'回應的內容不是 RSS 或 Atom 訂閱。',"The feed's certificate could not be verified.":'無法驗證這個訂閱網站的憑證。','The feed could not be reached within the time limit.':'這個訂閱在時限內沒有回應。','The feed could not be reached.':'無法連上這個訂閱。'};
const HELP='A new viewer starts with the RSS source\'s Chinese finance and business feeds, in groups. Under Feeds, edit, disable or remove feeds or whole groups, rename a group, or add public RSS or Atom URLs (100 at most) with a group name; each feed has its own frequency or Manual mode. Import OPML takes a feed list exported by another reader (a file or pasted text); Export OPML shows yours to copy. The RSS Feed Groups panel from Plaza can add groups of checked feeds here once you allow it in its permissions (♧). Automatic refresh runs while this viewer is open, including retries after errors. Closing it pauses refresh. Settings and the last content stay in your Terminal. The reader shows text supplied by the feed, which may be an excerpt. Feed content cannot run scripts or load images. Snapshot mode only reads a saved result.';
function mount(root,bridge){
 const context=bridge.context||{};let language=/^zh/i.test(context.locale||'')?'zh':'en';
 const t=key=>language==='zh'?(ZH[key]||key):key;
 // A feed's error from the source (feeds.py), in the viewer's language; an HTTP status keeps its number.
 const feedError=message=>{const status=/^The feed returned HTTP (\d{3})\.$/.exec(message||'');
  return status&&language==='zh'?'這個訂閱回應 HTTP '+status[1]+'。':t(message);};
 const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
 const btn=(text,cls)=>{const n=el('button',cls,t(text));n.type='button';return n;};
 const option=(text,value)=>{const n=el('option','',t(text));n.value=String(value);return n;};
 const selectFrequency=value=>{const n=el('select');n.setAttribute('aria-label',t('Frequency'));for(const [v,label] of FREQUENCIES)n.append(option(label,v));n.value=String(value??900);return n;};
 let disposed=false,timer=null,busy=false,epoch=0,feeds=[],groups=[],legacy=false,before=null,source='',editing=-1,selected='',rows={},last={};
 root.dataset.theme=context.theme||'light';
 const status=el('p','rss-status');status.setAttribute('role','status');
 // Shown while this panel is a copy of the Phema from before revision 4, which keeps no groups.
 const outdated=el('p','rss-outdated rss-error',t('Groups need the updated RSS Viewer. In New Data Browser, select RSS Viewer, click 更新 and open a new one.'));outdated.hidden=true;
 const bar=el('div','rss-bar'),brand=el('span','rss-wordmark',t('RSS Viewer')),search=el('input'),filter=el('select','rss-filter');
 search.type='search';search.placeholder=t('Search articles');search.setAttribute('aria-label',t('Search articles'));
 filter.setAttribute('aria-label',t('Feeds'));
 const refresh=btn('Refresh','rss-primary'),configure=btn('Feeds'),help=btn('How to Use');bar.append(brand,search,filter,refresh,configure,help);
 const helpPanel=el('p','rss-help',language==='zh'?'新的閱讀器預設載入 RSS 資料來源的中文財經與商業訂閱，並依群組排列。可在「訂閱來源」編輯、停用或移除單一訂閱或整個群組、重新命名群組，或新增公開的 RSS 或 Atom 網址並指定群組（最多 100 個），並為每個訂閱設定更新頻率或手動。「匯入 OPML」可讀入其他閱讀器匯出的訂閱清單（檔案或貼上文字），「匯出 OPML」顯示您的清單供複製。Plaza 上的「RSS 訂閱群組」在您於其權限（♧）允許後，可將檢查過的訂閱群組加入此處。自動更新僅在此檢視開啟時執行，關閉後暫停。設定與內容保留在您的 Terminal。文章顯示訂閱提供的文字，可能只是摘要。快照模式只讀取已儲存的內容。':HELP);helpPanel.hidden=true;
 help.onclick=()=>{helpPanel.hidden=!helpPanel.hidden;};
 const config=el('section','rss-config'),form=el('div','rss-form'),url=el('input'),name=el('input'),groupName=el('input'),frequency=selectFrequency(900),add=btn('Add feed','rss-primary'),cancel=btn('Cancel'),feedList=el('div','rss-feeds');
 const tools=el('div','rss-tools'),importButton=btn('Import OPML'),exportButton=btn('Export OPML');tools.append(importButton,exportButton);
 const transfer=el('div','rss-transfer'),transferNote=el('small','rss-transfer-note'),opmlText=el('textarea','rss-opml'),transferActions=el('div','rss-form'),chooseFile=btn('Choose file'),importNow=btn('Import','rss-primary'),closeTransfer=btn('Close');
 opmlText.rows=8;opmlText.setAttribute('aria-label','OPML');transferActions.append(chooseFile,importNow,closeTransfer);transfer.append(transferNote,opmlText,transferActions);transfer.hidden=true;
 url.type='url';url.placeholder=t('Feed URL');url.maxLength=2048;url.setAttribute('aria-label',t('Feed URL'));
 name.type='text';name.placeholder=t('Name (optional)');name.maxLength=100;name.setAttribute('aria-label',t('Name (optional)'));cancel.hidden=true;
 groupName.type='text';groupName.placeholder=t('Group (optional)');groupName.maxLength=60;groupName.setAttribute('aria-label',t('Group (optional)'));
 form.append(url,name,groupName,frequency,add,cancel);config.append(form,tools,transfer,feedList);config.hidden=true;configure.onclick=()=>{config.hidden=!config.hidden;};
 const split=el('section','rss-split'),list=el('div','rss-list'),reader=el('article','rss-reader');reader.setAttribute('aria-label',t('Reading feed content'));split.append(list,reader);
 root.replaceChildren(bar,status,outdated,helpPanel,config,split);
 const note=(value,error=false)=>{status.textContent=value;status.className='rss-status'+(error?' rss-error':'');};
 const stop=()=>{disposed=true;epoch++;clearTimeout(timer);document.removeEventListener('phemacast:context',onContext);};
 const onContext=event=>{root.dataset.theme=event.detail?.theme||'light';};document.addEventListener('phemacast:context',onContext);
 function normalizeURL(value){const match=/^(https?):\/\/([a-z0-9.-]+|\[[a-f0-9:]+\])((?:\/|\?)[^\s\\#]*)?(?:#.*)?$/i.exec(value.trim());if(!match)throw Error(t('Use a public HTTP or HTTPS feed URL.'));return match[1].toLowerCase()+'://'+match[2].toLowerCase()+(match[3]?.startsWith('/')?match[3]:'/'+(match[3]||''));}
 const settings=()=>feeds.map(({url,name,enabled,refresh_seconds,group})=>({url,name:name||'',enabled:enabled!==false,refresh_seconds:refresh_seconds??900,...(group?{group:String(group).slice(0,60)}:{})}));
 const plain=list=>list.map(({group,...feed})=>feed);
 // Saves the feeds (and the directory groups, when they change). A copy of the Phema from before revision 4 has no
 // group field: it keeps the feeds without groups, and the viewer says how to update it.
 async function save(next,nextGroups){
  if(typeof bridge.setParameters!=='function')throw Error(t('Settings could not be saved: ')+'Terminal parameter storage is unavailable.');
  const grouped=next.some(f=>f.group)||Boolean(nextGroups?.length),previous=JSON.stringify(feeds);
  try{await bridge.setParameters(nextGroups?{feeds:next,groups:nextGroups}:{feeds:next});}
  catch(error){if(!grouped)throw error;await bridge.setParameters({feeds:plain(next)});next=plain(next);nextGroups=null;legacy=true;}
  // For a moment after a save the Terminal can still answer with the list as it was: sync() leaves that one alone.
  before=previous;feeds=next;if(nextGroups)groups=nextGroups;outdated.hidden=!legacy;renderFeeds();render();schedule();
 }
 // A click while a read runs waits for it, then acts (it used to be dropped without a word).
 const idle=()=>new Promise(resolve=>{const check=()=>busy&&!disposed?setTimeout(check,150):resolve();check();});
 // An AI app's action (`raise`) gets the error back as well as the note.
 const action=(fn,raise=false)=>async()=>{while(busy&&!disposed)await idle();if(disposed){if(raise)throw Error('The view closed.');return;}busy=true;refresh.disabled=true;try{return await fn();}catch(error){note(error.message,true);if(raise)throw error;}finally{busy=false;refresh.disabled=false;schedule();}};
 const serial=fn=>action(fn,true)();
 function resetForm(){editing=-1;url.value='';name.value='';groupName.value='';frequency.value='900';add.textContent=t('Add feed');cancel.hidden=true;}
 cancel.onclick=resetForm;
 // Add a feed (index -1) or save the one at `index`, as the feed form does.
 async function saveFeed(fields,index){
  const address=normalizeURL(fields.url),next=settings();
  if(next.some((f,i)=>i!==index&&f.url===address))throw Error(t('A feed with this URL already exists.'));
  if(index<0&&next.length>=MAX_FEEDS)throw Error(t('Add up to 100 feeds.'));
  const group=String(fields.group||'').trim().slice(0,60);
  const item={url:address,name:String(fields.name||'').trim(),enabled:index<0?true:next[index].enabled,refresh_seconds:Number(fields.refresh_seconds),...(group?{group}:{})};
  const previous=index<0?'':next[index].url;
  if(index<0)next.push(item);else next[index]=item;
  await save(next);if(previous){delete rows[previous];delete last[previous];}
  return item;
 }
 add.onclick=action(async()=>{
  await saveFeed({url:url.value,name:name.value,group:groupName.value,refresh_seconds:frequency.value},editing);resetForm();await load(false);
 });
 // Groups in the order their first feed appears; feeds without a group come under Other.
 const groupOrder=()=>{const order=[];for(const feed of feeds){const group=feed.group||'';if(!order.includes(group))order.push(group);}return order;};
 const renames=[];  // each group's name field, with the group it renames
 function renderFeeds(){
  feedList.replaceChildren();renames.length=0;
  for(const group of groupOrder()){
   const members=feeds.map((feed,index)=>({feed,index})).filter(({feed})=>(feed.group||'')===group);
   const section=el('section','rss-group'),head=el('div','rss-group-head'),all=el('input');
   all.type='checkbox';all.checked=members.every(({feed})=>feed.enabled!==false);all.setAttribute('aria-label',group||t('Other'));
   head.append(all,el('strong','rss-group-name',group||t('Other')),el('small','',members.length+' '+t('feeds')));
   all.onchange=action(async()=>{const next=settings();for(const {index} of members)next[index].enabled=all.checked;await save(next);});
   if(group){
    const field=el('input','rss-rename'),rename=btn('Rename'),drop=btn('Remove group');
    field.type='text';field.maxLength=60;field.value=group;field.hidden=true;field.setAttribute('aria-label',t('Group name'));renames.push([field,group]);
    rename.onclick=()=>{field.hidden=!field.hidden;if(!field.hidden)field.focus();};
    field.onchange=action(()=>renameGroup(group,field.value));
    drop.onclick=action(async()=>{for(const {feed} of members){delete rows[feed.url];delete last[feed.url];}
     await save(settings().filter(f=>f.group!==group),groups.filter(g=>g.name!==group));resetForm();await keep();render();});
    head.append(field,rename,drop);
   }
   section.append(head);feedList.append(section);
   for(const {feed,index} of members)section.append(feedRow(feed,index));
  }
 }
 async function renameGroup(group,name){const value=String(name).trim().slice(0,60);if(!value||value===group)return;
  await save(settings().map(f=>f.group===group?{...f,group:value}:f),groups.map(g=>g.name===group?{...g,name:value}:g));}
 function feedRow(feed,index){
   const row=el('div','rss-feed'),enabled=el('input');enabled.type='checkbox';enabled.checked=feed.enabled!==false;enabled.setAttribute('aria-label',feed.name||feed.url);
   const label=el('span','rss-feed-name',feed.name||feed.url),detail=el('small','',rows[feed.url]?.error?feedError(rows[feed.url].error):feed.url);if(rows[feed.url]?.error)detail.className='rss-error';label.append(detail);
   const every=selectFrequency(feed.refresh_seconds),edit=btn('Edit'),remove=btn('Remove');
   enabled.onchange=action(async()=>{const next=settings();next[index].enabled=enabled.checked;await save(next);});
   every.onchange=action(async()=>{const next=settings();next[index].refresh_seconds=Number(every.value);await save(next);});
   edit.onclick=()=>{editing=index;url.value=feed.url;name.value=feed.name||'';groupName.value=feed.group||'';frequency.value=String(feed.refresh_seconds??900);add.textContent=t('Save feed');cancel.hidden=false;};
   remove.onclick=action(async()=>{const next=settings();next.splice(index,1);await save(next);delete rows[feed.url];delete last[feed.url];resetForm();await keep();render();});
   row.append(enabled,label,every,edit,remove);return row;
 }
 // OPML in: a file (the Terminal's own file picker) or pasted text. Feeds already listed are skipped; a folder becomes
 // the feeds' group.
 importButton.onclick=()=>{transfer.hidden=false;opmlText.removeAttribute('readonly');opmlText.value='';transferNote.textContent=t('Paste OPML here, or choose an OPML file.');chooseFile.hidden=typeof bridge.pickTextFile!=='function';importNow.hidden=false;opmlText.focus();};
 exportButton.onclick=()=>{transfer.hidden=false;opmlText.setAttribute('readonly','');opmlText.value=globalThis.RSSOPML.write(settings(),t('RSS Viewer'));transferNote.textContent=t('Copy this OPML into another reader.');chooseFile.hidden=true;importNow.hidden=true;};
 closeTransfer.onclick=()=>{transfer.hidden=true;opmlText.value='';};
 chooseFile.onclick=async()=>{try{const file=await bridge.pickTextFile();if(file?.text!=null)opmlText.value=file.text;}catch(error){note(error.message,true);}};
 importNow.onclick=action(()=>importOPML(opmlText.value,()=>{transfer.hidden=true;opmlText.value='';}));
 async function importOPML(text,taken=()=>{}){
  const found=globalThis.RSSOPML.parse(text).feeds;if(!found.length)throw Error(t('No feeds found in this OPML.'));
  const next=settings(),have=new Set(next.map(f=>f.url));let added=0,listed=0,over=0;
  for(const feed of found){
   let address;try{address=normalizeURL(feed.url);}catch{continue;}
   if(have.has(address)){listed++;continue;}
   if(next.length>=MAX_FEEDS){over++;continue;}
   next.push({url:address,name:feed.name||'',enabled:true,refresh_seconds:900,...(feed.group?{group:feed.group}:{})});have.add(address);added++;
  }
  taken();
  // Read the new feeds first, then say what the import did.
  if(added){await save(next);await load(false);}
  note(t('Imported')+' '+added+' '+t('feeds')+(listed?' · '+listed+' '+t('already listed'):'')+(over?' · '+over+' '+t('over the limit'):''),over>0);
  return {added,listed,over};
 }
 function articles(){
  const enabled=new Set(feeds.filter(f=>f.enabled!==false).map(f=>f.url)),q=search.value.trim().toLowerCase();
  const groupOf=new Map(feeds.map(f=>[f.url,f.group||''])),choice=filter.value,inGroup=choice.startsWith('group:')?choice.slice(6):null;
  return Object.values(rows).filter(r=>enabled.has(r.url)).flatMap(r=>(r.items||[]).map(item=>({...item,feed:r.name||r.title||r.url,feed_url:r.url,group:groupOf.get(r.url)||''})))
   .filter(item=>(!choice||(inGroup!=null?item.group===inGroup:item.feed_url===choice))&&(!q||(item.title+' '+item.content+' '+item.feed).toLowerCase().includes(q)))
   .sort((a,b)=>(b.published_at||'').localeCompare(a.published_at||''));
 }
 function when(value){try{return new Intl.DateTimeFormat(context.locale||'en',{timeZone:context.timezone||'UTC',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value).getTime());}catch{return '';}}
 function render(){
  // The filter lists each group (all its feeds) and then its feeds.
  const choice=filter.value,values=[''];filter.replaceChildren(option('All feeds',''));
  for(const group of groupOrder()){
   const members=feeds.filter(f=>(f.group||'')===group),box=group?el('optgroup'):filter;if(group){box.setAttribute('label',group);filter.append(box);}
   if(group){const all=el('option','',t('All in')+' '+group);all.value='group:'+group;box.append(all);values.push(all.value);}
   for(const feed of members){box.append(option(feed.name||rows[feed.url]?.title||feed.url,feed.url));values.push(feed.url);}
  }
  filter.value=values.includes(choice)?choice:'';
  const items=articles();if(!items.some(i=>i.id===selected))selected=items[0]?.id||'';
  list.replaceChildren();
  for(const item of items){const button=btn('','rss-story');button.setAttribute('aria-pressed',String(selected===item.id));button.append(el('div','rss-meta',item.feed+' · '+(item.published_at?when(item.published_at):'')),el('strong','',item.title),el('span','rss-preview',(item.summary||item.content||'').slice(0,110)));button.onclick=()=>{selected=item.id;render();};list.append(button);}
  if(!items.length)list.append(el('p','rss-empty',t(feeds.length?'No articles match.':'No articles yet. Add a feed, then refresh.')));
  reader.replaceChildren();const item=items.find(i=>i.id===selected);
  if(!item){reader.append(el('p','rss-empty',t('Select an article to read.')));return;}
  reader.append(el('div','rss-meta',[item.feed,item.author,item.published_at?when(item.published_at):''].filter(Boolean).join(' · ')),el('h2','',item.title),el('div','rss-body',item.content||item.summary||''));
  // The confined frame cannot navigate to external URLs. Display a selectable source address without fetching it.
  if(item.url)reader.append(el('p','rss-link',item.url));
 }
 // The Terminal measures a kept value as escaped JSON, where each non-ASCII character counts six (\uXXXX): a page of
 // Chinese articles weighs several times its length. Keep the copy under KEPT_LIMIT by that measure.
 const weight=value=>{const s=JSON.stringify(value);let n=0;for(let i=0;i<s.length;i++)n+=s.charCodeAt(i)<128?1:6;return n;};
 async function keep(){
  if(!bridge.kept?.write)return;
  const copy=JSON.parse(JSON.stringify({source,feeds:settings(),rows,last}));
  // Drop the oldest articles of the largest feed first.
  const sizes=new Map(Object.entries(copy.rows).map(([url,row])=>[url,weight(row)]));
  let total=weight(copy);
  while(total>KEPT_LIMIT){
   const url=[...sizes.entries()].sort((a,b)=>b[1]-a[1])[0]?.[0];const row=url&&copy.rows[url];
   if(!row?.items?.length)break;
   const dropped=weight(row.items.pop())+1;sizes.set(url,sizes.get(url)-dropped);total-=dropped;
  }
  await bridge.kept.write(KEPT,copy);
 }
 // Read the Phema's settings again; draw the feeds and articles again only when they changed, so an open feed menu
 // or a selection in the reader stays as it is.
 async function sync(){
  const saved=typeof bridge.parameters==='function'?(await bridge.parameters())?.values||{}:context.parameters||{};
  const next=saved.source_agent||context.parameters?.source_agent||context.parameters?.publisher_id||'';
  let changed=false;
  if(next!==source){source=next;rows={};last={};epoch++;selected='';changed=true;}
  if(Array.isArray(saved.feeds)){
   const text=JSON.stringify(saved.feeds);
   if(text!==before){before=null;if(text!==JSON.stringify(feeds)){feeds=saved.feeds;changed=true;}}
  }
  if(Array.isArray(saved.groups))groups=saved.groups;
  if(changed){renderFeeds();render();}
 }
 // When a feed is next due, in milliseconds from now: 0 if it is due, null if it refreshes only by hand.
 function due(feed,now){const every=(feed.refresh_seconds??900)*1000;if(feed.enabled===false)return null;if(!last[feed.url])return 0;return every>0?Math.max(0,last[feed.url]+every-now):null;}
 async function load(force){
  await sync();const ticket=epoch;const now=Date.now();
  const wanted=feeds.filter(f=>f.enabled!==false&&(force||due(f,now)===0));
  if(!wanted.length){if(force)render();return;}
  // The button rests only while feeds are read; a check that finds nothing due leaves it alone.
  refresh.disabled=true;
  try{await read(wanted,force,ticket);}finally{refresh.disabled=false;}
 }
 async function read(wanted,force,ticket){
  note(t('Loading…'));
  // A read sends the source's feed fields only: the group is the viewer's own.
  const ask=wanted.map(({url,name,enabled,refresh_seconds})=>({url,name:name||'',enabled:enabled!==false,refresh_seconds:refresh_seconds??900,...(force?{}:{etag:rows[url]?.etag||'',last_modified:rows[url]?.last_modified||''})}));
  // The source reads at most BATCH feeds in one request: more are asked in turn, and one failed batch keeps the others.
  // The Terminal runs one read of this panel at a time and answers "still processing" (409) to one that starts while
  // it is finishing the last: wait a moment and ask again (walked in 28410 on 2026-11-23).
  const ask_=async batch=>{for(let attempt=0;;attempt++){try{return await bridge.invoke({compositionReference:REF,sourceMode:'parameters',input:{feeds:batch,limit:20}});}
   catch(error){if(attempt>=3||disposed||!/still processing/i.test(error?.message||''))throw error;await new Promise(resolve=>setTimeout(resolve,1500*(attempt+1)));}}};
  let failure=null,answered=0;
  for(let start=0;start<ask.length;start+=BATCH){
   const batch=ask.slice(start,start+BATCH);
   try{
    const reply=await ask_(batch);
    if(disposed||ticket!==epoch)return;
    if(reply?.error)throw Error(reply.error);
    const result=reply?.response||reply;
    if(!Array.isArray(result?.feeds))throw Error('The RSS source returned no feed results.');
    const current=typeof bridge.parameters==='function'?(await bridge.parameters())?.values||{}:null;
    if(current?.source_agent&&current.source_agent!==source){await sync();return;}
    for(const row of result.feeds){last[row.url]=Date.now();rows[row.url]=row.status==='not_modified'?{...rows[row.url],...row,etag:row.etag||rows[row.url]?.etag||'',last_modified:row.last_modified||rows[row.url]?.last_modified||'',status:'ready'}:row.status==='error'?{...rows[row.url],...row}:row;}
    answered++;
   }catch(error){if(disposed||ticket!==epoch)return;
    // A failed feed waits its interval; one never read yet (just added) is tried again after RETRY_MS.
    for(const feed of batch){const every=(feed.refresh_seconds||900)*1000;last[feed.url]=Date.now()-(rows[feed.url]?0:Math.max(0,every-RETRY_MS));}
    failure=error;}
  }
  renderFeeds();render();
  if(failure&&!answered){note(t('Last content kept; refresh failed: ')+failure.message,true);return;}
  const errors=Object.values(rows).filter(r=>r.status==='error').length;
  note(failure?t('Last content kept; refresh failed: ')+failure.message:t('Updated')+' · '+articles().length+' '+t('articles')+(errors?' · '+errors+' '+t('feed errors'):''),Boolean(failure)||errors>0);
  await keep();
 }
 // Each time it opens, a viewer saves the feeds it shows. A list that is only the Phema's default is not this panel's
 // own page value: the Terminal shows other panels (the RSS Feed Groups panel) no feeds, and a group added there would
 // replace them all. Saving what is already saved changes nothing. (Walked in 28410 on 2026-11-23: a kept marker can't
 // tell, since kept values outlive one panel.) A viewer with no feeds starts with the source's default feeds once; one
 // whose feeds were all removed later stays empty.
 async function offerDefaults(){
  const marked=bridge.kept?.read?await bridge.kept.read(FILLED):null,filled=(marked?.value||marked)?.filled===true;
  let list=null;
  if(feeds.length)list=settings();
  else if(!filled&&DEFAULTS.length)list=DEFAULTS.slice(0,MAX_FEEDS).map(f=>({url:f.url,name:f.name||'',enabled:true,refresh_seconds:900,...(f.group?{group:f.group}:{})}));
  if(list){
   // A copy of the Phema from before revision 3 keeps at most 20 feeds (and one from before revision 4 no groups).
   try{await save(list);}catch(error){await save(plain(list).slice(0,BATCH));}
  }
  if(!filled&&bridge.kept?.write)await bridge.kept.write(FILLED,{filled:true});
 }
 // Wake when the next feed is due, and at least every WAKE_MS to notice settings changed outside this viewer (each
 // wake reads the Phema's parameters once). A viewer whose feeds all refresh by hand only checks its settings.
 function schedule(){
  clearTimeout(timer);if(disposed)return;
  const now=Date.now(),waits=feeds.map(f=>due(f,now)).filter(wait=>wait!=null);
  const wait=Math.min(WAKE_MS,...waits);
  timer=setTimeout(async()=>{if(!busy){busy=true;try{await load(false);}catch(error){note(error.message,true);}finally{busy=false;}}schedule();},Math.max(1000,wait));
 }
 refresh.onclick=action(()=>load(true));search.oninput=render;filter.onchange=render;
 // --- What an AI app may ask (release.py VIEWER_ACTIONS) ----------------------------------------------------------------
 // Each action takes the steps a click takes, through the same functions and one action at a time, so the feeds stay
 // this Phema's page values as always. Feeds are named by their names or addresses, groups and stories by their names
 // and titles. Not offered: Remove and Remove group.
 let started=Promise.resolve();
 const fail=text=>new Error(text),quoted=text=>'“'+text+'”';
 const same=(a,b)=>String(a??'').trim().toLowerCase()===String(b??'').trim().toLowerCase();
 function named(list,name,what,labels){
  const exact=list.filter(x=>labels(x).includes(name)),found=exact.length?exact:list.filter(x=>labels(x).some(label=>same(label,name)));
  if(!found.length)throw fail('There is no '+what+' named '+quoted(name)+'. describe lists them.');
  if(found.length>1)throw fail('More than one '+what+' is named '+quoted(name)+'.');
  return found[0];
 }
 const feedName=f=>f.name||rows[f.url]?.title||f.url;
 const feedAt=ref=>feeds.indexOf(named(feeds,ref,'feed',f=>[f.url,f.name,rows[f.url]?.title].filter(Boolean)));
 const feedFacts=f=>({name:feedName(f),url:f.url,on:f.enabled!==false,frequency_seconds:f.refresh_seconds??900,
  ...(rows[f.url]?.error?{problem:feedError(rows[f.url].error)}:{})});
 const storyFacts=item=>({title:item.title,feed:item.feed,published_at:item.published_at||null});
 function listFacts(){const items=articles(),open=items.find(i=>i.id===selected),choice=filter.value;
  const shownFilter=!choice?'':choice.startsWith('group:')?choice.slice(6):feedName(feeds.find(f=>f.url===choice)||{url:choice});
  return {filter:shownFilter,search:search.value,count:items.length,stories:items.slice(0,20).map(storyFacts),open:open?storyFacts(open):null};}
 function live(){if(context.sourceMode!=='parameters')throw fail('This view shows a snapshot; switch it to live content first.');}
 // The feed form or a group's new name, typed and not yet saved, would be drawn over.
 function notEditing(index=-2){
  if(editing>=0&&(index===-2||index===editing))throw fail(quoted(feedName(feeds[editing]||{url:url.value}))+' is being edited in the window.');
  for(const [field,group] of renames)if(!field.hidden&&field.value.trim()!==group)throw fail(quoted(group)+' is being edited in the window.');
 }
 // Undo (the Terminal's, `undo` in an edit's answer): this viewer keeps its feeds and groups only in the window's
 // parameter values, which sync() reads back as they are, so each edit answers 'parameters'.
 const actions={
  async describe(){
   await started;
   return {...(context.sourceMode==='snapshot'?{snapshot:true}:{}),
    groups:groupOrder().map(group=>{const members=feeds.filter(f=>(f.group||'')===group);
     return {name:group||t('Other'),on:members.every(f=>f.enabled!==false),feeds:members.map(feedFacts)};}),...listFacts()};
  },
  async show({filter:pick,search:words,article}){
   live();await started;
   if(pick!==undefined){
    const group=pick?groupOrder().find(g=>g&&same(g,pick)):null;
    filter.value=!pick?'':group?'group:'+group:feeds[feedAt(pick)].url;render();
   }
   if(words!==undefined){search.value=words;render();}
   let story=null;
   if(article!==undefined){const item=named(articles(),article,'story in the list',i=>[i.title]);selected=item.id;render();
    story={...storyFacts(item),url:item.url||null,text:String(item.content||item.summary||'').slice(0,1500)};}
   return {...listFacts(),...(story?{open:story}:{})};
  },
  async add_feed({url:address,name:label,group,frequency_seconds}){
   live();await started;
   if(editing>=0||url.value.trim())throw fail('The feed form is being edited in the window.');
   notEditing();
   const item=await serial(async()=>{const made=await saveFeed({url:address,name:label||'',group:group||'',refresh_seconds:frequency_seconds??900},-1);await load(false);return made;});
   return {feed:feedFacts(feeds.find(f=>f.url===item.url)||item),group:item.group||null,undo:'parameters'};
  },
  async set_feed({feed,on,frequency_seconds,name:label,group}){
   live();await started;
   const index=feedAt(feed);notEditing(index);
   const address=feeds[index].url;
   await serial(async()=>{
    const at=()=>feeds.findIndex(f=>f.url===address);
    // The row's checkbox and frequency, then Edit and Save feed for its name or group.
    if(on!==undefined){const next=settings();next[at()].enabled=on;await save(next);}
    if(frequency_seconds!==undefined){const next=settings();next[at()].refresh_seconds=frequency_seconds;await save(next);}
    if(label!==undefined||group!==undefined){const current=settings()[at()];
     await saveFeed({url:current.url,name:label??current.name,group:group??current.group??'',refresh_seconds:current.refresh_seconds},at());await load(false);}
   });
   return {feed:feedFacts(feeds.find(f=>f.url===address)),undo:'parameters'};
  },
  async set_group({group,on,name:renamed}){
   live();await started;notEditing();
   const found=named(groupOrder(),group,'group',g=>[g||t('Other')]);
   if(renamed!==undefined&&!found)throw fail('Feeds without a group have no name to change.');
   await serial(async()=>{
    if(on!==undefined){const next=settings();feeds.forEach((f,i)=>{if((f.group||'')===found)next[i].enabled=on;});await save(next);}
    if(renamed!==undefined)await renameGroup(found,renamed);
   });
   const now=renamed!==undefined&&renamed.trim()?renamed.trim().slice(0,60):found;
   const members=feeds.filter(f=>(f.group||'')===now);
   return {group:{name:now||t('Other'),on:members.every(f=>f.enabled!==false),feeds:members.map(feedFacts)},undo:'parameters'};
  },
  async import_opml({opml}){
   live();await started;notEditing();
   const c=await serial(()=>importOPML(opml));
   return {added:c.added,already_listed:c.listed,over_the_limit:c.over,...(c.added?{undo:'parameters'}:{})};
  },
  async refresh(){
   live();await started;
   await serial(()=>load(true));
   return {articles:articles().length,problems:Object.values(rows).filter(r=>r.status==='error').length};
  },
 };
 // An older Terminal's view host has no `actions`; the view works as before.
 try{for(const [name,fn] of Object.entries(actions))bridge.actions?.handle?.(name,fn);}catch{}
 if(context.sourceMode==='snapshot'){
  refresh.hidden=true;configure.hidden=true;const picker=el('select'),view=btn('View Content');picker.setAttribute('aria-label',t('Snapshot'));bar.append(picker,view);view.disabled=true;
  Promise.resolve().then(()=>bridge.snapshots()).then(value=>{if(disposed)return;for(const row of value?.snapshots||[])picker.append(option(row.label||when(row.createdAt),row.id));view.disabled=!picker.options.length;if(view.disabled)note(t('No saved snapshots.'));}).catch(error=>note(error.message,true));
  view.onclick=async()=>{try{const saved=await bridge.readSnapshot(picker.value);if(disposed)return;const result=saved.results?.[REF]?.value;const data=result?.response||result;feeds=saved.parameters?.feeds||[];rows={};for(const row of data?.feeds||[]){rows[row.url]=row;if(!feeds.some(f=>f.url===row.url))feeds.push({url:row.url,name:row.name,enabled:true});}render();note(t('Snapshot content · refresh is off.'));}catch(error){note(error.message,true);}};
  render();return stop;
 }
 if(context.sourceMode&&context.sourceMode!=='parameters'){note('Select parameters or a saved snapshot.',true);refresh.disabled=true;return stop;}
 started=Promise.resolve().then(async()=>{
  await sync();
  await offerDefaults();
  if(bridge.kept?.read){const saved=await bridge.kept.read(KEPT);const value=saved?.value||saved;if(value?.source===source){rows=value.rows||{};last={};renderFeeds();render();}}
  config.hidden=feeds.length>0;await action(()=>load(true))();
 }).catch(error=>note(error.message,true));
 return stop;
}
globalThis.RSSViewer=Object.freeze({mount});
const bridge=globalThis.phemacastAgentView;
if(bridge&&typeof document!=='undefined'){const root=document.querySelector('#rss-viewer');if(root)globalThis.disposeRSSViewer=mount(root,bridge);}
})();
