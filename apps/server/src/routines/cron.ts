/** Dependency-free 5-field cron parsing, next-run maths and human descriptions. */

import { RoutineValidationError } from './types.js';

export type CronField = 'minute' | 'hour' | 'day' | 'month' | 'weekday';

const RANGES: Record<CronField, [number, number]> = {
  minute: [0, 59],
  hour: [0, 23],
  day: [1, 31],
  month: [1, 12],
  weekday: [0, 7],
};

export interface ParsedCron {
  expression: string;
  minute: Set<number>;
  hour: Set<number>;
  day: Set<number>;
  month: Set<number>;
  weekday: Set<number>;
  /** True when the field was written as `*` (the dom/dow OR rule needs this). */
  dayAny: boolean;
  weekdayAny: boolean;
}

function fail(expression: string, message: string): never {
  throw new RoutineValidationError(`invalid cron "${expression}": ${message}`);
}

function expandPart(part: string, field: CronField, expression: string): number[] {
  const [minimum, maximum] = RANGES[field];
  const bad = (): never => fail(expression, `bad ${field} field "${part}"`);
  let base = part;
  let step = 1;
  const slash = part.indexOf('/');
  if (slash >= 0) {
    base = part.slice(0, slash);
    const stepRaw = part.slice(slash + 1);
    if (!/^\d+$/.test(stepRaw)) bad();
    step = Number(stepRaw);
    if (step <= 0) bad();
  }
  let low: number;
  let high: number;
  if (base === '*') {
    low = minimum;
    high = maximum;
  } else if (base.includes('-')) {
    const pieces = base.split('-');
    if (pieces.length !== 2 || !/^\d+$/.test(pieces[0] ?? '') || !/^\d+$/.test(pieces[1] ?? '')) bad();
    low = Number(pieces[0]);
    high = Number(pieces[1]);
  } else {
    if (!/^\d+$/.test(base)) bad();
    low = Number(base);
    high = low;
  }
  if (low < minimum || high > maximum || low > high) bad();
  const values: number[] = [];
  for (let value = low; value <= high; value += step) values.push(value);
  return values;
}

export function validateCron(expression: string): ParsedCron {
  const fields = expression.trim().split(/\s+/);
  if (fields.length !== 5) fail(expression, 'expected 5 space-separated fields');
  const [minuteRaw, hourRaw, dayRaw, monthRaw, weekdayRaw] = fields as [string, string, string, string, string];
  const sets: Record<CronField, Set<number>> = {
    minute: new Set(),
    hour: new Set(),
    day: new Set(),
    month: new Set(),
    weekday: new Set(),
  };
  for (const [field, raw] of [
    ['minute', minuteRaw],
    ['hour', hourRaw],
    ['day', dayRaw],
    ['month', monthRaw],
    ['weekday', weekdayRaw],
  ] as Array<[CronField, string]>) {
    if (raw === '') fail(expression, `empty ${field} field`);
    for (const part of raw.split(',')) {
      if (part === '') fail(expression, `empty ${field} item`);
      for (const value of expandPart(part, field, expression)) sets[field].add(value);
    }
  }
  if (sets.weekday.has(7)) sets.weekday.add(0);
  sets.weekday.delete(7);
  return {
    expression: expression.trim(),
    minute: sets.minute,
    hour: sets.hour,
    day: sets.day,
    month: sets.month,
    weekday: sets.weekday,
    dayAny: dayRaw === '*',
    weekdayAny: weekdayRaw === '*',
  };
}

function offsetMinutes(tz: 'Asia/Shanghai' | 'UTC'): number {
  return tz === 'UTC' ? 0 : 8 * 60;
}

/** Local wall-clock parts for an instant, as if the zone were UTC. */
function localParts(instant: Date, tz: 'Asia/Shanghai' | 'UTC'): Date {
  return new Date(instant.getTime() + offsetMinutes(tz) * 60_000);
}

function fromLocal(local: Date, tz: 'Asia/Shanghai' | 'UTC'): Date {
  return new Date(local.getTime() - offsetMinutes(tz) * 60_000);
}

function cronMatches(parsed: ParsedCron, local: Date): boolean {
  if (!parsed.minute.has(local.getUTCMinutes())) return false;
  if (!parsed.hour.has(local.getUTCHours())) return false;
  if (!parsed.month.has(local.getUTCMonth() + 1)) return false;
  const dayMatch = parsed.day.has(local.getUTCDate());
  const weekdayMatch = parsed.weekday.has(local.getUTCDay());
  if (parsed.dayAny && parsed.weekdayAny) return true;
  if (parsed.dayAny) return weekdayMatch;
  if (parsed.weekdayAny) return dayMatch;
  return dayMatch || weekdayMatch;
}

export function nextCronRun(parsed: ParsedCron, tz: 'Asia/Shanghai' | 'UTC', after: Date): Date {
  // Start at the next whole minute strictly after `after`.
  const start = new Date(after.getTime() + 60_000);
  start.setUTCSeconds(0, 0);
  const local = localParts(start, tz);
  const limit = 366 * 2 * 24 * 60;
  for (let step = 0; step < limit; step += 1) {
    if (cronMatches(parsed, local)) return fromLocal(local, tz);
    local.setUTCMinutes(local.getUTCMinutes() + 1);
  }
  throw new RoutineValidationError(`cron "${parsed.expression}" never fires within two years`);
}

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

function sameSet(value: Set<number>, expected: readonly number[]): boolean {
  return value.size === expected.length && expected.every((entry) => value.has(entry));
}

function padded(value: number): string {
  return String(value).padStart(2, '0');
}

function weekdayText(days: Set<number>): string {
  if (sameSet(days, [1, 2, 3, 4, 5])) return '工作日';
  if (sameSet(days, [0, 6])) return '周末';
  if (sameSet(days, [0, 1, 2, 3, 4, 5, 6])) return '每天';
  return `每周${[...days].sort().map((day) => WEEKDAY_LABELS[day]).join('、')}`;
}

export function describeCron(parsed: ParsedCron, tz: 'Asia/Shanghai' | 'UTC'): string {
  const zone = tz === 'Asia/Shanghai' ? '北京时间' : 'UTC';
  if (parsed.minute.size === 1 && parsed.hour.size === 1 && parsed.month.size === 12) {
    const minute = [...parsed.minute][0] ?? 0;
    const hour = [...parsed.hour][0] ?? 0;
    const time = `${padded(hour)}:${padded(minute)}`;
    if (parsed.dayAny && parsed.weekdayAny) return `每天 ${time}（${zone}）`;
    if (parsed.dayAny) return `${weekdayText(parsed.weekday)} ${time}（${zone}）`;
    if (parsed.weekdayAny) return `每月 ${[...parsed.day].sort((a, b) => a - b).join('、')} 日 ${time}（${zone}）`;
    return `${weekdayText(parsed.weekday)}或每月 ${[...parsed.day].sort((a, b) => a - b).join('、')} 日 ${time}（${zone}）`;
  }
  return `cron ${parsed.expression}（${zone}）`;
}
