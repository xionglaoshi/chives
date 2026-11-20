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
export function assetOptions(data: string, bot: BotManifest, catalog: BotCatalog) {
  const library = join(data,'library');
  mkdirSync(library,{recursive:true});
  const files = readdirSync(library,{withFileTypes:true}).filter(f=>f.isFile() && /^[\w-]+\.sqlite$/.test(f.name)).map(f=>f.name);
  const installed = resolve(data) === resolve(import.meta.dirname,'../../../../data');
  const bundled = installed ? ['strategy-results','market-monitor'].filter(id => existsSync(join(data,'../runtime',
    id==='strategy-results'?'strategy-hub/strategy.sqlite':'market/market.db'))) : [];
  const selectable = bot.id === 'chives' || bot.persona === 'bots/_shared/specialist.md'
    ? catalog.mcp.filter(name => name !== 'paper_broker' || bot.trading_guard)
    : [...new Set([...bot.mcp,...researchServers.filter(s=>catalog.mcp.includes(s))])];
  const external=connections(data);
  return {skills:catalog.skills, mcp:[...selectable,...external.map(e=>e.id)],
    tools:[...localTools,...(bot.id==='chives'||bot.id==='research'?['publish_research']:[]),'browser_research',...Object.keys(equityTools)], toolNames:{...Object.fromEntries(external.map(e=>[e.id,e.name+(e.enabled?'':'（已停用）')])),find_research:'查询团队的市场研究',publish_research:'发布共享市场研究',browser_research:'浏览器自动化（Playwright · Chromium）',...Object.fromEntries(Object.entries(equityTools).map(([k,v])=>[k,v.label]))}, databases:['bot-library',...bundled,...files]};
}
export function assets(data: string, bot: BotManifest): AssetProfile {
  const p=assetPaths(data,bot.id);
  if (!existsSync(p.agents)) {
    const initial = bot.persona === 'bots/_shared/specialist.md'
      ? '# Bot 个人指令\n\n按当前 Bot 职责执行。\n'
      : '# '+bot.name+'\n\n'+bot.role+'\n';
    writeFileSync(p.agents,initial,{mode:0o600});
  }
  const presetPath=resolve(import.meta.dirname,'../../../../bots',bot.id,'task-prompt.md');
  const preset=existsSync(presetPath)?readFileSync(presetPath,'utf8').trim():'';
  const saved=existsSync(p.config) ? JSON.parse(readFileSync(p.config,'utf8')) : {};
  const available=new Set(connections(data).map(e=>e.id));
  if(Array.isArray(saved.mcp))saved.mcp=saved.mcp.filter((id:string)=>!id.startsWith('ext_')||available.has(id));
  if (bot.id === 'chives') {
    const full = assetOptions(data,bot,{skills:[],mcp:bot.mcp});
    return {...saved, skillMode:'all', skills:[], mcp:[...bot.mcp,...(saved.mcp??[]).filter((id:string)=>available.has(id))], tools:full.tools, databases:full.databases,
      preset:saved.preset ?? preset, instructions:readFileSync(p.agents,'utf8')};
  }
  return {skillMode: bot.persona === 'bots/_shared/specialist.md' || Array.isArray(saved.skills) || bot.skills.length ? 'selected' : 'all', skills:bot.skills, mcp:bot.mcp, tools:[...localTools,...(bot.id==='research'?['publish_research']:[]),...Object.keys(equityTools).filter(k=>equityTools[k]!.bots.includes(bot.id))], databases:['bot-library'], preset, ...saved,
    instructions:readFileSync(p.agents,'utf8')};
}
export function saveAssets(data:string, bot:BotManifest, profile:AssetProfile) {
  const p=assetPaths(data,bot.id);
  const {instructions,...resourceConfig}=profile;
  for (const [file,body] of [[p.agents,instructions],[p.config,JSON.stringify(resourceConfig,null,2)]] as const) {
    const temp=file+'.'+randomUUID(); writeFileSync(temp,body,{mode:0o600});renameSync(temp,file);
  }
}
