import { z } from 'zod';
import { AppError } from '../errors.js';
import type { Store } from '../store/index.js';
import { DEFAULT_ENTRY_BOT_ID, type BotRegistry } from './registry.js';

const key = 'bots.hired.v1';
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
    const hired = ids.filter(id => id === DEFAULT_ENTRY_BOT_ID || (prior ?? initial).includes(id));
    if (prior === undefined || hired.length !== prior.length || hired.some(id => !prior.includes(id))) {
      store.settings.set(key, hired);
    }
    registry.setHired(hired);
  }

  list() {
    const names = new Map(this.store.bots.list().map(b => [b.id, b.displayName]));
    return this.registry.list().map(b => ({
      id: b.id, name: names.get(b.id) ?? b.name, permanent: b.id === DEFAULT_ENTRY_BOT_ID, hired: this.registry.isHired(b.id),
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
    if (!hired.has(DEFAULT_ENTRY_BOT_ID)) {
      throw new AppError(400, 'operator_required', '总调度为常驻 Bot，无法解聘。');
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
