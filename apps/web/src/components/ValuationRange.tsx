import './ValuationRange.css';

export type EstimateRange = {low:number|null;high:number|null;valuationKind?:string;score?:number|null};
const format = new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2});

function valuationComparison(estimate: EstimateRange|undefined|null, price: number|undefined|null) {
  const low = estimate?.low, high = estimate?.high;
  if (typeof low !== 'number' || typeof high !== 'number' ||
      !Number.isFinite(low) || !Number.isFinite(high) || low <= 0 || low > high) return null;
  const priced = typeof price === 'number' && Number.isFinite(price) && price > 0;
  return {low, high, below:priced && price < low, above:priced && price > high, priced};
}

export function ValuationRange({estimate,price,showCurrency=true,showComparison=false}: {estimate:EstimateRange|undefined|null;price:number|undefined|null;showCurrency?:boolean;showComparison?:boolean}) {
  const range=valuationComparison(estimate,price);
  if(!range)return estimate?'依据不足':'待测算';
  const tone=range.below?'below':range.above?'above':range.priced?'inside':'unpriced';
  const boundary=range.below?range.low:range.above?range.high:null;
  return <>
    <span className={'valuation-range--'+tone}>{showCurrency && '¥'}{format.format(range.low)}–{format.format(range.high)}</span>
    {showComparison && boundary!==null && typeof price==='number' &&
      <small className="valuation-range__comparison">现价{range.below?'低于估值下限':'高于估值上限'} {format.format(Math.abs(price/boundary-1)*100)}%</small>}
  </>;
}

export function ValuationNotice() {
  return <small className="valuation-notice">AI估算的合理股价及后市AI预测均由Chives基于该股公开数据、近一年交易数据、外围对标市场、行业动态及国家政策等37个因素复合估算而出，历史数据回测平均准确率仅为64.7%。AI会犯错，数据仅供投研参考，请勿作为投资依据。</small>;
}

function OutlookFaces({score}:{score:number}) {
  const direction=score>0?'up':score<0?'down':'neutral';
  const label=score>0?'看涨':score<0?'看跌':'中性';
  return <span className={`valuation-outlook valuation-outlook--${direction}`} role="img"
    aria-label={score===0?label:`${label} ${Math.abs(score)} 档`} title={`未来 20 个交易日 · ${label}`}>
    <span className="valuation-outlook__label">{label}</span>
    {Array.from({length:Math.max(1,Math.abs(score))},(_,index)=>
      <svg key={index} viewBox="0 0 24 24" width="20" height="20" fill="none"
        stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10"/>
        {score===0?<path d="M9.5 9a2.5 2.5 0 1 1 4 2c-1.2.8-1.5 1.2-1.5 2.2m0 3.3h.01"/>:<>
          <path d="M8 9h.01m8 0h.01"/>
          <path d={score>0?'M7.5 13.5c2 3.8 7 3.8 9 0':'M7.5 16c2-3 7-3 9 0m1-4.5v1'}/>
        </>}
      </svg>)}
  </span>;
}

export function ValuationOutlook({estimate}: {estimate: EstimateRange|null|undefined}) {
  return estimate?.score == null ? (estimate ? '依据不足' : '待测算') : <OutlookFaces score={estimate.score}/>;
}
