import {useEffect,useRef,useState} from 'react';
import {desk} from './deskApi';
import {preview} from './StyleAssessment';
import {appPath} from '../appPath';
import './questionnaire.css';

export type Answer={choice?:number;choices?:number[];allocation?:number[];skipped?:boolean|undefined;note?:string|undefined};
export type InterviewAnswers=Record<string,Answer>;
export type InterviewQuestion={id:string;title:string;options:string[];why:string;type:string;chapter:string};
type Material={name:string;text:string};
type Draft={scope:string;index:number;answers:InterviewAnswers;selfDescription:string;materials:Material[];revision:string|null;profileRevision:string|null};
type Interview={questions:InterviewQuestion[];draft:Draft;currentRevision:string|null;previousMaterials:string[]};
const answered=(a?:Answer)=>!!a&&!a.skipped&&(a.choice!==undefined||!!a.choices?.length||!!a.allocation||!!a.note?.trim());
const reportUrl=appPath(new URLSearchParams(window.location.search).get('from')==='workspace' ? '/#/workspace/portrait' : '/#/settings?tab=risk');

export function QuestionnairePage(){
 const [data,setData]=useState<Interview>(),[error,setError]=useState('');
 useEffect(()=>{document.title='用户画像问卷 · Chives';let live=true;desk<Interview>('interview').then(v=>{if(live)setData(v);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
 return <main className="exam-page">{data?<InterviewForm data={data}/>:<p role="status">{error||'正在读取本机问卷…'}</p>}</main>;
}

function InterviewForm({data}:{data:Interview}){
 const [draft,setDraft]=useState(data.draft),[status,setStatus]=useState(''),[error,setError]=useState('');
 const [busy,setBusy]=useState(false);
 const state=useRef(draft),revision=useRef(draft.revision),dirty=useRef(false),saving=useRef<Promise<void>|null>(null);
 const [stale,setStale]=useState(data.currentRevision!==draft.profileRevision);
 const {questions}=data,question=questions[draft.index],answer=question?draft.answers[question.id]:undefined;
 const count=questions.filter(q=>answered(draft.answers[q.id])).length;
 const [lastSaved,setLastSaved]=useState(!!draft.revision);
 const title=useRef<HTMLHeadingElement>(null);
 useEffect(()=>{title.current?.focus({preventScroll:true});window.scrollTo(0,0);},[draft.index]);
 useEffect(()=>{
  function warn(event:BeforeUnloadEvent){if(dirty.current||saving.current){event.preventDefault();event.returnValue='';}}
  window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);
 },[]);
 function flush():Promise<void>{
  if(saving.current)return saving.current;
  saving.current=(async()=>{
   while(dirty.current){
    dirty.current=false;setStatus('正在保存…');
    try{const saved=await desk<{revision:string}>('interview-draft','POST',{...state.current,revision:revision.current});
     revision.current=saved.revision;setLastSaved(true);
    }catch(e){dirty.current=true;setStatus('草稿保存失败');throw e;}
   }
   setStatus('已保存到本机');
  })().finally(()=>{saving.current=null;});
  return saving.current;
 }
 function change(patch:Partial<Draft>){
  const next={...state.current,...patch};state.current=next;setDraft(next);dirty.current=true;setError('');
  void flush().catch(e=>setError(e.message));
 }
 function respond(value:Answer){
  if(!question)return;
  const next={...state.current.answers};if(answered(value))next[question.id]=value;else delete next[question.id];
  change({answers:next});
 }
 async function leave(){setBusy(true);try{await flush();window.location.assign(reportUrl);}catch(e){setError((e as Error).message);setBusy(false);}}
 async function submit(){
  const missing=questions.findIndex(q=>!answered(state.current.answers[q.id]));
  if(missing!==-1){change({index:missing});setError('请先回答这一题。');return;}
  setBusy(true);setError('');
  try{if(!revision.current)dirty.current=true;await flush();setStatus('总经理正在核对完整答卷并整理档案…');
   await desk('interview-submit','POST',{revision:revision.current});window.location.replace(reportUrl);
  }catch(e){setError((e as Error).message);setStatus('答卷已保留，可再次提交');setBusy(false);}
 }
 async function attach(files:File[]){
  setBusy(true);setError('');
  try{for(const file of files){
   const value=await preview(file),next=state.current.materials.filter(m=>m.name!==value.name);
   if(next.length>=8)throw Error('最多可提交八份资料。');
   change({materials:[...next,{name:value.name,text:value.text}]});
   if(value.truncated)setStatus('该文件已截取前 12000 字，请核对摘录。');
  }}catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 return <>
 <header className="exam-head"><span>总经理 · 客户访谈</span><button disabled={busy} onClick={()=>void leave()}>保存并退出</button></header>
 {stale?<section><h1>答题期间，您的正式画像有更新</h1><p>草稿仍在本机。继续后可逐题核对，提交时将按本次答卷重新评估。</p><button onClick={()=>{setStale(false);change({profileRevision:data.currentRevision,index:0});}}>核对草稿</button></section>:
 <fieldset disabled={busy} className="exam-body"><div className="exam-progress"><span>{question?'第 '+(draft.index+1)+' / '+questions.length+' 题':'问卷补充'}</span><span>已答 {count} 题</span></div>
 <progress max={questions.length} value={count} aria-label="答题进度"/>
 {question?<section key={question.id}><small>{question.chapter}</small>
 <h1 ref={title} tabIndex={-1}>{question.title}</h1>
 <p className="exam-why"><em>为什么问　{question.why}</em></p>
 <div className="exam-options">{question.options.map((label,i)=><label key={label}>
   <input type="radio" name={question.id} checked={answer?.choice===i} onChange={()=>respond({...answer,choice:i})}/>{label}
 </label>)}</div>
 <label className="exam-text">补充说明（选填）<textarea maxLength={1500} value={answer?.note??''} onChange={e=>respond({...answer,note:e.target.value})}/></label>
 </section>:<section><h1 ref={title} tabIndex={-1}>还有什么希望 Chives 了解您？</h1><p className="exam-why"><em>您可以补充问卷没问到的经历、资金安排，或希望 Bot 怎样与您交流。您说得越具体，Chives 在以后的任务中就越能贴合您的实际情况。</em></p>
 <label className="exam-text">补充自述（选填）<textarea rows={6} maxLength={8000} value={draft.selfDescription} onChange={e=>change({selfDescription:e.target.value})}/></label>
 <label className="exam-text">补充资料（选填）<input type="file" multiple accept=".csv,.tsv,.xlsx,.pdf,.docx,.txt,.md,.png,.jpg,.jpeg" onChange={e=>{const files=Array.from(e.target.files??[]);e.target.value='';void attach(files);}}/></label>
 {data.previousMaterials.length>0&&<p>已保存的资料会一同评估：{data.previousMaterials.join('、')}。可上传同名文件替换。</p>}
 {draft.materials.map((m,i)=><div key={m.name}><label className="exam-text">核对摘录 · {m.name}<textarea value={m.text} maxLength={12000} onChange={e=>change({materials:draft.materials.map((x,j)=>i===j?{...x,text:e.target.value}:x)})}/></label><button onClick={()=>change({materials:draft.materials.filter((_,j)=>j!==i)})}>移除</button></div>)}
 <p>提交后，总经理会核对整份答卷、自述和资料摘录，写入有依据的个人偏好和近期事项，并列出仍需核实的地方。</p></section>}
 <footer><button disabled={draft.index===0} onClick={()=>change({index:draft.index-1})}>上一题</button>
 {question?<button className="exam-primary" disabled={!answered(answer)} onClick={()=>change({index:draft.index+1})}>下一题</button>:<button className="exam-primary" onClick={()=>void submit()}>交给总经理建档</button>}</footer>
 </fieldset>}
 <p className="exam-status" role="status">{status||(lastSaved?'已保存到本机':'作答后自动保存到本机')}</p>
 {error&&<div role="alert">{error} {dirty.current&&<button onClick={()=>void flush().catch(e=>setError(e.message))}>重试保存</button>}</div>}
 </>;
}
