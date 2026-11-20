import type { BotPanel } from '@chives/server/protocol';

export const STRATEGY_PANEL_PREFIX = 'strategy:';

export function strategyIdOfPanel(panel: BotPanel): string | null {
  return panel.startsWith(STRATEGY_PANEL_PREFIX) ? panel.slice(STRATEGY_PANEL_PREFIX.length) : null;
}

/** Strategy display names; unknown ids fall back to the id so new strategies still work. */
export function strategyLabel(id: string): string {
  if (id === 'zhushenglang') return '主升浪';
  return id;
}

export function panelLabel(panel: BotPanel): string {
  const strategyId = strategyIdOfPanel(panel);
  if (strategyId !== null) return strategyLabel(strategyId);
  if (panel === 'market') return '行情';
  if (panel === 'portfolio') return '持仓';
  return '盯盘';
}
