export interface McpInfo {
  name: string;
  description: string;
}

/** Chinese labels for the MCP servers a bot can carry. `chives` is internal and hidden. */
export const MCP_INFO: Record<string, McpInfo> = {
  cn_data: { name: 'A 股行情与财务', description: 'A 股行情、财务报表与基础数据' },
  cn_extra: { name: '分钟线与快照', description: '分钟线、盘口快照与扩展行情' },
  cn_research: { name: '研报与一致预期', description: '卖方研报、评级与一致预期' },
  market_watch: { name: '大盘与板块', description: '指数、板块与市场宽度' },
  cn_watch: { name: 'Chives 雷达', description: '自选股告警与盘中观察' },
  tavily: { name: '网页检索', description: '公开网页检索与来源定位' },
  scrape: { name: '网页抓取', description: '读取公开网页正文' },
  profile: { name: '你的画像', description: '你主动写下的偏好与约束' },
  portfolio: { name: '你的持仓', description: '只在你问到时读取的持仓数据' },
  hub: { name: '信号与计划', description: '信号、计划与待确认事项' },
  paper_broker: { name: '模拟盘', description: '只在模拟盘演练，每次下单都要你批准' }
};

export function mcpInfo(server: string): McpInfo {
  return MCP_INFO[server] ?? { name: server, description: '外部数据与工具' };
}

/** Ordered MCP servers the UI should show; `chives` stays internal. */
export function visibleMcp(mcp: readonly string[]): string[] {
  return mcp.filter((server) => server !== 'chives');
}

export function mcpNames(mcp: readonly string[]): string[] {
  return visibleMcp(mcp).map((server) => mcpInfo(server).name);
}

/** `/Users/me/...` → `~/...`; other absolute paths are left alone. */
export function shortenWorkspacePath(path: string): string {
  const match = /^\/(?:Users|home)\/[^/]+/.exec(path);
  return match === null ? path : `~${path.slice(match[0].length)}`;
}

export function skillSummary(skills: readonly string[]): string {
  if (skills.length === 0) return '暂无';
  const shown = skills.slice(0, 3).join('、');
  return skills.length > 3 ? `${skills.length} 项 · ${shown} 等` : `${skills.length} 项 · ${shown}`;
}
