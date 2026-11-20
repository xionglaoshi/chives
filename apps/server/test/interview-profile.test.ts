import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {it,expect,vi} from 'vitest';
import {createApp} from '../src/app.js';
import {FakeDriver} from '../src/harness/fake.js';
import {DEFAULT_MODEL_PROVIDER,ModelProviderStore} from '../src/settings/model-provider.js';
import {profilePath,interview,interviewAnswers,validProfileFile,evaluationInput,reportView} from '../src/settings/interview-profile.js';
import {eligibleStyles,legacyInvestmentStyle} from '../src/settings/investment-style.js';
import {listen,closeServer,testConfig,repoRoot,waitFor} from './support.js';

function opening(people:{name:string}[]){
 return '您的投资风格像是'+people.slice(0,3).map(p=>p.name).join('、')+'三人的结合体。您愿意先核对一项结论背后的证据，再决定自己的下一步。把每次判断的依据记下来，日后回头检验，这种耐心有潜力成为您做独立研究的长处。';
}

it('persists the same revised profile for the report, continuing chats and every specialist',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'chives-interview-')),driver=new FakeDriver();
 const app=createApp({config:{...testConfig(dir),botsDir:join(repoRoot,'bots')},driver});
 const base=await listen(app.server),original=globalThis.fetch;
 const prompt=vi.spyOn(driver,'prompt');
 new ModelProviderStore(app.store,dir).write({...DEFAULT_MODEL_PROVIDER,baseURL:'http://profile-model.test'},'synthetic');
 let fail=false;
 vi.stubGlobal('fetch',async(url:Parameters<typeof fetch>[0],opts?:RequestInit)=>{
  if(!String(url).startsWith('http://profile-model.test'))return original(url,opts);
  if(fail)return new Response('',{status:503});
  const body=JSON.parse(String(opts?.body)),input=JSON.parse(body.messages[1].content);
  expect(body.messages[0].content).toContain('投资人物卡');
  const value={styleAssessment:{code:'unclear',sources:[]},overview:'您提到，希望先看证据，再决定采取什么行动。'.repeat(12),traits:{goal:'稳步积累',style:'核对证据',risk:'待了解',research:'经营',communication:'简洁'},encouragement:opening(input.投资人物卡),
   matches:input.投资人物卡.slice(0,3).map((p:{id:string})=>({id:p.id,reason:'您注重买入方法',source:'57'})),
   cardReadings:Object.fromEntries(input.cards.map((c:{id:string})=>[c.id,'您可以用这些回答和以后的实际记录做对照。']))};
  return Response.json({choices:[{message:{content:JSON.stringify(value)}}]});
 });
 const desk=async(data?:object)=>{const response=await fetch(base+'/api/settings/desk/assessment',{method:data?'POST':'GET',headers:{'X-Chives-Kernel-Manager':'local','Content-Type':'application/json'},...(data?{body:JSON.stringify(data)}:{})});return {status:response.status,body:await response.json()};};
 const chat=async(bot:string,text:string)=>{
  const res=await fetch(base+'/api/bots/'+bot+'/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
  expect(res.status).toBe(202);const {taskId}=await res.json();await waitFor(()=>app.store.tasks.get(taskId)?.status==='done');
  return app.store.messages.listByTask(taskId).map(m=>m.content).join('\n');
 };
 try{
  expect((await desk()).body.questions).toHaveLength(100);
  expect(interview.filter(q=>q.initial)).toHaveLength(30);
  expect(interviewAnswers.safeParse({'11':{allocation:Array(11).fill(0)}}).success).toBe(false);
  expect(interviewAnswers.safeParse({'03':{choices:[0,1]}}).success).toBe(false);
  const form={version:3,mode:'questionnaire',revision:null,scope:'personal',answers:{'57':{choice:0},'51':{choice:0}}};
  const first=await desk(form);expect(first.status).toBe(200);expect(first.body.result.report.match.people).toHaveLength(3);
  const read=()=>readFileSync(join(dir,profilePath),'utf8');
  const saved=JSON.parse(read());
  expect(first.body.result.report.match.reason).toBe(saved.summary.encouragement);
  expect(saved.investmentStyle).toBe('unclear');
  expect(first.body.result.report.investmentStyle).toBe('无明确风格');
  expect(validProfileFile(JSON.stringify({...saved,investmentStyle:'aggressive'}))).toBe(false);
  saved.summary.encouragement='您愿意核对自己的判断。';
  expect(validProfileFile(JSON.stringify(saved))).toBe(true);
  const oldMatch=reportView(saved).report.match;
  expect(oldMatch.reason).toContain(saved.summary.encouragement);
  expect(oldMatch.people.every(person=>oldMatch.reason.includes(person.name))).toBe(true);
  delete saved.investmentStyle;delete saved.summary.styleAssessment;
  expect(validProfileFile(JSON.stringify(saved))).toBe(true);
  expect(validProfileFile(read())).toBe(true);expect(JSON.parse(read()).cards).toHaveLength(32);
  const notice=await chat('expert','我以后首选宽基指数基金。');
  const code=/确认更新画像 ([0-9a-f]{8})/.exec(notice)?.[1];expect(code).toBeTruthy();
  expect(JSON.parse(read()).answers['57'].choice).toBe(0);
  expect(await chat('expert','确认更新画像 '+code)).toContain('您的本地画像已经更新');
  expect(JSON.parse(read()).corrections[0].previous['57'].choice).toBe(0);
  const updated=(await desk()).body.result;expect(updated.answers['57'].choice).toBe(2);expect(updated.updated).not.toBe(first.body.result.updated);
  for(const bot of app.registry.list()){
   await chat(bot.id,'我的指数基金偏好适合怎样研究？');
   const last=prompt.mock.calls.at(-1)!;expect(last[0].id).toBe(bot.id);expect(last[2]).toContain('investmentStyle');expect(last[2]).toContain('买覆盖多个行业的宽基指数基金');
  }
  fail=true;const before=read();
  expect((await desk({version:3,mode:'supplement',revision:updated.updated,materials:[{name:'test',text:'虚构测试资料'}]})).status).toBe(502);
  expect(read()).toBe(before);expect((await desk(form)).status).toBe(409);
 }finally{vi.unstubAllGlobals();app.sse.closeAll();await closeServer(app.server);await app.close();rmSync(dir,{recursive:true,force:true});}
});

it('resumes the file draft, submits the three evidence sources, and returns all cards without inventing a peer rank',async()=>{
 const dir=mkdtempSync(join(tmpdir(),'chives-exam-'));
 const app=createApp({config:testConfig(dir),driver:new FakeDriver()});
 const base=await listen(app.server),original=globalThis.fetch;
 const call=async(path:string,body?:unknown)=>{
  const r=await fetch(base+'/api/settings/desk/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Chives-Kernel-Manager':'local'},...(body===undefined?{}:{body:JSON.stringify(body)})});
  return {status:r.status,value:await r.json()};
 };
 new ModelProviderStore(app.store,dir).write({...DEFAULT_MODEL_PROVIDER,baseURL:'http://exam-model.test'},'synthetic');
 vi.stubGlobal('fetch',async(url:Parameters<typeof fetch>[0],opts?:RequestInit)=>{
  if(!String(url).startsWith('http://exam-model.test'))return original(url,opts);
  const messages=JSON.parse(String(opts?.body)).messages,input=JSON.parse(messages[1].content);
  expect(messages[0].content).toContain('写回与展示');
  expect(input.selfDescription).toEqual({id:'S1',text:'我习惯复核经营现金流。'});
  expect(input.materials[0].text).toContain('账期');
  expect(input.evidence.find((e:{id:string})=>e.id==='01').note).toBe('我想攒一笔养老钱。');
  const value={styleAssessment:{code:'unclear',sources:[]},overview:'您愿意看现金流，核对账期是您研究经营风险的方法。'.repeat(8),traits:{goal:'养老',style:'看经营',risk:'待核对',research:'回款',communication:'直接'},encouragement:opening(input.投资人物卡),matches:input.投资人物卡.slice(0,3).map((p:{id:string})=>({id:p.id,source:'S1',reason:'您看重现金流'})),cardReadings:Object.fromEntries(input.cards.map((c:{id:string})=>[c.id,'您的回答支持这个判断。']))};
  return Response.json({choices:[{message:{content:JSON.stringify(value)}}]});
 });
 try{
  const start=(await call('interview')).value;
  const partial={...start.draft,index:1,answers:{'01':{note:'我想攒一笔养老钱。'}}};
  const saved=(await call('interview-draft',partial)).value;
  expect((await call('interview-draft',partial)).status).toBe(409);
  expect((await call('interview-submit',saved)).status).toBe(400);
  expect(JSON.parse(readFileSync(join(dir,'profile/interview-draft.json'),'utf8')).index).toBe(1);
  expect((await call('interview')).value.draft.answers).toEqual(partial.answers);
  const answers=JSON.parse(readFileSync(join(repoRoot,'presets/style-assessment/example100.json'),'utf8')).answers;
  answers['01']=partial.answers['01'];
  const final=await call('interview-draft',{...partial,...saved,index:100,answers,selfDescription:'我习惯复核经营现金流。',materials:[{name:'记录.txt',text:'客户账期延长。'}]});
  const result=await call('interview-submit',final.value);
  expect(result.status).toBe(200);
  const cards=result.value.result.report.styleCards;
  expect(cards.items).toHaveLength(32);expect(cards.items.slice(0,cards.featured.length).map((c:{id:string})=>c.id)).toEqual(cards.featured);
  expect(cards.items.find((c:{id:string})=>c.id==='C02').position.kind).toBe('scale');
  expect(cards.items.find((c:{id:string})=>c.id==='C02').position.comparison).toBeNull();
  const again=(await call('interview')).value;
  expect(again.draft.index).toBe(0);expect(again.draft.answers).toEqual(answers);
  expect(again.previousMaterials).toContain('记录.txt');expect(again.draft.selfDescription).toContain('现金流');
  expect(validProfileFile(readFileSync(join(dir,profilePath),'utf8'))).toBe(true);
 }finally{vi.unstubAllGlobals();app.sse.closeAll();await closeServer(app.server);await app.close();rmSync(dir,{recursive:true,force:true});}
});

it('separates the investment objective from the risk grade when reading historical answers',()=>{
 const classify=(goal:number,lottery:number,grade:number,willingness:number,asset=3)=>
  legacyInvestmentStyle({'01':{choice:goal},'09':{choice:0},'27':{choice:lottery},'92':{choice:asset}},{grade,willingness});
 expect(classify(4,3,5,100)).toBe('aggressive');
 expect(classify(4,3,1,100)).toBe('unclear');
 expect(classify(1,2,3,55)).toBe('balanced');
 expect(classify(0,1,5,85)).toBe('steady');
 expect(classify(0,0,1,0,5)).toBe('very_conservative');
 expect(classify(0,0,1,0,0)).toBe('steady');
 expect(eligibleStyles({grade:null,willingness:100})).toEqual(['unclear']);
});

it('checks a model label against the risk boundary and the available evidence before saving',()=>{
 const sample=JSON.parse(readFileSync(join(repoRoot,'presets/style-assessment/example100.json'),'utf8'));
 const input=evaluationInput(sample.answers,[],'personal','我希望保值。');
 expect(input.schema.safeParse({...sample.summary,styleAssessment:{code:'steady',sources:['01']},encouragement:'您值得肯定。'}).success).toBe(false);
 const accepts=(code:string,sources:string[])=>input.schema.safeParse({...sample.summary,styleAssessment:{code,sources}}).success;
 expect(accepts('steady',['01','S1'])).toBe(true);
 expect(accepts('aggressive',['01'])).toBe(false);
 expect(accepts('very_conservative',['01','26','27'])).toBe(false);
 const withPreference=evaluationInput(sample.answers,[],'personal','我希望把结余买成货币基金。');
 expect(withPreference.schema.safeParse({...sample.summary,styleAssessment:{code:'very_conservative',sources:['S1','26']}}).success).toBe(true);
 expect(accepts('steady',['M2'])).toBe(false);
 expect(accepts('steady',[])).toBe(false);
 expect(accepts('unclear',[])).toBe(true);
});
