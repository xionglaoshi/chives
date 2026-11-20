import { mkdtemp, readdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import { botSkillsDir } from '../src/bots/index.js';
import { CHIVES_SERVER_HOST } from '../src/index.js';
import { FakeDriver } from '../src/harness/fake.js';
import { makeRegistry, testConfig } from './support.js';

describe('createApp', () => {
  let app: ChivesApp;
  let baseUrl: string;
  let dataDir: string;

  beforeAll(async () => {
    dataDir = await mkdtemp(join(tmpdir(), 'chives-index-'));
    app = createApp({ config: testConfig(dataDir), driver: new FakeDriver() });
    await new Promise<void>((resolve) => {
      app.server.listen(0, CHIVES_SERVER_HOST, resolve);
    });
    const address = app.server.address();
    if (address === null || typeof address === 'string') throw new Error('missing address');
    baseUrl = `http://${CHIVES_SERVER_HOST}:${address.port}`;
  });

  afterAll(async () => {
    app.sse.closeAll();
    await new Promise<void>((resolve, reject) => {
      app.server.close((error) => (error === undefined ? resolve() : reject(error)));
    });
    await app.close();
    await rm(dataDir, { recursive: true, force: true });
  });

  it('serves the health endpoint', async () => {
    const response = await fetch(`${baseUrl}/api/health`);

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ ok: true });
  });

  it('materializes each bot skill directory at startup', async () => {
    for (const bot of makeRegistry().list()) {
      const entries = await readdir(botSkillsDir(dataDir, bot.id));
      expect(entries.sort()).toEqual([...bot.skills].sort());
    }
  });
});
