/** Generic owner-declared selection dialog over every Phema storage. Search and resolution stay with each storage. */
import {validateUIBundle,resolveUIMessage} from "./phema-i18n.js";
import {createOwnerBusy} from './owner-busy.js';
import {displayDateTime} from './time-display.js';
import {TERMINAL_STORAGE as TERMINAL} from './phema-storages.js';
// A Phema's panels and their places on its grid, as the chooser's diagram draws them.
export function layoutOutline(phema){
 try{
  const layout=composition(phema).presentation?.document?.design?.layout||{},columns=Number(layout.columns)||12;
  return {columns,panels:(Array.isArray(layout.children)?layout.children:[]).slice(0,64).map((node,index)=>{const p=node?.position||{};
   return {label:String(node?.title||node?.label||'Panel '+(index+1)).slice(0,200),column:Number(p.column)||1,row:Number(p.row)||index+1,
    columnSpan:Number(p.columnSpan)||columns,rowSpan:Number(p.rowSpan)||1};})};
 }catch{return {columns:12,panels:[]};}
}
const composition = phema => {
 const parts=phema?.sections?.flatMap(s=>s.content||[]).filter(n=>n.type==='phemacast:composition');
 if(parts?.length!==1)throw Error('A resolved selection Phema is required.');
 return parts[0];
};
const el=(tag,text='',className='')=>{const node=document.createElement(tag);node.textContent=text;node.className=className;return node;};
// A saved value on one line: a list joined with commas, an object's own entries as "name value".
const shown=value=>Array.isArray(value)?value.map(shown).join(', '):value&&typeof value==='object'?Object.entries(value).map(([k,v])=>k+' '+shown(v)).join(', '):String(value??'');
// What to ask the owner for when opening a snapshot: the values its Phema was opened with, so the owner returns the
// definition the snapshot was saved from. Its `parameters` also hold what the views kept on top (a tab, a chart
// range); the owner would bind those into another definition, and the Terminal would refuse the snapshot as
// another revision. A snapshot saved before it kept them apart opens with the values the open
// form asks for, as parameter mode does: the owner fills the others from their defaults.
export function openedWith(snapshot,schema){
 if(snapshot.phemaParameters&&typeof snapshot.phemaParameters==='object'&&!Array.isArray(snapshot.phemaParameters))return snapshot.phemaParameters;
 const saved=snapshot.parameters||{},properties=schema?.properties||{};
 return Object.fromEntries(Object.entries(saved).filter(([key])=>Object.hasOwn(properties,key)&&properties[key]?.readOnly!==true));
}
const effects=['writesState','externalSend','paidExecution','startsJob','opensStream'];
const readonly=ref=>ref?.kind==='pulse'&&ref.refresh?.trigger==='manual'&&ref.extensions?.['phemacast:operation-binding']&&
 effects.every(k=>ref.extensions?.['phemacast:operation-effects']?.[k]===false)&&Object.keys(ref.extensions['phemacast:operation-effects']).length===effects.length;

async function protectedSession({phema,request,toEntry,workspaceId}){
 const refs=composition(phema).references;
 if(!refs?.length||refs.some(ref=>!readonly(ref)))throw Error('Selection requires protected, effect-free owner reads.');
 const mount=await request('/api/instances',{method:'POST',body:{entry:toEntry(phema),command:'CONTENT',sourceMode:'parameters',workspaceId}});
 if(!mount?.id)throw Error('Selection mount returned no identity.');
 const path='/api/instances/'+encodeURIComponent(mount.id),capability=mount.content?.transportCapability;
 let closed=false,heartbeat;
 const close=async()=>{if(!closed){closed=true;clearInterval(heartbeat);await request(path,{method:'DELETE'});}};
 if(capability?.id!=='phemacast:neutral-operation-form'||!['1.0.0','1.1.0'].includes(capability.version)){
  await close();throw Error('Protected selection transport is unavailable.');
 }
 heartbeat=setInterval(()=>{if(!closed)request(path).catch(()=>{});},30000);
 return {close,async read(reference,inputs){
  if(closed)throw Error('Selection dialog is closed.');
  if(!refs.some(r=>r.id===reference))throw Error('Undeclared selection reference.');
  const intent=crypto.randomUUID().replaceAll('-','');
  const prepared=await request(path+'/content',{method:'POST',body:{operation:'prepare-interaction',references:[reference],inputs,requestKey:intent}});
  if(prepared.intentId!==intent||prepared.state!=='prepared'||!/^[a-f0-9]{64}$/.test(prepared.wireDigest))throw Error('Selection preparation could not be verified.');
  const result=await request(path+'/content',{method:'POST',body:{operation:'invoke-interaction',references:[reference],requestKey:intent,wireDigest:prepared.wireDigest}});
  if(result.intentId!==intent||result.wireDigest!==prepared.wireDigest)throw Error('Selection result could not be verified.');
  // The owner refused or the call did not finish: say so in the viewer's language, with the owner's reason when it gave one.
  if(result.state!=='complete'){const reason=typeof result.refusal==='string'&&result.refusal.trim()?result.refusal.trim():null;
   const uiKey=reason?'The layout owner could not open it: {0}':'The layout could not be opened. Try again.';
   throw Object.assign(Error(reason?'The layout owner could not open it: '+reason:uiKey),{uiKey,uiArgs:reason?[reason]:[]});}
  return result.value;
 }};
}

/** The starter workspace an owner publishes in its catalog (phemacast.core.starter_workspace): the one Phema with
 * the identity `getting-started` carries `phemacast:starter-workspace`, a name and the catalog keys to open in
 * order. Each is opened with no parameters through the owner's own selection, as Open in New Data Browser would.
 * Returns null when the owner publishes none; nothing here chooses what a workspace holds. */
export const STARTER_PHEMA='getting-started';
export async function readStarterWorkspace({phema,request,toEntry,workspaceId,locale='en',limit=12,onProgress=()=>{}}){
 const entry=composition(phema).extensions?.['phemacast:selector-entry'];
 if(entry?.version!=='1.0.0'||!entry.phema)throw Error('The owner has not declared a Phema selector.');
 toEntry(entry.phema);
 const picker=composition(entry.phema).extensions?.['phemacast:selection'];
 if(picker?.version!=='1.0.0'||!picker.catalogReference||!picker.openReference)throw Error('The owner selection definition is invalid.');
 const session=await protectedSession({phema:entry.phema,request,toEntry,workspaceId});
 try{
  const catalog=await session.read(picker.catalogReference,{query:''});
  if(catalog?.schema!=='phemacast:selection-catalog/1'||!Array.isArray(catalog.items)||catalog.items.length>200)throw Error('The owner returned an invalid Phema list.');
  const open=async item=>{
   const value=await session.read(picker.openReference,{key:item.key,revision:item.revision,source_mode:'parameters',parameters:{}});
   if(!value?.phema||value.resolved!==true||value.source_mode!=='parameters')throw Error('The owner did not return a resolved Phema.');
   toEntry(value.phema);return value.phema;
  };
  const starters=catalog.items.filter(item=>item?.phemaId===STARTER_PHEMA&&item.available===true);
  if(starters.length!==1)return null;
  const document=await open(starters[0]),starter=composition(document).extensions?.['phemacast:starter-workspace'];
  if(starter?.version!=='1.0.0'||typeof starter.name!=='string'||!starter.name.trim()||!Array.isArray(starter.items)||
     !starter.items.length||starter.items.length>12||starter.items.some(item=>typeof item?.key!=='string'))
   throw Error('The starter workspace definition is invalid.');
  // The starter's name in the viewer's language, from the starter document's own messages.
  const bundles=[composition(document).presentation?.document?.extensions?.['phemacast:ui'],starters[0].extensions?.['phemacast:ui']]
   .map(bundle=>{try{return bundle?validateUIBundle(bundle):null;}catch{return null;}});
  const name=resolveUIMessage(bundles,locale,starter.name,(_locale,key)=>key).trim().slice(0,60);
  const phemas=[],skipped=[],listed=starter.items.slice(0,limit);
  for(const [index,{key}] of listed.entries()){
   const item=catalog.items.find(row=>row?.key===key);
   // An entry this account cannot open stays out; the others still open.
   if(!item?.available){skipped.push(key);continue;}
   // Each read is one call to the owner, one after another: the window says which one it waits for.
   try{onProgress({name,index:index+1,total:listed.length});}catch{}
   try{phemas.push(await open(item));}catch(error){skipped.push(key);console.warn('Starter workspace:',key,error.message);}
  }
  return {name,phemas,skipped};
 }finally{await session.close().catch(error=>console.error('Starter workspace cleanup:',error.message));}
}

// A storage that has not answered after this long gets a note; its results join the list whenever they arrive.
const SLOW_MS=8000;
// An owner's selector entry: its `phemacast:selection` definition, its UI messages and a protected session for its reads.
async function ownerLibrary({phema,request,toEntry,workspaceId}){
 const entry=composition(phema).extensions?.['phemacast:selector-entry'];
 if(entry?.version!=='1.0.0'||!entry.phema)throw Error('The owner has not declared a Phema selector.');
 toEntry(entry.phema);
 const picker=composition(entry.phema).extensions?.['phemacast:selection'];
 if(picker?.version!=='1.0.0'||!picker.catalogReference||!picker.openReference)throw Error('The owner selection definition is invalid.');
 const declared=composition(entry.phema).presentation?.document?.extensions?.['phemacast:ui'];
 const ui=declared?validateUIBundle(declared):null;
 return {picker,ui,session:await protectedSession({phema:entry.phema,request,toEntry,workspaceId})};
}

// The agent libraries this account may use now, as the dialog's storage list names them (not this Terminal's own).
async function librariesOf(storages){
 if(typeof storages!=='function')return [];
 const found=await Promise.resolve().then(storages);
 return (Array.isArray(found)?found:[]).filter(row=>row?.id&&row.id!==TERMINAL&&typeof row.selector==='function'&&typeof row.name==='string');
}

/** One search over every place Phemas are stored: this Terminal's own store (`/api/kept-phemas`) and each agent
 * library `storages()` discovers. Each storage has a checkbox; the merged list labels each result with its storage.
 * `preference` keeps the storages left out and the Arrange windows choice in the Terminal's store
 * ({get()→{excluded,arrange}|null, set(value)}). */
// The libraries' default lists (an empty search) as last shown, so the dialog opens on them while each library is asked
// again. A hint only: nothing opens from it, and each library's answer replaces it.
const CACHE_VERSION=1,CACHE_LIMIT=1_500_000;
function readListCache(cache){
 try{
  const value=JSON.parse(cache?.read?.()||'null');
  if(value?.version!==CACHE_VERSION||!Array.isArray(value.storages)||value.storages.length>50)return [];
  return value.storages.filter(row=>typeof row?.id==='string'&&row.id.startsWith('agent:')&&typeof row.name==='string'&&
   Array.isArray(row.items)&&row.items.length<=200&&row.items.every(item=>typeof item?.key==='string'&&typeof item.name==='string'))
   .map(row=>({id:row.id,name:row.name.slice(0,150),ui:row.ui?validateUIBundle(row.ui):null,items:row.items}));
 }catch{return [];}
}

export function installPhemaSelector({request,toEntry,workspaceId,text=x=>x,onOpen,previews=null,trustOwner=null,storages:discover=null,preference=null,cache=null}){
 let active;
 return {
 /** For an AI app (mcp_access.py search_phemas, open_phema): the Phemas each agent library lists for `query`, by
  * name and library name as the dialog shows them, without the dialog. A library that can't be asked is left out and
  * named in `unanswered`. Each library's session closes when its answer is in. */
 async searchLibraries({query='',storages=discover}={}){
  const found=[],unanswered=[];
  for(const storage of await librariesOf(storages)){
   let setup=null;
   try{
    setup=await ownerLibrary({phema:await storage.selector(),request,toEntry,workspaceId:workspaceId()});
    const value=await setup.session.read(setup.picker.catalogReference,{query:String(query||'').slice(0,499)});
    if(value?.schema!=='phemacast:selection-catalog/1'||!Array.isArray(value.items))throw Error('The owner returned an invalid Phema list.');
    for(const item of value.items.slice(0,200))if(typeof item?.key==='string'&&typeof item.name==='string'&&item.available!==false)
     found.push({name:item.name,description:typeof item.description==='string'?item.description:'',library:storage.name,storage:storage.id,key:item.key});
   }catch{unanswered.push(storage.name);}
   finally{setup?.session.close().catch(()=>{});}
  }
  return {found,unanswered};
 },
 /** Open a library's Phema by its name (and library, when several have one so named), as the dialog's Open does with
  * its parameters: the owner resolves it, and the window opens it where `onOpen` puts a new window. */
 async openFromLibrary({name,library=null,storages=discover,options={}}){
  const wanted=String(name||'').trim().toLowerCase(),inLibrary=library?String(library).trim().toLowerCase():null;
  const {found}=await this.searchLibraries({query:name,storages});
  const matches=found.filter(item=>item.name.trim().toLowerCase()===wanted&&(!inLibrary||item.library.trim().toLowerCase()===inLibrary));
  if(!matches.length)return null;
  if(matches.length>1)throw Error('Several libraries have a Phema named '+name+': '+matches.map(item=>item.library).join(', ')+'. Name the library.');
  const item=matches[0],storage=(await librariesOf(storages)).find(row=>row.id===item.storage);
  if(!storage)throw Error('That library is not available now; search again.');
  const setup=await ownerLibrary({phema:await storage.selector(),request,toEntry,workspaceId:workspaceId()});
  try{
   const listed=await setup.session.read(setup.picker.catalogReference,{query:item.name});
   const entry=(listed?.items||[]).find(row=>row?.key===item.key);
   if(!entry)throw Error('That Phema is no longer in its library; search again.');
   const value=await setup.session.read(setup.picker.openReference,{key:entry.key,revision:entry.revision,source_mode:'parameters',parameters:{}});
   if(!value?.phema||value.resolved!==true||value.source_mode!=='parameters')throw Error('The owner did not return a resolved Phema.');
   toEntry(value.phema);
   await onOpen({phema:value.phema,sourceMode:'parameters',target:'new',selectionKey:entry.key,...options});
   return {name:item.name,library:item.library};
  }finally{setup.session.close().catch(()=>{});}
 },
 /** Phemas kept in this Terminal, when no agent library can be asked. Opens only when there are some. */
 async openSaved(options={}){
  let kept=[];try{const value=await request('/api/kept-phemas');kept=Array.isArray(value?.phemas)?value.phemas:[];}catch{kept=[];}
  return kept.length?this.open({...options,phema:null,storages:null}):null;
 },
 /** `phema`, an owner's resolved Phema that declares a selector, searches that one library (named `name`);
  * otherwise `storages` (by default the discovery given at install) lists the agent libraries. `pick`, when given,
  * makes the dialog choose a Phema instead of opening it: the chosen one goes to pick({name, key, storage, phemaId,
  * preview, picture}), with the last screenshot this Terminal saved of it as a data: URL when there is one. */
 open({phema=null,name=null,storages=discover,target:initialTarget='new',current=null,pick=null}={}){
  if(active){active.search.focus();return active.dialog;}
  if(phema)composition(phema);
  const lang=()=>document.documentElement.lang||'en';
  const itemUI=new WeakMap(),storageOf=new WeakMap(),states=[];
  // An item's own messages, then its storage's, then the other storages' and the Terminal's own.
  const bundles=item=>{const own=storageOf.get(item)?.ui||null;return [itemUI.get(item)||null,own,...states.map(s=>s.ui).filter(b=>b&&b!==own)];};
  const say=(key,item,args=[])=>resolveUIMessage(bundles(item),lang(),key,(_locale,key)=>text(key)).replace(/\{(\d+)\}/g,(match,i)=>args[i]??match);
  const put=(node,key,item,args=[])=>{node.textContent=say(key,item,args);node.dataset.uiKey=key;node.dataset.uiArgs=JSON.stringify(args);return node;};
  const label=(tag,key,className='',item,args=[])=>put(el(tag,'',className),key,item,args);
  const attribute=(node,name,key,item)=>{node.setAttribute(name,say(key,item));node.setAttribute('data-ui-attr-'+name,JSON.stringify({key,args:[]}));};
  const scoped=(node,bundle)=>{if(bundle)node.dataset.phemaUi=JSON.stringify(bundle);else delete node.dataset.phemaUi;};
  const dialog=el('dialog','','phema-selector');attribute(dialog,'aria-label','Phema layouts');
  const busy=createOwnerBusy(dialog,{label:()=>say('Loading Phemas…')});
  const header=el('header'),heading=label('strong',pick?'Choose a Phema to copy':'Phema layouts'),dismiss=el('button','×');
  dismiss.type='button';attribute(dismiss,'aria-label','Close dialog');header.append(heading,dismiss);
  const searchForm=el('form','','ps-search'),search=el('input'),find=label('button','Search'),refresh=el('button','↻');
  search.type='search';attribute(search,'placeholder','Search Phemas');attribute(search,'aria-label','Search Phemas');search.maxLength=499;
  find.type='submit';refresh.type='button';attribute(refresh,'aria-label','Refresh Phema list');
  const remembered=preference?.get?.()||{},excluded=new Set(Array.isArray(remembered.excluded)?remembered.excluded:[]);
  // When this window opened each Phema from here (newest 100), for sorting by Last opened.
  const opened=new Map((Array.isArray(remembered.opened)?remembered.opened:[]).filter(row=>typeof row?.storage==='string'&&typeof row.key==='string'&&Number.isFinite(row.at))
   .map(row=>[row.storage+'\n'+row.key,row]));
  // Where to search: one checkbox per storage, kept as this window's preference.
  const storageBar=el('div','','ps-storages');storageBar.setAttribute('role','group');attribute(storageBar,'aria-label','Search in');storageBar.append(label('span','Search in','ps-storages-label'));
  // The list's order: the Phemas this window opened most recently first and the others in each storage's own order,
  // or by name in the window's language.
  const sortField=el('label','','ps-sort'),sort=el('select');attribute(sort,'aria-label','Sort by');
  for(const [key,value] of [['Last opened','opened'],['Name','name']]){const option=label('option',key);option.value=value;sort.append(option);}
  sort.value=remembered.sort==='name'?'name':'opened';sortField.append(label('span','Sort by'),sort);
  searchForm.append(search,find,refresh,storageBar,sortField);
  const status=el('p','','ps-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const notes=el('p','','ps-storage-notes'),statusRow=el('div','','ps-status-row');notes.hidden=true;statusRow.append(status,notes);
  const body=el('div','','ps-columns'),catalog=el('aside','','ps-catalog'),detail=el('section','','ps-detail');
  catalog.setAttribute('role','listbox');attribute(catalog,'aria-label','Phemas');attribute(detail,'aria-label','Phema preview');body.append(catalog,detail);
  // Working in the shown Phema's form or source mode makes it the viewer's pick.
  detail.addEventListener('input',()=>{if(selection)picked=true;});detail.addEventListener('change',()=>{if(selection)picked=true;});
  const listBox=el('div','','ps-list');catalog.append(listBox);
  const footer=el('footer'),target=el('select'),targetLabel=el('label'),open=el('button','','ps-primary');targetLabel.append(label('span','Open layout in'));open.append(label('span','Open Phema'));
  attribute(target,'aria-label','Open layout in');for(const [key,value] of [['New Data Browser','new'],['Current Data Browser','current']]){const option=label('option',key);option.value=value;target.append(option);}
  target.value=initialTarget==='current'?'current':'new';targetLabel.append(target);open.type='button';open.disabled=true;
  // Opening into the current Data Browser replaces its layout and symbols; say so before it happens.
  const replaces=label('small',"Opening replaces this browser's content.",'ps-replace-note');
  // A new Data Browser either tiles every window again or leaves the open ones where they are.
  const arrangeField=el('label','','ps-arrange'),arrange=el('input');arrange.type='checkbox';arrange.checked=remembered.arrange!==false;
  arrangeField.append(arrange,label('span','Arrange windows'));attribute(arrangeField,'title','Tile all Data Browsers after opening');
  const placement=()=>{replaces.hidden=target.value!=='current';arrangeField.hidden=target.value==='current';};placement();target.onchange=placement;
  footer.append(targetLabel,replaces,arrangeField,open);dialog.append(header,searchForm,statusRow,body,footer);
  // Choosing a Phema opens nothing: no window to open it in, and one button that hands it over.
  if(pick){targetLabel.hidden=true;replaces.hidden=true;arrangeField.hidden=true;open.replaceChildren(label('span','Use this Phema'));}
  let closed=false,opening=false,picked=false,selection,controls=[],mode,shot,chosen=null,savedRows=[],discovery=null;
  // Plaza's lists on this account's own Phemas (who may see, open and change each), read once per dialog.
  const permissions=request('/api/phema-permissions').catch(()=>null);
  // Each library's default list as it last answered, kept as a hint for the next opening (see readListCache).
  const caching=typeof storages==='function'&&!phema&&!!cache,cached=caching?readListCache(cache):[],listed=new Map(cached.map(row=>[row.id,row]));
  function saveLists(){
   if(!caching)return;
   try{
    const value=JSON.stringify({version:CACHE_VERSION,storages:[...listed.values()].map(({id,name,ui,items})=>({id,name,ui,items}))});
    if(value.length<=CACHE_LIMIT)cache.write(value);
   }catch{/* A full or blocked browser store only loses the hint. */}
  }
  const remember=()=>{
   const value={excluded:[...excluded].slice(-50),arrange:arrange.checked,sort:sort.value,opened:[...opened.values()].sort((a,b)=>b.at-a.at).slice(0,100)};
   // Saving can be refused (a window that may not change settings); the choice still holds while the dialog is open.
   Promise.resolve().then(()=>preference?.set?.(value)).catch(error=>console.warn('Phema chooser preference:',error.message));
  };
  arrange.onchange=remember;sort.onchange=()=>{remember();renderList();};
  const noteOpened=item=>{const storage=storageOf.get(item)?.storage.id;if(!storage)return;opened.set(storage+'\n'+item.key,{storage,key:item.key,at:Date.now()});remember();};
  // Saved screenshots arrive after the list; one can move a library's Phema up under Last opened.
  const unwatch=previews?.watch(()=>{if(closed)return;if(selection)paint(selection);if(sort.value==='opened'&&states.some(s=>s.items.length))renderList();});previews?.load();
  const report=error=>{if(!closed){if(error?.uiKey){put(status,error.uiKey,undefined,error.uiArgs||[]);return;}delete status.dataset.uiKey;delete status.dataset.uiArgs;status.textContent=error.message||String(error);}};
  const failure=error=>error?.uiKey?say(error.uiKey,undefined,error.uiArgs||[]):String(error?.message||error);
  const storageName=state=>state.storage.uiKey?say(state.storage.uiKey):state.storage.name;
  // A Phema kept in this Terminal (one on this computer included) opens without an agent, so it need not wait for one.
  function update(){const fromSnapshot=mode?.value==='snapshot',waiting=!selection?.saved&&storageOf.get(selection)?.phase==='loading';
   if(pick){open.disabled=waiting||opening||!selection?.available;return;}
   open.disabled=waiting||opening||!selection?.available||(fromSnapshot?!chosen:mode?.value!=='parameters'||controls.some(c=>!c.input.checkValidity()));}
  const when=seconds=>displayDateTime(new Date(seconds*1000).toISOString());
  function enlargeImage(src){
   const viewer=el('dialog','','layout-preview-dialog'),header=el('header'),close=el('button','×');attribute(close,'aria-label','Close dialog');
   header.append(label('strong','Screenshot taken with this snapshot'),close);const image=el('img');image.src=src;image.alt='';viewer.append(header,image);
   close.onclick=()=>viewer.close();viewer.onclose=()=>viewer.remove();document.body.append(viewer);viewer.showModal();
  }
  // The screenshot saved with the chosen snapshot; an older snapshot without one keeps the diagram.
  function paintSnapshot(item){
   const fallback=()=>{if(shot?.isConnected)shot.replaceChildren(label('p','No screenshot was saved with this snapshot','ps-shot-note'),diagram(item.preview,item));};
   if(!chosen?.screenshot){fallback();return;}
   const wanted=chosen.id;
   request('/api/snapshot-previews/'+encodeURIComponent(wanted)).then(saved=>{
    if(!shot?.isConnected||chosen?.id!==wanted)return;
    const enlarge=el('button','','ps-shot');enlarge.type='button';attribute(enlarge,'aria-label','Enlarge preview');
    const image=el('img');image.alt='';image.src=saved.image;enlarge.append(image);enlarge.onclick=()=>enlargeImage(saved.image);
    const note=el('p','','ps-shot-note');note.append(label('span','Screenshot taken with this snapshot'),document.createTextNode(' · '+when(chosen.createdAt)+' · '),label('span','Saved image, not live data'));
    const structure=el('details','','ps-structure');structure.append(label('summary','Layout structure'),diagram(item.preview,item));
    shot.replaceChildren(enlarge,note,structure);
   }).catch(fallback);
  }
  function diagram(preview,item){
   const grid=el('div','','ps-diagram');attribute(grid,'aria-label','Layout preview');
   const panels=preview?.panels||[],columns=Math.max(1,Math.min(24,Number(preview?.columns)||12));
   let rows=1;
   for(const p of panels){const r=Math.max(1,Math.min(128,Number(p.row)||1)),h=Math.max(1,Math.min(128,Number(p.rowSpan)||1));rows=Math.max(rows,r+h-1);}
   grid.style.gridTemplateColumns=`repeat(${columns},minmax(0,1fr))`;grid.style.gridTemplateRows=`repeat(${rows},minmax(0,1fr))`;
   for(const p of panels){
    const panel=label('div',p.label||'Panel','ps-panel',item);
    const col=Math.max(1,Math.min(columns,Number(p.column)||1)),width=Math.max(1,Math.min(columns-col+1,Number(p.columnSpan)||columns));
    panel.style.gridColumn=`${col}/span ${width}`;panel.style.gridRow=`${Math.max(1,Math.min(128,Number(p.row)||1))}/span ${Math.max(1,Math.min(128,Number(p.rowSpan)||1))}`;
    grid.append(panel);
   }
   if(!panels.length)grid.append(label('p','No layout preview is available.'));
   return grid;
  }
  // The last good instance the user's own Terminal saw, never live data; the diagram stands in until one exists.
  function paint(item){
   if(!shot?.isConnected)return;
   if(mode?.value==='snapshot'){paintSnapshot(item);return;}
   const saved=previews?.forPhema(item.phemaId);
   if(!saved){shot.replaceChildren(label('p','No saved screenshot yet','ps-shot-note'),diagram(item.preview,item));return;}
   const enlarge=el('button','','ps-shot');enlarge.type='button';attribute(enlarge,'aria-label','Enlarge preview');
   const image=el('img');image.alt='';image.src=saved.thumbnail;enlarge.append(image);enlarge.onclick=()=>previews.open(saved.layoutPreviewKey);
   previews.full(saved.layoutPreviewKey).then(src=>{if(image.isConnected)image.src=src;}).catch(()=>{});
   const note=el('p','','ps-shot-note');note.append(label('span','Last known preview'),document.createTextNode(' · '+previews.note(saved)+' · '),label('span','Saved image, not live data'));
   const structure=el('details','','ps-structure');structure.append(label('summary','Layout structure'),diagram(item.preview,item));
   shot.replaceChildren(enlarge,note,structure);
  }
  // Change layout starts on the entry this Browser opened. Its key tells it apart from another owner's copy that
  // keeps the same Phema id; a Browser saved before keys matches by id only when one item has it.
  function reopened(item){
   if(!current||item?.saved)return false;
   if(current.key)return item.key===current.key;
   const sameId=states.filter(s=>s.included).flatMap(s=>s.items).filter(row=>!row.saved&&row.available&&row.phemaId===current.phemaId);
   return sameId.length===1&&sameId[0]===item;
  }
  const sameEntry=(a,b)=>!!a&&!!b&&a.key===b.key&&storageOf.get(a)===storageOf.get(b);
  function show(item){
   selection=item;controls=[];chosen=null;mode=null;detail.replaceChildren();scoped(detail,itemUI.get(item)||storageOf.get(item)?.ui);scoped(open,itemUI.get(item));
   for(const button of listBox.querySelectorAll('.ps-option'))button.setAttribute('aria-selected',String(button.dataset.key===item.key&&button.dataset.storage===storageOf.get(item)?.storage.id));
   shot=el('div','','ps-shot-slot');detail.append(label('h2',item.name,'',item),label('p',item.description||'','ps-description',item));
   // The Phema's own author, from Plaza; the agent that stores it only serves it.
   if(typeof item.owner?.name==='string'&&item.owner.name){
    const line=el('div','','ps-owner-line'),href=item.owner.record&&trustOwner?.(item.owner.record);
    line.append(label('span','Owner: {0}','ps-owner',item,[item.owner.name]));
    // Plaza's page, where you choose to trust this owner's account; nothing changes here.
    // A separate element: translation rewrites the owner text and would drop a link inside it.
    if(href){const link=label('a','Trust this owner on Plaza','ps-owner-trust');link.href=href;link.target='_blank';link.rel='noopener';line.append(link);}
    detail.append(line);
   }
   const permissionSlot=el('div','','ps-permissions-slot');detail.append(permissionSlot);
   const keeper=storageOf.get(item)?.storage.id;
   if(typeof keeper==='string'&&keeper.startsWith('agent:')&&!item.saved)permissions.then(value=>{
    const own=value?.available&&(value.phemas||[]).find(row=>row.agentId===keeper.slice(6)&&row.key===item.key);
    if(!own||closed||selection!==item)return;
    const toggle=label('button','Permissions','ps-permissions-toggle');toggle.type='button';toggle.setAttribute('aria-expanded','false');
    const panel=el('div','','ps-permissions');panel.hidden=true;
    toggle.onclick=()=>{panel.hidden=!panel.hidden;toggle.setAttribute('aria-expanded',String(!panel.hidden));if(!panel.hidden)permissionPanel(panel,own,value.roles||[],item);};
    permissionSlot.replaceChildren(toggle,panel);
   });
   detail.append(shot);paint(item);
   const previewButton=label('button','View Content');previewButton.type='button';
   const inspected=el('div','','ps-inspection');inspected.hidden=true;
   const table=el('table');attribute(table,'aria-label','Layout structure');
   const top=el('tr');for(const title of ['Panel','Column','Row','Width','Height'])top.append(label('th',title));table.append(top);
   for(const panel of item.preview?.panels||[]){const row=el('tr');for(const key of ['label','column','row','columnSpan','rowSpan'])row.append(key==='label'?label('td',panel[key]||'','',item):el('td',String(panel[key]??'')));table.append(row);}
   inspected.append(table);
   // Each panel by its layout title, with its saved state in the interface language.
   const PANEL_STATUS={ready:'Ready',partial:'Partial',pending:'Content pending',resolving:'Resolving content',unavailable:'Unavailable',failed:'Unavailable',blocked:'Approval required'};
   // In snapshot mode View Content shows what the chosen snapshot holds: its symbols and each panel's saved state.
   async function snapshotContent(){
    const value=await request('/api/phema-snapshots/'+encodeURIComponent(chosen.id));
    const facts=el('table');attribute(facts,'aria-label','Snapshot');
    const fact=(name,text)=>{const row=el('tr');row.append(label('th',name,'',item),el('td',text));facts.append(row);};
    fact('Saved at',when(value.capturedAt||chosen.createdAt));if(value.label)fact('Label',value.label);
    // The values the open form asks for. One a view keeps itself (a tab, a chart range) is not shown, as the form
    // does not show it, and no value reads "[object Object]".
    for(const [key,current] of Object.entries(value.parameters||{})){
     const rule=item.parameterSchema?.properties?.[key];if(rule?.readOnly===true)continue;
     fact(rule?.title||key,shown(current));
    }
    const panels=el('table');attribute(panels,'aria-label','Panels');const head=el('tr');for(const title of ['Panel','Status','Rows'])head.append(label('th',title));panels.append(head);
    for(const panel of value.panels||[]){const row=el('tr');row.append(label('td',panel.title||panel.id,'',item),label('td',PANEL_STATUS[panel.status]||String(panel.status||'')),el('td',panel.rows==null?'—':String(panel.rows)));panels.append(row);}
    return [facts,panels];
   }
   previewButton.onclick=async()=>{
    if(inspected.hidden&&mode.value==='snapshot'){if(!chosen)return;try{inspected.replaceChildren(...await snapshotContent());}catch(error){report(error);return;}}
    else if(inspected.hidden)inspected.replaceChildren(table);
    inspected.hidden=!inspected.hidden;previewButton.setAttribute('aria-expanded',String(!inspected.hidden));
   };
   previewButton.setAttribute('aria-expanded','false');
   const snapshotField=el('label','','ps-snapshot');snapshotField.hidden=true;snapshotField.append(label('span','Snapshot'));
   const snapshotSelect=el('select');attribute(snapshotSelect,'aria-label','Snapshot');snapshotField.append(snapshotSelect);
   const noSnapshots=label('p','No saved snapshots yet. Open with parameters, then save one with ▣ Phema content → Save snapshot.','ps-snapshot-note');noSnapshots.hidden=true;
   const choose=value=>{chosen=value;inspected.hidden=true;previewButton.setAttribute('aria-expanded','false');paint(item);update();};
   snapshotSelect.onchange=()=>choose(snapshots.find(s=>s.id===snapshotSelect.value)||null);
   let snapshots=[];
   // The viewer's own saved Browser snapshots of this Phema, newest first.
   async function loadSnapshots(){
    try{
     const result=await request('/api/phema-snapshots?phemaId='+encodeURIComponent(item.phemaId));
     if(closed||selection!==item||mode.value!=='snapshot')return;
     snapshots=Array.isArray(result?.snapshots)?result.snapshots:[];
     snapshotSelect.replaceChildren(...snapshots.map(s=>{const option=el('option',when(s.createdAt)+(s.label?' · '+s.label:''));option.value=s.id;return option;}));
     snapshotField.hidden=!snapshots.length;noSnapshots.hidden=!!snapshots.length;choose(snapshots[0]||null);
    }catch(error){report(error);}
   }
   const modeLabel=el('label');modeLabel.append(label('span','Source mode'));mode=el('select');attribute(mode,'aria-label','Source mode');
   for(const [key,value] of [['Parameters','parameters'],['Snapshot','snapshot']]){const option=label('option',key);option.value=value;mode.append(option);}
   for(const option of mode.options)option.disabled=!(item.sourceModes||[]).includes(option.value);
   mode.value='parameters';modeLabel.append(mode);attribute(mode,'title',item.snapshotReason||'',item);
   mode.onchange=()=>{
    const fromSnapshot=mode.value==='snapshot';chosen=null;form.hidden=fromSnapshot;snapshotField.hidden=true;noSnapshots.hidden=true;inspected.hidden=true;
    previewButton.setAttribute('aria-expanded','false');paint(item);update();if(fromSnapshot)loadSnapshots();
   };
   const toolbar=el('div','','ps-preview-tools');toolbar.append(modeLabel,snapshotField,previewButton);detail.append(toolbar,noSnapshots,inspected);
   if(item.unavailableReason)detail.append(label('p',item.unavailableReason,'ps-error',item));
   const schema=item.parameterSchema||{},form=el('div','','ps-parameters');
   // Its owner lets you open it with its saved values only: they show, and none can be changed.
   const locked=item.parametersLocked===true;
   if(locked&&Object.values(schema.properties||{}).some(s=>s.readOnly!==true))form.append(label('p','Only its owner can change these parameters.','ps-locked-note'));
   for(const [key,s] of Object.entries(schema.properties||{})){
    // A parameter its view keeps itself starts from its default; there is nothing to choose here.
    if(s.readOnly===true)continue;
    // Change layout starts from the open layout's own values, not the template's defaults.
    const start=!locked&&reopened(item)&&Object.hasOwn(current.parameters,key)?current.parameters[key]:s.default;
    const field=el('label'),input=el(s.enum||s.oneOf?'select':'input');field.append(label('span',s.title||key,'',item));
    attribute(input,'aria-label',s.title||key,item);
    // A field's own help: its description as a tooltip, its first example as the placeholder. Values are never rewritten.
    if(typeof s.description==='string'&&s.description.trim())attribute(field,'title',s.description,item);
    const example=Array.isArray(s.examples)?s.examples[0]:undefined;
    if(s.enum||s.oneOf){for(const choice of s.oneOf||s.enum.map(value=>({const:value,title:String(value)}))){const option=choice.title?label('option',choice.title,'',item):el('option',String(choice.const));option.value=String(choice.const);input.append(option);};input.value=String(start??'');}
    else if(s.type==='boolean'){input.type='checkbox';input.checked=start===true;}
    else if(['integer','number'].includes(s.type)){input.type='number';input.step=s.type==='integer'?'1':'any';if(s.minimum!==undefined)input.min=String(s.minimum);if(s.maximum!==undefined)input.max=String(s.maximum);input.value=String(start??'');}
    else if(s.type==='string'||s.type==='array'){input.type='text';input.value=s.type==='array'?(Array.isArray(start)?start:[]).join(', '):String(start??'');if(s.maxLength)input.maxLength=s.maxLength;
     if(example!==undefined)input.placeholder=Array.isArray(example)?example.join(', '):String(example);}
    else {input.type='text';input.disabled=true;attribute(input,'placeholder','Unsupported parameter control');const copy={...item,available:false};storageOf.set(copy,storageOf.get(item));if(itemUI.has(item))itemUI.set(copy,itemUI.get(item));item=copy;selection=item;}
    if(locked)input.disabled=true;
    input.required=(schema.required||[]).includes(key);input.oninput=update;field.append(input);form.append(field);controls.push({key,s,input});
   }
   detail.append(form,keepTools(item));if(!pick)open.replaceChildren(label('span','Open'),document.createTextNode(' '),label('span',item.name,'',item));update();
  }
  // Who may see, open and change one of this account's Phemas: three lists, each everyone, only you, or roles you
  // made. Saved to Plaza through this window's session; the agent that keeps the Phema enforces them.
  const RIGHTS=[['see','See'],['open','Open'],['change','Change parameters']],MODES=[['everyone','Everyone'],['owner','Only me'],['roles','Chosen roles']];
  function permissionPanel(panel,own,roles,item){
   const draft=Object.fromEntries(RIGHTS.map(([right])=>[right,{mode:own.rights?.[right]?.mode||'everyone',roles:(own.rights?.[right]?.roles||[]).map(role=>role.id)}]));
   const note=el('p','','ps-permissions-status');note.setAttribute('role','status');
   const rows=RIGHTS.map(([right,name])=>{
    const row=el('div','','ps-permission-row'),select=el('select'),picks=el('div','','ps-permission-roles');
    row.dataset.right=right;attribute(select,'aria-label',name);
    for(const [value,text] of MODES){const option=label('option',text);option.value=value;select.append(option);}
    select.value=draft[right].mode;
    const fill=()=>{
     picks.hidden=draft[right].mode!=='roles';
     if(picks.hidden){picks.replaceChildren();return;}
     if(!roles.length){picks.replaceChildren(label('span','You have no roles yet. Create one in the Permission Viewer.','ps-muted'));return;}
     picks.replaceChildren(...roles.map(role=>{
      const choice=el('label'),box=el('input');box.type='checkbox';box.value=role.id;box.checked=draft[right].roles.includes(role.id);
      box.onchange=()=>{draft[right].roles=roles.map(r=>r.id).filter(id=>id===role.id?box.checked:draft[right].roles.includes(id));};
      choice.append(box,document.createTextNode(' '+role.name));return choice;
     }));
    };
    select.onchange=()=>{draft[right].mode=select.value;fill();};
    row.append(label('span',name,'ps-permission-name'),select,picks);fill();return row;
   });
   const save=label('button','Save'),cancel=label('button','Cancel');save.type='button';cancel.type='button';
   save.onclick=async()=>{
    const empty=RIGHTS.find(([right])=>draft[right].mode==='roles'&&!draft[right].roles.length);
    if(empty){put(note,'Choose roles for {0}.',item,[say(empty[1],item)]);return;}
    save.disabled=true;
    try{
     const answer=await request('/api/phema-permissions',{method:'PUT',body:{agentId:own.agentId,key:own.key,...draft}});
     own.rights=answer?.rights||own.rights;if(!closed)put(note,'Saved',item);
    }catch(error){if(!closed)note.textContent=error.message||String(error);}
    finally{save.disabled=false;}
   };
   cancel.onclick=()=>{panel.hidden=true;panel.previousSibling?.setAttribute?.('aria-expanded','false');};
   const tools=el('div','','ps-permission-tools');tools.append(save,cancel);
   panel.replaceChildren(label('p','Who may see, open and change this Phema','ps-permissions-title'),...rows,tools,note);
  }
  // What the form would open with: the values the viewer chose.
  function chosenParameters(){
   const parameters=Object.create(null);
   // A Phema whose parameters are locked opens with its saved values: it sends none.
   if(selection?.parametersLocked===true)return parameters;
   for(const {key,s,input} of controls)parameters[key]=s.type==='boolean'?input.checked:['integer','number'].includes(s.type)?Number(input.value):s.type==='array'?input.value.split(',').map(x=>x.trim()).filter(Boolean):input.value;
   return parameters;
  }
  // The newer revision an agent library offers for a Phema kept here from it.
  const newer=row=>row.source?.kind==='local'||row.source?.kind==='bundled'?null:states.filter(s=>s.storage.id!==TERMINAL&&s.included)
   .flatMap(s=>s.items).find(item=>item.key===row.source?.key&&item.available&&Number(item.revision)>Number(row.source?.revision))||null;
  // A local Phema (shipped by a component on this computer) is updated by the Terminal; a library one from its library.
  const savedItem=row=>({key:'saved:'+row.id,name:row.name||row.id,description:row.description||'',available:true,sourceModes:['parameters'],
   parameterSchema:{},saved:row,update:row.source?.kind==='local'?(row.update?{local:true,revision:row.update.revision}:null):newer(row)});
  // Local matches what a Phema is called, as kept and as shown in the window's language.
  const matches=(item,query)=>{const q=query.toLocaleLowerCase();return !q||[item.name,item.description,say(item.name,item),item.description?say(item.description,item):'']
   .some(v=>String(v||'').toLocaleLowerCase().includes(q));};
  async function loadSaved(){
   const value=await request('/api/kept-phemas');savedRows=Array.isArray(value?.phemas)?value.phemas:[];
   const state=states[0];state.items=savedRows.map(savedItem).filter(item=>matches(item,search.value.trim()));
   for(const item of state.items)storageOf.set(item,state);
  }
  // Until a storage answers a new search, only its earlier Phemas that the search matches here (the test this
  // Terminal's own Phemas use) stay in the list and its count; its answer then replaces them.
  function narrow(state,query){
   if(state.answered===query)return;
   state.items=state.items.filter(item=>matches(item,query));state.answered=null;
  }
  // A library's newer revisions can arrive after the kept Phemas; their badges follow.
  function refreshUpdates(){for(const item of states[0].items)if(!item.update?.local)item.update=newer(item.saved);}
  async function keep(item,parameters){
   const {picker,session}=await storageOf.get(item).setup;
   const value=await session.read(picker.openReference,{key:item.key,revision:item.revision,source_mode:'parameters',parameters});
   if(!value?.phema||value.resolved!==true)throw Error('The owner did not return a resolved Phema.');
   toEntry(value.phema);
   await request('/api/kept-phemas',{method:'PUT',body:{phema:value.phema,key:item.key,revision:Number(item.revision)||1,name:item.name,description:item.description||''}});
   await loadSaved();renderList();
  }
  // Keeping a library's Phema here, or updating, opening and removing one kept here.
  function keepTools(item){
   const tools=el('div','','ps-keep');
   if(item.saved){
    tools.append(label('p','Kept in this Terminal; it opens without asking the catalog.','ps-description'));
    if(item.update?.local){const update=label('button','Update');update.type='button';
     update.onclick=busy.bind(update,async()=>{try{await request('/api/kept-phemas/'+encodeURIComponent(item.saved.id)+'/update',{method:'POST',body:{}});put(status,'Updated in this Terminal');await loadSaved();renderList();}catch(error){report(error);}});tools.append(update);}
    else if(item.update){const update=label('button','Update from catalog');update.type='button';
     update.onclick=busy.bind(update,async()=>{try{await keep(item.update,{});put(status,'Updated in this Terminal');}catch(error){report(error);}});tools.append(update);}
    const remove=label('button','Remove from this Terminal');remove.type='button';
    remove.onclick=busy.bind(remove,async()=>{try{await request('/api/kept-phemas/'+encodeURIComponent(item.saved.id),{method:'DELETE'});selection=null;picked=false;detail.replaceChildren();await loadSaved();renderList();update();}catch(error){report(error);}});
    tools.append(remove);
   }else if(storageOf.get(item)?.setup&&item.available){
    const save=label('button','Save in this Terminal');save.type='button';
    save.onclick=busy.bind(save,async()=>{try{await keep(item,chosenParameters());put(status,'Saved in this Terminal');}catch(error){report(error);}});
    tools.append(save);
   }
   return tools;
  }
  // One list for every storage ticked: this Terminal's first, then each library's in its own order, each labelled.
  function option(item){
   const state=storageOf.get(item),button=el('button','','ps-option');button.type='button';button.setAttribute('role','option');
   button.dataset.key=item.key;button.dataset.storage=state.storage.id;button.setAttribute('aria-selected',String(sameEntry(item,selection)));
   scoped(button,itemUI.get(item));
   const head=el('span','','ps-option-head'),badge=state.storage.uiKey?label('span',state.storage.uiKey,'ps-source'):el('span',state.storage.name,'ps-source');
   head.append(label('strong',item.name,'',item),badge);
   // A reusable block an agent kept here for the person (phema_library `block`): shown so the person sees and can delete it.
   if(item.saved?.source?.kind==='block')head.append(label('span','Block','ps-source'));
   button.append(head);
   if(item.update)button.append(label('small','Update available','ps-badge'));
   if(!item.saved&&typeof item.description==='string'&&item.description.trim()){button.append(label('small',item.description,'',item));attribute(button,'title',item.description,item);}
   button.onclick=()=>{picked=true;show(item);};
   return button;
  }
  function paintStatus(){
   if(closed)return;
   const included=states.filter(s=>s.included),count=included.reduce((n,s)=>n+s.items.length,0);
   if(!included.length)put(status,'Choose where to search.');
   else if(count)put(status,'{0} Phemas',undefined,[String(count)]);
   else if(included.some(s=>s.phase==='loading'))put(status,'Loading Phemas…');
   else put(status,'No matching Phemas.');
   const lines=[...included.filter(s=>s.note).map(s=>label('span',s.note,'',undefined,[storageName(s),...(s.reason?[s.reason]:[])])),
    ...(discovery?[label('span','Other Phema storages could not be listed: {0}','',undefined,[discovery])]:[])];
   notes.replaceChildren(...lines);notes.hidden=!lines.length;notes.title=lines.map(line=>line.textContent).join(' · ');
  }
  const updateKey=item=>item?.update?(item.update.local?'local@':item.update.key+'@')+item.update.revision:'';
  // When this window last opened it: its own record or, for a library's Phema, the newest screenshot this Terminal
  // kept of it (one opened before openings were recorded); or when it was last saved, if later, so a newly saved
  // Phema comes first. Its storage gives that save time in seconds.
  const lastOpened=item=>Math.max(Number(opened.get(storageOf.get(item)?.storage.id+'\n'+item.key)?.at)||0,
   item.saved?0:Number(previews?.forPhema(item.phemaId)?.capturedAt)||0,
   1000*(Number(item.saved?item.saved.savedAt:item.savedAt)||0));
  function order(rows){
   const position=new Map(rows.map((row,i)=>[row,i]));
   if(sort.value==='name'){
    const collator=new Intl.Collator(lang(),{numeric:true,sensitivity:'base'});
    return rows.slice().sort((a,b)=>collator.compare(say(a.name,a),say(b.name,b))||position.get(a)-position.get(b));
   }
   const when=new Map(rows.map(row=>[row,lastOpened(row)]));
   return rows.slice().sort((a,b)=>when.get(b)-when.get(a)||position.get(a)-position.get(b));
  }
  function renderList(){
   if(closed)return;
   const shownUpdate=updateKey(selection);
   refreshUpdates();
   const rows=order(states.filter(s=>s.included).flatMap(s=>s.items));
   listBox.replaceChildren(...rows.map(option));
   // The viewer's own pick (a click, or a value typed in its form) stays; otherwise the entry this Browser opened, else
   // the top of the list as it now stands, so the chosen order decides what is shown first.
   const kept=selection?rows.find(row=>sameEntry(row,selection)):null;
   const next=(picked&&kept)||rows.find(row=>row.available&&reopened(row))||rows.find(row=>row.available)||rows[0]||null;
   if(!next){selection=null;picked=false;detail.replaceChildren();}
   // A fresh answer replaces the cached or earlier copy of the shown row: redraw it unless the viewer is working in it.
   else if(!sameEntry(next,selection)||updateKey(next)!==shownUpdate||(!picked&&next!==selection))show(next);
   else {selection=next;for(const button of listBox.querySelectorAll('.ps-option'))button.setAttribute('aria-selected',String(button.dataset.key===next.key&&button.dataset.storage===storageOf.get(next).storage.id));}
   paintStatus();update();
  }
  // Search one storage with the current query. Its results replace its earlier ones when they arrive.
  function searchStorage(state){
   if(closed||!state.included)return Promise.resolve();
   const query=search.value.trim();narrow(state,query);
   // A library known only from the cached list is asked once discovery names it again.
   if(state.storage.id!==TERMINAL&&!state.storage.selector){state.phase='loading';renderStorages();renderList();return Promise.resolve();}
   const run=++state.run;
   state.phase='loading';state.note=null;state.reason=null;clearTimeout(state.slow);
   state.slow=setTimeout(()=>{if(!closed&&state.run===run&&state.phase==='loading'){state.note='{0} is still searching; until it answers, only Phemas that match are shown.';paintStatus();}},SLOW_MS);
   renderStorages();renderList();
   return busy.run(async()=>{
    try{
     if(state.storage.id===TERMINAL){await loadSaved();if(state.run!==run)return;}
     else{
      state.setup??=Promise.resolve().then(()=>state.storage.selector()).then(phema=>ownerLibrary({phema,request,toEntry,workspaceId:workspaceId()}));
      const {picker,ui,session}=await state.setup;
      state.ui=ui;if(ui&&!dialog.dataset.phemaUi)scoped(dialog,ui);
      const value=await session.read(picker.catalogReference,{query});
      if(closed||state.run!==run)return;
      if(value?.schema!=='phemacast:selection-catalog/1'||!Array.isArray(value.items)||value.items.length>200)throw Error('The owner returned an invalid Phema list.');
      for(const item of value.items){
       if(typeof item.key!=='string'||typeof item.name!=='string')throw Error('The owner returned an invalid Phema item.');
       const bundle=item.extensions?.['phemacast:ui'];if(bundle)itemUI.set(item,validateUIBundle(bundle));storageOf.set(item,state);
      }
      state.items=value.items;
      if(!query&&caching){listed.set(state.storage.id,{id:state.storage.id,name:state.storage.name,ui,items:value.items});saveLists();}
     }
     state.answered=query;state.phase='ready';state.note=null;state.reason=null;  // its answer ends the still-searching note
    }catch(error){
     if(closed||state.run!==run)return;
     // Its earlier results go; the others stay. A library is asked afresh next time.
     state.items=[];state.phase='failed';state.note='{0} could not be searched: {1}';state.reason=failure(error);
     if(state.setup){state.setup.then(({session})=>session.close()).catch(()=>{});state.setup=null;}
    }finally{
     if(state.run===run){clearTimeout(state.slow);if(state.phase==='loading')state.phase='ready';renderStorages();renderList();}
    }
   }).catch(()=>{});  // the dialog closed meanwhile
  }
  function addStorage(storage){
   const state={storage,included:!excluded.has(storage.id),items:[],answered:'',phase:'idle',note:null,reason:null,run:0,slow:null,setup:null,ui:null,box:null};
   states.push(state);
   const box=el('input'),field=el('label','','ps-storage');box.type='checkbox';box.checked=state.included;state.box=field;
   field.append(box,storage.uiKey?label('span',storage.uiKey):el('span',storage.name));
   box.onchange=()=>{
    state.included=box.checked;if(box.checked)excluded.delete(storage.id);else excluded.add(storage.id);remember();
    if(box.checked)searchStorage(state);else{++state.run;clearTimeout(state.slow);state.phase='idle';state.note=null;renderStorages();renderList();}
   };
   storageBar.append(field);return state;
  }
  function renderStorages(){for(const state of states)state.box.setAttribute('aria-busy',String(state.included&&state.phase==='loading'));}
  function load(){for(const state of states)if(state.included)searchStorage(state);paintStatus();}
  addStorage({id:TERMINAL,uiKey:'Local'});
  if(phema)addStorage({id:'catalog',...(name?{name:String(name)}:{uiKey:'Catalog'}),selector:async()=>phema});
  else if(typeof storages==='function'){
   // The libraries as last listed show at once, each marked as still being asked; nothing opens from them.
   for(const row of cached){
    const state=addStorage({id:row.id,name:row.name});state.ui=row.ui;state.phase='loading';
    state.items=row.items;for(const item of row.items){storageOf.set(item,state);const bundle=item.extensions?.['phemacast:ui'];if(bundle)try{itemUI.set(item,validateUIBundle(bundle));}catch{}}
   }
   renderStorages();if(cached.length)renderList();
   // The libraries this account may use now; each is asked again, and a cached one that is gone leaves the list.
   Promise.resolve().then(storages).then(found=>{
    if(closed)return;
    const current=new Set();
    for(const storage of found||[]){
     if(!storage?.id||storage.id===TERMINAL||current.has(storage.id))continue;
     current.add(storage.id);
     const known=states.find(s=>s.storage.id===storage.id);
     if(known){known.storage=storage;known.box.lastChild.textContent=storage.name;if(known.included)searchStorage(known);else{known.phase='idle';renderStorages();}}
     else searchStorage(addStorage(storage));
    }
    for(const state of states.filter(s=>s.storage.id!==TERMINAL&&!current.has(s.storage.id))){
     ++state.run;state.box.remove();states.splice(states.indexOf(state),1);listed.delete(state.storage.id);
    }
    saveLists();renderList();
   }).catch(error=>{
    if(closed)return;discovery=failure(error);
    // Without discovery no cached library can be asked or opened.
    for(const state of states)if(state.storage.id!==TERMINAL&&!state.storage.selector){state.items=[];state.phase='failed';}
    renderStorages();renderList();
   });
  }
  open.onclick=busy.bind(open,async()=>{
   if(open.disabled)return;
   if(pick){
    opening=true;update();
    try{
     const item=selection,storage=storageOf.get(item)?.storage.id||'';
     let preview=item.preview,phemaId=item.phemaId||'',key=item.key;
     if(item.saved){
      // Kept here: its own copy gives the layout, and the library key it was kept from names it to its owner.
      const kept=await request('/api/kept-phemas/'+encodeURIComponent(item.saved.id));
      if(closed)return;
      preview=layoutOutline(kept.phema);phemaId=typeof kept.phema?.id==='string'?kept.phema.id:'';
      if(typeof kept.source?.key==='string'&&kept.source.key)key=kept.source.key;
     }
     const saved=phemaId?previews?.forPhema(phemaId):null;
     let picture='';if(saved){try{picture=await previews.full(saved.layoutPreviewKey);}catch{picture='';}}
     if(closed)return;
     // The name and the block names in the viewer's language, as this list shows them: the pane that keeps the choice
     // draws them as given (Alvin, 2026-11-26: the Original design pane showed the Watch's part names in English).
     const outline=preview||{columns:12,panels:[]};
     const panels=(Array.isArray(outline.panels)?outline.panels:[]).map(p=>p&&typeof p.label==='string'&&p.label?{...p,label:say(p.label,item)}:p);
     await pick({name:say(item.name,item),key,storage,phemaId,preview:{...outline,panels},picture:typeof picture==='string'?picture:''});
     dialog.close();
    }catch(error){report(error);}finally{opening=false;update();}
    return;
   }
   opening=true;put(status,'Opening Phema…');update();
   const item=selection,parameters=chosenParameters(),snapshot=mode.value==='snapshot'?chosen:null;
   const placed=target.value==='new'?{arrange:arrange.checked}:{};
   try{
    if(item.saved){
     // Kept here: open this Terminal's copy, with the parameters it was kept with.
     const kept=await request('/api/kept-phemas/'+encodeURIComponent(item.saved.id));
     if(closed)return;
     toEntry(kept.phema);
     await onOpen({phema:kept.phema,sourceMode:'parameters',target:target.value,selectionKey:kept.source?.key||null,...placed});noteOpened(item);dialog.close();
     return;
    }
    // A snapshot opens the same definition with the symbols it was saved with.
    const {picker,session}=await storageOf.get(item).setup;
    const value=await session.read(picker.openReference,{key:item.key,revision:item.revision,source_mode:mode.value,parameters:snapshot?openedWith(snapshot,item.parameterSchema):parameters});
    if(closed)return;
    if(!value?.phema||value.resolved!==true||!['parameters','snapshot'].includes(value.source_mode))throw Error('The owner did not return a resolved Phema.');
    toEntry(value.phema);
    await onOpen({phema:value.phema,sourceMode:value.source_mode,target:target.value,selectionKey:item.key,...(snapshot?{snapshotId:snapshot.id}:{}),...placed});noteOpened(item);dialog.close();
   }catch(error){report(error);}finally{opening=false;update();}
  });
  searchForm.onsubmit=event=>{event.preventDefault();load();};refresh.onclick=load;dismiss.onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{
   closed=true;active=null;unwatch?.();busy.dispose();dialog.remove();
   for(const state of states){clearTimeout(state.slow);state.setup?.then(({session})=>session.close()).catch(error=>console.error('Selection cleanup:',error.message));}
  },{once:true});
  if(!document.querySelector('link[data-phema-selector-style]')){const link=document.createElement('link');link.rel='stylesheet';link.href=new URL('./phema-selector.css',import.meta.url).href;link.dataset.phemaSelectorStyle='true';document.head.append(link);}
  document.body.append(dialog);active={dialog,search};dialog.showModal();search.focus();load();return dialog;
 }};
}
