import {createHash,randomUUID} from 'node:crypto';
import {existsSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {z} from 'zod';
import {AppError} from '../errors.js';
import {writePrivateJson} from './interview-profile.js';
import {CustomerReviewer,readJson,type Evidence,type ReviewJob} from './customer-review.js';

type Question={id:string;field:string;chapter:string;title:string;why:string;options:string[];type:'single'};
const answer=z.object({choice:z.number().int().nonnegative().optional(),note:z.string().trim().max(1500).optional()}).strict();
const materials=z.array(z.object({name:z.string().trim().min(1).max(160),text:z.string().max(12000)})).max(8);
const draftSchema=z.object({scope:z.literal('personal'),index:z.number().int().nonnegative(),answers:z.record(z.string(),answer),
  selfDescription:z.string().max(8000),materials,revision:z.string().nullable(),profileRevision:z.string().nullable()});
type Draft=z.infer<typeof draftSchema>;
type Document={survey:'ceo-interview.v1';questions:(Question&{answer:z.infer<typeof answer>;selected:string|null})[];selfDescription:string;materials:Draft['materials']};
type Finding={id:string;label:string;value:unknown;reason:string;refs:string[];status:string};
type Result={version:4;revision:string;updated:string;overview:string;document:Document;findings:Finding[];recent:{text:string}[];preferences:{text:string}[]};

export class CustomerInterview {
  readonly questions:Question[];
  private pending=new Map<string,Promise<unknown>>();
  private path:string;
  private resultPath:string;
  constructor(private reviewer:CustomerReviewer,private legacyRevision:()=>string|null,private allowed:()=>boolean){
    this.questions=readJson(join(reviewer.repo,'presets/style-assessment/customer-interview.json'));
    this.path=join(reviewer.dir,'profile/customer-interview-draft.json');
    this.resultPath=join(reviewer.dir,'user/reviews/interview-result.json');
  }
  result(){return existsSync(this.resultPath)?readJson<Result>(this.resultPath):null;}
  view(){
    const r=this.result(); if(!r)return null;
    return {version:4,updated:r.updated,overview:r.overview,findings:r.findings,preferences:r.preferences,recent:r.recent,
      answered:r.document.questions.length,materials:r.document.materials.map(m=>m.name)};
  }
  questionnaire(){
    const result=this.result(),revision=result?.updated??this.legacyRevision();
    const draft:Draft=existsSync(this.path)?draftSchema.parse(readJson(this.path)):{scope:'personal',index:0,
      answers:result?Object.fromEntries(result.document.questions.map(q=>[q.id,q.answer])):{},
      materials:[],selfDescription:result?.document.selfDescription??'',revision:null,profileRevision:revision};
    return {questions:this.questions,currentRevision:revision,draft,previousMaterials:result?.document.materials.map(m=>m.name)??[]};
  }
  save(body:unknown){
    const next=draftSchema.parse(body),current=this.questionnaire();
    if(next.revision!==current.draft.revision||next.profileRevision!==current.currentRevision)throw new AppError(409,'stale','问卷或用户画像已更新，请重新打开核对。');
    if(next.index>this.questions.length)throw new AppError(400,'invalid_page','无效页码');
    for(const [key,a] of Object.entries(next.answers)){
      const q=this.questions.find(q=>q.id===key);
      if(!q||(a.choice===undefined?!a.note:a.choice>=q.options.length))throw new AppError(400,'invalid_answer','无效的访谈题号或选项。');
    }
    const revision=randomUUID();writePrivateJson(this.path,{...next,revision});return {revision};
  }
  async submit(revision:unknown,addition?:unknown){
    if(!this.allowed())throw new AppError(403,'archive_permissions','请在权限设置中允许读取用户数据库和写入记忆后再提交。');
    const q=this.questionnaire(),previous=this.result();
    const extra=addition===undefined?[]:materials.min(1).parse(addition);
    const supplement=addition!==undefined;
    const completed=revision && previous?.revision==='intake-'+revision;
    if(completed&&!supplement)return this.view();
    if(typeof revision!=='string'||revision!==(supplement?previous?.updated:q.draft.revision)||(!supplement&&q.currentRevision!==q.draft.profileRevision))
      throw new AppError(409,'stale','正式画像或草稿已更新，请重新打开。');
    const source=supplement?'intake-'+createHash('sha256').update(revision+JSON.stringify(extra)).digest('hex').slice(0,40):'intake-'+revision;
    const existing=this.pending.get(source);if(existing)return existing;
    const run=async()=>{
      const incoming=supplement?extra:q.draft.materials;
      const combined=materials.parse([...(previous?.document.materials??[]).filter(m=>!incoming.some(x=>x.name===m.name)),...incoming]);
      const document:Document=supplement?{...previous!.document,materials:combined}:{survey:'ceo-interview.v1',selfDescription:q.draft.selfDescription,materials:combined,
        questions:this.questions.map(item=>{
          const a=q.draft.answers[item.id];
          if(!a||(a.choice===undefined&&!a.note))throw new AppError(400,'incomplete','请完成「'+item.title+'」，或选择暂不适用。');
          return {...item,answer:a,selected:a.choice===undefined?null:item.options[a.choice]!};
        })};
      const evidence:Evidence=Object.fromEntries(document.questions.map(({id,title,selected,answer})=>[id,{title,selected,note:answer.note??''}]));
      if(document.selfDescription)evidence.S1={text:document.selfDescription};
      document.materials.forEach((m,i)=>{evidence['M'+(i+1)]=m;});
      const plan=join(this.reviewer.dir,'user-archive-state',source+'-review.json');
      let job:ReviewJob;
      if(existsSync(plan))job=readJson(plan);
      else{
        const review=await this.reviewer.review('intake',document,evidence);
        job={id:source,kind:'intake',preset:this.reviewer.preset('intake'),at:new Date().toISOString(),document,evidence,review};
        writePrivateJson(plan,job);
      }
      const latest=this.questionnaire();
      if(!this.allowed()||latest.currentRevision!==q.currentRevision||(!supplement&&latest.draft.revision!==revision))
        throw new AppError(409,'stale','整理期间授权、草稿或画像已变化，请核对后重试。');
      this.reviewer.publish(job);
      if(!supplement)rmSync(this.path,{force:true});
      return this.view();
    };
    this.pending.set(source,run());
    try{return await this.pending.get(source);}finally{this.pending.delete(source);}
  }
}
