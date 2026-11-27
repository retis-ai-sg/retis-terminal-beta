/**
 * Where each Phema's window was last placed in this Terminal window, so it opens there again.
 *
 * The places are a preference of the window (`phemaWindows`, per account and Terminal window, in the Terminal's store
 * with its other settings), keyed by the Phema's own id: the identity the Terminal already gives an opened Phema
 * (agent workspace entries reuse its window, view-kept results and scheduled runs follow it), and the one every way of
 * opening carries. A saved workspace keeps its own layout; these places apply only when a Phema opens in a new window.
 */
import {normalizeFrame} from './window-geometry.js';

/** The most places kept, newest first. */
export const PHEMA_WINDOWS_LIMIT=100;
/** How far a second copy of an open Phema moves from the first, in CSS pixels (as a duplicated window does). */
export const COPY_OFFSET=28;
const KEY_LENGTH=200,MAX_PIXELS=100000;
const finite=value=>typeof value==='number'&&Number.isFinite(value);

/** The identity a window's place is kept under: its Phema's id, or null for a window with no Phema. */
export function phemaWindowKey(browser){
 const id=browser?.customLayout?.id;
 return typeof id==='string'&&id.length>0&&id.length<=KEY_LENGTH?id:null;
}

function row(value){
 if(!value||typeof value!=='object'||typeof value.phema!=='string'||!value.phema||value.phema.length>KEY_LENGTH)return null;
 const sizes=['x','y','width','height'].map(name=>value[name]);
 if(!sizes.every(finite)||value.x<0||value.y<0||value.width<1||value.height<1||sizes.some(n=>n>MAX_PIXELS))return null;
 if(!Number.isInteger(value.at)||value.at<=0)return null;
 const [x,y,width,height]=sizes.map(Math.round);
 return {phema:value.phema,x,y,width,height,maximized:value.maximized===true,at:value.at};
}

/** The kept places as the store holds them: valid rows only, one per Phema, newest first, at most the limit. */
export function normalizePhemaWindows(value){
 const seen=new Set();
 return (Array.isArray(value)?value:[]).map(row).filter(Boolean).sort((a,b)=>b.at-a.at)
  .filter(item=>!seen.has(item.phema)&&seen.add(item.phema)).slice(0,PHEMA_WINDOWS_LIMIT);
}

/**
 * Where a Phema opens in a new window: its saved frame, kept whole inside the canvas (a smaller screen moves and
 * shrinks it into view). `taken` lists the frames of its windows already open; the new one moves 28px down and right
 * of each window of the same Phema at that place, or up and left once the canvas edge stops it.
 */
export function restoredFrame(saved,taken,bounds){
 const base=normalizeFrame(saved,bounds),open=(taken||[]).filter(Boolean);
 const free=frame=>!open.some(other=>Math.abs(other.x-frame.x)<COPY_OFFSET/2&&Math.abs(other.y-frame.y)<COPY_OFFSET/2);
 if(free(base))return base;
 for(const sign of [1,-1])for(let step=1;step<=12;step+=1){
  const frame=normalizeFrame({...base,x:base.x+sign*step*COPY_OFFSET,y:base.y+sign*step*COPY_OFFSET},bounds);
  if(free(frame))return frame;
 }
 return normalizeFrame({...base,x:base.x+COPY_OFFSET,y:base.y+COPY_OFFSET},bounds);
}

/**
 * The window's kept places. `read()` gives the list the store last sent; `write(list)` saves the whole list. Saves go
 * one at a time, and changes made while one is on its way go together in the next, so the store ends with the last.
 */
export function createPhemaWindows({read,write,now=()=>Date.now()}){
 let pending=null,saving=null;
 const list=()=>pending||normalizePhemaWindows(read());
 // Nothing awaits between the loop's last check and `saving=null`, so a change never waits behind a finished save.
 async function flush(){
  while(pending){
   const value=pending;
   try{await write(value);}
   catch(error){console.warn('Window places were not saved:',error?.message||error);}
   if(pending===value)pending=null;
  }
  saving=null;
 }
 return {
  /** The saved place of a Phema's window, or null. */
  get(key){return key?list().find(item=>item.phema===key)||null:null;},
  /** Keep a Phema's window place; a part left out (frame or maximized) stays as it was saved. */
  remember(key,{frame,maximized}={}){
   if(!key)return null;
   const previous=list().find(item=>item.phema===key)||null,place=frame||previous;
   if(!place)return null;
   const value=row({phema:key,x:place.x,y:place.y,width:place.width,height:place.height,
    maximized:typeof maximized==='boolean'?maximized:previous?.maximized===true,at:Math.max(now(),(previous?.at||0)+1)});
   if(!value)return null;
   pending=normalizePhemaWindows([value,...list().filter(item=>item.phema!==key)]);
   if(!saving)saving=flush();
   return value;
  },
  /** Resolves once every change so far is saved (or failed to save). */
  settled(){return saving||Promise.resolve();},
 };
}
