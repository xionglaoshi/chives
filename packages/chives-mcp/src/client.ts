/** Thin HTTP client for Chives Server's internal delegation API. */

export const DEFAULT_REQUEST_TIMEOUT_MS = 44_000;

export interface ChivesClientOptions {
  api: string;
  token: string;
  /** Hard ceiling for one HTTP round trip; must stay below dsh's 60 s MCP timeout. */
  requestTimeoutMs?: number;
  fetchImpl?: typeof fetch;
}

export interface ChivesErrorResult {
  error: string;
  message: string;
}

export function isErrorResult(value: unknown): value is ChivesErrorResult {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { error?: unknown }).error === 'string' &&
    (value as { error: string }).error !== ''
  );
}

function errorResult(error: string, message: string): ChivesErrorResult {
  return { error, message };
}

function parseBody(text: string): unknown {
  if (text === '') return {};
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return { error: 'invalid_response', message: text.slice(0, 500) };
  }
}

export class ChivesClient {
  readonly api: string;
  private readonly token: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(options: ChivesClientOptions) {
    this.api = options.api.replace(/\/+$/, '');
    this.token = options.token;
    this.timeoutMs = options.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  async post(path: string, body: Record<string, unknown>): Promise<unknown> {
    if (this.api === '') return errorResult('missing_api', 'CHIVES_API is not set');
    if (this.token === '') return errorResult('missing_token', 'CHIVES_SESSION_TOKEN is not set');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetchImpl(`${this.api}${path}`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          accept: 'application/json',
          authorization: `Bearer ${this.token}`,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      const text = await response.text();
      const parsed = parseBody(text);
      if (!response.ok) {
        if (isErrorResult(parsed)) return parsed;
        const nested = (parsed as { error?: { code?: unknown; message?: unknown } }).error;
        if (typeof nested === 'object' && nested !== null && typeof nested.code === 'string') {
          return errorResult(
            nested.code,
            typeof nested.message === 'string'
              ? nested.message
              : `Chives Server returned HTTP ${response.status}`,
          );
        }
        return errorResult(`http_${response.status}`, `Chives Server returned HTTP ${response.status}`);
      }
      return parsed;
    } catch (error) {
      if (controller.signal.aborted) {
        return errorResult('timeout', `Chives Server did not answer within ${this.timeoutMs} ms`);
      }
      const message = error instanceof Error ? error.message : String(error);
      return errorResult('unreachable', `Chives Server is unreachable: ${message}`);
    } finally {
      clearTimeout(timer);
    }
  }

  delegate(
    bot: string,
    brief: string,
    waitSeconds: number,
    reportBack = true,
    timeoutMinutes?: number,
  ): Promise<unknown> {
    return this.post('/api/internal/delegations', {
      bot,
      brief,
      wait_seconds: waitSeconds,
      report_back: reportBack,
      ...(timeoutMinutes === undefined ? {} : { timeout_minutes: timeoutMinutes }),
    });
  }

  delegateWait(ids: readonly string[], mode: 'any' | 'all', waitSeconds: number): Promise<unknown> {
    return this.post('/api/internal/delegations/wait', {
      ids: [...ids],
      mode,
      wait_seconds: waitSeconds,
    });
  }

  timelineSearch(
    query: string,
    options: { limit?: number; taskId?: string } = {},
  ): Promise<unknown> {
    return this.post('/api/internal/timeline/search', {
      query,
      ...(options.limit === undefined ? {} : { limit: options.limit }),
      ...(options.taskId === undefined ? {} : { task_id: options.taskId }),
    });
  }

  memoryRead(topic?: string): Promise<unknown> {
    return this.post('/api/internal/memory/read', topic === undefined ? {} : { topic });
  }

  routineCreate(input: {
    title: string;
    schedule: Record<string, unknown>;
    prompt: string;
    tradingDaysOnly?: boolean;
  }): Promise<unknown> {
    return this.post('/api/internal/routines/create', {
      title: input.title,
      schedule: input.schedule,
      prompt: input.prompt,
      ...(input.tradingDaysOnly === undefined ? {} : { trading_days_only: input.tradingDaysOnly }),
    });
  }

  routineList(): Promise<unknown> {
    return this.post('/api/internal/routines/list', {});
  }

  routineDelete(id: string): Promise<unknown> {
    return this.post('/api/internal/routines/delete', { id });
  }

  watchPlanCreate(input: {
    code: string;
    label: string;
    when: Record<string, unknown>[];
    match?: string;
    giveUp?: Record<string, unknown>[];
    market?: Record<string, unknown>[];
    expiresInDays?: number;
    note?: string;
    repeat?: boolean;
  }): Promise<unknown> {
    return this.post('/api/internal/watch-plans/create', {
      code: input.code,
      label: input.label,
      when: input.when,
      ...(input.match === undefined ? {} : { match: input.match }),
      ...(input.giveUp === undefined ? {} : { give_up: input.giveUp }),
      ...(input.market === undefined ? {} : { market: input.market }),
      ...(input.expiresInDays === undefined ? {} : { expires_in_days: input.expiresInDays }),
      ...(input.note === undefined ? {} : { note: input.note }),
      ...(input.repeat === undefined ? {} : { repeat: input.repeat }),
    });
  }

  watchPlanUpdate(input: {
    id: string;
    code?: string;
    label?: string;
    when?: Record<string, unknown>[];
    match?: string;
    giveUp?: Record<string, unknown>[];
    market?: Record<string, unknown>[];
    expiresInDays?: number;
    note?: string;
    repeat?: boolean;
  }): Promise<unknown> {
    return this.post('/api/internal/watch-plans/update', {
      id: input.id,
      ...(input.code === undefined ? {} : { code: input.code }),
      ...(input.label === undefined ? {} : { label: input.label }),
      ...(input.when === undefined ? {} : { when: input.when }),
      ...(input.match === undefined ? {} : { match: input.match }),
      ...(input.giveUp === undefined ? {} : { give_up: input.giveUp }),
      ...(input.market === undefined ? {} : { market: input.market }),
      ...(input.expiresInDays === undefined ? {} : { expires_in_days: input.expiresInDays }),
      ...(input.note === undefined ? {} : { note: input.note }),
      ...(input.repeat === undefined ? {} : { repeat: input.repeat }),
    });
  }

  watchPlanDelete(id: string): Promise<unknown> {
    return this.post('/api/internal/watch-plans/delete', { id });
  }

  watchPlanList(status: 'active' | 'all'): Promise<unknown> {
    return this.post('/api/internal/watch-plans/list', { status });
  }

  notifyUser(input: {
    title: string;
    body: string;
    level: 'info' | 'important' | 'urgent';
  }): Promise<unknown> {
    return this.post('/api/internal/notifications/notify', input);
  }

  memoryWrite(input: {
    title: string;
    body: string;
    kind: string;
    evidence: string;
    expiresInDays?: number;
  }): Promise<unknown> {
    return this.post('/api/internal/memory/write', {
      title: input.title,
      body: input.body,
      kind: input.kind,
      evidence: input.evidence,
      ...(input.expiresInDays === undefined ? {} : { expires_in_days: input.expiresInDays }),
    });
  }
}
