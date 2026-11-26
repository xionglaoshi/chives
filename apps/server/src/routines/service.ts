import {legacyBriefingPrompt, morningId, reviewId} from './initial-briefing.js';
/** Manifest sync plus the wall-clock scheduler that turns due routines into tasks. */

import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import type { BotManifest, BotRegistry } from '../bots/index.js';
import type { Orchestrator } from '../orchestrator.js';
import { readProactiveSettings } from '../proactive-settings.js';
import { transaction } from '../store/db.js';
import type { RoutineRecord, RoutineSchedule, Store } from '../store/index.js';
import { shanghaiDayKey } from '../time.js';
import { describeCron, nextCronRun, validateCron } from './cron.js';
import {
  MAX_PROMPT_CHARS,
  MAX_TITLE_CHARS,
  RoutineValidationError,
  parseSchedule,
} from './types.js';

export const TICK_INTERVAL_MS = 30_000;
export const MISSED_GRACE_MS = 15 * 60_000;

export interface RoutineServiceOptions {
  registry: BotRegistry;
  store: Store;
  orchestrator: Orchestrator;
  now: () => Date;
  repoRoot: string;
  tickMs?: number;
  /** Injected in tests; defaults to `config/trade_calendar.json`. */
  tradingDays?: ReadonlySet<string>;
  /** Quiet logger; defaults to console. Tests pass a no-op. */
  log?: (message: string, detail?: unknown) => void;
}

function routineIdFor(botId: string, sourceId: string): string {
  return `manifest:${botId}:${sourceId}`;
}

export function loadTradingDays(repoRoot: string): Set<string> {
  try {
    const raw: unknown = JSON.parse(
      readFileSync(join(repoRoot, 'config', 'trade_calendar.json'), 'utf8'),
    );
    if (Array.isArray(raw)) {
      return new Set(raw.filter((entry): entry is string => typeof entry === 'string'));
    }
  } catch {
    // A missing calendar degrades to "no trading days"; the scheduler still runs
    // routines without `trading_days_only`.
  }
  return new Set();
}

export function computeNextRun(
  schedule: RoutineSchedule,
  after: Date,
): Date | null {
  if (schedule.kind === 'once') {
    const at = new Date(schedule.at);
    return at.getTime() > after.getTime() ? at : null;
  }
  if (schedule.kind === 'every') {
    const step = schedule.minutes * 60_000;
    return new Date((Math.floor(after.getTime() / step) + 1) * step);
  }
  const parsed = validateCron(schedule.expression);
  return nextCronRun(parsed, schedule.tz, after);
}

export function describeSchedule(schedule: RoutineSchedule): string {
  if (schedule.kind === 'every') return `每 ${schedule.minutes} 分钟`;
  if (schedule.kind === 'once') {
    return `一次性 · ${schedule.at.replace('T', ' ').replace(/\.\d+Z$/, ' UTC')}`;
  }
  return describeCron(validateCron(schedule.expression), schedule.tz);
}

export interface CreateRoutineInput {
  title: string;
  schedule: unknown;
  prompt: string;
  tradingDaysOnly?: boolean;
}

export class RoutineService {
  private readonly registry: BotRegistry;
  private readonly store: Store;
  private readonly orchestrator: Orchestrator;
  private readonly now: () => Date;
  private readonly tradingDays: ReadonlySet<string>;
  private readonly tickMs: number;
  private readonly log: (message: string, detail?: unknown) => void;
  private timer: ReturnType<typeof setInterval> | undefined;
  private ticking = false;

  constructor(options: RoutineServiceOptions) {
    this.registry = options.registry;
    this.store = options.store;
    this.orchestrator = options.orchestrator;
    this.now = options.now;
    this.tradingDays = options.tradingDays ?? loadTradingDays(options.repoRoot);
    this.tickMs = options.tickMs ?? TICK_INTERVAL_MS;
    this.log = options.log ?? ((message, detail) => console.log(message, detail ?? ''));
  }

  start(): void {
    this.syncManifest();
    this.refreshNextRuns();
    if (this.timer !== undefined) return;
    this.timer = setInterval(() => {
      void this.tick().catch((error: unknown) => this.log('routine tick failed', error));
    }, this.tickMs);
    this.timer.unref();
  }

  stop(): void {
    if (this.timer === undefined) return;
    clearInterval(this.timer);
    this.timer = undefined;
  }

  /** Manifest routines are upserted; the DB keeps each routine's enabled switch. */
  syncManifest(): void {
    const now = this.now().toISOString();
    for (const bot of this.registry.list()) {
      for (const routine of bot.routines) {
        const canonical = routineIdFor(bot.id, routine.id);
        if ([morningId, reviewId].includes(canonical) && !this.registry.isHired(bot.id)) continue;
        let id = canonical;
        let prompt = routine.prompt;
        if (canonical === morningId) {
          let bound = this.store.settings.get<string>('desk.morningRoutineId');
          if (!bound) {
            const legacy = this.list(bot.id).find(row => row.source === 'user' &&
              (row.prompt.startsWith('生成每日投研简报，投递到 Chives Bot 消息。') ||
               row.title === '每日投研简报' && row.schedule.kind === 'cron' && row.schedule.expression === '0 9 * * 1-5'));
            bound = legacy?.id ?? canonical;
            if (legacy) {
              const original = legacyBriefingPrompt('').trim();
              const custom = legacy.prompt.startsWith(original) ? legacy.prompt.slice(original.length).trim() : '';
              if (custom) this.store.settings.set('desk.morningAdditions', custom);
              const edited = !legacy.prompt.startsWith(original) || legacy.title !== '每日投研简报' ||
                legacy.schedule.kind !== 'cron' || legacy.schedule.expression !== '0 9 * * 1-5' ||
                legacy.schedule.tz !== 'Asia/Shanghai' || legacy.tradingDaysOnly;
              if (edited) this.store.settings.set('routine.override:'+bound,'edited');
              this.store.db.prepare("UPDATE routines SET source='manifest' WHERE id=?").run(bound);
            }
            this.store.settings.set('desk.morningRoutineId',bound);
          }
          id = bound;
          const additions = this.store.settings.get<string>('desk.morningAdditions');
          if (additions) prompt += '\n'+additions;
        }
        if (this.store.settings.get(`routine.override:${id}`)) continue;
        let schedule: RoutineSchedule;
        try {
          schedule = parseSchedule(routine.schedule);
        } catch (error) {
          this.log(`routine ${routine.id} of bot ${bot.id} has an invalid schedule`, error);
          continue;
        }
        const next = computeNextRun(schedule, this.now());
        this.store.routines.upsertManifest({
          id,
          botId: bot.id,
          source: 'manifest',
          title: routine.title,
          schedule,
          prompt,
          tradingDaysOnly: routine.trading_days_only === true,
          enabled: routine.enabled !== false,
          createdAt: now,
          nextRunAt: next === null ? null : next.toISOString(),
        });
      }
    }
  }

  private refreshNextRuns(): void {
    const now = this.now();
    for (const routine of this.store.routines.list()) {
      if (routine.nextRunAt !== null) continue;
      const next = computeNextRun(routine.schedule, now);
      this.store.routines.setNextRun(routine.id, next === null ? null : next.toISOString());
    }
  }

  isTradingDay(date: Date): boolean {
    if (this.tradingDays.size === 0) {
      const weekday = new Date(date.getTime() + 8 * 3600_000).getUTCDay();
      return weekday !== 0 && weekday !== 6;
    }
    return this.tradingDays.has(shanghaiDayKey(date));
  }

  async tick(): Promise<void> {
    if (this.ticking) return;
    this.ticking = true;
    try {
      const now = this.now();
      const due = this.store.routines.listDue(now.toISOString());
      for (const routine of due) {
        if (this.store.routines.get(routine.id)?.enabled) await this.handleDue(routine, now);
      }
    } finally {
      this.ticking = false;
    }
  }

  private async handleDue(
    routine: RoutineRecord,
    now: Date,
  ): Promise<void> {
    const next = computeNextRun(routine.schedule, now);
    const nextIso = next === null ? null : next.toISOString();
    const settings = readProactiveSettings(this.store);
    if (!this.registry.isHired(routine.botId) || !settings.enabled || !settings.autoAnalysis || settings.observeOnly) {
      this.store.routines.setNextRun(routine.id, nextIso);
      return;
    }
    if (routine.tradingDaysOnly && !this.isTradingDay(now)) {
      this.store.routines.setNextRun(routine.id, nextIso);
      return;
    }
    const dueAt = routine.nextRunAt === null ? now.getTime() : Date.parse(routine.nextRunAt);
    if (Number.isFinite(dueAt) && now.getTime() - dueAt > MISSED_GRACE_MS) {
      this.log(`routine ${routine.id} missed its window; skipping this occurrence`);
      this.store.routines.setNextRun(routine.id, nextIso);
      return;
    }

    try {
      await this.orchestrator.submitProactive(routine.botId, {
        title: routine.title,
        label: '主动消息',
        prompt: routine.prompt,
        origin: 'routine',
        meta: { routineId: routine.id, schedule: describeSchedule(routine.schedule) },
      });
      this.store.routines.markRun(routine.id, now.toISOString(), nextIso);
    } catch (error) {
      if (error instanceof Error && 'code' in error && error.code === 'bot_busy') return;
      this.log(`routine ${routine.id} could not start`, error);
      this.store.routines.setNextRun(routine.id, nextIso);
    }
  }

  list(botId: string): RoutineRecord[] {
    return this.store.routines.listByBot(botId);
  }

  get(id: string): RoutineRecord | undefined {
    return this.store.routines.get(id);
  }

  createForBot(botId: string, input: CreateRoutineInput): RoutineRecord {
    this.requireBot(botId);
    const title = input.title.trim();
    if (title === '' || [...title].length > MAX_TITLE_CHARS) {
      throw new RoutineValidationError(`title must be 1-${MAX_TITLE_CHARS} characters`);
    }
    const prompt = input.prompt.trim();
    if (prompt === '' || prompt.length > MAX_PROMPT_CHARS) {
      throw new RoutineValidationError(`prompt must be 1-${MAX_PROMPT_CHARS} characters`);
    }
    const schedule = parseSchedule(input.schedule);
    const now = this.now();
    const next = computeNextRun(schedule, now);
    return this.store.routines.create({
      id: `user:${randomUUID()}`,
      botId,
      source: 'user',
      title,
      schedule,
      prompt,
      tradingDaysOnly: input.tradingDaysOnly === true,
      enabled: false,
      createdAt: now.toISOString(),
      nextRunAt: next === null ? null : next.toISOString(),
    });
  }

  setEnabled(id: string, enabled: boolean): RoutineRecord | undefined {
    const routine = this.store.routines.get(id);
    if (routine === undefined) return undefined;
    const updated = this.store.routines.setEnabled(id, enabled);
    if (updated !== undefined && enabled && (!routine.enabled || updated.nextRunAt === null)) {
      const next = computeNextRun(updated.schedule, this.now());
      return this.store.routines.setNextRun(id, next === null ? null : next.toISOString());
    }
    return updated;
  }

  editManaged(id: string, patch: Record<string, unknown>): RoutineRecord | undefined {
    const current = this.get(id);
    if (!current) return;
    const title = patch.title === undefined ? current.title : patch.title;
    if (typeof title !== 'string' || !title.trim() || [...title.trim()].length > MAX_TITLE_CHARS) {
      throw new RoutineValidationError(`任务名称须为 1–${MAX_TITLE_CHARS} 字。`);
    }
    const prompt = patch.prompt === undefined ? current.prompt : patch.prompt;
    if (typeof prompt !== 'string' || !prompt.trim() || prompt.trim().length > MAX_PROMPT_CHARS) {
      throw new RoutineValidationError(`任务指令须为 1–${MAX_PROMPT_CHARS} 字。`);
    }
    const tradingDaysOnly = patch.tradingDaysOnly === undefined ? current.tradingDaysOnly : patch.tradingDaysOnly;
    if (typeof tradingDaysOnly !== 'boolean') throw new RoutineValidationError('仅交易日必须为开或关。');
    const schedule = patch.schedule === undefined ? current.schedule : parseSchedule(patch.schedule);
    const nextRunAt = JSON.stringify(schedule) === JSON.stringify(current.schedule)
      ? current.nextRunAt : computeNextRun(schedule, this.now())?.toISOString() ?? null;
    return transaction(this.store.db, () => {
      const result = this.store.routines.edit(id, { title: title.trim(), prompt: prompt.trim(), schedule, tradingDaysOnly, nextRunAt });
      if (result?.source === 'manifest') this.store.settings.set(`routine.override:${id}`, 'edited');
      return result;
    });
  }

  deleteManaged(id: string): boolean {
    const routine = this.get(id);
    if (!routine) return false;
    return transaction(this.store.db, () => {
      if (routine.source === 'manifest') this.store.settings.set(`routine.override:${id}`, 'deleted');
      return this.store.routines.delete(id);
    });
  }

  delete(id: string): boolean {
    const routine = this.store.routines.get(id);
    if (routine === undefined || routine.source !== 'user') return false;
    return this.store.routines.delete(id);
  }

  async runNow(id: string): Promise<{ taskId: string; messageId: string }> {
    const routine = this.store.routines.get(id);
    if (routine === undefined) throw new RoutineValidationError(`unknown routine "${id}"`);
    const result = await this.orchestrator.submitProactive(routine.botId, {
      title: routine.title,
      label: '主动消息',
      prompt: routine.prompt,
      origin: 'routine',
      meta: { routineId: routine.id, manual: true },
    });
    const now = this.now();
    const next = computeNextRun(routine.schedule, now);
    this.store.routines.markRun(id, now.toISOString(), next === null ? null : next.toISOString());
    return result;
  }

  private requireBot(botId: string): BotManifest {
    const bot = this.registry.get(botId);
    if (bot === undefined) throw new RoutineValidationError(`unknown bot "${botId}"`);
    return bot;
  }
}
