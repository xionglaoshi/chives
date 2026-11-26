import { randomUUID } from 'node:crypto';
import { AppError } from '../errors.js';
import type { Store } from '../store/index.js';
import { transaction } from '../store/db.js';
import { normalizeSymbolCode } from '../symbols.js';
import { marketSession } from '../dashboard/market.js';
import type {Bar,Crossing,MarketTick} from './indicators.js';
import { toMessageDto,toTaskDto } from '../api/dto.js';
import type { EventBus } from '../events/index.js';
import type { NotificationService } from '../notifications/service.js';

export const pendingTape='分时 DDX、分时博弈、内外盘差待接入有定义的盘口数据。';
export const technicalPeriod='已完成的5分钟K线 · 不复权';
type Monitor={code:string;title:string;held:number;manual:number;enabled:number;removed:number;created_at:string;
  checked_at:string|null;state:string;bar_time:string|null};
export interface TechnicalOptions{
  store:Store;bus:EventBus;notifications:NotificationService;now:()=>Date;
  hired:()=>boolean;canReadHoldings:()=>boolean;active:()=>boolean;tradingDay:(date:Date)=>boolean;
  names:Record<string,string>;holdings:()=>Promise<{code:string;name?:string}[]>;
  calculate:(bars:Bar[])=>Promise<Crossing[]>;
  quote?:(code:string)=>Promise<MarketTick|undefined>;
  analyze?:(taskId:string,title:string,summary:string)=>Promise<void>;
  bars:(code:string)=>Promise<{bars:Bar[];stale:boolean;timeBasis?:'start'|'end'|undefined}>;
}
export class TechnicalWatches{
  private pending:Promise<void>|undefined;
  constructor(private o:TechnicalOptions){}
  private get db(){return this.o.store.db;}
  private row(code:string){return this.db.prepare('SELECT * FROM technical_watches WHERE code=?').get(code) as unknown as Monitor|undefined;}
  list(){
    return (this.db.prepare('SELECT * FROM technical_watches WHERE removed=0 AND (manual=1 OR held=1) ORDER BY code').all() as unknown as Monitor[])
      .filter(r=>!!r.manual||this.o.canReadHoldings()).map(r=>({id:r.code,code:r.code,botId:'trader',kind:'technical' as const,title:r.title,
        enabled:!!r.enabled,createdAt:r.created_at,conditionText:technicalPeriod,state:r.state,checkedAt:r.checked_at,
        sources:[...(r.held&&this.o.canReadHoldings()?['持仓']:[]),...(r.manual?['客户点名']:[])],pending:pendingTape}));
  }
  edit(raw:unknown,action:string,title?:unknown){
    const code=normalizeSymbolCode(String(raw??''));
    if(!/^[0-9]{6}\.(SH|SZ|BJ)$/.test(code))throw new AppError(400,'stock','请输入沪深北股票代码。');
    const row=this.row(code);
    if(action==='start'){
      if(!this.o.hired()||!Object.hasOwn(this.o.names,code))throw new AppError(400,'stock','请核对交易员聘用状态及证券名录。');
      this.upsert(code,this.o.names[code]!,false);
    }else{
      if(!row)throw new AppError(404,'watch','找不到这只股票的技术监测。');
      if(action==='rename'){
        if(typeof title!=='string'||!title.trim()||Array.from(title.trim()).length>40)throw new AppError(400,'title','名称须为1至40字。');
        this.db.prepare('UPDATE technical_watches SET title=? WHERE code=?').run(title.trim(),code);
      }else if(action==='delete')this.db.prepare('UPDATE technical_watches SET removed=1,enabled=0,manual=0 WHERE code=?').run(code);
      else if(action==='pause')this.db.prepare('UPDATE technical_watches SET enabled=0 WHERE code=?').run(code);
      else if(action==='resume'&&this.o.hired())this.db.prepare('UPDATE technical_watches SET enabled=1,removed=0,manual=CASE WHEN held=0 THEN 1 ELSE manual END,state=?,bar_time=NULL WHERE code=?').run('待首份行情',code);
      else throw new AppError(400,'action','请核对操作及在岗状态。');
    }
    if(action==='pause'||action==='resume'||action==='delete'){
      this.db.prepare('DELETE FROM technical_ticks WHERE code=?').run(code);
      this.db.prepare('UPDATE technical_events SET delivered=1 WHERE code=? AND delivered=0').run(code);
    }
    const saved=this.row(code)!;
    return {code,enabled:!!saved.enabled&&!saved.removed,removed:!!saved.removed,state:saved.removed?'已删除':saved.enabled?saved.state:'已暂停',
      period:technicalPeriod,pending:pendingTape,href:'#/settings?tab=tasks&kind=technical&task='+code};
  }
  private upsert(code:string,name:string,held:boolean){
    const source=held?'held':'manual';
    this.db.prepare(`INSERT INTO technical_watches(code,title,${source},created_at) VALUES(?,?,1,?)
      ON CONFLICT(code) DO UPDATE SET ${source}=1`).run(code,(name||code)+'技术盯盘',this.o.now().toISOString());
  }
  sync(positions:{code:string;name?:string}[]){
    const codes=new Set(positions.map(p=>normalizeSymbolCode(p.code)));
    transaction(this.db,()=>{
      for(const p of positions){const code=normalizeSymbolCode(p.code);this.upsert(code,p.name||this.o.names[code]||code,true);}
      for(const row of this.db.prepare('SELECT code FROM technical_watches WHERE held=1').all()){
        if(!codes.has(String(row.code)))this.db.prepare('UPDATE technical_watches SET held=0 WHERE code=?').run(row.code!);
      }
    });
  }
  tick(){return this.pending??=(this.run().finally(()=>{this.pending=undefined;}));}
  async idle(){await this.pending;}
  private async run(){
    if(!this.o.hired())return;
    let ledgerReady=false;
    if(this.o.canReadHoldings()){
      try{const rows=await this.o.holdings();if(!this.o.hired())return;if(this.o.canReadHoldings()){this.sync(rows);ledgerReady=true;}}
      catch{this.db.prepare("UPDATE technical_watches SET state='持仓数据待恢复' WHERE held=1 AND manual=0").run();}
    }
    const at=this.o.now(), local=new Date(at.getTime()+8*3600_000).toISOString(), minute=local.slice(11,16);
    const closingWindow=(minute>='11:30'&&minute<='11:34')||(minute>='15:00'&&minute<='15:04');
    if(!this.o.active()||!this.o.tradingDay(at)||(marketSession(at)!=='trading'&&!closingWindow))return;
    const rows=this.list().filter(r=>r.enabled&&(ledgerReady||r.sources.includes('客户点名')));
    for(let i=0;i<rows.length;i+=4)await Promise.all(rows.slice(i,i+4).map(async r=>{
      await Promise.all([this.evaluate(r.code,at),this.evaluateQuote(r.code,at)]);
    }));
    await this.deliver(at);
  }
  private async evaluate(code:string,at:Date){
    if(!Object.hasOwn(this.o.names,code)){this.db.prepare('UPDATE technical_watches SET state=? WHERE code=?').run('待接证券行情',code);return;}
    const prior=this.row(code)!;
    if(prior.checked_at&&at.getTime()-Date.parse(prior.checked_at)<50_000)return;
    const status=(value:string)=>this.db.prepare('UPDATE technical_watches SET checked_at=?,state=? WHERE code=?')
      .run(at.toISOString(),value,code);
    try{
      const source=await this.o.bars(code);
      if(!this.o.active()||!this.o.hired())return;
      const current=this.row(code);
      if(!current?.enabled||current.removed||!current.manual&&(!current.held||!this.o.canReadHoldings()))return;
      const stamp=(b:Bar)=>Date.parse(/(Z|[+-]\d\d:\d\d)$/.test(b.time)?b.time:b.time+'+08:00');
      // Providers timestamp bars at different ends. Older gateways need a newer bar to confirm closure.
      const series=source.bars.filter(b=>Number.isFinite(stamp(b))&&stamp(b)<=at.getTime()).sort((a,b)=>stamp(a)-stamp(b));
      const newest=series.at(-1);
      if(source.stale||!newest||at.getTime()-stamp(newest)>6*60_000){status('行情延迟或停牌');return;}
      const bars=source.timeBasis==='end'?series:source.timeBasis==='start'
        ?series.filter(b=>stamp(b)+5*60_000<=at.getTime()):series.slice(0,-1);
      if(bars.some((b,i)=>!([b.open,b.high,b.low,b.close].every(v=>Number.isFinite(v)&&v>0))||
        b.low>Math.min(b.open,b.close)||b.high<Math.max(b.open,b.close)||i>0&&stamp(b)<=stamp(bars[i-1]!))){status('K线数据待核');return;}
      const last=bars.at(-1),before=bars.at(-2);
      if(!last||!before||stamp(newest)-stamp(last)>5*60_000||!(Number(last.volume_shares)>0)){status('等待连续有效成交');return;}
      if(current.bar_time===last.time){status(current.state);return;}
      const ready=bars.length>=61?'监测中':'部分指标预热中';
      const continuous=!!current.checked_at && at.getTime()-Date.parse(current.checked_at)<=6*60_000
        && (current.state==='监测中'||current.state==='部分指标预热中');
      const events=continuous && stamp(last)-stamp(before)===5*60_000 && current.bar_time?await this.o.calculate(bars):[];
      if(!this.authorized(code) || this.row(code)?.bar_time!==current.bar_time)return;
      transaction(this.db,()=>{
        this.db.prepare('UPDATE technical_watches SET bar_time=?,checked_at=?,state=? WHERE code=?')
          .run(last.time,at.toISOString(),ready,code);
        // A new subscription starts at the current market state; never replay a past crossover.
        if(!current.bar_time || stamp(last)<Date.parse(current.created_at))return;
        this.record(code,last.time,last.close,'5分钟已收线',events,at);
      });
    }catch{status('行情源暂不可用');}
  }
  private authorized(code:string){
    const r=this.row(code);
    return this.o.hired() && this.o.active() && !!r?.enabled && !r.removed &&
      (!!r.manual || (!!r.held && this.o.canReadHoldings()));
  }
  private async evaluateQuote(code:string,at:Date){
    if(!this.o.quote||!Object.hasOwn(this.o.names,code))return;
    const tick=await this.o.quote(code).catch(()=>undefined);
    if(!tick||!this.authorized(code)||!Number.isFinite(tick.price)||tick.price<=0)return;
    const time=Date.parse(tick.quote_time),old=this.db.prepare('SELECT * FROM technical_ticks WHERE code=?').get(code);
    const age=at.getTime()-time;
    if(!Number.isFinite(age)||age<0||age>180_000||old&&Date.parse(String(old.stamp))>=time)return;
    transaction(this.db,()=>{
      this.db.prepare('INSERT OR REPLACE INTO technical_ticks VALUES(?,?,?,?)').run(code,tick.quote_time,tick.volume_ratio??null,tick.change_pct??null);
      if(!old||time-Date.parse(String(old.stamp))>5*60_000)return;
      const events:Crossing[]=[];
      for(const [name,before,after,level] of [
        ['量比',old.ratio,tick.volume_ratio,2],['日涨跌幅（%）',old.change_pct,tick.change_pct,3],
        ['日涨跌幅（%）',old.change_pct,tick.change_pct,-3]] as const){
        if(typeof before!=='number'||typeof after!=='number')continue;
        if(before<=level&&after>level||before>=level&&after<level)
          events.push({name,before,after,levelBefore:level,levelAfter:level,up:after>level});
      }
      this.record(code,tick.quote_time,tick.price,'盘中报价',events,at);
    });
  }
  private record(code:string,stamp:string,price:number,period:string,events:Crossing[],at:Date){
    for(const up of [true,false]){
      const hits=events.filter(h=>h.up===up);
      if(!hits.length)continue;
      const title=(this.o.names[code]||code)+' · '+period+'信号';
      const values=hits.map(h=>h.name+' '+h.before.toFixed(2)+'→'+h.after.toFixed(2)+(up?' 上穿 ':' 下穿 ')+h.levelAfter.toFixed(2)).join('；');
      const summary=code+'，'+stamp+'，'+period+'，价格 '+price+'。'+values+'。';
      this.db.prepare('INSERT OR IGNORE INTO technical_events(code,bar_time,direction,task_id,title,summary,created_at) VALUES(?,?,?,?,?,?,?)')
        .run(code,stamp,period+(up?'up':'down'),randomUUID(),title,summary,at.toISOString());
    }
  }
  private async deliver(at:Date){
    const rows=this.db.prepare('SELECT * FROM technical_events WHERE delivered=0 ORDER BY created_at').all();
    for(const r of rows){
      const id=String(r.task_id), title=String(r.title), text=String(r.summary), code=String(r.code);
      if(this.authorized(code)&&at.getTime()-Date.parse(String(r.created_at))<=5*60_000){
        if(!this.o.store.tasks.get(id)){
          try{
            if(!this.o.analyze || this.o.store.tasks.findRunning('trader'))throw new Error('busy');
            await this.o.analyze(id,title,text);
          }catch{
            if(!this.authorized(code))continue;
            if(!this.o.store.tasks.get(id)){
              const t=this.o.store.tasks.create({id,botId:'trader',title,startedAt:at.toISOString(),origin:'technical'});
              const message=this.o.store.messages.append({id:randomUUID(),botId:'trader',taskId:t.id,role:'bot',kind:'text',
                content:text+'若下一周期反向穿回，则这次越线信号失效。',meta:{code},createdAt:at.toISOString()});
              const done=this.o.store.tasks.finish(t.id,'done',at.toISOString());
              this.db.prepare('UPDATE tasks SET closed_at=? WHERE id=?').run(at.toISOString(),id);
              this.o.bus.publish({type:'message.created',botId:'trader',taskId:id,message:toMessageDto(message)});
              this.o.bus.publish({type:'task.updated',botId:'trader',taskId:id,task:toTaskDto(done)});
            }
          }
        }
        if(this.authorized(code)&&!this.o.store.notifications.countForTask(id))
          this.o.notifications.notify({botId:'trader',taskId:id,title,body:Array.from(text).slice(0,300).join(''),level:'info',localOnly:true});
      }
      this.db.prepare('UPDATE technical_events SET delivered=1 WHERE task_id=?').run(id);
    }
  }
}
