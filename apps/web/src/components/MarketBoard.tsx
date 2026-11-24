import type {ReactNode} from 'react';
import type {WorldDashboardDto} from '@chives/server/protocol';
import { askAiPrompts, fillAskPrompt } from '../utils/askAiPrompts';
import content from '../../../../packages/chives-terminal/chives_terminal/workbench-content.json';
import {useEffect,useState} from 'react';
import type {AskExpert} from './askExpert';
import {appPath} from '../appPath';
import {useExpertSidebarData} from './ExpertSidebarData';
import {ExpertSidebarMarket,MarketIndexRows} from './ExpertSidebarMarket';
import {formatPercent,formatPrice,priceDirection,SESSION_TEXT} from './ExpertSidebarFormat';
import './market-board.css';
import {MarketNews} from './MarketNews';

type Row={name:string;code?:string;change_pct:number|null;amount_yuan:number|null;leader?:{name:string;change_pct:number|null}|null};
type RankedRow = Row & {volume_shares: number | null};
type Snapshot<T = Row>={rows:T[];asOf:string;stale:boolean};
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
function Change({n}:{n:number|null}){return <b className={'mb-'+priceDirection(n)}>{formatPercent(n)}</b>}
function Panel({title,ask,action,children,cls=''}:{title:string;ask:ReactNode;action?:ReactNode;children:ReactNode;cls?:string}){
  return <section className={'mb-panel '+cls}><header><h2>{title}</h2><div className="mb-panel-actions">{action}{ask}</div></header>{children}</section>;
}
function table(headers:string[],rows:(string|number|null|undefined)[][]){
  return [headers,headers.map(()=>'---'),...rows].map(row=>'| '+row.map(x=>String(x??'暂无').replaceAll('|','｜').replace(/[\r\n]+/g,' ')).join(' | ')+' |').join('\n');
}
export function MarketBoard({onAskExpert, messages}:{onAskExpert:AskExpert; messages:ReactNode}){
  function ask(title:string,ready:boolean,prompt:string,markdown:()=>string){
    return <button className="mb-ask" disabled={!ready} onClick={()=>{
      const captured=new Date().toISOString();
      const file=new File(['# '+title+'\n\n截取时间（UTC）：'+captured+'\n\n'+markdown()+'\n'],title+'-'+captured.slice(0,10)+'.md',{type:'text/markdown'});
      onAskExpert(prompt,file);
    }}>问AI</button>;
  }
  const {market} = useExpertSidebarData('market', 0);
  const [sector, selectSector] = useState('');
  const movers = useFeed<Snapshot<RankedRow>>('limit-up');
  const losers = useFeed<Snapshot<RankedRow> & {order: 'volume' | 'change'}>('limit-down');
  const sectors = useFeed<Snapshot>('sectors'), world = useFeed<WorldDashboardDto>('world');
  const m = market.data;
  const tiles=sectors.data?.rows??[], tile=tiles.find(r=>r.name===sector)??tiles[0];
  const status=(error?:boolean)=>error?'暂时取不到，稍后自动重试':'正在读取行情…';
  const ratio = m?.breadth.upRatioPct;
  return <article className="market-board dynamic-board" aria-label="动态看板">
    <div className="dynamic-board-grid">
    <div className="dynamic-board-column">
      {messages}
      <MarketNews ask={ask}/>
    </div>
    <div className="dynamic-board-column">
    <Panel title={content.market.market} ask={ask('大盘走势',!!m?.indexes.length,
      fillAskPrompt(askAiPrompts['行情看板']['大盘走势'], {指数名: m?.indexes.map(index => index.name).join('、') ?? '主要指数'}),()=>[
        '数据时间：'+m!.asOf+' · '+SESSION_TEXT[m!.session]+(m!.stale||market.status==='error'?' · 缓存快照':''),
        table(['指数','代码','点位','涨跌幅','分时采样点'],m!.indexes.map(x=>[x.name,x.code,x.price,formatPercent(x.changePct),x.spark.join('、')])),
        table(['沪深成交额（元）','上涨家数','下跌家数','上涨占比','涨停家数','跌停家数'],[[m!.amountYuan,m!.breadth.up,m!.breadth.down,formatPercent(ratio??null),m!.limit.limitUp,m!.limit.limitDown]])
      ].join('\n\n'))}>
      <ExpertSidebarMarket state={market} embedded/>
    </Panel>
    <Panel title={content.market.world} ask={ask('外围市场',!!world.data?.rows.some(row => row.price !== null),askAiPrompts['行情看板']['外围市场'],()=>[
      '指数来源：Yahoo Finance，港美部分指数报价可回退腾讯行情。市场成交量和涨跌家数按 TradingView 有成交且有对应数据的主要上市普通股汇总。日本涨跌停来自株探，统计东证三个主要板块中现价仍在限制价的股票。'+(world.error?'当前显示缓存快照。':''),
      table(['市场','指数','点位','涨跌幅','报价时间'],world.data!.rows.map(row=>[row.market,row.name,row.price,formatPercent(row.changePct),row.time])),
      table(['市场','成交量（股）','上涨','下跌','涨停','跌停'],(world.data!.stats??[]).map(row=>[row.market,row.volumeShares,row.up,row.down,row.limitUp,row.limitDown]))
    ].join('\n\n'))}>
      {!world.data ? <small>{status(world.error)}</small> : <div className="mb-world-markets">
        {[...new Set(world.data.rows.map(row => row.market))].map(region => {
          const stats = world.data?.stats?.find(row => row.market === region);
          const indexes = world.data!.rows.filter(row => row.market === region);
          const shares = stats?.volumeShares;
          const volume = shares == null ? '—' : new Intl.NumberFormat('zh-CN', {notation:'compact', maximumFractionDigits:2}).format(shares)+'股';
          return <section className="mb-market-overview" key={region}>
            <h3>{region}</h3>
            <MarketIndexRows indexes={indexes.map(row => ({...row, code:row.code??row.name, spark:row.spark??[]}))} />
            <dl className="expert-sidebar__stats">
              <div className="expert-sidebar__stat"><dt>成交量</dt><dd>{volume}</dd></div>
              <div className="expert-sidebar__stat"><dt>上涨 / 下跌</dt><dd>
                <span className="mb-up">{stats?.up ?? '—'}</span> / <span className="mb-down">{stats?.down ?? '—'}</span>
              </dd></div>
              <div className="expert-sidebar__stat"><dt>涨停 / 跌停</dt><dd>
                <span className="mb-up">{stats?.limitUp ?? '—'}</span> / <span className="mb-down">{stats?.limitDown ?? '—'}</span>
              </dd></div>
            </dl>
          </section>;
        })}
        <small>成交量和涨跌家数按有成交的主要上市普通股汇总。日本涨跌停统计东证现价触及限制价的股票。— 表示缺少可比数据。</small>
      </div>}
      {world.error&&world.data&&<small>显示最近快照</small>}
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
        {(sectors.error||sectors.data?.stale) && <small>显示最近缓存</small>}
      </> : <div className="mb-sector-empty" role="status">{sectors.error?'行业行情暂不可用，将自动重试':sectors.data?'暂无行业数据':'正在读取行业行情…'}</div>}
    </Panel>
    {([{title:'个股涨停榜', feed:movers, order:'成交量', empty:'暂无涨停股票'},
      {title:'个股跌停榜', feed:losers, order:losers.data?.order === 'volume' ? '成交量' : '跌幅', empty:'暂无下跌股票'}
    ] as const).map(({title, feed, order, empty}) => <Panel key={title} title={title} ask={ask(title,!!feed.data?.rows.length,
      fillAskPrompt(askAiPrompts['行情看板'][title], {股票数:feed.data?.rows.length??0, 排序:order}),()=>[
      '按'+order+'排序 · '+feed.data!.asOf+(feed.error||feed.data!.stale?' · 缓存快照':''),
      table(['排名','股票','代码','涨跌幅','成交量（股）'],feed.data!.rows.map((x,n)=>[n+1,x.name,x.code,formatPercent(x.change_pct),x.volume_shares]))
    ].join('\n\n'))}>
      {feed.data ? <>
        {feed.data.rows.length ? <table><thead><tr><th>沪深 A 股</th><th>涨跌幅</th><th>成交量（股）</th></tr></thead>
          <tbody>{feed.data.rows.map(r=><tr key={r.code}><td>{r.name}</td><td><Change n={r.change_pct}/></td><td>{r.volume_shares?.toLocaleString('zh-CN')??'—'}</td></tr>)}</tbody>
        </table> : <p>{empty}</p>}
        <small>按{order}排序{(feed.error||feed.data.stale)&&' · 最近缓存'}</small>
      </> : <small>{status(feed.error)}</small>}
    </Panel>)}
    </div>
    </div>
  </article>;
}
