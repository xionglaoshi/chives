import {
  closeSync,
  ftruncateSync,
  mkdirSync,
  openSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import { BINARY_CONTENT_LIMIT_BYTES } from '../src/deliverables/index.js';
import { FakeDriver } from '../src/harness/fake.js';
import { closeServer, listen, testConfig } from './support.js';

const directories: string[] = [];
const apps: ChivesApp[] = [];

afterEach(async () => {
  for (const app of apps.splice(0)) {
    app.sse.closeAll();
    await closeServer(app.server);
    await app.close();
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

function workspaceOf(dataDir: string, botId: string): string {
  return join(dataDir, 'bots', botId, 'workspace');
}

async function startApp(dataDir: string): Promise<{ baseUrl: string; workspace: string }> {
  const workspace = workspaceOf(dataDir, 'expert');
  const driver = new FakeDriver({ workspaceDirFor: (bot) => workspaceOf(dataDir, bot.id) });
  const app = createApp({ config: testConfig(dataDir), driver });
  apps.push(app);
  const baseUrl = await listen(app.server);
  return { baseUrl, workspace };
}

function imageUrl(baseUrl: string, path: string, botId = 'expert'): string {
  return `${baseUrl}/api/bots/${botId}/files/content?path=${encodeURIComponent(path)}`;
}

describe('bot workspace image content API', () => {
  it('serves a png with revalidation headers and honours conditional requests', async () => {
    const dataDir = await tempDir('chives-image-api-');
    const { baseUrl, workspace } = await startApp(dataDir);
    mkdirSync(join(workspace, 'charts'), { recursive: true });
    writeFileSync(join(workspace, 'charts', 'k.png'), Buffer.from([0x89, 0x50, 0x4e, 0x47]));

    const response = await fetch(imageUrl(baseUrl, 'charts/k.png'));
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toBe('image/png');
    expect(response.headers.get('cache-control')).toBe('no-cache');
    expect(response.headers.get('x-content-type-options')).toBe('nosniff');
    const etag = response.headers.get('etag');
    const lastModified = response.headers.get('last-modified');
    expect(etag).not.toBeNull();
    expect(lastModified).not.toBeNull();
    expect((await response.arrayBuffer()).byteLength).toBe(4);

    const byEtag = await fetch(imageUrl(baseUrl, 'charts/k.png'), {
      headers: { 'if-none-match': etag ?? '' },
    });
    expect(byEtag.status).toBe(304);
    expect(byEtag.headers.get('etag')).toBe(etag);

    const byDate = await fetch(imageUrl(baseUrl, 'charts/k.png'), {
      headers: { 'if-modified-since': lastModified ?? '' },
    });
    expect(byDate.status).toBe(304);
  });

  it('serves svg as image/svg+xml with a sandbox CSP', async () => {
    const dataDir = await tempDir('chives-image-svg-');
    const { baseUrl, workspace } = await startApp(dataDir);
    mkdirSync(workspace, { recursive: true });
    writeFileSync(
      join(workspace, 'chart.svg'),
      '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    );

    const response = await fetch(imageUrl(baseUrl, 'chart.svg'));
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toBe('image/svg+xml');
    expect(response.headers.get('content-security-policy')).toBe('sandbox');
  });

  it('rejects escapes, non-images, missing files, and oversized images', async () => {
    const dataDir = await tempDir('chives-image-guard-');
    const { baseUrl, workspace } = await startApp(dataDir);
    mkdirSync(workspace, { recursive: true });
    writeFileSync(join(workspace, '..', 'outside.png'), 'png');
    writeFileSync(join(workspace, 'notes.txt'), 'text');
    writeFileSync(join(workspace, 'inside.png'), 'png');
    symlinkSync(join(workspace, '..', 'outside.png'), join(workspace, 'leak.png'));
    const big = join(workspace, 'big.png');
    const fd = openSync(big, 'w');
    ftruncateSync(fd, BINARY_CONTENT_LIMIT_BYTES + 1);
    closeSync(fd);

    expect((await fetch(imageUrl(baseUrl, '../outside.png'))).status).toBe(403);
    expect((await fetch(imageUrl(baseUrl, '/etc/passwd'))).status).toBe(403);
    expect((await fetch(imageUrl(baseUrl, 'leak.png'))).status).toBe(403);
    expect((await fetch(imageUrl(baseUrl, 'notes.txt'))).status).toBe(404);
    expect((await fetch(imageUrl(baseUrl, 'missing.png'))).status).toBe(404);
    expect((await fetch(imageUrl(baseUrl, 'big.png'))).status).toBe(413);
    expect((await fetch(imageUrl(baseUrl, 'inside.png', 'nobody'))).status).toBe(404);
    expect((await fetch(`${baseUrl}/api/bots/expert/files/content`)).status).toBe(400);
    expect(
      (await fetch(imageUrl(baseUrl, 'inside.png'), { method: 'POST' })).status,
    ).toBe(405);
  });

  it('returns the existing JSON error shape', async () => {
    const dataDir = await tempDir('chives-image-error-shape-');
    const { baseUrl, workspace } = await startApp(dataDir);
    mkdirSync(workspace, { recursive: true });
    writeFileSync(join(workspace, 'notes.txt'), 'text');
    const response = await fetch(imageUrl(baseUrl, 'notes.txt'));
    await expect(response.json()).resolves.toEqual({
      error: {
        code: 'image_not_found',
        message: 'only png, jpg, jpeg, gif, webp and svg images can be served',
      },
    });
  });
});
