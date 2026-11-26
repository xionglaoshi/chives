import { z } from 'zod';
import { AppError } from '../errors.js';
import type { Store } from '../store/index.js';
import { DEFAULT_ENTRY_BOT_ID, type BotRegistry } from './registry.js';

import { WATCH_TRADER_ID, botHasWatches } from './types.js';

const permanentIds = new Set([DEFAULT_ENTRY_BOT_ID, 'cio', 'cro', WATCH_TRADER_ID, 'analyst']);
export const isPermanentBot = (id: string): boolean => permanentIds.has(id);

const key = 'bots.hired.v1';

export function transferActiveWatches(store: Store, registry: BotRegistry, now: Date): void {
  const trader = registry.get(WATCH_TRADER_ID);
  if (!trader || !botHasWatches(trader)) return;
  const plan = store.db.prepare("SELECT id FROM watches WHERE status='active' AND bot_id<>? AND expires_at>?").all(trader.id, now.toISOString());
  if (!plan.length) return;
  // Persist the successor's employment before transferring plans. A failed transfer can be retried.
  const prior = store.settings.get<string[]>(key) ?? [DEFAULT_ENTRY_BOT_ID];
  if (!prior.includes(trader.id)) store.settings.set(key, [...prior, trader.id]);
  store.db.prepare("UPDATE watches SET bot_id=? WHERE status='active' AND bot_id<>? AND expires_at>?")
    .run(trader.id, trader.id, now.toISOString());
}
const selection = z.object({
  expected: z.record(z.string(), z.boolean()),
  hiredIds: z.array(z.string()),
}).strict();

/** One local roster, shared by all clients. Unregistered IDs cannot acquire work. */
export class BotEmployment {
  constructor(private store: Store, private registry: BotRegistry) {
    const ids = registry.list().map(bot => bot.id);
    const prior = store.settings.get<string[]>(key);
    const initial = ids.includes(DEFAULT_ENTRY_BOT_ID) ? [DEFAULT_ENTRY_BOT_ID] : ids;
    const hired = ids.filter(id => isPermanentBot(id) || (prior ?? initial).includes(id));
    if (prior === undefined || hired.length !== prior.length || hired.some(id => !prior.includes(id))) {
      store.settings.set(key, hired);
    }
    registry.setHired(hired);
  }

  list() {
    return this.registry.list().map(b => ({
      id: b.id, name: b.name, permanent: isPermanentBot(b.id), hired: this.registry.isHired(b.id),
    }));
  }

  update(raw: unknown): string[] {
    const input = selection.safeParse(raw);
    if (!input.success) throw new AppError(400, 'invalid_roster', '请提交完整的聘用名单。');
    const {expected, hiredIds} = input.data;
    const current = this.registry.list();
    if (Object.keys(expected).length !== current.length ||
        !current.every(b => expected[b.id] === this.registry.isHired(b.id))) {
      throw new AppError(409, 'roster_changed', '聘用名册已更新，请按最新名单重新选择。');
    }
    const hired = new Set(hiredIds);
    if (current.some(bot => isPermanentBot(bot.id) && !hired.has(bot.id))) {
      throw new AppError(400, 'ceo_required', '常驻 Bot 始终启用，无法解聘。');
    }
    if (hired.size !== hiredIds.length || hiredIds.some(id => !this.registry.get(id))) {
      throw new AppError(400, 'invalid_roster', '聘用名单中有重复或未知的 Bot。');
    }
    const changed = current.filter(b => hired.has(b.id) !== expected[b.id]).map(b => b.id);
    if (changed.length) {
      this.store.settings.set(key, hiredIds);
      this.registry.setHired(hiredIds);
    }
    return changed;
  }
}
