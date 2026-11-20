/** Routine schedule parsing and validation shared by the manifest, HTTP API and scheduler. */

import type { RoutineSchedule } from '../store/types.js';
import { validateCron } from './cron.js';

export const ROUTINE_TZ = ['Asia/Shanghai', 'UTC'] as const;
export type RoutineTz = (typeof ROUTINE_TZ)[number];
export const MIN_EVERY_MINUTES = 5;
export const MAX_PROMPT_CHARS = 4000;
export const MAX_TITLE_CHARS = 60;

export class RoutineValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RoutineValidationError';
  }
}

function fail(message: string): never {
  throw new RoutineValidationError(message);
}

export function parseSchedule(raw: unknown): RoutineSchedule {
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) {
    fail('schedule must be an object');
  }
  const body = raw as Record<string, unknown>;
  const keys = Object.keys(body);
  const hasCron = 'cron' in body || 'tz' in body;
  const hasEvery = 'every_minutes' in body;
  const hasOnce = 'once_at' in body;
  const count = [hasCron, hasEvery, hasOnce].filter(Boolean).length;
  if (count !== 1) fail('schedule must contain exactly one of cron, every_minutes, once_at');

  if (hasEvery) {
    if (keys.length !== 1) fail('every_minutes schedule takes no other fields');
    const value = body['every_minutes'];
    if (typeof value !== 'number' || !Number.isInteger(value) || value < MIN_EVERY_MINUTES) {
      fail(`every_minutes must be an integer >= ${MIN_EVERY_MINUTES}`);
    }
    return { kind: 'every', minutes: value };
  }
  if (hasOnce) {
    if (keys.length !== 1) fail('once_at schedule takes no other fields');
    const value = body['once_at'];
    if (typeof value !== 'string' || !Number.isFinite(Date.parse(value))) {
      fail('once_at must be an ISO8601 timestamp');
    }
    return { kind: 'once', at: new Date(value).toISOString() };
  }

  if (keys.some((key) => key !== 'cron' && key !== 'tz')) {
    fail('cron schedule only accepts cron and tz');
  }
  const expression = body['cron'];
  if (typeof expression !== 'string' || expression.trim() === '') {
    fail('cron must be a non-empty string');
  }
  const tzRaw = body['tz'] ?? 'Asia/Shanghai';
  if (typeof tzRaw !== 'string' || !(ROUTINE_TZ as readonly string[]).includes(tzRaw)) {
    fail(`tz must be one of: ${ROUTINE_TZ.join(', ')}`);
  }
  validateCron(expression.trim());
  return { kind: 'cron', expression: expression.trim(), tz: tzRaw as RoutineTz };
}

export function scheduleToWire(schedule: RoutineSchedule): Record<string, unknown> {
  if (schedule.kind === 'every') return { every_minutes: schedule.minutes };
  if (schedule.kind === 'once') return { once_at: schedule.at };
  return { cron: schedule.expression, tz: schedule.tz };
}

export { validateCron } from './cron.js';
