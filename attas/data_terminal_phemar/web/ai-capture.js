// A picture of what this window shows, for an AI app the window approved (mcp_access.py capture_window). It draws the
// page's own content the way workspace previews do. Agent views draw inside sandboxed frames that a page capture
// cannot see, so they come out as empty boxes; a Browser window whose data an AI app may not see is left out.
import {toJpeg} from './preview-raster.js';

// The page hands the picture back in one request, which the Terminal takes up to 1 MB (runtime.py).
export const MAX_WIDTH=1600,MAX_HEIGHT=1000,MAX_CHARS=900_000;
const FRAMES='Agent views draw inside their own frames and show as empty boxes; read_window gives their panels.';

/** What stays out of the picture: password fields, frames, media, scripts, other origins' images, hidden windows. */
export function keep(node,hidden=new Set()){
 if(!(node instanceof Element))return true;
 if(node.matches('input[type="password"],iframe,video,audio,script,[data-preview-exclude]'))return false;
 if(node.matches('[data-browser]')&&hidden.has(node.dataset.browser))return false;
 if(node instanceof HTMLImageElement){try{return new URL(node.currentSrc||node.src,location.href).origin===location.origin||node.src.startsWith('data:image/');}catch{return false;}}
 return true;
}

/** A bounded JPEG of `node` (the window area, or one Browser window with `single`). */
export async function captureForAI(node,{hidden=new Set(),single=false}={}){
 const width=node.clientWidth,height=node.clientHeight;
 if(!width||!height)throw new Error('Nothing is showing to capture; bring the Browser window to the front first.');
 const scale=Math.min(1,MAX_WIDTH/width,MAX_HEIGHT/height);
 const options={width,height,canvasWidth:Math.round(width*scale),canvasHeight:Math.round(height*scale),pixelRatio:1,skipFonts:true,
  filter:n=>keep(n,hidden),backgroundColor:getComputedStyle(node).backgroundColor||getComputedStyle(document.body).backgroundColor,
  // One Browser window sits at its own place in the window area; draw it from its top left corner.
  ...(single?{style:{position:'relative',left:'0',top:'0',transform:'none',margin:'0',boxShadow:'none',contentVisibility:'visible',contain:'none',inset:'0'}}:{})};
 let image=await toJpeg(node,{...options,quality:.8});
 if(image.length>MAX_CHARS)image=await toJpeg(node,{...options,quality:.55});
 if(image.length>MAX_CHARS){options.canvasWidth=Math.round(options.canvasWidth*.7);options.canvasHeight=Math.round(options.canvasHeight*.7);image=await toJpeg(node,{...options,quality:.5});}
 if(image.length>MAX_CHARS)throw new Error('The picture is too large; capture one Browser window instead.');
 const frames=node.querySelectorAll('iframe').length;
 return {image,width:options.canvasWidth,height:options.canvasHeight,agentViews:frames,...(frames?{note:FRAMES}:{})};
}
