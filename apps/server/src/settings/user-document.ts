import {existsSync,readFileSync,writeFileSync,renameSync,linkSync,unlinkSync} from 'node:fs';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import type {Profile} from './interview-profile.js';
import {styleLabels} from './investment-style.js';

export const holdingsPath='profile/finance-portfolio.json';
export function ensureHoldings(dir:string){
 const move=(from:string,to:string)=>{
  const old=join(dir,'dsh',from),dest=join(dir,'profile',to);
  if(!existsSync(old))return;
  if(!existsSync(dest))linkSync(old,dest);
  if(!readFileSync(dest).equals(readFileSync(old)))throw Error('个人文件存在不同版本：'+from);
  unlinkSync(old);
 };
 move('finance-portfolio.json','finance-portfolio.json');
 move('finance-profile.json','finance-profile.json');
 const agents=join(dir,'dsh/AGENTS.md');
 if(existsSync(agents)){
  const text=readFileSync(agents,'utf8'),block=/<!-- dsh-finance:profile:start -->[\s\S]*?<!-- dsh-finance:profile:end -->/.exec(text)?.[0];
  if(block){
   const target=join(dir,'profile/finance-profile.md');
   if(!existsSync(target))writeFileSync(target,block+'\n',{flag:'wx',mode:0o600});
   if(readFileSync(target,'utf8').trim()!==block.trim())throw Error('过往偏好摘要存在不同版本');
   const rest=text.replace(block,'');
   if(rest.trim()){const tmp=agents+'.'+randomUUID();writeFileSync(tmp,rest,{mode:0o600});renameSync(tmp,agents);}else unlinkSync(agents);
  }
 }
 const dest=join(dir,holdingsPath);
 if(!existsSync(dest))writeFileSync(dest,JSON.stringify({version:1,updated_at:null,as_of:null,cash:null,positions:[]},null,2)+'\n',{flag:'wx',mode:0o600});
}

function brief(v:unknown){
 return (Array.isArray(v)?v.join('、'):typeof v==='string'?v:'').replace(/\s+/g,' ').trim();
}
export function refreshUserDocument(dir:string,p:Profile|null){
 const lines=['# 用户画像','','## 身份标签'];
 if(p){
  const f=p.facts;
  for(const tag of p.summary.identityTags??[])lines.push('- '+brief(tag));
  for(const [label,key] of [['身份','identity.roles'],['熟悉行业','expertise.sectors'],['股票投资经验','experience.stock_years'],['自报股票市值','capital.stock_value_band']] as const){
   if(brief(f[key]))lines.push('- '+label+'：'+brief(f[key]));
  }
  const allocation=f['wealth.allocation_pct'];
  if(allocation&&typeof allocation==='object'&&!Array.isArray(allocation))lines.push('- 直接持股占总资产：'+(allocation['直接持有的股票']??0)+'%（问卷估计）');
  lines.push('- 投资风格：'+styleLabels[p.investmentStyle]+'；风险承受能力：'+(p.grade?'C'+p.grade:'待补充')+'（Chives 评估）');
 }else lines.push('- 尚未评测');
 lines.push('','## 用户偏好');
 if(p){
  const rules=[...(p.confirmedPreferences??[]).slice(-5).map(s=>'本人确认：'+brief(s)),
   ...(p.summary.preferenceRules??[]).map(brief)];
  if(!p.summary.preferenceRules?.length)for(const [label,key] of [['选择投资工具','style.equity_vehicle'],['分析行业','bot.industry_entry'],['出现分歧','bot.disagreement_format'],['说明不确定性','bot.uncertainty'],['提醒重点','bot.risk_priority']] as const){
   if(brief(p.facts[key]))rules.push(label+'时：'+brief(p.facts[key]));
  }
  if(p.summary.preferenceRules?.length&&brief(p.facts['style.equity_vehicle']))rules.push('投资工具：'+brief(p.facts['style.equity_vehicle']));
  for(const [label,text] of [['研究偏好',p.summary.traits.research],['沟通偏好',p.summary.traits.communication]]){
   if(text&&text!=='待了解')rules.push(label+'：'+brief(text));
  }
  rules.push('选择证券时：'+brief(p.summary.traits.style));
  for(const rule of new Set(rules))lines.push('- '+rule);
 }else lines.push('- 待了解');
 lines.push('','## 按需读取','以下路径相对于本文件所在的 profile 目录。','- 问卷原答、资产比例、自述、补充资料：investor.json 的 answers、facts、selfDescription、materials。','- 风格报告、人物类比、偏好更正：investor.json 的 summary、confirmedPreferences、corrections。','- 实际持仓、现金及已记录成交：finance-portfolio.json。获持仓权限时通过 portfolio 工具读取。','- 历史手动投资档案：finance-profile.json；可读摘要：finance-profile.md。','- 用户资料与工作台设置：account-settings.json（含联系方式，仅在本人要求管理资料时使用）。','- 显示偏好、通知偏好和侧栏排序：appearance.json、notifications.json、sidebar-order.json。','- 未提交的问卷进度：interview-draft.json（作答期间生成）。','');
 const content=lines.join('\n'),dest=join(dir,'profile/USER.md');
 if(existsSync(dest)&&readFileSync(dest,'utf8')===content)return;
 const tmp=dest+'.'+randomUUID();writeFileSync(tmp,content,{flag:'wx',mode:0o600});renameSync(tmp,dest);
}
