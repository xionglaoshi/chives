import {useEffect,useState} from 'react';
import {appPath} from '../appPath';
import {desk} from './deskApi';
import './Watchlist.css';

type Estimate={valuationKind?:string;version:number;low:number|null;high:number|null;score:number|null;asOf:string;basis:string;invalidation:string;measuredAt:string;horizon:number};
type Entry={code:string;name:string;pending?:boolean;estimates:Estimate[]};
type Quote={price:number;changePct?:number;basis:string;as_of:string};
const fmt=new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2});
const stamp=(time:string)=>new Date(time).toLocaleString('zh-CN',{hour12:false});

function OutlookFaces({score}:{score:number}) {
  const direction=score>0?'up':score<0?'down':'neutral';
  const label=score>0?'看涨':score<0?'看跌':'中性';
  return <span className={`watchlist-faces watchlist-faces--${direction}`} role="img"
    aria-label={score===0?label:`${label} ${Math.abs(score)} 档`} title={label}>
    {Array.from({length:Math.max(1,Math.abs(score))},(_,index)=>
      <svg key={index} viewBox="0 0 24 24" width="20" height="20" fill="none"
        stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10"/>
        {score===0?<path d="M9.5 9a2.5 2.5 0 1 1 4 2c-1.2.8-1.5 1.2-1.5 2.2m0 3.3h.01"/>:<>
          <path d="M8 9h.01m8 0h.01"/>
          <path d={score>0?'M7.5 13.5c2 3.8 7 3.8 9 0':'M7.5 16c2-3 7-3 9 0m1-4.5v1'}/>
        </>}
      </svg>)}
  </span>;
}

function WatchQuote({code,latest}:{code:string;latest:Estimate|undefined}) {
  const [quote,setQuote]=useState<Quote|null>(null);
  useEffect(()=>{
    let active=true;
    const refresh=()=>void desk<Quote|null>('holdings','POST',{action:'quote',code})
      .then(result=>{if(active)setQuote(result);}).catch(()=>{if(active)setQuote(null);});
    refresh();
    const timer=window.setInterval(refresh,60000);
    return ()=>{active=false;window.clearInterval(timer);};
  },[code]);
  const bound=quote&&latest&&(latest.low!==null&&quote.price<latest.low?latest.low:
    latest.high!==null&&quote.price>latest.high?latest.high:null);
  if(!quote)return <>暂无行情</>;
  const change=quote.changePct;
  return <><strong>{fmt.format(quote.price)}</strong>{change!==undefined&&
    <span className={change>0?'watchlist-up':change<0?'watchlist-down':''}> {change>0?'+':''}{fmt.format(change)}%</span>}
    <small>{quote.basis} · {quote.as_of}</small>
    {bound&&<small>现价{quote.price>bound?'高于估值上限':'低于估值下限'} {fmt.format(Math.abs(quote.price/bound-1)*100)}%</small>}
  </>;
}

export function Watchlist({onConversation}:{onConversation:()=>void}) {
  const [entries,setEntries]=useState<Entry[]|null>(null);
  const [directory,setDirectory]=useState<Record<string,string>>({});
  const [search,setSearch]=useState('');
  const [adding,setAdding]=useState(false);
  const [busy,setBusy]=useState(false);
  const [notice,setNotice]=useState('');
  const refresh=async()=>setEntries(await desk<Entry[]>('watchlist'));
  useEffect(()=>{
    void refresh().catch(error=>setNotice(String(error)));
    const timer=window.setInterval(()=>void refresh().catch(()=>{}),3000);
    return ()=>window.clearInterval(timer);
  },[]);
  useEffect(()=>{
    if(!adding)return;
    const controller=new AbortController();
    void fetch(appPath('/holdings-securities.json'),{signal:controller.signal})
      .then(response=>{if(!response.ok)throw Error();return response.json();}).then(setDirectory)
      .catch(()=>{if(!controller.signal.aborted)setNotice('无法加载证券名录。');});
    return ()=>controller.abort();
  },[adding]);
  const keyword=search.trim().toUpperCase();
  const matches=keyword?Object.entries(directory).filter(([code,name])=>
    /\.((SH)|(SZ)|(BJ))$/.test(code)&&(code.startsWith(keyword)||name.includes(keyword))).slice(0,12):[];
  async function act(action:string,code?:string) {
    setBusy(true);setNotice('');
    try {
      const result=await desk<{added?:string[]}>('watchlist','POST',{action,code});
      if(action==='screen'){onConversation();return;}
      if(action==='add'){
        setAdding(false);setSearch('');
        setNotice(result.added?.length?'已加入用户关注。':'已在用户关注中。');
      }
      await refresh();
    }catch(error){setNotice(error instanceof Error?error.message:String(error));}
    finally{setBusy(false);}
  }
  return <section className="watchlist">
    <header><h1>用户关注</h1><div className="watchlist-actions">
      <button disabled={busy} onClick={()=>void act('screen')}>股票筛选器</button>
      <button disabled={busy} onClick={()=>setAdding(!adding)}>{adding?'收起添加':'添加关注'}</button>
    </div></header>
    {adding&&<div className="watchlist-search"><label>股票代码或名称
      <input autoFocus value={search} onChange={event=>setSearch(event.target.value)} placeholder="例如 600519 或 贵州茅台"/>
    </label>{matches.map(([code,name])=><button key={code} disabled={busy} onClick={()=>void act('add',code)}>{name} · {code}</button>)}
    {keyword&&!matches.length&&<small>未找到匹配的沪深北证券。</small>}</div>}
    {notice&&<p role="status">{notice}</p>}
    {entries===null?<p>正在读取关注列表…</p>:entries.length===0?<p>还没有关注的股票。可直接添加，也可请总调度筛选。</p>:
    <div className="watchlist-grid">
      <div className="watchlist-heading"><span>股票</span><span>行情</span><span>合理估值</span><span>后市判断</span><span>测算与操作</span></div>
      {entries.map(entry=>{
        const latest=entry.estimates.at(-1),score=latest?.score;
        return <article className="watchlist-row" key={entry.code}>
          <div><strong>{entry.name}</strong><small>{entry.code}</small></div>
          <div><WatchQuote code={entry.code} latest={latest}/></div>
          <div><small className="watchlist-mobile-label">合理估值</small>{latest
            ?latest.low===null||latest.high===null?'依据不足':`¥${fmt.format(latest.low)}–${fmt.format(latest.high)}`
            :'待测算'}{latest?.low!=null&&<small>{latest.valuationKind??'历史测算'}</small>}</div>
          <div><small className="watchlist-mobile-label">未来 20 个交易日</small>
            {score==null?(latest?'依据不足':'待测算'):<OutlookFaces score={score}/>}</div>
          <div className="watchlist-actions"><button disabled={busy||entry.pending} onClick={()=>void act('estimate',entry.code)}>{entry.pending?'测算中':'立刻测算'}</button>
            <button disabled={busy} onClick={()=>void act('remove',entry.code)}>移除</button>
            {latest&&<small>{stamp(latest.measuredAt)}</small>}</div>
        </article>;
      })}
    </div>}
  </section>;
}
