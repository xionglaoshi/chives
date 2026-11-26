import type { BotStatus, BotSummary } from '@chives/server/protocol';

export const BOT_STATUS_LABELS: Record<BotStatus, string> = {
  idle: '空闲',
  starting: '启动中',
  working: '工作中',
  awaiting_approval: '待批准',
  error: '出错'
};

export const BOT_STATUS_TONES: Record<BotStatus, string> = {
  idle: 'muted',
  starting: 'working',
  working: 'working',
  awaiting_approval: 'gold',
  error: 'error'
};

/** The idle label becomes a delegation wait when the bot has report-back children. */
export function botStatusLabel(
  bot: Pick<BotSummary, 'status' | 'waitingDelegations'>
): string {
  const waiting = bot.waitingDelegations ?? 0;
  if (bot.status === 'idle' && waiting > 0) return `等待委派结果（${waiting}）`;
  return BOT_STATUS_LABELS[bot.status];
}

const HASH_PREFIX = '#/bot/';

export function readBotIdFromHash(hash: string): string | null {
  if (!hash.startsWith(HASH_PREFIX)) return null;
  try {
    const value = decodeURIComponent(hash.slice(HASH_PREFIX.length));
    return value === '' ? null : value;
  } catch {
    return null;
  }
}

export function botHash(botId: string): string {
  return `${HASH_PREFIX}${encodeURIComponent(botId)}`;
}

export function defaultBotId(bots: BotSummary[]): string | null {
  return (
    bots.find((bot) => bot.permanent ?? (bot.id === 'ceo'))?.id ??
    bots.find((bot) => !bot.background)?.id ??
    bots[0]?.id ??
    null
  );
}

export function isBotRunning(bot: BotSummary): boolean {
  return (
    bot.runningTaskId !== null ||
    bot.status === 'working' ||
    bot.status === 'starting' ||
    bot.status === 'awaiting_approval'
  );
}
