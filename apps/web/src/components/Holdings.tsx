import {useEffect,useState,type FormEvent} from 'react';
import {useExpertSidebarData} from './ExpertSidebarData';
import {formatPercent,formatPrice,priceDirection} from './ExpertSidebarFormat';
import {askAiPrompts} from '../utils/askAiPrompts';
import type {AskExpert} from './askExpert';
import {desk} from './deskApi';
import './holdings.css';
import {ValuationNotice,ValuationOutlook,ValuationRange,type EstimateRange} from './ValuationRange';
import {HoldingSecurityFields} from './HoldingSecurityFields';

type Position={code:string;name:string;qty:number;cost_price:number;available_qty?:number|null};
type Ledger={positions:Position[];cash:number|null};
const pnlNumber=new Intl.NumberFormat('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
const money=new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY'});
const quantityLabel = '持股数';
const priceLabel = '成本价';
const privacyKey='chives.expertSidebar.hideAmounts';

export function Holdings({onAskExpert}:{onAskExpert:AskExpert}){
 const [book,setBook]=useState<Ledger|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [valuations,setValuations]=useState<Record<string,EstimateRange|null>>({});
 const [valuating,setValuating]=useState<string|null>(null);
 const [valuationError,setValuationError]=useState('');
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
 useEffect(()=>{
  if (!book?.positions.length) return;
  let active=true;
  void desk<Record<string,EstimateRange|null>>('holdings-valuations')
   .then(result=>{if(active){setValuations(result);setValuationError('');}})
   .catch(()=>{if(active)setValuationError('暂时无法读取AI估算的合理股价。');});
  return ()=>{active=false;};
 },[book]);
 async function measure(code:string){
  setValuating(code);setValuationError('');
  try{
   const result=await desk<EstimateRange>('holdings-valuations','POST',{code});
   setValuations(current=>({...current,[code]:result}));
  }catch(error){setValuationError((error as Error).message);}
  finally{setValuating(null);}
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
 <button disabled={busy||!!editor||!!valuating} onClick={()=>{void refresh();setQuoteRevision(value=>value+1);}}>刷新</button>
 <button disabled={!book||busy||!!editor} className="holdings-primary" onClick={()=>{setError('');setEditor('new');}}>添加持仓</button></div></header>
 {error&&<p role="alert">{error}</p>}
 {valuationError&&<p role="status">{valuationError}</p>}
 {book&&<><div className="holdings-totals">
 <div><span>今日估算盈亏</span><strong className={'holding-'+priceDirection(summary?.todayPnl??null)}>{amount(summary?.todayPnl)}</strong></div>
 <div><span>持仓市值</span><strong>{amount(summary?.totalMarketValue)}</strong></div>
 <div><span>累计浮盈亏</span><strong className={'holding-'+priceDirection(summary?.totalPnl??null)}>{amount(summary?.totalPnl)}</strong></div><div><span>持仓成本合计</span><strong>{amount(book.positions.reduce((a,p)=>a+p.qty*p.cost_price,0))}</strong></div><div><span>证券数量</span><strong>{book.positions.length} 只</strong></div>
 <div className="holdings-actions"><button disabled={!portfolio.data} onClick={askPortfolio}>问AI</button><button aria-pressed={hidden} onClick={()=>{setHidden(!hidden);try{localStorage.setItem(privacyKey,hidden?'0':'1');}catch{/* Session display still works. */}}}>{hidden?'显示金额':'隐藏金额'}</button></div></div>
 {book.positions.length>0&&<>
 <small role="status">
 {portfolio.status==='loading'?'正在读取持仓行情…':!portfolio.data?'持仓行情暂不可用':
  [summary?.unpricedCount?'部分持仓缺少报价':null,portfolio.status==='error'?'最近缓存':null].filter(Boolean).join(' · ')}
 </small>
 <ValuationNotice/>
 </>}
 {editor&&<form key={current?.code??'new'} onSubmit={save}><h2>{current?'编辑持仓':'添加持仓'}</h2><fieldset disabled={busy}>
 <HoldingSecurityFields current={current} hidden={hidden}/>
 </fieldset><div className="holdings-actions"><button type="button" disabled={busy} onClick={()=>{setEditor(null);setError('');}}>取消</button><button className="holdings-primary" disabled={busy}>保存持仓</button></div></form>}
 <h2>持仓明细</h2>
 {book.positions.length === 0 ? <p>尚未录入持仓。请输入代码或简称添加证券。</p> : (
   <div className="holdings-table">
     <table role="table">
       <thead role="rowgroup">
         <tr role="row">{['证券', quantityLabel, priceLabel, '现价', 'AI估算的合理股价', '后市AI预测', '今日涨跌', '今日贡献', '操作'].map(label =>
           <th key={label} role="columnheader" scope="col">{label}</th>
         )}</tr>
       </thead>
       <tbody role="rowgroup">{book.positions.map(position => {
         const quote=quotes.get(position.code);
         const estimate=valuations[position.code];
         const price=quote?.price??null;
         const rawPnl=price!==null && price>0 ? price-position.cost_price : NaN;
         const pnl=Number.isFinite(rawPnl) ? Math.sign(rawPnl)*Math.round(Math.abs(rawPnl)*100)/100 : null;
         const priceTone=hidden || pnl===null || pnl===0 ? '' : pnl>0 ? ' holding-price-profit' : ' holding-price-loss';
         const metrics = [
           [quantityLabel, hidden ? '••••' : position.qty.toLocaleString('zh-CN')],
           [priceLabel, hidden ? '••••' : position.cost_price],
           ['现价', <div className={'holding-current-price'+priceTone}>
             <span>{formatPrice(price)}</span>
             {pnl!==null && <span className="holding-price-pnl">
               {hidden?'每股盈亏 ••••':pnl===0?'每股持平 0.00元':(pnl>0?'每股浮盈 ':'每股浮亏 ')+pnlNumber.format(Math.abs(pnl))+'元'}
             </span>}
           </div>],
           ['AI估算的合理股价', <div className="holding-estimate">
             {valuating===position.code?'测算中…':<ValuationRange estimate={estimate} price={price} showCurrency={false} showComparison/>}
             {!estimate?.low && valuating!==position.code && /^\d{6}\.(SH|SZ|BJ)$/.test(position.code) &&
               <button type="button" disabled={!!valuating||busy||!!editor} onClick={()=>void measure(position.code)}>测算</button>}
           </div>],
           ['后市AI预测', valuating===position.code?'测算中…':<ValuationOutlook estimate={estimate}/>],
           ['今日涨跌', formatPercent(quote?.changePct??null), priceDirection(quote?.changePct??null)],
           ['今日贡献', amount(quote?.todayPnl), priceDirection(quote?.todayPnl??null)]
         ] as const;
         return <tr role="row" key={position.code}>
           <td role="cell">
             <b>{position.name}</b><small>{position.code}</small>
           </td>
           {metrics.map(([label, value, direction]) =>
             <td role="cell" key={label} className={direction?'holding-'+direction:undefined}>
               <span className="holding-mobile-label" aria-hidden="true">{label}</span>{value}
             </td>
           )}
           <td role="cell"><div className="holding-row-actions">
             <button type="button" title="编辑持仓" aria-label={'编辑 '+position.name} disabled={busy || !!editor || !!valuating}
               onClick={() => { setError(''); setEditor(position); }}>
               <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m14 6 4 4M4 20l4.5-1 11-11a2.8 2.8 0 0 0-4-4l-11 11L4 20Z"/></svg>
             </button>
             <button type="button" title="从持仓账本移除" aria-label={'移除 '+position.name} disabled={busy || !!editor || !!valuating} onClick={() => {
               if (window.confirm('从个人持仓账本移除 '+position.name+'（'+position.code+'）？')) {
                 void change({action:'remove', original:position});
               }
             }}>
               <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v6m4-6v6"/></svg>
             </button>
           </div></td>
         </tr>;
       })}</tbody>
     </table>
   </div>
 )}
 </>}
 {!book&&busy&&<p role="status">正在读取持仓…</p>}
 </section>;
}
