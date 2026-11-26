import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import {transaction} from '../store/db.js';
import type { Store } from '../store/index.js';
import { extractUserSymbols } from '../symbols.js';
import { AppError } from '../errors.js';
import { loadTradingDays } from '../routines/service.js';

type Fields=Record<string,unknown>;
export function fields(x:unknown):Fields {return x && typeof x==='object' && !Array.isArray(x)?x as Fields:{};}
const list=(x:unknown):Fields[]=>Array.isArray(x)?x.map(fields):[];
const day=86400_000;
function fileText(file:string) {return existsSync(file)?readFileSync(file,'utf8'):'';}
export function portfolioFields(raw:unknown,id:string) {
  const p=fields(raw);
  const positions=list(p.positions).map(row=>({code:String(row.code),name:String(row.name??''),
    ...(id==='cro'?{qty:row.qty,marketValue:row.marketValue,weight:row.weight}: {})}));
  return {positions,asOf:p.as_of??p.asOf??p.updated_at??null,...(id==='cro'?{cash:p.cash??null}: {})};
}

export class DeskInputs {
  readonly directory:Record<string,string>;
  private names:Record<string,string>;
  readonly dates:string[];
  constructor(private store:Store,root:string,private data:string) {
    const file=join(root,'apps/web/public/holdings-securities.json');
    this.directory=JSON.parse(fileText(file)||'{}') as Record<string,string>;
    this.names=Object.fromEntries(Object.entries(this.directory).map(([code,name])=>[name,code]));
    this.dates=[...loadTradingDays(root)].sort();
  }
  symbols(text:string){return extractUserSymbols(text,this.names);}
  noteNews(raw:unknown,at:Date) {
    const data=fields(raw);
    for(const scope of ['domestic','global']){
      const snap=fields(data[scope]), time=Date.parse(String(snap.updatedAt??''));
      if(Number.isFinite(time)&&time<=at.getTime() && time>at.getTime()-4*day && Array.isArray(snap.entries)&&snap.entries.length)
        this.store.db.prepare('INSERT OR IGNORE INTO desk_news VALUES(?,?,?)').run(scope,time,JSON.stringify(snap.entries));
    }
    this.store.db.prepare('DELETE FROM desk_news WHERE observed_at<?').run(at.getTime()-4*day);
  }
  newsWindows(at:Date){
    const result=[];
    for(let i=0;i<3;i++){
      const end=at.getTime()-i*day,begin=end-day;
      for(const scope of ['domestic','global']){
        const rows=this.store.db.prepare('SELECT observed_at,items FROM desk_news WHERE scope=? AND observed_at>? AND observed_at<=? ORDER BY observed_at')
          .all(scope,begin,end);
        const topics=new Map<string,Fields>();
        for(const snap of rows) for(const [index,item] of list(JSON.parse(String(snap.items))).entries()){
          const key=String(item.url||item.title);
          const earlier=topics.get(key);
          topics.set(key,{...item,firstSeen:earlier?.firstSeen??snap.observed_at,lastSeen:snap.observed_at,
            bestRank:Math.min(Number(earlier?.bestRank??Infinity),index+1)});
        }
        const window={scope,start:new Date(begin).toISOString(),end:new Date(end).toISOString(),snapshots:rows.length};
        result.push({type:'新闻覆盖',...window});
        for(const item of topics.values())result.push({type:'财经热榜',...window,...item});
      }
    }
    return result;
  }
  async captureClosingFlows(at:Date,read:(scope:string,kind:string)=>Promise<{as_of:string;stale?:boolean;data:{rows?:unknown[]}}>){
    const local=new Date(at.getTime()+8*3600_000).toISOString(),day=local.slice(0,10);
    if(local.slice(11,16)<'15:05'||!this.dates.includes(day))return;
    const jobs=[];
    for(const scope of ['sector','rank'])for(const kind of ['in','out']){
      if(this.store.db.prepare('SELECT 1 FROM desk_flow_closes WHERE day=? AND scope=? AND kind=?').get(day,scope,kind))continue;
      jobs.push((async()=>{
        const flow=await read(scope,kind), stamp=Date.parse(flow.as_of);
        if(flow.stale||!Number.isFinite(stamp)||Math.abs(stamp-at.getTime())>5*60_000||!flow.data.rows?.length)return;
        this.store.db.prepare('INSERT OR IGNORE INTO desk_flow_closes VALUES(?,?,?,?,?)').run(day,scope,kind,flow.as_of,JSON.stringify(flow.data.rows));
      })());
    }
    await Promise.allSettled(jobs);
    this.store.db.prepare('DELETE FROM desk_flow_closes WHERE day<?').run(new Date(at.getTime()-30*86400_000).toISOString().slice(0,10));
  }
  closingFlows(dates:string[],kind:string){
    return dates.flatMap(day=>['rank','sector'].map(scope=>{
      const r=this.store.db.prepare('SELECT observed_at,rows FROM desk_flow_closes WHERE day=? AND scope=? AND kind=?').get(day,scope,kind);
      return {type:'收盘后资金榜观测',day,scope,kind,observedAt:r?.observed_at??null,rows:r?JSON.parse(String(r.rows)):null,
        basis:r?'在该交易日收盘后采集的排名，时间是采集时点':'该交易日无已采集快照'};
    }));
  }
  closedDates(at:Date) {
    const local=new Date(at.getTime()+8*3600_000).toISOString();
    return this.dates.filter(d=>d<local.slice(0,10)||d===local.slice(0,10)&&local.slice(11,16)>='15:00').slice(-3);
  }
  securities(positions:Fields[],followed:Fields[],allowMemory:boolean) {
    const map=new Map<string,{code:string;name:string;sources:string[];contexts:string[]}>();
    const add=(code:string,name:string,source:string,context='')=>{
      const entry=map.get(code)??{code,name:name||this.directory[code]||'',sources:[],contexts:[]};
      if(!entry.sources.includes(source))entry.sources.push(source);
      if(context&&!entry.contexts.includes(context))entry.contexts.push(context);
      map.set(code,entry);
    };
    for(const row of positions)add(String(row.code),String(row.name??''),'持仓');
    for(const row of followed)add(String(row.code),String(row.name??''),'关注');
    if(allowMemory){
      const memory=fileText(join(this.data,'user/recent-memory.md'));
      for(const line of memory.split(/\r?\n/)) for(const {code,name} of extractUserSymbols(line,this.names)){
        if(!this.directory[code]&&!/^[036489]\d{5}\.(SH|SZ|BJ)$/.test(code))continue;
        // Share only the security and its investment topic, never the whole customer note.
        const date=line.match(/\d{4}-\d{2}-\d{2}/)?.[0];
        const label=name||this.directory[code]||code.slice(0,6);
        const clauses=line.replace(/（\d{4}-\d{2}-\d{2}，消息[^）]+）/g,'').split(/[。；;\n]/)
          .filter(c=>c.includes(label)||c.includes(code.slice(0,6)));
        const topics=clauses.join('。').match(/(?:不再|暂缓|继续|优先|等待|观察|关注)?(?:估值|分红|跟踪|财报|调仓|量价|风险|观察|政策|订单|盈利|回撤|现金流|减仓|加仓|回款|业绩)/g)??[];
        add(code,name,'短期记忆',[date,...new Set(topics)].filter(Boolean).join('、'));
      }
    }
    return [...map.values()];
  }
  observePositions(raw:unknown,at:Date){
    const book=fields(raw);
    if(!Array.isArray(book.positions))return;
    const positions=list(book.positions);
    if(positions.some(p=>typeof p.code!=='string'||typeof p.qty!=='number'||p.qty<0))return;
    const next=new Map(positions.map(p=>[String(p.code),Number(p.qty)]));
    const previous=new Map(this.store.db.prepare('SELECT * FROM desk_position_state').all().map(r=>[String(r.code),Number(r.quantity)]));
    const initialized=this.store.settings.get('desk.positionsInitialized');
    transaction(this.store.db,()=>{
      for(const code of new Set([...previous.keys(),...next.keys()])){
        const old=previous.get(code)??0, qty=next.get(code)??0;
        if(old===qty)continue;
        if(initialized)this.store.db.prepare('INSERT INTO desk_position_changes(code,direction,observed_at) VALUES(?,?,?)')
          .run(code,!old?'新增持仓':!qty?'移出持仓':qty>old?'持仓增加':'持仓减少',at.toISOString());
        if(qty)this.store.db.prepare('INSERT OR REPLACE INTO desk_position_state VALUES(?,?)').run(code,qty);
        else this.store.db.prepare('DELETE FROM desk_position_state WHERE code=?').run(code);
      }
      if(!initialized)this.store.settings.set('desk.positionsInitialized',true);
    });
  }
  behavior(at:Date,code:unknown,mode:unknown,days:unknown) {
    if(code && (typeof code!=='string'||!/^\d{6}(\.(SH|SZ|BJ))?$/.test(code)))throw new AppError(400,'symbol','请输入证券代码。');
    if(mode && !['live','simulation'].includes(String(mode)))throw new AppError(400,'mode','请指定实盘或模拟。');
    const duration=Number(days??90);
    if(!Number.isInteger(duration)||duration<1||duration>730)throw new AppError(400,'period','期间须在1至730天内。');
    const from=new Date(at.getTime()-duration*day).toISOString();
    const path=join(this.data,'user/portfolio/trades.sqlite');
    let trades:unknown[]=[];
    if(existsSync(path)){
      const db=new DatabaseSync(path,{readOnly:true});
      try{trades=db.prepare(`SELECT mode,symbol,side,date(executed_at) AS day,source,COUNT(*) AS fills
        FROM trades t WHERE julianday(executed_at) BETWEEN julianday(?) AND julianday(?) AND (?='' OR mode=?)
        AND (?='' OR substr(symbol,1,6)=?) AND reverses IS NULL AND NOT EXISTS (SELECT 1 FROM trades r WHERE r.reverses=t.id)
        GROUP BY mode,symbol,side,day,source ORDER BY day DESC`).all(from,at.toISOString(),String(mode??''),String(mode??''),String(code??''),String(code??'').slice(0,6));
      }finally{db.close();}
    }
    const changes=mode==='simulation'?[]:this.store.db.prepare("SELECT code,direction,observed_at FROM desk_position_changes WHERE observed_at BETWEEN ? AND ? AND (?='' OR substr(code,1,6)=?) ORDER BY observed_at DESC")
      .all(from,at.toISOString(),String(code??''),String(code??'').slice(0,6));
    return {from,asOf:at.toISOString(),trades,positionChanges:changes,changeBasis:'自首次观测起记录账本变化；本身不能证明有成交。',source:'客户档案已记录成交，按日期、实盘或模拟分列',
      preferences:fileText(join(this.data,'user/preferences/instructions.md')),recentMemory:fileText(join(this.data,'user/recent-memory.md'))};
  }
}
