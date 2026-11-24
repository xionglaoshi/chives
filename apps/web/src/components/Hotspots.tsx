import { workbenchTools } from '../utils/routes';
import { askAiPrompts, fillAskPrompt } from '../utils/askAiPrompts';
import content from '../../../../packages/chives-terminal/chives_terminal/workbench-content.json';
import {useEffect,useState} from 'react';
import type {AskExpert} from './askExpert';
import {appPath} from '../appPath';
import './market-board.css';
import './hotspots.css';

type Entry={name:string;code:string;url:string;metric:string;r5?:number;r30?:number;shareChange?:number|null};
type Board={note:string;url:string;title:string;asOf:string;rows:Entry[];columns:[string,string]};
type Payload={snapshot:{publishedAt:string;boards:Record<string,Board>;retained:string[]}|null;status:{state:string;startedAt?:string;finishedAt?:string}};
const boardPrompts: Partial<Record<string, {提示词: string}>> = askAiPrompts['热门榜单'];
const headers={'x-chives-kernel-manager':'local'};
const api=appPath('/api/settings/desk/hotspots');
function changeValue(id:string,r:Entry){
  const fields:Record<string,string>=content.hotspots.changeField;
  const field=fields[id]??content.hotspots.defaultChangeField;
  return r[field as 'shareChange'|'r5'|'r30'];
}
function percent(change:number|undefined|null,world=false){
  return change==null?(world?'待满五日':'暂无数据'):(change>0?'+':'')+change.toFixed(2)+'%';
}
function boardFile(id:string,b:Board,published:string,retained:boolean){
  const cell=(s:string)=>s.replaceAll('|','｜').replace(/[\r\n]+/g,' ');
  const lines=['# '+b.title,'','数据日期：'+b.asOf+' · 发布版本：'+published+(retained?' · 沿用上期':''),'',b.note,'',
    ['排名',id==='global'?'板块':'股票','代码',...b.columns].join(' | '),'--- | --- | --- | --- | ---',
    ...b.rows.map((r,i)=>[String(i+1),r.name,r.code,r.metric,percent(changeValue(id,r),id==='global')].map(cell).join(' | ')),
    '','数据来源：'+b.url];
  return new File([lines.join('\n')+'\n'],b.title+'-'+b.asOf+'.md',{type:'text/markdown'});
}
function stockQuoteUrl(code:string){
  const exchange=code.startsWith('6')?'sh':/^[489]/.test(code)?'bj':'sz';
  return 'https://quote.eastmoney.com/'+exchange+code+'.html';
}
function Ranking({id,b,onAsk}:{id:string;b:Board;onAsk:()=>void}){
  const world=id==='global';
  const primaryColor=id==='out'?'mb-down':id==='in'||id==='private'?'mb-up':'';
  return <section className="mb-panel hs-panel"><header><h2>{b.title}</h2><button className="hs-ask" disabled={!Object.hasOwn(boardPrompts, id)} onClick={onAsk}>问AI</button></header>
    <table><thead><tr><th scope="col">{world?'板块':'股票'}</th>{b.columns?.map(label=><th key={label} scope="col">{label}</th>)}</tr></thead>
    <tbody>{b.rows.map(r=>{
      const change=changeValue(id,r);
      return <tr key={r.code}><td>{world?<strong>{r.name}</strong>:<a href={stockQuoteUrl(r.code)} target="_blank" rel="noreferrer">{r.name}</a>}<small>{r.code}</small></td>
        <td className={primaryColor}>{r.metric}</td><td className={(change??0)>0?'mb-up':(change??0)<0?'mb-down':''}>{percent(change,world)}</td></tr>;
    })}</tbody></table></section>;
}
export function Hotspots({onAskExpert}:{onAskExpert:AskExpert}){
  function ask(id:string,b:Board){
    if(!data?.snapshot)return;
    const file=boardFile(id,b,data.snapshot.publishedAt,data.snapshot.retained.includes(id));
    const template = boardPrompts[id]?.提示词;
    if (template !== undefined) onAskExpert(fillAskPrompt(template, {榜单名: b.title}), file);
  }
  const [data,setData]=useState<Payload|null>(null),[error,setError]=useState(''),[pending,setPending]=useState(false);
  const running=pending||data?.status.state==='running';
  useEffect(()=>{
    const ctrl=new AbortController();let timer:number;
    async function read(){
      let busy=false;
      try{const r=await fetch(api,{headers,signal:ctrl.signal,cache:'no-store'});if(!r.ok)throw Error();
        const v:Payload=await r.json();busy=v.status.state==='running';if(!ctrl.signal.aborted){setData(v);setError('');}}
      catch{if(!ctrl.signal.aborted)setError('暂时无法读取榜单，正在重试');}
      finally{if(!ctrl.signal.aborted)timer=window.setTimeout(read,busy?1800:15000);}
    }
    void read();return ()=>{ctrl.abort();window.clearTimeout(timer);};
  },[pending]);
  async function update(){
    setPending(true);
    try{const r=await fetch(api,{method:'POST',headers});if(!r.ok)throw Error();
      setData(v=>v?{...v,status:{state:'running'}}:v);}
    catch{setError('更新任务启动失败，请重试');}finally{setPending(false);}
  }
  return <article className="market-board hotspots"><header className="mb-title"><div><small>工作台</small><h1>{workbenchTools.trends}</h1></div><div className="hs-actions"><small>{data?.snapshot?'发布于 '+new Date(data.snapshot.publishedAt).toLocaleString('zh-CN',{hour12:false}):''}</small><button disabled={running||!data} onClick={update}>{running?'正在生成…':'重新生成榜单'}</button></div></header>
    <div role="status">{error|| (data?.status.state==='error'?'本次更新未完成，保留最近发布版本。':data?.status.state==='partial'?'部分榜单沿用上次结果。':running?'后台更新中，您可以继续查看榜单。':'')}</div>
    {data?.snapshot?<div className="mb-grid">{Object.entries(data.snapshot.boards).map(([id,b])=><Ranking key={id} id={id} b={b} onAsk={()=>void ask(id,b)}/>)}</div>:<p>{data?'等待首版榜单发布':'正在读取本地榜单…'}</p>}</article>;
}
