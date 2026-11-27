/** The table control (`phemacast:control.table` 1.0.0), after Windows Forms' DataGridView.
 * Host-installed renderer: the Phema supplies only data (phemacast/core/controls.py checks it). Its events run the
 * declarative actions; this module never evaluates anything a document supplies. Actions that reach the Terminal
 * travel as DOM events the Terminal handles: `phemacast:control-parameters` (page values) and
 * `phemacast:control-action` (run or refresh a reference, show a message, actions between panels). */
import {registerRenderer} from './composition-renderers.js';
import {LIMITS,esc,TOKENS,NAME,resolve,css,parseValue,validate,eventActions,plan,states,overrides,placeOf,keyOf,controlState,apply,restore} from './control-runtime.js';
export {pointer,resolve,css,parseValue,validate,eventActions,plan} from './control-runtime.js';

export const ID='phemacast:control.table',VERSION='1.0.0';
// Defaults where the Phema says nothing: a read-only list that selects whole rows.
export const DEFAULTS={readOnly:true,selectionMode:'fullRowSelect',multiSelect:false,editMode:'editOnKeystroke',columnHeadersVisible:true,rowHeadersVisible:false,allowUserToResizeColumns:true,allowUserToOrderColumns:false,allowUserToAddRows:false,allowUserToDeleteRows:false,autoSizeColumnsMode:'displayedCells',cellBorderStyle:'singleHorizontal',clipboardCopyMode:'enableWithoutHeaderText',showCellToolTips:true,enabled:true,visible:true,theme:'terminal'};

/** The rows a data source holds, and the columns it names when it names them. */
export function rowsOf(source,limit=LIMITS.rows){
 let rows=[],columns=null;
 if(Array.isArray(source))rows=source;
 else if(source&&typeof source==='object'){
  if(Array.isArray(source.rows)){rows=source.rows;if(Array.isArray(source.columns))columns=source.columns;}
  else if(Array.isArray(source.items))rows=source.items;
  else rows=[source];
 }
 rows=rows.slice(0,Math.min(limit,LIMITS.rows)).map(row=>row&&typeof row==='object'&&!Array.isArray(row)?row:{value:row});
 return {rows,columns};
}

/** The columns a table shows, in display order: the Phema's own, or generated from the data (autoGenerateColumns). */
export function columnsOf(doc,data){
 const declared=Array.isArray(doc.columns)?doc.columns.slice(0,LIMITS.columns):[];
 let columns=declared.map((column,index)=>({...column,key:column.dataPropertyName||column.name,name:column.name||column.dataPropertyName,index}));
 if(!columns.length||doc.autoGenerateColumns===true){
  const known=new Set(columns.map(c=>c.key));
  const generated=data.columns?data.columns.map(c=>({key:c.key,headerText:c.label||c.key})):[...new Set(data.rows.slice(0,50).flatMap(row=>Object.keys(row)))].map(key=>({key}));
  for(const column of generated)if(column.key&&!known.has(column.key)&&columns.length<LIMITS.columns)columns.push({...column,name:column.key,dataPropertyName:column.key,index:columns.length});
 }
 columns=columns.filter(column=>column.visible!==false);
 return columns.map((column,i)=>({...column,order:Number.isInteger(column.displayIndex)?column.displayIndex:i})).sort((a,b)=>a.order-b.order||a.index-b.index);
}

export function matches(row,when,scope){
 const left=row?.[when.field],right=resolve(when.value,scope);
 switch(when.op){
  case 'null':return left===null||left===undefined;
  case 'notNull':return left!==null&&left!==undefined;
  case '=':return left===right||String(left)===String(right);
  case '!=':return !(left===right||String(left)===String(right));
 }
 if(left===null||left===undefined||right===null||right===undefined)return false;
 const a=typeof left==='number'?left:Number(left),b=typeof right==='number'?right:Number(right);
 const [x,y]=Number.isNaN(a)||Number.isNaN(b)?[String(left),String(right)]:[a,b];
 return when.op==='<'?x<y:when.op==='<='?x<=y:when.op==='>'?x>y:when.op==='>='?x>=y:false;
}

/** A cell's style as DataGridView inherits it: table default, rows, alternating rows, column, then each rule met. */
export function cellStyle(doc,column,row,rowIndex,scope){
 const style={...doc.defaultCellStyle,...doc.rowsDefaultCellStyle,...(rowIndex%2?doc.alternatingRowsDefaultCellStyle:null),...column.defaultCellStyle};
 for(const rule of Array.isArray(doc.cellStyleRules)?doc.cellStyleRules.slice(0,LIMITS.styleRules):[])
  if((!rule.columns||rule.columns.includes(column.name))&&rule.when&&matches(row,rule.when,scope))Object.assign(style,rule.style);
 return style;
}
/** Rows in display order: sorted by a column, numbers by value, text by locale, empty cells last. */
export function sortRows(entries,key,order){
 if(!key||!['ascending','descending'].includes(order))return entries;
 const sign=order==='descending'?-1:1;
 return [...entries].sort((a,b)=>{
  const x=a.row[key],y=b.row[key];
  if(x===y)return a.index-b.index;
  if(x===null||x===undefined)return 1;if(y===null||y===undefined)return -1;
  if(typeof x==='number'&&typeof y==='number')return sign*(x-y);
  return sign*String(x).localeCompare(String(y),undefined,{numeric:true});
 });
}

function itemsOf(column,scope){
 const source=column.items??resolve(column.dataSource,scope);
 const {rows}=rowsOf(Array.isArray(source)?source:source&&typeof source==='object'?source:[],LIMITS.items);
 return rows.map(row=>Object.hasOwn(row,'value')&&Object.keys(row).length===1?{value:row.value,text:row.value}:{value:column.valueMember?row[column.valueMember]:row.value??row.id,text:column.displayMember?row[column.displayMember]:row.text??row.name??row.value});
}

/** Everything the table draws, from the panel's value: {control, parameters, results, own}. */
export function model(value,overrides={},state={}){
 const doc={...DEFAULTS,...value.control,...overrides};
 const scope={parameters:value.parameters||{},results:value.results||{},links:value.links,panels:value.panels,opened:value.opened,agents:value.agents,controlState:state.controlState};
 const source=doc.dataSource!==undefined?resolve(doc.dataSource,scope):value.own?(value.results||{})[value.own]:undefined;
 const data=rowsOf(source,Number.isInteger(doc.rowLimit)?doc.rowLimit:LIMITS.rows);
 const rows=data.rows.map((row,index)=>({index,row:state.edits?.has(index)?{...row,...state.edits.get(index)}:row})).filter(entry=>!state.deleted?.has(entry.index));
 for(const [i,row] of (state.added||[]).entries())rows.push({index:data.rows.length+i,row,added:true});
 let columns=columnsOf(doc,data);
 if(state.order?.length)columns=[...columns].sort((a,b)=>{const x=state.order.indexOf(a.name),y=state.order.indexOf(b.name);return (x<0?999:x)-(y<0?999:y);});
 const sortedColumn=state.sort?state.sort.column:doc.sortedColumn,sortOrder=state.sort?state.sort.order:doc.sortOrder;
 const sortKey=columns.find(c=>c.name===sortedColumn)?.key;
 return {doc,scope,columns,rows:sortRows(rows,sortKey,sortOrder),sortedColumn,sortOrder,dataError:source!==undefined&&source!==null&&typeof source!=='object'};
}

const editable=(doc,column)=>doc.enabled!==false&&doc.readOnly!==true&&column.readOnly!==true&&['textBox','checkBox','comboBox',undefined].includes(column.columnType);
function cellHTML(m,column,entry,displayIndex,ctx,state){
 const {doc,scope}=m,value=entry.row[column.key],style=cellStyle(doc,column,entry.row,displayIndex,scope);
 const format=style.format||ctx.fieldFormats?.[column.key];
 const empty=value===null||value===undefined;
 const shown=empty?(style.nullValue??''):(ctx.formatValue?ctx.formatValue(value,format):value);
 const kind=column.columnType||'textBox',edit=editable(doc,column);
 const current=state.current&&state.current.index===entry.index&&state.current.column===column.name;
 const error=state.errors?.get(entry.index+'|'+column.name);
 const tip=error?` title="${esc(ctx.translate?ctx.translate(error):error)}"`:doc.showCellToolTips&&!empty?` title="${esc(typeof value==='object'?JSON.stringify(value):value)}"`:'';
 let body;
 if(kind==='checkBox')body=`<input type="checkbox" data-cell-check ${value===true?'checked':''} ${edit?'':'disabled'} aria-label="${esc(column.headerText||column.name)}">`;
 else if(kind==='button')body=`<button type="button" class="control-cell-button" data-cell-content>${column.useColumnTextForButtonValue?(ctx.label||esc)(String(column.text||'')):esc(shown)}</button>`;
 else if(kind==='link')body=empty?'':`<button type="button" class="control-cell-link" data-cell-content>${esc(shown)}</button>`;
 else if(kind==='comboBox'){const item=itemsOf(column,scope).find(item=>item.value===value||String(item.value)===String(value));body=esc(item?item.text:shown);}
 else body=esc(shown);
 const numeric=typeof value==='number'&&!style.alignment;
 return `<td data-column="${esc(column.name)}" class="${numeric?'control-number':''}${current?' control-current':''}${error?' control-error':''}${column.frozen?' control-frozen':''}"${tip}${error?' aria-invalid="true"':''} style="${css(style)}">${body}</td>`;
}

/** The table's HTML for one state. */
export function tableHTML(m,ctx,state={}){
 const {doc,columns,rows}=m;
 if(doc.visible===false)return '<div class="phema-control" hidden></div>';
 const label=ctx.label||esc,say=key=>esc(ctx.translate?ctx.translate(key):key),theme=doc.theme&&doc.theme!=='terminal'?` data-control-theme="${esc(doc.theme)}"`:'';
 const root=css({backColor:doc.backColor,foreColor:doc.foreColor,font:doc.font,padding:doc.padding});
 const fill=doc.autoSizeColumnsMode==='fill',weights=columns.reduce((sum,c)=>sum+(c.fillWeight||100),0);
 const width=column=>fill?`width:${((column.fillWeight||100)/weights*100).toFixed(2)}%`:Number.isInteger(column.width)?`width:${column.width}px`:'';
 const header=doc.columnHeadersVisible===false?'':`<thead><tr>${doc.rowHeadersVisible?'<th class="control-row-header" aria-hidden="true"></th>':''}${columns.map(column=>{
  const sorted=m.sortedColumn===column.name?m.sortOrder:'none';
  const sortable=column.sortMode!=='notSortable';
  return `<th data-column="${esc(column.name)}" class="${column.frozen?'control-frozen':''}" aria-sort="${sorted==='ascending'?'ascending':sorted==='descending'?'descending':'none'}" style="${[width(column),Number.isInteger(column.minimumWidth)?`min-width:${column.minimumWidth}px`:'',css(doc.columnHeadersDefaultCellStyle)].filter(Boolean).join(';')}"${column.toolTipText?` title="${say(column.toolTipText)}"`:''}${doc.allowUserToOrderColumns?' draggable="true"':''}><div class="control-header${doc.allowUserToResizeColumns!==false&&column.resizable!==false?' control-resizable':''}">${sortable?`<button type="button" data-header>${label(String(column.headerText??column.name))}${sorted==='ascending'?' ▲':sorted==='descending'?' ▼':''}</button>`:`<span data-header>${label(String(column.headerText??column.name))}</span>`}</div></th>`;}).join('')}</tr></thead>`;
 const selected=state.selected||new Set();
 const body=rows.map((entry,i)=>`<tr data-row="${entry.index}" class="${selected.has(entry.index)?'control-selected':''}${entry.added?' control-added':''}" aria-selected="${selected.has(entry.index)}">${doc.rowHeadersVisible?`<th class="control-row-header" data-row-header scope="row">${selected.has(entry.index)?'▶':''}</th>`:''}${columns.map(column=>cellHTML(m,column,entry,i,ctx,state)).join('')}</tr>`).join('');
 const add=doc.allowUserToAddRows&&doc.enabled!==false&&doc.readOnly!==true?`<tfoot><tr><td colspan="${columns.length+(doc.rowHeadersVisible?1:0)}"><button type="button" class="control-add-row" data-add-row>${label('Add row')}</button></td></tr></tfoot>`:'';
 const caption=doc.text?`<caption>${label(String(doc.text))}</caption>`:'';
 const empty=!rows.length?`<p class="control-empty">${label(m.dataError?'This data can’t be shown as a table.':'No rows.')}</p>`:'';
 return `<div class="phema-control control-table borders-${esc(doc.cellBorderStyle)}${doc.enabled===false?' control-disabled':''}"${theme} data-control-name="${esc(doc.name||'')}" data-control="${esc(doc.name||'')}" style="${root}${TOKENS[doc.gridColor]?`;--control-grid:var(${TOKENS[doc.gridColor]})`:''}"${doc.toolTipText?` title="${say(doc.toolTipText)}"`:''}${doc.enabled===false?' aria-disabled="true"':''}><div class="control-scroll" tabindex="${Number.isInteger(doc.tabIndex)?doc.tabIndex:0}"><table class="${fill?'control-fill':''}" role="grid" aria-multiselectable="${doc.multiSelect===true}">${caption}${header}<tbody>${body}</tbody>${add}</table></div>${empty}</div>`;
}

// ---- In the page: state, events and actions. -------------------------------------------------------------------
export function mountTable(host,value,context){
 const ctx={...context,fieldFormats:value.fieldFormats||{}};
 const name=value.control?.name||'',key=keyOf(host,name),{window}=placeOf(host);
 const state=states.get(key)||{selected:new Set(),edits:new Map(),deleted:new Set(),added:[],errors:new Map(),current:null,sort:null,order:null,seen:null,bound:null};
 states.set(key,state);host._controlNames=new Set([name]);
 state.clear=()=>{state.selected.clear();state.current=null;};
 let m;
 const view=()=>{
  m=model(value,overrides.get(window+'|'+name)||{},{...state,controlState:controlState(window)});
  // A redraw keeps where the viewer was: the scroll position and the keyboard focus.
  const scroller=host.querySelector('.control-scroll'),top=scroller?.scrollTop||0,left=scroller?.scrollLeft||0;
  const focused=host.contains(document.activeElement)&&!document.activeElement.closest('[data-cell-editor]');
  host.innerHTML=tableHTML(m,ctx,state);
  const next=host.querySelector('.control-scroll');
  if(next){next.scrollTop=top;next.scrollLeft=left;if(focused)next.focus({preventScroll:true});}
  for(const cell of host.querySelectorAll('.control-frozen')){let left=0,node=cell.previousElementSibling;while(node){if(node.classList.contains('control-frozen'))left+=node.offsetWidth;node=node.previousElementSibling;}cell.style.left=left+'px';}
  const frozen=[...host.querySelectorAll('thead th.control-frozen,tbody tr:first-child td.control-frozen')].slice(0,LIMITS.columns),width=Math.max(0,...frozen.map(cell=>cell.offsetLeft+cell.offsetWidth));
  if(next)next.style.scrollPaddingLeft=width+'px';
 };
 const rowOf=index=>m.rows.find(entry=>entry.index===index)?.row;
 const selectedRows=()=>m.rows.filter(entry=>state.selected.has(entry.index)).slice(0,500).map(entry=>entry.row);
 state.read=property=>({rows:m.rows.slice(0,500).map(entry=>entry.row),selectedRows:selectedRows(),currentRow:state.current?rowOf(state.current.index)??null:null,
  currentCell:state.current?{rowIndex:m.rows.findIndex(entry=>entry.index===state.current.index),columnName:state.current.column,value:rowOf(state.current.index)?.[m.columns.find(c=>c.name===state.current.column)?.key]}:null,
  sortedColumn:m.sortedColumn??null,sortOrder:m.sortOrder??'none'})[property];
 host._controlRender=view;
 const details=(entry,column,extra={})=>({rowIndex:entry?m.rows.indexOf(entry):-1,columnName:column?.name??null,value:entry&&column?entry.row[column.key]:undefined,row:entry?.row??null,rows:selectedRows(),sortedColumn:m.sortedColumn??null,sortOrder:m.sortOrder??'none',...extra});
 // One gesture: run its events' actions, then save the states the Phema binds to page values.
 const run=(fired,boundChanged=false)=>{
  if(m.doc.enabled===false)return;
  const actions=fired.flatMap(([event,detail])=>eventActions(m.doc,event,detail,m.scope));
  const result=plan(actions,value.parameters||{});
  // A bound state is saved when it changes, never just because the table was drawn.
  if(boundChanged)for(const [stateName,target] of Object.entries(m.doc.dataBindings||{})){const param=String(target?.$param||'').slice(1);if(NAME.test(param)){const next=state.read(stateName)??null,seen=JSON.stringify(next);if(state.bound[param]!==seen){state.bound[param]=seen;result.values[param]=next;}}}
  apply(host,result);
 };
 const select=(entry,column,{toggle=false,range=false}={})=>{
  const before=state.current?.index,fired=[],mode=m.doc.selectionMode,was=[...state.selected].join(',');
  if(mode==='cellSelect'||mode==='fullRowSelect'||mode==='rowHeaderSelect'){
   if(m.doc.multiSelect&&toggle){state.selected.has(entry.index)?state.selected.delete(entry.index):state.selected.add(entry.index);}
   else if(m.doc.multiSelect&&range&&before!==undefined){const a=m.rows.findIndex(e=>e.index===before),b=m.rows.indexOf(entry);for(const e of m.rows.slice(Math.min(a,b),Math.max(a,b)+1))state.selected.add(e.index);}
   else{state.selected.clear();state.selected.add(entry.index);}
  }
  const target=column?.name??m.columns[0]?.name,changed=before!==entry.index||state.current?.column!==target,selection=was!==[...state.selected].join(',');
  // Nothing new: no redraw (a double click must find the cell it started on) and no events.
  if(!changed&&!selection)return fired;
  if(before!==undefined&&before!==entry.index)fired.push(['rowLeave',details(m.rows.find(e=>e.index===before),null)]);
  state.current={index:entry.index,column:target};
  view();
  if(before!==entry.index)fired.push(['rowEnter',details(entry,column)]);
  if(selection)fired.push(['selectionChanged',details(entry,column)]);
  if(changed)fired.push(['currentCellChanged',details(entry,column)]);
  return fired;
 };
 const commit=(entry,column,raw)=>{
  const parsed=parseValue(raw,column.valueType||(typeof entry.row[column.key]==='number'?'number':undefined));
  const message=parsed.error||validate(parsed.value,column.validation);
  const where=entry.index+'|'+column.name;
  if(message){
   // The editor stays open on the refused value: mark the cell where it is, without a redraw.
   state.errors.set(where,message);
   const td=host.querySelector(`tr[data-row="${entry.index}"] td[data-column="${CSS.escape(column.name)}"]`);
   if(td){td.classList.add('control-error');td.setAttribute('aria-invalid','true');td.title=ctx.translate?ctx.translate(message):message;td.querySelector('[data-cell-editor]')?.focus();}
   run([['cellValidating',details(entry,column,{valid:false,message})],['dataError',details(entry,column,{message})]]);
   return false;
  }
  state.errors.delete(where);
  const oldValue=entry.row[column.key];
  if(oldValue===parsed.value){view();return true;}
  state.edits.set(entry.index,{...(state.edits.get(entry.index)||{}),[column.key]:parsed.value});
  view();
  const now=m.rows.find(e=>e.index===entry.index)||entry;
  run([['cellValueChanged',details(now,column,{oldValue})],['cellEndEdit',details(now,column)]],true);
  return true;
 };
 const edit=(td,entry,column,initial)=>{
  if(!editable(m.doc,column)||column.columnType==='checkBox')return;
  const items=column.columnType==='comboBox'?itemsOf(column,m.scope):null;
  const old=entry.row[column.key];
  td.innerHTML=items?`<select data-cell-editor>${items.map(item=>`<option value="${esc(JSON.stringify(item.value))}" ${item.value===old?'selected':''}>${esc(item.text)}</option>`).join('')}</select>`:`<input data-cell-editor value="${esc(initial??old??'')}" ${column.validation?.maxLength?`maxlength="${column.validation.maxLength}"`:''}>`;
  const input=td.querySelector('[data-cell-editor]');input.focus();
  let done=false;
  const finish=save=>{if(done)return;done=true;if(!save){view();return;}const raw=items?JSON.parse(input.value):input.value;if(!commit(entry,column,raw))done=false;};
  input.addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();finish(true);}if(event.key==='Escape'){event.preventDefault();finish(false);}event.stopPropagation();});
  input.addEventListener('blur',()=>finish(true));
  if(items)input.addEventListener('change',()=>finish(true));
 };
 const locate=target=>{
  const td=target.closest('td[data-column],th[data-row-header]'),tr=target.closest('tr[data-row]');
  const entry=tr?m.rows.find(e=>e.index===Number(tr.dataset.row)):null;
  const column=td?.dataset.column?m.columns.find(c=>c.name===td.dataset.column):null;
  return {td,entry,column};
 };
 host.addEventListener('click',event=>{
  if(m.doc.enabled===false)return;
  const th=event.target.closest('th[data-column]');
  if(th&&event.target.closest('[data-header]')){
   const column=m.columns.find(c=>c.name===th.dataset.column);if(!column)return;
   const fired=[['columnHeaderMouseClick',details(null,column)]];
   if(column.sortMode!=='notSortable'&&column.sortMode!=='programmatic'){
    const order=m.sortedColumn===column.name&&m.sortOrder==='ascending'?'descending':'ascending';
    state.sort={column:column.name,order};view();fired.push(['sorted',details(null,column)]);
   }
   run(fired,true);return;
  }
  if(event.target.closest('[data-add-row]')){state.added.push({});view();run([['userAddedRow',details(m.rows.at(-1),null)]],true);return;}
  const {td,entry,column}=locate(event.target);if(!entry)return;
  const fired=[];
  if(event.target.closest('[data-row-header]')||m.doc.selectionMode!=='rowHeaderSelect')fired.push(...select(entry,column,{toggle:event.metaKey||event.ctrlKey,range:event.shiftKey}));
  if(column)fired.push(['cellClick',details(entry,column)]);
  if(column&&event.target.closest('[data-cell-content]'))fired.push(['cellContentClick',details(entry,column)]);
  fired.push(['click',details(entry,column)]);
  const check=event.target.closest('[data-cell-check]');
  run(fired,true);
  if(check&&column&&editable(m.doc,column))commit(entry,column,check.checked);
  else if(td&&column&&m.doc.editMode==='editOnEnter'&&!event.target.closest('button'))edit(host.querySelector(`tr[data-row="${entry.index}"] td[data-column="${CSS.escape(column.name)}"]`),entry,column);
 });
 host.addEventListener('dblclick',event=>{
  const {entry,column}=locate(event.target);if(!entry||m.doc.enabled===false)return;
  run([['cellDoubleClick',details(entry,column)],['doubleClick',details(entry,column)]]);
  if(column&&m.doc.editMode!=='editProgrammatically')edit(host.querySelector(`tr[data-row="${entry.index}"] td[data-column="${CSS.escape(column.name)}"]`),m.rows.find(e=>e.index===entry.index),column);
 });
 host.addEventListener('keydown',event=>{
  if(m.doc.enabled===false||event.target.closest('[data-cell-editor]'))return;
  const current=state.current?m.rows.findIndex(e=>e.index===state.current.index):-1;
  const column=m.columns.find(c=>c.name===state.current?.column)||m.columns[0];
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){
   event.preventDefault();const next=m.rows[Math.max(0,Math.min(m.rows.length-1,current+(event.key==='ArrowDown'?1:-1)))];
   if(next)run(select(next,column),true);return;
  }
  if(event.key==='ArrowLeft'||event.key==='ArrowRight'){
   if(current<0)return;event.preventDefault();const i=m.columns.indexOf(column),to=m.columns[Math.max(0,Math.min(m.columns.length-1,i+(event.key==='ArrowRight'?1:-1)))];
   run(select(m.rows[current],to),true);return;
  }
  const entry=m.rows[current];
  if((event.key==='Delete'||event.key==='Backspace')&&m.doc.allowUserToDeleteRows&&m.doc.readOnly!==true&&state.selected.size){
   event.preventDefault();const rows=selectedRows();
   run([['userDeletingRow',details(entry,null)]]);
   if(!globalThis.confirm?.((ctx.translate||(k=>k))(rows.length===1?'Delete this row?':'Delete the selected rows?')))return;
   for(const index of state.selected)state.deleted.add(index);state.selected.clear();state.current=null;view();
   run([['userDeletedRow',details(null,null,{rows})]],true);return;
  }
  if(event.key==='Enter'||event.key==='Escape'){
   const fired=[['keyDown',details(entry,column,{key:event.key})]];
   if(event.key==='Enter'&&entry&&column&&['button','link'].includes(column.columnType))fired.push(['cellContentClick',details(entry,column)]);
   run(fired);
   if(event.key==='Enter'&&entry&&column&&m.doc.editMode!=='editProgrammatically')edit(host.querySelector(`tr[data-row="${entry.index}"] td[data-column="${CSS.escape(column.name)}"]`),entry,column);
   return;
  }
  if(event.key==='F2'&&entry&&column){event.preventDefault();edit(host.querySelector(`tr[data-row="${entry.index}"] td[data-column="${CSS.escape(column.name)}"]`),entry,column);return;}
  if(m.doc.editMode==='editOnKeystroke'&&entry&&column&&event.key.length===1&&!event.metaKey&&!event.ctrlKey&&!event.altKey){event.preventDefault();edit(host.querySelector(`tr[data-row="${entry.index}"] td[data-column="${CSS.escape(column.name)}"]`),entry,column,event.key);}
 });
 host.addEventListener('focusin',event=>{if(!host.contains(event.relatedTarget))run([['enter',details(null,null)]]);});
 host.addEventListener('focusout',event=>{if(!host.contains(event.relatedTarget))run([['leave',details(null,null)]]);});
 host.addEventListener('copy',event=>{
  if(m.doc.clipboardCopyMode==='disable'||!state.selected.size||event.target.closest('[data-cell-editor]'))return;
  const lines=selectedRows().map(row=>m.columns.map(c=>String(row[c.key]??'')).join('\t'));
  if(m.doc.clipboardCopyMode==='enableAlwaysIncludeHeaderText')lines.unshift(m.columns.map(c=>c.headerText??c.name).join('\t'));
  event.clipboardData?.setData('text/plain',lines.join('\n'));event.preventDefault();
 });
 let dragged=null;
 host.addEventListener('dragstart',event=>{const th=event.target.closest('th[data-column]');if(th&&m.doc.allowUserToOrderColumns){dragged=th.dataset.column;event.dataTransfer?.setData('text/plain',dragged);}});
 host.addEventListener('dragover',event=>{if(dragged&&event.target.closest('th[data-column]'))event.preventDefault();});
 host.addEventListener('drop',event=>{
  const th=event.target.closest('th[data-column]');if(!dragged||!th)return;event.preventDefault();
  const names=m.columns.map(c=>c.name),from=names.indexOf(dragged),to=names.indexOf(th.dataset.column);
  if(from>=0&&to>=0&&from!==to){names.splice(to,0,names.splice(from,1)[0]);state.order=names;view();}
  dragged=null;
 });
 view();
 if(!state.bound){state.bound={};for(const [stateName,target] of Object.entries(m.doc.dataBindings||{})){const param=String(target?.$param||'').slice(1);if(NAME.test(param))state.bound[param]=JSON.stringify(state.read(stateName)??null);}}
 // Data arrived or changed: dataBindingComplete once per distinct data, never again for the same rows.
 const signature=JSON.stringify([m.rows.length,m.rows.slice(0,20).map(e=>e.row)]);
 if(state.seen!==signature){state.seen=signature;run([[m.dataError?'dataError':'dataBindingComplete',details(null,null,m.dataError?{message:'This data can’t be shown as a table.'}:{})]],true);}
 // An AI app the window approved (MCP `controls` / `use_control`): read the table, select a row, or set an editable
 // cell, through the same selection, commit and events a person's click or edit takes.
 host._aiControls={
  list:()=>[{control:name,kind:'table',enabled:m.doc.enabled!==false,readOnly:m.doc.readOnly===true,rows:m.rows.length,
   columns:m.columns.slice(0,50).map(c=>({name:c.name,header:String(c.headerText??c.name).slice(0,100),editable:editable(m.doc,c)})),
   selectedRows:[...state.selected].slice(0,50),events:Object.keys(m.doc.events||{}),settable:m.doc.enabled!==false}],
  use:(control,op,arg)=>{
   if(control!==name)throw Error('This panel has no control by that name; controls lists them.');
   if(m.doc.enabled===false)throw Error('That control is disabled now.');
   const row=Number(arg?.row),entry=Number.isInteger(row)?m.rows[row]:null;if(!entry)throw Error('Give a row index from 0 to '+Math.max(0,m.rows.length-1)+'.');
   const column=arg?.column==null?null:m.columns.find(c=>c.name===arg.column);if(arg?.column!=null&&!column)throw Error('That table has no column by that name.');
   if(op==='select_row'){const fired=select(entry,column);if(column)fired.push(['cellClick',details(entry,column)]);fired.push(['click',details(entry,column)]);run(fired,true);return details(entry,column);}
   if(op==='set_cell'){if(!column||!editable(m.doc,column))throw Error('That cell is not editable.');if(!commit(entry,column,arg.value))throw Error(state.errors.get(entry.index+'|'+column.name)||'That value was refused.');return details(m.rows.find(e=>e.index===entry.index)||entry,column);}
   throw Error('Select a row, or set an editable cell.');
  }};
 return ()=>{host._controlRender=null;host._aiControls=null;};
}

registerRenderer({id:ID,version:VERSION,features:['events','editing','styles','themes'],
 render(value,ctx){return tableHTML(model(value),{...ctx,fieldFormats:value.fieldFormats||ctx.fieldFormats||{}});},
 mount:mountTable});
