import type { DeliverableDto, DeliverableKind, MessageDto } from '@chives/server/protocol';

export const KIND_LABELS: Record<DeliverableKind, string> = {
  markdown: '报告',
  image: '图片',
  csv: '表格',
  json: '数据',
  html: '网页',
  pdf: 'PDF',
  code: '代码',
  other: '文件'
};

function isDeliverable(value: unknown): value is DeliverableDto {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const entry = value as Record<string, unknown>;
  return (
    typeof entry['id'] === 'string' &&
    typeof entry['taskId'] === 'string' &&
    typeof entry['botId'] === 'string' &&
    typeof entry['path'] === 'string' &&
    typeof entry['kind'] === 'string' &&
    typeof entry['size'] === 'number' &&
    typeof entry['createdAt'] === 'string'
  );
}

/** Deliverables embedded in a `kind=deliverable` message's meta. */
const HIDDEN_EXTENSIONS = new Set(['py', 'js', 'ts', 'sh', 'json', 'jsonl', 'csv', 'parquet', 'txt', 'log']);
const HIDDEN_DIRECTORIES = new Set(['scripts', 'scratch', 'data']);

/**
 * Mirrors the server's `isDeliverablePath` for records written before it existed:
 * code, data and scratch files are working files, not something to hand the user.
 */
export function isShownDeliverablePath(path: string): boolean {
  const segments = path.replaceAll('\\', '/').split('/').filter((part) => part !== '' && part !== '.');
  const name = segments.at(-1) ?? '';
  if (segments.length === 1 && name === 'MAP.md') return false;
  if (segments.length > 1 && HIDDEN_DIRECTORIES.has(segments[0] ?? '')) return false;
  const dot = name.lastIndexOf('.');
  const extension = dot < 0 ? '' : name.slice(dot + 1).toLowerCase();
  return !HIDDEN_EXTENSIONS.has(extension);
}

export function deliverablesFromMessage(message: MessageDto): DeliverableDto[] {
  const raw = message.meta?.['deliverables'];
  if (!Array.isArray(raw)) return [];
  return raw.filter(isDeliverable).filter((entry) => isShownDeliverablePath(entry.path));
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function fileName(path: string): string {
  return path.split('/').at(-1) ?? path;
}

/** Drops query/hash, decodes percent-encoding, and normalizes separators. */
export function normalizeDeliverablePath(value: string): string {
  const withoutQuery = value.split('#')[0]?.split('?')[0] ?? '';
  let decoded = withoutQuery;
  try {
    decoded = decodeURIComponent(withoutQuery);
  } catch {
    // Keep the raw text when it is not valid percent-encoding.
  }
  return decoded.replaceAll('\\', '/').replace(/^\.\//, '');
}

/** Directory part of a workspace-relative POSIX path; '' for the root. */
export function workspaceDirectoryOf(path: string): string {
  const normalized = normalizeDeliverablePath(path);
  const index = normalized.lastIndexOf('/');
  return index < 0 ? '' : normalized.slice(0, index);
}

function normalizeRelativeSegments(segments: readonly string[]): string | null {
  const result: string[] = [];
  for (const segment of segments) {
    if (segment === '' || segment === '.') continue;
    if (segment === '..') {
      if (result.length === 0) return null;
      result.pop();
      continue;
    }
    result.push(segment);
  }
  return result.length === 0 ? null : result.join('/');
}

/**
 * Workspace paths a relative Markdown image may resolve to: first relative to
 * the Markdown file's own directory, then relative to the workspace root.
 */
export function resolveMarkdownImagePaths(
  baseDir: string | undefined,
  src: string
): string[] {
  const source = normalizeDeliverablePath(src);
  if (source === '') return [];
  const candidates: string[] = [];
  const base = baseDir === undefined || baseDir === '' ? null : normalizeRelativeSegments(baseDir.split('/'));
  if (base !== null) {
    const joined = normalizeRelativeSegments([...base.split('/'), ...source.split('/')]);
    if (joined !== null) candidates.push(joined);
  }
  const rooted = normalizeRelativeSegments(source.split('/'));
  if (rooted !== null) candidates.push(rooted);
  return [...new Set(candidates)];
}

/** Relative image sources embedded in Markdown; absolute and remote URLs are ignored. */
export function embeddedImagePaths(markdown: string): string[] {
  const paths: string[] = [];
  const pattern = /!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+["'][^"']*["'])?\s*\)/g;
  for (const match of markdown.matchAll(pattern)) {
    const source = match[1] ?? '';
    if (source === '' || source.startsWith('#') || source.startsWith('/')) continue;
    if (/^[a-z][a-z0-9+.-]*:/i.test(source)) continue;
    const normalized = normalizeDeliverablePath(source);
    if (normalized !== '') paths.push(normalized);
  }
  return paths;
}
