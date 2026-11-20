/** Fixed-offset Asia/Shanghai helpers (the product does not need DST). */

const SHANGHAI_OFFSET_MS = 8 * 60 * 60_000;

export function shanghaiParts(date: Date): {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
} {
  const local = new Date(date.getTime() + SHANGHAI_OFFSET_MS);
  return {
    year: local.getUTCFullYear(),
    month: local.getUTCMonth() + 1,
    day: local.getUTCDate(),
    hour: local.getUTCHours(),
    minute: local.getUTCMinutes(),
  };
}

export function shanghaiDayKey(date: Date): string {
  const parts = shanghaiParts(date);
  return `${parts.year}-${String(parts.month).padStart(2, '0')}-${String(parts.day).padStart(2, '0')}`;
}

/** UTC instant of 00:00 Asia/Shanghai on the calendar day containing `date`. */
export function shanghaiDayStart(date: Date): Date {
  const parts = shanghaiParts(date);
  return new Date(Date.UTC(parts.year, parts.month - 1, parts.day) - SHANGHAI_OFFSET_MS);
}

export function formatShanghaiTime(date: Date): string {
  const parts = shanghaiParts(date);
  return `${String(parts.hour).padStart(2, '0')}:${String(parts.minute).padStart(2, '0')}`;
}
