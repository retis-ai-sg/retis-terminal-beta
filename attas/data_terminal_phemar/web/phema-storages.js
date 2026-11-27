/** Where Phemas are stored, besides this Terminal's own store: each agent this account may use whose declared
 * workspace entry opens a Phema library. Generic: an agent declares it (`phemacast:phema-library` on its entry) and
 * names itself; nothing here knows which agents exist. */
import {resolveWorkspaceEntry,workspaceEntryReference} from './workspace-entry-navigation.js';

export const TERMINAL_STORAGE='terminal';
export const LIBRARY='phemacast:phema-library';
const declares=phema=>phema?.sections?.flatMap(s=>s.content||[]).filter(n=>n.type==='phemacast:composition')
 .some(node=>node.extensions?.[LIBRARY]?.version==='1.0.0');

/** The agents' Phema libraries, each {id, name, selector()}: `selector` resolves the agent's entry now and returns
 * the Phema that declares its `phemacast:selector-entry`. */
export async function agentStorages({request,toEntry,workspaceId}){
 const value=await request('/api/agent-workspaces');
 if(!Array.isArray(value?.entries))throw Error('Workspace discovery returned an invalid response.');
 const storages=[],seen=new Set();
 for(const entry of value.entries){
  if(typeof entry?.name!=='string'||!entry.name.trim()||!declares(entry.phema))continue;
  const agent=workspaceEntryReference(entry)?.target?.agentId;
  if(typeof agent!=='string'||!agent||seen.has(agent))continue;
  seen.add(agent);
  storages.push({id:'agent:'+agent,name:entry.name.trim().slice(0,150),
   async selector(){return (await resolveWorkspaceEntry({entry,request,toEntry,workspaceId:workspaceId()})).phema;}});
 }
 return storages;
}
