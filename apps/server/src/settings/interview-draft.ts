import {existsSync,readFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {z} from 'zod';
import {AppError} from '../errors.js';
import {interview,interviewAnswers,writePrivateJson} from './interview-profile.js';
import type {Profile} from './interview-profile.js';

export const draftPath='profile/interview-draft.json';
const draftFields=z.object({
  scope:z.enum(['personal','family']), index:z.number().int().min(0).max(interview.length),
  answers:interviewAnswers, selfDescription:z.string().max(8000),
  materials:z.array(z.object({name:z.string().min(1).max(160),text:z.string().max(12000)})).max(8),
});
const snapshot=draftFields.extend({revision:z.string().nullable(),profileRevision:z.string().nullable()});
export type Draft=z.infer<typeof snapshot>;

export class InterviewDraft {
  private path:string;
  constructor(dir:string){this.path=join(dir,draftPath);}
  read(profile:Profile|null,profileRevision:string|null):Draft {
    if(existsSync(this.path))return snapshot.parse(JSON.parse(readFileSync(this.path,'utf8')));
    return {revision:null,profileRevision,index:0,scope:profile?.scope==='family'?'family':'personal',answers:profile?.answers??{},
      selfDescription:profile?.selfDescription??'',materials:[]};
  }
  save(body:unknown,profile:Profile|null,profileRevision:string|null){
    const next=snapshot.parse(body),current=this.read(profile,profileRevision);
    if(next.revision!==current.revision)throw new AppError(409,'draft_changed','另一窗口已保存更新，请重新打开问卷读取最新进度。');
    if(next.profileRevision!==profileRevision)throw new AppError(409,'profile_changed','正式画像有了更新，请重新打开问卷，核对后继续。');
    const revision=randomUUID();
    writePrivateJson(this.path,{...next,revision});
    return {revision};
  }
  assertCurrent(revision:unknown){
    if(!revision||!existsSync(this.path)||JSON.parse(readFileSync(this.path,'utf8')).revision!==revision)
      throw new AppError(409,'draft_changed','答卷已有更新，请重新打开后提交。');
  }
  clear(){rmSync(this.path,{force:true});}
}
