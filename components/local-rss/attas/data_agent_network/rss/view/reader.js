/* RSS Viewer (revision 5): the subscriptions and articles Local RSS keeps for its user, through its one `rss_local`
   reference. Every RSS source the user can reach is listed by Local RSS (a Terminal data request); the one picked is
   used to browse groups and to refresh. Local RSS keeps the subscriptions; this Phema keeps only the source picked and
   which groups are open. */
(()=>{
'use strict';
const REF='rss-local',OPEN='rss:v2:open-groups',WAKE_MS=30000;
const FREQUENCIES=[[0,'Manual'],[60,'1 min'],[300,'5 min'],[900,'15 min'],[1800,'30 min'],[3600,'1 hour'],[21600,'6 hours'],[86400,'1 day']];
const LANGUAGES={'zh-Hant':'繁體中文','zh-Hans':'简体中文','en':'English','ja':'日本語'};
const TOPICS_ZH={stocks:'股票',markets:'市場',industry:'產業',technology:'科技',international:'國際','cross-strait':'兩岸',finance:'財經',
 business:'商業','personal-finance':'理財',crypto:'加密貨幣','central-banks':'央行'};
const ZH={'RSS Viewer':'RSS 閱讀器','Articles':'文章','Subscriptions':'訂閱','Refresh':'更新','How to Use':'使用說明','RSS source':'RSS 來源',
 'this computer':'本機','Search articles':'搜尋文章','All feeds':'所有訂閱','All in':'全部：','Manual':'手動','1 min':'1 分鐘','5 min':'5 分鐘',
 '15 min':'15 分鐘','30 min':'30 分鐘','1 hour':'1 小時','6 hours':'6 小時','1 day':'1 天','Group default':'群組預設','feeds':'個訂閱',
 'Following · synced':'已追蹤 · 同步','Own':'自訂','Off':'已關閉','On':'開啟','Default frequency':'預設更新頻率','Rename':'重新命名',
 'Unfollow':'取消追蹤','Remove group':'移除群組','Remove':'移除','Group name':'群組名稱','My subscriptions':'我的訂閱',
 'Browse groups':'瀏覽群組','All languages':'所有語言','All topics':'所有主題','Search groups':'搜尋群組','Follow':'追蹤','Following':'已追蹤',
 'Add a feed':'新增訂閱','Feed URL':'訂閱網址','Name (optional)':'名稱（選填）','Group (optional)':'群組（選填）','Add feed':'新增訂閱',
 'Frequency':'更新頻率','Import OPML':'匯入 OPML','Export OPML':'匯出 OPML','Choose file':'選擇檔案','Import':'匯入','Close':'關閉',
 'Paste OPML here, or choose an OPML file.':'在此貼上 OPML，或選擇 OPML 檔案。','Copy this OPML into another reader.':'將此 OPML 複製到其他閱讀器。',
 'Loading…':'載入中…','Updated':'已更新','articles':'篇文章','No articles yet. Subscribe to feeds, then refresh.':'尚無文章。請訂閱後更新。',
 'No articles match.':'沒有符合的文章。','Select an article to read.':'選取文章閱讀。','Reading feed content':'閱讀訂閱內容',
 'Read':'已讀取','failed':'個失敗','waiting for the background reader':'個由背景讀取','through':'經由','Imported':'已匯入',
 'already listed':'個已存在','over the limit':'個超過上限','No feeds found in this OPML.':'此 OPML 中沒有訂閱。',
 'Moved your earlier feeds into Local RSS':'已將先前的訂閱移入 Local RSS','Now following':'已追蹤','No groups match.':'沒有符合的群組。',
 'Snapshot':'快照','View Content':'檢視內容','No saved snapshots.':'沒有已儲存的快照。','Snapshot content · refresh is off.':'快照內容 · 已關閉更新。',
 'waiting':'等待讀取','error':'錯誤','Directory':'目錄',
 'Open article':'開啟原文','Translate':'翻譯','Translating…':'翻譯中…','Show original':'顯示原文','Show translation':'顯示譯文',
 'Translated with':'譯文 · 模型','Model':'模型','Loading models…':'載入模型…','No model found':'找不到可用的模型','Translate to':'翻譯成',
 'This computer':'本機','Your key':'自有金鑰','Plaza (points)':'Plaza（點數）','points':'點','My note':'我的筆記','Note store':'筆記儲存位置',
 'Choose a store…':'選擇儲存空間…','No AssetStorage found':'找不到 AssetStorage','Write a note…':'寫下筆記…','Save note':'儲存筆記',
 'Saved':'已儲存','Note removed':'已刪除筆記','Any time':'不限時間','Today':'今天','Last 24 hours':'24 小時內','Last 3 days':'3 天內',
 'Last 7 days':'7 天內','Last 30 days':'30 天內','Newest first':'最新優先','Oldest first':'最舊優先','Date':'日期','Sort':'排序','Resize':'調整寬度',
 'Smaller text':'縮小文字','Larger text':'放大文字','Collapse note':'收合筆記','Show note':'展開筆記','Note':'筆記',
 'Select an article to write a note.':'選取文章後可寫筆記。','Resize note':'調整筆記寬度','Tagged by':'標記者','more tags':'個標籤'};
// What Local RSS and the feeds say (feeds.py, subscriptions.py, local.py, library.py), in a Chinese viewer's words. A
// message with a number or a name in it is matched by its pattern below.
const SAID_ZH={'Use a public HTTP or HTTPS feed URL without credentials or a custom port.':'請使用公開的 HTTP 或 HTTPS 訂閱網址，不含帳號密碼或自訂連接埠。',
 'The feed hostname could not be resolved.':'找不到這個訂閱網址的主機。','Feeds must resolve only to public internet addresses.':'訂閱網址只能指向公開的網際網路位址。',
 'The feed redirected too many times.':'這個訂閱轉址太多次。','The feed redirected from HTTPS to HTTP.':'這個訂閱從 HTTPS 轉址到 HTTP，已停止讀取。',
 'The feed returned an unsupported compressed response.':'這個訂閱回應了不支援的壓縮格式。','The feed exceeds the 1 MB size limit.':'這個訂閱超過 1 MB 的大小上限。',
 'The feed could not be retrieved.':'無法取得這個訂閱。','The feed is empty or too large.':'這個訂閱是空的，或內容太大。',
 'Feed document types and entity declarations are not supported.':'不支援含文件類型或實體宣告的訂閱。',
 'The response is not valid RSS or Atom XML.':'回應的內容不是有效的 RSS 或 Atom XML。','The response is not an RSS or Atom feed.':'回應的內容不是 RSS 或 Atom 訂閱。',
 "The feed's certificate could not be verified.":'無法驗證這個訂閱網站的憑證。','The feed could not be reached within the time limit.':'這個訂閱在時限內沒有回應。',
 'The feed could not be reached.':'無法連上這個訂閱。',
 'A feed with this URL is already in your subscriptions.':'這個訂閱網址已在您的訂閱中。','Name the group.':'請輸入群組名稱。',
 'That group is not in your subscriptions.':'這個群組不在您的訂閱中。','That feed is not in your subscriptions.':'這個訂閱不在您的訂閱中。',
 'A feed from a followed group stays in its group; turn it off instead.':'已追蹤群組的訂閱會留在原群組；若不需要，請將它關閉。',
 'The RSS subscriptions file is not one this Local RSS can read.':'這個 Local RSS 無法讀取目前的訂閱檔案。',
 'That RSS source did not answer.':'該 RSS 來源沒有回應。','That RSS source refused the request.':'該 RSS 來源拒絕了這個要求。',
 'That RSS source answered with something this Local RSS cannot read.':'該 RSS 來源的回應無法由 Local RSS 讀取。',
 'That RSS source has no feed group directory.':'該 RSS 來源沒有訂閱群組目錄。','Choose a Local RSS operation.':'請選擇 Local RSS 的操作。',
 'That article is no longer kept.':'這篇文章已不再保留。','Local RSS returned no result.':'Local RSS 沒有回傳結果。',
 'The model answered with no text.':'模型沒有回傳文字。','No answer came back.':'沒有收到回應。','That note could not be read.':'無法讀取這則筆記。',
 'This Terminal cannot list agents.':'這個 Terminal 無法列出代理。','Send an http or https link.':'只能開啟 http 或 https 連結。'};
const SAID_ZH_PATTERNS=[[/^The feed returned HTTP (\d{3})\.$/,m=>'這個訂閱回應 HTTP '+m[1]+'。'],
 [/^Keep up to (\d+) feeds\.$/,m=>'最多可保留 '+m[1]+' 個訂閱。'],[/^Keep up to (\d+) groups\.$/,m=>'最多可保留 '+m[1]+' 個群組。'],
 [/^That RSS source lists no group (.+)\.$/,m=>'該 RSS 來源沒有群組 '+m[1]+'。'],
 [/^Choose a frequency of ([\d, ]+) seconds\.$/,m=>'請選擇更新頻率（秒）：'+m[1]+'。'],
 [/^Invalid .+ request: text may not contain control characters\.$/,()=>'文字不可包含控制字元。'],
 [/^A note is at most (\d+) characters/,m=>'筆記最多 '+m[1]+' 個字，且不可包含換行與 Tab 以外的控制字元。']];
const HELP_EN='Local RSS keeps your subscriptions on this computer and reads them in the background. Articles lists what it has read; select one to read the text its feed supplies (often an excerpt). Subscriptions: open a group to switch it or its feeds on or off, set the group\'s default frequency or a feed\'s own, rename or remove it. A followed group stays in sync with its directory: new feeds are added, dropped ones removed, your choices kept. Browse groups lists the directory of the RSS source picked above (any RSS source you can reach, on this computer or on Plaza); Follow adds a group. Add your own feeds by URL or Import OPML; Export OPML shows yours to copy. Refresh reads now, through the picked source. With a story open: Open article opens its page in your browser; pick a model and a language, then Translate (a model on this computer is free, your own key is billed by its vendor, a Plaza model costs points); My note keeps your note on the story in the AssetStorage you pick. Drag the bar between the list and the story to resize them.';
const HELP_ZH='Local RSS 在這台電腦保存您的訂閱，並在背景讀取。「文章」列出已讀取的內容，選取後顯示訂閱提供的文字（多為摘要）。「訂閱」中可展開群組，開關群組或單一訂閱、設定群組預設更新頻率或單一訂閱的頻率，並重新命名或移除。已追蹤的群組會與目錄同步：新增的訂閱會加入、移除的會刪除，您的設定保留。「瀏覽群組」列出上方所選 RSS 來源（本機或 Plaza 上您可使用的任何 RSS 來源）的目錄，按「追蹤」加入群組。也可用網址新增自己的訂閱或匯入 OPML；「匯出 OPML」顯示您的清單供複製。「更新」會經由所選來源立即讀取。開啟文章後：「開啟原文」在瀏覽器開啟原始網頁；選擇模型與語言後按「翻譯」（本機模型免費，自有金鑰由供應商計費，Plaza 模型使用點數）；「我的筆記」將筆記存放在您選擇的 AssetStorage。拖曳清單與文章之間的分隔線可調整寬度。';
function mount(root,bridge){
 const context=bridge.context||{},zh=/^zh/i.test(context.locale||'');
 const t=key=>zh?(ZH[key]||key):key;
 // A message from Local RSS or a feed, in the viewer's language; one this viewer doesn't know stays as it came.
 const say=message=>{const text=String(message||'');if(!zh)return text;if(Object.hasOwn(SAID_ZH,text))return SAID_ZH[text];
  for(const [pattern,words] of SAID_ZH_PATTERNS){const m=pattern.exec(text);if(m)return words(m);}return text;};
 const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
 const btn=(text,cls)=>{const n=el('button',cls,t(text));n.type='button';return n;};
 const option=(text,value)=>{const n=el('option','',text);n.value=String(value);return n;};
 const frequencySelect=(value,withDefault)=>{const n=el('select');n.setAttribute('aria-label',t('Frequency'));if(withDefault)n.append(option(t('Group default'),''));
  for(const [v,label] of FREQUENCIES)n.append(option(t(label),v));n.value=value==null?'':String(value);return n;};
 const topicLabel=value=>zh?(TOPICS_ZH[value]||value):value;
 const groupName=group=>(zh?group.name?.['zh-Hant']:group.name?.en)||group.name?.en||group.id;
 let disposed=false,timer=null,busy=false,tab='articles',subs=null,sources=[],source='',articles=[],selected='',open=new Set(),listing=null,texts=new Map(),self='';
 // One story's tools (story.py): the model and language to translate with, the AssetStorage notes go to, and the list's
 // date filter and order, kept as this viewer's choices in the Terminal.
 const STORY='rss:v2:story',SPLIT='rss:v2:split';
 let prefs={llm:null,language:zh?'zh-Hant':'en',store:'',when:'',order:'newest',noteOpen:true,sizes:{list:1,story:1,note:1}},llms=null,stores=null,choicesAsked=false;
 const SCALES=[0.85,1,1.15,1.3,1.5,1.75];
 const translated=new Map(),showing=new Map(),notes=new Map(),drafts=new Map(),loadingNotes=new Set(),translating=new Set();
 // The tags analysts gave the stories (Local Analyst, through Local RSS), by address; asked again for an untagged one
 // after TAGS_AGAIN_MS, since tagging runs every half hour.
 const tagsByUrl=new Map(),tagsAskedAt=new Map(),TAGS_AGAIN_MS=600000;let tagsLoading=false;
 const keepPrefs=()=>{if(bridge.kept?.write)bridge.kept.write(STORY,prefs).catch(()=>{});};
 const llmKey=m=>m?[m.source,m.agent,m.provider,m.model].join('|'):'';
 root.dataset.theme=context.theme||'light';
 const onContext=event=>{root.dataset.theme=event.detail?.theme||'light';};document.addEventListener('phemacast:context',onContext);
 // --- layout -----------------------------------------------------------------------------------------------------
 const bar=el('div','rss-bar'),brand=el('span','rss-wordmark',t('RSS Viewer')),sourcePick=el('select','rsr-source'),tabs=el('div','rsr-tabs');
 sourcePick.setAttribute('aria-label',t('RSS source'));
 const articlesTab=btn('Articles','rsr-tab'),subsTab=btn('Subscriptions','rsr-tab'),refresh=btn('Refresh','rss-primary'),help=btn('How to Use');
 articlesTab.setAttribute('role','tab');subsTab.setAttribute('role','tab');tabs.append(articlesTab,subsTab);
 bar.append(brand,sourcePick,tabs,refresh,help);
 const status=el('p','rss-status');status.setAttribute('role','status');
 const helpPanel=el('p','rss-help',zh?HELP_ZH:HELP_EN);helpPanel.hidden=true;help.onclick=()=>{helpPanel.hidden=!helpPanel.hidden;};
 const articlesPane=el('section','rsr-articles'),tools=el('div','rsr-tools'),search=el('input'),filter=el('select','rss-filter');
 search.type='search';search.placeholder=t('Search articles');search.setAttribute('aria-label',t('Search articles'));filter.setAttribute('aria-label',t('All feeds'));
 const split=el('section','rss-split'),list=el('div','rss-list'),reader=el('article','rss-reader');reader.setAttribute('aria-label',t('Reading feed content'));
 const whenPick=el('select','rsr-when'),orderPick=el('select','rsr-order');whenPick.setAttribute('aria-label',t('Date'));orderPick.setAttribute('aria-label',t('Sort'));
 for(const [value,label] of [['','Any time'],['today','Today'],['24h','Last 24 hours'],['3d','Last 3 days'],['7d','Last 7 days'],['30d','Last 30 days']])whenPick.append(option(t(label),value));
 for(const [value,label] of [['newest','Newest first'],['oldest','Oldest first']])orderPick.append(option(t(label),value));
 // The bar between the list and the story moves (drag it, or arrow keys when it has focus); its place is kept.
 const bar_=(cls,label)=>{const n=el('div',cls);n.setAttribute('role','separator');n.setAttribute('aria-orientation','vertical');n.setAttribute('aria-label',t(label));n.tabIndex=0;return n;};
 const divider=bar_('rsr-divider','Resize'),noteDivider=bar_('rsr-divider rsr-divider-note','Resize note');
 // Three panels, each scrolling on its own: the list (a header with the count and its text size), the story, and the
 // note (collapsible to a strip).
 const listHead=el('div','rsr-pane-head'),listCount=el('span','rsr-pane-title'),listItems=el('div','rsr-list-items'),notePane=el('aside','rsr-notes');
 notePane.setAttribute('aria-label',t('My note'));
 list.append(listHead,listItems);
 tools.append(search,filter,whenPick,orderPick);split.append(list,divider,reader,noteDivider,notePane);articlesPane.append(tools,split);
 const subsPane=el('section','rsr-subs'),mine=el('div','rsr-groups'),browse=el('section','rsr-browse'),browseBar=el('div','rsr-tools');
 const language=el('select'),topic=el('select'),groupSearch=el('input'),directoryBox=el('div','rsr-directory');
 language.setAttribute('aria-label',t('All languages'));language.append(option(t('All languages'),''));for(const [code,label] of Object.entries(LANGUAGES))language.append(option(label,code));
 topic.setAttribute('aria-label',t('All topics'));topic.append(option(t('All topics'),''));
 groupSearch.type='search';groupSearch.placeholder=t('Search groups');groupSearch.setAttribute('aria-label',t('Search groups'));groupSearch.maxLength=40;
 browseBar.append(language,topic,groupSearch);browse.append(el('h3','',t('Browse groups')),browseBar,directoryBox);
 const adding=el('section','rsr-add'),form=el('div','rss-form'),url=el('input'),name=el('input'),groupField=el('input'),every=frequencySelect(null,true),add=btn('Add feed','rss-primary');
 url.type='url';url.placeholder=t('Feed URL');url.maxLength=2048;url.setAttribute('aria-label',t('Feed URL'));
 name.type='text';name.placeholder=t('Name (optional)');name.maxLength=100;name.setAttribute('aria-label',t('Name (optional)'));
 groupField.type='text';groupField.placeholder=t('Group (optional)');groupField.maxLength=60;groupField.setAttribute('aria-label',t('Group (optional)'));
 const opmlTools=el('div','rss-tools'),importButton=btn('Import OPML'),exportButton=btn('Export OPML');
 const transfer=el('div','rss-transfer'),transferNote=el('small','rss-transfer-note'),opmlText=el('textarea','rss-opml'),transferActions=el('div','rss-form'),chooseFile=btn('Choose file'),importNow=btn('Import','rss-primary'),closeTransfer=btn('Close');
 opmlText.rows=8;opmlText.setAttribute('aria-label','OPML');transferActions.append(chooseFile,importNow,closeTransfer);transfer.append(transferNote,opmlText,transferActions);transfer.hidden=true;
 form.append(url,name,groupField,every,add);opmlTools.append(importButton,exportButton);adding.append(el('h3','',t('Add a feed')),form,opmlTools,transfer);
 subsPane.append(el('h3','',t('My subscriptions')),mine,browse,adding);subsPane.hidden=true;
 root.replaceChildren(bar,status,helpPanel,articlesPane,subsPane);
 const note=(value,error=false)=>{status.textContent=value;status.className='rss-status'+(error?' rss-error':'');};
 // --- calls ------------------------------------------------------------------------------------------------------
 // Each call's request key, from the host (it needs a secure page); a local one otherwise.
 const requestKey=()=>{try{return String(bridge.requestKey());}catch{return 'r'+Date.now().toString(36)+Math.floor(Math.random()*1e12).toString(36);}};
 async function call(operation,parameters={}){
  const reply=await bridge.invoke({compositionReference:REF,sourceMode:'parameters',input:{operation,parameters,request_key:requestKey()}});
  if(reply?.error)throw Error(String(reply.error));
  const result=reply?.response;
  if(!result)throw Error('Local RSS returned no result.');
  if(result.kind==='subscriptions')take(result);
  return result;
 }
 // One action at a time; a click while another runs waits for it.
 const idle=()=>new Promise(resolve=>{const check=()=>busy&&!disposed?setTimeout(check,150):resolve();check();});
 // An AI app's action (`raise`) gets the error back as well as the note.
 const action=(fn,raise=false)=>async()=>{while(busy&&!disposed)await idle();if(disposed){if(raise)throw Error('The view closed.');return;}busy=true;refresh.disabled=true;try{return await fn();}catch(error){note(say(error.message),true);if(raise)throw error;}finally{busy=false;refresh.disabled=false;schedule();}};
 const serial=fn=>action(fn,true)();
 const picked=()=>source&&source!==self?source:undefined;
 // Each feed's status after a read: a feed that failed shows why under it at once, not at the next change.
 const statuses=()=>call('rss_subscriptions').catch(()=>{});
 // --- subscriptions -----------------------------------------------------------------------------------------------
 // The list is drawn again when the subscriptions change (their revision); a feed's status (its error, its title) comes
 // from reading it, which changes no revision, so each answer repaints the rows in place, keeping what is being typed.
 const rows=new Map(),renames=[];  // renames: each group's name field, with the group it renames
 function take(result){const changed=!subs||subs.revision!==result.revision;subs=result;self=result.self||self;
  if(changed){renderMine();renderFilter();if(listing)renderDirectory();}else for(const feed of subs.feeds||[])rows.get(feed.url)?.(feed);}
 const groupFeeds=key=>(subs?.feeds||[]).filter(f=>f.group===key);
 function keepOpen(){if(bridge.kept?.write)bridge.kept.write(OPEN,{open:[...open]}).catch(()=>{});}
 function renderMine(){
  mine.replaceChildren();rows.clear();renames.length=0;
  for(const group of subs?.groups||[]){
   const feeds=groupFeeds(group.key),box=el('details','rsr-group'),summary=el('summary');
   box.open=open.has(group.key);box.addEventListener('toggle',()=>{if(box.open)open.add(group.key);else open.delete(group.key);keepOpen();});
   const label=el('span','rsr-group-name',group.name),meta=el('small','',[feeds.length+' '+t('feeds'),group.source==='directory'?t('Following · synced'):t('Own'),
    t(FREQUENCIES.find(f=>f[0]===group.refresh_seconds)?.[1]||'15 min'),group.enabled?'':t('Off')].filter(Boolean).join(' · '));
   summary.append(label,meta);box.append(summary);
   const controls=el('div','rsr-group-controls'),onBox=el('input'),onLabel=el('label','rsr-check');
   onBox.type='checkbox';onBox.checked=group.enabled;onBox.setAttribute('aria-label',group.name);onLabel.append(onBox,el('span','',t('On')));
   const defaultEvery=frequencySelect(group.refresh_seconds,false);defaultEvery.setAttribute('aria-label',t('Default frequency')+' · '+group.name);
   const rename=el('input'),renameButton=btn('Rename'),drop=btn(group.source==='directory'?'Unfollow':'Remove group');
   rename.type='text';rename.maxLength=60;rename.value=group.name;rename.setAttribute('aria-label',t('Group name'));renames.push([rename,group]);
   onBox.onchange=action(()=>call('rss_set_group',{key:group.key,enabled:onBox.checked}));
   defaultEvery.onchange=action(()=>call('rss_set_group',{key:group.key,refresh_seconds:Number(defaultEvery.value)}));
   renameButton.onclick=action(async()=>{const value=rename.value.trim();if(value&&value!==group.name)await call('rss_set_group',{key:group.key,name:value});});
   drop.onclick=action(async()=>{open.delete(group.key);keepOpen();await call('rss_set_group',{key:group.key,remove:true});await loadArticles();});
   controls.append(onLabel,defaultEvery,rename,renameButton,drop);box.append(controls);
   for(const feed of feeds)box.append(feedRow(feed));
   mine.append(box);
  }
 }
 function feedRow(feed){
  const row=el('div','rss-feed'),onBox=el('input');onBox.type='checkbox';onBox.checked=feed.enabled;onBox.setAttribute('aria-label',feed.name||feed.url);
  const title=el('span'),detail=el('small'),label=el('span','rss-feed-name');label.append(title,detail);
  const paint=now=>{const problem=now.status?.status==='error'?say(now.status.error):'';title.textContent=now.name||now.status?.title||now.url;
   detail.textContent=problem||now.url;detail.className=problem?'rss-error':'';};
  paint(feed);rows.set(feed.url,paint);
  const own=frequencySelect(feed.refresh_seconds,true);own.setAttribute('aria-label',t('Frequency')+' · '+(feed.name||feed.url));
  onBox.onchange=action(()=>call('rss_update_feed',{url:feed.url,enabled:onBox.checked}));
  own.onchange=action(()=>call('rss_update_feed',{url:feed.url,refresh_seconds:own.value===''?null:Number(own.value)}));
  row.append(onBox,label,own);
  if(feed.origin!=='directory'){const remove=btn('Remove');remove.onclick=action(()=>call('rss_remove_feed',{url:feed.url}));row.append(remove);}
  return row;
 }
 async function addFeed({url:value,name:label,group,refresh_seconds},taken=()=>{}){
  const had=new Set((subs?.feeds||[]).map(f=>f.url));
  await call('rss_add_feed',{url:value,...(label?{name:label}:{}),...(group?{group}:{}),...(refresh_seconds!=null?{refresh_seconds}:{})});
  taken();
  // Read the new feed now; the background reader takes it from here.
  const added=(subs?.feeds||[]).find(f=>!had.has(f.url));if(added){await call('rss_refresh',{feed:added.url}).catch(()=>{});await statuses();}await loadArticles();
  return added?(subs?.feeds||[]).find(f=>f.url===added.url)||added:null;
 }
 add.onclick=action(async()=>{
  const value=url.value.trim();if(!value)return;
  await addFeed({url:value,name:name.value.trim(),group:groupField.value.trim(),refresh_seconds:every.value!==''?Number(every.value):null},()=>{url.value='';name.value='';});
 });
 // --- browsing the picked source's directory ------------------------------------------------------------------------
 let topicsListed=false;
 async function loadDirectory(){
  const parameters={...(picked()?{source:picked()}:{}),...(language.value?{language:language.value}:{}),...(topic.value?{topic:topic.value}:{}),...(groupSearch.value.trim()?{query:groupSearch.value.trim()}:{})};
  listing=await call('rss_directory',parameters);
  if(!topicsListed){const keep=topic.value;topic.replaceChildren(option(t('All topics'),''));for(const value of listing.topics||[])topic.append(option(topicLabel(value),value));topic.value=keep;topicsListed=true;}
  renderDirectory();
 }
 // A group is followed once, from whichever source it was followed: Local RSS keeps one group for each directory id.
 const heldGroup=id=>(subs?.groups||[]).find(g=>g.source==='directory'&&g.directory_id===id);
 function renderDirectory(){
  directoryBox.replaceChildren();
  // The source this listing came from: a row follows from it even if the picker has moved on since.
  const from=listing?.source&&listing.source!==self?listing.source:undefined;
  for(const group of listing?.groups||[]){
   const row=el('div','rsr-dir-row'),box=el('details','rsr-group'),summary=el('summary');
   summary.append(el('span','rsr-group-name',groupName(group)),el('small','',[LANGUAGES[group.language]||group.language,(group.topics||[]).map(topicLabel).join(', '),(group.feeds||[]).length+' '+t('feeds')].join(' · ')));
   box.append(summary,el('p','rsr-description',(zh?group.description?.['zh-Hant']:group.description?.en)||''));
   for(const feed of group.feeds||[]){const line=el('div','rsr-dir-feed');line.append(el('span','',feed.name),el('small','',feed.url));box.append(line);}
   const followed=Boolean(heldGroup(group.id)),follow=btn(followed?'Following':'Follow',followed?'':'rss-primary');follow.disabled=followed;
   follow.setAttribute('aria-label',t(followed?'Following':'Follow')+' '+groupName(group));
   follow.onclick=action(()=>followGroup(group,from));
   row.append(box,follow);directoryBox.append(row);
  }
  if(!(listing?.groups||[]).length)directoryBox.append(el('p','rss-empty',t('No groups match.')));
 }
 // Follow a directory group from `from` (another RSS source), or from the picked one when it is this Local RSS.
 async function followGroup(group,from){
  if(heldGroup(group.id)){if(listing)renderDirectory();return false;}const had=new Set((subs?.groups||[]).map(g=>g.key));
  await call('rss_follow',{id:group.id,name:groupName(group).slice(0,60),...(from?{source:from}:{})});if(listing)renderDirectory();note(t('Now following')+' '+groupName(group));
  const added=(subs?.groups||[]).find(g=>!had.has(g.key));if(added){await call('rss_refresh',{group:added.key,...(from?{source:from}:{})}).catch(()=>{});await statuses();}await loadArticles();
  return true;
 }
 language.onchange=action(loadDirectory);topic.onchange=action(loadDirectory);groupSearch.onchange=action(loadDirectory);
 // --- OPML -----------------------------------------------------------------------------------------------------------
 importButton.onclick=()=>{transfer.hidden=false;opmlText.removeAttribute('readonly');opmlText.value='';transferNote.textContent=t('Paste OPML here, or choose an OPML file.');chooseFile.hidden=typeof bridge.pickTextFile!=='function';importNow.hidden=false;};
 exportButton.onclick=()=>{const groups=new Map((subs?.groups||[]).map(g=>[g.key,g.name]));transfer.hidden=false;opmlText.setAttribute('readonly','');
  opmlText.value=globalThis.RSSOPML.write((subs?.feeds||[]).map(f=>({url:f.url,name:f.name,group:groups.get(f.group)||''})),t('RSS Viewer'));
  transferNote.textContent=t('Copy this OPML into another reader.');chooseFile.hidden=true;importNow.hidden=true;};
 closeTransfer.onclick=()=>{transfer.hidden=true;opmlText.value='';};
 chooseFile.onclick=async()=>{try{const file=await bridge.pickTextFile();if(file?.text!=null)opmlText.value=file.text;}catch(error){note(say(error.message),true);}};
 async function importOPML(text,taken=()=>{}){
  const found=globalThis.RSSOPML.parse(text).feeds;if(!found.length)throw Error(t('No feeds found in this OPML.'));
  const result=await call('rss_import',{feeds:found.slice(0,500).map(f=>({url:f.url,...(f.name?{name:f.name}:{}),...(f.group?{group:f.group}:{})}))});
  taken();const c=result.imported||{};
  note(t('Imported')+' '+(c.added||0)+' '+t('feeds')+(c.listed?' · '+c.listed+' '+t('already listed'):'')+(c.over?' · '+c.over+' '+t('over the limit'):''),Boolean(c.over));
  return c;
 }
 importNow.onclick=action(()=>importOPML(opmlText.value,()=>{transfer.hidden=true;opmlText.value='';}));
 // --- text size per panel, and the panels' widths -----------------------------------------------------------------
 let listWidth=0,noteWidth=0,drag=null;
 function applyLayout(){
  const sizes=prefs.sizes||{},style=[];
  if(listWidth)style.push('--rsr-list:'+listWidth+'px');
  if(noteWidth)style.push('--rsr-note:'+noteWidth+'px');
  for(const panel of ['list','story','note'])style.push('--rsr-'+panel+'-scale:'+(SCALES.includes(sizes[panel])?sizes[panel]:1));
  split.setAttribute('style',style.join(';'));
  split.className='rss-split'+(prefs.noteOpen===false?' rsr-notes-closed':'')+(drag?' rsr-dragging':'');
 }
 function sizeButtons(panel){
  const box=el('span','rsr-sizes'),smaller=btn('A−','rsr-size'),larger=btn('A+','rsr-size');
  smaller.setAttribute('aria-label',t('Smaller text'));larger.setAttribute('aria-label',t('Larger text'));smaller.title=t('Smaller text');larger.title=t('Larger text');
  const at=()=>Math.max(0,SCALES.indexOf((prefs.sizes||{})[panel]??1));
  const step=delta=>{const next=SCALES[Math.min(SCALES.length-1,Math.max(0,at()+delta))];prefs.sizes={...(prefs.sizes||{}),[panel]:next};keepPrefs();applyLayout();
   smaller.disabled=at()===0;larger.disabled=at()===SCALES.length-1;};
  smaller.disabled=at()===0;larger.disabled=at()===SCALES.length-1;
  smaller.onclick=()=>step(-1);larger.onclick=()=>step(1);box.append(smaller,larger);return box;
 }
 listHead.append(listCount,sizeButtons('list'));
 // --- articles ---------------------------------------------------------------------------------------------------------
 function renderFilter(){
  const choice=filter.value,values=[''];filter.replaceChildren(option(t('All feeds'),''));
  for(const group of subs?.groups||[]){
   const box=el('optgroup');box.setAttribute('label',group.name);filter.append(box);
   const all=option(t('All in')+' '+group.name,'group:'+group.key);box.append(all);values.push(all.value);
   for(const feed of groupFeeds(group.key)){box.append(option(feed.name||feed.url,feed.url));values.push(feed.url);}
  }
  filter.value=values.includes(choice)?choice:'';
 }
 function when(value){try{return new Intl.DateTimeFormat(context.locale||'en',{timeZone:context.timezone||'UTC',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value).getTime());}catch{return '';}}
 // The calendar day of a time in the viewer's time zone, for Today.
 const dayOf=ms=>{try{return new Intl.DateTimeFormat('en-CA',{timeZone:context.timezone||'UTC',year:'numeric',month:'2-digit',day:'2-digit'}).format(ms);}catch{return '';}};
 const SPANS={'24h':864e5,'3d':3*864e5,'7d':7*864e5,'30d':30*864e5};
 const timeOf=a=>{const ms=Date.parse(a.published_at||'');return Number.isFinite(ms)?ms:null;};
 function shown(){
  const choice=filter.value,q=search.value.trim().toLowerCase(),now=Date.now(),today=prefs.when==='today'?dayOf(now):'';
  const items=articles.filter(a=>(!choice||(choice.startsWith('group:')?a.group===choice.slice(6):a.feed===choice))&&(!q||(a.title+' '+a.summary+' '+a.feed_name).toLowerCase().includes(q))
   &&(!prefs.when||(()=>{const ms=timeOf(a);return ms!==null&&(today?dayOf(ms)===today:now-ms<=SPANS[prefs.when]);})()));
  // Newest or oldest first; a story with no date goes last either way.
  return items.sort((x,y)=>{const a=timeOf(x),b=timeOf(y);if(a===b)return 0;if(a===null)return 1;if(b===null)return -1;return prefs.order==='oldest'?a-b:b-a;});
 }
 function tagInfo(entry){
  const lines=[entry.tag];
  for(const by of entry.by){
   if(by.members?.length)lines.push(by.members.map(m=>m.name+(m.code?' ('+m.code+')':'')).join('、'));
   lines.push(t('Tagged by')+' '+(by.analyst||'—')+(by.tagged_at?' · '+when(by.tagged_at):''));
  }
  return lines.join('\n');
 }
 // A story's tags as chips; each one's tooltip says which members it is about, who tagged it and when.
 function tagChips(url,most){
  const found=tagsByUrl.get(url)||[];if(!found.length)return null;
  const box=el('div','rsr-tags');
  for(const entry of found.slice(0,most)){const chip=el('span','rsr-tag',entry.tag);chip.title=tagInfo(entry);box.append(chip);}
  if(found.length>most){const more=el('span','rsr-tag rsr-tag-more','+'+(found.length-most));more.title=found.slice(most).map(tagInfo).join('\n\n');box.append(more);}
  return box;
 }
 function queueTags(){
  if(context.sourceMode==='snapshot'||tagsLoading)return;
  const now=Date.now(),urls=[...new Set(articles.map(a=>a.url).filter(Boolean))]
   .filter(u=>!tagsAskedAt.has(u)||(!(tagsByUrl.get(u)||[]).length&&now-tagsAskedAt.get(u)>TAGS_AGAIN_MS)).slice(0,300);
  if(!urls.length)return;
  tagsLoading=true;
  action(async()=>{
   try{
    const got=(await call('rss_tags',{urls})).tags||{};
    for(const u of urls){tagsAskedAt.set(u,Date.now());tagsByUrl.set(u,got[u]||[]);}
    if(urls.some(u=>(got[u]||[]).length))renderArticles();
   }catch{for(const u of urls)tagsAskedAt.set(u,Date.now());}  // no Local Analyst: the stories just have no tags
   finally{tagsLoading=false;}
  })();
 }
 function renderArticles(){
  const items=shown();if(!items.some(a=>a.feed+a.id===selected))selected=items[0]?items[0].feed+items[0].id:'';
  listItems.replaceChildren();listCount.textContent=items.length+' '+t('articles');
  for(const item of items){const key=item.feed+item.id,button=btn('','rss-story');button.setAttribute('aria-pressed',String(selected===key));
   button.append(el('div','rss-meta',item.feed_name+' · '+(item.published_at?when(item.published_at):'')),el('strong','',item.title),el('span','rss-preview',(item.summary||'').slice(0,110)));
   const chips=tagChips(item.url,3);if(chips)button.append(chips);
   button.onclick=()=>{selected=key;renderArticles();};listItems.append(button);}
  if(!items.length)listItems.append(el('p','rss-empty',t(articles.length?'No articles match.':'No articles yet. Subscribe to feeds, then refresh.')));
  const item=items.find(a=>a.feed+a.id===selected);reader.replaceChildren();
  if(!item){reader.append(el('p','rss-empty',t('Select an article to read.')));renderNotes(null,'');return;}
  renderStory(item);
 }
 // --- one story: open its page, translate it, keep a note on it ---------------------------------------------------------
 function renderStory(item){
  const key=item.feed+item.id,slot=key+'|'+prefs.language,translation=translated.get(slot),inTranslation=Boolean(translation&&showing.get(key));
  // A translation fills in part by part; the parts still coming show as an ellipsis.
  const translatedText=translation?translation.parts.filter(part=>part!=null).join('\n\n')+(translating.has(slot)?'\n\n…':''):'';
  const body=el('div','rss-body',inTranslation?translatedText:(texts.get(key)??item.summary??''));
  const storyTools=el('div','rsr-story-tools');
  if(item.url){
   // The view can't open a page itself; the Terminal opens it in a new tab. An older Terminal shows the address to copy.
   if(typeof bridge.openLink==='function'){const page=btn('Open article');page.title=item.url;page.onclick=()=>{Promise.resolve(bridge.openLink(item.url)).catch(error=>note(say(error.message),true));};storyTools.append(page);}
   else storyTools.append(el('span','rsr-url',item.url));
  }
  if(context.sourceMode!=='snapshot')storyTools.append(...translateTools(item,key,translation,inTranslation));
  storyTools.append(sizeButtons('story'));
  reader.append(el('div','rss-meta',[item.feed_name,item.author,item.published_at?when(item.published_at):''].filter(Boolean).join(' · ')),
   el('h2','',inTranslation?translation.title||item.title:item.title));
  const chips=tagChips(item.url,40);if(chips)reader.append(chips);
  if(inTranslation)reader.append(el('p','rsr-translated',t('Translated with')+' '+(translation.model||'')));
  reader.append(storyTools,body);
  renderNotes(item,key);
  if(!texts.has(key))call('rss_article',{feed:item.feed,id:item.id}).then(r=>{texts.set(key,r.article.content||r.article.summary||'');if(selected===key&&!disposed&&!showing.get(key))body.textContent=texts.get(key);}).catch(()=>{});
  if(!choicesAsked&&context.sourceMode!=='snapshot')loadChoices();
 }
 function translateTools(item,key,translation,inTranslation){
  const model=el('select','rsr-llm');model.setAttribute('aria-label',t('Model'));
  if(llms===null)model.append(option(t('Loading models…'),''));
  else if(!llms.length)model.append(option(t('No model found'),''));
  else{
   const heading={local:t('This computer'),own:t('Your key'),site:t('Plaza (points)')};
   for(const kind of ['local','own','site']){const rows=llms.filter(m=>m.source===kind);if(!rows.length)continue;const box=el('optgroup');box.setAttribute('label',heading[kind]);
    for(const m of rows)box.append(option(m.name+' · '+m.by+(m.points!=null?' · '+m.points+' '+t('points'):''),llmKey(m)));model.append(box);}
   model.value=llms.some(m=>llmKey(m)===llmKey(prefs.llm))?llmKey(prefs.llm):llmKey(llms[0]);
  }
  model.onchange=()=>{prefs.llm=(llms||[]).find(m=>llmKey(m)===model.value)||null;keepPrefs();};
  const language=el('select','rsr-lang');language.setAttribute('aria-label',t('Translate to'));
  for(const [code,label] of Object.entries(LANGUAGES))language.append(option(label,code));language.value=prefs.language;
  language.onchange=()=>{prefs.language=language.value;keepPrefs();renderArticles();};
  const slot=key+'|'+prefs.language,busyHere=translating.has(slot);
  const go=btn(busyHere?'Translating…':translation?(inTranslation?'Show original':'Show translation'):'Translate');
  go.disabled=busyHere||(!translation&&!(llms&&llms.length));
  go.onclick=translation&&!busyHere?()=>{showing.set(key,!inTranslation);renderArticles();}:()=>{
   const chosen=(llms||[]).find(m=>llmKey(m)===model.value);if(!chosen||translating.has(slot))return;
   prefs.llm=chosen;keepPrefs();translating.add(slot);showing.set(key,true);note(t('Translating…'));renderArticles();
   translatePart(item,key,chosen,prefs.language,0);
  };
  return [model,language,go];
 }
 // One part per call, each its own action: a slow model on this computer answers each part in time, the story fills
 // in as parts come back, and other actions (a note, a refresh) run in between.
 function translatePart(item,key,chosen,language,part){
  const slot=key+'|'+language;
  action(async()=>{
   let result;
   try{result=await call('rss_translate',{feed:item.feed,id:item.id,language,part,llm:{source:chosen.source,agent:chosen.agent,provider:chosen.provider,model:chosen.model}});}
   catch(error){translating.delete(slot);if(selected===key)renderArticles();throw error;}
   const held=translated.get(slot)||{title:'',parts:[],total:result.parts,model:''};
   held.parts[part]=result.text||'';if(part===0)held.title=result.title||'';held.total=result.parts;held.model=result.model||held.model;
   translated.set(slot,held);
   const done=held.parts.filter(text=>text!=null).length,more=part+1<result.parts;
   if(!more)translating.delete(slot);
   note(more?t('Translating…')+' '+done+'/'+held.total:t('Translated with')+' '+held.model);
   if(selected===key)renderArticles();
   if(more&&!disposed)translatePart(item,key,chosen,language,part+1);
  })();
 }
 // The viewer's own note on the story, in the AssetStorage it picks; what is typed survives a redraw.
 // The note panel on the right: collapsible to a strip; the note on the story shown, in the AssetStorage picked.
 function renderNotes(item,key){
  if(context.sourceMode==='snapshot'){notePane.hidden=true;noteDivider.hidden=true;return;}
  if(prefs.noteOpen===false){
   const show=btn('Note','rsr-notes-toggle');show.setAttribute('aria-label',t('Show note'));show.setAttribute('aria-expanded','false');show.title=t('Show note');
   show.onclick=()=>{prefs.noteOpen=true;keepPrefs();applyLayout();renderArticles();};notePane.replaceChildren(show);return;
  }
  const head=el('div','rsr-pane-head'),collapse=btn('»','rsr-size');collapse.setAttribute('aria-label',t('Collapse note'));collapse.setAttribute('aria-expanded','true');collapse.title=t('Collapse note');
  collapse.onclick=()=>{prefs.noteOpen=false;keepPrefs();applyLayout();renderArticles();};
  head.append(el('strong','rsr-pane-title',t('My note')),sizeButtons('note'),collapse);
  const body=el('div','rsr-notes-body');
  if(item)body.append(...notePanel(item,key));else body.append(el('p','rss-empty',t('Select an article to write a note.')));
  notePane.replaceChildren(head,body);
 }
 function notePanel(item,key){
  const pick=el('select','rsr-store'),text=el('textarea','rsr-note-text'),row=el('div','rsr-note-actions');
  const save=btn('Save note','rss-primary'),said=el('small','rsr-note-said');
  pick.setAttribute('aria-label',t('Note store'));text.setAttribute('aria-label',t('My note'));text.rows=4;text.maxLength=20000;text.placeholder=t('Write a note…');
  pick.append(option(stores===null?t('Loading…'):stores.length?t('Choose a store…'):t('No AssetStorage found'),''));
  for(const s of stores||[])pick.append(option(s.name+(s.local?' · '+t('this computer'):' · Plaza'),s.agentId));
  pick.value=(stores||[]).some(s=>s.agentId===prefs.store)?prefs.store:'';
  const noteKey=pick.value+'|'+key,held=notes.get(noteKey);
  text.value=drafts.has(key)?drafts.get(key):held?.text||'';
  text.disabled=save.disabled=!pick.value||!held;
  said.textContent=held?.error||(held?.updated?t('Saved')+' · '+when(held.updated):pick.value&&!held?t('Loading…'):'');
  if(held?.error)said.className='rsr-note-said rss-error';
  if(pick.value&&!held&&!loadingNotes.has(noteKey)){
   loadingNotes.add(noteKey);
   action(async()=>{
    try{const r=await call('rss_note',{feed:item.feed,id:item.id,store:pick.value});notes.set(noteKey,{text:r.text||'',asset_id:r.asset_id||null,updated:r.updated||null});}
    catch(error){notes.set(noteKey,{text:'',asset_id:null,error:say(error.message)});}
    finally{loadingNotes.delete(noteKey);}
    if(selected===key)renderArticles();
   })();
  }
  pick.onchange=()=>{prefs.store=pick.value;keepPrefs();renderArticles();};
  text.oninput=()=>{drafts.set(key,text.value);};
  save.onclick=action(()=>saveNote(item,key,pick.value,text.value,notes.get(noteKey)||{}));
  row.append(save,said);
  return [pick,text,row];
 }
 async function saveNote(item,key,store,value,before){
  const r=await call('rss_save_note',{feed:item.feed,id:item.id,store,text:value,...(before.asset_id?{asset_id:before.asset_id}:{})});
  notes.set(store+'|'+key,{text:r.text||'',asset_id:r.asset_id||null,updated:r.updated||null});drafts.delete(key);
  note(t(r.deleted?'Note removed':'Saved'));renderArticles();
  return r;
 }
 // The models and stores, asked once a story is open (Terminal data requests: they take a moment).
 function loadChoices(){
  choicesAsked=true;
  action(async()=>{
   try{llms=(await call('rss_llms')).llms||[];}catch(error){llms=[];note(say(error.message),true);}
   try{stores=(await call('rss_stores')).stores||[];}catch{stores=[];}
   if(!prefs.llm&&llms.length)prefs.llm=llms[0];
   renderArticles();
  })();
 }
 // --- the movable bars: list | story, and story | note ---------------------------------------------------------------
 const noteSpace=()=>prefs.noteOpen===false?32:(noteWidth||notePane.clientWidth||280);
 const setWidth=px=>{const total=split.clientWidth||0;listWidth=Math.round(Math.max(160,total?Math.min(px,total-noteSpace()-240):px));applyLayout();};
 const setNoteWidth=px=>{const total=split.clientWidth||0;noteWidth=Math.round(Math.max(200,total?Math.min(px,total-(listWidth||list.clientWidth)-240):px));applyLayout();};
 const keepWidth=()=>{if(bridge.kept?.write)bridge.kept.write(SPLIT,{width:listWidth||null,note:noteWidth||null}).catch(()=>{});};
 const endDrag=()=>{if(!drag)return;drag=null;applyLayout();keepWidth();};
 divider.addEventListener('pointerdown',event=>{drag={which:'list',x:event.clientX,width:list.clientWidth};applyLayout();});
 noteDivider.addEventListener('pointerdown',event=>{if(prefs.noteOpen===false)return;drag={which:'note',x:event.clientX,width:notePane.clientWidth};applyLayout();});
 split.addEventListener('pointermove',event=>{if(!drag)return;const moved=event.clientX-drag.x;if(drag.which==='list')setWidth(drag.width+moved);else setNoteWidth(drag.width-moved);});
 for(const type of ['pointerup','pointerleave','pointercancel'])split.addEventListener(type,endDrag);
 divider.addEventListener('keydown',event=>{if(event.key!=='ArrowLeft'&&event.key!=='ArrowRight')return;setWidth((listWidth||list.clientWidth)+(event.key==='ArrowLeft'?-24:24));keepWidth();});
 noteDivider.addEventListener('keydown',event=>{if(event.key!=='ArrowLeft'&&event.key!=='ArrowRight')return;setNoteWidth((noteWidth||notePane.clientWidth)+(event.key==='ArrowLeft'?24:-24));keepWidth();});
 whenPick.onchange=()=>{prefs.when=whenPick.value;keepPrefs();renderArticles();};
 orderPick.onchange=()=>{prefs.order=orderPick.value;keepPrefs();renderArticles();};
 // The articles of the group or feed the filter picks, asked of Local RSS: an older group's articles may not be among
 // the newest of every feed.
 const picks=value=>value.startsWith('group:')?{group:value.slice(6)}:value?{feed:value}:{};
 let loadedFor='';
 async function loadArticles(){
  const choice=filter.value,result=await call('rss_articles',picks(choice));
  if(choice!==filter.value)return;  // the filter moved on; its own load follows
  const before=articles.length&&articles[0].feed+articles[0].id,after=result.items.length&&result.items[0].feed+result.items[0].id;
  if(choice!==loadedFor||before!==after||articles.length!==result.items.length){articles=result.items;loadedFor=choice;renderArticles();}
  note(t('Updated')+' · '+articles.length+' '+t('articles'));
  queueTags();
 }
 const reloadArticles=action(loadArticles);
 search.oninput=renderArticles;filter.onchange=()=>{renderArticles();if(context.sourceMode!=='snapshot'){note(t('Loading…'));reloadArticles();}};
 async function refreshNow(){
  note(t('Loading…'));const result=await call('rss_refresh',picked()?{source:picked()}:{});await statuses();await loadArticles();
  const via=picked()?' · '+t('through')+' '+(sources.find(s=>s.agentId===picked())?.name||picked()):'';
  // Everything read within the last minute: the list is current, so say only that.
  if(!result.read&&!result.failed&&!result.waiting&&!result.error)return result;
  note(t('Read')+' '+result.read+' '+t('feeds')+(result.failed?' · '+result.failed+' '+t('failed'):'')+(result.waiting?' · '+result.waiting+' '+t('waiting for the background reader'):'')+via+(result.error?' · '+say(result.error):''),Boolean(result.failed||result.error));
  return result;
 }
 refresh.onclick=action(refreshNow);
 // --- tabs and the source picker ---------------------------------------------------------------------------------------
 function show(which){tab=which;articlesPane.hidden=which!=='articles';subsPane.hidden=which!=='subscriptions';
  articlesTab.setAttribute('aria-selected',String(which==='articles'));subsTab.setAttribute('aria-selected',String(which==='subscriptions'));
  articlesTab.className='rsr-tab'+(which==='articles'?' rsr-active':'');subsTab.className='rsr-tab'+(which==='subscriptions'?' rsr-active':'');}
 articlesTab.onclick=()=>show('articles');
 subsTab.onclick=action(async()=>{show('subscriptions');if(!listing)await loadDirectory();});
 function renderSources(){sourcePick.replaceChildren();
  for(const s of sources)sourcePick.append(option(s.name+(s.local?' · '+t('this computer'):' · Plaza'),s.agentId));
  if(sources.some(s=>s.agentId===source))sourcePick.value=source;}
 async function chooseSource(value){source=value;if(typeof bridge.setParameters==='function')await bridge.setParameters({source_agent:source});topicsListed=false;listing=null;directoryBox.replaceChildren(el('p','rss-empty',t('Loading…')));if(tab==='subscriptions')await loadDirectory();}
 sourcePick.onchange=action(()=>chooseSource(sourcePick.value));
 // --- page values: the source picked, groups another panel asks to follow, an earlier copy's feeds -------------------
 async function pageValues(){
  const values=typeof bridge.parameters==='function'?(await bridge.parameters())?.values||{}:context.parameters||{};
  if(values.source_agent&&!source)source=values.source_agent;
  const asked=Array.isArray(values.follow)?values.follow:[];
  if(asked.length){
   const names=[];
   for(const entry of asked){try{await call('rss_follow',{id:entry.id,...(entry.source&&entry.source!==self?{source:entry.source}:{}),...(entry.name?{name:entry.name}:{})});names.push(entry.name||entry.id);}catch(error){note(say(error.message),true);}}
   await bridge.setParameters({follow:[]});
   if(names.length){note(t('Now following')+' '+names.join(', '));await call('rss_refresh',{}).catch(()=>{});await loadArticles();if(listing)await loadDirectory();}
  }
  const earlier=Array.isArray(values.feeds)?values.feeds:[];
  if(earlier.length){
   const result=await call('rss_import',{feeds:earlier.slice(0,500).map(f=>({url:f.url,...(f.name?{name:f.name}:{}),...(f.group?{group:f.group}:{}),enabled:f.enabled!==false,
    ...(Object.hasOwn(f,'refresh_seconds')?{refresh_seconds:f.refresh_seconds}:{})}))});
   await bridge.setParameters({feeds:[],groups:[]});
   if(result.imported?.added)note(t('Moved your earlier feeds into Local RSS')+' · '+result.imported.added+' '+t('feeds'));
  }
 }
 // --- waking ---------------------------------------------------------------------------------------------------------
 function schedule(){clearTimeout(timer);if(disposed)return;
  timer=setTimeout(async()=>{if(!busy){busy=true;try{await pageValues();await call('rss_subscriptions');await loadArticles();}catch(error){note(say(error.message),true);}finally{busy=false;}}schedule();},WAKE_MS);}
 const stop=()=>{disposed=true;clearTimeout(timer);document.removeEventListener('phemacast:context',onContext);};
 let started=Promise.resolve();
 // --- What an AI app may ask (release.py READER_ACTIONS) ----------------------------------------------------------------
 // Each action takes the steps a click takes, through the same functions and one action at a time, so Local RSS keeps the
 // subscriptions as it always does and the window shows the outcome. Feeds are named by their names or addresses, groups
 // and stories by their names and titles. Not offered: Remove, Remove group and Unfollow, Translate, Open article, and an
 // empty note (it removes the note).
 // Undo (the Terminal's, `undo` in an edit's answer): set_group, set_feed and a replaced note give their inverse, the
 // same action with what was there before. Subscribing, following and importing give none: Local RSS keeps them, and
 // removing is not offered.
 const fail=text=>new Error(text),quoted=text=>'“'+text+'”';
 const same=(a,b)=>String(a??'').trim().toLowerCase()===String(b??'').trim().toLowerCase();
 const brief=(text,most)=>{const value=String(text??'');return value.length>most?value.slice(0,most-1)+'…':value;};
 function named(list,name,what,labels){
  const exact=list.filter(x=>labels(x).includes(name)),found=exact.length?exact:list.filter(x=>labels(x).some(label=>same(label,name)));
  if(!found.length)throw fail('There is no '+what+' named '+quoted(name)+'. describe lists them.');
  if(found.length>1)throw fail('More than one '+what+' is named '+quoted(name)+'.');
  return found[0];
 }
 const feedName=f=>f.name||f.status?.title||f.url;
 const groupNamed=name=>named(subs?.groups||[],name,'group',g=>[g.name]);
 const feedNamed=ref=>named(subs?.feeds||[],ref,'feed',f=>[f.url,f.name,f.status?.title].filter(Boolean));
 const storyNamed=title=>named(shown(),title,'story in the list',a=>[a.title]);
 const feedFacts=f=>({name:feedName(f),url:f.url,on:!!f.enabled,frequency_seconds:f.refresh_seconds??null,
  ...(f.status?.status==='error'?{problem:say(f.status.error)}:{})});
 const groupFacts=g=>({name:g.name,followed:g.source==='directory',on:!!g.enabled,frequency_seconds:g.refresh_seconds??900,feeds:groupFeeds(g.key).map(feedFacts)});
 const storyFacts=a=>({title:a.title,feed:a.feed_name,published_at:a.published_at||null});
 function filterName(){const value=filter.value;if(!value)return '';
  if(value.startsWith('group:'))return (subs?.groups||[]).find(g=>g.key===value.slice(6))?.name||'';
  const f=(subs?.feeds||[]).find(x=>x.url===value);return f?feedName(f):value;}
 function listFacts(){const items=shown(),open=items.find(a=>a.feed+a.id===selected);
  return {tab,filter:filterName(),search:search.value,count:items.length,stories:items.slice(0,20).map(storyFacts),open:open?storyFacts(open):null};}
 function live(){if(context.sourceMode==='snapshot')throw fail('This view shows a snapshot; switch it to live content first.');}
 async function ready(){live();await started;if(!subs)throw fail('Local RSS has not answered yet; try again in a moment.');}
 // A group's new name typed and not yet taken (Rename) would be drawn over.
 function notRenaming(){for(const [field,group] of renames)if(field.value.trim()!==group.name)throw fail(quoted(group.name)+' is being edited in the window.');}
 const actions={
  async describe(){
   await started;
   const picks=sources.find(s=>s.agentId===source);
   return {source:picks?picks.name:null,...(context.sourceMode==='snapshot'?{snapshot:true}:{}),groups:(subs?.groups||[]).map(groupFacts),...listFacts()};
  },
  async show({tab:which,filter:pick,search:words,article}){
   await ready();
   if(which==='subscriptions')await serial(async()=>{show('subscriptions');if(!listing)await loadDirectory();});
   else if(which==='articles')show('articles');
   if(pick!==undefined){
    let value='';
    if(pick!==''){const group=(subs.groups||[]).find(g=>same(g.name,pick));value=group?'group:'+group.key:feedNamed(pick).url;}
    filter.value=value;renderArticles();note(t('Loading…'));await serial(loadArticles);
   }
   if(words!==undefined){search.value=words;renderArticles();}
   let story=null;
   if(article!==undefined){
    if(tab!=='articles')show('articles');
    const item=storyNamed(article),key=item.feed+item.id;
    selected=key;renderArticles();
    if(!texts.has(key)){const r=await call('rss_article',{feed:item.feed,id:item.id});texts.set(key,r.article.content||r.article.summary||'');if(selected===key)renderArticles();}
    story={...storyFacts(item),url:item.url||null,text:brief(texts.get(key)||item.summary||'',1500)};
   }
   return {...listFacts(),...(story?{open:story}:{})};
  },
  async add_feed({url:address,name:label,group,frequency_seconds}){
   await ready();
   const added=await serial(()=>addFeed({url:address.trim(),name:(label||'').trim(),group:(group||'').trim(),refresh_seconds:frequency_seconds??null}));
   if(!added)throw fail('Local RSS did not add the feed.');
   const kept=(subs?.groups||[]).find(g=>g.key===added.group);
   return {feed:feedFacts(added),group:kept?.name||null};
  },
  async follow_group({group,source:by}){
   await ready();
   let from=picked();
   if(by!==undefined){const chosen=named(sources,by,'RSS source',s=>[s.name]);from=chosen.agentId!==self?chosen.agentId:undefined;}
   return serial(async()=>{
    const found=await call('rss_directory',from?{source:from}:{});
    const wanted=named(found.groups||[],group,'feed group',g=>[g.name?.en,g.name?.['zh-Hant'],g.id].filter(Boolean));
    const added=await followGroup(wanted,from);
    return {group:groupName(wanted),following:true,...(added?{}:{already:true}),feeds:(wanted.feeds||[]).map(f=>f.name)};
   });
  },
  async set_group({group,on,frequency_seconds,name:renamed}){
   await ready();notRenaming();
   const found=groupNamed(group);
   // Undo: set_group again on the group by its name now, with what it had before for each setting changed.
   const earlier={...(on!==undefined?{on:!!found.enabled}:{}),...(frequency_seconds!==undefined?{frequency_seconds:found.refresh_seconds??900}:{})},oldName=found.name;
   return serial(async()=>{
    if(on!==undefined)await call('rss_set_group',{key:found.key,enabled:on});
    if(frequency_seconds!==undefined)await call('rss_set_group',{key:found.key,refresh_seconds:frequency_seconds});
    if(renamed!==undefined&&renamed.trim()!==found.name)await call('rss_set_group',{key:found.key,name:renamed.trim()});
    const now=(subs?.groups||[]).find(g=>g.key===found.key),name=(now||found).name;
    const back={...earlier,...(name!==oldName?{name:oldName}:{})};
    return {group:groupFacts(now||found),...(Object.keys(back).length?{undo:{action:'set_group',input:{group:name,...back}}}:{})};
   });
  },
  async set_feed({feed,on,frequency_seconds}){
   await ready();notRenaming();
   const found=feedNamed(feed);
   // Undo: set_feed again on the feed by its address, with what it had before (null: its group's default).
   const back={...(on!==undefined?{on:!!found.enabled}:{}),...(frequency_seconds!==undefined?{frequency_seconds:found.refresh_seconds??null}:{})};
   return serial(async()=>{
    if(on!==undefined)await call('rss_update_feed',{url:found.url,enabled:on});
    if(frequency_seconds!==undefined)await call('rss_update_feed',{url:found.url,refresh_seconds:frequency_seconds});
    return {feed:feedFacts((subs?.feeds||[]).find(f=>f.url===found.url)||found),
     ...(Object.keys(back).length?{undo:{action:'set_feed',input:{feed:found.url,...back}}}:{})};
   });
  },
  async import_opml({opml}){
   await ready();notRenaming();
   const c=await serial(()=>importOPML(opml));
   return {added:c.added||0,already_listed:c.listed||0,over_the_limit:c.over||0};
  },
  async choose_source({source:by}){
   await ready();
   const chosen=named(sources,by,'RSS source',s=>[s.name]);
   // Undo: choose_source again with the source saved before, while the menu lists it by that one name; with none saved
   // before (the view then reads through Local RSS), or one no longer listed, the window's earlier parameter values.
   let saved='';try{saved=(typeof bridge.parameters==='function'?(await bridge.parameters())?.values:context.parameters)?.source_agent||'';}catch{}
   const earlier=saved&&sources.find(s=>s.agentId===saved),label=String(earlier?.name||'');
   const undo=label&&label.length<=120&&sources.filter(s=>s.name===label).length===1?{action:'choose_source',input:{source:label}}:'parameters';
   sourcePick.value=chosen.agentId;
   await serial(()=>chooseSource(chosen.agentId));
   return {source:chosen.name,undo};
  },
  async refresh(){
   await ready();
   const result=await serial(refreshNow);
   return {read:result?.read||0,failed:result?.failed||0,waiting:result?.waiting||0,articles:articles.length,...(result?.error?{problem:say(result.error)}:{})};
  },
  async save_note({article,text:value,store:by}){
   await ready();
   if(!String(value).trim())throw fail('Write the note; an empty note would remove it.');
   const item=storyNamed(article),key=item.feed+item.id,editing=()=>drafts.has(key);
   if(editing())throw fail('The note on '+quoted(item.title)+' is being edited in the window.');
   if(stores===null)await serial(async()=>{if(stores===null){try{stores=(await call('rss_stores')).stores||[];}catch{stores=[];}}});
   const chosen=by!==undefined?named(stores,by,'AssetStorage',s=>[s.name]):stores.find(s=>s.agentId===prefs.store);
   if(!chosen)throw fail('No AssetStorage is picked for notes; name one with store.');
   if(prefs.store!==chosen.agentId){prefs.store=chosen.agentId;keepPrefs();}
   if(tab!=='articles')show('articles');
   selected=key;renderArticles();
   return serial(async()=>{
    // As the note panel does: the note kept on the story, then Save note.
    const before=await call('rss_note',{feed:item.feed,id:item.id,store:chosen.agentId});
    if(editing())throw fail('The note on '+quoted(item.title)+' is being edited in the window.');
    const r=await saveNote(item,key,chosen.agentId,value,{asset_id:before.asset_id||null});
    // Undo: save_note again with the note kept before, in the same AssetStorage. A first note has none: an empty note,
    // which would remove it, is not offered.
    const earlier=String(before.text||''),title=String(item.title||''),storeName=String(chosen.name||'');
    const undo=earlier.trim()&&earlier.length<=20000&&title&&title.length<=500?{action:'save_note',input:{article:title,text:earlier,
     ...(storeName&&storeName.length<=120&&stores.filter(s=>s.name===storeName).length===1?{store:storeName}:{})}}:null;
    return {article:item.title,store:chosen.name,saved:!r.deleted,replaced:Boolean(before.text),...(undo?{undo}:{})};
   });
  },
 };
 // An older Terminal's view host has no `actions`; the view works as before.
 try{for(const [name,fn] of Object.entries(actions))bridge.actions?.handle?.(name,fn);}catch{}
 if(context.sourceMode==='snapshot'){
  refresh.hidden=true;subsTab.hidden=true;sourcePick.hidden=true;const pickSnapshot=el('select'),view=btn('View Content');pickSnapshot.setAttribute('aria-label',t('Snapshot'));bar.append(pickSnapshot,view);view.disabled=true;
  Promise.resolve().then(()=>bridge.snapshots()).then(value=>{if(disposed)return;for(const row of value?.snapshots||[])pickSnapshot.append(option(row.label||when(row.createdAt),row.id));view.disabled=!pickSnapshot.options.length;if(view.disabled)note(t('No saved snapshots.'));}).catch(error=>note(say(error.message),true));
  view.onclick=async()=>{try{const saved=await bridge.readSnapshot(pickSnapshot.value);const result=saved.results?.[REF]?.value;const data=result?.response||result;articles=data?.kind==='articles'?data.items:[];renderArticles();note(t('Snapshot content · refresh is off.'));}catch(error){note(say(error.message),true);}};
  show('articles');renderArticles();return stop;
 }
 show('articles');
 started=Promise.resolve().then(action(async()=>{
  note(t('Loading…'));
  if(bridge.kept?.read){
   const kept=await bridge.kept.read(OPEN);const value=kept?.value||kept;if(Array.isArray(value?.open))open=new Set(value.open);
   const story=await bridge.kept.read(STORY).catch(()=>null),chosen=story?.value||story;
   if(chosen&&typeof chosen==='object')prefs={...prefs,...Object.fromEntries(Object.entries(chosen).filter(([k])=>Object.hasOwn(prefs,k)))};
   whenPick.value=prefs.when||'';orderPick.value=prefs.order||'newest';
   const kept2=await bridge.kept.read(SPLIT).catch(()=>null),place=kept2?.value||kept2;
   if(Number.isFinite(place?.note))noteWidth=place.note;if(Number.isFinite(place?.width))setWidth(place.width);
   prefs.sizes={list:1,story:1,note:1,...(prefs.sizes&&typeof prefs.sizes==='object'?prefs.sizes:{})};applyLayout();listHead.replaceChildren(listCount,sizeButtons('list'));
  }
  await call('rss_subscriptions');
  await pageValues();
  try{sources=(await call('rss_sources')).sources||[];}catch(error){sources=[];}
  if(!sources.some(s=>s.agentId===self)&&self)sources.unshift({agentId:self,name:'Local RSS',local:true,self:true});
  if(!source||!sources.some(s=>s.agentId===source))source=self;
  renderSources();
  await loadArticles();
 })).catch(error=>note(say(error.message),true));
 return stop;
}
globalThis.RSSReader=Object.freeze({mount});
const bridge=globalThis.phemacastAgentView;
if(bridge&&typeof document!=='undefined'){const root=document.querySelector('#rss-viewer');if(root)globalThis.disposeRSSReader=mount(root,bridge);}
})();
