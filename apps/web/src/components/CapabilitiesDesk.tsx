import {useEffect,useState} from 'react';
import {desk} from './deskApi';
import './CapabilitiesDesk.css';

type Connection={id:string;name:string;source:string;transport:string;tools:string[];enabled:boolean;revision:string;bots:string[]};
type Template={id:string;name:string;description:string;hint:string;docs:string};
type Directory={connections:Connection[];templates:Template[];official:string[];approvedOnly:boolean;bots:{id:string;name:string}[]};
type Editor={source:string;entry?:Connection;remove?:boolean};
const example=JSON.stringify({mcpServers:{research:{url:'https://example.com/mcp',headers:{Authorization:'Bearer YOUR_KEY'}}}},null,2);

function configFromJson(text:string,name:string){
  let value;
  try{value=JSON.parse(text);}catch{throw Error('配置需要使用有效的 JSON。');}
  if(!value||typeof value!=='object'||Array.isArray(value))throw Error('请输入 MCP 服务配置对象。');
  if('mcpServers' in value){
    if(!value.mcpServers||typeof value.mcpServers!=='object'||Array.isArray(value.mcpServers)||Object.keys(value.mcpServers).length!==1)
      throw Error('每次请选择一个 MCP 服务添加。');
    const [key,spec]=Object.entries(value.mcpServers)[0]!;
    return {name:name.trim()||key,spec};
  }
  return {name:name.trim(),spec:value};
}
export function CapabilitiesDesk({onOpenProfile}:{onOpenProfile:(id:string)=>void}){
  const [data,setData]=useState<Directory>(),[tab,setTab]=useState('installed'),[editor,edit]=useState<Editor>();
  const [name,setName]=useState(''),[json,setJson]=useState(''),[key,setKey]=useState(''),[url,setUrl]=useState('');
  const [mode,setMode]=useState('http'),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
  const reload=async()=>setData(await desk<Directory>('capabilities'));
  useEffect(()=>{void reload().catch(e=>setMessage(e.message));},[]);
  function close(){edit(undefined);setJson('');setKey('');setUrl('');}
  useEffect(()=>{
    if(!editor)return;
    function escape(e:KeyboardEvent){if(e.key==='Escape'&&!busy)close();}
    window.addEventListener('keydown',escape);return ()=>window.removeEventListener('keydown',escape);
  },[editor,busy]);
  function open(next:Editor){
    setName(next.entry?.name??'');setMode(next.entry?.transport==='stdio'||next.entry?.transport==='SSE'?'json':'http');
    setJson('');setKey('');setUrl('');setMessage('');edit(next);
  }
  async function perform(action:string,entry=editor?.entry){
    setBusy(true);setMessage('');
    try{
      const body:Record<string,unknown>={action};
      if(entry)Object.assign(body,{id:entry.id,revision:entry.revision});
      if(action==='toggle')body.enabled=!entry?.enabled;
      if(['add','replace','probe'].includes(action)&&editor){
        body.source=editor.source;
        if(editor.source!=='custom')body.key=key;
        else if(mode==='json')Object.assign(body,configFromJson(json,name));
        else Object.assign(body,{name,spec:{url,headers:key?{Authorization:'Bearer '+key}:{}}});
      }
      const result=await desk<{tools?:string[]}>('capabilities','POST',body);
      if(action!=='probe'&&action!=='test'){await reload();close();setTab('installed');}
      if(['probe','test'].includes(action))setMessage('连接成功，发现 '+result.tools!.length+' 个工具。'+result.tools!.slice(0,8).join('、'));
      else setMessage(({delete:'已移除连接',add:'已添加服务，可在 Bot 档案中授权。',replace:'连接已更新',toggle:'服务状态已更新'})[action]??'已保存');
    }catch(e){setMessage(e instanceof Error?e.message:'操作失败');}finally{setBusy(false);}
  }
  const preset=data?.templates.find(t=>t.id===editor?.source);
  const status=message&&<p role="status" className="mcp-status">{message}</p>;
  return <div className="mcp-desk">
    <div className="mcp-toolbar"><div className="mcp-tabs" aria-label="服务分类">{[['installed','已添加'],['market','MCP 市场'],['builtin','官方内置']].map(([id,label])=>
      <button key={id} aria-pressed={tab===id} onClick={()=>{setTab(id!);setMessage('');}}>{label}</button>)}</div>
      {data&&!data.approvedOnly&&<button className="desk-primary" onClick={()=>open({source:'custom'})}>＋ 手动添加</button>}</div>
    {!data&&!message&&<p>正在读取服务…</p>}
    {data&&tab==='installed'&&<>{!data.connections.length&&<div className="mcp-empty"><strong>尚未添加第三方服务</strong><p>从市场选择服务{data.approvedOnly?'':'，或导入供应商提供的 MCP 配置'}。Bot 的服务权限由开发者维护。</p><button onClick={()=>setTab('market')}>浏览 MCP 市场</button></div>}
      {data.connections.map(c=><article className="mcp-card" key={c.id}><div className="mcp-heading"><strong>{c.name}</strong>
        <label><input type="checkbox" role="switch" aria-label={'启用 '+c.name} checked={c.enabled} disabled={busy} onChange={()=>void perform('toggle',c)}/></label></div>
        <p>{c.transport} · {c.enabled?'已启用':'已停用'} · {c.bots.length?'已授权给'+c.bots.join('、'):'尚未授权给 Bot'}</p>
        <details><summary>{c.tools.length} 个工具</summary><ul>{c.tools.map(t=><li key={t}>{t}</li>)}</ul></details>
        <div className="mcp-actions"><button disabled={busy} onClick={()=>void perform('test',c)}>测试连接</button><button disabled={busy} onClick={()=>open({source:c.source,entry:c})}>{c.source==='custom'?'编辑配置':'更换密钥'}</button>
        <button disabled={busy} onClick={()=>open({source:c.source,entry:c,remove:true})}>移除</button></div></article>)}
      {!!data.connections.length&&<section><h3>查看 Bot 工具配置</h3><div className="mcp-actions">{data.bots.map(b=><button key={b.id} onClick={()=>onOpenProfile(b.id)}>{b.name}</button>)}</div></section>}</>}
    {data&&tab==='market'&&<>{data.templates.map(t=>{const added=data.connections.some(c=>c.source===t.id);return <article className="mcp-card" key={t.id}><div className="mcp-heading"><strong>{t.name}</strong><button disabled={added} onClick={()=>open({source:t.id})}>{added?'已添加':'添加'}</button></div><p>{t.description}</p><a href={t.docs} target="_blank" rel="noreferrer">供应商说明 ↗</a></article>;})}</>}
    {data&&tab==='builtin'&&<><p>这些接口由 Chives 维护。各 Bot 按自己的授权调用。</p><div className="mcp-official">{data.official.map(n=><code key={n}>{n}</code>)}</div></>}
    {!editor&&status}
    {editor&&<div className="desk-modal-layer"><section className="desk-modal" role="dialog" aria-modal="true" aria-labelledby="mcp-title">
      <button className="desk-close" aria-label="关闭" disabled={busy} onClick={()=>{close();setMessage('');}}>×</button>
      <h2 id="mcp-title">{editor.remove?'移除 '+editor.entry!.name:preset?preset.name:editor.entry?'编辑 MCP 配置':'手动添加 MCP'}</h2>
      {editor.remove?<><p>移除后，已授权的 Bot 也会失去这项能力。</p><button disabled={busy} onClick={()=>void perform('delete')}>确认移除</button></>:
        <form onSubmit={e=>{e.preventDefault();void perform(editor.entry?'replace':'add');}}>
          {preset?<><p>{preset.hint}</p><label>API Key<input autoFocus type="password" required autoComplete="new-password" value={key} onChange={e=>setKey(e.target.value)}/></label></>:
            <><label>接入方式<select value={mode} onChange={e=>setMode(e.target.value)}><option value="http">远程 HTTP 服务</option><option value="json">导入配置 JSON</option></select></label>
            <label>服务名称<input required={mode==='http'} value={name} placeholder={mode==='json'?'可沿用配置中的服务名':'用于 Bot 授权列表'} onChange={e=>setName(e.target.value)}/></label>
            {mode==='http'?<><label>服务地址<input required type="url" placeholder="https://…/mcp" value={url} onChange={e=>setUrl(e.target.value)}/></label>
            <label>Bearer Token（可选）<input type="password" autoComplete="new-password" value={key} onChange={e=>setKey(e.target.value)}/></label></>:
            <><label>MCP 配置<textarea required rows={9} spellCheck={false} placeholder={example} value={json} onChange={e=>setJson(e.target.value)}/></label>
            <p>支持 HTTP、SSE 和 stdio。stdio 会在本机运行指定的程序，请核对命令和来源。</p></>}
            {editor.entry&&<p>请重新填写完整配置，已有凭证不会回显。</p>}</>}
          <div className="mcp-actions">{!editor.entry&&<button disabled={busy} type="button" onClick={()=>void perform('probe')}>测试连接</button>}<button className="desk-primary" disabled={busy}>{busy?'连接中…':'验证并保存'}</button></div>
        </form>}{status}</section></div>}
  </div>;
}
