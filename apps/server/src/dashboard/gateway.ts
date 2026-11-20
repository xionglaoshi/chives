/** Minimal client for the cn-market-gateway `POST /v1/call` endpoint. */

export type GatewayStatus = 'ok' | 'partial' | 'unavailable';

export interface GatewayEnvelope<T> {
  status: GatewayStatus;
  as_of: string;
  data: T;
  stale?: boolean;
  message?: string;
  missing?: Array<{ field: string; reason: string }>;
}

export class GatewayError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GatewayError';
  }
}

export interface GatewayOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

const DEFAULT_TIMEOUT_MS = 12_000;

export async function callGateway<T>(
  options: GatewayOptions,
  tool: string,
  args: Record<string, unknown>,
): Promise<GatewayEnvelope<T>> {
  const doFetch = options.fetchImpl ?? fetch;
  const url = `${options.baseUrl.replace(/\/+$/, '')}/v1/call`;
  let response: Response;
  try {
    response = await doFetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ tool, args }),
      signal: AbortSignal.timeout(options.timeoutMs ?? DEFAULT_TIMEOUT_MS),
    });
  } catch {
    throw new GatewayError('行情网关连不上，请确认 cn-market-gateway 正在运行');
  }
  if (!response.ok) {
    throw new GatewayError(`行情网关返回 HTTP ${response.status}`);
  }
  let payload: unknown;
  try {
    payload = (await response.json()) as unknown;
  } catch {
    throw new GatewayError('行情网关返回的不是 JSON');
  }
  if (typeof payload !== 'object' || payload === null) {
    throw new GatewayError('行情网关返回格式不对');
  }
  const envelope = payload as Partial<GatewayEnvelope<T>>;
  if (envelope.status === 'unavailable') {
    const message = typeof envelope.message === 'string' ? envelope.message : '行情服务暂时不可用';
    throw new GatewayError(message);
  }
  if (envelope.status !== 'ok' && envelope.status !== 'partial') {
    throw new GatewayError('行情网关返回状态未知');
  }
  return {
    status: envelope.status,
    as_of: typeof envelope.as_of === 'string' ? envelope.as_of : new Date().toISOString(),
    data: envelope.data as T,
    ...(typeof envelope.stale === 'boolean' ? { stale: envelope.stale } : {}),
    ...(typeof envelope.message === 'string' ? { message: envelope.message } : {}),
    ...(Array.isArray(envelope.missing) ? { missing: envelope.missing } : {}),
  };
}
