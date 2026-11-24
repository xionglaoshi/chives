import {useEffect,useState,type FormEvent} from 'react';
import {useExpertSidebarData} from './ExpertSidebarData';
import {formatPercent,formatPrice,priceDirection} from './ExpertSidebarFormat';
import {askAiPrompts} from '../utils/askAiPrompts';
import type {AskExpert} from './askExpert';
import {desk} from './deskApi';
import './holdings.css';
import {HoldingSecurityFields} from './HoldingSecurityFields';

type Position={note?:string|null;code:string;name:string;qty:number;cost_price:number;available_qty?:number|null};
type Ledger={positions:Position[];cash:number|null};
const money=new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY'});
const quantityLabel = '持仓数量';
const priceLabel = '平均持股成本价（元）';
const costLabel = '持仓成本';
const privacyKey='chives.expertSidebar.hideAmounts';

export function Holdings({onAskExpert}:{onAskExpert:AskExpert}){
 const [book,setBook]=useState<Ledger|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [quoteRevision,setQuoteRevision]=useState(0);
 const {portfolio}=useExpertSidebarData('portfolio',quoteRevision);
 const summary=portfolio.data?.summary;
 const quotes=new Map(portfolio.data?.positions.map(position=>[position.code,position]));
 const [editor,setEditor]=useState<Position|'new'|null>(null);
 const [hidden,setHidden]=useState(()=>{try{return localStorage.getItem(privacyKey)==='1';}catch{return false;}});
 async function refresh(){
  setBusy(true);setError('');
  try{setBook(await desk<Ledger>('holdings'));}catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 useEffect(()=>{void refresh();},[]);
 async function change(body:object){
  setBusy(true);setError('');
  try{setBook(await desk<Ledger>('holdings','POST',body));setEditor(null);setQuoteRevision(value=>value+1);}
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
 const amount=(n:number|null|undefined)=>hidden?'••••':n==null?'—':money.format(n);
 function askPortfolio(){
  const snapshot=portfolio.data;
  if(!snapshot)return;
  const lines=[
   '# 用户持仓', '数据时间：'+(snapshot.asOf??'待更新'),
   ...(hidden?['金额已隐藏。']:[
    '今日估算盈亏：'+amount(snapshot.summary.todayPnl),
    '持仓市值：'+amount(snapshot.summary.totalMarketValue),
    '累计浮盈亏：'+amount(snapshot.summary.totalPnl)
   ]),
   ...snapshot.positions.map(position=>[
    position.name,position.code,'现价 '+formatPrice(position.price),'今日涨跌 '+formatPercent(position.changePct),
    ...(hidden?[]:['今日贡献 '+amount(position.todayPnl)])
   ].join(' · '))
  ];
  onAskExpert(askAiPrompts['行情看板']['我的持仓'][snapshot.empty?'空仓':hidden?'隐藏金额':'显示金额'],
   new File([lines.join('\n\n')],'用户持仓.md',{type:'text/markdown'}));
 }
 return <section className="holdings"><header><h1>用户持仓</h1><div>
 <button disabled={busy||!!editor} onClick={()=>{void refresh();setQuoteRevision(value=>value+1);}}>刷新</button>
 <button disabled={!book||busy||!!editor} className="holdings-primary" onClick={()=>{setError('');setEditor('new');}}>添加持仓</button></div></header>
 {error&&<p role="alert">{error}</p>}
 {book&&<><div className="holdings-totals">
 <div><span>今日估算盈亏</span><strong className={'holding-'+priceDirection(summary?.todayPnl??null)}>{amount(summary?.todayPnl)}</strong></div>
 <div><span>持仓市值</span><strong>{amount(summary?.totalMarketValue)}</strong></div>
 <div><span>累计浮盈亏</span><strong className={'holding-'+priceDirection(summary?.totalPnl??null)}>{amount(summary?.totalPnl)}</strong></div><div><span>持仓成本合计</span><strong>{amount(book.positions.reduce((a,p)=>a+p.qty*p.cost_price,0))}</strong></div><div><span>证券数量</span><strong>{book.positions.length} 只</strong></div>
 <div className="holdings-actions"><button disabled={!portfolio.data} onClick={askPortfolio}>问AI</button><button aria-pressed={hidden} onClick={()=>{setHidden(!hidden);try{localStorage.setItem(privacyKey,hidden?'0':'1');}catch{/* Session display still works. */}}}>{hidden?'显示金额':'隐藏金额'}</button></div></div>
 {book.positions.length>0&&<small role="status">
 {portfolio.status==='loading'?'正在读取持仓行情…':!portfolio.data?'持仓行情暂不可用':
  ['今日盈亏按现持股数及较昨收价差估算',
   summary?.unpricedCount?'部分持仓缺少报价':null,portfolio.status==='error'?'最近缓存':null].filter(Boolean).join(' · ')}
 </small>}
 {editor&&<form key={current?.code??'new'} onSubmit={save}><h2>{current?'编辑持仓':'添加持仓'}</h2><fieldset disabled={busy}>
 <HoldingSecurityFields current={current} hidden={hidden}/>
 </fieldset><div className="holdings-actions"><button type="button" disabled={busy} onClick={()=>{setEditor(null);setError('');}}>取消</button><button className="holdings-primary" disabled={busy}>保存持仓</button></div></form>}
 <h2>持仓明细</h2>
 {book.positions.length === 0 ? <p>尚未录入持仓。请输入代码或简称添加证券。</p> : (
   <div className="holdings-table">
     <table role="table">
       <thead role="rowgroup">
         <tr role="row">{['证券', quantityLabel, priceLabel, costLabel, '现价', '今日涨跌', '今日贡献', '操作'].map(label =>
           <th key={label} role="columnheader" scope="col">{label}</th>
         )}</tr>
       </thead>
       <tbody role="rowgroup">{book.positions.map(position => {
         const quote=quotes.get(position.code);
         const metrics = [
           [quantityLabel, hidden ? '••••' : position.qty.toLocaleString('zh-CN')],
           [priceLabel, hidden ? '••••' : position.cost_price],
           [costLabel, amount(position.qty * position.cost_price)],
           ['现价', formatPrice(quote?.price??null)],
           ['今日涨跌', formatPercent(quote?.changePct??null), priceDirection(quote?.changePct??null)],
           ['今日贡献', amount(quote?.todayPnl), priceDirection(quote?.todayPnl??null)]
         ] as const;
         return <tr role="row" key={position.code}>
           <td role="cell">
             <b>{position.name}</b><small>{position.code}</small>
             {position.note?.startsWith('模拟持仓') && <small>模拟持仓</small>}
           </td>
           {metrics.map(([label, value, direction]) =>
             <td role="cell" key={label} className={direction?'holding-'+direction:undefined}>
               <span className="holding-mobile-label" aria-hidden="true">{label}</span>{value}
             </td>
           )}
           <td role="cell">
             <button disabled={busy || !!editor} onClick={() => { setError(''); setEditor(position); }}>编辑</button>{' '}
             <button disabled={busy || !!editor} onClick={() => {
               if (window.confirm('从个人持仓账本移除 '+position.name+'（'+position.code+'）？')) {
                 void change({action:'remove', original:position});
               }
             }}>移除</button>
           </td>
         </tr>;
       })}</tbody>
     </table>
   </div>
 )}
 </>}
 {!book&&busy&&<p role="status">正在读取持仓…</p>}
 </section>;
}
