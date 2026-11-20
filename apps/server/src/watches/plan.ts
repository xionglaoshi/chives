/** Local validation for bot-owned watch plans; mirrors cn-watch's Plan schema. */

import { shanghaiDayKey } from '../time.js';
import type { JsonRecord } from '../store/index.js';

export const MAX_LABEL_CHARS = 40;
export const MAX_NOTE_CHARS = 200;
export const MAX_WATCHES_PER_BOT = 20;
export const MAX_CHIVES_WATCHES = 25;
export const MIN_EXPIRES_DAYS = 1;
export const MAX_EXPIRES_DAYS = 30;
export const DEFAULT_EXPIRES_DAYS = 5;
export const MAX_CONDITIONS = 6;

export type WatchMatch = 'any' | 'all';

export interface WatchCreateInput {
  code: unknown;
  label: unknown;
  when: unknown;
  match?: unknown;
  giveUp?: unknown;
  market?: unknown;
  expiresInDays?: unknown;
  note?: unknown;
  repeat?: unknown;
}

export interface WatchUpdateInput {
  code?: unknown;
  label?: unknown;
  when?: unknown;
  match?: unknown;
  giveUp?: unknown;
  market?: unknown;
  expiresInDays?: unknown;
  note?: unknown;
  repeat?: unknown;
}

export interface NormalizedWatchInput {
  code: string;
  label: string;
  note: string;
  match: WatchMatch;
  repeat: boolean;
  expiresInDays: number;
  when: JsonRecord[];
  giveUp: JsonRecord[];
  market: JsonRecord[];
}

const STOCK_TYPES = new Set([
  'price_cross',
  'price_in_range',
  'pct_change',
  'open_pct',
  'volume_ratio',
]);
const MARKET_TYPES = new Set(['index_pct', 'regime']);
const INDEX_CODES = new Set([
  '000001.SH',
  '399001.SZ',
  '399006.SZ',
  '000300.SH',
  '000852.SH',
  '000688.SH',
]);
const REGIMES = new Set(['strong', 'neutral', 'weak']);

export class WatchValidationError extends Error {
  readonly code: string;
  readonly field: string | undefined;

  constructor(code: string, message: string, field?: string) {
    super(message);
    this.name = 'WatchValidationError';
    this.code = code;
    this.field = field;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function inferSuffix(digits: string): string {
  return '569'.includes(digits[0] ?? '') ? 'SH' : 'SZ';
}

/** Rejects Beijing exchange and index families exactly like cn-watch. */
export function normalizeWatchCode(value: unknown): string {
  let raw: string;
  if (typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 999999) {
    raw = String(value).padStart(6, '0');
  } else if (typeof value === 'string') {
    raw = value.trim().toUpperCase();
  } else {
    throw new WatchValidationError('invalid_symbol', '代码格式错误：需要 6 位数字', 'code');
  }
  let suffix = '';
  let digits = raw;
  if (raw.includes('.')) {
    const parts = raw.split('.');
    digits = parts[0] ?? '';
    suffix = parts[1] ?? '';
    if (suffix === 'BJ') {
      throw new WatchValidationError('unsupported_market', '暂不支持北交所代码', 'code');
    }
    if (suffix !== 'SH' && suffix !== 'SZ') {
      throw new WatchValidationError('invalid_symbol', `代码格式错误：${raw}`, 'code');
    }
  }
  if (!/^\d{6}$/.test(digits)) {
    throw new WatchValidationError('invalid_symbol', `代码格式错误：${raw}`, 'code');
  }
  if (/^[48]/.test(digits)) {
    throw new WatchValidationError('unsupported_market', '暂不支持北交所代码', 'code');
  }
  if (suffix === '') suffix = inferSuffix(digits);
  if (
    digits === '999999' ||
    digits.startsWith('399') ||
    (suffix === 'SH' && digits.startsWith('000'))
  ) {
    throw new WatchValidationError('unsupported_instrument', '暂不支持指数代码', 'code');
  }
  return `${digits}.${suffix}`;
}

function numberInRange(
  value: unknown,
  where: string,
  minimum: number,
  maximum: number,
  exclusiveMinimum = false,
): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new WatchValidationError('invalid_condition', `${where} 必须是数字`, where);
  }
  const tooLow = exclusiveMinimum ? value <= minimum : value < minimum;
  if (tooLow || value > maximum) {
    throw new WatchValidationError('invalid_condition', `${where} 超出范围`, where);
  }
  return value;
}

function stringField(value: unknown, where: string, allowed: readonly string[]): string {
  if (typeof value !== 'string' || !allowed.includes(value)) {
    throw new WatchValidationError('invalid_condition', `${where} 不合法`, where);
  }
  return value;
}

function onlyKeys(raw: Record<string, unknown>, allowed: readonly string[], where: string): void {
  const extra = Object.keys(raw).find((key) => !allowed.includes(key));
  if (extra !== undefined) {
    throw new WatchValidationError('invalid_condition', `${where}.${extra} 是未知字段`, `${where}.${extra}`);
  }
}

/** Normalizes one condition into the exact object cn-watch's validator accepts. */
export function validateCondition(
  value: unknown,
  group: 'stock' | 'market',
  where: string,
): JsonRecord {
  if (!isRecord(value)) {
    throw new WatchValidationError('invalid_condition', `${where} 必须是对象`, where);
  }
  const type = value['type'];
  if (typeof type !== 'string') {
    throw new WatchValidationError('invalid_condition', `${where}.type 缺失`, `${where}.type`);
  }
  const allowed = group === 'stock' ? STOCK_TYPES : MARKET_TYPES;
  if (!allowed.has(type)) {
    throw new WatchValidationError(
      'invalid_condition',
      `${where}.type 不支持 ${type}`,
      `${where}.type`,
    );
  }
  if (group === 'stock') {
    switch (type) {
      case 'price_cross': {
        onlyKeys(value, ['type', 'direction', 'level'], where);
        return {
          type,
          direction: stringField(value['direction'], `${where}.direction`, ['up', 'down']),
          level: numberInRange(value['level'], `${where}.level`, 0, Number.MAX_SAFE_INTEGER, true),
        };
      }
      case 'price_in_range': {
        onlyKeys(value, ['type', 'lo', 'hi'], where);
        const lo = numberInRange(value['lo'], `${where}.lo`, 0, Number.MAX_SAFE_INTEGER, true);
        const hi = numberInRange(value['hi'], `${where}.hi`, 0, Number.MAX_SAFE_INTEGER, true);
        if (lo >= hi) {
          throw new WatchValidationError('invalid_condition', `${where} 要求 lo < hi`, `${where}.lo`);
        }
        return { type, lo, hi };
      }
      case 'pct_change': {
        onlyKeys(value, ['type', 'direction', 'threshold_pct'], where);
        return {
          type,
          direction: stringField(value['direction'], `${where}.direction`, ['up', 'down']),
          threshold_pct: numberInRange(
            value['threshold_pct'],
            `${where}.threshold_pct`,
            0,
            100,
            true,
          ),
        };
      }
      case 'open_pct': {
        onlyKeys(value, ['type', 'op', 'value'], where);
        return {
          type,
          op: stringField(value['op'], `${where}.op`, ['>=', '<=']),
          value: numberInRange(value['value'], `${where}.value`, -100, 100),
        };
      }
      default: {
        onlyKeys(value, ['type', 'op', 'value'], where);
        return {
          type,
          op: stringField(value['op'], `${where}.op`, ['>=', '<=']),
          value: numberInRange(value['value'], `${where}.value`, 0, 1000, true),
        };
      }
    }
  }
  if (type === 'index_pct') {
    onlyKeys(value, ['type', 'code', 'op', 'value'], where);
    const code = value['code'];
    if (typeof code !== 'string' || !INDEX_CODES.has(code)) {
      throw new WatchValidationError('invalid_condition', `${where}.code 不在允许的指数内`, `${where}.code`);
    }
    return {
      type,
      code,
      op: stringField(value['op'], `${where}.op`, ['>=', '<=']),
      value: numberInRange(value['value'], `${where}.value`, -100, 100),
    };
  }
  onlyKeys(value, ['type', 'values'], where);
  const values = value['values'];
  if (!Array.isArray(values) || values.length === 0) {
    throw new WatchValidationError('invalid_condition', `${where}.values 必须是非空数组`, `${where}.values`);
  }
  const cleaned: string[] = [];
  for (const entry of values) {
    if (typeof entry !== 'string' || !REGIMES.has(entry)) {
      throw new WatchValidationError(
        'invalid_condition',
        `${where}.values 只接受 strong/neutral/weak`,
        `${where}.values`,
      );
    }
    if (cleaned.includes(entry)) {
      throw new WatchValidationError('invalid_condition', `${where}.values 不能重复`, `${where}.values`);
    }
    cleaned.push(entry);
  }
  return { type, values: cleaned };
}

function conditionList(
  value: unknown,
  group: 'stock' | 'market',
  where: string,
  minimum: number,
): JsonRecord[] {
  if (value === undefined) {
    if (minimum === 0) return [];
    throw new WatchValidationError('invalid_arguments', `${where} 至少需要 1 条`, where);
  }
  if (!Array.isArray(value)) {
    throw new WatchValidationError('invalid_arguments', `${where} 必须是数组`, where);
  }
  if (value.length < minimum) {
    throw new WatchValidationError('invalid_arguments', `${where} 至少需要 ${minimum} 条`, where);
  }
  if (value.length > MAX_CONDITIONS) {
    throw new WatchValidationError(
      'invalid_arguments',
      `${where} 最多 ${MAX_CONDITIONS} 条`,
      where,
    );
  }
  return value.map((entry, index) => validateCondition(entry, group, `${where}[${index}]`));
}

function boundedText(
  value: unknown,
  where: string,
  max: number,
  required: boolean,
): string {
  if (value === undefined || value === null) {
    if (required) throw new WatchValidationError('invalid_arguments', `${where} 不能为空`, where);
    return '';
  }
  if (typeof value !== 'string') {
    throw new WatchValidationError('invalid_arguments', `${where} 必须是字符串`, where);
  }
  const text = value.trim();
  if (required && text === '') {
    throw new WatchValidationError('invalid_arguments', `${where} 不能为空`, where);
  }
  if ([...text].length > max) {
    throw new WatchValidationError('invalid_arguments', `${where} 最多 ${max} 个字符`, where);
  }
  return text;
}

function expiresDays(value: unknown): number {
  if (value === undefined) return DEFAULT_EXPIRES_DAYS;
  if (
    typeof value !== 'number' ||
    !Number.isInteger(value) ||
    value < MIN_EXPIRES_DAYS ||
    value > MAX_EXPIRES_DAYS
  ) {
    throw new WatchValidationError(
      'invalid_arguments',
      `expires_in_days 必须是 ${MIN_EXPIRES_DAYS}-${MAX_EXPIRES_DAYS} 的整数`,
      'expires_in_days',
    );
  }
  return value;
}

export function validateWatchInput(input: WatchCreateInput): NormalizedWatchInput {
  const code = normalizeWatchCode(input.code);
  const label = boundedText(input.label, 'label', MAX_LABEL_CHARS, true);
  const note = boundedText(input.note, 'note', MAX_NOTE_CHARS, false);
  const match: WatchMatch =
    input.match === undefined || input.match === 'any'
      ? 'any'
      : input.match === 'all'
        ? 'all'
        : (() => {
            throw new WatchValidationError('invalid_arguments', 'match 只接受 any/all', 'match');
          })();
  if (input.repeat !== undefined && typeof input.repeat !== 'boolean') {
    throw new WatchValidationError('invalid_arguments', 'repeat 必须是布尔值', 'repeat');
  }
  return {
    code,
    label,
    note,
    match,
    repeat: input.repeat === true,
    expiresInDays: expiresDays(input.expiresInDays),
    when: conditionList(input.when, 'stock', 'when', 1),
    giveUp: conditionList(input.giveUp, 'stock', 'give_up', 0),
    market: conditionList(input.market, 'market', 'market', 0),
  };
}

export interface WatchPlan {
  id: string;
  code: string;
  market: JsonRecord[];
  sector: JsonRecord[];
  stock: JsonRecord[];
  policy: WatchMatch;
  giveup: JsonRecord[];
  stop_price: number | null;
  held: boolean;
  expires_at: string;
  label: string;
}

export function buildPlan(
  planId: string,
  input: NormalizedWatchInput,
  expiresAt: string,
): WatchPlan {
  return {
    id: planId,
    code: input.code,
    market: input.market,
    sector: [],
    stock: input.when,
    policy: input.match,
    giveup: input.giveUp,
    stop_price: null,
    held: false,
    expires_at: expiresAt,
    label: input.label,
  };
}

export function planIdFor(id: string): string {
  return `chives-${id}`;
}

export function watchIdFromPlan(planId: string): string | null {
  return /^chives-(.+)$/.exec(planId)?.[1] ?? null;
}

function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

export function describeCondition(condition: JsonRecord): string {
  const type = condition['type'];
  if (type === 'price_cross') {
    return `${condition['direction'] === 'up' ? '站上' : '跌破'} ${String(condition['level'])}`;
  }
  if (type === 'price_in_range') {
    return `进入 ${String(condition['lo'])}–${String(condition['hi'])}`;
  }
  if (type === 'pct_change') {
    return `${condition['direction'] === 'up' ? '涨幅达到' : '跌幅达到'} ${String(condition['threshold_pct'])}%`;
  }
  if (type === 'open_pct') {
    return `开盘涨跌幅 ${String(condition['op'])} ${String(condition['value'])}%`;
  }
  if (type === 'volume_ratio') {
    return `量比 ${String(condition['op'])} ${String(condition['value'])}`;
  }
  if (type === 'index_pct') {
    return `指数 ${String(condition['code'])} 涨跌幅 ${String(condition['op'])} ${String(condition['value'])}%`;
  }
  if (type === 'regime') {
    const values = Array.isArray(condition['values']) ? condition['values'].join('/') : '';
    return `大盘处于 ${values}`;
  }
  return String(type);
}

function joinConditions(conditions: readonly JsonRecord[], policy: WatchMatch): string {
  return conditions.map(describeCondition).join(policy === 'all' ? ' 且 ' : ' 或 ');
}

/** One human line such as 「柳工 000528.SZ：跌破 7.71 或站上 8.69 时唤醒投资专家，至 11-27」. */
export function describeWatch(input: {
  name?: string;
  code: string;
  plan: JsonRecord;
}): string {
  const plan = input.plan;
  const stock = Array.isArray(plan['stock']) ? (plan['stock'] as JsonRecord[]) : [];
  const market = Array.isArray(plan['market']) ? (plan['market'] as JsonRecord[]) : [];
  const policy = plan['policy'] === 'all' ? 'all' : 'any';
  const parts: string[] = [];
  if (market.length > 0) parts.push(joinConditions(market, 'all'));
  if (stock.length > 0) parts.push(joinConditions(stock, policy));
  const expiry = typeof plan['expires_at'] === 'string' ? shanghaiMonthDay(plan['expires_at']) : '';
  const display =
    input.name !== undefined && input.name !== '' && input.name !== input.code
      ? `${input.name} ${input.code}`
      : input.code;
  const body = parts.length === 0 ? '条件待定' : parts.join(' 且 ');
  return `${display}：${body} 时唤醒投资专家${expiry === '' ? '' : `，至 ${expiry}`}`;
}

export function describeGiveUp(plan: JsonRecord): string {
  const giveup = Array.isArray(plan['giveup']) ? (plan['giveup'] as JsonRecord[]) : [];
  if (giveup.length === 0) return '';
  return `放弃条件：${joinConditions(giveup, 'any')}`;
}

export function planToRecord(plan: WatchPlan): JsonRecord {
  return { ...plan } as JsonRecord;
}

export function watchPrice(raw: JsonRecord): number | null {
  return (
    number(raw['price']) ??
    number(raw['last_price']) ??
    number((isRecord(raw['detail']) ? raw['detail'] : undefined)?.['price']) ??
    number((isRecord(raw['object']) ? raw['object'] : undefined)?.['price'])
  );
}

/** `MM-DD` of an ISO instant in Beijing time (expiry is stored in UTC). */
export function shanghaiMonthDay(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : shanghaiDayKey(date).slice(5);
}
