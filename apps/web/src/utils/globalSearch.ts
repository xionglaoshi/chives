import type { BotSummary } from '@chives/server/protocol';
import installGuide from '../../../../INSTALL.md?raw';
import settingsGuide from '../../../../docs/设置中心.md?raw';
import botGuide from '../../../../docs/专家内核与配置.md?raw';
import researchGuide from '../../../../docs/投研工具.md?raw';
import commands from '../../../../packages/chives-terminal/chives_terminal/command-reference.json';
import { sections } from '../components/SettingsNav';
import { settingsEnglish } from '../components/deskLanguage';
import { helpItems } from './helpTopics';
import { conversationHash, workbenchTools } from './routes';

export type SearchGroup = '设置' | '帮助文档' | '命令' | '工作台' | 'Bot';
type Destination = { hash: string } | { body: string; source: string } | { command: string; terminal: boolean };
export interface SearchEntry {
  group: SearchGroup;
  title: string;
  summary: string;
  keywords?: string;
  destination: Destination;
}

const settingTerms: Record<string, string> = {
  account: '头像 姓名 邮箱 电话', risk: '问卷 用户画像 风险承受能力',
  models: '思考强度 推理强度 快速模式 处理速度 默认模型 DeepSeek OpenAI Codex GPT API Key reasoning effort fast',
  history: '历史记录 记忆 股票', messages: '通知 提醒 勿扰', channels: '微信 企业微信 飞书 Telegram Slack Discord',
  appearance: '主题 字体 字号 时区 语言 颜色 涨跌配色', chat: '思考摘要 工具调用 排队 消息中断',
  permissions: '工作区写入 查询本地资料库 自动分析', capabilities: '第三方工具 MCP',
  tasks: '定时任务 计划 调度', kernels: 'dsh 版本', backup: '导出 导入 恢复 迁移', updates: '检查更新 升级'
};

// Split only at real Markdown headings, preserving fenced examples in the result.
function documentSections(file: string, markdown: string): SearchEntry[] {
  const entries: SearchEntry[] = [];
  let title = file, body: string[] = [], fence = '';
  function flush() {
    const content = body.join('\n').trim();
    if (content) entries.push({group:'帮助文档', title, summary:file, destination:{body:content, source:file}});
    body = [];
  }
  for (const line of markdown.split(/\r?\n/)) {
    const marker = /^\s{0,3}(`{3,}|~{3,})/.exec(line)?.[1];
    if (marker && !fence) fence = marker;
    else if (marker && marker.startsWith(fence) && line.trim() === marker) fence = '';
    const heading = !fence && /^#{1,3}\s+(.+)$/.exec(line);
    if (heading) { flush(); title = heading[1]!; }
    else body.push(line);
  }
  flush();
  return entries;
}

const catalog: SearchEntry[] = [
  ...sections.flatMap(section => section.items.map(([id, title, summary]): SearchEntry => ({
    group:'设置', title:title!, summary:summary!, keywords:[id, section.label, settingTerms[id!], ...(settingsEnglish[id!] ?? [])].join(' '),
    destination:{hash:'#/settings?tab='+id}
  }))),
  ...Object.entries(workbenchTools).map(([tool, title]): SearchEntry => ({group:'工作台', title, summary:'打开工作台页面', destination:{hash:'#/workspace/'+tool}})),
  {group:'工作台',title:'人才市场',summary:'查看、聘用与解聘 Bot',destination:{hash:'#/bots'}},
  ...[commands.chat, commands.shell].flatMap((items, i) => Object.entries(items).map(([command, description]): SearchEntry => ({
    group:'命令',title:command,summary:description, keywords: i ? '终端 shell CLI' : '终端会话 斜杠 slash CLI',
    destination:{command,terminal:i === 1}
  }))),
  ...helpItems.map(([title, body]): SearchEntry => ({group:'帮助文档',title,summary:'设置中心 · 常见问题',destination:{body,source:'设置中心 · 常见问题'}})),
  ...documentSections('INSTALL.md', installGuide),
  ...documentSections('docs/设置中心.md', settingsGuide),
  ...documentSections('docs/专家内核与配置.md', botGuide),
  ...documentSections('docs/投研工具.md', researchGuide)
];

function normalize(text: string) {
  return text.normalize('NFKC').toLowerCase().trim().replace(/\s+/g, ' ');
}

export function searchEntries(query: string, bots: readonly BotSummary[]): SearchEntry[] {
  const q = normalize(query);
  if (!q) return [];
  const botEntries = bots.map((bot): SearchEntry => ({
    group:'Bot',title:bot.name,summary:bot.role || '打开对话',keywords:bot.id,destination:{hash:conversationHash(bot.id)}
  }));
  const terms = q.split(' ');
  const scored = [...catalog, ...botEntries].map(entry => {
    const title = normalize(entry.title), keywords = normalize(entry.keywords ?? '').split(' ');
    const summary = normalize(entry.summary);
    const body = 'body' in entry.destination ? normalize(entry.destination.body) : '';
    const group = normalize(entry.group);
    let score = Number(title === q) * 100 + Number(title.startsWith(q)) * 12;
    for (const term of terms) {
      const weight = keywords.includes(term) ? 44 : title.includes(term) ? 30 : group.includes(term) ? 15
        : keywords.some(word => word.includes(term)) ? 12 : summary.includes(term) ? 9 : body.includes(term) ? 2 : 0;
      if (!weight) return {entry,score:0};
      score += weight;
    }
    return {entry,score};
  });
  return scored.filter(item => item.score).sort((a,b) => b.score-a.score).map(item => item.entry);
}
