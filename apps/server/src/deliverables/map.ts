/** Deterministic MAP.md generation: the bot-readable map of its workspace. */

import {
  closeSync,
  openSync,
  readSync,
  readdirSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import { join } from 'node:path';

import { extensionOf } from './kinds.js';
import {
  WORKSPACE_DIRECTORIES,
  WORKSPACE_MAP_FILE,
  type WorkspaceDirectory,
} from './layout.js';

/** Above this many files every section is capped and says how many were omitted. */
export const MAP_TRUNCATION_THRESHOLD = 500;
const REPORT_SECTION_LIMIT = 100;
const TOPIC_SECTION_LIMIT = 50;
const SCRIPTS_SECTION_LIMIT = 10;
const UPLOADS_SECTION_LIMIT = 20;
const UNARCHIVED_SECTION_LIMIT = 50;
const TITLE_READ_BYTES = 8 * 1024;
const TITLE_MAX_LENGTH = 200;
const IGNORED_DIRECTORY_NAMES = new Set(['node_modules', '__pycache__']);
const REPORT_EXTENSIONS = new Set(['md', 'markdown', 'mdx', 'html', 'htm', 'pdf', 'docx', 'xlsx', 'pptx']);

const DIRECTORY_PURPOSES: Record<WorkspaceDirectory, string> = {
  reports: '正式产物：报告 .md/.html/.pdf，按标的或主题分子目录',
  charts: '报告引用的图片，按标的或主题分子目录',
  data: '可复用的数据文件（csv/json/parquet），按标的或主题分子目录',
  scripts: '可重跑的脚本',
  scratch: '临时文件；7 天前的文件会被自动清理',
  uploads: '用户上传的文件，按日期分子目录；只读参考，不是交付物',
};

const UNTHEMED = '（未分主题）';

interface WorkspaceFile {
  path: string;
  size: number;
  mtimeMs: number;
}

function compareText(left: string, right: string): number {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

function walk(root: string, directory: string, prefix: string, files: WorkspaceFile[]): void {
  let entries;
  try {
    entries = readdirSync(directory, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (entry.name.startsWith('.')) continue;
    if (IGNORED_DIRECTORY_NAMES.has(entry.name)) continue;
    const relative = prefix === '' ? entry.name : `${prefix}/${entry.name}`;
    if (entry.isSymbolicLink()) continue;
    if (entry.isDirectory()) {
      walk(root, join(directory, entry.name), relative, files);
      continue;
    }
    if (!entry.isFile()) continue;
    try {
      const stat = statSync(join(directory, entry.name));
      files.push({ path: relative, size: stat.size, mtimeMs: stat.mtimeMs });
    } catch {
      // A file that vanished mid-walk is simply absent from the map.
    }
  }
}

function listWorkspaceFiles(workspace: string): WorkspaceFile[] {
  const files: WorkspaceFile[] = [];
  walk(workspace, workspace, '', files);
  return files;
}

function newestFirst(left: WorkspaceFile, right: WorkspaceFile): number {
  return right.mtimeMs - left.mtimeMs || compareText(left.path, right.path);
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(mtimeMs: number): string {
  return new Date(mtimeMs).toISOString().slice(0, 10);
}

function formatTimestamp(now: Date): string {
  return `${now.toISOString().replace('T', ' ').slice(0, 19)} UTC`;
}

function linkTarget(path: string): string {
  return /\s/.test(path) ? `<${path}>` : path;
}

function readHeading(path: string): string | null {
  const extension = extensionOf(path);
  if (extension !== 'md' && extension !== 'markdown' && extension !== 'mdx') return null;
  let descriptor: number | null = null;
  try {
    descriptor = openSync(path, 'r');
    const buffer = Buffer.alloc(TITLE_READ_BYTES);
    const length = readSync(descriptor, buffer, 0, TITLE_READ_BYTES, 0);
    const text = buffer.subarray(0, length).toString('utf8');
    for (const line of text.replace(/^\uFEFF/, '').split(/\r?\n/)) {
      if (!line.startsWith('# ')) continue;
      const title = line.slice(2).trim();
      if (title !== '') return title.slice(0, TITLE_MAX_LENGTH);
    }
    return null;
  } catch {
    return null;
  } finally {
    if (descriptor !== null) {
      try {
        closeSync(descriptor);
      } catch {
        // Ignore close failures; the map falls back to a file name.
      }
    }
  }
}

function reportTitle(file: WorkspaceFile, workspace: string): string {
  return readHeading(join(workspace, file.path)) ?? file.path.split('/').at(-1) ?? file.path;
}

function topicOf(path: string, directory: string): string {
  const rest = path.slice(directory.length + 1);
  const separator = rest.indexOf('/');
  return separator < 0 ? UNTHEMED : rest.slice(0, separator);
}

function groupByTopic(
  files: readonly WorkspaceFile[],
  directory: string,
): Map<string, WorkspaceFile[]> {
  const groups = new Map<string, WorkspaceFile[]>();
  for (const file of files) {
    const topic = topicOf(file.path, directory);
    const group = groups.get(topic);
    if (group === undefined) groups.set(topic, [file]);
    else group.push(file);
  }
  for (const group of groups.values()) group.sort(newestFirst);
  return groups;
}

function sortedTopics(groups: ReadonlyMap<string, readonly WorkspaceFile[]>): string[] {
  return [...groups.keys()].sort((left, right) => {
    if (left === UNTHEMED) return 1;
    if (right === UNTHEMED) return -1;
    return compareText(left, right);
  });
}

function fileLine(file: WorkspaceFile, label?: string): string {
  const title = label ?? (file.path.split('/').at(-1) ?? file.path);
  return `- [${title}](${linkTarget(file.path)}) · ${formatDate(file.mtimeMs)}`;
}

function renderReports(workspace: string, files: readonly WorkspaceFile[], truncated: boolean): string[] {
  const lines: string[] = ['## reports/'];
  if (files.length === 0) {
    lines.push('', '（暂无报告）');
    return lines;
  }
  const groups = groupByTopic(files, 'reports');
  const limit = truncated ? REPORT_SECTION_LIMIT : Number.POSITIVE_INFINITY;
  let rendered = 0;
  let omitted = 0;
  for (const topic of sortedTopics(groups)) {
    const reports = groups.get(topic) ?? [];
    const shown: string[] = [];
    for (const report of reports) {
      if (rendered >= limit) {
        omitted += 1;
        continue;
      }
      rendered += 1;
      shown.push(fileLine(report, reportTitle(report, workspace)));
    }
    if (shown.length === 0) continue;
    lines.push('', `### ${topic}`, '', ...shown);
  }
  if (omitted > 0) lines.push('', `另有 ${omitted} 个报告未列出`);
  return lines;
}

function renderTopicSection(
  workspace: string,
  directory: WorkspaceDirectory,
  files: readonly WorkspaceFile[],
  truncated: boolean,
): string[] {
  const lines: string[] = [`## ${directory}/`];
  if (files.length === 0) {
    lines.push('', '（暂无文件）');
    return lines;
  }
  const groups = groupByTopic(files, directory);
  const topics = sortedTopics(groups);
  const limit = truncated ? TOPIC_SECTION_LIMIT : Number.POSITIVE_INFINITY;
  let omittedTopics = 0;
  for (const [index, topic] of topics.entries()) {
    if (index >= limit) {
      omittedTopics += 1;
      continue;
    }
    const group = groups.get(topic) ?? [];
    lines.push('', `### ${topic}（${group.length} 个文件）`, '');
    lines.push(...group.slice(0, 5).map((file) => fileLine(file)));
  }
  if (omittedTopics > 0) lines.push('', `另有 ${omittedTopics} 个主题未列出`);
  return lines;
}

function renderScripts(files: readonly WorkspaceFile[]): string[] {
  const lines: string[] = ['## scripts/'];
  if (files.length === 0) {
    lines.push('', '（暂无脚本）');
    return lines;
  }
  const sorted = [...files].sort(newestFirst);
  lines.push('', ...sorted.slice(0, SCRIPTS_SECTION_LIMIT).map((file) => fileLine(file)));
  const omitted = sorted.length - SCRIPTS_SECTION_LIMIT;
  if (omitted > 0) lines.push('', `另有 ${omitted} 个脚本未列出`);
  return lines;
}

function renderScratch(files: readonly WorkspaceFile[]): string[] {
  const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
  return ['## scratch/', '', `共 ${files.length} 个文件，${formatBytes(totalBytes)}`];
}

function renderUploads(files: readonly WorkspaceFile[]): string[] {
  const lines: string[] = ['## 用户上传/'];
  if (files.length === 0) {
    lines.push('', '（暂无上传文件）');
    return lines;
  }
  const sorted = [...files].sort(newestFirst);
  lines.push('', ...sorted.slice(0, UPLOADS_SECTION_LIMIT).map((file) => fileLine(file)));
  const omitted = sorted.length - UPLOADS_SECTION_LIMIT;
  if (omitted > 0) lines.push('', `另有 ${omitted} 个上传文件未列出`);
  return lines;
}

function rootUnarchivedEntries(workspace: string): Array<{ name: string; directory: boolean }> {
  const conventional = new Set<string>(WORKSPACE_DIRECTORIES);
  const entries: Array<{ name: string; directory: boolean }> = [];
  let children;
  try {
    children = readdirSync(workspace, { withFileTypes: true });
  } catch {
    return entries;
  }
  for (const entry of children) {
    if (entry.name.startsWith('.')) continue;
    if (entry.name === WORKSPACE_MAP_FILE) continue;
    if (entry.isSymbolicLink()) continue;
    if (entry.isDirectory()) {
      if (!conventional.has(entry.name)) entries.push({ name: entry.name, directory: true });
      continue;
    }
    if (entry.isFile()) entries.push({ name: entry.name, directory: false });
  }
  entries.sort((left, right) => compareText(left.name, right.name));
  return entries;
}

function renderUnarchived(workspace: string, truncated: boolean): string[] {
  const entries = rootUnarchivedEntries(workspace);
  const lines: string[] = ['## 未归档', ''];
  if (entries.length === 0) {
    lines.push('根目录下没有不符合约定的文件或目录。');
    return lines;
  }
  lines.push('根目录下不符合约定的文件与目录：');
  lines.push('');
  const limit = truncated ? UNARCHIVED_SECTION_LIMIT : Number.POSITIVE_INFINITY;
  for (const [index, entry] of entries.entries()) {
    if (index >= limit) break;
    lines.push(entry.directory ? `- \`${entry.name}/\`（目录）` : `- \`${entry.name}\``);
  }
  const omitted = Math.max(entries.length - limit, 0);
  if (omitted > 0) lines.push('', `另有 ${omitted} 个条目未列出`);
  return lines;
}

/** Renders MAP.md content without touching the filesystem. */
export function generateWorkspaceMap(
  workspace: string,
  options: { now?: Date } = {},
): string {
  const now = options.now ?? new Date();
  const all = listWorkspaceFiles(workspace);
  const truncated = all.length > MAP_TRUNCATION_THRESHOLD;
  const inDirectory = (directory: WorkspaceDirectory): WorkspaceFile[] =>
    all.filter((file) => file.path.startsWith(`${directory}/`));

  const lines: string[] = [
    '# 工作目录地图',
    '',
    '这是这个 bot 的工作目录地图，由 Chives 在每轮任务结束后自动生成，请勿手工修改；开始任务前先读它，复用已有的报告和数据。',
    `生成时间：${formatTimestamp(now)}`,
    '',
    '## 目录约定',
    '',
    ...WORKSPACE_DIRECTORIES.map((directory) => `- \`${directory}/\` ${DIRECTORY_PURPOSES[directory]}`),
    `- \`${WORKSPACE_MAP_FILE}\` 本目录地图，由服务端生成，只读`,
  ];

  const reports = inDirectory('reports').filter((file) => REPORT_EXTENSIONS.has(extensionOf(file.path)));
  lines.push('', ...renderReports(workspace, reports, truncated));
  lines.push('', ...renderTopicSection(workspace, 'charts', inDirectory('charts'), truncated));
  lines.push('', ...renderTopicSection(workspace, 'data', inDirectory('data'), truncated));
  lines.push('', ...renderUploads(inDirectory('uploads')));
  lines.push('', ...renderScripts(inDirectory('scripts')));
  lines.push('', ...renderScratch(inDirectory('scratch')));
  lines.push('', ...renderUnarchived(workspace, truncated));
  return `${lines.join('\n')}\n`;
}

/**
 * Atomically replaces MAP.md (temp file + rename). A failure is logged and
 * reported, never thrown into the turn that triggered it.
 */
export function writeWorkspaceMap(
  workspace: string,
  options: { now?: Date } = {},
): boolean {
  const target = join(workspace, WORKSPACE_MAP_FILE);
  const temporary = join(workspace, `.${WORKSPACE_MAP_FILE}.${process.pid}.${Date.now()}.tmp`);
  try {
    const content = generateWorkspaceMap(workspace, options);
    writeFileSync(temporary, content, 'utf8');
    renameSync(temporary, target);
    return true;
  } catch (error) {
    try {
      unlinkSync(temporary);
    } catch {
      // Nothing to clean up when the temp file was never created.
    }
    console.error('chives workspace map update failed', error);
    return false;
  }
}
