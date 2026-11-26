import {execFileSync} from 'node:child_process';
import {mkdtempSync,readFileSync,writeFileSync,rmSync,appendFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import type {AddressInfo} from 'node:net';
import {it,expect,vi} from 'vitest';
import {createApp} from '../src/app.js';
import {loadConfig} from '../src/config.js';
import type {HarnessDriver} from '../src/harness/types.js';
import {FakeDriver} from '../src/harness/fake.js';
import {ArchiveMemory} from '../src/settings/archive-memory.js';
import {CustomerReviewer} from '../src/settings/customer-review.js';

const root=fileURLToPath(new URL('../../../',import.meta.url));
const temp=()=>mkdtempSync(join(process.env.CHIVES_TEST_DIR??tmpdir(),'ceo-'));
function config(data:string){return {...loadConfig({CHIVES_REPO_ROOT:root,CHIVES_DATA_DIR:data}),repoRoot:root,botsDir:join(root,'bots'),dataDir:data,dshHome:join(data,'dsh'),port:0,harness:'fake' as const};}
const header={'Content-Type':'application/json','X-Chives-Kernel-Manager':'local'};
const ids=['ceo','cio','cro','trader','analyst'];
it('reads all three current documents on consecutive turns of every job and protects the factory task',async()=>{
  const dir=temp();
  const driver:HarnessDriver=new FakeDriver();
  const captured=new Map<string,string>();
  driver.prompt=async(bot,session,prompt,sink)=>{captured.set(bot.id,prompt);sink({type:'message',text:'收到。'});return {stopReason:'end_turn'};};
  const app=createApp({config:config(dir),driver,startSchedulers:false});
  try{
    await new Promise<void>(r=>app.server.listen(0,'127.0.0.1',r));
    const url='http://127.0.0.1:'+(app.server.address() as AddressInfo).port;
    app.store.settings.set('ceo.archive.daily.enabled',false);
    const tasks=await fetch(url+'/api/settings/tasks').then(r=>r.json());
    expect(tasks.filter((t:{kind:string})=>t.kind==='archive')).toMatchObject([{id:'ceo-daily',botId:'ceo',enabled:true}]);
    for(const method of ['PATCH','DELETE']){
      const res=await fetch(url+'/api/settings/tasks/archive/ceo-daily',{method,headers:header,...(method==='PATCH'?{body:'{"enabled":false}'}:{})});
      expect(res.status).toBe(403);expect((await res.json()).error.code).toBe('factory_task');
    }
    for(const pass of [1,2]){
      const source={source_id:'ctx'+pass,origin:'dialogue',effective_at:new Date().toISOString(),evidence:{session:'已核实测试来源'+pass},
        decisions:{financial_statement_skill:{old:pass===1?null:1,value:pass,decision:'applied',reason:'测试理由'+pass,refs:['session']}}};
      execFileSync(process.env.CALENDAR_PYTHON??join(root,'.venv/bin/python'),[join(root,'scripts/user_archive.py'),'--data',dir,'apply'],{input:JSON.stringify(source)});
      appendFileSync(join(dir,'user/user-index.md'),'\n最新索引'+pass);
      writeFileSync(join(dir,'user/recent-memory.md'),'最新短记'+pass);
      for(const id of ids){
        await app.orchestrator.submitMessage(id,'继续上一个问题 '+pass);
        await vi.waitFor(()=>expect(app.store.tasks.latestForBot(id)?.status).toBe('done'));
        const prompt=captured.get(id)??'';
        for(const mark of ['测试理由'+pass,'最新索引'+pass,'最新短记'+pass])expect(prompt).toContain(mark);
      }
    }
  }finally{app.sse.closeAll();await new Promise<void>(r=>app.server.close(()=>r()));await app.close();rmSync(dir,{recursive:true,force:true});}
});
it('advances the Shanghai checkpoint only after publication and catches up missed days including weekends',async()=>{
  const dir=temp(),app=createApp({config:config(dir),startSchedulers:false});
  let clock=new Date('2026-11-28T00:01:00+08:00');
  try{
    const seen:string[]=[];
    const reviewer=new CustomerReviewer(dir,root,async prompt=>{
      const pkg=JSON.parse(prompt.split('资料包（JSON）\n').at(-1)!);
      seen.push(pkg.document.day);
      return JSON.stringify({overview:'无新的有据事项',attributes:[],recent:[],longTerm:[],preferences:[]});
    });
    const task=new ArchiveMemory(app.store,reviewer,app.memory,()=>({enabled:true,portfolio:true,roles:ids.map(id=>({id,role:id}))}),async()=>({}),()=>clock);
    await task.tick();expect(task.status().through).toBe('2026-11-27');
    clock=new Date('2026-12-01T00:01:00+08:00');
    await task.tick();await task.tick();
    expect(seen).toEqual(['2026-11-27','2026-11-28','2026-11-29','2026-11-30']);
    expect(task.status().through).toBe('2026-11-30');
  }finally{await app.close();rmSync(dir,{recursive:true,force:true});}
});
it('retains P0 when both a new survey and a stated fact conflict, preserving their reasons',async()=>{
  const dir=temp(),app=createApp({config:config(dir),startSchedulers:false});
  try{
    const reviewer=new CustomerReviewer(dir,root,async()=>''),evidence={first:{role:'user',message:'1'},second:{role:'user',message:'2'}};
    const at='2026-11-20T08:00:00Z',id='A01',refs=['first','second'];
    const review={overview:'核验',attributes:[{id,value:4,reason:'两次独立核验',refs,verifiedBehavior:true}],recent:[],preferences:[],longTerm:[],retire:[],resolved:[],staff:[]};
    reviewer.publish({id:'daily-evidence',at,kind:'daily',evidence,review});
    const fields=reviewer.dictionary(),all=Object.fromEntries(fields.flatMap(f=>[1,2].map(n=>[f.id+'-'+n,{selected:'确定',note:''}])));
    reviewer.publish({id:'intake-later',at:'2026-11-24T08:00:00Z',kind:'intake',evidence:all,document:{survey:'ceo-interview.v1'},review:{...review,attributes:fields.map(f=>({id:f.id,value:f.id==='A01'?8:null,refs:[f.id+'-1',f.id+'-2'],reason:'问卷依据'}))}});
    reviewer.publish({id:'daily-stated',at:'2026-11-25T08:00:00Z',kind:'daily',evidence,review:{...review,attributes:[{id,value:9,reason:'本人说法',refs,explicitFact:true}]}});
    expect(JSON.parse(readFileSync(join(dir,'user/attributes/values.json'),'utf8')).financial_statement_skill).toBe(4);
    const finding=JSON.parse(readFileSync(join(dir,'user/reviews/interview-result.json'),'utf8')).findings[0];
    expect(finding.status).toBe('待核实');expect(finding.reason).toContain('P0');
  }finally{await app.close();rmSync(dir,{recursive:true,force:true});}
});
it('allows only the CEO to propose an edit, and publishes only after the customer receives and confirms it',async()=>{
  const dir=temp(), app=createApp({config:config(dir),startSchedulers:false});
  try{
    await new Promise<void>(r=>app.server.listen(0,'127.0.0.1',r));
    const base='http://127.0.0.1:'+(app.server.address() as AddressInfo).port;
    async function propose(botId:string){
      const at=new Date().toISOString();
      const task=app.store.tasks.create({botId,startedAt:at});
      const quote='请以后先给我两句结论';
      app.store.messages.append({id:task.id+'-customer',botId,taskId:task.id,role:'user',kind:'text',content:quote,createdAt:at});
      const token=app.sessions.issue({botId,taskId:task.id,depth:0});
      const res=await fetch(base+'/api/internal/user/propose-note',{method:'POST',headers:{...header,authorization:'Bearer '+token},body:JSON.stringify({destination:'preferences',quote,text:'先给两句结论',reason:'本人明确的长期沟通要求'})});
      return {task,res,at};
    }
    expect((await propose('analyst')).res.status).toBe(403);
    const {task,res,at}=await propose('ceo');expect(res.status).toBe(200);
    const preview=await res.json(),file=join(dir,'user/preferences/instructions.md');
    expect(readFileSync(file,'utf8')).not.toContain('两句结论');
    app.store.messages.append({id:task.id+'-preview',botId:'ceo',taskId:task.id,role:'bot',kind:'text',content:preview.impact+' '+preview.proposed+' '+preview.confirmation,createdAt:at});
    app.store.tasks.finish(task.id,'done',at);
    await app.orchestrator.submitMessage('ceo',preview.confirmation);
    await vi.waitFor(()=>expect(readFileSync(file,'utf8')).toContain('P1 本人对话二次确认'));
    expect(readFileSync(join(dir,'user/user-index.md'),'utf8')).toContain('先给两句结论');
  }finally{app.sse.closeAll();await new Promise<void>(r=>app.server.close(()=>r()));await app.close();rmSync(dir,{recursive:true,force:true});}
});

it('reuses a live archive, sends changed files, and refreshes after resume or context pressure',async()=>{
  const dir=temp(),driver:HarnessDriver=new FakeDriver();
  const prompts:string[]=[];
  let live=false,used=100,size=10000;
  let reply="收到。";
  driver.ensureSession=async(_bot,_task,options)=>{
    if(live)options?.onLiveSession?.();
    return 'same-session-id';
  };
  driver.prompt=async(_bot,_session,prompt,sink)=>{
    prompts.push(prompt);
    sink({type:'usage',used,size});
    sink({type:'message',text:reply});
    return {stopReason:'end_turn'};
  };
  const app=createApp({config:config(dir),driver,startSchedulers:false});
  const ask=async()=>{
    await app.orchestrator.submitMessage('ceo','继续这个问题');
    await vi.waitFor(()=>expect(app.store.tasks.latestForBot('ceo')?.status).toBe('done'));
    return prompts.at(-1)!;
  };
  try{
    expect(await ask()).toContain('attributes/values.json');
    live=true;
    expect(await ask()).toBe('继续这个问题');
    writeFileSync(join(dir,'user/recent-memory.md'),'新近期事项');
    const changed=await ask();
    expect(changed).toContain('新近期事项');
    expect(changed).not.toContain('attributes/values.json');
    expect(changed).not.toContain('user-index.md');
    live=false;
    expect(await ask()).toContain('attributes/values.json');
    live=true;
    used=6000;
    await ask();
    expect(await ask()).toContain('attributes/values.json');
    used=100;
    await ask();
    reply="需要重新加载客户档案：recent-memory.md";
    await ask();
    reply="收到。";
    expect(await ask()).toContain("attributes/values.json");
    used=0;
    await ask();
    expect(await ask()).toContain('attributes/values.json');
  }finally{await app.close();rmSync(dir,{recursive:true,force:true});}
});
