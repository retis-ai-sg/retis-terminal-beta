import {mountCompactComposition} from './compact-composition.js';
import {permittedResource,boundedAsset} from './media-resource-policy.js';
import {customHTML} from './composition-renderers.js';
import {interactionResultHTML} from './interaction-result.js';
import {structuredFields} from './structured-operation-fields.js';
/** Generic, declarative media renderers. No markup, scripts or plugin code from Phema. */
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const MEDIA_TYPES=['text','image','audio','video','scene','interactive','viewer'];
export function safeMediaURL(value){try{const u=new URL(value);return u.protocol==='https:'&&!u.username&&!u.password?u.href:null;}catch{return null;}}
export function mediaHTML(kind,value,{fallback='Media unavailable',label=x=>x,uiLabel=null,uiAttribute=null,resolveURL=x=>x,resourcePolicy=null,authenticatedLocal=false}={}){
 const text=uiLabel||((key)=>escape(label(key))),attr=uiAttribute||((name,key)=>`${name}="${escape(label(key))}"`);
 if(!value||typeof value!=='object')return `<p class="panel-note">${text(fallback)}</p>`;
 if(kind==='text')return `<div class="composition-text">${authoredText(value.text??value.title??'',text)}${safeMediaURL(value.url)?`<p><a href="${escape(safeMediaURL(value.url))}" target="_blank" rel="noopener noreferrer">${value.title?escape(value.title):text('Open source')}</a></p>`:''}</div>`;
 if(kind==='interactive')return interactiveHTML(value,text,label,attr);
 if(kind==='viewer')return viewerHTML(value,text,attr);
 if(kind==='scene'&&value.asset&&!permittedResource(value.asset.url,resourcePolicy))return `<p class="panel-note">${text('Phema permission review required')}</p>`;
 if(kind==='scene')return `<div class="composition-scene" data-scene="${escape(JSON.stringify(value))}"><canvas ${value.description?`aria-label="${escape(value.description)}"`:attr('aria-label','3D scene')}></canvas><button type="button" data-scene-play ${attr('title','Play / pause')}>▶</button><input data-scene-time type="range" min="0" max="${Number(value.timeline?.duration)||60}" step="0.01" value="0" ${attr('aria-label','Timeline')}><span data-scene-status>${escape(value.description||'')}</span></div>`;
 const url=permittedResource(value.url,resourcePolicy);
 if(!url)return `<p class="panel-note">${value.transcript?escape(value.transcript):text(fallback)}</p>`;
 if(kind==='image')return `<img class="composition-image" data-asset-url="${escape(url)}" crossorigin="anonymous" alt="${escape(value.alt||'')}" loading="lazy" referrerpolicy="no-referrer">`;
 let content='';
 const youtube=kind==='video'&&permittedResource('https://www.youtube-nocookie.com/',resourcePolicy)&&new URL(url).hostname.match(/^(?:www\.)?(?:youtube\.com|youtu\.be)$/);
 if(youtube){const u=new URL(url),parts=u.pathname.split('/').filter(Boolean),id=u.hostname==='youtu.be'?parts[0]:u.searchParams.get('v')||(['shorts','embed','live'].includes(parts[0])?parts[1]:null);content=/^[\w-]{11}$/.test(id||'')?`<iframe src="https://www.youtube-nocookie.com/embed/${id}" ${value.title?`title="${escape(value.title)}"`:attr('title','Video')} sandbox="allow-scripts allow-same-origin allow-presentation" allow="fullscreen" loading="lazy" referrerpolicy="no-referrer"></iframe>`:'';}
 else if(kind==='audio'||kind==='video')content=`<${kind} controls preload="metadata" data-playback="${escape(JSON.stringify(value.playback||{}))}" data-asset-url="${escape(resolveURL(url))}" data-authenticated-local="${authenticatedLocal?'true':'false'}" crossorigin="anonymous" ${value.poster&&permittedResource(value.poster,resourcePolicy)?`data-poster-url="${escape(resolveURL(value.poster))}"`:''}>${(Array.isArray(value.captions)?value.captions:[]).filter(t=>permittedResource(t.url,resourcePolicy)).map(t=>`<track kind="captions" data-authenticated-local="${authenticatedLocal?'true':'false'}" data-asset-url="${escape(resolveURL(t.url))}" srclang="${escape(t.language)}" label="${escape(t.label||t.language)}">`).join('')}</${kind}>`;
 return `<div class="composition-media">${content}<a href="${escape(resolveURL(url))}" target="_blank" rel="noopener noreferrer">${value.title?escape(value.title):text('Open media')}</a>${value.transcript?`<details><summary>${text('Transcript')}</summary><p>${escape(value.transcript)}</p></details>`:''}</div>`;
}
export function mountScenes(root=document){
 for(const element of root.querySelectorAll('.composition-scene:not([data-mounted])')){
  element.dataset.mounted='true';
  if(sceneAsset(element)){continue;}
  const canvas=element.querySelector('canvas'),ctx=canvas.getContext('2d');let scene;
  try{scene=JSON.parse(element.dataset.scene);}catch{continue;}
  let angle=.45,playing=false,last=0,elapsed=0,frame=null,drag=null;
  const vector=(v,fallback)=>Array.isArray(v)&&v.length===3&&v.every(n=>Number.isFinite(n)&&Math.abs(n)<=10000)?v:fallback;
  const objects=Array.isArray(scene?.objects)?scene.objects.filter(o=>o&&typeof o==='object').slice(0,100):[];
  function draw(now){
   if(!element.isConnected)return;
   if(playing)elapsed+=Math.min((now-last)/1000,.1);last=now;
   const width=Math.max(1,element.clientWidth),height=Math.max(100,element.clientHeight-28);canvas.width=width*devicePixelRatio;canvas.height=height*devicePixelRatio;canvas.style.width=width+'px';canvas.style.height=height+'px';ctx.scale(devicePixelRatio,devicePixelRatio);ctx.clearRect(0,0,width,height);
   const scale=Math.min(width,height)/8;
   const project=([x,y,z])=>[width/2+(x*Math.cos(angle)-z*Math.sin(angle))*scale,height/2+(-y+(x*Math.sin(angle)+z*Math.cos(angle))*.35)*scale];
   for(const obj of objects){
    const animated=timelineObject(obj,scene.timeline,elapsed);
    const p=vector(animated.position,[0,0,0]),s=vector(animated.size,[1,1,1]),r=vector(animated.rotation,[0,0,0]);
    const spin=Number.isFinite(obj.spin)&&Math.abs(obj.spin)<=10?obj.spin:0;
    const transform=([x,y,z])=>{const [rx,ry,rz]=[r[0],r[1]+spin*elapsed,r[2]];[y,z]=[y*Math.cos(rx)-z*Math.sin(rx),y*Math.sin(rx)+z*Math.cos(rx)];[x,z]=[x*Math.cos(ry)-z*Math.sin(ry),x*Math.sin(ry)+z*Math.cos(ry)];[x,y]=[x*Math.cos(rz)-y*Math.sin(rz),x*Math.sin(rz)+y*Math.cos(rz)];return project([p[0]+x,p[1]+y,p[2]+z]);};
    ctx.strokeStyle=/^#[0-9a-f]{6}$/i.test(obj.color||'')?obj.color:'#86bccc';ctx.lineWidth=1.3;
    if(obj.shape==='sphere'){for(const plane of [[0,1],[1,2],[0,2]]){ctx.beginPath();for(let i=0;i<=32;i++){const v=[0,0,0];v[plane[0]]=Math.cos(i/32*2*Math.PI)*s[plane[0]]/2;v[plane[1]]=Math.sin(i/32*2*Math.PI)*s[plane[1]]/2;const point=transform(v);i?ctx.lineTo(...point):ctx.moveTo(...point);}ctx.stroke();}continue;}
    if(obj.shape==='mesh'){const points=(obj.vertices||[]).slice(0,10000).map(v=>transform(v.map((x,i)=>x*s[i])));for(const face of (obj.faces||[]).slice(0,20000)){if(face.some(i=>!points[i]))continue;ctx.beginPath();face.forEach((index,i)=>i?ctx.lineTo(...points[index]):ctx.moveTo(...points[index]));ctx.closePath();ctx.stroke();}continue;}
    if(obj.shape!=='box')continue;
    const vertices=Array.from({length:8},(_,i)=>transform([((i&1)?1:-1)*s[0]/2,((i&2)?1:-1)*s[1]/2,((i&4)?1:-1)*s[2]/2]));
    for(let i=0;i<8;i++)for(const bit of [1,2,4])if(!(i&bit)){ctx.beginPath();ctx.moveTo(...vertices[i]);ctx.lineTo(...vertices[i|bit]);ctx.stroke();}
   }
   const slider=element.querySelector('[data-scene-time]');if(slider&&!slider.matches(':active'))slider.value=scene.timeline?.loop?elapsed%scene.timeline.duration:elapsed;
   if(playing&&!frame)frame=requestAnimationFrame(time=>{frame=null;draw(time);});
  }
  element.querySelector('[data-scene-play]').onclick=()=>{playing=!playing;last=performance.now();draw(last);};
  const slider=element.querySelector('[data-scene-time]');if(slider)slider.oninput=()=>{elapsed=Number(slider.value);draw(performance.now());};
  canvas.onpointerdown=e=>{drag=e.clientX;canvas.setPointerCapture(e.pointerId);};canvas.onpointermove=e=>{if(drag!==null){angle+=(e.clientX-drag)/100;drag=e.clientX;draw(performance.now());}};canvas.onpointerup=()=>{drag=null;};
  const observer=new ResizeObserver(()=>{if(element.isConnected)draw(performance.now());else observer.disconnect();});observer.observe(element);draw(performance.now());
 }
}

// A Phema's own text is shown through its UI catalog when the catalog has it, so a help note reads in the viewer's
// language; text that cannot be a catalog key (too long, or with {0}-style slots) shows as it is.
// A web page or a picture the person chooses to look at. Both live in one page setting, which the Phema's owner reads.
// The page runs in a sandbox with no access to the Terminal, and leaves no referrer behind. A site that refuses to be
// shown inside another page stays blank, so the panel offers to open it in a new tab.
const VIEWER_PARAMETER=/^[A-Za-z][A-Za-z0-9_]{0,63}$/,VIEWER_IMAGE=/^image\/(jpeg|png|webp)$/;
const viewerImage=value=>value&&typeof value==='object'&&VIEWER_IMAGE.test(value.type||'')&&typeof value.data==='string'&&/^[A-Za-z0-9+/=]{1,280000}$/.test(value.data)?
 {data:value.data,type:value.type,...(Number.isInteger(value.width)?{width:value.width}:{}),...(Number.isInteger(value.height)?{height:value.height}:{})}:null;
// A Phema to copy: its name, the key and storage it is listed by, its panels' places, and the picture the person's
// Terminal last saved of it. Only what fits is kept, so a bad value never reaches the Phema's owner.
const viewerText=(value,limit)=>typeof value==='string'&&value.trim()?value.trim().slice(0,limit):'';
const viewerCell=value=>typeof value==='number'&&Number.isFinite(value)&&value>=0&&value<=128?value:null;
function viewerPhemaValue(value){
 if(!value||typeof value!=='object'||Array.isArray(value))return null;
 const name=viewerText(value.name,200),key=viewerText(value.key,300);if(!name||!key)return null;
 const panels=(Array.isArray(value.panels)?value.panels:[]).slice(0,64).filter(panel=>panel&&typeof panel==='object').map(panel=>{
  const kept={label:viewerText(panel.label,200)};
  for(const field of ['column','row','columnSpan','rowSpan']){const cell=viewerCell(panel[field]);if(cell!==null)kept[field]=cell;}
  return kept;});
 const image=viewerImage(value.image),storage=viewerText(value.storage,300),phemaId=viewerText(value.phemaId,300);
 return {name,key,...(storage?{storage}:{}),...(phemaId?{phemaId}:{}),...(Number.isInteger(value.columns)&&value.columns>=1&&value.columns<=24?{columns:value.columns}:{}),panels,...(image?{image}:{})};
}
export function viewerSetting(value){
 const current=value&&typeof value==='object'&&!Array.isArray(value)?value:{};
 const image=viewerImage(current.image);
 const pdf=image&&current.pdf&&typeof current.pdf==='object'&&typeof current.pdf.name==='string'&&Number.isInteger(current.pdf.page)&&Number.isInteger(current.pdf.pages)&&current.pdf.page>=1&&current.pdf.page<=current.pdf.pages&&current.pdf.pages<=5000?
  {name:current.pdf.name.slice(0,120),page:current.pdf.page,pages:current.pdf.pages,...(Number.isInteger(current.pdf.size)?{size:current.pdf.size}:{})}:null;
 const phema=viewerPhemaValue(current.phema);
 return {mode:['image','phema'].includes(current.mode)?current.mode:'web',...(safeMediaURL(current.url)?{url:safeMediaURL(current.url)}:{}),...(image?{image}:{}),...(pdf?{pdf}:{}),...(phema?{phema}:{})};
}
// A Phema's panels as blocks on its grid: each where the Phema puts it, named by its title.
function viewerBlocks(phema,text){
 const columns=phema.columns||12,panels=phema.panels||[];
 const rows=Math.max(1,...panels.map(p=>(p.row||1)+(p.rowSpan||1)-1));
 const blocks=panels.map((p,index)=>{
  const column=Math.min(columns,Math.max(1,p.column||1)),span=Math.min(columns-column+1,Math.max(.5,p.columnSpan||columns));
  const style=`left:${(column-1)/columns*100}%;width:${span/columns*100}%;top:${((p.row||1)-1)/rows*100}%;height:${(p.rowSpan||1)/rows*100}%`;
  return `<div class="composition-viewer-block" style="${style}"><span>${escape(p.label||String(index+1))}</span></div>`;}).join('');
 return `<p class="composition-viewer-note">${text('Blocks')} · ${panels.length}</p><div class="composition-viewer-blocks" style="height:${Math.min(640,Math.max(160,rows*56))}px" ${attr('aria-label','Blocks')}>${blocks}</div>`;
 function attr(name,label){return `${name}="${escape(text(label))}"`;}
}
function viewerHTML(value,text,attr){
 const name=VIEWER_PARAMETER.test(value.parameter||'')?value.parameter:'';
 const current=viewerSetting(value.value),{mode,url,image,pdf,phema}=current;
 // A PDF's page is the picture; ‹ › turn its pages while the PDF is open in this window.
 const pages=pdf?`<span class="composition-viewer-pages"><button type="button" data-viewer-page="-1" ${attr('aria-label','Previous page')} ${pdf.page<=1?'disabled':''}>‹</button><small>${escape(pdf.page+' / '+pdf.pages)}</small><button type="button" data-viewer-page="1" ${attr('aria-label','Next page')} ${pdf.page>=pdf.pages?'disabled':''}>›</button></span><small class="composition-viewer-pdf" title="${escape(pdf.name)}">${escape(pdf.name)}</small>`:'';
 const option=(choice,label)=>`<option value="${choice}"${mode===choice?' selected':''}>${text(label)}</option>`;
 // A Phema: the Terminal's own chooser picks it, and the panel shows its last saved picture and its blocks.
 const bar=mode==='phema'
  ?`<button type="button" data-viewer-phema>${text(phema?'Choose another Phema':'Choose a Phema')}</button>${phema?`<small class="composition-viewer-pdf" title="${escape(phema.name)}">${escape(phema.name)}</small><button type="button" data-viewer-clear>${text('Remove')}</button>`:''}<small data-viewer-message hidden></small>`
  :mode==='web'
  ?`<input type="url" data-viewer-url value="${escape(url||'')}" ${attr('placeholder','https://…')} ${attr('aria-label','Web address')}><button type="button" data-viewer-go>${text('Go')}</button>${url?`<a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${text('Open in a new tab')}</a>`:''}`
  :`<button type="button" data-viewer-pick>${text('Choose a picture or PDF')}</button><input type="file" accept="image/png,image/jpeg,image/webp,application/pdf,.pdf" data-viewer-file hidden>${pages}${image?`${pdf?'':`<small>${image.width&&image.height?escape(image.width+'×'+image.height):''}</small>`}<button type="button" data-viewer-clear>${text('Remove')}</button>`:''}<small data-viewer-message hidden></small>`;
 const body=mode==='phema'
  ?(phema?`${phema.image?`<img class="composition-viewer-image" src="data:${escape(phema.image.type)};base64,${escape(phema.image.data)}" alt="">`:''}${viewerBlocks(phema,text)}`:`<p class="panel-note">${text('Choose a Phema to copy its blocks.')}</p>`)
  :mode==='web'
  ?(url?`<iframe class="composition-viewer-page" src="${escape(url)}" sandbox="allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" loading="lazy" ${attr('title','Web page')}></iframe><p class="composition-viewer-note">${text('If the page stays blank, it does not allow being shown here: open it in a new tab.')}</p>`:`<p class="panel-note">${text('Enter a web address to see the page here.')}</p>`)
  :(image?`<img class="composition-viewer-image" src="data:${escape(image.type)};base64,${escape(image.data)}" alt="">`:`<p class="panel-note">${text('Choose a picture or a PDF to see it here.')}</p>`);
 return `<div class="composition-viewer" data-viewer data-viewer-parameter="${escape(name)}" data-viewer-value="${escape(JSON.stringify(current))}"><div class="composition-viewer-bar"><select data-viewer-mode ${attr('aria-label','Show')}>${option('web','Web page')}${option('image','Picture')}${option('phema','Phema')}</select>${bar}</div><div class="composition-viewer-body">${body}</div></div>`;
}
// The person's choice goes to the host as `phemacast:viewer-change` {parameter, value}; the host keeps it as the page setting.
const VIEWER_EDGE=1024,VIEWER_CHARS=200000;
// A PDF opens in pdf.js (phemacast/web/vendor/pdfjs, loaded only when one is chosen) and its page is drawn as the
// picture, so the Phema's owner and its model calls get a picture as before. The PDF itself stays in this window's
// memory, never in the page setting: a reload keeps the picture of the page and asks for the PDF again to turn pages.
const VIEWER_PDF_BYTES=30*1024*1024,VIEWER_PDF_EDGE=1600,openPdfs=new Map();
const isPdf=file=>file.type==='application/pdf'||/\.pdf$/i.test(file.name||'');
const pdfKey=(parameter,pdf)=>parameter+'|'+pdf.name+'|'+(pdf.size??'');
let pdfjs=null;
async function pdfLibrary(){
 if(!pdfjs){
  pdfjs=import('./composition-vendor/pdfjs/pdf.min.js').then(library=>{
   library.GlobalWorkerOptions.workerSrc=new URL('./composition-vendor/pdfjs/pdf.worker.min.js',import.meta.url).href;return library;});
  pdfjs.catch(()=>{pdfjs=null;});
 }
 return pdfjs;
}
async function viewerPdf(file){
 if(file.size>VIEWER_PDF_BYTES)throw new Error('Choose a PDF up to 30 MB.');
 const library=await pdfLibrary();
 try{return await library.getDocument({data:new Uint8Array(await file.arrayBuffer()),enableXfa:false,useSystemFonts:true}).promise;}
 catch(error){console.warn("pdf.js:",error?.name,error?.message);throw new Error('This PDF cannot be read.');}
}
async function pdfPicture(document_,number){
 const page=await document_.getPage(number),base=page.getViewport({scale:1});
 const viewport=page.getViewport({scale:Math.min(4,VIEWER_PDF_EDGE/Math.max(base.width,base.height))});
 const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.floor(viewport.width));canvas.height=Math.max(1,Math.floor(viewport.height));
 await page.render({canvas,viewport,background:'#ffffff'}).promise;page.cleanup?.();
 return canvasPicture(canvas);
}
// A drawn picture as a JPEG of at most VIEWER_EDGE px whose base64 fits VIEWER_CHARS.
function canvasPicture(source){
 let scale=Math.min(1,VIEWER_EDGE/Math.max(source.width,source.height));
 for(let tries=0;tries<10;tries++){
  const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(source.width*scale));canvas.height=Math.max(1,Math.round(source.height*scale));
  const context=canvas.getContext('2d');context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(source,0,0,canvas.width,canvas.height);
  for(const quality of [0.85,0.72,0.6]){const data=canvas.toDataURL('image/jpeg',quality).split(',')[1];if(data.length<=VIEWER_CHARS)return {data,type:'image/jpeg',width:canvas.width,height:canvas.height};}
  scale*=0.8;
 }
 throw new Error('This picture is still too large after shrinking. Choose a simpler one.');
}
async function viewerPicture(file){
 if(!VIEWER_IMAGE.test(file.type)||file.size>10*1024*1024)throw new Error('Choose a PNG, JPEG or WebP image up to 10 MB.');
 const bitmap=await createImageBitmap(file);
 try{
  if(bitmap.width*bitmap.height>40000000)throw new Error('Choose an image up to 40 megapixels.');
  let scale=Math.min(1,VIEWER_EDGE/Math.max(bitmap.width,bitmap.height));
  for(let tries=0;tries<10;tries++){
   const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));
   const context=canvas.getContext('2d');context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(bitmap,0,0,canvas.width,canvas.height);
   for(const quality of [0.85,0.72,0.6]){const data=canvas.toDataURL('image/jpeg',quality).split(',')[1];if(data.length<=VIEWER_CHARS)return {data,type:'image/jpeg',width:canvas.width,height:canvas.height};}
   scale*=0.8;
  }
  throw new Error('This picture is still too large after shrinking. Choose a simpler one.');
 }finally{bitmap.close?.();}
}
// The host's chosen Phema as the setting keeps it: its picture (a data: URL the Terminal saved) as a small JPEG.
async function viewerPhema(choice){
 const preview=choice?.preview&&typeof choice.preview==='object'?choice.preview:{};
 const value=viewerPhemaValue({name:choice?.name,key:choice?.key,storage:choice?.storage,phemaId:choice?.phemaId,columns:Number(preview.columns)||undefined,
  panels:(Array.isArray(preview.panels)?preview.panels:[]).map(p=>({label:p?.label,column:Number(p?.column),row:Number(p?.row),columnSpan:Number(p?.columnSpan),rowSpan:Number(p?.rowSpan)}))});
 if(!value)throw new Error('That Phema cannot be copied here.');
 const picture=typeof choice.picture==='string'&&/^data:image\/(png|jpeg|webp);base64,/.test(choice.picture)?choice.picture:'';
 if(picture){
  try{
   const image=new Image();image.src=picture;await image.decode();
   const canvas=document.createElement('canvas');canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;canvas.getContext('2d').drawImage(image,0,0);
   value.image=canvasPicture(canvas);
  }catch{/* The blocks still show without the picture. */}
 }
 return value;
}
function mountViewers(root){
 for(const viewer of root.querySelectorAll('[data-viewer]:not([data-viewer-mounted])')){
  viewer.dataset.viewerMounted='true';
  const parameter=viewer.dataset.viewerParameter;if(!parameter)continue;
  let current;try{current=viewerSetting(JSON.parse(viewer.dataset.viewerValue||'{}'));}catch{current={mode:'web'};}
  // Sending a choice ends the person's typing in the address box; until then a redraw keeps what they typed (#224).
  const change=value=>{const box=viewer.querySelector('[data-viewer-url]');if(box)delete box.dataset.typing;
   viewer.dispatchEvent(new CustomEvent('phemacast:viewer-change',{bubbles:true,detail:{parameter,value:viewerSetting(value)}}));};
  const mode=viewer.querySelector('[data-viewer-mode]'),address=viewer.querySelector('[data-viewer-url]'),go=viewer.querySelector('[data-viewer-go]');
  const pick=viewer.querySelector('[data-viewer-pick]'),file=viewer.querySelector('[data-viewer-file]'),clear=viewer.querySelector('[data-viewer-clear]');
  // A note in the window's language: a fresh element named by its message key, which the host translates as it arrives.
  let message=viewer.querySelector('[data-viewer-message]');
  const say=key=>{if(!message?.isConnected)return;const next=message.cloneNode(false);next.dataset.uiKey=key;next.textContent=key;next.hidden=false;message.replaceWith(next);message=next;};
  if(mode)mode.onchange=()=>change({...current,mode:mode.value});
  // An emptied box clears the page, so nothing goes on being copied from the one shown before.
  const visit=()=>{let value=(address?.value||'').trim();address?.setCustomValidity?.('');
   if(!value){const {url,...rest}=current;change({...rest,mode:'web'});return;}
   if(!/^https:\/\//i.test(value))value='https://'+value.replace(/^http:\/\//i,'');
   if(!safeMediaURL(value)){address?.setCustomValidity?.('https://…');address?.reportValidity?.();return;}change({...current,mode:'web',url:value});};
  if(go)go.onclick=visit;
  if(address)address.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();visit();}};
  // The person is typing an address they have not sent: panel-refresh.js keeps it when the panel is drawn anew.
  if(address)address.oninput=()=>{address.dataset.typing='1';};
  if(pick&&file){pick.onclick=()=>file.click();
   file.onchange=async()=>{const chosen=file.files?.[0];if(!chosen)return;
    try{
     if(isPdf(chosen)){
      say('Reading the PDF…');
      const opened=await viewerPdf(chosen),pdf={name:chosen.name||'document.pdf',size:chosen.size,page:1,pages:opened.numPages};
      const key=pdfKey(parameter,pdf);openPdfs.get(key)?.destroy?.();openPdfs.set(key,opened);
      while(openPdfs.size>3){const [oldest,kept]=openPdfs.entries().next().value;kept.destroy?.();openPdfs.delete(oldest);}
      change({...current,mode:'image',image:await pdfPicture(opened,1),pdf});
     }else{const {pdf,...rest}=current;change({...rest,mode:'image',image:await viewerPicture(chosen)});}
    }
    catch(error){say(error.message);}};}
  for(const turn of viewer.querySelectorAll('[data-viewer-page]'))turn.onclick=async()=>{
   const pdf=current.pdf,opened=pdf&&openPdfs.get(pdfKey(parameter,pdf));if(!pdf)return;
   if(!opened){say('Choose the PDF again to turn its pages.');return;}
   const page=Math.min(pdf.pages,Math.max(1,pdf.page+Number(turn.dataset.viewerPage)));if(page===pdf.page)return;
   try{change({...current,image:await pdfPicture(opened,page),pdf:{...pdf,page}});}
   catch(error){say(error.message);}
  };
  if(clear)clear.onclick=()=>{if(current.mode==='phema'){const {phema,...rest}=current;change({...rest,mode:'phema'});return;}const {image,pdf,...rest}=current;change({...rest,mode:'image'});};
  // The host opens its own Phema chooser and answers with the chosen Phema ({name, key, storage, phemaId, preview,
  // picture}); a host without one leaves the event unanswered.
  const choosePhema=viewer.querySelector('[data-viewer-phema]');
  if(choosePhema)choosePhema.onclick=()=>{
   const detail={parameter,handled:false,respond:async choice=>{
    try{change({...current,mode:'phema',phema:await viewerPhema(choice)});}
    catch(error){say(error.message);}}};
   viewer.dispatchEvent(new CustomEvent('phemacast:viewer-choose-phema',{bubbles:true,detail}));
   if(!detail.handled)say('This Terminal cannot choose a Phema here.');
  };
 }
}
function authoredText(value,text){
 const content=String(value??'');
 return content&&content.length<=2000&&!/\{\d+\}/.test(content)?text(content):escape(content);
}
function interactiveHTML(value,text,plainText,attribute){
 const fields=structuredFields(value.inputSchema,{text,attribute});
 return `<form data-phema-interaction><fieldset ${value.disabled?'disabled':''}><div class="phema-form-grid">${fields}</div><button type="submit">${text(value.submitLabel||'Run interaction')}</button><p role="status"></p>${resultHTML(value.result,text,plainText)}</fieldset></form>`;
}
// A result that hands over a resolved Phema keeps its open button when the panel redraws.
function resultHTML(result,text,plainText){
 const navigation=!result||typeof result!=='object'?[]:Array.isArray(result.navigation)?result.navigation:result.phema?[{label:'Open Phema',phema:result.phema,source_mode:result.source_mode}]:[];
 const items=navigation.slice(0,4).filter(item=>item?.phema&&['parameters','snapshot'].includes(item.source_mode));
 if(items.length)return `<div class="composition-interaction-result">${text('Operation completed.')} ${items.map(item=>`<button type="button" data-phema-result="${escape(JSON.stringify({phema:item.phema,sourceMode:item.source_mode}))}">${text(item.label||'Open Phema')}</button>`).join('')}</div>`;
 // Owner tables and key values render as on acknowledgement, not as raw JSON.
 return `<div class="composition-interaction-result">${interactionResultHTML(result,{escape,render:customHTML,text,plainText})}</div>`;
}
export function timelineObject(object,timeline,elapsed){
 const result={...object};if(!timeline)return result;
 const time=timeline.loop?elapsed%timeline.duration:Math.min(elapsed,timeline.duration);
 for(const track of timeline.tracks||[]){if(track.target!==object.id)continue;const frames=track.keyframes;if(!frames?.length)continue;let left=frames[0],right=frames.at(-1);for(const frame of frames){if(frame.time<=time)left=frame;if(frame.time>=time){right=frame;break;}}const ratio=left===right?0:Math.max(0,Math.min(1,(time-left.time)/(right.time-left.time)));result[track.property]=left.value.map((v,i)=>v+(right.value[i]-v)*ratio);}
 return result;
}
function sceneAsset(element){let scene;try{scene=JSON.parse(element.dataset.scene);}catch{return false;}if(!scene.asset)return false;import('./composition-scene-assets.js').then(m=>m.mountAssetScene(element,scene)).catch(()=>{element.querySelector('[data-scene-status]').textContent='Model renderer unavailable';});return true;}
export function mountMedia(root){
 mountCompactComposition(root);
 mountViewers(root);
 // The host opens the handed-over Phema; mount authorization still runs on its server.
 for(const button of root.querySelectorAll('[data-phema-result]:not([data-result-mounted])')){
  button.dataset.resultMounted='true';
  button.onclick=()=>{let detail;try{detail=JSON.parse(button.dataset.phemaResult);}catch{return;}
   button.dispatchEvent(new CustomEvent('phemacast:open-result',{bubbles:true,detail}));};
 }
 for(const media of root.querySelectorAll('[data-asset-url]:not([data-asset-loading])')){
  media.dataset.assetLoading='true';const control=new AbortController(),blobs=[];
  const observer=new MutationObserver(()=>{if(!media.isConnected){control.abort();blobs.forEach(URL.revokeObjectURL);observer.disconnect();}});observer.observe(document.body,{childList:true,subtree:true});
  const limit=media.tagName==='TRACK'?250000:media.tagName==='IMG'?20000000:50000000;
  boundedAsset(media.dataset.assetUrl,{maxBytes:limit,signal:control.signal,authenticatedLocal:media.dataset.authenticatedLocal==='true'}).then(blob=>{if(!media.isConnected)return;const url=URL.createObjectURL(blob);blobs.push(url);media.src=url;
   media.addEventListener(media.tagName==='IMG'?'load':'loadedmetadata',()=>{if((media.naturalWidth||media.videoWidth||0)*(media.naturalHeight||media.videoHeight||0)>16000000||media.duration>3600){media.removeAttribute('src');media.dataset.assetError='Media decoding limit exceeded';}},{once:true});
  }).catch(()=>{media.dataset.assetError='Media unavailable';});
  if(media.dataset.posterUrl)boundedAsset(media.dataset.posterUrl,{maxBytes:20000000,signal:control.signal,authenticatedLocal:media.dataset.authenticatedLocal==='true'}).then(blob=>{const url=URL.createObjectURL(blob);blobs.push(url);media.poster=url;}).catch(()=>{});
 }
for(const media of root.querySelectorAll('audio[data-playback]:not([data-mounted]),video[data-playback]:not([data-mounted])')){media.dataset.mounted='true';let p;try{p=JSON.parse(media.dataset.playback);}catch{p={};}media.muted=p.muted===true;media.playbackRate=p.rate||1;const start=Number(p.start)||0;const init=()=>{if(start<media.duration)media.currentTime=start;};media.addEventListener('loadedmetadata',init,{once:true});if(media.readyState>=1)init();media.addEventListener('timeupdate',()=>{const end=Math.min(Number(p.end)||media.duration,media.duration);if(media.currentTime>=end){if(p.loop){media.currentTime=start;media.play().catch(()=>{});}else media.pause();}});}}
