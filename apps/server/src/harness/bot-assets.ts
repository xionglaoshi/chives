import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import type { BotCatalog, BotManifest } from '../bots/index.js';

import {installed as connections} from '../settings/mcp-connections.js';

export const localTools = ['read_skill','save_report','recall_memory','remember','inspect_database','find_research'];
const equityTools: Record<string,{label:string;bots:string[]}> = JSON.parse(
  readFileSync(resolve(import.meta.dirname,'../../../../config/equity-tools.json'),'utf8'));
export const researchServers = ['cn_market','cn_research','cn_extra','tavily','scrape','strategy'];
export interface AssetProfile {
  skillMode?: 'all' | 'selected';
  skills: string[]; mcp: string[]; tools: string[]; databases: string[];
  instructions: string; preset: string;
}
export function assetPaths(data: string, id: string) {
  const dir = join(data,'bots',id,'profile');
  mkdirSync(dir,{recursive:true,mode:0o700});
  return {dir, agents:join(dir,'AGENTS.md'), config:join(dir,'resources.json')};
}
const deskDescriptions:Record<string,string>={employee_roster:'在岗名册',handoff_request:'转交客户委托',technical_watch:'持仓与点名技术盯盘',briefing_inputs:'简报数据与时间覆盖',customer_behavior:'客户交易行为摘要',portfolio_snapshot:'持仓证券',user_watchlist:'用户关注',published_valuation:'已发布个股估值'};
function deskTools(id:string){
  const names=['employee_roster','handoff_request'];
  if(id==='ceo')names.push('customer_behavior','read_user_attributes','find_user_memory','propose_user_attribute','propose_customer_note');
  if(['cio','cro','trader','analyst'].includes(id))names.push('portfolio_snapshot');
  if(['ceo','cio','cro','analyst'].includes(id))names.push('user_watchlist');
  if(['cio','cro'].includes(id))names.push('briefing_inputs');
  if(['cio','analyst'].includes(id))names.push('published_valuation');
  if(id==='trader')names.push('technical_watch');
  return names;
}
export function assetOptions(data: string, bot: BotManifest, catalog: BotCatalog) {
  const library = join(data,'library');
  mkdirSync(library,{recursive:true});
  const files = readdirSync(library,{withFileTypes:true}).filter(f=>f.isFile() && /^[\w-]+\.sqlite$/.test(f.name)).map(f=>f.name);
  const installed = resolve(data) === resolve(import.meta.dirname,'../../../../data');
  const bundled = installed ? ['strategy-results','market-monitor'].filter(id => existsSync(join(data,'../runtime',
    id==='strategy-results'?'strategy-hub/strategy.sqlite':'market/market.db'))) : [];
  const selectable = bot.id === 'ceo' || bot.persona === 'bots/_shared/specialist.md'
    ? catalog.mcp.filter(name => name !== 'paper_broker' || bot.trading_guard)
    : [...new Set([...bot.mcp,...researchServers.filter(s=>catalog.mcp.includes(s))])];
  const external=connections(data);
  return {skills:catalog.skills, mcp:[...selectable,...external.map(e=>e.id)],
    tools:[...deskTools(bot.id),...localTools,...(bot.id==='ceo'?['read_local_document']:[]),...(bot.id==='research'?['publish_research']:[]),'browser_research',...Object.keys(equityTools)], toolNames:{...deskDescriptions,read_local_document:'读取本机文档',write_local_document:'写入本机文档',read_user_attributes:'读取客户属性',find_user_memory:'查找长期记忆',propose_user_attribute:'拟定属性变更',propose_customer_note:'拟定客户记忆变更','chives-databases':'全部 Chives 数据库（只读）',...Object.fromEntries(external.map(e=>[e.id,e.name+(e.enabled?'':'（已停用）')])),find_research:'查询团队的市场研究',publish_research:'发布共享市场研究',browser_research:'浏览器自动化（Playwright · Chromium）',...Object.fromEntries(Object.entries(equityTools).map(([k,v])=>[k,v.label]))}, databases:['bot-library',...(bot.id==='ceo'?['chives-databases']:[]),...bundled,...files]};
}
export function assets(data: string, bot: BotManifest): AssetProfile {
  const p=assetPaths(data,bot.id);
  if (!existsSync(p.agents)) {
    const initial = bot.persona === 'bots/_shared/specialist.md'
      ? '# Bot 个人指令\n\n按当前 Bot 职责执行。\n'
      : '# '+bot.name+'\n\n'+bot.role+'\n';
    writeFileSync(p.agents,initial,{mode:0o600});
  }
  const priorInstructions = readFileSync(p.agents, 'utf8');
  // Refresh the generated profile heading when a Bot's registered name changes.
  const generated = '# ' + bot.name + '\n\n' + bot.role + '\n';
  const instructions = /^# [^\n]+\n\n/.test(priorInstructions) &&
    priorInstructions.slice(priorInstructions.indexOf('\n\n') + 2) === bot.role + '\n'
    ? generated : priorInstructions;
  if (instructions !== priorInstructions) writeFileSync(p.agents, instructions);
  const presetPath=resolve(import.meta.dirname,'../../../../bots',bot.id,'task-prompt.md');
  const preset=existsSync(presetPath)?readFileSync(presetPath,'utf8').trim():'';
  const saved=existsSync(p.config) ? JSON.parse(readFileSync(p.config,'utf8')) : {};
  const available=new Set(connections(data).map(e=>e.id));
  if(Array.isArray(saved.mcp))saved.mcp=saved.mcp.filter((id:string)=>!id.startsWith('ext_')||available.has(id));
  if (bot.id === 'ceo') {
    const full = assetOptions(data,bot,{skills:[],mcp:bot.mcp});
    const allowedTools = [...deskTools(bot.id),...localTools.filter(tool => !['inspect_database', 'save_report'].includes(tool)), 'read_local_document',
      'browser_research'];
    return {skillMode:'selected', skills:bot.skills, mcp:bot.mcp, tools:allowedTools.filter(tool => full.tools.includes(tool)),
      databases:[], preset, instructions:''};
  }
  return {skillMode: bot.persona === 'bots/_shared/specialist.md' || Array.isArray(saved.skills) || bot.skills.length ? 'selected' : 'all', skills:bot.skills, mcp:bot.mcp, tools:[...deskTools(bot.id),...localTools,...(bot.id==='research'?['publish_research']:[]),...Object.keys(equityTools).filter(k=>equityTools[k]!.bots.includes(bot.id))], databases:['bot-library'], preset, ...(['cio','cro','trader','analyst'].includes(bot.id) ? {} : saved),
    instructions};
}
export function saveAssets(data:string, bot:BotManifest, profile:AssetProfile) {
  const p=assetPaths(data,bot.id);
  const {instructions,...resourceConfig}=profile;
  for (const [file,body] of [[p.agents,instructions],[p.config,JSON.stringify(resourceConfig,null,2)]] as const) {
    const temp=file+'.'+randomUUID(); writeFileSync(temp,body,{mode:0o600});renameSync(temp,file);
  }
}
