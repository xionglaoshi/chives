import {useEffect,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {desk, type Preferences} from './deskApi';
import {appPath} from '../appPath';
export type Save=(patch:Partial<Preferences>)=>Promise<void>;
export function Row({title,hint,children}:{title:string;hint?:string|undefined;children:ReactNode}){
 return <div className="desk-row"><div><strong>{title}</strong>{hint&&<p>{hint}</p>}</div>{children}</div>;
}
export function Picker({label,value,choices,onChange}:{label:string;value:string;choices:string[][];onChange:(s:string)=>void}){
 return <select aria-label={label} value={value} onChange={e=>onChange(e.target.value)}>{choices.map(([v,n])=><option key={v} value={v}>{n}</option>)}</select>;
}
export function ProfileCard({p,save}:{p:Preferences;save:Save}){
 const [draft,set]=useState({name:p.name,email:p.email,phone:p.phone,avatar:p.avatar});const [msg,notice]=useState('');
 const avatar=async(file?:File)=>{if(!file)return;try{
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>6000000)throw Error('请选择 6 MB 以内的 PNG、JPEG 或 WebP 图片');
  const image=await createImageBitmap(file);const canvas=document.createElement('canvas');canvas.width=192;canvas.height=192;
  const side=Math.min(image.width,image.height);canvas.getContext('2d')!.drawImage(image,(image.width-side)/2,(image.height-side)/2,side,side,0,0,192,192);image.close();set({...draft,avatar:canvas.toDataURL('image/png')});notice('头像已就绪，保存后生效');
 }catch(e){notice(String(e));}};
 return <form onSubmit={async e=>{e.preventDefault();try{await save(draft);notice('用户资料已保存');}catch(e){notice(String(e));}}}>
 <div className="desk-profile"><div className="desk-avatar">{draft.avatar?<img alt="用户头像" src={draft.avatar}/>:<span>{draft.name.slice(0,1)||'我'}</span>}</div><div><strong>{draft.name||'本机用户'}</strong><p>您的个人资料仅用于为您提供服务，未经您的同意，Chives 不会向第三方披露。</p><label className="desk-upload">更换头像<input type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>void avatar(e.target.files?.[0])}/></label></div></div>
 {([['name','名称','text'],['email','邮箱','email'],['phone','电话','tel']] as const).map(([key,title,type])=><Row key={key} title={title}><input type={type} aria-label={title} maxLength={180} value={draft[key]} onChange={e=>set({...draft,[key]:e.target.value})} placeholder={'填写'+title}/></Row>)}
 <div className="desk-actions"><span role="status">{msg}</span><button className="desk-primary">保存资料</button></div></form>;
}
type History={questions:{content:string;date:string}[];stocks:{code:string;name:string}[];memories:{bot:string;title:string;body:string}[]};
export function UserHistory(){const [h,set]=useState<History|null>(null),[err,error]=useState('');
 useEffect(()=>{void desk<History>('userdata').then(set).catch(e=>error(e.message));},[]);
 if(!h)return <p role="status">{err||'正在读取研究记录…'}</p>;
 const groups:[string,string[]][]=[['Bot 记忆',h.memories.map(m=>m.bot+' · '+m.title+'：'+m.body)],['研究过的股票',h.stocks.map(s=>[s.name,s.code].filter(Boolean).join(' · '))],['问过的问题',h.questions.map(q=>q.content) ]]; return <>{groups.map(([k,v])=><section className="desk-card" key={String(k)}><h3>{k} <small>{v.length}</small></h3>{(v as string[]).length?<ul>{(v as string[]).map((t,i)=><li key={i}>{t}</li>)}</ul>:<p>还没有相关记录。</p>}</section>)}</>;
}
export function DisplayPrefs({p,save}:{p:Preferences;save:Save}){
 const select=(key:keyof Preferences,title:string,hint:string,choices:string[][])=><Row title={title} hint={hint}><Picker label={title} value={String(p[key])} onChange={s=>void save({[key]:s}).catch(()=>{})} choices={choices}/></Row>;
 return <>{select('locale',p.locale==='en-US'?'Language / 语言':'语言','用于设置导航、Bot 回答和时间格式。',[['zh-CN','简体中文'],['en-US','English']])}{select('timezone','显示时区','用于对话时间；交易日仍按北京时间计算。',['Asia/Shanghai','Asia/Hong_Kong','Asia/Tokyo','America/New_York','Europe/London','UTC'].map(s=>[s,s]))}{select('density','样式','调整列表行距。',[['comfortable','舒适'],['compact','紧凑']])}{select('fontSize','字体大小','调整工作台阅读尺寸。',[['small','小'],['standard','标准'],['large','大']])}</>;
}
export function Behavior({p,save,page}:{p:Preferences;save:Save;page:string}){
 const check=(key:keyof Preferences,label:string,hint:string)=><Row title={label} hint={hint}><input aria-label={label} type="checkbox" role="switch" checked={!!p[key]} onChange={e=>void save({[key]:e.target.checked}).catch(()=>{})}/></Row>;
 return page==='chat'?<>{check('showProcess','显示实时思考摘要','显示内核公开返回的推理片段。')}{check('showTools','显示工具调用','在对话中展开本轮工具执行步骤。')}<Row title="任务执行期间的新消息" hint="排队会等本轮结束。优先引导会结束当前轮次，优先处理新要求。"><Picker label="新消息方式" value={p.busyMode} onChange={v=>void save({busyMode:v}).catch(()=>{})} choices={[['queue','顺序排队'],['interrupt','优先引导']]}/></Row></>:<>
 {check('attachmentsRead','向 Bot 提供工作区附件','允许将选中的工作区文件随消息交给 Bot 阅读。')}{check('workspaceWrite','工作区写入','控制本地报告保存工具和 dsh 工作区写入模式。')}{check('databaseRead','查询本地资料库','控制 Bot 的表格抽样查询工具。')}{check('memoryWrite','写入 Bot 记忆','关闭后只允许读取已有记忆。')}{check('portfolioAccess','访问持仓服务','关闭后下轮任务不再挂载私人持仓 MCP。')}</>;
}
const helpItems=[
 ['怎样让 Bot 按我的投资习惯作答？','在「风格评估」完成问卷。获准读取用户画像的 Bot 会用这些偏好解释机会和风险。'],
 ['怎样找到以前和 Bot 聊过的内容？','在侧栏搜索历史会话，点击结果可跳到原消息。也可以直接从已在岗Bot列表打开该 Bot，接着之前的对话聊。'],
 ['内核与模型有什么区别？','内核执行任务、调度工具。模型提供推理。Chives 统一使用 dsh。Bot 可以继承全局模型，也可以选择自己的模型连接。'],
 ['消息发送到哪里？','应用内通知、浏览器和系统通知分别控制。通讯频道需要验证机器人身份、指定目标会话并启用投递。'],
 ['怎样迁移到另一台 Mac？','在「备份及导入」下载个性化数据，在目标机导入。聊天和报告索引另有研究记录导出。模型及通讯密钥需在目标机重新授权。'],
 ['为什么有些组件无法更新？','只有上游仓库发布的文件可以更新。存在本地开发改动时，Chives 会显示冲突，供开发者核对。'],
];
export function HelpDesk(){
 const [query,setQuery]=useState('');
 const terms=query.trim().toLowerCase().split(/\s+/).filter(Boolean);
 const matches=helpItems.filter(item=>{
   const text=item.join(' ').toLowerCase();
   return terms.every(term=>text.includes(term));
 });
 return <>
   <input className="desk-help-search" type="search" aria-label="搜索技术文档"
     placeholder="搜索本页问题或答案" value={query} onChange={event=>setQuery(event.target.value)}/>
   {matches.map(([question,answer])=><details className="desk-faq" key={question}>
     <summary>{question}</summary><p>{answer}</p>
   </details>)}
   {!matches.length&&<p role="status">没有找到匹配的问题，试试其他关键词。</p>}
 </>;
}
export function Backup(){
 const picker=useRef<HTMLInputElement>(null);
 const [msg,set]=useState(''),[file,choose]=useState<File|null>(null),[busy,wait]=useState(false);
 async function run(restore=false){wait(true);try{if(restore&&file){const b=JSON.parse(await file.text());const result=await desk<{files:number}>('restore','POST',b);set('已恢复 '+result.files+' 个个性化文件，刷新工作台后生效');choose(null);}else{const b=await desk('backup');const a=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify(b,null,2)],{type:'application/json'}));a.href=url;a.download='Chives-个性化备份-'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),5000);set('个性化备份已生成');}}catch(e){set(String(e));}finally{wait(false);}}
 return <>
   <div className="desk-backup-rows">
     <Row title="备份个人配置" hint="包含资料、持仓账本、画像、外观、消息偏好及 Bot 记忆。">
       <button className="desk-backup-action" disabled={busy} onClick={()=>void run()}>下载备份</button>
     </Row>
     <Row title="导入个人配置" hint="覆盖备份中的同名项目。应用前会在本机留存一份当前配置。">
       <input ref={picker} hidden aria-label="选择个性化备份" type="file" accept=".json" onChange={e=>{
         const selected=e.currentTarget.files?.[0];if(selected)choose(selected);
         e.currentTarget.value='';
       }}/>
       <button type="button" className="desk-backup-action" disabled={busy} onClick={()=>picker.current?.click()}>选择文件</button>
     </Row>
     {file&&<button className="desk-primary" disabled={busy} onClick={()=>void run(true)}>确认导入 {file.name}</button>}
     <Row title="研究记录" hint="单独导出会话、任务和交付记录索引。">
       <a className="desk-download-link desk-backup-action" href={appPath('/api/export')} download>导出研究记录</a>
     </Row>
   </div>
   {msg&&<p role="status">{msg}</p>}
 </>;
}
const componentNames:Record<string,string>={app:'Chives 主体',skills:'技能',tools:'投研工具',factors:'因子库',databases:'随仓发布的数据库资料'};
const updateStates:Record<string,string>={unpublished:'仓库尚未发布',current:'已是最新版本',conflict:'存在本地改动，请核对差异',available:'可更新'};
type UpdateSnapshot={items:{id:string;state:string;count:number}[];updated?:string[]};

export function Updates({auto,save}:{auto:boolean;save:Save}){
 const [snapshot,setSnapshot]=useState<UpdateSnapshot|null>(null);
 const [message,setMessage]=useState(''),[pending,setPending]=useState('');
 async function toggle(enabled:boolean){
   setPending('toggle');
   try{await save({autoUpdateOnCheck:enabled});}catch(e){setMessage(String(e));}
   finally{setPending('');}
 }
 async function run(id?:string){
   setPending(id??'check');setMessage('');
   try{
     const action=id?'update':auto?'check-and-update':'check';
     const result=await desk<UpdateSnapshot>('updates','POST',{action,id});
     setSnapshot(result);
     const selected=result.items.filter(item=>!id||id==='all'||item.id===id);
     const updated=result.updated??[];
     const text=updated.length?'已更新'+updated.map(key=>componentNames[key]).join('、')+'。':
       id&&id!=='all'?componentNames[id]+'：'+updateStates[selected[0]!.state]+'。':'已完成检查。';
     const conflict=selected.some(item=>item.state==='conflict');
     setMessage(text+(conflict&&(!id||id==='all')?'有本地改动的组件已保留。':'')+
       (updated.includes('app')?'请重新启动工作台以加载主体更新。':''));
   }catch(e){setMessage(String(e));}finally{setPending('');}
 }
 return <>
   <Row title="自动更新" hint="开启后，点击「检查更新」会将可更新的组件安装到本机。">
     <input type="checkbox" role="switch" aria-label="自动更新" checked={auto} disabled={!!pending} onChange={e=>void toggle(e.target.checked)}/>
   </Row>
   <div className="desk-actions">
     <button disabled={!!pending} onClick={()=>void run()}>{pending==='check'?'正在检查…':'检查更新'}</button>
     {snapshot?.items.some(item=>item.state==='available')&&<button className="desk-primary" disabled={!!pending} onClick={()=>void run('all')}>全部更新</button>}
   </div>
   {Object.entries(componentNames).map(([id,name])=>{
     const item=snapshot?.items.find(item=>item.id===id);
     const hint=item?.state==='available'?'可更新 '+item.count+' 个文件':item?updateStates[item.state]:'尚未检查';
     return <Row key={id} title={name} hint={hint}><button disabled={!!pending} aria-label={'更新'+name} onClick={()=>void run(id)}>{pending===id?'更新中…':'更新'}</button></Row>;
   })}
   <p role="status">{message}</p>
 </>;
}
