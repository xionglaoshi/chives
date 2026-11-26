import { botHasWatches, WATCH_REFERRAL } from '../bots/types.js';
/** Watch lifecycle: local persistence, chives-radar sync, expiry, reconciliation and triggers. */

import { createHash, randomUUID } from 'node:crypto';

import { toMessageDto, toWatchDto } from '../api/dto.js';
import type { WatchDto } from '../api/protocol.js';
import type { BotRegistry } from '../bots/index.js';
import type { EventBus } from '../events/index.js';
import { NotificationService } from '../notifications/index.js';
import type { Orchestrator } from '../orchestrator.js';
import { readProactiveSettings } from '../proactive-settings.js';
import type { JsonRecord, Store, WatchEventKind, WatchRecord, WatchStatus } from '../store/index.js';
import type { AlertView } from '../alerts/service.js';
import { ChivesRadarClient, type EnginePlanState } from './engine.js';
import {
  DEFAULT_EXPIRES_DAYS,
  MAX_LABEL_CHARS,
  MAX_CHIVES_WATCHES,
  MAX_NOTE_CHARS,
  MAX_WATCHES_PER_BOT,
  WatchValidationError,
  buildPlan,
  describeCondition,
  describeGiveUp,
  describeWatch,
  planIdFor,
  planToRecord,
  validateWatchInput,
  watchIdFromPlan,
  watchPrice,
  shanghaiMonthDay,
  type NormalizedWatchInput,
  type WatchCreateInput,
  type WatchPlan,
  type WatchUpdateInput,
} from './plan.js';

export const WATCH_SYNC_INTERVAL_MS = 30_000;
export const REPEAT_COOLDOWN_MS = 30 * 60_000;
export const WATCH_NOTICE_PREFIX = 'watch.notices.';

export interface WatchServiceOptions {
  store: Store;
  registry: BotRegistry;
  orchestrator: Orchestrator;
  bus: EventBus;
  notifications: NotificationService;
  now: () => Date;
  cnWatchUrl: string;
  fetchImpl?: typeof fetch;
  syncIntervalMs?: number;
  log?: (message: string, detail?: unknown) => void;
}

/** A queued trigger older than this is given up and the user is notified instead. */
const PENDING_MAX_MS = 30 * 60_000;
const PAUSE_KEY = 'watch.pause:';
const TRIGGER_STATES = new Set(['execute', 'abandon', 'exit']);

export interface WatchTriggerInput {
  planId: string;
  alert: AlertView;
  now: Date;
}

export type WatchTriggerResult =
  | { status: 'started'; taskId: string }
  | { status: 'skipped'; reason: string; taskId?: string };

export interface WatchDetail {
  watch: WatchDto;
  history: Array<{
    id: number;
    kind: string;
    actor: string;
    taskId: string | null;
    detail: string | null;
    createdAt: string;
    before: JsonRecord | null;
    after: JsonRecord | null;
  }>;
}

function queueWatchNotice(store: Store, botId: string, text: string): void {
  const key = `${WATCH_NOTICE_PREFIX}${botId}`;
  const current = store.settings.get<string[]>(key);
  const list = Array.isArray(current) ? current : [];
  store.settings.set(key, [...list, text].slice(-10));
}

/** Consumed by the orchestrator before the next prompt; returns one injection block. */
export function consumeWatchNotices(store: Store, botId: string): string {
  const key = `${WATCH_NOTICE_PREFIX}${botId}`;
  const current = store.settings.get<string[]>(key);
  if (!Array.isArray(current) || current.length === 0) return '';
  store.settings.delete(key);
  return current.map((entry) => `- ${entry}`).join('\n');
}

function detailRecord(alert: AlertView): JsonRecord {
  const detail = alert.raw['detail'];
  return typeof detail === 'object' && detail !== null && !Array.isArray(detail)
    ? (detail as JsonRecord)
    : {};
}

function textOf(record: JsonRecord, key: string): string {
  const value = record[key];
  return typeof value === 'string' ? value : '';
}

function stateOf(alert: AlertView): string {
  return textOf(detailRecord(alert), 'to');
}

function savedPlanId(watch: WatchRecord): string {
  const id = watch.plan['id'];
  return typeof id === 'string' && watchIdFromPlan(id) === watch.id ? id : planIdFor(watch.id);
}

export class WatchService {
  private readonly store: Store;
  private readonly registry: BotRegistry;
  private readonly orchestrator: Orchestrator;
  private readonly bus: EventBus;
  private readonly notifications: NotificationService;
  private readonly now: () => Date;
  private readonly engine: ChivesRadarClient;
  private readonly syncIntervalMs: number;
  private readonly log: (message: string, detail?: unknown) => void;
  private timer: ReturnType<typeof setInterval> | undefined;
  private ticking = false;
  /** Triggers that arrived while the owning bot was busy; retried when its task ends. */
  private readonly pending = new Map<string, { input: WatchTriggerInput; since: number }>();
  private unsubscribe: (() => void) | undefined;

  constructor(options: WatchServiceOptions) {
    this.store = options.store;
    this.registry = options.registry;
    this.orchestrator = options.orchestrator;
    this.bus = options.bus;
    this.notifications = options.notifications;
    this.now = options.now;
    this.engine = new ChivesRadarClient({
      baseUrl: options.cnWatchUrl,
      ...(options.fetchImpl === undefined ? {} : { fetchImpl: options.fetchImpl }),
    });
    const configured = Number(process.env['CHIVES_WATCH_SYNC_SECONDS'] ?? '');
    this.syncIntervalMs =
      options.syncIntervalMs ??
      (Number.isFinite(configured) && configured > 0
        ? configured * 1000
        : WATCH_SYNC_INTERVAL_MS);
    this.log = options.log ?? ((message, detail) => console.log(message, detail ?? ''));
  }

  start(): void {
    if (this.timer !== undefined) return;
    const interval = Number.isFinite(this.syncIntervalMs) && this.syncIntervalMs > 0
      ? this.syncIntervalMs
      : WATCH_SYNC_INTERVAL_MS;
    this.timer = setInterval(() => {
      void this.tick().catch((error: unknown) => this.log('watch reconcile failed', error));
    }, interval);
    this.timer.unref();
    this.unsubscribe = this.bus.subscribe((event) => {
      if (event.type !== 'task.updated' || event.task.status === 'running') return;
      void this.flushPending(event.task.botId).catch((error: unknown) =>
        this.log('watch pending trigger retry failed', error),
      );
    });
    void this.tick().catch(() => undefined);
  }

  stop(): void {
    this.unsubscribe?.();
    this.unsubscribe = undefined;
    if (this.timer === undefined) return;
    clearInterval(this.timer);
    this.timer = undefined;
  }

  /** Watch ids whose trigger is waiting for the bot to be free (for tests and status). */
  pendingWatchIds(): string[] {
    return [...this.pending.keys()];
  }

  /**
   * Retries queued triggers for one bot (or all bots). A trigger older than
   * PENDING_MAX_MS is given up: the watch is marked triggered and the user is
   * notified directly, so a reminder is never silently lost.
   */
  async flushPending(botId?: string): Promise<void> {
    for (const [watchId, entry] of [...this.pending]) {
      const watch = this.store.watches.get(watchId);
      if (watch === undefined || !this.enabled(watch)) {
        this.pending.delete(watchId);
        continue;
      }
      if (botId !== undefined && watch.botId !== botId) continue;
      const now = this.now();
      if (now.getTime() - entry.since > PENDING_MAX_MS) {
        this.pending.delete(watchId);
        await this.giveUpBusy(watch, stateOf(entry.input.alert), now);
        continue;
      }
      this.pending.delete(watchId);
      await this.handleTrigger({ ...entry.input, now });
    }
  }

  private async giveUpBusy(watch: WatchRecord, state: string, now: Date): Promise<void> {
    const display = watch.name === '' ? watch.code : watch.name;
    const notification = this.notifications.notifyGuardrail(
      watch.botId,
      watch.createdTaskId ?? '',
      `盯盘已触发（${watch.label}）`,
      `${display} ${describeWatch(watch)}；bot 一直在忙，没有自动分析`,
    );
    this.notifications.publishCreated(notification);
    await this.markTriggered(watch, null, state === '' ? 'execute' : state, now, '盯盘触发，Bot 正忙，已发送提醒');
  }

  /**
   * chives-radar only alerts on a state transition; if that alert was missed (server
   * restart, lost poll) a one-shot watch would sit in a trigger state forever.
   */
  private catchUpTriggers(byId: Map<string, EnginePlanState>): void {
    for (const watch of this.store.watches.list({ status: 'active' })) {
      if (!this.enabled(watch) || watch.repeat === true || watch.triggeredAt !== null || this.pending.has(watch.id)) continue;
      const planId = savedPlanId(watch);
      const state = byId.get(planId);
      if (state === undefined || !TRIGGER_STATES.has(state.state)) continue;
      this.pending.set(watch.id, {
        since: this.now().getTime(),
        input: {
          planId,
          now: this.now(),
          alert: {
            id: 0,
            ts: state.since,
            code: watch.code,
            name: watch.name,
            ruleId: `plan:${planId}`,
            ruleType: 'plan',
            title: watch.label,
            strategyId: '',
            event: '',
            level: '',
            raw: {
              detail: { plan_id: planId, from: '', to: state.state, reason: '引擎状态已满足条件（补触发）', label: watch.label },
              price: state.last_price,
            },
          },
        },
      });
    }
  }

  private enabled(watch: WatchRecord): boolean {
    return this.registry.isHired(watch.botId) && watch.status === 'active' && this.store.settings.get<boolean | string>(PAUSE_KEY + watch.id) !== true;
  }

  private view(watch: WatchRecord): WatchDto {
    return { ...toWatchDto(watch), enabled: this.enabled(watch) };
  }

  managedRules(watch: WatchRecord) {
    const plan = watch.plan;
    return {
      when: Array.isArray(plan.stock) ? plan.stock as JsonRecord[] : [],
      giveUp: Array.isArray(plan.giveup) ? plan.giveup as JsonRecord[] : [],
      market: Array.isArray(plan.market) ? plan.market as JsonRecord[] : [],
      match: plan.policy === 'all' ? 'all' as const : 'any' as const,
    };
  }

  async setEnabled(id: string, enabled: boolean, owner?: { botId: string; taskId: string }): Promise<void> {
    if (owner) { this.requireBot(owner.botId); this.requireOwned(id, owner.botId); }
    const watch = this.store.watches.get(id);
    if (!watch || watch.status !== 'active' || Date.parse(watch.expiresAt) <= this.now().getTime()) {
      throw new WatchValidationError('not_active', '这条盯盘已结束。');
    }
    if (this.enabled(watch) === enabled) return;
    const now = this.now().toISOString();
    this.store.settings.set(PAUSE_KEY + id, enabled ? now : true);
    this.pending.delete(id);
    this.store.watches.update(id, { engineState: null, syncError: null, updatedAt: now });
    const sync = enabled ? await this.engine.upsert(watch.plan) : await this.engine.remove(savedPlanId(watch));
    const current = this.store.watches.get(id);
    if (!current || current.status !== 'active') return;
    if (this.enabled(current) !== enabled) {
      await this.tick();
      return;
    }
    const updated = this.store.watches.update(id, { syncError: sync.ok ? null : 'engine_unreachable' }) ?? current;
    this.addEvent(updated, 'updated', owner ? 'bot' : 'user', owner?.taskId ?? null, enabled ? '恢复盯盘' : '暂停盯盘');
    this.publish('watch.updated', updated);
  }

  getDetail(id: string): WatchDetail | undefined {
    const watch = this.store.watches.get(id);
    if (watch === undefined) return undefined;
    return {
      watch: this.view(watch),
      history: this.store.watches.events(id).map((event) => ({
        id: event.id,
        kind: event.kind,
        actor: event.actor,
        taskId: event.taskId,
        detail: event.detail,
        createdAt: event.createdAt,
        before: event.before,
        after: event.after,
      })),
    };
  }

  list(botId: string | undefined, status: WatchStatus | 'all' | undefined): WatchDto[] {
    const watches =
      status === 'all' || status === undefined
        ? this.store.watches.list(botId === undefined ? {} : { botId })
        : this.store.watches.list({
            ...(botId === undefined ? {} : { botId }),
            status,
          });
    return watches.map((watch) => this.view(watch));
  }

  countActive(botId: string): number {
    return this.store.watches.countActiveByBot(botId);
  }

  profileWatches(botId: string): WatchDto[] {
    return this.list(botId, 'all');
  }

  private publish(event: 'watch.created' | 'watch.updated', watch: WatchRecord): void {
    this.bus.publish({ type: event, botId: watch.botId, watch: this.view(watch) });
  }

  private addEvent(
    watch: WatchRecord,
    kind: WatchEventKind,
    actor: 'user' | 'bot' | 'system',
    taskId: string | null,
    detail: string,
    before: JsonRecord | null = null,
    after: JsonRecord | null = null,
  ): void {
    this.store.watches.addEvent({
      watchId: watch.id,
      botId: watch.botId,
      kind,
      actor,
      taskId,
      before,
      after,
      detail,
      createdAt: this.now().toISOString(),
    });
  }

  /** A timeline card anchored to the tool-calling turn; no confirmation is required. */
  private appendCard(
    watch: WatchRecord,
    taskId: string | null,
    action: 'created' | 'updated' | 'deleted',
    diff: string,
  ): string {
    const createdAt = this.now().toISOString();
    const message = this.store.messages.append({
      id: randomUUID(),
      botId: watch.botId,
      taskId: taskId !== null && this.store.tasks.get(taskId) !== undefined ? taskId : null,
      role: 'system',
      kind: 'approval',
      content:
        action === 'deleted'
          ? `已删除盯盘：${watch.label}`
          : `盯盘已${action === 'created' ? '创建' : '修改'}：${watch.label}`,
      meta: {
        approvalKind: 'watch',
        watchAction: action,
        watchId: watch.id,
        code: watch.code,
        name: watch.name,
        label: watch.label,
        conditionText: describeWatch(watch),
        expiresAt: watch.expiresAt,
        status: watch.status,
        diff,
        repeat: watch.repeat,
      },
      createdAt,
    });
    this.bus.publish({
      type: 'message.created',
      botId: watch.botId,
      taskId: message.taskId,
      message: toMessageDto(message),
    });
    return message.id;
  }

  /** Keeps every existing card for this watch in sync with its current status. */
  private syncCardStatus(watch: WatchRecord, status: WatchStatus): void {
    for (const message of this.store.messages.listByKind('approval')) {
      if (message.meta?.['approvalKind'] !== 'watch') continue;
      if (message.meta?.['watchId'] !== watch.id) continue;
      const updated = this.store.messages.updateMeta(message.id, {
        ...(message.meta ?? {}),
        status,
      });
      if (updated === undefined) continue;
      this.bus.publish({
        type: 'message.created',
        botId: watch.botId,
        taskId: updated.taskId,
        message: toMessageDto(updated),
      });
    }
  }

  private requireBot(botId: string): void {
    const bot = this.registry.get(botId);
    if (bot === undefined) throw new WatchValidationError('unknown_bot', `没有这个 bot：${botId}`);
    if (!botHasWatches(bot) || !this.registry.isHired(botId)) {
      throw new WatchValidationError('watch_owner_required', WATCH_REFERRAL);
    }
    if (bot.background) {
      throw new WatchValidationError('background_bot', '后台 bot 不能设置盯盘');
    }
  }

  private requireOwned(id: string, botId: string): WatchRecord {
    const watch = this.store.watches.get(id);
    if (watch === undefined || watch.botId !== botId) {
      throw new WatchValidationError('not_found', '没有找到这条盯盘');
    }
    return watch;
  }

  private planFor(input: NormalizedWatchInput, id: string, expiresAt: string): WatchPlan {
    return buildPlan(planIdFor(id), input, expiresAt);
  }

  private expiryFrom(input: NormalizedWatchInput, from: Date): string {
    return new Date(from.getTime() + input.expiresInDays * 86_400_000).toISOString();
  }

  async create(botId: string, taskId: string | null, raw: WatchCreateInput, handoffId?: string): Promise<WatchDto> {
    this.requireBot(botId);
    const input = validateWatchInput(raw);
    const identity=[handoffId,input.code,input.when,input.giveUp,input.market,input.match,input.repeat,input.expiresInDays];
    const id=handoffId?createHash('sha256').update(JSON.stringify(identity)).digest('hex').slice(0,24):randomUUID().replace(/-/g,'').slice(0,24);
    const existing=this.store.watches.get(id);
    if(existing)return this.view(existing);
    if (this.store.watches.countActiveByBot(botId) >= MAX_WATCHES_PER_BOT) {
      throw new WatchValidationError(
        'too_many_watches',
        `每个 bot 最多同时盯 ${MAX_WATCHES_PER_BOT} 条`,
      );
    }
    if (this.store.watches.countActiveChives() >= MAX_CHIVES_WATCHES) {
      throw new WatchValidationError(
        'too_many_watches',
        `所有 bot 的活跃盯盘合计最多 ${MAX_CHIVES_WATCHES} 条`,
      );
    }
    const now = this.now();
    const expiresAt = this.expiryFrom(input, now);
    const plan = this.planFor(input, id, expiresAt);
    const planRecord = planToRecord(plan);
    const sync = await this.engine.upsert(planRecord);
    if (!sync.ok && !sync.unreachable) {
      throw new WatchValidationError(
        sync.code,
        `盯盘引擎拒绝了这条盯盘：${sync.message}`,
        sync.field ?? undefined,
      );
    }
    const duplicate=this.store.watches.get(id);
    if(duplicate)return this.view(duplicate);
    const watch = this.store.watches.create({
      id,
      botId,
      code: input.code,
      name: '',
      label: input.label,
      note: input.note,
      plan: planRecord,
      repeat: input.repeat,
      status: 'active',
      engineState: null,
      lastPrice: null,
      syncError: sync.ok ? null : 'engine_unreachable',
      createdTaskId: taskId,
      updatedTaskId: taskId,
      createdAt: now.toISOString(),
      updatedAt: now.toISOString(),
      expiresAt,
      cancelledBy: null,
    });
    this.addEvent(watch, 'created', 'bot', taskId, describeWatch(watch), null, planRecord);
    this.appendCard(watch, taskId, 'created', '');
    this.publish('watch.created', watch);
    return this.view(watch);
  }

  private mergedInput(watch: WatchRecord, patch: WatchUpdateInput): NormalizedWatchInput {
    const plan = watch.plan;
    const stock = Array.isArray(plan['stock']) ? (plan['stock'] as JsonRecord[]) : [];
    const giveup = Array.isArray(plan['giveup']) ? (plan['giveup'] as JsonRecord[]) : [];
    const market = Array.isArray(plan['market']) ? (plan['market'] as JsonRecord[]) : [];
    return validateWatchInput({
      code: patch.code ?? watch.code,
      label: patch.label ?? watch.label,
      when: patch.when ?? stock,
      match: patch.match ?? (plan['policy'] === 'all' ? 'all' : 'any'),
      giveUp: patch.giveUp ?? giveup,
      market: patch.market ?? market,
      expiresInDays:
        patch.expiresInDays ??
        Math.max(
          1,
          Math.min(
            30,
            Math.ceil((Date.parse(watch.expiresAt) - this.now().getTime()) / 86_400_000),
          ),
        ),
      note: patch.note ?? watch.note,
      repeat: patch.repeat ?? watch.repeat,
    });
  }

  async update(
    botId: string,
    taskId: string | null,
    id: string,
    patch: WatchUpdateInput,
    actor: 'bot' | 'user' = 'bot',
  ): Promise<{ watch: WatchDto; diff: string }> {
    if (actor === 'bot') this.requireBot(botId);
    const watch = this.requireOwned(id, botId);
    if (watch.status !== 'active') {
      throw new WatchValidationError('not_active', '这条盯盘已经不在生效中');
    }
    const input = this.mergedInput(watch, patch);
    const now = this.now();
    const expiresAt = patch.expiresInDays === undefined ? watch.expiresAt : this.expiryFrom(input, now);
    const plan = { ...this.planFor(input, watch.id, expiresAt), id: savedPlanId(watch) };
    const planRecord = planToRecord(plan);
    const wasEnabled = this.enabled(watch);
    const sync = wasEnabled ? await this.engine.upsert(planRecord) : {ok: true as const};
    if (!sync.ok && !sync.unreachable) {
      throw new WatchValidationError(
        sync.code,
        `盯盘引擎拒绝了这次修改：${sync.message}`,
        sync.field ?? undefined,
      );
    }
    const current = this.store.watches.get(id);
    if (!current || current.status !== 'active') {
      await this.engine.remove(savedPlanId(watch));
      throw new WatchValidationError('not_active', '这条盯盘已结束。');
    }
    if (!this.enabled(current) && wasEnabled) await this.engine.remove(savedPlanId(watch));
    const updated = this.store.watches.update(watch.id, {
      code: input.code,
      ...(input.code !== watch.code ? {name: '', engineState: null, lastPrice: null} : {}),
      label: input.label,
      note: input.note,
      plan: planRecord,
      repeat: input.repeat,
      expiresAt,
      syncError: sync.ok ? null : 'engine_unreachable',
      updatedTaskId: taskId,
      updatedAt: now.toISOString(),
    });
    if (updated === undefined) throw new WatchValidationError('not_found', '没有找到这条盯盘');
    const diff = this.describeChange(watch, updated);
    this.addEvent(updated, 'updated', actor, taskId, diff, watch.plan, planRecord);
    if (actor === 'bot') this.appendCard(updated, taskId, 'updated', diff);
    this.publish('watch.updated', updated);
    return { watch: this.view(updated), diff };
  }

  private describeChange(before: WatchRecord, after: WatchRecord): string {
    const lines: string[] = [];
    if (before.label !== after.label) lines.push(`名称：${before.label} → ${after.label}`);
    if (before.code !== after.code) lines.push(`标的：${before.code} → ${after.code}`);
    if (before.note !== after.note) lines.push('理由已更新');
    if (JSON.stringify(before.plan['stock']) !== JSON.stringify(after.plan['stock'])) {
      lines.push(
        `条件：${describeWatch(before)} → ${describeWatch(after)}`,
      );
    }
    if (JSON.stringify(before.plan['market']) !== JSON.stringify(after.plan['market'])) {
      lines.push('大盘条件已更新');
    }
    if (JSON.stringify(before.plan['giveup']) !== JSON.stringify(after.plan['giveup'])) {
      lines.push(`放弃条件：${describeGiveUp(before.plan) || '无'} → ${describeGiveUp(after.plan) || '无'}`);
    }
    if (before.expiresAt !== after.expiresAt) {
      lines.push(`到期：${shanghaiMonthDay(before.expiresAt)} → ${shanghaiMonthDay(after.expiresAt)}`);
    }
    if (before.repeat !== after.repeat) lines.push(after.repeat ? '改为可重复触发' : '改为只触发一次');
    return lines.length === 0 ? '条件未变化，到期时间已刷新' : lines.join('；');
  }

  async cancelByBot(botId: string, taskId: string | null, id: string): Promise<WatchDto> {
    this.requireBot(botId);
    const watch = this.requireOwned(id, botId);
    if (watch.status !== 'active') {
      throw new WatchValidationError('not_active', '这条盯盘已经不在生效中');
    }
    return this.finishCancel(watch, 'bot', taskId, () => {
      this.appendCard(watch, taskId, 'deleted', '');
    });
  }

  async cancelByUser(id: string): Promise<WatchDto | undefined> {
    const watch = this.store.watches.get(id);
    if (watch === undefined) return undefined;
    if (watch.status !== 'active') return this.view(watch);
    const dto = await this.finishCancel(watch, 'user', null, () => undefined);
    queueWatchNotice(
      this.store,
      watch.botId,
      `用户删除了盯盘「${describeWatch(watch)}」，不要再按这条盯盘提醒或分析。`,
    );
    return dto;
  }

  private async finishCancel(
    watch: WatchRecord,
    actor: 'user' | 'bot' | 'system',
    taskId: string | null,
    afterUpdate: () => void,
  ): Promise<WatchDto> {
    const now = this.now();
    const updated = this.store.watches.update(watch.id, {
      status: 'cancelled',
      cancelledBy: actor,
      updatedAt: now.toISOString(),
      ...(taskId === null ? {} : { updatedTaskId: taskId }),
    });
    const result = updated ?? watch;
    const remove = await this.engine.remove(savedPlanId(watch));
    if (!remove.ok) {
      this.store.watches.update(watch.id, { syncError: 'engine_unreachable' });
    }
    this.addEvent(result, 'cancelled', actor, taskId, `盯盘已取消（${actor}）`);
    this.syncCardStatus(result, 'cancelled');
    afterUpdate();
    this.publish('watch.updated', this.store.watches.get(watch.id) ?? result);
    return this.view(this.store.watches.get(watch.id) ?? result);
  }

  private async expire(watch: WatchRecord): Promise<void> {
    await this.engine.remove(savedPlanId(watch));
    const now = this.now().toISOString();
    const updated = this.store.watches.update(watch.id, {
      status: 'expired',
      syncError: null,
      updatedAt: now,
    });
    const result = updated ?? watch;
    this.addEvent(result, 'expired', 'system', null, '盯盘到期');
    this.syncCardStatus(result, 'expired');
    this.publish('watch.updated', result);
  }

  private async cancelBySystem(watch: WatchRecord, reason: string): Promise<void> {
    const now = this.now().toISOString();
    const updated = this.store.watches.update(watch.id, {
      status: 'cancelled',
      cancelledBy: 'system',
      syncError: null,
      updatedAt: now,
    });
    const result = updated ?? watch;
    this.addEvent(result, 'sync_error', 'system', null, reason);
    this.addEvent(result, 'cancelled', 'system', null, `引擎拒绝，已自动取消：${reason}`);
    this.syncCardStatus(result, 'cancelled');
    const anchor = watch.createdTaskId ?? watch.updatedTaskId;
    const message = this.store.messages.append({
      id: randomUUID(),
      botId: watch.botId,
      taskId: anchor !== null && this.store.tasks.get(anchor) !== undefined ? anchor : null,
      role: 'system',
      kind: 'notice',
      content: `盯盘「${describeWatch(watch)}」被盯盘引擎拒绝，已自动取消：${reason}`,
      meta: { code: 'watch_sync_error', watchId: watch.id },
      createdAt: now,
    });
    this.bus.publish({
      type: 'message.created',
      botId: watch.botId,
      taskId: message.taskId,
      message: toMessageDto(message),
    });
    this.publish('watch.updated', result);
  }

  async tick(): Promise<void> {
    if (this.ticking) return;
    this.ticking = true;
    try {
      const now = this.now();
      for (const watch of this.store.watches.listExpired(now.toISOString())) {
        await this.expire(watch);
      }
      const remote = await this.engine.list();
      const active = this.store.watches.list({ status: 'active' }).filter(watch => this.enabled(watch));
      if (!remote.ok) {
        for (const watch of active) {
          if (watch.syncError !== 'engine_unreachable') {
            this.store.watches.update(watch.id, { syncError: 'engine_unreachable' });
            this.addEvent(watch, 'sync_error', 'system', null, '盯盘引擎不可达，恢复后自动补推');
          }
        }
        return;
      }
      const byId = new Map(remote.plans.map((plan) => [plan.id, plan]));
      const activePlanIds = new Set(active.map((watch) => savedPlanId(watch)));
      for (const watch of active) {
        const current = this.store.watches.get(watch.id);
        if (!current || !this.enabled(current)) continue;
        const planId = savedPlanId(current);
        const state = byId.get(planId);
        if (state?.state === 'expired') {
          await this.expire(watch);
          continue;
        }
        const sync = await this.engine.upsert(current.plan);
        const after = this.store.watches.get(watch.id);
        if (!after || !this.enabled(after)) { await this.engine.remove(planId); continue; }
        if (!sync.ok && !sync.unreachable) {
          await this.cancelBySystem(watch, `${sync.code}：${sync.message}`);
          continue;
        }
        if (!sync.ok) {
          this.store.watches.update(watch.id, { syncError: 'engine_unreachable' });
          continue;
        }
        this.store.watches.update(watch.id, {
          engineState: state?.state ?? watch.engineState,
          lastPrice: state?.last_price === undefined ? watch.lastPrice : state.last_price,
          syncError: null,
        });
      }
      this.catchUpTriggers(byId);
      for (const [planId, state] of byId) {
        if (watchIdFromPlan(planId) === null) continue;
        if (activePlanIds.has(planId)) continue;
        const id = watchIdFromPlan(planId);
        const current = id === null ? undefined : this.store.watches.get(id);
        if (!current || !this.enabled(current)) await this.engine.remove(state.id);
      }
    } finally {
      this.ticking = false;
    }
    await this.flushPending();
  }

  private buildPrompt(watch: WatchRecord, alert: AlertView, now: Date): string {
    const detail = detailRecord(alert);
    const from = textOf(detail, 'from');
    const to = textOf(detail, 'to');
    const reason = textOf(detail, 'reason');
    const price = watchPrice(alert.raw);
    const originTask =
      watch.createdTaskId === null ? undefined : this.store.tasks.get(watch.createdTaskId);
    const originLine =
      originTask === undefined
        ? '发起这条盯盘的任务：未知'
        : `发起这条盯盘的任务：${originTask.title ?? '未命名'}（${originTask.startedAt}）`;
    const note = watch.note === '' ? '（无）' : watch.note;
    return [
      '盯盘触发了。先取实时数据核对；分析后判断用户是否需要立即知道——需要就调用 notify_user（一句结论 + 关键数字 + 数据时间），不需要就只在这里写结论；需要调整或撤掉这条盯盘就用 watch_plan_update / watch_plan_delete；不下单。',
      '',
      `标的：${watch.name === '' ? watch.code : `${watch.name}（${watch.code}）`}`,
      `条件：${describeWatch(watch)}`,
      watch.plan['giveup'] === undefined ? '' : describeGiveUp(watch.plan),
      `设置理由：${note}`,
      `触发：${from === '' ? '—' : from} → ${to === '' ? '—' : to}${reason === '' ? '' : `（${reason}）`}`,
      `触发时价格：${price === null ? '未提供' : String(price)}`,
      `触发时间：${alert.ts ?? now.toISOString()}`,
      originLine,
      '',
      '盯盘只会唤醒你做分析，绝不下单；模拟盘下单仍走原有审批。',
    ]
      .filter((line) => line !== '')
      .join('\n');
  }

  async handleTrigger(input: WatchTriggerInput): Promise<WatchTriggerResult> {
    const id = watchIdFromPlan(input.planId);
    if (id === null) return { status: 'skipped', reason: 'not_chives_plan' };
    const watch = this.store.watches.get(id);
    if (watch === undefined) return { status: 'skipped', reason: 'unknown_watch' };
    if (!this.registry.isHired(watch.botId)) return { status: 'skipped', reason: 'bot_not_hired' };
    if (!this.enabled(watch)) return { status: 'skipped', reason: 'watch_not_active' };
    const resumed = this.store.settings.get<boolean | string>(PAUSE_KEY + id);
    if (typeof resumed === 'string' && (!input.alert.ts || Date.parse(input.alert.ts) < Date.parse(resumed))) {
      return { status: 'skipped', reason: 'before_watch_resume' };
    }
    const to = stateOf(input.alert);
    let current = watch;
    const alertName = input.alert.name.replace(/\s+/g, '');
    if (current.name === '' && alertName !== '') {
      current = this.store.watches.update(watch.id, { name: alertName }) ?? current;
    }
    const engineState = to === '' ? current.engineState : to;
    if (to === 'await_confirm') {
      this.store.watches.update(watch.id, { engineState });
      return { status: 'skipped', reason: 'await_confirm' };
    }
    if (to !== 'execute' && to !== 'abandon' && to !== 'exit') {
      this.store.watches.update(watch.id, { engineState });
      return { status: 'skipped', reason: 'state_change' };
    }
    const settings = readProactiveSettings(this.store);
    if (!settings.enabled) return { status: 'skipped', reason: 'disabled' };
    if (this.store.watches.get(watch.id)?.repeat === true && watch.triggeredAt !== null) {
      const elapsed = input.now.getTime() - Date.parse(watch.triggeredAt);
      if (Number.isFinite(elapsed) && elapsed < REPEAT_COOLDOWN_MS) {
        return { status: 'skipped', reason: 'repeat_cooldown' };
      }
    }
    if (settings.observeOnly) return { status: 'skipped', reason: 'observe_only' };
    const body = `${current.name === '' ? current.code : current.name} ${describeWatch(current)}，自动分析已关闭`;
    if (!settings.autoAnalysis) {
      const notification = this.notifications.notifyGuardrail(
        watch.botId,
        watch.createdTaskId ?? '',
        `盯盘已触发（${watch.label}）`,
        body,
      );
      this.notifications.publishCreated(notification);
      const message = this.store.messages.append({
        id: randomUUID(),
        botId: watch.botId,
        taskId: null,
        role: 'system',
        kind: 'notice',
        content: `盯盘已触发（${describeWatch(watch)}），自动分析已关闭`,
        meta: { code: 'auto_analysis_disabled', watchId: watch.id },
        createdAt: input.now.toISOString(),
      });
      this.bus.publish({
        type: 'message.created',
        botId: watch.botId,
        taskId: null,
        message: toMessageDto(message),
      });
      await this.markTriggered(current, null, to, input.now, '盯盘触发，自动分析已关闭');
      return { status: 'skipped', reason: 'auto_analysis_disabled' };
    }
    const prompt = this.buildPrompt(current, input.alert, input.now);
    const display = current.name === '' ? current.code : current.name;
    const conditions = Array.isArray(current.plan['stock'])
      ? (current.plan['stock'] as JsonRecord[])
      : [];
    const primary = conditions[0] === undefined ? current.label : describeCondition(conditions[0]);
    let result;
    try {
      result = await this.orchestrator.submitProactive(current.botId, {
        title: `盯盘触发 · ${display} · ${primary}`,
        label: '盯盘触发',
        prompt,
        origin: 'alert',
        meta: {
          source: 'cn-watch',
          ruleId: input.alert.ruleId,
          code: current.code,
          watchId: current.id,
          planId: input.planId,
          originTaskId: current.createdTaskId,
        },
      });
    } catch (error) {
      this.log('watch trigger queued until the bot is free', error);
      if (!this.pending.has(current.id)) {
        this.pending.set(current.id, { input, since: input.now.getTime() });
        this.addEvent(current, 'trigger_queued', 'system', null, '盯盘已触发，bot 正忙，当前任务结束后自动唤醒');
      }
      return { status: 'skipped', reason: 'bot_busy_queued' };
    }
    await this.markTriggered(current, result.taskId, to, input.now);
    return { status: 'started', taskId: result.taskId };
  }

  private async markTriggered(
    watch: WatchRecord,
    taskId: string | null,
    state: string,
    now: Date,
    detail = '盯盘触发，已唤醒 bot',
  ): Promise<void> {
    const oneShot = watch.repeat !== true;
    const updated = this.store.watches.update(watch.id, {
      status: oneShot ? 'triggered' : 'active',
      engineState: state,
      triggeredAt: now.toISOString(),
      triggerTaskId: taskId,
      updatedAt: now.toISOString(),
    });
    const result = updated ?? watch;
    this.addEvent(
      result,
      'triggered',
      'system',
      taskId,
      detail,
      null,
      { state, taskId },
    );
    this.syncCardStatus(result, oneShot ? 'triggered' : 'active');
    this.publish('watch.updated', result);
    if (oneShot) {
      await this.engine.remove(savedPlanId(watch));
    }
  }
}

export { DEFAULT_EXPIRES_DAYS, MAX_LABEL_CHARS, MAX_NOTE_CHARS };
export type { WatchCreateInput, WatchUpdateInput, WatchPlan };
