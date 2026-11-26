/** User file uploads: validation, workspace placement, and prompt labels. */

import { mkdirSync, statSync, writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';

import type { DeliverableKind, MessageAttachmentDto } from '../api/protocol.js';
import { AppError } from '../errors.js';
import { classifyKind, extensionOf } from './kinds.js';
import { resolveWorkspacePath } from './files.js';

export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
export const MAX_ATTACHMENTS_PER_MESSAGE = 10;
export const UPLOADS_DIRECTORY = 'uploads';

export const ALLOWED_UPLOAD_EXTENSIONS = new Set([
  'pdf',
  'md',
  'txt',
  'csv',
  'tsv',
  'json',
  'xlsx',
  'xls',
  'docx',
  'pptx',
  'png',
  'jpg',
  'jpeg',
  'webp',
  'gif',
]);

const TEXT_EXTENSIONS = new Set(['md', 'txt', 'csv', 'tsv', 'json']);
const ZIP_EXTENSIONS = new Set(['xlsx', 'docx', 'pptx']);
const PATH_SEPARATORS = /[\\/]/g;
const MAX_NAME_LENGTH = 180;

const OLE_MAGIC = Buffer.from([0xd0, 0xcf, 0x11, 0xe0, 0xa1, 0xb1, 0x1a, 0xe1]);
const ZIP_MAGIC = Buffer.from([0x50, 0x4b, 0x03, 0x04]);
const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const JPEG_MAGIC = Buffer.from([0xff, 0xd8, 0xff]);
const GIF87_MAGIC = Buffer.from('GIF87a', 'ascii');
const GIF89_MAGIC = Buffer.from('GIF89a', 'ascii');
const PDF_MAGIC = Buffer.from('%PDF-', 'ascii');

const BINARY_MAGICS = [PNG_MAGIC, JPEG_MAGIC, GIF87_MAGIC, GIF89_MAGIC, PDF_MAGIC, ZIP_MAGIC, OLE_MAGIC];

const ATTACHMENT_KIND_LABELS: Record<DeliverableKind, string> = {
  markdown: '文档',
  image: '图片',
  csv: '表格',
  json: '数据',
  html: '网页',
  pdf: 'PDF',
  code: '文本',
  other: '文件',
};

function startsWith(buffer: Buffer, magic: Buffer): boolean {
  return buffer.length >= magic.length && buffer.subarray(0, magic.length).equals(magic);
}

function isWebp(buffer: Buffer): boolean {
  return (
    buffer.length >= 12 &&
    buffer.subarray(0, 4).toString('ascii') === 'RIFF' &&
    buffer.subarray(8, 12).toString('ascii') === 'WEBP'
  );
}

function hasBinaryMagic(buffer: Buffer): boolean {
  return BINARY_MAGICS.some((magic) => startsWith(buffer, magic)) || isWebp(buffer);
}

function isText(buffer: Buffer): boolean {
  if (buffer.includes(0)) return false;
  const text = buffer.toString('utf8');
  if (text.includes('\uFFFD')) return false;
  return Buffer.from(text, 'utf8').equals(buffer);
}

function assertMagic(name: string, data: Buffer): void {
  const extension = extensionOf(name);
  const valid = (() => {
    if (TEXT_EXTENSIONS.has(extension)) {
      if (!isText(data) || hasBinaryMagic(data)) return false;
      if (extension === 'json') {
        const first = data.toString('utf8').trimStart()[0];
        return first === '{' || first === '[';
      }
      return true;
    }
    if (extension === 'silk') return startsWith(data, Buffer.from('#!SILK_V3')) || startsWith(data, Buffer.from('\x02#!SILK_V3'));
    if (extension === 'ogg') return startsWith(data, Buffer.from('OggS'));
    if (extension === 'mp3') return startsWith(data, Buffer.from('ID3')) || (data[0] === 0xff && ((data[1] ?? 0) & 0xe0) === 0xe0);
    if (extension === 'm4a') return data.subarray(4, 8).toString('ascii') === 'ftyp';
    if (extension === 'pdf') return startsWith(data, PDF_MAGIC);
    if (extension === 'png') return startsWith(data, PNG_MAGIC);
    if (extension === 'jpg' || extension === 'jpeg') return startsWith(data, JPEG_MAGIC);
    if (extension === 'gif') return startsWith(data, GIF87_MAGIC) || startsWith(data, GIF89_MAGIC);
    if (extension === 'webp') return isWebp(data);
    if (ZIP_EXTENSIONS.has(extension)) return startsWith(data, ZIP_MAGIC);
    if (extension === 'xls') return startsWith(data, OLE_MAGIC);
    return false;
  })();
  if (!valid) {
    throw new AppError(
      400,
      'unsupported_file_type',
      `文件内容与扩展名 .${extension || '未知'} 不一致`,
    );
  }
}

function stripControlCharacters(value: string): string {
  return [...value]
    .filter((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127)
    .join('');
}

/** Removes path separators and control characters while keeping Chinese names. */
export function sanitizeUploadFileName(raw: string): string {
  let name = stripControlCharacters(raw.replace(PATH_SEPARATORS, '')).trim();
  name = name.replace(/^\.+/, '');
  if (name.length > MAX_NAME_LENGTH) {
    const extension = extensionOf(name);
    const suffix = extension === '' ? '' : `.${extension}`;
    name = `${name.slice(0, MAX_NAME_LENGTH - suffix.length)}${suffix}`;
  }
  if (name === '' || name === '.' || name === '..' || /^\.+$/.test(name)) {
    throw new AppError(400, 'validation_error', '文件名无效');
  }
  return name;
}

function withSuffix(name: string, counter: number): string {
  const extension = extensionOf(name);
  if (extension === '') return `${name}-${counter}`;
  return `${name.slice(0, -(extension.length + 1))}-${counter}.${extension}`;
}

function dateStamp(now: Date): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${year}${month}${day}`;
}

export interface SavedUpload {
  path: string;
  name: string;
  size: number;
  kind: DeliverableKind;
}

/** Writes one upload under `uploads/<YYYYMMDD>/` and returns its workspace path. */
export function saveUpload(
  workspace: string,
  rawName: string,
  data: Buffer,
  options: { now?: Date; channelAudio?: boolean } = {},
): SavedUpload {
  if (data.length > MAX_UPLOAD_BYTES) {
    throw new AppError(413, 'payload_too_large', '单个文件不能超过 20 MB');
  }
  const name = sanitizeUploadFileName(rawName);
  const extension = extensionOf(name);
  if (!ALLOWED_UPLOAD_EXTENSIONS.has(extension) && !(options.channelAudio && ['silk', 'ogg', 'mp3', 'm4a'].includes(extension))) {
    throw new AppError(400, 'unsupported_file_type', `不支持的文件类型：.${extension || '未知'}`);
  }
  assertMagic(name, data);
  const kind = classifyKind(name);
  const directory = `${UPLOADS_DIRECTORY}/${dateStamp(options.now ?? new Date())}`;
  mkdirSync(join(workspace, UPLOADS_DIRECTORY), { recursive: true });
  mkdirSync(join(workspace, directory), { recursive: true });
  const realDirectory = resolveWorkspacePath(workspace, directory);

  let finalName = name;
  let counter = 2;
  while (true) {
    try {
      writeFileSync(join(realDirectory, finalName), data, { flag: 'wx' });
      break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error;
      finalName = withSuffix(name, counter);
      counter += 1;
    }
  }
  return {
    path: `${directory}/${finalName}`,
    name: finalName,
    size: data.length,
    kind,
  };
}

function isAttachment(value: unknown): value is { path: string } {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const entry = value as Record<string, unknown>;
  return typeof entry['path'] === 'string';
}

/**
 * Validates attachments sent with a message: at most ten, each an existing
 * file under `uploads/` inside the bot workspace.
 */
export function validateMessageAttachments(
  workspace: string,
  raw: unknown,
): MessageAttachmentDto[] {
  if (raw === undefined || raw === null) return [];
  if (!Array.isArray(raw)) {
    throw new AppError(400, 'validation_error', 'attachments must be an array');
  }
  if (raw.length > MAX_ATTACHMENTS_PER_MESSAGE) {
    throw new AppError(
      400,
      'validation_error',
      `一条消息最多 ${MAX_ATTACHMENTS_PER_MESSAGE} 个附件`,
    );
  }
  const attachments: MessageAttachmentDto[] = [];
  for (const value of raw) {
    if (!isAttachment(value)) {
      throw new AppError(400, 'validation_error', 'attachment must contain a path');
    }
    const path = value['path'].replaceAll('\\', '/');
    if (!path.startsWith(`${UPLOADS_DIRECTORY}/`)) {
      throw new AppError(400, 'validation_error', 'attachment must live under uploads/');
    }
    const absolute = resolveWorkspacePath(workspace, path);
    const stat = statSync(absolute);
    if (!stat.isFile()) {
      throw new AppError(400, 'validation_error', 'attachment is not a regular file');
    }
    if (stat.size > MAX_UPLOAD_BYTES) {
      throw new AppError(400, 'validation_error', 'attachment is larger than 20 MB');
    }
    const kind = classifyKind(path);
    const name = basename(path);
    attachments.push({
      path,
      name,
      size: stat.size,
      kind,
    });
  }
  return attachments;
}

export function attachmentKindLabel(kind: DeliverableKind): string {
  return ATTACHMENT_KIND_LABELS[kind] ?? '文件';
}

export function formatAttachmentSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** The paragraph appended to the user's prompt for one message's attachments. */
export function renderAttachmentPrompt(attachments: readonly MessageAttachmentDto[]): string {
  if (attachments.length === 0) return '';
  const lines = [
    '用户上传了以下文件（路径相对你的工作目录）：',
    ...attachments.map(
      (attachment) =>
        `- ${attachment.path}（${attachmentKindLabel(attachment.kind)}，${formatAttachmentSize(attachment.size)}）`,
    ),
  ];
  return lines.join('\n');
}

export interface LoopbackAddress {
  address: string;
  family: string;
}

/** True when the HTTP server is bound only to loopback. */
export function isLocalOnlyAddress(address: string | LoopbackAddress | null): boolean {
  if (address === null || typeof address === 'string') return false;
  return address.address === '127.0.0.1' || address.address === '::1' || address.address === '::ffff:127.0.0.1';
}
