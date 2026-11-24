import {randomUUID} from 'node:crypto';
import {mkdirSync, readFileSync, renameSync, writeFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {readValuationReceipt} from './holding-valuations.js';
import {AppError} from '../errors.js';

export type Estimate = {version: number; low: number|null; high: number|null; score: number|null;
  asOf: string; basis: string; invalidation: string; taskId: string; botId: string; measuredAt: string; horizon: number; requestId?: string; valuationId?: string; valuationKind?: '静态参考'|'动态估值'|'依据不足'; modelVersion?: string};
type Entry = {code: string; name: string; addedAt: string; source: 'manual'|'screen'; note: string;
  pending?: string; pendingDate?: string; estimates: Estimate[]};

export const valuationInstructions = 'A 股合理估值统一调用 estimate_equity_value(code, as_of)。使用返回的区间和 valuation_id。dynamic 有值时优先显示动态估值，否则只显示 static 并标注静态参考、动态待校准。两项均为空时注明工具返回的原因。未来20个交易日采用同一回执的 outlook.label 和 outlook.score，说明其历史命中情况及限制。';
export const valuationDay = (now: Date) => new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);

export const screeningPrompt = '接下来我会通过对话筛选股票。请先用几句话建议我可以从哪些维度筛选，例如近五年平均股息率和分红稳定性、盈利与现金流、估值、行业与主题（如 AI 产业链）、成交活跃度，以及与我当前持仓的行业重合度。请问我这次最看重什么、要筛哪个市场、有哪些必须满足的条件。等我给出条件后再运行筛选，简要列出候选股票、入选理由和关键指标。请让我以「确认加入用户关注：证券代码」确认要加入的股票，支持多个代码。确认后调用关注工具，告诉我新增及已在列表中的标的。自选股即用户关注。' + ' 若筛选条件涉及合理估值，按以下规则测算候选。' + valuationInstructions;

export class Watchlist {
  private readonly file: string;
  private directory?: Record<string,string>;
  constructor(private root:string, private data:string) {
    this.file = join(data,'user','portfolio','watchlist.json');
  }
  read(): Entry[] {
    try {
      const data = JSON.parse(readFileSync(this.file,'utf8'));
      if (data.schemaVersion !== 1 || !Array.isArray(data.entries)) throw new Error('invalid');
      return data.entries;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
      throw new AppError(409,'watchlist_invalid','用户关注文件异常，请先恢复备份。');
    }
  }
  private write(entries: Entry[]) {
    mkdirSync(dirname(this.file),{recursive:true});
    const temp=this.file+'.'+randomUUID();
    writeFileSync(temp,JSON.stringify({schemaVersion:1,entries},null,2)+'\n',{mode:0o600,flag:'wx'});
    renameSync(temp,this.file);
  }
  add(codes: unknown[], source: Entry['source'], now: Date) {
    this.directory ??= JSON.parse(readFileSync(join(this.root,'apps/web/public/holdings-securities.json'),'utf8')) as Record<string,string>;
    const entries=this.read();
    const selected=codes.map(value=>{
      const code=String(value).trim().toUpperCase();
      if (!/^\d{6}\.(SH|SZ|BJ)$/.test(code) || !Object.hasOwn(this.directory!,code)) {
        throw new AppError(400,'security','请选择名录中的沪深北证券。');
      }
      return {code,name:this.directory![code]!};
    });
    const added:string[]=[], existing:string[]=[];
    for (const item of selected) {
      if (entries.some(entry=>entry.code===item.code)) {existing.push(item.code); continue;}
      entries.push({...item,addedAt:now.toISOString(),source,note:'',estimates:[]});
      added.push(item.code);
    }
    if (added.length) this.write(entries);
    return {added,existing};
  }
  remove(code: string) {this.write(this.read().filter(item=>item.code!==code));}
  get(code: string) {
    const entry=this.read().find(item=>item.code===code);
    if (!entry) throw new AppError(404,'watchlist_missing','该证券不在用户关注中。');
    return entry;
  }
  pending(code:string, id:string|null, day?:string) {
    const current=this.read();
    const entry=current.find(item=>item.code===code);
    if (!entry) return;
    if (id) {entry.pending=id; entry.pendingDate=day??valuationDay(new Date());}
    else {delete entry.pending; delete entry.pendingDate;}
    this.write(current);
  }
  saveEstimate(id:string, body:Record<string,unknown>, taskId:string, botId:string, now:Date) {
    const current=this.read();
    const entry=current.find(item=>item.pending===id);
    // A tool call can be retried after its response was lost, even after a later task starts.
    const saved=(entry ? entry.estimates : current.flatMap(e=>e.estimates)).find(e=>
      e.taskId===taskId && e.botId===botId && e.valuationId===body.valuationId &&
      (e.requestId===undefined || e.requestId===id));
    if (saved) {
      if (entry) {delete entry.pending; delete entry.pendingDate; this.write(current);}
      return saved;
    }
    if (!entry) {
      throw new AppError(409,'watchlist_pending','没有匹配的用户测算请求。');
    }
    const {valuationId,basis,invalidation}=body;
    const note=(value:unknown):value is string=>typeof value==='string'&&value.trim().length>0&&value.length<=4000;
    if (typeof valuationId!=='string' || !/^[a-f0-9]{64}$/.test(valuationId) ||
        !note(basis)||!note(invalidation)) {
      throw new AppError(400,'watchlist_estimate','请提供工具的测算编号、依据和失效条件。');
    }
    const day=entry.pendingDate??valuationDay(now);
    const invalid=()=>new AppError(409,'valuation_receipt','测算编号与本次证券或日期不匹配，请重新调用估值工具。');
    let receipt;
    try { receipt=readValuationReceipt(this.data,entry.code,day,valuationId); }
    catch {throw invalid();}
    const {record, estimate:priced}=receipt;
    const score=Object.hasOwn(record,'outlook') ? record.outlook?.score ?? null : body.score ?? null;
    if(score!==null && !(typeof score==='number' && Number.isInteger(score) && Math.abs(score)<=5)) throw invalid();
    const estimate:Estimate={version:(entry.estimates.at(-1)?.version??0)+1,...priced,score,asOf:record.as_of,basis,invalidation,valuationId,modelVersion:record.model_version,
      taskId,botId,requestId:id,measuredAt:now.toISOString(),horizon:record.horizon_trading_days};
    entry.estimates.push(estimate);
    delete entry.pending;
    delete entry.pendingDate;
    this.write(current);
    return estimate;
  }
}
