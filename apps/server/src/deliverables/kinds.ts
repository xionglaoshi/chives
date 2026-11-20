/** File classification and HTTP content types for workspace deliverables. */

export type DeliverableKind =
  | 'markdown'
  | 'image'
  | 'csv'
  | 'json'
  | 'html'
  | 'pdf'
  | 'code'
  | 'other';

const KIND_BY_EXTENSION: Record<string, DeliverableKind> = {
  md: 'markdown',
  markdown: 'markdown',
  mdx: 'markdown',
  png: 'image',
  jpg: 'image',
  jpeg: 'image',
  gif: 'image',
  webp: 'image',
  svg: 'image',
  bmp: 'image',
  avif: 'image',
  csv: 'csv',
  tsv: 'csv',
  json: 'json',
  jsonl: 'json',
  html: 'html',
  htm: 'html',
  pdf: 'pdf',
  ts: 'code',
  tsx: 'code',
  js: 'code',
  jsx: 'code',
  mjs: 'code',
  cjs: 'code',
  py: 'code',
  ipynb: 'code',
  sh: 'code',
  bash: 'code',
  zsh: 'code',
  go: 'code',
  rs: 'code',
  java: 'code',
  kt: 'code',
  c: 'code',
  cc: 'code',
  cpp: 'code',
  h: 'code',
  hpp: 'code',
  rb: 'code',
  php: 'code',
  sql: 'code',
  css: 'code',
  scss: 'code',
  yml: 'code',
  yaml: 'code',
  toml: 'code',
  ini: 'code',
  xml: 'code',
  swift: 'code',
  lua: 'code',
  r: 'code',
  txt: 'code',
  log: 'code',
};

const CONTENT_TYPES: Record<DeliverableKind, string> = {
  markdown: 'text/markdown; charset=utf-8',
  image: 'application/octet-stream',
  csv: 'text/csv; charset=utf-8',
  json: 'application/json; charset=utf-8',
  html: 'text/html; charset=utf-8',
  pdf: 'application/pdf',
  code: 'text/plain; charset=utf-8',
  other: 'application/octet-stream',
};

const IMAGE_CONTENT_TYPES: Record<string, string> = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  webp: 'image/webp',
  svg: 'image/svg+xml',
  bmp: 'image/bmp',
  avif: 'image/avif',
};

/** Lower-case extension without the dot, or '' when the name has none. */
export function extensionOf(path: string): string {
  const base = path.split('/').at(-1) ?? path;
  const index = base.lastIndexOf('.');
  if (index <= 0 || index === base.length - 1) return '';
  return base.slice(index + 1).toLowerCase();
}

export function classifyKind(path: string): DeliverableKind {
  return KIND_BY_EXTENSION[extensionOf(path)] ?? 'other';
}

export function contentTypeFor(path: string, kind: DeliverableKind): string {
  if (kind === 'image') {
    return IMAGE_CONTENT_TYPES[extensionOf(path)] ?? 'application/octet-stream';
  }
  return CONTENT_TYPES[kind];
}

export function isBinaryKind(kind: DeliverableKind): boolean {
  return kind === 'image' || kind === 'pdf';
}

/** Image types the browser may render inline from the workspace content route. */
const INLINE_IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg']);

export function isInlineImage(path: string): boolean {
  return INLINE_IMAGE_EXTENSIONS.has(extensionOf(path));
}
