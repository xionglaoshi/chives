import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { createApp, type ChivesApp } from '../src/app.js';
import type {
  AppearanceSettingsDto,
  DataLocationDto,
  ModelKeyDto,
  ModelSettingsDto,
  RuntimeSettingsDto,
  SettingsProfileDto,
} from '../src/api/protocol.js';
import { FakeDriver } from '../src/harness/fake.js';
import { DshDriver } from '../src/harness/dsh-driver.js';
import { resolveProfileServer, type ProfileServerConfig } from '../src/settings/index.js';
import { Store } from '../src/store/index.js';
import { makeBot, repoRoot, closeServer, listen, testConfig } from './support.js';

const fakeProfilePath = fileURLToPath(new URL('./fixtures/fake-profile-mcp.mjs', import.meta.url));
const fakeAgentPath = fileURLToPath(
  new URL('../../../packages/acp-client/test/fake-agent.mjs', import.meta.url),
);

interface Harness {
  app: ChivesApp;
  baseUrl: string;
  directory: string;
}

interface StartOptions {
  profileServer?: { config: ProfileServerConfig | null; error: string | null };
  engineHealth?: (port: number) => Promise<boolean>;
  revealExec?: (file: string, args: readonly string[], callback: (error: Error | null) => void) => void;
}

const harnesses: Harness[] = [];
const directories: string[] = [];

function envRecord(extra: Record<string, string> = {}): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (typeof value === 'string') env[key] = value;
  }
  return { ...env, ...extra };
}

async function startApp(options: StartOptions = {}): Promise<Harness> {
  const directory = await mkdtemp(join(tmpdir(), 'chives-settings-'));
  directories.push(directory);
  const app = createApp({
    config: testConfig(directory),
    driver: new FakeDriver(),
    ...(options.profileServer === undefined ? {} : { profileServer: options.profileServer }),
    ...(options.engineHealth === undefined ? {} : { engineHealth: options.engineHealth }),
    ...(options.revealExec === undefined
      ? {}
      : { revealExec: options.revealExec, platform: 'darwin' as const }),
  });
  const baseUrl = await listen(app.server);
  const harness = { app, baseUrl, directory };
  harnesses.push(harness);
  return harness;
}

function profileServer(logPath?: string): { config: ProfileServerConfig; error: null } {
  return {
    config: {
      command: process.execPath,
      args: [fakeProfilePath],
      cwd: repoRoot,
      env: envRecord({
        DSH_HOME: '/tmp/chives-test-dsh-home',
        ...(logPath === undefined ? {} : { FAKE_PROFILE_LOG: logPath }),
      }),
    },
    error: null,
  };
}

afterEach(async () => {
  for (const harness of harnesses.splice(0)) {
    await closeServer(harness.app.server);
    await harness.app.close();
  }
  for (const directory of directories.splice(0)) {
    await rm(directory, { recursive: true, force: true });
  }
});

async function json<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

describe('settings profile over a fake stdio MCP server', () => {
  it('reads, updates and clears fields through the MCP client', async () => {
    const logPath = join(tmpdir(), `chives-profile-log-${Date.now()}.jsonl`);
    const harness = await startApp({ profileServer: profileServer(logPath) });

    const empty = await json<SettingsProfileDto>(
      await fetch(`${harness.baseUrl}/api/settings/profile`),
    );
    expect(empty.available).toBe(true);
    expect(empty.fields).toEqual({});
    expect(empty.error).toBeNull();

    const updated = await fetch(`${harness.baseUrl}/api/settings/profile`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ fields: { risk_level: 'balanced', sectors: ['白酒', '算力'] } }),
    });
    expect(updated.status).toBe(200);
    expect(await json<SettingsProfileDto>(updated)).toMatchObject({
      available: true,
      fields: { risk_level: 'balanced', sectors: ['白酒', '算力'] },
    });

    const readBack = await json<SettingsProfileDto>(
      await fetch(`${harness.baseUrl}/api/settings/profile`),
    );
    expect(readBack.fields['risk_level']).toBe('balanced');

    const cleared = await fetch(`${harness.baseUrl}/api/settings/profile`, {
      method: 'DELETE',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ fields: ['sectors'] }),
    });
    expect(cleared.status).toBe(200);
    const afterClear = await json<SettingsProfileDto>(cleared);
    expect(afterClear.fields['sectors']).toBeUndefined();
    expect(afterClear.fields['risk_level']).toBe('balanced');

    const invalid = await fetch(`${harness.baseUrl}/api/settings/profile`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ fields: { risk_level: 'yolo' } }),
    });
    expect(invalid.status).toBe(400);
    expect((await json<{ error: { code: string } }>(invalid)).error.code).toBe('invalid_value');

    const log = await readFile(logPath, 'utf8');
    expect(log).toContain('"/tmp/chives-test-dsh-home"');
    await rm(logPath, { force: true });
  });

  it('reports an unavailable profile service without breaking other settings', async () => {
    const harness = await startApp({
      profileServer: {
        config: {
          command: join(tmpdir(), 'missing-profile-mcp-binary'),
          args: [],
          env: envRecord(),
        },
        error: null,
      },
    });

    const profile = await json<SettingsProfileDto>(
      await fetch(`${harness.baseUrl}/api/settings/profile`),
    );
    expect(profile.available).toBe(false);
    expect(profile.error).not.toBeNull();

    const proactive = await fetch(`${harness.baseUrl}/api/settings/proactive`);
    expect(proactive.status).toBe(200);
    expect(await json<{ enabled: boolean }>(proactive)).toMatchObject({ enabled: true });
  });

  it('takes the profile command from the overlay and passes DSH_HOME', () => {
    const resolved = resolveProfileServer(repoRoot, '/tmp/configured-dsh-home');
    expect(resolved.error).toBeNull();
    expect(resolved.config?.command).toContain('profile-mcp/.venv/bin/python');
    expect(resolved.config?.args).toEqual(['-m', 'profile_mcp']);
    expect(resolved.config?.env['DSH_HOME']).toBe('/tmp/configured-dsh-home');
  });
});

describe('settings runtime, model and keys', () => {
  it('reports harness, bot process and engine health', async () => {
    const harness = await startApp({
      engineHealth: async (port) => port !== 8866,
    });
    harness.app.processMonitor.markRunning('expert');

    const runtime = await json<RuntimeSettingsDto>(
      await fetch(`${harness.baseUrl}/api/settings/runtime`),
    );
    expect(runtime.harness.name).toBe('Fake Harness');
    expect(runtime.harness.version).toBeNull();
    expect(runtime.engines).toEqual([
      { port: 8865, healthy: true },
      { port: 8866, healthy: false },
      { port: 8867, healthy: true },
    ]);
    expect(runtime.bots.find((bot) => bot.id === 'expert')?.process).toBe('running');
    expect(runtime.bots.find((bot) => bot.id === 'research')?.process).toBe('not_started');
  });

  it('stores default model options captured from session/new', async () => {
    const harness = await startApp();

    const empty = await json<ModelSettingsDto>(
      await fetch(`${harness.baseUrl}/api/settings/models`),
    );
    expect(empty).toEqual({ selected: null, options: [] });

    const tooEarly = await fetch(`${harness.baseUrl}/api/settings/models`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ value: 'm1' }),
    });
    expect(tooEarly.status).toBe(400);

    harness.app.settings.noteConfigOptions([
      {
        id: 'model',
        options: [
          { value: 'm1', name: 'Model One' },
          { value: 'm2', name: 'Model Two' },
        ],
      },
    ]);
    const listed = await json<ModelSettingsDto>(
      await fetch(`${harness.baseUrl}/api/settings/models`),
    );
    expect(listed.options).toEqual([
      { value: 'm1', name: 'Model One' },
      { value: 'm2', name: 'Model Two' },
    ]);

    // dsh groups choices by provider; the values are JSON-encoded [provider, model] pairs.
    harness.app.settings.noteConfigOptions([
      {
        id: 'model',
        options: [
          {
            group: 'huosan',
            name: 'huosan',
            options: [
              { value: '["huosan","m1"]', name: 'Model One' },
              { value: '["huosan","m2"]', name: 'Model Two' },
            ],
          },
        ],
      } as never,
    ]);
    const grouped = await json<ModelSettingsDto>(
      await fetch(`${harness.baseUrl}/api/settings/models`),
    );
    expect(grouped.options.map((option) => option.value)).toEqual(['["huosan","m1"]', '["huosan","m2"]']);
    harness.app.settings.noteConfigOptions([
      {
        id: 'model',
        options: [
          { value: 'm1', name: 'Model One' },
          { value: 'm2', name: 'Model Two' },
        ],
      },
    ]);

    const saved = await fetch(`${harness.baseUrl}/api/settings/models`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ value: 'm2' }),
    });
    expect(saved.status).toBe(200);
    expect(await json<ModelSettingsDto>(saved)).toMatchObject({ selected: 'm2' });

    const unknown = await fetch(`${harness.baseUrl}/api/settings/models`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ value: 'nope' }),
    });
    expect(unknown.status).toBe(400);
  });

  it('never exposes key values and reports configured as a boolean', async () => {
    const harness = await startApp();
    const logs: unknown[][] = [];
    const logSpy = vi.spyOn(console, 'log').mockImplementation((...args: unknown[]) => {
      logs.push(args);
    });
    const errorSpy = vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
      logs.push(args);
    });
    const previousTavily = process.env['TAVILY_API_KEY'];
    const previousGildata = process.env['GILDATA_TOKEN'];
    process.env['TAVILY_API_KEY'] = 'secret-value';
    delete process.env['GILDATA_TOKEN'];
    try {
      const response = await fetch(`${harness.baseUrl}/api/settings/keys`);
      const body = await response.text();
      expect(body).not.toContain('secret-value');
      const keys = JSON.parse(body) as ModelKeyDto[];
      expect(logs.flat().join(' ')).not.toContain('secret-value');
      expect(keys).toEqual([
        { name: 'TAVILY_API_KEY', configured: true },
        { name: 'GILDATA_TOKEN', configured: false },
        { name: '模型路由', configured: false },
      ]);
    } finally {
      if (previousTavily === undefined) delete process.env['TAVILY_API_KEY'];
      else process.env['TAVILY_API_KEY'] = previousTavily;
      if (previousGildata === undefined) delete process.env['GILDATA_TOKEN'];
      else process.env['GILDATA_TOKEN'] = previousGildata;
      logSpy.mockRestore();
      errorSpy.mockRestore();
    }
  });
});

describe('settings appearance, data and export', () => {
  it('persists appearance and applies defaults', async () => {
    const harness = await startApp();
    const defaults = await json<AppearanceSettingsDto>(
      await fetch(`${harness.baseUrl}/api/settings/appearance`),
    );
    expect(defaults).toEqual({ theme: 'system', changeColor: 'red-up' });

    const saved = await fetch(`${harness.baseUrl}/api/settings/appearance`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ theme: 'light', changeColor: 'green-up' }),
    });
    expect(saved.status).toBe(200);
    expect(await json<AppearanceSettingsDto>(saved)).toEqual({
      theme: 'light',
      changeColor: 'green-up',
    });

    const invalid = await fetch(`${harness.baseUrl}/api/settings/appearance`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ theme: 'sepia' }),
    });
    expect(invalid.status).toBe(400);
  });

  it('reports the data directory, reveals it and exports without secrets', async () => {
    const opened: Array<{ file: string; args: readonly string[] }> = [];
    const harness = await startApp({
      revealExec: (file, args, callback) => {
        opened.push({ file, args: [...args] });
        callback(null);
      },
    });
    await writeFile(join(harness.directory, 'sample.txt'), 'local data');

    const data = await json<DataLocationDto>(
      await fetch(`${harness.baseUrl}/api/settings/data`),
    );
    expect(data.path).toBe(harness.directory);
    expect(data.bytes).toBeGreaterThan(0);

    const reveal = await fetch(`${harness.baseUrl}/api/settings/data/reveal`, { method: 'POST' });
    expect(reveal.status).toBe(200);
    expect(opened).toEqual([{ file: 'open', args: [harness.directory] }]);

    harness.app.store.messages.append({
      id: 'export-message',
      botId: 'expert',
      taskId: null,
      role: 'user',
      kind: 'text',
      content: '导出我',
      createdAt: new Date().toISOString(),
    });
    process.env['TAVILY_API_KEY'] = 'secret-value';
    try {
      const response = await fetch(`${harness.baseUrl}/api/export`);
      expect(response.status).toBe(200);
      expect(response.headers.get('content-disposition')).toMatch(
        /attachment; filename="chives-export-\d{8}-\d{4}\.json"/,
      );
      const body = await response.text();
      expect(body).not.toContain('secret-value');
      expect(body).not.toContain('"dataDir"');
      const payload = JSON.parse(body) as {
        formatVersion: number;
        messages: Array<{ id: string }>;
        tasks: unknown[];
        settings: { appearance: AppearanceSettingsDto };
      };
      expect(payload.formatVersion).toBe(1);
      expect(payload.messages.some((message) => message.id === 'export-message')).toBe(true);
      expect(Array.isArray(payload.tasks)).toBe(true);
      expect(payload.settings.appearance).toEqual({ theme: 'system', changeColor: 'red-up' });
    } finally {
      delete process.env['TAVILY_API_KEY'];
    }
  });
});

describe('DshDriver default model', () => {
  it('applies the saved model to a new session but not to non-default bots', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'chives-model-driver-'));
    directories.push(dataDir);
    const logPath = join(dataDir, 'agent.log');
    const captured: string[] = [];
    const driver = new DshDriver({
      dataDir,
      dshHome: join(dataDir, 'dsh-home'),
      modelOverlay: '',
      personaTextFor: () => '',
      spawnSpecFor: () => ({
        command: process.execPath,
        args: [fakeAgentPath],
        env: {
          ...envRecord({ FAKE_AGENT_SCENARIO: 'normal', FAKE_AGENT_LOG: logPath }),
        },
      }),
      defaultModel: () => 'fake-model',
      onConfigOptions: (_bot, options) => {
        const model = options.find((option) => option.id === 'model');
        for (const choice of model?.options ?? []) captured.push(choice.value);
      },
    });
    const store = Store.open(dataDir);
    try {
      const bot = makeBot({ id: 'default-bot' });
      const task = store.tasks.create({
        botId: bot.id,
        title: 'model',
        startedAt: new Date().toISOString(),
      });
      await driver.ensureSession(bot, task);

      const log = await readFile(logPath, 'utf8');
      const calls = log
        .trim()
        .split('\n')
        .map((line) => JSON.parse(line) as { method?: string; params?: Record<string, unknown> })
        .filter((entry) => entry.method === 'session/set_config_option');
      expect(calls).toHaveLength(1);
      expect(calls[0]?.params).toMatchObject({ configId: 'model', value: 'fake-model' });
      expect(captured).toContain('fake-model');

      const other = makeBot({ id: 'other-bot', model: 'named-route' });
      const otherTask = store.tasks.create({
        botId: other.id,
        title: 'other',
        startedAt: new Date().toISOString(),
      });
      await driver.ensureSession(other, otherTask);
      const after = (await readFile(logPath, 'utf8'))
        .trim()
        .split('\n')
        .map((line) => JSON.parse(line) as { method?: string })
        .filter((entry) => entry.method === 'session/set_config_option');
      expect(after).toHaveLength(1);
    } finally {
      await driver.shutdown();
      store.close();
    }
  });
});
