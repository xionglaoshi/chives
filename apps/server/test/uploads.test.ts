import { existsSync, mkdirSync, readFileSync, utimesSync, writeFileSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type { HarnessDriver, HarnessPromptResult, HarnessSink } from '../src/harness/types.js';
import type { BotManifest } from '../src/bots/index.js';
import type { TaskRecord } from '../src/store/index.js';
import type { MessageAccepted, MessageAttachmentDto } from '../src/api/protocol.js';
import {
  MAX_UPLOAD_BYTES,
  generateWorkspaceMap,
  isDeliverablePath,
  sanitizeUploadFileName
} from '../src/deliverables/index.js';
import { closeServer, listen, testConfig, waitFor } from './support.js';

const PNG = Buffer.concat([
  Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
  Buffer.from('fake-png-body')
]);

interface Entry {
  app: ChivesApp;
  baseUrl: string;
}

const directories: string[] = [];
const entries: Entry[] = [];

afterEach(async () => {
  for (const entry of entries.splice(0)) {
    entry.app.sse.closeAll();
    await closeServer(entry.app.server);
    await entry.app.close();
  }
  for (const directory of directories.splice(0)) {
    await rm(directory, { recursive: true, force: true });
  }
});

async function tempDir(prefix: string): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), prefix));
  directories.push(directory);
  return directory;
}

function workspaceOf(dataDir: string): string {
  return join(dataDir, 'bots', 'expert', 'workspace');
}

class RecordingDriver implements HarnessDriver {
  readonly prompts: string[] = [];

  ensureSession(
    _bot: BotManifest,
    task: TaskRecord
  ): Promise<string> {
    return Promise.resolve(task.harnessSessionId ?? 'upload-session');
  }

  async prompt(
    _bot: BotManifest,
    _sessionId: string,
    text: string,
    sink: HarnessSink
  ): Promise<HarnessPromptResult> {
    this.prompts.push(text);
    sink({ type: 'message', text: '收到' });
    return { stopReason: 'end_turn' };
  }

  cancel(): void {
    // Nothing to cancel in this deterministic driver.
  }

  async shutdown(): Promise<void> {
    // No process to stop.
  }
}

async function startApp(dataDir: string, driver?: HarnessDriver): Promise<Entry> {
  const app = createApp({
    config: testConfig(dataDir),
    ...(driver === undefined ? {} : { driver })
  });
  const baseUrl = await listen(app.server);
  const entry = { app, baseUrl };
  entries.push(entry);
  return entry;
}

async function upload(
  baseUrl: string,
  name: string,
  body: Buffer
): Promise<Response> {
  return fetch(`${baseUrl}/api/bots/expert/uploads`, {
    method: 'POST',
    headers: { 'x-file-name': encodeURIComponent(name) },
    body: new Uint8Array(body)
  });
}

describe('upload endpoint', () => {
  it('stores a file under uploads/<date>/, dedupes the name, and updates MAP.md', async () => {
    const dataDir = await tempDir('chives-upload-');
    const { baseUrl } = await startApp(dataDir);

    const first = await upload(baseUrl, '行情截图.png', PNG);
    expect(first.status).toBe(200);
    const saved = (await first.json()) as MessageAttachmentDto;
    expect(saved.path).toMatch(/^uploads\/\d{8}\/行情截图\.png$/);
    expect(saved.name).toBe('行情截图.png');
    expect(saved.size).toBe(PNG.length);
    expect(saved.kind).toBe('image');
    expect(existsSync(join(workspaceOf(dataDir), saved.path))).toBe(true);

    const second = await upload(baseUrl, '行情截图.png', PNG);
    const deduped = (await second.json()) as MessageAttachmentDto;
    expect(deduped.path).toMatch(/-2\.png$/);
    expect(deduped.name).toBe('行情截图-2.png');

    const map = readFileSync(join(workspaceOf(dataDir), 'MAP.md'), 'utf8');
    expect(map).toContain('## 用户上传/');
    expect(map).toContain('[行情截图.png](uploads/');
  });

  it('removes separators and control characters, and keeps Chinese names', async () => {
    expect(sanitizeUploadFileName('../一季度\n报告.md')).toBe('一季度报告.md');
    expect(sanitizeUploadFileName('..\\..\\secret.md')).toBe('secret.md');
    const dataDir = await tempDir('chives-upload-name-');
    const { baseUrl } = await startApp(dataDir);
    const response = await upload(baseUrl, '../一季度\n报告.md', Buffer.from('# 中文\n', 'utf8'));
    expect(response.status).toBe(200);
    const saved = (await response.json()) as MessageAttachmentDto;
    expect(saved.path).toMatch(/^uploads\/\d{8}\/一季度报告\.md$/);
    expect(saved.path).not.toContain('..');
    expect(existsSync(join(workspaceOf(dataDir), saved.path))).toBe(true);
  });

  it('rejects an oversized file before writing it', async () => {
    const dataDir = await tempDir('chives-upload-big-');
    const { baseUrl } = await startApp(dataDir);
    const response = await upload(baseUrl, 'big.txt', Buffer.alloc(MAX_UPLOAD_BYTES + 1, 0x61));
    expect(response.status).toBe(413);
  });

  it('rejects a file whose magic bytes do not match its extension', async () => {
    const dataDir = await tempDir('chives-upload-type-');
    const { baseUrl } = await startApp(dataDir);
    const response = await upload(baseUrl, 'not-image.png', Buffer.from('plain text', 'utf8'));
    expect(response.status).toBe(400);
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe(
      'unsupported_file_type'
    );
    const wrongText = await upload(baseUrl, 'data.json', Buffer.from('not json', 'utf8'));
    expect(wrongText.status).toBe(400);
  });

  it('rejects a traversal-looking name without escaping the workspace', async () => {
    const dataDir = await tempDir('chives-upload-traversal-');
    const { baseUrl } = await startApp(dataDir);
    const response = await upload(baseUrl, '../../secret.md', Buffer.from('# secret', 'utf8'));
    expect(response.status).toBe(200);
    const saved = (await response.json()) as MessageAttachmentDto;
    expect(saved.path).toMatch(/^uploads\/\d{8}\/secret\.md$/);
    expect(existsSync(join(dataDir, 'secret.md'))).toBe(false);
    expect(existsSync(join(workspaceOf(dataDir), '..', 'secret.md'))).toBe(false);
  });

  it('refuses uploads when the server is not bound to loopback', async () => {
    const dataDir = await tempDir('chives-upload-host-');
    const app = createApp({ config: testConfig(dataDir) });
    await new Promise<void>((resolve) => {
      app.server.listen(0, '0.0.0.0', () => resolve());
    });
    const address = app.server.address();
    if (address === null || typeof address === 'string') throw new Error('missing address');
    const baseUrl = `http://127.0.0.1:${address.port}`;
    entries.push({ app, baseUrl });

    const response = await upload(baseUrl, 'a.txt', Buffer.from('hello', 'utf8'));
    expect(response.status).toBe(403);
  });
});

describe('uploads in MAP.md and deliverables', () => {
  it('is not a deliverable', () => {
    expect(isDeliverablePath('uploads/20261117/report.md')).toBe(false);
    expect(isDeliverablePath('uploads/20261117/chart.png')).toBe(false);
  });

  it('lists the 20 newest uploads and notes the rest', async () => {
    const dataDir = await tempDir('chives-upload-map-');
    const workspace = workspaceOf(dataDir);
    const directory = join(workspace, 'uploads', '20261117');
    mkdirSync(directory, { recursive: true });
    const base = new Date('2026-11-17T00:00:00.000Z');
    for (let index = 0; index < 21; index += 1) {
      const file = join(directory, `file-${String(index).padStart(2, '0')}.txt`);
      writeFileSync(file, `file ${index}`);
      const stamp = new Date(base.getTime() + index * 60_000);
      utimesSync(file, stamp, stamp);
    }
    const map = generateWorkspaceMap(workspace);
    expect(map).toContain('## 用户上传/');
    expect(map).toContain('另有 1 个上传文件未列出');
    expect(map).toContain('[file-20.txt](uploads/20261117/file-20.txt)');
  });
});

describe('message attachments', () => {
  it('stores attachments in meta and appends the upload paragraph to the prompt', async () => {
    const dataDir = await tempDir('chives-upload-message-');
    const driver = new RecordingDriver();
    const { baseUrl, app } = await startApp(dataDir, driver);

    const md = (await (await upload(baseUrl, 'note.md', Buffer.from('# 笔记\n', 'utf8'))).json()) as MessageAttachmentDto;
    const png = (await (await upload(baseUrl, 'chart.png', PNG)).json()) as MessageAttachmentDto;

    const response = await fetch(`${baseUrl}/api/bots/expert/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: '看这两个文件', attachments: [md, png] })
    });
    expect(response.status).toBe(202);
    const accepted = (await response.json()) as MessageAccepted;
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');

    const user = app.store.messages.listByTask(accepted.taskId).find((message) => message.role === 'user');
    expect(user?.meta?.['attachments']).toEqual([md, png]);
    const prompt = driver.prompts.at(-1) ?? '';
    expect(prompt).toContain('看这两个文件');
    expect(prompt).toContain('用户上传了以下文件（路径相对你的工作目录）：');
    expect(prompt).toContain(`- ${md.path}（文档，`);
    expect(prompt).toContain(`- ${png.path}（图片，`);
  });

  it('accepts an attachment-only message', async () => {
    const dataDir = await tempDir('chives-upload-only-');
    const driver = new RecordingDriver();
    const { baseUrl, app } = await startApp(dataDir, driver);
    const file = (await (await upload(baseUrl, 'only.md', Buffer.from('# only\n', 'utf8'))).json()) as MessageAttachmentDto;

    const response = await fetch(`${baseUrl}/api/bots/expert/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: '', attachments: [file] })
    });
    expect(response.status).toBe(202);
    const accepted = (await response.json()) as MessageAccepted;
    await waitFor(() => app.store.tasks.get(accepted.taskId)?.status === 'done');
    const user = app.store.messages.listByTask(accepted.taskId).find((message) => message.role === 'user');
    expect(user?.content).toBe('');
    expect(user?.meta?.['attachments']).toEqual([file]);
    expect(driver.prompts.at(-1)).toContain(`- ${file.path}（文档，`);
  });

  it('rejects paths outside uploads/ and an empty message with no attachments', async () => {
    const dataDir = await tempDir('chives-upload-invalid-');
    const { baseUrl } = await startApp(dataDir, new RecordingDriver());
    const outside = await fetch(`${baseUrl}/api/bots/expert/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        text: 'x',
        attachments: [{ path: 'reports/x.md', name: 'x.md', size: 1, kind: 'markdown' }]
      })
    });
    expect(outside.status).toBe(400);
    const empty = await fetch(`${baseUrl}/api/bots/expert/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text: '' })
    });
    expect(empty.status).toBe(400);
  });
});
