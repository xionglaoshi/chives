import './ValuationRange.css';

export type EstimateRange = {low:number|null;high:number|null;valuationKind?:string};
const format = new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2});

export function valuationComparison(estimate: EstimateRange|undefined|null, price: number|undefined|null) {
  const low = estimate?.low, high = estimate?.high;
  if (typeof low !== 'number' || typeof high !== 'number' ||
      !Number.isFinite(low) || !Number.isFinite(high) || low <= 0 || low > high) return null;
  const priced = typeof price === 'number' && Number.isFinite(price) && price > 0;
  return {low, high, below:priced && price < low, above:priced && price > high, priced};
}

export function ValuationRange({estimate,price}: {estimate:EstimateRange|undefined|null;price:number|undefined|null}) {
  const range=valuationComparison(estimate,price);
  if(!range)return estimate?'依据不足':'待测算';
  const tone=range.below?'below':range.above?'above':range.priced?'inside':'unpriced';
  return <span className={'valuation-range--'+tone}>¥{format.format(range.low)}–{format.format(range.high)}</span>;
}
