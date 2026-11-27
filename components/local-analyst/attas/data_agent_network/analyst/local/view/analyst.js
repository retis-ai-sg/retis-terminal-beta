/* Analyst Sentiment: the Local Analyst's view. Rules stay in the Terminal (page values), each rule's automatic runs are
   the Terminal's scheduled runs, and the results are read back from the AssetStorage the viewer picks. The analysts are
   the analyst Personas this Terminal can use, wherever they live (this computer, a Plaza, behind Pipeline). */
(()=>{
'use strict';
const REF='analyst-local',MAX_TAG_RULES=8,MAX_SENT_RULES=16,MAX_STOCK_RULES=8,MAX_TAGS=12,MAX_LISTS=12,MAX_RULE_LISTS=6,MAX_SOURCES=4,MAX_STATIC=300;
const REFRESH=[[1,'1 h'],[6,'6 h'],[24,'1 day'],[168,'1 week']];
const EVERY=[[15,'15 min'],[30,'30 min'],[60,'1 h'],[180,'3 h'],[360,'6 h'],[1440,'1 day']],PERIODS=[1,2,3,4,6,12,24];
const TAG=/^[\p{L}\p{N}_ .-]{1,30}$/u;
const ZH={'Analyst Sentiment':'分析師情緒','Rules':'規則','How to Use':'使用說明','Refresh':'更新','AssetStorage':'檔案庫','Choose…':'請選擇…',
 'Rule':'規則','New rule':'新規則','Add rule':'新增規則','Tagging':'標記','Sentiment':'情緒','Stock':'個股',
 'Tagging: tag every new news item':'標記：為每則新新聞加上標籤','Sentiment: score a tag\'s news per period':'情緒：按時段為某標籤的新聞評分',
 'Stock: score each listed stock a news item names':'個股：為新聞提到的清單股票逐檔評分',
 'Analyst':'分析師','News source':'新聞來源','Tags':'標籤','Also tag members of':'也標記這些清單的成員','Run every':'執行頻率',
 'Run automatically':'自動執行','Tag to score':'評分的標籤','One record per':'每筆紀錄涵蓋','List to score':'評分的清單',
 'Run now':'立即執行','Remove':'移除',
 'this computer':'本機','15 min':'15 分鐘','30 min':'30 分鐘','1 h':'1 小時','3 h':'3 小時','6 h':'6 小時','1 day':'1 天',
 '{0} h':'{0} 小時','Period':'時段','Score':'分數','Comment':'評論','Close':'關閉','Articles':'文章','Loading…':'載入中…','Running…':'執行中…',
 'positive':'正面','negative':'負面','neutral':'中性','mixed':'分歧','unknown':'不明',
 'No records yet. Add a tagging rule and a sentiment rule, then run them.':'尚無紀錄。請新增標記規則與情緒規則，再執行。',
 'Tagged {0} new items':'已標記 {0} 則新聞','no new news':'沒有新新聞','{0} left for the next run':'{0} 則留待下次','points used':'點已使用',
 'Saved':'已儲存','kept':'已有','no news':'無新聞','failed':'失敗','unreadable':'無法解讀','not saved':'未儲存',
 'Choose an analyst, news and tags, and an AssetStorage.':'請選擇分析師、新聞與標籤，以及檔案庫。',
 'Choose an analyst and a tag, and an AssetStorage.':'請選擇分析師與標籤，以及檔案庫。',
 'Tags are 1 to 12 words of up to 30 letters, digits, spaces, dots or dashes.':'標籤為 1 到 12 個詞，每個最多 30 個字母、數字、空格、點或連字號。',
 'Settings could not be saved: ':'無法儲存設定：','Automatic runs need a Terminal that keeps scheduled runs. Update this Terminal.':'自動執行需要能保存排程的終端，請更新終端。',
 'This Analyst Sentiment is an older copy without rules. In New Data Browser, select Analyst Sentiment, click 更新 and open a new one.':'此分析師情緒是沒有規則的舊版。請在「新增資料瀏覽器」選取「分析師情緒」，按「更新」後開啟新的。',
 'No analyst is available to this Terminal.':'此終端沒有可用的分析師。','No news source offers a news feed.':'沒有新聞來源提供新聞動態。',
 'No AssetStorage is available. Install Local AssetStorage in Retis MAS Manager, or use the site\'s.':'沒有可用的檔案庫。請在 Retis MAS Manager 安裝本機檔案庫，或使用本站的檔案庫。',
 'Recent tagging':'最近標記','{0} items':'{0} 則',
 'Named lists':'具名清單','Add list':'新增清單','Add from preset…':'從範本新增…','List name':'清單名稱','Members':'成員來源',
 'Typed in (static)':'手動輸入（固定）','Read from URLs (dynamic)':'從網址讀取（動態）','Read the URLs again every':'網址重新讀取頻率',
 '1 week':'1 週','Entries':'項目','JSON or CSV list URL':'清單網址（JSON 或 CSV）','Code suffix':'代碼字尾','Code column':'代碼欄','Name column':'名稱欄',
 'Other names column':'其他名稱欄','Add source':'新增來源','Remove source':'移除來源','Check':'檢查','Edit':'編輯','Done':'完成','Lists':'清單',
 '{0} entries':'{0} 項','read {0}':'讀取於 {0}','Checking…':'檢查中…','Choose the columns after Check.':'按「檢查」後選擇欄位。',
 'One per line: code, name, other names. A line with one value is a name.':'每行一項：代碼、名稱、其他名稱；只有一個值時為名稱。',
 'A list name is up to 30 letters, digits, spaces, dots or dashes.':'清單名稱最多 30 個字母、數字、空格、點或連字號。',
 'Choose an analyst, news and tags or lists, and an AssetStorage.':'請選擇分析師、新聞與標籤或清單，以及檔案庫。',
 '{0} list members':'{0} 個清單項目','Tagged news':'已標記新聞','Tags':'標籤','(none)':'（無）',
 'Recent stock scoring':'最近個股評分',
 'Scored {0} new items':'已評分 {0} 則新聞','{0} opinions':'{0} 筆看法','Scored news':'已評分新聞','no view':'無看法',
 'Choose an analyst and a list, and an AssetStorage.':'請選擇分析師與清單，以及檔案庫。'};
// What the Local Analyst says when a run, a list check or a record cannot go on (run.py, scoring.py, lists.py), in a
// Chinese viewer's words; one with a name, a number or another agent's own words in it is matched by its pattern.
const SAID_ZH={'A named list this rule uses is missing; open the rule and choose its lists again.':'此規則使用的具名清單已不存在；請開啟規則並重新選擇清單。',
 'The named list this rule uses is missing; open the rule and choose its list again.':'此規則使用的具名清單已不存在；請開啟規則並重新選擇清單。',
 'A tagging rule needs tags or named lists.':'標記規則需要標籤或具名清單。','no answer was returned':'沒有傳回任何回應',
 'Choose a Local Analyst operation.':'請選擇本機分析師的操作。','The Local Analyst returned no result.':'本機分析師沒有傳回結果。','unavailable':'目前無法使用',
 'The news source':'新聞來源','AssetStorage':'檔案庫',
 'The analyst did not answer with JSON.':'分析師的回答不是 JSON。','The analyst answer is not readable JSON.':'分析師的回答不是可讀取的 JSON。',
 'The analyst answer is not a JSON object.':'分析師的回答不是 JSON 物件。','The analyst answer has no tags.':'分析師的回答沒有標籤。',
 'The analyst answer has no items.':'分析師的回答沒有項目。','The analyst answer is not a readable opinion.':'分析師的回答不是可讀取的看法。',
 'That record is too large to read.':'這筆紀錄太大，無法讀取。','That AssetStorage file keeps no analyst record.':'這個檔案庫檔案沒有分析師紀錄。',
 'A list URL is a public https:// address without a user name or a custom port.':'清單網址必須是公開的 https:// 位址，不含使用者名稱或自訂連接埠。',
 'The list host could not be found.':'找不到清單網址的主機。','A list URL must reach only public internet addresses.':'清單網址只能指向公開的網際網路位址。',
 'The list took too long to read.':'讀取清單逾時。','The list URL redirected too many times.':'清單網址轉址太多次。',
 'The list URL answered with an unsupported compression.':'清單網址回應了不支援的壓縮格式。','The list is larger than 8 MB.':'清單超過 8 MB。',
 'The list is neither UTF-8 nor Big5 text.':'清單不是 UTF-8 或 Big5 文字。','Choose the column that has the names.':'請選擇含有名稱的欄位。',
 'The list has no rows: use a JSON array of objects, a {code: name} object, or CSV with a header.':'清單沒有資料列：請使用由物件組成的 JSON 陣列、{代碼: 名稱} 物件，或含標題列的 CSV。'};
const SAID_ZH_PATTERNS=[[/^The list URL answered HTTP (\d{3})\.$/,m=>'清單網址回應 HTTP '+m[1]+'。'],
 [/^The list "(.+)" has no entries\.$/,m=>'清單「'+m[1]+'」沒有項目。'],
 [/^The list "(.+?)" could not be read: (.+)$/s,(m,said)=>'無法讀取清單「'+m[1]+'」：'+said(m[2])],
 [/^The list URL could not be read: (.+)$/s,(m,said)=>'無法讀取清單網址：'+said(m[1])],
 [/^(.+?) did not answer: (.+)$/s,(m,said)=>said(m[1])+' 沒有回應：'+said(m[2])],
 [/^(.+?) gave no news: (.+)$/s,(m,said)=>said(m[1])+' 沒有提供新聞：'+said(m[2])]];
const HELP_EN='Named lists say who or what news can be about: a static list you type (one per line: code, name, other names), or a dynamic list read from public URLs every hour, day or week, such as all Taiwan stocks; presets add Taiwan stocks, currencies and industries. A tagging rule has one analyst read the news from a source and tag every new item with the tags you list (for example Taiwan Stock, FX) and with the members of the lists you tick: names found in the text are confirmed by the analyst, and an item with a member also gets the list\'s name as a tag. A sentiment rule has one analyst score the news of one tag, one record per period (for example every 6 hours): a comment and a score from -100 to +100. A period with no tagged news gets no record. A stock rule has one analyst score each tagged news item for each member of one list it names (for example 2330.TW), from -100 to +100 with a confidence; the sentiment strategy templates in Strategy Monitor read these scores. Choose the kind of rule and its analyst, then Add rule; each rule has its own analyst. Analysts are the analyst personas this Terminal can use: on this computer, on a Plaza, or behind Pipeline. Tick Run automatically to run a rule on its own schedule while this Terminal window is signed in, even with this panel closed; Run now runs it once. Each analyst call costs that analyst\'s points. Records stay in the AssetStorage you choose; select a row to read its comment and articles.';
const HELP_ZH='具名清單說明新聞可能涉及的對象：您輸入的固定清單（每行一項：代碼、名稱、其他名稱），或每小時、每天或每週從公開網址讀取的動態清單，例如全部台股；範本可加入台股、外匯幣別與產業別。標記規則讓一位分析師讀取某個來源的新聞，為每則新新聞加上您列出的標籤（例如 Taiwan Stock、FX）及您勾選清單中的項目：文中找到的名稱由分析師確認，含有清單項目的新聞也會加上該清單名稱作為標籤。情緒規則讓一位分析師為某個標籤的新聞評分，每個時段（例如每 6 小時）一筆：評論與 -100 到 +100 的分數；沒有標記新聞的時段不產生紀錄。個股情緒規則讓一位分析師為每則已標記新聞中、某個清單的每個項目（例如 2330.TW）評分，-100 到 +100 並附信心程度；策略監看的新聞情緒策略範本會讀取這些分數。選擇規則種類與分析師，再按「新增規則」；每條規則都有自己的分析師。分析師是此終端可用的分析師角色：在這台電腦、Plaza 上，或透過 Pipeline。勾選「自動執行」可在此終端視窗保持登入時依排程執行規則，即使關閉此面板；「立即執行」只執行一次。每次詢問分析師都會扣該分析師的點數。紀錄保存在您選擇的檔案庫；選取一列可閱讀評論與文章。';
function mount(root,bridge){
 const context=bridge.context||{};const language=/^zh/i.test(context.locale||'')?'zh':'en';
 const t=(key,...values)=>{let text=language==='zh'?(ZH[key]||key):key;values.forEach((v,i)=>{text=text.replace('{'+i+'}',v);});return text;};
 // A message from the Local Analyst (or another agent's words inside one) in the viewer's language; one this view
 // doesn't know stays as it came.
 const said=message=>{const text=String(message??'');if(language!=='zh')return text;if(Object.hasOwn(SAID_ZH,text))return SAID_ZH[text];
  for(const [pattern,words] of SAID_ZH_PATTERNS){const m=pattern.exec(text);if(m)return words(m,said);}return text;};
 const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n;};
 const btn=(text,cls)=>{const n=el('button',cls,t(text));n.type='button';return n;};
 const option=(text,value)=>{const n=el('option','',text);n.value=String(value);return n;};
 const requestKey=()=>typeof bridge.requestKey==='function'?String(bridge.requestKey()):crypto.randomUUID();
 const newId=()=>requestKey().replace(/[^0-9a-f]/gi,'').toLowerCase().slice(-8)||String(Date.now()%1e8);
 let disposed=false,values={named_lists:[],tagging_rules:[],sentiment_rules:[],stock_rules:[]},choices=null,rows=[],tagging=[],scored=[],selected='',runs=[],outdated=false;
 const editing=new Set(),columns={},checked={};  // lists open for editing, each URL's columns, each list's last check
 // Text being typed and not yet taken (its change event comes when the field is left), by field: the rule or list it
 // belongs to. Drawing the rules again would lose it, so an AI app's action waits for it (see `actions` below).
 const typing=new Map();
 const typed=(control,item)=>{control.addEventListener('input',()=>typing.set(control,item));control.addEventListener('change',()=>typing.delete(control));return control;};
 root.dataset.theme=context.theme||'light';
 const onContext=event=>{root.dataset.theme=event.detail?.theme||'light';};document.addEventListener('phemacast:context',onContext);
 const bar=el('div','la-bar'),brand=el('span','la-wordmark',t('Analyst Sentiment')),store=el('select'),rulesButton=btn('Rules'),refresh=btn('Refresh'),help=btn('How to Use');
 bar.append(brand);
 const status=el('p','la-status');status.setAttribute('role','status');
 const helpPanel=el('p','la-help',language==='zh'?HELP_ZH:HELP_EN);helpPanel.hidden=true;help.onclick=()=>{helpPanel.hidden=!helpPanel.hidden;};
 // Every control has its caption above it, which is also its name (Alvin, 2026-11-26: "otherwise nobody knows what 動態
 // and 1 小時 mean"); a box of several controls, or a value shown as text, is a captioned group.
 function field(caption,control,cls=''){const f=el('label','la-field'+(cls?' '+cls:''));control.setAttribute('aria-label',t(caption));
  f.append(el('span','la-cap',t(caption)),control);return f;}
 function group(caption,node,cls=''){const f=el('div','la-field'+(cls?' '+cls:''));f.setAttribute('role','group');f.setAttribute('aria-label',t(caption));
  f.append(el('span','la-cap',t(caption)),node);return f;}
 // One list of rules of every kind, in the order they were added (Alvin, 2026-11-26): choose the kind and its analyst,
 // then Add rule. Each rule keeps its own analyst.
 const KINDS=[['tag','Tagging: tag every new news item'],['sent','Sentiment: score a tag\'s news per period'],['stock','Stock: score each listed stock a news item names']];
 const KIND_NAME={tag:'Tagging',sent:'Sentiment',stock:'Stock'},MAX_RULES={tag:MAX_TAG_RULES,sent:MAX_SENT_RULES,stock:MAX_STOCK_RULES};
 const DRAFT={tag:{tags:[],every_minutes:60,enabled:false},sent:{period_hours:6,enabled:false},stock:{every_minutes:60,enabled:false}};
 const rulesPanel=el('section','la-rules'),ruleList=el('div','la-rule-list'),newKind=el('select'),newAnalyst=el('select'),addRule=btn('Add rule');
 newKind.append(...KINDS.map(([k,label])=>option(t(label),k)));
 const ruleBar=el('div','la-rule la-add');ruleBar.append(field('New rule',newKind,'la-kindpick'),field('Analyst',newAnalyst),addRule);
 let order=[];  // rule keys (kind:id) in the order they were added; kept rules come by kind when the view opens
 const listList=el('div','la-list-list'),addList=btn('Add list'),presets=el('select'),listBar=el('div','la-rule');presets.setAttribute('aria-label',t('Add from preset…'));listBar.append(addList,presets);
 rulesPanel.append(el('h4','',t('Named lists')),listList,listBar,el('h4','',t('Rules')),ruleList,ruleBar);
 bar.append(field('AssetStorage',store,'la-inline'),rulesButton,refresh,help);
 rulesButton.onclick=()=>{rulesPanel.hidden=!rulesPanel.hidden;};
 const recent=el('div','la-recent'),table=el('div','la-table'),detail=el('section','la-detail');detail.hidden=true;
 root.replaceChildren(bar,status,helpPanel,rulesPanel,recent,table,detail);
 const note=(text,error=false)=>{status.textContent=text;status.className='la-status'+(error?' la-error':'');};
 const stop=()=>{disposed=true;document.removeEventListener('phemacast:context',onContext);};
 async function call(operation,parameters){
  const reply=await bridge.invoke({compositionReference:REF,sourceMode:'parameters',input:{operation,parameters,request_key:requestKey()}});
  if(reply&&reply.error)throw Error(said(reply.error));
  if(!reply||!reply.response)throw Error(said('The Local Analyst returned no result.'));
  if(reply.response.status==='unavailable')throw Error(said(reply.response.reason||'unavailable'));
  return reply.response;
 }
 const keep=(choice,fields)=>Object.fromEntries(fields.filter(k=>choice&&choice[k]!==undefined&&choice[k]!=='').map(k=>[k,choice[k]]));
 // What the Terminal tells: an analyst's name and whether it runs on this computer.
 const where=a=>a.local?' · '+t('this computer'):'';
 const analystLabel=a=>(a.name||a.agentId)+where(a);
 const language2=()=>language==='zh'?'zh-Hant':'en';
 const listComplete=l=>!!(l&&TAG.test(l.name||'')&&(l.kind==='static'?(l.entries||[]).length>0:(l.sources||[]).length>0&&l.sources.every(s=>/^https:\/\/./.test(s.url||'')&&s.name)));
 const keptLists=()=>(values.named_lists||[]).filter(listComplete).map(clean);
 const usedLists=rule=>keptLists().filter(l=>(rule.lists||[]).includes(l.id));
 // A sentiment rule's tag is one of the tagging rules' tags or the name of a list they use.
 const tagsOffered=()=>[...new Set((values.tagging_rules||[]).flatMap(rule=>[...(rule.tags||[]),...usedLists(rule).map(l=>l.name)]))];
 function select(label,list,current,text,keyOf,empty='Choose…'){
  const n=el('select');n.setAttribute('aria-label',t(label));n.append(option(t(empty),''));
  for(const item of list)n.append(option(text(item),keyOf(item)));
  const key=current?keyOf(current):'';
  if(key&&!list.some(item=>keyOf(item)===key))n.append(option(text(current),key));  // kept, though not listed now
  n.value=key;return n;
 }
 async function save(changes){
  if(outdated){note(t('This Analyst Sentiment is an older copy without rules. In New Data Browser, select Analyst Sentiment, click 更新 and open a new one.'),true);return false;}
  for(const [k,v] of Object.entries(changes))if(k==='store')values[k]=v;
  if(typeof bridge.setParameters!=='function')return true;
  try{await bridge.setParameters(changes);return true;}catch(error){note(t('Settings could not be saved: ')+error.message,true);return false;}
 }
 const OPERATION={tag:'analyst_tag',sent:'analyst_score',stock:'analyst_stock_score'},FIELD={tag:'tagging_rules',sent:'sentiment_rules',stock:'stock_rules'};
 const stockList2=rule=>keptLists().filter(l=>l.id===rule.list);  // a stock rule's one list, while it is kept
 const runKey=(kind,rule)=>kind+'-'+rule.id;
 const runInput=(kind,rule)=>({operation:OPERATION[kind],parameters:{rule,store:values.store,language:language2(),
  ...(kind==='tag'&&usedLists(rule).length?{lists:usedLists(rule)}:{}),...(kind==='stock'?{lists:stockList2(rule)}:{})},request_key:requestKey()});
 const complete=(kind,rule)=>!!(rule.analyst&&(kind==='tag'?rule.news&&((rule.tags||[]).length||usedLists(rule).length):kind==='stock'?stockList2(rule).length:rule.tag));
 const runLabel=(kind,rule)=>kind==='tag'?[...(rule.tags||[]),...usedLists(rule).map(l=>l.name)].join(', '):kind==='stock'?stockList2(rule).map(l=>l.name).join(''):rule.tag;
 const ready=(kind,rule)=>!!values.store&&complete(kind,rule);
 // A rule ticked Auto has its own scheduled run, rescheduled whenever the rule changes; unticked or removed, it stops.
 async function follow(kind,rule){
  const found=runs.find(r=>r.key===runKey(kind,rule)&&r.status!=='stopped');
  if(rule.enabled&&ready(kind,rule)){
   if(typeof bridge.schedule!=='function'){note(t('Automatic runs need a Terminal that keeps scheduled runs. Update this Terminal.'),true);return;}
   const made=await bridge.schedule({compositionReference:REF,key:runKey(kind,rule),label:t('Analyst Sentiment')+' · '+runLabel(kind,rule),
    everySeconds:kind==='sent'?rule.period_hours*3600:rule.every_minutes*60,input:runInput(kind,rule),keyField:'request_key'});
   runs=[...runs.filter(r=>r.key!==runKey(kind,rule)),{...made,key:runKey(kind,rule),status:'running'}];
  }else if(found&&typeof bridge.stopRun==='function'){await bridge.stopRun({id:found.id});runs=runs.filter(r=>r!==found);}
 }
 async function change(kind,index,patch,remove=false){
  const field=FIELD[kind],list=[...(values[field]||[])],before=list[index];
  if(remove)list.splice(index,1);else list[index]={...before,...patch};
  // Only complete rules are kept: the Terminal refuses a rule without its analyst, news and tags (or tag). A draft row
  // stays in this view until it is complete.
  values={...values,[field]:list};
  if(!await save({[field]:list.filter(rule=>complete(kind,rule))}))return false;
  try{await follow(kind,remove?{...before,enabled:false}:list[index]);}catch(error){note(error.message,true);}
  renderRules();return true;
 }
 function tagRow(rule,index,number){
  const c=choices||{analysts:[],news:[]},row=el('div','la-rule');
  const who=select('Analyst',c.analysts,rule.analyst,analystLabel,a=>a.agentId),news=select('News source',c.news,rule.news,s=>s.name+where(s),s=>s.agentId);
  const tags=typed(el('input'),'Rule '+number);tags.type='text';tags.maxLength=400;tags.placeholder='Taiwan Stock, FX';tags.value=(rule.tags||[]).join(', ');
  const every=el('select');for(const [v,label] of EVERY)every.append(option(t(label),v));every.value=String(rule.every_minutes||60);
  const auto=el('input');auto.type='checkbox';auto.checked=!!rule.enabled;
  const now=btn('Run now'),drop=btn('Remove');
  who.onchange=()=>{const a=c.analysts.find(x=>x.agentId===who.value);if(a)change('tag',index,{analyst:keep(a,['agentId','name','local'])});};
  news.onchange=()=>{const s=c.news.find(x=>x.agentId===news.value);if(s)change('tag',index,{news:keep(s,['agentId','name','local','modelRef'])});};
  tags.onchange=()=>{const list=[...new Set(tags.value.split(/[,，、]+/).map(s=>s.trim()).filter(Boolean))];
   if(list.length>MAX_TAGS||list.some(s=>!TAG.test(s))){note(t('Tags are 1 to 12 words of up to 30 letters, digits, spaces, dots or dashes.'),true);return;}
   change('tag',index,{tags:list});};
  // The named lists this rule finds members of, ticked by name.
  const pick=el('span','la-lists');pick.hidden=!keptLists().length;
  for(const l of keptLists()){const box=el('input');box.type='checkbox';box.checked=(rule.lists||[]).includes(l.id);box.setAttribute('aria-label',l.name);
   box.onchange=()=>{const chosen=keptLists().filter(x=>x.id===l.id?box.checked:(rule.lists||[]).includes(x.id)).map(x=>x.id);
    if(chosen.length>MAX_RULE_LISTS){box.checked=false;return;}change('tag',index,{lists:chosen});};
   const label=el('label','la-auto');label.append(box,el('span','',l.name));pick.append(label);}
  every.onchange=()=>change('tag',index,{every_minutes:Number(every.value)});
  auto.onchange=()=>change('tag',index,{enabled:auto.checked});
  drop.onclick=()=>change('tag',index,{},true);
  now.onclick=()=>runOnce('tag',rule,now);
  row.append(group('Rule',el('span','la-kind',t(KIND_NAME.tag)),'la-kindcol'),field('Analyst',who),field('News source',news),field('Tags',tags,'la-wide'),...(pick.hidden?[]:[group('Also tag members of',pick,'la-group')]),field('Run every',every),
   field('Run automatically',auto,'la-check'),now,drop);return row;
 }
 function sentRow(rule,index,number){
  const c=choices||{analysts:[]},row=el('div','la-rule');
  const who=select('Analyst',c.analysts,rule.analyst,analystLabel,a=>a.agentId);
  const offered=tagsOffered(),tag=el('select');tag.append(option(t('Choose…'),''));
  for(const name of [...offered,...(rule.tag&&!offered.includes(rule.tag)?[rule.tag]:[])])tag.append(option(name,name));tag.value=rule.tag||'';
  const period=el('select');for(const h of PERIODS)period.append(option(t('{0} h',h),h));period.value=String(rule.period_hours||6);
  const auto=el('input');auto.type='checkbox';auto.checked=!!rule.enabled;
  const now=btn('Run now'),drop=btn('Remove');
  who.onchange=()=>{const a=c.analysts.find(x=>x.agentId===who.value);if(a)change('sent',index,{analyst:keep(a,['agentId','name','local'])});};
  tag.onchange=()=>{if(tag.value)change('sent',index,{tag:tag.value});};
  period.onchange=()=>change('sent',index,{period_hours:Number(period.value)});
  auto.onchange=()=>change('sent',index,{enabled:auto.checked});
  drop.onclick=()=>change('sent',index,{},true);
  now.onclick=()=>runOnce('sent',rule,now);
  row.append(group('Rule',el('span','la-kind',t(KIND_NAME.sent)),'la-kindcol'),field('Analyst',who),field('Tag to score',tag),field('One record per',period),
   field('Run automatically',auto,'la-check'),now,drop);return row;
 }
 function stockRow(rule,index,number){
  const c=choices||{analysts:[]},row=el('div','la-rule');
  const who=select('Analyst',c.analysts,rule.analyst,analystLabel,a=>a.agentId);
  const list=select('List to score',keptLists(),keptLists().find(l=>l.id===rule.list)||null,l=>l.name,l=>l.id);
  const every=el('select');for(const [v,label] of EVERY)every.append(option(t(label),v));every.value=String(rule.every_minutes||60);
  const auto=el('input');auto.type='checkbox';auto.checked=!!rule.enabled;
  const now=btn('Run now'),drop=btn('Remove');
  who.onchange=()=>{const a=c.analysts.find(x=>x.agentId===who.value);if(a)change('stock',index,{analyst:keep(a,['agentId','name','local'])});};
  list.onchange=()=>{if(list.value)change('stock',index,{list:list.value});};
  every.onchange=()=>change('stock',index,{every_minutes:Number(every.value)});
  auto.onchange=()=>change('stock',index,{enabled:auto.checked});
  drop.onclick=()=>change('stock',index,{},true);
  now.onclick=()=>runOnce('stock',rule,now);
  row.append(group('Rule',el('span','la-kind',t(KIND_NAME.stock)),'la-kindcol'),field('Analyst',who),field('List to score',list),field('Run every',every),
   field('Run automatically',auto,'la-check'),now,drop);return row;
 }
 // --- named lists: drafts stay in this view; a complete list is kept, and the rules using it are rescheduled ---
 async function changeList(index,patch,remove=false){
  const list=[...(values.named_lists||[])],before=list[index];
  if(remove)list.splice(index,1);else{list[index]={...before,...patch};for(const k of Object.keys(list[index]))if(list[index][k]===undefined)delete list[index][k];}
  values={...values,named_lists:list};
  if(remove)values.tagging_rules=(values.tagging_rules||[]).map(r=>({...r,lists:(r.lists||[]).filter(id=>id!==before.id)}));
  const changes={named_lists:list.filter(listComplete).map(clean)};if(remove)changes.tagging_rules=values.tagging_rules.filter(r=>complete('tag',r));
  // A stock rule whose list is removed waits as a draft until another list is chosen; its automatic run stops.
  if(remove)changes.stock_rules=(values.stock_rules||[]).filter(r=>complete('stock',r));
  if(!await save(changes))return false;
  for(const rule of values.tagging_rules||[])if((rule.lists||[]).includes(before.id)||remove)try{await follow('tag',rule);}catch(error){note(error.message,true);}
  for(const rule of values.stock_rules||[])if(rule.list===before.id)try{await follow('stock',rule);}catch(error){note(error.message,true);}
  renderRules();return true;
 }
 const listStatus=l=>{const c=checked[l.id];if(!c)return '';if(c.status!=='ready')return said(c.reason||'');
  return t('{0} entries',String(c.entries).replace(/\B(?=(\d{3})+(?!\d))/g,','))+(c.fetched_at?' · '+t('read {0}',fmt(c.fetched_at)):'')+((c.notes||[]).length?' — '+c.notes[0]:'');};
 async function checkList(l,button,raise=false){
  if(!TAG.test(l.name||'')){note(t('A list name is up to 30 letters, digits, spaces, dots or dashes.'),true);if(raise)throw Error(status.textContent);return null;}
  if(button)button.disabled=true;note(t('Checking…'));
  let found=null,failure=null;
  try{found=await call('analyst_list_check',{list:l});checked[l.id]=found;for(const s of found.sources||[])columns[s.url]=s.columns||[];
   note(found.status==='ready'?l.name+': '+listStatus(l):said(found.reason||''),found.status!=='ready');}
  catch(error){failure=error;note(error.message,true);}finally{if(button)button.disabled=false;}
  if(!disposed)renderRules();
  if(failure&&raise)throw failure;
  return found;
 }
 // Entries as lines; one without a code starts with a comma when it has other names, so it reads back the same.
 const lines=l=>(l.entries||[]).map(e=>(e.code?[e.code,e.name,...(e.aliases||[])]:(e.aliases||[]).length?['',e.name,...e.aliases]:[e.name]).join(', ')).join('\n');
 function parseLines(text){
  return text.split(/\n/).map(line=>line.split(/[,，、]/).map(v=>v.trim()).filter((v,i)=>i===0||v)).filter(f=>f.some(Boolean)).slice(0,MAX_STATIC)
   .map(f=>f.length===1?{code:'',name:f[0].slice(0,80),aliases:[]}:{code:f[0].slice(0,40),name:(f[1]||f[0]).slice(0,80),aliases:f.slice(2,8).map(v=>v.slice(0,80))})
   .map(e=>e.code?e:{name:e.name,aliases:e.aliases}).filter(e=>e.name);
 }
 function columnSelect(label,url,current){
  const n=el('select');n.setAttribute('aria-label',t(label));n.append(option(t('Choose…'),''));
  for(const c of [...(columns[url]||[]),...(current&&!(columns[url]||[]).includes(current)?[current]:[])])n.append(option(c,c));n.value=current||'';return n;
 }
 function sourceRow(l,index,source,si){
  const item=l.name||'A new list',row=el('div','la-rule la-source'),url=typed(el('input'),item),suffix=typed(el('input'),item);
  url.type='url';url.maxLength=500;url.placeholder='https://';url.value=source.url||'';
  suffix.type='text';suffix.maxLength=8;suffix.placeholder='.TW';suffix.value=source.suffix||'';
  const code=columnSelect('Code column',source.url,source.code),name=columnSelect('Name column',source.url,source.name);
  const other=[0,1].map(k=>columnSelect('Other names column',source.url,(source.aliases||[])[k]));
  const drop=btn('Remove source');
  const put=patch=>{const sources=[...(l.sources||[])];sources[si]={...sources[si],...patch};
   for(const k of Object.keys(sources[si]))if(sources[si][k]===''||(Array.isArray(sources[si][k])&&!sources[si][k].length))delete sources[si][k];changeList(index,{sources});};
  url.onchange=()=>put({url:url.value.trim()});suffix.onchange=()=>{if(/^[.A-Za-z0-9-]*$/.test(suffix.value))put({suffix:suffix.value});};
  code.onchange=()=>put({code:code.value});name.onchange=()=>put({name:name.value});
  for(const o of other)o.onchange=()=>put({aliases:[...new Set(other.map(x=>x.value).filter(Boolean))]});
  drop.onclick=()=>changeList(index,{sources:(l.sources||[]).filter((_,k)=>k!==si)});
  row.append(field('JSON or CSV list URL',url,'la-address'),field('Code suffix',suffix,'la-narrow'),field('Code column',code),field('Name column',name),
   ...other.map(o=>field('Other names column',o)),drop);
  if(source.url&&!(columns[source.url]||[]).length&&!source.name)row.append(el('span','la-hint',t('Choose the columns after Check.')));
  return row;
 }
 function listRow(l,index){
  const box=el('div','la-list'),row=el('div','la-rule');
  const name=typed(el('input'),l.name||'A new list');name.type='text';name.maxLength=30;name.value=l.name||'';name.placeholder='Taiwan Stock';
  const kind=el('select');kind.append(option(t('Typed in (static)'),'static'),option(t('Read from URLs (dynamic)'),'dynamic'));kind.value=l.kind||'static';
  const every=el('select');for(const [v,label] of REFRESH)every.append(option(t(label),v));every.value=String(l.refresh_hours||24);
  const status=el('span','la-hint',listStatus(l)),check=btn('Check'),edit=btn(editing.has(l.id)?'Done':'Edit'),drop=btn('Remove');
  name.onchange=()=>{if(!TAG.test(name.value.trim())){note(t('A list name is up to 30 letters, digits, spaces, dots or dashes.'),true);return;}changeList(index,{name:name.value.trim()});};
  kind.onchange=()=>changeList(index,kind.value==='dynamic'?{kind:'dynamic',entries:undefined,sources:l.sources||[{url:''}],refresh_hours:l.refresh_hours||24}:{kind:'static',sources:undefined,refresh_hours:undefined,entries:l.entries||[]});
  every.onchange=()=>changeList(index,{refresh_hours:Number(every.value)});
  check.onclick=()=>checkList(clean(l),check);
  edit.onclick=()=>{if(editing.has(l.id))editing.delete(l.id);else editing.add(l.id);renderRules();};
  drop.onclick=()=>{editing.delete(l.id);changeList(index,{},true);};
  const again=field('Read the URLs again every',every);again.hidden=l.kind!=='dynamic';
  row.append(field('List name',name),field('Members',kind),again,status,check,edit,drop);box.append(row);
  if(editing.has(l.id)){
   const editor=el('div','la-editor');
   if(l.kind==='dynamic'){
    (l.sources||[]).forEach((source,si)=>editor.append(sourceRow(l,index,source,si)));
    const more=btn('Add source');more.disabled=(l.sources||[]).length>=MAX_SOURCES;more.onclick=()=>changeList(index,{sources:[...(l.sources||[]),{url:''}]});editor.append(more);
   }else{
    const area=typed(el('textarea'),l.name||'A new list');area.rows=6;area.value=lines(l);area.placeholder='2330, 台積電, TSMC\nUSD, 美元, US dollar';
    area.onchange=()=>changeList(index,{entries:parseLines(area.value)});editor.append(field('Entries',area,'la-entries'),el('p','la-hint',t('One per line: code, name, other names. A line with one value is a name.')));
   }
   box.append(editor);
  }
  return box;
 }
 // A list as the schema takes it: no empty fields, no draft sources.
 function clean(l){const out={id:l.id,name:(l.name||'').trim(),kind:l.kind||'static'};
  if(out.kind==='static')out.entries=(l.entries||[]).slice(0,MAX_STATIC);
  else{out.refresh_hours=l.refresh_hours||24;out.sources=(l.sources||[]).filter(s=>s.url).map(s=>Object.fromEntries(Object.entries(s).filter(([,v])=>v!==''&&v!=null&&!(Array.isArray(v)&&!v.length))));}
  return out;}
 addList.onclick=()=>{const l={id:newId(),name:'',kind:'static',entries:[]};values.named_lists=[...(values.named_lists||[]),l];editing.add(l.id);renderRules();};
 presets.onchange=async()=>{const p=(choices?.presets||[]).find(x=>x.id===presets.value);presets.value='';if(!p)return;
  const taken=new Set((values.named_lists||[]).map(l=>l.name));if(taken.has(p.list.name)){note(p.list.name+' ✓');return;}
  const l={...JSON.parse(JSON.stringify(p.list)),id:newId()};values.named_lists=[...(values.named_lists||[]),l];
  await changeList(values.named_lists.length-1,{});await checkList(l);};
 function renderRules(){
  typing.clear();  // the fields drawn before are gone
  listList.replaceChildren(...(values.named_lists||[]).map(listRow));addList.disabled=(values.named_lists||[]).length>=MAX_LISTS;
  presets.replaceChildren(option(t('Add from preset…'),''),...(choices?.presets||[]).map(p=>option(p.title?.[language]||p.title?.en||p.id,p.id)));presets.hidden=!(choices?.presets||[]).length;
  const ROW={tag:tagRow,sent:sentRow,stock:stockRow};
  ruleList.replaceChildren(...ordered().map(({kind,rule,index},at)=>ROW[kind](rule,index,at+1)));
  const picked=newAnalyst.value;
  newAnalyst.replaceChildren(option(t('Choose…'),''),...(choices?.analysts||[]).map(a=>option(analystLabel(a),a.agentId)));
  newAnalyst.value=(choices?.analysts||[]).some(a=>a.agentId===picked)?picked:'';limitKind();
  const c=choices||{stores:[]},kept=values.store,listed=[...c.stores,...(kept&&!c.stores.some(s=>s.agentId===kept.agentId)?[kept]:[])];
  store.replaceChildren(option(t('Choose…'),''),...listed.map(s=>option(s.name+where(s),s.agentId)));
  store.value=kept?kept.agentId:'';
 }
 // Every rule of every kind, in the order they were added; rules kept before this view opened come first, by kind.
 function ordered(){
  const all=[];for(const kind of ['tag','sent','stock'])(values[FIELD[kind]]||[]).forEach((rule,index)=>all.push({kind,rule,index,key:kind+':'+rule.id}));
  const known=new Map(all.map(r=>[r.key,r]));
  order=[...order.filter(k=>known.has(k)),...all.map(r=>r.key).filter(k=>!order.includes(k))];
  return order.map(k=>known.get(k));
 }
 const limitKind=()=>{addRule.disabled=(values[FIELD[newKind.value]]||[]).length>=MAX_RULES[newKind.value];};
 newKind.onchange=limitKind;
 // A new rule starts with the analyst chosen beside it and is saved once the rest is chosen; until then it is a draft row.
 addRule.onclick=()=>{const kind=newKind.value,a=(choices?.analysts||[]).find(x=>x.agentId===newAnalyst.value);
  const rule={id:newId(),...(a?{analyst:keep(a,['agentId','name','local'])}:{}),...DRAFT[kind]};
  values[FIELD[kind]]=[...(values[FIELD[kind]]||[]),rule];order.push(kind+':'+rule.id);renderRules();};
 store.onchange=()=>{const s=(choices?.stores||[]).find(x=>x.agentId===store.value);if(s)save({store:keep(s,['agentId','name','local'])}).then(history);};
 function summary(kind,result){
  if(kind==='stock'){const saved=(result.batches||[]).filter(b=>b.status==='saved');
   const parts=[result.new?t('Scored {0} new items',saved.reduce((n,b)=>n+b.items,0)):t('no new news')];
   const opinions=saved.reduce((n,b)=>n+(b.opinions||0),0);if(opinions)parts.push(t('{0} opinions',opinions));
   if(result.left)parts.push(t('{0} left for the next run',result.left));if(result.points)parts.push(result.points+' '+t('points used'));
   const bad=(result.batches||[]).find(b=>b.reason);return result.list+': '+parts.join(' · ')+(bad?' — '+said(bad.reason):'');}
  if(kind==='tag'){const saved=(result.batches||[]).filter(b=>b.status==='saved').reduce((n,b)=>n+b.items,0);
   const parts=[result.new?t('Tagged {0} new items',saved):t('no new news')];if(result.left)parts.push(t('{0} left for the next run',result.left));
   const members=(result.batches||[]).reduce((n,b)=>n+(b.entities||0),0);if(members)parts.push(t('{0} list members',members));
   if(result.points)parts.push(result.points+' '+t('points used'));const bad=(result.batches||[]).find(b=>b.reason);
   return parts.join(' · ')+(bad?' — '+said(bad.reason):'')+((result.notes||[]).length?' — '+result.notes[0]:'');}
  const counts={};for(const r of result.results||[])counts[r.status]=(counts[r.status]||0)+1;
  const parts=[['saved','Saved'],['kept','kept'],['no_news','no news'],['failed','failed'],['unreadable','unreadable'],['not_saved','not saved']].filter(([k])=>counts[k]).map(([k,l])=>t(l)+' '+counts[k]);
  if(result.points)parts.push(result.points+' '+t('points used'));const bad=(result.results||[]).find(r=>r.reason);
  return result.tag+': '+parts.join(' · ')+(bad?' — '+said(bad.reason):'');
 }
 async function runOnce(kind,rule,button,raise=false){
  if(!ready(kind,rule)){note(t(kind==='tag'?'Choose an analyst, news and tags or lists, and an AssetStorage.':kind==='stock'?'Choose an analyst and a list, and an AssetStorage.':'Choose an analyst and a tag, and an AssetStorage.'),true);if(raise)throw Error(status.textContent);return null;}
  if(button)button.disabled=true;note(t('Running…'));
  try{const result=await call(OPERATION[kind],runInput(kind,rule).parameters);if(!disposed){note(summary(kind,result));await history();}return result;}
  catch(error){if(!disposed)note(error.message,true);if(raise)throw error;return null;}finally{if(button)button.disabled=false;}
 }
 const fmt=value=>{try{return new Intl.DateTimeFormat(context.locale||undefined,{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value).getTime());}catch{return String(value||'');}};
 const tone=score=>score==null?'la-none':score>=20?'la-up':score<=-20?'la-down':'la-flat';
 function renderTable(){
  // The latest tagging runs: each opens to show its items, their tags and the list members found in them.
  recent.hidden=!tagging.length&&!scored.length;
  const link=(r,text)=>{const b=el('button','la-link',text);b.type='button';b.setAttribute('aria-pressed',String(r.asset_id===selected));b.onclick=()=>open(r);return b;};
  recent.replaceChildren(...(tagging.length?[el('span','',t('Recent tagging')+':'),...tagging.slice(0,3).map(r=>link(r,fmt(r.from)+'–'+fmt(r.upto)+' · '+t('{0} items',r.items??'?')+(r.tags.length?' · '+r.tags.join(', '):'')))]:[]),
   ...(scored.length?[el('span','',t('Recent stock scoring')+':'),...scored.slice(0,3).map(r=>link(r,fmt(r.from)+'–'+fmt(r.upto)+' · '+r.list+' · '+t('{0} opinions',r.opinions??'?')))]:[]));
  if(!rows.length){table.replaceChildren(el('p','la-empty',t('No records yet. Add a tagging rule and a sentiment rule, then run them.')));return;}
  const head=el('div','la-tr la-th');for(const name of ['Period','Tag','Analyst','Score','Comment'])head.append(el('span','',t(name)));
  const body=rows.map(r=>{const line=el('button','la-tr');line.type='button';line.setAttribute('aria-pressed',String(r.asset_id===selected));
   const score=el('span','la-score '+tone(r.score),r.score==null?'—':(r.score>0?'+':'')+r.score);score.title=t(r.label||'unknown');
   line.append(el('span','',fmt(r.window_start)+(r.hours?' · '+t('{0} h',r.hours):'')),el('span','la-ticker',r.tag),el('span','la-who',r.analyst),score,el('span','la-comment',r.comment||''));
   line.onclick=()=>open(r);return line;});
  table.replaceChildren(head,...body);
 }
 async function open(row){
  selected=row.asset_id;renderTable();detail.hidden=false;detail.replaceChildren(el('p','la-status',t('Loading…')));
  try{
   const found=(await call('analyst_detail',{store:values.store,asset_id:row.asset_id})).record;
   if(disposed||selected!==row.asset_id)return;
   const close=btn('Close');close.onclick=()=>{selected='';detail.hidden=true;renderTable();};
   if(String(found.schema||'').startsWith('attas.analyst.stock-sentiments')){
    const items=found.items||[],list=el('ol','la-articles'),head=el('div','la-detail-head');
    head.append(el('strong','',t('Scored news')+' · '+(found.list||'')+' · '+(found.analyst?.name||'')+' · '+t('{0} items',items.length)),close);
    for(const a of items){const li=el('li','',[fmt(a.published_at),a.publisher,a.title].filter(Boolean).join(' · '));
     const views=(a.opinions||[]).map(o=>(o.name||o.code)+' ('+o.code+') '+(o.score>0?'+':'')+o.score+(o.confidence==null?'':' · '+o.confidence));
     li.append(el('div','la-tags',views.length?views.join(' · '):t('no view')));list.append(li);}
    detail.replaceChildren(head,list);return found;
   }
   if(String(found.schema||'').startsWith('attas.analyst.news-tags')){
    const items=found.items||[],list=el('ol','la-articles'),head=el('div','la-detail-head');
    head.append(el('strong','',t('Tagged news')+' · '+(found.analyst?.name||'')+' · '+t('{0} items',items.length)),close);
    for(const a of items){const li=el('li','',[fmt(a.published_at),a.publisher,a.title].filter(Boolean).join(' · '));
     const found2=[...(a.tags||[]),...(a.entities||[]).map(m=>m.name+(m.code&&m.code!==m.name?' ('+m.code+')':''))];
     li.append(el('div','la-tags',found2.length?found2.join(' · '):t('(none)')));list.append(li);}
    detail.replaceChildren(head,list);return found;
   }
   const head=el('div','la-detail-head');head.append(el('strong','',found.tag+' · '+fmt(found.window.start)+' – '+fmt(found.window.end)),close);
   const sentiment=found.sentiment||{},list=el('ol','la-articles');
   for(const a of found.items||[])list.append(el('li','',[fmt(a.published_at),a.publisher,a.title].filter(Boolean).join(' · ')));
   detail.replaceChildren(head,el('p','la-meta',[found.analyst?.name,t(sentiment.label||'unknown'),sentiment.score==null?'—':String(sentiment.score)].filter(Boolean).join(' · ')),
    el('p','la-body',found.comment||''),el('h4','',t('Articles')+' ('+(found.items||[]).length+')'),list);
   return found;
  }catch(error){if(!disposed)detail.replaceChildren(el('p','la-status la-error',error.message));return null;}
 }
 async function history(){
  if(!values.store){rows=[];tagging=[];scored=[];renderTable();return;}
  try{const found=await call('analyst_history',{store:values.store,limit:50});rows=found.rows||[];tagging=found.tagging||[];scored=found.stock||[];}
  catch(error){note(error.message,true);}
  if(!disposed)renderTable();
 }
 refresh.onclick=()=>history();
 async function start(){
  try{const saved=typeof bridge.parameters==='function'?(await bridge.parameters())?.values||{}:context.parameters||{};
   outdated=!('tagging_rules' in saved)&&('tickers' in saved||'analysts' in saved);
   values={named_lists:Array.isArray(saved.named_lists)?saved.named_lists:[],tagging_rules:Array.isArray(saved.tagging_rules)?saved.tagging_rules:[],
    sentiment_rules:Array.isArray(saved.sentiment_rules)?saved.sentiment_rules:[],stock_rules:Array.isArray(saved.stock_rules)?saved.stock_rules:[],
    ...(saved.store?{store:saved.store}:{})};}
  catch{values={named_lists:[],tagging_rules:[],sentiment_rules:[],stock_rules:[]};}
  if(outdated)note(t('This Analyst Sentiment is an older copy without rules. In New Data Browser, select Analyst Sentiment, click 更新 and open a new one.'),true);
  rulesPanel.hidden=values.sentiment_rules.length>0||values.stock_rules.length>0;renderRules();renderTable();if(!outdated)note(t('Loading…'));
  try{choices=await call('analyst_choices',{});if(!outdated)note('');}catch(error){choices={analysts:[],news:[],stores:[],failed:true};note(error.message,true);}
  if(disposed)return;
  if(!choices.failed&&!outdated){const missing=[!choices.analysts.length&&'No analyst is available to this Terminal.',!choices.news.length&&'No news source offers a news feed.',
   !choices.stores.length&&'No AssetStorage is available. Install Local AssetStorage in Retis MAS Manager, or use the site\'s.'].filter(Boolean);
   if(missing.length)note(missing.map(m=>t(m)).join(' '),true);}
  if(typeof bridge.runs==='function'){try{runs=((await bridge.runs())?.runs||[]).filter(r=>/^(tag|sent|stock)-/.test(r.key||''));}catch{runs=[];}}
  renderRules();await history();
 }
 const starting=start();
 // --- What an AI app may ask (release.py VIEW_ACTIONS) ----------------------------------------------------------------
 // Each action takes the steps a click takes, through the same functions, so the window shows the outcome and the
 // Terminal keeps the rules as it always does. Items are named as people name them: a list by its name; an analyst, news
 // source or AssetStorage by the name the window shows; a rule by its number in the list of rules. Not offered: Remove,
 // Run automatically (it schedules runs that spend points), and changes to a rule that runs automatically.
 // Undo (the Terminal's, `undo` in an edit's answer): the lists, rules and AssetStorage live only in the window's
 // parameter values, which start() reads back as they are ('parameters'); set_store gives its inverse instead.
 const KIND_OF={tagging:'tag',sentiment:'sent',stock:'stock'},KIND_WORD={tag:'tagging',sent:'sentiment',stock:'stock'};
 const fail=text=>new Error(text),quoted=text=>'“'+text+'”';
 const same=(a,b)=>String(a??'').trim().toLowerCase()===String(b??'').trim().toLowerCase();
 const brief=(text,most=240)=>{const s=String(text??'');return s.length>most?s.slice(0,most-1)+'…':s;};
 function named(list,name,what,labels=x=>[x.name]){
  const exact=list.filter(x=>labels(x).includes(name)),found=exact.length?exact:list.filter(x=>labels(x).some(label=>same(label,name)));
  if(!found.length)throw fail('There is no '+what+' named '+quoted(name)+'. describe lists them.');
  if(found.length>1)throw fail('More than one '+what+' is named '+quoted(name)+'.');
  return found[0];
 }
 const analystNamed=name=>keep(named(choices?.analysts||[],name,'analyst',a=>[a.name||a.agentId]),['agentId','name','local']);
 const presetLabels=p=>[p.title?.en,p.title?.zh,p.id].filter(Boolean);
 function ruleAt(number){const found=ordered()[number-1];if(!found)throw fail('There is no rule '+number+'. describe lists the rules.');return found;}
 const automatic=(kind,rule)=>!!rule.enabled||runs.some(r=>r.key===runKey(kind,rule)&&r.status!=='stopped');
 const AUTOMATIC=' Untick Run automatically in the window first.';
 function writable(){
  if(outdated)throw fail(t('This Analyst Sentiment is an older copy without rules. In New Data Browser, select Analyst Sentiment, click 更新 and open a new one.'));
  for(const item of typing.values())throw fail(quoted(item)+' is being edited in the window.');
 }
 const unsaved=()=>fail(status.textContent||'The change could not be saved.');
 const kept=id=>(values.named_lists||[]).find(l=>l.id===id);
 function ruleFacts(kind,rule,number){
  const facts={number,kind:KIND_WORD[kind],analyst:rule.analyst?.name||rule.analyst?.agentId||null,automatic:automatic(kind,rule),complete:complete(kind,rule)};
  if(kind==='tag')return {...facts,news:rule.news?.name||null,tags:[...(rule.tags||[])],lists:usedLists(rule).map(l=>l.name),every_minutes:rule.every_minutes||60};
  if(kind==='sent')return {...facts,tag:rule.tag||null,period_hours:rule.period_hours||6};
  return {...facts,list:stockList2(rule)[0]?.name||null,every_minutes:rule.every_minutes||60};
 }
 function listFacts(l){
  const c=checked[l.id],facts={name:l.name||'',kind:l.kind||'static',complete:listComplete(l)};
  if(facts.kind==='dynamic')Object.assign(facts,{refresh_hours:l.refresh_hours||24,sources:clean(l).sources||[]});
  else facts.entries=(l.entries||[]).length;
  if(c)facts.checked=c.status==='ready'?{entries:c.entries,...(c.fetched_at?{read_at:c.fetched_at}:{}),...((c.sources||[]).length?{columns:Object.fromEntries(c.sources.map(s=>[s.url,s.columns||[]]))}:{})}:{problem:said(c.reason||'')};
  return facts;
 }
 const entriesOf=list=>list.map(e=>{const name=String(e.name).trim().slice(0,80),aliases=(e.aliases||[]).map(a=>String(a).trim().slice(0,80)).filter(Boolean).slice(0,6),code=String(e.code||'').trim().slice(0,40);
  return code?{code,name,aliases}:{name,aliases};}).filter(e=>e.name);
 const sourcesOf=list=>list.map(s=>Object.fromEntries(Object.entries({url:String(s.url).trim(),name:s.name,code:s.code,aliases:s.aliases,suffix:s.suffix})
  .filter(([,v])=>v!==undefined&&v!==''&&!(Array.isArray(v)&&!v.length))));
 function checkName(name,except){
  if(!TAG.test(name))throw fail(t('A list name is up to 30 letters, digits, spaces, dots or dashes.'));
  if((values.named_lists||[]).some(l=>l!==except&&same(l.name,name)))throw fail('A list named '+quoted(name)+' is already kept.');
 }
 /** A rule's settings from the names an AI app gives, as the rule's menus take them. */
 function ruleFields(kind,given,rule){
  const allowed={tag:['analyst','news','tags','lists','every_minutes'],sent:['analyst','tag','period_hours'],stock:['analyst','list','every_minutes']}[kind];
  const wrong=Object.keys(given).filter(key=>given[key]!==undefined&&!allowed.includes(key));
  if(wrong.length)throw fail('A '+KIND_WORD[kind]+' rule has no '+wrong.join(', ')+'.');
  const out={};
  if(given.analyst!==undefined)out.analyst=analystNamed(given.analyst);
  if(given.news!==undefined)out.news=keep(named(choices?.news||[],given.news,'news source'),['agentId','name','local','modelRef']);
  if(given.tags!==undefined){const list=[...new Set(given.tags.map(s=>String(s).trim()).filter(Boolean))];
   if(list.length>MAX_TAGS||list.some(s=>!TAG.test(s)))throw fail(t('Tags are 1 to 12 words of up to 30 letters, digits, spaces, dots or dashes.'));out.tags=list;}
  if(given.lists!==undefined){const chosen=given.lists.map(name=>named(keptLists(),name,'named list').id);
   if(new Set(chosen).size>MAX_RULE_LISTS)throw fail('A rule uses up to '+MAX_RULE_LISTS+' lists.');out.lists=keptLists().filter(l=>chosen.includes(l.id)).map(l=>l.id);}
  if(given.every_minutes!==undefined){if(!EVERY.some(([v])=>v===given.every_minutes))throw fail('Choose every_minutes from '+EVERY.map(([v])=>v).join(', ')+'.');out.every_minutes=given.every_minutes;}
  if(given.tag!==undefined){const offered=tagsOffered(),found=offered.find(x=>x===given.tag)||offered.find(x=>same(x,given.tag))||(rule&&same(rule.tag,given.tag)?rule.tag:null);
   if(!found)throw fail(quoted(given.tag)+' is not one of the tagging rules\' tags or lists. describe lists them.');out.tag=found;}
  if(given.period_hours!==undefined){if(!PERIODS.includes(given.period_hours))throw fail('Choose period_hours from '+PERIODS.join(', ')+'.');out.period_hours=given.period_hours;}
  if(given.list!==undefined)out.list=named(keptLists(),given.list,'named list').id;
  return out;
 }
 const MISSING={tag:'A tagging rule needs its news, and tags or lists.',sent:'A sentiment rule needs its tag.',stock:'A stock rule needs its list.'};
 const actions={
  async describe(){
   await starting;
   return {store:values.store?.name||null,
    named_lists:(values.named_lists||[]).map(listFacts),
    rules:ordered().map(({kind,rule},at)=>ruleFacts(kind,rule,at+1)),
    records:rows.slice(0,10).map(r=>({period:r.window_start,hours:r.hours??null,tag:r.tag,analyst:r.analyst||null,score:r.score??null,label:r.label||null,comment:brief(r.comment)})),
    recent_tagging:tagging.slice(0,3).map(r=>({from:r.from,upto:r.upto,items:r.items??null,tags:[...(r.tags||[])]})),
    recent_stock_scoring:scored.slice(0,3).map(r=>({from:r.from,upto:r.upto,list:r.list,opinions:r.opinions??null})),
    choices:{analysts:(choices?.analysts||[]).map(a=>({name:a.name||a.agentId,on_this_computer:!!a.local})),news:(choices?.news||[]).map(s=>s.name),
     stores:(choices?.stores||[]).map(s=>s.name),presets:(choices?.presets||[]).map(p=>p.title?.[language]||p.title?.en||p.id)},
    ...(outdated?{note:t('This Analyst Sentiment is an older copy without rules. In New Data Browser, select Analyst Sentiment, click 更新 and open a new one.')}:{})};
  },
  async show_record({tag,period}){
   await starting;
   const at=Date.parse(period),row=rows.find(r=>same(r.tag,tag)&&(r.window_start===period||Number.isFinite(at)&&Date.parse(r.window_start)===at));
   if(!row)throw fail('No record of '+quoted(tag)+' for '+period+' is listed. describe lists the latest records.');
   const found=await open(row);
   if(!found)throw fail(detail.textContent||'That record could not be read.');
   const sentiment=found.sentiment||{};
   return {tag:found.tag||row.tag,period:found.window?.start||row.window_start,hours:found.window?.hours??row.hours??null,analyst:found.analyst?.name||row.analyst||null,
    score:sentiment.score??null,label:sentiment.label||null,comment:brief(found.comment,2000),articles:(found.items||[]).length,
    titles:(found.items||[]).slice(0,10).map(a=>a.title)};
  },
  async set_store({store:name}){
   await starting;if(outdated)writable();
   const found=named(choices?.stores||[],name,'AssetStorage');
   // Undo: set_store again with the AssetStorage chosen before, while the menu lists it by that one name; with none
   // chosen before, or one no longer listed, the window's earlier parameter values.
   const earlier=values.store,again=earlier?.name&&String(earlier.name).length<=120?(choices?.stores||[]).filter(s=>s.name===earlier.name):[];
   const undo=again.length===1&&again[0].agentId===earlier.agentId?{action:'set_store',input:{store:earlier.name}}:'parameters';
   if(!await save({store:keep(found,['agentId','name','local'])}))throw unsaved();
   store.value=found.agentId;await history();
   return {store:found.name,records:rows.length,undo};
  },
  async add_list({preset,name,entries,sources,refresh_hours}){
   await starting;writable();
   if((values.named_lists||[]).length>=MAX_LISTS)throw fail('Keep up to '+MAX_LISTS+' named lists.');
   if(preset!==undefined){
    if([name,entries,sources,refresh_hours].some(v=>v!==undefined))throw fail('Give a preset alone, or a list of your own without one.');
    const p=named(choices?.presets||[],preset,'preset',presetLabels);checkName(p.list.name);
    // As Add from preset does: the preset's list is kept, then checked.
    const l={...JSON.parse(JSON.stringify(p.list)),id:newId()};values.named_lists=[...(values.named_lists||[]),l];
    if(!await changeList(values.named_lists.length-1,{}))throw unsaved();
    await checkList(clean(kept(l.id)));
    return {list:listFacts(kept(l.id)),undo:'parameters'};
   }
   if(name===undefined)throw fail('Name the list.');
   if(!entries===!sources)throw fail('Give a static list its entries, or a dynamic list its sources.');
   if(entries&&refresh_hours!==undefined)throw fail('refresh_hours is for a list read from URLs.');
   checkName(name);
   // As Add list does, then its name, its kind and its entries or sources.
   const l={id:newId(),name:'',kind:'static',entries:[]};values.named_lists=[...(values.named_lists||[]),l];editing.add(l.id);
   const patch=entries?{name,entries:entriesOf(entries)}:{name,kind:'dynamic',entries:undefined,sources:sourcesOf(sources),refresh_hours:refresh_hours||24};
   if(!await changeList(values.named_lists.length-1,patch))throw unsaved();
   if(sources)await checkList(clean(kept(l.id)));
   return {list:listFacts(kept(l.id)),undo:'parameters'};
  },
  async set_list({list,name,entries,sources,refresh_hours}){
   await starting;writable();
   const found=named(values.named_lists||[],list,'named list'),index=values.named_lists.indexOf(found);
   if(entries&&found.kind==='dynamic')throw fail(quoted(found.name)+' is read from URLs; give it sources.');
   if((sources||refresh_hours!==undefined)&&found.kind!=='dynamic')throw fail(quoted(found.name)+' is typed in; give it entries.');
   if(name!==undefined)checkName(name,found);
   const using=[...(values.tagging_rules||[]).filter(r=>(r.lists||[]).includes(found.id)).map(r=>['tag',r]),...(values.stock_rules||[]).filter(r=>r.list===found.id).map(r=>['stock',r])];
   if(using.some(([kind,rule])=>automatic(kind,rule)))throw fail(quoted(found.name)+' is used by a rule that runs automatically.'+AUTOMATIC);
   const patch={...(name!==undefined?{name}:{}),...(entries?{entries:entriesOf(entries)}:{}),...(sources?{sources:sourcesOf(sources)}:{}),...(refresh_hours!==undefined?{refresh_hours}:{})};
   if(!await changeList(index,patch))throw unsaved();
   if(sources)await checkList(clean(kept(found.id)));
   return {list:listFacts(kept(found.id)),undo:'parameters'};
  },
  async check_list({list}){
   await starting;writable();
   const found=named(values.named_lists||[],list,'named list');
   await checkList(clean(found),null,true);
   return {list:listFacts(kept(found.id))};
  },
  async add_rule({kind:word,...given}){
   await starting;writable();
   const kind=KIND_OF[word];if(!kind)throw fail('Choose a tagging, sentiment or stock rule.');
   if((values[FIELD[kind]]||[]).length>=MAX_RULES[kind])throw fail('Keep up to '+MAX_RULES[kind]+' '+word+' rules.');
   const fields=ruleFields(kind,given,null);
   if(!complete(kind,{...DRAFT[kind],...fields}))throw fail(MISSING[kind]);
   // As Add rule does with the analyst chosen beside it, then the rule's own menus.
   const rule={id:newId(),analyst:fields.analyst,...DRAFT[kind]};
   values[FIELD[kind]]=[...(values[FIELD[kind]]||[]),rule];order.push(kind+':'+rule.id);
   const index=values[FIELD[kind]].length-1;
   if(!await change(kind,index,fields))throw unsaved();
   const number=ordered().findIndex(r=>r.key===kind+':'+rule.id)+1;
   return {rule:ruleFacts(kind,values[FIELD[kind]][index],number),undo:'parameters'};
  },
  async set_rule({rule:number,...given}){
   await starting;writable();
   const {kind,rule,index}=ruleAt(number);
   if(automatic(kind,rule))throw fail('Rule '+number+' runs automatically.'+AUTOMATIC);
   const fields=ruleFields(kind,given,rule);
   if(!Object.keys(fields).length)throw fail('Name at least one setting to change.');
   // A kept rule that lost its news, tags or list would no longer be kept.
   if(complete(kind,rule)&&!complete(kind,{...rule,...fields}))throw fail(MISSING[kind]);
   if(!await change(kind,index,fields))throw unsaved();
   return {rule:ruleFacts(kind,values[FIELD[kind]][index],number),undo:'parameters'};
  },
  async run_rule({rule:number}){
   await starting;if(outdated)writable();
   const {kind,rule}=ruleAt(number);
   const result=await runOnce(kind,rule,null,true);
   return {rule:number,kind:KIND_WORD[kind],summary:summary(kind,result),points:result.points||0};
  },
 };
 // An older Terminal's view host has no `actions`; the view works as before.
 try{for(const [name,fn] of Object.entries(actions))bridge.actions?.handle?.(name,fn);}catch{}
 return stop;
}
globalThis.LocalAnalystView=Object.freeze({mount});
const bridge=globalThis.phemacastAgentView;
if(bridge&&typeof document!=='undefined'){const root=document.querySelector('#local-analyst');if(root)globalThis.disposeLocalAnalyst=mount(root,bridge);}
})();
