import {useEffect,useState,type FormEvent} from 'react';
import {desk} from './deskApi';
import './holdings.css';
import {HoldingSecurityFields} from './HoldingSecurityFields';

type Position={note?:string|null;code:string;name:string;qty:number;cost_price:number;available_qty?:number|null};
type Ledger={positions:Position[];cash:number|null};
const money=new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY'});
const privacyKey='chives.expertSidebar.hideAmounts';

export function Holdings(){
 const [book,setBook]=useState<Ledger|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [editor,setEditor]=useState<Position|'new'|null>(null);
 const [hidden,setHidden]=useState(()=>{try{return localStorage.getItem(privacyKey)==='1';}catch{return false;}});
 async function refresh(){
  setBusy(true);setError('');
  try{setBook(await desk<Ledger>('holdings'));}catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 useEffect(()=>{void refresh();},[]);
 async function change(body:object){
  setBusy(true);setError('');
  try{setBook(await desk<Ledger>('holdings','POST',body));setEditor(null);}
  catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 function save(event:FormEvent<HTMLFormElement>){
  event.preventDefault();
  const f=new FormData(event.currentTarget),name=String(f.get('name')).trim(),qty=Number(f.get('qty')),cost=Number(f.get('cost'));
  if(!Number.isSafeInteger(qty)||qty<1){setError('请输入有效的持股数量。');return;}
  if(!f.get('code')){setError('请先从本地名录选择证券。');return;}
  if(editor==='new')void change({action:'add',row:{code:String(f.get('code')).trim(),name,quantity:qty,cost}});
  else if(editor)void change({action:'edit',original:editor,row:{qty,cost_price:cost,available_qty:editor.available_qty==null?null:Math.min(editor.available_qty,qty)}});
 }
 const current=typeof editor==='object'?editor:null;
 const amount=(n:number)=>hidden?'••••':money.format(n);
 return <section className="holdings"><header><h1>用户持仓</h1><div>
 <button disabled={busy||!!editor} onClick={()=>void refresh()}>刷新</button>
 <button disabled={!book||busy||!!editor} className="holdings-primary" onClick={()=>{setError('');setEditor('new');}}>添加持仓</button></div></header>
 {error&&<p role="alert">{error}</p>}
 {book&&<><div className="holdings-totals"><div><span>持仓成本合计</span><strong>{amount(book.positions.reduce((a,p)=>a+p.qty*p.cost_price,0))}</strong></div><div><span>证券数量</span><strong>{book.positions.length} 只</strong></div>
 <button aria-pressed={hidden} onClick={()=>{setHidden(!hidden);try{localStorage.setItem(privacyKey,hidden?'0':'1');}catch{/* Session display still works. */}}}>{hidden?'显示金额':'隐藏金额'}</button></div>
 {editor&&<form key={current?.code??'new'} onSubmit={save}><h2>{current?'编辑持仓':'添加持仓'}</h2><fieldset disabled={busy}>
 <HoldingSecurityFields current={current} hidden={hidden}/>
 </fieldset><div className="holdings-actions"><button type="button" disabled={busy} onClick={()=>{setEditor(null);setError('');}}>取消</button><button className="holdings-primary" disabled={busy}>保存持仓</button></div></form>}
 <h2>持仓明细</h2>{book.positions.length===0?<p>尚未录入持仓。请输入代码或简称添加证券。</p>:<div className="holdings-table"><table><thead><tr><th>证券</th><th>持仓数量</th><th>平均持股成本价（元）</th><th>持仓成本</th><th>操作</th></tr></thead><tbody>{book.positions.map(p=><tr key={p.code}><td><b>{p.name}</b><small>{p.code}</small>{p.note?.startsWith('模拟持仓')&&<small>模拟持仓</small>}</td><td>{hidden?'••••':p.qty.toLocaleString('zh-CN')}</td><td>{hidden?'••••':p.cost_price}</td><td>{amount(p.qty*p.cost_price)}</td><td><button disabled={busy||!!editor} onClick={()=>{setError('');setEditor(p);}}>编辑</button> <button disabled={busy||!!editor} onClick={()=>{if(window.confirm('从个人持仓账本移除 '+p.name+'（'+p.code+'）？'))void change({action:'remove',original:p});}}>移除</button></td></tr>)}</tbody></table></div>}</>}
 {!book&&busy&&<p role="status">正在读取持仓…</p>}
 </section>;
}
