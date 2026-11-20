/** Renders the "## 你记得的" section: ordering, expiry marks, and the 3000-char cap. */

import { dateOnly, isExpired } from './policy.js';
import type { MemoryKind, MemoryRecord } from './types.js';

export const MAX_MEMORY_INJECTION_CHARS = 3000;
const EXPIRED_NOTE = '（已过期，仅供参考）';

const KIND_LABELS: Readonly<Record<MemoryKind, string>> = {
  preference: '偏好',
  view: '观点',
  fact: '事实',
  note: '笔记',
};

export function memoryKindLabel(kind: MemoryKind): string {
  return KIND_LABELS[kind];
}

function expiryLabel(record: MemoryRecord): string {
  return record.expiresAt === null ? '无到期' : `到期 ${dateOnly(record.expiresAt)}`;
}

export function formatMemoryLine(record: MemoryRecord, now: Date): string {
  const prefix = `[${record.kind} · 写于 ${dateOnly(record.writtenAt)}（${expiryLabel(record)}）]`;
  const body = `${record.title}：${record.body}`;
  return isExpired(record.expiresAt, now) ? `${prefix} ${body}${EXPIRED_NOTE}` : `${prefix} ${body}`;
}

function byWrittenAtDesc(left: MemoryRecord, right: MemoryRecord): number {
  return right.writtenAt.localeCompare(left.writtenAt) || right.slug.localeCompare(left.slug);
}

/**
 * Preferences are always first, other unexpired entries follow newest-first,
 * and expired views/facts are last. When over budget the expired lines go
 * first, then the oldest non-preference lines, then the oldest preferences.
 */
export function buildMemoryInjection(
  records: readonly MemoryRecord[],
  now: Date,
  maxChars = MAX_MEMORY_INJECTION_CHARS,
): string {
  if (records.length === 0 || maxChars <= 0) return '';
  const activePreferences = records
    .filter((record) => record.kind === 'preference' && !isExpired(record.expiresAt, now))
    .sort(byWrittenAtDesc);
  const activeOthers = records
    .filter((record) => record.kind !== 'preference' && !isExpired(record.expiresAt, now))
    .sort(byWrittenAtDesc);
  const expired = records
    .filter((record) => isExpired(record.expiresAt, now))
    .sort(byWrittenAtDesc);

  const preferences = [...activePreferences];
  const others = [...activeOthers];
  const stale = [...expired];

  const render = (): string =>
    [
      ...preferences.map((record) => formatMemoryLine(record, now)),
      ...others.map((record) => formatMemoryLine(record, now)),
      ...stale.map((record) => formatMemoryLine(record, now)),
    ].join('\n');

  let text = render();
  while (text.length > maxChars && stale.length > 0) {
    stale.pop();
    text = render();
  }
  while (text.length > maxChars && others.length > 0) {
    others.pop();
    text = render();
  }
  while (text.length > maxChars && preferences.length > 0) {
    preferences.pop();
    text = render();
  }
  if (text.length > maxChars) {
    return `${text.slice(0, Math.max(0, maxChars - 1))}…`;
  }
  return text;
}
