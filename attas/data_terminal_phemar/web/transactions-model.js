export function filterLedger(rows,{query='',action='',from='',to='',timeZone}={}) {
 const needle=query.trim().toLowerCase();
 return rows.filter(row=>{
  const date=new Date(row.created_at);let localDate='';if(Number.isFinite(+date)){if(timeZone){const parts=new Intl.DateTimeFormat('en-GB',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date),get=type=>parts.find(p=>p.type===type).value;localDate=[get('year'),get('month'),get('day')].join('-');}else localDate=[date.getFullYear(),String(date.getMonth()+1).padStart(2,'0'),String(date.getDate()).padStart(2,'0')].join('-');}
  return (!action||(row.kind||row.action)===action)&&(!from||localDate>=from)&&(!to||localDate<=to)&&(!needle||[row.id,row.request_id,row.reason,row.agent_name,row.agentLabel,row.agent_id,row.escrowId,row.source,row.counterparty,...(row.payees||[]).flatMap(p=>[p.provider_username,p.provider_user_id,p.agent_name])].join(' ').toLowerCase().includes(needle));
 });
}
export function csvCell(value) {
 let text=String(value??'');
 // Spreadsheet text must not be interpreted as a formula on opening the export.
 if(typeof value!=='number'&&/^[\s]*[=+@-]/.test(text))text="'"+text;
 return '"'+text.replaceAll('"','""')+'"';
}
export function ledgerCSV(rows) {
 const keys=['created_at','label','delta','previous_credit_points','credit_points','agent_name','payee','pulse','source','reason','request_id','escrowId','id'];
 const lines=[keys.map(csvCell).join(',')];
 for(const row of rows){const values={...row,payee:(row.payees||[]).map(p=>p.provider_username||p.provider_user_id).join('; ')};lines.push(keys.map(k=>csvCell(values[k])).join(','));}
 return '\ufeff'+lines.join('\r\n');
}
// Plaza holds an execution's points before it runs (a reservation) and returns them when it settles or refunds; the
// payment is an entry of its own. The holds and returns are among a period's credits and debits and cancel out, except
// for an execution with no settlement in this history: its points are still held (`open`, over `openRuns` executions).
export function reservationTotals(rows=[]) {
 let held=0,returned=0;const runs=new Map();
 for(const row of rows){
  const reserve=row.action==='report_escrow_reserve',settle=row.action==='report_escrow_capture'||row.action==='report_escrow_refund';
  if(!reserve&&!settle)continue;
  const key=row.escrowId||row.request_id||row.id,run=runs.get(key)||{held:0,settled:false};runs.set(key,run);
  if(reserve){held+=Math.max(0,-row.delta);run.held+=Math.max(0,-row.delta);}
  else{returned+=Math.max(0,row.delta);run.settled=true;}
 }
 const open=[...runs.values()].filter(run=>run.held&&!run.settled);
 return {held,returned,open:open.reduce((sum,run)=>sum+run.held,0),openRuns:open.length};
}
