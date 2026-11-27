/** The agents a viewer may choose for a pulse (`{"$agents": {"pulse": …}}` in a Phema's controls), read from the
 * Terminal (agent_choices.py: agents offering it that Plaza trusts for this viewer) and kept for a minute. Choosing
 * one grants nothing: the reference that asks it is checked again when it runs. */
const KEEP_MS=60000;
const lists=new Map();   // pulse → {at, agents, pending}
let request=null,changed=()=>{};
export function configureAgentChoices(options){request=options.request;changed=options.changed||(()=>{});}
/** {pulse: [{agentId, name}]} for the pulses asked, as far as they are known now; the rest are fetched. */
export function agentChoices(pulses){
 const known={};
 for(const pulse of new Set(pulses)){
  const entry=lists.get(pulse);
  if(entry?.agents)known[pulse]=entry.agents;
  if(!request||entry?.pending||(entry&&Date.now()-entry.at<KEEP_MS))continue;
  lists.set(pulse,{...entry,pending:true,at:Date.now()});
  request('/api/agent-choices?pulse='+encodeURIComponent(pulse)).then(answer=>{
   const agents=Array.isArray(answer?.agents)?answer.agents.slice(0,50):[];
   const before=JSON.stringify(entry?.agents);lists.set(pulse,{at:Date.now(),agents});
   if(JSON.stringify(agents)!==before)changed();
  }).catch(()=>{lists.set(pulse,{at:Date.now(),agents:entry?.agents||[]});});
 }
 return known;
}
/** The pulses a control document lists agents for. */
export function choicePulses(value,found=[],depth=0){
 if(depth>12||!value||typeof value!=='object')return found;
 if(!Array.isArray(value)&&Object.hasOwn(value,'$agents')){if(typeof value.$agents?.pulse==='string')found.push(value.$agents.pulse);return found;}
 for(const child of Object.values(value))choicePulses(child,found,depth+1);
 return found;
}
