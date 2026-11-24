import { workbenchTools } from '../utils/routes';
import { askAiPrompts, fillAskPrompt } from '../utils/askAiPrompts';
import content from '../../../../packages/chives-terminal/chives_terminal/workbench-content.json';
import {useEffect,useState,type ReactNode} from 'react';
import type {AskExpert} from './askExpert';
import {appPath} from '../appPath';
import {useExpertSidebarData} from './ExpertSidebarData';
import {ExpertSidebarSparkline} from './ExpertSidebarSparkline';
import {formatAmount,formatPercent,formatPrice,priceDirection,SESSION_TEXT} from './ExpertSidebarFormat';
import './market-board.css';
import {MarketNews} from './MarketNews';

type Row={name:string;code?:string;change_pct:number|null;amount_yuan:number|null;leader?:{name:string;change_pct:number|null}|null};
type Snapshot={rows:Row[];asOf:string;stale:boolean};
type World={rows:{name:string;market:string;price:number|null;changePct:number|null;time:string|null}[]};
function useFeed<T>(part:string) {
  const [state,set]=useState<{part:string;data?:T;error?:boolean}>({part});
  useEffect(()=>{
    const controller=new AbortController();
    let pending=false;
    async function read(){
      if(document.hidden || pending)return;
      pending=true;
      try{
        const res=await fetch(appPath('/api/dashboard/'+part),{signal:controller.signal});
        if(!res.ok)throw Error();
        const data=await res.json() as T;
        if(!controller.signal.aborted)set({part,data});
      }catch{if(!controller.signal.aborted)set(old=>({...(old.part===part?old:{}),part,error:true}));}
      finally{pending=false;}
    }
    void read();
    const timer=setInterval(()=>void read(),60_000);
    document.addEventListener('visibilitychange',read);
    return ()=>{controller.abort();clearInterval(timer);document.removeEventListener('visibilitychange',read);};
  },[part]);
  return state.part===part?state:{part};
}
function stamp(s?:string|null){
  if(!s || !Number.isFinite(Date.parse(s)))return '时间待更新';
  return new Date(s).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Shanghai',hour12:false});
}
function Change({n}:{n:number|null}){return <b className={'mb-'+priceDirection(n)}>{formatPercent(n)}</b>}
function Panel({title,ask,action,children,cls=''}:{title:string;ask:ReactNode;action?:ReactNode;children:ReactNode;cls?:string}){
  return <section className={'mb-panel '+cls}><header><h2>{title}</h2><div className="mb-panel-actions">{action}{ask}</div></header>{children}</section>;
}
const privacyKey='chives.expertSidebar.hideAmounts';
function table(headers:string[],rows:(string|number|null|undefined)[][]){
  return [headers,headers.map(()=>'---'),...rows].map(row=>'| '+row.map(x=>String(x??'暂无').replaceAll('|','｜').replace(/[\r\n]+/g,' ')).join(' | ')+' |').join('\n');
}
export function MarketBoard({onAskExpert}:{onAskExpert:AskExpert}){
  function ask(title:string,ready:boolean,prompt:string,markdown:()=>string){
    return <button className="mb-ask" disabled={!ready} onClick={()=>{
      const captured=new Date().toISOString();
      const file=new File(['# '+title+'\n\n截取时间（UTC）：'+captured+'\n\n'+markdown()+'\n'],title+'-'+captured.slice(0,10)+'.md',{type:'text/markdown'});
      onAskExpert(prompt,file);
    }}>问AI</button>;
  }
  const market=useExpertSidebarData('market',0).market, portfolio=useExpertSidebarData('portfolio',0).portfolio;
  const [idx,selectIdx]=useState(''),[sector,selectSector]=useState(''),[rank,setRank]=useState('gainers');
  const movers=useFeed<Snapshot>(rank), sectors=useFeed<Snapshot>('sectors'), world=useFeed<World>('world');
  const [hidden,hide]=useState(()=>{try{return localStorage.getItem(privacyKey)==='1'}catch{return true}});
  function toggle(){hide(!hidden);try{localStorage.setItem(privacyKey,hidden?'0':'1')}catch{/* session only */}}
  const m=market.data,p=portfolio.data,i=m?.indexes.find(x=>x.code===idx)??m?.indexes[0];
  const tiles=sectors.data?.rows??[], tile=tiles.find(r=>r.name===sector)??tiles[0];
  const status=(error?:boolean)=>error?'暂时取不到，稍后自动重试':'正在读取行情…';
  const amount=(n:number|null|undefined)=>hidden?'••••':n==null?'—':n.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
  const ratio=m?.breadth.upRatioPct;
  return <article className="market-board">
    <div className="mb-title"><div><small>工作台</small><h1>{workbenchTools.market}</h1></div><small>{m?SESSION_TEXT[m.session]+' · '+stamp(m.asOf)+' 北京时间':'A 股市场'}</small></div>
    {p&&!p.empty&&<button className="mb-account-strip" onClick={()=>document.querySelector('.mb-summary')?.scrollIntoView({block:'center',behavior:'smooth'})}><span>我的持仓 <strong>{p.summary.positionCount} 只</strong></span><span>今日估算盈亏 <b className={'mb-'+priceDirection(p.summary.todayPnl)}>{amount(p.summary.todayPnl)} 元</b></span><span>查看贡献 ↓</span></button>}
    <div className="mb-grid">
    <Panel title={content.market.market} cls="mb-major" ask={ask('大盘走势',!!i,fillAskPrompt(askAiPrompts['行情看板']['大盘走势'], {指数名: i?.name ?? '当前指数'}),()=>[
        '数据时间：'+m?.asOf+' · '+SESSION_TEXT[m!.session]+(m?.stale||market.status==='error'?' · 缓存快照':''),
        table(['指数','代码','点位','涨跌幅'],m!.indexes.map(x=>[x.name,x.code,x.price,formatPercent(x.changePct)])),
        '当前选择：'+i!.name+'。五分钟走势采样点（从早到晚）：'+(i!.spark.join('、')||'暂无')
      ].join('\n\n'))}>
      <div className="mb-tabs">{m?.indexes.map(x=><button key={x.code} aria-pressed={x.code===i?.code} onClick={()=>selectIdx(x.code)}>{x.name}</button>)}</div>
      {i?<><div className="mb-index"><strong>{formatPrice(i.price)}</strong><Change n={i.changePct}/></div>{i.spark.length>1?<div className="mb-chart"><ExpertSidebarSparkline values={i.spark} label={i.name}/></div>:<small>暂无分时数据</small>}</>:<small>{status(market.status==='error')}</small>}
      {(m?.stale||market.status==='error'&&m)&&<small>显示最近快照</small>}
    </Panel>
    <Panel title={content.market.breadth} cls="mb-minor" ask={ask('市场宽度',!!m,askAiPrompts['行情看板']['市场宽度'],()=>[
      '数据时间：'+m!.asOf+' · '+SESSION_TEXT[m!.session]+(m!.stale||market.status==='error'?' · 缓存快照':''),
      table(['沪深成交额（元）','上涨家数','下跌家数','上涨占比','涨停家数','跌停家数'],[[m!.amountYuan,m!.breadth.up,m!.breadth.down,formatPercent(ratio??null),m!.limit.limitUp,m!.limit.limitDown]])
    ].join('\n\n'))}><small>沪深成交额</small><strong className="mb-value">{formatAmount(m?.amountYuan??null)}</strong>
      <div className="mb-stat"><span>上涨 <b className="mb-up">{m?.breadth.up??'—'}</b></span><span>下跌 <b className="mb-down">{m?.breadth.down??'—'}</b></span></div>
      {ratio!=null&&<div className="mb-breadth" aria-label={'上涨占比 '+formatPercent(ratio)}><i style={{width:ratio+'%'}}/></div>}
      <div className="mb-stat"><span>涨停 <b>{m?.limit.limitUp??'—'}</b></span><span>跌停 <b>{m?.limit.limitDown??'—'}</b></span></div>
    </Panel>
    <Panel title={content.market.world} cls="mb-full" ask={ask('外围市场',!!world.data?.rows.length,askAiPrompts['行情看板']['外围市场'],()=>[
      '来源：腾讯行情。港股使用香港当地时间，美股使用纽约当地时间。'+(world.error?'当前显示缓存快照。':''),
      table(['市场','指数','点位','涨跌幅','当地报价时间'],world.data!.rows.map(x=>[x.market,x.name,x.price,formatPercent(x.changePct),x.time]))
    ].join('\n\n'))}>
      {!world.data?<small>{status(world.error)}</small>:<div className="mb-world">{['港股','美股'].map(region=><div key={region}><h3>{region} <small>{region==='港股'?'香港时间':'纽约时间'}</small></h3><div className="mb-world-quotes">{world.data?.rows.filter(x=>x.market===region).map(x=><div key={x.name}><span>{x.name}</span><strong>{formatPrice(x.price)}</strong><Change n={x.changePct}/><small>{x.time?.slice(5,16)??'时间待更新'}</small></div>)}</div></div>)}</div>}{world.error&&world.data&&<small>显示最近快照</small>}
    </Panel>
    <Panel title={content.market.sectors} cls="mb-sectors" ask={ask('行业热图',!!tile,fillAskPrompt(askAiPrompts['行情看板']['行业热图'], {行业名: tile?.name ?? '行业'}),()=>[
      '成交额前12行业 · '+sectors.data!.asOf+(sectors.error||sectors.data!.stale?' · 缓存快照':'')+' · 当前选择：'+tile!.name,
      table(['行业','涨跌幅','成交额（元）','领涨股','领涨股涨跌幅'],tiles.map(x=>[x.name,formatPercent(x.change_pct),x.amount_yuan,x.leader?.name,formatPercent(x.leader?.change_pct??null)]))
    ].join('\n\n'))}>
      {tile ? <>
        <div className="mb-tiles">{tiles.map(row=>{
          const active=row.name===tile.name;
          const direction=priceDirection(row.change_pct);
          const background={up:'color-mix(in srgb, var(--color-up) 3.4%, transparent)',
            down:'color-mix(in srgb, var(--color-down) 4.6%, transparent)',
            flat:'color-mix(in srgb, var(--mb-flat) 6%, transparent)'}[direction];
          return <button key={row.name} aria-pressed={active} onClick={()=>selectSector(row.name)}
            style={{backgroundColor:background}}>
            <span>{row.name}</span><Change n={row.change_pct}/>
          </button>;
        })}</div>
        <div className="mb-sector-detail"><small>{tile.name} · 领涨股</small>
          <div><strong>{tile.leader?.name??'—'}</strong><Change n={tile.leader?.change_pct??null}/></div>
        </div>
        <small>快照 {stamp(sectors.data?.asOf)}{(sectors.error||sectors.data?.stale)&&' · 最近缓存'}</small>
      </> : <div className="mb-sector-empty" role="status">{sectors.error?'行业行情暂不可用，将自动重试':sectors.data?'暂无行业数据':'正在读取行业行情…'}</div>}
    </Panel>
    <Panel title="个股表现" ask={ask('个股表现',!!movers.data?.rows.length,askAiPrompts['行情看板']['个股表现'][rank === 'gainers' ? '涨幅榜' : '成交额榜'],()=>[
      (rank==='gainers'?'涨幅榜':'成交额榜')+' · '+movers.data!.asOf+(movers.error||movers.data!.stale?' · 缓存快照':''),
      table(['排名','股票','代码','涨跌幅','成交额（元）'],movers.data!.rows.map((x,n)=>[n+1,x.name,x.code,formatPercent(x.change_pct),x.amount_yuan]))
    ].join('\n\n'))} action={<div className="mb-tabs">{[['gainers',content.market.gainers],['active',content.market.active]].map(([key,label])=><button key={key} aria-pressed={rank===key} onClick={()=>setRank(key!)}>{label}</button>)}</div>}>
      {movers.data?<><table><thead><tr><th>沪深 A 股</th><th>涨跌幅</th><th>成交额</th></tr></thead><tbody>{movers.data.rows.map(r=><tr key={r.code}><td>{r.name}</td><td><Change n={r.change_pct}/></td><td>{formatAmount(r.amount_yuan)}</td></tr>)}</tbody></table><small>快照 {stamp(movers.data.asOf)}{(movers.error||movers.data.stale)&&' · 最近缓存'}</small></>:<small>{status(movers.error)}</small>}
    </Panel>
    <MarketNews ask={ask}/>
    <Panel title={content.market.portfolio} cls="mb-full" ask={ask('我的持仓',!!p,askAiPrompts['行情看板']['我的持仓'][p?.empty ? '空仓' : hidden ? '隐藏金额' : '显示金额'],()=>[
      '数据时间：'+p!.asOf+' · '+(p!.empty?'尚未录入持仓':'按现持股数及较昨收价差估算')+(portfolio.status==='error'?' · 缓存快照':''),
      '证券数量：'+p!.summary.positionCount+' · 缺少报价：'+p!.summary.unpricedCount,
      hidden?'金额已隐藏。':table(['今日估算盈亏（元）','持仓市值（元）','累计浮盈亏（元）'],[[p!.summary.todayPnl,p!.summary.totalMarketValue,p!.summary.totalPnl]]),
      table(['持仓','代码','现价','今日涨跌',...(hidden?[]:['今日贡献（元）'])],[...p!.positions].sort((a,b)=>Math.abs(b.todayPnl??0)-Math.abs(a.todayPnl??0)).map(x=>[x.name,x.code,x.price,formatPercent(x.changePct),...(hidden?[]:[x.todayPnl])]))
    ].join('\n\n'))} action={<div className="mb-tabs"><button onClick={toggle}>{hidden?'显示金额':'隐藏金额'}</button><a href="#/workspace/holdings">持仓明细 ↗</a></div>}>
      {!p?<small>{status(portfolio.status==='error')}</small>:p.empty?<a href="#/workspace/holdings">添加第一笔持仓</a>:<>
        <div className="mb-summary">{[['今日估算盈亏',p.summary.todayPnl],['持仓市值',p.summary.totalMarketValue],['累计浮盈亏',p.summary.totalPnl]].map(([label,value])=><div key={label}><small>{label}（元）</small><strong>{amount(typeof value==='number'?value:null)}</strong></div>)}</div>
        <table><thead><tr><th>持仓</th><th>现价</th><th>今日涨跌</th><th>今日贡献（元）</th></tr></thead><tbody>{[...p.positions].sort((a,b)=>Math.abs(b.todayPnl??0)-Math.abs(a.todayPnl??0)).map(r=><tr key={r.code}><td>{r.name}</td><td>{formatPrice(r.price)}</td><td><Change n={r.changePct}/></td><td className={'mb-'+priceDirection(r.todayPnl)}>{amount(r.todayPnl)}</td></tr>)}</tbody></table>
        <small>按现持股数及较昨收价差估算 · {stamp(p.asOf)}{p.summary.unpricedCount>0&&' · 部分持仓缺少报价'}{portfolio.status==='error'&&' · 最近缓存'}</small></>}
    </Panel>
    </div>
  </article>;
}
