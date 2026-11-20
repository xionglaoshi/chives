/** Minimal HTTP client for cn-watch's plan endpoints. Never writes rules or watchlists. */

import type { JsonRecord } from '../store/index.js';

export const WATCH_ENGINE_TIMEOUT_MS = 5_000;

export interface EnginePlanState {
  id: string;
  code: string;
  label: string;
  state: string;
  since: string;
  last_price: number | null;
  expires_at: string | null;
  active: boolean;
}

export type EngineUpsertResult =
  | { ok: true; status: string }
  | { ok: false; unreachable: true; message: string }
  | { ok: false; unreachable: false; code: string; message: string; field: string | null };

export type EngineRemoveResult =
  | { ok: true; removed: boolean }
  | { ok: false; unreachable: true; message: string }
  | { ok: false; unreachable: false; code: string; message: string };

export type EngineListResult =
  | { ok: true; plans: EnginePlanState[] }
  | { ok: false; unreachable: true; message: string };

export interface CnWatchClientOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function errorText(body: unknown, fallback: string): { code: string; message: string; field: string | null } {
  if (isRecord(body)) {
    return {
      code: typeof body['code'] === 'string' ? body['code'] : 'engine_rejected',
      message: typeof body['message'] === 'string' ? body['message'] : fallback,
      field: typeof body['field'] === 'string' ? body['field'] : null,
    };
  }
  return { code: 'engine_rejected', message: fallback, field: null };
}

function toPlanState(value: unknown): EnginePlanState | null {
  if (!isRecord(value) || typeof value['id'] !== 'string') return null;
  return {
    id: value['id'],
    code: typeof value['code'] === 'string' ? value['code'] : '',
    label: typeof value['label'] === 'string' ? value['label'] : '',
    state: typeof value['state'] === 'string' ? value['state'] : 'unknown',
    since: typeof value['since'] === 'string' ? value['since'] : '',
    last_price: typeof value['last_price'] === 'number' ? value['last_price'] : null,
    expires_at: typeof value['expires_at'] === 'string' ? value['expires_at'] : null,
    active: value['active'] !== false,
  };
}

export class CnWatchClient {
  readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(options: CnWatchClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.timeoutMs = options.timeoutMs ?? WATCH_ENGINE_TIMEOUT_MS;
  }

  private async request(path: string, init: RequestInit): Promise<Response | null> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    timer.unref?.();
    try {
      return await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        headers: { accept: 'application/json', ...(init.body === undefined ? {} : { 'content-type': 'application/json' }) },
        signal: controller.signal,
      });
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  async upsert(plan: JsonRecord): Promise<EngineUpsertResult> {
    const response = await this.request('/plans/upsert', {
      method: 'POST',
      body: JSON.stringify(plan),
    });
    if (response === null) return { ok: false, unreachable: true, message: '盯盘引擎没有响应' };
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (response.ok) {
      return { ok: true, status: isRecord(body) && typeof body['status'] === 'string' ? body['status'] : 'ok' };
    }
    const error = errorText(body, `盯盘引擎返回 HTTP ${response.status}`);
    return { ok: false, unreachable: false, code: error.code, message: error.message, field: error.field };
  }

  async remove(id: string): Promise<EngineRemoveResult> {
    const response = await this.request('/plans/remove', {
      method: 'POST',
      body: JSON.stringify({ id }),
    });
    if (response === null) return { ok: false, unreachable: true, message: '盯盘引擎没有响应' };
    if (response.ok) return { ok: true, removed: true };
    if (response.status === 404) return { ok: true, removed: false };
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    const error = errorText(body, `盯盘引擎返回 HTTP ${response.status}`);
    return { ok: false, unreachable: false, code: error.code, message: error.message };
  }

  async list(): Promise<EngineListResult> {
    const response = await this.request('/plans', { method: 'GET' });
    if (response === null) return { ok: false, unreachable: true, message: '盯盘引擎没有响应' };
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (!response.ok || !isRecord(body) || !Array.isArray(body['plans'])) {
      return {
        ok: false,
        unreachable: true,
        message: `盯盘引擎返回异常（HTTP ${response.status}）`,
      };
    }
    const plans: EnginePlanState[] = [];
    for (const entry of body['plans']) {
      const state = toPlanState(entry);
      if (state !== null) plans.push(state);
    }
    return { ok: true, plans };
  }
}
