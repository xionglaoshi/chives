export const workbenchTools = { 
  market: '行情看板',
  holdings: '用户持仓',
  trends: '热门榜单',
  strategies: '策略市场',
  portrait: '风格评估',
 } as const;
export type WorkbenchTool = keyof typeof workbenchTools;
export type AppRoute =
  | { name: 'workspace'; tool: WorkbenchTool }
  | { name: 'overview' }
  | { name: 'settings' }
  | { name: 'profile'; botId: string }
  | { name: 'conversation'; botId: string | null };

function decode(value: string): string | null {
  try {
    const decoded = decodeURIComponent(value);
    return decoded === '' ? null : decoded;
  } catch {
    return null;
  }
}

/** Parses `#/bots`, `#/settings`, `#/bot/<id>`, and `#/bot/<id>/profile`. */
export function readRoute(hash: string): AppRoute {
  if (hash === '' || hash === '#' || hash === '#/') return {name:'workspace',tool:'market'};
  const tool = hash.replace(/^#\/workspace\//, '');
  if (hash.startsWith('#/workspace/') && Object.hasOwn(workbenchTools,tool)) return {name:'workspace',tool:tool as WorkbenchTool};
  if (hash === '#/bots' || hash === '#/bots/') return { name: 'overview' };
  if (hash === '#/settings' || hash === '#/settings/' || hash.startsWith('#/settings?tab=')) return { name: 'settings' };
  if (!hash.startsWith('#/bot/')) return { name: 'conversation', botId: null };
  const rest = hash.slice('#/bot/'.length);
  const slash = rest.indexOf('/');
  if (slash < 0) {
    return { name: 'conversation', botId: decode(rest) };
  }
  const botId = decode(rest.slice(0, slash));
  if (botId === null) return { name: 'conversation', botId: null };
  return rest.slice(slash) === '/profile'
    ? { name: 'profile', botId }
    : { name: 'conversation', botId };
}

export function routeHash(route: AppRoute): string {
  if (route.name === 'workspace') return '#/workspace/'+route.tool;
  if (route.name === 'overview') return '#/bots';
  if (route.name === 'settings') return '#/settings';
  if (route.name === 'profile') return `#/bot/${encodeURIComponent(route.botId)}/profile`;
  return route.botId === null ? '#/' : `#/bot/${encodeURIComponent(route.botId)}`;
}

export function conversationHash(botId: string): string {
  return routeHash({ name: 'conversation', botId });
}

export function profileHash(botId: string): string {
  return routeHash({ name: 'profile', botId });
}

export function settingsHash(): string {
  return '#/settings';
}

export function routeKey(route: AppRoute): string {
  return route.name === 'conversation' && route.botId === null
    ? 'conversation'
    : routeHash(route);
}
