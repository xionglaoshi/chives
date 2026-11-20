/** MCP client for the profile service; the server never reads profile files directly. */

import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { getDefaultEnvironment, StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

import { loadOverlayMcpConfigs } from '../harness/overlays.js';

const CONNECT_TIMEOUT_MS = 5_000;
const CALL_TIMEOUT_MS = 5_000;

export interface ProfileServerConfig {
  command: string;
  args: string[];
  cwd?: string;
  env: Record<string, string>;
}

export interface ProfileSnapshot {
  available: boolean;
  fields: Record<string, unknown>;
  timestamps: Record<string, string>;
  updatedAt: string | null;
  error: string | null;
}

export class ProfileUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProfileUnavailableError';
  }
}

export class ProfileToolError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'ProfileToolError';
    this.code = code;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asStringMap(value: unknown): Record<string, string> {
  if (!isRecord(value)) return {};
  const mapped: Record<string, string> = {};
  for (const [key, entry] of Object.entries(value)) {
    if (typeof entry === 'string') mapped[key] = entry;
  }
  return mapped;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, message: string): Promise<T> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new ProfileUnavailableError(message));
    }, timeoutMs);
    timer.unref();
    promise.then(
      (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function envelopeFromContent(content: unknown): Record<string, unknown> {
  if (!Array.isArray(content)) {
    throw new ProfileUnavailableError('profile 服务返回了无法解析的结果');
  }
  for (const block of content) {
    if (!isRecord(block) || block['type'] !== 'text' || typeof block['text'] !== 'string') continue;
    try {
      const parsed: unknown = JSON.parse(block['text']);
      if (isRecord(parsed)) return parsed;
    } catch {
      // Try the next text block.
    }
  }
  throw new ProfileUnavailableError('profile 服务返回了无法解析的结果');
}

function snapshotFromData(data: unknown, available: boolean): ProfileSnapshot {
  const record = isRecord(data) ? data : {};
  const rawFields = isRecord(record['fields'])
    ? record['fields']
    : isRecord(record['after'])
      ? record['after']
      : {};
  return {
    available,
    fields: rawFields,
    timestamps: asStringMap(record['timestamps']),
    updatedAt: typeof record['updated_at'] === 'string' ? record['updated_at'] : null,
    error: null,
  };
}

/**
 * Spawns the stdio profile MCP server lazily and keeps one connection for the
 * server lifetime. Any transport failure marks it unavailable and drops the
 * client so the next request retries a fresh process.
 */
export class ProfileMcpClient {
  private client: Client | undefined;
  private connecting: Promise<Client> | undefined;

  constructor(
    private readonly config: ProfileServerConfig | null,
    private readonly configError: string | null = null,
  ) {}

  async get(): Promise<ProfileSnapshot> {
    try {
      const payload = await this.call('profile_get', {});
      return snapshotFromData(payload['data'], true);
    } catch (error) {
      if (error instanceof ProfileUnavailableError) {
        return {
          available: false,
          fields: {},
          timestamps: {},
          updatedAt: null,
          error: error.message,
        };
      }
      throw error;
    }
  }

  async update(fields: Record<string, unknown>): Promise<ProfileSnapshot> {
    const payload = await this.call('profile_update', { fields });
    this.throwToolError(payload);
    return snapshotFromData(payload['data'], true);
  }

  async clear(fields: readonly string[]): Promise<ProfileSnapshot> {
    const payload = await this.call('profile_clear', { fields: [...fields] });
    this.throwToolError(payload);
    return snapshotFromData(payload['data'], true);
  }

  async close(): Promise<void> {
    await this.reset();
  }

  private throwToolError(payload: Record<string, unknown>): void {
    if (payload['ok'] === true) return;
    const error = isRecord(payload['error']) ? payload['error'] : {};
    throw new ProfileToolError(
      asText(error['code']) || 'profile_error',
      asText(error['message']) || '画像服务拒绝了这次修改',
    );
  }

  private async ensureClient(): Promise<Client> {
    if (this.client !== undefined) return this.client;
    if (this.connecting !== undefined) return this.connecting;
    this.connecting = this.connect().finally(() => {
      this.connecting = undefined;
    });
    return this.connecting;
  }

  private async connect(): Promise<Client> {
    if (this.config === null) {
      throw new ProfileUnavailableError(this.configError ?? '画像服务不可用');
    }
    const client = new Client({ name: 'chives-server', version: '0.0.0' });
    const transport = new StdioClientTransport({
      command: this.config.command,
      args: this.config.args,
      env: this.config.env,
      ...(this.config.cwd === undefined ? {} : { cwd: this.config.cwd }),
    });
    try {
      await withTimeout(
        client.connect(transport),
        CONNECT_TIMEOUT_MS,
        '画像服务没有在 5 秒内启动',
      );
      this.client = client;
      return client;
    } catch (error) {
      await client.close().catch(() => undefined);
      throw error instanceof ProfileUnavailableError
        ? error
        : new ProfileUnavailableError(`画像服务启动失败：${errorMessage(error)}`);
    }
  }

  private async call(
    name: string,
    args: Record<string, unknown>,
  ): Promise<Record<string, unknown>> {
    const client = await this.ensureClient();
    try {
      const result = await withTimeout(
        client.callTool({ name, arguments: args }),
        CALL_TIMEOUT_MS,
        '画像服务没有在 5 秒内响应',
      );
      return envelopeFromContent(result.content);
    } catch (error) {
      await this.reset();
      throw error instanceof ProfileUnavailableError
        ? error
        : new ProfileUnavailableError(`画像服务调用失败：${errorMessage(error)}`);
    }
  }

  private async reset(): Promise<void> {
    const current = this.client;
    this.client = undefined;
    if (current === undefined) return;
    await current.close().catch(() => undefined);
  }
}

export interface ResolvedProfileServer {
  config: ProfileServerConfig | null;
  error: string | null;
}

/**
 * Reads the command, args and cwd from `overlays/profile.cordis.yml`. The
 * overlay's `env` is deliberately not copied: only DSH_HOME from the server
 * configuration is passed to the child.
 */
export function resolveProfileServer(repoRoot: string, dshHome: string): ResolvedProfileServer {
  try {
    const loaded = loadOverlayMcpConfigs(repoRoot);
    const config = loaded.byServer.get('profile');
    if (config === undefined) {
      return { config: null, error: '没有找到 overlays/profile.cordis.yml 里的 profile 服务' };
    }
    const env = getDefaultEnvironment();
    if (dshHome !== '') env['DSH_HOME'] = dshHome;
    return {
      config: {
        command: config.command,
        args: [...config.args],
        ...(config.cwd === undefined ? {} : { cwd: config.cwd }),
        env,
      },
      error: null,
    };
  } catch (error) {
    return { config: null, error: `画像服务配置读取失败：${errorMessage(error)}` };
  }
}
