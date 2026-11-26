import {mkdtempSync,readFileSync,writeFileSync,rmSync,mkdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {it,expect} from 'vitest';
import {profilePath,interviewAnswers,validProfileFile,evaluationInput,reportView} from '../src/settings/interview-profile.js';
import {eligibleStyles,legacyInvestmentStyle} from '../src/settings/investment-style.js';
import {CustomerReviewer} from '../src/settings/customer-review.js';
import {CustomerInterview} from '../src/settings/customer-interview.js';
import {UserArchive} from '../src/settings/user-archive.js';
const repoRoot=fileURLToPath(new URL('../../../',import.meta.url));

it('keeps the previous report readable and opens a clean versioned interview',()=>{
 const dir=mkdtempSync(join(process.env.CHIVES_TEST_DIR??tmpdir(),'previous-assessment-'));
 try{
  const original=readFileSync(join(repoRoot,'presets/style-assessment/example100.json'),'utf8');
  mkdirSync(join(dir,'profile'));writeFileSync(join(dir,profilePath),original);
  const saved=JSON.parse(original);
  const prior=reportView(saved);expect(prior.report.match.people.length).toBeGreaterThan(0);
  expect(validProfileFile(original)).toBe(true);
  expect(interviewAnswers.safeParse({'11':{allocation:Array(11).fill(0)}}).success).toBe(false);
  const service=new CustomerInterview(new CustomerReviewer(dir,repoRoot,async()=>''),()=>saved.updated,()=>true);
  const start=service.questionnaire();expect(start.currentRevision).toBe(saved.updated);
  expect(start.questions).toHaveLength(78);expect(start.draft.answers).toEqual({});
  expect(readFileSync(join(dir,profilePath),'utf8')).toBe(original);
 }finally{rmSync(dir,{recursive:true,force:true});}
});

it('resumes the current draft, sends every question and source with the preset, and recovers a failed CEO submission',async()=>{
 const dir=mkdtempSync(join(process.env.CHIVES_TEST_DIR??tmpdir(),'customer-intake-'));
 try{
  new UserArchive(dir,repoRoot).initialize();
  let fail=true;
  const reviewer=new CustomerReviewer(dir,repoRoot,async prompt=>{
   if(fail)throw Error('测试离线');
   expect(prompt).toContain('user/recent-memory.md');expect(prompt).toContain('P0');
   const pkg=JSON.parse(prompt.split('资料包（JSON）\n').at(-1)!);
   expect(pkg.document.questions).toHaveLength(78);expect(pkg.evidence.S1.text).toContain('现金流');
   expect(pkg.evidence.M1.text).toContain('账期');expect(pkg.evidence['A23-1'].note).toBe('用于养老');
   expect(pkg.document.questions.every((q:{options:string[];why:string})=>q.options.length>1&&q.why)).toBe(true);
   return JSON.stringify({overview:'仍缺记录',attributes:reviewer.dictionary().map(f=>({id:f.id,reason:'请补近期实例',value:null,refs:[f.id+'-1',f.id+'-2']})),recent:[],preferences:[],longTerm:[]});
  });
  const service=new CustomerInterview(reviewer,()=>null,()=>true),start=service.questionnaire();
  const first={...start.draft,index:1,answers:{'A23-1':{note:'用于养老'}}};
  const partial=service.save(first);expect(()=>service.save(first)).toThrow();expect(service.questionnaire().draft.answers).toEqual(first.answers);
  await expect(service.submit(partial.revision)).rejects.toThrow();
  const answers={...Object.fromEntries(start.questions.map(q=>[q.id,{choice:0}])),...first.answers};
  const final=service.save({...first,...partial,index:78,answers,selfDescription:'关注现金流',materials:[{name:'笔记',text:'需要核对账期。'}]});
  await expect(service.submit(final.revision)).rejects.toThrow('测试离线');expect(service.result()).toBeNull();
  fail=false;await service.submit(final.revision);await service.submit(final.revision);
  expect(service.view()?.findings).toHaveLength(37);
  const retest=service.questionnaire();expect(retest.draft.index).toBe(0);expect(retest.draft.answers).toEqual(answers);
  expect(retest.previousMaterials).toEqual(['笔记']);
 }finally{rmSync(dir,{recursive:true,force:true});}
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
