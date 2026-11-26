import { randomUUID } from 'node:crypto';
import type { Store } from '../store/index.js';
import type { BotRegistry } from '../bots/index.js';
import type { Orchestrator } from '../orchestrator.js';
import { AppError } from '../errors.js';
import { toMessageDto } from '../api/dto.js';
import type { EventBus } from '../events/index.js';
import type { SessionIdentity } from './tokens.js';
import { normalizeSymbolCode } from '../symbols.js';

type Request = {id:string;source_task:string;source_bot:string;source_message:string;target:string;intent:string;
  original:string;context:string;task_link:string|null;brief:string;status:string;target_task:string;outcome:string|null;created_at:string};
const labels:Record<string,string> = {draft:'待聘用',queued:'待接手',running:'已受理',done:'已答复',failed:'办理失败',clarify:'待补资料'};
const discussionOnly = /(?:不要|不用|无需|先别|暂不)(?:.{0,6})(?:执行|办理|转交|创建|设置|盯盘|监测)|只(?:想|是)?(?:讨论|问问|了解|咨询|聊聊)|假如我(?:说|要求)/;

export function authorizedThresholds(original:string,body:Record<string,unknown>){
  const supplied=new Set((original.replace(/\d{6}(?:\.(SH|SZ|BJ))?/gi,'').match(/-?\d+(?:\.\d+)?/g)??[]).map(Number));
  const rules=[body.when,body.give_up,body.market].flatMap(v=>Array.isArray(v)?v:[]);
  if(!rules.length)return false;
  return rules.every(input=>{
    if(!input||typeof input!=='object')return false;
    const rule=input as Record<string,unknown>;
    const numbers=Object.values(rule).filter((v):v is number=>typeof v==='number');
    if(!numbers.length||!numbers.every(v=>supplied.has(v)))return false;
    const words=JSON.stringify(rule);
    if(rule.type==='price_cross'){
      const direction=rule.direction==='up'?'(?:涨破|上穿|突破|超过|升至|高于|涨到|涨至)':'(?:跌破|下穿|下破|低于|回落(?:至|到)?|跌到|跌至)';
      const matches=[...original.matchAll(new RegExp(direction+'[\\s人民币￥¥价格]*(-?\\d+(?:\\.\\d+)?)','g'))];
      return matches.some(m=>Number(m[1])===rule.level);
    }
    if(rule.type==='pct_change'&&!/%|％|百分之|涨幅|跌幅|涨跌幅/.test(original))return false;
    if(rule.type==='volume_ratio'&&!/量比/.test(original))return false;
    if(rule.type==='open_pct'&&!/开盘/.test(original))return false;
    if(rule.type==='index_pct' && (!/指数|大盘/.test(original)||!original.includes(String(rule.code).slice(0,6))))return false;
    if(/below|down|lte|less/.test(words) && !/跌|低于|下穿|下破|回落/.test(original))return false;
    if(/above|up|gte|greater/.test(words) && !/涨|高于|上穿|突破|超过|升至/.test(original))return false;
    return true;
  });
}

export class Handoffs {
  private working = false;
  constructor(private store:Store, private registry:BotRegistry, private runner:Orchestrator,
    private bus:EventBus, private now:()=>Date, private names:(code:string)=>string|undefined,
    private attachments:(from:string,to:string,messageId:string)=>string = ()=>'',
    private symbols:(text:string)=>string[] = ()=>[]) {}

  async request(who:SessionIdentity, intent:unknown, brief:unknown) {
    const task=this.store.tasks.get(who.taskId);
    if (!task || task.botId!==who.botId || task.delegated || who.depth || task.status!=='running' || !this.registry.isHired(who.botId))
      throw new AppError(403,'handoff_source','请从客户正在进行的会话转交。');
    const original=this.store.messages.listByTask(task.id).findLast(m=>m.role==='user' && m.kind==='text');
    if (!original || discussionOnly.test(original.content) && !/(?:不用再盯|不再盯|取消盯盘|删除盯盘)/.test(original.content)) throw new AppError(403,'consultation','请在当前会话答疑。');
    if (typeof intent!=='string' || typeof brief!=='string' || !brief.trim() || brief.length>2400)
      throw new AppError(400,'handoff_input','请写明承办事项和交接说明。');
    const target=this.registry.list().find(bot=>bot.accepts_handoffs?.includes(intent))?.id;
    if (!target || target===who.botId) throw new AppError(400,'handoff_target','请选择能承办该事项的其他岗位。');
    let context='';
    if (intent==='watch' && /这只|那只|这家|刚才|前面|说的价|上述/.test(original.content)) {
      const current=this.symbols(original.content);
      const previous=this.store.messages.listByTask(task.id).filter(m=>m.role==='user'&&m.kind==='text'&&m.id!==original.id).reverse();
      for (const msg of previous) {
        const found=this.symbols(msg.content);
        if(!found.length)continue;
        if(found.length===1 && (!current.length || current.includes(found[0]!))) {
          context=found[0]!;
          if(/说的价|刚才的价|上述价/.test(original.content)) {
            const levels=msg.content.match(/(?:跌破|低于|突破|涨破|高于|下穿|上穿)\s*[-+]?\d+(?:\.\d+)?(?:元|%|％)?/g);
            if(levels)context+=' '+levels.join('、');
          }
        }
        break;
      }
    }
    const db=this.store.db;
    db.prepare('INSERT OR IGNORE INTO desk_handoffs (id,source_task,source_bot,source_message,target,intent,original,brief,status,target_task,created_at,context) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)').run(
      randomUUID(),task.id,who.botId,original.id,target,intent,original.content,brief.trim(),
      this.registry.isHired(target)?'queued':'draft',randomUUID(),this.now().toISOString(),context);
    const get=()=>db.prepare('SELECT * FROM desk_handoffs WHERE source_message=? AND target=? AND intent=?')
      .get(original.id,target,intent) as unknown as Request;
    const row=get();
    this.notice(row,row.status);
    await this.tick();
    const state=get();
    return {id:state.id,target,status:labels[state.status],conversation:this.link(state),outcome:state.outcome};
  }
  private link(row:Request) { return row.status==='draft'?'#/bots':'#/bot/'+row.target+'?task='+encodeURIComponent(row.target_task); }
  private notice(row:Request,status:string) {
    const id='handoff:'+row.id+':'+status;
    if(this.store.messages.get(id)) return;
    const target=this.registry.nameFor(row.target);
    const href=this.link({...row,status});
    const msg=this.store.messages.append({id,botId:row.source_bot,taskId:row.source_task,role:'system',kind:'notice',
      content:target+' · '+labels[status]+(row.outcome?'。'+row.outcome:''),
      meta:{handoffHref:href,handoffId:row.id,...(row.task_link?{managedTaskHref:row.task_link}:{})},createdAt:this.now().toISOString()});
    this.bus.publish({type:'message.created',botId:msg.botId,taskId:row.source_task,message:toMessageDto(msg)});
  }
  private set(row:Request,status:string,outcome=row.outcome) {
    this.store.db.prepare('UPDATE desk_handoffs SET status=?, outcome=? WHERE id=?').run(status,outcome,row.id);
    this.notice({...row,status,outcome},status);
  }
  async idle() { while(this.working)await new Promise(resolve=>setTimeout(resolve,10)); }
  async tick() {
    if(this.working) return;
    this.working=true;
    try {
      const entries=this.store.db.prepare("SELECT * FROM desk_handoffs WHERE status IN ('queued','draft','running') ORDER BY created_at").all() as unknown as Request[];
      for(const row of entries) {
        const task=this.store.tasks.get(row.target_task);
        if(task){
          if(task.status==='running'){ if(row.status!=='running')this.set(row,'running'); continue; }
          const reply=this.store.messages.listByTask(task.id).findLast(m=>m.role==='bot'&&m.kind==='text')?.content;
          const watchWrite=row.intent==='watch' && /盯|提醒|监测|监控/.test(row.original);
          const verified=row.outcome;
          const status=task.status!=='done'?'failed':watchWrite && !verified?'clarify':'done';
          this.set(row,status,verified || (status==='clarify'?'尚无已生效的盯盘变更，请在承接会话核对标的或条件。':(reply?.slice(0,450) || '请查看承接会话的执行记录。')));
          continue;
        }
        if(!this.registry.isHired(row.target)){if(row.status!=='draft')this.set(row,'draft');continue;}
        if(this.runner.runningTaskId(row.target)){if(row.status!=='queued')this.set(row,'queued');continue;}
        try{
          const attachments=this.attachments(row.source_bot,row.target,row.source_message);
          await this.runner.submitProactive(row.target,{origin:'handoff',taskId:row.target_task,title:row.original.trim().slice(0,75)||'客户委托',
            label:'客户转交 · '+this.registry.nameFor(row.source_bot),meta:{original:row.original,sourceBot:row.source_bot,handoffId:row.id},
            prompt:'客户原话（系统核实）\n'+row.original+(row.context?'\n客户在本会话此前确认的标的或点位：'+row.context:'')+'\n同事整理（工作参考，原话决定授权范围）\n'+row.brief+
              '\n承办事项：'+row.intent+'。按本岗权限办理；标的、授权或条件不明时，向客户核实。已有暂停记录请保留。'+attachments});
          this.set(row,'running');
        }catch(e){if(!(e instanceof AppError && e.code==='bot_busy'))this.set(row,'failed',e instanceof AppError?e.message:'承接任务启动失败。');}
      }
    }finally{this.working=false;}
  }

  /** Only the real customer message can extend a handed-off turn's authority. */
  received(who:SessionIdentity) {
    const task=this.store.tasks.get(who.taskId);
    if(task?.origin!=='handoff' || this.store.messages.listByTask(task.id).some(m=>m.role==='user'))return;
    return this.store.db.prepare('SELECT * FROM desk_handoffs WHERE target_task=? AND target=?').get(task.id,who.botId) as unknown as Request|undefined;
  }
  authorizeWatch(who:SessionIdentity,action:string,raw:unknown) {
    const row=this.received(who); if(!row)return;
    const code=normalizeSymbolCode(String(raw??''));
    const name=this.names(code);
    const actions:Record<string,RegExp>={start:/盯|监控|监测|提醒|跟踪/,resume:/恢复|重新开启|重新启用|继续盯/,pause:/暂停|先停/,delete:/删除|取消|撤销|不再盯|不用再盯/,update:/改|调|变更/};
    const mentioned=/^\d{6}\.(SH|SZ|BJ)$/.test(code) && (row.original.includes(code.slice(0,6)) || !!name && row.original.includes(name) || row.context.split(' ')[0]===code);
    if(row.intent!=='watch' || !mentioned || !actions[action]?.test(row.original) ||
       action==='start' && /暂停|取消|删除|不要盯|不再盯/.test(row.original))
      throw new AppError(403,'handoff_scope','请客户在承接会话确认证券和具体操作。');
  }
  receipt(who:SessionIdentity,text:string,link:string|null=null) {
    const row=this.received(who); if(row)this.store.db.prepare('UPDATE desk_handoffs SET outcome=?, task_link=COALESCE(?,task_link) WHERE id=?').run(text,link,row.id);
  }
}
