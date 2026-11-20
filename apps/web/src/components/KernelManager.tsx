import { useEffect, useState } from 'react';
import dshIcon from '../brand/dsh.png?inline';
import { appPath } from '../appPath';

interface Version {current:string;latest:string|null;available:boolean;busy:boolean}
const url=appPath('/api/settings/kernels');
export function KernelManager(){
  const [info,setInfo]=useState<Version|null>(null);
  const [pending,setPending]=useState('');
  const [message,setMessage]=useState('');
  useEffect(()=>{
    const controller=new AbortController();
    fetch(url,{signal:controller.signal}).then(async r=>{
      if(!r.ok)throw Error();
      setInfo(await r.json());
    }).catch(()=>{if(!controller.signal.aborted)setMessage('无法读取内核版本');});
    return ()=>controller.abort();
  },[]);
  async function change(action:'check'|'upgrade'){
    setPending(action);setMessage('');
    try{
      const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Chives-Kernel-Manager':'local'},
        body:JSON.stringify({action,version:info?.latest})});
      const result=await r.json();
      if(!r.ok)throw Error(result.error?.message || '操作失败');
      setInfo(result);
      setMessage(action==='upgrade'?'升级完成，后续任务使用新版本。':result.available?'发现可选更新。':'当前已是最新版本。');
    }catch(error){setMessage(error instanceof Error?error.message:'连接失败');}finally{setPending('');}
  }
  return <section aria-label="dsh 版本与升级"><div className="desk-kernel">
    <img src={dshIcon} alt=""/><div><h3>DeepSeek Harness</h3>
    <p>当前版本 {info?.current??'读取中…'}{info?.latest && ' · 最新版本 '+info.latest}</p></div></div>
    <p className="settings__row-hint">所有 Bot 共用 dsh。检查后由你选择是否升级，进行中的研究会先完成。</p>
    <div className="desk-actions"><button disabled={!!pending} onClick={()=>void change('check')}>{pending==='check'?'检查中…':'检查更新'}</button>
    {info?.available && <button disabled={!!pending||info.busy} onClick={()=>void change('upgrade')}>{pending==='upgrade'?'正在安装并验证…':'升级到 '+info.latest}</button>}</div>
    <p role="status">{message}</p></section>;
}
