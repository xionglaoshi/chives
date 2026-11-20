import { watchIdFromPlan } from '../watches/plan.js';
/** Polls the two read-only watch engines, applies cost guardrails, starts bot tasks. */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import type { BotRegistry } from '../bots/index.js';
import type { Orchestrator } from '../orchestrator.js';
import { readProactiveSettings } from '../proactive-settings.js';
import type { AlertEventRecord, Store } from '../store/index.js';
import type { WatchService } from '../watches/service.js';
import { shanghaiDayKey } from '../time.js';
import { type AlertsConfig, type AlertSourceConfig } from './config.js';

export const STOP_FILE = 'STOP';
export const MAX_TIMEOUT_TIMERS = 64;

export const NOTIFY_INSTRUCTION =
  '分析后判断用户是否需要立即知道：需要就调用 notify_user（一句结论 + 关键数字 + 数据时间），不需要就只在这里写结论。不下单。';

const RULE_LABELS: Record<string, string> = {
  pct_change: '涨跌幅',
  vwap_deviation: '均价偏离',
  limit_proximity: '接近涨跌停',
  price_cross: '价格突破',
  volume_surge: '放量',
};

export interface AlertServiceOptions {
  config: AlertsConfig;
  store: Store;
  registry: BotRegistry;
  orchestrator: Orchestrator;
  now: () => Date;
  dataDir: string;
  repoRoot: string;
  /** T139: `chives-*` plan alerts wake the owning bot instead of being skipped. */
  watches?: WatchService;
  fetchImpl?: typeof fetch;
  log?: (message: string, detail?: unknown) => void;
  /** Injected in tests so no real timer is left behind. */
  scheduleTimeout?: (fn: () => void, ms: number) => { unref?: () => void };
  clearScheduledTimeout?: (handle: { unref?: () => void }) => void;
}

type RawAlert = Record<string, unknown>;

export interface AlertView {
  id: number;
  ts: string | null;
  code: string;
  name: string;
  ruleId: string;
  ruleType: string;
  title: string;
  /** strategy-hub events carry these; other sources leave them empty. */
  strategyId: string;
  event: string;
  level: string;
  raw: RawAlert;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function globMatch(pattern: string, value: string): boolean {
  if (pattern === '*') return true;
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*');
  return new RegExp(`^${escaped}$`, 'i').test(value);
}

function ruleTypeOf(raw: RawAlert): string {
  const value = raw['rule_type'];
  if (typeof value === 'string') return value;
  const ruleId = text(raw['rule_id']);
  if (ruleId.startsWith('plan:')) return 'plan';
  return '';
}

export function toAlertView(raw: RawAlert): AlertView | null {
  const id = raw['id'];
  if (typeof id !== 'number' || !Number.isInteger(id) || id <= 0) return null;
  const object = isRecord(raw['object']) ? raw['object'] : undefined;
  const detail = isRecord(raw['detail']) ? raw['detail'] : undefined;
  const code = text(raw['code']) || text(object?.['code']);
  const name = text(raw['name']) || text(object?.['name']);
  const ruleId = text(raw['rule_id']);
  const ruleType = ruleTypeOf(raw);
  const rawTitle = text(raw['title']);
  const label = rawTitle !== '' ? rawTitle : (RULE_LABELS[ruleType] ?? ruleId);
  const ts =
    text(raw['ts']) ||
    text(raw['created_at']) ||
    (typeof raw['created_at'] === 'string' ? raw['created_at'] : '');
  return {
    id,
    ts: ts === '' ? null : ts,
    code: code.toUpperCase(),
    name,
    ruleId,
    ruleType,
    title:
      rawTitle !== '' && (name === '' || rawTitle.startsWith(name))
        ? rawTitle
        : `${name} ${label}`.trim() || `告警 ${id}`,
    strategyId: text(raw['strategy_id']) || text(detail?.['strategy_id']),
    event: text(raw['event']) || text(detail?.['event']),
    level: text(raw['level']) || text(detail?.['level']),
    raw,
  };
}

export function isPlanAlert(alert: AlertView): boolean {
  return alert.ruleType === 'plan' || alert.ruleId.startsWith('plan:');
}

/** Escapes the two characters that could close the `<alert_data>` block early. */
export function alertJson(alert: RawAlert): string {
  return JSON.stringify(alert, null, 2).replace(/</g, '\\u003c').replace(/>/g, '\\u003e');
}

export function alertDataBlock(alert: RawAlert): string {
  return `<alert_data>\n${alertJson(alert)}\n</alert_data>`;
}

function isoOrNull(date: Date): string {
  return Number.isFinite(date.getTime()) ? date.toISOString() : '';
}

export class AlertService {
  private readonly config: AlertsConfig;
  private readonly store: Store;
  private readonly registry: BotRegistry;
  private readonly orchestrator: Orchestrator;
  private readonly now: () => Date;
  private readonly dataDir: string;
  private readonly fetchImpl: typeof fetch;
  private readonly log: (message: string, detail?: unknown) => void;
  private readonly scheduleTimeout: (fn: () => void, ms: number) => { unref?: () => void };
  private readonly clearScheduledTimeout: (handle: { unref?: () => void }) => void;
  private readonly presetText: string;
  private readonly presetHasPlaceholder: boolean;
  private readonly watches: WatchService | undefined;
  private readonly nextAttempt = new Map<string, number>();
  private readonly failures = new Map<string, number>();
  private readonly timers = new Set<{ unref?: () => void }>();
  private timer: ReturnType<typeof setInterval> | undefined;
  private ticking = false;

  constructor(options: AlertServiceOptions) {
    this.config = options.config;
    this.store = options.store;
    this.registry = options.registry;
    this.orchestrator = options.orchestrator;
    this.now = options.now;
    this.dataDir = options.dataDir;
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.log = options.log ?? ((message, detail) => console.log(message, detail ?? ''));
    this.scheduleTimeout =
      options.scheduleTimeout ??
      ((fn, ms) => {
        const handle = setTimeout(fn, ms);
        handle.unref();
        return handle;
      });
    this.clearScheduledTimeout =
      options.clearScheduledTimeout ??
      ((handle) => clearTimeout(handle as ReturnType<typeof setTimeout>));
    this.presetText = this.loadPreset(options.repoRoot);
    this.presetHasPlaceholder = this.presetText.includes('{alert_json}');
    this.watches = options.watches;
  }

  private loadPreset(repoRoot: string): string {
    try {
      return readFileSync(join(repoRoot, 'presets', 'finance', 'alert-analysis.md'), 'utf8');
    } catch {
      return '这是一次告警触发的只读分析：不下单、不调用 paper_ 开头的工具。\n\n{alert_json}';
    }
  }

  start(): void {
    if (this.timer !== undefined) return;
    const interval = this.config.limits.pollSeconds * 1000;
    this.timer = setInterval(() => {
      void this.tick().catch((error: unknown) => this.log('alert poll failed', error));
    }, interval);
    this.timer.unref();
    void this.tick().catch(() => undefined);
  }

  close(): void {
    if (this.timer !== undefined) {
      clearInterval(this.timer);
      this.timer = undefined;
    }
    for (const handle of this.timers) this.clearScheduledTimeout(handle);
    this.timers.clear();
  }

  async tick(): Promise<void> {
    if (this.ticking) return;
    this.ticking = true;
    try {
      const now = this.now();
      for (const source of this.config.sources) {
        if (!source.enabled) continue;
        const nextAt = this.nextAttempt.get(source.name) ?? 0;
        if (now.getTime() < nextAt) continue;
        await this.pollSource(source, now);
      }
    } finally {
      this.ticking = false;
    }
  }

  private cursorKey(source: AlertSourceConfig): string {
    return `alerts.cursor.${source.name}`;
  }

  private cursor(source: AlertSourceConfig): number | undefined {
    const value = this.store.settings.get<number>(this.cursorKey(source));
    return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : undefined;
  }

  private setCursor(source: AlertSourceConfig, id: number): void {
    this.store.settings.set(this.cursorKey(source), id);
  }

  private async fetchAlerts(source: AlertSourceConfig, cursor: number): Promise<RawAlert[]> {
    const url = `${source.url}/alerts?${source.cursorParam}=${cursor}&limit=${source.batchLimit}`;
    const controller = new AbortController();
    const timer = this.scheduleTimeout(() => controller.abort(), 10_000);
    try {
      const response = await this.fetchImpl(url, {
        method: 'GET',
        headers: { accept: 'application/json' },
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`engine returned HTTP ${response.status}`);
      const body: unknown = await response.json();
      if (!isRecord(body)) throw new Error('engine response is not an object');
      if (body['ok'] === false) throw new Error('engine reported ok:false');
      const alerts = body['alerts'];
      if (!Array.isArray(alerts)) throw new Error('engine response has no alerts array');
      return alerts.filter(isRecord);
    } finally {
      this.clearScheduledTimeout(timer);
    }
  }

  private markFailure(source: AlertSourceConfig, now: Date): void {
    const count = (this.failures.get(source.name) ?? 0) + 1;
    this.failures.set(source.name, count);
    const base = this.config.limits.pollSeconds * 1000;
    const delay = Math.min(60_000, base * 2 ** Math.min(count, 6));
    this.nextAttempt.set(source.name, now.getTime() + delay);
    if (count === 1) this.log(`${source.name} unreachable; retrying with backoff`);
  }

  private markSuccess(source: AlertSourceConfig): void {
    this.failures.set(source.name, 0);
    this.nextAttempt.set(source.name, 0);
  }

  private async pollSource(source: AlertSourceConfig, now: Date): Promise<void> {
    if (source.name === 'strategy-hub') {
      await this.pollStrategy(source, now);
      return;
    }
    const known = this.cursor(source);
    try {
      if (known === undefined) {
        const historical = await this.fetchAlerts(source, 0);
        const latest = historical.reduce((max, alert) => {
          const id = alert['id'];
          return typeof id === 'number' && id > max ? id : max;
        }, 0);
        this.setCursor(source, latest);
        this.markSuccess(source);
        this.log(`${source.name} baseline set to ${latest}; existing alerts are not replayed`);
        return;
      }
      const cursor = known;
      const fetched = await this.fetchAlerts(source, cursor);
      this.markSuccess(source);
      const views = fetched
        .map(toAlertView)
        .filter((alert): alert is AlertView => alert !== null)
        .filter((alert) => alert.id > cursor)
        .sort((left, right) => left.id - right.id);
      if (views.length === 0) return;
      const overflow = views.slice(0, Math.max(0, views.length - this.config.limits.batchSize));
      const batch = views.slice(overflow.length);
      for (const alert of overflow) {
        this.record(source, alert, 'skipped', isPlanAlert(alert) ? 'plan_alert' : 'queue_overflow', now);
        this.setCursor(source, alert.id);
      }
      for (const alert of batch) {
        await this.processAlert(source, alert, now);
        this.setCursor(source, alert.id);
      }
    } catch (error) {
      this.markFailure(source, now);
      void error;
    }
  }

  private strategyBots(strategyId: string): string[] {
    return this.registry
      .list()
      .filter((bot) => bot.strategies?.includes(strategyId) === true)
      .map((bot) => bot.id);
  }

  /** strategy-hub polls coalesce all of one trading day's events per bot into one wake. */
  private async pollStrategy(source: AlertSourceConfig, now: Date): Promise<void> {
    const known = this.cursor(source);
    try {
      if (known === undefined) {
        let cursor = 0;
        let latest = 0;
        for (let page = 0; page < 200; page += 1) {
          const historical = await this.fetchAlerts(source, cursor);
          latest = historical.reduce((max, alert) => {
            const id = alert['id'];
            return typeof id === 'number' && id > max ? id : max;
          }, latest);
          if (historical.length < source.batchLimit || latest <= cursor) break;
          cursor = latest;
        }
        this.setCursor(source, latest);
        this.markSuccess(source);
        this.log(`${source.name} baseline set to ${latest}; existing strategy alerts are not replayed`);
        return;
      }
      let cursor = known;
      const collected: RawAlert[] = [];
      for (let page = 0; page < 20; page += 1) {
        const batch = await this.fetchAlerts(source, cursor);
        const fresh = batch.filter((alert) => {
          const id = alert['id'];
          return typeof id === 'number' && Number.isInteger(id) && id > cursor;
        });
        collected.push(...fresh);
        const newest = fresh.reduce((max, alert) => {
          const id = alert['id'];
          return typeof id === 'number' && id > max ? id : max;
        }, cursor);
        if (batch.length < source.batchLimit || newest <= cursor) break;
        cursor = newest;
      }
      this.markSuccess(source);
      const views = collected
        .map(toAlertView)
        .filter((alert): alert is AlertView => alert !== null)
        .sort((left, right) => left.id - right.id);
      if (views.length === 0) return;

      type Group = { botId: string; strategyId: string; day: string; alerts: AlertView[] };
      const groups = new Map<string, Group>();
      for (const alert of views) {
        if (alert.strategyId === '') {
          this.skip(source, alert, 'not_strategy_event', now);
          continue;
        }
        if (alert.level !== 'important') {
          this.skip(source, alert, 'not_important', now);
          continue;
        }
        if (alert.ts === null || !Number.isFinite(Date.parse(alert.ts))) {
          this.skip(source, alert, 'invalid_alert_ts', now);
          continue;
        }
        const bots = this.strategyBots(alert.strategyId);
        if (bots.length === 0) {
          this.skip(source, alert, 'not_subscribed', now);
          continue;
        }
        const eventDate = alert.raw['event_date'];
        const day =
          typeof eventDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(eventDate)
            ? eventDate
            : shanghaiDayKey(new Date(alert.ts));
        for (const botId of bots) {
          const key = `${botId}::${alert.strategyId}::${day}`;
          const group = groups.get(key) ?? { botId, strategyId: alert.strategyId, day, alerts: [] };
          group.alerts.push(alert);
          groups.set(key, group);
        }
      }
      for (const group of groups.values()) {
        await this.processStrategyGroup(source, group.botId, group.strategyId, group.day, group.alerts, now);
      }
      if (views.length > 0) this.setCursor(source, views[views.length - 1]?.id ?? known);
    } catch (error) {
      this.markFailure(source, now);
      void error;
    }
  }

  private async processStrategyGroup(
    source: AlertSourceConfig,
    botId: string,
    strategyId: string,
    day: string,
    alerts: AlertView[],
    now: Date,
  ): Promise<void> {
    const skipAll = (reason: string): void => {
      for (const alert of alerts) this.skip(source, alert, reason, now);
    };
    if (this.stopRequested()) {
      skipAll('kill_switch');
      return;
    }
    const settings = readProactiveSettings(this.store);
    if (!settings.enabled) {
      skipAll('disabled');
      return;
    }
    const bot = this.registry.get(botId);
    if (bot === undefined) {
      skipAll('unknown_bot');
      return;
    }
    const markerKey = `alerts.strategyDay.${botId}.${strategyId}`;
    if (this.store.settings.get<string>(markerKey) === day) {
      skipAll('already_woken_today');
      return;
    }
    const previous = this.store.alertEvents.lastStartedAtForStrategy(source.name, strategyId);
    if (previous !== null) {
      const previousAt = Date.parse(previous);
      if (Number.isFinite(previousAt) && now.getTime() - previousAt < this.config.limits.cooldownSeconds * 1000) {
        skipAll('cooldown');
        return;
      }
    }
    if (!settings.autoAnalysis) {
      skipAll('auto_analysis_disabled');
      return;
    }
    if (this.config.limits.observeOnly || settings.observeOnly) {
      skipAll('observe_only');
      return;
    }
    const title = `${alerts[0]?.name ?? bot.name} 策略事件 · ${day} · ${alerts.length} 条`;
    const codes = [...new Set(alerts.map((alert) => alert.code).filter((code) => code !== ''))];
    const rows = alerts.map((alert) => ({
      id: alert.id,
      code: alert.code,
      name: alert.name,
      event: alert.event,
      title: alert.title,
      created_at: alert.ts,
    }));
    const prompt = [
      '<strategy_events>',
      JSON.stringify(rows, null, 2),
      '</strategy_events>',
      '',
      `这是 ${strategyId} 策略在同一交易日（${day}）产生的全部重要事件，服务端已合并为一次唤醒。`,
      '请按以下顺序处理：',
      `1. 先调用 strategy_pools，strategy_id 填 "${strategyId}"，看当日两个池的排序与分项。`,
      `2. 对下列每个 code 调用 strategy_round（strategy_id="${strategyId}"）取当前轮次、事件与分项：${codes.join('、') || '（无代码）'}。`,
      '3. 先给结论（今日池子变化），再列优先级一/二、主升浪池前列与移出、需要人工复核的票与不确定性；规则筛选结果，不是买卖建议。',
      '4. 值得用户立即知道才调用 notify_user（一条结论 + 关键数字 + 数据日期），否则只在时间线写结论。',
      '',
      NOTIFY_INSTRUCTION,
    ].join('\n');
    try {
      const result = await this.orchestrator.submitProactive(botId, {
        title,
        label: '策略事件',
        prompt,
        origin: 'alert',
        meta: {
          source: source.name,
          strategyId,
          alertId: alerts[0]?.id ?? null,
          count: alerts.length,
          day,
        },
      });
      for (const alert of alerts) this.record(source, alert, 'started', null, now, result.taskId);
      this.store.settings.set(markerKey, day);
      this.scheduleRunTimeout(result.taskId);
    } catch (error) {
      skipAll('bot_busy');
      void error;
    }
  }

  private routeFor(source: AlertSourceConfig, alert: AlertView): string | null {
    for (const route of this.config.routes) {
      if (route.source !== source.name && route.source !== '*') continue;
      if (!globMatch(route.ruleId, alert.ruleId)) continue;
      if (!globMatch(route.code, alert.code)) continue;
      return route.bot;
    }
    return null;
  }

  private record(
    source: AlertSourceConfig,
    alert: AlertView,
    status: 'started' | 'skipped',
    reason: string | null,
    now: Date,
    taskId: string | null = null,
  ): AlertEventRecord {
    return this.store.alertEvents.add({
      source: source.name,
      alertId: alert.id,
      alertTs: alert.ts,
      code: alert.code || null,
      name: alert.name || null,
      ruleId: alert.ruleId || null,
      status,
      reason,
      taskId,
      createdAt: now.toISOString(),
    });
  }

  private skip(
    source: AlertSourceConfig,
    alert: AlertView,
    reason: string,
    now: Date,
  ): void {
    this.record(source, alert, 'skipped', reason, now);
  }

  private cooldownActive(source: AlertSourceConfig, alert: AlertView, alertTs: Date): boolean {
    const previous = this.store.alertEvents.lastStartedTs(source.name, alert.code, alert.ruleId);
    if (previous === null) return false;
    const previousAt = Date.parse(previous);
    if (!Number.isFinite(previousAt)) return false;
    return alertTs.getTime() - previousAt < this.config.limits.cooldownSeconds * 1000;
  }

  private stopRequested(): boolean {
    return existsSync(join(this.dataDir, STOP_FILE));
  }

  private async processAlert(
    source: AlertSourceConfig,
    alert: AlertView,
    now: Date,
  ): Promise<void> {
    if (this.stopRequested()) {
      this.skip(source, alert, 'kill_switch', now);
      return;
    }
    const settings = readProactiveSettings(this.store);
    if (!settings.enabled) {
      this.skip(source, alert, 'disabled', now);
      return;
    }
    if (isPlanAlert(alert)) {
      const detail = isRecord(alert.raw['detail']) ? alert.raw['detail'] : undefined;
      const planId = text(detail?.['plan_id']) || (alert.ruleId.startsWith('plan:') ? alert.ruleId.slice(5) : '');
      if (watchIdFromPlan(planId) !== null && this.watches !== undefined) {
        if (alert.ts === null || !Number.isFinite(Date.parse(alert.ts))) {
          this.skip(source, alert, 'invalid_alert_ts', now);
          return;
        }
        const alertTs = new Date(alert.ts);
        if ((now.getTime() - alertTs.getTime()) / 1000 > this.config.limits.maxAlertAgeSeconds) {
          this.skip(source, alert, 'stale_alert', now);
          return;
        }
        const result = await this.watches.handleTrigger({ planId, alert, now });
        if (result.status === 'started') {
          this.record(source, alert, 'started', null, now, result.taskId);
          this.scheduleRunTimeout(result.taskId);
        } else {
          this.skip(source, alert, result.reason, now);
        }
        return;
      }
      // Plan alerts with any other prefix belong to the hub; never touch them.
      this.skip(source, alert, 'plan_alert', now);
      return;
    }
    const botId = this.routeFor(source, alert);
    if (botId === null) {
      this.skip(source, alert, 'not_selected', now);
      return;
    }
    if (this.registry.get(botId) === undefined) {
      this.skip(source, alert, 'unknown_bot', now);
      return;
    }
    if (alert.ts === null || !Number.isFinite(Date.parse(alert.ts))) {
      this.skip(source, alert, 'invalid_alert_ts', now);
      return;
    }
    const alertTs = new Date(alert.ts);
    const age = (now.getTime() - alertTs.getTime()) / 1000;
    if (age > this.config.limits.maxAlertAgeSeconds) {
      this.skip(source, alert, 'stale_alert', now);
      return;
    }
    if (this.cooldownActive(source, alert, alertTs)) {
      this.skip(source, alert, 'cooldown', now);
      return;
    }
    if (!settings.autoAnalysis) {
      this.skip(source, alert, 'auto_analysis_disabled', now);
      return;
    }
    if (this.config.limits.observeOnly || settings.observeOnly) {
      this.skip(source, alert, 'observe_only', now);
      return;
    }
    const basePrompt = this.presetHasPlaceholder
      ? this.presetText.replace('{alert_json}', () => alertJson(alert.raw))
      : `${this.presetText}\n\n${alertDataBlock(alert.raw)}`;
    const prompt = `${basePrompt}\n\n${NOTIFY_INSTRUCTION}`;
    try {
      const result = await this.orchestrator.submitProactive(botId, {
        title: alert.title,
        label: '盯盘告警',
        prompt,
        origin: 'alert',
        meta: {
          source: source.name,
          alertId: alert.id,
          ruleId: alert.ruleId,
          code: alert.code,
        },
      });
      this.record(source, alert, 'started', null, now, result.taskId);
      this.scheduleRunTimeout(result.taskId);
    } catch (error) {
      this.skip(source, alert, 'bot_busy', now);
      void error;
    }
  }



  private scheduleRunTimeout(taskId: string): void {
    if (this.timers.size >= MAX_TIMEOUT_TIMERS) return;
    const handle = this.scheduleTimeout(() => {
      this.timers.delete(handle);
      const task = this.store.tasks.get(taskId);
      if (task === undefined || task.status !== 'running') return;
      try {
        this.orchestrator.cancelTask(taskId);
      } catch {
        // The turn may have finished between the check and the cancel.
      }
    }, this.config.limits.runTimeoutSeconds * 1000);
    this.timers.add(handle);
  }

  events(limit: number): AlertEventRecord[] {
    return this.store.alertEvents.list(Math.max(1, Math.min(limit, 200)));
  }

  /** One line per source for the settings page / tests. */
  sourceStatus(): Array<{ name: string; enabled: boolean; cursor: number | null }> {
    return this.config.sources.map((source) => ({
      name: source.name,
      enabled: source.enabled,
      cursor: this.cursor(source) ?? null,
    }));
  }
}

export { isoOrNull };
