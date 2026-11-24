import { askAiPrompts, fillAskPrompt } from '../utils/askAiPrompts';
import content from '../../../../packages/chives-terminal/chives_terminal/workbench-content.json';
import {useEffect,useState,type ReactNode} from 'react';
import {appPath} from '../appPath';
import './market-news.css';

type Entry = {title:string;url:string;source:string;publishedAt:string|null;day:string|null;region:string};
type Edition = {updatedAt:string;entries:Entry[]};
type Snapshot = {domestic:Edition|null;global:Edition|null};
const clock = new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});

type AskButton = (title:string,ready:boolean,prompt:string,markdown:()=>string)=>ReactNode;

function NewsCard({title,promptKey,edition,failed,ask}:{title:string;promptKey:'国内资讯'|'国际资讯';edition:Edition|null;failed:boolean;ask:AskButton}){
  const entries=edition?.entries.slice(0,20)??[];
  const prompt = fillAskPrompt(askAiPrompts['行情看板'][promptKey], {新闻条数: entries.length});
  const markdown=()=>[
    '榜单更新时间（北京时间）：'+clock.format(new Date(edition!.updatedAt)),
    ...entries.map((entry,index)=>[
      '### '+(index+1)+'. '+entry.title,
      [entry.source,entry.region,entry.publishedAt?clock.format(new Date(entry.publishedAt)):entry.day].filter(Boolean).join(' · '),
      '原文：<'+entry.url+'>'
    ].join('\n\n'))
  ].join('\n\n');

  return <section className="mb-panel market-news-card">
    <header><h2>{title}</h2><div className="mb-panel-actions">{ask(title,entries.length>0,prompt,markdown)}</div></header>
    {edition ? <>
      <ul>{entries.map((entry)=><li key={entry.url}>
        <a href={entry.url} target="_blank" rel="noopener noreferrer">{entry.title}</a>
        <small>{[entry.source,entry.region,entry.publishedAt?clock.format(new Date(entry.publishedAt)):entry.day].filter(Boolean).join(' · ')}</small>
      </li>)}</ul>
    </>:<small role="status">{failed?'暂时无法读取资讯':'正在读取资讯…'}</small>}
  </section>;
}

export function MarketNews({ask}:{ask:AskButton}){
  const [data,setData]=useState<Snapshot|null>(null);
  const [failed,setFailed]=useState(false);
  useEffect(()=>{
    const controller=new AbortController();
    async function refresh(){
      try {
        const response=await fetch(appPath('/market-news.json'),{signal:controller.signal,cache:'no-store'});
        if(!response.ok)throw new Error('news unavailable');
        const snapshot:Snapshot=await response.json();
        if(!controller.signal.aborted){setData(snapshot);setFailed(false);}
      } catch {if(!controller.signal.aborted)setFailed(true);}
    }
    void refresh();
    const timer=window.setInterval(()=>void refresh(),60000);
    return ()=>{controller.abort();window.clearInterval(timer);};
  },[]);
  return <>
    <NewsCard title={content.market.domestic} promptKey="国内资讯" edition={data?.domestic??null} failed={failed||data!==null} ask={ask}/>
    <NewsCard title={content.market.global} promptKey="国际资讯" edition={data?.global??null} failed={failed||data!==null} ask={ask}/>
  </>;
}
