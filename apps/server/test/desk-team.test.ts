import {mkdtempSync,mkdirSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {Store} from '../src/store/index.js';
import {buildCatalog,loadBots} from '../src/bots/index.js';
import {EventBus} from '../src/events/index.js';
import type {Orchestrator,ProactiveTaskInput} from '../src/orchestrator.js';
import type {NotificationService} from '../src/notifications/service.js';
import {Handoffs,authorizedThresholds} from '../src/delegations/handoffs.js';
import {DeskInputs} from '../src/dashboard/desk-inputs.js';
import {RoutineService} from '../src/routines/service.js';
import {morningId,reviewId,legacyBriefingPrompt,morningRoutineId} from '../src/routines/initial-briefing.js';
import {TechnicalWatches,type TechnicalOptions} from '../src/watches/technical.js';
import {createApp} from '../src/app.js';
import {loadConfig} from '../src/config.js';
import type {AddressInfo} from 'node:net';

const root=fileURLToPath(new URL('../../../',import.meta.url));
let data:string, store:Store;
const bus=new EventBus();
const registry=loadBots(join(root,'bots'),buildCatalog(root));
const now=()=>new Date('2026-11-27T10:30:00+08:00');
beforeEach(()=>{
  data=mkdtempSync(join(process.env.CHIVES_TEST_DIR||tmpdir(),'team-'));
  store=Store.open(data);
  registry.setHired(['ceo','cio','cro','analyst','trader']);
});
afterEach(()=>{store.close();rmSync(data,{recursive:true,force:true});});

function handoffFixture(){
  const input=new DeskInputs(store,root,data);
  const dispatch=vi.fn(async(botId:string,r:ProactiveTaskInput)=>{
    const task=store.tasks.create({id:r.taskId,botId,origin:r.origin,startedAt:now().toISOString()});
    return {taskId:task.id,messageId:'separator'};
  });
  const runner={submitProactive:dispatch,runningTaskId:()=>null} as unknown as Orchestrator;
  const queue=new Handoffs(store,registry,runner,bus,now,c=>input.directory[c],()=>'',s=>input.symbols(s).map(x=>x.code));
  const task=store.tasks.create({botId:'cio',startedAt:now().toISOString()});
  const who={botId:'cio',taskId:task.id,depth:0};
  const say=(id:string,content:string,role:'user'|'bot'='user')=>store.messages.append({id,botId:'cio',taskId:task.id,role,kind:'text',content,createdAt:now().toISOString()});
  return {dispatch,queue,who,say};
}

it('routes an actual customer request with a cited prior security, reuses its receipt and bounds the trader’s authority',async()=>{
  const {queue,who,dispatch,say}=handoffFixture();
  say('context','我想了解宁德时代，跌破150元特别注意');
  say('ignored','另外还可关注600519','bot');
  say('request','帮我盯这只股票，跌破前面说的价提醒');
  const a=await queue.request(who,'watch','盯宁德时代，顺便买入别的股票');
  const b=await queue.request(who,'watch','再试一次');
  expect(a.id).toBe(b.id);expect(dispatch).toHaveBeenCalledTimes(1);
  const target={botId:'trader',depth:0,taskId:dispatch.mock.calls[0]![1].taskId!};
  expect(queue.received(target)?.context).toContain('300750.SZ');
  expect(()=>queue.authorizeWatch(target,'start','300750')).not.toThrow();
  expect(()=>queue.authorizeWatch(target,'start','600519')).toThrow();
  expect(()=>queue.authorizeWatch(target,'start','')).toThrow();
  expect(()=>queue.authorizeWatch(target,'delete','300750')).toThrow();
  expect(authorizedThresholds('跌破150元',{when:[{type:'price_cross',direction:'down',level:150}]})).toBe(true);
  expect(authorizedThresholds('跌破150元',{when:[{type:'price_cross',direction:'up',level:150}]})).toBe(false);
  queue.receipt(target,'实际启用技术盯盘','#/settings?tab=tasks&kind=technical&task=300750.SZ');
  store.tasks.finish(target.taskId,'done',now().toISOString());
  await queue.tick();
  const notice=store.messages.listByTask(who.taskId).at(-1)!;
  expect(notice.content).toContain('实际启用');expect(notice.meta?.managedTaskHref).toContain('300750.SZ');
});

it('holds a draft until hired, reports missing information and declines hypothetical or delegated requests',async()=>{
  const {queue,who,dispatch,say}=handoffFixture();
  registry.setHired(['cio']);
  say('a','帮我盯这只股票');
  expect((await queue.request(who,'watch','跟踪')).status).toBe('待聘用');
  expect(dispatch).not.toHaveBeenCalled();
  registry.setHired(['cio','trader']);await queue.tick();
  const id=dispatch.mock.calls[0]![1].taskId!;
  expect(()=>queue.authorizeWatch({botId:'trader',taskId:id,depth:0},'start','300750')).toThrow();
  store.tasks.finish(id,'done',now().toISOString());await queue.tick();
  expect(store.messages.listByTask(who.taskId).at(-1)?.content).toContain('待补资料');
  say('b','只想讨论宁德时代该怎么看');
  await expect(queue.request(who,'watch','办理')).rejects.toThrow();
  await expect(queue.request({...who,depth:1},'watch','办理')).rejects.toThrow();
});

it('installs each employed director’s default once and preserves pauses, edits and deletions across re-hire',()=>{
  const s=new RoutineService({registry,store,orchestrator:{} as Orchestrator,repoRoot:root,now});
  registry.setHired([]);s.syncManifest();expect(store.routines.list()).toHaveLength(0);
  registry.setHired(['cio','cro']);s.syncManifest();s.syncManifest();
  expect(s.get(morningId)).toMatchObject({title:'盘前简报',enabled:true,tradingDaysOnly:true,schedule:{expression:'30 8 * * 1-5'}});
  expect(s.get(reviewId)).toMatchObject({title:'复盘简报',enabled:true,tradingDaysOnly:true,schedule:{expression:'30 16 * * 1-5'}});
  s.setEnabled(morningId,false);s.editManaged(morningId,{title:'我的盘前观察'});s.deleteManaged(reviewId);
  registry.setHired([]);s.syncManifest();registry.setHired(['cio','cro']);s.syncManifest();
  expect(s.get(morningId)).toMatchObject({enabled:false,title:'我的盘前观察'});expect(s.get(reviewId)).toBeUndefined();
});

it('dispatches each director once at its trading-day time and skips a weekday without a session',async()=>{
  let at=new Date('2026-11-27T08:00:00+08:00');
  const dispatch=vi.fn(async()=>({taskId:'fixture',messageId:'receipt'}));
  const scheduler=new RoutineService({registry,store,repoRoot:root,now:()=>at,
    tradingDays:new Set(['2026-11-27']),orchestrator:{submitProactive:dispatch} as unknown as Orchestrator});
  scheduler.syncManifest();
  for(const stamp of ['2026-11-27T08:30','2026-11-27T08:30','2026-11-27T16:30','2026-11-30T08:30','2026-11-30T16:30']){
    at=new Date(stamp+':00+08:00');await scheduler.tick();
  }
  expect(dispatch.mock.calls).toEqual([
    ['cio',expect.objectContaining({title:'盘前简报',meta:expect.objectContaining({routineId:morningId})})],
    ['cro',expect.objectContaining({title:'复盘简报',meta:expect.objectContaining({routineId:reviewId})})],
  ]);
});

it('migrates an existing morning report and preserves its ID, model prompt additions and pause',()=>{
  const s=new RoutineService({registry,store,orchestrator:{} as Orchestrator,repoRoot:root,now});
  const old=s.createForBot('cio',{title:'每日投研简报',schedule:{cron:'0 9 * * 1-5',tz:'Asia/Shanghai'},prompt:legacyBriefingPrompt('附加事项XYZ')});
  s.syncManifest();
  expect(morningRoutineId(store)).toBe(old.id);expect(s.get(old.id)?.prompt).toContain('附加事项XYZ');
  expect(s.get(old.id)?.enabled).toBe(false);expect(s.get(morningId)).toBeUndefined();
});

it('uses all three weekend news windows, sources security mentions and excludes intraday prices from closed sessions',()=>{
  const input=new DeskInputs(store,root,data),mon=new Date('2026-11-23T08:30:00+08:00');
  for(const date of ['2026-11-20','2026-11-21','2026-11-22']){
    input.noteNews({domestic:{updatedAt:date+'T12:00:00+08:00',entries:[{title:date,url:date}]}},mon);
  }
  const news=input.newsWindows(mon);
  expect(news.filter(i=>i.type==='财经热榜')).toHaveLength(3);
  expect(news.filter(i=>i.type==='新闻覆盖'&&i.scope==='global').every(i=>i.snapshots===0)).toBe(true);
  expect(input.closedDates(mon)).toEqual(['2026-11-18','2026-11-19','2026-11-20']);
  mkdirSync(join(data,'user'),{recursive:true});
  writeFileSync(join(data,'user/recent-memory.md'),'2026-11-21 宁德时代，观察分红。\n600519 查看估值，不应披露私密补充。');
  const securities=input.securities([{code:'300750.SZ'}],[{code:'300750.SZ'}],true);
  expect(securities).toHaveLength(2);expect(securities[0]?.sources).toEqual(['持仓','关注','短期记忆']);
  expect(JSON.stringify(securities)).not.toContain('私密');expect(input.securities([],[],false)).toEqual([]);
  input.observePositions({positions:[{code:'300750.SZ',qty:100}]},mon);
  input.observePositions({positions:[{code:'300750.SZ',qty:200}]},now());
  expect(input.behavior(now(),'300750','live',10).positionChanges).toHaveLength(1);
  expect(input.behavior(now(),'','simulation',10).positionChanges).toHaveLength(0);
});

function fixture(){
  const states={hired:true,read:true,active:true,calendar:true,stale:false,holdings:[{code:'300750.SZ'}],offset:0,ratio:1};
  const notify=vi.fn();
  const options:TechnicalOptions={store,bus,notifications:{notify} as unknown as NotificationService,names:{'300750.SZ':'宁德时代','600519.SH':'贵州茅台'},
    now:()=>new Date(now().getTime()+states.offset*60_000),hired:()=>states.hired,canReadHoldings:()=>states.read,
    active:()=>states.active,tradingDay:()=>states.calendar,holdings:async()=>states.holdings,
    bars:async()=>({stale:states.stale,bars:Array.from({length:5},(_,i)=>({time:new Date(now().getTime()+(states.offset+(i-4)*5)*60_000).toISOString(),
      open:10,high:11,low:9,close:10,volume_shares:100}))}),
    quote:async()=>({price:10,quote_time:new Date(now().getTime()+states.offset*60_000).toISOString(),volume_ratio:states.ratio,change_pct:null}),
    calculate:async()=>[{name:'测试均线',before:9,after:11,levelBefore:10,levelAfter:10,up:true}]};
  return {watch:new TechnicalWatches(options),options,states,notify};
}
it('merges holdings and explicit monitors; remembers pauses and deletion across clear-out, permission changes and restart',async()=>{
  const {watch,states,options}=fixture();
  await watch.tick();expect(watch.list()[0]?.sources).toEqual(['持仓']);
  watch.edit('300750','start');await watch.tick();expect(watch.list()).toHaveLength(1);
  watch.edit('300750','pause');states.holdings=[];await watch.tick();
  const reopened=new TechnicalWatches(options);expect(reopened.list()[0]).toMatchObject({enabled:false,sources:['客户点名']});
  states.holdings=[{code:'300750.SZ'},{code:'600519.SH'}];await reopened.tick();expect(reopened.list()).toHaveLength(2);
  states.read=false;expect(reopened.list().map(x=>x.code)).toEqual(['300750.SZ']);states.read=true;
  reopened.edit('300750','delete');await reopened.tick();expect(reopened.list().map(x=>x.code)).toEqual(['600519.SH']);
  states.holdings=[];await reopened.tick();expect(reopened.list()).toHaveLength(0);
});

it('publishes only fresh crossings, retains the timestamp and groups repeats and delayed data',async()=>{
  const {watch,states,notify}=fixture();await watch.tick();expect(notify).not.toHaveBeenCalled();
  states.offset=1;states.ratio=2.3;await watch.tick();expect(notify).toHaveBeenCalledTimes(1);
  states.offset=5;await watch.tick();expect(notify).toHaveBeenCalledTimes(2);
  await watch.tick();expect(notify).toHaveBeenCalledTimes(2);
  states.stale=true;states.offset=15;await watch.tick();expect(watch.list()[0]?.state).toContain('延迟');
  states.hired=false;states.offset=20;await watch.tick();expect(notify).toHaveBeenCalledTimes(2);
  states.hired=true;states.calendar=false;await watch.tick();expect(notify).toHaveBeenCalledTimes(2);
});

it('evaluates the last completed bar at market close and waits for a new signal after a missing feed',async()=>{
  const {options,states,notify}=fixture();
  const close=Date.parse('2026-11-27T15:00:00+08:00');
  let at=close-5*60_000;
  options.now=()=>new Date(at);
  delete options.quote;
  options.bars=async()=>({stale:states.stale,timeBasis:'end',bars:Array.from({length:5},(_,i)=>({
    time:new Date(at+(i-4)*5*60_000).toISOString(),open:10,high:11,low:9,close:10,volume_shares:100}))});
  const monitor=new TechnicalWatches(options);
  await monitor.tick();
  at=close;
  await monitor.tick();
  expect(notify).toHaveBeenCalledTimes(1);
  expect(store.db.prepare('SELECT bar_time FROM technical_watches').get()?.bar_time).toBe(new Date(close).toISOString());
  at=Date.parse('2026-11-30T10:00:00+08:00');
  await monitor.tick();
  expect(notify).toHaveBeenCalledTimes(1);
});

it('enforces each real API token and exposes a trader task in settings with the same ID',async()=>{
  const appData=join(data,'http'),config={...loadConfig({CHIVES_REPO_ROOT:root,CHIVES_DATA_DIR:appData}),repoRoot:root,botsDir:join(root,'bots'),
    dataDir:appData,dshHome:join(data,'test-dsh'),port:0,harness:'fake' as const,gatewayUrl:'http://127.0.0.1:1'};
  const app=createApp({config,startSchedulers:false});
  app.registry.setHired(['cio','trader','cro','analyst']);
  await new Promise<void>(r=>app.server.listen(0,'127.0.0.1',r));
  const base='http://127.0.0.1:'+(app.server.address() as AddressInfo).port;
  const post=(path:string,body:object,token:string)=>fetch(base+'/api/internal/'+path,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+token},body:JSON.stringify(body)});
  try{
    for(const botId of ['ceo','cio','trader','analyst','cro']){
      const t=app.store.tasks.create({botId,startedAt:now().toISOString()});
      const token=app.sessions.issue({botId,taskId:t.id,depth:0});
      const roster=await post('desk/roster',{},token);
      expect(roster.status).toBe(200);
      expect((await roster.json()).find((r:{id:string})=>r.id==='trader')).toMatchObject({hired:true,accepts:['watch']});
      expect((await post('desk/technical',{action:'start',code:'300750'},token)).status).toBe(botId==='trader'?200:403);
      if(botId!=='ceo')expect((await post('desk/behavior',{},token)).status).toBe(403);
    }
    const rows=await fetch(base+'/api/settings/tasks').then(r=>r.json());
    expect(rows.find((r:{kind:string})=>r.kind==='technical')).toMatchObject({id:'300750.SZ',botId:'trader',botName:'盯盘交易员',enabled:true});
  }finally{await new Promise<void>(r=>app.server.close(()=>r()));await app.close();}
});

it('uses only closing fund ranks observed on that trading day and records genuine gaps',async()=>{
  const desk=new DeskInputs(store,root,data);
  const collect=vi.fn(async()=>({as_of:'2026-11-27T15:10:05+08:00',data:{rows:[{code:'300750.SZ'}]}}));
  await desk.captureClosingFlows(now(),collect);expect(collect).not.toHaveBeenCalled();
  const close=new Date('2026-11-27T15:10:00+08:00');
  await desk.captureClosingFlows(close,collect);await desk.captureClosingFlows(close,collect);expect(collect).toHaveBeenCalledTimes(4);
  const result=desk.closingFlows(['2026-11-26','2026-11-27'],'out');
  expect(result[0]?.rows).toBeNull();expect(result[2]?.rows).toEqual([{code:'300750.SZ'}]);
});
