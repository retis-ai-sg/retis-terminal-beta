/** Versioned generic host. Application content still comes from its publisher. */
import {AgentViewNode} from './node.mjs';
import {CompositionViewChannel} from './composition-channel.mjs';
// The host's own words, in the viewer's language (walk of 2026-11-18: a Chinese Terminal showed them in English).
const WORDS={lost:{en:'This view lost its Phema connection.','zh-Hant':'此畫面與 Phema 的連線已中斷。','zh-Hans':'此画面与 Phema 的连接已中断。',
  ja:'このビューは Phema との接続を失いました。',es:'Esta vista perdió su conexión con el Phema.',fr:'Cette vue a perdu sa connexion au Phema.'},
 reload:{en:'Reload view','zh-Hant':'重新載入畫面','zh-Hans':'重新载入画面',ja:'ビューを再読み込み',es:'Recargar vista',fr:'Recharger la vue'},
 // The channel's reasons a view could not start, shown under the banner or in place of the view.
 'The selected Phema has changed or closed. Reload this view.':{'zh-Hant':'所選的 Phema 已變更或關閉。請重新載入此畫面。','zh-Hans':'所选的 Phema 已更改或关闭。请重新载入此画面。',
  ja:'選択した Phema が変更されたか、閉じられました。このビューを再読み込みしてください。',es:'El Phema seleccionado cambió o se cerró. Vuelve a cargar esta vista.',fr:'Le Phema sélectionné a changé ou a été fermé. Rechargez cette vue.'},
 'The Phema did not finish initializing. Reload this view.':{'zh-Hant':'Phema 尚未完成初始化。請重新載入此畫面。','zh-Hans':'Phema 尚未完成初始化。请重新载入此画面。',
  ja:'Phema の初期化が完了しませんでした。このビューを再読み込みしてください。',es:'El Phema no terminó de inicializarse. Vuelve a cargar esta vista.',fr:'Le Phema n’a pas fini de s’initialiser. Rechargez cette vue.'},
 'The Phema could not initialize.':{'zh-Hant':'Phema 無法初始化。','zh-Hans':'Phema 无法初始化。',
  ja:'Phema を初期化できませんでした。',es:'El Phema no pudo inicializarse.',fr:'Le Phema n’a pas pu s’initialiser.'},
 // The channel's reasons an open view stopped (composition-channel.mjs).
 'The Phema source mode changed. Reload this view.':{'zh-Hant':'Phema 的來源模式已變更。請重新載入此畫面。','zh-Hans':'Phema 的来源模式已更改。请重新载入此画面。',
  ja:'Phema のソースモードが変更されました。このビューを再読み込みしてください。',es:'El modo de origen del Phema cambió. Vuelve a cargar esta vista.',fr:'Le mode de source du Phema a changé. Rechargez cette vue.'},
 'The Phema changed. Reload this view before another operation.':{'zh-Hant':'Phema 已變更。請先重新載入此畫面，再進行其他操作。','zh-Hans':'Phema 已更改。请先重新载入此画面，再进行其他操作。',
  ja:'Phema が変更されました。次の操作の前にこのビューを再読み込みしてください。',es:'El Phema cambió. Vuelve a cargar esta vista antes de otra operación.',fr:'Le Phema a changé. Rechargez cette vue avant une autre opération.'},
 'The mounted parameters or generation changed. Reload this view before another operation.':{'zh-Hant':'此畫面所用的參數已變更，或頁面已重新執行。請先重新載入此畫面，再進行其他操作。',
  'zh-Hans':'此画面所用的参数已更改，或页面已重新运行。请先重新载入此画面，再进行其他操作。',ja:'このビューのパラメーターが変更されたか、ページが再実行されました。次の操作の前にこのビューを再読み込みしてください。',
  es:'Los parámetros de esta vista cambiaron o la página se volvió a ejecutar. Vuelve a cargar esta vista antes de otra operación.',fr:'Les paramètres de cette vue ont changé ou la page a été réexécutée. Rechargez cette vue avant une autre opération.'},
 'The Terminal did not apply the parameter values. Reload this view.':{'zh-Hant':'終端未套用這些參數值。請重新載入此畫面。','zh-Hans':'终端未应用这些参数值。请重新载入此画面。',
  ja:'ターミナルはパラメーター値を適用しませんでした。このビューを再読み込みしてください。',es:'El terminal no aplicó los valores de los parámetros. Vuelve a cargar esta vista.',fr:'Le terminal n’a pas appliqué les valeurs des paramètres. Rechargez cette vue.'}};
/** The host's own words (`WORDS`), in the viewer's language; any other text as it came. */
export const say=(word,locale)=>{const code=String(locale||'en'),words=Object.hasOwn(WORDS,word)?WORDS[word]:null;if(!words)return word;
 return words[/^zh[-_](hant|tw|hk|mo)/i.test(code)?'zh-Hant':/^zh/i.test(code)?'zh-Hans':code.slice(0,2).toLowerCase()]||words.en||word;};

export function mountAgentView(root,reference,context,{request,presentation,compositionContext,onPresentation,hostRelease,runtimeDigest,startTimeoutMs}){
 Object.assign(root.style,{display:'flex',flexDirection:'column',flex:'1',minHeight:'0',overflow:'hidden'});
 const target=root.querySelector('[data-agent-view-host]');
 Object.assign(target.style,{height:'100%',flex:'1',minHeight:'0'});
 const status=document.createElement('p');status.setAttribute('role','status');target.append(status);
 let closed=false;
 // When the view's Phema link can't be reconnected, offer one remount of the same reference.
 const stale=document.createElement('div'),note=document.createElement('span'),reload=document.createElement('button');
 stale.setAttribute('role','status');
 Object.assign(stale.style,{display:'none',alignItems:'center',gap:'8px',padding:'4px 8px',fontSize:'12px',borderBottom:'1px solid currentColor'});
 const label=()=>{const locale=presentation(root,context).locale;note.textContent=say('lost',locale);reload.textContent=say('reload',locale);};
 label();reload.type='button';
 Object.assign(reload.style,{font:'inherit',color:'inherit',background:'transparent',border:'1px solid currentColor',borderRadius:'4px',padding:'2px 8px',cursor:'pointer'});
 stale.append(note,reload);target.parentNode.insertBefore(stale,target);
 const node=new AgentViewNode(target,{request,context:presentation(root,context),hostRelease,runtimeDigest,onPresentation,startTimeoutMs,
  ...(compositionContext?{compositionChannel:value=>new CompositionViewChannel({...compositionContext(root,value),reference:value,onStale:()=>{if(!closed)stale.style.display='flex';}})}:{}),
  // Mounting replaces the target's children; bring the status back when it has something to say.
  onStatus:value=>{status.textContent=value;status.hidden=value==='Mounted';if(!status.hidden&&!status.isConnected)target.prepend(status);}});
 const mount=()=>node.reload(reference).catch(error=>{if(closed)return;target.replaceChildren(status);status.hidden=false;status.textContent=say(error.message,presentation(root,context).locale);});
 reload.addEventListener('click',()=>{stale.style.display='none';mount();});
 // The container announces a presentation change (such as its theme); the open view follows without remounting.
 const follow=()=>{if(!closed){node.updateContext(presentation(root,context));label();}};
 addEventListener('phemacast:presentation-changed',follow);
 mount();
 // The dispose function is also the container's handle on the open view: the actions it offers AI apps, and a way to
 // ask it to take one (the container checks each call before it gets here).
 const dispose=()=>{closed=true;removeEventListener('phemacast:presentation-changed',follow);stale.remove();node.dispose();};
 return Object.assign(dispose,{action:(name,input,options)=>node.action(name,input,options),actions:()=>node.actions,mountId:()=>node.mountId});
}
