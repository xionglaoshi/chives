import {useEffect,useState} from 'react';
import {appPath} from '../appPath';
import {ValuationNotice,ValuationOutlook,ValuationRange,useValuationAccessDenied,type EstimateRange} from './ValuationRange';
import {desk} from './deskApi';
import './Watchlist.css';

type Entry={code:string;name:string;publicEstimate:EstimateRange|null};
type Quote={price:number;changePct?:number;basis:string};
const fmt=new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2});

function WatchPrices({code,latest}:{code:string;latest:EstimateRange|null|undefined}) {
  const [quote,setQuote]=useState<Quote|null>(null);
  useEffect(()=>{
    let active=true;
    const refresh=()=>void desk<Quote|null>('holdings','POST',{action:'quote',code})
      .then(result=>{if(active)setQuote(result);}).catch(()=>{if(active)setQuote(null);});
    refresh();
    const timer=window.setInterval(refresh,60000);
    return ()=>{active=false;window.clearInterval(timer);};
  },[code]);
  const price=quote?.price;
  const hasPrice=typeof price==='number' && Number.isFinite(price) && price>0;
  const change=quote?.changePct;
  return <>
    <div>{quote && hasPrice ? <>
      <strong>{fmt.format(price)}</strong>{change!==undefined &&
        <span className={change>0?'watchlist-up':change<0?'watchlist-down':''}> {change>0?'+':''}{fmt.format(change)}%</span>}
      <small>{quote.basis}</small>
    </> : '暂无行情'}</div>
    <div><small className="watchlist-mobile-label">AI估算的合理股价</small>
      <ValuationRange estimate={latest} price={price} showCurrency={false} showComparison/>
    </div>
  </>;
}

export function Watchlist({onConversation}:{onConversation:()=>void}) {
  const denied=useValuationAccessDenied();
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
      <button data-init-target="watchlist" disabled={busy} onClick={()=>setAdding(!adding)}>{adding?'收起添加':'添加关注'}</button>
    </div></header>
    <ValuationNotice denied={denied}/>
    {adding&&<div className="watchlist-search"><label>股票代码或名称
      <input autoFocus value={search} onChange={event=>setSearch(event.target.value)} placeholder="例如 600519 或 贵州茅台"/>
    </label>{matches.map(([code,name])=><button key={code} disabled={busy} onClick={()=>void act('add',code)}>{name} · {code}</button>)}
    {keyword&&!matches.length&&<small>未找到匹配的沪深北证券。</small>}</div>}
    {notice&&<p role="status">{notice}</p>}
    {entries===null?<p>正在读取关注列表…</p>:entries.length===0?<p>还没有关注的股票。可直接添加，也可请总经理筛选。</p>:
    <div className="watchlist-grid">
      <div className="watchlist-heading"><span>股票</span><span>行情</span><span>AI估算的合理股价</span><span>后市AI预测</span><span>测算与操作</span></div>
      {entries.map(entry=>{
        const latest=denied?null:entry.publicEstimate;
        return <article className="watchlist-row" key={entry.code}>
          <div><strong>{entry.name}</strong><small>{entry.code}</small></div>
          <WatchPrices code={entry.code} latest={latest}/>
          <div><small className="watchlist-mobile-label">后市AI预测</small>
            <ValuationOutlook estimate={latest}/></div>
          <div className="watchlist-row-actions">
            <button type="button" disabled={busy} title="同步已发布的合理股价"
              aria-label={'同步已发布估值 '+entry.name} aria-busy={busy} onClick={()=>void act('estimate',entry.code)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M20 7v5h-5M4 17v-5h5M5 8a8 8 0 0 1 13-2l2 3M19 16a8 8 0 0 1-13 2l-2-3"/>
              </svg>
            </button>
            <button type="button" disabled={busy} title="移出用户关注" aria-label={'移出 '+entry.name} onClick={()=>void act('remove',entry.code)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v6m4-6v6"/>
              </svg>
            </button>
          </div>
        </article>;
      })}
    </div>}
  </section>;
}
