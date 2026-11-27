/** SplitContainer, after Windows Forms' SplitContainer: two panels of a page side by side, with a border the person
 * drags and a panel they can hide to a strip. The Phema declares it (`phemacast:split-containers` in its layout
 * document's extensions, checked by phemacast/core/split_containers.py); the window keeps where the person left the
 * border. Geometry and state only: which columns move and how wide they are. The host draws the border. */
export const SPLIT_EXTENSION='phemacast:split-containers';
const NAME=/^[A-Za-z][A-Za-z0-9_-]{0,63}$/;
const STATES=['','panel1','panel2'];
const whole=value=>typeof value==='number'&&Math.abs(value-Math.round(value))<1e-7;
const share=value=>Math.min(.95,Math.max(.05,value));
const pixels=value=>Number.isInteger(value)&&value>=0&&value<=2000?value:120;
const fr=value=>Number(Math.max(0,value).toFixed(4));

/** The declarations as they reach a host: on the entry, or inside a composition's layout extension. */
export function declaredSplits(entry){
 const found=entry?.extensions?.[SPLIT_EXTENSION]||entry?.extensions?.['phemacast:layout']?.extensions?.[SPLIT_EXTENSION];
 return Array.isArray(found)?found:[];
}

/** The page's split containers that fit its grid now; any that do not are skipped and the grid shows as it is. */
export function splitContainers(entry,layout){
 if(layout?.columns!==12||layout.snapToGrid===false)return [];
 const surfaces=new Map((layout.children||[]).filter(node=>!node.tabId&&node.position).map(node=>[node.id,node]));
 const used=new Set(),spans=[],names=new Set(),found=[];
 for(const split of declaredSplits(entry).slice(0,4)){
  if(!split||typeof split!=='object'||!NAME.test(split.name||'')||names.has(split.name)||(split.orientation??'vertical')!=='vertical')continue;
  const one=surfaces.get(split.panel1),two=surfaces.get(split.panel2);if(!one||!two||one===two||used.has(one.id)||used.has(two.id))continue;
  const a=one.position,b=two.position;
  if(![a.column,a.columnSpan,a.row,a.rowSpan,b.column,b.columnSpan,b.row,b.rowSpan].every(whole))continue;
  if(a.row!==b.row||a.rowSpan!==b.rowSpan||Math.round(a.column+a.columnSpan)!==Math.round(b.column))continue;
  const from=Math.round(a.column),to=Math.round(b.column+b.columnSpan)-1;
  if(spans.some(([start,end])=>from<=end&&start<=to))continue;
  names.add(split.name);used.add(one.id);used.add(two.id);spans.push([from,to]);
  const first=Math.round(a.columnSpan),second=Math.round(b.columnSpan),declared=Number(split.splitterDistance);
  found.push({name:split.name,panel1:one.id,panel2:two.id,title1:one.title||'',title2:two.title||'',from,first,second,
   row:Math.round(a.row),rowSpan:Math.round(a.rowSpan),
   distance:share(Number.isFinite(declared)&&declared>=5&&declared<=95?declared/100:first/(first+second)),
   panel1MinSize:pixels(split.panel1MinSize),panel2MinSize:pixels(split.panel2MinSize),fixed:split.isSplitterFixed===true,
   collapsed:split.panel1Collapsed===true?'panel1':split.panel2Collapsed===true?'panel2':''});
 }
 return found;
}

/** Where the border is for one window: what the person left, else the Phema's starting point. */
export function splitState(split,kept){
 const distance=typeof kept?.distance==='number'&&Number.isFinite(kept.distance)?share(kept.distance):split.distance;
 const collapsed=STATES.includes(kept?.collapsed)?kept.collapsed:split.collapsed;
 return {distance,collapsed};
}

/** The grid's columns with each split's panels at their widths ('' when the page has no split). Columns outside the
 * splits keep their share; a hidden panel leaves a STRIP wide enough for the border's show button. */
export const STRIP='14px';
export function splitColumns(splits,kept={},override={}){
 if(!splits.length)return '';
 const columns=Array(12).fill('minmax(0,1fr)'),track=value=>`minmax(0,${fr(value)}fr)`;
 for(const split of splits){
  const state=override[split.name]||splitState(split,kept?.[split.name]),total=split.first+split.second;
  const one=state.collapsed==='panel1'?0:state.collapsed==='panel2'?total:state.distance*total,two=total-one;
  for(let i=0;i<split.first;i++)columns[split.from-1+i]=state.collapsed==='panel1'?(i?track(0):STRIP):track(one/split.first);
  for(let i=0;i<split.second;i++)columns[split.from-1+split.first+i]=state.collapsed==='panel2'?(i?track(0):STRIP):track(two/split.second);
 }
 return columns.join(' ');
}

/** Style added after the grid's own: the moved columns (the host's stylesheet reads --layout-columns). */
export function splitStyle(splits,kept,override){
 const columns=splitColumns(splits,kept,override);
 return columns?`;--layout-columns:${columns};grid-template-columns:${columns}`:'';
}

/** The panel's share for a pointer at x over the two panels' box, kept inside both panels' minimum widths. */
export function shareAt(split,x,left,width){
 if(!(width>0))return split.distance;
 let low=split.panel1MinSize/width,high=1-split.panel2MinSize/width;
 if(low>high)low=high=(low+high)/2;  // a window too narrow for both minimums splits the shortfall
 return share(Math.min(high,Math.max(low,(x-left)/width)));
}

/** A window's kept states, cleaned the way a saved workspace keeps them. */
export function normalizeSplits(value){
 if(!value||typeof value!=='object'||Array.isArray(value))return {};
 return Object.fromEntries(Object.entries(value).filter(([name,state])=>NAME.test(name)&&state&&typeof state==='object'
  &&typeof state.distance==='number'&&Number.isFinite(state.distance)&&STATES.includes(state.collapsed??''))
  .slice(0,4).map(([name,state])=>[name,{distance:share(state.distance),collapsed:state.collapsed||''}]));
}
