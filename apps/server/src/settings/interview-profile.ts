import {readFileSync,writeFileSync,renameSync,mkdirSync,existsSync,rmSync} from 'node:fs';
import {basename,dirname,join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {z} from 'zod';
import {AppError} from '../errors.js';
import {cardPosition} from './card-position.js';
import {styleAssessment,styleLabels,eligibleStyles,legacyInvestmentStyle} from './investment-style.js';
import type {Investor} from './style-report.js';

function asset(path:string){return readFileSync(new URL('../../../../presets/'+path,import.meta.url),'utf8');}
export interface Question {id:string;title:string;options:string[];type:'single'|'multi'|'allocation';param:string;why:string;initial:boolean}
interface Definition {id:string;title:string;required:string[];optional:string[];rule:string;action:string}
export const interview:Question[]=JSON.parse(asset('style-assessment/interview100.json'));
const definitions:Definition[]=JSON.parse(asset('style-assessment/cards.json'));
const investors:Investor[]=JSON.parse(asset('investor-styles/catalog.json')).people;
export const rubric=asset('style-assessment/评价依据.md');
const byId=new Map(interview.map(q=>[q.id,q]));
const numeric=z.number().int().nonnegative();
const response=z.object({choice:numeric.optional(),choices:z.array(numeric).min(1).optional(),allocation:z.array(numeric.max(100)).length(11).optional(),note:z.string().trim().max(1500).optional(),skipped:z.boolean().optional()}).strict();
export const interviewAnswers=z.record(z.string(),response).superRefine((all,ctx)=>{
 for(const [id,a] of Object.entries(all)){
  const q=byId.get(id); let ok=false;
  if(q){
   const kinds=Number(a.choice!==undefined)+Number(!!a.choices)+Number(!!a.allocation)+Number(!!a.skipped);
   if(kinds===0&&a.note?.trim())ok=true;
   if(kinds===1){
    if(a.skipped)ok=!a.note;
    else if(q.type==='allocation')ok=a.allocation?.reduce((x,y)=>x+y,0)===100;
    else if(q.type==='single')ok=a.choice!==undefined&&a.choice<q.options.length;
    else if(a.choices){
     const choices=a.choices;
     const exclusive=choices.some(i=>/^(暂时没有其他|都能比较|说不准|这些收入和资产没有|不确定|开通过相关权限|以上都|暂时没有特别|从未直接|平时不用|从没用)/.test(q.options[i]??''));
     ok=new Set(choices).size===choices.length&&choices.every(i=>i<q.options.length)&&(!exclusive||choices.length===1)&&(!['42','84'].includes(id)||choices.length<=3);
    }
   }
  }
  if(!ok)ctx.addIssue({code:'custom',path:[id],message:'请核对第 '+id+' 题的选项或资产比例'});
 }
});
export type InterviewAnswers=z.infer<typeof interviewAnswers>;
export const materialsSchema=z.array(z.object({name:z.string().trim().min(1).max(160),text:z.string().trim().min(1).max(12000)})).max(8).refine(ms=>ms.reduce((n,m)=>n+m.text.length,0)<=40000);
type Materials=z.infer<typeof materialsSchema>;
export function factsFor(answers:InterviewAnswers){
 const facts:Record<string,string|string[]|Record<string,number>>={};
 for(const q of interview){
  const a=answers[q.id];if(!a||a.skipped)continue;
  if(a.allocation)facts[q.param]=Object.fromEntries(q.options.flatMap((v,i)=>a.allocation![i]?[[v,a.allocation![i]]]:[]));
  else if(a.choices)facts[q.param]=a.choices.map(i=>q.options[i]!);
  else if(a.choice!==undefined)facts[q.param]=q.options[a.choice]!;
  else if(a.note)facts[q.param]=a.note;
 }
 return facts;
}
function derived(answers:InterviewAnswers){
 const ix=(id:string)=>answers[id]?.choice??-1;
 const present=(id:string)=>{const a=answers[id];return a?.choice!==undefined||!!a?.choices||!!a?.allocation;};
 const kIds=['04','21','22','23','24','25'],wIds=['26','27','28','29'];
 const scale=(ids:string[])=>ids.every(present)?Math.round(ids.reduce((n,id)=>n+ix(id),0)*100/(3*ids.length)*100)/100:null;
 const k=scale(kIds),w=scale(wIds),conflict=ix('04')===3&&ix('25')===0;
 const grade=k===null||w===null||conflict?null:Math.min(5,1+Math.floor(Math.min(k,w)/20),ix('23')===0?1:5,['04','21','24'].some(id=>ix(id)===0)?2:5);
 const overlap=answers['20']?.choices??[];
 const joint=ix('49')===0&&overlap.includes(2)&&overlap.some(v=>v===0||v===1);
 const codes:Record<number,string>={
  25:k===null||w===null?'unknown':w-k>=25?'willingness_ahead':k-w>=25?'capacity_ahead':'similar',
  26:({0:0,1:8,2:9} as Record<number,number>)[ix('19')]===ix('13')?'constrained_reduction':'allocation_intent',
  27:joint?'job_stock_overlap':overlap.includes(1)&&overlap.includes(3)?'private_business_overlap':'industry_exposure',
  28:['pause','sell_for_expenses','wait','draw_reserves','review'][ix('94')]??'unknown',
  29:ix('04')===3&&ix('36')>=0&&ix('36')<3?'long_funds_short_trade':'holding_comparison',
  30:ix('93')===0?'no_current_limit':ix('37')>ix('93')?'historical_band_higher':ix('37')===ix('93')?'same_band':'historical_band_lower',
  31:'cash_'+Number(ix('46')===1)+'_governance_'+Number(ix('47')===1),
  32:ix('56')===3&&ix('89')<=1?'backtest_time_limited':'research_workflow'
 };
 const groups=[[1,2,3,4,26,28],[5,6,7,8,25],[9,10,11,12],[13,14,15,16,29,30],[17,18,19,20,31,32],[21,22,23,24],[27]];
 const priority=[[2,3,4,25,28],[9,15,18,19,31],[17,26,27],[3,5,6,11,30],[8,14,15,16,21,22,23,24,29,30]];
 const review=[[3,26,27,30],[4,12,28],[5,6,7,8,25],[13,14,15,16,21,22,23,24,29,30],[17,18,19,20,27,31,32]];
 const goals=[[2,5,25],[9,11,29],[4,10,14],[17,20,32],[7,13,22],[8,23,24]];
 const cards=definitions.map((d,i)=>{
  const n=i+1,ids=[...d.required,...d.optional].filter(present);
  let state=d.required.every(present)?'ready':'missing';
  if(([8,9,13,16,22,23,29,30].includes(n)&&(ix('31')===0||answers['81']?.choices?.includes(4)))||(n===8&&ix('33')===0)||(n===16&&ix('60')===7)||(n===23&&ix('79')===4)||(n===28&&ix('15')===0)||(n===29&&ix('36')===5)||(n===30&&ix('37')===0))state='na';
  if(([2,25].includes(n)&&conflict)||(n===27&&((ix('49')===0&&overlap.length&&!joint)||(ix('49')>=2&&overlap.includes(2)&&overlap.some(v=>v<2))))||(n===4&&present('15')&&present('16')&&(ix('15')===0)!==(ix('16')===4)))state='clarify';
  const rare=n===25&&codes[n]!=='similar'||n===26&&codes[n]==='constrained_reduction'||n===27&&joint||n===28&&[1,3].includes(ix('94'))||n===29&&codes[n]==='long_funds_short_trade'||n===30&&codes[n]==='historical_band_higher'||n===31&&ix('45')>=2&&(ix('46')!==1||ix('47')!==1)||n===32&&codes[n]==='backtest_time_limited';
  const urgent=n===2&&(ix('04')===0||ix('25')===0)||n===25&&codes[n]==='willingness_ahead'&&(ix('23')===0||ix('24')===0)||n===27&&joint||n===28&&[1,3].includes(ix('94'))||n===23&&ix('79')===2;
  const h=urgent?3:n>=25||[2,3,4,5,8,15,21,23].includes(n)?2:1;
  const interest=priority[ix('95')]?.includes(n)||review[ix('100')]?.includes(n)?2:goals[ix('01')]?.includes(n)?1:0;
  const support=d.optional.some(present)?2:1;
  return {id:d.id,title:d.title,state,code:state==='ready'?(codes[n]??d.required.map(id=>id+'='+JSON.stringify(answers[id]?.choice??answers[id]?.choices??'allocation')).join(',')):state,ids,group:groups.findIndex(g=>g.includes(n)),importance:h,interest,score:4*h+3*interest+2*(rare?2:n>=25?1:0)+support};
 });
 const ranked=cards.filter(c=>c.state==='ready').sort((a,b)=>b.score-a.score||b.importance-a.importance||a.id.localeCompare(b.id));
 const featured:string[]=[],groupsUsed=new Map<number,number>();
 let interestSeen=false;
 while(featured.length<8){
  const rest=ranked.filter(c=>!featured.includes(c.id));if(!rest.length)break;
  let pool=rest.filter(c=>c.importance===3);
  if(!pool.length){
   pool=rest.filter(c=>(groupsUsed.get(c.group)??0)<2);
   if(!pool.length)pool=rest.filter(c=>(groupsUsed.get(c.group)??0)<3);
   if(!pool.length)pool=rest;
   if(!interestSeen&&pool.some(c=>c.interest===2))pool=pool.filter(c=>c.interest===2);
  }
  const adjusted=(c:typeof cards[number])=>c.score-2*(groupsUsed.get(c.group)??0);
  const pick=pool.sort((a,b)=>adjusted(b)-adjusted(a)||b.importance-a.importance||a.id.localeCompare(b.id))[0]!;
  featured.push(pick.id);groupsUsed.set(pick.group,(groupsUsed.get(pick.group)??0)+1);interestSeen||=pick.interest===2;
 }
 return {grade,capacity:k,willingness:w,conflict,cards,featured,ordered:ranked.map(c=>c.id)};
}
const short=z.string().trim().min(1).max(140);
const narrative=z.object({
 identityTags:z.array(z.string().trim().min(1).max(60)).max(4).optional(),
 preferenceRules:z.array(z.string().trim().min(1).max(100)).max(6).optional(),
 styleAssessment:styleAssessment.optional(),
 overview:z.string().min(100).max(1200),traits:z.object({goal:short,style:short,risk:short,research:short,communication:short}),
 encouragement:z.string().trim().min(1).max(350),matches:z.array(z.object({id:z.string(),reason:short,source:z.string()})).max(3),
 cardReadings:z.record(z.string(),z.string().trim().min(1).max(360))
});
export function evaluationInput(answers:InterviewAnswers,materials:Materials,scope:string,selfDescription='',confirmedPreferences:string[]=[],storedReport=false){
 const result=derived(answers),facts=factsFor(answers);
 const evidence=interview.filter(q=>q.param in facts).map(q=>({id:q.id,question:q.title,field:q.param,value:facts[q.param],note:answers[q.id]?.note}));
 const usable=new Set([...(selfDescription?['S1']:[]),...confirmedPreferences.map((_,i)=>'P'+(i+1)),...evidence.map(e=>e.id),...materials.map((_,i)=>'M'+(i+1))]);
 const canMatch=materials.length>0||['51','52','53','54','56','57','59','60','71','76','77','78'].some(id=>usable.has(id));
 const ready=result.cards.filter(c=>c.state==='ready');
 // Extreme labels need evidence of the investment preference as well as a risk score.
 const written=[
  ...evidence.map(e=>({id:e.id,text:e.note??''})),
  {id:'S1',text:selfDescription},...materials.map((m,i)=>({id:'M'+(i+1),text:m.text})),
  ...confirmedPreferences.map((text,i)=>({id:'P'+(i+1),text}))
 ];
 const preferenceSources={
  aggressive:[...(answers['01']?.choice===4?['01']:[]),...written.filter(e=>/极高回报|极高收益|极致.{0,4}(回报|收益)|高风险高(收益|回报)|翻倍|赚大钱|赚一大笔|收益最大化/.test(e.text)).map(e=>e.id)],
  very_conservative:[...([2,5].includes(answers['92']?.choice??-1)?['92']:[]),...written.filter(e=>/货币(市场)?基金|货基|存款|低波动|低风险理财|固收|固定收益|短债|国债|现金管理/.test(e.text)).map(e=>e.id)]
 };
 const allowedStyles=eligibleStyles(result).filter(code=>!(code==='aggressive'||code==='very_conservative')||preferenceSources[code].length>0);
 const schema=narrative.superRefine((s,ctx)=>{
  const style=s.styleAssessment;
  if(!style&&!storedReport)ctx.addIssue({code:'custom',message:'请返回 styleAssessment'});
  if(style&&(!allowedStyles.includes(style.code)||(style.code!=='unclear'&&!style.sources.length)||style.sources.some(id=>!usable.has(id))))
   ctx.addIssue({code:'custom',message:'投资风格与风险边界或引用依据不符'});
  if(style&&(style.code==='aggressive'||style.code==='very_conservative')&&!preferenceSources[style.code].some(id=>style.sources.includes(id)))
   ctx.addIssue({code:'custom',message:'极端风格须引用 preferenceSources 中体现当前主动偏好的一项来源'});
  const valid=s.matches.every(m=>investors.some(p=>p.id===m.id)&&usable.has(m.source));
  if(!valid||s.matches.length!==(canMatch?3:0)||new Set(s.matches.map(p=>p.id)).size!==s.matches.length)ctx.addIssue({code:'custom',message:'人物或依据不完整'});
  if(!storedReport&&valid&&s.matches.length===3){
   const intro=s.encouragement;
   if(intro.length<75||intro.length>150||/[\r\n]/u.test(intro)||!intro.includes('您')||
      !s.matches.every(m=>intro.includes(investors.find(p=>p.id===m.id)!.name)))
    ctx.addIssue({code:'custom',path:['encouragement'],message:'请用一个约100字的自然段，称呼「您」，写出三位所选人物在投资人物卡中的全名，结合具体习惯赞赏用户并说明潜力。'});
  }
  if(!s.overview.includes('您'))ctx.addIssue({code:'custom',message:'请面向本人解读'});
  if(Object.keys(s.cardReadings).length!==ready.length||ready.some(c=>!s.cardReadings[c.id]))ctx.addIssue({code:'custom',message:'卡片解读不完整'});
 });
 const input={scope,allowedStyles,styleLabels,preferenceSources,evidence,selfDescription:selfDescription?{id:'S1',text:selfDescription}:null,materials:materials.map((m,i)=>({id:'M'+(i+1),text:m.text})),risk:{grade:result.grade,capacity:result.capacity,willingness:result.willingness},cards:ready.map(c=>({id:c.id,title:c.title,code:c.code,sources:c.ids,rule:definitions.find(d=>d.id===c.id)!.rule})),人物数量:canMatch?3:0,投资人物卡:investors.map(p=>({id:p.id,name:p.name,style:p.style,bio:p.bio,signals:p.signals}))};
 return {result,facts,input,schema};
}
export function cardsForBot(p:Profile,ids:string[]){
 const selected=new Set(ids);
 return p.cards.filter(c=>!selected.size||selected.has(c.id)).map(c=>{
  const definition=definitions.find(d=>d.id===c.id)!;
  return {id:c.id,title:c.title,state:c.state,code:c.code,fields:c.ids.map(id=>byId.get(id)!.param),
   ...(c.state==='ready'?{action:definition.action,reading:p.summary.cardReadings[c.id]}:{})};
 });
}
export const profilePath='profile/investor.json';
export function makeProfile(answers:InterviewAnswers,materials:Materials,scope:string,updated:string,model:string,summary:z.infer<typeof narrative>,selfDescription?:string){
 const result=derived(answers),facts=factsFor(answers);
 return {...(selfDescription!==undefined?{selfDescription}:{}),version:3 as const,survey:'interview100.v2',updated,model,scope,answers,materials,facts,...result,investmentStyle:summary.styleAssessment?.code??legacyInvestmentStyle(answers,result),summary};
}
export type Correction={time:string;bot:string;reason:string;previous:InterviewAnswers;changes:InterviewAnswers};
export type Profile=ReturnType<typeof makeProfile>&{corrections?:Correction[];confirmedPreferences?:string[]};
export function validProfileFile(text:string){
 try{
  const p=JSON.parse(text);
  if(p.version!==3)return false;
  if(p.status==='unassessed')return Object.keys(p).length===2;
  if(!z.iso.datetime().safeParse(p.updated).success||!['personal','family'].includes(p.scope)||!interviewAnswers.safeParse(p.answers).success||!materialsSchema.safeParse(p.materials).success||typeof p.model!=='string')return false;
  if(p.selfDescription!==undefined&&!z.string().max(8000).safeParse(p.selfDescription).success)return false;
  const {schema}=evaluationInput(p.answers,p.materials,p.scope,p.selfDescription,p.confirmedPreferences??[],true);
  if(!schema.safeParse(p.summary).success)return false;
  const rebuilt=makeProfile(p.answers,p.materials,p.scope,p.updated,p.model,p.summary,p.selfDescription);
  return Object.entries(rebuilt).every(([k,v])=>(k==='investmentStyle'&&p[k]===undefined&&!p.summary.styleAssessment)||JSON.stringify(v)===JSON.stringify(p[k]))&&
   (!p.confirmedPreferences||z.array(z.string().max(500)).max(100).safeParse(p.confirmedPreferences).success)&&
   (!p.corrections||z.array(z.object({time:z.iso.datetime(),bot:z.string(),reason:z.string().max(500),previous:interviewAnswers,changes:interviewAnswers})).safeParse(p.corrections).success);
 }catch{return false;}
}
export function readProfile(dir:string):Profile|null{
 const path=join(dir,profilePath);
 if(!existsSync(path))return null;
 const record=JSON.parse(readFileSync(path,'utf8'));
 if(record.version===3&&record.status==='unassessed')return null;
 if(record.version!==3||!record.facts||!Array.isArray(record.cards)||!record.summary)throw new AppError(500,'invalid_profile','本地画像文件无法读取。');
 if(record.investmentStyle===undefined){
  record.investmentStyle=record.summary.styleAssessment?.code??legacyInvestmentStyle(record.answers,record);
  writeProfile(dir,record);
 }
 return record as Profile;
}
export function writeProfile(dir:string,profile:Profile|{version:3;status:'unassessed'}){
 writePrivateJson(join(dir,profilePath),profile);
}
export function writePrivateJson(path:string,profile:unknown){
 mkdirSync(dirname(path),{recursive:true,mode:0o700});
 const tmp=path+'.'+randomUUID();
 try{writeFileSync(tmp,JSON.stringify(profile),{mode:0o600,flag:'wx'});renameSync(tmp,path);}finally{rmSync(tmp,{force:true});}
}
export function reportView(p:Profile){
 const persons=p.summary.matches.map(m=>{
  const person=investors.find(i=>i.id===m.id)!;
  return {...person,portrait:(person.webReleaseEligible?'/api/':'/api/internal/')+'style-portraits/'+encodeURIComponent(basename(person.portrait))+'?v='+person.portraitSha256.slice(0,12),evidence:[m.source],difference:'',reason:m.reason};
 });
 const praise=p.summary.encouragement;
 const names=persons.map(person=>person.name);
 let introduction=praise;
 if(!names.length)introduction='目前的方法证据不足，可以补充选股经历。'+praise;
 else if(!names.every(name=>praise.includes(name))){
  // Earlier reports stored the model's praise separately from the three names.
  introduction='您的投资风格像是'+names.join('、')+'三人的结合体。'+praise;
 }
 const cardById=new Map(p.cards.map(c=>[c.id,c]));
 const order=[...new Set([...p.featured,...p.ordered,...p.cards.map(c=>c.id)])];
 const statusText:Record<string,string>={missing:'这项解读还需要更多相关答案。',na:'根据您的经历，这个情境暂不适用。',clarify:'相关答案还需要核对，暂缓判断。'};
 const items=order.map(id=>{
  const c=cardById.get(id)!;
  return {id,title:c.title,reading:p.summary.cardReadings[id]??statusText[c.state],position:cardPosition(p,id,byId,c.state==='ready')};
 });
 return {version:3,updated:p.updated,scope:p.scope,grade:p.grade,overview:p.summary.overview,model:p.model,summary:p.summary,answers:p.answers,materials:p.materials.map(m=>m.name),
 report:{investmentStyle:styleLabels[p.investmentStyle??legacyInvestmentStyle(p.answers,p)],answered:Object.keys(p.facts).length,risk:{grade:p.grade,flags:p.conflict?['用款时间的回答存在差异，请核实。']:[]},dimensions:[],match:{kind:'combined',reason:introduction,people:persons},
 styleCards:{featured:p.featured,items,clarify:p.cards.filter(c=>c.state==='clarify').map(c=>c.title)}}};
}

export function interviewExample(){return reportView(JSON.parse(asset('style-assessment/example100.json')) as Profile);}
