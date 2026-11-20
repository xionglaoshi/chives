/**
 * The model endpoint Chives configures for every bot: base URL, protocol, model id and API key.
 *
 * Non-secret fields live in the settings store. The key is kept in `<dataDir>/secrets/model.env`
 * (mode 0600), handed to dsh only as an environment variable and never returned to the web client.
 */

import { chmodSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import {CodexSubscription,codexBase} from './codex-subscription.js';
import { stringify } from 'yaml';

import type { ModelProviderDto } from '../api/protocol.js';
import type { Store } from '../store/index.js';

export const MODEL_PROVIDER_KEY = 'model_provider';
/** Route name Chives registers in dsh; bots reach it as `chives/<model>`. */
export const CHIVES_PROVIDER_ID = 'chives';
export const MODEL_KEY_ENV = 'CHIVES_MODEL_API_KEY';

export const MODEL_APIS = ['openai-completions', 'openai-responses', 'anthropic-messages','openai-codex-subscription'] as const;
export type ModelApi = (typeof MODEL_APIS)[number];
export type { ModelProviderDto };

export interface ModelProviderConfig {
  baseURL: string;
  api: ModelApi;
  model: string;
  /** Display name in model pickers; defaults to the model id. */
  displayName?: string;
  contextWindow?: number;
  maxTokens?: number;
  /** DeepSeek V4-style thinking switch over an OpenAI-compatible endpoint. */
  deepseekThinking: boolean;
}

export interface ModelRuntime {
  patchPath: string;
  route: { provider: string; model: string };
  env: Record<string, string>;
}

export const DEFAULT_MODEL_PROVIDER: ModelProviderConfig = {
  baseURL: 'https://api.deepseek.com/v1',
  api: 'openai-completions',
  model: 'deepseek-flash',
  deepseekThinking: true,
};

export class ModelProviderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ModelProviderError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function positiveInt(value: unknown, name: string): number | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  const number = typeof value === 'string' ? Number(value) : value;
  if (typeof number !== 'number' || !Number.isInteger(number) || number < 1) {
    throw new ModelProviderError(`${name} 必须是正整数`);
  }
  return number;
}

function checkBaseURL(raw: unknown): string {
  if (typeof raw !== 'string' || raw.trim() === '') throw new ModelProviderError('请填写 API 地址');
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    throw new ModelProviderError('API 地址必须是 http(s) 链接');
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    throw new ModelProviderError('API 地址必须是 http(s) 链接');
  }
  if (url.username !== '' || url.password !== '') {
    throw new ModelProviderError('API 地址里不要带账号密码，密钥请填在密钥栏');
  }
  return raw.trim().replace(/\/+$/, '');
}

/** Validates a client payload; unknown fields are rejected so typos do not silently vanish. */
export function parseModelProvider(raw: unknown): ModelProviderConfig {
  if (!isRecord(raw)) throw new ModelProviderError('配置必须是对象');
  const allowed = new Set([
    'baseURL',
    'api',
    'model',
    'displayName',
    'contextWindow',
    'maxTokens',
    'deepseekThinking',
  ]);
  for (const key of Object.keys(raw)) {
    if (!allowed.has(key)) throw new ModelProviderError(`未知字段 "${key}"`);
  }
  const api = raw['api'] ?? DEFAULT_MODEL_PROVIDER.api;
  if (!MODEL_APIS.includes(api as ModelApi)) {
    throw new ModelProviderError(`API 协议只能是 ${MODEL_APIS.join('、')}`);
  }
  const model = raw['model'];
  if (typeof model !== 'string' || model.trim() === '' || /\s/.test(model.trim())) {
    throw new ModelProviderError('请填写模型 ID（不能含空格）');
  }
  if(api==='openai-codex-subscription' && raw.baseURL!==codexBase)throw new ModelProviderError('订阅连接须使用 OpenAI 官方地址');
  const displayName = raw['displayName'];
  if (displayName !== undefined && displayName !== null && typeof displayName !== 'string') {
    throw new ModelProviderError('显示名称必须是文本');
  }
  const thinking = raw['deepseekThinking'] ?? DEFAULT_MODEL_PROVIDER.deepseekThinking;
  if (typeof thinking !== 'boolean') throw new ModelProviderError('deepseekThinking 必须是布尔值');
  const contextWindow = positiveInt(raw['contextWindow'], '上下文窗口');
  const maxTokens = positiveInt(raw['maxTokens'], '最大输出');
  return {
    baseURL: checkBaseURL(raw['baseURL']),
    api: api as ModelApi,
    model: model.trim(),
    ...(typeof displayName === 'string' && displayName.trim() !== ''
      ? { displayName: displayName.trim() }
      : {}),
    ...(contextWindow === undefined ? {} : { contextWindow }),
    ...(maxTokens === undefined ? {} : { maxTokens }),
    deepseekThinking: thinking,
  };
}

function keyFile(dataDir: string): string {
  return join(dataDir, 'secrets', 'model.env');
}

export function modelPatchPath(dataDir: string): string {
  return join(dataDir, 'harness', 'dsh', 'model.patch.yml');
}

/** dsh `llm-pi-ai` patch for the configured route; the key is referenced by env name only. */
export function buildModelPatch(config: ModelProviderConfig): string {
  if(config.api==='openai-codex-subscription')return stringify([{id:'llm-pi-ai',config:{providers:{'openai-codex':{models:[{id:config.model}]}}}}]);
  const model: Record<string, unknown> = { id: config.model };
  if (config.displayName !== undefined) model['name'] = config.displayName;
  if (config.contextWindow !== undefined) model['contextWindow'] = config.contextWindow;
  if (config.maxTokens !== undefined) model['maxTokens'] = config.maxTokens;
  if (config.deepseekThinking && config.api === 'openai-completions') {
    model['compat'] = { thinkingFormat: 'deepseek' };
    model['reasoningEfforts'] = { off: null, high: 'high', max: 'max' };
  }
  const provider: Record<string, unknown> = {
    displayName: config.displayName ?? config.model,
    apiKeyEnv: MODEL_KEY_ENV,
    api: config.api,
    baseURL: config.baseURL,
    models: [model],
  };
  return stringify([{ id: 'llm-pi-ai', config: { providers: { [CHIVES_PROVIDER_ID]: provider } } }], {
    lineWidth: 0,
  });
}

export class ModelProviderStore {
  readonly subscription:CodexSubscription;
  constructor(
    private readonly store: Store,
    private readonly dataDir: string,
    home?:string,
  ) {this.subscription=new CodexSubscription(dataDir,home);}

  read(): ModelProviderConfig | null {
    const raw = this.store.settings.get(MODEL_PROVIDER_KEY);
    if (raw === undefined || raw === null) return null;
    try {
      return parseModelProvider(raw);
    } catch {
      return null;
    }
  }

  keyConfigured(): boolean {
    return this.currentKey() !== '';
  }

  dto(): ModelProviderDto {
    const saved = this.read();
    const keyConfigured = this.keyConfigured();
    return {
      ...(saved ?? DEFAULT_MODEL_PROVIDER),
      keyConfigured,
      active: saved !== null && (keyConfigured || saved.api==='openai-codex-subscription'),
    };
  }

  /** `apiKey`: a string replaces the saved key, `null` deletes it, `undefined` keeps it. */
  write(config: ModelProviderConfig, apiKey: string | null | undefined): ModelProviderDto {
    if(config.api==='openai-codex-subscription')apiKey=null;
    if (apiKey !== undefined && apiKey !== null) {
      const key = apiKey.trim();
      if (key === '' || /[\r\n]/.test(key)) throw new ModelProviderError('密钥不能为空或换行');
      this.writeKey(key);
    } else if (apiKey === null) {
      rmSync(keyFile(this.dataDir), { force: true });
    }
    this.store.settings.set(MODEL_PROVIDER_KEY, config);
    return this.dto();
  }

  clear(): ModelProviderDto {
    this.store.settings.delete(MODEL_PROVIDER_KEY);
    rmSync(keyFile(this.dataDir), { force: true });
    rmSync(modelPatchPath(this.dataDir), { force: true });
    return this.dto();
  }

  /** What a newly spawned dsh process should use, or `undefined` to keep the launcher's overlay. */
  runtime(override?: string, botId?: string): ModelRuntime | undefined {
    const config = this.read();
    const key = this.currentKey();
    if (config === null || (key === '' && config.api!=='openai-codex-subscription')) return undefined;
    return this.runtimeFor({...config,model:override || config.model},key,botId);
  }

  runtimeFor(config:ModelProviderConfig,key:string,botId?:string): ModelRuntime {
    const patchPath = botId ? join(this.dataDir, "harness", "dsh", botId + ".model.yml") : modelPatchPath(this.dataDir);
    mkdirSync(join(this.dataDir, 'harness', 'dsh'), { recursive: true });
    writeFileSync(patchPath, buildModelPatch(config), 'utf8');
    return {
      patchPath,
      route: { provider: config.api==='openai-codex-subscription'?'openai-codex':CHIVES_PROVIDER_ID, model: config.model },
      env: config.api==='openai-codex-subscription'?{}:{ [MODEL_KEY_ENV]: key },
    };
  }

  async validateModel(model: string): Promise<void> {
    const endpoint = this.read()?.baseURL;
    if (!endpoint) throw new Error('模型服务未配置');
    const res = await fetch(endpoint + '/models', {
      headers: {Authorization: 'Bearer ' + this.currentKey()}, signal: AbortSignal.timeout(10000), redirect: 'error',
    });
    if (!res.ok) throw new Error('模型列表不可用');
    const list = await res.json() as {data?: {id: string}[]};
    if (!list.data?.some(item => item.id === model)) throw new Error('无此模型');
  }

  currentKey(): string {
    const path = keyFile(this.dataDir);
    if (!existsSync(path)) return '';
    try {
      const data = readFileSync(path, 'utf8');
      const match = /^CHIVES_MODEL_API_KEY=(.*)$/m.exec(data);
      return (match?.[1] ?? '').trim();
    } catch {
      return '';
    }
  }

  private writeKey(key: string): void {
    const dir = join(this.dataDir, 'secrets');
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    const path = keyFile(this.dataDir);
    writeFileSync(path, `${MODEL_KEY_ENV}=${key}\n`, { encoding: 'utf8', mode: 0o600 });
    chmodSync(path, 0o600);
  }
}
