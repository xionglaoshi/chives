import { cpSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it } from 'vitest';
import { createApp } from '../src/app.js';
import { closeServer, listen, repoRoot, testConfig } from './support.js';

it('keeps the CEO as the permanent Bot and reserves hiring for the owner', async () => {
  const root = mkdtempSync(join(tmpdir(), 'chives-ceo-'));
  const config = { ...testConfig(join(root, 'data')), botsDir: join(root, 'bots') };
  for (const name of ['ceo', '_shared']) {
    cpSync(join(repoRoot, 'bots', name), join(config.botsDir, name), { recursive: true });
  }
  const app = createApp({ config, startSchedulers: false });
  const base = await listen(app.server);
  try {
    const parent = app.store.tasks.create({ botId: 'ceo', startedAt: new Date().toISOString() });
    const token = app.sessions.issue({ botId: 'ceo', taskId: parent.id, depth: 0 });
    const employment = '/api/settings/desk/employment';
    const headers = { 'Content-Type': 'application/json', 'X-Chives-Kernel-Manager': 'local' };
    const roster = await fetch(base + employment, { headers }).then(response => response.json());
    expect(roster).toEqual([{ id: 'ceo', name: '总经理', hired: true, permanent: true }]);
    const rejected = await fetch(base + employment, {
      method: 'PUT', headers, body: JSON.stringify({ expected: { ceo: true }, hiredIds: [] }),
    });
    expect(rejected.status).toBe(400);
    const botEdit = await fetch(base + employment, {
      method: 'PUT', headers: { ...headers, Authorization: 'Bearer ' + token },
      body: JSON.stringify({ expected: { ceo: true }, hiredIds: ['ceo'] }),
    });
    expect(botEdit.status).toBe(403);
  } finally {
    app.sse.closeAll();
    await closeServer(app.server);
    await app.close();
    rmSync(root, { recursive: true, force: true });
  }
});
