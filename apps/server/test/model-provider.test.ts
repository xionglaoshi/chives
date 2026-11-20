import { mkdtempSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, afterEach, describe, expect, it } from 'vitest';
import { parse } from 'yaml';

import { createApp, type ChivesApp } from '../src/app.js';
import type { ModelProviderDto } from '../src/api/protocol.js';
import { FakeDriver } from '../src/harness/fake.js';
import { dshPatchPath, dshSpawnSpec } from '../src/harness/index.js';
import { buildCatalog, loadBots, type BotManifest } from '../src/bots/index.js';
import {
  buildModelPatch,
  MODEL_KEY_ENV,
  ModelProviderError,
  ModelProviderStore,
  parseModelProvider,
} from '../src/settings/model-provider.js';
import { Store } from '../src/store/index.js';
import { closeServer, listen, repoRoot, testConfig } from './support.js';

const dirs: string[] = [];
function tempDir(): string {
  const dir = mkdtempSync(join(tmpdir(), 'chives-model-'));
  dirs.push(dir);
  return dir;
}
afterAll(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
});

const FLASH = {
  baseURL: 'https://gateway.example/v1/',
  api: 'openai-completions',
  model: 'deepseek-v4.1-flash',
  deepseekThinking: true,
};

describe('parseModelProvider', () => {
  it('normalizes the base URL and rejects bad input', () => {
    expect(parseModelProvider(FLASH).baseURL).toBe('https://gateway.example/v1');
    expect(() => parseModelProvider({ ...FLASH, baseURL: 'ftp://x' })).toThrow(ModelProviderError);
    expect(() => parseModelProvider({ ...FLASH, baseURL: 'https://u:p@x.example' })).toThrow(
      ModelProviderError,
    );
    expect(() => parseModelProvider({ ...FLASH, model: 'a b' })).toThrow(ModelProviderError);
    expect(() => parseModelProvider({ ...FLASH, api: 'grpc' })).toThrow(ModelProviderError);
    expect(() => parseModelProvider({ ...FLASH, maxTokens: -1 })).toThrow(ModelProviderError);
    expect(() => parseModelProvider({ ...FLASH, apiKey: 'sk' })).toThrow(ModelProviderError);
  });
});

describe('buildModelPatch', () => {
  it('uses the native Codex subscription route and fixes its destination', () => {
    const config = { api: 'openai-codex-subscription', baseURL: 'https://chatgpt.com/backend-api', model: 'gpt-5.5', deepseekThinking: false };
    expect(parse(buildModelPatch(parseModelProvider(config)))[0].config.providers).toEqual({
      'openai-codex': { models: [{ id: config.model }] },
    });
    expect(() => parseModelProvider({ ...config, baseURL: 'https://other.example' })).toThrow();
  });

  it('declares one pi-ai route that names the key by env var only', () => {
    const doc = parse(
      buildModelPatch(parseModelProvider({ ...FLASH, contextWindow: 1_000_000, maxTokens: 65_536 })),
    ) as Array<{ id: string; config: { providers: Record<string, Record<string, unknown>> } }>;
    expect(doc).toHaveLength(1);
    expect(doc[0]?.id).toBe('llm-pi-ai');
    const route = doc[0]?.config.providers['chives'];
    expect(route).toMatchObject({
      apiKeyEnv: MODEL_KEY_ENV,
      api: 'openai-completions',
      baseURL: 'https://gateway.example/v1',
      models: [
        {
          id: 'deepseek-v4.1-flash',
          contextWindow: 1_000_000,
          maxTokens: 65_536,
          compat: { thinkingFormat: 'deepseek' },
          reasoningEfforts: { off: null, high: 'high', max: 'max' },
        },
      ],
    });
  });

  it('omits the DeepSeek thinking switch when turned off', () => {
    const text = buildModelPatch(parseModelProvider({ ...FLASH, deepseekThinking: false }));
    expect(text).not.toContain('thinkingFormat');
  });
});

describe('ModelProviderStore', () => {
  it('keeps the key in a 0600 file, never in the DTO or the patch', () => {
    const dataDir = tempDir();
    const store = Store.open(dataDir);
    const provider = new ModelProviderStore(store, dataDir);
    expect(provider.runtime()).toBeUndefined();
    expect(provider.dto().active).toBe(false);

    const saved = provider.write(parseModelProvider(FLASH), 'sk-test-123');
    expect(saved.active).toBe(true);
    expect(JSON.stringify(saved)).not.toContain('sk-test-123');
    const keyPath = join(dataDir, 'secrets', 'model.env');
    expect(statSync(keyPath).mode & 0o777).toBe(0o600);

    const runtime = provider.runtime();
    expect(runtime?.route).toEqual({ provider: 'chives', model: 'deepseek-v4.1-flash' });
    expect(runtime?.env).toEqual({ [MODEL_KEY_ENV]: 'sk-test-123' });
    expect(readFileSync(runtime?.patchPath ?? '', 'utf8')).not.toContain('sk-test-123');

    // Omitting the key keeps it; clearing removes config, key and patch.
    provider.write(parseModelProvider({ ...FLASH, model: 'deepseek-v4.1-pro' }), undefined);
    expect(provider.runtime()?.env[MODEL_KEY_ENV]).toBe('sk-test-123');
    provider.clear();
    expect(provider.runtime()).toBeUndefined();
    expect(provider.dto().keyConfigured).toBe(false);
    store.close();
  });
});

describe('dshSpawnSpec with a Chives model runtime', () => {
  it('replaces the launcher overlay, routes default bots to it and passes the key by env', () => {
    const dataDir = tempDir();
    const registry = loadBots(join(repoRoot, 'apps/server/test/fixtures/bots'), buildCatalog(repoRoot));
    const expert = registry.get('expert') as BotManifest;
    const spec = dshSpawnSpec(expert, {
      dataDir,
      dshHome: '/tmp/dsh-home',
      modelOverlay: '/tmp/private-overlay.cordis.yml',
      personaText: 'persona',
      repoRoot,
      routes: { default: { provider: 'huosan', model: 'old' } },
      modelRuntime: {
        patchPath: '/tmp/model.patch.yml',
        route: { provider: 'chives', model: 'deepseek-v4.1-flash' },
        env: { [MODEL_KEY_ENV]: 'sk-x' },
      },
    });
    expect(spec.args).toContain('/tmp/model.patch.yml');
    expect(spec.args).not.toContain('/tmp/private-overlay.cordis.yml');
    expect(spec.env[MODEL_KEY_ENV]).toBe('sk-x');
    const generated = readFileSync(dshPatchPath(dataDir, 'expert'), 'utf8');
    expect(generated).toContain('provider: chives');
    expect(generated).toContain('model: deepseek-v4.1-flash');
    expect(generated).not.toContain('sk-x');
  });

  it('skips an empty overlay instead of passing a blank --patch', () => {
    const dataDir = tempDir();
    const registry = loadBots(join(repoRoot, 'apps/server/test/fixtures/bots'), buildCatalog(repoRoot));
    const expert = registry.get('expert') as BotManifest;
    const spec = dshSpawnSpec(expert, {
      dataDir,
      dshHome: '/tmp/dsh-home',
      modelOverlay: '',
      personaText: 'persona',
      repoRoot,
    });
    expect(spec.args.filter((arg) => arg === '--patch')).toHaveLength(1);
  });
});

describe('/api/settings/model-provider', () => {
  let app: ChivesApp | undefined;
  afterEach(async () => {
    if (app !== undefined) {
      await closeServer(app.server);
      await app.close();
      app = undefined;
    }
  });

  it('saves write-only, clears the stale default model and can be cleared', async () => {
    const directory = tempDir();
    app = createApp({ config: testConfig(directory), driver: new FakeDriver() });
    const baseUrl = await listen(app.server);
    const put = (body: unknown): Promise<Response> =>
      fetch(`${baseUrl}/api/settings/model-provider`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });

    const initial = (await (await fetch(`${baseUrl}/api/settings/model-provider`)).json()) as ModelProviderDto;
    expect(initial).toMatchObject({ model: 'deepseek-flash', active: false, keyConfigured: false });

    expect((await put({ ...FLASH, baseURL: 'nope' })).status).toBe(400);

    const saved = await put({ ...FLASH, apiKey: 'sk-live-should-not-echo' });
    expect(saved.status).toBe(200);
    const text = await saved.text();
    expect(text).not.toContain('sk-live-should-not-echo');
    expect(JSON.parse(text)).toMatchObject({ active: true, keyConfigured: true });

    const kept = (await (await put({ ...FLASH, apiKey: '' })).json()) as ModelProviderDto;
    expect(kept.keyConfigured).toBe(true);

    const cleared = (await (
      await fetch(`${baseUrl}/api/settings/model-provider`, { method: 'DELETE' })
    ).json()) as ModelProviderDto;
    expect(cleared).toMatchObject({ active: false, keyConfigured: false });
  });
});
