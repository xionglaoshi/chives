import {useEffect,useState} from 'react';
import type {ActiveRoutineDto,ProactiveSettingsDto} from '@chives/server/protocol';
import {fetchManagedRoutines,toggleAllRoutines,updateRoutine} from '../api/client';
import {BotAvatar} from '../brand/BotAvatar';
import './TaskManagement.css';

interface Props {
  proactive: ProactiveSettingsDto|null;
  error: string|null;
  onObserve: (flag:boolean)=>Promise<void>;
  onOpenProfile: (botId:string)=>void;
}

export function TaskManagement({proactive,error,onObserve,onOpenProfile}:Props){
  const [rows,setRows]=useState<ActiveRoutineDto[]|null>(null);
  const [pending,setPending]=useState(false),[failure,setFailure]=useState(''),[retry,setRetry]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();
    setFailure('');
    fetchManagedRoutines(controller.signal).then(items=>{
      if(!controller.signal.aborted)setRows(items);
    }).catch(e=>{if(!controller.signal.aborted)setFailure(e.message);});
    return ()=>controller.abort();
  },[retry]);
  async function change(enabled:boolean,id?:string){
    setPending(true);setFailure('');
    try{
      if(id===undefined)setRows(await toggleAllRoutines(enabled));
      else{
        const updated=await updateRoutine(id,{enabled});
        setRows(items=>items?.map(r=>r.id===id?{...r,...updated}:r)??null);
      }
    }catch(e){setFailure(e instanceof Error?e.message:'保存失败，请重试');}
    finally{setPending(false);}
  }
  const count=rows?.filter(r=>r.enabled).length??0,total=rows?.length??0;
  const allEnabled=total>0&&count===total;
  const blocked=!proactive ? '' : !proactive.autoAnalysis?'自动分析权限已关闭。':!proactive.enabled?'主动消息已关闭。':proactive.observeOnly?'观察模式已开启。':'';
  return <div className="routine-manager">
    <div className="routine-manager__header">
      <div><h3>全部定时任务</h3><p>{rows ? total+' 项任务 · 已开启 '+count+' 项' : failure?'任务列表读取失败':'正在读取任务…'}</p></div>
      <div className="routine-manager__controls">
        {count>0&&!allEnabled&&<button disabled={pending} onClick={()=>void change(false)}>全部关闭</button>}
        <input type="checkbox" role="switch" aria-label="全部定时任务" checked={allEnabled}
          disabled={!total||pending} onChange={e=>void change(e.currentTarget.checked)}/>
      </div>
    </div>
    {failure&&<p role="alert">{failure} <button disabled={pending} onClick={()=>setRetry(n=>n+1)}>重新读取</button></p>}
    {error&&<p role="alert">{error}</p>}
    {blocked&&<p className="routine-manager__note">{blocked}已开启的定时任务暂停自动执行。</p>}
    {rows&&(!total?<p>还没有定时任务。</p>:<ul className="routine-manager__list">
      {rows.map(r=><li key={r.id}>
        <BotAvatar emblem={r.botAvatar?.emblem??'crown'} tone={r.botAvatar?.tone??'gold'} name={r.botName} size={18}/>
        <div className="routine-manager__task"><strong>{r.title}</strong>
          <div className="routine-manager__meta"><button title={'查看'+r.botName+'档案'} onClick={()=>onOpenProfile(r.botId)}>{r.botName}</button>
          <span>{r.scheduleText}{r.tradingDaysOnly?' · 仅交易日':''}</span></div></div>
        <input type="checkbox" role="switch" aria-label={r.botName+' · '+r.title} checked={r.enabled}
          disabled={pending} onChange={e=>void change(e.currentTarget.checked,r.id)}/>
      </li>)}
    </ul>)}
    <details className="routine-manager__advanced"><summary>高级</summary>
      <div className="routine-manager__header"><label htmlFor="routine-observe"><strong>观察模式</strong>
      <p>记录行情触发，暂停自动分析和定时运行。关闭后按原计划继续。</p></label>
      <input id="routine-observe" aria-label="观察模式" type="checkbox" role="switch" checked={proactive?.observeOnly??false}
        disabled={!proactive||pending} onChange={async e=>{setPending(true);try{await onObserve(e.currentTarget.checked);}finally{setPending(false);}}}/></div>
    </details>
  </div>;
}
