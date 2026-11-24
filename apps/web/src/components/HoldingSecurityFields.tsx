import {useEffect,useMemo,useState} from 'react';
import {appPath} from '../appPath';
import {desk} from './deskApi';

type Security={code:string;name:string};
type Position=Security & {qty:number;cost_price:number};
type Quote={price:number;basis:string;as_of:string};
const display=(s:Security)=>s.name+' · '+s.code;
const currency=new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY'});
const amount=(n:number|null)=>n===null?'—':currency.format(n);
const normalize=(s:string)=>s.trim().toUpperCase().replace(/\s+/g,'');

export function HoldingSecurityFields({current,hidden}:{current:Position|null;hidden:boolean}){
 const [rows,setRows]=useState<Security[]>([]),[failed,setFailed]=useState(false);
 const [text,setText]=useState(current?display(current):''),[touched,setTouched]=useState(false);
 const [cost,setCost]=useState(current?String(current.cost_price):''),[qty,setQty]=useState(current?String(current.qty):'100');
 const [result,setResult]=useState<{code:string;quote:Quote|null}|null>(null);
 useEffect(()=>{
  if(current)return;
  const controller=new AbortController();
  fetch(appPath('/holdings-securities.json'),{signal:controller.signal}).then(async r=>{
   if(!r.ok)throw Error();
   setRows(Object.entries(await r.json() as Record<string,string>).map(([code,name])=>({code,name})));
  }).catch(()=>{if(!controller.signal.aborted)setFailed(true);});
  return ()=>controller.abort();
 },[current]);
 const term=normalize(text);
 const matches=useMemo(()=>term?rows.filter(s=>s.code.startsWith(term)||normalize(s.name).includes(term)||normalize(display(s))===term):[],[term,rows]);
 const exact=matches.filter(s=>s.code===term||s.code.split('.')[0]===term||normalize(s.name)===term||normalize(display(s))===term);
 const selected=current??(exact.length===1?exact[0]:null);
 const code=selected?.code??'';
 useEffect(()=>{
  if(!code)return;
  let active=true;
  function load(){desk<Quote|null>('holdings','POST',{action:'quote',code}).then(quote=>{if(active)setResult({code,quote});}).catch(()=>{if(active)setResult({code,quote:null});});}
  load();const timer=window.setInterval(load,60000);
  return ()=>{active=false;window.clearInterval(timer);};
 },[code]);
 const quote=result?.code===code?result.quote:null;
 const count=Number(qty),validQty=Number.isSafeInteger(count)&&count>0;
 const value=quote&&validQty?quote.price*count:null;
 const basis=validQty&&Number(cost)>0?Number(cost)*count:null;
 const profit=value!==null&&basis!==null?value-basis:null;
 return <>
 <div className="holding-form-row"><label>证券代码或简称<input required readOnly={!!current} list="holding-securities" value={text} placeholder="输入代码、股票或基金简称" onBlur={()=>setTouched(true)} onChange={e=>setText(e.target.value)}/>
 <datalist id="holding-securities">{matches.slice(0,20).map(s=><option key={s.code} value={display(s)}/>)}</datalist>
 <input type="hidden" name="code" value={code}/><input type="hidden" name="name" value={selected?.name??''}/>
 {selected&&!current&&text!==display(selected)&&<small>{display(selected)}</small>}
 {failed&&<small role="alert">本地名录加载失败，请刷新。</small>}
 {touched&&term&&!selected&&!failed&&<small role="alert">{matches.length?'请选择与代码对应的证券。':'未找到该证券，请核对代码或简称。'}</small>}</label>
 <div><span>当前价格（元）</span><output>{quote?quote.price:code?(result?.code===code?'暂无行情':'读取中…'):'—'}</output>{quote&&<small>{quote.basis} · {quote.as_of}</small>}</div></div>
 <div className="holding-form-row"><label>成本价（元）<input name="cost" type="number" required min="0.000001" step="any" value={cost} onChange={e=>setCost(e.target.value)}/></label>
 <label>{/^(11|12|81)/.test(code)&&!code.endsWith('.OF')?'持有数量（张）':code.endsWith('.OF')||/^(5|15|16|18)/.test(code)?'持有份数（份）':'持股数（股）'}<input name="qty" type="number" required min="1" step="1" value={qty} onChange={e=>setQty(e.target.value)}/></label></div>
 <div className="holding-valuation" aria-live="polite">{[['持股市值',value],['持股总成本',basis],['账面盈亏',profit]].map(([label,n])=><div key={label}><span>{label}</span><output className={label==='账面盈亏'&&!hidden&&profit?(profit>0?'holding-gain':'holding-loss'):''}>{hidden?'••••':amount(n as number|null)}</output></div>)}</div>
 </>;
}
