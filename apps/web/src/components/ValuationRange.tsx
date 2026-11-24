import './ValuationRange.css';

export type EstimateRange = {low:number|null;high:number|null;valuationKind?:string};
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
  return <small className="valuation-notice">合理股价由Chives基于该股基本面、近一年交易数据及所处行业动态等复合估算而出。AI会犯错，数据仅供投研参考，请勿作为投资依据。</small>;
}
