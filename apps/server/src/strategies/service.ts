/** `GET /api/strategies/:id/pools`: server-side proxy to the loopback strategy-hub. */

export interface StrategyPoolsResult {
  status: number;
  body: unknown;
}

export interface StrategyServiceOptions {
  baseUrl: string;
  fetchImpl?: typeof fetch;
  now?: () => number;
  ttlMs?: number;
  timeoutMs?: number;
}

const DEFAULT_TTL_MS = 60_000;
const DEFAULT_TIMEOUT_MS = 10_000;

function failure(message: string): StrategyPoolsResult {
  return { status: 503, body: { error: { code: 'strategy_unavailable', message } } };
}

export class StrategyService {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;
  private readonly now: () => number;
  private readonly ttlMs: number;
  private readonly timeoutMs: number;
  private readonly cache = new Map<string, { expiresAt: number; result: StrategyPoolsResult }>();
  private readonly pending = new Map<string, Promise<StrategyPoolsResult>>();

  constructor(options: StrategyServiceOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.fetchImpl = options.fetchImpl ?? fetch;
    this.now = options.now ?? (() => Date.now());
    this.ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  }

  async pools(strategyId: string, date?: string): Promise<StrategyPoolsResult> {
    const key = `${strategyId}|${date ?? ''}`;
    const cached = this.cache.get(key);
    if (cached !== undefined && this.now() < cached.expiresAt) return cached.result;
    const inFlight = this.pending.get(key);
    if (inFlight !== undefined) return inFlight;
    const load = this.fetchPools(strategyId, date)
      .then((result) => {
        if (result.status === 200) {
          this.cache.set(key, { expiresAt: this.now() + this.ttlMs, result });
        }
        return result;
      })
      .finally(() => {
        this.pending.delete(key);
      });
    this.pending.set(key, load);
    return load;
  }

  private async fetchPools(strategyId: string, date?: string): Promise<StrategyPoolsResult> {
    const query = date === undefined || date === '' ? '' : `?date=${encodeURIComponent(date)}`;
    const url = `${this.baseUrl}/v1/${encodeURIComponent(strategyId)}/pools${query}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetchImpl(url, {
        method: 'GET',
        headers: { accept: 'application/json' },
        signal: controller.signal,
      });
      let body: unknown;
      try {
        body = await response.json();
      } catch {
        return failure('策略服务返回了无法识别的内容');
      }
      if (!response.ok) {
        if (typeof body === 'object' && body !== null) {
          return { status: response.status, body };
        }
        return failure(`策略服务返回 HTTP ${response.status}`);
      }
      return { status: 200, body };
    } catch {
      return failure('策略服务没有启动，请确认 strategy-hub 正在运行（127.0.0.1:8869）');
    } finally {
      clearTimeout(timer);
    }
  }
}
