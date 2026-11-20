import {useEffect,useState} from 'react';
import type {AskExpert} from './useExpertAttachment';
import {desk} from './deskApi';

import type {InterviewQuestion,InterviewAnswers as Answers} from './InterviewForm';
import {StyleReport,type Report} from './StyleReport';
export type Excerpt={name:string;text:string;truncated:boolean};
const labels={philosophy:'投资理念',style:'决策风格',industries:'偏好行业',analogy:'与哪位投资人相似',riskBehavior:'实际风险偏好',evidence:'判断依据'};
type Insight=keyof typeof labels;
type View={
  questions:InterviewQuestion[];
  result:{scope?:string;version:number;updated:string;grade:number|null;summary:Record<Insight,string>;overview?:string;report?:Report;model:string;answers:Answers;materials:string[]}|null;
  sample?:{report:Report;overview:string};
};
export async function preview(file:File){
  if(file.size>4*1024*1024)throw Error(file.name+' 超过 4 MB。');
  const encoded=await new Promise<string>((ok,fail)=>{
    const reader=new FileReader();reader.onload=()=>ok(String(reader.result).split(',')[1]??'');
    reader.onerror=()=>fail(Error('无法读取 '+file.name));reader.readAsDataURL(file);
  });
  return desk<Excerpt>('assessment-preview','POST',{name:file.name,base64:encoded});
}
export function StyleAssessment({interviewReturn='settings',onAskExpert}:{interviewReturn?:'settings'|'workspace';onAskExpert:AskExpert}){
  const [data,set]=useState<View|null>(null),[mode,open]=useState<'supplement'|null>(null);
  const [files,attach]=useState<Excerpt[]>([]);
  const [pending,busy]=useState(''),[error,err]=useState(''),[notice,notify]=useState('');
  useEffect(()=>{let live=true;const refresh=()=>desk<View>('assessment').then(v=>{if(live)set(v);}).catch(e=>{if(live)err(e.message);});void refresh();window.addEventListener('focus',refresh);return()=>{live=false;window.removeEventListener('focus',refresh);};},[]);
  const result=data?.result;
  function begin(next:'questionnaire'|'supplement'){if(next==='questionnaire'){const url=new URL(window.location.href);url.searchParams.set('interview','1');if(interviewReturn==='workspace')url.searchParams.set('from','workspace');url.hash='';window.open(url.toString(),'chives-style-interview');return;}attach([]);err('');notify('');open(next);}
  async function select(list:File[]){
    if(!list.length)return;
    busy('正在本机读取资料…');err('');let draft=[...files];
    try{
      for(const file of list){
        const entry=await preview(file);
        draft=[...draft.filter(x=>x.name!==entry.name),entry];attach(draft);
      }
    }catch(e){err(e instanceof Error?e.message:'资料读取失败');}finally{busy('');}
  }
  async function submit(answers:Answers={},scope="personal"){
    busy('模型正在评估…');err('');notify('');
    try{
      const next=await desk<View>('assessment','POST',{version:3,mode,scope,revision:result?.updated??null,answers,
        materials:files.map(({name,text})=>({name,text}))});
      set(next);open(null);attach([]);notify('用户画像已更新。');return true;
    }catch(e){err(e instanceof Error?e.message:'评估失败');return false;}finally{busy('');}
  }
  return <div className="style-assessment">
    <section className="desk-assess"><div><strong>用户画像</strong><p>{result?'最近评估于 '+new Date(result.updated).toLocaleString():'完成问卷后，即可查看风险承受能力和风格偏好。'}</p></div>
      <div className="style-actions"><button className="desk-primary" disabled={!data||!!pending||mode!==null} onClick={()=>begin('questionnaire')}>{result?'重新评测':'开始评测'}</button>
      <button disabled={!data||!!pending||mode!==null} onClick={()=>begin('supplement')}>补充资料更新评估</button></div></section>
    {error&&<p role="alert">{error}</p>}{(pending||notice)&&<p role="status">{pending||notice}</p>}
    {mode==='supplement'&&<form className="desk-card" onSubmit={e=>{e.preventDefault();void submit();}}><h3>补充评估资料</h3><fieldset disabled={!!pending}>
      {result?.version!==3?<p>请先完成新版问卷，之后可以结合成交记录或持仓报告更新画像。</p>:<>
        <label>选择成交记录、持仓报告或研究笔记<input type="file" multiple accept=".csv,.tsv,.xlsx,.pdf,.docx,.txt,.md,.png,.jpg,.jpeg" onChange={e=>{const list=Array.from(e.target.files??[]);e.target.value='';void select(list);}}/></label>
        <p>支持 CSV、Excel（.xlsx）、文本 PDF、Word（.docx）、文本和图片。每份最多 4 MB，扫描页可导出为图片识别。</p>
        {files.map((f,i)=><div key={f.name}><label>{f.name}{f.truncated?'（已截取前 12000 字，可替换为关键片段）':''}<textarea required maxLength={12000} value={f.text} onChange={e=>attach(files.map((v,j)=>i===j?{...v,text:e.target.value}:v))}/></label><button type="button" onClick={()=>attach(files.filter((_,j)=>i!==j))}>移除该摘录</button></div>)}
      </>}
      {result&&result.materials.length>0&&<p>本次沿用的资料：{result.materials.join('、')}。上传同名文件可替换摘录。</p>}
      <p>已配置的模型将读取问卷和您确认的资料摘录，请先删去账号等私人信息。</p>
      <div className="style-actions">{result?.version!==3?<button type="button" onClick={()=>begin('questionnaire')}>去填问卷</button>:<button className="desk-primary" disabled={!files.length}>提交评估</button>}
      <button type="button" onClick={()=>open(null)}>取消</button></div></fieldset>
    </form>}
    {!mode&&result?.report&&result.overview&&<StyleReport onAskExpert={onAskExpert} updated={result.updated} report={result.report} overview={result.overview}/>}
    {!mode&&result?.version===1&&<section><h3>上次评估 · 旧版问卷</h3><p>Chives 研究参考 C{result.grade}。重新评测后可查看风格解读与人物匹配。</p>{Object.entries(labels).map(([k,label])=><p key={k}><strong>{label}</strong>　{result.summary[k as Insight]}</p>)}</section>}
    {!mode&&data?.sample&&!result&&<StyleReport onAskExpert={onAskExpert} report={data.sample.report} overview={data.sample.overview} example/>}
  </div>;
}
