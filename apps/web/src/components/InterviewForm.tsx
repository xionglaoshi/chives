import {useEffect,useRef,useState} from 'react';
import {desk} from './deskApi';
import {preview} from './StyleAssessment';
import {appPath} from '../appPath';
import './questionnaire.css';

export type Answer={choice?:number;choices?:number[];allocation?:number[];skipped?:boolean|undefined;note?:string|undefined};
export type InterviewAnswers=Record<string,Answer>;
export type InterviewQuestion={id:string;title:string;options:string[];why:string;type:string;param:string;initial:boolean};
type Material={name:string;text:string};
type Draft={scope:string;index:number;answers:InterviewAnswers;selfDescription:string;materials:Material[];revision:string|null;profileRevision:string|null};
type Interview={questions:InterviewQuestion[];draft:Draft;currentRevision:string|null;previousMaterials:string[]};
const fallbackAllocation=[0,0,0,0,0,0,0,0,0,0,100];
const exclusive=/^(暂时没有其他|都能比较|说不准|这些收入和资产没有|不确定|开通过相关权限|以上都|暂时没有特别|从未直接|平时不用|从没用)/;
const answered=(a?:Answer)=>!!a&&!a.skipped&&(a.choice!==undefined||!!a.choices?.length||!!a.allocation||!!a.note?.trim());
const reportUrl=appPath(new URLSearchParams(window.location.search).get('from')==='workspace' ? '/#/workspace/portrait' : '/#/settings?tab=risk');

export function QuestionnairePage(){
 const [data,setData]=useState<Interview>(),[error,setError]=useState('');
 useEffect(()=>{document.title='用户画像问卷 · Chives';let live=true;desk<Interview>('interview').then(v=>{if(live)setData(v);}).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
 return <main className="exam-page">{data?<InterviewForm data={data}/>:<p role="status">{error||'正在读取本机问卷…'}</p>}</main>;
}

function InterviewForm({data}:{data:Interview}){
 const [draft,setDraft]=useState(data.draft),[status,setStatus]=useState(''),[error,setError]=useState('');
 const [busy,setBusy]=useState(false),[showNote,setShowNote]=useState(false);
 const state=useRef(draft),revision=useRef(draft.revision),dirty=useRef(false),saving=useRef<Promise<void>|null>(null);
 const [stale,setStale]=useState(data.currentRevision!==draft.profileRevision);
 const {questions}=data,question=questions[draft.index],answer=question?draft.answers[question.id]:undefined;
 const count=questions.filter(q=>answered(draft.answers[q.id])).length;
 const [lastSaved,setLastSaved]=useState(!!draft.revision);
 const title=useRef<HTMLHeadingElement>(null);
 useEffect(()=>{setShowNote(false);title.current?.focus({preventScroll:true});window.scrollTo(0,0);},[draft.index]);
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
 // Move earlier browser-only progress into the file the first time the new page opens.
 useEffect(()=>{
  if(data.draft.revision||stale)return;
  const key='chives.interview100.v2.'+(data.currentRevision??'new');let old;
  try{old=JSON.parse(localStorage.getItem(key)??'null');}catch{return;}
  if(!old||!old.answers||!['family','personal'].includes(old.scope))return;
  const list=questions.filter(q=>(old.full||q.initial)&&!(q.id==='34'&&old.answers['33']?.choice===0)&&!(q.id==='94'&&old.answers['15']?.choice===0));
  const index=Math.max(0,questions.findIndex(q=>q.id===list[old.index]?.id));
  change({answers:{...data.draft.answers,...old.answers},scope:old.scope,index});
  void flush().then(()=>localStorage.removeItem(key)).catch(()=>{});
 },[]); // Only migrate the draft loaded at entry.
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
  try{if(!revision.current)dirty.current=true;await flush();setStatus('模型正在生成您的报告…');
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
 const allocation=answer?.allocation??fallbackAllocation;
 const noteOnly=!!answer?.note&&answer.choice===undefined&&!answer.choices&&!answer.allocation;
 const hasOtherOption=question?.type==='allocation'?-1:question?.options.findIndex(v=>/^其他(?:$|.*[（(]|原因$|用途$|情况$)/.test(v))??-1;
 const selectedOther=hasOtherOption>=0&&(answer?.choice===hasOtherOption||answer?.choices?.includes(hasOtherOption));
 return <>
 <header className="exam-head"><span>Chives · 用户画像问卷</span><button disabled={busy} onClick={()=>void leave()}>保存并退出</button></header>
 {stale?<section><h1>答题期间，您的正式画像有更新</h1><p>草稿仍在本机。继续后可逐题核对，提交时将按本次答卷重新评估。</p><button onClick={()=>{setStale(false);change({profileRevision:data.currentRevision,index:0});}}>核对草稿</button></section>:
 <fieldset disabled={busy} className="exam-body"><div className="exam-progress"><span>{question?'第 '+(draft.index+1)+' / '+questions.length+' 题':'问卷补充'}</span><span>已答 {count} 题</span></div>
 <progress max={questions.length} value={count} aria-label="答题进度"/>
 {question?<section key={question.id}>
 {draft.index===0&&<fieldset className="exam-scope"><legend>本次填写谁的资产？</legend>{[['personal','我个人的资产'],['family','家庭共同资产']].map(([value,label])=><label key={value}><input type="radio" name="scope" checked={draft.scope===value} onChange={()=>{if(!count||window.confirm('切换统计范围后，请核对已有答案是否也适用于新范围。确定切换吗？'))change({scope:value!});}}/>{label}</label>)}</fieldset>}
 <h1 ref={title} tabIndex={-1}>{question.id==='18'&&draft.scope==='family'?question.title.replace('您每月','您家里每月'):question.title}</h1>
 <p className="exam-why"><em>为什么问　{question.why}</em></p>
 <div className="exam-options">{question.type==='allocation'?<>
 <p>填写大致百分比，剩余比例自动计入「其他」。</p>{question.options.map((label,i)=><label key={label}>{label}<span><input aria-label={label+'百分比'} type="number" min="0" max={100} disabled={i===10} value={allocation[i]} onChange={e=>{const a=[...allocation];const n=Math.min(a[i]!+a[10]!,Math.max(0,Math.round(Number(e.target.value)||0)));a[10]!+=a[i]!-n;a[i]=n;respond({allocation:a,note:answer?.note});}}/> %</span></label>)}
 {!answer?.allocation&&<button onClick={()=>respond({allocation:[...allocation],note:answer?.note})}>确认当前比例</button>}</>:
 question.options.map((label,i)=>{
 const multi=question.type==='multi',checked=multi?!!answer?.choices?.includes(i):answer?.choice===i;
 return <label key={i}><input type={multi?'checkbox':'radio'} name={question.id} checked={checked} onChange={()=>{
  const note=noteOnly?undefined:answer?.note;
  if(!multi){setShowNote(false);respond({choice:i,note:selectedOther||showNote?undefined:note});return;}
  const old=answer?.choices??[],choices=checked?old.filter(v=>v!==i):exclusive.test(label)?[i]:[...old.filter(v=>!exclusive.test(question.options[v]!)),i];
  if(['42','84'].includes(question.id)&&choices.length>3){setError('这道题最多选择三项。');return;}
  respond(choices.length?{choices,note}:{note});
 }}/>{label}</label>;})}
 {hasOtherOption<0&&<label><input type={question.type==='single'?'radio':'checkbox'} name={question.type==='single'?question.id:undefined} checked={showNote||noteOnly||(question.type!=='single'&&!!answer?.note)} onChange={e=>{setShowNote(e.target.checked);if(question.type==='single'&&e.target.checked)respond({note:answer?.note});else if(!e.target.checked){const {note,...rest}=answer??{};respond(rest);}}}/>其他情况，我想自己描述</label>}
 </div>
 {(showNote||selectedOther||!!answer?.note||question.id==='40')&&<label className="exam-text">您的说明<textarea maxLength={1500} value={answer?.note??''} onChange={e=>respond({...answer,skipped:undefined,note:e.target.value})}/></label>}
 </section>:<section><h1 ref={title} tabIndex={-1}>还有什么希望 Chives 了解您？</h1><p className="exam-why"><em>您可以补充问卷没问到的经历、资金安排，或希望 Bot 怎样与您交流。您说得越具体，Chives 在以后的任务中就越能贴合您的实际情况。</em></p>
 <label className="exam-text">补充自述（选填）<textarea rows={6} maxLength={8000} value={draft.selfDescription} onChange={e=>change({selfDescription:e.target.value})}/></label>
 <label className="exam-text">补充资料（选填）<input type="file" multiple accept=".csv,.tsv,.xlsx,.pdf,.docx,.txt,.md,.png,.jpg,.jpeg" onChange={e=>{const files=Array.from(e.target.files??[]);e.target.value='';void attach(files);}}/></label>
 {data.previousMaterials.length>0&&<p>已保存的资料会一同评估：{data.previousMaterials.join('、')}。可上传同名文件替换。</p>}
 {draft.materials.map((m,i)=><div key={m.name}><label className="exam-text">核对摘录 · {m.name}<textarea value={m.text} maxLength={12000} onChange={e=>change({materials:draft.materials.map((x,j)=>i===j?{...x,text:e.target.value}:x)})}/></label><button onClick={()=>change({materials:draft.materials.filter((_,j)=>j!==i)})}>移除</button></div>)}
 <p>提交后，当前模型将收到您的问卷、自述和确认的资料摘录，并按 Chives 的评价依据生成报告。</p></section>}
 <footer><button disabled={draft.index===0} onClick={()=>change({index:draft.index-1})}>上一题</button>
 {question?<button className="exam-primary" disabled={!answered(answer)} onClick={()=>change({index:draft.index+1})}>下一题</button>:<button className="exam-primary" onClick={()=>void submit()}>提交并生成报告</button>}</footer>
 </fieldset>}
 <p className="exam-status" role="status">{status||(lastSaved?'已保存到本机':'作答后自动保存到本机')}</p>
 {error&&<div role="alert">{error} {dirty.current&&<button onClick={()=>void flush().catch(e=>setError(e.message))}>重试保存</button>}</div>}
 </>;
}
