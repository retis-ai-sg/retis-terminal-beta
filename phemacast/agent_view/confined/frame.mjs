/** Trusted generic frame. Owner JavaScript executes only inside the WASM VM. */
import {newQuickJSWASMModuleFromVariant,newVariant} from 'quickjs-emscripten-core';
import variant from '@jitl/quickjs-wasmfile-release-sync';
import environment from 'phemacast-runtime:environment';
import wasmText from 'phemacast-runtime:wasm';
import {DrawingSurface,safeCSS} from './surface.mjs';
import {pickTextFile} from './text_file.mjs';
const PROTOCOL='phemacast:agent-view-message/1';
const wasm=Uint8Array.from(atob(wasmText),c=>c.charCodeAt(0)).buffer;
const defaultDateOptions=JSON.stringify(new Intl.DateTimeFormat().resolvedOptions());
const modulePromise=newQuickJSWASMModuleFromVariant(newVariant(variant,{wasmBinary:wasm,wasmModule:()=>WebAssembly.compile(wasm),wasmSourceMapData:{version:3,sources:[],names:[],mappings:''}}));
function boundedJSON(value){const text=JSON.stringify(value);if(!text||text.length>300000)throw Error('View value exceeds its limit');return text;}
// A layout picture (pickImage({maxEdge})) is a JPEG whose longest side is at most maxEdge (64 to 1600 px), shrunk until
// its base64 fits a view value; without options a view gets the 128-px portrait it always had.
const LAYOUT_CHARS=280000;
async function layoutPicture(image,edge){
 let scale=Math.min(1,edge/Math.max(image.width,image.height));
 for(let tries=0;tries<10;tries++){
  const canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(image.width*scale));canvas.height=Math.max(1,Math.round(image.height*scale));
  const context=canvas.getContext('2d');context.fillStyle='#fff';context.fillRect(0,0,canvas.width,canvas.height);context.drawImage(image,0,0,canvas.width,canvas.height);
  for(const quality of [0.85,0.72,0.6]){
   const value=canvas.toDataURL('image/jpeg',quality).split(',')[1];
   if(value.length<=LAYOUT_CHARS)return {content_base64:value,type:'image/jpeg',width:canvas.width,height:canvas.height};
  }
  scale*=0.8;
 }
 throw Error('This picture is still too large after shrinking. Choose a simpler one.');
}
export function pickImage(root,options={}){
 if(!navigator.userActivation?.isActive)throw Error('Select an image from an explicit user action.');
 const layout=Number.isInteger(options?.maxEdge);
 if(layout&&(options.maxEdge<64||options.maxEdge>1600))throw Error('A layout picture is 64 to 1600 px on its longest side.');
 return new Promise((resolve,reject)=>{
  const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp';input.hidden=true;root.append(input);
  const finish=(value,error)=>{input.remove();error?reject(error):resolve(value);};
  input.addEventListener('cancel',()=>finish(null),{once:true});
  input.onchange=async()=>{try{
   const file=input.files?.[0];if(!file){finish(null);return;}
   const bytes=layout?10*1024*1024:2*1024*1024,pixels=layout?40000000:16000000;
   if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>bytes)throw Error(layout?'Choose a PNG, JPEG or WebP image up to 10 MB.':'Choose a PNG, JPEG or WebP image up to 2 MB.');
   const image=await createImageBitmap(file);if(image.width*image.height>pixels){image.close();throw Error(layout?'Choose an image up to 40 megapixels.':'Choose an image up to 16 megapixels.');}
   if(layout){try{finish(await layoutPicture(image,options.maxEdge));}finally{image.close();}return;}
   const scale=Math.min(1,128/image.width,128/image.height),canvas=document.createElement('canvas');canvas.width=Math.max(1,Math.round(image.width*scale));canvas.height=Math.max(1,Math.round(image.height*scale));
   canvas.getContext('2d').drawImage(image,0,0,canvas.width,canvas.height);image.close();
   const value=canvas.toDataURL('image/png').split(',')[1];if(value.length>90000)throw Error('This portrait exceeds the bounded image input. Select a simpler image.');
   finish({content_base64:value});
  }catch(error){finish(null,error);}};input.click();
 });
}
export async function createConfinedRuntime(root,{script,style='',html='',context,invoke,onError=()=>{}}){
 const appearance=value=>{document.documentElement.dataset.theme=value.theme||'light';
  for(const [key,color]of Object.entries(value.colors||{}))if(/^[-a-z]{1,40}$/.test(key)&&/^#[a-f0-9]{3,8}$/i.test(color))document.documentElement.style.setProperty('--'+key,color);};
 appearance(context);
 const module=await modulePromise,runtime=module.newRuntime();runtime.setMemoryLimit(64*1024*1024);
 const vm=runtime.newContext();let closed=false,deadline=Date.now()+15000;const pending=new Set(),timers=new Set();
 runtime.setInterruptHandler(()=>closed||Date.now()>deadline);
 const error=value=>{const v=vm.dump(value);return new Error(v.message||'Owner script failed in its isolated runtime');};
 const run=code=>{deadline=Date.now()+15000;const result=vm.evalCode(code,'owner-view.js');if(result.error){const e=error(result.error);result.error.dispose();throw e;}result.value.dispose();drain();};
 const drain=()=>{if(closed)return;deadline=Date.now()+15000;for(let i=0;i<100&&runtime.hasPendingJob();i++){const result=runtime.executePendingJobs(100);if(result.error){const e=error(result.error);result.error.dispose();onError(e);break;}}};
 const deliver=(fn,args)=>{if(closed)return;try{run(fn+'(...'+boundedJSON(args)+')');}catch(e){onError(e);}};
 const surface=new DrawingSurface(root,(id,event)=>deliver('__deliverEvent',[id,event]));
 root.addEventListener('submit',event=>event.preventDefault(),true);
 const bind=(name,fn)=>{const handle=vm.newFunction(name,(...values)=>{try{const args=values.map(value=>vm.getString(value));const result=fn(...args);return result;}catch(e){return {error:vm.newError(e.message)};}});vm.setProp(vm.global,name,handle);handle.dispose();};
 bind('__surface',(method,json)=>vm.newString(JSON.stringify(surface.call(method,JSON.parse(json)))));
 bind('__context',()=>vm.newString(boundedJSON(context)));
 bind('__random',()=>vm.newString(crypto.randomUUID()));
 bind('__timer',(id,ms)=>{if(timers.size>=100)throw Error('Timer limit exceeded');const timer=setTimeout(()=>{timers.delete(timer);deliver('__deliverTimer',[id]);},Math.max(4,Math.min(30000,Number(ms)||0)));timers.add(timer);return vm.undefined;});
 bind('__format',(type,json)=>{if(json.length>4000)throw Error('Format request exceeds its limit');const [requestedLocale,requestedOptions,value]=JSON.parse(json);const locale=requestedLocale??undefined,options=requestedOptions??undefined;let result;
  if(type==='number')result=new Intl.NumberFormat(locale,options).format(value);
  else if(type==='numberOptions')result=JSON.stringify(new Intl.NumberFormat(locale,options).resolvedOptions());
  else if(type==='date')result=new Intl.DateTimeFormat(locale,options).format(value);
  else if(type==='parts')result=JSON.stringify(new Intl.DateTimeFormat(locale,options).formatToParts(value));
  else if(type==='dateOptions')result=!locale&&!options?defaultDateOptions:JSON.stringify(new Intl.DateTimeFormat(locale,options).resolvedOptions());
  else if(type==='supported'&&locale==='timeZone')result=JSON.stringify(Intl.supportedValuesOf('timeZone'));
  else throw Error('Undeclared presentation formatter');return vm.newString(result);});
 // Answers of the view's action handlers (environment.js __deliverAction), by action id.
 const actionReplies=new Map();
 bind('__actionReply',(id,json)=>{const settle=actionReplies.get(id);if(settle){actionReplies.delete(id);settle(json);}return vm.undefined;});
 bind('__operation',(type,json)=>{
  if(!['invoke','status','set-mode','pick-image','pick-text-file','presentation','parameters','set-parameters','save-snapshot','snapshots','read-snapshot','schedule','runs','run-now','stop-run','kept-read','kept-write','kept-drop','image-put','panels','panel-parameters','set-panel-parameters','open-link'].includes(type)||json.length>300000||pending.size>=16)throw Error('Operation is unavailable');
  const promise=vm.newPromise();pending.add(promise);
  // A picture is decoded here, in the frame: nothing leaves it (raster.mjs).
  const action=type==='image-put'?surface.images.put(JSON.parse(json)):type==='pick-image'?pickImage(root,JSON.parse(json)):type==='pick-text-file'?pickTextFile(root):Promise.resolve().then(()=>invoke(type,JSON.parse(json)));
  Promise.resolve(action).then(value=>{
   if(closed)return;deadline=Date.now()+15000;const result=vm.evalCode('JSON.parse('+JSON.stringify(boundedJSON(value))+')');if(result.error){promise.reject(result.error);result.error.dispose();}else{promise.resolve(result.value);result.value.dispose();}
  },reason=>{if(closed)return;deadline=Date.now()+15000;const e=vm.newError(String(reason.message||reason));promise.reject(e);e.dispose();}).catch(e=>onError(e)).finally(()=>{if(!closed){pending.delete(promise);drain();promise.dispose();}});
  return promise.handle;
 });
 const dispose=()=>{if(closed)return;closed=true;actionReplies.clear();for(const timer of timers)clearTimeout(timer);timers.clear();surface.dispose();for(const promise of pending)promise.dispose();pending.clear();vm.dispose();runtime.dispose();};
 try{
  const css=document.createElement('style');css.textContent=safeCSS(style);root.before(css);
  surface.markup(root,html);run(environment);run(script);
  return {dispose(){dispose();css.remove();},
   // Presentation fields only; the view's parameters and source mode stay as mounted.
   updateContext(value){if(closed)return;context={...context,...value};appearance(context);deliver('__deliverContext',[value]);},
   // An action the container asks for: the view's handler (actions.handle) runs it; resolves with its answer.
   action(id,name,input,by){return new Promise((resolve,reject)=>{
    if(closed||actionReplies.has(String(id))||actionReplies.size>=16){reject(Error(closed?'The view is not open; open its Browser window first.':'This view is busy with another action; try again in a moment.'));return;}
    actionReplies.set(String(id),json=>{let reply=null;try{reply=JSON.parse(json);}catch{}
     if(reply?.ok===true)resolve(reply.value===undefined?null:reply.value);
     else reject(Error(typeof reply?.error==='string'&&reply.error?reply.error:'The view could not take that action.'));});
    try{run('__deliverAction(...'+boundedJSON([String(id),String(name),input===undefined?null:input,String(by??'')])+')');}
    catch(e){actionReplies.delete(String(id));reject(e);}
   });},
   evaluate(code){deadline=Date.now()+15000;const r=vm.evalCode(code);if(r.error){const e=error(r.error);r.error.dispose();throw e;}const data=vm.dump(r.value);r.value.dispose();drain();return data;}};
 }catch(e){try{dispose();}catch{}throw e;}
}

// This is the only browser-facing channel. It supplies no credentials or URLs.
if(typeof window!=='undefined'){
 let port=null,view=null,failed=false,sequence=0,operationTimeoutMs=35000,update=null;const pending=new Map();
 // The container asks the view to take an action (host.mjs AgentView#action); the reply carries the action's id.
 const answer=async data=>{
  if(typeof data.id!=='string'||!/^action-[0-9]+$/.test(data.id))return;
  const value=data.value&&typeof data.value==='object'?data.value:{};let reply;
  try{
   if(!view)throw Error(failed?'The view did not start; reload it.':'The view is still starting; try again in a moment.');
   const result=await view.action(data.id,typeof value.action==='string'?value.action:'',value.input,typeof value.by==='string'?value.by:'');
   const text=JSON.stringify(result===undefined?null:result)??'null';
   if(text.length>300000)throw Error("The action's input or answer exceeds its limit.");
   reply={ok:true,value:JSON.parse(text)};
  }catch(error){reply={ok:false,error:String(error?.message||error||'The view could not take that action.')};}
  port.postMessage({schema:PROTOCOL,type:'action-reply',id:data.id,...reply});
 };
 const invoke=(type,value)=>new Promise((resolve,reject)=>{const id='request-'+(++sequence);const timer=setTimeout(()=>{pending.delete(id);reject(Error('Operation timed out; inspect status before retrying'));},operationTimeoutMs);pending.set(id,{resolve,reject,timer});port.postMessage({schema:PROTOCOL,type,id,value});});
 const receive=async event=>{
  if(event.source!==parent||event.data?.schema!==PROTOCOL||event.data.type!=='connect'||event.ports.length!==1||port)return;
  removeEventListener('message',receive);port=event.ports[0];
  port.onmessage=event=>{const data=event.data;
   // A context change can arrive while the view is still starting; it is applied once the view exists.
   if(data?.schema===PROTOCOL&&data.type==='context'){if(view)view.updateContext(data.context);else update={...update,...data.context};return;}
   if(data?.schema===PROTOCOL&&data.type==='action'){answer(data);return;}
   const request=pending.get(data?.id);if(!request)return;pending.delete(data.id);clearTimeout(request.timer);data.ok?request.resolve(data.value):request.reject(Error(data.error));};port.start();
  const spec=event.data.spec,context=event.data.context;
  if(Number.isInteger(context.operationTimeoutMs)&&context.operationTimeoutMs>=1000&&context.operationTimeoutMs<=270000)operationTimeoutMs=context.operationTimeoutMs;
  try{view=await createConfinedRuntime(document.querySelector('main'),{script:spec.assets.script.text,style:spec.assets.style?.text||'',html:spec.html,context,invoke,onError:error=>{const status=document.querySelector('[role=status]');if(status)status.textContent=error.message;}});if(update)view.updateContext(update);}
  catch(error){failed=true;document.querySelector('main').textContent=error.message;}
 };
 addEventListener('message',receive);parent.postMessage({schema:PROTOCOL,type:'ready'},'*');
 addEventListener('pagehide',()=>{view?.dispose();port?.close();for(const {timer}of pending.values())clearTimeout(timer);pending.clear();});
}
