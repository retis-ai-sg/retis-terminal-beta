/* OPML for the RSS views: read the feed lists other readers export and write one to copy. Built into each view's
   release before the view's own script (release.py, groups_release.py). */
(()=>{
'use strict';
const MAX_TEXT=100000,MAX_FEEDS=500;
const ENTITIES={amp:'&',lt:'<',gt:'>',quot:'"',apos:"'"};
const decode=value=>value.replace(/&(#x[0-9a-f]{1,6}|#[0-9]{1,7}|[a-z]+);/gi,(all,name)=>{
 if(name[0]==='#'){const code=name[1].toLowerCase()==='x'?parseInt(name.slice(2),16):parseInt(name.slice(1),10);
  return code>0&&code<=0x10ffff&&!(code>=0xd800&&code<=0xdfff)?String.fromCodePoint(code):'';}
 return Object.hasOwn(ENTITIES,name.toLowerCase())?ENTITIES[name.toLowerCase()]:'';});
const clean=(value,limit)=>decode(String(value||'')).replace(/[\u0000-\u001f\u007f]+/g,' ').replace(/\s+/g,' ').trim().slice(0,limit);
function attributes(text){
 const found={};const pattern=/([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;let match;
 while((match=pattern.exec(text)))found[match[1].toLowerCase()]=match[2]??match[3]??'';
 return found;
}
/** Feeds in an OPML document, each with the name of the outline folder around it as its group. Only <outline> elements
 *  are read; a document type or entity declaration is refused, so nothing is expanded or loaded. */
function parse(text){
 text=String(text||'');
 if(!text.trim())throw Error('Paste OPML or choose an OPML file.');
 if(text.length>MAX_TEXT)throw Error('Use an OPML document up to 100 KB.');
 if(/<!DOCTYPE|<!ENTITY/i.test(text))throw Error('OPML with a document type or entity declarations is not supported.');
 if(!/<opml[\s>]/i.test(text))throw Error('This is not an OPML document.');
 const feeds=[],stack=[],pattern=/<(\/?)outline\b((?:[^>"']|"[^"]*"|'[^']*')*?)(\/?)>/gi;let match;
 while((match=pattern.exec(text))&&feeds.length<MAX_FEEDS){
  const [,closing,body,selfClosing]=match;
  if(closing){stack.pop();continue;}
  const attrs=attributes(body),url=clean(attrs.xmlurl,2048),name=clean(attrs.text||attrs.title,100);
  if(url){const folder=[...stack].reverse().find(Boolean)||'';feeds.push({url,name,group:folder.slice(0,60)});}
  if(!selfClosing)stack.push(url?null:name||null);
 }
 return {feeds};
}
const escape=value=>String(value??'').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g,'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
/** An OPML 2.0 document for these feeds: grouped feeds inside an outline folder named after their group. */
function write(feeds,title){
 const line=f=>'<outline type="rss" text="'+escape(f.name||f.url)+'" title="'+escape(f.name||f.url)+'" xmlUrl="'+escape(f.url)+'"/>';
 const order=[],grouped=new Map();
 for(const feed of feeds){const group=feed.group||'';if(!grouped.has(group)){grouped.set(group,[]);order.push(group);}grouped.get(group).push(feed);}
 const body=order.flatMap(group=>group?['  <outline text="'+escape(group)+'" title="'+escape(group)+'">',...grouped.get(group).map(f=>'   '+line(f)),'  </outline>']:grouped.get(group).map(f=>'  '+line(f)));
 return ['<?xml version="1.0" encoding="UTF-8"?>','<opml version="2.0">',' <head><title>'+escape(title||'RSS feeds')+'</title></head>',' <body>',...body,' </body>','</opml>',''].join('\n');
}
globalThis.RSSOPML=Object.freeze({parse,write});
})();
