import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { z } from 'zod';
import { AppError } from '../errors.js';

export type ReviewTurn = (prompt:string)=>Promise<string>;
export type Evidence = Record<string,Record<string,unknown>>;
const references=z.array(z.string().min(1)).min(1).max(20);
const text=z.string().trim().min(1).max(400);
const note=z.object({text,refs:references});
const field=z.object({id:z.string().regex(/^A\d{2}$/),value:z.union([z.null(),z.boolean(),z.number(),z.string(),z.array(z.string())]),refs:references,reason:text,verifiedBehavior:z.boolean().optional(),explicitFact:z.boolean().optional()});
const theme=note.extend({category:z.enum(['关注的证券','研究委托','投资观点','投资复盘']),title:z.string().regex(/^[\p{L}\p{N}（）() ·_-]{1,48}$/u)});
const output=z.object({overview:z.string().trim().min(1).max(1500),attributes:z.array(field).max(37),recent:z.array(note).max(12),
  preferences:z.array(note).max(8),longTerm:z.array(theme).max(12),
  staff:z.array(note.extend({bot:z.string(),quote:z.string().min(2).max(220),title:z.string().min(1).max(70)})).max(20).default([]),
  resolved:z.array(z.string()).max(40).default([]),
  retire:z.array(z.object({bot:z.string(),slug:z.string(),reason:text})).max(40).default([])});
export type Review = z.infer<typeof output>;
export interface ReviewJob {id:string;kind:'intake'|'daily';at:string;evidence:Evidence;document?:unknown;preset?:string;review:Review}

export function readJson<T>(path:string):T {return JSON.parse(readFileSync(path,'utf8')) as T;}
export class CustomerReviewer {
  constructor(readonly dir:string,readonly repo:string,private turn:ReviewTurn) {}
  dictionary(){
    const dir=join(this.repo,'presets/user-attributes');
    return readdirSync(dir).filter(name=>/^A\d\d-.*\.json$/.test(name)).sort().map(name=>readJson<{id:string;key:string;label:string;scale:string;domain:unknown;review_when:string}>(join(dir,name)));
  }
  preset(kind:'intake'|'daily'){
    return readFileSync(join(this.repo,'presets/style-assessment',kind==='intake'?'总经理访谈归档.md':'总经理每日整理.md'),'utf8');
  }
  async review(kind:'intake'|'daily',document:unknown,evidence:Evidence):Promise<Review>{
    const preset=this.preset(kind);
    const dictionary=this.dictionary();
    const prompt=preset+'\n资料包（JSON）\n'+JSON.stringify({asOf:new Date().toISOString(),dictionary,document,evidence});
    let feedback='';
    for(let attempt=0;attempt<2;attempt++){
      const response=await this.turn(prompt+feedback);
      try {
        const result=output.parse(JSON.parse(response.trim().replace(/^```(?:json)?\s*/i,'').replace(/\s*```$/,'')));
        const ids=new Set(result.attributes.map(row=>row.id));
        if(ids.size!==result.attributes.length||dictionary.length!==37||dictionary.some(f=>kind==='intake'&&!ids.has(f.id))) throw Error('请为 A01 至 A37 各给一个结果。');
        for(const item of [...result.attributes,...result.recent,...result.preferences,...result.longTerm,...result.staff]){
          if(item.refs.some(ref=>!Object.hasOwn(evidence,ref))) throw Error('引用必须使用资料包中的来源编号。');
        }
        return result;
      }catch(e){feedback='\n上次结构未通过：'+(e instanceof Error?e.message.slice(0,650):'字段错误')+'。请从同一份资料重新返回完整 JSON。';}
    }
    throw new AppError(422,'review_incomplete','总经理的整理结果尚未通过核验，资料已保留，可以重试。');
  }
  publish(job:ReviewJob){
    const local=join(this.repo,'.venv/bin/python');
    const python=process.env.CALENDAR_PYTHON??(existsSync(local)?local:'python3');
    try{return JSON.parse(execFileSync(python,[join(this.repo,'scripts/customer_archive.py'),this.dir],{
      input:JSON.stringify(job),encoding:'utf8',timeout:30000,stdio:['pipe','pipe','pipe']}));}
    catch(e){const err=e as {stderr?:string};throw new AppError(409,'publication_failed','档案写入未完成：'+(String(err.stderr??'').split('\n').filter(Boolean).at(-1)??'请重试').slice(0,160));}
  }
}
