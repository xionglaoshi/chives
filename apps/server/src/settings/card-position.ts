import {cardPercentile} from './style-norms.js';
import type {Profile,Question} from './interview-profile.js';

// These question options are already ordered from the low anchor to the high anchor.
const axes:Record<string,[string,string,string]> = {
 C02:['04','不到半年','至少五年'],C04:['15','没有新增资金','1,000 万元及以上'],
 C05:['26','较小亏损就不安','较大亏损才不安'],C07:['27','确定的结果','更大的盈亏波动'],
 C32:['89','每周不足一小时','每周至少十五小时']
};
// Per-question anchors describe the particular decision, not an investor population rank.
// null means this choice cannot locate the investor on that axis.
type Anchors=[question:string,low:string,high:string,positions:(number|null)[]];
const tendencies:Record<string,Anchors>={
 C01:['01','更看重保值','更看重短期获利',[0,null,null,null,100,null]],
 C06:['72','对急跌更敏感','对持续下跌更敏感',[0,100,null,50]],
 C08:['34','倾向减持','倾向增持',[25,0,null,50,100,null]],
 C09:['51','重公司价值','重市场走势',[0,25,0,null,100,null,null]],
 C10:['52','重当期分红','重再投资回报',[0,100,null,null,null]],
 C11:['53','等价格回落','等向上突破',[0,null,null,100,null]],
 C12:['57','倾向自己选股','倾向按指数配置',[0,null,100,100,50,null]],
 C13:['71','重经营和估值','重价格和资金走势',[100,100,0,0,null]],
 C14:['76','重经营表现','重股价趋势',[0,0,25,100,null,null]],
 C15:['74','因经营变化退出','按价格信号退出',[0,100,0,null]],
 C16:['60','重基本面','重上涨势头',[0,0,0,100,null,null,null,null]],
 C17:['43','多靠转述','多靠一手观察',[100,100,75,null,0]],
 C18:['46','先看市场表现','先核对经营数据',[100,100,null,0]],
 C19:['47','重外部评价','重交易条件',[null,100,0,null]],
 C20:['61','视为同一来源','视为多个来源',[0,25,75,100]],
 C21:['64','倾向立即行动','倾向等待核实',[0,25,75,100,null]],
 C22:['75','等预定条件','受市场气氛带动',[0,0,0,0,100,null]],
 C23:['79','倾向减少投入','倾向增加投入',[50,25,100,0,null]],
 C24:['77','按原规则执行','视情况调整',[0,100,null,null,null]],
 C26:['19','受现实条件限制','可自行调整',[0,0,25,25,100,null]],
 C27:['49','行业风险较分散','行业风险较集中',[100,50,0,null,null]],
 C28:['94','原计划可照常执行','依赖新增资金',[75,100,0,100,null]],
 C29:['36','持有时间较短','持有时间较长',[0,25,50,75,100,null]],
 C30:['93','单股上限较低','单股上限较高',[null,0,25,75,100]]
};
const calculatedAxes:Record<string,[string,string]>={
 C03:['全部容易动用','全部较难动用'],C25:['资金条件更宽裕','冒险意愿更强'],C31:['两项都未选择','两项都选择']
};
export function cardPosition(p:Profile,id:string,byId:Map<string,Question>,ready=true){
 const keyedAxis=axes[id]??tendencies[id];
 const [low,high]=keyedAxis?[keyedAxis[1],keyedAxis[2]]:calculatedAxes[id]??['偏低','偏高'];
 const neutral={kind:'scale' as const,value:50,low,high,label:'倾向暂不明确 · 中性位置',comparison:null};
 if(!ready)return neutral;
 const scale=(value:number,label:string,low:string,high:string)=>({kind:'scale' as const,value,label,low,high,comparison:cardPercentile(id,value)});
 const axis=axes[id];
 if(axis){
  const [qid,low,high]=axis,q=byId.get(qid)!,i=p.answers[qid]?.choice;
  return i===undefined?neutral:scale(Math.round(i*100/(q.options.length-1)),q.options[i]!,low,high);
 }
 if(id==='C03'){
  const weights=p.answers['11']?.allocation,indices=p.answers['17']?.choices;
  if(!weights||!indices||indices.includes(12))return neutral;
  const share=indices.reduce((s,i)=>s+(weights[i]??0),0);
  return scale(share,'自报一个月内较难变现的资产占 '+share+'%','全部容易动用','全部较难动用');
 }
 if(id==='C25'&&p.willingness!==null&&p.capacity!==null){
  const diff=p.willingness-p.capacity;
  return scale(Math.round((diff+100)/2),'资金条件 '+Math.round(p.capacity)+' 分 · 波动接受度 '+Math.round(p.willingness)+' 分','资金条件更宽裕','冒险意愿更强');
 }
 if(id==='C31'){
  const n=Number(p.answers['46']?.choice===1)+Number(p.answers['47']?.choice===1);
  return scale(n*50,'两道报表情境题中，您有 '+n+' 道选择了核对关键交易细节','两项都未选择','两项都选择');
 }
 const rule=tendencies[id];
 if(!rule)return neutral;
 const [qid,,,positions]=rule;
 const choice=p.answers[qid]?.choice;
 const value=choice===undefined?null:positions[choice];
 const label=choice===undefined?'':byId.get(qid)?.options[choice];
 if(value==null)return {kind:'scale' as const,value:50,low,high,label:[label,'倾向暂不明确 · 中性位置'].filter(Boolean).join(' · '),comparison:null};
 return scale(value,label??'',low,high);
}
