// A window whose page is an earlier version of a page a program on this computer ships, such as Local RSS's RSS Viewer
// after Local RSS was updated, asks for approval: only the page exactly as the program ships it now counts as the
// person's own. 「更新為目前的版本」 takes the program's current page into the window. This
// Terminal's kept copy is updated from the program first, so New Data Browser then opens the same page.

/** The program's current page for its Phema library key (`local:<id>`), or null when this Terminal keeps no copy. */
export async function currentComponentPage(request,key){
 if(typeof key!=='string'||!key.startsWith('local:'))return null;
 const listed=(await request('/api/kept-phemas'))?.phemas||[];
 const row=listed.find(r=>r?.source?.kind==='local'&&r.source.key===key);
 if(!row)return null;
 await request('/api/kept-phemas/'+encodeURIComponent(row.id)+'/update',{method:'POST',body:{}});
 const kept=await request('/api/kept-phemas/'+encodeURIComponent(row.id));
 return kept?.phema&&typeof kept.phema==='object'?kept.phema:null;
}

/** The window's page values for the parameters the current page still declares. */
export function carriedValues(values,params){
 const declared=params&&typeof params==='object'?params:{};
 return Object.fromEntries(Object.entries(values&&typeof values==='object'?values:{}).filter(([key])=>Object.hasOwn(declared,key)));
}
