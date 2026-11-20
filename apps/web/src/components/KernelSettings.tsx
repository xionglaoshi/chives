import {useState,useEffect} from 'react';
import {appPath} from '../appPath';
import {BotAssets} from './BotAssets';
import './KernelSettings.css';
interface ModelSettings {connection:string;model:string;defaultModel:string;models:{id:string;label:string;model:string}[]}
export function KernelSettings({id,onSave}:{id:string;onSave:()=>void}){
  const url=appPath('/api/bots/'+encodeURIComponent(id)+'/model');
  const [config,setConfig]=useState<ModelSettings|null>(null);
  const [choice,select]=useState('');
  const [model,setModel]=useState('');
  const [notice,note]=useState('');
  useEffect(()=>{
    const abort=new AbortController();
    fetch(url,{signal:abort.signal}).then(async r=>{
      if(!r.ok)throw Error();
      const data:ModelSettings=await r.json();
      setConfig(data);select(data.connection||(data.model?'custom':''));setModel(data.model);
    }).catch(()=>{if(!abort.signal.aborted)note('无法读取模型配置');});
    return ()=>abort.abort();
  },[url]);
  async function save(){
    try{
      const response=await fetch(url,{method:'PUT',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({connection:choice==='custom'?'':choice,model:choice==='custom'?model.trim():''})});
      if(!response.ok)throw Error((await response.json()).error?.message||'保存失败');
      note('已保存，下次任务生效');onSave();
    }catch(e){note(e instanceof Error?e.message:'连接失败');}
  }
  return <section aria-label="Bot 模型与资产">{config&&<><label>Bot 模型 <select aria-label="Bot 模型" value={choice} onChange={e=>select(e.target.value)}>
    <option value="">跟随全局默认 · {config.defaultModel}</option>
    {config.models.map(m=><option value={m.id} key={m.id}>{m.label} · {m.model}</option>)}
    <option value="custom">指定当前供应商的模型 ID</option></select></label>
    {choice==='custom'&&<label>模型 ID <input value={model} onChange={e=>setModel(e.target.value)}/></label>}
    <button disabled={choice==='custom'&&!model.trim()} onClick={()=>void save()}>保存模型</button></>}
    <span role="status">{notice}</span><BotAssets id={id} onSave={onSave}/></section>;
}
