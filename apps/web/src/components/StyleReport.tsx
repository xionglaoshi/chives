import {useExpertAttachment,type AskExpert} from './useExpertAttachment';
import {appPath} from '../appPath';
import {InvestorSurveyComparison} from './InvestorSurveyComparison';
import './style-report.css';

type Person={reason?:string;webReleaseEligible:boolean;id:string;name:string;style:string;bio:string;portrait:string;portraitSource:string;portraitCredit:string;portraitLicense:string;portraitLicenseUrl:string;portraitModification:string;baike:string;evidence:string[];difference:string};
type Comparison={n:number;period:string;peerGroup:string;percentile:number;topPercent:number;source:string};
type Dimension={id:string;title:string;low:string;high:string;value:number|null;reading:string;evidence:string[];comparison:Comparison|null};
type CardPosition={kind:'scale';value:number;label:string;low:string;high:string;comparison:Comparison|null};
const neutralPosition:CardPosition={kind:'scale',value:50,label:'倾向暂不明确 · 中性位置',low:'偏向一端',high:'偏向另一端',comparison:null};
function PositionBar({position}:{position:CardPosition|null|undefined}){
 const p=position?.kind==='scale'?position:neutralPosition;
 const compare=p.comparison;
 return <div className="ir-card-position"><small>{p.label}</small><div role="img" aria-label={'问卷量表位置 '+p.value+' / 100'} className="ir-track"><i style={{left:p.value+'%'}}/></div><div className="ir-ends"><span>{p.low}</span><span>{p.high}</span></div>
 {compare&&<p>在{compare.peerGroup}中约处于第 {compare.percentile} 百分位。<a href={compare.source} target="_blank" rel="noreferrer">{compare.period} · {compare.n} 人</a></p>}</div>;
}
export type Report={investmentStyle?:string;styleCards?:{featured:string[];items:{id:string;title:string;reading:string;position?:CardPosition|null}[];clarify:string[]};answered:number;risk:{grade:number|null;flags:string[]};dimensions:Dimension[];match:{kind:string;reason:string;people:Person[]}};
const official='https://www.amac.org.cn/xwfb/hydt/202005/t20200513_18820.html';
function RiskMap({dimensions}:{dimensions:Dimension[]}) {
  const will=dimensions.find(d=>d.id==='riskAppetite')?.value;
  const room=dimensions.find(d=>d.id==='capitalFlexibility')?.value;
  if(will==null||room==null)return null;
  const note=will-room>=20?'你愿意承担的波动，比这笔钱的条件允许的更高。可以先标出最早的用款日，再判断自己能等多久。':
    room-will>=20?'资金给你留了余地，但你对回撤更敏感。可把心理上能守住的边界也写进计划。':
    '这笔钱的条件与你对波动的接受度较接近。下一次明显回撤时，可以用真实感受复核这次判断。';
  return <figure className="ir-risk-map"><figcaption><h5>敢冒的险，和承担得起的险</h5><p>{note}</p></figcaption>
    <div role="img" aria-label={'资金余地 '+room+'，波动接受度 '+will+'，两轴满分均为100'}><small>资金余地大 ↑</small>
    <div className="ir-plane"><i style={{left:will+'%',bottom:room+'%'}}/></div><div className="ir-ends"><span>余地小</span><span>更敢冒险 →</span></div></div></figure>;
}
// Older reports stored the entire reading as one paragraph. Keep the original wording.
function overviewParagraphs(text:string){
 const lines=text.trim().split(/\n+/).map(s=>s.trim()).filter(Boolean);
 if(lines.length===2||lines.length===3)return lines;
 let parts=lines.length>3?lines:(lines[0]??'').split(/(?<=[。！？][”」』]?)\s*(?![”」』])/u).filter(Boolean);
 if(parts.length===1)parts=parts[0]!.split(/(?<=[，；,;])\s*/u).filter(Boolean);
 if(parts.length===1&&parts[0]!.length>=100){
  const chars=Array.from(parts[0]!),mid=Math.ceil(chars.length/2);
  return [chars.slice(0,mid).join(''),chars.slice(mid).join('')];
 }
 if(parts.length<2)return parts;
 const count=parts.length>2&&text.length>=300?3:2;
 const paragraphs:string[]=[];
 for(let remaining=count;remaining>1;remaining--){
  const target=parts.join('').length/remaining;
  let size=parts[0]!.length,cut=1;
  while(cut<=parts.length-remaining&&Math.abs(size+parts[cut]!.length-target)<Math.abs(size-target)){
   size+=parts[cut]!.length;cut++;
  }
  paragraphs.push(parts.slice(0,cut).join(''));parts=parts.slice(cut);
 }
 return [...paragraphs,parts.join('')];
}
type Section='综合解读'|'您像谁'|'风格解读';
const personalEvidence='请先读我的用户画像 USER.md，按其中的资料地图查阅本次已提交问卷的原答（investor.json 的 answers），对照题干、选项文字和我的备注。结合相关自述、补充资料及后续更正，再解读附件。引用时简述题意和我的实际回答；遇到矛盾就指出来。原答缺失或读不到时，请说明哪项判断缺依据，不要替我补答。';
const questions:Record<Section,string>={
  综合解读:'请从资金用途、最早用款时间、可承担的亏损、下跌时的实际反应中挑出关键回答，分别解释我的财务承受能力和心理接受度。用这些依据说明报告为何给出这个风险等级和投资风格，最后指出一个最值得我复核的问题。',
  您像谁:'请逐一介绍附件中三位投资人的代表经历与投资方法，生平事实请核对可靠来源。每人选取我在估值、选股、卖出或处理回撤时的一条相关原答，说明 Chives 为什么认为我们相似、哪一点还有差距，以及我可以借鉴的一种做法。区分我说过的偏好和有实际经历印证的行为。',
  风格解读:'请挑出最影响我决策的三张风格卡，逐张写清“我怎么答、卡片怎么解释、实际投资时可能怎样表现”。用买入、持有或遇到下跌的具体情境，说明哪些倾向相互支持、哪些可能冲突，最后整理成三条下次交易前能自问的问题。'
};
function peerNote(c:Comparison|null|undefined){
  return c?'对照：'+c.peerGroup+'，第 '+c.percentile+' 百分位（'+c.period+'，'+c.n+' 人）。来源：'+c.source:'';
}
function sectionText(section:Section,report:Report,overview:string){
  if(section==='综合解读')return ['风险承受能力（Chives 研究参考）：'+(report.risk.grade?'C'+report.risk.grade:'待补充'),
    '投资风格：'+(report.investmentStyle??'无明确风格'),...report.risk.flags,...overviewParagraphs(overview),'参考文件：'+official];
  if(section==='您像谁')return [report.match.reason,...report.match.people.flatMap(p=>[
    '## '+p.name,p.style,p.bio,p.reason,...(p.evidence??[]),p.difference,p.baike
  ])];
  if(report.styleCards)return [...report.styleCards.items.flatMap(card=>{
    const pos=card.position?.kind==='scale'?card.position:neutralPosition;
    return ['## '+card.title,card.reading,pos.label+'；问卷量表 '+pos.value+'/100（'+pos.low+' → '+pos.high+'）',peerNote(pos.comparison)];
  }),...(report.styleCards.clarify??[])];
  return report.dimensions.flatMap(d=>['## '+d.title,d.reading,d.value==null?'位置待补充':'问卷量表 '+d.value+'/100（'+d.low+' → '+d.high+'）',peerNote(d.comparison)]);
}
export function StyleReport({report,overview,example=false,updated,onAskExpert}:{report:Report;overview:string;example?:boolean;updated?:string;onAskExpert:AskExpert}){
  const {risk,match}=report;
  const {asking,askError,attach}=useExpertAttachment(onAskExpert);
  function heading(section:Section){
    function ask(){
      const kind=example?'示例报告（虚构答卷）':'个人评估报告';
      const text=['# '+section,kind,updated?'评估时间：'+updated:'','作答题数：'+report.answered,...sectionText(section,report,overview)].filter(Boolean).join('\n\n');
      const evidence=example?'这是虚构示例。请仅使用附件中示例答题者的材料，以下“我”均指示例人物。请注明示例，缺少的原答标为未知，不读取我的个人资料。':personalEvidence;
      const prompt=evidence+'\n\n'+questions[section];
      void attach(section,new File([text+'\n'],kind+'-'+section+'.md',{type:'text/markdown'}),prompt);
    }
    return <div className="ir-section-heading"><h4>{section}</h4><button type="button" disabled={asking!==null} onClick={ask}>{asking===section?'准备中…':'问AI'}</button></div>;
  }
  return <article className="investor-report">
    <header><small>{example?'示例报告 · 虚构答卷':'个人评估报告 · '+report.answered+' 题作答'}</small><h3>{example?'一份风格评估是什么样的':'您的投资风格'}</h3></header>
    {askError&&<p role="alert">{askError}</p>}
    <section className="ir-overview">{heading('综合解读')}
    <div className="ir-conclusions"><details><summary>风险承受能力：{risk.grade?'C'+risk.grade:'待补充'}</summary>
      <p>这是 Chives 根据您的资金条件、用款期限和亏损接受度给出的研究参考。正式适当性评估由相应募集机构完成。</p>
      {risk.flags.map(f=><p key={f}>{f}</p>)}<a href={official} target="_blank" rel="noreferrer">中基协《基金募集机构投资者适当性管理实施指引（试行）》 ↗</a>
    </details><div>投资风格：{report.investmentStyle??'无明确风格'}</div></div>
    {overviewParagraphs(overview).map((p,i)=><p key={i}>{p}</p>)}</section>
    <section>{heading('您像谁')}<p>{match.reason}</p>{match.people.filter(p=>p.reason).map(p=><p key={p.id}><strong>{p.name}</strong>　{p.reason}</p>)}{match.people.map(p=><div key={p.id} className="ir-person">
      {p.portrait&&<a className="ir-portrait" href={p.portraitSource} target="_blank" rel="noreferrer"
        aria-label={p.name+'头像来源：'+p.portraitCredit+' · '+p.portraitLicense}
        title={[p.portraitCredit,p.portraitLicense,p.portraitModification].join(' · ')}>
        <img src={appPath(p.portrait)} alt={p.name} width="88" height="88" loading="lazy"/></a>}
      <div><h5><a className="ir-person-name" href={p.baike} target="_blank" rel="noreferrer" title={'在百度百科查看'+p.name}>{p.name}</a></h5>
        <p>{p.bio}</p></div></div>)}</section>
    {report.styleCards?<section>{heading('风格解读')}
      <div className="ir-grid">{report.styleCards.items.map(card=><div className="ir-dimension" key={card.id}><h5>{card.title}</h5><p>{card.reading}</p>{card.id==='C13'&&<InvestorSurveyComparison/>}<PositionBar position={card.position}/></div>)}</div></section>:<section>{heading('风格解读')}<p>圆点标出答案在每条量表上的位置。两端代表不同习惯。人群排名需要同版问卷的真实样本。</p><RiskMap dimensions={report.dimensions}/><div className="ir-grid">{report.dimensions.map(d=><div className="ir-dimension" key={d.id}>
      <h5>{d.title}</h5><p>{d.reading}</p>{d.value!==null&&<div role="img" aria-label={d.title+'，量表位置 '+d.value+' / 100'}><div className="ir-track"><i style={{left:d.value+'%'}}/></div><div className="ir-ends"><span>{d.low}</span><span>{d.high}</span></div></div>}
      {d.comparison&&<p>在{d.comparison.peerGroup}中约处于第 {d.comparison.percentile} 百分位（同分取中位）。<a href={d.comparison.source} target="_blank" rel="noreferrer">{d.comparison.period} · {d.comparison.n} 人</a></p>}
      </div>)}</div></section>}
    {!report.styleCards&&<InvestorSurveyComparison/>}
  </article>;
}
