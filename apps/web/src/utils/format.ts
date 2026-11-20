const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'] as const;

function pad(value: number): string {
  return value.toString().padStart(2, '0');
}

export function toDayKey(iso: string): string {
  const date = new Date(iso);
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

export function formatDateLabel(iso: string, now: Date = new Date()): string {
  const value = new Date(iso);
  const today = startOfDay(now);
  const target = startOfDay(value);
  const diffDays = Math.round((today.getTime() - target.getTime()) / 86_400_000);
  if (diffDays === 0) return '今天';
  if (diffDays === 1) return '昨天';
  return `${value.getMonth() + 1} 月 ${value.getDate()} 日 ${WEEKDAYS[value.getDay()]}`;
}

export function formatTime(iso: string): string {
  const value = new Date(iso);
  const zone=typeof document==='undefined'?undefined:document.documentElement.dataset.timezone;
  if(zone&&Number.isFinite(value.getTime()))return new Intl.DateTimeFormat(document.documentElement.lang||'zh-CN',{timeZone:zone,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(value);
  return `${pad(value.getHours())}:${pad(value.getMinutes())}`;
}

export function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours} 小时 ${minutes} 分 ${seconds} 秒`;
  if (minutes > 0) return `${minutes} 分 ${seconds} 秒`;
  return `${seconds} 秒`;
}

export function formatDurationBetween(startedAt: string, endedAt: string | null, now: number): string {
  const started = new Date(startedAt).getTime();
  const ended = endedAt === null ? now : new Date(endedAt).getTime();
  if (!Number.isFinite(started) || !Number.isFinite(ended)) return '0 秒';
  return formatDuration(ended - started);
}

export function truncateOutput(text: string, limit = 2000): { text: string; truncated: boolean } {
  if (text.length <= limit) return { text, truncated: false };
  return { text: text.slice(0, limit), truncated: true };
}

export function formatJson(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** `YYYY-MM-DD` of an ISO instant in Beijing time (server timestamps are UTC). */
export function formatShanghaiDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(date);
}
