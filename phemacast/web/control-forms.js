/** The Terminal's common controls besides the table (`phemacast:control.<type>` 1.0.0), after Windows Forms: Label,
 * LinkLabel, Button, TextBox, NumericUpDown, ComboBox, ListBox, CheckedListBox, CheckBox, RadioButton, DateTimePicker,
 * TrackBar, ProgressBar, GroupBox, Panel and TabControl. Containers hold other controls, tables included.
 *
 * A value a control shows comes from its page value when `dataBindings` binds it (two-way, as Control.DataBindings),
 * else from its property. An edit is saved when it is committed (change, Enter, a choice), so typing never redraws
 * the page; its events run the Phema's declarative actions (control-runtime.js). */
import {registerRenderer} from './composition-renderers.js';
import {VOCABULARY} from './control-vocabulary.js';
import {LIMITS,esc,NAME,LINK,resolve,css,parseValue,validate,eventActions,plan,states,overrides,placeOf,keyOf,controlState,apply,restore} from './control-runtime.js';
// Names and bindings an AI app never reads or sets (as phemacast/core/controls.py SECRET).
const SECRET=/password|secret|token|api.?key|credential|cookie|authorization/i;
import {mountTable} from './control-table.js';

export const VERSION='1.0.0';
export const KINDS=Object.keys(VOCABULARY.kinds).filter(kind=>kind!=='table');
const CONTAINERS=new Set(['groupBox','panel','tabControl']);
// The state each kind keeps, which `dataBindings` may tie to a page value and `$control` may read.
const VALUE={textBox:'text',numericUpDown:'value',comboBox:'selectedValue',listBox:'selectedValues',checkedListBox:'checkedValues',checkBox:'checked',radioButton:'checked',dateTimePicker:'value',trackBar:'value',tabControl:'selectedIndex'};
const SKIP=new Set(['type','events','dataBindings','controls','tabPages','columns','items','dataSource']);
const ALIGN={left:'left',center:'center',right:'right',topLeft:'left',middleLeft:'left',bottomLeft:'left',topCenter:'center',middleCenter:'center',bottomCenter:'center',topRight:'right',middleRight:'right',bottomRight:'right'};

/** A control's properties as drawn now: the document, then setProperty changes, each binding resolved. */
export function effective(doc,scope,changed={}){
 const out={};
 for(const [key,value] of Object.entries({...doc,...changed}))out[key]=SKIP.has(key)?value:resolve(value,scope);
 return out;
}

/** The choices of a list control: {value, text}, from `items` or a bound `dataSource`, at most LIMITS.items. */
export function itemsOf(doc,scope){
 const source=doc.items!==undefined?resolve(doc.items,scope):resolve(doc.dataSource,scope);
 let rows=Array.isArray(source)?source:Array.isArray(source?.rows)?source.rows:Array.isArray(source?.items)?source.items:[];
 rows=rows.slice(0,LIMITS.items).map(item=>item&&typeof item==='object'&&!Array.isArray(item)
  ?{value:doc.valueMember?item[doc.valueMember]:item.value??item.id??item.agentId??item.text,text:String((doc.displayMember?item[doc.displayMember]:item.text??item.name??item.value)??'')}
  :{value:item,text:String(item??'')});
 if(doc.sorted===true)rows.sort((a,b)=>a.text.localeCompare(b.text,undefined,{numeric:true}));
 return rows;
}
const same=(a,b)=>a===b||(a!==null&&a!==undefined&&b!==null&&b!==undefined&&String(a)===String(b));

/** A control's current value for one of its states: the bound page value, else what the viewer chose here, else the
 * property. `bound` says whether a page value holds it. */
export function current(kind,doc,state,scope,property=VALUE[kind]){
 const binding=doc.dataBindings?.[property];
 if(binding)return {bound:true,value:resolve(binding,scope)};
 if(state?.values&&Object.hasOwn(state.values,property))return {bound:false,value:state.values[property]};
 if(kind==='radioButton'&&property==='checked'&&doc.dataBindings?.value)return {bound:true,value:same(resolve(doc.dataBindings.value,scope),doc.value)};
 return {bound:false,value:doc[property]};
}

const attrs=(doc,kind,name,say)=>`data-control="${esc(name)}" data-kind="${kind}" class="phema-ctl ctl-${kind}${doc.enabled===false?' ctl-disabled':''}"${doc.theme&&doc.theme!=='terminal'?` data-control-theme="${esc(doc.theme)}"`:''}${doc.toolTipText?` title="${say(doc.toolTipText)}"`:''}${doc.visible===false?' hidden':''} style="${css({backColor:doc.backColor,foreColor:doc.foreColor,font:doc.font,padding:doc.padding,margin:doc.margin})}"`;
const off=doc=>doc.enabled===false?' disabled':'';
const shownNumber=(value,places)=>typeof value==='number'&&Number.isInteger(places)?value.toFixed(places):value??'';

/** One control's HTML, children included; `env` collects what the page needs to run it. */
export function controlHTML(raw,ctx,env,path='0'){
 const kind=raw.type,name=typeof raw.name==='string'&&raw.name?raw.name:'_'+path.replace(/\./g,'_');
 // A table inside a container keeps its own state (control-table.js): it only gets a host to mount into.
 if(kind==='table'){env.tables.push({name,doc:raw});return `<div class="ctl-table-host" data-table-host="${esc(name)}" data-control="${esc(name)}"></div>`;}
 const scope=env.scope,state=env.state(name),doc=effective(raw,scope,env.changed(name));
 env.controls.set(name,{doc,kind,name});
 const label=ctx.label||esc,say=key=>esc(ctx.translate?ctx.translate(key):key),text=v=>label(String(v??''));
 const a=attrs(doc,kind,name,say),value=VALUE[kind]?current(kind,doc,state,scope):{value:undefined};
 const invalid=state.error?` aria-invalid="true" title="${say(state.error)}"`:'';
 const align=ALIGN[doc.textAlign]?`text-align:${ALIGN[doc.textAlign]}`:'';
 switch(kind){
  case 'label':return `<div ${a}><span class="ctl-text${doc.autoEllipsis?' ctl-ellipsis':''}" style="${align}">${text(doc.text)}</span></div>`;
  case 'linkLabel':return `<div ${a}><button type="button" class="ctl-link${doc.linkVisited?' ctl-visited':''}" data-act="link"${off(doc)}>${text(doc.text)}</button></div>`;
  case 'button':return `<div ${a}><button type="button" class="ctl-button" data-act="button"${off(doc)}>${text(doc.text)}</button></div>`;
  case 'textBox':{
   const shown=state.draft??value.value??'';
   const common=`data-input${off(doc)}${doc.readOnly?' readonly':''}${Number.isInteger(doc.maxLength)&&doc.maxLength>0?` maxlength="${doc.maxLength}"`:''}${doc.placeholderText?` placeholder="${say(doc.placeholderText)}"`:''} style="${align}"${invalid}`;
   return `<div ${a}>${doc.multiline?`<textarea ${common}${doc.wordWrap===false?' wrap="off"':''}>${esc(shown)}</textarea>`:`<input type="text" ${common} value="${esc(shown)}">`}</div>`;
  }
  case 'numericUpDown':{
   const step=typeof doc.increment==='number'?doc.increment:Number.isInteger(doc.decimalPlaces)&&doc.decimalPlaces>0?10**-doc.decimalPlaces:1;
   return `<div ${a}><input type="number" data-input${off(doc)} value="${esc(state.draft??shownNumber(value.value,doc.decimalPlaces))}"${typeof doc.minimum==='number'?` min="${doc.minimum}"`:''}${typeof doc.maximum==='number'?` max="${doc.maximum}"`:''} step="${step}"${invalid}></div>`;
  }
  case 'comboBox':{
   const items=itemsOf(doc,scope),index=items.findIndex(item=>same(item.value,value.value));
   env.items.set(name,items);
   if(doc.dropDownStyle==='dropDown'){
    const list=`list-${env.id}-${name}`;
    return `<div ${a}><input type="text" data-input list="${esc(list)}"${off(doc)} value="${esc(state.draft??(index>=0?items[index].text:value.value??''))}"${invalid}><datalist id="${esc(list)}">${items.map(item=>`<option value="${esc(item.text)}"></option>`).join('')}</datalist></div>`;
   }
   return `<div ${a}><select data-input${off(doc)}${invalid}>${index<0?'<option value="-1" selected></option>':''}${items.map((item,i)=>`<option value="${i}"${i===index?' selected':''}>${esc(item.text)}</option>`).join('')}</select></div>`;
  }
  case 'listBox':{
   const items=itemsOf(doc,scope),chosen=Array.isArray(value.value)?value.value:[];
   env.items.set(name,items);
   return `<div ${a}><select data-input${doc.selectionMode&&doc.selectionMode!=='one'?' multiple':''} size="${Math.max(2,Math.min(items.length||2,8))}"${off(doc)}${invalid}>${items.map((item,i)=>`<option value="${i}"${chosen.some(v=>same(v,item.value))?' selected':''}>${esc(item.text)}</option>`).join('')}</select></div>`;
  }
  case 'checkedListBox':{
   const items=itemsOf(doc,scope),checked=Array.isArray(value.value)?value.value:[];
   env.items.set(name,items);
   return `<div ${a} role="group">${items.map((item,i)=>`<label class="ctl-check"><input type="checkbox" data-item="${i}"${checked.some(v=>same(v,item.value))?' checked':''}${off(doc)}> ${esc(item.text)}</label>`).join('')}</div>`;
  }
  case 'checkBox':{
   const state3=doc.threeState&&value.value===null?'indeterminate':value.value===true?'checked':'unchecked';
   return `<div ${a}><label class="ctl-check"><input type="checkbox" data-input${state3==='checked'?' checked':''}${state3==='indeterminate'?' data-indeterminate':''}${off(doc)}> ${text(doc.text)}</label></div>`;
  }
  case 'radioButton':{
   const group=`${env.id}|${doc.groupName||'radio'}`;
   return `<div ${a}><label class="ctl-check"><input type="radio" data-input name="${esc(group)}"${value.value===true?' checked':''}${off(doc)}> ${text(doc.text)}</label></div>`;
  }
  case 'dateTimePicker':{
   const type=doc.format==='time'?'time':typeof value.value==='string'&&value.value.length>10?'datetime-local':'date';
   const empty=value.value===null||value.value===undefined||value.value==='';
   const box=doc.showCheckBox?`<input type="checkbox" data-date-on${empty?'':' checked'}${off(doc)}> `:'';
   const min=typeof doc.minDate==='string'?` min="${esc(doc.minDate)}"`:'',max=typeof doc.maxDate==='string'?` max="${esc(doc.maxDate)}"`:'';
   return `<div ${a}>${box}<input type="${type}" data-input value="${esc(empty?'':String(value.value).replace(' ','T'))}"${min}${max}${off(doc)}${doc.showCheckBox&&empty?' disabled':''}${invalid}></div>`;
  }
  case 'trackBar':{
   const min=typeof doc.minimum==='number'?doc.minimum:0,max=typeof doc.maximum==='number'?doc.maximum:10;
   return `<div ${a}><input type="range" data-input min="${min}" max="${max}" step="${typeof doc.smallChange==='number'?doc.smallChange:1}" value="${esc(value.value??min)}"${doc.orientation==='vertical'?' class="ctl-vertical"':''}${off(doc)}></div>`;
  }
  case 'progressBar':{
   const min=typeof doc.minimum==='number'?doc.minimum:0,max=typeof doc.maximum==='number'?doc.maximum:100,v=typeof doc.value==='number'?doc.value:null;
   return `<div ${a}><progress max="${max-min}"${doc.style==='marquee'||v===null?'':` value="${Math.max(0,Math.min(max,v)-min)}"`}></progress></div>`;
  }
  case 'groupBox':return `<fieldset ${a} data-border="${esc(doc.borderStyle||'fixedSingle')}"><legend>${text(doc.text)}</legend><div class="ctl-flow">${children(raw.controls,ctx,env,path)}</div></fieldset>`;
  case 'panel':return `<div ${a} data-border="${esc(doc.borderStyle||'none')}"><div class="ctl-flow">${children(raw.controls,ctx,env,path)}</div></div>`;
  case 'tabControl':{
   const pages=Array.isArray(raw.tabPages)?raw.tabPages.slice(0,12):[];
   const selected=Math.max(0,Math.min(pages.length-1,Number.isInteger(value.value)?value.value:0));
   return `<div ${a}><div class="ctl-tablist" role="tablist">${pages.map((page,i)=>`<button type="button" role="tab" data-tab="${i}" aria-selected="${i===selected}"${off(doc)}>${text(page.text)}</button>`).join('')}</div><div class="ctl-flow" role="tabpanel">${children(pages[selected]?.controls,ctx,env,path+'.'+selected)}</div></div>`;
  }
 }
 return '';
}
function children(list,ctx,env,path){
 return (Array.isArray(list)?list:[]).slice(0,LIMITS.controls).map((child,i)=>child&&typeof child==='object'?controlHTML(child,ctx,env,path+'.'+i):'').join('');
}

/** What the page draws for one surface, and what it needs to run it (for tests and for mount). */
export function formHTML(value,ctx,{window='',panel='',changed=()=>({}),state=()=>({})}={}){
 const env={id:window+'|'+panel,scope:{parameters:value.parameters||{},results:value.results||{},links:value.links,panels:value.panels,opened:value.opened,agents:value.agents,controlState:controlState(window)},controls:new Map(),items:new Map(),tables:[],changed,state};
 const html=value.control&&typeof value.control==='object'&&KINDS.includes(value.control.type)?controlHTML(value.control,ctx,env):'';
 return {html,env};
}

// ---- In the page. ---------------------------------------------------------------------------------------------
function mountForm(host,value,context){
 const ctx={...context,fieldFormats:value.fieldFormats||{}};
 const {window,panel}=placeOf(host);
 const local=new Map();     // control name → its state on this page
 const stateOf=name=>{
  if(!local.has(name)){
   const key=keyOf(host,name),kept=states.get(key)||{values:{},bound:{}};
   kept.read=property=>{const entry=env.controls.get(name);return entry?readState(entry,property):undefined;};
   kept.clear=()=>{kept.values={};kept.draft=undefined;};
   states.set(key,kept);local.set(name,kept);
  }
  return local.get(name);
 };
 let env;
 const readState=({kind,doc,name},property)=>{
  const state=stateOf(name),items=env.items.get(name)||[];
  if(kind==='comboBox'){
   const selected=current(kind,doc,state,env.scope).value,index=items.findIndex(item=>same(item.value,selected));
   return property==='selectedIndex'?index:property==='text'?(index>=0?items[index].text:selected??''):selected;
  }
  if(kind==='checkedListBox'&&property==='selectedValues')return state.values.selectedValues??[];
  if(kind==='checkBox'&&property==='checkState'){const v=current(kind,doc,state,env.scope).value;return v===null?'indeterminate':v?'checked':'unchecked';}
  if(kind==='radioButton'&&property==='value')return doc.value;
  return current(kind,doc,state,env.scope,property).value;
 };
 const view=()=>{
  const drawn=formHTML(value,ctx,{window,panel,changed:name=>overrides.get(window+'|'+name)||{},state:stateOf});
  env=drawn.env;host.innerHTML=drawn.html;
  host._controlNames=new Set(env.controls.keys());
  for(const box of host.querySelectorAll('input[data-indeterminate]'))box.indeterminate=true;
  for(const {name,doc} of env.tables){
   const target=host.querySelector(`[data-table-host="${CSS.escape(name)}"]`);host._controlNames.add(name);
   if(target)mountTable(target,{control:doc,parameters:value.parameters,results:value.results,own:null,fieldFormats:value.fieldFormats,links:value.links,panels:value.panels,opened:value.opened,agents:value.agents},context);
  }
  restore(host);
 };
 host._controlRender=view;
 const entryOf=target=>{const node=target.closest?.('[data-control]');if(!node||node.dataset.tableHost!==undefined)return null;const entry=env.controls.get(node.dataset.control);return entry?{...entry,name:node.dataset.control,node}:null;};
 const details=(entry,extra={})=>{const state=stateOf(entry.name);return {name:entry.doc.name??null,kind:entry.kind,value:VALUE[entry.kind]?readState(entry,VALUE[entry.kind]):undefined,...extra};};
 // One gesture on one control: its events' actions, then the page values its bound states now hold.
 const run=(entry,fired,writes={})=>{
  if(entry.doc.enabled===false)return;
  const actions=fired.flatMap(([event,detail])=>eventActions(entry.doc,event,detail,env.scope));
  const result=plan(actions,value.parameters||{});
  for(const [stateName,next] of Object.entries(writes)){
   const target=entry.doc.dataBindings?.[stateName]?.$param,param=typeof target==='string'?target.slice(1):'';
   if(NAME.test(param)&&JSON.stringify((value.parameters||{})[param])!==JSON.stringify(next))result.values[param]=next??null;
  }
  apply(host,result);
 };
 // A committed value: checked, then saved where the Phema binds it, or kept here when nothing binds it.
 const commit=(entry,property,next,fired)=>{
  const state=stateOf(entry.name),old=readState(entry,property);
  const message=validate(next,entry.doc.validation);
  if(message){
   state.error=message;
   const input=entry.node.querySelector('[data-input]');if(input){input.setAttribute('aria-invalid','true');input.title=ctx.translate?ctx.translate(message):message;}
   run(entry,[['validating',details(entry,{valid:false,message,value:next})]]);
   return false;
  }
  state.error=undefined;state.draft=undefined;
  const bound=Boolean(entry.doc.dataBindings?.[property]||(entry.kind==='radioButton'&&entry.doc.dataBindings?.value));
  if(!bound)state.values={...state.values,[property]:next};
  // An unbound radio button that is checked unchecks the others of its group on this surface.
  if(!bound&&entry.kind==='radioButton'&&next===true)for(const [other,{kind,doc}] of env.controls)if(other!==entry.name&&kind==='radioButton'&&(doc.groupName||'radio')===(entry.doc.groupName||'radio'))stateOf(other).values={...stateOf(other).values,checked:false};
  const writes=bound?entry.kind==='radioButton'&&entry.doc.dataBindings?.value?(next?{value:entry.doc.value}:{}):{[property]:next}:{};
  if(!bound||same(JSON.stringify(old),JSON.stringify(next)))view();
  run(entry,[['validated',details(entry,{valid:true,value:next})],...fired.map(([event,extra])=>[event,details(entry,{oldValue:old,value:next,...extra})])],writes);
  return true;
 };
 host.addEventListener('click',event=>{
  const entry=entryOf(event.target);if(!entry||entry.doc.enabled===false)return;
  const {kind,doc}=entry;
  if(kind==='tabControl'){
   const tab=event.target.closest('[data-tab]');
   if(tab){const index=Number(tab.dataset.tab);if(index!==readState(entry,'selectedIndex'))commit(entry,'selectedIndex',index,[['selectedIndexChanged',{selectedIndex:index}]]);return;}
  }
  const fired=[['click',details(entry)]];
  if(kind==='linkLabel'&&event.target.closest('[data-act="link"]')){
   fired.push(['linkClicked',details(entry,{link:doc.link??null})]);
   overrides.set(window+'|'+entry.name,{...overrides.get(window+'|'+entry.name),linkVisited:true});
   if(typeof doc.link==='string'&&LINK.test(doc.link))globalThis.open?.(doc.link,'_blank','noopener,noreferrer');
  }
  run(entry,fired);
 });
 host.addEventListener('dblclick',event=>{const entry=entryOf(event.target);if(entry)run(entry,[['doubleClick',details(entry)]]);});
 // Typing: textChanged (after a pause) and textUpdate; nothing is saved until the edit is committed.
 const timers=new Map();
 host.addEventListener('input',event=>{
  const entry=entryOf(event.target);if(!entry)return;
  const {kind}=entry,input=event.target;
  if(kind==='textBox'||(kind==='comboBox'&&entry.doc.dropDownStyle==='dropDown')||kind==='numericUpDown'){
   stateOf(entry.name).draft=input.value;
   if(kind==='comboBox')run(entry,[['textUpdate',details(entry,{text:input.value})]]);
   if(kind==='textBox'&&entry.doc.events?.textChanged){clearTimeout(timers.get(entry.name));timers.set(entry.name,setTimeout(()=>run(entry,[['textChanged',details(entry,{text:input.value})]]),400));}
  }
  if(kind==='trackBar')run(entry,[['scroll',details(entry,{value:Number(input.value)})]]);
 });
 host.addEventListener('change',event=>{
  const entry=entryOf(event.target);if(!entry)return;
  const {kind,doc}=entry,input=event.target,items=env.items.get(entry.name)||[];
  if(kind==='textBox')commit(entry,'text',input.value,[['textChanged',{}]]);
  else if(kind==='numericUpDown'){const parsed=parseValue(input.value,'number');if(parsed.error){const s=stateOf(entry.name);s.error=parsed.error;input.setAttribute('aria-invalid','true');input.title=ctx.translate?ctx.translate(parsed.error):parsed.error;run(entry,[['validating',details(entry,{valid:false,message:parsed.error})]]);return;}
   // As NumericUpDown does, a typed value is held to the minimum and maximum, then to the decimal places.
   let next=parsed.value;
   if(next!==null){if(typeof doc.minimum==='number')next=Math.max(doc.minimum,next);if(typeof doc.maximum==='number')next=Math.min(doc.maximum,next);if(Number.isInteger(doc.decimalPlaces))next=Number(next.toFixed(doc.decimalPlaces));}
   commit(entry,'value',next,[['valueChanged',{}]]);}
  else if(kind==='comboBox'){
   if(doc.dropDownStyle==='dropDown'){const hit=items.find(item=>item.text===input.value);commit(entry,'selectedValue',hit?hit.value:input.value,[['selectedValueChanged',{}],['selectionChangeCommitted',{}]]);}
   else{const index=Number(input.value),item=items[index];if(!item)return;commit(entry,'selectedValue',item.value,[['selectedIndexChanged',{selectedIndex:index}],['selectedValueChanged',{}],['selectionChangeCommitted',{selectedIndex:index}]]);}
  }
  else if(kind==='listBox'){const values=[...input.selectedOptions].map(option=>items[Number(option.value)]?.value).filter(v=>v!==undefined);commit(entry,'selectedValues',values,[['selectedIndexChanged',{selectedValues:values}]]);}
  else if(kind==='checkedListBox'){
   const index=Number(input.dataset.item),item=items[index];if(!item)return;
   const before=readState(entry,'checkedValues')||[],values=input.checked?[...before.filter(v=>!same(v,item.value)),item.value]:before.filter(v=>!same(v,item.value));
   stateOf(entry.name).values.selectedValues=[item.value];
   commit(entry,'checkedValues',values,[['itemCheck',{item:item.value,checked:input.checked}],['selectedIndexChanged',{selectedIndex:index}]]);
  }
  else if(kind==='checkBox')commit(entry,'checked',input.checked,[['checkedChanged',{checked:input.checked}],['checkStateChanged',{checkState:input.checked?'checked':'unchecked'}]]);
  else if(kind==='radioButton')commit(entry,'checked',input.checked,[['checkedChanged',{checked:input.checked}]]);
  else if(kind==='dateTimePicker'){
   if(input.matches('[data-date-on]')){commit(entry,'value',input.checked?(entry.node.querySelector('[data-input]').value||null):null,[['valueChanged',{}]]);return;}
   commit(entry,'value',input.value||null,[['valueChanged',{}]]);
  }
  else if(kind==='trackBar')commit(entry,'value',Number(input.value),[['valueChanged',{}]]);
 });
 host.addEventListener('keydown',event=>{
  const entry=entryOf(event.target);if(!entry||!['Enter','Escape'].includes(event.key))return;
  const input=event.target;
  if(event.key==='Escape'&&input.matches('[data-input]')&&entry.kind==='textBox'){stateOf(entry.name).draft=undefined;view();}
  run(entry,[['keyDown',details(entry,{key:event.key})]]);
  if(event.key==='Enter'&&entry.kind==='textBox'&&!input.matches('textarea'))input.blur?.();
 });
 host.addEventListener('focusin',event=>{
  const entry=entryOf(event.target);if(!entry||entryOf(event.relatedTarget||document.body)?.name===entry.name)return;
  const fired=[['enter',details(entry)]];if(entry.kind==='comboBox')fired.push(['dropDown',details(entry)]);run(entry,fired);
 });
 host.addEventListener('focusout',event=>{
  const entry=entryOf(event.target);if(!entry||(event.relatedTarget&&entryOf(event.relatedTarget)?.name===entry.name))return;
  const fired=[['leave',details(entry)]];if(entry.kind==='comboBox')fired.push(['dropDownClosed',details(entry)]);run(entry,fired);
 });
 // What an AI app the window approved may do with these controls (the Terminal's MCP `controls` / `use_control`):
 // read them, set a value or click, through the same commit and events a person's input takes. A disabled or
 // read-only control, or one whose name or binding looks like a secret, is not reachable.
 const secret=entry=>SECRET.test(entry.name)||SECRET.test(JSON.stringify(entry.doc.dataBindings||{}));
 const SETTABLE=new Set(['textBox','numericUpDown','comboBox','listBox','checkedListBox','checkBox','radioButton','dateTimePicker','trackBar','tabControl']);
 host._aiControls={
  list:()=>[...env.controls].map(([name,{kind,doc}])=>{
   const entry={name,kind,doc},items=env.items.get(name)||[],hidden=secret(entry);
   return {control:name,kind,...(typeof doc.text==='string'&&kind!=='textBox'?{text:doc.text.slice(0,200)}:{}),
    ...(VALUE[kind]&&!hidden?{value:readState(entry,VALUE[kind])}:{}),enabled:doc.enabled!==false,readOnly:doc.readOnly===true,
    settable:SETTABLE.has(kind)&&doc.enabled!==false&&doc.readOnly!==true&&!hidden,
    events:Object.keys(doc.events||{}),...(items.length?{items:items.slice(0,50).map(item=>({text:item.text,value:item.value}))}:{})};
  }),
  use:(name,op,arg)=>{
   const found=env.controls.get(name);if(!found)throw Error('This panel has no control by that name; controls lists them.');
   const node=host.querySelector(`[data-control="${CSS.escape(name)}"]`),entry={...found,name,node};
   if(secret(entry))throw Error("AI apps can't use that control.");
   if(entry.doc.enabled===false)throw Error('That control is disabled now.');
   if(op==='click'){run(entry,[['click',details(entry)]]);return details(entry);}
   if(op!=='set'||!SETTABLE.has(entry.kind))throw Error('Set a value on an input control, or click.');
   if(entry.doc.readOnly===true)throw Error('That control is read-only.');
   const {kind,doc}=entry,items=env.items.get(name)||[],pick=v=>items.find(item=>same(item.value,v))||items.find(item=>item.text===v);
   let ok;
   if(kind==='textBox')ok=commit(entry,'text',arg==null?'':String(arg),[['textChanged',{}]]);
   else if(kind==='numericUpDown'||kind==='trackBar'){
    let next=arg===null?null:Number(arg);if(next!==null&&!Number.isFinite(next))throw Error('Give a number.');
    if(next!==null){if(typeof doc.minimum==='number')next=Math.max(doc.minimum,next);if(typeof doc.maximum==='number')next=Math.min(doc.maximum,next);if(Number.isInteger(doc.decimalPlaces))next=Number(next.toFixed(doc.decimalPlaces));}
    ok=commit(entry,'value',next,[['valueChanged',{}]]);
   }
   else if(kind==='comboBox'){const item=pick(arg);if(!item&&doc.dropDownStyle!=='dropDown')throw Error('Choose one of its items.');
    ok=commit(entry,'selectedValue',item?item.value:String(arg),[['selectedValueChanged',{}],['selectionChangeCommitted',{}]]);}
   else if(kind==='listBox'||kind==='checkedListBox'){
    const values=(Array.isArray(arg)?arg:[arg]).map(v=>{const item=pick(v);if(!item)throw Error('Choose among its items.');return item.value;});
    ok=commit(entry,kind==='listBox'?'selectedValues':'checkedValues',values,[['selectedIndexChanged',{selectedValues:values}]]);
   }
   else if(kind==='checkBox'||kind==='radioButton'){if(typeof arg!=='boolean')throw Error('Give true or false.');ok=commit(entry,'checked',arg,[['checkedChanged',{checked:arg}]]);}
   else if(kind==='dateTimePicker')ok=commit(entry,'value',arg==null||arg===''?null:String(arg),[['valueChanged',{}]]);
   else if(kind==='tabControl'){const index=Number(arg);if(!Number.isInteger(index)||index<0||index>=(doc.tabPages||[]).length)throw Error('Give a tab index.');ok=commit(entry,'selectedIndex',index,[['selectedIndexChanged',{selectedIndex:index}]]);}
   if(ok===false)throw Error(stateOf(name).error||'That value was refused.');
   return details(entry);
  }};
 view();
 return ()=>{host._controlRender=null;host._aiControls=null;for(const timer of timers.values())clearTimeout(timer);};
}

for(const kind of KINDS)registerRenderer({id:VOCABULARY.renderers[kind],version:VERSION,features:['events','bindings','styles','themes'],
 render(value,ctx){return formHTML(value,{...ctx,fieldFormats:value.fieldFormats||ctx.fieldFormats||{}}).html;},
 mount:mountForm});
