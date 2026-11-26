import {existsSync,readFileSync} from 'node:fs';
import {join} from 'node:path';
import type {Store} from '../store/index.js';
import {MemoryService} from '../memory/service.js';
import {memorySlug} from '../memory/policy.js';
import {writePrivateJson} from './interview-profile.js';
import {sampleReportSegment} from './style-report-turn.js';
import {CustomerReviewer,readJson,type ReviewJob,type Evidence} from './customer-review.js';

const DAY=86_400_000;
const dateAt=(ms:number)=>new Date(ms+8*3600_000).toISOString().slice(0,10);
const midnight=(day:string)=>Date.parse(day+'T00:00:00+08:00');
const key='ceo.archive.daily.';
type Access={enabled:boolean;portfolio:boolean;roles:{id:string;role:string}[]};
type Scope={day:string;after:number};
type Input={evidence:Evidence;document:{day:string;readAt:string;roles:Access['roles'];memories:Record<string,ReturnType<MemoryService['list']>>;recent:unknown};after:number;more:boolean;access:string};

export class ArchiveMemory {
  private timer?:ReturnType<typeof setInterval>;
  private busy=false;
  private stopped=false;
  private nextAttempt=0;
  constructor(private store:Store,private reviewer:CustomerReviewer,private memory:MemoryService,
    private access:()=>Access,private portfolio:(date:Date)=>Promise<Record<string,unknown>>,private now=()=>new Date()){}
  status(){
    const through=this.store.settings.get<string>(key+'through')??null;
    return {kind:'archive' as const,id:'ceo-daily',botId:'ceo',title:'每日客户档案整理',enabled:true,
      conditionText:'总经理出厂任务 · 每日启动或跨日后整理，离线日期按序补齐',state:!this.access().enabled?'等待用户数据库权限':this.busy?'整理中':this.store.settings.get<string>(key+'error')||(through===dateAt(this.now().getTime()-DAY)?'已完成，等待下一日':'等待检查'),
      through,createdAt:this.store.settings.get<string>(key+'created')??this.now().toISOString()};
  }
  start(){
    this.store.settings.delete(key+'enabled');
    if(!this.store.settings.get(key+'created'))this.store.settings.set(key+'created',this.now().toISOString());
    void this.tick();this.timer=setInterval(()=>void this.tick(),30_000);this.timer.unref();
  }
  stop(){this.stopped=true;if(this.timer)clearInterval(this.timer);}
  private async collect(scope:Scope,access:Access):Promise<Input>{
    const {day,after}=scope,begin=midnight(day);
    const rows=this.store.db.prepare(`SELECT m.rowid n,m.id,m.role,m.content,m.created_at,m.bot_id,m.task_id FROM messages m
      JOIN tasks t ON t.id=m.task_id WHERE m.rowid>? AND m.created_at>=? AND m.created_at<? AND m.kind='text' AND m.role IN ('user','bot')
      AND t.depth=0 AND t.delegated=0 AND (t.origin IS NULL OR EXISTS
        (SELECT 1 FROM messages u WHERE u.task_id=t.id AND u.role='user' AND u.kind='text')) AND COALESCE(t.segment_reason,'')<>? ORDER BY m.rowid LIMIT 51`)
      .all(after,new Date(begin).toISOString(),new Date(begin+DAY).toISOString(),sampleReportSegment);
    const evidence:Evidence={},allowed=new Set(access.roles.map(b=>b.id));
    let end=after,size=0;
    for(const row of rows.slice(0,50)){
      if(size>=22000)break;
      end=Number(row.n);
      if(!allowed.has(String(row.bot_id)))continue;
      evidence[String(row.id)]={role:row.role,text:row.content,bot:row.bot_id,at:row.created_at,task:row.task_id,message:row.id};
      size+=String(row.content).length;
    }
    const at=this.now();
    if(access.portfolio&&after===0){
      const snapshot=await this.portfolio(new Date(begin+DAY-1));
      evidence.portfolio={role:'snapshot',readAt:at.toISOString(),...snapshot};
      if(Array.isArray(snapshot.liveTrades))snapshot.liveTrades.forEach((trade,i)=>{evidence['trade-'+(i+1)]={role:'trade',record:trade};});
    }
    const memories=Object.fromEntries(access.roles.map(b=>[b.id,this.memory.list(b.id)]));
    const recentPath=join(this.reviewer.dir,'user-archive-state/ceo-recent.json');
    const recent=existsSync(recentPath)?readJson(recentPath):{};
    return {document:{day,readAt:at.toISOString(),roles:access.roles,memories,recent},evidence,after:end,more:rows.some(row=>Number(row.n)>end),access:JSON.stringify(access)};
  }
  private publishStaff(job:ReviewJob,input:Input){
    const roles=new Set(input.document.roles.map(b=>b.id));
    for(const item of job.review.staff){
      if(!roles.has(item.bot))continue;
      const texts=item.refs.map(ref=>input.evidence[ref]).filter(r=>r?.role==='user').map(r=>String(r!.text));
      if(!texts.some(t=>t.includes(item.quote)))continue;
      const old=this.memory.get(item.bot,memorySlug(item.title));
      if(old?.source==='user'||(old?.body===item.text))continue;
      this.memory.write({botId:item.bot,taskId:job.id,actor:'capture',candidate:{title:item.title,kind:'note',body:item.text,evidence:item.quote},userTexts:texts});
    }
    for(const item of job.review.retire){
      const before=input.document.memories[item.bot]?.find(m=>m.slug===item.slug);
      if(!before||!roles.has(item.bot))continue;
      this.memory.retireForReview(item.bot,before,item.reason,job.id);
    }
  }
  async tick(){
    if(this.busy||this.stopped||this.now().getTime()<this.nextAttempt||!this.access().enabled)return;
    this.busy=true;
    try{
      const yesterday=dateAt(this.now().getTime()-DAY);
      const through=this.store.settings.get<string>(key+'through');
      let scope=this.store.settings.get<Scope>(key+'cursor')??{day:through?dateAt(midnight(through)+DAY):yesterday,after:0};
      while(scope.day<=yesterday&&!this.stopped){
        this.store.settings.set(key+'cursor',scope);
        const access=this.access();if(!access.enabled)return;
        const id='daily-'+scope.day+'-'+scope.after;
        const plan=join(this.reviewer.dir,'user-archive-state',id+'-plan.json');
        let saved=existsSync(plan)?readJson<{input:Input;job:ReviewJob}>(plan):undefined;
        if(!saved||saved.input.access!==JSON.stringify(access)){
          const input=await this.collect(scope,access);
          const review=await this.reviewer.review('daily',input.document,input.evidence);
          saved={input,job:{id,kind:'daily',preset:this.reviewer.preset('daily'),at:new Date(midnight(scope.day)+DAY-1).toISOString(),evidence:input.evidence,review}};
          if(JSON.stringify(this.access())!==input.access||this.stopped)return;
          writePrivateJson(plan,saved);
        }
        if(this.stopped||JSON.stringify(this.access())!==saved.input.access)return;
        this.reviewer.publish(saved.job);
        this.publishStaff(saved.job,saved.input);
        const completedDay=scope.day;
        scope=saved.input.more?{day:scope.day,after:saved.input.after}:{day:dateAt(midnight(scope.day)+DAY),after:0};
        if(!saved.input.more)this.store.settings.set(key+'through',completedDay);
        this.store.settings.set(key+'cursor',scope);this.store.settings.delete(key+'error');
      }
    }catch(error){
      if(!this.stopped){this.store.settings.set(key+'error',error instanceof Error?error.message.slice(0,180):'整理失败，等待重试');this.nextAttempt=this.now().getTime()+5*60_000;}
    }finally{this.busy=false;}
  }
}
