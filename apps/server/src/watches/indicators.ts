/** Decisions use consecutive, completed five-minute bars, without price adjustment. */
export interface Bar {time:string;open:number;high:number;low:number;close:number;volume_shares:number|null;amount_yuan?:number|null}
export interface Crossing {name:string; before:number;after:number;levelBefore:number;levelAfter:number;up:boolean}
export interface MarketTick {quote_time:string;price:number;change_pct:number|null;volume_ratio:number|null}
