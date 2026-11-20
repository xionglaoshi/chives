import { readFileSync } from "node:fs";
import { basename } from "node:path";
import { z } from "zod";
import { referencePosition } from "./style-norms.js";

export interface StyleQuestion {
  id: string;
  group: string;
  title: string;
  options: string[];
  initial: boolean;
  followup?: string;
}
type TaggedQuestion = StyleQuestion & { tags?: string[][] };
type Vector = Record<string, number>;
export interface Investor {
  id: string;
  name: string;
  style: string;
  bio: string;
  baike: string;
  portrait: string;
  portraitSource: string;
  portraitSha256: string;
  portraitCredit: string;
  portraitLicense: string;
  portraitLicenseUrl: string;
  portraitModification: string;
  webReleaseEligible: boolean;
  weights: Vector;
  signals: string[];
}
function readPreset<T>(file: string): T {
  return JSON.parse(readFileSync(new URL("../../../../presets/" + file, import.meta.url), "utf8")) as T;
}
const questions = readPreset<TaggedQuestion[]>("style-assessment/questions-v2.json");
const { people } = readPreset<{ people: Investor[] }>("investor-styles/catalog.json");
export const questionBank: StyleQuestion[] = questions.map(({ tags: _privateLabels, ...q }) => q);
const byId = new Map(questions.map(q => [q.id, q]));

const singleAnswer = z.object({
  choice: z.number().int().nonnegative().optional(),
  note: z.string().trim().max(1500).optional(),
  skipped: z.boolean().optional(),
}).strict();
export const styleAnswersSchema = z.record(z.string(), singleAnswer).superRefine((answers, ctx) => {
  for (const [id, answer] of Object.entries(answers)) {
    const q = byId.get(id);
    if (!q || (answer.choice !== undefined && answer.choice >= q.options.length) ||
        (answer.skipped && answer.choice !== undefined)) {
      ctx.addIssue({ code: "custom", path: [id], message: "请使用本版题号及有效选项，跳过的题目不能同时有答案。" });
    }
  }
});
export type StyleAnswers = z.infer<typeof styleAnswersSchema>;
const capacityIds = ["08", "09", "10", "11", "12", "14"];
const willingIds = ["16", "17", "18", "19"];
function rawScale(a: StyleAnswers, ids: string[]) {
  const choices = ids.map(id => a[id]?.choice);
  return choices.every((x): x is number => x !== undefined)
    ? 100 * choices.reduce((s, v) => s + v, 0) / (3 * choices.length) : null;
}
const tidy = (x: number | null) => x === null ? null : Math.round(x * 100) / 100;
function riskResult(a: StyleAnswers) {
  const capacity = rawScale(a, capacityIds);
  const willingness = rawScale(a, willingIds);
  const flags: string[] = [];
  let cap = 5;
  if (a["11"]?.choice === 0) { cap = 1; flags.push("第11题显示任何本金损失都会影响必要支出，本账户最高参考 C1。"); }
  for (const [id, text] of [["08", "半年内有确定用款"], ["09", "备用金不足一个月"], ["12", "近期须偿还的借款或保证金"]] as const) {
    if (a[id]?.choice === 0) { cap = Math.min(cap, 2); flags.push("第" + id + "题显示" + text + "，本账户最高参考 C2。"); }
  }
  const timeConflict = a["08"]?.choice === 3 && a["14"]?.choice === 0;
  const paymentConflict = a["10"]?.choice === 3 && [0, 1].includes(a["15"]?.choice ?? -1);
  if (timeConflict) flags.push("第08题与第14题的用款时间不一致，请确认是否指同一笔钱。");
  if (paymentConflict) flags.push("第10题与第15题的支付能力不一致，请核实必要支出能否独立覆盖。");
  if (a["13"]?.choice === 0) flags.push("第13题提示收入和持仓可能随同一行业下行。");
  if ((a["54"]?.choice ?? -1) >= 2) flags.push("第54题涉及未公开消息，Bot 应优先查证公开披露。");
  if (capacity === null || willingness === null) flags.push("资金承受能力与主观接受度需分别答全，缺答时暂缓出档。");
  const grade = capacity === null || willingness === null || timeConflict || paymentConflict
    ? null : Math.min(5, cap, 1 + Math.floor(Math.min(capacity, willingness) / 20));
  return { grade, capacity: tidy(capacity), willingness: tidy(willingness), flags };
}

function evidence(a: StyleAnswers, ids: string[]): string[] {
  return ids.flatMap(id => {
    const q = byId.get(id);
    const choice = a[id]?.choice;
    const text = choice === undefined ? undefined : q?.options[choice];
    return text ? ["第" + id + "题 · " + text] : [];
  });
}
const historyIds = new Set(["25", "29", "31", "38"]);
const axes: Record<string,string> = { V: "value", G: "growth", I: "income", M: "macro", Q: "quant", T: "momentum", P: "passive" };
const axisNames: Record<string,string> = { V:"价值", G:"成长", I:"现金收入", M:"宏观配置", Q:"量化规则", T:"趋势与短线", P:"被动指数" };
type Item = { id:string; available: string[]; selected:string[] };
function observations(a: StyleAnswers): Item[] {
  return questions.flatMap(q => {
    const c = a[q.id]?.choice;
    const selected = c === undefined ? undefined : q.tags?.[c];
    return selected && q.tags ? [{ id: q.id, available:[...new Set(q.tags.flat())], selected }] : [];
  });
}
function vector(items: Item[], method: boolean) {
  const hits:Vector = {}, opportunities:Vector = {};
  for (const item of items) {
    for (const label of item.available.filter(x => (axes[x] === undefined) === method))
      opportunities[label] = (opportunities[label] ?? 0) + 1;
    for (const label of item.selected) hits[label] = (hits[label] ?? 0) + 1;
  }
  const v:Vector = {};
  for (const [label,n] of Object.entries(opportunities)) {
    const h = hits[label] ?? 0;
    v[label] = h > 0 ? (h + .5) / (n + 1) : 0;
  }
  const scale = method ? Math.max(0,...Object.values(v)) : Object.values(v).reduce((s,x) => s+x,0);
  if (scale > 0) for (const key of Object.keys(v)) v[key] = v[key]! / scale;
  return v;
}
const norm = (v:Vector) => Math.sqrt(Object.values(v).reduce((s,x) => s+x*x,0));
function styleSimilarity(v:Vector, candidate:Investor, methods:Vector) {
  const dot = Object.entries(v).reduce((s,[key,x]) => s+x*(candidate.weights[key] ?? 0),0);
  const cosine = dot/(norm(v)*norm(candidate.weights) || 1);
  const keys = new Set([...Object.keys(methods), ...candidate.signals]);
  let intersection=0, union=0;
  for(const key of keys) {
    const x=methods[key] ?? 0, y=Number(candidate.signals.includes(key));
    intersection+=Math.min(x,y);
    union+=Math.max(x,y);
  }
  return 0.65*cosine + 0.35*(union ? intersection/union : 0);
}
type PersonResult = Omit<Investor,"weights"|"signals"> & {evidence:string[];difference:string};
type Match = {kind:"single"|"mixed"|"insufficient"; reason:string; people:PersonResult[]};
function leading(v:Vector,items:Item[]) {
  const ranked=Object.entries(v).sort((a,b)=>b[1]-a[1]);
  const first=ranked[0];
  return first && first[1]>(ranked[1]?.[1] ?? 0) && items.filter(x=>x.selected.includes(first[0])).length>=2 ? first[0] : undefined;
}
function matchPeople(a: StyleAnswers, obs:Item[]): Match {
  const insufficient = (reason:string):Match => ({kind:"insufficient",reason,people:[]});
  const hist = obs.filter(i=>historyIds.has(i.id));
  const self = obs.filter(i=>i.id<="40"&&!historyIds.has(i.id));
  const method = obs.filter(i=>i.id>="57");
  if (hist.length<2 || self.length<6 || method.length<3) return insufficient("再补充买卖回顾、选股依据和交易习惯，才能分清认同的方法和实际做法。");
  const examples = [...(a["65"]?.note ?? "").normalize("NFKC").matchAll(/T([123])\s*[:：、.\-]?\s*([^T\n；;]{2,})/gi)];
  if ((a["65"]?.choice ?? 0)<2 || new Set(examples.filter(x=>/[\p{L}\p{N}]/u.test(x[2] ?? "")).map(x=>x[1])).size<2)
    return insufficient("请在第65题分别用 T1、T2 写下两笔不同交易的实际理由，便于核对回顾证据。");
  const h=vector(hist,false), s=vector(self,false), m=vector(obs,true);
  const v:Vector={};
  for (const [tag,name] of Object.entries(axes)) v[name]=.6*(h[tag]??0)+.4*(s[tag]??0);
  const ranked = people.flatMap(person => {
    const methodHits = obs.filter(i=>i.selected.some(t=>person.signals.includes(t)));
    const axisHits = obs.filter(i=>i.selected.some(t=>(person.weights[axes[t] ?? ""] ?? 0)>0));
    const ids = [...new Set([...methodHits,...axisHits].map(i=>i.id))];
    if (ids.length<2 || !methodHits.length) return [];
    if (person.id === "xu" && !(obs.some(i=>i.id!=="60"&&i.selected.includes("flow")) && (a["60"]?.choice===0||a["71"]?.choice===1))) return [];
    const { weights,signals, ...card }=person;
    const other=obs.find(i=>i.id<="40"&&i.selected.some(t=>axes[t] && !weights[axes[t]!]));
    const difference = other ? "侧重点不同的一题：" + evidence(a,[other.id])[0]
      : "这些答题只反映研究与交易习惯，尚缺同一市场阶段下的长期操作记录。";
    const result:PersonResult={...card, portrait:(card.webReleaseEligible ? "/api/" : "/api/internal/")+"style-portraits/"+encodeURIComponent(basename(card.portrait))+"?v="+card.portraitSha256.slice(0,12),
      evidence:evidence(a,ids.slice(0,3)), difference};
    return [{ result, score:styleSimilarity(v,person,m) }];
  }).sort((x,y)=>y.score-x.score);
  const [first,second]=ranked;
  if(!first || first.score<.60) return insufficient("目前的答案涉及多种方法，尚未形成足够明确的人物类比。");
  const selfLead=leading(s,self), histLead=leading(h,hist);
  if(selfLead && histLead && selfLead!==histLead) {
    return { kind:"mixed", reason:"您认同"+axisNames[selfLead]+"，最近的实际记录更接近"+axisNames[histLead]+"。可在下次交易后复核这种差异。",people:[] };
  }
  if(second && first.score-second.score<.08) return {kind:"mixed",reason:"两种方法都有直接依据，现有答案尚不足以分出唯一的人物。",people:[first.result,second.result]};
  return {kind:"single",reason:"买卖回顾与选股方法共同支持这项类比。",people:[first.result]};
}

interface Axis {
  id:string; title:string; question:string; low:string; high:string;
  values:(number|null)[]; readings:[string,string,string];
}
const anchors:Axis[]=[
  {id:'lossTolerance',title:'浮亏敏感度',question:'16',low:'较能坦然面对',high:'较早感到不安',values:[100,67,33,0],
   readings:['较大浮亏才影响睡眠。复盘时也要留意实际卖出的原因。','持续浮亏会影响你的感受，可把预案里的退出条件写清楚。','即使资金闲置，较小的浮亏也会影响睡眠。Bot 应先讲可能的损失。']},
  {id:'holdingPatience',title:'等待兑现的耐心',question:'18',low:'较快重新决策',high:'愿意长期复核',values:[0,33,67,100],
   readings:['长时间浮亏会较快改变你的计划，短期的验证信号对你更有用。','等待有期限，值得把经营假设和验证日期一起记录。','你愿意跨过较长的浮亏期，更需要区分股价波动与经营逻辑失效。']},
  {id:'concentration',title:'集中持仓倾向',question:'57',low:'分散个股敞口',high:'集中跟踪少数公司',values:[100,0,null,null],
   readings:['你倾向用许多小仓位限制单股损失，可再检查行业暴露是否集中。','你的组合做法介于集中跟踪和分散配置之间。','你倾向集中跟踪少数公司，单一公司判断错误对组合的影响更大。']},
  {id:'rumorRestraint',title:'消息到下单的距离',question:'53',low:'先交易再确认',high:'等待公开证据',values:[0,25,65,100,100],
   readings:['听到未经证实的消息，你可能先交易。Bot 应标明哪些信息仍缺公告。','你愿意先把传闻列入待查清单，下一步是找能证伪的公开事实。','面对市场传闻，你更愿意等待披露或不参与。']},
  {id:'researchVerification',title:'研究证据离源头多远',question:'49',low:'多经转述',high:'接近原始记录',values:[100,100,40,0,null],
   readings:['这次行业判断来自转述，结论可能受同一个消息源影响。','你参考研究或媒体报道，也可以继续追到原始数据。','你能指向订单、报价或原始公告。下一步可检查样本代表性。']},
  {id:'trendChasing',title:'上涨后的追价意愿',question:'28',low:'等待经营或价格依据',high:'看重盘面强度',values:[100,100,25,0],
   readings:['股价已经上涨时，你仍希望看到盈利或估值依据。','你会同时看经营线索和价格行为。','突破或题材轮动会引起你的兴趣。值得事先明确走势转弱后的复核条件。']},
];
export function buildStyleReport(a:StyleAnswers) {
  const risk=riskResult(a);
  const answered=questionBank.filter(q=>!a[q.id]?.skipped && (a[q.id]?.choice!==undefined || a[q.id]?.note)).length;
  const complete=(q:StyleQuestion)=>a[q.id]?.choice!==undefined;
  const form=questionBank.every(complete)?'full':
    questionBank.filter(q=>q.initial).every(complete)&&questionBank.filter(q=>!q.initial).every(q=>!a[q.id]?.note&&a[q.id]?.choice===undefined)?'core':null;
  function dimension(id:string,title:string,low:string,high:string,value:number|null,reading:string,ids:string[]){
    return {id,title,low,high,value:value===null?null:Math.round(value),reading,evidence:evidence(a,ids),
      comparison:value!==null&&form?referencePosition(id,value,form):null};
  }
  const dimensions=[
    dimension('riskAppetite','面对波动有多敢出手','倾向守住本金','愿承担较大波动',risk.willingness,
      risk.willingness===null?'还需完成四道波动情境题。':risk.willingness>=65?'你在波动情境中较愿意承担风险，要结合实际用款时间来解释。':risk.willingness<35?'面对回撤，你更看重本金稳定。':'你愿意在一定范围内接受回撤，超出预期时会重新考虑。',willingIds),
    dimension('capitalFlexibility','资金给你多少回旋余地','近期约束较多','用款压力较小',risk.capacity,
      risk.capacity===null?'还需补齐用款期限、备用金等资金条件。':risk.capacity>=65?'这笔资金的整体支付压力较小，仍应单独考虑硬性支出。':'必要开支和备用金会影响这笔钱能等待多久。',capacityIds),
    ...anchors.map(axis=>{
      const i=a[axis.question]?.choice;
      const value=i===undefined?null:axis.values[i]??null;
      return dimension(axis.id,axis.title,axis.low,axis.high,value,value===null?'这项回答不足以确定位置，可在复测时补充具体经历。':axis.readings[value<34?0:value>65?2:1],[axis.question]);
    })
  ];
  return {risk,dimensions,match:matchPeople(a,observations(a)),answered};
}
export type StyleReport=ReturnType<typeof buildStyleReport>;
